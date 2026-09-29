"""Monitoring companies and their manual status actions."""

from flask import Blueprint

import engine
import rt
from core import F, authenticate, check_owner, created, listing, ok, q, validate
from errors import ApiError
from store import base_row, now, store, touch

bp = Blueprint("companies", __name__)

READ_ONE_ROLES = ["ProgramAdministrator", "PermitClerk", "BillingClerk",
                  "FalseAlarmReviewOfficer", "PoliceDispatchSupervisor",
                  "AlarmCompanyOperator"]
READ_MANY_ROLES = ["ProgramAdministrator", "PermitClerk", "BillingClerk",
                   "FalseAlarmReviewOfficer", "PoliceDispatchSupervisor"]

CREATE_FIELDS = [
    F("legal_name", "string"),
    F("license_number", "string"),
    F("contact_email", "string"),
    F("contact_phone", "string"),
    F("score_mode", "enum", values=("VOLUME_WEIGHTED", "PERIOD_EQUAL")),
]

ACTION_FIELDS = [
    F("action", "enum", values=("SUSPEND", "REINSTATE", "REVOKE")),
    F("status_reason", "string"),
]


@bp.post("/alarm-companies")
def create_company():
    ctx = authenticate(["ProgramAdministrator"])
    data = validate(ctx.body, CREATE_FIELDS)
    for existing in store.alarm_companies.values():
        if existing.get("status") == "REVOKED":
            continue
        if existing.get("license_number") == data["license_number"]:
            raise ApiError("ERR_INVALID_FIELD_VALUE",
                           "license_number is already held by a live company.")
    row = base_row()
    row["legal_name"] = data["legal_name"]
    row["license_number"] = data["license_number"]
    row["contact_email"] = data["contact_email"]
    row["contact_phone"] = data["contact_phone"]
    row["status"] = "ACTIVE"
    row["score_mode"] = data["score_mode"]
    row["reporting_compliance_score"] = 1.00
    row["monitored_system_count"] = 0
    row["dispatch_request_count_lifetime"] = 0
    row["consecutive_flagged_report_count"] = 0
    row["probation_started_at"] = None
    row["status_reason"] = None
    row["last_status_action_at"] = None
    store.alarm_companies[row["id"]] = row
    engine.rollup_company(row, bump=False)
    engine.recompute_flagged_run(row)
    return created(row)


@bp.post("/alarm-companies/<company_id>/status-actions")
def company_status_action(company_id):
    ctx = authenticate(["ProgramAdministrator"])
    data = validate(ctx.body, ACTION_FIELDS)
    company = rt.resolve("AlarmCompany", company_id)
    action = data["action"]
    status = company.get("status")
    stamped = now()
    if action == "SUSPEND":
        if status not in ("ACTIVE", "PROBATION"):
            raise ApiError("ERR_INVALID_STATE",
                           "SUSPEND is available from ACTIVE or PROBATION only.")
        if status == "ACTIVE":
            company["probation_started_at"] = stamped
        company["status"] = "SUSPENDED"
    elif action == "REINSTATE":
        if status != "SUSPENDED":
            raise ApiError("ERR_INVALID_STATE",
                           "REINSTATE is available from SUSPENDED only.")
        if not engine.reinstatement_earned(company):
            raise ApiError("ERR_COMPANY_REINSTATEMENT_NOT_EARNED",
                           "Two consecutive accepted periods at or above 0.70 are required.")
        company["status"] = "PROBATION"
    else:
        if status != "SUSPENDED":
            raise ApiError("ERR_INVALID_STATE",
                           "REVOKE is available from SUSPENDED only.")
        company["status"] = "REVOKED"
    company["status_reason"] = data["status_reason"]
    company["last_status_action_at"] = stamped
    engine.rollup_company(company, bump=False)
    touch(company)
    return ok(company)


@bp.get("/alarm-companies/<company_id>")
def get_company(company_id):
    ctx = authenticate(READ_ONE_ROLES)
    company = rt.resolve("AlarmCompany", company_id)
    check_owner(ctx, company_id=company["id"])
    engine.rollup_company(company, bump=False)
    return ok(company)


@bp.get("/alarm-companies")
def list_companies():
    authenticate(READ_MANY_ROLES)
    rows = rt.all_rows("AlarmCompany")
    for row in rows:
        engine.rollup_company(row, bump=False)
    status = q("status")
    license_number = q("license_number")
    if status is not None:
        rows = [r for r in rows if r.get("status") == status]
    if license_number is not None:
        rows = [r for r in rows if r.get("license_number") == license_number]
    return listing(rows, rt.fields("AlarmCompany"))
