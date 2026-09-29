"""Benefit plans, fee schedules, providers, contracts and edit rules (PRD 3.1)."""

from datetime import timedelta

from flask import Blueprint, request

from auth import ALL_OPERATORS, endpoint
from envelope import created, ok
from errors import ApiError
from routes.common import filter_equals, render_list, resolve
from serializers import dump
from store import db, parse_date
from validators import (
    body,
    check_interval,
    read_date,
    read_enum,
    read_int,
    read_number,
    read_string,
    require_fields,
)

bp = Blueprint("config", __name__)

CONTRACT_GAP_DAYS = 1


# --------------------------------------------------------------------------
# BenefitPlan
# --------------------------------------------------------------------------
@bp.post("/adjudication/benefit-plans")
@endpoint(["PlanAdmin"])
def create_benefit_plan():
    payload = body()
    require_fields(
        payload,
        [
            "plan_code",
            "name",
            "deductible_individual_cents",
            "oop_max_individual_cents",
            "coinsurance_member_pct",
        ],
    )
    plan = {
        "plan_code": read_string(payload, "plan_code", required=True),
        "name": read_string(payload, "name", required=True),
        "plan_year_start_date": read_date(payload, "plan_year_start_date", "2026-01-01"),
        "deductible_individual_cents": read_int(
            payload, "deductible_individual_cents", minimum=0, required=True
        ),
        "oop_max_individual_cents": read_int(
            payload, "oop_max_individual_cents", minimum=0, required=True
        ),
        "coinsurance_member_pct": read_number(
            payload, "coinsurance_member_pct", minimum=0, maximum=1, required=True
        ),
        "copay_office_visit_cents": read_int(
            payload, "copay_office_visit_cents", 2500, minimum=0
        ),
        "out_of_network_penalty_pct": read_number(
            payload, "out_of_network_penalty_pct", 0.30, minimum=0, maximum=1
        ),
        "timely_filing_days": read_int(payload, "timely_filing_days", 90, minimum=1),
        "cob_method": read_enum(
            payload, "cob_method", ("COME_OUT_WHOLE", "NON_DUPLICATION"), "COME_OUT_WHOLE"
        ),
    }
    return created(dump("benefit_plan", db.insert("benefit_plans", plan)))


@bp.get("/adjudication/benefit-plans/<plan_id>")
@endpoint(ALL_OPERATORS)
def get_benefit_plan(plan_id):
    plan = resolve("benefit_plans", plan_id, "ERR_PLAN_NOT_FOUND")
    return ok(dump("benefit_plan", plan))


# --------------------------------------------------------------------------
# FeeScheduleRate
# --------------------------------------------------------------------------
@bp.post("/adjudication/benefit-plans/<plan_id>/fee-schedule-rates")
@endpoint(["NetworkManager", "PlanAdmin"])
def publish_fee_rate(plan_id):
    plan = resolve("benefit_plans", plan_id, "ERR_PLAN_NOT_FOUND")
    payload = body()
    require_fields(payload, ["procedure_code", "allowed_amount_cents", "effective_date"])
    procedure_code = read_string(payload, "procedure_code", required=True)
    allowed_amount_cents = read_int(payload, "allowed_amount_cents", minimum=0, required=True)
    effective_date = read_date(payload, "effective_date", required=True)
    for rate in db.values("fee_schedule_rates"):
        if (
            rate["plan_id"] == plan["id"]
            and rate["procedure_code"] == procedure_code
            and rate["effective_date"] == effective_date
        ):
            raise ApiError("ERR_DUPLICATE_FEE_RATE")
    row = db.insert(
        "fee_schedule_rates",
        {
            "plan_id": plan["id"],
            "procedure_code": procedure_code,
            "allowed_amount_cents": allowed_amount_cents,
            "effective_date": effective_date,
        },
    )
    return created(dump("fee_schedule_rate", row))


@bp.get("/adjudication/benefit-plans/<plan_id>/fee-schedule-rates")
@endpoint(ALL_OPERATORS)
def list_fee_rates(plan_id):
    plan = resolve("benefit_plans", plan_id, "ERR_PLAN_NOT_FOUND")
    rows = [r for r in db.values("fee_schedule_rates") if r["plan_id"] == plan["id"]]
    rows = filter_equals(rows, "procedure_code", request.args.get("procedure_code"))
    return render_list("fee_schedule_rate", rows)


# --------------------------------------------------------------------------
# Provider
# --------------------------------------------------------------------------
@bp.post("/adjudication/providers")
@endpoint(["PlanAdmin", "NetworkManager"])
def create_provider():
    payload = body()
    require_fields(payload, ["npi", "name", "network_status"])
    provider = {
        "npi": read_string(payload, "npi", required=True),
        "name": read_string(payload, "name", required=True),
        "network_status": read_enum(
            payload, "network_status", ("IN_NETWORK", "OUT_OF_NETWORK"), required=True
        ),
        "specialty_code": read_string(payload, "specialty_code", "GEN"),
    }
    return created(dump("provider", db.insert("providers", provider)))


@bp.get("/adjudication/providers/<provider_id>")
@endpoint(ALL_OPERATORS)
def get_provider(provider_id):
    provider = resolve("providers", provider_id, "ERR_PROVIDER_NOT_FOUND")
    return ok(dump("provider", provider))


# --------------------------------------------------------------------------
# ProviderContract
# --------------------------------------------------------------------------
@bp.post("/adjudication/contracts")
@endpoint(["NetworkManager"])
def draft_contract():
    payload = body()
    # Body foreign keys resolve before request-body shape validation.
    if payload.get("provider_id") is not None:
        resolve("providers", payload["provider_id"], "ERR_PROVIDER_NOT_FOUND")
    if payload.get("plan_id") is not None:
        resolve("benefit_plans", payload["plan_id"], "ERR_PLAN_NOT_FOUND")
    require_fields(
        payload, ["provider_id", "plan_id", "effective_date", "term_date", "pricing_method"]
    )
    provider_id = read_string(payload, "provider_id", required=True)
    plan_id = read_string(payload, "plan_id", required=True)
    effective_date = read_date(payload, "effective_date", required=True)
    term_date = read_date(payload, "term_date", required=True)
    check_interval("term_date", effective_date, term_date)
    pricing_method = read_enum(
        payload, "pricing_method", ("PCT_OF_FEE_SCHEDULE", "CASE_RATE"), required=True
    )
    contract_pct = read_number(payload, "contract_pct", exclusive_minimum=0, maximum=5)
    case_rate_cents = read_int(payload, "case_rate_cents", minimum=0)
    if pricing_method == "PCT_OF_FEE_SCHEDULE" and contract_pct is None:
        raise ApiError("ERR_INVALID_FIELD_VALUE", "contract_pct is required for PCT_OF_FEE_SCHEDULE.")
    if pricing_method == "CASE_RATE" and case_rate_cents is None:
        raise ApiError("ERR_INVALID_FIELD_VALUE", "case_rate_cents is required for CASE_RATE.")

    _check_contract_window(provider_id, plan_id, effective_date, term_date)

    contract = {
        "provider_id": provider_id,
        "plan_id": plan_id,
        "effective_date": effective_date,
        "term_date": term_date,
        "pricing_method": pricing_method,
        "contract_pct": contract_pct,
        "case_rate_cents": case_rate_cents,
        "status": "DRAFT",
    }
    return created(dump("provider_contract", db.insert("provider_contracts", contract)))


def _check_contract_window(provider_id, plan_id, effective_date, term_date):
    """At least one full clear calendar day between windows; adjacency conflicts."""
    new_start = parse_date(effective_date)
    new_end = parse_date(term_date)
    gap = timedelta(days=CONTRACT_GAP_DAYS + 1)
    for existing in db.values("provider_contracts"):
        if existing["provider_id"] != provider_id or existing["plan_id"] != plan_id:
            continue
        if existing["status"] == "TERMINATED":
            continue
        old_start = parse_date(existing["effective_date"])
        old_end = parse_date(existing["term_date"])
        separated = new_start >= old_end + gap or new_end + gap <= old_start
        if not separated:
            raise ApiError("ERR_CONTRACT_WINDOW_CONFLICT")


@bp.get("/adjudication/contracts/<contract_id>")
@endpoint(ALL_OPERATORS)
def get_contract(contract_id):
    contract = resolve("provider_contracts", contract_id, "ERR_CONTRACT_NOT_FOUND")
    return ok(dump("provider_contract", contract))


@bp.get("/adjudication/contracts")
@endpoint(ALL_OPERATORS)
def list_contracts():
    rows = db.values("provider_contracts")
    rows = filter_equals(rows, "provider_id", request.args.get("provider_id"))
    rows = filter_equals(rows, "plan_id", request.args.get("plan_id"))
    rows = filter_equals(rows, "status", request.args.get("status"))
    return render_list("provider_contract", rows)


@bp.post("/adjudication/contracts/<contract_id>/activate")
@endpoint(["NetworkManager"])
def activate_contract(contract_id):
    contract = resolve("provider_contracts", contract_id, "ERR_CONTRACT_NOT_FOUND")
    if contract["status"] != "DRAFT":
        raise ApiError("ERR_CONTRACT_NOT_DRAFT")
    if contract["pricing_method"] == "PCT_OF_FEE_SCHEDULE" and contract["contract_pct"] is None:
        raise ApiError("ERR_INVALID_FIELD_VALUE", "contract_pct must be populated to activate.")
    if contract["pricing_method"] == "CASE_RATE" and contract["case_rate_cents"] is None:
        raise ApiError("ERR_INVALID_FIELD_VALUE", "case_rate_cents must be populated to activate.")
    contract["status"] = "ACTIVE"
    db.touch(contract)
    return ok(dump("provider_contract", contract))


@bp.post("/adjudication/contracts/<contract_id>/terminate")
@endpoint(["NetworkManager"])
def terminate_contract(contract_id):
    contract = resolve("provider_contracts", contract_id, "ERR_CONTRACT_NOT_FOUND")
    payload = body()
    require_fields(payload, ["term_date"])
    term_date = read_date(payload, "term_date", required=True)
    if contract["status"] != "ACTIVE":
        raise ApiError("ERR_CONTRACT_NOT_ACTIVE")
    contract["status"] = "TERMINATED"
    contract["term_date"] = term_date
    db.touch(contract)
    return ok(dump("provider_contract", contract))


# --------------------------------------------------------------------------
# EditRule
# --------------------------------------------------------------------------
@bp.post("/adjudication/edit-rules")
@endpoint(["PlanAdmin", "MedicalDirector"])
def create_edit_rule():
    payload = body()
    require_fields(
        payload, ["rule_code", "edit_type", "primary_code", "severity", "precedence_rank", "reason_code"]
    )
    edit_type = read_enum(
        payload,
        "edit_type",
        ("BUNDLING", "MUTUALLY_EXCLUSIVE", "UNITS_LIMIT", "AUTH_REQUIRED"),
        required=True,
    )
    rule = {
        "rule_code": read_string(payload, "rule_code", required=True),
        "edit_type": edit_type,
        "primary_code": read_string(payload, "primary_code", required=True),
        "secondary_code": read_string(payload, "secondary_code"),
        "max_units": read_int(payload, "max_units", minimum=1),
        "severity": read_enum(payload, "severity", ("DENY", "PEND", "INFORM"), required=True),
        "precedence_rank": read_int(payload, "precedence_rank", minimum=1, required=True),
        "reason_code": read_string(payload, "reason_code", required=True),
    }
    if edit_type in ("BUNDLING", "MUTUALLY_EXCLUSIVE") and rule["secondary_code"] is None:
        raise ApiError("ERR_INVALID_FIELD_VALUE", "secondary_code is required for this edit_type.")
    if edit_type == "UNITS_LIMIT" and rule["max_units"] is None:
        raise ApiError("ERR_INVALID_FIELD_VALUE", "max_units is required for UNITS_LIMIT.")
    return created(dump("edit_rule", db.insert("edit_rules", rule)))
