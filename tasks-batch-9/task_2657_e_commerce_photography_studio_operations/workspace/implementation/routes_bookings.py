"""Talent bookings: holds, the frozen charge, usage-rights confirmation and
cancellation."""
from flask import Blueprint

from core import (
    BOOKING_STATES, ROLE_ON_SET, SCOPE_RANK, authorize, by_created, created, db,
    fail, get_body, new_row, ok, ok_list, page_params, paginate, qenum, qstr,
    touch, vdt, venum, vint, vstr,
)
from logic import (
    compute_booking_charge, find, refresh_all_releases,
    session_committed_talent_cost,
)
from serialize import booking_out

bp = Blueprint("bookings", __name__)


def select_release(booking):
    """PRD 3.5 selector: scope breadth DESC, then valid_until DESC, then
    created_at ASC; the first candidate wins."""
    refresh_all_releases()
    candidates = [r for r in db.releases.values()
                  if r["talent_id"] == booking["talent_id"]
                  and r["doc_state"] == "SIGNED"
                  and r["valid_from"] <= booking["call_time"]
                  and r["valid_until"] > booking["wrap_time"]]
    if not candidates:
        return None
    candidates.sort(key=lambda r: (r["created_at"], r["_seq"]))
    candidates.sort(key=lambda r: r["valid_until"], reverse=True)
    candidates.sort(key=lambda r: SCOPE_RANK[r["scope"]], reverse=True)
    return candidates[0]


@bp.post("/talent-bookings")
def create_booking():
    authorize("Producer")
    body = get_body()
    session_id = vstr(body, "session_id", minlen=1)
    talent_id = vstr(body, "talent_id", minlen=1)
    role_on_set = venum(body, "role_on_set", ROLE_ON_SET)
    call_time = vdt(body, "call_time")
    wrap_time = vdt(body, "wrap_time")
    expected_session_version = vint(body, "expected_session_version", minimum=0)

    session = find(db.sessions, session_id, "ERR_SESSION_NOT_FOUND")
    talent = find(db.talents, talent_id, "ERR_REFERENCE_NOT_FOUND")

    if session["session_state"] != "BOOKED":
        fail("ERR_SESSION_NOT_BOOKED")
    if expected_session_version != session["version"]:
        fail("ERR_STALE_SESSION_VERSION")

    if (wrap_time <= call_time
            or call_time < session["scheduled_start"]
            or wrap_time > session["scheduled_end"]):
        fail("ERR_INVALID_TIME_WINDOW",
             "The booked window must sit inside the session and be positive.")

    for other in db.bookings.values():
        if other["talent_id"] != talent["id"]:
            continue
        if other["booking_state"] not in ("HELD", "CONFIRMED"):
            continue
        if call_time < other["wrap_time"] and other["call_time"] < wrap_time:
            fail("ERR_TALENT_OVERLAP")

    if role_on_set != talent["talent_type"]:
        fail("ERR_TALENT_TYPE_MISMATCH",
             "role_on_set '%s' does not match talent_type '%s'."
             % (role_on_set, talent["talent_type"]))

    charge = compute_booking_charge(talent, call_time, wrap_time)
    row = new_row({
        "session_id": session["id"],
        "talent_id": talent["id"],
        "role_on_set": role_on_set,
        "call_time": call_time,
        "wrap_time": wrap_time,
        "booked_minutes": charge["booked_minutes"],
        "regular_minutes": charge["regular_minutes"],
        "overtime_minutes": charge["overtime_minutes"],
        "charge_cents": charge["charge_cents"],
        "booking_state": "HELD",
        "usage_rights_scope": None,
        "release_document_id": None,
    })
    db.bookings[row["id"]] = row
    touch(talent)
    touch(session)
    return created(booking_out(row))


@bp.post("/talent-bookings/<booking_id>/confirm")
def confirm_booking(booking_id):
    authorize("Producer")
    booking = find(db.bookings, booking_id, "ERR_BOOKING_NOT_FOUND")
    if booking["booking_state"] != "HELD":
        fail("ERR_BOOKING_INVALID_STATE")
    session = db.sessions.get(booking["session_id"])
    if session is None or session["session_state"] not in ("BOOKED", "LOCKED"):
        fail("ERR_SESSION_TERMINAL")

    talent = db.talents.get(booking["talent_id"])
    selected = None
    if talent is not None and talent.get("requires_release"):
        selected = select_release(booking)
        if selected is None:
            fail("ERR_RELEASE_NOT_ON_FILE")
        if SCOPE_RANK[selected["scope"]] < SCOPE_RANK[session["required_usage_scope"]]:
            fail("ERR_RELEASE_SCOPE_INSUFFICIENT")

    committed = session_committed_talent_cost(session["id"])
    if committed + booking["charge_cents"] > session["budget_cap_cents"]:
        fail("ERR_SESSION_BUDGET_EXCEEDED")

    booking["booking_state"] = "CONFIRMED"
    if selected is not None:
        booking["release_document_id"] = selected["id"]
        booking["usage_rights_scope"] = selected["scope"]
    touch(booking)
    touch(session)
    return ok(booking_out(booking))


@bp.post("/talent-bookings/<booking_id>/cancel")
def cancel_booking(booking_id):
    authorize("Producer")
    body = get_body()
    vstr(body, "reason", required=False, default=None, maxlen=2000)
    booking = find(db.bookings, booking_id, "ERR_BOOKING_NOT_FOUND")
    if booking["booking_state"] not in ("HELD", "CONFIRMED"):
        fail("ERR_BOOKING_INVALID_STATE")

    was_confirmed = booking["booking_state"] == "CONFIRMED"
    booking["booking_state"] = "CANCELLED"
    touch(booking)

    talent = db.talents.get(booking["talent_id"])
    if talent is not None:
        touch(talent)
    if was_confirmed:
        session = db.sessions.get(booking["session_id"])
        if session is not None:
            touch(session)
    return ok(booking_out(booking))


@bp.get("/talent-bookings/<booking_id>")
def read_booking(booking_id):
    authorize("StudioAdmin", "Producer", "Photographer")
    row = find(db.bookings, booking_id, "ERR_BOOKING_NOT_FOUND")
    return ok(booking_out(row))


@bp.get("/talent-bookings")
def list_bookings():
    authorize("StudioAdmin", "Producer", "Photographer")
    limit, offset = page_params()
    session_id = qstr("session_id")
    talent_id = qstr("talent_id")
    release_document_id = qstr("release_document_id")
    booking_state = qenum("booking_state", BOOKING_STATES)
    role_on_set = qenum("role_on_set", ROLE_ON_SET)

    rows = list(db.bookings.values())
    if session_id is not None:
        rows = [r for r in rows if r["session_id"] == session_id]
    if talent_id is not None:
        rows = [r for r in rows if r["talent_id"] == talent_id]
    if release_document_id is not None:
        rows = [r for r in rows if r.get("release_document_id") == release_document_id]
    if booking_state is not None:
        rows = [r for r in rows if r["booking_state"] == booking_state]
    if role_on_set is not None:
        rows = [r for r in rows if r["role_on_set"] == role_on_set]

    page, total = paginate(by_created(rows), limit, offset)
    return ok_list([booking_out(r) for r in page], limit, offset, total)
