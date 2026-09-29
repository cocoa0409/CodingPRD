"""Noncompliance investigations (PRD 3.10)."""

from flask import Blueprint

import cascade
import common as C
import enums as E
import middleware as M
import queries as Q
import shape as S
from db import now, ordered, plus_days, set_fields, store
from errors import ApiError
from response import list_response, object_response
from serial import public, public_list

bp = Blueprint("cases", __name__)

OPEN_CASE_STATES = ("OPEN", "EVIDENCE_REVIEW", "REMEDIATION_ORDERED", "WITHDRAWAL_ORDERED")


@bp.post("/noncompliance-cases")
def open_case():
    user_id, _ = M.auth([M.COMPLIANCE_OFFICER])
    body = S.body_obj()
    # rung 5
    listing = C.body_fk("listing", body, "listing_id")
    # rung 6
    S.req_str(body, "listing_id")
    category = S.req_str(body, "category")
    evidence_summary = S.req_str(body, "evidence_summary", 1, 500)
    claimed_units = S.req_int(body, "claimed_impact_units", 0, 10000000)
    # rung 7
    S.check_enum(category, E.CASE_CATEGORIES, "category")
    # rung 22
    if listing["compliance_status"] not in ("COMPLIANT", "REMEDIATED"):
        raise ApiError("ERR_INVALID_LISTING_STATE",
                       "the listing's compliance_status does not admit a new case")
    # rung 34
    if category == "IP_WITHDRAWAL":
        raise ApiError("ERR_DEVICE_TYPE_MISMATCH",
                       "the IP_WITHDRAWAL category is reserved to the system")

    case = cascade.make_case(listing, category, evidence_summary, claimed_units, user_id)
    set_fields(listing, compliance_status="UNDER_INVESTIGATION")
    member = store.members.get(listing["member_id"])
    if member is not None:
        cascade.recompute_member(member)
    return object_response(public(case), 201)


@bp.get("/noncompliance-cases/<case_id>")
def get_case(case_id):
    M.auth([M.PROGRAM_ADMIN, M.COMPLIANCE_OFFICER, M.MEMBER])
    return object_response(public(C.must("case", case_id)), 200)


@bp.get("/noncompliance-cases")
def list_cases():
    M.auth([M.PROGRAM_ADMIN, M.COMPLIANCE_OFFICER, M.MEMBER])
    limit, offset = S.paging()
    listing_id = S.q_str("listing_id")
    state = S.q_str("state")
    category = S.q_str("category")
    auto_opened = S.q_bool("auto_opened")
    rows = ordered(store.cases.values())
    if listing_id is not None:
        rows = [r for r in rows if r["listing_id"] == listing_id]
    if state is not None:
        rows = [r for r in rows if r["state"] == state]
    if category is not None:
        rows = [r for r in rows if r["category"] == category]
    if auto_opened is not None:
        rows = [r for r in rows if r["auto_opened"] is auto_opened]
    page, total = C.paginate(rows, limit, offset)
    return list_response(public_list(page), limit, offset, total)


@bp.post("/noncompliance-cases/<case_id>/advance")
def advance_case(case_id):
    M.auth([M.COMPLIANCE_OFFICER])
    case = C.must("case", case_id)
    listing = store.listings.get(case["listing_id"])
    body = S.body_obj()
    # rung 6 -- disposition plus the conditional presence of remediation_days
    disposition = S.req_str(body, "disposition")
    if disposition == "ORDER_REMEDIATION":
        if not S.present(body, "remediation_days"):
            S.bad("remediation_days is required when disposition is ORDER_REMEDIATION")
        raw_days = body.get("remediation_days")
        if isinstance(raw_days, bool) or not isinstance(raw_days, int):
            S.bad("remediation_days must be an integer")
    elif S.present(body, "remediation_days"):
        S.bad("remediation_days must be absent unless disposition is ORDER_REMEDIATION")
    # rung 7
    S.check_enum(disposition, E.CASE_DISPOSITIONS, "disposition")
    # rung 9
    if disposition == "ORDER_REMEDIATION":
        days = body["remediation_days"]
        if days < 1 or days > 365:
            raise ApiError("ERR_INVALID_DATE_RANGE",
                           "remediation_days must be between 1 and 365")
    # rung 23
    origin = {
        "ESCALATE": ("OPEN",),
        "ORDER_REMEDIATION": ("EVIDENCE_REVIEW",),
        "ORDER_WITHDRAWAL": ("EVIDENCE_REVIEW",),
        "CONFIRM_REMEDIATION": ("REMEDIATION_ORDERED",),
    }[disposition]
    if case["state"] not in origin:
        raise ApiError("ERR_INVALID_CASE_STATE",
                       "%s is not available from %s" % (disposition, case["state"]))

    if disposition == "ESCALATE":
        set_fields(case, state="EVIDENCE_REVIEW")
    elif disposition == "ORDER_REMEDIATION":
        set_fields(case,
                   state="REMEDIATION_ORDERED",
                   remediation_deadline_at=plus_days(now(), body["remediation_days"]))
        if listing is not None and listing["publication_status"] == "PUBLISHED":
            set_fields(listing, publication_status="SUPPRESSED")
    elif disposition == "ORDER_WITHDRAWAL":
        set_fields(case, state="WITHDRAWAL_ORDERED")
        if listing is not None:
            set_fields(listing,
                       publication_status="WITHDRAWN",
                       compliance_status="NONCOMPLIANT")
            cascade.revoke_credential(store.submissions.get(listing["submission_id"]))
    else:
        # rung 48 -- equality with the deadline is accepted
        deadline = case["remediation_deadline_at"]
        if deadline is None or now() > deadline:
            raise ApiError("ERR_REMEDIATION_DEADLINE_PASSED",
                           "the remediation deadline has passed")
        set_fields(case, state="REMEDIATED")
        if listing is not None:
            set_fields(listing, compliance_status="REMEDIATED")
    return object_response(public(case), 200)


@bp.post("/noncompliance-cases/<case_id>/close")
def close_case(case_id):
    user_id, _ = M.auth([M.COMPLIANCE_OFFICER])
    case = C.must("case", case_id)
    # rung 23
    if case["state"] not in ("REMEDIATED", "WITHDRAWAL_ORDERED"):
        raise ApiError("ERR_INVALID_CASE_STATE",
                       "closure requires REMEDIATED or WITHDRAWAL_ORDERED")
    # rung 24
    if user_id == case["opened_by_user_id"]:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES",
                       "the officer who opened the case may not close it")
    set_fields(case, state="CLOSED", closed_by_user_id=user_id)
    listing = store.listings.get(case["listing_id"])
    if listing is not None:
        member = store.members.get(listing["member_id"])
        if member is not None:
            cascade.recompute_member(member)
    return object_response(public(case), 200)
