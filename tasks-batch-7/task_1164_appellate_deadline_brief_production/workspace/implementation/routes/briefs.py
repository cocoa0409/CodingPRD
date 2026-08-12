"""Brief endpoints (PRD §3.5)."""
from flask import Blueprint, request

from db import STORE, now_iso, parse_iso
from errors import ApiError
from middleware import get_auth, require_roles
from response import success_object, success_list
from services.core import (
    get_body, req_enum, req_int, opt_iso, new_entity, paginate, touch,
    path_case, path_brief, path_attorney, path_schedule, path_record,
    fk_schedule, fk_attorney, court_for_case, compute_over_limit,
    toa_for_brief, schedule_due_for_brief_type, record_for_case,
    schedule_for_case,
)
from services.workflows import create_filing, BRIEF_TYPE_TO_DEADLINE_KIND

bp = Blueprint("briefs", __name__)

ALL = ("CourtAdmin", "Attorney", "CourtClerk", "ParalegalStaff")
BRIEF_TYPES = ("OPENING", "RESPONSE", "REPLY", "AMICUS")
TERMINAL_BRIEF = ("ACCEPTED", "REJECTED", "STRICKEN")


def _check_admitted(attorney, case):
    if case["court_id"] not in (attorney.get("admitted_court_ids") or []):
        raise ApiError("ERR_NOT_ADMITTED",
                       "Attorney not admitted to the case's court", 403)


@bp.post("/appellate/cases/<cid>/briefs")
def create_brief(cid):
    auth = get_auth()
    require_roles(auth, ("Attorney",))
    case = path_case(cid)
    body = get_body()
    schedule = fk_schedule(body.get("schedule_id"))
    brief_type = req_enum(body, "brief_type", BRIEF_TYPES)
    author = fk_attorney(body.get("author_attorney_id"), "author_attorney_id")
    page_count = req_int(body, "page_count")
    word_count = req_int(body, "word_count")

    if schedule["case_id"] != case["id"]:
        raise ApiError("ERR_FK_NOT_FOUND",
                       "schedule_id does not belong to this case", 404)

    # Admission check (priority 7): the acting attorney is the author
    acting = STORE.attorneys.get(auth.user_id)
    if acting is None:
        raise ApiError("ERR_NOT_ADMITTED",
                       "Acting attorney record not found", 403)
    _check_admitted(acting, case)

    court = court_for_case(case)
    brief = new_entity({
        "case_id": case["id"],
        "schedule_id": schedule["id"],
        "brief_type": brief_type,
        "author_attorney_id": author["id"],
        "due_at": schedule_due_for_brief_type(schedule, brief_type),
        "page_count": page_count,
        "word_count": word_count,
        "over_limit": False,
        "status": "DRAFT",
    })
    brief["over_limit"] = compute_over_limit(brief, court)
    STORE.briefs[brief["id"]] = brief

    # Auto-create TOA (1:1)
    toa = new_entity({
        "brief_id": brief["id"],
        "citation_count": 0,
        "verified_count": 0,
        "unverified_count": 0,
        "generated_at": None,
    })
    STORE.toas[toa["id"]] = toa

    out = dict(brief)
    out.pop("_seq", None)
    return success_object(out, 201)


@bp.get("/appellate/cases/<cid>/briefs")
def list_case_briefs(cid):
    auth = get_auth()
    require_roles(auth, ALL)
    case = path_case(cid)
    items = [b for b in STORE.briefs.values() if b["case_id"] == case["id"]]
    bt = request.args.get("brief_type")
    if bt is not None:
        items = [b for b in items if b["brief_type"] == bt]
    st = request.args.get("status")
    if st is not None:
        items = [b for b in items if b["status"] == st]
    page, limit, offset, total = paginate(items)
    return success_list(page, limit, offset, total)


@bp.get("/appellate/briefs/<bid>")
def get_brief(bid):
    auth = get_auth()
    require_roles(auth, ALL)
    b = path_brief(bid)
    out = dict(b)
    out.pop("_seq", None)
    return success_object(out)


@bp.patch("/appellate/briefs/<bid>")
def patch_brief(bid):
    auth = get_auth()
    require_roles(auth, ("Attorney",))
    b = path_brief(bid)
    if b["status"] in TERMINAL_BRIEF:
        raise ApiError("ERR_ALREADY_TERMINAL", "Brief is in a terminal state", 409)
    if b["status"] not in ("DRAFT", "IN_REVIEW"):
        raise ApiError("ERR_INVALID_STATE",
                       "Brief can be edited only in DRAFT or IN_REVIEW", 409)
    body = get_body()
    changed = False
    if "page_count" in body:
        b["page_count"] = req_int(body, "page_count")
        changed = True
    if "word_count" in body:
        b["word_count"] = req_int(body, "word_count")
        changed = True
    case = STORE.cases.get(b["case_id"])
    court = court_for_case(case) if case else None
    if court:
        b["over_limit"] = compute_over_limit(b, court)
    touch(b)
    out = dict(b)
    out.pop("_seq", None)
    return success_object(out)


@bp.post("/appellate/briefs/<bid>/submit-review")
def submit_review(bid):
    auth = get_auth()
    require_roles(auth, ("Attorney",))
    b = path_brief(bid)
    if b["status"] in TERMINAL_BRIEF:
        raise ApiError("ERR_ALREADY_TERMINAL", "Brief is in a terminal state", 409)
    if b["status"] != "DRAFT":
        raise ApiError("ERR_INVALID_STATE", "Brief must be DRAFT to submit for review", 409)
    # Only the drafter submits own draft
    if b["author_attorney_id"] != auth.user_id:
        raise ApiError("ERR_FORBIDDEN_ROLE",
                       "Only the drafting attorney may submit the brief for review", 403)
    case = STORE.cases.get(b["case_id"])
    if case and case.get("posture") not in ("BRIEFING", "RECORD_PENDING"):
        raise ApiError("ERR_INVALID_STATE",
                       "Case posture must be BRIEFING or RECORD_PENDING", 409)
    b["status"] = "IN_REVIEW"
    touch(b)
    out = dict(b)
    out.pop("_seq", None)
    return success_object(out)


@bp.post("/appellate/briefs/<bid>/approve")
def approve_brief(bid):
    auth = get_auth()
    require_roles(auth, ("Attorney",))
    b = path_brief(bid)
    if b["status"] in TERMINAL_BRIEF:
        raise ApiError("ERR_ALREADY_TERMINAL", "Brief is in a terminal state", 409)
    # Priority 5: state
    if b["status"] != "IN_REVIEW":
        raise ApiError("ERR_INVALID_STATE", "Brief must be IN_REVIEW to approve", 409)
    # Priority 6: segregation of duties
    if b["author_attorney_id"] == auth.user_id:
        raise ApiError("ERR_SELF_APPROVAL_FORBIDDEN",
                       "Brief approver must differ from brief author", 403)
    case = STORE.cases.get(b["case_id"])
    # Priority 7: admission
    acting = STORE.attorneys.get(auth.user_id)
    if acting is None:
        raise ApiError("ERR_NOT_ADMITTED", "Acting attorney record not found", 403)
    _check_admitted(acting, case)
    # Priority 9: over limit
    if b.get("over_limit"):
        raise ApiError("ERR_BRIEF_OVER_LIMIT",
                       "Brief exceeds the court's length limit", 422)
    # Priority 10: TOA verification when court mandates e-filing
    court = court_for_case(case) if case else None
    if court and court.get("efiling_required"):
        toa = toa_for_brief(b["id"])
        if toa is None or toa.get("unverified_count", 0) != 0:
            raise ApiError("ERR_TOA_UNVERIFIED",
                           "Table of authorities has unverified citations", 422)
    b["status"] = "READY"
    touch(b)
    out = dict(b)
    out.pop("_seq", None)
    return success_object(out)


@bp.post("/appellate/briefs/<bid>/return-draft")
def return_draft(bid):
    auth = get_auth()
    require_roles(auth, ("Attorney",))
    b = path_brief(bid)
    if b["status"] in TERMINAL_BRIEF:
        raise ApiError("ERR_ALREADY_TERMINAL", "Brief is in a terminal state", 409)
    if b["status"] != "IN_REVIEW":
        raise ApiError("ERR_INVALID_STATE", "Brief must be IN_REVIEW to return", 409)
    if b["author_attorney_id"] == auth.user_id:
        raise ApiError("ERR_SELF_APPROVAL_FORBIDDEN",
                       "Reviewer must differ from brief author", 403)
    b["status"] = "DRAFT"
    touch(b)
    out = dict(b)
    out.pop("_seq", None)
    return success_object(out)


@bp.post("/appellate/briefs/<bid>/efile")
def efile_brief(bid):
    auth = get_auth()
    require_roles(auth, ("Attorney",))
    b = path_brief(bid)
    if b["status"] in TERMINAL_BRIEF:
        raise ApiError("ERR_ALREADY_TERMINAL", "Brief is in a terminal state", 409)
    # Priority 5: state
    if b["status"] != "READY":
        raise ApiError("ERR_INVALID_STATE", "Brief must be READY to e-file", 409)
    case = STORE.cases.get(b["case_id"])
    # Priority 7: admission
    acting = STORE.attorneys.get(auth.user_id)
    if acting is None:
        raise ApiError("ERR_NOT_ADMITTED", "Acting attorney record not found", 403)
    _check_admitted(acting, case)
    # Priority 8: deadline currency
    if b.get("due_at") and parse_iso(now_iso()) > parse_iso(b["due_at"]):
        raise ApiError("ERR_DEADLINE_PASSED", "Brief due date has passed", 409)
    # Priority 9: over limit
    if b.get("over_limit"):
        raise ApiError("ERR_BRIEF_OVER_LIMIT",
                       "Brief exceeds the court's length limit", 422)
    # Priority 11: record + schedule readiness
    rec = record_for_case(case["id"]) if case else None
    sched = STORE.briefing_schedules.get(b["schedule_id"])
    rec_ok = rec is not None and rec["status"] in ("COMPLETE", "FILED")
    sched_ok = sched is not None and sched["status"] == "ACTIVE"
    if not (rec_ok and sched_ok):
        raise ApiError("ERR_RECORD_NOT_COMPLETE",
                       "Record must be COMPLETE/FILED and schedule ACTIVE", 409)
    # Priority 16: service completeness
    body = get_body()
    served = body.get("served_party_emails")
    if not isinstance(served, list) or any(not isinstance(x, str) for x in served):
        raise ApiError("ERR_INVALID_REQUEST",
                       "served_party_emails must be an array of strings", 400)
    if len(served) == 0:
        raise ApiError("ERR_SERVICE_INCOMPLETE",
                       "E-filed brief must serve at least one party email", 422)

    b["status"] = "EFILED"
    touch(b)
    filing = create_filing(case, "BRIEF", "EFILE", served, brief_id=b["id"])
    touch(case)
    out = dict(filing)
    out.pop("_seq", None)
    return success_object(out)


@bp.post("/appellate/briefs/<bid>/strike")
def strike_brief(bid):
    auth = get_auth()
    require_roles(auth, ("CourtClerk",))
    b = path_brief(bid)
    if b["status"] == "STRICKEN":
        raise ApiError("ERR_ALREADY_TERMINAL", "Brief is already STRICKEN", 409)
    if b["status"] != "ACCEPTED":
        raise ApiError("ERR_INVALID_STATE", "Brief must be ACCEPTED to strike", 409)
    body = get_body()
    reason = body.get("reason")
    if not isinstance(reason, str) or reason == "":
        raise ApiError("ERR_INVALID_REQUEST", "reason is required", 400)
    b["status"] = "STRICKEN"
    touch(b)
    # Compensating reversal: reset deadline met
    case = STORE.cases.get(b["case_id"])
    kind = BRIEF_TYPE_TO_DEADLINE_KIND.get(b["brief_type"])
    if case and kind:
        for d in STORE.deadlines.values():
            if d["case_id"] == case["id"] and d["kind"] == kind and d["met"]:
                d["met"] = False
                d["met_at"] = None
                touch(d)
    out = dict(b)
    out.pop("_seq", None)
    return success_object(out)


# --- Sub-resource / cross filters -------------------------------------------

@bp.get("/appellate/briefing-schedules/<sid>/briefs")
def list_schedule_briefs(sid):
    auth = get_auth()
    require_roles(auth, ALL)
    schedule = path_schedule(sid)
    items = [b for b in STORE.briefs.values() if b["schedule_id"] == schedule["id"]]
    bt = request.args.get("brief_type")
    if bt is not None:
        items = [b for b in items if b["brief_type"] == bt]
    st = request.args.get("status")
    if st is not None:
        items = [b for b in items if b["status"] == st]
    page, limit, offset, total = paginate(items)
    return success_list(page, limit, offset, total)


@bp.get("/appellate/briefs")
def list_briefs():
    auth = get_auth()
    require_roles(auth, ALL)
    items = list(STORE.briefs.values())
    sid = request.args.get("schedule_id")
    if sid is not None:
        items = [b for b in items if b["schedule_id"] == sid]
    aid = request.args.get("author_attorney_id")
    if aid is not None:
        items = [b for b in items if b["author_attorney_id"] == aid]
    bt = request.args.get("brief_type")
    if bt is not None:
        items = [b for b in items if b["brief_type"] == bt]
    st = request.args.get("status")
    if st is not None:
        items = [b for b in items if b["status"] == st]
    page, limit, offset, total = paginate(items)
    return success_list(page, limit, offset, total)


@bp.get("/appellate/attorneys/<aid>/briefs")
def list_attorney_briefs(aid):
    auth = get_auth()
    require_roles(auth, ALL)
    att = path_attorney(aid)
    items = [b for b in STORE.briefs.values() if b["author_attorney_id"] == att["id"]]
    st = request.args.get("status")
    if st is not None:
        items = [b for b in items if b["status"] == st]
    page, limit, offset, total = paginate(items)
    return success_list(page, limit, offset, total)
