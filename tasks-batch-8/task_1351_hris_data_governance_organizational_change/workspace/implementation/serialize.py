"""Resource serializers — output shapes per scaffold entity tables."""
from util import fmt_ts


def _d(d):
    return d.isoformat() if d is not None else None


def _base(e):
    return {
        "id": e["id"],
        "created_at": fmt_ts(e["created_at"]),
        "updated_at": fmt_ts(e["updated_at"]),
        "version": e["version"],
    }


def ser_data_field(f):
    return {**_base(f),
            "field_key": f["field_key"],
            "display_name": f["display_name"],
            "sensitivity": f["sensitivity"],
            "history_policy": f["history_policy"],
            "downstream_channels": list(f["downstream_channels"]),
            "owner_team": f["owner_team"],
            "status": f["status"]}


def ser_dq_rule(r):
    return {**_base(r),
            "target_field_id": r["target_field_id"],
            "rule_type": r["rule_type"],
            "severity": r["severity"],
            "param_min": r["param_min"],
            "param_max": r["param_max"],
            "param_pattern": r["param_pattern"],
            "status": r["status"]}


def ser_position(p):
    return {**_base(p),
            "title": p["title"],
            "department": p["department"],
            "parent_position_id": p["parent_position_id"],
            "headcount_budget": p["headcount_budget"],
            "status": p["status"]}


def ser_worker(w):
    return {**_base(w),
            "legal_name": w["legal_name"],
            "worker_number": w["worker_number"],
            "hire_date": _d(w["hire_date"]),
            "initial_position_id": w["initial_position_id"],
            "initial_salary_cents": w["initial_salary_cents"],
            "status": w["status"],
            "termination_date": _d(w["termination_date"])}


def ser_assignment(r):
    return {**_base(r),
            "worker_id": r["worker_id"],
            "change_request_id": r["change_request_id"],
            "position_id": r["position_id"],
            "salary_cents": r["salary_cents"],
            "pay_grade": r["pay_grade"],
            "location_code": r["location_code"],
            "effective_start_date": _d(r["effective_start_date"]),
            "effective_end_date": _d(r["effective_end_date"]),
            "row_status": r["row_status"]}


def ser_change_request(c):
    return {**_base(c),
            "target_type": c["target_type"],
            "target_worker_id": c["target_worker_id"],
            "target_position_id": c["target_position_id"],
            "target_field_id": c["target_field_id"],
            "new_value": c["new_value"],
            "effective_date": _d(c["effective_date"]),
            "correction_mode": c["correction_mode"],
            "target_row_id": c["target_row_id"],
            "propagate_correction": c["propagate_correction"],
            "status": c["status"],
            "created_by": c["created_by"],
            "approver_1_id": c["approver_1_id"],
            "approver_2_id": c["approver_2_id"],
            "prior_value": c["prior_value"],
            "prior_row_end": _d(c["prior_row_end"])}


def ser_batch(b, lines_of_batch):
    lines = [l for l in lines_of_batch if l["batch_id"] == b["id"]]
    applied = [l for l in lines if l["status"] == "APPLIED"]
    failed = [l for l in lines if l["status"] == "FAILED"]
    delta = sum(l["resolved_delta_cents"] for l in applied
                if l.get("resolved_delta_cents") is not None)
    return {**_base(b),
            "name": b["name"],
            "status": b["status"],
            "scheduled_effective_date": _d(b["scheduled_effective_date"]),
            "total_lines": len(lines),
            "applied_lines": len(applied),
            "failed_lines": len(failed),
            "total_delta_cents": delta}


def ser_batch_line(l):
    return {**_base(l),
            "batch_id": l["batch_id"],
            "line_index": l["line_index"],
            "target_worker_id": l["target_worker_id"],
            "target_field_id": l["target_field_id"],
            "new_value": l["new_value"],
            "effective_date": _d(l["effective_date"]),
            "status": l["status"],
            "error_id": l["error_id"],
            "resolved_delta_cents": l["resolved_delta_cents"]}


def ser_event(e):
    return {**_base(e),
            "event_type": e["event_type"],
            "channel": e["channel"],
            "worker_id": e["worker_id"],
            "change_request_id": e["change_request_id"],
            "batch_id": e["batch_id"],
            "status": e["status"],
            "retry_count": e["retry_count"],
            "resolution_note": e["resolution_note"]}


def ser_exception(x):
    return {**_base(x),
            "rule_id": x["rule_id"],
            "change_request_id": x["change_request_id"],
            "batch_id": x["batch_id"],
            "integration_event_id": x["integration_event_id"],
            "worker_id": x["worker_id"],
            "field_id": x["field_id"],
            "observed_value": x["observed_value"],
            "status": x["status"],
            "priority_score": x["priority_score"],
            "waiver_expiry_date": _d(x["waiver_expiry_date"]),
            "resolution_note": x["resolution_note"]}


def ser_grant(g):
    return {**_base(g),
            "user_id": g["user_id"],
            "role_code": g["role_code"],
            "scope_department": g["scope_department"],
            "valid_from": _d(g["valid_from"]),
            "valid_until": _d(g["valid_until"]),
            "status": g["status"],
            "approved_by": g["approved_by"]}


def ser_audit(a):
    # Append-only log: id + created_at only; no updated_at / version.
    return {"id": a["id"],
            "created_at": fmt_ts(a["created_at"]),
            "actor_id": a["actor_id"],
            "action": a["action"],
            "worker_id": a["worker_id"],
            "field_id": a["field_id"],
            "change_request_id": a["change_request_id"],
            "batch_id": a["batch_id"],
            "old_value": a["old_value"],
            "new_value": a["new_value"]}
