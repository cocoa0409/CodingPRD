"""Shoot-day execution: completion, shut-down cascade, strict compliance."""
from test_helpers import (
    FO,
    LM,
    ApiErrorId,
    assert_complaint,
    create_complaint_payload,
    get_success_data,
    make_owner_rep_headers,
    set_clock,
    setup_in_progress_day,
    sweep,
    validate_error,
    validate_paginated,
    validate_success,
)


def _get_day(api, production_id, day_id):
    return get_success_data(api.get_shoot_day(production_id, day_id, LM))


def _get_closure(api, production_id, closure_id):
    rows, _ = validate_paginated(api.list_street_closures(production_id, LM))
    matches = [r for r in rows if r["id"] == closure_id]
    assert matches, f"StreetClosure {closure_id} not found in list"
    return matches[0]


def _get_complaint(api, production_id, complaint_id):
    rows, _ = validate_paginated(api.list_complaints(production_id, LM))
    matches = [r for r in rows if r["id"] == complaint_id]
    assert matches, f"Complaint {complaint_id} not found in list"
    return matches[0]


# ---------------------------------------------------------------------------
# Difficulty: IN_PROGRESS branches — SHUT_DOWN cancels closures, COMPLETED does not
# ---------------------------------------------------------------------------

def test_critical_complaint_shuts_down_day_and_cancels_closures(api):
    """PRD §3.9: "Filing a `CRITICAL` complaint against an `IN_PROGRESS` day fires
    the shut-down cascade of §3.8 immediately"
    PRD §3.8: "a `CRITICAL` complaint filed against an `IN_PROGRESS` day shuts the
    day down automatically — the film office may also shut an in-progress day down
    explicitly — moving it to `SHUT_DOWN` and cancelling its day's `APPROVED` or
    `ACTIVE` street closures, which frees those street-segment intervals; the
    production itself remains `ACTIVE`."
    PRD §3.9: "the complaint opens as `OPEN`."

    Design: Difficulty/non_linear_state_machine/shoot_day_branching_complete_vs_shutdown_divergent_side_effects
    """
    result = setup_in_progress_day(
        permit_overrides={"closed_lanes": 2, "shoot_hours_per_day": 8},
        monitors=[
            {"monitor_type": "POLICE", "officer_badge": "PD-1"},
            {"monitor_type": "FILM_OFFICER", "officer_badge": "FO-1"},
        ],
        closure_overrides={},
    )
    production_id = result["production"]["id"]
    day = result["shoot_day"]
    assert day["status"] == "IN_PROGRESS", f"Setup: day must be IN_PROGRESS, got {day['status']}"

    complaint = get_success_data(api.create_complaint(
        production_id,
        create_complaint_payload(day["id"], category="PROPERTY_DAMAGE", severity="CRITICAL"),
        make_owner_rep_headers(result["owner"]["id"]),
    ))
    assert_complaint(complaint)

    day_now = _get_day(api, production_id, day["id"])
    assert day_now["status"] == "SHUT_DOWN", (
        f"CRITICAL complaint on an IN_PROGRESS day must shut it down, got {day_now['status']}"
    )
    closure_now = _get_closure(api, production_id, result["closure"]["id"])
    assert closure_now["status"] == "CANCELLED", (
        "The shut-down branch cancels the day's APPROVED/ACTIVE closures"
    )
    assert _get_complaint(api, production_id, complaint["id"])["status"] == "OPEN", (
        "Filing does not auto-resolve the complaint"
    )
    production = get_success_data(api.get_production(production_id, LM))
    assert production["status"] == "ACTIVE"


def test_completed_branch_leaves_closures_untouched_until_clock_sweep(api):
    """PRD §3.8: "Completion recomputes `compliance_status` and sweeps every
    still-unchecked `CONFIRMED` assignment into `NO_SHOW`."
    PRD §3.6: "From `APPROVED` the closure's life is clock-driven: the operations
    sweep moves it to `ACTIVE` when the clock reaches `closure_start`, and to
    `COMPLETED` when the clock reaches `closure_end`."

    Design: Difficulty/non_linear_state_machine/shoot_day_branching_complete_vs_shutdown_divergent_side_effects
    """
    result = setup_in_progress_day(
        permit_overrides={"closed_lanes": 2, "shoot_hours_per_day": 8},
        monitors=[
            {"monitor_type": "POLICE", "officer_badge": "PD-1"},
            {"monitor_type": "FILM_OFFICER", "officer_badge": "FO-1"},
        ],
        closure_overrides={},
    )
    production_id = result["production"]["id"]
    day = result["shoot_day"]
    assert day["status"] == "IN_PROGRESS"

    for monitor in result["monitors"]:
        get_success_data(api.check_in_monitor_assignment(production_id, monitor["id"], FO))
    completed = validate_success(api.complete_shoot_day(production_id, day["id"], 8, LM))
    assert completed["status"] == "COMPLETED"

    # Divergence: unlike SHUT_DOWN, completion does NOT cancel the day's closure.
    closure_now = _get_closure(api, production_id, result["closure"]["id"])
    assert closure_now["status"] == "ACTIVE", (
        f"On the COMPLETED branch the closure stays live, got {closure_now['status']}"
    )
    # It completes only when the clock passes its window end.
    set_clock("2026-08-10T21:00:00Z")
    sweep()
    assert _get_closure(api, production_id, result["closure"]["id"])["status"] == "COMPLETED"


# ---------------------------------------------------------------------------
# Difficulty: strict compliance variant — resolved complaints still count
# ---------------------------------------------------------------------------

def _in_progress_day_with_resolved_complaint(api, severity, category="NOISE"):
    """IN_PROGRESS day (lanes 0, hours 8, cast 40 -> 1 monitor required); the
    given-severity complaint is filed, acknowledged, and resolved; the monitor is
    then checked in. Returns (result, complaint)."""
    result = setup_in_progress_day()
    production_id = result["production"]["id"]
    day = result["shoot_day"]
    assert day["status"] == "IN_PROGRESS"
    complaint = get_success_data(api.create_complaint(
        production_id,
        create_complaint_payload(day["id"], category=category, severity=severity),
        make_owner_rep_headers(result["owner"]["id"]),
    ))
    get_success_data(api.acknowledge_complaint(production_id, complaint["id"], LM))
    resolved = get_success_data(
        api.resolve_complaint(production_id, complaint["id"], "Quieter generators deployed", LM)
    )
    assert resolved["status"] == "RESOLVED"
    for monitor in result["monitors"]:
        get_success_data(api.check_in_monitor_assignment(production_id, monitor["id"], FO))
    return result, complaint


def test_resolved_high_complaint_still_counts_under_strict_variant(api):
    """PRD §3.8: "The strict variant, the authoritative one persisted on the shoot
    day and used for wrap gating, counts every complaint against the day including
    `RESOLVED` ones — resolving a complaint never erases the compliance fact."
    PRD §3.8: "each counted `HIGH` or `CRITICAL` complaint against the day adds
    two points"
    PRD §3.8: "Two or more points mean `VIOLATION`, exactly one means `DEGRADED`,
    zero means `COMPLIANT`"
    PRD §3.8: "it records `overtime_minutes` as the excess of actual over planned
    hours, in minutes, floored at zero — a day that runs short records zero
    overtime."

    Design: Difficulty/dual_variant_calc/shoot_day_compliance_strict_vs_lenient_resolved_high_complaint
    """
    result, complaint = _in_progress_day_with_resolved_complaint(api, "HIGH")
    production_id = result["production"]["id"]
    day = result["shoot_day"]

    completed = validate_success(api.complete_shoot_day(production_id, day["id"], 8, LM))
    assert completed["status"] == "COMPLETED"
    assert completed["overtime_minutes"] == 0
    # Strict variant: the RESOLVED HIGH complaint still contributes 2 points.
    assert completed["compliance_status"] == "VIOLATION", (
        f"Persisted strict compliance must be VIOLATION, got {completed['compliance_status']}"
    )
    assert _get_complaint(api, production_id, complaint["id"])["status"] == "RESOLVED"


def test_resolved_medium_complaint_persists_degraded_under_strict_variant(api):
    """PRD §3.8: "each counted `MEDIUM` complaint adds one."
    PRD §3.8: "Two or more points mean `VIOLATION`, exactly one means `DEGRADED`,
    zero means `COMPLIANT`"
    PRD §3.8: "The strict variant, the authoritative one persisted on the shoot
    day and used for wrap gating, counts every complaint against the day including
    `RESOLVED` ones — resolving a complaint never erases the compliance fact."

    Design: Difficulty/dual_variant_calc/shoot_day_compliance_strict_vs_lenient_resolved_high_complaint
    """
    result, complaint = _in_progress_day_with_resolved_complaint(api, "MEDIUM", "PARKING")
    production_id = result["production"]["id"]
    day = result["shoot_day"]

    completed = validate_success(api.complete_shoot_day(production_id, day["id"], 8, LM))
    assert completed["overtime_minutes"] == 0
    # Strict variant: the RESOLVED MEDIUM complaint still contributes 1 point.
    assert completed["compliance_status"] == "DEGRADED", (
        f"One point under the strict variant must yield DEGRADED, got {completed['compliance_status']}"
    )
    assert _get_complaint(api, production_id, complaint["id"])["status"] == "RESOLVED"


# ---------------------------------------------------------------------------
# Corner: monitor release and completion caps on a live day
# ---------------------------------------------------------------------------

def test_monitor_release_while_day_in_progress_rejected(api):
    """PRD §3.8: "Release by the film office frees the officer: an `ASSIGNED`
    assignment releases freely, but a `CONFIRMED` one cannot be released while its
    day is `IN_PROGRESS` (the attempt fails with `ERR_DAY_IN_PROGRESS`)."

    Design: Corner/state_machines/monitor_release_while_day_in_progress_rejected
    """
    result = setup_in_progress_day()
    production_id = result["production"]["id"]
    day = result["shoot_day"]
    assert day["status"] == "IN_PROGRESS"
    monitor = result["monitors"][0]
    assert monitor["status"] == "CONFIRMED"

    resp = api.release_monitor_assignment(production_id, monitor["id"], FO)
    validate_error(resp, ApiErrorId.ERR_DAY_IN_PROGRESS)

    rows, _ = validate_paginated(api.list_monitor_assignments(production_id, LM))
    by_id = {row["id"]: row for row in rows}
    assert by_id[monitor["id"]]["status"] == "CONFIRMED"


def test_shoot_day_complete_above_location_hours_cap_rejected(api):
    """PRD §3.8: "it requires `actual_hours`, which must not exceed the location's
    `max_shoot_hours_per_day` (else `ERR_HOURS_EXCEED_LOCATION_CAP`)"

    Design: Corner/state_machines/shoot_day_complete_above_location_hours_cap_rejected
    """
    result = setup_in_progress_day()
    production_id = result["production"]["id"]
    day = result["shoot_day"]
    assert day["status"] == "IN_PROGRESS"

    resp = api.complete_shoot_day(production_id, day["id"], 15, LM)
    validate_error(resp, ApiErrorId.ERR_HOURS_EXCEED_LOCATION_CAP)
    assert _get_day(api, production_id, day["id"])["status"] == "IN_PROGRESS"
