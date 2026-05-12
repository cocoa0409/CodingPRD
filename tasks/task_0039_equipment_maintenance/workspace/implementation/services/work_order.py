"""WorkOrder creation and lifecycle service."""
from datetime import timedelta

from db import db, new_id
from errors import (
    ERR_CROSS_SITE_REFERENCE,
    ERR_EQUIPMENT_BUSY,
    ERR_EQUIPMENT_LIFECYCLE,
    ERR_NOT_FOUND,
    ERR_SKILL_MISMATCH,
    raise_err,
)
from services.audit import append_audit
from services.calculations import (
    bucket_for_score,
    compute_priority_score,
    select_technician,
    sla_due_at,
    refresh_technician_open_loads,
)


def create_work_order(
    site_id,
    equipment_id,
    template_id,
    source,
    plan_id=None,
    explicit_priority=None,
    preferred_technician_id=None,
):
    """Build a WorkOrder. Caller is expected to have validated cross-site.

    Returns the work order dict. Raises if equipment lifecycle/busy invalid.
    """
    equipment = db.equipment.get(equipment_id)
    if equipment is None or equipment["site_id"] != site_id:
        raise_err(ERR_NOT_FOUND, "Equipment not found")
    template = db.templates.get(template_id)
    if template is None or template["site_id"] != site_id:
        raise_err(ERR_NOT_FOUND, "Template not found")

    # Lifecycle gate
    if equipment["lifecycle_status"] not in {"COMMISSIONED", "IN_SERVICE"}:
        raise_err(ERR_EQUIPMENT_LIFECYCLE, "Equipment lifecycle does not permit new work")
    # Busy gate
    if equipment.get("open_work_order_id"):
        raise_err(ERR_EQUIPMENT_BUSY, "Equipment already has an open work order")

    site_clock = db.site_clock(site_id)

    # Compute priority
    score = compute_priority_score(equipment, template, source)
    if explicit_priority is not None and explicit_priority in {"P1", "P2", "P3", "P4"}:
        bucket = explicit_priority
    else:
        bucket = bucket_for_score(score)

    # Select technician
    required_skill = template["required_skill"]
    chosen_tech_id = None
    if preferred_technician_id is not None:
        # check eligibility
        pref = db.technicians.get(preferred_technician_id)
        if pref is not None and pref["site_id"] == site_id and pref["status"] == "ACTIVE" and required_skill in pref["skills"]:
            chosen_tech_id = pref["id"]
        else:
            chosen_tech_id = select_technician(site_id, required_skill)
    else:
        chosen_tech_id = select_technician(site_id, required_skill)

    wo_id = new_id()
    opened_at = site_clock
    sla = sla_due_at(opened_at, bucket)
    wo = {
        "id": wo_id,
        "created_at": site_clock,
        "updated_at": site_clock,
        "version": 1,
        "site_id": site_id,
        "equipment_id": equipment_id,
        "template_id": template_id,
        "plan_id": plan_id,
        "source": source,
        "priority": bucket,
        "priority_score": score,
        "required_skill": required_skill,
        "estimated_minutes": template["estimated_minutes"],
        "assigned_technician_id": chosen_tech_id,
        "status": "PENDING",
        "opened_at": opened_at,
        "started_at": None,
        "completed_at": None,
        "closed_at": None,
        "sla_due_at": sla,
        "sla_breached": False,
        "pause_reason": None,
        "total_active_minutes": 0,
        "parts_cost_cents": None,
        "reassign_count": 0,
        "_in_progress_started_at": None,  # internal: timestamp of latest IN_PROGRESS entry
        "cancel_reason": None,
    }
    db.work_orders[wo_id] = wo
    equipment["open_work_order_id"] = wo_id
    refresh_technician_open_loads(site_id)
    return wo


def recompute_priority_for_open_work_orders_of_equipment(site_id, equipment):
    """Triggered when criticality changes."""
    for w in list(db.work_orders.values()):
        if w["equipment_id"] != equipment["id"]:
            continue
        if w["status"] in {"COMPLETED", "CLOSED", "CANCELLED"}:
            continue
        template = db.templates.get(w["template_id"])
        if template is None:
            continue
        old_bucket = w["priority"]
        score = compute_priority_score(equipment, template, w["source"])
        new_bucket = bucket_for_score(score)
        w["priority_score"] = score
        if new_bucket != old_bucket:
            w["priority"] = new_bucket
            w["sla_due_at"] = sla_due_at(w["opened_at"], new_bucket)


# ---- Plan generation --------------------------------------------------

def run_plan_generation_periodic(site_id):
    """Steps 1 and 2 — periodic time and periodic usage plan generation."""
    site_clock = db.site_clock(site_id)
    plans = [p for p in db.plans_for_site(site_id) if p["status"] == "ACTIVE"]

    # Track which equipment already got a WO this tick.
    used_equipment = set()

    # Step 1: PERIODIC_TIME, ordered by next_due_at ASC, id ASC
    time_plans = [p for p in plans if p["kind"] == "PERIODIC_TIME"]
    time_plans.sort(key=lambda p: (p["next_due_at"] or site_clock, p["id"]))
    for p in time_plans:
        if p["next_due_at"] is None:
            continue
        if site_clock < p["next_due_at"]:
            continue
        equipment = db.equipment.get(p["equipment_id"])
        if equipment is None:
            continue
        if equipment["id"] in used_equipment:
            continue
        if equipment.get("open_work_order_id"):
            continue
        if equipment["lifecycle_status"] not in {"COMMISSIONED", "IN_SERVICE"}:
            continue
        try:
            wo = create_work_order(
                site_id=site_id,
                equipment_id=equipment["id"],
                template_id=p["template_id"],
                source="PLAN_PERIODIC",
                plan_id=p["id"],
            )
        except Exception:
            continue
        used_equipment.add(equipment["id"])
        p["last_generated_at"] = site_clock
        p["next_due_at"] = site_clock + timedelta(seconds=(p["interval_days"] or 0) * 86400)
        if "version" in p:
            p["version"] += 1
        p["updated_at"] = site_clock

    # Step 2: PERIODIC_USAGE, ordered by id ASC
    usage_plans = [p for p in plans if p["kind"] == "PERIODIC_USAGE"]
    usage_plans.sort(key=lambda p: p["id"])
    for p in usage_plans:
        equipment = db.equipment.get(p["equipment_id"])
        if equipment is None:
            continue
        if equipment["id"] in used_equipment:
            continue
        if equipment.get("open_work_order_id"):
            continue
        if equipment["lifecycle_status"] not in {"COMMISSIONED", "IN_SERVICE"}:
            continue
        baseline = p["last_generated_usage"] if p.get("last_generated_usage") is not None else 0
        if (equipment["usage_counter"] - baseline) < (p["interval_usage"] or 0):
            continue
        try:
            wo = create_work_order(
                site_id=site_id,
                equipment_id=equipment["id"],
                template_id=p["template_id"],
                source="PLAN_PERIODIC",
                plan_id=p["id"],
            )
        except Exception:
            continue
        used_equipment.add(equipment["id"])
        p["last_generated_usage"] = equipment["usage_counter"]
        p["last_generated_at"] = site_clock
        if "version" in p:
            p["version"] += 1
        p["updated_at"] = site_clock


def run_plan_generation_on_alarm(site_id, equipment, alarm_event):
    """Steps 3 and 4 — for /alarms endpoint only."""
    plans = [p for p in db.plans_for_site(site_id) if p["status"] == "ACTIVE"]
    used = False  # only one work order per alarm per equipment

    # Step 3: TRIGGER_ALARM, equipment match + alarm_code match. Order: id ASC
    alarm_plans = [
        p for p in plans
        if p["kind"] == "TRIGGER_ALARM"
        and p["equipment_id"] == equipment["id"]
        and (p.get("alarm_code") == alarm_event["alarm_code"])
    ]
    alarm_plans.sort(key=lambda p: p["id"])
    for p in alarm_plans:
        if used:
            break
        if equipment.get("open_work_order_id"):
            break
        try:
            wo = create_work_order(
                site_id=site_id,
                equipment_id=equipment["id"],
                template_id=p["template_id"],
                source="ALARM",
                plan_id=p["id"],
            )
            alarm_event["generated_work_order_id"] = wo["id"]
            used = True
        except Exception:
            continue

    if used:
        return

    # Step 4: TRIGGER_THRESHOLD with threshold_metric == alarm_code AND predicate.
    metric_value = alarm_event.get("metric_value")
    threshold_plans = [
        p for p in plans
        if p["kind"] == "TRIGGER_THRESHOLD"
        and p["equipment_id"] == equipment["id"]
        and p.get("threshold_metric") == alarm_event["alarm_code"]
    ]
    threshold_plans.sort(key=lambda p: p["id"])
    for p in threshold_plans:
        if used:
            break
        if equipment.get("open_work_order_id"):
            break
        if metric_value is None:
            continue
        op = p.get("threshold_op")
        tv = p.get("threshold_value")
        if tv is None or op is None:
            continue
        try:
            mv = float(metric_value)
            tv_f = float(tv)
        except (TypeError, ValueError):
            continue
        predicate = False
        if op == "GTE":
            predicate = mv >= tv_f
        elif op == "GT":
            predicate = mv > tv_f
        elif op == "LTE":
            predicate = mv <= tv_f
        elif op == "LT":
            predicate = mv < tv_f
        if not predicate:
            continue
        try:
            wo = create_work_order(
                site_id=site_id,
                equipment_id=equipment["id"],
                template_id=p["template_id"],
                source="ALARM",
                plan_id=p["id"],
            )
            alarm_event["generated_work_order_id"] = wo["id"]
            used = True
        except Exception:
            continue
