"""Work restriction intervals and return-to-work clearance workflow."""
from test_helpers import (
    ApiErrorId,
    assert_instant,
    create_exposure_case,
    create_restriction,
    create_work_restriction_payload,
    decide_clearance,
    get_employee,
    get_restriction,
    list_restrictions,
    make_cleared_employee,
    register_employee,
    request_clearance,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestHalfOpenOverlap:
    def test_adjacent_restriction_at_end_date_allowed(self, api, physician_headers):
        """PRD §3.6: "Restrictions occupy a half-open interval that includes
        the start and excludes the end: a new `ACTIVE` restriction whose
        interval intersects another `ACTIVE` restriction of the same employee
        is rejected with `ERR_WORK_RESTRICTION_OVERLAP`, while adjacency — one
        restriction's end exactly meeting another's start — is permitted
        because the end is exclusive."

        Design: Difficulty/resource_temporal_overlap/work_restriction_half_open_overlap
        """
        emp = register_employee("E-OV1", full_name="Over Lap")
        r1 = create_restriction(emp["id"], restriction_type="NO_PROCEDURES",
                                start_date="2026-08-05T00:00:00Z",
                                end_date="2026-08-20T00:00:00Z")
        assert r1["status"] == "ACTIVE"

        # start == R1.end_date: adjacency, permitted under the half-open rule.
        r2 = create_restriction(emp["id"], restriction_type="MODIFIED_DUTY",
                                start_date="2026-08-20T00:00:00Z")
        assert r2["status"] == "ACTIVE"
        assert r2["end_date"] is None, "open-ended restriction keeps end_date null"

        emp_after = get_employee(emp["id"])
        assert emp_after["open_restriction_count"] == 2

    def test_overlapping_restriction_rejected(self, api, physician_headers):
        """PRD §3.6: "a new `ACTIVE` restriction whose interval intersects
        another `ACTIVE` restriction of the same employee is rejected with
        `ERR_WORK_RESTRICTION_OVERLAP`"

        Design: Difficulty/resource_temporal_overlap/work_restriction_half_open_overlap
        """
        emp = register_employee("E-OV1B", full_name="Over Lap Two")
        create_restriction(emp["id"], restriction_type="NO_PROCEDURES",
                           start_date="2026-08-05T00:00:00Z",
                           end_date="2026-08-20T00:00:00Z")

        # One day before the incumbent's end: the interiors intersect.
        resp = api.create_work_restriction(
            emp["id"],
            create_work_restriction_payload(
                restriction_type="NO_PATIENT_CONTACT",
                start_date="2026-08-19T00:00:00Z",
                end_date="2026-08-25T00:00:00Z",
            ),
            physician_headers,
        )
        validate_error(resp, ApiErrorId.ERR_WORK_RESTRICTION_OVERLAP)

        emp_after = get_employee(emp["id"])
        assert emp_after["open_restriction_count"] == 1, (
            "the rejected create must not add to the restriction count"
        )


class TestClearanceRequiresActiveRestriction:
    def test_decide_cleared_on_expired_restriction_rejected(self, api,
                                                            physician_headers):
        """PRD §3.6: "The decision requires the clearance to be `PENDING`
        (`ERR_INVALID_STATE`) and the linked restriction still `ACTIVE`
        (`ERR_RESTRICTION_NOT_ACTIVE`)" and "When a restriction has an
        `end_date` and the clock reaches or passes it, the restriction
        automatically becomes `EXPIRED`, decrementing `open_restriction_count`
        and recomputing the posture."

        Design: Difficulty/cross_entity_state_dependency/clearance_decide_requires_restriction_active
        """
        emp = register_employee("E-XD1", full_name="Xdep One", job_category="TECH",
                                department="RAD")
        wr = create_restriction(emp["id"], restriction_type="MODIFIED_DUTY",
                                start_date="2026-08-02T00:00:00Z",
                                end_date="2026-08-10T00:00:00Z")
        clr = request_clearance(wr["id"])
        assert clr["status"] == "PENDING"

        # At now == end_date the half-open interval has fully elapsed.
        set_clock("2026-08-10T00:00:00Z")
        wr_after = get_restriction(wr["id"])
        assert wr_after["status"] == "EXPIRED"
        assert get_employee(emp["id"])["open_restriction_count"] == 0

        resp = api.decide_clearance(clr["id"], {"outcome": "CLEARED"}, physician_headers)
        validate_error(resp, ApiErrorId.ERR_RESTRICTION_NOT_ACTIVE)

        clr_after = validate_success(api.get_clearance(clr["id"], physician_headers))
        assert clr_after["status"] == "PENDING"

    def test_decide_denied_on_expired_restriction_rejected(self, api,
                                                           physician_headers):
        """PRD §3.6: "The decision requires the clearance to be `PENDING`
        (`ERR_INVALID_STATE`) and the linked restriction still `ACTIVE`
        (`ERR_RESTRICTION_NOT_ACTIVE`)" — the gate applies to the decision
        itself, regardless of the requested outcome (a `DENIED` decision
        leaves the restriction `ACTIVE` per the same section).

        Design: Difficulty/cross_entity_state_dependency/clearance_decide_requires_restriction_active
        """
        emp = register_employee("E-XD1D", full_name="Xdep Two", job_category="TECH",
                                department="RAD")
        wr = create_restriction(emp["id"], restriction_type="MODIFIED_DUTY",
                                start_date="2026-08-02T00:00:00Z",
                                end_date="2026-08-10T00:00:00Z")
        clr = request_clearance(wr["id"])

        set_clock("2026-08-10T00:00:00Z")
        assert get_restriction(wr["id"])["status"] == "EXPIRED"

        resp = api.decide_clearance(clr["id"], {"outcome": "DENIED"}, physician_headers)
        validate_error(resp, ApiErrorId.ERR_RESTRICTION_NOT_ACTIVE)

        clr_after = validate_success(api.get_clearance(clr["id"], physician_headers))
        assert clr_after["status"] == "PENDING"


class TestRestrictionCreateLiftConservesCount:
    def test_create_raises_count_and_restricts_posture(self, api):
        """PRD §3.6: "Creating a restriction increments the employee's
        `open_restriction_count` by one and recomputes the posture."
        PRD §3.1: "Otherwise, when `open_restriction_count` is above zero, the
        posture is `RESTRICTED_DUTY`."

        Design: Difficulty/compensating_invariant/restriction_create_lift_conserves_count
        """
        emp = make_cleared_employee("E-CI2", full_name="Lift Pair")
        assert emp["open_restriction_count"] == 0
        assert emp["compliance_posture"] == "CLEAR"

        wr = create_restriction(emp["id"], restriction_type="NO_PATIENT_CONTACT",
                                start_date="2026-08-02T00:00:00Z")
        assert wr["status"] == "ACTIVE"
        assert wr["origin"] == "MANUAL"

        emp_mid = get_employee(emp["id"])
        assert emp_mid["open_restriction_count"] == 1
        assert emp_mid["compliance_posture"] == "RESTRICTED_DUTY"

    def test_clearance_lift_returns_count_and_posture(self, api):
        """PRD §3.6: "A `CLEARED` decision transitions the restriction `ACTIVE
        → LIFTED`, decrements `open_restriction_count` by one, and recomputes
        the posture"

        Design: Difficulty/compensating_invariant/restriction_create_lift_conserves_count
        """
        emp = make_cleared_employee("E-CI2B", full_name="Lift Pair Two")
        wr = create_restriction(emp["id"], restriction_type="NO_PATIENT_CONTACT",
                                start_date="2026-08-02T00:00:00Z")
        assert get_employee(emp["id"])["open_restriction_count"] == 1

        clr = request_clearance(wr["id"])
        decided = decide_clearance(clr["id"], "CLEARED",
                                   decision_note="fit for full duty")
        assert decided["status"] == "CLEARED"
        assert decided["decided_by_user_id"] is not None
        assert decided["decided_at"] is not None

        assert get_restriction(wr["id"])["status"] == "LIFTED"
        emp_end = get_employee(emp["id"])
        assert emp_end["open_restriction_count"] == 0, (
            "the lift compensates the create: count returns to zero"
        )
        assert emp_end["compliance_posture"] == "CLEAR"


class TestClearanceOnLiftedRestriction:
    def test_clearance_request_on_lifted_restriction_rejected(self, api,
                                                              nurse_headers):
        """PRD §3.6: "A nurse requests a `ReturnToWorkClearance` against an
        `ACTIVE` restriction — requesting against a restriction in any other
        status is rejected with `ERR_RESTRICTION_NOT_ACTIVE`"

        Design: Corner/state_machines/clearance_create_on_lifted_restriction_rejected
        """
        emp = register_employee("E-SM11", full_name="Lift Ed")
        wr = create_restriction(emp["id"], restriction_type="NO_PROCEDURES",
                                start_date="2026-08-02T00:00:00Z")
        clr = request_clearance(wr["id"])
        decide_clearance(clr["id"], "CLEARED")
        assert get_restriction(wr["id"])["status"] == "LIFTED"

        resp = api.create_clearance(wr["id"], {}, nurse_headers)
        validate_error(resp, ApiErrorId.ERR_RESTRICTION_NOT_ACTIVE)


class TestRestrictionCaseLinkage:
    def test_case_belonging_to_other_employee_rejected(self, api,
                                                       physician_headers):
        """PRD §3.6: "An optional `exposure_case_id` may link the restriction
        to the exposure that caused it; when present, the case must belong to
        the same employee (`ERR_CASE_EMPLOYEE_MISMATCH`)."

        Design: Corner/validations/restriction_case_employee_mismatch_rejected
        """
        emp_a = register_employee("E-V8A", full_name="Case Owner")
        emp_b = register_employee("E-V8B", full_name="Other Emp", job_category="TECH",
                                  department="LAB")
        case_a = create_exposure_case(
            emp_a["id"], exposure_type="PERCUTANEOUS",
            exposure_datetime="2026-07-30T10:00:00Z",
            source_known=False, body_fluid="BLOOD",
        )

        resp = api.create_work_restriction(
            emp_b["id"],
            create_work_restriction_payload(
                restriction_type="MODIFIED_DUTY",
                start_date="2026-08-02T00:00:00Z",
                exposure_case_id=case_a["id"],
            ),
            physician_headers,
        )
        validate_error(resp, ApiErrorId.ERR_CASE_EMPLOYEE_MISMATCH)

        assert list_restrictions(emp_b["id"]) == []
