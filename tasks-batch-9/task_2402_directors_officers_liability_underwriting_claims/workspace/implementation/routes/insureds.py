"""Insureds, disclosure packages and litigation history (PRD 3.1)."""

from flask import Blueprint

import db
from auth import UNDERWRITER, COMPLIANCE_OFFICER, authenticate
from errors import ApiError
from money import ZERO, dec, q2
from response import list_response, object_response
from routes.common import get_insured
from services import derive, scoring
from validation import Field, paginate, parse_body, parse_pagination, validate

bp = Blueprint("insureds", __name__)

SECTOR_CODES = ("TECH", "BIOTECH", "FINANCIAL", "ENERGY", "INDUSTRIAL", "CONSUMER")
EXCHANGE_LISTINGS = ("LISTED", "PRIVATE", "NONE")
CONTROL_STATUSES = ("INDEPENDENT", "CHANGE_OF_CONTROL_ANNOUNCED", "ACQUIRED")
CASE_TYPES = (
    "SECURITIES_CLASS_ACTION",
    "DERIVATIVE",
    "REGULATORY_ENFORCEMENT",
    "MERGER_OBJECTION",
    "EMPLOYMENT_PRACTICES",
    "FIDUCIARY",
)
OUTCOMES = ("DISMISSED", "SETTLED", "JUDGMENT", "PENDING")

CREATE_FIELDS = [
    Field("legal_name", "string"),
    Field("sector_code", "enum", enum=SECTOR_CODES),
    Field("exchange_listing", "enum", enum=EXCHANGE_LISTINGS),
    Field("market_cap_usd", "money", check=lambda v: v >= 0),
    Field("fiscal_year_end", "string"),
    Field("entity_capacity_cap_usd", "money", check=lambda v: v > 0),
    Field("control_status", "enum", required=False, enum=CONTROL_STATUSES, default="INDEPENDENT"),
    Field("change_of_control_date", "datetime", required=False, default=None),
]

UPDATE_FIELDS = [
    Field("expected_insured_version", "integer"),
    Field("control_status", "enum", required=False, enum=CONTROL_STATUSES),
    Field("change_of_control_date", "datetime", required=False),
    Field("market_cap_usd", "money", required=False, check=lambda v: v >= 0),
    Field("entity_capacity_cap_usd", "money", required=False, check=lambda v: v > 0),
]

PACKAGE_FIELDS = [
    Field("fiscal_year", "integer", check=lambda v: v >= 2000),
    Field("filed_date", "datetime"),
    Field("restatement_flag", "boolean"),
    Field("material_weakness_count", "integer", check=lambda v: v >= 0),
    Field("going_concern_flag", "boolean"),
    Field("negative_operating_cash_flow_flag", "boolean"),
    Field("debt_to_equity", "number", check=lambda v: v >= 0),
    Field("independent_director_ratio", "number", check=lambda v: 0 <= v <= 1),
    Field("dual_class_shares_flag", "boolean"),
    Field("staggered_board_flag", "boolean"),
    Field("combined_ceo_chair_flag", "boolean"),
    Field("auditor_change_flag", "boolean"),
]

EVENT_FIELDS = [
    Field("case_type", "enum", enum=CASE_TYPES),
    Field("filed_date", "datetime"),
    Field("resolved_date", "datetime", required=False, default=None),
    Field("indemnity_paid_usd", "money", required=False, default=ZERO, check=lambda v: v >= 0),
    Field("outcome", "enum", required=False, enum=OUTCOMES, default=None),
]


@bp.post("/dno/insureds")
def create_insured():
    authenticate(UNDERWRITER)
    values, _ = validate(parse_body(), CREATE_FIELDS)
    control_status = values["control_status"] or "INDEPENDENT"
    if control_status != "INDEPENDENT" and values["change_of_control_date"] is None:
        raise ApiError("ERR_CONDITIONAL_FIELD_REQUIRED")
    cap = values["entity_capacity_cap_usd"]
    record = db.insert(
        "insureds",
        {
            "legal_name": values["legal_name"],
            "sector_code": values["sector_code"],
            "exchange_listing": values["exchange_listing"],
            "market_cap_usd": values["market_cap_usd"],
            "fiscal_year_end": values["fiscal_year_end"],
            "control_status": control_status,
            "change_of_control_date": values["change_of_control_date"],
            "entity_capacity_cap_usd": cap,
            "aggregate_bound_side_c_usd": q2(ZERO),
            "available_side_c_capacity_usd": q2(cap),
            "capacity_posture": "OPEN",
            "open_policy_count": 0,
        },
    )
    return object_response(record, 201)


@bp.patch("/dno/insureds/<insured_id>")
def update_insured(insured_id):
    authenticate(COMPLIANCE_OFFICER)
    insured = get_insured(insured_id)
    values, provided = validate(parse_body(), UPDATE_FIELDS)

    if "control_status" in provided and values["control_status"] != "INDEPENDENT":
        if values.get("change_of_control_date") is None:
            raise ApiError("ERR_CONDITIONAL_FIELD_REQUIRED")

    if values["expected_insured_version"] != insured["version"]:
        raise ApiError("ERR_STALE_VERSION")

    for name in ("control_status", "change_of_control_date", "market_cap_usd", "entity_capacity_cap_usd"):
        if name in provided:
            insured[name] = values[name]

    touched = derive.Touched()
    derive.recompute_insured_capacity(insured)
    touched.add(insured)
    touched.flush()
    return object_response(insured)


@bp.get("/dno/insureds/<insured_id>")
def read_insured(insured_id):
    authenticate()
    return object_response(get_insured(insured_id))


@bp.post("/dno/insureds/<insured_id>/disclosure-packages")
def create_package(insured_id):
    authenticate(UNDERWRITER)
    insured = get_insured(insured_id)
    values, _ = validate(parse_body(), PACKAGE_FIELDS)
    record = {"insured_id": insured["id"]}
    for field in PACKAGE_FIELDS:
        record[field.name] = values[field.name]
    record["financial_subscore"] = q2(ZERO)
    record["governance_subscore"] = q2(ZERO)
    return object_response(db.insert("disclosure_packages", record), 201)


@bp.get("/dno/insureds/<insured_id>/disclosure-packages")
def list_packages(insured_id):
    authenticate()
    insured = get_insured(insured_id)
    limit, offset = parse_pagination()
    records = scoring.packages_of(insured["id"])
    return list_response(paginate(records, limit, offset), limit, offset, len(records))


@bp.post("/dno/insureds/<insured_id>/litigation-events")
def create_event(insured_id):
    authenticate(UNDERWRITER)
    insured = get_insured(insured_id)
    values, _ = validate(parse_body(), EVENT_FIELDS)
    record = {
        "insured_id": insured["id"],
        "case_type": values["case_type"],
        "filed_date": values["filed_date"],
        "resolved_date": values["resolved_date"],
        "indemnity_paid_usd": q2(dec(values["indemnity_paid_usd"] or ZERO)),
        "outcome": values["outcome"],
        "weight_units": q2(ZERO),
    }
    return object_response(db.insert("litigation_events", record, common_fields=False), 201)


@bp.get("/dno/insureds/<insured_id>/litigation-events")
def list_events(insured_id):
    authenticate()
    insured = get_insured(insured_id)
    limit, offset = parse_pagination()
    records = scoring.events_of(insured["id"])
    return list_response(paginate(records, limit, offset), limit, offset, len(records))
