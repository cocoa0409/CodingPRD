"""Pro forma capital schedules on two bases (PRD 3.3)."""
from flask import Blueprint

import calc
from db import db, new_record, serialize, set_fields, touch
from errors import ApiError
from helpers import (
    check_application_version,
    ensure_application_filer,
    fetch,
    fetch_fk,
    list_and_respond,
    require_usd,
)
from middleware import (
    READ_ROLES_NO_COMMENTER,
    ROLE_ANALYST,
    ROLE_FILER,
    get_body,
    req_enum,
    req_int,
    req_str,
    require_roles,
)
from response import object_response

schedules_bp = Blueprint("schedules", __name__)

BASES = ("REGULATORY_ADJUSTED", "INTERNAL_STRESS")
ADJUSTMENT_FIELDS = (
    "goodwill_created_usd",
    "core_deposit_intangible_usd",
    "aoci_markdown_usd",
    "deferred_tax_asset_usd",
    "transaction_costs_usd",
    "cash_consideration_usd",
)


@schedules_bp.post("/pro-forma-schedules")
@require_roles(ROLE_FILER, ROLE_ANALYST)
def create_schedule():
    body = get_body(required=True)
    application_id = req_str(body, "application_id")
    expected_version = req_int(body, "expected_application_version", minimum=0)
    basis = req_enum(body, "basis", BASES)
    adjustments = {field: require_usd(body, field) for field in ADJUSTMENT_FIELDS}

    application = fetch_fk("applications", application_id)
    ensure_application_filer(application)
    check_application_version(application, expected_version)

    acquirer = db.institutions.get(application["acquirer_id"])
    target = db.institutions.get(application["target_id"])
    if acquirer is None or target is None:
        raise ApiError("ERR_INSTITUTION_NOT_FOUND", "a party of the application is unknown")
    for institution in (acquirer, target):
        if (
            int(institution["risk_weighted_assets_usd"]) == 0
            or int(institution["average_total_assets_usd"]) == 0
        ):
            raise ApiError(
                "ERR_CAPITAL_DATA_MISSING",
                "both institutions must report risk-weighted assets and average total assets",
            )

    fields = {"application_id": application["id"], "basis": basis}
    fields.update(adjustments)
    fields.update(
        {
            "pro_forma_cet1_ratio_pct": 0.00,
            "pro_forma_tier1_leverage_pct": 0.00,
            "capital_adequacy_flag": "UNDERCAPITALIZED",
            "status": "CURRENT",
        }
    )
    record = new_record(fields)
    cet1_pct, leverage_pct, flag = calc.pro_forma_ratios(basis, acquirer, target, record)
    record["pro_forma_cet1_ratio_pct"] = cet1_pct
    record["pro_forma_tier1_leverage_pct"] = leverage_pct
    record["capital_adequacy_flag"] = flag

    for existing in list(db.schedules.values()):
        if (
            existing["application_id"] == application["id"]
            and existing["basis"] == basis
            and existing["status"] == "CURRENT"
        ):
            set_fields(existing, status="SUPERSEDED")

    db.schedules[record["id"]] = record
    touch(application)
    return object_response(serialize(record), 201)


@schedules_bp.get("/pro-forma-schedules/<record_id>")
@require_roles(*READ_ROLES_NO_COMMENTER)
def get_schedule(record_id):
    return object_response(serialize(fetch("schedules", record_id)))


@schedules_bp.get("/pro-forma-schedules")
@require_roles(*READ_ROLES_NO_COMMENTER)
def list_schedules():
    return list_and_respond("schedules", ("application_id", "basis", "status"))
