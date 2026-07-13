"""Day/night population, the cyclic zone-order machine, and the household cascade."""
from test_helpers import (
    validate_success, validate_error,
    ApiErrorId, assert_zone,
    create_active_incident, create_zone, order_zone, set_clock,
    setup_checkin_scenario, TEST_USERS,
)

COMMANDER = TEST_USERS["commander_headers"]
TRAFFIC = TEST_USERS["traffic_headers"]
SHELTER = TEST_USERS["shelter_headers"]
REGISTRAR = TEST_USERS["registrar_headers"]


def test_zone_population_daytime_variant(api):
    """PRD 2.5: "During daytime, a zone's `population_at_risk` is the resident headcount multiplied by the `daytime_occupancy_factor` plus the full `transient_population`, then rounded half-up to a whole number."
    PRD 2.5: "the daytime window is the hours from 6 up to but not including 18 (that is, an hour at least 6 and less than 18)."

    Design: Difficulty/dual_variant_calc/population_day_vs_night_on_zone
    """
    inc = create_active_incident()
    zone = create_zone(inc["id"], residential_population=1000, transient_population=200,
                       daytime_occupancy_factor=1.2, nighttime_occupancy_factor=0.9)
    set_clock("2026-03-01T12:00:00Z")

    data = validate_success(api.get_zone(zone["id"], COMMANDER))
    assert_zone(data)
    # round_half_up(1000*1.2 + 200) == 1400
    assert data["population_at_risk"] == 1400


def test_zone_population_nighttime_variant(api):
    """PRD 2.5: "During nighttime (any hour outside that window), the transient population is excluded entirely and `population_at_risk` is the resident headcount multiplied by the `nighttime_occupancy_factor`, rounded half-up to a whole number."
    PRD 2.5: "At startup, and before any clock-setting call has been made, the clock reads exactly `2026-03-01T00:00:00Z`."

    Design: Difficulty/dual_variant_calc/population_day_vs_night_on_zone
    """
    inc = create_active_incident()
    zone = create_zone(inc["id"], residential_population=1000, transient_population=200,
                       daytime_occupancy_factor=1.2, nighttime_occupancy_factor=0.9)

    # Default clock is 2026-03-01T00:00:00Z (hour 0 -> nighttime); no clock set.
    data = validate_success(api.get_zone(zone["id"], COMMANDER))
    assert_zone(data)
    # round_half_up(1000*0.9), transients excluded == 900
    assert data["population_at_risk"] == 900


def test_zone_reentry_back_to_mandatory_cycles(api):
    """PRD 3.2: "Re-evacuating `RE_ENTRY_ALLOWED → MANDATORY` reverses re-entry as a compensation: every credential on the zone currently `ACTIVE` is `SUSPENDED`, and every household at `CLEARED_FOR_REENTRY` moves back to `ORDERED`."
    PRD 3.2: "The requested target must additionally be reachable from the zone's current `order_level`, or the request is rejected with `ERR_INVALID_ORDER_TRANSITION`."

    Design: Difficulty/non_linear_state_machine/zone_cyclic_reentry_back_to_mandatory
    """
    inc = create_active_incident()
    zone = create_zone(inc["id"])
    order_zone(zone["id"], "MANDATORY")
    order_zone(zone["id"], "RE_ENTRY_ALLOWED")

    data = validate_success(api.set_zone_order(zone["id"], {"level": "MANDATORY"}, COMMANDER))
    assert data["order_level"] == "MANDATORY"


def test_zone_version_increments_across_reentry_cycle(api):
    """PRD 3.2: "The legal operator-driven transitions and their household cascades are as follows, and each recomputes the zone's `population_at_risk`, stamps `order_issued_at` with the current clock, and increments the zone `version`"
    PRD 2.4: "The `version` begins at 1 when the resource is created and increments by exactly 1 on every mutation of that resource"

    Design: Difficulty/non_linear_state_machine/zone_cyclic_reentry_back_to_mandatory
    """
    inc = create_active_incident()
    zone = create_zone(inc["id"])
    assert zone["version"] == 1
    v_mand = order_zone(zone["id"], "MANDATORY")["version"]
    v_reentry = order_zone(zone["id"], "RE_ENTRY_ALLOWED")["version"]
    v_remand = order_zone(zone["id"], "MANDATORY")["version"]

    assert v_mand == 2
    assert v_reentry == 3
    assert v_remand == 4


def test_mandatory_order_auto_checks_in_reserved(api):
    """PRD 3.2: "Second, for each such household whose `current_assignment_id` points to an assignment still in `RESERVED`, that assignment is auto-checked-in — moved to `CHECKED_IN` with `checked_in_at` stamped to now — and the household moves to `SHELTERED`."

    Design: Difficulty/transitive_cascade/mandatory_order_cascade_zone_registrant_assignment_shelter
    """
    ctx = setup_checkin_scenario(order_level="VOLUNTARY", physical_capacity=3, staffed_beds=3,
                                 ada_reserved_pct=0, party_size=3, open_shelter=True)
    order_zone(ctx["zone"]["id"], "MANDATORY")

    reg = validate_success(api.get_registrant(ctx["registrant"]["id"], COMMANDER))
    asg = validate_success(api.get_shelter_assignment(ctx["assignment"]["id"], COMMANDER))
    assert reg["status"] == "SHELTERED"
    assert asg["status"] == "CHECKED_IN"


def test_mandatory_order_tips_shelter_full(api):
    """PRD 3.2: "Third, each shelter that received an auto-check-in recomputes its `reserved_beds` and `occupied_beds`, and if `occupied_beds` has reached or exceeded `effective_capacity` it moves `OPEN → FULL`."

    Design: Difficulty/transitive_cascade/mandatory_order_cascade_zone_registrant_assignment_shelter
    """
    ctx = setup_checkin_scenario(order_level="VOLUNTARY", physical_capacity=3, staffed_beds=3,
                                 ada_reserved_pct=0, party_size=3, open_shelter=True)
    order_zone(ctx["zone"]["id"], "MANDATORY")

    shelter = validate_success(api.get_shelter(ctx["shelter"]["id"], COMMANDER))
    assert shelter["status"] == "FULL"
    assert shelter["occupied_beds"] == 3
    assert shelter["reserved_beds"] == 0


def test_zone_order_none_to_reentry_is_invalid_transition(api):
    """PRD 3.2: "The requested target must additionally be reachable from the zone's current `order_level`, or the request is rejected with `ERR_INVALID_ORDER_TRANSITION`."

    Design: Corner/state_machines/zone_order_none_to_reentry_is_invalid_transition
    """
    inc = create_active_incident()
    zone = create_zone(inc["id"])

    resp = api.set_zone_order(zone["id"], {"level": "RE_ENTRY_ALLOWED"}, COMMANDER)
    validate_error(resp, ApiErrorId.ERR_INVALID_ORDER_TRANSITION)


def test_traffic_manager_cannot_issue_zone_order(api):
    """PRD 2.1: "If the headers are well-formed but the named role is not permitted to perform the requested operation, the request is rejected with `ERR_UNAUTHORIZED_ROLE` (HTTP 403)."
    PRD 2.1: "all other write operations are exclusive to the single owning role listed in the endpoint table of Section 4."

    Design: Corner/rbac/traffic_manager_cannot_issue_zone_order
    """
    inc = create_active_incident()
    zone = create_zone(inc["id"])

    resp = api.set_zone_order(zone["id"], {"level": "MANDATORY"}, TRAFFIC)
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED_ROLE)
