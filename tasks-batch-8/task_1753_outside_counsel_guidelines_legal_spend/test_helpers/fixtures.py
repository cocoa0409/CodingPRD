"""Composite setup helpers for the outside-counsel spend test suite.

The runner restarts the server before every test, so every helper builds its
preconditions from scratch using only PRD-declared endpoints. Setup calls use
get_success_data() so a failed precondition surfaces as a clear "Setup step
failed" message rather than a confusing assertion error.

Identity threading: PanelFirmUser is entity-backed (PRD §2.1), so every
ownership-gated call uses make_panel_firm_headers(firm["id"]).
"""
from prd_bench_local_runner.testing import get_success_data

from test_helpers.api_client import api_client
from test_helpers.constants import TEST_DEFAULTS
from test_helpers.factories import (
    create_accrual_payload,
    create_appeal_payload,
    create_guideline_version_payload,
    create_invoice_payload,
    create_legal_department_payload,
    create_matter_payload,
    create_panel_firm_payload,
    create_rate_card_payload,
    create_rate_row_payload,
    create_timekeeper_payload,
    make_line_item,
    put_forecast_payload,
    set_clock_payload,
)
from test_helpers.test_users import TEST_USERS, make_panel_firm_headers


def ops_headers() -> dict:
    """LegalOpsReviewer (opaque role) headers."""
    return TEST_USERS["legal_ops_headers"]


def firm_headers(firm_id: str) -> dict:
    """PanelFirmUser headers bound to the given firm id (ownership-gated calls)."""
    return make_panel_firm_headers(firm_id)


# ---------------------------------------------------------------------------
# Tier 1/2: department, firm, timekeepers
# ---------------------------------------------------------------------------

def create_department(**overrides) -> dict:
    """Create a legal department. Returns the created department."""
    return get_success_data(
        api_client.create_legal_department(create_legal_department_payload(**overrides), ops_headers())
    )


def create_firm(dept_id: str, firm_name: str = None) -> dict:
    """Onboard a panel firm (starts ACTIVE, version 1). Returns the firm."""
    payload = create_panel_firm_payload(**({"firm_name": firm_name} if firm_name else {}))
    return get_success_data(api_client.create_panel_firm(dept_id, payload, ops_headers()))


def setup_department_with_firm(**dept_overrides) -> tuple:
    """Department + one ACTIVE panel firm. Returns (dept, firm)."""
    dept = create_department(**dept_overrides)
    firm = create_firm(dept["id"])
    return dept, firm


def register_timekeeper(dept_id: str, firm_id: str, full_name: str = "Pat Partner",
                        tk_class: str = "PARTNER") -> dict:
    """Register a timekeeper under the firm (qualification_status PENDING)."""
    return get_success_data(
        api_client.create_timekeeper(
            dept_id, firm_id,
            create_timekeeper_payload(full_name=full_name, tk_class=tk_class),
            firm_headers(firm_id),
        )
    )


def qualify_timekeeper(dept_id: str, firm_id: str, tk_id: str) -> dict:
    """Mark a timekeeper QUALIFIED."""
    return get_success_data(api_client.qualify_timekeeper(dept_id, firm_id, tk_id, ops_headers()))


def register_and_qualify_timekeeper(dept_id: str, firm_id: str, full_name: str = "Pat Partner",
                                    tk_class: str = "PARTNER") -> dict:
    tk = register_timekeeper(dept_id, firm_id, full_name, tk_class)
    return qualify_timekeeper(dept_id, firm_id, tk["id"])


# ---------------------------------------------------------------------------
# Tier 3: rate-card lifecycle
# ---------------------------------------------------------------------------

def get_firm(dept_id: str, firm_id: str) -> dict:
    return get_success_data(api_client.get_panel_firm(dept_id, firm_id, ops_headers()))


def create_draft_rate_card(dept_id: str, firm_id: str, effective_year: int = None) -> dict:
    """Create a DRAFT rate card with a fresh OCC read of the firm's version."""
    year = effective_year if effective_year is not None else TEST_DEFAULTS["EFFECTIVE_YEAR"]
    firm_v = get_firm(dept_id, firm_id)["version"]
    return get_success_data(
        api_client.create_rate_card(
            dept_id, firm_id,
            create_rate_card_payload(effective_year=year, expected_panel_firm_version=firm_v),
            firm_headers(firm_id),
        )
    )


def add_rate_row(dept_id: str, firm_id: str, card_id: str, timekeeper_id: str,
                 hourly_rate_cents: int) -> dict:
    return get_success_data(
        api_client.add_rate_row(
            dept_id, firm_id, card_id,
            create_rate_row_payload(timekeeper_id=timekeeper_id, hourly_rate_cents=hourly_rate_cents),
            firm_headers(firm_id),
        )
    )


def submit_rate_card(dept_id: str, firm_id: str, card_id: str) -> dict:
    return get_success_data(api_client.submit_rate_card(dept_id, firm_id, card_id, firm_headers(firm_id)))


def approve_rate_card(dept_id: str, firm_id: str, card_id: str) -> dict:
    return get_success_data(api_client.approve_rate_card(dept_id, firm_id, card_id, ops_headers()))


def create_approved_rate_card(dept_id: str, firm_id: str, rates: list, effective_year: int = None) -> dict:
    """Full chain: DRAFT card -> one rate row per (timekeeper_id, cents) -> submit -> approve.

    rates: list of (timekeeper_id, hourly_rate_cents) tuples.
    Returns the APPROVED card.
    """
    card = create_draft_rate_card(dept_id, firm_id, effective_year)
    for tk_id, cents in rates:
        add_rate_row(dept_id, firm_id, card["id"], tk_id, cents)
    submit_rate_card(dept_id, firm_id, card["id"])
    return approve_rate_card(dept_id, firm_id, card["id"])


# ---------------------------------------------------------------------------
# Tier 2/3: matters and engagement
# ---------------------------------------------------------------------------

def create_matter(dept_id: str, firm_id: str, title: str = None, budget_cents: int = None) -> dict:
    """Create a matter (engagement_status PENDING, spend counters zero)."""
    overrides = {}
    if title is not None:
        overrides["title"] = title
    if budget_cents is not None:
        overrides["budget_cents"] = budget_cents
    return get_success_data(
        api_client.create_matter(dept_id, create_matter_payload(panel_firm_id=firm_id, **overrides), ops_headers())
    )


def get_matter(dept_id: str, matter_id: str) -> dict:
    return get_success_data(api_client.get_matter(dept_id, matter_id, ops_headers()))


def engage_matter(dept_id: str, matter_id: str, firm_id: str) -> dict:
    return get_success_data(api_client.engage_matter(dept_id, matter_id, firm_headers(firm_id)))


def create_engaged_matter(dept_id: str, firm_id: str, title: str = None,
                          budget_cents: int = None) -> dict:
    """Create + engage a matter. Returns the matter re-read after engagement
    (so its version field is the current one for OCC invoice submission)."""
    matter = create_matter(dept_id, firm_id, title, budget_cents)
    engage_matter(dept_id, matter["id"], firm_id)
    return get_matter(dept_id, matter["id"])


# ---------------------------------------------------------------------------
# Tier 2 composite: billing-ready context
# ---------------------------------------------------------------------------

def setup_billing_ready(rate_cents: int = None, tk_class: str = "PARTNER",
                        budget_cents: int = None, effective_year: int = None,
                        dept_overrides: dict = None, firm_name: str = None) -> dict:
    """Department + ACTIVE firm + one QUALIFIED timekeeper + APPROVED rate card
    + ENGAGED matter. The standard preamble for invoice tests.

    Returns a dict: dept, firm, timekeeper, rate_card, matter, matter_version.
    """
    dept, firm = setup_department_with_firm(**(dept_overrides or {}))
    tk = register_and_qualify_timekeeper(dept["id"], firm["id"], tk_class=tk_class)
    rate = rate_cents if rate_cents is not None else TEST_DEFAULTS["PARTNER_RATE_CENTS"]
    card = create_approved_rate_card(dept["id"], firm["id"], [(tk["id"], rate)], effective_year)
    matter = create_engaged_matter(dept["id"], firm["id"], budget_cents=budget_cents)
    return {
        "dept": dept,
        "firm": firm,
        "timekeeper": tk,
        "rate_card": card,
        "matter": matter,
        "matter_version": matter["version"],
    }


# ---------------------------------------------------------------------------
# Tier 3: invoices, line items, appeals
# ---------------------------------------------------------------------------

def submit_invoice(dept_id: str, matter_id: str, firm_id: str, matter_version: int,
                   line_items: list, invoice_number: str = "INV-001",
                   period_start: str = None, period_end: str = None) -> dict:
    """Submit an e-billing invoice. Returns the created invoice (post auto-review)."""
    payload = create_invoice_payload(
        invoice_number=invoice_number,
        billing_period_start=period_start or TEST_DEFAULTS["PERIOD_START"],
        billing_period_end=period_end or TEST_DEFAULTS["PERIOD_END"],
        expected_matter_version=matter_version,
        line_items=line_items,
    )
    return get_success_data(api_client.create_invoice(dept_id, matter_id, payload, firm_headers(firm_id)))


def get_invoice(dept_id: str, matter_id: str, invoice_id: str) -> dict:
    return get_success_data(api_client.get_invoice(dept_id, matter_id, invoice_id, ops_headers()))


def list_line_items(dept_id: str, matter_id: str, invoice_id: str) -> list:
    return get_success_data(api_client.list_line_items(dept_id, matter_id, invoice_id, ops_headers()))


def get_line_by_task_code(lines: list, task_code: str) -> dict:
    """Find a line item by its UTBMS task code (stable under list ordering)."""
    matches = [ln for ln in lines if ln["utbms_task_code"] == task_code]
    assert len(matches) == 1, f"Expected exactly one line with task {task_code}, got {len(matches)}"
    return matches[0]


def get_line_item(dept_id: str, matter_id: str, invoice_id: str, line_id: str) -> dict:
    return get_success_data(api_client.get_line_item(dept_id, matter_id, invoice_id, line_id, ops_headers()))


def clean_line(tk_id: str, task_code: str = "L110", hours: float = 1.00,
               rate_cents: int = None, narrative: str = None) -> dict:
    """A line item the rule engine approves: single task marker in the
    narrative, rate equal to the timekeeper's approved rate."""
    return make_line_item(
        timekeeper_id=tk_id,
        utbms_task_code=task_code,
        narrative=narrative or f"professional services {task_code}",
        hours=hours,
        rate_cents=rate_cents if rate_cents is not None else TEST_DEFAULTS["PARTNER_RATE_CENTS"],
    )


def block_billed_line(tk_id: str, task_code: str = "L120", hours: float = 1.00,
                      rate_cents: int = None) -> dict:
    """A line item whose narrative carries two distinct L### markers, which the
    block-billing detector rejects (PRD §3.5)."""
    return make_line_item(
        timekeeper_id=tk_id,
        utbms_task_code=task_code,
        narrative="attended L110 hearing and drafted L220 response",
        hours=hours,
        rate_cents=rate_cents if rate_cents is not None else TEST_DEFAULTS["PARTNER_RATE_CENTS"],
    )


def rate_not_on_card_line(tk_id: str, task_code: str = "L110", hours: float = 1.00,
                          rate_cents: int = 90_000) -> dict:
    """A line whose rate matches no approved rate on the card yet sits below it,
    so the rule engine leaves it PENDING for manual review (PRD §3.5)."""
    return make_line_item(
        timekeeper_id=tk_id,
        utbms_task_code=task_code,
        narrative=f"research {task_code}",
        hours=hours,
        rate_cents=rate_cents,
    )


def file_appeal(dept_id: str, matter_id: str, invoice_id: str, line_id: str,
                firm_id: str, rationale: str = "The rejection is not supported") -> dict:
    return get_success_data(
        api_client.create_appeal(
            dept_id, matter_id, invoice_id, line_id,
            create_appeal_payload(rationale=rationale), firm_headers(firm_id),
        )
    )


def claim_appeal(dept_id: str, matter_id: str, invoice_id: str, line_id: str, appeal_id: str) -> dict:
    return get_success_data(
        api_client.claim_appeal(dept_id, matter_id, invoice_id, line_id, appeal_id, ops_headers())
    )


def grant_appeal(dept_id: str, matter_id: str, invoice_id: str, line_id: str,
                 appeal_id: str, note: str = "Accepted") -> dict:
    return get_success_data(
        api_client.grant_appeal(
            dept_id, matter_id, invoice_id, line_id, appeal_id,
            {"resolution_note": note}, ops_headers(),
        )
    )


def deny_appeal(dept_id: str, matter_id: str, invoice_id: str, line_id: str,
                appeal_id: str, note: str = "Rejected") -> dict:
    return get_success_data(
        api_client.deny_appeal(
            dept_id, matter_id, invoice_id, line_id, appeal_id,
            {"resolution_note": note}, ops_headers(),
        )
    )


def setup_partially_approved_invoice(firm_name: str = None) -> dict:
    """Billing-ready context plus one invoice whose line1 (L110, clean, 1h) is
    approved and line2 (L120, block-billed, 1h) is rejected, leaving the invoice
    PARTIALLY_APPROVED with approved_total_cents == 100000.

    Returns the billing context augmented with invoice, line1, line2.
    """
    ctx = setup_billing_ready(firm_name=firm_name)
    dept_id, firm_id = ctx["dept"]["id"], ctx["firm"]["id"]
    tk_id = ctx["timekeeper"]["id"]
    invoice = submit_invoice(
        dept_id, ctx["matter"]["id"], firm_id, ctx["matter_version"],
        [clean_line(tk_id, "L110", 1.00, 100_000), block_billed_line(tk_id, "L120", 1.00, 100_000)],
        invoice_number="INV-PARTIAL",
    )
    lines = list_line_items(dept_id, ctx["matter"]["id"], invoice["id"])
    ctx["invoice"] = invoice
    ctx["line1"] = get_line_by_task_code(lines, "L110")
    ctx["line2"] = get_line_by_task_code(lines, "L120")
    return ctx


def setup_rejected_invoice_with_claimed_appeal() -> dict:
    """Billing-ready context plus a single-line invoice whose only line is
    block-billed (invoice REJECTED, approved_total 0), with an appeal already
    filed and claimed (UNDER_REVIEW).

    Returns the billing context augmented with invoice, line, appeal.
    """
    ctx = setup_billing_ready()
    dept_id, firm_id = ctx["dept"]["id"], ctx["firm"]["id"]
    tk_id = ctx["timekeeper"]["id"]
    invoice = submit_invoice(
        dept_id, ctx["matter"]["id"], firm_id, ctx["matter_version"],
        [block_billed_line(tk_id, "L110", 5.00, 100_000)],
        invoice_number="INV-REJ",
    )
    line = get_line_by_task_code(list_line_items(dept_id, ctx["matter"]["id"], invoice["id"]), "L110")
    appeal = file_appeal(dept_id, ctx["matter"]["id"], invoice["id"], line["id"], firm_id)
    claim_appeal(dept_id, ctx["matter"]["id"], invoice["id"], line["id"], appeal["id"])
    ctx["invoice"] = invoice
    ctx["line"] = line
    ctx["appeal"] = appeal
    return ctx


# ---------------------------------------------------------------------------
# Tier 1: guidelines, acknowledgments, clock
# ---------------------------------------------------------------------------

def set_clock(to_iso8601: str) -> dict:
    return get_success_data(api_client.set_clock(set_clock_payload(to_iso8601=to_iso8601), ops_headers()))


def create_guideline(dept_id: str, version_label: str = "OCG-2026-A",
                     effective_date: str = "2026-09-01T00:00:00Z") -> dict:
    return get_success_data(
        api_client.create_guideline_version(
            dept_id,
            create_guideline_version_payload(version_label=version_label, effective_date=effective_date),
            ops_headers(),
        )
    )


def publish_guideline(dept_id: str, gv_id: str) -> dict:
    return get_success_data(api_client.publish_guideline_version(dept_id, gv_id, ops_headers()))


def list_acknowledgments(dept_id: str, firm_id: str, params: dict = None) -> list:
    return get_success_data(api_client.list_acknowledgments(dept_id, firm_id, ops_headers(), params=params))


def publish_guideline_and_get_ack(dept_id: str, firm_id: str,
                                  version_label: str = "OCG-2026-A",
                                  effective_date: str = "2026-09-01T00:00:00Z") -> tuple:
    """Publish a guideline version and return (version, the firm's cascade-created
    PENDING acknowledgment)."""
    gv = create_guideline(dept_id, version_label, effective_date)
    publish_guideline(dept_id, gv["id"])
    acks = list_acknowledgments(dept_id, firm_id)
    assert len(acks) == 1, f"Expected exactly one cascade-created acknowledgment, got {len(acks)}"
    return gv, acks[0]


# ---------------------------------------------------------------------------
# Tier 4: accruals and forecasts
# ---------------------------------------------------------------------------

def create_accrual(dept_id: str, matter_id: str, firm_id: str, period_year: int,
                   period_month: int, amount_cents: int) -> dict:
    return get_success_data(
        api_client.create_accrual(
            dept_id, matter_id,
            create_accrual_payload(period_year=period_year, period_month=period_month,
                                   amount_cents=amount_cents),
            firm_headers(firm_id),
        )
    )


def put_forecast(dept_id: str, matter_id: str, lifecycle_estimate_cents: int) -> dict:
    return get_success_data(
        api_client.put_forecast(
            dept_id, matter_id,
            put_forecast_payload(lifecycle_estimate_cents=lifecycle_estimate_cents),
            ops_headers(),
        )
    )


def get_forecast(dept_id: str, matter_id: str) -> dict:
    return get_success_data(api_client.get_forecast(dept_id, matter_id, ops_headers()))
