"""Entity -> JSON serializers.

Server-stamped instants are stored as datetimes and rendered here with the
three-fractional-digit UTC rule.  Caller-supplied instants (operation windows,
dyno windows) are stored as the raw request strings and echoed verbatim.
"""

import clock as clockmod
from store import db


def _base(record, versioned=True):
    out = {"id": record["id"], "created_at": clockmod.render_instant(record["created_at"])}
    if versioned:
        out["updated_at"] = clockmod.render_instant(record["updated_at"])
        out["version"] = record["version"]
    return out


def deposits_held_cents(distributor_id):
    """Derived ledger field: sum of amount_cents over this distributor's HELD
    deposits; closed and forfeited deposits are excluded."""
    total = 0
    for dep in db.core_deposits.values():
        if dep["distributor_id"] == distributor_id and dep["status"] == "HELD":
            total += dep["amount_cents"]
    return total


def distributor(d):
    out = {
        "distributor_code": d["distributor_code"],
        "name": d["name"],
        "emissions_requirement": d["emissions_requirement"],
        "status": d["status"],
        "credit_limit_cents": d["credit_limit_cents"],
        "volume_discount_pct": d["volume_discount_pct"],
        "deposits_held_cents": deposits_held_cents(d["id"]),
        "credit_balance_cents": d["credit_balance_cents"],
    }
    out.update(_base(d))
    return out


def core_return(r):
    out = {
        "distributor_id": r["distributor_id"],
        "build_spec_id": r["build_spec_id"],
        "core_deposit_id": r["core_deposit_id"],
        "status": r["status"],
        "grade": r["grade"],
        "missing_components": list(r["missing_components"]),
        "provisional_credit_cents": r["provisional_credit_cents"],
        "final_credit_cents": r["final_credit_cents"],
        "graded_at": clockmod.render_instant(r["graded_at"]),
        "dispute_count": r["dispute_count"],
    }
    out.update(_base(r))
    return out


def core_deposit(d):
    out = {
        "distributor_id": d["distributor_id"],
        "reman_engine_id": d["reman_engine_id"],
        "amount_cents": d["amount_cents"],
        "sold_at": clockmod.render_instant(d["sold_at"]),
        "status": d["status"],
        "refunded_cents": d["refunded_cents"],
        "forfeited_cents": d["forfeited_cents"],
        "age_days_at_close": d["age_days_at_close"],
        "closed_at": clockmod.render_instant(d["closed_at"]),
    }
    out.update(_base(d))
    return out


def build_spec(s):
    out = {
        "engine_family": s["engine_family"],
        "application_code": s["application_code"],
        "emissions_tier": s["emissions_tier"],
        "status": s["status"],
        "list_price_cents": s["list_price_cents"],
        "core_deposit_cents": s["core_deposit_cents"],
        "core_base_credit_cents": s["core_base_credit_cents"],
        "allowed_reuse_grades": list(s["allowed_reuse_grades"]),
        "allowed_interchange_groups": list(s["allowed_interchange_groups"]),
        "dyno_min_horsepower": s["dyno_min_horsepower"],
        "dyno_min_oil_pressure_psi": s["dyno_min_oil_pressure_psi"],
        "dyno_max_coolant_temp_f": s["dyno_max_coolant_temp_f"],
        "required_op_sequence": list(s["required_op_sequence"]),
        "activated_at": clockmod.render_instant(s["activated_at"]),
        "retired_at": clockmod.render_instant(s["retired_at"]),
    }
    out.update(_base(s))
    return out


def work_order(w):
    out = {
        "core_return_id": w["core_return_id"],
        "build_spec_id": w["build_spec_id"],
        "status": w["status"],
        "reman_engine_id": w["reman_engine_id"],
        "rework_count": w["rework_count"],
    }
    out.update(_base(w))
    return out


def machine_operation(o):
    out = {
        "work_order_id": o["work_order_id"],
        "op_type": o["op_type"],
        "sequence": o["sequence"],
        "station_code": o["station_code"],
        "scheduled_start": o["scheduled_start"],
        "scheduled_end": o["scheduled_end"],
        "result": o["result"],
        "status": o["status"],
        "attempt_count": o["attempt_count"],
    }
    out.update(_base(o))
    return out


def component(c):
    out = {
        "work_order_id": c["work_order_id"],
        "part_type": c["part_type"],
        "interchange_group": c["interchange_group"],
        "reuse_grade": c["reuse_grade"],
        "status": c["status"],
        "consumed_by_work_order_id": c["consumed_by_work_order_id"],
    }
    out.update(_base(c))
    return out


def reman_engine(e):
    out = {
        "work_order_id": e["work_order_id"],
        "build_spec_id": e["build_spec_id"],
        "serial_number": e["serial_number"],
        "status": e["status"],
        "latest_dyno_result": e["latest_dyno_result"],
        "sealed_at": clockmod.render_instant(e["sealed_at"]),
        "sealed_by": e["sealed_by"],
        "distributor_id": e["distributor_id"],
        "sold_at": clockmod.render_instant(e["sold_at"]),
        "sale_price_cents": e["sale_price_cents"],
    }
    out.update(_base(e))
    return out


def dyno_test(t):
    # DynoTest is immutable: only id and created_at, no updated_at / version.
    out = {
        "reman_engine_id": t["reman_engine_id"],
        "recorded_by": t["recorded_by"],
        "dyno_cell_code": t["dyno_cell_code"],
        "started_at": t["started_at"],
        "ended_at": t["ended_at"],
        "horsepower": t["horsepower"],
        "oil_pressure_psi": t["oil_pressure_psi"],
        "coolant_temp_f": t["coolant_temp_f"],
        "result": t["result"],
        "attempt": t["attempt"],
    }
    out.update(_base(t, versioned=False))
    return out


def warranty_claim(c):
    out = {
        "reman_engine_id": c["reman_engine_id"],
        "distributor_id": c["distributor_id"],
        "failure_description": c["failure_description"],
        "status": c["status"],
        "filed_at": clockmod.render_instant(c["filed_at"]),
        "months_in_service": c["months_in_service"],
        "teardown_findings": c["teardown_findings"],
        "teardown_by": c["teardown_by"],
        "settled_credit_cents": c["settled_credit_cents"],
    }
    out.update(_base(c))
    return out
