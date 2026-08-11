"""Calculation rules (SCAFFOLD §1.3). All money is integer cents; every
fractional result is rounded half-up, in the pinned orders of PRD §2.6."""
from datetime import timedelta
from decimal import Decimal

from db import store
from util import money_ratio, round_half_up

CURE_PERIOD_DAYS = 14
REDEMPTION_PERIOD_DAYS = 10
ACCEPT_WINDOW_DAYS = 2
PROPERTY_RETENTION_DAYS = 15
DEFICIENCY_NOTICE_DAYS = 30

GRADE_MULTIPLIERS = {
    "EXCELLENT": Decimal("0.85"),
    "GOOD": Decimal("0.75"),
    "FAIR": Decimal("0.60"),
    "POOR": Decimal("0.45"),
}
RESERVE_FLOOR_RATIO = Decimal("0.50")
RELIST_MARKDOWN = Decimal("0.95")
EST_RECOVERY_RATIO = Decimal("0.9")

BREACH_PENALTY = 25
EXPIRED_PENALTY = 10
FAST_SECURE_BONUS = 2
FAST_SECURE_DAYS = 14
SUSPENSION_THRESHOLD = 40
ROLLING_WINDOW_DAYS = 90

COST_KINDS = {"COST_REPO_FEE", "COST_STORAGE", "COST_TRANSPORT", "COST_KEY",
              "COST_OTHER", "ADJUSTMENT"}
MANUAL_LEDGER_KINDS = COST_KINDS  # manual POST accepts only these


def case_entries(case_id):
    rows = [e for e in store.ledger_entries.values()
            if e["recovery_case_id"] == case_id]
    rows.sort(key=lambda e: (e["created_at"], e["_seq"]))
    return rows


def recovery_costs_total(case_id):
    """Ledger cost total: COST_*/ADJUSTMENT sums minus reversals of those."""
    entries = case_entries(case_id)
    total = sum(e["amount_cents"] for e in entries if e["kind"] in COST_KINDS)
    reversal_total = 0
    for e in entries:
        if e["kind"] != "REVERSAL":
            continue
        target = store.ledger_entries.get(e.get("reverses_entry_id") or "")
        if target is not None and target["kind"] in COST_KINDS:
            reversal_total += e["amount_cents"]
    return total - reversal_total


def total_outstanding(loan):
    return (loan["principal_balance_cents"] + loan["accrued_interest_cents"]
            + loan["late_fees_cents"] - loan["paid_to_date_cents"])


def per_diem_cents(loan):
    """Pinned order: daily interest rounded half-up to cents FIRST."""
    raw = (Decimal(loan["principal_balance_cents"]) * Decimal(loan["apr_bps"])
           / Decimal(10000) / Decimal(365))
    return round_half_up(raw)


def interest_days(start_dt, end_dt):
    """Calendar days between two UTC dates (end - start)."""
    return (end_dt.date() - start_dt.date()).days


def cure_amount_cents(case, loan):
    return (loan["missed_installments"] * loan["monthly_payment_cents"]
            + loan["late_fees_cents"]
            + recovery_costs_total(case["id"]))


def quote_amount(case, loan, quote_type, valid_until):
    """Returns (quoted_amount_cents, per_diem_cents_snapshot)."""
    costs = recovery_costs_total(case["id"])
    if quote_type == "REDEMPTION":
        per_diem = per_diem_cents(loan)
        days = interest_days(case["created_at"], valid_until)
        return total_outstanding(loan) + per_diem * days + costs, per_diem
    # REINSTATEMENT: arrears + costs only; no principal, no per-diem.
    amount = (loan["missed_installments"] * loan["monthly_payment_cents"]
              + loan["late_fees_cents"] + costs)
    return amount, 0


def grade_adjusted_appraisal(case):
    return round_half_up(Decimal(case["trade_in_value_cents"])
                         * GRADE_MULTIPLIERS[case["condition_grade"]])


def reserve_price(case, loan):
    """Initial reserve; each component rounded independently before min/max."""
    grade_adjusted = grade_adjusted_appraisal(case)
    payoff_estimate = total_outstanding(loan) + recovery_costs_total(case["id"])
    floor_value = round_half_up(RESERVE_FLOOR_RATIO * Decimal(payoff_estimate))
    return min(grade_adjusted, max(case["auction_guide_low_cents"], floor_value))


def relist_reserve(prior_reserve_cents):
    return round_half_up(Decimal(prior_reserve_cents) * RELIST_MARKDOWN)


def sale_fee_lines(auction_house, gross_sale_cents):
    """Each fee line rounded to cents individually BEFORE subtraction."""
    auction_fee = round_half_up(
        Decimal(gross_sale_cents) * Decimal(auction_house["fee_bps"]) / Decimal(10000))
    transport_fee = auction_house["transport_fee_cents"]
    net = gross_sale_cents - auction_fee - transport_fee
    return auction_fee, transport_fee, net


def case_consignments(case_id):
    rows = [c for c in store.consignments.values()
            if c["recovery_case_id"] == case_id]
    rows.sort(key=lambda c: c["consignment_seq"])
    return rows


def case_certified_sale(case_id):
    """The case's CERTIFIED SaleRecord (via its consignments), or None."""
    consignment_ids = {c["id"] for c in case_consignments(case_id)}
    for s in store.sale_records.values():
        if s["consignment_id"] in consignment_ids and s["status"] == "CERTIFIED":
            return s
    return None


def provisional_proceeds(case):
    """PROVISIONAL proceeds: latest consignment reserve x 0.9, else the
    grade-adjusted appraisal x 0.9. Returns (proceeds_cents, basis)."""
    consignments = case_consignments(case["id"])
    if consignments:
        latest = consignments[-1]  # greatest consignment_seq; tie-free key
        return (round_half_up(Decimal(latest["reserve_price_cents"])
                              * EST_RECOVERY_RATIO),
                "consignment_reserve")
    return (round_half_up(Decimal(grade_adjusted_appraisal(case))
                          * EST_RECOVERY_RATIO),
            "grade_adjusted_appraisal")


def deficiency_amounts(case, loan, variant):
    """Shared waterfall skeleton; variants differ only in proceeds / as-of.

    Returns (deficiency_cents, surplus_cents). For PROVISIONAL also returns
    basis via provisional_proceeds; FINAL uses the CERTIFIED sale record.
    """
    per_diem = per_diem_cents(loan)
    if variant == "FINAL":
        sale = case_certified_sale(case["id"])
        proceeds = sale["net_proceeds_cents"]
        as_of = case["sold_at"]
    else:
        proceeds, _basis = provisional_proceeds(case)
        as_of = store.clock
    days = interest_days(case["created_at"], as_of)
    payoff_as_of = total_outstanding(loan) + per_diem * days
    total_owed = payoff_as_of + recovery_costs_total(case["id"])
    return max(0, total_owed - proceeds), max(0, proceeds - total_owed)


def agent_assignments(agent_id):
    rows = [a for a in store.repo_assignments.values()
            if a["agent_id"] == agent_id]
    rows.sort(key=lambda a: (a["created_at"], a["_seq"]))
    return rows


def agent_scores(agent_id):
    """(lifetime, rolling_90d) — same weights; rolling restricts to rows whose
    created_at >= now - 90 days (logical clock)."""
    cutoff = store.clock - timedelta(days=ROLLING_WINDOW_DAYS)
    lifetime = 100
    rolling = 100
    for a in agent_assignments(agent_id):
        if a["status"] == "BREACHED_PEACE":
            delta = -BREACH_PENALTY
        elif a["status"] == "EXPIRED":
            delta = -EXPIRED_PENALTY
        elif a["status"] == "SECURED" and a.get("secured_fast"):
            delta = FAST_SECURE_BONUS
        else:
            delta = 0
        lifetime += delta
        if a["created_at"] >= cutoff:
            rolling += delta
    clamp = lambda v: max(0, min(100, v))
    return clamp(lifetime), clamp(rolling)


def live_assignment_count(agent_id):
    return sum(1 for a in store.repo_assignments.values()
               if a["agent_id"] == agent_id
               and a["status"] in ("ASSIGNED", "ACCEPTED"))


def overlaps_half_open(a_start, a_end, b_start, b_end):
    """[a_start, a_end) vs [b_start, b_end): adjacency is NOT overlap."""
    return a_start < b_end and b_start < a_end


def overlaps_closed(a_start, a_end, b_start, b_end):
    """[a_start, a_end] vs [b_start, b_end]: touching counts as conflict."""
    return a_start <= b_end and b_start <= a_end


def window_conflicts(agent_id, start, end):
    """Any half-open overlap with the agent's live assignment windows?"""
    for a in store.repo_assignments.values():
        if a["agent_id"] != agent_id:
            continue
        if a["status"] not in ("ASSIGNED", "ACCEPTED"):
            continue
        if overlaps_half_open(start, end, a["field_window_start"], a["field_window_end"]):
            return True
    return False


def auto_select_agent(case, loan, window_start, window_end):
    """agent_auto_select: eligible pool ranked by rolling score desc, then
    agent created_at asc (registration order breaks remaining ties)."""
    eligible = []
    for agent in store.repo_agents.values():
        if agent["status"] != "ACTIVE":
            continue
        if loan["governing_state_code"] not in agent["licensed_state_codes"]:
            continue
        if live_assignment_count(agent["id"]) >= agent["max_active_assignments"]:
            continue
        if window_conflicts(agent["id"], window_start, window_end):
            continue
        breached_here = any(
            a["recovery_case_id"] == case["id"] and a["status"] == "BREACHED_PEACE"
            for a in agent_assignments(agent["id"]))
        if breached_here:
            continue
        eligible.append(agent)
    if not eligible:
        return None
    eligible.sort(key=lambda ag: (-agent_scores(ag["id"])[1],
                                  ag["created_at"], ag["_seq"]))
    return eligible[0]
