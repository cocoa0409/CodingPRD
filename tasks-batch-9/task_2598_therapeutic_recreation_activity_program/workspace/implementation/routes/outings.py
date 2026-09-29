"""Outings: transport, seats, escorts and the consent dimension (PRD 3.8)."""
from flask import Blueprint

import serializers
from db import date_str, iso, parse_datetime, store
from errors import ApiError
from helpers import ctx, load, new_entity, paginate, resolve_fk
from middleware import (
    ROLE_ACTIVITY_AIDE,
    ROLE_ACTIVITY_DIRECTOR,
    ROLE_COMPLIANCE_OFFICER,
    ROLE_RECREATION_THERAPIST,
    authorize,
    filter_arg,
    pagination,
)
from response import list_response, object_response
from services import clinical
from services import constants as C
from services import outings as outing_svc
from validation import read_body, validate

bp = Blueprint("outings", __name__)

READ_ROLES = (
    ROLE_ACTIVITY_DIRECTOR,
    ROLE_RECREATION_THERAPIST,
    ROLE_ACTIVITY_AIDE,
    ROLE_COMPLIANCE_OFFICER,
)

CREATE_SPEC = {
    "program_id": {"type": "id", "required": True},
    "vehicle_id": {"type": "id", "required": True},
    "destination": {"type": "string", "max_len": 160, "required": True},
    "departure_at": {"type": "datetime", "required": True},
    "return_at": {"type": "datetime", "required": True},
    "escort_count": {"type": "int", "min": 0, "max": 20, "required": True},
}

BOOKING_SPEC = {
    "expected_vehicle_version": {"type": "int", "min": 0, "required": True},
}

LOGISTICS_SPEC = {
    "action": {
        "type": "enum",
        "values": ["SET_ESCORTS", "FINALIZE", "DEPART", "RETURN", "CANCEL"],
        "required": True,
    },
    "escort_count": {"type": "int", "min": 0, "max": 20},
    "cancel_reason": {"type": "string", "max_len": 300},
}

CONSENT_SPEC = {
    "resident_id": {"type": "id", "required": True},
    "responsible_party_name": {"type": "string", "max_len": 120, "required": True},
    "responsible_party_relation": {
        "type": "enum",
        "values": C.CONSENT_RELATIONS,
        "required": True,
    },
    "expires_on": {"type": "date"},
}

DECISION_SPEC = {
    "decision": {
        "type": "enum",
        "values": ["GRANTED", "DENIED", "REVOKED"],
        "required": True,
    },
    "expires_on": {"type": "date"},
}

DECISION_SOURCES = {
    "GRANTED": ("REQUESTED", "REVOKED", "DENIED"),
    "DENIED": ("REQUESTED",),
    "REVOKED": ("GRANTED",),
}

LOGISTICS_SOURCES = {
    "SET_ESCORTS": ("PLANNING", "TRANSPORT_BOOKED"),
    "FINALIZE": ("TRANSPORT_BOOKED",),
    "DEPART": ("READY",),
    "RETURN": ("DEPARTED",),
    "CANCEL": ("PLANNING", "TRANSPORT_BOOKED", "READY"),
}


@bp.post("/outings")
def create_outing():
    authorize(ROLE_ACTIVITY_DIRECTOR, ROLE_RECREATION_THERAPIST)
    body = read_body()
    program = resolve_fk(body, "program_id", "program")
    vehicle = resolve_fk(body, "vehicle_id", "vehicle")
    values = validate(body, CREATE_SPEC)
    departure_at = values["departure_at"]
    return_at = values["return_at"]
    if return_at <= departure_at:
        raise ApiError("ERR_TIME_WINDOW_INVALID")
    if departure_at < store.now():
        raise ApiError("ERR_SESSION_IN_PAST")

    context = ctx()
    outing = new_entity(
        {
            "program_id": program["id"],
            "vehicle_id": vehicle["id"],
            "destination": values["destination"],
            "departure_at": iso(departure_at),
            "return_at": iso(return_at),
            "escort_count": values["escort_count"],
            "logistics_status": "PLANNING",
            "consent_status": "COLLECTING",
            "roster_count": 0,
            "manifest_count": 0,
            "weighted_supervision_load": 0.0,
            "required_escorts": 0,
            "ambulatory_seats_required": 0,
            "wheelchair_seats_required": 0,
            "seat_shortfall_total": 0,
            "departed_at": None,
            "returned_at": None,
            "cancel_reason": None,
        }
    )
    store.outings[outing["id"]] = outing
    # The supervision requirement runs once over the empty manifest.
    outing_svc.apply_supervision(store, outing, context)
    return object_response(serializers.outing(outing), 201)


@bp.get("/outings/<outing_id>")
def get_outing(outing_id):
    authorize(*READ_ROLES)
    outing = load("outing", outing_id)
    return object_response(serializers.outing(outing), 200)


@bp.get("/outings")
def list_outings():
    authorize(*READ_ROLES)
    limit, offset = pagination()
    program_id = filter_arg("program_id")
    vehicle_id = filter_arg("vehicle_id")
    logistics_status = filter_arg("logistics_status")
    consent_status = filter_arg("consent_status")
    rows = list(store.outings.values())
    if program_id:
        rows = [o for o in rows if o["program_id"] == program_id]
    if vehicle_id:
        rows = [o for o in rows if o["vehicle_id"] == vehicle_id]
    if logistics_status:
        rows = [o for o in rows if o["logistics_status"] == logistics_status]
    if consent_status:
        rows = [o for o in rows if o["consent_status"] == consent_status]
    rows.sort(key=lambda o: (o["departure_at"], o["created_at"], o["_seq"]))
    page, total = paginate(rows, limit, offset)
    return list_response([serializers.outing(o) for o in page], limit, offset, total)


@bp.post("/outings/<outing_id>/transport-booking")
def book_transport(outing_id):
    authorize(ROLE_ACTIVITY_DIRECTOR)
    body = read_body()
    outing = load("outing", outing_id)
    values = validate(body, BOOKING_SPEC)
    # Rank 13: booking is admitted only from PLANNING.
    if outing["logistics_status"] != "PLANNING":
        raise ApiError("ERR_OUTING_INVALID_STATE")
    vehicle = store.vehicles.get(outing["vehicle_id"])
    if vehicle is None:
        raise ApiError("ERR_VEHICLE_NOT_FOUND")
    # Rank 20: optimistic concurrency on the vehicle.
    if values["expected_vehicle_version"] != vehicle["version"]:
        raise ApiError("ERR_STALE_VEHICLE_VERSION")
    # Rank 26: the turnaround-widened interval must be clear.
    if outing_svc.vehicle_conflict(store, vehicle, outing) is not None:
        raise ApiError("ERR_VEHICLE_TIME_CONFLICT")
    # Rank 48: the vehicle must be in service at booking time.
    if vehicle["status"] != "AVAILABLE":
        raise ApiError("ERR_VEHICLE_OUT_OF_SERVICE")
    # Rank 52: the seat waterfall must come out even.
    allocation = outing_svc.seat_allocation(store, outing)
    if allocation["seat_shortfall_total"] != 0:
        raise ApiError("ERR_VEHICLE_CAPACITY_EXCEEDED")

    context = ctx()
    for key, value in allocation.items():
        outing[key] = value
    outing["logistics_status"] = "TRANSPORT_BOOKED"
    context.bump(outing)
    outing_svc.recompute_vehicle_reservations(store, vehicle, context, force_bump=True)
    return object_response(serializers.outing(outing), 200)


@bp.post("/outings/<outing_id>/logistics")
def drive_logistics(outing_id):
    authorize(ROLE_ACTIVITY_DIRECTOR)
    body = read_body()
    outing = load("outing", outing_id)
    values = validate(body, LOGISTICS_SPEC)
    action = values["action"]
    if action == "SET_ESCORTS" and values["escort_count"] is None:
        raise ApiError(
            "ERR_INVALID_REQUEST", "escort_count is required for SET_ESCORTS."
        )
    if action != "SET_ESCORTS" and values["escort_count"] is not None:
        raise ApiError(
            "ERR_INVALID_REQUEST", "escort_count is only accepted for SET_ESCORTS."
        )
    if action == "CANCEL" and values["cancel_reason"] is None:
        raise ApiError("ERR_INVALID_REQUEST", "cancel_reason is required for CANCEL.")
    if action != "CANCEL" and values["cancel_reason"] is not None:
        raise ApiError(
            "ERR_INVALID_REQUEST", "cancel_reason is only accepted for CANCEL."
        )

    # Rank 13: the action must be declared for the current logistics_status.
    if outing["logistics_status"] not in LOGISTICS_SOURCES[action]:
        raise ApiError("ERR_OUTING_INVALID_STATE")

    vehicle = store.vehicles.get(outing["vehicle_id"])
    context = ctx()

    if action == "SET_ESCORTS":
        outing["escort_count"] = values["escort_count"]
        outing_svc.apply_supervision(store, outing, context)
        outing_svc.apply_seat_allocation(store, outing, context)
        if outing["logistics_status"] == "TRANSPORT_BOOKED" and vehicle is not None:
            outing_svc.recompute_vehicle_reservations(
                store, vehicle, context, force_bump=True
            )
    elif action == "FINALIZE":
        # Rank 35 before rank 36: escorts first, consent second.
        if outing["escort_count"] < outing["required_escorts"]:
            raise ApiError("ERR_SUPERVISION_RATIO_UNMET")
        if outing["consent_status"] != "CONSENT_COMPLETE" or not (
            outing_svc.manifest_all_effective(store, outing)
        ):
            raise ApiError("ERR_CONSENT_INCOMPLETE")
        outing["logistics_status"] = "READY"
    elif action == "DEPART":
        if store.now() < parse_datetime(outing["departure_at"]):
            raise ApiError("ERR_OUTING_INVALID_STATE")
        if outing["consent_status"] != "CONSENT_COMPLETE" or not (
            outing_svc.manifest_all_effective(store, outing)
        ):
            raise ApiError("ERR_CONSENT_INCOMPLETE")
        outing["logistics_status"] = "DEPARTED"
        outing["departed_at"] = store.now_iso()
    elif action == "RETURN":
        departed_at = parse_datetime(outing["departed_at"])
        if departed_at is not None and store.now() < departed_at:
            raise ApiError("ERR_OUTING_INVALID_STATE")
        outing["logistics_status"] = "RETURNED"
        outing["returned_at"] = store.now_iso()
        if vehicle is not None:
            outing_svc.recompute_vehicle_reservations(
                store, vehicle, context, force_bump=True
            )
    else:
        released = outing["logistics_status"] in ("TRANSPORT_BOOKED", "READY")
        outing["logistics_status"] = "CANCELLED"
        outing["cancel_reason"] = values["cancel_reason"]
        if released and vehicle is not None:
            outing_svc.recompute_vehicle_reservations(
                store, vehicle, context, force_bump=True
            )

    context.bump(outing)
    return object_response(serializers.outing(outing), 200)


def _refresh_consent_dimension(outing, context):
    """Re-derive the consent axis, then the supervision requirement.

    The seat requirement is only recomputed by consent activity while the outing
    is already TRANSPORT_BOOKED; no seat is reserved at planning time.
    """
    outing_svc.recompute_counts(store, outing, context)
    derived = outing_svc.derive_consent_status(store, outing)
    outing["consent_status"] = derived
    if derived != "CONSENT_COMPLETE" and outing["logistics_status"] == "READY":
        # The only backwards move in the logistics dimension.
        outing["logistics_status"] = "TRANSPORT_BOOKED"
    outing_svc.apply_supervision(store, outing, context)
    if outing["logistics_status"] == "TRANSPORT_BOOKED":
        outing_svc.apply_seat_allocation(store, outing, context)


@bp.post("/outings/<outing_id>/consents")
def add_rider(outing_id):
    authorize(ROLE_ACTIVITY_DIRECTOR, ROLE_RECREATION_THERAPIST, ROLE_ACTIVITY_AIDE)
    body = read_body()
    outing = load("outing", outing_id)
    resident = resolve_fk(body, "resident_id", "resident")
    values = validate(body, CONSENT_SPEC)

    # Rank 13: consent collection closes once the bus is out or the trip is off.
    if outing["logistics_status"] in outing_svc.CLOSED_LOGISTICS:
        raise ApiError("ERR_OUTING_INVALID_STATE")
    # Rank 28 / 29: only an admitted, assessed resident may ride.
    if resident["status"] != "ADMITTED":
        raise ApiError("ERR_RESIDENT_NOT_ADMITTED")
    if not clinical.resident_assessments(store, resident["id"]):
        raise ApiError("ERR_NO_ACTIVE_ASSESSMENT")
    # Rank 37: a bedbound resident may never join a manifest.
    if resident.get("functional_mobility") == "BEDBOUND":
        raise ApiError("ERR_RESIDENT_INELIGIBLE_FOR_OUTING")
    # Rank 46: one consent row per resident per outing, in any status at all.
    for row in outing_svc.outing_consents(store, outing["id"]):
        if row["resident_id"] == resident["id"]:
            raise ApiError("ERR_DUPLICATE_CONSENT")

    context = ctx()
    expires_on = values["expires_on"]
    consent = new_entity(
        {
            "outing_id": outing["id"],
            "resident_id": resident["id"],
            "responsible_party_name": values["responsible_party_name"],
            "responsible_party_relation": values["responsible_party_relation"],
            "status": "REQUESTED",
            "expires_on": date_str(expires_on) if expires_on is not None else None,
            "decided_at": None,
        }
    )
    store.consents[consent["id"]] = consent
    _refresh_consent_dimension(outing, context)
    context.bump(outing)
    return object_response(serializers.consent(consent), 201)


@bp.post("/outings/<outing_id>/consents/<consent_id>/decision")
def decide_consent(outing_id, consent_id):
    authorize(ROLE_ACTIVITY_DIRECTOR, ROLE_RECREATION_THERAPIST, ROLE_ACTIVITY_AIDE)
    body = read_body()
    outing = load("outing", outing_id)
    consent = load("consent", consent_id)
    # Rank 7: nested-child ownership is a 404 on the child, never a 403.
    if consent["outing_id"] != outing["id"]:
        raise ApiError("ERR_CONSENT_NOT_FOUND")
    values = validate(body, DECISION_SPEC)
    decision = values["decision"]

    # Rank 13: no decision lands once the bus is out or the trip is off.
    if outing["logistics_status"] in outing_svc.CLOSED_LOGISTICS:
        raise ApiError("ERR_OUTING_INVALID_STATE")
    # Rank 14: the pairing must be declared.
    if consent["status"] not in DECISION_SOURCES[decision]:
        raise ApiError("ERR_CONSENT_INVALID_STATE")

    context = ctx()
    consent["status"] = decision
    consent["decided_at"] = store.now_iso()
    if decision == "GRANTED":
        expires_on = values["expires_on"]
        consent["expires_on"] = (
            date_str(expires_on) if expires_on is not None else None
        )
    context.bump(consent)

    _refresh_consent_dimension(outing, context)
    vehicle = store.vehicles.get(outing["vehicle_id"])
    if vehicle is not None:
        if outing["logistics_status"] == "TRANSPORT_BOOKED":
            outing_svc.recompute_vehicle_reservations(
                store, vehicle, context, force_bump=True
            )
        elif outing["logistics_status"] in C.RESERVING_LOGISTICS:
            outing_svc.recompute_vehicle_reservations(store, vehicle, context)
    context.bump(outing)
    return object_response(serializers.consent(consent), 200)


@bp.get("/outings/<outing_id>/consents")
def list_outing_consents(outing_id):
    authorize(*READ_ROLES)
    outing = load("outing", outing_id)
    limit, offset = pagination()
    status = filter_arg("status")
    rows = outing_svc.outing_consents(store, outing["id"])
    if status:
        rows = [c for c in rows if c["status"] == status]
    rows.sort(key=lambda c: (c["created_at"], c["_seq"]))
    page, total = paginate(rows, limit, offset)
    return list_response([serializers.consent(c) for c in page], limit, offset, total)


@bp.get("/outing-consents/<consent_id>")
def get_consent(consent_id):
    authorize(*READ_ROLES)
    consent = load("consent", consent_id)
    return object_response(serializers.consent(consent), 200)


@bp.get("/outing-consents")
def list_consents():
    authorize(*READ_ROLES)
    limit, offset = pagination()
    resident_id = filter_arg("resident_id")
    outing_id = filter_arg("outing_id")
    status = filter_arg("status")
    rows = list(store.consents.values())
    if resident_id:
        rows = [c for c in rows if c["resident_id"] == resident_id]
    if outing_id:
        rows = [c for c in rows if c["outing_id"] == outing_id]
    if status:
        rows = [c for c in rows if c["status"] == status]
    rows.sort(key=lambda c: (c["created_at"], c["_seq"]))
    page, total = paginate(rows, limit, offset)
    return list_response([serializers.consent(c) for c in page], limit, offset, total)
