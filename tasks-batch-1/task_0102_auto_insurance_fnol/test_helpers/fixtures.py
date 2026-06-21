"""Composite setup helpers for multi-step test prerequisites.

Most interesting claims need the system walked 5-15 API calls deep (policy ->
coverage -> adjuster -> claim -> verify -> assign -> estimate -> submit ->
[evaluate] -> decide -> settle, then subrogation/rental/ledger work). These
helpers encapsulate those chains so tests focus on assertions.

Uses get_success_data() (lenient 2xx validator) so setup failures produce clear
"Setup step failed" errors rather than confusing assertion failures.

Identity threading: the ClaimsAdjuster / TotalLossAdjuster roles are
entity_backed on Adjuster, so any authorship/ownership-gated call uses
make_claims_adjuster_headers(adjuster_id) / make_total_loss_adjuster_headers(
adjuster_id) with the real Adjuster.id — never the shared fallback constant.
"""
import uuid

from prd_bench_local_runner.testing import get_success_data
from .api_client import api_client
from .factories import (
    create_policy_payload,
    create_coverage_payload,
    create_rental_coverage_payload,
    create_adjuster_payload,
    create_claim_payload,
    create_claim_party_payload,
    create_repair_estimate_payload,
    create_total_loss_evaluation_payload,
    create_rental_reimbursement_payload,
    create_subrogation_case_payload,
    estimate_lines,
)
from .test_users import (
    TEST_USERS,
    make_claims_adjuster_headers,
    make_total_loss_adjuster_headers,
)

SUP = TEST_USERS["supervisor_headers"]
SUB = TEST_USERS["subrogation_headers"]


def _uniq(prefix: str) -> str:
    """A collision-free suffix so unique fields (policy_number) never clash within a test."""
    return f"{prefix}-{uuid.uuid4().hex[:10]}"


# ─── Tier 0: primitive creators ───────────────────────

def create_policy(comparative_fault_rule="PURE", policyholder_name=None, **overrides):
    """Create an ACTIVE policy. Returns the policy dict."""
    if policyholder_name is None:
        policyholder_name = _uniq("Holder")
    payload = create_policy_payload(
        policyholder_name=policyholder_name,
        policy_number=_uniq("POL"),
        comparative_fault_rule=comparative_fault_rule,
        **overrides,
    )
    return get_success_data(api_client.create_policy(payload, SUP))


def add_collision_coverage(policy_id, limit_cents=1_000_000, deductible_cents=50_000):
    payload = create_coverage_payload(
        coverage_type="COLLISION", limit_cents=limit_cents, deductible_cents=deductible_cents
    )
    return get_success_data(api_client.create_coverage(policy_id, payload, SUP))


def add_rental_coverage(policy_id, limit_cents=100_000, rental_daily_cap_cents=5_000, rental_max_days=10):
    payload = create_rental_coverage_payload(
        limit_cents=limit_cents,
        rental_daily_cap_cents=rental_daily_cap_cents,
        rental_max_days=rental_max_days,
    )
    return get_success_data(api_client.create_coverage(policy_id, payload, SUP))


def create_adjuster(license_tier="STANDARD", full_name=None):
    payload = create_adjuster_payload(
        full_name=full_name or _uniq("Adj"), license_tier=license_tier
    )
    return get_success_data(api_client.create_adjuster(payload, SUP))


def file_claim(policy_id, adjuster_id, **overrides):
    """File an FNOL claim as the given ClaimsAdjuster. Returns the claim dict."""
    payload = create_claim_payload(policy_id, **overrides)
    headers = make_claims_adjuster_headers(adjuster_id)
    return get_success_data(api_client.create_claim(payload, headers))


# ─── Tier 1: state progression on the Claim ───────────

def verify_claim(claim_id, adjuster_id):
    """Run verify-coverage as the ClaimsAdjuster. Returns the updated claim dict."""
    headers = make_claims_adjuster_headers(adjuster_id)
    return get_success_data(api_client.verify_coverage(claim_id, headers))


def assign_claim(claim_id, adjuster_id, expected_claim_version):
    """Assign the adjuster (ClaimsSupervisor-exclusive, OCC-guarded). Returns updated claim."""
    payload = {"adjuster_id": adjuster_id, "expected_claim_version": expected_claim_version}
    return get_success_data(api_client.assign_adjuster(claim_id, payload, SUP))


def submit_estimate(claim_id, adjuster_id, repair_total_cents=600_000, lines=None):
    """Create + submit a repair estimate authored by the assigned adjuster.

    Returns the SUBMITTED estimate dict.
    """
    headers = make_claims_adjuster_headers(adjuster_id)
    if lines is None:
        lines = estimate_lines(repair_total_cents)
    est = get_success_data(api_client.create_repair_estimate(
        create_repair_estimate_payload(claim_id, lines=lines), headers))
    return get_success_data(api_client.submit_repair_estimate(est["id"], headers))


def author_total_loss_evaluation(claim_id, senior_adjuster_id, salvage_retained_by_insurer=None):
    """Author a total-loss evaluation as the given SENIOR TotalLossAdjuster."""
    payload = create_total_loss_evaluation_payload(claim_id)
    if salvage_retained_by_insurer is not None:
        payload["salvage_retained_by_insurer"] = salvage_retained_by_insurer
    headers = make_total_loss_adjuster_headers(senior_adjuster_id)
    return get_success_data(api_client.create_total_loss_evaluation(payload, headers))


# ─── Tier 2: claim hierarchy shortcuts ────────────────

def setup_claim_under_review(comparative_fault_rule="PURE", vehicle_acv_cents=800_000,
                             insured_fault_pct=0, deductible_cents=50_000,
                             limit_cents=1_000_000, salvage_value_cents=0,
                             with_rental=False):
    """Active policy + COLLISION coverage + adjuster + claim driven to UNDER_REVIEW.

    Returns dict with keys: policy, adjuster, claim, version (claim version after assign).
    """
    policy = create_policy(comparative_fault_rule=comparative_fault_rule)
    add_collision_coverage(policy["id"], limit_cents=limit_cents, deductible_cents=deductible_cents)
    if with_rental:
        add_rental_coverage(policy["id"])
    adjuster = create_adjuster(license_tier="STANDARD")
    claim = file_claim(
        policy["id"], adjuster["id"],
        loss_type="COLLISION", vehicle_acv_cents=vehicle_acv_cents,
        insured_fault_pct=insured_fault_pct, salvage_value_cents=salvage_value_cents,
    )
    verified = verify_claim(claim["id"], adjuster["id"])
    assigned = assign_claim(claim["id"], adjuster["id"], verified["version"])
    return {
        "policy": policy,
        "adjuster": adjuster,
        "claim": assigned,
        "version": assigned["version"],
    }


def setup_claim_with_submitted_estimate(repair_total_cents=600_000, **kwargs):
    """UNDER_REVIEW claim with one SUBMITTED repair estimate.

    Returns dict adding 'estimate' to setup_claim_under_review's keys.
    """
    ctx = setup_claim_under_review(**kwargs)
    est = submit_estimate(ctx["claim"]["id"], ctx["adjuster"]["id"],
                          repair_total_cents=repair_total_cents)
    ctx["estimate"] = est
    return ctx


def setup_repair_approved_claim(repair_total_cents=600_000, **kwargs):
    """Claim decided REPAIR (status REPAIR_APPROVED, settlement_cents computed).

    Returns dict adding 'claim' (post-decision) and keeping 'estimate'.
    """
    ctx = setup_claim_with_submitted_estimate(repair_total_cents=repair_total_cents, **kwargs)
    headers = make_claims_adjuster_headers(ctx["adjuster"]["id"])
    decided = get_success_data(api_client.decide_disposition(
        ctx["claim"]["id"],
        {"decision": "REPAIR", "expected_claim_version": ctx["version"]},
        headers,
    ))
    ctx["claim"] = decided
    ctx["version"] = decided["version"]
    return ctx


def setup_settled_repair_claim(repair_total_cents=600_000, insured_fault_pct=0,
                               comparative_fault_rule="PURE", with_third_party=False,
                               third_party_fault_pct=100, vehicle_acv_cents=800_000,
                               **kwargs):
    """A REPAIR claim driven all the way to SETTLED (one APPROVED SETTLEMENT disbursement).

    If with_third_party, adds a THIRD_PARTY ClaimParty before verify and returns
    its id under 'third_party'. Returns dict with policy/adjuster/claim/version/estimate
    and optionally 'third_party'.
    """
    policy = create_policy(comparative_fault_rule=comparative_fault_rule)
    add_collision_coverage(policy["id"])
    adjuster = create_adjuster(license_tier="STANDARD")
    claim = file_claim(
        policy["id"], adjuster["id"],
        loss_type="COLLISION", vehicle_acv_cents=vehicle_acv_cents,
        insured_fault_pct=insured_fault_pct,
    )
    third_party = None
    if with_third_party:
        adj_headers = make_claims_adjuster_headers(adjuster["id"])
        third_party = get_success_data(api_client.create_claim_party(
            create_claim_party_payload(
                claim["id"], party_role="THIRD_PARTY", display_name="Other Driver",
                fault_pct=third_party_fault_pct, at_fault_carrier_name="Rival Mutual",
            ),
            adj_headers,
        ))
    verified = verify_claim(claim["id"], adjuster["id"])
    assigned = assign_claim(claim["id"], adjuster["id"], verified["version"])
    est = submit_estimate(claim["id"], adjuster["id"], repair_total_cents=repair_total_cents)
    adj_headers = make_claims_adjuster_headers(adjuster["id"])
    decided = get_success_data(api_client.decide_disposition(
        claim["id"],
        {"decision": "REPAIR", "expected_claim_version": assigned["version"]},
        adj_headers,
    ))
    settled = get_success_data(api_client.settle_claim(
        claim["id"], {"expected_claim_version": decided["version"]}, SUP))
    ctx = {
        "policy": policy,
        "adjuster": adjuster,
        "claim": settled,
        "version": settled["version"],
        "estimate": est,
    }
    if third_party is not None:
        ctx["third_party"] = third_party
    return ctx


# ─── Tier 3: total-loss lifecycle ─────────────────────

def setup_total_loss_ready(vehicle_acv_cents=800_000, repair_total_cents=600_000,
                           salvage_value_cents=120_000, deductible_cents=50_000,
                           limit_cents=1_000_000, salvage_retained_by_insurer=True,
                           comparative_fault_rule="PURE", with_rental=False,
                           rental_max_days=10):
    """UNDER_REVIEW claim with a SUBMITTED estimate and a SENIOR total-loss evaluation
    (is_total_loss expected true for the default 0.75-ratio inputs), ready for the
    TOTAL_LOSS disposition decision by a SEPARATE senior adjuster.

    The repair estimate is authored by adj1 (STANDARD, the assigned adjuster); the
    total-loss evaluation is authored by adjS (SENIOR), so segregation of duties holds.

    Returns dict: policy, adj1, adjS, claim, version, estimate, evaluation.
    """
    policy = create_policy(comparative_fault_rule=comparative_fault_rule)
    add_collision_coverage(policy["id"], limit_cents=limit_cents, deductible_cents=deductible_cents)
    if with_rental:
        add_rental_coverage(policy["id"], rental_max_days=rental_max_days)
    adj1 = create_adjuster(license_tier="STANDARD")
    adjS = create_adjuster(license_tier="SENIOR")
    claim = file_claim(
        policy["id"], adj1["id"],
        loss_type="COLLISION", vehicle_acv_cents=vehicle_acv_cents,
        salvage_value_cents=salvage_value_cents,
    )
    verified = verify_claim(claim["id"], adj1["id"])
    assigned = assign_claim(claim["id"], adj1["id"], verified["version"])
    est = submit_estimate(claim["id"], adj1["id"], repair_total_cents=repair_total_cents)
    evaluation = author_total_loss_evaluation(
        claim["id"], adjS["id"], salvage_retained_by_insurer=salvage_retained_by_insurer)
    return {
        "policy": policy,
        "adj1": adj1,
        "adjS": adjS,
        "claim": assigned,
        "version": assigned["version"],
        "estimate": est,
        "evaluation": evaluation,
    }


def decide_total_loss(claim_id, senior_adjuster_id, expected_claim_version):
    """Decide TOTAL_LOSS as the SENIOR TotalLossAdjuster. Returns the updated claim."""
    headers = make_total_loss_adjuster_headers(senior_adjuster_id)
    return get_success_data(api_client.decide_disposition(
        claim_id,
        {"decision": "TOTAL_LOSS", "expected_claim_version": expected_claim_version},
        headers,
    ))


# ─── Tier 4: subrogation lifecycle ────────────────────

def open_subrogation_case(claim_id, target_party_id, demand_cents=400_000):
    """Open a subrogation case (computes recoverable_cents). Returns the case dict."""
    payload = create_subrogation_case_payload(claim_id, target_party_id, demand_cents=demand_cents)
    return get_success_data(api_client.create_subrogation_case(payload, SUB))


def setup_subrogation_case(demand_cents=400_000, insured_fault_pct=0,
                           comparative_fault_rule="PURE", third_party_fault_pct=100,
                           vehicle_acv_cents=2_000_000):
    """A SETTLED claim with a THIRD_PARTY and a freshly OPENed subrogation case.

    Returns dict: policy, adjuster, claim, third_party, subrogation_case.
    """
    ctx = setup_settled_repair_claim(
        repair_total_cents=600_000,
        insured_fault_pct=insured_fault_pct,
        comparative_fault_rule=comparative_fault_rule,
        with_third_party=True,
        third_party_fault_pct=third_party_fault_pct,
        vehicle_acv_cents=vehicle_acv_cents,
    )
    case = open_subrogation_case(
        ctx["claim"]["id"], ctx["third_party"]["id"], demand_cents=demand_cents)
    ctx["subrogation_case"] = case
    return ctx


def setup_subrogation_negotiating(demand_cents=400_000, **kwargs):
    """A subrogation case driven OPEN -> DEMAND_SENT -> NEGOTIATING.

    Returns the same dict as setup_subrogation_case with the case in NEGOTIATING.
    """
    ctx = setup_subrogation_case(demand_cents=demand_cents, **kwargs)
    case_id = ctx["subrogation_case"]["id"]
    get_success_data(api_client.send_demand(case_id, {}, SUB))
    ctx["subrogation_case"] = get_success_data(api_client.begin_negotiation(case_id, SUB))
    return ctx


def setup_subrogation_demand_sent(demand_cents=400_000, **kwargs):
    """A subrogation case driven OPEN -> DEMAND_SENT (demand sent once)."""
    ctx = setup_subrogation_case(demand_cents=demand_cents, **kwargs)
    case_id = ctx["subrogation_case"]["id"]
    ctx["subrogation_case"] = get_success_data(api_client.send_demand(case_id, {}, SUB))
    return ctx


# ─── Tier 5: rental lifecycle ─────────────────────────

def create_rental(claim_id, adjuster_id, rental_start_date, rental_end_date, daily_rate_cents=6_000):
    """Create a PENDING rental reimbursement on the claim. Returns the rental dict."""
    headers = make_claims_adjuster_headers(adjuster_id)
    payload = create_rental_reimbursement_payload(
        claim_id,
        rental_start_date=rental_start_date,
        rental_end_date=rental_end_date,
        daily_rate_cents=daily_rate_cents,
    )
    return get_success_data(api_client.create_rental_reimbursement(payload, headers))


def setup_verified_claim_with_rental_coverage(rental_max_days=10, rental_daily_cap_cents=5_000):
    """Active policy with COLLISION + RENTAL coverage; an adjuster; a COVERAGE_VERIFIED claim.

    Returns dict: policy, adjuster, claim (verified).
    """
    policy = create_policy(comparative_fault_rule="PURE")
    add_collision_coverage(policy["id"])
    add_rental_coverage(policy["id"], rental_daily_cap_cents=rental_daily_cap_cents,
                        rental_max_days=rental_max_days)
    adjuster = create_adjuster(license_tier="STANDARD")
    claim = file_claim(policy["id"], adjuster["id"], loss_type="COLLISION", vehicle_acv_cents=800_000)
    verified = verify_claim(claim["id"], adjuster["id"])
    return {"policy": policy, "adjuster": adjuster, "claim": verified}


def setup_verified_claim_no_rental_coverage():
    """Active policy with only COLLISION coverage; an adjuster; a COVERAGE_VERIFIED claim.

    Returns dict: policy, adjuster, claim (verified).
    """
    policy = create_policy(comparative_fault_rule="PURE")
    add_collision_coverage(policy["id"])
    adjuster = create_adjuster(license_tier="STANDARD")
    claim = file_claim(policy["id"], adjuster["id"], loss_type="COLLISION", vehicle_acv_cents=800_000)
    verified = verify_claim(claim["id"], adjuster["id"])
    return {"policy": policy, "adjuster": adjuster, "claim": verified}
