"""EvidenceItem and EvidencePacket endpoints (PRD 3.3)."""
from datetime import timedelta
from flask import Blueprint, request

from db import db
from errors import (
    raise_error, ERR_INVALID_STATE_TRANSITION, ERR_ACTIVE_PACKET_EXISTS,
    ERR_STALE_CASE_VERSION, ERR_REVIEW_RESPONSE_LATE, ERR_DUPLICATE_RESPONSE,
    ERR_PARTY_BINDING_MISMATCH, ERR_REVIEW_WINDOW_OPEN, ERR_INVALID_REQUEST,
)
from middleware import authorized, check_case_read_access, party_side_of, STAFF_READ_ROLES
from response import success_list, success_object
from services.core import (
    new_record, touch, public, bump_case, append_event, auto_notice, get_case,
    check_case_not_terminal, get_pagination, sort_items, apply_filters,
    require_active_investigator, active_assignment_for,
    EVIDENCE_SIDES, EVIDENCE_TYPES, LIVE_PACKET_STATES,
)
from util import clock_iso, clock_dt, parse_datetime, fmt_datetime
from validate import (
    get_body, req_str, req_enum, require_path, as_int, as_enum, as_str,
)

bp = Blueprint("evidence", __name__)

READ_ROLES = STAFF_READ_ROLES + ["Party"]


# ---------------------------------------------------------------------------
# EvidenceItem
# ---------------------------------------------------------------------------

@bp.post("/cases/<cid>/evidence-items")
def submit_evidence(cid):
    caller = authorized(["Party", "Investigator"])
    case = get_case(cid)
    check_case_not_terminal(case)
    body = get_body()
    # Tier 4: case must be INVESTIGATION.
    if case["status"] != "INVESTIGATION":
        raise_error(ERR_INVALID_STATE_TRANSITION,
                    f"case is {case['status']}, not INVESTIGATION")
    # Tier 7: Investigator-role actors must hold the case's ACTIVE assignment.
    if caller.role == "Investigator":
        require_active_investigator(case, caller)
    # Tier 8: Party actors submit for their own side only.
    side = as_enum(body, "submitted_by_side", EVIDENCE_SIDES)
    if caller.role == "Party" and side is not None:
        if party_side_of(case, caller.user_id) is None or side != party_side_of(case, caller.user_id):
            raise_error(ERR_PARTY_BINDING_MISMATCH,
                        "submitted_by_side does not match the acting party's side")
    # Tier 11: schema.
    submitted_by_side = req_enum(body, "submitted_by_side", EVIDENCE_SIDES)
    evidence_type = req_enum(body, "evidence_type", EVIDENCE_TYPES)
    description = req_str(body, "description")
    rec = new_record("evidence_items", {
        "case_id": cid,
        "submitted_by_side": submitted_by_side,
        "evidence_type": evidence_type,
        "description": description,
        "collected_at": clock_iso(),
        "status": "SUBMITTED",
        "exclusion_reason": None,
    })
    append_event(cid, "EVIDENCE_SUBMITTED", caller,
                 {"evidence_item_id": rec["id"], "evidence_type": evidence_type})
    return success_object(public(rec), 201)


@bp.get("/cases/<cid>/evidence-items")
def list_evidence(cid):
    caller = authorized(READ_ROLES)
    case = get_case(cid)
    check_case_read_access(caller, case)
    items = [e for e in db["evidence_items"].values() if e["case_id"] == cid]
    items = apply_filters(items, {
        "status": request.args.get("status"),
        "submitted_by_side": request.args.get("submitted_by_side"),
    })
    items = sort_items(items)
    total = len(items)
    limit, offset = get_pagination()
    page = items[offset:offset + limit]
    return success_list([public(r) for r in page], total, limit, offset)


@bp.get("/evidence-items/<eid>")
def get_evidence(eid):
    caller = authorized(READ_ROLES)
    item = require_path("evidence_items", eid)
    case = get_case(item["case_id"])
    check_case_read_access(caller, case)
    return success_object(public(item))


@bp.post("/evidence-items/<eid>/begin-review")
def begin_review(eid):
    caller = authorized(["Investigator"])
    item = require_path("evidence_items", eid)
    case = get_case(item["case_id"])
    if item["status"] not in ("SUBMITTED", "EXCLUDED"):
        raise_error(ERR_INVALID_STATE_TRANSITION,
                    f"evidence item is {item['status']}; begin-review requires SUBMITTED or EXCLUDED")
    if case["status"] not in ("INVESTIGATION", "EVIDENCE_REVIEW"):
        raise_error(ERR_INVALID_STATE_TRANSITION,
                    f"case is {case['status']}; evidence review requires INVESTIGATION or EVIDENCE_REVIEW")
    require_active_investigator(case, caller)
    item["status"] = "UNDER_REVIEW"
    touch(item)
    append_event(case["id"], "EVIDENCE_REVIEW_STARTED", caller,
                 {"evidence_item_id": eid, "status": "UNDER_REVIEW"})
    return success_object(public(item))


@bp.post("/evidence-items/<eid>/rule-relevance")
def rule_relevance(eid):
    caller = authorized(["Investigator"])
    item = require_path("evidence_items", eid)
    case = get_case(item["case_id"])
    if item["status"] != "UNDER_REVIEW":
        raise_error(ERR_INVALID_STATE_TRANSITION,
                    f"evidence item is {item['status']}, not UNDER_REVIEW")
    require_active_investigator(case, caller)
    body = get_body()
    ruling = req_enum(body, "ruling", ["ACCEPTED", "EXCLUDED"])
    if ruling == "EXCLUDED":
        exclusion_reason = req_str(body, "exclusion_reason")
        item["exclusion_reason"] = exclusion_reason
        item["status"] = "EXCLUDED"
    else:
        item["exclusion_reason"] = None
        item["status"] = "ACCEPTED"
    touch(item)
    append_event(case["id"], "EVIDENCE_RULED", caller,
                 {"evidence_item_id": eid, "status": item["status"]})
    return success_object(public(item))


# ---------------------------------------------------------------------------
# EvidencePacket
# ---------------------------------------------------------------------------

@bp.post("/cases/<cid>/evidence-packets")
def create_packet(cid):
    caller = authorized(["Investigator"])
    case = get_case(cid)
    check_case_not_terminal(case)
    body = get_body()
    # Tier 7: one live packet per case.
    if any(p["case_id"] == cid and p["status"] in LIVE_PACKET_STATES
           for p in db["evidence_packets"].values()):
        raise_error(ERR_ACTIVE_PACKET_EXISTS,
                    "another evidence packet on this case is still live")
    # Tier 7: actor must hold the case's ACTIVE assignment.
    require_active_investigator(case, caller)
    # Tier 10: OCC.
    expected = as_int(body, "expected_case_version")
    if expected is not None and expected != case["version"]:
        raise_error(ERR_STALE_CASE_VERSION,
                    "expected_case_version does not match the case's current version")
    # Tier 11: schema (expected_case_version is non-optional).
    if not isinstance(body.get("expected_case_version"), int) \
            or isinstance(body.get("expected_case_version"), bool):
        raise_error(ERR_INVALID_REQUEST, "missing or invalid field: expected_case_version")

    sequence = sum(1 for p in db["evidence_packets"].values() if p["case_id"] == cid) + 1
    rec = new_record("evidence_packets", {
        "case_id": cid,
        "packet_sequence": sequence,
        "investigative_report_summary": None,
        "report_attached_at": None,
        "status": "DRAFT",
        "released_at": None,
        "review_closes_at": None,
        "complainant_responded_at": None,
        "respondent_responded_at": None,
        "pinned_item_ids": [],
    })
    append_event(cid, "PACKET_CREATED", caller,
                 {"packet_id": rec["id"], "packet_sequence": sequence})
    # Supersede the FINALIZED predecessor, returning its pinned ACCEPTED items
    # to UNDER_REVIEW (PRD 3.3 create-with-supersede).
    finalized = [
        p for p in db["evidence_packets"].values()
        if p["case_id"] == cid and p["status"] == "FINALIZED"
    ]
    if finalized:
        old = max(finalized, key=lambda p: p["_seq"])
        old["status"] = "SUPERSEDED"
        touch(old)
        append_event(cid, "PACKET_SUPERSEDED", caller,
                     {"packet_id": old["id"], "status": "SUPERSEDED"}, system=True)
        for item_id in old.get("pinned_item_ids", []):
            item = db["evidence_items"].get(item_id)
            if item is not None and item["status"] == "ACCEPTED":
                item["status"] = "UNDER_REVIEW"
                touch(item)
                append_event(cid, "EVIDENCE_REVIEW_STARTED", caller,
                             {"evidence_item_id": item["id"], "status": "UNDER_REVIEW"},
                             system=True)
    bump_case(case)
    return success_object(public(rec), 201)


@bp.get("/cases/<cid>/evidence-packets")
def list_packets(cid):
    caller = authorized(READ_ROLES)
    case = get_case(cid)
    check_case_read_access(caller, case)
    items = [p for p in db["evidence_packets"].values() if p["case_id"] == cid]
    items = apply_filters(items, {"status": request.args.get("status")})
    items = sort_items(items)
    total = len(items)
    limit, offset = get_pagination()
    page = items[offset:offset + limit]
    return success_list([public(r) for r in page], total, limit, offset)


@bp.get("/evidence-packets/<pid>")
def get_packet(pid):
    caller = authorized(READ_ROLES)
    packet = require_path("evidence_packets", pid)
    case = get_case(packet["case_id"])
    check_case_read_access(caller, case)
    return success_object(public(packet))


@bp.post("/evidence-packets/<pid>/attach-report")
def attach_report(pid):
    caller = authorized(["Investigator"])
    packet = require_path("evidence_packets", pid)
    case = get_case(packet["case_id"])
    if packet["status"] != "DRAFT":
        raise_error(ERR_INVALID_STATE_TRANSITION,
                    f"packet is {packet['status']}, not DRAFT")
    require_active_investigator(case, caller)
    body = get_body()
    summary = req_str(body, "investigative_report_summary")
    packet["investigative_report_summary"] = summary
    packet["report_attached_at"] = clock_iso()
    touch(packet)
    append_event(case["id"], "REPORT_ATTACHED", caller, {"packet_id": pid})
    return success_object(public(packet))


@bp.post("/evidence-packets/<pid>/release")
def release_packet(pid):
    caller = authorized(["Investigator"])
    packet = require_path("evidence_packets", pid)
    case = get_case(packet["case_id"])
    if packet["status"] != "DRAFT":
        raise_error(ERR_INVALID_STATE_TRANSITION,
                    f"packet is {packet['status']}, not DRAFT")
    if case["status"] != "INVESTIGATION":
        raise_error(ERR_INVALID_STATE_TRANSITION,
                    f"case is {case['status']}, not INVESTIGATION")
    if packet.get("report_attached_at") is None:
        raise_error(ERR_INVALID_STATE_TRANSITION,
                    "investigative report must be attached before release")
    require_active_investigator(case, caller)

    now = clock_dt()
    released_at = fmt_datetime(now)
    packet["released_at"] = released_at
    packet["review_closes_at"] = fmt_datetime(now + timedelta(days=10))
    accepted = [
        e for e in db["evidence_items"].values()
        if e["case_id"] == case["id"] and e["status"] == "ACCEPTED"
    ]
    accepted.sort(key=lambda e: (parse_datetime(e["collected_at"]), e["created_at"], e["_seq"]))
    packet["pinned_item_ids"] = [e["id"] for e in accepted]
    packet["status"] = "RELEASED_FOR_REVIEW"
    touch(packet)
    case["status"] = "EVIDENCE_REVIEW"
    bump_case(case)
    append_event(case["id"], "PACKET_RELEASED", caller,
                 {"packet_id": pid, "status": "RELEASED_FOR_REVIEW"})
    auto_notice(case["id"], "EVIDENCE_RELEASE", "BOTH",
                "The evidence packet has been released for review.")
    append_event(case["id"], "NOTICE_SENT", caller,
                 {"notice_type": "EVIDENCE_RELEASE", "recipient_side": "BOTH"})
    return success_object(public(packet))


@bp.post("/evidence-packets/<pid>/review-responses")
def record_review_response(pid):
    caller = authorized(["Party"])
    packet = require_path("evidence_packets", pid)
    case = get_case(packet["case_id"])
    body = get_body()
    if packet["status"] != "RELEASED_FOR_REVIEW":
        raise_error(ERR_INVALID_STATE_TRANSITION,
                    f"packet is {packet['status']}, not RELEASED_FOR_REVIEW")
    # Tier 6: timeliness, inclusive at the close instant.
    if clock_dt() > parse_datetime(packet["review_closes_at"]):
        raise_error(ERR_REVIEW_RESPONSE_LATE,
                    "the evidence review window has closed")
    # Tier 7: one response per party side per packet.
    side = as_enum(body, "party_side", ["COMPLAINANT", "RESPONDENT"])
    if side == "COMPLAINANT" and packet.get("complainant_responded_at") is not None:
        raise_error(ERR_DUPLICATE_RESPONSE,
                    "the complainant side has already responded on this packet")
    if side == "RESPONDENT" and packet.get("respondent_responded_at") is not None:
        raise_error(ERR_DUPLICATE_RESPONSE,
                    "the respondent side has already responded on this packet")
    # Tier 8: party binding.
    if side is not None:
        actor_side = party_side_of(case, caller.user_id)
        if actor_side is None or side != actor_side:
            raise_error(ERR_PARTY_BINDING_MISMATCH,
                        "party_side does not match the acting party's binding on the case")
    # Tier 11: schema.
    party_side = req_enum(body, "party_side", ["COMPLAINANT", "RESPONDENT"])
    req_str(body, "response_text")

    now = clock_iso()
    if party_side == "COMPLAINANT":
        packet["complainant_responded_at"] = now
    else:
        packet["respondent_responded_at"] = now
    touch(packet)
    append_event(case["id"], "REVIEW_RESPONSE_RECORDED", caller,
                 {"packet_id": pid, "party_side": party_side})
    if packet.get("complainant_responded_at") is not None \
            and packet.get("respondent_responded_at") is not None:
        packet["status"] = "REVIEW_CLOSED"
        touch(packet)
        append_event(case["id"], "PACKET_REVIEW_CLOSED", caller,
                     {"packet_id": pid, "status": "REVIEW_CLOSED"}, system=True)
    return success_object(public(packet), 201)


@bp.post("/evidence-packets/<pid>/finalize")
def finalize_packet(pid):
    caller = authorized(["Investigator"])
    packet = require_path("evidence_packets", pid)
    case = get_case(packet["case_id"])
    if packet["status"] == "RELEASED_FOR_REVIEW":
        # Tier 6: window must be closed (both responses in, or clock at/past close).
        both_in = packet.get("complainant_responded_at") is not None \
            and packet.get("respondent_responded_at") is not None
        clock_past = clock_dt() >= parse_datetime(packet["review_closes_at"])
        if not (both_in or clock_past):
            raise_error(ERR_REVIEW_WINDOW_OPEN,
                        "the review window is still open with responses outstanding")
        packet["status"] = "REVIEW_CLOSED"
        touch(packet)
        append_event(case["id"], "PACKET_REVIEW_CLOSED", caller,
                     {"packet_id": pid, "status": "REVIEW_CLOSED"}, system=True)
    elif packet["status"] != "REVIEW_CLOSED":
        raise_error(ERR_INVALID_STATE_TRANSITION,
                    f"packet is {packet['status']}, not REVIEW_CLOSED")
    if case["status"] != "EVIDENCE_REVIEW":
        raise_error(ERR_INVALID_STATE_TRANSITION,
                    f"case is {case['status']}, not EVIDENCE_REVIEW")
    if packet.get("report_attached_at") is None:
        raise_error(ERR_INVALID_STATE_TRANSITION,
                    "investigative report must be attached before finalize")
    asg = require_active_investigator(case, caller)

    packet["status"] = "FINALIZED"
    touch(packet)
    case["status"] = "HEARING_PREPARATION"
    bump_case(case)
    asg["status"] = "COMPLETED"
    touch(asg)
    append_event(case["id"], "PACKET_FINALIZED", caller,
                 {"packet_id": pid, "status": "FINALIZED"})
    return success_object(public(packet))


@bp.post("/evidence-packets/<pid>/withdraw")
def withdraw_packet(pid):
    caller = authorized(["Investigator"])
    packet = require_path("evidence_packets", pid)
    case = get_case(packet["case_id"])
    if packet["status"] != "DRAFT":
        raise_error(ERR_INVALID_STATE_TRANSITION,
                    f"packet is {packet['status']}, not DRAFT")
    require_active_investigator(case, caller)
    packet["status"] = "WITHDRAWN"
    touch(packet)
    append_event(case["id"], "PACKET_WITHDRAWN", caller,
                 {"packet_id": pid, "status": "WITHDRAWN"})
    return success_object(public(packet))
