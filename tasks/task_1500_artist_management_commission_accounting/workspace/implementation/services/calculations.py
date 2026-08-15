"""Calculation rules per scaffold Section 1.3: commission resolution, recoupment
waterfall, statement generation, approval routing, evaluation scoring, audit cost
allocation."""
from datetime import timedelta

from db import db
from errors import raise_error, ERR_NO_RATE_SCHEDULE
from util import (
    add_months,
    floor_div_int,
    parse_date,
    parse_datetime,
    round_half_up_int,
)

MIN_DISBURSEMENT_CENTS = 50000
TIER1_MAX_CENTS = 100000
TIER2_MAX_CENTS = 1000000
ARTIST_APPROVAL_THRESHOLD_CENTS = 10000000
UNDERPAYMENT_RATIO_THRESHOLD_PCT = 5  # compared as exact rational: underpayment*100 >= base*5
FIRM_BEARING_FLOOR_CENTS = 2500000
WINDOW_DAYS = 365

COMMISSIONABLE_POSTURES = {"ACTIVE", "SUPERSEDED", "TERMINATED", "EXPIRED", "SUNSET"}


# ---------------------------------------------------------------------------
# Rate schedule windows (half-open) and commission rate resolution
# ---------------------------------------------------------------------------

def find_covering_schedule(agreement_id, income_type, recognition_date_iso):
    recog = parse_date(recognition_date_iso)
    for s in db["rate_schedules"].values():
        if s["agreement_id"] != agreement_id or s["income_type"] != income_type:
            continue
        start = parse_date(s["effective_from_date"])
        end = parse_date(s["effective_to_date"]) if s.get("effective_to_date") else None
        if start <= recog and (end is None or recog < end):
            return s
    return None


def schedule_windows_conflict(a_from, a_to, b_from, b_to):
    """Half-open [from, to) overlap; None end = +infinity; adjacency allowed."""
    a_to_inf = a_to is None
    b_to_inf = b_to is None
    # a_from < b_to (or +inf) AND b_from < a_to (or +inf)
    cond1 = True if b_to_inf else (a_from < b_to)
    cond2 = True if a_to_inf else (b_from < a_to)
    return cond1 and cond2


def resolve_commission(event, agreement):
    """commission_rate_resolution (scaffold 1.3): pins schedule, term_relation, rate."""
    schedule = find_covering_schedule(agreement["id"], event["income_type"], event["recognition_date"])
    if schedule is None:
        raise_error(ERR_NO_RATE_SCHEDULE,
                    "no rate schedule for (agreement, income_type) covers the recognition date")

    # PRD 3.5: the effective end is termination_date "when the agreement is
    # TERMINATED". Termination_date is stamped at termination and never cleared;
    # a terminated agreement may since have swept to SUNSET, so key on the
    # recorded date, not the current status (otherwise the terminated-agreement
    # sunset window of 3.2 would be unreachable at verify time).
    if agreement.get("termination_date"):
        term_effective_end = parse_date(agreement["termination_date"])
    else:
        term_effective_end = parse_date(agreement["term_end_date"])

    recog = parse_date(event["recognition_date"])
    if recog <= term_effective_end:
        term_relation = "IN_TERM"
        applied_rate_bps = schedule["in_term_rate_bps"]
    else:
        sunset_end_for_type = add_months(term_effective_end, schedule["sunset_months"])
        in_window = recog <= sunset_end_for_type
        if event.get("linked_engagement_id") is None:
            deal_in_term = True
        else:
            eng = db["engagements"].get(event["linked_engagement_id"])
            if eng is not None and eng.get("confirmed_at"):
                confirmed_date = parse_datetime(eng["confirmed_at"]).date()
                deal_in_term = confirmed_date <= term_effective_end
            else:
                deal_in_term = False
        if in_window and deal_in_term:
            term_relation = "SUNSET"
            applied_rate_bps = schedule["sunset_rate_bps"]
        else:
            term_relation = "POST_TERM_EXEMPT"
            applied_rate_bps = 0

    event["applied_schedule_id"] = schedule["id"]
    event["applied_rate_bps"] = applied_rate_bps
    event["term_relation"] = term_relation


def compute_commission_amount(event, agreement):
    """commission_amount (scaffold 1.3): per-event round_half_up to whole cents."""
    base = event["gross_amount_cents"]
    if (
        agreement["touring_commission_base"] == "NET_OF_EXPENSES"
        and event["income_type"] == "TOURING"
        and event.get("linked_engagement_id") is not None
    ):
        expense_sum = sum(
            e["amount_cents"]
            for e in db["expenses"].values()
            if e.get("engagement_id") == event["linked_engagement_id"]
            and e["status"] in ("APPROVED", "REIMBURSED")
        )
        base = max(0, base - expense_sum)
    commission = round_half_up_int(base * event["applied_rate_bps"], 10000)
    event["commission_amount_cents"] = commission
    event["artist_net_cents"] = event["gross_amount_cents"] - commission


# ---------------------------------------------------------------------------
# Advance recoupment waterfall (scaffold 1.3)
# ---------------------------------------------------------------------------

def run_recoupment_waterfall(event, agreement):
    from services.core import touch

    cash_share = event["received_amount_cents"] - event["commission_amount_cents"]
    eligible = [
        a for a in db["advances"].values()
        if a["artist_id"] == event["artist_id"]
        and a["status"] == "ACTIVE"
        and (not a["applies_to_income_types"] or event["income_type"] in a["applies_to_income_types"])
    ]
    eligible.sort(key=lambda a: (a["issued_date"], a["created_at"]))

    if agreement["recoupment_policy"] == "PRO_RATA":
        total_out = sum(a["outstanding_cents"] for a in eligible)
        if total_out == 0:
            event["recouped_amount_cents"] = 0
        else:
            total_recouped = 0
            prior_shares = 0
            for i, a in enumerate(eligible):
                if i < len(eligible) - 1:
                    share = floor_div_int(cash_share * a["outstanding_cents"], total_out)
                    prior_shares += share
                else:
                    share = cash_share - prior_shares  # remainder to LAST
                applied = min(a["outstanding_cents"],
                              round_half_up_int(share * a["recoup_pct_bps"], 10000))
                if applied > 0:
                    a["recouped_cents"] += applied
                    a["outstanding_cents"] -= applied
                if a["outstanding_cents"] == 0:
                    a["status"] = "RECOUPED"
                touch(a)
                total_recouped += applied
            event["recouped_amount_cents"] = total_recouped
    else:  # FIFO
        remaining = cash_share
        total_recouped = 0
        for a in eligible:
            if remaining <= 0:
                break
            take = min(a["outstanding_cents"],
                       round_half_up_int(remaining * a["recoup_pct_bps"], 10000))
            if take > 0:
                a["recouped_cents"] += take
                a["outstanding_cents"] -= take
                remaining -= take
                total_recouped += take
            if a["outstanding_cents"] == 0:
                a["status"] = "RECOUPED"
            touch(a)
        event["recouped_amount_cents"] = total_recouped

    event["artist_payable_cents"] = cash_share - event["recouped_amount_cents"]


# ---------------------------------------------------------------------------
# Expense approval routing (scaffold 1.3)
# ---------------------------------------------------------------------------

def expense_required_approvers(amount_cents):
    if amount_cents <= TIER1_MAX_CENTS:
        return ["BUSINESS_MANAGER"]
    if amount_cents <= TIER2_MAX_CENTS:
        return ["BUSINESS_MANAGER", "ARTIST"]
    return ["BUSINESS_MANAGER", "ARTIST", "FIRM_ADMIN"]


def create_approval_requests(artist_id, target_type, target_id, approvers, requested_by):
    from services.core import new_record

    created = []
    for approver in approvers:
        rec = new_record("approval_requests", {
            "artist_id": artist_id,
            "target_type": target_type,
            "target_id": target_id,
            "required_approver": approver,
            "status": "PENDING",
            "requested_by_user_id": requested_by,
            "decided_by_user_id": None,
            "decision_note": None,
        })
        created.append(rec)
    return created


# ---------------------------------------------------------------------------
# Opportunity evaluation (scaffold 1.3)
# ---------------------------------------------------------------------------

def trailing_average_gross(artist_id, income_type, clock_date):
    window_start = clock_date - timedelta(days=WINDOW_DAYS)
    source = [
        e for e in db["income_events"].values()
        if e["artist_id"] == artist_id
        and e["income_type"] == income_type
        and e["status"] in ("SETTLED", "POSTED")
        and e.get("received_date")
        and window_start <= parse_date(e["received_date"]) <= clock_date
    ]
    if not source:
        return None
    total = sum(e["received_amount_cents"] for e in source)
    return round_half_up_int(total, len(source))


def evaluate_opportunity(opp, clock_date):
    avg = trailing_average_gross(opp["artist_id"], opp["income_type"], clock_date)
    if avg is None:
        financial_component = 50
    else:
        financial_component = min(100, round_half_up_int(50 * opp["current_value_cents"], avg))

    # availability: plain (unbuffered) closed-interval intersection
    p_start = parse_date_or_dt(opp["proposed_window_start"])
    p_end = parse_date_or_dt(opp["proposed_window_end"])
    conflicts = []
    for eng in db["engagements"].values():
        if eng["artist_id"] != opp["artist_id"]:
            continue
        if eng["status"] not in ("HOLD", "CONFIRMED"):
            continue
        e_start = parse_date_or_dt(eng["start_datetime"])
        e_end = parse_date_or_dt(eng["end_datetime"])
        if p_start <= e_end and e_start <= p_end:
            conflicts.append(eng)
    if any(c["status"] == "CONFIRMED" for c in conflicts):
        availability_component = 0
    elif conflicts:
        availability_component = 50
    else:
        availability_component = 100

    # 0.5*financial + 0.3*fit + 0.2*availability, round half up at the final step only
    numerator = 5 * financial_component + 3 * opp["fit_score"] + 2 * availability_component
    score = round_half_up_int(numerator, 10)
    if score >= 70:
        recommendation = "PURSUE"
    elif score >= 40:
        recommendation = "CONSIDER"
    else:
        recommendation = "PASS_SUGGESTED"
    return score, recommendation


def parse_date_or_dt(s):
    from util import parse_datetime
    s2 = s.strip()
    if "T" in s2:
        return parse_datetime(s2)
    return parse_date(s2)


def requires_artist_approval(opp):
    return opp["current_value_cents"] > ARTIST_APPROVAL_THRESHOLD_CENTS


def maybe_create_artist_approval(opp, requested_by):
    """Create a PENDING ARTIST approval request if required and none pending/approved."""
    if not requires_artist_approval(opp):
        return
    for req in db["approval_requests"].values():
        if (
            req["target_type"] == "OPPORTUNITY"
            and req["target_id"] == opp["id"]
            and req["required_approver"] == "ARTIST"
            and req["status"] in ("PENDING", "APPROVED")
        ):
            return
    create_approval_requests(opp["artist_id"], "OPPORTUNITY", opp["id"], ["ARTIST"], requested_by)


def has_approved_artist_request(opp_id):
    for req in db["approval_requests"].values():
        if (
            req["target_type"] == "OPPORTUNITY"
            and req["target_id"] == opp_id
            and req["required_approver"] == "ARTIST"
            and req["status"] == "APPROVED"
        ):
            return True
    return False


# ---------------------------------------------------------------------------
# Statement generation (scaffold 1.3, PRD 3.8)
# ---------------------------------------------------------------------------

def generate_statement_lines(statement):
    """Build the line set for a draft statement; marks audit flags. Returns lines list."""
    from services.core import new_record

    artist_id = statement["artist_id"]
    p_start = parse_date(statement["period_start_date"])
    p_end = parse_date(statement["period_end_date"])
    basis = statement["basis"]
    lines = []
    rate_snapshot = []

    # (1) INCOME lines
    income_events = []
    for e in db["income_events"].values():
        if e["artist_id"] != artist_id or e["statement_id"] is not None:
            continue
        if basis == "ACCRUAL":
            if e["status"] in ("VERIFIED", "SETTLED") and p_start <= parse_date(e["recognition_date"]) <= p_end:
                income_events.append(e)
        else:  # CASH
            if e["status"] == "SETTLED" and e.get("received_date") and p_start <= parse_date(e["received_date"]) <= p_end:
                income_events.append(e)
    income_events.sort(key=lambda e: (e["created_at"], e["id"]))
    for e in income_events:
        line = new_record("statement_lines", {
            "statement_id": statement["id"],
            "line_type": "INCOME",
            "ref_id": e["id"],
            "amount_cents": e["artist_net_cents"],
            "commission_cents": e["commission_amount_cents"],
            "note": f"Income {e['income_type']} from {e['source_name']} recognized {e['recognition_date']}",
        }, with_version=False)
        lines.append(line)
        rate_snapshot.append({
            "income_type": e["income_type"],
            "schedule_id": e["applied_schedule_id"],
            "rate_bps": e["applied_rate_bps"],
        })
    statement["_swept_income_event_ids"] = [e["id"] for e in income_events]

    # (2) EXPENSE_REIMBURSEMENT lines
    expenses = [
        e for e in db["expenses"].values()
        if e["artist_id"] == artist_id
        and e["status"] == "APPROVED"
        and parse_date(e["incurred_date"]) <= p_end
    ]
    expenses.sort(key=lambda e: (e["created_at"], e["id"]))
    for e in expenses:
        line = new_record("statement_lines", {
            "statement_id": statement["id"],
            "line_type": "EXPENSE_REIMBURSEMENT",
            "ref_id": e["id"],
            "amount_cents": e["amount_cents"],
            "commission_cents": 0,
            "note": f"Expense {e['category']} incurred {e['incurred_date']}",
        }, with_version=False)
        lines.append(line)
    statement["_swept_expense_ids"] = [e["id"] for e in expenses]

    # (3) ADVANCE_RECOUPMENT lines
    recoup_events = [
        e for e in db["income_events"].values()
        if e["artist_id"] == artist_id
        and e["recoup_statement_id"] is None
        and (e["recouped_amount_cents"] or 0) > 0
        and e.get("received_date")
        and p_start <= parse_date(e["received_date"]) <= p_end
    ]
    recoup_events.sort(key=lambda e: (e["created_at"], e["id"]))
    for e in recoup_events:
        line = new_record("statement_lines", {
            "statement_id": statement["id"],
            "line_type": "ADVANCE_RECOUPMENT",
            "ref_id": e["id"],
            "amount_cents": e["recouped_amount_cents"],
            "commission_cents": 0,
            "note": f"Advance recoupment from event received {e['received_date']}",
        }, with_version=False)
        lines.append(line)
    statement["_swept_recoup_event_ids"] = [e["id"] for e in recoup_events]

    # (4) ADJUSTMENT lines from audits
    audits = [
        a for a in db["audits"].values()
        if a["artist_id"] == artist_id and a["status"] in ("FINDINGS_ISSUED", "CLOSED")
    ]
    audits.sort(key=lambda a: (a["created_at"], a["id"]))
    for a in audits:
        if (a.get("findings_underpayment_cents") or 0) > 0 and not a["underpayment_applied"]:
            line = new_record("statement_lines", {
                "statement_id": statement["id"],
                "line_type": "ADJUSTMENT",
                "ref_id": a["id"],
                "amount_cents": a["findings_underpayment_cents"],
                "commission_cents": 0,
                "note": f"Audit underpayment finding on statement {a['scope_statement_id']}",
            }, with_version=False)
            lines.append(line)
            a["underpayment_applied"] = True
            from services.core import touch
            touch(a)
        if (
            a.get("cost_bearer") == "ARTIST"
            and (a.get("audit_cost_cents") or 0) > 0
            and not a["cost_applied"]
        ):
            line = new_record("statement_lines", {
                "statement_id": statement["id"],
                "line_type": "ADJUSTMENT",
                "ref_id": a["id"],
                "amount_cents": -a["audit_cost_cents"],
                "commission_cents": 0,
                "note": f"Audit cost recovery on statement {a['scope_statement_id']}",
            }, with_version=False)
            lines.append(line)
            a["cost_applied"] = True
            from services.core import touch
            touch(a)

    statement["rate_snapshot"] = rate_snapshot
    return lines


def recompute_statement_totals(statement):
    """Recompute totals over the statement's current line set (generate and amend)."""
    lines = [l for l in db["statement_lines"].values() if l["statement_id"] == statement["id"]]
    income_net_total = sum(l["amount_cents"] for l in lines if l["line_type"] == "INCOME")
    commission_total = sum(l["commission_cents"] for l in lines if l["line_type"] == "INCOME")
    # gross = net + commission per income line
    gross_total = sum(
        l["amount_cents"] + l["commission_cents"] for l in lines if l["line_type"] == "INCOME"
    )
    expense_total = sum(l["amount_cents"] for l in lines if l["line_type"] == "EXPENSE_REIMBURSEMENT")
    recoup_total = sum(l["amount_cents"] for l in lines if l["line_type"] == "ADVANCE_RECOUPMENT")
    adjustment_total = sum(l["amount_cents"] for l in lines if l["line_type"] == "ADJUSTMENT")

    statement["gross_total_cents"] = gross_total
    statement["commission_total_cents"] = commission_total
    statement["income_net_total_cents"] = income_net_total
    statement["expense_total_cents"] = expense_total
    statement["recoup_total_cents"] = recoup_total
    statement["adjustment_total_cents"] = adjustment_total

    net_payable = income_net_total - expense_total - recoup_total + adjustment_total + statement["carry_in_cents"]
    statement["net_payable_cents"] = net_payable
    if net_payable >= MIN_DISBURSEMENT_CENTS:
        statement["disbursed_cents"] = net_payable
        statement["carry_out_cents"] = 0
    elif net_payable > 0:
        statement["disbursed_cents"] = 0
        statement["carry_out_cents"] = net_payable
    else:
        statement["disbursed_cents"] = 0
        statement["carry_out_cents"] = net_payable


# ---------------------------------------------------------------------------
# Audit cost allocation (scaffold 1.3)
# ---------------------------------------------------------------------------

def audit_cost_bearer(statement_net_payable_cents, findings_underpayment_cents):
    """FIRM if ratio >= 5% (exact rational) or underpayment >= floor; else ARTIST."""
    base = statement_net_payable_cents
    under = findings_underpayment_cents
    ratio_firm = True if base <= 0 else (under * 100 >= base * UNDERPAYMENT_RATIO_THRESHOLD_PCT)
    if ratio_firm or under >= FIRM_BEARING_FLOOR_CENTS:
        return "FIRM"
    return "ARTIST"
