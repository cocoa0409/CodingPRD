"""Carrier onboarding and authorization posture (PRD 3.1)."""

from decimal import Decimal

from flask import Blueprint

import calc
from cascades import rerate_carrier
from errors import ApiError
from response import collection_response, resource_response
from store import create_record, db, touch
from validation import (
    authorize,
    find_carrier,
    get_enum,
    get_money,
    get_string,
    guard_terminal,
    guard_transition,
    is_liaison,
    json_body,
    pagination,
    query_bool,
    query_enum,
    scope_check,
)

bp = Blueprint("carriers", __name__)

CARRIER_STATUSES = (
    "PENDING_DILIGENCE",
    "AUTHORIZED",
    "RESTRICTED",
    "SUSPENDED",
    "TERMINATED",
)
AM_BEST_RATINGS = ("A_PLUS_PLUS", "A_PLUS", "A", "A_MINUS", "B_PLUS_PLUS", "B_PLUS", "B")
READ_ROLES = (
    "PlatformAdmin",
    "BenefitsAnalyst",
    "RiskOfficer",
    "TreasuryController",
    "BoardSecretary",
)
ZERO = Decimal("0.00")


@bp.post("/carriers")
def onboard_carrier():
    authorize(("PlatformAdmin",))
    body = json_body()
    legal_name = get_string(body, "legal_name")
    naic_code = get_string(body, "naic_code")
    am_best_rating = get_enum(body, "am_best_rating", AM_BEST_RATINGS)
    statutory_surplus = get_money(body, "statutory_surplus_usd", positive_only=True)
    domicile_state = get_string(body, "domicile_state")

    carrier = create_record(
        db.carriers,
        {
            "legal_name": legal_name,
            "naic_code": naic_code,
            "am_best_rating": am_best_rating,
            "statutory_surplus_usd": statutory_surplus,
            "domicile_state": domicile_state,
            "status": "PENDING_DILIGENCE",
            "watch_list_flag": False,
            "reserved_premium_usd": ZERO,
            "in_force_premium_usd": ZERO,
            "in_force_cash_value_usd": ZERO,
            "concentration_bps": 0,
            "regulatory_notice_count": 0,
            "last_approved_review_year": None,
        },
    )
    return resource_response(carrier, 201)


@bp.get("/carriers")
def list_carriers():
    authorize(READ_ROLES)
    limit, offset = pagination()
    status = query_enum("status", CARRIER_STATUSES)
    watch_list_flag = query_bool("watch_list_flag")
    rows = []
    for carrier in db.carriers.values():
        if status is not None and carrier["status"] != status:
            continue
        if watch_list_flag is not None and bool(carrier["watch_list_flag"]) != watch_list_flag:
            continue
        rows.append(carrier)
    return collection_response(rows, limit, offset)


@bp.get("/carriers/<carrier_id>")
def read_carrier(carrier_id):
    authorize(READ_ROLES + ("CarrierLiaison",))
    if is_liaison():
        scope_check(carrier_id)
    return resource_response(find_carrier(carrier_id))


@bp.post("/carriers/<carrier_id>/suspend")
def suspend_carrier(carrier_id):
    authorize(("RiskOfficer",))
    carrier = find_carrier(carrier_id)
    guard_terminal(carrier["status"], ("TERMINATED",))
    guard_transition(carrier["status"] in ("AUTHORIZED", "RESTRICTED"))
    carrier["status"] = "SUSPENDED"
    touch(carrier)
    return resource_response(carrier)


@bp.post("/carriers/<carrier_id>/reinstate")
def reinstate_carrier(carrier_id):
    authorize(("RiskOfficer",))
    carrier = find_carrier(carrier_id)
    guard_terminal(carrier["status"], ("TERMINATED",))
    guard_transition(carrier["status"] == "SUSPENDED")
    guard_transition(
        carrier["concentration_bps"] <= calc.CARRIER_RELEASE_BPS
        and carrier["watch_list_flag"] is not True
    )
    carrier["status"] = "AUTHORIZED"
    touch(carrier)
    return resource_response(carrier)


@bp.post("/carriers/<carrier_id>/terminate")
def terminate_carrier(carrier_id):
    authorize(("RiskOfficer",))
    carrier = find_carrier(carrier_id)
    guard_terminal(carrier["status"], ("TERMINATED",))
    guard_transition(carrier["status"] == "SUSPENDED")
    live = [
        policy
        for policy in db.policies.values()
        if policy["carrier_id"] == carrier_id
        and policy["status"] in calc.LIVE_POLICY_STATUSES
    ]
    if live:
        raise ApiError("ERR_INVALID_STATE_TRANSITION")

    carrier["status"] = "TERMINATED"

    for product in db.product_types.values():
        if product["carrier_id"] != carrier_id:
            continue
        if product["status"] in ("OPEN", "ON_WATCH"):
            product["status"] = "CLOSED_TO_NEW"
            touch(product)

    releasable = (
        "SUBMITTED",
        "DILIGENCE_CLEARED",
        "CAPACITY_RESERVED",
        "NOTICE_FILED",
        "CONCURRENCE_PENDING",
        "APPROVED",
    )
    for request in db.purchase_requests.values():
        if request["carrier_id"] != carrier_id:
            continue
        if request["status"] not in releasable:
            continue
        request["status"] = "REJECTED"
        request["reserved_premium_usd"] = ZERO
        touch(request)

    rerate_carrier(carrier)
    return resource_response(carrier)
