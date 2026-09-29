"""Operations surface: the logical clock and the time-driven sweep (PRD 2.5)."""

from flask import Blueprint

from db import db, iso
from middleware import authenticate
from response import ok
from services import cascade
from validation import Payload, raw_body

bp = Blueprint("ops", __name__)


@bp.post("/_clock/set_current_utc")
def set_clock():
    # PRD 2.5: this is the one endpoint exempt from the authentication headers
    # of 2.1, so rungs 1-3 of the ladder do not run here.
    payload = Payload(raw_body(), ("current_utc",))
    current_utc = payload.instant("current_utc")
    previous = db.clock
    db.clock = current_utc
    return ok({"current_utc": iso(current_utc), "previous_utc": iso(previous)})


@bp.post("/stewardship-sweeps")
def stewardship_sweep():
    authenticate(("ProgramAdmin", "StewardshipMonitor"))
    Payload(raw_body(), ())
    return ok(cascade.run_stewardship_sweep())
