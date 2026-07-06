from flask import Blueprint

import errors
from errors import err
from db import db, base_fields, touch
from middleware import get_auth, require_role
from response import ok_object, ok_array
from validate import body, require_str, require_enum, require_positive_int, paginate
from routes.common import get_donor
import domain

bp = Blueprint("donors", __name__)

DONOR_TYPES = {"SPERM", "OOCYTE"}
BLOOD_TYPES = {"A_POS", "A_NEG", "B_POS", "B_NEG", "AB_POS", "AB_NEG", "O_POS", "O_NEG"}

READ_ROLES = {"ScreeningOfficer", "CatalogManager", "ComplianceOfficer", "Recipient", "LabTech", "BillingClerk"}


@bp.post("/donors")
def create_donor():
    _uid, role = get_auth()
    require_role(role, {"ScreeningOfficer"})
    data = body()
    display_code = require_str(data, "display_code")
    full_name = require_str(data, "full_name")
    donor_type = require_enum(data, "donor_type", DONOR_TYPES)
    blood_type = require_enum(data, "blood_type", BLOOD_TYPES)
    family_limit = require_positive_int(data, "family_limit")

    donor = base_fields(db)
    donor.update({
        "display_code": display_code,
        "full_name": full_name,
        "donor_type": donor_type,
        "blood_type": blood_type,
        "fda_eligible": False,
        "genetic_panel_clear": False,
        "family_limit": family_limit,
        "reported_family_count": 0,
        "status": "APPLICANT",
        "is_family_limit_reached": False,
    })
    db.donors[donor["id"]] = donor
    return ok_object(donor, 201)


@bp.get("/donors/<i>")
def get_one(i):
    _uid, role = get_auth()
    require_role(role, READ_ROLES)
    return ok_object(get_donor(i))


@bp.get("/donors")
def list_donors():
    _uid, role = get_auth()
    require_role(role, READ_ROLES)
    from flask import request
    items = list(db.donors.values())
    status_f = request.args.get("status")
    type_f = request.args.get("donor_type")
    blood_f = request.args.get("blood_type")
    if status_f is not None:
        items = [d for d in items if d["status"] == status_f]
    if type_f is not None:
        items = [d for d in items if d["donor_type"] == type_f]
    if blood_f is not None:
        items = [d for d in items if d["blood_type"] == blood_f]
    page, limit, offset, total = paginate(items)
    return ok_array(page, limit, offset, total)
