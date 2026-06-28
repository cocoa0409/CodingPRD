"""Domain services: entity lifecycle, computed-field reconciliation,
calculations, state transitions, and cascades.

Every behavior traces to a verbatim PRD sentence (see inline references).
"""
from datetime import timedelta

from clock import clock, parse_iso8601
from common import add_months, round_half_up
from constants import (
    ADDON_MINUTES_EACH,
    BIG_HOME_FACTOR,
    BUFFER_MINUTES,
    DENSITY_WEIGHT,
    DRYER_MINUTES_PER_LINE,
    DUCT_MINUTES_PER_LINE,
    LARGE_HOME_SQFT,
    MULTI_SYSTEM_THRESHOLD,
    REFERRAL_RISK_THRESHOLD,
    REFERRAL_TTL_DAYS,
    RISK_CEILING,
    SANITIZE_MINUTES_PER_LINE,
    SETUP_MINUTES,
    SEVERITY_WEIGHT,
)
from db import db, new_id, now_iso
from errors import err


# ==========================================================================
# Common-field helpers
# ==========================================================================
def stamp_new(record):
    """Set system common fields on a freshly created record (PRD §2.4)."""
    ts = now_iso()
    record["id"] = new_id()
    record["created_at"] = ts
    record["updated_at"] = ts
    record["version"] = 1
    record["_seq"] = db.next_seq()
    return record


def touch(record):
    """Mutation: refresh updated_at and bump version (PRD §2.4, §2.5)."""
    record["updated_at"] = now_iso()
    record["version"] += 1


# ==========================================================================
# Home computed-field reconciliation (PRD §2.5, §3.1, §3.9)
# ==========================================================================
def recompute_home_active_system_count(home):
    home["active_system_count"] = sum(
        1
        for s in db.hvac_systems.values()
        if s["home_id"] == home["id"] and s["status"] == "ACTIVE"
    )


def recompute_home_has_active_plan(home):
    home["has_active_plan"] = any(
        p["home_id"] == home["id"] and p["lifecycle_status"] == "ACTIVE"
        for p in db.recurring_plans.values()
    )


# ==========================================================================
# Route committed-minutes ledger (calc route_committed_minutes, PRD §3.7)
# ==========================================================================
def recompute_committed_minutes(route):
    """Full recompute over committed work orders in SCHEDULED/IN_PROGRESS/COMPLETED."""
    route["committed_minutes"] = sum(
        wo["duration_minutes"] or 0
        for wo in db.work_orders.values()
        if wo["route_plan_id"] == route["id"]
        and wo["status"] in ("SCHEDULED", "IN_PROGRESS", "COMPLETED")
    )


# ==========================================================================
# Pricing engine (calc estimate_total / invoice_total, PRD §3.4, §3.8)
# ==========================================================================
def _price_from_lines(cfg, service_lines, addons, active_system_count,
                      has_active_plan):
    """Shared tiered-pricing arithmetic for both estimate and invoice.

    Round half up at each pinned step (discount, then plan, then tax),
    round-per-step then sum (PRD §2.7, §3.4).
    """
    n = active_system_count

    duct_lines = sum(1 for sl in service_lines if sl["service_type"] == "DUCT")
    sanitize_lines = sum(
        1 for sl in service_lines if sl["service_type"] == "SANITIZE"
    )
    dryer_lines = sum(
        1 for sl in service_lines if sl["service_type"] == "DRYER_VENT"
    )

    duct_subtotal = duct_lines * (
        cfg["duct_base_cents"] + max(0, n - 1) * cfg["duct_per_system_cents"]
    )
    sanitize_subtotal = sanitize_lines * cfg["sanitize_per_system_cents"]
    dryer_subtotal = dryer_lines * cfg["dryer_vent_flat_cents"]

    # Multi-system discount applies ONLY to the duct line subtotal.
    if n >= MULTI_SYSTEM_THRESHOLD:
        duct_subtotal = round_half_up(
            duct_subtotal * (1 - cfg["multi_system_discount_pct"])
        )

    # Add-on subtotal over DISTINCT addon codes.
    addon_price = {
        "SANITIZER": cfg["addon_sanitizer_cents"],
        "UV": cfg["addon_uv_cents"],
        "COIL": cfg["addon_coil_cents"],
    }
    addon_subtotal = sum(addon_price[code] for code in set(addons))

    service_subtotal = (
        duct_subtotal + sanitize_subtotal + dryer_subtotal + addon_subtotal
    )

    # Plan-member discount applies to the WHOLE service subtotal, AFTER the
    # multi-system discount (evaluation order pinned).
    if has_active_plan:
        service_subtotal = round_half_up(
            service_subtotal * (1 - cfg["plan_member_discount_pct"])
        )

    tax = round_half_up(service_subtotal * cfg["tax_pct"])
    return service_subtotal + tax


def compute_estimate_total(work_order, home, cfg):
    """Estimate: requested lines + config-at-quote + live home counts."""
    return _price_from_lines(
        cfg,
        work_order["service_lines"],
        work_order["addons"],
        home["active_system_count"],
        home["has_active_plan"],
    )


def compute_invoice_total(performed_service_lines, performed_addons, home, cfg):
    """Invoice: performed lines + pinned config + live home counts at complete."""
    return _price_from_lines(
        cfg,
        performed_service_lines,
        performed_addons,
        home["active_system_count"],
        home["has_active_plan"],
    )


# ==========================================================================
# Duration estimate (calc work_order_duration, PRD §3.5)
# ==========================================================================
def compute_duration_minutes(work_order, home):
    n = home["active_system_count"]
    service_lines = work_order["service_lines"]
    addons = work_order["addons"]

    duct_lines = sum(1 for sl in service_lines if sl["service_type"] == "DUCT")
    sanitize_lines = sum(
        1 for sl in service_lines if sl["service_type"] == "SANITIZE"
    )
    dryer_lines = sum(
        1 for sl in service_lines if sl["service_type"] == "DRYER_VENT"
    )

    per_line = (
        duct_lines * DUCT_MINUTES_PER_LINE
        + sanitize_lines * SANITIZE_MINUTES_PER_LINE
        + dryer_lines * DRYER_MINUTES_PER_LINE
    )
    per_addon = len(set(addons)) * ADDON_MINUTES_EACH

    # Big-home surcharge: only the per-line portion, only when BOTH system
    # count high AND square footage high.
    if n >= MULTI_SYSTEM_THRESHOLD and home["square_footage"] >= LARGE_HOME_SQFT:
        per_line = round_half_up(per_line * BIG_HOME_FACTOR)

    return SETUP_MINUTES + per_line + per_addon


# ==========================================================================
# Contamination risk score (calc contamination_risk_score, PRD §3.8)
# ==========================================================================
def compute_risk_score(after_inspection, home):
    n = home["active_system_count"]
    base = after_inspection["dust_severity"] * SEVERITY_WEIGHT
    register_sum = sum(
        s["register_count"]
        for s in db.hvac_systems.values()
        if s["home_id"] == home["id"] and s["status"] == "ACTIVE"
    )
    density = round_half_up(register_sum / max(1, n))
    score = base + density * DENSITY_WEIGHT
    if score > RISK_CEILING:
        score = RISK_CEILING
    if score < 0:
        score = 0
    return score


# ==========================================================================
# Slot overlap geometry (calc route_slot_overlap, PRD §3.7)
# ==========================================================================
def slot_overlaps(route, new_start, new_duration, exclude_wo_id=None):
    """Half-open intervals expanded by BUFFER_MINUTES on both sides."""
    nb_start = new_start - BUFFER_MINUTES
    nb_end = new_start + new_duration + BUFFER_MINUTES
    for wo in db.work_orders.values():
        if wo["route_plan_id"] != route["id"]:
            continue
        if exclude_wo_id is not None and wo["id"] == exclude_wo_id:
            continue
        if wo["status"] not in ("SCHEDULED", "IN_PROGRESS", "COMPLETED"):
            continue
        ex_start = wo["scheduled_start_minute"]
        ex_end = ex_start + wo["duration_minutes"]
        # overlap if buffered_new.start < ex.end AND ex.start < buffered_new.end
        if nb_start < ex_end and ex_start < nb_end:
            return True
    return False


# ==========================================================================
# Reminder advance (calc next_reminder_advance, PRD §3.9)
# ==========================================================================
def advance_reminder(plan):
    """DUE -> ACKNOWLEDGED -> WAITING; advance next_reminder_at by cadence."""
    prior = parse_iso8601(plan["next_reminder_at"])
    from clock import format_iso8601

    plan["next_reminder_at"] = format_iso8601(
        add_months(prior, plan["cadence_months"])
    )
    # ACKNOWLEDGED then immediately re-armed to WAITING for the next cycle.
    plan["reminder_status"] = "WAITING"


# ==========================================================================
# Clock-driven re-evaluation (PRD §2.9): due reminders + TTL-expired referrals
# ==========================================================================
def reevaluate_clock_driven():
    now = clock.now()

    # Due reminders: WAITING -> DUE for ACTIVE plans whose next_reminder_at reached.
    for plan in db.recurring_plans.values():
        if (
            plan["lifecycle_status"] == "ACTIVE"
            and plan["reminder_status"] == "WAITING"
        ):
            due_at = parse_iso8601(plan["next_reminder_at"])
            if due_at is not None and now >= due_at:
                plan["reminder_status"] = "DUE"
                touch(plan)

    # TTL-expired referrals: PENDING -> EXPIRED after REFERRAL_TTL_DAYS.
    for referral in db.upsell_referrals.values():
        if referral["status"] == "PENDING":
            created = parse_iso8601(referral["created_at"])
            if created is not None and now >= created + timedelta(
                days=REFERRAL_TTL_DAYS
            ):
                referral["status"] = "EXPIRED"
                touch(referral)
