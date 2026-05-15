"""Yield sweep + history routes."""
from __future__ import annotations

from flask import Blueprint, request

from core.auth import require_roles
from core.clock import clock
from core.errors import raise_error
from core.pagination import page, parse_pagination
from core.response import success_array, success_object
from core.store import store
from services.calculations import compute_yield_batch_size
from services.engine import (
    cascade_revoke_aid_for_application,
    get_university,
    recompute_rank_score,
)
from services.serializers import sweep_out
from services.time_utils import add_days, parse_iso

bp = Blueprint("yield_management", __name__)


@bp.post("/universities/<university_id>/yield-sweep")
@require_roles("AdmissionsOfficer", "PlatformAdmin")
def run_yield_sweep(university_id: str):
    uni = get_university(university_id)
    sweep_lock = store.get_sweep_lock(uni["id"])
    if not sweep_lock.acquire(blocking=False):
        raise_error("ERR_SWEEP_IN_PROGRESS")
    try:
        now = clock.iso()
        epoch_start_enrolled = uni.get("enrolled_count", 0)

        # ---- Stage 1: auto-revoke past-deadline admitted applications ----
        for app in list(store.applications.values()):
            program = store.programs.get(app["program_id"])
            if program is None or program["university_id"] != uni["id"]:
                continue
            if app["status"] != "ADMITTED":
                continue
            if not app.get("enrollment_deadline"):
                continue
            if parse_iso(now) > parse_iso(app["enrollment_deadline"]):
                app["status"] = "WITHDRAWN"
                store.bump(app)
                if program.get("admitted_count", 0) > 0:
                    program["admitted_count"] = program["admitted_count"] - 1
                    store.bump(program)
                cascade_revoke_aid_for_application(app["id"])

        # ---- Stage 2: recycle expired waitlist offers ----
        for entry in store.waitlist_entries.values():
            program = store.programs.get(entry["program_id"])
            if program is None or program["university_id"] != uni["id"]:
                continue
            if entry["status"] != "OFFERED":
                continue
            if not entry.get("offer_expires_at"):
                continue
            if parse_iso(now) > parse_iso(entry["offer_expires_at"]):
                # Revert provisional reservation
                if program.get("admitted_count", 0) > 0:
                    program["admitted_count"] = program["admitted_count"] - 1
                    store.bump(program)
                entry["status"] = "ACTIVE"
                entry["offered_at"] = None
                entry["offer_expires_at"] = None
                store.bump(entry)
                recompute_rank_score(entry)

        # ---- Stage 3: compute batch size ----
        uni_programs = [p for p in store.programs.values() if p["university_id"] == uni["id"]]
        admitted_open = sum(max(0, p["capacity"] - p.get("admitted_count", 0)) for p in uni_programs)
        batch_size = compute_yield_batch_size(
            target=uni.get("yield_target_count", 0),
            enrolled=uni.get("enrolled_count", 0),
            admitted_open=admitted_open,
        )

        # ---- Stage 4: promote ACTIVE waitlist entries in rank order ----
        # Recompute every ACTIVE entry's rank_score so up-to-date tenure/interest values apply.
        candidates = []
        for entry in store.waitlist_entries.values():
            program = store.programs.get(entry["program_id"])
            if program is None or program["university_id"] != uni["id"]:
                continue
            if entry["status"] != "ACTIVE":
                continue
            recompute_rank_score(entry)
            candidates.append(entry)

        candidates.sort(
            key=lambda e: (
                -float(e.get("rank_score") or 0),  # rank DESC
                e["created_at"],                    # then oldest first
                e["id"],                            # then lex id
            )
        )

        offers_extended = 0
        for entry in candidates:
            if offers_extended >= batch_size:
                break
            program = store.programs.get(entry["program_id"])
            if program is None:
                continue
            if program.get("admitted_count", 0) >= program["capacity"]:
                continue
            entry["status"] = "OFFERED"
            entry["offered_at"] = now
            entry["offer_expires_at"] = add_days(now, 7)
            store.bump(entry)
            program["admitted_count"] = program.get("admitted_count", 0) + 1
            store.bump(program)
            offers_extended += 1

        # Determine epoch: prior count + 1.
        prior = [s for s in store.yield_sweeps.values() if s["university_id"] == uni["id"]]
        epoch = len(prior) + 1

        sweep_stamp = store.stamp_create(with_version=False)
        sweep = {
            "id": sweep_stamp["id"],
            "created_at": sweep_stamp["created_at"],
            "university_id": uni["id"],
            "epoch": epoch,
            "enrolled_count_at_start": epoch_start_enrolled,
            "offers_extended": offers_extended,
            "ran_at": now,
        }
        store.yield_sweeps[sweep["id"]] = sweep

        # Refresh university.enrolled_count via direct recount (defensive) and bump.
        new_enrolled = sum(
            1
            for a in store.applications.values()
            if a["status"] == "ENROLLED"
            and store.programs.get(a["program_id"]) is not None
            and store.programs[a["program_id"]]["university_id"] == uni["id"]
        )
        if new_enrolled != uni.get("enrolled_count", 0):
            uni["enrolled_count"] = new_enrolled
            store.bump(uni)

        return success_object(sweep_out(sweep), 200)
    finally:
        sweep_lock.release()


@bp.get("/universities/<university_id>/yield-sweeps")
@require_roles("AdmissionsOfficer", "PlatformAdmin")
def list_yield_sweeps(university_id: str):
    get_university(university_id)
    limit, offset = parse_pagination()
    items = [s for s in store.yield_sweeps.values() if s["university_id"] == university_id]
    items.sort(key=lambda s: s["created_at"])
    page_items, total = page(items, limit, offset)
    return success_array([sweep_out(s) for s in page_items], limit, offset, total, 200)
