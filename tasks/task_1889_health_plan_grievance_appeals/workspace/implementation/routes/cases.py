"""GrievanceAppealCase endpoints (PRD sections 3.2, 3.3, 3.5, 3.8)."""

from datetime import timedelta

from flask import Blueprint, request

import calc
import db
import errors
from auth import require_roles
from envelope import (paginate, parse_bool_param, parse_pagination,
                      success_list, success_object)
from serializers import (case_out, effectuation_out, event_out,
                         notification_out, referral_out, reopening_out,
                         review_out)
import services
from services import (append_event, create_effectuation, get_case_or_404,
                      get_or_404, guard_status)
from validate import (get_body, opt_bool, opt_int, opt_str, req_enum,
                      req_str)

bp = Blueprint("cases", __name__)

CASE_KINDS = {"GRIEVANCE", "ORG_DETERMINATION", "APPEAL"}
DECISION_OUTCOMES = {"FULLY_FAVORABLE", "PARTIALLY_FAVORABLE", "UNFAVORABLE"}
APPENDABLE_EVENT_TYPES = {"NOTE", "DOCUMENT", "EXTENSION_REQUEST",
                          "CTM_LINKED", "CTM_UNLINKED"}
ALL_ROLES = {"PlatformAdmin", "IntakeSpecialist", "CaseAnalyst",
             "MedicalDirector", "MemberServicesRep", "ComplianceOfficer",
             "ClaimsProcessor"}


# ---------------------------------------------------------------------------
# Intake
# ---------------------------------------------------------------------------

@bp.route("/appeals/cases", methods=["POST"])
@require_roles({"IntakeSpecialist"})
def create_case(_user_id, _role):
    body = get_body()
    member_id = req_str(body, "member_id")
    provider_id = opt_str(body, "provider_id")
    case_kind = req_enum(body, "case_kind", CASE_KINDS)
    expedited_requested = opt_bool(body, "expedited_requested", False)
    expedited_justification = opt_str(body, "expedited_justification")
    reopened_from_case_id = opt_str(body, "reopened_from_case_id")
    if expedited_requested and not (
            expedited_justification and expedited_justification.strip()):
        raise errors.validation(
            "expedited_justification is required when expedited_requested is true")
    # Body FK references (priority 4)
    member = db.members.get(member_id)
    if member is None:
        raise errors.reference_not_found(f"member not found: {member_id}")
    if provider_id is not None and provider_id not in db.providers:
        raise errors.reference_not_found(f"provider not found: {provider_id}")
    if reopened_from_case_id is not None and reopened_from_case_id not in db.cases:
        raise errors.reference_not_found(
            f"reopened_from_case_id not found: {reopened_from_case_id}")
    # Expedited eligibility (priority 14): grievances have no expedited track
    if expedited_requested and case_kind == "GRIEVANCE":
        raise errors.expedited_not_allowed()
    # Duplicate intake guard (priority 20): same member/kind/provider within 1h
    now = db.clock_now()
    for existing in db.cases.values():
        if (existing["member_id"] == member_id
                and existing["case_kind"] == case_kind
                and existing["provider_id"] == provider_id
                and existing["status"] not in ("CLOSED", "WITHDRAWN")
                and (now - existing["received_at"]).total_seconds()
                <= calc.DUPLICATE_WINDOW_SECONDS):
            raise errors.duplicate_case()
    c = db.make_common()
    c.update({
        "member_id": member_id,
        "provider_id": provider_id,
        "case_kind": case_kind,
        "priority_track": "STANDARD",
        "expedited_requested": expedited_requested,
        "expedited_justification": expedited_justification,
        "status": "RECEIVED",
        "decision_outcome": None,
        "received_at": now,
        "acknowledged_at": None,
        "decided_at": None,
        "notified_at": None,
        "closed_at": None,
        "extension_applied": False,
        "resolution_due_at": None,
        "effectuation_due_at": None,
        "ctm_linked": False,
        "reopened_from_case_id": reopened_from_case_id,
        "_triaged_by": None,
    })
    db.cases[c["id"]] = c
    return success_object(case_out(c), status=201)


@bp.route("/appeals/cases/<cid>", methods=["GET"])
@require_roles(ALL_ROLES)
def get_case(cid, _user_id, _role):
    return success_object(case_out(get_case_or_404(cid)))


@bp.route("/appeals/cases", methods=["GET"])
@require_roles({"PlatformAdmin", "ComplianceOfficer", "CaseAnalyst"})
def list_cases(_user_id, _role):
    limit, offset = parse_pagination(request.args)
    rows = list(db.cases.values())
    member_id = request.args.get("member_id")
    if member_id is not None:
        rows = [c for c in rows if c["member_id"] == member_id]
    provider_id = request.args.get("provider_id")
    if provider_id is not None:
        rows = [c for c in rows if c["provider_id"] == provider_id]
    status = request.args.get("status")
    if status is not None:
        rows = [c for c in rows if c["status"] == status]
    case_kind = request.args.get("case_kind")
    if case_kind is not None:
        rows = [c for c in rows if c["case_kind"] == case_kind]
    priority_track = request.args.get("priority_track")
    if priority_track is not None:
        rows = [c for c in rows if c["priority_track"] == priority_track]
    reopened_from = request.args.get("reopened_from_case_id")
    if reopened_from is not None:
        rows = [c for c in rows if c["reopened_from_case_id"] == reopened_from]
    overdue = parse_bool_param(request.args, "overdue")
    if overdue is not None:
        rows = [c for c in rows if calc.case_overdue(c) == overdue]
    rows.sort(key=lambda c: (c["created_at"], c["_seq"]))
    page, total = paginate(rows, limit, offset)
    return success_list([case_out(c) for c in page], total, limit, offset)


# ---------------------------------------------------------------------------
# Triage / review / expedite / extension / decide / withdraw / close
# ---------------------------------------------------------------------------

@bp.route("/appeals/cases/<cid>/triage", methods=["POST"])
@require_roles({"IntakeSpecialist"})
def triage_case(cid, _user_id, _role):
    case = get_case_or_404(cid)
    guard_status(case, ("RECEIVED",))
    member = db.members[case["member_id"]]
    if member["enrollment_status"] != "ACTIVE":
        raise errors.invalid_state("member is not ACTIVE")
    if case["case_kind"] in ("ORG_DETERMINATION", "APPEAL"):
        if case["provider_id"] is None or case["provider_id"] not in db.providers:
            raise errors.reference_not_found(
                "provider_id must reference an existing Provider for this case kind")
    # Acknowledgement window (priority 9): triage within 24h of received_at
    if (db.clock_now() - case["received_at"]).total_seconds() > calc.ACK_WINDOW_HOURS * 3600:
        raise errors.ack_window_missed()
    # Priority classification and policy (priority 15)
    expedited = case["expedited_requested"] and case["case_kind"] != "GRIEVANCE"
    track = "EXPEDITED" if expedited else "STANDARD"
    policy = calc.active_policy_or_error(member["program"], case["case_kind"], track)
    case["priority_track"] = track
    case["acknowledged_at"] = db.clock_now()
    case["resolution_due_at"] = calc.compute_resolution_due(case, policy)
    case["status"] = "TRIAGED"
    case["_triaged_by"] = _user_id
    append_event(case, "NOTE", _role, _user_id, body="TRIAGED")
    db.touch(case)
    return success_object(case_out(case))


@bp.route("/appeals/cases/<cid>/begin-review", methods=["POST"])
@require_roles({"CaseAnalyst"})
def begin_review(cid, _user_id, _role):
    case = get_case_or_404(cid)
    guard_status(case, ("TRIAGED",))
    case["status"] = "IN_REVIEW"
    append_event(case, "NOTE", _role, _user_id, body="REVIEW_STARTED")
    db.touch(case)
    return success_object(case_out(case))


@bp.route("/appeals/cases/<cid>/expedite", methods=["POST"])
@require_roles({"MedicalDirector"})
def expedite_case(cid, _user_id, _role):
    case = get_case_or_404(cid)
    guard_status(case, ("TRIAGED", "IN_REVIEW"))
    if case["case_kind"] == "GRIEVANCE":
        raise errors.expedited_not_allowed()
    if case["priority_track"] != "STANDARD":
        raise errors.invalid_state("case is already EXPEDITED")
    member = db.members[case["member_id"]]
    policy = calc.active_policy_or_error(member["program"], case["case_kind"],
                                         "EXPEDITED")
    case["priority_track"] = "EXPEDITED"
    # Anchor remains received_at; the expedited policy's smaller hours apply.
    case["resolution_due_at"] = calc.compute_resolution_due(case, policy)
    append_event(case, "PRIORITY_UPGRADE", _role, _user_id)
    db.touch(case)
    return success_object(case_out(case))


@bp.route("/appeals/cases/<cid>/extensions", methods=["POST"])
@require_roles({"MemberServicesRep"})
def apply_extension(cid, _user_id, _role):
    case = get_case_or_404(cid)
    body = get_body()
    expected = body.get("expected_case_version")
    if expected is None:
        raise errors.validation("missing required field: expected_case_version")
    if not isinstance(expected, int) or isinstance(expected, bool):
        raise errors.validation("expected_case_version must be an integer")
    guard_status(case, ("TRIAGED", "IN_REVIEW", "PENDING_CLINICAL"))
    member = db.members[case["member_id"]]
    policy = calc.find_active_policy(member["program"], case["case_kind"],
                                     case["priority_track"])
    if case["extension_applied"] or policy is None or policy["extension_hours"] <= 0:
        raise errors.extension_consumed()
    # OCC (PRD section 2.7.1)
    if expected != case["version"]:
        raise errors.stale_version()
    case["extension_applied"] = True
    case["resolution_due_at"] = case["resolution_due_at"] + timedelta(
        hours=policy["extension_hours"])
    append_event(case, "EXTENSION_GRANTED", _role, _user_id)
    db.touch(case)
    return success_object(case_out(case))


@bp.route("/appeals/cases/<cid>/decide", methods=["POST"])
@require_roles({"MedicalDirector", "CaseAnalyst"})
def decide_case(cid, _user_id, _role):
    case = get_case_or_404(cid)
    body = get_body()
    decision_outcome = req_enum(body, "decision_outcome", DECISION_OUTCOMES)
    payment = opt_int(body, "payment_amount_cents", None)
    guard_status(case, ("IN_REVIEW", "PENDING_CLINICAL"))
    if case["status"] == "PENDING_CLINICAL":
        # Segregation of duties (priority 7): decider != triaging specialist
        if case["_triaged_by"] is not None and _user_id == case["_triaged_by"]:
            raise errors.duty_segregation(
                "decider must differ from the IntakeSpecialist who triaged the case")
        # Clinical routing (priority 8): requires a DETERMINED review
        if not services.determined_review_exists(case["id"]):
            raise errors.clinical_review_required(
                "a DETERMINED clinical review is required")
    else:  # IN_REVIEW: non-clinical door, grievances only
        if case["case_kind"] != "GRIEVANCE":
            raise errors.clinical_review_required(
                "non-grievance cases must route through PENDING_CLINICAL")
    # Payment allowance (priority 19)
    if payment is not None:
        if payment < 0:
            raise errors.payment_not_allowed("payment_amount_cents must be >= 0")
        if decision_outcome == "UNFAVORABLE":
            raise errors.payment_not_allowed(
                "payment is not allowed with an UNFAVORABLE outcome")
    case["decision_outcome"] = decision_outcome
    case["decided_at"] = db.clock_now()
    case["status"] = "DECIDED"
    append_event(case, "DECISION_RECORDED", _role, _user_id)
    if decision_outcome != "UNFAVORABLE":
        member = db.members[case["member_id"]]
        policy = calc.active_policy_or_error(member["program"],
                                             case["case_kind"],
                                             case["priority_track"])
        case["effectuation_due_at"] = case["decided_at"] + timedelta(
            hours=policy["effectuation_hours"])
        create_effectuation(case, payment if payment is not None else 0)
    db.touch(case)
    return success_object(case_out(case))


@bp.route("/appeals/cases/<cid>/withdraw", methods=["POST"])
@require_roles({"MemberServicesRep"})
def withdraw_case(cid, _user_id, _role):
    case = get_case_or_404(cid)
    guard_status(case, ("RECEIVED", "TRIAGED", "IN_REVIEW"))
    case["status"] = "WITHDRAWN"
    case["closed_at"] = db.clock_now()
    append_event(case, "NOTE", _role, _user_id, body="WITHDRAWN")
    db.touch(case)
    return success_object(case_out(case))


@bp.route("/appeals/cases/<cid>/close", methods=["POST"])
@require_roles({"ComplianceOfficer"})
def close_case_endpoint(cid, _user_id, _role):
    case = get_case_or_404(cid)
    guard_status(case, ("NOTIFIED", "IRE_REFERRED"))
    if case["status"] == "NOTIFIED":
        if case["decision_outcome"] != "UNFAVORABLE":
            effs = services.effectuations_for_case(case["id"])
            if not any(e["status"] in ("EFFECTUATED", "WAIVED") for e in effs):
                raise errors.invalid_state(
                    "linked Effectuation must be EFFECTUATED or WAIVED before closure")
        if case["decision_outcome"] != "FULLY_FAVORABLE" and case["case_kind"] == "APPEAL":
            refs = services.referrals_for_case(case["id"])
            window_lapsed = (db.clock_now() - case["decided_at"]).total_seconds() \
                > calc.IRE_FORWARD_WINDOW_HOURS * 3600
            if not refs and not window_lapsed:
                raise errors.invalid_state(
                    "an IRE referral or a lapsed 72h forwarding window is required")
    else:  # IRE_REFERRED
        refs = services.referrals_for_case(case["id"])
        ref = refs[-1] if refs else None
        if ref is None or ref["status"] not in ("DECISION_RECEIVED", "EFFECTUATED"):
            raise errors.invalid_state(
                "linked IRE referral must be DECISION_RECEIVED before closure")
        if ref["ire_decision"] in ("OVERTURN_PLAN", "PARTIAL"):
            linked = [e for e in services.effectuations_for_case(case["id"])
                      if e["referral_id"] == ref["id"]]
            if not any(e["status"] == "EFFECTUATED" for e in linked):
                raise errors.invalid_state(
                    "linked Effectuation must be EFFECTUATED before closure")
    services.close_case(case, _role, _user_id)
    return success_object(case_out(case))


# ---------------------------------------------------------------------------
# Case events
# ---------------------------------------------------------------------------

@bp.route("/appeals/cases/<cid>/events", methods=["POST"])
@require_roles({"IntakeSpecialist", "CaseAnalyst", "MemberServicesRep",
                "ComplianceOfficer"})
def append_case_event(cid, _user_id, _role):
    case = get_case_or_404(cid)
    body = get_body()
    event_type = req_enum(body, "event_type", APPENDABLE_EVENT_TYPES)
    note_body = opt_str(body, "body")
    if event_type == "CTM_LINKED":
        if case["status"] not in ("CLOSED", "WITHDRAWN"):
            case["ctm_linked"] = True
    elif event_type == "CTM_UNLINKED":
        if case["ctm_linked"]:
            case["ctm_linked"] = False
    event = append_event(case, event_type, _role, _user_id, body=note_body,
                         bump_case_version=True)
    return success_object(event_out(event), status=201)


@bp.route("/appeals/cases/<cid>/events", methods=["GET"])
@require_roles({"PlatformAdmin", "IntakeSpecialist", "CaseAnalyst",
                "MedicalDirector", "MemberServicesRep", "ComplianceOfficer"})
def list_case_events(cid, _user_id, _role):
    get_case_or_404(cid)
    limit, offset = parse_pagination(request.args)
    rows = [e for e in db.events.values() if e["case_id"] == cid]
    event_type = request.args.get("event_type")
    if event_type is not None:
        rows = [e for e in rows if e["event_type"] == event_type]
    rows.sort(key=lambda e: (e["occurred_at"], e["created_at"], e["_seq"]))
    page, total = paginate(rows, limit, offset)
    return success_list([event_out(e) for e in page], total, limit, offset)


# ---------------------------------------------------------------------------
# Reverse-reachability collections
# ---------------------------------------------------------------------------

@bp.route("/appeals/cases/<cid>/clinical-reviews", methods=["GET"])
@require_roles({"PlatformAdmin", "CaseAnalyst", "MedicalDirector",
                "ComplianceOfficer"})
def list_case_reviews(cid, _user_id, _role):
    get_case_or_404(cid)
    limit, offset = parse_pagination(request.args)
    rows = [r for r in db.reviews.values() if r["case_id"] == cid]
    status = request.args.get("status")
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    rows.sort(key=lambda r: (r["created_at"], r["_seq"]))
    page, total = paginate(rows, limit, offset)
    return success_list([review_out(r) for r in page], total, limit, offset)


@bp.route("/appeals/cases/<cid>/notifications", methods=["GET"])
@require_roles({"PlatformAdmin", "MemberServicesRep", "ComplianceOfficer"})
def list_case_notifications(cid, _user_id, _role):
    get_case_or_404(cid)
    limit, offset = parse_pagination(request.args)
    rows = [n for n in db.notifications.values() if n["case_id"] == cid]
    status = request.args.get("status")
    if status is not None:
        rows = [n for n in rows if n["status"] == status]
    kind = request.args.get("notification_kind")
    if kind is not None:
        rows = [n for n in rows if n["notification_kind"] == kind]
    rows.sort(key=lambda n: (n["created_at"], n["_seq"]))
    page, total = paginate(rows, limit, offset)
    return success_list([notification_out(n) for n in page], total, limit, offset)


@bp.route("/appeals/cases/<cid>/ire-referrals", methods=["GET"])
@require_roles({"PlatformAdmin", "ComplianceOfficer"})
def list_case_referrals(cid, _user_id, _role):
    get_case_or_404(cid)
    limit, offset = parse_pagination(request.args)
    rows = services.referrals_for_case(cid)
    page, total = paginate(rows, limit, offset)
    return success_list([referral_out(r) for r in page], total, limit, offset)


@bp.route("/appeals/cases/<cid>/effectuations", methods=["GET"])
@require_roles({"PlatformAdmin", "ComplianceOfficer", "ClaimsProcessor"})
def list_case_effectuations(cid, _user_id, _role):
    get_case_or_404(cid)
    limit, offset = parse_pagination(request.args)
    rows = services.effectuations_for_case(cid)
    status = request.args.get("status")
    if status is not None:
        rows = [e for e in rows if e["status"] == status]
    page, total = paginate(rows, limit, offset)
    return success_list([effectuation_out(e) for e in page], total, limit, offset)


@bp.route("/appeals/cases/<cid>/reopenings", methods=["GET"])
@require_roles({"PlatformAdmin", "ComplianceOfficer"})
def list_case_reopenings(cid, _user_id, _role):
    get_case_or_404(cid)
    limit, offset = parse_pagination(request.args)
    rows = [r for r in db.reopenings.values() if r["case_id"] == cid]
    status = request.args.get("status")
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    rows.sort(key=lambda r: (r["created_at"], r["_seq"]))
    page, total = paginate(rows, limit, offset)
    return success_list([reopening_out(r) for r in page], total, limit, offset)
