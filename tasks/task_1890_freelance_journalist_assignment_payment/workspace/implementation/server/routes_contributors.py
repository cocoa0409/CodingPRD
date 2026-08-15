"""Contributor roster endpoints."""

from flask import request

from .auth import require, require_owner
from .blueprint import bp
from .cascade import terminate_contributor
from .envelope import ok_list, ok_obj
from .errors import ApiError, bad_request, invalid_state, not_found
from .serialize import ser_contributor
from .store import STORE, new_entity, touch
from .util import body, opt_bool, opt_str, paged, pagination_params, req_enum, sort_created

TAX_RESIDENCIES = ("DOMESTIC_US", "FOREIGN")


@bp.post("/freelance-desk/contributors")
def create_contributor():
    require(["DeskAdmin"])
    b = body()
    # Priority 14 (duplicate email) is evaluated before generic field shape (15).
    email_val = b.get("email")
    if isinstance(email_val, str) and email_val:
        for c in STORE.contributors.values():
            if c["email"].lower() == email_val.lower():
                raise ApiError("ERR_DUPLICATE_EMAIL", 409, "Email already on the roster")
    legal_name = opt_str(b, "legal_name")
    if legal_name is None or legal_name == "":
        bad_request("legal_name is required")
    if not isinstance(email_val, str) or not email_val:
        bad_request("email is required")
    tax_residency = req_enum(b, "tax_residency", TAX_RESIDENCIES)
    pen_name = opt_str(b, "pen_name", "")
    backup_flag = opt_bool(b, "backup_withholding_flag", False)

    e = new_entity()
    e.update({
        "legal_name": legal_name,
        "pen_name": pen_name,
        "email": email_val,
        "tax_residency": tax_residency,
        "status": "ACTIVE",
        "ytd_gross_cents": 0,
        "reportable_threshold_crossed": False,
        "backup_withholding_flag": backup_flag,
    })
    STORE.contributors[e["id"]] = e
    return ok_obj(ser_contributor(e), 201)


@bp.get("/freelance-desk/contributors")
def list_contributors():
    require(["DeskAdmin", "Editor", "FinanceUser"])
    items = list(STORE.contributors.values())
    status = request.args.get("status")
    if status:
        items = [c for c in items if c["status"] == status]
    tr = request.args.get("tax_residency")
    if tr:
        items = [c for c in items if c["tax_residency"] == tr]
    rtc = request.args.get("reportable_threshold_crossed")
    if rtc is not None:
        if rtc.lower() == "true":
            items = [c for c in items if c["reportable_threshold_crossed"]]
        elif rtc.lower() == "false":
            items = [c for c in items if not c["reportable_threshold_crossed"]]
    items = sort_created(items)
    limit, offset = pagination_params()
    page, total = paged(items, limit, offset)
    return ok_list([ser_contributor(c) for c in page], limit, offset, total)


def _get_contributor(cid):
    c = STORE.contributors.get(cid)
    if c is None:
        not_found("Contributor")
    return c


@bp.get("/freelance-desk/contributors/<cid>")
def get_contributor(cid):
    uid, role = require(["DeskAdmin", "Editor", "FinanceUser", "Contributor"])
    c = _get_contributor(cid)
    if role == "Contributor":
        require_owner(uid, c["id"])
    return ok_obj(ser_contributor(c))


@bp.post("/freelance-desk/contributors/<cid>/suspend")
def suspend_contributor(cid):
    require(["DeskAdmin"])
    c = _get_contributor(cid)
    if c["status"] != "ACTIVE":
        invalid_state("Only an ACTIVE contributor can be suspended")
    c["status"] = "SUSPENDED"
    touch(c)
    return ok_obj(ser_contributor(c))


@bp.post("/freelance-desk/contributors/<cid>/reinstate")
def reinstate_contributor(cid):
    require(["DeskAdmin"])
    c = _get_contributor(cid)
    if c["status"] != "SUSPENDED":
        invalid_state("Only a SUSPENDED contributor can be reinstated")
    c["status"] = "ACTIVE"
    touch(c)
    return ok_obj(ser_contributor(c))


@bp.post("/freelance-desk/contributors/<cid>/terminate")
def terminate_contributor_endpoint(cid):
    require(["DeskAdmin"])
    c = _get_contributor(cid)
    if c["status"] not in ("ACTIVE", "SUSPENDED"):
        invalid_state("Only an ACTIVE or SUSPENDED contributor can be terminated")
    terminate_contributor(c)
    return ok_obj(ser_contributor(c))
