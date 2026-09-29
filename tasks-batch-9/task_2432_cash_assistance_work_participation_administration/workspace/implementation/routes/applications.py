"""Application intake, income and resources, determination and disposition
(PRD 3.2 and 3.3)."""

from flask import Blueprint

import guards
from calc import (RESOURCE_LIMIT_CENTS, STATE_TIME_LIMIT_MONTHS, benefit_amount,
                  countable_income, diversion_figures, payment_standard,
                  required_hours, resource_countable_value)
from domain import (cases_of_household, extension_covers, granted_extensions,
                    lookup, rows_where)
from errors import fail
from guards import (Fields, body_str, raw_body, require, require_different_actor,
                    require_owner)
from respond import created, filter_value, listing, ok, pagination
from store import db, new_record, ordered, touch

bp = Blueprint("applications", __name__)

REQUESTED_PROGRAMS = ("ONGOING_ASSISTANCE", "DIVERSION_CONSIDERED")
BUDGETING_METHODS = ("PROSPECTIVE", "RETROSPECTIVE")
SOURCE_TYPES = ("EARNED", "UNEARNED_CHILD_SUPPORT", "UNEARNED_SSI", "UNEARNED_UI")
VERIFY_OUTCOMES = ("VERIFIED", "REFUSED")
ITEM_TYPES = ("LIQUID_ASSET", "VEHICLE", "REAL_PROPERTY", "RETIREMENT")
EXCLUSION_TYPES = ("NONE", "PRIMARY_VEHICLE", "HOMESTEAD", "RETIREMENT_ACCOUNT")
DENIAL_REASONS = ("NONE", "RESOURCES_OVER_LIMIT", "ZERO_BENEFIT", "TIME_LIMIT",
                  "FAILURE_TO_COOPERATE", "OTHER")
WITHDRAWABLE = ("RECEIVED", "DETERMINED", "DIVERSION_OFFERED")


def _application(application_id):
    return lookup("applications", application_id, "ERR_APPLICATION_NOT_FOUND")


def _owning_household(application):
    return db.households[application["household_id"]]


@bp.post("/applications")
def file_application():
    actor = require(guards.APPLICANT, guards.CASEWORKER)
    body = raw_body()
    candidate = body_str(body, "household_id")
    if candidate is not None:
        lookup("households", candidate, "ERR_HOUSEHOLD_NOT_FOUND")
    fields = Fields(body)
    fields.identifier("household_id")
    fields.month("application_month")
    fields.enum("requested_program", REQUESTED_PROGRAMS)
    fields.enum("budgeting_method", BUDGETING_METHODS, required=False,
                default="PROSPECTIVE")
    require_owner(actor, fields["household_id"])

    application = new_record({
        "household_id": fields["household_id"],
        "application_month": fields["application_month"],
        "requested_program": fields["requested_program"],
        "budgeting_method": fields["budgeting_method"],
        "status": "RECEIVED",
        "snapshot_family_type": None,
        "countable_income_cents": None,
        "countable_resources_cents": None,
        "determined_benefit_cents": None,
        "determined_by_user_id": None,
        "decided_by_user_id": None,
        "denial_reason": "NONE",
        "withdrawal_reason": None,
    })
    db.applications[application["id"]] = application
    return created(application)


@bp.get("/applications/<application_id>")
def read_application(application_id):
    actor = require()
    application = _application(application_id)
    require_owner(actor, application["household_id"])
    return ok(application)


@bp.post("/applications/<application_id>/income-sources")
def add_income_source(application_id):
    require(guards.CASEWORKER)
    application = _application(application_id)
    fields = Fields(raw_body())
    fields.enum("source_type", SOURCE_TYPES)
    fields.integer("gross_monthly_cents", minimum=0)
    fields.integer("month_1_cents", required=False, default=0)
    fields.integer("month_2_cents", required=False, default=0)
    fields.integer("month_3_cents", required=False, default=0)
    fields.boolean("is_recurring")
    if application["status"] != "RECEIVED":
        fail("ERR_INVALID_APPLICATION_STATE",
             "Income may only be attached while the application is RECEIVED.")

    source = new_record({
        "application_id": application_id,
        "source_type": fields["source_type"],
        "gross_monthly_cents": fields["gross_monthly_cents"],
        "month_1_cents": fields["month_1_cents"],
        "month_2_cents": fields["month_2_cents"],
        "month_3_cents": fields["month_3_cents"],
        "is_recurring": fields["is_recurring"],
        "verification_status": "UNVERIFIED",
    })
    db.income_sources[source["id"]] = source
    return created(source)


@bp.get("/applications/<application_id>/income-sources")
def list_income_sources(application_id):
    require()
    _application(application_id)
    limit, offset = pagination()
    rows = rows_where("income_sources", application_id=application_id)
    source_type = filter_value("source_type")
    status = filter_value("verification_status")
    if source_type is not None:
        rows = [row for row in rows if row["source_type"] == source_type]
    if status is not None:
        rows = [row for row in rows if row["verification_status"] == status]
    return listing(rows, limit, offset)


@bp.post("/income-sources/<source_id>/verify")
def verify_income_source(source_id):
    require(guards.CASEWORKER)
    source = lookup("income_sources", source_id, "ERR_INCOME_SOURCE_NOT_FOUND")
    fields = Fields(raw_body())
    fields.enum("verification_status", VERIFY_OUTCOMES)
    source["verification_status"] = fields["verification_status"]
    touch(source)
    return ok(source)


@bp.post("/applications/<application_id>/resource-items")
def add_resource_item(application_id):
    require(guards.CASEWORKER)
    _application(application_id)
    fields = Fields(raw_body())
    fields.enum("item_type", ITEM_TYPES)
    fields.integer("gross_value_cents", minimum=0)
    fields.integer("encumbrance_cents", required=False, default=0)
    fields.enum("exclusion_type", EXCLUSION_TYPES)

    item = new_record({
        "application_id": application_id,
        "item_type": fields["item_type"],
        "gross_value_cents": fields["gross_value_cents"],
        "encumbrance_cents": fields["encumbrance_cents"],
        "exclusion_type": fields["exclusion_type"],
        "countable_value_cents": resource_countable_value(
            fields["gross_value_cents"], fields["encumbrance_cents"],
            fields["exclusion_type"]),
    }, audited=False)
    db.resource_items[item["id"]] = item
    return created(item)


@bp.get("/applications/<application_id>/resource-items")
def list_resource_items(application_id):
    require()
    _application(application_id)
    limit, offset = pagination()
    rows = rows_where("resource_items", application_id=application_id)
    item_type = filter_value("item_type")
    if item_type is not None:
        rows = [row for row in rows if row["item_type"] == item_type]
    return listing(rows, limit, offset)


@bp.post("/applications/<application_id>/determine")
def determine(application_id):
    actor = require(guards.CASEWORKER)
    application = _application(application_id)
    if application["status"] != "RECEIVED":
        fail("ERR_INVALID_APPLICATION_STATE",
             "Only a RECEIVED application may be determined.")
    household = _owning_household(application)
    window = household.get("diversion_ineligible_through_month")
    if window is not None and application["application_month"] <= window:
        fail("ERR_DIVERSION_INELIGIBILITY_ACTIVE",
             "The household is inside a diversion ineligibility window.")

    sources = rows_where("income_sources", application_id=application_id)
    income = countable_income(sources, application["budgeting_method"])
    resources = sum(item["countable_value_cents"] for item
                    in rows_where("resource_items", application_id=application_id))
    benefit = benefit_amount(household["household_size"], income, 0)
    application["snapshot_family_type"] = household["family_type"]
    application["countable_income_cents"] = income
    application["countable_resources_cents"] = resources
    application["determined_benefit_cents"] = benefit
    application["determined_by_user_id"] = actor.user_id
    application["status"] = "DETERMINED"
    touch(application)
    return ok(application)


def _time_limit_blocks(household, certification_start_month):
    """PRD 3.3: at or over the state limit unless a GRANTED extension of any
    case of the household covers the certification start month."""
    if household["state_clock_months_used"] < STATE_TIME_LIMIT_MONTHS:
        return False
    for case in cases_of_household(household["id"]):
        for extension in granted_extensions(case["id"]):
            if extension_covers(extension, certification_start_month):
                return False
    return True


@bp.post("/applications/<application_id>/approve")
def approve(application_id):
    actor = require(guards.SUPERVISOR)
    application = _application(application_id)
    fields = Fields(raw_body())
    fields.month("certification_start_month")
    require_different_actor(actor, application["determined_by_user_id"])
    if application["status"] != "DETERMINED":
        fail("ERR_INVALID_APPLICATION_STATE",
             "Only a DETERMINED application may be approved.")
    household = _owning_household(application)
    if _time_limit_blocks(household, fields["certification_start_month"]):
        fail("ERR_TIME_LIMIT_EXHAUSTED",
             "The household has exhausted the state time limit.")
    if application["countable_resources_cents"] > RESOURCE_LIMIT_CENTS:
        fail("ERR_RESOURCE_LIMIT_EXCEEDED",
             "Countable resources exceed the program limit.")
    if not application["determined_benefit_cents"]:
        fail("ERR_INELIGIBLE_ZERO_BENEFIT", "The determined benefit is zero.")

    family_type = application["snapshot_family_type"]
    hours = required_hours(family_type)
    case = new_record({
        "household_id": household["id"],
        "application_id": application_id,
        "case_number": db.next_case_number(),
        "certification_start_month": fields["certification_start_month"],
        "benefit_status": "PENDING_ISSUANCE",
        "compliance_status": "NOT_REQUIRED" if family_type == "CHILD_ONLY"
                             else "ASSIGNED",
        "closure_reason": "NONE",
        "family_type": family_type,
        "household_size": household["household_size"],
        "countable_income_cents": application["countable_income_cents"],
        "sanction_level": 0,
        "sanction_pct": 0.00,
        "benefit_amount_cents": application["determined_benefit_cents"],
        "required_weekly_hours": hours["required_weekly_hours"],
        "required_core_weekly_hours": hours["required_core_weekly_hours"],
        "required_monthly_hours": hours["required_monthly_hours"],
        "required_core_monthly_hours": hours["required_core_monthly_hours"],
        "supportive_fy_authorized_cents": 0,
    })
    db.cases[case["id"]] = case
    application["status"] = "APPROVED"
    application["decided_by_user_id"] = actor.user_id
    touch(application)
    return created(case)


@bp.post("/applications/<application_id>/deny")
def deny(application_id):
    actor = require(guards.SUPERVISOR)
    application = _application(application_id)
    fields = Fields(raw_body())
    fields.enum("denial_reason", DENIAL_REASONS)
    require_different_actor(actor, application["determined_by_user_id"])
    if application["status"] != "DETERMINED":
        fail("ERR_INVALID_APPLICATION_STATE",
             "Only a DETERMINED application may be denied.")
    application["status"] = "DENIED"
    application["denial_reason"] = fields["denial_reason"]
    application["decided_by_user_id"] = actor.user_id
    touch(application)
    return ok(application)


@bp.post("/applications/<application_id>/withdraw")
def withdraw(application_id):
    actor = require(guards.APPLICANT, guards.CASEWORKER)
    application = _application(application_id)
    fields = Fields(raw_body())
    fields.text("withdrawal_reason")
    require_owner(actor, application["household_id"])
    if application["status"] not in WITHDRAWABLE:
        fail("ERR_INVALID_APPLICATION_STATE",
             "This application may no longer be withdrawn.")
    application["status"] = "WITHDRAWN"
    application["withdrawal_reason"] = fields["withdrawal_reason"]
    touch(application)
    for grant in rows_where("diversion_grants", application_id=application_id):
        if grant["status"] == "OFFERED":
            grant["status"] = "DECLINED"
            touch(grant)
    return ok(application)


@bp.post("/applications/<application_id>/diversion-grants")
def offer_diversion(application_id):
    require(guards.SUPERVISOR)
    application = _application(application_id)
    if application["status"] != "DETERMINED" or \
            application["requested_program"] != "DIVERSION_CONSIDERED":
        fail("ERR_INVALID_APPLICATION_STATE",
             "Diversion may only be offered on a DETERMINED application filed as "
             "DIVERSION_CONSIDERED.")
    basis = application["determined_benefit_cents"]
    if not basis:
        fail("ERR_DIVERSION_REQUIRES_BENEFIT",
             "A diversion offer requires a positive determined benefit.")

    figures = diversion_figures(basis, application["application_month"])
    grant = new_record({
        "application_id": application_id,
        "monthly_benefit_basis_cents": basis,
        "lump_sum_cents": figures["lump_sum_cents"],
        "ineligibility_months": figures["ineligibility_months"],
        "ineligibility_end_month": figures["ineligibility_end_month"],
        "status": "OFFERED",
        "decline_reason": None,
    })
    db.diversion_grants[grant["id"]] = grant
    application["status"] = "DIVERSION_OFFERED"
    touch(application)
    return created(grant)


@bp.get("/applications/<application_id>/diversion-grants")
def list_diversion_grants(application_id):
    require()
    _application(application_id)
    limit, offset = pagination()
    rows = rows_where("diversion_grants", application_id=application_id)
    status = filter_value("status")
    if status is not None:
        rows = [row for row in rows if row["status"] == status]
    return listing(rows, limit, offset)


def _grant(grant_id):
    return lookup("diversion_grants", grant_id, "ERR_DIVERSION_GRANT_NOT_FOUND")


@bp.post("/diversion-grants/<grant_id>/accept")
def accept_diversion(grant_id):
    actor = require(guards.APPLICANT)
    grant = _grant(grant_id)
    application = db.applications[grant["application_id"]]
    require_owner(actor, application["household_id"])
    if grant["status"] != "OFFERED":
        fail("ERR_INVALID_DIVERSION_STATE", "Only an OFFERED grant may be accepted.")
    grant["status"] = "ACCEPTED"
    touch(grant)
    application["status"] = "DIVERTED"
    touch(application)
    household = _owning_household(application)
    household["diversion_ineligible_through_month"] = grant["ineligibility_end_month"]
    touch(household)
    return ok(grant)


@bp.post("/diversion-grants/<grant_id>/decline")
def decline_diversion(grant_id):
    actor = require(guards.APPLICANT)
    grant = _grant(grant_id)
    fields = Fields(raw_body())
    fields.text("decline_reason")
    application = db.applications[grant["application_id"]]
    require_owner(actor, application["household_id"])
    if grant["status"] != "OFFERED":
        fail("ERR_INVALID_DIVERSION_STATE", "Only an OFFERED grant may be declined.")
    grant["status"] = "DECLINED"
    grant["decline_reason"] = fields["decline_reason"]
    touch(grant)
    if application["status"] == "DIVERSION_OFFERED":
        application["status"] = "DETERMINED"
        touch(application)
    return ok(grant)
