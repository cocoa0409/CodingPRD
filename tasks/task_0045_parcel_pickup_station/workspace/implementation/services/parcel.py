"""Parcel state machine, registration, pickup, dispose, shelf reassignment."""
import random
from datetime import timedelta

from clock import now
from db import store, new_id, GLOBAL_LOCK
from errors import E, raise_error
from services.common import (
    stamp_create, bump, write_audit, emit_event, check_version_occ
)
from services.pricing import storage_fee_at


ACTIVE_PARCEL_STATES = {"SHELVED", "OVERTIME", "AWAITING_RETURN"}


# ---------- Pickup code minting ----------
def _mint_code(parcel_id: str, issue_reason: str = "INITIAL") -> dict:
    """Mint a new 6-digit ACTIVE pickup code. Raises if collision-exhausted."""
    active_codes = {row["code"] for row in store.pickup_codes.values()
                    if row["status"] == "ACTIVE"}
    candidate = None
    for _ in range(20):
        c = "".join(random.choice("0123456789") for _ in range(6))
        if c not in active_codes:
            candidate = c
            break
    if candidate is None:
        raise_error(E.PICKUP_CODE_GENERATION_EXHAUSTED, "Could not mint a unique code")

    row = stamp_create({
        "parcel_id": parcel_id,
        "code": candidate,
        "status": "ACTIVE",
        "issued_at": now(),
        "issue_reason": issue_reason,
        "consumed_at": None,
        "superseded_by": None,
    })
    store.pickup_codes[row["id"]] = row
    return row


def get_active_code_for_parcel(parcel_id: str):
    for c in store.pickup_codes.values():
        if c["parcel_id"] == parcel_id and c["status"] == "ACTIVE":
            return c
    return None


# ---------- Parcel registration ----------
def register_parcel(station_id: str, body: dict, actor_role: str, actor_id: str):
    from services.station import get_station
    from services.shelf_zone import get_zone

    station = get_station(station_id, allow_not_found=False)

    # Auth-of-shape: required fields
    required = ["courier_company_id", "tracking_number", "recipient_phone",
                "weight_grams", "size_class"]
    for k in required:
        if body.get(k) in (None, ""):
            raise_error(E.VALIDATION, f"{k} is required")

    courier_company_id = str(body["courier_company_id"])
    tracking_number = str(body["tracking_number"])
    recipient_phone = str(body["recipient_phone"])
    recipient_name = body.get("recipient_name")
    weight_grams = body["weight_grams"]
    size_class = body["size_class"]
    exception_type = body.get("exception_type") or "NONE"
    shelf_zone_id = body.get("shelf_zone_id")
    shelf_position = body.get("shelf_position")

    # Type/format validation
    if not isinstance(weight_grams, int) or weight_grams < 1:
        raise_error(E.VALIDATION, "weight_grams must be integer >= 1")
    if size_class not in ("S", "M", "L", "XL"):
        raise_error(E.VALIDATION, "size_class invalid")
    if exception_type not in ("NONE", "DAMAGED", "WRONG_DELIVERY"):
        raise_error(E.VALIDATION, "exception_type invalid")
    if not recipient_phone.isdigit() or not (6 <= len(recipient_phone) <= 15):
        raise_error(E.VALIDATION, "recipient_phone must be 6..15 digits")

    with GLOBAL_LOCK:
        is_exception = exception_type != "NONE"

        # Validation priority: state -> business_safety -> referential -> constraints
        if is_exception:
            # Station must be ACTIVE or SUSPENDED for exception path
            if station["status"] not in ("ACTIVE", "SUSPENDED"):
                raise_error(E.STATION_NOT_ACTIVE, "Station not active or suspended")
            # business_safety: exception cannot also request shelf assignment
            if shelf_zone_id is not None or shelf_position is not None:
                raise_error(E.EXCEPTION_PARCEL_CANNOT_SHELVE,
                            "Exception parcel cannot be shelved")
        else:
            # Normal acceptance: station must be ACTIVE
            if station["status"] != "ACTIVE":
                raise_error(E.STATION_NOT_ACTIVE, "Station not active")
            # Shelf zone is required for normal acceptance
            if shelf_zone_id is None or shelf_position is None:
                raise_error(E.VALIDATION, "shelf_zone_id and shelf_position required")
            # Referential resolution (foreign-key existence)
            zone = get_zone(shelf_zone_id, allow_not_found=True)
            if zone is None:
                raise_error(E.RESOURCE_NOT_FOUND, "shelf_zone_id not found")
            # business_referential: zone-station match
            if zone["station_id"] != station_id:
                raise_error(E.SHELF_ZONE_STATION_MISMATCH, "Zone does not belong to station")
            # Validate shelf_position format
            if not isinstance(shelf_position, str) or not shelf_position:
                raise_error(E.VALIDATION, "shelf_position must be string")
            # Business constraint: shelf position occupied
            for p in store.parcels.values():
                if (p["shelf_zone_id"] == shelf_zone_id
                        and p["shelf_position"] == shelf_position
                        and p["status"] in ACTIVE_PARCEL_STATES):
                    raise_error(E.SHELF_POSITION_OCCUPIED, "Shelf position occupied")
            # Business constraint: zone full
            if zone["occupied_slots"] >= zone["capacity"]:
                raise_error(E.SHELF_ZONE_FULL, "Shelf zone full")
            # Business constraint: station capacity
            if station["current_occupancy"] >= station["storage_capacity"]:
                raise_error(E.STATION_CAPACITY_EXCEEDED, "Station capacity exceeded")
            # Duplicate tracking number among active-lifecycle rows (status != REJECTED)
            for p in store.parcels.values():
                if (p["courier_company_id"] == courier_company_id
                        and p["tracking_number"] == tracking_number
                        and p["status"] != "REJECTED"):
                    raise_error(E.DUPLICATE_TRACKING_NUMBER, "Duplicate tracking number")

        # Create parcel row
        parcel = stamp_create({
            "station_id": station_id,
            "courier_company_id": courier_company_id,
            "tracking_number": tracking_number,
            "recipient_phone": recipient_phone,
            "recipient_name": recipient_name,
            "weight_grams": weight_grams,
            "size_class": size_class,
            "shelf_zone_id": None,
            "shelf_position": None,
            "status": "UNREGISTERED",
            "exception_type": exception_type,
            "shelved_at": None,
            "free_storage_deadline": None,
            "picked_up_at": None,
            "returned_at": None,
            "long_stay_flagged_at": None,
            "storage_fee_total": 0,
            "storage_fee_locked": False,
        })

        if is_exception:
            # UNREGISTERED -> REJECTED
            parcel["status"] = "REJECTED"
            bump(parcel)
            store.parcels[parcel["id"]] = parcel
            write_audit("Parcel", parcel["id"], "INBOUND_REJECTED",
                        actor_role, actor_id,
                        from_state="UNREGISTERED", to_state="REJECTED",
                        payload={"exception_type": exception_type})
            return parcel

        # Normal accept: UNREGISTERED -> SHELVED
        t = now()
        parcel["shelf_zone_id"] = shelf_zone_id
        parcel["shelf_position"] = shelf_position
        parcel["shelved_at"] = t
        parcel["free_storage_deadline"] = t + timedelta(hours=station["free_storage_hours"])
        parcel["status"] = "SHELVED"
        bump(parcel)
        store.parcels[parcel["id"]] = parcel

        # Update station / zone counters
        station["current_occupancy"] += 1
        bump(station)
        zone["occupied_slots"] += 1
        bump(zone)

        # Mint initial pickup code
        code = _mint_code(parcel["id"], issue_reason="INITIAL")

        # Emit T1 initial reminder
        from services.reminder import emit_reminder
        emit_reminder(parcel["id"], "T1_INITIAL", "SMS", "INBOUND")

        # Audit + outbox
        write_audit("Parcel", parcel["id"], "INBOUND_ACCEPTED",
                    actor_role, actor_id,
                    from_state="UNREGISTERED", to_state="SHELVED",
                    payload={"shelf_zone_id": shelf_zone_id, "shelf_position": shelf_position})
        emit_event("IM", "PICKUP_CODE_SENT", "PickupCode", code["id"],
                   payload={"parcel_id": parcel["id"], "code": code["code"]})

        return parcel


# ---------- Pickup code reissue ----------
def reissue_pickup_code(parcel_id: str, body: dict, actor_role: str, actor_id: str):
    parcel = store.parcels.get(parcel_id)
    if parcel is None:
        raise_error(E.RESOURCE_NOT_FOUND, "Parcel not found")
    reason = body.get("reason") if body else None
    if not reason:
        raise_error(E.VALIDATION, "reason required")

    with GLOBAL_LOCK:
        if parcel["status"] not in ("SHELVED", "OVERTIME", "AWAITING_RETURN"):
            raise_error(E.INVALID_PARCEL_STATE, "Parcel state invalid for reissue")

        active = get_active_code_for_parcel(parcel_id)
        if active is None:
            # No active code to reissue from -> race already happened
            raise_error(E.PICKUP_CODE_REISSUE_RACE, "No active code to reissue")

        # Mint new code first (so we can record superseded_by)
        new_code = _mint_code(parcel_id, issue_reason="REISSUED_LOST")
        # Flip the old code to REISSUED
        active["status"] = "REISSUED"
        active["superseded_by"] = new_code["id"]
        bump(active)
        emit_event("IM", "PICKUP_CODE_REISSUED", "PickupCode", new_code["id"],
                   payload={"parcel_id": parcel_id, "code": new_code["code"]})
        write_audit("PickupCode", active["id"], "PICKUP_CODE_REISSUED",
                    actor_role, actor_id,
                    from_state="ACTIVE", to_state="REISSUED",
                    payload={"superseded_by": new_code["id"]})
        return new_code


# ---------- Shelf reassignment ----------
def reassign_shelf(parcel_id: str, body: dict, actor_role: str, actor_id: str):
    parcel = store.parcels.get(parcel_id)
    if parcel is None:
        raise_error(E.RESOURCE_NOT_FOUND, "Parcel not found")

    from services.shelf_zone import get_zone
    from services.station import get_station
    new_zone_id = body.get("shelf_zone_id")
    new_pos = body.get("shelf_position")
    if not new_zone_id or not new_pos:
        raise_error(E.VALIDATION, "shelf_zone_id and shelf_position required")

    new_zone = get_zone(new_zone_id, allow_not_found=True)
    if new_zone is None:
        raise_error(E.RESOURCE_NOT_FOUND, "shelf_zone_id not found")

    with GLOBAL_LOCK:
        if parcel["status"] not in ACTIVE_PARCEL_STATES:
            raise_error(E.INVALID_PARCEL_STATE, "Parcel not on shelf")
        check_version_occ(parcel, body)

        if new_zone["station_id"] != parcel["station_id"]:
            raise_error(E.SHELF_ZONE_STATION_MISMATCH, "Zone-station mismatch")

        # Position occupied check
        for p in store.parcels.values():
            if (p["id"] != parcel_id
                    and p["shelf_zone_id"] == new_zone_id
                    and p["shelf_position"] == new_pos
                    and p["status"] in ACTIVE_PARCEL_STATES):
                raise_error(E.SHELF_POSITION_OCCUPIED, "Shelf position occupied")

        # If moving zones, recompute zone counters
        old_zone_id = parcel["shelf_zone_id"]
        old_pos = parcel["shelf_position"]
        if old_zone_id != new_zone_id:
            old_zone = store.shelf_zones.get(old_zone_id)
            if old_zone:
                old_zone["occupied_slots"] = max(0, old_zone["occupied_slots"] - 1)
                bump(old_zone)
            # Capacity check on new zone
            if new_zone["occupied_slots"] >= new_zone["capacity"]:
                raise_error(E.SHELF_ZONE_FULL, "Zone full")
            new_zone["occupied_slots"] += 1
            bump(new_zone)

        parcel["shelf_zone_id"] = new_zone_id
        parcel["shelf_position"] = new_pos
        bump(parcel)

        write_audit("Parcel", parcel_id, "SHELF_REASSIGNED",
                    actor_role, actor_id, from_state=None, to_state=None,
                    payload={
                        "from_zone": old_zone_id, "from_position": old_pos,
                        "to_zone": new_zone_id, "to_position": new_pos,
                    })
        return parcel


# ---------- Pickup ----------
def pickup_parcel(parcel_id: str, body: dict, actor_role: str, actor_id: str):
    parcel = store.parcels.get(parcel_id)
    if parcel is None:
        raise_error(E.RESOURCE_NOT_FOUND, "Parcel not found")
    from services.station import get_station
    station = get_station(parcel["station_id"], allow_not_found=False)

    method = body.get("verification_method") if body else None
    code_in = body.get("code") if body else None
    auth_id = body.get("authorization_id") if body else None
    delegate_id_number = body.get("delegate_id_number") if body else None
    face_match = bool(body.get("face_match")) if body else False

    with GLOBAL_LOCK:
        # state checks
        if station["status"] != "ACTIVE":
            raise_error(E.STATION_NOT_ACTIVE, "Station not active")

        # Parcel state — per PRD §2.11, state-check fires before
        # business-safety. ERR_PARCEL_ALREADY_PICKED_UP is reserved for
        # the race-loser case (PRD §3.6); a fresh request landing on an
        # already-PICKED_UP parcel is a plain state-gate failure.
        if parcel["status"] not in ("SHELVED", "OVERTIME", "AWAITING_RETURN"):
            raise_error(E.INVALID_PARCEL_STATE, "Parcel not pickable")

        # If AWAITING_RETURN: ensure no return shipment is COURIER_ACCEPTED/SHIPPED/DISPOSED
        request_return_to_decline = None
        if parcel["status"] == "AWAITING_RETURN":
            for rs in store.return_shipments.values():
                if rs["parcel_id"] != parcel_id:
                    continue
                if rs["status"] in ("COURIER_ACCEPTED", "SHIPPED", "DISPOSED"):
                    raise_error(E.INVALID_PARCEL_STATE, "Parcel already in return process")
                if rs["status"] == "REQUESTED":
                    request_return_to_decline = rs

        # Verification
        verified = False
        used_code = None
        used_auth = None

        if face_match is True:
            verified = True

        if not verified and code_in:
            for c in store.pickup_codes.values():
                if (c["parcel_id"] == parcel_id
                        and c["status"] == "ACTIVE"
                        and c["code"] == code_in):
                    used_code = c
                    verified = True
                    break

        if not verified and auth_id:
            auth = store.pickup_auths.get(auth_id)
            if auth and auth["parcel_id"] == parcel_id and auth["status"] == "ACTIVE":
                if auth.get("delegate_id_number") == delegate_id_number:
                    if now() < auth["expires_at"]:
                        used_auth = auth
                        verified = True

        if not verified:
            raise_error(E.PICKUP_VERIFICATION_FAILED, "Verification failed")

        # Apply transition
        t = now()
        parcel["picked_up_at"] = t
        parcel["storage_fee_total"] = storage_fee_at(
            parcel["free_storage_deadline"], t, parcel["size_class"])
        parcel["storage_fee_locked"] = True
        from_state = parcel["status"]
        parcel["status"] = "PICKED_UP"
        bump(parcel)

        # Decrement counters
        station["current_occupancy"] = max(0, station["current_occupancy"] - 1)
        bump(station)
        zone = store.shelf_zones.get(parcel["shelf_zone_id"])
        if zone is not None:
            zone["occupied_slots"] = max(0, zone["occupied_slots"] - 1)
            bump(zone)

        # Consume code / authorization
        if used_code:
            used_code["status"] = "CONSUMED"
            used_code["consumed_at"] = t
            bump(used_code)
        if used_auth:
            used_auth["status"] = "CONSUMED"

        # If a REQUESTED return existed -> mark COURIER_DECLINED
        if request_return_to_decline:
            request_return_to_decline["status"] = "COURIER_DECLINED"
            request_return_to_decline["courier_response_at"] = t
            bump(request_return_to_decline)

        # If storage_fee_total > 0, roll into RECIPIENT bill for current period
        if parcel["storage_fee_total"] and parcel["storage_fee_total"] > 0:
            from services.billing import roll_storage_into_recipient_bill
            roll_storage_into_recipient_bill(parcel)

        write_audit("Parcel", parcel_id, "PICKED_UP",
                    actor_role, actor_id, from_state=from_state, to_state="PICKED_UP",
                    payload={
                        "verification_method": method,
                        "storage_fee_total": parcel["storage_fee_total"],
                    })
        return parcel


# ---------- Dispose ----------
DISPOSAL_GRACE_HOURS = 240


def dispose_parcel(parcel_id: str, body: dict, actor_role: str, actor_id: str):
    parcel = store.parcels.get(parcel_id)
    if parcel is None:
        raise_error(E.RESOURCE_NOT_FOUND, "Parcel not found")
    reason = (body or {}).get("reason")

    with GLOBAL_LOCK:
        if parcel["status"] != "AWAITING_RETURN":
            raise_error(E.INVALID_PARCEL_STATE, "Parcel state invalid for dispose")
        if parcel.get("long_stay_flagged_at") is None:
            raise_error(E.DISPOSAL_TOO_EARLY, "Not long-stay flagged yet")
        # No return shipment in COURIER_ACCEPTED or SHIPPED
        for rs in store.return_shipments.values():
            if rs["parcel_id"] == parcel_id and rs["status"] in ("COURIER_ACCEPTED", "SHIPPED"):
                raise_error(E.INVALID_PARCEL_STATE, "Active return shipment exists")

        if now() < parcel["long_stay_flagged_at"] + _td(DISPOSAL_GRACE_HOURS):
            raise_error(E.DISPOSAL_TOO_EARLY, "Disposal too early")

        t = now()
        parcel["status"] = "DISPOSED"
        # Finalize storage fee at disposal time
        parcel["storage_fee_total"] = storage_fee_at(
            parcel["free_storage_deadline"], t, parcel["size_class"])
        parcel["storage_fee_locked"] = True
        bump(parcel)

        # Counter decrements
        station = store.stations.get(parcel["station_id"])
        if station is not None:
            station["current_occupancy"] = max(0, station["current_occupancy"] - 1)
            bump(station)
        zone = store.shelf_zones.get(parcel["shelf_zone_id"])
        if zone is not None:
            zone["occupied_slots"] = max(0, zone["occupied_slots"] - 1)
            bump(zone)

        _void_codes_on_terminal(parcel_id)

        write_audit("Parcel", parcel_id, "DISPOSED",
                    actor_role, actor_id,
                    from_state="AWAITING_RETURN", to_state="DISPOSED",
                    payload={"reason": reason})
        return parcel


def _td(hours):
    return timedelta(hours=hours)


def _void_codes_on_terminal(parcel_id: str):
    for c in store.pickup_codes.values():
        if c["parcel_id"] != parcel_id:
            continue
        if c["status"] == "ACTIVE":
            c["status"] = "VOIDED"
            c["consumed_at"] = None
            bump(c)
        elif c["status"] == "REISSUED":
            c["status"] = "VOIDED"
            bump(c)


# ---------- Lookups ----------
def get_parcel(parcel_id, allow_not_found=False):
    p = store.parcels.get(parcel_id)
    if p is None and not allow_not_found:
        raise_error(E.RESOURCE_NOT_FOUND, "Parcel not found")
    return p
