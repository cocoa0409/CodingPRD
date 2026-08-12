"""Error trigger coverage: training-currency gate, stale-policy signing,
unauthenticated requests, posture gate, departure gates (PRD §2.12, §3)."""
import pytest

from test_helpers import (
    validate_success,
    validate_error,
    ApiErrorId,
    create_counterparty,
    create_active_nda,
    create_registered_asset,
    add_verified_measure,
    create_employee_record,
    create_active_employee,
    create_grant_request,
    create_exit_interview_payload,
    create_under_review_disclosure,
    make_employee_headers,
    make_ip_counsel_headers,
    get_pending_ack_id,
    sign_employee_ack,
    TEST_USERS,
)

IP = TEST_USERS["ip_counsel_headers"]
HR = TEST_USERS["hr_partner_headers"]
SEC = TEST_USERS["security_officer_headers"]


class TestTrainingNotCurrentGate:
    def test_grant_approve_with_untrained_employee_rejected(self, api):
        """PRD §3.4: "The employee's `training_current` must be true, otherwise
        `ERR_TRAINING_NOT_CURRENT`."

        Design: Corner/errors/grant_approve_with_untrained_employee_rejected
        """
        emp = create_active_employee(
            complete_training=False,
            full_name="Skip Train", email="skip@x.com", department="ENG",
            role_title="SDE", access_clearance="STANDARD",
            hired_at="2026-05-01T00:00:00Z",
        )
        asset = create_registered_asset(
            title="Train probe", description="x", classification="INTERNAL",
            owner_department="ENG", exposure_estimate_cents=10,
        )
        grant = create_grant_request(emp["id"], asset["id"], justification="j",
                                     expires_at="2026-12-01T00:00:00Z")
        resp = api.transition_grant(
            grant["id"], {"to_status": "APPROVED"},
            TEST_USERS["security_officer_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_TRAINING_NOT_CURRENT)
        data = validate_success(api.get_grant(grant["id"], SEC))
        assert data["status"] == "REQUESTED"


class TestStalePolicyAckSigning:
    def test_stale_policy_ack_sign_rejected(self, api):
        """PRD §3.3: "`PENDING` rows are deliberately left in place at the old
        version, where they become unsignable via `ERR_POLICY_VERSION_STALE` and
        eventually expire through the sweep."
        PRD §3.3: "only an acknowledgment whose `policy_version` still matches
        the program's current version can be signed, otherwise
        `ERR_POLICY_VERSION_STALE`."

        Design: Corner/errors/stale_policy_ack_sign_rejected
        """
        emp = create_employee_record(
            full_name="Stale Ack", email="stale@x.com", department="ENG",
            role_title="SDE", access_clearance="STANDARD",
            hired_at="2026-05-01T00:00:00Z",
        )
        ack_v1 = get_pending_ack_id(emp["id"])
        validate_success(api.publish_policy({"new_version": "v2"}, IP))

        resp = api.sign_acknowledgment(ack_v1, make_employee_headers(emp["id"]))
        validate_error(resp, ApiErrorId.ERR_POLICY_VERSION_STALE)
        stale = validate_success(api.get_acknowledgment(ack_v1, HR))
        assert stale["status"] == "PENDING", "PENDING rows are left in place by publish"

        resp = api.list_acknowledgments(
            HR, params={"employee_id": emp["id"], "status": "PENDING",
                        "policy_version": "v2"}
        )
        rows = validate_success(resp)
        assert len(rows) == 1
        fresh = validate_success(
            api.sign_acknowledgment(rows[0]["id"], make_employee_headers(emp["id"]))
        )
        assert fresh["status"] == "SIGNED", "fresh v2 ack signs cleanly"


class TestUnauthenticated:
    def test_unauthenticated_request_rejected(self, api):
        """PRD §2.1: "A request missing either header, or presenting a role
        outside this declared set, is rejected with `ERR_UNAUTHENTICATED`."
        PRD §2.12: "First (1) authentication: `X-User-Role` and `X-User-ID`
        present and the role declared, else `ERR_UNAUTHENTICATED`."

        Design: Corner/errors/unauthenticated_request_rejected
        """
        resp = api.list_assets({"Content-Type": "application/json"})
        validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED)


class TestPostureDeficientGate:
    def test_posture_deficient_blocks_approval(self, api):
        """PRD §3.5: "The asset's `protection_posture` must be `ADEQUATE` or
        `STRONG`, otherwise `ERR_POSTURE_DEFICIENT`."

        Design: Corner/errors/posture_deficient_blocks_approval
        """
        cp = create_counterparty(legal_name="Posture Ltd", counterparty_type="VENDOR")
        nda = create_active_nda(
            cp["id"], template_version="t28", governing_law="ID",
            effective_date="2026-01-01T00:00:00Z", expiry_date="2027-01-01T00:00:00Z",
            survival_months=3, classification_ceiling="CONFIDENTIAL",
        )
        asset = create_registered_asset(
            title="Posture probe", description="x", classification="CONFIDENTIAL",
            owner_department="ENG", exposure_estimate_cents=1000,
        )
        # Single VERIFIED TECHNICAL = 25 < 40 -> DEFICIENT
        add_verified_measure(asset["id"], "TECHNICAL", title="t", evidence_uri="s3://ev/t.pdf")
        emp = create_employee_record(
            full_name="Posture Req", email="posture@x.com", department="ENG",
            role_title="SDE", access_clearance="STANDARD",
            hired_at="2026-05-01T00:00:00Z",
        )
        disc = create_under_review_disclosure(
            emp["id"], asset["id"], nda["id"],
            purpose="p", marking_protocol="STAMPED_CONFIDENTIAL",
            planned_disclosure_date="2026-07-01T00:00:00Z",
        )
        resp = api.transition_disclosure(
            disc["id"], {"to_status": "APPROVED"}, make_ip_counsel_headers("counsel_1")
        )
        validate_error(resp, ApiErrorId.ERR_POSTURE_DEFICIENT)
        data = validate_success(api.get_disclosure(disc["id"], IP))
        assert data["status"] == "UNDER_REVIEW"


class TestDepartureGates:
    def test_departure_without_certified_interview_rejected(self, api):
        """PRD §3.6: "Departure itself — `NOTICE → DEPARTED` — carries a triple
        gate: a `CERTIFIED` exit interview must exist for the employee,
        otherwise `ERR_EXIT_INTERVIEW_NOT_CERTIFIED`."

        Design: Corner/errors/departure_without_certified_interview_rejected
        """
        emp = create_active_employee(
            complete_training=False, full_name="No Cert", email="nocert@x.com",
            department="ENG", role_title="SDE", access_clearance="STANDARD",
            hired_at="2026-05-01T00:00:00Z",
        )
        resp = api.create_exit_interview(
            create_exit_interview_payload(
                emp["id"],
                scheduled_start="2026-05-09T10:00:00Z",
                scheduled_end="2026-05-09T11:00:00Z",
            ), HR
        )
        ei = validate_success(resp, expected_status=201)
        validate_success(api.transition_exit_interview(ei["id"], {"to_status": "CONDUCTED"}, HR))
        validate_success(api.transition_employee(
            emp["id"], {"to_status": "NOTICE", "departure_type": "VOLUNTARY"}, HR
        ))
        resp = api.transition_employee(emp["id"], {"to_status": "DEPARTED"}, HR)
        validate_error(resp, ApiErrorId.ERR_EXIT_INTERVIEW_NOT_CERTIFIED)
        data = validate_success(api.get_employee(emp["id"], HR))
        assert data["status"] == "NOTICE"

    def test_departure_with_open_review_rejected(self, api):
        """PRD §3.6: "every forensic review of the employee must have concluded
        in `CLOSED_NO_ACTION` or `ESCALATED`, otherwise
        `ERR_REVIEW_NOT_CONCLUDED`."
        PRD §3.6: "An involuntary notice auto-creates a **ForensicReview** for
        the employee in `OPENED` with `trigger_reason` of
        `INVOLUNTARY_DEPARTURE`."

        Design: Corner/errors/departure_with_open_review_rejected
        """
        emp = create_active_employee(
            complete_training=False, full_name="Open Review", email="openrev@x.com",
            department="ENG", role_title="SDE", access_clearance="STANDARD",
            hired_at="2026-05-01T00:00:00Z",
        )
        from test_helpers import create_certified_interview
        create_certified_interview(
            emp["id"],
            scheduled_start="2026-05-09T10:00:00Z",
            scheduled_end="2026-05-09T11:00:00Z",
        )
        # Involuntary notice auto-creates an OPENED review
        validate_success(api.transition_employee(
            emp["id"], {"to_status": "NOTICE", "departure_type": "INVOLUNTARY"}, HR
        ))
        resp = api.transition_employee(emp["id"], {"to_status": "DEPARTED"}, HR)
        validate_error(resp, ApiErrorId.ERR_REVIEW_NOT_CONCLUDED)
        data = validate_success(api.get_employee(emp["id"], HR))
        assert data["status"] == "NOTICE"
