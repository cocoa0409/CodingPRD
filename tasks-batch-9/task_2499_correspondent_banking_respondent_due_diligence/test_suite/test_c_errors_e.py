"""Corner queue - section errors, part E: clock windows, refresh intervals and the ceiling."""
from test_helpers import (
    CONTROL_DOMAIN_ORDER,
    ApiErrorId,
    add_control_rows,
    assert_instant_equals,
    assess_questionnaire,
    corridor,
    licensed_respondent,
    maintain_request,
    new_jurisdiction,
    open_profile,
    open_questionnaire,
    overlay_row,
    progress_refresh,
    read_request,
    read_respondent,
    schedule_refresh,
    score_respondent,
    set_clock,
    setup_approved_respondent,
    setup_sent_request,
    submit_questionnaire,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.fixtures import ANALYST


def _de():
    return new_jurisdiction(
        jurisdiction_code="DE", name="Germany", basel_aml_index=4.0, corridor_risk_weight=1.0
    )


def test_marking_or_escalating_an_rfi_before_its_window_elapses(api):
    """One error code guards two clocks: the due instant, which is inclusive, and the further
    seventy-two hours each escalation level needs - and the refused call charges no strike.

    Design: Corner/errors/marking_or_escalating_an_rfi_before_its_window_elapses
    """
    _de()
    bundle = setup_sent_request(
        severity="MEDIUM", topic="ACTIVITY_EXPLANATION", jurisdiction_code="DE",
        legal_name="Nordbank AG", swift_bic="NORDDEFF",
        expected_monthly_volume_usd=500000.00, expected_monthly_count=100,
    )
    rid = bundle["respondent"]["id"]
    request_id = bundle["request"]["id"]
    assert bundle["request"]["sla_hours"] == 168
    assert_instant_equals(bundle["request"]["due_at"], "2026-08-08T00:00:00Z")
    assert read_respondent(rid)["unresponsive_strikes"] == 0

    too_early = api.mark_overdue(request_id, {"action": "MARK_OVERDUE"}, ANALYST)
    validate_error(too_early, ApiErrorId.ERR_RFI_NOT_YET_OVERDUE, expected_status=422)
    assert read_request(request_id)["state"] == "SENT"
    assert read_respondent(rid)["unresponsive_strikes"] == 0

    set_clock("2026-08-08T00:00:00Z")
    marked = maintain_request(request_id, "MARK_OVERDUE")
    assert marked["state"] == "OVERDUE"
    assert read_respondent(rid)["unresponsive_strikes"] == 1
    level_after_marking = marked["escalation_level"]

    premature = api.mark_overdue(request_id, {"action": "ESCALATE"}, ANALYST)
    validate_error(premature, ApiErrorId.ERR_RFI_NOT_YET_OVERDUE, expected_status=422)

    stored = read_request(request_id)
    assert stored["state"] == "OVERDUE"
    assert stored["escalation_level"] == level_after_marking
    assert read_respondent(rid)["unresponsive_strikes"] == 1


def _completed_cycle():
    """Approved respondent whose first cycle over [2026-08-01, 2026-09-01) is COMPLETED."""
    _de()
    bundle = setup_approved_respondent(
        "DE", legal_name="Nordbank AG", swift_bic="NORDDEFF",
        expected_monthly_volume_usd=500000.00, expected_monthly_count=100,
    )
    rid = bundle["respondent"]["id"]
    first = schedule_refresh(rid, "2026-08-01T00:00:00Z", "2026-09-01T00:00:00Z")
    progress_refresh(first["id"], "START")

    questionnaire = open_questionnaire(rid, version="WOLFSBERG_V1_5")
    rows = add_control_rows(questionnaire["id"], rid)
    submit_questionnaire(questionnaire["id"], rid)
    for domain in CONTROL_DOMAIN_ORDER:
        overlay_row(rows[domain]["id"], assessed_rating=4)
    assessed = assess_questionnaire(questionnaire["id"], "REFRESH_FINAL")
    assert assessed["computed_control_score"] == 80.00
    score_respondent(rid, "REFRESH_FINAL")

    completed = progress_refresh(first["id"], "COMPLETE")
    assert completed["state"] == "COMPLETED"
    assert completed["completed_control_score"] == 80.00
    assert read_respondent(rid)["dd_state"] == "APPROVED"
    return rid, first


def _window(window_start, scheduled_due_date):
    return {
        "trigger_reason": "CADENCE",
        "window_start": window_start,
        "scheduled_due_date": scheduled_due_date,
    }


def test_refresh_window_overlap_and_post_completion_buffer_in_pinned_order(api):
    """One endpoint gives four verdicts on one respondent - buffer violation, clean create,
    interior overlap, and the pair where a window breaching both answers with the overlap 409 -
    while a window starting exactly where another ends is adjacency rather than overlap.

    Design: Corner/errors/refresh_window_overlap_and_post_completion_buffer_in_pinned_order
    """
    rid, _first = _completed_cycle()

    inside_buffer = api.create_periodic_refresh(
        rid, _window("2026-09-15T00:00:00Z", "2026-10-15T00:00:00Z"), ANALYST
    )
    validate_error(inside_buffer, ApiErrorId.ERR_REFRESH_BUFFER_VIOLATION, expected_status=422)
    assert read_respondent(rid)["dd_state"] == "APPROVED"
    _rows, meta = validate_paginated(
        api.list_periodic_refreshes(ANALYST, params={"respondent_bank_id": rid})
    )
    assert meta["total_count"] == 1

    second = validate_success(
        api.create_periodic_refresh(
            rid, _window("2026-10-05T00:00:00Z", "2026-11-05T00:00:00Z"), ANALYST
        ),
        expected_status=201,
    )
    assert second["state"] == "SCHEDULED"
    assert read_respondent(rid)["dd_state"] == "REFRESH_DUE"

    interior = api.create_periodic_refresh(
        rid, _window("2026-10-20T00:00:00Z", "2026-11-20T00:00:00Z"), ANALYST
    )
    validate_error(interior, ApiErrorId.ERR_REFRESH_WINDOW_OVERLAP, expected_status=409)

    both = api.create_periodic_refresh(
        rid, _window("2026-09-20T00:00:00Z", "2026-10-20T00:00:00Z"), ANALYST
    )
    validate_error(both, ApiErrorId.ERR_REFRESH_WINDOW_OVERLAP, expected_status=409)

    adjacent = validate_success(
        api.create_periodic_refresh(
            rid, _window("2026-11-05T00:00:00Z", "2026-12-05T00:00:00Z"), ANALYST
        ),
        expected_status=201,
    )
    assert adjacent["state"] == "SCHEDULED"

    rows, final_meta = validate_paginated(
        api.list_periodic_refreshes(ANALYST, params={"respondent_bank_id": rid})
    )
    assert final_meta["total_count"] == 3
    assert_instant_equals(rows[0]["window_start"], "2026-08-01T00:00:00Z")
    assert_instant_equals(rows[1]["window_start"], "2026-10-05T00:00:00Z")
    assert_instant_equals(rows[2]["window_start"], "2026-11-05T00:00:00Z")


def test_calibration_beyond_the_buffered_aggregate_ceiling(api):
    """The ceiling bites on the buffered aggregate, so a corridor already clamped to the
    per-corridor ceiling still breaks the rule, and the refused calibration writes nothing.

    Design: Corner/errors/calibration_beyond_the_buffered_aggregate_ceiling
    """
    _de()
    respondent = licensed_respondent(
        "DE", legal_name="Nordbank AG", swift_bic="NORDDEFF",
        expected_monthly_volume_usd=500000.00, expected_monthly_count=100,
    )
    rid = respondent["id"]
    assert score_respondent(rid, "ONBOARDING_PROVISIONAL")["risk_rating"] == "LOW"
    big = open_profile(
        rid, [corridor("DE", 400000000.00, 80)],
        effective_from="2026-06-01T00:00:00Z", effective_to="2026-06-30T00:00:00Z",
    )
    fitting = open_profile(
        rid, [corridor("DE", 300000000.00, 80)],
        effective_from="2026-07-01T00:00:00Z", effective_to="2026-07-31T00:00:00Z",
    )

    refused = api.calibrate_profile(big["id"], {"action": "CALIBRATE"}, ANALYST)
    validate_error(
        refused, ApiErrorId.ERR_AGGREGATE_THRESHOLD_EXCEEDED, expected_status=422
    )

    untouched = validate_success(api.get_monitoring_profile(big["id"], ANALYST))
    assert untouched["calibration_state"] == "PROVISIONAL"
    assert untouched["corridor_thresholds"] == []
    assert untouched["aggregate_usd_threshold"] is None
    assert untouched["calibrated_at"] is None

    calibrated = validate_success(
        api.calibrate_profile(fitting["id"], {"action": "CALIBRATE"}, ANALYST)
    )
    assert calibrated["calibration_state"] == "CALIBRATED"
    assert calibrated["corridor_thresholds"][0]["usd_threshold"] == 448500000.00
    assert calibrated["aggregate_usd_threshold"] == 493350000.00
    assert calibrated["hold_threshold_usd"] == 49335000.00
