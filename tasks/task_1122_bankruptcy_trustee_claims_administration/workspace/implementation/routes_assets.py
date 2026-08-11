"""Asset endpoints: scheduling, investigation, marking, abandonment, exemption."""
from flask import Blueprint, request

import db
from errors import (
    ApiError, ERR_INVALID_STATE, ERR_REFERENTIAL_INTEGRITY, ERR_ASSET_EXEMPT,
)
from middleware import auth_context, require_roles, json_body, ALL_ROLES
from response import ok_object, paginate
from services_common import (
    new_entity, touch, get_case, get_or_404, ensure_case_open,
    ensure_trustee_binding, ser_asset, ser_sale, sorted_rows,
)
from util import require_str, require_int, optional_bool

bp = Blueprint("assets", __name__)


def _get_asset_and_case(asset_id):
    asset = get_or_404(db.assets, asset_id, "asset")
    return asset, db.cases[asset["case_id"]]


@bp.route("/trustee/cases/<id>/assets", methods=["POST"])
def create_asset(id):
    uid, role = auth_context()
    require_roles(role, ("Trustee", "Clerk"))
    case = get_case(id)
    ensure_case_open(case)
    if role == "Trustee":
        ensure_trustee_binding(case, uid)
    body = json_body()

    raw_claim = body.get("encumbered_claim_id")
    if isinstance(raw_claim, str):
        claim = db.claims.get(raw_claim)
        if claim is None or claim["case_id"] != id:
            raise ApiError(ERR_REFERENTIAL_INTEGRITY, 422,
                           "encumbered_claim_id must name a claim of this case.")

    description = require_str(body, "description")
    scheduled_value = require_int(body, "scheduled_value_cents", minimum=0)
    exempt = optional_bool(body, "exempt")
    if raw_claim is not None and not isinstance(raw_claim, str):
        from errors import ERR_INVALID_REQUEST
        raise ApiError(ERR_INVALID_REQUEST, 400, "encumbered_claim_id must be a string.")

    asset = new_entity({
        "case_id": id,
        "description": description,
        "scheduled_value_cents": scheduled_value,
        "exempt": exempt if exempt is not None else False,
        "encumbered_claim_id": raw_claim,
        "status": "SCHEDULED",
        "realized_proceeds_cents": 0,
    })
    db.assets[asset["id"]] = asset
    return ok_object(ser_asset(asset), status=201)


@bp.route("/trustee/cases/<id>/assets", methods=["GET"])
def list_case_assets(id):
    auth_context()
    require_roles(request.headers.get("X-User-Role"), ALL_ROLES)
    get_case(id)
    status = request.args.get("status")
    rows = [a for a in db.assets.values() if a["case_id"] == id]
    if status is not None:
        rows = [a for a in rows if a["status"] == status]
    return paginate([ser_asset(a) for a in sorted_rows(rows)])


@bp.route("/trustee/assets/<id>", methods=["GET"])
def get_asset(id):
    auth_context()
    require_roles(request.headers.get("X-User-Role"), ALL_ROLES)
    return ok_object(ser_asset(get_or_404(db.assets, id, "asset")))


@bp.route("/trustee/assets/<id>/sales", methods=["GET"])
def asset_sales(id):
    auth_context()
    require_roles(request.headers.get("X-User-Role"), ALL_ROLES)
    get_or_404(db.assets, id, "asset")
    rows = [s for s in db.sales.values() if s["asset_id"] == id]
    return paginate([ser_sale(s) for s in sorted_rows(rows)])


@bp.route("/trustee/assets/<id>/investigate", methods=["POST"])
def investigate_asset(id):
    uid, role = auth_context()
    require_roles(role, ("Trustee",))
    asset, case = _get_asset_and_case(id)
    ensure_case_open(case)
    if asset["status"] != "SCHEDULED":
        raise ApiError(ERR_INVALID_STATE, 409, "Asset must be SCHEDULED to investigate.")
    ensure_trustee_binding(case, uid)
    asset["status"] = "UNDER_INVESTIGATION"
    touch(asset)
    return ok_object(ser_asset(asset))


@bp.route("/trustee/assets/<id>/mark_for_sale", methods=["POST"])
def mark_for_sale(id):
    uid, role = auth_context()
    require_roles(role, ("Trustee",))
    asset, case = _get_asset_and_case(id)
    ensure_case_open(case)
    if asset["status"] != "UNDER_INVESTIGATION":
        raise ApiError(ERR_INVALID_STATE, 409, "Asset must be UNDER_INVESTIGATION to mark for sale.")
    ensure_trustee_binding(case, uid)
    if asset["exempt"]:
        raise ApiError(ERR_ASSET_EXEMPT, 409, "An exempt asset may not be liquidated.")
    if case["status"] not in ("CLAIMS_ADMINISTRATION", "LIQUIDATION"):
        raise ApiError(ERR_INVALID_STATE, 409,
                       "Case must be in CLAIMS_ADMINISTRATION or LIQUIDATION to mark an asset for sale.")
    asset["status"] = "MARKED_FOR_SALE"
    touch(asset)
    return ok_object(ser_asset(asset))


@bp.route("/trustee/assets/<id>/abandon", methods=["POST"])
def abandon_asset(id):
    uid, role = auth_context()
    require_roles(role, ("Trustee",))
    asset, case = _get_asset_and_case(id)
    ensure_case_open(case)
    if asset["status"] not in ("UNDER_INVESTIGATION", "MARKED_FOR_SALE"):
        raise ApiError(ERR_INVALID_STATE, 409,
                       "Only an UNDER_INVESTIGATION or MARKED_FOR_SALE asset may be abandoned.")
    ensure_trustee_binding(case, uid)
    asset["status"] = "ABANDONED"
    touch(asset)
    return ok_object(ser_asset(asset))


@bp.route("/trustee/assets/<id>/release_exemption", methods=["POST"])
def release_exemption(id):
    _, role = auth_context()
    require_roles(role, ("Court",))
    asset, case = _get_asset_and_case(id)
    ensure_case_open(case)
    if asset["status"] not in ("SCHEDULED", "UNDER_INVESTIGATION"):
        raise ApiError(ERR_INVALID_STATE, 409,
                       "Only a SCHEDULED or UNDER_INVESTIGATION asset may be exemption-released.")
    if not asset["exempt"]:
        raise ApiError(ERR_INVALID_STATE, 409, "The asset is not claimed exempt.")
    asset["status"] = "EXEMPT_RELEASED"
    touch(asset)
    return ok_object(ser_asset(asset))
