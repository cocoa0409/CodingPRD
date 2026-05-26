"""Entity lookup helpers — produce ERR_NOT_FOUND / ERR_FK_NOT_FOUND on miss."""
from __future__ import annotations

import db
from errors import ApiError, ERR_NOT_FOUND, ERR_FK_NOT_FOUND


def get_owner_or_404(oid: str) -> dict:
    o = db.owners.get(oid)
    if o is None:
        raise ApiError(ERR_NOT_FOUND, "Owner not found.")
    return o


def get_sitter_or_404(sid: str) -> dict:
    s = db.sitters.get(sid)
    if s is None:
        raise ApiError(ERR_NOT_FOUND, "Sitter not found.")
    return s


def get_pet_or_404(pid: str) -> dict:
    p = db.pets.get(pid)
    if p is None:
        raise ApiError(ERR_NOT_FOUND, "Pet not found.")
    return p


def get_background_check_or_404(bid: str) -> dict:
    b = db.background_checks.get(bid)
    if b is None:
        raise ApiError(ERR_NOT_FOUND, "BackgroundCheck not found.")
    return b


def get_emergency_contact_or_404(eid: str) -> dict:
    e = db.emergency_contacts.get(eid)
    if e is None:
        raise ApiError(ERR_NOT_FOUND, "EmergencyContact not found.")
    return e


def get_meet_and_greet_or_404(mid: str) -> dict:
    m = db.meet_and_greets.get(mid)
    if m is None:
        raise ApiError(ERR_NOT_FOUND, "MeetAndGreet not found.")
    return m


def get_booking_or_404(bid: str) -> dict:
    b = db.bookings.get(bid)
    if b is None:
        raise ApiError(ERR_NOT_FOUND, "Booking not found.")
    return b


def get_key_handoff_or_404(kid: str) -> dict:
    k = db.key_handoffs.get(kid)
    if k is None:
        raise ApiError(ERR_NOT_FOUND, "KeyHandoff not found.")
    return k


def get_gps_track_or_404(gid: str) -> dict:
    g = db.gps_tracks.get(gid)
    if g is None:
        raise ApiError(ERR_NOT_FOUND, "GpsTrack not found.")
    return g


def get_insurance_claim_or_404(cid: str) -> dict:
    c = db.insurance_claims.get(cid)
    if c is None:
        raise ApiError(ERR_NOT_FOUND, "InsuranceClaim not found.")
    return c


# ---------- FK lookups (raise ERR_FK_NOT_FOUND) ----------
def fk_owner(oid: str) -> dict:
    o = db.owners.get(oid)
    if o is None:
        raise ApiError(ERR_FK_NOT_FOUND, f"owner_id {oid} does not exist.")
    return o


def fk_sitter(sid: str) -> dict:
    s = db.sitters.get(sid)
    if s is None:
        raise ApiError(ERR_FK_NOT_FOUND, f"sitter_id {sid} does not exist.")
    return s


def fk_pet(pid: str) -> dict:
    p = db.pets.get(pid)
    if p is None:
        raise ApiError(ERR_FK_NOT_FOUND, f"pet_id {pid} does not exist.")
    return p


def fk_booking(bid: str) -> dict:
    b = db.bookings.get(bid)
    if b is None:
        raise ApiError(ERR_FK_NOT_FOUND, f"booking_id {bid} does not exist.")
    return b


# ---------- BackgroundCheck-by-sitter lookup ----------
def bg_check_for_sitter(sitter_id: str) -> dict | None:
    for bc in db.background_checks.values():
        if bc["sitter_id"] == sitter_id:
            return bc
    return None


def key_handoff_for_booking(booking_id: str) -> dict | None:
    for kh in db.key_handoffs.values():
        if kh["booking_id"] == booking_id:
            return kh
    return None
