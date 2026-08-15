"""Appeal decision endpoints (auditor) + withdrawal (entrant)."""
from flask import Blueprint

import audit
import clock
import services
import store
from auth import authenticate, authorize, forbid
from errors import (
    raise_err, ERR_INVALID_REQUEST, ERR_SEGREGATION_OF_DUTIES,
)
from util import body_json, req_enum, bump, success_object, get_or_404

bp = Blueprint("appeals", __name__)

REMEDIES = ["RESCORE", "REINSTATE", "NONE"]


def _season_of_appeal(appeal):
    e = store.entries.get(appeal["entry_id"])
    return services.season_of_entry(e) if e else None


def _check_sod(appeal, uid):
    """The acting auditor's identity must differ from the filing entrant's
    owning user id (the entrant id IS that user id)."""
    if uid == appeal["filed_by_entrant_id"]:
        raise_err(ERR_SEGREGATION_OF_DUTIES,
                  "the appeal filer may not decide their own appeal")


def _set_integrity(season, flag):
    if season is not None and season["integrity_flag"] != flag:
        season["integrity_flag"] = flag
        bump(season)


@bp.post("/awards/appeals/<aid>/take-under-review")
def take_under_review(aid):
    uid, role = authenticate()
    authorize(role, ["Auditor"])
    ap = get_or_404(store.appeals, aid, "Appeal")
    services.guard_transition("appeal", ap, {"FILED"})
    _check_sod(ap, uid)
    ap["status"] = "UNDER_REVIEW"
    bump(ap)
    _set_integrity(_season_of_appeal(ap), "UNDER_REVIEW")
    return success_object(services.serialize_appeal(ap), 200)


@bp.post("/awards/appeals/<aid>/uphold")
def uphold_appeal(aid):
    uid, role = authenticate()
    authorize(role, ["Auditor"])
    ap = get_or_404(store.appeals, aid, "Appeal")
    body = body_json()
    remedy = req_enum(body, "remedy", REMEDIES)
    services.guard_transition("appeal", ap, {"UNDER_REVIEW"})
    _check_sod(ap, uid)
    ap["status"] = "UPHELD"
    ap["decided_at"] = clock.now()
    ap["decided_by"] = uid
    ap["remedy"] = remedy
    bump(ap)
    season = _season_of_appeal(ap)
    entry = store.entries.get(ap["entry_id"])
    if remedy == "RESCORE" and entry is not None:
        # void the round that produced the appealed score: the highest-index
        # non-VOIDED round of the category, already NORMALIZED/PUBLISHED, in
        # which the appealed entry was scored
        cat = store.categories.get(entry["category_id"])
        if cat is not None:
            rounds = [r for r in services.non_voided_rounds(cat["id"])
                      if r["status"] in ("NORMALIZED", "PUBLISHED")]
            rounds = [r for r in rounds
                      if any(s["entry_id"] == entry["id"]
                             for s in services.scores_of_round(r["id"]))]
            if rounds:
                services.void_round_for_rescore(rounds[-1], entry, ap["grounds"])
        _set_integrity(season, "UNDER_REVIEW")
    elif remedy == "REINSTATE" and entry is not None \
            and entry["status"] == "INELIGIBLE":
        entry["status"] = "UNDER_REVIEW"
        entry["payment_status"] = "PAID"
        bump(entry)
    if season is not None:
        audit.append(season["id"], role, uid, "APPEAL_UPHELD", "Appeal", ap["id"],
                     {"before": {"status": "UNDER_REVIEW"},
                      "after": {"status": "UPHELD", "remedy": remedy}})
    return success_object(services.serialize_appeal(ap), 200)


@bp.post("/awards/appeals/<aid>/deny")
def deny_appeal(aid):
    uid, role = authenticate()
    authorize(role, ["Auditor"])
    ap = get_or_404(store.appeals, aid, "Appeal")
    services.guard_transition("appeal", ap, {"UNDER_REVIEW"})
    _check_sod(ap, uid)
    ap["status"] = "DENIED"
    ap["decided_at"] = clock.now()
    ap["decided_by"] = uid
    bump(ap)
    season = _season_of_appeal(ap)
    if season is not None:
        entry_ids = {e["id"] for e in services.entries_of_season(season["id"])}
        open_left = any(o["entry_id"] in entry_ids
                        and o["status"] in ("FILED", "UNDER_REVIEW")
                        for o in store.appeals.values())
        if not open_left and season["integrity_flag"] == "UNDER_REVIEW":
            season["integrity_flag"] = "CLEAN"
            bump(season)
    return success_object(services.serialize_appeal(ap), 200)


@bp.post("/awards/appeals/<aid>/withdraw")
def withdraw_appeal(aid):
    uid, role = authenticate()
    authorize(role, ["Entrant"])
    ap = get_or_404(store.appeals, aid, "Appeal")
    if ap["filed_by_entrant_id"] != uid:
        forbid("only the filing entrant may withdraw this appeal")
    services.guard_transition("appeal", ap, {"FILED"})
    ap["status"] = "WITHDRAWN"
    bump(ap)
    return success_object(services.serialize_appeal(ap), 200)
