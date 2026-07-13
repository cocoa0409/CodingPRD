"""Validation-priority conflicts, temporal overlap, cross-entity state gates.

Difficulty rules priority_pair_validation_conflict, resource_temporal_overlap,
cross_entity_state_dependency, and the zero-night date boundary. Each priority
test relies on PRD §2.9's explicit statement that "A check earlier in this list
always masks a later one."
"""
from test_helpers import (
    validate_success, validate_error, get_success_data, ApiErrorId,
    make_host_headers, make_guest_headers, make_admin_headers,
    register_host, register_verified_guest, register_unverified_guest,
    create_plan, create_vehicle, create_listed_vehicle, current_vehicle_version,
    add_active_pricing_rule, book_trip,
    create_trip_payload, create_claim_payload, create_pricing_rule_payload,
    setup_confirmed_trip, setup_checked_out_trip, file_claim,
)

ADMIN = make_admin_headers()


def _listed_scenario(api, guest_verified=True, base_price=10000):
    host = register_host(api)
    guest = (register_verified_guest(api) if guest_verified
             else register_unverified_guest(api))
    plan = create_plan(api)
    vehicle = create_listed_vehicle(api, host["id"], base_daily_price_cents=base_price)
    return {"host": host, "guest": guest, "plan": plan, "vehicle": vehicle}


# ------------------- Difficulty: state (6) masks temporal (8) on booking
def test_booking_state_beats_temporal_conflict(api):
    """PRD §2.9: "A check earlier in this list always masks a later one"
    PRD §3.3: "Only a guest whose `verification_status` is `VERIFIED` may book;
    a booking attempt by any other status fails with `ERR_GUEST_NOT_VERIFIED`."

    Design: Difficulty/priority_pair_validation_conflict/booking_state_beats_temporal
    """
    host = register_host(api)
    guest1 = register_verified_guest(api, license_number="DL-9a", name="G1", email="g1@x.com")
    guest2 = register_unverified_guest(api, name="G2", email="g2@x.com")
    plan = create_plan(api)
    vehicle = create_listed_vehicle(api, host["id"])
    book_trip(api, vehicle["id"], guest1["id"], plan["id"], "2026-06-01", "2026-06-08")
    version = current_vehicle_version(api, vehicle["id"])
    payload = create_trip_payload(vehicle["id"], guest2["id"], plan["id"],
                                  "2026-06-03", "2026-06-06", version)
    resp = api.create_trip(payload, make_guest_headers(guest2["id"]))
    validate_error(resp, ApiErrorId.ERR_GUEST_NOT_VERIFIED)


def test_booking_temporal_fires_when_guest_verified(api):
    """PRD §3.4: "the trip window must not overlap any `ACTIVE` `BOOKED` block on
    that vehicle under half-open comparison, else `ERR_DATES_UNAVAILABLE`."

    Design: Difficulty/priority_pair_validation_conflict/booking_state_beats_temporal
    """
    host = register_host(api)
    guest1 = register_verified_guest(api, license_number="DL-9b", name="G1", email="g1b@x.com")
    guest2 = register_verified_guest(api, license_number="DL-9c", name="G2", email="g2b@x.com")
    plan = create_plan(api)
    vehicle = create_listed_vehicle(api, host["id"])
    book_trip(api, vehicle["id"], guest1["id"], plan["id"], "2026-06-01", "2026-06-08")
    version = current_vehicle_version(api, vehicle["id"])
    payload = create_trip_payload(vehicle["id"], guest2["id"], plan["id"],
                                  "2026-06-03", "2026-06-06", version)
    resp = api.create_trip(payload, make_guest_headers(guest2["id"]))
    validate_error(resp, ApiErrorId.ERR_DATES_UNAVAILABLE)


# ------------- Difficulty: constraint (7) masks referential/uniqueness (9)
def test_claim_amount_constraint_beats_duplicate_open(api):
    """PRD §2.9: "A check earlier in this list always masks a later one"
    PRD §3.8: "a `damage_amount_cents` that must be greater than zero (else
    `ERR_INVALID_CLAIM_AMOUNT`)"

    Design: Difficulty/priority_pair_validation_conflict/claim_constraint_beats_referential
    """
    ctx = setup_checked_out_trip(api)
    file_claim(api, ctx, claimant="HOST", damage_amount_cents=200000)  # first open claim
    resp = api.create_claim(ctx["trip"]["id"], create_claim_payload("HOST", 0, "bad amount"),
                            ctx["host_headers"])
    validate_error(resp, ApiErrorId.ERR_INVALID_CLAIM_AMOUNT)


def test_duplicate_open_claim_fires_when_amount_valid(api):
    """PRD §3.8: "A trip may hold at most one open (non-terminal) claim at a
    time; filing a second while one is still open is rejected with
    `ERR_DUPLICATE_OPEN_CLAIM`."

    Design: Difficulty/priority_pair_validation_conflict/claim_constraint_beats_referential
    """
    ctx = setup_checked_out_trip(api)
    file_claim(api, ctx, claimant="HOST", damage_amount_cents=200000)  # first open claim
    resp = api.create_claim(ctx["trip"]["id"], create_claim_payload("HOST", 50000, "second"),
                            ctx["host_headers"])
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_OPEN_CLAIM)


# ---------------------- Difficulty: zero-night empty-interval boundary
def test_zero_night_booking_rejected(api):
    """PRD §3.4: "The span must be at least one night (`end_date` strictly after
    `start_date`), else `ERR_INVALID_DATE_RANGE`, and must not exceed the
    maximum trip length of 90 nights, else `ERR_TRIP_TOO_LONG`."

    Design: Difficulty/boundary_precision_check/zero_night_booking_rejected
    """
    sc = _listed_scenario(api)
    version = current_vehicle_version(api, sc["vehicle"]["id"])
    payload = create_trip_payload(sc["vehicle"]["id"], sc["guest"]["id"], sc["plan"]["id"],
                                  "2026-06-01", "2026-06-01", version)
    resp = api.create_trip(payload, make_guest_headers(sc["guest"]["id"]))
    validate_error(resp, ApiErrorId.ERR_INVALID_DATE_RANGE)


def test_one_night_booking_accepted(api):
    """PRD §3.4: "The span must be at least one night (`end_date` strictly after
    `start_date`), else `ERR_INVALID_DATE_RANGE`"

    Design: Difficulty/boundary_precision_check/zero_night_booking_rejected
    """
    sc = _listed_scenario(api)
    trip = book_trip(api, sc["vehicle"]["id"], sc["guest"]["id"], sc["plan"]["id"],
                     "2026-06-01", "2026-06-02")
    assert trip["nights"] == 1
    assert trip["status"] == "REQUESTED"


# ---------------- Difficulty: booking requires Vehicle LISTED (cross-entity)
def test_booking_draft_vehicle_rejected(api):
    """PRD §3.4: "The vehicle must be `LISTED` — a booking against a `DRAFT`,
    `SNOOZED`, or `UNLISTED` vehicle is rejected with `ERR_VEHICLE_NOT_LISTED`"

    Design: Difficulty/cross_entity_state_dependency/booking_requires_vehicle_listed
    """
    host = register_host(api)
    guest = register_verified_guest(api, license_number="DL-13", name="GM", email="gm@x.com")
    plan = create_plan(api)
    draft = create_vehicle(api, host["id"])  # never listed -> DRAFT
    payload = create_trip_payload(draft["id"], guest["id"], plan["id"],
                                  "2026-06-01", "2026-06-08", draft["version"])
    resp = api.create_trip(payload, make_guest_headers(guest["id"]))
    validate_error(resp, ApiErrorId.ERR_VEHICLE_NOT_LISTED)


def test_booking_listed_vehicle_accepted(api):
    """PRD §3.4: "The vehicle must be `LISTED` — a booking against a `DRAFT`,
    `SNOOZED`, or `UNLISTED` vehicle is rejected with `ERR_VEHICLE_NOT_LISTED`"

    Design: Difficulty/cross_entity_state_dependency/booking_requires_vehicle_listed
    """
    sc = _listed_scenario(api)
    trip = book_trip(api, sc["vehicle"]["id"], sc["guest"]["id"], sc["plan"]["id"],
                     "2026-06-01", "2026-06-08")
    assert trip["status"] == "REQUESTED"


# ------------- Difficulty: claim requires Trip CHECKED_OUT/COMPLETED (cross-entity)
def test_claim_on_confirmed_trip_rejected(api):
    """PRD §3.8: "either party may file a damage claim, but only against a trip
    whose `status` is `CHECKED_OUT` or `COMPLETED`; a claim against any earlier
    state is rejected with `ERR_TRIP_NOT_CLAIMABLE`."

    Design: Difficulty/cross_entity_state_dependency/claim_requires_trip_checked_out
    """
    ctx = setup_confirmed_trip(api)
    resp = api.create_claim(ctx["trip"]["id"], create_claim_payload("HOST", 50000, "premature"),
                            ctx["host_headers"])
    validate_error(resp, ApiErrorId.ERR_TRIP_NOT_CLAIMABLE)


def test_claim_on_checked_out_trip_accepted(api):
    """PRD §3.8: "either party may file a damage claim, but only against a trip
    whose `status` is `CHECKED_OUT` or `COMPLETED`; a claim against any earlier
    state is rejected with `ERR_TRIP_NOT_CLAIMABLE`."

    Design: Difficulty/cross_entity_state_dependency/claim_requires_trip_checked_out
    """
    ctx = setup_checked_out_trip(api)
    resp = api.create_claim(ctx["trip"]["id"], create_claim_payload("HOST", 50000, "damage"),
                            ctx["host_headers"])
    claim = validate_success(resp, expected_status=201)
    assert claim["status"] == "FILED"


# ----------------- Difficulty: availability half-open overlap
def test_availability_overlap_offset_rejected(api):
    """PRD §3.4: "the trip window must not overlap any `ACTIVE` `BOOKED` block on
    that vehicle under half-open comparison, else `ERR_DATES_UNAVAILABLE`."

    Design: Difficulty/resource_temporal_overlap/availability_halfopen_overlap_rejected
    """
    sc = _listed_scenario(api)
    book_trip(api, sc["vehicle"]["id"], sc["guest"]["id"], sc["plan"]["id"],
              "2026-06-01", "2026-06-08")
    version = current_vehicle_version(api, sc["vehicle"]["id"])
    payload = create_trip_payload(sc["vehicle"]["id"], sc["guest"]["id"], sc["plan"]["id"],
                                  "2026-06-05", "2026-06-10", version)
    resp = api.create_trip(payload, make_guest_headers(sc["guest"]["id"]))
    validate_error(resp, ApiErrorId.ERR_DATES_UNAVAILABLE)


def test_availability_overlap_contained_rejected(api):
    """PRD §3.4: "the trip window must not overlap any `ACTIVE` `BOOKED` block on
    that vehicle under half-open comparison, else `ERR_DATES_UNAVAILABLE`."

    Design: Difficulty/resource_temporal_overlap/availability_halfopen_overlap_rejected
    """
    sc = _listed_scenario(api)
    book_trip(api, sc["vehicle"]["id"], sc["guest"]["id"], sc["plan"]["id"],
              "2026-06-01", "2026-06-08")
    version = current_vehicle_version(api, sc["vehicle"]["id"])
    payload = create_trip_payload(sc["vehicle"]["id"], sc["guest"]["id"], sc["plan"]["id"],
                                  "2026-06-02", "2026-06-05", version)
    resp = api.create_trip(payload, make_guest_headers(sc["guest"]["id"]))
    validate_error(resp, ApiErrorId.ERR_DATES_UNAVAILABLE)


# ----------------- Difficulty: pricing rule closed-interval overlap
def test_pricing_rule_adjacent_shared_endpoint_rejected(api):
    """PRD §3.2: "A pricing rule's interval is closed — both endpoints inclusive
    ... a create whose interval overlaps an existing `ACTIVE` rule on that
    vehicle is rejected with `ERR_PRICING_RULE_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/pricing_closed_interval_adjacent_rejected
    """
    host = register_host(api)
    vehicle = create_vehicle(api, host["id"])
    add_active_pricing_rule(api, host["id"], vehicle["id"], "2026-06-01", "2026-06-07", 15000)
    resp = api.create_pricing_rule(
        create_pricing_rule_payload(vehicle["id"], "2026-06-07", "2026-06-10", 18000),
        make_host_headers(host["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_PRICING_RULE_OVERLAP)


def test_pricing_rule_non_adjacent_day_after_accepted(api):
    """PRD §3.2: "A pricing rule's interval is closed — both endpoints inclusive
    ... a create whose interval overlaps an existing `ACTIVE` rule on that
    vehicle is rejected with `ERR_PRICING_RULE_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/pricing_closed_interval_adjacent_rejected
    """
    host = register_host(api)
    vehicle = create_vehicle(api, host["id"])
    add_active_pricing_rule(api, host["id"], vehicle["id"], "2026-06-01", "2026-06-07", 15000)
    resp = api.create_pricing_rule(
        create_pricing_rule_payload(vehicle["id"], "2026-06-08", "2026-06-10", 18000),
        make_host_headers(host["id"]),
    )
    rule = validate_success(resp, expected_status=201)
    assert rule["status"] == "ACTIVE"
