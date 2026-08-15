"""Entity -> public JSON serialization (exact field sets from SCAFFOLD 1.1)."""
from util import fmt_dt


def _base(e, common=True):
    out = {"id": e["id"]}
    return out


def _dt(v):
    return fmt_dt(v) if v is not None else None


def _common(e):
    return {
        "created_at": _dt(e["created_at"]),
        "updated_at": _dt(e["updated_at"]),
        "version": e["version"],
    }


def program(p):
    out = {
        "id": p["id"],
        "program_name": p["program_name"],
        "fiscal_year": p["fiscal_year"],
        "state_code": p["state_code"],
        "window_start": _dt(p["window_start"]),
        "window_end": _dt(p["window_end"]),
        "spot_check_modulus": p["spot_check_modulus"],
        "advance_cap_pct": p["advance_cap_pct"],
        "status": p["status"],
        "ranking_run_count": p["ranking_run_count"],
    }
    out.update(_common(p))
    return out


def pool(p):
    available = p["allocated_cents"] - p["obligated_cents"] - p["paid_cents"]
    out = {
        "id": p["id"],
        "program_id": p["program_id"],
        "pool_type": p["pool_type"],
        "allocated_cents": p["allocated_cents"],
        "obligated_cents": p["obligated_cents"],
        "paid_cents": p["paid_cents"],
        "available_cents": available,
    }
    out.update(_common(p))
    return out


def rate(r):
    # Rates and criteria are immutable config rows: id + created_at only.
    return {
        "id": r["id"],
        "program_id": r["program_id"],
        "practice_code": r["practice_code"],
        "unit": r["unit"],
        "standard_rate_cents": r["standard_rate_cents"],
        "hu_rate_cents": r["hu_rate_cents"],
        "lifespan_years": r["lifespan_years"],
        "created_at": _dt(r["created_at"]),
    }


def criterion(c):
    return {
        "id": c["id"],
        "program_id": c["program_id"],
        "criterion_code": c["criterion_code"],
        "weight": c["weight"],
        "max_points": c["max_points"],
        "created_at": _dt(c["created_at"]),
    }


def applicant(a):
    out = {
        "id": a["id"],
        "legal_name": a["legal_name"],
        "hu_category": a["hu_category"],
        "historically_underserved": a["historically_underserved"],
        "parcel_ids": list(a["parcel_ids"]),
    }
    out.update(_common(a))
    return out


def application(a):
    out = {
        "id": a["id"],
        "program_id": a["program_id"],
        "applicant_id": a["applicant_id"],
        "parcel_id": a["parcel_id"],
        "planned_practices": a["planned_practices"],
        "self_reported_answers": a["self_reported_answers"],
        "verified_answers": a["verified_answers"],
        "provisional_score": a["provisional_score"],
        "ranking_score": a["ranking_score"],
        "estimated_obligation_cents": a["estimated_obligation_cents"],
        "funded_pool_id": a["funded_pool_id"],
        "status": a["status"],
    }
    out.update(_common(a))
    return out


def contract(c):
    out = {
        "id": c["id"],
        "program_id": c["program_id"],
        "application_id": c["application_id"],
        "applicant_id": c["applicant_id"],
        "pool_id": c["pool_id"],
        "obligated_amount_cents": c["obligated_amount_cents"],
        "paid_amount_cents": c["paid_amount_cents"],
        "status": c["status"],
    }
    out.update(_common(c))
    return out


def item(i):
    out = {
        "id": i["id"],
        "contract_id": i["contract_id"],
        "payment_schedule_rate_id": i["payment_schedule_rate_id"],
        "practice_code": i["practice_code"],
        "planned_quantity": i["planned_quantity"],
        "unit": i["unit"],
        "applicable_rate_cents": i["applicable_rate_cents"],
        "scheduled_amount_cents": i["scheduled_amount_cents"],
        "implementation_deadline": _dt(i["implementation_deadline"]),
        "certification_status": i["certification_status"],
        "certified_quantity": i["certified_quantity"],
        "certified_by_user_id": i["certified_by_user_id"],
        "certified_at": _dt(i["certified_at"]),
        "payment_status": i["payment_status"],
        "paid_amount_cents": i["paid_amount_cents"],
    }
    out.update(_common(i))
    return out


def payment_request(r):
    out = {
        "id": r["id"],
        "program_id": r["program_id"],
        "contract_id": r["contract_id"],
        "practice_item_id": r["practice_item_id"],
        "documented_cost_cents": r["documented_cost_cents"],
        "documentation_refs": list(r["documentation_refs"]),
        "sequence_number": r["sequence_number"],
        "sampled": r["sampled"],
        "computed_amount_cents": r["computed_amount_cents"],
        "advance_offset_cents": r["advance_offset_cents"],
        "disbursed_amount_cents": r["disbursed_amount_cents"],
        "reviewed_by_user_id": r["reviewed_by_user_id"],
        "status": r["status"],
    }
    out.update(_common(r))
    return out


def advance(a):
    out = {
        "id": a["id"],
        "contract_id": a["contract_id"],
        "applicant_id": a["applicant_id"],
        "practice_item_id": a["practice_item_id"],
        "issued_cents": a["issued_cents"],
        "issued_at": _dt(a["issued_at"]),
        "expenditure_due_date": _dt(a["expenditure_due_date"]),
        "applied_cents": a["applied_cents"],
        "returned_cents": a["returned_cents"],
        "outstanding_cents": a["outstanding_cents"],
        "status": a["status"],
    }
    out.update(_common(a))
    return out


def modification(m):
    out = {
        "id": m["id"],
        "contract_id": m["contract_id"],
        "kind": m["kind"],
        "practice_item_id": m["practice_item_id"],
        "new_deadline": _dt(m["new_deadline"]),
        "new_practice_code": m["new_practice_code"],
        "new_quantity": m["new_quantity"],
        "requested_by_user_id": m["requested_by_user_id"],
        "status": m["status"],
    }
    out.update(_common(m))
    return out


def spot_check(s):
    out = {
        "id": s["id"],
        "contract_id": s["contract_id"],
        "practice_item_id": s["practice_item_id"],
        "payment_request_id": s["payment_request_id"],
        "inspector_user_id": s["inspector_user_id"],
        "failure_reason": s["failure_reason"],
        "status": s["status"],
    }
    out.update(_common(s))
    return out


def obligation(o):
    out = {
        "id": o["id"],
        "contract_id": o["contract_id"],
        "practice_item_id": o["practice_item_id"],
        "parcel_id": o["parcel_id"],
        "practice_code": o["practice_code"],
        "start_date": _dt(o["start_date"]),
        "end_date": _dt(o["end_date"]),
        "reported_by_user_id": o["reported_by_user_id"],
        "status": o["status"],
    }
    out.update(_common(o))
    return out


def demand(d):
    out = {
        "id": d["id"],
        "contract_id": d["contract_id"],
        "maintenance_obligation_id": d["maintenance_obligation_id"],
        "advance_payment_id": d["advance_payment_id"],
        "payment_request_id": d["payment_request_id"],
        "amount_cents": d["amount_cents"],
        "due_date": _dt(d["due_date"]),
        "status": d["status"],
    }
    out.update(_common(d))
    return out
