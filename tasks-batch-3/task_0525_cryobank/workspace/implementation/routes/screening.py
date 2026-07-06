from flask import Blueprint, request

import errors
from errors import err
from db import db, base_fields, touch
from middleware import get_auth, require_role
from response import ok_object, ok_array
from validate import (
    body, require_str, require_bool, require_nonneg_int, optional_str, paginate,
)
from routes.common import get_application, get_donor
import domain

bp = Blueprint("screening", __name__)

READ_ROLES = {"ScreeningOfficer", "ComplianceOfficer"}


@bp.post("/screening-applications")
def create_app():
    _uid, role = get_auth()
    require_role(role, {"ScreeningOfficer"})
    data = body()
    donor_id = require_str(data, "donor_id")
    fda_risk_flag = require_bool(data, "fda_risk_flag", default=False, required=False)
    genetic_carrier_count = require_nonneg_int(data, "genetic_carrier_count")
    partner_screening_required = require_bool(data, "partner_screening_required", default=False, required=False)
    decision_note = optional_str(data, "decision_note")

    donor = get_donor(donor_id)  # existence

    app = base_fields(db)
    app.update({
        "donor_id": donor_id,
        "fda_risk_flag": fda_risk_flag,
        "genetic_carrier_count": genetic_carrier_count,
        "partner_screening_required": partner_screening_required,
        "decision_note": decision_note,
        "status": "SUBMITTED",
    })
    db.screening_applications[app["id"]] = app
    return ok_object(app, 201)


@bp.get("/screening-applications/<i>")
def get_one(i):
    _uid, role = get_auth()
    require_role(role, READ_ROLES)
    return ok_object(get_application(i))


@bp.get("/screening-applications")
def list_apps():
    _uid, role = get_auth()
    require_role(role, READ_ROLES)
    items = list(db.screening_applications.values())
    donor_f = request.args.get("donor_id")
    status_f = request.args.get("status")
    if donor_f is not None:
        items = [a for a in items if a["donor_id"] == donor_f]
    if status_f is not None:
        items = [a for a in items if a["status"] == status_f]
    page, limit, offset, total = paginate(items)
    return ok_array(page, limit, offset, total)


@bp.post("/screening-applications/<i>/start-review")
def start_review(i):
    _uid, role = get_auth()
    require_role(role, {"ScreeningOfficer"})
    app = get_application(i)
    if app["status"] != "SUBMITTED":
        raise err(errors.ERR_INVALID_STATE, "Application not in SUBMITTED")
    app["status"] = "UNDER_REVIEW"
    touch(db, app)
    donor = db.donors.get(app["donor_id"])
    if donor is not None and donor["status"] == "APPLICANT":
        donor["status"] = "SCREENING"
        touch(db, donor)
    return ok_object(app)


@bp.post("/screening-applications/<i>/approve")
def approve(i):
    _uid, role = get_auth()
    require_role(role, {"ScreeningOfficer"})
    app = get_application(i)
    data = body()
    if app["status"] != "UNDER_REVIEW":
        raise err(errors.ERR_INVALID_STATE, "Application not in UNDER_REVIEW")
    if app["fda_risk_flag"]:
        raise err(errors.ERR_FDA_INELIGIBLE, "FDA risk flag set")
    if app["genetic_carrier_count"] > 0 and app["partner_screening_required"]:
        raise err(errors.ERR_GENETIC_SCREENING_INCOMPLETE, "Partner screening incomplete")
    note = optional_str(data, "decision_note")
    if note is not None:
        app["decision_note"] = note
    app["status"] = "APPROVED"
    touch(db, app)
    donor = db.donors.get(app["donor_id"])
    if donor is not None:
        donor["status"] = "APPROVED"
        donor["fda_eligible"] = True
        donor["genetic_panel_clear"] = (app["genetic_carrier_count"] == 0)
        touch(db, donor)
    return ok_object(app)


@bp.post("/screening-applications/<i>/defer")
def defer(i):
    _uid, role = get_auth()
    require_role(role, {"ScreeningOfficer"})
    app = get_application(i)
    data = body()
    if app["status"] != "UNDER_REVIEW":
        raise err(errors.ERR_INVALID_STATE, "Application not in UNDER_REVIEW")
    note = optional_str(data, "decision_note")
    if note is not None:
        app["decision_note"] = note
    app["status"] = "DEFERRED"
    touch(db, app)
    donor = db.donors.get(app["donor_id"])
    if donor is not None:
        donor["status"] = "DEFERRED"
        touch(db, donor)
        # CASCADE: every non-DISCARDED specimen -> DISCARDED (voids reservations,
        # cancels shipments); every inventory -> FROZEN.
        for specimen in db.specimens.values():
            if specimen["donor_id"] == donor["id"] and specimen["status"] != "DISCARDED":
                domain.discard_specimen(specimen, cancel_shipments=True)
        for inv in db.donor_inventories.values():
            if inv["donor_id"] == donor["id"]:
                inv["hold_status"] = "FROZEN"
                domain.recompute_inventory(inv, bump=True)
    return ok_object(app)
