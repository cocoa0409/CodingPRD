"""RecountCase endpoints (PRD §3.8, §3.9)."""

from flask import Blueprint, g, request

import db
from errors import (
    APIError, invalid_request, not_found, invalid_state, segregation,
)
import errors as E
from middleware import require_roles
from response import ok_object, ok_array
from services import serialize
from services.common import get_json_body, require_fields, paginate

bp = Blueprint("recounts", __name__)

DISCREPANCY_TOLERANCE = 5
PASSES = {"MACHINE", "HAND"}
RECOUNT_TARGETS = {"CERTIFIED", "DISMISSED"}


@bp.route("/recount-cases", methods=["POST"])
def create_recount():
    require_roles("ElectionAdmin")
    body = get_json_body()
    require_fields(body, "election_id", "precinct_id")
    # Existence left-to-right: election_id then precinct_id.
    election = db.elections.get(body["election_id"])
    if election is None:
        raise not_found("Election not found.")
    precinct = db.precincts.get(body["precinct_id"])
    if precinct is None:
        raise not_found("Precinct not found.")

    # Recount precondition (priority 16): precinct must be TALLIED.
    if precinct["tally_status"] != "TALLIED":
        raise APIError(E.ERR_PRECINCT_NOT_TALLIED,
                       "Precinct is not TALLIED.", 409)

    row = {
        "election_id": body["election_id"],
        "precinct_id": body["precinct_id"],
        "original_count": precinct.get("reported_vote_count"),
        "machine_recount": None,
        "hand_recount": None,
        "certified_count": None,
        "status": "REQUESTED",
    }
    db.stamp_create_full(row)
    db.recount_cases[row["id"]] = row
    return ok_object(serialize.recount_view(row), 201)


@bp.route("/recount-cases/<rid>", methods=["GET"])
def get_recount(rid):
    require_roles("ElectionAdmin", "Canvasser")
    rc = db.recount_cases.get(rid)
    if rc is None:
        raise not_found("Recount case not found.")
    return ok_object(serialize.recount_view(rc))


@bp.route("/recount-cases", methods=["GET"])
def list_recounts():
    require_roles("ElectionAdmin", "Canvasser")
    election_id = request.args.get("election_id")
    precinct_id = request.args.get("precinct_id")
    status = request.args.get("status")
    rows = list(db.recount_cases.values())
    if election_id is not None:
        rows = [r for r in rows if r["election_id"] == election_id]
    if precinct_id is not None:
        rows = [r for r in rows if r["precinct_id"] == precinct_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    page, limit, offset, total, has_more = paginate(rows)
    return ok_array([serialize.recount_view(r) for r in page],
                    limit=limit, offset=offset, total_count=total, has_more=has_more)


@bp.route("/recount-cases/<rid>/submit-pass", methods=["POST"])
def submit_pass(rid):
    require_roles("Canvasser")
    rc = db.recount_cases.get(rid)
    if rc is None:
        raise not_found("Recount case not found.")
    body = get_json_body()
    require_fields(body, "pass", "count")
    which = body["pass"]
    if which not in PASSES:
        raise invalid_request("pass must be MACHINE or HAND.")
    count = body["count"]
    if isinstance(count, bool) or not isinstance(count, int):
        raise invalid_request("count must be an integer.")

    cur = rc["status"]
    # Legal source-state check (priority 4) before segregation.
    if which == "MACHINE":
        if cur not in ("REQUESTED", "HAND_DONE"):
            raise invalid_state("Machine pass not allowed from current state.")
    else:  # HAND
        if cur not in ("REQUESTED", "MACHINE_DONE"):
            raise invalid_state("Hand pass not allowed from current state.")

    # Segregation of duties (priority 5): acting user != tally recorder.
    precinct = db.precincts.get(rc["precinct_id"])
    if precinct is not None and g.user_id == precinct.get("tally_recorded_by_user_id"):
        raise segregation(
            "The canvasser who recorded the tally may not submit a recount pass.")

    if which == "MACHINE":
        rc["machine_recount"] = count
        rc["status"] = "BOTH_DONE" if cur == "HAND_DONE" else "MACHINE_DONE"
    else:
        rc["hand_recount"] = count
        rc["status"] = "BOTH_DONE" if cur == "MACHINE_DONE" else "HAND_DONE"
    db.stamp_update(rc)
    return ok_object(serialize.recount_view(rc))


@bp.route("/recount-cases/<rid>/transition", methods=["POST"])
def transition_recount(rid):
    require_roles("ElectionAdmin")
    rc = db.recount_cases.get(rid)
    if rc is None:
        raise not_found("Recount case not found.")
    body = get_json_body()
    require_fields(body, "target_status")
    target = body["target_status"]
    if target not in RECOUNT_TARGETS:
        raise invalid_request("Unknown target_status.")

    cur = rc["status"]

    if target == "CERTIFIED":
        if cur != "BOTH_DONE":
            raise invalid_state("Recount is not BOTH_DONE.")
        machine = rc["machine_recount"]
        hand = rc["hand_recount"]
        delta = abs(machine - hand)
        if delta <= DISCREPANCY_TOLERANCE:
            certified = hand
        else:
            certified = min(machine, hand)
        rc["certified_count"] = certified
        rc["status"] = "CERTIFIED"
        db.stamp_update(rc)
        precinct = db.precincts.get(rc["precinct_id"])
        if precinct is not None:
            precinct["reported_vote_count"] = certified
            db.stamp_update(precinct)
        return ok_object(serialize.recount_view(rc))

    if target == "DISMISSED":
        if cur not in ("REQUESTED", "MACHINE_DONE", "HAND_DONE", "BOTH_DONE"):
            raise invalid_state("Recount cannot be dismissed from current state.")
        rc["status"] = "DISMISSED"
        db.stamp_update(rc)
        return ok_object(serialize.recount_view(rc))

    raise invalid_request("Unsupported target_status.")
