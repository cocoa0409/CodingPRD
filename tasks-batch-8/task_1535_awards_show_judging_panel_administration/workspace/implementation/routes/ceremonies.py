"""Ceremony endpoints + winner announcements."""
from flask import Blueprint, request

import audit
import clock
import services
import store
from auth import authenticate, authorize, ALL_ROLES
from errors import (
    raise_err, ERR_INVALID_REQUEST, ERR_INVALID_STATE, ERR_DUPLICATE,
    ERR_CONSTRAINT_VIOLATION, ERR_CEREMONY_OVERLAP, ERR_OUTSIDE_WINDOW,
    ERR_REFERENTIAL_INTEGRITY, ERR_EMBARGO_ACTIVE,
)
from util import (
    body_json, req_str, req_datetime, new_record, bump, success_object,
    list_response, get_or_404, ref_or_404,
)

bp = Blueprint("ceremonies", __name__)


def _validate_rundown(rundown):
    """Shape (400); duplicate segment_no (409); contiguity from 1 (422)."""
    if not isinstance(rundown, list) or not rundown:
        raise_err(ERR_INVALID_REQUEST,
                  "rundown must be a non-empty array of segments")
    seen = []
    for seg in rundown:
        if not isinstance(seg, dict):
            raise_err(ERR_INVALID_REQUEST, "rundown segments must be objects")
        if not isinstance(seg.get("segment_no"), int) \
                or isinstance(seg.get("segment_no"), bool):
            raise_err(ERR_INVALID_REQUEST, "segment_no must be an integer")
        if not isinstance(seg.get("category_id"), str):
            raise_err(ERR_INVALID_REQUEST, "segment category_id must be a string")
        if not isinstance(seg.get("duration_seconds"), int) \
                or isinstance(seg.get("duration_seconds"), bool):
            raise_err(ERR_INVALID_REQUEST, "duration_seconds must be an integer")
        seen.append(seg["segment_no"])
    if len(set(seen)) != len(seen):
        raise_err(ERR_DUPLICATE, "rundown segment_no values must be unique")
    if sorted(seen) != list(range(1, len(seen) + 1)):
        raise_err(ERR_CONSTRAINT_VIOLATION,
                  "rundown segment_no values must be contiguous from 1")


@bp.post("/awards/seasons/<sid>/ceremonies")
def create_ceremony(sid):
    _, role = authenticate()
    authorize(role, ["ProgramAdmin"])
    s = get_or_404(store.seasons, sid, "Season")
    body = body_json()
    venue_name = req_str(body, "venue_name")
    starts_at = req_datetime(body, "starts_at")
    ends_at = req_datetime(body, "ends_at")
    rundown = body.get("rundown")
    _validate_rundown(rundown)
    for seg in rundown:
        ref_or_404(store.categories, seg["category_id"], "Category")
    if s["status"] in ("ARCHIVED", "CANCELLED"):
        raise_err(ERR_INVALID_STATE, "season is closed")
    # half-open [starts_at, ends_at) overlap against non-terminal ceremonies
    for c in store.ceremonies.values():
        if c["season_id"] != s["id"] or c["status"] in ("CONCLUDED", "ABORTED"):
            continue
        if starts_at < c["ends_at"] and c["starts_at"] < ends_at:
            raise_err(ERR_CEREMONY_OVERLAP,
                      "ceremony overlaps an existing ceremony of this season")
    if ends_at <= starts_at:
        raise_err(ERR_INVALID_REQUEST, "ends_at must be > starts_at")
    rec = new_record()
    rec.update({
        "season_id": s["id"],
        "venue_name": venue_name,
        "starts_at": starts_at,
        "ends_at": ends_at,
        "status": "PLANNING",
        "rundown": rundown,
    })
    store.ceremonies[rec["id"]] = rec
    return success_object(services.serialize_ceremony(rec), 201)


@bp.get("/awards/seasons/<sid>/ceremonies")
def list_ceremonies(sid):
    _, role = authenticate()
    authorize(role, ALL_ROLES)
    s = get_or_404(store.seasons, sid, "Season")
    records = [c for c in store.ceremonies.values() if c["season_id"] == s["id"]]
    status = request.args.get("status")
    if status:
        records = [c for c in records if c["status"] == status]
    return list_response(records, services.serialize_ceremony)


@bp.get("/awards/ceremonies/<cid>")
def get_ceremony(cid):
    _, role = authenticate()
    authorize(role, ALL_ROLES)
    c = get_or_404(store.ceremonies, cid, "Ceremony")
    return success_object(services.serialize_ceremony(c), 200)


@bp.post("/awards/ceremonies/<cid>/rehearse")
def rehearse_ceremony(cid):
    _, role = authenticate()
    authorize(role, ["ProgramAdmin"])
    c = get_or_404(store.ceremonies, cid, "Ceremony")
    services.guard_transition("ceremony", c, {"PLANNING"})
    s = store.seasons.get(c["season_id"])
    if s is None or s["status"] != "EMBARGOED":
        raise_err(ERR_INVALID_STATE, "rehearsal requires season EMBARGOED")
    published = {cat["id"] for cat in store.categories.values()
                 if cat["season_id"] == c["season_id"] and cat["status"] == "PUBLISHED"}
    covered = [seg["category_id"] for seg in c["rundown"]]
    if set(covered) != published or len(covered) != len(published):
        raise_err(ERR_CONSTRAINT_VIOLATION,
                  "rundown must cover every PUBLISHED category exactly once")
    c["status"] = "REHEARSAL"
    bump(c)
    return success_object(services.serialize_ceremony(c), 200)


@bp.post("/awards/ceremonies/<cid>/conclude")
def conclude_ceremony(cid):
    _, role = authenticate()
    authorize(role, ["ProgramAdmin"])
    c = get_or_404(store.ceremonies, cid, "Ceremony")
    services.guard_transition("ceremony", c, {"LIVE"})
    for cat in store.categories.values():
        if cat["season_id"] == c["season_id"] and cat["status"] == "PUBLISHED":
            ok = any(a["category_id"] == cat["id"] and a["status"] == "ANNOUNCED"
                     for a in store.announcements.values())
            if not ok:
                raise_err(ERR_INVALID_STATE,
                          "every PUBLISHED category needs an ANNOUNCED announcement")
    c["status"] = "CONCLUDED"
    bump(c)
    return success_object(services.serialize_ceremony(c), 200)


@bp.post("/awards/ceremonies/<cid>/abort")
def abort_ceremony(cid):
    _, role = authenticate()
    authorize(role, ["ProgramAdmin"])
    c = get_or_404(store.ceremonies, cid, "Ceremony")
    services.guard_transition("ceremony", c, {"PLANNING", "REHEARSAL"})
    c["status"] = "ABORTED"
    bump(c)
    return success_object(services.serialize_ceremony(c), 200)


# ---------------------------------------------------------------------------
# winner announcements
# ---------------------------------------------------------------------------
@bp.post("/awards/categories/<cid>/announcements")
def stage_announcement(cid):
    _, role = authenticate()
    authorize(role, ["ProgramAdmin"])
    cat = get_or_404(store.categories, cid, "Category")
    body = body_json()
    ceremony_id = req_str(body, "ceremony_id")
    ceremony = ref_or_404(store.ceremonies, ceremony_id, "Ceremony")
    if ceremony["season_id"] != cat["season_id"]:
        raise_err(ERR_REFERENTIAL_INTEGRITY,
                  "ceremony and category belong to different seasons")
    rec = new_record()
    rec.update({
        "category_id": cat["id"],
        "ceremony_id": ceremony["id"],
        "winner_entry_id": None,
        "status": "STAGED",
        "announced_at": None,
        "retraction_reason": None,
    })
    store.announcements[rec["id"]] = rec
    return success_object(services.serialize_announcement(rec), 201)


def _embargo_gate_for_announcement(ann_or_cat_season):
    if ann_or_cat_season is not None \
            and ann_or_cat_season["status"] in ("FINALISTS_LOCKED", "EMBARGOED"):
        lift = ann_or_cat_season.get("embargo_lifts_at")
        if lift is None or clock.now() < lift:
            raise_err(ERR_EMBARGO_ACTIVE,
                      "announcement data is embargo-protected")


@bp.get("/awards/announcements/<aid>")
def get_announcement(aid):
    _, role = authenticate()
    authorize(role, ["ProgramAdmin", "Auditor", "Anonymous"])
    a = get_or_404(store.announcements, aid, "WinnerAnnouncement")
    if role == "Anonymous":
        cat = store.categories.get(a["category_id"])
        season = store.seasons.get(cat["season_id"]) if cat else None
        _embargo_gate_for_announcement(season)
    return success_object(services.serialize_announcement(a), 200)


@bp.get("/awards/categories/<cid>/announcements")
def list_category_announcements(cid):
    _, role = authenticate()
    authorize(role, ["ProgramAdmin", "Auditor", "Anonymous"])
    cat = get_or_404(store.categories, cid, "Category")
    if role == "Anonymous":
        season = store.seasons.get(cat["season_id"])
        _embargo_gate_for_announcement(season)
    records = [a for a in store.announcements.values() if a["category_id"] == cat["id"]]
    status = request.args.get("status")
    if status:
        records = [a for a in records if a["status"] == status]
    return list_response(records, services.serialize_announcement)


@bp.get("/awards/ceremonies/<cid>/announcements")
def list_ceremony_announcements(cid):
    _, role = authenticate()
    authorize(role, ["ProgramAdmin", "Auditor", "Anonymous"])
    c = get_or_404(store.ceremonies, cid, "Ceremony")
    if role == "Anonymous":
        season = store.seasons.get(c["season_id"])
        _embargo_gate_for_announcement(season)
    records = [a for a in store.announcements.values() if a["ceremony_id"] == c["id"]]
    return list_response(records, services.serialize_announcement)


def _rank1_entry(category_id):
    for e in services.entries_of_category(category_id):
        if e.get("final_rank") == 1 and e["status"] == "FINALIST":
            return e
    return None


@bp.post("/awards/announcements/<aid>/announce")
def announce(aid):
    uid, role = authenticate()
    authorize(role, ["ProgramAdmin"])
    a = get_or_404(store.announcements, aid, "WinnerAnnouncement")
    services.guard_transition("announcement", a, {"STAGED", "RESTAGED"})
    cat = store.categories.get(a["category_id"])
    season = store.seasons.get(cat["season_id"]) if cat else None
    ceremony = store.ceremonies.get(a["ceremony_id"])
    if season is None or season["status"] != "CEREMONY_LIVE":
        raise_err(ERR_INVALID_STATE, "announce requires season CEREMONY_LIVE")
    if ceremony is None or ceremony["status"] != "LIVE":
        raise_err(ERR_INVALID_STATE, "announce requires ceremony LIVE")
    if season.get("embargo_lifts_at") is None \
            or clock.now() < season["embargo_lifts_at"]:
        raise_err(ERR_OUTSIDE_WINDOW, "embargo has not lifted yet")
    winner = _rank1_entry(a["category_id"])
    if winner is None:
        raise_err(ERR_REFERENTIAL_INTEGRITY,
                  "no entry holds final_rank 1 in this category")
    a["winner_entry_id"] = winner["id"]
    a["status"] = "ANNOUNCED"
    a["announced_at"] = clock.now()
    bump(a)
    # fan out: winner -> WINNER (+TROPHY), other FINALISTs -> NON_WINNER (+CERTIFICATE)
    for e in services.entries_of_category(a["category_id"]):
        if e["status"] != "FINALIST":
            continue
        if e["id"] == winner["id"]:
            e["status"] = "WINNER"
            bump(e)
            _create_fulfillment(season, e, a, "TROPHY")
        else:
            e["status"] = "NON_WINNER"
            bump(e)
            _create_fulfillment(season, e, a, "CERTIFICATE")
    audit.append(season["id"], role, uid, "WINNER_ANNOUNCED",
                 "WinnerAnnouncement", a["id"],
                 {"before": {"status": "STAGED_OR_RESTAGED"},
                  "after": {"status": "ANNOUNCED",
                            "winner_entry_id": winner["id"]}})
    return success_object(services.serialize_announcement(a), 200)


def _create_fulfillment(season, entry, announcement, item_type):
    rec = new_record()
    rec.update({
        "season_id": season["id"],
        "entry_id": entry["id"],
        "announcement_id": announcement["id"],
        "item_type": item_type,
        "engraving_text": None,
        "quantity": 1,
        "status": "DRAFT",
        "vendor_reference": None,
    })
    store.fulfillment_orders[rec["id"]] = rec
    return rec


@bp.post("/awards/announcements/<aid>/retract")
def retract_announcement(aid):
    uid, role = authenticate()
    authorize(role, ["Auditor"])
    a = get_or_404(store.announcements, aid, "WinnerAnnouncement")
    body = body_json()
    reason = req_str(body, "retraction_reason")
    services.guard_transition("announcement", a, {"ANNOUNCED"})
    cat = store.categories.get(a["category_id"])
    season = store.seasons.get(cat["season_id"]) if cat else None
    winner = store.entries.get(a.get("winner_entry_id") or "")
    appeal = None
    if winner is not None:
        for ap in store.appeals.values():
            if (ap["entry_id"] == winner["id"] and ap["status"] == "UPHELD"
                    and ap.get("remedy") == "RESCORE"):
                appeal = ap
                break
    if appeal is None:
        raise_err(ERR_INVALID_STATE,
                  "retraction requires an UPHELD RESCORE appeal against the winner")
    a["status"] = "RETRACTED"
    a["retraction_reason"] = reason
    bump(a)
    if winner is not None:
        if appeal["grounds"] == "CONFLICT_UNDECLARED":
            services.disqualify_entry(winner, reason)
        elif winner["status"] == "WINNER":
            # other grounds: the entry stays FINALIST pending the rescore
            winner["status"] = "FINALIST"
            bump(winner)
        # the TROPHY order is cancelled while still DRAFT/QUEUED/IN_PRODUCTION
        for fo in store.fulfillment_orders.values():
            if (fo["announcement_id"] == a["id"] and fo["item_type"] == "TROPHY"
                    and fo["status"] in ("DRAFT", "QUEUED", "IN_PRODUCTION")):
                fo["status"] = "CANCELLED"
                bump(fo)
    if season is not None:
        if season["integrity_flag"] != "UNDER_REVIEW":
            season["integrity_flag"] = "UNDER_REVIEW"
        bump(season)
        audit.append(season["id"], role, uid, "WINNER_RETRACTED",
                     "WinnerAnnouncement", a["id"],
                     {"before": {"status": "ANNOUNCED"},
                      "after": {"status": "RETRACTED", "reason": reason}})
    return success_object(services.serialize_announcement(a), 200)


@bp.post("/awards/announcements/<aid>/restage")
def restage_announcement(aid):
    _, role = authenticate()
    authorize(role, ["ProgramAdmin"])
    a = get_or_404(store.announcements, aid, "WinnerAnnouncement")
    services.guard_transition("announcement", a, {"RETRACTED"})
    finals = [r for r in services.non_voided_rounds(a["category_id"])
              if r["round_index"] == 3]
    if not finals or finals[-1]["status"] != "NORMALIZED":
        raise_err(ERR_INVALID_STATE,
                  "the replacement FINAL round must be NORMALIZED before restage")
    winner = _rank1_entry(a["category_id"])
    a["winner_entry_id"] = winner["id"] if winner is not None else None
    a["status"] = "RESTAGED"
    bump(a)
    return success_object(services.serialize_announcement(a), 200)
