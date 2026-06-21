"""Deferred sweep run on clock advance (PRD section 2.5, 3.6-3.8)."""
import db
from services.common import touch


def _has_valid_card_covering(record_id, store, period):
    for m in store.medical_cards.values():
        if m["driver_record_id"] != record_id:
            continue
        if m["status"] == "VALID" and m["valid_through_period"] >= period:
            return True
    return False


def run_sweep(store):
    """Materialize all time-driven transitions in the PRD-defined order:
    1. Expire stale ACTIVE violations.
    2. Expire VALID medical cards past valid_through_period; downgrade CDL.
    3. Mark ACTIVE suspensions whose eligible_period has come due SERVED.
    """
    cur = store.current_period

    # 1. Violations: ACTIVE with (cur - occurred_period) > window -> EXPIRED.
    for v in store.violations.values():
        if v["status"] == "ACTIVE" and (cur - v["occurred_period"]) > db.POINT_WINDOW_PERIODS:
            v["status"] = "EXPIRED"
            touch(v)
        # point_balance is computed on read, so no explicit record recompute needed.

    # 2. Medical cards: VALID with cur > valid_through_period -> EXPIRED.
    for m in store.medical_cards.values():
        if m["status"] == "VALID" and cur > m["valid_through_period"]:
            m["status"] = "EXPIRED"
            touch(m)

    # After expiring cards, downgrade any record whose cdl_status is ACTIVE and
    # has no VALID card covering the current clock.
    for record in store.driver_records.values():
        if record["cdl_status"] == "ACTIVE" and not _has_valid_card_covering(
            record["id"], store, cur
        ):
            record["cdl_status"] = "MEDICALLY_DOWNGRADED"
            touch(record)
            for c in store.cdl_endorsements.values():
                if c["driver_record_id"] == record["id"] and c["status"] == "GRANTED":
                    c["status"] = "SUSPENDED"
                    touch(c)

    # 3. Suspensions: ACTIVE with cur >= eligible_period -> SERVED.
    for s in store.suspensions.values():
        if s["status"] == "ACTIVE" and cur >= s["eligible_period"]:
            s["status"] = "SERVED"
            touch(s)
