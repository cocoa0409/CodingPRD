"""Validation, precedence, boundary, cross-entity-dependency and temporal-overlap tests.

Covers Difficulty queue (priority_pair_validation_conflict, boundary_precision_check,
cross_entity_state_dependency, resource_temporal_overlap) and Corner queue (validations,
entities, endpoints sections).
"""
from test_helpers import (
    api_client,
    validate_success,
    validate_error,
    get_success_data,
    make_patron_headers,
    NON_EXISTENT_UUID,
    TEST_USERS,
    setup_venue_lot_film,
    setup_scheduled_showtime,
    create_venue,
    create_lot,
    create_film,
    create_showtime,
    create_season_pass,
    create_concession_item,
    create_private_rental,
    create_approved_rental,
    make_reservation,
    create_paid_reservation,
    create_checked_in_reservation,
    create_concession_order,
    create_paid_concession_order,
    set_clock,
)

OPERATOR = TEST_USERS["venue_operator_headers"]
GATE = TEST_USERS["gate_attendant_headers"]


# =====================================================================
# Difficulty: priority_pair_validation_conflict / existence_beats_referential_pass_invalid
# =====================================================================
def test_existence_beats_referential_pass_invalid(api):
    """PRD §2.7: "Next, existence of every resource named in the path or body is checked,
    left to right, with the first missing one yielding `ERR_NOT_FOUND` (HTTP 404)."

    Design: Difficulty/priority_pair_validation_conflict/existence_beats_referential_pass_invalid
    """
    venue, lot, film, st = setup_scheduled_showtime(
        clock="2026-06-01T00:00:00Z", start_utc="2026-06-26T02:00:00Z"
    )
    res = api.create_reservation(
        {"showtime_id": st["id"], "patron_id": "patron-iii", "occupant_count": 2,
         "season_pass_id": "00000000-0000-4000-8000-000000000000",
         "expected_showtime_version": st["version"]},
        make_patron_headers("patron-iii"),
    )
    validate_error(res, "ERR_NOT_FOUND")


def test_existence_beats_referential_nonexistent_showtime(api):
    """PRD §2.7: "Next, existence of every resource named in the path or body is checked,
    left to right, with the first missing one yielding `ERR_NOT_FOUND` (HTTP 404)."

    Design: Difficulty/priority_pair_validation_conflict/existence_beats_referential_pass_invalid
    """
    venue, lot, film = setup_venue_lot_film(clock="2026-06-01T00:00:00Z")
    sp = create_season_pass("patron-iv", "2026-06-01T00:00:00Z", "2026-12-31T23:59:59Z",
                            tier="GOLD", max_redemptions=3)
    # Showtime does not exist; body also names a valid pass. Existence (showtime) wins.
    res = api.create_reservation(
        {"showtime_id": "22222222-2222-4222-8222-222222222222", "patron_id": "patron-iv",
         "occupant_count": 2, "season_pass_id": sp["id"], "expected_showtime_version": 1},
        make_patron_headers("patron-iv"),
    )
    validate_error(res, "ERR_NOT_FOUND")


# =====================================================================
# Difficulty: boundary_precision_check / lot_full_exact_last_stall_boundary
# =====================================================================
def test_lot_full_last_stall_boundary(api):
    """PRD §3.4: "For a per-car reservation, the showtime's `reserved_stall_count` must be
    strictly less than the lot's `stall_count`, otherwise `ERR_LOT_FULL` (HTTP 409)."

    Design: Difficulty/boundary_precision_check/lot_full_exact_last_stall_boundary
    """
    venue, lot, film = setup_venue_lot_film(clock="2026-06-01T00:00:00Z", stall_count=1)
    st = create_showtime(venue["id"], lot["id"], film["id"], "2026-06-28T02:00:00Z")
    make_reservation(st, "patron-j1", occupant_count=2)  # takes the last stall
    st_after = validate_success(api.get_showtime(st["id"], OPERATOR))
    assert st_after["reserved_stall_count"] == 1
    res = api.create_reservation(
        {"showtime_id": st["id"], "patron_id": "patron-j2", "occupant_count": 2,
         "expected_showtime_version": st_after["version"]},
        make_patron_headers("patron-j2"),
    )
    validate_error(res, "ERR_LOT_FULL")


def test_first_reservation_succeeds_at_capacity_one(api):
    """PRD §3.4: "For a per-car reservation, the showtime's `reserved_stall_count` must be
    strictly less than the lot's `stall_count`, otherwise `ERR_LOT_FULL` (HTTP 409)."

    Design: Difficulty/boundary_precision_check/lot_full_exact_last_stall_boundary
    """
    venue, lot, film = setup_venue_lot_film(clock="2026-06-01T00:00:00Z", stall_count=1)
    st = create_showtime(venue["id"], lot["id"], film["id"], "2026-06-28T03:00:00Z")
    # reserved_stall_count 0 < 1 -> the create succeeds (boundary X-1 case).
    resv = make_reservation(st, "patron-j0", occupant_count=2)
    assert resv["stalls_used"] == 1
    st_after = validate_success(api.get_showtime(st["id"], OPERATOR))
    assert st_after["reserved_stall_count"] == 1


# =====================================================================
# Difficulty: boundary_precision_check / empty_concession_lines_rejected
# =====================================================================
def test_empty_concession_lines_rejected(api):
    """PRD §3.8: "The order carries its `reservation_id` and a non-empty `lines` array,
    where each line is an object of `{concession_item_id, qty}` with a `qty` of at least 1."

    Design: Difficulty/boundary_precision_check/empty_concession_lines_rejected
    """
    venue, lot, film, st = setup_scheduled_showtime(
        clock="2026-06-01T00:00:00Z", start_utc="2026-06-29T02:00:00Z"
    )
    resv = make_reservation(st, "patron-kkk", occupant_count=2)
    res = api.create_concession_order(resv["id"], {"lines": []}, make_patron_headers("patron-kkk"))
    validate_error(res, "ERR_INVALID_REQUEST")


def test_missing_concession_lines_field_rejected(api):
    """PRD §3.8: "The order carries its `reservation_id` and a non-empty `lines` array,
    where each line is an object of `{concession_item_id, qty}` with a `qty` of at least 1."

    Design: Difficulty/boundary_precision_check/empty_concession_lines_rejected
    """
    venue, lot, film, st = setup_scheduled_showtime(
        clock="2026-06-01T00:00:00Z", start_utc="2026-06-29T03:00:00Z"
    )
    resv = make_reservation(st, "patron-noml", occupant_count=2)
    # lines field omitted entirely.
    res = api.create_concession_order(resv["id"], {}, make_patron_headers("patron-noml"))
    validate_error(res, "ERR_INVALID_REQUEST")


# =====================================================================
# Difficulty: cross_entity_state_dependency /
#   concession_fulfill_requires_reservation_scanned
# =====================================================================
def test_concession_fulfill_requires_reservation_scanned(api):
    """PRD §3.8: "A paid order is fulfilled by a `GateAttendant`, advancing `status` from
    `PAID` to `FULFILLED`; fulfillment is allowed only while the order is `PAID` and — a
    cross-entity guard — only once the parent reservation's `occupancy_status` is `SCANNED`,
    ensuring food is handed over only after the patron has physically scanned in."

    Design: Difficulty/cross_entity_state_dependency/concession_fulfill_requires_reservation_scanned
    """
    venue, lot, film = setup_venue_lot_film(clock="2026-06-30T01:30:00Z")
    item = create_concession_item(venue["id"], name="Popcorn", unit_price_cents=350, tax_rate=0.0725)
    st = create_showtime(venue["id"], lot["id"], film["id"], "2026-06-30T02:00:00Z")
    resv = create_checked_in_reservation(st, "patron-lll", occupant_count=2)
    order = create_paid_concession_order(
        resv["id"], "patron-lll", [{"concession_item_id": item["id"], "qty": 1}]
    )
    # Reservation is CHECKED_IN, not SCANNED -> fulfill rejected.
    res = api.fulfill_concession_order(order["id"], GATE)
    validate_error(res, "ERR_INVALID_STATE")
    resv_after = validate_success(api.get_reservation(resv["id"], GATE))
    assert resv_after["occupancy_status"] == "CHECKED_IN"


def test_concession_fulfill_succeeds_after_reservation_scanned(api):
    """PRD §3.8: "A paid order is fulfilled by a `GateAttendant`, advancing `status` from
    `PAID` to `FULFILLED`; fulfillment is allowed only while the order is `PAID` and — a
    cross-entity guard — only once the parent reservation's `occupancy_status` is `SCANNED`."

    Design: Difficulty/cross_entity_state_dependency/concession_fulfill_requires_reservation_scanned
    """
    venue, lot, film = setup_venue_lot_film(clock="2026-06-30T02:30:00Z")
    item = create_concession_item(venue["id"], name="Popcorn", unit_price_cents=350, tax_rate=0.0725)
    st = create_showtime(venue["id"], lot["id"], film["id"], "2026-06-30T03:00:00Z")
    # Build the reservation to SCANNED then attach a PAID order.
    resv = make_reservation(st, "patron-scn", occupant_count=2)
    gate_code = resv["gate_code"]
    validate_success(api.pay_reservation(resv["id"], make_patron_headers("patron-scn")))
    validate_success(api.check_in_reservation(resv["id"], GATE))
    validate_success(api.scan_reservation(resv["id"], gate_code, GATE))
    order = create_paid_concession_order(
        resv["id"], "patron-scn", [{"concession_item_id": item["id"], "qty": 1}]
    )
    fulfilled = validate_success(api.fulfill_concession_order(order["id"], GATE))
    assert fulfilled["status"] == "FULFILLED"


# =====================================================================
# Difficulty: cross_entity_state_dependency / rental_approve_blocked_by_showtime_on_lot
# =====================================================================
def test_rental_approve_blocked_by_showtime_on_lot(api):
    """PRD §3.7: "there must be no other `APPROVED` private rental on the same lot whose
    closed window overlaps this one, and no showtime on the same lot whose `status` is
    `SCHEDULED` or `WEATHER_HOLD` whose interval intersects this hold window. A conflict
    yields `ERR_RENTAL_CONFLICT` (HTTP 409)."

    Design: Difficulty/cross_entity_state_dependency/rental_approve_blocked_by_showtime_on_lot
    """
    venue, lot, film = setup_venue_lot_film(clock="2026-06-01T00:00:00Z", runtime_minutes=120)
    # A SCHEDULED showtime occupies the lot in the evening window.
    create_showtime(venue["id"], lot["id"], film["id"], "2026-07-05T02:00:00Z")
    rental = create_private_rental(
        venue["id"], lot["id"], "org-9", "2026-07-05T02:30:00Z", "2026-07-05T05:00:00Z",
        flat_venue_fee_cents=100000, per_hour_cents=10000,
    )
    res = api.approve_private_rental(rental["id"], rental["version"], OPERATOR)
    validate_error(res, "ERR_RENTAL_CONFLICT")
    rental_after = validate_success(api.get_private_rental(rental["id"], OPERATOR))
    assert rental_after["status"] == "REQUESTED"


def test_rental_approve_succeeds_when_showtime_on_other_lot(api):
    """PRD §3.7: "no showtime on the same lot whose `status` is `SCHEDULED` or
    `WEATHER_HOLD` whose interval intersects this hold window. A conflict yields
    `ERR_RENTAL_CONFLICT` (HTTP 409)."

    Design: Difficulty/cross_entity_state_dependency/rental_approve_blocked_by_showtime_on_lot
    """
    venue, lot, film = setup_venue_lot_film(clock="2026-06-01T00:00:00Z", runtime_minutes=120)
    other_lot = create_lot(venue["id"], name="OtherLot", stall_count=10, person_capacity=100)
    # Showtime on `lot`; rental requested on `other_lot` for an overlapping window.
    create_showtime(venue["id"], lot["id"], film["id"], "2026-07-06T02:00:00Z")
    rental = create_private_rental(
        venue["id"], other_lot["id"], "org-other", "2026-07-06T02:30:00Z", "2026-07-06T05:00:00Z",
        flat_venue_fee_cents=100000, per_hour_cents=10000,
    )
    approved = validate_success(
        api.approve_private_rental(rental["id"], rental["version"], OPERATOR)
    )
    assert approved["status"] == "APPROVED"


# =====================================================================
# Difficulty: resource_temporal_overlap / showtime_overlap_half_open_plus_buffer
# =====================================================================
def test_showtime_overlap_half_open_plus_buffer(api):
    """PRD §3.2: "treating each showtime's occupancy as the half-open window from its
    `start_utc` up to but not including its `end_utc`, and extending that window by the
    venue's `turnaround_buffer_minutes` of cleanup time, the new window must not overlap that
    of any other showtime on the same lot whose `status` is `SCHEDULED` or `WEATHER_HOLD`. A
    collision yields `ERR_SHOWTIME_OVERLAP` (HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/showtime_overlap_half_open_plus_buffer
    """
    venue, lot, film = setup_venue_lot_film(
        clock="2026-06-01T00:00:00Z", runtime_minutes=120,
        venue_overrides={"turnaround_buffer_minutes": 30},
    )
    # First showtime 02:00-04:00 (120m). Buffer 30m blocks any start before 04:30.
    create_showtime(venue["id"], lot["id"], film["id"], "2026-07-10T02:00:00Z")
    # Second showtime starting 04:29 collides (04:29 < 04:00 + 30m).
    res = api.create_showtime(
        {"venue_id": venue["id"], "lot_id": lot["id"], "primary_film_id": film["id"],
         "is_double_feature": False, "start_utc": "2026-07-10T04:29:00Z",
         "pricing_mode": "PER_CAR", "base_price_cents": 2000},
        OPERATOR,
    )
    validate_error(res, "ERR_SHOWTIME_OVERLAP")


def test_showtime_no_overlap_after_buffer(api):
    """PRD §3.2: "extending that window by the venue's `turnaround_buffer_minutes` of cleanup
    time, the new window must not overlap that of any other showtime on the same lot whose
    `status` is `SCHEDULED` or `WEATHER_HOLD`."

    Design: Difficulty/resource_temporal_overlap/showtime_overlap_half_open_plus_buffer
    """
    venue, lot, film = setup_venue_lot_film(
        clock="2026-06-01T00:00:00Z", runtime_minutes=120,
        venue_overrides={"turnaround_buffer_minutes": 30},
    )
    create_showtime(venue["id"], lot["id"], film["id"], "2026-07-11T02:00:00Z")
    # 04:30 is exactly end(04:00)+buffer(30m); the half-open+buffer window ends at 04:30,
    # so a start at 04:30 does not overlap and succeeds.
    second = validate_success(
        api.create_showtime(
            {"venue_id": venue["id"], "lot_id": lot["id"], "primary_film_id": film["id"],
             "is_double_feature": False, "start_utc": "2026-07-11T04:30:00Z",
             "pricing_mode": "PER_CAR", "base_price_cents": 2000},
            OPERATOR,
        ),
        expected_status=201,
    )
    assert second["status"] == "SCHEDULED"


# =====================================================================
# Difficulty: resource_temporal_overlap / rental_overlap_closed_whole_lot
# =====================================================================
def test_rental_overlap_closed_interval_shared_endpoint(api):
    """PRD §3.7: "the lot must be free across the requested window, treated as a closed
    interval (inclusive of both `start_utc` and `end_utc`) covering the whole lot: there must
    be no other `APPROVED` private rental on the same lot whose closed window overlaps this
    one."

    Design: Difficulty/resource_temporal_overlap/rental_overlap_closed_whole_lot
    """
    venue, lot, film = setup_venue_lot_film(clock="2026-06-01T00:00:00Z")
    # First rental 02:00-06:00 approved.
    create_approved_rental(
        venue["id"], lot["id"], "org-a", "2026-07-12T02:00:00Z", "2026-07-12T06:00:00Z"
    )
    # Second rental 06:00-08:00; closed-interval shares endpoint 06:00 -> conflict.
    r2 = create_private_rental(
        venue["id"], lot["id"], "org-b", "2026-07-12T06:00:00Z", "2026-07-12T08:00:00Z"
    )
    res = api.approve_private_rental(r2["id"], r2["version"], OPERATOR)
    validate_error(res, "ERR_RENTAL_CONFLICT")
    r2_after = validate_success(api.get_private_rental(r2["id"], OPERATOR))
    assert r2_after["status"] == "REQUESTED"


def test_rental_approve_succeeds_disjoint_closed_windows(api):
    """PRD §3.7: "the lot must be free across the requested window, treated as a closed
    interval (inclusive of both `start_utc` and `end_utc`) covering the whole lot: there must
    be no other `APPROVED` private rental on the same lot whose closed window overlaps this
    one."

    Design: Difficulty/resource_temporal_overlap/rental_overlap_closed_whole_lot
    """
    venue, lot, film = setup_venue_lot_film(clock="2026-06-01T00:00:00Z")
    # First rental 02:00-06:00 approved.
    create_approved_rental(
        venue["id"], lot["id"], "org-d1", "2026-07-13T02:00:00Z", "2026-07-13T06:00:00Z"
    )
    # Second rental 07:00-09:00 is strictly disjoint from the closed [02:00,06:00] window.
    r2 = create_private_rental(
        venue["id"], lot["id"], "org-d2", "2026-07-13T07:00:00Z", "2026-07-13T09:00:00Z"
    )
    approved = validate_success(api.approve_private_rental(r2["id"], r2["version"], OPERATOR))
    assert approved["status"] == "APPROVED"


# =====================================================================
# Corner: validations / person_capacity_exceeded_rejected
# =====================================================================
def test_person_capacity_exceeded_rejected(api):
    """PRD §3.4: "For a per-person reservation, the showtime's `reserved_person_count` plus
    the new `occupant_count` must be at most the lot's `person_capacity`, otherwise
    `ERR_PERSON_CAPACITY_EXCEEDED` (HTTP 409)."

    Design: Corner/validations/person_capacity_exceeded_rejected
    """
    venue, lot, film = setup_venue_lot_film(clock="2026-06-01T00:00:00Z", person_capacity=3)
    st = create_showtime(venue["id"], lot["id"], film["id"], "2026-08-08T02:00:00Z",
                         pricing_mode="PER_PERSON", base_price_cents=900)
    res = api.create_reservation(
        {"showtime_id": st["id"], "patron_id": "patron-pcap", "occupant_count": 4,
         "expected_showtime_version": st["version"]},
        make_patron_headers("patron-pcap"),
    )
    validate_error(res, "ERR_PERSON_CAPACITY_EXCEEDED")


# =====================================================================
# Corner: validations / pass_exhausted_on_last_redemption
# =====================================================================
def test_pass_exhausted_on_last_redemption(api):
    """PRD §3.4: "a pass-backed create also requires redemption budget: `redemptions_used`
    must be strictly less than the pass's `max_redemptions`, or the create is rejected with
    `ERR_PASS_EXHAUSTED` (HTTP 409)."

    Design: Corner/validations/pass_exhausted_on_last_redemption
    """
    venue, lot, film = setup_venue_lot_film(clock="2026-06-01T00:00:00Z")
    sp = create_season_pass("patron-pex", "2026-08-01T00:00:00Z", "2026-08-31T23:59:59Z",
                            tier="SILVER", max_redemptions=1)
    st1 = create_showtime(venue["id"], lot["id"], film["id"], "2026-08-09T02:00:00Z")
    make_reservation(st1, "patron-pex", occupant_count=2, season_pass_id=sp["id"])
    st2 = create_showtime(venue["id"], lot["id"], film["id"], "2026-08-10T02:00:00Z")
    res = api.create_reservation(
        {"showtime_id": st2["id"], "patron_id": "patron-pex", "occupant_count": 2,
         "season_pass_id": sp["id"], "expected_showtime_version": st2["version"]},
        make_patron_headers("patron-pex"),
    )
    validate_error(res, "ERR_PASS_EXHAUSTED")


# =====================================================================
# Corner: validations / concession_unavailable_item_rejected
# =====================================================================
def test_concession_unavailable_item_rejected(api):
    """PRD §3.8: "Every referenced concession item must have `available` equal to true and
    must belong to the same venue as the reservation; otherwise the create is rejected with
    `ERR_ITEM_UNAVAILABLE` (HTTP 409)."

    Design: Corner/validations/concession_unavailable_item_rejected
    """
    venue, lot, film = setup_venue_lot_film(clock="2026-06-01T00:00:00Z")
    item = create_concession_item(venue["id"], name="Sold Out", unit_price_cents=500,
                                  tax_rate=0.0, available=False)
    st = create_showtime(venue["id"], lot["id"], film["id"], "2026-08-11T02:00:00Z")
    resv = make_reservation(st, "patron-iu", occupant_count=2)
    res = api.create_concession_order(
        resv["id"], {"lines": [{"concession_item_id": item["id"], "qty": 1}]},
        make_patron_headers("patron-iu"),
    )
    validate_error(res, "ERR_ITEM_UNAVAILABLE")


# =====================================================================
# Corner: validations / showtime_config_invalid_double_without_secondary
# =====================================================================
def test_showtime_config_invalid_double_without_secondary(api):
    """PRD §3.2: "`secondary_film_id` must be non-null exactly when `is_double_feature` is
    true (non-null with a single feature, or null with a double feature, is inconsistent). A
    violation yields `ERR_SHOWTIME_CONFIG_INVALID` (HTTP 422)."

    Design: Corner/validations/showtime_config_invalid_double_without_secondary
    """
    venue, lot, film = setup_venue_lot_film(clock="2026-06-01T00:00:00Z")
    res = api.create_showtime(
        {"venue_id": venue["id"], "lot_id": lot["id"], "primary_film_id": film["id"],
         "is_double_feature": True, "start_utc": "2026-08-12T02:00:00Z",
         "pricing_mode": "PER_CAR", "base_price_cents": 2000},
        OPERATOR,
    )
    validate_error(res, "ERR_SHOWTIME_CONFIG_INVALID")


# =====================================================================
# Corner: validations / weather_features_remaining_out_of_range_rejected
# =====================================================================
def test_weather_features_remaining_out_of_range_rejected(api):
    """PRD §3.10: "For a cancellation, `features_remaining` must lie between 0 and the
    showtime's total feature count (2 for a double feature, 1 for a single feature); a value
    outside that range is rejected with `ERR_WEATHER_FEATURES_INVALID` (HTTP 422)."

    Design: Corner/validations/weather_features_remaining_out_of_range_rejected
    """
    venue, lot, film, st = setup_scheduled_showtime(
        clock="2026-06-01T00:00:00Z", start_utc="2026-08-13T02:00:00Z"
    )
    res = api.create_weather_event(
        st["id"], {"severity": "CANCELLATION", "features_remaining": 2}, OPERATOR
    )
    validate_error(res, "ERR_WEATHER_FEATURES_INVALID")


# =====================================================================
# Corner: validations / pagination_limit_out_of_range_rejected
# =====================================================================
def test_pagination_limit_out_of_range_rejected(api):
    """PRD §2.3: "A `limit` outside the inclusive range of 1 through 100, or a negative
    `offset`, is rejected with `ERR_VALIDATION_LIMIT` (HTTP 422)."

    Design: Corner/validations/pagination_limit_out_of_range_rejected
    """
    venue = create_venue(name="VC26")
    res = api.list_showtimes(make_patron_headers("patron-pg"),
                             params={"venue_id": venue["id"], "limit": 0})
    validate_error(res, "ERR_VALIDATION_LIMIT")


# =====================================================================
# Corner: errors / error_pass_invalid_outside_validity_window
# =====================================================================
def test_pass_invalid_outside_validity_window(api):
    """PRD §3.4: "if a `season_pass_id` is supplied, that pass must be `ACTIVE`, owned by the
    acting patron, within its validity window, not exhausted, and valid for this screening in
    the sense that the showtime's `start_utc` is on or before the pass's `valid_to_utc`. Any
    of those pass conditions failing — wrong owner, not `ACTIVE`, outside the window, or a
    screening after `valid_to_utc` — yields `ERR_PASS_INVALID` (HTTP 422)."

    Design: Corner/errors/error_pass_invalid_outside_validity_window
    """
    venue, lot, film = setup_venue_lot_film(clock="2026-06-01T00:00:00Z")
    sp = create_season_pass("patron-pw", "2026-08-01T00:00:00Z", "2026-08-31T23:59:59Z",
                            tier="SILVER", max_redemptions=3)
    # Showtime starts 2026-09-05, after the pass valid_to_utc 2026-08-31.
    st = create_showtime(venue["id"], lot["id"], film["id"], "2026-09-05T02:00:00Z")
    res = api.create_reservation(
        {"showtime_id": st["id"], "patron_id": "patron-pw", "occupant_count": 2,
         "season_pass_id": sp["id"], "expected_showtime_version": st["version"]},
        make_patron_headers("patron-pw"),
    )
    validate_error(res, "ERR_PASS_INVALID")
