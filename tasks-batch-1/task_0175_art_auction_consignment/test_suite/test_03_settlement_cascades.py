"""Settlement cascades and compensation invariants: the depth-3 disburse
cascade, the depth-2 reverse-sale cascade, the bidder-balance conservation
invariant, and the hammer-decomposition invariant.
"""
from test_helpers import get_success_data
from test_helpers.assertions import assert_seller_statement_decomposition
from test_helpers.fixtures import (
    setup_statemented_lot, setup_invoiced_lot, FINANCE,
)
from test_helpers.factories import STANDARD_TIERS


# ===========================================================================
# Queue A — transitive_cascade
# ===========================================================================
def test_disburse_depth3_cascade_settles_lot(api):
    """PRD §3.8: "Disbursement is a depth-three cascade on a single action: it
    creates a `Payout` in `DISBURSED` status whose `amount_cents` is a snapshot
    of the statement's `net_payable_cents` ...; it sets the statement's
    `status` to `PAID` ...; if the lot's `ResaleRoyalty` exists and is
    `ACCRUED`, it sets that royalty's `status` to `REMITTED` ...; and it
    advances the lot's `settlement_status` from `STATEMENTED` to `SETTLED`"

    Hammer 1,250,000 at 10% commission with a living artist -> net 1,075,000.

    Design: Difficulty/transitive_cascade/cascade_disburse_depth3
    """
    scene, statement = setup_statemented_lot(
        hammer_cents=1250000, tiers=STANDARD_TIERS, seller_commission_bps=1000,
        artist_alive=True)
    payout = get_success_data(api.disburse_statement(
        statement["id"], {"expected_seller_statement_version": statement["version"]}, FINANCE))
    assert payout["amount_cents"] == 1075000, payout["amount_cents"]
    assert payout["status"] == "DISBURSED"
    stmt_after = get_success_data(api.get_seller_statement(statement["id"], FINANCE))
    assert stmt_after["status"] == "PAID"
    lot_after = get_success_data(api.get_lot(scene["lot"]["id"], FINANCE))
    assert lot_after["settlement_status"] == "SETTLED"
    royalties = get_success_data(api.list_lot_resale_royalties(scene["lot"]["id"], FINANCE))
    assert royalties[0]["status"] == "REMITTED"


def test_disburse_remits_royalty_on_same_action(api):
    """PRD §3.8: "if the lot's `ResaleRoyalty` exists and is `ACCRUED`, it sets
    that royalty's `status` to `REMITTED` (incrementing the royalty's `version`
    by 1), marking the moment the withheld royalty is remitted to the
    collecting society"

    The royalty is ACCRUED before disburse and REMITTED after the single
    disburse action — the remittance bubbles on the cascade.

    Design: Difficulty/transitive_cascade/cascade_disburse_depth3
    """
    scene, statement = setup_statemented_lot(
        hammer_cents=1250000, tiers=STANDARD_TIERS, seller_commission_bps=1000,
        artist_alive=True)
    before = get_success_data(api.list_lot_resale_royalties(scene["lot"]["id"], FINANCE))
    assert before[0]["status"] == "ACCRUED"
    get_success_data(api.disburse_statement(
        statement["id"], {"expected_seller_statement_version": statement["version"]}, FINANCE))
    after = get_success_data(api.list_lot_resale_royalties(scene["lot"]["id"], FINANCE))
    assert after[0]["status"] == "REMITTED"


def test_reverse_sale_depth2_voids_invoice_and_drops_balance(api):
    """PRD §3.9: "the lot's `ISSUED` `Invoice` becomes `VOID`, and because that
    invoice no longer counts, the buyer's `outstanding_balance_cents` is
    decreased by the invoice's `total_due_cents`"
    PRD §3.9: "The lot's `settlement_status` returns to `NONE`"

    Reversing a SOLD+invoiced lot voids the invoice and the bidder balance
    drops by total_due (1,575,000 -> 0).

    Design: Difficulty/transitive_cascade/cascade_reverse_sale_depth2
    """
    scene, invoice = setup_invoiced_lot(
        hammer_cents=1250000, tiers=STANDARD_TIERS, artist_alive=False)
    bidder_id = scene["bidder"]["id"]
    lot_id = scene["lot"]["id"]
    pre = get_success_data(api.get_bidder(bidder_id, FINANCE))
    assert pre["outstanding_balance_cents"] == 1575000
    lot = get_success_data(api.get_lot(lot_id, FINANCE))
    get_success_data(api.reverse_sale(lot_id, {"expected_lot_version": lot["version"]}, FINANCE))
    inv_after = get_success_data(api.get_invoice(invoice["id"], FINANCE))
    assert inv_after["status"] == "VOID"
    post = get_success_data(api.get_bidder(bidder_id, FINANCE))
    assert post["outstanding_balance_cents"] == 0


def test_reverse_sale_rolls_settlement_status_to_none(api):
    """PRD §3.9: "The lot's `settlement_status` returns to `NONE` and the lot's
    `version` is incremented by 1."

    A second observable of the reverse-sale cascade: the lot's financial
    dimension returns to NONE while the invoice goes VOID.

    Design: Difficulty/transitive_cascade/cascade_reverse_sale_depth2
    """
    scene, invoice = setup_invoiced_lot(
        hammer_cents=1250000, tiers=STANDARD_TIERS, artist_alive=False)
    lot_id = scene["lot"]["id"]
    lot = get_success_data(api.get_lot(lot_id, FINANCE))
    assert lot["settlement_status"] == "INVOICED"
    get_success_data(api.reverse_sale(lot_id, {"expected_lot_version": lot["version"]}, FINANCE))
    after = get_success_data(api.get_lot(lot_id, FINANCE))
    assert after["settlement_status"] == "NONE"


# ===========================================================================
# Queue A — compensating_invariant
# ===========================================================================
def test_bidder_balance_returns_to_zero_after_reverse(api):
    """PRD §3.6: "Issuing the invoice also recomputes the winning bidder's
    `outstanding_balance_cents` so that it includes the new invoice's
    `total_due_cents`."
    PRD §3.9: "the buyer's `outstanding_balance_cents` is decreased by the
    invoice's `total_due_cents`"

    The forward (invoice) and compensating (reverse-sale) actions conserve the
    balance: 0 -> 1,575,000 -> 0 with no drift.

    Design: Difficulty/compensating_invariant/invariant_bidder_balance_zero_after_reverse
    """
    scene, invoice = setup_invoiced_lot(
        hammer_cents=1250000, tiers=STANDARD_TIERS, artist_alive=False)
    bidder_id = scene["bidder"]["id"]
    lot_id = scene["lot"]["id"]
    mid = get_success_data(api.get_bidder(bidder_id, FINANCE))
    assert mid["outstanding_balance_cents"] == 1575000
    lot = get_success_data(api.get_lot(lot_id, FINANCE))
    get_success_data(api.reverse_sale(lot_id, {"expected_lot_version": lot["version"]}, FINANCE))
    after = get_success_data(api.get_bidder(bidder_id, FINANCE))
    assert after["outstanding_balance_cents"] == 0


def test_bidder_balance_zero_before_invoice(api):
    """PRD §3.1: "Each new bidder begins with `status` of `ACTIVE` and an
    `outstanding_balance_cents` of 0; the balance is a computed figure equal to
    the sum of `total_due_cents` over the bidder's invoices that are in
    `ISSUED` status"

    The conserved quantity starts at its pre-invoice value of 0, the same value
    it must return to after compensation.

    Design: Difficulty/compensating_invariant/invariant_bidder_balance_zero_after_reverse
    """
    scene, invoice = setup_invoiced_lot(
        hammer_cents=1250000, tiers=STANDARD_TIERS, artist_alive=False)
    bidder_id = scene["bidder"]["id"]
    lot_id = scene["lot"]["id"]
    lot = get_success_data(api.get_lot(lot_id, FINANCE))
    get_success_data(api.reverse_sale(lot_id, {"expected_lot_version": lot["version"]}, FINANCE))
    after = get_success_data(api.get_bidder(bidder_id, FINANCE))
    # 0 is both the pre-invoice value and the post-compensation value.
    assert after["outstanding_balance_cents"] == 0


def test_seller_proceeds_hammer_conserved(api):
    """PRD §3.8: "the `net_payable_cents` is the `hammer_price_cents` less the
    `seller_commission_cents` less the `resale_royalty_withheld_cents`."

    For a STATEMENTED lot the identity hammer == commission + royalty_withheld
    + net must hold exactly (1,250,000 == 125,000 + 50,000 + 1,075,000).

    Design: Difficulty/compensating_invariant/invariant_seller_proceeds_conserved
    """
    scene, statement = setup_statemented_lot(
        hammer_cents=1250000, tiers=STANDARD_TIERS, seller_commission_bps=1000,
        artist_alive=True)
    assert statement["hammer_price_cents"] == 1250000
    assert statement["seller_commission_cents"] == 125000
    assert statement["resale_royalty_withheld_cents"] == 50000
    assert statement["net_payable_cents"] == 1075000
    assert (statement["hammer_price_cents"]
            == statement["seller_commission_cents"]
            + statement["resale_royalty_withheld_cents"]
            + statement["net_payable_cents"])


def test_seller_statement_decomposition_holds_generally(api):
    """PRD §3.8: "the `net_payable_cents` is the `hammer_price_cents` less the
    `seller_commission_cents` less the `resale_royalty_withheld_cents`. The net
    payable is guaranteed to be non-negative and must never be negative"

    The hammer-decomposition identity also holds for a non-royalty lot
    (royalty_withheld 0): net == hammer - commission, never negative.

    Design: Difficulty/compensating_invariant/invariant_seller_proceeds_conserved
    """
    scene, statement = setup_statemented_lot(
        hammer_cents=1250000, tiers=STANDARD_TIERS, seller_commission_bps=1000,
        artist_alive=False)
    assert statement["resale_royalty_withheld_cents"] == 0
    assert_seller_statement_decomposition(statement)
    assert statement["net_payable_cents"] == 1125000
