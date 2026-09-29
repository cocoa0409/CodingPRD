"""Specification versions and feature sets (PRD 3.1)."""

from flask import Blueprint

import cascade
import common as C
import enums as E
import middleware as M
import queries as Q
import shape as S
from db import new_row, now, ordered, set_fields, store
from errors import ApiError
from response import list_response, object_response
from serial import public, public_list

bp = Blueprint("specifications", __name__)


@bp.post("/specifications")
def create_specification():
    M.auth([M.PROGRAM_ADMIN])
    body = S.body_obj()
    # rung 6 -- shape and ranges
    version_label = S.req_str(body, "version_label", 1, 32)
    baseline = S.req_str(body, "security_baseline_level")
    effective_date = S.req_dt(body, "effective_date")
    sunset_date = S.opt_dt(body, "sunset_date")
    supersedes_id = S.opt_str(body, "supersedes_specification_id")
    min_credits = S.opt_int(body, "min_plugfest_credits", 0, 4, 0)
    # rung 7 -- enum membership
    S.check_enum(baseline, E.SECURITY_BASELINES, "security_baseline_level")
    # rung 9 -- date range
    if sunset_date is not None and not sunset_date > effective_date:
        raise ApiError("ERR_INVALID_DATE_RANGE", "sunset_date must be after effective_date")
    # rung 13 -- the superseded version must already be RATIFIED or DEPRECATED
    if supersedes_id is not None:
        target = store.specifications.get(supersedes_id)
        if target is None or target["status"] not in ("RATIFIED", "DEPRECATED"):
            raise ApiError("ERR_INVALID_SPECIFICATION_STATE",
                           "supersedes_specification_id must name a RATIFIED or DEPRECATED version")
    # rung 51 -- duplicate name
    for row in store.specifications.values():
        if row["version_label"] == version_label:
            raise ApiError("ERR_DUPLICATE_NAME", "version_label already exists")

    spec = new_row(
        version_label=version_label,
        status="DRAFT",
        security_baseline_level=baseline,
        effective_date=effective_date,
        sunset_date=sunset_date,
        supersedes_specification_id=supersedes_id,
        min_plugfest_credits=min_credits,
        ratified_at=None,
        deprecated_at=None,
        feature_set_count=0,
    )
    store.specifications[spec["id"]] = spec
    return object_response(public(spec), 201)


@bp.get("/specifications/<specification_id>")
def get_specification(specification_id):
    M.auth(M.ALL_ROLES)
    return object_response(public(C.must("specification", specification_id)), 200)


@bp.get("/specifications")
def list_specifications():
    M.auth(M.ALL_ROLES)
    limit, offset = S.paging()
    status = S.q_str("status")
    baseline = S.q_enum("security_baseline_level", E.SECURITY_BASELINES)
    supersedes = S.q_str("supersedes_specification_id")
    rows = Q.specs()
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    if baseline is not None:
        rows = [r for r in rows if r["security_baseline_level"] == baseline]
    if supersedes is not None:
        rows = [r for r in rows if r["supersedes_specification_id"] == supersedes]
    page, total = C.paginate(rows, limit, offset)
    return list_response(public_list(page), limit, offset, total)


@bp.post("/specifications/<specification_id>/ratify")
def ratify_specification(specification_id):
    M.auth([M.PROGRAM_ADMIN])
    spec = C.must("specification", specification_id)
    # rung 13
    if spec["status"] != "DRAFT":
        raise ApiError("ERR_INVALID_SPECIFICATION_STATE", "only a DRAFT version can be ratified")
    # rung 43 -- baseline coverage per represented device class
    feature_sets = Q.feature_sets_of_spec(spec["id"])
    if not feature_sets:
        raise ApiError("ERR_MANDATORY_COVERAGE_INCOMPLETE",
                       "a version needs at least one feature set")
    for device_type in sorted({fs["device_type"] for fs in feature_sets}):
        if not any(fs["obligation"] == "MANDATORY"
                   for fs in feature_sets if fs["device_type"] == device_type):
            raise ApiError("ERR_MANDATORY_COVERAGE_INCOMPLETE",
                           "device class %s has no MANDATORY feature set" % device_type)
    set_fields(spec, status="RATIFIED", ratified_at=now())
    return object_response(public(spec), 200)


@bp.post("/specifications/<specification_id>/deprecate")
def deprecate_specification(specification_id):
    M.auth([M.PROGRAM_ADMIN])
    spec = C.must("specification", specification_id)
    status = spec["status"]
    if status == "RATIFIED":
        set_fields(spec, status="DEPRECATED", deprecated_at=now())
        cascade.deprecation_cascade(spec)
    elif status == "DEPRECATED":
        live = ("DRAFT", "SUBMITTED", "IN_REVIEW", "RETURNED_FOR_INFO", "REVIEW_COMPLETE")
        for submission in Q.submissions_for_spec(spec["id"]):
            if submission["state"] in live:
                raise ApiError("ERR_INVALID_SPECIFICATION_STATE",
                               "a live submission blocks retirement")
        set_fields(spec, status="RETIRED")
    else:
        raise ApiError("ERR_INVALID_SPECIFICATION_STATE",
                       "a %s version cannot be demoted" % status)
    return object_response(public(spec), 200)
