from flask import Blueprint, request

import db
from db import STORE
from errors import (
    ApiError,
    ERR_INVALID_STATE_TRANSITION,
    ERR_STALE_VERSION,
    ERR_VALIDATION,
    ERR_WRITER_NOT_ACTIVE,
)
from middleware import ALL_ROLES, auth_context, require_roles
from response import success
from serializers import advance_view
from services import (
    get_or_404, new_record, recompute_writer_rollups, sorted_all, touch,
)
from validators import body_json, opt_int, paginate, pagination_params, req_int, req_str

bp = Blueprint("advances", __name__)


@bp.route("/advances", methods=["POST"], strict_slashes=False)
def create_advance():
    uid, role = auth_context()
    require_roles(role, ["PublisherAdmin"])
    body = body_json()
    writer_id = body.get("writer_id")
    if not isinstance(writer_id, str) or not writer_id:
        raise ApiError(ERR_VALIDATION, 422, "writer_id is required")
    writer = get_or_404("writers", writer_id, "writer")
    agreement_ref = req_str(body, "agreement_ref")
    amount_cents = req_int(body, "amount_cents", lo=1)
    recoup_rate_bp = opt_int(body, "recoup_rate_bp", lo=1, hi=10000)
    if recoup_rate_bp is None:
        recoup_rate_bp = 10000
    expected = body.get("expected_writer_version")
    if expected is None or isinstance(expected, bool) or not isinstance(expected, int):
        raise ApiError(ERR_VALIDATION, 422,
                       "expected_writer_version is required and must be an integer")
    if expected != writer["version"]:
        raise ApiError(ERR_STALE_VERSION, 412,
                       "expected_writer_version does not match the writer's "
                       "current version")
    a = new_record()
    a.update({
        "writer_id": writer_id,
        "agreement_ref": agreement_ref,
        "amount_cents": amount_cents,
        "recoup_rate_bp": recoup_rate_bp,
        "status": "DRAFT",
        "recouped_cents": 0,
        "outstanding_cents": 0,
        "paid_at": None,
    })
    STORE["advances"][a["id"]] = a
    touch(writer)  # creating an advance increments the parent Writer version
    return success(advance_view(a), status=201)


@bp.route("/advances", methods=["GET"], strict_slashes=False)
def list_advances():
    uid, role = auth_context()
    require_roles(role, ALL_ROLES)
    limit, offset = pagination_params()
    items = sorted_all("advances")
    writer_id = request.args.get("writer_id")
    status = request.args.get("status")
    if writer_id is not None:
        items = [a for a in items if a["writer_id"] == writer_id]
    if status is not None:
        items = [a for a in items if a["status"] == status]
    page, meta = paginate(items, limit, offset)
    return success([advance_view(a) for a in page],
                   response_type="array", pagination=meta)


@bp.route("/advances/<aid>", methods=["GET"], strict_slashes=False)
def get_advance(aid):
    uid, role = auth_context()
    require_roles(role, ALL_ROLES)
    a = get_or_404("advances", aid, "advance")
    return success(advance_view(a))


@bp.route("/advances/<aid>/approve", methods=["POST"], strict_slashes=False)
def approve_advance(aid):
    uid, role = auth_context()
    require_roles(role, ["FinanceManager"])
    a = get_or_404("advances", aid, "advance")
    if a["status"] != "DRAFT":
        raise ApiError(ERR_INVALID_STATE_TRANSITION, 409,
                       "approve requires status DRAFT")
    writer = STORE["writers"][a["writer_id"]]
    if writer["status"] != "ACTIVE":
        raise ApiError(ERR_WRITER_NOT_ACTIVE, 409,
                       "the writer is not ACTIVE")
    a["status"] = "APPROVED"
    touch(a)
    return success(advance_view(a))


@bp.route("/advances/<aid>/pay", methods=["POST"], strict_slashes=False)
def pay_advance(aid):
    uid, role = auth_context()
    require_roles(role, ["FinanceManager"])
    a = get_or_404("advances", aid, "advance")
    if a["status"] != "APPROVED":
        raise ApiError(ERR_INVALID_STATE_TRANSITION, 409,
                       "pay requires status APPROVED")
    a["status"] = "PAID"
    a["paid_at"] = db.clock_now()
    a["outstanding_cents"] = a["amount_cents"]
    touch(a)
    writer = STORE["writers"][a["writer_id"]]
    recompute_writer_rollups(writer)
    return success(advance_view(a))


@bp.route("/advances/<aid>/cancel", methods=["POST"], strict_slashes=False)
def cancel_advance(aid):
    uid, role = auth_context()
    require_roles(role, ["FinanceManager"])
    a = get_or_404("advances", aid, "advance")
    if a["status"] not in ("DRAFT", "APPROVED"):
        raise ApiError(ERR_INVALID_STATE_TRANSITION, 409,
                       "cancel requires status DRAFT or APPROVED")
    a["status"] = "CANCELLED"
    touch(a)
    return success(advance_view(a))
