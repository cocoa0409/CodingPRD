"""HealthTreatment endpoints + health-dimension state machine (PRD §3.7)."""
from flask import Blueprint, request

import errors
import serializers
import calculations
from common import (stamp_create, touch, get_body, require_str, require_int,
                    parse_dt, parse_iso, to_iso, must_get, require_fk, paginate)
from db import store
from middleware import require_roles, ALL_ROLES
from response import object_response, array_response

bp = Blueprint("health", __name__)


@bp.route("/health-treatments", methods=["POST"])
def create_treatment():
    require_roles({"Veterinarian"})
    body = get_body()
    cohort_id, cohort = require_fk(body, "cohort_id", store.cohorts)
    tank_id, tank = require_fk(body, "tank_id", store.tanks)
    medication = require_str(body, "medication")
    started_at = parse_dt(body, "started_at")
    duration_days = require_int(body, "duration_days", gt=0)
    withdrawal_days = require_int(body, "withdrawal_days", ge=0)

    with store.lock:
        # Health-dimension state machine: only a HEALTHY cohort can start treatment.
        if cohort["health_status"] != "HEALTHY":
            raise errors.invalid_state()

        # Treatment-window overlap (PRD §3.7, buffer-extended): reject if started_at
        # < withdrawal_end_at of any prior treatment on this tank whose status is
        # ACTIVE or COMPLETED. Adjacency at withdrawal_end_at is allowed.
        for t in store.health_treatments.values():
            if t["tank_id"] != tank_id:
                continue
            if t["status"] not in {"ACTIVE", "COMPLETED"}:
                continue
            prior_withdrawal_end = parse_iso(t["withdrawal_end_at"])
            if started_at < prior_withdrawal_end:
                raise errors.treatment_window_conflict()

        treatment_end, withdrawal_end = calculations.compute_treatment_window(
            started_at, duration_days, withdrawal_days)

        rec = {
            "cohort_id": cohort_id,
            "tank_id": tank_id,
            "medication": medication,
            "started_at": to_iso(started_at),
            "duration_days": duration_days,
            "withdrawal_days": withdrawal_days,
            "treatment_end_at": to_iso(treatment_end),
            "withdrawal_end_at": to_iso(withdrawal_end),
            "status": "ACTIVE",
        }
        stamp_create(rec)
        store.health_treatments[rec["id"]] = rec

        # Cohort health: HEALTHY -> UNDER_TREATMENT; set withdrawal_until.
        cohort["health_status"] = "UNDER_TREATMENT"
        cohort["withdrawal_until"] = to_iso(withdrawal_end)
        touch(cohort)

        data = serializers.health_treatment_out(rec)
    return object_response(data, 201)


@bp.route("/health-treatments", methods=["GET"])
def list_treatments():
    require_roles(ALL_ROLES)
    cohort_id = request.args.get("cohort_id")
    tank_id = request.args.get("tank_id")
    with store.lock:
        items = list(store.health_treatments.values())
        if cohort_id is not None:
            items = [t for t in items if t["cohort_id"] == cohort_id]
        if tank_id is not None:
            items = [t for t in items if t["tank_id"] == tank_id]
        window, limit, offset, total = paginate(items)
        data = [serializers.health_treatment_out(t) for t in window]
    return array_response(data, limit, offset, total)


@bp.route("/health-treatments/<tid>", methods=["GET"])
def get_treatment(tid):
    require_roles(ALL_ROLES)
    with store.lock:
        rec = must_get(store.health_treatments, tid)
        data = serializers.health_treatment_out(rec)
    return object_response(data, 200)


@bp.route("/health-treatments/<tid>/complete", methods=["POST"])
def complete_treatment(tid):
    require_roles({"Veterinarian"})
    with store.lock:
        treatment = must_get(store.health_treatments, tid)
        if treatment["status"] != "ACTIVE":
            raise errors.invalid_state()
        # Must have reached treatment_end_at (PRD §3.7).
        if store.clock < parse_iso(treatment["treatment_end_at"]):
            raise errors.treatment_not_due()

        treatment["status"] = "COMPLETED"
        touch(treatment)

        cohort = store.cohorts.get(treatment["cohort_id"])
        if cohort is not None:
            cohort["health_status"] = "WITHDRAWAL"
            touch(cohort)

        data = serializers.health_treatment_out(treatment)
    return object_response(data, 200)


@bp.route("/health-treatments/<tid>/clear", methods=["POST"])
def clear_treatment(tid):
    require_roles({"Veterinarian"})
    with store.lock:
        treatment = must_get(store.health_treatments, tid)
        if treatment["status"] != "COMPLETED":
            raise errors.invalid_state()
        # Must have reached withdrawal_end_at (PRD §3.7).
        if store.clock < parse_iso(treatment["withdrawal_end_at"]):
            raise errors.treatment_not_due()

        treatment["status"] = "CLEARED"
        touch(treatment)

        cohort = store.cohorts.get(treatment["cohort_id"])
        if cohort is not None:
            cohort["health_status"] = "HEALTHY"
            cohort["withdrawal_until"] = None
            touch(cohort)

        data = serializers.health_treatment_out(treatment)
    return object_response(data, 200)
