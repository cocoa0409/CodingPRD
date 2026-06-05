"""AccessSession endpoints: open (gate entry), read, exit, void.

Gate admission ordering (PRD §2.9):
  existence -> zone-type -> stall occupancy -> gate admission.
Exit ordering: state -> time-range -> validation redeemability.
"""
from __future__ import annotations

from flask import Blueprint

import db
from errors import (
    APIError,
    ERR_GATE_CLOSED,
    ERR_INVALID_STATE,
    ERR_INVALID_TIME_RANGE,
    ERR_SPACE_OCCUPIED,
    ERR_VALIDATION_NOT_REDEEMABLE,
    ERR_ZONE_TYPE_FORBIDDEN,
)
from middleware import get_json_body, require_auth
from response import ok_object
from services import calculations, recompute
from services.common import (
    lookup,
    normalize_plate,
    require_datetime,
    require_string,
)
from services.serialize import public

bp = Blueprint("sessions", __name__)


def _active_permit_for_plate_in_garage(plate: str, garage_id: str):
    """Return any ACTIVE permit bound to plate whose zone is in the garage."""
    for p in db.permits.values():
        if p["plate"] == plate and p["status"] == "ACTIVE":
            z = db.zones.get(p["zone_id"])
            if z is not None and z["garage_id"] == garage_id:
                return p
    return None


def _zones_of_garage(garage_id: str):
    zs = [z for z in db.zones.values() if z["garage_id"] == garage_id]
    return sorted(zs, key=lambda z: z["_seq"])


def _select_space_in_zone(zone_id: str):
    """First AVAILABLE + unoccupied space in the zone (creation order)."""
    cand = [
        s
        for s in db.spaces.values()
        if s["zone_id"] == zone_id and s["status"] == "AVAILABLE" and not s.get("is_occupied")
    ]
    cand.sort(key=lambda s: s["_seq"])
    return cand[0] if cand else None


@bp.post("/parking/sessions")
def open_session():
    require_auth(["FacilityAdmin"])()
    body = get_json_body()
    garage_id = require_string(body, "garage_id")
    plate_raw = require_string(body, "plate")
    entry_at_utc = require_datetime(body, "entry_at_utc", required=True)
    permit_id = body.get("permit_id")

    plate = normalize_plate(plate_raw)

    garage = lookup(db.garages, garage_id)
    permit = None
    if permit_id is not None:
        permit = lookup(db.permits, permit_id)

    # Classify PERMIT vs TRANSIENT. A session is PERMIT when admitted under a
    # valid ACTIVE permit (bound to the plate, in this garage).
    is_permit = False
    chosen_zone = None
    if permit is not None and permit["status"] == "ACTIVE" and permit["plate"] == plate:
        z = db.zones.get(permit["zone_id"])
        if z is not None and z["garage_id"] == garage_id:
            is_permit = True
            chosen_zone = z

    # ---- gate-mode admission (PRD §3.5) ----
    # CLOSED rejects all; PERMIT_ONLY rejects without a valid ACTIVE permit.
    # Zone-type is checked before occupancy before gate per §2.9; but gate
    # CLOSED is unconditional. We evaluate in the §2.9 order: zone-type ->
    # occupancy -> gate. However gate_mode==CLOSED forbids everything, so it is
    # a gate-admission concern (priority 11) evaluated after stall occupancy.

    if is_permit:
        # PERMIT session parks in the permit's zone.
        # Zone-type for a PERMIT zone is implicitly fine (PERMIT or MIXED).
        zone_for_space = chosen_zone
        # stall occupancy
        space = _select_space_in_zone(zone_for_space["id"])
        if space is None:
            raise APIError(ERR_SPACE_OCCUPIED, 409, "No available space in the permit zone")
        # gate admission
        if garage["gate_mode"] == "CLOSED":
            raise APIError(ERR_GATE_CLOSED, 409, "Garage gate is CLOSED")
        # PERMIT_ONLY is satisfied (valid permit present).
        session_kind = "PERMIT"
        chosen_space = space
    else:
        # TRANSIENT session. Eligible zones are TRANSIENT or MIXED.
        eligible = [z for z in _zones_of_garage(garage_id) if z["zone_type"] in ("TRANSIENT", "MIXED")]
        if not eligible:
            # No transient-eligible zone -> zone-type forbidden (priority 6).
            raise APIError(ERR_ZONE_TYPE_FORBIDDEN, 409, "No transient-eligible zone in this garage")

        # stall occupancy (priority 10): find a zone with a free space.
        chosen_space = None
        zone_for_space = None
        for z in eligible:
            sp = _select_space_in_zone(z["id"])
            if sp is not None:
                chosen_space = sp
                zone_for_space = z
                break
        if chosen_space is None:
            raise APIError(ERR_SPACE_OCCUPIED, 409, "No available space in an eligible zone")

        # gate admission (priority 11)
        if garage["gate_mode"] == "CLOSED":
            raise APIError(ERR_GATE_CLOSED, 409, "Garage gate is CLOSED")
        if garage["gate_mode"] == "PERMIT_ONLY":
            # Reject transient entries without a valid ACTIVE permit for plate.
            if _active_permit_for_plate_in_garage(plate, garage_id) is None:
                raise APIError(ERR_GATE_CLOSED, 409, "Garage is PERMIT_ONLY and plate has no active permit")
        session_kind = "TRANSIENT"

    # ---- side effects ----
    s = db.stamp_common(
        {
            "garage_id": garage_id,
            "space_id": chosen_space["id"],
            "permit_id": permit_id if is_permit else None,
            "plate": plate,
            "entry_at_utc": entry_at_utc,
            "exit_at_utc": None,
            "status": "OPEN",
            "session_kind": session_kind,
            "gross_charge_cents": 0,
            "validation_id": None,
            "net_charge_cents": 0,
        }
    )
    db.sessions[s["id"]] = s

    recompute.set_space_occupied(chosen_space, True, bump=True)
    recompute.recompute_garage_counts(garage, bump=True)

    return ok_object(public(s), 201)


@bp.get("/parking/sessions/<sid>")
def read_session(sid):
    require_auth(["FacilityAdmin", "EnforcementOfficer", "Motorist"])()
    s = lookup(db.sessions, sid)
    return ok_object(public(s), 200)


@bp.post("/parking/sessions/<sid>/exit")
def exit_session(sid):
    require_auth(["FacilityAdmin"])()
    s = lookup(db.sessions, sid)
    body = get_json_body()
    exit_at_utc = require_datetime(body, "exit_at_utc", required=True)
    validation_id = body.get("validation_id")

    validation = None
    if validation_id is not None:
        validation = lookup(db.validations, validation_id)

    # state (priority 4)
    if s["status"] != "OPEN":
        raise APIError(ERR_INVALID_STATE, 409, "Session is not OPEN")

    # time range (exit strictly after entry)
    entry_dt = db.parse_iso_dt(s["entry_at_utc"])
    exit_dt = db.parse_iso_dt(exit_at_utc)
    if exit_dt <= entry_dt:
        raise APIError(ERR_INVALID_TIME_RANGE, 409, "exit_at_utc must be strictly after entry_at_utc")

    # validation redeemability (priority 8)
    if validation is not None:
        ok = (
            validation["status"] == "ISSUED"
            and validation["garage_id"] == s["garage_id"]
            and exit_dt < db.parse_iso_dt(validation["expires_at_utc"])
        )
        if not ok:
            raise APIError(ERR_VALIDATION_NOT_REDEEMABLE, 409, "Validation is not redeemable")

    # ---- compute charges ----
    space = db.spaces.get(s["space_id"])
    zone = db.zones.get(space["zone_id"]) if space is not None else None
    rate_plan = db.rate_plans.get(zone["rate_plan_id"]) if zone is not None else None

    s["exit_at_utc"] = exit_at_utc

    if s["session_kind"] == "PERMIT":
        gross = 0
    else:
        gross = calculations.transient_charge(s, rate_plan)
    s["gross_charge_cents"] = gross

    net = gross
    applied_discount = 0
    if s["session_kind"] == "TRANSIENT" and validation is not None:
        merchant = db.merchants.get(validation["merchant_id"])
        res = calculations.validation_discount(gross, validation, merchant, rate_plan)
        applied_discount = res["applied_discount"]
        net = res["net"]
    s["net_charge_cents"] = net

    if validation is not None and s["session_kind"] == "TRANSIENT":
        s["validation_id"] = validation_id

    s["status"] = "CLOSED"
    db.bump(s)

    # free the space + recompute garage occupancy
    if space is not None:
        recompute.set_space_occupied(space, False, bump=True)
    garage = db.garages.get(s["garage_id"])
    if garage is not None:
        recompute.recompute_garage_counts(garage, bump=True)

    # validation redemption + merchant budget debit (cascade T2)
    if applied_discount > 0 and validation is not None:
        validation["status"] = "REDEEMED"
        db.bump(validation)
        merchant = db.merchants.get(validation["merchant_id"])
        if merchant is not None:
            merchant["validation_budget_cents"] -= applied_discount
            db.bump(merchant)

    return ok_object(public(s), 200)


@bp.post("/parking/sessions/<sid>/void")
def void_session(sid):
    require_auth(["FacilityAdmin"])()
    s = lookup(db.sessions, sid)
    if s["status"] != "OPEN":
        raise APIError(ERR_INVALID_STATE, 409, "Session is not OPEN")

    s["status"] = "VOIDED"
    db.bump(s)

    space = db.spaces.get(s["space_id"])
    if space is not None:
        recompute.set_space_occupied(space, False, bump=True)
    garage = db.garages.get(s["garage_id"])
    if garage is not None:
        recompute.recompute_garage_counts(garage, bump=True)

    return ok_object(public(s), 200)
