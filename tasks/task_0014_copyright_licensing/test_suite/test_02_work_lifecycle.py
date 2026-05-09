"""Work creation, ownership shares, submission, and registration
(PRD §3.1, §3.2)."""
import pytest

from test_helpers import (
    validate_success,
    validate_error,
    ApiErrorId,
    create_rights_holder,
    create_two_rights_holders,
    create_draft_work,
    submit_work,
    approve_work_registration,
    reject_work_registration,
    create_registered_work,
    create_work_payload,
    patch_work_payload,
    emit_event_payload,
    list_rights_chain_events,
    list_audit_logs_filtered,
    assert_work,
    assert_rights_chain_event,
    assert_ownership_shares_total,
    make_rights_holder_headers,
    ADMIN_HEADERS,
    unique_doc_id,
    unique_event_id,
)


# ---------------------------------------------------------------------------
# Work creation: ownership share validation
# ---------------------------------------------------------------------------

class TestOwnershipShares:
    """PRD §3.1: "the sum of primary_share_bps and every share_bps in
    co_owners must equal exactly 10000 basis points; every individual
    share_bps must be strictly greater than zero and at most 10000; and no
    rights_holder_id may appear more than once in co_owners."
    """

    def test_create_work_shares_sum_below_10000_rejected(self, api):
        """PRD §3.1: sum != 10000 -> ERR_OWNERSHIP_SHARES_INVALID."""
        rh_a, rh_b = create_two_rights_holders(api)
        headers = make_rights_holder_headers(rh_a["id"])
        payload = create_work_payload(
            primary_owner_id=rh_a["id"],
            primary_share_bps=5000,
            co_owners=[{"rights_holder_id": rh_b["id"], "share_bps": 4000}],
        )
        resp = api.create_work(payload, headers)
        validate_error(resp, ApiErrorId.ERR_OWNERSHIP_SHARES_INVALID.value)

    def test_create_work_shares_sum_above_10000_rejected(self, api):
        """PRD §3.1: sum > 10000 -> ERR_OWNERSHIP_SHARES_INVALID."""
        rh_a, rh_b = create_two_rights_holders(api)
        headers = make_rights_holder_headers(rh_a["id"])
        payload = create_work_payload(
            primary_owner_id=rh_a["id"],
            primary_share_bps=8000,
            co_owners=[{"rights_holder_id": rh_b["id"], "share_bps": 3000}],
        )
        resp = api.create_work(payload, headers)
        validate_error(resp, ApiErrorId.ERR_OWNERSHIP_SHARES_INVALID.value)

    def test_create_work_zero_share_rejected(self, api):
        """PRD §3.1: 'every individual share_bps must be strictly greater than
        zero and at most 10000.'"""
        rh_a, rh_b = create_two_rights_holders(api)
        headers = make_rights_holder_headers(rh_a["id"])
        payload = create_work_payload(
            primary_owner_id=rh_a["id"],
            primary_share_bps=10000,
            co_owners=[{"rights_holder_id": rh_b["id"], "share_bps": 0}],
        )
        resp = api.create_work(payload, headers)
        validate_error(resp, ApiErrorId.ERR_OWNERSHIP_SHARES_INVALID.value)

    def test_create_work_duplicate_co_owner_rejected(self, api):
        """PRD §3.1: 'no rights_holder_id may appear more than once in co_owners.
        A duplicated co-owner is rejected with ERR_DUPLICATE_CO_OWNER.'"""
        rh_a, rh_b = create_two_rights_holders(api)
        headers = make_rights_holder_headers(rh_a["id"])
        payload = create_work_payload(
            primary_owner_id=rh_a["id"],
            primary_share_bps=8000,
            co_owners=[
                {"rights_holder_id": rh_b["id"], "share_bps": 1000},
                {"rights_holder_id": rh_b["id"], "share_bps": 1000},
            ],
        )
        resp = api.create_work(payload, headers)
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_CO_OWNER.value)

    def test_create_work_duplicate_co_owner_precedes_share_total(self, api):
        """PRD §3.1: 'The duplicate-co-owner check evaluates before the
        share-total check so that a request that contains both errors surfaces
        the duplication first.'

        Crafted: shares would be invalid (total != 10000) AND there is a
        duplicate. Server must surface ERR_DUPLICATE_CO_OWNER, not
        ERR_OWNERSHIP_SHARES_INVALID.
        """
        rh_a, rh_b = create_two_rights_holders(api)
        headers = make_rights_holder_headers(rh_a["id"])
        payload = create_work_payload(
            primary_owner_id=rh_a["id"],
            primary_share_bps=5000,
            co_owners=[
                {"rights_holder_id": rh_b["id"], "share_bps": 1000},
                {"rights_holder_id": rh_b["id"], "share_bps": 1000},
            ],
        )
        resp = api.create_work(payload, headers)
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_CO_OWNER.value)

    def test_create_work_valid_shares_succeed(self, api):
        """PRD §3.1: sum == 10000, no duplicates, all shares > 0 -> success."""
        rh_a, rh_b = create_two_rights_holders(api)
        headers = make_rights_holder_headers(rh_a["id"])
        payload = create_work_payload(
            primary_owner_id=rh_a["id"],
            primary_share_bps=7000,
            co_owners=[{"rights_holder_id": rh_b["id"], "share_bps": 3000}],
        )
        resp = api.create_work(payload, headers)
        data = validate_success(resp, expected_status=201)
        assert_work(data)
        assert data["registration_status"] == "DRAFT"
        assert_ownership_shares_total(data)


# ---------------------------------------------------------------------------
# Patch work — primary-owner-only, version increments
# ---------------------------------------------------------------------------

class TestPatchWork:
    """PRD §3.1: "While the work is in DRAFT, the primary owner — and only
    the primary owner — may patch the title, the co_owners array, the
    primary_share_bps, and the ownership_proof_doc_id. Attempts to patch by
    anyone whose X-User-ID is not the work's primary_owner_id are rejected
    with ERR_FORBIDDEN."
    """

    def test_patch_work_by_non_owner_rejected(self, api):
        """PRD §3.1: non-owner patch -> ERR_FORBIDDEN."""
        rh_a, rh_b = create_two_rights_holders(api)
        work = create_draft_work(api, rh_a)
        # rh_b attempts patch — should be rejected as not primary_owner_id.
        rh_b_headers = make_rights_holder_headers(rh_b["id"])
        resp = api.patch_work(work["id"],
                                patch_work_payload(title="Hijack", version=work["version"]),
                                rh_b_headers)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN.value)

    def test_patch_work_by_owner_succeeds_and_increments_version(self, api):
        """PRD §3.1: 'Every accepted patch writes an AuditLog row of
        change_type LICENSE_CHANGED recording the diff, refreshes updated_at,
        and increments version.'"""
        rh_a, _ = create_two_rights_holders(api)
        work = create_draft_work(api, rh_a, title="Original Title")
        original_version = work["version"]
        headers = make_rights_holder_headers(rh_a["id"])
        resp = api.patch_work(work["id"],
                                patch_work_payload(title="New Title",
                                                    version=original_version),
                                headers)
        data = validate_success(resp)
        assert data["title"] == "New Title"
        assert data["version"] == original_version + 1, (
            f"PRD §2.4 / §3.1: version must increment by exactly one; was "
            f"{original_version}, got {data['version']}"
        )

    def test_patch_work_writes_audit_log(self, api):
        """PRD §3.1: 'Every accepted patch writes an AuditLog row of
        change_type LICENSE_CHANGED.'"""
        rh_a, _ = create_two_rights_holders(api)
        work = create_draft_work(api, rh_a, title="Audit Original")
        headers = make_rights_holder_headers(rh_a["id"])
        resp = api.patch_work(work["id"],
                                patch_work_payload(title="Audit Patched",
                                                    version=work["version"]),
                                headers)
        validate_success(resp)
        logs = list_audit_logs_filtered(api,
                                          subject_entity="Work",
                                          subject_id=work["id"],
                                          change_type="LICENSE_CHANGED")
        assert len(logs) >= 1, (
            "PRD §3.1: patching a Work must write an AuditLog of "
            "change_type LICENSE_CHANGED"
        )


# ---------------------------------------------------------------------------
# Submit for registration
# ---------------------------------------------------------------------------

class TestSubmitForRegistration:
    """PRD §3.2: "Submission has two preconditions: the share distribution
    must still be valid (... ERR_OWNERSHIP_SHARES_INVALID otherwise) and
    ownership_proof_doc_id must be non-empty (ERR_OWNERSHIP_PROOF_MISSING
    otherwise)."
    """

    def test_submit_moves_to_under_review(self, api):
        """PRD §3.2: 'submission moves the work to UNDER_REVIEW, transitioning
        registration_status from DRAFT to UNDER_REVIEW.'"""
        rh_a, _ = create_two_rights_holders(api)
        work = create_draft_work(api, rh_a)
        result = submit_work(api, work, rh_a)
        assert result["registration_status"] == "UNDER_REVIEW"

    def test_submit_with_empty_proof_doc_rejected(self, api):
        """PRD §3.2: 'ownership_proof_doc_id must be non-empty
        (ERR_OWNERSHIP_PROOF_MISSING otherwise).'"""
        rh_a, _ = create_two_rights_holders(api)
        # Create a draft with empty proof doc id (PRD allows draft creation
        # without proof; submit requires it). We provide empty string.
        headers = make_rights_holder_headers(rh_a["id"])
        payload = create_work_payload(
            primary_owner_id=rh_a["id"],
            ownership_proof_doc_id="",
        )
        # Some implementations may reject empty string at create time.
        resp = api.create_work(payload, headers)
        if resp.status_code == 201:
            work = resp.json()["data"]
            resp = api.submit_work(work["id"], headers,
                                    payload={"version": work["version"]})
            validate_error(resp, ApiErrorId.ERR_OWNERSHIP_PROOF_MISSING.value)
        else:
            # Must be the proof-missing error if rejection happens at create.
            validate_error(resp, ApiErrorId.ERR_OWNERSHIP_PROOF_MISSING.value)


# ---------------------------------------------------------------------------
# Registration approval / rejection (PRD §3.2)
# ---------------------------------------------------------------------------

class TestRegistrationFlow:
    """PRD §3.2: "An approval transitions the work from UNDER_REVIEW to
    REGISTERED; the server mints a fresh UUID for certificate_id, stamps
    certificate_issued_at with the current instant, and appends a
    RightsChainEvent with event_type of REGISTERED, ref_entity of Work, and
    ref_id set to the work's id."
    """

    def test_registration_approval_mints_certificate(self, api):
        """PRD §3.2: REGISTRATION_APPROVED → REGISTERED with certificate_id minted."""
        work, _ = create_registered_work(api)
        assert work["registration_status"] == "REGISTERED"
        assert work["certificate_id"] is not None, (
            "PRD §3.2: REGISTERED work must carry certificate_id"
        )
        assert work["certificate_issued_at"] is not None, (
            "PRD §3.2: REGISTERED work must carry certificate_issued_at"
        )

    def test_registration_approval_appends_rights_chain_event(self, api):
        """PRD §3.2: 'appends a RightsChainEvent with event_type of REGISTERED,
        ref_entity of Work, and ref_id set to the work's id.'"""
        work, _ = create_registered_work(api)
        events = list_rights_chain_events(api, work["id"])
        assert any(
            e["event_type"] == "REGISTERED" and e["ref_id"] == work["id"]
            and e["ref_entity"] == "Work"
            for e in events
        ), (
            "PRD §3.2: registration must append a REGISTERED RightsChainEvent "
            "with ref_entity=Work and ref_id=work.id"
        )

    def test_registration_rejection_is_terminal_no_certificate(self, api):
        """PRD §3.2: 'A rejection transitions the work from UNDER_REVIEW to
        REJECTED, which is terminal and produces no certificate.'"""
        rh_a, _ = create_two_rights_holders(api)
        work = create_draft_work(api, rh_a)
        work = submit_work(api, work, rh_a)
        rejected = reject_work_registration(api, work)
        assert rejected["registration_status"] == "REJECTED"
        assert rejected.get("certificate_id") is None, (
            "PRD §3.2: REJECTED works produce no certificate"
        )

    def test_registration_event_for_draft_work_rejected(self, api):
        """PRD §3.2: 'Both transitions require the work to actually be in
        UNDER_REVIEW at the moment the event is applied; an event arriving
        for a work in any other state is rejected with ERR_INVALID_STATE.'"""
        rh_a, _ = create_two_rights_holders(api)
        work = create_draft_work(api, rh_a)  # status=DRAFT, NOT submitted
        payload = emit_event_payload(
            source="COPYRIGHT_AUTHORITY",
            event_type="REGISTRATION_APPROVED",
            ref_entity="Work",
            ref_id=work["id"],
            payload={},
            external_event_id=unique_event_id("reject-draft"),
        )
        resp = api.emit_event(payload, ADMIN_HEADERS)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)
