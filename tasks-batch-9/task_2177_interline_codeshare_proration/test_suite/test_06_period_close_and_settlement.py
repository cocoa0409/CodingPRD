"""Closing a settlement period: the fixed-rate clearance cascade and the mileage true-up."""

from test_helpers import (
    OPERATOR,
    assert_clearinghouse_zero_sum,
    assert_iso_instant_equals,
    close_period,
    draft_invoice,
    fly,
    new_carrier,
    new_exchange_rate,
    new_period,
    read_agreement,
    read_carrier,
    read_coupon,
    read_invoice,
    read_period,
    run_proration,
    set_clock,
    setup_agreement,
    setup_ticket_with_coupons,
    setup_two_carriers,
    submit_invoice,
    validate_success,
)


# --------------------------------------------------------------------------- #
# ESTIMATE at fly time versus PERIOD_TRUE_UP at close
# --------------------------------------------------------------------------- #
def _two_first_class_sectors_flown_in_one_period():
    set_clock("2026-08-02T00:00:00Z")
    aa, bb = setup_two_carriers()
    period = new_period()
    _ticket, coupons = setup_ticket_with_coupons(
        aa["id"],
        [
            {"operating_carrier_id": bb["id"], "origin": "JFK", "destination": "LHR",
             "class_of_service": "FIRST", "tpm_miles": 5000},
            {"operating_carrier_id": bb["id"], "origin": "LHR", "destination": "JFK",
             "class_of_service": "FIRST", "tpm_miles": 5000},
        ],
        ticket_number="0012000000001",
        issue_date="2026-08-02T00:00:00Z",
    )
    fly(coupons[0]["id"], aa["id"])
    fly(coupons[1]["id"], aa["id"])
    return aa, bb, period, coupons


def test_fly_time_estimates_are_costed_tier_by_tier_as_the_miles_accumulate(api):
    """PRD §3.4: "What those miles *cost* depends on how many miles the operating carrier has
    already accrued this settlement period, and the tier is read from the carrier's running
    `period_accrued_miles` **as it stands before this coupon's miles are added**."
    PRD §3.4: "Only then are the coupon's miles added to the operating carrier's
    `period_accrued_miles`, and its `ffp_accrual_cost_minor` added to that carrier's
    `period_ffp_cost_estimate_minor`."

    Design: Difficulty/dual_variant_calc/ffp_estimate_tier_vs_period_true_up_tier
    """
    _aa, bb, _period, coupons = _two_first_class_sectors_flown_in_one_period()

    first = read_coupon(coupons[0]["id"])
    second = read_coupon(coupons[1]["id"])
    assert first["ffp_miles_awarded"] == 10000
    assert first["ffp_tier"] == "TIER_A"
    assert first["ffp_accrual_cost_minor"] == 14000
    assert second["ffp_miles_awarded"] == 10000
    assert second["ffp_tier"] == "TIER_B"
    assert second["ffp_accrual_cost_minor"] == 11500

    carrier = read_carrier(bb["id"])
    assert carrier["period_accrued_miles"] == 20000
    assert carrier["period_ffp_cost_estimate_minor"] == 25500, "14000 + 11500"


def test_period_close_reprices_the_whole_period_at_a_single_tier(api):
    """PRD §3.7: "A **single** tier is then chosen from that period total using the same
    thresholds as fly time — `TIER_A` at 1400 per thousand below 10000 miles, `TIER_B` at 1150
    per thousand from 10000 up to but not including 40000, `TIER_C` at 900 per thousand at
    40000 and above — and applied retroactively to every mile of the period."
    PRD §3.7: "The result, the period total multiplied by the chosen per-thousand rate divided
    by 1000 and rounded half up, is written to that carrier's `period_ffp_cost_trued_up_minor`.
    The difference between it and the sum of those same coupons' `ffp_accrual_cost_minor`
    estimates is written to `ffp_true_up_delta_minor`, and it may be negative."
    PRD §3.7: "For every carrier that operated at least one coupon whose `coupon_status` is
    `FLOWN` or `ADJUSTED` and whose `flown_at` falls in the half-open window from
    `period_start` inclusive to `period_end` exclusive, the period's total miles are summed
    from those coupons' `ffp_miles_awarded`."

    Design: Difficulty/dual_variant_calc/ffp_estimate_tier_vs_period_true_up_tier
    """
    aa, bb, period, _coupons = _two_first_class_sectors_flown_in_one_period()
    assert read_carrier(bb["id"])["period_ffp_cost_estimate_minor"] == 25500

    set_clock("2026-09-06T00:00:00Z")
    closed = validate_success(api.close_period(period["id"], OPERATOR), 200)
    assert closed["status"] == "CLOSED"

    operator_carrier = read_carrier(bb["id"])
    assert operator_carrier["period_ffp_cost_trued_up_minor"] == 23000, (
        "20000 period miles priced entirely at the TIER_B rate of 1150 per thousand"
    )
    assert operator_carrier["ffp_true_up_delta_minor"] == -2500, "23000 - 25500"

    validating_carrier = read_carrier(aa["id"])
    assert validating_carrier["period_ffp_cost_trued_up_minor"] == 0, (
        "the accrual is owed to the operating partner, never to the validating carrier"
    )


# --------------------------------------------------------------------------- #
# The five-hop close cascade driven by the FX variance
# --------------------------------------------------------------------------- #
def _eur_invoice_submitted_under_a_tight_credit_limit():
    set_clock("2026-08-10T00:00:00Z")
    aa = new_carrier("AA", credit_limit_minor=270000)
    cc = new_carrier("CC", base_currency="EUR")
    new_exchange_rate(
        from_currency="EUR", to_currency="USD",
        effective_date="2026-08-05T00:00:00Z", rate_scaled=1085000,
    )
    new_exchange_rate(
        from_currency="EUR", to_currency="USD",
        effective_date="2026-08-20T00:00:00Z", rate_scaled=1120000,
    )
    agreement, _factors = setup_agreement(
        aa["id"], cc["id"], "STRAIGHT_RATE", factors=(), activate=True,
        settlement_currency="EUR",
    )
    period = new_period()
    ticket, coupons = setup_ticket_with_coupons(
        aa["id"],
        [{"operating_carrier_id": cc["id"], "origin": "CDG", "destination": "JFK",
          "class_of_service": "ECONOMY", "tpm_miles": 1000}],
        ticket_number="0019000000001",
        total_fare_minor=250000,
        sale_currency="EUR",
        fly_all=True,
    )
    run_proration(ticket["id"], aa["id"], "FINAL")
    invoice = draft_invoice(
        period["id"], cc["id"], aa["id"], [coupons[0]["id"]], billing_currency="EUR"
    )
    invoice = submit_invoice(invoice["id"], cc["id"])
    return {"aa": aa, "cc": cc, "agreement": agreement, "period": period,
            "ticket": ticket, "coupon": coupons[0], "invoice": invoice}


def test_period_close_fixes_the_rate_and_books_the_fx_variance(api):
    """PRD §3.3: "Otherwise the eligible quotes are those whose `from_currency` and
    `to_currency` match the requested ordered pair and whose `effective_date` is at or before
    the anchor instant; among them the one with the latest `effective_date` wins, with the
    earlier `created_at` breaking a tie that the uniqueness rule above makes unreachable in
    practice."
    PRD §3.7: "For each, the fixed FX quote is selected at the anchor of the period's
    `rate_fixing_date` and stamped as `fixed_rate_scaled`; `final_settlement_minor` becomes
    `total_claim_minor` multiplied by `fixed_rate_scaled`, divided by 1000000, rounded half
    up; and `fx_variance_minor` becomes `final_settlement_minor` less
    `provisional_settlement_minor`, which may be negative."
    PRD §3.7: "Because each of those invoices became `CLEARED`, its billing carrier's
    `pending_receivable_minor` is reduced by `provisional_settlement_minor` and its
    `settled_receivable_minor` increased by `final_settlement_minor`, while its billed
    carrier's `pending_payable_minor` is reduced by `provisional_settlement_minor` and its
    `settled_payable_minor` increased by `final_settlement_minor`."

    Design: Difficulty/transitive_cascade/period_close_fx_variance_suspends_carrier_and_its_agreement
    """
    ctx = _eur_invoice_submitted_under_a_tight_credit_limit()
    submitted = read_invoice(ctx["invoice"]["id"])
    assert submitted["total_claim_minor"] == 248125
    assert submitted["provisional_rate_scaled"] == 1085000
    assert submitted["provisional_settlement_minor"] == 269216
    assert read_carrier(ctx["aa"]["id"])["pending_payable_minor"] == 269216

    set_clock("2026-09-06T00:00:00Z")
    closed = close_period(ctx["period"]["id"])

    invoice = read_invoice(ctx["invoice"]["id"])
    assert invoice["status"] == "CLEARED"
    assert invoice["fixed_rate_scaled"] == 1120000
    assert invoice["final_settlement_minor"] == 277900
    assert invoice["fx_variance_minor"] == 8684
    assert_iso_instant_equals(invoice["cleared_at"], "2026-09-06T00:00:00Z")
    assert_iso_instant_equals(invoice["cleared_at"], closed["closed_at"])

    aa = read_carrier(ctx["aa"]["id"])
    cc = read_carrier(ctx["cc"]["id"])
    assert aa["pending_payable_minor"] == 0
    assert aa["settled_payable_minor"] == 277900
    assert cc["pending_receivable_minor"] == 0
    assert cc["settled_receivable_minor"] == 277900


def test_fx_variance_at_close_suspends_the_over_limit_carrier_and_its_agreement(api):
    """PRD §3.7: "Because a carrier's settled balances just moved, every carrier whose
    `settled_payable_minor` less its `settled_receivable_minor` is now strictly greater than
    its `credit_limit_minor`, and whose `status` is still `ACTIVE`, transitions to `SUSPENDED`
    and bumps its `version`."
    PRD §3.7: "Because a carrier became `SUSPENDED` in hop 4, every prorate agreement whose
    `status` is `ACTIVE` and which names that carrier as either `issuing_carrier_id` or
    `partner_carrier_id` transitions to `SUSPENDED` with `suspension_reason` of
    `CARRIER_SUSPENDED`, bumping each agreement's `version`."
    PRD §2.10: "After each of those six, the clearing-house invariant must hold: **summed
    across every carrier row in the system, without any status filter, `net_position_minor` is
    exactly zero.**"

    Design: Difficulty/transitive_cascade/period_close_fx_variance_suspends_carrier_and_its_agreement
    """
    ctx = _eur_invoice_submitted_under_a_tight_credit_limit()

    set_clock("2026-09-06T00:00:00Z")
    close_period(ctx["period"]["id"])

    aa = read_carrier(ctx["aa"]["id"])
    cc = read_carrier(ctx["cc"]["id"])
    assert aa["status"] == "SUSPENDED", (
        "277900 settled payable exceeds AA's 270000 limit once the fixed rate lands"
    )
    assert cc["status"] == "ACTIVE"

    agreement = read_agreement(ctx["agreement"]["id"])
    assert agreement["status"] == "SUSPENDED"
    assert agreement["suspension_reason"] == "CARRIER_SUSPENDED"

    period = read_period(ctx["period"]["id"])
    assert period["status"] == "CLOSED"
    assert period["cleared_invoice_count"] == 1

    assert aa["net_position_minor"] == -277900
    assert cc["net_position_minor"] == 277900
    assert_clearinghouse_zero_sum([aa, cc])
