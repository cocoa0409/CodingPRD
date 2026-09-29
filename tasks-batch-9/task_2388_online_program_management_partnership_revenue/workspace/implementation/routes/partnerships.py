"""Partnership contracting, settlement statement creation and computed reads."""

import copy

from flask import Blueprint, request

import constants as C
import db
import serializers
from db import bump_partnership_version, store, touch
from errors import ApiError, bad_request
from middleware import authenticate, body, check_action_role, check_scope, scope_filter
from response import object_response
from routes.common import get_partnership, listing
from services.cascades import cascade_a, performance_run
from services.derive import expiry_date, recompute_partnership
from services.money import parse_iso_date
from services.settlement import compute_statement
from validation import (Field, IPEDS_RE, enum_filter, pagination_args,
                        validate_body)

bp = Blueprint("partnerships", __name__)

READ_ALL = ("PlatformAdmin", "UniversityProvost", "UniversityBursar", "FacultyChair",
            "ComplianceAuditor", "PartnerAccountLead")
SUMMARY_ROLES = ("PlatformAdmin", "UniversityProvost", "UniversityBursar",
                 "ComplianceAuditor", "PartnerAccountLead")
LIST_ROLES = ("PlatformAdmin", "UniversityProvost", "UniversityBursar",
              "ComplianceAuditor")

REGISTER_SPEC = {
    "university_name": Field("string", required=True),
    "university_ipeds_id": Field("string", required=True, pattern=IPEDS_RE),
    "partner_org_name": Field("string", required=True),
    "contract_structure": Field("enum", required=True, enum=C.CONTRACT_STRUCTURES),
    "term_months": Field("integer", required=True, minimum=12, maximum=120),
    "effective_date": Field("date", required=True),
    "revenue_recognition_method": Field("enum", required=True, enum=C.RECOGNITION_METHODS),
    "marketing_budget_cents": Field("integer", required=True),
    "revenue_share_tiers": Field("tiers"),
    "fee_schedule_monthly_cents": Field("integer"),
    "refund_schedule": Field("bands"),
    "exclusivity_cip_codes": Field("string_array"),
    "bundled_services_exception_claimed": Field("boolean"),
}

TERMS_SPEC = {
    "expected_partnership_version": Field("integer", required=True),
    "term_months": Field("integer", minimum=12, maximum=120),
    "revenue_share_tiers": Field("tiers"),
    "marketing_budget_cents": Field("integer"),
    "refund_schedule": Field("bands"),
    "revenue_recognition_method": Field("enum", enum=C.RECOGNITION_METHODS),
    "fee_schedule_monthly_cents": Field("integer"),
}

CONTRACT_SPEC = {
    "action": Field("enum", required=True, enum=tuple(C.CONTRACT_ACTION_ROLES)),
    "change_request_note": Field("string"),
    "executed_date": Field("date"),
    "wind_down_reason": Field("string"),
    "wind_down_effective_date": Field("date"),
}

PERFORMANCE_SPEC = {
    "window_start": Field("date", required=True),
    "window_end": Field("date", required=True),
}

STATEMENT_SPEC = {
    "period_start": Field("date", required=True),
    "period_end": Field("date", required=True),
    "expected_partnership_version": Field("integer", required=True),
}

CONTRACT_TRANSITIONS = {
    "SUBMIT_FOR_REVIEW": ("DRAFT", "UNDER_REVIEW"),
    "REQUEST_CHANGES": ("UNDER_REVIEW", "DRAFT"),
    "EXECUTE": ("UNDER_REVIEW", "EXECUTED"),
    "WIND_DOWN": ("EXECUTED", "WIND_DOWN"),
    "CLOSE_OUT": ("WIND_DOWN", "CLOSED_OUT"),
}


def _check_fee_structure(structure, fee):
    if fee > 0 and structure != "FEE_FOR_SERVICE":
        raise ApiError("ERR_FEE_STRUCTURE_MISMATCH")
    if structure == "REVENUE_SHARE" and fee != 0:
        raise ApiError("ERR_FEE_STRUCTURE_MISMATCH")
    if structure == "FEE_FOR_SERVICE" and fee <= 0:
        raise ApiError("ERR_FEE_STRUCTURE_MISMATCH")


@bp.post("/partnerships")
def register():
    authenticate(("PlatformAdmin",))
    values = validate_body(body(), REGISTER_SPEC)

    structure = values["contract_structure"]
    fee = values.get("fee_schedule_monthly_cents", 0)
    if fee > 0 and structure != "FEE_FOR_SERVICE":
        raise ApiError("ERR_FEE_STRUCTURE_MISMATCH")
    if structure == "REVENUE_SHARE" and fee != 0:
        raise ApiError("ERR_FEE_STRUCTURE_MISMATCH")

    entity = db.base_entity()
    entity.update({
        "university_name": values["university_name"],
        "university_ipeds_id": values["university_ipeds_id"],
        "partner_org_name": values["partner_org_name"],
        "contract_structure": structure,
        "term_months": values["term_months"],
        "effective_date": values["effective_date"],
        "expiry_date": expiry_date(values["effective_date"], values["term_months"]),
        "status": "DRAFT",
        "revenue_share_tiers": values.get(
            "revenue_share_tiers", copy.deepcopy(C.DEFAULT_REVENUE_SHARE_TIERS)),
        "fee_schedule_monthly_cents": fee,
        "refund_schedule": values.get(
            "refund_schedule", copy.deepcopy(C.DEFAULT_REFUND_SCHEDULE)),
        "revenue_recognition_method": values["revenue_recognition_method"],
        "exclusivity_cip_codes": values.get("exclusivity_cip_codes", []),
        "bundled_services_exception_claimed": values.get(
            "bundled_services_exception_claimed", False),
        "marketing_budget_cents": values["marketing_budget_cents"],
        "marketing_budget_remaining_cents": 0,
        "unrecouped_marketing_spend_cents": 0,
        "collected_tuition_cents": 0,
        "recognized_revenue_cents": 0,
        "contract_year_recognized_cents": 0,
        "remitted_to_partner_cents": 0,
        "holdback_balance_cents": 0,
        "change_request_count": 0,
        "executed_date": None,
        "wind_down_effective_date": None,
    })
    store.partnerships[entity["id"]] = entity
    return object_response(serializers.partnership(entity), 201)


@bp.get("/partnerships/<partnership_id>")
def read(partnership_id):
    uid, role = authenticate(READ_ALL)
    entity = get_partnership(partnership_id)
    check_scope(role, uid, entity["id"])
    return object_response(serializers.partnership(entity))


@bp.get("/partnerships")
def index():
    authenticate(LIST_ROLES)
    limit, offset = pagination_args(request.args)
    status = enum_filter(request.args, "status", C.PARTNERSHIP_STATUSES)
    ipeds = request.args.get("university_ipeds_id")

    items = db.sort_created(list(store.partnerships.values()))
    if status is not None:
        items = [p for p in items if p["status"] == status]
    if ipeds is not None:
        items = [p for p in items if p["university_ipeds_id"] == ipeds]
    return listing(items, serializers.partnership, limit, offset)


@bp.patch("/partnerships/<partnership_id>/terms")
def amend_terms(partnership_id):
    uid, role = authenticate(("PartnerAccountLead",))
    values = validate_body(body(), TERMS_SPEC)
    entity = get_partnership(partnership_id)
    check_scope(role, uid, entity["id"])

    if values["expected_partnership_version"] != entity["version"]:
        raise ApiError("ERR_STALE_PARTNERSHIP_VERSION")
    if entity["status"] not in ("DRAFT", "UNDER_REVIEW", "EXECUTED"):
        raise ApiError("ERR_PARTNERSHIP_INVALID_STATE")

    structure = entity["contract_structure"]
    fee = values.get("fee_schedule_monthly_cents", entity["fee_schedule_monthly_cents"])
    if fee > 0 and structure != "FEE_FOR_SERVICE":
        raise ApiError("ERR_FEE_STRUCTURE_MISMATCH")
    if structure == "REVENUE_SHARE" and fee != 0:
        raise ApiError("ERR_FEE_STRUCTURE_MISMATCH")

    if "term_months" in values:
        entity["term_months"] = values["term_months"]
        entity["expiry_date"] = expiry_date(entity["effective_date"], entity["term_months"])
    if "revenue_share_tiers" in values:
        entity["revenue_share_tiers"] = values["revenue_share_tiers"]
    if "marketing_budget_cents" in values:
        entity["marketing_budget_cents"] = values["marketing_budget_cents"]
    if "refund_schedule" in values:
        entity["refund_schedule"] = values["refund_schedule"]
    if "revenue_recognition_method" in values:
        entity["revenue_recognition_method"] = values["revenue_recognition_method"]
    if "fee_schedule_monthly_cents" in values:
        entity["fee_schedule_monthly_cents"] = fee

    recompute_partnership(entity)
    bump_partnership_version(entity)
    return object_response(serializers.partnership(entity))


@bp.post("/partnerships/<partnership_id>/contract-actions")
def contract_action(partnership_id):
    uid, role = authenticate(("PartnerAccountLead", "UniversityProvost"))
    values = validate_body(body(), CONTRACT_SPEC)
    action = values["action"]
    check_action_role(role, action, C.CONTRACT_ACTION_ROLES)

    if action == "WIND_DOWN" and values.get("wind_down_effective_date") is None:
        raise bad_request("wind_down_effective_date is required for WIND_DOWN.")

    entity = get_partnership(partnership_id)
    check_scope(role, uid, entity["id"])

    source, target = CONTRACT_TRANSITIONS[action]
    if entity["status"] != source:
        raise ApiError("ERR_PARTNERSHIP_INVALID_STATE")

    if action == "SUBMIT_FOR_REVIEW":
        _check_fee_structure(entity["contract_structure"],
                             entity["fee_schedule_monthly_cents"])
        entity["expiry_date"] = expiry_date(entity["effective_date"], entity["term_months"])
    elif action == "REQUEST_CHANGES":
        entity["change_request_count"] += 1
    elif action == "EXECUTE":
        supplied = values.get("executed_date")
        entity["executed_date"] = supplied or db.current_date().isoformat()
    elif action == "WIND_DOWN":
        effective = parse_iso_date(values["wind_down_effective_date"])
        if effective < db.current_date():
            raise bad_request("wind_down_effective_date may not precede the current date.")
        entity["wind_down_effective_date"] = values["wind_down_effective_date"]
    elif action == "CLOSE_OUT":
        for program in db.programs_of(entity["id"]):
            if program["status"] not in ("CLOSED", "REJECTED", "DRAFT"):
                raise ApiError("ERR_TEACH_OUT_OBLIGATIONS_UNMET")
        for statement in db.statements_of(entity["id"]):
            if statement["status"] in C.OPEN_STATEMENT_STATUSES:
                raise ApiError("ERR_TEACH_OUT_OBLIGATIONS_UNMET")

    entity["status"] = target
    if action == "WIND_DOWN":
        cascade_a(entity)

    recompute_partnership(entity)
    bump_partnership_version(entity)
    return object_response(serializers.partnership(entity))


@bp.post("/partnerships/<partnership_id>/counselor-performance-runs")
def counselor_performance(partnership_id):
    uid, role = authenticate(("PartnerAccountLead", "UniversityProvost"))
    values = validate_body(body(), PERFORMANCE_SPEC)
    entity = get_partnership(partnership_id)
    check_scope(role, uid, entity["id"])
    result = performance_run(entity, values["window_start"], values["window_end"])
    return object_response(result)


@bp.post("/partnerships/<partnership_id>/remittance-statements")
def create_statement(partnership_id):
    uid, role = authenticate(("UniversityBursar",))
    values = validate_body(body(), STATEMENT_SPEC)
    entity = get_partnership(partnership_id)

    if values["expected_partnership_version"] != entity["version"]:
        raise ApiError("ERR_STALE_PARTNERSHIP_VERSION")
    if entity["status"] != "EXECUTED":
        raise ApiError("ERR_PARTNERSHIP_INVALID_STATE")

    today = db.current_date()
    if today > parse_iso_date(entity["expiry_date"]):
        raise ApiError("ERR_CONTRACT_TERM_EXPIRED")

    start = parse_iso_date(values["period_start"])
    end = parse_iso_date(values["period_end"])
    for existing in db.statements_of(entity["id"]):
        other_start = parse_iso_date(existing["period_start"])
        other_end = parse_iso_date(existing["period_end"])
        if start <= other_end and other_start <= end:
            raise ApiError("ERR_STATEMENT_PERIOD_OVERLAP")
    if not end < today:
        raise ApiError("ERR_PERIOD_NOT_ELAPSED")

    statement = db.base_entity()
    statement.update({
        "partnership_id": entity["id"],
        "period_start": values["period_start"],
        "period_end": values["period_end"],
        "status": "CALCULATED",
        "recognition_method_applied": entity["revenue_recognition_method"],
        "recognized_revenue_cents": 0,
        "share_gross_cents": 0,
        "marketing_recoupment_cents": 0,
        "subtotal_cents": 0,
        "holdback_pct": 0.0,
        "holdback_cents": 0,
        "fee_for_service_cents": 0,
        "net_payable_cents": 0,
        "line_count": 0,
        "authored_by_user_id": uid,
        "approved_by_user_id": None,
        "resolved_by_user_id": None,
        "adjustment_delta_cents": 0,
        "requires_recalculation": False,
        "dispute_reason": None,
        "remittance_reference": None,
        "remitted_at": None,
        "_lines": [],
    })
    store.statements[statement["id"]] = statement

    compute_statement(statement, entity)
    recompute_partnership(entity)
    bump_partnership_version(entity)
    return object_response(serializers.statement(statement), 201)


@bp.get("/partnerships/<partnership_id>/revenue-summary")
def revenue_summary(partnership_id):
    uid, role = authenticate(SUMMARY_ROLES)
    entity = get_partnership(partnership_id)
    check_scope(role, uid, entity["id"])
    recompute_partnership(entity)

    statements = db.statements_of(entity["id"])
    open_count = sum(1 for s in statements if s["status"] in C.OPEN_STATEMENT_STATUSES)
    return object_response({
        "collected_tuition_cents": entity["collected_tuition_cents"],
        "recognized_revenue_cents": entity["recognized_revenue_cents"],
        "remitted_to_partner_cents": entity["remitted_to_partner_cents"],
        "holdback_balance_cents": entity["holdback_balance_cents"],
        "unrecouped_marketing_spend_cents": entity["unrecouped_marketing_spend_cents"],
        "marketing_budget_remaining_cents": entity["marketing_budget_remaining_cents"],
        "open_statement_count": open_count,
        "program_count": len(db.programs_of(entity["id"])),
    })
