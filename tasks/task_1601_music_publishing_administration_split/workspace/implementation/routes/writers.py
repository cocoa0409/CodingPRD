from flask import Blueprint, request

from db import STORE
from errors import ApiError, ERR_FORBIDDEN, ERR_INVALID_STATE_TRANSITION, ERR_VALIDATION
from middleware import ALL_ROLES, auth_context, require_roles
from response import success
from serializers import writer_view
from services import get_or_404, new_record, sorted_all, touch
from validators import body_json, paginate, pagination_params, req_enum, req_str

bp = Blueprint("writers", __name__)

PRO_AFFILIATIONS = ["ASCAP", "BMI", "SESAC", "PRS", "GEMA", "SACEM", "NONE"]


@bp.route("/writers", methods=["POST"], strict_slashes=False)
def create_writer():
    uid, role = auth_context()
    require_roles(role, ["PublisherAdmin"])
    body = body_json()
    legal_name = req_str(body, "legal_name")
    ipi_number = req_str(body, "ipi_number")
    pro_affiliation = req_enum(body, "pro_affiliation", PRO_AFFILIATIONS)
    if len(ipi_number) < 9 or len(ipi_number) > 13:
        raise ApiError(ERR_VALIDATION, 422,
                       "ipi_number must be 9 to 13 characters")
    for existing in STORE["writers"].values():
        if existing["ipi_number"] == ipi_number:
            raise ApiError(ERR_VALIDATION, 422,
                           "ipi_number must be unique across all writers")
    w = new_record()
    w.update({
        "legal_name": legal_name,
        "ipi_number": ipi_number,
        "pro_affiliation": pro_affiliation,
        "status": "ACTIVE",
        "payable_balance_cents": 0,
        "advance_outstanding_cents": 0,
        "lifetime_earned_cents": 0,
    })
    STORE["writers"][w["id"]] = w
    return success(writer_view(w), status=201)


@bp.route("/writers", methods=["GET"], strict_slashes=False)
def list_writers():
    uid, role = auth_context()
    require_roles(role, ALL_ROLES)
    limit, offset = pagination_params()
    items = sorted_all("writers")
    status = request.args.get("status")
    pro = request.args.get("pro_affiliation")
    if status is not None:
        items = [w for w in items if w["status"] == status]
    if pro is not None:
        items = [w for w in items if w["pro_affiliation"] == pro]
    page, meta = paginate(items, limit, offset)
    return success([writer_view(w) for w in page], response_type="array",
                   pagination=meta)


@bp.route("/writers/<wid>", methods=["GET"], strict_slashes=False)
def get_writer(wid):
    uid, role = auth_context()
    require_roles(role, ALL_ROLES)
    w = get_or_404("writers", wid, "writer")
    return success(writer_view(w))


@bp.route("/writers/<wid>/earnings-summary", methods=["GET"], strict_slashes=False)
def earnings_summary(wid):
    uid, role = auth_context()
    require_roles(role, ["PublisherAdmin", "RoyaltyAnalyst", "FinanceManager", "Writer"])
    if role == "Writer" and uid != wid:
        raise ApiError(ERR_FORBIDDEN, 403,
                       "a Writer may only read their own earnings summary")
    w = get_or_404("writers", wid, "writer")
    return success({
        "writer_id": w["id"],
        "status": w["status"],
        "payable_balance_cents": w["payable_balance_cents"],
        "advance_outstanding_cents": w["advance_outstanding_cents"],
        "lifetime_earned_cents": w["lifetime_earned_cents"],
    })


@bp.route("/writers/<wid>/suspend", methods=["POST"], strict_slashes=False)
def suspend_writer(wid):
    uid, role = auth_context()
    require_roles(role, ["PublisherAdmin"])
    w = get_or_404("writers", wid, "writer")
    if w["status"] != "ACTIVE":
        raise ApiError(ERR_INVALID_STATE_TRANSITION, 409,
                       "only an ACTIVE writer can be suspended")
    w["status"] = "SUSPENDED"
    touch(w)
    return success(writer_view(w))


@bp.route("/writers/<wid>/reactivate", methods=["POST"], strict_slashes=False)
def reactivate_writer(wid):
    uid, role = auth_context()
    require_roles(role, ["PublisherAdmin"])
    w = get_or_404("writers", wid, "writer")
    if w["status"] != "SUSPENDED":
        raise ApiError(ERR_INVALID_STATE_TRANSITION, 409,
                       "only a SUSPENDED writer can be reactivated")
    w["status"] = "ACTIVE"
    touch(w)
    return success(writer_view(w))
