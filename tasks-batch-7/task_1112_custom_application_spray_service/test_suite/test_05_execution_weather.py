"""Execution gates: weather envelope, observation freshness, REI lockout,
assignment authorization, and the WEATHER_HOLD cycle."""
import pytest
from test_helpers import (
    api_client, validate_success, validate_error, get_success_data,
    create_work_order, schedule_work_order, must_schedule, post_weather,
    set_clock, start_work_order, must_start, complete_work_order,
    create_applicator, create_equipment, post_calibration,
    base_environment, scheduled_environment, in_progress_environment,
    completed_environment, make_applicator_headers,
    REI_UNTIL_STANDARD, TEST_USERS,
)

DISPATCHER = TEST_USERS["dispatcher_headers"]
ADMIN = TEST_USERS["admin_headers"]


def test_wind_exactly_at_envelope_max_passes(api):
    """PRD §3.5: "its `wind_mph` is at most the effective maximum (a reading
    exactly equal to the limit passes)"

    Design: Difficulty/boundary_precision_check/wind_exactly_at_envelope_max_passes
    """
    env = scheduled_environment()
    post_weather(env["applicator"]["id"], wind_mph=10.0)  # effective cap min(10,15)=10
    set_clock("2026-05-10T08:00:00Z")
    started = must_start(env["work_order"]["id"], env["applicator"]["id"])
    assert started["status"] == "IN_PROGRESS"


def test_wind_one_tenth_over_envelope_max_fails(api):
    """PRD §3.5: "its `wind_mph` is at most the effective maximum (a reading
    exactly equal to the limit passes), its `temp_f` sits inside the band
    inclusively on both ends, and `inversion_present` is false."
    PRD §3.5: "That observation must satisfy the mix envelope (below), else
    `ERR_WEATHER_WINDOW_VIOLATION`."

    Design: Difficulty/boundary_precision_check/wind_exactly_at_envelope_max_passes
    """
    env = scheduled_environment()
    post_weather(env["applicator"]["id"], wind_mph=10.1)
    set_clock("2026-05-10T08:00:00Z")
    res = start_work_order(env["work_order"]["id"], env["applicator"]["id"])
    validate_error(res, "ERR_WEATHER_WINDOW_VIOLATION", expected_status=409)


def test_mix_envelope_nested_min_max(api):
    """PRD §3.5: "The effective maximum wind is the smallest `max_wind_mph`
    among the line products; the effective temperature band runs from the
    largest `min_temp_f` to the smallest `max_temp_f`."
    PRD §3.5: "That observation must satisfy the mix envelope (below), else
    `ERR_WEATHER_WINDOW_VIOLATION`."

    Design: Difficulty/combinatorial_formula/mix_envelope_nested_min_max
    """
    env = scheduled_environment()
    set_clock("2026-05-10T08:00:00Z")

    # Wind 12 is legal for P2 (15) alone but exceeds the mix cap min(10,15)=10.
    post_weather(env["applicator"]["id"], observed_at="2026-05-10T07:30:00Z", wind_mph=12)
    res1 = start_work_order(env["work_order"]["id"], env["applicator"]["id"])
    validate_error(res1, "ERR_WEATHER_WINDOW_VIOLATION", expected_status=409)

    # Temp 45 is legal for P1 (40) alone but below the mix floor max(40,50)=50.
    post_weather(env["applicator"]["id"], observed_at="2026-05-10T07:45:00Z",
                 wind_mph=8, temp_f=45)
    res2 = start_work_order(env["work_order"]["id"], env["applicator"]["id"])
    validate_error(res2, "ERR_WEATHER_WINDOW_VIOLATION", expected_status=409)

    wo = validate_success(api.get_work_order(env["work_order"]["id"], DISPATCHER), 200)
    assert wo["status"] == "SCHEDULED", "both envelope-violating starts must be rejected"


def test_mix_envelope_temperature_floor_boundary(api):
    """PRD §3.5: "the effective temperature band runs from the largest
    `min_temp_f` to the smallest `max_temp_f`."
    PRD §3.5: "The envelope passes when the observation is fresh, its
    `wind_mph` is at most the effective maximum (a reading exactly equal to the
    limit passes), its `temp_f` sits inside the band inclusively on both ends,
    and `inversion_present` is false."

    Design: Difficulty/combinatorial_formula/mix_envelope_nested_min_max
    """
    env = scheduled_environment()
    set_clock("2026-05-10T08:00:00Z")

    # 49.9 < max(40,50)=50: below the inclusive floor.
    post_weather(env["applicator"]["id"], observed_at="2026-05-10T07:30:00Z", temp_f=49.9)
    res = start_work_order(env["work_order"]["id"], env["applicator"]["id"])
    validate_error(res, "ERR_WEATHER_WINDOW_VIOLATION", expected_status=409)

    # Exactly 50: inside the band, start succeeds.
    post_weather(env["applicator"]["id"], observed_at="2026-05-10T07:45:00Z", temp_f=50)
    started = must_start(env["work_order"]["id"], env["applicator"]["id"])
    assert started["status"] == "IN_PROGRESS"


def test_observation_staleness_boundary_at_start(api):
    """PRD §3.5: "the WeatherObservation with the greatest `observed_at` (ties
    broken by the latest `created_at`) must have been taken no more than 60
    minutes before now, else `ERR_OBSERVATION_STALE`."

    Design: Corner/validations/observation_staleness_boundary_at_start
    """
    env = scheduled_environment(num_products=1, scheduled_end="2026-05-10T12:00:00Z")
    post_weather(env["applicator"]["id"], observed_at="2026-05-10T07:00:00Z")

    set_clock("2026-05-10T08:01:00Z")  # observation is 61 minutes old
    res = start_work_order(env["work_order"]["id"], env["applicator"]["id"])
    validate_error(res, "ERR_OBSERVATION_STALE", expected_status=409)

    set_clock("2026-05-10T08:00:00Z")  # exactly 60 minutes old: still fresh
    started = must_start(env["work_order"]["id"], env["applicator"]["id"])
    assert started["status"] == "IN_PROGRESS"


def test_start_blocked_by_field_rei_then_passes_at_boundary(api):
    """PRD §3.5: "The field's re-entry lockout must have expired: `rei_until`
    is either null or the current time is on or after it — the boundary is
    half-open, so arriving exactly at `rei_until` is permitted — else
    `ERR_REI_ACTIVE`."
    PRD §3.5: "The field's `rei_until` advances to the later of its existing
    value and `completed_at` plus the largest `rei_hours` among the applied
    products — the lockout never moves earlier"

    Design: Difficulty/cross_entity_state_dependency/start_blocked_by_field_rei
    """
    env = completed_environment(acres_to_treat=50)  # completed 2026-05-10T10:30:00Z
    field = validate_success(api.get_field(env["field"]["id"], ADMIN), 200)
    assert field["rei_until"] == REI_UNTIL_STANDARD, \
        f"rei_until must be completed_at + max(24,48)h = {REI_UNTIL_STANDARD}, got {field['rei_until']}"

    wo2 = create_work_order(env["customer"]["id"], env["field"]["id"],
                            env["prescription"]["id"], acres_to_treat=40)
    must_schedule(wo2["id"], env["applicator"]["id"], env["equipment"]["id"],
                  scheduled_start="2026-05-12T08:00:00Z",
                  scheduled_end="2026-05-12T11:00:00Z")

    # One hour before rei_until: lockout still in force.
    post_weather(env["applicator"]["id"], observed_at="2026-05-12T09:00:00Z")
    set_clock("2026-05-12T09:30:00Z")
    res = start_work_order(wo2["id"], env["applicator"]["id"])
    validate_error(res, "ERR_REI_ACTIVE", expected_status=409)

    # Exactly at rei_until: half-open boundary permits entry.
    post_weather(env["applicator"]["id"], observed_at="2026-05-12T10:15:00Z")
    set_clock("2026-05-12T10:30:00Z")
    started = must_start(wo2["id"], env["applicator"]["id"])
    assert started["status"] == "IN_PROGRESS"


def test_start_on_field_with_null_rei_passes(api):
    """PRD §3.5: "The field's re-entry lockout must have expired: `rei_until`
    is either null or the current time is on or after it"
    PRD §3.1: "A fresh field has `rei_until` null, meaning no re-entry lockout
    has ever been set on it"

    Design: Difficulty/cross_entity_state_dependency/start_blocked_by_field_rei
    """
    env = scheduled_environment()
    field = validate_success(api.get_field(env["field"]["id"], ADMIN), 200)
    assert field["rei_until"] is None
    post_weather(env["applicator"]["id"])
    set_clock("2026-05-10T08:00:00Z")
    started = must_start(env["work_order"]["id"], env["applicator"]["id"])
    assert started["status"] == "IN_PROGRESS"


def test_applicator_cannot_start_others_job(api):
    """PRD §3.5: "Starting a `SCHEDULED` work order requires the caller's
    `X-User-ID` to equal the order's `applicator_id` (else `ERR_FORBIDDEN`)"

    Design: Corner/rbac/applicator_cannot_start_others_job
    """
    env = scheduled_environment(num_products=1)
    ap2 = create_applicator(display_name="Bob", license_no="L-200",
                            license_categories=["HERBICIDE"])
    post_weather(env["applicator"]["id"])
    set_clock("2026-05-10T08:00:00Z")
    res = start_work_order(env["work_order"]["id"], ap2["id"])
    validate_error(res, "ERR_FORBIDDEN", expected_status=403)


def test_work_order_weather_hold_cycle(api):
    """PRD §3.5: "Posting an observation is never inert: any `IN_PROGRESS` work
    order whose mix envelope the new reading violates is automatically moved to
    `WEATHER_HOLD`, with its `version` incremented."
    PRD §3.5: "success returns the order to `IN_PROGRESS` and increments its
    `version`."

    Design: Difficulty/non_linear_state_machine/work_order_weather_hold_cycle
    """
    env = in_progress_environment()
    ap = env["applicator"]["id"]
    wo_id = env["work_order"]["id"]

    # A violating reading (wind 12 > effective cap 10) holds the job.
    set_clock("2026-05-10T08:20:00Z")
    post_weather(ap, observed_at="2026-05-10T08:15:00Z", wind_mph=12)
    held = validate_success(api.get_work_order(wo_id, DISPATCHER), 200)
    assert held["status"] == "WEATHER_HOLD", \
        f"violating observation must auto-hold the in-progress job, got {held['status']}"

    # A passing fresh reading lets the same applicator resume.
    set_clock("2026-05-10T08:50:00Z")
    post_weather(ap, observed_at="2026-05-10T08:45:00Z", wind_mph=8)
    resumed = validate_success(api_client.resume_work_order(
        wo_id, make_applicator_headers(ap)), 200)
    assert resumed["status"] == "IN_PROGRESS"
    assert resumed["started_at"] == "2026-05-10T08:00:00.000Z", \
        "the hold cycle preserves the original start stamp"
    assert resumed["applicator_id"] == ap, "the hold retains the assignment"


def test_resume_rejected_while_latest_observation_violates(api):
    """PRD §3.5: "Resuming a held order again requires the caller to be the
    assigned applicator (else `ERR_FORBIDDEN`), a fresh observation no older
    than 60 minutes (else `ERR_OBSERVATION_STALE`), and a passing envelope
    (else `ERR_WEATHER_WINDOW_VIOLATION`)"

    Design: Difficulty/non_linear_state_machine/work_order_weather_hold_cycle
    """
    env = in_progress_environment()
    ap = env["applicator"]["id"]
    wo_id = env["work_order"]["id"]

    set_clock("2026-05-10T08:20:00Z")
    post_weather(ap, observed_at="2026-05-10T08:15:00Z", wind_mph=12)  # violates -> hold
    held = validate_success(api.get_work_order(wo_id, DISPATCHER), 200)
    assert held["status"] == "WEATHER_HOLD"

    # The freshest observation is fresh in time but still violates the envelope.
    res = api_client.resume_work_order(wo_id, make_applicator_headers(ap))
    validate_error(res, "ERR_WEATHER_WINDOW_VIOLATION", expected_status=409)


def test_state_beats_safety_on_cancelled_start(api):
    """PRD §2.9: "When several checks could reject the same request, the server
    evaluates them in a fixed precedence order so the reported failure is
    deterministic." — state (category 6, surfacing `ERR_INVALID_STATE`) is
    evaluated before regulatory safety gates (category 7, surfacing
    `ERR_REI_ACTIVE`).

    Design: Difficulty/priority_pair_validation_conflict/state_beats_safety_on_cancelled_start
    """
    env = completed_environment(acres_to_treat=50)  # field rei_until 2026-05-12T10:30:00Z
    ap = env["applicator"]["id"]

    wo2 = create_work_order(env["customer"]["id"], env["field"]["id"],
                            env["prescription"]["id"], acres_to_treat=40)
    must_schedule(wo2["id"], ap, env["equipment"]["id"],
                  scheduled_start="2026-05-11T08:00:00Z",
                  scheduled_end="2026-05-11T11:00:00Z")
    validate_success(api_client.cancel_work_order(wo2["id"], DISPATCHER), 200)

    # REI is still active (rei_until 2026-05-12T10:30) AND the order is
    # CANCELLED: the state error must win over the safety error.
    post_weather(ap, observed_at="2026-05-11T07:30:00Z")
    set_clock("2026-05-11T08:00:00Z")
    res = start_work_order(wo2["id"], ap)
    validate_error(res, "ERR_INVALID_STATE", expected_status=409)


def test_state_beats_staleness_on_cancelled_start(api):
    """PRD §2.9: "When several checks could reject the same request, the server
    evaluates them in a fixed precedence order so the reported failure is
    deterministic." — state (category 6, surfacing `ERR_INVALID_STATE`) is
    evaluated before regulatory safety gates (category 7, surfacing
    `ERR_OBSERVATION_STALE`).

    Design: Difficulty/priority_pair_validation_conflict/state_beats_safety_on_cancelled_start
    """
    env = scheduled_environment()
    ap = env["applicator"]["id"]
    validate_success(api_client.cancel_work_order(env["work_order"]["id"], DISPATCHER), 200)

    # No weather observation at all (staleness gate would fail) AND the order
    # is CANCELLED: the state error must win.
    set_clock("2026-05-10T08:00:00Z")
    res = start_work_order(env["work_order"]["id"], ap)
    validate_error(res, "ERR_INVALID_STATE", expected_status=409)
