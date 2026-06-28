"""Service-ticket lifecycle + ATM operational_status propagation (PRD §3.8).

MINOR -> ATM FAULTED ; MAJOR -> ATM OUT_OF_SERVICE.
A MAJOR ticket on a FAULTED ATM escalates it to OUT_OF_SERVICE.
resolve/cancel restore IN_SERVICE only if no other OPEN/ACKNOWLEDGED ticket
remains on the ATM. reopen re-faults and increments reopen_count.

operational_status and cash_status are INDEPENDENT dimensions — ticket logic
never touches cash_status.
"""


def _open_ack_tickets(store, atm_id, exclude_id=None):
    out = []
    for t in store.service_tickets.values():
        if t["atm_id"] != atm_id:
            continue
        if t["id"] == exclude_id:
            continue
        if t["status"] in ("OPEN", "ACKNOWLEDGED"):
            out.append(t)
    return out


def apply_fault(store, atm, severity):
    """Drive operational_status when a ticket opens or reopens."""
    if severity == "MAJOR":
        atm["operational_status"] = "OUT_OF_SERVICE"
    else:  # MINOR
        # MINOR forces FAULTED, but never downgrades an OUT_OF_SERVICE machine.
        if atm["operational_status"] != "OUT_OF_SERVICE":
            atm["operational_status"] = "FAULTED"
    store.touch(atm)


def restore_if_clear(store, atm, closing_ticket_id):
    """Return ATM to IN_SERVICE if no other OPEN/ACKNOWLEDGED ticket remains."""
    if not _open_ack_tickets(store, atm["id"], exclude_id=closing_ticket_id):
        atm["operational_status"] = "IN_SERVICE"
        store.touch(atm)
