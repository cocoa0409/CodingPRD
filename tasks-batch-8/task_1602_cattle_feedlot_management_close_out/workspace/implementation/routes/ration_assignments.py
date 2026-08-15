"""Ration assignment endpoints."""
from flask import Blueprint

import store
from auth import authenticate, authorize
from errors import ERR_LOT_NOT_FOUND, ERR_RATION_NOT_FOUND, ERR_INVALID_REQUEST, \
    ERR_INVALID_DATE_RANGE, ERR_STEP_UP_VIOLATION, ERR_RATION_WINDOW_OVERLAP, raise_err
from serializers import ration_assignment_out
from services import lot_service
from util import body_json, get_or_404, new_record, req_str, req_date, success_object

bp = Blueprint("ration_assignments", __name__)


@bp.route("/feedlot/ration-assignments", methods=["POST"])
def create_ration_assignment():
    _, role = authenticate()
    authorize(role, ["FeedManager"])
    body = body_json()

    lot_id = req_str(body, "lot_id")
    ration_id = req_str(body, "ration_id")
    start_date = req_date(body, "start_date")
    end_date = req_date(body, "end_date")

    # Validate resources exist
    lot = store.lots.get(lot_id)
    if lot is None:
        raise_err(ERR_LOT_NOT_FOUND, "Lot not found: %s" % lot_id)
    ration = store.rations.get(ration_id)
    if ration is None:
        raise_err(ERR_RATION_NOT_FOUND, "Ration not found: %s" % ration_id)

    # State check
    lot_service.check_lot_open(lot)

    # Validate date range
    if end_date <= start_date:
        raise_err(ERR_INVALID_DATE_RANGE,
                  "end_date must be strictly after start_date")

    # Step-up rule
    existing_ras = [
        ra for ra in store.ration_assignments.values()
        if ra["lot_id"] == lot_id
    ]
    existing_ras.sort(key=lambda ra: ra["created_at"])

    if not existing_ras:
        # First assignment must be step_level 1
        if ration["step_level"] != 1:
            raise_err(ERR_STEP_UP_VIOLATION,
                      "First ration assignment must be step_level 1")
    else:
        # Subsequent must be latest step_level + 1
        latest_ra = existing_ras[-1]
        latest_ration = store.rations.get(latest_ra["ration_id"])
        if latest_ration and ration["step_level"] != latest_ration["step_level"] + 1:
            raise_err(ERR_STEP_UP_VIOLATION,
                      "Ration step_level must be %d (latest + 1)"
                      % (latest_ration["step_level"] + 1))

    # Window overlap rule
    for ra in existing_ras:
        # Check overlap: [start, end) overlaps [ra.start, ra.end)
        if start_date < ra["end_date"] and end_date > ra["start_date"]:
            raise_err(ERR_RATION_WINDOW_OVERLAP,
                      "Ration window overlaps existing window [%s, %s)"
                      % (ra["start_date"].isoformat(), ra["end_date"].isoformat()))

    rec = new_record()
    rec.update({
        "lot_id": lot_id,
        "ration_id": ration_id,
        "start_date": start_date,
        "end_date": end_date,
        "status": "ACTIVE",
    })
    store.ration_assignments[rec["id"]] = rec
    return success_object(ration_assignment_out(rec), 201)
