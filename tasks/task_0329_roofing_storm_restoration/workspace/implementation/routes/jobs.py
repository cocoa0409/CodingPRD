"""Job resource: create, read, list, and lifecycle transitions."""
from flask import Blueprint, request

import errors
from errors import ApiError
from db import db, common_create_fields, touch
from middleware import require_role, get_json_body
from response import success, list_response
import validators as V

bp = Blueprint("jobs", __name__)

ROLE_ALL = {"FieldAdjuster", "Estimator", "ProductionManager"}
PERILS = {"HAIL", "WIND", "HURRICANE", "OTHER"}


def _new_job(customer_name, property_address, peril, assigned_estimator_id,
             insurance_carrier, retainage_pct):
    ent = common_create_fields(versioned=True)
    ent.update({
        "customer_name": customer_name,
        "property_address": property_address,
        "peril": peril,
        "insurance_carrier": insurance_carrier,
        "status": "LEAD",
        "assigned_estimator_id": assigned_estimator_id,
        "bound_estimate_id": None,
        "contract_value_cents": 0,
        "disbursed_gross_cents": 0,
        "retainage_held_cents": 0,
        "disbursed_net_cents": 0,
        "billed_pct": 0,
        "remaining_billable_cents": 0,
        "retainage_pct": retainage_pct,
        "lost_reason": None,
    })
    return ent


@bp.route("/jobs", methods=["POST"])
def create_job():
    require_role({"FieldAdjuster"})
    body = get_json_body()
    customer_name = V.require_field(body, "customer_name")
    property_address = V.require_field(body, "property_address")
    peril = V.require_field(body, "peril")
    assigned_estimator_id = V.require_field(body, "assigned_estimator_id")
    for fld, val in (("customer_name", customer_name),
                     ("property_address", property_address),
                     ("assigned_estimator_id", assigned_estimator_id)):
        if not isinstance(val, str):
            V.missing_field(fld)

    # FK resolution (priority 4) before enum/range (priority 6).
    V.resolve_fk(db.estimators, assigned_estimator_id)

    # enum / range (priority 6)
    V.validate_enum(peril, PERILS, "peril")
    retainage_pct = body.get("retainage_pct", 0.10)
    if retainage_pct is None:
        retainage_pct = 0.10
    V.validate_number(retainage_pct, "retainage_pct", ge=0, le=0.20)

    insurance_carrier = body.get("insurance_carrier")
    if insurance_carrier is not None and not isinstance(insurance_carrier, str):
        V.invalid_request("insurance_carrier must be a string")

    ent = _new_job(customer_name, property_address, peril,
                   assigned_estimator_id, insurance_carrier, retainage_pct)
    with db.lock:
        db.jobs[ent["id"]] = ent
    return success(ent, status=201)


@bp.route("/jobs/<entity_id>", methods=["GET"])
def get_job(entity_id):
    require_role(ROLE_ALL)
    ent = V.find_or_404(db.jobs, entity_id)
    return success(ent, status=200)


@bp.route("/jobs", methods=["GET"])
def list_jobs():
    require_role(ROLE_ALL)
    limit, offset = V.parse_pagination()
    status = request.args.get("status")
    est_id = request.args.get("assigned_estimator_id")
    items = list(db.jobs.values())
    if status is not None:
        items = [j for j in items if j["status"] == status]
    if est_id is not None:
        items = [j for j in items if j["assigned_estimator_id"] == est_id]
    items = V.sort_by_created(items)
    page, total = V.paginate(items, limit, offset)
    return list_response(page, limit, offset, total)


# ---------------------------------------------------------------------------
# Lifecycle transitions
# ---------------------------------------------------------------------------
def _state(job, *allowed):
    if job["status"] not in allowed:
        raise ApiError(errors.ERR_INVALID_STATE, 409,
                       "Job not in a valid state for this transition")


@bp.route("/jobs/<entity_id>/mark-inspected", methods=["POST"])
def mark_inspected(entity_id):
    require_role({"FieldAdjuster"})
    with db.lock:
        job = V.find_or_404(db.jobs, entity_id)
        _state(job, "LEAD")
        # cross-entity precondition: a PASSED DAMAGE_ASSESSMENT exists
        has = any(
            i["job_id"] == job["id"] and i["kind"] == "DAMAGE_ASSESSMENT"
            and i["status"] == "PASSED"
            for i in db.inspections.values()
        )
        if not has:
            raise ApiError(errors.ERR_NO_PASSED_ASSESSMENT, 409,
                           "No passed damage-assessment inspection")
        job["status"] = "INSPECTED"
        touch(job)
        return success(job, status=200)


@bp.route("/jobs/<entity_id>/mark-estimated", methods=["POST"])
def mark_estimated(entity_id):
    require_role({"Estimator"})
    with db.lock:
        job = V.find_or_404(db.jobs, entity_id)
        _state(job, "INSPECTED")
        has = any(
            e["job_id"] == job["id"] and e["status"] == "FINALIZED"
            for e in db.estimates.values()
        )
        if not has:
            raise ApiError(errors.ERR_NO_FINALIZED_ESTIMATE, 409,
                           "No finalized estimate")
        job["status"] = "ESTIMATED"
        touch(job)
        return success(job, status=200)


@bp.route("/jobs/<entity_id>/contract", methods=["POST"])
def contract_job(entity_id):
    require_role({"Estimator"})
    with db.lock:
        job = V.find_or_404(db.jobs, entity_id)
        body = get_json_body()
        estimate_id = V.require_field(body, "estimate_id")
        if not isinstance(estimate_id, str):
            V.missing_field("estimate_id")
        # FK resolution (priority 4)
        estimate = V.resolve_fk(db.estimates, estimate_id)
        # A job already bound (already contracted) cannot be contracted again.
        # This guards the re-contract case ahead of the generic state check so a
        # CONTRACTED/later job surfaces ERR_ALREADY_CONTRACTED (PRD §3.3).
        if job.get("bound_estimate_id") is not None:
            raise ApiError(errors.ERR_ALREADY_CONTRACTED, 409,
                           "Job already has a bound estimate")
        # state (priority 7): job must be ESTIMATED
        _state(job, "ESTIMATED")
        # the named estimate must belong to this job and be FINALIZED
        if estimate["job_id"] != job["id"] or estimate["status"] != "FINALIZED":
            raise ApiError(errors.ERR_INVALID_STATE, 409,
                           "Estimate must belong to this job and be FINALIZED")
        # bind
        job["bound_estimate_id"] = estimate_id
        job["contract_value_cents"] = estimate["final_total_cents"]
        job["remaining_billable_cents"] = estimate["final_total_cents"]
        job["status"] = "CONTRACTED"
        touch(job)
        # supersede other FINALIZED estimates for this job
        for e in db.estimates.values():
            if (e["job_id"] == job["id"] and e["id"] != estimate_id
                    and e["status"] == "FINALIZED"):
                e["status"] = "SUPERSEDED"
                touch(e)
        return success(job, status=200)


@bp.route("/jobs/<entity_id>/start-production", methods=["POST"])
def start_production(entity_id):
    require_role({"ProductionManager"})
    with db.lock:
        job = V.find_or_404(db.jobs, entity_id)
        _state(job, "CONTRACTED")
        delivered = any(
            m["job_id"] == job["id"] and m["status"] == "DELIVERED"
            for m in db.material_orders.values()
        )
        if not delivered:
            raise ApiError(errors.ERR_MATERIALS_NOT_DELIVERED, 409,
                           "No delivered material order")
        issued = any(
            p["job_id"] == job["id"] and p["status"] == "ISSUED"
            for p in db.permits.values()
        )
        if not issued:
            raise ApiError(errors.ERR_PERMIT_NOT_ISSUED, 409,
                           "No issued permit")
        job["status"] = "IN_PRODUCTION"
        touch(job)
        return success(job, status=200)


@bp.route("/jobs/<entity_id>/complete", methods=["POST"])
def complete_job(entity_id):
    require_role({"ProductionManager"})
    with db.lock:
        job = V.find_or_404(db.jobs, entity_id)
        _state(job, "IN_PRODUCTION")
        if job["billed_pct"] != 1.0:
            raise ApiError(errors.ERR_FINAL_DRAW_MISSING, 409,
                           "Final draw not disbursed")
        passed_final = any(
            i["job_id"] == job["id"] and i["kind"] == "PERMIT_FINAL"
            and i["status"] == "PASSED"
            for i in db.inspections.values()
        )
        if not passed_final:
            raise ApiError(errors.ERR_FINAL_INSPECTION_MISSING, 409,
                           "No passed permit-final inspection")
        open_co = any(
            co["job_id"] == job["id"] and co["status"] in ("PROPOSED", "APPROVED")
            for co in db.change_orders.values()
        )
        if open_co:
            raise ApiError(errors.ERR_OPEN_CHANGE_ORDER, 409,
                           "Open change order present")
        job["status"] = "COMPLETED"
        touch(job)
        return success(job, status=200)


@bp.route("/jobs/<entity_id>/lose", methods=["POST"])
def lose_job(entity_id):
    require_role({"FieldAdjuster"})
    with db.lock:
        job = V.find_or_404(db.jobs, entity_id)
        body = get_json_body()
        lost_reason = V.require_field(body, "lost_reason")
        if not isinstance(lost_reason, str):
            V.missing_field("lost_reason")
        _state(job, "LEAD", "INSPECTED", "ESTIMATED")
        job["status"] = "LOST"
        job["lost_reason"] = lost_reason
        touch(job)
        return success(job, status=200)
