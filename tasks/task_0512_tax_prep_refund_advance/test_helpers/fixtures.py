"""Composite setup helpers for multi-step test prerequisites.

Most interesting claims require the system to be walked into a specific state
through many endpoint calls (open office -> file credential -> add preparer ->
intake client -> open return -> add docs -> assign -> DOCS_PENDING -> IN_PREP ->
PREPARED -> efile -> efile-ack ACCEPTED -> open bank product -> ...). These
helpers encapsulate the recurring preambles so tests focus on assertions.

All helpers use get_success_data() (lenient) so a setup failure surfaces as a
clear "Setup step failed" message rather than a confusing assertion failure.

Identity threading: TaxPreparer is the only entity-backed role. Wherever a call
is ownership-gated to the assigned preparer (efile, efile-ack, transitions that
read TaxReturn.preparer_id), the helpers pass make_tax_preparer_headers(prep_id)
with the real Preparer.id, never the shared constant.
"""
from prd_bench_local_runner.testing import get_success_data
from .api_client import api_client
from .factories import (
    create_office_payload,
    create_credential_payload,
    create_preparer_payload,
    create_client_payload,
    create_appointment_payload,
    create_return_payload,
    create_document_payload,
    create_audit_protection_payload,
    create_refund_transfer_payload,
    create_refund_advance_payload,
)
from .test_users import TEST_USERS, make_tax_preparer_headers

OM = TEST_USERS["office_manager_headers"]
FD = TEST_USERS["front_desk_headers"]
BO = TEST_USERS["bank_officer_headers"]


# ─── Tier 1: Primitive builders ───────────────────────────────────────────

def create_office(bank_product_enabled=False, **overrides):
    """Open a storefront. Returns the Office dict."""
    payload = create_office_payload(bank_product_enabled=bank_product_enabled, **overrides)
    return get_success_data(api_client.create_office(payload, OM))


def create_credential(office_id, **overrides):
    """File a PTIN credential under an office. Returns the credential dict."""
    payload = create_credential_payload(office_id, **overrides)
    return get_success_data(api_client.create_credential(payload, OM))


def create_preparer(office_id, credential_id, **overrides):
    """Add a preparer to an office. Returns the Preparer dict."""
    payload = create_preparer_payload(credential_id, **overrides)
    return get_success_data(api_client.create_preparer(office_id, payload, OM))


def create_client(office_id, **overrides):
    """Intake a taxpayer. Returns the Client dict."""
    payload = create_client_payload(**overrides)
    return get_success_data(api_client.create_client(office_id, payload, FD))


def create_return(office_id, client_id, headers=None, **overrides):
    """Open a tax return. Returns the TaxReturn dict.

    `headers` defaults to the front-desk operator (opaque), which is permitted
    to open returns; pass a preparer's headers when a later ownership-gated
    transition on the same return must match X-User-ID.
    """
    payload = create_return_payload(office_id, client_id, **overrides)
    return get_success_data(api_client.create_return(payload, headers or FD))


def add_document(return_id, headers, doc_type="W2", is_required=True, **overrides):
    """Add one document to a return's checklist. Returns the DocumentIntake."""
    payload = create_document_payload(doc_type=doc_type, is_required=is_required, **overrides)
    return get_success_data(api_client.create_document(return_id, payload, headers))


def set_document_received(document_id, headers):
    return get_success_data(api_client.set_document_status(document_id, {"status": "RECEIVED"}, headers))


# ─── Tier 2: Office + credential + preparer setup ──────────────────────────

def setup_office_with_preparer(bank_product_enabled=False, office_overrides=None,
                               credential_overrides=None, preparer_overrides=None):
    """Office + ACTIVE credential + one preparer.

    Returns (office, credential, preparer, prep_headers) where prep_headers is
    make_tax_preparer_headers(preparer.id) — already identity-threaded.
    """
    office = create_office(bank_product_enabled=bank_product_enabled, **(office_overrides or {}))
    cred = create_credential(office["id"], **(credential_overrides or {}))
    prep = create_preparer(office["id"], cred["id"], **(preparer_overrides or {}))
    prep_headers = make_tax_preparer_headers(prep["id"])
    return office, cred, prep, prep_headers


# ─── Tier 3: TaxReturn lifecycle shortcuts ─────────────────────────────────

def setup_return_in_docs_pending(bank_product_enabled=False, client_overrides=None,
                                 return_overrides=None, doc_required=True):
    """Walk a return to DOCS_PENDING with a preparer assigned and one document
    marked RECEIVED (so the IN_PREP preconditions can be satisfied next).

    Returns dict of (office, credential, preparer, prep_headers, client,
    return_, document).
    """
    office, cred, prep, prep_headers = setup_office_with_preparer(
        bank_product_enabled=bank_product_enabled)
    client = create_client(office["id"], **(client_overrides or {}))
    ret = create_return(office["id"], client["id"], headers=prep_headers,
                        **(return_overrides or {}))
    doc = add_document(ret["id"], prep_headers, is_required=doc_required)
    set_document_received(doc["id"], prep_headers)
    get_success_data(api_client.assign_return(ret["id"], {"preparer_id": prep["id"]}, prep_headers))
    get_success_data(api_client.transition_return(ret["id"], {"to": "DOCS_PENDING"}, prep_headers))
    return {
        "office": office, "credential": cred, "preparer": prep,
        "prep_headers": prep_headers, "client": client,
        "return": ret, "document": doc,
    }


def setup_return_in_prep(bank_product_enabled=False, client_overrides=None,
                         return_overrides=None):
    """Walk a return all the way to IN_PREP (prep fee computed). Returns the
    same dict shape as setup_return_in_docs_pending plus the IN_PREP return."""
    ctx = setup_return_in_docs_pending(
        bank_product_enabled=bank_product_enabled,
        client_overrides=client_overrides, return_overrides=return_overrides)
    ret = get_success_data(api_client.transition_return(
        ctx["return"]["id"], {"to": "IN_PREP"}, ctx["prep_headers"]))
    ctx["return"] = ret
    return ctx


def setup_return_prepared(bank_product_enabled=False, client_overrides=None,
                          return_overrides=None):
    """Walk a return to PREPARED. Returns the context dict with the PREPARED
    return."""
    ctx = setup_return_in_prep(
        bank_product_enabled=bank_product_enabled,
        client_overrides=client_overrides, return_overrides=return_overrides)
    ret = get_success_data(api_client.transition_return(
        ctx["return"]["id"], {"to": "PREPARED"}, ctx["prep_headers"]))
    ctx["return"] = ret
    return ctx


def setup_return_accepted(bank_product_enabled=False, client_overrides=None,
                          return_overrides=None):
    """Walk a return through e-file and an ACCEPTED ack to EFILED_ACCEPTED.

    Returns the context dict with the accepted return.
    """
    ctx = setup_return_prepared(
        bank_product_enabled=bank_product_enabled,
        client_overrides=client_overrides, return_overrides=return_overrides)
    rid = ctx["return"]["id"]
    ph = ctx["prep_headers"]
    get_success_data(api_client.efile_return(rid, ph))
    ret = get_success_data(api_client.efile_ack_return(rid, {"ack_status": "ACCEPTED"}, ph))
    ctx["return"] = ret
    return ctx


# ─── Tier 4: Bank-product compositions ─────────────────────────────────────

def create_refund_transfer(tax_return_id, **overrides):
    """Open a PENDING_FUNDING refund-transfer. Returns the RefundTransfer."""
    payload = create_refund_transfer_payload(tax_return_id, **overrides)
    return get_success_data(api_client.create_refund_transfer(payload, BO))


def create_refund_advance(tax_return_id, requested_cents, **overrides):
    """Open a REQUESTED refund-advance. Returns the RefundAdvance."""
    payload = create_refund_advance_payload(tax_return_id, requested_cents, **overrides)
    return get_success_data(api_client.create_refund_advance(payload, BO))


def create_approved_advance(tax_return_id, requested_cents):
    """Request + underwrite-APPROVE an advance. Returns the APPROVED advance."""
    adv = create_refund_advance(tax_return_id, requested_cents)
    return get_success_data(api_client.underwrite_refund_advance(
        adv["id"], {"decision": "APPROVE"}, BO))


def create_audit_protection(tax_return_id, **overrides):
    """Add an ACTIVE audit-protection add-on. Returns the AuditProtection."""
    payload = create_audit_protection_payload(tax_return_id, **overrides)
    return get_success_data(api_client.create_audit_protection(payload, BO))


def setup_accepted_return_with_pending_transfer(return_overrides=None,
                                                client_overrides=None):
    """Bank-product office; accepted return; one PENDING_FUNDING RefundTransfer.

    Returns (ctx, refund_transfer) where ctx is the setup_return_accepted dict.
    """
    ctx = setup_return_accepted(
        bank_product_enabled=True,
        client_overrides=client_overrides or {"risk_band": "LOW"},
        return_overrides=return_overrides or {"complexity_band": "SIMPLE",
                                              "expected_refund_cents": 500000})
    rt = create_refund_transfer(ctx["return"]["id"])
    return ctx, rt


def setup_accepted_return_with_disbursed_advance_and_pending_transfer(
        advance_cents=60000, return_overrides=None):
    """Bank office; accepted SIMPLE return; advance APPROVED then DISBURSED; one
    PENDING_FUNDING RefundTransfer. The advance is disbursed BEFORE the transfer
    is disbursed (so the transfer disburse can later cascade it to REPAID).

    Returns (ctx, refund_transfer, refund_advance).
    """
    ctx = setup_return_accepted(
        bank_product_enabled=True,
        client_overrides={"risk_band": "LOW"},
        return_overrides=return_overrides or {"complexity_band": "SIMPLE",
                                              "expected_refund_cents": 500000})
    rid = ctx["return"]["id"]
    adv = create_approved_advance(rid, advance_cents)
    rt = create_refund_transfer(rid)
    adv = get_success_data(api_client.disburse_refund_advance(adv["id"], BO))
    return ctx, rt, adv


# ─── Tier 5: Reject-loop accumulation ──────────────────────────────────────

def cycle_return_through_rejections(num_rejections):
    """Open a SIMPLE return, walk it to PREPARED, and run it through
    `num_rejections` full reject cycles (efile -> efile-ack REJECTED ->
    transition back to PREPARED). After N cycles the return is in PREPARED with
    reject_count == N, having looped back each time. To stop in EFILED_REJECTED
    with reject_count == N, the final loop-back transition is omitted.

    Returns the context dict (with the return left in EFILED_REJECTED and
    reject_count == num_rejections — the final correction loop-back is NOT done,
    so callers can test the next loop-back attempt).
    """
    ctx = setup_return_prepared(return_overrides={"complexity_band": "SIMPLE"})
    rid = ctx["return"]["id"]
    ph = ctx["prep_headers"]
    for i in range(num_rejections):
        get_success_data(api_client.efile_return(rid, ph))
        get_success_data(api_client.efile_ack_return(
            rid, {"ack_status": "REJECTED", "reject_code": f"R{i + 1}"}, ph))
        # Loop back to PREPARED for every cycle except the last, so the return is
        # left in EFILED_REJECTED with reject_count == num_rejections.
        if i < num_rejections - 1:
            get_success_data(api_client.transition_return(rid, {"to": "PREPARED"}, ph))
    ctx["return"] = get_success_data(api_client.get_return(rid, ph))
    return ctx
