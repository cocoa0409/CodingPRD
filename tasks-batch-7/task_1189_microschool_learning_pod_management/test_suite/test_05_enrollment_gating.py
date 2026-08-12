"""Enrollment-gating claims: pod-state dependency, posture gating, and the
validation-order priority pair (posture gate before capacity)."""
from test_helpers import (
    ApiErrorId,
    create_seat_payload,
    get_success_data,
    make_family_headers,
    validate_error,
    validate_error_is_one_of,
    validate_success,
    TEST_USERS,
)
from test_helpers.fixtures import (
    create_family,
    create_student,
    enroll_seat,
    get_pod,
    get_pod_version,
    set_clock,
    setup_active_pod_with_enrolled_seats,
    setup_enrolled_seat,
    setup_family_student_seat,
    setup_pod_active,
    setup_pod_forming,
    setup_pod_licensing_review,
)

ADMIN = TEST_USERS["platform_admin_headers"]
OPERATOR = TEST_USERS["pod_operator_headers"]
OFFICER = TEST_USERS["compliance_officer_headers"]
REGISTRAR = TEST_USERS["registrar_headers"]


class TestSeatEnrollRequiresPodActive:
    def test_enroll_rejected_while_pod_forming(self, api):
        """PRD 3.6: "The pod must be `ACTIVE`; its `posture` must be `OPEN`
        or `RESTRICTED`; capacity must remain, with any enrollment that would
        push `enrolled_count` past `seat_capacity` rejected as
        `ERR_CAPACITY_FULL` (HTTP 422); the student must still be an
        `APPLICANT`; ..."

        Design: Difficulty/cross_entity_state_dependency/seat_enroll_requires_pod_active
        """
        set_clock("2026-06-01T00:00:00Z")
        pod, site, policy, plan = setup_pod_forming()
        family, student, seat = setup_family_student_seat(pod)
        pod_v = get_pod_version(pod["id"])
        resp = api.enroll_seat(
            pod["id"], seat["id"], {"expected_pod_version": pod_v},
            make_family_headers(family["id"]),
        )
        # PRD does not pin which of the state check / posture gate reports
        # first for a FORMING pod, so accept either (PRD 2.11).
        validate_error_is_one_of(
            resp, [ApiErrorId.ERR_INVALID_STATE, ApiErrorId.ERR_POD_FROZEN]
        )
        seat_now = get_success_data(api.get_seat(seat["id"], REGISTRAR))
        assert seat_now["seat_status"] == "RESERVED"

    def test_enroll_rejected_while_pod_licensing_review(self, api):
        """PRD 3.6: "The pod must be `ACTIVE`; its `posture` must be `OPEN`
        or `RESTRICTED`; capacity must remain, with any enrollment that would
        push `enrolled_count` past `seat_capacity` rejected as
        `ERR_CAPACITY_FULL` (HTTP 422); the student must still be an
        `APPLICANT`; ..."

        Design: Difficulty/cross_entity_state_dependency/seat_enroll_requires_pod_active
        """
        set_clock("2026-06-01T00:00:00Z")
        pod, site, policy, plan, det, guide, assignment = setup_pod_licensing_review()
        family, student, seat = setup_family_student_seat(pod)
        pod_v = get_pod_version(pod["id"])
        resp = api.enroll_seat(
            pod["id"], seat["id"], {"expected_pod_version": pod_v},
            make_family_headers(family["id"]),
        )
        validate_error_is_one_of(
            resp, [ApiErrorId.ERR_INVALID_STATE, ApiErrorId.ERR_POD_FROZEN]
        )
        seat_now = get_success_data(api.get_seat(seat["id"], REGISTRAR))
        assert seat_now["seat_status"] == "RESERVED"


class TestFrozenPodVsCapacity:
    def test_frozen_pod_reports_pod_frozen_not_capacity(self, api):
        """PRD 2.11: "Where several business rules guard one operation,
        their relative order is part of the contract. Seat enrollment
        evaluates the posture gate first, then capacity, then the term
        window."

        Design: Difficulty/priority_pair_validation_conflict/frozen_pod_vs_capacity
        """
        set_clock("2026-08-15T00:00:00Z")
        # Fill the pod to capacity (5 enrolled of seat_capacity=5).
        ctx = setup_active_pod_with_enrolled_seats(num_seats=5, seat_capacity=5)
        pod = ctx["pod"]
        # Suspend the pod: posture becomes FROZEN.
        pod = validate_success(api.suspend_pod(pod["id"], OFFICER))
        assert pod["status"] == "SUSPENDED"
        assert pod["posture"] == "FROZEN"

        # A sixth seat is RESERVED while the pod is SUSPENDED. Reservation is
        # itself posture-gated, so if reservation is blocked by the frozen
        # posture there is nothing further to enroll; create the seat only
        # if the server permits reservation under SUSPENDED (FROZEN posture
        # blocks it per PRD 2.8, in which case we instead exercise enroll on
        # an already-reserved seat created before suspension — see the
        # sibling test for that arrangement).
        family = create_family()
        student = create_student(family["id"])
        resp = api.create_seat(
            pod["id"],
            create_seat_payload(student["id"], enrolled_on="2026-08-15"),
            REGISTRAR,
        )
        validate_error(resp, ApiErrorId.ERR_POD_FROZEN, expected_status=409)

    def test_enroll_on_frozen_full_pod_reports_pod_frozen(self, api):
        """PRD 2.8: "A pod whose `posture` is `FROZEN` refuses five
        categories of child mutation with `ERR_POD_FROZEN` (HTTP 409):
        reserving a seat, enrolling a reserved seat, withdrawing an enrolled
        seat, requesting a progress conference, and scheduling a guide
        assignment."
        PRD 2.11: "Seat enrollment evaluates the posture gate first, then
        capacity, then the term window."

        Design: Difficulty/priority_pair_validation_conflict/frozen_pod_vs_capacity
        """
        set_clock("2026-08-15T00:00:00Z")
        # Fill the pod to capacity, keeping one extra RESERVED seat waiting.
        ctx = setup_active_pod_with_enrolled_seats(num_seats=5, seat_capacity=5)
        pod = ctx["pod"]
        family6 = create_family()
        student6 = create_student(family6["id"])
        seat6 = get_success_data(api.create_seat(
            pod["id"],
            create_seat_payload(student6["id"], enrolled_on="2026-08-15"),
            REGISTRAR,
        ))
        assert seat6["seat_status"] == "RESERVED"
        pod = validate_success(api.suspend_pod(pod["id"], OFFICER))
        assert pod["posture"] == "FROZEN"
        assert pod["enrolled_count"] == 5  # at capacity AND frozen

        resp = api.enroll_seat(
            pod["id"], seat6["id"], {"expected_pod_version": pod["version"]},
            make_family_headers(family6["id"]),
        )
        # Posture gate beats capacity (PRD 2.11): ERR_POD_FROZEN, not
        # ERR_CAPACITY_FULL.
        validate_error(resp, ApiErrorId.ERR_POD_FROZEN, expected_status=409)
        seat_now = get_success_data(api.get_seat(seat6["id"], REGISTRAR))
        assert seat_now["seat_status"] == "RESERVED"
        pod_now = get_pod(pod["id"])
        assert pod_now["enrolled_count"] == 5
