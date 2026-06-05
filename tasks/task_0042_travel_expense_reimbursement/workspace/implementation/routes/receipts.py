"""Receipt routes: upload, get, list, ocr, verify, dispute."""
from flask import Blueprint, request, g

from common import (get_json_body, require_fields, require_string,
                    require_nonneg_int, paginate, list_response)
from db import store, base_fields, touch
from errors import err
from middleware import require_roles
from response import success
from services import get_or_404

bp = Blueprint("receipts", __name__)


def _receipt_view(r):
    return dict(r)


def _owns_line(line):
    report = store.expense_reports.get(line["report_id"])
    if report is None:
        return False
    trip = store.trip_requests.get(report["trip_request_id"])
    if trip is None:
        return False
    return trip["traveler_id"] == g.user_id


@bp.route("/receipts", methods=["POST"])
@require_roles("Traveler")
def upload_receipt():
    body = get_json_body()
    require_fields(body, ["expense_line_id", "image_ref"])
    line_id = require_string(body, "expense_line_id")
    # FK existence
    line = get_or_404(store.expense_lines, line_id)
    # ownership
    if not _owns_line(line):
        raise err("ERR_NOT_OWNER", "Traveler does not own this line")
    image_ref = require_string(body, "image_ref")
    r = base_fields()
    r.update({
        "expense_line_id": line_id,
        "image_ref": image_ref,
        "ocr_amount_cents": None,
        "ocr_merchant": None,
        "status": "UPLOADED",
    })
    store.receipts[r["id"]] = r
    return success(_receipt_view(r), status=201)


@bp.route("/receipts/<receipt_id>", methods=["GET"])
@require_roles("FinanceAdmin", "Traveler", "Approver")
def get_receipt(receipt_id):
    r = get_or_404(store.receipts, receipt_id)
    return success(_receipt_view(r))


@bp.route("/receipts", methods=["GET"])
@require_roles("FinanceAdmin", "Traveler", "Approver")
def list_receipts():
    limit, offset = paginate()
    items = list(store.receipts.values())
    line_id = request.args.get("expense_line_id")
    if line_id is not None:
        items = [r for r in items if r["expense_line_id"] == line_id]
    page, pagination = list_response(items, limit, offset)
    return success([_receipt_view(r) for r in page], pagination=pagination)


@bp.route("/receipts/<receipt_id>/ocr", methods=["POST"])
@require_roles("FinanceAdmin")
def ocr_receipt(receipt_id):
    r = get_or_404(store.receipts, receipt_id)
    body = get_json_body()
    require_fields(body, ["ocr_amount_cents", "ocr_merchant"])
    ocr_amount = require_nonneg_int(body, "ocr_amount_cents")
    ocr_merchant = require_string(body, "ocr_merchant")
    if r["status"] != "UPLOADED":
        raise err("ERR_INVALID_STATE", "Receipt is not UPLOADED")
    r["ocr_amount_cents"] = ocr_amount
    r["ocr_merchant"] = ocr_merchant
    r["status"] = "OCR_PROCESSED"
    touch(r)
    return success(_receipt_view(r))


@bp.route("/receipts/<receipt_id>/verify", methods=["POST"])
@require_roles("FinanceAdmin")
def verify_receipt(receipt_id):
    r = get_or_404(store.receipts, receipt_id)
    if r["status"] not in ("OCR_PROCESSED", "DISPUTED"):
        raise err("ERR_INVALID_STATE", "Receipt cannot be verified from its current state")
    # business: ocr_amount equals linked line claimed_amount
    line = store.expense_lines.get(r["expense_line_id"])
    line_claimed = line["claimed_amount_cents"] if line else None
    if r["ocr_amount_cents"] != line_claimed:
        raise err("ERR_RECEIPT_AMOUNT_MISMATCH", "OCR amount does not match claimed amount")
    r["status"] = "VERIFIED"
    touch(r)
    return success(_receipt_view(r))


@bp.route("/receipts/<receipt_id>/dispute", methods=["POST"])
@require_roles("FinanceAdmin")
def dispute_receipt(receipt_id):
    r = get_or_404(store.receipts, receipt_id)
    if r["status"] != "OCR_PROCESSED":
        raise err("ERR_INVALID_STATE", "Receipt is not OCR_PROCESSED")
    r["status"] = "DISPUTED"
    touch(r)
    return success(_receipt_view(r))
