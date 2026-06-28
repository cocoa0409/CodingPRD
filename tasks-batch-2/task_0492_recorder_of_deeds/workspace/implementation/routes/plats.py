"""PlatSurvey routes (PRD §3.6, §4). Lot-range reservation with overlap checks
on approve and re-checked at record."""
from flask import Blueprint, request

import errors
from auth import require_auth, SUBMITTER, EXAMINER, RECORDER, ALL_READERS
from db import db, new_id, common_fields, touch
from helpers import (body, require_fields, as_int, as_str, get_or_404, out,
                     out_list, paginate, sort_created)
from response import ok, created, listed

bp = Blueprint("plats", __name__)


def _ranges_overlap(s1, e1, s2, e2):
    """Two closed inclusive ranges overlap whenever each one's start is not
    greater than the other's end (PRD §3.6)."""
    return s1 <= e2 and s2 <= e1


def _overlaps_recorded(plat):
    """True if any already-RECORDED plat on the same office_id + subdivision_name
    + block_number has a closed inclusive lot range overlapping this plat's."""
    for other in db.plats.values():
        if other["id"] == plat["id"]:
            continue
        if other["status"] != "RECORDED":
            continue
        if (other["office_id"] == plat["office_id"]
                and other["subdivision_name"] == plat["subdivision_name"]
                and other["block_number"] == plat["block_number"]):
            if _ranges_overlap(plat["start_lot"], plat["end_lot"],
                               other["start_lot"], other["end_lot"]):
                return True
    return False


@bp.route("/plats", methods=["POST"])
def create_plat():
    require_auth([SUBMITTER])
    data = body()
    require_fields(data, ["submitter_id", "office_id", "subdivision_name",
                          "block_number", "start_lot", "end_lot"])
    submitter_id = as_str(data, "submitter_id")
    office_id = as_str(data, "office_id")
    subdivision_name = as_str(data, "subdivision_name")
    block_number = as_int(data, "block_number", minimum=0)
    start_lot = as_int(data, "start_lot", minimum=0)
    end_lot = as_int(data, "end_lot", minimum=0)

    # Existence (priority 3), left-to-right
    get_or_404(db.submitters, submitter_id)
    get_or_404(db.offices, office_id)

    pid = new_id()
    plat = {
        "id": pid,
        "submitter_id": submitter_id,
        "office_id": office_id,
        "subdivision_name": subdivision_name,
        "block_number": block_number,
        "start_lot": start_lot,
        "end_lot": end_lot,
        "status": "SUBMITTED",
        "plat_book": None,
        "plat_page": None,
    }
    plat.update(common_fields())
    db.plats[pid] = plat
    return created(out(plat))


@bp.route("/plats/<pid>", methods=["GET"])
def get_plat(pid):
    require_auth(ALL_READERS)
    plat = get_or_404(db.plats, pid)
    return ok(out(plat))


@bp.route("/plats", methods=["GET"])
def list_plats():
    require_auth(ALL_READERS)
    items = list(db.plats.values())
    submitter_id = request.args.get("submitter_id")
    office_id = request.args.get("office_id")
    subdivision_name = request.args.get("subdivision_name")
    status = request.args.get("status")
    if submitter_id is not None:
        items = [p for p in items if p["submitter_id"] == submitter_id]
    if office_id is not None:
        items = [p for p in items if p["office_id"] == office_id]
    if subdivision_name is not None:
        items = [p for p in items if p["subdivision_name"] == subdivision_name]
    if status is not None:
        items = [p for p in items if p["status"] == status]
    items = sort_created(items)
    window, limit, offset, total = paginate(items)
    return listed(out_list(window), limit, offset, total)


@bp.route("/plats/<pid>/approve", methods=["POST"])
def approve_plat(pid):
    require_auth([EXAMINER])
    plat = get_or_404(db.plats, pid)
    # State (priority 5)
    if plat["status"] != "SUBMITTED":
        raise errors.err(errors.ERR_INVALID_STATE, "Plat is not SUBMITTED")
    # Invalid lot range (priority 4 category, 422)
    if plat["end_lot"] < plat["start_lot"]:
        raise errors.err(errors.ERR_INVALID_LOT_RANGE, "end_lot < start_lot")
    # Temporal/overlap (priority 9)
    if _overlaps_recorded(plat):
        raise errors.err(errors.ERR_LOT_RANGE_OVERLAP, "Lot range overlaps a recorded plat")
    plat["status"] = "APPROVED"
    touch(plat)
    return ok(out(plat))


@bp.route("/plats/<pid>/reject", methods=["POST"])
def reject_plat(pid):
    require_auth([EXAMINER])
    plat = get_or_404(db.plats, pid)
    if plat["status"] != "SUBMITTED":
        raise errors.err(errors.ERR_INVALID_STATE, "Plat is not SUBMITTED")
    plat["status"] = "REJECTED"
    touch(plat)
    return ok(out(plat))


@bp.route("/plats/<pid>/record", methods=["POST"])
def record_plat(pid):
    require_auth([RECORDER])
    plat = get_or_404(db.plats, pid)
    if plat["status"] != "APPROVED":
        raise errors.err(errors.ERR_INVALID_STATE, "Plat is not APPROVED")
    # Re-check overlap at record time (priority 9)
    if _overlaps_recorded(plat):
        raise errors.err(errors.ERR_LOT_RANGE_OVERLAP, "Lot range overlaps a recorded plat")
    office = db.offices[plat["office_id"]]
    plat["plat_book"] = office["current_book"]
    plat["plat_page"] = office["current_page"]
    plat["status"] = "RECORDED"
    touch(plat)
    return ok(out(plat))
