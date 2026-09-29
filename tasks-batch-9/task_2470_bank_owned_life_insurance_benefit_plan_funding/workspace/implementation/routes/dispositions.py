"""Disposition analysis, tax consequences and execution (PRD 3.8)."""

from decimal import Decimal

from flask import Blueprint

import calc
from cascades import rerate_carrier, unmatch_policy_from_plans
from errors import ApiError
from response import collection_response, resource_response
from store import create_record, db, ordered, touch
from validation import (
    authorize,
    find_analysis,
    find_carrier,
    find_policy,
    get_datetime,
    get_enum,
    get_id,
    get_int,
    get_money,
    get_string,
    guard_terminal,
    guard_transition,
    json_body,
    pagination,
    query_enum,
    query_str,
)

bp = Blueprint("dispositions", __name__)

DISPOSITION_TYPES = ("FULL_SURRENDER", "PARTIAL_SURRENDER", "EXCHANGE_1035")
ANALYSIS_STATUSES = ("DRAFT", "REVIEWED", "COMMITTED", "EXECUTED", "ABANDONED", "REJECTED")
TERMINAL = ("EXECUTED", "ABANDONED", "REJECTED")
READ_ROLES = ("TreasuryController", "RiskOfficer")
ZERO = Decimal("0.00")


def _product_of(policy):
    product = db.product_types.get(policy["product_type_id"])
    if product is None:
        raise ApiError("ERR_PRODUCT_TYPE_NOT_FOUND")
    return product


def _figures(policy, disposition_type, requested_withdrawal):
    product = _product_of(policy)
    return calc.policy_taxable_gain(policy, product, disposition_type, requested_withdrawal)


def _policy_of(analysis):
    policy = db.policies.get(analysis["policy_id"])
    if policy is None:
        raise ApiError("ERR_POLICY_NOT_FOUND")
    return policy


@bp.post("/exchange-analyses")
def create_analysis():
    authorize(("TreasuryController",))
    body = json_body()
    policy_id = get_id(body, "policy_id")
    disposition_type = get_enum(body, "disposition_type", DISPOSITION_TYPES)
    replacement_carrier_id = get_id(body, "replacement_carrier_id", required=False)
    requested_withdrawal = get_money(
        body, "requested_withdrawal_usd", required=False, default=ZERO
    )
    expected_policy_version = get_int(body, "expected_policy_version", required=True)
    if disposition_type != "PARTIAL_SURRENDER" and requested_withdrawal != 0:
        raise ApiError(
            "ERR_INVALID_REQUEST",
            "Field 'requested_withdrawal_usd' must be 0.00 for this disposition_type.",
        )

    policy = find_policy(policy_id)
    if replacement_carrier_id is not None:
        find_carrier(replacement_carrier_id)

    if int(policy["version"]) != expected_policy_version:
        raise ApiError("ERR_STALE_POLICY_VERSION")

    if disposition_type == "EXCHANGE_1035":
        if replacement_carrier_id is None:
            raise ApiError("ERR_PRODUCT_CARRIER_MISMATCH")
    elif replacement_carrier_id is not None:
        raise ApiError("ERR_PRODUCT_CARRIER_MISMATCH")

    if disposition_type == "PARTIAL_SURRENDER":
        if requested_withdrawal > policy["cash_surrender_value_usd"]:
            raise ApiError("ERR_SURRENDER_EXCEEDS_CASH_VALUE")

    figures = _figures(policy, disposition_type, requested_withdrawal)
    analysis = create_record(
        db.exchange_analyses,
        {
            "policy_id": policy["id"],
            "replacement_carrier_id": replacement_carrier_id,
            "disposition_type": disposition_type,
            "requested_withdrawal_usd": requested_withdrawal,
            "cost_recovery_method": figures["cost_recovery_method"],
            "taxable_gain_usd": figures["taxable_gain_usd"],
            "surrender_charge_usd": figures["surrender_charge_usd"],
            "tax_liability_usd": figures["tax_liability_usd"],
            "net_proceeds_usd": figures["net_proceeds_usd"],
            "status": "DRAFT",
            "resulting_policy_id": None,
            "_pre_commit_cost_basis_usd": None,
            "_pre_commit_cash_value_usd": None,
        },
    )

    # superseding create: every other DRAFT or REVIEWED analysis is rejected
    for other in ordered(list(db.exchange_analyses.values())):
        if other["id"] == analysis["id"] or other["policy_id"] != policy["id"]:
            continue
        if other["status"] in ("DRAFT", "REVIEWED"):
            other["status"] = "REJECTED"
            touch(other)

    touch(policy)
    return resource_response(analysis, 201)


@bp.get("/exchange-analyses")
def list_analyses():
    authorize(READ_ROLES)
    limit, offset = pagination()
    policy_id = query_str("policy_id")
    replacement_carrier_id = query_str("replacement_carrier_id")
    resulting_policy_id = query_str("resulting_policy_id")
    status = query_enum("status", ANALYSIS_STATUSES)
    rows = []
    for analysis in db.exchange_analyses.values():
        if policy_id is not None and analysis["policy_id"] != policy_id:
            continue
        if (
            replacement_carrier_id is not None
            and analysis.get("replacement_carrier_id") != replacement_carrier_id
        ):
            continue
        if (
            resulting_policy_id is not None
            and analysis.get("resulting_policy_id") != resulting_policy_id
        ):
            continue
        if status is not None and analysis["status"] != status:
            continue
        rows.append(analysis)
    return collection_response(rows, limit, offset)


@bp.get("/exchange-analyses/<analysis_id>")
def read_analysis(analysis_id):
    authorize(READ_ROLES)
    return resource_response(find_analysis(analysis_id))


@bp.post("/exchange-analyses/<analysis_id>/review")
def review_analysis(analysis_id):
    authorize(("RiskOfficer",))
    analysis = find_analysis(analysis_id)
    guard_terminal(analysis["status"], TERMINAL)
    guard_transition(analysis["status"] == "DRAFT")
    policy = _policy_of(analysis)
    guard_transition(policy["status"] == "IN_FORCE")

    figures = _figures(policy, analysis["disposition_type"], analysis["requested_withdrawal_usd"])
    analysis.update(figures)
    analysis["status"] = "REVIEWED"
    touch(analysis)
    return resource_response(analysis)


@bp.post("/exchange-analyses/<analysis_id>/reject")
def reject_analysis(analysis_id):
    authorize(("RiskOfficer",))
    analysis = find_analysis(analysis_id)
    guard_terminal(analysis["status"], TERMINAL)
    guard_transition(analysis["status"] == "REVIEWED")
    analysis["status"] = "REJECTED"
    touch(analysis)
    return resource_response(analysis)


@bp.post("/exchange-analyses/<analysis_id>/commit")
def commit_analysis(analysis_id):
    authorize(("TreasuryController",))
    analysis = find_analysis(analysis_id)
    guard_terminal(analysis["status"], TERMINAL)
    guard_transition(analysis["status"] == "REVIEWED")
    policy = _policy_of(analysis)
    guard_transition(policy["status"] == "IN_FORCE")

    analysis["_pre_commit_cost_basis_usd"] = policy["cost_basis_usd"]
    analysis["_pre_commit_cash_value_usd"] = policy["cash_surrender_value_usd"]
    analysis["status"] = "COMMITTED"
    touch(analysis)

    policy["status"] = "PENDING_EXCHANGE"
    touch(policy)
    return resource_response(analysis)


@bp.post("/exchange-analyses/<analysis_id>/abandon")
def abandon_analysis(analysis_id):
    authorize(("TreasuryController",))
    analysis = find_analysis(analysis_id)
    guard_terminal(analysis["status"], TERMINAL)
    guard_transition(analysis["status"] == "COMMITTED")
    policy = _policy_of(analysis)
    guard_transition(policy["status"] == "PENDING_EXCHANGE")

    analysis["status"] = "ABANDONED"
    touch(analysis)

    if analysis["_pre_commit_cost_basis_usd"] is not None:
        policy["cost_basis_usd"] = analysis["_pre_commit_cost_basis_usd"]
    if analysis["_pre_commit_cash_value_usd"] is not None:
        policy["cash_surrender_value_usd"] = analysis["_pre_commit_cash_value_usd"]
    policy["status"] = "IN_FORCE"
    touch(policy)
    return resource_response(analysis)


@bp.post("/exchange-analyses/<analysis_id>/execute-exchange")
def execute_exchange(analysis_id):
    authorize(("TreasuryController",))
    body = json_body()
    policy_number = get_string(body, "policy_number")
    raw_issue_date, issue_date = get_datetime(body, "issue_date")

    analysis = find_analysis(analysis_id)
    guard_terminal(analysis["status"], TERMINAL)
    guard_transition(analysis["status"] == "COMMITTED")
    guard_transition(analysis["disposition_type"] == "EXCHANGE_1035")
    policy = _policy_of(analysis)
    guard_transition(policy["status"] == "PENDING_EXCHANGE")

    replacement_carrier_id = analysis.get("replacement_carrier_id")
    guard_transition(replacement_carrier_id is not None)
    replacement_carrier = db.carriers.get(replacement_carrier_id)
    if replacement_carrier is None:
        raise ApiError("ERR_CARRIER_NOT_FOUND")
    if replacement_carrier["status"] != "AUTHORIZED":
        raise ApiError("ERR_CARRIER_RESTRICTED")

    successor = create_record(
        db.policies,
        {
            "purchase_request_id": None,
            "carrier_id": replacement_carrier["id"],
            "product_type_id": policy["product_type_id"],
            "employee_id": policy["employee_id"],
            "exchanged_from_policy_id": policy["id"],
            "policy_number": policy_number,
            "issue_date": raw_issue_date,
            "_issue_date": issue_date,
            "single_premium_usd": analysis["net_proceeds_usd"],
            "face_amount_usd": policy["face_amount_usd"],
            "cost_basis_usd": policy["cost_basis_usd"],
            "cash_surrender_value_usd": analysis["net_proceeds_usd"],
            "policy_year": 1,
            "status": "IN_FORCE",
        },
    )

    analysis["status"] = "EXECUTED"
    analysis["resulting_policy_id"] = successor["id"]
    touch(analysis)

    policy["status"] = "EXCHANGED"
    touch(policy)

    old_carrier = db.carriers.get(policy["carrier_id"])
    if old_carrier is not None:
        rerate_carrier(old_carrier)
    rerate_carrier(replacement_carrier)
    return resource_response(successor, 201)


@bp.post("/exchange-analyses/<analysis_id>/execute-surrender")
def execute_surrender(analysis_id):
    authorize(("TreasuryController",))
    analysis = find_analysis(analysis_id)
    guard_terminal(analysis["status"], TERMINAL)
    guard_transition(analysis["status"] == "COMMITTED")
    guard_transition(analysis["disposition_type"] in ("FULL_SURRENDER", "PARTIAL_SURRENDER"))
    policy = _policy_of(analysis)
    guard_transition(policy["status"] == "PENDING_EXCHANGE")

    analysis["status"] = "EXECUTED"
    touch(analysis)

    if analysis["disposition_type"] == "FULL_SURRENDER":
        policy["cash_surrender_value_usd"] = ZERO
    else:
        remaining = policy["cash_surrender_value_usd"] - analysis["requested_withdrawal_usd"]
        if remaining < 0:
            remaining = ZERO
        policy["cash_surrender_value_usd"] = remaining
    policy["status"] = "SURRENDERED"
    touch(policy)

    carrier = db.carriers.get(policy["carrier_id"])
    if carrier is not None:
        rerate_carrier(carrier)

    unmatch_policy_from_plans(policy)
    return resource_response(analysis)
