"""Derived-field reconciliation, ledgers, cascades and serializers."""

from decimal import Decimal

import calc
from store import apply, collection, db, fmt_dt, now_iso, sort_rows, touch


# --------------------------------------------------------------------------
# serialization helpers
# --------------------------------------------------------------------------
def fnum(value):
    if value is None:
        return None
    if isinstance(value, Decimal):
        return float(value)
    return value


def pick(row, fields):
    out = {"id": row["id"]}
    for name in fields:
        out[name] = fnum(row.get(name))
    out["created_at"] = row.get("created_at")
    if "updated_at" in row:
        out["updated_at"] = row.get("updated_at")
    if "version" in row:
        out["version"] = row.get("version")
    return out


PACKAGE_FIELDS = (
    "name",
    "floor_count",
    "total_area_sqm",
    "contract_value_cents",
    "unit_rate_cents_per_sqm",
    "base_labor_rate_cents_per_hour",
    "design_temp_delta_c",
    "weather_tightness_deadline_date",
    "system_type",
    "state",
    "engineering_posture",
    "blocking_submittal_count",
    "open_critical_defect_count",
    "planned_shop_hours",
    "planned_field_crew_size",
    "certified_area_sqm",
    "earned_value_certified_cents",
    "retention_held_cents",
    "mockup_qualified",
    "weather_tight_zone_count",
    "closeout_note",
)

SUBMITTAL_FIELDS = (
    "package_id",
    "submittal_type",
    "title",
    "drawing_set_ref",
    "delegated_design_scope",
    "state",
    "revision_cycle",
    "sealed_by_user_id",
    "seal_license_no",
    "sealed_at",
    "reviewed_by_user_id",
    "review_decision",
    "open_notes_count",
    "escalation_ref",
    "dispute_resolution_ref",
    "reopen_reason",
)

RELEASE_FIELDS = (
    "package_id",
    "submittal_id",
    "glass_order_id",
    "zone_ids",
    "panels_per_zone",
    "lites_per_panel",
    "state",
    "system_type_at_release",
    "lot_count",
    "revoked_reason",
    "released_at",
)

GLASS_ORDER_FIELDS = (
    "package_id",
    "supplier_name",
    "coating_code",
    "quoted_lead_time_days",
    "ordered_lites",
    "expedite_authorized",
    "expedite_tier",
    "state",
    "coating_revision_count",
    "re_fire_required",
    "risk_variant",
    "risk_score",
    "risk_flag",
    "effective_lead_days",
    "last_risk_computed_at",
    "received_lites",
    "breakage_stock_lites",
)

DRAW_FIELDS = (
    "glass_order_id",
    "panel_lot_id",
    "quantity_lites",
    "reason",
    "status",
    "cancelled_reason",
)

LOT_FIELDS = (
    "release_id",
    "glass_order_id",
    "zone_id",
    "lot_code",
    "panel_count",
    "lite_count",
    "fabrication_status",
    "hold_reason",
    "status_before_hold",
    "shipped_at",
)

LAB_FIELDS = ("name", "chamber_capacity", "accreditation_ref")

MOCKUP_FIELDS = (
    "package_id",
    "test_lab_id",
    "retest_of_test_id",
    "attempt_no",
    "window_start",
    "window_end",
    "chambers_required",
    "state",
    "chamber_hours",
    "invoice_subtotal_cents",
    "surcharge_cents",
    "invoice_cents",
    "air_infiltration_cfm",
    "water_penetration_observed",
    "structural_deflection_mm",
    "result_recorded_at",
)

SURVEY_FIELDS = (
    "zone_id",
    "embed_layout_ref",
    "planned_anchor_count",
    "tolerance_mm",
    "state",
    "surveyed_anchor_count",
    "max_deviation_mm",
    "survey_attempt_count",
    "surveyed_by_user_id",
    "poured_at",
)

ZONE_FIELDS = (
    "package_id",
    "floor_number",
    "elevation_label",
    "area_sqm",
    "height_m",
    "span_mm",
    "anchor_type",
    "designed_joint_mm",
    "planned_panel_count",
    "budget_crew_hours",
    "install_status",
    "weather_status",
    "thermal_movement_allowance_mm",
    "deflection_limit_mm",
    "provisional_labor_cost_cents",
    "final_labor_cost_cents",
    "certified_line_cents",
    "weather_tight_at",
    "weather_tight_cycle_count",
    "hang_completed_at",
    "certification_note",
)

CREW_DAY_FIELDS = (
    "zone_id",
    "work_date",
    "crew_size",
    "shift_hours",
    "panels_installed",
    "status",
    "day_index",
    "straight_person_hours",
    "overtime_person_hours",
    "day_cost_cents",
    "void_reason",
)

RIG_FIELDS = (
    "package_id",
    "rig_code",
    "rig_kind",
    "capacity_panels_per_shift",
    "changeover_buffer_minutes",
    "status",
)

RESERVATION_FIELDS = (
    "rig_id",
    "zone_id",
    "window_start",
    "window_end",
    "planned_panel_count",
    "status",
    "blocked_from",
    "blocked_until",
    "cancelled_reason",
)

FIELD_TEST_FIELDS = (
    "zone_id",
    "test_kind",
    "scheduled_for",
    "attempt_no",
    "state",
    "water_penetration_observed",
    "measured_air_leakage_cfm",
    "measured_deflection_mm",
    "outcome_reason",
    "recorded_by_user_id",
    "result_recorded_at",
)

DEFECT_FIELDS = (
    "package_id",
    "zone_id",
    "field_test_id",
    "mockup_test_id",
    "origin",
    "severity",
    "description",
    "status",
    "raised_by_user_id",
    "remediation_note",
    "reinspected_by_user_id",
    "reinspect_fail_count",
    "waiver_ref",
    "closed_at",
)


def ser_package(row):
    return pick(row, PACKAGE_FIELDS)


def ser_submittal(row):
    return pick(row, SUBMITTAL_FIELDS)


def ser_release(row):
    return pick(row, RELEASE_FIELDS)


def ser_glass_order(row):
    out = pick(row, GLASS_ORDER_FIELDS)
    out.update(order_ledger(row))
    return out


def ser_draw(row):
    return pick(row, DRAW_FIELDS)


def ser_lot(row):
    return pick(row, LOT_FIELDS)


def ser_lab(row):
    return pick(row, LAB_FIELDS)


def ser_mockup(row):
    return pick(row, MOCKUP_FIELDS)


def ser_survey(row):
    return pick(row, SURVEY_FIELDS)


def ser_zone(row):
    out = pick(row, ZONE_FIELDS)
    consumed, remaining = crew_hour_ledger(row)
    out["consumed_crew_hours"] = float(consumed)
    out["remaining_crew_hours"] = float(remaining)
    return out


def ser_crew_day(row):
    return pick(row, CREW_DAY_FIELDS)


def ser_rig(row):
    return pick(row, RIG_FIELDS)


def ser_reservation(row):
    return pick(row, RESERVATION_FIELDS)


def ser_field_test(row):
    return pick(row, FIELD_TEST_FIELDS)


def ser_defect(row):
    return pick(row, DEFECT_FIELDS)


# --------------------------------------------------------------------------
# ledgers (PRD §2.10)
# --------------------------------------------------------------------------
def order_ledger(order):
    """Glass lite ledger, computed from the live child rows on every read."""
    if order["state"] in ("RECEIVED", "CLOSED") and order.get("received_lites") is not None:
        committable = int(order["received_lites"])
    else:
        committable = int(order["ordered_lites"])
    allocated = 0
    for lot in db.lots.values():
        if lot["glass_order_id"] == order["id"]:
            allocated += int(lot["lite_count"])
    breakage = int(order.get("breakage_stock_lites") or 0)
    drawn = 0
    for draw in db.draws.values():
        if draw["glass_order_id"] == order["id"] and draw["status"] == "DRAWN":
            drawn += int(draw["quantity_lites"])
    return {
        "committable_lites": committable,
        "allocated_lites": allocated,
        "breakage_stock_lites": breakage,
        "drawn_lites": drawn,
        "available_stock_lites": breakage - drawn,
        "unallocated_lites": committable - allocated - breakage,
    }


def crew_hour_ledger(zone):
    """Zone crew-hour ledger, 1 decimal place, may go negative."""
    total = Decimal(0)
    for log in db.crew_days.values():
        if log["zone_id"] == zone["id"] and log["status"] == "POSTED":
            total += calc.D(log["crew_size"]) * calc.D(log["shift_hours"])
    consumed = calc.rhu(total, 1)
    remaining = calc.rhu(calc.D(zone["budget_crew_hours"]) - consumed, 1)
    return consumed, remaining


# --------------------------------------------------------------------------
# package derived reconciliation
# --------------------------------------------------------------------------
def package_of(row):
    return db.packages.get(row.get("package_id"))


def zone_package(zone):
    return db.packages.get(zone["package_id"])


def open_critical_defects(package_id, zone_id=None):
    out = []
    for item in db.defects.values():
        if item["package_id"] != package_id:
            continue
        if zone_id is not None and item.get("zone_id") != zone_id:
            continue
        if item["severity"] == "CRITICAL" and item["status"] in (
            "OPEN",
            "REMEDIATION_SUBMITTED",
        ):
            out.append(item)
    return out


def posture_fields(package):
    package_id = package["id"]
    blocking = 0
    escalated = False
    for sub in db.submittals.values():
        if sub["package_id"] != package_id:
            continue
        if sub["state"] in ("REVISION_REQUIRED", "ESCALATED"):
            blocking += 1
        if sub["state"] == "ESCALATED":
            escalated = True
    critical = len(open_critical_defects(package_id))
    if escalated or critical >= calc.FROZEN_AT_OPEN_CRITICAL:
        posture = "FROZEN"
    elif blocking >= 1 or critical >= calc.RESTRICTED_AT_OPEN_CRITICAL:
        posture = "RESTRICTED"
    else:
        posture = "OPEN"
    return {
        "engineering_posture": posture,
        "blocking_submittal_count": blocking,
        "open_critical_defect_count": critical,
    }


def certified_zones(package_id):
    rows = [
        zone
        for zone in db.zones.values()
        if zone["package_id"] == package_id and zone["weather_status"] == "WEATHER_TIGHT"
    ]
    return sorted(
        rows,
        key=lambda z: (z.get("weather_tight_at") or "", z.get("created_at") or "", z.get("_seq", 0)),
    )


def earned_value_view(package):
    zones = certified_zones(package["id"])
    subtotal = 0
    area = Decimal(0)
    for zone in zones:
        subtotal += calc.certified_line_cents(
            zone["area_sqm"], package["unit_rate_cents_per_sqm"]
        )
        area += calc.D(zone["area_sqm"])
    retention = calc.retention_cents(subtotal)
    return {
        "certified_area_sqm": calc.rhu(area, 2),
        "certified_subtotal_cents": subtotal,
        "retention_held_cents": retention,
        "earned_value_certified_cents": subtotal - retention,
        "weather_tight_zone_count": len(zones),
    }


def ev_fields(package):
    view = earned_value_view(package)
    return {
        "certified_area_sqm": view["certified_area_sqm"],
        "earned_value_certified_cents": view["earned_value_certified_cents"],
        "retention_held_cents": view["retention_held_cents"],
        "weather_tight_zone_count": view["weather_tight_zone_count"],
    }


def mockup_qualified(package_id):
    for test in db.mockups.values():
        if test["package_id"] == package_id and test["state"] == "PASSED":
            return True
    return False


def sync_package(package, extra=None):
    """Re-derive every computed package field from scratch; single version bump."""
    updates = {}
    updates.update(posture_fields(package))
    if package["state"] != "CLOSED_OUT":
        updates.update(ev_fields(package))
    updates["mockup_qualified"] = mockup_qualified(package["id"])
    if extra:
        updates.update(extra)
    return apply(package, updates)


# --------------------------------------------------------------------------
# zone derived limits
# --------------------------------------------------------------------------
def zone_limit_fields(zone, package):
    return {
        "thermal_movement_allowance_mm": calc.thermal_movement_allowance_mm(
            package["system_type"],
            zone["anchor_type"],
            zone["span_mm"],
            package["design_temp_delta_c"],
            zone["height_m"],
        ),
        "deflection_limit_mm": calc.deflection_limit_mm(
            package["system_type"], zone["span_mm"]
        ),
    }


def zone_final_labor_cents(zone):
    logs = sort_rows(
        [
            log
            for log in db.crew_days.values()
            if log["zone_id"] == zone["id"] and log["status"] == "POSTED"
        ]
    )
    logs.sort(key=lambda log: (log["work_date"], log["created_at"], log["_seq"]))
    return sum(int(log["day_cost_cents"]) for log in logs)


def reindex_crew_days(zone_id):
    logs = [
        log
        for log in db.crew_days.values()
        if log["zone_id"] == zone_id and log["status"] == "POSTED"
    ]
    logs.sort(key=lambda log: (log["work_date"], log["created_at"], log["_seq"]))
    for index, log in enumerate(logs, start=1):
        log["day_index"] = index


# --------------------------------------------------------------------------
# cascades
# --------------------------------------------------------------------------
def revert_zone_weather(zone):
    """A certified zone loses weather-tightness; roll the package back."""
    if zone["weather_status"] != "WEATHER_TIGHT":
        return
    apply(
        zone,
        {
            "weather_status": "REMEDIATION",
            "weather_tight_at": None,
            "certified_line_cents": None,
        },
    )
    package = zone_package(zone)
    if package is None:
        return
    extra = None
    if package["state"] == "WEATHER_TIGHT_ACHIEVED":
        extra = {"state": "IN_INSTALLATION"}
    sync_package(package, extra)


def hold_lots_of_release(release, reason):
    for lot in sort_rows(list(db.lots.values())):
        if lot["release_id"] != release["id"]:
            continue
        if lot["fabrication_status"] not in ("BATCHED", "GLAZED"):
            continue
        apply(
            lot,
            {
                "status_before_hold": lot["fabrication_status"],
                "fabrication_status": "ON_HOLD",
                "hold_reason": reason,
            },
        )
        zone = db.zones.get(lot["zone_id"])
        if zone is not None:
            revert_zone_weather(zone)


def revoke_releases(reason, submittal_id=None, glass_order_id=None):
    for release in sort_rows(list(db.releases.values())):
        if release["state"] != "RELEASED":
            continue
        if submittal_id is not None and release["submittal_id"] != submittal_id:
            continue
        if glass_order_id is not None and release["glass_order_id"] != glass_order_id:
            continue
        apply(release, {"state": "REVOKED", "revoked_reason": reason})
        hold_lots_of_release(release, reason)


def unhold_lots_for_release(release, zone_ids):
    """A superseding release re-points what a previous revision froze."""
    for lot in sort_rows(list(db.lots.values())):
        if lot["zone_id"] not in zone_ids:
            continue
        if lot["fabrication_status"] != "ON_HOLD":
            continue
        if lot["hold_reason"] != "SUBMITTAL_REVISION":
            continue
        restored = lot.get("status_before_hold") or "BATCHED"
        apply(
            lot,
            {
                "fabrication_status": restored,
                "hold_reason": None,
                "status_before_hold": None,
                "release_id": release["id"],
            },
        )


def maybe_close_release(release):
    lots = [lot for lot in db.lots.values() if lot["release_id"] == release["id"]]
    if not lots:
        return
    if all(lot["fabrication_status"] == "SHIPPED" for lot in lots):
        if release["state"] == "RELEASED":
            apply(release, {"state": "CLOSED"})


def maybe_close_order(order):
    lots = [lot for lot in db.lots.values() if lot["glass_order_id"] == order["id"]]
    if not lots:
        return
    if not all(lot["fabrication_status"] == "SHIPPED" for lot in lots):
        return
    ledger = order_ledger(order)
    if ledger["unallocated_lites"] != 0:
        return
    if order["state"] == "RECEIVED":
        apply(order, {"state": "CLOSED"})


def risk_updates(order, coating_revision_count=None, expedite_tier=None):
    """Re-derive the procurement risk block; returns (updates, new_flag)."""
    from store import as_date, clock_date

    package = package_of(order)
    deadline = as_date(package["weather_tightness_deadline_date"]) if package else None
    days_to_deadline = 0 if deadline is None else (deadline - clock_date()).days
    revisions = (
        order["coating_revision_count"]
        if coating_revision_count is None
        else coating_revision_count
    )
    tier = order["expedite_tier"] if expedite_tier is None else expedite_tier
    score, effective, variant, flag = calc.risk_score(
        order["quoted_lead_time_days"], revisions, tier, days_to_deadline
    )
    updates = {
        "risk_score": score,
        "effective_lead_days": effective,
        "risk_variant": variant,
        "risk_flag": flag,
        "last_risk_computed_at": now_iso(),
    }
    return updates, flag


def all_lots_shipped_for_zone(zone_id):
    lots = [lot for lot in db.lots.values() if lot["zone_id"] == zone_id]
    if not lots:
        return False
    return all(lot["fabrication_status"] == "SHIPPED" for lot in lots)


def zone_children(mapping, zone_id, **filters):
    return collection(mapping, zone_id=zone_id, **filters)


def fmt(value):
    return fmt_dt(value)


__all__ = [name for name in dir() if not name.startswith("_")]
