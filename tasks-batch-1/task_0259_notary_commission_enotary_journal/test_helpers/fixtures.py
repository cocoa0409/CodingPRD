"""Composite setup helpers.

Tests reach interesting states through multi-step API call chains. These
helpers encapsulate those chains so tests focus on assertions. All helpers use
get_success_data() so a broken precondition surfaces as a clear "Setup step
failed" message rather than a confusing downstream assertion failure.

Identity threading: the Notary role is entity_backed — ownership-gated calls
(sessions, documents, journal entries) MUST use make_notary_headers(notary_id)
with the real notary id, never the shared constant.
"""
from prd_bench_local_runner.testing import get_success_data
from .api_client import api_client as _api
from .test_users import (
    TEST_USERS,
    make_notary_headers,
    make_commission_authority_headers,
    make_anonymous_headers,
)
from . import factories as f


CA_HEADERS = TEST_USERS["commission_authority_headers"]
ANON_HEADERS = TEST_USERS["anonymous_headers"]


# ---------------------------------------------------------------------------
# Clock helpers
# ---------------------------------------------------------------------------
def set_clock(iso: str):
    """Pin the system clock to a UTC instant."""
    return get_success_data(_api.set_clock({"to_iso8601": iso}, CA_HEADERS))


def advance_clock(iso: str):
    """Advance the clock and mark expiries."""
    return get_success_data(_api.advance_clock({"to_iso8601": iso}, CA_HEADERS))


# ---------------------------------------------------------------------------
# Tier 1 / 2: configuration setup
# ---------------------------------------------------------------------------
def create_jurisdiction(**overrides):
    """Create a jurisdiction. Returns the jurisdiction dict."""
    return get_success_data(_api.create_jurisdiction(f.create_jurisdiction_payload(**overrides), CA_HEADERS))


def add_fee_schedule(jurisdiction_id, act_type, max_act_fee_cents):
    """Add a per-act fee schedule row to a jurisdiction."""
    return get_success_data(
        _api.create_fee_schedule(
            jurisdiction_id, f.create_fee_schedule_payload(act_type, max_act_fee_cents), CA_HEADERS
        )
    )


def register_notary(jurisdiction_id, **overrides):
    """Self-register a notary applicant (status APPLIED). Returns the notary dict."""
    return get_success_data(
        _api.register_notary(f.register_notary_payload(jurisdiction_id, **overrides), ANON_HEADERS)
    )


def create_bond(notary_id, jurisdiction_id, **overrides):
    """Create a PENDING bond for a notary. Returns the bond dict."""
    return get_success_data(
        _api.create_bond(f.create_bond_payload(notary_id, jurisdiction_id, **overrides), CA_HEADERS)
    )


def activate_bond(bond_id):
    """Activate a PENDING bond. Returns the activated bond dict."""
    return get_success_data(_api.activate_bond(bond_id, CA_HEADERS))


# ---------------------------------------------------------------------------
# Tier 1: notary state progression
# ---------------------------------------------------------------------------
def setup_active_notary(
    jurisdiction_overrides=None,
    notary_overrides=None,
    bond_overrides=None,
    fee_schedules=None,
):
    """Build an ACTIVE notary with an ACTIVE bond, fully commissioned.

    Steps: jurisdiction -> optional fee schedules -> notary -> bond -> activate
    bond -> commission -> activate notary.

    Returns dict with keys: jurisdiction, notary, bond. The notary dict is the
    post-activation read so its status is ACTIVE.
    """
    jx = create_jurisdiction(**(jurisdiction_overrides or {}))
    for act_type, cap in (fee_schedules or {}).items():
        add_fee_schedule(jx["id"], act_type, cap)
    notary = register_notary(jx["id"], **(notary_overrides or {}))
    bond = create_bond(notary["id"], jx["id"], **(bond_overrides or {}))
    activate_bond(bond["id"])
    get_success_data(_api.commission_notary(notary["id"], CA_HEADERS))
    notary = get_success_data(_api.activate_notary(notary["id"], CA_HEADERS))
    bond = get_success_data(_api.get_bond(bond["id"], CA_HEADERS))
    return {"jurisdiction": jx, "notary": notary, "bond": bond}


def setup_commissioned_notary(jurisdiction_overrides=None, notary_overrides=None, bond_overrides=None):
    """Notary commissioned but NOT yet activated (status COMMISSIONED)."""
    jx = create_jurisdiction(**(jurisdiction_overrides or {}))
    notary = register_notary(jx["id"], **(notary_overrides or {}))
    bond = create_bond(notary["id"], jx["id"], **(bond_overrides or {}))
    activate_bond(bond["id"])
    notary = get_success_data(_api.commission_notary(notary["id"], CA_HEADERS))
    return {"jurisdiction": jx, "notary": notary, "bond": bond}


def setup_applied_notary_with_pending_bond(
    jurisdiction_overrides=None, notary_overrides=None, bond_overrides=None
):
    """APPLIED notary with a PENDING (never-activated) bond."""
    jx = create_jurisdiction(**(jurisdiction_overrides or {}))
    notary = register_notary(jx["id"], **(notary_overrides or {}))
    bond = create_bond(notary["id"], jx["id"], **(bond_overrides or {}))
    return {"jurisdiction": jx, "notary": notary, "bond": bond}


def setup_revoked_notary():
    """An ACTIVE notary driven to terminal REVOKED status."""
    ctx = setup_active_notary()
    notary = get_success_data(_api.revoke_notary(ctx["notary"]["id"], CA_HEADERS))
    ctx["notary"] = notary
    return ctx


# ---------------------------------------------------------------------------
# Tier 3: session lifecycle shortcuts
# ---------------------------------------------------------------------------
def create_session(notary_id, start, end, **overrides):
    """Create a RON session. Returns the session dict."""
    hdr = make_notary_headers(notary_id)
    return get_success_data(
        _api.create_session(f.create_session_payload(notary_id, start, end, **overrides), hdr)
    )


def add_signer(session_id, notary_id, full_name="Test Signer", kba_passed=True, credential_analysis_passed=True):
    hdr = make_notary_headers(notary_id)
    payload = f.create_signer_payload(
        full_name, kba_passed=kba_passed, credential_analysis_passed=credential_analysis_passed
    )
    return get_success_data(_api.add_signer(session_id, payload, hdr))


def add_document(session_id, notary_id, signer_id, act_type, requested_fee_cents):
    hdr = make_notary_headers(notary_id)
    payload = f.create_document_payload(signer_id, act_type, requested_fee_cents)
    return get_success_data(_api.add_document(session_id, payload, hdr))


def setup_session_to_active(
    notary_id,
    start="2026-06-10T15:00:00Z",
    end="2026-06-10T16:00:00Z",
    documents=None,
    session_overrides=None,
):
    """Build a session and drive it to ACTIVE with one fully-verified signer and
    the supplied documents attached (still PENDING).

    documents: list of (act_type, requested_fee_cents) tuples.

    Returns dict: session, signer, documents (list, created in order).
    """
    hdr = make_notary_headers(notary_id)
    sess = create_session(notary_id, start, end, **(session_overrides or {}))
    signer = add_signer(sess["id"], notary_id, full_name="Verified Signer",
                        kba_passed=True, credential_analysis_passed=True)
    docs = []
    for act_type, fee in (documents or []):
        docs.append(add_document(sess["id"], notary_id, signer["id"], act_type, fee))
    get_success_data(_api.begin_identity(sess["id"], hdr))
    get_success_data(_api.resolve_identity(sess["id"], {"outcome": "VERIFIED"}, hdr))
    sess = get_success_data(_api.start_session(sess["id"], hdr))
    return {"session": sess, "signer": signer, "documents": docs}


def setup_completed_session(notary_id, start, end, documents, session_overrides=None):
    """Drive a session to ACTIVE, notarize every supplied document, then COMPLETE.

    documents: list of (act_type, requested_fee_cents). All are notarized.

    Returns dict: session (post-complete read), signer, documents (post-notarize
    reads, in created order).
    """
    hdr = make_notary_headers(notary_id)
    built = setup_session_to_active(notary_id, start, end, documents, session_overrides)
    sess, signer, docs = built["session"], built["signer"], built["documents"]
    for doc in docs:
        get_success_data(_api.notarize_document(sess["id"], doc["id"], {}, hdr))
    sess = get_success_data(_api.complete_session(sess["id"], hdr))
    # Re-read documents AFTER completion: capped_fee_cents is stamped during the
    # completion transition (PRD §3.6), so a pre-complete read would still show 0.
    notarized = [get_success_data(_api.get_document(doc["id"], hdr)) for doc in docs]
    return {"session": sess, "signer": signer, "documents": notarized}


# ---------------------------------------------------------------------------
# Tier 3: complaint lifecycle shortcuts
# ---------------------------------------------------------------------------
def file_complaint(notary_id, category, claim_amount_cents=None, operator_id="auditor-default"):
    """File a complaint. operator_id is recorded as filed_by_user_id."""
    payload = f.create_complaint_payload(notary_id, category)
    if claim_amount_cents is not None:
        payload["claim_amount_cents"] = claim_amount_cents
    hdr = make_commission_authority_headers(operator_id)
    return get_success_data(_api.create_complaint(payload, hdr))


def file_and_open_complaint(notary_id, category, claim_amount_cents=None, operator_id="auditor-default"):
    """File a complaint and open it to UNDER_REVIEW."""
    hdr = make_commission_authority_headers(operator_id)
    cmp = file_complaint(notary_id, category, claim_amount_cents, operator_id)
    cmp = get_success_data(_api.open_review(cmp["id"], hdr))
    return cmp


def file_and_substantiate_complaint(notary_id, category, claim_amount_cents=None, operator_id="auditor-default"):
    """File -> open -> substantiate. Returns the SUBSTANTIATED complaint."""
    hdr = make_commission_authority_headers(operator_id)
    cmp = file_and_open_complaint(notary_id, category, claim_amount_cents, operator_id)
    cmp = get_success_data(_api.substantiate(cmp["id"], hdr))
    return cmp


def raise_risk_with_substantiations(notary_id, categories, operator_id="auditor-default"):
    """Substantiate one complaint per category in order, accumulating risk_score.

    categories: list of complaint category strings, applied sequentially.
    Returns the list of SUBSTANTIATED complaint dicts.
    """
    out = []
    for cat in categories:
        out.append(file_and_substantiate_complaint(notary_id, cat, operator_id=operator_id))
    return out
