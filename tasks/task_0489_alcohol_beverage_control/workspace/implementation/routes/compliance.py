"""Three-tier compliance reports: submit (runs excise_assessment) + fetch."""
import re

from flask import Blueprint

import errors
from auth import require_auth, ALL_READERS
from db import db, new_id, common_fields
from helpers import body, out, get_or_404
import validate
from calculations import excise_due
from response import ok, created

bp = Blueprint("compliance", __name__)

TIERS = {"SUPPLIER", "WHOLESALER", "RETAILER"}
PERIOD_PATTERN = r"^[0-9]{4}-Q[1-4]$"


@bp.route("/compliance-reports", methods=["POST"])
def create_compliance_report():
    require_auth(["Applicant"])
    data = body()
    license_id = validate.require_str(data, "license_id")
    if license_id not in db.licenses:
        raise errors.err(errors.ERR_NOT_FOUND, "License not found")
    tier = validate.require_enum(data, "tier", TIERS)
    period_code = validate.require_str(data, "period_code")
    if not re.match(PERIOD_PATTERN, period_code):
        raise errors.err(errors.ERR_INVALID_REQUEST, "Invalid period_code")
    gross_sales_cents = validate.require_int(data, "gross_sales_cents", minimum=0)

    excise = excise_due(gross_sales_cents, tier)
    ent = {
        "id": new_id(), "license_id": license_id, "tier": tier,
        "period_code": period_code, "gross_sales_cents": gross_sales_cents,
        "excise_due_cents": excise,
    }
    ent.update(common_fields())
    db.compliance_reports[ent["id"]] = ent
    return created(out(ent))


@bp.route("/compliance-reports/<id>", methods=["GET"])
def get_compliance_report(id):
    require_auth(ALL_READERS)
    ent = get_or_404(db.compliance_reports, id)
    return ok(out(ent))
