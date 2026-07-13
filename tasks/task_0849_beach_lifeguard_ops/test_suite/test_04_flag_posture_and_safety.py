"""Zone swim-flag cycle, safety-check precedence, and the understaffing cascade."""
from test_helpers import (
    validate_success, validate_error,
    ApiErrorId,
    TEST_USERS,
    setup_beach_zone, setup_scheduled_shift, setup_green_zone,
    clock_in, clock_out, raise_flag,
)

CAPTAIN = TEST_USERS["beach_captain_headers"]


# --- Non-linear (cyclic) flag machine ----------------------------------------

def test_flag_green_to_yellow(api):
    """PRD §3.4: "From `RED` the captain may raise the flag to `GREEN`; from `GREEN` to
    `YELLOW`; from `YELLOW` back to `GREEN`; and from either `GREEN` or `YELLOW` back down to
    `RED`."

    Design: Difficulty/non_linear_state_machine/zone_flag_green_yellow_green_cycle
    """
    beach, zone, tower, guard, shift = setup_green_zone(api)
    data = validate_success(api.set_zone_flag(zone["id"], {"flag_status": "YELLOW"}, CAPTAIN), 200)
    assert data["flag_status"] == "YELLOW", f"GREEN->YELLOW expected YELLOW, got {data['flag_status']}"


def test_flag_yellow_back_to_green_closes_cycle(api):
    """PRD §3.4: "From `RED` the captain may raise the flag to `GREEN`; from `GREEN` to
    `YELLOW`; from `YELLOW` back to `GREEN`; and from either `GREEN` or `YELLOW` back down to
    `RED`."

    Design: Difficulty/non_linear_state_machine/zone_flag_green_yellow_green_cycle
    """
    beach, zone, tower, guard, shift = setup_green_zone(api)
    raise_flag(api, zone["id"], "YELLOW")
    data = validate_success(api.set_zone_flag(zone["id"], {"flag_status": "GREEN"}, CAPTAIN), 200)
    assert data["flag_status"] == "GREEN", f"YELLOW->GREEN expected GREEN, got {data['flag_status']}"


# --- Precedence: rip-current (safety) outranks understaffed (constraint) -----

def _setup_high_rip_understaffed_zone(api):
    beach, zone = setup_beach_zone(api, min_guards_required=1, clock="2026-07-15T09:00:00Z")
    validate_success(
        api.post_zone_conditions(zone["id"], {"rip_current_level": "HIGH", "weather_note": "storm swell"}, CAPTAIN),
        200,
    )
    return beach, zone


def test_rip_current_unsafe_reported_before_understaffed_on_green(api):
    """PRD §2.5: "For raising a swim flag, the requested transition must first be legal for the
    zone's current posture (`ERR_INVALID_STATE`, 409), then no active closure may be in force
    (`ERR_ZONE_UNDER_CLOSURE`, 409), then the rip current must be safe (`ERR_RIP_CURRENT_UNSAFE`,
    409), and finally the zone must be adequately staffed (`ERR_ZONE_UNDERSTAFFED`, 409)."

    Design: Difficulty/priority_pair_validation_conflict/flag_green_rip_beats_understaffed
    """
    beach, zone = _setup_high_rip_understaffed_zone(api)
    resp = api.set_zone_flag(zone["id"], {"flag_status": "GREEN"}, CAPTAIN)
    validate_error(resp, ApiErrorId.ERR_RIP_CURRENT_UNSAFE.value)


# --- Cross-entity: GREEN gated on guard count derived from shifts -------------

def test_raise_green_rejected_when_zone_understaffed(api):
    """PRD §3.4: "Third, the zone's `on_duty_guard_count` must be at least its
    `min_guards_required`, or the raise is rejected with `ERR_ZONE_UNDERSTAFFED` (409)."

    Design: Difficulty/cross_entity_state_dependency/zone_green_requires_guards_from_shifts
    """
    beach, zone, tower, guard, shift = setup_scheduled_shift(api)
    resp = api.set_zone_flag(zone["id"], {"flag_status": "GREEN"}, CAPTAIN)
    validate_error(resp, ApiErrorId.ERR_ZONE_UNDERSTAFFED.value)


def test_raise_green_succeeds_after_guard_clocks_in(api):
    """PRD §3.3: "On clock-in the server stamps `clock_in_at` from the logical clock and
    recomputes the zone's `on_duty_guard_count`, which rises by one."
    PRD §3.4: "Third, the zone's `on_duty_guard_count` must be at least its
    `min_guards_required`, or the raise is rejected with `ERR_ZONE_UNDERSTAFFED` (409)."

    Design: Difficulty/cross_entity_state_dependency/zone_green_requires_guards_from_shifts
    """
    beach, zone, tower, guard, shift = setup_scheduled_shift(api)
    clock_in(api, shift["id"], guard["id"])
    data = validate_success(api.set_zone_flag(zone["id"], {"flag_status": "GREEN"}, CAPTAIN), 200)
    assert data["flag_status"] == "GREEN", f"GREEN must succeed once staffed, got {data['flag_status']}"


# --- Transitive cascade: clock-out drops count -> forces flag RED ------------

def test_clock_out_drops_guard_count_to_zero(api):
    """PRD §3.3: "The server stamps `clock_out_at` from the logical clock and recomputes the
    zone's `on_duty_guard_count`, which falls by one."

    Design: Difficulty/transitive_cascade/clockout_understaffed_cascade_depth2
    """
    beach, zone, tower, guard, shift = setup_green_zone(api)
    clock_out(api, shift["id"], guard["id"])
    zone_after = validate_success(api.get_zone(zone["id"], CAPTAIN), 200)
    assert zone_after["on_duty_guard_count"] == 0, (
        f"count must be 0 after the only guard clocks out, got {zone_after['on_duty_guard_count']}"
    )


def test_clock_out_below_minimum_forces_flag_red(api):
    """PRD §3.3: "if the resulting `on_duty_guard_count` drops below the zone's
    `min_guards_required` while the zone's `flag_status` is `GREEN` or `YELLOW`, the server
    automatically forces `flag_status` down to `RED`, because a swim flag may not fly over an
    understaffed zone."

    Design: Difficulty/transitive_cascade/clockout_understaffed_cascade_depth2
    """
    beach, zone, tower, guard, shift = setup_green_zone(api)
    clock_out(api, shift["id"], guard["id"])
    zone_after = validate_success(api.get_zone(zone["id"], CAPTAIN), 200)
    assert zone_after["flag_status"] == "RED", (
        f"flag must auto-drop to RED when zone falls understaffed, got {zone_after['flag_status']}"
    )
