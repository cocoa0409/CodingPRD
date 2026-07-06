from flask import Blueprint, request

import errors
from errors import err
from db import db, base_fields, touch
from clock import parse_iso
from middleware import get_auth, require_role
from response import ok_object, ok_array
from validate import body, require_str, require_bool, require_positive_int, paginate
from routes.common import get_specimen, get_donor
import domain

bp = Blueprint("specimens", __name__)

READ_ROLES = {"LabTech", "ComplianceOfficer", "CatalogManager"}


def _validate_dt(data, field):
    v = data.get(field)
    if not isinstance(v, str):
        raise err(errors.ERR_INVALID_REQUEST, f"Field {field} must be an ISO8601 datetime")
    try:
        parse_iso(v)
    except (ValueError, TypeError):
        raise err(errors.ERR_INVALID_REQUEST, f"Field {field} must be an ISO8601 datetime")
    return v


@bp.post("/specimens")
def create_specimen():
    _uid, role = get_auth()
    require_role(role, {"LabTech"})
    data = body()
    donor_id = require_str(data, "donor_id")
    collection_date = _validate_dt(data, "collection_date")
    initial_vial_count = require_positive_int(data, "initial_vial_count")
    quarantine_release_date = _validate_dt(data, "quarantine_release_date")
    retest_negative = require_bool(data, "retest_negative", default=False, required=False)

    get_donor(donor_id)  # existence

    specimen = base_fields(db)
    specimen.update({
        "donor_id": donor_id,
        "collection_date": collection_date,
        "initial_vial_count": initial_vial_count,
        "quarantine_release_date": quarantine_release_date,
        "retest_negative": retest_negative,
        "status": "COLLECTED",
    })
    db.specimens[specimen["id"]] = specimen
    return ok_object(specimen, 201)


@bp.get("/specimens/<i>")
def get_one(i):
    _uid, role = get_auth()
    require_role(role, READ_ROLES)
    return ok_object(get_specimen(i))


@bp.get("/specimens")
def list_specimens():
    _uid, role = get_auth()
    require_role(role, READ_ROLES)
    items = list(db.specimens.values())
    donor_f = request.args.get("donor_id")
    status_f = request.args.get("status")
    if donor_f is not None:
        items = [s for s in items if s["donor_id"] == donor_f]
    if status_f is not None:
        items = [s for s in items if s["status"] == status_f]
    page, limit, offset, total = paginate(items)
    return ok_array(page, limit, offset, total)


@bp.post("/specimens/<i>/begin-quarantine")
def begin_quarantine(i):
    _uid, role = get_auth()
    require_role(role, {"LabTech"})
    specimen = get_specimen(i)
    data = body()
    if specimen["status"] != "COLLECTED":
        raise err(errors.ERR_INVALID_STATE, "Specimen not in COLLECTED")
    dewar_code = require_str(data, "dewar_code")
    donor = db.donors.get(specimen["donor_id"])
    if donor is None or donor["status"] != "APPROVED":
        raise err(errors.ERR_INVALID_STATE, "Donor not APPROVED")
    specimen["status"] = "QUARANTINE"
    touch(db, specimen)
    # mint one inventory lot
    inv = base_fields(db)
    inv.update({
        "specimen_id": specimen["id"],
        "donor_id": specimen["donor_id"],
        "dewar_code": dewar_code,
        "total_vials": specimen["initial_vial_count"],
        "reserved_vials": 0,
        "shipped_vials": 0,
        "available_vials": specimen["initial_vial_count"],
        "committed_available_vials": specimen["initial_vial_count"],
        "is_listed": False,
        "hold_status": "OPEN",
    })
    db.donor_inventories[inv["id"]] = inv
    return ok_object(specimen)


@bp.post("/specimens/<i>/release-quarantine")
def release_quarantine(i):
    _uid, role = get_auth()
    require_role(role, {"ComplianceOfficer"})
    specimen = get_specimen(i)
    if specimen["status"] != "QUARANTINE":
        raise err(errors.ERR_INVALID_STATE, "Specimen not in QUARANTINE")
    if not specimen["retest_negative"]:
        raise err(errors.ERR_RETEST_NOT_NEGATIVE, "Retest not negative")
    if db.now() < parse_iso(specimen["quarantine_release_date"]):
        raise err(errors.ERR_QUARANTINE_NOT_ELAPSED, "Quarantine window not elapsed")
    donor = db.donors.get(specimen["donor_id"])
    if donor is None or donor["status"] != "APPROVED":
        raise err(errors.ERR_INVALID_STATE, "Donor not APPROVED")
    specimen["status"] = "RELEASED"
    touch(db, specimen)
    # first released specimen for donor -> donor ACTIVE
    if donor["status"] == "APPROVED":
        donor["status"] = "ACTIVE"
        touch(db, donor)
    # recompute inventory listability
    for inv in db.donor_inventories.values():
        if inv["specimen_id"] == specimen["id"]:
            domain.recompute_inventory(inv, bump=True)
    return ok_object(specimen)


@bp.post("/specimens/<i>/discard")
def discard(i):
    _uid, role = get_auth()
    require_role(role, {"ComplianceOfficer"})
    specimen = get_specimen(i)
    if specimen["status"] not in ("QUARANTINE", "RELEASED"):
        raise err(errors.ERR_INVALID_STATE, "Specimen cannot be discarded from its current state")
    domain.discard_specimen(specimen, cancel_shipments=True)
    return ok_object(specimen)
