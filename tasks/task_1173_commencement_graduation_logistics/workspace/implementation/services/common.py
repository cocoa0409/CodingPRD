"""Shared service helpers: lookup, validation, posture gates, cascades."""
from datetime import timedelta

import db
from errors import (
    raise_err,
    ERR_NOT_FOUND,
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE,
    ERR_CEREMONY_POSTURE_FORBIDS,
    ERR_GRADUATE_NOT_ELIGIBLE,
    ERR_STALE_VERSION,
)

ELIGIBLE_FAMILY = {"ELIGIBLE", "ELIGIBLE_ON_APPEAL", "CONFIRMED"}


# ---------- lookups ----------

def get_ceremony_or_404(cid):
    c = db.ceremonies.get(cid)
    if c is None:
        raise_err(ERR_NOT_FOUND, "Ceremony not found")
    return c


def get_venue_or_404(vid):
    v = db.venues.get(vid)
    if v is None:
        raise_err(ERR_NOT_FOUND, "Venue not found")
    return v


def get_graduate_or_404(gid):
    g = db.graduates.get(gid)
    if g is None:
        raise_err(ERR_NOT_FOUND, "Graduate not found")
    return g


def get_audit_or_404(aid):
    a = db.eligibility_audits.get(aid)
    if a is None:
        raise_err(ERR_NOT_FOUND, "EligibilityAudit not found")
    return a


def get_allocation_or_404(aid):
    a = db.ticket_allocations.get(aid)
    if a is None:
        raise_err(ERR_NOT_FOUND, "TicketAllocation not found")
    return a


def get_regalia_or_404(oid):
    o = db.regalia_orders.get(oid)
    if o is None:
        raise_err(ERR_NOT_FOUND, "RegaliaOrder not found")
    return o


def get_seat_or_404(sid):
    s = db.seat_assignments.get(sid)
    if s is None:
        raise_err(ERR_NOT_FOUND, "SeatAssignment not found")
    return s


def get_reader_card_or_404(rid):
    r = db.reader_cards.get(rid)
    if r is None:
        raise_err(ERR_NOT_FOUND, "ReaderCard not found")
    return r


def get_batch_or_404(bid):
    b = db.print_batches.get(bid)
    if b is None:
        raise_err(ERR_NOT_FOUND, "PrintBatch not found")
    return b


def get_diploma_or_404(did):
    d = db.diplomas.get(did)
    if d is None:
        raise_err(ERR_NOT_FOUND, "Diploma not found")
    return d


def get_session_or_404(sid):
    s = db.rehearsal_sessions.get(sid)
    if s is None:
        raise_err(ERR_NOT_FOUND, "RehearsalSession not found")
    return s


def get_attendance_or_404(aid):
    a = db.rehearsal_attendances.get(aid)
    if a is None:
        raise_err(ERR_NOT_FOUND, "RehearsalAttendance not found")
    return a


def get_accommodation_or_404(rid):
    r = db.accommodation_requests.get(rid)
    if r is None:
        raise_err(ERR_NOT_FOUND, "AccommodationRequest not found")
    return r


def get_vendor_contract_or_404(cid):
    c = db.vendor_contracts.get(cid)
    if c is None:
        raise_err(ERR_NOT_FOUND, "VendorContract not found")
    return c


# ---------- shared validators ----------

def require_body_fields(body, fields):
    for f in fields:
        if f not in body or body[f] is None:
            raise_err(ERR_INVALID_REQUEST, f"Missing required field: {f}")


def is_number(x):
    return isinstance(x, (int, float)) and not isinstance(x, bool)


def is_int(x):
    return isinstance(x, int) and not isinstance(x, bool)


def require_number(body, f, minimum=None):
    if f not in body or not is_number(body[f]):
        raise_err(ERR_INVALID_REQUEST, f"Field {f} must be a number")
    if minimum is not None and body[f] < minimum:
        raise_err(ERR_INVALID_REQUEST, f"Field {f} must be >= {minimum}")


def require_int(body, f, minimum=None):
    if f not in body or not is_int(body[f]):
        raise_err(ERR_INVALID_REQUEST, f"Field {f} must be an integer")
    if minimum is not None and body[f] < minimum:
        raise_err(ERR_INVALID_REQUEST, f"Field {f} must be >= {minimum}")


def require_string(body, f):
    if f not in body or not isinstance(body[f], str):
        raise_err(ERR_INVALID_REQUEST, f"Field {f} must be a string")


def require_enum(body, f, domain):
    if f not in body or body[f] not in domain:
        raise_err(ERR_INVALID_REQUEST, f"Field {f} must be one of {sorted(domain)}")


def posture_gate(ceremony, allowed_postures):
    if ceremony["readiness_posture"] not in allowed_postures:
        raise_err(
            ERR_CEREMONY_POSTURE_FORBIDS,
            f"Ceremony posture {ceremony['readiness_posture']} forbids this operation",
        )


def graduate_eligible_gate(grad):
    if grad["status"] not in ELIGIBLE_FAMILY:
        raise_err(ERR_GRADUATE_NOT_ELIGIBLE, "Graduate is not in the eligible family")


def occ_check(entity, expected):
    """OCC: expected must equal current version; omission treated as invalid request."""
    if expected is None or not is_int(expected):
        raise_err(ERR_INVALID_REQUEST, "expected_*_version is required and must be an integer")
    if expected != entity["version"]:
        raise_err(ERR_STALE_VERSION, "Stale version")
