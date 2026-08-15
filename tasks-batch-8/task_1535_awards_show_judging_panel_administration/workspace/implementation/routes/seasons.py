"""Season endpoints + season-scoped collections (categories, ceremonies,
conflict-declarations, fulfillment-orders, audit-logs)."""
from datetime import timedelta

from flask import Blueprint, request

import audit
import clock
import services
import store
from auth import authenticate, authorize, ALL_ROLES
from errors import (
    raise_err, ERR_INVALID_REQUEST, ERR_INVALID_STATE, ERR_OUTSIDE_WINDOW,
    ERR_DUPLICATE, ERR_HASH_CHAIN_BROKEN, ERR_CONSTRAINT_VIOLATION,
)
from util import (
    body_json, req_str, opt_str, opt_int, opt_enum, opt_datetime, req_datetime,
    new_record, bump, success_object, list_response, get_or_404,
)

bp = Blueprint("seasons", __name__)

SEASON_STATUSES = ["DRAFT", "OPEN", "SUBMISSION_CLOSED", "JUDGING",
                   "FINALISTS_LOCKED", "EMBARGOED", "CEREMONY_LIVE",
                   "PUBLISHED", "ARCHIVED", "CANCELLED"]


def _validate_rubric_shape(rubric):
    if not isinstance(rubric, list) or not rubric:
        raise_err(ERR_INVALID_REQUEST,
                  "scoring_rubric must be a non-empty array of criterion objects")
    for c in rubric:
        if not isinstance(c, dict):
            raise_err(ERR_INVALID_REQUEST, "scoring_rubric entries must be objects")
        if not isinstance(c.get("criterion_code"), str):
            raise_err(ERR_INVALID_REQUEST, "criterion_code must be a string")
        if not isinstance(c.get("weight_bp"), int) or isinstance(c.get("weight_bp"), bool):
            raise_err(ERR_INVALID_REQUEST, "weight_bp must be an integer")
        if not isinstance(c.get("max_score"), int) or isinstance(c.get("max_score"), bool):
            raise_err(ERR_INVALID_REQUEST, "max_score must be an integer")


# ---------------------------------------------------------------------------
# seasons
# ---------------------------------------------------------------------------
@bp.post("/awards/seasons")
def create_season():
    _, role = authenticate()
    authorize(role, ["ProgramAdmin"])
    body = body_json()
    code = req_str(body, "code")
    if len(code) > 40:
        raise_err(ERR_INVALID_REQUEST, "code must be 1..40 chars")
    title = req_str(body, "title")
    if len(title) > 120:
        raise_err(ERR_INVALID_REQUEST, "title must be 1..120 chars")
    submission_opens_at = req_datetime(body, "submission_opens_at")
    early_fee_ends_at = req_datetime(body, "early_fee_ends_at")
    submission_closes_at = req_datetime(body, "submission_closes_at")
    eligibility_window_start = req_datetime(body, "eligibility_window_start")
    eligibility_window_end = req_datetime(body, "eligibility_window_end")
    ceremony_scheduled_at = opt_datetime(body, "ceremony_scheduled_at")
    max_appeals = opt_int(body, "max_appeals_per_entry", 2)
    refund_policy = opt_enum(body, "refund_policy", ["FLAT_FEE", "EARLY_BIRD_FREE"], "FLAT_FEE")
    ack_window_hours = opt_int(body, "ack_window_hours", 72)
    go_live_lead_minutes = opt_int(body, "go_live_lead_minutes", 30)
    # cross-field calendar consistency
    if early_fee_ends_at < submission_opens_at or early_fee_ends_at > submission_closes_at:
        raise_err(ERR_INVALID_REQUEST,
                  "early_fee_ends_at must be >= submission_opens_at and <= submission_closes_at")
    if eligibility_window_end <= eligibility_window_start:
        raise_err(ERR_INVALID_REQUEST,
                  "eligibility_window_end must be > eligibility_window_start")
    for s in store.seasons.values():
        if s["code"] == code:
            raise_err(ERR_DUPLICATE, "season code already exists: %s" % code)
    rec = new_record()
    rec.update({
        "code": code,
        "title": title,
        "status": "DRAFT",
        "submission_opens_at": submission_opens_at,
        "early_fee_ends_at": early_fee_ends_at,
        "submission_closes_at": submission_closes_at,
        "eligibility_window_start": eligibility_window_start,
        "eligibility_window_end": eligibility_window_end,
        "ceremony_scheduled_at": ceremony_scheduled_at,
        "embargo_lifts_at": None,
        "ack_window_hours": ack_window_hours,
        "go_live_lead_minutes": go_live_lead_minutes,
        "max_appeals_per_entry": max_appeals,
        "refund_policy": refund_policy,
        "active_entries_count": 0,
        "integrity_flag": "CLEAN",
        "_live_ceremony_id": None,
    })
    store.seasons[rec["id"]] = rec
    return success_object(services.serialize_season(rec), 201)


@bp.get("/awards/seasons")
def list_seasons():
    _, role = authenticate()
    authorize(role, ALL_ROLES)
    records = list(store.seasons.values())
    status = request.args.get("status")
    if status:
        records = [s for s in records if s["status"] == status]
    return list_response(records, services.serialize_season)


@bp.get("/awards/seasons/<sid>")
def get_season(sid):
    _, role = authenticate()
    authorize(role, ALL_ROLES)
    s = get_or_404(store.seasons, sid, "Season")
    return success_object(services.serialize_season(s), 200)


def _season_for_action(sid):
    return get_or_404(store.seasons, sid, "Season")


@bp.post("/awards/seasons/<sid>/open")
def open_season(sid):
    uid, role = authenticate()
    authorize(role, ["ProgramAdmin"])
    s = _season_for_action(sid)
    services.guard_transition("season", s, {"DRAFT"})
    now = clock.now()
    if not (s["submission_opens_at"] <= now < s["submission_closes_at"]):
        raise_err(ERR_OUTSIDE_WINDOW,
                  "clock must satisfy submission_opens_at <= now < submission_closes_at")
    has_published = any(c["season_id"] == s["id"] and c["status"] == "PUBLISHED"
                        for c in store.categories.values())
    if not has_published:
        raise_err(ERR_INVALID_STATE,
                  "at least one PUBLISHED category is required to open the season")
    s["status"] = "OPEN"
    bump(s)
    audit.append(s["id"], role, uid, "SEASON_OPEN", "AwardSeason", s["id"],
                 {"before": {"status": "DRAFT"}, "after": {"status": "OPEN"}})
    return success_object(services.serialize_season(s), 200)


@bp.post("/awards/seasons/<sid>/close-submissions")
def close_submissions(sid):
    uid, role = authenticate()
    authorize(role, ["ProgramAdmin"])
    s = _season_for_action(sid)
    services.guard_transition("season", s, {"OPEN"})
    if clock.now() < s["submission_closes_at"]:
        raise_err(ERR_OUTSIDE_WINDOW, "clock has not reached submission_closes_at")
    services.close_submissions(s, role, uid)
    return success_object(services.serialize_season(s), 200)


@bp.post("/awards/seasons/<sid>/begin-judging")
def begin_judging(sid):
    uid, role = authenticate()
    authorize(role, ["ProgramAdmin"])
    s = _season_for_action(sid)
    services.guard_transition("season", s, {"SUBMISSION_CLOSED"})
    for e in services.entries_of_season(s["id"]):
        if e["status"] in ("SUBMITTED", "UNDER_REVIEW"):
            raise_err(ERR_INVALID_STATE,
                      "entry %s still %s; resolve to ELIGIBLE or INELIGIBLE first"
                      % (e["id"], e["status"]))
    for cat in [c for c in store.categories.values()
                if c["season_id"] == s["id"] and c["status"] == "PUBLISHED"]:
        rounds = services.non_voided_rounds(cat["id"])
        if not rounds:
            raise_err(ERR_INVALID_STATE,
                      "PUBLISHED category %s has no scoring round" % cat["id"])
        first = rounds[0]
        if first["status"] != "PANEL_LOCKED":
            raise_err(ERR_INVALID_STATE,
                      "category %s: lowest-indexed round must be PANEL_LOCKED" % cat["id"])
    s["status"] = "JUDGING"
    bump(s)
    for e in services.entries_of_season(s["id"]):
        if e["status"] == "ELIGIBLE":
            e["status"] = "IN_JUDGING"
            bump(e)
    audit.append(s["id"], role, uid, "SEASON_BEGIN_JUDGING", "AwardSeason", s["id"],
                 {"before": {"status": "SUBMISSION_CLOSED"},
                  "after": {"status": "JUDGING"}})
    return success_object(services.serialize_season(s), 200)


@bp.post("/awards/seasons/<sid>/lock-finalists")
def lock_finalists(sid):
    uid, role = authenticate()
    authorize(role, ["ProgramAdmin"])
    s = _season_for_action(sid)
    services.guard_transition("season", s, {"JUDGING"})
    pub_cats = [c for c in store.categories.values()
                if c["season_id"] == s["id"] and c["status"] == "PUBLISHED"]
    for cat in pub_cats:
        final_rounds = [r for r in services.non_voided_rounds(cat["id"])
                        if r["round_index"] == 3]
        if not final_rounds or final_rounds[0]["status"] != "NORMALIZED":
            raise_err(ERR_INVALID_STATE,
                      "category %s: FINAL round must be NORMALIZED" % cat["id"])
    s["status"] = "FINALISTS_LOCKED"
    bump(s)
    for cat in pub_cats:
        final_round = [r for r in services.non_voided_rounds(cat["id"])
                       if r["round_index"] == 3][0]
        candidates = [e for e in services.entries_of_category(cat["id"])
                      if e["status"] == "IN_JUDGING"
                      and e.get("final_composite_score") is not None]
        candidates.sort(key=lambda e: (-float(e["final_composite_score"]),
                                       -float(services.final_round_weighted_raw(final_round, e["id"])),
                                       e["created_at"], e["_seq"]))
        for idx, e in enumerate(candidates, start=1):
            if idx <= cat["finalist_slots"]:
                e["status"] = "FINALIST"
                bump(e)
                rec = new_record()
                rec.update({
                    "category_id": cat["id"],
                    "entry_id": e["id"],
                    "announced_rank": e.get("final_rank") or idx,
                    "notification_status": "PENDING",
                    "notified_at": None,
                    "embargo_visible": False,
                })
                store.finalists[rec["id"]] = rec
            else:
                e["status"] = "NON_FINALIST"
                bump(e)
        final_round["status"] = "PUBLISHED"
        bump(final_round)
    audit.append(s["id"], role, uid, "SEASON_LOCK_FINALISTS", "AwardSeason", s["id"],
                 {"before": {"status": "JUDGING"},
                  "after": {"status": "FINALISTS_LOCKED"}})
    return success_object(services.serialize_season(s), 200)


@bp.post("/awards/seasons/<sid>/embargo")
def embargo_season(sid):
    uid, role = authenticate()
    authorize(role, ["ProgramAdmin"])
    body = body_json()
    embargo_lifts_at = req_datetime(body, "embargo_lifts_at")
    s = _season_for_action(sid)
    services.guard_transition("season", s, {"FINALISTS_LOCKED"})
    for cat in [c for c in store.categories.values() if c["season_id"] == s["id"]]:
        for fr in services.finalists_of_category(cat["id"]):
            if fr["notification_status"] not in ("NOTIFIED", "ACKNOWLEDGED", "DECLINED"):
                raise_err(ERR_INVALID_STATE,
                          "all finalist records must leave PENDING before embargo")
    now = clock.now()
    if s.get("ceremony_scheduled_at") is None or s["ceremony_scheduled_at"] <= now:
        raise_err(ERR_OUTSIDE_WINDOW,
                  "ceremony_scheduled_at must be set and lie in the future")
    if embargo_lifts_at <= now:
        raise_err(ERR_OUTSIDE_WINDOW, "embargo_lifts_at must be after the current clock")
    s["status"] = "EMBARGOED"
    s["embargo_lifts_at"] = embargo_lifts_at
    bump(s)
    audit.append(s["id"], role, uid, "SEASON_EMBARGO", "AwardSeason", s["id"],
                 {"before": {"status": "FINALISTS_LOCKED"},
                  "after": {"status": "EMBARGOED",
                            "embargo_lifts_at": embargo_lifts_at.isoformat()}})
    return success_object(services.serialize_season(s), 200)


@bp.post("/awards/seasons/<sid>/go-live")
def go_live(sid):
    uid, role = authenticate()
    authorize(role, ["ProgramAdmin"])
    s = _season_for_action(sid)
    services.guard_transition("season", s, {"EMBARGOED"})
    rehearsals = [c for c in store.ceremonies.values()
                  if c["season_id"] == s["id"] and c["status"] == "REHEARSAL"]
    if not rehearsals:
        raise_err(ERR_INVALID_STATE, "no REHEARSAL ceremony exists for this season")
    rehearsals.sort(key=lambda c: (c["starts_at"], c["created_at"], c["_seq"]))
    ceremony = rehearsals[0]
    now = clock.now()
    lead = ceremony["starts_at"] - timedelta(minutes=s["go_live_lead_minutes"])
    if now < lead:
        raise_err(ERR_OUTSIDE_WINDOW,
                  "go-live permitted from ceremony start minus go_live_lead_minutes")
    s["status"] = "CEREMONY_LIVE"
    s["_live_ceremony_id"] = ceremony["id"]
    bump(s)
    ceremony["status"] = "LIVE"
    bump(ceremony)
    services.recompute_embargo_visibility(s)
    audit.append(s["id"], role, uid, "SEASON_GO_LIVE", "AwardSeason", s["id"],
                 {"before": {"status": "EMBARGOED"},
                  "after": {"status": "CEREMONY_LIVE"}})
    return success_object(services.serialize_season(s), 200)


@bp.post("/awards/seasons/<sid>/publish-results")
def publish_results(sid):
    uid, role = authenticate()
    authorize(role, ["ProgramAdmin"])
    s = _season_for_action(sid)
    services.guard_transition("season", s, {"CEREMONY_LIVE"})
    for cat in [c for c in store.categories.values()
                if c["season_id"] == s["id"] and c["status"] == "PUBLISHED"]:
        ok = any(a["category_id"] == cat["id"] and a["status"] == "ANNOUNCED"
                 for a in store.announcements.values())
        if not ok:
            raise_err(ERR_INVALID_STATE,
                      "category %s has no ANNOUNCED winner announcement" % cat["id"])
    ceremony_ok = False
    if s.get("_live_ceremony_id"):
        c = store.ceremonies.get(s["_live_ceremony_id"])
        ceremony_ok = c is not None and c["status"] == "CONCLUDED"
    if not ceremony_ok:
        ceremony_ok = any(c["season_id"] == s["id"] and c["status"] == "CONCLUDED"
                          for c in store.ceremonies.values())
    if not ceremony_ok:
        raise_err(ERR_INVALID_STATE, "the ceremony must be CONCLUDED")
    s["status"] = "PUBLISHED"
    bump(s)
    for cat in [c for c in store.categories.values() if c["season_id"] == s["id"]]:
        for fr in services.finalists_of_category(cat["id"]):
            if not fr["embargo_visible"]:
                fr["embargo_visible"] = True
                bump(fr)
    audit.append(s["id"], role, uid, "SEASON_PUBLISH", "AwardSeason", s["id"],
                 {"before": {"status": "CEREMONY_LIVE"},
                  "after": {"status": "PUBLISHED"}})
    return success_object(services.serialize_season(s), 200)


@bp.post("/awards/seasons/<sid>/archive")
def archive_season(sid):
    uid, role = authenticate()
    authorize(role, ["ProgramAdmin"])
    s = _season_for_action(sid)
    services.guard_transition("season", s, {"PUBLISHED"})
    entry_ids = {e["id"] for e in services.entries_of_season(s["id"])}
    for a in store.appeals.values():
        if a["entry_id"] in entry_ids and a["status"] in ("FILED", "UNDER_REVIEW"):
            raise_err(ERR_INVALID_STATE, "open appeals remain for this season")
    for fo in store.fulfillment_orders.values():
        if fo["season_id"] == s["id"] and fo["status"] not in ("DELIVERED", "CANCELLED"):
            raise_err(ERR_INVALID_STATE, "unresolved fulfillment orders remain")
    s["status"] = "ARCHIVED"
    bump(s)
    audit.append(s["id"], role, uid, "SEASON_ARCHIVE", "AwardSeason", s["id"],
                 {"before": {"status": "PUBLISHED"}, "after": {"status": "ARCHIVED"}})
    return success_object(services.serialize_season(s), 200)


@bp.post("/awards/seasons/<sid>/cancel")
def cancel_season(sid):
    uid, role = authenticate()
    authorize(role, ["ProgramAdmin"])
    s = _season_for_action(sid)
    services.guard_transition("season", s, {"DRAFT", "OPEN"})
    s["status"] = "CANCELLED"
    bump(s)
    for e in services.entries_of_season(s["id"]):
        if e["status"] not in ("WITHDRAWN", "DISQUALIFIED"):
            e["status"] = "WITHDRAWN"
            bump(e)
        for inv in services.invoices_of_entry(e["id"]):
            if inv["status"] == "ISSUED":
                inv["status"] = "VOIDED"
                bump(inv)
                e["payment_status"] = "UNPAID"
    services.recompute_active_entries_count(s)
    audit.append(s["id"], role, uid, "SEASON_CANCEL", "AwardSeason", s["id"],
                 {"before": {}, "after": {"status": "CANCELLED"}})
    return success_object(services.serialize_season(s), 200)


# ---------------------------------------------------------------------------
# categories under a season
# ---------------------------------------------------------------------------
@bp.post("/awards/seasons/<sid>/categories")
def create_category(sid):
    _, role = authenticate()
    authorize(role, ["ProgramAdmin"])
    s = get_or_404(store.seasons, sid, "Season")
    body = body_json()
    code = req_str(body, "code")
    name = req_str(body, "name")
    if s["status"] in ("ARCHIVED", "CANCELLED"):
        raise_err(ERR_INVALID_STATE, "season is closed")
    description = opt_str(body, "description")
    eligibility_rules_text = opt_str(body, "eligibility_rules_text")
    min_materials = opt_int(body, "min_materials", 1)
    max_entries = opt_int(body, "max_entries_per_entrant", 3)
    early_fee = _req_fee(body, "early_fee_cents")
    standard_fee = _req_fee(body, "standard_fee_cents")
    late_fee = _req_fee(body, "late_fee_cents")
    panel_size = opt_int(body, "panel_size", 5)
    finalist_slots = opt_int(body, "finalist_slots", 3)
    rubric = body.get("scoring_rubric")
    _validate_rubric_shape(rubric)
    for c in store.categories.values():
        if c["season_id"] == s["id"] and c["code"] == code:
            raise_err(ERR_DUPLICATE, "category code already exists in this season: %s" % code)
    rec = new_record()
    rec.update({
        "season_id": s["id"],
        "code": code,
        "name": name,
        "description": description,
        "eligibility_rules_text": eligibility_rules_text,
        "min_materials": min_materials,
        "max_entries_per_entrant": max_entries,
        "early_fee_cents": early_fee,
        "standard_fee_cents": standard_fee,
        "late_fee_cents": late_fee,
        "panel_size": panel_size,
        "finalist_slots": finalist_slots,
        "scoring_rubric": rubric,
        "status": "DRAFT",
    })
    store.categories[rec["id"]] = rec
    return success_object(services.serialize_category(rec), 201)


def _req_fee(body, key):
    from util import req_int
    v = req_int(body, key)
    if v < 0:
        raise_err(ERR_INVALID_REQUEST, "%s must be >= 0" % key)
    return v


@bp.get("/awards/seasons/<sid>/categories")
def list_categories(sid):
    _, role = authenticate()
    authorize(role, ALL_ROLES)
    s = get_or_404(store.seasons, sid, "Season")
    records = [c for c in store.categories.values() if c["season_id"] == s["id"]]
    status = request.args.get("status")
    if status:
        records = [c for c in records if c["status"] == status]
    return list_response(records, services.serialize_category)


# ---------------------------------------------------------------------------
# audit logs
# ---------------------------------------------------------------------------
@bp.get("/awards/seasons/<sid>/audit-logs")
def list_audit_logs(sid):
    _, role = authenticate()
    authorize(role, ["ProgramAdmin", "Auditor"])
    s = get_or_404(store.seasons, sid, "Season")
    if not audit.verify_chain(s["id"]):
        if s["integrity_flag"] != "COMPROMISED":
            s["integrity_flag"] = "COMPROMISED"
            bump(s)
        raise_err(ERR_HASH_CHAIN_BROKEN, "audit hash chain verification failed")
    rows = audit.season_rows(s["id"])
    target_type = request.args.get("target_type")
    target_id = request.args.get("target_id")
    if target_type:
        rows = [r for r in rows if r["target_type"] == target_type]
    if target_id:
        rows = [r for r in rows if r["target_id"] == target_id]
    return list_response(rows, services.serialize_audit)
