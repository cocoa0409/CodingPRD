"""Return-reduction levers and their measured deployments (PRD 3.9)."""

from flask import Blueprint, request

import constants as C
import validate as V
from db import db, new_row
from errors import ApiError
from lookup import (ensure_not_delisted, filtered, get_deployment, get_intervention,
                    get_item)
from middleware import authenticate
from response import array_response, object_response
from services.derive import (deployments_of_item, recompute_intervention,
                             terminate_deployment)
from services.deployments import savings_report

bp = Blueprint("interventions", __name__)


@bp.post("/fit-program/interventions")
def create_intervention():
    authenticate(C.ROLE_MERCH_OPS_ADMIN)
    body = V.get_body()

    name = V.req_str(body, "name", min_len=1, max_len=200)
    lever = V.req_enum(body, "lever", C.LEVERS)
    unit_cost_cents = V.req_int(body, "unit_cost_cents", minimum=0)

    intervention = new_row({
        "name": name,
        "lever": lever,
        "unit_cost_cents": unit_cost_cents,
        "deployment_count": 0,
        "measured_deployment_count": 0,
        "gross_savings_cents": 0,
        "spend_cents": 0,
        "net_savings_cents": 0,
        "funding_posture": "FUNDED",
    })
    db.interventions[intervention["id"]] = intervention
    return object_response(intervention, 201)


@bp.get("/fit-program/interventions/<intervention_id>")
def read_intervention(intervention_id):
    authenticate(C.ROLE_MERCH_OPS_ADMIN, C.ROLE_FIT_ANALYST)
    return object_response(get_intervention(intervention_id))


@bp.get("/fit-program/interventions/<intervention_id>/savings-report")
def read_savings_report(intervention_id):
    authenticate(C.ROLE_MERCH_OPS_ADMIN, C.ROLE_FIT_ANALYST)
    intervention = get_intervention(intervention_id)

    variant = request.args.get("variant")
    if variant is None or variant == "":
        variant = C.DEFAULT_SAVINGS_VARIANT
    if variant not in C.SAVINGS_VARIANTS:
        raise V.invalid("'variant' must be one of %s."
                        % ", ".join(C.SAVINGS_VARIANTS))

    return object_response(savings_report(intervention, variant))


# ---------------------------------------------------------------------------
# deployments
# ---------------------------------------------------------------------------
def _windows_intersect(new_start, new_end, old_start, old_end):
    """Half-open [start, end); touching endpoints do not intersect."""
    return new_start < old_end and old_start < new_end


@bp.post("/fit-program/intervention-deployments")
def schedule_deployment():
    authenticate(C.ROLE_MERCH_OPS_ADMIN)
    body = V.get_body()

    intervention_id = V.req_str(body, "intervention_id", min_len=1)
    item_id = V.req_str(body, "item_id", min_len=1)
    window_start = V.req_instant(body, "window_start")
    window_end = V.req_instant(body, "window_end")
    spend_cents = V.req_int(body, "spend_cents", minimum=0)

    intervention = get_intervention(intervention_id)
    item = get_item(item_id)
    ensure_not_delisted(item)

    # window sanity belongs to the same rank as the overlap check
    if window_start >= window_end:
        raise ApiError("ERR_DEPLOYMENT_WINDOW_OVERLAP",
                       "window_start must be strictly before window_end.")
    for existing in deployments_of_item(item["id"]):
        if existing["status"] in ("TERMINATED", "MEASURED"):
            continue
        other = db.interventions.get(existing["intervention_id"])
        if other is None or other["lever"] != intervention["lever"]:
            continue
        if _windows_intersect(window_start, window_end,
                              existing["window_start"], existing["window_end"]):
            raise ApiError("ERR_DEPLOYMENT_WINDOW_OVERLAP",
                           "A live deployment of this lever already covers part "
                           "of that window on this item.")

    if item["listing_status"] != "LISTED":
        raise ApiError("ERR_DEPLOYMENT_ITEM_NOT_LISTED",
                       "The item must be LISTED to carry a deployment; it is %s."
                       % item["listing_status"])

    deployment = new_row({
        "intervention_id": intervention["id"],
        "item_id": item["id"],
        "window_start": window_start,
        "window_end": window_end,
        "spend_cents": spend_cents,
        "status": "SCHEDULED",
        "baseline_units_count": None,
        "baseline_return_rate_bp": None,
        "window_units_count": None,
        "measured_return_rate_bp": None,
        "avoided_return_count": None,
        "attributed_savings_cents": None,
        "terminated_reason_code": None,
        "_hop_run": 0,
    })
    db.deployments[deployment["id"]] = deployment

    recompute_intervention(intervention)
    return object_response(deployment, 201)


@bp.get("/fit-program/intervention-deployments/<deployment_id>")
def read_deployment(deployment_id):
    authenticate(C.ROLE_MERCH_OPS_ADMIN, C.ROLE_FIT_ANALYST)
    return object_response(get_deployment(deployment_id))


@bp.get("/fit-program/intervention-deployments")
def list_deployments():
    authenticate(C.ROLE_MERCH_OPS_ADMIN, C.ROLE_FIT_ANALYST)
    limit, offset = V.pagination_params()
    rows = filtered(db.deployments.values(), {
        "intervention_id": "intervention_id",
        "item_id": "item_id",
        "status": "status",
    })
    page, meta = V.paginate(rows, limit, offset)
    return array_response(page, meta)


@bp.post("/fit-program/intervention-deployments/<deployment_id>/terminate")
def terminate_early(deployment_id):
    authenticate(C.ROLE_MERCH_OPS_ADMIN)
    deployment = get_deployment(deployment_id)
    body = V.get_body()
    reason_code = V.req_enum(body, "terminated_reason_code",
                             C.TERMINATED_REASON_CODES)

    if deployment["status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_DEPLOYMENT_STATE",
                       "Only an ACTIVE deployment can be terminated; this one is "
                       "%s." % deployment["status"])

    terminate_deployment(deployment, reason_code)
    return object_response(deployment)
