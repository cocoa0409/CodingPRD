"""Rights shares, the share-change audit ledger, and the
dispute-posture / FROZEN gate on share termination (PRD §3.3, §2.9,
§2.10 priority 7)."""
from __future__ import annotations
import pytest

from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    assert_rights_share,
    assert_share_change_audit,
    create_rights_holder,
    create_share,
    create_work_draft,
    find_audit_by_kind,
    make_rights_holder_headers,
    open_dispute,
    patch_share_payload,
    setup_approved_recording_work,
    submit_work,
    take_review,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestShareCreation:

    def test_share_creation_emits_created_audit(self, api):
        """PRD §3.1: 'Creating a share emits a ShareChangeAudit row with
        change_kind of CREATED and an after_snapshot capturing the
        initial {share_percent, share_status, agency_binding_id} triple
        (the before_snapshot is null on creation).'

        Claim: POST /royalty/works/{id}/shares → 201 with audit ledger
        containing a row whose change_kind == CREATED and
        before_snapshot is null.
        """
        h = create_rights_holder()
        w = create_work_draft(h["id"])
        s = create_share(w["id"], h["id"], h["id"], 100.00)
        # Read audit.
        resp = api.list_share_audit(
            w["id"], s["id"], make_rights_holder_headers(h["id"]),
            params={"limit": 100},
        )
        audits, _ = validate_paginated(resp)
        created = find_audit_by_kind(audits, "CREATED")
        assert len(created) == 1
        assert_share_change_audit(created[0])
        assert created[0].get("before_snapshot") is None

    def test_share_audit_row_is_append_only_shape(self, api):
        """PRD §2.4: 'four scaffold entities are deliberately leaner —
        ShareChangeAudit, PlaybackEvent, DistributionRuleVersion, and
        ExternalSyncEvent — these carry only id and created_at; both
        updated_at and version are absent on them.'

        Claim: audit row response shape has id + created_at but no
        version and no updated_at.
        """
        h = create_rights_holder()
        w = create_work_draft(h["id"])
        s = create_share(w["id"], h["id"], h["id"], 100.00)
        resp = api.list_share_audit(
            w["id"], s["id"], make_rights_holder_headers(h["id"]),
            params={"limit": 100},
        )
        audits, _ = validate_paginated(resp)
        assert len(audits) >= 1
        row = audits[0]
        assert "id" in row
        assert "created_at" in row
        # PRD §2.4 explicitly says the leaner shape OMITS updated_at and version.
        assert "updated_at" not in row or row.get("updated_at") is None
        assert "version" not in row or row.get("version") is None


class TestShareUpdate:

    def test_percent_update_emits_percent_updated_audit(self, api):
        """PRD §3.3: 'A share update may target one or more of three
        writable attributes: share_percent (re-allocating the holder's
        fraction of the work), agency_binding_id (rebinding to a
        different agency or unbinding entirely), and share_status...
        Each update kind writes a ShareChangeAudit row with the
        corresponding change_kind — PERCENT_UPDATED, AGENCY_REBOUND,
        STATUS_TRANSITION, or TERMINATED.'

        Claim: PATCH share with new share_percent → 200 + audit row with
        change_kind == PERCENT_UPDATED.
        """
        h = create_rights_holder()
        w = create_work_draft(h["id"])
        s = create_share(w["id"], h["id"], h["id"], 50.00)
        # Add a second share so the work passes future approval; not
        # required for the PATCH test itself.
        h2 = create_rights_holder()
        create_share(w["id"], h["id"], h2["id"], 50.00)
        # PATCH the first share's percent.
        resp = api.patch_share(
            w["id"], s["id"], patch_share_payload(share_percent=40.00),
            make_rights_holder_headers(h["id"]),
        )
        validate_success(resp, 200)
        audit_resp = api.list_share_audit(
            w["id"], s["id"], make_rights_holder_headers(h["id"]),
            params={"limit": 100},
        )
        audits, _ = validate_paginated(audit_resp)
        pct = find_audit_by_kind(audits, "PERCENT_UPDATED")
        assert len(pct) >= 1

    def test_termination_emits_terminated_audit(self, api):
        """PRD §3.3: 'A share's share_status lifecycle is ACTIVE →
        DISPUTED ... → TERMINATED, with ACTIVE → TERMINATED as the
        direct termination path... Each update kind writes a
        ShareChangeAudit row with the corresponding change_kind —
        PERCENT_UPDATED, AGENCY_REBOUND, STATUS_TRANSITION, or
        TERMINATED.'

        Claim: PATCH share to share_status=TERMINATED on a CLEAR-posture
        work → audit row with change_kind == TERMINATED.
        """
        # Work needs to remain CLEAR; setup gives us approved + CLEAR.
        h, work, share = setup_approved_recording_work()
        # Now terminate via PATCH.
        resp = api.patch_share(
            work["id"], share["id"],
            patch_share_payload(share_status="TERMINATED"),
            make_rights_holder_headers(h["id"]),
        )
        validate_success(resp, 200)
        audit_resp = api.list_share_audit(
            work["id"], share["id"], make_rights_holder_headers(h["id"]),
            params={"limit": 100},
        )
        audits, _ = validate_paginated(audit_resp)
        term = find_audit_by_kind(audits, "TERMINATED")
        assert len(term) >= 1


class TestFrozenWorkBlocksTerminate:

    def test_holder_terminate_blocked_when_dispute_posture_frozen(self, api):
        """PRD §3.3 / §2.10 priority 7: 'Holder-initiated termination of
        a share is blocked while the parent work's dispute_posture is
        FROZEN; an attempt is rejected with ERR_WORK_FROZEN.'

        Claim: After opening a dispute on the work (posture FROZEN),
        PATCH share share_status=TERMINATED via the holder →
        ERR_WORK_FROZEN (409).
        """
        h, work, share = setup_approved_recording_work()
        # Open a dispute → posture FROZEN.
        open_dispute(work["id"], h["id"], dispute_kind="OWNERSHIP")
        # Attempt termination by the owner — must be blocked.
        resp = api.patch_share(
            work["id"], share["id"],
            patch_share_payload(share_status="TERMINATED"),
            make_rights_holder_headers(h["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_WORK_FROZEN.value, 409)


class TestShareNotFound:

    def test_share_not_found_under_existing_work(self, api):
        """PRD §2.5: 'the platform first resolves the outer id (in the
        example, the Work), and only after confirming the parent exists
        does it resolve the inner share_id (the RightsShare) and verify
        that the share actually belongs to the parent work. Any failure
        along this chain returns ERR_NOT_FOUND (HTTP 404) keyed to the
        first segment that fails.'

        Claim: PATCH /royalty/works/{existing}/shares/{unknown} →
        ERR_NOT_FOUND (404).
        """
        h, work, _share = setup_approved_recording_work()
        resp = api.patch_share(
            work["id"], NON_EXISTENT_UUID,
            patch_share_payload(share_percent=42.00),
            make_rights_holder_headers(h["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value, 404)
