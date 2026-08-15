"""Log-day workflow routes: finalize (copy rotation + week lock), reconcile
(as-run entries, credits, shortfall, week close), plus the StationAdmin
logical clock. PRD §3.7/§3.8 and §2.5."""

import uuid

from flask import Blueprint

from domain import (
    LATE_PENALTY_PCT, bucket_for, copy_rotation_select, eligible_copy,
    line_of_spot, post_discrepancy_credit, run_completion_sweep,
    usage_snapshot,
)
from helpers import (
    auth, created_key, fail, fmt_clock, json_body, list_response, new_record,
    ok_object, parse_iso_datetime, touch,
)
from serializers import ser_as_run_entry, ser_log_day
from store import db

bp = Blueprint("logs", __name__)


def get_log_day_or_404(log_day_id):
    rec = db.log_days.get(log_day_id)
    if rec is None:
        fail("ERR_NOT_FOUND", "log day %s not found" % log_day_id)
    return rec


def scheduled_spots_on(date_str):
    return sorted(
        (
            s
            for s in db.spots.values()
            if s["status"] == "SCHEDULED" and s["scheduled_air_date"] == date_str
        ),
        key=created_key,
    )


# ---------------------------------------------------------------------------
# Finalization (PRD §3.7)
# ---------------------------------------------------------------------------

@bp.post("/traffic/log-days/<log_day_id>/finalize")
def finalize_log_day(log_day_id):
    auth("TrafficManager")
    log = get_log_day_or_404(log_day_id)
    # State legality (4): only a DRAFT log can be finalized.
    if log["status"] != "DRAFT":
        fail(
            "ERR_INVALID_STATE",
            "log day in status %s cannot be finalized" % log["status"],
        )
    # Date window (5): only today or future logs may be finalized.
    if log["log_date"] < db.now.date().isoformat():
        fail("ERR_DATE_WINDOW", "cannot finalize a past log")
    spots = scheduled_spots_on(log["log_date"])
    # Cross-reference coherence (6): an advertiser holding RECEIVED copy but
    # none matching the line's length is a reference mismatch.
    for spot in spots:
        line = line_of_spot(spot)
        advertiser_id = db.orders[line["order_id"]]["advertiser_id"]
        received = [
            c
            for c in db.copy_instructions.values()
            if c["advertiser_id"] == advertiser_id and c["status"] == "RECEIVED"
        ]
        if received and not any(
            c["length_seconds"] == line["spot_length_seconds"] for c in received
        ):
            fail(
                "ERR_REFERENCE_MISMATCH",
                "no RECEIVED copy matches the line's spot_length_seconds",
            )
    # Log completeness (10): every scheduled spot must have resolvable copy.
    for spot in spots:
        line = line_of_spot(spot)
        advertiser_id = db.orders[line["order_id"]]["advertiser_id"]
        if not eligible_copy(advertiser_id, line["spot_length_seconds"]):
            fail(
                "ERR_COPY_NOT_RECEIVED",
                "scheduled spot has no RECEIVED copy of matching length",
            )
    # Side effects: deterministic weighted round-robin copy assignment in
    # spot creation order, scored against the times-used snapshot taken at
    # the start of this finalize run (PRD §3.7).
    snapshot = usage_snapshot()
    for spot in spots:
        line = line_of_spot(spot)
        advertiser_id = db.orders[line["order_id"]]["advertiser_id"]
        winner = copy_rotation_select(
            eligible_copy(advertiser_id, line["spot_length_seconds"]), snapshot
        )
        spot["copy_instruction_id"] = winner["id"]
        touch(spot)
    log["status"] = "FINALIZED"
    touch(log)
    # Finalizing any single log day locks the owning week (OPEN -> LOCKED).
    week = db.avail_weeks[log["avail_week_id"]]
    if week["status"] == "OPEN":
        week["status"] = "LOCKED"
        touch(week)
    return ok_object(ser_log_day(log))


# ---------------------------------------------------------------------------
# Reconciliation (PRD §3.8)
# ---------------------------------------------------------------------------

@bp.post("/traffic/log-days/<log_day_id>/reconcile")
def reconcile_log_day(log_day_id):
    auth("BillingClerk")
    log = get_log_day_or_404(log_day_id)
    # State legality (4): only a FINALIZED log can be reconciled.
    if log["status"] != "FINALIZED":
        fail(
            "ERR_INVALID_STATE",
            "log day in status %s cannot be reconciled" % log["status"],
        )
    data = json_body()
    entries = data.get("entries")
    # Payload completeness (11): exactly one entry per SCHEDULED spot of the
    # log date — no missing, no extras, no duplicates.
    expected = {s["id"]: s for s in scheduled_spots_on(log["log_date"])}
    if not isinstance(entries, list):
        fail("ERR_RECONCILE_MISMATCH", "entries must be a list of as-run records")
    seen = set()
    normalized = []
    for entry in entries:
        if not isinstance(entry, dict):
            fail("ERR_RECONCILE_MISMATCH", "each entry must be an object")
        spot_id = entry.get("spot_id")
        if spot_id not in expected or spot_id in seen:
            fail(
                "ERR_RECONCILE_MISMATCH",
                "entries must cover exactly the log's scheduled spots",
            )
        seen.add(spot_id)
        aired = entry.get("aired")
        if not isinstance(aired, bool):
            fail("ERR_RECONCILE_MISMATCH", "each entry must report aired as a boolean")
        actual_rating = entry.get("actual_rating")
        if aired and actual_rating is None:
            fail(
                "ERR_RECONCILE_MISMATCH",
                "aired entry must supply actual_rating",
            )
        normalized.append((spot_id, aired, actual_rating))
    if seen != set(expected):
        fail(
            "ERR_RECONCILE_MISMATCH",
            "entries must cover exactly the log's scheduled spots",
        )
    # Field sanity (13): measured ratings, when supplied, must be non-negative
    # numbers.
    for spot_id, aired, actual_rating in normalized:
        if actual_rating is not None and (
            isinstance(actual_rating, bool)
            or not isinstance(actual_rating, (int, float))
            or actual_rating < 0
        ):
            fail("ERR_INVALID_REQUEST", "actual_rating must be a non-negative number")
    # Apply: one append-only AsRunEntry per payload entry, then each spot
    # transitions per its outcome.
    for spot_id, aired, actual_rating in normalized:
        spot = db.spots[spot_id]
        entry = {
            "id": str(uuid.uuid4()),
            "created_at": db.now,
            "_seq": db.next_seq(),
            "log_day_id": log["id"],
            "spot_id": spot_id,
            "aired": aired,
            "actual_rating": actual_rating,
        }
        db.as_run_entries[entry["id"]] = entry
        line = line_of_spot(spot)
        if aired:
            spot["status"] = "AIRED"
            touch(spot)
        else:
            # Missed at air time: treated as a preemption discovered at
            # reconcile — OVERSOLD, seconds released, late-tier credit posted.
            unit = db.avail_units[spot["avail_unit_id"]]
            unit[bucket_for(spot)] -= line["spot_length_seconds"]
            touch(unit)
            spot["status"] = "PREEMPTED"
            spot["preempt_reason"] = "OVERSOLD"
            touch(spot)
            order = db.orders[line["order_id"]]
            post_discrepancy_credit(order["id"], spot, LATE_PENALTY_PCT)
    log["status"] = "RECONCILED"
    touch(log)
    # When every log day of the owning week is RECONCILED the week CLOSES.
    week = db.avail_weeks[log["avail_week_id"]]
    week_logs = [l for l in db.log_days.values() if l["avail_week_id"] == week["id"]]
    if all(l["status"] == "RECONCILED" for l in week_logs) and week["status"] != "CLOSED":
        week["status"] = "CLOSED"
        touch(week)
    return ok_object(ser_log_day(log))


# ---------------------------------------------------------------------------
# As-run entry listings
# ---------------------------------------------------------------------------

@bp.get("/traffic/log-days/<log_day_id>/as-run-entries")
def list_log_day_as_run_entries(log_day_id):
    auth("TrafficManager", "BillingClerk", "StationAdmin")
    get_log_day_or_404(log_day_id)
    items = [e for e in db.as_run_entries.values() if e["log_day_id"] == log_day_id]
    return list_response(items, ser_as_run_entry)


# ---------------------------------------------------------------------------
# Logical clock (PRD §2.5)
# ---------------------------------------------------------------------------

@bp.post("/traffic/_clock/set_current_utc")
def set_current_utc():
    auth("StationAdmin")
    data = json_body()
    to_iso8601 = data.get("to_iso8601")
    if to_iso8601 is None:
        fail("ERR_INVALID_REQUEST", "to_iso8601 is required")
    db.now = parse_iso_datetime(to_iso8601)
    # Advancing the clock runs the order completion sweep (PRD §3.4).
    run_completion_sweep()
    return ok_object({"current_utc": fmt_clock(db.now)})
