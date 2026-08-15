"""PostingRecord endpoints (PRD 3.6)."""
from datetime import timedelta

from flask import Blueprint, request

import calc
import db
import domain
from errors import ApiError, err_invalid_request, err_invalid_state
from middleware import require_roles
from response import success
from serializers import posting_out
from util import clock_today, req_str, opt_str, parse_date

bp = Blueprint("postings", __name__, url_prefix="/api")


def get_posting_or_404(pid):
    p = db.posting_records.get(pid)
    if p is None:
        raise ApiError("ERR_POSTING_RECORD_NOT_FOUND", 404,
                       "Posting record not found")
    return p


@bp.route("/posting-records", methods=["POST"])
def create_posting_record():
    user_id, _ = require_roles("FieldInstaller")
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        raise err_invalid_request("Request body must be a JSON object")

    flight_id = body.get("flight_id")
    if isinstance(flight_id, str) and flight_id not in db.flights:
        raise ApiError("ERR_FLIGHT_NOT_FOUND", 404, "Flight not found")

    # Family 4: shape
    flight_id = req_str(body, "flight_id")
    posted_on = parse_date(body.get("posted_on"), "posted_on")
    photo_proof_url = req_str(body, "photo_proof_url")
    notes = opt_str(body, "notes", default="")

    flight = db.flights[flight_id]

    # Family 8: the flight must be postable
    if flight["status"] not in ("ART_CLEARED", "MISSED"):
        raise ApiError("ERR_FLIGHT_NOT_POSTABLE", 409,
                       "A posting record requires the flight in ART_CLEARED "
                       "or MISSED")

    # Family 9: posting date window
    if posted_on < flight["start_date"] - timedelta(days=7) \
            or posted_on > clock_today():
        raise err_invalid_request(
            "posted_on must be within [start_date - 7 days, current date]")

    p = db.new_resource()
    p.update({
        "flight_id": flight["id"],
        "installer_user_id": user_id,
        "posted_on": posted_on,
        "photo_proof_url": photo_proof_url,
        "notes": notes,
        "status": "REPORTED",
        "verified_by_user_id": None,
        "rejection_reason": None,
    })
    db.posting_records[p["id"]] = p
    return success(posting_out(p), code=201)


@bp.route("/posting-records/<pid>", methods=["PUT"])
def update_posting_record(pid):
    user_id, _ = require_roles("OperationsAuditor")
    p = get_posting_or_404(pid)
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        raise err_invalid_request("Request body must be a JSON object")

    new_status = body.get("status")
    if not isinstance(new_status, str) or new_status not in (
            "REPORTED", "VERIFIED", "REJECTED"):
        raise err_invalid_request("status is required and must be REPORTED, "
                                  "VERIFIED or REJECTED")
    rejection_reason = None
    if "rejection_reason" in body and body["rejection_reason"] is not None:
        if not isinstance(body["rejection_reason"], str):
            raise err_invalid_request("rejection_reason must be a string")
        rejection_reason = body["rejection_reason"]
    if new_status == "REJECTED" and not rejection_reason:
        raise err_invalid_request(
            "Rejection requires a non-empty rejection_reason")

    # Family 5: state legality
    if p["status"] != "REPORTED":
        raise err_invalid_state(
            "Posting record cannot transition %s -> %s"
            % (p["status"], new_status))
    if new_status == "REPORTED":
        raise err_invalid_state("A REPORTED record cannot be re-reported")
    if new_status == "VERIFIED":
        for other in db.posting_records.values():
            if other["id"] != p["id"] and other["flight_id"] == p["flight_id"] \
                    and other["status"] == "VERIFIED":
                raise err_invalid_state(
                    "A VERIFIED posting already exists for this flight")

    # Family 6: segregation of duties
    if user_id == p["installer_user_id"]:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES", 403,
                       "The verifier must differ from the installer")

    flight = db.flights.get(p["flight_id"])

    if new_status == "REJECTED":
        p["rejection_reason"] = rejection_reason
        p["status"] = "REJECTED"
        db.touch(p)
        return success(posting_out(p))

    # VERIFIED
    if flight is None or flight["status"] not in ("ART_CLEARED", "MISSED"):
        raise err_invalid_state(
            "The flight is not in a state that accepts verification")
    p["verified_by_user_id"] = user_id
    p["status"] = "VERIFIED"
    db.touch(p)

    on_time = p["posted_on"] <= flight["start_date"] + timedelta(days=2)
    if on_time:
        domain.flight_enters_live(flight)
    else:
        flight["missed_days"] = (p["posted_on"] - flight["start_date"]).days
        domain.flight_enters_live(flight)
        domain.auto_make_good(flight, "MISSED_POSTING",
                              calc.mg_missed_posting(flight))

    # Successor completion cascade (PRD 3.6): every other flight on the same
    # face in {LIVE, HOLDOVER} with end_date before the current date completes.
    today = clock_today()
    candidates = [
        f for f in domain.face_flights(flight["face_id"])
        if f["id"] != flight["id"] and f["status"] in ("LIVE", "HOLDOVER")
        and f["end_date"] < today
    ]
    candidates.sort(key=lambda f: (f["end_date"], f["_seq"]))
    for other in candidates:
        domain.complete_flight(other, with_holdover=True)

    return success(posting_out(p))
