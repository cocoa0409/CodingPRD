"""Host & Guest registration/fetch, and the test-driving clock (PRD §3.1, §3.4, §3.10)."""
from flask import Blueprint

from db import db
from errors import err
from middleware import require_auth
from models import make_entity, serialize
from response import success
from services.access import get_or_404
from util import parse_iso_lenient, iso_now
from validators import (
    get_body, req_str, opt_str, opt_enum, opt_int, req_bool_default,
    check_range, require,
)

bp = Blueprint("identity", __name__)

PAYOUT_METHODS = {"BANK_TRANSFER", "PAYPAL"}


@bp.post("/hosts")
def create_host():
    # Anonymous/open endpoint (no auth required, PRD §2.1).
    body = get_body()
    email = req_str(body, "email")
    display_name = req_str(body, "display_name")
    payout_method = opt_enum(body, "payout_method", PAYOUT_METHODS, "BANK_TRANSFER")
    host = make_entity({
        "email": email,
        "display_name": display_name,
        "payout_method": payout_method,
    })
    db.hosts[host["id"]] = host
    return success(serialize(host), status=201)


@bp.get("/hosts/<hid>")
def get_host(hid):
    require_auth({"Host", "PlatformAdmin"})
    host = get_or_404(db.hosts, hid)
    return success(serialize(host))


@bp.post("/guests")
def create_guest():
    body = get_body()
    email = req_str(body, "email")
    full_name = req_str(body, "full_name")
    govt_id_verified = req_bool_default(body, "govt_id_verified", False)
    prior_cancellations = opt_int(body, "prior_cancellations", 0)
    check_range(prior_cancellations, "prior_cancellations", lo=0)
    chargeback_flag = req_bool_default(body, "chargeback_flag", False)
    guest = make_entity({
        "email": email,
        "full_name": full_name,
        "govt_id_verified": govt_id_verified,
        "prior_cancellations": prior_cancellations,
        "chargeback_flag": chargeback_flag,
        # risk_score uncomputed until first screening (PRD §3.4).
        "risk_score": None,
    })
    db.guests[guest["id"]] = guest
    return success(serialize(guest), status=201)


@bp.get("/guests/<gid>")
def get_guest(gid):
    require_auth({"Guest", "Host", "PlatformAdmin"})
    guest = get_or_404(db.guests, gid)
    return success(serialize(guest))


@bp.post("/_clock/set_current_utc")
def set_clock():
    # PlatformAdmin or Anonymous may set the clock; if headers are present they
    # must name one of those roles, but Anonymous needs no headers (PRD §2.1, §3.10).
    from middleware import get_principal
    user_id, role = get_principal()
    if role is not None and role not in ("PlatformAdmin", "Anonymous"):
        # A well-formed but non-permitted role -> forbidden.
        raise err("ERR_FORBIDDEN_ROLE", "role not permitted to set the clock")
    body = get_body()
    raw = require(body, "to_iso8601")
    new_clock = parse_iso_lenient(raw)
    db.current_utc = new_clock
    _auto_advance_confirmed_bookings(new_clock)
    return success({"current_utc": iso_now(new_clock)})


def _auto_advance_confirmed_bookings(current_utc):
    """Every CONFIRMED booking whose check_in <= current_utc -> IN_STAY (PRD §3.6, §3.10)."""
    from models import touch
    for booking in db.bookings.values():
        if booking["status"] == "CONFIRMED" and booking["check_in"] <= current_utc:
            booking["status"] = "IN_STAY"
            touch(booking)
