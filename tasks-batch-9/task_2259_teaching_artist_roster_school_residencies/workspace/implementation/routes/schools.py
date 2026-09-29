"""School partners and their blackout calendars."""
from flask import Blueprint, request

import db
import middleware as mw
import response
from enums import BLACKOUT_TYPES
from errors import ApiError
from services import derive
from validators import Payload, bad

bp = Blueprint("schools", __name__)


def find_school(school_id):
    school = db.school_partners.get(school_id)
    if school is None:
        raise ApiError("ERR_SCHOOL_PARTNER_NOT_FOUND", "school partner %s not found" % school_id)
    return school


@bp.post("/school-partners")
def create_school():
    mw.auth("ProgramDirector")
    body = Payload(request.get_json(silent=True))
    row = db.base_row()
    row.update({
        "name": body.string("name", required=True, min_len=1, max_len=120),
        "district_name": body.string("district_name", required=True),
        "grade_span": body.string("grade_span", required=True),
        "concurrent_session_capacity": body.integer("concurrent_session_capacity",
                                                    required=True, minimum=1),
        "total_enrollment": body.integer("total_enrollment", required=True, minimum=1),
        "frl_pct": body.number("frl_pct", required=True, minimum=0, maximum=1, decimals=2),
        "ell_pct": body.number("ell_pct", required=True, minimum=0, maximum=1, decimals=2),
        "iep_pct": body.number("iep_pct", required=True, minimum=0, maximum=1, decimals=2),
    })
    db.school_partners[row["id"]] = row
    return response.ok(derive.school_view(row), 201)


@bp.get("/school-partners/<school_id>")
def read_school(school_id):
    mw.auth()
    school = find_school(school_id)
    return response.ok(derive.school_view(school))


@bp.post("/school-partners/<school_id>/calendar-blackouts")
def create_blackout(school_id):
    mw.auth("RosterCoordinator", "SchoolLiaison")
    school = find_school(school_id)
    body = Payload(request.get_json(silent=True))
    blackout_type = body.enum("blackout_type", BLACKOUT_TYPES, required=True)
    start_date = body.date("start_date", required=True)
    end_date = body.date("end_date", required=True)
    if end_date < start_date:
        bad("end_date must not be earlier than start_date")
    note = body.string("note", default=None, min_len=0)
    row = db.base_row(versioned=False)
    row.update({
        "school_partner_id": school["id"],
        "blackout_type": blackout_type,
        "start_date": start_date,
        "end_date": end_date,
        "note": note,
    })
    db.calendar_blackouts[row["id"]] = row
    return response.ok(derive.blackout_view(row), 201)


@bp.get("/school-partners/<school_id>/calendar-blackouts")
def list_blackouts(school_id):
    mw.auth()
    school = find_school(school_id)
    limit, offset = mw.pagination()
    rows = db.ordered([b for b in db.calendar_blackouts.values()
                       if b["school_partner_id"] == school["id"]])
    page, total = mw.page(rows, limit, offset)
    return response.ok_list([derive.blackout_view(r) for r in page], limit, offset, total)
