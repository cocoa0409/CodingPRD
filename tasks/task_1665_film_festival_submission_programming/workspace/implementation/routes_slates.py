"""Routes: slates, slate entries, invitation responses, bulk issuance."""

from datetime import timedelta

from flask import Blueprint, request

import domain as D
from errors import (err409, err_invalid_state, err_not_found, err_phase,
                    err_referential, err_stale_version)
from store import DB
from util import (auth, check_ownership, created_key, get_body, get_or_404,
                  ok, paginate, require_role, v_bool, v_enum, v_int, v_str)

bp = Blueprint("slates", __name__)

SLATE_READ = ["FESTIVAL_ADMIN", "FESTIVAL_DIRECTOR", "PROGRAM_CHAIR"]
ENTRY_READ = ["FESTIVAL_ADMIN", "FESTIVAL_DIRECTOR", "PROGRAM_CHAIR",
              "SCHEDULING_OPS", "FILMMAKER"]


def _section_category_ok(section, category):
    if category == "SHORT_FILM":
        return section == "SHORTS"
    return section != "SHORTS"


# -------------------------------------------------------------------- slates
@bp.post("/festival/slates")
def create_slate():
    body = get_body()
    edition_id = v_str(body, "edition_id")
    section = v_enum(body, "section", D.SECTIONS)
    capacity_slots = v_int(body, "capacity_slots", min_v=1)
    uid, role = auth()
    require_role(role, ["PROGRAM_CHAIR"])
    if edition_id not in DB.editions:
        raise err_referential("Edition not found")
    if any(s["edition_id"] == edition_id and s["section"] == section
           for s in DB.slates.values()):
        raise err409("ERR_DUPLICATE_SLATE",
                     "A slate for this section already exists in this edition")
    rec = D.new_rec({
        "edition_id": edition_id, "section": section,
        "capacity_slots": capacity_slots, "status": "OPEN",
        "last_entry_added_by": None, "locked_at": None,
    })
    DB.slates[rec["id"]] = rec
    return ok(D.ser_slate(rec), 201)


@bp.get("/festival/slates/<sid>")
def get_slate(sid):
    uid, role = auth()
    require_role(role, SLATE_READ)
    rec = get_or_404(DB.slates, sid)
    return ok(D.ser_slate(rec))


@bp.get("/festival/slates")
def list_slates():
    uid, role = auth()
    require_role(role, SLATE_READ)
    items = list(DB.slates.values())
    edition_id = request.args.get("edition_id")
    status = request.args.get("status")
    if edition_id is not None:
        items = [s for s in items if s["edition_id"] == edition_id]
    if status is not None:
        items = [s for s in items if s["status"] == status]
    items.sort(key=created_key)
    page, meta = paginate(items)
    return ok([D.ser_slate(s) for s in page], pagination=meta)


@bp.post("/festival/slates/<sid>/deliberate")
def deliberate_slate(sid):
    get_body()
    uid, role = auth()
    require_role(role, ["PROGRAM_CHAIR"])
    rec = get_or_404(DB.slates, sid)
    if rec["status"] != "OPEN":
        raise err_invalid_state("Only an OPEN slate may move to DELIBERATING")
    edition = DB.editions.get(rec["edition_id"])
    if edition is None or edition["status"] != "DELIBERATION":
        raise err_phase("Edition is not in DELIBERATION")
    rec["status"] = "DELIBERATING"
    D.touch(rec)
    return ok(D.ser_slate(rec))


@bp.post("/festival/slates/<sid>/entries")
def add_entry(sid):
    body = get_body()
    submission_id = v_str(body, "submission_id")
    expected_version = v_int(body, "expected_slate_version")
    uid, role = auth()
    require_role(role, ["PROGRAM_CHAIR"])
    slate = get_or_404(DB.slates, sid)
    if slate["status"] != "DELIBERATING":
        raise err_invalid_state("Slate is not DELIBERATING")
    sub = DB.submissions.get(submission_id)
    edition = DB.editions.get(slate["edition_id"])
    if edition is None or edition["status"] != "DELIBERATION":
        raise err_phase("Edition is not in DELIBERATION")
    if sub is None:
        raise err_referential("Submission not found")
    if sub["edition_id"] != slate["edition_id"]:
        raise err_referential("Submission belongs to another edition")
    # Structural rules precede the film's own state requirement (PRD §3.5) so
    # that a film already live on this slate reports ERR_DUPLICATE_ENTRY.
    if any(e["slate_id"] == sid and e["submission_id"] == submission_id
           and e["status"] != "DROPPED" for e in DB.entries.values()):
        raise err409("ERR_DUPLICATE_ENTRY",
                     "Submission already has a live entry on this slate")
    if not _section_category_ok(slate["section"], sub["category"]):
        raise err409("ERR_SECTION_CATEGORY_MISMATCH",
                     "Submission category is not allowed in this section")
    if sub["status"] != "IN_SCREENING":
        raise err_invalid_state("Only IN_SCREENING submissions may be nominated")
    if expected_version != slate["version"]:
        raise err_stale_version()
    live = [e for e in DB.entries.values()
            if e["slate_id"] == sid and e["status"] != "DROPPED"]
    rank = max((e["rank_position"] for e in live), default=0) + 1
    rec = D.new_rec({
        "slate_id": sid, "submission_id": submission_id,
        "rank_position": rank, "lane": "UNASSIGNED", "status": "NOMINATED",
        "rsvp_deadline_at": None, "locked_composite_score": None,
        "_ever_held": False,
    })
    DB.entries[rec["id"]] = rec
    sub["status"] = "ADVANCED"
    D.touch(sub)
    slate["last_entry_added_by"] = uid
    D.touch(slate)
    return ok(D.ser_entry(rec), 201)


@bp.get("/festival/slates/<sid>/entries")
def list_slate_entries(sid):
    uid, role = auth()
    require_role(role, ["FESTIVAL_ADMIN", "FESTIVAL_DIRECTOR", "PROGRAM_CHAIR",
                        "FILMMAKER"])
    get_or_404(DB.slates, sid)
    items = [e for e in DB.entries.values() if e["slate_id"] == sid]
    if role == "FILMMAKER":
        own = {s["id"] for s in DB.submissions.values()
               if s["submitter_id"] == uid}
        items = [e for e in items if e["submission_id"] in own]
    status = request.args.get("status")
    if status is not None:
        items = [e for e in items if e["status"] == status]
    # §2.3 exception: slate entries are ordered by rank_position ascending.
    items.sort(key=lambda e: (e["rank_position"], e["_seq"]))
    page, meta = paginate(items)
    return ok([D.ser_entry(e) for e in page], pagination=meta)


@bp.delete("/festival/slates/<sid>/entries/<eid>")
def delete_entry(sid, eid):
    uid, role = auth()
    require_role(role, ["PROGRAM_CHAIR"])
    slate = get_or_404(DB.slates, sid)
    entry = DB.entries.get(eid)
    if entry is None or entry["slate_id"] != sid:
        raise err_not_found()
    if slate["status"] != "DELIBERATING":
        raise err_invalid_state("Entries may be removed only while DELIBERATING")
    if entry["status"] != "NOMINATED":
        raise err_invalid_state("Only a NOMINATED entry may be removed")
    entry["status"] = "DROPPED"
    D.touch(entry)
    sub = DB.submissions.get(entry["submission_id"])
    if sub is not None and sub["status"] == "ADVANCED":
        sub["status"] = "IN_SCREENING"
        D.touch(sub)
    # Compact surviving rank positions upward, preserving relative order.
    survivors = sorted(
        (e for e in DB.entries.values()
         if e["slate_id"] == sid and e["status"] != "DROPPED"),
        key=lambda e: (e["rank_position"], e["_seq"]))
    for i, e in enumerate(survivors, start=1):
        if e["rank_position"] != i:
            e["rank_position"] = i
            D.touch(e)
    D.touch(slate)
    return ok({}, 204)


@bp.post("/festival/slates/<sid>/lock")
def lock_slate(sid):
    get_body()
    uid, role = auth()
    require_role(role, ["FESTIVAL_DIRECTOR"])
    slate = get_or_404(DB.slates, sid)
    if slate["status"] != "DELIBERATING":
        raise err_invalid_state("Only a DELIBERATING slate may be locked")
    live = sorted(
        (e for e in DB.entries.values()
         if e["slate_id"] == sid and e["status"] != "DROPPED"),
        key=lambda e: (e["rank_position"], e["_seq"]))
    # Segregation of duties: the director who placed the last entry may not
    # also certify the slate (fires only when at least one entry exists).
    if live and slate["last_entry_added_by"] == uid:
        raise err409("ERR_SEGREGATION_OF_DUTIES",
                     "The last entry adder may not lock the slate")
    if len(live) < slate["capacity_slots"]:
        raise err409("ERR_SLATE_UNDERFILLED",
                     "Entry count is below the slate capacity")
    for e in live:
        if e["rank_position"] <= slate["capacity_slots"]:
            sub = DB.submissions.get(e["submission_id"])
            comp = sub["composite_score"] if sub else None
            if comp is None or comp < D.SLATE_COMPOSITE_THRESHOLD:
                raise err409("ERR_BELOW_SLATE_THRESHOLD",
                             "A main-lane entry lacks a composite score >= 7.500")
    for e in live:
        e["lane"] = ("MAIN" if e["rank_position"] <= slate["capacity_slots"]
                     else "WAITLIST")
        sub = DB.submissions.get(e["submission_id"])
        e["locked_composite_score"] = (sub["composite_score"]
                                       if sub is not None else None)
        D.touch(e)
    slate["locked_at"] = D.now()
    slate["status"] = "LOCKED"
    D.touch(slate)
    return ok(D.ser_slate(slate))


@bp.post("/festival/slates/<sid>/reopen")
def reopen_slate(sid):
    get_body()
    uid, role = auth()
    require_role(role, ["FESTIVAL_DIRECTOR"])
    slate = get_or_404(DB.slates, sid)
    if slate["status"] != "LOCKED":
        raise err_invalid_state("Only a LOCKED slate may be reopened")
    live = [e for e in DB.entries.values()
            if e["slate_id"] == sid and e["status"] != "DROPPED"]
    if any(e["status"] != "NOMINATED" for e in live):
        raise err_invalid_state(
            "A slate with answered invitations may not be reopened")
    for e in live:
        e["lane"] = "UNASSIGNED"
        e["locked_composite_score"] = None
        D.touch(e)
    slate["status"] = "DELIBERATING"
    D.touch(slate)
    return ok(D.ser_slate(slate))


# ------------------------------------------------------------------- entries
@bp.get("/festival/slate-entries/<eid>")
def get_entry(eid):
    uid, role = auth()
    require_role(role, ENTRY_READ)
    rec = get_or_404(DB.entries, eid)
    if role == "FILMMAKER":
        sub = DB.submissions.get(rec["submission_id"])
        check_ownership(sub is not None and sub["submitter_id"] == uid)
    return ok(D.ser_entry(rec))


@bp.get("/festival/slate-entries")
def list_entries():
    uid, role = auth()
    require_role(role, ENTRY_READ)
    items = list(DB.entries.values())
    if role == "FILMMAKER":
        own = {s["id"] for s in DB.submissions.values()
               if s["submitter_id"] == uid}
        items = [e for e in items if e["submission_id"] in own]
    submission_id = request.args.get("submission_id")
    slate_id = request.args.get("slate_id")
    status = request.args.get("status")
    lane = request.args.get("lane")
    if submission_id is not None:
        items = [e for e in items if e["submission_id"] == submission_id]
    if slate_id is not None:
        items = [e for e in items if e["slate_id"] == slate_id]
    if status is not None:
        items = [e for e in items if e["status"] == status]
    if lane is not None:
        items = [e for e in items if e["lane"] == lane]
    items.sort(key=created_key)
    page, meta = paginate(items)
    return ok([D.ser_entry(e) for e in page], pagination=meta)


@bp.post("/festival/slate-entries/<eid>/respond")
def respond_entry(eid):
    body = get_body()
    accept = v_bool(body, "accept")
    uid, role = auth()
    require_role(role, ["FILMMAKER"])
    entry = get_or_404(DB.entries, eid)
    sub = DB.submissions.get(entry["submission_id"])
    check_ownership(sub is not None and sub["submitter_id"] == uid)
    if entry["status"] != "INVITED":
        raise err_invalid_state("Only an INVITED entry may be answered")
    slate = DB.slates.get(entry["slate_id"])
    if accept:
        entry["status"] = "CONFIRMED"
        D.touch(entry)
        sub["status"] = "CONFIRMED"
        D.touch(sub)
        # Two DRAFT artifacts are born on acceptance: travel package and
        # exhibition agreement (one per confirmed submission, keyed to the
        # accepting entry).
        package = D.new_rec({
            "submission_id": sub["id"], "edition_id": sub["edition_id"],
            "delegate_count": None, "origin_country_code": None,
            "is_international": None, "hotel_nights_requested": None,
            "hotel_nights_allocated": 0, "raw_stipend_cents": None,
            "stipend_cents": 0, "penalty_cents": 0, "status": "DRAFT",
        })
        DB.packages[package["id"]] = package
        agreement = D.new_rec({
            "submission_id": sub["id"], "slate_entry_id": entry["id"],
            "rights_scope": None, "licensed_screening_count": None,
            "used_screening_count": 0, "exclusivity_until": None,
            "revenue_share_pct": None, "submission_version_at_signing": None,
            "status": "DRAFT",
        })
        DB.agreements[agreement["id"]] = agreement
        edition = DB.editions.get(sub["edition_id"])
        if edition is not None:
            D.recompute_edition_ledger(edition)
    else:
        entry["status"] = "DECLINED"
        D.touch(entry)
        sub["status"] = "DECLINED_BY_FILMMAKER"
        D.touch(sub)
        if slate is not None:
            D.promotion_cascade(slate)
    return ok(D.ser_entry(entry))


# ---------------------------------------------------------- issue invitations
@bp.post("/festival/editions/<eid>/issue-invitations")
def issue_invitations(eid):
    get_body()
    uid, role = auth()
    require_role(role, ["FESTIVAL_DIRECTOR"])
    edition = get_or_404(DB.editions, eid)
    if edition["status"] != "NOTIFICATION":
        raise err_phase("Edition is not in NOTIFICATION")
    slates = sorted((s for s in DB.slates.values() if s["edition_id"] == eid),
                    key=created_key)
    if any(s["status"] != "LOCKED" for s in slates):
        raise err409("ERR_SLATES_UNLOCKED",
                     "Every slate must be LOCKED to issue invitations")
    invited_entry_ids = []
    declined_submission_ids = []
    waitlisted_submission_ids = []
    deadline = D.now() + timedelta(days=edition["rsvp_window_days"])
    for slate in slates:
        entries = sorted(
            (e for e in DB.entries.values()
             if e["slate_id"] == slate["id"] and e["status"] == "NOMINATED"),
            key=lambda e: (e["rank_position"], e["_seq"]))
        for entry in entries:
            sub = DB.submissions.get(entry["submission_id"])
            if entry["lane"] == "MAIN":
                entry["status"] = "INVITED"
                entry["rsvp_deadline_at"] = deadline
                D.touch(entry)
                if sub is not None and sub["status"] == "ADVANCED":
                    sub["status"] = "INVITED"
                    D.touch(sub)
                invited_entry_ids.append(entry["id"])
            elif entry["lane"] == "WAITLIST":
                if sub is not None and sub["status"] == "ADVANCED":
                    sub["status"] = "WAITLISTED"
                    D.touch(sub)
                    waitlisted_submission_ids.append(sub["id"])
    # Films still IN_SCREENING sit on no locked slate: declined in this sweep.
    for sub in sorted(DB.submissions.values(), key=created_key):
        if sub["edition_id"] == eid and sub["status"] == "IN_SCREENING":
            sub["status"] = "DECLINED"
            D.touch(sub)
            declined_submission_ids.append(sub["id"])
    return ok({
        "invited_entry_ids": invited_entry_ids,
        "declined_submission_ids": declined_submission_ids,
        "waitlisted_submission_ids": waitlisted_submission_ids,
    })
