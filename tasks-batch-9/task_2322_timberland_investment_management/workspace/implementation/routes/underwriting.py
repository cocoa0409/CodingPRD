"""Underwriting cases and the investment-committee review cycle (PRD 3.2)."""

from flask import Blueprint

import calc
import db
import middleware
import response
import serializers
import services
import validate
from db import store
from errors import ApiError

bp = Blueprint("underwriting", __name__)

NON_TERMINAL_CASE_STATES = ("DRAFT", "SUBMITTED", "REVISION_REQUESTED")


def revalue(case, prop):
    """Recompute the whole valuation stack against current inventory."""
    base_tons, acres = services.inventoried_totals(prop["id"])
    species = services.dominant_species(prop["id"], inventoried_only=True)
    case.update(calc.underwritten_value(
        base_tons=base_tons,
        acres=acres,
        species_code=species,
        discount_pct=prop["market_access_discount_pct"],
        growth_variant=case["growth_variant"],
        discount_rate_bps=case["discount_rate_bps"],
        stumpage_price_usd_per_ton=case["stumpage_price_usd_per_ton"],
        hbu_acres=prop["hbu_acres"],
        hbu_price_per_acre_usd=prop["hbu_price_per_acre_usd"],
        annual_rec_income_usd=prop["annual_rec_income_usd"],
    ))


@bp.post("/underwriting-cases")
def create_case():
    user_id = middleware.require("AcquisitionAnalyst")
    body = validate.json_body()

    raw_property_id = validate.opt_str_id(body, "property_id")
    prop = None
    if raw_property_id is not None:
        prop = services.find(store.properties, raw_property_id, "ERR_PROPERTY_NOT_FOUND")

    property_id = validate.string(body, "property_id")
    growth_variant = validate.enum(body, "growth_variant", calc.GROWTH_VARIANTS)
    discount_rate_bps = validate.integer(body, "discount_rate_bps", 1, 5000)
    stumpage = validate.number(body, "stumpage_price_usd_per_ton", minimum=0,
                               exclusive_min=True, dp=2)
    bid = validate.number(body, "bid_price_usd", minimum=0, exclusive_min=True, dp=2)
    expected_property_version = validate.integer(body, "expected_property_version")
    if prop is None:
        prop = services.find(store.properties, property_id, "ERR_PROPERTY_NOT_FOUND")

    if expected_property_version != prop["version"]:
        raise ApiError("ERR_STALE_PROPERTY_VERSION")

    rec = db.base_fields()
    rec.update({
        "property_id": prop["id"],
        "growth_variant": growth_variant,
        "discount_rate_bps": discount_rate_bps,
        "stumpage_price_usd_per_ton": stumpage,
        "bid_price_usd": bid,
        "status": "DRAFT",
        "revision_count": 0,
        "authored_by_user_id": user_id,
        "decided_by_user_id": None,
        "decision_note": None,
    })
    revalue(rec, prop)
    store.underwriting_cases[rec["id"]] = rec
    services.mark(prop)
    return response.created(serializers.underwriting_case(rec))


@bp.get("/underwriting-cases/<case_id>")
def get_case(case_id):
    middleware.require(*middleware.ANY_ROLE)
    case = services.find(store.underwriting_cases, case_id,
                         "ERR_UNDERWRITING_CASE_NOT_FOUND")
    return response.ok(serializers.underwriting_case(case))


@bp.post("/underwriting-cases/<case_id>/submit")
def submit_case(case_id):
    middleware.require("AcquisitionAnalyst")
    case = services.find(store.underwriting_cases, case_id,
                         "ERR_UNDERWRITING_CASE_NOT_FOUND")
    prop = store.properties.get(case["property_id"])

    if case["status"] not in ("DRAFT", "REVISION_REQUESTED"):
        raise ApiError("ERR_INVALID_STATE_TRANSITION")
    if prop["status"] not in ("PROSPECT", "UNDER_UNDERWRITING"):
        raise ApiError("ERR_INVALID_STATE_TRANSITION")

    # The stack is rebuilt before the bid is tested, so a cruise or a hazard
    # event since the last submission is reflected in the ceiling.
    revalue(case, prop)
    if calc.D(case["bid_price_usd"]) > calc.D(case["underwritten_value_usd"]):
        raise ApiError("ERR_BID_EXCEEDS_UNDERWRITTEN_VALUE")

    if case["status"] == "REVISION_REQUESTED":
        case["decision_note"] = None
    case["status"] = "SUBMITTED"
    services.mark(case)
    prop["status"] = "UNDER_UNDERWRITING"
    services.mark(prop)
    return response.ok(serializers.underwriting_case(case))


@bp.post("/underwriting-cases/<case_id>/decide")
def decide_case(case_id):
    user_id = middleware.require("InvestmentCommittee")
    case = services.find(store.underwriting_cases, case_id,
                         "ERR_UNDERWRITING_CASE_NOT_FOUND")
    body = validate.json_body()
    decision = validate.enum(body, "decision",
                             ("APPROVE", "REJECT", "REQUEST_REVISION"))
    note = validate.string(body, "decision_note", 1, None, required=False)

    if case["authored_by_user_id"] == user_id:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES")
    if case["status"] != "SUBMITTED":
        raise ApiError("ERR_INVALID_STATE_TRANSITION")
    if decision == "REQUEST_REVISION" and case["revision_count"] >= calc.MAX_REVISION_ROUNDS:
        raise ApiError("ERR_REVISION_LIMIT_REACHED")

    prop = store.properties.get(case["property_id"])
    case["decided_by_user_id"] = user_id
    if note is not None:
        case["decision_note"] = note

    if decision == "APPROVE":
        case["status"] = "APPROVED"
        prop["status"] = "APPROVED_FOR_BID"
        for sibling in services.rows(store.underwriting_cases,
                                     property_id=prop["id"]):
            if sibling["id"] == case["id"]:
                continue
            if sibling["status"] in NON_TERMINAL_CASE_STATES:
                sibling["status"] = "WITHDRAWN"
                sibling["decision_note"] = "superseded by approved case"
                services.mark(sibling)
    elif decision == "REJECT":
        case["status"] = "REJECTED"
        prop["status"] = "PASSED"
    else:
        case["status"] = "REVISION_REQUESTED"
        case["revision_count"] += 1

    services.mark(case)
    services.mark(prop)
    return response.ok(serializers.underwriting_case(case))
