"""Reading before writing, and seeing the whole consequence in the answer itself."""

from test_helpers import (
    FLOOR_OPERATOR,
    FLOOR_OPERATOR_ID,
    GALLERY_MANAGER,
    SCORES_GRADE_A,
    ApiErrorId,
    api_client,
    complete_delivery,
    create_buyer,
    create_consignor,
    create_crew,
    create_item,
    create_zone,
    fetch_consignor,
    fetch_consignor_ledger,
    fetch_item,
    fetch_sale,
    fetch_zone,
    get_success_data,
    payout_payload,
    place_item,
    receive_item,
    sale_payload,
    schedule_delivery,
    screen_item,
    setup_consignor_with_active_agreement,
    take_custody,
    total_count,
    validate_error,
    validate_success,
)

ONE_STEP = [(1, 0, 0.00, 0)]

BUREAU = {
    "title": "Bureau",
    "category": "CASEGOOD",
    "declared_value_cents": 60_000,
    "photo_count": 5,
    "volume_cuft": 12,
    "footprint_sqft": 10,
}


def test_a_stale_expected_consignor_version_is_refused():
    """The version gate outranks both fiscal gates, so an empty ledger still answers 412.

    PRD 2.7: "If `Consignor.version` has advanced since that read — because another writer
    booked a sale credit, a pickup surcharge debit or a damage chargeback that legitimately
    supersedes the earlier balance — the request is rejected with
    `ERR_STALE_CONSIGNOR_VERSION` (HTTP 412) and no ledger entry is minted."

    PRD 2.9: "`expected_consignor_version` equals the stored `Consignor.version`, on payout
    disbursement — otherwise `ERR_STALE_CONSIGNOR_VERSION` (412)."

    PRD 2.4: "`version`, an integer that begins at 1 on creation and increments by exactly 1
    on each mutation that actually changes a stored field."

    PRD 3.9: "The balance must be strictly greater than zero, otherwise
    `ERR_INSUFFICIENT_BALANCE`, and it must then be at least the 2,000-cent payout minimum,
    otherwise `ERR_PAYOUT_BELOW_MINIMUM`; a consignor may still be paid out while their
    `escheat_state` is `DORMANT`, since dormancy is a warning rather than a freeze."

    Design: Corner/cross_cutting_complexity_layers/a_stale_expected_consignor_version_is_refused
    """
    alpha = create_consignor(
        display_name="Alpha", floor_number=1, has_elevator=False
    )
    observed = fetch_consignor(alpha["id"])
    assert observed["version"] == 1, (
        f"Expected a fresh record at version 1, got {observed['version']}"
    )

    moved = api_client.patch_consignor(
        alpha["id"], {"floor_number": 3, "has_elevator": True}, GALLERY_MANAGER
    )
    validate_success(moved, 200)

    stale = api_client.create_payout(
        alpha["id"], payout_payload(observed["version"]), GALLERY_MANAGER
    )
    validate_error(stale, ApiErrorId.ERR_STALE_CONSIGNOR_VERSION, 412)

    current = fetch_consignor(alpha["id"])
    assert current["version"] == 2, (
        f"Expected the address correction to have moved the counter, "
        f"got {current['version']}"
    )
    assert current["floor_number"] == 3, (
        f"Expected the third floor recorded, got {current['floor_number']}"
    )
    assert current["has_elevator"] is True, (
        f"Expected the elevator recorded, got {current['has_elevator']}"
    )
    assert current["unclaimed_balance_cents"] == 0, (
        f"Expected an untouched balance, got {current['unclaimed_balance_cents']}"
    )

    ledger = api_client.list_consignor_ledger_entries(
        alpha["id"], GALLERY_MANAGER, params={"limit": 100}
    )
    assert total_count(ledger) == 0, (
        f"Expected the refused payout to mint nothing, got {total_count(ledger)}"
    )

    fresh = api_client.create_payout(
        alpha["id"], payout_payload(current["version"]), GALLERY_MANAGER
    )
    validate_error(fresh, ApiErrorId.ERR_INSUFFICIENT_BALANCE, 409)
    assert total_count(
        api_client.list_consignor_ledger_entries(
            alpha["id"], GALLERY_MANAGER, params={"limit": 100}
        )
    ) == 0, "Expected the second refusal to mint nothing either"


def test_the_sale_response_already_carries_the_split_and_the_freed_floor_space():
    """Nothing is deferred: the split arrives in the 201, and the footage waits for the van.

    PRD 3.8: "`consignor_share_cents` is then `sale_price_cents` multiplied by
    `split_pct_applied`, rounded half up to a whole number of cents, and
    `gallery_share_cents` is the exact remainder of `sale_price_cents` after the consignor's
    share is taken out."

    PRD 3.8: "Its `placement_zone_id` is deliberately **retained** until the piece
    physically leaves on a delivery, so a sold-but-undelivered piece keeps counting toward
    its zone's `occupied_sqft`."

    PRD 3.8: "Second, because the sale exists, one `SALE_CREDIT` ledger entry of positive
    `consignor_share_cents` is minted against the consignor."

    PRD 3.8: "and `placement_zone_id` is finally cleared to null with the former zone's
    `occupied_sqft` and `utilization_state` recomputed, freeing the square feet the sold
    piece had still been holding."

    Design: Corner/consistency_model/the_sale_response_already_carries_the_split_and_the_freed_floor_space
    """
    world = setup_consignor_with_active_agreement(schedule_steps=ONE_STEP)
    consignor_id = world["consignor"]["id"]
    bureau = create_item(world["agreement"]["id"], **BUREAU)
    screen_item(bureau["id"], scores=SCORES_GRADE_A)
    take_custody(consignor_id, [bureau["id"]])
    receive_item(bureau["id"], scores=SCORES_GRADE_A)
    zone = create_zone(name="Front A", zone_type="SHOWROOM_FRONT", capacity_sqft=200)
    place_item(bureau["id"], zone["id"], tag_code="SHOWROOM-1")
    buyer = create_buyer(display_name="Nora Vance", floor_number=2, has_elevator=False)

    assert fetch_consignor(consignor_id)["unclaimed_balance_cents"] == -17_000, (
        f"Expected the collection surcharge alone, "
        f"got {fetch_consignor(consignor_id)['unclaimed_balance_cents']}"
    )
    assert fetch_zone(zone["id"])["occupied_sqft"] == 10, (
        f"Expected ten square feet charged, "
        f"got {fetch_zone(zone['id'])['occupied_sqft']}"
    )

    response = api_client.create_sale(
        sale_payload(bureau["id"], buyer["id"], 51_000), FLOOR_OPERATOR
    )
    validate_success(response, 201)
    rung = get_success_data(response)
    assert rung["split_pct_applied"] == 0.60, (
        f"Expected the casegood base plus the mid-band bonus, "
        f"got {rung['split_pct_applied']}"
    )
    assert rung["consignor_share_cents"] == 30_600, (
        f"Expected 51000 at sixty hundredths, got {rung['consignor_share_cents']}"
    )
    assert rung["gallery_share_cents"] == 20_400, (
        f"Expected the exact remainder, got {rung['gallery_share_cents']}"
    )
    assert rung["consignor_share_cents"] + rung["gallery_share_cents"] == 51_000, (
        "The two shares must re-add to the sale price to the cent"
    )
    assert rung["status"] == "COMPLETED", (
        f"Expected COMPLETED, got {rung['status']}"
    )
    assert rung["markdown_sequence_at_sale"] == 1, (
        f"Expected the opening step recorded, "
        f"got {rung['markdown_sequence_at_sale']}"
    )
    assert rung["refund_cents"] == 0, (
        f"Expected no refund yet, got {rung['refund_cents']}"
    )
    assert rung["sold_by_user_id"] == FLOOR_OPERATOR_ID, (
        f"Expected the operator at the register recorded, "
        f"got {rung['sold_by_user_id']}"
    )

    assert fetch_consignor(consignor_id)["unclaimed_balance_cents"] == 13_600, (
        f"Expected 30600 against 17000 in the very next read, "
        f"got {fetch_consignor(consignor_id)['unclaimed_balance_cents']}"
    )
    entries = fetch_consignor_ledger(consignor_id)
    assert len(entries) == 2, (
        f"Expected the surcharge and the credit, "
        f"got {[e['entry_type'] for e in entries]}"
    )
    assert entries[1]["entry_type"] == "SALE_CREDIT", (
        f"Expected a SALE_CREDIT, got {entries[1]['entry_type']}"
    )
    assert entries[1]["amount_cents"] == 30_600, (
        f"Expected 30600, got {entries[1]['amount_cents']}"
    )
    assert entries[1]["balance_after_cents"] == 13_600, (
        f"Expected the running balance already carried on the entry, "
        f"got {entries[1]['balance_after_cents']}"
    )

    sold = fetch_item(bureau["id"])
    assert sold["lifecycle_state"] == "SOLD", (
        f"Expected SOLD, got {sold['lifecycle_state']}"
    )
    assert sold["inventory_state"] == "IN_CUSTODY", (
        f"Expected the piece still in the building, got {sold['inventory_state']}"
    )
    assert sold["placement_zone_id"] == zone["id"], (
        f"Expected the zone retained until the van comes, "
        f"got {sold['placement_zone_id']}"
    )
    still_charged = fetch_zone(zone["id"])
    assert still_charged["occupied_sqft"] == 10, (
        f"Expected the sold piece still holding its footage, "
        f"got {still_charged['occupied_sqft']}"
    )
    assert still_charged["utilization_state"] == "NORMAL", (
        f"Expected NORMAL at 10 of 200, got {still_charged['utilization_state']}"
    )

    stored = fetch_sale(rung["id"])
    assert (
        stored["split_pct_applied"],
        stored["consignor_share_cents"],
        stored["gallery_share_cents"],
    ) == (0.60, 30_600, 20_400), (
        f"Expected the stored row to match the 201 body, got "
        f"{stored['split_pct_applied']}, {stored['consignor_share_cents']}, "
        f"{stored['gallery_share_cents']}"
    )

    crew = create_crew(name="WG-1", max_concurrent_jobs=2)
    order = schedule_delivery(rung["id"], crew["id"])
    delivered = complete_delivery(order["id"], outcome="DELIVERED")
    assert delivered["status"] == "DELIVERED", (
        f"Expected the order delivered, got {delivered['status']}"
    )

    released = fetch_zone(zone["id"])
    assert released["occupied_sqft"] == 0, (
        f"Expected the square feet freed once the piece left, "
        f"got {released['occupied_sqft']}"
    )
    gone = fetch_item(bureau["id"])
    assert gone["placement_zone_id"] is None, (
        f"Expected the zone finally cleared, got {gone['placement_zone_id']}"
    )
    assert gone["inventory_state"] == "RELEASED", (
        f"Expected RELEASED, got {gone['inventory_state']}"
    )
