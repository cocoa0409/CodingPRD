"""Launch: the joint gate where weather, geofence, authorization, drone and pack are all
checked at once, in the fixed order of §2.11."""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import (
    ApiErrorId,
    assert_pct,
    assert_weather_observation,
    charge_battery,
    create_geofence_zone,
    create_weather_observation,
    lift_geofence_zone,
    read_battery,
    read_drone,
    read_flight,
    set_clock,
    setup_cleared_flight,
    setup_grounding_cascade,
    setup_world,
)
from test_helpers.test_users import TEST_USERS

ADMIN = TEST_USERS["platform_admin_headers"]
OPERATOR = TEST_USERS["dispatch_operator_headers"]


# ================================================================== weather flyability
def test_weather_boundaries_are_themselves_flyable(api):
    """PRD §3.1: "On write, the system computes and freezes a boolean `flyable` on the
    observation: it is true when the sustained wind is at most 35.0 kph **and** the gust is at
    most 45.0 kph **and** the visibility is at least 1.5 km **and** the precipitation is either
    `NONE` or `LIGHT`. All three numeric boundaries are themselves flyable — a 35.0 kph wind, a
    45.0 kph gust and a visibility of exactly 1.5 km all pass. `HEAVY` precipitation is never
    flyable regardless of the other three. Observations are immutable once written."

    Design: Corner/calculations/weather_thresholds_are_inclusive_at_35_kph_and_45_kph_gust
    """
    w = setup_world()

    on_boundary = create_weather_observation(
        w["sa"]["id"],
        observed_at="2026-05-01T07:00:00Z",
        wind_kph=35,
        gust_kph=45,
        visibility_km=1.5,
        precip="LIGHT",
    )
    assert on_boundary["flyable"] is True, "35.0 / 45.0 / 1.5 all sit exactly on the boundary"

    over = create_weather_observation(
        w["sa"]["id"],
        observed_at="2026-05-01T08:00:00Z",
        wind_kph=35.1,
        gust_kph=45,
        visibility_km=1.5,
        precip="LIGHT",
    )
    assert over["flyable"] is False, "a 35.1 kph sustained wind exceeds the 35.0 kph limit"


def test_weather_observation_is_immutable_and_publishes_no_version(api):
    """PRD §2.5: "Two entities are exceptions and are immutable after creation:
    `WeatherObservation` and `DeliveryDrop`. Both carry `id` and `created_at` only. Neither has
    an `updated_at` field nor a `version` field, and neither field should appear in their
    response payloads."
    PRD §3.1: "On write, the system computes and freezes a boolean `flyable` on the
    observation: it is true when the sustained wind is at most 35.0 kph **and** the gust is at
    most 45.0 kph **and** the visibility is at least 1.5 km **and** the precipitation is either
    `NONE` or `LIGHT`."

    Design: Corner/entities/weather_observation_is_immutable_and_carries_no_version
    """
    w = setup_world()

    obs = validate_success(
        api.create_weather_observation(
            {
                "service_area_id": w["sa"]["id"],
                "observed_at": "2026-06-01T08:00:00Z",
                "wind_kph": 50,
                "gust_kph": 60,
                "visibility_km": 8,
                "precip": "NONE",
            },
            ADMIN,
        ),
        201,
    )

    assert obs["flyable"] is False, "a 50 kph sustained wind is not flyable"
    assert_weather_observation(obs)
    assert "version" not in obs
    assert "updated_at" not in obs

    reread = validate_success(api.get_weather_observation(obs["id"], ADMIN))
    assert "version" not in reread
    assert "updated_at" not in reread


# ===================================================================== geofence gate
def test_active_geofence_blocks_launch_and_lifting_it_releases_the_sortie(api):
    """PRD §3.6: "No `ACTIVE` geofence zone of the order's service area whose half-open
    effective period contains the current logical clock may intersect the route. The route is
    sampled at three points: the launch nest's coordinates, the order's dropoff point, and the
    midpoint between the two (the arithmetic mean of the two latitudes and the arithmetic mean
    of the two longitudes). A zone intersects if the planar distance from its centre to *any* of
    those three points is less than **or equal to** its `radius_km` — a point sitting exactly on
    the boundary circle is a violation, not a near miss. Any intersection rejects the launch
    with `ERR_GEOFENCE_VIOLATION` (HTTP 409)."
    PRD §3.1: "A published zone's `status` is `ACTIVE`; lifting it moves `status` to `LIFTED`,
    after which it no longer gates anything."

    Design: Corner/calculations/active_geofence_blocks_launch_and_lifted_zone_does_not
    """
    w = setup_cleared_flight()
    zone = create_geofence_zone(
        w["sa"]["id"],
        kind="NO_FLY",
        center_lat=37.05,
        center_lon=-122.0,
        radius_km=1.0,
        effective_from="2026-06-01T08:00:00Z",
        effective_to="2026-06-01T18:00:00Z",
    )

    blocked = api.launch_flight(w["flight"]["id"], OPERATOR)
    validate_error(blocked, ApiErrorId.ERR_GEOFENCE_VIOLATION.value)
    assert read_flight(w["flight"]["id"])["ops_state"] == "PLANNED"

    lifted = lift_geofence_zone(zone["id"])
    assert lifted["status"] == "LIFTED"

    flight = validate_success(api.launch_flight(w["flight"]["id"], OPERATOR))
    assert flight["ops_state"] == "LAUNCHED"
    assert read_drone(w["drone"]["id"])["status"] == "IN_FLIGHT"
    assert read_battery(w["battery"]["id"])["state"] == "IN_USE"


# ================================================== the authorization window (half-open)
def test_launch_at_exactly_the_window_end_is_outside_the_window(api):
    """PRD §3.6: "The current logical clock must fall inside the authorization's half-open
    window: at or after `window_start`, and strictly before `window_end`. A clock at exactly
    `window_end` is outside the window. A launch outside the window is rejected with
    `ERR_AUTHORIZATION_WINDOW_EXPIRED` (HTTP 409)."

    Design: Difficulty/cross_entity_state_dependency/flight_launch_gated_by_authorization_window
    """
    w = setup_cleared_flight()

    set_clock("2026-06-01T12:00:00Z")  # exactly the exclusive end of [08:00Z, 12:00Z)
    resp = api.launch_flight(w["flight"]["id"], OPERATOR)

    validate_error(resp, ApiErrorId.ERR_AUTHORIZATION_WINDOW_EXPIRED.value)


def test_window_expiry_leaves_the_approved_authorization_and_the_flight_untouched(api):
    """PRD §3.6: "The current logical clock must fall inside the authorization's half-open
    window: at or after `window_start`, and strictly before `window_end`. A clock at exactly
    `window_end` is outside the window. A launch outside the window is rejected with
    `ERR_AUTHORIZATION_WINDOW_EXPIRED` (HTTP 409)."
    PRD §3.4: "The winning drone moves `IDLE → RESERVED` and its `version` advances by one."
    PRD §3.4: "The battery is *not* touched at dispatch — it stays `READY` until the sortie
    actually leaves the ground."

    Design: Difficulty/cross_entity_state_dependency/flight_launch_gated_by_authorization_window
    """
    w = setup_cleared_flight()

    set_clock("2026-06-01T12:00:00Z")
    resp = api.launch_flight(w["flight"]["id"], OPERATOR)
    validate_error(resp, ApiErrorId.ERR_AUTHORIZATION_WINDOW_EXPIRED.value)

    auth = validate_success(api.get_airspace_authorization(w["auth"]["id"], ADMIN))
    assert auth["status"] == "APPROVED", "only the clock moved; the authorization still stands"

    flight = read_flight(w["flight"]["id"])
    assert flight["ops_state"] == "PLANNED"
    assert flight["clearance_state"] == "CLEARED"

    assert read_drone(w["drone"]["id"])["status"] == "RESERVED"
    assert read_battery(w["battery"]["id"])["state"] == "READY"


# ============================================================ the energy budget boundary
def test_launch_succeeds_when_charge_exactly_equals_the_required_energy(api):
    """PRD §3.6: "The installed pack's `charge_pct` must be at least the flight's
    `required_energy_pct`. A charge exactly equal to the requirement is sufficient. A charge
    below it rejects the launch with `ERR_INSUFFICIENT_BATTERY` (HTTP 409)."
    PRD §3.6: "On success, four records move together. The flight goes `PLANNED → LAUNCHED` and
    its `version` advances. The drone goes `RESERVED → IN_FLIGHT` and its `version` advances.
    The pack goes `READY → IN_USE` and its `version` advances — no charge is debited yet,
    because the system does not know what the airframe actually flew. And the order bubbles up
    from `ASSIGNED → IN_TRANSIT`, its `version` advancing too."

    Design: Difficulty/boundary_precision_check/launch_charge_exactly_equals_required_energy
    """
    w = setup_cleared_flight()
    assert_pct(w["flight"]["required_energy_pct"], 38.6, "required_energy_pct")

    charge_battery(w["battery"]["id"], 38.6)

    flight = validate_success(api.launch_flight(w["flight"]["id"], OPERATOR))
    assert flight["ops_state"] == "LAUNCHED"
    assert read_drone(w["drone"]["id"])["status"] == "IN_FLIGHT"
    assert read_battery(w["battery"]["id"])["state"] == "IN_USE"


def test_launch_is_rejected_when_charge_falls_one_tenth_below_the_required_energy(api):
    """PRD §3.6: "The installed pack's `charge_pct` must be at least the flight's
    `required_energy_pct`. A charge exactly equal to the requirement is sufficient. A charge
    below it rejects the launch with `ERR_INSUFFICIENT_BATTERY` (HTTP 409)."

    Design: Difficulty/boundary_precision_check/launch_charge_exactly_equals_required_energy
    """
    w = setup_cleared_flight()
    assert_pct(w["flight"]["required_energy_pct"], 38.6, "required_energy_pct")

    charge_battery(w["battery"]["id"], 38.5)  # one tenth of a percent short

    resp = api.launch_flight(w["flight"]["id"], OPERATOR)
    validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_BATTERY.value)

    assert read_flight(w["flight"]["id"])["ops_state"] == "PLANNED"
    assert read_battery(w["battery"]["id"])["state"] == "READY"


# ================================================== priority of the rejection order
def test_launch_reports_the_flight_state_before_the_grounding_of_its_drone(api):
    """PRD §2.11: "When several checks could reject the same request, they are evaluated in a
    fixed order so that the returned error is deterministic."
    PRD §2.11: "9. The state precondition of the transition being attempted (the matching 409
    state code)."
    PRD §2.11: "14. Drone grounding (`ERR_DRONE_GROUNDED`)."
    PRD §3.6: "The flight's `ops_state` must be `PLANNED` — otherwise `ERR_FLIGHT_NOT_PLANNED`
    (HTTP 409)."

    Design: Difficulty/priority_pair_validation_conflict/launch_state_beats_drone_grounded_safety
    """
    w = setup_cleared_flight()
    setup_grounding_cascade(world=w, severity="CRITICAL", category="GROUND_DAMAGE")

    resp = api.launch_flight(w["flight"]["id"], OPERATOR)

    validate_error(resp, ApiErrorId.ERR_FLIGHT_NOT_PLANNED.value)


def test_the_grounding_violation_is_genuinely_present_when_the_state_check_wins(api):
    """PRD §3.6: "The flight's drone must not be `GROUNDED` — otherwise `ERR_DRONE_GROUNDED`
    (HTTP 409). A drone that is neither `GROUNDED` nor `RESERVED` is in a state from which the
    sortie cannot lift off at all."
    PRD §3.8: "Because of hop 2, every flight of that drone whose `ops_state` is `PLANNED`,
    `LAUNCHED`, `DROPPING` or `RETURNING` is force-aborted, with `abort_reason` set to
    `DRONE_GROUNDED` and `actual_route_km` set to 0.0."

    Design: Difficulty/priority_pair_validation_conflict/launch_state_beats_drone_grounded_safety
    """
    w = setup_cleared_flight()
    setup_grounding_cascade(world=w, severity="CRITICAL", category="GROUND_DAMAGE")

    assert read_drone(w["drone"]["id"])["status"] == "GROUNDED", (
        "the lower-priority ERR_DRONE_GROUNDED violation is genuinely present"
    )

    resp = api.launch_flight(w["flight"]["id"], OPERATOR)
    validate_error(resp, ApiErrorId.ERR_FLIGHT_NOT_PLANNED.value)

    flight = read_flight(w["flight"]["id"])
    assert flight["ops_state"] == "ABORTED", "the rejected launch changes nothing"
    assert flight["abort_reason"] == "DRONE_GROUNDED"


def test_launch_reports_weather_no_go_ahead_of_the_energy_budget(api):
    """PRD §2.11: "When several checks could reject the same request, they are evaluated in a
    fixed order so that the returned error is deterministic."
    PRD §2.11: "12. Weather flyability at launch (`ERR_WEATHER_NO_GO`)."
    PRD §2.11: "24. Battery charge sufficient for the flight's energy requirement
    (`ERR_INSUFFICIENT_BATTERY`) — the energy budget is the fiscal check of this domain and it
    runs last among the safety gates."
    PRD §3.6: "The latest weather observation of the order's service area must have `flyable`
    true. A service area with no observations at all counts as flyable. An unflyable latest
    observation rejects the launch with `ERR_WEATHER_NO_GO` (HTTP 409)."

    Design: Difficulty/priority_pair_validation_conflict/launch_weather_safety_beats_energy_fiscal
    """
    w = setup_cleared_flight()
    charge_battery(w["battery"]["id"], 10.0)  # far below the 38.6 the sortie requires
    create_weather_observation(
        w["sa"]["id"],
        observed_at="2026-06-01T08:55:00Z",
        wind_kph=50,
        gust_kph=60,
        visibility_km=8,
        precip="NONE",
    )

    resp = api.launch_flight(w["flight"]["id"], OPERATOR)

    validate_error(resp, ApiErrorId.ERR_WEATHER_NO_GO.value)


def test_the_energy_violation_is_genuinely_present_when_the_weather_gate_wins(api):
    """PRD §3.6: "The installed pack's `charge_pct` must be at least the flight's
    `required_energy_pct`. A charge exactly equal to the requirement is sufficient. A charge
    below it rejects the launch with `ERR_INSUFFICIENT_BATTERY` (HTTP 409)."
    PRD §3.4: "The `wind_kph_at_dispatch` is frozen at this moment from the `wind_kph` of the
    latest weather observation of the order's service area (latest by `observed_at`, ties broken
    by `created_at`); when the area has no observation at all, the frozen wind is 0."

    Design: Difficulty/priority_pair_validation_conflict/launch_weather_safety_beats_energy_fiscal
    """
    w = setup_cleared_flight()
    charge_battery(w["battery"]["id"], 10.0)
    create_weather_observation(
        w["sa"]["id"],
        observed_at="2026-06-01T08:55:00Z",
        wind_kph=50,
        gust_kph=60,
        visibility_km=8,
        precip="NONE",
    )

    resp = api.launch_flight(w["flight"]["id"], OPERATOR)
    validate_error(resp, ApiErrorId.ERR_WEATHER_NO_GO.value)

    battery = read_battery(w["battery"]["id"])
    flight = read_flight(w["flight"]["id"])

    # the fiscal violation really is there: 10.0 < 38.6.
    assert_pct(battery["charge_pct"], 10.0, "charge_pct")
    assert_pct(flight["required_energy_pct"], 38.6, "required_energy_pct")
    # the wind was frozen at dispatch, before the no-go observation was published.
    assert_pct(flight["wind_kph_at_dispatch"], 0.0, "wind_kph_at_dispatch")
    # no side effect fired.
    assert flight["ops_state"] == "PLANNED"
    assert battery["state"] == "READY"
