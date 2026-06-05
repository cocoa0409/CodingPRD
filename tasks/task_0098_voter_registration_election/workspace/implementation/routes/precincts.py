"""Precinct endpoints (PRD §3.1, §3.8)."""

from flask import Blueprint, g, request

import db
from errors import invalid_request, not_found, invalid_state
from middleware import require_roles
from response import ok_object, ok_array
from services import serialize
from services.common import get_json_body, require_fields, paginate

bp = Blueprint("precincts", __name__)


def _require_int(body, field, *, minimum=None):
    require_fields(body, field)
    val = body[field]
    if isinstance(val, bool) or not isinstance(val, int):
        raise invalid_request(f"{field} must be an integer.")
    if minimum is not None and val < minimum:
        raise invalid_request(f"{field} must be >= {minimum}.")
    return val


@bp.route("/precincts", methods=["POST"])
def create_precinct():
    require_roles("ElectionAdmin")
    body = get_json_body()
    require_fields(body, "election_id", "code", "county_fips",
                   "street_low", "street_high", "max_registrations")
    # Existence: election_id (left-to-right; it is the only FK in the body).
    election = db.elections.get(body["election_id"])
    if election is None:
        raise not_found("Election not found.")

    if not isinstance(body["code"], str) or not body["code"].strip():
        raise invalid_request("code must be a non-empty string.")
    if not isinstance(body["county_fips"], str) or not body["county_fips"].strip():
        raise invalid_request("county_fips must be a string.")
    street_low = _require_int(body, "street_low")
    street_high = _require_int(body, "street_high")
    max_reg = _require_int(body, "max_registrations", minimum=1)
    if street_high < street_low:
        raise invalid_request("street_high must be >= street_low.")

    row = {
        "election_id": body["election_id"],
        "code": body["code"],
        "county_fips": body["county_fips"],
        "street_low": street_low,
        "street_high": street_high,
        "max_registrations": max_reg,
        "assigned_count": 0,
        "capacity_posture": "OPEN",
        "tally_status": "PENDING",
        "reported_vote_count": None,
        "tally_recorded_by_user_id": None,
    }
    db.stamp_create_full(row)
    db.precincts[row["id"]] = row
    return ok_object(serialize.precinct_view(row), 201)


@bp.route("/precincts/<pid>", methods=["GET"])
def get_precinct(pid):
    require_roles("ElectionAdmin", "ElectionOfficial", "Canvasser", "PollWorker")
    p = db.precincts.get(pid)
    if p is None:
        raise not_found("Precinct not found.")
    return ok_object(serialize.precinct_view(p))


@bp.route("/precincts", methods=["GET"])
def list_precincts():
    require_roles("ElectionAdmin", "ElectionOfficial", "Canvasser", "PollWorker")
    election_id = request.args.get("election_id")
    rows = list(db.precincts.values())
    if election_id is not None:
        rows = [r for r in rows if r["election_id"] == election_id]
    page, limit, offset, total, has_more = paginate(rows)
    return ok_array([serialize.precinct_view(r) for r in page],
                    limit=limit, offset=offset, total_count=total, has_more=has_more)


@bp.route("/precincts/<pid>/tally", methods=["POST"])
def tally_precinct(pid):
    require_roles("Canvasser")
    p = db.precincts.get(pid)
    if p is None:
        raise not_found("Precinct not found.")
    if p["tally_status"] != "PENDING":
        raise invalid_state("Precinct is not PENDING.")
    body = get_json_body()
    count = _require_int(body, "reported_vote_count")

    p["tally_status"] = "TALLIED"
    p["reported_vote_count"] = count
    p["tally_recorded_by_user_id"] = g.user_id
    db.stamp_update(p)
    return ok_object(serialize.precinct_view(p))
