"""Cascades and state-machine side effects (SCAFFOLD §1.2 / PRD §2.9, §3.8)."""

from db import DB, now_ts
from services.calculations import compact_stage_sequence


def touch(resource):
    resource["updated_at"] = now_ts()
    resource["version"] += 1


# ---------------------------------------------------------------------------
# Contest cancellation cascade (PRD §2.9): entries -> WITHDRAWN, booked
# pre-judging slots -> OPEN, queued perf slots -> SKIPPED (NO resequence),
# green-room bookings -> CANCELLED.
# ---------------------------------------------------------------------------

def contest_cancel_cascade(contest):
    ts = now_ts()
    contest_id = contest["id"]

    for entry in DB.entries.values():
        if entry["contest_id"] == contest_id and entry["status"] not in ("WITHDRAWN", "DISQUALIFIED"):
            entry["status"] = "WITHDRAWN"
            entry["updated_at"] = ts
            entry["version"] += 1

    for slot in DB.prejudging_slots.values():
        if slot.get("booked_entry_id"):
            entry = DB.entries.get(slot["booked_entry_id"])
            if entry and entry["contest_id"] == contest_id and slot["status"] == "BOOKED":
                slot["status"] = "OPEN"
                slot["booked_entry_id"] = None
                slot["updated_at"] = ts
                slot["version"] += 1

    for slot in DB.performance_slots.values():
        if slot["contest_id"] == contest_id and slot["status"] == "QUEUED":
            slot["status"] = "SKIPPED"
            slot["updated_at"] = ts
            slot["version"] += 1

    for booking in DB.green_room_bookings.values():
        if booking["contest_id"] == contest_id and booking["status"] == "BOOKED":
            booking["status"] = "CANCELLED"
            booking["updated_at"] = ts
            booking["version"] += 1


# ---------------------------------------------------------------------------
# Tabulation reopen cascade (Category TABULATED -> SCORING): sibling PLACED
# entries revert to PERFORMED with placement fields cleared; parent contest in
# TABULATION reverts to JUDGING (bubble-up).
# ---------------------------------------------------------------------------

def tabulation_reopen_cascade(category):
    if category["status"] != "TABULATED":
        return
    ts = now_ts()
    category["status"] = "SCORING"
    category["updated_at"] = ts
    category["version"] += 1

    for entry in DB.entries.values():
        if entry["category_id"] == category["id"] and entry["status"] == "PLACED":
            entry["status"] = "PERFORMED"
            entry["placement_rank"] = None
            entry["final_score"] = None
            entry["craftsmanship_mean"] = None
            entry["updated_at"] = ts
            entry["version"] += 1

    contest = DB.contest_events.get(category["contest_id"])
    if contest and contest["status"] == "TABULATION":
        contest["status"] = "JUDGING"
        contest["updated_at"] = ts
        contest["version"] += 1


# ---------------------------------------------------------------------------
# WITHDRAW cascade (Entry): booked pre-judging slot -> OPEN; QUEUED/ON_STAGE
# performance slot -> SKIPPED; then stage_sequence_compaction.
# ---------------------------------------------------------------------------

def withdraw_cascade(entry):
    ts = now_ts()
    for slot in DB.prejudging_slots.values():
        if slot["status"] == "BOOKED" and slot.get("booked_entry_id") == entry["id"]:
            slot["status"] = "OPEN"
            slot["booked_entry_id"] = None
            slot["updated_at"] = ts
            slot["version"] += 1

    skipped_any = False
    for slot in DB.performance_slots.values():
        if slot["entry_id"] == entry["id"] and slot["status"] in ("QUEUED", "ON_STAGE"):
            slot["status"] = "SKIPPED"
            slot["updated_at"] = ts
            slot["version"] += 1
            skipped_any = True
    if skipped_any:
        compact_stage_sequence(entry["contest_id"])


# ---------------------------------------------------------------------------
# DISQUALIFY cascade (PRD §3.8): link 1 sheets -> VOID; link 2 tabulation
# reopen on the category; link 3 contest bubble-up (handled inside reopen);
# fan-out: prejudging release, perf skip + compaction, award revoke w/ budget.
# ---------------------------------------------------------------------------

def disqualify_cascade(entry):
    ts = now_ts()
    category = DB.categories.get(entry["category_id"])

    # Link 1: void all non-VOID scoresheets of this entry.
    for sheet in DB.scoresheets.values():
        if sheet["entry_id"] == entry["id"] and sheet["status"] in ("DRAFT", "SUBMITTED", "LOCKED"):
            sheet["status"] = "VOID"
            sheet["updated_at"] = ts
            sheet["version"] += 1

    # Fan-out: pre-judging release.
    for slot in DB.prejudging_slots.values():
        if slot["status"] == "BOOKED" and slot.get("booked_entry_id") == entry["id"]:
            slot["status"] = "OPEN"
            slot["booked_entry_id"] = None
            slot["updated_at"] = ts
            slot["version"] += 1

    # Fan-out: performance skip + compaction.
    skipped_any = False
    for slot in DB.performance_slots.values():
        if slot["entry_id"] == entry["id"] and slot["status"] in ("QUEUED", "ON_STAGE"):
            slot["status"] = "SKIPPED"
            slot["updated_at"] = ts
            slot["version"] += 1
            skipped_any = True
    if skipped_any:
        compact_stage_sequence(entry["contest_id"])

    # Fan-out: revoke PENDING/APPROVED awards of this entry (budget restore is
    # implicit — budget_reserved_cents is computed from statuses).
    for award in DB.prize_awards.values():
        if award["entry_id"] == entry["id"] and award["status"] in ("PENDING", "APPROVED"):
            award["status"] = "REVOKED"
            award["updated_at"] = ts
            award["version"] += 1

    # Clear own placement fields if it was PLACED (title stripped).
    if entry["placement_rank"] is not None or entry["status"] == "PLACED":
        entry["placement_rank"] = None
        entry["final_score"] = None
        entry["craftsmanship_mean"] = None

    # Link 2 + 3: tabulation reopen cascade on the category (contest bubble-up
    # happens inside). Fires because voiding sheets breaks locked-sheet
    # completeness of a TABULATED category.
    if category is not None:
        tabulation_reopen_cascade(category)
