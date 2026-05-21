"""Serialization helpers — convert internal entity dicts to API responses.

Internal storage keeps Decimals as Decimals (for precision); the serializers
render them with exactly two decimal places per PRD §2.6.
"""

from utils import decimal_to_serial


def _common(entity: dict) -> dict:
    """Render id/created_at/updated_at/version when present."""
    out = {
        "id": entity["id"],
    }
    if "created_at" in entity:
        out["created_at"] = entity["created_at"]
    if "updated_at" in entity:
        out["updated_at"] = entity["updated_at"]
    if "version" in entity:
        out["version"] = entity["version"]
    return out


def serialize_owner(owner: dict) -> dict:
    base = _common(owner)
    base.update({
        "full_name": owner["full_name"],
        "date_of_birth": owner["date_of_birth"],
        "residency_state": owner["residency_state"],
        "real_id_status": owner["real_id_status"],
        "real_id_score": decimal_to_serial(owner["real_id_score"])
            if owner.get("real_id_score") is not None else None,
        "real_id_expires_at": owner.get("real_id_expires_at"),
        "is_resident": owner["is_resident"],
        "outstanding_holds_count": owner["outstanding_holds_count"],
    })
    return base


def serialize_vehicle(vehicle: dict) -> dict:
    base = _common(vehicle)
    base.update({
        "vin": vehicle["vin"],
        "make": vehicle["make"],
        "model": vehicle["model"],
        "model_year": vehicle["model_year"],
        "curb_weight_lbs": vehicle["curb_weight_lbs"],
        "fuel_type": vehicle["fuel_type"],
        "vin_verification_status": vehicle["vin_verification_status"],
        "vin_verified_at": vehicle.get("vin_verified_at"),
        "title_status": vehicle["title_status"],
        "lien_status": vehicle["lien_status"],
        "current_title_id": vehicle.get("current_title_id"),
        "emissions_expires_at": vehicle.get("emissions_expires_at"),
    })
    return base


def serialize_title(title: dict) -> dict:
    # Title has only id + issued_at (no updated_at, no version per PRD §2.4).
    return {
        "id": title["id"],
        "vehicle_id": title["vehicle_id"],
        "owner_id": title["owner_id"],
        "brand": title["brand"],
        "issued_at": title["issued_at"],
        "superseded_at": title.get("superseded_at"),
        "is_active": title["is_active"],
        "source_application_id": title.get("source_application_id"),
    }


def serialize_lien_record(lien: dict) -> dict:
    base = _common(lien)
    base.update({
        "title_id": lien["title_id"],
        "lienholder_name": lien["lienholder_name"],
        "principal_amount": decimal_to_serial(lien["principal_amount"]),
        "status": lien["status"],
        "released_at": lien.get("released_at"),
        "release_reference": lien.get("release_reference"),
    })
    return base


def serialize_inspection(insp: dict) -> dict:
    base = _common(insp)
    base.update({
        "vehicle_id": insp["vehicle_id"],
        "station_id": insp["station_id"],
        "scheduled_start": insp["scheduled_start"],
        "scheduled_end": insp["scheduled_end"],
        "status": insp["status"],
        "result_recorded_at": insp.get("result_recorded_at"),
        "odometer_reading": insp.get("odometer_reading"),
    })
    return base


def serialize_realid_application(app: dict) -> dict:
    base = _common(app)
    base.update({
        "owner_id": app["owner_id"],
        "status": app["status"],
        "documents_proof_of_identity": app["documents_proof_of_identity"],
        "documents_proof_of_residency": app["documents_proof_of_residency"],
        "documents_proof_of_ssn": app["documents_proof_of_ssn"],
        "revision_count": app["revision_count"],
        "approved_at": app.get("approved_at"),
    })
    return base


def serialize_plate(plate: dict) -> dict:
    base = _common(plate)
    base.update({
        "plate_number": plate["plate_number"],
        "vehicle_id": plate["vehicle_id"],
        "status": plate["status"],
        "activated_at": plate.get("activated_at"),
        "suspended_at": plate.get("suspended_at"),
        "surrender_reason": plate.get("surrender_reason"),
    })
    return base


def serialize_transfer_application(app: dict) -> dict:
    base = _common(app)
    base.update({
        "vehicle_id": app["vehicle_id"],
        "applicant_owner_id": app["applicant_owner_id"],
        "application_type": app["application_type"],
        "status": app["status"],
        "salvage_branch_taken": app["salvage_branch_taken"],
        "trade_in_value": decimal_to_serial(app["trade_in_value"]),
        "declared_sale_price": decimal_to_serial(app["declared_sale_price"]),
        "fee_subtotal": decimal_to_serial(app["fee_subtotal"]) if app.get("fee_subtotal") is not None else None,
        "processing_fee": decimal_to_serial(app["processing_fee"]) if app.get("processing_fee") is not None else None,
        "total_due": decimal_to_serial(app["total_due"]) if app.get("total_due") is not None else None,
        "paid_at": app.get("paid_at"),
        "plate_id": app.get("plate_id"),
        "rejection_reason": app.get("rejection_reason"),
    })
    return base


def serialize_ledger_entry(entry: dict) -> dict:
    return {
        "id": entry["id"],
        "application_id": entry["application_id"],
        "kind": entry["kind"],
        "amount_cents": entry["amount_cents"],
        "occurred_at": entry["occurred_at"],
    }
