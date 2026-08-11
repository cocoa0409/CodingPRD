"""Trade accounts, the deposit ledger view and payments."""

from decimal import Decimal
from flask import Blueprint

from . import constants as C
from . import lookup
from .auth import authorize
from .calc import (
    account_shipments,
    recompute_outstanding_balance,
    recompute_self_dist_ledger,
    recompute_shipment_aging,
)
from .envelope import list_response, object_response
from .errors import ApiError
from .routes_recipes import require_id
from .store import base_record, collection_sorted, db, touch
from .util import dec, round2
from .validate import (
    body_dict,
    field,
    pagination,
    paginate,
    parse_body,
    query_enum,
)

bp = Blueprint("accounts", __name__)

ACCOUNT_ROLES = ("SalesRep", "ComplianceOfficer", "PlatformAdmin")
NOTICE_STATUSES = ("PENDING", "ACKNOWLEDGED", "OVERDUE")


@bp.post("/accounts")
def open_account():
    authorize("SalesRep", "PlatformAdmin")
    payload = body_dict()
    data = parse_body(
        payload,
        [
            field("account_name", "string", required=True),
            field("channel", "enum", required=True, members=C.ACCOUNT_CHANNELS),
            field("credit_limit", "number", required=True, positive=True),
            field(
                "credit_terms_days",
                "integer",
                default=C.WHOLESALE_DEFAULT_TERMS_DAYS,
            ),
            field("alcoholic_license_on_file", "boolean", default=False),
        ],
    )
    record = base_record()
    record.update(
        {
            "account_name": data["account_name"],
            "channel": data["channel"],
            "credit_terms_days": int(data["credit_terms_days"]),
            "credit_limit": round2(data["credit_limit"]),
            "outstanding_balance": Decimal("0.00"),
            "keg_deposit_balance": Decimal("0.00"),
            "deposit_refunded_total": Decimal("0.00"),
            "deposit_forfeited_total": Decimal("0.00"),
            "kegs_charged_lifetime": 0,
            "ytd_self_dist_liters": Decimal("0.00"),
            "alcoholic_license_on_file": bool(data["alcoholic_license_on_file"]),
            "status": "ONBOARDING",
            "open_recall_notice_count": 0,
        }
    )
    db.accounts[record["id"]] = record
    return object_response(record, 201)


@bp.post("/accounts/<id>/activate")
def activate_account(id):
    authorize("SalesRep", "PlatformAdmin")
    account = lookup.account(id)
    body_dict()
    if account["status"] != "ONBOARDING":
        raise ApiError(
            "ERR_INVALID_STATE", "Only an ONBOARDING account may be activated."
        )
    account["status"] = "ACTIVE"
    touch(account)
    return object_response(account)


@bp.post("/accounts/<id>/credit-hold")
def credit_hold_account(id):
    authorize("SalesRep", "PlatformAdmin")
    account = lookup.account(id)
    payload = body_dict()
    parse_body(payload, [field("reason", "string")])
    if account["status"] != "ACTIVE":
        raise ApiError(
            "ERR_INVALID_STATE", "Only an ACTIVE account may be placed on credit hold."
        )
    account["status"] = "CREDIT_HOLD"
    touch(account)
    return object_response(account)


@bp.post("/accounts/<id>/payments")
def apply_payment(id):
    authorize("SalesRep", "PlatformAdmin")
    account = lookup.account(id)
    payload = body_dict()
    shipment = lookup.shipment(require_id(payload, "shipment_id"))
    data = parse_body(
        payload,
        [
            field("shipment_id", "string", required=True),
            field("amount", "number", required=True),
        ],
    )
    if shipment["status"] != "DELIVERED":
        raise ApiError(
            "ERR_INVALID_STATE", "A payment applies to a DELIVERED shipment only."
        )

    recompute_shipment_aging(shipment)
    expected = round2(dec(shipment["subtotal"]) + dec(shipment["late_fee"]))
    if round2(data["amount"]) != expected:
        raise ApiError(
            "ERR_VALIDATION",
            "The payment amount must equal the shipment's subtotal plus late_fee.",
        )

    shipment["paid_at"] = db.clock
    shipment["status"] = "PAID"
    touch(shipment)

    recompute_outstanding_balance(account)
    recompute_self_dist_ledger(account)

    if account["status"] == "CREDIT_HOLD":
        badly_overdue = False
        for other in account_shipments(account["id"]):
            if other["status"] != "DELIVERED":
                continue
            recompute_shipment_aging(other)
            if int(other["days_past_due"]) > C.CREDIT_HOLD_PAST_DUE_DAYS:
                badly_overdue = True
                break
        if not badly_overdue:
            account["status"] = "ACTIVE"
    touch(account)

    return object_response(shipment)


@bp.get("/accounts/<id>")
def read_account(id):
    authorize(*ACCOUNT_ROLES)
    account = lookup.account(id)
    recompute_self_dist_ledger(account)
    recompute_outstanding_balance(account)
    return object_response(account)


@bp.get("/accounts/<id>/recall-notices")
def list_account_recall_notices(id):
    authorize(*ACCOUNT_ROLES)
    account = lookup.account(id)
    status = query_enum("status", NOTICE_STATUSES)
    limit, offset = pagination()
    rows = collection_sorted(
        db.recall_notices,
        lambda n: n["account_id"] == account["id"]
        and (status is None or n["status"] == status),
    )
    page, total = paginate(rows, limit, offset)
    return list_response(page, limit, offset, total)


@bp.post("/recall-notices/<id>/acknowledge")
def acknowledge_notice(id):
    from flask import g

    authorize("SalesRep", "PlatformAdmin")
    notice = lookup.recall_notice(id)
    payload = body_dict()
    parse_body(payload, [field("note", "string")])
    if notice["status"] not in ("PENDING", "OVERDUE"):
        raise ApiError(
            "ERR_INVALID_STATE", "Only a PENDING or OVERDUE notice may be acknowledged."
        )
    notice["status"] = "ACKNOWLEDGED"
    notice["acknowledged_at"] = db.clock
    notice["acknowledged_by_user_id"] = g.user_id
    touch(notice)

    account = db.accounts.get(notice["account_id"])
    if account is not None:
        account["open_recall_notice_count"] = max(
            0, int(account["open_recall_notice_count"]) - 1
        )
        touch(account)
    return object_response(notice)
