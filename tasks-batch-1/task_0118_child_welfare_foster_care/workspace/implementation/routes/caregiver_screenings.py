"""Caregiver screening routes (PRD §3.4)."""
from flask import Blueprint, request

import db
import errors
import helpers
import middleware
import response
from services import serialize

bp = Blueprint("caregiver_screenings", __name__)


@bp.route("/caregiver-screenings", methods=["POST"])
def create_screening():
    _, role = middleware.authenticate()
    middleware.authorize(role, {"LicensingWorker"})
    body = helpers.get_body()
    foster_home_id = helpers.require_str(body, "foster_home_id")
    member_name = helpers.require_str(body, "member_name")
    disqualifying = helpers.optional_bool(body, "disqualifying", default=False)
    home = db.foster_homes.get(foster_home_id)
    if home is None:
        raise errors.not_found("Foster home not found.")
    record = {
        "foster_home_id": foster_home_id,
        "member_name": member_name,
        "status": "PENDING",
        "disqualifying": disqualifying,
    }
    db.stamp_create(record)
    db.caregiver_screenings[record["id"]] = record
    # Adding a screening changes the home's clearance picture; bump the home's
    # version (PRD §2.8: adding or clearing a screening bumps the home version).
    db.bump(home)
    return response.success(serialize.caregiver_screening(record), 201)


@bp.route("/caregiver-screenings/<sid>", methods=["GET"])
def get_screening(sid):
    _, role = middleware.authenticate()
    middleware.authorize(role, {"Admin", "LicensingWorker"})
    record = db.caregiver_screenings.get(sid)
    if record is None:
        raise errors.not_found("Caregiver screening not found.")
    return response.success(serialize.caregiver_screening(record), 200)


@bp.route("/caregiver-screenings", methods=["GET"])
def list_screenings():
    _, role = middleware.authenticate()
    middleware.authorize(role, {"Admin", "LicensingWorker"})
    limit, offset = helpers.pagination()
    foster_home_id = request.args.get("foster_home_id")
    status = request.args.get("status")
    records = list(db.caregiver_screenings.values())
    if foster_home_id is not None:
        records = [r for r in records if r["foster_home_id"] == foster_home_id]
    if status is not None:
        records = [r for r in records if r["status"] == status]
    page, total = helpers.paginate(records, limit, offset)
    return response.list_success([serialize.caregiver_screening(r) for r in page], limit, offset, total)


@bp.route("/caregiver-screenings/<sid>/resolve", methods=["POST"])
def resolve_screening(sid):
    _, role = middleware.authenticate()
    middleware.authorize(role, {"LicensingWorker"})
    record = db.caregiver_screenings.get(sid)
    if record is None:
        raise errors.not_found("Caregiver screening not found.")
    if record["status"] != "PENDING":
        raise errors.invalid_state("Screening is not PENDING.")
    if record["disqualifying"]:
        record["status"] = "FLAGGED"
    else:
        record["status"] = "CLEARED"
    db.bump(record)
    # Resolving changes the home's clearance picture; bump the owning home's
    # version (PRD §2.8: clearing a screening bumps the home version).
    home = db.foster_homes.get(record["foster_home_id"])
    if home is not None:
        db.bump(home)
    return response.success(serialize.caregiver_screening(record), 200)
