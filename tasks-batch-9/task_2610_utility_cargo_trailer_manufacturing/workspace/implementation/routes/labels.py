"""VIN minting, certification labelling and title documentation (PRD 3.7)."""
from flask import Blueprint

import errors
import lookups
import validators as v
from db import clock_now, db, new_id, now_iso, public, public_list, stamp_new, touch
from middleware import actor, endpoint
from response import created, listing
from services import calc, rollups

bp = Blueprint("labels", __name__)


@bp.route("/trailer-units/<unit_id>/certification-label", methods=["POST"])
@endpoint(["CertificationOfficer"])
def issue_label(unit_id):
    unit = lookups.unit_or_404(unit_id)
    data = v.body()
    tire_size_code = v.req_str(data, "tire_size_code", min_len=1, max_len=32)

    if unit["build_status"] != "ROAD_TEST_PASSED":
        raise errors.ApiError("ERR_UNIT_BUILD_STATE_INVALID", 409,
                              "A trailer in build_status %s may not be labelled"
                              % unit["build_status"])
    if rollups.issued_label(unit["id"]) is not None:
        raise errors.ApiError("ERR_LABEL_ALREADY_ISSUED", 409,
                              "Trailer %s already carries an ISSUED certification label"
                              % unit["id"])
    model = db.models.get(unit["model_id"])
    if model.get("certified_by_user_id") is not None and \
            actor() == model["certified_by_user_id"]:
        raise errors.ApiError("ERR_SEGREGATION_OF_DUTIES", 403,
                              "User %s certified this model and may not issue its labels"
                              % actor())
    if unit["compliance_status"] != "FULLY_COMPLIANT":
        raise errors.ApiError("ERR_UNIT_NOT_COMPLIANT", 422,
                              "A trailer in compliance_status %s may not be labelled"
                              % unit["compliance_status"])

    db.vin_counter += 1
    vin_sequence = db.vin_counter
    row = {
        "id": new_id(),
        "unit_id": unit["id"],
        "vin": calc.build_vin(model, unit, vin_sequence, clock_now().year),
        "vin_sequence": vin_sequence,
        "gvwr_lbs": unit["gvwr_lbs"],
        "gawr_per_axle_lbs": model["axle_rating_lbs"],
        "tire_size_code": tire_size_code,
        "model_version_pinned": unit["model_version_pinned"],
        "mco_number": calc.mco_number(vin_sequence),
        "issued_by_user_id": actor(),
        "issued_at": now_iso(),
        "status": "ISSUED",
        "voided_reason": None,
    }
    stamp_new(row)
    db.labels[row["id"]] = row

    unit["vin"] = row["vin"]
    unit["build_status"] = "LABELED"
    touch(unit)
    rollups.maybe_release_to_stock(unit)
    return created(public(row))


@bp.route("/trailer-units/<unit_id>/certification-label", methods=["GET"])
@endpoint(["CertificationOfficer", "SalesAdmin", "PlantEngineer", "Dealer"])
def list_labels(unit_id):
    unit = lookups.unit_or_404(unit_id)
    include_voided = v.query_flag("include_voided", False)
    limit, offset = v.pagination()
    rows = sorted(rollups.labels_of_unit(unit["id"]), key=lambda r: (r["created_at"], r["_seq"]))
    if not include_voided:
        rows = [r for r in rows if r["status"] != "VOIDED"]
    total = len(rows)
    return listing(public_list(rows[offset:offset + limit]), limit, offset, total)
