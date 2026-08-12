"""Closeout: the invoice, its tax fork, late interest and the deposit endgame."""

from test_helpers import (
    CLERK,
    COORD,
    ApiErrorId,
    assert_deposit_conservation,
    assert_invoice,
    assert_money,
    assert_same_instant,
    make_listing_agent_headers,
    set_clock,
    setup_occupied_agent_visit_completed,
    setup_occupied_invoice_issued,
    setup_occupied_pay_at_closing_authorized,
    setup_occupied_pay_at_closing_deferred,
    setup_occupied_split_visit_completed,
    setup_occupied_tax_exempt_brokerage_visit_completed,
    setup_vacant_project_staged,
    start_pickup_in_progress,
    validate_error,
    validate_success,
)


def _vacant_invoice_issued(api, ctx):
    """Take the canonical vacant project through pickup completion and issue its invoice."""
    pickup_id = start_pickup_in_progress(ctx)
    validate_success(api.complete_pickup(pickup_id, COORD))
    invoice = validate_success(api.open_closeout(ctx["proj_id"], CLERK), 201)
    validate_success(api.issue_invoice(invoice["id"], CLERK))
    return invoice["id"]


def test_paying_more_than_the_total_due_is_refused(api):
    """PRD §2.7: "Rung 68: `amount_paid` equals the invoice's `total_due` exactly —
    underpayment and overpayment are both refused; otherwise `ERR_OVERPAYMENT`, HTTP 422."
    PRD §3.9: "Payment is exact or it is nothing: `amount_paid` must equal `total_due` to the
    cent, and both underpayment and overpayment are refused with `ERR_OVERPAYMENT`."

    Design: Corner/errors/paying_more_than_total_due_returns_overpayment
    """
    ctx = setup_occupied_invoice_issued()

    resp = api.pay_invoice(ctx["inv_id"], 4000.00, CLERK)

    validate_error(resp, ApiErrorId.ERR_OVERPAYMENT.value, 422)
    invoice = validate_success(api.get_invoice(ctx["inv_id"], CLERK))
    assert_money(invoice["total_due"], 3058.06, "invoice.total_due")
    assert invoice["state"] == "ISSUED"


def test_paying_an_already_settled_invoice_is_answered_at_the_fiscal_gate(api):
    """PRD §2.7: "Rung 69: the invoice is not already in state `PAID`; otherwise
    `ERR_INVOICE_ALREADY_PAID`, HTTP 409."
    PRD §3.9: "A payment against an invoice already in state `PAID` is refused with
    `ERR_INVOICE_ALREADY_PAID` — reached at the fiscal gate rather than at the state gate, by
    the named exception described in §2.7 — and so are a void and an escalate against a paid
    invoice."
    PRD §3.9: "A successful payment is permitted from `ISSUED` or from `ESCALATED`, moves the
    invoice to `PAID`, stamps `paid_at` from the logical clock, drives the project's
    `payment_state` to `SETTLED`, clears `fiscal_hold`, and refunds the deposit residue per
    the waterfall."

    Design: Corner/errors/paying_a_settled_invoice_returns_already_paid
    """
    ctx = setup_occupied_invoice_issued()
    validate_success(api.pay_invoice(ctx["inv_id"], 3058.06, CLERK))

    resp = api.pay_invoice(ctx["inv_id"], 3058.06, CLERK)

    validate_error(resp, ApiErrorId.ERR_INVOICE_ALREADY_PAID.value, 409)
    invoice = validate_success(api.get_invoice(ctx["inv_id"], CLERK))
    assert invoice["state"] == "PAID"
    assert_same_instant(invoice["paid_at"], "2026-06-02T09:00:00Z", "invoice.paid_at")
    project = validate_success(api.get_project(ctx["proj_id"], COORD))
    assert project["payment_state"] == "SETTLED"


def test_issuing_an_issued_invoice_again_is_an_invalid_invoice_state(api):
    """PRD §2.7: "Rung 31: the invoice's `state` is a legal origin for the requested
    transition; otherwise `ERR_INVOICE_INVALID_STATE`, HTTP 409."
    PRD §3.9: "Issuing it moves `DRAFT → ISSUED`, stamps `issued_at` from the logical clock,
    sets `due_date` to `issued_at` plus 15 days, and drives the project's `payment_state` to
    `INVOICED`; it requires the project to be in `CLOSEOUT` and the `payer_type` to be
    anything other than `PAY_AT_CLOSING`."

    Design: Corner/errors/issuing_an_already_issued_invoice_returns_invoice_invalid_state
    """
    ctx = setup_occupied_invoice_issued()

    resp = api.issue_invoice(ctx["inv_id"], CLERK)

    validate_error(resp, ApiErrorId.ERR_INVOICE_INVALID_STATE.value, 409)
    invoice = validate_success(api.get_invoice(ctx["inv_id"], CLERK))
    assert_invoice(invoice)
    assert invoice["state"] == "ISSUED"
    assert_same_instant(invoice["due_date"], "2026-06-17T09:00:00Z", "invoice.due_date")


def test_a_closed_project_freezes_every_write_beneath_it(api):
    """PRD §2.7: "Rung 14: the ancestor project is not in `workflow_state` `CLOSED`;
    otherwise `ERR_PROJECT_CLOSED`, HTTP 409."
    PRD §3.9: "Closing the project moves it `CLOSEOUT → CLOSED`, and that is the single place
    the two axes meet: it requires the `payment_state` to be `SETTLED` or `WRITTEN_OFF` and
    every invoice on the project to be `PAID` or `VOID`."
    PRD §3.9: "`CLOSED` is the workflow axis's only terminal state, and a closed project
    freezes every mutating operation beneath it with `ERR_PROJECT_CLOSED`."

    Design: Corner/errors/writes_against_a_closed_project_return_project_closed
    """
    ctx = setup_occupied_invoice_issued()
    validate_success(api.pay_invoice(ctx["inv_id"], 3058.06, CLERK))
    validate_success(api.close_project(ctx["proj_id"], COORD))

    resp = api.upgrade_package(ctx["proj_id"], ctx["tier_ess"], COORD)

    validate_error(resp, ApiErrorId.ERR_PROJECT_CLOSED.value, 409)
    project = validate_success(api.get_project(ctx["proj_id"], COORD))
    assert project["workflow_state"] == "CLOSED"
    assert project["payment_state"] == "SETTLED"


def test_refunding_a_deposit_before_the_invoice_is_paid_is_refused(api):
    """PRD §2.7: "Rung 73: a deposit may only be refunded once its project's invoice is in
    state `PAID`; otherwise `ERR_DEPOSIT_INVALID_STATE`, HTTP 409 — the same code rung 32
    uses, reached here for a fiscal rather than a structural reason."
    PRD §3.3: "A **refund** returns the residue: `refunded_amount` takes the value of
    `held_remaining`, which then becomes 0.00, and the deposit reaches `REFUNDED` — but only
    once the project's invoice is in state `PAID`, and a refund attempted earlier is refused
    with `ERR_DEPOSIT_INVALID_STATE`."

    Design: Corner/errors/deposit_refund_before_payment_is_refused
    """
    ctx = setup_occupied_invoice_issued()

    resp = api.refund_deposit(ctx["dep_id"], CLERK)

    validate_error(resp, ApiErrorId.ERR_DEPOSIT_INVALID_STATE.value, 409)
    deposit = validate_success(api.get_deposit(ctx["dep_id"], CLERK))
    assert deposit["state"] == "HELD"
    assert_money(deposit["held_remaining"], 829.00, "deposit.held_remaining")
    assert_money(deposit["refunded_amount"], 0.00, "deposit.refunded_amount")
    assert_deposit_conservation(deposit)


def test_closing_a_sale_past_the_deferral_window_is_refused(api):
    """PRD §2.7: "Rung 70: a `DEFERRED_CLOSING` invoice is converted within 120 days of its
    `issued_at`; otherwise `ERR_CLOSING_DEFERRAL_EXPIRED`, HTTP 409."
    PRD §3.9: "The conversion is refused with `ERR_CLOSING_DEFERRAL_EXPIRED` when the logical
    clock is more than 120 days past the invoice's `issued_at`."

    Design: Corner/errors/closing_after_the_deferral_window_returns_deferral_expired
    """
    ctx = setup_occupied_pay_at_closing_deferred()
    agent = make_listing_agent_headers(ctx["agent_id"])
    set_clock("2026-10-20T09:00:00Z")
    validate_success(api.listing_under_contract(ctx["listing_id"], agent))

    resp = api.listing_close(ctx["listing_id"], agent)

    validate_error(resp, ApiErrorId.ERR_CLOSING_DEFERRAL_EXPIRED.value, 409)
    invoice = validate_success(api.get_invoice(ctx["inv_id"], CLERK))
    assert invoice["state"] == "DEFERRED_CLOSING"
    listing = validate_success(api.get_listing(ctx["listing_id"], COORD))
    assert listing["listing_state"] == "UNDER_CONTRACT"
    assert listing["closed_at"] is None


def test_escalating_a_deferred_invoice_books_the_closing_escalation_fee(api):
    """PRD §3.9: "A deferred invoice becomes `ESCALATED` when the listing terminates or when a
    clerk escalates it directly because the deferral has run out; escalation books the 650.00
    closing escalation fee, recomputes `total_due`, and sets the project's `fiscal_hold`
    true."
    PRD §2.8: "The invoice `line_summary` is an object keyed by component name, and the
    twelve components have a **fixed, pinned order**: `package`, `room_overage`,
    `accessory_overage`, `labour`, `travel`, `lease`, `extension`, `holdover`, `damage`,
    `photo`, `cancellation`, `closing_escalation`."

    Design: Corner/errors/escalating_a_deferred_invoice_books_the_closing_escalation_fee
    """
    ctx = setup_occupied_pay_at_closing_deferred()

    validate_success(api.escalate_invoice(ctx["inv_id"], CLERK))

    invoice = validate_success(api.get_invoice(ctx["inv_id"], CLERK))
    assert invoice["state"] == "ESCALATED"
    assert_money(invoice["line_summary"]["closing_escalation"], 650.00,
                 "line_summary.closing_escalation")
    assert_money(invoice["subtotal"], 3475.00, "invoice.subtotal")
    assert_money(invoice["tax_amount"], 286.69, "invoice.tax_amount")
    assert_money(invoice["total_due"], 3761.69, "invoice.total_due")
    project = validate_success(api.get_project(ctx["proj_id"], COORD))
    assert project["fiscal_hold"] is True


def test_a_split_payer_invoice_is_taxed_at_the_standard_rate(api):
    """PRD §3.3: "Under `SPLIT` the bill is divided and the deposit is 25 percent."
    PRD §3.9: "In every other case — `AGENT`, `SPLIT`, a non-exempt `BROKERAGE`, and
    `PAY_AT_CLOSING` — the whole `subtotal` is multiplied by the standard rate of 8.25
    percent."
    PRD §3.9: "The evaluation order for the whole invoice is **pinned in six steps, and no
    step reads a later step's output**: first the `subtotal`; second the `tax_amount`,
    computed from that subtotal; third the interest base, which is subtotal plus tax; fourth
    the interest, whose rate tier is keyed on that base and therefore excludes interest
    itself, so the value is well defined in a single pass; fifth `deposit_applied`, which is
    the sum of the deposit's `applied_to_balance`, `applied_to_damage` and
    `applied_to_holdover`; and sixth `total_due`, which is the interest base plus the
    interest minus `deposit_applied`, floored at 0.00 and rounded half-up to two decimal
    places."

    Design: Corner/calculations/split_payer_rounding_remainder_lands_on_the_seller_share
    """
    ctx = setup_occupied_split_visit_completed()

    invoice = validate_success(api.open_closeout(ctx["proj_id"], CLERK), 201)

    project = validate_success(api.get_project(ctx["proj_id"], COORD))
    assert_money(project["contract_value"], 4145.00, "project.contract_value")
    deposit = validate_success(api.get_deposit(ctx["dep_id"], CLERK))
    assert_money(deposit["amount"], 1036.25, "deposit.amount")
    assert_money(invoice["subtotal"], 2825.00, "invoice.subtotal")
    assert_money(invoice["tax_amount"], 233.06, "invoice.tax_amount")
    assert_money(invoice["total_due"], 3058.06, "invoice.total_due")


def test_a_project_read_surfaces_every_derived_billing_field(api):
    """PRD §3.2: "The new row starts in `workflow_state` `DRAFT` and `payment_state`
    `UNBILLED`, with `window_extension_count` 0, `restage_count` 0, `photo_sessions_consumed`
    0, `reshoot_credits_remaining` 1, `destage_eligible` false and `fiscal_hold` false."
    PRD §3.3: "Collecting the deposit moves it `REQUIRED → HELD`, sets `held_remaining` to
    the full `amount`, and drives the project's `payment_state` `UNBILLED → DEPOSIT_HELD`."

    Design: Corner/endpoints/project_read_exposes_every_derived_billing_field
    """
    ctx = setup_vacant_project_staged()

    project = validate_success(api.get_project(ctx["proj_id"], CLERK))

    assert_money(project["contract_value"], 7690.00, "project.contract_value")
    assert project["room_count"] == 4
    assert project["accessory_set_count"] == 3
    assert project["reshoot_credits_remaining"] == 1
    assert project["restage_count"] == 0
    assert project["fiscal_hold"] is False
    assert project["payment_state"] == "DEPOSIT_HELD"


def test_a_tax_exempt_brokerage_invoice_carries_no_tax_at_all(api):
    """PRD §3.9: "When the `payer_type` is `BROKERAGE` and the billed brokerage carries
    `tax_exempt` true, `tax_amount` is exactly 0.00 regardless of subtotal."
    PRD §3.3: "Under `BROKERAGE` the firm is billed and the deposit is exactly 0.00 percent —
    which is to say exactly nothing."

    Design: Difficulty/dual_variant_calc/tax_amount_diverges_by_payer_on_billing_domain
    """
    ctx = setup_occupied_tax_exempt_brokerage_visit_completed()

    invoice = validate_success(api.open_closeout(ctx["proj_id"], CLERK), 201)

    project = validate_success(api.get_project(ctx["proj_id"], COORD))
    assert_money(project["contract_value"], 2495.00, "project.contract_value")
    deposit = validate_success(api.get_deposit(ctx["dep_id"], CLERK))
    assert_money(deposit["amount"], 0.00, "deposit.amount")
    assert_money(invoice["subtotal"], 2825.00, "invoice.subtotal")
    assert_money(invoice["tax_amount"], 0.00, "invoice.tax_amount")
    assert invoice["state"] == "DRAFT"


def test_the_same_lines_under_an_agent_payer_do_carry_standard_tax(api):
    """PRD §3.9: "In every other case — `AGENT`, `SPLIT`, a non-exempt `BROKERAGE`, and
    `PAY_AT_CLOSING` — the whole `subtotal` is multiplied by the standard rate of 8.25
    percent."
    PRD §3.9: "A seller-paid and an agent-paid invoice carrying identical lines therefore
    carry different tax."

    Design: Difficulty/dual_variant_calc/tax_amount_diverges_by_payer_on_billing_domain
    """
    ctx = setup_occupied_agent_visit_completed()

    invoice = validate_success(api.open_closeout(ctx["proj_id"], CLERK), 201)

    assert_money(invoice["subtotal"], 2825.00, "invoice.subtotal")
    assert_money(invoice["tax_amount"], 233.06, "invoice.tax_amount")
    assert invoice["state"] == "DRAFT"


def test_a_seller_payer_vacant_invoice_taxes_only_the_rental_components(api):
    """PRD §3.9: "When the `payer_type` is `SELLER`, only the rental components are taxed:
    the `lease`, `extension` and `holdover` components are added together and multiplied by a
    rental-only rate of 6.25 percent."
    PRD §3.5: "The lease component also carries the initial lease charge itself, which is the
    lease's `monthly_rent` at the instant of invoice materialisation multiplied by its
    `initial_cycles`, rounded half-up to two decimal places; extension cycles are billed
    through `extension_charge` instead, so the two never double-count."
    PRD §3.5: "for every rental order on the project in state `DELIVERED` or `RETURNED`, the
    shortfall is that order's `effective_term_cycles` minus the lease's `billed_cycles`,
    floored at 0, and the order contributes its `monthly_rate_total` multiplied by that
    shortfall, rounded half-up to two decimal places before accumulation; the accumulated
    total is rounded again and booked into the invoice's `lease` component."

    Design: Difficulty/combinatorial_formula/interest_rate_tier_keyed_on_pre_interest_base
    """
    ctx = setup_vacant_project_staged()
    invoice_id = _vacant_invoice_issued(api, ctx)

    invoice = validate_success(api.get_invoice(invoice_id, CLERK))

    lease = validate_success(api.get_lease(ctx["lease_id"], COORD))
    assert_money(lease["monthly_rent"], 1867.50, "lease.monthly_rent")
    assert_money(invoice["subtotal"], 14605.00, "invoice.subtotal")
    assert_money(invoice["tax_amount"], 610.31, "invoice.tax_amount")


def test_the_interest_rate_tier_is_keyed_on_the_pre_interest_base(api):
    """PRD §3.9: "**Late-payment interest never compounds on itself.** Its base is the
    invoice's `subtotal` plus its `tax_amount` and nothing else."
    PRD §3.9: "Otherwise the months overdue are the elapsed time from `due_date` to the clock
    divided by 30 days and rounded **up** to a whole number, and the rate is selected from
    the base: a base strictly greater than 5000.00 accrues at 1.5 percent per month, and
    anything at or below that accrues at the reduced rate of 0.75 percent per month."
    PRD §3.9: "The evaluation order for the whole invoice is **pinned in six steps, and no
    step reads a later step's output**: first the `subtotal`; second the `tax_amount`,
    computed from that subtotal; third the interest base, which is subtotal plus tax; fourth
    the interest, whose rate tier is keyed on that base and therefore excludes interest
    itself, so the value is well defined in a single pass; fifth `deposit_applied`, which is
    the sum of the deposit's `applied_to_balance`, `applied_to_damage` and
    `applied_to_holdover`; and sixth `total_due`, which is the interest base plus the
    interest minus `deposit_applied`, floored at 0.00 and rounded half-up to two decimal
    places."

    Design: Difficulty/combinatorial_formula/interest_rate_tier_keyed_on_pre_interest_base
    """
    ctx = setup_vacant_project_staged()
    invoice_id = _vacant_invoice_issued(api, ctx)
    set_clock("2026-11-02T09:00:00Z")

    invoice = validate_success(api.get_invoice(invoice_id, CLERK))

    assert_money(invoice["deposit_applied"], 2307.00, "invoice.deposit_applied")
    assert_money(invoice["interest_accrued"], 228.23, "invoice.interest_accrued")
    assert_money(invoice["total_due"], 13136.54, "invoice.total_due")


def test_applying_then_refunding_a_deposit_conserves_its_amount(api):
    """PRD §2.11: "A deposit's `amount` always equals the sum of `applied_to_damage`,
    `applied_to_holdover`, `applied_to_balance`, `refunded_amount`, `forfeited_amount` and
    `held_remaining`."
    PRD §2.11: "The compensating pair is applying the waterfall against refunding the
    residue."
    PRD §3.3: "A **refund** returns the residue: `refunded_amount` takes the value of
    `held_remaining`, which then becomes 0.00, and the deposit reaches `REFUNDED` — but only
    once the project's invoice is in state `PAID`, and a refund attempted earlier is refused
    with `ERR_DEPOSIT_INVALID_STATE`."

    Design: Difficulty/compensating_invariant/deposit_apply_then_refund_conserves_the_deposit_amount
    """
    ctx = setup_occupied_pay_at_closing_authorized()
    agent = make_listing_agent_headers(ctx["agent_id"])
    validate_success(api.collect_deposit(ctx["dep_id"], CLERK))
    visit = validate_success(api.schedule_visit(
        ctx["proj_id"], "2026-06-02T09:00:00Z", COORD), 201)
    set_clock("2026-06-02T09:00:00Z")
    validate_success(api.complete_visit(visit["id"], 2.0, COORD))
    invoice = validate_success(api.open_closeout(ctx["proj_id"], CLERK), 201)
    validate_success(api.apply_deposit(ctx["dep_id"], invoice["id"], CLERK))
    validate_success(api.defer_invoice_to_closing(invoice["id"], CLERK))
    validate_success(api.listing_under_contract(ctx["listing_id"], agent))
    validate_success(api.listing_close(ctx["listing_id"], agent))
    validate_success(api.pay_invoice(invoice["id"], 0.00, CLERK))

    validate_success(api.refund_deposit(ctx["dep_id"], CLERK))

    deposit = validate_success(api.get_deposit(ctx["dep_id"], CLERK))
    assert_money(deposit["amount"], 6197.50, "deposit.amount")
    assert_money(deposit["applied_to_damage"], 0.00, "deposit.applied_to_damage")
    assert_money(deposit["applied_to_holdover"], 0.00, "deposit.applied_to_holdover")
    assert_money(deposit["applied_to_balance"], 3058.06, "deposit.applied_to_balance")
    assert_money(deposit["refunded_amount"], 3139.44, "deposit.refunded_amount")
    assert_money(deposit["forfeited_amount"], 0.00, "deposit.forfeited_amount")
    assert_money(deposit["held_remaining"], 0.00, "deposit.held_remaining")
    assert deposit["state"] == "REFUNDED"
    stored_invoice = validate_success(api.get_invoice(invoice["id"], CLERK))
    assert_money(stored_invoice["subtotal"], 2825.00, "invoice.subtotal")
    assert_money(stored_invoice["tax_amount"], 233.06, "invoice.tax_amount")
    assert_money(stored_invoice["total_due"], 0.00, "invoice.total_due")
    assert_deposit_conservation(deposit)
