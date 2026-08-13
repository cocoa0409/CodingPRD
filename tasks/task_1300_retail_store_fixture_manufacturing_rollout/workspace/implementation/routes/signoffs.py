"""InstallSignoff endpoints."""

from __future__ import annotations

from flask import Blueprint

import db
from errors import (
    raise_err,
    ERR_DELIVERY_NOT_FOUND,
    ERR_DELIVERY_INVALID_STATE,
    ERR_SIGNOFF_NOT_FOUND,
    ERR_SIGNOFF_INVALID_STATE,
    ERR_SIGNOFF_SELF_APPROVAL,
    ERR_SIGNOFF_ALREADY_PENDING,
    ERR_PHOTO_EVIDENCE_REQUIRED,
)
from middleware import require_roles
from response import success_object, success_list
from services.calculations import (
    attic_initial_quantity,
    attic_unit_cost,
    reorder_required,
)
from services.serializers import serialize, serialize_list
from util import (
    apply_filters,
    get_json_body,
    optional_field,
    paginate,
    parse_pagination,
    require_string,
    sort_by_created_at,
)

bp = Blueprint("signoffs", __name__)


def _get_signoff_or_404(signoff_id: str) -> dict:
    signoff = db.signoffs.get(signoff_id)
    if signoff is None:
        raise_err(ERR_SIGNOFF_NOT_FOUND, "InstallSignoff id does not exist")
    return signoff


def _validate_photo_urls(body: dict) -> list:
    photo_urls = body.get("photo_urls")
    if not isinstance(photo_urls, list) or len(photo_urls) == 0:
        raise_err(ERR_PHOTO_EVIDENCE_REQUIRED, "photo_urls must contain at least one entry")
    return photo_urls


@bp.route("/install-signoffs", methods=["POST"])
@require_roles("InstallCrewLead")
def create_signoff(_user_id: str, _role: str):
    body = get_json_body()
    delivery_id = require_string(body, "delivery_id")
    photo_urls = _validate_photo_urls(body)
    notes = optional_field(body, "notes", None)

    delivery = db.deliveries.get(delivery_id)
    if delivery is None:
        raise_err(ERR_DELIVERY_NOT_FOUND, "InstallDelivery id does not exist")
    if delivery["status"] != "DELIVERED":
        raise_err(ERR_DELIVERY_INVALID_STATE, "signoff creation requires delivery DELIVERED")

    # At most one pending signoff per delivery
    for existing in db.signoffs.values():
        if existing["delivery_id"] == delivery_id and existing["status"] == "SUBMITTED":
            raise_err(ERR_SIGNOFF_ALREADY_PENDING, "A SUBMITTED signoff already exists for this delivery")

    signoff = {
        "delivery_id": delivery_id,
        "photo_urls": photo_urls,
        "notes": notes,
        "submission_count": 1,
        "submitted_by_user_id": _user_id,
        "reviewed_by_user_id": None,
        "rejection_reason": None,
        "status": "SUBMITTED",
    }
    db.stamp_new(signoff)
    db.signoffs[signoff["id"]] = signoff
    return success_object(serialize(signoff), 201)


@bp.route("/install-signoffs", methods=["GET"])
@require_roles("Any")
def list_signoffs(_user_id: str, _role: str):
    limit, offset = parse_pagination()
    items = sort_by_created_at(list(db.signoffs.values()))
    items = apply_filters(items, ["delivery_id", "status"])
    page, total = paginate(items, limit, offset)
    return success_list(serialize_list(page), limit, offset, total)


@bp.route("/install-signoffs/<signoff_id>", methods=["GET"])
@require_roles("Any")
def get_signoff(signoff_id: str, _user_id: str, _role: str):
    signoff = _get_signoff_or_404(signoff_id)
    return success_object(serialize(signoff))


@bp.route("/install-signoffs/<signoff_id>/approve", methods=["POST"])
@require_roles("StoreManager")
def approve_signoff(signoff_id: str, _user_id: str, _role: str):
    signoff = _get_signoff_or_404(signoff_id)
    if signoff["status"] != "SUBMITTED":
        raise_err(ERR_SIGNOFF_INVALID_STATE, "approve requires signoff SUBMITTED")
    if signoff["submitted_by_user_id"] is not None and _user_id == signoff["submitted_by_user_id"]:
        raise_err(ERR_SIGNOFF_SELF_APPROVAL, "Approver must differ from the most recent submitter")

    signoff["reviewed_by_user_id"] = _user_id
    signoff["status"] = "APPROVED"
    db.touch(signoff)

    # Cascade hop 2: delivery -> COMPLETE
    delivery = db.deliveries.get(signoff["delivery_id"])
    if delivery is not None:
        delivery["status"] = "COMPLETE"
        db.touch(delivery)

        # Cascade hop 3: kit -> FULFILLED; program.fulfilled_kit_count += 1
        kit = db.kits.get(delivery["kit_id"])
        if kit is not None:
            kit["status"] = "FULFILLED"
            db.touch(kit)

            program = db.programs.get(kit["program_id"])
            if program is not None:
                program["fulfilled_kit_count"] += 1
                db.touch(program)

            # Cascade hop 4: auto-create the attic stock ledger (one per kit)
            existing = next(
                (l for l in db.ledgers.values() if l["kit_id"] == kit["id"]),
                None,
            )
            if existing is None:
                qty = attic_initial_quantity(kit["total_components"])
                unit_cost = attic_unit_cost(kit["kit_total_cost_cents"], kit["total_components"])
                ledger = {
                    "kit_id": kit["id"],
                    "store_code": kit["store_code"],
                    "quantity_on_hand": qty,
                    "reorder_point": 2,
                    "reorder_required": reorder_required(qty, 2),
                    "unit_cost_cents": unit_cost,
                    "disposition_type": None,
                    "recovery_value_cents": None,
                    "status": "ACTIVE",
                }
                db.stamp_new(ledger)
                db.ledgers[ledger["id"]] = ledger

    return success_object(serialize(signoff))


@bp.route("/install-signoffs/<signoff_id>/reject", methods=["POST"])
@require_roles("StoreManager")
def reject_signoff(signoff_id: str, _user_id: str, _role: str):
    signoff = _get_signoff_or_404(signoff_id)
    if signoff["status"] != "SUBMITTED":
        raise_err(ERR_SIGNOFF_INVALID_STATE, "reject requires signoff SUBMITTED")
    body = get_json_body()
    reason = body.get("reason")
    if not isinstance(reason, str) or reason == "":
        from errors import ERR_INVALID_REQUEST
        raise_err(ERR_INVALID_REQUEST, "reason is required")
    signoff["reviewed_by_user_id"] = _user_id
    signoff["rejection_reason"] = reason
    signoff["status"] = "REJECTED"
    db.touch(signoff)
    return success_object(serialize(signoff))


@bp.route("/install-signoffs/<signoff_id>/resubmit", methods=["POST"])
@require_roles("InstallCrewLead")
def resubmit_signoff(signoff_id: str, _user_id: str, _role: str):
    signoff = _get_signoff_or_404(signoff_id)
    if signoff["status"] != "REJECTED":
        raise_err(ERR_SIGNOFF_INVALID_STATE, "resubmit requires signoff REJECTED")
    body = get_json_body()
    photo_urls = _validate_photo_urls(body)
    notes = optional_field(body, "notes", signoff.get("notes"))

    signoff["photo_urls"] = photo_urls
    if notes is not None:
        signoff["notes"] = notes
    signoff["rejection_reason"] = None
    signoff["submitted_by_user_id"] = _user_id
    signoff["submission_count"] += 1
    signoff["status"] = "SUBMITTED"
    db.touch(signoff)
    return success_object(serialize(signoff))
