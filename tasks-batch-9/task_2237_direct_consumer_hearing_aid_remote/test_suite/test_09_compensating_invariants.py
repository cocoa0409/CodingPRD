"""Compensating actions: each one must restore or preserve a conservation identity.

Three identities are exercised here — cash on a device order, unit counts on an
inventory pool, and benefit allocation on a reimbursement claim — each observed both
before the compensating action and after it.
"""
from test_helpers import (
    CARE_OPS,
    COMPLIANCE,
    REIMBURSEMENT,
    REIMBURSEMENT_2,
    api_client,
    assert_benefit_conservation,
    assert_cash_conservation,
    assert_inventory_conservation,
    create_inventory_pool,
    get_pool,
    get_success_data,
    make_patient_headers,
    setup_delivered_order,
    setup_return_settled,
    validate_success,
)

# --- cash: settlement then restocking waiver ------------------------------
RETURN_ISSUED_AT_UTC = "2026-08-07T00:00:00Z"
CAPTURED_CENTS = 210096
RESTOCKING_FEE_CENTS = 19225
NON_REFUNDABLE_SHIPPING_CENTS = 1495
SETTLED_REFUND_CENTS = 189376
SETTLED_RETAINED_CENTS = 20720

# --- inventory: exchange reservation then cancellation --------------------
SOURCE_POOL_UNITS = 5
TARGET_POOL_UNITS = 3
TARGET_DOME_SIZE = "L"
TARGET_TIP_TYPE = "CLOSED"

# --- benefit: waterfall then void ----------------------------------------
CLAIMED_AMOUNT_CENTS = 150000
INSURANCE_CAP_CENTS = 100000
INSURANCE_USED_CENTS = 40000
FSA_BALANCE_CENTS = 25000
EXPECTED_ELIGIBLE_CENTS = 150000
EXPECTED_INSURANCE_PAID_CENTS = 60000
EXPECTED_FSA_PAID_CENTS = 25000
EXPECTED_PATIENT_RESPONSIBILITY_CENTS = 65000
DEVICE_ORDER_DOCUMENT_CODES = ["INVOICE", "AUDIOGRAM_OR_WAIVER", "PROOF_OF_PAYMENT", "LMN"]


# ---------------------------------------------------------------------------
# Cash conservation
# ---------------------------------------------------------------------------
def _setup_partially_refunded_order() -> dict:
    """A whole-order RESELLABLE return settled seven days into a 30-day trial."""
    return setup_return_settled(
        inspection_grade="RESELLABLE",
        at_iso=RETURN_ISSUED_AT_UTC,
        policy_overrides={"trial_period_days": 30},
    )


def test_settlement_retains_restocking_and_shipping_with_cash_conserved():
    """"a settlement whose `restocking_fee_cents` plus `non_refundable_shipping_cents` exceeds 0 with
    a positive `refund_amount_cents` moves `CAPTURED → PARTIALLY_REFUNDED`, adding
    `refund_amount_cents` to `refunded_cents` and adding the retained restocking plus
    non-refundable shipping to `retained_cents`, then recomputing `open_balance_cents` — which
    should reach 0 on a whole-order return." (PRD §3.6)

    "For a whole-order return, `refund_amount_cents` plus `restocking_fee_cents` plus
    `non_refundable_shipping_cents` equals `captured_cents` exactly." (PRD §3.6)

    Design: Difficulty/compensating_invariant/cash_conservation_restored_by_restocking_waiver
    """
    env = _setup_partially_refunded_order()

    rma = validate_success(api_client.get_return_authorization(env["rma"]["id"], CARE_OPS))
    assert rma["status"] == "REFUND_SETTLED", (
        f"the authorization must be settled before a waiver applies, got {rma['status']!r}"
    )
    assert rma["restocking_variant"] == "FLAT_PCT", (
        "a FLAT_PCT pinned mode with a non-zero days_used_at_issue yields the FLAT_PCT variant, got "
        f"{rma['restocking_variant']!r}"
    )
    assert rma["restocking_fee_cents"] == RESTOCKING_FEE_CENTS, (
        "19000 on the device component plus 225 on the accessory component is "
        f"{RESTOCKING_FEE_CENTS}, got {rma['restocking_fee_cents']}"
    )
    assert rma["non_refundable_shipping_cents"] == NON_REFUNDABLE_SHIPPING_CENTS, (
        "a policy with shipping_refundable false retains the order's shipping of "
        f"{NON_REFUNDABLE_SHIPPING_CENTS}, got {rma['non_refundable_shipping_cents']}"
    )
    assert rma["refund_amount_cents"] == SETTLED_REFUND_CENTS, (
        f"{CAPTURED_CENTS} minus {RESTOCKING_FEE_CENTS} minus {NON_REFUNDABLE_SHIPPING_CENTS} is "
        f"{SETTLED_REFUND_CENTS}, got {rma['refund_amount_cents']}"
    )

    order = validate_success(api_client.get_device_order(env["order"]["id"], CARE_OPS))
    assert order["payment_status"] == "PARTIALLY_REFUNDED", (
        f"a retained settlement lands on PARTIALLY_REFUNDED, got {order['payment_status']!r}"
    )
    assert order["captured_cents"] == CAPTURED_CENTS, (
        f"captured_cents is untouched by a refund, expected {CAPTURED_CENTS}, got "
        f"{order['captured_cents']}"
    )
    assert order["refunded_cents"] == SETTLED_REFUND_CENTS, (
        f"refunded_cents must be {SETTLED_REFUND_CENTS}, got {order['refunded_cents']}"
    )
    assert order["retained_cents"] == SETTLED_RETAINED_CENTS, (
        f"restocking plus non-refundable shipping is {SETTLED_RETAINED_CENTS}, got "
        f"{order['retained_cents']}"
    )
    assert order["open_balance_cents"] == 0, (
        f"a whole-order return closes the open balance, got {order['open_balance_cents']}"
    )
    assert_cash_conservation(order)


def test_restocking_waiver_moves_retained_value_into_refunded():
    """"A compliance officer may afterwards waive retained restocking, optionally with a
    `reason_note`, provided the settled authorization's `restocking_fee_cents` is above 0 and the
    clock is within 30 days of `settled_at`. This compensating action moves the payment dimension
    `PARTIALLY_REFUNDED → REFUNDED`, refunding the retained amount so that `refunded_cents` equals
    `captured_cents`, `retained_cents` becomes 0 and `open_balance_cents` becomes 0, and rewriting
    the authorization's `restocking_variant` to `WAIVED` with `restocking_fee_cents` and
    `non_refundable_shipping_cents` set to 0 and `refund_amount_cents` set to `captured_cents`.
    Cash conservation holds before and after." (PRD §3.6)

    Design: Difficulty/compensating_invariant/cash_conservation_restored_by_restocking_waiver
    """
    env = _setup_partially_refunded_order()
    before = validate_success(api_client.get_device_order(env["order"]["id"], CARE_OPS))
    assert_cash_conservation(before)

    validate_success(
        api_client.waive_restocking(
            env["rma"]["id"], {"reason_note": "goodwill waiver after review"}, COMPLIANCE
        )
    )

    rma = validate_success(api_client.get_return_authorization(env["rma"]["id"], CARE_OPS))
    assert rma["restocking_variant"] == "WAIVED", (
        f"the waiver rewrites the variant to WAIVED, got {rma['restocking_variant']!r}"
    )
    assert rma["restocking_fee_cents"] == 0, (
        f"the waived restocking fee must be 0, got {rma['restocking_fee_cents']}"
    )
    assert rma["non_refundable_shipping_cents"] == 0, (
        f"the waiver also zeroes non-refundable shipping, got {rma['non_refundable_shipping_cents']}"
    )
    assert rma["refund_amount_cents"] == CAPTURED_CENTS, (
        f"refund_amount_cents becomes captured_cents {CAPTURED_CENTS}, got "
        f"{rma['refund_amount_cents']}"
    )

    order = validate_success(api_client.get_device_order(env["order"]["id"], CARE_OPS))
    assert order["payment_status"] == "REFUNDED", (
        f"the waiver completes the refund, got {order['payment_status']!r}"
    )
    assert order["captured_cents"] == CAPTURED_CENTS, (
        f"the waiver moves value between counters without changing captured_cents, got "
        f"{order['captured_cents']}"
    )
    assert order["refunded_cents"] == CAPTURED_CENTS, (
        f"refunded_cents must equal captured_cents {CAPTURED_CENTS}, got {order['refunded_cents']}"
    )
    assert order["retained_cents"] == 0, (
        f"retained_cents must be 0 after the waiver, got {order['retained_cents']}"
    )
    assert order["open_balance_cents"] == 0, (
        f"open_balance_cents must be 0 after the waiver, got {order['open_balance_cents']}"
    )
    assert_cash_conservation(order)


# ---------------------------------------------------------------------------
# Inventory conservation
# ---------------------------------------------------------------------------
def _setup_reserved_fit_exchange() -> dict:
    """Delivered NEO-M-OPEN order with a RESERVED exchange against a NEO-L-CLOSED pool."""
    env = setup_delivered_order()
    env["target_pool"] = create_inventory_pool(
        restock_units=TARGET_POOL_UNITS,
        sku=f"NEO-{TARGET_DOME_SIZE}-{TARGET_TIP_TYPE}",
        model="NEO",
        dome_size=TARGET_DOME_SIZE,
        tip_type=TARGET_TIP_TYPE,
    )
    order = validate_success(api_client.get_device_order(env["order"]["id"], CARE_OPS))
    env["patient_headers"] = make_patient_headers(env["patient"]["id"])
    env["exchange"] = get_success_data(
        api_client.create_fit_exchange(
            env["order"]["id"],
            {
                "to_dome_size": TARGET_DOME_SIZE,
                "to_tip_type": TARGET_TIP_TYPE,
                "expected_device_order_version": order["version"],
            },
            env["patient_headers"],
        )
    )
    return env


def test_fit_exchange_reservation_holds_a_unit_without_breaking_conservation():
    """"Reservation happens in the same request, so an accepted request lands in `RESERVED`: the
    server writes `to_inventory_pool_id` and `from_inventory_pool_id`, decrements the target pool's
    `on_hand_units` and increments its `reserved_units`, computes `exchange_fee_cents`, and
    increments the order's `version` by one." (PRD §3.6)

    "And every `InventoryPool` satisfies an **inventory-conservation identity**: `on_hand_units`
    plus `reserved_units` plus `dispatched_units` always equals `total_units_received`." (PRD §2.6)

    Design: Difficulty/compensating_invariant/inventory_conservation_restored_by_fit_exchange_cancel
    """
    env = _setup_reserved_fit_exchange()

    exchange = validate_success(api_client.get_fit_exchange(env["exchange"]["id"], CARE_OPS))
    assert exchange["status"] == "RESERVED", (
        f"an accepted exchange reserves immediately, got {exchange['status']!r}"
    )
    assert exchange["exchange_ordinal"] == 1, (
        f"the first exchange on the order is ordinal 1, got {exchange['exchange_ordinal']}"
    )
    assert exchange["exchange_fee_cents"] == 0, (
        f"exchanges inside an ACTIVE trial are free, got {exchange['exchange_fee_cents']}"
    )

    target = get_pool(env["target_pool"]["id"])
    assert target["on_hand_units"] == TARGET_POOL_UNITS - 1, (
        f"the reservation decrements on_hand_units to {TARGET_POOL_UNITS - 1}, got "
        f"{target['on_hand_units']}"
    )
    assert target["reserved_units"] == 1, (
        f"the reservation increments reserved_units to 1, got {target['reserved_units']}"
    )
    assert target["dispatched_units"] == 0, (
        f"nothing has shipped yet, so dispatched_units stays 0, got {target['dispatched_units']}"
    )
    assert target["total_units_received"] == TARGET_POOL_UNITS, (
        f"a reservation never changes total_units_received, got {target['total_units_received']}"
    )
    assert_inventory_conservation(target)

    source = get_pool(env["pool"]["id"])
    assert source["dispatched_units"] == 1, (
        f"the outgoing configuration is still with the patient, got {source['dispatched_units']}"
    )
    assert source["total_units_received"] == SOURCE_POOL_UNITS, (
        f"the source pool's received total is {SOURCE_POOL_UNITS}, got {source['total_units_received']}"
    )
    assert_inventory_conservation(source)


def test_cancelling_a_reserved_exchange_restores_the_pool_counters_exactly():
    """"Cancellation, optionally with a `reason_note`, is a compensating action available to the
    patient from `RESERVED` and to a care operator from `SHIPPED` (the latter requiring the order's
    trial not to be `RETURN_SETTLED`): the target pool's `reserved_units` decrements and its
    `on_hand_units` increments, restoring the pre-request counters exactly, and any
    `exchange_fee_cents` that was charged is credited back to the plan's `credit_balance_cents`."
    (PRD §3.6)

    Design: Difficulty/compensating_invariant/inventory_conservation_restored_by_fit_exchange_cancel
    """
    env = _setup_reserved_fit_exchange()
    reserved = get_pool(env["target_pool"]["id"])
    assert_inventory_conservation(reserved)

    exchange = validate_success(
        api_client.cancel_fit_exchange(
            env["exchange"]["id"], {"reason_note": "patient changed their mind"},
            env["patient_headers"],
        )
    )
    assert exchange["status"] == "CANCELLED", (
        f"cancelling from RESERVED terminates the exchange as CANCELLED, got {exchange['status']!r}"
    )

    target = get_pool(env["target_pool"]["id"])
    assert target["on_hand_units"] == TARGET_POOL_UNITS, (
        f"on_hand_units must be restored to the pre-request {TARGET_POOL_UNITS}, got "
        f"{target['on_hand_units']}"
    )
    assert target["reserved_units"] == 0, (
        f"reserved_units must return to 0, got {target['reserved_units']}"
    )
    assert target["dispatched_units"] == 0, (
        f"a cancelled exchange never dispatches, got {target['dispatched_units']}"
    )
    assert target["total_units_received"] == TARGET_POOL_UNITS, (
        f"total_units_received is unchanged at {TARGET_POOL_UNITS}, got {target['total_units_received']}"
    )
    assert_inventory_conservation(target)

    source = get_pool(env["pool"]["id"])
    assert source["dispatched_units"] == 1, (
        f"the cancellation leaves the source pool alone, got {source['dispatched_units']}"
    )
    assert_inventory_conservation(source)


# ---------------------------------------------------------------------------
# Benefit conservation
# ---------------------------------------------------------------------------
def _setup_submitted_reimbursement_claim() -> dict:
    """A fully documented DEVICE_ORDER claim submitted through the benefit waterfall."""
    env = setup_delivered_order()
    claim = get_success_data(
        api_client.create_reimbursement_claim(
            {
                "patient_id": env["patient"]["id"],
                "subject_kind": "DEVICE_ORDER",
                "device_order_id": env["order"]["id"],
                "claimed_amount_cents": CLAIMED_AMOUNT_CENTS,
                "document_codes": DEVICE_ORDER_DOCUMENT_CODES,
                "insurance_benefit_cap_cents": INSURANCE_CAP_CENTS,
                "insurance_benefit_used_cents": INSURANCE_USED_CENTS,
                "fsa_balance_cents": FSA_BALANCE_CENTS,
            },
            REIMBURSEMENT,
        )
    )
    env["claim"] = get_success_data(api_client.submit_reimbursement_claim(claim["id"], REIMBURSEMENT))
    return env


def test_submitted_claim_fills_the_benefit_buckets_in_waterfall_order():
    """"Step one computes `eligible_amount_cents`: ... for a `DEVICE_ORDER` subject it is the lesser
    of `claimed_amount_cents` and the order's `captured_cents` minus `refunded_cents` minus
    `retained_cents` floored at 0 ... `insurance_paid_cents` is the lesser of the eligible amount and
    the declared `insurance_benefit_cap_cents` minus `insurance_benefit_used_cents` floored at 0;
    what remains after insurance is the eligible amount minus `insurance_paid_cents`;
    `fsa_paid_cents` is the lesser of that remainder and `fsa_balance_cents`; and
    `patient_responsibility_cents` is the eligible amount minus `insurance_paid_cents` minus
    `fsa_paid_cents`, absorbing any remainder by construction." (PRD §3.8)

    Design: Difficulty/compensating_invariant/benefit_conservation_preserved_by_reimbursement_void
    """
    env = _setup_submitted_reimbursement_claim()

    claim = validate_success(api_client.get_reimbursement_claim(env["claim"]["id"], REIMBURSEMENT))
    assert claim["status"] == "SUBMITTED", (
        f"submission moves the claim DRAFT to SUBMITTED, got {claim['status']!r}"
    )
    assert claim["documentation_complete"] is True, (
        "all four DEVICE_ORDER document codes were supplied, so documentation_complete must be true"
    )
    assert claim["eligible_amount_cents"] == EXPECTED_ELIGIBLE_CENTS, (
        f"the claimed {CLAIMED_AMOUNT_CENTS} is below the order's net capture, so the eligible "
        f"amount is {EXPECTED_ELIGIBLE_CENTS}, got {claim['eligible_amount_cents']}"
    )
    assert claim["insurance_paid_cents"] == EXPECTED_INSURANCE_PAID_CENTS, (
        f"the remaining insurance benefit is {INSURANCE_CAP_CENTS} minus {INSURANCE_USED_CENTS}, so "
        f"insurance_paid_cents is {EXPECTED_INSURANCE_PAID_CENTS}, got {claim['insurance_paid_cents']}"
    )
    assert claim["fsa_paid_cents"] == EXPECTED_FSA_PAID_CENTS, (
        f"the FSA bucket is capped by the declared balance {FSA_BALANCE_CENTS}, got "
        f"{claim['fsa_paid_cents']}"
    )
    assert claim["patient_responsibility_cents"] == EXPECTED_PATIENT_RESPONSIBILITY_CENTS, (
        f"the patient absorbs the remainder {EXPECTED_PATIENT_RESPONSIBILITY_CENTS}, got "
        f"{claim['patient_responsibility_cents']}"
    )
    assert_benefit_conservation(claim)


def test_voiding_an_approved_claim_zeroes_the_benefits_and_conserves_the_total():
    """"A compliance officer may void a claim from `SUBMITTED` or from `APPROVED`, optionally with a
    `reason_note`; either void zeroes `insurance_paid_cents` and `fsa_paid_cents` and sets
    `patient_responsibility_cents` to `eligible_amount_cents`, leaving benefit conservation
    unchanged." (PRD §3.8)

    "every `ReimbursementClaim` satisfies a **benefit-conservation identity**:
    `insurance_paid_cents` plus `fsa_paid_cents` plus `patient_responsibility_cents` always equals
    `eligible_amount_cents`, in every state including denial and void." (PRD §2.6)

    Design: Difficulty/compensating_invariant/benefit_conservation_preserved_by_reimbursement_void
    """
    env = _setup_submitted_reimbursement_claim()
    validate_success(api_client.start_reimbursement_review(env["claim"]["id"], REIMBURSEMENT))
    approved = validate_success(
        api_client.decide_reimbursement_claim(
            env["claim"]["id"], {"decision": "APPROVE"}, REIMBURSEMENT_2
        )
    )
    assert approved["status"] == "APPROVED", (
        f"a second specialist may approve the claim, got {approved['status']!r}"
    )
    assert_benefit_conservation(approved)

    voided = validate_success(
        api_client.void_reimbursement_claim(
            env["claim"]["id"], {"reason_note": "duplicate paperwork withdrawn"}, COMPLIANCE
        )
    )
    assert voided["status"] == "VOIDED", (
        f"the compliance void terminates the claim as VOIDED, got {voided['status']!r}"
    )
    assert voided["insurance_paid_cents"] == 0, (
        f"the void zeroes insurance_paid_cents, got {voided['insurance_paid_cents']}"
    )
    assert voided["fsa_paid_cents"] == 0, (
        f"the void zeroes fsa_paid_cents, got {voided['fsa_paid_cents']}"
    )
    assert voided["patient_responsibility_cents"] == EXPECTED_ELIGIBLE_CENTS, (
        "patient_responsibility_cents absorbs the whole eligible amount "
        f"{EXPECTED_ELIGIBLE_CENTS}, got {voided['patient_responsibility_cents']}"
    )
    assert voided["eligible_amount_cents"] == EXPECTED_ELIGIBLE_CENTS, (
        f"the void does not restate the eligible amount, got {voided['eligible_amount_cents']}"
    )
    assert_benefit_conservation(voided)
