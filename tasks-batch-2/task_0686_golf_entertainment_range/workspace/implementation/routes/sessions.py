"""GameSession routes: start, shots (scoring), end (free bay + confirm loyalty),
settle (billing), void (PRD §3.6, §3.7, §3.8; SCAFFOLD §1.5).

play_status (OPEN/ENDED) and billing_status (UNBILLED/CHARGED/VOID) are two
independent dimensions on the same session row.
"""

from flask import Blueprint, request

from db import db, stamp_common, stamp_immutable, touch
from response import success, list_success, parse_pagination, paginate
from middleware import get_caller, require_roles
from errors import (
    raise_err, ERR_INVALID_REQUEST, ERR_INVALID_STATE, ERR_VALIDATION_RANGE,
    ERR_FBTAB_NOT_CLOSED, ERR_INSUFFICIENT_FUNDS,
)
from services import validate as V
from services import calc
from services.lookup import get_or_404
from services.serialize import session_out

bp = Blueprint("sessions", __name__)

PAY_SOURCES = {"WALLET", "CARD_ON_FILE"}

# Walk-in bay fee for a session settlement. The PRD defines no concrete walk-in
# bay fee value and no input supplies one, so the session's own bay fee is 0;
# the closed F&B tab total is the only defined contribution (PRD §3.8).
WALK_IN_BAY_FEE_CENTS = 0


@bp.post("/golf/sessions")
def create_session():
    caller = get_caller()
    require_roles(caller, {"FrontDesk"})
    data = V.body()

    bay_id = V.as_str(V.require(data, "bay_id"), "bay_id")
    member_id = V.as_str(V.require(data, "member_id"), "member_id")
    bay = get_or_404(db.bays, bay_id, "bay")
    get_or_404(db.members, member_id, "member")

    reservation_id = data.get("reservation_id")
    if reservation_id is not None:
        reservation = get_or_404(db.reservations, reservation_id, "reservation")
        if reservation["status"] != "CONFIRMED":
            raise_err(ERR_INVALID_STATE, "reservation must be CONFIRMED to realize a session")

    session = stamp_common({
        "bay_id": bay_id,
        "member_id": member_id,
        "reservation_id": reservation_id,
        "queue_ticket_id": None,
        "play_status": "OPEN",
        "billing_status": "UNBILLED",
        "total_score": 0,
        "shot_count": 0,
        "shots": [],
        "charge_id": None,
        "_final_earn": 0,
    })
    db.sessions[session["id"]] = session

    bay["status"] = "OCCUPIED"
    bay["current_session_id"] = session["id"]
    touch(bay)

    return success(session_out(session), status=201)


@bp.get("/golf/sessions/<session_id>")
def get_session(session_id):
    caller = get_caller()
    require_roles(caller, {"Guest", "FrontDesk", "RangeManager"})
    s = get_or_404(db.sessions, session_id, "session")
    return success(session_out(s))


@bp.get("/golf/sessions")
def list_sessions():
    caller = get_caller()
    require_roles(caller, {"Guest", "FrontDesk", "RangeManager"})
    limit, offset = parse_pagination(request.args)
    records = list(db.sessions.values())
    for key in ("bay_id", "member_id", "reservation_id", "queue_ticket_id", "charge_id"):
        val = request.args.get(key)
        if val is not None:
            records = [s for s in records if s.get(key) == val]
    window, total = paginate(records, limit, offset)
    return list_success([session_out(s) for s in window], limit, offset, total)


@bp.post("/golf/sessions/<session_id>/shots")
def record_shot(session_id):
    caller = get_caller()
    require_roles(caller, {"FrontDesk"})
    s = get_or_404(db.sessions, session_id, "session")
    data = V.body()
    points = V.as_int(V.require(data, "points"), "points")
    if points < 0:
        raise_err(ERR_VALIDATION_RANGE, "points must be >= 0")

    if s["play_status"] != "OPEN":
        raise_err(ERR_INVALID_STATE, "session is not OPEN")

    seq = len(s["shots"]) + 1
    s["shots"].append({"seq": seq, "points": points})
    total, count = calc.scoring(s["shots"])
    s["total_score"] = total
    s["shot_count"] = count
    touch(s)
    return success(session_out(s))


@bp.post("/golf/sessions/<session_id>/end")
def end_session(session_id):
    caller = get_caller()
    require_roles(caller, {"FrontDesk"})
    s = get_or_404(db.sessions, session_id, "session")
    V.body()

    if s["play_status"] != "OPEN":
        raise_err(ERR_INVALID_STATE, "session is not OPEN")

    # Recompute total_score one final time.
    total, count = calc.scoring(s["shots"])
    s["total_score"] = total
    s["shot_count"] = count

    # Free the bay.
    bay = db.bays.get(s["bay_id"])
    if bay is not None:
        bay["status"] = "AVAILABLE"
        bay["current_session_id"] = None
        touch(bay)

    # Confirm loyalty: move provisional -> confirmed via EARN_FINAL on the
    # session's net amount. The session's net is its provisional earn basis;
    # the reservation that realizes it carried the provisional accrual.
    member = db.members.get(s["member_id"])
    net_cents = _session_net_cents(s)
    final = calc.earn_final(net_cents, member["tier"]) if member else 0
    prov = calc.earn_provisional(net_cents)
    if member is not None:
        member["loyalty_points"] += final
        member["pending_loyalty_points"] -= prov
        if member["pending_loyalty_points"] < 0:
            member["pending_loyalty_points"] = 0
        touch(member)
    s["_final_earn"] = final
    s["_prov_earn"] = prov

    s["play_status"] = "ENDED"
    touch(s)
    return success(session_out(s))


def _session_net_cents(s):
    """Net cents basis for loyalty on a session.

    For a reserved session the basis is the realizing reservation's quoted
    price (its provisional earn was accrued there). A walk-in session with no
    reservation has a walk-in bay fee basis (0 by PRD, see WALK_IN_BAY_FEE_CENTS).
    """
    if s.get("reservation_id"):
        res = db.reservations.get(s["reservation_id"])
        if res is not None:
            return res["quoted_price_cents"]
    return WALK_IN_BAY_FEE_CENTS


@bp.post("/golf/sessions/<session_id>/settle")
def settle_session(session_id):
    caller = get_caller()
    require_roles(caller, {"FrontDesk"})
    s = get_or_404(db.sessions, session_id, "session")
    data = V.body()
    if "pay_source" in data and data["pay_source"] is not None:
        pay_source = V.as_enum(data["pay_source"], "pay_source", PAY_SOURCES)
    else:
        pay_source = "CARD_ON_FILE"

    # Priority 6: billing state must be UNBILLED.
    if s["billing_status"] != "UNBILLED":
        raise_err(ERR_INVALID_STATE, "session billing is not UNBILLED")
    # play_status must be ENDED.
    if s["play_status"] != "ENDED":
        raise_err(ERR_INVALID_STATE, "session play is not ENDED")
    # Any attached F&B tab must be CLOSED.
    fb_total = 0
    for t in db.fb_tabs.values():
        if t["session_id"] == session_id:
            if t["status"] != "CLOSED":
                raise_err(ERR_FBTAB_NOT_CLOSED, "attached F&B tab is still open")
            fb_total += t["total_cents"]

    amount = WALK_IN_BAY_FEE_CENTS + fb_total
    member = db.members.get(s["member_id"])

    # Priority 12: funding (WALLET).
    if pay_source == "WALLET" and member["wallet_balance_cents"] < amount:
        raise_err(ERR_INSUFFICIENT_FUNDS, "wallet balance below settlement amount")

    charge = stamp_immutable({
        "member_id": s["member_id"],
        "kind": "SESSION_SETTLEMENT",
        "amount_cents": amount,
        "pay_source": pay_source,
        "status": "SETTLED",
    })
    db.charges[charge["id"]] = charge
    s["charge_id"] = charge["id"]
    if pay_source == "WALLET":
        member["wallet_balance_cents"] -= amount
        touch(member)

    s["billing_status"] = "CHARGED"
    touch(s)
    return success(session_out(s))


@bp.post("/golf/sessions/<session_id>/void")
def void_session(session_id):
    caller = get_caller()
    require_roles(caller, {"RangeManager"})
    s = get_or_404(db.sessions, session_id, "session")
    V.body()

    if s["billing_status"] != "UNBILLED":
        raise_err(ERR_INVALID_STATE, "session billing is not UNBILLED")

    member = db.members.get(s["member_id"])
    if member is not None:
        # Reverse any confirmed loyalty earned for this session at end.
        final = s.get("_final_earn", 0)
        if final:
            member["loyalty_points"] -= final
            if member["loyalty_points"] < 0:
                member["loyalty_points"] = 0
            s["_final_earn"] = 0
        # Reverse any outstanding provisional earn still pending for this session.
        if s["play_status"] != "ENDED":
            prov = calc.earn_provisional(_session_net_cents(s))
            if prov:
                member["pending_loyalty_points"] -= prov
                if member["pending_loyalty_points"] < 0:
                    member["pending_loyalty_points"] = 0
        touch(member)

    s["billing_status"] = "VOID"
    touch(s)
    return success(session_out(s))
