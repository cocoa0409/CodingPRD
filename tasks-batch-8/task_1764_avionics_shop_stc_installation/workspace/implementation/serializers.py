"""Resource serializers — exact field sets per scaffold entity table."""
import clock
from util import iso_millis


def _common(e):
    return {
        "id": e.id,
        "created_at": iso_millis(e.created_at),
        "updated_at": iso_millis(e.updated_at),
        "version": e.version,
    }


def _dt_or_none(v):
    return iso_millis(v) if v is not None else None


def ser_customer(c):
    out = {
        "name": c.name,
        "contact_email": c.contact_email,
        "customer_kind": c.customer_kind,
    }
    out.update(_common(c))
    return out


def ser_aircraft(a):
    out = {
        "customer_id": a.customer_id,
        "tail_number": a.tail_number,
        "make_model": a.make_model,
        "baseline_empty_weight_lb": a.baseline_empty_weight_lb,
        "baseline_arm_in": a.baseline_arm_in,
        "baseline_moment_lb_in": a.baseline_moment_lb_in,
        "cg_min_arm_in": a.cg_min_arm_in,
        "cg_max_arm_in": a.cg_max_arm_in,
        "status": a.status,
    }
    out.update(_common(a))
    return out


def ser_work_order(w):
    out = {
        "aircraft_id": w.aircraft_id,
        "scope_description": w.scope_description,
        "estimated_downtime_days": w.estimated_downtime_days,
        "quoted_labor_hours": w.quoted_labor_hours,
        "bay_code": w.bay_code,
        "bay_window_start": iso_millis(w.bay_window_start),
        "bay_window_end": iso_millis(w.bay_window_end),
        "status": w.status,
        "inducted_at": _dt_or_none(w.inducted_at),
        "completed_at": _dt_or_none(w.completed_at),
        "actual_downtime_days": w.actual_downtime_days,
        "downtime_overage_days": w.downtime_overage_days,
        "overage_acknowledged": w.overage_acknowledged,
        "parts_pending_count": w.parts_pending_count,
        "tasks_unverified_count": w.tasks_unverified_count,
        "total_actual_labor_hours": w.total_actual_labor_hours,
        "total_billed_labor_cents": w.total_billed_labor_cents,
        "quoted_total_cents": w.quoted_total_cents,
        "warranty_term_months": w.warranty_term_months,
        "software_subscription_months": w.software_subscription_months,
        "warranty_expires_at": _dt_or_none(w.warranty_expires_at),
        "subscription_expires_at": _dt_or_none(w.subscription_expires_at),
    }
    out.update(_common(w))
    return out


def ser_panel_design(d):
    out = {
        "work_order_id": d.work_order_id,
        "revision": d.revision,
        "layout_notes": d.layout_notes,
        "equipment_list": d.equipment_list,
        "total_added_weight_lb": d.total_added_weight_lb,
        "status": d.status,
    }
    out.update(_common(d))
    return out


def equipment_is_late(o):
    """is_late: strictly greater than promised_date; compares against the logical
    clock while unreceived; false until the order has been marked ordered."""
    if o.promised_date is None:
        return False
    ref = o.received_at if o.received_at is not None else clock.now()
    return ref > o.promised_date


def ser_equipment_order(o):
    out = {
        "work_order_id": o.work_order_id,
        "seq": o.seq,
        "source": o.source,
        "source_design_revision": o.source_design_revision,
        "part_number": o.part_number,
        "description": o.description,
        "quantity": o.quantity,
        "unit_price_cents": o.unit_price_cents,
        "lead_time_days": o.lead_time_days,
        "ordered_at": _dt_or_none(o.ordered_at),
        "promised_date": _dt_or_none(o.promised_date),
        "received_at": _dt_or_none(o.received_at),
        "is_late": equipment_is_late(o),
        "status": o.status,
    }
    out.update(_common(o))
    return out


def ser_install_task(t):
    out = {
        "work_order_id": t.work_order_id,
        "task_kind": t.task_kind,
        "description": t.description,
        "estimated_hours": t.estimated_hours,
        "actual_hours": t.actual_hours,
        "performed_by_user_id": t.performed_by_user_id,
        "verified_by_user_id": t.verified_by_user_id,
        "billed_labor_cents": t.billed_labor_cents,
        "status": t.status,
    }
    out.update(_common(t))
    return out


def ser_test_event(e):
    out = {
        "work_order_id": e.work_order_id,
        "test_kind": e.test_kind,
        "scheduled_start": iso_millis(e.scheduled_start),
        "scheduled_end": iso_millis(e.scheduled_end),
        "attempt": e.attempt,
        "result": e.result,
        "status": e.status,
    }
    out.update(_common(e))
    return out


def ser_regulatory_package(p):
    out = {
        "work_order_id": p.work_order_id,
        "approval_path": p.approval_path,
        "stc_number": p.stc_number,
        "faa_tracking_number": p.faa_tracking_number,
        "decided_by_user_id": p.decided_by_user_id,
        "status": p.status,
    }
    out.update(_common(p))
    return out


def ser_wb_revision(r):
    out = {
        "work_order_id": r.work_order_id,
        "method": r.method,
        "added_items": r.added_items,
        "removed_weight_lb": r.removed_weight_lb,
        "removed_arm_in": r.removed_arm_in,
        "new_empty_weight_lb": r.new_empty_weight_lb,
        "new_moment_lb_in": r.new_moment_lb_in,
        "new_arm_in": r.new_arm_in,
        "cg_within_limits": r.cg_within_limits,
        "status": r.status,
    }
    out.update(_common(r))
    return out
