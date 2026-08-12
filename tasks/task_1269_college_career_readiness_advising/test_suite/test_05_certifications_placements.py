"""Certifications and work-based-learning placements.

PRD §3.6 (certification machine, cert points, placement intervals, site
capacity), §2.6 (pipeline precedence).
"""
import pytest

from test_helpers import (
    TEST_USERS, ApiErrorId, assert_certification, assert_pct, assert_placement,
    complete_placement, confirm_placement, create_active_plan, create_advisor,
    create_certification, create_pathway, create_placement, create_site,
    create_student, get_plan, pass_certification, schedule_certification,
    set_clock, setup_student_with_active_plan, transition_certification,
    transition_placement, validate_error, validate_success,
)

ADMIN = TEST_USERS["district_admin_headers"]
WBL = TEST_USERS["wbl_coordinator_headers"]


class TestCertificationRetakeLoop:
    """Difficulty instance: REGISTERED -> EXAM_SCHEDULED -> FAILED ->
    EXAM_SCHEDULED -> PASSED with retake_count as loop-carried state."""

    def _setup_failed_cert(self):
        advisor = create_advisor(full_name="C Adv", max_caseload=50)
        student = create_student(student_ref="C001", grade_level=10,
                                 demographic_group="GROUP_C",
                                 advisor_id=advisor["id"])
        cert = create_certification(student["id"], "OSHA")
        schedule_certification(cert["id"], "2026-05-10T09:00:00Z")
        transition_certification(cert["id"], "FAILED")
        return student, cert

    def test_retake_increments_count_and_overwrites_exam(self, api):
        """PRD §3.6: "A `FAILED` attempt may be rescheduled to
        `EXAM_SCHEDULED` with a fresh future `exam_at`, incrementing
        `retake_count` by 1 and overwriting `exam_at`."

        Design: Difficulty/non_linear_state_machine/certification_retake_loop
        """
        student, cert = self._setup_failed_cert()
        retaken = transition_certification(cert["id"], "EXAM_SCHEDULED",
                                           exam_at="2026-05-20T09:00:00Z")
        assert retaken["status"] == "EXAM_SCHEDULED"
        assert retaken["retake_count"] == 1
        assert retaken["exam_at"].startswith("2026-05-20T09:00"), (
            f"exam_at must be overwritten by the retake, got "
            f"{retaken['exam_at']!r}"
        )

    def test_retake_loop_can_reach_passed(self, api):
        """PRD §3.6: "From `EXAM_SCHEDULED` the outcome is binary: `PASSED`
        stamps `earned_at` ... while `FAILED` simply increments the record's
        `version` and opens the retake loop."

        Design: Difficulty/non_linear_state_machine/certification_retake_loop
        """
        student, cert = self._setup_failed_cert()
        transition_certification(cert["id"], "EXAM_SCHEDULED",
                                 exam_at="2026-05-20T09:00:00Z")
        passed = transition_certification(cert["id"], "PASSED")
        assert_certification(passed)
        assert passed["status"] == "PASSED"
        assert passed["retake_count"] == 1
        assert passed["earned_at"] is not None


class TestCertificationPoints:
    def test_certification_points_levels(self, api):
        """PRD §3.6: "When the plan's pathway carries a null
        `required_certification_code`, the component is 100. Otherwise, a
        `PASSED` certification whose `cert_code` matches the required code
        scores the full 100; a `PASSED` certification in any other code earns
        partial credit of 50; and no pass at all scores 0."

        Design: Corner/calculations/certification_points_levels
        """
        advisor = create_advisor(max_caseload=10)
        pw_req = create_pathway(pathway_code="HLTH",
                                required_certification_code="CNA",
                                required_work_hours=0)
        pw_free = create_pathway(pathway_code="FREE")
        s1 = create_student(student_ref="CP1", advisor_id=advisor["id"])
        p1 = create_active_plan(s1, pw_req["id"], advisor["id"])
        s2 = create_student(student_ref="CP2", demographic_group="GROUP_B",
                            advisor_id=advisor["id"])
        p2 = create_active_plan(s2, pw_free["id"], advisor["id"])

        pass_certification(s1["id"], "OSHA", exam_at="2026-05-10T09:00:00Z")
        cna = create_certification(s1["id"], "CNA")
        schedule_certification(cna["id"], "2026-05-12T09:00:00Z")

        plan_mid = get_plan(p1["id"])
        assert plan_mid["certification_points"] == 50, (
            "OSHA passed but the required CNA is only scheduled"
        )

        transition_certification(cna["id"], "PASSED")
        plan_after = get_plan(p1["id"])
        assert plan_after["certification_points"] == 100

        plan_free = get_plan(p2["id"])
        assert plan_free["certification_points"] == 100, (
            "a pathway with no required certification scores 100"
        )


class TestPlacementCreationAndStart:
    def test_placement_invalid_term_returns_422(self, api):
        """PRD §3.6: "The interval is half-open: `term_start` is inclusive,
        `term_end` is exclusive, and an end that does not fall strictly after
        the start is rejected with `ERR_INVALID_TERM` (HTTP 422) at the early
        pipeline stage noted in §2.6, ahead of role and existence checks."

        Design: Corner/validations/placement_invalid_term_returns_422
        """
        advisor = create_advisor(max_caseload=10)
        site = create_site(site_code="VT", max_concurrent_placements=5)
        student = create_student(student_ref="VT1", advisor_id=advisor["id"])
        resp = api.create_placement(
            student["id"],
            {"site_id": site["id"], "term_start": "2026-06-01T00:00:00Z",
             "term_end": "2026-05-01T00:00:00Z", "hours_per_week": 10},
            WBL,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_TERM)

    def test_placement_start_before_term_returns_409(self, api):
        """PRD §3.6: "A `CONFIRMED` placement goes `ACTIVE` once the logical
        clock reaches `term_start`; attempting the move early is
        `ERR_TERM_NOT_STARTED`."

        Design: Corner/validations/placement_start_before_term_returns_409
        """
        advisor = create_advisor(max_caseload=10)
        site = create_site(site_code="TS", max_concurrent_placements=5)
        student = create_student(student_ref="TS1", advisor_id=advisor["id"])
        placement = create_placement(student["id"], site["id"],
                                     "2026-06-01T00:00:00Z",
                                     "2026-08-01T00:00:00Z", 10)
        confirm_placement(placement["id"])

        early = api.transition_placement(placement["id"],
                                         {"to_status": "ACTIVE"}, WBL)
        validate_error(early, ApiErrorId.ERR_TERM_NOT_STARTED)

        set_clock("2026-06-01T09:00:00Z")
        activated = validate_success(
            api.transition_placement(placement["id"], {"to_status": "ACTIVE"},
                                     WBL))
        assert activated["status"] == "ACTIVE"


class TestPairwiseOverlap:
    """Difficulty instance: half-open pairwise exclusion on one student's
    timeline."""

    def _setup_pairwise(self):
        advisor = create_advisor(max_caseload=50)
        site = create_site(site_code="SP", max_concurrent_placements=10)
        student = create_student(student_ref="H001", advisor_id=advisor["id"])
        p1 = create_placement(student["id"], site["id"],
                              "2026-04-01T00:00:00Z", "2026-05-01T00:00:00Z",
                              10)
        confirm_placement(p1["id"])
        p2 = create_placement(student["id"], site["id"],
                              "2026-05-01T00:00:00Z", "2026-06-01T00:00:00Z",
                              10)
        p3 = create_placement(student["id"], site["id"],
                              "2026-04-15T00:00:00Z", "2026-05-15T00:00:00Z",
                              10)
        return student, p1, p2, p3

    def test_adjacent_half_open_intervals_do_not_overlap(self, api):
        """PRD §3.6: "The pairwise rule treats intervals as half-open — an
        existing placement and the candidate overlap only when the existing
        start falls strictly before the candidate end and the candidate start
        falls strictly before the existing end, so a placement ending exactly
        when another begins is adjacency, not overlap".

        Design: Difficulty/resource_temporal_overlap/student_pairwise_half_open_overlap
        """
        student, p1, p2, p3 = self._setup_pairwise()
        confirmed = confirm_placement(p2["id"])
        assert_placement(confirmed)
        assert confirmed["status"] == "CONFIRMED", (
            "[05-01, 06-01) touches [04-01, 05-01) but does not overlap it"
        )

    def test_interior_overlap_rejected(self, api):
        """PRD §3.6: "a violation is `ERR_PLACEMENT_OVERLAP`" of the rule that
        "the new interval must not pairwise-overlap any of the student's other
        `CONFIRMED` or `ACTIVE` placements".

        Design: Difficulty/resource_temporal_overlap/student_pairwise_half_open_overlap
        """
        student, p1, p2, p3 = self._setup_pairwise()
        confirm_placement(p2["id"])
        resp = api.transition_placement(p3["id"], {"to_status": "CONFIRMED"},
                                        WBL)
        validate_error(resp, ApiErrorId.ERR_PLACEMENT_OVERLAP)
        after = validate_success(api.get_placement(p3["id"], ADMIN))
        assert after["status"] == "OFFERED"


class TestSiteAggregateCapacity:
    """Difficulty instance: aggregate interval capacity across students."""

    def _setup_aggregate(self):
        advisor = create_advisor(max_caseload=50)
        site = create_site(site_code="SG", max_concurrent_placements=2)
        sa = create_student(student_ref="I001", advisor_id=advisor["id"])
        sb = create_student(student_ref="I002", demographic_group="GROUP_B",
                            advisor_id=advisor["id"])
        sc = create_student(student_ref="I003", demographic_group="GROUP_C",
                            advisor_id=advisor["id"])
        pa = create_placement(sa["id"], site["id"], "2026-05-04T00:00:00Z",
                              "2026-06-04T00:00:00Z", 10)
        confirm_placement(pa["id"])
        pb = create_placement(sb["id"], site["id"], "2026-05-10T00:00:00Z",
                              "2026-06-10T00:00:00Z", 10)
        confirm_placement(pb["id"])
        pc = create_placement(sc["id"], site["id"], "2026-05-15T00:00:00Z",
                              "2026-05-20T00:00:00Z", 10)
        pd = create_placement(sc["id"], site["id"], "2026-06-04T00:00:00Z",
                              "2026-07-01T00:00:00Z", 10)
        return site, pa, pb, pc, pd

    def test_third_overlapping_confirm_rejected(self, api):
        """PRD §3.6: "the largest count — 0 when no evaluation points exist —
        plus the candidate itself must not exceed `max_concurrent_placements`,
        on pain of `ERR_SITE_CAPACITY_EXCEEDED`."

        Design: Difficulty/resource_temporal_overlap/site_aggregate_capacity_overlap
        """
        site, pa, pb, pc, pd = self._setup_aggregate()
        resp = api.transition_placement(pc["id"], {"to_status": "CONFIRMED"},
                                        WBL)
        validate_error(resp, ApiErrorId.ERR_SITE_CAPACITY_EXCEEDED)
        assert resp.json()["data"]["error_id"] != \
            ApiErrorId.ERR_PLACEMENT_OVERLAP.value, (
                "each student holds at most one placement here; the pairwise "
                "rule must not fire"
            )

    def test_adjacent_confirm_after_expiry_allowed(self, api):
        """PRD §3.6: "The interval is half-open: `term_start` is inclusive,
        `term_end` is exclusive". PRD §3.6: "at each such point, the overlap
        count is the number of those existing placements whose half-open
        interval contains the point; and the largest count — 0 when no
        evaluation points exist — plus the candidate itself must not exceed
        `max_concurrent_placements`, on pain of `ERR_SITE_CAPACITY_EXCEEDED`."

        Design: Difficulty/resource_temporal_overlap/site_aggregate_capacity_overlap
        """
        site, pa, pb, pc, pd = self._setup_aggregate()
        api.transition_placement(pc["id"], {"to_status": "CONFIRMED"}, WBL)
        confirmed = validate_success(
            api.transition_placement(pd["id"], {"to_status": "CONFIRMED"},
                                     WBL))
        assert confirmed["status"] == "CONFIRMED", (
            "at t=2026-06-04 only one existing interval occupies the site"
        )


class TestSiteCapacityBoundary:
    """Difficulty instance: exact-equality boundary on the aggregate rule."""

    def _setup_capacity_boundary(self):
        advisor = create_advisor(max_caseload=50)
        site = create_site(site_code="SC", max_concurrent_placements=2)
        sa = create_student(student_ref="SC1", advisor_id=advisor["id"])
        sb = create_student(student_ref="SC2", demographic_group="GROUP_B",
                            advisor_id=advisor["id"])
        sc = create_student(student_ref="SC3", demographic_group="GROUP_C",
                            advisor_id=advisor["id"])
        pa = create_placement(sa["id"], site["id"], "2026-05-04T00:00:00Z",
                              "2026-06-04T00:00:00Z", 10)
        confirm_placement(pa["id"])
        pb = create_placement(sb["id"], site["id"], "2026-05-10T00:00:00Z",
                              "2026-06-10T00:00:00Z", 10)
        confirm_placement(pb["id"])
        pc = create_placement(sc["id"], site["id"], "2026-05-15T00:00:00Z",
                              "2026-05-20T00:00:00Z", 10)
        pc2 = create_placement(sc["id"], site["id"], "2026-06-04T00:00:00Z",
                               "2026-07-01T00:00:00Z", 10)
        return site, pa, pb, pc, pc2

    def test_exact_max_allowed_and_overflow_rejected(self, api):
        """PRD §3.6: "at each such point, the overlap count is the number of
        those existing placements whose half-open interval contains the point;
        and the largest count — 0 when no evaluation points exist — plus the
        candidate itself must not exceed `max_concurrent_placements`, on pain
        of `ERR_SITE_CAPACITY_EXCEEDED`."

        Design: Difficulty/boundary_precision_check/site_capacity_at_exact_max
        """
        site, pa, pb, pc, pc2 = self._setup_capacity_boundary()
        # P_A and P_B both confirmed: overlap max reached exactly 2 == max.
        assert validate_success(api.get_placement(pa["id"], ADMIN))[
            "status"] == "CONFIRMED"
        assert validate_success(api.get_placement(pb["id"], ADMIN))[
            "status"] == "CONFIRMED"
        # P_C would push the overlap maximum to 3.
        resp = api.transition_placement(pc["id"], {"to_status": "CONFIRMED"},
                                        WBL)
        validate_error(resp, ApiErrorId.ERR_SITE_CAPACITY_EXCEEDED)
        assert validate_success(api.get_placement(pc["id"], ADMIN))[
            "status"] == "OFFERED"

    def test_adjacent_after_expiry_and_display_count(self, api):
        """PRD §3.6: "a placement ending exactly when another begins is
        adjacency, not overlap". PRD §3.6: "The site record carries
        `confirmed_active_count`, a display count of its `CONFIRMED` and
        `ACTIVE` placements".

        Design: Difficulty/boundary_precision_check/site_capacity_at_exact_max
        """
        site, pa, pb, pc, pc2 = self._setup_capacity_boundary()
        api.transition_placement(pc["id"], {"to_status": "CONFIRMED"}, WBL)
        confirmed = validate_success(
            api.transition_placement(pc2["id"], {"to_status": "CONFIRMED"},
                                     WBL))
        assert confirmed["status"] == "CONFIRMED"
        site_after = validate_success(api.get_placement_site(site["id"],
                                                             ADMIN))
        assert site_after["confirmed_active_count"] == 3


class TestSiteSlotConservation:
    """Difficulty instance: confirmed_active_count returns to its prior value
    across a confirm/terminate pair."""

    def _setup_offered(self):
        advisor = create_advisor(max_caseload=50)
        site = create_site(site_code="SL", max_concurrent_placements=5)
        student = create_student(student_ref="L001", advisor_id=advisor["id"])
        placement = create_placement(student["id"], site["id"],
                                     "2026-04-01T00:00:00Z",
                                     "2026-06-01T00:00:00Z", 10)
        return site, placement

    def test_confirm_then_terminate_restores_count(self, api):
        """PRD §3.6: "Termination records its cause in `terminated_reason` —
        `MANUAL` for a direct coordinator action". PRD §3.6: "A confirmed
        placement increments its `version` and the site's
        `confirmed_active_count` recomputes."

        Design: Difficulty/compensating_invariant/site_slot_conserved_on_confirm_terminate
        """
        site, placement = self._setup_offered()
        before = validate_success(api.get_placement_site(site["id"], ADMIN))
        assert before["confirmed_active_count"] == 0

        confirm_placement(placement["id"])
        mid = validate_success(api.get_placement_site(site["id"], ADMIN))
        assert mid["confirmed_active_count"] == 1

        terminated = transition_placement(placement["id"], "TERMINATED")
        assert_placement(terminated)
        assert terminated["status"] == "TERMINATED"
        assert terminated["terminated_reason"] == "MANUAL"

        after = validate_success(api.get_placement_site(site["id"], ADMIN))
        assert after["confirmed_active_count"] == 0, (
            "CONFIRMED followed by TERMINATED must leave no ledger drift"
        )

    def test_terminated_placement_keeps_zero_hours(self, api):
        """PRD §3.6: "Hours only ever arrive through completion: a placement
        terminated from `CONFIRMED` or `ACTIVE` keeps `hours_logged` at 0."

        Design: Difficulty/compensating_invariant/site_slot_conserved_on_confirm_terminate
        """
        site, placement = self._setup_offered()
        confirm_placement(placement["id"])
        terminated = transition_placement(placement["id"], "TERMINATED")
        assert terminated["hours_logged"] == 0
        site_after = validate_success(api.get_placement_site(site["id"],
                                                             ADMIN))
        assert site_after["confirmed_active_count"] == 0


class TestOverlapBeatsCapacity:
    """Difficulty instance: one CONFIRM violating both the pairwise rule and
    the aggregate capacity rule reports the earlier pipeline stage."""

    def _setup_double_violation(self):
        advisor = create_advisor(max_caseload=50)
        site1 = create_site(site_code="S1", max_concurrent_placements=1)
        site2 = create_site(site_code="S2", max_concurrent_placements=10)
        sa = create_student(student_ref="W001", advisor_id=advisor["id"])
        sb = create_student(student_ref="W002", demographic_group="GROUP_B",
                            advisor_id=advisor["id"])
        pa = create_placement(sa["id"], site1["id"], "2026-04-01T00:00:00Z",
                              "2026-06-01T00:00:00Z", 10)
        confirm_placement(pa["id"])  # site1 now at max 1
        pb0 = create_placement(sb["id"], site2["id"], "2026-04-10T00:00:00Z",
                               "2026-05-10T00:00:00Z", 8)
        confirm_placement(pb0["id"])
        pb1 = create_placement(sb["id"], site1["id"], "2026-04-15T00:00:00Z",
                               "2026-05-15T00:00:00Z", 8)
        return site1, site2, sb, pb1

    def test_overlap_error_outranks_capacity_error(self, api):
        """PRD §2.6: "When a request violates rules belonging to more than one
        stage, the stage that sits earliest in the pipeline determines the
        reported error; later failures are masked until the earlier one is
        resolved." PRD §2.6 stage 11 names `ERR_PLACEMENT_OVERLAP` among the
        clock-relative rules; stage 13 names `ERR_SITE_CAPACITY_EXCEEDED`
        among capacity and quota.

        Design: Difficulty/priority_pair_validation_conflict/placement_confirm_overlap_beats_capacity
        """
        site1, site2, sb, pb1 = self._setup_double_violation()
        resp = api.transition_placement(pb1["id"], {"to_status": "CONFIRMED"},
                                        WBL)
        validate_error(resp, ApiErrorId.ERR_PLACEMENT_OVERLAP)
        assert resp.json()["data"]["error_id"] != \
            ApiErrorId.ERR_SITE_CAPACITY_EXCEEDED.value

    def test_rejected_confirm_leaves_placement_offered(self, api):
        """PRD §3.6: "the new interval must not pairwise-overlap any of the
        student's other `CONFIRMED` or `ACTIVE` placements". PRD §2.4: "The
        `version` is an integer that starts at 1 when the resource is created
        and increments by exactly 1 on every mutation of that resource."

        Design: Difficulty/priority_pair_validation_conflict/placement_confirm_overlap_beats_capacity
        """
        site1, site2, sb, pb1 = self._setup_double_violation()
        before = validate_success(api.get_placement(pb1["id"], ADMIN))
        api.transition_placement(pb1["id"], {"to_status": "CONFIRMED"}, WBL)
        after = validate_success(api.get_placement(pb1["id"], ADMIN))
        assert after["status"] == "OFFERED"
        assert after["version"] == before["version"]
