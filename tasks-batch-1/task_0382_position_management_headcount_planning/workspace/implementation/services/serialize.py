"""Serialization of stored records into API output dicts.

Derived fields (span_of_control, planned/actual cost, posture, committed_fte,
committed_cost_cents, filled_fte, adjusted/available budget) are materialised
here from current state so every read is internally consistent with children
(PRD §2.8, §2.10 — immediate consistency model).
"""
from db import db
from . import calc


def employee_out(e):
    return {
        "id": e["id"],
        "full_name": e["full_name"],
        "email": e["email"],
        "annual_salary_cents": e["annual_salary_cents"],
        "status": e["status"],
        "created_at": e["created_at"],
        "updated_at": e["updated_at"],
        "version": e["version"],
    }


def grade_out(g):
    # Immutable config: only id + created_at as common fields (PRD §2.4).
    return {
        "id": g["id"],
        "code": g["code"],
        "band_min_cents": g["band_min_cents"],
        "band_mid_cents": g["band_mid_cents"],
        "band_max_cents": g["band_max_cents"],
        "rank": g["rank"],
        "created_at": g["created_at"],
    }


def cost_center_out(cc):
    adjusted = calc.adjusted_budget_cents(cc)
    committed_cost = calc.committed_cost_cents(cc["id"])
    return {
        "id": cc["id"],
        "name": cc["name"],
        "code": cc["code"],
        "annual_budget_cents": cc["annual_budget_cents"],
        "adjusted_budget_cents": adjusted,
        "fte_cap": cc["fte_cap"],
        "committed_fte": calc.committed_fte(cc["id"]),
        "committed_cost_cents": committed_cost,
        "filled_fte": calc.filled_fte(cc["id"]),
        "available_budget_cents": adjusted - committed_cost,
        "posture": calc.cost_center_posture(cc["id"]),
        "version": cc["version"],
        "created_at": cc["created_at"],
        "updated_at": cc["updated_at"],
    }


def position_out(p):
    return {
        "id": p["id"],
        "cost_center_id": p["cost_center_id"],
        "grade_id": p["grade_id"],
        "manager_position_id": p["manager_position_id"],
        "title": p["title"],
        "fte": p["fte"],
        "lifecycle_status": p["lifecycle_status"],
        "occupancy_status": p["occupancy_status"],
        "span_of_control": calc.span_of_control(p["id"]),
        "planned_cost_cents": calc.planned_cost_cents(p),
        "actual_cost_cents": calc.actual_cost_cents(p),
        "version": p["version"],
        "created_at": p["created_at"],
        "updated_at": p["updated_at"],
    }


def incumbent_out(i):
    return {
        "id": i["id"],
        "position_id": i["position_id"],
        "employee_id": i["employee_id"],
        "start_date": i["start_date"],
        "end_date": i["end_date"],
        "status": i["status"],
        "created_at": i["created_at"],
        "updated_at": i["updated_at"],
        "version": i["version"],
    }


def freeze_order_out(f):
    return {
        "id": f["id"],
        "cost_center_id": f["cost_center_id"],
        "effective_from": f["effective_from"],
        "effective_to": f["effective_to"],
        "reason": f["reason"],
        "status": f["status"],
        "version": f["version"],
        "created_at": f["created_at"],
        "updated_at": f["updated_at"],
    }


def requisition_out(r):
    return {
        "id": r["id"],
        "position_id": r["position_id"],
        "req_type": r["req_type"],
        "justification": r["justification"],
        "status": r["status"],
        "version": r["version"],
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
    }


def reclass_request_out(r):
    return {
        "id": r["id"],
        "position_id": r["position_id"],
        "target_grade_id": r["target_grade_id"],
        "from_grade_rank": r["from_grade_rank"],
        "target_grade_rank": r["target_grade_rank"],
        "direction": r["direction"],
        "status": r["status"],
        "version": r["version"],
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
    }


def forecast_period_out(fp):
    return {
        "id": fp["id"],
        "cost_center_id": fp["cost_center_id"],
        "fiscal_label": fp["fiscal_label"],
        "planned_fte": fp["planned_fte"],
        "actual_fte": fp["actual_fte"],
        "variance_fte": fp["variance_fte"],
        "status": fp["status"],
        "version": fp["version"],
        "created_at": fp["created_at"],
        "updated_at": fp["updated_at"],
    }


def budget_adjustment_out(b):
    # Append-only event: only id + created_at as common fields (PRD §2.4).
    return {
        "id": b["id"],
        "cost_center_id": b["cost_center_id"],
        "amount_cents": b["amount_cents"],
        "memo": b["memo"],
        "status": b["status"],
        "created_at": b["created_at"],
    }
