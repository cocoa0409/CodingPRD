"""Confirming an order: the money waterfall, the FSA bucket, the FINAL re-quote, and
the validation precedence §2.9 pins."""

from test_helpers import (
    ApiErrorId,
    assert_order,
    claim_for,
    confirm_order,
    create_order_payload,
    list_lab_orders_for,
    new_customer,
    new_frame,
    new_in_network_policy,
    new_material,
    new_order,
    new_prescription,
    new_verified_prescription,
    read_claim,
    read_customer,
    read_order,
    read_policy,
    setup_in_network_percey_order,
    setup_order_scenario,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.fixtures import (
    BENEFITS,
    LOW_POWER_RX,
    RX_POWER_EXACTLY_SIX,
    STORE,
    make_customer_headers,
)


# ═════════════════════════════════════════════════════════════════════════════
# Dual variant — the ESTIMATED quote at confirm vs the FINAL re-quote
# ═════════════════════════════════════════════════════════════════════════════

def test_confirm_produces_the_estimated_quote_with_the_fsa_bucket_applied(api):
    """PRD §3.6: "`benefit_frame_cents` is the smaller of the policy's
    `frame_allowance_remaining_cents` **at the moment of the call** and the discounted
    frame amount. `benefit_lens_cents` is the discounted lens amount minus the policy's
    `lens_copay_cents`, floored at zero — a copay larger than the lens line does not
    create negative benefit. Under the `ESTIMATED` variant, `benefit_applied_cents` is
    simply `benefit_frame_cents` plus `benefit_lens_cents`."
    PRD §3.6: "**Step six: the FSA bucket.** `fsa_applied_cents` is the smallest of three
    numbers: the `fsa_amount_cents` the customer offered on the confirm request, the
    customer's `fsa_balance_cents`, and the pre-FSA balance."

    Design: Difficulty/dual_variant_calc/order_quote_estimated_vs_final_after_in_network_adjudication
    """
    scenario = setup_in_network_percey_order(fsa_balance_cents=10000)
    order = confirm_order(scenario["order"]["id"], scenario["customer"]["id"], 5000)

    assert_order(order)
    assert order["lens_upcharge_cents"] == 17950
    assert order["subtotal_cents"] == 37450
    assert order["discount_cents"] == 3745
    assert order["benefit_frame_cents"] == 15000, "the whole 15,000c allowance, under the 17,550c discounted frame"
    assert order["benefit_lens_cents"] == 13655, "16,155c discounted lens less the 2,500c copay"
    assert order["benefit_applied_cents"] == 28655
    assert order["fsa_applied_cents"] == 5000
    assert order["customer_due_cents"] == 50, "33,705 net - 28,655 benefit - 5,000 FSA"
    assert order["quote_variant"] == "ESTIMATED"


def test_in_network_approval_re_quotes_the_order_under_the_final_variant(api):
    """PRD §3.8: "The claim's `approved_amount_cents` becomes the smaller of the parent
    order's `benefit_applied_cents` as computed under the `ESTIMATED` variant and the
    insurer's `allowed_amount_cents`."
    PRD §3.8: "Under `FINAL`, `benefit_applied_cents` is replaced by the smaller of the
    `ESTIMATED` `benefit_applied_cents` and the claim's `allowed_amount_cents`;
    `customer_due_cents` becomes the net amount (the subtotal less the discount) minus
    that new `benefit_applied_cents` minus the already-committed `fsa_applied_cents`; and
    the order's `quote_variant` becomes `FINAL`."

    Identical order data, a different answer: the insurer's 20,000c allowed amount caps
    the retailer's 28,655c estimate, so the shortfall lands on the customer and
    `customer_due_cents` moves from 50 to 8,705.

    Design: Difficulty/dual_variant_calc/order_quote_estimated_vs_final_after_in_network_adjudication
    """
    scenario = setup_in_network_percey_order(fsa_balance_cents=10000)
    order = confirm_order(scenario["order"]["id"], scenario["customer"]["id"], 5000)
    assert order["customer_due_cents"] == 50, "the ESTIMATED quote before adjudication"

    claim = claim_for(order["id"])
    resp = api.adjudicate_insurance_claim(
        claim["id"], {"decision": "APPROVED", "allowed_amount_cents": 20000}, BENEFITS
    )
    adjudicated = validate_success(resp, 200)

    assert adjudicated["status"] == "ADJUDICATED_APPROVED"
    assert adjudicated["approved_amount_cents"] == 20000, "min(28,655 estimated, 20,000 allowed)"

    final = read_order(order["id"])
    assert final["quote_variant"] == "FINAL"
    assert final["benefit_applied_cents"] == 20000
    assert final["customer_due_cents"] == 8705, "33,705 net - 20,000 FINAL benefit - 5,000 FSA"
    # Nothing else is recomputed.
    assert final["lens_upcharge_cents"] == 17950
    assert final["subtotal_cents"] == 37450
    assert final["discount_cents"] == 3745
    assert final["fsa_applied_cents"] == 5000


def test_confirm_response_already_carries_every_cascaded_value(api):
    """PRD §3.6: "A successful confirmation runs a four-link cascade. The order is
    re-quoted under the `ESTIMATED` variant against the policy's current remaining
    allowance and the customer's current balance, `fsa_applied_cents` is set, the
    customer's `fsa_balance_cents` is debited by exactly that amount, and the order's
    `version` increments."
    PRD §3.6: "The lab order's arrival in turn produces — but only when the customer has a
    non-null `insurance_policy_id` — an insurance claim in `SUBMITTED`, whose `policy_id`
    is copied from the customer, whose `service_lines` array is empty, and whose
    `reserved_frame_benefit_cents` equals the order's `benefit_frame_cents`; the order's
    `active_claim_id` is pointed at it. And that claim, finally, debits its policy:
    `frame_allowance_remaining_cents` decreases by exactly `reserved_frame_benefit_cents`."

    Design: Corner/consistency_model/confirm_response_already_carries_every_cascaded_value
    """
    scenario = setup_in_network_percey_order(fsa_balance_cents=10000)

    resp = api.confirm_order(
        scenario["order"]["id"], {"fsa_amount_cents": 5000}, scenario["headers"]
    )
    body = validate_success(resp, 200)

    # No follow-up read is needed: the confirm response itself carries the cascade.
    assert body["fulfillment_status"] == "CONFIRMED"
    assert body["payment_status"] == "AUTHORIZED"
    assert body["benefit_frame_cents"] == 15000
    assert body["benefit_lens_cents"] == 13655
    assert body["benefit_applied_cents"] == 28655
    assert body["fsa_applied_cents"] == 5000
    assert body["customer_due_cents"] == 50
    assert body["active_claim_id"] is not None

    claim = read_claim(body["active_claim_id"])
    assert claim["status"] == "SUBMITTED"
    assert claim["service_lines"] == []
    assert claim["reserved_frame_benefit_cents"] == 15000
    assert claim["policy_id"] == scenario["policy"]["id"]

    assert read_policy(scenario["policy"]["id"])["frame_allowance_remaining_cents"] == 0
    assert read_customer(scenario["customer"]["id"])["fsa_balance_cents"] == 5000


def test_offering_more_fsa_than_the_balance_is_refused(api):
    """PRD §3.6: "And the offered `fsa_amount_cents` must not exceed the customer's
    `fsa_balance_cents`, or the confirm is refused with `ERR_INSUFFICIENT_FSA`."

    Design: Corner/validations/confirm_with_more_fsa_than_balance_rejected
    """
    scenario = setup_order_scenario(
        customer={"fsa_balance_cents": 5000},
        frame={"price_cents": 9500, "min_pd_mm": 54.0, "max_pd_mm": 70.0},
        material={"code": "M150", "base_price_cents": 0, "material_index": 1.50},
        prescription=dict(LOW_POWER_RX),
    )
    order = scenario["order"]

    resp = api.confirm_order(order["id"], {"fsa_amount_cents": 6000}, scenario["headers"])
    validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_FSA.value)

    after = read_order(order["id"])
    assert after["fulfillment_status"] == "DRAFT"
    assert after["fsa_applied_cents"] == 0
    assert read_customer(scenario["customer"]["id"])["fsa_balance_cents"] == 5000
    assert list_lab_orders_for(order["id"]) == [], "a refused confirm mints no lab order"


def test_confirming_a_bopis_order_at_a_closed_store_is_refused(api):
    """PRD §3.6: "If the order's `delivery_method` is `BOPIS`, the destination store's
    `status` must be `OPEN`, or the confirm is refused with `ERR_STORE_CLOSED`."
    PRD §2.9: "**Store open** — otherwise `ERR_STORE_CLOSED` (409). This check guards
    exactly two operations: confirming a `BOPIS` order, and shipping a lab order whose
    parent order is `BOPIS`."

    Design: Corner/state_machines/shipping_a_bopis_lab_order_to_a_closed_store_returns_store_closed
    """
    scenario = setup_order_scenario(
        store={"name": "Shuttered", "exam_chairs": 1, "status": "CLOSED"},
        frame={"price_cents": 9500, "min_pd_mm": 54.0, "max_pd_mm": 70.0},
        material={"code": "M150", "base_price_cents": 0, "material_index": 1.50},
        prescription=dict(LOW_POWER_RX),
        delivery_method="BOPIS",
    )
    order = scenario["order"]
    assert order["delivery_method"] == "BOPIS"
    assert order["store_id"] == scenario["store"]["id"]

    resp = api.confirm_order(order["id"], {}, scenario["headers"])
    validate_error(resp, ApiErrorId.ERR_STORE_CLOSED.value)

    assert read_order(order["id"])["fulfillment_status"] == "DRAFT"
    assert list_lab_orders_for(order["id"]) == [], "the ship guard is never reached"


# ═════════════════════════════════════════════════════════════════════════════
# Validation precedence — §2.9 reports the FIRST failure, never the worst one
# ═════════════════════════════════════════════════════════════════════════════

def _shared_allowance_scenario():
    """One 15,000c in-network plan shared by two customers.

    Customer B drafts an order while the allowance is untouched, so B's order freezes
    `benefit_frame_cents` at 15,000. Customer A then confirms and drains the allowance to
    zero. B's prescription was never verified.
    """
    policy = new_in_network_policy(
        frame_allowance_cents=15000, lens_copay_cents=2500, annual_max_cents=30000
    )
    frame = new_frame(price_cents=19500, tryon_stock=2, min_pd_mm=54.0, max_pd_mm=70.0)
    material = new_material(code="M167", base_price_cents=12000, material_index=1.67)

    cust_a = new_customer(
        full_name="Ann Alpha", email="ann@example.com", insurance_policy_id=policy["id"]
    )
    cust_b = new_customer(
        full_name="Bo Beta", email="bo@example.com", insurance_policy_id=policy["id"]
    )

    rx_a = new_verified_prescription(cust_a["id"], **RX_POWER_EXACTLY_SIX)
    rx_b = new_prescription(cust_b["id"], **RX_POWER_EXACTLY_SIX)  # stays SUBMITTED

    order_b = new_order(cust_b["id"], rx_b["id"], frame["id"], material["id"])
    order_a = new_order(cust_a["id"], rx_a["id"], frame["id"], material["id"])
    confirm_order(order_a["id"], cust_a["id"])  # drains the allowance to zero

    return {
        "policy": policy,
        "cust_b": cust_b,
        "order_b": order_b,
        "headers_b": make_customer_headers(cust_b["id"]),
    }


def test_unverified_prescription_beats_insufficient_benefit_at_confirm(api):
    """PRD §2.9: "The system evaluates checks in the following fixed priority order and
    reports the **first** failure it encounters; later checks are never reached."
    PRD §2.9: "10. **Prescription verified at confirmation** — otherwise
    `ERR_PRESCRIPTION_NOT_VERIFIED` (409). Applies only to order confirmation."
    PRD §2.9: "28. **Benefit sufficiency** — otherwise `ERR_INSUFFICIENT_BENEFIT` (422).
    Order confirmation only."

    One confirm violates both: the prescription is still SUBMITTED, AND the order's frozen
    15,000c frame benefit over-draws an allowance another customer already drained. The
    409 state error must win over the 422 fiscal one.

    Design: Difficulty/priority_pair_validation_conflict/confirm_state_rx_not_verified_beats_fiscal_insufficient_benefit
    """
    scenario = _shared_allowance_scenario()

    resp = api.confirm_order(scenario["order_b"]["id"], {}, scenario["headers_b"])
    validate_error(resp, ApiErrorId.ERR_PRESCRIPTION_NOT_VERIFIED.value)
    assert resp.status_code == 409


def test_the_over_drawn_allowance_is_genuinely_in_play_behind_the_state_error(api):
    """PRD §3.6: "The order's `benefit_frame_cents` must not exceed the policy's
    `frame_allowance_remaining_cents` — the reservation may not over-draw the allowance —
    or the confirm is refused with `ERR_INSUFFICIENT_BENEFIT`."
    PRD §3.6: "And that claim, finally, debits its policy: `frame_allowance_remaining_cents`
    decreases by exactly `reserved_frame_benefit_cents`."

    The fiscal violation is real — B's order froze a 15,000c frame benefit and the plan has
    zero left — which is what makes the precedence assertion above meaningful rather than
    vacuous.

    Design: Difficulty/priority_pair_validation_conflict/confirm_state_rx_not_verified_beats_fiscal_insufficient_benefit
    """
    scenario = _shared_allowance_scenario()

    order_b = read_order(scenario["order_b"]["id"])
    assert order_b["fulfillment_status"] == "DRAFT"
    assert order_b["benefit_frame_cents"] == 15000, (
        "B drafted while the allowance was untouched"
    )
    assert read_policy(scenario["policy"]["id"])["frame_allowance_remaining_cents"] == 0, (
        "A's confirmation already reserved the whole allowance"
    )

    resp = api.confirm_order(scenario["order_b"]["id"], {}, scenario["headers_b"])
    validate_error(resp, ApiErrorId.ERR_PRESCRIPTION_NOT_VERIFIED.value)


def _cross_owner_lens_mismatch_scenario():
    """Customer C owns a verified power-6.00 prescription; customer D owns nothing.
    D orders against C's prescription with a 1.60 blank that is too weak for it."""
    frame = new_frame(price_cents=19500, min_pd_mm=54.0, max_pd_mm=70.0)
    weak = new_material(code="M160", base_price_cents=6000, material_index=1.60)
    cust_c = new_customer(full_name="Cy Owner", email="cyo@example.com")
    cust_d = new_customer(full_name="Dee Other", email="dee@example.com")
    rx_c = new_verified_prescription(cust_c["id"], **RX_POWER_EXACTLY_SIX)
    return {
        "frame": frame,
        "material": weak,
        "cust_c": cust_c,
        "cust_d": cust_d,
        "rx_c": rx_c,
        "headers_d": make_customer_headers(cust_d["id"]),
    }


def test_lens_incompatibility_beats_prescription_owner_mismatch_at_order_creation(api):
    """PRD §2.9: "The system evaluates checks in the following fixed priority order and
    reports the **first** failure it encounters; later checks are never reached."
    PRD §2.9: "14. **Lens material strong enough for the correction** — otherwise
    `ERR_LENS_INCOMPATIBLE_WITH_RX` (422). Order creation only."
    PRD §2.9: "17. **Prescription ownership** — the referenced prescription's `customer_id`
    matches the order's or the appointment's `customer_id`; otherwise
    `ERR_PRESCRIPTION_OWNER_MISMATCH` (422). This check guards exactly two operations:
    order creation and exam completion."

    One POST violates both. Optical safety is checked before referential integrity, so the
    lens error is the one reported.

    Design: Difficulty/priority_pair_validation_conflict/order_create_safety_lens_mismatch_beats_referential_owner_mismatch
    """
    scenario = _cross_owner_lens_mismatch_scenario()

    resp = api.create_order(
        create_order_payload(
            scenario["cust_d"]["id"],
            scenario["rx_c"]["id"],  # not D's prescription
            scenario["frame"]["id"],
            scenario["material"]["id"],  # 1.60, below the 1.67 the power demands
        ),
        scenario["headers_d"],
    )
    validate_error(resp, ApiErrorId.ERR_LENS_INCOMPATIBLE_WITH_RX.value)
    assert resp.status_code == 422


def test_the_refused_cross_owner_order_persists_no_draft(api):
    """PRD §3.5: "Separately, the prescription must belong to the ordering customer: a
    `customer_id` mismatch between the order and the prescription is refused with
    `ERR_PRESCRIPTION_OWNER_MISMATCH`."
    PRD §3.5: "If the selected material option's `material_index` is **below** the required
    tier, the order is refused with `ERR_LENS_INCOMPATIBLE_WITH_RX`; an index at or above
    the tier is accepted, and an over-specified blank is always permitted."

    The ownership violation is real — the prescription belongs to C, not D — and neither
    violation leaves a draft behind.

    Design: Difficulty/priority_pair_validation_conflict/order_create_safety_lens_mismatch_beats_referential_owner_mismatch
    """
    scenario = _cross_owner_lens_mismatch_scenario()
    assert scenario["rx_c"]["customer_id"] == scenario["cust_c"]["id"]

    resp = api.create_order(
        create_order_payload(
            scenario["cust_d"]["id"],
            scenario["rx_c"]["id"],
            scenario["frame"]["id"],
            scenario["material"]["id"],
        ),
        scenario["headers_d"],
    )
    validate_error(resp, ApiErrorId.ERR_LENS_INCOMPATIBLE_WITH_RX.value)

    _rows, meta = validate_paginated(
        api.list_orders(STORE, params={"customer_id": scenario["cust_d"]["id"]})
    )
    assert meta["total_count"] == 0
