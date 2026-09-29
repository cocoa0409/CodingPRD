"""Temporal overlap geometries: three different interval algebras in one system.

Fitting slots widen only the candidate and compare strictly, so buffered adjacency is
legal. Firmware maintenance windows compare non-strictly, so touching endpoints collide.
Trial pause intervals merge on touch and are governed by an inclusive aggregate budget.
"""
from datetime import datetime, timezone

from test_helpers import (
    CARE_OPS,
    FIRMWARE_ENGINEER,
    REPAIR_TECH,
    ApiErrorId,
    api_client,
    create_provider,
    get_success_data,
    make_patient_headers,
    set_clock,
    setup_delivered_order,
    validate_error,
    validate_success,
)

# --- fitting-slot geometry -------------------------------------------------
PROVIDER_BUFFER_MINUTES = 10
PROVIDER_CAPACITY_MINUTES = 480
EXISTING_SLOT_START_UTC = "2026-08-10T10:00:00Z"
EXISTING_SLOT_END_UTC = "2026-08-10T11:00:00Z"
COLLIDING_SLOT_START_UTC = "2026-08-10T11:09:00Z"
COLLIDING_SLOT_END_UTC = "2026-08-10T11:39:00Z"
ADJACENT_SLOT_START_UTC = "2026-08-10T11:10:00Z"
ADJACENT_SLOT_END_UTC = "2026-08-10T11:40:00Z"
EXPECTED_BOOKED_MINUTES = 90
EXPECTED_UTILIZATION_PCT = 18.8

# --- campaign-window geometry ---------------------------------------------
BASE_WINDOW_START_UTC = "2026-09-01T00:00:00Z"
BASE_WINDOW_END_UTC = "2026-09-30T00:00:00Z"
TOUCHING_WINDOW_START_UTC = "2026-09-30T00:00:00Z"
TOUCHING_WINDOW_END_UTC = "2026-10-15T00:00:00Z"
ONE_SECOND_LATER_START_UTC = "2026-09-30T00:00:01Z"

# --- trial-pause geometry -------------------------------------------------
TRIAL_DAYS = 90
FIRST_PAUSE_OPEN_UTC = "2026-08-05T00:00:00Z"
FIRST_PAUSE_CLOSE_UTC = "2026-08-15T00:00:00Z"
SECOND_PAUSE_CLOSE_UTC = "2026-10-30T00:00:00Z"
THIRD_PAUSE_ATTEMPT_UTC = "2026-11-01T00:00:00Z"
EXPECTED_PAUSED_DAYS = 86
EXPECTED_DAYS_USED_AT_RESUME = 4
EXPECTED_EFFECTIVE_END_UTC = "2027-01-24T00:00:00Z"
EXPECTED_NOMINAL_END_UTC = "2026-10-30T00:00:00Z"


def _same_instant(actual: str, expected: str) -> bool:
    """Compare two ISO 8601 UTC timestamps as instants, ignoring fractional spelling."""
    def parse(value: str) -> datetime:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)

    return parse(actual) == parse(expected)


# ---------------------------------------------------------------------------
# Fitting slots: widened candidate, strict comparisons
# ---------------------------------------------------------------------------
def _setup_provider_with_one_booked_hour() -> dict:
    """One SCHEDULED 60-minute session at 10:00-11:00 for a provider buffering 10 minutes."""
    env = setup_delivered_order()
    env["provider"] = create_provider(
        full_name="Slot Geometry Provider",
        daily_capacity_minutes=PROVIDER_CAPACITY_MINUTES,
        buffer_minutes=PROVIDER_BUFFER_MINUTES,
    )
    env["patient_headers"] = make_patient_headers(env["patient"]["id"])
    env["existing_session"] = get_success_data(
        api_client.create_remote_fitting_session(
            {
                "patient_id": env["patient"]["id"],
                "session_type": "FOLLOW_UP",
                "scheduled_start_utc": EXISTING_SLOT_START_UTC,
                "scheduled_end_utc": EXISTING_SLOT_END_UTC,
                "provider_id": env["provider"]["id"],
                "device_order_id": env["order"]["id"],
            },
            env["patient_headers"],
        )
    )
    return env


def _book_candidate(env: dict, start_utc: str, end_utc: str):
    return api_client.create_remote_fitting_session(
        {
            "patient_id": env["patient"]["id"],
            "session_type": "FOLLOW_UP",
            "scheduled_start_utc": start_utc,
            "scheduled_end_utc": end_utc,
            "provider_id": env["provider"]["id"],
            "device_order_id": env["order"]["id"],
        },
        env["patient_headers"],
    )


def test_candidate_starting_one_minute_inside_the_buffer_collides():
    """"**Slot overlap** widens only the *candidate* interval by the provider's `buffer_minutes` on
    both sides — the candidate is treated as starting `buffer_minutes` earlier and ending
    `buffer_minutes` later — and compares that widened candidate against each existing session of
    the same provider whose `status` is `SCHEDULED` or `IN_PROGRESS`, using those existing sessions'
    un-widened half-open intervals. A conflict exists when the widened candidate start is strictly
    before the existing end **and** the existing start is strictly before the widened candidate end
    ... A conflict is rejected with `ERR_PROVIDER_SLOT_CONFLICT`." (PRD §3.4)

    Design: Difficulty/resource_temporal_overlap/fitting_slot_buffered_adjacency_accepted_but_one_minute_earlier_collides
    """
    env = _setup_provider_with_one_booked_hour()

    resp = _book_candidate(env, COLLIDING_SLOT_START_UTC, COLLIDING_SLOT_END_UTC)
    validate_error(resp, ApiErrorId.ERR_PROVIDER_SLOT_CONFLICT.value)

    sessions = api_client.list_remote_fitting_sessions(
        CARE_OPS, params={"provider_id": env["provider"]["id"]}
    ).json()["data"]
    assert len(sessions) == 1, (
        f"the rejected booking must not persist a session, got {len(sessions)} for this provider"
    )


def test_candidate_touching_the_buffered_boundary_is_accepted():
    """"both comparisons are strict, so exact adjacency at the buffered boundary — a widened
    candidate start falling precisely on an existing end — is accepted." (PRD §3.4)

    "The booked interval is half-open from `scheduled_start_utc` inclusive to `scheduled_end_utc`
    exclusive; `duration_minutes` is the whole number of minutes between the two ... Creation
    confirms the slot in the same request, so a new session lands in `SCHEDULED`" (PRD §3.4)

    Design: Difficulty/resource_temporal_overlap/fitting_slot_buffered_adjacency_accepted_but_one_minute_earlier_collides
    """
    env = _setup_provider_with_one_booked_hour()

    session = validate_success(
        _book_candidate(env, ADJACENT_SLOT_START_UTC, ADJACENT_SLOT_END_UTC), 201
    )
    assert session["status"] == "SCHEDULED", (
        f"an accepted booking lands in SCHEDULED, got {session['status']!r}"
    )
    assert session["duration_minutes"] == 30, (
        f"11:10 to 11:40 is 30 whole minutes, got {session['duration_minutes']}"
    )


def test_provider_capacity_counters_recomputed_after_the_adjacent_booking():
    """"After every accepted booking, and after every transition that moves a session into or out of
    `SCHEDULED`, `IN_PROGRESS` or `COMPLETED`, the provider's `booked_minutes_on_focus_date` and
    `utilization_pct` are recomputed, the latter as 100 multiplied by
    `booked_minutes_on_focus_date` divided by `daily_capacity_minutes`, rounded half up to one
    decimal place." (PRD §3.4)

    Design: Difficulty/resource_temporal_overlap/fitting_slot_buffered_adjacency_accepted_but_one_minute_earlier_collides
    """
    env = _setup_provider_with_one_booked_hour()
    validate_success(_book_candidate(env, ADJACENT_SLOT_START_UTC, ADJACENT_SLOT_END_UTC), 201)

    provider = validate_success(api_client.get_provider(env["provider"]["id"], CARE_OPS))
    assert provider["booked_minutes_on_focus_date"] == EXPECTED_BOOKED_MINUTES, (
        "a 60-minute and a 30-minute session on the same UTC date sum to "
        f"{EXPECTED_BOOKED_MINUTES}, got {provider['booked_minutes_on_focus_date']}"
    )
    assert provider["utilization_pct"] == EXPECTED_UTILIZATION_PCT, (
        f"100 * 90 / 480 is 18.75, which rounds half up to {EXPECTED_UTILIZATION_PCT}, got "
        f"{provider['utilization_pct']}"
    )

    sessions = api_client.list_remote_fitting_sessions(
        CARE_OPS, params={"provider_id": env["provider"]["id"]}
    ).json()["data"]
    assert len(sessions) == 2, (
        f"both the original and the adjacent session must hold the provider's day, got {len(sessions)}"
    )


# ---------------------------------------------------------------------------
# Firmware maintenance windows: closed intervals, non-strict comparisons
# ---------------------------------------------------------------------------
def _campaign_payload(campaign_code: str, model: str, window_start_utc: str,
                      window_end_utc: str) -> dict:
    return {
        "campaign_code": campaign_code,
        "model": model,
        "from_version": "4.0.0",
        "to_version": "4.2.1",
        "window_start_utc": window_start_utc,
        "window_end_utc": window_end_utc,
    }


def _create_campaign(campaign_code: str, model: str, window_start_utc: str,
                     window_end_utc: str) -> dict:
    return get_success_data(
        api_client.create_firmware_campaign(
            _campaign_payload(campaign_code, model, window_start_utc, window_end_utc),
            FIRMWARE_ENGINEER,
        )
    )


def _setup_scheduled_september_neo_campaign() -> dict:
    set_clock("2026-08-01T00:00:00Z")
    base = _create_campaign("FW-NEO-SEP", "NEO", BASE_WINDOW_START_UTC, BASE_WINDOW_END_UTC)
    base = get_success_data(api_client.schedule_firmware_campaign(base["id"], FIRMWARE_ENGINEER))
    assert base["status"] == "SCHEDULED", (
        f"the occupying campaign must be SCHEDULED to hold a window, got {base['status']!r}"
    )
    return {"base": base}


def test_same_model_window_starting_where_another_ends_is_refused():
    """"no other campaign for the same `model` whose `status` is `SCHEDULED`, `ROLLING` or `PAUSED`
    may occupy an intersecting window. **Window collision uses non-strict comparisons on both
    sides**: a conflict exists when this campaign's `window_start_utc` is at or before the other's
    `window_end_utc` and the other's `window_start_utc` is at or before this campaign's
    `window_end_utc`. Touching endpoints therefore collide — a window starting at the exact instant
    another ends is a conflict ... A collision is refused with `ERR_CAMPAIGN_WINDOW_CONFLICT`."
    (PRD §3.9)

    Design: Difficulty/resource_temporal_overlap/campaign_window_closed_interval_touching_endpoints_collide
    """
    env = _setup_scheduled_september_neo_campaign()
    touching = _create_campaign(
        "FW-NEO-TOUCH", "NEO", TOUCHING_WINDOW_START_UTC, TOUCHING_WINDOW_END_UTC
    )

    resp = api_client.schedule_firmware_campaign(touching["id"], FIRMWARE_ENGINEER)
    validate_error(resp, ApiErrorId.ERR_CAMPAIGN_WINDOW_CONFLICT.value)

    refused = validate_success(api_client.get_firmware_campaign(touching["id"], FIRMWARE_ENGINEER))
    assert refused["status"] == "DRAFT", (
        f"a refused schedule leaves the campaign in DRAFT, got {refused['status']!r}"
    )

    holder = validate_success(
        api_client.get_firmware_campaign(env["base"]["id"], FIRMWARE_ENGINEER)
    )
    assert holder["status"] == "SCHEDULED", (
        f"the occupying campaign is untouched by the refusal, got {holder['status']!r}"
    )


def test_window_collision_only_applies_within_the_same_model():
    """"Campaigns in `DRAFT`, `COMPLETED` or `ABORTED` occupy no window, and only same-model
    campaigns can collide." (PRD §3.9)

    "Scheduling moves the campaign `DRAFT → SCHEDULED`" (PRD §3.9)

    Design: Difficulty/resource_temporal_overlap/campaign_window_closed_interval_touching_endpoints_collide
    """
    _setup_scheduled_september_neo_campaign()
    other_model = _create_campaign(
        "FW-LINK-SEP", "LINK", BASE_WINDOW_START_UTC, BASE_WINDOW_END_UTC
    )

    scheduled = validate_success(
        api_client.schedule_firmware_campaign(other_model["id"], FIRMWARE_ENGINEER)
    )
    assert scheduled["status"] == "SCHEDULED", (
        "an identical window on a different model must schedule cleanly, got "
        f"{scheduled['status']!r}"
    )


def test_same_model_window_starting_one_second_after_another_ends_is_accepted():
    """"a conflict exists when this campaign's `window_start_utc` is at or before the other's
    `window_end_utc` and the other's `window_start_utc` is at or before this campaign's
    `window_end_utc`." (PRD §3.9)

    "Scheduling moves the campaign `DRAFT → SCHEDULED` and enforces three conditions:
    `window_start_utc` must be strictly before `window_end_utc`, `to_version` must differ from
    `from_version`, and no other campaign for the same `model` whose `status` is `SCHEDULED`,
    `ROLLING` or `PAUSED` may occupy an intersecting window." (PRD §3.9)

    Design: Difficulty/resource_temporal_overlap/campaign_window_closed_interval_touching_endpoints_collide
    """
    _setup_scheduled_september_neo_campaign()
    disjoint = _create_campaign(
        "FW-NEO-OCT", "NEO", ONE_SECOND_LATER_START_UTC, TOUCHING_WINDOW_END_UTC
    )

    scheduled = validate_success(
        api_client.schedule_firmware_campaign(disjoint["id"], FIRMWARE_ENGINEER)
    )
    assert scheduled["status"] == "SCHEDULED", (
        "a window opening one second after the other closes does not intersect, got "
        f"{scheduled['status']!r}"
    )


# ---------------------------------------------------------------------------
# Trial pauses: closed intervals that merge on touch, plus an inclusive budget
# ---------------------------------------------------------------------------
def _run_repair_pause(env: dict, open_utc: str, close_utc: str) -> dict:
    """Open a depot pause at open_utc and close it by returning the unit at close_utc."""
    repair = get_success_data(
        api_client.create_repair_order(
            {"device_id": env["assigned_device"]["id"], "fault_code": "NO_SOUND"},
            make_patient_headers(env["patient"]["id"]),
        )
    )
    get_success_data(api_client.send_repair_kit(repair["id"], CARE_OPS))
    set_clock(open_utc)
    get_success_data(api_client.receive_repair_order(repair["id"], REPAIR_TECH))
    get_success_data(api_client.start_repair_order(repair["id"], REPAIR_TECH))
    get_success_data(
        api_client.resolve_repair_order(repair["id"], {"resolution": "REPAIRED"}, REPAIR_TECH)
    )
    set_clock(close_utc)
    return get_success_data(api_client.return_repair_to_patient(repair["id"], REPAIR_TECH))


def _setup_trial_with_two_touching_pauses() -> dict:
    """A 90-day trial paused 08-05 to 08-15 and then 08-15 to 10-30 — the intervals touch."""
    env = setup_delivered_order(policy_overrides={"trial_period_days": TRIAL_DAYS})
    _run_repair_pause(env, FIRST_PAUSE_OPEN_UTC, FIRST_PAUSE_CLOSE_UTC)
    _run_repair_pause(env, FIRST_PAUSE_CLOSE_UTC, SECOND_PAUSE_CLOSE_UTC)
    return env


def test_touching_pause_intervals_merge_into_one_paused_span():
    """"Intervals are sorted by `pause_start_utc` ascending with their insertion order in the array
    as the tie-break, then merged: when the next interval's start is at or before the running
    interval's end, the two merge and the running end becomes the later of the two ends — touching
    endpoints therefore merge rather than double-count. `paused_days` is the total merged paused
    duration in seconds divided by 86,400 seconds (24 hours) and floored. Elapsed days are the
    counting-window end minus `started_at`, in seconds, divided by 86,400 and floored ... `days_used`
    is the elapsed days minus `paused_days`, floored at 0. And `effective_end_utc` — the deadline
    that actually gates a return — is `nominal_end_utc` plus `paused_days` days plus
    `extension_days_granted` days." (PRD §3.6)

    Design: Difficulty/resource_temporal_overlap/trial_pause_touching_intervals_allowed_until_aggregate_budget_exhausted
    """
    env = _setup_trial_with_two_touching_pauses()

    trial = validate_success(api_client.get_trial_period(env["trial"]["id"], CARE_OPS))
    assert trial["status"] == "ACTIVE", (
        f"returning the repaired unit drives the trial PAUSED to ACTIVE, got {trial['status']!r}"
    )
    assert len(trial["pause_intervals"]) == 2, (
        f"two depot receipts append two intervals, got {len(trial['pause_intervals'])}"
    )
    assert all(interval["pause_end_utc"] is not None for interval in trial["pause_intervals"]), (
        "both intervals must be closed once each repaired unit has been returned"
    )
    assert trial["paused_days"] == EXPECTED_PAUSED_DAYS, (
        "the touching intervals merge into 08-05 through 10-30, which is "
        f"{EXPECTED_PAUSED_DAYS} whole days, got {trial['paused_days']}"
    )
    assert trial["days_used"] == EXPECTED_DAYS_USED_AT_RESUME, (
        f"90 elapsed days minus {EXPECTED_PAUSED_DAYS} paused days is "
        f"{EXPECTED_DAYS_USED_AT_RESUME}, got {trial['days_used']}"
    )
    assert _same_instant(trial["nominal_end_utc"], EXPECTED_NOMINAL_END_UTC), (
        f"a 90-day trial started 2026-08-01 nominally ends {EXPECTED_NOMINAL_END_UTC}, got "
        f"{trial['nominal_end_utc']!r}"
    )
    assert _same_instant(trial["effective_end_utc"], EXPECTED_EFFECTIVE_END_UTC), (
        f"the nominal end plus {EXPECTED_PAUSED_DAYS} paused days is "
        f"{EXPECTED_EFFECTIVE_END_UTC}, got {trial['effective_end_utc']!r}"
    )


def test_third_pause_refused_once_the_aggregate_budget_is_reached():
    """"And the trial carries an aggregate budget: once `paused_days` has reached 60, which is
    inclusive, no new pause may open, rejected with `ERR_PAUSE_BUDGET_EXHAUSTED`." (PRD §3.6)

    "A depot receipt of a device that is under trial pauses the clock, moving the trial
    `ACTIVE → PAUSED` and appending a new interval whose start is the current logical clock and
    whose end is still null." (PRD §3.6)

    Design: Difficulty/resource_temporal_overlap/trial_pause_touching_intervals_allowed_until_aggregate_budget_exhausted
    """
    env = _setup_trial_with_two_touching_pauses()
    third = get_success_data(
        api_client.create_repair_order(
            {"device_id": env["assigned_device"]["id"], "fault_code": "NO_SOUND"},
            make_patient_headers(env["patient"]["id"]),
        )
    )
    get_success_data(api_client.send_repair_kit(third["id"], CARE_OPS))
    set_clock(THIRD_PAUSE_ATTEMPT_UTC)

    resp = api_client.receive_repair_order(third["id"], REPAIR_TECH)
    validate_error(resp, ApiErrorId.ERR_PAUSE_BUDGET_EXHAUSTED.value)

    trial = validate_success(api_client.get_trial_period(env["trial"]["id"], CARE_OPS))
    assert trial["status"] == "ACTIVE", (
        f"the refused receipt must not pause the trial, got {trial['status']!r}"
    )
    assert trial["paused_days"] == EXPECTED_PAUSED_DAYS, (
        f"the refused receipt adds no paused days, expected {EXPECTED_PAUSED_DAYS}, got "
        f"{trial['paused_days']}"
    )
    assert len(trial["pause_intervals"]) == 2, (
        f"the refused receipt appends no interval, got {len(trial['pause_intervals'])}"
    )
    assert _same_instant(trial["effective_end_utc"], EXPECTED_EFFECTIVE_END_UTC), (
        f"the deadline is unchanged at {EXPECTED_EFFECTIVE_END_UTC}, got "
        f"{trial['effective_end_utc']!r}"
    )
