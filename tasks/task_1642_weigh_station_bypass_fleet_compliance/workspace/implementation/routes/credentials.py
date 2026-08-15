"""Bypass credential routes (PRD 3.4). Activation is the choke point: gates in
pinned order are carrier ACTIVE -> posture ELIGIBLE/CONDITIONAL -> vehicle
IN_SERVICE -> covering subscription -> past-due standing."""
from datetime import date

from flask import Blueprint

import db
from db import store
from errors import ApiError
from middleware import (
    body_json,
    ctx,
    list_response,
    need_enum,
    need_str,
    ownership_guard,
    require_role,
)
from response import ok

bp = Blueprint("credentials", __name__)

DEVICE_TYPES = ("TRANSPONDER", "MOBILE_APP")
CRED_TARGETS = ("ACTIVE", "SUSPENDED", "DEACTIVATED")
NON_TERMINAL = ("PROVISIONED", "ACTIVE", "SUSPENDED")

_LEGAL = {
    ("PROVISIONED", "ACTIVE"),
    ("ACTIVE", "SUSPENDED"),
    ("SUSPENDED", "ACTIVE"),
    ("PROVISIONED", "DEACTIVATED"),
    ("ACTIVE", "DEACTIVATED"),
    ("SUSPENDED", "DEACTIVATED"),
}


@bp.post("/api/bypass-credentials")
def create_credential():
    uid, role = ctx()
    require_role(role, ("CarrierManager",))
    body = body_json()
    vid = body.get("vehicle_id")
    veh = store.vehicles.get(vid) if isinstance(vid, str) else None
    # Rung 3: ownership resolves through the referenced vehicle
    if veh is not None:
        ownership_guard(veh["carrier_id"], uid)
    # Rung 4
    if isinstance(vid, str) and veh is None:
        raise ApiError("ERR_VEHICLE_NOT_FOUND", 404, "vehicle id does not exist")
    # Rung 7: carrier must be ACTIVE
    if veh is not None:
        carrier = store.carriers.get(veh["carrier_id"])
        if carrier is not None and carrier["status"] != "ACTIVE":
            raise ApiError(
                "ERR_CARRIER_NOT_ACTIVE",
                409,
                "carrier must be ACTIVE to provision credentials",
            )
    # Rung 12
    vid = need_str(body, "vehicle_id")
    dtype = need_enum(body, "device_type", DEVICE_TYPES)
    serial = need_str(body, "device_serial")
    # Rung 13: serial uniqueness, then one non-terminal credential per (vehicle, type)
    for c in store.credentials.values():
        if c["device_serial"] == serial:
            raise ApiError(
                "ERR_DUPLICATE_DEVICE_SERIAL", 409, "device_serial already provisioned"
            )
    for c in store.credentials.values():
        if (
            c["vehicle_id"] == vid
            and c["device_type"] == dtype
            and c["status"] in NON_TERMINAL
        ):
            raise ApiError(
                "ERR_CREDENTIAL_TYPE_ALREADY_ACTIVE",
                409,
                "vehicle already has a non-DEACTIVATED credential of this device_type",
            )
    rec = {
        "id": db.new_id(),
        "_seq": store.next_seq(),
        "vehicle_id": vid,
        "carrier_id": veh["carrier_id"],
        "device_type": dtype,
        "device_serial": serial,
        "status": "PROVISIONED",
        "status_reason": "NONE",
        "version": 1,
    }
    db.stamp(rec)
    store.credentials[rec["id"]] = rec
    return ok(db.public(rec), 201)


@bp.get("/api/bypass-credentials")
def list_credentials():
    return list_response(
        store.credentials.values(),
        [
            ("carrier_id", "carrier_id"),
            ("vehicle_id", "vehicle_id"),
            ("status", "status"),
        ],
    )


@bp.get("/api/bypass-credentials/<credentialId>")
def get_credential(credentialId):
    ctx()
    cred = store.credentials.get(credentialId)
    if cred is None:
        raise ApiError("ERR_CREDENTIAL_NOT_FOUND", 404, "credential id does not exist")
    return ok(db.public(cred), 200)


def _pause_active_subscription(vehicle_id):
    """Billing follows service: suspending a credential pauses the vehicle's
    ACTIVE subscription (paused_at := today)."""
    for sub in store.subscriptions.values():
        if sub["vehicle_id"] == vehicle_id and sub["status"] == "ACTIVE":
            sub["status"] = "PAUSED"
            sub["paused_at"] = db.today().isoformat()
            db.bump(sub)


@bp.post("/api/bypass-credentials/<credentialId>/transition")
def credential_transition(credentialId):
    uid, role = ctx()
    require_role(role, ("CarrierManager",))
    cred = store.credentials.get(credentialId)
    # Rung 3 / 4
    if cred is not None:
        ownership_guard(cred["carrier_id"], uid)
    if cred is None:
        raise ApiError("ERR_CREDENTIAL_NOT_FOUND", 404, "credential id does not exist")
    body = body_json()
    to = body.get("to_status")
    # Rung 5 for valid targets; rung 12 otherwise
    if isinstance(to, str) and to in CRED_TARGETS:
        if (cred["status"], to) not in _LEGAL:
            raise ApiError(
                "ERR_INVALID_STATE_TRANSITION",
                409,
                f"credential cannot transition from {cred['status']} to {to}",
            )
    else:
        raise ApiError(
            "ERR_INVALID_REQUEST",
            400,
            "to_status must be one of ACTIVE, SUSPENDED, DEACTIVATED",
        )
    carrier = store.carriers.get(cred["carrier_id"])
    veh = store.vehicles.get(cred["vehicle_id"])
    if to == "ACTIVE":
        # Rung 7 safety gates in pinned order
        if carrier is not None and carrier["status"] != "ACTIVE":
            raise ApiError(
                "ERR_CARRIER_NOT_ACTIVE", 409, "carrier must be ACTIVE to activate a credential"
            )
        if carrier is not None and carrier["eligibility_status"] not in (
            "ELIGIBLE",
            "CONDITIONAL",
        ):
            raise ApiError(
                "ERR_CARRIER_NOT_BYPASS_ELIGIBLE",
                422,
                "carrier posture must be ELIGIBLE or CONDITIONAL to activate a credential",
            )
        if veh is not None and veh["service_status"] != "IN_SERVICE":
            raise ApiError(
                "ERR_VEHICLE_NOT_IN_SERVICE", 409, "vehicle must be IN_SERVICE"
            )
        # Rung 15 fiscal gates: covering subscription first, then past-due standing
        today = db.today()
        covering = None
        for s in store.subscriptions.values():
            if (
                s["vehicle_id"] == cred["vehicle_id"]
                and s["status"] in ("ACTIVE", "PAUSED")
                and s["_start"] <= today <= s["_end"]
            ):
                covering = s
                break
        if covering is None:
            raise ApiError(
                "ERR_NO_ACTIVE_SUBSCRIPTION",
                402,
                "no ACTIVE/PAUSED subscription covers today for this vehicle",
            )
        has_past_due = any(
            i["carrier_id"] == cred["carrier_id"] and i["status"] == "PAST_DUE"
            for i in store.invoices.values()
        )
        if has_past_due or covering["payment_standing"] == "PAST_DUE":
            raise ApiError(
                "ERR_CARRIER_PAST_DUE", 402, "carrier has past-due standing"
            )
        cred["status"] = "ACTIVE"
        cred["status_reason"] = "NONE"
        db.bump(cred)
        # Service follows the credential: a PAUSED covering subscription resumes.
        if covering["status"] == "PAUSED":
            covering["status"] = "ACTIVE"
            if covering["paused_at"]:
                covering["paused_days_current_period"] += (
                    today - date.fromisoformat(covering["paused_at"])
                ).days
            covering["paused_at"] = None
            db.bump(covering)
    elif to == "SUSPENDED":
        cred["status"] = "SUSPENDED"
        cred["status_reason"] = "MANUAL"
        db.bump(cred)
        _pause_active_subscription(cred["vehicle_id"])
    else:  # DEACTIVATED (terminal); manual deactivation leaves subscriptions alone
        cred["status"] = "DEACTIVATED"
        cred["status_reason"] = "MANUAL"
        db.bump(cred)
    return ok(db.public(cred), 200)
