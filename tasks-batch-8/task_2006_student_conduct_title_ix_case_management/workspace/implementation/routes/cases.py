"""Case intake, lifecycle transitions, reconcile, and audit log (PRD 3.1, 3.8)."""
from datetime import timedelta
from flask import Blueprint, request

from db import db
from errors import (
    raise_error, ERR_INVALID_STATE_TRANSITION, ERR_FORBIDDEN_ROLE,
    ERR_ONLY_COMPLAINANT_MAY_FILE, ERR_JURISDICTION_REQUIREMENTS_UNMET,
    ERR_REMAND_SCOPE_MISMATCH, ERR_INVALID_REQUEST,
)
from middleware import authorized, check_case_read_access, STAFF_READ_ROLES, ALL_ROLES
from response import success_list, success_object
from services.core import (
    new_record, touch, public, bump_case, append_event, auto_notice, get_case,
    check_case_not_terminal, get_pagination, sort_items, apply_filters,
    recompute_exposure, CATEGORIES, TITLE_IX_CATEGORIES, RECEIVED_VIA, STANDARDS,
    DISMISSAL_REASONS,
)
from util import clock_iso, clock_dt, parse_datetime
from validate import (
    get_body, req_enum_list, req_datetime, req_bool, req_enum, opt_enum,
    require_profile_fk, as_bool, as_str,
)

bp = Blueprint("cases", __name__)

DISMISS_FROM_STATES = {
    "JURISDICTION_REVIEW", "AWAITING_FORMAL_COMPLAINT", "INVESTIGATION",
    "EVIDENCE_REVIEW", "HEARING_PREPARATION", "INFORMAL_RESOLUTION_IN_PROGRESS",
}


def _mint_report_number(received_iso):
    year = parse_datetime(received_iso).year
    seq = sum(
        1 for c in db["cases"].values()
        if parse_datetime(c["received_at"]).year == year
    ) + 1
    return f"RPT-{year}-{seq:04d}"


@bp.post("/cases")
def create_case():
    caller = authorized(["TitleIXCoordinator", "CaseAdministrator"])
    body = get_body()
    # Tier 3: body FK existence.
    require_profile_fk(body, "complainant_id")
    require_profile_fk(body, "respondent_id")
    require_profile_fk(body, "coordinator_id")
    # Tier 11: schema.
    complainant_id = body["complainant_id"]
    respondent_id = body["respondent_id"]
    coordinator_id = body["coordinator_id"]
    categories = req_enum_list(body, "categories", CATEGORIES)
    occurred_at = req_datetime(body, "occurred_at")
    in_program = req_bool(body, "occurred_in_program_activity")
    in_us = req_bool(body, "occurred_in_united_states")
    received_via = req_enum(body, "received_via", RECEIVED_VIA)
    standard = opt_enum(body, "standard_of_evidence", STANDARDS, "PREPONDERANCE")

    received_at = clock_iso()
    rec = new_record("cases", {
        "report_number": _mint_report_number(received_at),
        "complainant_id": complainant_id,
        "respondent_id": respondent_id,
        "coordinator_id": coordinator_id,
        "categories": categories,
        "occurred_at": occurred_at,
        "occurred_in_program_activity": in_program,
        "occurred_in_united_states": in_us,
        "received_via": received_via,
        "received_at": received_at,
        "status": "RECEIVED",
        "formal_complaint_signed": False,
        "formal_complaint_filed_at": None,
        "standard_of_evidence": standard,
        "dismissal_reason": None,
        "remand_target": None,
        "active_supportive_measure_count": 0,
        "interim_suspension_eligible": False,
        "exposure_score": 0,
        "closed_at": None,
    })
    recompute_exposure(rec)
    append_event(rec["id"], "REPORT_RECEIVED", caller, {
        "report_number": rec["report_number"],
    })
    return success_object(public(rec), 201)


@bp.get("/cases")
def list_cases():
    authorized(STAFF_READ_ROLES)
    items = list(db["cases"].values())
    filters = {
        "status": request.args.get("status"),
        "complainant_id": request.args.get("complainant_id"),
        "respondent_id": request.args.get("respondent_id"),
        "coordinator_id": request.args.get("coordinator_id"),
    }
    items = apply_filters(items, filters)
    category = request.args.get("category")
    if category:
        items = [c for c in items if category in c.get("categories", [])]
    received_year = request.args.get("received_year")
    if received_year:
        try:
            year = int(received_year)
        except (TypeError, ValueError):
            raise_error(ERR_INVALID_REQUEST, "received_year must be an integer")
        items = [c for c in items if parse_datetime(c["received_at"]).year == year]
    items = sort_items(items)
    total = len(items)
    limit, offset = get_pagination()
    page = items[offset:offset + limit]
    return success_list([public(r) for r in page], total, limit, offset)


@bp.get("/cases/<cid>")
def get_one_case(cid):
    caller = authorized(list(ALL_ROLES))
    case = get_case(cid)
    check_case_read_access(caller, case)
    return success_object(public(case))


@bp.post("/cases/<cid>/begin-jurisdiction-review")
def begin_jurisdiction_review(cid):
    caller = authorized(["TitleIXCoordinator"])
    case = get_case(cid)
    if case["status"] != "RECEIVED":
        raise_error(ERR_INVALID_STATE_TRANSITION,
                    f"case is {case['status']}, not RECEIVED")
    if caller.user_id != case["coordinator_id"]:
        raise_error(ERR_FORBIDDEN_ROLE,
                    "only the case's owning coordinator may begin jurisdiction review")
    case["status"] = "JURISDICTION_REVIEW"
    bump_case(case)
    append_event(cid, "JURISDICTION_REVIEW_STARTED", caller, {"status": "JURISDICTION_REVIEW"})
    return success_object(public(case))


@bp.post("/cases/<cid>/confirm-jurisdiction")
def confirm_jurisdiction(cid):
    caller = authorized(["TitleIXCoordinator"])
    case = get_case(cid)
    if case["status"] != "JURISDICTION_REVIEW":
        raise_error(ERR_INVALID_STATE_TRANSITION,
                    f"case is {case['status']}, not JURISDICTION_REVIEW")
    ok = (
        case["occurred_in_program_activity"] is True
        and case["occurred_in_united_states"] is True
        and any(c in TITLE_IX_CATEGORIES for c in case["categories"])
    )
    if not ok:
        raise_error(ERR_JURISDICTION_REQUIREMENTS_UNMET,
                    "jurisdiction facts unmet or no Title IX category present")
    case["status"] = "AWAITING_FORMAL_COMPLAINT"
    bump_case(case)
    append_event(cid, "JURISDICTION_CONFIRMED", caller, {"status": "AWAITING_FORMAL_COMPLAINT"})
    return success_object(public(case))


@bp.post("/cases/<cid>/dismiss")
def dismiss_case(cid):
    caller = authorized(["TitleIXCoordinator"])
    case = get_case(cid)
    body = get_body()
    # Tier 4 state: from-state + referral-flag mapping (PRD 3.1).
    refer = as_bool(body, "refer_to_conduct")
    status = case["status"]
    if status not in DISMISS_FROM_STATES:
        raise_error(ERR_INVALID_STATE_TRANSITION,
                    f"dismissal is not available from {status}")
    if refer is True and status != "JURISDICTION_REVIEW":
        # Referral exists only at the jurisdiction stage.
        raise_error(ERR_INVALID_STATE_TRANSITION,
                    f"refer_to_conduct dismissal matches no transition from {status}")
    # Tier 11 schema.
    dismissal_reason = req_enum(body, "dismissal_reason", DISMISSAL_REASONS)
    refer_to_conduct = req_bool(body, "refer_to_conduct")

    # Cascades per stage (PRD 3.1).
    if status in ("INVESTIGATION", "HEARING_PREPARATION"):
        for h in db["hearings"].values():
            if h["case_id"] == cid and h["status"] in ("SCHEDULED", "ADJOURNED"):
                h["status"] = "CANCELLED"
                touch(h)
                append_event(cid, "HEARING_CANCELLED", caller,
                             {"hearing_id": h["id"], "status": "CANCELLED"}, system=True)
    if status == "INFORMAL_RESOLUTION_IN_PROGRESS":
        for ir in db["informal_resolutions"].values():
            if ir["case_id"] == cid and ir["status"] in ("PROPOSED", "IN_PROGRESS"):
                ir["status"] = "TERMINATED"
                touch(ir)
                append_event(cid, "INFORMAL_TERMINATED", caller,
                             {"informal_resolution_id": ir["id"]}, system=True)

    now = clock_iso()
    case["dismissal_reason"] = dismissal_reason
    case["closed_at"] = now
    if refer_to_conduct:
        case["status"] = "REFERRED_TO_CONDUCT"
        append_event(cid, "CASE_REFERRED", caller, {"status": "REFERRED_TO_CONDUCT",
                                                    "dismissal_reason": dismissal_reason})
    else:
        case["status"] = "DISMISSED"
        append_event(cid, "CASE_DISMISSED", caller, {"status": "DISMISSED",
                                                     "dismissal_reason": dismissal_reason})
    bump_case(case)
    auto_notice(cid, "DISMISSAL", "BOTH", "The case has been dismissed.")
    append_event(cid, "NOTICE_SENT", caller, {"notice_type": "DISMISSAL", "recipient_side": "BOTH"})
    return success_object(public(case))


@bp.post("/cases/<cid>/file-formal-complaint")
def file_formal_complaint(cid):
    caller = authorized(["Party"])
    case = get_case(cid)
    if case["status"] != "AWAITING_FORMAL_COMPLAINT":
        raise_error(ERR_INVALID_STATE_TRANSITION,
                    f"case is {case['status']}, not AWAITING_FORMAL_COMPLAINT")
    if caller.user_id != case["complainant_id"]:
        raise_error(ERR_ONLY_COMPLAINANT_MAY_FILE,
                    "only the case complainant may file the formal complaint")
    now = clock_iso()
    case["status"] = "INVESTIGATION"
    case["formal_complaint_signed"] = True
    case["formal_complaint_filed_at"] = now
    bump_case(case)
    append_event(cid, "FORMAL_COMPLAINT_FILED", caller, {"formal_complaint_signed": True})
    auto_notice(cid, "ALLEGATIONS", "BOTH",
                "Notice of allegations: a formal complaint has been filed.")
    append_event(cid, "NOTICE_SENT", caller, {"notice_type": "ALLEGATIONS", "recipient_side": "BOTH"})
    return success_object(public(case))


@bp.post("/cases/<cid>/finalize-closure")
def finalize_closure(cid):
    caller = authorized(["TitleIXCoordinator"])
    case = get_case(cid)
    if case["status"] != "DETERMINATION_ISSUED":
        raise_error(ERR_INVALID_STATE_TRANSITION,
                    f"case is {case['status']}, not DETERMINATION_ISSUED")
    det = None
    for d in db["determinations"].values():
        if d["case_id"] == cid and d["status"] == "ISSUED":
            if det is None or d["_seq"] > det["_seq"]:
                det = d
    now = clock_dt()
    if det is None or not (now > parse_datetime(det["appeal_deadline"])):
        raise_error(ERR_INVALID_STATE_TRANSITION,
                    "the full appeal window must have elapsed before closure")
    if any(a["case_id"] == cid and a["status"] in ("FILED", "UNDER_REVIEW")
           for a in db["appeals"].values()):
        raise_error(ERR_INVALID_STATE_TRANSITION,
                    "an appeal is still pending on this case")
    det["status"] = "FINAL"
    touch(det)
    append_event(cid, "DETERMINATION_FINALIZED", caller, {"determination_id": det["id"]})
    case["status"] = "CLOSED"
    case["closed_at"] = clock_iso()
    bump_case(case)
    append_event(cid, "CASE_CLOSED", caller, {"status": "CLOSED"})
    return success_object(public(case))


@bp.post("/cases/<cid>/resume")
def resume_case(cid):
    caller = authorized(["TitleIXCoordinator"])
    case = get_case(cid)
    body = get_body()
    if case["status"] != "REMANDED":
        raise_error(ERR_INVALID_STATE_TRANSITION,
                    f"case is {case['status']}, not REMANDED")
    # Optional payload target consistency (PRD 3.6 remand-scope consistency).
    requested = as_str(body, "remand_target") or as_str(body, "target")
    if requested is not None and requested != case.get("remand_target"):
        raise_error(ERR_REMAND_SCOPE_MISMATCH,
                    "resume target does not match the case's remand_target")
    target = case.get("remand_target")
    if target == "INVESTIGATION":
        finalized = [
            p for p in db["evidence_packets"].values()
            if p["case_id"] == cid and p["status"] == "FINALIZED"
        ]
        if finalized:
            packet = max(finalized, key=lambda p: p["_seq"])
            packet["status"] = "SUPERSEDED"
            touch(packet)
            append_event(cid, "PACKET_SUPERSEDED", caller,
                         {"packet_id": packet["id"], "status": "SUPERSEDED"}, system=True)
            for item_id in packet.get("pinned_item_ids", []):
                item = db["evidence_items"].get(item_id)
                if item is not None and item["status"] == "ACCEPTED":
                    item["status"] = "UNDER_REVIEW"
                    touch(item)
                    append_event(cid, "EVIDENCE_REVIEW_STARTED", caller,
                                 {"evidence_item_id": item["id"], "status": "UNDER_REVIEW"},
                                 system=True)
        case["status"] = "INVESTIGATION"
    else:
        case["status"] = "HEARING_PREPARATION"
    case["remand_target"] = None
    bump_case(case)
    append_event(cid, "CASE_RESUMED", caller, {"status": case["status"]})
    return success_object(public(case))


@bp.post("/cases/<cid>/reconcile")
def reconcile_case(cid):
    caller = authorized(["TitleIXCoordinator", "CaseAdministrator"])
    case = get_case(cid)
    check_case_not_terminal(case)
    now = clock_dt()

    expired_measure_ids = []
    expired_directive_ids = []
    review_closed_packet_ids = []
    completed_sanction_ids = []

    for m in sort_items([m for m in db["supportive_measures"].values() if m["case_id"] == cid]):
        if m["status"] == "ACTIVE" and m.get("effective_to") is not None \
                and parse_datetime(m["effective_to"]) <= now:
            m["status"] = "EXPIRED"
            touch(m)
            case["active_supportive_measure_count"] -= 1
            expired_measure_ids.append(m["id"])
            append_event(cid, "MEASURE_EXPIRED", None,
                         {"measure_id": m["id"], "status": "EXPIRED"}, system=True)

    directives = sort_items([d for d in db["no_contact_directives"].values() if d["case_id"] == cid])
    for d in directives:
        if d["status"] == "ACTIVE" and d.get("effective_to") is not None \
                and parse_datetime(d["effective_to"]) <= now:
            d["status"] = "EXPIRED"
            touch(d)
            expired_directive_ids.append(d["id"])
            append_event(cid, "DIRECTIVE_EXPIRED", None,
                         {"directive_id": d["id"], "status": "EXPIRED"}, system=True)
    if expired_directive_ids:
        recompute_exposure(case)

    for p in sort_items([p for p in db["evidence_packets"].values() if p["case_id"] == cid]):
        if p["status"] == "RELEASED_FOR_REVIEW" and p.get("review_closes_at") is not None \
                and parse_datetime(p["review_closes_at"]) <= now:
            p["status"] = "REVIEW_CLOSED"
            touch(p)
            review_closed_packet_ids.append(p["id"])
            append_event(cid, "PACKET_REVIEW_CLOSED", None,
                         {"packet_id": p["id"], "status": "REVIEW_CLOSED"}, system=True)

    det_ids = {d["id"] for d in db["determinations"].values() if d["case_id"] == cid}
    for s in sort_items([s for s in db["sanctions"].values() if s["determination_id"] in det_ids]):
        if s["status"] == "ACTIVE" and s.get("duration_days") is not None \
                and s.get("effective_from") is not None:
            completes_at = parse_datetime(s["effective_from"]) + timedelta(days=s["duration_days"])
            if completes_at <= now:
                s["status"] = "COMPLETED"
                touch(s)
                completed_sanction_ids.append(s["id"])
                append_event(cid, "SANCTION_COMPLETED", None,
                             {"sanction_id": s["id"], "status": "COMPLETED"}, system=True)

    if expired_measure_ids or expired_directive_ids or review_closed_packet_ids or completed_sanction_ids:
        bump_case(case)

    return success_object({
        "expired_measure_ids": expired_measure_ids,
        "expired_directive_ids": expired_directive_ids,
        "review_closed_packet_ids": review_closed_packet_ids,
        "completed_sanction_ids": completed_sanction_ids,
    })


@bp.get("/cases/<cid>/events")
def list_case_events(cid):
    authorized(STAFF_READ_ROLES)
    get_case(cid)
    items = [e for e in db["case_events"].values() if e["case_id"] == cid]
    items = apply_filters(items, {"event_type": request.args.get("event_type")})
    items = sort_items(items)
    total = len(items)
    limit, offset = get_pagination()
    page = items[offset:offset + limit]
    return success_list([public(r) for r in page], total, limit, offset)
