"""Partial returns, merchant settlement, MDR clawback, and net-settled conservation.

Covers queue A combinatorial_formula (return rounding), compensating_invariant
(merchant net settled), plus queue B corner instances on settlement state and
partial clawback.
"""
from test_helpers import (
    validate_success,
    setup_activated_loan,
    setup_released_settlement,
    get_loan,
    get_merchant,
    get_settlement_for_loan,
    list_installments,
    installments_by_sequence,
    find_installment,
    make_servicer_headers,
    make_merchant_headers,
    create_return_payload,
)

SERVICER = make_servicer_headers()


def test_return_reallocation_newest_first_exact_integer_subtraction(api):
    """PRD §3.9: "First, the principal_reduction_cents is the lesser of
    return_amount_cents and the loan's remaining_principal_cents."
    PRD §3.9: "Second, that principal reduction is distributed across the loan's unpaid
    installments — those whose status is SCHEDULED or LATE — newest-due-first, in
    descending sequence_no, reducing each installment's outstanding (its amount_due_cents
    minus its amount_paid_cents) before moving to the next; an installment whose
    outstanding is fully covered is moved to CANCELLED."

    Design: Difficulty/combinatorial_formula/return_reallocation_rounding_order_pinned
    """
    ctx = setup_activated_loan(cart_amount_cents=100_000, plan_type="PAY_IN_4",
                               mdr_bps=600, settlement_hold_days=0)
    loan = ctx["loan"]
    # 30000 return on [25000,25000,25000,25000]: cancels #4, reduces #3 to 20000.
    resp = api.create_return(
        create_return_payload(loan["id"], 30_000),
        make_merchant_headers(ctx["merchant"]["id"]),
    )
    ret = validate_success(resp, 201)
    assert ret["principal_reduction_cents"] == 30_000
    assert ret["settlement_clawback_cents"] == 28_200, (
        "clawback = 30000 - round_half_up(30000*600/10000=1800) = 28200"
    )

    refreshed = get_loan(loan["id"])
    assert refreshed["remaining_principal_cents"] == 70_000

    installments = installments_by_sequence(list_installments(loan["id"]))
    inst4 = find_installment(installments, 4)
    inst3 = find_installment(installments, 3)
    assert inst4["status"] == "CANCELLED", "newest installment #4 fully covered -> CANCELLED"
    assert inst3["amount_due_cents"] == 20_000, "installment #3 reduced 25000 -> 20000"


def test_return_mdr_clawback_rounds_once(api):
    """PRD §3.9: "Fourth, the merchant keeps its discount on returned goods but the net
    principal is clawed back: the MDR portion on the return is return_amount_cents
    multiplied by the merchant's mdr_bps divided by 10000, rounded half up, and the
    settlement_clawback_cents is the lesser of return_amount_cents minus that MDR portion
    and the settlement's remaining net (its net_settlement_cents minus its current
    clawed_back_cents)."

    Design: Difficulty/combinatorial_formula/return_reallocation_rounding_order_pinned
    """
    ctx = setup_activated_loan(cart_amount_cents=100_000, plan_type="PAY_IN_4",
                               mdr_bps=600, settlement_hold_days=0)
    resp = api.create_return(
        create_return_payload(ctx["loan"]["id"], 30_000),
        make_merchant_headers(ctx["merchant"]["id"]),
    )
    ret = validate_success(resp, 201)
    # mdr_on_return = round_half_up(30000 * 600 / 10000) = round_half_up(1800.0) = 1800
    # clawback = 30000 - 1800 = 28200, capped at settlement net 94000.
    assert ret["settlement_clawback_cents"] == 28_200


def test_merchant_net_settled_conserved_release_then_full_clawback(api):
    """PRD §3.8: "On release the merchant's net_settled_cents is recomputed, adding
    this row's net_settlement_cents minus its clawed_back_cents."
    PRD §3.8: "A settlement that is already RELEASED moves to CLAWED_BACK only via a
    return whose clawback drives clawed_back_cents to net_settlement_cents, and in that
    case the previously released net is reversed back out of the merchant's
    net_settled_cents".

    Design: Difficulty/compensating_invariant/merchant_net_settled_conserved_across_release_and_clawback
    """
    ctx = setup_released_settlement(cart_amount_cents=100_000, mdr_bps=600)
    merchant_after_release = get_merchant(ctx["merchant"]["id"])
    assert merchant_after_release["net_settled_cents"] == 94_000, (
        "net 100000 - mdr 6000 = 94000 after release"
    )

    # Full 100000 return: clawback = 100000 - round_half_up(6000) = 94000, capped at net 94000.
    resp = api.create_return(
        create_return_payload(ctx["loan"]["id"], 100_000),
        make_merchant_headers(ctx["merchant"]["id"]),
    )
    validate_success(resp, 201)

    merchant_after_return = get_merchant(ctx["merchant"]["id"])
    assert merchant_after_return["net_settled_cents"] == 0, (
        "fully-clawed-back released settlement returns net_settled to 0"
    )
    settlement = get_settlement_for_loan(ctx["loan"]["id"])
    assert settlement["status"] == "CLAWED_BACK"


def test_partial_return_on_released_settlement_stays_released(api):
    """PRD §3.8: "A RELEASED settlement that is only partially clawed back stays
    RELEASED, with the merchant's rollup reflecting net_settlement_cents minus
    clawed_back_cents."

    Design: Corner/cross_cutting_complexity_layers/return_partial_reallocation_settlement_clawback_recorded
    """
    ctx = setup_released_settlement(cart_amount_cents=100_000, mdr_bps=600)
    resp = api.create_return(
        create_return_payload(ctx["loan"]["id"], 30_000),
        make_merchant_headers(ctx["merchant"]["id"]),
    )
    ret = validate_success(resp, 201)
    assert ret["settlement_clawback_cents"] == 28_200

    settlement = get_settlement_for_loan(ctx["loan"]["id"])
    assert settlement["clawed_back_cents"] == 28_200
    assert settlement["status"] == "RELEASED", "partial clawback keeps a RELEASED row RELEASED"

    merchant = get_merchant(ctx["merchant"]["id"])
    assert merchant["net_settled_cents"] == 65_800, "94000 net - 28200 clawed = 65800"


def test_settlement_created_pending_with_mdr_fee_and_net(api):
    """PRD §3.8: "The settlement's mdr_fee_cents is the merchant discount fee, computed
    at origination as the gross financed amount multiplied by the merchant's mdr_bps
    divided by 10000, rounded half up. Its net_settlement_cents is the gross financed
    amount minus that fee. Its clawed_back_cents begins at 0, and its status begins
    PENDING."

    Design: Difficulty/compensating_invariant/merchant_net_settled_conserved_across_release_and_clawback
    """
    ctx = setup_activated_loan(cart_amount_cents=100_000, plan_type="PAY_IN_4",
                               mdr_bps=600, settlement_hold_days=2)
    settlement = get_settlement_for_loan(ctx["loan"]["id"])
    assert settlement["gross_financed_cents"] == 100_000
    assert settlement["mdr_fee_cents"] == 6_000, "round_half_up(100000*600/10000) = 6000"
    assert settlement["net_settlement_cents"] == 94_000
    assert settlement["clawed_back_cents"] == 0
    assert settlement["status"] == "PENDING"
