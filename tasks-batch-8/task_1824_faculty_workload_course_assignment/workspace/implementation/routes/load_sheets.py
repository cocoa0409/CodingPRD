"""LoadSheet endpoints (read-only; sheets are auto-created by the first
assignment or release-time grant for a term-and-faculty pair)."""

import db
from errors import ApiError, ERR_LOAD_SHEET_NOT_FOUND
from middleware import authenticate, ALL_ROLES
from response import success_obj, success_list
from routes import make_blueprint
from util import pagination_params, paginate, apply_filters

bp = make_blueprint("load_sheets")


@bp.get("/load-sheets")
def list_load_sheets():
    authenticate(ALL_ROLES)
    limit, offset = pagination_params()
    items = apply_filters(db.all_of("load_sheets"), ["term_id", "faculty_id"])
    page, total, has_more = paginate(items, limit, offset)
    return success_list([db.public(s) for s in page], limit, offset, total, has_more)


@bp.get("/load-sheets/<loadSheetId>")
def get_load_sheet(loadSheetId):
    authenticate(ALL_ROLES)
    sheet = db.get("load_sheets", loadSheetId)
    if sheet is None:
        raise ApiError(ERR_LOAD_SHEET_NOT_FOUND, 404, "load sheet not found")
    return success_obj(db.public(sheet), 200)
