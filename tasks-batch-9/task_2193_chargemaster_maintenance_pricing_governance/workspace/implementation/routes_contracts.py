"""Payer contracts and price-change impact analyses (PRD 3.6)."""

from datetime import timedelta

from flask import Blueprint

import validate
from auth import CM, CO, PCA, RIA, SA, require
from calc import payer_impact_delta
from derive import find, stale_analyses_for_facility
from envelope import list_response, ok
from errors import fail
from routes_facilities import body_facility
from store import STORE, fmt_iso, serialize

bp = Blueprint("routes_contracts", __name__)

PRODUCT_LINES = ("COMMERCIAL", "MEDICARE_ADVANTAGE", "MEDICAID_MCO")
REIMBURSEMENT_METHODS = ("PERCENT_OF_CHARGE", "LESSER_OF_FEE_SCHEDULE", "CASE_RATE")
VARIANTS = ("FORWARD_PROJECTED", "HISTORICAL_REPLAY")
CONTRACT_READERS = [SA, CM, CO, RIA, PCA]
ANALYSIS_READERS = [SA, CM, RIA, PCA, CO]


@bp.route("/chargemaster/payer-contracts", methods=["POST"])
def create_payer_contract():
    require(CM)
    data = validate.body()
    facility = body_facility(data)
    payer_code = validate.req_string(data, "payer_code")
    product_line = validate.req_enum(data, "product_line", PRODUCT_LINES)
    method = validate.req_enum(data, "reimbursement_method", REIMBURSEMENT_METHODS)
    term_start = validate.req_dt(data, "term_start_date")
    term_end = validate.req_dt(data, "term_end_date")
    percent_bp = validate.opt_int(data, "percent_of_charge_bp")
    fee_schedule = validate.opt_int(data, "fee_schedule_cents")
    case_rate = validate.opt_int(data, "case_rate_cents")
    trailing_units = validate.opt_int(data, "trailing_units", 0)
    notice_days = validate.opt_int(data, "renegotiation_notice_days", 30)
    if term_end < term_start:
        fail("ERR_VALIDATION", "term_end_date must be no earlier than term_start_date.")
    if method != "CASE_RATE" and percent_bp is None:
        fail("ERR_VALIDATION", "percent_of_charge_bp is required for this method.")
    if method == "LESSER_OF_FEE_SCHEDULE" and fee_schedule is None:
        fail("ERR_VALIDATION", "fee_schedule_cents is required for LESSER_OF_FEE_SCHEDULE.")
    if method == "CASE_RATE" and case_rate is None:
        fail("ERR_VALIDATION", "case_rate_cents is required for CASE_RATE.")

    scope = []
    for row in STORE.ordered(STORE.payer_contracts):
        if row["facility_id"] != facility["id"]:
            continue
        if row["payer_code"] != payer_code:
            continue
        if row["product_line"] != product_line:
            continue
        if row["status"] not in ("ACTIVE", "EXPIRED"):
            continue
        scope.append(row)

    for row in scope:
        if row["_term_start"] <= term_end and term_start <= row["_term_end"]:
            fail(
                "ERR_CONTRACT_TERM_OVERLAP",
                "A term for this payer scope already covers part of this interval.",
            )

    priors = [row for row in scope if row["_term_end"] < term_start]
    if priors:
        prior = max(priors, key=lambda r: r["_term_end"])
        gap = term_start - prior["_term_end"]
        if not gap > timedelta(days=prior["renegotiation_notice_days"]):
            fail(
                "ERR_CONTRACT_TERM_BUFFER_VIOLATION",
                "The gap after the prior term must exceed %d days."
                % prior["renegotiation_notice_days"],
            )

    contract = {
        "facility_id": facility["id"],
        "payer_code": payer_code,
        "product_line": product_line,
        "reimbursement_method": method,
        "percent_of_charge_bp": percent_bp,
        "fee_schedule_cents": fee_schedule if method == "LESSER_OF_FEE_SCHEDULE" else None,
        "case_rate_cents": case_rate if method == "CASE_RATE" else None,
        "term_start_date": fmt_iso(term_start),
        "term_end_date": fmt_iso(term_end),
        "status": "ACTIVE",
        "trailing_units": trailing_units,
        "renegotiation_notice_days": notice_days,
        "_term_start": term_start,
        "_term_end": term_end,
    }
    STORE.stamp_new(contract)
    STORE.payer_contracts[contract["id"]] = contract
    stale_analyses_for_facility(facility["id"])
    return ok(serialize(contract), 201)


@bp.route("/chargemaster/payer-contracts", methods=["GET"])
def list_payer_contracts():
    require(CONTRACT_READERS)
    facility_id = validate.query_filter("facility_id")
    payer_code = validate.query_filter("payer_code")
    product_line = validate.query_filter("product_line")
    status = validate.query_filter("status")

    def keep(row):
        if facility_id is not None and row["facility_id"] != facility_id:
            return False
        if payer_code is not None and row["payer_code"] != payer_code:
            return False
        if product_line is not None and row["product_line"] != product_line:
            return False
        if status is not None and row["status"] != status:
            return False
        return True

    return list_response(STORE.ordered(STORE.payer_contracts, keep), serialize)


@bp.route("/chargemaster/payer-contracts/<payer_contract_id>", methods=["GET"])
def read_payer_contract(payer_contract_id):
    require(CONTRACT_READERS)
    row = find(
        STORE.payer_contracts,
        payer_contract_id,
        "ERR_GOVERNANCE_RESOURCE_NOT_FOUND",
        "PayerContract",
    )
    return ok(serialize(row))


@bp.route("/chargemaster/payer-contracts/<payer_contract_id>/terminate", methods=["POST"])
def terminate_payer_contract(payer_contract_id):
    require(CM)
    contract = find(
        STORE.payer_contracts,
        payer_contract_id,
        "ERR_GOVERNANCE_RESOURCE_NOT_FOUND",
        "PayerContract",
    )
    data = validate.body()
    validate.opt_string(data, "termination_note")
    contract["status"] = "TERMINATED"
    STORE.touch(contract)
    stale_analyses_for_facility(contract["facility_id"])
    return ok(serialize(contract))


# ---------------------------------------------------------------------------
# Price change impact analyses
# ---------------------------------------------------------------------------
@bp.route("/chargemaster/price-change-analyses", methods=["POST"])
def create_analysis():
    require([CM, RIA])
    data = validate.body()
    request_row = None
    if "change_request_id" in data and isinstance(data.get("change_request_id"), str):
        request_row = STORE.change_requests.get(data["change_request_id"])
        if request_row is None:
            fail(
                "ERR_REFERENCED_RESOURCE_NOT_FOUND",
                "ChangeRequest %s does not exist." % data["change_request_id"],
            )
    else:
        validate.req_id(data, "change_request_id")
    variant = validate.req_enum(data, "variant", VARIANTS)

    item = STORE.charge_items.get(request_row["charge_item_id"])
    facility = STORE.facilities.get(item["facility_id"])
    old_gross = item["gross_charge_cents"]
    new_gross = request_row.get("projected_gross_charge_cents") or 0
    payer_lines, total = payer_impact_delta(variant, facility, item, old_gross, new_gross)

    analysis = {
        "change_request_id": request_row["id"],
        "variant": variant,
        "analysed_charge_item_version": item["version"],
        "old_gross_charge_cents": old_gross,
        "new_gross_charge_cents": new_gross,
        "payer_lines": payer_lines,
        "total_reimbursement_delta_cents": total,
        "status": "COMPUTED",
        "signed_off_by_user_id": None,
    }
    STORE.stamp_new(analysis)
    STORE.analyses[analysis["id"]] = analysis
    return ok(serialize(analysis), 201)


@bp.route("/chargemaster/price-change-analyses", methods=["GET"])
def list_analyses():
    require(ANALYSIS_READERS)
    change_request_id = validate.query_filter("change_request_id")
    variant = validate.query_filter("variant")
    status = validate.query_filter("status")

    def keep(row):
        if change_request_id is not None and row["change_request_id"] != change_request_id:
            return False
        if variant is not None and row["variant"] != variant:
            return False
        if status is not None and row["status"] != status:
            return False
        return True

    return list_response(STORE.ordered(STORE.analyses, keep), serialize)


@bp.route("/chargemaster/price-change-analyses/<analysis_id>", methods=["GET"])
def read_analysis(analysis_id):
    require(ANALYSIS_READERS)
    row = find(
        STORE.analyses,
        analysis_id,
        "ERR_GOVERNANCE_RESOURCE_NOT_FOUND",
        "PriceChangeImpactAnalysis",
    )
    return ok(serialize(row))


@bp.route("/chargemaster/price-change-analyses/<analysis_id>/sign-off", methods=["POST"])
def sign_off_analysis(analysis_id):
    user_id, _role = require(CO)
    analysis = find(
        STORE.analyses,
        analysis_id,
        "ERR_GOVERNANCE_RESOURCE_NOT_FOUND",
        "PriceChangeImpactAnalysis",
    )
    data = validate.body()
    validate.opt_string(data, "signoff_note")
    if analysis["status"] not in ("COMPUTED", "STALE"):
        fail(
            "ERR_INVALID_ANALYSIS_STATE",
            "An analysis in %s cannot be signed off." % analysis["status"],
        )
    if analysis["status"] == "STALE":
        fail("ERR_ANALYSIS_SIGNOFF_STALE", "The analysis is STALE.")
    request_row = STORE.change_requests.get(analysis["change_request_id"])
    item = STORE.charge_items.get(request_row["charge_item_id"]) if request_row else None
    if item is None or analysis["analysed_charge_item_version"] != item["version"]:
        fail(
            "ERR_ANALYSIS_SIGNOFF_STALE",
            "The analysed charge item version no longer matches.",
        )
    analysis["status"] = "SIGNED_OFF"
    analysis["signed_off_by_user_id"] = user_id
    STORE.touch(analysis)
    return ok(serialize(analysis))
