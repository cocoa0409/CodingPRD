"""Pen assignment endpoints."""
from flask import Blueprint

import store
from auth import authenticate, authorize
from errors import ERR_PEN_NOT_FOUND, ERR_LOT_NOT_FOUND, ERR_ASSIGNMENT_NOT_FOUND, \
    ERR_INVALID_REQUEST, ERR_INVALID_DATE_RANGE, ERR_OVER_ASSIGNMENT, \
    ERR_COMMINGLE_RULE_VIOLATION, ERR_PEN_CAPACITY_EXCEEDED, raise_err
from serializers import pen_assignment_out
from services import pen_service, lot_service
from util import body_json, get_or_404, new_record, bump, req_str, req_int, \
    req_date, success_object

bp = Blueprint("assignments", __name__)


@bp.route("/feedlot/assignments", methods=["POST"])
def create_assignment():
    _, role = authenticate()
    authorize(role, ["FeedyardManager"])
    body = body_json()

    pen_id = req_str(body, "pen_id")
    lot_id = req_str(body, "lot_id")
    head_count = req_int(body, "head_count")
    start_date = req_date(body, "start_date")

    if head_count <= 0:
        raise_err(ERR_INVALID_REQUEST, "head_count must be > 0")

    # Validate resources exist
    pen = store.pens.get(pen_id)
    if pen is None:
        raise_err(ERR_PEN_NOT_FOUND, "Pen not found: %s" % pen_id)
    lot = store.lots.get(lot_id)
    if lot is None:
        raise_err(ERR_LOT_NOT_FOUND, "Lot not found: %s" % lot_id)

    # State checks
    lot_service.check_lot_open(lot)
    pen_service.check_pen_not_maintenance(pen)

    # Validate start_date >= lot.arrival_date
    if start_date < lot["arrival_date"]:
        raise_err(ERR_INVALID_DATE_RANGE,
                  "start_date must be >= lot.arrival_date")

    # Check commingling rules if pen already has lots
    active_assignments = [
        pa for pa in store.pen_assignments.values()
        if pa["pen_id"] == pen_id and pa["status"] == "ACTIVE"
    ]
    if active_assignments:
        existing_lots = [store.lots.get(pa["lot_id"]) for pa in active_assignments]
        existing_lots = [l for l in existing_lots if l is not None]

        for existing_lot in existing_lots:
            # Same sex_class
            if existing_lot["sex_class"] != lot["sex_class"]:
                raise_err(ERR_COMMINGLE_RULE_VIOLATION,
                          "Lots differ in sex_class")
            # Both commingle_allowed
            if not lot["commingle_allowed"] or not existing_lot["commingle_allowed"]:
                raise_err(ERR_COMMINGLE_RULE_VIOLATION,
                          "Both lots must have commingle_allowed=true")
            # Same active ration
            new_lot_rations = set(
                ra["ration_id"] for ra in store.ration_assignments.values()
                if ra["lot_id"] == lot["id"] and ra["status"] == "ACTIVE"
            )
            existing_lot_rations = set(
                ra["ration_id"] for ra in store.ration_assignments.values()
                if ra["lot_id"] == existing_lot["id"] and ra["status"] == "ACTIVE"
            )
            if new_lot_rations != existing_lot_rations:
                raise_err(ERR_COMMINGLE_RULE_VIOLATION,
                          "Lots must share the same active ration")

    # Check pen capacity over overlapping days
    # For simplicity, check if adding this assignment would exceed capacity
    # at any point. Since we don't track daily capacity precisely, we check
    # the maximum possible overlap.
    max_overlap = head_count + sum(pa["head_count"] for pa in active_assignments)
    if max_overlap > pen["capacity_head"]:
        # More precise check: find actual overlap days
        # For now, conservative check
        raise_err(ERR_PEN_CAPACITY_EXCEEDED,
                  "Adding %d head would exceed pen capacity %d"
                  % (head_count, pen["capacity_head"]))

    # Check lot over-assignment
    lot_active_head = sum(
        pa["head_count"] for pa in store.pen_assignments.values()
        if pa["lot_id"] == lot_id and pa["status"] == "ACTIVE"
    )
    if lot_active_head + head_count > lot["head_count_current"]:
        raise_err(ERR_OVER_ASSIGNMENT,
                  "Lot's total assigned head (%d) plus new head (%d) exceeds head_count_current (%d)"
                  % (lot_active_head, head_count, lot["head_count_current"]))

    rec = new_record()
    rec.update({
        "pen_id": pen_id,
        "lot_id": lot_id,
        "head_count": head_count,
        "start_date": start_date,
        "end_date": None,
        "status": "ACTIVE",
    })
    store.pen_assignments[rec["id"]] = rec

    # Update pen occupancy
    pen_service.recompute_pen_occupancy(pen)

    return success_object(pen_assignment_out(rec), 201)


@bp.route("/feedlot/assignments/<assignment_id>/end", methods=["POST"])
def end_assignment(assignment_id):
    _, role = authenticate()
    authorize(role, ["FeedyardManager"])
    body = body_json()
    end_date = req_date(body, "end_date")

    rec = get_or_404(store.pen_assignments, assignment_id,
                     ERR_ASSIGNMENT_NOT_FOUND, "PenAssignment")

    if rec["status"] != "ACTIVE":
        from errors import ERR_ASSIGNMENT_ALREADY_ENDED
        raise_err(ERR_ASSIGNMENT_ALREADY_ENDED,
                  "Assignment %s is not ACTIVE (status=%s)" % (assignment_id, rec["status"]))

    if end_date < rec["start_date"]:
        raise_err(ERR_INVALID_DATE_RANGE,
                  "end_date must be >= start_date")

    rec["status"] = "ENDED"
    rec["end_date"] = end_date
    bump(rec)

    # Recompute pen occupancy
    pen = store.pens.get(rec["pen_id"])
    if pen:
        pen_service.recompute_pen_occupancy(pen)

    return success_object(pen_assignment_out(rec))
