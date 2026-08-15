"""Census-cap boundary tests: equality rejects; cap-1 accepts then cap rejects.
Also accept-transfer temporal-vs-fiscal priority test.
"""
import pytest

from test_helpers import (
    validate_success, validate_error, get_success_data, ApiErrorId,
    TEST_USERS, make_hospitalist_headers,
    set_clock, create_hospitalist, create_patient, create_shift,
    admit_and_accept, setup_handoff_accepted_for_shift,
)

ADMIN = TEST_USERS["group_admin_headers"]


class TestCensusCapExactEqualityRejects:
    """Difficulty instance: census_cap_exact_equality_rejects."""

    def _setup(self, api):
        """H_T cap 2 ACTIVE shift 07-19; H_S cap 16 ACTIVE shift 08-20.
        P1 -> H_T (census 1). P2 -> H_S then transferred to H_T (census 2 == cap).
        P3 -> H_S, transfer PENDING to H_T (the one we will try to accept)."""
        h_t = create_hospitalist("H T", "INTERNAL_MEDICINE", max_census_cap=2)
        h_s = create_hospitalist("H S", "ICU", max_census_cap=16)
        s_t = create_shift(h_t["id"], "DAY", "2026-05-01T07:00:00Z", "2026-05-01T19:00:00Z", activate=True)
        s_s = create_shift(h_s["id"], "DAY", "2026-05-01T08:00:00Z", "2026-05-01T20:00:00Z", activate=True)
        set_clock("2026-05-01T09:00:00Z")
        # P1: H_T wins tie (earlier shift start 07:00)
        p1 = create_patient(mrn="M921", acuity="MEDIUM", admit_source="ED",
                            stay_type="INPATIENT", admitted_at="2026-05-01T08:00:00Z")
        a1 = get_success_data(api.create_admission({"patient_id": p1["id"]}, ADMIN))
        assert a1["offered_to_hospitalist_id"] == h_t["id"]
        get_success_data(api.accept_admission(a1["id"], make_hospitalist_headers(h_t["id"])))
        # P2: H_T (2-1)/2=0.5 vs H_S 1.0 -> H_S
        p2 = create_patient(mrn="M922", acuity="LOW", admit_source="DIRECT",
                            stay_type="INPATIENT", admitted_at="2026-05-01T08:10:00Z")
        a2 = get_success_data(api.create_admission({"patient_id": p2["id"]}, ADMIN))
        assert a2["offered_to_hospitalist_id"] == h_s["id"]
        acc2 = get_success_data(api.accept_admission(a2["id"], make_hospitalist_headers(h_s["id"])))
        asg2 = acc2["assignment_id"]
        # Initiate transfer H_S -> H_T; H_T at census 1 < cap 2 -> accept succeeds
        asg2_v = get_success_data(api.get_assignment(asg2, ADMIN))["version"]
        get_success_data(api.transfer_assignment(
            asg2,
            {"target_hospitalist_id": h_t["id"], "expected_assignment_version": asg2_v},
            make_hospitalist_headers(h_s["id"]),
        ))
        get_success_data(api.accept_transfer(asg2, make_hospitalist_headers(h_t["id"])))
        # H_T census is now 2 == cap
        # P3 -> H_S (H_T ineligible at cap)
        p3 = create_patient(mrn="M923", acuity="LOW", admit_source="ED",
                            stay_type="INPATIENT", admitted_at="2026-05-01T08:20:00Z")
        a3 = get_success_data(api.create_admission({"patient_id": p3["id"]}, ADMIN))
        assert a3["offered_to_hospitalist_id"] == h_s["id"]
        acc3 = get_success_data(api.accept_admission(a3["id"], make_hospitalist_headers(h_s["id"])))
        asg3 = acc3["assignment_id"]
        asg3_v = get_success_data(api.get_assignment(asg3, ADMIN))["version"]
        get_success_data(api.transfer_assignment(
            asg3,
            {"target_hospitalist_id": h_t["id"], "expected_assignment_version": asg3_v},
            make_hospitalist_headers(h_s["id"]),
        ))
        return h_t, h_s, p1, p2, p3, asg2, asg3

    def test_accept_at_cap_minus_one_succeeds_and_reaches_cap(self, api):
        """PRD §3.4: "finally capacity, with the target's `current_census`
        strictly below their cap, equality rejecting as
        `ERR_CENSUS_CAP_REACHED`."

        Design: Difficulty/boundary_precision_check/census_cap_exact_equality_rejects
        """
        h_t, h_s, p1, p2, p3, asg2, asg3 = self._setup(api)
        # The setup's first accept-transfer (asg2) succeeded at cap-1 and left
        # H_T at census 2 == cap.
        h_t_now = get_success_data(api.get_hospitalist(h_t["id"], ADMIN))
        assert h_t_now["current_census"] == 2
        assert h_t_now["max_census_cap"] == 2

    def test_accept_at_cap_equality_rejected(self, api):
        """PRD §2.7 item 9: "The accepting hospitalist's census must be
        strictly below `max_census_cap`, with equality rejecting —
        `ERR_CENSUS_CAP_REACHED` (HTTP 422)".
        PRD §3.4: "finally capacity, with the target's `current_census`
        strictly below their cap, equality rejecting as
        `ERR_CENSUS_CAP_REACHED`."

        Design: Difficulty/boundary_precision_check/census_cap_exact_equality_rejects
        """
        h_t, h_s, p1, p2, p3, asg2, asg3 = self._setup(api)
        resp = api.accept_transfer(asg3, make_hospitalist_headers(h_t["id"]))
        validate_error(resp, ApiErrorId.ERR_CENSUS_CAP_REACHED)
        asg3_now = get_success_data(api.get_assignment(asg3, ADMIN))
        assert asg3_now["status"] == "PENDING_TRANSFER"
