"""The suspension floor, and the two gates a payout has to clear in order."""

from test_helpers import (
    GALLERY_MANAGER,
    INTAKE_APPRAISER,
    SCORES_GRADE_A,
    ApiErrorId,
    api_client,
    consignor_version,
    create_buyer,
    create_item,
    create_zone,
    fetch_agreement,
    fetch_consignor,
    fetch_consignor_ledger,
    fetch_sale,
    item_payload,
    payout_payload,
    place_item,
    receive_item,
    screen_item,
    sell_item,
    setup_consignor_with_active_agreement,
    take_custody,
    total_count,
    validate_error,
)

ONE_STEP = [(1, 0, 0.00, 0)]

BIG_ARMOIRE = {
    "title": "Armoire",
    "category": "CASEGOOD",
    "declared_value_cents": 200_000,
    "photo_count": 5,
    "volume_cuft": 90,
    "footprint_sqft": 20,
}
SECOND_ARMOIRE = {
    "title": "Second Armoire",
    "category": "CASEGOOD",
    "declared_value_cents": 60_000,
    "photo_count": 5,
    "volume_cuft": 12,
    "footprint_sqft": 10,
}
TRINKET = {
    "title": "Trinket",
    "category": "CASEGOOD",
    "declared_value_cents": 1_000,
    "photo_count": 5,
    "volume_cuft": 1,
    "footprint_sqft": 1,
}


def test_creating_a_second_piece_for_a_suspended_consignor_is_refused():
    """The suspension is a consequence of one capped surcharge, not an input.

    PRD 3.4: "Finally the surcharge is capped at 35 hundredths of the summed
    `declared_value_cents` of every piece attached to the job, that cap being itself rounded
    half up to a whole number of cents, and the surcharge charged is the smaller of the two
    rounded integers — the gallery will not bill a mover's day out at more than a third of
    what the furniture is worth."

    PRD 3.4: "Fourth, because the recomputed balance may now be deeply negative, if it has
    fallen below negative 50,000 cents the consignor's `status` becomes `SUSPENDED`."

    PRD 3.2: "Intake is refused with `ERR_AGREEMENT_NOT_ACTIVE` when the named agreement is
    `DRAFT`, `EXPIRED` or `TERMINATED`, with `ERR_CONSIGNOR_SUSPENDED` when the copied
    consignor is `SUSPENDED`, and with `ERR_CONSIGNOR_ESCHEATED` when that consignor has
    been escheated."

    Design: Corner/errors/creating_a_second_piece_for_a_suspended_consignor_is_refused
    """
    world = setup_consignor_with_active_agreement(
        schedule_steps=ONE_STEP,
        term_days=365,
        consignor_overrides={"floor_number": 8, "has_elevator": False},
    )
    consignor_id = world["consignor"]["id"]
    agreement_id = world["agreement"]["id"]

    armoire = create_item(agreement_id, **BIG_ARMOIRE)
    screen_item(armoire["id"], scores=SCORES_GRADE_A)

    collected = take_custody(
        consignor_id,
        [armoire["id"]],
        crew_size=4,
        actual_stair_flights=7,
        actual_elevator_used=False,
        actual_crew_size=4,
    )
    assert collected["pickup_job"]["final_surcharge_cents"] == 70_000, (
        f"Expected the raw 100775 clipped to the 70000 cap, "
        f"got {collected['pickup_job']['final_surcharge_cents']}"
    )

    refused = api_client.create_item(
        item_payload(agreement_id, **SECOND_ARMOIRE), INTAKE_APPRAISER
    )
    validate_error(refused, ApiErrorId.ERR_CONSIGNOR_SUSPENDED, 409)

    consignor = fetch_consignor(consignor_id)
    assert consignor["status"] == "SUSPENDED", (
        f"Expected SUSPENDED below the 50000 floor, got {consignor['status']}"
    )
    assert consignor["unclaimed_balance_cents"] == -70_000, (
        f"Expected -70000, got {consignor['unclaimed_balance_cents']}"
    )

    agreement = fetch_agreement(agreement_id)
    assert agreement["status"] == "ACTIVE", (
        f"Expected the paperwork perfectly sound, got {agreement['status']}"
    )

    listed = api_client.list_items(
        INTAKE_APPRAISER, params={"agreement_id": agreement_id, "limit": 100}
    )
    assert total_count(listed) == 1, (
        f"Expected the one armoire, got {total_count(listed)}"
    )


def _a_trinket_collected_for_a_capped_three_hundred_and_fifty():
    """A 1,000-cent piece whose 14,500 surcharge is clipped to 350 by the cap."""
    world = setup_consignor_with_active_agreement(
        schedule_steps=ONE_STEP,
        consignor_overrides={"floor_number": 1, "has_elevator": False},
    )
    trinket = create_item(world["agreement"]["id"], **TRINKET)
    priced = screen_item(trinket["id"], scores=SCORES_GRADE_A)
    assert priced["list_price_cents"] == 850, (
        f"Expected 1000 at eighty-five hundredths, got {priced['list_price_cents']}"
    )
    collected = take_custody(world["consignor"]["id"], [trinket["id"]])
    assert collected["pickup_job"]["final_surcharge_cents"] == 350, (
        f"Expected the raw 14500 clipped to the 350 cap, "
        f"got {collected['pickup_job']['final_surcharge_cents']}"
    )
    world["trinket"] = trinket
    return world


def test_a_payout_against_a_negative_balance_is_refused_as_insufficient():
    """The zero-or-negative gate answers first, so this id is reachable at all.

    PRD 3.9: "The balance must be strictly greater than zero, otherwise
    `ERR_INSUFFICIENT_BALANCE`, and it must then be at least the 2,000-cent payout minimum,
    otherwise `ERR_PAYOUT_BELOW_MINIMUM`; a consignor may still be paid out while their
    `escheat_state` is `DORMANT`, since dormancy is a warning rather than a freeze."

    PRD 2.9: "The zero-or-negative test at position 38 deliberately runs first: were the
    order reversed, every negative balance would answer `ERR_PAYOUT_BELOW_MINIMUM` and
    `ERR_INSUFFICIENT_BALANCE` would be unreachable."

    Design: Corner/errors/a_payout_against_a_negative_balance_is_refused_as_insufficient
    """
    world = _a_trinket_collected_for_a_capped_three_hundred_and_fifty()
    consignor_id = world["consignor"]["id"]

    before = fetch_consignor(consignor_id)
    assert before["unclaimed_balance_cents"] == -350, (
        f"Expected -350, got {before['unclaimed_balance_cents']}"
    )

    refused = api_client.create_payout(
        consignor_id, payout_payload(before["version"]), GALLERY_MANAGER
    )
    validate_error(refused, ApiErrorId.ERR_INSUFFICIENT_BALANCE, 409)

    entries = fetch_consignor_ledger(consignor_id)
    assert len(entries) == 1, (
        f"Expected the surcharge debit alone, got {[e['entry_type'] for e in entries]}"
    )
    assert entries[0]["entry_type"] == "PICKUP_SURCHARGE_DEBIT", (
        f"Expected no payout minted, got {entries[0]['entry_type']}"
    )

    after = fetch_consignor(consignor_id)
    assert after["unclaimed_balance_cents"] == -350, (
        f"Expected -350 still, got {after['unclaimed_balance_cents']}"
    )
    assert after["version"] == before["version"], (
        f"Expected version {before['version']} unmoved by the refusal, "
        f"got {after['version']}"
    )


def test_a_payout_against_a_positive_balance_under_two_thousand_is_refused():
    """A strictly positive 118 clears the first gate and fails the second.

    PRD 3.9: "The balance must be strictly greater than zero, otherwise
    `ERR_INSUFFICIENT_BALANCE`, and it must then be at least the 2,000-cent payout minimum,
    otherwise `ERR_PAYOUT_BELOW_MINIMUM`; a consignor may still be paid out while their
    `escheat_state` is `DORMANT`, since dormancy is a warning rather than a freeze."

    PRD 3.8: "`consignor_share_cents` is then `sale_price_cents` multiplied by
    `split_pct_applied`, rounded half up to a whole number of cents, and
    `gallery_share_cents` is the exact remainder of `sale_price_cents` after the consignor's
    share is taken out."

    PRD 3.8: "Add a price-band bonus read off `sale_price_cents`: nothing at all below
    50,000 cents, 5 hundredths for a price of at least 50,000 cents but below 150,000 cents,
    and 10 hundredths for a price of 150,000 cents or more — big tickets earn the consignor a
    better share because the gallery's handling cost does not scale with them."

    Design: Corner/errors/a_payout_against_a_positive_balance_under_two_thousand_is_refused
    """
    world = _a_trinket_collected_for_a_capped_three_hundred_and_fifty()
    consignor_id = world["consignor"]["id"]
    trinket_id = world["trinket"]["id"]

    receive_item(trinket_id, scores=SCORES_GRADE_A)
    bin_zone = create_zone(
        name="Bargain Bin", zone_type="CLEARANCE", capacity_sqft=100
    )
    place_item(trinket_id, bin_zone["id"], tag_code="BARGAIN-1")

    buyer = create_buyer(display_name="Nora Vance", floor_number=2, has_elevator=False)
    sale = sell_item(trinket_id, buyer["id"], 850)

    stored = fetch_sale(sale["id"])
    assert stored["split_pct_applied"] == 0.55, (
        f"Expected the casegood base with no band bonus, "
        f"got {stored['split_pct_applied']}"
    )
    assert stored["consignor_share_cents"] == 468, (
        f"Expected 850 at fifty-five hundredths, "
        f"got {stored['consignor_share_cents']}"
    )
    assert stored["gallery_share_cents"] == 382, (
        f"Expected the exact remainder, got {stored['gallery_share_cents']}"
    )

    before = fetch_consignor(consignor_id)
    assert before["unclaimed_balance_cents"] == 118, (
        f"Expected 468 against the 350 surcharge, "
        f"got {before['unclaimed_balance_cents']}"
    )

    refused = api_client.create_payout(
        consignor_id, payout_payload(consignor_version(consignor_id)), GALLERY_MANAGER
    )
    validate_error(refused, ApiErrorId.ERR_PAYOUT_BELOW_MINIMUM, 409)

    assert fetch_consignor(consignor_id)["unclaimed_balance_cents"] == 118, (
        f"Expected 118 still, "
        f"got {fetch_consignor(consignor_id)['unclaimed_balance_cents']}"
    )
    entries = fetch_consignor_ledger(consignor_id)
    assert [e["entry_type"] for e in entries] == [
        "PICKUP_SURCHARGE_DEBIT",
        "SALE_CREDIT",
    ], f"Expected no payout among them, got {[e['entry_type'] for e in entries]}"
