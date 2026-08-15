"""State-machine legality, terminal lockdown, OCC stale-version guards,
cascades, and the computed availability read."""
from test_helpers import (
    validate_success, validate_error, ApiErrorId,
    create_artist, create_gear_model, create_gear_unit, create_tour, add_stop,
    add_rider_line, source_line, get_tour, get_stop, get_unit, get_reservation,
    get_line, settle_reservation,
    setup_tour_with_sourced_line, setup_complete_blocked_scene,
    setup_inspected_reservation_scene,
    create_rider_line_payload, create_source_payload,
    api_client, TEST_USERS,
)

OPS = TEST_USERS["ops_manager_headers"]
TM = TEST_USERS["tour_manager_headers"]
LC = TEST_USERS["logistics_headers"]
WT = TEST_USERS["warehouse_tech_headers"]


def test_stale_version_occ_on_tour_activate(api, tour_manager_headers):
    """PRD §2.10: "Activating a tour requires `expected_tour_version` matching
    the tour's current `version`." and "each rejects a mismatched value with
    `ERR_STALE_VERSION` (HTTP 412)."
    PRD §3.2: "adding a stop also bumps the parent tour's `version`".

    Design: Corner/validations/stale_version_occ_on_tour_activate
    """
    artist = create_artist(legal_name="Occ Act", tier="STANDARD")
    tour = create_tour(artist["id"], name="Occ Tour", insurance_policy_id="POL-OCC")
    stale_version = get_tour(tour["id"])["version"]
    add_stop(tour["id"], city_code="LAX", venue_date="2026-08-10T00:00:00Z",
             load_in_ts="2026-08-10T10:00:00Z")

    stale = api.activate_tour(tour["id"], {"expected_tour_version": stale_version},
                              tour_manager_headers)
    validate_error(stale, ApiErrorId.ERR_STALE_VERSION)

    fresh_version = get_tour(tour["id"])["version"]
    activated = validate_success(api.activate_tour(
        tour["id"], {"expected_tour_version": fresh_version}, tour_manager_headers))
    assert activated["status"] == "ACTIVE"


def test_stale_version_occ_on_reservation_settle(api, tour_manager_headers):
    """PRD §2.10: "Settling a reservation requires `expected_reservation_version`
    matching the reservation's current `version`. The version advances when a
    damage claim is filed against the reservation or when check-in adjusts the
    unit, so a stale settle would compute the final fee against an obsolete
    inspection basis."
    PRD §2.10: "each rejects a mismatched value with `ERR_STALE_VERSION` (HTTP
    412)."

    Design: Corner/cross_cutting_layers/stale_version_occ_on_reservation_settle
    """
    ctx = setup_inspected_reservation_scene()
    rid = ctx["reservation"]["id"]

    stale = api.settle_reservation(rid, {"expected_reservation_version": ctx["stale_version"]},
                                   tour_manager_headers)
    validate_error(stale, ApiErrorId.ERR_STALE_VERSION)

    settled = settle_reservation(rid)
    assert settled["status"] == "SETTLED"


def test_rider_line_invalid_transition_requested_to_fulfilled(api, warehouse_tech_headers):
    """PRD §3.4: "Once gear is physically on site, a `WarehouseTech` marks the
    line fulfilled: from either `SOURCED` or `APPROVED`, provided the linked
    reservation has reached `DELIVERED`, the line moves to `FULFILLED`."
    PRD §2.11: "4. State legality — a target whose current state does not permit
    the requested transition fails with `ERR_INVALID_STATE` (HTTP 409)."

    Design: Corner/state_machines/rider_line_invalid_transition_requested_to_fulfilled
    """
    artist = create_artist(legal_name="IT Act")
    model = create_gear_model(sku="IT-BASS-1", category="BASS", daily_rate_cents=10_000,
                              replacement_value_cents=100_000, weight_class="HAND_CARRY")
    tour = create_tour(artist["id"], name="IT Tour")
    stop = add_stop(tour["id"], city_code="LAX", venue_date="2026-08-10T00:00:00Z",
                    load_in_ts="2026-08-10T10:00:00Z")
    line = add_rider_line(stop["id"], model["id"])

    resp = api.mark_rider_line_fulfilled(line["id"], warehouse_tech_headers)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


def test_tour_complete_blocked_by_open_claim(api, tour_manager_headers):
    """PRD §3.9: "Every stop must be `SETTLED` or `CANCELLED`, every reservation
    must be `SETTLED` or `CANCELLED`, and no damage claim attached to the tour's
    reservation lines may remain in `FILED`, `ASSESSED`, or `DISPUTED`."
    PRD §2.11: "4. State legality — a target whose current state does not permit
    the requested transition fails with `ERR_INVALID_STATE` (HTTP 409)."

    Design: Corner/state_machines/tour_complete_blocked_by_open_claim
    """
    ctx = setup_complete_blocked_scene()
    resp = api.complete_tour(ctx["tour"]["id"], tour_manager_headers)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


def test_terminal_state_lockdown_retired_unit(api):
    """PRD §3.6: "Retirement is the fleet's exit door: an `OpsManager` retires a
    unit from `AVAILABLE` to `RETIRED`".
    PRD §3.3: "a candidate must belong to the requested model, currently sit in
    `AVAILABLE`, carry a `condition_score` of at least 40 and a
    `rental_days_since_service` below 30".
    PRD §2.11: "8. Availability — a window overlap or transit-buffer collision
    with no eligible vendor fallback fails with `ERR_GEAR_UNAVAILABLE` (HTTP
    409)."

    Design: Corner/state_machines/terminal_state_lockdown_retired_unit
    """
    model = create_gear_model(sku="TL-GTR-1", category="GUITAR", daily_rate_cents=10_000,
                              replacement_value_cents=100_000, weight_class="HAND_CARRY")
    unit = create_gear_unit(model["id"], serial_number="TL-U1", home_city_code="LAX")
    retired = validate_success(api.retire_gear_unit(unit["id"], OPS))
    assert retired["status"] == "RETIRED"

    artist = create_artist(legal_name="Terminal Act", tier="PLATINUM", deposit_waived=True)
    tour = create_tour(artist["id"], name="Terminal Tour")
    stop = add_stop(tour["id"], city_code="LAX", venue_date="2026-08-10T00:00:00Z",
                    load_in_ts="2026-08-10T10:00:00Z")
    line = add_rider_line(stop["id"], model["id"])
    resp = api.source_rider_line(line["id"], create_source_payload(
        origin_city_code="LAX", dest_city_code="LAX",
        start_date="2026-08-09T00:00:00Z", end_date="2026-08-11T00:00:00Z"), LC)
    validate_error(resp, ApiErrorId.ERR_GEAR_UNAVAILABLE)


def test_cascade_tour_cancel_releases_units(api, tour_manager_headers):
    """PRD §2.9: "Cancelling a tour reaches down through its stops, their rider
    lines, and the reservations sourced for those lines, releasing any physical
    units the cascade unties."
    PRD §3.9: "From `DRAFT`, a `TourManager` cancels: every `PLANNED` stop moves
    to `CANCELLED`, every rider line of those stops in `REQUESTED`, `SOURCED`,
    `SUBSTITUTION_PENDING`, or `APPROVED` moves to `CANCELLED`, and every
    reservation still in `DRAFT` moves to `CANCELLED`."

    Design: Corner/cross_cutting_layers/cascade_tour_cancel_releases_units
    """
    ctx = setup_tour_with_sourced_line(
        city="LAX", activate=False, insurance_policy_id=None,
        artist_overrides={"legal_name": "CX Act", "tier": "PLATINUM", "deposit_waived": True},
        model_overrides={"sku": "CX-AMP-1", "daily_rate_cents": 10_000,
                         "replacement_value_cents": 100_000})

    cancelled = validate_success(api.cancel_tour(ctx["tour"]["id"], tour_manager_headers))
    assert cancelled["status"] == "CANCELLED"
    assert get_stop(ctx["stop"]["id"])["status"] == "CANCELLED"
    assert get_line(ctx["line"]["id"])["status"] == "CANCELLED"
    assert get_reservation(ctx["reservation"]["id"])["status"] == "CANCELLED"
    unit = get_unit(ctx["unit"]["id"])
    assert unit["status"] == "AVAILABLE"
    assert unit["active_reservation_id"] is None


def test_gear_unit_availability_computed_read(api, logistics_headers):
    """PRD §3.3: "a computed availability read answers, for a queried
    `start_date` and `end_date`, whether the unit is free — an `available` flag
    plus the `conflicting_reservation_ids` that stand in the way."
    PRD §2.5: "All rental-window arithmetic treats a window as a half-open
    interval: the start date is included, the end date is excluded, and two
    windows that merely touch — one ending exactly when the other begins — do
    not overlap."

    Design: Corner/endpoints/gear_unit_availability_computed_read
    """
    ctx = setup_tour_with_sourced_line(
        city="LAX", activate=False, insurance_policy_id=None,
        start_date="2026-08-10T00:00:00Z", end_date="2026-08-15T00:00:00Z",
        venue_date="2026-08-12T00:00:00Z",
        artist_overrides={"legal_name": "Avail Act", "tier": "PLATINUM", "deposit_waived": True},
        model_overrides={"sku": "AV-GTR-1", "category": "GUITAR", "daily_rate_cents": 10_000,
                         "replacement_value_cents": 100_000})
    unit_id = ctx["unit"]["id"]
    rid = ctx["reservation"]["id"]

    overlap = validate_success(api.get_gear_unit_availability(
        unit_id, logistics_headers,
        params={"start_date": "2026-08-14T00:00:00Z", "end_date": "2026-08-20T00:00:00Z"}))
    assert overlap["available"] is False
    assert rid in overlap["conflicting_reservation_ids"]

    adjacent = validate_success(api.get_gear_unit_availability(
        unit_id, logistics_headers,
        params={"start_date": "2026-08-15T00:00:00Z", "end_date": "2026-08-20T00:00:00Z"}))
    assert adjacent["available"] is True
    assert adjacent["conflicting_reservation_ids"] == []
