"""ParametricPolicy endpoints (PRD §3.5): quote, list, bind, cancel."""

from datetime import date

from flask import Blueprint, request

import db
from errors import (
    err, ERR_INVALID_REQUEST, ERR_CROSS_REFERENCE_INVALID, ERR_POLICY_NOT_QUOTED,
    ERR_HOLDER_NOT_ACTIVE_FOR_BIND, ERR_PROGRAM_NOT_ACTIVE, ERR_INDEX_NOT_ACTIVE,
    ERR_PREMIUM_NOT_PAID, ERR_EXPOSURE_LIMIT_EXCEEDED, ERR_POLICY_NOT_BOUND,
    ERR_POLICY_HAS_CLAIMS, ERR_POLICY_PAYMENT_IN_FLIGHT, ERR_POLICY_NOT_FOUND,
)
from middleware import require_roles, ALL_ROLES
from response import success_object, success_list
from routes.common import (
    body, require_fields, pagination_params, paginate, sorted_by_created,
    get_program, get_holder_in_program, get_policy_of_holder,
)
from services import domain, calc

bp = Blueprint("policies", __name__)


def _validate_iso_date(value, field):
    if not isinstance(value, str):
        raise err(ERR_INVALID_REQUEST, 400, f"{field} must be a YYYY-MM-DD string")
    try:
        return date.fromisoformat(value)
    except ValueError:
        raise err(ERR_INVALID_REQUEST, 400, f"{field} must be YYYY-MM-DD")


@bp.post("/programs/<programId>/policyholders/<holderId>/policies")
def quote_policy(programId, holderId):
    require_roles("Underwriter")
    prog = get_program(programId)
    holder = get_holder_in_program(prog, holderId)
    data = body()
    require_fields(data, ["index_definition_id", "sum_insured_cents",
                          "policy_start_date", "policy_end_date"])
    start = _validate_iso_date(data["policy_start_date"], "policy_start_date")
    end = _validate_iso_date(data["policy_end_date"], "policy_end_date")
    if end <= start:
        raise err(ERR_INVALID_REQUEST, 400, "policy_end_date must be > policy_start_date")
    if not isinstance(data["sum_insured_cents"], int) or data["sum_insured_cents"] <= 0:
        raise err(ERR_INVALID_REQUEST, 400, "sum_insured_cents must be a positive integer")

    # Cross-reference: index must exist and belong to this program (priority 7)
    idx = db.index_definitions.get(data["index_definition_id"])
    if not idx or idx["program_id"] != prog["id"]:
        raise err(ERR_CROSS_REFERENCE_INVALID, 422,
                  "Referenced index belongs to a different program")

    premium_cents, premium_tax_cents = calc.premium_pricing(
        data["sum_insured_cents"], idx, prog["regulatory_classification"]
    )

    pol = domain.stamp_new({
        "policyholder_id": holder["id"],
        "program_id": prog["id"],
        "index_definition_id": idx["id"],
        "sum_insured_cents": data["sum_insured_cents"],
        "policy_start_date": data["policy_start_date"],
        "policy_end_date": data["policy_end_date"],
        "premium_cents": premium_cents,
        "premium_tax_cents": premium_tax_cents,
        "lifecycle_status": "QUOTED",
        "settlement_posture": "CLEAR",
    })
    db.policies[pol["id"]] = pol

    # Quotation simultaneously issues the premium invoice (PRD §3.5)
    inv = domain.stamp_new({
        "policy_id": pol["id"],
        "invoice_amount_cents": premium_cents + premium_tax_cents,
        "amount_paid_cents": 0,
        "due_date": data["policy_start_date"],
        "status": "ISSUED",
    })
    db.invoices[inv["id"]] = inv

    return success_object(domain.serialize(pol), 201)


@bp.get("/programs/<programId>/policyholders/<holderId>/policies")
def list_policies_of_holder(programId, holderId):
    require_roles(*ALL_ROLES)
    domain.run_expiry_sweep()
    prog = get_program(programId)
    holder = get_holder_in_program(prog, holderId)
    limit, offset = pagination_params()
    items = sorted_by_created(
        p for p in db.policies.values() if p["policyholder_id"] == holder["id"]
    )
    page, total = paginate(items, limit, offset)
    return success_list(domain.serialize_list(page), limit, offset, total)


@bp.get("/programs/<programId>/policyholders/<holderId>/policies/<policyId>")
def get_policy(programId, holderId, policyId):
    require_roles(*ALL_ROLES)
    domain.run_expiry_sweep()
    prog = get_program(programId)
    holder = get_holder_in_program(prog, holderId)
    pol = get_policy_of_holder(holder, policyId)
    return success_object(domain.serialize(pol))


@bp.post("/programs/<programId>/policyholders/<holderId>/policies/<policyId>/bind")
def bind_policy(programId, holderId, policyId):
    require_roles("Underwriter")
    domain.run_expiry_sweep()
    prog = get_program(programId)
    holder = get_holder_in_program(prog, holderId)
    pol = get_policy_of_holder(holder, policyId)

    # Priority 4: parent program must be ACTIVE
    if prog["status"] != "ACTIVE":
        raise err(ERR_PROGRAM_NOT_ACTIVE, 409, "Operation requires program status ACTIVE")
    # Priority 5: state guards
    if pol["lifecycle_status"] != "QUOTED":
        raise err(ERR_POLICY_NOT_QUOTED, 409, "Bind requires lifecycle_status QUOTED")
    if holder["status"] != "ACTIVE":
        raise err(ERR_HOLDER_NOT_ACTIVE_FOR_BIND, 409,
                  "Policy bind requires policyholder status ACTIVE")
    idx = db.index_definitions.get(pol["index_definition_id"])
    if not idx or idx["status"] != "ACTIVE":
        raise err(ERR_INDEX_NOT_ACTIVE, 409, "Operation requires index status ACTIVE")

    # Fiscal gates: premium paid, exposure headroom
    inv = next((i for i in db.invoices.values() if i["policy_id"] == pol["id"]), None)
    if not inv or inv["status"] != "PAID":
        raise err(ERR_PREMIUM_NOT_PAID, 402,
                  "Bind requires the policy's PremiumInvoice to be PAID")

    # Exposure: simulate binding this policy, check headroom (PRD §3.5/§3.9)
    active_treaties = [t for t in db.treaties.values()
                       if t["program_id"] == prog["id"] and t["status"] == "ACTIVE"]
    from decimal import Decimal
    total_ceded_pct = min(Decimal("100"), sum(
        (calc._D(t["ceded_percentage"]) for t in active_treaties), Decimal("0")
    ))
    bound = sorted(
        (p for p in db.policies.values()
         if p["program_id"] == prog["id"] and p["lifecycle_status"] == "BOUND"),
        key=lambda p: p["created_at"],
    )
    retained = 0
    for p in bound:
        share = calc.round_half_up_cents(calc._D(p["sum_insured_cents"]) * total_ceded_pct / Decimal("100"))
        retained += int(p["sum_insured_cents"]) - share
    new_share = calc.round_half_up_cents(calc._D(pol["sum_insured_cents"]) * total_ceded_pct / Decimal("100"))
    retained_after = retained + (int(pol["sum_insured_cents"]) - new_share)
    if retained_after > int(prog["exposure_limit_cents"]):
        raise err(ERR_EXPOSURE_LIMIT_EXCEEDED, 402,
                  "Binding would push net_retained_exposure_cents above exposure_limit_cents")

    pol["lifecycle_status"] = "BOUND"
    domain.touch(pol)
    prog["gross_written_premium_cents"] = int(prog["gross_written_premium_cents"]) + int(pol["premium_cents"])
    calc.recompute_net_retained_exposure(prog)
    domain.touch(prog)
    return success_object(domain.serialize(pol))


@bp.post("/programs/<programId>/policyholders/<holderId>/policies/<policyId>/cancel")
def cancel_policy(programId, holderId, policyId):
    require_roles("Underwriter")
    domain.run_expiry_sweep()
    prog = get_program(programId)
    holder = get_holder_in_program(prog, holderId)
    pol = get_policy_of_holder(holder, policyId)

    if pol["lifecycle_status"] != "BOUND":
        raise err(ERR_POLICY_NOT_BOUND, 409, "Operation requires lifecycle_status BOUND")
    if pol["settlement_posture"] == "PAYMENT_PENDING":
        raise err(ERR_POLICY_PAYMENT_IN_FLIGHT, 409,
                  "Cancel blocked: settlement_posture PAYMENT_PENDING")
    for c in db.claims.values():
        if c["policy_id"] == pol["id"] and c["status"] in (
            "GENERATED", "ADJUSTED", "APPROVED", "FRAUD_HOLD", "PAID"
        ):
            raise err(ERR_POLICY_HAS_CLAIMS, 409,
                      "Cancel blocked: policy has claims in non-terminal states or PAID")

    pol["lifecycle_status"] = "CANCELLED"
    domain.touch(pol)
    calc.recompute_net_retained_exposure(prog)
    domain.touch(prog)
    return success_object(domain.serialize(pol))


# --- Program-scoped and flat filtered lists ---

@bp.get("/programs/<programId>/policies")
def list_policies_in_program(programId):
    require_roles(*ALL_ROLES)
    domain.run_expiry_sweep()
    prog = get_program(programId)
    limit, offset = pagination_params()
    items = [p for p in db.policies.values() if p["program_id"] == prog["id"]]
    items = _apply_policy_filters(items)
    items = sorted_by_created(items)
    page, total = paginate(items, limit, offset)
    return success_list(domain.serialize_list(page), limit, offset, total)


@bp.get("/programs/policies")
def list_policies_flat():
    require_roles(*ALL_ROLES)
    domain.run_expiry_sweep()
    limit, offset = pagination_params()
    items = list(db.policies.values())
    items = _apply_policy_filters(items)
    items = sorted_by_created(items)
    page, total = paginate(items, limit, offset)
    return success_list(domain.serialize_list(page), limit, offset, total)


def _apply_policy_filters(items):
    iid = request.args.get("index_definition_id")
    hid = request.args.get("policyholder_id")
    pid = request.args.get("program_id")
    lst = request.args.get("lifecycle_status")
    if iid is not None:
        items = [p for p in items if p["index_definition_id"] == iid]
    if hid is not None:
        items = [p for p in items if p["policyholder_id"] == hid]
    if pid is not None:
        items = [p for p in items if p["program_id"] == pid]
    if lst is not None:
        items = [p for p in items if p["lifecycle_status"] == lst]
    return items


@bp.get("/programs/policies/<policyId>")
def get_policy_flat(policyId):
    require_roles(*ALL_ROLES)
    domain.run_expiry_sweep()
    pol = db.policies.get(policyId)
    if not pol:
        raise err(ERR_POLICY_NOT_FOUND, 404, "Policy id does not exist")
    return success_object(domain.serialize(pol))
