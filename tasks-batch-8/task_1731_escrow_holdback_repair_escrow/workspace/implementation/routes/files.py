"""Escrow file endpoints."""

from db import store
from helpers import (
    get_body, check_allowed_fields, req_string, opt_string, req_date,
    get_file_or_404, new_entity, ser_file, ser_holdback, paginated, sorted_default,
)
from middleware import authenticate, authorize, ALL_ROLES
from response import success

from . import bp


@bp.post("/escrow/files")
def create_file():
    _uid, role = authenticate()
    authorize(role, ["EscrowOfficer"])
    data = get_body()
    check_allowed_fields(
        data,
        {"property_address", "closing_date", "buyer_user_id", "seller_user_id",
         "lender_user_id", "insurer_user_id"},
    )
    addr = req_string(data, "property_address")
    closing = req_date(data, "closing_date")
    buyer = req_string(data, "buyer_user_id")
    seller = req_string(data, "seller_user_id")
    lender = req_string(data, "lender_user_id")
    insurer = opt_string(data, "insurer_user_id")
    f = new_entity()
    f.update({
        "property_address": addr,
        "closing_date": closing,
        "buyer_user_id": buyer,
        "seller_user_id": seller,
        "lender_user_id": lender,
        "insurer_user_id": insurer,
        "status": "OPEN",
    })
    store.files[f["id"]] = f
    return success(ser_file(f), response_type="object", status=201)


@bp.get("/escrow/files/<fid>")
def get_file(fid):
    _uid, role = authenticate()
    authorize(role, ALL_ROLES)
    f = get_file_or_404(fid)
    return success(ser_file(f), response_type="object", status=200)


@bp.get("/escrow/files/<fid>/holdbacks")
def list_file_holdbacks(fid):
    _uid, role = authenticate()
    authorize(role, ALL_ROLES)
    get_file_or_404(fid)
    items = [h for h in store.holdbacks.values() if h["escrow_file_id"] == fid]
    return paginated(sorted_default(items), ser_holdback)
