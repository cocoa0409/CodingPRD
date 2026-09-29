"""Fired-lot reads and the quality hold."""

import response
import services as svc
from auth import ALL_ROLES, endpoint
from errors import ApiError
from routes import apply_filters
from store import db, touch
from validation import body, v_str

from flask import Blueprint

bp = Blueprint("fired_lots", __name__)


@bp.get("/fired-lots/<lid>")
@endpoint(ALL_ROLES)
def get_lot(lid):
    return response.entity(svc.lot_or_404(lid))


@bp.get("/fired-lots")
@endpoint(ALL_ROLES)
def list_lots():
    rows = apply_filters(
        db.fired_lots.values(),
        {
            "production_run_id": "production_run_id",
            "color_family": "color_family",
            "texture": "texture",
            "grade": "grade",
            "durability_grade": "durability_grade",
            "status": "status",
        },
    )
    return response.collection(rows)


@bp.get("/fired-lots/<lid>/blend-components")
@endpoint(ALL_ROLES)
def list_lot_components(lid):
    svc.lot_or_404(lid)
    rows = [c for c in db.blend_components.values() if c["fired_lot_id"] == lid]
    return response.collection(apply_filters(rows, {"status": "status"}))


@bp.post("/fired-lots/<lid>/quarantine")
@endpoint(["QualityManager"])
def quarantine_lot(lid):
    lot = svc.lot_or_404(lid)
    payload = body()
    reason = v_str(payload, "quarantine_reason")

    if lot["status"] not in ("AVAILABLE", "RESERVED"):
        raise ApiError(
            "ERR_FIRED_LOT_UNAVAILABLE",
            "Only an AVAILABLE or RESERVED fired lot can be quarantined.",
        )

    lot["status"] = "QUARANTINED"
    lot["quarantine_reason"] = reason
    touch(lot)
    return response.entity(lot)
