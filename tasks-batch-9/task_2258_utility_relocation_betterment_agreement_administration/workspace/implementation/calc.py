"""Every derived figure in the system (SCAFFOLD section 1.3 / PRD sections 2.11,
3.4, 3.5, 3.7, 3.8, 3.9).

Aggregates that are pure functions of other rows are recomputed on demand so the
conservation invariants of PRD 2.8 hold by construction.
"""
from datetime import timedelta
from decimal import Decimal

import db as store
from util import days_between, ceil_days, dec, rhu_int, round_half_up

# ---- constants ---------------------------------------------------------------
DEPTH_TOLERANCE_IN = 6
PRIOR_OCCUPANCY_CREDIT_PCT = 10
SUBSEQUENT_OCCUPANCY_PENALTY_PCT = 20
PUBLIC_AGENCY_CREDIT_PCT = 25
UNSUPPORTED_CLAIM_PENALTY_PCT = 15
FIELD_CONTRADICTION_PENALTY_PCT = 45

BETTERMENT_RATIO_THRESHOLD = Decimal(1)
RATIO_DECIMALS = 6

TIER_1_CEILING_CENTS = 5000000
TIER_2_CEILING_CENTS = 50000000

CONTRACTUAL_FLOAT_DAYS = 5
CLEARANCE_WARNING_DAYS = 60
MOBILIZATION_BUFFER_DAYS = 3
DELINQUENCY_HOLD_THRESHOLD = 2
PLAN_REVISION_LIMIT = 3
APPEAL_LIMIT = 1

BASE_BY_OCCUPANCY = {
    "FEE_SIMPLE": 100,
    "PRIVATE_EASEMENT": 100,
    "PERMIT": 0,
    "UNDOCUMENTED": 0,
}

OWNER_RESPONSIBILITY_BY_CAUSE = {
    "UTILITY_OWNER": 100,
    "UTILITY_OWNER_PERMIT_WAIT": 60,
    "THIRD_PARTY": 50,
    "STATE_PERMIT_DELAY": 0,
}


# ================================================== prior rights =============

def contradicts_record(quality_level, measured_depth_in, facility_depth_in):
    if quality_level != "QL_A":
        return False
    return abs(measured_depth_in - facility_depth_in) > DEPTH_TOLERANCE_IN


def evidence_variant_for_facility(facility_id):
    """Step 1: a QL_A investigation that contradicts the record forces FIELD_BASIS."""
    for inv in store.investigations_of_facility(facility_id):
        if inv["quality_level"] == "QL_A" and inv.get("contradicts_record"):
            return "FIELD_BASIS"
    return "RECORD_BASIS"


def prior_rights_state_share(variant, facility, owner, project, claimed_basis):
    """Steps 2-4.  Integer percent, clamped into 0..100, never rounded."""
    basis = facility["occupancy_basis"]
    if basis == "FRANCHISE":
        base = 0 if owner.get("is_public_agency") else 50
    else:
        base = BASE_BY_OCCUPANCY.get(basis, 0)

    adj = 0
    if variant == "RECORD_BASIS" and facility["installed_year"] < project["row_acquisition_year"]:
        adj += PRIOR_OCCUPANCY_CREDIT_PCT
    if facility["installed_year"] >= project["row_acquisition_year"]:
        adj -= SUBSEQUENT_OCCUPANCY_PENALTY_PCT
    if owner.get("is_public_agency"):
        adj += PUBLIC_AGENCY_CREDIT_PCT
    if claimed_basis != basis:
        adj -= UNSUPPORTED_CLAIM_PENALTY_PCT
    if variant == "FIELD_BASIS":
        adj -= FIELD_CONTRADICTION_PENALTY_PCT

    return min(100, max(0, base + adj))


def determination_shares(determination, force_variant=None):
    """Returns (variant, provisional_record_basis_share, share_under_variant)."""
    conflict = store.db.conflicts.get(determination["conflict_id"])
    facility = store.facility_of_conflict(conflict)
    owner = store.db.owners.get(facility["owner_id"])
    project = store.project_of_conflict(conflict)
    variant = force_variant or evidence_variant_for_facility(facility["id"])
    claimed = determination["claimed_basis"]
    provisional = prior_rights_state_share("RECORD_BASIS", facility, owner, project, claimed)
    current = prior_rights_state_share(variant, facility, owner, project, claimed)
    return variant, provisional, current


# ================================================== betterment ===============

def betterment_fields(estimated_cost_cents, replacement_in_kind_cost_cents,
                      proposed_capacity_ratio):
    """Steps 1-4.  Returns (betterment_ratio Decimal(6dp), betterment_amount_cents)."""
    estimate = dec(estimated_cost_cents)
    in_kind = dec(replacement_in_kind_cost_cents)
    ratio_in = dec(proposed_capacity_ratio)

    scope = (estimate - in_kind) / estimate if estimate != 0 else Decimal(0)
    if ratio_in <= BETTERMENT_RATIO_THRESHOLD:
        capacity = Decimal(0)
    else:
        capacity = (ratio_in - BETTERMENT_RATIO_THRESHOLD) / ratio_in

    combined = scope + (Decimal(1) - scope) * capacity
    ratio = round_half_up(combined, RATIO_DECIMALS)
    if ratio > Decimal(1):
        ratio = Decimal(1)
    if ratio < Decimal(0):
        ratio = Decimal(0)
    ratio = round_half_up(ratio, RATIO_DECIMALS)
    amount = rhu_int(estimate * ratio)
    return ratio, amount


def per_line_betterment_credit(included_documents, betterment_ratio):
    """Step 5: each line rounded before summing, salvage credits signed negative."""
    ratio = dec(betterment_ratio)
    total = 0
    for doc in included_documents:
        part = rhu_int(dec(doc["amount_cents"]) * ratio)
        total += -part if doc["doc_type"] == "CREDIT_SALVAGE" else part
    return total


# ================================================== eligible cost ============

def _document_sort_key(doc):
    return (doc["_incurred_on_dt"], doc["created_at"], doc["_seq"])


def actual_basis_accrual(agreement):
    """Chronological accrual with whole-document exclusion at the ceiling.

    Returns (eligible_cost_cents, included_documents, excluded_documents)."""
    candidates = [d for d in store.documents_of_agreement(agreement["id"])
                  if d["review_status"] == "ACCEPTED" and d["doc_type"] != "INDIRECT"]
    candidates.sort(key=_document_sort_key)

    running = 0
    included = []
    excluded = []
    ceiling = agreement["not_to_exceed_cents"]
    for doc in candidates:
        signed = -doc["amount_cents"] if doc["doc_type"] == "CREDIT_SALVAGE" else doc["amount_cents"]
        candidate = running + signed
        if candidate > ceiling:
            excluded.append(doc)
            continue
        running = candidate
        included.append(doc)
    return running, included, excluded


def settlement_figures(agreement, cost_basis=None):
    """The nine ordered settlement figures.

    Returns (figures dict, included_documents, excluded_documents)."""
    basis = cost_basis or agreement["cost_basis"]
    plan = store.plan_of_agreement(agreement)
    conflict = store.conflict_of_plan(plan) if plan is not None else None
    owner = store.db.owners.get(agreement["owner_id"])

    if basis == "ESTIMATE_BASIS":
        direct = plan["estimated_cost_cents"] if plan is not None else 0
        credit = plan["betterment_amount_cents"] if plan is not None else 0
        included = []
        excluded = []
    else:
        direct, included, excluded = actual_basis_accrual(agreement)
        ratio = plan["betterment_ratio"] if plan is not None else Decimal(0)
        credit = per_line_betterment_credit(included, ratio)

    rate = owner["_rate_dec"] if owner is not None else Decimal(0)
    indirect = rhu_int(dec(direct) * dec(rate) / Decimal(100))
    gross = direct + indirect
    net = max(0, gross - credit)

    if net <= TIER_1_CEILING_CENTS:
        tier = 100
    elif net <= TIER_2_CEILING_CENTS:
        tier = 95
    else:
        tier = 90

    share_pct = 0
    if conflict is not None and conflict.get("state_share_pct") is not None:
        share_pct = conflict["state_share_pct"]

    uncapped = rhu_int(dec(net) * dec(share_pct) / Decimal(100) * dec(tier) / Decimal(100))
    state_share = min(uncapped, agreement["not_to_exceed_cents"])
    owner_share = net - state_share

    figures = {
        "eligible_cost_cents": direct,
        "indirect_cost_cents": indirect,
        "betterment_credit_cents": credit,
        "net_allowable_cents": net,
        "participation_tier_pct": tier,
        "state_share_cents": state_share,
        "owner_share_cents": owner_share,
    }
    return figures, included, excluded


def apply_settlement_figures(agreement, cost_basis=None):
    figures, included, excluded = settlement_figures(agreement, cost_basis)
    agreement.update(figures)
    return figures, included, excluded


def indirect_loaded_estimate(plan, owner):
    """Rung 28 floor: plan estimate loaded with the owner's audited indirect rate."""
    rate = owner["_rate_dec"]
    return rhu_int(dec(plan["estimated_cost_cents"]) * (Decimal(1) + dec(rate) / Decimal(100)))


# ================================================== project aggregates =======

def project_open_conflict_count(project):
    return len([c for c in store.conflicts_of_project(project["id"])
                if c["status"] != "CLEARED"])


def governing_plan(conflict_id):
    plans = [p for p in store.plans_of_conflict(conflict_id) if p["status"] != "SUPERSEDED"]
    if not plans:
        return None
    return max(plans, key=lambda p: (p["created_at"], p["_seq"]))


def project_state_liability(project):
    total = 0
    for conflict in store.conflicts_of_project(project["id"]):
        if conflict["status"] == "CLEARED":
            continue
        plan = governing_plan(conflict["id"])
        if plan is None:
            continue
        participating = max(0, plan["estimated_cost_cents"] - plan["betterment_amount_cents"])
        share = conflict.get("state_share_pct") or 0
        total += rhu_int(dec(participating) * dec(share) / Decimal(100))
    return total


def project_committed_ledger(project):
    return sum(a["state_share_cents"] for a in store.agreements_of_project(project["id"])
               if a["execution_status"] == "EXECUTED")


def project_aggregate_compensable_delay_days(project):
    return sum(k["compensable_days"] for k in store.claims_of_project(project["id"])
               if k["status"] == "ALLOCATED")


def clearance_posture(project):
    liability = project_state_liability(project)
    ledger = project_committed_ledger(project)
    if max(liability, ledger) > project["reimbursement_authority_cents"]:
        return "FUNDING_BLOCKED"

    conflicts = store.conflicts_of_project(project["id"])
    if any(c["status"] == "IDENTIFIED" for c in conflicts):
        return "AT_RISK"
    horizon = store.db.clock + timedelta(days=CLEARANCE_WARNING_DAYS)
    for commitment in store.commitments_of_project(project["id"]):
        if commitment["status"] in ("COMMITTED", "IN_PROGRESS") \
                and commitment["_window_end_dt"] <= horizon:
            return "AT_RISK"

    if not conflicts or any(c["status"] != "CLEARED" for c in conflicts):
        return "CLEARANCE_PENDING"
    return "CLEAR"


def untriaged_conflict_count(project):
    return len([c for c in store.conflicts_of_project(project["id"])
                if c["status"] == "IDENTIFIED"])


def overdue_commitment_count(project):
    now = store.db.clock
    return len([c for c in store.commitments_of_project(project["id"])
                if c["status"] in ("COMMITTED", "IN_PROGRESS") and c["_window_end_dt"] < now])


def at_risk_commitment_count(project):
    horizon = store.db.clock + timedelta(days=CLEARANCE_WARNING_DAYS)
    return len([c for c in store.commitments_of_project(project["id"])
                if c["status"] in ("COMMITTED", "IN_PROGRESS") and c["_window_end_dt"] <= horizon])


# ================================================== owner aggregates =========

def owner_open_commitment_days(owner):
    total = 0
    for commitment in store.commitments_of_owner(owner["id"]):
        if commitment["status"] in ("COMMITTED", "IN_PROGRESS"):
            total += days_between(commitment["_window_start_dt"], commitment["_window_end_dt"])
    return total


def owner_assessed_delay_liability(owner):
    total = 0
    for claim in store.ordered(store.db.claims):
        if claim["status"] != "ALLOCATED":
            continue
        commitment = store.db.commitments.get(claim["commitment_id"])
        if commitment is not None and commitment["owner_id"] == owner["id"]:
            total += claim["allocated_to_owner_cents"]
    return total


# ================================================== slot occupancy ===========

def slot_occupant_count(slot):
    return len([c for c in store.commitments_of_slot(slot["id"])
                if c["status"] in ("COMMITTED", "IN_PROGRESS")])


def slot_status(slot):
    return "FULL" if slot_occupant_count(slot) >= slot["max_occupants"] else "OPEN"


# ================================================== commitments ==============

def window_days_overlap(new_start, new_end, existing_start, existing_end):
    """Buffered collision test (PRD 3.7): 3 mobilisation days added to each end."""
    buffer_ = timedelta(days=MOBILIZATION_BUFFER_DAYS)
    return new_start < existing_end + buffer_ and existing_start < new_end + buffer_


def late_days_for(actual_complete_dt, window_end_dt):
    if actual_complete_dt <= window_end_dt:
        return 0
    return max(0, ceil_days(actual_complete_dt - window_end_dt))


# ================================================== delay claims =============

def claim_compensable_days(commitment_late_days, claimed_days):
    net_late = max(0, commitment_late_days - CONTRACTUAL_FLOAT_DAYS)
    return min(net_late, claimed_days)


def claim_daily_rate(claimed_amount_cents, claimed_days, contract_daily_overhead_cents):
    implied = rhu_int(dec(claimed_amount_cents) / dec(claimed_days))
    return min(implied, contract_daily_overhead_cents)


def claim_allocation(compensable_days, daily_rate_cents, delay_cause):
    gross = compensable_days * daily_rate_cents
    owner_pct = OWNER_RESPONSIBILITY_BY_CAUSE[delay_cause]
    to_owner = rhu_int(dec(gross) * dec(owner_pct) / Decimal(100))
    to_state = gross - to_owner
    return to_owner, to_state
