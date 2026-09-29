"""Small guards shared by the route modules."""
import calc
import db
from errors import fail

NOT_FOUND = {
    "member": "ERR_MEMBER_NOT_FOUND",
    "invoice": "ERR_DUES_INVOICE_NOT_FOUND",
    "shell": "ERR_SHELL_NOT_FOUND",
    "report": "ERR_DAMAGE_REPORT_NOT_FOUND",
    "reading": "ERR_READING_NOT_FOUND",
    "session": "ERR_SESSION_NOT_FOUND",
    "regatta": "ERR_REGATTA_NOT_FOUND",
    "entry": "ERR_ENTRY_NOT_FOUND",
    "seat": "ERR_SEAT_NOT_FOUND",
    "heat": "ERR_HEAT_NOT_FOUND",
    "lane": "ERR_LANE_NOT_FOUND",
    "protest": "ERR_PROTEST_NOT_FOUND",
    "trailer": "ERR_TRAILER_NOT_FOUND",
}

STORE = {
    "member": db.members,
    "invoice": db.invoices,
    "shell": db.shells,
    "report": db.reports,
    "reading": db.readings,
    "session": db.sessions,
    "regatta": db.regattas,
    "entry": db.entries,
    "seat": db.seats,
    "heat": db.heats,
    "lane": db.lanes,
    "protest": db.protests,
    "trailer": db.trailers,
}


def load(kind, ident):
    """Ladder rung 3: path identifier existence with the entity-specific 404."""
    rec = STORE[kind].get(ident)
    if rec is None:
        fail(NOT_FOUND[kind], "No %s with id %s." % (kind, ident))
    return rec


def check_fk(kind, data, field):
    """Ladder rung 4: body foreign-key existence, before payload shape."""
    value = data.get(field)
    if isinstance(value, str) and value not in STORE[kind]:
        fail(NOT_FOUND[kind], "No %s with id %s." % (kind, value))
    return value


def not_terminal(kind, rec, field="status"):
    """Ladder rung 8."""
    if rec[field] in calc.TERMINAL[kind]:
        fail("ERR_ALREADY_TERMINAL",
             "This %s is already in terminal state %s." % (kind, rec[field]))
    return rec


def invalid_transition(message="Transition is not permitted from the current state."):
    fail("ERR_INVALID_STATUS_TRANSITION", message)


def member_active(member, what="member"):
    """Ladder rung 21."""
    if member["membership_status"] != "ACTIVE":
        fail("ERR_MEMBER_NOT_ACTIVE",
             "The %s %s is not ACTIVE." % (what, member["id"]))
