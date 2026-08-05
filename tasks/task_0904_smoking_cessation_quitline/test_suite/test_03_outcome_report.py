"""Program outcome report: point-prevalence vs continuous rates and empty cohorts."""
from test_helpers import (
    validate_success, TEST_USERS,
    set_clock, create_program, create_participant, create_enrollment,
    submit_readiness, activate, create_quit_attempt, record_follow_up,
    setup_active_enrollment,
)

PA = TEST_USERS["program_admin_headers"]
CM = TEST_USERS["case_manager_headers"]


def _build_two_participant_cohort(api):
    """Two sponsored EN participants: both 7-day abstinent; P1 also 30-day abstinent
    (continuous), P2 not. Clock advanced past quit_date + 30 days so both mature."""
    set_clock(api, "2026-06-01T00:00:00Z")
    program = create_program(api, budget=1000000, nrt_allotted=3)
    ids = []
    for _ in range(2):
        part = create_participant(api, cpd=10, program_id=program["id"])
        enr = create_enrollment(api, part["id"])
        submit_readiness(api, enr["id"], 6, 6, 0)
        activate(api, enr["id"])
        create_quit_attempt(api, enr["id"], "2026-06-02T00:00:00Z", "COLD_TURKEY")
        ids.append(enr["id"])
    set_clock(api, "2026-06-09T00:00:00Z")
    record_follow_up(api, ids[0], 7, True)
    record_follow_up(api, ids[1], 7, True)
    set_clock(api, "2026-07-02T00:00:00Z")
    record_follow_up(api, ids[0], 30, True)
    record_follow_up(api, ids[1], 30, False)
    return program


def test_outcome_report_point_prevalence_vs_continuous(api):
    """PRD §3.9: "the `point_prevalence_7day_rate` is 100 times the count of cohort
    enrollments having a seven-day abstinent outcome, divided by the cohort size,
    rounded half up to one decimal place; and the `continuous_30day_rate` is 100
    times the count of cohort enrollments having both a seven-day abstinent outcome
    and a thirty-day abstinent outcome, divided by the cohort size, rounded half up
    to one decimal place."

    Design: Difficulty/dual_variant_calc/abstinence_point_prevalence_vs_continuous_rate
    """
    program = _build_two_participant_cohort(api)
    report = validate_success(api.get_outcome_report(program["id"], PA))
    assert report["cohort_size"] == 2
    assert report["point_prevalence_7day_rate"] == 100.0
    assert report["continuous_30day_rate"] == 50.0


def test_outcome_report_continuous_never_exceeds_point_prevalence(api):
    """PRD §3.9: "Because the continuous numerator counts a subset of the
    point-prevalence numerator, the continuous rate never exceeds the seven-day rate."

    Design: Difficulty/dual_variant_calc/abstinence_point_prevalence_vs_continuous_rate
    """
    program = _build_two_participant_cohort(api)
    report = validate_success(api.get_outcome_report(program["id"], PA))
    assert report["continuous_30day_rate"] <= report["point_prevalence_7day_rate"]
    assert report["continuous_30day_rate"] == 50.0


def test_outcome_report_empty_program_returns_zero(api):
    """PRD §3.9: "When the cohort is empty both rates are 0.0."

    Design: Difficulty/boundary_precision_check/outcome_report_empty_cohort_returns_zero
    """
    program = create_program(api, budget=100000, nrt_allotted=3)
    report = validate_success(api.get_outcome_report(program["id"], PA))
    assert report["cohort_size"] == 0
    assert report["point_prevalence_7day_rate"] == 0.0
    assert report["continuous_30day_rate"] == 0.0


def test_outcome_report_immature_quit_date_excluded_from_cohort(api):
    """PRD §3.9: "The cohort is every enrollment of a participant whose
    `employer_program_id` is this program, provided the enrollment has at least one
    quit attempt whose `quit_date` is set and the current clock time is at or after
    that quit date plus 30 days."
    PRD §3.9: "When the cohort is empty both rates are 0.0."

    Design: Difficulty/boundary_precision_check/outcome_report_empty_cohort_returns_zero
    """
    set_clock(api, "2026-06-01T00:00:00Z")
    program = create_program(api, budget=100000, nrt_allotted=3)
    part = create_participant(api, cpd=10, program_id=program["id"])
    enr = create_enrollment(api, part["id"])
    submit_readiness(api, enr["id"], 6, 6, 0)
    activate(api, enr["id"])
    create_quit_attempt(api, enr["id"], "2026-06-02T00:00:00Z", "COLD_TURKEY")
    # Clock still well before quit_date + 30 days (2026-07-02): enrollment not mature.
    set_clock(api, "2026-06-15T00:00:00Z")
    report = validate_success(api.get_outcome_report(program["id"], PA))
    assert report["cohort_size"] == 0
    assert report["point_prevalence_7day_rate"] == 0.0
    assert report["continuous_30day_rate"] == 0.0
