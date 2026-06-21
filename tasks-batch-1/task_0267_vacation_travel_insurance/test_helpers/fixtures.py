"""Composite setup helpers for multi-step test prerequisites.

Uses get_success_data() (lenient validator) internally so setup failures surface as
clear "Setup failed" errors rather than confusing assertion failures.

Identity threading: a Policy is owned by a Traveler (entity_backed). Every
ownership-gated call (create policy, add insured, record payment, file claim, add
expense/document, resubmit, cancel) uses make_traveler_headers(traveler_id) with the
real Traveler.id — never the shared TEST_USERS["traveler_headers"] constant.
"""
from prd_bench_local_runner.testing import get_success_data
from .api_client import api_client
from .factories import (
    create_plan_payload, create_traveler_payload, create_named_storm_payload,
    create_policy_payload, create_insured_traveler_payload, record_payment_payload,
    create_claim_payload, create_expense_payload, create_document_payload,
    create_payout_payload, set_clock_payload,
)
from .test_users import TEST_USERS, make_traveler_headers
from .constants import TEST_DEFAULTS

ADMIN = TEST_USERS["carrier_admin_headers"]
UNDERWRITER = TEST_USERS["underwriter_headers"]
ADJUSTER = TEST_USERS["claims_adjuster_headers"]


# ─── Primitive setup ──────────────────────────────────────────────────────

def set_clock(iso: str):
    """Set the server clock to the given ISO instant (CarrierAdmin)."""
    return get_success_data(api_client.set_clock(set_clock_payload(iso), ADMIN))


def create_plan(**overrides) -> dict:
    """Create an ACTIVE plan. Returns the plan dict."""
    return get_success_data(api_client.create_plan(create_plan_payload(**overrides), ADMIN))


def create_traveler(**overrides) -> dict:
    """Register a traveler. Returns the traveler dict."""
    return get_success_data(api_client.create_traveler(create_traveler_payload(**overrides), ADMIN))


def create_named_storm(**overrides) -> dict:
    """Declare a named storm. Returns the storm dict."""
    return get_success_data(api_client.create_named_storm(create_named_storm_payload(**overrides), ADMIN))


def create_quoted_policy(plan_id: str, traveler_id: str, **policy_overrides) -> dict:
    """Create a QUOTED policy owned by traveler_id. Returns the policy dict."""
    headers = make_traveler_headers(traveler_id)
    return get_success_data(api_client.create_policy(
        create_policy_payload(plan_id, traveler_id, **policy_overrides), headers))


def add_insured(policy_id: str, traveler_id: str, owner_traveler_id: str = None, **overrides) -> dict:
    """Add an insured traveler to a QUOTED policy. owner_traveler_id is the policy owner
    (defaults to traveler_id when the insured is the owner). Returns the insured dict."""
    owner = owner_traveler_id or traveler_id
    headers = make_traveler_headers(owner)
    return get_success_data(api_client.add_insured_traveler(
        policy_id, create_insured_traveler_payload(traveler_id, **overrides), headers))


def record_payment(policy_id: str, owner_traveler_id: str, expected_version: int = None) -> dict:
    """Record premium payment. If expected_version is None, reads the live policy version first.
    Returns the updated policy dict."""
    if expected_version is None:
        live = get_success_data(api_client.get_policy(policy_id, ADMIN))
        expected_version = live["version"]
    headers = make_traveler_headers(owner_traveler_id)
    return get_success_data(api_client.record_payment(
        policy_id, record_payment_payload(expected_version), headers))


def issue_policy(policy_id: str) -> dict:
    """Issue (activate) a paid policy (Underwriter). Returns the updated policy dict."""
    return get_success_data(api_client.issue_policy(policy_id, UNDERWRITER))


# ─── Tier: Active policy in one call ───────────────────────────────────────

def setup_active_policy(plan_overrides=None, policy_overrides=None,
                        insured_overrides=None, clock="2026-06-01T00:00:00Z"):
    """Full path to an ACTIVE policy: clock -> plan -> traveler -> quoted policy ->
    one COVERED insured (covering full trip cost) -> record payment -> issue.

    Returns dict with keys: plan, traveler, policy (the ACTIVE policy after issue),
    insured, traveler_id, owner_headers.
    """
    plan_overrides = plan_overrides or {}
    policy_overrides = policy_overrides or {}
    insured_overrides = insured_overrides or {}

    if clock is not None:
        set_clock(clock)
    plan = create_plan(**plan_overrides)
    traveler = create_traveler()
    policy = create_quoted_policy(plan["id"], traveler["id"], **policy_overrides)

    # Default the insured to cover the full trip cost so issuance passes the
    # trip-cost-match precondition.
    ins_kwargs = dict(insured_overrides)
    ins_kwargs.setdefault("covered_trip_cost_cents", policy["trip_cost_cents"])
    insured = add_insured(policy["id"], traveler["id"], **ins_kwargs)

    record_payment(policy["id"], traveler["id"])
    active = issue_policy(policy["id"])
    return {
        "plan": plan,
        "traveler": traveler,
        "traveler_id": traveler["id"],
        "policy": active,
        "insured": insured,
        "owner_headers": make_traveler_headers(traveler["id"]),
    }


def setup_paid_quoted_policy(plan_overrides=None, policy_overrides=None,
                             insured_overrides=None, clock=None):
    """Path to a QUOTED policy whose premium is PAID but which is NOT yet issued.
    Returns the same dict shape as setup_active_policy, with policy in QUOTED/PAID."""
    plan_overrides = plan_overrides or {}
    policy_overrides = policy_overrides or {}
    insured_overrides = insured_overrides or {}

    if clock is not None:
        set_clock(clock)
    plan = create_plan(**plan_overrides)
    traveler = create_traveler()
    policy = create_quoted_policy(plan["id"], traveler["id"], **policy_overrides)
    ins_kwargs = dict(insured_overrides)
    ins_kwargs.setdefault("covered_trip_cost_cents", policy["trip_cost_cents"])
    insured = add_insured(policy["id"], traveler["id"], **ins_kwargs)
    paid = record_payment(policy["id"], traveler["id"])
    return {
        "plan": plan,
        "traveler": traveler,
        "traveler_id": traveler["id"],
        "policy": paid,
        "insured": insured,
        "owner_headers": make_traveler_headers(traveler["id"]),
    }


# ─── Tier: Claims ──────────────────────────────────────────────────────────

def file_claim(policy_id: str, insured_id: str, owner_traveler_id: str,
               peril: str, incident_at: str, **overrides) -> dict:
    """File a claim against an ACTIVE policy (owning Traveler). Returns the claim dict."""
    headers = make_traveler_headers(owner_traveler_id)
    return get_success_data(api_client.create_claim(
        create_claim_payload(policy_id, insured_id, peril, incident_at, **overrides), headers))


def add_expense(claim_id: str, owner_traveler_id: str, category: str,
                description: str, documented_amount_cents: int, **overrides) -> dict:
    headers = make_traveler_headers(owner_traveler_id)
    return get_success_data(api_client.add_expense(
        claim_id, create_expense_payload(category, description, documented_amount_cents, **overrides),
        headers))


def add_document(claim_id: str, owner_traveler_id: str,
                 doc_type: str = "RECEIPT", file_ref: str = "ref-1") -> dict:
    headers = make_traveler_headers(owner_traveler_id)
    return get_success_data(api_client.add_document(
        claim_id, create_document_payload(doc_type, file_ref), headers))


def start_review(claim_id: str) -> dict:
    """Open review (ClaimsAdjuster). Returns the claim dict."""
    return get_success_data(api_client.start_review(claim_id, ADJUSTER))


def setup_claim_under_review(active=None, peril="MEDICAL", incident_at="2026-06-05T00:00:00Z",
                             claim_overrides=None, expenses=None, doc_type="MEDICAL_REPORT",
                             with_document=True, plan_overrides=None, policy_overrides=None,
                             insured_overrides=None, clock="2026-06-01T00:00:00Z"):
    """Build an ACTIVE policy, file a claim of the given peril, optionally add expense
    lines and a document, then move the claim to UNDER_REVIEW.

    `expenses` is a list of dicts each forwarded to add_expense (category/description/
    documented_amount_cents + optional fields).

    Returns dict: plan, traveler, traveler_id, policy, insured, claim (UNDER_REVIEW),
    owner_headers.
    """
    claim_overrides = claim_overrides or {}
    expenses = expenses or []

    if active is None:
        active = setup_active_policy(plan_overrides=plan_overrides,
                                     policy_overrides=policy_overrides,
                                     insured_overrides=insured_overrides, clock=clock)
    policy = active["policy"]
    traveler_id = active["traveler_id"]
    insured = active["insured"]

    claim = file_claim(policy["id"], insured["id"], traveler_id, peril, incident_at,
                       **claim_overrides)
    for exp in expenses:
        add_expense(claim["id"], traveler_id, **exp)
    if with_document:
        add_document(claim["id"], traveler_id, doc_type=doc_type, file_ref="doc-1")
    reviewed = start_review(claim["id"])
    return {
        **active,
        "claim": reviewed,
    }


# ─── Tier: Approved claim + payout ─────────────────────────────────────────

def approve_claim(claim_id: str) -> dict:
    """Approve a claim under review (ClaimsAdjuster). Returns the claim dict."""
    return get_success_data(api_client.approve_claim(claim_id, ADJUSTER))


def create_payout(claim_id: str) -> dict:
    """Create a PENDING payout for an APPROVED claim (ClaimsAdjuster). Returns the payout dict."""
    return get_success_data(api_client.create_payout(create_payout_payload(claim_id), ADJUSTER))


def disburse_payout(payout_id: str) -> dict:
    """Disburse a pending payout (ClaimsAdjuster). Returns the payout dict."""
    return get_success_data(api_client.disburse_payout(payout_id, ADJUSTER))


def setup_approved_cancellation_claim_with_pending_payout(
        plan_overrides=None, trip_cost_cents=300000, prepaid_cents=300000,
        clock="2026-06-01T00:00:00Z", incident_at="2026-06-05T00:00:00Z"):
    """ACTIVE policy + a CANCELLATION claim (COVERED_REASON) approved for the full
    prepaid amount, with a PENDING payout created. Returns dict with keys from
    setup_active_policy plus claim (APPROVED) and payout (PENDING).
    """
    active = setup_active_policy(
        plan_overrides=plan_overrides,
        policy_overrides={"trip_cost_cents": trip_cost_cents},
        insured_overrides={"covered_trip_cost_cents": trip_cost_cents},
        clock=clock,
    )
    bundle = setup_claim_under_review(
        active=active, peril="CANCELLATION",
        incident_at=incident_at,
        claim_overrides={"cancellation_reason": "COVERED_REASON"},
        expenses=[{"category": "PREPAID_TRIP", "description": "all",
                   "documented_amount_cents": prepaid_cents,
                   "prepaid_nonrefundable_cents": prepaid_cents,
                   "supplier_refund_received_cents": 0}],
        doc_type="RECEIPT",
    )
    claim = approve_claim(bundle["claim"]["id"])
    payout = create_payout(claim["id"])
    return {**bundle, "claim": claim, "payout": payout}


# ─── Convenience getters ───────────────────────────────────────────────────

def get_policy(policy_id: str) -> dict:
    return get_success_data(api_client.get_policy(policy_id, ADMIN))


def get_claim(claim_id: str) -> dict:
    return get_success_data(api_client.get_claim(claim_id, ADMIN))


def get_payout(payout_id: str) -> dict:
    return get_success_data(api_client.get_payout(payout_id, ADMIN))


def list_refunds_for_policy(policy_id: str) -> list:
    data, _meta = _paginated(api_client.list_refunds(ADMIN, params={"policy_id": policy_id}))
    return data


def _paginated(response):
    """Local lenient unpack of a paginated list response for fixture use."""
    body = response.json()
    return body.get("data", []), body.get("meta", {})
