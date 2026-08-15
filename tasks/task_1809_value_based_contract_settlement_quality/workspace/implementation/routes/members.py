"""Member and EligibilitySpan endpoints."""

from __future__ import annotations

from flask import Blueprint

import db
from errors import (
    raise_err,
    ERR_DUPLICATE_MEMBER_REF,
    ERR_INVALID_DATE_RANGE,
    ERR_INVALID_STATE_TRANSITION,
    ERR_NOT_FOUND,
    ERR_SPAN_OVERLAP,
)
from middleware import ALL_ROLES, require_roles
from response import success_list, success_object
from util import (
    apply_filters,
    get_json_body,
    paginate,
    parse_pagination,
    reject_unknown_fields,
    require_date,
    require_int,
    require_string,
    sort_by_created_at,
)

bp = Blueprint("members", __name__)


# ---------------------------------------------------------------------------
# Member
# ---------------------------------------------------------------------------

@bp.route("/vbc/members", methods=["POST"])
@require_roles("PayerAdmin")
def create_member(_user_id: str, _role: str):
    body = get_json_body()
    raw_program = body.get("program_id")
    if isinstance(raw_program, str) and raw_program != "" and raw_program not in db.programs:
        raise_err(ERR_NOT_FOUND, "program_id does not exist")
    reject_unknown_fields(body, {"program_id", "member_ref", "birth_year"})
    program_id = require_string(body, "program_id")
    member_ref = require_string(body, "member_ref")
    birth_year = require_int(body, "birth_year", minimum=1900, maximum=2026)
    if program_id not in db.programs:
        raise_err(ERR_NOT_FOUND, "program_id does not exist")

    # Uniqueness: member_ref within the program.
    for member in db.members.values():
        if member["program_id"] == program_id and member["member_ref"] == member_ref:
            raise_err(ERR_DUPLICATE_MEMBER_REF, "member_ref already exists in the program")

    member = {
        "program_id": program_id,
        "member_ref": member_ref,
        "birth_year": birth_year,
        "member_status": "ELIGIBLE",
    }
    db.stamp_new(member)
    db.members[member["id"]] = member
    return success_object(member, 201)


@bp.route("/vbc/members", methods=["GET"])
@require_roles(*ALL_ROLES)
def list_members(_user_id: str, _role: str):
    limit, offset = parse_pagination()
    items = sort_by_created_at(list(db.members.values()))
    items = apply_filters(items, ["program_id", "member_status"])
    page, total = paginate(items, limit, offset)
    return success_list(page, limit, offset, total)


@bp.route("/vbc/members/<member_id>", methods=["GET"])
@require_roles(*ALL_ROLES)
def get_member(member_id: str, _user_id: str, _role: str):
    member = db.members.get(member_id)
    if member is None:
        raise_err(ERR_NOT_FOUND, "Member id does not exist")
    return success_object(member)


@bp.route("/vbc/members/<member_id>/disenroll", methods=["POST"])
@require_roles("PayerAdmin")
def disenroll_member(member_id: str, _user_id: str, _role: str):
    member = db.members.get(member_id)
    if member is None:
        raise_err(ERR_NOT_FOUND, "Member id does not exist")
    if member["member_status"] != "ELIGIBLE":
        raise_err(ERR_INVALID_STATE_TRANSITION, "Only an ELIGIBLE member can be disenrolled")
    member["member_status"] = "DISENROLLED"
    db.touch(member)
    return success_object(member)


# ---------------------------------------------------------------------------
# EligibilitySpan
# ---------------------------------------------------------------------------

@bp.route("/vbc/eligibility-spans", methods=["POST"])
@require_roles("PayerAdmin")
def create_span(_user_id: str, _role: str):
    body = get_json_body()
    raw_member = body.get("member_id")
    if isinstance(raw_member, str) and raw_member != "" and raw_member not in db.members:
        raise_err(ERR_NOT_FOUND, "member_id does not exist")
    reject_unknown_fields(body, {"member_id", "start_date", "end_date"})
    member_id = require_string(body, "member_id")
    start_date = require_date(body, "start_date")
    end_date = require_date(body, "end_date")
    if member_id not in db.members:
        raise_err(ERR_NOT_FOUND, "member_id does not exist")

    start = db.parse_date(start_date)
    end = db.parse_date(end_date)

    # Priority 9 (overlap) before priority 12 (date range): check overlap only
    # when the range itself is ordered; an inverted range cannot share dates in
    # a meaningful way and is reported as ERR_INVALID_DATE_RANGE below.
    if start <= end:
        for span in db.eligibility_spans.values():
            if span["member_id"] != member_id:
                continue
            other_start = db.parse_date(span["start_date"])
            other_end = db.parse_date(span["end_date"])
            # Closed intervals: sharing even one calendar date is overlap.
            if start <= other_end and end >= other_start:
                raise_err(ERR_SPAN_OVERLAP, "Span shares at least one date with another span of the member")

    # Priority 12: closed interval; equal start == end is a valid one-day span.
    if start > end:
        raise_err(ERR_INVALID_DATE_RANGE, "start_date must be on or before end_date")

    span = {
        "member_id": member_id,
        "start_date": start_date,
        "end_date": end_date,
        "span_status": "ACTIVE",
    }
    db.stamp_new(span)
    db.eligibility_spans[span["id"]] = span
    return success_object(span, 201)


@bp.route("/vbc/eligibility-spans", methods=["GET"])
@require_roles(*ALL_ROLES)
def list_spans(_user_id: str, _role: str):
    limit, offset = parse_pagination()
    items = sort_by_created_at(list(db.eligibility_spans.values()))
    items = apply_filters(items, ["member_id", "span_status"])
    page, total = paginate(items, limit, offset)
    return success_list(page, limit, offset, total)


@bp.route("/vbc/eligibility-spans/<span_id>", methods=["GET"])
@require_roles(*ALL_ROLES)
def get_span(span_id: str, _user_id: str, _role: str):
    span = db.eligibility_spans.get(span_id)
    if span is None:
        raise_err(ERR_NOT_FOUND, "EligibilitySpan id does not exist")
    return success_object(span)


@bp.route("/vbc/eligibility-spans/<span_id>/close", methods=["POST"])
@require_roles("PayerAdmin")
def close_span(span_id: str, _user_id: str, _role: str):
    span = db.eligibility_spans.get(span_id)
    if span is None:
        raise_err(ERR_NOT_FOUND, "EligibilitySpan id does not exist")
    if span["span_status"] != "ACTIVE":
        raise_err(ERR_INVALID_STATE_TRANSITION, "Only an ACTIVE span can be closed")
    span["span_status"] = "CLOSED"
    db.touch(span)
    return success_object(span)
