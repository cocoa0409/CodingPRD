"""Validation-gate violations and RBAC denials, each in an isolated scenario
where exactly one gate can fail."""
from test_helpers import (
    validate_success, validate_error, ApiErrorId,
    create_artist, create_gear_model, create_gear_unit, create_tour, add_stop,
    add_rider_line, source_line, create_approved_vendor, activate_tour,
    create_artist_payload, create_tour_payload, create_source_payload,
    create_shipment_payload, create_shipment_line_payload,
    api_client, TEST_USERS, make_vendor_rep_headers, build_user_headers,
)

OPS = TEST_USERS["ops_manager_headers"]
TM = TEST_USERS["tour_manager_headers"]
LC = TEST_USERS["logistics_headers"]
WT = TEST_USERS["warehouse_tech_headers"]


def test_unauthenticated_request_rejected(api):
    """PRD §2.1: "A request with missing or malformed headers, or whose role
    value is not one of the declared roles, is rejected with
    `ERR_UNAUTHENTICATED` (HTTP 401)."

    Design: Corner/validations/unauthenticated_request_rejected
    """
    resp = api._request("GET", "/backline/tours", headers={})
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED)


def test_warehouse_tech_cannot_create_tour(api, warehouse_tech_headers):
    """PRD §2.1: "A well-formed request whose role is not permitted to perform
    the target operation is rejected with `ERR_UNAUTHORIZED` (HTTP 403)."
    PRD §3.2: "A `TourManager` opens a tour by naming the headlining artist via
    `artist_id`, giving the tour a display `name`, and bounding it with a
    `start_date` and an `end_date` that must fall on or after the start."
    — tour creation belongs to the TourManager; WarehouseTech is not permitted.

    Design: Corner/roles/warehouse_tech_cannot_create_tour
    """
    artist = create_artist(legal_name="RBAC Act")
    resp = api.create_tour(create_tour_payload(artist["id"], name="Nope"),
                           warehouse_tech_headers)
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED)


def test_vendor_rep_scoped_to_own_vendor(api):
    """PRD §3.8: "Negotiation belongs to the vendor's representative, and
    ownership is enforced through the identity rule of §2.1: only a
    `PartnerVendorRep` whose `X-User-ID` matches the request's
    `partner_vendor_id` may act, with a rep of a different vendor rejected as
    `ERR_VENDOR_NOT_ELIGIBLE`".

    Design: Corner/roles/vendor_rep_scoped_to_own_vendor
    """
    artist = create_artist(legal_name="Scope Act", tier="PLATINUM", deposit_waived=True)
    model = create_gear_model(sku="SC-PA-1", category="PA", daily_rate_cents=80_000,
                              replacement_value_cents=600_000, weight_class="HEAVY")
    vendor_a = create_approved_vendor(name="VendorA", city_codes=["LAX"], commission_bps=1000)
    vendor_b = create_approved_vendor(name="VendorB", city_codes=["LAX"], commission_bps=1000)
    tour = create_tour(artist["id"], name="Scope Tour")
    stop = add_stop(tour["id"], city_code="LAX", venue_date="2026-08-12T00:00:00Z",
                    load_in_ts="2026-08-12T10:00:00Z")
    line = add_rider_line(stop["id"], model["id"])
    reservation = validate_success(api.source_rider_line(
        line["id"],
        create_source_payload(origin_city_code="LAX", dest_city_code="LAX",
                              start_date="2026-08-11T00:00:00Z", end_date="2026-08-13T00:00:00Z",
                              use_cross_rental=True, partner_vendor_id=vendor_b["id"],
                              vendor_rate_cents_per_day=70_000),
        LC))
    from test_helpers import find_cross_request_for_reservation
    crr = find_cross_request_for_reservation(reservation["id"])

    resp = api.accept_cross_rental_request(crr["id"], make_vendor_rep_headers(vendor_a["id"]))
    validate_error(resp, ApiErrorId.ERR_VENDOR_NOT_ELIGIBLE)


def test_missing_required_field_rejected(api, tour_manager_headers):
    """PRD §2.11: "16. Request shape — missing required fields, wrongly typed
    values, enum values outside their declared sets, quantities below one, or
    unparseable dates fail with `ERR_INVALID_REQUEST` (HTTP 400)."

    Design: Corner/validations/missing_required_field_rejected
    """
    resp = api.create_tour({"name": "No Artist", "start_date": "2026-08-01T00:00:00Z",
                            "end_date": "2026-08-31T00:00:00Z"}, tour_manager_headers)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


def test_invalid_window_stop_outside_tour(api, tour_manager_headers):
    """PRD §3.2: "The venue date must lie within the tour's start and end dates
    inclusive, and the load-in must fall strictly before the 20:00 cutoff on the
    venue date; violating either constraint is rejected with `ERR_INVALID_WINDOW`
    (HTTP 422)."

    Design: Corner/validations/invalid_window_stop_outside_tour
    """
    artist = create_artist(legal_name="Window Act")
    tour = create_tour(artist["id"], name="Window Tour")
    resp = api.create_tour_stop(tour["id"], {
        "city_code": "LAX", "venue_date": "2026-09-05T00:00:00Z",
        "load_in_ts": "2026-09-05T10:00:00Z"}, tour_manager_headers)
    validate_error(resp, ApiErrorId.ERR_INVALID_WINDOW)


def test_substitution_model_not_in_list(api):
    """PRD §3.4: "the substitute must appear in the originally requested model's
    `substitute_model_ids`, with an unlisted model surfacing as
    `ERR_SUBSTITUTION_NOT_ALLOWED` (HTTP 422)."

    Design: Corner/validations/substitution_model_not_in_list
    """
    artist = create_artist(legal_name="Sub Act", tier="PLATINUM", deposit_waived=True)
    model_a = create_gear_model(sku="SB-GTR-A", category="GUITAR", daily_rate_cents=10_000,
                                replacement_value_cents=100_000, weight_class="HAND_CARRY")
    model_b = create_gear_model(sku="SB-GTR-B", category="GUITAR", daily_rate_cents=9000,
                                replacement_value_cents=90_000, weight_class="HAND_CARRY")
    create_gear_unit(model_a["id"], serial_number="SB-U1", home_city_code="LAX")
    # A substitute-model unit exists so availability passes and the allowlist
    # gate is the one that fires.
    create_gear_unit(model_b["id"], serial_number="SB-U2", home_city_code="LAX")
    tour = create_tour(artist["id"], name="Sub Tour")
    stop = add_stop(tour["id"], city_code="LAX", venue_date="2026-08-10T00:00:00Z",
                    load_in_ts="2026-08-10T10:00:00Z")
    line = add_rider_line(stop["id"], model_a["id"])
    source_line(line["id"], origin_city_code="LAX", dest_city_code="LAX",
                start_date="2026-08-09T00:00:00Z", end_date="2026-08-11T00:00:00Z")

    resp = api.propose_substitution(
        line["id"], {"substitute_gear_model_id": model_b["id"],
                     "substitution_reason": "not in list"}, LC)
    validate_error(resp, ApiErrorId.ERR_SUBSTITUTION_NOT_ALLOWED)


def test_cross_rental_vendor_not_eligible(api):
    """PRD §3.8: "Either way, the vendor must be `APPROVED` and its `city_codes`
    must cover the stop's city, or the request fails with
    `ERR_VENDOR_NOT_ELIGIBLE` (HTTP 422)."

    Design: Corner/validations/cross_rental_vendor_not_eligible
    """
    artist = create_artist(legal_name="Ven Act", tier="PLATINUM", deposit_waived=True)
    model = create_gear_model(sku="VE-PA-1", category="PA", daily_rate_cents=80_000,
                              replacement_value_cents=600_000, weight_class="HEAVY")
    pending = validate_success(api.create_partner_vendor(
        {"name": "Pending Co", "city_codes": ["LAX"], "commission_bps": 1000}, OPS), 201)
    tour = create_tour(artist["id"], name="Ven Tour")
    stop = add_stop(tour["id"], city_code="LAX", venue_date="2026-08-12T00:00:00Z",
                    load_in_ts="2026-08-12T10:00:00Z")
    line = add_rider_line(stop["id"], model["id"])

    resp = api.source_rider_line(
        line["id"],
        create_source_payload(origin_city_code="LAX", dest_city_code="LAX",
                              start_date="2026-08-11T00:00:00Z", end_date="2026-08-13T00:00:00Z",
                              use_cross_rental=True, partner_vendor_id=pending["id"],
                              vendor_rate_cents_per_day=70_000),
        LC)
    validate_error(resp, ApiErrorId.ERR_VENDOR_NOT_ELIGIBLE)


def test_insurance_required_at_activation(api, tour_manager_headers):
    """PRD §3.2: "and then the insurance requirement, which demands a non-null
    `insurance_policy_id` whenever the artist's `deposit_waived` is false,
    failing with `ERR_INSURANCE_REQUIRED` (HTTP 422)."

    Design: Corner/validations/insurance_required_at_activation
    """
    artist = create_artist(legal_name="Ins Act", tier="STANDARD")
    tour = create_tour(artist["id"], name="Ins Tour")
    add_stop(tour["id"], city_code="LAX", venue_date="2026-08-10T00:00:00Z",
             load_in_ts="2026-08-10T10:00:00Z")
    fresh = validate_success(api.get_tour(tour["id"], tour_manager_headers))
    resp = api.activate_tour(tour["id"], {"expected_tour_version": fresh["version"]},
                             tour_manager_headers)
    validate_error(resp, ApiErrorId.ERR_INSURANCE_REQUIRED)


def test_err_deposit_insufficient_trigger(api):
    """PRD §2.7: "The ledger is never allowed to dip below zero: if an artist's
    balance — after accounting for the deposits currently held across that
    artist's reservations — cannot cover a new hold, the operation that would
    create the hold is rejected with `ERR_DEPOSIT_INSUFFICIENT` (HTTP 402)."

    Design: Corner/errors/err_deposit_insufficient_trigger
    """
    artist = create_artist(legal_name="Broke Act", tier="STANDARD")
    model = create_gear_model(sku="BR-AMP-1", category="AMP", daily_rate_cents=10_000,
                              replacement_value_cents=300_000, weight_class="HAND_CARRY")
    create_gear_unit(model["id"], serial_number="BR-U1", home_city_code="LAX")
    tour = create_tour(artist["id"], name="Broke Tour", insurance_policy_id="POL-B")
    stop = add_stop(tour["id"], city_code="LAX", venue_date="2026-08-10T00:00:00Z",
                    load_in_ts="2026-08-10T10:00:00Z")
    line = add_rider_line(stop["id"], model["id"])

    resp = api.source_rider_line(line["id"], create_source_payload(
        origin_city_code="LAX", dest_city_code="LAX",
        start_date="2026-08-09T00:00:00Z", end_date="2026-08-11T00:00:00Z"), LC)
    validate_error(resp, ApiErrorId.ERR_DEPOSIT_INSUFFICIENT)


def test_flight_case_required_enforcement(api):
    """PRD §3.5: "a unit whose `flight_case_required` is true must name an
    `AVAILABLE` case whose `size_class` is adequate for the unit's weight class,
    failing with `ERR_FLIGHT_CASE_REQUIRED` (HTTP 422)."
    PRD §3.5: "Two constraints are enforced both at booking and again at
    loading, in the §2.11 order".

    Design: Corner/validations/flight_case_required_enforcement
    """
    artist = create_artist(legal_name="Case Act")
    model = create_gear_model(sku="FC-PA-1", category="PA", daily_rate_cents=50_000,
                              replacement_value_cents=500_000, weight_class="HEAVY")
    unit = create_gear_unit(model["id"], serial_number="FC-U1", home_city_code="LAX")
    tour = create_tour(artist["id"], name="Case Tour")
    shipment = validate_success(api.create_shipment(
        create_shipment_payload(tour["id"], from_city_code="LAX", to_city_code="NYC",
                                ship_date="2026-08-09T00:00:00Z", capacity_kg=500), LC), 201)

    # Booking the HEAVY unit without a case is already rejected (the constraint
    # is enforced at booking and again at loading).
    resp = api.create_shipment_line(
        shipment["id"], create_shipment_line_payload(unit["id"], weight_kg=100,
                                                     labor_minutes=30), LC)
    validate_error(resp, ApiErrorId.ERR_FLIGHT_CASE_REQUIRED)


def test_shipment_line_capacity_enforced(api):
    """PRD §3.5: "capacity first — the leg's booked weight may reach but never
    exceed `capacity_kg`, and a line that would push it over is rejected with
    `ERR_CAPACITY_EXCEEDED` (HTTP 422)".
    PRD §3.5: "Two constraints are enforced both at booking and again at
    loading, in the §2.11 order".

    Design: Corner/state_machines/shipment_line_capacity_enforced_at_load
    """
    artist = create_artist(legal_name="Cap Act")
    model = create_gear_model(sku="CP-AMP-1", category="AMP", daily_rate_cents=10_000,
                              replacement_value_cents=100_000, weight_class="STANDARD")
    u1 = create_gear_unit(model["id"], serial_number="CP-U1", home_city_code="LAX")
    u2 = create_gear_unit(model["id"], serial_number="CP-U2", home_city_code="LAX")
    u3 = create_gear_unit(model["id"], serial_number="CP-U3", home_city_code="LAX")
    tour = create_tour(artist["id"], name="Cap Tour")
    shipment = validate_success(api.create_shipment(
        create_shipment_payload(tour["id"], from_city_code="LAX", to_city_code="NYC",
                                ship_date="2026-08-09T00:00:00Z", capacity_kg=50), LC), 201)

    validate_success(api.create_shipment_line(
        shipment["id"], create_shipment_line_payload(u1["id"], weight_kg=40,
                                                     labor_minutes=10), LC), 201)
    # 40 + 11 would exceed the 50kg capacity.
    over = api.create_shipment_line(
        shipment["id"], create_shipment_line_payload(u2["id"], weight_kg=11,
                                                     labor_minutes=10), LC)
    validate_error(over, ApiErrorId.ERR_CAPACITY_EXCEEDED)
    # 40 + 10 reaches exactly the capacity and is permitted.
    exact = validate_success(api.create_shipment_line(
        shipment["id"], create_shipment_line_payload(u3["id"], weight_kg=10,
                                                     labor_minutes=10), LC), 201)
    fetched = validate_success(api.get_shipment(shipment["id"], LC))
    assert fetched["booked_weight_kg"] == 50
