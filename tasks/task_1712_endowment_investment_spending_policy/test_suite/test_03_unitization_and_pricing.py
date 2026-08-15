"""Unit pricing variants, per-gift rounding order, and ledger unitization rows."""
from test_helpers import (
    TEST_USERS,
    activate_fund,
    assert_ledger_entry,
    create_donor,
    create_fund,
    create_gift,
    finalize_open_quarter,
    get_success_data,
    receive_gift,
    set_target_allocations,
    setup_funded_world,
    setup_pool_world,
    setup_zero_manager_pool,
    validate_paginated,
    validate_success,
)


def _receive_expendable_gift(fund_id, donor_id, external_ref, amount_cents):
    gift = create_gift(fund_id, donor_id, external_ref, gift_type="EXPENDABLE",
                       amount_cents=amount_cents)
    return receive_gift(gift["id"])


def test_provisional_estimate_diverges_from_final_price_units(api):
    """PRD §3.2: 'Receipt stamps `received_quarter_index` with the open quarter
    (`current_quarter_index` + 1) — this stamp decides which quarter's `FINAL` price
    will unitize the gift — and computes an advisory
    `provisional_units_estimate_micro` as the gift's `amount_cents` multiplied by one
    billion and divided by the pool's `current_unit_price_millicents`, rounded half
    up.'
    PRD §3.4: 'Each gift's `units_purchased_micro` is its `amount_cents` multiplied
    by one billion and divided by the `final_unit_price_millicents`, rounded half up
    per gift — never aggregated and then rounded.'

    Design: Difficulty/dual_variant_calc/gift_unitization_provisional_estimate_diverges_from_final_price_units
    """
    ctx = setup_funded_world(corpus_cents=10_000_000, pool_name="Pool DV")
    pool_id = ctx["pool"]["id"]

    # Received during open quarter 2: estimate stamped at the Q1 FINAL price 100000.
    received = _receive_expendable_gift(ctx["fund"]["id"], ctx["donor"]["id"], "G2", 5_000_000)
    assert received["received_quarter_index"] == 2
    assert received["provisional_units_estimate_micro"] == 50_000_000_000

    # Q2 final price rises to 120000 millicents (MV 12000000 over 100000000000 units).
    finalize_open_quarter(pool_id, 12_000_000, reports=[{
        "manager_id": ctx["manager"]["id"], "beginning_mv_cents": 10_000_000,
        "ending_mv_cents": 12_000_000,
        "flows": [{"day_offset": 45, "amount_cents": 5_000_000}],
    }])

    gift = get_success_data(api.get_gift(received["id"], TEST_USERS["io_headers"]))
    assert gift["gift_status"] == "UNITIZED"
    assert gift["unitized_quarter_index"] == 2
    assert gift["units_purchased_micro"] == 41_666_666_667
    assert gift["units_purchased_micro"] != gift["provisional_units_estimate_micro"]


def test_provisional_estimate_divergence_accumulates_into_fund_units(api):
    """PRD §3.4: 'the fund's `units_held_micro` and the pool's
    `total_units_outstanding_micro` both increase by exactly `units_purchased_micro`'
    PRD §3.2: 'an advisory `provisional_units_estimate_micro`' (advisory only — the
    finalized quantity is authoritative).

    Design: Difficulty/dual_variant_calc/gift_unitization_provisional_estimate_diverges_from_final_price_units
    """
    ctx = setup_funded_world(corpus_cents=10_000_000, pool_name="Pool DV")
    pool_id = ctx["pool"]["id"]
    _receive_expendable_gift(ctx["fund"]["id"], ctx["donor"]["id"], "G2", 5_000_000)

    finalize_open_quarter(pool_id, 12_000_000, reports=[{
        "manager_id": ctx["manager"]["id"], "beginning_mv_cents": 10_000_000,
        "ending_mv_cents": 12_000_000,
        "flows": [{"day_offset": 45, "amount_cents": 5_000_000}],
    }])

    fund = get_success_data(api.get_fund(ctx["fund"]["id"], TEST_USERS["io_headers"]))
    # 100000000000 seed units + 41666666667 from the Q2 gift at price 120000.
    assert fund["units_held_micro"] == 141_666_666_667
    pool = get_success_data(api.get_pool(pool_id, TEST_USERS["io_headers"]))
    assert pool["total_units_outstanding_micro"] == 141_666_666_667
    assert pool["current_unit_price_millicents"] == 120_000


def test_per_gift_rounding_order_two_one_cent_gifts(api):
    """PRD §3.4: 'Each gift's `units_purchased_micro` is its `amount_cents`
    multiplied by one billion and divided by the `final_unit_price_millicents`,
    rounded half up per gift — never aggregated and then rounded.'

    Design: Difficulty/combinatorial_formula/gift_unitization_per_gift_rounding_order_mode_b
    """
    ctx = setup_funded_world(corpus_cents=10_000_000, pool_name="Pool RND")
    pool_id = ctx["pool"]["id"]
    g2 = _receive_expendable_gift(ctx["fund"]["id"], ctx["donor"]["id"], "R2", 1)
    g3 = _receive_expendable_gift(ctx["fund"]["id"], ctx["donor"]["id"], "R3", 1)

    # Q2 final price 300000 millicents (MV 30000000 over 100000000000 pre-flow units).
    finalize_open_quarter(pool_id, 30_000_000, reports=[{
        "manager_id": ctx["manager"]["id"], "beginning_mv_cents": 10_000_000,
        "ending_mv_cents": 30_000_000,
        "flows": [{"day_offset": 0, "amount_cents": 20_000_002}],
    }])

    gift2 = get_success_data(api.get_gift(g2["id"], TEST_USERS["io_headers"]))
    gift3 = get_success_data(api.get_gift(g3["id"], TEST_USERS["io_headers"]))
    assert gift2["units_purchased_micro"] == 3333, "round_half_up(1 * 1e9 / 300000)"
    assert gift3["units_purchased_micro"] == 3333

    fund = get_success_data(api.get_fund(ctx["fund"]["id"], TEST_USERS["io_headers"]))
    # Per-gift rounding: 3333 + 3333; the sum-then-round order would yield ...6667.
    assert fund["units_held_micro"] == 100_000_006_666


def test_per_gift_rounding_preserves_pool_unit_identity(api):
    """PRD §2.5: 'The pool's `total_units_outstanding_micro` is the exact integer sum
    of every fund's `units_held_micro`, maintained by construction'
    PRD §3.4: 'rounded half up per gift — never aggregated and then rounded.'

    Design: Difficulty/combinatorial_formula/gift_unitization_per_gift_rounding_order_mode_b
    """
    ctx = setup_funded_world(corpus_cents=10_000_000, pool_name="Pool RND")
    pool_id = ctx["pool"]["id"]
    _receive_expendable_gift(ctx["fund"]["id"], ctx["donor"]["id"], "R2", 1)
    _receive_expendable_gift(ctx["fund"]["id"], ctx["donor"]["id"], "R3", 1)

    finalize_open_quarter(pool_id, 30_000_000, reports=[{
        "manager_id": ctx["manager"]["id"], "beginning_mv_cents": 10_000_000,
        "ending_mv_cents": 30_000_000,
        "flows": [{"day_offset": 0, "amount_cents": 20_000_002}],
    }])

    fund = get_success_data(api.get_fund(ctx["fund"]["id"], TEST_USERS["io_headers"]))
    pool = get_success_data(api.get_pool(pool_id, TEST_USERS["io_headers"]))
    assert pool["total_units_outstanding_micro"] == fund["units_held_micro"] == 100_000_006_666


def test_inception_price_applies_when_zero_units_outstanding(api):
    """PRD §3.4: 'when that pre-flow unit count is 0 the price is the inception price
    of 100000 millicents, otherwise it is the final value multiplied by one billion
    and divided by the pre-flow units, rounded half up and floored at 1 millicent.'

    Design: Corner/calculations/inception_price_applies_when_zero_units_outstanding
    """
    ctx = setup_zero_manager_pool(pool_name="Pool ZU")
    pool_id = ctx["pool"]["id"]
    fund = create_fund(pool_id, fund_code="FZU", fund_name="Fund ZU")
    donor = create_donor(donor_name="D ZU")
    gift = create_gift(fund["id"], donor["id"], "ZU1", gift_type="CORPUS",
                       amount_cents=10_000_000)
    activate_fund(fund["id"])
    receive_gift(gift["id"])

    valuation = finalize_open_quarter(pool_id, 0)
    assert valuation["valuation_status"] == "FINAL"
    assert valuation["final_unit_price_millicents"] == 100_000

    gift_after = get_success_data(api.get_gift(gift["id"], TEST_USERS["io_headers"]))
    assert gift_after["units_purchased_micro"] == 100_000_000_000
    assert gift_after["unitized_quarter_index"] == 1


def test_zero_market_value_with_units_hits_price_floor(api):
    """PRD §3.4: 'when that pre-flow unit count is 0 the price is the inception price
    of 100000 millicents, otherwise it is the final value multiplied by one billion
    and divided by the pre-flow units, rounded half up and floored at 1 millicent.'
    PRD §3.4: '`is_underwater` is set to true exactly when `market_value_cents` is
    strictly less than `historic_gift_value_cents` — equality is not underwater.'

    Design: Corner/calculations/zero_market_value_with_units_hits_price_floor
    """
    ctx = setup_zero_manager_pool(pool_name="Pool ZF")
    pool_id = ctx["pool"]["id"]
    fund = create_fund(pool_id, fund_code="FZF", fund_name="Fund ZF")
    donor = create_donor(donor_name="D ZF")
    gift = create_gift(fund["id"], donor["id"], "ZF1", gift_type="CORPUS",
                       amount_cents=10_000_000)
    activate_fund(fund["id"])
    receive_gift(gift["id"])
    finalize_open_quarter(pool_id, 0)

    finalize_open_quarter(pool_id, 0)

    pool = get_success_data(api.get_pool(pool_id, TEST_USERS["io_headers"]))
    assert pool["current_unit_price_millicents"] == 1, "price floor, never 0"
    fund_after = get_success_data(api.get_fund(fund["id"], TEST_USERS["io_headers"]))
    assert fund_after["market_value_cents"] == 100  # round_half_up(1e11 * 1 / 1e9)
    assert fund_after["is_underwater"] is True      # 100 < 10000000


def test_ledger_entries_are_append_only_and_carry_unitization_fields(api):
    """PRD §3.4: 'a `UnitLedgerEntry` of type `GIFT_UNITIZE` is emitted — or
    `REINVEST_UNITIZE` when the gift's `source_payout_id` is set.'
    PRD §2.4: '`UnitLedgerEntry` is append-only and immutable: it carries `id` and
    `created_at` only, and both `updated_at` and `version` are absent from it.'
    PRD §3.12: 'Each entry records its `fund_id`, the `quarter_index` it belongs to
    (the quarter being finalized, or the open quarter for out-of-band redemptions),
    its `entry_type`, the signed `units_delta_micro` movement, the signed
    `amount_cents` cash value, and a polymorphic `reference_id` holding the id of the
    `GiftContribution`, `SpendingDistribution`, `ProgramPayout`, or superseding
    `UnitValuation` that caused the entry'

    Design: Corner/entities/ledger_entries_are_append_only_and_carry_unitization_fields
    """
    ctx = setup_zero_manager_pool(pool_name="Pool LE")
    pool_id = ctx["pool"]["id"]
    fund = create_fund(pool_id, fund_code="FLE", fund_name="Fund LE")
    donor = create_donor(donor_name="D LE")
    gift = create_gift(fund["id"], donor["id"], "LE1", gift_type="CORPUS",
                       amount_cents=5_000_000)
    activate_fund(fund["id"])
    receive_gift(gift["id"])
    finalize_open_quarter(pool_id, 0)

    res = api.list_ledger_entries(
        TEST_USERS["io_headers"],
        params={"fund_id": fund["id"], "entry_type": "GIFT_UNITIZE"},
    )
    entries, meta = validate_paginated(res)
    assert len(entries) == 1
    entry = entries[0]
    assert_ledger_entry(entry)
    assert entry["units_delta_micro"] == 50_000_000_000
    assert entry["amount_cents"] == 5_000_000
    assert entry["quarter_index"] == 1
    assert entry["reference_id"] == gift["id"]
