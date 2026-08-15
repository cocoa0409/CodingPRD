"""Consult lifecycle tests: complete-from-OPEN rejection; reopen window
expiry; accept-transfer target on-leave rejection.
"""
import pytest

from test_helpers import (
    validate_success, validate_error, get_success_data, ApiErrorId,
    TEST_USERS, make_hospitalist_headers,
    set_clock, create_hospitalist, create_patient, create_shift,
    admit_and_accept, create_consult_for,
)

ADMIN = TEST_USERS["group_admin_headers"]
SPECIALIST = TEST_USERS["specialist_headers"]


class TestConsultCompleteFromOpenRejected:
    """Corner instance: consult_complete_from_open_rejected."""

    def test_complete_from_open_fails(self, api):
        """PRD §3.7: "Completion moves `ACKNOWLEDGED` → `COMPLETED` — from no
        other state, else `ERR_CONSULT_INVALID_STATE`".

        Design: Corner/state_machines/consult_complete_from_open_rejected
        """
        h1 = create_hospitalist("H One", "ICU", max_census_cap=16)
        create_shift(h1["id"], "DAY", "2026-05-01T06:00:00Z", "2026-05-01T18:00:00Z", activate=True)
        set_clock("2026-05-01T09:00:00Z")
        p1 = create_patient(mrn="S003", acuity="MEDIUM", admit_source="ED",
                            stay_type="INPATIENT", admitted_at="2026-05-01T08:00:00Z")
        admit_and_accept(p1["id"])
        c1 = create_consult_for(p1["id"], h1["id"], "NEPHROLOGY", "ROUTINE", "AKI eval")
        resp = api.complete_consult(c1["id"], SPECIALIST)
        validate_error(resp, ApiErrorId.ERR_CONSULT_INVALID_STATE)
        c_now = get_success_data(api.get_consult_request(c1["id"], ADMIN))
        assert c_now["status"] == "OPEN"


class TestConsultReopenAfterWindowExpiresRejected:
    """Corner instance: consult_reopen_after_window_expires_rejected."""

    def test_reopen_one_ms_past_window_fails(self, api):
        """PRD §3.7: "the current logical time must fall at or before
        `completed_at` plus 24 hours, else `ERR_CONSULT_REOPEN_WINDOW_EXPIRED`
        (HTTP 422)."

        Design: Corner/state_machines/consult_reopen_after_window_expires_rejected
        """
        h1 = create_hospitalist("H One", "ICU", max_census_cap=16)
        create_shift(h1["id"], "DAY", "2026-05-01T06:00:00Z", "2026-05-01T18:00:00Z", activate=True)
        set_clock("2026-05-01T10:00:00Z")
        p1 = create_patient(mrn="S004", acuity="MEDIUM", admit_source="ED",
                            stay_type="INPATIENT", admitted_at="2026-05-01T09:00:00Z")
        admit_and_accept(p1["id"])
        c1 = create_consult_for(p1["id"], h1["id"], "CARDIOLOGY", "ROUTINE", "murmur")
        set_clock("2026-05-01T10:05:00Z")
        get_success_data(api.acknowledge_consult(c1["id"], SPECIALIST))
        set_clock("2026-05-01T10:10:00Z")
        get_success_data(api.complete_consult(c1["id"], SPECIALIST))
        # Reopen at completed_at + 24h + 1ms -> rejected
        set_clock("2026-05-02T10:10:00.001Z")
        resp = api.reopen_consult(c1["id"], make_hospitalist_headers(h1["id"]))
        validate_error(resp, ApiErrorId.ERR_CONSULT_REOPEN_WINDOW_EXPIRED)
        c_now = get_success_data(api.get_consult_request(c1["id"], ADMIN))
        assert c_now["status"] == "COMPLETED"


class TestAcceptTransferTargetOnLeaveRejected:
    """Corner instance: accept_transfer_target_on_leave_rejected."""

    def test_on_leave_target_rejected(self, api):
        """PRD §3.4: "the cross-entity tier, where ... the target's
        employment must be `ACTIVE` (else `ERR_HOSPITALIST_NOT_ACTIVE`)".
        PRD §2.5: "`distribution_eligible` ... is false whenever
        `employment_status` is anything other than `ACTIVE`".

        Design: Corner/errors/accept_transfer_target_on_leave_rejected
        """
        h_t = create_hospitalist("H T", "ICU", max_census_cap=16, employment_status="ON_LEAVE")
        h_s = create_hospitalist("H S", "INTERNAL_MEDICINE", max_census_cap=16)
        create_shift(h_t["id"], "DAY", "2026-05-01T06:00:00Z", "2026-05-01T18:00:00Z", activate=True)
        create_shift(h_s["id"], "DAY", "2026-05-01T08:00:00Z", "2026-05-01T20:00:00Z", activate=True)
        set_clock("2026-05-01T09:00:00Z")
        p1 = create_patient(mrn="X009", acuity="MEDIUM", admit_source="ED",
                            stay_type="INPATIENT", admitted_at="2026-05-01T08:30:00Z")
        a1 = get_success_data(api.create_admission({"patient_id": p1["id"]}, ADMIN))
        # H_T ON_LEAVE is excluded from the pool -> offered to H_S
        assert a1["offered_to_hospitalist_id"] == h_s["id"]
        acc = get_success_data(api.accept_admission(a1["id"], make_hospitalist_headers(h_s["id"])))
        asg_id = acc["assignment_id"]
        asg_v = get_success_data(api.get_assignment(asg_id, ADMIN))["version"]
        get_success_data(api.transfer_assignment(
            asg_id,
            {"target_hospitalist_id": h_t["id"], "expected_assignment_version": asg_v},
            make_hospitalist_headers(h_s["id"]),
        ))
        resp = api.accept_transfer(asg_id, make_hospitalist_headers(h_t["id"]))
        validate_error(resp, ApiErrorId.ERR_HOSPITALIST_NOT_ACTIVE)
        asg_now = get_success_data(api.get_assignment(asg_id, ADMIN))
        assert asg_now["status"] == "PENDING_TRANSFER"
        h_t_now = get_success_data(api.get_hospitalist(h_t["id"], ADMIN))
        assert h_t_now["current_census"] == 0
