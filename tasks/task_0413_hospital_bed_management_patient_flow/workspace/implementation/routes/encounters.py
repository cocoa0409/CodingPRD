"""Encounter registration + ADT lifecycle state machine, plus ADT event listing."""

from flask import Blueprint, request

import errors
from errors import err
from db import store, iso
from middleware import authenticate, authorize, get_json_body, parse_pagination
from response import success, list_success
from services import common, placement
from services.adt import append_adt
from services.listing import paginate

bp = Blueprint("encounters", __name__)

SEXES = {"MALE", "FEMALE"}
ORIGINS = {"ED", "DIRECT", "TRANSFER_IN"}
ENC_STATUSES = {"REGISTERED", "ADMIT_PENDING", "BOARDING", "PLACED",
                "DISCHARGE_ORDERED", "DISCHARGED", "CANCELLED"}


def _get_encounter_or_404(enc_id):
    enc = store.encounters.get(enc_id)
    if enc is None:
        raise err(errors.ERR_NOT_FOUND, "Encounter not found")
    return enc


def _cancel_open_bed_requests(encounter_id):
    for req in store.bed_requests.values():
        if req["encounter_id"] == encounter_id and req["status"] in ("QUEUED", "ASSIGNED"):
            req["status"] = "CANCELLED"
            req["assigned_bed_id"] = None
            req["match_score"] = None
            common.touch(req)


# ---------------------------------------------------------------------------
# Registration + reads
# ---------------------------------------------------------------------------
@bp.route("/encounters", methods=["POST"])
def create_encounter():
    _, role = authenticate()
    authorize(role, {"BedControlCoordinator", "TransferCenterAgent", "FlowAdmin"})
    body = get_json_body()

    mrn = body.get("mrn")
    sex = body.get("sex")
    if not isinstance(mrn, str) or not mrn:
        raise err(errors.ERR_INVALID_REQUEST, "mrn is required")
    if sex not in SEXES:
        raise err(errors.ERR_INVALID_REQUEST, "sex must be MALE or FEMALE")

    requires_iso = body.get("requires_isolation", False)
    requires_tele = body.get("requires_telemetry", False)
    if requires_iso is None:
        requires_iso = False
    if requires_tele is None:
        requires_tele = False
    if not isinstance(requires_iso, bool):
        raise err(errors.ERR_INVALID_REQUEST, "requires_isolation must be boolean")
    if not isinstance(requires_tele, bool):
        raise err(errors.ERR_INVALID_REQUEST, "requires_telemetry must be boolean")

    origin = body.get("origin", "ED")
    if origin is None:
        origin = "ED"
    if origin not in ORIGINS:
        raise err(errors.ERR_INVALID_REQUEST, "origin must be ED, DIRECT, or TRANSFER_IN")

    enc = {
        "mrn": mrn,
        "sex": sex,
        "requires_isolation": requires_iso,
        "requires_telemetry": requires_tele,
        "origin": origin,
        "status": "REGISTERED",
        "current_bed_id": None,
        "transferred_from_bed_id": None,
        "admit_decision_at": None,
        "admitted_at": None,
        "discharge_order_at": None,
        "discharged_at": None,
        "boarding_hours": 0.00,
        "boarding_breached": False,
        "length_of_stay_hours": 0.00,
        "long_stay_flag": False,
        "open_barrier_count": 0,
        # private clock anchors
        "_admit_decision_dt": None,
        "_admitted_dt": None,
        "_discharged_dt": None,
        "_boarding_frozen": None,
        "_last_bed_id": None,
    }
    common.stamp_new(enc)
    store.encounters[enc["id"]] = enc
    return success(common.serialize_encounter(enc), status=201)


@bp.route("/encounters/<enc_id>", methods=["GET"])
def get_encounter(enc_id):
    _, role = authenticate()
    authorize(role, {"FlowAdmin", "BedControlCoordinator", "ChargeNurse",
                     "TransferCenterAgent", "CaseManager"})
    enc = _get_encounter_or_404(enc_id)
    return success(common.serialize_encounter(enc))


@bp.route("/encounters", methods=["GET"])
def list_encounters():
    _, role = authenticate()
    authorize(role, {"FlowAdmin", "BedControlCoordinator", "ChargeNurse",
                     "TransferCenterAgent", "CaseManager"})
    limit, offset = parse_pagination()
    status_filter = request.args.get("status")
    if status_filter is not None and status_filter not in ENC_STATUSES:
        raise err(errors.ERR_INVALID_REQUEST, "invalid status filter")
    encs = list(store.encounters.values())
    if status_filter is not None:
        encs = [e for e in encs if e["status"] == status_filter]
    page, total = paginate(encs, limit, offset)
    return list_success([common.serialize_encounter(e) for e in page], limit, offset, total)


# ---------------------------------------------------------------------------
# ADT transitions
# ---------------------------------------------------------------------------
@bp.route("/encounters/<enc_id>/admit-order", methods=["POST"])
def admit_order(enc_id):
    _, role = authenticate()
    authorize(role, {"BedControlCoordinator", "FlowAdmin"})
    enc = _get_encounter_or_404(enc_id)
    if enc["status"] != "REGISTERED":
        raise err(errors.ERR_INVALID_STATE, "Encounter is not REGISTERED")
    now = store.clock_now()
    enc["status"] = "ADMIT_PENDING"
    enc["admit_decision_at"] = iso(now)
    enc["_admit_decision_dt"] = now
    common.touch(enc)
    append_adt(enc["id"], "ADMIT")
    # ED origin auto-advances to BOARDING
    if enc["origin"] == "ED":
        enc["status"] = "BOARDING"
        common.touch(enc)
    return success(common.serialize_encounter(enc))


@bp.route("/encounters/<enc_id>/start-boarding", methods=["POST"])
def start_boarding(enc_id):
    _, role = authenticate()
    authorize(role, {"BedControlCoordinator"})
    enc = _get_encounter_or_404(enc_id)
    if enc["status"] != "ADMIT_PENDING" or enc["origin"] != "ED":
        raise err(errors.ERR_INVALID_STATE, "Encounter is not an ADMIT_PENDING ED encounter")
    enc["status"] = "BOARDING"
    common.touch(enc)
    return success(common.serialize_encounter(enc))


@bp.route("/encounters/<enc_id>/transfer", methods=["POST"])
def transfer(enc_id):
    _, role = authenticate()
    authorize(role, {"BedControlCoordinator"})
    enc = _get_encounter_or_404(enc_id)
    body = get_json_body()

    target_bed_id = body.get("target_bed_id")
    if not isinstance(target_bed_id, str) or not target_bed_id:
        raise err(errors.ERR_INVALID_REQUEST, "target_bed_id is required")

    # State legality before business checks.
    if enc["status"] != "PLACED":
        raise err(errors.ERR_INVALID_STATE, "Encounter is not PLACED")

    target_bed = store.beds.get(target_bed_id)
    if target_bed is None:
        # body FK -> reference-not-found
        raise err(errors.ERR_REFERENCE_NOT_FOUND, "target_bed_id does not resolve")

    # Safety checks: isolation -> telemetry -> cohort -> availability.
    placement.check_bed_safety(enc, target_bed)
    # same-bed check (after availability per validation order 13<14)
    if enc["current_bed_id"] == target_bed_id:
        raise err(errors.ERR_SAME_BED, "Transfer target equals current bed")

    old_bed = store.beds.get(enc["current_bed_id"])
    enc["transferred_from_bed_id"] = enc["current_bed_id"]
    # old bed -> DIRTY (auto EvsTask)
    if old_bed is not None:
        placement.vacate_bed(old_bed, enc)
    # target -> OCCUPIED
    placement.occupy_bed(target_bed, enc)
    enc["current_bed_id"] = target_bed_id
    common.touch(enc)
    append_adt(enc["id"], "TRANSFER",
               from_bed_id=enc["transferred_from_bed_id"], to_bed_id=target_bed_id)
    return success(common.serialize_encounter(enc))


@bp.route("/encounters/<enc_id>/discharge-order", methods=["POST"])
def discharge_order(enc_id):
    _, role = authenticate()
    authorize(role, {"CaseManager", "BedControlCoordinator"})
    enc = _get_encounter_or_404(enc_id)
    if enc["status"] != "PLACED":
        raise err(errors.ERR_INVALID_STATE, "Encounter is not PLACED")
    now = store.clock_now()
    enc["status"] = "DISCHARGE_ORDERED"
    enc["discharge_order_at"] = iso(now)
    enc["_discharge_order_dt"] = now
    common.touch(enc)
    append_adt(enc["id"], "DISCHARGE_ORDER")
    return success(common.serialize_encounter(enc))


@bp.route("/encounters/<enc_id>/rescind-discharge", methods=["POST"])
def rescind_discharge(enc_id):
    _, role = authenticate()
    authorize(role, {"CaseManager", "BedControlCoordinator"})
    enc = _get_encounter_or_404(enc_id)
    if enc["status"] != "DISCHARGE_ORDERED":
        raise err(errors.ERR_INVALID_STATE, "Encounter is not DISCHARGE_ORDERED")
    enc["status"] = "PLACED"
    enc["discharge_order_at"] = None
    enc["_discharge_order_dt"] = None
    common.touch(enc)
    return success(common.serialize_encounter(enc))


@bp.route("/encounters/<enc_id>/discharge", methods=["POST"])
def discharge(enc_id):
    _, role = authenticate()
    authorize(role, {"CaseManager", "BedControlCoordinator"})
    enc = _get_encounter_or_404(enc_id)
    if enc["status"] != "DISCHARGE_ORDERED":
        raise err(errors.ERR_INVALID_STATE, "Encounter is not DISCHARGE_ORDERED")
    # business gate: zero open barriers
    common.recompute_encounter(enc)
    if enc["open_barrier_count"] != 0:
        raise err(errors.ERR_OPEN_BARRIERS, "Open discharge barriers remain")
    now = store.clock_now()
    bed = store.beds.get(enc["current_bed_id"])
    enc["status"] = "DISCHARGED"
    enc["discharged_at"] = iso(now)
    enc["_discharged_dt"] = now
    if enc["current_bed_id"] is not None:
        enc["_last_bed_id"] = enc["current_bed_id"]
    if bed is not None:
        placement.vacate_bed(bed, enc)
    enc["current_bed_id"] = None
    common.touch(enc)
    append_adt(enc["id"], "DISCHARGE", from_bed_id=enc["_last_bed_id"])
    return success(common.serialize_encounter(enc))


@bp.route("/encounters/<enc_id>/cancel", methods=["POST"])
def cancel_encounter(enc_id):
    _, role = authenticate()
    authorize(role, {"BedControlCoordinator", "FlowAdmin"})
    enc = _get_encounter_or_404(enc_id)
    if enc["status"] not in ("REGISTERED", "ADMIT_PENDING", "BOARDING"):
        raise err(errors.ERR_INVALID_STATE, "Encounter cannot be cancelled from this state")
    prior = enc["status"]
    enc["status"] = "CANCELLED"
    common.touch(enc)
    if prior in ("ADMIT_PENDING", "BOARDING"):
        _cancel_open_bed_requests(enc["id"])
    append_adt(enc["id"], "CANCEL")
    return success(common.serialize_encounter(enc))


# ---------------------------------------------------------------------------
# ADT event listing (nested under encounter)
# ---------------------------------------------------------------------------
@bp.route("/encounters/<enc_id>/adt-events", methods=["GET"])
def list_adt_events(enc_id):
    _, role = authenticate()
    authorize(role, {"FlowAdmin", "BedControlCoordinator", "CaseManager"})
    _get_encounter_or_404(enc_id)
    limit, offset = parse_pagination()
    events = [e for e in store.adt_events.values() if e["encounter_id"] == enc_id]
    page, total = paginate(events, limit, offset)
    return list_success([common.serialize_adt(e) for e in page], limit, offset, total)
