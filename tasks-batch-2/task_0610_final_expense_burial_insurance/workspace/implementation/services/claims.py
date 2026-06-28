"""Claim adjudication, dual-variant payout, and the death-benefit waterfall
(PRD §3.11-§3.14)."""
import db
from clock import parse_iso
from errors import err
from helpers import round_half_up
from services import timecalc, policy_ops, policy_calc, ledger


def death_certificate_for(claim_id):
    for dc in db.death_certificates.values():
        if dc["claim_id"] == claim_id:
            return dc
    return None


def compute_payout(claim, policy, plan, finalize=False):
    """Dual-variant claim payout (PRD §3.12). Sets gross_benefit_cents and
    payout_basis on the claim in place. Returns gross_benefit_cents."""
    issue = parse_iso(policy["issue_date"])
    dod = parse_iso(claim["date_of_death"])
    months_in_force = timecalc.whole_months_between(issue, dod)

    benefit_type = policy["benefit_type"]
    graded_eligible = benefit_type in ("GRADED_BENEFIT", "LEVEL_BENEFIT")
    within_graded = (
        graded_eligible
        and months_in_force < plan["graded_period_months"]
        and claim["manner_of_death"] == "NATURAL"
    )

    if not within_graded:
        claim["payout_basis"] = "FULL_FACE"
        claim["gross_benefit_cents"] = policy["face_amount_cents"]
    else:
        claim["payout_basis"] = "GRADED_REFUND"
        refund = 0
        for p in db.premium_payments.values():
            if p["policy_id"] != policy["id"] or p["status"] != "POSTED":
                continue
            posted = parse_iso(p["posted_date"])
            days = timecalc.whole_days_between(posted, dod)
            interest_p = round_half_up(
                p["amount_cents"] * plan["graded_refund_apr"] * days / 365
            )
            refund += p["amount_cents"] + interest_p
        claim["gross_benefit_cents"] = refund
    return claim["gross_benefit_cents"]


def start_review(claim):
    if claim["status"] != "FILED":
        raise err("ERR_INVALID_STATE", "Claim is not FILED")
    if death_certificate_for(claim["id"]) is None:
        raise err("ERR_DEATH_CERTIFICATE_MISSING", "No DeathCertificate attached")
    claim["status"] = "UNDER_REVIEW"
    policy = db.policies.get(claim["policy_id"])
    plan = db.product_plans.get(policy["product_plan_id"])
    compute_payout(claim, policy, plan)
    claim["loan_offset_cents"] = policy_calc.outstanding_loan_balance_cents(policy["id"])
    claim["net_payout_cents"] = max(
        0, claim["gross_benefit_cents"] - claim["loan_offset_cents"]
    )
    db.touch(claim)
    return claim


def recompute_provisional(claim):
    """Recompute provisional gross/net when reading an UNDER_REVIEW/CONTESTING claim."""
    if claim["status"] not in ("UNDER_REVIEW", "CONTESTING"):
        return
    policy = db.policies.get(claim["policy_id"])
    plan = db.product_plans.get(policy["product_plan_id"])
    compute_payout(claim, policy, plan)
    claim["loan_offset_cents"] = policy_calc.outstanding_loan_balance_cents(policy["id"])
    claim["net_payout_cents"] = max(
        0, claim["gross_benefit_cents"] - claim["loan_offset_cents"]
    )


def contest(claim):
    if claim["status"] != "UNDER_REVIEW":
        raise err("ERR_INVALID_STATE", "Claim is not UNDER_REVIEW")
    policy = db.policies.get(claim["policy_id"])
    plan = db.product_plans.get(policy["product_plan_id"])
    issue = parse_iso(policy["issue_date"])
    dod = parse_iso(claim["date_of_death"])
    months = timecalc.whole_months_between(issue, dod)
    if months >= plan["contestability_period_months"]:
        raise err("ERR_OUTSIDE_CONTESTABILITY", "Death is outside the contestability window")
    claim["status"] = "CONTESTING"
    db.touch(claim)
    return claim


def approve(claim):
    if claim["status"] not in ("UNDER_REVIEW", "CONTESTING"):
        raise err("ERR_INVALID_STATE", "Claim is not UNDER_REVIEW or CONTESTING")
    policy = db.policies.get(claim["policy_id"])
    plan = db.product_plans.get(policy["product_plan_id"])
    if policy["coverage_status"] != "ACTIVE":
        raise err("ERR_POLICY_NOT_IN_FORCE", "Policy coverage is not ACTIVE")
    dc = death_certificate_for(claim["id"])
    if dc is None or not dc["verified"]:
        raise err("ERR_CERTIFICATE_NOT_VERIFIED", "DeathCertificate is not verified")

    # Finalize the payout.
    compute_payout(claim, policy, plan, finalize=True)
    loan_offset = policy_calc.outstanding_loan_balance_cents(policy["id"])
    claim["loan_offset_cents"] = loan_offset
    net_payout = max(0, claim["gross_benefit_cents"] - loan_offset)
    claim["net_payout_cents"] = net_payout
    claim["status"] = "APPROVED"

    # CASCADE depth-3 step 1: terminate policy (settles loans).
    policy_ops.terminate_on_claim(policy, loan_offset)
    policy_calc.recompute_policy(policy)

    ledger.append(policy["id"], "BENEFIT_PAID", net_payout, policy["net_cash_value_cents"])
    if loan_offset > 0:
        ledger.append(policy["id"], "LOAN_OFFSET", -loan_offset, policy["net_cash_value_cents"])

    # Allocate the net payout across payees (waterfall §3.14).
    allocate_waterfall(policy, net_payout)

    db.touch(claim)
    return claim


def deny(claim, denial_reason):
    if claim["status"] not in ("UNDER_REVIEW", "CONTESTING"):
        raise err("ERR_INVALID_STATE", "Claim is not UNDER_REVIEW or CONTESTING")
    policy = db.policies.get(claim["policy_id"])
    plan = db.product_plans.get(policy["product_plan_id"])
    from_contesting = claim["status"] == "CONTESTING"
    claim["net_payout_cents"] = 0

    if from_contesting:
        claim["denial_reason"] = "MISREPRESENTATION"
        # If within contestability window, rescind the policy.
        issue = parse_iso(policy["issue_date"])
        dod = parse_iso(claim["date_of_death"])
        months = timecalc.whole_months_between(issue, dod)
        if months < plan["contestability_period_months"] and policy["coverage_status"] == "ACTIVE":
            policy["coverage_status"] = "RESCINDED"
            db.touch(policy)
    else:
        # From UNDER_REVIEW: reason taken from the request.
        if denial_reason not in ("POLICY_NOT_IN_FORCE", "EXCLUDED_CAUSE"):
            raise err("ERR_VALIDATION", "denial_reason must be POLICY_NOT_IN_FORCE or EXCLUDED_CAUSE")
        claim["denial_reason"] = denial_reason

    claim["status"] = "DENIED"
    db.touch(claim)
    return claim


def allocate_waterfall(policy, pool):
    """Death-benefit waterfall (PRD §3.14). Funeral homes off the top, residual
    split across ACTIVE beneficiaries by share_pct (floor + remainder by created_at ASC)."""
    fh_total = sum(
        f["assigned_benefit_cents"] for f in db.funeral_home_assignments.values()
        if f["policy_id"] == policy["id"] and f["status"] == "ACTIVE"
    )
    fh_paid = min(pool, fh_total)
    residual = pool - fh_paid

    actives = [
        b for b in db.beneficiaries.values()
        if b["policy_id"] == policy["id"] and b["status"] == "ACTIVE"
    ]
    actives.sort(key=lambda b: (b.get("created_at", ""), b.get("_seq", 0)))
    shares = []
    for b in actives:
        b_share = (residual * b["share_pct"]) // 100
        shares.append(b_share)
    remainder = residual - sum(shares)
    i = 0
    while remainder > 0 and actives:
        shares[i % len(actives)] += 1
        remainder -= 1
        i += 1
    # Allocation is computed deterministically; figures are not persisted as
    # resource fields beyond the claim payout per the PRD.
    return fh_paid, list(zip(actives, shares))
