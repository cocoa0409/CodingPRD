"""Business logic: calculations, recomputes, cascades, and clock sweeps."""

from datetime import timedelta
from decimal import Decimal

from db import store, mint, touch
from utils import dec, round_half_up_cents, parse_datetime_value

# ---------------------------------------------------------------------------
# Constants (from the calculation rules table)
# ---------------------------------------------------------------------------

SUBAWARD_MTDC_ALLOWANCE_CENTS = 2500000
THIRD_PARTY_CREDIT_FACTOR = Decimal("0.5")
THIRD_PARTY_CAP_OF_REQUIRED = Decimal("0.25")
ENHANCED_AMOUNT_THRESHOLD_CENTS = 25000000
ENHANCED_SURCHARGE = 15
MAX_EFFORT_PCT = Decimal("100.00")

ACTIVITY_TO_RATE_TYPE = {
    "RESEARCH_ON_CAMPUS": "ON_CAMPUS_RESEARCH",
    "RESEARCH_OFF_CAMPUS": "OFF_CAMPUS_RESEARCH",
    "INSTRUCTION": "INSTRUCTION",
    "OTHER_SPONSORED": "OTHER_SPONSORED",
}

ACTIVITY_CODES = list(ACTIVITY_TO_RATE_TYPE.keys())
RATE_TYPES = ["ON_CAMPUS_RESEARCH", "OFF_CAMPUS_RESEARCH", "INSTRUCTION", "OTHER_SPONSORED"]

EFFORT_CONTRIBUTOR_STATES = {
    "ROUTED", "INSTITUTIONALLY_APPROVED", "SUBMITTED", "JIT_REQUESTED",
    "NEGOTIATING", "AWARDED", "SETUP_COMPLETE",
}

PROPOSAL_TERMINAL_STATES = {"SETUP_COMPLETE", "WITHDRAWN", "DECLINED"}

REVIEW_VALIDITY_DEFAULTS = {
    "IRB": 365,
    "IACUC": 1095,
    "EXPORT_CONTROL": 730,
    "CONFLICT_OF_INTEREST": 365,
}

RISK_BASE = {"CURRENT": 10, "NOT_REQUIRED": 20, "MISSING": 45, "DELINQUENT": 60}

CASH_COST_SHARE_SOURCES = {"DEPARTMENT", "COLLEGE", "CENTRAL_OFFICE"}

MTDC_EXCLUDED_CATEGORIES = {"EQUIPMENT", "TUITION", "PARTICIPANT_SUPPORT"}


# ---------------------------------------------------------------------------
# Lookup helpers
# ---------------------------------------------------------------------------

def proposals_of_opportunity(opp_id):
    return [p for p in store.proposals.values() if p["opportunity_id"] == opp_id]


def proposals_of_pi(pi_id):
    return [p for p in store.proposals.values() if p["pi_id"] == pi_id]


def lines_of_proposal(pid):
    return [l for l in store.budget_lines.values() if l["proposal_id"] == pid]


def snapshots_of_proposal(pid):
    return [s for s in store.budget_snapshots.values() if s["proposal_id"] == pid]


def cost_shares_of_proposal(pid):
    return [c for c in store.cost_share_commitments.values() if c["proposal_id"] == pid]


def reviews_of_proposal(pid):
    return [r for r in store.compliance_reviews.values() if r["proposal_id"] == pid]


def subs_of_proposal(pid):
    return [s for s in store.subrecipient_commitments.values() if s["proposal_id"] == pid]


def offers_of_proposal(pid):
    return [o for o in store.negotiation_offers.values() if o["proposal_id"] == pid]


def handoff_of_proposal(pid):
    for h in store.award_handoffs.values():
        if h["proposal_id"] == pid:
            return h
    return None


# ---------------------------------------------------------------------------
# Risk scoring (subrecipient_risk_score)
# ---------------------------------------------------------------------------

def risk_score_standard(org):
    base = RISK_BASE[org["single_audit_status"]]
    findings = min(5 * org["audit_finding_count"], 25)
    foreign = 10 if org["is_foreign"] else 0
    first_time = 10 if org["first_time_subrecipient"] else 0
    return base + findings + foreign + first_time


def risk_tier_of(score):
    if score < 25:
        return "LOW"
    if score <= 49:
        return "MEDIUM"
    return "HIGH"


# ---------------------------------------------------------------------------
# PI effort (pi_effort_capacity)
# ---------------------------------------------------------------------------

def windows_overlap(a_start, a_end, b_start, b_end):
    """Half-open window overlap; adjacency does not overlap."""
    return a_start < b_end and b_start < a_end


def committed_effort_pct(pi):
    """Portfolio load: sum of pi_effort_pct over contributor-state proposals."""
    total = Decimal("0")
    for p in proposals_of_pi(pi["id"]):
        if p["status"] in EFFORT_CONTRIBUTOR_STATES:
            total += dec(p["pi_effort_pct"])
    return total


def effort_capacity_ok(candidate):
    total = dec(candidate["pi_effort_pct"])
    for other in proposals_of_pi(candidate["pi_id"]):
        if other["id"] == candidate["id"]:
            continue
        if other["status"] not in EFFORT_CONTRIBUTOR_STATES:
            continue
        if windows_overlap(candidate["_start"], candidate["_end"],
                           other["_start"], other["_end"]):
            total += dec(other["pi_effort_pct"])
    return total <= MAX_EFFORT_PCT


# ---------------------------------------------------------------------------
# Cost-share adequacy (cost_share_requirement) — pinned evaluation order
# ---------------------------------------------------------------------------

def compute_cost_share(proposal, request_total_cents=None):
    """Pure pinned-order computation; returns (total_approved, total_effective,
    is_adequate, required_min)."""
    opp = store.funding_opportunities.get(proposal["opportunity_id"])
    if request_total_cents is None:
        request_total_cents = proposal["total_request_cents"]

    if opp is None or not opp["requires_cost_share"]:
        required_min = 0
    else:
        pct = dec(opp["min_cost_share_pct_of_request"])
        required_min = round_half_up_cents(
            pct * Decimal(request_total_cents) / Decimal(100))

    cash_approved = 0
    tp_approved = 0
    total_approved = 0
    for c in cost_shares_of_proposal(proposal["id"]):
        if c["status"] != "APPROVED":
            continue
        total_approved += c["amount_cents"]
        if c["source_type"] in CASH_COST_SHARE_SOURCES:
            cash_approved += c["amount_cents"]
        elif c["source_type"] == "THIRD_PARTY_IN_KIND":
            tp_approved += c["amount_cents"]

    tp_effective = min(
        round_half_up_cents(Decimal(tp_approved) * THIRD_PARTY_CREDIT_FACTOR),
        round_half_up_cents(Decimal(required_min) * THIRD_PARTY_CAP_OF_REQUIRED),
    )
    total_effective = cash_approved + tp_effective
    return total_approved, total_effective, total_effective >= required_min, required_min


def recompute_cost_share(proposal, request_total_cents=None):
    approved, effective, adequate, _ = compute_cost_share(
        proposal, request_total_cents)
    proposal["total_approved_cost_share_cents"] = approved
    proposal["total_effective_cost_share_cents"] = effective
    proposal["is_cost_share_adequate"] = adequate


# ---------------------------------------------------------------------------
# Compliance posture
# ---------------------------------------------------------------------------

def recompute_posture(proposal):
    reviews = reviews_of_proposal(proposal["id"])
    if any(r["status"] == "DISAPPROVED" for r in reviews):
        posture = "BLOCKED"
    elif any(r["status"] in ("PENDING", "INFO_REQUESTED", "EXPIRED") for r in reviews):
        posture = "REVIEW_PENDING"
    else:
        posture = "CLEAR"
    proposal["compliance_posture"] = posture


# ---------------------------------------------------------------------------
# Rate selection and the indirect-cost calculation (indirect_cost)
# ---------------------------------------------------------------------------

def _window_covers(agreement, project_start):
    return agreement["_start"] <= project_start < agreement["_end"]


def select_rate_agreement(rate_type, project_start, basis):
    """PROVISIONAL_BASIS prefers FINAL then PROVISIONAL; FINAL_BASIS only FINAL."""
    finals = [a for a in store.fa_rate_agreements.values()
              if a["rate_type"] == rate_type and a["status"] == "FINAL"
              and _window_covers(a, project_start)]
    if finals:
        finals.sort(key=lambda a: a["_seq"])
        return finals[0], "FINAL_RATE"
    if basis == "FINAL_BASIS":
        return None, None
    provisionals = [a for a in store.fa_rate_agreements.values()
                    if a["rate_type"] == rate_type and a["status"] == "PROVISIONAL"
                    and _window_covers(a, project_start)]
    if provisionals:
        provisionals.sort(key=lambda a: a["_seq"])
        return provisionals[0], "PROVISIONAL_RATE"
    return None, None


def applied_rate(selected_rate_pct, opp):
    cap = opp["fa_rate_cap_pct"]
    if cap is None:
        return dec(selected_rate_pct)
    return min(dec(selected_rate_pct), dec(cap))


def compute_indirect(proposal, applied_rate_pct, base_portions=None):
    """Per-line indirect, rounded half up per line then summed.

    base_portions: optional pre-pinned list of (line_id, base_portion_cents)
    (used for the FINAL_BASIS recomputation at mark-ready). When omitted, the
    portions are derived from the proposal's current lines in pinned order.
    Returns (per_line_indirect, total_direct_cents, total_indirect_cents, base_cents).
    """
    rate = dec(applied_rate_pct)
    per_line = []
    total_direct = 0
    total_indirect = 0
    base_total = 0

    if base_portions is not None:
        for line_id, portion in base_portions:
            indirect = round_half_up_cents(
                Decimal(portion) * rate / Decimal(100))
            per_line.append({
                "budget_line_id": line_id,
                "base_portion_cents": portion,
                "indirect_cents": indirect,
            })
            base_total += portion
            total_indirect += indirect
        total_direct = proposal["total_direct_cents"]
        return per_line, total_direct, total_indirect, base_total

    lines = [l for l in lines_of_proposal(proposal["id"]) if not l["is_cost_share"]]
    lines.sort(key=lambda l: (l["fiscal_year"], l["created_at"], l["_seq"]))
    allowances = {}
    for line in lines:
        amount = line["amount_cents"]
        total_direct += amount
        if proposal["fa_base_type"] == "TDC":
            portion = amount
        elif line["category"] in MTDC_EXCLUDED_CATEGORIES:
            portion = 0
        elif line["category"] == "SUBAWARD":
            cid = line["subrecipient_commitment_id"]
            remaining = allowances.get(cid, SUBAWARD_MTDC_ALLOWANCE_CENTS)
            portion = min(amount, remaining)
            allowances[cid] = remaining - portion
        else:
            portion = amount
        indirect = round_half_up_cents(Decimal(portion) * rate / Decimal(100))
        per_line.append({
            "budget_line_id": line["id"],
            "base_portion_cents": portion,
            "indirect_cents": indirect,
        })
        base_total += portion
        total_indirect += indirect

    return per_line, total_direct, total_indirect, base_total


def recompute_mtdc_flags(proposal):
    """Refresh counts_toward_mtdc on every line of the proposal (MTDC rules)."""
    lines = [l for l in lines_of_proposal(proposal["id"]) if not l["is_cost_share"]]
    lines.sort(key=lambda l: (l["fiscal_year"], l["created_at"], l["_seq"]))
    allowances = {}
    flags = {}
    for line in lines:
        if line["category"] in MTDC_EXCLUDED_CATEGORIES:
            flags[line["id"]] = False
        elif line["category"] == "SUBAWARD":
            cid = line["subrecipient_commitment_id"]
            remaining = allowances.get(cid, SUBAWARD_MTDC_ALLOWANCE_CENTS)
            portion = min(line["amount_cents"], remaining)
            allowances[cid] = remaining - portion
            flags[line["id"]] = portion > 0
        else:
            flags[line["id"]] = True
    for line in lines_of_proposal(proposal["id"]):
        if line["is_cost_share"]:
            if line["category"] in MTDC_EXCLUDED_CATEGORIES:
                line["counts_toward_mtdc"] = False
            else:
                line["counts_toward_mtdc"] = True
        else:
            line["counts_toward_mtdc"] = flags.get(line["id"], True)


# ---------------------------------------------------------------------------
# Cascades
# ---------------------------------------------------------------------------

def terminal_cleanup(proposal):
    """Shared by withdrawal, declined offers, and intake closure."""
    pid = proposal["id"]
    for r in reviews_of_proposal(pid):
        if r["status"] in ("PENDING", "INFO_REQUESTED"):
            r["status"] = "CANCELLED"
            touch(r)
    for c in cost_shares_of_proposal(pid):
        if c["status"] == "PLEDGED":
            c["status"] = "WITHDRAWN"
            touch(c)
        elif c["status"] == "APPROVED":
            c["status"] = "RELEASED"
            touch(c)
    for s in subs_of_proposal(pid):
        if s["status"] in ("DRAFT", "VERIFIED", "STALE"):
            s["status"] = "VOIDED"
            touch(s)
    for o in offers_of_proposal(pid):
        if o["status"] == "PROPOSED":
            o["status"] = "VOIDED"
            touch(o)
    recompute_cost_share(proposal)
    recompute_posture(proposal)


def return_for_revision_effects(proposal):
    """Compensation for entering RETURNED_FOR_REVISION."""
    pid = proposal["id"]
    for c in cost_shares_of_proposal(pid):
        if c["status"] == "APPROVED":
            c["status"] = "RELEASED"
            touch(c)
    for s in subs_of_proposal(pid):
        if s["status"] == "VERIFIED":
            s["status"] = "STALE"
            touch(s)
    recompute_cost_share(proposal)


def bubble_handoff_blocked(proposal):
    """READY handoff falls back to BLOCKED when a review expires/is disapproved."""
    h = handoff_of_proposal(proposal["id"])
    if h is not None and h["status"] == "READY":
        h["status"] = "BLOCKED"
        h["compliance_verified"] = False
        touch(h)


# ---------------------------------------------------------------------------
# Clock sweeps
# ---------------------------------------------------------------------------

def run_clock_sweeps():
    now = store.clock
    # Intake closure: opportunities whose sponsor deadline has passed.
    for opp in store.funding_opportunities.values():
        if opp["status"] != "PUBLISHED":
            continue
        if not (opp["_sponsor_deadline_dt"] < now):
            continue
        opp["status"] = "INTAKE_CLOSED"
        touch(opp)
        for proposal in proposals_of_opportunity(opp["id"]):
            if proposal["status"] in ("DRAFT", "BUDGET_LOCKED", "ROUTED",
                                      "RETURNED_FOR_REVISION"):
                terminal_cleanup(proposal)
                proposal["status"] = "WITHDRAWN"
                touch(proposal)
    # Review expiry: APPROVED reviews whose validity has lapsed.
    for review in store.compliance_reviews.values():
        if review["status"] == "APPROVED" and review["_approved_until_dt"] is not None \
                and review["_approved_until_dt"] < now:
            review["status"] = "EXPIRED"
            touch(review)
            proposal = store.proposals.get(review["proposal_id"])
            if proposal is not None:
                recompute_posture(proposal)
                bubble_handoff_blocked(proposal)
