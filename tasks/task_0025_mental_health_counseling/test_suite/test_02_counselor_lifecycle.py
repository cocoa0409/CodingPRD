"""Counselor registration, profile updates, disqualification, and the
ACTIVE/SUSPENDED/DISQUALIFIED state machine (PRD §3.1, §3.2)."""
from __future__ import annotations
import pytest

from test_helpers import (
    NON_EXISTENT_UUID,
    advance_clock,
    api_client,
    assert_counselor,
    bring_counselor_to_active,
    create_counselor,
    create_counselor_payload,
    DEFAULT_T0,
    disqualify_counselor,
    fetch_open_cycle_for,
    list_audit_log,
    make_admin_headers,
    make_counselor_headers,
    setup_two_confirmed_for_disqualify_chain,
    shift,
    validate_error,
    validate_success,
)


class TestCounselorRegistration:
    def test_create_counselor_starts_pending_cert(self, api, admin_headers):
        """PRD §3.1: "On registration the counselor's `status` begins at
        `PENDING_CERT`."
        """
        res = api.create_counselor(create_counselor_payload(), admin_headers)
        counselor = validate_success(res, expected_status=201)
        assert_counselor(counselor)
        assert counselor["status"] == "PENDING_CERT"
        assert counselor["total_supervision_hours"] == 0
        assert counselor["total_ce_hours"] == 0

    def test_default_revenue_share_is_7000(self, api, admin_headers):
        """PRD §2.8: "Counselor revenue share is similarly stored in basis
        points on the counselor's `revenue_share_bps` field, with a default
        of 7000 (70%) and a permitted range from 0 to 10000."
        """
        payload = create_counselor_payload()
        payload.pop("revenue_share_bps", None)
        res = api.create_counselor(payload, admin_headers)
        counselor = validate_success(res, expected_status=201)
        assert counselor["revenue_share_bps"] == 7000

    def test_email_must_be_lowercase(self, api, admin_headers):
        """PRD §3.1: "the unique lowercase `email` they will use to sign in
        and to receive payouts" — entity definition shows the email field is
        stored lowercase."""
        payload = create_counselor_payload(email="MIXED.Case@Example.Test")
        res = api.create_counselor(payload, admin_headers)
        # A faithful implementer either rejects or normalises. Either way
        # the stored email must be lowercase per the constraint, so check
        # the persisted entity in the success branch and accept rejection
        # in the error branch.
        if res.status_code == 201:
            counselor = validate_success(res, expected_status=201)
            assert counselor["email"] == counselor["email"].lower()
        else:
            assert res.status_code in (400, 422)

    def test_first_certification_cycle_auto_created(self, api, admin_headers):
        """PRD §3.1: "The platform automatically opens that counselor's first
        `CertificationCycle` in the `OPEN` state with `cycle_index` of 1,
        `required_supervision_hours` of 40 (frozen at cycle creation — the
        first cycle's bar is forty supervision hours, every subsequent
        cycle's bar is twenty), `required_ce_hours` of 12"
        """
        counselor = create_counselor()
        cycle = fetch_open_cycle_for(counselor["id"])
        assert cycle["status"] == "OPEN"
        assert cycle["cycle_index"] == 1
        assert float(cycle["required_supervision_hours"]) == 40.0
        assert float(cycle["required_ce_hours"]) == 12.0


class TestCounselorProfileUpdate:
    def test_counselor_can_patch_own_profile(self, api):
        """PRD §3.1: "A counselor can update their own profile through a
        PATCH that admits any combination of `specialty_tags`,
        `supported_channels`, `timezone`, `license_expires_at`, and a
        `version` for optimistic concurrency."
        """
        counselor = create_counselor()
        new_tags = ["TRAUMA", "ADDICTION", "GRIEF"]
        res = api.update_counselor(
            counselor["id"],
            {"specialty_tags": new_tags, "version": counselor["version"]},
            make_counselor_headers(counselor["id"]),
        )
        updated = validate_success(res, expected_status=200)
        assert sorted(updated["specialty_tags"]) == sorted(new_tags)
        assert updated["version"] == counselor["version"] + 1

    def test_patch_with_stale_version_rejected(self, api):
        """PRD §2.5: "When supplied, the server compares it against the
        current stored value: a match allows the mutation to proceed (and
        increments `version` by 1); a mismatch rejects the request with
        `ERR_VERSION_CONFLICT` and HTTP 409."
        """
        counselor = create_counselor()
        # First patch increments version.
        api.update_counselor(
            counselor["id"],
            {"timezone": "America/New_York", "version": counselor["version"]},
            make_counselor_headers(counselor["id"]),
        )
        # Second patch with the original (now-stale) version.
        res = api.update_counselor(
            counselor["id"],
            {"timezone": "Europe/London", "version": counselor["version"]},
            make_counselor_headers(counselor["id"]),
        )
        validate_error(res, "ERR_VERSION_CONFLICT", expected_status=409)


class TestDisqualifyCounselor:
    def test_disqualify_active_counselor_marks_disqualified(self):
        """PRD §3.2: "A counselor may be removed from the platform entirely
        via a disqualification action by a `PlatformAdmin`. This is
        permitted while the counselor is in `ACTIVE` or `SUSPENDED` and
        moves the counselor to the terminal `DISQUALIFIED` state."
        """
        advance_clock(DEFAULT_T0)
        counselor = bring_counselor_to_active()
        result = disqualify_counselor(counselor)
        assert result["status"] == "DISQUALIFIED"

    def test_disqualify_emits_audit_log(self):
        """PRD §3.2: "every `CONFIRMED` future appointment cancels with
        `cancellation_reason` of `COUNSELOR_CANCEL`, has `refund_state` set
        to `FULL_REFUNDED`, and gets a corresponding REFUND row written to
        `SettlementLedger`; and an `AuditLogEntry` with action
        `COUNSELOR_DISQUALIFIED` is appended."
        """
        advance_clock(DEFAULT_T0)
        counselor = bring_counselor_to_active()
        disqualify_counselor(counselor)
        entries = list_audit_log(
            action="COUNSELOR_DISQUALIFIED", target_id=counselor["id"],
        )
        assert any(e["action"] == "COUNSELOR_DISQUALIFIED"
                   and e["target_id"] == counselor["id"] for e in entries)

    def test_disqualify_pending_cert_counselor_rejected(self, api, admin_headers):
        """PRD §3.2: "This is permitted while the counselor is in `ACTIVE`
        or `SUSPENDED` and moves the counselor to the terminal
        `DISQUALIFIED` state."

        Implication: disqualify on PENDING_CERT (not in {ACTIVE, SUSPENDED})
        is rejected with ERR_INVALID_STATE.
        """
        counselor = create_counselor()
        assert counselor["status"] == "PENDING_CERT"
        res = api.disqualify_counselor(counselor["id"], admin_headers, {"reason": "x"})
        validate_error(res, "ERR_INVALID_STATE", expected_status=409)


class TestCounselorListAndDetail:
    def test_list_returns_active_counselors_only(self, api, admin_headers, public_headers):
        """PRD §3.4: "The counselor list accepts query filters
        `specialty_tag`, `channel`, and `timezone`, paginated by `limit` and
        `offset`, and returns only `ACTIVE` counselors."
        """
        # Create a PENDING_CERT counselor (won't appear) and an ACTIVE one.
        pending = create_counselor()
        advance_clock(DEFAULT_T0)
        active = bring_counselor_to_active()
        res = api.list_counselors(public_headers)
        assert res.status_code == 200
        body = res.json()
        ids = [c["id"] for c in body["data"]]
        assert active["id"] in ids
        assert pending["id"] not in ids
