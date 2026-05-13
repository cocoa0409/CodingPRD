"""Prize payment routes: dispatch, retry, get, list."""
from flask import Blueprint, request

from common import check_version, get_json_body, paginate, stamp_update
from db import db
from errors import api_error
from middleware import require_roles
from response import success


bp = Blueprint("prize_payments", __name__)


def _linked_transfer(payment):
    """Find the CopyrightTransfer linked to this payment by (project_id, submission_id)
    inferred via the prize_tier_id -> winner_submission_id mapping."""
    tier = db.prize_tiers.get(payment.get("prize_tier_id"))
    if not tier:
        return None
    submission_id = tier.get("winner_submission_id")
    if not submission_id:
        return None
    for t in db.copyright_transfers.values():
        if t.get("project_id") == payment.get("project_id") and t.get("submission_id") == submission_id:
            return t
    return None


@bp.route("/prize-payments/<prize_payment_id>/dispatch", methods=["POST"])
def dispatch_payment(prize_payment_id):
    require_roles({"PlatformOps"})
    payment = db.prize_payments.get(prize_payment_id)
    if not payment:
        raise api_error("ERR_NOT_FOUND", "prize payment not found")
    body = get_json_body()
    check_version(payment, body)
    idem = body.get("idempotency_key")
    if not isinstance(idem, str) or not idem:
        raise api_error("ERR_VALIDATION", "idempotency_key required")
    if payment.get("status") != "SCHEDULED":
        raise api_error("ERR_INVALID_STATE", "payment must be SCHEDULED to dispatch")

    # Linked transfer must be REGISTERED
    transfer = _linked_transfer(payment)
    if not transfer or transfer.get("status") != "REGISTERED":
        raise api_error("ERR_COPYRIGHT_NOT_REGISTERED",
                        "linked CopyrightTransfer must be REGISTERED before dispatch")

    # Idempotency check per (project_id, prize_tier_id)
    existing_id = db.payment_idempotency_index.get(idem)
    if existing_id:
        existing = db.prize_payments.get(existing_id)
        if (existing and existing.get("project_id") == payment.get("project_id")
                and existing.get("prize_tier_id") == payment.get("prize_tier_id")
                and existing.get("status") in {"PAYING", "PAID"}):
            raise api_error(
                "ERR_DUPLICATE_IDEMPOTENCY_KEY",
                f"idempotency_key already in use for this (project, tier); existing payment {existing_id}",
            )

    payment["idempotency_key"] = idem
    payment["status"] = "PAYING"
    db.payment_idempotency_index[idem] = payment["id"]
    stamp_update(payment)
    return success(payment)


@bp.route("/prize-payments/<prize_payment_id>/retry", methods=["POST"])
def retry_payment(prize_payment_id):
    require_roles({"PlatformOps"})
    payment = db.prize_payments.get(prize_payment_id)
    if not payment:
        raise api_error("ERR_NOT_FOUND", "prize payment not found")
    body = get_json_body()
    check_version(payment, body)
    if payment.get("status") != "FAILED":
        raise api_error("ERR_INVALID_STATE", "only FAILED payments can be retried")
    payment["status"] = "SCHEDULED"
    # Free idempotency_key from the previous attempt
    key = payment.get("idempotency_key")
    if key and db.payment_idempotency_index.get(key) == payment["id"]:
        del db.payment_idempotency_index[key]
    payment["idempotency_key"] = None
    stamp_update(payment)
    return success(payment)


@bp.route("/prize-payments/<prize_payment_id>", methods=["GET"])
def get_payment(prize_payment_id):
    user_id, role = require_roles({"PlatformOps", "Designer"})
    payment = db.prize_payments.get(prize_payment_id)
    if not payment:
        raise api_error("ERR_NOT_FOUND", "prize payment not found")
    if role == "Designer" and payment.get("designer_id") != user_id:
        raise api_error("ERR_FORBIDDEN", "Designers can only fetch their own payments")
    return success(payment)


@bp.route("/prize-payments", methods=["GET"])
def list_payments():
    user_id, role = require_roles({"PlatformOps", "Designer"})
    items = list(db.prize_payments.values())
    if role == "Designer":
        items = [p for p in items if p.get("designer_id") == user_id]
    project_id = request.args.get("project_id")
    designer_id = request.args.get("designer_id")
    status = request.args.get("status")
    if project_id:
        items = [p for p in items if p.get("project_id") == project_id]
    if designer_id:
        items = [p for p in items if p.get("designer_id") == designer_id]
    if status:
        items = [p for p in items if p.get("status") == status]
    page, meta = paginate(items)
    return success(page, response_type="array", pagination=meta)
