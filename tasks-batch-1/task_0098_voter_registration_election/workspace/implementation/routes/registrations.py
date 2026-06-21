"""VoterRegistration endpoints (PRD §3.2, §3.9)."""

from flask import Blueprint, g, request

import db
from errors import (
    APIError, invalid_request, not_found, invalid_state,
)
import errors as E
from middleware import require_roles
from response import ok_object, ok_array
from services import serialize
from services.common import (
    get_json_body, require_fields, paginate, parse_iso, clock_now,
    recompute_precinct, recompute_election_counts,
)

bp = Blueprint("registrations", __name__)

PARTIES = {"DEMOCRAT", "REPUBLICAN", "INDEPENDENT", "GREEN",
           "LIBERTARIAN", "UNAFFILIATED"}
VOTING_AGE = 18

# Non-approval transition target statuses.
NONAPPROVAL_TARGETS = {"NEEDS_REVIEW", "PENDING", "REJECTED", "WITHDRAWN"}


@bp.route("/registrations", methods=["POST"])
def create_registration():
    require_roles("ElectionOfficial", "Voter")
    body = get_json_body()
    require_fields(body, "election_id", "first_name", "last_name", "national_id",
                   "is_citizen", "date_of_birth", "county_fips", "street_number")
    election = db.elections.get(body["election_id"])
    if election is None:
        raise not_found("Election not found.")

    # Field shape.
    for f in ("first_name", "last_name", "national_id", "county_fips"):
        if not isinstance(body[f], str) or not body[f].strip():
            raise invalid_request(f"{f} must be a non-empty string.")
    if not isinstance(body["is_citizen"], bool):
        raise invalid_request("is_citizen must be a boolean.")
    if isinstance(body["street_number"], bool) or not isinstance(body["street_number"], int):
        raise invalid_request("street_number must be an integer.")
    try:
        parse_iso(body["date_of_birth"])
    except (ValueError, TypeError):
        raise invalid_request("date_of_birth must be a valid ISO 8601 timestamp.")
    party = body.get("party", "UNAFFILIATED")
    if party is None:
        party = "UNAFFILIATED"
    if party not in PARTIES:
        raise invalid_request("party out of range.")

    # Duplicate guard (§3.2): same (election_id, national_id) in
    # {PENDING, NEEDS_REVIEW, ACTIVE}.
    for r in db.registrations.values():
        if (r["election_id"] == body["election_id"]
                and r["national_id"] == body["national_id"]
                and r["status"] in ("PENDING", "NEEDS_REVIEW", "ACTIVE")):
            raise APIError(E.ERR_DUPLICATE_REGISTRATION,
                           "A non-rejected registration with this national_id exists.",
                           409)

    row = {
        "election_id": body["election_id"],
        "precinct_id": None,
        "first_name": body["first_name"],
        "last_name": body["last_name"],
        "national_id": body["national_id"],
        "is_citizen": body["is_citizen"],
        "date_of_birth": body["date_of_birth"],
        "county_fips": body["county_fips"],
        "street_number": body["street_number"],
        "party": party,
        "early_voted_at": None,
        "status": "PENDING",
        "reviewed_by_user_id": None,
    }
    db.stamp_create_full(row)
    db.registrations[row["id"]] = row
    return ok_object(serialize.registration_view(row), 201)


@bp.route("/registrations/<rid>", methods=["GET"])
def get_registration(rid):
    require_roles("ElectionAdmin", "ElectionOfficial", "Voter")
    r = db.registrations.get(rid)
    if r is None:
        raise not_found("Registration not found.")
    return ok_object(serialize.registration_view(r))


@bp.route("/registrations", methods=["GET"])
def list_registrations():
    require_roles("ElectionAdmin", "ElectionOfficial")
    election_id = request.args.get("election_id")
    precinct_id = request.args.get("precinct_id")
    status = request.args.get("status")
    rows = list(db.registrations.values())
    if election_id is not None:
        rows = [r for r in rows if r["election_id"] == election_id]
    if precinct_id is not None:
        rows = [r for r in rows if r.get("precinct_id") == precinct_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    page, limit, offset, total, has_more = paginate(rows)
    return ok_array([serialize.registration_view(r) for r in page],
                    limit=limit, offset=offset, total_count=total, has_more=has_more)


def _age_years(dob_iso, election_date_iso):
    """Completed-years age as of election_date (PRD §3.9 calendar arithmetic)."""
    dob = parse_iso(dob_iso)
    ed = parse_iso(election_date_iso)
    age = ed.year - dob.year
    if (ed.month, ed.day) < (dob.month, dob.day):
        age -= 1
    return age


def _select_precinct(reg, election):
    """Precinct selector (PRD §3.9). Returns (precinct or None, all_matches).

    all_matches is the list of precincts matching the county/street filter
    regardless of capacity_posture — used to distinguish NO_PRECINCT_MATCH
    (empty) from PRECINCT_FULL (non-empty but no OPEN candidate).
    """
    matches = []
    for p in db.precincts.values():
        if p["election_id"] != election["id"]:
            continue
        if p["county_fips"] != reg["county_fips"]:
            continue
        if not (p["street_low"] <= reg["street_number"] <= p["street_high"]):
            continue
        matches.append(p)
    open_candidates = [p for p in matches if p.get("capacity_posture") == "OPEN"]
    if not open_candidates:
        return None, matches
    open_candidates.sort(key=lambda p: (
        p.get("assigned_count", 0),         # emptiest first
        -p["max_registrations"],            # most headroom
        p.get("created_at", ""),            # oldest
        p.get("id", ""),
    ))
    return open_candidates[0], matches


@bp.route("/registrations/<rid>/approve", methods=["POST"])
def approve_registration(rid):
    require_roles("ElectionOfficial")
    r = db.registrations.get(rid)
    if r is None:
        raise not_found("Registration not found.")
    election = db.elections.get(r["election_id"])
    if election is None:
        raise not_found("Election not found.")

    # State (priority 4).
    if r["status"] != "PENDING":
        raise invalid_state("Registration is not PENDING.")
    if election["status"] != "REGISTRATION_OPEN":
        raise invalid_state("Election is not in REGISTRATION_OPEN.")

    # Temporal window (priority 6): strictly before registration_deadline.
    if clock_now() >= parse_iso(election["registration_deadline"]):
        raise APIError(E.ERR_WINDOW_CLOSED,
                       "Registration deadline has passed.", 422)

    # Eligibility gate, in order: citizen, age, residency, then capacity.
    if r["is_citizen"] is not True:
        raise APIError(E.ERR_NOT_CITIZEN, "Registrant is not a citizen.", 422)
    if _age_years(r["date_of_birth"], election["election_date"]) < VOTING_AGE:
        raise APIError(E.ERR_UNDERAGE, "Registrant is under the voting age.", 422)

    selected, matches = _select_precinct(r, election)
    if not matches:
        raise APIError(E.ERR_NO_PRECINCT_MATCH,
                       "No precinct covers the voter's county and street.", 422)
    if selected is None:
        raise APIError(E.ERR_PRECINCT_FULL,
                       "All matching precincts are full.", 409)

    # Apply.
    r["status"] = "ACTIVE"
    r["precinct_id"] = selected["id"]
    r["reviewed_by_user_id"] = g.user_id
    db.stamp_update(r)
    recompute_precinct(selected)
    db.stamp_update(selected)
    recompute_election_counts(election)
    db.stamp_update(election)
    return ok_object(serialize.registration_view(r))


@bp.route("/registrations/<rid>/transition", methods=["POST"])
def transition_registration(rid):
    require_roles("ElectionOfficial")
    r = db.registrations.get(rid)
    if r is None:
        raise not_found("Registration not found.")
    body = get_json_body()
    require_fields(body, "target_status")
    target = body["target_status"]
    if target not in NONAPPROVAL_TARGETS:
        raise invalid_request("Unknown target_status.")

    cur = r["status"]

    if target == "NEEDS_REVIEW":
        if cur != "PENDING":
            raise invalid_state("Registration is not PENDING.")
        r["status"] = "NEEDS_REVIEW"
        db.stamp_update(r)
        return ok_object(serialize.registration_view(r))

    if target == "PENDING":
        if cur != "NEEDS_REVIEW":
            raise invalid_state("Registration is not NEEDS_REVIEW.")
        # Apply corrected fields when present.
        if "county_fips" in body and body["county_fips"] is not None:
            if not isinstance(body["county_fips"], str) or not body["county_fips"].strip():
                raise invalid_request("county_fips must be a non-empty string.")
            r["county_fips"] = body["county_fips"]
        if "street_number" in body and body["street_number"] is not None:
            sn = body["street_number"]
            if isinstance(sn, bool) or not isinstance(sn, int):
                raise invalid_request("street_number must be an integer.")
            r["street_number"] = sn
        if "is_citizen" in body and body["is_citizen"] is not None:
            if not isinstance(body["is_citizen"], bool):
                raise invalid_request("is_citizen must be a boolean.")
            r["is_citizen"] = body["is_citizen"]
        r["status"] = "PENDING"
        db.stamp_update(r)
        return ok_object(serialize.registration_view(r))

    if target == "REJECTED":
        if cur not in ("PENDING", "NEEDS_REVIEW"):
            raise invalid_state("Registration is not PENDING or NEEDS_REVIEW.")
        r["status"] = "REJECTED"
        r["reviewed_by_user_id"] = g.user_id
        db.stamp_update(r)
        return ok_object(serialize.registration_view(r))

    if target == "WITHDRAWN":
        if cur != "ACTIVE":
            raise invalid_state("Registration is not ACTIVE.")
        # Withdraw guard: no in-flight absentee ballot.
        for b in db.ballots.values():
            if (b["registration_id"] == rid
                    and b["request_status"] in ("ISSUED", "RETURNED", "ACCEPTED")):
                raise APIError(E.ERR_BALLOT_BLOCKS_WITHDRAW,
                               "An in-flight absentee ballot blocks withdrawal.", 409)
        precinct = db.precincts.get(r.get("precinct_id"))
        r["status"] = "WITHDRAWN"
        db.stamp_update(r)
        if precinct is not None:
            recompute_precinct(precinct)
            db.stamp_update(precinct)
        election = db.elections.get(r["election_id"])
        if election is not None:
            recompute_election_counts(election)
            db.stamp_update(election)
        return ok_object(serialize.registration_view(r))

    raise invalid_request("Unsupported target_status.")
