"""Serialize entity dicts for outbound responses."""
from clock import iso


def _ts(v):
    if v is None:
        return None
    return iso(v) if hasattr(v, "tzinfo") else v


def _num(v):
    # Money rendered as float; numbers without decimals serialize fine as int or float.
    if v is None:
        return None
    return v


def station(row: dict) -> dict:
    return {
        "id": row["id"],
        "name": row["name"],
        "address": row["address"],
        "business_hours_open": row["business_hours_open"],
        "business_hours_close": row["business_hours_close"],
        "storage_capacity": row["storage_capacity"],
        "free_storage_hours": row["free_storage_hours"],
        "status": row["status"],
        "current_occupancy": row["current_occupancy"],
        "quality_score": row.get("quality_score"),
        "created_at": _ts(row["created_at"]),
        "updated_at": _ts(row["updated_at"]),
        "version": row["version"],
    }


def shelf_zone(row: dict) -> dict:
    return {
        "id": row["id"],
        "station_id": row["station_id"],
        "zone_code": row["zone_code"],
        "row_count": row["row_count"],
        "column_count": row["column_count"],
        "zone_type": row["zone_type"],
        "capacity": row["capacity"],
        "occupied_slots": row["occupied_slots"],
        "created_at": _ts(row["created_at"]),
        "updated_at": _ts(row["updated_at"]),
        "version": row["version"],
    }


def staff(row: dict) -> dict:
    return {
        "id": row["id"],
        "station_id": row["station_id"],
        "full_name": row["full_name"],
        "phone": row["phone"],
        "role_kind": row["role_kind"],
        "status": row["status"],
        "created_at": _ts(row["created_at"]),
        "updated_at": _ts(row["updated_at"]),
        "version": row["version"],
    }


def parcel(row: dict) -> dict:
    return {
        "id": row["id"],
        "station_id": row["station_id"],
        "courier_company_id": row["courier_company_id"],
        "tracking_number": row["tracking_number"],
        "recipient_phone": row["recipient_phone"],
        "recipient_name": row.get("recipient_name"),
        "weight_grams": row["weight_grams"],
        "size_class": row["size_class"],
        "shelf_zone_id": row.get("shelf_zone_id"),
        "shelf_position": row.get("shelf_position"),
        "status": row["status"],
        "exception_type": row.get("exception_type", "NONE"),
        "shelved_at": _ts(row.get("shelved_at")),
        "free_storage_deadline": _ts(row.get("free_storage_deadline")),
        "picked_up_at": _ts(row.get("picked_up_at")),
        "returned_at": _ts(row.get("returned_at")),
        "long_stay_flagged_at": _ts(row.get("long_stay_flagged_at")),
        "storage_fee_total": row.get("storage_fee_total", 0),
        "storage_fee_locked": row.get("storage_fee_locked", False),
        "created_at": _ts(row["created_at"]),
        "updated_at": _ts(row["updated_at"]),
        "version": row["version"],
    }


def pickup_code(row: dict) -> dict:
    return {
        "id": row["id"],
        "parcel_id": row["parcel_id"],
        "code": row["code"],
        "status": row["status"],
        "issued_at": _ts(row["issued_at"]),
        "issue_reason": row["issue_reason"],
        "consumed_at": _ts(row.get("consumed_at")),
        "superseded_by": row.get("superseded_by"),
        "created_at": _ts(row["created_at"]),
        "updated_at": _ts(row["updated_at"]),
        "version": row["version"],
    }


def pickup_auth(row: dict) -> dict:
    return {
        "id": row["id"],
        "parcel_id": row["parcel_id"],
        "delegate_name": row["delegate_name"],
        "delegate_id_number": row["delegate_id_number"],
        "delegate_phone": row["delegate_phone"],
        "granted_at": _ts(row["granted_at"]),
        "expires_at": _ts(row["expires_at"]),
        "status": row["status"],
        "created_at": _ts(row["created_at"]),
    }


def reminder(row: dict) -> dict:
    return {
        "id": row["id"],
        "parcel_id": row["parcel_id"],
        "tier": row["tier"],
        "channel": row["channel"],
        "sent_at": _ts(row["sent_at"]),
        "triggered_by": row["triggered_by"],
        "created_at": _ts(row["created_at"]),
    }


def return_shipment(row: dict) -> dict:
    return {
        "id": row["id"],
        "parcel_id": row["parcel_id"],
        "courier_company_id": row["courier_company_id"],
        "courier_tracking_return": row.get("courier_tracking_return"),
        "status": row["status"],
        "requested_at": _ts(row["requested_at"]),
        "courier_response_at": _ts(row.get("courier_response_at")),
        "shipped_at": _ts(row.get("shipped_at")),
        "created_at": _ts(row["created_at"]),
        "updated_at": _ts(row["updated_at"]),
        "version": row["version"],
    }


def billing_period(row: dict) -> dict:
    return {
        "id": row["id"],
        "station_id": row["station_id"],
        "period_yyyymm": row["period_yyyymm"],
        "period_start": _ts(row["period_start"]),
        "period_end": _ts(row["period_end"]),
        "status": row["status"],
        "handover_fee_total": row.get("handover_fee_total", 0),
        "storage_fee_total": row.get("storage_fee_total", 0),
        "quality_adjustment_factor": row.get("quality_adjustment_factor", 1.0),
        "final_total": row.get("final_total", 0),
        "created_at": _ts(row["created_at"]),
        "updated_at": _ts(row["updated_at"]),
        "version": row["version"],
    }


def bill(row: dict) -> dict:
    return {
        "id": row["id"],
        "billing_period_id": row["billing_period_id"],
        "payer_kind": row["payer_kind"],
        "payer_ref": row["payer_ref"],
        "handover_fee_amount": row.get("handover_fee_amount", 0),
        "storage_fee_amount": row.get("storage_fee_amount", 0),
        "parcel_count": row.get("parcel_count", 0),
        "status": row["status"],
        "issued_at": _ts(row.get("issued_at")),
        "paid_at": _ts(row.get("paid_at")),
        "dispute_reason": row.get("dispute_reason"),
        "created_at": _ts(row["created_at"]),
        "updated_at": _ts(row["updated_at"]),
        "version": row["version"],
    }


def quality_assessment(row: dict) -> dict:
    return {
        "id": row["id"],
        "station_id": row["station_id"],
        "period_yyyymm": row["period_yyyymm"],
        "mis_shelving_rate": row.get("mis_shelving_rate", 0),
        "lost_parcel_rate": row.get("lost_parcel_rate", 0),
        "complaint_rate": row.get("complaint_rate", 0),
        "response_timeliness_score": row.get("response_timeliness_score", 1.0),
        "composite_score": row.get("composite_score", 1.0),
        "status": row["status"],
        "closed_at": _ts(row.get("closed_at")),
        "created_at": _ts(row["created_at"]),
        "updated_at": _ts(row["updated_at"]),
        "version": row["version"],
    }


def audit_event(row: dict) -> dict:
    return {
        "id": row["id"],
        "subject_kind": row["subject_kind"],
        "subject_id": row["subject_id"],
        "action": row["action"],
        "actor_role": row.get("actor_role"),
        "actor_id": row.get("actor_id"),
        "from_state": row.get("from_state"),
        "to_state": row.get("to_state"),
        "payload": row.get("payload", {}),
        "created_at": _ts(row["created_at"]),
    }


def system_event(row: dict) -> dict:
    return {
        "id": row["id"],
        "target_system": row["target_system"],
        "event_name": row["event_name"],
        "subject_kind": row["subject_kind"],
        "subject_id": row["subject_id"],
        "payload": row.get("payload", {}),
        "sequence": row["sequence"],
        "emitted_at": _ts(row["emitted_at"]),
        "created_at": _ts(row["created_at"]),
    }
