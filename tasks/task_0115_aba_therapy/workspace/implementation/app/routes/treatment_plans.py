"""TreatmentPlan endpoints — PRD §3.3."""
from decimal import Decimal

from flask import Blueprint, jsonify, request

from ..auth import require_auth
from ..errors import APIError
from ..helpers import (
    get_json_body,
    get_pagination_params,
    paginate,
    require_field,
)
from ..responses import list_response, success_response
from ..services.lookups import get_evaluation, get_patient, get_treatment_plan
from ..services.serialize import serialize_plan
from ..store import get_lock, get_store, stamp_create, stamp_update


bp = Blueprint("treatment_plans", __name__)


def _check_supervision_target_ratio(supervision: float, direct: int) -> None:
    """Static plan ratio gate (PRD §2.10): supervision/direct must be >= 0.10."""
    if direct <= 0:
        raise APIError("ERR_PLAN_RATIO_INSUFFICIENT",
                       "weekly_direct_hours_target must be > 0 to compute supervision ratio")
    ratio = Decimal(str(supervision)) / Decimal(direct)
    if ratio < Decimal("0.10"):
        raise APIError("ERR_PLAN_RATIO_INSUFFICIENT",
                       f"plan ratio {ratio} is below 0.10")


@bp.post("/patients/<patient_id>/treatment-plans")
@require_auth("BCBA")
def create_plan(patient_id):
    body = get_json_body()
    with get_lock():
        patient = get_patient(patient_id)
        clinic = get_store().clinics[patient["clinic_id"]]
        store = get_store()

        source_evaluation_id = require_field(body, "source_evaluation_id")
        weekly_direct = require_field(body, "weekly_direct_hours_target")
        weekly_supervision = require_field(body, "weekly_supervision_hours_target")
        weekly_parent_training = require_field(body, "weekly_parent_training_hours_target")

        if not isinstance(weekly_direct, int) or isinstance(weekly_direct, bool):
            raise APIError("ERR_VALIDATION", "weekly_direct_hours_target must be an integer")
        if not isinstance(weekly_supervision, (int, float)) or isinstance(weekly_supervision, bool):
            raise APIError("ERR_VALIDATION", "weekly_supervision_hours_target must be numeric")
        if not isinstance(weekly_parent_training, (int, float)) or isinstance(weekly_parent_training, bool):
            raise APIError("ERR_VALIDATION", "weekly_parent_training_hours_target must be numeric")
        # Parent-training target must lie in [0.5, 4.0].
        if not (Decimal("0.5") <= Decimal(str(weekly_parent_training)) <= Decimal("4.0")):
            raise APIError("ERR_VALIDATION",
                           "weekly_parent_training_hours_target must be in [0.5, 4.0]")

        # Source evaluation FK + status.
        ev = get_evaluation(source_evaluation_id)
        if ev["patient_id"] != patient_id:
            raise APIError("ERR_VALIDATION",
                           "source_evaluation must belong to the same patient")
        if ev["status"] != "COMPLETED":
            raise APIError("ERR_INVALID_STATE",
                           "source_evaluation must be in COMPLETED status")
        if weekly_direct != ev["recommended_weekly_hours"]:
            raise APIError("ERR_VALIDATION",
                           "weekly_direct_hours_target must equal source_evaluation.recommended_weekly_hours")

        # Uniqueness: at most one DRAFT plan per patient. An ACTIVE plan
        # may coexist with a DRAFT plan, which enables the supersede flow
        # in PRD §3.3 ("A BCBA prepares a new plan in DRAFT for the same
        # patient and then invokes the supersede capability on the new
        # plan").
        for p in store.treatment_plans.values():
            if p["patient_id"] == patient_id and p["status"] == "DRAFT":
                raise APIError(
                    "ERR_TREATMENT_PLAN_CONFLICT",
                    "Patient already has a TreatmentPlan in DRAFT",
                )

        record = stamp_create(
            {
                "patient_id": patient_id,
                "source_evaluation_id": source_evaluation_id,
                "weekly_direct_hours_target": weekly_direct,
                "weekly_supervision_hours_target": weekly_supervision,
                "weekly_parent_training_hours_target": weekly_parent_training,
                "plan_version": 1,
                "superseded_by_id": None,
                "activated_at": None,
                "status": "DRAFT",
            },
            now=clinic["now_ts"],
        )
        store.treatment_plans[record["id"]] = record

    body_out, status = success_response(serialize_plan(record), status=201)
    return jsonify(body_out), status


@bp.post("/treatment-plans/<plan_id>/activate")
@require_auth("BCBA")
def activate_plan(plan_id):
    with get_lock():
        plan = get_treatment_plan(plan_id)
        if plan["status"] != "DRAFT":
            raise APIError("ERR_INVALID_STATE",
                           f"Cannot activate plan in status {plan['status']}")

        store = get_store()
        # Uniqueness: another ACTIVE plan for the patient → conflict.
        for p in store.treatment_plans.values():
            if p["id"] == plan_id:
                continue
            if p["patient_id"] == plan["patient_id"] and p["status"] == "ACTIVE":
                raise APIError("ERR_TREATMENT_PLAN_CONFLICT",
                               "Another TreatmentPlan is already ACTIVE for this patient")

        # Source evaluation must still be COMPLETED.
        ev = store.evaluations.get(plan["source_evaluation_id"])
        if ev is None or ev["status"] != "COMPLETED":
            raise APIError("ERR_INVALID_STATE",
                           "source_evaluation must still be COMPLETED at activation")

        # Static supervision ratio gate.
        _check_supervision_target_ratio(
            plan["weekly_supervision_hours_target"],
            plan["weekly_direct_hours_target"],
        )

        patient = get_patient(plan["patient_id"])
        clinic = store.clinics[patient["clinic_id"]]
        plan["activated_at"] = clinic["now_ts"]
        plan["status"] = "ACTIVE"
        stamp_update(plan, now=clinic["now_ts"])

    body_out, status = success_response(serialize_plan(plan))
    return jsonify(body_out), status


@bp.post("/treatment-plans/<plan_id>/supersede")
@require_auth("BCBA")
def supersede_plan(plan_id):
    body = get_json_body()
    previous_plan_id = require_field(body, "previous_plan_id")
    with get_lock():
        new_plan = get_treatment_plan(plan_id)
        old_plan = get_treatment_plan(previous_plan_id)

        if new_plan["status"] != "DRAFT":
            raise APIError("ERR_INVALID_STATE",
                           f"New plan must be DRAFT (is {new_plan['status']})")
        if old_plan["status"] != "ACTIVE":
            raise APIError("ERR_INVALID_STATE",
                           f"Previous plan must be ACTIVE (is {old_plan['status']})")
        if new_plan["patient_id"] != old_plan["patient_id"]:
            raise APIError("ERR_VALIDATION",
                           "supersede target plan must belong to the same patient")

        # Source evaluation of the new plan must still be COMPLETED.
        ev = get_store().evaluations.get(new_plan["source_evaluation_id"])
        if ev is None or ev["status"] != "COMPLETED":
            raise APIError("ERR_INVALID_STATE",
                           "source_evaluation must still be COMPLETED at supersede time")

        # Static ratio gate on the new plan.
        _check_supervision_target_ratio(
            new_plan["weekly_supervision_hours_target"],
            new_plan["weekly_direct_hours_target"],
        )

        patient = get_patient(new_plan["patient_id"])
        clinic = get_store().clinics[patient["clinic_id"]]
        now_ts = clinic["now_ts"]

        # Atomic: old → SUPERSEDED, new → ACTIVE, plan_version increments.
        old_plan["status"] = "SUPERSEDED"
        old_plan["superseded_by_id"] = new_plan["id"]
        stamp_update(old_plan, now=now_ts)

        new_plan["plan_version"] = old_plan["plan_version"] + 1
        new_plan["activated_at"] = now_ts
        new_plan["status"] = "ACTIVE"
        stamp_update(new_plan, now=now_ts)

    body_out, status = success_response(serialize_plan(new_plan))
    return jsonify(body_out), status


@bp.get("/patients/<patient_id>/treatment-plans")
@require_auth("BCBA", "ClinicAdmin", "RBT", "PayerAdmin")
def list_plans(patient_id):
    limit, offset = get_pagination_params()
    status_filter = request.args.get("status")
    with get_lock():
        get_patient(patient_id)
        items = [
            p for p in get_store().treatment_plans.values()
            if p["patient_id"] == patient_id and (status_filter is None or p["status"] == status_filter)
        ]
        items.sort(key=lambda p: p["created_at"])
        page, total = paginate(items, limit, offset)
        body_out, status = list_response(
            [serialize_plan(p) for p in page], total, limit, offset
        )
    return jsonify(body_out), status
