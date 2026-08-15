"""PortabilityAction endpoints."""

from flask import Blueprint, request

import db
import errors
from middleware import require_roles
from response import success_object
from routes.helpers import get_or_404
from routes.contracts import _terminate_contract_cascade

bp = Blueprint("portability_actions", __name__)


def serialize_portability_action(p):
    return {
        "id": p["id"],
        "family_id": p["family_id"],
        "destination_zip": p["destination_zip"],
        "action_type": p["action_type"],
        "status": p["status"],
        "created_at": p["created_at"],
        "updated_at": p["updated_at"],
        "version": p["version"],
    }


@bp.route("/hcv/portability-actions", methods=["POST"])
def create_action():
    require_roles("HousingAuthorityAdmin")
    body = request.get_json(force=True, silent=True) or {}
    family_id = body.get("family_id")
    destination_zip = body.get("destination_zip")
    action_type = body.get("action_type")
    get_or_404(db.voucher_families, family_id, "VoucherFamily")
    if action_type not in ("PORT_IN", "PORT_OUT"):
        raise errors.invalid_amount("action_type must be PORT_IN or PORT_OUT")
    rec = db.make_record({
        "family_id": family_id,
        "destination_zip": destination_zip,
        "action_type": action_type,
        "status": "INITIATED",
    })
    db.portability_actions[rec["id"]] = rec
    return success_object(serialize_portability_action(rec), 201)


@bp.route("/hcv/portability-actions/<pid>", methods=["GET"])
def get_action(pid):
    require_roles("HousingAuthorityAdmin")
    p = get_or_404(db.portability_actions, pid, "PortabilityAction")
    return success_object(serialize_portability_action(p))


@bp.route("/hcv/portability-actions/<pid>/accept-billing", methods=["POST"])
def accept_billing(pid):
    require_roles("HousingAuthorityAdmin")
    p = get_or_404(db.portability_actions, pid, "PortabilityAction")
    if p["status"] != "INITIATED":
        raise errors.invalid_state("PortabilityAction must be INITIATED")
    p["status"] = "BILLING_ACCEPTED"
    db.touch(p)
    return success_object(serialize_portability_action(p))


@bp.route("/hcv/portability-actions/<pid>/absorb", methods=["POST"])
def absorb(pid):
    require_roles("HousingAuthorityAdmin")
    p = get_or_404(db.portability_actions, pid, "PortabilityAction")
    if p["status"] != "BILLING_ACCEPTED":
        raise errors.invalid_state("PortabilityAction must be BILLING_ACCEPTED")
    p["status"] = "ABSORBED"
    db.touch(p)
    if p["action_type"] == "PORT_OUT":
        family = db.voucher_families.get(p["family_id"])
        if family is not None:
            # Find the linked ACTIVE contract for this family
            linked = None
            for c in db.hap_contracts.values():
                if c["family_id"] == family["id"] and c["status"] == "ACTIVE":
                    linked = c
                    break
            if family["status"] == "LEASED":
                family["status"] = "PORTED_OUT"
                db.touch(family)
            if linked is not None:
                _terminate_contract_cascade(linked, linked["status"])
    return success_object(serialize_portability_action(p))


@bp.route("/hcv/portability-actions/<pid>/terminate", methods=["POST"])
def terminate_action(pid):
    require_roles("HousingAuthorityAdmin")
    p = get_or_404(db.portability_actions, pid, "PortabilityAction")
    if p["status"] != "INITIATED":
        raise errors.invalid_state("PortabilityAction must be INITIATED")
    p["status"] = "TERMINATED"
    db.touch(p)
    return success_object(serialize_portability_action(p))
