"""UPCS inspections, findings, the 8823 lifecycle, and the noncompliance cascade to posture.

Translates queue A (Difficulty) instances transitive_cascade/disqualify_unit,
transitive_cascade/inspection_fail, boundary_precision_check/upcs_score,
resource_temporal_overlap/inspection_window, cross_entity_state_dependency/inspection_close,
and compensating_invariant/report_then_correct; plus queue B (Corner) finding/report
instances, the exigent-health-safety override, and the project-close guard.
"""
import pytest
from test_helpers import (
    validate_success,
    validate_error,
    get_success_data,
    TEST_USERS,
    create_project,
    create_building,
    setup_project_building,
    make_over_income_unit,
    setup_failed_inspection_with_open_finding,
    make_state_hfa_headers,
    create_inspection_payload,
)
from test_helpers import api_client

OWNER = TEST_USERS["owner_agent_headers"]
HFA = TEST_USERS["state_hfa_headers"]
HFA_1 = make_state_hfa_headers("hfa-1")
HFA_2 = make_state_hfa_headers("hfa-2")


def _findings_for_inspection(inspection_id):
    body = api_client.list_findings(HFA, params={"inspection_id": inspection_id}).json()
    return body["data"]


# ─── Difficulty: disqualify cascade (unit -> building -> project) ──

def test_disqualify_over_income_unit_zeroes_building_credit(api):
    """PRD §3.9: "Disqualification drives the unit's `li_status` to the terminal `DISQUALIFIED`
    and sets `is_low_income_counted` to false. It then cascades: the owning building's
    `applicable_fraction`, `qualified_basis_cents`, and `annual_credit_cents` are recomputed
    (Section 3.5)"

    Design: Difficulty/transitive_cascade/disqualify_unit_cascades_building_credit_then_project_posture
    """
    project, building, unit, _hh = make_over_income_unit(
        unit_overrides={
            "unit_number": "U1", "bedroom_count": 1, "sqft": 1_000,
            "utility_allowance_cents": 9_000, "ami_designation": "AMI_50",
        },
        initial_income_cents=3_000_000,
        recert_income_cents=6_000_000,  # > over140 5_376_000 -> OVER_INCOME
    )
    before = get_success_data(api.get_building(building["id"], OWNER))
    assert before["annual_credit_cents"] == 900_000  # 1 LI of 10 units -> af 0.1
    res = api.disqualify_unit(unit["id"], {"discovered_on": "2027-03-01T00:00:00Z"}, HFA)
    disq = validate_success(res, 200)
    assert disq["li_status"] == "DISQUALIFIED"
    assert disq["is_low_income_counted"] is False
    after = get_success_data(api.get_building(building["id"], OWNER))
    assert after["applicable_fraction"] == 0.0000
    assert after["annual_credit_cents"] == 0


def test_disqualify_creates_finding_and_flips_project_posture(api):
    """PRD §3.9: "a new `Finding` is created with `category` of `AVAILABLE_UNIT_VIOLATION`,
    recording the acting `StateHFA`'s `X-User-ID` as the finding's `origin_agent_id`. That
    finding in turn bumps the project's `open_finding_count` and recomputes the project's
    `posture`."
    PRD §2.8: "otherwise, if at least one finding is in `OPEN` status, the posture is
    `AT_RISK`; otherwise the posture is `COMPLIANT`."

    Design: Difficulty/transitive_cascade/disqualify_unit_cascades_building_credit_then_project_posture
    """
    project, building, unit, _hh = make_over_income_unit(
        unit_overrides={
            "unit_number": "U1", "bedroom_count": 1, "sqft": 1_000,
            "utility_allowance_cents": 9_000, "ami_designation": "AMI_50",
        },
        initial_income_cents=3_000_000,
        recert_income_cents=6_000_000,
    )
    api.disqualify_unit(unit["id"], {"discovered_on": "2027-03-01T00:00:00Z"}, HFA)
    project_after = get_success_data(api.get_project(project["id"], HFA))
    assert project_after["open_finding_count"] == 1
    assert project_after["posture"] == "AT_RISK"


# ─── Difficulty: inspection-fail cascade (inspection -> finding -> project) ──

def test_conduct_failing_inspection_computes_fail_result(api):
    """PRD §3.8: "The `score` is 100 minus the sum of all the `deduction_points`, floored at 0
    (it never goes negative). The `result` is `FAIL` if `has_exigent_health_safety` is true or
    the `score` is below the passing threshold of 60; otherwise the `result` is `PASS`."

    Design: Difficulty/transitive_cascade/inspection_fail_cascades_finding_then_project_posture
    """
    project, building = setup_project_building()
    inspection = get_success_data(
        api.create_inspection(
            create_inspection_payload(
                building["id"], deduction_points=[20, 15, 12],
                has_exigent_health_safety=False,
            ),
            HFA,
        )
    )
    conducted = validate_success(api.conduct_inspection(inspection["id"], HFA), 200)
    assert conducted["score"] == 53
    assert conducted["result"] == "FAIL"


def test_failing_inspection_bumps_finding_count_and_flips_posture(api):
    """PRD §3.8: "If the result is `FAIL`, the system creates a `Finding` whose `category` is
    `UPCS_FAIL` and whose `status` is `OPEN`, recording the conducting `StateHFA`'s
    `X-User-ID` as the finding's `origin_agent_id`; that new finding bumps the owning project's
    `open_finding_count` and recomputes the project's `posture` as the cascade described in
    Section 2.8."

    Design: Difficulty/transitive_cascade/inspection_fail_cascades_finding_then_project_posture
    """
    project, building = setup_project_building()
    inspection = get_success_data(
        api.create_inspection(
            create_inspection_payload(
                building["id"], deduction_points=[20, 15, 12],
                has_exigent_health_safety=False,
            ),
            HFA,
        )
    )
    api.conduct_inspection(inspection["id"], HFA)
    project_after = get_success_data(api.get_project(project["id"], HFA))
    assert project_after["open_finding_count"] == 1
    assert project_after["posture"] == "AT_RISK"


# ─── Difficulty: UPCS score strict-less-than-60 boundary ──

def test_upcs_score_exactly_60_passes(api):
    """PRD §3.8: "The `result` is `FAIL` if `has_exigent_health_safety` is true or the `score`
    is below the passing threshold of 60; otherwise the `result` is `PASS`."

    Design: Difficulty/boundary_precision_check/upcs_score_strict_less_than_pass_threshold_60
    """
    project, building = setup_project_building()
    inspection = get_success_data(
        api.create_inspection(
            create_inspection_payload(
                building["id"], deduction_points=[20, 20],  # score 60
                window_start="2026-03-01T00:00:00Z", window_end="2026-03-05T00:00:00Z",
                inspected_on="2026-03-03T00:00:00Z", has_exigent_health_safety=False,
            ),
            HFA,
        )
    )
    conducted = validate_success(api.conduct_inspection(inspection["id"], HFA), 200)
    assert conducted["score"] == 60
    assert conducted["result"] == "PASS"


def test_upcs_score_59_fails(api):
    """PRD §3.8: "The `result` is `FAIL` if `has_exigent_health_safety` is true or the `score`
    is below the passing threshold of 60; otherwise the `result` is `PASS`."

    Design: Difficulty/boundary_precision_check/upcs_score_strict_less_than_pass_threshold_60
    """
    project, building = setup_project_building()
    inspection = get_success_data(
        api.create_inspection(
            create_inspection_payload(
                building["id"], deduction_points=[20, 21],  # score 59
                window_start="2026-04-01T00:00:00Z", window_end="2026-04-05T00:00:00Z",
                inspected_on="2026-04-03T00:00:00Z", has_exigent_health_safety=False,
            ),
            HFA,
        )
    )
    conducted = validate_success(api.conduct_inspection(inspection["id"], HFA), 200)
    assert conducted["score"] == 59
    assert conducted["result"] == "FAIL"


# ─── Difficulty: inspection window closed-interval 7-day buffer ──

def test_inspection_window_within_seven_day_buffer_rejected(api):
    """PRD §3.8: "a new window conflicts with an existing window on the same building when the
    new start is at or before the existing end plus seven days and the existing start is at or
    before the new end plus seven days; if any existing inspection on the building conflicts
    under that buffered, closed-interval rule, the new inspection is rejected with
    `ERR_INSPECTION_WINDOW_CONFLICT`."

    Design: Difficulty/resource_temporal_overlap/inspection_window_closed_interval_seven_day_buffer_on_building
    """
    project, building = setup_project_building()
    get_success_data(
        api.create_inspection(
            create_inspection_payload(
                building["id"], window_start="2026-03-01T00:00:00Z",
                window_end="2026-03-05T00:00:00Z", inspected_on="2026-03-03T00:00:00Z",
                deduction_points=[5],
            ),
            HFA,
        )
    )
    res = api.create_inspection(
        create_inspection_payload(
            building["id"], window_start="2026-03-08T00:00:00Z",  # within 7 days of 03-05
            window_end="2026-03-09T00:00:00Z", inspected_on="2026-03-08T00:00:00Z",
            deduction_points=[5],
        ),
        HFA,
    )
    validate_error(res, "ERR_INSPECTION_WINDOW_CONFLICT", expected_status=409)


def test_inspection_window_clear_of_buffer_accepted(api):
    """PRD §3.8: "two inspections on one building must be at least a seven-day separation
    buffer apart on each side."

    Design: Difficulty/resource_temporal_overlap/inspection_window_closed_interval_seven_day_buffer_on_building
    """
    project, building = setup_project_building()
    get_success_data(
        api.create_inspection(
            create_inspection_payload(
                building["id"], window_start="2026-03-01T00:00:00Z",
                window_end="2026-03-05T00:00:00Z", inspected_on="2026-03-03T00:00:00Z",
                deduction_points=[5],
            ),
            HFA,
        )
    )
    res = api.create_inspection(
        create_inspection_payload(
            building["id"], window_start="2026-03-13T00:00:00Z",  # clears the 7-day buffer
            window_end="2026-03-14T00:00:00Z", inspected_on="2026-03-13T00:00:00Z",
            deduction_points=[5],
        ),
        HFA,
    )
    scheduled = validate_success(res, 201)
    assert scheduled["status"] == "SCHEDULED"


# ─── Difficulty: inspection close requires no open findings ──

def test_inspection_close_blocked_while_finding_open(api):
    """PRD §3.8: "When a `StateHFA` **closes** a `CONDUCTED` inspection, it advances to the
    terminal `CLOSED` status, but only when no finding linked to that inspection (matching its
    `inspection_id`) is still in `OPEN` or `REPORTED_8823` status; a close attempted while a
    linked finding remains unresolved is rejected with `ERR_OPEN_FINDINGS_BLOCK_CLOSE`."

    Design: Difficulty/cross_entity_state_dependency/inspection_close_requires_no_open_findings
    """
    project, building, inspection, _finding = setup_failed_inspection_with_open_finding()
    res = api.close_inspection(inspection["id"], HFA)
    validate_error(res, "ERR_OPEN_FINDINGS_BLOCK_CLOSE", expected_status=409)


def test_inspection_close_succeeds_after_finding_corrected(api):
    """PRD §3.8: "When a `StateHFA` **closes** a `CONDUCTED` inspection, it advances to the
    terminal `CLOSED` status, but only when no finding linked to that inspection (matching its
    `inspection_id`) is still in `OPEN` or `REPORTED_8823` status; a close attempted while a
    linked finding remains unresolved is rejected with `ERR_OPEN_FINDINGS_BLOCK_CLOSE`."
    PRD §3.9: "An `OwnerAgent` **corrects** a finding, moving it to `CORRECTED` from either
    `OPEN` or `REPORTED_8823` once the noncompliance is cured."

    Design: Difficulty/cross_entity_state_dependency/inspection_close_requires_no_open_findings
    """
    project, building, inspection, finding = setup_failed_inspection_with_open_finding()
    get_success_data(api.correct_finding(finding["id"], OWNER))
    closed = validate_success(api.close_inspection(inspection["id"], HFA), 200)
    assert closed["status"] == "CLOSED"


# ─── Difficulty: report-then-correct conserves open_finding_count ──

def test_reporting_8823_does_not_change_open_finding_count(api):
    """PRD §3.9: "Filing the 8823 sets the finding's `reported_8823_on` to the current clock
    time and recomputes the project's `posture`, which remains `NONCOMPLIANT` while any
    finding is `OPEN` or `REPORTED_8823`. Because reporting leaves the finding unresolved, it
    does not change `open_finding_count`."

    Design: Difficulty/compensating_invariant/report_then_correct_restores_project_open_finding_count
    """
    project, building, _insp, finding = setup_failed_inspection_with_open_finding(
        conductor_user_id="hfa-1"
    )
    before = get_success_data(api.get_project(project["id"], HFA))
    assert before["open_finding_count"] == 1
    get_success_data(api.report_finding(finding["id"], HFA_2))
    after_report = get_success_data(api.get_project(project["id"], HFA))
    assert after_report["open_finding_count"] == 1
    assert after_report["posture"] == "NONCOMPLIANT"


def test_correcting_reported_finding_restores_count_and_posture(api):
    """PRD §3.9: "An `OwnerAgent` **corrects** a finding, moving it to `CORRECTED` from either
    `OPEN` or `REPORTED_8823` once the noncompliance is cured. Correcting a finding decrements
    the project's `open_finding_count` by one and recomputes the project's `posture`."

    Design: Difficulty/compensating_invariant/report_then_correct_restores_project_open_finding_count
    """
    project, building, _insp, finding = setup_failed_inspection_with_open_finding(
        conductor_user_id="hfa-1"
    )
    get_success_data(api.report_finding(finding["id"], HFA_2))
    corrected = validate_success(api.correct_finding(finding["id"], OWNER), 200)
    assert corrected["status"] == "CORRECTED"
    after = get_success_data(api.get_project(project["id"], HFA))
    assert after["open_finding_count"] == 0
    assert after["posture"] == "COMPLIANT"


# ─── Corner: 8823 report by different vs origin actor ──

def test_report_8823_by_different_actor_succeeds(api):
    """PRD §3.9: "Filing the 8823 sets the finding's `reported_8823_on` to the current clock
    time and recomputes the project's `posture`, which remains `NONCOMPLIANT` while any finding
    is `OPEN` or `REPORTED_8823`."
    PRD §3.10: "The server's startup default for the clock is `2026-01-01T00:00:00Z`, and
    before any explicit set the clock reads exactly that default and never the real wall-clock
    time."

    Design: Corner/errors/report_8823_by_different_actor_succeeds
    """
    project, building, _insp, finding = setup_failed_inspection_with_open_finding(
        conductor_user_id="hfa-1"
    )
    reported = validate_success(api.report_finding(finding["id"], HFA_2), 200)
    assert reported["status"] == "REPORTED_8823"
    assert reported["reported_8823_on"] == "2026-01-01T00:00:00.000Z"


def test_report_8823_by_origin_actor_returns_segregation_of_duties(api):
    """PRD §3.9: "A report by that same originating actor is rejected with
    `ERR_SEGREGATION_OF_DUTIES`."

    Design: Corner/errors/report_8823_by_origin_actor_returns_segregation_of_duties
    """
    project, building, _insp, finding = setup_failed_inspection_with_open_finding(
        conductor_user_id="hfa-1"
    )
    res = api.report_finding(finding["id"], HFA_1)  # same actor who conducted the inspection
    validate_error(res, "ERR_SEGREGATION_OF_DUTIES", expected_status=403)
    after = get_success_data(api.get_finding(finding["id"], HFA))
    assert after["status"] == "OPEN"


# ─── Corner: exigent health & safety forces FAIL ──────

def test_exigent_health_safety_forces_fail_regardless_of_score(api):
    """PRD §3.8: "The `result` is `FAIL` if `has_exigent_health_safety` is true or the `score`
    is below the passing threshold of 60; otherwise the `result` is `PASS`."

    Design: Corner/errors/upcs_exigent_health_safety_forces_fail_regardless_of_score
    """
    project, building = setup_project_building()
    inspection = get_success_data(
        api.create_inspection(
            create_inspection_payload(
                building["id"], deduction_points=[5],  # score 95 (would otherwise PASS)
                has_exigent_health_safety=True,
            ),
            HFA,
        )
    )
    conducted = validate_success(api.conduct_inspection(inspection["id"], HFA), 200)
    assert conducted["score"] == 95
    assert conducted["result"] == "FAIL"
    project_after = get_success_data(api.get_project(project["id"], HFA))
    assert project_after["open_finding_count"] == 1


# ─── Corner: project close guarded transition ─────────

def test_project_close_from_draft_returns_invalid_state(api):
    """PRD §3.7: "From `CREDIT_PERIOD` a `StateHFA` advances the project to
    `COMPLIANCE_PERIOD`, and from `COMPLIANCE_PERIOD` a `StateHFA` closes the project to the
    terminal `CLOSED` state — but a project may close only when its `open_finding_count` is 0;
    a close attempted while findings remain unresolved is rejected with
    `ERR_OPEN_FINDINGS_BLOCK_CLOSE`."
    PRD §4: "All other state-changing operations — the action endpoints that drive
    transitions, and the logical-clock set — return a `200 OK` status code."

    Design: Corner/state_machines/project_close_blocked_by_open_finding_count
    """
    project = create_project()  # status DRAFT
    res = api.close_project(project["id"], HFA)
    validate_error(res, "ERR_INVALID_STATE", expected_status=409)
    after = get_success_data(api.get_project(project["id"], HFA))
    assert after["status"] == "DRAFT"
