"""Hardship endpoints: create request, documents, withdraw, pay, suspension record."""

from flask import Blueprint, request

import db
import errors
from middleware import require_roles, check_participant_ownership, paginate
from response import success_object, success_list
from services import audit
from services import calculations as calc
from services.state import (get_participant, get_hardship, plan_of_participant,
                            plan_of_hardship, require_plan_active,
                            election_of_participant, create_tax_event,
                            has_active_suspension)
from services.util import new_id, now_iso, today, touch, iso, date_iso, parse, add_months, add_years

bp = Blueprint("hardship", __name__)

HARDSHIP_REASONS = ("MEDICAL", "FUNERAL", "EVICTION", "TUITION", "HOME_PURCHASE", "DISASTER")
DOCUMENT_TYPES = ("INVOICE", "MEDICAL_BILL", "BANK_STATEMENT", "ATTESTATION",
                  "EVICTION_NOTICE", "OTHER")


def _bad(msg):
    return errors.err(errors.ERR_INVALID_REQUEST, msg, 400)


def _create_approval_tasks(plan, subject_type, subject_id, chain):
    for i, approver_role in enumerate(chain, start=1):
        task = {
            "id": new_id(),
            "plan_id": plan["id"],
            "subject_type": subject_type,
            "subject_id": subject_id,
            "step_order": i,
            "approver_role": approver_role,
            "status": "PENDING",
            "decided_by": None,
            "decided_on": None,
        }
        task["created_at"] = now_iso()
        task["updated_at"] = task["created_at"]
        task["version"] = 1
        db.approval_tasks[task["id"]] = task


@bp.route("/participants/<participant_id>/hardship-requests", methods=["POST"])
def create_hardship(participant_id):
    user_id, role = require_roles("Participant")
    participant = get_participant(participant_id)
    check_participant_ownership(user_id, role, participant["id"])
    plan = plan_of_participant(participant)
    body = request.get_json(silent=True) or {}
    if not isinstance(body, dict):
        raise _bad("Body must be a JSON object")
    reason = body.get("reason_category")
    amount = body.get("amount_cents")
    semantics = body.get("amount_semantics", "GROSS")
    attestation = body.get("attestation")
    if reason not in HARDSHIP_REASONS:
        raise _bad("reason_category is not a recognized safe-harbor reason")
    if not isinstance(amount, int) or isinstance(amount, bool) or amount <= 0:
        raise _bad("amount_cents is required and must be a positive integer")
    if semantics not in ("NET", "GROSS"):
        raise _bad("amount_semantics must be NET or GROSS")
    if attestation is not None and not isinstance(attestation, bool):
        raise _bad("attestation must be a boolean")

    # Plan posture gate
    require_plan_active(plan)

    today_dt = today()
    # Priority 10: suspension overlap
    if has_active_suspension(participant["id"], today_dt):
        raise errors.err(errors.ERR_SUSPENSION_OVERLAP,
                         "An ACTIVE suspension record exists for the participant", 422)
    # Priority 11: business constraints in pinned order
    if reason not in plan["allowed_hardship_reasons"]:
        raise errors.err(errors.ERR_UNSAFE_HARBOR_REASON,
                         "reason_category not permitted by the plan", 422)
    if participant["employment_status"] != "ACTIVE":
        raise errors.err(errors.ERR_EMPLOYMENT_NOT_ACTIVE,
                         "Employment is not ACTIVE", 422)
    # Priority 12: fiscal
    if amount > participant["vested_balance_cents"]:
        raise errors.err(errors.ERR_INSUFFICIENT_VESTED_BALANCE,
                         "amount_cents exceeds vested balance", 422)

    econ = calc.hardship_gross_up(amount, semantics, plan["withholding_rate_bps"])
    hr = {
        "id": new_id(),
        "participant_id": participant["id"],
        "plan_id": plan["id"],
        "reason_category": reason,
        "amount_cents": amount,
        "amount_semantics": semantics,
        "attestation": attestation,
        "gross_withdrawal_cents": econ["gross_withdrawal_cents"],
        "withholding_cents": econ["withholding_cents"],
        "fee_cents": econ["fee_cents"],
        "net_disbursed_cents": econ["net_disbursed_cents"],
        "status": "UNDER_REVIEW",
        "paid_on": None,
    }
    hr["created_at"] = now_iso()
    hr["updated_at"] = hr["created_at"]
    hr["version"] = 1
    db.hardship_requests[hr["id"]] = hr
    _create_approval_tasks(plan, "HARDSHIP", hr["id"], plan["hardship_approval_chain"])
    audit.append(plan["id"], role, user_id, "HARDSHIP_REQUESTED",
                 "HardshipRequest", hr["id"],
                 {"reason_category": reason, "amount_cents": amount})
    return success_object(hr, status=201)


@bp.route("/participants/<participant_id>/hardship-requests", methods=["GET"])
def list_participant_hardships(participant_id):
    user_id, role = require_roles("RecordkeeperAdmin", "PlanSponsor", "Auditor", "Participant")
    participant = get_participant(participant_id)
    check_participant_ownership(user_id, role, participant["id"])
    items = sorted([h for h in db.hardship_requests.values()
                    if h["participant_id"] == participant["id"]],
                   key=lambda r: r["created_at"])
    page, total, limit, offset = paginate(items)
    return success_list(page, total, limit, offset)


@bp.route("/hardship-requests/<hardship_id>", methods=["GET"])
def read_hardship(hardship_id):
    user_id, role = require_roles("RecordkeeperAdmin", "PlanSponsor", "Auditor", "Participant")
    hr = get_hardship(hardship_id)
    check_participant_ownership(user_id, role, hr["participant_id"])
    return success_object(hr)


@bp.route("/hardship-requests/<hardship_id>/documents", methods=["POST"])
def upload_document(hardship_id):
    user_id, role = require_roles("Participant")
    hr = get_hardship(hardship_id)
    check_participant_ownership(user_id, role, hr["participant_id"])
    body = request.get_json(silent=True) or {}
    if not isinstance(body, dict):
        raise _bad("Body must be a JSON object")
    doc_type = body.get("document_type")
    amount = body.get("amount_cents")
    description = body.get("description")
    if doc_type not in DOCUMENT_TYPES:
        raise _bad("document_type is not a recognized value")
    if not isinstance(amount, int) or isinstance(amount, bool) or amount < 0:
        raise _bad("amount_cents is required and must be a non-negative integer")
    if description is not None and not isinstance(description, str):
        raise _bad("description must be a string")

    if hr["status"] not in ("UNDER_REVIEW", "PENDING_DOCUMENTS"):
        raise errors.err(errors.ERR_INVALID_STATE,
                         f"Cannot upload documents to a request in {hr['status']}", 409)

    doc = {
        "id": new_id(),
        "created_at": now_iso(),
        "hardship_request_id": hr["id"],
        "document_type": doc_type,
        "amount_cents": amount,
        "description": description,
        "retained_until": None,
    }
    db.hardship_documents[doc["id"]] = doc

    # If PENDING_DOCUMENTS: return to UNDER_REVIEW and reopen the DOCS_REQUESTED task
    if hr["status"] == "PENDING_DOCUMENTS":
        hr["status"] = "UNDER_REVIEW"
        touch(hr)
        for task in db.approval_tasks.values():
            if task["subject_type"] == "HARDSHIP" and task["subject_id"] == hr["id"] \
                    and task["status"] == "DOCS_REQUESTED":
                task["status"] = "PENDING"
                task["decided_by"] = None
                task["decided_on"] = None
                touch(task)

    audit.append(hr["plan_id"], role, user_id, "HARDSHIP_DOCUMENT_UPLOADED",
                 "HardshipDocument", doc["id"],
                 {"document_type": doc_type, "amount_cents": amount})
    return success_object(doc, status=201)


@bp.route("/hardship-requests/<hardship_id>/documents", methods=["GET"])
def list_documents(hardship_id):
    user_id, role = require_roles("RecordkeeperAdmin", "PlanSponsor", "Auditor", "Participant")
    hr = get_hardship(hardship_id)
    check_participant_ownership(user_id, role, hr["participant_id"])
    items = sorted([d for d in db.hardship_documents.values()
                    if d["hardship_request_id"] == hr["id"]],
                   key=lambda r: r["created_at"])
    page, total, limit, offset = paginate(items)
    return success_list(page, total, limit, offset)


@bp.route("/hardship-requests/<hardship_id>/withdraw", methods=["POST"])
def withdraw_hardship(hardship_id):
    user_id, role = require_roles("Participant")
    hr = get_hardship(hardship_id)
    check_participant_ownership(user_id, role, hr["participant_id"])
    if hr["status"] not in ("UNDER_REVIEW", "PENDING_DOCUMENTS"):
        raise errors.err(errors.ERR_INVALID_STATE,
                         f"Cannot withdraw a request in {hr['status']}", 409)
    hr["status"] = "WITHDRAWN"
    touch(hr)
    for task in db.approval_tasks.values():
        if task["subject_type"] == "HARDSHIP" and task["subject_id"] == hr["id"] \
                and task["status"] == "PENDING":
            task["status"] = "CANCELLED"
            touch(task)
    return success_object(hr)


@bp.route("/hardship-requests/<hardship_id>/pay", methods=["POST"])
def pay_hardship(hardship_id):
    user_id, role = require_roles("RecordkeeperAdmin")
    hr = get_hardship(hardship_id)
    plan = plan_of_hardship(hr)
    participant = get_participant(hr["participant_id"])
    if hr["status"] != "APPROVED":
        raise errors.err(errors.ERR_INVALID_STATE,
                         f"Cannot pay a request in {hr['status']}", 409)
    require_plan_active(plan)
    if hr["gross_withdrawal_cents"] > participant["vested_balance_cents"]:
        raise errors.err(errors.ERR_INSUFFICIENT_VESTED_BALANCE,
                         "gross_withdrawal_cents exceeds vested balance", 422)

    today_dt = today()
    hr["status"] = "PAID"
    hr["paid_on"] = date_iso(today_dt)
    touch(hr)
    participant["vested_balance_cents"] -= hr["gross_withdrawal_cents"]

    # Suspension record
    suspension = {
        "id": new_id(),
        "participant_id": participant["id"],
        "hardship_request_id": hr["id"],
        "starts_on": date_iso(today_dt),
        "ends_on": date_iso(add_months(today_dt, plan["hardship_suspension_months"])),
        "status": "ACTIVE",
    }
    suspension["created_at"] = now_iso()
    suspension["updated_at"] = suspension["created_at"]
    suspension["version"] = 1
    db.suspension_records[suspension["id"]] = suspension

    # Election ACTIVE -> SUSPENDED cascade
    election = election_of_participant(participant["id"])
    if election and election["status"] == "ACTIVE":
        election["status"] = "SUSPENDED"
        touch(election)
        participant["contribution_status"] = "SUSPENDED"

    # Tax event
    create_tax_event(participant, "HARDSHIP_DISTRIBUTION", hr["id"],
                     hr["gross_withdrawal_cents"], today_dt)

    # Document retention stamps
    retained_until = add_years(today_dt, 7)
    for doc in db.hardship_documents.values():
        if doc["hardship_request_id"] == hr["id"]:
            doc["retained_until"] = date_iso(retained_until)

    touch(participant)
    audit.append(plan["id"], role, user_id, "HARDSHIP_PAID",
                 "HardshipRequest", hr["id"],
                 {"gross_withdrawal_cents": hr["gross_withdrawal_cents"],
                  "paid_on": hr["paid_on"]})
    return success_object(hr)


@bp.route("/hardship-requests/<hardship_id>/approval-tasks", methods=["GET"])
def list_hardship_approval_tasks(hardship_id):
    user_id, role = require_roles("RecordkeeperAdmin", "PlanSponsor", "Auditor", "Participant")
    hr = get_hardship(hardship_id)
    check_participant_ownership(user_id, role, hr["participant_id"])
    items = sorted([t for t in db.approval_tasks.values()
                    if t["subject_type"] == "HARDSHIP" and t["subject_id"] == hr["id"]],
                   key=lambda r: r["step_order"])
    page, total, limit, offset = paginate(items)
    return success_list(page, total, limit, offset)


@bp.route("/hardship-requests/<hardship_id>/suspension-record", methods=["GET"])
def get_suspension_record(hardship_id):
    user_id, role = require_roles("RecordkeeperAdmin", "PlanSponsor", "Auditor", "Participant")
    hr = get_hardship(hardship_id)
    check_participant_ownership(user_id, role, hr["participant_id"])
    items = sorted([s for s in db.suspension_records.values()
                    if s["hardship_request_id"] == hr["id"]],
                   key=lambda r: r["created_at"])
    from middleware import parse_limit_offset
    limit, offset = parse_limit_offset()
    page = items[offset:offset + limit]
    return success_list(page, len(items), limit, offset)
