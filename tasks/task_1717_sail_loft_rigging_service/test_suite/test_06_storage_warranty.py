"""Storage program pricing, warranty rulings, and balance accounting."""
from test_helpers import (
    ApiErrorId,
    get_customer,
    get_storage_contract,
    make_customer_headers,
    setup_delivered_work_order,
    setup_order_with_qc_passed_job,
    setup_returned_storage_contract,
    setup_storage_contract,
    validate_error,
    validate_success,
    TEST_USERS,
)

MGR = TEST_USERS["loft_manager_headers"]


# ---------------------------------------------------------------------------
# Storage fee: pinned per-item-round-then-sum order — PRD §3.7
# ---------------------------------------------------------------------------

def test_storage_fee_full_wash_list_per_item_rounding(api):
    """PRD §3.7: "The fee is built in a pinned rounding order: each selected wash
    item's price — 14,550 cents for `MAIN_WASH`, 12,350 cents for `GENOA_WASH`,
    9,875 cents for `SPINNAKER_WASH`, and 21,000 cents for `RIG_WASH` — is first
    rounded half-up to whole cents individually; the rounded item fees are summed;
    and the season base determined by the boat's `hull_length_m` is added last —
    180,000 cents for hulls under 10 metres, 260,000 cents for hulls at least 10
    metres and at most 15 metres, and 390,000 cents for hulls over 15 metres.
    Sum-then-round is explicitly rejected; the per-item rounding must happen
    first."

    Design: Difficulty/combinatorial_formula/storage_fee_per_item_round_then_sum_mode_b
    """
    ctx = setup_storage_contract(
        hull_length_m=12.0,
        wash_item_codes=["MAIN_WASH", "GENOA_WASH", "SPINNAKER_WASH", "RIG_WASH"],
    )
    received = validate_success(
        api.receive_storage_contract(ctx["boat"]["id"], ctx["contract"]["id"], MGR)
    )
    assert received["contract_status"] == "RECEIVED"
    # 260000 + (14550 + 12350 + 9875 + 21000) = 260000 + 57775 = 317775
    assert received["quoted_storage_fee_cents"] == 317775, (
        f"got {received['quoted_storage_fee_cents']}"
    )


def test_storage_fee_tier_boundary_at_10m(api):
    """PRD §3.7: "the season base determined by the boat's `hull_length_m` is
    added last — 180,000 cents for hulls under 10 metres, 260,000 cents for hulls
    at least 10 metres and at most 15 metres, and 390,000 cents for hulls over 15
    metres."

    Design: Difficulty/combinatorial_formula/storage_fee_per_item_round_then_sum_mode_b
    """
    ctx = setup_storage_contract(hull_length_m=10.0, wash_item_codes=["MAIN_WASH"])
    received = validate_success(
        api.receive_storage_contract(ctx["boat"]["id"], ctx["contract"]["id"], MGR)
    )
    # Exactly 10 m lands in the "at least 10 and at most 15" tier: 260000 + 14550.
    assert received["quoted_storage_fee_cents"] == 274550, (
        f"got {received['quoted_storage_fee_cents']}"
    )


# ---------------------------------------------------------------------------
# Warranty REPAIR credit restores the balance — PRD §3.5
# ---------------------------------------------------------------------------

def test_repair_ruling_credits_invoice_back(api):
    """PRD §3.5: "A `REPAIR` ruling moves the order from `WARRANTY_REVIEW` to
    `WARRANTY_REPAIR`: the work continues at no charge, the order's
    `warranty_flag` is set to true, and the invoice is credited back by reducing
    the customer's `outstanding_balance_cents` by the order's
    `invoiced_total_cents`, floored at zero."

    Design: Difficulty/compensating_invariant/customer_outstanding_balance_restored_after_warranty_repair_credit
    """
    ctx = setup_delivered_work_order(cloth_tier="RACE", option_codes=[], fitted_option_codes=[])
    order = ctx["work_order"]
    assert order["invoiced_total_cents"] == 584250  # 61.50 * 9500
    customer_id = ctx["customer"]["id"]
    assert get_customer(customer_id)["outstanding_balance_cents"] == 584250

    claimed = validate_success(
        api.open_warranty_claim(order["id"], {"claim_reason": "seam split on first sail"},
                                make_customer_headers(customer_id))
    )
    assert claimed["order_status"] == "WARRANTY_REVIEW"

    ruled = validate_success(api.rule_warranty(order["id"], {"ruling": "REPAIR"}, MGR))
    assert ruled["order_status"] == "WARRANTY_REPAIR"
    assert ruled["warranty_flag"] is True
    balance = get_customer(customer_id)["outstanding_balance_cents"]
    assert balance == 0, f"charge 584250 + credit 584250 must conserve the balance at 0, got {balance}"


def test_repair_credit_floors_balance_at_zero(api):
    """PRD §2.8: "Credits can never drive the balance below zero: both payment
    application and warranty write-off floor the resulting balance at zero."
    PRD §3.5: "the invoice is credited back by reducing the customer's
    `outstanding_balance_cents` by the order's `invoiced_total_cents`, floored at
    zero."

    Design: Difficulty/compensating_invariant/customer_outstanding_balance_restored_after_warranty_repair_credit
    """
    ctx = setup_delivered_work_order(cloth_tier="RACE", option_codes=[], fitted_option_codes=[])
    order = ctx["work_order"]
    customer_id = ctx["customer"]["id"]
    # Pay down most of the 584250 invoice so the REPAIR credit exceeds the rest.
    paid = validate_success(api.record_payment(customer_id, {"amount_cents": 500000}, MGR), expected_status=201)
    assert paid["outstanding_balance_cents"] == 84250

    validate_success(
        api.open_warranty_claim(order["id"], {"claim_reason": "delamination"},
                                make_customer_headers(customer_id))
    )
    ruled = validate_success(api.rule_warranty(order["id"], {"ruling": "REPAIR"}, MGR))
    assert ruled["order_status"] == "WARRANTY_REPAIR"
    balance = get_customer(customer_id)["outstanding_balance_cents"]
    assert balance == 0, f"84250 - 584250 must floor at 0, got {balance}"


# ---------------------------------------------------------------------------
# Corner: storage fee edges, invalid skip, payment floor, immediate consistency
# ---------------------------------------------------------------------------

def test_storage_fee_empty_wash_list_returns_base_only(api):
    """PRD §3.7: "an optional `wash_item_codes` array selecting from `MAIN_WASH`,
    `GENOA_WASH`, `SPINNAKER_WASH`, and `RIG_WASH` — defaulting to empty, with
    each selected item priced individually" and "180,000 cents for hulls under 10
    metres".

    Design: Corner/calculations/storage_fee_empty_wash_list_returns_base_only
    """
    ctx = setup_storage_contract(hull_length_m=8.0, wash_item_codes=[])
    received = validate_success(
        api.receive_storage_contract(ctx["boat"]["id"], ctx["contract"]["id"], MGR)
    )
    assert received["quoted_storage_fee_cents"] == 180000, (
        f"empty wash list must price the season base only, got {received['quoted_storage_fee_cents']}"
    )


def test_storage_contract_cannot_skip_enrolled_to_stored(api):
    """PRD §3.7: "From there the contract walks the yard's rhythm, each step a
    `LoftManager` action: completing the wash moves `RECEIVED` to `WASHED`,
    racking the boat moves `WASHED` to `STORED`" — racking is only legal from
    `WASHED`, and PRD §2.5: "Fourth, the generic source-state legality of the
    requested transition is verified (failure yields `ERR_INVALID_STATE`,
    HTTP 409)."

    Design: Corner/state_machines/storage_contract_invalid_skip_enrolled_to_stored
    """
    ctx = setup_storage_contract(hull_length_m=9.0, wash_item_codes=[])
    resp = api.rack_store(ctx["boat"]["id"], ctx["contract"]["id"], MGR)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    after = get_storage_contract(ctx["contract"]["id"])
    assert after["contract_status"] == "ENROLLED", (
        f"rejected skip must leave the contract ENROLLED, got {after['contract_status']}"
    )


def test_payment_floors_outstanding_balance_at_zero(api):
    """PRD §3.1: "Recording a payment is a `LoftManager` action that takes an
    `amount_cents` and reduces the customer's `outstanding_balance_cents` by that
    amount, floored at zero."

    Design: Corner/endpoints/payment_reduces_outstanding_balance_with_floor_zero
    """
    # A returned storage contract bills 260000 + 14550 = 274550 to the customer.
    ctx = setup_returned_storage_contract(hull_length_m=12.0, wash_item_codes=["MAIN_WASH"])
    customer_id = ctx["customer"]["id"]
    assert get_customer(customer_id)["outstanding_balance_cents"] == 274550

    paid = validate_success(
        api.record_payment(customer_id, {"amount_cents": 999999}, MGR), expected_status=201
    )
    assert paid["outstanding_balance_cents"] == 0, (
        f"over-payment must floor the balance at 0, got {paid['outstanding_balance_cents']}"
    )


def test_confirm_delivery_balance_visible_immediately(api):
    """PRD §3.5: "The invoiced amount is then debited to the customer: their
    `outstanding_balance_cents` increases by `invoiced_total_cents`." — the debit
    is part of the confirmation, so the very next read shows it.

    Design: Corner/consistency_model/confirm_delivery_balance_visible_in_same_read
    """
    ctx = setup_order_with_qc_passed_job(cloth_tier="RACE")
    order = validate_success(
        api.confirm_delivery(ctx["work_order"]["id"], {"fitted_option_codes": []},
                             make_customer_headers(ctx["customer"]["id"]))
    )
    assert order["order_status"] == "DELIVERED"
    assert order["invoiced_total_cents"] == 584250  # 61.50 * 9500

    customer = validate_success(api.get_customer(ctx["customer"]["id"], MGR))
    assert customer["outstanding_balance_cents"] == 584250, (
        f"invoice debit must be visible immediately, got {customer['outstanding_balance_cents']}"
    )
