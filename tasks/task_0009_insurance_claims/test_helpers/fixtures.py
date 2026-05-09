"""Composite setup helpers for multi-step test prerequisites.

Identity threading rules (PRD §2.1):
- Adjuster is entity_backed: every ownership-gated call (POST/PATCH on
  /claims/{id}/investigations*, POST /claims/{id}/submit-for-review) MUST
  use make_adjuster_headers(adjuster["id"]) so Investigation.adjuster_id
  equals X-User-ID.
- Customer is opaque BUT carries a stable identity comparison: ownership
  on a Claim is verified by Claim.claimant_id == X-User-ID, and a Customer
  may only act on a Policy whose insured_party_id == X-User-ID. We therefore
  thread a per-test customer id through Policy.insured_party_id at policy
  creation AND through subsequent customer calls via
  make_customer_headers(insured_party_id).
- Reviewer is opaque BUT must satisfy segregation of duties (the
  reviewer's X-User-ID must differ from Investigation.adjuster_id and,
  on appeal, from the primary reviewer's X-User-ID). Distinct labels are
  used to obtain distinct principals.
"""
import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional, List, Dict, Any, Tuple

from prd_bench_local_runner.testing import get_success_data, validate_paginated

from .api_client import api_client
from .factories import (
    create_policy_payload, create_adjuster_payload, create_repair_shop_payload,
    create_claim_payload, create_investigation_payload, patch_investigation_payload,
    create_estimate_line_item_payload, create_decision_payload,
    create_appeal_payload, create_appeal_decision_payload,
    create_subrogation_payload, create_fraud_flag_payload,
    advance_clock_payload, bank_event_payload,
)
from .test_users import (
    TEST_USERS, make_adjuster_headers, make_customer_headers,
    make_reviewer_headers, make_payout_officer_headers, make_admin_headers,
)
from .constants import DEFAULTS


# ─── Unique-id helpers ────────────────────────────────────────────
def _short_uid(n: int = 8) -> str:
    return uuid.uuid4().hex[:n].upper()


def _unique_policy_number() -> str:
    # Policy.policy_number constraint: uppercase alphanumeric, length 8-24.
    return f"POL{_short_uid(12)}"


def _unique_license() -> str:
    return f"LIC-{_short_uid(8)}"


def _unique_tax_id() -> str:
    return f"TAX{_short_uid(10)}"


def _unique_idempotency_key() -> str:
    return f"idem-{uuid.uuid4().hex}"


def _unique_customer_id() -> str:
    return f"customer-{uuid.uuid4().hex[:12]}"


# ─── Time helpers ─────────────────────────────────────────────────
def _iso(dt: datetime) -> str:
    """Format a datetime as ISO 8601 UTC with 3 fractional digits."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    s = dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"
    return s


def now_utc() -> datetime:
    return datetime.now(timezone.utc).replace(microsecond=0)


def days_ago(n: int) -> str:
    return _iso(now_utc() - timedelta(days=n))


def days_ahead(n: int) -> str:
    return _iso(now_utc() + timedelta(days=n))


# ─── Tier 1: primitive entity creators ────────────────────────────
def create_policy(
    insured_party_id: Optional[str] = None,
    coverage_type: str = "AUTO",
    coverage_limit_cents: int = DEFAULTS["COVERAGE_LIMIT_CENTS"],
    deductible_cents: int = DEFAULTS["DEDUCTIBLE_CENTS"],
    coinsurance_ratio: float = DEFAULTS["COINSURANCE_RATIO"],
    effective_from: Optional[str] = None,
    effective_to: Optional[str] = None,
    reporting_window_days: Optional[int] = DEFAULTS["REPORTING_WINDOW_DAYS"],
    policy_number: Optional[str] = None,
) -> dict:
    """Create an ACTIVE Policy. The caller-supplied insured_party_id (or a
    fresh uuid if omitted) must be reused as the X-User-ID for any Customer
    actions on this policy."""
    payload = create_policy_payload(
        policy_number=policy_number or _unique_policy_number(),
        insured_party_id=insured_party_id or _unique_customer_id(),
        coverage_type=coverage_type,
        coverage_limit_cents=coverage_limit_cents,
        deductible_cents=deductible_cents,
        coinsurance_ratio=coinsurance_ratio,
        effective_from=effective_from or days_ago(365),
        effective_to=effective_to or days_ahead(365),
        reporting_window_days=reporting_window_days,
    )
    return get_success_data(api_client.create_policy(payload, TEST_USERS["admin_headers"]))


def create_adjuster(
    full_name: str = "Test Adjuster",
    specialty: str = "AUTO",
    license_number: Optional[str] = None,
) -> dict:
    payload = create_adjuster_payload(
        full_name=full_name,
        license_number=license_number or _unique_license(),
        specialty=specialty,
    )
    return get_success_data(api_client.create_adjuster(payload, TEST_USERS["admin_headers"]))


def create_repair_shop(
    name: str = "Test Repair Shop",
    tax_id: Optional[str] = None,
) -> dict:
    payload = create_repair_shop_payload(
        name=name,
        tax_id=tax_id or _unique_tax_id(),
    )
    return get_success_data(api_client.create_repair_shop(payload, TEST_USERS["admin_headers"]))


def patch_policy_status(policy_id: str, status: str, version: Optional[int] = None) -> dict:
    body = {"status": status}
    if version is not None:
        body["version"] = version
    return get_success_data(api_client.patch_policy(
        policy_id, body, TEST_USERS["admin_headers"]
    ))


def get_policy(policy_id: str, headers: Optional[dict] = None) -> dict:
    if headers is None:
        headers = TEST_USERS["admin_headers"]
    return get_success_data(api_client.get_policy(policy_id, headers))


def get_repair_shop(shop_id: str, projection: Optional[str] = None) -> dict:
    params = {"projection": projection} if projection else None
    return get_success_data(api_client.get_repair_shop(
        shop_id, TEST_USERS["admin_headers"], params=params
    ))


def get_claim(claim_id: str, headers: Optional[dict] = None) -> dict:
    if headers is None:
        headers = TEST_USERS["admin_headers"]
    return get_success_data(api_client.get_claim(claim_id, headers))


def list_audit_log(claim_id: str, params: Optional[dict] = None) -> Tuple[list, dict]:
    res = api_client.get_audit_log(claim_id, TEST_USERS["admin_headers"], params=params)
    return validate_paginated(res)


# ─── Test-driving control ─────────────────────────────────────────
def advance_clock(to_iso8601: str) -> dict:
    return get_success_data(api_client.advance_clock(
        advance_clock_payload(to_iso8601), TEST_USERS["admin_token_headers"]
    ))


def bank_settle(payout_id: str) -> dict:
    return get_success_data(api_client.bank_settle(
        bank_event_payload(payout_id), TEST_USERS["admin_token_headers"]
    ))


def bank_fail(payout_id: str) -> dict:
    return get_success_data(api_client.bank_fail(
        bank_event_payload(payout_id), TEST_USERS["admin_token_headers"]
    ))


# ─── Tier 2: world primitives ─────────────────────────────────────
def setup_basic_world(
    coverage_type: str = "AUTO",
    coverage_limit_cents: int = DEFAULTS["COVERAGE_LIMIT_CENTS"],
    deductible_cents: int = DEFAULTS["DEDUCTIBLE_CENTS"],
    coinsurance_ratio: float = DEFAULTS["COINSURANCE_RATIO"],
    reporting_window_days: int = DEFAULTS["REPORTING_WINDOW_DAYS"],
    adjuster_specialty: Optional[str] = None,
) -> Dict[str, Any]:
    """Create a baseline operating world: one ACTIVE Policy with a fresh
    Customer (insured_party_id), one ACTIVE Adjuster whose specialty matches
    the policy's coverage type, and one ACTIVE RepairShop. Returns a dict
    with all entities plus the customer's opaque insured_party_id.

    The customer's id is threaded through Policy.insured_party_id so that
    customer-headed calls (intake, appeal, GET own claim) honour the
    X-User-ID == Policy.insured_party_id ownership rule.
    """
    insured_party_id = _unique_customer_id()
    policy = create_policy(
        insured_party_id=insured_party_id,
        coverage_type=coverage_type,
        coverage_limit_cents=coverage_limit_cents,
        deductible_cents=deductible_cents,
        coinsurance_ratio=coinsurance_ratio,
        reporting_window_days=reporting_window_days,
    )
    adjuster = create_adjuster(
        full_name="Primary Adjuster",
        specialty=adjuster_specialty or coverage_type,
    )
    shop = create_repair_shop(name="Primary Repair Shop")
    return {
        "insured_party_id": insured_party_id,
        "policy": policy,
        "adjuster": adjuster,
        "repair_shop": shop,
    }


# ─── Tier 3: state-progression helpers ────────────────────────────
def file_claim(
    world: Dict[str, Any],
    claimed_amount_cents: int = DEFAULTS["CLAIMED_AMOUNT_CENTS"],
    salvage_value_cents: int = 0,
    loss_date: Optional[str] = None,
    idempotency_key: Optional[str] = None,
    report_channel: str = "WEB",
    insured_party_id: Optional[str] = None,
    policy: Optional[dict] = None,
) -> dict:
    """File a claim as the world's customer. Returns the new Claim row.

    Threads insured_party_id through make_customer_headers so the
    server-side check `Claim.claimant_id == X-User-ID` and
    `Policy.insured_party_id == X-User-ID` hold (PRD §2.1, §3.1)."""
    p = policy or world["policy"]
    cid = insured_party_id or world.get("insured_party_id")
    assert cid is not None, "file_claim requires insured_party_id (or world['insured_party_id'])"
    payload = create_claim_payload(
        policy_id=p["id"],
        report_channel=report_channel,
        idempotency_key=idempotency_key or _unique_idempotency_key(),
        loss_date=loss_date or days_ago(1),
        claimed_amount_cents=claimed_amount_cents,
        salvage_value_cents=salvage_value_cents,
    )
    return get_success_data(api_client.create_claim(payload, make_customer_headers(cid)))


def open_investigation(
    world: Dict[str, Any],
    claim: dict,
    adjuster: Optional[dict] = None,
) -> dict:
    """Adjuster opens an Investigation; Claim transitions INTAKE ->
    UNDER_INVESTIGATION. Adjuster headers are threaded with adjuster["id"]
    so X-User-ID == Investigation.adjuster_id holds (PRD §2.1)."""
    adj = adjuster or world["adjuster"]
    payload = create_investigation_payload(adjuster_id=adj["id"])
    return get_success_data(api_client.create_investigation(
        claim["id"], payload, make_adjuster_headers(adj["id"])
    ))


def update_investigation(
    claim: dict,
    investigation: dict,
    adjuster: dict,
    photo_urls: Optional[List[str]] = None,
    document_authenticity_passed: Optional[bool] = None,
    assessed_loss_cents: Optional[int] = None,
) -> dict:
    """PATCH the investigation as the assigning adjuster."""
    payload = patch_investigation_payload(
        photo_urls=photo_urls,
        document_authenticity_passed=document_authenticity_passed,
        assessed_loss_cents=assessed_loss_cents,
    )
    return get_success_data(api_client.patch_investigation(
        claim["id"], investigation["id"], payload, make_adjuster_headers(adjuster["id"])
    ))


def add_estimate_line_item(
    claim: dict,
    investigation: dict,
    adjuster: dict,
    repair_shop: dict,
    description: str = "Repair line",
    amount_cents: int = DEFAULTS["ESTIMATE_AMOUNT_CENTS"],
) -> dict:
    payload = create_estimate_line_item_payload(
        repair_shop_id=repair_shop["id"],
        description=description,
        amount_cents=amount_cents,
    )
    return get_success_data(api_client.create_estimate_line_item(
        claim["id"], investigation["id"], payload, make_adjuster_headers(adjuster["id"])
    ))


def submit_for_review(claim: dict, adjuster: dict) -> dict:
    return get_success_data(api_client.submit_for_review(
        claim["id"], make_adjuster_headers(adjuster["id"])
    ))


def setup_claim_under_investigation(
    world: Optional[Dict[str, Any]] = None,
    claimed_amount_cents: int = DEFAULTS["CLAIMED_AMOUNT_CENTS"],
    assessed_loss_cents: int = DEFAULTS["ASSESSED_LOSS_CENTS"],
    salvage_value_cents: int = 0,
    photos: Optional[List[str]] = None,
    document_authenticity_passed: bool = True,
    add_estimate: bool = True,
    estimate_amount_cents: Optional[int] = None,
    coverage_type: str = "AUTO",
    coverage_limit_cents: int = DEFAULTS["COVERAGE_LIMIT_CENTS"],
    deductible_cents: int = DEFAULTS["DEDUCTIBLE_CENTS"],
    coinsurance_ratio: float = DEFAULTS["COINSURANCE_RATIO"],
    reporting_window_days: int = DEFAULTS["REPORTING_WINDOW_DAYS"],
) -> Dict[str, Any]:
    """Build a Claim that has reached UNDER_INVESTIGATION with a fully
    populated Investigation: photo, doc-auth=True, assessed_loss set, and
    (by default) one EstimateLineItem. Ready for submit-for-review by default.

    Returns: world | {"claim", "investigation", "estimate" (if added)}.
    """
    world = world or setup_basic_world(
        coverage_type=coverage_type,
        coverage_limit_cents=coverage_limit_cents,
        deductible_cents=deductible_cents,
        coinsurance_ratio=coinsurance_ratio,
        reporting_window_days=reporting_window_days,
    )
    claim = file_claim(
        world,
        claimed_amount_cents=claimed_amount_cents,
        salvage_value_cents=salvage_value_cents,
    )
    investigation = open_investigation(world, claim)
    investigation = update_investigation(
        claim, investigation, world["adjuster"],
        photo_urls=photos if photos is not None else ["https://example.com/photo1.jpg"],
        document_authenticity_passed=document_authenticity_passed,
        assessed_loss_cents=assessed_loss_cents,
    )
    estimate = None
    if add_estimate:
        estimate = add_estimate_line_item(
            claim, investigation, world["adjuster"], world["repair_shop"],
            amount_cents=estimate_amount_cents or assessed_loss_cents,
        )
    return {
        **world,
        "claim": get_claim(claim["id"]),
        "investigation": investigation,
        "estimate": estimate,
    }


def setup_claim_under_review(
    world: Optional[Dict[str, Any]] = None,
    claimed_amount_cents: int = DEFAULTS["CLAIMED_AMOUNT_CENTS"],
    assessed_loss_cents: int = DEFAULTS["ASSESSED_LOSS_CENTS"],
    salvage_value_cents: int = 0,
    coverage_type: str = "AUTO",
    coverage_limit_cents: int = DEFAULTS["COVERAGE_LIMIT_CENTS"],
    deductible_cents: int = DEFAULTS["DEDUCTIBLE_CENTS"],
    coinsurance_ratio: float = DEFAULTS["COINSURANCE_RATIO"],
) -> Dict[str, Any]:
    """Drive a claim from intake all the way to UNDER_REVIEW (calculations
    pinned). Returns world | {"claim", "investigation", "estimate"}."""
    state = setup_claim_under_investigation(
        world=world,
        claimed_amount_cents=claimed_amount_cents,
        assessed_loss_cents=assessed_loss_cents,
        salvage_value_cents=salvage_value_cents,
        coverage_type=coverage_type,
        coverage_limit_cents=coverage_limit_cents,
        deductible_cents=deductible_cents,
        coinsurance_ratio=coinsurance_ratio,
    )
    submit_for_review(state["claim"], state["adjuster"])
    state["claim"] = get_claim(state["claim"]["id"])
    return state


def record_primary_decision(
    state: Dict[str, Any],
    outcome: str = "APPROVE",
    rationale: Optional[str] = None,
    reviewer_label: str = "primary-reviewer",
) -> Dict[str, Any]:
    """Record a primary review decision under a fresh Reviewer principal
    distinct from the adjuster (segregation of duties)."""
    headers = make_reviewer_headers(reviewer_label)
    res = api_client.create_decision(
        state["claim"]["id"],
        create_decision_payload(outcome=outcome,
                                  rationale=rationale or f"{outcome.title()} reviewed."),
        headers,
    )
    decision = get_success_data(res)
    state["primary_decision"] = decision
    state["primary_reviewer_headers"] = headers
    state["claim"] = get_claim(state["claim"]["id"])
    return state


def setup_claim_approved(
    claimed_amount_cents: int = DEFAULTS["CLAIMED_AMOUNT_CENTS"],
    assessed_loss_cents: int = DEFAULTS["ASSESSED_LOSS_CENTS"],
    salvage_value_cents: int = 0,
    coinsurance_ratio: float = DEFAULTS["COINSURANCE_RATIO"],
    deductible_cents: int = DEFAULTS["DEDUCTIBLE_CENTS"],
    coverage_limit_cents: int = DEFAULTS["COVERAGE_LIMIT_CENTS"],
    reviewer_label: str = "primary-reviewer",
) -> Dict[str, Any]:
    """Build a claim through APPROVED via the manual primary path. The
    reviewer's X-User-ID is distinct from the adjuster id (segregation of
    duties is honoured)."""
    state = setup_claim_under_review(
        claimed_amount_cents=claimed_amount_cents,
        assessed_loss_cents=assessed_loss_cents,
        salvage_value_cents=salvage_value_cents,
        coinsurance_ratio=coinsurance_ratio,
        deductible_cents=deductible_cents,
        coverage_limit_cents=coverage_limit_cents,
    )
    state = record_primary_decision(state, outcome="APPROVE",
                                      reviewer_label=reviewer_label)
    return state


def setup_claim_denied(
    claimed_amount_cents: int = 5_000_000,  # MANUAL path (above $2,000)
    assessed_loss_cents: int = 5_000_000,
    salvage_value_cents: int = 0,
    coinsurance_ratio: float = DEFAULTS["COINSURANCE_RATIO"],
    deductible_cents: int = DEFAULTS["DEDUCTIBLE_CENTS"],
    coverage_limit_cents: int = 100_000_000,
    reviewer_label: str = "primary-reviewer",
    rationale: str = "Insufficient evidence.",
) -> Dict[str, Any]:
    """Build a claim through DENIED via the manual primary path."""
    state = setup_claim_under_review(
        claimed_amount_cents=claimed_amount_cents,
        assessed_loss_cents=assessed_loss_cents,
        salvage_value_cents=salvage_value_cents,
        coinsurance_ratio=coinsurance_ratio,
        deductible_cents=deductible_cents,
        coverage_limit_cents=coverage_limit_cents,
    )
    state = record_primary_decision(state, outcome="DENY",
                                      rationale=rationale,
                                      reviewer_label=reviewer_label)
    return state


def create_payout(state: Dict[str, Any]) -> Dict[str, Any]:
    """Create a Payout for an APPROVED claim under PayoutOfficer."""
    res = api_client.create_payout(
        state["claim"]["id"], TEST_USERS["payout_officer_headers"]
    )
    payout = get_success_data(res)
    state["payout"] = payout
    state["claim"] = get_claim(state["claim"]["id"])
    return state


def setup_claim_paid(
    claimed_amount_cents: int = DEFAULTS["CLAIMED_AMOUNT_CENTS"],
    assessed_loss_cents: int = DEFAULTS["ASSESSED_LOSS_CENTS"],
    salvage_value_cents: int = 50_000,
    coinsurance_ratio: float = DEFAULTS["COINSURANCE_RATIO"],
    deductible_cents: int = DEFAULTS["DEDUCTIBLE_CENTS"],
    coverage_limit_cents: int = DEFAULTS["COVERAGE_LIMIT_CENTS"],
) -> Dict[str, Any]:
    """Build a claim through PAID with a PENDING payout."""
    state = setup_claim_approved(
        claimed_amount_cents=claimed_amount_cents,
        assessed_loss_cents=assessed_loss_cents,
        salvage_value_cents=salvage_value_cents,
        coinsurance_ratio=coinsurance_ratio,
        deductible_cents=deductible_cents,
        coverage_limit_cents=coverage_limit_cents,
    )
    state = create_payout(state)
    return state


def setup_claim_settled(
    claimed_amount_cents: int = DEFAULTS["CLAIMED_AMOUNT_CENTS"],
    assessed_loss_cents: int = DEFAULTS["ASSESSED_LOSS_CENTS"],
    salvage_value_cents: int = 50_000,
    coinsurance_ratio: float = DEFAULTS["COINSURANCE_RATIO"],
    deductible_cents: int = DEFAULTS["DEDUCTIBLE_CENTS"],
) -> Dict[str, Any]:
    """Build a claim where the bank-settle event has fired: Payout SETTLED,
    Claim CLOSED."""
    state = setup_claim_paid(
        claimed_amount_cents=claimed_amount_cents,
        assessed_loss_cents=assessed_loss_cents,
        salvage_value_cents=salvage_value_cents,
        coinsurance_ratio=coinsurance_ratio,
        deductible_cents=deductible_cents,
    )
    bank_settle(state["payout"]["id"])
    # After settle, refetch
    state["payout"] = get_success_data(
        api_client.get_payout(state["claim"]["id"], TEST_USERS["admin_headers"])
    )
    state["claim"] = get_claim(state["claim"]["id"])
    return state


# ─── Tier 4: Appeal helpers ───────────────────────────────────────
def create_appeal(state: Dict[str, Any], grounds: str = "Reconsider please.") -> Dict[str, Any]:
    """File an appeal on a DENIED claim as the original claimant."""
    cid = state.get("insured_party_id")
    assert cid is not None, "create_appeal needs insured_party_id in state"
    res = api_client.create_appeal(
        state["claim"]["id"],
        create_appeal_payload(grounds=grounds),
        make_customer_headers(cid),
    )
    appeal = get_success_data(res)
    state["appeal"] = appeal
    state["claim"] = get_claim(state["claim"]["id"])
    return state


def record_appeal_decision(
    state: Dict[str, Any],
    outcome: str,  # "OVERTURN" or "UPHOLD"
    rationale: Optional[str] = None,
    reviewer_label: str = "secondary-reviewer",
) -> Dict[str, Any]:
    """Record a secondary review decision via a Reviewer whose X-User-ID
    differs from both the assigned adjuster id and the primary reviewer's
    id (segregation of duties at secondary review, PRD §2.7, §3.7)."""
    headers = make_reviewer_headers(reviewer_label)
    res = api_client.create_appeal_decision(
        state["claim"]["id"], state["appeal"]["id"],
        create_appeal_decision_payload(outcome=outcome,
                                          rationale=rationale or f"{outcome.title()} on appeal."),
        headers,
    )
    decision = get_success_data(res)
    state["secondary_decision"] = decision
    state["secondary_reviewer_headers"] = headers
    state["appeal"] = state.get("appeal") and {
        **state["appeal"],
    }
    state["claim"] = get_claim(state["claim"]["id"])
    return state


def setup_claim_appealed(
    claimed_amount_cents: int = 5_000_000,
    assessed_loss_cents: int = 5_000_000,
    salvage_value_cents: int = 0,
    coinsurance_ratio: float = DEFAULTS["COINSURANCE_RATIO"],
    deductible_cents: int = DEFAULTS["DEDUCTIBLE_CENTS"],
    coverage_limit_cents: int = 100_000_000,
) -> Dict[str, Any]:
    """Drive a claim through DENIED -> APPEALED via Customer appeal."""
    state = setup_claim_denied(
        claimed_amount_cents=claimed_amount_cents,
        assessed_loss_cents=assessed_loss_cents,
        salvage_value_cents=salvage_value_cents,
        coinsurance_ratio=coinsurance_ratio,
        deductible_cents=deductible_cents,
        coverage_limit_cents=coverage_limit_cents,
    )
    state = create_appeal(state)
    return state


# ─── Tier 5: FraudFlag / RepairShop helpers ───────────────────────
def add_fraud_flag(
    claim: dict,
    signal: str,
    severity: float = 1.0,
    repair_shop_id: Optional[str] = None,
) -> dict:
    """Add a fraud flag against a claim (admin operation)."""
    payload = create_fraud_flag_payload(
        signal=signal, severity=severity, repair_shop_id=repair_shop_id,
    )
    return get_success_data(api_client.create_fraud_flag(
        claim["id"], payload, TEST_USERS["admin_headers"]
    ))


def setup_three_collusion_flagged_claims(
    coverage_type: str = "AUTO",
) -> Dict[str, Any]:
    """Set up three independent UNDER_INVESTIGATION claims that each carry
    one REPAIR_SHOP_COLLUSION FraudFlag against the SAME shared RepairShop.
    Used to drive trust-decay tests (per_flag variant accumulates 3 * 0.20).

    Each claim sits on its own Policy/Customer/Claim row but shares the
    one shop in its EstimateLineItem. Returns the shop and a list of claim
    states.
    """
    shop = create_repair_shop(name="Shared Collusion Shop")
    states: List[Dict[str, Any]] = []
    for i in range(3):
        # Each claim has its own world (own customer, own policy, own
        # adjuster) — but they all share the single shared shop.
        world = setup_basic_world(coverage_type=coverage_type)
        # Override the world's shop with the shared one.
        world["repair_shop"] = shop
        state = setup_claim_under_investigation(world=world)
        # Attach the collusion fraud flag against the shared shop.
        add_fraud_flag(
            state["claim"], signal="REPAIR_SHOP_COLLUSION",
            severity=1.0, repair_shop_id=shop["id"],
        )
        states.append(state)
    return {"shop": shop, "states": states}


def submit_all_for_review(states: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Submit each claim for review in order."""
    out = []
    for s in states:
        submit_for_review(s["claim"], s["adjuster"])
        s["claim"] = get_claim(s["claim"]["id"])
        out.append(s)
    return out


# ─── Tier 6: Subrogation / payout-cycle helpers ───────────────────
def post_subrogation(state: Dict[str, Any], amount_cents: int) -> Dict[str, Any]:
    """Record a subrogation recovery. PRD §3.6 requires payout SETTLED.
    Bank-settle the payout if not already settled; the resulting claim state
    is CLOSED (per PRD's bank-settle cascade)."""
    payout = state.get("payout")
    if payout and payout.get("status") == "PENDING":
        bank_settle(payout["id"])
        state["payout"] = get_success_data(
            api_client.get_payout(state["claim"]["id"], TEST_USERS["admin_headers"])
        )
        state["claim"] = get_claim(state["claim"]["id"])
    res = api_client.create_subrogation(
        state["claim"]["id"],
        create_subrogation_payload(amount_cents=amount_cents),
        TEST_USERS["payout_officer_headers"],
    )
    state["claim"] = get_success_data(res)
    return state
