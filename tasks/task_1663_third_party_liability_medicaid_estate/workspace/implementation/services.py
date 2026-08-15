"""Business logic: calculations (SCAFFOLD §1.3), cascades, derived fields.

Every formula here traces to a verbatim PRD §3 sentence. All money is integer
cents; multiplicative results are rounded half-up (PRD §2.6).
"""

from datetime import timedelta
from decimal import Decimal

from db import (
    CLOCK,
    EXPENSE_CLAIMS,
    LIENS,
    NOTICES,
    POSTINGS,
    SETTLEMENTS,
    CASES,
    MEMBERS,
    new_entity,
    now_iso,
    parse_iso_z,
    touch,
)
from util import parse_date, round_half_up_cents

# --- Statutory constants (SCAFFOLD §1.3) --------------------------------------
STATUTORY_LIEN_CAP_CENTS = 250000
DEFAULT_MEDICAL_RATIO = Decimal("0.35")
COST_SHARE_CAP_PCT = Decimal("0.25")
COMM_TIER1_CAP_CENTS = 100000
COMM_TIER1_RATE = Decimal("0.10")
COMM_TIER2_WIDTH_CENTS = 100000
COMM_TIER2_RATE = Decimal("0.075")
COMM_TIER3_RATE = Decimal("0.05")
HOMESTEAD_EXEMPT_CAP_CENTS = 5000000
INCOME_LIMIT_CENTS = 3000000
ESTATE_FILING_DAYS = 365
NOTICE_DEADLINE_DAYS = 30
SOL_YEARS = 3
EPISODE_WINDOW_DAYS = 90
NEGOTIATION_FREEZE_DAYS = 14
MAX_APPEALS = 1

TERMINAL_CASE_STATUSES = {"RESOLVED", "CLOSED_NO_RECOVERY", "SOL_EXPIRED"}
ACTIVE_LIEN_STATUSES = {"FILED", "AMENDED"}
OPEN_SETTLEMENT_STATUSES = {"OFFERED", "COUNTERED"}


# --- Finders ------------------------------------------------------------------
def active_lien_for_case(case_id):
    for lien in LIENS.values():
        if lien["case_id"] == case_id and lien["status"] in ACTIVE_LIEN_STATUSES:
            return lien
    return None


def member_of_case(case):
    return MEMBERS.get(case["member_id"])


def case_of_settlement(settlement):
    return CASES.get(settlement["case_id"])


# --- Notices (PRD §2.11) -------------------------------------------------------
def create_notice(member_id, case_id, estate_case_id, notice_type):
    n = new_entity()
    n.update(
        {
            "member_id": member_id,
            "case_id": case_id,
            "estate_case_id": estate_case_id,
            "notice_type": notice_type,
            "status": "QUEUED",
            "due_date": (CLOCK.today() + timedelta(days=NOTICE_DEADLINE_DAYS)).isoformat(),
            "sent_at": None,
            "is_late": None,
        }
    )
    NOTICES[n["id"]] = n
    return n


# --- Derived-field recomputation (PRD §2.9) ------------------------------------
def recompute_case_total_paid_claims(case):
    case["total_paid_claims_cents"] = sum(
        c["paid_amount_cents"]
        for c in EXPENSE_CLAIMS.values()
        if c["case_id"] == case["id"]
    )


def recompute_lien_outstanding(lien):
    """outstanding = lien_amount - sum of POSTED postings' gross on this lien."""
    posted = sum(
        p["gross_recovery_cents"]
        for p in POSTINGS.values()
        if p["lien_id"] == lien["id"] and p["status"] == "POSTED"
    )
    lien["outstanding_cents"] = lien["lien_amount_cents"] - posted


def recompute_case_total_recovered(case):
    """Sum of gross_recovery_cents over POSTED postings of this case."""
    total = 0
    for p in POSTINGS.values():
        if p["status"] != "POSTED":
            continue
        s = SETTLEMENTS.get(p["settlement_id"])
        if s is not None and s["case_id"] == case["id"]:
            total += p["gross_recovery_cents"]
    case["total_recovered_cents"] = total


# --- Calculations --------------------------------------------------------------
def lien_perfected_amount(case):
    """§3.3: basis = sum of paid over claims dated on/after the injury;
    lien amount = min(statutory cap, basis). Integer cents, no rounding."""
    injury = parse_date(case["injury_date"])
    basis = sum(
        c["paid_amount_cents"]
        for c in EXPENSE_CLAIMS.values()
        if c["case_id"] == case["id"] and parse_date(c["service_date"]) >= injury
    )
    return min(STATUTORY_LIEN_CAP_CENTS, basis)


def settlement_recovery_amount(gross, fee_pct, costs, recovery_approach, lien_outstanding):
    """§3.4: returns (fee_amount_cents, cost_share_cents, state_recovery_cents,
    member_net_cents). Variant keyed off the member's recovery_approach."""
    fee = round_half_up_cents(Decimal(gross) * Decimal(str(fee_pct)))
    if recovery_approach == "SUBROGATION":
        # Pinned order: cost share is capped by 25% of the PRE-COST recovery.
        pre_cost_recovery = min(lien_outstanding, gross)
        cost_share = min(
            costs, round_half_up_cents(Decimal(pre_cost_recovery) * COST_SHARE_CAP_PCT)
        )
        state_recovery = pre_cost_recovery - cost_share
    else:  # REIMBURSEMENT
        net_after_fees = gross - fee - costs
        ratio_limited = round_half_up_cents(Decimal(gross) * DEFAULT_MEDICAL_RATIO)
        state_recovery = max(0, min(lien_outstanding, net_after_fees, ratio_limited))
        cost_share = 0
    member_net = gross - fee - costs - state_recovery
    return fee, cost_share, state_recovery, member_net


def contractor_commission(gross):
    """§3.5: 10% up to 100000; 7.5% of the next 100000; 5% above 200000.
    The tier products are summed and rounded half-up ONCE per posting."""
    tier1 = Decimal(min(gross, COMM_TIER1_CAP_CENTS)) * COMM_TIER1_RATE
    tier2 = (
        Decimal(min(max(gross - COMM_TIER1_CAP_CENTS, 0), COMM_TIER2_WIDTH_CENTS))
        * COMM_TIER2_RATE
    )
    tier3 = Decimal(max(gross - COMM_TIER1_CAP_CENTS - COMM_TIER2_WIDTH_CENTS, 0)) * COMM_TIER3_RATE
    return round_half_up_cents(tier1 + tier2 + tier3)


def estate_final_claim_amount(member, exempt_services_cents):
    """§3.6: final claim = max(0, lifetime_paid - POSTED TPL recoveries of the
    member's cases - exempt services)."""
    tpl_offset = 0
    for p in POSTINGS.values():
        if p["status"] != "POSTED":
            continue
        s = SETTLEMENTS.get(p["settlement_id"])
        if s is None:
            continue
        c = CASES.get(s["case_id"])
        if c is not None and c["member_id"] == member["id"]:
            tpl_offset += p["gross_recovery_cents"]
    return max(0, member["lifetime_paid_cents"] - tpl_offset - exempt_services_cents)


def hardship_reduction(waiver, estate_case):
    """§3.7: FULL -> entire outstanding; PARTIAL -> min(requested, collectible)
    where collectible = max(0, outstanding - max(0, homestead - exempt cap))."""
    if waiver["waiver_type"] == "FULL":
        return estate_case["claim_outstanding_cents"]
    exposed_equity = max(0, waiver["homestead_value_cents"] - HOMESTEAD_EXEMPT_CAP_CENTS)
    collectible = max(0, estate_case["claim_outstanding_cents"] - exposed_equity)
    return min(waiver["requested_reduction_cents"], collectible)


# --- Cascades -------------------------------------------------------------------
def fire_sol_expiry(case):
    """§2.5 lazy expiry cascade: case -> SOL_EXPIRED; open liens -> EXPIRED;
    open settlements -> REJECTED. Each affected resource is touched."""
    case["status"] = "SOL_EXPIRED"
    touch(case)
    for lien in LIENS.values():
        if lien["case_id"] == case["id"] and lien["status"] in ACTIVE_LIEN_STATUSES:
            lien["status"] = "EXPIRED"
            touch(lien)
    for s in SETTLEMENTS.values():
        if s["case_id"] == case["id"] and s["status"] in OPEN_SETTLEMENT_STATUSES:
            s["status"] = "REJECTED"
            touch(s)


def sol_expired(case):
    """Strictly-greater calendar-date comparison: expiry only AFTER sol_date."""
    return CLOCK.today() > parse_date(case["sol_date"])


def negotiation_frozen(case_id):
    """§3.3 freeze: for every OFFERED/COUNTERED settlement on the case the
    current timestamp must be strictly later than updated_at + 14 days; the
    interval is closed — exactly +14 days is still frozen."""
    now = CLOCK.now()
    for s in SETTLEMENTS.values():
        if s["case_id"] == case_id and s["status"] in OPEN_SETTLEMENT_STATUSES:
            freeze_end = parse_iso_z(s["updated_at"]) + timedelta(days=NEGOTIATION_FREEZE_DAYS)
            if now <= freeze_end:
                return True
    return False
