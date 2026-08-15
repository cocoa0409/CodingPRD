"""Bordereaux reporting and the submission data-quality gate (PRD section 3.7).

computed_totals: per-row commission rounded half-up THEN summed (pinned order);
declared_totals must equal computed_totals exactly at submission.
"""
from decimal import Decimal
from flask import Blueprint, request

import serialize
from db import STORE, new_entity, touch, now_dt
from errors import (
    raise_err, err, ERR_INVALID_STATE, ERR_INVALID_REQUEST,
    ERR_EMPTY_BORDEREAU, ERR_BORDEREAU_PERIOD_COVERED,
    ERR_BORDEREAU_DUPLICATE_ROW, ERR_BORDEREAU_ROW_UNKNOWN_POLICY,
    ERR_BORDEREAU_ROW_MISMATCH, ERR_BORDEREAU_TOTAL_MISMATCH,
)
from middleware import require_roles, require_carrier_owner, ALL_ROLES
from response import success_object
from routes.common import get_or_404, render_list, filter_query
from routes.programs import require_program_not_terminal
from services.pricing import round_cents
from validation import get_body, req_str, req_enum, req_datetime, opt_list, opt_dict

bp = Blueprint("bordereaux", __name__)

BORDEREAU_TYPES = {"PREMIUM", "CLAIMS"}


def _validate_rows(bordereau_type, rows):
    """Structural validation only; referential and amount checks run at submit."""
    for i, r in enumerate(rows):
        if not isinstance(r, dict):
            raise err(ERR_INVALID_REQUEST, "Row %d must be an object." % i)
        if bordereau_type == "PREMIUM":
            id_field, amount_fields = "policy_id", ("written_premium_cents", "commission_cents")
        else:
            id_field, amount_fields = "claim_id", ("paid_cents", "case_reserve_cents")
        if not isinstance(r.get(id_field), str) or not r.get(id_field):
            raise err(ERR_INVALID_REQUEST, "Row %d requires a non-empty '%s'." % (i, id_field))
        for f in amount_fields:
            v = r.get(f)
            if isinstance(v, bool) or not isinstance(v, int):
                raise err(ERR_INVALID_REQUEST, "Row %d field '%s' must be an integer." % (i, f))


def compute_totals(bordereau_type, rows, commission_rate_pct):
    """PREMIUM: per-row commission = round_half_up(row written premium * rate),
    summed after rounding (pinned). CLAIMS: plain sums."""
    if bordereau_type == "PREMIUM":
        premium = 0
        commission = 0
        for r in rows:
            premium += r["written_premium_cents"]
            commission += round_cents(Decimal(r["written_premium_cents"]) * Decimal(str(commission_rate_pct)))
        return {"premium_cents": premium, "commission_cents": commission}
    paid = 0
    reserve = 0
    for r in rows:
        paid += r["paid_cents"]
        reserve += r["case_reserve_cents"]
    return {"paid_cents": paid, "reserve_cents": reserve}


@bp.post("/mga/programs/<programId>/bordereaux")
def create_bordereau(programId):
    require_roles("MGAFinance")
    program = get_or_404(STORE.programs, programId, "Program")
    body = get_body()
    bordereau_type = req_enum(body, "bordereau_type", BORDEREAU_TYPES)
    period_label = req_str(body, "period_label")
    due_date = req_datetime(body, "due_date")
    rows = opt_list(body, "rows", [])
    declared_totals = opt_dict(body, "declared_totals", None)
    _validate_rows(bordereau_type, rows)
    require_program_not_terminal(program)
    b = new_entity()
    b.update({
        "program_id": program["id"],
        "bordereau_type": bordereau_type,
        "period_label": period_label,
        "rows": [dict(r) for r in rows],
        "declared_totals": declared_totals,
        "computed_totals": compute_totals(bordereau_type, rows, program["commission_rate_pct"]),
        "row_count": len(rows),
        "due_date": due_date,
        "overdue": False,
        "status": "DRAFT",
        "rejection_reason": None,
        "submitted_at": None,
    })
    STORE.bordereaux[b["id"]] = b
    return success_object(serialize.bordereau(b), status=201)


@bp.get("/mga/programs/<programId>/bordereaux")
def list_program_bordereaux(programId):
    require_roles(*ALL_ROLES)
    get_or_404(STORE.programs, programId, "Program")
    items = filter_query(
        [b for b in STORE.bordereaux.values() if b["program_id"] == programId],
        bordereau_type=request.args.get("bordereau_type"),
        status=request.args.get("status"),
    )
    return render_list(items, serialize.bordereau)


@bp.get("/mga/bordereaux/<bordereauId>")
def get_bordereau(bordereauId):
    require_roles(*ALL_ROLES)
    b = get_or_404(STORE.bordereaux, bordereauId, "Bordereau")
    return success_object(serialize.bordereau(b))


@bp.get("/mga/bordereaux")
def list_bordereaux():
    require_roles(*ALL_ROLES)
    items = filter_query(
        list(STORE.bordereaux.values()),
        program_id=request.args.get("program_id"),
        bordereau_type=request.args.get("bordereau_type"),
        status=request.args.get("status"),
    )
    return render_list(items, serialize.bordereau)


@bp.post("/mga/bordereaux/<bordereauId>/submit")
def submit_bordereau(bordereauId):
    require_roles("MGAFinance")
    b = get_or_404(STORE.bordereaux, bordereauId, "Bordereau")
    if b["status"] != "DRAFT":
        raise_err(ERR_INVALID_STATE, "Only a DRAFT bordereau can be submitted.")
    rows = b["rows"]
    btype = b["bordereau_type"]
    # Data-quality gate, in the scaffold's pinned order.
    if len(rows) < 1:
        raise_err(ERR_EMPTY_BORDEREAU, "A bordereau may not be submitted with zero rows.")
    for o in STORE.bordereaux.values():
        if (
            o["id"] != b["id"]
            and o["program_id"] == b["program_id"]
            and o["bordereau_type"] == btype
            and o["period_label"] == b["period_label"]
            and o["status"] == "ACCEPTED"
        ):
            raise_err(ERR_BORDEREAU_PERIOD_COVERED, "An ACCEPTED bordereau already covers this program, type and period.")
    key = "policy_id" if btype == "PREMIUM" else "claim_id"
    seen = set()
    for r in rows:
        if r[key] in seen:
            raise_err(ERR_BORDEREAU_DUPLICATE_ROW, "Duplicate %s '%s' within rows." % (key, r[key]))
        seen.add(r[key])
    for r in rows:
        if btype == "PREMIUM":
            target = STORE.policies.get(r["policy_id"])
        else:
            target = STORE.claims.get(r["claim_id"])
        if target is None or target["program_id"] != b["program_id"]:
            raise_err(ERR_BORDEREAU_ROW_UNKNOWN_POLICY, "Row references an unknown or foreign %s." % key)
    for r in rows:
        if btype == "PREMIUM":
            pol = STORE.policies[r["policy_id"]]
            if r["written_premium_cents"] != pol["gross_premium_cents"] or r["commission_cents"] != pol["mga_commission_cents"]:
                raise_err(ERR_BORDEREAU_ROW_MISMATCH, "Row amounts differ from the referenced policy's current fields.")
        else:
            cl = STORE.claims[r["claim_id"]]
            if r["paid_cents"] != cl["paid_cents"] or r["case_reserve_cents"] != cl["case_reserve_cents"]:
                raise_err(ERR_BORDEREAU_ROW_MISMATCH, "Row amounts differ from the referenced claim's current fields.")
    if b["declared_totals"] is None or b["declared_totals"] != b["computed_totals"]:
        raise_err(ERR_BORDEREAU_TOTAL_MISMATCH, "declared_totals does not equal computed_totals.")
    b["status"] = "SUBMITTED"
    b["submitted_at"] = now_dt()
    touch(b)
    return success_object(serialize.bordereau(b))


@bp.post("/mga/bordereaux/<bordereauId>/accept")
def accept_bordereau(bordereauId):
    require_roles("CarrierUnderwriter")
    b = get_or_404(STORE.bordereaux, bordereauId, "Bordereau")
    program = STORE.programs[b["program_id"]]
    require_carrier_owner(program)
    if b["status"] != "SUBMITTED":
        raise_err(ERR_INVALID_STATE, "Only a SUBMITTED bordereau can be accepted.")
    b["status"] = "ACCEPTED"
    touch(b)
    # Mark the underlying records as reported to the carrier.
    if b["bordereau_type"] == "PREMIUM":
        for r in b["rows"]:
            pol = STORE.policies.get(r["policy_id"])
            if pol is not None and pol["reported_premium_bordereau_id"] != b["id"]:
                pol["reported_premium_bordereau_id"] = b["id"]
                touch(pol)
    else:
        for r in b["rows"]:
            cl = STORE.claims.get(r["claim_id"])
            if cl is not None and cl["reported_claim_bordereau_id"] != b["id"]:
                cl["reported_claim_bordereau_id"] = b["id"]
                touch(cl)
    return success_object(serialize.bordereau(b))


@bp.post("/mga/bordereaux/<bordereauId>/reject")
def reject_bordereau(bordereauId):
    require_roles("CarrierUnderwriter")
    b = get_or_404(STORE.bordereaux, bordereauId, "Bordereau")
    program = STORE.programs[b["program_id"]]
    require_carrier_owner(program)
    body = get_body()
    rejection_reason = req_str(body, "rejection_reason")
    if b["status"] != "SUBMITTED":
        raise_err(ERR_INVALID_STATE, "Only a SUBMITTED bordereau can be rejected.")
    b["status"] = "REJECTED"
    b["rejection_reason"] = rejection_reason
    touch(b)
    return success_object(serialize.bordereau(b))


@bp.post("/mga/bordereaux/<bordereauId>/revise")
def revise_bordereau(bordereauId):
    require_roles("MGAFinance")
    b = get_or_404(STORE.bordereaux, bordereauId, "Bordereau")
    if b["status"] != "REJECTED":
        raise_err(ERR_INVALID_STATE, "Only a REJECTED bordereau can be revised back to DRAFT.")
    b["status"] = "DRAFT"
    b["rejection_reason"] = None
    b["submitted_at"] = None
    touch(b)
    return success_object(serialize.bordereau(b))


@bp.post("/mga/bordereaux/<bordereauId>/cancel")
def cancel_bordereau(bordereauId):
    require_roles("MGAFinance")
    b = get_or_404(STORE.bordereaux, bordereauId, "Bordereau")
    if b["status"] != "DRAFT":
        raise_err(ERR_INVALID_STATE, "Only a DRAFT bordereau can be cancelled.")
    b["status"] = "CANCELLED"
    touch(b)
    return success_object(serialize.bordereau(b))
