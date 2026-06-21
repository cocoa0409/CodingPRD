"""ChangeOrder resource: propose, read, list, approve, apply (cascade), void."""
from flask import Blueprint, request

import errors
from errors import ApiError
from db import db, common_create_fields, touch
from middleware import require_role, get_json_body
from response import success, list_response
from services import calculations as calc
from services.jobledger import effective_shingle_squares, recompute_remaining
import validators as V

bp = Blueprint("change_orders", __name__)

ROLE_ALL = {"FieldAdjuster", "Estimator", "ProductionManager"}


@bp.route("/change-orders", methods=["POST"])
def create_change_order():
    require_role({"ProductionManager", "Estimator"})
    body = get_json_body()
    job_id = V.require_field(body, "job_id")
    reason = V.require_field(body, "reason")
    delta_cents = V.require_field(body, "delta_cents")
    if not isinstance(job_id, str):
        V.missing_field("job_id")
    if not isinstance(reason, str):
        V.missing_field("reason")
    # FK (priority 4)
    V.resolve_fk(db.jobs, job_id)
    # range / type (priority 6)
    V.validate_int(delta_cents, "delta_cents")
    extra = body.get("extra_shingle_squares", 0)
    if extra is None:
        extra = 0
    V.validate_number(extra, "extra_shingle_squares", ge=0)

    ent = common_create_fields(versioned=True)
    ent.update({
        "job_id": job_id,
        "reason": reason,
        "delta_cents": delta_cents,
        "extra_shingle_squares": extra,
        "status": "PROPOSED",
    })
    with db.lock:
        db.change_orders[ent["id"]] = ent
    return success(ent, status=201)


@bp.route("/change-orders/<entity_id>", methods=["GET"])
def get_change_order(entity_id):
    require_role(ROLE_ALL)
    ent = V.find_or_404(db.change_orders, entity_id)
    return success(ent, status=200)


@bp.route("/change-orders", methods=["GET"])
def list_change_orders():
    require_role(ROLE_ALL)
    limit, offset = V.parse_pagination()
    items = list(db.change_orders.values())
    for key in ("job_id", "status"):
        val = request.args.get(key)
        if val is not None:
            items = [c for c in items if c.get(key) == val]
    items = V.sort_by_created(items)
    page, total = V.paginate(items, limit, offset)
    return list_response(page, limit, offset, total)


@bp.route("/change-orders/<entity_id>/approve", methods=["POST"])
def approve_change_order(entity_id):
    require_role({"ProductionManager"})
    with db.lock:
        co = V.find_or_404(db.change_orders, entity_id)
        # state (priority 7): must be PROPOSED
        if co["status"] != "PROPOSED":
            raise ApiError(errors.ERR_INVALID_STATE, 409,
                           "Change order not PROPOSED")
        # cross-entity: parent job CONTRACTED or IN_PRODUCTION
        job = db.jobs.get(co["job_id"])
        if job is None or job["status"] not in ("CONTRACTED", "IN_PRODUCTION"):
            raise ApiError(errors.ERR_INVALID_STATE, 409,
                           "Parent job must be CONTRACTED or IN_PRODUCTION")
        co["status"] = "APPROVED"
        touch(co)
        return success(co, status=200)


@bp.route("/change-orders/<entity_id>/apply", methods=["POST"])
def apply_change_order(entity_id):
    require_role({"ProductionManager"})
    with db.lock:
        co = V.find_or_404(db.change_orders, entity_id)
        body = get_json_body()
        expected_version = V.require_field(body, "expected_job_version")
        if not V.is_int(expected_version):
            V.invalid_request("expected_job_version must be an integer")
        # state (priority 7): change order must be APPROVED
        if co["status"] != "APPROVED":
            raise ApiError(errors.ERR_INVALID_STATE, 409,
                           "Change order not APPROVED")
        job = db.jobs.get(co["job_id"])
        # cross-entity state (ERR_INVALID_STATE): job CONTRACTED or IN_PRODUCTION
        if job is None or job["status"] not in ("CONTRACTED", "IN_PRODUCTION"):
            raise ApiError(errors.ERR_INVALID_STATE, 409,
                           "Parent job must be CONTRACTED or IN_PRODUCTION")
        # fiscal (priority 10): contract+delta must not drop below disbursed gross
        if job["contract_value_cents"] + co["delta_cents"] < job["disbursed_gross_cents"]:
            raise ApiError(errors.ERR_CONTRACT_BELOW_DISBURSED, 409,
                           "Amended contract below disbursed gross")
        # OCC (priority 11): version match
        if expected_version != job["version"]:
            raise ApiError(errors.ERR_STALE_JOB_VERSION, 412,
                           "expected_job_version is stale")

        # apply — cascade
        co["status"] = "APPLIED"
        touch(co)
        # hop 1: contract_value += delta
        job["contract_value_cents"] += co["delta_cents"]
        # hop 2: remaining_billable re-derived
        recompute_remaining(job)
        # hop 3: re-size ORDERED material orders when extra squares > 0
        if co.get("extra_shingle_squares", 0) and co["extra_shingle_squares"] > 0:
            new_squares = effective_shingle_squares(job)  # already folds APPLIED COs
            for mo in db.material_orders.values():
                if mo["job_id"] == job["id"] and mo["status"] == "ORDERED":
                    bundles, weight, freight = calc.material_sizing(new_squares)
                    mo["bundles"] = bundles
                    mo["total_weight_lbs"] = weight
                    mo["freight_cents"] = freight
                    touch(mo)
        touch(job)  # version bump closes the apply
        return success(co, status=200)


@bp.route("/change-orders/<entity_id>/void", methods=["POST"])
def void_change_order(entity_id):
    require_role({"ProductionManager"})
    with db.lock:
        co = V.find_or_404(db.change_orders, entity_id)
        if co["status"] not in ("PROPOSED", "APPROVED"):
            raise ApiError(errors.ERR_INVALID_STATE, 409,
                           "Change order not PROPOSED or APPROVED")
        co["status"] = "VOIDED"
        touch(co)
        return success(co, status=200)
