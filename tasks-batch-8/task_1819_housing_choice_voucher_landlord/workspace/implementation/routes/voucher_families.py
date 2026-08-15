"""VoucherFamily endpoints."""

from flask import Blueprint, request

import db
import errors
from middleware import require_roles
from response import success_object, success_list
from routes.helpers import parse_pagination, get_or_404, sorted_page

bp = Blueprint("voucher_families", __name__)


def serialize_family(f):
    return {
        "id": f["id"],
        "family_code": f["family_code"],
        "voucher_bedroom_size": f["voucher_bedroom_size"],
        "annual_income_cents": f["annual_income_cents"],
        "status": f["status"],
        "created_at": f["created_at"],
        "updated_at": f["updated_at"],
        "version": f["version"],
    }


@bp.route("/hcv/voucher-families", methods=["POST"])
def create_family():
    require_roles("HousingAuthorityAdmin")
    body = request.get_json(force=True, silent=True) or {}
    family_code = body.get("family_code")
    voucher_bedroom_size = body.get("voucher_bedroom_size")
    annual_income_cents = body.get("annual_income_cents")
    # unique family_code
    for f in db.voucher_families.values():
        if f["family_code"] == family_code:
            raise errors.APIError(errors.ERR_INVALID_STATE, "family_code already registered", 409)
    # income >= 0
    if annual_income_cents is None or not isinstance(annual_income_cents, int) or annual_income_cents < 0:
        raise errors.invalid_amount("annual_income_cents must be >= 0")
    rec = db.make_record({
        "family_code": family_code,
        "voucher_bedroom_size": voucher_bedroom_size,
        "annual_income_cents": annual_income_cents,
        "status": "SEARCHING",
    })
    db.voucher_families[rec["id"]] = rec
    return success_object(serialize_family(rec), 201)


@bp.route("/hcv/voucher-families/<fid>", methods=["GET"])
def get_family(fid):
    require_roles("HousingAuthorityAdmin")
    f = get_or_404(db.voucher_families, fid, "VoucherFamily")
    return success_object(serialize_family(f))


@bp.route("/hcv/voucher-families/<fid>/exit", methods=["POST"])
def exit_family(fid):
    require_roles("HousingAuthorityAdmin")
    f = get_or_404(db.voucher_families, fid, "VoucherFamily")
    if f["status"] != "SEARCHING":
        raise errors.invalid_state("VoucherFamily must be SEARCHING to exit")
    f["status"] = "EXITED"
    db.touch(f)
    return success_object(serialize_family(f))


@bp.route("/hcv/voucher-families/<fid>/portability-actions", methods=["GET"])
def list_family_portability_actions(fid):
    require_roles("HousingAuthorityAdmin")
    get_or_404(db.voucher_families, fid, "VoucherFamily")
    limit, offset = parse_pagination()
    rows = [p for p in db.portability_actions.values() if p["family_id"] == fid]
    page, total = sorted_page(rows, limit, offset)
    from routes.portability_actions import serialize_portability_action
    return success_list([serialize_portability_action(p) for p in page], total, limit, offset)
