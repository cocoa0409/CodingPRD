"""StateRegistration endpoints."""

from flask import Blueprint, request

import errors
from db import store
from middleware import (require_roles, get_json_body, require_string,
                        require_number, require_int, parse_pagination, paginate)
from response import success_object, success_list
from services.calculations import (stamp_new, touch, serialize, serialize_list,
                                   compute_registration_fee, iso_format,
                                   REGISTRATION_HOLD_THRESHOLD)
from decimal import Decimal

bp = Blueprint("state_registrations", __name__)

# Terminal for direct client transitions: APPROVED, EXPIRED, REVOKED.
# REJECTED is NOT terminal (resubmit loops back to SUBMITTED).
REG_CLIENT_TERMINAL = {"APPROVED", "EXPIRED", "REVOKED"}


@bp.route("/formulas/<id>/state-registrations", methods=["POST"])
def create_registration(id):
    require_roles("RegulatoryAffairs")
    formula = store.formulas.get(id)
    if formula is None:
        raise errors.not_found("Formula not found")
    if formula["status"] not in ("SUBSTANTIATED", "LOCKED"):
        raise errors.invalid_state(
            "Registrations may only be submitted for SUBSTANTIATED or LOCKED formulas")
    body = get_json_body()
    state_code = require_string(body, "state_code")
    if len(state_code) != 2 or not state_code.isalpha() or state_code.upper() != state_code:
        raise errors.invalid_request("state_code must be exactly 2 uppercase letters")
    label_revision_ref = require_int(body, "label_revision_ref")
    tonnage_tier = require_number(body, "tonnage_tier")

    for reg in store.state_registrations.values():
        if reg["formula_id"] == id and reg["state_code"] == state_code:
            raise errors.duplicate_key("state_code already registered within formula")

    fee = compute_registration_fee(state_code, tonnage_tier)
    now_iso = iso_format(store.now())
    reg = {
        "formula_id": id,
        "state_code": state_code,
        "label_revision_ref": label_revision_ref,
        "status": "SUBMITTED",
        "fee_cents": fee,
        "submitted_at": now_iso,
        "decided_at": None,
        "_decided_at_dt": None,
        "_tonnage_tier": tonnage_tier,
    }
    stamp_new(reg)
    store.state_registrations[reg["id"]] = reg
    return success_object(serialize(reg), 201)


def _get_registration(id):
    r = store.state_registrations.get(id)
    if r is None:
        raise errors.not_found("StateRegistration not found")
    return r


@bp.route("/state-registrations/<id>", methods=["GET"])
def get_registration(id):
    require_roles("PlatformAdmin", "RegulatoryAffairs", "StateRegulator", "QAApprover")
    reg = _get_registration(id)
    return success_object(serialize(reg), 200)


@bp.route("/formulas/<id>/state-registrations", methods=["GET"])
def list_registrations(id):
    require_roles("PlatformAdmin", "RegulatoryAffairs", "StateRegulator")
    formula = store.formulas.get(id)
    if formula is None:
        raise errors.not_found("Formula not found")
    limit, offset = parse_pagination()
    status_filter = request.args.get("status")
    items = [r for r in store.state_registrations.values() if r["formula_id"] == id]
    items.sort(key=lambda e: (e["_created_at_dt"], e["id"]))
    if status_filter is not None:
        items = [r for r in items if r["status"] == status_filter]
    page, total = paginate(items, limit, offset)
    return success_list(serialize_list(page), limit, offset, total, 200)


@bp.route("/state-registrations/<id>/accept-for-review", methods=["POST"])
def accept_for_review(id):
    require_roles("StateRegulator")
    reg = _get_registration(id)
    if reg["status"] in REG_CLIENT_TERMINAL:
        raise errors.already_terminal("Registration is in a terminal state")
    if reg["status"] != "SUBMITTED":
        raise errors.invalid_state("Only SUBMITTED registrations can be accepted for review")
    formula = store.formulas.get(reg["formula_id"])
    if formula is None:
        raise errors.not_found("Formula not found")
    if formula["status"] not in ("SUBSTANTIATED", "LOCKED"):
        raise errors.invalid_state("Formula must be SUBSTANTIATED or LOCKED")
    if formula.get("open_recall_flag"):
        raise errors.open_recall()
    reg["status"] = "UNDER_REVIEW"
    touch(reg, status_changed=True)
    return success_object(serialize(reg), 200)


@bp.route("/state-registrations/<id>/approve", methods=["POST"])
def approve_registration(id):
    require_roles("StateRegulator")
    reg = _get_registration(id)
    if reg["status"] in REG_CLIENT_TERMINAL:
        raise errors.already_terminal("Registration is in a terminal state")
    if reg["status"] != "UNDER_REVIEW":
        raise errors.invalid_state("Only UNDER_REVIEW registrations can be approved")
    body = get_json_body()
    if "expected_formula_version" not in body or body["expected_formula_version"] is None:
        raise errors.invalid_request("expected_formula_version is required")
    efv = body["expected_formula_version"]
    if isinstance(efv, bool) or not isinstance(efv, int):
        raise errors.invalid_request("expected_formula_version must be an integer")
    formula = store.formulas.get(reg["formula_id"])
    if formula is None:
        raise errors.not_found("Formula not found")
    if efv != formula["version"]:
        raise errors.stale_formula_version()
    if int(reg["label_revision_ref"]) != int(formula["revision_number"]):
        raise errors.label_revision_stale()
    brand = store.brand_owners.get(formula["brand_owner_id"])
    score = Decimal(str(brand.get("complaint_score", 0))) if brand else Decimal("0")
    if score >= REGISTRATION_HOLD_THRESHOLD:
        raise errors.complaint_score_hold()

    reg["status"] = "APPROVED"
    now = store.now()
    reg["decided_at"] = iso_format(now)
    reg["_decided_at_dt"] = now
    touch(reg, status_changed=True)
    return success_object(serialize(reg), 200)


@bp.route("/state-registrations/<id>/reject", methods=["POST"])
def reject_registration(id):
    require_roles("StateRegulator")
    reg = _get_registration(id)
    if reg["status"] in REG_CLIENT_TERMINAL:
        raise errors.already_terminal("Registration is in a terminal state")
    if reg["status"] != "UNDER_REVIEW":
        raise errors.invalid_state("Only UNDER_REVIEW registrations can be rejected")
    reg["status"] = "REJECTED"
    now = store.now()
    reg["decided_at"] = iso_format(now)
    reg["_decided_at_dt"] = now
    touch(reg, status_changed=True)
    return success_object(serialize(reg), 200)


@bp.route("/state-registrations/<id>/resubmit", methods=["POST"])
def resubmit_registration(id):
    require_roles("RegulatoryAffairs")
    reg = _get_registration(id)
    if reg["status"] in REG_CLIENT_TERMINAL:
        raise errors.already_terminal("Registration is in a terminal state")
    if reg["status"] != "REJECTED":
        raise errors.invalid_state("Only REJECTED registrations can be resubmitted")
    body = get_json_body()
    tonnage_tier = require_number(body, "tonnage_tier")
    formula = store.formulas.get(reg["formula_id"])
    if formula is None:
        raise errors.not_found("Formula not found")
    if formula["status"] not in ("SUBSTANTIATED", "LOCKED"):
        raise errors.invalid_state("Formula must be SUBSTANTIATED or LOCKED")
    reg["fee_cents"] = compute_registration_fee(reg["state_code"], tonnage_tier)
    reg["_tonnage_tier"] = tonnage_tier
    reg["status"] = "SUBMITTED"
    touch(reg, status_changed=True)
    return success_object(serialize(reg), 200)
