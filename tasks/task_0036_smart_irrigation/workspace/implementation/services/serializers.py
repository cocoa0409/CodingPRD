"""Serializers — convert internal record dicts to JSON-friendly payloads."""

from db import iso


def _common_fields(rec):
    return {
        "id": rec["id"],
        "created_at": iso(rec.get("created_at")),
        "updated_at": iso(rec.get("updated_at")),
        "version": rec.get("version"),
    }


def tenant_view(rec):
    out = _common_fields(rec)
    out.update({
        "name": rec.get("name"),
        "contact_email": rec.get("contact_email"),
        "status": rec.get("status"),
    })
    return out


def plot_view(rec):
    out = _common_fields(rec)
    out.update({
        "tenant_id": rec.get("tenant_id"),
        "name": rec.get("name"),
        "area_hectares": rec.get("area_hectares"),
        "crop_type": rec.get("crop_type"),
        "crop_stage": rec.get("crop_stage"),
        "pump_id": rec.get("pump_id"),
        "status": rec.get("status"),
        "last_irrigated_at": iso(rec.get("last_irrigated_at")),
    })
    return out


def sensor_view(rec):
    out = _common_fields(rec)
    out.update({
        "plot_id": rec.get("plot_id"),
        "sensor_type": rec.get("sensor_type"),
        "poll_interval_seconds": rec.get("poll_interval_seconds"),
        "min_valid_value": rec.get("min_valid_value"),
        "max_valid_value": rec.get("max_valid_value"),
        "status": rec.get("status"),
        "last_reading_at": iso(rec.get("last_reading_at")),
    })
    return out


def sensor_reading_view(rec):
    return {
        "id": rec["id"],
        "created_at": iso(rec.get("created_at")),
        "sensor_id": rec.get("sensor_id"),
        "value": rec.get("value"),
        "reading_timestamp": iso(rec.get("reading_timestamp")),
        "validity": rec.get("validity"),
        "archived": rec.get("archived", False),
    }


def irrigation_plan_view(rec):
    out = _common_fields(rec)
    out.update({
        "plot_id": rec.get("plot_id"),
        "window_start": iso(rec.get("window_start")),
        "window_end": iso(rec.get("window_end")),
        "planned_volume_liters": rec.get("planned_volume_liters"),
        "source": rec.get("source"),
        "status": rec.get("status"),
        "plan_version": rec.get("plan_version"),
        "parent_plan_id": rec.get("parent_plan_id"),
    })
    return out


def valve_group_view(rec):
    out = _common_fields(rec)
    out.update({
        "tenant_id": rec.get("tenant_id"),
        "name": rec.get("name"),
        "pump_id": rec.get("pump_id"),
        "valve_ids": list(rec.get("valve_ids", [])),
        "control_mode": rec.get("control_mode"),
        "max_parallel_valves": rec.get("max_parallel_valves"),
    })
    return out


def control_command_view(rec):
    out = _common_fields(rec)
    out.update({
        "plan_id": rec.get("plan_id"),
        "valve_group_id": rec.get("valve_group_id"),
        "requested_volume_liters": rec.get("requested_volume_liters"),
        "dispatch_mode": rec.get("dispatch_mode"),
        "status": rec.get("status"),
        "actual_volume_liters": rec.get("actual_volume_liters", 0),
        "feedback_received_at": iso(rec.get("feedback_received_at")),
        "failure_reason": rec.get("failure_reason"),
    })
    return out


def water_quota_view(rec):
    out = _common_fields(rec)
    out.update({
        "plot_id": rec.get("plot_id"),
        "period_start": iso(rec.get("period_start")),
        "period_end": iso(rec.get("period_end")),
        "allocated_liters": rec.get("allocated_liters"),
        "carry_forward_liters": rec.get("carry_forward_liters", 0),
        "provisional_used_liters": rec.get("provisional_used_liters", 0),
        "final_used_liters": rec.get("final_used_liters", 0),
        "warning_threshold_pct": rec.get("warning_threshold_pct"),
        "usage_state": rec.get("usage_state"),
        "approval_state": rec.get("approval_state"),
        "approval_extra_liters": rec.get("approval_extra_liters", 0),
    })
    return out


def alert_view(rec, severity_override=None):
    out = _common_fields(rec)
    out.update({
        "tenant_id": rec.get("tenant_id"),
        "subject_type": rec.get("subject_type"),
        "subject_id": rec.get("subject_id"),
        "rule_code": rec.get("rule_code"),
        "severity": severity_override if severity_override is not None else rec.get("severity"),
        "status": rec.get("status"),
        "acknowledged_by": rec.get("acknowledged_by"),
        "resolved_by": rec.get("resolved_by"),
    })
    return out


def water_bill_view(rec):
    out = _common_fields(rec)
    out.update({
        "tenant_id": rec.get("tenant_id"),
        "plot_id": rec.get("plot_id"),
        "period_start": iso(rec.get("period_start")),
        "period_end": iso(rec.get("period_end")),
        "peak_liters": rec.get("peak_liters", 0),
        "offpeak_liters": rec.get("offpeak_liters", 0),
        "line_items": list(rec.get("line_items", [])),
        "total_amount_cents": rec.get("total_amount_cents", 0),
        "amount_paid_cents": rec.get("amount_paid_cents", 0),
        "status": rec.get("status"),
        "dispute_reason": rec.get("dispute_reason"),
    })
    return out


def audit_log_view(rec):
    return {
        "id": rec["id"],
        "created_at": iso(rec.get("created_at")),
        "actor_role": rec.get("actor_role"),
        "actor_id": rec.get("actor_id"),
        "action_type": rec.get("action_type"),
        "subject_type": rec.get("subject_type"),
        "subject_id": rec.get("subject_id"),
        "payload": rec.get("payload", {}),
    }
