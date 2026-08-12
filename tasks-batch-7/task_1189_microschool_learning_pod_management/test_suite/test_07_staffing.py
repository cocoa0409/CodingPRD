"""Guide staffing claims: window-overlap geometry, window validity, guide
standing, the safety-vs-constraint priority pair, and the termination
cascade."""
from test_helpers import (
    ApiErrorId,
    create_guide_assignment_payload,
    create_guide_payload,
    create_pod_payload,
    create_safety_policy_payload,
    validate_error,
    validate_success,
    TEST_USERS,
)
from test_helpers.fixtures import (
    create_guide,
    create_guide_assignment,
    create_site,
    get_pod,
    set_clock,
    setup_active_pod_with_enrolled_seats,
    setup_pod_active,
)

ADMIN = TEST_USERS["platform_admin_headers"]
OPERATOR = TEST_USERS["pod_operator_headers"]
OFFICER = TEST_USERS["compliance_officer_headers"]


class TestGuideWindowOverlap:
    def test_touching_window_boundaries_overlap(self, api):
        """PRD 3.4: "Creation enforces, after the posture gate, three checks
        in order: the window must not overlap any of the same guide's
        existing windows in `SCHEDULED` or `ACTIVE` status, with overlap
        measured inclusively at both ends (`ERR_GUIDE_WINDOW_OVERLAP`,
        HTTP 422); the start date must not fall after the end date and the
        window must intersect the pod's academic term (`ERR_INVALID_WINDOW`,
        HTTP 422); and the referenced guide must be `ACTIVE`
        (`ERR_GUIDE_INACTIVE`, HTTP 422)."

        Design: Difficulty/resource_temporal_overlap/guide_assignment_inclusive_overlap
        """
        set_clock("2026-06-01T00:00:00Z")
        pod, site, policy, plan, det, guide, assignment = setup_pod_active()
        # The fixture guide already holds the full-term assignment required
        # for pod activation (PRD 3.3); the overlap rule is per-guide ("the
        # same guide's existing windows"), so a fresh second guide isolates
        # the geometry exercised here.
        guide2 = create_guide()
        # Existing assignment: [2026-08-01, 2026-12-31] for this guide.
        first = create_guide_assignment(
            pod["id"], guide2["id"],
            window_start_date="2026-08-01", window_end_date="2026-12-31",
            weekly_hours=20, is_primary=False,
        )
        # New window starting exactly on the existing window's end date
        # overlaps under inclusive-both-ends semantics.
        resp = api.create_guide_assignment(
            pod["id"],
            create_guide_assignment_payload(
                guide2["id"],
                window_start_date="2026-12-31", window_end_date="2027-03-31",
                weekly_hours=20, is_primary=False,
            ),
            OPERATOR,
        )
        validate_error(resp, ApiErrorId.ERR_GUIDE_WINDOW_OVERLAP,
                       expected_status=422)

    def test_day_after_window_end_is_safe(self, api):
        """PRD 3.4: "Creation enforces, after the posture gate, three checks
        in order: the window must not overlap any of the same guide's
        existing windows in `SCHEDULED` or `ACTIVE` status, with overlap
        measured inclusively at both ends (`ERR_GUIDE_WINDOW_OVERLAP`,
        HTTP 422); the start date must not fall after the end date and the
        window must intersect the pod's academic term (`ERR_INVALID_WINDOW`,
        HTTP 422); and the referenced guide must be `ACTIVE`
        (`ERR_GUIDE_INACTIVE`, HTTP 422)."

        Design: Difficulty/resource_temporal_overlap/guide_assignment_inclusive_overlap
        """
        set_clock("2026-06-01T00:00:00Z")
        pod, site, policy, plan, det, guide, assignment = setup_pod_active()
        # Fresh second guide: the overlap rule is per-guide, and the fixture
        # guide already holds a full-term assignment from pod activation.
        guide2 = create_guide()
        create_guide_assignment(
            pod["id"], guide2["id"],
            window_start_date="2026-08-01", window_end_date="2026-12-31",
            weekly_hours=20, is_primary=False,
        )
        # One day past the existing end date: no overlap.
        data = validate_success(
            api.create_guide_assignment(
                pod["id"],
                create_guide_assignment_payload(
                    guide2["id"],
                    window_start_date="2027-01-01", window_end_date="2027-03-31",
                    weekly_hours=20, is_primary=False,
                ),
                OPERATOR,
            ),
            expected_status=201,
        )
        assert data["assignment_status"] == "SCHEDULED"


class TestGuideWindowValidity:
    def test_err_invalid_window_triggerable(self, api):
        """PRD 3.4: "Creation enforces, after the posture gate, three checks
        in order: the window must not overlap any of the same guide's
        existing windows in `SCHEDULED` or `ACTIVE` status, with overlap
        measured inclusively at both ends (`ERR_GUIDE_WINDOW_OVERLAP`,
        HTTP 422); the start date must not fall after the end date and the
        window must intersect the pod's academic term (`ERR_INVALID_WINDOW`,
        HTTP 422); and the referenced guide must be `ACTIVE`
        (`ERR_GUIDE_INACTIVE`, HTTP 422)."

        Design: Corner/errors/err_invalid_window_triggerable
        """
        set_clock("2026-08-01T00:00:00Z")
        pod, site, policy, plan, det, guide, assignment = setup_pod_active()
        # A second guide avoids the overlap check with the fixture's
        # full-term assignment for the primary guide.
        guide2 = create_guide()
        resp = api.create_guide_assignment(
            pod["id"],
            create_guide_assignment_payload(
                guide2["id"],
                window_start_date="2027-01-01", window_end_date="2026-12-01",
                weekly_hours=20,
            ),
            OPERATOR,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_WINDOW, expected_status=422)


class TestGuideStanding:
    def test_err_guide_inactive_triggerable(self, api):
        """PRD 3.4: "Creation enforces, after the posture gate, three checks
        in order: the window must not overlap any of the same guide's
        existing windows in `SCHEDULED` or `ACTIVE` status, with overlap
        measured inclusively at both ends (`ERR_GUIDE_WINDOW_OVERLAP`,
        HTTP 422); the start date must not fall after the end date and the
        window must intersect the pod's academic term (`ERR_INVALID_WINDOW`,
        HTTP 422); and the referenced guide must be `ACTIVE`
        (`ERR_GUIDE_INACTIVE`, HTTP 422)."

        Design: Corner/errors/err_guide_inactive_triggerable
        """
        set_clock("2026-08-01T00:00:00Z")
        pod, site, policy, plan, det, guide, assignment = setup_pod_active()
        candidate = validate_success(
            api.create_guide(create_guide_payload(), ADMIN), expected_status=201
        )
        assert candidate["guide_status"] == "CANDIDATE"
        resp = api.create_guide_assignment(
            pod["id"],
            create_guide_assignment_payload(candidate["id"], weekly_hours=20),
            OPERATOR,
        )
        validate_error(resp, ApiErrorId.ERR_GUIDE_INACTIVE, expected_status=422)


class TestSafetyVsConstraintPair:
    def test_open_enrollment_without_safety_policy_rejected(self, api):
        """PRD 3.1: "Opening enrollment — moving a pod from `DRAFT` to
        `FORMING` — is a `PodOperator` action gated on three preconditions:
        the referenced site must be `AVAILABLE` or `LEASED`; the pod must
        hold at least one `APPROVED` safety policy; and it must hold at
        least one `APPROVED` curriculum plan. A missing or inadequate safety
        policy is rejected with `ERR_SAFETY_POLICY_MISSING` (HTTP 422)."

        Design: Difficulty/priority_pair_validation_conflict/safety_vs_constraint_overlap
        """
        set_clock("2026-06-01T00:00:00Z")
        site = create_site()
        pod = validate_success(
            api.create_pod(create_pod_payload(site["id"]), OPERATOR),
            expected_status=201,
        )
        # No safety policy and no curriculum plan exist for this pod.
        resp = api.open_enrollment(pod["id"], OPERATOR)
        validate_error(resp, ApiErrorId.ERR_SAFETY_POLICY_MISSING,
                       expected_status=422)
        pod_now = get_pod(pod["id"])
        assert pod_now["status"] == "DRAFT"

    def test_overlapping_assignment_rejected_on_compliant_pod(self, api):
        """PRD 2.11: "Creating a guide assignment evaluates the posture gate
        first, then window overlap against the guide's existing commitments,
        then window validity, then the guide's active standing."
        PRD 3.4: "the window must not overlap any of the same guide's
        existing windows in `SCHEDULED` or `ACTIVE` status, with overlap
        measured inclusively at both ends (`ERR_GUIDE_WINDOW_OVERLAP`,
        HTTP 422)"

        Design: Difficulty/priority_pair_validation_conflict/safety_vs_constraint_overlap
        """
        set_clock("2026-06-01T00:00:00Z")
        pod, site, policy, plan, det, guide, assignment = setup_pod_active()
        # The fixture's assignment spans the full term; any second window
        # for the same guide overlaps it. Give the overlapping window a
        # start date AFTER its own end date as well: per PRD 2.11 the
        # overlap check fires before window validity.
        resp = api.create_guide_assignment(
            pod["id"],
            create_guide_assignment_payload(
                guide["id"],
                window_start_date="2027-02-01", window_end_date="2027-01-01",
                weekly_hours=20, is_primary=False,
            ),
            OPERATOR,
        )
        validate_error(resp, ApiErrorId.ERR_GUIDE_WINDOW_OVERLAP,
                       expected_status=422)


class TestGuideTerminateCascade:
    def test_terminate_violating_ratio_auto_suspends_pod(self, api):
        """PRD 3.4: "The termination recomputes the pod's compliance flag,
        and if the ratio is found in violation the pod is automatically
        suspended — its `status` moves to `SUSPENDED` and its `posture` to
        `FROZEN` without any separate officer action."

        Design: Difficulty/transitive_cascade/guide_terminate_cascade_depth_2
        """
        set_clock("2026-08-15T00:00:00Z")
        # 12 enrolled seats, one ACTIVE CERTIFIED guide assignment, plus a
        # SCHEDULED replacement window (starting beyond the 7-day waiver
        # horizon) so the staffing-floor guard of PRD 3.4 passes: projected
        # FTE over the remaining SCHEDULED assignment still satisfies
        # min_guides_required, while the same-window ACTIVE ratio collapses
        # to zero and trips the violation cascade.
        ctx = setup_active_pod_with_enrolled_seats(
            num_seats=12, seat_capacity=12, clock="2026-08-15T00:00:00Z",
        )
        pod = ctx["pod"]
        guide2 = create_guide()
        create_guide_assignment(
            pod["id"], guide2["id"],
            window_start_date="2026-09-01", window_end_date="2027-05-31",
            weekly_hours=30, is_primary=False,
        )
        asg = validate_success(
            api.get_guide_assignment(ctx["assignment"]["id"], OPERATOR)
        )
        assert asg["assignment_status"] == "ACTIVE", (
            "fixture clock must have driven the assignment to ACTIVE, got "
            f"{asg['assignment_status']}"
        )
        terminated = validate_success(
            api.terminate_guide_assignment(pod["id"], asg["id"], OPERATOR)
        )
        assert terminated["assignment_status"] == "TERMINATED_EARLY"

        pod_now = get_pod(pod["id"])
        assert pod_now["compliance_flag"] == "VIOLATION", (
            f"0 FTE across 12 enrolled seats must be VIOLATION, got "
            f"{pod_now['compliance_flag']}"
        )
        assert pod_now["status"] == "SUSPENDED"
        assert pod_now["posture"] == "FROZEN"

    def test_frozen_pod_blocks_seat_reservation_after_termination(self, api):
        """PRD 2.8: "A pod whose `posture` is `FROZEN` refuses five
        categories of child mutation with `ERR_POD_FROZEN` (HTTP 409):
        reserving a seat, enrolling a reserved seat, withdrawing an enrolled
        seat, requesting a progress conference, and scheduling a guide
        assignment."
        PRD 3.4: "The termination recomputes the pod's compliance flag, and
        if the ratio is found in violation the pod is automatically
        suspended — its `status` moves to `SUSPENDED` and its `posture` to
        `FROZEN` without any separate officer action."

        Design: Difficulty/transitive_cascade/guide_terminate_cascade_depth_2
        """
        from test_helpers import create_seat_payload
        from test_helpers.fixtures import create_family, create_student

        set_clock("2026-08-15T00:00:00Z")
        ctx = setup_active_pod_with_enrolled_seats(
            num_seats=12, seat_capacity=12, clock="2026-08-15T00:00:00Z",
        )
        pod = ctx["pod"]
        # Replacement assignment keeps the staffing-floor guard of PRD 3.4
        # satisfied so the termination itself is permitted and the ratio
        # violation cascade is what drives the pod to SUSPENDED/FROZEN.
        guide2 = create_guide()
        create_guide_assignment(
            pod["id"], guide2["id"],
            window_start_date="2026-09-01", window_end_date="2027-05-31",
            weekly_hours=30, is_primary=False,
        )
        validate_success(
            api.terminate_guide_assignment(pod["id"], ctx["assignment"]["id"],
                                           OPERATOR)
        )
        pod_now = get_pod(pod["id"])
        assert pod_now["posture"] == "FROZEN"

        family = create_family()
        student = create_student(family["id"])
        resp = api.create_seat(
            pod["id"],
            create_seat_payload(student["id"], enrolled_on="2026-08-15"),
            TEST_USERS["registrar_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_POD_FROZEN, expected_status=409)
