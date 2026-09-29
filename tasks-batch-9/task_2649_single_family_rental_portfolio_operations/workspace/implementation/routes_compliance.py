"""Compliance obligations, property-tax appeals and their cascades."""
from flask import Blueprint

import calc
import cascades
import store
import views
from envelope import created, ok, paginate
from errors import fail
from validation import F, authorize, body_json, must_find, parse_date_value, validate

bp = Blueprint("compliance", __name__)

OBLIGATION_READ = ["ComplianceOfficer", "PortfolioAdmin", "RegionalDirector",
                   "OperationsManager", "LeasingAgent"]

OBLIGATION_FIELDS = [
    F("home_id", "string"),
    F("obligation_type", "string",
      enum=["HOA_VIOLATION", "INSURANCE_DEFICIENCY", "PROPERTY_TAX_APPEAL"]),
    F("severity", "string", enum=["MINOR", "MAJOR", "CRITICAL"]),
    F("description", "string"),
    F("due_on", "date"),
    F("assessed_value_cents", "money", required=False, default=None),
    F("target_value_cents", "money", required=False, default=None),
    F("consultant_fee_bps", "bps", required=False, default=0),
    F("supersedes_obligation_id", "string", required=False, default=""),
]


@bp.post("/compliance-obligations")
def create_obligation():
    data = validate(body_json(), OBLIGATION_FIELDS)
    if data["obligation_type"] == "PROPERTY_TAX_APPEAL":
        for name in ("assessed_value_cents", "target_value_cents"):
            if data[name] is None:
                fail("ERR_INVALID_REQUEST",
                     "Field '%s' is required for a property tax appeal." % name)
    authorize(["ComplianceOfficer"])
    home = must_find("homes", data["home_id"], "ERR_HOME_NOT_FOUND")
    if data["supersedes_obligation_id"]:
        must_find("compliance_obligations", data["supersedes_obligation_id"],
                  "ERR_COMPLIANCE_OBLIGATION_NOT_FOUND")

    tax_appeal = data["obligation_type"] == "PROPERTY_TAX_APPEAL"
    row = store.base_row()
    row.update({
        "home_id": home["id"],
        "supersedes_obligation_id": data["supersedes_obligation_id"],
        "work_order_id": "",
        "obligation_type": data["obligation_type"],
        "severity": data["severity"],
        "description": data["description"],
        "due_on": data["due_on"],
        "planned_resolution_on": "",
        "evidence_ref": "",
        "assessed_value_cents": (int(data["assessed_value_cents"]) if tax_appeal else 0),
        "target_value_cents": (int(data["target_value_cents"]) if tax_appeal else 0),
        "settled_value_cents": 0,
        "consultant_fee_bps": data["consultant_fee_bps"],
        "annual_tax_savings_cents": 0,
        "consultant_fee_cents": 0,
        "net_tax_benefit_cents": 0,
        "resolution_round": 0,
        "submitted_by_user_id": "",
        "status": "OPEN",
    })
    store.insert("compliance_obligations", row)
    cascades.recompute_posture(home)
    return created(views.public(row))


@bp.get("/compliance-obligations/<obligation_id>")
def read_obligation(obligation_id):
    authorize(OBLIGATION_READ)
    row = must_find("compliance_obligations", obligation_id,
                    "ERR_COMPLIANCE_OBLIGATION_NOT_FOUND")
    return ok(views.public(row))


@bp.get("/compliance-obligations")
def list_obligations():
    authorize(OBLIGATION_READ)
    rows = views.filtered("compliance_obligations", [
        ("home_id", "home_id", "string"),
        ("supersedes_obligation_id", "supersedes_obligation_id", "string"),
        ("work_order_id", "work_order_id", "string"),
        ("obligation_type", "obligation_type", "string"),
        ("severity", "severity", "string"),
        ("status", "status", "string"),
    ])
    return paginate(rows, views.public)


@bp.post("/compliance-obligations/<obligation_id>/plan")
def plan_obligation(obligation_id):
    data = validate(body_json(), [
        F("planned_resolution_on", "date"),
        F("work_order_id", "string", required=False, default=""),
    ])
    authorize(["ComplianceOfficer"])
    work_order = None
    if data["work_order_id"]:
        work_order = must_find("work_orders", data["work_order_id"], "ERR_WORK_ORDER_NOT_FOUND")
    obligation = must_find("compliance_obligations", obligation_id,
                           "ERR_COMPLIANCE_OBLIGATION_NOT_FOUND")
    if obligation["status"] not in ("OPEN", "RESOLUTION_REJECTED"):
        fail("ERR_INVALID_STATE")
    if work_order is not None:
        if (work_order["home_id"] != obligation["home_id"]
                or work_order["status"] == "VOIDED"):
            fail("ERR_OBLIGATION_WORK_ORDER_MISMATCH")
    if parse_date_value(data["planned_resolution_on"]) > parse_date_value(obligation["due_on"]):
        fail("ERR_OBLIGATION_PAST_DUE")

    replan = obligation["status"] == "RESOLUTION_REJECTED"
    obligation["status"] = "PLANNED"
    obligation["planned_resolution_on"] = data["planned_resolution_on"]
    if work_order is not None:
        obligation["work_order_id"] = work_order["id"]
    if replan:
        obligation["resolution_round"] = int(obligation["resolution_round"]) + 1
    store.touch(obligation)
    return ok(views.public(obligation))


@bp.post("/compliance-obligations/<obligation_id>/submit-resolution")
def submit_resolution(obligation_id):
    data = validate(body_json(), [
        F("evidence_ref", "string", required=False, default=None),
        F("settled_value_cents", "money", required=False, default=None),
    ])
    role, user_id = authorize(["ComplianceOfficer"])
    obligation = must_find("compliance_obligations", obligation_id,
                           "ERR_COMPLIANCE_OBLIGATION_NOT_FOUND")
    if obligation["status"] != "PLANNED":
        fail("ERR_INVALID_STATE")
    home = store.get("homes", obligation["home_id"])
    if obligation["obligation_type"] == "PROPERTY_TAX_APPEAL":
        settled = data["settled_value_cents"]
        if settled is None or int(settled) < 1 or int(settled) > int(home["assessed_value_cents"]):
            fail("ERR_SETTLED_VALUE_INVALID")
        obligation["settled_value_cents"] = int(settled)
    else:
        if not data["evidence_ref"]:
            fail("ERR_EVIDENCE_REQUIRED")
    if data["evidence_ref"] is not None:
        obligation["evidence_ref"] = data["evidence_ref"]
    obligation["status"] = "RESOLUTION_SUBMITTED"
    obligation["submitted_by_user_id"] = user_id
    store.touch(obligation)
    return ok(views.public(obligation))


@bp.post("/compliance-obligations/<obligation_id>/review-resolution")
def review_resolution(obligation_id):
    data = validate(body_json(), [
        F("decision", "string", enum=["ACCEPT", "REJECT", "WAIVE"]),
        F("review_note", "string", required=False, default=None),
    ])
    role, user_id = authorize(["ComplianceOfficer", "RegionalDirector"])
    obligation = must_find("compliance_obligations", obligation_id,
                           "ERR_COMPLIANCE_OBLIGATION_NOT_FOUND")
    if obligation["status"] != "RESOLUTION_SUBMITTED":
        fail("ERR_INVALID_STATE")
    if user_id == obligation["submitted_by_user_id"]:
        fail("ERR_SEGREGATION_OF_DUTIES")
    decision = data["decision"]
    if decision == "WAIVE":
        if (obligation["obligation_type"] != "HOA_VIOLATION"
                or obligation["severity"] not in ("MINOR", "MAJOR")):
            fail("ERR_CRITICAL_OBLIGATION_NOT_WAIVABLE")

    home = store.get("homes", obligation["home_id"])
    market = cascades.market_of(home)

    if decision == "REJECT":
        obligation["status"] = "RESOLUTION_REJECTED"
        obligation["submitted_by_user_id"] = ""
        store.touch(obligation)
        cascades.recompute_posture(home)
        return ok(views.public(obligation))

    if decision == "WAIVE":
        obligation["status"] = "WAIVED"
        store.touch(obligation)
        cascades.recompute_posture(home)
        return ok(views.public(obligation))

    obligation["status"] = "RESOLVED"
    if obligation["obligation_type"] == "PROPERTY_TAX_APPEAL":
        # Hop 1 — the appeal economics, against the assessment as it stands now.
        settlement = calc.tax_appeal_savings(
            home["assessed_value_cents"], obligation["settled_value_cents"],
            market["millage_bps"], obligation["consultant_fee_bps"])
        obligation.update(settlement)
        store.touch(obligation)
        # Hop 2 — the home's assessment and its annual tax line.
        home["assessed_value_cents"] = int(obligation["settled_value_cents"])
        cascades.recompute_property_tax(home)
        store.touch(home)
        # Hops 3 and 4 — the realized yield group, then hold/sell.
        cascades.recompute_realized(home)
    else:
        store.touch(obligation)
    cascades.recompute_posture(home)
    return ok(views.public(obligation))
