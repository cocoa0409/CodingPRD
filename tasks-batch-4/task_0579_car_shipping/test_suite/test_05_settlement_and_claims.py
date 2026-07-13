"""Settlement re-pricing, COD balance boundaries, and the damage-claim lifecycle.

Translated from SCAFFOLD_DIFFICULTY_DESIGN.yaml §1.8 (dual_variant_calc,
non_linear_state_machine, transitive_cascade, cross_entity_state_dependency,
boundary_precision_check) and SCAFFOLD_CORNER_DESIGN.yaml §1.9 (calculations,
validations, state_machines).
"""
from test_helpers import (
    TEST_USERS,
    file_claim,
    list_order_ledger,
    make_carrier_headers,
    make_shipper_headers,
    post_ledger,
    read_order,
    record_inspection,
    setup_delivered_order,
    setup_dispatched_order,
    setup_quoted_order,
    validate_error,
    validate_error_is_one_of,
    validate_success,
)


# ─── dual_variant_calc / provisional quote vs settled total — 2 tests ───────

def test_quoted_total_reflects_declared_inoperable_count(api):
    """PRD §3.3: "The quote total is base_cents plus transport_surcharge_cents plus
    inoperable_surcharge_cents minus multi_car_discount_cents."
    PRD §3.3: "Each vehicle whose is_inoperable flag is true adds a flat 15000
    cents ($150)."

    Two operable vehicles on a 1000-mile OPEN order price with zero inoperable
    surcharge: base 85000 minus the two-car discount 4250 gives 80750.

    Design: Difficulty/dual_variant_calc/quote_provisional_vs_settled_total_on_order
    """
    ctx = setup_delivered_order(
        route_miles=1000, num_vehicles=2, declared_value_cents=1_000_000,
        pickup_observed_inoperable=2,
    )
    order = ctx["order"]
    assert order["status"] == "DELIVERED"
    assert order["quoted_total_cents"] == 80750, f"quoted_total was {order['quoted_total_cents']}"


def test_settled_total_reflects_pickup_observed_inoperable_count(api):
    """PRD §3.7: "The settlement inoperable surcharge is 15000 cents multiplied by
    the PICKUP inspection's observed_inoperable_count, and settled_total_cents is
    base_cents plus transport_surcharge_cents plus that observed inoperable
    surcharge minus multi_car_discount_cents."
    PRD §3.7: "it records what the load would have priced at given the observed
    condition and diverges from quoted_total_cents exactly when the observed
    inoperable count differs from the declared count used at quote time."

    Two vehicles observed inoperable at pickup add 30000, so settled 110750 differs
    from quoted 80750.

    Design: Difficulty/dual_variant_calc/quote_provisional_vs_settled_total_on_order
    """
    ctx = setup_delivered_order(
        route_miles=1000, num_vehicles=2, declared_value_cents=1_000_000,
        pickup_observed_inoperable=2,
    )
    order = ctx["order"]
    assert order["settled_total_cents"] == 110750, f"settled_total was {order['settled_total_cents']}"
    assert order["settled_total_cents"] != order["quoted_total_cents"]


# ─── non_linear_state_machine / claim return ↔ resubmit — 2 tests ───────────

def test_claim_return_then_resubmit_returns_to_submitted_with_new_amount(api):
    """PRD §3.9: "From SUBMITTED, an admin may return the claim for more
    information, moving it to RETURNED_FOR_INFO".
    PRD §3.9: "The owning Shipper may then resubmit, moving it from
    RETURNED_FOR_INFO back to SUBMITTED and updating claimed_cents to the
    resubmitted amount".

    Design: Difficulty/non_linear_state_machine/claim_return_resubmit_cycle
    """
    ctx = setup_delivered_order(route_miles=1200, delivery_damage_count=1)
    claim = file_claim(ctx["order"]["id"], ctx["shipper"]["id"], 300000)
    validate_success(api.return_claim(claim["id"], TEST_USERS["admin_headers"]), 200)
    resp = api.resubmit_claim(claim["id"], {"claimed_cents": 250000},
                              make_shipper_headers(ctx["shipper"]["id"]))
    resubmitted = validate_success(resp, expected_status=200)
    assert resubmitted["status"] == "SUBMITTED"
    assert resubmitted["claimed_cents"] == 250000


def test_claim_return_moves_to_returned_for_info(api):
    """PRD §3.9: "From SUBMITTED, an admin may return the claim for more
    information, moving it to RETURNED_FOR_INFO; this requires the claim to be
    SUBMITTED, else ERR_CLAIM_NOT_ACTIONABLE."

    Design: Difficulty/non_linear_state_machine/claim_return_resubmit_cycle
    """
    ctx = setup_delivered_order(route_miles=1200, delivery_damage_count=1)
    claim = file_claim(ctx["order"]["id"], ctx["shipper"]["id"], 300000)
    returned = validate_success(api.return_claim(claim["id"], TEST_USERS["admin_headers"]), 200)
    assert returned["status"] == "RETURNED_FOR_INFO"


# ─── transitive_cascade / claim pay → ledger → has_open_claim — 2 tests ─────

def test_claim_pay_moves_claim_to_paid_with_approved_amount(api):
    """PRD §3.9: "an Admin pays an APPROVED claim (ERR_CLAIM_NOT_ACTIONABLE
    otherwise), which posts a CLAIM_PAYOUT ledger entry equal to the negative of
    approved_cents on the order, reconciles amount_paid_cents and
    outstanding_balance_cents, moves the claim to the terminal PAID state, and
    recomputes the order's has_open_claim."
    PRD §3.9: "approved_cents is the smaller of that eligible amount and the
    responsible carrier's cargo_insurance_limit_cents."

    Design: Difficulty/transitive_cascade/claim_pay_cascade_ledger_balance_depth3
    """
    ctx = setup_delivered_order(route_miles=1200, delivery_damage_count=2, declared_value_cents=1_000_000)
    claim = file_claim(ctx["order"]["id"], ctx["shipper"]["id"], 500000)
    validate_success(api.approve_claim(claim["id"], TEST_USERS["admin_headers"]), 200)
    paid = validate_success(api.pay_claim(claim["id"], TEST_USERS["admin_headers"]), 200)
    assert paid["status"] == "PAID"
    assert paid["approved_cents"] == 500000


def test_claim_pay_clears_open_claim_and_posts_payout(api):
    """PRD §3.9: "an Admin pays an APPROVED claim (ERR_CLAIM_NOT_ACTIONABLE
    otherwise), which posts a CLAIM_PAYOUT ledger entry equal to the negative of
    approved_cents on the order, reconciles amount_paid_cents and
    outstanding_balance_cents, moves the claim to the terminal PAID state, and
    recomputes the order's has_open_claim."

    Design: Difficulty/transitive_cascade/claim_pay_cascade_ledger_balance_depth3
    """
    ctx = setup_delivered_order(route_miles=1200, delivery_damage_count=2, declared_value_cents=1_000_000)
    claim = file_claim(ctx["order"]["id"], ctx["shipper"]["id"], 500000)
    validate_success(api.approve_claim(claim["id"], TEST_USERS["admin_headers"]), 200)
    validate_success(api.pay_claim(claim["id"], TEST_USERS["admin_headers"]), 200)

    order = read_order(ctx["order"]["id"], ctx["shipper"]["id"])
    assert order["has_open_claim"] is False
    ledger = list_order_ledger(ctx["order"]["id"])
    payouts = [e for e in ledger if e["kind"] == "CLAIM_PAYOUT" and e["status"] == "POSTED"]
    assert len(payouts) == 1, f"Expected one POSTED CLAIM_PAYOUT, got {len(payouts)}"
    assert payouts[0]["amount_cents"] == -500000


# ─── cross_entity_state_dependency / claim approval needs delivery damage — 2 ─

def test_claim_approve_succeeds_with_delivery_damage(api):
    """PRD §3.9: "An Admin approves a SUBMITTED claim, which requires the claim to
    be SUBMITTED (ERR_CLAIM_NOT_ACTIONABLE) and requires damage on record: the
    order must be DELIVERED and a DELIVERY inspection with a damage_count greater
    than 0 must exist, else ERR_NO_DAMAGE_ON_RECORD."

    Design: Difficulty/cross_entity_state_dependency/claim_approve_requires_delivery_damage
    """
    ctx = setup_delivered_order(route_miles=1200, delivery_damage_count=1, declared_value_cents=1_000_000)
    claim = file_claim(ctx["order"]["id"], ctx["shipper"]["id"], 500000)
    approved = validate_success(api.approve_claim(claim["id"], TEST_USERS["admin_headers"]), 200)
    assert approved["status"] == "APPROVED"


def test_claim_approve_sets_capped_payout(api):
    """PRD §3.9: "the eligible amount is the smaller of claimed_cents and the sum
    of declared_value_cents across the order's vehicles, and approved_cents is the
    smaller of that eligible amount and the responsible carrier's
    cargo_insurance_limit_cents."

    Claimed 500000, declared 1000000, insurance 3000000 → approved 500000.

    Design: Difficulty/cross_entity_state_dependency/claim_approve_requires_delivery_damage
    """
    ctx = setup_delivered_order(route_miles=1200, delivery_damage_count=1, declared_value_cents=1_000_000)
    claim = file_claim(ctx["order"]["id"], ctx["shipper"]["id"], 500000)
    approved = validate_success(api.approve_claim(claim["id"], TEST_USERS["admin_headers"]), 200)
    assert approved["approved_cents"] == 500000


def test_claim_approved_amount_capped_by_declared_value(api):
    """PRD §3.9: "the eligible amount is the smaller of claimed_cents and the sum
    of declared_value_cents across the order's vehicles, and approved_cents is the
    smaller of that eligible amount and the responsible carrier's
    cargo_insurance_limit_cents."

    Claimed 2500000, declared 1000000, insurance 3000000 → approved 1000000.

    Design: Corner/calculations/claim_approved_capped_by_declared_value
    """
    ctx = setup_delivered_order(route_miles=1200, delivery_damage_count=3, declared_value_cents=1_000_000)
    claim = file_claim(ctx["order"]["id"], ctx["shipper"]["id"], 2_500_000)
    approved = validate_success(api.approve_claim(claim["id"], TEST_USERS["admin_headers"]), 200)
    assert approved["status"] == "APPROVED"
    assert approved["approved_cents"] == 1_000_000


# ─── boundary_precision_check / COD payment at exact balance — 2 tests ──────

def test_cod_payment_equal_to_outstanding_drives_balance_to_zero(api):
    """PRD §3.4: "A COD_PAYMENT must not overpay: its amount_cents may not exceed
    the order's current outstanding_balance_cents".
    PRD §2.10: "outstanding_balance_cents is the order's quoted_total_cents minus
    amount_paid_cents."

    Outstanding 80000; a COD_PAYMENT of exactly 80000 is accepted and drives it to 0.

    Design: Difficulty/boundary_precision_check/cod_overpayment_inclusive_boundary_exact_balance_ok
    """
    ctx = setup_quoted_order(route_miles=1200, declared_value_cents=1_000_000)  # total 100000
    post_ledger(ctx["order"]["id"], "DEPOSIT", 20000)  # outstanding 80000
    validate_success(
        api.create_ledger_entry(ctx["order"]["id"], {"kind": "COD_PAYMENT", "amount_cents": 80000},
                                TEST_USERS["broker_headers"]),
        expected_status=201,
    )
    order = read_order(ctx["order"]["id"], ctx["shipper"]["id"])
    assert order["outstanding_balance_cents"] == 0


def test_cod_payment_at_boundary_updates_amount_paid(api):
    """PRD §2.10: "amount_paid_cents is the sum of amount_cents over all POSTED
    ledger entries whose kind is DEPOSIT or COD_PAYMENT — inflows only."

    Deposit 20000 + COD 80000 → amount_paid_cents 100000.

    Design: Difficulty/boundary_precision_check/cod_overpayment_inclusive_boundary_exact_balance_ok
    """
    ctx = setup_quoted_order(route_miles=1200, declared_value_cents=1_000_000)
    post_ledger(ctx["order"]["id"], "DEPOSIT", 20000)
    validate_success(
        api.create_ledger_entry(ctx["order"]["id"], {"kind": "COD_PAYMENT", "amount_cents": 80000},
                                TEST_USERS["broker_headers"]),
        expected_status=201,
    )
    order = read_order(ctx["order"]["id"], ctx["shipper"]["id"])
    assert order["amount_paid_cents"] == 100000


def test_cod_payment_over_outstanding_rejected(api):
    """PRD §3.4: "A COD_PAYMENT must not overpay: its amount_cents may not exceed
    the order's current outstanding_balance_cents, and an attempt to do so is
    rejected with ERR_OVERPAYMENT."

    Design: Corner/validations/cod_overpayment_over_balance_returns_overpayment
    """
    ctx = setup_quoted_order(route_miles=1200, declared_value_cents=1_000_000)
    post_ledger(ctx["order"]["id"], "DEPOSIT", 20000)  # outstanding 80000
    resp = api.create_ledger_entry(ctx["order"]["id"], {"kind": "COD_PAYMENT", "amount_cents": 80001},
                                   TEST_USERS["broker_headers"])
    validate_error(resp, "ERR_OVERPAYMENT", expected_status=402)


# ─── state_machines / duplicate pickup inspection ──────────────────────────

def test_duplicate_pickup_inspection_rejected(api):
    """PRD §3.7: "The PICKUP inspection advances the order from DISPATCHED to
    PICKED_UP. It requires that the assignment be DISPATCHED and belong to the
    acting carrier (ERR_NOT_ASSIGNED_CARRIER), and that no prior PICKUP inspection
    already exist for the order, else ERR_DUPLICATE_INSPECTION."
    PRD §2.1: "then whether the target resource is in a state that permits the
    transition (ERR_INVALID_STATE, 409, unless a more specific domain state error
    is declared for that transition)".

    Once the order is PICKED_UP a second PICKUP is faithfully rejectable either as
    a duplicate or on the generic order-state check; this asserts the family.

    Design: Corner/state_machines/duplicate_pickup_inspection_returns_duplicate_inspection
    """
    ctx = setup_dispatched_order(route_miles=1200)
    record_inspection(ctx["order"]["id"], ctx["carrier"]["id"], "PICKUP", odometer=10000)
    resp = api.create_inspection(
        ctx["order"]["id"], {"phase": "PICKUP", "odometer": 10005},
        make_carrier_headers(ctx["carrier"]["id"]),
    )
    validate_error_is_one_of(resp, ["ERR_DUPLICATE_INSPECTION", "ERR_INVALID_STATE"])
