"""Invoicing: kind compatibility, per-line rounding, the empty-lines gate, the
issue/pay/void lifecycle, and the money ledger that issue and void must conserve.
"""
import pytest

from test_helpers import (
    validate_success,
    validate_error,
    ApiErrorId,
    TEST_USERS,
    assert_lines_sum_to_subtotal,
    assert_total_is_subtotal_plus_tax,
    assert_billing_status_matches_ledger,
    fixtures,
    factories as F,
)

DL = TEST_USERS["delivery_lead_headers"]
FIN = TEST_USERS["finance_officer_headers"]
ENG = TEST_USERS["engineer_headers"]

TM_ENGAGEMENT = {
    "billing_model": "TIME_AND_MATERIALS",
    "contract_value": 100000.00,
    "budget_hours_cap": 500,
    "standard_hourly_rate": 200.00,
}


def test_time_and_materials_invoice_excludes_non_billable_and_unapproved_time(api):
    """PRD 3.8: "For a `TIME_AND_MATERIALS` invoice, the eligible time entries are those that are `APPROVED`, are billable, whose `work_date` falls inside the **inclusive** window running from `period_start` through `period_end`, and whose ticket rolls up through its sprint to this engagement. Entries that are `SUBMITTED`, `REJECTED` or `REVERSED`, and non-billable entries of any status, are excluded."
    PRD 3.3: "A ticket's `actual_hours` is at all times the sum of `hours` over its `APPROVED` time entries, and its `variance_ratio` is that `actual_hours` figure divided by its `estimated_hours`, rounded half up to 4 decimal places."

    Design: Corner/calculations/tm_invoice_excludes_non_billable_and_unapproved_time
    """
    ctx = fixtures.setup_ticket_in_progress(
        engagement_overrides=TM_ENGAGEMENT, ticket_overrides={"title": "Search API"}
    )
    ticket_id = ctx["ticket"]["id"]
    billable = fixtures.log_time(ticket_id, 2.0, work_date="2026-05-05", billable=True)
    fixtures.approve_time(billable["id"])
    non_billable = fixtures.log_time(ticket_id, 1.0, work_date="2026-05-05", billable=False)
    fixtures.approve_time(non_billable["id"])
    fixtures.log_time(ticket_id, 3.0, work_date="2026-05-05")  # left SUBMITTED

    invoice = fixtures.create_invoice(
        ctx["engagement"]["id"],
        "TIME_AND_MATERIALS",
        period_start="2026-05-01",
        period_end="2026-05-31",
    )
    assert len(invoice["lines"]) == 1, f"one eligible ticket, got {len(invoice['lines'])} lines"
    assert invoice["lines"][0]["amount"] == pytest.approx(400.00, abs=0.01), (
        "only the 2.0 approved billable hours are billed, at 200.00/h"
    )
    assert invoice["subtotal"] == pytest.approx(400.00, abs=0.01)
    assert invoice["tax"] == pytest.approx(33.00, abs=0.01)
    assert invoice["total"] == pytest.approx(433.00, abs=0.01)

    engagement = validate_success(api.get_engagement(ctx["engagement"]["id"], DL))
    assert engagement["approved_hours"] == pytest.approx(2.0, abs=0.01), (
        "the approved non-billable entry stays out of the burn ledger"
    )
    ticket = validate_success(api.get_ticket(ticket_id, DL))
    assert ticket["actual_hours"] == pytest.approx(3.0, abs=0.01), (
        "the ticket roll-up counts every APPROVED entry, billable or not"
    )


def test_issuing_an_invoice_with_zero_lines_is_rejected(api):
    """PRD 3.8: "An invoice whose computed `lines` array comes out empty is still created — a time-and-materials period with no approved billable hours in it produces exactly that — but it can never be issued."
    PRD 3.8: "Only a `DRAFT` invoice may be issued; the attempt is refused with `ERR_INVOICE_NO_LINES` (HTTP 422) if the invoice has no lines, and with `ERR_MILESTONE_NOT_COMPLETED` (HTTP 409) if it is a `MILESTONE` invoice whose milestone has not reached `COMPLETED`."

    Design: Corner/validations/issue_invoice_with_zero_lines_is_rejected
    """
    ctx = fixtures.setup_active_engagement(**TM_ENGAGEMENT)
    invoice = fixtures.create_invoice(
        ctx["engagement"]["id"],
        "TIME_AND_MATERIALS",
        period_start="2026-05-01",
        period_end="2026-05-31",
    )
    assert invoice["lines"] == [], "no approved billable hours produce an empty lines array"
    assert invoice["subtotal"] == pytest.approx(0.0, abs=0.01)

    resp = api.issue_invoice(invoice["id"], FIN)
    validate_error(resp, ApiErrorId.ERR_INVOICE_NO_LINES.value)

    after = validate_success(api.get_invoice(invoice["id"], FIN))
    assert after["status"] == "DRAFT", "the refused issue leaves the invoice in DRAFT"
    engagement = validate_success(api.get_engagement(ctx["engagement"]["id"], DL))
    assert engagement["billing_status"] == "UNBILLED"


def test_second_live_invoice_for_the_same_milestone_is_rejected(api):
    """PRD 3.8: "A milestone may carry at most one live invoice: if an invoice already exists for that `milestone_id` in `DRAFT`, `ISSUED` or `PAID` status, a second create is rejected with `ERR_DUPLICATE_MILESTONE_INVOICE` (HTTP 409) — only a `VOID` invoice frees the milestone for a fresh attempt."

    Design: Corner/validations/duplicate_milestone_invoice_is_rejected
    """
    ctx = fixtures.setup_accepted_release()  # the cascade already raised a DRAFT invoice
    milestone_id = ctx["milestone"]["id"]

    resp = api.create_invoice(
        F.create_invoice_payload(
            engagement_id=ctx["engagement"]["id"],
            kind="MILESTONE",
            milestone_id=milestone_id,
            expected_engagement_version=fixtures.engagement_version(ctx["engagement"]["id"]),
        ),
        FIN,
    )
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_MILESTONE_INVOICE.value)

    invoices = validate_success(api.list_invoices(FIN, params={"milestone_id": milestone_id}))
    assert len(invoices) == 1, "the milestone still carries exactly one live invoice"


def test_milestone_invoice_on_a_time_and_materials_engagement_is_rejected(api):
    """PRD 3.8: "A `MILESTONE` invoice requires the engagement's `billing_model` to be `FIXED` and requires a `milestone_id`."
    PRD 3.8: "A mismatch between kind and billing model, or a missing kind-mandatory reference or period, is rejected with `ERR_INVOICE_KIND_MISMATCH` (HTTP 422)."

    Design: Corner/validations/milestone_invoice_on_a_time_and_materials_engagement_is_rejected
    """
    ctx = fixtures.setup_active_engagement(**TM_ENGAGEMENT)
    engagement_id = ctx["engagement"]["id"]
    milestone = fixtures.create_milestone(engagement_id, title="Phase 1", amount=5000.00)

    resp = api.create_invoice(
        F.create_invoice_payload(
            engagement_id=engagement_id,
            kind="MILESTONE",
            milestone_id=milestone["id"],
            expected_engagement_version=fixtures.engagement_version(engagement_id),
        ),
        FIN,
    )
    validate_error(resp, ApiErrorId.ERR_INVOICE_KIND_MISMATCH.value)

    invoices = validate_success(api.list_invoices(FIN, params={"engagement_id": engagement_id}))
    assert len(invoices) == 0, "the rejected create must not persist an invoice"


def test_paying_an_invoice_with_the_wrong_amount_is_rejected(api):
    """PRD 3.8: "Payment is recorded against an `ISSUED` invoice by supplying a `paid_amount` which must equal the invoice's `total` **exactly** — no partial payments, no overpayments; a mismatch is refused with `ERR_PAYMENT_AMOUNT_MISMATCH` (HTTP 422)."

    Design: Corner/validations/pay_with_wrong_amount_is_rejected
    """
    ctx = fixtures.setup_issued_milestone_invoice()
    invoice_id = ctx["invoice"]["id"]
    assert ctx["invoice"]["total"] == pytest.approx(5412.50, abs=0.01)

    resp = api.pay_invoice(invoice_id, 5000.00, FIN)
    validate_error(resp, ApiErrorId.ERR_PAYMENT_AMOUNT_MISMATCH.value)

    after = validate_success(api.get_invoice(invoice_id, FIN))
    assert after["status"] == "ISSUED", "a mismatched payment leaves the invoice ISSUED"
    assert after.get("paid_at") is None


def test_voiding_a_paid_invoice_is_rejected(api):
    """PRD 3.8: "A `PAID` invoice cannot be voided. `VOID` is terminal."
    PRD 2.9: "The **money ledger**: an engagement's `invoiced_amount` must equal the sum of `subtotal` over every invoice of that engagement whose status is `ISSUED` or `PAID`."

    Design: Corner/state_machines/void_a_paid_invoice_is_rejected
    """
    ctx = fixtures.setup_issued_milestone_invoice()
    invoice_id = ctx["invoice"]["id"]
    paid = validate_success(api.pay_invoice(invoice_id, 5412.50, FIN))
    assert paid["status"] == "PAID"

    resp = api.void_invoice(invoice_id, "Too late", FIN)
    validate_error(resp, ApiErrorId.ERR_INVALID_TRANSITION.value)

    after = validate_success(api.get_invoice(invoice_id, FIN))
    assert after["status"] == "PAID"
    engagement = validate_success(api.get_engagement(ctx["engagement"]["id"], DL))
    assert engagement["invoiced_amount"] == pytest.approx(5000.00, abs=0.01), (
        "an ISSUED or PAID invoice counts equally in the money ledger"
    )
    assert engagement["billing_status"] == "PARTIALLY_BILLED"
    milestone = validate_success(api.get_milestone(ctx["milestone"]["id"], DL))
    assert milestone["status"] == "BILLED"


def test_billing_status_reaches_fully_billed_while_delivery_stays_active(api):
    """PRD 2.9: "When `invoiced_amount` is greater than or equal to `contract_value` it is `FULLY_BILLED`."
    PRD 2.9: "`billing_status` is a pure function of that money ledger, recomputed after every issue and every void, and it moves independently of the engagement's delivery `status`: an `ACTIVE` engagement may be `UNBILLED`, `PARTIALLY_BILLED` or `FULLY_BILLED`."

    Design: Corner/cross_cutting_complexity_layers/engagement_billing_status_reaches_fully_billed_on_issue
    """
    ctx = fixtures.setup_accepted_release(
        engagement_overrides={
            "billing_model": "FIXED",
            "contract_value": 5000.00,
            "budget_hours_cap": 40,
        },
        milestone_overrides={"title": "Whole project", "amount": 5000.00},
    )
    issued = validate_success(api.issue_invoice(ctx["invoice"]["id"], FIN))
    assert issued["status"] == "ISSUED"

    engagement = validate_success(api.get_engagement(ctx["engagement"]["id"], DL))
    assert engagement["invoiced_amount"] == pytest.approx(5000.00, abs=0.01), (
        "invoiced_amount sums subtotals and is therefore tax-exclusive"
    )
    assert engagement["billing_status"] == "FULLY_BILLED"
    assert engagement["status"] == "ACTIVE", "the delivery dimension is untouched by billing"
    assert_billing_status_matches_ledger(engagement)
    milestone = validate_success(api.get_milestone(ctx["milestone"]["id"], DL))
    assert milestone["status"] == "BILLED"


def test_invoice_create_with_a_stale_engagement_version_is_rejected(api):
    """PRD 2.7: "Creating an invoice likewise requires `expected_engagement_version` in the body, carrying the `version` of the target `Engagement` as the finance officer last observed it. Invoice creation snapshots the engagement's billing ledger — approved hours, milestone status, contract value — so if the engagement's `version` has advanced since that read, the snapshot is stale and the create is rejected with `ERR_STALE_ENGAGEMENT_VERSION` (HTTP 412)."

    Design: Corner/cross_cutting_complexity_layers/occ_stale_engagement_version_on_invoice_create
    """
    ctx = fixtures.setup_ticket_in_progress(
        engagement_overrides=TM_ENGAGEMENT, ticket_overrides={"title": "Reports"}
    )
    engagement_id = ctx["engagement"]["id"]
    observed_version = fixtures.engagement_version(engagement_id, FIN)

    entry = fixtures.log_time(ctx["ticket"]["id"], 2.0)
    fixtures.approve_time(entry["id"])  # the approval cascade bumps the engagement's version

    resp = api.create_invoice(
        F.create_invoice_payload(
            engagement_id=engagement_id,
            kind="TIME_AND_MATERIALS",
            expected_engagement_version=observed_version,
            period_start="2026-05-01",
            period_end="2026-05-31",
        ),
        FIN,
    )
    validate_error(resp, ApiErrorId.ERR_STALE_ENGAGEMENT_VERSION.value)

    invoices = validate_success(api.list_invoices(FIN, params={"engagement_id": engagement_id}))
    assert len(invoices) == 0, "the stale create must not persist an invoice"


# ---------------------------------------------------------------------------
# The pinned rounding order
# ---------------------------------------------------------------------------
def test_invoice_rounds_each_line_before_summing_the_subtotal(api):
    """PRD 3.8: "**Each line's `amount` is rounded half up to 2 decimal places on its own, and the `subtotal` is the plain sum of those already-rounded line amounts** — summing raw products and rounding once at the end is a different, wrong number."
    PRD 3.8: "The eligible entries are grouped by ticket, and the tickets are emitted in ascending order of the ticket's `created_at`; the ticket identifier is never used for ordering."

    Design: Difficulty/combinatorial_formula/invoice_per_line_rounding_then_sum_mode_b
    """
    ctx = fixtures.setup_active_sprint(
        engagement_overrides={
            "billing_model": "TIME_AND_MATERIALS",
            "contract_value": 100000.00,
            "budget_hours_cap": 100,
            "standard_hourly_rate": 187.55,
        }
    )
    sprint_id = ctx["sprint"]["id"]
    ticket_a = fixtures.create_ticket(
        sprint_id, title="Auth service", estimated_hours=4, assignee_user_id="eng-001"
    )
    ticket_b = fixtures.create_ticket(
        sprint_id, title="Billing sync", estimated_hours=4, assignee_user_id="eng-001"
    )
    fixtures.start_ticket(ticket_a["id"], "eng-001")
    fixtures.start_ticket(ticket_b["id"], "eng-001")
    entry_a = fixtures.log_time(ticket_a["id"], 1.33, work_date="2026-05-05")
    fixtures.approve_time(entry_a["id"])
    entry_b = fixtures.log_time(ticket_b["id"], 2.17, work_date="2026-05-05")
    fixtures.approve_time(entry_b["id"])

    invoice = fixtures.create_invoice(
        ctx["engagement"]["id"],
        "TIME_AND_MATERIALS",
        period_start="2026-05-01",
        period_end="2026-05-31",
    )
    assert len(invoice["lines"]) == 2, f"one line per ticket, got {len(invoice['lines'])}"
    assert invoice["lines"][0]["label"] == "Auth service", (
        "lines are emitted in ascending order of the ticket's created_at"
    )
    assert invoice["lines"][1]["label"] == "Billing sync"
    assert invoice["lines"][0]["amount"] == pytest.approx(249.44, abs=0.005), (
        "1.33h at 187.55/h rounds to 249.44 on its own"
    )
    assert invoice["lines"][1]["amount"] == pytest.approx(406.98, abs=0.005), (
        "2.17h at 187.55/h rounds to 406.98 on its own"
    )
    assert invoice["subtotal"] == pytest.approx(656.42, abs=0.005), (
        f"the subtotal is 249.44 + 406.98 = 656.42, not the 656.43 that summing raw "
        f"products would give; got {invoice['subtotal']}"
    )
    assert invoice["tax"] == pytest.approx(54.15, abs=0.005)
    assert invoice["total"] == pytest.approx(710.57, abs=0.005)
    assert_lines_sum_to_subtotal(invoice)
    assert_total_is_subtotal_plus_tax(invoice)


def test_burn_rounds_on_the_aggregate_and_may_diverge_from_the_invoice_subtotal(api):
    """PRD 2.8: "The engagement's burn rounds **once, on the aggregate**: total approved hours are multiplied by the blended rate and the single product is rounded. An invoice rounds **per line and then sums**: each line amount is rounded to 2 decimal places on its own, and the subtotal is the plain arithmetic sum of those already-rounded line amounts with no further rounding applied."
    PRD 2.8: "For identical hours these two disciplines can disagree by a cent. That divergence is intentional; each figure is correct under its own pinned rule, and neither may be "reconciled" against the other."

    Design: Difficulty/combinatorial_formula/invoice_per_line_rounding_then_sum_mode_b
    """
    ctx = fixtures.setup_active_sprint(
        engagement_overrides={
            "billing_model": "TIME_AND_MATERIALS",
            "contract_value": 100000.00,
            "budget_hours_cap": 100,
            "standard_hourly_rate": 187.55,
        }
    )
    sprint_id = ctx["sprint"]["id"]
    ticket_a = fixtures.create_ticket(
        sprint_id, title="Auth service", estimated_hours=4, assignee_user_id="eng-001"
    )
    ticket_b = fixtures.create_ticket(
        sprint_id, title="Billing sync", estimated_hours=4, assignee_user_id="eng-001"
    )
    fixtures.start_ticket(ticket_a["id"], "eng-001")
    fixtures.start_ticket(ticket_b["id"], "eng-001")
    entry_a = fixtures.log_time(ticket_a["id"], 1.33, work_date="2026-05-05")
    fixtures.approve_time(entry_a["id"])
    entry_b = fixtures.log_time(ticket_b["id"], 2.17, work_date="2026-05-05")
    fixtures.approve_time(entry_b["id"])

    invoice = fixtures.create_invoice(
        ctx["engagement"]["id"],
        "TIME_AND_MATERIALS",
        period_start="2026-05-01",
        period_end="2026-05-31",
    )
    engagement = validate_success(api.get_engagement(ctx["engagement"]["id"], DL))

    assert engagement["approved_hours"] == pytest.approx(3.5, abs=0.01)
    assert engagement["burned_cost"] == pytest.approx(656.43, abs=0.005), (
        f"3.5h at 187.55/h is 656.425, rounded half up once on the aggregate to 656.43; "
        f"got {engagement['burned_cost']}"
    )
    assert invoice["subtotal"] == pytest.approx(656.42, abs=0.005)
    assert invoice["subtotal"] != engagement["burned_cost"], (
        "the per-line and aggregate disciplines disagree by a cent, and neither is "
        "reconciled against the other"
    )


# ---------------------------------------------------------------------------
# The invoice depends on its milestone's state
# ---------------------------------------------------------------------------
def test_issuing_a_milestone_invoice_whose_milestone_is_still_planned_is_rejected(api):
    """PRD 3.8: "Only a `DRAFT` invoice may be issued; the attempt is refused with `ERR_INVOICE_NO_LINES` (HTTP 422) if the invoice has no lines, and with `ERR_MILESTONE_NOT_COMPLETED` (HTTP 409) if it is a `MILESTONE` invoice whose milestone has not reached `COMPLETED`."

    Design: Difficulty/cross_entity_state_dependency/milestone_invoice_issue_requires_completed_milestone_cross_entity_invoice_milestone
    """
    ctx = fixtures.setup_active_engagement(
        billing_model="FIXED", contract_value=50000.00, budget_hours_cap=200
    )
    engagement_id = ctx["engagement"]["id"]
    milestone = fixtures.create_milestone(
        engagement_id, title="Phase 1 - Design", amount=5000.00
    )
    invoice = fixtures.create_invoice(
        engagement_id, "MILESTONE", milestone_id=milestone["id"]
    )
    assert invoice["status"] == "DRAFT"
    assert invoice["total"] == pytest.approx(5412.50, abs=0.01), (
        "the invoice itself is perfectly well-formed; only its milestone is not ready"
    )

    resp = api.issue_invoice(invoice["id"], FIN)
    validate_error(resp, ApiErrorId.ERR_MILESTONE_NOT_COMPLETED.value)

    after = validate_success(api.get_invoice(invoice["id"], FIN))
    assert after["status"] == "DRAFT"
    assert validate_success(api.get_milestone(milestone["id"], DL))["status"] == "PLANNED"


def test_the_same_milestone_invoice_issues_once_its_milestone_is_completed(api):
    """PRD 3.8: "On success the invoice moves `DRAFT → ISSUED`, `issued_at` is stamped from the logical clock, a `MILESTONE` invoice drags its milestone `COMPLETED → BILLED`, the engagement's `invoiced_amount` is recomputed as the sum of `subtotal` over the engagement's `ISSUED` and `PAID` invoices, the engagement's `billing_status` is recomputed from it per §2.9, and the engagement's `version` increments by 1."
    PRD 2.9: "When `invoiced_amount` is exactly 0 the engagement is `UNBILLED`."

    Design: Difficulty/cross_entity_state_dependency/milestone_invoice_issue_requires_completed_milestone_cross_entity_invoice_milestone
    """
    ctx = fixtures.setup_qa_passed_release(
        milestone_overrides={"title": "Phase 1 - Design", "amount": 5000.00}
    )
    engagement_id = ctx["engagement"]["id"]
    milestone_id = ctx["milestone"]["id"]
    invoice = fixtures.create_invoice(
        engagement_id, "MILESTONE", milestone_id=milestone_id
    )

    blocked = api.issue_invoice(invoice["id"], FIN)
    validate_error(blocked, ApiErrorId.ERR_MILESTONE_NOT_COMPLETED.value)
    before = validate_success(api.get_engagement(engagement_id, DL))
    assert before["invoiced_amount"] == pytest.approx(0.0, abs=0.01)
    assert before["billing_status"] == "UNBILLED"

    # Client acceptance completes the milestone; the invoice's own state never changed.
    validate_success(api.decide_acceptance(ctx["release"]["id"], "ACCEPT", ctx["client_headers"]))
    assert validate_success(api.get_milestone(milestone_id, DL))["status"] == "COMPLETED"

    issued = validate_success(api.issue_invoice(invoice["id"], FIN))
    assert issued["status"] == "ISSUED", "the identical issue succeeds once the milestone is COMPLETED"
    assert validate_success(api.get_milestone(milestone_id, DL))["status"] == "BILLED"


# ---------------------------------------------------------------------------
# The compensating void
# ---------------------------------------------------------------------------
def test_voiding_an_issued_invoice_walks_the_milestone_back_to_completed(api):
    """PRD 3.8: "Voiding an `ISSUED` invoice unwinds the issue link by link: the invoice moves `ISSUED → VOID`; if it was a `MILESTONE` invoice, the milestone is walked back `BILLED → COMPLETED`; the engagement's `invoiced_amount` and `billing_status` are recomputed; and the engagement's `version` increments by 1."

    Design: Difficulty/compensating_invariant/invoice_void_restores_money_ledger_and_milestone_status_with_zero_drift
    """
    ctx = fixtures.setup_issued_milestone_invoice()
    assert validate_success(api.get_milestone(ctx["milestone"]["id"], DL))["status"] == "BILLED"

    voided = validate_success(
        api.void_invoice(ctx["invoice"]["id"], "Client disputed the scope of Phase 1", FIN)
    )
    assert voided["status"] == "VOID"

    milestone = validate_success(api.get_milestone(ctx["milestone"]["id"], DL))
    assert milestone["status"] == "COMPLETED", (
        f"the void walks the milestone back from BILLED, got {milestone['status']}"
    )
    release = validate_success(api.get_release(ctx["release"]["id"], DL))
    assert release["status"] == "ACCEPTED", "voiding the invoice does not un-accept the release"


def test_voiding_an_issued_invoice_restores_the_money_ledger_with_zero_drift(api):
    """PRD 2.9: "Issuing an invoice and then voiding it must restore `invoiced_amount`, the engagement's `billing_status`, and the linked milestone's own status to exactly their pre-issue values."
    PRD 2.9: "The **money ledger**: an engagement's `invoiced_amount` must equal the sum of `subtotal` over every invoice of that engagement whose status is `ISSUED` or `PAID`. Invoices in `DRAFT` or `VOID` contribute nothing."

    Design: Difficulty/compensating_invariant/invoice_void_restores_money_ledger_and_milestone_status_with_zero_drift
    """
    ctx = fixtures.setup_issued_milestone_invoice()
    engagement_id = ctx["engagement"]["id"]

    billed = validate_success(api.get_engagement(engagement_id, DL))
    assert billed["invoiced_amount"] == pytest.approx(5000.00, abs=0.01)
    assert billed["billing_status"] == "PARTIALLY_BILLED"

    validate_success(api.void_invoice(ctx["invoice"]["id"], "Disputed", FIN))

    engagement = validate_success(api.get_engagement(engagement_id, DL))
    assert engagement["invoiced_amount"] == pytest.approx(0.0, abs=0.01), (
        f"a VOID invoice contributes nothing to the money ledger, got "
        f"{engagement['invoiced_amount']}"
    )
    assert engagement["billing_status"] == "UNBILLED"
    assert_billing_status_matches_ledger(engagement)

    live = [
        inv
        for inv in validate_success(
            api.list_invoices(FIN, params={"engagement_id": engagement_id})
        )
        if inv["status"] in ("ISSUED", "PAID")
    ]
    assert live == [], "no ISSUED or PAID invoice remains, so the ledger sum is 0.00"
