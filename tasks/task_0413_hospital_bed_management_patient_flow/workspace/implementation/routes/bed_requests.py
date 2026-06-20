"""BedRequest placement state machine: create, auto-place, assign, confirm (OCC),
release, cancel."""

from flask import Blueprint, request

import errors
from errors import err
from db import store, iso
from middleware import authenticate, authorize, get_json_body, parse_pagination
from response import success, list_success
from services import common, placement
from services.adt import append_adt
from services.listing import paginate

bp = Blueprint("bed_requests", __name__)

PRIORITIES = {"STAT", "URGENT", "ROUTINE"}
UNIT_TYPES = {"MEDSURG", "TELEMETRY", "ICU", "ED"}
REQ_STATUSES = {"QUEUED", "ASSIGNED", "CONFIRMED", "CANCELLED", "EXPIRED"}


def _get_request_or_404(req_id):
    req = store.bed_requests.get(req_id)
    if req is None:
        raise err(errors.ERR_NOT_FOUND, "Bed request not found")
    return req


@bp.route("/bed-requests", methods=["POST"])
def create_request():
    _, role = authenticate()
    authorize(role, {"TransferCenterAgent", "BedControlCoordinator"})
    body = get_json_body()

    encounter_id = body.get("encounter_id")
    preferred_unit_id = body.get("preferred_unit_id")

    # body FK existence
    if not isinstance(encounter_id, str) or not encounter_id:
        raise err(errors.ERR_INVALID_REQUEST, "encounter_id is required")
    if encounter_id not in store.encounters:
        raise err(errors.ERR_REFERENCE_NOT_FOUND, "encounter_id does not resolve")
    if preferred_unit_id is not None and preferred_unit_id not in store.units:
        raise err(errors.ERR_REFERENCE_NOT_FOUND, "preferred_unit_id does not resolve")

    acceptable = body.get("acceptable_unit_types", [])
    if acceptable is None:
        acceptable = []
    if not isinstance(acceptable, list) or any(t not in UNIT_TYPES for t in acceptable):
        raise err(errors.ERR_INVALID_REQUEST, "acceptable_unit_types must be a list of unit types")

    priority = body.get("priority", "ROUTINE")
    if priority is None:
        priority = "ROUTINE"
    if priority not in PRIORITIES:
        raise err(errors.ERR_INVALID_REQUEST, "priority must be STAT, URGENT, or ROUTINE")

    req = {
        "encounter_id": encounter_id,
        "preferred_unit_id": preferred_unit_id,
        "acceptable_unit_types": list(acceptable),
        "priority": priority,
        "status": "QUEUED",
        "assigned_bed_id": None,
        "match_score": None,
        "queued_ops_index": store.ops_run_index,
    }
    common.stamp_new(req)
    store.bed_requests[req["id"]] = req
    return success(common.serialize_bed_request(req), status=201)


@bp.route("/bed-requests/<req_id>", methods=["GET"])
def get_request(req_id):
    _, role = authenticate()
    authorize(role, {"FlowAdmin", "BedControlCoordinator", "TransferCenterAgent"})
    req = _get_request_or_404(req_id)
    return success(common.serialize_bed_request(req))


@bp.route("/bed-requests", methods=["GET"])
def list_requests():
    _, role = authenticate()
    authorize(role, {"FlowAdmin", "BedControlCoordinator", "TransferCenterAgent"})
    limit, offset = parse_pagination()
    enc_filter = request.args.get("encounter_id")
    pref_filter = request.args.get("preferred_unit_id")
    status_filter = request.args.get("status")
    if status_filter is not None and status_filter not in REQ_STATUSES:
        raise err(errors.ERR_INVALID_REQUEST, "invalid status filter")
    reqs = list(store.bed_requests.values())
    if enc_filter is not None:
        reqs = [r for r in reqs if r["encounter_id"] == enc_filter]
    if pref_filter is not None:
        reqs = [r for r in reqs if r.get("preferred_unit_id") == pref_filter]
    if status_filter is not None:
        reqs = [r for r in reqs if r["status"] == status_filter]
    page, total = paginate(reqs, limit, offset)
    return list_success([common.serialize_bed_request(r) for r in page], limit, offset, total)


@bp.route("/bed-requests/<req_id>/auto-place", methods=["POST"])
def auto_place(req_id):
    _, role = authenticate()
    authorize(role, {"BedControlCoordinator", "TransferCenterAgent"})
    req = _get_request_or_404(req_id)
    if req["status"] != "QUEUED":
        raise err(errors.ERR_INVALID_STATE, "Bed request is not QUEUED")
    enc = store.encounters.get(req["encounter_id"])
    bed, score = placement.select_best_bed(enc, req["acceptable_unit_types"], req["preferred_unit_id"])
    if bed is None:
        raise err(errors.ERR_NO_ELIGIBLE_BED, "No eligible bed available")
    req["status"] = "ASSIGNED"
    req["assigned_bed_id"] = bed["id"]
    req["match_score"] = score
    common.touch(req)
    return success(common.serialize_bed_request(req))


@bp.route("/bed-requests/<req_id>/assign", methods=["POST"])
def assign(req_id):
    _, role = authenticate()
    authorize(role, {"BedControlCoordinator"})
    req = _get_request_or_404(req_id)
    body = get_json_body()

    bed_id = body.get("bed_id")
    # body FK existence (priority 4) before invalid-request / state.
    if not isinstance(bed_id, str) or not bed_id:
        raise err(errors.ERR_INVALID_REQUEST, "bed_id is required")
    bed = store.beds.get(bed_id)
    if bed is None:
        raise err(errors.ERR_REFERENCE_NOT_FOUND, "bed_id does not resolve")

    if req["status"] != "QUEUED":
        raise err(errors.ERR_INVALID_STATE, "Bed request is not QUEUED")

    enc = store.encounters.get(req["encounter_id"])
    # safety checks: isolation -> telemetry -> cohort -> availability
    placement.check_bed_safety(enc, bed)

    score = placement.match_score(bed, enc, req["preferred_unit_id"])
    req["status"] = "ASSIGNED"
    req["assigned_bed_id"] = bed_id
    req["match_score"] = score
    common.touch(req)
    return success(common.serialize_bed_request(req))


@bp.route("/bed-requests/<req_id>/confirm", methods=["POST"])
def confirm(req_id):
    _, role = authenticate()
    authorize(role, {"BedControlCoordinator", "TransferCenterAgent"})
    req = _get_request_or_404(req_id)
    body = get_json_body()

    if "expected_bed_version" not in body or body.get("expected_bed_version") is None:
        raise err(errors.ERR_INVALID_REQUEST, "expected_bed_version is required")
    expected = body.get("expected_bed_version")
    if not isinstance(expected, int) or isinstance(expected, bool):
        raise err(errors.ERR_INVALID_REQUEST, "expected_bed_version must be an integer")

    if req["status"] != "ASSIGNED":
        raise err(errors.ERR_INVALID_STATE, "Bed request is not ASSIGNED")

    bed = store.beds.get(req["assigned_bed_id"])
    enc = store.encounters.get(req["encounter_id"])

    # Safety checks: isolation -> telemetry -> cohort -> availability.
    placement.check_bed_safety(enc, bed)

    # OCC guard (after the business-safety checks, per validation ordering).
    if expected != bed["version"]:
        raise err(errors.ERR_STALE_BED_VERSION, "expected_bed_version does not match bed version")

    # Encounter must be BOARDING or non-ED ADMIT_PENDING.
    if not (enc["status"] == "BOARDING"
            or (enc["status"] == "ADMIT_PENDING" and enc["origin"] != "ED")):
        raise err(errors.ERR_INVALID_STATE, "Encounter is not ready for placement")

    now = store.clock_now()
    was_boarding = enc["status"] == "BOARDING"

    # Confirm request.
    req["status"] = "CONFIRMED"
    common.touch(req)

    # Occupy bed (this bumps bed.version by 1).
    placement.occupy_bed(bed, enc)

    # Encounter -> PLACED.
    if was_boarding:
        admit_decision = enc.get("_admit_decision_dt")
        if admit_decision is not None:
            frozen = common.round2((now - admit_decision).total_seconds() / 3600.0)
        else:
            frozen = 0.00
        enc["_boarding_frozen"] = frozen
        enc["boarding_hours"] = frozen
    enc["status"] = "PLACED"
    enc["current_bed_id"] = bed["id"]
    if enc.get("_admitted_dt") is None:
        enc["_admitted_dt"] = now
        enc["admitted_at"] = iso(now)
    common.touch(enc)
    append_adt(enc["id"], "PLACE", to_bed_id=bed["id"])

    return success(common.serialize_bed_request(req))


@bp.route("/bed-requests/<req_id>/release", methods=["POST"])
def release(req_id):
    _, role = authenticate()
    authorize(role, {"BedControlCoordinator", "TransferCenterAgent"})
    req = _get_request_or_404(req_id)
    if req["status"] != "ASSIGNED":
        raise err(errors.ERR_INVALID_STATE, "Bed request is not ASSIGNED")
    req["status"] = "QUEUED"
    req["assigned_bed_id"] = None
    req["match_score"] = None
    req["queued_ops_index"] = store.ops_run_index
    common.touch(req)
    return success(common.serialize_bed_request(req))


@bp.route("/bed-requests/<req_id>/cancel", methods=["POST"])
def cancel_request(req_id):
    _, role = authenticate()
    authorize(role, {"BedControlCoordinator", "TransferCenterAgent"})
    req = _get_request_or_404(req_id)
    if req["status"] not in ("QUEUED", "ASSIGNED"):
        raise err(errors.ERR_INVALID_STATE, "Bed request cannot be cancelled from this state")
    req["status"] = "CANCELLED"
    req["assigned_bed_id"] = None
    req["match_score"] = None
    common.touch(req)
    return success(common.serialize_bed_request(req))
