from flask import Blueprint, request

from core import (AGE_BANDS, ERR_INVALID_REQUEST, ApiError, body, db,
                  list_response, new_resource, ok, req_enum, req_int, req_str,
                  require_roles)
from logic import cell_touch
from serializers import ser_cell

bp = Blueprint("cells", __name__)


def get_cell_or_404(cell_id):
    cell = db.cells.get(cell_id)
    if cell is None:
        raise ApiError("ERR_PANEL_CELL_NOT_FOUND", 404, "Panel cell not found")
    return cell


@bp.post("/feedback-panel/panel-cells")
@require_roles("PanelManager")
def create_cell():
    data = body()
    age_band = req_enum(data, "age_band", AGE_BANDS)
    district = req_str(data, "district")
    tenure_bucket = req_enum(data, "tenure_bucket", ("RENTER", "OWNER"))
    target_size = req_int(data, "target_size", min_value=0)
    for c in db.cells.values():
        if (c["age_band"] == age_band and c["district"] == district
                and c["tenure_bucket"] == tenure_bucket):
            raise ApiError(ERR_INVALID_REQUEST, 400,
                           "a cell already exists for this demographic triple")
    cell = new_resource()
    cell.update({
        "age_band": age_band,
        "district": district,
        "tenure_bucket": tenure_bucket,
        "target_size": target_size,
        "reserved_count": 0,
        "active_count": 0,
        "status": "SATURATED" if target_size == 0 else "OPEN",
    })
    db.cells[cell["id"]] = cell
    return ok(ser_cell(cell), 201)


@bp.get("/feedback-panel/panel-cells")
@require_roles("PanelManager", "DataAnalyst")
def list_cells():
    items = list(db.cells.values())
    status = request.args.get("status")
    if status is not None:
        items = [c for c in items if c["status"] == status]
    return list_response(items, ser_cell)


@bp.get("/feedback-panel/panel-cells/<cell_id>")
@require_roles("PanelManager", "DataAnalyst")
def get_cell(cell_id):
    return ok(ser_cell(get_cell_or_404(cell_id)))


@bp.post("/feedback-panel/panel-cells/<cell_id>/targets")
@require_roles("PanelManager")
def adjust_target(cell_id):
    cell = get_cell_or_404(cell_id)
    data = body()
    target_size = req_int(data, "target_size", min_value=0)
    expected = req_int(data, "expected_cell_version")
    if expected != cell["version"]:
        raise ApiError("ERR_STALE_CELL_VERSION", 412,
                       "expected_cell_version does not match the cell's current version")
    cell["target_size"] = target_size
    cell_touch(cell)
    return ok(ser_cell(cell))
