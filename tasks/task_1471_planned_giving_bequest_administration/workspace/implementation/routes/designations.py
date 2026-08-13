"""Beneficiary designations (PRD 3.4)."""
from flask import Blueprint, g

import store
from domain import SLOTS, lookup, matches, paginate, sort_created, view
from envelope import success
from errors import ApiError
from security import ALL_ROLES, require_roles
from store import base_fields, touch
from validate import get_body, validate_body

bp = Blueprint("designations", __name__)

ACTIONS = ("SUBMIT", "VERIFY", "REJECT", "REVOKE")


def _slot_occupied(agreement_id, slot, exclude_id=None):
    return any(
        d["gift_agreement_id"] == agreement_id
        and d["slot"] == slot
        and d["status"] == "SUBMITTED"
        and d["id"] != exclude_id
        for d in store.designations.values()
    )


@bp.post("/giving/beneficiary-designations")
@require_roles("GiftOfficer")
def create_designation():
    body = get_body()
    validate_body(
        body,
        {
            "gift_agreement_id": ("str", True, None),
            "slot": ("str", True, SLOTS),
            "beneficiary_name": ("str", True, None),
            "document_received": ("bool", False, None),
        },
    )
    agreement = lookup(store.agreements, body["gift_agreement_id"], "GiftAgreement")
    # slot occupancy: at most one SUBMITTED per (agreement, slot)
    if _slot_occupied(agreement["id"], body["slot"]):
        raise ApiError(
            "ERR_SLOT_OCCUPIED",
            409,
            "A SUBMITTED designation already occupies this slot",
        )
    designation = base_fields()
    designation.update(
        {
            "gift_agreement_id": agreement["id"],
            "slot": body["slot"],
            "beneficiary_name": body["beneficiary_name"],
            "document_received": body.get("document_received", False),
            "status": "DRAFT",
            "rejection_reason": None,
        }
    )
    store.designations[designation["id"]] = designation
    return success(view(designation), 201)


@bp.get("/giving/beneficiary-designations")
@require_roles(*ALL_ROLES)
def list_designations():
    items = [
        d
        for d in sort_created(store.designations.values())
        if matches(d, {"gift_agreement_id": None, "slot": None, "status": None})
    ]
    page, meta = paginate(items)
    return success([view(d) for d in page], 200, meta)


@bp.get("/giving/beneficiary-designations/<designation_id>")
@require_roles(*ALL_ROLES)
def get_designation(designation_id):
    return success(
        view(lookup(store.designations, designation_id, "BeneficiaryDesignation")),
        200,
    )


@bp.post("/giving/beneficiary-designations/<designation_id>/transition")
@require_roles("GiftOfficer", "GiftAdministrator")
def designation_transition(designation_id):
    body = get_body()
    validate_body(
        body,
        {
            "action": ("str", True, ACTIONS),
            "rejection_reason": ("str", False, None),
        },
    )
    action = body["action"]
    # per-action roles: SUBMIT is GiftOfficer; VERIFY/REJECT/REVOKE are GiftAdministrator
    required = "GiftOfficer" if action == "SUBMIT" else "GiftAdministrator"
    if g.role != required:
        raise ApiError(
            "ERR_UNAUTHORIZED", 403, "Action %s requires %s" % (action, required)
        )
    designation = lookup(store.designations, designation_id, "BeneficiaryDesignation")
    status = designation["status"]

    if action == "SUBMIT":
        if status not in ("DRAFT", "REJECTED"):
            raise ApiError("ERR_INVALID_STATE", 409, "Cannot SUBMIT from %s" % status)
        if _slot_occupied(
            designation["gift_agreement_id"], designation["slot"], exclude_id=designation["id"]
        ):
            raise ApiError(
                "ERR_SLOT_OCCUPIED",
                409,
                "A SUBMITTED designation already occupies this slot",
            )
        designation["status"] = "SUBMITTED"
        designation["rejection_reason"] = None  # revise-and-resubmit clears it
    elif action == "VERIFY":
        if status != "SUBMITTED":
            raise ApiError("ERR_INVALID_STATE", 409, "Cannot VERIFY from %s" % status)
        if not designation["document_received"]:
            raise ApiError(
                "ERR_DOCUMENT_NOT_RECEIVED",
                409,
                "Designation document has not been received",
            )
        # auto-supersede any other VERIFIED designation on the same (agreement, slot)
        for other in store.designations.values():
            if (
                other["id"] != designation["id"]
                and other["gift_agreement_id"] == designation["gift_agreement_id"]
                and other["slot"] == designation["slot"]
                and other["status"] == "VERIFIED"
            ):
                other["status"] = "SUPERSEDED"
                touch(other)
        designation["status"] = "VERIFIED"
    elif action == "REJECT":
        if status != "SUBMITTED":
            raise ApiError("ERR_INVALID_STATE", 409, "Cannot REJECT from %s" % status)
        designation["status"] = "REJECTED"
        designation["rejection_reason"] = body.get("rejection_reason")
    else:  # REVOKE
        if status != "VERIFIED":
            raise ApiError("ERR_INVALID_STATE", 409, "Cannot REVOKE from %s" % status)
        agreement = store.agreements.get(designation["gift_agreement_id"])
        if agreement is None or agreement["status"] not in ("DRAFT", "EXECUTED"):
            raise ApiError(
                "ERR_INVALID_STATE",
                409,
                "Designation paperwork is frozen once the agreement is funded",
            )
        designation["status"] = "REVOKED"

    touch(designation)
    return success(view(designation), 200)
