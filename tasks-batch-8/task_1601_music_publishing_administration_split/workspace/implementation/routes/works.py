from flask import Blueprint, request

import db
from db import STORE
from errors import ApiError, ERR_INVALID_STATE_TRANSITION, ERR_VALIDATION
from middleware import ALL_ROLES, auth_context, require_roles
from response import success
from serializers import work_view
from services import get_or_404, new_record, sorted_all, touch
from validators import body_json, opt_list, paginate, pagination_params, req_dt, req_str

bp = Blueprint("works", __name__)


@bp.route("/works", methods=["POST"], strict_slashes=False)
def create_work():
    uid, role = auth_context()
    require_roles(role, ["PublisherAdmin"])
    body = body_json()
    parent_id = body.get("parent_work_id")
    if parent_id is not None:
        if not isinstance(parent_id, str):
            raise ApiError(ERR_VALIDATION, 422,
                           "parent_work_id must be a string or null")
        get_or_404("works", parent_id, "parent work")
    title = req_str(body, "title")
    grant_date = req_dt(body, "grant_date")
    alternates = opt_list(body, "alternate_titles")
    if alternates is None:
        alternates = []
    for alt in alternates:
        if not isinstance(alt, str):
            raise ApiError(ERR_VALIDATION, 422,
                           "alternate_titles must contain only strings")
    w = new_record()
    w.update({
        "title": title,
        "alternate_titles": list(alternates),
        "parent_work_id": parent_id,
        "work_code": db.next_work_code(),
        "iswc": None,
        "grant_date": grant_date,
        "registration_status": "UNREGISTERED",
        "copyright_status": "UNFILED",
        "total_collected_cents": 0,
        "total_distributed_cents": 0,
    })
    STORE["works"][w["id"]] = w
    return success(work_view(w), status=201)


@bp.route("/works", methods=["GET"], strict_slashes=False)
def list_works():
    uid, role = auth_context()
    require_roles(role, ALL_ROLES)
    limit, offset = pagination_params()
    items = sorted_all("works")
    parent = request.args.get("parent_work_id")
    reg = request.args.get("registration_status")
    cop = request.args.get("copyright_status")
    if parent is not None:
        items = [w for w in items if w["parent_work_id"] == parent]
    if reg is not None:
        items = [w for w in items if w["registration_status"] == reg]
    if cop is not None:
        items = [w for w in items if w["copyright_status"] == cop]
    page, meta = paginate(items, limit, offset)
    return success([work_view(w) for w in page], response_type="array",
                   pagination=meta)


@bp.route("/works/<wid>", methods=["GET"], strict_slashes=False)
def get_work(wid):
    uid, role = auth_context()
    require_roles(role, ALL_ROLES)
    w = get_or_404("works", wid, "work")
    return success(work_view(w))


@bp.route("/works/<wid>/file-copyright", methods=["POST"], strict_slashes=False)
def file_copyright(wid):
    uid, role = auth_context()
    require_roles(role, ["CopyrightSpecialist"])
    w = get_or_404("works", wid, "work")
    body = body_json()
    req_str(body, "filing_ref")
    if w["copyright_status"] != "UNFILED":
        raise ApiError(ERR_INVALID_STATE_TRANSITION, 409,
                       "copyright filing requires copyright_status UNFILED")
    w["copyright_status"] = "FILED"
    touch(w)
    return success(work_view(w))


@bp.route("/works/<wid>/register-copyright", methods=["POST"], strict_slashes=False)
def register_copyright(wid):
    uid, role = auth_context()
    require_roles(role, ["CopyrightSpecialist"])
    w = get_or_404("works", wid, "work")
    body = body_json()
    req_str(body, "registration_number")
    if w["copyright_status"] != "FILED":
        raise ApiError(ERR_INVALID_STATE_TRANSITION, 409,
                       "copyright registration requires copyright_status FILED")
    w["copyright_status"] = "COPCO_REGISTERED"
    touch(w)
    return success(work_view(w))
