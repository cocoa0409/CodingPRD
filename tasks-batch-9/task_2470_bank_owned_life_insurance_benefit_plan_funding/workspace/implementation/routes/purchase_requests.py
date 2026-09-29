"""Purchase requests: gates, capacity, notification and approval (PRD 3.3, 3.4)."""

from decimal import Decimal

from flask import Blueprint

import calc
from cascades import refresh_carrier_totals
from errors import ApiError
from response import collection_response, object_response, resource_response
from store import create_record, db, touch
from validation import (
    actor,
    authorize,
    find_carrier,
    find_employee,
    find_product_type,
    find_purchase_request,
    get_datetime,
    get_id,
    get_int,
    get_money,
    guard_terminal,
    guard_transition,
    is_liaison,
    json_body,
    liaison_carrier_id,
    pagination,
    query_enum,
    query_str,
    scope_check,
)
from util import add_days

bp = Blueprint("purchase_requests", __name__)

REQUEST_STATUSES = (
    "DRAFT",
    "SUBMITTED",
    "DILIGENCE_CLEARED",
    "CAPACITY_RESERVED",
    "NOTICE_FILED",
    "CONCURRENCE_PENDING",
    "APPROVED",
    "ISSUED",
    "REJECTED",
    "WITHDRAWN",
)
TERMINAL = ("ISSUED", "REJECTED", "WITHDRAWN")
ZERO = Decimal("0.00")


def _carrier_of(request):
    carrier = db.carriers.get(request["carrier_id"])
    if carrier is None:
        raise ApiError("ERR_CARRIER_NOT_FOUND")
    return carrier


def _product_of(request):
    product = db.product_types.get(request["product_type_id"])
    if product is None:
        raise ApiError("ERR_PRODUCT_TYPE_NOT_FOUND")
    return product


@bp.post("/purchase-requests")
def draft_request():
    authorize(("BenefitsAnalyst",))
    body = json_body()
    carrier_id = get_id(body, "carrier_id")
    product_type_id = get_id(body, "product_type_id")
    employee_id = get_id(body, "employee_id")
    single_premium = get_money(body, "single_premium_usd", positive_only=True)
    face_amount = get_money(body, "face_amount_usd", positive_only=True)
    raw_effective, effective = get_datetime(body, "requested_effective_date")

    find_carrier(carrier_id)
    product = find_product_type(product_type_id)
    find_employee(employee_id)
    if product["carrier_id"] != carrier_id:
        raise ApiError("ERR_PRODUCT_CARRIER_MISMATCH")

    request = create_record(
        db.purchase_requests,
        {
            "carrier_id": carrier_id,
            "product_type_id": product_type_id,
            "employee_id": employee_id,
            "single_premium_usd": single_premium,
            "face_amount_usd": face_amount,
            "requested_effective_date": raw_effective,
            "_requested_effective_date": effective,
            "status": "DRAFT",
            "reserved_premium_usd": ZERO,
            "base_ratio_bps": 0,
            "effective_limit_pct": Decimal("0"),
            "aggregate_limit_usd": ZERO,
            "headroom_usd": ZERO,
            "carrier_concentration_bps": 0,
            "notice_required": False,
            "notice_filed_at": None,
            "notice_waiting_ends_at": None,
            "concurrence_requested_at": None,
            "submitted_by_user_id": None,
            "approved_by_user_id": None,
        },
    )
    return resource_response(request, 201)


@bp.get("/purchase-requests")
def list_requests():
    authorize(("BenefitsAnalyst", "RiskOfficer", "TreasuryController", "CarrierLiaison"))
    limit, offset = pagination()
    carrier_id = query_str("carrier_id")
    product_type_id = query_str("product_type_id")
    employee_id = query_str("employee_id")
    status = query_enum("status", REQUEST_STATUSES)
    if is_liaison():
        scope_check(carrier_id)
        carrier_id = liaison_carrier_id()
    rows = []
    for request in db.purchase_requests.values():
        if carrier_id is not None and request["carrier_id"] != carrier_id:
            continue
        if product_type_id is not None and request["product_type_id"] != product_type_id:
            continue
        if employee_id is not None and request["employee_id"] != employee_id:
            continue
        if status is not None and request["status"] != status:
            continue
        rows.append(request)
    return collection_response(rows, limit, offset)


@bp.get("/purchase-requests/<request_id>")
def read_request(request_id):
    authorize(("BenefitsAnalyst", "RiskOfficer", "TreasuryController"))
    return resource_response(find_purchase_request(request_id))


@bp.get("/purchase-requests/<request_id>/capacity-projection")
def capacity_projection(request_id):
    authorize(("RiskOfficer", "TreasuryController"))
    request = find_purchase_request(request_id)
    carrier = _carrier_of(request)
    product = _product_of(request)
    return object_response(calc.purchase_capacity_headroom(request, carrier, product))


@bp.post("/purchase-requests/<request_id>/submit")
def submit_request(request_id):
    authorize(("BenefitsAnalyst",))
    request = find_purchase_request(request_id)
    guard_terminal(request["status"], TERMINAL)
    guard_transition(request["status"] == "DRAFT")

    employee = db.employees.get(request["employee_id"])
    if employee is None:
        raise ApiError("ERR_EMPLOYEE_NOT_FOUND")

    effective = request["_requested_effective_date"]
    covering = [
        record
        for record in db.consent_records.values()
        if record["employee_id"] == employee["id"]
        and record["_coverage_start_date"] <= effective <= record["_coverage_end_date"]
    ]
    executed = [record for record in covering if record["status"] == "EXECUTED"]
    if not executed:
        if any(record["status"] in ("REVOKED", "EXPIRED") for record in covering):
            raise ApiError("ERR_CONSENT_EXPIRED")
        raise ApiError("ERR_CONSENT_MISSING")
    if all(record["_coverage_end_date"] < db.now() for record in executed):
        raise ApiError("ERR_CONSENT_EXPIRED")

    if employee["insurable_interest_status"] != "ESTABLISHED":
        raise ApiError("ERR_INSURABLE_INTEREST_NOT_ESTABLISHED")

    product = _product_of(request)
    if product["carrier_id"] != request["carrier_id"]:
        raise ApiError("ERR_PRODUCT_CARRIER_MISMATCH")

    request["status"] = "SUBMITTED"
    request["notice_required"] = calc.notice_required(request["single_premium_usd"])
    request["submitted_by_user_id"] = actor()
    touch(request)
    return resource_response(request)


@bp.post("/purchase-requests/<request_id>/clear-diligence")
def clear_diligence(request_id):
    authorize(("RiskOfficer",))
    request = find_purchase_request(request_id)
    guard_terminal(request["status"], TERMINAL)
    guard_transition(request["status"] == "SUBMITTED")
    carrier = _carrier_of(request)

    # Validation ladder (section 2.11): the diligence-decision family is evaluated
    # before the exposure-constraint family, so a carrier with no approved file
    # reports ERR_DILIGENCE_NOT_CLEARED even when its posture also blocks clearance.
    approved = [
        review
        for review in db.diligence_reviews.values()
        if review["carrier_id"] == carrier["id"] and review["status"] == "APPROVED"
    ]
    if not approved:
        raise ApiError("ERR_DILIGENCE_NOT_CLEARED")
    latest = max(approved, key=lambda r: r["review_year"])
    if int(latest["financial_strength_score"]) < calc.MIN_APPROVAL_SCORE:
        raise ApiError("ERR_DILIGENCE_NOT_CLEARED")

    product = _product_of(request)
    if product["status"] == "CLOSED_TO_NEW":
        raise ApiError("ERR_PRODUCT_CLOSED_TO_NEW")
    if carrier["status"] != "AUTHORIZED":
        raise ApiError("ERR_CARRIER_RESTRICTED")

    request["status"] = "DILIGENCE_CLEARED"
    touch(request)
    return resource_response(request)


@bp.post("/purchase-requests/<request_id>/reserve-capacity")
def reserve_capacity(request_id):
    authorize(("TreasuryController",))
    body = json_body()
    expected_carrier_version = get_int(body, "expected_carrier_version", required=True)
    request = find_purchase_request(request_id)
    guard_terminal(request["status"], TERMINAL)
    guard_transition(request["status"] == "DILIGENCE_CLEARED")

    carrier = _carrier_of(request)
    if int(carrier["version"]) != expected_carrier_version:
        raise ApiError("ERR_STALE_CARRIER_VERSION")

    product = _product_of(request)
    if product["status"] == "CLOSED_TO_NEW":
        raise ApiError("ERR_PRODUCT_CLOSED_TO_NEW")
    if carrier["status"] in ("RESTRICTED", "SUSPENDED", "TERMINATED"):
        raise ApiError("ERR_CARRIER_RESTRICTED")

    figures = calc.purchase_capacity_headroom(request, carrier, product)
    if figures["carrier_concentration_bps"] > figures["single_carrier_limit_bps"]:
        raise ApiError("ERR_CARRIER_CONCENTRATION_EXCEEDED")
    if figures["headroom_usd"] < 0:
        raise ApiError("ERR_CAPITAL_CAPACITY_EXCEEDED")

    request["base_ratio_bps"] = figures["base_ratio_bps"]
    request["effective_limit_pct"] = figures["effective_limit_pct"]
    request["aggregate_limit_usd"] = figures["aggregate_limit_usd"]
    request["headroom_usd"] = figures["headroom_usd"]
    request["carrier_concentration_bps"] = figures["carrier_concentration_bps"]
    request["reserved_premium_usd"] = request["single_premium_usd"]
    request["status"] = "CAPACITY_RESERVED"
    touch(request)

    refresh_carrier_totals(carrier)
    touch(carrier)
    return resource_response(request)


@bp.post("/purchase-requests/<request_id>/file-notice")
def file_notice(request_id):
    authorize(("TreasuryController",))
    request = find_purchase_request(request_id)
    guard_terminal(request["status"], TERMINAL)
    guard_transition(request["status"] == "CAPACITY_RESERVED")
    guard_transition(request["notice_required"] is True)

    now = db.now()
    request["notice_filed_at"] = now
    request["notice_waiting_ends_at"] = add_days(now, calc.NOTICE_WAITING_PERIOD_DAYS)
    request["status"] = "NOTICE_FILED"
    touch(request)

    carrier = _carrier_of(request)
    carrier["regulatory_notice_count"] = int(carrier["regulatory_notice_count"]) + 1
    touch(carrier)
    return resource_response(request)


@bp.post("/purchase-requests/<request_id>/request-concurrence")
def request_concurrence(request_id):
    authorize(("BenefitsAnalyst",))
    request = find_purchase_request(request_id)
    guard_terminal(request["status"], TERMINAL)
    if request["status"] == "CAPACITY_RESERVED":
        guard_transition(request["notice_required"] is not True)
    elif request["status"] == "NOTICE_FILED":
        guard_transition(request["notice_filed_at"] is not None)
    else:
        guard_transition(False)

    request["concurrence_requested_at"] = db.now()
    request["status"] = "CONCURRENCE_PENDING"
    touch(request)
    return resource_response(request)


@bp.post("/purchase-requests/<request_id>/approve")
def approve_request(request_id):
    authorize(("RiskOfficer",))
    request = find_purchase_request(request_id)
    guard_terminal(request["status"], TERMINAL)
    guard_transition(request["status"] == "CONCURRENCE_PENDING")
    if actor() == request["submitted_by_user_id"]:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES")
    if request["notice_filed_at"] is not None:
        if db.now() < request["notice_waiting_ends_at"]:
            raise ApiError("ERR_NOTICE_WAITING_PERIOD_ACTIVE")

    request["status"] = "APPROVED"
    request["approved_by_user_id"] = actor()
    touch(request)
    return resource_response(request)


def _release_premium(request):
    carrier = _carrier_of(request)
    request["reserved_premium_usd"] = ZERO
    refresh_carrier_totals(carrier)
    touch(carrier)


@bp.post("/purchase-requests/<request_id>/reject")
def reject_request(request_id):
    authorize(("RiskOfficer",))
    request = find_purchase_request(request_id)
    guard_terminal(request["status"], TERMINAL)
    guard_transition(
        request["status"]
        in (
            "SUBMITTED",
            "DILIGENCE_CLEARED",
            "CAPACITY_RESERVED",
            "NOTICE_FILED",
            "CONCURRENCE_PENDING",
            "APPROVED",
        )
    )
    request["status"] = "REJECTED"
    _release_premium(request)
    touch(request)
    return resource_response(request)


@bp.post("/purchase-requests/<request_id>/withdraw")
def withdraw_request(request_id):
    authorize(("BenefitsAnalyst",))
    request = find_purchase_request(request_id)
    guard_terminal(request["status"], TERMINAL)
    guard_transition(
        request["status"]
        in (
            "SUBMITTED",
            "DILIGENCE_CLEARED",
            "CAPACITY_RESERVED",
            "NOTICE_FILED",
            "CONCURRENCE_PENDING",
        )
    )
    # withdrawal is the submitter's own compensating action
    guard_transition(actor() == request["submitted_by_user_id"])
    request["status"] = "WITHDRAWN"
    _release_premium(request)
    touch(request)
    return resource_response(request)
