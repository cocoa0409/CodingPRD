"""Composite setup helpers for multi-step test prerequisites.

Encapsulates the long onboarding/funding chains that nearly every interesting
claim requires, so tests can focus on assertions. Uses get_success_data()
(lenient validator) internally so setup failures surface clearly.

The canonical funding chain is:
  program -> client -> approve client -> debtor -> approve debtor ->
  relationship -> send-notice -> invoice -> verify -> batch -> fund

All officer identities default to: underwriter uw_1, funding fo_1,
collections co_1, admin admin_1 (distinct so the default funder differs from
the default credit-decision user; segregation of duties passes by default).
"""
from prd_bench_local_runner.testing import get_success_data
from .api_client import api_client
from .factories import (
    create_program_payload, create_client_payload, approve_client_payload,
    create_debtor_payload, approve_debtor_payload, create_relationship_payload,
    create_invoice_payload, verify_payload, create_batch_payload,
    fund_batch_payload, create_posting_payload,
)
from .test_users import (
    make_admin_headers, make_underwriter_headers, make_funding_headers,
    make_collections_headers,
)

ADMIN = make_admin_headers("admin_1")
UW = make_underwriter_headers("uw_1")
FO = make_funding_headers("fo_1")
CO = make_collections_headers("co_1")

_inv_counter = {"n": 0}


def _next_invoice_number(prefix="INV"):
    _inv_counter["n"] += 1
    return f"{prefix}-{_inv_counter['n']}"


# ─── Tier 1: primitives ──────────────────────────────────────────────────────

def create_program(**overrides):
    """Create a FactoringProgram (ACTIVE). Returns the program dict."""
    res = api_client.create_program(create_program_payload(**overrides), ADMIN)
    return get_success_data(res)


def create_pending_client(program_id, **overrides):
    """Onboard a PENDING client. Returns the client dict."""
    res = api_client.create_client(create_client_payload(program_id, **overrides), ADMIN)
    return get_success_data(res)


def create_approved_client(program_id, approve_overrides=None, client_overrides=None,
                           uw_user_id="uw_1"):
    """Onboard a client and credit-approve it. Returns the approved client dict."""
    client = create_pending_client(program_id, **(client_overrides or {}))
    res = api_client.client_credit_decision(
        client["id"], approve_client_payload(**(approve_overrides or {})),
        make_underwriter_headers(uw_user_id),
    )
    return get_success_data(res)


def create_pending_debtor(program_id, **overrides):
    res = api_client.create_debtor(create_debtor_payload(program_id, **overrides), ADMIN)
    return get_success_data(res)


def create_approved_debtor(program_id, approve_overrides=None, debtor_overrides=None,
                           uw_user_id="uw_1"):
    """Onboard a debtor and credit-approve it. Returns the approved debtor dict."""
    debtor = create_pending_debtor(program_id, **(debtor_overrides or {}))
    res = api_client.debtor_credit_decision(
        debtor["id"], approve_debtor_payload(**(approve_overrides or {})),
        make_underwriter_headers(uw_user_id),
    )
    return get_success_data(res)


def create_relationship(client_id, debtor_id, noticed=True, **overrides):
    """Create a relationship; if noticed, send the notice-of-assignment.
    Returns the relationship dict (re-read after send-notice when noticed)."""
    rel = get_success_data(api_client.create_relationship(
        create_relationship_payload(client_id, debtor_id, **overrides), FO))
    if noticed:
        rel = get_success_data(api_client.send_notice(rel["id"], FO))
    return rel


# ─── Tier 2: parties ready to fund ───────────────────────────────────────────

def setup_funding_ready(program_overrides=None, client_approve_overrides=None,
                        client_overrides=None, debtor_approve_overrides=None,
                        debtor_overrides=None, relationship_overrides=None,
                        noticed=True, uw_user_id="uw_1"):
    """Program + APPROVED client + APPROVED debtor + relationship (noticed by
    default). Returns dict with program, client, debtor, relationship."""
    program = create_program(**(program_overrides or {}))
    client = create_approved_client(
        program["id"], approve_overrides=client_approve_overrides,
        client_overrides=client_overrides, uw_user_id=uw_user_id)
    debtor = create_approved_debtor(
        program["id"], approve_overrides=debtor_approve_overrides,
        debtor_overrides=debtor_overrides, uw_user_id=uw_user_id)
    relationship = create_relationship(
        client["id"], debtor["id"], noticed=noticed, **(relationship_overrides or {}))
    return {
        "program": program,
        "client": client,
        "debtor": debtor,
        "relationship": relationship,
    }


def submit_invoice(client_id, debtor_id, invoice_number=None, **overrides):
    """Submit a SUBMITTED invoice. Returns the invoice dict."""
    invoice_number = invoice_number or _next_invoice_number()
    res = api_client.create_invoice(
        create_invoice_payload(client_id, debtor_id, invoice_number, **overrides), FO)
    return get_success_data(res)


def submit_and_verify_invoice(client_id, debtor_id, invoice_number=None,
                              verify_method="WAIVED", confirmed_amount_cents=None,
                              **invoice_overrides):
    """Submit an invoice and verify it. Returns the VERIFIED invoice dict."""
    invoice = submit_invoice(client_id, debtor_id, invoice_number, **invoice_overrides)
    if confirmed_amount_cents is None:
        confirmed_amount_cents = invoice["face_amount_cents"]
    res = api_client.verify_invoice(
        invoice["id"],
        verify_payload(method=verify_method, confirmed_amount_cents=confirmed_amount_cents),
        FO)
    return get_success_data(res)


def _current_client_version(client_id, headers=FO):
    return get_success_data(api_client.get_client(client_id, headers))["version"]


def fund_single_invoice(client, debtor, invoice_overrides=None, batch_reference="B",
                        funding_user_id="fo_1"):
    """Submit + verify a single invoice, batch it, and fund it. Returns dict with
    invoice (re-read after funding), batch (after fund), client_id, debtor_id.

    `client` and `debtor` are the approved party dicts from setup_funding_ready.
    """
    invoice = submit_and_verify_invoice(
        client["id"], debtor["id"], **(invoice_overrides or {}))
    batch = get_success_data(api_client.create_batch(
        create_batch_payload(client["id"], [invoice["id"]], batch_reference=batch_reference),
        FO))
    cv = _current_client_version(client["id"])
    fund_res = api_client.fund_batch(
        batch["id"], fund_batch_payload(cv), make_funding_headers(funding_user_id))
    funded_batch = get_success_data(fund_res)
    funded_invoice = get_success_data(api_client.get_invoice(invoice["id"], FO))
    return {
        "invoice": funded_invoice,
        "batch": funded_batch,
        "client_id": client["id"],
        "debtor_id": debtor["id"],
    }


def setup_funded_invoice(face_amount_cents=100000, advance_rate_pct=0.85,
                         fee_rate_per_day=0.0005, tier2_multiplier=1.5,
                         tier3_multiplier=2.0, recourse_type="RECOURSE",
                         recourse_grace_days=90, verification_required=False,
                         credit_limit_cents=100_000_000,
                         concentration_pct=0.90, ceiling_cents=100_000_000,
                         invoice_overrides=None):
    """End-to-end: program/client/debtor/relationship + one FUNDED invoice at
    the default clock. Returns dict: program, client, debtor, relationship,
    invoice (FUNDED, re-read), batch."""
    parties = setup_funding_ready(
        program_overrides={
            "default_fee_rate_per_day": fee_rate_per_day,
            "tier2_multiplier": tier2_multiplier,
            "tier3_multiplier": tier3_multiplier,
            "recourse_grace_days": recourse_grace_days,
        },
        client_approve_overrides={
            "approved_advance_rate_pct": advance_rate_pct,
            "credit_limit_cents": credit_limit_cents,
            "default_concentration_limit_pct": concentration_pct,
        },
        client_overrides={"requested_advance_rate_pct": advance_rate_pct},
        debtor_approve_overrides={
            "approved_credit_ceiling_cents": ceiling_cents,
            "verification_required": verification_required,
        },
        relationship_overrides={"recourse_type": recourse_type},
    )
    inv_over = {"face_amount_cents": face_amount_cents}
    inv_over.update(invoice_overrides or {})
    funded = fund_single_invoice(
        parties["client"], parties["debtor"], invoice_overrides=inv_over)
    return {
        "program": parties["program"],
        "client": parties["client"],
        "debtor": parties["debtor"],
        "relationship": parties["relationship"],
        "invoice": funded["invoice"],
        "batch": funded["batch"],
    }


# ─── Tier 3: terminal collection states ──────────────────────────────────────

def post_collection(invoice_id, client_id, amount_cents, received_at,
                    payer="DEBTOR", funding_headers=CO):
    """Post a single collection against an invoice using the current client
    version. Returns the posting dict (or the response data)."""
    cv = _current_client_version(client_id, funding_headers)
    res = api_client.create_posting(
        invoice_id,
        create_posting_payload(amount_cents, received_at, cv, payer=payer),
        funding_headers)
    return get_success_data(res)


def advance_clock(to_iso8601):
    """Advance the server logical clock. Returns the raw response."""
    return api_client.set_clock(to_iso8601, ADMIN)


def setup_outstanding_invoice(clock_to="2026-06-10T00:00:00Z", **funded_kwargs):
    """Build a FUNDED invoice then advance the clock past due_date so the
    automatic FUNDED->OUTSTANDING fires. Returns the same dict as
    setup_funded_invoice with the invoice re-read (OUTSTANDING)."""
    ctx = setup_funded_invoice(**funded_kwargs)
    advance_clock(clock_to)
    ctx["invoice"] = get_success_data(api_client.get_invoice(ctx["invoice"]["id"], CO))
    return ctx


def setup_short_paid_invoice(partial_amount_cents=80000,
                             received_at="2026-06-10T00:00:00Z",
                             clock_to="2026-06-10T00:00:00Z", **funded_kwargs):
    """Build a FUNDED invoice, advance clock past due (-> OUTSTANDING), post a
    partial collection, then close-collection (-> SHORT_PAID). Returns ctx with
    invoice re-read (SHORT_PAID)."""
    ctx = setup_funded_invoice(**funded_kwargs)
    advance_clock(clock_to)
    post_collection(ctx["invoice"]["id"], ctx["client"]["id"],
                    partial_amount_cents, received_at)
    get_success_data(api_client.close_collection(ctx["invoice"]["id"], CO))
    ctx["invoice"] = get_success_data(api_client.get_invoice(ctx["invoice"]["id"], CO))
    return ctx
