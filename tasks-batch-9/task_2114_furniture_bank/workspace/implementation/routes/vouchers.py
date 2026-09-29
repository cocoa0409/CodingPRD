"""Voucher issuance, allocation rounds, billing settlement and withdrawal
(PRD 3.3, 3.6, 3.9).
"""

from decimal import Decimal

from flask import Blueprint

from auth import authenticate, require_agency_scope, resolve
from core import CATEGORIES, GRADES_ABC, clock
from db import (
    db, new_entity, serialize, touch, lines_of_voucher, stops_of_voucher,
    voucher_of_referral, client_of_voucher, referral_of_voucher,
)
from envelope import object_response
from errors import ApiError
from routes._common import filtered, respond_list
from services.allocation import cancel_voucher, run_allocation_round
from validation import Field, pagination_params, validate_body

bp = Blueprint("vouchers", __name__)

FEE_ACTIONS = ("WAIVE", "INVOICE", "RECORD_PAYMENT", "WRITE_OFF")


def _scope_voucher(actor, voucher):
    referral = referral_of_voucher(voucher)
    if referral is not None:
        require_agency_scope(actor, referral["agency_id"])


@bp.route("/vouchers", methods=["POST"])
def issue_voucher():
    actor = authenticate(["CaseManager"])
    payload = validate_body([
        Field("referral_id", "string"),
        Field("lines", "object_array", non_empty_array=True, item_fields=[
            Field("category", "enum", members=CATEGORIES),
            Field("quantity_requested", "integer", minimum=1, maximum=6),
            Field("min_condition", "enum", members=GRADES_ABC),
        ]),
    ])
    referral = resolve("referral", payload["referral_id"])
    require_agency_scope(actor, referral["agency_id"])
    client = db.clients.get(referral["client_id"])

    # (11) state gate
    if referral["status"] != "APPROVED":
        raise ApiError("ERR_REFERRAL_NOT_APPROVED",
                       "A voucher may only be issued against an APPROVED referral.")
    # (13) bed-bug block
    if client["bed_bug_status"] == "CONFIRMED":
        raise ApiError("ERR_CLIENT_BED_BUG_BLOCK",
                       "The household is under a confirmed bed-bug infestation.")
    # (17) referral expiry
    if referral["expires_at"] is not None and clock.now() > referral["expires_at"]:
        raise ApiError("ERR_REFERRAL_EXPIRED", "The referral has expired.")
    # (20) at most one voucher per referral
    if voucher_of_referral(referral["id"]) is not None:
        raise ApiError("ERR_VOUCHER_ALREADY_EXISTS",
                       "This referral already carries a voucher.")

    voucher = new_entity(
        referral_id=referral["id"],
        status="ISSUED",
        fee_status="PENDING",
        gross_fee_cents=0,
        subsidy_cents=0,
        client_due_cents=0,
        fee_basis=None,
        fill_ratio=Decimal("0.000"),
        amount_paid_cents=0,
    )
    db.vouchers[voucher["id"]] = voucher
    for element in payload["lines"]:
        line = new_entity(
            voucher_id=voucher["id"],
            category=element["category"],
            quantity_requested=element["quantity_requested"],
            min_condition=element["min_condition"],
            quantity_allocated=0,
            status="OPEN",
        )
        db.voucher_lines[line["id"]] = line
    return object_response(serialize(voucher), 201)


@bp.route("/vouchers/<voucher_id>", methods=["GET"])
def get_voucher(voucher_id):
    actor = authenticate(["CaseManager", "WarehouseLead", "DispatchPlanner", "PlatformAdmin"])
    voucher = resolve("voucher", voucher_id)
    _scope_voucher(actor, voucher)
    return object_response(serialize(voucher))


@bp.route("/vouchers", methods=["GET"])
def list_vouchers():
    authenticate(["CaseManager", "WarehouseLead", "DispatchPlanner", "PlatformAdmin"])
    limit, offset = pagination_params()
    rows = filtered(list(db.vouchers.values()), {
        "referral_id": "referral_id",
        "status": "status",
        "fee_status": "fee_status",
    })
    return respond_list(rows, limit, offset)


@bp.route("/vouchers/<voucher_id>/lines", methods=["GET"])
def list_voucher_lines(voucher_id):
    authenticate(["CaseManager", "WarehouseLead", "DispatchPlanner", "PlatformAdmin"])
    limit, offset = pagination_params()
    voucher = resolve("voucher", voucher_id)
    rows = filtered(lines_of_voucher(voucher["id"]), {"status": "status"})
    return respond_list(rows, limit, offset)


@bp.route("/vouchers/<voucher_id>/stops", methods=["GET"])
def list_voucher_stops(voucher_id):
    authenticate(["CaseManager", "DispatchPlanner", "PlatformAdmin"])
    limit, offset = pagination_params()
    voucher = resolve("voucher", voucher_id)
    rows = filtered(stops_of_voucher(voucher["id"]), {"status": "status"})
    return respond_list(rows, limit, offset)


@bp.route("/vouchers/<voucher_id>/allocate", methods=["POST"])
def allocate_voucher(voucher_id):
    authenticate(["WarehouseLead"])
    payload = validate_body([Field("expected_voucher_version", "integer")])
    voucher = resolve("voucher", voucher_id)

    # (10) optimistic concurrency on the voucher's version
    if payload["expected_voucher_version"] != voucher["version"]:
        raise ApiError("ERR_STALE_VOUCHER_VERSION",
                       "`expected_voucher_version` does not match the voucher's version.")
    # (11) state gate
    if voucher["status"] not in ("ISSUED", "PARTIALLY_ALLOCATED"):
        raise ApiError("ERR_VOUCHER_INVALID_STATE",
                       "Only an ISSUED or PARTIALLY_ALLOCATED voucher may be allocated.")
    client = client_of_voucher(voucher)
    referral = referral_of_voucher(voucher)
    # (13) bed-bug block
    if client["bed_bug_status"] == "CONFIRMED":
        raise ApiError("ERR_CLIENT_BED_BUG_BLOCK",
                       "The household is under a confirmed bed-bug infestation.")
    # (17) referral expiry
    if referral["expires_at"] is not None and clock.now() > referral["expires_at"]:
        raise ApiError("ERR_REFERRAL_EXPIRED", "The referral has expired.")

    run_allocation_round(voucher)
    return object_response(serialize(voucher))


@bp.route("/vouchers/<voucher_id>/fee-settlement", methods=["POST"])
def fee_settlement(voucher_id):
    authenticate(["PlatformAdmin"])
    payload = validate_body([
        Field("action", "enum", members=FEE_ACTIONS),
        Field("amount_cents", "integer", required=False, default=None),
    ])
    action = payload["action"]
    if action == "RECORD_PAYMENT" and payload["amount_cents"] is None:
        raise ApiError("ERR_VALIDATION",
                       "`amount_cents` is required when recording a payment.")
    voucher = resolve("voucher", voucher_id)

    # (11) state gate on the billing axis
    if action == "WAIVE":
        allowed = voucher["fee_status"] == "PENDING" and voucher["status"] != "CANCELLED"
    elif action == "INVOICE":
        allowed = voucher["fee_status"] == "PENDING" and voucher["status"] == "DELIVERED"
    else:
        allowed = voucher["fee_status"] == "INVOICED"
    if not allowed:
        raise ApiError("ERR_FEE_STATE_INVALID",
                       "That settlement action has no outgoing edge from this fee_status.")

    if action == "RECORD_PAYMENT":
        # (29) the payment must match what the household owes, exactly
        if payload["amount_cents"] != voucher["client_due_cents"]:
            raise ApiError("ERR_FEE_AMOUNT_MISMATCH",
                           "`amount_cents` must equal client_due_cents exactly.")

    if action == "WAIVE":
        voucher["fee_status"] = "WAIVED"
        voucher["subsidy_cents"] = voucher["gross_fee_cents"]
        voucher["client_due_cents"] = 0
    elif action == "INVOICE":
        voucher["fee_status"] = "INVOICED"
    elif action == "RECORD_PAYMENT":
        voucher["fee_status"] = "PAID"
        voucher["amount_paid_cents"] = payload["amount_cents"]
    else:
        voucher["fee_status"] = "WRITTEN_OFF"
        voucher["client_due_cents"] = 0
    touch(voucher)
    return object_response(serialize(voucher))


@bp.route("/vouchers/<voucher_id>/cancel", methods=["POST"])
def cancel_voucher_route(voucher_id):
    actor = authenticate(["CaseManager", "PlatformAdmin"])
    validate_body([Field("reason", "string")])
    voucher = resolve("voucher", voucher_id)
    _scope_voucher(actor, voucher)

    # (11) state gate
    if voucher["status"] not in ("ISSUED", "PARTIALLY_ALLOCATED", "ALLOCATED"):
        raise ApiError("ERR_VOUCHER_INVALID_STATE",
                       "This voucher can no longer be cancelled.")
    cancel_voucher(voucher)
    return object_response(serialize(voucher))
