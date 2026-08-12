"""Coder endpoints (PRD §3.5)."""
from flask import Blueprint

from db import stamp_new, store, touch
from errors import ERR_CODER_NOT_FOUND, ERR_INVALID_REQUEST, fail
from middleware import ALL_ROLES, require_roles
from response import ok_obj
from services.core import CREDENTIALS, ser_coder
from validators import body, has, opt_enum, req_enum, req_str

bp = Blueprint("coders", __name__)

CODER_STATUSES = ("ACTIVE", "INACTIVE")


def get_coder_or_404(coder_id):
    c = store.coders.get(coder_id)
    if c is None:
        fail(404, ERR_CODER_NOT_FOUND, f"Coder {coder_id} does not exist")
    return c


@bp.route("/coders", methods=["POST"])
def create_coder():
    require_roles("CodingManager")
    b = body()
    employee_no = req_str(b, "employee_no")
    full_name = req_str(b, "full_name")
    credential = req_enum(b, "credential", CREDENTIALS)
    if any(c["employee_no"] == employee_no for c in store.coders.values()):
        fail(400, ERR_INVALID_REQUEST, "employee_no must be unique")
    coder = stamp_new({
        "employee_no": employee_no,
        "full_name": full_name,
        "credential": credential,
        "status": "ACTIVE",
        "workload_units": 0,
        "accepted_count": 0,
        "accepted_weighted_units": 0,
        "productivity_units_per_day": 0,
        "accuracy_running": None,
        "credential_review_required": False,
    })
    store.coders[coder["id"]] = coder
    return ok_obj(ser_coder(coder), 201)


@bp.route("/coders/<id>", methods=["GET"])
def get_coder(id):
    require_roles(*ALL_ROLES)
    return ok_obj(ser_coder(get_coder_or_404(id)), 200)


@bp.route("/coders/<id>", methods=["PATCH"])
def patch_coder(id):
    require_roles("CodingManager")
    coder = get_coder_or_404(id)
    b = body()
    new_status = opt_enum(b, "status", CODER_STATUSES) if has(b, "status") else None
    new_cred = opt_enum(b, "credential", CREDENTIALS) if has(b, "credential") else None
    changed = False
    if new_status is not None and new_status != coder["status"]:
        coder["status"] = new_status
        changed = True
    if new_cred is not None and new_cred != coder["credential"]:
        coder["credential"] = new_cred
        changed = True
    if changed:
        touch(coder)
    return ok_obj(ser_coder(coder), 200)
