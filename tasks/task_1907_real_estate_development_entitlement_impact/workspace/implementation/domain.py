"""Domain logic: fee math, opposition scoring, deadlines, cascades.

All monetary arithmetic uses Decimal with round-half-up at 2dp. Per PRD 2.6,
each category's NET is rounded to cents first and only then summed into the
assessment net_total ("round per-category then sum").
"""

import math
from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP

import store
from store import CLOCK, STORES, touch

# --- constants pinned by PRD / scaffold ------------------------------------
PERMIT_STREAMLINING_DAYS = 90
NOTICE_LEAD_DAYS = 20
APPEAL_WINDOW_DAYS = 30       # not numerically pinned in PRD; see worklog note
REFERENDUM_WINDOW_DAYS = 30   # not numerically pinned in PRD; see worklog note
REFERENDUM_SIGNATURE_PCT = Decimal("0.10")
LATE_FEE_RATE_PER_MONTH = Decimal("0.015")
DAYS_PER_MONTH = 30

CATEGORIES = ("TRANSPORTATION", "PARKS", "FIRE", "WATER", "SEWER")
AFFORDABLE_EXEMPT_CATEGORIES = ("TRANSPORTATION", "PARKS")
SQFT_BASIS_DIVISOR = 1000

WEIGHTS = {"SUPPORT": -2, "NEUTRAL": 0, "OPPOSE": 5, "ORGANIZED_OPPOSITION": 12}
ELEVATED_THRESHOLD = 10
HIGH_THRESHOLD = 30

SEQUENCE_RANKS = {"GRADING": 1, "BUILDING": 2, "UTILITY": 2, "OCCUPANCY": 3}

CENT = Decimal("0.01")


def D(value) -> Decimal:
    """Exact Decimal from an int/float/str input."""
    return Decimal(str(value))


def r2(value: Decimal) -> Decimal:
    return value.quantize(CENT, rounding=ROUND_HALF_UP)


# --- lookups ----------------------------------------------------------------

def get_or_404(store_name: str, rec_id: str, label: str):
    from errors import ApiError, ERR_NOT_FOUND
    rec = store.get(store_name, rec_id)
    if rec is None:
        raise ApiError(ERR_NOT_FOUND, f"{label} not found: {rec_id}", 404)
    return rec


def project_for(application: dict):
    return store.get("projects", application.get("project_id"))


def application_for(child: dict, key: str = "application_id"):
    return store.get("applications", child.get(key))


# --- impact fee assessment calculation (PRD 3.3 / scaffold 1.3) -------------

def _rate_for(schedule: dict, category: str, land_use_type: str) -> Decimal:
    suffix = "res" if land_use_type == "RESIDENTIAL" else "com"
    return D(schedule[f"rate_{category.lower()}_{suffix}"])


def compute_assessment_lines(project: dict, application: dict, schedule: dict):
    """Returns (category_lines, gross_total, prior_total, impr_total, net_total).

    Every stored dollar figure is quantized to cents half-up; net per category
    is rounded before summing (PRD 2.6).
    """
    land_use = project["land_use_type"]
    if land_use == "RESIDENTIAL":
        basis = D(project.get("dwelling_units", 0))
    else:
        basis = D(project.get("floor_area_sqft", 0)) / D(SQFT_BASIS_DIVISOR)

    prior_basis_map = project.get("prior_use_basis") or {}
    impr_map = application.get("improvement_credits") or {}

    lines = []
    gross_total = Decimal("0.00")
    prior_total = Decimal("0.00")
    impr_total = Decimal("0.00")
    net_total = Decimal("0.00")

    for cat in CATEGORIES:
        rate = _rate_for(schedule, cat, land_use)
        eff_basis = basis
        if land_use == "RESIDENTIAL" and cat in AFFORDABLE_EXEMPT_CATEGORIES:
            eff_basis = D(project.get("dwelling_units", 0)) - D(
                project.get("affordable_units", 0))
        gross = r2(eff_basis * rate)

        prior_raw = D(prior_basis_map.get(cat, 0)) * rate
        prior = r2(min(prior_raw, gross))

        remaining = gross - prior
        impr_raw = D(impr_map.get(cat, 0))
        impr = r2(min(impr_raw, remaining)) if remaining > 0 else Decimal("0.00")

        net = r2(gross - prior - impr)

        lines.append({
            "category": cat,
            "gross": gross,
            "prior_use_credit": prior,
            "improvement_credit": impr,
            "net": net,
        })
        gross_total += gross
        prior_total += prior
        impr_total += impr
        net_total += net

    return lines, r2(gross_total), r2(prior_total), r2(impr_total), r2(net_total)


def adopted_schedule_now():
    """The (single) ADOPTED schedule; tie-break latest effective_date then
    earliest created_at. Returns None when no ADOPTED schedule exists."""
    adopted = [s for s in store.all_records("fee_schedules")
               if s["status"] == "ADOPTED"]
    if not adopted:
        return None
    adopted.sort(key=lambda s: (store.parse_dt(s["effective_date"])),
                 reverse=True)
    best_eff = store.parse_dt(adopted[0]["effective_date"])
    top = [s for s in adopted
           if store.parse_dt(s["effective_date"]) == best_eff]
    top.sort(key=lambda s: s["created_at"])
    return top[0]


def vested_da_for(application: dict):
    """A DevelopmentAgreement covering this application whose vesting holds:
    vesting_status == VESTED and logical clock <= vesting_expires_at."""
    now = CLOCK.now()
    for da in store.all_records("development_agreements"):
        if da.get("application_id") != application["id"]:
            continue
        if da.get("vesting_status") == "VESTED" and \
                store.parse_dt(da["vesting_expires_at"]) >= now:
            return da
    return None


def final_schedule_for(application: dict):
    """Vesting rule for FINAL assessments (PRD 3.6): VESTED + unexpired DA
    keeps the pinned schedule; otherwise the currently ADOPTED schedule."""
    if vested_da_for(application) is not None and \
            application.get("pinned_fee_schedule_id"):
        return store.get("fee_schedules", application["pinned_fee_schedule_id"])
    return adopted_schedule_now()


def create_assessment(application: dict, project: dict, schedule: dict,
                      variant: str, due_date):
    lines, gross_total, prior_total, impr_total, net_total = \
        compute_assessment_lines(project, application, schedule)
    rec = store.new_record("assessments")
    rec.update({
        "application_id": application["id"],
        "fee_schedule_id": schedule["id"],
        "variant": variant,
        "category_lines": lines,
        "gross_total": gross_total,
        "prior_use_credit_total": prior_total,
        "improvement_credit_total": impr_total,
        "net_total": net_total,
        "due_date": store.fmt_dt(due_date) if due_date is not None else None,
        "outstanding_balance": net_total,
        "status": "OPEN",
    })
    return rec


def recompute_final_assessment(assessment: dict, application: dict,
                               project: dict, schedule: dict, due_date):
    """Re-approval after remand recomputes the existing FINAL assessment."""
    lines, gross_total, prior_total, impr_total, net_total = \
        compute_assessment_lines(project, application, schedule)
    assessment.update({
        "fee_schedule_id": schedule["id"],
        "category_lines": lines,
        "gross_total": gross_total,
        "prior_use_credit_total": prior_total,
        "improvement_credit_total": impr_total,
        "net_total": net_total,
        "due_date": store.fmt_dt(due_date) if due_date is not None else None,
    })
    recompute_outstanding(assessment)
    bal = assessment["outstanding_balance"]
    if bal <= Decimal("0.00") and paid_in_total(assessment) > 0:
        assessment["status"] = "PAID"
    elif paid_in_total(assessment) > 0:
        assessment["status"] = "PARTIALLY_PAID"
    else:
        assessment["status"] = "OPEN"
    touch(assessment)


def payments_of(assessment_id: str):
    return [p for p in store.all_records("payments")
            if p.get("assessment_id") == assessment_id]


def paid_in_total(assessment: dict) -> Decimal:
    return sum((D(p["applied_amount"])
                for p in payments_of(assessment["id"])
                if not p.get("refunded")),
               Decimal("0.00"))


def recompute_outstanding(assessment: dict) -> None:
    assessment["outstanding_balance"] = r2(
        D(assessment["net_total"]) - paid_in_total(assessment))


# --- late fee (PRD 3.7) ------------------------------------------------------

def compute_late_fee(amount: Decimal, paid_at, due_date_str) -> Decimal:
    if not due_date_str:
        return Decimal("0.00")
    due = store.parse_dt(due_date_str)
    delta = paid_at - due
    days_late = max(0, delta.days)
    full_months = days_late // DAYS_PER_MONTH
    if full_months <= 0:
        return Decimal("0.00")
    return r2(amount * LATE_FEE_RATE_PER_MONTH * D(full_months))


# --- opposition scoring (PRD 3.5) --------------------------------------------

def recompute_opposition(application: dict) -> None:
    score = sum(WEIGHTS[e["disposition"]]
                for e in store.all_records("outreach_events")
                if e.get("application_id") == application["id"])
    application["opposition_score"] = score
    if score >= HIGH_THRESHOLD:
        posture = "HIGH"
    elif score >= ELEVATED_THRESHOLD:
        posture = "ELEVATED"
    else:
        posture = "LOW"
    application["opposition_posture"] = posture
    touch(application)


# --- refund cascade (PRD 3.6 / 3.7 / 3.9) ------------------------------------

def refund_open_assessments(application: dict) -> None:
    for a in store.all_records("assessments"):
        if a.get("application_id") != application["id"]:
            continue
        if a["status"] in ("OPEN", "PARTIALLY_PAID"):
            for p in payments_of(a["id"]):
                if not p.get("refunded"):
                    p["refunded"] = True
                    touch(p)
            a["status"] = "REFUNDED"
            recompute_outstanding(a)
            touch(a)


# --- clock-driven system transitions (PRD 2.8) --------------------------------

def advance_system_transitions() -> None:
    """Runs whenever the logical clock is (re)set."""
    now = CLOCK.now()
    # Development agreements: referendum window lapse -> EFFECTIVE / VESTED.
    for da in store.all_records("development_agreements"):
        if da["status"] == "ADOPTED":
            deadline = store.parse_dt(da["referendum_deadline"])
            qualified = any(
                p for p in store.all_records("petitions")
                if p.get("development_agreement_id") == da["id"]
                and p["status"] == "CERTIFIED_QUALIFIED")
            if now >= deadline and not qualified:
                da["status"] = "EFFECTIVE"
                da["vesting_status"] = "VESTED"
                touch(da)
        if da["status"] == "EFFECTIVE" and da.get("vesting_status") == "VESTED":
            if now > store.parse_dt(da["vesting_expires_at"]):
                da["vesting_status"] = "LAPSED"
                touch(da)
    # Rendered decisions finalize once the appeal deadline passes cleanly.
    for dec in store.all_records("decisions"):
        if dec["status"] != "RENDERED":
            continue
        if now < store.parse_dt(dec["appeal_deadline"]):
            continue
        pending = any(
            ap for ap in store.all_records("appeals")
            if ap.get("application_id") == dec["application_id"]
            and ap["status"] == "FILED")
        if not pending:
            dec["status"] = "FINAL"
            touch(dec)


# --- vesting expiry in years --------------------------------------------------

def add_years(dt, years: int):
    try:
        return dt.replace(year=dt.year + years)
    except ValueError:  # Feb 29 -> Feb 28 on non-leap target year
        return dt.replace(year=dt.year + years, day=28)


def referendum_required_signatures(registered_voters: int) -> int:
    return math.ceil(REFERENDUM_SIGNATURE_PCT * D(registered_voters))


# --- permit issuance precondition evaluation ---------------------------------

def latest_decision_for(application_id: str):
    decs = [d for d in store.all_records("decisions")
            if d.get("application_id") == application_id]
    if not decs:
        return None
    return decs[-1]


def final_assessment_for(application_id: str):
    for a in store.all_records("assessments"):
        if a.get("application_id") == application_id and \
                a.get("variant") == "FINAL":
            return a
    return None


def issuance_blockers(seq: dict):
    """Ordered issuance precondition failures (PRD 3.9). Returns a list of
    (error_id, message, http_status) tuples; empty means issuable."""
    from errors import (ERR_APPLICATION_NOT_APPROVED, ERR_APPEAL_WINDOW_OPEN,
                        ERR_SEQUENCE_VIOLATION, ERR_CONDITIONS_PENDING,
                        ERR_FEES_UNPAID)
    blockers = []
    app = store.get("applications", seq["application_id"])
    if app is None or app["status"] != "APPROVED":
        blockers.append((ERR_APPLICATION_NOT_APPROVED,
                         "Parent application must be APPROVED", 409))
        return blockers
    dec = latest_decision_for(app["id"])
    if dec is None or dec["status"] != "FINAL":
        blockers.append((ERR_APPEAL_WINDOW_OPEN,
                         "EntitlementDecision is not FINAL (appeal pending or "
                         "window open)", 409))
        return blockers
    lower = [s for s in store.all_records("permit_sequences")
             if s.get("application_id") == app["id"]
             and s["sequence_rank"] < seq["sequence_rank"]
             and s["status"] != "ISSUED"]
    if lower:
        blockers.append((ERR_SEQUENCE_VIOLATION,
                         "Lower sequence_rank permit not yet ISSUED", 409))
    pending_conditions = [c for c in store.all_records("conditions")
                          if c.get("application_id") == app["id"]
                          and c.get("required_before") == "PERMIT_ISSUANCE"
                          and c["status"] == "PENDING"]
    if pending_conditions:
        blockers.append((ERR_CONDITIONS_PENDING,
                         "PERMIT_ISSUANCE condition still PENDING", 409))
    final = final_assessment_for(app["id"])
    if final is None or final["status"] not in ("PAID", "DEFERRED"):
        blockers.append((ERR_FEES_UNPAID,
                         "FINAL assessment neither PAID nor DEFERRED", 402))
    elif (seq["permit_type"] == "OCCUPANCY" and final["status"] == "DEFERRED"
          and D(final["outstanding_balance"]) > 0):
        blockers.append((ERR_FEES_UNPAID,
                         "OCCUPANCY requires the FINAL assessment actually "
                         "PAID while a deferred balance stands unpaid", 402))
    return blockers
