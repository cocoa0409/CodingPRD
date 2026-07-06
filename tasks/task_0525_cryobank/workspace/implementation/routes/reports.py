from flask import Blueprint, request

from db import db, base_fields
from middleware import get_auth, require_role
from response import ok_object, ok_array
from validate import body, require_str, require_enum, paginate
from routes.common import get_report, get_donor
from routes.specimens import _validate_dt

bp = Blueprint("reports", __name__)

REPORT_TYPES = {"ADVERSE_REACTION", "FDA_ANNUAL", "GENETIC_UPDATE"}


@bp.post("/regulatory-reports")
def create_report():
    _uid, role = get_auth()
    require_role(role, {"ComplianceOfficer"})
    data = body()
    donor_id = require_str(data, "donor_id")
    report_type = require_enum(data, "report_type", REPORT_TYPES)
    as_of = _validate_dt(data, "as_of")
    donor = get_donor(donor_id)

    total_shipped = sum(
        r["vial_count"] for r in db.vial_reservations.values()
        if r["donor_id"] == donor_id and r["status"] == "SHIPPED"
    )
    rep = base_fields(db)
    rep.update({
        "donor_id": donor_id,
        "report_type": report_type,
        "as_of": as_of,
        "total_families_at_report": donor["reported_family_count"],
        "total_vials_shipped_at_report": total_shipped,
        "status": "FILED",
    })
    db.regulatory_reports[rep["id"]] = rep
    return ok_object(rep, 201)


@bp.get("/regulatory-reports/<i>")
def get_one(i):
    _uid, role = get_auth()
    require_role(role, {"ComplianceOfficer"})
    return ok_object(get_report(i))


@bp.get("/regulatory-reports")
def list_reports():
    _uid, role = get_auth()
    require_role(role, {"ComplianceOfficer"})
    items = list(db.regulatory_reports.values())
    donor_f = request.args.get("donor_id")
    type_f = request.args.get("report_type")
    if donor_f is not None:
        items = [r for r in items if r["donor_id"] == donor_f]
    if type_f is not None:
        items = [r for r in items if r["report_type"] == type_f]
    page, limit, offset, total = paginate(items)
    return ok_array(page, limit, offset, total)
