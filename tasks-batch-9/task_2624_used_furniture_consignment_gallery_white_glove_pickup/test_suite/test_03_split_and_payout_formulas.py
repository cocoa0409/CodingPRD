"""Assembling the consignor's share, and emptying the account afterwards."""

from test_helpers import (
    GALLERY_MANAGER,
    SCORES_GRADE_A,
    STD_SCHEDULE_STEPS,
    create_buyer,
    fetch_consignor,
    fetch_item,
    request_payout,
    sell_item,
    setup_item_on_floor,
    validate_paginated,
)

TWO_STEP_SCHEDULE = STD_SCHEDULE_STEPS[:2]

ART_CLAMP_ITEM = {
    "title": "Oil landscape",
    "category": "ART",
    "declared_value_cents": 200_000,
    "photo_count": 4,
    "volume_cuft": 12,
    "footprint_sqft": 10,
}
ART_PAYOUT_ITEM = {
    "title": "Bronze study",
    "category": "ART",
    "declared_value_cents": 170_000,
    "photo_count": 4,
    "volume_cuft": 12,
    "footprint_sqft": 10,
}


def _art_on_the_floor(item_overrides):
    """A grade-A art piece placed in the front showroom, plus a walk-in buyer."""
    world = setup_item_on_floor(
        screen_scores=SCORES_GRADE_A,
        item_overrides=item_overrides,
    )
    world["buyer"] = create_buyer()
    return world


def test_category_and_price_bonus_are_clamped_at_seventy_hundredths():
    """A 0.75 assembled share is rewritten to the 0.70 ceiling.

    PRD 3.8: "Start from the category base share: 50 hundredths for `SOFA`, 55
    hundredths for `DINING`, 55 hundredths for `CASEGOOD`, 60 hundredths for `RUG`,
    65 hundredths for `ART` and 45 hundredths for `OUTDOOR`. Add a price-band bonus
    read off `sale_price_cents`: nothing at all below 50,000 cents, 5 hundredths for
    a price of at least 50,000 cents but below 150,000 cents, and 10 hundredths for
    a price of 150,000 cents or more"; "The resulting fraction is clamped into the
    closed range from 40 hundredths to 70 hundredths"

    Design: Difficulty/combinatorial_formula/consignor_split_max_clamp_beats_category_and_price_bonus
    """
    world = _art_on_the_floor(ART_CLAMP_ITEM)
    item = fetch_item(world["item"]["id"])

    assert item["list_price_cents"] == 204_000, (
        f"Expected 204000, got {item['list_price_cents']}"
    )
    assert item["current_price_cents"] == 204_000, (
        f"Expected 204000, got {item['current_price_cents']}"
    )

    sale = sell_item(item["id"], world["buyer"]["id"], 204_000)

    assert sale["split_pct_applied"] == 0.70, (
        f"Expected the 0.70 ceiling, got {sale['split_pct_applied']}"
    )
    assert sale["consignor_share_cents"] == 142_800, (
        f"Expected 142800, got {sale['consignor_share_cents']}"
    )
    assert sale["consignor_share_cents"] != 153_000, (
        "The unclamped 0.65 + 0.10 fraction must not be paid"
    )
    assert sale["gallery_share_cents"] == 61_200, (
        f"Expected 61200, got {sale['gallery_share_cents']}"
    )
    assert sale["consignor_share_cents"] + sale["gallery_share_cents"] == 204_000, (
        "The two shares must re-add to the price charged"
    )
    assert sale["markdown_sequence_at_sale"] == 1, (
        f"Expected 1, got {sale['markdown_sequence_at_sale']}"
    )


def test_clamped_share_is_the_figure_credited_to_the_ledger(api):
    """The ledger receives the clamped share, not the assembled fraction.

    PRD 3.8: "one `SALE_CREDIT` ledger entry of positive `consignor_share_cents` is
    minted against the consignor"; "`gallery_share_cents` is the exact remainder of
    `sale_price_cents` after the consignor's share is taken out"

    Design: Difficulty/combinatorial_formula/consignor_split_max_clamp_beats_category_and_price_bonus
    """
    world = _art_on_the_floor(ART_CLAMP_ITEM)
    consignor_id = world["consignor"]["id"]

    sell_item(world["item"]["id"], world["buyer"]["id"], 204_000)

    entries, meta = validate_paginated(
        api.list_consignor_ledger_entries(
            consignor_id, GALLERY_MANAGER, params={"limit": 100}
        )
    )
    assert meta["total_count"] == 2, (
        f"Expected the collection debit plus the sale credit, got {meta['total_count']}"
    )
    credits = [e for e in entries if e["entry_type"] == "SALE_CREDIT"]
    assert len(credits) == 1, f"Expected one SALE_CREDIT, got {len(credits)}"
    assert credits[0]["amount_cents"] == 142_800, (
        f"Expected +142800, got {credits[0]['amount_cents']}"
    )
    assert credits[0]["balance_after_cents"] == 125_800, (
        f"Expected 125800 after the credit, got {credits[0]['balance_after_cents']}"
    )

    consignor = fetch_consignor(consignor_id)
    assert consignor["unclaimed_balance_cents"] == 125_800, (
        f"Expected 125800, got {consignor['unclaimed_balance_cents']}"
    )
    assert consignor["lifetime_credits_cents"] == 142_800, (
        f"Expected 142800, got {consignor['lifetime_credits_cents']}"
    )


def test_withholding_band_is_read_off_the_balance_before_anything_is_taken():
    """A 101,000-cent balance withholds 2,020 and pays out 98,980.

    PRD 3.9: "nothing is withheld when the available amount is below 100,000 cents;
    2 hundredths of it are withheld when the amount is at least 100,000 cents but
    below 500,000 cents; and 3 hundredths are withheld at 500,000 cents or above.
    `withholding_cents` is the available amount multiplied by that fraction, rounded
    half up to a whole number of cents."

    Design: Difficulty/combinatorial_formula/payout_withholding_tier_keyed_on_pre_withholding_balance
    """
    world = setup_item_on_floor(
        screen_scores=SCORES_GRADE_A,
        item_overrides=ART_PAYOUT_ITEM,
        schedule_steps=TWO_STEP_SCHEDULE,
    )
    buyer = create_buyer()
    consignor_id = world["consignor"]["id"]

    sale = sell_item(world["item"]["id"], buyer["id"], 168_572)
    assert sale["split_pct_applied"] == 0.70, (
        f"Expected 0.70, got {sale['split_pct_applied']}"
    )
    assert sale["consignor_share_cents"] == 118_000, (
        f"Expected 118000, got {sale['consignor_share_cents']}"
    )
    assert fetch_consignor(consignor_id)["unclaimed_balance_cents"] == 101_000, (
        "The balance available for payout must be 101000"
    )

    entry = request_payout(consignor_id)

    assert entry["entry_type"] == "PAYOUT_DISBURSEMENT_DEBIT", (
        f"Expected PAYOUT_DISBURSEMENT_DEBIT, got {entry['entry_type']}"
    )
    assert entry["withholding_cents"] == 2_020, (
        f"Expected 2020, got {entry['withholding_cents']}"
    )
    assert entry["processing_fee_cents"] == 0, (
        f"An ACH account pays no processing fee, got {entry['processing_fee_cents']}"
    )
    assert entry["net_payout_cents"] == 98_980, (
        f"Expected 98980, got {entry['net_payout_cents']}"
    )
    assert entry["net_payout_cents"] != 101_000, (
        "Re-keying the band on the post-withholding figure would pay the whole balance"
    )


def test_payout_debits_the_whole_available_amount_and_zeroes_the_balance(api):
    """The minted debit is the whole balance, and the account lands on zero.

    PRD 3.9: "Exactly one `PAYOUT_DISBURSEMENT_DEBIT` entry is minted for the
    negation of the whole available amount"; "The recomputed
    `unclaimed_balance_cents` is therefore exactly 0, `last_activity_at` is stamped
    from the clock, a `DORMANT` `escheat_state` returns to `NONE`"

    Design: Difficulty/combinatorial_formula/payout_withholding_tier_keyed_on_pre_withholding_balance
    """
    world = setup_item_on_floor(
        screen_scores=SCORES_GRADE_A,
        item_overrides=ART_PAYOUT_ITEM,
        schedule_steps=TWO_STEP_SCHEDULE,
    )
    buyer = create_buyer()
    consignor_id = world["consignor"]["id"]
    sell_item(world["item"]["id"], buyer["id"], 168_572)

    entry = request_payout(consignor_id)

    assert entry["amount_cents"] == -101_000, (
        f"Expected -101000, the whole balance, got {entry['amount_cents']}"
    )
    assert entry["balance_after_cents"] == 0, (
        f"Expected 0, got {entry['balance_after_cents']}"
    )

    consignor = fetch_consignor(consignor_id)
    assert consignor["unclaimed_balance_cents"] == 0, (
        f"Expected 0, got {consignor['unclaimed_balance_cents']}"
    )
    assert consignor["escheat_state"] == "NONE", (
        f"Expected NONE, got {consignor['escheat_state']}"
    )

    _, meta = validate_paginated(
        api.list_consignor_ledger_entries(
            consignor_id, GALLERY_MANAGER, params={"limit": 100}
        )
    )
    assert meta["total_count"] == 3, (
        f"Expected collection, credit and disbursement, got {meta['total_count']}"
    )
