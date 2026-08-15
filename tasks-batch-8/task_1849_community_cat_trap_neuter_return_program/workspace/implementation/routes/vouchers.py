"""Voucher issuance and expiry (PRD §3.8, §2.8).

Issuance enforces the monthly cap: at most 30,000 cents per caretaker per
logical calendar month across both funding sources, counting only vouchers in
ISSUED / COMMITTED / REDEEMED; a request that lands exactly on the cap is
admitted. The expiry sweep moves ISSUED vouchers at least 3 calendar months
old to EXPIRED and is rejected with ERR_NOTHING_TO_EXPIRE when nothing
qualifies.
"""

from flask import Blueprint

from db import db
from errors import (ApiError, ERR_MONTHLY_CAP_EXCEEDED, ERR_NOTHING_TO_EXPIRE,
                    not_found)
from middleware import json_body, require_roles
from response import success_array, success_object
from services.voucher_service import (cap_headroom, current_month,
                                      expirable_vouchers)
from util import public, req_enum, req_int, req_str, sorted_created, stamp_common, touch

bp = Blueprint("vouchers", __name__)

FUNDING_SOURCES = {"MUNICIPAL_GRANT", "DONATION_FUND"}


@bp.post("/tnr/vouchers")
@require_roles("ProgramCoordinator")
def create_voucher(user_id, role):
    body = json_body()
    caretaker_id = req_str(body, "caretaker_id")
    face_value_cents = req_int(body, "face_value_cents", minimum=1)
    funding_source = req_enum(body, "funding_source", FUNDING_SOURCES)

    if caretaker_id not in db.caretakers:
        raise not_found("caretaker")

    month = current_month()
    if face_value_cents > cap_headroom(caretaker_id, month):
        raise ApiError(ERR_MONTHLY_CAP_EXCEEDED, 402,
                       "Voucher issuance would exceed the caretaker's monthly "
                       "issuance cap of 30000 cents.")

    voucher = stamp_common({
        "caretaker_id": caretaker_id,
        "face_value_cents": face_value_cents,
        "funding_source": funding_source,
        "issued_month": month,
        "status": "ISSUED",
        "reimbursement_cents": None,
        "caretaker_share_cents": None,
    })
    db.vouchers[voucher["id"]] = voucher
    return success_object(public(voucher), status=201)


@bp.get("/tnr/vouchers/<vid>")
@require_roles("ProgramCoordinator", "Caretaker")
def get_voucher(vid, user_id, role):
    voucher = db.vouchers.get(vid)
    if voucher is None:
        raise not_found("voucher")
    return success_object(public(voucher))


@bp.post("/tnr/vouchers/expire-sweep")
@require_roles("ProgramCoordinator")
def expire_sweep(user_id, role):
    matches = sorted_created(expirable_vouchers())
    if not matches:
        raise ApiError(ERR_NOTHING_TO_EXPIRE, 422,
                       "No ISSUED voucher is at least 3 months old.")
    for voucher in matches:
        voucher["status"] = "EXPIRED"
        touch(voucher)
    items = [public(v) for v in matches]
    return success_array(items, total_count=len(items), limit=len(items),
                         offset=0)
