"""Evaluation endpoints."""

from flask import Blueprint, request

import errors
import validation as v
from db import store, new_entity, touch
from middleware import require_roles, ALL_ROLES
from response import success_object, success_list

bp = Blueprint("evaluations", __name__)

SCORE_FIELDS = ("acuity_score", "contrast_score", "field_loss_pct")
CATEGORIES = {"MAGNIFIER", "CCTV", "SCREEN_READER"}


def _opt_score(body, field):
    return v.opt_int(body, field, default=None, min_v=0, max_v=100)


@bp.post("/api/evaluations")
def create_evaluation():
    actor = require_roles(["VisionSpecialist"])
    body = v.require_body(request.get_json(silent=True))
    v.reject_unknown_fields(body, {
        "client_id", "referral_id", "expected_client_version",
        "acuity_score", "contrast_score", "field_loss_pct", "recommended_category",
    })
    client_id = v.req_string(body, "client_id")
    referral_id = v.req_string(body, "referral_id")
    expected_client_version = v.req_int(body, "expected_client_version")
    acuity_score = _opt_score(body, "acuity_score")
    contrast_score = _opt_score(body, "contrast_score")
    field_loss_pct = _opt_score(body, "field_loss_pct")
    recommended_category = v.opt_enum(body, "recommended_category", CATEGORIES, default=None)

    # existence
    client = store.clients.get(client_id)
    if client is None:
        raise errors.not_found("Client not found")
    referral = store.referrals.get(referral_id)
    if referral is None:
        raise errors.not_found("Referral not found")

    # referral must belong to the same client (ERR_VALIDATION per endpoint description)
    if referral["client_id"] != client_id:
        raise errors.validation("referral_id does not belong to client_id")

    # OCC (priority 5)
    if expected_client_version != client["version"]:
        raise errors.stale_version()

    # cross-entity state (priority 8)
    if referral["status"] != "ACCEPTED":
        raise errors.referral_not_accepted()

    # side effects: supersede DRAFT/REVISED evaluations of the same client; bump client version
    for ev in store.evaluations.values():
        if ev["client_id"] == client_id and ev["status"] in ("DRAFT", "REVISED"):
            ev["status"] = "SUPERSEDED"
            touch(ev)
    touch(client)

    evaluation = new_entity()
    evaluation.update({
        "client_id": client_id,
        "referral_id": referral_id,
        "evaluator_user_id": actor.user_id,
        "acuity_score": acuity_score,
        "contrast_score": contrast_score,
        "field_loss_pct": field_loss_pct,
        "recommended_category": recommended_category,
        "status": "DRAFT",
    })
    store.evaluations[evaluation["id"]] = evaluation
    return success_object(evaluation, status=201)


@bp.get("/api/evaluations/<eid>")
def get_evaluation(eid):
    require_roles(ALL_ROLES)
    ev = store.evaluations.get(eid)
    if ev is None:
        raise errors.not_found("Evaluation not found")
    return success_object(ev)


@bp.get("/api/evaluations")
def list_evaluations():
    require_roles(ALL_ROLES)
    limit, offset = v.parse_pagination(request.args)
    client_id = request.args.get("client_id")
    referral_id = request.args.get("referral_id")
    status = request.args.get("status")
    items = v.apply_filters(list(store.evaluations.values()), [
        (client_id, "client_id"),
        (referral_id, "referral_id"),
        (status, "status"),
    ])
    items = v.sort_by_created(items)
    total = len(items)
    return success_list(items[offset:offset + limit], limit, offset, total)


@bp.post("/api/evaluations/<eid>/finalize")
def finalize_evaluation(eid):
    require_roles(["VisionSpecialist"])
    ev = store.evaluations.get(eid)
    if ev is None:
        raise errors.not_found("Evaluation not found")
    if ev["status"] not in ("DRAFT", "REVISED"):
        raise errors.invalid_state("Evaluation cannot be finalized from its current state")
    if (ev["acuity_score"] is None or ev["contrast_score"] is None
            or ev["field_loss_pct"] is None or ev["recommended_category"] is None):
        raise errors.assessment_incomplete("All four clinical fields are required to finalize")
    ev["status"] = "FINALIZED"
    touch(ev)
    return success_object(ev)


@bp.post("/api/evaluations/<eid>/revise")
def revise_evaluation(eid):
    require_roles(["VisionSpecialist"])
    body = request.get_json(silent=True)
    if body is not None:
        if not isinstance(body, dict):
            raise errors.validation("Request body must be a JSON object")
        v.reject_unknown_fields(body, SCORE_FIELDS + ("recommended_category",))
    else:
        body = {}
    acuity_score = _opt_score(body, "acuity_score")
    contrast_score = _opt_score(body, "contrast_score")
    field_loss_pct = _opt_score(body, "field_loss_pct")
    recommended_category = v.opt_enum(body, "recommended_category", CATEGORIES, default=None)

    ev = store.evaluations.get(eid)
    if ev is None:
        raise errors.not_found("Evaluation not found")
    if ev["status"] != "FINALIZED":
        raise errors.invalid_state("Only a FINALIZED evaluation can be revised")
    # blocked while any DeviceOrder referencing this evaluation is ACTIVE or CONVERTED
    for order in store.device_orders.values():
        if order["evaluation_id"] == eid and order["status"] in ("ACTIVE", "CONVERTED"):
            raise errors.invalid_state("Evaluation is referenced by an ACTIVE or CONVERTED device order")

    if acuity_score is not None:
        ev["acuity_score"] = acuity_score
    if contrast_score is not None:
        ev["contrast_score"] = contrast_score
    if field_loss_pct is not None:
        ev["field_loss_pct"] = field_loss_pct
    if recommended_category is not None:
        ev["recommended_category"] = recommended_category
    ev["status"] = "REVISED"
    touch(ev)
    return success_object(ev)
