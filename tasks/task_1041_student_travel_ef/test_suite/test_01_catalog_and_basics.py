"""Catalog creation, request validation, not-found, computed price, and listing basics.

Translates queue-B (corner) instances from the entities/endpoints/consistency sections.
"""
from test_helpers import (
    validate_success, validate_error, validate_paginated,
    ApiErrorId, OPERATOR, NON_EXISTENT_UUID,
    assert_tour,
    setup_open_departure, set_clock, make_tour, make_group_leader, make_departure,
    enroll,
    create_tour_payload, create_enrollment_payload,
)


def test_create_tour_returns_201_with_echoed_fields(api):
    """PRD §3.1: "A tour is a reusable product template carrying a marketing name,
    a destination, the number of nights on the itinerary (which must be at least 1),
    and a reference base_price_cents per traveler (which must be zero or greater)."
    PRD §4: "Operations that create a new resource return 201 Created".

    Design: Corner/entities/tour_creation_returns_201_with_fields
    """
    resp = api.create_tour(
        create_tour_payload(name="Athens Odyssey", destination="Greece", nights=6, base_price_cents=210000),
        OPERATOR,
    )
    data = validate_success(resp, expected_status=201)
    assert_tour(data)
    assert data["name"] == "Athens Odyssey"
    assert data["nights"] == 6
    assert data["base_price_cents"] == 210000


def test_enrollment_missing_traveler_gender_returns_validation(api):
    """PRD §2.9: "Request-shape problems — a missing required field, a wrong type,
    or an illegal enum value — surface as ERR_VALIDATION (400)."

    Design: Corner/entities/enrollment_missing_traveler_gender_returns_validation
    """
    ctx = setup_open_departure(api, clock="2026-08-18T00:00:00Z")
    payload = {
        "departure_id": ctx["departure"]["id"],
        "traveler_name": "No Gender",
        "traveler_dob": "2010-05-01T00:00:00Z",
    }
    resp = api.create_enrollment(payload, OPERATOR)
    validate_error(resp, ApiErrorId.ERR_VALIDATION.value, expected_status=400)


def test_get_departure_nonexistent_returns_not_found(api):
    """PRD §2.8: "The first identifier that does not resolve determines the error,
    and the specific code is the entity-appropriate not-found code: ERR_TOUR_NOT_FOUND,
    ERR_GROUP_LEADER_NOT_FOUND, ERR_DEPARTURE_NOT_FOUND, ... each carrying HTTP 404."

    Design: Corner/entities/departure_get_nonexistent_returns_not_found
    """
    resp = api.get_departure(NON_EXISTENT_UUID, OPERATOR)
    validate_error(resp, ApiErrorId.ERR_DEPARTURE_NOT_FOUND.value, expected_status=404)


def test_enrollment_price_locked_is_computed_input_ignored(api):
    """PRD §3.3: "At creation the system computes and stores price_locked_cents; any
    price supplied by the client is ignored."
    PRD §3.3: "An early-bird discount applies only when the logical clock is at or
    before the departure's early_bird_cutoff: in that case the discount is ten percent
    of the gross, rounded half-up to the nearest cent; otherwise the discount is zero."

    Design: Corner/entities/enrollment_price_locked_is_computed_input_ignored
    """
    ctx = setup_open_departure(api, clock="2026-08-18T00:00:00Z", price_per_traveler_cents=250000)
    # clock 2026-08-18 is AFTER early_bird_cutoff 2026-08-01 -> no discount; plain enrollment.
    resp = api.create_enrollment(create_enrollment_payload(ctx["departure"]["id"], traveler_name="Plain P"), OPERATOR)
    data = validate_success(resp, expected_status=201)
    assert data["price_locked_cents"] == 250000


def test_enrollment_create_response_carries_price_immediately(api):
    """PRD §2.7: "Consistency is immediate: by the time a mutating request returns,
    every derived figure it affects already reflects the change."
    PRD §3.3: "the discount is ten percent of the gross, rounded half-up to the nearest cent".

    Design: Corner/consistency_model/immediate_price_visible_in_enrollment_create_response
    """
    ctx = setup_open_departure(api, clock="2026-07-15T00:00:00Z", price_per_traveler_cents=250000)
    # clock 2026-07-15 is on/before early_bird_cutoff 2026-08-01 -> 10% discount = 25000.
    resp = api.create_enrollment(create_enrollment_payload(ctx["departure"]["id"], traveler_name="Imm I"), OPERATOR)
    created = validate_success(resp, expected_status=201)
    assert created["price_locked_cents"] == 225000, "create response must already carry computed price"
    fetched = validate_success(api.get_enrollment(created["id"], OPERATOR))
    assert fetched["price_locked_cents"] == 225000, "GET must equal the create-response value"


def test_departures_list_returns_pagination_envelope_filtered_by_tour(api):
    """PRD §2.3: "Every list response includes limit, offset, total_count, and has_more
    in the meta object of the envelope."
    PRD §4: "GET | /departures | List departures, optionally filtered by tour or leader".

    Design: Corner/endpoints/departures_list_returns_pagination_envelope
    """
    set_clock(api, "2026-07-15T00:00:00Z")
    tour = make_tour(api)
    gl = make_group_leader(api)
    make_departure(api, tour["id"], gl["id"], depart_date="2026-11-01T00:00:00Z", return_date="2026-11-08T00:00:00Z")
    make_departure(api, tour["id"], gl["id"], depart_date="2026-12-01T00:00:00Z", return_date="2026-12-08T00:00:00Z",
                   enrollment_deadline="2026-10-01T00:00:00Z", early_bird_cutoff="2026-09-01T00:00:00Z")
    resp = api.list_departures(OPERATOR, params={"tour_id": tour["id"], "limit": 10, "offset": 0})
    data, meta = validate_paginated(resp)
    assert len(data) == 2, f"expected 2 departures under the tour, got {len(data)}"
    assert meta["total_count"] == 2
    assert meta["has_more"] is False


def test_enrollment_reverse_reachable_via_departure_subresource(api):
    """PRD §3.3: "Enrolling a traveler onto a departure records departure_id,
    traveler_name, traveler_dob (the date of birth at UTC midnight, used later for
    rooming), and traveler_gender, which is one of MALE, FEMALE, or NONBINARY."
    PRD §4: "GET | /departures/{id}/enrollments | List enrollments on a departure".

    Design: Corner/endpoints/enrollment_reverse_reachable_via_departure_subresource
    """
    ctx = setup_open_departure(api, clock="2026-08-18T00:00:00Z")
    enr = enroll(api, ctx["departure"]["id"], traveler_name="Rev R")
    resp = api.list_departure_enrollments(ctx["departure"]["id"], OPERATOR, params={"limit": 10, "offset": 0})
    data, _meta = validate_paginated(resp)
    matches = [e for e in data if e["id"] == enr["id"]]
    assert matches, f"enrollment {enr['id']} not reverse-reachable via its departure"
    assert matches[0]["departure_id"] == ctx["departure"]["id"]
