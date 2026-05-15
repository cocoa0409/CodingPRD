"""Collection-case endpoints (PRD §3.8)."""
from __future__ import annotations

from flask import Blueprint, g

from ..auth import require_auth
from ..constants import SOFT_TO_HARD_REMINDER_THRESHOLD
from ..errors import api_error
from ..response import success_envelope
from ..store import store
from ..utils import get_json_body, require_str

bp = Blueprint("collection_cases", __name__, url_prefix="/scf/collection-cases")


READ_ROLES = ("CollectionManager", "PlatformAdmin")


def _get_case(cid):
    case = store.collection_cases.get(cid)
    if case is None:
        raise api_error("ERR_NOT_FOUND", "Collection case not found")
    return case


def _related_core_enterprise(case: dict):
    schedule = store.repayment_schedules.get(case["schedule_id"])
    if schedule is None:
        return None
    app = store.financing_applications.get(schedule["application_id"])
    if app is None:
        return None
    receivable = store.receivables.get(app["receivable_id"])
    if receivable is None:
        return None
    confirmation = store.payable_confirmations.get(receivable.get("confirmation_id"))
    if confirmation is None:
        return None
    return store.core_enterprises.get(confirmation["core_enterprise_id"])


@bp.post("/<cid>/remind")
@require_auth(["CollectionManager"])
def remind_case(cid):
    case = _get_case(cid)
    if case.get("stage") not in ("SOFT", "HARD"):
        raise api_error("ERR_INVALID_STATE", "Reminder allowed only in SOFT/HARD")
    with store.lock:
        case["reminder_count"] = int(case.get("reminder_count", 0)) + 1
        store.stamp_update(case)
    return success_envelope(case)


@bp.post("/<cid>/escalate")
@require_auth(["CollectionManager"])
def escalate_case(cid):
    case = _get_case(cid)
    if case.get("stage") != "SOFT":
        raise api_error("ERR_INVALID_STATE", "Escalation only from SOFT")
    if int(case.get("reminder_count", 0)) < SOFT_TO_HARD_REMINDER_THRESHOLD:
        raise api_error("ERR_INVALID_STATE", "Reminder threshold not yet reached")
    if case.get("aging_bucket") not in ("DPD_31_60", "DPD_61_90", "DPD_OVER_90"):
        raise api_error("ERR_INVALID_STATE", "Aging bucket not eligible for escalation")
    with store.lock:
        case["stage"] = "HARD"
        store.stamp_update(case)
    return success_envelope(case)


@bp.post("/<cid>/invoke-joint-liability")
@require_auth(["CollectionManager"])
def invoke_joint_liability(cid):
    case = _get_case(cid)
    if case.get("stage") != "HARD":
        raise api_error("ERR_INVALID_STATE", "Joint-liability invocation only from HARD")
    ce = _related_core_enterprise(case)
    if not ce or not ce.get("joint_liability_flag"):
        raise api_error("ERR_INVALID_STATE", "Core enterprise joint_liability_flag is false")
    if case.get("aging_bucket") not in ("DPD_61_90", "DPD_OVER_90"):
        raise api_error("ERR_INVALID_STATE", "Aging bucket not eligible for joint liability")
    with store.lock:
        case["stage"] = "JOINT_LIABILITY"
        store.stamp_update(case)
        store.emit_event(
            "ERP_SYNC",
            {"core_enterprise_id": (ce or {}).get("id"), "case_id": case["id"], "action": "JOINT_LIABILITY"},
        )
    return success_envelope(case)


@bp.post("/<cid>/legal")
@require_auth(["CollectionManager"])
def legal_case(cid):
    case = _get_case(cid)
    stage = case.get("stage")
    if stage not in ("HARD", "JOINT_LIABILITY"):
        raise api_error("ERR_INVALID_STATE", "Legal escalation only from HARD or JOINT_LIABILITY")
    if case.get("aging_bucket") != "DPD_OVER_90":
        raise api_error("ERR_INVALID_STATE", "Aging bucket must be DPD_OVER_90")
    ce = _related_core_enterprise(case)
    if stage == "HARD":
        # PRD: direct HARD -> LEGAL only when core joint_liability_flag is false
        if ce and ce.get("joint_liability_flag"):
            raise api_error("ERR_INVALID_STATE", "Must invoke joint liability before legal when applicable")
    with store.lock:
        case["stage"] = "LEGAL"
        store.stamp_update(case)
    return success_envelope(case)


@bp.post("/<cid>/write-off")
@require_auth(["CollectionManager"])
def write_off_case(cid):
    case = _get_case(cid)
    if case.get("stage") != "LEGAL":
        raise api_error("ERR_INVALID_STATE", "Write-off only from LEGAL")
    if case.get("aging_bucket") != "DPD_OVER_90":
        raise api_error("ERR_INVALID_STATE", "Aging bucket must be DPD_OVER_90")
    body = get_json_body()
    write_off_reason = require_str(body, "write_off_reason")

    schedule = store.repayment_schedules.get(case["schedule_id"])
    application = store.financing_applications.get(schedule["application_id"]) if schedule else None
    receivable = store.receivables.get(application["receivable_id"]) if application else None
    confirmation = (
        store.payable_confirmations.get(receivable["confirmation_id"]) if receivable else None
    )
    ce = (
        store.core_enterprises.get(confirmation["core_enterprise_id"])
        if confirmation
        else None
    )
    principal = int((application or {}).get("approved_amount_cents") or 0)

    with store.lock:
        case["stage"] = "WRITTEN_OFF"
        case["write_off_reason"] = write_off_reason
        store.stamp_update(case)
        if schedule:
            schedule["status"] = "WRITTEN_OFF"
            store.stamp_update(schedule)
        if receivable and receivable.get("status") != "WRITTEN_OFF":
            receivable["status"] = "WRITTEN_OFF"
            store.stamp_update(receivable)
        # Release credit_line_consumed_cents by principal
        if ce is not None and principal > 0:
            ce["credit_line_consumed_cents"] = max(
                0, int(ce.get("credit_line_consumed_cents", 0)) - principal
            )
            store.stamp_update(ce)
        store.append_audit(
            actor_role=g.user_role,
            actor_id=g.user_id,
            entity_type="CollectionCase",
            entity_id=case["id"],
            action="WRITE_OFF",
            amount_cents=principal,
        )
    return success_envelope(case)


@bp.get("/<cid>")
@require_auth(READ_ROLES)
def get_case(cid):
    case = _get_case(cid)
    return success_envelope(case)
