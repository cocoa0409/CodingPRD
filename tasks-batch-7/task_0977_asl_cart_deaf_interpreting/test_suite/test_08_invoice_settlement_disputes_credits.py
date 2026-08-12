"""Settlement: invoice parallel dimensions, state-error bundle, payments, dispute
resolution, the credit-memo waterfall, and the compensating void actions."""
from test_helpers import (
    api_client,
    validate_error,
    get_success_data,
    ApiErrorId,
    TEST_USERS,
    make_org_requester_headers,
    make_interpreter_headers,
    set_clock,
    create_org,
    create_standard_rate_card,
    create_active_interpreter,
    add_availability,
    create_submitted_request,
    offer_to,
    accept_assignment,
    confirm_assignment,
    get_request,
    get_invoice,
    get_org,
    get_encounter_of,
    setup_generated_invoice,
    setup_issued_invoice,
    assert_invoice_invariants,
    find_line,
    create_credit_memo_payload,
    create_manual_strike,
    create_interpreter_payload,
    file_complaint,
    begin_review,
)

ADMIN = TEST_USERS["platform_admin_headers"]
CLERK = TEST_USERS["billing_clerk_headers"]
REVIEWER = TEST_USERS["quality_reviewer_headers"]


# ─── Difficulty: non_linear_state_machine / invoice parallel dims ────

def _setup_parallel_dimension_invoice():
    """ISSUED invoice 24840 -> payment 10000 -> dispute OPEN -> resolve UPHELD."""
    ctx = setup_issued_invoice()
    get_success_data(api_client.record_payment(
        ctx["invoice"]["id"], {"amount_cents": 10000}, CLERK))
    get_success_data(api_client.dispute_invoice(
        ctx["invoice"]["id"], {"reason": "Travel time looks inflated"},
        make_org_requester_headers(ctx["org"]["id"])))
    return ctx


def test_invoice_payment_and_dispute_dimensions_advance_independently():
    """PRD §3.8: "The payment accrues into `payments_applied_cents` and the due is
    recomputed: a payment short of the due moves `payment_status` from `UNPAID` to
    `PARTIALLY_PAID`" and "The owning `OrgRequester` disputes an `ISSUED` invoice,
    moving `dispute_status` from `NONE` to `OPEN`".
    (24840 due -> 10000 paid -> PARTIALLY_PAID with 14840 due, while the dispute
    dimension independently sits at OPEN.)

    Design: Difficulty/non_linear_state_machine/invoice_parallel_dimensions_independent
    """
    ctx = _setup_parallel_dimension_invoice()
    invoice = get_invoice(ctx["invoice"]["id"])
    assert invoice["payment_status"] == "PARTIALLY_PAID"
    assert invoice["amount_due_cents"] == 14840
    assert invoice["dispute_status"] == "OPEN", (
        "the PARTIALLY_PAID x OPEN combination is legal: dimensions are independent"
    )
    upheld = get_success_data(api_client.resolve_dispute(
        invoice["id"], {"outcome": "UPHELD"}, CLERK))
    assert upheld["dispute_status"] == "RESOLVED_UPHELD"
    assert upheld["payment_status"] == "PARTIALLY_PAID", (
        "UPHELD leaves the payment dimension untouched"
    )
    assert upheld["amount_due_cents"] == 14840


def test_invoice_final_payment_closes_paid_and_request():
    """PRD §3.8: "one that exactly covers the due — or a credit application that
    does — moves it to `PAID`. When the invoice belongs to a completed assignment,
    reaching `PAID` bubbles the request from `COMPLETED` to `CLOSED` and stamps
    `closed_at`."

    Design: Difficulty/non_linear_state_machine/invoice_parallel_dimensions_independent
    """
    ctx = _setup_parallel_dimension_invoice()
    get_success_data(api_client.resolve_dispute(
        ctx["invoice"]["id"], {"outcome": "UPHELD"}, CLERK))
    paid = get_success_data(api_client.record_payment(
        ctx["invoice"]["id"], {"amount_cents": 14840}, CLERK))
    assert paid["payment_status"] == "PAID"
    assert paid["amount_due_cents"] == 0
    assert_invoice_invariants(paid)
    assert get_request(ctx["request"]["id"])["status"] == "CLOSED"


# ─── Corner: invoice / encounter state error bundle ──────────────────

def test_invoice_state_errors_bundle():
    """PRD §3.8: "the invoice must be `ISSUED` (else `ERR_INVOICE_NOT_ISSUED`)".
    PRD §3.8: "issuing requires `issue_status` `DRAFT` (else `ERR_INVOICE_NOT_DRAFT`)".
    PRD §3.7: "each assignment yields exactly one invoice — a second generation is
    rejected with `ERR_INVOICE_ALREADY_EXISTS`".
    PRD §3.8: "Resolution belongs to the `BillingClerk` and requires an `OPEN`
    dispute (else `ERR_INVOICE_NOT_DISPUTED`)".
    PRD §3.7: "verifying an already-verified encounter is rejected with
    `ERR_ENCOUNTER_ALREADY_VERIFIED`".

    Design: Corner/errors/invoice_state_errors_bundle
    """
    ctx = setup_generated_invoice()  # DRAFT invoice on a verified encounter
    inv_id = ctx["invoice"]["id"]
    enc_id = ctx["encounter"]["id"]
    org_headers = make_org_requester_headers(ctx["org"]["id"])

    e1 = api_client.dispute_invoice(inv_id, {"reason": "too early"}, org_headers)
    validate_error(e1, ApiErrorId.ERR_INVOICE_NOT_ISSUED)

    get_success_data(api_client.issue_invoice(inv_id, CLERK))
    e2 = api_client.issue_invoice(inv_id, CLERK)
    validate_error(e2, ApiErrorId.ERR_INVOICE_NOT_DRAFT)

    e3 = api_client.generate_invoice({"assignment_id": ctx["assignment"]["id"]}, CLERK)
    validate_error(e3, ApiErrorId.ERR_INVOICE_ALREADY_EXISTS)

    e4 = api_client.resolve_dispute(inv_id, {"outcome": "UPHELD"}, CLERK)
    validate_error(e4, ApiErrorId.ERR_INVOICE_NOT_DISPUTED)

    e5 = api_client.verify_encounter(enc_id, {}, org_headers)
    validate_error(e5, ApiErrorId.ERR_ENCOUNTER_ALREADY_VERIFIED)


def test_payment_exceeds_amount_due_rejected():
    """PRD §3.8: "A `BillingClerk` records a payment of `amount_cents` against an
    `ISSUED` invoice; the amount must be positive and no more than the current
    `amount_due_cents`, with overpayment rejected as
    `ERR_PAYMENT_EXCEEDS_AMOUNT_DUE` (HTTP 422)." and "When the invoice belongs to a
    completed assignment, reaching `PAID` bubbles the request from `COMPLETED` to
    `CLOSED` and stamps `closed_at`."

    Design: Corner/validations/payment_exceeds_amount_due_rejected
    """
    ctx = setup_issued_invoice()  # amount due 24840
    inv_id = ctx["invoice"]["id"]
    over = api_client.record_payment(inv_id, {"amount_cents": 24841}, CLERK)
    validate_error(over, ApiErrorId.ERR_PAYMENT_EXCEEDS_AMOUNT_DUE)
    exact = get_success_data(api_client.record_payment(
        inv_id, {"amount_cents": 24840}, CLERK))
    assert exact["payment_status"] == "PAID"
    assert exact["amount_due_cents"] == 0
    assert get_request(ctx["request"]["id"])["status"] == "CLOSED"


def test_resolve_dispute_overturned_adds_adjustment_line():
    """PRD §3.8: "`OVERTURNED` closes it as `RESOLVED_OVERTURNED` and requires a
    positive `adjustment_cents` no greater than the invoice's `amount_due_cents` plus
    its `credits_applied_cents` (else `ERR_INVALID_REQUEST`). An overturn appends an
    `ADJUSTMENT` line whose `amount_cents` is the negative of the adjustment,
    recomputes `subtotal_cents` under the round-per-line rule, and recomputes
    `amount_due_cents`; if the due falls to zero the invoice becomes `PAID`, which
    may bubble its request from `COMPLETED` to `CLOSED`."

    Design: Corner/endpoints/resolve_dispute_overturned_adds_adjustment_line
    """
    ctx = setup_issued_invoice()
    inv_id = ctx["invoice"]["id"]
    get_success_data(api_client.dispute_invoice(
        inv_id, {"reason": "Mileage overstated"},
        make_org_requester_headers(ctx["org"]["id"])))
    resolved = get_success_data(api_client.resolve_dispute(
        inv_id, {"outcome": "OVERTURNED", "adjustment_cents": 4840}, CLERK))
    assert resolved["dispute_status"] == "RESOLVED_OVERTURNED"
    adjustment = find_line(resolved, "ADJUSTMENT")
    assert adjustment["amount_cents"] == -4840
    assert resolved["subtotal_cents"] == 20000, "24840 - 4840"
    assert resolved["amount_due_cents"] == 20000
    assert_invoice_invariants(resolved)
    paid = get_success_data(api_client.record_payment(
        inv_id, {"amount_cents": 20000}, CLERK))
    assert paid["payment_status"] == "PAID"
    assert get_request(ctx["request"]["id"])["status"] == "CLOSED"


def test_void_invoice_reverses_credit_applications():
    """PRD §3.8: "Voiding an issued invoice reverses every credit-memo application
    against it, returning each applied amount to its memo's `remaining_cents` and
    reopening any memo it had exhausted."
    PRD §3.1: "It is recomputed on every read as the sum of `amount_due_cents` over
    that organization's invoices whose `issue_status` is `ISSUED` and whose
    `payment_status` is not `PAID`." (A VOID invoice leaves the aggregation.)

    Design: Corner/endpoints/void_invoice_reverses_credit_applications
    """
    ctx = setup_issued_invoice()
    org_id = ctx["org"]["id"]
    org_now = get_org(org_id)
    memo = get_success_data(api_client.create_credit_memo(
        create_credit_memo_payload(org_id, org_now["version"], amount_cents=5000),
        CLERK))
    assert memo["status"] == "EXHAUSTED" and memo["remaining_cents"] == 0
    voided = get_success_data(api_client.void_invoice(ctx["invoice"]["id"], CLERK))
    assert voided["issue_status"] == "VOID"
    memo_after = get_success_data(api_client.get_credit_memo(memo["id"], ADMIN))
    assert memo_after["remaining_cents"] == 5000, "application reversed to the memo"
    assert memo_after["status"] == "OPEN", "the exhausted memo reopens"
    assert get_org(org_id)["outstanding_balance_cents"] == 0


# ─── Difficulty: compensating_invariant / credit apply then void ─────

def _setup_applied_memo():
    ctx = setup_issued_invoice()  # subtotal/due 24840, org outstanding 24840
    org_now = get_org(ctx["org"]["id"])
    memo = get_success_data(api_client.create_credit_memo(
        create_credit_memo_payload(ctx["org"]["id"], org_now["version"],
                                   amount_cents=5000),
        CLERK))
    return ctx, memo


def test_credit_application_preserves_amount_due_invariant():
    """PRD §3.7: "Finally, `amount_due_cents` is the greater of zero and the
    subtotal minus `credits_applied_cents` minus `payments_applied_cents`; that
    invariant must hold at all times".
    PRD §3.8: "Whatever is left becomes the memo's `remaining_cents`, and a memo
    fully consumed turns `EXHAUSTED`". (24840 - 5000 - 0 = 19840; org outstanding
    drops to 19840.)

    Design: Difficulty/compensating_invariant/credit_apply_then_void_restores_amount_due
    """
    ctx, memo = _setup_applied_memo()
    invoice = get_invoice(ctx["invoice"]["id"])
    assert invoice["credits_applied_cents"] == 5000
    assert invoice["amount_due_cents"] == 19840
    assert_invoice_invariants(invoice)
    assert memo["remaining_cents"] == 0 and memo["status"] == "EXHAUSTED"
    assert get_org(ctx["org"]["id"])["outstanding_balance_cents"] == 19840


def test_credit_memo_void_restores_amount_due_without_drift():
    """PRD §3.8: "a `BillingClerk` voids a memo in `OPEN` or `EXHAUSTED` (anything
    else draws `ERR_CREDIT_MEMO_NOT_OPEN`), flipping it to `VOID` and reversing
    every application on its invoices — each invoice's `credits_applied_cents` is
    reduced, its `amount_due_cents` recomputed". (The conserved money quantity
    returns: due 24840, credits 0, org outstanding 24840 — zero drift.)

    Design: Difficulty/compensating_invariant/credit_apply_then_void_restores_amount_due
    """
    ctx, memo = _setup_applied_memo()
    get_success_data(api_client.void_credit_memo(memo["id"], CLERK))
    invoice = get_invoice(ctx["invoice"]["id"])
    assert invoice["credits_applied_cents"] == 0
    assert invoice["amount_due_cents"] == 24840
    assert_invoice_invariants(invoice)
    memo_after = get_success_data(api_client.get_credit_memo(memo["id"], ADMIN))
    assert memo_after["status"] == "VOID"
    assert get_org(ctx["org"]["id"])["outstanding_balance_cents"] == 24840


# ─── Difficulty: transitive_cascade / complaint -> memo waterfall ────

def _setup_two_issued_invoices_and_complaint():
    """Invoice A (older, issued 2026-06-13): 130-min encounter, zero claims -> 19500.
    Invoice B (newer, issued 2026-06-14): 130 min + 90 travel min + 12 mi -> 24840.
    A CRITICAL complaint against assignment A stands UNDER_REVIEW.

    Both requests are filed, offered, accepted, and confirmed while the logical
    clock is still 2026-05-01, so each submission honors the PRD §3.3 two-hour
    lead rule; the encounters are then served in chronological order.
    """
    set_clock("2026-05-01T00:00:00Z")
    org = create_org()
    create_standard_rate_card()
    interp = create_active_interpreter()
    add_availability(interp["id"], "2026-06-01T00:00:00Z", "2026-07-01T00:00:00Z")
    ih = make_interpreter_headers(interp["id"])

    def _confirm(start_date, mileage_est):
        req = create_submitted_request(
            org["id"], scheduled_start=f"{start_date}T14:00:00Z",
            scheduled_end=f"{start_date}T16:30:00Z", estimated_mileage=mileage_est)
        asg = offer_to(req["id"], interp["id"])
        accept_assignment(asg)
        confirm_assignment(asg)
        return req, asg

    def _serve(asg, start_date, checkout_payload):
        """Drive a confirmed assignment through its encounter -> DRAFT invoice."""
        set_clock(f"{start_date}T14:00:00Z")
        get_success_data(api_client.depart_assignment(asg["id"], ih))
        get_success_data(api_client.check_in_assignment(asg["id"], ih))
        set_clock(f"{start_date}T16:10:00Z")
        get_success_data(api_client.check_out_assignment(asg["id"], checkout_payload, ih))
        enc = get_encounter_of(asg["id"])
        get_success_data(api_client.verify_encounter(
            enc["id"], {}, make_org_requester_headers(org["id"])))
        return get_success_data(api_client.generate_invoice(
            {"assignment_id": asg["id"]}, CLERK))

    req_a, asg_a = _confirm("2026-06-10", 0)
    req_b, asg_b = _confirm("2026-06-11", 12)

    inv_a = _serve(asg_a, "2026-06-10", {})
    inv_b = _serve(asg_b, "2026-06-11",
                   {"travel_minutes_claimed": 90, "mileage_claimed": 12})

    set_clock("2026-06-13T00:00:00Z")
    get_success_data(api_client.issue_invoice(inv_a["id"], CLERK))
    set_clock("2026-06-14T00:00:00Z")
    get_success_data(api_client.issue_invoice(inv_b["id"], CLERK))

    complaint = file_complaint(
        {"org": org, "assignment": asg_a}, category="QUALITY",
        severity="CRITICAL", narrative="Gross misinterpretation")
    begin_review(complaint["id"])
    return {
        "org": org, "interpreter": interp,
        "req_a": req_a, "asg_a": asg_a, "inv_a": inv_a,
        "req_b": req_b, "asg_b": asg_b, "inv_b": inv_b,
        "complaint": complaint,
    }


def test_substantiated_complaint_creates_credit_memo():
    """PRD §3.9: "`credit_pct` takes its severity default (ten percent for `MINOR`,
    a quarter for `MAJOR`, half for `CRITICAL`) unless the payload's
    `credit_pct_override` supplies a different fraction; `credit_amount_cents` is
    that fraction times the base, rounded half-up, where the base is the
    `subtotal_cents` of the assignment's `ISSUED` invoice when one exists and
    otherwise the assignment's `estimated_cost_cents`. Substantiation then
    auto-creates a credit memo on the filing organization for exactly
    `credit_amount_cents` with `complaint_id` pointing at the complaint".
    (Override 1.0 x invoice A's 19500 subtotal = 19500.)

    Design: Difficulty/transitive_cascade/substantiated_complaint_credit_waterfall_pays_oldest_invoice
    """
    ctx = _setup_two_issued_invoices_and_complaint()
    adjudicated = get_success_data(api_client.adjudicate_complaint(
        ctx["complaint"]["id"],
        {"outcome": "SUBSTANTIATED", "credit_pct_override": 1.0}, REVIEWER))
    assert adjudicated["status"] == "SUBSTANTIATED"
    assert adjudicated["credit_amount_cents"] == 19500
    memos = get_success_data(api_client.list_complaint_credit_memos(
        ctx["complaint"]["id"], ADMIN))
    assert len(memos) == 1, "substantiation auto-creates exactly one memo"
    memo = memos[0]
    assert memo["amount_cents"] == 19500
    assert memo["complaint_id"] == ctx["complaint"]["id"]
    assert memo["remaining_cents"] == 0 and memo["status"] == "EXHAUSTED"


def test_credit_waterfall_pays_oldest_invoice_and_closes_request():
    """PRD §3.8: "Creation immediately runs the waterfall: among the org's invoices
    that are `ISSUED` and not yet `PAID`, ordered by `issued_at` ascending with ties
    broken by `created_at` ascending (ids never consulted), the memo applies the
    lesser of its remaining balance and each invoice's `amount_due_cents`, oldest
    first". PRD §3.8: "an invoice whose due reaches zero flips to `PAID` (bubbling
    its request to `CLOSED` as above)".
    (The 19500 memo covers the older 19500 invoice fully; the newer 24840 invoice is
    untouched because the memo is exhausted.)

    Design: Difficulty/transitive_cascade/substantiated_complaint_credit_waterfall_pays_oldest_invoice
    """
    ctx = _setup_two_issued_invoices_and_complaint()
    get_success_data(api_client.adjudicate_complaint(
        ctx["complaint"]["id"],
        {"outcome": "SUBSTANTIATED", "credit_pct_override": 1.0}, REVIEWER))
    inv_a = get_invoice(ctx["inv_a"]["id"])
    assert inv_a["credits_applied_cents"] == 19500
    assert inv_a["amount_due_cents"] == 0
    assert inv_a["payment_status"] == "PAID", "oldest issued_at served first"
    inv_b = get_invoice(ctx["inv_b"]["id"])
    assert inv_b["credits_applied_cents"] == 0
    assert inv_b["amount_due_cents"] == 24840, "memo exhausted before reaching it"
    assert get_request(ctx["req_a"]["id"])["status"] == "CLOSED"


# ─── Corner: partial waterfall, OCC on org, double-void/rescind ──────

def _setup_two_invoices_partial_waterfall():
    """Invoice A 19500 (encounter, zero claims) issued 2026-06-13; invoice B 18000
    (fee-only from a 23.5h-notice cancel) issued 2026-06-14."""
    set_clock("2026-05-01T00:00:00Z")
    org = create_org()
    create_standard_rate_card()
    interp = create_active_interpreter()
    add_availability(interp["id"], "2026-06-01T00:00:00Z", "2026-07-01T00:00:00Z")
    ih = make_interpreter_headers(interp["id"])

    # Invoice A via a 130-minute encounter with zero claims.
    req_a = create_submitted_request(org["id"], estimated_mileage=0)
    asg_a = offer_to(req_a["id"], interp["id"])
    accept_assignment(asg_a)
    confirm_assignment(asg_a)
    set_clock("2026-06-10T14:00:00Z")
    get_success_data(api_client.depart_assignment(asg_a["id"], ih))
    get_success_data(api_client.check_in_assignment(asg_a["id"], ih))
    set_clock("2026-06-10T16:10:00Z")
    get_success_data(api_client.check_out_assignment(asg_a["id"], {}, ih))
    enc_a = get_encounter_of(asg_a["id"])
    get_success_data(api_client.verify_encounter(
        enc_a["id"], {}, make_org_requester_headers(org["id"])))
    inv_a = get_success_data(api_client.generate_invoice(
        {"assignment_id": asg_a["id"]}, CLERK))
    set_clock("2026-06-13T00:00:00Z")
    get_success_data(api_client.issue_invoice(inv_a["id"], CLERK))

    # Invoice B via a late cancellation (23.5h notice -> full minimum charge 18000).
    req_b = create_submitted_request(
        org["id"], scheduled_start="2026-06-15T14:00:00Z",
        scheduled_end="2026-06-15T15:00:00Z", estimated_mileage=5)
    asg_b = offer_to(req_b["id"], interp["id"])
    accept_assignment(asg_b)
    confirm_assignment(asg_b)
    set_clock("2026-06-14T14:30:00Z")
    get_success_data(api_client.cancel_assignment(
        asg_b["id"], make_org_requester_headers(org["id"])))
    inv_b = get_success_data(api_client.list_assignment_invoices(asg_b["id"], ADMIN))[0]
    get_success_data(api_client.issue_invoice(inv_b["id"], CLERK))
    return {"org": org, "inv_a": inv_a, "inv_b": inv_b}


def test_waterfall_partial_application_oldest_first():
    """PRD §3.8: "the memo applies the lesser of its remaining balance and each
    invoice's `amount_due_cents`, oldest first, recording each application as a pair
    of `invoice_id` and `amount_cents` appended to the memo's `applications` array in
    application order" and "one partially covered stands at `PARTIALLY_PAID` when
    some amount has been applied and the due remains below the subtotal. Whatever is
    left becomes the memo's `remaining_cents`, and a memo fully consumed turns
    `EXHAUSTED`".
    (A 10000-cent memo hits only the older invoice: 19500 -> 9500 PARTIALLY_PAID;
    the newer 18000 invoice is untouched.)

    Design: Corner/calculations/waterfall_partial_application_oldest_first
    """
    ctx = _setup_two_invoices_partial_waterfall()
    org_now = get_org(ctx["org"]["id"])
    memo = get_success_data(api_client.create_credit_memo(
        create_credit_memo_payload(ctx["org"]["id"], org_now["version"],
                                   amount_cents=10000),
        CLERK))
    inv_a = get_invoice(ctx["inv_a"]["id"])
    assert inv_a["credits_applied_cents"] == 10000
    assert inv_a["amount_due_cents"] == 9500
    assert inv_a["payment_status"] == "PARTIALLY_PAID"
    inv_b = get_invoice(ctx["inv_b"]["id"])
    assert inv_b["credits_applied_cents"] == 0
    assert inv_b["amount_due_cents"] == 18000
    assert memo["remaining_cents"] == 0 and memo["status"] == "EXHAUSTED"
    assert memo["applications"] == [
        {"invoice_id": ctx["inv_a"]["id"], "amount_cents": 10000}]


def test_occ_stale_org_version_on_credit_memo_rejected():
    """PRD §2.7: "Creating a credit memo requires the non-optional
    `expected_org_version` field carrying the organization `version` the client last
    read; a mismatch with the organization's current `version` is rejected with
    `ERR_STALE_ORG_VERSION` (HTTP 412), because memo creation waterfall-applies
    against the outstanding-balance view the client used and bumps the
    organization's version."

    Design: Corner/cross_cutting_layers/occ_stale_org_version_on_credit_memo_rejected
    """
    set_clock("2026-05-01T00:00:00Z")
    org = create_org()
    memo = get_success_data(api_client.create_credit_memo(
        create_credit_memo_payload(org["id"], org["version"], amount_cents=1000),
        CLERK))
    stale = api_client.create_credit_memo(
        create_credit_memo_payload(org["id"], org["version"], amount_cents=2000),
        REVIEWER)
    validate_error(stale, ApiErrorId.ERR_STALE_ORG_VERSION)
    # The first memo found no ISSUED invoices, so nothing applied.
    assert memo["remaining_cents"] == 1000 and memo["status"] == "OPEN"
    memos = get_success_data(api_client.list_org_credit_memos(org["id"], ADMIN))
    assert len(memos) == 1


def test_memo_void_and_strike_rescind_twice_return_not_open_not_active():
    """PRD §3.8: "a `BillingClerk` voids a memo in `OPEN` or `EXHAUSTED` (anything
    else draws `ERR_CREDIT_MEMO_NOT_OPEN`)".
    PRD §3.6: "attempting to rescind a strike that is not `ACTIVE` is rejected with
    `ERR_STRIKE_NOT_ACTIVE`."

    Design: Corner/errors/memo_void_and_strike_rescind_twice_return_not_open_not_active
    """
    set_clock("2026-05-01T00:00:00Z")
    org = create_org()
    memo = get_success_data(api_client.create_credit_memo(
        create_credit_memo_payload(org["id"], org["version"], amount_cents=1000),
        CLERK))
    get_success_data(api_client.void_credit_memo(memo["id"], CLERK))
    e1 = api_client.void_credit_memo(memo["id"], CLERK)
    validate_error(e1, ApiErrorId.ERR_CREDIT_MEMO_NOT_OPEN)

    interp = get_success_data(api_client.create_interpreter(
        create_interpreter_payload(), ADMIN))
    strike = create_manual_strike(interp["id"], "2026-04-01T09:00:00Z")
    get_success_data(api_client.rescind_strike(strike["id"], ADMIN))
    e2 = api_client.rescind_strike(strike["id"], ADMIN)
    validate_error(e2, ApiErrorId.ERR_STRIKE_NOT_ACTIVE)
