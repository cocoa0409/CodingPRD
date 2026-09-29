"""The supplemental workforce pipeline: fork, join and badge (PRD 3.5)."""
from flask import Blueprint, request

import lookup
import projections
from auth import ALL_ROLES, authorize
from db import create_row, store, touch
from errors import api_error
from response import ok, paginated, parse_pagination
from serializers import serialize
from validators import F, body

bp = Blueprint("workforce", __name__)

CRAFTS = ("PIPEFITTER", "ELECTRICIAN", "INSULATOR", "SCAFFOLD_BUILDER",
          "RAD_TECH", "LABORER")
OUTCOMES = ("CLEAR", "ADVERSE")


@bp.route("/outages/<outage_id>/supplemental-workers", methods=["POST"])
@authorize("ContractorCoordinator")
def create_supplemental_worker(outage_id):
    outage = lookup.outage(outage_id)
    payload = body([
        F("full_name", "str", min_len=1, max_len=120),
        F("craft", "str", enum=CRAFTS),
        F("sponsoring_contractor", "str", min_len=1, max_len=120),
    ])
    worker = create_row(store.supplemental_workers, {
        "outage_id": outage["id"],
        "full_name": payload["full_name"],
        "craft": payload["craft"],
        "sponsoring_contractor": payload["sponsoring_contractor"],
        "background_status": "PENDING",
        "training_modules_completed": 0,
        "training_status": "PENDING",
        "badge_number": None,
        "status": "REQUESTED",
    })
    return ok(serialize(worker), 201)


@bp.route("/supplemental-workers/<row_id>", methods=["GET"])
@authorize(*ALL_ROLES)
def get_supplemental_worker(row_id):
    return ok(serialize(lookup.supplemental_worker(row_id)))


@bp.route("/outages/<outage_id>/supplemental-workers", methods=["GET"])
@authorize(*ALL_ROLES)
def list_supplemental_workers(outage_id):
    outage = lookup.outage(outage_id)
    limit, offset = parse_pagination(request.args)
    rows = projections.workers_of_outage(outage["id"])
    for key in ("status", "craft"):
        wanted = request.args.get(key)
        if wanted is not None:
            rows = [r for r in rows if r[key] == wanted]
    return paginated(rows, limit, offset, serialize)


def _evaluate_join(worker):
    """Fork-join: neither branch alone reaches BADGE_READY."""
    if (worker["status"] == "SCREENING"
            and worker["background_status"] == "CLEAR"
            and worker["training_status"] == "COMPLETE"):
        worker["status"] = "BADGE_READY"
        touch(worker)


@bp.route("/supplemental-workers/<row_id>/background-result", methods=["POST"])
@authorize("AccessAuthority")
def record_background_result(row_id):
    worker = lookup.supplemental_worker(row_id)
    payload = body([F("outcome", "str", enum=OUTCOMES)])
    if worker["status"] not in ("REQUESTED", "SCREENING"):
        raise api_error("ERR_WORKER_STATE_INVALID",
                        "A background result may only be recorded in REQUESTED or SCREENING.")
    if payload["outcome"] == "CLEAR":
        worker["background_status"] = "CLEAR"
        if worker["status"] == "REQUESTED":
            worker["status"] = "SCREENING"
        touch(worker)
        _evaluate_join(worker)
    else:
        worker["background_status"] = "ADVERSE"
        worker["status"] = "DENIED"
        touch(worker)
    return ok(serialize(worker))


@bp.route("/supplemental-workers/<row_id>/training-completion", methods=["POST"])
@authorize("AccessAuthority", "ContractorCoordinator")
def record_training_completion(row_id):
    worker = lookup.supplemental_worker(row_id)
    payload = body([F("modules_completed", "int", ge=0)])
    if worker["status"] not in ("REQUESTED", "SCREENING"):
        raise api_error("ERR_WORKER_STATE_INVALID",
                        "Training may only be recorded in REQUESTED or SCREENING.")
    outage = store.outages[worker["outage_id"]]
    worker["training_modules_completed"] = payload["modules_completed"]
    worker["training_status"] = (
        "COMPLETE"
        if payload["modules_completed"] >= outage["required_training_modules"]
        else "PENDING")
    if worker["status"] == "REQUESTED":
        worker["status"] = "SCREENING"
    touch(worker)
    _evaluate_join(worker)
    return ok(serialize(worker))


@bp.route("/supplemental-workers/<row_id>/badge", methods=["POST"])
@authorize("AccessAuthority")
def badge_worker(row_id):
    worker = lookup.supplemental_worker(row_id)
    payload = body([F("badge_number", "str", min_len=1, max_len=24)])
    if worker["status"] != "BADGE_READY":
        raise api_error("ERR_WORKER_STATE_INVALID",
                        "Badging requires the worker to be in BADGE_READY.")
    outage = store.outages[worker["outage_id"]]
    for other in projections.workers_of_outage(outage["id"]):
        if (other["id"] != worker["id"] and other["status"] == "BADGED"
                and other["badge_number"] == payload["badge_number"]):
            raise api_error("ERR_BADGE_NUMBER_TAKEN",
                            "The badge number is already held by a badged worker.")
    worker["badge_number"] = payload["badge_number"]
    worker["status"] = "BADGED"
    touch(worker)
    projections.recompute_badged_count(outage)
    touch(outage)
    return ok(serialize(worker))
