"""Delivery, the 110% rule, and the revenue waterfall (PRD 3.7, 3.8, 2.9, 2.10)."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assert_revenue_statement,
    assert_waterfall_conservation,
    deliver_order,
    delivered_additional_order,
    get_order,
    get_statement_for_order,
    register_order,
    setup_delivered_order,
    setup_in_transit_order,
    setup_network,
    setup_registered_order,
    staff_order,
    validate_error,
    validate_success,
    get_success_data,
)

ADMIN = TEST_USERS["van_line_admin_headers"]


# ---------------------------------------------------------------------------
# Dual variant: BINDING vs NON_BINDING final charges
# ---------------------------------------------------------------------------
def test_binding_final_charges_lock_estimate_regardless_of_scale(api):
    """PRD section 3.7: "For a `BINDING` order the final invoice equals the
    accepted estimate's `estimated_charges_cents` verbatim — actual scale weight
    never changes it. For a `NON_BINDING` order the linehaul and fuel components
    are recomputed over the authoritative weight (the original weighment, or an
    applied re-weigh) using the linehaul algorithm of §3.3, and combined with the
    locked coverage's premium and the accepted estimate's packing charge."
    PRD section 3.7: "The `deferred_balance_cents` is the final charges minus the
    delivery amount due — zero for `BINDING` orders, and zero whenever the final
    charges do not exceed the cap; the boundary is inclusive, so when the final
    charges equal the cap exactly, the whole amount is demandable and the deferred
    balance is zero."

    Design: Difficulty/dual_variant_calc/binding_vs_non_binding_final_charges
    """
    ctx = setup_delivered_order(
        pricing_mode="BINDING", estimated_weight_lbs=8000, actual_weight_lbs=9600
    )
    order = ctx["order"]
    # 8000 lbs estimate: 80 cwt * 4500 * 1.2 = 432000 + 43200 fuel = 475200.
    assert order["final_charges_cents"] == 475200, (
        f"binding basis locks the estimate even though the scale showed 9600 lbs, got {order['final_charges_cents']}"
    )
    assert order["delivery_amount_due_cents"] == 475200
    assert order["deferred_balance_cents"] == 0


def test_non_binding_final_charges_recomputed_with_cap(api):
    """PRD section 3.7: "For a `NON_BINDING` order the linehaul and fuel
    components are recomputed over the authoritative weight (the original
    weighment, or an applied re-weigh) using the linehaul algorithm of §3.3, and
    combined with the locked coverage's premium and the accepted estimate's
    packing charge. The federal collection cap is one hundred ten percent of the
    accepted estimate's `estimated_charges_cents`, rounded half up. The amount
    lawfully demandable at the curb, `delivery_amount_due_cents`, is the smaller
    of the final charges and the cap for a `NON_BINDING` order, and the full final
    charges for a `BINDING` order."

    Design: Difficulty/dual_variant_calc/binding_vs_non_binding_final_charges
    """
    binding = setup_delivered_order(
        pricing_mode="BINDING", estimated_weight_lbs=8000, actual_weight_lbs=9600
    )
    # The second order shares the first order's published tariff — PRD 2.8
    # forbids publishing a second tariff over the same pickup window.
    non_binding = delivered_additional_order(
        binding, pricing_mode="NON_BINDING", estimated_weight_lbs=8000, actual_weight_lbs=9600
    )
    nb = non_binding["order"]
    # 96 cwt * 4500 * 1.2 = 518400 + 51840 fuel = 570240 final.
    assert nb["final_charges_cents"] == 570240, (
        f"non-binding basis prices the actual 96 cwt, got {nb['final_charges_cents']}"
    )
    # cap = round_half_up(1.10 * 475200) = 522720 binds.
    assert nb["delivery_amount_due_cents"] == 522720
    assert nb["deferred_balance_cents"] == 47520

    diff = nb["final_charges_cents"] - binding["order"]["final_charges_cents"]
    assert diff == 95040, (
        f"identical physical data must differ by exactly 95040 across pricing modes, got {diff}"
    )


# ---------------------------------------------------------------------------
# Exact 110% boundary
# ---------------------------------------------------------------------------
def test_delivery_cap_exact_110_percent_zero_deferred(api):
    """PRD section 3.7: "The federal collection cap is one hundred ten percent of
    the accepted estimate's `estimated_charges_cents`, rounded half up. The amount
    lawfully demandable at the curb, `delivery_amount_due_cents`, is the smaller
    of the final charges and the cap for a `NON_BINDING` order, and the full final
    charges for a `BINDING` order. The `deferred_balance_cents` is the final
    charges minus the delivery amount due — zero for `BINDING` orders, and zero
    whenever the final charges do not exceed the cap; the boundary is inclusive,
    so when the final charges equal the cap exactly, the whole amount is
    demandable and the deferred balance is zero."

    Design: Difficulty/boundary_precision_check/delivery_cap_exact_110_percent_zero_deferred
    """
    ctx = setup_delivered_order(
        pricing_mode="NON_BINDING", estimated_weight_lbs=8000, actual_weight_lbs=8800
    )
    order = ctx["order"]
    # 88 cwt * 4500 * 1.2 = 475200 + 47520 = 522720 == round_half_up(1.10 * 475200).
    assert order["final_charges_cents"] == 522720
    assert order["delivery_amount_due_cents"] == 522720, (
        "final == cap exactly: the inclusive min demands the full amount"
    )
    assert order["deferred_balance_cents"] == 0


def test_payment_rejected_when_no_deferred_balance(api):
    """PRD section 3.7: "The payment is permitted only while `billing_status` is
    `FINAL_BILLED` and a `deferred_balance_cents` greater than zero remains
    (otherwise `ERR_NO_BALANCE_DUE`), and the amount must equal the deferred
    balance exactly (otherwise `ERR_PAYMENT_AMOUNT_MISMATCH`); a successful
    payment moves `billing_status` to `PAID` and bumps the order's `version`."

    Design: Difficulty/boundary_precision_check/delivery_cap_exact_110_percent_zero_deferred
    """
    ctx = setup_delivered_order(
        pricing_mode="NON_BINDING", estimated_weight_lbs=8000, actual_weight_lbs=8800
    )
    assert ctx["order"]["deferred_balance_cents"] == 0
    resp = api.post_payment(ctx["order"]["id"], {"amount_cents": 1}, ctx["cust_h"])
    validate_error(resp, ApiErrorId.ERR_NO_BALANCE_DUE)


# ---------------------------------------------------------------------------
# Deliver cascade: statement -> assignments -> agent ledgers
# ---------------------------------------------------------------------------
def test_deliver_creates_provisional_statement_with_waterfall(api):
    """PRD section 3.7: "The order lands in `DELIVERED` with its `version` bumped,
    and three cascade hops follow. Hop one: the order's single `RevenueStatement`
    is created in `PROVISIONAL` with the revenue waterfall of §3.8 computed and
    its share fields written, and every `PERFORMED` re-weigh request on the order
    flips to `EXPIRED`."
    PRD section 3.8: "The van line takes the residual — the basis minus the four
    role shares — subject to a floor. The floor is four percent of the basis,
    rounded half up. When the residual falls short of the floor, the shortfall is
    carved out of the `HAULING` share — always `HAULING`, pinned, never pro-rated
    across buckets — and the van line's share is set to the floor."

    Design: Difficulty/transitive_cascade/deliver_cascade_statement_assignment_agent_ledger
    """
    ctx = setup_delivered_order(
        pricing_mode="NON_BINDING", estimated_weight_lbs=8000, actual_weight_lbs=9600
    )
    statement = ctx["statement"]
    assert_revenue_statement(statement)
    assert statement["status"] == "PROVISIONAL", "hop 1: created by the order mutation"
    # L = 570240, all agents STANDARD: 10% / 20% / 54% / 10%.
    assert statement["linehaul_revenue_cents"] == 570240
    assert statement["booking_share_cents"] == 57024
    assert statement["origin_share_cents"] == 114048
    assert statement["hauling_share_cents"] == 307930
    assert statement["destination_share_cents"] == 57024
    # residual 34214 >= floor 22810 -> the floor branch does not fire.
    assert statement["van_line_share_cents"] == 34214


def test_deliver_completes_assignments_and_credits_agent_ledgers(api):
    """PRD section 3.7: "Hop two: every `CONFIRMED` agent assignment on the order
    becomes `COMPLETED` with its `split_amount_cents` written per the waterfall.
    Hop three: each completed assignment credits its `split_amount_cents` to the
    holding agent's `ytd_linehaul_share_cents` ledger, bumping each such agent's
    `version`."
    PRD section 2.9: "An agent's `ytd_linehaul_share_cents` is a running ledger of
    linehaul earnings: when a revenue statement is created at delivery, each
    completed assignment's `split_amount_cents` is added to the holding agent's
    ledger."

    Design: Difficulty/transitive_cascade/deliver_cascade_statement_assignment_agent_ledger
    """
    ctx = setup_delivered_order(
        pricing_mode="NON_BINDING", estimated_weight_lbs=8000, actual_weight_lbs=9600
    )
    hauling = get_success_data(
        api.get_agent_assignment(ctx["assignments"]["HAULING"]["id"], ADMIN)
    )
    assert hauling["status"] == "COMPLETED", "hop 2: caused by statement creation"
    assert hauling["split_amount_cents"] == 307930

    haul_agent = get_success_data(api.get_agent(ctx["hauling_agent"]["id"], ADMIN))
    assert haul_agent["ytd_linehaul_share_cents"] == 307930, "hop 3: assignment mutation credits the ledger"
    book_agent = get_success_data(api.get_agent(ctx["booking_agent"]["id"], ADMIN))
    assert book_agent["ytd_linehaul_share_cents"] == 57024


# ---------------------------------------------------------------------------
# Waterfall with tier bonuses and a binding floor
# ---------------------------------------------------------------------------
def _setup_floor_binding_statement():
    """L = 570240 with Origin PREFERRED (+0.01) and Hauling PREMIER (+0.02) so the
    van-line 4% floor binds and the deficit lands on HAULING."""
    return setup_delivered_order(
        pricing_mode="NON_BINDING",
        estimated_weight_lbs=8000,
        actual_weight_lbs=9600,
        origin_tier="PREFERRED",
        hauling_tier="PREMIER",
    )


def test_waterfall_shares_include_commission_tier_bonuses(api):
    """PRD section 3.8: "The waterfall divides `linehaul_revenue_cents` across the
    four `CONFIRMED` agent assignments in a pinned bucket order — `BOOKING` first,
    then `ORIGIN`, then `HAULING`, then `DESTINATION`. Each bucket's effective
    percentage is the role's base — ten percent for `BOOKING`, twenty percent for
    `ORIGIN`, fifty-four percent for `HAULING`, and ten percent for `DESTINATION`
    — plus the commission-tier bonus of the agent holding that assignment: no
    bonus for `STANDARD`, one percentage point for `PREFERRED`, and two percentage
    points for `PREMIER`."

    Design: Difficulty/combinatorial_formula/revenue_split_waterfall_floor_binds
    """
    ctx = _setup_floor_binding_statement()
    statement = ctx["statement"]
    assert statement["linehaul_revenue_cents"] == 570240
    assert statement["booking_share_cents"] == 57024, "0.10 * L"
    # round_half_up(0.21 * 570240) = round_half_up(119750.4)
    assert statement["origin_share_cents"] == 119750
    assert statement["destination_share_cents"] == 57024
    # round_half_up(0.56 * L) = 319334 minus the floor deficit 5702.
    assert statement["hauling_share_cents"] == 313632, (
        f"the floor deficit is carved out of HAULING, got {statement['hauling_share_cents']}"
    )


def test_waterfall_floor_binds_and_conservation_holds(api):
    """PRD section 3.8: "The van line takes the residual — the basis minus the
    four role shares — subject to a floor. The floor is four percent of the basis,
    rounded half up. When the residual falls short of the floor, the shortfall is
    carved out of the `HAULING` share — always `HAULING`, pinned, never pro-rated
    across buckets — and the van line's share is set to the floor."
    PRD section 3.8: "A conservation invariant holds at all times: the four role
    shares plus the van-line share net of the valuation premium equal
    `linehaul_revenue_cents` exactly."

    Design: Difficulty/combinatorial_formula/revenue_split_waterfall_floor_binds
    """
    ctx = _setup_floor_binding_statement()
    statement = ctx["statement"]
    # raw residual 17108 < floor round_half_up(0.04 * 570240) = 22810 -> floor binds.
    assert statement["van_line_share_cents"] == 22810, (
        f"van line share is set to the floor, got {statement['van_line_share_cents']}"
    )
    assert_waterfall_conservation(statement, valuation_premium_cents=0)


# ---------------------------------------------------------------------------
# Validation precedence: state gate beats the fiscal gate on deliver
# ---------------------------------------------------------------------------
def _setup_registered_with_destination_assignment(api):
    ctx = setup_registered_order(pricing_mode="NON_BINDING", mileage=1200)
    proposal = get_success_data(
        api.create_agent_assignment(
            ctx["order"]["id"],
            {"agent_id": ctx["destination_agent"]["id"], "role": "DESTINATION"},
            ctx["booking_h"],
        )
    )
    get_success_data(api.confirm_agent_assignment(proposal["id"], ctx["dest_h"]))
    return ctx


def test_deliver_state_error_precedes_fiscal_check(api):
    """PRD section 2.10: "Every request is evaluated against a fixed validation
    pipeline, and a request rejected at an earlier stage never reaches a later
    one."
    PRD section 2.10: "Lifecycle-state gates — from-state and sub-state
    preconditions on the target resource, endpoint by endpoint (HTTP 409)."
    PRD section 2.10: "Money gates — delivery collection, deferred-balance
    payment, settlement-offer caps, arbitration award ranges (HTTP 422)."
    PRD section 3.7: "the order is `IN_TRANSIT` or `OUT_FOR_DELIVERY` (from any
    other state, `ERR_TRANSITION_NOT_ALLOWED`)"

    Design: Difficulty/priority_pair_validation_conflict/deliver_state_error_precedes_fiscal_check
    """
    ctx = _setup_registered_with_destination_assignment(api)
    # Wildly wrong collected amount would also fail the fiscal check — the state
    # error must win anyway.
    resp = api.deliver_order(
        ctx["order"]["id"], {"collected_at_delivery_cents": 999999}, ctx["dest_h"]
    )
    validate_error(resp, ApiErrorId.ERR_TRANSITION_NOT_ALLOWED)
    order = get_order(ctx["order"]["id"])
    assert order["status"] == "REGISTERED"


def test_deliver_state_gate_fires_with_proposed_staffing(api):
    """PRD section 2.10: "Every request is evaluated against a fixed validation
    pipeline, and a request rejected at an earlier stage never reaches a later
    one."
    PRD section 3.7: "Delivery is completed by the destination agent through four
    gates evaluated in this written order: the order is `IN_TRANSIT` or
    `OUT_FOR_DELIVERY` (from any other state, `ERR_TRANSITION_NOT_ALLOWED`); no
    SIT lot on the order is still `IN_STORAGE` (else `ERR_SHIPMENT_IN_STORAGE` —
    recall that a `CONVERTED_PERMANENT` lot does not block); no re-weigh request
    on the order is still `REQUESTED` (else `ERR_REWEIGH_PENDING`, and the
    customer must cancel the pending request first — a performed-but-unapplied
    re-weigh does not block and instead expires in the cascade below); and the
    payload's `collected_at_delivery_cents` equals the freshly recomputed
    `delivery_amount_due_cents` (a mismatch is `ERR_DELIVERY_PAYMENT_MISMATCH`,
    HTTP 422)."

    Design: Difficulty/priority_pair_validation_conflict/deliver_state_error_precedes_fiscal_check
    """
    ctx = setup_registered_order(pricing_mode="NON_BINDING", mileage=1200)
    # Destination assignment only PROPOSED: ownership scoping still passes, and
    # the lifecycle-state gate fires before any money check.
    get_success_data(
        api.create_agent_assignment(
            ctx["order"]["id"],
            {"agent_id": ctx["destination_agent"]["id"], "role": "DESTINATION"},
            ctx["booking_h"],
        )
    )
    resp = api.deliver_order(
        ctx["order"]["id"], {"collected_at_delivery_cents": 999999}, ctx["dest_h"]
    )
    validate_error(resp, ApiErrorId.ERR_TRANSITION_NOT_ALLOWED)
    order = get_order(ctx["order"]["id"])
    assert order["status"] == "REGISTERED"


# ---------------------------------------------------------------------------
# Deferred-balance payment and immediate consistency
# ---------------------------------------------------------------------------
def test_payment_must_match_deferred_balance_exactly(api):
    """PRD section 3.7: "The payment is permitted only while `billing_status` is
    `FINAL_BILLED` and a `deferred_balance_cents` greater than zero remains
    (otherwise `ERR_NO_BALANCE_DUE`), and the amount must equal the deferred
    balance exactly (otherwise `ERR_PAYMENT_AMOUNT_MISMATCH`); a successful
    payment moves `billing_status` to `PAID` and bumps the order's `version`."

    Design: Corner/validations/payment_must_match_deferred_balance_exactly
    """
    ctx = setup_delivered_order(
        pricing_mode="NON_BINDING", estimated_weight_lbs=8000, actual_weight_lbs=9600
    )
    assert ctx["order"]["deferred_balance_cents"] == 47520

    short = api.post_payment(ctx["order"]["id"], {"amount_cents": 47519}, ctx["cust_h"])
    validate_error(short, ApiErrorId.ERR_PAYMENT_AMOUNT_MISMATCH)

    paid = get_success_data(
        api.post_payment(ctx["order"]["id"], {"amount_cents": 47520}, ctx["cust_h"])
    )
    assert paid["billing_status"] == "PAID", "exact payment of the deferred balance flips to PAID"


def test_deliver_response_reflects_all_mutations_immediately(api):
    """PRD section 3.7: "A successful delivery sets `final_charges_cents`,
    refreshes `delivery_amount_due_cents` and `deferred_balance_cents`, records
    the collected amount in `collected_at_delivery_cents`, stamps `delivered_at`
    from the logical clock, and moves `billing_status` to `FINAL_BILLED` — and for
    a `BINDING` order straight on to `PAID` within the same transition."
    PRD section 2.2: "Unless otherwise noted, operations that create or modify a
    resource will return the created or updated resource object in the data field."
    PRD section 3.8: "Exactly one `RevenueStatement` exists per order, created
    automatically at delivery in `PROVISIONAL` status."

    Design: Corner/consistency_model/deliver_response_reflects_all_mutations_immediately
    """
    ctx = setup_in_transit_order(
        pricing_mode="NON_BINDING", estimated_weight_lbs=8000, actual_weight_lbs=9600
    )
    resp = api.deliver_order(
        ctx["order"]["id"], {"collected_at_delivery_cents": 522720}, ctx["dest_h"]
    )
    data = validate_success(resp)
    # The deliver response body itself carries every mutation.
    assert data["final_charges_cents"] == 570240
    assert data["delivery_amount_due_cents"] == 522720
    assert data["deferred_balance_cents"] == 47520
    assert data["billing_status"] == "FINAL_BILLED"
    assert data["status"] == "DELIVERED"

    statement = get_statement_for_order(ctx["order"]["id"])
    assert statement["status"] == "PROVISIONAL", (
        "the cascade is visible in the same logical instant"
    )
