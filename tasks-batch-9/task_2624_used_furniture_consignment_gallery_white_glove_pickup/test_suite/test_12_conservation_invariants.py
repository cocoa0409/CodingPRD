"""Two quantities that must come back to where they started: money, and square feet."""

from test_helpers import (
    GALLERY_MANAGER,
    SCORES_GRADE_A,
    SCORES_GRADE_B,
    STD_SCHEDULE_STEPS,
    ApiErrorId,
    api_client,
    create_buyer,
    create_crew,
    create_item,
    create_zone,
    fetch_consignor,
    fetch_consignor_ledger,
    fetch_delivery_order,
    fetch_item,
    fetch_item_ledger,
    fetch_sale,
    fetch_zone,
    flag_inventory,
    place_item,
    receive_item,
    reverse_sale,
    schedule_delivery,
    screen_item,
    sell_item,
    setup_consignor_with_active_agreement,
    take_custody,
    validate_error,
    write_off_item,
    write_off_payload,
)

TWO_STEP_SCHEDULE = STD_SCHEDULE_STEPS[:2]

BRIDGEWATER_SOFA = {
    "title": "Bridgewater sofa",
    "category": "SOFA",
    "declared_value_cents": 189_950,
    "photo_count": 5,
    "volume_cuft": 65,
    "footprint_sqft": 24,
}


def _a_sofa_sold_and_booked_for_delivery():
    """One third-floor collection, one sale, one delivery order still to run."""
    world = setup_consignor_with_active_agreement(
        schedule_steps=TWO_STEP_SCHEDULE,
        consignor_overrides={
            "floor_number": 3,
            "has_elevator": False,
            "payout_method": "ACH",
        },
    )
    sofa = create_item(world["agreement"]["id"], **BRIDGEWATER_SOFA)
    screen_item(sofa["id"], scores=SCORES_GRADE_B)
    take_custody(
        world["consignor"]["id"],
        [sofa["id"]],
        window_start="2026-08-01T07:00:00Z",
        window_end="2026-08-01T09:00:00Z",
        actual_stair_flights=2,
    )
    receive_item(sofa["id"], scores=SCORES_GRADE_B)
    world["zone"] = create_zone(
        name="Front A", zone_type="SHOWROOM_FRONT", capacity_sqft=200
    )
    world["sofa"] = place_item(sofa["id"], world["zone"]["id"], tag_code="T-1401")

    world["buyer"] = create_buyer(floor_number=2, has_elevator=False)
    world["sale"] = sell_item(sofa["id"], world["buyer"]["id"], 126_317)
    world["crew"] = create_crew(name="Crew 1", max_concurrent_jobs=2)
    world["order"] = schedule_delivery(world["sale"]["id"], world["crew"]["id"])
    return world


def test_reversing_a_sale_returns_the_balance_to_its_pre_sale_figure():
    """The credit and its debit cancel to the cent, and the lifetime total does not.

    PRD 3.8: "Exactly one `SALE_REVERSAL_DEBIT` entry is minted, carrying the negation
    of `consignor_share_cents`, so the sale's two ledger entries for that piece sum to
    exactly zero and the consignor's `unclaimed_balance_cents` returns precisely to its
    pre-sale value"

    PRD 2.11: "`lifetime_credits_cents` is the sum of `amount_cents` restricted to
    entries whose amount is positive, so it never decreases."

    Design: Difficulty/compensating_invariant/sale_reversal_returns_the_ledger_to_its_pre_sale_balance
    """
    world = _a_sofa_sold_and_booked_for_delivery()
    consignor_id = world["consignor"]["id"]

    before = fetch_consignor(consignor_id)
    assert before["unclaimed_balance_cents"] == 25_474, (
        f"Expected 69474 of credit against 44000 of surcharge, "
        f"got {before['unclaimed_balance_cents']}"
    )

    reverse_sale(world["sale"]["id"])

    entries = fetch_consignor_ledger(consignor_id)
    assert [e["amount_cents"] for e in entries] == [-44_000, 69_474, -69_474], (
        f"Expected an append-only three-entry history, got "
        f"{[e['amount_cents'] for e in entries]}"
    )
    reversals = [e for e in entries if e["entry_type"] == "SALE_REVERSAL_DEBIT"]
    assert len(reversals) == 1, (
        f"Expected exactly one reversal debit, got {len(reversals)}"
    )
    assert reversals[0]["amount_cents"] == -69_474, (
        f"Expected -69474, got {reversals[0]['amount_cents']}"
    )
    assert reversals[0]["balance_after_cents"] == -44_000, (
        f"Expected the pre-sale -44000 restored, "
        f"got {reversals[0]['balance_after_cents']}"
    )
    credit = [e for e in entries if e["entry_type"] == "SALE_CREDIT"][0]
    assert credit["amount_cents"] + reversals[0]["amount_cents"] == 0, (
        "The credit and its reversal must sum to zero"
    )

    after = fetch_consignor(consignor_id)
    assert after["unclaimed_balance_cents"] == -44_000, (
        f"Expected -44000, got {after['unclaimed_balance_cents']}"
    )
    assert after["lifetime_credits_cents"] == 69_474, (
        f"Expected the lifetime credit total to survive the reversal, "
        f"got {after['lifetime_credits_cents']}"
    )


def test_the_reversal_unwinds_the_delivery_but_cannot_be_applied_twice():
    """The piece goes back on the floor, the crew is released, and the sale is spent.

    PRD 3.8: "Any delivery order still in `SCHEDULED` against that sale is moved
    `SCHEDULED → CANCELLED`, which releases the crew window so it stops participating
    in concurrency checks."

    PRD 2.9: "The sale's `status` is `COMPLETED`, meaning neither `SETTLED` nor
    `REVERSED`, on sale reversal and delivery-order creation — otherwise
    `ERR_SALE_ALREADY_REVERSED` (409)."

    Design: Difficulty/compensating_invariant/sale_reversal_returns_the_ledger_to_its_pre_sale_balance
    """
    world = _a_sofa_sold_and_booked_for_delivery()
    sale_id = world["sale"]["id"]
    zone_id = world["zone"]["id"]

    occupied_before = fetch_zone(zone_id)["occupied_sqft"]
    reverse_sale(sale_id)

    sale = fetch_sale(sale_id)
    assert sale["status"] == "REVERSED", (
        f"Expected REVERSED, got {sale['status']}"
    )
    assert sale["reversed_at"].startswith("2026-08-01T00:00:00"), (
        f"Expected the reversal stamped from the clock, got {sale['reversed_at']}"
    )
    assert sale["consignor_share_cents"] == 69_474, (
        f"Expected the recorded share retained rather than zeroed, "
        f"got {sale['consignor_share_cents']}"
    )

    sofa = fetch_item(world["sofa"]["id"])
    assert sofa["lifecycle_state"] == "ON_FLOOR", (
        f"Expected the sofa back on the floor, got {sofa['lifecycle_state']}"
    )
    assert sofa["markdown_sequence"] == 1, (
        f"Expected the first step still in force, got {sofa['markdown_sequence']}"
    )
    assert sofa["placement_zone_id"] == zone_id, (
        f"Expected the zone it never left, got {sofa['placement_zone_id']}"
    )
    assert sofa["current_price_cents"] == 126_317, (
        f"Expected the ticket price kept, got {sofa['current_price_cents']}"
    )

    order = fetch_delivery_order(world["order"]["id"])
    assert order["status"] == "CANCELLED", (
        f"Expected the delivery order cancelled, got {order['status']}"
    )

    zone = fetch_zone(zone_id)
    assert zone["occupied_sqft"] == occupied_before == 24, (
        f"Expected 24 square feet before and after, got {zone['occupied_sqft']}"
    )

    second = api_client.reverse_sale(sale_id, GALLERY_MANAGER)
    validate_error(second, ApiErrorId.ERR_SALE_ALREADY_REVERSED, 409)
    entries = fetch_consignor_ledger(world["consignor"]["id"])
    assert len(entries) == 3, (
        f"Expected no fourth entry from the second attempt, got {len(entries)}"
    )


LAWSON_SOFA = {
    "title": "Lawson sofa",
    "category": "SOFA",
    "declared_value_cents": 189_950,
    "photo_count": 5,
    "volume_cuft": 65,
    "footprint_sqft": 24,
}
TEAK_HIGHBOY = {
    "title": "Teak highboy",
    "category": "CASEGOOD",
    "declared_value_cents": 60_000,
    "photo_count": 4,
    "volume_cuft": 20,
    "footprint_sqft": 18,
}
CANE_NIGHTSTAND = {
    "title": "Cane nightstand",
    "category": "CASEGOOD",
    "declared_value_cents": 20_000,
    "photo_count": 3,
    "volume_cuft": 13,
    "footprint_sqft": 12,
}


def _a_nightstand_reported_missing_beside_two_pieces_that_are_not():
    """Three placed pieces; the nightstand alone has been flagged MISSING."""
    world = setup_consignor_with_active_agreement(
        schedule_steps=TWO_STEP_SCHEDULE,
        consignor_overrides={"payout_method": "ACH"},
    )
    agreement_id = world["agreement"]["id"]

    sofa = create_item(agreement_id, **LAWSON_SOFA)
    highboy = create_item(agreement_id, **TEAK_HIGHBOY)
    nightstand = create_item(agreement_id, **CANE_NIGHTSTAND)
    screen_item(sofa["id"], scores=SCORES_GRADE_B)
    screen_item(highboy["id"], scores=SCORES_GRADE_A)
    screen_item(nightstand["id"], scores=SCORES_GRADE_A)

    take_custody(
        world["consignor"]["id"],
        [sofa["id"], highboy["id"], nightstand["id"]],
        window_start="2026-08-01T07:00:00Z",
        window_end="2026-08-01T10:00:00Z",
    )
    receive_item(sofa["id"], scores=SCORES_GRADE_B)
    receive_item(highboy["id"], scores=SCORES_GRADE_A)
    receive_item(nightstand["id"], scores=SCORES_GRADE_A)

    world["zone"] = create_zone(
        name="Front A", zone_type="SHOWROOM_FRONT", capacity_sqft=200
    )
    zone_id = world["zone"]["id"]
    world["sofa"] = place_item(sofa["id"], zone_id, tag_code="T-1501")
    world["highboy"] = place_item(highboy["id"], zone_id, tag_code="T-1502")
    world["nightstand"] = place_item(nightstand["id"], zone_id, tag_code="T-1503")

    flag_inventory(nightstand["id"], "MISSING")
    return world


def test_a_recovered_write_off_unwinds_its_own_credit_to_the_cent():
    """The credit and the recovery debit cancel, and the lifetime total keeps both feet.

    PRD 3.9: "one `SHRINKAGE_CREDIT` entry of the same sixty-percent-of-current-price
    amount is minted, the consignor's `unclaimed_balance_cents` and
    `lifetime_credits_cents` are recomputed with `last_activity_at` stamped from the
    clock"

    PRD 3.9: "one `SHRINKAGE_RECOVERY_DEBIT` ledger entry equal to the exact negation of
    that piece's earlier `SHRINKAGE_CREDIT` is minted to unwind the credit, the
    consignor's `unclaimed_balance_cents` is recomputed"

    PRD 2.11: "`lifetime_credits_cents` is the sum of `amount_cents` restricted to
    entries whose amount is positive, so it never decreases."

    Design: Difficulty/compensating_invariant/write_off_then_recovery_and_replacement_restores_zone_square_footage
    """
    world = _a_nightstand_reported_missing_beside_two_pieces_that_are_not()
    consignor_id = world["consignor"]["id"]
    nightstand_id = world["nightstand"]["id"]

    write_off_item(nightstand_id)

    credited = fetch_consignor(consignor_id)
    assert credited["unclaimed_balance_cents"] == -32_300, (
        f"Expected 10200 of credit against 42500 of surcharge, "
        f"got {credited['unclaimed_balance_cents']}"
    )

    flag_inventory(nightstand_id, "RECOVERED")

    entries = fetch_consignor_ledger(consignor_id)
    assert [e["amount_cents"] for e in entries] == [-42_500, 10_200, -10_200], (
        f"Expected an append-only three-entry history, got "
        f"{[e['amount_cents'] for e in entries]}"
    )
    assert [e["entry_type"] for e in entries] == [
        "PICKUP_SURCHARGE_DEBIT",
        "SHRINKAGE_CREDIT",
        "SHRINKAGE_RECOVERY_DEBIT",
    ], f"Expected the three entry types in order, got {[e['entry_type'] for e in entries]}"
    assert entries[1]["balance_after_cents"] == -32_300, (
        f"Expected -32300 after the credit, got {entries[1]['balance_after_cents']}"
    )
    assert entries[2]["balance_after_cents"] == -42_500, (
        f"Expected the pre-write-off -42500 restored, "
        f"got {entries[2]['balance_after_cents']}"
    )
    assert entries[1]["amount_cents"] + entries[2]["amount_cents"] == 0, (
        "The credit and its recovery debit must sum to zero"
    )

    after = fetch_consignor(consignor_id)
    assert after["unclaimed_balance_cents"] == -42_500, (
        f"Expected -42500, got {after['unclaimed_balance_cents']}"
    )
    assert after["lifetime_credits_cents"] == 10_200, (
        f"Expected the lifetime credit total to survive the unwind, "
        f"got {after['lifetime_credits_cents']}"
    )

    item_entries = fetch_item_ledger(nightstand_id)
    assert len(item_entries) == 2, (
        f"Expected the credit and its unwind against the piece, "
        f"got {[e['entry_type'] for e in item_entries]}"
    )


def test_the_zone_gives_up_twelve_square_feet_and_takes_them_back_on_re_placement():
    """Mislaid keeps the footage, written off frees it, re-placement consumes it again.

    PRD 2.10: "`occupied_sqft` is the exact integer sum of `footprint_sqft` over every
    `ConsignmentItem` whose `placement_zone_id` names that zone"

    PRD 3.9: "the piece keeps counting toward its zone's `occupied_sqft` until the loss
    is actually booked"

    PRD 3.9: "the merchandising dimension moves `WRITTEN_OFF → AWAITING_PLACEMENT` so
    the piece must be placed and tagged again from scratch, `tag_code` is cleared to null
    to force that re-tagging"

    Design: Difficulty/compensating_invariant/write_off_then_recovery_and_replacement_restores_zone_square_footage
    """
    world = _a_nightstand_reported_missing_beside_two_pieces_that_are_not()
    zone_id = world["zone"]["id"]
    nightstand_id = world["nightstand"]["id"]

    mislaid = fetch_zone(zone_id)
    assert mislaid["occupied_sqft"] == 54, (
        f"Expected the mislaid nightstand to keep its 12 square feet, "
        f"got {mislaid['occupied_sqft']}"
    )
    assert mislaid["utilization_state"] == "NORMAL", (
        f"Expected NORMAL at 54 of 200, got {mislaid['utilization_state']}"
    )

    write_off_item(nightstand_id)

    booked = fetch_zone(zone_id)
    assert booked["occupied_sqft"] == 42, (
        f"Expected 24 + 18 once the loss is booked, got {booked['occupied_sqft']}"
    )
    written_off = fetch_item(nightstand_id)
    assert written_off["inventory_state"] == "WRITTEN_OFF_INV", (
        f"Expected WRITTEN_OFF_INV, got {written_off['inventory_state']}"
    )
    assert written_off["lifecycle_state"] == "WRITTEN_OFF", (
        f"Expected WRITTEN_OFF, got {written_off['lifecycle_state']}"
    )
    assert written_off["placement_zone_id"] is None, (
        f"Expected the zone cleared, got {written_off['placement_zone_id']}"
    )

    flag_inventory(nightstand_id, "RECOVERED")

    recovered = fetch_item(nightstand_id)
    assert recovered["inventory_state"] == "IN_CUSTODY", (
        f"Expected IN_CUSTODY, got {recovered['inventory_state']}"
    )
    assert recovered["lifecycle_state"] == "AWAITING_PLACEMENT", (
        f"Expected the piece back at AWAITING_PLACEMENT, "
        f"got {recovered['lifecycle_state']}"
    )
    assert recovered["tag_code"] is None, (
        f"Expected the tag cleared to force re-tagging, got {recovered['tag_code']}"
    )
    unplaced = fetch_zone(zone_id)
    assert unplaced["occupied_sqft"] == 42, (
        f"Expected 42 while the recovered piece is unplaced, "
        f"got {unplaced['occupied_sqft']}"
    )

    replaced = place_item(nightstand_id, zone_id, tag_code="T-1503R")
    assert replaced["lifecycle_state"] == "ON_FLOOR", (
        f"Expected ON_FLOOR after re-placement, got {replaced['lifecycle_state']}"
    )
    assert replaced["tag_code"] == "T-1503R", (
        f"Expected the fresh tag, got {replaced['tag_code']}"
    )

    restored = fetch_zone(zone_id)
    assert restored["occupied_sqft"] == 54, (
        f"Expected the original 54 square feet back, got {restored['occupied_sqft']}"
    )
    assert restored["utilization_state"] == "NORMAL", (
        f"Expected NORMAL again, got {restored['utilization_state']}"
    )

    for name, footprint in (("sofa", 24), ("highboy", 18)):
        piece = fetch_item(world[name]["id"])
        assert piece["inventory_state"] == "IN_CUSTODY", (
            f"Expected the {name} untouched by the excursion, "
            f"got {piece['inventory_state']}"
        )
        assert piece["placement_zone_id"] == zone_id, (
            f"Expected the {name} still holding its {footprint} square feet, "
            f"got {piece['placement_zone_id']}"
        )


def test_replaying_the_write_off_on_a_stale_version_is_refused_before_any_state_check():
    """The version guard answers first, so the replay mints nothing.

    PRD 2.9: "`expected_item_version` equals the stored `ConsignmentItem.version`, on
    single-item write-off — otherwise `ERR_STALE_ITEM_VERSION` (412)."

    PRD 3.9: "Either flag increments the piece's `version` by 1"

    Design: Difficulty/compensating_invariant/write_off_then_recovery_and_replacement_restores_zone_square_footage
    """
    world = _a_nightstand_reported_missing_beside_two_pieces_that_are_not()
    zone_id = world["zone"]["id"]
    nightstand_id = world["nightstand"]["id"]

    stale_version = fetch_item(nightstand_id)["version"]
    write_off_item(nightstand_id, expected_item_version=stale_version)
    flag_inventory(nightstand_id, "RECOVERED")
    place_item(nightstand_id, zone_id, tag_code="T-1503R")

    current = fetch_item(nightstand_id)
    assert current["version"] > stale_version, (
        f"Expected the version to have moved past {stale_version}, "
        f"got {current['version']}"
    )

    replay = api_client.write_off_item(
        nightstand_id, write_off_payload(stale_version), GALLERY_MANAGER
    )
    validate_error(replay, ApiErrorId.ERR_STALE_ITEM_VERSION, 412)

    entries = fetch_consignor_ledger(world["consignor"]["id"])
    assert [e["amount_cents"] for e in entries] == [-42_500, 10_200, -10_200], (
        f"Expected the refused replay to mint nothing, got "
        f"{[e['amount_cents'] for e in entries]}"
    )
    after = fetch_item(nightstand_id)
    assert after["version"] == current["version"], (
        f"Expected version {current['version']} unchanged by the refusal, "
        f"got {after['version']}"
    )
    assert after["inventory_state"] == "IN_CUSTODY", (
        f"Expected the piece to stay IN_CUSTODY, got {after['inventory_state']}"
    )
    assert fetch_zone(zone_id)["occupied_sqft"] == 54, (
        f"Expected 54 square feet held, got {fetch_zone(zone_id)['occupied_sqft']}"
    )
