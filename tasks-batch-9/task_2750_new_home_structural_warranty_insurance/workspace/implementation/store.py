"""Row lookup, derived-aggregate recompute and the two cascades.

Everything here is pure in-memory bookkeeping over the dicts in `db`.
"""

from datetime import timedelta

import calc
import db
from errors import err

# ---------------------------------------------------------------------------
# Path / foreign-key resolution (PRD 2.6).  Each raises the catalogued 404.
# ---------------------------------------------------------------------------
_NOT_FOUND = {
    "builder": "ERR_BUILDER_NOT_FOUND",
    "homeowner": "ERR_HOMEOWNER_NOT_FOUND",
    "neutral": "ERR_NEUTRAL_NOT_FOUND",
    "policy": "ERR_POLICY_NOT_FOUND",
    "coverage_term": "ERR_COVERAGE_TERM_NOT_FOUND",
    "transfer": "ERR_TRANSFER_NOT_FOUND",
    "claim": "ERR_CLAIM_NOT_FOUND",
    "reserve_entry": "ERR_RESERVE_ENTRY_NOT_FOUND",
    "escalation_case": "ERR_ESCALATION_CASE_NOT_FOUND",
}


def _resolve(table, kind, row_id):
    row = table.get(row_id) if isinstance(row_id, str) else None
    if row is None:
        raise err(_NOT_FOUND[kind], "%s '%s' does not exist" % (kind, row_id))
    return row


def get_builder(row_id):
    return _resolve(db.builders, "builder", row_id)


def get_homeowner(row_id):
    return _resolve(db.homeowners, "homeowner", row_id)


def get_neutral(row_id):
    return _resolve(db.neutrals, "neutral", row_id)


def get_policy(row_id):
    return _resolve(db.policies, "policy", row_id)


def get_term(row_id):
    return _resolve(db.coverage_terms, "coverage_term", row_id)


def get_transfer(row_id):
    return _resolve(db.transfers, "transfer", row_id)


def get_claim(row_id):
    return _resolve(db.claims, "claim", row_id)


def get_reserve_entry(row_id):
    return _resolve(db.reserve_entries, "reserve_entry", row_id)


def get_case(row_id):
    return _resolve(db.escalation_cases, "escalation_case", row_id)


# ---------------------------------------------------------------------------
# Collection views, always in insertion (created_at) order.
# ---------------------------------------------------------------------------
def _ordered(table):
    return sorted(table.values(), key=db.sort_key_created)


def all_rows(table):
    return _ordered(table)


def policies_of_builder(builder_id):
    return [p for p in _ordered(db.policies) if p["builder_id"] == builder_id]


def terms_of_policy(policy_id):
    return [t for t in _ordered(db.coverage_terms) if t["policy_id"] == policy_id]


def transfers_of_policy(policy_id):
    return [t for t in _ordered(db.transfers) if t["policy_id"] == policy_id]


def claims_of_policy(policy_id):
    return [c for c in _ordered(db.claims) if c["policy_id"] == policy_id]


def claims_of_term(term_id):
    return [c for c in _ordered(db.claims) if c["coverage_term_id"] == term_id]


def claims_of_builder(builder_id):
    ids = set(p["id"] for p in db.policies.values() if p["builder_id"] == builder_id)
    return [c for c in _ordered(db.claims) if c["policy_id"] in ids]


def assessments_of_claim(claim_id):
    return [a for a in _ordered(db.assessments) if a["claim_id"] == claim_id]


def entries_of_claim(claim_id):
    return [e for e in _ordered(db.reserve_entries) if e["claim_id"] == claim_id]


def cases_of_claim(claim_id):
    return [c for c in _ordered(db.escalation_cases) if c["claim_id"] == claim_id]


def cases_of_neutral(neutral_id):
    return [c for c in _ordered(db.escalation_cases) if c["neutral_id"] == neutral_id]


def base_structural_term(policy_id):
    for term in terms_of_policy(policy_id):
        if term["term_kind"] == "BASE" and term["coverage_type"] == "STRUCTURAL":
            return term
    return None


def builder_of_claim(claim):
    return db.builders.get(db.policies[claim["policy_id"]]["builder_id"])


def term_of_claim(claim):
    return db.coverage_terms.get(claim["coverage_term_id"])


def term_sort_key(term):
    return (0 if term["term_kind"] == "BASE" else 1, term["start_date"],
            term["created_at"], term["_seq"])


# ---------------------------------------------------------------------------
# calculations.builder_loss_ratio -- always recomputed from scratch.
# ---------------------------------------------------------------------------
DENOMINATOR_COVERAGE_STATES = ("ACTIVE", "EXPIRED")


def recompute_builder(builder):
    if builder is None:
        return None
    earned = 0
    for policy in policies_of_builder(builder["id"]):
        if (policy["coverage_status"] in DENOMINATOR_COVERAGE_STATES
                and policy["premium_status"] == "PAID"):
            earned += policy["premium_cents"]
    incurred = 0
    for claim in claims_of_builder(builder["id"]):
        if claim["obligor"] == "INSURER":
            incurred += claim["reserve_cents"] + claim["paid_cents"]
    builder["earned_premium_cents"] = earned
    builder["incurred_loss_cents"] = incurred
    ratio = calc.loss_ratio_of(incurred, earned)
    builder["loss_ratio"] = ratio
    builder["monitoring_posture"] = "OPEN" if earned == 0 else calc.posture_for(ratio)
    return builder


def enrolled_policy_count(builder_id):
    """Effective home volume of the renewal_reassessment variant."""
    return sum(1 for p in policies_of_builder(builder_id)
               if p["coverage_status"] in DENOMINATOR_COVERAGE_STATES)


def open_claim_count(builder_id):
    return sum(1 for c in claims_of_builder(builder_id)
               if c["status"] not in calc.CLAIM_TERMINAL_STATES)


# ---------------------------------------------------------------------------
# The reserve journal.
# ---------------------------------------------------------------------------
def append_entry(claim, entry_type, amount_cents, recorded_by_user_id,
                 memo=None, reversed_entry_id=None):
    """Append one journal row.  Call AFTER the claim balances have moved: the
    two balance stamps capture the claim as the entry left it."""
    row = {
        "claim_id": claim["id"],
        "entry_type": entry_type,
        "amount_cents": amount_cents,
        "reversed_entry_id": reversed_entry_id,
        "balance_after_reserve_cents": claim["reserve_cents"],
        "balance_after_paid_cents": claim["paid_cents"],
        "memo": memo,
        "recorded_by_user_id": recorded_by_user_id,
    }
    db.stamp_create(row, versioned=False)
    db.reserve_entries[row["id"]] = row
    return row


def release_reserve(claim, recorded_by_user_id):
    """Give the whole reserve back; incurred_authorized_cents never moves."""
    amount = claim["reserve_cents"]
    claim["released_cents"] += amount
    claim["reserve_cents"] = 0
    if amount >= 1:
        append_entry(claim, "RELEASE", amount, recorded_by_user_id)
    return amount


# ---------------------------------------------------------------------------
# calculations.claim_net_payable applied to a claim row.
# ---------------------------------------------------------------------------
def apply_waterfall(claim, variant):
    term = term_of_claim(claim)
    remaining = term["remaining_limit_cents"] if term else 0
    figures = calc.settlement_waterfall(
        claim["claimed_amount_cents"], claim["substantiation_ratio"],
        claim["designated_structural"], variant, remaining,
    )
    claim.update(figures)
    return figures


def establish_reserve(claim):
    """insurer-backed arm: the net payable becomes the reserve."""
    net = claim["net_payable_cents"]
    claim["incurred_authorized_cents"] = (claim["paid_cents"]
                                         + claim["released_cents"] + net)
    claim["reserve_cents"] = net


def authorize_amount(claim, amount_cents):
    """Settlement / award authorisation: reserve is overwritten, not added to."""
    claim["incurred_authorized_cents"] = (claim["paid_cents"]
                                         + claim["released_cents"] + amount_cents)
    claim["reserve_cents"] = amount_cents


def join_insurer_arm(claim):
    """The REFUSE_OBLIGATION join and cascade links 1-2 share this body."""
    claim["obligor"] = "INSURER"
    claim["status"] = "INSURER_ADJUDICATION"
    apply_waterfall(claim, "insurer")
    establish_reserve(claim)


# ---------------------------------------------------------------------------
# Builder-default cascade (PRD 3.2).
# ---------------------------------------------------------------------------
def builder_default_cascade(builder):
    for claim in claims_of_builder(builder["id"]):
        if claim["status"] == "BUILDER_OBLIGATION_NOTICE":
            join_insurer_arm(claim)            # links 1 and 2
            db.mark(claim)
    recompute_builder(builder)                 # link 3
    for policy in policies_of_builder(builder["id"]):
        if policy["coverage_status"] == "PENDING_ENROLLMENT":
            policy["coverage_status"] = "VOIDED"
            db.mark(policy)
            for term in terms_of_policy(policy["id"]):
                if term["status"] == "OPEN":
                    term["status"] = "ELAPSED"
                    db.mark(term)


# ---------------------------------------------------------------------------
# Limit-exhaustion cascade (PRD 3.8), links 4, 5 and 6.
# ---------------------------------------------------------------------------
SUSPENDABLE_STATES = ("UNDER_INVESTIGATION", "BUILDER_OBLIGATION_NOTICE",
                      "INSURER_ADJUDICATION", "APPROVED")


def limit_exhaustion_cascade(term, paying_claim, builder, recorded_by_user_id):
    for claim in claims_of_term(term["id"]):
        if claim is paying_claim:
            continue
        if claim["status"] in SUSPENDABLE_STATES:
            claim["status"] = "SUSPENDED_NO_LIMIT"      # link 4
            release_reserve(claim, recorded_by_user_id)
            db.mark(claim)
    recompute_builder(builder)                          # link 5
    if builder is not None and builder["monitoring_posture"] == "FROZEN":
        for policy in policies_of_builder(builder["id"]):    # link 6
            if policy["coverage_status"] == "PENDING_ENROLLMENT":
                policy["enrollment_hold"] = True
                db.mark(policy)


# ---------------------------------------------------------------------------
# The epoch sweep of POST /_clock/set_current_utc (PRD 3.4).
# ---------------------------------------------------------------------------
def epoch_sweep(new_date_str):
    elapsed_terms = 0
    for term in _ordered(db.coverage_terms):
        if term["status"] == "OPEN" and term["end_date"] < new_date_str:
            term["status"] = "ELAPSED"
            db.mark(term)
            elapsed_terms += 1
    expired_policies = 0
    for policy in _ordered(db.policies):
        if policy["coverage_status"] != "ACTIVE":
            continue
        structural = base_structural_term(policy["id"])
        if structural is not None and structural["end_date"] < new_date_str:
            policy["coverage_status"] = "EXPIRED"
            db.mark(policy)
            expired_policies += 1
    return expired_policies, elapsed_terms


# ---------------------------------------------------------------------------
# Escalation deadlines and the neutral calendar.
# ---------------------------------------------------------------------------
def deadline_from(anchor_date, days):
    return anchor_date + timedelta(days=days)


def neutral_window_conflict(neutral_id, window_start, window_end, exclude_case_id=None):
    """The requested half-open window, widened by the turnaround allowance on
    both sides, must be clear of every other window on this neutral."""
    pad = timedelta(minutes=calc.NEUTRAL_TURNAROUND_MINUTES)
    lo = window_start - pad
    hi = window_end + pad
    for case in cases_of_neutral(neutral_id):
        if exclude_case_id is not None and case["id"] == exclude_case_id:
            continue
        if lo < case["_window_end"] and case["_window_start"] < hi:
            return True
    return False
