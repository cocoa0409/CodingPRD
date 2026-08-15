"""Composite setup helpers: multi-step state builders used across the suite.

Every helper builds its preconditions from scratch through PRD-declared
endpoints (the server is restarted before each test, so nothing carries
over). Setup calls use get_success_data so a broken precondition surfaces as
a clear "Setup step failed" error rather than a confusing assertion.
"""
from types import SimpleNamespace

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import BM_USER_ID, CO_USER_ID, FIN_USER_ID
from .factories import (
    create_brief_payload,
    create_brand_payload,
    create_creator_payload,
    create_deliverable_payload,
    create_pitch_payload,
    disclosure_pass_checklist,
    propose_terms_payload,
)
from .test_users import (
    TEST_USERS,
    make_brand_headers,
    make_creator_headers,
    make_officer_headers,
)

TM = TEST_USERS["talent_manager_headers"]
BM = TEST_USERS["brand_manager_headers"]  # X-User-ID == BM_USER_ID
CO = TEST_USERS["compliance_officer_headers"]  # X-User-ID == CO_USER_ID
FIN = TEST_USERS["finance_admin_headers"]  # X-User-ID == FIN_USER_ID
ADMIN = TEST_USERS["platform_admin_headers"]


# --- Logical clock ---------------------------------------------------------

def set_clock(to_iso8601: str) -> dict:
    """Advance the logical clock (PlatformAdmin only, PRD §2.5)."""
    return get_success_data(
        api_client.set_current_utc({"to_iso8601": to_iso8601}, ADMIN)
    )


# --- Roster / brand intake -------------------------------------------------

def make_creator(**overrides) -> dict:
    """Create a creator (lands in APPLIED). Returns the created Creator."""
    return get_success_data(
        api_client.create_creator(create_creator_payload(**overrides), TM)
    )


def make_active_creator(**overrides) -> dict:
    """Create a creator and walk APPLIED -> SCREENING -> ACTIVE.

    The ACTIVE transition runs the rate-card computation (PRD §3.1). Returns
    the creator re-read after activation so computed fields are populated.
    """
    creator = make_creator(**overrides)
    cid = creator["id"]
    get_success_data(
        api_client.transition_creator(cid, {"to_state": "SCREENING"}, TM)
    )
    get_success_data(
        api_client.transition_creator(cid, {"to_state": "ACTIVE"}, TM)
    )
    return get_success_data(api_client.get_creator(cid, TM))


def make_brand(**overrides) -> dict:
    """Create a brand (opens ACTIVE, credit_hold false). Returns the Brand."""
    return get_success_data(
        api_client.create_brand(create_brand_payload(**overrides), BM)
    )


# --- Briefs and pitches ----------------------------------------------------

def make_draft_brief(brand_id: str, **overrides) -> dict:
    """Create a brief (opens DRAFT). Returns the created Brief."""
    return get_success_data(
        api_client.create_brief(create_brief_payload(brand_id, **overrides), BM)
    )


def make_open_brief(brand_id: str, **overrides) -> SimpleNamespace:
    """Create a brief and publish it (DRAFT -> OPEN).

    Returns ns(brief=<published brief>, version=<current brief version>).
    """
    brief = make_draft_brief(brand_id, **overrides)
    published = get_success_data(api_client.publish_brief(brief["id"], BM))
    return SimpleNamespace(brief=published, version=published["version"])


def get_brief(brief_id: str) -> dict:
    return get_success_data(api_client.get_brief(brief_id, BM))


def make_pitch(
    brief_id: str,
    creator_id: str,
    proposed_fee_cents: int = 100000,
    concept_note: str = "concept",
    expected_brief_version: int = None,
) -> dict:
    """Create a pitch (SUBMITTED). When expected_brief_version is omitted the
    brief's current version is read first (OCC field, PRD §2.7)."""
    if expected_brief_version is None:
        expected_brief_version = get_brief(brief_id)["version"]
    return get_success_data(
        api_client.create_pitch(
            brief_id,
            create_pitch_payload(
                creator_id,
                expected_brief_version,
                proposed_fee_cents=proposed_fee_cents,
                concept_note=concept_note,
            ),
            TM,
        )
    )


def shortlist_pitch(pitch_id: str) -> dict:
    return get_success_data(
        api_client.pitch_brand_action(pitch_id, {"action": "SHORTLIST"}, BM)
    )


def accept_pitch(pitch_id: str) -> dict:
    """BrandManager ACCEPT; on success the response carries deal_id (PRD §3.3)."""
    return get_success_data(
        api_client.pitch_brand_action(pitch_id, {"action": "ACCEPT"}, BM)
    )


# --- Deal lifecycle --------------------------------------------------------

def make_accepted_deal(
    creator_overrides: dict = None,
    brief_overrides: dict = None,
    proposed_fee_cents: int = 100000,
) -> SimpleNamespace:
    """Full chain: ACTIVE creator + brand + OPEN brief + pitch + SHORTLIST +
    ACCEPT. Returns ns(creator, brand, brief, pitch, deal_id). The deal is
    DRAFT (no terms proposed yet)."""
    creator = make_active_creator(**(creator_overrides or {}))
    brand = make_brand(**({"industry": "TECH"} | {}))
    brief_ns = make_open_brief(brand["id"], **(brief_overrides or {}))
    pitch = make_pitch(
        brief_ns.brief["id"], creator["id"], proposed_fee_cents=proposed_fee_cents,
        expected_brief_version=brief_ns.version,
    )
    shortlist_pitch(pitch["id"])
    accepted = accept_pitch(pitch["id"])
    return SimpleNamespace(
        creator=creator,
        brand=brand,
        brief=brief_ns.brief,
        pitch=accepted,
        deal_id=accepted["deal_id"],
    )


def get_deal(deal_id: str) -> dict:
    return get_success_data(api_client.get_deal(deal_id, BM))


def propose_terms(deal_id: str, fee_base_cents: int) -> dict:
    """Propose terms (DRAFT -> PENDING_CREATOR); reads the deal's current
    version first for the OCC field (PRD §2.7)."""
    version = get_deal(deal_id)["version"]
    return get_success_data(
        api_client.propose_terms(
            deal_id, propose_terms_payload(fee_base_cents, version), BM
        )
    )


def creator_accept_terms(deal_id: str, creator_id: str) -> dict:
    return get_success_data(
        api_client.creator_respond(
            deal_id, {"action": "ACCEPT"}, make_creator_headers(creator_id)
        )
    )


def brand_accept_terms(deal_id: str, brand_id: str) -> dict:
    """Brand ACCEPT = activation (PENDING_BRAND -> ACTIVE, PRD §3.4)."""
    return get_success_data(
        api_client.brand_respond(
            deal_id, {"action": "ACCEPT"}, make_brand_headers(brand_id)
        )
    )


def make_pending_brand_deal(
    creator_overrides: dict = None,
    brief_overrides: dict = None,
    fee_base_cents: int = 100000,
) -> SimpleNamespace:
    """Accepted pitch + propose-terms + creator ACCEPT: deal PENDING_BRAND."""
    ns = make_accepted_deal(
        creator_overrides=creator_overrides,
        brief_overrides=brief_overrides,
        proposed_fee_cents=fee_base_cents,
    )
    propose_terms(ns.deal_id, fee_base_cents)
    creator_accept_terms(ns.deal_id, ns.creator["id"])
    ns.deal = get_deal(ns.deal_id)
    return ns


def make_active_deal(
    creator_overrides: dict = None,
    brief_overrides: dict = None,
    fee_base_cents: int = 100000,
) -> SimpleNamespace:
    """Full negotiation chain through brand ACCEPT: deal ACTIVE with
    fee_total_cents pinned (PRD §3.4). Returns ns(creator, brand, brief,
    pitch, deal_id, deal)."""
    ns = make_pending_brand_deal(
        creator_overrides=creator_overrides,
        brief_overrides=brief_overrides,
        fee_base_cents=fee_base_cents,
    )
    brand_accept_terms(ns.deal_id, ns.brand["id"])
    ns.deal = get_deal(ns.deal_id)
    return ns


# --- Deliverables ----------------------------------------------------------

def plan_deliverable(deal_id: str, **overrides) -> dict:
    """Plan a deliverable on an ACTIVE deal (opens PENDING_SUBMISSION)."""
    return get_success_data(
        api_client.create_deliverable(
            deal_id, create_deliverable_payload(**overrides), BM
        )
    )


def get_deliverable(deliverable_id: str) -> dict:
    return get_success_data(api_client.get_deliverable(deliverable_id, BM))


def submit_deliverable(deliverable_id: str, creator_id: str) -> dict:
    return get_success_data(
        api_client.submit_deliverable(
            deliverable_id, make_creator_headers(creator_id)
        )
    )


def approve_deliverable(deliverable_id: str, approver_user_id: str = BM_USER_ID) -> dict:
    """BrandManager APPROVE; stamps reviewed_by_user_id (PRD §3.5)."""
    return get_success_data(
        api_client.review_deliverable(
            deliverable_id,
            {"action": "APPROVE"},
            {"X-User-ID": approver_user_id,
             "X-User-Role": "BrandManager",
             "Content-Type": "application/json"},
        )
    )


def publish_deliverable(deliverable_id: str, creator_id: str, url: str) -> dict:
    return get_success_data(
        api_client.publish_deliverable(
            deliverable_id, {"content_url": url},
            make_creator_headers(creator_id),
        )
    )


def get_queued_check_id(deliverable_id: str) -> str:
    """The deliverable's QUEUED disclosure check id (status-filtered listing)."""
    data = get_success_data(
        api_client.list_deliverable_disclosure_checks(
            deliverable_id, CO, params={"status": "QUEUED"}
        )
    )
    assert isinstance(data, list) and len(data) == 1, (
        f"expected exactly one QUEUED disclosure check, got {data!r}"
    )
    return data[0]["id"]


def pass_disclosure_check(check_id: str, officer_user_id: str = CO_USER_ID) -> dict:
    """ComplianceOfficer PASS on a QUEUED check (bubbles deliverable, PRD §3.6)."""
    return get_success_data(
        api_client.review_disclosure_check(
            check_id,
            disclosure_pass_checklist(),
            make_officer_headers(officer_user_id),
        )
    )


def publish_flow(
    deal_id: str, deliverable_id: str, creator_id: str,
    url: str = "https://content.example/post",
    approver_user_id: str = BM_USER_ID,
) -> SimpleNamespace:
    """submit -> APPROVE -> publish. Returns ns(deliverable, check_id) with the
    deliverable PUBLISHED and its disclosure check QUEUED."""
    submit_deliverable(deliverable_id, creator_id)
    approve_deliverable(deliverable_id, approver_user_id)
    publish_deliverable(deliverable_id, creator_id, url)
    check_id = get_queued_check_id(deliverable_id)
    return SimpleNamespace(
        deliverable=get_deliverable(deliverable_id), check_id=check_id
    )


def verify_flow(
    deal_id: str, deliverable_id: str, creator_id: str,
    url: str = "https://content.example/post",
    approver_user_id: str = BM_USER_ID,
    officer_user_id: str = CO_USER_ID,
) -> SimpleNamespace:
    """Full content path: submit -> APPROVE -> publish -> disclosure PASS.
    Returns ns(deliverable, check_id) with the deliverable VERIFIED."""
    pub = publish_flow(
        deal_id, deliverable_id, creator_id, url=url,
        approver_user_id=approver_user_id,
    )
    pass_disclosure_check(pub.check_id, officer_user_id)
    return SimpleNamespace(
        deliverable=get_deliverable(deliverable_id), check_id=pub.check_id
    )


def make_deal_with_verified_deliverable(
    creator_overrides: dict = None,
    brief_overrides: dict = None,
    fee_base_cents: int = 100000,
    deliverable_overrides: dict = None,
) -> SimpleNamespace:
    """ACTIVE deal with one VERIFIED deliverable (deal becomes COMPLETED when
    it is the deal's only deliverable, PRD §3.4 bubble-up). Returns
    ns(creator, brand, brief, pitch, deal_id, deal, deliverable, check_id)."""
    ns = make_active_deal(
        creator_overrides=creator_overrides,
        brief_overrides=brief_overrides,
        fee_base_cents=fee_base_cents,
    )
    deliverable = plan_deliverable(ns.deal_id, **(deliverable_overrides or {}))
    verified = verify_flow(ns.deal_id, deliverable["id"], ns.creator["id"])
    ns.deliverable = verified.deliverable
    ns.check_id = verified.check_id
    ns.deal = get_deal(ns.deal_id)
    return ns


# --- Invoices and payouts --------------------------------------------------

def get_deal_payout(deal_id: str) -> dict:
    """The deal's payout (created at invoice issue, PRD §3.8)."""
    data = get_success_data(
        api_client.list_payouts(FIN, params={"deal_id": deal_id})
    )
    assert isinstance(data, list) and len(data) == 1, (
        f"expected exactly one payout for deal {deal_id}, got {data!r}"
    )
    return data[0]


def make_draft_invoice(deal_id: str) -> dict:
    """Create the deal's invoice (opens DRAFT with computed lines, PRD §3.8)."""
    return get_success_data(api_client.create_invoice(deal_id, FIN))


def make_issued_invoice(deal_id: str, issuer_user_id: str = FIN_USER_ID) -> dict:
    """Create + issue: invoice ISSUED, ACCRUED payout spawned (PRD §3.8)."""
    invoice = make_draft_invoice(deal_id)
    return get_success_data(
        api_client.issue_invoice(
            invoice["id"],
            {"X-User-ID": issuer_user_id,
             "X-User-Role": "FinanceAdmin",
             "Content-Type": "application/json"},
        )
    )


def pay_invoice_in_full(
    invoice_id: str, payer_user_id: str = FIN_USER_ID
) -> dict:
    """Record payment of exactly total_cents + late_fee_cents (PRD §3.8)."""
    invoice = get_success_data(api_client.get_invoice(invoice_id, FIN))
    amount = invoice["total_cents"] + invoice["late_fee_cents"]
    return get_success_data(
        api_client.record_payment(
            invoice_id,
            {"amount_cents": amount},
            {"X-User-ID": payer_user_id,
             "X-User-Role": "FinanceAdmin",
             "Content-Type": "application/json"},
        )
    )


def make_paid_invoice_scenario(
    creator_overrides: dict = None,
    brief_overrides: dict = None,
    issuer_user_id: str = FIN_USER_ID,
) -> SimpleNamespace:
    """ACTIVE/COMPLETED deal + VERIFIED deliverable + ISSUED invoice + recorded
    payment. Returns ns(..., invoice, payout) with payout PAYABLE."""
    ns = make_deal_with_verified_deliverable(
        creator_overrides=creator_overrides, brief_overrides=brief_overrides
    )
    invoice = make_issued_invoice(ns.deal_id, issuer_user_id=issuer_user_id)
    paid = pay_invoice_in_full(invoice["id"], payer_user_id=issuer_user_id)
    ns.invoice = paid
    ns.payout = get_deal_payout(ns.deal_id)
    return ns
