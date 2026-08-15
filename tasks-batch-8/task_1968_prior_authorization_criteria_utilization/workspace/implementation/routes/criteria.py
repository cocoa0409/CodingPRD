"""Criteria library: ClinicalCriteriaSet and GuidelineVersion endpoints."""

from datetime import timedelta

from flask import request as flask_request

from db import db, base_record, touch
from errors import (
    ApiError,
    ERR_INVALID_CRITERIA_SET_TRANSITION,
    ERR_INVALID_GUIDELINE_TRANSITION,
    ERR_GUIDELINE_HAS_INFLIGHT_REQUESTS,
    ERR_GUIDELINE_WINDOW_OVERLAP,
    ERR_NO_ACTIVE_GUIDELINE,
    ERR_STALE_VERSION,
    ERR_SUPERSEDES_CROSS_SET,
    invalid_request,
)
from middleware import (
    ALL_ROLES,
    ROLE_POLICY_EDITOR,
    authorize,
    get_or_404,
    json_body,
    opt_dt,
    req_bool,
    req_dt,
    req_enum,
    req_int,
    req_str,
    opt_str,
)
from response import list_response, ok, serialize
from . import make_blueprint

bp = make_blueprint("criteria")

LOB_DOMAINS = ("COMMERCIAL", "MEDICARE", "MEDICAID")
CRITERIA_SET_STATUSES = ("DRAFT", "ACTIVE", "RETIRED")
GUIDELINE_STATUSES = ("DRAFT", "PUBLISHED", "SUPERSEDED", "RETIRED")


# ------------------------------------------------------------- criteria sets

@bp.route("/criteria-sets", methods=["POST"])
def create_criteria_set():
    authorize(ROLE_POLICY_EDITOR)
    body = json_body()
    name = req_str(body, "name")
    lob = req_enum(body, "line_of_business", LOB_DOMAINS)
    service_category = req_str(body, "service_category")
    rec = base_record()
    rec.update(
        {
            "name": name,
            "line_of_business": lob,
            "service_category": service_category,
            "status": "DRAFT",
        }
    )
    db.criteria_sets[rec["id"]] = rec
    return ok(serialize(rec), status=201)


@bp.route("/criteria-sets/<sid>", methods=["GET"])
def get_criteria_set(sid):
    authorize(*ALL_ROLES)
    rec = get_or_404(db.criteria_sets, sid, "criteria set")
    return ok(serialize(rec))


@bp.route("/criteria-sets/<sid>/transition", methods=["POST"])
def transition_criteria_set(sid):
    authorize(ROLE_POLICY_EDITOR)
    rec = get_or_404(db.criteria_sets, sid, "criteria set")
    body = json_body()
    to_status = req_enum(body, "to_status", CRITERIA_SET_STATUSES)

    if to_status == "ACTIVE":
        if rec["status"] != "DRAFT":
            raise ApiError(
                ERR_INVALID_CRITERIA_SET_TRANSITION,
                409,
                "Criteria set must be DRAFT to activate",
            )
        has_published = any(
            gv["criteria_set_id"] == sid and gv["status"] == "PUBLISHED"
            for gv in db.guideline_versions.values()
        )
        if not has_published:
            raise ApiError(
                ERR_NO_ACTIVE_GUIDELINE,
                409,
                "Set activation requires at least one PUBLISHED guideline version",
            )
        rec["status"] = "ACTIVE"
    elif to_status == "RETIRED":
        if rec["status"] != "ACTIVE":
            raise ApiError(
                ERR_INVALID_CRITERIA_SET_TRANSITION,
                409,
                "Criteria set must be ACTIVE to retire",
            )
        rec["status"] = "RETIRED"
    else:
        # DRAFT is never a valid transition target
        raise ApiError(
            ERR_INVALID_CRITERIA_SET_TRANSITION,
            409,
            "Criteria set transition not allowed",
        )
    touch(rec)
    return ok(serialize(rec))


# ---------------------------------------------------------- guideline versions

@bp.route("/criteria-sets/<sid>/guideline-versions", methods=["POST"])
def create_guideline_version(sid):
    authorize(ROLE_POLICY_EDITOR)
    get_or_404(db.criteria_sets, sid, "criteria set")
    body = json_body()
    version_label = req_str(body, "version_label")
    content = req_str(body, "content")
    auto_approve_eligible = req_bool(body, "auto_approve_eligible")
    effective_from = req_dt(body, "effective_from")
    effective_until = opt_dt(body, "effective_until")
    supersedes_version_id = opt_str(body, "supersedes_version_id")
    if supersedes_version_id is not None and (
        supersedes_version_id not in db.guideline_versions
    ):
        raise invalid_request(
            f"supersedes_version_id {supersedes_version_id} does not exist"
        )
    rec = base_record()
    rec.update(
        {
            "criteria_set_id": sid,
            "version_label": version_label,
            "content": content,
            "auto_approve_eligible": auto_approve_eligible,
            "effective_from": effective_from,
            "effective_until": effective_until,
            "supersedes_version_id": supersedes_version_id,
            "status": "DRAFT",
        }
    )
    db.guideline_versions[rec["id"]] = rec
    return ok(serialize(rec), status=201)


@bp.route("/guideline-versions/<gid>", methods=["GET"])
def get_guideline_version(gid):
    authorize(*ALL_ROLES)
    rec = get_or_404(db.guideline_versions, gid, "guideline version")
    return ok(serialize(rec))


@bp.route("/guideline-versions", methods=["GET"])
def list_guideline_versions():
    authorize(*ALL_ROLES)
    criteria_set_id = _q("criteria_set_id")
    supersedes_version_id = _q("supersedes_version_id")
    status = _q("status")
    items = [
        gv
        for gv in db.guideline_versions.values()
        if (criteria_set_id is None or gv["criteria_set_id"] == criteria_set_id)
        and (
            supersedes_version_id is None
            or gv["supersedes_version_id"] == supersedes_version_id
        )
        and (status is None or gv["status"] == status)
    ]
    return list_response(items)


def _q(name):
    v = flask_request.args.get(name)
    return v if v not in (None, "") else None


def _closed_windows_intersect(a_from, a_until, b_from, b_until):
    """Closed-interval intersection; None until = +infinity."""
    a_end = a_until if a_until is not None else _INF
    b_end = b_until if b_until is not None else _INF
    return a_from <= b_end and b_from <= a_end


from datetime import datetime, timezone  # noqa: E402

_INF = datetime.max.replace(tzinfo=timezone.utc)


@bp.route("/guideline-versions/<gid>/transition", methods=["POST"])
def transition_guideline_version(gid):
    authorize(ROLE_POLICY_EDITOR)
    gv = get_or_404(db.guideline_versions, gid, "guideline version")
    body = json_body()

    # priority 4: body well-formedness
    to_status = req_enum(body, "to_status", GUIDELINE_STATUSES)
    expected = req_int(body, "expected_criteria_set_version")

    criteria_set = db.criteria_sets[gv["criteria_set_id"]]

    # priority 5: OCC runs BEFORE any business validation on this endpoint
    if expected != criteria_set["version"]:
        raise ApiError(
            ERR_STALE_VERSION,
            412,
            "expected_criteria_set_version does not match the criteria set's "
            "current version",
        )

    if to_status == "PUBLISHED":
        # priority 6: state guards
        if criteria_set["status"] not in ("DRAFT", "ACTIVE"):
            raise ApiError(
                ERR_INVALID_GUIDELINE_TRANSITION,
                409,
                "Cannot publish under a RETIRED criteria set",
            )
        if gv["status"] != "DRAFT":
            raise ApiError(
                ERR_INVALID_GUIDELINE_TRANSITION,
                409,
                "Only a DRAFT guideline version can be published",
            )
        sup = None
        if gv["supersedes_version_id"] is not None:
            sup = db.guideline_versions.get(gv["supersedes_version_id"])
            if sup is None:
                raise invalid_request("supersedes_version_id does not exist")
            if sup["status"] != "PUBLISHED":
                raise ApiError(
                    ERR_INVALID_GUIDELINE_TRANSITION,
                    409,
                    "supersedes_version_id must name a PUBLISHED version",
                )
            # priority 8: cross-reference consistency
            if sup["criteria_set_id"] != gv["criteria_set_id"]:
                raise ApiError(
                    ERR_SUPERSEDES_CROSS_SET,
                    422,
                    "supersedes_version_id belongs to a different criteria set",
                )
        # priority 10: closed-window overlap vs OTHER PUBLISHED versions in the
        # set, excluding the version being superseded
        for other in db.guideline_versions.values():
            if other["id"] == gv["id"]:
                continue
            if other["criteria_set_id"] != gv["criteria_set_id"]:
                continue
            if other["status"] != "PUBLISHED":
                continue
            if sup is not None and other["id"] == sup["id"]:
                continue
            if _closed_windows_intersect(
                gv["effective_from"],
                gv["effective_until"],
                other["effective_from"],
                other["effective_until"],
            ):
                raise ApiError(
                    ERR_GUIDELINE_WINDOW_OVERLAP,
                    409,
                    "Publish would create intersecting closed effective windows "
                    "among PUBLISHED versions of the set",
                )
        gv["status"] = "PUBLISHED"
        touch(gv)
        if sup is not None:
            sup["status"] = "SUPERSEDED"
            sup["effective_until"] = gv["effective_from"] - timedelta(seconds=1)
            touch(sup)
        touch(criteria_set)

    elif to_status == "RETIRED":
        if gv["status"] not in ("DRAFT", "PUBLISHED"):
            raise ApiError(
                ERR_INVALID_GUIDELINE_TRANSITION,
                409,
                "Only a DRAFT or PUBLISHED guideline version can be retired",
            )
        # priority 9: in-flight guard
        if gv["status"] == "PUBLISHED":
            inflight = any(
                r["guideline_version_id"] == gv["id"]
                and r["status"] in ("PENDED_REVIEW", "ESCALATED_MD")
                for r in db.requests.values()
            )
            if inflight:
                raise ApiError(
                    ERR_GUIDELINE_HAS_INFLIGHT_REQUESTS,
                    409,
                    "Retire blocked: a request pinned to this version is "
                    "PENDED_REVIEW or ESCALATED_MD",
                )
        gv["status"] = "RETIRED"
        touch(gv)
        touch(criteria_set)

    else:
        # DRAFT / SUPERSEDED are never direct transition targets
        raise ApiError(
            ERR_INVALID_GUIDELINE_TRANSITION,
            409,
            "Guideline transition not allowed",
        )

    return ok(serialize(gv))
