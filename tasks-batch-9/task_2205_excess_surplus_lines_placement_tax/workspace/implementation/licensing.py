"""Rung 11 of the ladder: broker licensing (PRD 2.11 item 11)."""

import serialize
import store

SURPLUS_LINES = "SURPLUS_LINES"


def has_active_surplus_lines(broker_id, state_code):
    """True when the brokerage holds a SURPLUS_LINES licence for state_code whose
    computed status is ACTIVE. A licence expiring exactly now is already LAPSED."""
    for rec in store.licenses_of_broker(broker_id):
        if rec.get("license_type") != SURPLUS_LINES:
            continue
        if rec.get("state_code") != state_code:
            continue
        if serialize.license_status(rec) == "ACTIVE":
            return True
    return False
