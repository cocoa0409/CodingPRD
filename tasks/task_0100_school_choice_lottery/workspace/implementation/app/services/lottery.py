"""Lottery draw and ranking — SCAFFOLD §1.3 lottery_selection / PRD §3.5."""
from datetime import timedelta

from ..calculations import (OFFER_RESPONSE_HOURS, PRIORITY_RANK,
                            compute_lottery_score)
from ..clock import clock_now_dt, clock_now_iso, format_iso
from ..errors import APIError
from ..store import get_store, new_id, now_iso, stamp_update


def run_lottery_draw(program: dict) -> dict:
    """Run the deterministic lottery for a program. Caller validates preconditions."""
    store = get_store()
    pid = program["id"]
    seed = program["lottery_seed"]

    submitted_apps = [a for a in store.applications.values()
                      if a["program_id"] == pid and a["status"] == "SUBMITTED"]

    # Compute lottery_score for each submitted application
    for app in submitted_apps:
        app["lottery_score"] = compute_lottery_score(
            float(app["lottery_weight"]), seed, app["id"]
        )
        stamp_update(app)

    # Sort by (priority_category rank ASC, lottery_score DESC, created_at ASC, id ASC)
    def sort_key(a):
        return (
            PRIORITY_RANK[a["priority_category"]],
            -float(a["lottery_score"]),
            a["created_at"],
            a["id"],
        )

    ranked = sorted(submitted_apps, key=sort_key)

    seats_total = int(program["seats_total"])
    now_dt = clock_now_dt()
    offer_expires_iso = format_iso(now_dt + timedelta(hours=OFFER_RESPONSE_HOURS))

    offers_count = 0
    for idx, app in enumerate(ranked):
        if idx < seats_total:
            app["status"] = "OFFERED"
            app["offer_expires_at"] = offer_expires_iso
            app["waitlist_position"] = None
            stamp_update(app)
            offers_count += 1
        else:
            app["status"] = "WAITLISTED"
            app["waitlist_position"] = idx - seats_total + 1
            stamp_update(app)

    # Program transitions to LOTTERY_DRAWN
    program["window_status"] = "LOTTERY_DRAWN"
    # seats_offered = number of OFFERED + ACCEPTED in this program
    offered_count = sum(1 for a in store.applications.values()
                        if a["program_id"] == pid and a["status"] in ("OFFERED", "ACCEPTED"))
    accepted_count = sum(1 for a in store.applications.values()
                         if a["program_id"] == pid and a["status"] == "ACCEPTED")
    program["seats_offered"] = offered_count
    program["seats_accepted"] = accepted_count
    stamp_update(program)

    # Create LotteryRun audit record
    lr = {
        "id": new_id(),
        "program_id": pid,
        "seed_used": seed,
        "drawn_at": clock_now_iso(),
        "applications_ranked": [
            {
                "application_id": a["id"],
                "lottery_score": float(a["lottery_score"]),
                "rank": i + 1,
            }
            for i, a in enumerate(ranked)
        ],
        "offers_issued_count": offers_count,
        "created_at": now_iso(),
    }
    store.lottery_runs[lr["id"]] = lr
    return lr
