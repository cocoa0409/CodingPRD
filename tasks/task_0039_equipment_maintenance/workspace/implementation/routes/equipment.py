"""Equipment routes: create, get, patch, lifecycle transitions, alarms."""
from flask import Blueprint

from db import db, new_id, parse_iso
from errors import (
    ERR_BAD_REQUEST,
    ERR_EQUIPMENT_BUSY,
    ERR_INVALID_STATE,
    ERR_NO_ACTIVE_PLAN,
    ERR_TEMPORAL_INVALID,
    raise_err,
)
from middleware import require_role
from response import success_object
from services.audit import append_audit
from services.calculations import recompute_sla_breached
from services.common import (
    bump_version,
    check_version,
    get_equipment_or_404,
    get_json_body,
    get_site_or_404,
)
from services.serialize import serialize_alarm, serialize_equipment
from services.work_order import (
    recompute_priority_for_open_work_orders_of_equipment,
    run_plan_generation_on_alarm,
)

bp = Blueprint("equipment", __name__)


VALID_CATEGORIES = {"PUMP", "COMPRESSOR", "HVAC", "CONVEYOR", "BOILER"}
VALID_CRITICALITY = {"LOW", "MEDIUM", "HIGH"}
VALID_SEVERITY = {"INFO", "WARN", "CRITICAL"}


@bp.route("/sites/<site_id>/equipment", methods=["POST"])
def create_equipment(site_id):
    require_role(["SiteManager"])
    site = get_site_or_404(site_id)
    body = get_json_body()

    required = ["asset_tag", "category", "location", "responsible_user_id",
                "technical_spec", "criticality", "warranty_start", "warranty_end"]
    for f in required:
        if f not in body or body.get(f) in (None, ""):
            raise_err(ERR_BAD_REQUEST, f"{f} is required")

    if body["category"] not in VALID_CATEGORIES:
        raise_err(ERR_BAD_REQUEST, "invalid category")
    if body["criticality"] not in VALID_CRITICALITY:
        raise_err(ERR_BAD_REQUEST, "invalid criticality")

    try:
        ws = parse_iso(body["warranty_start"])
        we = parse_iso(body["warranty_end"])
    except Exception:
        raise_err(ERR_BAD_REQUEST, "invalid warranty datetime")

    if we <= ws:
        raise_err(ERR_TEMPORAL_INVALID, "warranty_end must be > warranty_start")

    usage_counter = body.get("usage_counter", 0)
    if not isinstance(usage_counter, int) or isinstance(usage_counter, bool) or usage_counter < 0:
        raise_err(ERR_BAD_REQUEST, "usage_counter must be a non-negative integer")

    technical_spec = body["technical_spec"]
    if not isinstance(technical_spec, dict):
        raise_err(ERR_BAD_REQUEST, "technical_spec must be an object")

    asset_tag = body["asset_tag"]
    if not isinstance(asset_tag, str) or not asset_tag.strip():
        raise_err(ERR_BAD_REQUEST, "asset_tag must be a non-empty string")
    # uniqueness per site (best-effort; not in error catalog so we 400)
    for e in db.equipment_for_site(site_id):
        if e["asset_tag"] == asset_tag:
            raise_err(ERR_BAD_REQUEST, "asset_tag must be unique per site")

    eid = new_id()
    clock = db.site_clock(site_id)
    e = {
        "id": eid,
        "created_at": clock,
        "updated_at": clock,
        "version": 1,
        "site_id": site_id,
        "asset_tag": asset_tag,
        "category": body["category"],
        "location": body["location"],
        "responsible_user_id": body["responsible_user_id"],
        "technical_spec": technical_spec,
        "criticality": body["criticality"],
        "warranty_start": ws,
        "warranty_end": we,
        "lifecycle_status": "INSTALLED",
        "usage_counter": usage_counter,
        "last_failure_at": None,
        "last_repair_completed_at": None,
        "open_work_order_id": None,
    }
    db.equipment[eid] = e
    return success_object(serialize_equipment(e), 201)


@bp.route("/sites/<site_id>/equipment/<equipment_id>", methods=["GET"])
def get_equipment(site_id, equipment_id):
    require_role(["Any"])
    get_site_or_404(site_id)
    e = get_equipment_or_404(site_id, equipment_id)
    return success_object(serialize_equipment(e))


@bp.route("/sites/<site_id>/equipment/<equipment_id>", methods=["PATCH"])
def patch_equipment(site_id, equipment_id):
    require_role(["SiteManager"])
    get_site_or_404(site_id)
    e = get_equipment_or_404(site_id, equipment_id)
    body = get_json_body()
    check_version(e, body)

    changed_criticality = False
    if "criticality" in body:
        c = body["criticality"]
        if c not in VALID_CRITICALITY:
            raise_err(ERR_BAD_REQUEST, "invalid criticality")
        if c != e["criticality"]:
            changed_criticality = True
        e["criticality"] = c
    if "location" in body:
        if not isinstance(body["location"], str) or not body["location"].strip():
            raise_err(ERR_BAD_REQUEST, "invalid location")
        e["location"] = body["location"]
    if "responsible_user_id" in body:
        if not isinstance(body["responsible_user_id"], str) or not body["responsible_user_id"].strip():
            raise_err(ERR_BAD_REQUEST, "invalid responsible_user_id")
        e["responsible_user_id"] = body["responsible_user_id"]
    if "technical_spec" in body:
        if not isinstance(body["technical_spec"], dict):
            raise_err(ERR_BAD_REQUEST, "technical_spec must be an object")
        e["technical_spec"] = body["technical_spec"]
    if "usage_counter" in body:
        uc = body["usage_counter"]
        if not isinstance(uc, int) or isinstance(uc, bool) or uc < e["usage_counter"]:
            raise_err(ERR_BAD_REQUEST, "usage_counter must be monotonic non-decreasing")
        e["usage_counter"] = uc

    bump_version(e, site_id)

    if changed_criticality:
        recompute_priority_for_open_work_orders_of_equipment(site_id, e)

    return success_object(serialize_equipment(e))


@bp.route("/sites/<site_id>/equipment/<equipment_id>/commission", methods=["POST"])
def commission_equipment(site_id, equipment_id):
    require_role(["SiteManager"])
    get_site_or_404(site_id)
    e = get_equipment_or_404(site_id, equipment_id)
    if e["lifecycle_status"] != "INSTALLED":
        raise_err(ERR_INVALID_STATE, "Equipment not in INSTALLED state")
    # Need at least one ACTIVE plan
    has_active = any(
        p for p in db.plans_for_equipment(equipment_id)
        if p["status"] == "ACTIVE"
    )
    if not has_active:
        raise_err(ERR_NO_ACTIVE_PLAN, "Commissioning requires at least one ACTIVE plan")
    e["lifecycle_status"] = "COMMISSIONED"
    bump_version(e, site_id)
    return success_object(serialize_equipment(e))


@bp.route("/sites/<site_id>/equipment/<equipment_id>/place-in-service", methods=["POST"])
def place_in_service(site_id, equipment_id):
    require_role(["SiteManager"])
    get_site_or_404(site_id)
    e = get_equipment_or_404(site_id, equipment_id)
    if e["lifecycle_status"] != "COMMISSIONED":
        raise_err(ERR_INVALID_STATE, "Equipment not in COMMISSIONED state")
    e["lifecycle_status"] = "IN_SERVICE"
    bump_version(e, site_id)
    return success_object(serialize_equipment(e))


@bp.route("/sites/<site_id>/equipment/<equipment_id>/decommission", methods=["POST"])
def decommission(site_id, equipment_id):
    from datetime import timedelta
    require_role(["SiteManager"])
    get_site_or_404(site_id)
    e = get_equipment_or_404(site_id, equipment_id)
    if e["lifecycle_status"] != "IN_SERVICE":
        raise_err(ERR_INVALID_STATE, "Equipment not in IN_SERVICE state")
    if e.get("open_work_order_id"):
        raise_err(ERR_EQUIPMENT_BUSY, "Equipment has an open work order")

    e["lifecycle_status"] = "DECOMMISSIONED"
    bump_version(e, site_id)

    clock = db.site_clock(site_id)
    # Cascade: ACTIVE plans -> RETIRED
    for p in db.plans_for_equipment(equipment_id):
        if p["status"] == "ACTIVE":
            p["status"] = "RETIRED"
            if "version" in p:
                p["version"] += 1
            p["updated_at"] = clock

    # Cascade: PENDING work orders -> CANCELLED with reason EQUIPMENT_DECOMMISSIONED
    for w in list(db.work_orders_for_equipment(equipment_id)):
        if w["status"] == "PENDING":
            old = w["status"]
            w["status"] = "CANCELLED"
            w["cancel_reason"] = "EQUIPMENT_DECOMMISSIONED"
            w["updated_at"] = clock
            w["version"] += 1
            recompute_sla_breached(w, clock)
            # cancel all RESERVED requisitions
            for r in db.requisitions_for_work_order(w["id"]):
                if r["status"] == "RESERVED":
                    r["status"] = "CANCELLED"
                    r["updated_at"] = clock
                    r["version"] += 1
                    sp = db.spare_parts.get(r["part_id"])
                    if sp is not None:
                        sp["stock_reserved"] = max(0, sp["stock_reserved"] - r["qty"])
                        from services.calculations import replenish_eval
                        replenish_eval(sp)
            append_audit(
                site_id=site_id,
                action="WORK_ORDER_STATE_CHANGE",
                target_id=w["id"],
                from_value=old,
                to_value="CANCELLED",
            )
    # refresh open loads
    from services.calculations import refresh_technician_open_loads
    refresh_technician_open_loads(site_id)

    return success_object(serialize_equipment(e))


@bp.route("/sites/<site_id>/equipment/<equipment_id>/alarms", methods=["POST"])
def emit_alarm(site_id, equipment_id):
    require_role(["SiteManager", "Dispatcher"])
    get_site_or_404(site_id)
    e = get_equipment_or_404(site_id, equipment_id)
    body = get_json_body()
    if "emitted_at" in body:
        raise_err(ERR_TEMPORAL_INVALID, "emitted_at is system-set")
    alarm_code = body.get("alarm_code")
    severity = body.get("severity")
    if not isinstance(alarm_code, str) or not alarm_code:
        raise_err(ERR_BAD_REQUEST, "alarm_code is required")
    if severity not in VALID_SEVERITY:
        raise_err(ERR_BAD_REQUEST, "invalid severity")

    metric_value = body.get("metric_value")
    if metric_value is not None and not isinstance(metric_value, (int, float)):
        raise_err(ERR_BAD_REQUEST, "metric_value must be numeric")

    clock = db.site_clock(site_id)
    aid = new_id()
    alarm = {
        "id": aid,
        "created_at": clock,
        "equipment_id": equipment_id,
        "alarm_code": alarm_code,
        "severity": severity,
        "emitted_at": clock,
        "generated_work_order_id": None,
        "metric_value": metric_value,
    }
    db.alarm_events[aid] = alarm

    # Run Steps 3 and 4
    run_plan_generation_on_alarm(site_id, e, alarm)

    # If a WO was generated, also mark equipment.last_failure_at
    if alarm.get("generated_work_order_id"):
        e["last_failure_at"] = clock

    return success_object(serialize_alarm(alarm))
