"""No-show + standby promotion + accommodation expiry sweep for one TestEvent."""

from datetime import timedelta

import db
from clock import now
from config import CHECK_IN_GRACE_HOURS
from errors import err_invalid_request
from response import parse_iso_utc
from services.capacity_service import reconcile_capacity, standby_promotion_selector
from services.test_event_service import get_test_event_or_404, _apply_time_gated_transitions


def run_sweep(test_event_id: str) -> dict:
    e = get_test_event_or_404(test_event_id)
    current_now = now()
    test_date = parse_iso_utc(e["test_date"])
    no_show_deadline = test_date + timedelta(hours=CHECK_IN_GRACE_HOURS)

    no_show_count = 0
    # Track per-pair (general seats freed, accommodation seats freed) for the
    # standby promotion selector inputs (PRD §3.4 N, K).
    pair_freed: dict = {}

    # 1) Mark CONFIRMED registrations whose check-in window has passed as NO_SHOW.
    if current_now > no_show_deadline:
        for r in db.registrations.all():
            if r["test_event_id"] != test_event_id:
                continue
            if r["status"] == "CONFIRMED":
                pair = (r["test_event_id"], r["test_center_id"])
                acc = bool(r.get("accommodation_required"))
                r["status"] = "NO_SHOW"
                db.touch(r)
                no_show_count += 1
                n_freed, k_freed = pair_freed.get(pair, (0, 0))
                n_freed += 1
                if acc:
                    k_freed += 1
                pair_freed[pair] = (n_freed, k_freed)

    # 2) Per-TestCenter, run the standby promotion selector.
    promotions = 0
    # Also consider centers that had no no-shows but might need promotion if
    # capacity already exists (e.g., the caller invoked sweep just to fix the
    # ledger). We iterate over all capacity rows for this event.
    pairs_for_reconcile = set(pair_freed.keys())
    for cap in db.test_center_capacities.all():
        if cap["test_event_id"] != test_event_id:
            continue
        pairs_for_reconcile.add((test_event_id, cap["test_center_id"]))

    for ev_id, c_id in list(pairs_for_reconcile):
        reconcile_capacity(ev_id, c_id)
        n_freed, k_freed = pair_freed.get((ev_id, c_id), (0, 0))
        if n_freed > 0:
            promotions += standby_promotion_selector(
                ev_id, c_id,
                seats_freed=n_freed, accommodation_seats_freed=k_freed,
            )

    # 3) Expire accommodation requests whose review_deadline_at has passed.
    expired_accommodations = 0
    for a in db.accommodation_requests.all():
        if a["status"] in ("SUBMITTED", "UNDER_REVIEW", "NEEDS_MORE_INFO"):
            deadline = parse_iso_utc(a["review_deadline_at"])
            if current_now > deadline:
                a["status"] = "EXPIRED"
                db.touch(a)
                expired_accommodations += 1

    # Record that a sweep has been called for this event after test_date
    # (precondition for REGISTRATION_CLOSED → SCORES_PENDING).
    if current_now >= test_date:
        db.sweep_called_after_test_date[test_event_id] = True

    # After the sweep, the time-gated transition for REGISTRATION_CLOSED →
    # SCORES_PENDING may now be eligible.
    _apply_time_gated_transitions(e)

    return {
        "no_show_count": no_show_count,
        "promotions": promotions,
        "expired_accommodations": expired_accommodations,
    }
