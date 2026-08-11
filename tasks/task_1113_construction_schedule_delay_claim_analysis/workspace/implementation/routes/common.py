"""Shared hierarchical existence lookups (PRD §2.6: left-to-right 404)."""

from db import store
from errors import ApiError, ERR_NOT_FOUND


def _nf(what):
    raise ApiError(ERR_NOT_FOUND, 404, "%s does not exist" % what)


def get_project(pid):
    p = store.projects.get(pid)
    if p is None:
        _nf("Project '%s'" % pid)
    return p


def get_version(pid, vid):
    p = get_project(pid)
    v = store.schedule_versions.get(vid)
    if v is None or v["project_id"] != p["id"]:
        _nf("ScheduleVersion '%s'" % vid)
    return p, v


def get_activity(pid, vid, aid):
    p, v = get_version(pid, vid)
    a = store.activities.get(aid)
    if a is None or a["schedule_version_id"] != v["id"]:
        _nf("Activity '%s'" % aid)
    return p, v, a


def get_progress_update(pid, vid, puid):
    p, v = get_version(pid, vid)
    pu = store.progress_updates.get(puid)
    if pu is None or pu["schedule_version_id"] != v["id"]:
        _nf("ProgressUpdate '%s'" % puid)
    return p, v, pu


def get_delay_event(pid, did):
    p = get_project(pid)
    d = store.delay_events.get(did)
    if d is None or d["project_id"] != p["id"]:
        _nf("DelayEvent '%s'" % did)
    return p, d


def get_eot(pid, eid):
    p = get_project(pid)
    e = store.eot_requests.get(eid)
    if e is None or e["project_id"] != p["id"]:
        _nf("TimeExtensionRequest '%s'" % eid)
    return p, e


def get_directive(pid, aid):
    p = get_project(pid)
    d = store.acceleration_directives.get(aid)
    if d is None or d["project_id"] != p["id"]:
        _nf("AccelerationDirective '%s'" % aid)
    return p, d


def get_lda(pid, lid):
    p = get_project(pid)
    lda = store.ld_assessments.get(lid)
    if lda is None or lda["project_id"] != p["id"]:
        _nf("LiquidatedDamagesAssessment '%s'" % lid)
    return p, lda


def activities_of(version_id):
    return [a for a in store.activities.values()
            if a["schedule_version_id"] == version_id]


def relationships_of(version_id):
    return [r for r in store.relationships.values()
            if r["schedule_version_id"] == version_id]


def delay_events_of(project_id):
    return [d for d in store.delay_events.values() if d["project_id"] == project_id]


def ldas_of(project_id):
    return [l for l in store.ld_assessments.values() if l["project_id"] == project_id]


def latest_accepted_update(project_id):
    """Latest ACCEPTED UPDATE schedule version (by acceptance order), or None."""
    cands = [v for v in store.schedule_versions.values()
             if v["project_id"] == project_id and v["kind"] == "UPDATE"
             and v["status"] == "ACCEPTED"]
    if not cands:
        return None
    return max(cands, key=lambda v: (v.get("_accepted_seq") or 0, v.get("_seq", 0)))


def latest_accepted_baseline(project_id):
    cands = [v for v in store.schedule_versions.values()
             if v["project_id"] == project_id and v["kind"] == "BASELINE"
             and v["status"] == "ACCEPTED"]
    if not cands:
        return None
    return max(cands, key=lambda v: (v.get("_accepted_seq") or 0, v.get("_seq", 0)))
