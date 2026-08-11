"""The agent-of-record selector and the bounded overlap window (PRD 3.3)."""

import lookup
import timeutil


def select_agent_of_record(registration):
    """Candidates are APPOINTED or RESIGNATION_NOTICED appointments whose
    notice window has not closed (strict <).  A RESIGNATION_NOTICED row
    outranks an APPOINTED one, which is what creates the bounded overlap."""
    clock_date = timeutil.today()
    appointments = lookup.appointments_of_registration(registration["id"])
    candidates = [
        a
        for a in appointments
        if a["status"] in ("APPOINTED", "RESIGNATION_NOTICED")
        and (a["resignation_effective_on"] is None or clock_date < a["resignation_effective_on"])
    ]
    winner = None
    if candidates:
        candidates.sort(
            key=lambda a: (
                0 if a["status"] == "RESIGNATION_NOTICED" else 1,
                a["appointed_on"],
                a["created_at"],
                a["_seq"],
            )
        )
        winner = candidates[0]
    for appointment in appointments:
        appointment["of_record"] = winner is not None and appointment["id"] == winner["id"]
    registration["agent_of_record_id"] = winner["id"] if winner else None
    return winner
