"""Mileage routes — SCAFFOLD §1.5 / PRD §3.6."""
from decimal import Decimal

from flask import Blueprint, jsonify

from ..auth import require_auth
from ..errors import APIError
from ..helpers import get_json_body, require_field
from ..responses import success_response
from ..services import calculations as calc
from ..services.serialize import mileage_view
from ..store import get_lock, get_store, new_id, real_now_iso, stamp_create


bp = Blueprint("mileage", __name__)


def _find_visit(visit_id: str) -> dict:
    v = get_store().visits.get(visit_id)
    if v is None:
        raise APIError("ERR_NOT_FOUND", f"Visit {visit_id} not found")
    return v


@bp.post("/visits/<visit_id>/mileage")
@require_auth("FieldClinician")
def record_mileage(visit_id: str):
    body = get_json_body()
    miles_raw = require_field(body, "miles_driven")
    try:
        miles = calc.to_decimal(miles_raw)
    except (TypeError, ValueError, Exception):
        raise APIError("ERR_VALIDATION", "miles_driven must be a number")

    with get_lock():
        v = _find_visit(visit_id)

        # Priority 17: miles_driven > 0.
        if miles <= 0:
            raise APIError("ERR_MILEAGE_NOT_POSITIVE", "miles_driven must be > 0")

        # Priority 18: parent visit must be COMPLETED.
        if v["status"] != "COMPLETED":
            raise APIError(
                "ERR_MILEAGE_VISIT_NOT_COMPLETED",
                "Parent Visit must be in COMPLETED to record mileage",
            )

        reimbursement = calc.mileage_reimbursement(miles)

        # Quantize miles_driven for storage to keep serialized value stable.
        # Spec doesn't pin precision on miles_driven itself, but normalize to
        # avoid float-noise on the response surface.
        miles_stored = miles

        record = {
            "id": new_id(),
            "visit_id": visit_id,
            "episode_id": v["episode_id"],
            "miles_driven": miles_stored,
            "reimbursement_amount": reimbursement,
            "created_at": real_now_iso(),
        }
        # MileageLog has no updated_at / version per SCAFFOLD §1.1 + PRD §2.4.
        # stamp_create would add them — instead set id + created_at directly.
        get_store().mileage_logs[record["id"]] = record

        body_out, status = success_response(mileage_view(record), status=201)
    return jsonify(body_out), status


@bp.get("/visits/<visit_id>/mileage")
@require_auth("FieldClinician", "BillingSpecialist")
def list_mileage(visit_id: str):
    _find_visit(visit_id)
    items = [
        m for m in get_store().mileage_logs.values() if m["visit_id"] == visit_id
    ]
    items.sort(key=lambda m: m["created_at"])
    # mileage listing is unpaginated in the SCAFFOLD endpoint table (input: []).
    body, status = success_response(
        [mileage_view(m) for m in items], status=200, response_type="array"
    )
    return jsonify(body), status
