"""Entity serializers: exact public field sets per the scaffold entity table.

ULDType and TemperatureLog are deliberately lighter-weight (PRD 2.4): they
carry only id + created_at -- updated_at and version are absent.
"""

import services


def flight(f: dict) -> dict:
    return {
        "id": f["id"],
        "flight_number": f["flight_number"],
        "origin": f["origin"],
        "destination": f["destination"],
        "scheduled_departure": f["scheduled_departure"],
        "scheduled_arrival": f["scheduled_arrival"],
        "max_payload_kg": f["max_payload_kg"],
        "max_volume_m3": f["max_volume_m3"],
        "uld_position_count": f["uld_position_count"],
        "dg_certified": f["dg_certified"],
        "allocated_weight_kg": services.num(services.allocated_weight_kg(f["id"])),
        "allocated_volume_m3": services.num(services.allocated_volume_m3(f["id"])),
        "reserved_positions": services.reserved_positions(f["id"]),
        "weight_restriction_kg": f["weight_restriction_kg"],
        "status": f["status"],
        "created_at": f["created_at"],
        "updated_at": f["updated_at"],
        "version": f["version"],
    }


def booking(b: dict) -> dict:
    return {
        "id": b["id"],
        "flight_id": b["flight_id"],
        "shipper_ref": b["shipper_ref"],
        "commodity_code": b["commodity_code"],
        "pieces": b["pieces"],
        "gross_weight_kg": b["gross_weight_kg"],
        "volume_m3": b["volume_m3"],
        "chargeable_weight_kg": b["chargeable_weight_kg"],
        "is_dangerous_goods": b["is_dangerous_goods"],
        "temp_min_c": b["temp_min_c"],
        "temp_max_c": b["temp_max_c"],
        "declared_value": b["declared_value"],
        "temp_excursion_count": b["temp_excursion_count"],
        "temp_status": b["temp_status"],
        "build_up_plan_id": b["build_up_plan_id"],
        "created_by_user_id": b["created_by_user_id"],
        "status": b["status"],
        "created_at": b["created_at"],
        "updated_at": b["updated_at"],
        "version": b["version"],
    }


def uld_type(t: dict) -> dict:
    return {
        "id": t["id"],
        "type_code": t["type_code"],
        "tare_weight_kg": t["tare_weight_kg"],
        "max_gross_weight_kg": t["max_gross_weight_kg"],
        "internal_volume_m3": t["internal_volume_m3"],
        "created_at": t["created_at"],
    }


def uld(u: dict) -> dict:
    return {
        "id": u["id"],
        "uld_code": u["uld_code"],
        "uld_type_id": u["uld_type_id"],
        "status": u["status"],
        "dispatched_at": u["dispatched_at"],
        "returned_at": u["returned_at"],
        "created_at": u["created_at"],
        "updated_at": u["updated_at"],
        "version": u["version"],
    }


def build_up_plan(p: dict) -> dict:
    return {
        "id": p["id"],
        "flight_id": p["flight_id"],
        "uld_id": p["uld_id"],
        "build_start": p["build_start"],
        "build_end": p["build_end"],
        "total_weight_kg": services.num(services.plan_total_weight_kg(p["id"])),
        "status": p["status"],
        "created_at": p["created_at"],
        "updated_at": p["updated_at"],
        "version": p["version"],
    }


def dg_declaration(d: dict) -> dict:
    return {
        "id": d["id"],
        "booking_id": d["booking_id"],
        "un_number": d["un_number"],
        "dg_class": d["dg_class"],
        "packing_group": d["packing_group"],
        "declaration_doc_ref": d["declaration_doc_ref"],
        "checked_by_user_id": d["checked_by_user_id"],
        "rejection_reason": d["rejection_reason"],
        "status": d["status"],
        "created_at": d["created_at"],
        "updated_at": d["updated_at"],
        "version": d["version"],
    }


def temperature_log(t: dict) -> dict:
    return {
        "id": t["id"],
        "booking_id": t["booking_id"],
        "recorded_at": t["recorded_at"],
        "temperature_c": t["temperature_c"],
        "in_range": t["in_range"],
        "created_at": t["created_at"],
    }


def customs_hold(h: dict) -> dict:
    return {
        "id": h["id"],
        "booking_id": h["booking_id"],
        "reason_code": h["reason_code"],
        "placed_at": h["placed_at"],
        "released_at": h["released_at"],
        "release_note": h["release_note"],
        "status": h["status"],
        "created_at": h["created_at"],
        "updated_at": h["updated_at"],
        "version": h["version"],
    }


def claim(c: dict) -> dict:
    return {
        "id": c["id"],
        "booking_id": c["booking_id"],
        "claim_type": c["claim_type"],
        "claimed_amount": c["claimed_amount"],
        "items": c["items"],
        "description": c["description"],
        "item_total": c["item_total"],
        "basis": c["basis"],
        "approved_amount": c["approved_amount"],
        "settlement_ref": c["settlement_ref"],
        "status": c["status"],
        "created_at": c["created_at"],
        "updated_at": c["updated_at"],
        "version": c["version"],
    }


def uld_charge(c: dict) -> dict:
    return {
        "id": c["id"],
        "uld_id": c["uld_id"],
        "charge_type": c["charge_type"],
        "amount": c["amount"],
        "tier1_days": c["tier1_days"],
        "tier2_days": c["tier2_days"],
        "description": c["description"],
        "status": c["status"],
        "created_at": c["created_at"],
        "updated_at": c["updated_at"],
        "version": c["version"],
    }
