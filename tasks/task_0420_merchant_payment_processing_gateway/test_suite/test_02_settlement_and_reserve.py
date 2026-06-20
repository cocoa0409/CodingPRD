"""Settlement summary, reserve holds, the settle funding cascade, and reserve release.

Covers difficulty queue (combinatorial_formula rounding order, transitive_cascade settle,
compensating_invariant reserve conservation) and corner reserve/derived-field instances.
"""
from test_helpers import (
    validate_success, validate_paginated,
    set_clock, advance_clock,
    create_flat_plan, create_approved_merchant, create_authorized_charge,
    create_captured_charge, open_and_settle_batch,
    make_merchant_user_headers,
    TEST_USERS,
)

OPERATOR = TEST_USERS["platform_operator_headers"]


def test_settlement_total_fees_round_then_sum_per_capture(api):
    """PRD §3.4: "The rounding discipline is round-then-sum: each percentage component is
    rounded half-up to whole cents on its own before the components are added together".
    PRD §3.8: "The `total_fees_cents` is the sum of `processing_fee_cents` over those same
    charges."

    Design: Difficulty/combinatorial_formula/settlement_reserve_sum_then_round_vs_per_capture_round_then_sum
    """
    set_clock("2026-02-01T00:00:00Z")
    plan = create_flat_plan(flat_pct_bps=290, flat_fixed_cents=30)
    merchant, _ = create_approved_merchant(fee_plan_id=plan["id"], assigned_risk_band="MEDIUM")
    version = merchant["version"]
    create_captured_charge(merchant["id"], auth_amount_cents=333)
    create_captured_charge(merchant["id"], auth_amount_cents=333)
    settled, _ = open_and_settle_batch(merchant["id"], version, business_date="2026-02-01")
    assert settled["gross_captured_cents"] == 666
    # each capture fee: round(333*0.029)=10 (9.657->10) + 30 = 40; two captures => 80.
    assert settled["total_fees_cents"] == 80, f"expected 80, got {settled['total_fees_cents']}"


def test_settlement_reserve_sum_then_round_on_aggregate(api):
    """PRD §3.8: "it is the `gross_captured_cents` multiplied by the merchant's
    `reserve_rate_bps` divided by 10000, rounded half-up — this is sum-then-round on the
    aggregate, rounded a single time."

    Design: Difficulty/combinatorial_formula/settlement_reserve_sum_then_round_vs_per_capture_round_then_sum
    """
    set_clock("2026-02-01T00:00:00Z")
    plan = create_flat_plan(flat_pct_bps=290, flat_fixed_cents=30)
    merchant, _ = create_approved_merchant(fee_plan_id=plan["id"], assigned_risk_band="MEDIUM")
    version = merchant["version"]
    create_captured_charge(merchant["id"], auth_amount_cents=333)
    create_captured_charge(merchant["id"], auth_amount_cents=333)
    settled, _ = open_and_settle_batch(merchant["id"], version, business_date="2026-02-01")
    # MEDIUM reserve 500bps: round(666*0.05)=33 (33.3->33), NOT round(333*0.05)*2=34.
    assert settled["reserve_held_cents"] == 33, f"expected 33, got {settled['reserve_held_cents']}"


def test_settle_cascade_advances_charge_to_settled(api):
    """PRD §3.7: "first, every batched charge has its `settlement_status` moved from
    `BATCHED` to `SETTLED`."

    Design: Difficulty/transitive_cascade/settle_cascade_charge_reserve_ledger_depth3
    """
    set_clock("2026-01-01T00:00:00Z")
    plan = create_flat_plan()
    merchant, _ = create_approved_merchant(fee_plan_id=plan["id"], assigned_risk_band="MEDIUM")
    version = merchant["version"]
    charge = create_captured_charge(merchant["id"], auth_amount_cents=10000)
    open_and_settle_batch(merchant["id"], version, business_date="2026-01-01")
    fetched = validate_success(api.get_charge(charge["id"], make_merchant_user_headers(merchant["id"])))
    assert fetched["settlement_status"] == "SETTLED"


def test_settle_cascade_creates_reserve_entry_and_recomputes_reserved_balance(api):
    """PRD §3.7: "the reserve hold is computed and a `ReserveEntry` in `HELD` status is
    created for it, and a `RESERVE_HOLD` ledger entry is posted on the `RESERVE` account for
    the positive of the reserve amount with `source_type` `RESERVE_ENTRY`."
    PRD §3.9: "The corresponding `RESERVE_HOLD` ledger posting at settle is what raises the
    merchant's `reserved_balance_cents`."

    Design: Difficulty/transitive_cascade/settle_cascade_charge_reserve_ledger_depth3
    """
    set_clock("2026-01-01T00:00:00Z")
    plan = create_flat_plan()
    merchant, _ = create_approved_merchant(fee_plan_id=plan["id"], assigned_risk_band="MEDIUM")
    version = merchant["version"]
    create_captured_charge(merchant["id"], auth_amount_cents=10000)
    batch, _ = open_and_settle_batch(merchant["id"], version, business_date="2026-01-01")

    entries, _ = validate_paginated(api.list_batch_reserve_entries(batch["id"], OPERATOR))
    assert len(entries) >= 1, "settle must create a ReserveEntry for the batch"
    # MEDIUM 500bps: round(10000*0.05)=500.
    assert entries[0]["amount_cents"] == 500, f"expected reserve 500, got {entries[0]['amount_cents']}"

    merchant_after = validate_success(api.get_merchant(merchant["id"], OPERATOR))
    assert merchant_after["reserved_balance_cents"] == 500, (
        f"expected reserved_balance 500, got {merchant_after['reserved_balance_cents']}"
    )


def test_high_risk_reserve_rate_applied_at_settle(api):
    """PRD §3.2: "a `HIGH` band carries 1000 basis points, i.e. 10%".
    PRD §3.8: "Finally the `net_funding_cents` is the `gross_captured_cents` minus the
    `total_fees_cents` minus the `total_refunds_cents` minus the `reserve_held_cents`."

    Design: Corner/Calculations/corner_reserve_rate_constant_applied_high_band
    """
    set_clock("2026-01-01T00:00:00Z")
    plan = create_flat_plan(flat_pct_bps=290, flat_fixed_cents=30)
    merchant, _ = create_approved_merchant(
        fee_plan_id=plan["id"], assigned_risk_band="HIGH",
        merchant_overrides={"mcc": "7995"},
    )
    version = merchant["version"]
    create_captured_charge(merchant["id"], auth_amount_cents=10000)
    settled, _ = open_and_settle_batch(merchant["id"], version, business_date="2026-01-01")
    # HIGH reserve 1000bps: round(10000*0.10)=1000.
    assert settled["reserve_held_cents"] == 1000
    # net = 10000 - 320 fee - 0 refunds - 1000 reserve = 8680
    assert settled["net_funding_cents"] == 8680, f"expected 8680, got {settled['net_funding_cents']}"


def test_reserve_hold_then_release_conserves_cross_account_total(api):
    """PRD §3.9: "Releasing an entry moves its `reserve_status` from `HELD` to `RELEASED` and
    posts two ledger entries, both with `source_type` `RESERVE_ENTRY`: a `RESERVE_RELEASE`
    entry on the `RESERVE` account for the negative of the held `amount_cents`, and an
    `ADJUSTMENT` entry on the `AVAILABLE` account for the positive of the same `amount_cents`".

    Design: Difficulty/compensating_invariant/reserve_hold_then_release_conserves_total_balance_across_accounts
    """
    set_clock("2026-01-01T00:00:00Z")
    plan = create_flat_plan(flat_pct_bps=290, flat_fixed_cents=30)
    merchant, _ = create_approved_merchant(fee_plan_id=plan["id"], assigned_risk_band="MEDIUM")
    version = merchant["version"]
    create_captured_charge(merchant["id"], auth_amount_cents=10000)
    batch, _ = open_and_settle_batch(merchant["id"], version, business_date="2026-01-01")
    advance_clock("2026-01-03T00:00:00Z")
    validate_success(api.fund_batch(batch["id"], {}, OPERATOR))

    pre = validate_success(api.get_merchant(merchant["id"], OPERATOR))
    # available = 10000 - 320 fee - 500 reserve = 9180; reserved = 500.
    assert pre["available_balance_cents"] == 9180
    assert pre["reserved_balance_cents"] == 500
    total_pre = pre["available_balance_cents"] + pre["reserved_balance_cents"]

    advance_clock("2026-04-01T00:00:00Z")
    validate_success(api.run_reserve_releases(merchant["id"], {}, OPERATOR))
    post = validate_success(api.get_merchant(merchant["id"], OPERATOR))
    assert post["available_balance_cents"] == 9680
    assert post["reserved_balance_cents"] == 0
    total_post = post["available_balance_cents"] + post["reserved_balance_cents"]
    assert total_pre == total_post == 9680, "cross-account total must be conserved by release"


def test_reserve_release_zeroes_reserve_and_credits_available_by_held_amount(api):
    """PRD §3.9: "a `RESERVE_RELEASE` entry on the `RESERVE` account for the negative of the
    held `amount_cents`, and an `ADJUSTMENT` entry on the `AVAILABLE` account for the positive
    of the same `amount_cents` — together moving the funds from the reserve account into the
    available account."

    Design: Difficulty/compensating_invariant/reserve_hold_then_release_conserves_total_balance_across_accounts
    """
    set_clock("2026-01-01T00:00:00Z")
    plan = create_flat_plan(flat_pct_bps=290, flat_fixed_cents=30)
    merchant, _ = create_approved_merchant(fee_plan_id=plan["id"], assigned_risk_band="MEDIUM")
    version = merchant["version"]
    create_captured_charge(merchant["id"], auth_amount_cents=10000)
    batch, _ = open_and_settle_batch(merchant["id"], version, business_date="2026-01-01")
    advance_clock("2026-01-03T00:00:00Z")
    validate_success(api.fund_batch(batch["id"], {}, OPERATOR))

    pre = validate_success(api.get_merchant(merchant["id"], OPERATOR))
    held = pre["reserved_balance_cents"]
    assert held == 500
    avail_pre = pre["available_balance_cents"]

    advance_clock("2026-04-01T00:00:00Z")
    validate_success(api.run_reserve_releases(merchant["id"], {}, OPERATOR))
    post = validate_success(api.get_merchant(merchant["id"], OPERATOR))
    # RESERVE account drained by the full held amount; AVAILABLE credited by the same amount.
    assert post["reserved_balance_cents"] == 0
    assert post["available_balance_cents"] == avail_pre + held


def test_reserve_release_sweep_moves_reserve_to_available(api):
    """PRD §3.9: "The sweep releases every `HELD` reserve entry whose `release_date` has been
    reached or passed by the clock's date".
    PRD §3.9: "After the sweep, the merchant's `reserved_balance_cents` and
    `available_balance_cents` are both recomputed."

    Design: Corner/Cross-Cutting Complexity Layers/corner_reserve_release_derived_field_reconciliation
    """
    set_clock("2026-01-01T00:00:00Z")
    plan = create_flat_plan(flat_pct_bps=290, flat_fixed_cents=30)
    merchant, _ = create_approved_merchant(fee_plan_id=plan["id"], assigned_risk_band="MEDIUM")
    version = merchant["version"]
    create_captured_charge(merchant["id"], auth_amount_cents=10000)
    batch, _ = open_and_settle_batch(merchant["id"], version, business_date="2026-01-01")
    advance_clock("2026-01-03T00:00:00Z")
    validate_success(api.fund_batch(batch["id"], {}, OPERATOR))
    advance_clock("2026-04-02T00:00:00Z")
    validate_success(api.run_reserve_releases(merchant["id"], {}, OPERATOR))
    after = validate_success(api.get_merchant(merchant["id"], OPERATOR))
    assert after["reserved_balance_cents"] == 0
    assert after["available_balance_cents"] == 9680, (
        f"expected 9680 (9180 + 500 released), got {after['available_balance_cents']}"
    )
