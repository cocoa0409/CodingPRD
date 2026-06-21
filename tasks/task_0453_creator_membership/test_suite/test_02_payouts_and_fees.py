"""Payout settlement arithmetic, processing-fee rounding order, and the
pending-payout conservation invariant.

Covers the payout dual-variant calculation, the per-line processing-fee
rounding combinatorial, the pending-payout compensating invariant, plus the
derived-field, charge-already-swept, and payout-terminal corner instances.
"""
from test_helpers import (
    api_client,
    validate_success,
    validate_error,
    validate_paginated,
    get_success_data,
    make_creator_headers,
    make_platform_admin_headers,
    ApiErrorId,
    set_clock,
    setup_active_membership,
    setup_creator_with_succeeded_charges,
    sweep_payout,
    settle_charge,
    first_pledge_charge,
    get_pledge,
)

ADMIN = make_platform_admin_headers()


def test_payout_settlement_totals_starter_plan(api):
    """PRD §3.7: "`gross_cents` is the sum of `net_amount_cents` over the swept
    charges; `processing_fee_cents` is the sum of the already-rounded per-line
    `processing_fee_cents` of those charges; `platform_fee_cents` is the
    `gross_cents` multiplied by the commission rate for the creator's
    `platform_plan` — 0.10 for `STARTER`, 0.08 for `PRO`, and 0.05 for
    `PREMIUM` — rounded half up once over the whole gross; and
    `payout_amount_cents` is the `gross_cents` minus the `platform_fee_cents`
    minus the `processing_fee_cents`."

    Design: Difficulty/dual_variant_calc/dvc_payout_settlement_vs_empty_sweep
    """
    s = setup_creator_with_succeeded_charges([1500, 800, 1500], platform_plan="STARTER")
    payout = sweep_payout(s["creator"]["id"], s["cycle_anchor_date"])

    # gross = 1500+800+1500 = 3800.
    assert payout["gross_cents"] == 3800, f"Expected gross 3800, got {payout['gross_cents']}"
    # per-line processing fees: round(1500*.029)+30=74, round(800*.029)+30=53, 74 → 201.
    assert payout["processing_fee_cents"] == 201, f"Expected 201, got {payout['processing_fee_cents']}"
    # platform fee = round(3800*0.10) = 380.
    assert payout["platform_fee_cents"] == 380, f"Expected 380, got {payout['platform_fee_cents']}"
    # payout = 3800 - 380 - 201 = 3219.
    assert payout["payout_amount_cents"] == 3219, f"Expected 3219, got {payout['payout_amount_cents']}"


def test_empty_sweep_rejected_nothing_to_payout(api):
    """PRD §3.7: "If no charge matches, no payout is created and the request is
    rejected with `ERR_NOTHING_TO_PAYOUT`."

    Design: Difficulty/dual_variant_calc/dvc_payout_settlement_vs_empty_sweep
    """
    s = setup_creator_with_succeeded_charges([1500, 800, 1500], platform_plan="STARTER")
    sweep_payout(s["creator"]["id"], s["cycle_anchor_date"])  # first sweep takes all charges

    # All charges now swept → a second sweep finds nothing.
    resp = api_client.create_payout(
        {"creator_id": s["creator"]["id"], "cycle_anchor_date": s["cycle_anchor_date"]}, ADMIN
    )
    validate_error(resp, ApiErrorId.ERR_NOTHING_TO_PAYOUT.value)


def test_processing_fee_rounded_per_line(api):
    """PRD §3.7: "Otherwise the fee is the `net_amount_cents` multiplied by a
    percentage rate of 0.029, rounded half up to whole cents, plus a flat 30
    cents."
    PRD §3.7: "This fee is rounded per individual charge at settlement time; the
    rounding happens per line, before any later summation, and a payout must
    never re-derive a fee from a summed gross, because summing-then-rounding
    would diverge by cents."

    Design: Difficulty/combinatorial_formula/cf_processing_fee_per_line_then_sum
    """
    set_clock("2026-06-01T00:00:00Z")
    s = setup_active_membership(clock="2026-06-01T00:00:00Z", platform_plan="STARTER",
                               monthly_fee_cents=1500)
    pledge_id = s["pledge"]["id"]

    # The pledge's INITIAL_PRORATION on June 1 = full month = 1500; settled in setup.
    init = s["init_charge"]
    assert init["processing_fee_cents"] == 74, (
        f"net 1500 → round(1500*.029)+30 = 74, got {init['processing_fee_cents']}"
    )

    ch2 = get_success_data(api_client.create_charge(
        {"pledge_id": pledge_id, "charge_kind": "CYCLE_RENEWAL", "gross_amount_cents": 800}, ADMIN))
    ch2 = settle_charge(ch2["id"], "SUCCEEDED")
    assert ch2["processing_fee_cents"] == 53, (
        f"net 800 → round(800*.029)+30 = round(23.2)+30 = 53, got {ch2['processing_fee_cents']}"
    )

    ch3 = get_success_data(api_client.create_charge(
        {"pledge_id": pledge_id, "charge_kind": "CYCLE_RENEWAL", "gross_amount_cents": 1500}, ADMIN))
    ch3 = settle_charge(ch3["id"], "SUCCEEDED")
    assert ch3["processing_fee_cents"] == 74

    payout = sweep_payout(s["creator"]["id"], "2026-06-01T00:00:00Z")
    # Sum of per-line fees 74+53+74 = 201 (NOT 200 that sum-then-round would give).
    assert payout["processing_fee_cents"] == 201, (
        f"Expected sum of per-line fees 201, got {payout['processing_fee_cents']}"
    )


def test_pending_payout_conserved_across_sweep_and_reverse(api):
    """PRD §3.7: "the creator's `pending_payout_cents` is reduced by the total
    net that was swept."
    PRD §3.7: "A reversal un-sweeps: every charge that had been swept into the
    payout has its `swept_into_payout_id` cleared, and the creator's
    `pending_payout_cents` is increased by the sum of the `net_amount_cents` of
    those charges, restoring the balance that the sweep had removed and keeping
    pending earnings conserved across the sweep-then-reverse pair."

    Design: Difficulty/compensating_invariant/ci_pending_payout_conserved_on_payout_reverse
    """
    s = setup_creator_with_succeeded_charges([1500, 800], platform_plan="STARTER")
    creator_id = s["creator"]["id"]

    payout = sweep_payout(creator_id, s["cycle_anchor_date"])
    after_sweep = get_success_data(api_client.get_creator(creator_id, ADMIN))
    assert after_sweep["pending_payout_cents"] == 0, (
        f"after sweep pending must be 0, got {after_sweep['pending_payout_cents']}"
    )

    rev = api_client.reverse_payout(payout["id"], ADMIN)
    validate_success(rev, 200)

    after_rev = get_success_data(api_client.get_creator(creator_id, ADMIN))
    assert after_rev["pending_payout_cents"] == 2300, (
        f"after reverse pending must be restored to 2300, got {after_rev['pending_payout_cents']}"
    )
    # Both charges un-swept.
    data, _ = validate_paginated(api_client.list_charges(ADMIN, params={"creator_id": creator_id}))
    for c in data:
        assert c["swept_into_payout_id"] is None, (
            f"charge {c['id']} swept_into_payout_id must be null after reverse"
        )


def test_pending_payout_increments_by_net_on_settle(api):
    """PRD §3.7: "The platform maintains it incrementally: a successful
    settlement adds the charge's net, a refund subtracts it, and a payout
    reversal adds it back."

    Design: Corner/cross_cutting_complexity_layers/derived_pending_payout_recomputed_on_settle
    """
    set_clock("2026-06-16T00:00:00Z")
    s = setup_active_membership(clock="2026-06-16T00:00:00Z", platform_plan="STARTER",
                               monthly_fee_cents=1500)
    # The June-16 INITIAL_PRORATION net is 750, settled in setup.
    creator = get_success_data(api_client.get_creator(s["creator"]["id"], ADMIN))
    assert creator["pending_payout_cents"] == 750, (
        f"pending must equal settled net 750, got {creator['pending_payout_cents']}"
    )


def test_refund_of_swept_charge_rejected(api):
    """PRD §3.5: "A charge that has already been swept into a payout cannot be
    refunded — its `swept_into_payout_id` must still be null — and a swept charge
    is rejected with `ERR_CHARGE_ALREADY_SWEPT`."

    Design: Corner/errors/charge_already_swept_refund_rejected
    """
    s = setup_active_membership(clock="2026-06-01T00:00:00Z", monthly_fee_cents=1500)
    charge_id = s["init_charge"]["id"]
    sweep_payout(s["creator"]["id"], "2026-06-01T00:00:00Z")

    resp = api_client.refund_charge(charge_id, make_creator_headers(s["creator"]["id"]))
    validate_error(resp, ApiErrorId.ERR_CHARGE_ALREADY_SWEPT.value)


def test_reverse_paid_payout_rejected(api):
    """PRD §3.7: "Reversing moves the payout from `PENDING` to the terminal
    `REVERSED` and is permitted only from `PENDING`; otherwise it is rejected
    with `ERR_PAYOUT_NOT_REVERSIBLE`."

    Design: Corner/state_machines/payout_reverse_from_paid_returns_not_reversible
    """
    s = setup_active_membership(clock="2026-06-01T00:00:00Z", monthly_fee_cents=1500)
    payout = sweep_payout(s["creator"]["id"], "2026-06-01T00:00:00Z")
    validate_success(api_client.mark_payout_paid(payout["id"], ADMIN), 200)

    resp = api_client.reverse_payout(payout["id"], ADMIN)
    validate_error(resp, ApiErrorId.ERR_PAYOUT_NOT_REVERSIBLE.value)
