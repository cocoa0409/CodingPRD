"""Expenditure endpoints: charging, allowable-cost review, reclassification."""

from flask import Blueprint

import db
import errors
import middleware
import response
import validators as V
from routes.allocations import get_allocation_or_404
from routes.grants import get_grant_or_404
from routes.set_asides import get_set_aside_or_404
from services import calc, serializers, workflows

bp = Blueprint("expenditures", __name__)

ALL_ROLES = middleware.ROLES
FUNCTION_CODES = {"INSTRUCTION", "PD", "PARENT_ENGAGEMENT", "HOMELESS_SUPPORT", "EQUITABLE_SERVICES"}
# disallow reasons a client may supply; SNS_STALE_CASCADE is system-reserved.
CLIENT_DISALLOW_REASONS = {"SUPPLANT_RISK", "UNALLOWABLE_COST", "INSUFFICIENT_DOCUMENTATION"}
FUND_SOURCES = {"NON_TITLE_I_STATE", "NON_TITLE_I_LOCAL"}

# function_code required for each set-aside category
CATEGORY_FUNCTION = {
    "PROFESSIONAL_DEVELOPMENT": "PD",
    "PARENT_ENGAGEMENT": "PARENT_ENGAGEMENT",
    "HOMELESS_SERVICES": "HOMELESS_SUPPORT",
    "EQUITABLE_SERVICES": "EQUITABLE_SERVICES",
}


def get_expenditure_or_404(exp_id):
    exp = db.expenditures.get(exp_id)
    if exp is None:
        errors.fail(errors.ERR_NOT_FOUND, "Expenditure %s does not exist." % exp_id)
    return exp


@bp.post("/expenditures")
def create_expenditure():
    uid, role = middleware.current_user()
    middleware.require_role(role, {"ComplianceAnalyst"})
    data = V.json_body()
    # Tier 3: body FK existence in declared order.
    grant_ref = data.get("grant_id")
    if grant_ref is not None and isinstance(grant_ref, str):
        get_grant_or_404(grant_ref)
    alloc_ref = data.get("school_allocation_id")
    if alloc_ref is not None and isinstance(alloc_ref, str):
        get_allocation_or_404(alloc_ref)
    sa_ref = data.get("set_aside_id")
    if sa_ref is not None and isinstance(sa_ref, str):
        get_set_aside_or_404(sa_ref)
    # Tier 4: schema.
    V.check_unknown(data, {
        "grant_id", "school_allocation_id", "set_aside_id", "amount_cents",
        "function_code", "description", "incurred_date", "supplant_screen",
    })
    grant_id = V.req_str(data, "grant_id")
    grant = get_grant_or_404(grant_id)
    alloc_id = data.get("school_allocation_id")
    sa_id = data.get("set_aside_id")
    if alloc_id is not None and not isinstance(alloc_id, str):
        errors.fail(errors.ERR_INVALID_REQUEST, "school_allocation_id must be a string.")
    if sa_id is not None and not isinstance(sa_id, str):
        errors.fail(errors.ERR_INVALID_REQUEST, "set_aside_id must be a string.")
    amount = V.req_int(data, "amount_cents")
    if amount <= 0:
        errors.fail(errors.ERR_INVALID_REQUEST, "amount_cents must be > 0.")
    function_code = V.req_enum(data, "function_code", FUNCTION_CODES)
    V.req_str(data, "description")
    incurred_raw = V.req_str(data, "incurred_date")
    incurred = V.parse_date(incurred_raw, "incurred_date")
    supplant_screen = V.opt_bool(data, "supplant_screen", False)
    # Tier 9: charge-target consistency — exactly one target, belonging to the
    # grant, with a matching function code.
    if (alloc_id is None) == (sa_id is None):
        errors.fail(
            errors.ERR_CHARGE_TARGET_AMBIGUOUS,
            "Exactly one of school_allocation_id / set_aside_id must be named.",
        )
    alloc = None
    sa = None
    if alloc_id is not None:
        alloc = get_allocation_or_404(alloc_id)
        if alloc["grant_id"] != grant["id"]:
            errors.fail(
                errors.ERR_NOT_FOUND,
                "Charge target is not resolvable within grant %s." % grant["id"],
            )
        if function_code != "INSTRUCTION":
            errors.fail(
                errors.ERR_FUNCTION_TARGET_MISMATCH,
                "Charges against a school allocation must use function_code INSTRUCTION.",
            )
    else:
        sa = get_set_aside_or_404(sa_id)
        if sa["grant_id"] != grant["id"]:
            errors.fail(
                errors.ERR_NOT_FOUND,
                "Charge target is not resolvable within grant %s." % grant["id"],
            )
        if function_code != CATEGORY_FUNCTION[sa["category"]]:
            errors.fail(
                errors.ERR_FUNCTION_TARGET_MISMATCH,
                "function_code does not match the set-aside category.",
            )
    # Tier 8: supplement-not-supplant gate.
    if supplant_screen:
        ok = alloc is not None and any(
            d for d in db.sns_docs.values()
            if d["school_allocation_id"] == alloc["id"] and d["status"] == "ACCEPTED"
        )
        if not ok:
            errors.fail(
                errors.ERR_SUPPLANT_RISK_UNRESOLVED,
                "supplant_screen=true requires an ACCEPTED SNS document for the charged allocation.",
            )
    # Tier 10: funds-period bound.
    period_start, period_end = calc.funds_period(grant["fiscal_year"])
    if not (period_start <= incurred <= period_end):
        errors.fail(
            errors.ERR_COST_OUTSIDE_FISCAL_PERIOD,
            "incurred_date is outside the grant's funds period.",
        )
    # Tier 11: remaining-balance check (HTTP 402).
    if alloc is not None:
        remaining = (
            alloc["allocation_amount_cents"] - alloc["liquidated_cents"] - alloc["pending_cents"]
        )
    else:
        remaining = (
            sa["reserved_cents"] - sa["liquidated_cents"]
            - workflows.set_aside_pending_cents(sa["id"])
        )
    if amount > remaining:
        errors.fail(
            errors.ERR_INSUFFICIENT_ALLOCATION_BALANCE,
            "Charge exceeds the target's remaining balance.",
        )
    exp = db.init_common({
        "grant_id": grant["id"],
        "school_allocation_id": alloc_id,
        "set_aside_id": sa_id,
        "amount_cents": amount,
        "function_code": function_code,
        "description": data["description"],
        "incurred_date": incurred_raw,
        "supplant_screen": supplant_screen,
        "status": "PENDING_REVIEW",
        "submitted_by_user_id": uid,
        "reviewed_by_user_id": None,
        "review_note": None,
        "disallow_reason": None,
        "reclassified_to_fund_source": None,
    })
    db.expenditures[exp["id"]] = exp
    # Immediate ledger aggregation; the grant row mutated, so its version advances.
    for changed in workflows.recompute_ledgers(grant):
        db.touch(changed)
    db.touch(grant)
    return response.success_object(serializers.expenditure_view(exp), 201)


@bp.get("/expenditures")
def list_expenditures():
    _uid, role = middleware.current_user()
    middleware.require_role(role, ALL_ROLES)
    filters = [
        ("grant_id", V.query_filter("grant_id")),
        ("school_allocation_id", V.query_filter("school_allocation_id")),
        ("set_aside_id", V.query_filter("set_aside_id")),
        ("status", V.query_filter("status")),
    ]
    page, limit, offset, total = V.sorted_page(list(db.expenditures.values()), filters)
    return response.success_list(
        [serializers.expenditure_view(e) for e in page], limit, offset, total
    )


@bp.get("/expenditures/<exp_id>")
def get_expenditure(exp_id):
    _uid, role = middleware.current_user()
    middleware.require_role(role, ALL_ROLES)
    return response.success_object(serializers.expenditure_view(get_expenditure_or_404(exp_id)))


@bp.post("/expenditures/<exp_id>/review")
def review_expenditure(exp_id):
    uid, role = middleware.current_user()
    middleware.require_role(role, {"FederalProgramsDirector"})
    exp = get_expenditure_or_404(exp_id)
    data = V.json_body()
    V.check_unknown(data, {"decision", "review_note", "disallow_reason"})
    decision = V.req_enum(data, "decision", {"ALLOW", "DISALLOW"})
    review_note = V.opt_str(data, "review_note")
    disallow_reason = data.get("disallow_reason")
    if disallow_reason is not None and disallow_reason not in CLIENT_DISALLOW_REASONS:
        errors.fail(
            errors.ERR_INVALID_REQUEST,
            "disallow_reason must be one of SUPPLANT_RISK, UNALLOWABLE_COST, INSUFFICIENT_DOCUMENTATION.",
        )
    if decision == "DISALLOW" and disallow_reason is None:
        errors.fail(errors.ERR_INVALID_REQUEST, "disallow_reason is required when decision is DISALLOW.")
    # Tier 5: expenditure state, then grant state.
    if exp["status"] != "PENDING_REVIEW":
        errors.fail(
            errors.ERR_EXPENDITURE_NOT_REVIEWABLE,
            "Expenditure in status %s cannot be reviewed." % exp["status"],
        )
    grant = db.grants[exp["grant_id"]]
    if grant["status"] != "ALLOCATED":
        errors.fail(
            errors.ERR_GRANT_INVALID_STATE,
            "Allowable-cost review requires the grant to be ALLOCATED.",
        )
    # Tier 7: segregation of duties against the filer.
    if uid == exp["submitted_by_user_id"]:
        errors.fail(
            errors.ERR_SEGREGATION_OF_DUTIES,
            "The reviewer must differ from the expenditure's submitter.",
        )
    exp["reviewed_by_user_id"] = uid
    exp["review_note"] = review_note
    if decision == "ALLOW":
        exp["status"] = "ALLOWED"
    else:
        exp["status"] = "DISALLOWED"
        exp["disallow_reason"] = disallow_reason
    db.touch(exp)
    for changed in workflows.recompute_ledgers(grant):
        db.touch(changed)
    db.touch(grant)
    return response.success_object(serializers.expenditure_view(exp))


@bp.post("/expenditures/<exp_id>/reclassify")
def reclassify_expenditure(exp_id):
    _uid, role = middleware.current_user()
    middleware.require_role(role, {"ComplianceAnalyst"})
    exp = get_expenditure_or_404(exp_id)
    data = V.json_body()
    V.check_unknown(data, {"reclassified_to_fund_source"})
    fund_source = V.req_enum(data, "reclassified_to_fund_source", FUND_SOURCES)
    if exp["status"] != "DISALLOWED":
        errors.fail(
            errors.ERR_EXPENDITURE_NOT_RECLASSIFIABLE,
            "Only a DISALLOWED expenditure may be reclassified.",
        )
    # Compensating bookkeeping: liquidated totals already exclude the charge.
    exp["status"] = "RECLASSIFIED"
    exp["reclassified_to_fund_source"] = fund_source
    db.touch(exp)
    return response.success_object(serializers.expenditure_view(exp))
