"""Notification endpoints (PRD section 3.5)."""

from flask import Blueprint

import calc
import db
import errors
from auth import require_roles
from envelope import success_object
from serializers import notification_out
from services import (append_event, get_case_or_404, get_or_404,
                      guard_case_mutable, guard_entity_status)
from validate import get_body, opt_str_list, req_enum

bp = Blueprint("notifications", __name__)

RECIPIENT_KINDS = {"MEMBER", "PROVIDER"}
NOTIFICATION_KINDS = {"ACKNOWLEDGEMENT", "EXTENSION_NOTICE", "DECISION",
                      "IRE_FORWARD_NOTICE", "REOPEN_OUTCOME",
                      "EFFECTUATION_CONFIRMATION"}
NOTIFICATION_TERMINAL = ("DELIVERED", "FAILED")
VIEW_ROLES = {"PlatformAdmin", "MemberServicesRep", "ComplianceOfficer"}


def _compute_scores(notification, case):
    member = db.members[case["member_id"]]
    notification["required_elements"] = calc.required_elements_for(
        notification["notification_kind"], notification["recipient_kind"],
        member["program"], case["case_kind"], case["decision_outcome"])
    notification["completeness_score"] = calc.completeness_score(
        notification["required_elements"], notification["supplied_elements"])


@bp.route("/appeals/cases/<cid>/notifications", methods=["POST"])
@require_roles({"MemberServicesRep"})
def create_notification(cid, _user_id, _role):
    case = get_case_or_404(cid)
    # Terminal-state lockdown: no mutation on CLOSED/WITHDRAWN cases
    guard_case_mutable(case)
    body = get_body()
    recipient_kind = req_enum(body, "recipient_kind", RECIPIENT_KINDS)
    notification_kind = req_enum(body, "notification_kind", NOTIFICATION_KINDS)
    supplied = opt_str_list(body, "supplied_elements", [])
    n = db.make_common()
    n.update({
        "case_id": case["id"],
        "recipient_kind": recipient_kind,
        "notification_kind": notification_kind,
        "status": "QUEUED",
        "required_elements": [],
        "supplied_elements": supplied,
        "completeness_score": None,
        "sent_at": None,
    })
    _compute_scores(n, case)
    db.notifications[n["id"]] = n
    return success_object(notification_out(n), status=201)


@bp.route("/appeals/notifications/<nid>", methods=["GET"])
@require_roles(VIEW_ROLES)
def get_notification(nid, _user_id, _role):
    return success_object(notification_out(
        get_or_404(db.notifications, nid, "notification")))


@bp.route("/appeals/notifications/<nid>", methods=["PATCH"])
@require_roles({"MemberServicesRep"})
def patch_notification(nid, _user_id, _role):
    n = get_or_404(db.notifications, nid, "notification")
    # Only while QUEUED; terminal states report ERR_ALREADY_TERMINAL
    guard_entity_status(n, ("QUEUED",), NOTIFICATION_TERMINAL, "notification")
    body = get_body()
    if "supplied_elements" in body:
        n["supplied_elements"] = opt_str_list(body, "supplied_elements",
                                              n["supplied_elements"])
    case = db.cases[n["case_id"]]
    _compute_scores(n, case)
    db.touch(n)
    return success_object(notification_out(n))


@bp.route("/appeals/notifications/<nid>/mark-sent", methods=["POST"])
@require_roles({"MemberServicesRep"})
def mark_sent(nid, _user_id, _role):
    n = get_or_404(db.notifications, nid, "notification")
    guard_entity_status(n, ("QUEUED", "RETRIED"), NOTIFICATION_TERMINAL,
                        "notification")
    if n["completeness_score"] != calc.round2(1):
        raise errors.notification_incomplete()
    if n["sent_at"] is None:
        # sent_at records the first transition into SENT
        n["sent_at"] = db.clock_now()
    n["status"] = "SENT"
    db.touch(n)
    if n["notification_kind"] == "DECISION" and n["recipient_kind"] == "MEMBER":
        case = db.cases.get(n["case_id"])
        if case is not None and case["status"] == "DECIDED":
            case["status"] = "NOTIFIED"
            case["notified_at"] = n["sent_at"]
            append_event(case, "NOTIFICATION_SENT", _role, _user_id)
            db.touch(case)
    return success_object(notification_out(n))


@bp.route("/appeals/notifications/<nid>/mark-delivered", methods=["POST"])
@require_roles({"MemberServicesRep"})
def mark_delivered(nid, _user_id, _role):
    n = get_or_404(db.notifications, nid, "notification")
    guard_entity_status(n, ("SENT",), NOTIFICATION_TERMINAL, "notification")
    n["status"] = "DELIVERED"
    db.touch(n)
    return success_object(notification_out(n))


@bp.route("/appeals/notifications/<nid>/mark-failed", methods=["POST"])
@require_roles({"MemberServicesRep"})
def mark_failed(nid, _user_id, _role):
    n = get_or_404(db.notifications, nid, "notification")
    guard_entity_status(n, ("SENT", "RETRIED"), NOTIFICATION_TERMINAL,
                        "notification")
    n["status"] = "FAILED"
    db.touch(n)
    return success_object(notification_out(n))


@bp.route("/appeals/notifications/<nid>/retry", methods=["POST"])
@require_roles({"MemberServicesRep"})
def retry_notification(nid, _user_id, _role):
    n = get_or_404(db.notifications, nid, "notification")
    # FAILED is terminal with the sole exception of retry
    if n["status"] == "DELIVERED":
        raise errors.already_terminal("notification is DELIVERED")
    if n["status"] != "FAILED":
        raise errors.invalid_state("only FAILED notifications may be retried")
    n["status"] = "RETRIED"
    db.touch(n)
    return success_object(notification_out(n))
