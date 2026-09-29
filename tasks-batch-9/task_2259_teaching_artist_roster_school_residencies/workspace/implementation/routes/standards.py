"""The state arts standards catalog."""
from flask import Blueprint, request

import db
import middleware as mw
import response
from enums import DISCIPLINES, GRADE_BANDS, STRANDS
from errors import ApiError
from services import derive
from validators import Payload

bp = Blueprint("standards", __name__)


def standard_by_code(code):
    for row in db.ordered(list(db.arts_standards.values())):
        if row["code"] == code:
            return row
    return None


def resolve_codes(codes):
    """Resolve a standard_codes array left to right (PRD 2.8)."""
    resolved = []
    for code in codes:
        row = standard_by_code(code)
        if row is None:
            raise ApiError("ERR_UNKNOWN_STANDARD_CODE",
                           "%s does not match any arts standard" % code)
        resolved.append(row)
    return resolved


@bp.post("/arts-standards")
def create_standard():
    mw.auth("ProgramDirector", "CurriculumSpecialist")
    body = Payload(request.get_json(silent=True))
    code = body.string("code", required=True, min_len=3, max_len=24)
    discipline = body.enum("discipline", DISCIPLINES, required=True)
    grade_band = body.enum("grade_band", GRADE_BANDS, required=True)
    strand = body.enum("strand", STRANDS, required=True)
    description = body.string("description", required=True)
    if standard_by_code(code) is not None:
        raise ApiError("ERR_DUPLICATE_STANDARD_CODE", "standard code %s already exists" % code)

    row = db.base_row()
    row.update({
        "code": code,
        "discipline": discipline,
        "grade_band": grade_band,
        "strand": strand,
        "description": description,
    })
    db.arts_standards[row["id"]] = row
    return response.ok(derive.standard_view(row), 201)


@bp.get("/arts-standards")
def list_standards():
    mw.auth()
    limit, offset = mw.pagination()
    discipline = mw.q_enum("discipline", DISCIPLINES)
    grade_band = mw.q_enum("grade_band", GRADE_BANDS)
    strand = mw.q_enum("strand", STRANDS)
    rows = db.ordered(list(db.arts_standards.values()))
    if discipline:
        rows = [r for r in rows if r["discipline"] == discipline]
    if grade_band:
        rows = [r for r in rows if r["grade_band"] == grade_band]
    if strand:
        rows = [r for r in rows if r["strand"] == strand]
    page, total = mw.page(rows, limit, offset)
    return response.ok_list([derive.standard_view(r) for r in page], limit, offset, total)
