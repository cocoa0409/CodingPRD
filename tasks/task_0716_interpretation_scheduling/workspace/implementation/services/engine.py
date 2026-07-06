from datetime import timedelta

from db import db
from clock import parse_iso
from services import constants as C
from services import calc


# ---------------------------------------------------------------------------
# Interpreter load / status bookkeeping
# ---------------------------------------------------------------------------

def recompute_active_load(interp):
    """active_load = count of interpreter's assignments in ACCEPTED or IN_SESSION."""
    load = 0
    for a in db.assignments.values():
        if a["interpreter_id"] == interp["id"] and a["lifecycle_status"] in ("ACCEPTED", "IN_SESSION"):
            load += 1
    interp["active_load"] = load
    return load


def refresh_interpreter_computed(interp):
    avg, count = calc.rating_aggregate(interp["id"])
    interp["rating_avg"] = avg
    interp["rating_count"] = count
    interp["acceptance_pct"] = calc.acceptance_pct(interp["id"])


# ---------------------------------------------------------------------------
# Offer expiry sweep — observed lazily on read & before any mutation
# ---------------------------------------------------------------------------

def sweep_expired_offers():
    """Expire any OFFERED assignment whose TTL has elapsed; bubble request to OPEN."""
    now = db.clock.now()
    for a in list(db.assignments.values()):
        if a["lifecycle_status"] != "OFFERED":
            continue
        deadline = parse_iso(a["offered_at"]) + timedelta(seconds=C.OFFER_TTL_SECONDS)
        if now >= deadline:
            a["lifecycle_status"] = "EXPIRED"
            db.touch(a)
            interp = db.interpreters.get(a["interpreter_id"])
            if interp:
                refresh_interpreter_computed(interp)
                db.touch(interp)
            _bubble_request_to_open(a["request_id"])


def _bubble_request_to_open(request_id):
    req = db.requests.get(request_id)
    if req and req["status"] == "ASSIGNED":
        req["status"] = "OPEN"
        db.touch(req)


# ---------------------------------------------------------------------------
# Assignment completion bubbling
# ---------------------------------------------------------------------------

def complete_assignment(assignment, billing_status):
    """IN_SESSION -> COMPLETED, set billing, decrement load, fulfill request."""
    assignment["lifecycle_status"] = "COMPLETED"
    assignment["billing_status"] = billing_status
    db.touch(assignment)
    interp = db.interpreters.get(assignment["interpreter_id"])
    if interp:
        was_busy = interp["status"] == "BUSY"
        recompute_active_load(interp)
        if was_busy and interp["active_load"] < interp["max_concurrent_load"]:
            interp["status"] = "AVAILABLE"
        db.touch(interp)
    req = db.requests.get(assignment["request_id"])
    if req and req["status"] == "ASSIGNED":
        req["status"] = "FULFILLED"
        db.touch(req)


# ---------------------------------------------------------------------------
# Interpreter deactivation cascade (3 no-show strikes)
# ---------------------------------------------------------------------------

def maybe_deactivate_interpreter(interp):
    if interp["no_show_strikes"] < C.DEACTIVATION_STRIKES:
        return
    interp["status"] = "DEACTIVATED"
    interp["active_load"] = 0
    db.touch(interp)
    # cancel every other still-OFFERED assignment held by this interpreter
    for a in list(db.assignments.values()):
        if a["interpreter_id"] != interp["id"]:
            continue
        if a["lifecycle_status"] == "OFFERED":
            a["lifecycle_status"] = "CANCELLED"
            db.touch(a)
            _bubble_request_to_open(a["request_id"])
