"""Member / MemberEnrollmentSegment / Provider routes."""
from flask import Blueprint, request

import errors
from db import db, new_id, parse_dt
from middleware import require_roles, get_json_body, require_fields, require_enum, require_str
from response import success_object, success_list, parse_pagination
from serializers import member_view, segment_view, provider_view
from services.core import find_member, find_provider

bp = Blueprint("members", __name__)

ADMIN = ["QualityAdmin"]
ALL = ["QualityAdmin", "QualityAnalyst", "Abstractor", "OverReader",
       "ProviderRelations", "Auditor", "QualityDirector"]
GAP_BURDEN_ROLES = ["QualityAdmin", "QualityAnalyst", "ProviderRelations", "QualityDirector"]


# ---------------------------------------------------------------- members
@bp.post("/hedis/members")
def create_member():
    require_roles(ADMIN)
    body = get_json_body()
    require_fields(body, ["member_ref", "birth_date", "gender"])
    member_ref = require_str(body, "member_ref")
    birth = parse_dt(body.get("birth_date"))
    if birth is None:
        raise errors.invalid_request("birth_date must be an ISO8601 datetime")
    gender = require_enum(body, "gender", ["F", "M"])
    attributed = body.get("attributed_provider_ref")
    if attributed is not None and not isinstance(attributed, str):
        raise errors.invalid_request("attributed_provider_ref must be a string")

    # existence (priority 4.1): attributed provider must resolve
    if attributed is not None:
        found = any(p["provider_ref"] == attributed for p in db.providers.values())
        if not found:
            raise errors.provider_not_found()

    for m in db.members.values():
        if m["member_ref"] == member_ref:
            raise errors.ApiError(errors.ERR_DUPLICATE_MEMBER_REF, 409,
                                  "member_ref already registered")
    rec = {
        "id": new_id(),
        "member_ref": member_ref,
        "birth_date": birth,
        "gender": gender,
        "attributed_provider_ref": attributed,
        "created_at": db.clock,
        "updated_at": db.clock,
        "version": 1,
    }
    db.members[rec["id"]] = rec
    return success_object(member_view(rec), 201)


@bp.get("/hedis/members/<memberId>")
def get_member(memberId):
    require_roles(ALL)
    m = find_member(memberId)
    return success_object(member_view(m))


@bp.get("/hedis/members/<id>/enrollment-segments")
def list_member_segments(id):
    require_roles(ALL)
    find_member(id)
    items = [s for s in db.enrollment_segments.values() if s["member_id"] == id]
    items.sort(key=lambda s: s["created_at"])
    limit, offset = parse_pagination(request.args)
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([segment_view(s) for s in page], limit, offset, total)


# ---------------------------------------------------------------- enrollment segments
@bp.post("/hedis/enrollment-segments")
def create_segment():
    require_roles(ADMIN)
    body = get_json_body()
    require_fields(body, ["member_id", "span_start", "span_end"])
    span_start = parse_dt(body.get("span_start"))
    span_end = parse_dt(body.get("span_end"))
    if span_start is None or span_end is None:
        raise errors.invalid_request("span_start and span_end must be ISO8601 datetimes")
    if span_start > span_end:
        raise errors.invalid_request("span_start must be on or before span_end")
    member_id = body.get("member_id")
    member = find_member(member_id if isinstance(member_id, str) else "")

    # closed-interval overlap (priority 10.1): touching endpoints overlap
    for s in db.enrollment_segments.values():
        if s["member_id"] != member["id"]:
            continue
        if span_start <= s["span_end"] and span_end >= s["span_start"]:
            raise errors.ApiError(errors.ERR_ENROLLMENT_OVERLAP, 409,
                                  "Enrollment segment overlaps an existing segment")
    rec = {
        "id": new_id(),
        "member_id": member["id"],
        "span_start": span_start,
        "span_end": span_end,
        "created_at": db.clock,
    }
    db.enrollment_segments[rec["id"]] = rec
    return success_object(segment_view(rec), 201)


# ---------------------------------------------------------------- providers
@bp.post("/hedis/providers")
def create_provider():
    require_roles(ADMIN)
    body = get_json_body()
    require_fields(body, ["provider_ref", "name"])
    provider_ref = require_str(body, "provider_ref")
    name = require_str(body, "name")
    specialty = body.get("specialty")
    if specialty is not None and not isinstance(specialty, str):
        raise errors.invalid_request("specialty must be a string")
    for p in db.providers.values():
        if p["provider_ref"] == provider_ref:
            raise errors.ApiError(errors.ERR_DUPLICATE_PROVIDER_REF, 409,
                                  "provider_ref already registered")
    rec = {
        "id": new_id(),
        "provider_ref": provider_ref,
        "name": name,
        "specialty": specialty,
        "open_gap_count": 0,
        "created_at": db.clock,
        "updated_at": db.clock,
        "version": 1,
    }
    db.providers[rec["id"]] = rec
    return success_object(provider_view(rec), 201)


@bp.get("/hedis/providers/<providerId>")
def get_provider(providerId):
    require_roles(ALL)
    p = find_provider(providerId)
    return success_object(provider_view(p))


@bp.get("/hedis/providers/<providerId>/gap-burden")
def provider_gap_burden(providerId):
    require_roles(GAP_BURDEN_ROLES)
    p = find_provider(providerId)
    season_id = request.args.get("season_id")
    if season_id is None or season_id not in db.seasons:
        raise errors.not_found("season_id does not resolve")

    from services.core import round2
    burden = 0.0
    open_total = 0
    per_measure_lines = 0
    for r in db.runs.values():
        if r["season_id"] != season_id:
            continue
        spec = db.specs.get(r["spec_id"])
        if spec is None or spec["status"] == "RETIRED":
            continue
        open_gaps = sum(1 for g in db.gap_items.values()
                        if g["run_id"] == r["id"]
                        and g["provider_ref"] == p["provider_ref"]
                        and g["status"] in ("OPEN", "OUTREACH_DONE"))
        line = round2(open_gaps * spec["reporting_weight"])
        burden += line
        open_total += open_gaps
        if open_gaps > 0:
            per_measure_lines += 1
    # burden is a sum of 2dp values; normalize float noise
    burden = round2(burden)
    return success_object({
        "burden_score": burden,
        "open_gap_count": open_total,
        "per_measure_lines": per_measure_lines,
    })
