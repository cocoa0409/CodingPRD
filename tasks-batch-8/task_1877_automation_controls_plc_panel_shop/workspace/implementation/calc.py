"""Calculation rules (scaffold section 1.3) and the job posture engine."""

import math
from decimal import Decimal, ROUND_HALF_UP

from core import bump, add_months, now_iso
from store import db

LINE_ACTIVE_STATUSES = ("PENDING", "ORDERED", "RECEIVED", "SUBSTITUTED")
POWER_CLASSES = ("DISCONNECT", "BRANCH_PROTECTIVE", "CONTACTOR", "OVERLOAD", "POWER_SUPPLY")

CONTROL_BRANCH_FLOOR_KA = 25
CURRENT_LIMITING_THRESHOLD_KA = 100
RISK_PAD_DAYS = 7

TIER_RATE = {"TIER_LOCAL": 9500, "TIER_REGIONAL": 14500, "TIER_NATIONAL": 21000}
CAP_CENTS = 500000
DEDUCTIBLE_CENTS = 10000
PARTS_ALLOWANCE_CENTS = 25000

INCLUDED_BASE_HOURS = 8
OT_CAP_HOURS = 16
BASE_RATE = 18533
WEEKEND_MULT = Decimal("1.25")

W_WIRING = Decimal("0.35")
W_PROGRAM = Decimal("0.25")
W_TEST = Decimal("0.25")
W_LABEL = Decimal("0.15")


def _rhup(d):
    """Round half-up to integer."""
    return int(Decimal(d).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


# ---------------------------------------------------------------------------
# BOM input sets
# ---------------------------------------------------------------------------


def active_bom_lines(panel_id):
    """PanelComponent lines in an active posture, excluding retired originals.

    The input sets include a line only when no other line references it via
    substituted_for_id (scaffold: substitution approval side effects).
    """
    lines = [l for l in db.panel_components.values() if l["panel_id"] == panel_id]
    retired = {l["substituted_for_id"] for l in lines if l.get("substituted_for_id")}
    return [
        l
        for l in lines
        if l["line_status"] in LINE_ACTIVE_STATUSES and l["id"] not in retired
    ]


def line_extended_cost(line):
    """bom_cost_rollup: per-line round_half_up(quantity * unit_cost_snapshot, 0)."""
    return _rhup(Decimal(line["quantity"]) * Decimal(line["unit_cost_snapshot_cents"]))


def recompute_sccr(panel):
    """sccr_panel_rating: weakest link over power-circuit lines."""
    comps = []
    for line in active_bom_lines(panel["id"]):
        c = db.components.get(line["component_id"])
        if c is None:
            continue
        if c["component_class"] in POWER_CLASSES and c.get("sccr_ka") is not None:
            comps.append(c)
    if not comps:
        panel["sccr_rating_ka"] = 0
        return
    has_cl_bpd = any(
        c["component_class"] == "BRANCH_PROTECTIVE"
        and c["sccr_ka"] >= CURRENT_LIMITING_THRESHOLD_KA
        for c in comps
    )
    vals = []
    for c in comps:
        v = c["sccr_ka"]
        if has_cl_bpd and c["component_class"] in ("CONTACTOR", "OVERLOAD"):
            v = max(v, CONTROL_BRANCH_FLOOR_KA)
        vals.append(v)
    panel["sccr_rating_ka"] = min(vals)


# ---------------------------------------------------------------------------
# substitution_lead_time_delta (variants selected by Job.status)
# ---------------------------------------------------------------------------


def lead_time_delta(proposed_component, original_component, job_status):
    raw = proposed_component["lead_time_days"] - original_component["lead_time_days"]
    if job_status in ("BUILD", "TEST", "READY_TO_SHIP", "SHIPPED", "COMMISSIONED"):
        # optimistic: expediting erases increases; decreases kept as-is
        return min(raw, 0)
    # pessimistic (DESIGN, PROCUREMENT, and any other posture): risk pad on increases
    return raw + RISK_PAD_DAYS if raw > 0 else raw


# ---------------------------------------------------------------------------
# change_order_pricing (pinned evaluation order; tier on PRE-discount delta)
# ---------------------------------------------------------------------------


def change_order_computed_delta(price_delta_cents, discount_pct):
    if price_delta_cents < 0:
        # credits pass through undiscounted; a discount never deepens a credit
        return price_delta_cents
    if price_delta_cents < 100000:
        floor = Decimal("0.00")
    elif price_delta_cents < 500000:
        floor = Decimal("0.05")
    else:
        floor = Decimal("0.10")
    effective = max(Decimal(str(discount_pct)), floor)
    return _rhup(Decimal(price_delta_cents) * (Decimal("1") - effective))


# ---------------------------------------------------------------------------
# startup_labor_billing (waterfall; OT rate rounded to the cent FIRST)
# ---------------------------------------------------------------------------


def startup_billable(labor_hours, scheduled_start_dt):
    h = Decimal(str(labor_hours))
    base_h = min(h, Decimal(INCLUDED_BASE_HOURS))
    ot_h = min(max(h - Decimal(INCLUDED_BASE_HOURS), Decimal(0)), Decimal(OT_CAP_HOURS - INCLUDED_BASE_HOURS))
    em_h = max(h - Decimal(OT_CAP_HOURS), Decimal(0))
    ot_rate = Decimal(BASE_RATE) * Decimal("1.5")
    ot_rate = ot_rate.quantize(Decimal("1"), rounding=ROUND_HALF_UP)  # 27800
    raw = base_h * Decimal(BASE_RATE) + ot_h * ot_rate + em_h * Decimal(BASE_RATE) * 2
    # Saturday/Sunday (UTC) multiplier on the whole bill
    mult = WEEKEND_MULT if scheduled_start_dt.weekday() >= 5 else Decimal("1")
    return _rhup(raw * mult)


# ---------------------------------------------------------------------------
# warranty_liability (provisional / final variants)
# ---------------------------------------------------------------------------


def warranty_liability(claim, variant):
    job = db.jobs[claim["job_id"]]
    customer = db.customers[job["customer_id"]]
    commissioned = [
        p
        for p in db.panels.values()
        if p["job_id"] == job["id"] and p["status"] == "COMMISSIONED" and p.get("_commissioned_dt")
    ]
    proxy = max(p["_commissioned_dt"] for p in commissioned)
    days = (claim["_filed_dt"] - proxy).total_seconds() / 86400.0
    months_in_service = math.floor(days / 30.0)
    rate = TIER_RATE[customer["warranty_labor_tier"]]
    labor_cents = _rhup(Decimal(str(claim["claimed_labor_hours"])) * Decimal(rate))
    if variant == "provisional":
        # conservative accrual: no age-decay halving, no deductible
        return min(labor_cents + PARTS_ALLOWANCE_CENTS, CAP_CENTS)
    # final variant: age decay then cap then deductible floored at 0
    if months_in_service * 2 > job["warranty_months"]:
        labor_cents = _rhup(Decimal(labor_cents) / Decimal(2))
    subtotal = labor_cents + PARTS_ALLOWANCE_CENTS
    return max(min(subtotal, CAP_CENTS) - DEDUCTIBLE_CENTS, 0)


# ---------------------------------------------------------------------------
# as_built_completeness (weighted scoring)
# ---------------------------------------------------------------------------


def asbuilt_completeness_pct(pkg):
    score = (
        W_WIRING * (1 if pkg["has_wiring_diagram"] else 0)
        + W_PROGRAM * (1 if pkg["has_program_archive"] else 0)
        + W_TEST * (1 if pkg["has_test_report"] else 0)
        + W_LABEL * (1 if pkg["has_ul_label_photo"] else 0)
    )
    return _rhup(score * 100)


def recompute_asbuilt(pkg):
    """Recompute completeness and apply the auto-transitions."""
    pkg["completeness_pct"] = asbuilt_completeness_pct(pkg)
    if pkg["status"] == "INCOMPLETE" and pkg["completeness_pct"] == 100:
        pkg["status"] = "PENDING_REVIEW"
        bump(pkg)
    elif pkg["status"] == "PENDING_REVIEW" and pkg["completeness_pct"] < 100:
        # document withdrawal regresses the package
        pkg["status"] = "INCOMPLETE"
        bump(pkg)


# ---------------------------------------------------------------------------
# job_posture_derivation (compound posture, top-down)
# ---------------------------------------------------------------------------

AUTO_TRANSITIONS = {
    ("OPEN", "DESIGN"),
    ("DESIGN", "PROCUREMENT"),
    ("PROCUREMENT", "BUILD"),
    ("BUILD", "TEST"),
    ("TEST", "READY_TO_SHIP"),
    ("SHIPPED", "COMMISSIONED"),
}

PANELS_TEST_PASSED_PLUS = ("TEST_PASSED", "READY_FOR_LABEL", "LABELED", "SHIPPED", "COMMISSIONED")


def derive_posture(job):
    panels = [p for p in db.panels.values() if p["job_id"] == job["id"]]
    if not panels:
        return "OPEN"
    if any(p["status"] in ("DESIGN", "DESIGN_REVIEW") for p in panels):
        return "DESIGN"
    panel_ids = {p["id"] for p in panels}
    lines = [l for l in db.panel_components.values() if l["panel_id"] in panel_ids]
    if any(l["line_status"] in ("PENDING", "ORDERED") for l in lines):
        return "PROCUREMENT"
    if any(p["status"] in ("PROCUREMENT", "WIRING") for p in panels):
        return "BUILD"
    if any(p["status"] in ("POINT_TO_POINT", "TEST_FAILED") for p in panels):
        return "TEST"
    all_tp_plus = all(p["status"] in PANELS_TEST_PASSED_PLUS for p in panels)
    pkgs = [
        next((q for q in db.as_built_packages.values() if q["panel_id"] == p["id"]), None)
        for p in panels
    ]
    all_released = all(q is not None and q["status"] == "RELEASED" for q in pkgs)
    all_shipped_or_comm = all(p["status"] in ("SHIPPED", "COMMISSIONED") for p in panels)
    if all_tp_plus and all_released and not all_shipped_or_comm:
        return "READY_TO_SHIP"
    if all_shipped_or_comm:
        if all(p["status"] == "COMMISSIONED" for p in panels):
            return "COMMISSIONED"
        return "SHIPPED"
    # panels past testing but as-built gate not yet cleared
    return "TEST"


def reevaluate_job_posture(job):
    """Re-derive and fire declared auto-transitions. Never fires while the job
    is ON_HOLD or CLOSED; posture changes only ever fire through declared
    transitions."""
    if job["status"] in ("ON_HOLD", "CLOSED"):
        return
    while True:
        derived = derive_posture(job)
        if derived != job["status"] and (job["status"], derived) in AUTO_TRANSITIONS:
            job["status"] = derived
            if derived == "COMMISSIONED":
                latest = max(
                    p["_commissioned_dt"]
                    for p in db.panels.values()
                    if p["job_id"] == job["id"] and p.get("_commissioned_dt") is not None
                )
                job["warranty_expires_at"] = now_iso_of(add_months(latest, job["warranty_months"]))
            bump(job)
        else:
            break


def now_iso_of(dt):
    from core import iso

    return iso(dt)
