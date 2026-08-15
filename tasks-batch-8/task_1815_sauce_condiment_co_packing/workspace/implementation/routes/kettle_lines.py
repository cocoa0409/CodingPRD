"""KettleLine endpoints: kettle/fill line registration and read."""
from flask import Blueprint

from db import STORE
from errors import err, ERR_INVALID_REQUEST, ERR_KETTLE_LINE_NOT_FOUND
from middleware import require_roles
from response import success
from services.core import find_or_404, new_record, serialize
from util import as_int, as_str, body_json, req

bp = Blueprint("kettle_lines", __name__)


@bp.post("/copack/kettle-lines")
def create_kettle_line():
    require_roles("OpsAdmin")
    body = body_json()
    line_name = as_str(req(body, "line_name"), "line_name")
    capacity_units = as_int(req(body, "capacity_units"), "capacity_units")
    if capacity_units < 1:
        raise err(ERR_INVALID_REQUEST, 400, "capacity_units must be >= 1")
    rec = new_record({
        "line_name": line_name,
        "capacity_units": capacity_units,
    })
    STORE.kettle_lines[rec["id"]] = rec
    return success(serialize(rec), 201)


@bp.get("/copack/kettle-lines/<kid>")
def get_kettle_line(kid):
    require_roles("OpsAdmin", "QAReviewer")
    rec = find_or_404(STORE.kettle_lines, kid, ERR_KETTLE_LINE_NOT_FOUND, "kettle line")
    return success(serialize(rec))
