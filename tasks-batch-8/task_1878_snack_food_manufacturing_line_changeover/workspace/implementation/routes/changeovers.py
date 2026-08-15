from flask import Blueprint, request

from auth import require, ALL_ROLES
from domain import dump_changeover, get_changeover, get_line, get_product
from errors import ApiError
from store import STORE, touch, sort_key
from util import body, ok, paginate, req_enum, iso

from routes.runs import _create_changeover

bp = Blueprint("changeovers", __name__)


@bp.post("/snack-mfg/changeovers")
def create_changeover():
    require(["PlantManager"])
    data = body()
    # tier 3: body FK existence (line_id before to_product_id)
    line_id = data.get("line_id")
    to_product_id = data.get("to_product_id")
    line = get_line(STORE, line_id) if isinstance(line_id, str) else None
    product = get_product(STORE, to_product_id) if isinstance(to_product_id, str) else None
    if line is None:
        if not isinstance(line_id, str) or line_id == "":
            raise ApiError("ERR_VALIDATION", 400, "missing or invalid field: line_id")
        raise ApiError("ERR_LINE_NOT_FOUND", 404, "line not found")
    if product is None:
        if not isinstance(to_product_id, str) or to_product_id == "":
            raise ApiError("ERR_VALIDATION", 400, "missing or invalid field: to_product_id")
        raise ApiError("ERR_PRODUCT_NOT_FOUND", 404, "product not found")
    ch = _create_changeover(STORE, line, product)
    return ok(STORE, dump_changeover(ch), status=201)


@bp.get("/snack-mfg/changeovers/<cid>")
def get_changeover_ep(cid):
    require(ALL_ROLES)
    ch = get_changeover(STORE, cid)
    return ok(STORE, dump_changeover(ch))


@bp.get("/snack-mfg/changeovers")
def list_changeovers():
    require(ALL_ROLES)
    items = list(STORE.changeovers.values())
    line_id = request.args.get("line_id")
    to_product_id = request.args.get("to_product_id")
    status = request.args.get("status")
    if line_id is not None:
        items = [c for c in items if c["line_id"] == line_id]
    if to_product_id is not None:
        items = [c for c in items if c["to_product_id"] == to_product_id]
    if status is not None:
        items = [c for c in items if c["status"] == status]
    items.sort(key=sort_key)
    page, meta = paginate([dump_changeover(c) for c in items])
    return ok(STORE, page, response_type="array", pagination=meta)


def _terminal_guard(ch):
    if ch["status"] in ("APPLIED", "CANCELLED"):
        raise ApiError("ERR_ALREADY_TERMINAL", 409, "changeover is in a terminal state")


@bp.post("/snack-mfg/changeovers/<cid>/begin-cleaning")
def begin_cleaning(cid):
    uid, _ = require(["LineOperator"])
    ch = get_changeover(STORE, cid)
    _terminal_guard(ch)
    if ch["status"] != "REQUIRED":
        raise ApiError("ERR_INVALID_STATE", 409, "changeover is not REQUIRED")
    if ch["required_level"] == "NONE":
        raise ApiError("ERR_INVALID_STATE", 409, "a NONE changeover never requires cleaning")
    ch["status"] = "CLEANING"
    ch["cleaned_by_user_id"] = uid
    ch["swab_result"] = None
    touch(STORE, ch)
    return ok(STORE, dump_changeover(ch))


@bp.post("/snack-mfg/changeovers/<cid>/record-swab")
def record_swab(cid):
    uid, _ = require(["QualityTechnician"])
    ch = get_changeover(STORE, cid)
    data = body()
    result = req_enum(data, "result", {"PASS", "FAIL"})
    _terminal_guard(ch)
    if ch["status"] != "CLEANING":
        raise ApiError("ERR_INVALID_STATE", 409, "changeover is not CLEANING")
    ch["swab_attempts"] += 1
    if result == "PASS":
        ch["status"] = "SWAB_PENDING"
        ch["swab_result"] = "PASS"
    else:
        ch["status"] = "CLEANING"
        ch["swab_result"] = None
    touch(STORE, ch)
    return ok(STORE, dump_changeover(ch))


@bp.post("/snack-mfg/changeovers/<cid>/validate")
def validate_changeover(cid):
    uid, _ = require(["QualityTechnician"])
    ch = get_changeover(STORE, cid)
    _terminal_guard(ch)
    if ch["status"] != "SWAB_PENDING":
        raise ApiError("ERR_INVALID_STATE", 409, "changeover is not SWAB_PENDING")
    if ch["swab_result"] != "PASS":
        raise ApiError("ERR_INVALID_STATE", 409, "no passing swab recorded")
    if ch["cleaned_by_user_id"] is not None and uid == ch["cleaned_by_user_id"]:
        raise ApiError("ERR_SOD_VIOLATION", 403, "validator must differ from cleaner")
    ch["status"] = "VALIDATED"
    ch["validated_by_user_id"] = uid
    ch["validated_at"] = iso(STORE.clock)
    ch["_validated_dt"] = STORE.clock
    touch(STORE, ch)
    return ok(STORE, dump_changeover(ch))
