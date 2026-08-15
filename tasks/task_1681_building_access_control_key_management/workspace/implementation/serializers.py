from db import STORE, fmt_ts


def ser_building(b):
    return {
        "id": b["id"],
        "name": b["name"],
        "audit_retention_days": b["audit_retention_days"],
        "alert_escalation_minutes": b["alert_escalation_minutes"],
        "vendor_badge_pool_max": b["vendor_badge_pool_max"],
        "default_propped_threshold_seconds": b["default_propped_threshold_seconds"],
        "base_fee_cents": b["base_fee_cents"],
        "per_door_fee_cents": b["per_door_fee_cents"],
        "per_key_reissue_fee_cents": b["per_key_reissue_fee_cents"],
        "emergency_surcharge_pct": b["emergency_surcharge_pct"],
        "business_open_utc": b["business_open_utc"],
        "business_close_utc": b["business_close_utc"],
        "ops_run_index": b["ops_run_index"],
        "created_at": fmt_ts(b["created_at"]),
        "updated_at": fmt_ts(b["updated_at"]),
        "version": b["version"],
    }


def _node_counts(node_id):
    stock = issued = lost = 0
    for c in STORE["credentials"].values():
        if c["key_node_id"] != node_id:
            continue
        if c["status"] == "IN_STOCK":
            stock += 1
        elif c["status"] == "ISSUED":
            issued += 1
        elif c["status"] == "LOST":
            lost += 1
    return stock, issued, lost


def ser_key_node(n):
    stock, issued, lost = _node_counts(n["id"])
    return {
        "id": n["id"],
        "building_id": n["building_id"],
        "parent_id": n["parent_id"],
        "level": n["level"],
        "label": n["label"],
        "status": n["status"],
        "supersedes_node_id": n["supersedes_node_id"],
        "seq": n["seq"],
        "stock_credential_count": stock,
        "issued_credential_count": issued,
        "lost_credential_count": lost,
        "created_at": fmt_ts(n["created_at"]),
        "updated_at": fmt_ts(n["updated_at"]),
        "version": n["version"],
    }


def ser_door(d):
    return {
        "id": d["id"],
        "building_id": d["building_id"],
        "door_code": d["door_code"],
        "key_node_id": d["key_node_id"],
        "bitting_code": d["bitting_code"],
        "hardware_status": d["hardware_status"],
        "core_status": d["core_status"],
        "open_since": fmt_ts(d["open_since"]),
        "propped_threshold_seconds": d["propped_threshold_seconds"],
        "seq": d["seq"],
        "created_at": fmt_ts(d["created_at"]),
        "updated_at": fmt_ts(d["updated_at"]),
        "version": d["version"],
    }


def ser_person(p):
    return {
        "id": p["id"],
        "building_id": p["building_id"],
        "full_name": p["full_name"],
        "kind": p["kind"],
        "unit_label": p["unit_label"],
        "employer_name": p["employer_name"],
        "key_deposit_cents": p["key_deposit_cents"],
        "status": p["status"],
        "moved_out_at": fmt_ts(p["moved_out_at"]),
        "seq": p["seq"],
        "created_at": fmt_ts(p["created_at"]),
        "updated_at": fmt_ts(p["updated_at"]),
        "version": p["version"],
    }


def ser_credential(c):
    return {
        "id": c["id"],
        "building_id": c["building_id"],
        "key_node_id": c["key_node_id"],
        "serial_no": c["serial_no"],
        "type": c["type"],
        "status": c["status"],
        "holder_person_id": c["holder_person_id"],
        "issued_at": fmt_ts(c["issued_at"]),
        "expires_at": fmt_ts(c["expires_at"]),
        "lost_at": fmt_ts(c["lost_at"]),
        "deactivated_reason": c["deactivated_reason"],
        "seq": c["seq"],
        "created_at": fmt_ts(c["created_at"]),
        "updated_at": fmt_ts(c["updated_at"]),
        "version": c["version"],
    }


def ser_access_group(g):
    return {
        "id": g["id"],
        "building_id": g["building_id"],
        "name": g["name"],
        "door_ids": list(g["door_ids"]),
        "person_ids": list(g["person_ids"]),
        "days_of_week": list(g["days_of_week"]),
        "window_start_utc": g["window_start_utc"],
        "window_end_utc": g["window_end_utc"],
        "seq": g["seq"],
        "created_at": fmt_ts(g["created_at"]),
        "updated_at": fmt_ts(g["updated_at"]),
        "version": g["version"],
    }


def ser_access_event(e):
    # AccessEvent: immutable audit row — id and created_at only, no
    # updated_at / version.
    return {
        "id": e["id"],
        "building_id": e["building_id"],
        "credential_id": e["credential_id"],
        "door_id": e["door_id"],
        "occurred_at": fmt_ts(e["occurred_at"]),
        "outcome": e["outcome"],
        "archived": e["archived"],
        "seq": e["seq"],
        "created_at": fmt_ts(e["created_at"]),
    }


def ser_propped_alert(a):
    return {
        "id": a["id"],
        "building_id": a["building_id"],
        "door_id": a["door_id"],
        "opened_at": fmt_ts(a["opened_at"]),
        "status": a["status"],
        "resolved_reason": a["resolved_reason"],
        "incident_id": a["incident_id"],
        "seq": a["seq"],
        "created_at": fmt_ts(a["created_at"]),
        "updated_at": fmt_ts(a["updated_at"]),
        "version": a["version"],
    }


def ser_incident(i):
    return {
        "id": i["id"],
        "building_id": i["building_id"],
        "type": i["type"],
        "status": i["status"],
        "credential_id": i["credential_id"],
        "door_id": i["door_id"],
        "alert_id": i["alert_id"],
        "responsible_person_id": i["responsible_person_id"],
        "resolution_action": i["resolution_action"],
        "resolution_note": i["resolution_note"],
        "campaign_id": i["campaign_id"],
        "seq": i["seq"],
        "created_at": fmt_ts(i["created_at"]),
        "updated_at": fmt_ts(i["updated_at"]),
        "version": i["version"],
    }


def ser_campaign(c):
    return {
        "id": c["id"],
        "building_id": c["building_id"],
        "key_node_id": c["key_node_id"],
        "incident_id": c["incident_id"],
        "status": c["status"],
        "bill_to": c["bill_to"],
        "bill_person_id": c["bill_person_id"],
        "rekey_seq": c["rekey_seq"],
        "affected_door_count": c["affected_door_count"],
        "affected_credential_count": c["affected_credential_count"],
        "estimated_cost_cents": c["estimated_cost_cents"],
        "final_cost_cents": c["final_cost_cents"],
        "completed_at": fmt_ts(c["completed_at"]),
        "created_at": fmt_ts(c["created_at"]),
        "updated_at": fmt_ts(c["updated_at"]),
        "version": c["version"],
    }


def ser_work_order(w):
    return {
        "id": w["id"],
        "building_id": w["building_id"],
        "door_id": w["door_id"],
        "campaign_id": w["campaign_id"],
        "target_key_node_id": w["target_key_node_id"],
        "type": w["type"],
        "status": w["status"],
        "scheduled_start": fmt_ts(w["scheduled_start"]),
        "scheduled_end": fmt_ts(w["scheduled_end"]),
        "actual_cost_cents": w["actual_cost_cents"],
        "bill_person_id": w["bill_person_id"],
        "seq": w["seq"],
        "created_at": fmt_ts(w["created_at"]),
        "updated_at": fmt_ts(w["updated_at"]),
        "version": w["version"],
    }


def ser_charge(ch):
    return {
        "id": ch["id"],
        "building_id": ch["building_id"],
        "person_id": ch["person_id"],
        "campaign_id": ch["campaign_id"],
        "kind": ch["kind"],
        "amount_cents": ch["amount_cents"],
        "deposit_cents": ch["deposit_cents"],
        "provisional_refund_cents": ch["provisional_refund_cents"],
        "final_forfeit_total_cents": ch["final_forfeit_total_cents"],
        "final_refund_cents": ch["final_refund_cents"],
        "line_items": ch["line_items"],
        "moved_out_at": fmt_ts(ch["moved_out_at"]),
        "status": ch["status"],
        "seq": ch["seq"],
        "created_at": fmt_ts(ch["created_at"]),
        "updated_at": fmt_ts(ch["updated_at"]),
        "version": ch["version"],
    }
