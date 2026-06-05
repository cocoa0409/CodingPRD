"""Availability boundary precision, half-open interval adjacency, group-block cutoff
window, block close empty boundary, and compensating invariants (cancel releases
inventory, void restores folio balance). Plus overbooking allowance and block wash.

Difficulty queue: boundary_precision_check, resource_temporal_overlap, compensating_invariant.
Corner queue: overbooking allowance, block wash, immediate-consistency availability.
"""
from test_helpers import (
    api_client as _api_client,
    validate_success,
    validate_error,
    get_success_data,
    ApiErrorId,
    TEST_USERS,
    setup_basic,
    create_hotel,
    create_room_type,
    create_rate_plan,
    create_guest,
    create_group_block,
    get_folio_for_reservation,
    open_audit,
    run_one_audit,
)
api = _api_client
RM = TEST_USERS["revenue_manager_headers"]
FDA = TEST_USERS["front_desk_headers"]
NA = TEST_USERS["night_auditor_headers"]


def _folio(hotel_id, res_id):
    return get_folio_for_reservation(hotel_id, res_id)


def _avail_cell(hotel_id, room_type_id, start_date, end_date, stay_date):
    cells = validate_success(api.get_availability(FDA, params={
        "room_type_id": room_type_id, "start_date": start_date, "end_date": end_date}))
    for c in cells:
        if c["stay_date"] == stay_date:
            return c
    raise AssertionError(f"no availability cell for {stay_date} in {cells}")


# ===========================================================================
# Difficulty/boundary_precision_check/availability_sellable_exact_boundary_sold_plus_one
# ===========================================================================
def test_availability_boundary_sell_up_to_sellable_then_reject():
    """PRD §3.3: "A new reservation is admissible for a given night only when the current
    sold count plus one is at most the sellable count; selling the room that brings the
    sold count up to the sellable count is permitted, but the next one is not."

    inv 2, overbooking 0.0 -> sellable 2; rooms 1 and 2 sell (201), the 3rd is rejected
    with ERR_NO_AVAILABILITY.

    Design: Difficulty/boundary_precision_check/availability_sellable_exact_boundary_sold_plus_one
    """
    hotel = create_hotel(current_business_date="2026-07-01", overbooking_allowance_pct=0.0)
    std = create_room_type(hotel["id"], code="STD", tier_rank=1,
                           physical_inventory=2, base_rate_cents=10000)
    bar = create_rate_plan(hotel["id"], code="BAR", kind="BAR",
                           adjustment_mode="FLAT", adjustment_value=0, no_show_policy="NONE")
    guest = create_guest(hotel["id"])

    r1 = api.create_reservation({
        "hotel_id": hotel["id"], "guest_id": guest["id"], "room_type_id": std["id"],
        "rate_plan_id": bar["id"], "arrival_date": "2026-07-01",
        "departure_date": "2026-07-02"}, FDA)
    validate_success(r1, expected_status=201)
    r2 = api.create_reservation({
        "hotel_id": hotel["id"], "guest_id": guest["id"], "room_type_id": std["id"],
        "rate_plan_id": bar["id"], "arrival_date": "2026-07-01",
        "departure_date": "2026-07-02"}, FDA)
    validate_success(r2, expected_status=201)

    r3 = api.create_reservation({
        "hotel_id": hotel["id"], "guest_id": guest["id"], "room_type_id": std["id"],
        "rate_plan_id": bar["id"], "arrival_date": "2026-07-01",
        "departure_date": "2026-07-02"}, FDA)
    validate_error(r3, ApiErrorId.ERR_NO_AVAILABILITY.value)


def test_availability_second_sale_at_boundary_succeeds():
    """PRD §3.3: "If for any night in the half-open interval from `arrival_date` to
    `departure_date` the sold count plus one would exceed the sellable count, the booking
    is rejected with `ERR_NO_AVAILABILITY` (HTTP 409)."

    inv 2 -> sellable 2; the 2nd sale (sold 1 -> sold+1=2 <= 2) is admissible.

    Design: Difficulty/boundary_precision_check/availability_sellable_exact_boundary_sold_plus_one
    """
    hotel = create_hotel(current_business_date="2026-07-01", overbooking_allowance_pct=0.0)
    std = create_room_type(hotel["id"], code="STD", tier_rank=1,
                           physical_inventory=2, base_rate_cents=10000)
    bar = create_rate_plan(hotel["id"], code="BAR", kind="BAR",
                           adjustment_mode="FLAT", adjustment_value=0, no_show_policy="NONE")
    guest = create_guest(hotel["id"])
    get_success_data(api.create_reservation({
        "hotel_id": hotel["id"], "guest_id": guest["id"], "room_type_id": std["id"],
        "rate_plan_id": bar["id"], "arrival_date": "2026-07-01",
        "departure_date": "2026-07-02"}, FDA))
    second = api.create_reservation({
        "hotel_id": hotel["id"], "guest_id": guest["id"], "room_type_id": std["id"],
        "rate_plan_id": bar["id"], "arrival_date": "2026-07-01",
        "departure_date": "2026-07-02"}, FDA)
    res2 = validate_success(second, expected_status=201)
    assert res2["status"] == "HELD", res2


# ===========================================================================
# Difficulty/boundary_precision_check/block_close_empty_pending_pickups_zero_held
# ===========================================================================
def test_close_block_with_zero_held_pickups_succeeds():
    """PRD §3.2: "closing requires `expected_group_block_version` and is rejected with
    `ERR_BLOCK_HAS_PENDING_PICKUPS` (HTTP 409) if any reservation still attached to the
    block is in `HELD` status."

    A block with zero HELD reservations attached closes successfully (empty-set boundary).

    Design: Difficulty/boundary_precision_check/block_close_empty_pending_pickups_zero_held
    """
    hotel = create_hotel(current_business_date="2026-07-01", overbooking_allowance_pct=0.0)
    queen = create_room_type(hotel["id"], code="QUEEN", tier_rank=1,
                             physical_inventory=5, base_rate_cents=15000)
    grp = create_rate_plan(hotel["id"], code="GRP", kind="BAR",
                           adjustment_mode="FLAT", adjustment_value=0, no_show_policy="NONE")
    block = create_group_block(hotel["id"], queen["id"], grp["id"], block_name="Empty",
                               arrival_date="2026-07-05", departure_date="2026-07-06",
                               cutoff_date="2026-07-04", blocked_rooms=3)
    closed = validate_success(api.close_group_block(
        block["id"], {"expected_group_block_version": block["version"]}, RM))
    assert closed["status"] == "CLOSED", closed


def test_close_block_with_held_pickup_rejected():
    """PRD §3.2: "closing ... is rejected with `ERR_BLOCK_HAS_PENDING_PICKUPS` (HTTP 409)
    if any reservation still attached to the block is in `HELD` status."

    The opposite side of the zero-HELD boundary: one HELD pickup blocks the close.

    Design: Difficulty/boundary_precision_check/block_close_empty_pending_pickups_zero_held
    """
    hotel = create_hotel(current_business_date="2026-07-01", overbooking_allowance_pct=0.0)
    queen = create_room_type(hotel["id"], code="QUEEN", tier_rank=1,
                             physical_inventory=5, base_rate_cents=15000)
    grp = create_rate_plan(hotel["id"], code="GRP", kind="BAR",
                           adjustment_mode="FLAT", adjustment_value=0, no_show_policy="NONE")
    block = create_group_block(hotel["id"], queen["id"], grp["id"], block_name="Pend",
                               arrival_date="2026-07-08", departure_date="2026-07-10",
                               cutoff_date="2026-07-20", blocked_rooms=3)
    guest = create_guest(hotel["id"])
    get_success_data(api.create_reservation({
        "hotel_id": hotel["id"], "guest_id": guest["id"], "room_type_id": queen["id"],
        "rate_plan_id": grp["id"], "arrival_date": "2026-07-08",
        "departure_date": "2026-07-10", "group_block_id": block["id"],
        "expected_group_block_version": block["version"]}, FDA))
    block_now = validate_success(api.get_group_block(block["id"], RM))

    resp = api.close_group_block(
        block["id"], {"expected_group_block_version": block_now["version"]}, RM)
    validate_error(resp, ApiErrorId.ERR_BLOCK_HAS_PENDING_PICKUPS.value)


# ===========================================================================
# Difficulty/resource_temporal_overlap/room_inventory_overlap_half_open_interval_adjacency_allowed
# ===========================================================================
def test_adjacent_stay_at_shared_boundary_does_not_conflict():
    """PRD §3.3: "whose `arrival_date` is on or before the night and whose
    `departure_date` is strictly after it".

    inv 1; existing 07-01..07-03; a 07-03..07-05 stay is adjacent at the 07-03 checkout
    boundary and does not conflict on the half-open interval.

    Design: Difficulty/resource_temporal_overlap/room_inventory_overlap_half_open_interval_adjacency_allowed
    """
    hotel = create_hotel(current_business_date="2026-07-01", overbooking_allowance_pct=0.0)
    one = create_room_type(hotel["id"], code="ONE", tier_rank=1,
                           physical_inventory=1, base_rate_cents=10000)
    bar = create_rate_plan(hotel["id"], code="BAR", kind="BAR",
                           adjustment_mode="FLAT", adjustment_value=0, no_show_policy="NONE")
    guest = create_guest(hotel["id"])
    get_success_data(api.create_reservation({
        "hotel_id": hotel["id"], "guest_id": guest["id"], "room_type_id": one["id"],
        "rate_plan_id": bar["id"], "arrival_date": "2026-07-01",
        "departure_date": "2026-07-03"}, FDA))
    adj = api.create_reservation({
        "hotel_id": hotel["id"], "guest_id": guest["id"], "room_type_id": one["id"],
        "rate_plan_id": bar["id"], "arrival_date": "2026-07-03",
        "departure_date": "2026-07-05"}, FDA)
    res2 = validate_success(adj, expected_status=201)
    assert res2["status"] == "HELD", res2


def test_true_overlap_on_half_open_interval_rejected():
    """PRD §3.3: "If for any night in the half-open interval from `arrival_date` to
    `departure_date` the sold count plus one would exceed the sellable count, the booking
    is rejected with `ERR_NO_AVAILABILITY` (HTTP 409)."

    inv 1; existing 07-01..07-03 and 07-03..07-05; a 07-02..07-04 stay overlaps night
    07-02 (and 07-03) and is rejected.

    Design: Difficulty/resource_temporal_overlap/room_inventory_overlap_half_open_interval_adjacency_allowed
    """
    hotel = create_hotel(current_business_date="2026-07-01", overbooking_allowance_pct=0.0)
    one = create_room_type(hotel["id"], code="ONE", tier_rank=1,
                           physical_inventory=1, base_rate_cents=10000)
    bar = create_rate_plan(hotel["id"], code="BAR", kind="BAR",
                           adjustment_mode="FLAT", adjustment_value=0, no_show_policy="NONE")
    guest = create_guest(hotel["id"])
    get_success_data(api.create_reservation({
        "hotel_id": hotel["id"], "guest_id": guest["id"], "room_type_id": one["id"],
        "rate_plan_id": bar["id"], "arrival_date": "2026-07-01",
        "departure_date": "2026-07-03"}, FDA))
    get_success_data(api.create_reservation({
        "hotel_id": hotel["id"], "guest_id": guest["id"], "room_type_id": one["id"],
        "rate_plan_id": bar["id"], "arrival_date": "2026-07-03",
        "departure_date": "2026-07-05"}, FDA))

    resp = api.create_reservation({
        "hotel_id": hotel["id"], "guest_id": guest["id"], "room_type_id": one["id"],
        "rate_plan_id": bar["id"], "arrival_date": "2026-07-02",
        "departure_date": "2026-07-04"}, FDA)
    validate_error(resp, ApiErrorId.ERR_NO_AVAILABILITY.value)


# ===========================================================================
# Difficulty/resource_temporal_overlap/group_block_cutoff_temporal_window_vs_business_date
# ===========================================================================
def test_group_pickup_allowed_while_within_cutoff_window():
    """PRD §3.2: "pickup is allowed only while the block's `status` is `OPEN` and the
    property's `current_business_date` is on or before the block's `cutoff_date`."

    cutoff 07-01, current_business_date 07-01: a pickup on the boundary day is allowed.

    Design: Difficulty/resource_temporal_overlap/group_block_cutoff_temporal_window_vs_business_date
    """
    hotel = create_hotel(current_business_date="2026-07-01", overbooking_allowance_pct=0.0)
    queen = create_room_type(hotel["id"], code="QUEEN", tier_rank=1,
                             physical_inventory=9, base_rate_cents=15000)
    grp = create_rate_plan(hotel["id"], code="GRP", kind="BAR",
                           adjustment_mode="FLAT", adjustment_value=0, no_show_policy="NONE")
    block = create_group_block(hotel["id"], queen["id"], grp["id"], block_name="Late",
                               arrival_date="2026-07-08", departure_date="2026-07-10",
                               cutoff_date="2026-07-01", blocked_rooms=4)
    guest = create_guest(hotel["id"])
    pickup = api.create_reservation({
        "hotel_id": hotel["id"], "guest_id": guest["id"], "room_type_id": queen["id"],
        "rate_plan_id": grp["id"], "arrival_date": "2026-07-08",
        "departure_date": "2026-07-10", "group_block_id": block["id"],
        "expected_group_block_version": block["version"]}, FDA)
    res1 = validate_success(pickup, expected_status=201)
    assert res1["group_block_id"] == block["id"], res1


def test_group_pickup_after_cutoff_wash_rejected():
    """PRD §3.2: "A pickup attempted after the cutoff has passed — meaning the block is
    already `WASHED` or `CLOSED`, or `current_business_date` is strictly later than
    `cutoff_date` — is rejected with `ERR_BLOCK_CUTOFF_PASSED` (HTTP 409)."
    PRD §3.2: "When the night audit advances `current_business_date` to a value strictly
    greater than a block's `cutoff_date` while the block is still `OPEN`, the block washes:
    its `status` moves `OPEN → WASHED`".

    Design: Difficulty/resource_temporal_overlap/group_block_cutoff_temporal_window_vs_business_date
    """
    hotel = create_hotel(current_business_date="2026-07-01", overbooking_allowance_pct=0.0)
    queen = create_room_type(hotel["id"], code="QUEEN", tier_rank=1,
                             physical_inventory=9, base_rate_cents=15000)
    grp = create_rate_plan(hotel["id"], code="GRP", kind="BAR",
                           adjustment_mode="FLAT", adjustment_value=0, no_show_policy="NONE")
    block = create_group_block(hotel["id"], queen["id"], grp["id"], block_name="Late",
                               arrival_date="2026-07-08", departure_date="2026-07-10",
                               cutoff_date="2026-07-01", blocked_rooms=4)
    guest = create_guest(hotel["id"])
    get_success_data(api.create_reservation({
        "hotel_id": hotel["id"], "guest_id": guest["id"], "room_type_id": queen["id"],
        "rate_plan_id": grp["id"], "arrival_date": "2026-07-08",
        "departure_date": "2026-07-10", "group_block_id": block["id"],
        "expected_group_block_version": block["version"]}, FDA))
    run_one_audit(hotel["id"])  # advances date to 07-02 > cutoff 07-01 -> WASHED

    block_after = validate_success(api.get_group_block(block["id"], RM))
    assert block_after["status"] == "WASHED", block_after
    resp = api.create_reservation({
        "hotel_id": hotel["id"], "guest_id": guest["id"], "room_type_id": queen["id"],
        "rate_plan_id": grp["id"], "arrival_date": "2026-07-08",
        "departure_date": "2026-07-10", "group_block_id": block["id"],
        "expected_group_block_version": block_after["version"]}, FDA)
    validate_error(resp, ApiErrorId.ERR_BLOCK_CUTOFF_PASSED.value)


# ===========================================================================
# Difficulty/compensating_invariant/cancel_releases_inventory_sold_count_conserved
# ===========================================================================
def test_cancel_releases_inventory_sold_count_returns_to_zero():
    """PRD §3.3: "Availability is recomputed for every covered night so the released
    inventory returns to sale".
    PRD §3.3: "The sold count for a night is the number of reservations of that type whose
    stay interval covers the night ... and whose `status` is neither `CANCELLED` nor
    `NO_SHOW`".

    create raises sold_count to 1; cancel returns it to 0 (conserved).

    Design: Difficulty/compensating_invariant/cancel_releases_inventory_sold_count_conserved
    """
    hotel = create_hotel(current_business_date="2026-07-01", overbooking_allowance_pct=0.0)
    std = create_room_type(hotel["id"], code="STD", tier_rank=1,
                           physical_inventory=3, base_rate_cents=10000)
    bar = create_rate_plan(hotel["id"], code="BAR", kind="BAR",
                           adjustment_mode="FLAT", adjustment_value=0, no_show_policy="NONE")
    guest = create_guest(hotel["id"])
    res = get_success_data(api.create_reservation({
        "hotel_id": hotel["id"], "guest_id": guest["id"], "room_type_id": std["id"],
        "rate_plan_id": bar["id"], "arrival_date": "2026-07-01",
        "departure_date": "2026-07-02"}, FDA))
    before = _avail_cell(hotel["id"], std["id"], "2026-07-01", "2026-07-02", "2026-07-01")
    assert before["sold_count"] == 1, before

    validate_success(api.cancel_reservation(res["id"], FDA))
    after = _avail_cell(hotel["id"], std["id"], "2026-07-01", "2026-07-02", "2026-07-01")
    assert after["sold_count"] == 0, after


def test_cancel_on_sold_out_type_readmits_a_new_booking():
    """PRD §3.3: "Availability is recomputed for every covered night so the released
    inventory returns to sale".
    PRD §3.3: "selling the room that brings the sold count up to the sellable count is
    permitted, but the next one is not."

    inv 1: the only room is sold (next create would be rejected); cancelling that
    reservation conserves inventory back to zero so a fresh booking is re-admitted.

    Design: Difficulty/compensating_invariant/cancel_releases_inventory_sold_count_conserved
    """
    hotel = create_hotel(current_business_date="2026-07-01", overbooking_allowance_pct=0.0)
    one = create_room_type(hotel["id"], code="ONE", tier_rank=1,
                           physical_inventory=1, base_rate_cents=10000)
    bar = create_rate_plan(hotel["id"], code="BAR", kind="BAR",
                           adjustment_mode="FLAT", adjustment_value=0, no_show_policy="NONE")
    guest = create_guest(hotel["id"])
    res = get_success_data(api.create_reservation({
        "hotel_id": hotel["id"], "guest_id": guest["id"], "room_type_id": one["id"],
        "rate_plan_id": bar["id"], "arrival_date": "2026-07-01",
        "departure_date": "2026-07-02"}, FDA))
    validate_success(api.cancel_reservation(res["id"], FDA))

    readmit = api.create_reservation({
        "hotel_id": hotel["id"], "guest_id": guest["id"], "room_type_id": one["id"],
        "rate_plan_id": bar["id"], "arrival_date": "2026-07-01",
        "departure_date": "2026-07-02"}, FDA)
    res2 = validate_success(readmit, expected_status=201)
    assert res2["status"] == "HELD", res2


# ===========================================================================
# Difficulty/compensating_invariant/void_incidental_restores_folio_balance_conserved
# ===========================================================================
def test_void_incidental_restores_folio_balance_to_zero():
    """PRD §3.6: "A `FrontDeskAgent` may void a posted line, moving its `status` to
    `VOIDED` so it drops out of every folio sum; voiding carries `expected_folio_version`,
    recomputes the folio totals, and increments the folio's `version`."

    Posting a 2500 CHARGE raises balance to 2500; voiding it drops balance back to 0.

    Design: Difficulty/compensating_invariant/void_incidental_restores_folio_balance_conserved
    """
    b = setup_basic()
    res = get_success_data(api.create_reservation({
        "hotel_id": b["hotel"]["id"], "guest_id": b["guest"]["id"],
        "room_type_id": b["room_type"]["id"], "rate_plan_id": b["rate_plan"]["id"],
        "arrival_date": "2026-07-01", "departure_date": "2026-07-03"}, FDA))
    folio = _folio(b["hotel"]["id"], res["id"])
    inc = get_success_data(api.create_incidental({
        "hotel_id": b["hotel"]["id"], "folio_id": folio["id"], "kind": "CHARGE",
        "description": "Parking", "amount_cents": 2500}, FDA))
    folio_charged = validate_success(api.get_folio(folio["id"], FDA))
    assert folio_charged["balance_cents"] == 2500, folio_charged

    voided = validate_success(api.void_incidental(
        inc["id"], {"expected_folio_version": folio_charged["version"]}, FDA))
    assert voided["status"] == "VOIDED", voided
    folio_after = validate_success(api.get_folio(folio["id"], FDA))
    assert folio_after["balance_cents"] == 0, folio_after


def test_void_leaves_surviving_line_in_folio_balance():
    """PRD §3.6: "Lines in `VOIDED` status are excluded from every one of these sums."
    PRD §3.6: "Its `incidentals_cents` is the sum of the `amount_cents` of all `POSTED`
    agent-posted incidentals".

    Two CHARGE lines (2500 + 1000 -> 3500); voiding only the 2500 line conserves the
    balance down to exactly the surviving 1000 line, not to zero — the voided line drops
    out while the POSTED line remains.

    Design: Difficulty/compensating_invariant/void_incidental_restores_folio_balance_conserved
    """
    b = setup_basic()
    res = get_success_data(api.create_reservation({
        "hotel_id": b["hotel"]["id"], "guest_id": b["guest"]["id"],
        "room_type_id": b["room_type"]["id"], "rate_plan_id": b["rate_plan"]["id"],
        "arrival_date": "2026-07-01", "departure_date": "2026-07-03"}, FDA))
    folio = _folio(b["hotel"]["id"], res["id"])
    inc1 = get_success_data(api.create_incidental({
        "hotel_id": b["hotel"]["id"], "folio_id": folio["id"], "kind": "CHARGE",
        "description": "Parking", "amount_cents": 2500}, FDA))
    get_success_data(api.create_incidental({
        "hotel_id": b["hotel"]["id"], "folio_id": folio["id"], "kind": "CHARGE",
        "description": "Minibar", "amount_cents": 1000}, FDA))
    folio_two = validate_success(api.get_folio(folio["id"], FDA))
    assert folio_two["balance_cents"] == 3500, folio_two

    validate_success(api.void_incidental(
        inc1["id"], {"expected_folio_version": folio_two["version"]}, FDA))
    folio_after = validate_success(api.get_folio(folio["id"], FDA))
    assert folio_after["balance_cents"] == 1000, folio_after


# ===========================================================================
# Corner/cross_cutting_complexity_layers/rate_threshold_overbooking_allowance_raises_sellable
# ===========================================================================
def test_overbooking_allowance_raises_sellable_count():
    """PRD §3.3: "the sellable count is the floor of the room type's `physical_inventory`
    multiplied by one plus the property's `overbooking_allowance_pct`, minus the number of
    `OUT_OF_ORDER` rooms of that type."

    inv 4, overbooking 0.25 (the PRD maximum) -> sellable floor(4*1.25)=5; a 5th
    reservation (beyond physical inventory) succeeds because the allowance raised the
    sellable count above physical capacity.

    Design: Corner/cross_cutting_complexity_layers/rate_threshold_overbooking_allowance_raises_sellable
    """
    hotel = create_hotel(current_business_date="2026-07-01", overbooking_allowance_pct=0.25)
    std = create_room_type(hotel["id"], code="STD", tier_rank=1,
                           physical_inventory=4, base_rate_cents=10000)
    bar = create_rate_plan(hotel["id"], code="BAR", kind="BAR",
                           adjustment_mode="FLAT", adjustment_value=0, no_show_policy="NONE")
    guest = create_guest(hotel["id"])
    for _ in range(4):
        get_success_data(api.create_reservation({
            "hotel_id": hotel["id"], "guest_id": guest["id"], "room_type_id": std["id"],
            "rate_plan_id": bar["id"], "arrival_date": "2026-07-01",
            "departure_date": "2026-07-02"}, FDA))
    fifth = api.create_reservation({
        "hotel_id": hotel["id"], "guest_id": guest["id"], "room_type_id": std["id"],
        "rate_plan_id": bar["id"], "arrival_date": "2026-07-01",
        "departure_date": "2026-07-02"}, FDA)
    validate_success(fifth, expected_status=201)

    cell = _avail_cell(hotel["id"], std["id"], "2026-07-01", "2026-07-02", "2026-07-01")
    assert cell["sellable_count"] == 5, cell
    assert cell["sold_count"] == 5, cell


# ===========================================================================
# Corner/cross_cutting_complexity_layers/cascade_block_wash_partial_pickup_washes_remainder
# ===========================================================================
def test_block_wash_sets_washed_rooms_to_remainder():
    """PRD §3.2: "its `washed_rooms` is set to the `blocked_rooms` minus the
    `picked_up_rooms`, or 0 if that difference would be negative."

    Block blocked 4 with 1 pickup; after the audit washes it, washed_rooms == 3, status WASHED.

    Design: Corner/cross_cutting_complexity_layers/cascade_block_wash_partial_pickup_washes_remainder
    """
    hotel = create_hotel(current_business_date="2026-07-01", overbooking_allowance_pct=0.0)
    queen = create_room_type(hotel["id"], code="QUEEN", tier_rank=1,
                             physical_inventory=9, base_rate_cents=15000)
    grp = create_rate_plan(hotel["id"], code="GRP", kind="BAR",
                           adjustment_mode="FLAT", adjustment_value=0, no_show_policy="NONE")
    block = create_group_block(hotel["id"], queen["id"], grp["id"], block_name="Conf",
                               arrival_date="2026-07-08", departure_date="2026-07-10",
                               cutoff_date="2026-07-01", blocked_rooms=4)
    guest = create_guest(hotel["id"])
    get_success_data(api.create_reservation({
        "hotel_id": hotel["id"], "guest_id": guest["id"], "room_type_id": queen["id"],
        "rate_plan_id": grp["id"], "arrival_date": "2026-07-08",
        "departure_date": "2026-07-10", "group_block_id": block["id"],
        "expected_group_block_version": block["version"]}, FDA))
    run_one_audit(hotel["id"])

    block_after = validate_success(api.get_group_block(block["id"], RM))
    assert block_after["status"] == "WASHED", block_after
    assert block_after["picked_up_rooms"] == 1, block_after
    assert block_after["washed_rooms"] == 3, block_after


# ===========================================================================
# Corner/consistency_model/immediate_consistency_availability_reflects_create_in_same_flow
# ===========================================================================
def test_availability_reflects_reservation_immediately():
    """PRD §2.9: "Computed fields such as a folio's `balance_cents` or a corporate
    account's `outstanding_balance_cents` are recomputed synchronously inside the mutating
    request, never deferred."
    PRD §3.3: "Creating a reservation ... recomputes availability for the covered dates."

    GET availability right after a create shows sold_count == 1 (inv 3 -> sellable 3).

    Design: Corner/consistency_model/immediate_consistency_availability_reflects_create_in_same_flow
    """
    hotel = create_hotel(current_business_date="2026-07-01", overbooking_allowance_pct=0.0)
    std = create_room_type(hotel["id"], code="STD", tier_rank=1,
                           physical_inventory=3, base_rate_cents=10000)
    bar = create_rate_plan(hotel["id"], code="BAR", kind="BAR",
                           adjustment_mode="FLAT", adjustment_value=0, no_show_policy="NONE")
    guest = create_guest(hotel["id"])
    get_success_data(api.create_reservation({
        "hotel_id": hotel["id"], "guest_id": guest["id"], "room_type_id": std["id"],
        "rate_plan_id": bar["id"], "arrival_date": "2026-07-01",
        "departure_date": "2026-07-02"}, FDA))

    cell = _avail_cell(hotel["id"], std["id"], "2026-07-01", "2026-07-02", "2026-07-01")
    assert cell["sold_count"] == 1, cell
    assert cell["sellable_count"] == 3, cell
