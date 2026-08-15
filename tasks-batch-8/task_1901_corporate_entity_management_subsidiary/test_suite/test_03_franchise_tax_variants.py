"""Franchise-tax depth claims: the ESTIMATED/ACTUAL variant pair computed on
one filing, and the SHARES_TIERED block arithmetic at the free-share boundary."""
from test_helpers import (
    SEC1,
    fetch_entity,
    find_filing,
    prepare_filing,
    setup_base_entity,
    submit_filing,
    validate_success,
)


def _setup_prepared_franchise_filing(legal_name, authorized_shares):
    """ACTIVE entity whose period-2026 FRANCHISE_TAX filing is PREPARED."""
    ctx = setup_base_entity(legal_name=legal_name, authorized_shares=authorized_shares)
    entity = ctx["entity"]
    filing = find_filing(entity["id"], filing_type="FRANCHISE_TAX", period_year=2026)
    prepared = prepare_filing(filing["id"])
    return entity, prepared


def test_franchise_tax_estimated_uses_formation_basis(api):
    """PRD 3.7: "The `ESTIMATED` variant runs at prepare time and uses
    `shares_basis`: the prior accepted `FRANCHISE_TAX` filing's `shares_basis`
    for the same entity and jurisdiction, or the entity's `authorized_shares`
    at formation-confirm time for the first period."
    PRD 3.7: "subtract 5000 free shares from the share count, round up the
    remainder to whole blocks of 10000 shares, multiply the block count by 8500
    cents, add a base of 17500 cents, and cap the result at 2000000 cents."

    Design: Difficulty/dual_variant_calc/franchise_tax_estimated_vs_actual_basis
    """
    entity, prepared = _setup_prepared_franchise_filing("Acme Holdings Inc", 10000)

    # First period: basis is the formation-time authorized_shares (10000).
    assert prepared["shares_basis"] == 10000
    # 17500 + ceil((10000 - 5000) / 10000) * 8500 = 17500 + 1 * 8500 = 26000
    assert prepared["tax_estimated_cents"] == 26000

    # Change shares between the basis snapshot and submission (PATCH is allowed
    # while ACTIVE), then submit: the ACTUAL variant uses the current shares.
    validate_success(api.patch_entity(entity["id"], {"authorized_shares": 25000}, SEC1))
    submitted = submit_filing(prepared["id"])

    # 17500 + ceil((25000 - 5000) / 10000) * 8500 = 17500 + 2 * 8500 = 34500
    assert submitted["tax_assessed_cents"] == 34500
    assert submitted["tax_estimated_cents"] == 26000, "estimate stays at the snapshot basis"
    assert submitted["tax_assessed_cents"] != submitted["tax_estimated_cents"], (
        "PRD 3.7: the two variants diverge whenever shares change between the "
        "basis snapshot and submission"
    )


def test_franchise_tax_actual_drives_fee_and_accrual(api):
    """PRD 3.6: "At submit time, the system computes the actual franchise tax
    from the entity's current `authorized_shares`, determines `days_late` and
    `penalty_cents`, and sets `fee_cents` to the sum of `report_fee_cents`,
    `tax_assessed_cents`, and `penalty_cents`."
    PRD 3.6: "The submitter's `X-User-ID` is recorded in `submitted_by_user_id`,
    `submitted_date` is set to the current logical date, and the entity's
    `fees_accrued_cents` increases by `fee_cents`."

    Design: Difficulty/dual_variant_calc/franchise_tax_estimated_vs_actual_basis
    """
    entity, prepared = _setup_prepared_franchise_filing("Acme Holdings Inc", 10000)

    validate_success(api.patch_entity(entity["id"], {"authorized_shares": 25000}, SEC1))
    submitted = submit_filing(prepared["id"])

    assert submitted["status"] == "SUBMITTED"
    assert submitted["days_late"] == 0, "submitted 2026-08-01, on/before due 2026-12-31"
    assert submitted["penalty_cents"] == 0
    assert submitted["fee_cents"] == 39500, "5000 report fee + 34500 tax + 0 penalty"
    assert submitted["submitted_date"] == "2026-08-01"
    assert submitted["submitted_by_user_id"] == "fc-01"

    current = fetch_entity(entity["id"])
    assert current["fees_accrued_cents"] == 39500


def test_franchise_tax_block_floor_at_free_shares(api):
    """PRD 3.7: "subtract 5000 free shares from the share count, round up the
    remainder to whole blocks of 10000 shares, multiply the block count by 8500
    cents, add a base of 17500 cents, and cap the result at 2000000 cents."

    Design: Difficulty/combinatorial_formula/franchise_tax_tiered_block_ceil
    """
    entity, prepared = _setup_prepared_franchise_filing("Blockfloor Inc", 5000)

    submitted = submit_filing(prepared["id"])
    # max(0, 5000 - 5000) = 0 excess shares -> 0 blocks -> base only
    assert submitted["tax_assessed_cents"] == 17500
    assert submitted["fee_cents"] == 22500, "5000 report fee + 17500 tax + 0 penalty"


def test_franchise_tax_block_ceil_one_share_over(api):
    """PRD 3.7: "subtract 5000 free shares from the share count, round up the
    remainder to whole blocks of 10000 shares, multiply the block count by 8500
    cents, add a base of 17500 cents, and cap the result at 2000000 cents."

    Design: Difficulty/combinatorial_formula/franchise_tax_tiered_block_ceil
    """
    entity, prepared = _setup_prepared_franchise_filing("Blockstep Inc", 5001)

    submitted = submit_filing(prepared["id"])
    # 1 excess share rounds up to 1 full block: 17500 + 1 * 8500
    assert submitted["tax_assessed_cents"] == 26000
    assert submitted["fee_cents"] == 31000, "5000 report fee + 26000 tax + 0 penalty"
