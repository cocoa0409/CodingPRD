"""Rungs 18 and 19 -- the state gate.

ADJUDICATION of friction 1 (rung 18 ERR_INVALID_STATE vs rung 19
ERR_ALREADY_TERMINAL on a terminal row).

PRD §2.6 states the lowest-number-wins principle and, in the same breath, "the
expectation that ERR_ALREADY_TERMINAL is reachable", then hands the conflict to
the implementer. Taken literally, rung 18 would fire first on EVERY terminal row
(a terminal state by definition declares no outgoing transition), which makes
ERR_ALREADY_TERMINAL unreachable everywhere and deletes one of the sixty-one
declared error codes from the API.

Reachability-maximising reading: the terminal test is evaluated first. A row
sitting in one of its machine's terminal states reports ERR_ALREADY_TERMINAL; a
row in a non-terminal state that has no declared transition for the requested
trigger reports ERR_INVALID_STATE. Both codes stay reachable, and no declared
behaviour is lost -- no transition in §1.2 originates from a terminal state, so
nothing legitimate is blocked by ordering the terminal test first.
"""

from errors import ApiError

TERMINAL = {
    "account_status": ("CANCELLED",),
    "account_legal_hold": (),
    "member_status": ("REMOVED",),
    "member_authorization": (),
    "profile_status": ("RETIRED",),
    "scan_status": ("COMPLETED", "CANCELLED"),
    "exposure_status": (),
    "removal_status": ("COMPLETED", "VOIDED"),
    "document_status": ("REJECTED", "EXPIRED"),
    "alert_status": ("RESOLVED",),
    "alert_severity": (),
    "addon_status": ("CANCELLED",),
    "seat_status": (),
    "cycle_status": ("CLOSED",),
    "finding_status": (),
}


def gate(machine, current, allowed_from):
    """Rung 19 then rung 18 -- see the module adjudication."""
    # Adjudication of friction 1: terminal test first so ERR_ALREADY_TERMINAL
    # remains reachable.
    if current in TERMINAL[machine]:
        raise ApiError("ERR_ALREADY_TERMINAL")
    if current not in allowed_from:
        raise ApiError("ERR_INVALID_STATE")
