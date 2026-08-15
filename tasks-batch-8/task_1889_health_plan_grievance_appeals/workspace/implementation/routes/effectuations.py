"""Effectuation endpoints (PRD section 3.7)."""

from flask import Blueprint, request

import calc
import db
import errors
from auth import require_roles
from envelope import (paginate, parse_pagination, success_list,
                      success_object)
from serializers import effectuation_out
from services import (append_event, get_or_404, guard_entity_status)
from validate import get_body

bp = Blueprint("effectuations", __name__)

EFFECTUATION_TERMINAL = ("EFFECTUATED", "WAIVED")
VIEW_ROLES = {"PlatformAdmin", "ComplianceOfficer", "ClaimsProcessor"}


@bp.route("/appeals/effectuations/<eid>", methods=["GET"])
@require_roles(VIEW_ROLES)
def get_effectuation(eid, _user_id, _role):
    return success_object(effectuation_out(
        get_or_404(db.effectuations, eid, "effectuation")))


@bp.route("/appeals/effectuations", methods=["GET"])
@require_roles(VIEW_ROLES)
def list_effectuations(_user_id, _role):
    limit, offset = parse_pagination(request.args)
    rows = list(db.effectuations.values())
    case_id = request.args.get("case_id")
    if case_id is not None:
        rows = [e for e in rows if e["case_id"] == case_id]
    referral_id = request.args.get("referral_id")
    if referral_id is not None:
        rows = [e for e in rows if e["referral_id"] == referral_id]
    status = request.args.get("status")
    if status is not None:
        rows = [e for e in rows if e["status"] == status]
    rows.sort(key=lambda e: (e["created_at"], e["_seq"]))
    page, total = paginate(rows, limit, offset)
    return success_list([effectuation_out(e) for e in page], total, limit, offset)


@bp.route("/appeals/effectuations/<eid>/start", methods=["POST"])
@require_roles({"ClaimsProcessor"})
def start_effectuation(eid, _user_id, _role):
    eff = get_or_404(db.effectuations, eid, "effectuation")
    guard_entity_status(eff, ("PENDING",), EFFECTUATION_TERMINAL, "effectuation")
    # W-9 gate (priority 17)
    if eff["payment_amount_cents"] > 0:
        case = db.cases.get(eff["case_id"])
        provider = db.providers.get(case["provider_id"]) if case and case["provider_id"] else None
        if provider is not None and not provider["w9_on_file"]:
            raise errors.w9_required()
    eff["status"] = "IN_PROGRESS"
    db.touch(eff)
    case = db.cases.get(eff["case_id"])
    if case is not None:
        append_event(case, "EFFECTUATION_STARTED", _role, _user_id,
                     bump_case_version=True)
    return success_object(effectuation_out(eff))


@bp.route("/appeals/effectuations/<eid>/complete", methods=["POST"])
@require_roles({"ClaimsProcessor"})
def complete_effectuation(eid, _user_id, _role):
    eff = get_or_404(db.effectuations, eid, "effectuation")
    guard_entity_status(eff, ("IN_PROGRESS", "OVERDUE", "ESCALATED"),
                        EFFECTUATION_TERMINAL, "effectuation")
    body = get_body()
    expected = body.get("expected_effectuation_version")
    if expected is None:
        raise errors.validation(
            "missing required field: expected_effectuation_version")
    if not isinstance(expected, int) or isinstance(expected, bool):
        raise errors.validation("expected_effectuation_version must be an integer")
    # OCC (PRD section 2.7.3)
    if expected != eff["version"]:
        raise errors.stale_version()
    eff["status"] = "EFFECTUATED"
    eff["completed_at"] = db.clock_now()
    case = db.cases.get(eff["case_id"])
    if case is not None and case.get("effectuation_due_at") is not None \
            and case.get("decided_at") is not None:
        business_hours_only = False
        member = db.members.get(case["member_id"])
        if member is not None:
            policy = calc.find_active_policy(member["program"],
                                             case["case_kind"],
                                             case["priority_track"])
            if policy is not None:
                business_hours_only = policy["business_hours_only"]
        eff["timeliness_percent"] = calc.effectuation_timeliness(
            case, eff, business_hours_only=business_hours_only)
    db.touch(eff)
    if case is not None:
        append_event(case, "EFFECTUATION_COMPLETED", _role, _user_id,
                     bump_case_version=True)
    # Referral auto-transition DECISION_RECEIVED -> EFFECTUATED
    if eff["referral_id"]:
        ref = db.referrals.get(eff["referral_id"])
        if ref is not None and ref["status"] == "DECISION_RECEIVED":
            ref["status"] = "EFFECTUATED"
            db.touch(ref)
    return success_object(effectuation_out(eff))


@bp.route("/appeals/effectuations/<eid>/waive", methods=["POST"])
@require_roles({"ComplianceOfficer"})
def waive_effectuation(eid, _user_id, _role):
    eff = get_or_404(db.effectuations, eid, "effectuation")
    guard_entity_status(eff, ("PENDING",), EFFECTUATION_TERMINAL, "effectuation")
    if eff["payment_amount_cents"] != 0:
        raise errors.waiver_not_allowed()
    eff["status"] = "WAIVED"
    db.touch(eff)
    return success_object(effectuation_out(eff))


@bp.route("/appeals/effectuations/<eid>/escalate", methods=["POST"])
@require_roles({"ComplianceOfficer"})
def escalate_effectuation(eid, _user_id, _role):
    eff = get_or_404(db.effectuations, eid, "effectuation")
    guard_entity_status(eff, ("OVERDUE",), EFFECTUATION_TERMINAL, "effectuation")
    eff["status"] = "ESCALATED"
    db.touch(eff)
    return success_object(effectuation_out(eff))
