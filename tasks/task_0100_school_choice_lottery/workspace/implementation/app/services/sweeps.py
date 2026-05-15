"""Clock-driven sweeps and waitlist-backfill cascade.

Encapsulates the system-driven side effects fired both by POST /_clock/advance
and by application state transitions (decline, expire, accept-cascade, withdraw).
"""
from datetime import timedelta

from ..calculations import OFFER_RESPONSE_HOURS
from ..clock import clock_now_dt, format_iso, parse_iso
from ..store import get_store, new_id, now_iso, stamp_update


def _program_for_app(app: dict) -> dict:
    return get_store().programs[app["program_id"]]


def recompute_seats(program: dict) -> None:
    store = get_store()
    pid = program["id"]
    offered = 0
    accepted = 0
    for a in store.applications.values():
        if a["program_id"] != pid:
            continue
        if a["status"] in ("OFFERED", "ACCEPTED"):
            offered += 1
        if a["status"] == "ACCEPTED":
            accepted += 1
    if program.get("seats_offered") != offered or program.get("seats_accepted") != accepted:
        program["seats_offered"] = offered
        program["seats_accepted"] = accepted
        stamp_update(program)


def _emit_waitlist_event(program_id: str, triggered_by_app_id: str,
                         promoted_app_id) -> dict:
    store = get_store()
    ev = {
        "id": new_id(),
        "program_id": program_id,
        "triggered_by_application_id": triggered_by_app_id,
        "promoted_application_id": promoted_app_id,
        "occurred_at": now_iso(),
        "created_at": now_iso(),
    }
    store.waitlist_events[ev["id"]] = ev
    return ev


def _candidate_set_for_backfill(program_id: str) -> list:
    """Filter applications in WAITLISTED with valid transfer (if cross-district)."""
    store = get_store()
    program = store.programs[program_id]
    school = store.schools[program["school_id"]]
    target_district_id = school["district_id"]
    candidates = []
    for app in store.applications.values():
        if app["program_id"] != program_id:
            continue
        if app["status"] != "WAITLISTED":
            continue
        # Cross-district check: family must reside in another district
        student = store.students[app["student_id"]]
        family = store.families[student["family_id"]]
        if family["residency_district_id"] != target_district_id:
            # cross-district — must have currently APPROVED TransferRequest for this application
            ok = False
            for tr in store.transfer_requests.values():
                if (tr["application_id"] == app["id"]
                        and tr["target_district_id"] == target_district_id
                        and tr["status"] == "APPROVED"):
                    ok = True
                    break
            if not ok:
                continue
        candidates.append(app)
    return candidates


def waitlist_backfill(program_id: str, triggered_by_app_id: str) -> None:
    """Run the waitlist-backfill rule for a freed seat in `program_id`.

    Preserves the snapshot ranking from the LotteryRun. Promotes the highest-ranked
    surviving candidate to OFFERED and re-numbers the remaining waitlist positions.
    Emits a WaitlistEvent regardless of whether a promotion occurred.
    """
    store = get_store()
    program = store.programs[program_id]

    # Find the program's LotteryRun snapshot (the most recent draw for this program).
    snapshot_order = []
    for lr in store.lottery_runs.values():
        if lr["program_id"] == program_id:
            snapshot_order = [entry["application_id"] for entry in lr["applications_ranked"]]
            break

    # Once the first freed transition occurs after LOTTERY_DRAWN, move into BACKFILL.
    if program.get("window_status") == "LOTTERY_DRAWN":
        program["window_status"] = "BACKFILL"
        stamp_update(program)

    candidates = _candidate_set_for_backfill(program_id)
    candidate_ids = {c["id"] for c in candidates}
    ordered_survivors = [aid for aid in snapshot_order if aid in candidate_ids]

    promoted_app_id = None
    if ordered_survivors:
        promotee_id = ordered_survivors[0]
        promotee = store.applications[promotee_id]
        promotee["status"] = "OFFERED"
        promotee["offer_expires_at"] = format_iso(clock_now_dt() + timedelta(hours=OFFER_RESPONSE_HOURS))
        promotee["waitlist_position"] = None
        stamp_update(promotee)
        promoted_app_id = promotee_id
        # Renumber the survivors below the promotee
        for i, aid in enumerate(ordered_survivors[1:], start=1):
            app = store.applications[aid]
            if app.get("waitlist_position") != i:
                app["waitlist_position"] = i
                stamp_update(app)
    else:
        # No promotion — still renumber existing waitlist positions (they may have shifted).
        for i, aid in enumerate(ordered_survivors, start=1):
            app = store.applications[aid]
            if app.get("waitlist_position") != i:
                app["waitlist_position"] = i
                stamp_update(app)

    recompute_seats(program)
    _emit_waitlist_event(program_id, triggered_by_app_id, promoted_app_id)


def recompute_waitlist_positions(program_id: str) -> None:
    """Recompute waitlist positions in snapshot order for a program (no promotion)."""
    store = get_store()
    snapshot_order = []
    for lr in store.lottery_runs.values():
        if lr["program_id"] == program_id:
            snapshot_order = [entry["application_id"] for entry in lr["applications_ranked"]]
            break
    survivors = [aid for aid in snapshot_order
                 if aid in store.applications and store.applications[aid]["status"] == "WAITLISTED"]
    # The candidate set already filters cross-district transfers; here we just renumber
    # whatever WAITLISTED applications exist (revoke-cascade calls waitlist_backfill for
    # promotion handling).
    for i, aid in enumerate(survivors, start=1):
        app = store.applications[aid]
        if app.get("waitlist_position") != i:
            app["waitlist_position"] = i
            stamp_update(app)


# ---------------------------------------------------------------------------
# Clock-advance sweeps
# ---------------------------------------------------------------------------

def sweep_after_clock_advance() -> None:
    """Apply all due time-driven transitions in deterministic order.

    Order:
      1) Programs SCHEDULED -> OPEN if registration_open_at <= now < close.
      2) Programs OPEN -> CLOSED if now >= registration_close_at; cascade DRAFT -> WITHDRAWN.
      3) Applications OFFERED -> EXPIRED if offer_expires_at has passed; cascade backfill.
    """
    store = get_store()
    now = clock_now_dt()

    # Process programs sorted by id for determinism.
    program_ids = sorted(store.programs.keys())

    # Step 1: SCHEDULED -> OPEN
    for pid in program_ids:
        prog = store.programs[pid]
        if prog["window_status"] != "SCHEDULED":
            continue
        open_at = parse_iso(prog["registration_open_at"])
        close_at = parse_iso(prog["registration_close_at"])
        if open_at <= now < close_at:
            prog["window_status"] = "OPEN"
            stamp_update(prog)

    # Step 2: OPEN/SCHEDULED -> CLOSED when window has fully passed
    for pid in program_ids:
        prog = store.programs[pid]
        if prog["window_status"] not in ("SCHEDULED", "OPEN"):
            continue
        close_at = parse_iso(prog["registration_close_at"])
        if now >= close_at:
            prog["window_status"] = "CLOSED"
            stamp_update(prog)
            # Cascade DRAFT -> WITHDRAWN
            for app in store.applications.values():
                if app["program_id"] == pid and app["status"] == "DRAFT":
                    app["status"] = "WITHDRAWN"
                    stamp_update(app)

    # Step 3: OFFERED -> EXPIRED (and run waitlist_backfill on each).
    # Iterate over a snapshot so backfill-induced status changes don't disturb us.
    expired_targets = []
    for aid, app in store.applications.items():
        if app["status"] != "OFFERED" or not app.get("offer_expires_at"):
            continue
        exp = parse_iso(app["offer_expires_at"])
        if now >= exp:
            expired_targets.append(aid)
    expired_targets.sort()  # deterministic order
    for aid in expired_targets:
        app = store.applications[aid]
        if app["status"] != "OFFERED":  # may have been changed by an earlier sweep
            continue
        app["status"] = "EXPIRED"
        stamp_update(app)
        program = store.programs[app["program_id"]]
        recompute_seats(program)
        waitlist_backfill(program["id"], triggered_by_app_id=aid)
