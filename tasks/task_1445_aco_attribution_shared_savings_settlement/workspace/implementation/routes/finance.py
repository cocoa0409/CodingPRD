"""Benchmarks."""
from flask import Blueprint, request

import db
from errors import (ApiError, not_found, ERR_STALE_VERSION,
                    ERR_PERIOD_NOT_LOCKED)
from middleware import require_roles, ROLE_ACO_ADMIN, ALL_DOMAIN_ROLES
from response import success, list_success
from serializers import benchmark_out
from services import calc
from validate import get_json_body, validate_body

bp = Blueprint("finance", __name__)

BENCHMARK_SPEC = {
    "variant": {"type": "enum", "enum": ["PROVISIONAL", "FINAL"], "required": True},
    "expected_agreement_period_version": {"type": "int", "required": True},
}


@bp.post("/aco/agreement-periods/<period_id>/benchmarks")
def create_benchmark(period_id):
    require_roles([ROLE_ACO_ADMIN])
    body = validate_body(get_json_body(), BENCHMARK_SPEC)
    period = db.periods.get(period_id)
    if period is None:
        raise not_found("Agreement period not found")
    # OCC (priority 5) precedes period posture (priority 6).
    if body["expected_agreement_period_version"] != period["version"]:
        raise ApiError(ERR_STALE_VERSION, 412,
                       "expected_agreement_period_version does not match the "
                       "period's current version")
    if period["status"] != "ASSIGNMENT_LOCKED":
        raise ApiError(ERR_PERIOD_NOT_LOCKED, 409,
                       "Benchmark computation requires an ASSIGNMENT_LOCKED period")
    computed = calc.compute_benchmark(period, body["variant"])
    benchmark = db.stamp_new({
        "id": db.new_id(),
        "agreement_period_id": period["id"],
        "variant": body["variant"],
        "beneficiary_months": computed["beneficiary_months"],
        "risk_score_sum": computed["risk_score_sum"],
        "update_factor_used": computed["update_factor_used"],
        "total_benchmark_cents": computed["total_benchmark_cents"],
        "status": "ACTIVE",
    })
    db.benchmarks[benchmark["id"]] = benchmark
    # Each variant keeps at most one ACTIVE benchmark per period.
    for existing in db.benchmarks.values():
        if (existing["agreement_period_id"] == period["id"]
                and existing["variant"] == body["variant"]
                and existing["id"] != benchmark["id"]
                and existing["status"] == "ACTIVE"):
            existing["status"] = "SUPERSEDED"
            db.bump(existing)
    db.bump(period)
    return success(benchmark_out(benchmark), 201)


@bp.get("/aco/benchmarks/<benchmark_id>")
def get_benchmark(benchmark_id):
    require_roles(ALL_DOMAIN_ROLES)
    benchmark = db.benchmarks.get(benchmark_id)
    if benchmark is None:
        raise not_found("Benchmark not found")
    return success(benchmark_out(benchmark))


@bp.get("/aco/benchmarks")
def list_benchmarks():
    require_roles(ALL_DOMAIN_ROLES)
    items = list(db.benchmarks.values())
    for param in ("agreement_period_id", "variant", "status"):
        value = request.args.get(param)
        if value is not None:
            items = [b for b in items if b[param] == value]
    items.sort(key=lambda b: b["created_at"])
    return list_success([benchmark_out(b) for b in items])
