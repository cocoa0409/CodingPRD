"""Flat single-resource GET aliases and flat filtered-list GET endpoints
(FK reverse-reachability, PRD §2.3 + §4 table tail)."""

from flask import Blueprint, request

from db import store
from errors import ApiError, ERR_NOT_FOUND, ERR_INVALID_REQUEST
from middleware import (
    require_roles, paginate, sorted_items, serialize, ANY_ROLE,
)
from response import ok_object, ok_list

bp = Blueprint("flat", __name__)


def _q(name):
    v = request.args.get(name)
    return v if v not in (None, "") else None


def _bool_q(name):
    raw = request.args.get(name)
    if raw is None or raw == "":
        return None
    v = raw.strip().lower()
    if v in ("true", "1", "yes"):
        return True
    if v in ("false", "0", "no"):
        return False
    raise ApiError(ERR_INVALID_REQUEST, 400,
                   "Query parameter '%s' must be a boolean" % name)


def _get_by_id(collection, rid, what):
    r = collection.get(rid)
    if r is None:
        raise ApiError(ERR_NOT_FOUND, 404, "%s does not exist" % what)
    return r


def _list(collection, filters):
    items = list(collection.values())
    for fname, value in filters:
        if value is None:
            continue
        if fname == "is_critical":
            items = [r for r in items if bool(r.get("is_critical")) == value]
        else:
            items = [r for r in items if r.get(fname) == value]
    items = sorted_items(items)
    page, pg = paginate(items)
    return ok_list([serialize(r) for r in page], pg)


# --- Flat single-resource aliases ---

@bp.route("/construction-projects/schedule-versions/<vid>", methods=["GET"],
          strict_slashes=False)
def flat_get_version(vid):
    require_roles(*ANY_ROLE)
    return ok_object(serialize(_get_by_id(
        store.schedule_versions, vid, "ScheduleVersion '%s'" % vid)))


@bp.route("/construction-projects/activities/<aid>", methods=["GET"],
          strict_slashes=False)
def flat_get_activity(aid):
    require_roles(*ANY_ROLE)
    return ok_object(serialize(_get_by_id(
        store.activities, aid, "Activity '%s'" % aid)))


@bp.route("/construction-projects/relationships/<rid>", methods=["GET"],
          strict_slashes=False)
def flat_get_relationship(rid):
    require_roles(*ANY_ROLE)
    return ok_object(serialize(_get_by_id(
        store.relationships, rid, "ActivityRelationship '%s'" % rid)))


@bp.route("/construction-projects/progress-updates/<puid>", methods=["GET"],
          strict_slashes=False)
def flat_get_progress_update(puid):
    require_roles(*ANY_ROLE)
    return ok_object(serialize(_get_by_id(
        store.progress_updates, puid, "ProgressUpdate '%s'" % puid)))


@bp.route("/construction-projects/progress-entries/<peid>", methods=["GET"],
          strict_slashes=False)
def flat_get_progress_entry(peid):
    require_roles(*ANY_ROLE)
    return ok_object(serialize(_get_by_id(
        store.progress_entries, peid, "ProgressEntry '%s'" % peid)))


@bp.route("/construction-projects/delay-events/<did>", methods=["GET"],
          strict_slashes=False)
def flat_get_delay_event(did):
    require_roles(*ANY_ROLE)
    return ok_object(serialize(_get_by_id(
        store.delay_events, did, "DelayEvent '%s'" % did)))


@bp.route("/construction-projects/eot-requests/<eid>", methods=["GET"],
          strict_slashes=False)
def flat_get_eot(eid):
    require_roles(*ANY_ROLE)
    return ok_object(serialize(_get_by_id(
        store.eot_requests, eid, "TimeExtensionRequest '%s'" % eid)))


@bp.route("/construction-projects/acceleration-directives/<aid>",
          methods=["GET"], strict_slashes=False)
def flat_get_directive(aid):
    require_roles(*ANY_ROLE)
    return ok_object(serialize(_get_by_id(
        store.acceleration_directives, aid,
        "AccelerationDirective '%s'" % aid)))


@bp.route("/construction-projects/ld-assessments/<lid>", methods=["GET"],
          strict_slashes=False)
def flat_get_lda(lid):
    require_roles(*ANY_ROLE)
    return ok_object(serialize(_get_by_id(
        store.ld_assessments, lid,
        "LiquidatedDamagesAssessment '%s'" % lid)))


# --- Flat filtered-list endpoints ---

@bp.route("/construction-projects/schedule-versions", methods=["GET"],
          strict_slashes=False)
def flat_list_versions():
    require_roles(*ANY_ROLE)
    return _list(store.schedule_versions, [
        ("project_id", _q("project_id")),
        ("supersedes_version_id", _q("supersedes_version_id")),
        ("kind", _q("kind")),
        ("status", _q("status")),
    ])


@bp.route("/construction-projects/activities", methods=["GET"],
          strict_slashes=False)
def flat_list_activities():
    require_roles(*ANY_ROLE)
    return _list(store.activities, [
        ("schedule_version_id", _q("schedule_version_id")),
        ("is_critical", _bool_q("is_critical")),
    ])


@bp.route("/construction-projects/relationships", methods=["GET"],
          strict_slashes=False)
def flat_list_relationships():
    require_roles(*ANY_ROLE)
    return _list(store.relationships, [
        ("schedule_version_id", _q("schedule_version_id")),
        ("predecessor_activity_id", _q("predecessor_activity_id")),
        ("successor_activity_id", _q("successor_activity_id")),
    ])


@bp.route("/construction-projects/progress-updates", methods=["GET"],
          strict_slashes=False)
def flat_list_progress_updates():
    require_roles(*ANY_ROLE)
    return _list(store.progress_updates, [
        ("schedule_version_id", _q("schedule_version_id")),
        ("status", _q("status")),
    ])


@bp.route("/construction-projects/progress-entries", methods=["GET"],
          strict_slashes=False)
def flat_list_progress_entries():
    require_roles(*ANY_ROLE)
    return _list(store.progress_entries, [
        ("progress_update_id", _q("progress_update_id")),
        ("activity_id", _q("activity_id")),
    ])


@bp.route("/construction-projects/delay-events", methods=["GET"],
          strict_slashes=False)
def flat_list_delay_events():
    require_roles(*ANY_ROLE)
    return _list(store.delay_events, [
        ("project_id", _q("project_id")),
        ("fragnet_inserted_into_version_id",
         _q("fragnet_inserted_into_version_id")),
        ("status", _q("status")),
        ("causation", _q("causation")),
    ])


@bp.route("/construction-projects/eot-requests", methods=["GET"],
          strict_slashes=False)
def flat_list_eots():
    require_roles(*ANY_ROLE)
    return _list(store.eot_requests, [
        ("project_id", _q("project_id")),
        ("delay_event_id", _q("delay_event_id")),
        ("status", _q("status")),
    ])


@bp.route("/construction-projects/acceleration-directives", methods=["GET"],
          strict_slashes=False)
def flat_list_directives():
    require_roles(*ANY_ROLE)
    return _list(store.acceleration_directives, [
        ("project_id", _q("project_id")),
        ("status", _q("status")),
    ])


@bp.route("/construction-projects/ld-assessments", methods=["GET"],
          strict_slashes=False)
def flat_list_ldas():
    require_roles(*ANY_ROLE)
    return _list(store.ld_assessments, [
        ("project_id", _q("project_id")),
        ("status", _q("status")),
    ])
