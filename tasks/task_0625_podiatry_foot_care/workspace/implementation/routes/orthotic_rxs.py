"""Orthotic prescriptions (PRD §3.7)."""

from flask import Blueprint, request

import db
import errors
import middleware as mw
import response as resp
import validate as v

bp = Blueprint("orthotic_rxs", __name__)

ALL_ROLES = {"PracticeAdmin", "Podiatrist", "BillingSpecialist", "FrontDesk", "PayerAgent"}


def _bad_state(msg="OrthoticRx not in a legal state for the requested transition."):
    return errors.ApiError(errors.ERR_RX_BAD_STATE, 409, msg)


@bp.route("/podiatry/orthotic-rxs", methods=["POST"])
def create_rx():
    _, role = mw.authenticate()
    mw.require_role(role, {"Podiatrist"})
    body = mw.get_body()
    with db.lock():
        encounter_id = v.as_str(body, "encounter_id", required=True)
        prior_authorization_id = v.as_str(body, "prior_authorization_id", required=True)
        encounter = db.encounters.get(encounter_id)
        if encounter is None:
            raise errors.fk_not_found("encounter_id references a non-existent encounter.")
        if prior_authorization_id not in db.prior_authorizations:
            raise errors.fk_not_found(
                "prior_authorization_id references a non-existent prior authorization.")
        l_code = v.as_str(body, "l_code", required=True)
        foot_side = v.as_enum(body, "foot_side",
                              {"LEFT", "RIGHT", "BILATERAL"}, required=True)
        entity = {
            "encounter_id": encounter_id,
            "patient_id": encounter["patient_id"],
            "prior_authorization_id": prior_authorization_id,
            "l_code": l_code,
            "foot_side": foot_side,
            "status": "DRAFT",
        }
        db.stamp_common(entity)
        db.orthotic_rxs[entity["id"]] = entity
        return resp.success(entity, 201)


@bp.route("/podiatry/orthotic-rxs", methods=["GET"])
def list_rxs():
    _, role = mw.authenticate()
    mw.require_role(role, ALL_ROLES)
    encounter_id = request.args.get("encounter_id")
    pa_id = request.args.get("prior_authorization_id")
    items = []
    for r in db.orthotic_rxs.values():
        if encounter_id is not None and r["encounter_id"] != encounter_id:
            continue
        if pa_id is not None and r["prior_authorization_id"] != pa_id:
            continue
        items.append(r)
    page, meta = mw.paginate(items)
    return resp.success(page, 200, pagination=meta)


@bp.route("/podiatry/orthotic-rxs/<rx_id>", methods=["GET"])
def get_rx(rx_id):
    _, role = mw.authenticate()
    mw.require_role(role, ALL_ROLES)
    entity = db.orthotic_rxs.get(rx_id)
    if entity is None:
        raise errors.not_found("Orthotic Rx not found.")
    return resp.success(entity, 200)


def _load(rx_id):
    entity = db.orthotic_rxs.get(rx_id)
    if entity is None:
        raise errors.not_found("Orthotic Rx not found.")
    return entity


@bp.route("/podiatry/orthotic-rxs/<rx_id>/submit-to-payer", methods=["POST"])
def submit_to_payer(rx_id):
    _, role = mw.authenticate()
    mw.require_role(role, {"Podiatrist"})
    with db.lock():
        rx = _load(rx_id)
        if rx["status"] != "DRAFT":
            raise _bad_state("submit-to-payer requires status DRAFT.")
        pa = db.prior_authorizations[rx["prior_authorization_id"]]
        if pa["service_category"] != "ORTHOTIC":
            raise errors.ApiError(errors.ERR_PA_CATEGORY_MISMATCH, 409,
                                  "Linked PA must be ORTHOTIC category.")
        rx["status"] = "PENDING_PA"
        db.touch(rx)
        return resp.success(rx, 200)


@bp.route("/podiatry/orthotic-rxs/<rx_id>/payer-decision", methods=["POST"])
def payer_decision(rx_id):
    _, role = mw.authenticate()
    mw.require_role(role, {"PayerAgent"})
    with db.lock():
        rx = _load(rx_id)
        body = mw.get_body()
        decision = v.as_enum(body, "decision", {"APPROVE", "REVISE"}, required=True)
        if rx["status"] != "PENDING_PA":
            raise _bad_state("payer-decision requires status PENDING_PA.")
        if decision == "APPROVE":
            pa = db.prior_authorizations[rx["prior_authorization_id"]]
            if pa["status"] != "APPROVED":
                raise errors.ApiError(errors.ERR_PA_NOT_DRAWABLE, 409,
                                      "Linked PA must be APPROVED to approve the Rx.")
            rx["status"] = "APPROVED"
        else:  # REVISE
            rx["status"] = "DRAFT"
        db.touch(rx)
        return resp.success(rx, 200)


@bp.route("/podiatry/orthotic-rxs/<rx_id>/cancel", methods=["POST"])
def cancel_rx(rx_id):
    _, role = mw.authenticate()
    mw.require_role(role, {"Podiatrist"})
    with db.lock():
        rx = _load(rx_id)
        if rx["status"] != "APPROVED":
            raise _bad_state("cancel requires status APPROVED.")
        # Blocked if any lab order for this Rx is SHIPPED or RECEIVED.
        for lo in db.lab_orders.values():
            if lo["orthotic_rx_id"] == rx_id and lo["status"] in ("SHIPPED", "RECEIVED"):
                raise _bad_state(
                    "cancel blocked by a SHIPPED or RECEIVED lab order.")
        rx["status"] = "CANCELLED"
        db.touch(rx)
        return resp.success(rx, 200)
