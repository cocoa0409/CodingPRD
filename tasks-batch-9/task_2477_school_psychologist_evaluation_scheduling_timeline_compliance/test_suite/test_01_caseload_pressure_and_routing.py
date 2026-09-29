"""Caseload pressure, the server-side selector, and point conservation on re-routing."""
import pytest

from test_helpers import (
    AssessmentStatus,
    CaseloadStatus,
    ComplianceStatus,
    assert_caseload_points_conserved,
    assert_evaluation,
    assert_psychologist,
    fixtures,
)

INDEX = dict(abs=1e-9)


def _divergent_pressure_district():
    """Two evaluators with equal capacity whose pressure variants disagree.

    Psychologist B carries one five-point case that a sweep has driven to
    `BREACHED`; psychologist A carries one nine-point case consented on the day
    the clock now reads, so it is still `ON_TRACK`. A third five-point referral
    waits in `PENDING_ASSIGNMENT`.
    """
    fixtures.set_clock("2026-08-01T00:00:00Z")
    school = fixtures.create_school(
        name="Northside Elementary",
        building_code="NS01",
        grade_band="ELEMENTARY",
        concurrent_meeting_capacity=1,
        enrollment_count=480,
    )
    psych_a = fixtures.create_psychologist(
        [school["id"]],
        full_name="Ana Reyes",
        employee_number="E-1001",
        credential_type="SSP",
        languages_certified=["en"],
        weekly_capacity_points=20,
    )
    psych_b = fixtures.create_psychologist(
        [school["id"]],
        full_name="Ben Okoro",
        employee_number="E-1002",
        credential_type="SSP",
        languages_certified=["en"],
        weekly_capacity_points=20,
    )

    _, evaluation_b = fixtures.consented_referral(
        school["id"],
        student_local_id="STU-B",
        requested_domains=["COGNITIVE"],
        intervention_team_summary="tier 3 reading",
    )
    fixtures.assign_evaluator(evaluation_b["id"], psych_b["id"])

    fixtures.set_clock("2026-10-01T12:00:00Z")
    fixtures.run_sweep()

    _, evaluation_a = fixtures.consented_referral(
        school["id"],
        effective_at="2026-10-01T09:00:00Z",
        student_local_id="STU-A",
        interpreter_required=True,
        requested_domains=["COGNITIVE", "ACADEMIC", "SOCIAL_EMOTIONAL"],
        intervention_team_summary="tier 3 multi-domain",
    )
    fixtures.assign_evaluator(evaluation_a["id"], psych_a["id"])

    _, evaluation_c = fixtures.consented_referral(
        school["id"],
        effective_at="2026-10-01T09:00:00Z",
        student_local_id="STU-C",
        requested_domains=["COGNITIVE"],
        intervention_team_summary="tier 2 math",
    )
    return {
        "school": school,
        "psych_a": psych_a,
        "psych_b": psych_b,
        "evaluation_a": evaluation_a,
        "evaluation_b": evaluation_b,
        "evaluation_c": evaluation_c,
    }


def _reassignment_district():
    """One nine-point evaluation assigned to the first of two covering evaluators."""
    fixtures.set_clock("2026-08-01T00:00:00Z")
    school = fixtures.create_school(
        name="Rosewood Elementary",
        building_code="RW19",
        grade_band="ELEMENTARY",
        concurrent_meeting_capacity=2,
        enrollment_count=400,
    )
    psych_a = fixtures.create_psychologist(
        [school["id"]],
        full_name="Rita Vance",
        employee_number="E-1019",
        credential_type="SSP",
        weekly_capacity_points=20,
    )
    psych_b = fixtures.create_psychologist(
        [school["id"]],
        full_name="Sam Ito",
        employee_number="E-1020",
        credential_type="SSP",
        weekly_capacity_points=20,
    )
    _, evaluation = fixtures.consented_referral(
        school["id"],
        student_local_id="STU-V",
        primary_language="es",
        interpreter_required=True,
        requested_domains=["COGNITIVE", "ACADEMIC", "SOCIAL_EMOTIONAL"],
    )
    evaluation = fixtures.assign_evaluator(evaluation["id"], psych_a["id"])
    return {
        "school": school,
        "psych_a": psych_a,
        "psych_b": psych_b,
        "evaluation": evaluation,
    }


def test_pressure_variants_order_two_evaluators_oppositely():
    """The breached case makes B heavier on one variant and lighter on the other.

    "The two figures are identical while every open case is `ON_TRACK` and diverge as soon as one goes `AT_RISK` or `BREACHED`, which is the point: a psychologist carrying a single breached case can register as more loaded than a colleague carrying more raw points."

    Design: Difficulty/dual_variant_calc/pressure_index_variant_divergence_drives_selector
    """
    district = _divergent_pressure_district()

    psych_a = fixtures.get_psychologist(district["psych_a"]["id"])
    psych_b = fixtures.get_psychologist(district["psych_b"]["id"])
    assert_psychologist(psych_a)
    assert_psychologist(psych_b)

    assert psych_a["open_case_points"] == 9
    assert psych_a["pressure_index_assigned_basis"] == pytest.approx(0.45, **INDEX)
    assert psych_a["pressure_index_clock_weighted"] == pytest.approx(0.45, **INDEX)

    assert psych_b["open_case_points"] == 5
    assert psych_b["pressure_index_assigned_basis"] == pytest.approx(0.25, **INDEX)
    assert psych_b["pressure_index_clock_weighted"] == pytest.approx(0.50, **INDEX)

    # The two views rank the same two rows in opposite directions.
    assert (
        psych_b["pressure_index_assigned_basis"]
        < psych_a["pressure_index_assigned_basis"]
    )
    assert (
        psych_b["pressure_index_clock_weighted"]
        > psych_a["pressure_index_clock_weighted"]
    )

    breached = fixtures.get_evaluation(district["evaluation_b"]["id"])
    assert breached["compliance_status"] == ComplianceStatus.BREACHED.value
    on_track = fixtures.get_evaluation(district["evaluation_a"]["id"])
    assert on_track["compliance_status"] == ComplianceStatus.ON_TRACK.value


def test_selector_picks_the_winner_of_the_clock_weighted_ranking():
    """A wins at 0.35 against B at 0.40, the reverse of the assigned-basis order.

    "The clock-weighted figure is the one the assignment selector ranks on."

    Design: Difficulty/dual_variant_calc/pressure_index_variant_divergence_drives_selector
    """
    district = _divergent_pressure_district()

    routed = fixtures.assign_evaluator(district["evaluation_c"]["id"])

    assert_evaluation(routed)
    assert routed["psychologist_id"] == district["psych_a"]["id"]
    assert routed["assessment_status"] == AssessmentStatus.ASSIGNED.value
    assert routed["caseload_points"] == 5


def test_selector_routing_re_derives_only_the_winning_caseload():
    """The winner's three figures move together; the loser's are untouched.

    "Whichever mode resolved the target, the successful routing sets `psychologist_id` on the evaluation, increments the evaluation's `version` by one, and re-derives the newly assigned psychologist's `open_case_points`, `caseload_status`, `pressure_index_assigned_basis` and `pressure_index_clock_weighted`."

    Design: Difficulty/dual_variant_calc/pressure_index_variant_divergence_drives_selector
    """
    district = _divergent_pressure_district()

    fixtures.assign_evaluator(district["evaluation_c"]["id"])

    psych_a = fixtures.get_psychologist(district["psych_a"]["id"])
    assert psych_a["open_case_points"] == 14
    assert psych_a["caseload_status"] == CaseloadStatus.BALANCED.value
    assert psych_a["pressure_index_assigned_basis"] == pytest.approx(0.70, **INDEX)
    assert psych_a["pressure_index_clock_weighted"] == pytest.approx(0.70, **INDEX)

    psych_b = fixtures.get_psychologist(district["psych_b"]["id"])
    assert psych_b["open_case_points"] == 5


def test_reassignment_moves_every_point_to_the_incoming_evaluator():
    """The outgoing evaluator drops the nine points the incoming one gains.

    "Reassigning it is the compensating action: the outgoing psychologist loses exactly that evaluation's `caseload_points` and the incoming psychologist gains exactly the same number, so the district total is unchanged."

    Design: Difficulty/compensating_invariant/reassignment_conserves_district_caseload_points
    """
    district = _reassignment_district()

    before_a = fixtures.get_psychologist(district["psych_a"]["id"])
    before_b = fixtures.get_psychologist(district["psych_b"]["id"])
    assert before_a["open_case_points"] == 9
    assert before_b["open_case_points"] == 0

    fixtures.assign_evaluator(
        district["evaluation"]["id"], district["psych_b"]["id"]
    )

    after_a = fixtures.get_psychologist(district["psych_a"]["id"])
    after_b = fixtures.get_psychologist(district["psych_b"]["id"])
    assert_psychologist(after_a)
    assert_psychologist(after_b)

    assert after_a["open_case_points"] == 0
    assert after_a["caseload_status"] == CaseloadStatus.BALANCED.value
    assert after_a["pressure_index_assigned_basis"] == pytest.approx(0.0, **INDEX)
    assert after_a["pressure_index_clock_weighted"] == pytest.approx(0.0, **INDEX)

    assert after_b["open_case_points"] == 9
    assert after_b["pressure_index_assigned_basis"] == pytest.approx(0.45, **INDEX)
    assert after_b["pressure_index_clock_weighted"] == pytest.approx(0.45, **INDEX)


def test_reassignment_leaves_the_district_point_total_unchanged():
    """Nine points before, nine points after, on both sides of the identity.

    "The sum of `open_case_points` across all psychologists equals the sum of `caseload_points` across every evaluation that has a non-null `psychologist_id` and sits in one of the four open assessment statuses (`ASSIGNED`, `IN_TESTING`, `SCORED`, `REPORT_DRAFTED`)."

    Design: Difficulty/compensating_invariant/reassignment_conserves_district_caseload_points
    """
    district = _reassignment_district()
    ids = [district["psych_a"]["id"], district["psych_b"]["id"]]

    before_people = [fixtures.get_psychologist(pid) for pid in ids]
    before_evaluation = fixtures.get_evaluation(district["evaluation"]["id"])
    assert sum(p["open_case_points"] for p in before_people) == 9
    assert_caseload_points_conserved(before_people, [before_evaluation])

    fixtures.assign_evaluator(
        district["evaluation"]["id"], district["psych_b"]["id"]
    )

    after_people = [fixtures.get_psychologist(pid) for pid in ids]
    after_evaluation = fixtures.get_evaluation(district["evaluation"]["id"])
    assert sum(p["open_case_points"] for p in after_people) == 9
    assert after_evaluation["caseload_points"] == 9
    assert_caseload_points_conserved(after_people, [after_evaluation])


def test_reassignment_counts_the_re_route_and_advances_the_version():
    """The evaluation records the re-route and moves past the guard value used.

    "A genuine reassignment additionally increments `reassignment_count` by one and re-derives the caseload figures for **both** psychologists, the outgoing and the incoming."

    Design: Difficulty/compensating_invariant/reassignment_conserves_district_caseload_points
    """
    district = _reassignment_district()
    guard_version = fixtures.evaluation_version(district["evaluation"]["id"])

    reassigned = fixtures.assign_evaluator(
        district["evaluation"]["id"],
        district["psych_b"]["id"],
        expected_version=guard_version,
    )

    assert reassigned["psychologist_id"] == district["psych_b"]["id"]
    assert reassigned["assessment_status"] == AssessmentStatus.ASSIGNED.value
    assert reassigned["reassignment_count"] == 1
    assert reassigned["version"] > guard_version
