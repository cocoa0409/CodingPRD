"""Receipt upload & retrieve."""
from __future__ import annotations

from flask import Blueprint

from core.auth import current_user_id, require_roles
from core.envelope import get_json_body, success_response
from core.errors import err_not_found, err_validation
from core.serializers import serialize_receipt
from core.store import store
from core.utils import is_int, is_number, lock, new_id, now_iso, parse_iso


bp = Blueprint("receipts", __name__)


@bp.post("/receipts")
@require_roles("TRAVELER")
def create_receipt():
    body = get_json_body()
    required = ["merchant_name", "merchant_total_cents", "ocr_extracted_date", "ocr_confidence"]
    for f in required:
        if body.get(f) is None:
            raise err_validation(f"{f} is required.")

    if not is_int(body["merchant_total_cents"]) or body["merchant_total_cents"] < 0:
        raise err_validation("merchant_total_cents must be a non-negative integer.")
    if not is_number(body["ocr_confidence"]):
        raise err_validation("ocr_confidence must be a number.")
    confidence = float(body["ocr_confidence"])
    if confidence < 0 or confidence > 1:
        raise err_validation("ocr_confidence must be within [0, 1].")
    try:
        parse_iso(body["ocr_extracted_date"])
    except ValueError as exc:
        raise err_validation(str(exc))

    with lock():
        rec = {
            "id": new_id(),
            "uploader_employee_id": current_user_id(),
            "merchant_name": body["merchant_name"],
            "merchant_total_cents": int(body["merchant_total_cents"]),
            "ocr_extracted_date": body["ocr_extracted_date"],
            "ocr_confidence": confidence,
            "used_by_line_id": None,
            "created_at": now_iso(),
        }
        store.receipts[rec["id"]] = rec

    return success_response(serialize_receipt(rec), status=201)


@bp.get("/receipts/<rid>")
@require_roles("TRAVELER", "FINANCE_REVIEWER", "ADMIN")
def get_receipt(rid):
    rec = store.receipts.get(rid)
    if rec is None:
        raise err_not_found(f"Receipt {rid} not found.")
    return success_response(serialize_receipt(rec))
