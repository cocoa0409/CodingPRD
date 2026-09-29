"""Pass programmes: catalogue lifecycle, billing runs, revenue analytics."""

from flask import Blueprint

import serializers
from db import db
from errors import ApiError
from middleware import (ROLE_COMPLIANCE_OFFICER, ROLE_PROGRAM_ADMIN, require)
from response import created_response, list_response, object_response
from services import billing, domain
from validate import field, pagination, query_enum, query_int, read_body

bp = Blueprint("programs", __name__)

PROGRAM_STATUSES = ("DESIGN", "SALES_OPEN", "SEASON_ACTIVE", "RENEWAL_OPEN", "CLOSED")

LEGAL_TRANSITIONS = {
    ("DESIGN", "SALES_OPEN"),
    ("SALES_OPEN", "SEASON_ACTIVE"),
    ("SEASON_ACTIVE", "RENEWAL_OPEN"),
    ("RENEWAL_OPEN", "CLOSED"),
    ("SEASON_ACTIVE", "CLOSED"),
}

CREATE_SPEC = {
    "season_year": field("integer", required=True),
    "park_name": field("string", required=True),
    "early_bird_deadline": field("date", required=True),
    "capacity_peak_threshold_pct": field("number", minimum=0.50),
    "capacity_lock_threshold_pct": field("number", maximum=1.20),
    "capacity_lock_blockout_max_rank": field("integer", minimum=0),
    "delinquency_suspension_threshold": field("integer", minimum=1),
    "default_threshold": field("integer", minimum=2, maximum=12),
    "sharing_case_auto_open_score": field("integer", minimum=0),
}


@bp.post("/pass-programs")
def create_program():
    require(ROLE_PROGRAM_ADMIN)
    body = read_body(CREATE_SPEC)
    peak = body.get("capacity_peak_threshold_pct", 0.85)
    lock = body.get("capacity_lock_threshold_pct", 0.97)
    suspension = body.get("delinquency_suspension_threshold", 2)
    default_threshold = body.get("default_threshold", 3)
    if not (peak < lock):
        raise ApiError(
            "ERR_INVALID_REQUEST",
            "capacity_peak_threshold_pct must be strictly below capacity_lock_threshold_pct",
        )
    if not (suspension < default_threshold):
        raise ApiError(
            "ERR_INVALID_REQUEST",
            "delinquency_suspension_threshold must be strictly below default_threshold",
        )
    record = db.insert("pass_programs", {
        "season_year": body["season_year"],
        "park_name": body["park_name"],
        "status": "DESIGN",
        "early_bird_deadline": body["early_bird_deadline"],
        "capacity_peak_threshold_pct": peak,
        "capacity_lock_threshold_pct": lock,
        "capacity_lock_blockout_max_rank": body.get("capacity_lock_blockout_max_rank", 2),
        "delinquency_suspension_threshold": suspension,
        "default_threshold": default_threshold,
        "sharing_case_auto_open_score": body.get("sharing_case_auto_open_score", 65),
    })
    db.commit()
    return created_response(serializers.program_out(record))


@bp.get("/pass-programs")
def list_programs():
    require()
    limit, offset = pagination()
    status = query_enum("status", PROGRAM_STATUSES)
    season_year = query_int("season_year")
    rows = db.rows("pass_programs")
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    if season_year is not None:
        rows = [r for r in rows if r["season_year"] == season_year]
    rows = sorted(rows, key=lambda r: r["id"])
    rows = sorted(rows, key=lambda r: r["created_at"], reverse=True)
    return list_response([serializers.program_out(r) for r in rows], limit, offset)


@bp.get("/pass-programs/<program_id>")
def get_program(program_id):
    require()
    record = domain.get_program(program_id)
    return object_response(serializers.program_out(record))


@bp.post("/pass-programs/<program_id>/advance-status")
def advance_status(program_id):
    require(ROLE_PROGRAM_ADMIN)
    body = read_body({"target_status": field("enum", required=True, enum=PROGRAM_STATUSES)})
    program = domain.get_program(program_id)
    target = body["target_status"]
    current = program["status"]
    if (current, target) not in LEGAL_TRANSITIONS:
        raise ApiError("ERR_INVALID_PROGRAM_TRANSITION")
    if current == "DESIGN" and target == "SALES_OPEN":
        published = [t for t in domain.program_tiers(program_id) if t["status"] == "PUBLISHED"]
        if not published:
            raise ApiError(
                "ERR_INVALID_PROGRAM_TRANSITION",
                "at least one PUBLISHED pass tier is required",
            )
    if current == "SALES_OPEN" and target == "SEASON_ACTIVE":
        if not domain.program_park_days(program_id):
            raise ApiError(
                "ERR_INVALID_PROGRAM_TRANSITION",
                "at least one park day is required",
            )
    program["status"] = target
    if target == "CLOSED":
        domain.expire_program_passes(program)
    db.force_touch(program)
    db.commit()
    return object_response(serializers.program_out(program))


@bp.post("/pass-programs/<program_id>/billing-runs")
def billing_run(program_id):
    require(ROLE_PROGRAM_ADMIN)
    body = read_body({"as_of_date": field("date", required=True)})
    program = domain.get_program(program_id)
    report = billing.run_billing(program, body["as_of_date"])
    db.commit()
    return object_response(report)


@bp.get("/pass-programs/<program_id>/revenue-summary")
def revenue_summary(program_id):
    require(ROLE_PROGRAM_ADMIN, ROLE_COMPLIANCE_OFFICER)
    program = domain.get_program(program_id)
    revenue = domain.program_revenue(program["id"])
    return object_response({
        "program_id": program["id"],
        "base_revenue_cents": revenue["base_revenue_cents"],
        "recognized_revenue_cents": revenue["recognized_revenue_cents"],
        "deferred_revenue_cents": revenue["deferred_revenue_cents"],
        "forfeited_revenue_cents": revenue["forfeited_revenue_cents"],
        "active_pass_count": revenue["active_pass_count"],
        "total_visit_count": revenue["total_visit_count"],
        "visits_per_active_pass": revenue["visits_per_active_pass"],
        "total_in_park_spend_cents": revenue["total_in_park_spend_cents"],
        "spend_per_visit_cents": revenue["spend_per_visit_cents"],
    })
