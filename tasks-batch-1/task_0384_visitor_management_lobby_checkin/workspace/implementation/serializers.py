"""Entity -> response-dict serializers.

Computed/derived fields (PRD §2.9, §1.1) are recomputed at read time as aggregates
over SIGNED_IN visits, never trusted as free-floating counters.
"""
import db


def _common(record):
    return {
        "id": record["id"],
        "created_at": record["created_at"],
        "updated_at": record["updated_at"],
        "version": record["version"],
    }


def _signed_in_count_for_site(site_id):
    return sum(1 for v in db.visits.values()
               if v.get("site_id") == site_id and v.get("status") == "SIGNED_IN")


def _signed_in_count_for_floor(floor_id):
    return sum(1 for v in db.visits.values()
               if v.get("floor_id") == floor_id and v.get("status") == "SIGNED_IN")


def site(record):
    badge_in_use = _signed_in_count_for_site(record["id"])
    badge_total = record["badge_total"]
    out = _common(record)
    out.update({
        "name": record["name"],
        "timezone": record["timezone"],
        "badge_total": badge_total,
        "badge_in_use": badge_in_use,
        "badge_available": badge_total - badge_in_use,
    })
    return out


def floor(record):
    current_occupancy = _signed_in_count_for_floor(record["id"])
    capacity = record["capacity"]
    out = _common(record)
    out.update({
        "site_id": record["site_id"],
        "label": record["label"],
        "capacity": capacity,
        "current_occupancy": current_occupancy,
        "available_slots": capacity - current_occupancy,
    })
    return out


def host(record):
    out = _common(record)
    out.update({
        "site_id": record["site_id"],
        "full_name": record["full_name"],
        "email": record["email"],
        "department": record["department"],
        "notify_count": record["notify_count"],
    })
    return out


def watchlist_entry(record):
    out = _common(record)
    out.update({
        "site_id": record["site_id"],
        "match_type": record["match_type"],
        "match_value_normalized": record["match_value_normalized"],
        "severity": record["severity"],
        "active": record["active"],
    })
    return out


def meeting_room(record):
    out = _common(record)
    out.update({
        "floor_id": record["floor_id"],
        "name": record["name"],
        "seats": record["seats"],
    })
    return out


def parking_space(record):
    out = _common(record)
    out.update({
        "site_id": record["site_id"],
        "bay_label": record["bay_label"],
    })
    return out


def visit(record):
    out = _common(record)
    out.update({
        "site_id": record["site_id"],
        "host_id": record["host_id"],
        "floor_id": record["floor_id"],
        "room_id": record.get("room_id"),
        "parking_space_id": record.get("parking_space_id"),
        "contractor_pass_id": record.get("contractor_pass_id"),
        "visitor_full_name": record["visitor_full_name"],
        "visitor_company": record["visitor_company"],
        "scheduled_start": record["scheduled_start"],
        "scheduled_end": record["scheduled_end"],
        "id_scanned": record["id_scanned"],
        "status": record["status"],
        "risk_score": record["risk_score"],
        "sign_in_at": record.get("sign_in_at"),
        "sign_out_at": record.get("sign_out_at"),
        "visit_duration_minutes": record.get("visit_duration_minutes"),
        "badge_number": record.get("badge_number"),
    })
    return out


def agreement(record):
    out = _common(record)
    out.update({
        "visit_id": record["visit_id"],
        "document_kind": record["document_kind"],
        "document_version": record["document_version"],
        "status": record["status"],
        "signed_at": record.get("signed_at"),
        "signer_name": record.get("signer_name"),
    })
    return out


def contractor_pass(record):
    out = _common(record)
    out.update({
        "host_id": record["host_id"],
        "contractor_name": record["contractor_name"],
        "contractor_company": record["contractor_company"],
        "access_valid_from": record["access_valid_from"],
        "access_valid_until": record["access_valid_until"],
        "status": record["status"],
        "covered_visit_count": record["covered_visit_count"],
    })
    return out


def delivery(record):
    out = _common(record)
    out.update({
        "host_id": record["host_id"],
        "carrier": record["carrier"],
        "parcel_fees_cents": record["parcel_fees_cents"],
        "status": record["status"],
        "handling_invoice_cents": record["handling_invoice_cents"],
        "picked_up_at": record.get("picked_up_at"),
    })
    return out


def evacuation_event(record):
    out = _common(record)
    out.update({
        "floor_id": record["floor_id"],
        "triggered_reason": record["triggered_reason"],
        "roster_visit_ids": record["roster_visit_ids"],
        "roster_head_count": record["roster_head_count"],
    })
    return out
