"""Composite setup helpers.

Every helper builds its preconditions from scratch through PRD-declared endpoints
and uses the lenient success reader so a broken precondition surfaces as a setup
failure rather than as a confusing assertion failure.

The helpers return plain dicts ("environments") whose keys name the rows created,
so a consumer can reach for exactly the row it needs:

    env = setup_approved_claim()
    env["claim"], env["policy"], env["insolvency"], env["assignment"]
"""

from typing import List, Optional

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import (
    COMMITTEE_OFFICER_USER_ID,
    SCREENING_ANALYST_USER_ID,
)
from .factories import (
    assessment_payload,
    claim_payload,
    coverage_profile_payload,
    distribution_payload,
    estate_remittance_payload,
    insolvency_payload,
    member_insurer_payload,
    other_insurance_payload,
    poc_transfer_payload,
    policy_payload,
    premium_refund_payload,
    referral_payload,
    screen_payload,
    surcharge_filing_payload,
    vendor_assignment_payload,
    vendor_invoice_payload,
)
from .test_users import (
    make_claims_adjuster_headers,
    make_claims_committee_officer_headers,
    make_coverage_analyst_headers,
    make_defense_counsel_headers,
    make_member_insurer_agent_headers,
    TEST_USERS,
)

ADMIN = TEST_USERS["association_admin_headers"]
RECEIVER = TEST_USERS["receiver_liaison_headers"]
ANALYST = TEST_USERS["coverage_analyst_headers"]
OFFICER = TEST_USERS["claims_committee_officer_headers"]
ASSESSOR = TEST_USERS["assessment_officer_headers"]


# ---------------------------------------------------------------------------
# Tier 0: single-call primitives
# ---------------------------------------------------------------------------


def move_clock(to_iso8601: str) -> dict:
    """Move the server's logical clock and return the sweep result."""
    return get_success_data(api_client.set_clock(to_iso8601, ADMIN))


def create_coverage_profile(**overrides) -> dict:
    """Register one statutory coverage configuration row."""
    return get_success_data(
        api_client.create_coverage_profile(coverage_profile_payload(**overrides), ADMIN)
    )


def create_insolvency(**overrides) -> dict:
    return get_success_data(api_client.create_insolvency(insolvency_payload(**overrides), ADMIN))


def create_policy(insolvency_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_policy(policy_payload(insolvency_id, **overrides), RECEIVER)
    )


def trigger_insolvency(insolvency_id: str) -> dict:
    return get_success_data(api_client.trigger_insolvency(insolvency_id, ADMIN))


def read_insolvency(insolvency_id: str) -> dict:
    return get_success_data(api_client.get_insolvency(insolvency_id, ADMIN))


def read_policy(policy_id: str) -> dict:
    return get_success_data(api_client.get_policy(policy_id, ADMIN))


def read_claim(claim_id: str) -> dict:
    return get_success_data(api_client.get_claim(claim_id, ADMIN))


def read_settlement_worksheet(claim_id: str) -> dict:
    """Read the term-by-term settlement worksheet for one claim."""
    return get_success_data(api_client.get_settlement_worksheet(claim_id, ANALYST))


def read_premium_refund(policy_id: str) -> dict:
    """Read the single unearned premium refund filed on one policy."""
    rows = api_client.list_premium_refunds(policy_id, ANALYST).json()["data"]
    if not rows:
        raise AssertionError(f"Setup failed: no unearned premium refund on policy {policy_id}")
    return rows[0]


def read_assessment(assessment_id: str) -> dict:
    return get_success_data(api_client.get_assessment(assessment_id, ASSESSOR))


def read_member_assessment(member_assessment_id: str) -> dict:
    return get_success_data(api_client.get_member_assessment(member_assessment_id, ASSESSOR))


def read_vendor_assignment(claim_id: str, assignment_id: str) -> dict:
    rows = get_success_data(api_client.list_vendor_assignments(claim_id, ADMIN))
    for row in rows:
        if row["id"] == assignment_id:
            return row
    raise AssertionError(f"Setup failed: engagement {assignment_id} not listed on claim {claim_id}")


def remit_estate_cash(insolvency_id: str, amount_cents: int, remittance_ref: str = "RM-1") -> dict:
    return get_success_data(
        api_client.create_estate_remittance(
            insolvency_id, estate_remittance_payload(amount_cents, remittance_ref), RECEIVER
        )
    )


def run_distribution(insolvency_id: str, amount_cents: int, expected_version: Optional[int] = None) -> dict:
    """Run one distribution, reading the live insolvency version when none is given."""
    if expected_version is None:
        expected_version = read_insolvency(insolvency_id)["version"]
    return get_success_data(
        api_client.run_distribution(
            insolvency_id, distribution_payload(amount_cents, expected_version), ADMIN
        )
    )


# ---------------------------------------------------------------------------
# Tier 1: state progression — a triggered insolvency with a cancelled policy
# ---------------------------------------------------------------------------


def setup_triggered_insolvency(
    profile_overrides: Optional[dict] = None,
    insolvency_overrides: Optional[dict] = None,
    policy_overrides: Optional[dict] = None,
    extra_profiles: Optional[List[dict]] = None,
    with_policy: bool = True,
    trigger: bool = True,
) -> dict:
    """Coverage configuration -> insolvency -> policy -> triggering event.

    The policy is keyed in before the triggering event so the order cancels it,
    which is the precondition for screening and for refund filing.
    """
    profile = create_coverage_profile(**(profile_overrides or {}))
    profiles = [profile]
    for spec in extra_profiles or []:
        profiles.append(create_coverage_profile(**spec))

    insolvency = create_insolvency(**(insolvency_overrides or {}))
    policy = None
    if with_policy:
        policy = create_policy(insolvency["id"], **(policy_overrides or {}))
    if trigger:
        insolvency = trigger_insolvency(insolvency["id"])
        if policy is not None:
            policy = read_policy(policy["id"])
    return {
        "profile": profile,
        "profiles": profiles,
        "insolvency": insolvency,
        "policy": policy,
    }


def setup_declared_insolvency(
    profile_overrides: Optional[dict] = None,
    insolvency_overrides: Optional[dict] = None,
    policy_overrides: Optional[dict] = None,
) -> dict:
    """Same chain but stopping short of the triggering event."""
    return setup_triggered_insolvency(
        profile_overrides=profile_overrides,
        insolvency_overrides=insolvency_overrides,
        policy_overrides=policy_overrides,
        trigger=False,
    )


# ---------------------------------------------------------------------------
# Tier 2: entity hierarchy — claims presented against a cancelled policy
# ---------------------------------------------------------------------------


def present_claim(env: dict, **claim_overrides) -> dict:
    """Present one covered claim against the environment's policy."""
    claim = get_success_data(
        api_client.create_claim(
            claim_payload(env["insolvency"]["id"], env["policy"]["id"], **claim_overrides),
            RECEIVER,
        )
    )
    env["claim"] = claim
    return claim


def setup_presented_claim(claim_overrides: Optional[dict] = None, **env_kwargs) -> dict:
    """Triggered insolvency plus one claim still in its intake status."""
    env = setup_triggered_insolvency(**env_kwargs)
    present_claim(env, **(claim_overrides or {}))
    return env


def screen_claim(
    env: dict,
    decision: str = "COVERED",
    analyst_user_id: str = SCREENING_ANALYST_USER_ID,
    **screen_overrides,
) -> dict:
    claim = get_success_data(
        api_client.screen_claim(
            env["claim"]["id"],
            screen_payload(decision, **screen_overrides),
            make_coverage_analyst_headers(analyst_user_id),
        )
    )
    env["claim"] = claim
    env["screening_analyst_user_id"] = analyst_user_id
    return claim


def setup_screened_claim(
    claim_overrides: Optional[dict] = None,
    analyst_user_id: str = SCREENING_ANALYST_USER_ID,
    **env_kwargs,
) -> dict:
    """Triggered insolvency, cancelled policy, one screened-eligible claim."""
    env = setup_presented_claim(claim_overrides=claim_overrides, **env_kwargs)
    screen_claim(env, "COVERED", analyst_user_id)
    return env


# ---------------------------------------------------------------------------
# Tier 3: full lifecycle shortcuts — vendors, recommendation, approval
# ---------------------------------------------------------------------------


def engage_vendor(env: dict, **assignment_overrides) -> dict:
    """Engage one contracted vendor on the environment's claim."""
    assignment = get_success_data(
        api_client.create_vendor_assignment(
            env["claim"]["id"], vendor_assignment_payload(**assignment_overrides), ADMIN
        )
    )
    env.setdefault("assignments", []).append(assignment)
    if assignment["vendor_type"] == "ADJUSTER":
        env["assignment"] = assignment
        env["adjuster_headers"] = make_claims_adjuster_headers(assignment["id"])
    else:
        env["counsel_assignment"] = assignment
        env["counsel_headers"] = make_defense_counsel_headers(assignment["id"])
    env["claim"] = read_claim(env["claim"]["id"])
    return assignment


def setup_claim_under_adjustment(
    assignment_overrides: Optional[dict] = None,
    claim_overrides: Optional[dict] = None,
    analyst_user_id: str = SCREENING_ANALYST_USER_ID,
    **env_kwargs,
) -> dict:
    """Screened claim plus its ADJUSTER engagement, so the claim is in adjustment."""
    env = setup_screened_claim(
        claim_overrides=claim_overrides, analyst_user_id=analyst_user_id, **env_kwargs
    )
    engage_vendor(env, **(assignment_overrides or {}))
    return env


def recommend(env: dict, recommended_amount_cents: int, note: Optional[str] = None) -> dict:
    payload = {"recommended_amount_cents": recommended_amount_cents}
    if note is not None:
        payload["note"] = note
    claim = get_success_data(
        api_client.recommend_claim(env["claim"]["id"], payload, env["adjuster_headers"])
    )
    env["claim"] = claim
    return claim


def setup_recommended_claim(
    recommended_amount_cents: int = 990_000,
    assignment_overrides: Optional[dict] = None,
    claim_overrides: Optional[dict] = None,
    analyst_user_id: str = SCREENING_ANALYST_USER_ID,
    **env_kwargs,
) -> dict:
    """Claim carried through to a live adjuster recommendation."""
    env = setup_claim_under_adjustment(
        assignment_overrides=assignment_overrides,
        claim_overrides=claim_overrides,
        analyst_user_id=analyst_user_id,
        **env_kwargs,
    )
    recommend(env, recommended_amount_cents)
    return env


def approve(env: dict, officer_user_id: str = COMMITTEE_OFFICER_USER_ID, approval_note: Optional[str] = None) -> dict:
    payload = {} if approval_note is None else {"approval_note": approval_note}
    claim = get_success_data(
        api_client.approve_claim(
            env["claim"]["id"], make_claims_committee_officer_headers(officer_user_id), payload
        )
    )
    env["claim"] = claim
    env["approving_officer_user_id"] = officer_user_id
    return claim


def setup_approved_claim(
    recommended_amount_cents: int = 990_000,
    officer_user_id: str = COMMITTEE_OFFICER_USER_ID,
    approval_note: Optional[str] = None,
    **kwargs,
) -> dict:
    """Claim carried all the way through committee approval."""
    env = setup_recommended_claim(recommended_amount_cents=recommended_amount_cents, **kwargs)
    approve(env, officer_user_id, approval_note)
    return env


def setup_approved_claim_with_estate_cash(
    remitted_cents: int,
    recommended_amount_cents: int = 990_000,
    **kwargs,
) -> dict:
    """Approved claim with estate cash already remitted, ready for a distribution run."""
    env = setup_approved_claim(recommended_amount_cents=recommended_amount_cents, **kwargs)
    env["insolvency"] = remit_estate_cash(env["insolvency"]["id"], remitted_cents)
    return env


# ---------------------------------------------------------------------------
# Other-insurance layers
# ---------------------------------------------------------------------------


def register_other_insurance(env: dict, expected_claim_version: Optional[int] = None, **overrides) -> dict:
    """Register an other-insurance layer against the environment's claim."""
    if expected_claim_version is None:
        expected_claim_version = read_claim(env["claim"]["id"])["version"]
    layer = get_success_data(
        api_client.create_other_insurance(
            env["claim"]["id"],
            other_insurance_payload(expected_claim_version, **overrides),
            ANALYST,
        )
    )
    env.setdefault("other_insurance", []).append(layer)
    env["layer"] = layer
    env["claim"] = read_claim(env["claim"]["id"])
    return layer


def advance_other_insurance(env: dict, layer_id: str, status: str, recovered_cents: Optional[int] = None) -> dict:
    payload = {"status": status}
    if recovered_cents is not None:
        payload["recovered_cents"] = recovered_cents
    layer = get_success_data(
        api_client.update_other_insurance(env["claim"]["id"], layer_id, payload, ANALYST)
    )
    env["layer"] = layer
    env["claim"] = read_claim(env["claim"]["id"])
    return layer


def setup_claim_with_resolved_other_insurance(
    recovered_cents: int,
    final_status: str = "EXHAUSTED",
    claim_overrides: Optional[dict] = None,
    layer_overrides: Optional[dict] = None,
    **env_kwargs,
) -> dict:
    """Screened claim whose single other-insurance layer has been pursued to a
    resolved posture, so its recovery is inside the statutory computation."""
    env = setup_screened_claim(claim_overrides=claim_overrides, **env_kwargs)
    layer = register_other_insurance(env, **(layer_overrides or {}))
    advance_other_insurance(env, layer["id"], "PURSUING")
    advance_other_insurance(env, layer["id"], final_status, recovered_cents)
    return env


# ---------------------------------------------------------------------------
# Vendor invoices
# ---------------------------------------------------------------------------


def post_vendor_invoice(env: dict, hours: float, invoice_ref: str = "INV-1", assignment: Optional[dict] = None) -> dict:
    """Post an hourly invoice on an engagement, accruing administrative expense."""
    assignment = assignment or env["assignment"]
    headers = (
        make_claims_adjuster_headers(assignment["id"])
        if assignment["vendor_type"] == "ADJUSTER"
        else make_defense_counsel_headers(assignment["id"])
    )
    updated = get_success_data(
        api_client.create_vendor_invoice(
            env["claim"]["id"], assignment["id"], vendor_invoice_payload(hours, invoice_ref), headers
        )
    )
    if assignment["vendor_type"] == "ADJUSTER":
        env["assignment"] = updated
        env["adjuster_headers"] = make_claims_adjuster_headers(updated["id"])
    else:
        env["counsel_assignment"] = updated
    return updated


# ---------------------------------------------------------------------------
# Unearned premium refunds
# ---------------------------------------------------------------------------


def file_premium_refund(
    env: dict,
    refund_method: str,
    expected_policy_version: Optional[int] = None,
    policy: Optional[dict] = None,
) -> dict:
    """File the single refund admissible on a cancelled policy of the environment."""
    target = policy if policy is not None else env["policy"]
    if expected_policy_version is None:
        expected_policy_version = read_policy(target["id"])["version"]
    refund = get_success_data(
        api_client.create_premium_refund(
            target["id"],
            premium_refund_payload(refund_method, expected_policy_version),
            ANALYST,
        )
    )
    env.setdefault("refunds", []).append(refund)
    env["refund"] = refund
    if env.get("policy") and env["policy"]["id"] == target["id"]:
        env["policy"] = read_policy(target["id"])
    return refund


def setup_policy_with_premium_refund(
    refund_method: str = "SHORT_RATE",
    policy_overrides: Optional[dict] = None,
    **env_kwargs,
) -> dict:
    """Triggered insolvency, cancelled policy, one filed unearned premium refund."""
    env = setup_triggered_insolvency(policy_overrides=policy_overrides, **env_kwargs)
    file_premium_refund(env, refund_method)
    return env


# ---------------------------------------------------------------------------
# Sister-association referrals
# ---------------------------------------------------------------------------


def raise_referral(env: dict, target_state_code: str, basis: str) -> dict:
    referral = get_success_data(
        api_client.create_referral(
            env["claim"]["id"], referral_payload(target_state_code, basis), ADMIN
        )
    )
    env.setdefault("referrals", []).append(referral)
    env["referral"] = referral
    env["claim"] = read_claim(env["claim"]["id"])
    return referral


def respond_to_referral(env: dict, disposition: str, response_note: Optional[str] = None) -> dict:
    payload = {"disposition": disposition}
    if response_note is not None:
        payload["response_note"] = response_note
    referral = get_success_data(
        api_client.respond_referral(
            env["claim"]["id"], env["referral"]["id"], payload, ADMIN
        )
    )
    env["referral"] = referral
    env["claim"] = read_claim(env["claim"]["id"])
    return referral


def setup_claim_with_open_referral(
    target_state_code: str = "OH",
    basis: str = "CLAIMANT_RESIDENCE",
    claim_overrides: Optional[dict] = None,
    **env_kwargs,
) -> dict:
    """Screened claim parked on an open sister-association referral."""
    env = setup_screened_claim(claim_overrides=claim_overrides, **env_kwargs)
    raise_referral(env, target_state_code, basis)
    return env


# ---------------------------------------------------------------------------
# Tier 4: accumulation / threshold targeting — assessments and recoupment
# ---------------------------------------------------------------------------


def register_member_insurer(**overrides) -> dict:
    return get_success_data(
        api_client.create_member_insurer(member_insurer_payload(**overrides), ADMIN)
    )


def register_member_insurers(specs: List[dict]) -> List[dict]:
    """Register members in list order so their registration sequence is known."""
    return [register_member_insurer(**spec) for spec in specs]


def draft_assessment(insolvency_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_assessment(assessment_payload(insolvency_id, **overrides), ASSESSOR)
    )


def certify_assessment(assessment_id: str) -> dict:
    return get_success_data(api_client.certify_assessment(assessment_id, ASSESSOR))


def list_member_assessments(**params) -> List[dict]:
    body = api_client.list_member_assessments(ASSESSOR, params=params or None).json()
    return body["data"]


def setup_certified_assessment(
    member_specs: Optional[List[dict]] = None,
    needed_amount_cents: int = 1_400_000,
    assessment_overrides: Optional[dict] = None,
    insolvency_overrides: Optional[dict] = None,
    profile_overrides: Optional[dict] = None,
    policy_overrides: Optional[dict] = None,
    with_policy: bool = True,
) -> dict:
    """Register member insurers, draft the levy and certify it.

    Returns the environment plus ``members``, ``assessment`` and
    ``member_assessments`` (the invoices, in the order the members were
    registered) and ``agent_headers`` keyed by member insurer id.
    """
    env = setup_triggered_insolvency(
        profile_overrides=profile_overrides,
        insolvency_overrides=insolvency_overrides,
        policy_overrides=policy_overrides,
        with_policy=with_policy,
    )
    specs = member_specs if member_specs is not None else [
        {
            "naic_code": "20001",
            "insurer_name": "Wolverine Mutual Insurance",
            "direct_written_premium_cents": 100_000_000,
        }
    ]
    members = register_member_insurers(specs)
    env["members"] = members

    overrides = dict(assessment_overrides or {})
    overrides.setdefault("needed_amount_cents", needed_amount_cents)
    assessment = draft_assessment(env["insolvency"]["id"], **overrides)
    env["assessment"] = certify_assessment(assessment["id"])

    invoices = list_member_assessments(assessment_id=assessment["id"], limit=100)
    by_member = {row["member_insurer_id"]: row for row in invoices}
    env["member_assessments"] = [by_member[m["id"]] for m in members if m["id"] in by_member]
    env["member_assessment_by_member_id"] = by_member
    env["agent_headers"] = {
        m["id"]: make_member_insurer_agent_headers(m["id"]) for m in members
    }
    if env["member_assessments"]:
        env["member_assessment"] = env["member_assessments"][0]
        env["agent"] = env["agent_headers"][members[0]["id"]]
    return env


def pay_member_levy(env: dict, amount_cents: int, payment_ref: str = "PAY-1", invoice: Optional[dict] = None) -> dict:
    invoice = invoice or env["member_assessment"]
    headers = env["agent_headers"][invoice["member_insurer_id"]]
    updated = get_success_data(
        api_client.create_member_payment(
            invoice["id"], {"amount_cents": amount_cents, "payment_ref": payment_ref}, headers
        )
    )
    if invoice is env.get("member_assessment"):
        env["member_assessment"] = updated
    return updated


def file_surcharge(
    env: dict,
    surcharge_rate_bps: int,
    surcharge_base_cents: int,
    filing_ref: str = "SF-1",
    invoice: Optional[dict] = None,
) -> dict:
    invoice = invoice or env["member_assessment"]
    headers = env["agent_headers"][invoice["member_insurer_id"]]
    updated = get_success_data(
        api_client.create_surcharge_filing(
            invoice["id"],
            surcharge_filing_payload(surcharge_rate_bps, surcharge_base_cents, filing_ref),
            headers,
        )
    )
    if invoice is env.get("member_assessment"):
        env["member_assessment"] = updated
    return updated


def remit_recoupment(
    env: dict,
    proceeds_cents: int,
    remittance_ref: str = "RR-1",
    invoice: Optional[dict] = None,
) -> dict:
    invoice = invoice or env["member_assessment"]
    headers = env["agent_headers"][invoice["member_insurer_id"]]
    updated = get_success_data(
        api_client.create_recoupment_remittance(
            invoice["id"], {"proceeds_cents": proceeds_cents, "remittance_ref": remittance_ref}, headers
        )
    )
    if invoice is env.get("member_assessment"):
        env["member_assessment"] = updated
    return updated


def setup_member_assessment_with_surcharge(
    surcharge_rate_bps: int = 25,
    surcharge_base_cents: int = 60_000_000,
    member_specs: Optional[List[dict]] = None,
    needed_amount_cents: int = 1_400_000,
    **kwargs,
) -> dict:
    """Certified levy whose first invoice already carries an accepted surcharge filing."""
    env = setup_certified_assessment(
        member_specs=member_specs, needed_amount_cents=needed_amount_cents, **kwargs
    )
    file_surcharge(env, surcharge_rate_bps, surcharge_base_cents)
    return env


# ---------------------------------------------------------------------------
# Proof-of-claim batches
# ---------------------------------------------------------------------------


def deliver_poc_transfer(env: dict, receiver_batch_ref: str, records: List[dict]) -> dict:
    transfer = get_success_data(
        api_client.create_poc_transfer(
            env["insolvency"]["id"], poc_transfer_payload(receiver_batch_ref, records), RECEIVER
        )
    )
    env.setdefault("transfers", []).append(transfer)
    env["transfer"] = transfer
    return transfer


def convert_poc_transfer(env: dict, transfer_id: Optional[str] = None) -> dict:
    transfer_id = transfer_id or env["transfer"]["id"]
    transfer = get_success_data(api_client.convert_poc_transfer(transfer_id, RECEIVER))
    env["transfer"] = transfer
    return transfer


def setup_delivered_poc_batch(
    records: List[dict],
    receiver_batch_ref: str = "RB-001",
    with_policy: bool = False,
    trigger: bool = False,
    **env_kwargs,
) -> dict:
    """Insolvency file plus one unconverted proof-of-claim batch.

    Conversion is admissible while the file is still in its declared status, so
    neither a policy nor the triggering event is required by default.
    """
    env = setup_triggered_insolvency(with_policy=with_policy, trigger=trigger, **env_kwargs)
    deliver_poc_transfer(env, receiver_batch_ref, records)
    return env


# ---------------------------------------------------------------------------
# Committee remand cycles
# ---------------------------------------------------------------------------


def remand(env: dict, remand_reason: str, officer_user_id: str = COMMITTEE_OFFICER_USER_ID) -> dict:
    """Send a live recommendation back to adjustment."""
    claim = get_success_data(
        api_client.remand_claim(
            env["claim"]["id"],
            {"remand_reason": remand_reason},
            make_claims_committee_officer_headers(officer_user_id),
        )
    )
    env["claim"] = claim
    return claim


def setup_claim_after_two_remand_cycles(
    recommended_amounts: tuple = (2_400_000, 2_200_000, 2_000_000),
    remand_reasons: tuple = ("medical documentation incomplete", "wage loss unverified"),
    assignment_overrides: Optional[dict] = None,
    claim_overrides: Optional[dict] = None,
    **env_kwargs,
) -> dict:
    """A claim that has completed both permitted recommend/remand cycles and is
    sitting on its third live recommendation."""
    env = setup_claim_under_adjustment(
        assignment_overrides=assignment_overrides, claim_overrides=claim_overrides, **env_kwargs
    )
    recommend(env, recommended_amounts[0], "first recommendation")
    remand(env, remand_reasons[0])
    recommend(env, recommended_amounts[1], "second recommendation")
    remand(env, remand_reasons[1])
    recommend(env, recommended_amounts[2], "third recommendation")
    return env


# ---------------------------------------------------------------------------
# Multi-row scenarios: two policies, two refunds, invoiced engagements
# ---------------------------------------------------------------------------


def setup_two_policies_with_pending_refunds(
    refund_method: str = "PRO_RATA",
    first_policy_overrides: Optional[dict] = None,
    second_policy_overrides: Optional[dict] = None,
    remitted_cents: Optional[int] = None,
    profile_overrides: Optional[dict] = None,
    insolvency_overrides: Optional[dict] = None,
) -> dict:
    """Two cancelled policies each carrying one pending unearned premium refund.

    Both policies are keyed in before the triggering event so the liquidation
    order cancels both, which is what makes a refund admissible on each.
    """
    env = setup_declared_insolvency(
        profile_overrides=profile_overrides,
        insolvency_overrides=insolvency_overrides,
        policy_overrides=first_policy_overrides,
    )
    second = create_policy(env["insolvency"]["id"], **(second_policy_overrides or {}))
    env["insolvency"] = trigger_insolvency(env["insolvency"]["id"])
    env["policy"] = read_policy(env["policy"]["id"])
    env["second_policy"] = read_policy(second["id"])
    env["policies"] = [env["policy"], env["second_policy"]]

    env["first_refund"] = file_premium_refund(env, refund_method, policy=env["policy"])
    env["second_refund"] = file_premium_refund(env, refund_method, policy=env["second_policy"])
    if remitted_cents:
        env["insolvency"] = remit_estate_cash(env["insolvency"]["id"], remitted_cents)
    else:
        env["insolvency"] = read_insolvency(env["insolvency"]["id"])
    return env


def setup_two_policies_at_net_worth_boundary(
    low_net_worth_cents: int,
    high_net_worth_cents: int,
    gross_loss_cents: int = 900_000,
    profile_overrides: Optional[dict] = None,
) -> dict:
    """Two cancelled policies whose policyholder net worth straddles the line's
    exclusion threshold, each carrying one claim still awaiting screening."""
    env = setup_declared_insolvency(
        profile_overrides=profile_overrides,
        policy_overrides={
            "policy_number": "PA-1001",
            "policyholder_name": "Ada Renner",
            "policyholder_net_worth_cents": low_net_worth_cents,
        },
    )
    high_policy = create_policy(
        env["insolvency"]["id"],
        policy_number="PA-1002",
        policyholder_name="Renner Holdings",
        policyholder_net_worth_cents=high_net_worth_cents,
    )
    env["insolvency"] = trigger_insolvency(env["insolvency"]["id"])
    env["policy"] = read_policy(env["policy"]["id"])
    env["high_net_worth_policy"] = read_policy(high_policy["id"])

    insolvency_id = env["insolvency"]["id"]
    env["low_net_worth_claim"] = get_success_data(
        api_client.create_claim(
            claim_payload(
                insolvency_id,
                env["policy"]["id"],
                claim_number="C-LO",
                claimant_name="Ben Ortiz",
                gross_loss_cents=gross_loss_cents,
            ),
            ANALYST,
        )
    )
    env["high_net_worth_claim"] = get_success_data(
        api_client.create_claim(
            claim_payload(
                insolvency_id,
                env["high_net_worth_policy"]["id"],
                claim_number="C-HI",
                claimant_name="Cora Diaz",
                gross_loss_cents=gross_loss_cents,
            ),
            ANALYST,
        )
    )
    return env


def setup_approved_claim_with_vendor_invoice(
    hours: float = 10,
    invoice_ref: str = "INV-1",
    recommended_amount_cents: int = 2_400_000,
    remitted_cents: Optional[int] = None,
    **kwargs,
) -> dict:
    """Approved claim whose engagement has already invoiced hours, so the file
    carries both a claim reserve and accrued administrative expense."""
    env = setup_claim_under_adjustment(**kwargs)
    post_vendor_invoice(env, hours, invoice_ref)
    recommend(env, recommended_amount_cents)
    approve(env)
    if remitted_cents:
        env["insolvency"] = remit_estate_cash(env["insolvency"]["id"], remitted_cents)
    else:
        env["insolvency"] = read_insolvency(env["insolvency"]["id"])
    return env


def setup_recommended_claim_with_pursuing_layer(
    recommended_amount_cents: int = 1_000_000,
    analyst_user_id: str = SCREENING_ANALYST_USER_ID,
    layer_overrides: Optional[dict] = None,
    assignment_overrides: Optional[dict] = None,
    claim_overrides: Optional[dict] = None,
    **env_kwargs,
) -> dict:
    """A recommended claim with one other-insurance layer still being pursued, so
    the non-duplication gate at approval is not yet satisfied."""
    env = setup_screened_claim(
        claim_overrides=claim_overrides, analyst_user_id=analyst_user_id, **env_kwargs
    )
    layer = register_other_insurance(env, **(layer_overrides or {}))
    advance_other_insurance(env, layer["id"], "PURSUING")
    engage_vendor(env, **(assignment_overrides or {}))
    recommend(env, recommended_amount_cents)
    return env


# ---------------------------------------------------------------------------
# Tier 5: finalization / terminal state
# ---------------------------------------------------------------------------


def close_insolvency(insolvency_id: str) -> dict:
    return get_success_data(api_client.close_insolvency(insolvency_id, ADMIN))


def setup_fully_settled_insolvency(
    recommended_amount_cents: int = 890_000,
    remitted_cents: int = 1_000_000,
    **kwargs,
) -> dict:
    """Approved claim, estate cash remitted and one distribution run that pays the
    claim in full, leaving the file ready to close."""
    env = setup_approved_claim_with_estate_cash(
        remitted_cents=remitted_cents, recommended_amount_cents=recommended_amount_cents, **kwargs
    )
    env["distribution"] = run_distribution(
        env["insolvency"]["id"], env["claim"]["net_payable_cents"]
    )
    env["claim"] = read_claim(env["claim"]["id"])
    env["insolvency"] = read_insolvency(env["insolvency"]["id"])
    return env


def setup_closed_insolvency(**kwargs) -> dict:
    """Insolvency file walked through to CLOSED, for post-closure lockdown checks."""
    env = setup_fully_settled_insolvency(**kwargs)
    env["insolvency"] = close_insolvency(env["insolvency"]["id"])
    return env
