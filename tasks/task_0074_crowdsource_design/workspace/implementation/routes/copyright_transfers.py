"""Copyright transfer routes: create, issue, sign, register, void, get."""
from flask import Blueprint

from clock import format_iso, get_now
from common import check_version, get_json_body, stamp_new, stamp_update
from db import db
from errors import api_error
from middleware import require_roles
from response import success
from services.audit import emit_audit


bp = Blueprint("copyright_transfers", __name__)


def _validate_scope(scope, usage_rights):
    if scope not in {"FULL", "LIMITED"}:
        raise api_error("ERR_VALIDATION", "scope must be FULL or LIMITED")
    if not isinstance(usage_rights, list):
        raise api_error("ERR_VALIDATION", "usage_rights must be a list")
    if scope == "LIMITED" and not usage_rights:
        raise api_error("ERR_TRANSFER_SCOPE_INVALID", "scope=LIMITED requires usage_rights non-empty")
    if scope == "FULL" and len(usage_rights) > 0:
        raise api_error("ERR_TRANSFER_SCOPE_INVALID", "scope=FULL requires usage_rights empty")


def _has_upheld_dispute(submission_id, dispute_types):
    return any(
        d.get("subject_ref_kind") == "SUBMISSION"
        and d.get("subject_ref_id") == submission_id
        and d.get("status") == "RESOLVED_UPHELD"
        and d.get("dispute_type") in dispute_types
        for d in db.disputes.values()
    )


@bp.route("/copyright-transfers", methods=["POST"])
def create_transfer():
    require_roles({"PlatformOps"})
    body = get_json_body()
    project_id = body.get("project_id")
    submission_id = body.get("submission_id")
    scope = body.get("scope")
    usage_rights = body.get("usage_rights", []) or []
    if project_id not in db.projects:
        raise api_error("ERR_FK_NOT_FOUND", "project_id not found")
    submission = db.submissions.get(submission_id)
    if not submission:
        raise api_error("ERR_FK_NOT_FOUND", "submission_id not found")
    if submission.get("project_id") != project_id:
        raise api_error("ERR_FK_NOT_FOUND", "submission does not belong to project")
    if submission.get("status") not in {"WINNER", "RUNNER_UP"}:
        raise api_error("ERR_INVALID_STATE", "submission must be WINNER or RUNNER_UP")
    _validate_scope(scope, usage_rights)
    # PRD §3.8: "A PlatformOps operator may also create a transfer
    # manually for a winning or runner-up submission *when the
    # auto-draft is missing*." If an auto-DRAFTED transfer already
    # exists for this (project, submission), return that one rather
    # than creating a duplicate — the manual-create path is intended
    # to be the recovery path for the "missing" case only.
    for t in db.copyright_transfers.values():
        if t.get("project_id") == project_id and t.get("submission_id") == submission_id:
            return success(t, status=201)
    project = db.projects[project_id]
    transfer = stamp_new({
        "project_id": project_id,
        "submission_id": submission_id,
        "scope": scope,
        "usage_rights": list(usage_rights),
        "signers": [
            {"party_kind": "CLIENT", "party_id": project["client_id"], "signed_at": None},
            {"party_kind": "DESIGNER", "party_id": submission["designer_id"], "signed_at": None},
            {"party_kind": "PLATFORM_NOTARY", "party_id": None, "signed_at": None},
        ],
        "status": "DRAFTED",
        "registration_ref": None,
        "registered_at": None,
    })
    db.copyright_transfers[transfer["id"]] = transfer
    return success(transfer, status=201)


@bp.route("/copyright-transfers/<transfer_id>/issue-for-signing", methods=["POST"])
def issue_for_signing(transfer_id):
    user_id, _ = require_roles({"PlatformOps"})
    transfer = db.copyright_transfers.get(transfer_id)
    if not transfer:
        raise api_error("ERR_NOT_FOUND", "transfer not found")
    body = get_json_body()
    check_version(transfer, body)
    if transfer.get("status") != "DRAFTED":
        raise api_error("ERR_INVALID_STATE", "only DRAFTED transfers can be issued for signing")
    submission = db.submissions.get(transfer.get("submission_id"))
    if not submission or submission.get("status") not in {"WINNER", "RUNNER_UP"}:
        raise api_error("ERR_INVALID_STATE", "submission must be WINNER or RUNNER_UP to issue")
    _validate_scope(transfer["scope"], transfer.get("usage_rights", []))
    transfer["status"] = "PENDING_SIGNATURES"
    stamp_update(transfer)
    emit_audit(
        "COPYRIGHT_DRAFTED",
        "PLATFORM",
        user_id,
        "COPYRIGHT_TRANSFER",
        transfer["id"],
        {"previous_status": "DRAFTED", "new_status": "PENDING_SIGNATURES"},
    )
    return success(transfer)


@bp.route("/copyright-transfers/<transfer_id>/sign", methods=["POST"])
def sign_transfer(transfer_id):
    user_id, role = require_roles({"Client", "Designer", "PlatformOps"})
    transfer = db.copyright_transfers.get(transfer_id)
    if not transfer:
        raise api_error("ERR_NOT_FOUND", "transfer not found")
    body = get_json_body()
    party_kind = body.get("signer_party_kind")
    if party_kind not in {"CLIENT", "DESIGNER", "PLATFORM_NOTARY"}:
        raise api_error("ERR_VALIDATION", "signer_party_kind must be CLIENT, DESIGNER, or PLATFORM_NOTARY")
    check_version(transfer, body)
    if transfer.get("status") != "PENDING_SIGNATURES":
        raise api_error("ERR_INVALID_STATE", "transfer must be PENDING_SIGNATURES")

    # Determine next unsigned slot in order
    signers = transfer["signers"]
    next_slot = None
    next_idx = None
    for i, slot in enumerate(signers):
        if slot.get("signed_at") is None:
            next_slot = slot
            next_idx = i
            break
    if next_slot is None:
        raise api_error("ERR_INVALID_STATE", "all signers have already signed")
    if next_slot["party_kind"] != party_kind:
        raise api_error("ERR_SIGNATURE_OUT_OF_ORDER",
                        f"next expected signer is {next_slot['party_kind']}, not {party_kind}")

    # Identity / role match per PRD §3.8
    submission = db.submissions.get(transfer.get("submission_id"))
    project = db.projects.get(transfer.get("project_id"))
    if party_kind == "CLIENT":
        if role != "Client":
            raise api_error("ERR_FORBIDDEN", "CLIENT slot must be signed by Client role")
        if not project or user_id != project["client_id"]:
            raise api_error("ERR_FORBIDDEN", "CLIENT slot must be signed by the project's client")
    elif party_kind == "DESIGNER":
        if role != "Designer":
            raise api_error("ERR_FORBIDDEN", "DESIGNER slot must be signed by Designer role")
        if not submission or user_id != submission["designer_id"]:
            raise api_error("ERR_FORBIDDEN", "DESIGNER slot must be signed by the linked submission's designer")
    else:  # PLATFORM_NOTARY
        if role != "PlatformOps":
            raise api_error("ERR_FORBIDDEN", "PLATFORM_NOTARY slot must be signed by PlatformOps")

    next_slot["signed_at"] = format_iso(get_now())
    if party_kind == "PLATFORM_NOTARY" and next_slot.get("party_id") is None:
        next_slot["party_id"] = user_id
    emit_audit(
        "COPYRIGHT_SIGNED",
        "CLIENT" if party_kind == "CLIENT" else ("DESIGNER" if party_kind == "DESIGNER" else "PLATFORM"),
        user_id,
        "COPYRIGHT_TRANSFER",
        transfer["id"],
        {"slot": next_idx, "party_kind": party_kind},
    )
    # If last slot, flip to ALL_SIGNED
    if all(s.get("signed_at") is not None for s in signers):
        transfer["status"] = "ALL_SIGNED"
    stamp_update(transfer)
    return success(transfer)


@bp.route("/copyright-transfers/<transfer_id>/register", methods=["POST"])
def register_transfer(transfer_id):
    require_roles({"PlatformOps"})
    transfer = db.copyright_transfers.get(transfer_id)
    if not transfer:
        raise api_error("ERR_NOT_FOUND", "transfer not found")
    body = get_json_body()
    check_version(transfer, body)
    if transfer.get("status") != "ALL_SIGNED":
        raise api_error("ERR_INVALID_STATE", "transfer must be ALL_SIGNED to register")
    transfer["status"] = "REGISTERING"
    stamp_update(transfer)
    return success(transfer)


@bp.route("/copyright-transfers/<transfer_id>/void", methods=["POST"])
def void_transfer(transfer_id):
    user_id, _ = require_roles({"PlatformOps"})
    transfer = db.copyright_transfers.get(transfer_id)
    if not transfer:
        raise api_error("ERR_NOT_FOUND", "transfer not found")
    body = get_json_body()
    check_version(transfer, body)
    dispute_id = body.get("dispute_id")
    dispute = db.disputes.get(dispute_id) if dispute_id else None
    if not dispute:
        raise api_error("ERR_FK_NOT_FOUND", "dispute_id required and must reference an existing dispute")
    if dispute.get("status") != "RESOLVED_UPHELD":
        raise api_error("ERR_INVALID_STATE", "void requires an UPHELD dispute")

    status = transfer.get("status")
    submission_id = transfer.get("submission_id")
    if status == "PENDING_SIGNATURES":
        if dispute.get("dispute_type") not in {"COPYRIGHT", "PLAGIARISM"}:
            raise api_error("ERR_INVALID_STATE", "dispute type must be COPYRIGHT or PLAGIARISM")
        if dispute.get("subject_ref_kind") != "SUBMISSION" or dispute.get("subject_ref_id") != submission_id:
            raise api_error("ERR_INVALID_STATE", "dispute must target this transfer's submission")
    elif status == "ALL_SIGNED":
        if dispute.get("dispute_type") != "COPYRIGHT":
            raise api_error("ERR_INVALID_STATE", "ALL_SIGNED void requires a COPYRIGHT dispute")
        if transfer.get("registration_ref") is not None:
            raise api_error("ERR_INVALID_STATE", "registration_ref is set; cannot void from ALL_SIGNED")
        if dispute.get("subject_ref_kind") != "SUBMISSION" or dispute.get("subject_ref_id") != submission_id:
            raise api_error("ERR_INVALID_STATE", "dispute must target this transfer's submission")
    elif status == "REGISTERED":
        if dispute.get("dispute_type") not in {"COPYRIGHT", "PLAGIARISM"}:
            raise api_error("ERR_INVALID_STATE", "dispute type must be COPYRIGHT or PLAGIARISM")
        if dispute.get("subject_ref_kind") != "SUBMISSION" or dispute.get("subject_ref_id") != submission_id:
            raise api_error("ERR_INVALID_STATE", "dispute must target this transfer's submission")
    else:
        raise api_error("ERR_INVALID_STATE", f"transfer cannot be voided from status {status}")

    transfer["status"] = "VOIDED"
    stamp_update(transfer)
    emit_audit(
        "COPYRIGHT_VOIDED",
        "PLATFORM",
        user_id,
        "COPYRIGHT_TRANSFER",
        transfer["id"],
        {"from": status, "dispute_id": dispute_id},
    )

    # Cascade: linked PrizePayment -> REVERSED
    for p in db.prize_payments.values():
        if (p.get("project_id") == transfer["project_id"]
                and p.get("designer_id") == db.submissions.get(submission_id, {}).get("designer_id")):
            # Match payment by submission's tier
            sub = db.submissions.get(submission_id)
            if sub and p.get("prize_tier_id") == sub.get("prize_tier_id"):
                if p.get("status") in {"SCHEDULED", "PAYING", "PAID"}:
                    prior_status = p["status"]
                    p["status"] = "REVERSED"
                    stamp_update(p)
                    emit_audit(
                        "PRIZE_PAID",
                        "SYSTEM",
                        "system",
                        "PRIZE_PAYMENT",
                        p["id"],
                        {"reversal_note": f"voided from {prior_status} due to upheld dispute"},
                    )
                    # also free up idempotency_key
                    key = p.get("idempotency_key")
                    if key and db.payment_idempotency_index.get(key) == p["id"]:
                        del db.payment_idempotency_index[key]
                break

    return success(transfer)


@bp.route("/copyright-transfers/<transfer_id>", methods=["GET"])
def get_transfer(transfer_id):
    user_id, role = require_roles({"PlatformOps", "Client", "Designer"})
    transfer = db.copyright_transfers.get(transfer_id)
    if not transfer:
        raise api_error("ERR_NOT_FOUND", "transfer not found")
    project = db.projects.get(transfer.get("project_id"))
    submission = db.submissions.get(transfer.get("submission_id"))
    if role == "Client" and (not project or project.get("client_id") != user_id):
        raise api_error("ERR_FORBIDDEN", "Clients may only see transfers for their own projects")
    if role == "Designer" and (not submission or submission.get("designer_id") != user_id):
        raise api_error("ERR_FORBIDDEN", "Designers may only see transfers for their own submissions")
    return success(transfer)
