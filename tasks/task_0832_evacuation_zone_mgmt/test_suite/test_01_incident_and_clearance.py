"""Incident lifecycle, clearance-estimate rounding, and the all-clear cascade."""
import math

from test_helpers import (
    validate_success, validate_error, is_valid_uuid,
    ApiErrorId, assert_incident,
    create_incident, create_active_incident, set_incident_phase, set_clock,
    create_zone, order_zone, create_route, set_route_status, create_registrant,
    create_credential, TEST_USERS,
)

COMMANDER = TEST_USERS["commander_headers"]
TRAFFIC = TEST_USERS["traffic_headers"]
REGISTRAR = TEST_USERS["registrar_headers"]


def test_incident_create_returns_201_with_defaults(api):
    """PRD 3.1: "A new incident begins in `status` `DRAFT` with `activated_at`, `all_clear_at`, and `clearance_estimate_minutes` unpopulated, and `ipaws_slots_reserved` at zero."
    PRD 3.1: "The commander may also set the `ipaws_daily_slot_budget`; when omitted it defaults to 5."
    PRD 2.4: "The `version` begins at 1 when the resource is created and increments by exactly 1 on every mutation of that resource"

    Design: Corner/entities/incident_create_returns_201_with_defaults
    """
    resp = api.create_incident(
        {"name": "Ridge Fire", "jurisdiction": "Butte", "hazard_type": "WILDFIRE"},
        COMMANDER,
    )
    data = validate_success(resp, 201)
    assert_incident(data)
    assert data["status"] == "DRAFT"
    assert data["ipaws_daily_slot_budget"] == 5
    assert data["ipaws_slots_reserved"] == 0
    assert data["version"] == 1
    assert is_valid_uuid(data["id"]) and "_" not in data["id"], \
        "id must be a bare UUID with no type prefix"


def test_clearance_estimate_per_zone_ceil_then_sum(api):
    """PRD 3.1: "For each zone of the incident whose `order_level` is `VOLUNTARY` or `MANDATORY`, the system computes that zone's vehicle count as its `population_at_risk` divided by an average vehicle occupancy of 2.5 people per vehicle, rounded up to a whole number of vehicles, and accumulates these per-zone vehicle counts into a total."
    PRD 3.1: "Otherwise it is the total vehicles divided by the total throughput, multiplied by 60, and rounded up to a whole number of minutes."

    Design: Difficulty/combinatorial_formula/clearance_time_round_per_zone_then_sum
    """
    inc = create_active_incident(name="Coast Tsunami", jurisdiction="Del Norte", hazard_type="TSUNAMI")
    set_clock("2026-03-01T12:00:00Z")
    z_a = create_zone(inc["id"], name="Zone-A", residential_population=901,
                      transient_population=0, daytime_occupancy_factor=1.0)
    order_zone(z_a["id"], "MANDATORY")
    z_b = create_zone(inc["id"], name="Zone-B",
                      geofence_wkt="POLYGON((2 2,2 3,3 3,3 2,2 2))",
                      residential_population=901, transient_population=0, daytime_occupancy_factor=1.0)
    order_zone(z_b["id"], "MANDATORY")
    route = create_route(inc["id"], throughput_vph=60)
    set_route_status(route["id"], "OPEN")

    data = validate_success(api.get_incident(inc["id"], COMMANDER))
    # ceil(901/2.5)=361 per zone -> 722 vehicles; ceil((722/60)*60)=722
    assert data["clearance_estimate_minutes"] == 722


def test_clearance_estimate_rejects_sum_then_divide_order(api):
    """PRD 3.1: "The per-zone round-up-then-sum order is deliberate; summing populations first and dividing once would yield a different number and is explicitly not the rule."

    Design: Difficulty/combinatorial_formula/clearance_time_round_per_zone_then_sum
    """
    inc = create_active_incident(name="Coast Tsunami", jurisdiction="Del Norte", hazard_type="TSUNAMI")
    set_clock("2026-03-01T12:00:00Z")
    z_a = create_zone(inc["id"], name="Zone-A", residential_population=901,
                      transient_population=0, daytime_occupancy_factor=1.0)
    order_zone(z_a["id"], "MANDATORY")
    z_b = create_zone(inc["id"], name="Zone-B",
                      geofence_wkt="POLYGON((2 2,2 3,3 3,3 2,2 2))",
                      residential_population=901, transient_population=0, daytime_occupancy_factor=1.0)
    order_zone(z_b["id"], "MANDATORY")
    route = create_route(inc["id"], throughput_vph=60)
    set_route_status(route["id"], "OPEN")

    data = validate_success(api.get_incident(inc["id"], COMMANDER))
    disallowed = math.ceil(((math.ceil((901 + 901) / 2.5)) / 60) * 60)  # sum-then-divide == 721
    assert disallowed == 721
    assert data["clearance_estimate_minutes"] == 722
    assert data["clearance_estimate_minutes"] != 721


def test_all_clear_moves_voluntary_zone_to_reentry(api):
    """PRD 3.1: "first, every zone of the incident currently at `VOLUNTARY` is moved to `RE_ENTRY_ALLOWED` (each such zone's `version` increments); zones at `NONE` are left untouched, and no `MANDATORY` zone can be present because all-clear is blocked otherwise."

    Design: Difficulty/transitive_cascade/all_clear_cascade_incident_zone_credential
    """
    inc = create_active_incident(name="Delta Flood", jurisdiction="Sacramento", hazard_type="FLOOD")
    zone = create_zone(inc["id"])
    order_zone(zone["id"], "VOLUNTARY")
    reg = create_registrant(zone["id"], party_size=2)
    create_credential(zone["id"], reg["id"])

    set_incident_phase(inc["id"], "ALL_CLEAR")

    zone_after = validate_success(api.get_zone(zone["id"], COMMANDER))
    assert zone_after["order_level"] == "RE_ENTRY_ALLOWED"


def test_all_clear_activates_issued_credential(api):
    """PRD 3.1: "Second, for each zone that just became `RE_ENTRY_ALLOWED`, every credential on that zone in status `ISSUED` whose validity window contains the current clock — that is, `valid_from_utc` at or before now and now strictly before `valid_until_utc` — is moved to `ACTIVE`."

    Design: Difficulty/transitive_cascade/all_clear_cascade_incident_zone_credential
    """
    inc = create_active_incident(name="Delta Flood", jurisdiction="Sacramento", hazard_type="FLOOD")
    zone = create_zone(inc["id"])
    order_zone(zone["id"], "VOLUNTARY")
    reg = create_registrant(zone["id"], party_size=2)
    cred = create_credential(zone["id"], reg["id"],
                             valid_from_utc="2026-02-01T00:00:00Z",
                             valid_until_utc="2026-12-01T00:00:00Z")
    assert cred["status"] == "ISSUED"

    set_incident_phase(inc["id"], "ALL_CLEAR")

    cred_after = validate_success(api.get_access_credential(cred["id"], COMMANDER))
    assert cred_after["status"] == "ACTIVE"


def test_all_clear_blocked_by_mandatory_zone(api):
    """PRD 3.1: "Moving from `ACTIVE` to `ALL_CLEAR` stamps `all_clear_at` and is blocked while any zone belonging to the incident is still at `order_level` `MANDATORY` — such an attempt is rejected with `ERR_ALL_CLEAR_BLOCKED`."

    Design: Corner/validations/all_clear_blocked_by_mandatory_zone
    """
    inc = create_active_incident()
    zone = create_zone(inc["id"])
    order_zone(zone["id"], "MANDATORY")

    resp = api.set_incident_phase(inc["id"], {"to_phase": "ALL_CLEAR"}, COMMANDER)
    validate_error(resp, ApiErrorId.ERR_ALL_CLEAR_BLOCKED)


def test_route_open_requires_incident_active(api):
    """PRD 3.5: "Opening a route `PLANNED → OPEN` requires the owning incident to be `ACTIVE`, otherwise it is rejected with `ERR_INCIDENT_NOT_ACTIVE`."

    Design: Corner/validations/route_open_requires_incident_active
    """
    inc = create_incident(name="Coast Tsunami", jurisdiction="Del Norte", hazard_type="TSUNAMI")
    route = create_route(inc["id"])

    resp = api.set_route_status(route["id"], {"state": "OPEN"}, TRAFFIC)
    validate_error(resp, ApiErrorId.ERR_INCIDENT_NOT_ACTIVE)
