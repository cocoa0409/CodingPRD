"""The calendar ops-run checkpoint: the deadline sweep, its evidence-miss cascade, and
the epoch it advances even when nothing is overdue."""

from test_helpers import (
    TEST_USERS,
    create_manual_gap,
    read_control,
    read_engagement,
    schedule_evidence,
    set_clock,
    setup_engagement_at,
    validate_paginated,
    validate_success,
)

CL_HEADERS = TEST_USERS["compliance_lead_headers"]
PA_HEADERS = TEST_USERS["platform_admin_headers"]


def test_a_run_with_nothing_overdue_still_advances_the_epoch(api):
    """PRD 3.7: "A run over an engagement with nothing overdue is legitimate and simply
    reports zeroes with an advanced epoch."
    PRD 3.7: "Finally the run increments the engagement's `calendar_epoch` by one and its
    `version` by one. The response is a report on what the sweep did rather than the
    engagement row itself: `calendar_epoch` after the increment, `missed_evidence_count`
    for the number of evidence requests swept to `MISSED`, `expired_bridge_letter_count`
    for the number of letters expired, `gaps_created_count` for the number of gaps the
    cascades synthesised, and the engagement's resulting `gap_posture` and
    `gap_debt_points`."

    Design: Corner/cross_cutting_complexity_layers/corner_calendar_run_is_a_no_op_when_nothing_is_overdue
    """
    scenario = setup_engagement_at(phase="OBSERVATION", client_name="Quiet Run")
    request_id = scenario["evidence"]["S-01"]["id"]
    control_id = scenario["controls"]["S-01"]["id"]
    set_clock("2026-10-05T00:00:00.000Z")

    report = validate_success(api.run_calendar(scenario["engagement_id"], PA_HEADERS))
    assert report["missed_evidence_count"] == 0
    assert report["gaps_created_count"] == 0
    assert report["expired_bridge_letter_count"] == 0
    assert report["calendar_epoch"] == 1
    assert report["gap_posture"] == "OPEN"

    assert validate_success(api.get_evidence_request(request_id, CL_HEADERS))["status"] == "SCHEDULED"
    control = read_control(control_id)
    assert control["evidence_scheduled_count"] == 1
    assert control["evidence_missed_count"] == 0
    assert control["operating_status"] == "IN_OBSERVATION"
    assert read_engagement(scenario["engagement_id"])["calendar_epoch"] == 1

    _, meta = validate_paginated(
        api.list_gaps(CL_HEADERS, params={"engagement_id": scenario["engagement_id"]})
    )
    assert meta["total_count"] == 0


def build_two_overdue_periods():
    """An engagement in OBSERVATION carrying one live MODERATE gap and a control with two
    evidence periods, both of them past their due date on a logical clock of 2026-11-20."""
    scenario = setup_engagement_at(
        phase="OBSERVATION",
        client_name="Woodgrove",
        controls=[
            {
                "control_ref": "S-01",
                "evidence_period": ("2026-09-01T00:00:00.000Z", "2026-10-01T00:00:00.000Z"),
            }
        ],
    )
    scenario["second_evidence"] = schedule_evidence(
        scenario["controls"]["S-01"]["id"],
        period_index=1,
        period_start="2026-10-01T00:00:00.000Z",
        period_end="2026-11-01T00:00:00.000Z",
    )
    scenario["manual_gap"] = create_manual_gap(
        scenario["engagement_id"], "MODERATE", "Policy set not yet ratified"
    )
    set_clock("2026-11-20T00:00:00.000Z")
    return scenario


def test_the_sweep_moves_every_overdue_request_to_missed(api):
    """PRD 3.7: "The sweep first walks the engagement's evidence requests. Every request
    whose `status` is `SCHEDULED` or `REJECTED` and whose `due_date` falls strictly before
    the logical clock moves to `MISSED`."
    PRD 3.7: "Each such move decreases the control's `evidence_scheduled_count` by one and
    increases its `evidence_missed_count` by one. When that increment brings
    `evidence_missed_count` to 2 or more, the control moves `IN_OBSERVATION →
    TESTED_INEFFECTIVE`, a terminal state on the operating track."

    Design: Difficulty/transitive_cascade/calendar_run_cascades_missed_evidence_to_ineffective_to_gap_to_posture
    """
    scenario = build_two_overdue_periods()

    report = validate_success(api.run_calendar(scenario["engagement_id"], CL_HEADERS))
    assert report["missed_evidence_count"] == 2
    assert report["calendar_epoch"] == 1

    first = validate_success(
        api.get_evidence_request(scenario["evidence"]["S-01"]["id"], CL_HEADERS)
    )
    second = validate_success(
        api.get_evidence_request(scenario["second_evidence"]["id"], CL_HEADERS)
    )
    assert first["status"] == "MISSED"
    assert second["status"] == "MISSED"

    control = read_control(scenario["controls"]["S-01"]["id"])
    assert control["evidence_missed_count"] == 2
    assert control["evidence_scheduled_count"] == 0
    assert control["operating_status"] == "TESTED_INEFFECTIVE"


def test_the_evidence_miss_cascade_adds_a_gap_and_restricts_the_engagement(api):
    """PRD 3.7: "That operating move in turn creates exactly one gap with `source`
    `EVIDENCE_MISS`, severity `HIGH` and this control as its `control_id`, and that gap
    creation in turn drives the recompute of `base_debt_points`, `gap_debt_points` and
    `gap_posture`."
    PRD 3.5: "Second, the tier is selected **from the pre-surcharge base and never from the
    total it will later be added to**. A base of 10 or less draws a rate of 0 percent; a
    base from 11 through 25 inclusive draws 15 percent; a base of 26 or more draws 30
    percent."

    Design: Difficulty/transitive_cascade/calendar_run_cascades_missed_evidence_to_ineffective_to_gap_to_posture
    """
    scenario = build_two_overdue_periods()

    report = validate_success(api.run_calendar(scenario["engagement_id"], CL_HEADERS))
    assert report["gaps_created_count"] == 1
    assert report["gap_posture"] == "RESTRICTED"
    assert report["gap_debt_points"] == 12.65

    gaps, meta = validate_paginated(
        api.list_gaps(
            CL_HEADERS,
            params={"engagement_id": scenario["engagement_id"], "source": "EVIDENCE_MISS"},
        )
    )
    assert meta["total_count"] == 1
    assert gaps[0]["severity"] == "HIGH"
    assert gaps[0]["control_id"] == scenario["controls"]["S-01"]["id"]

    engagement = read_engagement(scenario["engagement_id"])
    assert engagement["base_debt_points"] == 11, (
        "The live MODERATE gap contributes 3 and the new HIGH gap contributes 8"
    )
    assert engagement["gap_debt_points"] == 12.65
    assert engagement["gap_posture"] == "RESTRICTED"
    assert engagement["calendar_epoch"] == 1
