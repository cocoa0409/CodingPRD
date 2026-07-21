"""Policy issuance, premium billing/invoicing cycle, monthly-fee tiered pricing, and the
lapse/reinstatement billing loop (PRD §3.3, §2.4 OCC)."""
from test_helpers import (
    validate_success, validate_error, validate_paginated, NON_EXISTENT_UUID, ApiErrorId,
    create_renter, setup_active_property,
    setup_manual_review_and_approve,
    setup_auto_approved_policy, pay_first_invoice, setup_active_policy,
    advance_clock, run_billing_cycle, adjust_coverage_limit,
    make_renter_headers, make_underwriting_agent_headers,
)


def test_policy_get_not_found(api, underwriting_agent_headers):
    """PRD §2.5: "an unresolvable ... a policy yields `ERR_POLICY_NOT_FOUND` ... all at
    HTTP 404."

    Design: Corner/entities/policy_get_not_found
    """
    res = api.get_policy(NON_EXISTENT_UUID, underwriting_agent_headers)
    validate_error(res, ApiErrorId.ERR_POLICY_NOT_FOUND, expected_status=404)


def test_invoice_pay_not_found(api):
    """PRD §2.5: "an unresolvable ... an invoice yields `ERR_INVOICE_NOT_FOUND` ... all at
    HTTP 404."

    Design: Corner/entities/invoice_pay_not_found
    """
    renter = create_renter()  # used only to authenticate the call
    res = api.pay_invoice(NON_EXISTENT_UUID, make_renter_headers(renter["id"]))
    validate_error(res, ApiErrorId.ERR_INVOICE_NOT_FOUND, expected_status=404)


def test_policy_cancel_from_awaiting_first_payment_invalid(api):
    """PRD §3.4: "A `Renter` may cancel their own policy at any point while it is `ACTIVE` or
    `LAPSED` — both non-terminal states permit cancellation directly, without first requiring
    reinstatement."

    Design: Corner/state_machines/policy_cancel_from_awaiting_first_payment_invalid
    """
    landlord, prop, rule = setup_active_property()
    renter = create_renter()
    enrollment, policy = setup_auto_approved_policy(prop["id"], renter)
    assert policy["status"] == "AWAITING_FIRST_PAYMENT"
    res = api.cancel_policy(policy["id"], make_renter_headers(renter["id"]))
    validate_error(res, ApiErrorId.ERR_INVALID_STATE, expected_status=409)
    after = validate_success(api.get_policy(policy["id"], make_renter_headers(renter["id"])), 200)
    assert after["status"] == "AWAITING_FIRST_PAYMENT"


def test_monthly_fee_high_tier_risk_multiplier_nonlinear(api):
    """PRD §3.3: "A risk multiplier is selected first — 1.0 for `LOW`, 1.3 for `MEDIUM`, 1.6 for
    `HIGH` — and multiplied against the coverage limit and against a base rate of 0.8% (expressed
    as the constant 0.008); that product is rounded half-up to the nearest cent, and a flat
    administrative fee of 150 cents is added on top to produce a pre-clamp figure."

    Design: Difficulty/combinatorial_formula/monthly_fee_high_tier_risk_multiplier_nonlinear
    """
    landlord, prop, rule = setup_active_property(monthly_rent_cents=200000)
    renter = create_renter()
    enrollment, policy = setup_manual_review_and_approve(
        prop["id"], renter,
        requested_coverage_limit_cents=300000,
        self_reported_annual_income_cents=1200000,
        credit_proxy_score=320,
        prior_eviction_count=2,
    )
    assert enrollment["risk_score_self_reported"] == 88
    assert enrollment["risk_tier"] == "HIGH"
    assert policy["monthly_fee_cents"] == 3990


def test_monthly_fee_low_tier_same_coverage_limit_differs_nonlinearly(api):
    """PRD §3.3: "A risk multiplier is selected first — 1.0 for `LOW`, 1.3 for `MEDIUM`, 1.6 for
    `HIGH` — and multiplied against the coverage limit and against a base rate of 0.8%..."

    Design: Difficulty/combinatorial_formula/monthly_fee_high_tier_risk_multiplier_nonlinear
    """
    landlord, prop, rule = setup_active_property(monthly_rent_cents=200000)
    renter = create_renter()
    enrollment, policy = setup_auto_approved_policy(
        prop["id"], renter, requested_coverage_limit_cents=300000,
    )
    assert enrollment["risk_tier"] == "LOW"
    assert policy["monthly_fee_cents"] == 2550


def test_monthly_fee_min_fee_floor_clamp_for_small_coverage_limit(api):
    """PRD §3.3: "Only when the pre-clamp figure is within the cap does the final
    `monthly_fee_cents` get set, as the greater of the pre-clamp figure and a floor of 1,500
    cents ($15)."

    Design: Corner/calculations/monthly_fee_min_fee_floor_clamp_for_small_coverage_limit
    """
    landlord, prop, rule = setup_active_property(monthly_rent_cents=200000)
    renter = create_renter()
    enrollment, policy = setup_auto_approved_policy(
        prop["id"], renter, requested_coverage_limit_cents=10000,
    )
    assert policy["monthly_fee_cents"] == 1500


def test_premium_installment_allocation_per_component_rounding(api):
    """PRD §3.3: "each component is rounded to the nearest cent independently before the three
    are summed, never the other way around, because rounding the total once versus rounding each
    piece first can differ by a cent or two whenever a component lands exactly on a half-cent
    boundary. The `insurance_premium_cents` portion is 85% of the monthly fee, the
    `platform_fee_cents` portion is 10%, and the `state_tax_cents` portion is 5%, each rounded
    half-up; `amount_cents` is the sum of the three already-rounded components."

    Design: Corner/calculations/premium_installment_allocation_per_component_rounding_diverges_from_naive_total
    """
    landlord, prop, rule = setup_active_property(monthly_rent_cents=200000)
    renter = create_renter()
    enrollment, policy = setup_auto_approved_policy(
        prop["id"], renter, requested_coverage_limit_cents=500000,
    )
    assert policy["monthly_fee_cents"] == 4150
    inv_res = api.list_policy_invoices(policy["id"], make_renter_headers(renter["id"]))
    invoices, _meta = validate_paginated(inv_res)
    invoice1 = invoices[0]
    assert invoice1["insurance_premium_cents"] == 3528
    assert invoice1["platform_fee_cents"] == 415
    assert invoice1["state_tax_cents"] == 208
    assert invoice1["amount_cents"] == 4151


def test_policy_lapsed_reinstatement_loop_returns_to_active(api):
    """PRD §3.3: "for every `ISSUED` invoice whose due date plus a five-day grace period
    (`OVERDUE_GRACE_DAYS`) has passed by the current logical clock time, the sweep marks it
    `OVERDUE` and, because that invoice belongs to an `ACTIVE` policy, cascades the policy to
    `LAPSED` in the same pass. A `LAPSED` policy is reinstated to `ACTIVE` the moment its renter
    pays the outstanding `OVERDUE` invoice — this is a genuine reinstatement cycle, `LAPSED` back
    to `ACTIVE`, not a one-way lapse."

    Design: Difficulty/non_linear_state_machine/policy_lapsed_reinstatement_loop_returns_to_active
    """
    landlord, prop, rule = setup_active_property()
    renter = create_renter()
    enrollment, policy = setup_auto_approved_policy(
        prop["id"], renter, requested_coverage_limit_cents=200000,
        lease_start_date="2026-07-01T00:00:00Z", lease_end_date="2028-07-01T00:00:00Z",
    )
    pay_first_invoice(policy["id"], renter["id"])
    advance_clock("2026-08-01T00:00:00Z")
    run_billing_cycle()
    inv, _ = validate_paginated(api.list_policy_invoices(policy["id"], make_renter_headers(renter["id"])))
    invoice2 = inv[1]
    advance_clock("2026-08-17T00:00:00Z")
    run_billing_cycle()
    lapsed = validate_success(api.get_policy(policy["id"], make_renter_headers(renter["id"])), 200)
    assert lapsed["status"] == "LAPSED"

    paid = validate_success(api.pay_invoice(invoice2["id"], make_renter_headers(renter["id"])), 200)
    assert paid["status"] == "PAID"
    reinstated = validate_success(api.get_policy(policy["id"], make_renter_headers(renter["id"])), 200)
    assert reinstated["status"] == "ACTIVE"


def test_policy_lapse_reinstate_cycle_repeats_a_second_time(api):
    """PRD §3.3: "A `LAPSED` policy is reinstated to `ACTIVE` the moment its renter pays the
    outstanding `OVERDUE` invoice — this is a genuine reinstatement cycle, `LAPSED` back to
    `ACTIVE`, not a one-way lapse."

    Design: Difficulty/non_linear_state_machine/policy_lapsed_reinstatement_loop_returns_to_active
    """
    landlord, prop, rule = setup_active_property()
    renter = create_renter()
    enrollment, policy = setup_auto_approved_policy(
        prop["id"], renter, requested_coverage_limit_cents=200000,
        lease_start_date="2026-07-01T00:00:00Z", lease_end_date="2028-07-01T00:00:00Z",
    )
    pay_first_invoice(policy["id"], renter["id"])
    # First lapse -> reinstate cycle.
    advance_clock("2026-08-01T00:00:00Z")
    run_billing_cycle()
    inv, _ = validate_paginated(api.list_policy_invoices(policy["id"], make_renter_headers(renter["id"])))
    invoice2 = inv[1]
    advance_clock("2026-08-17T00:00:00Z")
    run_billing_cycle()
    validate_success(api.pay_invoice(invoice2["id"], make_renter_headers(renter["id"])), 200)

    # Second lapse -> reinstate cycle.
    advance_clock("2026-09-01T00:00:00Z")
    run_billing_cycle()
    inv, _ = validate_paginated(api.list_policy_invoices(policy["id"], make_renter_headers(renter["id"])))
    invoice3 = inv[2]
    advance_clock("2026-09-17T00:00:00Z")
    run_billing_cycle()
    lapsed_again = validate_success(api.get_policy(policy["id"], make_renter_headers(renter["id"])), 200)
    assert lapsed_again["status"] == "LAPSED"

    paid3 = validate_success(api.pay_invoice(invoice3["id"], make_renter_headers(renter["id"])), 200)
    assert paid3["status"] == "PAID"
    reinstated_again = validate_success(api.get_policy(policy["id"], make_renter_headers(renter["id"])), 200)
    assert reinstated_again["status"] == "ACTIVE"


def test_invoice_payment_while_lapsed_cascades_policy_reinstatement(api):
    """PRD §3.3: "A `LAPSED` policy is reinstated to `ACTIVE` the moment its renter pays the
    outstanding `OVERDUE` invoice..." — paying the invoice (hop 1) itself causes the policy
    reinstatement (hop 2); no separate policy-level call is made.

    Design: Difficulty/transitive_cascade/invoice_payment_while_lapsed_cascades_policy_reinstatement_depth_2
    """
    landlord, prop, rule = setup_active_property()
    renter = create_renter()
    enrollment, policy = setup_auto_approved_policy(
        prop["id"], renter, requested_coverage_limit_cents=200000,
        lease_start_date="2026-07-01T00:00:00Z", lease_end_date="2028-07-01T00:00:00Z",
    )
    pay_first_invoice(policy["id"], renter["id"])
    advance_clock("2026-08-01T00:00:00Z")
    run_billing_cycle()
    inv, _ = validate_paginated(api.list_policy_invoices(policy["id"], make_renter_headers(renter["id"])))
    invoice2 = inv[1]
    advance_clock("2026-08-17T00:00:00Z")
    run_billing_cycle()

    before = validate_success(api.get_policy(policy["id"], make_renter_headers(renter["id"])), 200)
    assert before["status"] == "LAPSED"

    paid = validate_success(api.pay_invoice(invoice2["id"], make_renter_headers(renter["id"])), 200)
    assert paid["status"] == "PAID"
    after = validate_success(api.get_policy(policy["id"], make_renter_headers(renter["id"])), 200)
    assert after["status"] == "ACTIVE"


def test_invoice_payment_cascade_repeats_for_a_second_overdue_invoice(api):
    """PRD §3.3: "for every `ISSUED` invoice whose due date plus a five-day grace period...has
    passed...the sweep marks it `OVERDUE` and...cascades the policy to `LAPSED`...A `LAPSED`
    policy is reinstated to `ACTIVE` the moment its renter pays the outstanding `OVERDUE`
    invoice."

    Design: Difficulty/transitive_cascade/invoice_payment_while_lapsed_cascades_policy_reinstatement_depth_2
    """
    landlord, prop, rule = setup_active_property()
    renter = create_renter()
    enrollment, policy = setup_auto_approved_policy(
        prop["id"], renter, requested_coverage_limit_cents=200000,
        lease_start_date="2026-07-01T00:00:00Z", lease_end_date="2028-07-01T00:00:00Z",
    )
    pay_first_invoice(policy["id"], renter["id"])
    advance_clock("2026-08-01T00:00:00Z")
    run_billing_cycle()
    inv, _ = validate_paginated(api.list_policy_invoices(policy["id"], make_renter_headers(renter["id"])))
    invoice2 = inv[1]
    advance_clock("2026-08-17T00:00:00Z")
    run_billing_cycle()
    validate_success(api.pay_invoice(invoice2["id"], make_renter_headers(renter["id"])), 200)

    advance_clock("2026-09-01T00:00:00Z")
    run_billing_cycle()
    inv, _ = validate_paginated(api.list_policy_invoices(policy["id"], make_renter_headers(renter["id"])))
    invoice3 = inv[2]
    advance_clock("2026-09-17T00:00:00Z")
    run_billing_cycle()
    before = validate_success(api.get_policy(policy["id"], make_renter_headers(renter["id"])), 200)
    assert before["status"] == "LAPSED"

    paid3 = validate_success(api.pay_invoice(invoice3["id"], make_renter_headers(renter["id"])), 200)
    assert paid3["status"] == "PAID"
    after = validate_success(api.get_policy(policy["id"], make_renter_headers(renter["id"])), 200)
    assert after["status"] == "ACTIVE"


def test_coverage_limit_adjustment_stale_version_rejected(api):
    """PRD §2.4: "A request to adjust a policy's coverage limit must carry
    `expected_policy_version`, the client's last-observed value of that policy's `version`. If
    `expected_policy_version` does not match the policy's current `version` at the moment of the
    write — because a coverage-limit adjustment, a payout disbursement or reversal, or an
    invoice-driven status change has advanced it in the meantime — the adjustment is rejected
    with `ERR_STALE_POLICY_VERSION` (HTTP 412)..."

    Design: Corner/cross_cutting_complexity_layers/coverage_limit_adjustment_stale_version_rejected
    """
    ctx = setup_active_policy(coverage_limit_cents=300000)
    policy = ctx["policy"]
    stale_version = policy["version"]
    first = validate_success(
        adjust_coverage_limit(policy["id"], 600000, stale_version), 200
    )
    assert first["coverage_limit_cents"] == 600000

    res = adjust_coverage_limit(policy["id"], 700000, stale_version)
    validate_error(res, ApiErrorId.ERR_STALE_POLICY_VERSION, expected_status=412)
    after = validate_success(api.get_policy(policy["id"], make_underwriting_agent_headers()), 200)
    assert after["coverage_limit_cents"] == 600000


def test_coverage_limit_adjustment_succeeds_with_fresh_version(api):
    """PRD §2.4: "the client must re-read the policy and retry with the fresh version." PRD
    §3.3: "A successful adjustment sets `coverage_limit_cents` to the requested value...and
    increments the policy's `version` by one."

    Design: Corner/cross_cutting_complexity_layers/coverage_limit_adjustment_stale_version_rejected
    """
    ctx = setup_active_policy(coverage_limit_cents=300000)
    policy = ctx["policy"]
    first = validate_success(
        adjust_coverage_limit(policy["id"], 600000, policy["version"]), 200
    )
    assert first["coverage_limit_cents"] == 600000
    assert first["version"] == policy["version"] + 1

    second = validate_success(
        adjust_coverage_limit(policy["id"], 650000, first["version"]), 200
    )
    assert second["coverage_limit_cents"] == 650000
    assert second["version"] == first["version"] + 1
