"""Existence lookups, entity mutation helper, and canonical list ordering."""
import db
from errors import ApiError, ERR_NOT_FOUND
from util import now_iso


def project_or_404(pid):
    p = db.projects.get(pid) if isinstance(pid, str) else None
    if p is None:
        raise ApiError(ERR_NOT_FOUND, 404, "project not found")
    return p


def survey_or_404(sid):
    s = db.site_surveys.get(sid) if isinstance(sid, str) else None
    if s is None:
        raise ApiError(ERR_NOT_FOUND, 404, "site survey not found")
    return s


def safety_plan_or_404(sid):
    sp = db.safety_plans.get(sid) if isinstance(sid, str) else None
    if sp is None:
        raise ApiError(ERR_NOT_FOUND, 404, "safety plan not found")
    return sp


def lockout_or_404(wid):
    w = db.lockout_windows.get(wid) if isinstance(wid, str) else None
    if w is None:
        raise ApiError(ERR_NOT_FOUND, 404, "lockout window not found")
    return w


def rigging_or_404(rid):
    r = db.rigging_plans.get(rid) if isinstance(rid, str) else None
    if r is None:
        raise ApiError(ERR_NOT_FOUND, 404, "rigging plan not found")
    return r


def lift_or_404(lid):
    l = db.lift_permits.get(lid) if isinstance(lid, str) else None
    if l is None:
        raise ApiError(ERR_NOT_FOUND, 404, "lift permit not found")
    return l


def alignment_or_404(aid):
    a = db.alignment_records.get(aid) if isinstance(aid, str) else None
    if a is None:
        raise ApiError(ERR_NOT_FOUND, 404, "alignment record not found")
    return a


def checklist_or_404(cid):
    c = db.checklists.get(cid) if isinstance(cid, str) else None
    if c is None:
        raise ApiError(ERR_NOT_FOUND, 404, "commissioning checklist not found")
    return c


def labor_or_404(eid):
    e = db.labor_entries.get(eid) if isinstance(eid, str) else None
    if e is None:
        raise ApiError(ERR_NOT_FOUND, 404, "labor entry not found")
    return e


def touch(entity):
    """PRD 2.4: every modification refreshes updated_at and increments version."""
    entity["version"] += 1
    entity["updated_at"] = now_iso()


def sorted_items(items):
    """PRD 2.3: lists sort by created_at ascending (insertion order breaks ties)."""
    return sorted(items, key=lambda e: (e["created_at"], e["_seq"]))
