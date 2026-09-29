"""Difficulty queue - rule resource_temporal_overlap.

The two opposing interval conventions of the domain on the same clock: monitoring
profile intervals are CLOSED, so shared endpoints collide, while refresh windows are
HALF-OPEN, so the identical geometry is legal.
"""
from test_helpers import (
    ApiErrorId,
    add_control_rows,
    add_verified_owner,
    assert_instant_equals,
    calibrate,
    committee_decision,
    corridor,
    licensed_respondent,
    new_jurisdiction,
    open_profile,
    open_questionnaire,
    overlay_row,
    progress_refresh,
    read_profile,
    read_refresh,
    read_respondent,
    respondent_version,
    schedule_refresh,
    score_respondent,
    set_clock,
    submit_questionnaire,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.fixtures import ANALYST, assess_questionnaire


DOMAINS = [
    "GOVERNANCE", "KYC_ONBOARDING", "TRANSACTION_MONITORING", "SANCTIONS_SCREENING",
    "PEP_HANDLING", "TRAINING", "AUDIT", "NESTED_CONTROLS",
]


def _approved_low(code, **overrides):
    respondent = licensed_respondent(code, **overrides)
    rid = respondent["id"]
    add_verified_owner(rid, code, owner_name="Sole Holding", ownership_pct=100.00)
    questionnaire = open_questionnaire(rid, version="V1")
    add_control_rows(questionnaire["id"], rid, {d: 3 for d in DOMAINS})
    submit_questionnaire(questionnaire["id"], rid)
    assess_questionnaire(questionnaire["id"], "ONBOARDING_PROVISIONAL")
    scored = score_respondent(rid, "ONBOARDING_PROVISIONAL")
    assert scored["control_score"] == 60.00
    assert scored["control_credit"] == 0.2250
    assert scored["inherent_risk_score"] == 14.00
    assert scored["residual_risk_score"] == 10.85
    assert scored["risk_rating"] == "LOW"
    committee_decision(rid, "APPROVE")
    return rid


def _anchored_profile():
    """Approved LOW respondent with one CALIBRATED anchor profile over the closed
    interval [2026-01-01, 2026-06-30]."""
    code = new_jurisdiction(
        name="Germany", basel_aml_index=4.0, corridor_risk_weight=1.00,
        max_permitted_risk_rating="HIGH",
    )["jurisdiction_code"]
    rid = _approved_low(
        code, legal_name="Stuttgart Nostrobank AG", expected_monthly_volume_usd=4000000.00,
        expected_monthly_count=150,
    )
    anchor = open_profile(
        rid, [corridor(code, 4000000.00, 150)], tolerance_pct=0.10,
        effective_from="2026-01-01T00:00:00Z", effective_to="2026-06-30T00:00:00Z",
    )
    calibrate(anchor["id"])
    calibrated = read_profile(anchor["id"])
    assert calibrated["calibration_state"] == "CALIBRATED"
    assert calibrated["corridor_thresholds"] == [
        {"jurisdiction_code": code, "usd_threshold": 5720000.00, "count_threshold": 215}
    ]
    assert calibrated["aggregate_usd_threshold"] == 6292000.00
    assert calibrated["hold_threshold_usd"] == 629200.00
    return code, rid, anchor


def _profile_payload(code, version, effective_from, effective_to):
    return {
        "effective_from": effective_from,
        "effective_to": effective_to,
        "tolerance_pct": 0.10,
        "expected_respondent_version": version,
        "expected_corridors": [corridor(code, 4000000.00, 150)],
    }


def test_both_shared_profile_endpoints_collide_and_the_version_is_untouched(api):
    """Touching the anchor's right endpoint and touching its left endpoint are both 409s
    under closed semantics, and because neither wrote anything the very same
    `expected_respondent_version` still admits the create that clears the interval.

    Design: Difficulty/resource_temporal_overlap/monitoring_profile_intervals_are_closed_so_both_shared_endpoints_collide_and_one_second_clear_of_either_is_legal
    """
    code, rid, anchor = _anchored_profile()
    version = respondent_version(rid)

    right_touch = _profile_payload(
        code, version, "2026-06-30T00:00:00Z", "2026-09-30T00:00:00Z"
    )
    validate_error(
        api.create_monitoring_profile(rid, right_touch, ANALYST),
        ApiErrorId.ERR_MONITORING_INTERVAL_OVERLAP,
    )

    left_touch = _profile_payload(
        code, version, "2025-10-01T00:00:00Z", "2026-01-01T00:00:00Z"
    )
    validate_error(
        api.create_monitoring_profile(rid, left_touch, ANALYST),
        ApiErrorId.ERR_MONITORING_INTERVAL_OVERLAP,
    )

    clear = _profile_payload(code, version, "2026-06-30T00:00:01Z", "2026-09-30T00:00:00Z")
    created = validate_success(
        api.create_monitoring_profile(rid, clear, ANALYST), expected_status=201
    )
    assert created["calibration_state"] == "PROVISIONAL"
    assert created["corridor_thresholds"] == []  # a create never calibrates

    # Exactly one version bump across the three calls: only the 201 touched the respondent.
    assert respondent_version(rid) == version + 1


def test_one_second_clear_of_the_left_endpoint_is_legal_and_only_the_anchor_is_calibrated(api):
    """One second before the anchor's `effective_from` is admissible, leaving three
    profiles that the list read returns `effective_from` ascending with the anchor still
    the only CALIBRATED one over any instant.

    Design: Difficulty/resource_temporal_overlap/monitoring_profile_intervals_are_closed_so_both_shared_endpoints_collide_and_one_second_clear_of_either_is_legal
    """
    code, rid, anchor = _anchored_profile()
    right = validate_success(
        api.create_monitoring_profile(
            rid,
            _profile_payload(
                code, respondent_version(rid), "2026-06-30T00:00:01Z", "2026-09-30T00:00:00Z"
            ),
            ANALYST,
        ),
        expected_status=201,
    )

    left = validate_success(
        api.create_monitoring_profile(
            rid,
            _profile_payload(
                code, respondent_version(rid), "2025-10-01T00:00:00Z", "2025-12-31T23:59:59Z"
            ),
            ANALYST,
        ),
        expected_status=201,
    )
    assert left["calibration_state"] == "PROVISIONAL"

    rows, _meta = validate_paginated(
        api.list_monitoring_profiles(ANALYST, params={"respondent_bank_id": rid})
    )
    assert [row["id"] for row in rows] == [left["id"], anchor["id"], right["id"]]
    calibrated = [row["id"] for row in rows if row["calibration_state"] == "CALIBRATED"]
    assert calibrated == [anchor["id"]]

    respondent = read_respondent(rid)
    assert respondent["risk_rating"] == "LOW"
    assert respondent["dd_state"] == "APPROVED"


def _completed_then_scheduled_cycles():
    """One genuinely COMPLETED cycle over [2026-08-01, 2026-10-30) and one SCHEDULED cycle
    over [2026-12-15, 2027-03-15), 46 days clear of the completion buffer."""
    code = new_jurisdiction(
        name="Germany", basel_aml_index=4.0, corridor_risk_weight=1.00,
        max_permitted_risk_rating="HIGH",
    )["jurisdiction_code"]
    rid = _approved_low(
        code, legal_name="Erfurt Korrespondenzbank AG", expected_monthly_volume_usd=2000000.00,
        expected_monthly_count=100,
    )

    first = schedule_refresh(
        rid, "2026-08-01T00:00:00Z", "2026-10-30T00:00:00Z", trigger_reason="CADENCE"
    )
    progress_refresh(first["id"], "START")

    set_clock("2026-08-03T00:00:00Z")
    second = open_questionnaire(rid, version="V2")
    rows = add_control_rows(second["id"], rid, {d: 2 for d in DOMAINS})
    submit_questionnaire(second["id"], rid)
    for domain in DOMAINS:
        overlay_row(rows[domain]["id"], assessed_rating=3)
    assessed = assess_questionnaire(second["id"], "REFRESH_FINAL")
    assert assessed["computed_control_score"] == 60.00  # 20.0 * 3.0, self_rating ignored
    score_respondent(rid, "REFRESH_FINAL")
    completed = progress_refresh(first["id"], "COMPLETE")
    assert completed["state"] == "COMPLETED"
    assert_instant_equals(completed["completed_at"], "2026-08-03T00:00:00Z")
    assert completed["completed_control_score"] == 60.00
    assert completed["completion_risk_rating"] == "LOW"

    respondent = read_respondent(rid)
    assert_instant_equals(respondent["last_approved_at"], "2026-08-03T00:00:00Z")
    assert_instant_equals(respondent["refresh_due_date"], "2029-08-03T00:00:00Z")

    upcoming = schedule_refresh(
        rid, "2026-12-15T00:00:00Z", "2027-03-15T00:00:00Z", trigger_reason="CADENCE"
    )
    assert upcoming["state"] == "SCHEDULED"
    assert read_respondent(rid)["dd_state"] == "REFRESH_DUE"
    return rid, first, upcoming


def _refresh_payload(window_start, scheduled_due_date):
    return {
        "trigger_reason": "CADENCE",
        "window_start": window_start,
        "scheduled_due_date": scheduled_due_date,
    }


def test_interior_refresh_overlap_outranks_the_post_completion_buffer(api):
    """A window starting 11 days after the completed cycle's due date breaks only the
    buffer rule and answers 422; pushing only its far end until it also overlaps the
    SCHEDULED cycle must flip the answer to the priority-38 409.

    Design: Difficulty/resource_temporal_overlap/refresh_windows_are_half_open_so_adjacency_is_legal_and_the_interior_overlap_409_outranks_the_buffer_422
    """
    rid, first, upcoming = _completed_then_scheduled_cycles()

    buffer_only = _refresh_payload("2026-11-10T00:00:00Z", "2026-12-10T00:00:00Z")
    validate_error(
        api.create_periodic_refresh(rid, buffer_only, ANALYST),
        ApiErrorId.ERR_REFRESH_BUFFER_VIOLATION,
    )

    both_defects = _refresh_payload("2026-11-10T00:00:00Z", "2027-01-10T00:00:00Z")
    validate_error(
        api.create_periodic_refresh(rid, both_defects, ANALYST),
        ApiErrorId.ERR_REFRESH_WINDOW_OVERLAP,
    )

    assert read_refresh(upcoming["id"])["state"] == "SCHEDULED"
    rows, _meta = validate_paginated(
        api.list_periodic_refreshes(ANALYST, params={"respondent_bank_id": rid})
    )
    assert [row["id"] for row in rows] == [first["id"], upcoming["id"]]


def test_half_open_refresh_adjacency_is_legal_and_does_not_cancel_the_sibling(api):
    """A `window_start` exactly equal to the SCHEDULED cycle's `scheduled_due_date` is
    accepted - the opposite answer to the closed monitoring interval - and a CADENCE
    trigger leaves the sibling cycle alone.

    Design: Difficulty/resource_temporal_overlap/refresh_windows_are_half_open_so_adjacency_is_legal_and_the_interior_overlap_409_outranks_the_buffer_422
    """
    rid, first, upcoming = _completed_then_scheduled_cycles()

    adjacent = _refresh_payload("2027-03-15T00:00:00Z", "2027-06-13T00:00:00Z")
    created = validate_success(
        api.create_periodic_refresh(rid, adjacent, ANALYST), expected_status=201
    )

    assert created["state"] == "SCHEDULED"
    assert created["trigger_reason"] == "CADENCE"
    assert created["cadence_months_applied"] == 36  # frozen from approved_risk_rating LOW
    assert created["rating_at_schedule"] == "LOW"

    # Only ADVERSE_MEDIA, ALERT_ESCALATION and NESTED_DISCOVERY supersede siblings.
    assert read_refresh(upcoming["id"])["state"] == "SCHEDULED"

    rows, _meta = validate_paginated(
        api.list_periodic_refreshes(ANALYST, params={"respondent_bank_id": rid})
    )
    assert [row["id"] for row in rows] == [first["id"], upcoming["id"], created["id"]]
    assert [row["state"] for row in rows] == ["COMPLETED", "SCHEDULED", "SCHEDULED"]

    respondent = read_respondent(rid)
    assert respondent["dd_state"] == "REFRESH_DUE"
    assert respondent["risk_rating"] == "LOW"
