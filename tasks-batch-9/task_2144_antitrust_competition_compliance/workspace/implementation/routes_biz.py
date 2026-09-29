"""Competitor contacts, transactions, HSR analyses and risk assessments."""
from decimal import Decimal

from flask import Blueprint

import calc
import domain
from api import ok, created, listing
from calc import d, r2
from errors import fail
from ladder import (require_auth, body, touch, lookup, rows, pagination, filter_enum,
                    filter_str, req_str, req_enum, req_int, req_bool, req_dt,
                    req_enum_array, ALL_ROLES)
from store import db, new_record, clock_now, add_days

bp = Blueprint("biz", __name__)

CONTACT_STATUSES = ["LOGGED", "UNDER_REVIEW", "REMEDIATION_REQUIRED", "CLEARED", "ESCALATED"]
TRANSACTION_STATUSES = ["DRAFT", "ANALYZED", "EXEMPT", "FILED", "CLEARED"]


# =========================================================== CompetitorContact
@bp.post("/compliance/competitor-contacts")
def create_contact():
    role, user_id = require_auth(["Employee"])
    payload = body()
    unit_id = req_str(payload, "business_unit_id")
    employee_id = req_str(payload, "employee_id")
    competitor_name = req_str(payload, "competitor_name")
    channel = req_enum(payload, "contact_channel", calc.CONTACT_CHANNELS)
    tags = req_enum_array(payload, "topic_tags", calc.TOPIC_TAGS)
    pricing_topic = req_bool(payload, "pricing_topic")
    occurred_at = req_dt(payload, "occurred_at")

    unit = lookup("business_units", unit_id)
    employee = lookup("employees", employee_id)

    if employee_id != user_id:
        fail("ERR_NOT_RESOURCE_OWNER", "contact belongs to another employee")
    if employee["business_unit_id"] != unit_id:
        fail("ERR_NOT_RESOURCE_OWNER", "business unit is not this employee's unit")
    if unit["posture"] == "FROZEN":
        fail("ERR_BUSINESS_UNIT_FROZEN", "business unit is frozen")
    if employee["role_category"] in ("SALES", "PRICING"):
        if domain.training_status(employee) != "CURRENT":
            fail("ERR_TRAINING_NOT_CURRENT", "employee training is not current")

    charge, multiplier = calc.contact_exposure_points(
        channel, tags, pricing_topic, employee["role_category"], unit["risk_band"])
    if d(unit["exposure_points"]) + charge > d(unit["exposure_budget_points"]):
        fail("ERR_EXPOSURE_BUDGET_EXCEEDED", "exposure budget exceeded")

    row = new_record({
        "business_unit_id": unit_id,
        "employee_id": employee_id,
        "competitor_name": competitor_name,
        "contact_channel": channel,
        "topic_tags": tags,
        "pricing_topic": pricing_topic,
        "occurred_at": occurred_at,
        "status": "LOGGED",
        "exposure_points_charged": charge,
        "band_multiplier_applied": multiplier,
        "review_opened_by_user_id": None,
        "remediation_instructions": None,
        "remediation_response": None,
    })
    db.contacts[row["id"]] = row
    domain.recompute_ledger(unit)
    touch(unit)
    domain.recompute_posture(unit)
    return created(row, domain.ser_contact)


@bp.get("/compliance/competitor-contacts/<contact_id>")
def read_contact(contact_id):
    require_auth(ALL_ROLES)
    return ok(lookup("contacts", contact_id), domain.ser_contact)


@bp.get("/compliance/competitor-contacts")
def list_contacts():
    require_auth(ALL_ROLES)
    unit_id = filter_str("business_unit_id")
    employee_id = filter_str("employee_id")
    status = filter_enum("status", CONTACT_STATUSES)
    limit, offset = pagination()
    items = rows("contacts")
    if unit_id:
        items = [r for r in items if r["business_unit_id"] == unit_id]
    if employee_id:
        items = [r for r in items if r["employee_id"] == employee_id]
    if status:
        items = [r for r in items if r["status"] == status]
    return listing(items, domain.ser_contact, limit, offset)


@bp.post("/compliance/competitor-contacts/<contact_id>/review-opening")
def open_contact_review(contact_id):
    role, user_id = require_auth(["AntitrustCounsel"])
    body()
    contact = lookup("contacts", contact_id)
    if contact["status"] != "LOGGED":
        fail("ERR_INVALID_STATE", "contact is %s" % contact["status"])
    contact["status"] = "UNDER_REVIEW"
    contact["review_opened_by_user_id"] = user_id
    touch(contact)
    return ok(contact, domain.ser_contact)


@bp.post("/compliance/competitor-contacts/<contact_id>/remediation-order")
def order_remediation(contact_id):
    require_auth(["AntitrustCounsel"])
    payload = body()
    instructions = req_str(payload, "instructions")
    contact = lookup("contacts", contact_id)
    if contact["status"] != "UNDER_REVIEW":
        fail("ERR_INVALID_STATE", "contact is %s" % contact["status"])
    contact["status"] = "REMEDIATION_REQUIRED"
    contact["remediation_instructions"] = instructions
    touch(contact)
    return ok(contact, domain.ser_contact)


@bp.post("/compliance/competitor-contacts/<contact_id>/remediation-response")
def respond_remediation(contact_id):
    role, user_id = require_auth(["Employee"])
    payload = body()
    response = req_str(payload, "response")
    contact = lookup("contacts", contact_id)
    if contact["employee_id"] != user_id:
        fail("ERR_NOT_RESOURCE_OWNER", "contact belongs to another employee")
    if contact["status"] != "REMEDIATION_REQUIRED":
        fail("ERR_INVALID_STATE", "contact is %s" % contact["status"])
    contact["status"] = "UNDER_REVIEW"
    contact["remediation_response"] = response
    touch(contact)
    return ok(contact, domain.ser_contact)


@bp.post("/compliance/competitor-contacts/<contact_id>/clearance")
def clear_contact(contact_id):
    require_auth(["AntitrustCounsel"])
    payload = body()
    req_str(payload, "notes")
    contact = lookup("contacts", contact_id)
    if contact["status"] != "UNDER_REVIEW":
        fail("ERR_INVALID_STATE", "contact is %s" % contact["status"])
    contact["status"] = "CLEARED"
    contact["exposure_points_charged"] = Decimal("0.00")
    touch(contact)
    unit = db.business_units[contact["business_unit_id"]]
    domain.recompute_ledger(unit)
    touch(unit)
    domain.recompute_posture(unit)
    return ok(contact, domain.ser_contact)


@bp.post("/compliance/competitor-contacts/<contact_id>/escalation")
def escalate_contact(contact_id):
    require_auth(["AntitrustCounsel"])
    payload = body()
    req_str(payload, "reason")
    contact = lookup("contacts", contact_id)
    if contact["status"] != "UNDER_REVIEW":
        fail("ERR_INVALID_STATE", "contact is %s" % contact["status"])
    surcharge = r2(d(contact["exposure_points_charged"])
                   * (calc.ESCALATION_SURCHARGE_MULTIPLIER - Decimal("1")))
    contact["exposure_points_charged"] = r2(d(contact["exposure_points_charged"]) + surcharge)
    contact["status"] = "ESCALATED"
    touch(contact)
    unit = db.business_units[contact["business_unit_id"]]
    domain.recompute_ledger(unit)
    touch(unit)
    domain.recompute_posture(unit)
    return ok(contact, domain.ser_contact)


# ================================================================= Transaction
@bp.post("/compliance/transactions")
def create_transaction():
    role, user_id = require_auth(["BusinessLead"])
    payload = body()
    unit_id = req_str(payload, "business_unit_id")
    target_name = req_str(payload, "target_name")
    deal_value = req_int(payload, "deal_value_cents", minimum=0)
    assumed = req_int(payload, "assumed_liabilities_cents", minimum=0)
    market_valuation = req_int(payload, "market_valuation_cents", minimum=0)
    acquirer_assets = req_int(payload, "acquirer_total_assets_cents", minimum=0)
    target_assets = req_int(payload, "target_total_assets_cents", minimum=0)
    signed_at = req_dt(payload, "signed_at")
    exemption = req_enum(payload, "exemption_code", calc.EXEMPTION_CODES,
                         required=False, default="NONE")

    unit = lookup("business_units", unit_id)
    if unit_id != user_id:
        fail("ERR_NOT_RESOURCE_OWNER", "business unit belongs to another lead")
    if unit["posture"] == "FROZEN":
        fail("ERR_BUSINESS_UNIT_FROZEN", "business unit is frozen")

    row = new_record({
        "business_unit_id": unit_id,
        "target_name": target_name,
        "deal_value_cents": deal_value,
        "assumed_liabilities_cents": assumed,
        "market_valuation_cents": market_valuation,
        "acquirer_total_assets_cents": acquirer_assets,
        "target_total_assets_cents": target_assets,
        "exemption_code": exemption,
        "signed_at": signed_at,
        "status": "DRAFT",
        "filed_at": None,
        "waiting_period_end": None,
    })
    db.transactions[row["id"]] = row
    return created(row, domain.ser_transaction)


@bp.get("/compliance/transactions/<transaction_id>")
def read_transaction(transaction_id):
    require_auth(ALL_ROLES)
    return ok(lookup("transactions", transaction_id), domain.ser_transaction)


@bp.get("/compliance/transactions")
def list_transactions():
    require_auth(ALL_ROLES)
    unit_id = filter_str("business_unit_id")
    status = filter_enum("status", TRANSACTION_STATUSES)
    limit, offset = pagination()
    items = rows("transactions")
    if unit_id:
        items = [r for r in items if r["business_unit_id"] == unit_id]
    if status:
        items = [r for r in items if r["status"] == status]
    return listing(items, domain.ser_transaction, limit, offset)


@bp.post("/compliance/transactions/<transaction_id>/filing")
def file_transaction(transaction_id):
    require_auth(["AntitrustCounsel"])
    body()
    txn = lookup("transactions", transaction_id)
    if txn["status"] != "ANALYZED":
        fail("ERR_INVALID_STATE", "transaction is %s" % txn["status"])
    analysis = domain.active_analysis(txn["id"])
    if analysis is None or not analysis["filing_required"]:
        fail("ERR_TRANSACTION_NOT_ANALYZED", "no active analysis requires a filing")
    filed_at = clock_now()
    txn["status"] = "FILED"
    txn["filed_at"] = filed_at
    txn["waiting_period_end"] = add_days(filed_at, calc.HSR_WAITING_PERIOD_DAYS)
    touch(txn)
    return ok(txn, domain.ser_transaction)


@bp.post("/compliance/transactions/<transaction_id>/clearance")
def clear_transaction(transaction_id):
    require_auth(["AntitrustCounsel"])
    body()
    txn = lookup("transactions", transaction_id)
    if txn["status"] != "FILED":
        fail("ERR_INVALID_STATE", "transaction is %s" % txn["status"])
    if clock_now() < txn["waiting_period_end"]:
        fail("ERR_WAITING_PERIOD_ACTIVE", "the HSR waiting period has not elapsed")
    txn["status"] = "CLEARED"
    touch(txn)
    return ok(txn, domain.ser_transaction)


# ================================================================= HsrAnalysis
@bp.post("/compliance/hsr-analyses")
def create_hsr_analysis():
    role, user_id = require_auth(["AntitrustCounsel"])
    payload = body()
    transaction_id = req_str(payload, "transaction_id")
    variant = req_enum(payload, "valuation_variant", calc.VALUATION_VARIANTS)
    expected = req_int(payload, "expected_transaction_version")

    txn = lookup("transactions", transaction_id)
    if expected != txn["version"]:
        fail("ERR_STALE_VERSION", "transaction version has advanced")
    if txn["status"] not in ("DRAFT", "ANALYZED", "EXEMPT"):
        fail("ERR_INVALID_STATE", "transaction is %s" % txn["status"])

    size, determination, required = calc.hsr_size_of_transaction(txn, variant)
    prior = domain.active_analysis(txn["id"])
    if prior is not None:
        prior["status"] = "SUPERSEDED"
        touch(prior)

    row = new_record({
        "transaction_id": transaction_id,
        "valuation_variant": variant,
        "size_of_transaction_cents": size,
        "filing_required": required,
        "determination": determination,
        "status": "ACTIVE",
        "analyzed_by_user_id": user_id,
    })
    db.hsr_analyses[row["id"]] = row
    txn["status"] = "ANALYZED" if required else "EXEMPT"
    touch(txn)
    return created(row, domain.ser_hsr)


@bp.get("/compliance/hsr-analyses/<analysis_id>")
def read_hsr_analysis(analysis_id):
    require_auth(ALL_ROLES)
    return ok(lookup("hsr_analyses", analysis_id), domain.ser_hsr)


@bp.get("/compliance/hsr-analyses")
def list_hsr_analyses():
    require_auth(ALL_ROLES)
    transaction_id = filter_str("transaction_id")
    status = filter_enum("status", ["ACTIVE", "SUPERSEDED"])
    variant = filter_enum("valuation_variant", calc.VALUATION_VARIANTS)
    limit, offset = pagination()
    items = rows("hsr_analyses")
    if transaction_id:
        items = [r for r in items if r["transaction_id"] == transaction_id]
    if status:
        items = [r for r in items if r["status"] == status]
    if variant:
        items = [r for r in items if r["valuation_variant"] == variant]
    return listing(items, domain.ser_hsr, limit, offset)


# ============================================================== RiskAssessment
@bp.post("/compliance/risk-assessments")
def create_risk_assessment():
    require_auth(["AntitrustCounsel"])
    payload = body()
    unit_id = req_str(payload, "business_unit_id")
    variant = req_enum(payload, "variant", calc.ASSESSMENT_VARIANTS)
    expected = req_int(payload, "expected_business_unit_version")

    unit = lookup("business_units", unit_id)
    if expected != unit["version"]:
        fail("ERR_STALE_VERSION", "business unit version has advanced")

    escalated = len([c for c in domain.unit_contacts(unit_id) if c["status"] == "ESCALATED"])
    flagged = len([a for a in domain.unit_attendances(unit_id) if a["status"] == "FLAGGED"])
    violations = domain.document_violation_count(unit)
    result = calc.market_risk_index(unit, variant, escalated, flagged, violations)

    prior = domain.active_assessment(unit_id)
    if prior is not None:
        prior["status"] = "SUPERSEDED"
        touch(prior)

    row = new_record({
        "business_unit_id": unit_id,
        "variant": variant,
        "status": "ACTIVE",
    })
    row.update(result)
    db.risk_assessments[row["id"]] = row

    unit["risk_band"] = result["risk_band"]
    touch(unit)
    domain.recompute_posture(unit)
    return created(row, domain.ser_assessment)


@bp.get("/compliance/risk-assessments/<assessment_id>")
def read_risk_assessment(assessment_id):
    require_auth(ALL_ROLES)
    return ok(lookup("risk_assessments", assessment_id), domain.ser_assessment)


@bp.get("/compliance/risk-assessments")
def list_risk_assessments():
    require_auth(ALL_ROLES)
    unit_id = filter_str("business_unit_id")
    variant = filter_enum("variant", calc.ASSESSMENT_VARIANTS)
    status = filter_enum("status", ["ACTIVE", "SUPERSEDED"])
    limit, offset = pagination()
    items = rows("risk_assessments")
    if unit_id:
        items = [r for r in items if r["business_unit_id"] == unit_id]
    if variant:
        items = [r for r in items if r["variant"] == variant]
    if status:
        items = [r for r in items if r["status"] == status]
    return listing(items, domain.ser_assessment, limit, offset)
