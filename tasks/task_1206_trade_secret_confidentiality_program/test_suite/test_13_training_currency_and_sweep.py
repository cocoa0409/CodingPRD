"""Training currency computation and clock/sweep boundary semantics
(PRD §3.3, §2.5)."""
import pytest

from test_helpers import (
    validate_success,
    ApiErrorId,
    create_counterparty,
    create_active_nda,
    create_active_employee,
    create_training_assignment_payload,
    get_basic_training_id,
    make_employee_headers,
    TEST_USERS,
)

IP = TEST_USERS["ip_counsel_headers"]
HR = TEST_USERS["hr_partner_headers"]


class TestTrainingCurrentFlips:
    def test_training_current_flips_on_overdue_and_recovers(self, api):
        """PRD §3.3: "That flag is true exactly when two conditions hold: the
        employee has no training assignment in `OVERDUE` or `ESCALATED` status,
        and at least one `COMPLETED` `BASIC_TS` assignment exists whose
        `completed_at` lies within the trailing 365 days."
        PRD §3.3: "Completion belongs to the employee themself from `ASSIGNED`,
        `OVERDUE`, or `ESCALATED` — `X-User-ID` must equal the assignment's
        `employee_id`, otherwise `ERR_OWNERSHIP_REQUIRED` — and stamps
        `completed_at`."

        Design: Corner/calculations/training_current_flips_on_overdue_and_recovers
        """
        emp = create_active_employee(
            complete_training=True,
            full_name="Eve Train", email="eve@x.com", department="ENG",
            role_title="SDE", access_clearance="STANDARD",
            hired_at="2026-05-01T00:00:00Z",
        )
        resp = api.create_training_assignment(
            create_training_assignment_payload(
                emp["id"], module="CLEAN_DESK", due_at="2026-05-10T00:00:00Z"
            ), HR
        )
        tr2 = validate_success(resp, expected_status=201)

        tc1 = validate_success(api.get_employee(emp["id"], HR))["training_current"]
        assert tc1 is True, "BASIC_TS completed, nothing overdue"

        api.set_clock({"to_iso8601": "2026-05-20T00:00:00Z"}, IP)
        validate_success(api.run_sweep(IP))
        tc2 = validate_success(api.get_employee(emp["id"], HR))["training_current"]
        assert tc2 is False, "CLEAN_DESK assignment swept to OVERDUE"

        validate_success(api.transition_training_assignment(
            tr2["id"], {"to_status": "COMPLETED"}, make_employee_headers(emp["id"])
        ))
        tc3 = validate_success(api.get_employee(emp["id"], HR))["training_current"]
        assert tc3 is True, "late completion from OVERDUE restores currency"


class TestNdaExpiryBoundary:
    def test_nda_expiry_boundary_exactly_at_expiry_stays_active(self, api):
        """PRD §2.5: "Every clock comparison the sweep performs is strict. An
        NDA whose `expiry_date` equals the current clock stays `ACTIVE`."
        PRD §3.2: "Expiry is the sweep's work: an agreement still `ACTIVE` once
        the clock is strictly later than its `expiry_date` moves to `EXPIRED`."

        Design: Corner/calculations/nda_expiry_boundary_exactly_at_expiry_stays_active
        """
        cp = create_counterparty(legal_name="Tau Movers", counterparty_type="VENDOR")
        nda = create_active_nda(
            cp["id"], template_version="t17", governing_law="UT",
            effective_date="2026-01-01T00:00:00Z", expiry_date="2026-12-31T00:00:00Z",
            survival_months=3, classification_ceiling="INTERNAL",
        )
        api.set_clock({"to_iso8601": "2026-12-31T00:00:00Z"}, IP)
        sweep1 = validate_success(api.run_sweep(IP))
        assert sweep1["ndas_expired"] == 0, "at exactly expiry_date the NDA stays ACTIVE"
        still = validate_success(api.get_nda(nda["id"], IP))
        assert still["status"] == "ACTIVE"

        api.set_clock({"to_iso8601": "2026-12-31T00:00:01Z"}, IP)
        sweep2 = validate_success(api.run_sweep(IP))
        assert sweep2["ndas_expired"] == 1
        expired = validate_success(api.get_nda(nda["id"], IP))
        assert expired["status"] == "EXPIRED", "one second past expiry_date the sweep expires it"
