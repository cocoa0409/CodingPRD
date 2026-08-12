"""Core domain services: entity factories, serializers, fraud scoring,
allowance/funding ledger operations, and cascade machinery."""
import math
import uuid
from datetime import timedelta
from decimal import Decimal

from db import STORE
from util import fmt_ts, quarter_key_of, rhu

ELIGIBILITY_WAIT_DAYS = 30
DEPENDENT_CAP_MAX = 3
FRAUD_FLAG_THRESHOLD = 50
FRAUD_BLOCK_THRESHOLD = 80
VELOCITY_WINDOW_DAYS = 7
VELOCITY_FREE_COUNT = 5
PROVIDER_PATTERN_WINDOW_DAYS = 30
MAX_RESUBMISSIONS = 3
FILING_DEADLINE_DAYS = 90

OPEN_REVIEW = ("SUBMITTED", "UNDER_REVIEW", "NEEDS_INFO")


# ---------------------------------------------------------------------------
# Base entity helpers
# ---------------------------------------------------------------------------

def new_entity(with_version=True):
    eid = str(uuid.uuid4())
    now = fmt_ts(STORE.clock)
    e = {"id": eid, "created_at": now}
    if with_version:
        e["updated_at"] = now
        e["version"] = 1
    e["_seq"] = STORE.next_seq()
    return e


def touch(e):
    e["updated_at"] = fmt_ts(STORE.clock)
    e["version"] = e.get("version", 1) + 1


def serialize(e):
    return {k: v for k, v in e.items() if not k.startswith("_")}


def sort_created(items):
    return sorted(items, key=lambda e: e["_seq"])


# ---------------------------------------------------------------------------
# Lookup helpers
# ---------------------------------------------------------------------------

def tiers_of_plan(plan_id):
    return [t for t in sort_created(STORE.tiers.values()) if t["plan_id"] == plan_id]


def tier_for(plan_id, tier_code):
    for t in STORE.tiers.values():
        if t["plan_id"] == plan_id and t["tier_code"] == tier_code:
            return t
    return None


def active_dependents(member_id):
    return [d for d in STORE.dependents.values()
            if d["member_id"] == member_id and d["status"] == "ACTIVE"]


def claims_of_enrollment(enrollment_id):
    return [c for c in STORE.claims.values() if c["enrollment_id"] == enrollment_id]


def find_funding_account(employer_id, benefit_year):
    for a in STORE.funding_accounts.values():
        if a["employer_id"] == employer_id and a["benefit_year"] == benefit_year:
            return a
    return None


def funding_for_claim(claim):
    enr = STORE.enrollments.get(claim["enrollment_id"])
    if not enr:
        return None
    plan = STORE.plans.get(enr["plan_id"])
    if not plan:
        return None
    return find_funding_account(plan["employer_id"], plan["benefit_year"])


# ---------------------------------------------------------------------------
# Allowance (calc_effective_allowance / calc_allowance_ledger)
# ---------------------------------------------------------------------------

def effective_allowance(tier, member_id):
    base = tier["annual_allowance_cents"]
    if tier["tier_code"] == "FAMILY":
        n = min(len(active_dependents(member_id)), DEPENDENT_CAP_MAX)
        return rhu(Decimal(base) * (Decimal(1) + Decimal(n) * Decimal(str(tier["dependent_cap_pct"]))))
    return base


def recompute_member_allowances(member_id):
    """Dependent add/deactivate: recompute annual allowance on the member's
    ACTIVE/EXHAUSTED enrollments (calc_effective_allowance)."""
    for enr in STORE.enrollments.values():
        if enr["member_id"] != member_id or enr["status"] not in ("ACTIVE", "EXHAUSTED"):
            continue
        tier = tier_for(enr["plan_id"], enr["tier_code"]) or enr["_tier_snapshot"]
        enr["annual_allowance_cents"] = effective_allowance(tier, member_id)
        touch(enr)


# ---------------------------------------------------------------------------
# Funding ledger (calc_funding_reconciliation)
# ---------------------------------------------------------------------------

def append_funding_entry(account, claim_id, entry_type, amount):
    """Append one ledger entry and apply it to account counters immediately.
    amount is always stored positive; the sign is implied by entry_type."""
    a = account
    if entry_type == "DEPOSIT":
        a["funded_cents"] += amount
        a["available_cents"] += amount
    elif entry_type == "HOLD":
        a["reserved_cents"] += amount
        a["available_cents"] -= amount
    elif entry_type == "RELEASE":
        a["reserved_cents"] -= amount
        a["available_cents"] += amount
    elif entry_type == "DEBIT":
        a["reserved_cents"] -= amount
        a["disbursed_cents"] += amount
    elif entry_type == "CLAWBACK_CREDIT":
        a["disbursed_cents"] -= amount
        a["available_cents"] += amount
    entry = new_entity(with_version=False)
    entry.update({
        "funding_account_id": a["id"],
        "claim_id": claim_id,
        "entry_type": entry_type,
        "amount_cents": amount,
        "running_available_cents": a["available_cents"],
    })
    STORE.funding_entries[entry["id"]] = entry
    # System posture: FUNDED -> DEPLETED when available hits exactly 0 after a HOLD or DEBIT.
    if entry_type in ("HOLD", "DEBIT") and a["available_cents"] == 0 and a["status"] == "FUNDED":
        a["status"] = "DEPLETED"
    if entry_type == "DEPOSIT" and amount > 0 and a["status"] == "DEPLETED":
        a["status"] = "FUNDED"
    touch(a)
    return entry


# ---------------------------------------------------------------------------
# Claim reservation / rejection machinery
# ---------------------------------------------------------------------------

def claim_fraud_hold(claim):
    """True when any referenced visit has an OPEN or CONFIRMED FraudFlag."""
    for vid in claim.get("visit_ids", []):
        for f in STORE.fraud_flags.values():
            if f.get("visit_id") == vid and f["status"] in ("OPEN", "CONFIRMED"):
                return True
    return False


def release_claim_reservation(claim):
    """Hand back the claim's enrollment reservation and any funding HOLD.
    Must be called BEFORE flipping review_status away from its current value."""
    enr = STORE.enrollments.get(claim["enrollment_id"])
    if enr is None:
        return
    if claim["review_status"] in OPEN_REVIEW:
        enr["reserved_cents"] -= claim["claimed_amount_cents"]
        touch(enr)
    elif claim["review_status"] == "APPROVED" and claim["payment_status"] == "UNPAID":
        approved = claim["approved_amount_cents"] or 0
        enr["reserved_cents"] -= approved
        touch(enr)
        acct = funding_for_claim(claim)
        if acct is not None:
            append_funding_entry(acct, claim["id"], "RELEASE", approved)


def reject_claim(claim):
    """System/manual rejection: release reservation (+funding hold) then flip."""
    release_claim_reservation(claim)
    claim["review_status"] = "REJECTED"
    touch(claim)


def reject_open_claims_of_enrollment(enr, include_approved_unpaid=False):
    for c in claims_of_enrollment(enr["id"]):
        if c["review_status"] in OPEN_REVIEW:
            reject_claim(c)
        elif include_approved_unpaid and c["review_status"] == "APPROVED" \
                and c["payment_status"] == "UNPAID":
            reject_claim(c)


# ---------------------------------------------------------------------------
# Cascades
# ---------------------------------------------------------------------------

def terminate_member_cascade(member):
    for dep in STORE.dependents.values():
        if dep["member_id"] == member["id"] and dep["status"] == "ACTIVE":
            dep["status"] = "INACTIVE"
            touch(dep)
    for enr in STORE.enrollments.values():
        if enr["member_id"] == member["id"] and enr["status"] in ("ACTIVE", "EXHAUSTED"):
            enr["status"] = "CLOSED"
            touch(enr)
            reject_open_claims_of_enrollment(enr, include_approved_unpaid=True)


def reject_visit_cascade(visit):
    """Claims referencing this visit in SUBMITTED/NEEDS_INFO auto-reject."""
    for c in STORE.claims.values():
        if visit["id"] in c.get("visit_ids", []) and c["review_status"] in ("SUBMITTED", "NEEDS_INFO"):
            reject_claim(c)


def terminate_provider_cascade(provider):
    for v in STORE.visits.values():
        if v["provider_id"] == provider["id"] and v["status"] == "RECORDED":
            v["status"] = "REJECTED"
            touch(v)
    for c in STORE.claims.values():
        if c["provider_id"] == provider["id"] and c["review_status"] in ("SUBMITTED", "NEEDS_INFO"):
            reject_claim(c)


def exhaustion_cascade(enr):
    """After a payment: flip ACTIVE -> EXHAUSTED when used >= allowance and
    auto-reject every other open claim on the enrollment."""
    if enr["status"] == "ACTIVE" and enr["used_cents"] >= enr["annual_allowance_cents"]:
        enr["status"] = "EXHAUSTED"
        touch(enr)
        reject_open_claims_of_enrollment(enr)


def clawback_recovery(enr):
    if enr["status"] == "EXHAUSTED" and enr["used_cents"] < enr["annual_allowance_cents"]:
        enr["status"] = "ACTIVE"
        touch(enr)


# ---------------------------------------------------------------------------
# Fraud scoring (calc_fraud_score)
# ---------------------------------------------------------------------------

def _decay(age_days):
    if age_days <= 3:
        return 1.0
    if age_days <= 7:
        return 0.5
    return 0.0


def _provider_pattern(member_check_in, provider):
    """+20 when the provider was SUSPENDED at any point in the 30 days before
    check_in_at; decays by the most recent overlapping suspension's age."""
    window_start = member_check_in - timedelta(days=PROVIDER_PATTERN_WINDOW_DAYS)
    best_age = None
    for (susp, rein) in provider.get("_suspensions", []):
        interval_end = rein if rein is not None else member_check_in
        # does [susp, interval_end] intersect [window_start, check_in]?
        if susp <= member_check_in and interval_end >= window_start:
            overlap_end = min(interval_end, member_check_in)
            age = (member_check_in - overlap_end).total_seconds() / 86400.0
            if best_age is None or age < best_age:
                best_age = age
    if best_age is None:
        return 0.0
    return 20.0 * _decay(best_age)


def fraud_score(visit, final=False):
    """Weighted scoring. Provisional: velocity set counts RECORDED+VERIFIED.
    Final: VERIFIED only, CONFIRMED-flagged signals count double."""
    statuses = ("VERIFIED",) if final else ("RECORDED", "VERIFIED")
    check_in = visit["_check_in_dt"]
    window_start = check_in - timedelta(days=VELOCITY_WINDOW_DAYS)
    priors = [v for v in STORE.visits.values()
              if v["member_id"] == visit["member_id"]
              and v["id"] != visit["id"]
              and v["status"] in statuses
              and window_start <= v["_check_in_dt"] <= check_in]
    priors.sort(key=lambda v: (v["_check_in_dt"], v["_seq"]))
    # The visit itself sits at the window end; the first five visits are free.
    combined = priors + [visit]
    contributions = {"GEOFENCE_MISMATCH": 0.0, "VELOCITY": 0.0,
                     "PROVIDER_PATTERN": 0.0, "DUPLICATE_RECEIPT": 0.0}
    for v in combined[VELOCITY_FREE_COUNT:]:
        age = (check_in - v["_check_in_dt"]).total_seconds() / 86400.0
        contributions["VELOCITY"] += 10.0 * _decay(age)
    if visit["verification_method"] == "MANUAL_REVIEW":
        contributions["GEOFENCE_MISMATCH"] = 30.0
    provider = STORE.providers.get(visit["provider_id"])
    if provider is not None:
        contributions["PROVIDER_PATTERN"] = _provider_pattern(check_in, provider)
    if final:
        confirmed_signals = {f["signal"] for f in STORE.fraud_flags.values()
                             if f.get("visit_id") == visit["id"] and f["status"] == "CONFIRMED"}
        for sig in confirmed_signals:
            if sig in contributions:
                contributions[sig] *= 2.0
    score = min(100, int(sum(contributions.values())))
    return score, contributions


def dominant_signal(contributions):
    order = ["GEOFENCE_MISMATCH", "VELOCITY", "PROVIDER_PATTERN", "DUPLICATE_RECEIPT"]
    best, best_val = "VELOCITY", -1.0
    for sig in order:
        if contributions.get(sig, 0.0) > best_val:
            best, best_val = sig, contributions[sig]
    return best


def create_fraud_flag(visit, score, contributions):
    flag = new_entity()
    flag.update({
        "visit_id": visit["id"],
        "claim_id": None,
        "signal": dominant_signal(contributions),
        "severity": max(1, min(10, math.ceil(score / 10) if score else 1)),
        "status": "OPEN",
    })
    STORE.fraud_flags[flag["id"]] = flag
    return flag
