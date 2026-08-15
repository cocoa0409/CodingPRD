"""Entity creation defaults, computed fields, not-found, uniqueness, derived
counters, pagination envelope, and immediate read-after-write consistency."""
from test_helpers import (
    validate_success, validate_error, validate_paginated,
    NON_EXISTENT_UUID, ApiErrorId,
    create_artist, create_gear_model, create_gear_unit, create_tour, add_stop,
    create_artist_payload, create_gear_model_payload, create_gear_unit_payload,
    create_tour_payload, create_tour_stop_payload,
    api_client, TEST_USERS,
)

OPS = TEST_USERS["ops_manager_headers"]
TM = TEST_USERS["tour_manager_headers"]


def test_artist_creation_defaults_and_retrieval(api, ops_manager_headers):
    """PRD §3.1: "An `OpsManager` registers an artist with a `legal_name` — the
    contracting name used on paperwork — and optionally a commercial `tier` of
    `STANDARD`, `PREMIUM`, or `PLATINUM` (defaulting to `STANDARD` when omitted)
    and a `deposit_waived` flag (defaulting to false)."
    PRD §3.1: "New artists start with a `deposit_credit_cents` balance of zero."

    Design: Corner/entities/artist_creation_defaults_and_retrieval
    """
    created = validate_success(
        api.create_artist(create_artist_payload(legal_name="Defaults Band"),
                          ops_manager_headers), 201)
    assert created["tier"] == "STANDARD"
    assert created["deposit_waived"] is False

    fetched = validate_success(api.get_artist(created["id"], ops_manager_headers))
    assert fetched["tier"] == "STANDARD"
    assert fetched["deposit_waived"] is False
    assert fetched["deposit_credit_cents"] == 0
    assert fetched["risk_score"] == 0
    assert isinstance(fetched["version"], int)


def test_gear_unit_computed_flight_case_flag(api, ops_manager_headers):
    """PRD §2.8: "A third derived flag, `flight_case_required`, is read off the
    catalog model's weight class: it is true for `HEAVY` and `OVERSIZE` models
    and false for `HAND_CARRY` and `STANDARD` ones."
    PRD §3.3: "A unit begins `AVAILABLE` with a `condition_score` of 100 and
    zero `rental_days_since_service`."

    Design: Corner/entities/gear_unit_computed_flight_case_flag
    """
    heavy = create_gear_model(sku="EN-HV-1", category="PA", daily_rate_cents=50_000,
                              replacement_value_cents=500_000, weight_class="HEAVY")
    light = create_gear_model(sku="EN-HC-1", category="GUITAR", daily_rate_cents=10_000,
                              replacement_value_cents=100_000, weight_class="HAND_CARRY")
    u_heavy = validate_success(api.create_gear_unit(
        create_gear_unit_payload(heavy["id"], serial_number="EN-U1", home_city_code="LAX"),
        ops_manager_headers), 201)
    u_light = validate_success(api.create_gear_unit(
        create_gear_unit_payload(light["id"], serial_number="EN-U2", home_city_code="LAX"),
        ops_manager_headers), 201)
    assert u_heavy["flight_case_required"] is True
    assert u_light["flight_case_required"] is False
    assert u_heavy["condition_score"] == 100
    assert u_heavy["rental_days_since_service"] == 0


def test_tour_not_found_returns_404(api, tour_manager_headers):
    """PRD §2.11: "When an endpoint path contains multiple resource identifiers,
    existence is validated left to right — a tour before its stop, a stop before
    its rider line — and the request is rejected with `ERR_NOT_FOUND` (HTTP 404)
    at the first identifier that does not resolve to an existing resource."

    Design: Corner/entities/tour_not_found_returns_404
    """
    resp = api.get_tour(NON_EXISTENT_UUID, tour_manager_headers)
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND)


def test_gear_model_sku_uniqueness(api, ops_manager_headers):
    """PRD §3.3: "An `OpsManager` registers a model with a catalog-unique `sku`
    (a collision is rejected with `ERR_DUPLICATE`, HTTP 409)".

    Design: Corner/entities/gear_model_sku_uniqueness
    """
    create_gear_model(sku="UNQ-1", category="AMP", daily_rate_cents=1000,
                      replacement_value_cents=5000, weight_class="STANDARD")
    resp = api.create_gear_model(
        create_gear_model_payload(sku="UNQ-1", category="AMP", daily_rate_cents=2000,
                                  replacement_value_cents=6000, weight_class="STANDARD"),
        ops_manager_headers)
    validate_error(resp, ApiErrorId.ERR_DUPLICATE)


def test_tour_stop_count_derived_reconciliation(api, ops_manager_headers, tour_manager_headers):
    """PRD §3.2: "Because the stop list feeds the activation gate, adding a stop
    also bumps the parent tour's `version` and reconciles `stop_count`, which the
    server keeps aligned as stops are added or removed."

    Design: Corner/entities/tour_stop_count_derived_reconciliation
    """
    artist = create_artist(legal_name="Count Act")
    tour = create_tour(artist["id"], name="Count Tour")
    add_stop(tour["id"], city_code="LAX", venue_date="2026-08-10T00:00:00Z",
             load_in_ts="2026-08-10T10:00:00Z")
    add_stop(tour["id"], city_code="NYC", venue_date="2026-08-12T00:00:00Z",
             load_in_ts="2026-08-12T10:00:00Z")
    fetched = validate_success(api.get_tour(tour["id"], tour_manager_headers))
    assert fetched["stop_count"] == 2


def test_list_pagination_envelope(api, ops_manager_headers):
    """PRD §2.3: "The `limit` parameter caps the number of items returned; when
    omitted it defaults to 10, and it accepts values from a minimum of 1 to a
    maximum of 100."
    PRD §2.3: "Paginated list responses carry the following fields in the `meta`
    object of the response envelope: `limit`, `offset`, `total_count`, and
    `has_more`."
    PRD §2.2: "The `api_request_id` is a server-generated unique identifier for
    the request that starts with `req_`."

    Design: Corner/endpoints/list_pagination_envelope
    """
    for sku in ("PG-1", "PG-2", "PG-3"):
        create_gear_model(sku=sku, category="AMP", daily_rate_cents=1000,
                          replacement_value_cents=5000, weight_class="STANDARD")

    resp = api.list_gear_models(ops_manager_headers, params={"limit": 2, "offset": 0})
    data, meta = validate_paginated(resp)
    assert len(data) == 2
    assert meta["total_count"] == 3
    assert meta["has_more"] is True
    assert meta["limit"] == 2
    assert meta["offset"] == 0
    assert resp.json()["meta"]["api_request_id"].startswith("req_")

    data2, meta2 = validate_paginated(
        api.list_gear_models(ops_manager_headers, params={"limit": 2, "offset": 2}))
    assert len(data2) == 1
    assert meta2["has_more"] is False

    _, meta_default = validate_paginated(api.list_gear_models(ops_manager_headers))
    assert meta_default["limit"] == 10


def test_immediate_read_after_write(api, ops_manager_headers):
    """PRD §2.9: "Derived fields are always reconciled eagerly, at the moment
    the underlying event occurs, never lazily at read time."
    PRD §2.8: "it is true for `HEAVY` and `OVERSIZE` models and false for
    `HAND_CARRY` and `STANDARD` ones."

    Design: Corner/consistency_model/immediate_read_after_write
    """
    model = create_gear_model(sku="IM-PA-1", category="PA", daily_rate_cents=50_000,
                              replacement_value_cents=500_000, weight_class="HEAVY")
    created = validate_success(api.create_gear_unit(
        create_gear_unit_payload(model["id"], serial_number="IM-U1", home_city_code="LAX"),
        ops_manager_headers), 201)
    assert created["flight_case_required"] is True
    assert created["status"] == "AVAILABLE"

    fetched = validate_success(api.get_gear_unit(created["id"], ops_manager_headers))
    assert fetched["flight_case_required"] is True
    assert fetched["condition_score"] == 100
    assert fetched["version"] == created["version"]
