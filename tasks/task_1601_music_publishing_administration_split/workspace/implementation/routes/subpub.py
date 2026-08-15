from flask import Blueprint, request

from db import STORE
from errors import (
    ApiError,
    ERR_COVERAGE_OVERLAP,
    ERR_INVALID_DATE_RANGE,
    ERR_INVALID_STATE_TRANSITION,
    ERR_SUB_PUBLISHER_NOT_ACTIVE,
    ERR_VALIDATION,
)
from middleware import ALL_ROLES, auth_context, require_roles
from response import success
from serializers import agreement_view, sub_publisher_view
from services import agreement_status, get_or_404, new_record, sorted_all, touch
from validators import (
    body_json, paginate, pagination_params, req_dt, req_int, req_str, req_str_list,
)

bp = Blueprint("subpub", __name__)

INCOME_TYPES = ["PERFORMANCE", "MECHANICAL", "SYNC", "PRINT", "OTHER"]


# ---------------------------------------------------------------------------
# sub-publishers
# ---------------------------------------------------------------------------

@bp.route("/sub-publishers", methods=["POST"], strict_slashes=False)
def create_sub_publisher():
    uid, role = auth_context()
    require_roles(role, ["PublisherAdmin"])
    body = body_json()
    name = req_str(body, "name")
    home = req_str(body, "home_territory_code")
    sp = new_record()
    sp.update({"name": name, "home_territory_code": home, "status": "ACTIVE"})
    STORE["sub_publishers"][sp["id"]] = sp
    return success(sub_publisher_view(sp), status=201)


@bp.route("/sub-publishers/<sid>", methods=["GET"], strict_slashes=False)
def get_sub_publisher(sid):
    uid, role = auth_context()
    require_roles(role, ALL_ROLES)
    sp = get_or_404("sub_publishers", sid, "sub-publisher")
    return success(sub_publisher_view(sp))


@bp.route("/sub-publishers/<sid>/suspend", methods=["POST"], strict_slashes=False)
def suspend_sub_publisher(sid):
    uid, role = auth_context()
    require_roles(role, ["PublisherAdmin"])
    sp = get_or_404("sub_publishers", sid, "sub-publisher")
    if sp["status"] != "ACTIVE":
        raise ApiError(ERR_INVALID_STATE_TRANSITION, 409,
                       "only an ACTIVE sub-publisher can be suspended")
    sp["status"] = "SUSPENDED"
    touch(sp)
    return success(sub_publisher_view(sp))


@bp.route("/sub-publishers/<sid>/reactivate", methods=["POST"], strict_slashes=False)
def reactivate_sub_publisher(sid):
    uid, role = auth_context()
    require_roles(role, ["PublisherAdmin"])
    sp = get_or_404("sub_publishers", sid, "sub-publisher")
    if sp["status"] != "SUSPENDED":
        raise ApiError(ERR_INVALID_STATE_TRANSITION, 409,
                       "only a SUSPENDED sub-publisher can be reactivated")
    sp["status"] = "ACTIVE"
    touch(sp)
    return success(sub_publisher_view(sp))


# ---------------------------------------------------------------------------
# sub-publishing agreements
# ---------------------------------------------------------------------------

@bp.route("/sub-publishing-agreements", methods=["POST"], strict_slashes=False)
def create_agreement():
    uid, role = auth_context()
    require_roles(role, ["PublisherAdmin"])
    body = body_json()
    sub_publisher_id = body.get("sub_publisher_id")
    if not isinstance(sub_publisher_id, str) or not sub_publisher_id:
        raise ApiError(ERR_VALIDATION, 422, "sub_publisher_id is required")
    get_or_404("sub_publishers", sub_publisher_id, "sub-publisher")
    territory_codes = req_str_list(body, "territory_codes", non_empty=True)
    income_types = req_str_list(body, "income_types", non_empty=True,
                                allowed=INCOME_TYPES)
    retention_bp = req_int(body, "retention_bp", lo=1, hi=5000)
    effective_from = req_dt(body, "effective_from")
    effective_to = req_dt(body, "effective_to")
    if effective_from >= effective_to:
        raise ApiError(ERR_INVALID_DATE_RANGE, 422,
                       "effective_from must be strictly before effective_to")
    ag = new_record()
    ag.update({
        "sub_publisher_id": sub_publisher_id,
        "territory_codes": list(territory_codes),
        "income_types": list(income_types),
        "retention_bp": retention_bp,
        "effective_from": effective_from,
        "effective_to": effective_to,
        "status": "DRAFT",
    })
    STORE["sub_publishing_agreements"][ag["id"]] = ag
    return success(agreement_view(ag), status=201)


@bp.route("/sub-publishing-agreements", methods=["GET"], strict_slashes=False)
def list_agreements():
    uid, role = auth_context()
    require_roles(role, ALL_ROLES)
    limit, offset = pagination_params()
    items = sorted_all("sub_publishing_agreements")
    sub_publisher_id = request.args.get("sub_publisher_id")
    status = request.args.get("status")
    if sub_publisher_id is not None:
        items = [a for a in items if a["sub_publisher_id"] == sub_publisher_id]
    if status is not None:
        items = [a for a in items if agreement_status(a) == status]
    page, meta = paginate(items, limit, offset)
    return success([agreement_view(a) for a in page],
                   response_type="array", pagination=meta)


@bp.route("/sub-publishing-agreements/<aid>", methods=["GET"], strict_slashes=False)
def get_agreement(aid):
    uid, role = auth_context()
    require_roles(role, ALL_ROLES)
    ag = get_or_404("sub_publishing_agreements", aid, "sub-publishing agreement")
    return success(agreement_view(ag))


@bp.route("/sub-publishing-agreements/<aid>/activate", methods=["POST"], strict_slashes=False)
def activate_agreement(aid):
    uid, role = auth_context()
    require_roles(role, ["PublisherAdmin"])
    ag = get_or_404("sub_publishing_agreements", aid, "sub-publishing agreement")
    if ag["status"] != "DRAFT":
        raise ApiError(ERR_INVALID_STATE_TRANSITION, 409,
                       "activate requires status DRAFT")
    sp = STORE["sub_publishers"][ag["sub_publisher_id"]]
    if sp["status"] != "ACTIVE":
        raise ApiError(ERR_SUB_PUBLISHER_NOT_ACTIVE, 409,
                       "the referenced sub-publisher is not ACTIVE")
    for other in STORE["sub_publishing_agreements"].values():
        if other["id"] == ag["id"]:
            continue
        if agreement_status(other) != "ACTIVE":
            continue
        if not set(other["territory_codes"]) & set(ag["territory_codes"]):
            continue
        if not set(other["income_types"]) & set(ag["income_types"]):
            continue
        # half-open window overlap; touching intervals do not overlap
        if other["effective_from"] < ag["effective_to"] and \
                ag["effective_from"] < other["effective_to"]:
            raise ApiError(ERR_COVERAGE_OVERLAP, 409,
                           "coverage overlaps another ACTIVE agreement")
    ag["status"] = "ACTIVE"
    touch(ag)
    return success(agreement_view(ag))


@bp.route("/sub-publishing-agreements/<aid>/terminate", methods=["POST"], strict_slashes=False)
def terminate_agreement(aid):
    uid, role = auth_context()
    require_roles(role, ["PublisherAdmin"])
    ag = get_or_404("sub_publishing_agreements", aid, "sub-publishing agreement")
    if agreement_status(ag) != "ACTIVE":
        raise ApiError(ERR_INVALID_STATE_TRANSITION, 409,
                       "terminate requires status ACTIVE")
    ag["status"] = "TERMINATED"
    touch(ag)
    return success(agreement_view(ag))
