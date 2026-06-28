"""Recall scheduling (PRD §3.10)."""

from flask import Blueprint, request

import calculations as calc
import db
import errors
import middleware as mw
import response as resp
import validate as v

bp = Blueprint("recalls", __name__)

ALL_ROLES = {"PracticeAdmin", "Podiatrist", "BillingSpecialist", "FrontDesk", "PayerAgent"}


def _bad_state(msg="RecallSchedule not in a legal state for the requested transition."):
    return errors.ApiError(errors.ERR_RECALL_BAD_STATE, 409, msg)


@bp.route("/podiatry/recalls", methods=["POST"])
def create_recall():
    _, role = mw.authenticate()
    mw.require_role(role, {"FrontDesk"})
    body = mw.get_body()
    with db.lock():
        patient_id = v.as_str(body, "patient_id", required=True)
        patient = db.patients.get(patient_id)
        if patient is None:
            raise errors.fk_not_found("patient_id references a non-existent patient.")
        anchor_date = v.as_date(body, "anchor_date", required=True)
        # interval snapshotted from the patient's current risk category (PRD §3.10).
        category = patient["diabetic_foot_risk_category"]
        interval_days = calc.recall_interval_days(category)
        due_date = calc.add_days(anchor_date, interval_days)
        entity = {
            "patient_id": patient_id,
            "anchor_date": anchor_date,
            "interval_days": interval_days,
            "due_date": due_date,
            "status": "PENDING",
        }
        db.stamp_common(entity)
        db.recalls[entity["id"]] = entity
        return resp.success(entity, 201)


@bp.route("/podiatry/recalls", methods=["GET"])
def list_recalls():
    _, role = mw.authenticate()
    mw.require_role(role, ALL_ROLES)
    patient_id = request.args.get("patient_id")
    items = [r for r in db.recalls.values()
             if patient_id is None or r["patient_id"] == patient_id]
    page, meta = mw.paginate(items)
    return resp.success(page, 200, pagination=meta)


@bp.route("/podiatry/recalls/<recall_id>", methods=["GET"])
def get_recall(recall_id):
    _, role = mw.authenticate()
    mw.require_role(role, ALL_ROLES)
    entity = db.recalls.get(recall_id)
    if entity is None:
        raise errors.not_found("Recall not found.")
    return resp.success(entity, 200)


def _load(recall_id):
    entity = db.recalls.get(recall_id)
    if entity is None:
        raise errors.not_found("Recall not found.")
    return entity


@bp.route("/podiatry/recalls/<recall_id>/complete", methods=["POST"])
def complete_recall(recall_id):
    _, role = mw.authenticate()
    mw.require_role(role, {"FrontDesk"})
    with db.lock():
        r = _load(recall_id)
        if r["status"] != "PENDING":
            raise _bad_state("complete requires status PENDING.")
        r["status"] = "COMPLETED"
        db.touch(r)
        return resp.success(r, 200)


@bp.route("/podiatry/recalls/<recall_id>/cancel", methods=["POST"])
def cancel_recall(recall_id):
    _, role = mw.authenticate()
    mw.require_role(role, {"FrontDesk"})
    with db.lock():
        r = _load(recall_id)
        if r["status"] != "PENDING":
            raise _bad_state("cancel requires status PENDING.")
        r["status"] = "CANCELLED"
        db.touch(r)
        return resp.success(r, 200)
