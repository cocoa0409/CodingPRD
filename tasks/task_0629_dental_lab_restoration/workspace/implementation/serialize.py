"""Entity -> JSON-serializable dict converters.

Field names and audit fields per scaffold §1.1 and PRD §2.4. Datetime fields are
emitted as ISO 8601 UTC with three fractional digits.
"""
import db


def _audit(r):
    return {
        "id": r["id"],
        "created_at": db.iso(r["created_at"]),
        "updated_at": db.iso(r["updated_at"]),
        "version": r["version"],
    }


def doctor(r):
    out = _audit(r)
    out.update({
        "full_name": r["full_name"],
        "practice_name": r["practice_name"],
        "email": r["email"],
        "completed_case_count": r["completed_case_count"],
        "account_credit_cents": r["account_credit_cents"],
    })
    return out


def material(r):
    out = _audit(r)
    out.update({
        "code": r["code"],
        "name": r["name"],
        "base_unit_price_cents": r["base_unit_price_cents"],
        "fabrication_process": r["fabrication_process"],
        "is_active": r["is_active"],
    })
    return out


def mill_machine(r):
    out = _audit(r)
    out.update({
        "name": r["name"],
        "capability": r["capability"],
        "status": r["status"],
    })
    return out


def courier_route(r):
    out = _audit(r)
    out.update({
        "label": r["label"],
        "service_date": db.iso(r["service_date"]),
        "max_stops": r["max_stops"],
        "buffer_minutes": r["buffer_minutes"],
        "stop_count": r["stop_count"],
    })
    return out


def case(r):
    out = _audit(r)
    out.update({
        "doctor_id": r["doctor_id"],
        "intake_method": r["intake_method"],
        "is_rush": r["is_rush"],
        "status": r["status"],
        "scheduled_start_at": db.iso(r["scheduled_start_at"]),
        "promised_ready_at": db.iso(r["promised_ready_at"]),
        "shipped_at": db.iso(r["shipped_at"]),
        "sla_breached": r["sla_breached"],
        "revision_count": r["revision_count"],
        "billable_unit_count": r["billable_unit_count"],
    })
    return out


def restoration(r):
    out = _audit(r)
    out.update({
        "case_id": r["case_id"],
        "material_id": r["material_id"],
        "restoration_type": r["restoration_type"],
        "unit_count": r["unit_count"],
        "requested_shade": r["requested_shade"],
        "unit_price_cents": r["unit_price_cents"],
    })
    return out


def fabrication_unit(r):
    out = _audit(r)
    out.update({
        "restoration_id": r["restoration_id"],
        "remade_from_unit_id": r["remade_from_unit_id"],
        "status": r["status"],
        "is_billable": r["is_billable"],
    })
    return out


def shade_record(r):
    out = _audit(r)
    out.update({
        "restoration_id": r["restoration_id"],
        "shade_code": r["shade_code"],
        "matched": r["matched"],
    })
    return out


def mill_job(r):
    out = _audit(r)
    out.update({
        "fabrication_unit_id": r["fabrication_unit_id"],
        "mill_machine_id": r["mill_machine_id"],
        "start_at": db.iso(r["start_at"]),
        "duration_minutes": r["duration_minutes"],
        "end_at": db.iso(r["end_at"]),
        "status": r["status"],
    })
    return out


def route_stop(r):
    out = _audit(r)
    out.update({
        "courier_route_id": r["courier_route_id"],
        "case_id": r["case_id"],
        "window_start_at": db.iso(r["window_start_at"]),
        "window_minutes": r["window_minutes"],
        "window_end_at": db.iso(r["window_end_at"]),
        "status": r["status"],
    })
    return out


def invoice(r):
    out = _audit(r)
    out.update({
        "case_id": r["case_id"],
        "kind": r["kind"],
        "subtotal_cents": r["subtotal_cents"],
        "rush_surcharge_cents": r["rush_surcharge_cents"],
        "discount_cents": r["discount_cents"],
        "tax_cents": r["tax_cents"],
        "sla_credit_cents": r["sla_credit_cents"],
        "total_cents": r["total_cents"],
        "billing_status": r["billing_status"],
        "delivery_status": r["delivery_status"],
    })
    return out


def credit_memo(r):
    out = _audit(r)
    out.update({
        "case_id": r["case_id"],
        "invoice_id": r["invoice_id"],
        "amount_cents": r["amount_cents"],
        "status": r["status"],
    })
    return out


def remake_request(r):
    out = _audit(r)
    out.update({
        "case_id": r["case_id"],
        "fabrication_unit_id": r["fabrication_unit_id"],
        "reason": r["reason"],
        "status": r["status"],
    })
    return out
