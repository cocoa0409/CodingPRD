"""Business logic: calculations, state-machine side effects, cascades, clock rules.

All temporal rules use the logical clock (db.clock_now). Audit stamps
(created_at / updated_at / api_request_timestamp) use the wall clock.
"""
from datetime import timedelta
from decimal import Decimal

from db import DB, clock_now, fmt_iso, new_id, wall_now_iso
from errors import ApiError
from util import add_months, add_years, round_half_up_2, touch

LATE_REPORT_PENALTY_CENTS = 25000
RUBRIC_MAX = 4
ADVANCE_NOTICE_DAYS = 60
RENEWAL_WINDOW_DAYS = 180


# ---------------------------------------------------------------------------
# Lookup helpers (raise ERR_NOT_FOUND when absent)
# ---------------------------------------------------------------------------

def get_or_404(collection, entity_id, label="resource"):
    row = DB[collection].get(entity_id)
    if row is None:
        raise ApiError("ERR_NOT_FOUND", 404, f"{label} not found: {entity_id}")
    return row


# ---------------------------------------------------------------------------
# Composite index (campus_composite_index calculation)
# ---------------------------------------------------------------------------

def recompute_campus_composite(campus):
    """Recompute campus.composite_index_pct from FINALIZED ratings under the
    owning system's current term. Mutates the campus (no version bump here;
    the caller is responsible for touch())."""
    system = DB["systems"].get(campus["system_id"])
    current_term_id = system["current_term_id"] if system else None
    rows = [
        r for r in DB["ratings"].values()
        if r["campus_id"] == campus["id"]
        and r["status"] == "FINALIZED"
        and current_term_id is not None
        and r["term_id"] == current_term_id
    ]
    if not rows:
        campus["composite_index_pct"] = None
        return
    numerator = Decimal(0)
    denominator = Decimal(0)
    for r in rows:
        std = DB["standards"].get(r["standard_id"])
        if std is None:
            continue
        w = Decimal(std["weight_pct"])
        numerator += Decimal(r["rating"]) * w
        denominator += w
    if denominator == 0:
        campus["composite_index_pct"] = None
        return
    raw = (numerator / denominator) * (Decimal(100) / Decimal(RUBRIC_MAX))
    campus["composite_index_pct"] = round_half_up_2(raw)


# ---------------------------------------------------------------------------
# Goal attainment (goal_attainment calculation)
# ---------------------------------------------------------------------------

def recompute_goal_attainment(goal):
    """Recompute goal.current_value and goal.attainment_pct from indicators.

    Latest indicator by measured_at; tie broken by created_at ASC (earliest
    created wins).
    """
    indicators = [
        i for i in DB["indicators"].values() if i["goal_id"] == goal["id"]
    ]
    if indicators:
        # Order by measured_at DESC, created_at ASC; take the head.
        ordered = sorted(
            indicators,
            key=lambda i: (i["_measured_at_dt"],),
            reverse=True,
        )
        max_measured = ordered[0]["_measured_at_dt"]
        tied = [i for i in ordered if i["_measured_at_dt"] == max_measured]
        tied.sort(key=lambda i: i["created_at"])  # earliest created wins
        goal["current_value"] = tied[0]["value"]
    else:
        goal["current_value"] = goal["baseline_value"]

    baseline = Decimal(str(goal["baseline_value"]))
    target = Decimal(str(goal["target_value"]))
    current = Decimal(str(goal["current_value"]))
    if goal["direction"] == "INCREASE":
        denom = target - baseline
        progress = Decimal(0) if denom == 0 else (current - baseline) / denom
    else:  # DECREASE
        denom = baseline - target
        progress = Decimal(0) if denom == 0 else (baseline - current) / denom
    if progress < 0:
        progress = Decimal(0)
    if progress > 1:
        progress = Decimal(1)
    goal["attainment_pct"] = round_half_up_2(progress * Decimal(100))


# ---------------------------------------------------------------------------
# Fee schedule selection
# ---------------------------------------------------------------------------

def select_fee_schedule(issued_at_dt):
    """Pick the FeeSchedule with the greatest effective_from <= issued_at.
    Ties on effective_from broken by created_at ASC. None when no such row."""
    candidates = [
        fs for fs in DB["fee_schedules"].values()
        if fs["_effective_from_dt"] <= issued_at_dt
    ]
    if not candidates:
        return None
    # Greatest effective_from; ties by earliest created_at.
    candidates.sort(key=lambda fs: (fs["_effective_from_dt"], fs["created_at"]))
    # We want max effective_from, then earliest created_at among ties.
    max_eff = candidates[-1]["_effective_from_dt"]
    tied = [c for c in candidates if c["_effective_from_dt"] == max_eff]
    tied.sort(key=lambda fs: fs["created_at"])
    return tied[0]


# ---------------------------------------------------------------------------
# Invoice issuance (annual_fee_invoice_amount / visit_fee_invoice_amount)
# ---------------------------------------------------------------------------

def issue_invoice(system, invoice_type, billing_year):
    """Compute amount and persist an Invoice. Returns the new invoice row.

    Raises ERR_FISCAL_VIOLATION when no applicable FeeSchedule exists.
    """
    now_dt = clock_now()
    schedule = select_fee_schedule(now_dt)
    if schedule is None:
        raise ApiError(
            "ERR_FISCAL_VIOLATION",
            422,
            "No fee schedule in effect for the issuance date",
        )

    if invoice_type == "ANNUAL_FEE":
        billable = [
            c for c in DB["campuses"].values()
            if c["system_id"] == system["id"] and c["campus_status"] == "IN_SCOPE"
        ]
        large = [c for c in billable if c["enrollment"] >= schedule["large_campus_threshold"]]
        small_count = len(billable) - len(large)
        amount = (
            schedule["base_system_fee_cents"]
            + small_count * schedule["per_campus_fee_cents"]
            + len(large) * schedule["large_campus_fee_cents"]
        )
        credit = system["fee_credit_cents"]
        credit_moved = False
        if credit > 0:
            applied = min(credit, amount)
            amount -= applied
            system["fee_credit_cents"] = credit - applied
            credit_moved = applied != 0
        elif credit < 0:
            amount += -credit
            system["fee_credit_cents"] = 0
            credit_moved = True
        if credit_moved:
            touch(system)
    elif invoice_type == "VISIT_FEE":
        # Final settlement: only visits in REPORT_ISSUED count.
        visit_days = 0
        for v in DB["visits"].values():
            if v["term_id"] == system.get("current_term_id") and v["status"] == "REPORT_ISSUED":
                delta = v["_ends_on_dt"] - v["_starts_on_dt"]
                visit_days += delta.days
        amount = visit_days * schedule["visit_day_rate_cents"]
    elif invoice_type == "RENEWAL_FEE":
        # Renewal fee follows the annual-fee machinery per PRD 3.8.
        billable = [
            c for c in DB["campuses"].values()
            if c["system_id"] == system["id"] and c["campus_status"] == "IN_SCOPE"
        ]
        large = [c for c in billable if c["enrollment"] >= schedule["large_campus_threshold"]]
        small_count = len(billable) - len(large)
        amount = (
            schedule["base_system_fee_cents"]
            + small_count * schedule["per_campus_fee_cents"]
            + len(large) * schedule["large_campus_fee_cents"]
        )
        credit = system["fee_credit_cents"]
        credit_moved = False
        if credit > 0:
            applied = min(credit, amount)
            amount -= applied
            system["fee_credit_cents"] = credit - applied
            credit_moved = applied != 0
        elif credit < 0:
            amount += -credit
            system["fee_credit_cents"] = 0
            credit_moved = True
        if credit_moved:
            touch(system)
    else:
        raise ApiError("ERR_VALIDATION", 400, f"Unknown invoice_type: {invoice_type}")

    from util import stamp_new
    invoice = {
        "id": new_id(),
        "system_id": system["id"],
        "billing_year": billing_year,
        "invoice_type": invoice_type,
        "amount_cents": amount,
        "status": "ISSUED",
        "issued_at": fmt_iso(now_dt),
    }
    stamp_new(invoice, with_version=True)
    DB["invoices"][invoice["id"]] = invoice
    return invoice


# ---------------------------------------------------------------------------
# Interim report due date (interim_report_due_date calculation)
# ---------------------------------------------------------------------------

def interim_due_date(term, report_year):
    """due_date = add_years(term.term_start, report_year) - 60 days."""
    base = add_years(term["_term_start_dt"], report_year)
    return base - timedelta(days=ADVANCE_NOTICE_DAYS)


# ---------------------------------------------------------------------------
# RequiredActionItem due date (action_item_due_date calculation)
# ---------------------------------------------------------------------------

def action_item_due_date(visit, follow_up_months):
    """due_date = add_months(visit.ends_on, follow_up_months)."""
    return add_months(visit["_ends_on_dt"], follow_up_months)


# ---------------------------------------------------------------------------
# Clock-driven transitions (PRD 2.8). Called after every clock set.
# ---------------------------------------------------------------------------

def run_clock_transitions():
    """Re-evaluate every clock-driven transition at the current logical time."""
    now = clock_now()

    # SurveyWindow SCHEDULED -> OPEN; OPEN -> CLOSED / INVALIDATED
    for w in list(DB["survey_windows"].values()):
        if w["status"] == "SCHEDULED" and w["_opens_at_dt"] <= now < w["_closes_at_dt"]:
            w["status"] = "OPEN"
            touch(w)
        if w["status"] == "OPEN" and now >= w["_closes_at_dt"]:
            _close_window_with_threshold(w)

    # VisitEvent CONFIRMED -> IN_FIELD; IN_FIELD -> REPORT_DRAFT
    for v in list(DB["visits"].values()):
        if v["status"] == "CONFIRMED" and now >= v["_starts_on_dt"]:
            v["status"] = "IN_FIELD"
            touch(v)
        if v["status"] == "IN_FIELD" and now >= v["_ends_on_dt"]:
            v["status"] = "REPORT_DRAFT"
            touch(v)

    # RequiredActionItem OPEN -> OVERDUE
    for ai in list(DB["action_items"].values()):
        if ai["status"] == "OPEN" and now > ai["_due_date_dt"]:
            ai["status"] = "OVERDUE"
            touch(ai)

    # AccreditationTerm INTERIM_MONITORING -> RENEWAL
    for t in list(DB["terms"].values()):
        if t["status"] == "INTERIM_MONITORING":
            threshold = t["_term_end_dt"] - timedelta(days=RENEWAL_WINDOW_DAYS)
            if now >= threshold:
                t["status"] = "RENEWAL"
                touch(t)
                system = DB["systems"].get(t["system_id"])
                if system is not None:
                    # Issue a RENEWAL_FEE invoice via the fee machinery. If no
                    # fee schedule exists for the issuance date the clock tick
                    # still completes; the missing-schedule error surfaces when
                    # the bursar tries to issue manually.
                    try:
                        issue_invoice(system, "RENEWAL_FEE", now.year)
                    except ApiError as exc:
                        if exc.error_id != "ERR_FISCAL_VIOLATION":
                            raise


def _close_window_with_threshold(window):
    """Apply the participation threshold and land in CLOSED or INVALIDATED."""
    instrument = DB["instruments"].get(window["instrument_id"])
    min_pct = instrument["min_participation_pct"] if instrument else 0
    if window["response_count"] * 100 >= min_pct * window["eligible_count"]:
        window["status"] = "CLOSED"
    else:
        window["status"] = "INVALIDATED"
    touch(window)


def close_window_manual(window):
    """Manual close path used by POST /survey-windows/{id}/close."""
    _close_window_with_threshold(window)
