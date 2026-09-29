"""Multi-factor money arithmetic: per-line invoice rounding and credit brackets."""

from prd_bench_local_runner.testing import validate_success

from test_helpers.assertions import (
    assert_cents,
    assert_decimal2,
    assert_line_type_order,
    assert_subtotal_is_sum_of_lines,
    line_amounts_by_type,
)
from test_helpers.test_users import ADMIN_CONTROLLER_USER_ID, ADMIN_HQ_HEADERS


# ---------------------------------------------------------------------------
# Seven fractional-cent lines on one invoice
# ---------------------------------------------------------------------------
def test_invoice_subtotal_rounds_each_line_before_summing(api, rounding_invoice):
    """PRD §2.6: "One ordering rule governs the invoice and is normative rather
    than advisory: **each line is rounded to whole cents before it enters any
    sum, and the sums themselves are never rounded again**. Round per line, then
    add — not add, then round." `subtotal_cents` is the sum of every line's
    `amount_cents`, and it is pure integer arithmetic over values that were each
    already rounded.

    Design: Difficulty/combinatorial_formula/invoice_rounds_each_line_before_summing_not_after
    """
    invoice = rounding_invoice["invoice"]

    assert len(invoice["line_items"]) == 7
    assert_line_type_order(invoice)
    assert_subtotal_is_sum_of_lines(invoice)
    assert_cents(invoice["subtotal_cents"], 82036, "subtotal_cents")
    assert invoice["subtotal_cents"] != 82037


def test_invoice_line_groups_carry_their_own_rounded_totals(api, rounding_invoice):
    """PRD §3.9: "There is exactly one `BASE` line. Its raw value is a base fee
    selected by `event_type` — 42,000 cents for a `FOOD_SAMPLING` event and
    28,000 cents for a `NON_FOOD_DEMO` event — multiplied by a club-tier
    multiplier of 1.25 for a `FLAGSHIP` club, 1.00 for a `STANDARD` club or 0.85
    for a `SATELLITE` club, and multiplied again by a day-part multiplier of 1.00
    for `MORNING`, 1.15 for `MIDDAY` or 1.05 for `AFTERNOON`." The other two are
    proportions of the already-rounded `BASE` line: `PREMIUM_PLACEMENT` bills 18
    percent of it and `BILINGUAL_DEMONSTRATOR` bills 12 percent of it, each
    rounded half-up to whole cents on its own.

    Design: Difficulty/combinatorial_formula/invoice_rounds_each_line_before_summing_not_after
    """
    invoice = rounding_invoice["invoice"]

    assert line_amounts_by_type(invoice, "BASE") == [41055]
    assert line_amounts_by_type(invoice, "ADDON") == [7390, 5000]
    assert line_amounts_by_type(invoice, "STAFFING") == [12587, 8504]
    assert line_amounts_by_type(invoice, "HANDLING") == [5400, 2100]
    assert_cents(invoice["base_fee_cents"], 41055, "base_fee_cents")
    assert_cents(invoice["addon_fee_cents"], 12390, "addon_fee_cents")
    assert_cents(invoice["staffing_fee_cents"], 21091, "staffing_fee_cents")
    assert_cents(
        invoice["sample_handling_fee_cents"], 7500, "sample_handling_fee_cents"
    )


def test_staffing_lines_price_the_recorded_billable_hours(api, rounding_invoice):
    """PRD §3.9: "Each line is the assignment's `billable_hours` multiplied by
    that demonstrator's `hourly_rate_cents` and multiplied again by a role
    multiplier of 1.20 for a `LEAD` or 1.00 for a `SUPPORT`, rounded half-up to
    whole cents." `billable_hours` is the greater of `hours_worked` and a
    four-hour minimum, so a worker who is on site for two and a quarter hours
    still bills 4.00 hours; `billable_hours` reads 0.00 until the assignment
    actually reaches `COMPLETED`.

    Design: Difficulty/combinatorial_formula/invoice_rounds_each_line_before_summing_not_after
    """
    lead = validate_success(
        api.get_assignment(rounding_invoice["lead_assignment_id"], ADMIN_HQ_HEADERS)
    )
    support = validate_success(
        api.get_assignment(rounding_invoice["support_assignment_id"], ADMIN_HQ_HEADERS)
    )

    assert_decimal2(lead["hours_worked"], 4.50, "lead hours_worked")
    assert_decimal2(lead["billable_hours"], 4.50, "lead billable_hours")
    assert_decimal2(support["hours_worked"], 4.25, "support hours_worked")
    assert_decimal2(support["billable_hours"], 4.25, "support billable_hours")

    recon = rounding_invoice["reconciliation"]
    assert recon["cases_delivered"] == 6
    assert recon["recon_status"] == "BALANCED"


def test_standard_tier_single_month_event_earns_no_volume_discount(
    api, rounding_invoice
):
    """PRD §3.9: "`volume_discount_pct` is the vendor's tier base discount —
    0.06 for `PLATINUM`, 0.03 for `GOLD`, 0.00 for `STANDARD` — plus that volume
    step, capped so it can never exceed 0.10 however generous the tier and the
    month." On creation the invoice copies the event's `manufacturer_id` into its
    own `manufacturer_id` and snapshots the vendor's `credit_terms_days` into its
    own `credit_terms_days`, so a later change to the vendor's payment terms
    never rewrites an existing invoice.

    Design: Difficulty/combinatorial_formula/invoice_rounds_each_line_before_summing_not_after
    """
    invoice = rounding_invoice["invoice"]

    assert invoice["monthly_completed_event_count"] == 1
    assert_decimal2(invoice["volume_discount_pct"], 0.00, "volume_discount_pct")
    assert_cents(invoice["discount_cents"], 0, "discount_cents")
    assert_cents(invoice["credit_applied_cents"], 0, "credit_applied_cents")
    assert_cents(invoice["total_due_cents"], 82036, "total_due_cents")
    assert invoice["invoice_status"] == "DRAFT"
    assert invoice["credit_terms_days"] == 45


# ---------------------------------------------------------------------------
# Two credits on one event straddling the 50,000-cent base bracket
# ---------------------------------------------------------------------------
def test_first_credit_brackets_high_on_the_full_projected_base(
    api, credit_bracket_state
):
    """PRD §3.9: "When no such invoice exists, `gross_base_cents` is instead the
    projected base fee: the base fee for the event's `event_type` multiplied by
    the club-tier multiplier for the club's `club_tier` and by the day-part
    multiplier for the event's `day_part`, rounded half-up to whole cents, using
    the same three constant tables as the `BASE` invoice line." The base bracket
    is `HIGH` when `billable_base_cents` has reached at least 50,000 cents and
    `LOW` below that — so this step depends on step 3.

    Design: Difficulty/combinatorial_formula/credit_bracket_keyed_on_base_net_of_prior_applied_credits
    """
    credit = validate_success(
        api.get_credit(credit_bracket_state["credit_one_id"], ADMIN_HQ_HEADERS)
    )

    assert credit["credit_reason"] == "PRODUCT_SHORT"
    assert_cents(credit["gross_base_cents"], 52500, "gross_base_cents")
    assert_cents(credit["prior_applied_cents"], 0, "prior_applied_cents")
    assert_cents(credit["billable_base_cents"], 52500, "billable_base_cents")
    assert credit["notice_hours"] == 96
    assert_decimal2(credit["notice_tier_pct"], 0.25, "notice_tier_pct")
    assert_decimal2(credit["reason_multiplier"], 0.60, "reason_multiplier")
    assert_cents(credit["credit_amount_cents"], 7875, "credit_amount_cents")


def test_applied_credit_with_no_invoice_lands_on_the_vendor_credit_note_balance(
    api, credit_bracket_state
):
    """PRD §3.9: "The first hop places the money: when an invoice for the event
    has `invoice_status` `DRAFT` or `ISSUED`, `applied_to_invoice_id` is set to
    that invoice and that invoice's `credit_applied_cents` increases by this
    credit's `credit_amount_cents`; when no such invoice exists,
    `applied_to_invoice_id` stays unset and the vendor's
    `credit_note_balance_cents` increases by `credit_amount_cents` instead."
    Approval stamps `approved_by_user_id` with the acting `X-User-ID` and moves
    `credit_status` to `APPROVED` — a state that exists only transiently inside
    the request, because the credit immediately auto-advances to `APPLIED` in the
    same request, incrementing its `version`.

    Design: Difficulty/combinatorial_formula/credit_bracket_keyed_on_base_net_of_prior_applied_credits
    """
    credit = validate_success(
        api.get_credit(credit_bracket_state["credit_one_id"], ADMIN_HQ_HEADERS)
    )
    vendor = validate_success(
        api.get_manufacturer(
            credit_bracket_state["manufacturer"]["id"], ADMIN_HQ_HEADERS
        )
    )

    assert credit["credit_status"] == "APPLIED"
    assert credit["applied_to_invoice_id"] is None
    assert credit["approved_by_user_id"] == ADMIN_CONTROLLER_USER_ID
    assert_cents(
        vendor["credit_note_balance_cents"], 7875, "credit_note_balance_cents"
    )


def test_short_receipt_restates_the_event_allocation_downward(
    api, credit_bracket_state
):
    """PRD §3.7: "The first hop overwrites the event's `allocated_sample_cases`
    with the total `cases_received` across that event's shipments whose
    `shipment_status` is `DELIVERED` or `SHORT` — the allocation is restated
    downward to what physically arrived." The second hop, caused by the first,
    recomputes the event's `required_support_count` from the new
    `allocated_sample_cases`, so a food event that dropped below the six-case
    support threshold no longer demands a support worker.

    Design: Difficulty/combinatorial_formula/credit_bracket_keyed_on_base_net_of_prior_applied_credits
    """
    shipment = credit_bracket_state["shipment"]
    restated = credit_bracket_state["event_after_short_receipt"]
    event = validate_success(
        api.get_demo_event(credit_bracket_state["event_id"], ADMIN_HQ_HEADERS)
    )

    assert shipment["shipment_status"] == "SHORT"
    assert shipment["short_cases"] == 4
    assert restated["allocated_sample_cases"] == 2
    assert restated["required_support_count"] == 0
    assert event["booking_status"] == "CANCELLED"
    assert event["cancellation_reason"] == "CLUB_CANCELLED"


def test_second_credit_brackets_low_because_the_prior_credit_nets_the_base_down(
    api, credit_bracket_state
):
    """PRD §3.9: "Valuing a credit runs in seven ordered steps, and the order is
    normative — computing the notice tier before netting off prior credits
    produces a different answer, which is why the tier lookup deliberately sits
    downstream of the netting." `billable_base_cents` is `gross_base_cents` less
    `prior_applied_cents`, floored at zero. This step depends on both step 1 and
    step 2.

    Design: Difficulty/combinatorial_formula/credit_bracket_keyed_on_base_net_of_prior_applied_credits
    """
    credit = validate_success(
        api.get_credit(credit_bracket_state["credit_two_id"], ADMIN_HQ_HEADERS)
    )

    assert credit["credit_reason"] == "CLUB_CANCELLED"
    assert_cents(credit["gross_base_cents"], 52500, "gross_base_cents")
    assert_cents(credit["prior_applied_cents"], 7875, "prior_applied_cents")
    assert_cents(credit["billable_base_cents"], 44625, "billable_base_cents")
    assert credit["notice_hours"] == 96
    assert_decimal2(credit["notice_tier_pct"], 0.15, "notice_tier_pct")
    assert_decimal2(credit["reason_multiplier"], 1.00, "reason_multiplier")
    assert_cents(credit["credit_amount_cents"], 6694, "credit_amount_cents")
    assert credit["credit_amount_cents"] != 11156
    assert credit["credit_amount_cents"] != 13125
    assert credit["credit_status"] == "PENDING_APPROVAL"
