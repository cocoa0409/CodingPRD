from flask import Blueprint

import db
import errors
import middleware as mw
from response import success
from services import covenants
from services.common import parse_dt, stamp_new, touch
from services.pagination import get_pagination, paginate
from services.serialize import prop as ser_prop
from services.validate import body_json, require_fields, req_enum, req_int, req_str

bp = Blueprint("properties", __name__)

PROPERTY_TYPES = ("OFFICE", "RETAIL", "INDUSTRIAL", "MULTIFAMILY", "HOTEL")


@bp.post("/loans/<lid>/properties")
def create_property(lid):
    actor = mw.authenticate()
    mw.authorize(actor, ["MasterServicer"])
    loan = db.loans.get(lid)
    if loan is None:
        raise errors.not_found("Loan not found")
    data = body_json()
    require_fields(data, ["address", "property_type", "appraised_value_cents", "appraisal_date"])
    address = req_str(data, "address")
    ptype = req_enum(data, "property_type", PROPERTY_TYPES)
    value = req_int(data, "appraised_value_cents", gt=0)
    adate = parse_dt(data.get("appraisal_date"), "appraisal_date")
    p = {
        "id": db.new_id(),
        "loan_id": loan["id"],
        "address": address,
        "property_type": ptype,
        "appraised_value_cents": value,
        "appraisal_date": db.fmt_ts(adate),
        "appraisal_date_dt": adate,
        "appraised_by_user_id": None,
    }
    stamp_new(p)
    db.properties[p["id"]] = p
    return success(ser_prop(p), status=201)


@bp.get("/loans/<lid>/properties")
def list_properties(lid):
    actor = mw.authenticate()
    mw.authorize(actor, ["MasterServicer", "SpecialServicer", "Borrower"])
    loan = db.loans.get(lid)
    if not mw.read_scope_allows(actor, "loan", loan):
        raise errors.not_found("Loan not found")
    limit, offset = get_pagination()
    items = [p for p in db.properties.values() if p["loan_id"] == lid]
    items.sort(key=lambda p: (p["created_at"], p["id"]))
    page, pg = paginate([ser_prop(p) for p in items], limit, offset)
    return success(page, pagination=pg, is_array=True)


@bp.get("/properties/<pid>")
def get_property(pid):
    actor = mw.authenticate()
    mw.authorize(actor, ["MasterServicer", "SpecialServicer", "Borrower"])
    p = db.properties.get(pid)
    if not mw.read_scope_allows(actor, "property", p):
        raise errors.not_found("Property not found")
    return success(ser_prop(p))


@bp.post("/properties/<pid>/appraise")
def appraise(pid):
    actor = mw.authenticate()
    mw.authorize(actor, ["MasterServicer"])
    p = db.properties.get(pid)
    if p is None:
        raise errors.not_found("Property not found")
    data = body_json()
    require_fields(data, ["appraised_value_cents", "appraisal_date"])
    value = req_int(data, "appraised_value_cents", gt=0)
    adate = parse_dt(data.get("appraisal_date"), "appraisal_date")
    p["appraised_value_cents"] = value
    p["appraisal_date"] = db.fmt_ts(adate)
    p["appraisal_date_dt"] = adate
    p["appraised_by_user_id"] = actor["user_id"]
    touch(p)
    loan = db.loans.get(p["loan_id"])
    covenants.run_ltv_assessment(loan)
    return success(ser_prop(p))
