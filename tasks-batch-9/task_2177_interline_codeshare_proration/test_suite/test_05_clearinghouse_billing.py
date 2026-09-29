"""Drafting, submitting and recalling clearing-house invoices."""

from test_helpers import (
    ApiErrorId,
    OPERATOR,
    assert_clearinghouse_zero_sum,
    assert_invoice,
    create_invoice_payload,
    make_accountant_headers,
    make_billing_agent_headers,
    new_carrier,
    read_carrier,
    read_coupon,
    read_invoice,
    read_ticket,
    run_proration,
    set_clock,
    setup_cleared_invoice,
    setup_draft_invoice,
    setup_flown_final_prorated_ticket,
    setup_submitted_invoice,
    setup_ticket_with_coupons,
    setup_three_carriers,
    setup_two_carriers,
    new_period,
    validate_error,
    validate_paginated,
    validate_success,
    void_allocation,
)


# --------------------------------------------------------------------------- #
# Draft-time referential rules
# --------------------------------------------------------------------------- #
def test_invoice_draft_over_a_provisional_ticket_is_refused(api):
    """PRD §2.7: "**Ticket finally prorated.** For every coupon named in `coupon_ids`, the
    owning ticket's `proration_status` is `FINAL` — otherwise `ERR_TICKET_NOT_FINAL_PRORATED`
    (409). Applies to invoice drafting."
    PRD §3.6: "A successful draft opens in `DRAFT` status, writes the new invoice's identifier
    into each attached coupon's `billing_invoice_id`, sets the invoice's own `coupon_count`,
    and leaves every money field at zero — nothing is computed until submission."

    Design: Corner/validations/invoice_draft_over_a_provisional_ticket_returns_ticket_not_final_prorated
    """
    set_clock("2026-08-10T00:00:00Z")
    aa, bb = setup_two_carriers()
    period = new_period()
    ticket, coupons = setup_ticket_with_coupons(
        aa["id"], [{"operating_carrier_id": bb["id"]}],
        ticket_number="0047000000001", fly_all=True,
    )
    run_proration(ticket["id"], aa["id"], "PROVISIONAL")

    resp = api.create_invoice(
        create_invoice_payload(period["id"], bb["id"], aa["id"], [coupons[0]["id"]]),
        make_accountant_headers(bb["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_TICKET_NOT_FINAL_PRORATED.value)

    assert read_coupon(coupons[0]["id"])["billing_invoice_id"] is None
    _rows, meta = validate_paginated(
        api.list_invoices(OPERATOR, params={"settlement_period_id": period["id"]})
    )
    assert meta["total_count"] == 0


def test_invoice_draft_naming_a_carrier_that_did_not_operate_is_refused(api):
    """PRD §2.7: "**Coupon carrier match.** For every coupon in `coupon_ids`, the coupon's
    `operating_carrier_id` equals the invoice's `billing_carrier_id` and the owning ticket's
    `validating_carrier_id` equals the invoice's `billed_carrier_id` — otherwise
    `ERR_COUPON_CARRIER_MISMATCH` (422). Applies to invoice drafting."

    Design: Corner/validations/invoice_draft_billing_a_carrier_that_did_not_operate_returns_carrier_mismatch
    """
    set_clock("2026-08-10T00:00:00Z")
    aa, bb, cc = setup_three_carriers()
    period = new_period()
    ticket, coupons, _run = setup_flown_final_prorated_ticket(
        aa["id"], bb["id"], ticket_number="0048000000001"
    )

    resp = api.create_invoice(
        create_invoice_payload(period["id"], cc["id"], aa["id"], [coupons[0]["id"]]),
        make_accountant_headers(cc["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_COUPON_CARRIER_MISMATCH.value)

    coupon = read_coupon(coupons[0]["id"])
    assert coupon["billing_invoice_id"] is None
    assert coupon["operating_carrier_id"] == bb["id"]
    assert read_ticket(ticket["id"])["billing_status"] == "UNBILLED"


def test_invoice_draft_in_a_currency_the_ticket_was_not_sold_in_is_refused(api):
    """PRD §2.7: "**Currency agreement.** Every attached coupon's ticket `sale_currency`
    equals the invoice's `billing_currency` on an invoice draft; the selected agreement's
    `settlement_currency` equals the ticket's `sale_currency` during a final proration run;
    every population coupon's ticket `sale_currency` equals the sample's `claim_currency` on an
    audit draw. Otherwise `ERR_CURRENCY_MISMATCH` (422). Applies to invoice drafting,
    proration runs and audit-sample draw."

    Design: Corner/validations/invoice_draft_in_the_wrong_currency_returns_currency_mismatch
    """
    set_clock("2026-08-10T00:00:00Z")
    aa, bb = setup_two_carriers()
    period = new_period()
    _ticket, coupons, _run = setup_flown_final_prorated_ticket(
        aa["id"], bb["id"], ticket_number="0049000000001", sale_currency="USD"
    )

    resp = api.create_invoice(
        create_invoice_payload(
            period["id"], bb["id"], aa["id"], [coupons[0]["id"]], billing_currency="EUR"
        ),
        make_accountant_headers(bb["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_CURRENCY_MISMATCH.value)

    assert read_coupon(coupons[0]["id"])["billing_invoice_id"] is None
    _rows, meta = validate_paginated(
        api.list_invoices(OPERATOR, params={"settlement_period_id": period["id"]})
    )
    assert meta["total_count"] == 0


def test_coupon_already_attached_to_an_invoice_cannot_be_drafted_again(api):
    """PRD §2.7: "**Coupons unbilled.** Every coupon in `coupon_ids` has a null
    `billing_invoice_id` and a `coupon_status` of `FLOWN` or `ADJUSTED` — otherwise
    `ERR_COUPON_ALREADY_INVOICED` (409). Applies to invoice drafting."
    PRD §3.6: "A successful draft opens in `DRAFT` status, writes the new invoice's identifier
    into each attached coupon's `billing_invoice_id`, sets the invoice's own `coupon_count`,
    and leaves every money field at zero — nothing is computed until submission."

    Design: Corner/validations/coupon_already_attached_to_another_invoice_returns_already_invoiced
    """
    ctx = setup_draft_invoice(ticket_number="0050000000001")

    resp = api.create_invoice(
        create_invoice_payload(
            ctx["period"]["id"], ctx["bb"]["id"], ctx["aa"]["id"], [ctx["coupon"]["id"]]
        ),
        make_accountant_headers(ctx["bb"]["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_COUPON_ALREADY_INVOICED.value)

    assert read_coupon(ctx["coupon"]["id"])["billing_invoice_id"] == ctx["invoice"]["id"]
    assert read_invoice(ctx["invoice"]["id"])["coupon_count"] == 1
    _rows, meta = validate_paginated(
        api.list_invoices(OPERATOR, params={"settlement_period_id": ctx["period"]["id"]})
    )
    assert meta["total_count"] == 1


# --------------------------------------------------------------------------- #
# Submit-time money rules
# --------------------------------------------------------------------------- #
def test_submit_above_the_billed_carriers_credit_limit_is_refused(api):
    """PRD §3.6: "Submission is refused with `ERR_CREDIT_LIMIT_EXCEEDED` when it would push
    the billed carrier's net payable position past its limit — specifically when that
    carrier's `pending_payable_minor` plus `settled_payable_minor` plus this invoice's
    `provisional_settlement_minor`, less its `pending_receivable_minor` and
    `settled_receivable_minor`, would exceed `credit_limit_minor`."

    Design: Corner/validations/submit_above_the_billed_carriers_credit_limit_returns_credit_limit_exceeded
    """
    ctx = setup_draft_invoice(billed_credit_limit=50000, ticket_number="0052000000001")

    resp = api.submit_invoice(
        ctx["invoice"]["id"], make_billing_agent_headers(ctx["bb"]["id"])
    )
    validate_error(resp, ApiErrorId.ERR_CREDIT_LIMIT_EXCEEDED.value)

    invoice = read_invoice(ctx["invoice"]["id"])
    assert invoice["status"] == "DRAFT"
    assert invoice["submitted_at"] is None
    assert read_carrier(ctx["aa"]["id"])["pending_payable_minor"] == 0
    assert read_carrier(ctx["bb"]["id"])["pending_receivable_minor"] == 0
    assert read_ticket(ctx["ticket"]["id"])["billing_status"] == "UNBILLED"


def test_submit_without_an_eligible_quote_is_refused(api):
    """PRD §3.6: "The chosen scaled rate is stamped as `provisional_rate_scaled` and the
    converted figure as `provisional_settlement_minor`, being `total_claim_minor` multiplied
    by `provisional_rate_scaled`, divided by 1000000, rounded half up. If the pair has no
    eligible quote and the two currencies differ, submission fails with `ERR_NO_EXCHANGE_RATE`."
    PRD §2.7: "**FX quote available.** A quote exists for the ordered currency pair with an
    `effective_date` at or before the anchor instant, unless the two currencies are equal —
    otherwise `ERR_NO_EXCHANGE_RATE` (422). This necessarily precedes the credit check below,
    which needs the converted figure. Applies to invoice submission, settlement-period close
    and audit-sample close."

    Design: Corner/validations/submit_without_a_published_quote_returns_no_exchange_rate
    """
    ctx = setup_draft_invoice(
        ticket_number="0053000000001",
        total_fare_minor=250000,
        sale_currency="EUR",
        billing_currency="EUR",
    )

    resp = api.submit_invoice(
        ctx["invoice"]["id"], make_billing_agent_headers(ctx["bb"]["id"])
    )
    validate_error(resp, ApiErrorId.ERR_NO_EXCHANGE_RATE.value)

    invoice = read_invoice(ctx["invoice"]["id"])
    assert invoice["status"] == "DRAFT"
    assert invoice["provisional_settlement_minor"] == 0
    assert read_carrier(ctx["bb"]["id"])["pending_receivable_minor"] == 0


def test_late_submission_inside_an_open_period_attracts_the_penalty(api):
    """PRD §3.6: "`ich_handling_fee_minor` is the gross multiplied by `ich_fee_bp`, divided by
    10000, rounded half up. `late_submission_penalty_minor` is the gross multiplied by 200
    basis points, divided by 10000, rounded half up, but only when the current logical clock
    is strictly after the period's `submission_deadline`; otherwise it is zero.
    `total_claim_minor` is the gross less the handling fee and less the late penalty, and
    `net_billed_minor` is `total_claim_minor` less whatever `rejected_amount_minor` already
    stands on the invoice — zero at first submission."
    PRD §3.3: "When the source and target currencies are equal, the scaled rate is taken as
    exactly 1000000 and no lookup happens at all."

    Design: Corner/calculations/late_submission_penalty_applies_after_the_deadline_inside_an_open_period
    """
    ctx = setup_draft_invoice(
        ticket_number="0043000000001",
        period_overrides={"submission_deadline": "2026-08-15T00:00:00Z"},
    )
    set_clock("2026-08-20T00:00:00Z")

    invoice = validate_success(
        api.submit_invoice(ctx["invoice"]["id"], make_billing_agent_headers(ctx["bb"]["id"])),
        200,
    )
    assert_invoice(invoice)
    assert invoice["gross_billed_minor"] == 100000
    assert invoice["ich_fee_bp"] == 75
    assert invoice["ich_handling_fee_minor"] == 750
    assert invoice["late_submission_penalty_minor"] == 2000
    assert invoice["total_claim_minor"] == 97250
    assert invoice["provisional_settlement_minor"] == 97250
    assert invoice["status"] == "SUBMITTED"
    assert read_carrier(ctx["aa"]["id"])["pending_payable_minor"] == 97250


def test_invoice_listing_filters_by_period_and_status(api):
    """PRD §3.6: "Invoices may be listed filtered by `settlement_period_id`, by
    `billing_carrier_id`, by `billed_carrier_id` or by `status`."
    PRD §3.7: "For each, the fixed FX quote is selected at the anchor of the period's
    `rate_fixing_date` and stamped as `fixed_rate_scaled`; `final_settlement_minor` becomes
    `total_claim_minor` multiplied by `fixed_rate_scaled`, divided by 1000000, rounded half
    up; and `fx_variance_minor` becomes `final_settlement_minor` less
    `provisional_settlement_minor`, which may be negative."

    Design: Corner/endpoints/invoice_list_filters_by_period_and_status
    """
    ctx = setup_cleared_invoice(ticket_number="0059000000001")

    rows, meta = validate_paginated(
        api.list_invoices(
            make_billing_agent_headers(ctx["bb"]["id"]),
            params={
                "settlement_period_id": ctx["period"]["id"],
                "status": "CLEARED",
                "limit": 10,
                "offset": 0,
            },
        )
    )
    assert meta["total_count"] == 1
    assert meta["has_more"] is False
    assert rows[0]["id"] == ctx["invoice"]["id"]
    assert rows[0]["status"] == "CLEARED"
    assert rows[0]["total_claim_minor"] == 99250
    assert rows[0]["final_settlement_minor"] == 99250

    _rows, meta = validate_paginated(
        api.list_invoices(
            make_billing_agent_headers(ctx["bb"]["id"]),
            params={"settlement_period_id": ctx["period"]["id"], "status": "SUBMITTED"},
        )
    )
    assert meta["total_count"] == 0


# --------------------------------------------------------------------------- #
# The handling-fee tier is keyed on the pre-fee gross
# --------------------------------------------------------------------------- #
def test_handling_fee_tier_is_selected_on_the_pre_fee_gross(api):
    """PRD §3.6: "The clearing house's handling-fee rate, `ich_fee_bp`, is then selected from
    a three-tier scale keyed on that **pre-fee gross** — 75 basis points when the gross is
    below 500000 minor units, 50 basis points when it is at least 500000 but below 5000000,
    and 25 basis points when it is 5000000 or more."
    PRD §3.6: "This evaluation order is pinned and looks circular if read carelessly: the tier
    is keyed on the gross, never on the claim the carrier ultimately receives, and it is never
    re-selected after the deductions land."

    Design: Difficulty/combinatorial_formula/ich_fee_tier_keyed_on_pre_fee_gross_not_on_claim
    """
    ctx = setup_draft_invoice(total_fare_minor=500000, ticket_number="0014000000001")

    invoice = validate_success(
        api.submit_invoice(ctx["invoice"]["id"], make_billing_agent_headers(ctx["bb"]["id"])),
        200,
    )
    assert invoice["gross_billed_minor"] == 500000
    assert invoice["ich_fee_bp"] == 50, (
        "500000 sits on the second tier; keying the tier on the 497500 claim would give 75"
    )
    assert invoice["ich_handling_fee_minor"] == 2500, "not the 3750 a 75 bp reading would give"


def test_submitted_claim_and_conversion_follow_the_pre_fee_tier(api):
    """PRD §3.6: "`ich_handling_fee_minor` is the gross multiplied by `ich_fee_bp`, divided by
    10000, rounded half up. `late_submission_penalty_minor` is the gross multiplied by 200
    basis points, divided by 10000, rounded half up, but only when the current logical clock
    is strictly after the period's `submission_deadline`; otherwise it is zero.
    `total_claim_minor` is the gross less the handling fee and less the late penalty, and
    `net_billed_minor` is `total_claim_minor` less whatever `rejected_amount_minor` already
    stands on the invoice — zero at first submission."
    PRD §3.3: "When the source and target currencies are equal, the scaled rate is taken as
    exactly 1000000 and no lookup happens at all."

    Design: Difficulty/combinatorial_formula/ich_fee_tier_keyed_on_pre_fee_gross_not_on_claim
    """
    ctx = setup_draft_invoice(total_fare_minor=500000, ticket_number="0014000000001")

    invoice = validate_success(
        api.submit_invoice(ctx["invoice"]["id"], make_billing_agent_headers(ctx["bb"]["id"])),
        200,
    )
    assert_invoice(invoice)
    assert invoice["late_submission_penalty_minor"] == 0, "submitted well inside the deadline"
    assert invoice["total_claim_minor"] == 497500
    assert invoice["net_billed_minor"] == 497500
    assert invoice["provisional_rate_scaled"] == 1000000
    assert invoice["provisional_settlement_minor"] == 497500


# --------------------------------------------------------------------------- #
# Submission is gated on the settlement period
# --------------------------------------------------------------------------- #
def _draft_invoice_into_a_closed_period(api, credit_limit):
    ctx = setup_draft_invoice(
        billed_credit_limit=credit_limit, ticket_number="0026000000001"
    )
    set_clock("2026-09-06T00:00:00Z")
    validate_success(api.close_period(ctx["period"]["id"], OPERATOR), 200)
    return ctx


def test_submit_into_a_closed_period_is_refused(api):
    """PRD §2.7: "**Period open.** The referenced settlement period is `OPEN` — otherwise
    `ERR_PERIOD_NOT_OPEN` (409). Applies to invoice drafting, invoice submission, invoice
    recall and settlement-period close."
    PRD §3.6: "It requires the invoice to be `DRAFT`, the period to be `OPEN`, and the billing
    carrier to be `ACTIVE`."

    Design: Difficulty/cross_entity_state_dependency/invoice_submit_gated_on_settlement_period_status
    """
    ctx = _draft_invoice_into_a_closed_period(api, 100000000)

    resp = api.submit_invoice(
        ctx["invoice"]["id"], make_billing_agent_headers(ctx["bb"]["id"])
    )
    validate_error(resp, ApiErrorId.ERR_PERIOD_NOT_OPEN.value)

    period = validate_success(api.get_period(ctx["period"]["id"], OPERATOR), 200)
    assert period["status"] == "CLOSED"
    assert period["cleared_invoice_count"] == 0, "there was no SUBMITTED invoice to clear"


def test_refused_submit_into_a_closed_period_moves_no_balances(api):
    """PRD §3.6: "A successful submission sets `status` to `SUBMITTED` and `submitted_at` to
    the current logical clock, adds `provisional_settlement_minor` to the billing carrier's
    `pending_receivable_minor` and to the billed carrier's `pending_payable_minor`, recomputes
    `net_position_minor` on both, and moves every ticket owning one of the attached coupons
    from `billing_status` `UNBILLED` to `BILLED`."
    PRD §2.7: "When a request violates more than one rule, the response is decided by the
    **first** rule that fails in the ordering below, and no side effect of the request has
    been applied when it does."

    Design: Difficulty/cross_entity_state_dependency/invoice_submit_gated_on_settlement_period_status
    """
    ctx = _draft_invoice_into_a_closed_period(api, 100000000)

    validate_error(
        api.submit_invoice(ctx["invoice"]["id"], make_billing_agent_headers(ctx["bb"]["id"])),
        ApiErrorId.ERR_PERIOD_NOT_OPEN.value,
    )

    invoice = read_invoice(ctx["invoice"]["id"])
    assert invoice["status"] == "DRAFT"
    assert invoice["submitted_at"] is None
    assert invoice["total_claim_minor"] == 0
    assert read_carrier(ctx["bb"]["id"])["pending_receivable_minor"] == 0
    assert read_carrier(ctx["aa"]["id"])["pending_payable_minor"] == 0


# --------------------------------------------------------------------------- #
# The clearing-house zero sum across submit and recall
# --------------------------------------------------------------------------- #
def test_invoice_submission_posts_equal_and_opposite_pending_balances(api):
    """PRD §2.10: "Alongside them, `net_position_minor` is defined as
    `pending_receivable_minor` plus `settled_receivable_minor`, less `pending_payable_minor`
    and less `settled_payable_minor`; a positive value means the clearing house owes this
    carrier money."
    PRD §2.10: "After each of those six, the clearing-house invariant must hold: **summed
    across every carrier row in the system, without any status filter, `net_position_minor` is
    exactly zero.**"

    Design: Difficulty/compensating_invariant/invoice_recall_conserves_the_clearinghouse_zero_sum
    """
    ctx = setup_submitted_invoice(ticket_number="0029000000001")
    cc = new_carrier("CC")

    aa = read_carrier(ctx["aa"]["id"])
    bb = read_carrier(ctx["bb"]["id"])
    assert bb["pending_receivable_minor"] == 99250
    assert aa["pending_payable_minor"] == 99250
    assert bb["net_position_minor"] == 99250
    assert aa["net_position_minor"] == -99250
    assert_clearinghouse_zero_sum([aa, bb, read_carrier(cc["id"])])


def test_invoice_recall_reverses_the_balances_and_detaches_the_coupons(api):
    """PRD §3.6: "It reverses the submission exactly: it subtracts
    `provisional_settlement_minor` from the billing carrier's `pending_receivable_minor` and
    from the billed carrier's `pending_payable_minor` and recomputes `net_position_minor` on
    both; resets `gross_billed_minor`, `ich_fee_bp`, `ich_handling_fee_minor`,
    `late_submission_penalty_minor`, `total_claim_minor`, `net_billed_minor`,
    `provisional_rate_scaled`, `provisional_settlement_minor` and `submitted_at` to their
    defaults; detaches every attached coupon by clearing its `billing_invoice_id` back to null
    and setting the invoice's `coupon_count` to zero; returns the invoice to `DRAFT`; and
    bumps its `version`."
    PRD §3.6: "Tickets follow it out of billing: a ticket whose `billing_status` is `BILLED`
    returns to `UNBILLED` precisely when, after this recall's detachment, none of its coupons
    remains attached to any invoice in `SUBMITTED`, `CLEARED`, `PARTIALLY_REJECTED`,
    `FULLY_REJECTED` or `SETTLED` status."

    Design: Difficulty/compensating_invariant/invoice_recall_conserves_the_clearinghouse_zero_sum
    """
    ctx = setup_submitted_invoice(ticket_number="0029000000001")
    cc = new_carrier("CC")

    validate_success(
        api.recall_invoice(ctx["invoice"]["id"], make_billing_agent_headers(ctx["bb"]["id"])),
        200,
    )

    aa = read_carrier(ctx["aa"]["id"])
    bb = read_carrier(ctx["bb"]["id"])
    assert bb["pending_receivable_minor"] == 0
    assert aa["pending_payable_minor"] == 0
    assert aa["net_position_minor"] == 0
    assert bb["net_position_minor"] == 0
    assert_clearinghouse_zero_sum([aa, bb, read_carrier(cc["id"])])

    invoice = read_invoice(ctx["invoice"]["id"])
    assert invoice["status"] == "DRAFT"
    assert invoice["gross_billed_minor"] == 0
    assert invoice["total_claim_minor"] == 0
    assert invoice["provisional_settlement_minor"] == 0
    assert invoice["submitted_at"] is None
    assert invoice["coupon_count"] == 0

    coupon = read_coupon(ctx["coupon"]["id"])
    assert coupon["billing_invoice_id"] is None
    assert coupon["allocated_amount_minor"] == 100000, "a recall touches billing state only"

    ticket = read_ticket(ctx["ticket"]["id"])
    assert ticket["billing_status"] == "UNBILLED"
    assert ticket["proration_status"] == "FINAL"


# --------------------------------------------------------------------------- #
# The two ticket axes never read each other
# --------------------------------------------------------------------------- #
def test_void_proration_leaves_the_billing_axis_where_it_was(api):
    """PRD §3.5: "It leaves `billing_status` completely untouched — the two axes never read
    each other, and an already-billed ticket stays billed even after its allocation is
    discarded."
    PRD §3.5: "It sets `allocated_amount_minor` to 0 and `allocation_basis` to `UNALLOCATED`
    on every coupon of the ticket regardless of status, restores `unallocated_residual_minor`
    to the full `total_fare_minor`, resets `last_run_type` to `NONE`, moves `proration_status`
    back to `UNPRORATED` and bumps the ticket's `version`."

    Design: Difficulty/non_linear_state_machine/ticket_proration_and_billing_axes_move_independently
    """
    ctx = setup_submitted_invoice(ticket_number="0017000000001")
    assert read_ticket(ctx["ticket"]["id"])["billing_status"] == "BILLED"

    void_allocation(ctx["ticket"]["id"], ctx["aa"]["id"])

    ticket = read_ticket(ctx["ticket"]["id"])
    assert ticket["proration_status"] == "UNPRORATED"
    assert ticket["billing_status"] == "BILLED", "the billing axis is untouched by the void"
    assert ticket["unallocated_residual_minor"] == 100000
    assert ticket["last_run_type"] == "NONE"


def test_void_proration_does_not_restate_a_submitted_invoice(api):
    """PRD §3.6: "The `gross_billed_minor` is the sum of `allocated_amount_minor` over the
    coupons whose `billing_invoice_id` is this invoice; the coupon set was frozen at draft
    time and is only ever cleared by a recall."
    PRD §3.5: "It leaves `billing_status` completely untouched — the two axes never read each
    other, and an already-billed ticket stays billed even after its allocation is discarded."

    Design: Difficulty/non_linear_state_machine/ticket_proration_and_billing_axes_move_independently
    """
    ctx = setup_submitted_invoice(ticket_number="0017000000001")

    void_allocation(ctx["ticket"]["id"], ctx["aa"]["id"])

    coupon = read_coupon(ctx["coupon"]["id"])
    assert coupon["allocated_amount_minor"] == 0
    assert coupon["allocation_basis"] == "UNALLOCATED"
    assert coupon["coupon_status"] == "FLOWN"
    assert coupon["billing_invoice_id"] == ctx["invoice"]["id"]

    invoice = read_invoice(ctx["invoice"]["id"])
    assert invoice["status"] == "SUBMITTED"
    assert invoice["gross_billed_minor"] == 100000, (
        "the gross was frozen at submit and is not recomputed from the emptied allocation"
    )
