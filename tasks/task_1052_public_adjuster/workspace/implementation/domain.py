"""Domain logic: exposure recompute, fee calculations, and cascades.

All formulas trace to SCAFFOLD.yaml 1.3 and PRD 2.5 / 2.9 / 3.x.
"""

from decimal import Decimal

from store import db, new_id
from common import round_half_up, touch, fmt_ts, stamp_new, parse_iso


# --- Fee rate -------------------------------------------------------------

def effective_pct(contract):
    """min(fee_pct, statutory_cap_pct) as a Decimal (PRD 3.4)."""
    return min(Decimal(str(contract["fee_pct"])), Decimal(str(contract["statutory_cap_pct"])))


# --- Policy exposure (PRD 2.9, dual view) ---------------------------------

def recompute_policy_exposure(policy):
    """Recompute forward_exposure_cents / committed_cents / remaining_limit_cents.

    forward = sum(pa_acv_estimate_cents) over claims not in {PAID, WITHDRAWN}
    committed = sum(settlement_amount_cents) over SETTLED claims
                + sum(amount_recovered_cents) over PAID claims  (PAID reconciled
                  to actual recovery per PRD 3.7). Approved-supplement amounts are
                  already folded into each claim's settlement_amount_cents.
    remaining = coverage_limit_cents - committed
    Only bumps version/updated_at when a figure actually changes (PRD 2.4).
    """
    forward = 0
    committed = 0
    for claim in db.claims.values():
        if claim["policy_id"] != policy["id"]:
            continue
        st = claim["status"]
        if st not in ("PAID", "WITHDRAWN"):
            forward += claim.get("pa_acv_estimate_cents") or 0
        if st == "SETTLED":
            committed += claim["settlement_amount_cents"]
        elif st == "PAID":
            committed += claim["amount_recovered_cents"]
    remaining = policy["coverage_limit_cents"] - committed

    changed = (
        policy.get("forward_exposure_cents") != forward
        or policy.get("committed_cents") != committed
        or policy.get("remaining_limit_cents") != remaining
    )
    policy["forward_exposure_cents"] = forward
    policy["committed_cents"] = committed
    policy["remaining_limit_cents"] = remaining
    if changed:
        touch(policy)


# --- Final fee (PRD 3.7 / total_fee_rounding: round per payment, then sum) -

def recompute_final_fee(claim, contract):
    pct = effective_pct(contract)
    total = 0
    for p in db.payments.values():
        if p["claim_id"] == claim["id"] and p["status"] == "CLEARED":
            total += round_half_up(p["amount_cents"], pct)
    claim["final_fee_cents"] = total


# --- Settlement side effects (PRD 3.4 / 3.5) ------------------------------

def apply_settlement(claim, contract, policy, amount, actor_user_id):
    claim["settlement_amount_cents"] = amount
    claim["settled_at"] = fmt_ts(db.now())
    claim["accepted_by_user_id"] = actor_user_id
    claim["provisional_fee_cents"] = round_half_up(
        claim.get("pa_acv_estimate_cents") or 0, effective_pct(contract)
    )
    claim["status"] = "SETTLED"
    touch(claim)
    recompute_policy_exposure(policy)


# --- Disbursement waterfall (PRD 3.7 / disbursement_waterfall) ------------

def create_disbursement(claim, payment, contract):
    pct = effective_pct(contract)
    gross = payment["amount_cents"]
    fee = round_half_up(gross, pct)
    advance_outstanding = contract["prior_advance_cents"] - contract["advance_recouped_cents"]
    advance_recoup = min(gross - fee, advance_outstanding)
    if advance_recoup < 0:
        advance_recoup = 0
    client = gross - fee - advance_recoup
    d = {
        "id": new_id(),
        "claim_id": claim["id"],
        "payment_id": payment["id"],
        "gross_cents": gross,
        "fee_cents": fee,
        "advance_recoup_cents": advance_recoup,
        "client_cents": client,
        "released_at": None,
        "status": "PENDING",
    }
    stamp_new(d)
    db.disbursements[d["id"]] = d
    return d


# --- License validity (PRD 2.9) -------------------------------------------

def license_currently_valid(adjuster_id, state_code):
    now = db.now()
    for lic in db.licenses.values():
        if lic["adjuster_id"] != adjuster_id or lic["state_code"] != state_code:
            continue
        if lic["status"] != "ACTIVE":
            continue
        eff = parse_iso(lic["effective_date"])
        exp = parse_iso(lic["expiry_date"])
        if eff <= now <= exp:
            return True
    return False


# --- Cascades: claim withdrawal via contract rescind (PRD 3.2) ------------

CLAIM_RESCIND_STATES = {"FILED", "NEGOTIATING", "OFFER_RECEIVED", "IN_APPRAISAL", "SETTLED"}


def void_claim_supplements(claim):
    for s in db.supplements.values():
        if s["claim_id"] == claim["id"] and s["status"] in ("DRAFT", "SUBMITTED"):
            s["status"] = "VOIDED"
            touch(s)


def cancel_invoked_appraisals(claim):
    for a in db.appraisals.values():
        if a["claim_id"] == claim["id"] and a["status"] == "INVOKED":
            a["status"] = "CANCELLED"
            touch(a)


def rescind_cascade(contract):
    """Withdraw every non-terminal claim on the contract and void supplements."""
    for claim in list(db.claims.values()):
        if claim["contract_id"] != contract["id"]:
            continue
        if claim["status"] not in CLAIM_RESCIND_STATES:
            continue
        if claim["status"] == "IN_APPRAISAL":
            cancel_invoked_appraisals(claim)
        claim["status"] = "WITHDRAWN"
        touch(claim)
        void_claim_supplements(claim)
        policy = db.policies.get(claim["policy_id"])
        if policy:
            recompute_policy_exposure(policy)
