"""Feed-session settlement under the METERED_ACTUAL variant (PRD §3.8)."""

import db
from calc import TIER_RATE_CENTS_PER_UNIT, settled_charge_cents
from db import store, touch
from util import ceil_units, parse_dt


def ordered_usage_records(session_id):
    """Replay order: sampled_at_utc ASC with created_at ASC as the tie-break."""
    records = db.usage_records_of_session(session_id)
    records.sort(key=lambda r: (parse_dt(r["sampled_at_utc"]),
                                r.get("created_at") or "",
                                r.get("_seq", 0)))
    return records


def settle_and_terminate(session, touch_window=True):
    """Settle a session against reported usage and release its reservation.

    Shared by voluntary termination and by the rights-window revoke cascade;
    both use the METERED_ACTUAL variant, which ignores the booked window
    entirely and prices only what was actually reported.  There is no status
    filter on usage records — they are immutable and every one of them counts.

    ``touch_window`` is False when the caller is the revoke cascade, which is
    already mutating the window row itself and must not bump its ``version``
    once per settled session.
    """
    licensee = store.licensees.get(session["licensee_id"])
    tier_rate = TIER_RATE_CENTS_PER_UNIT[licensee["tier"]] if licensee else 0

    metered_units = 0
    for record in ordered_usage_records(session["id"]):
        metered_units += record["units_charged"]

    settled = settled_charge_cents(metered_units, tier_rate)
    refunded = session["reserved_units"] - ceil_units(metered_units)

    session["metered_units"] = metered_units
    session["settled_charge_cents"] = settled
    session["refunded_units"] = refunded
    session["status"] = "TERMINATED"
    session["halt_reason"] = "CLIENT_REQUEST"
    touch(session)

    if licensee is not None:
        licensee["reserved_units"] = licensee["reserved_units"] - session["reserved_units"]
        licensee["consumed_units"] = licensee["consumed_units"] + ceil_units(metered_units)
        licensee["available_units"] = licensee["available_units"] + refunded
        licensee["settled_charge_cents"] = licensee["settled_charge_cents"] + settled
        touch(licensee)

    window = store.rights_windows.get(session["rights_window_id"])
    if window is not None:
        window["active_feed_session_count"] = max(
            0, window["active_feed_session_count"] - 1)
        if touch_window:
            touch(window)
    return session
