"""PilotCell endpoints: pilot plant cell registration and read."""
from flask import Blueprint

from db import STORE
from errors import err, ERR_INVALID_REQUEST, ERR_PILOT_CELL_NOT_FOUND
from middleware import require_roles
from response import success
from services.core import find_or_404, new_record, serialize
from util import as_int, as_str, body_json, req

bp = Blueprint("pilot_cells", __name__)


@bp.post("/copack/pilot-cells")
def create_pilot_cell():
    require_roles("OpsAdmin")
    body = body_json()
    cell_name = as_str(req(body, "cell_name"), "cell_name")
    max_batch_units = as_int(req(body, "max_batch_units"), "max_batch_units")
    if max_batch_units < 1:
        raise err(ERR_INVALID_REQUEST, 400, "max_batch_units must be >= 1")
    rec = new_record({
        "cell_name": cell_name,
        "max_batch_units": max_batch_units,
    })
    STORE.pilot_cells[rec["id"]] = rec
    return success(serialize(rec), 201)


@bp.get("/copack/pilot-cells/<pid>")
def get_pilot_cell(pid):
    require_roles("OpsAdmin", "QAReviewer")
    rec = find_or_404(STORE.pilot_cells, pid, ERR_PILOT_CELL_NOT_FOUND, "pilot cell")
    return success(serialize(rec))
