"""Accounts: creation, reads, billing configuration, suspension and statement."""

from flask import Blueprint

import envelope
import ladder
import serializers as ser
import services
from constants import (
    ACCOUNT_TYPES,
    BILLING_MODES,
    DEFAULT_ACCOUNT_CREDIT_LIMIT_CENTS,
    ZONE_CODES,
)
from errors import ApiError
from store import db, stamp_new, touch

bp = Blueprint("accounts", __name__)

ACCOUNT_SPEC = ladder.Spec(
    required=[
        ("name", "string"),
        ("account_type", "string"),
        ("zone_code", "string"),
        ("contact_email", "string"),
    ],
    optional=[
        ("billing_mode", "string"),
        ("tax_exempt", "boolean"),
        ("credit_limit_cents", "integer"),
    ],
    enums={
        "account_type": ACCOUNT_TYPES,
        "zone_code": ZONE_CODES,
        "billing_mode": BILLING_MODES,
    },
    ranges={"credit_limit_cents": (0, None)},
)

ACCOUNT_PATCH_SPEC = ladder.Spec(
    optional=[
        ("billing_mode", "string"),
        ("tax_exempt", "boolean"),
        ("credit_limit_cents", "integer"),
        ("contact_email", "string"),
    ],
    enums={"billing_mode": BILLING_MODES},
    ranges={"credit_limit_cents": (0, None)},
)


@bp.route("/sharpening/accounts", methods=["POST"])
def create_account():
    ctx = ladder.begin("PlatformAdmin")
    ACCOUNT_SPEC.validate(ctx.body)
    row = stamp_new(
        {
            "name": ctx.body["name"],
            "account_type": ctx.body["account_type"],
            "zone_code": ctx.body["zone_code"],
            "billing_mode": ctx.body.get("billing_mode", "PER_VISIT"),
            "tax_exempt": bool(ctx.body.get("tax_exempt", False)),
            "credit_limit_cents": ctx.body.get(
                "credit_limit_cents", DEFAULT_ACCOUNT_CREDIT_LIMIT_CENTS
            ),
            "contact_email": ctx.body["contact_email"],
            "status": "ACTIVE",
        }
    )
    db.accounts[row["id"]] = row
    return envelope.created(ser.account(row))


@bp.route("/sharpening/accounts/<id>", methods=["GET"])
def get_account(id):
    ctx = ladder.begin("PlatformAdmin", "AccountOwner", "BillingClerk", "Dispatcher")
    row = ladder.must_exist(db.accounts, id, "Account")
    services.own_account(ctx, row["id"])
    return envelope.ok(ser.account(row))


@bp.route("/sharpening/accounts/<id>", methods=["PATCH"])
def patch_account(id):
    ctx = ladder.begin("PlatformAdmin")
    row = ladder.must_exist(db.accounts, id, "Account")
    ACCOUNT_PATCH_SPEC.validate(ctx.body)
    # Rung 9 deliberately does not apply here: the billing-configuration update
    # must remain callable on a suspended account.
    for field in ("billing_mode", "tax_exempt", "credit_limit_cents", "contact_email"):
        if field in ctx.body and ctx.body[field] is not None:
            row[field] = ctx.body[field]
    touch(row)
    return envelope.ok(ser.account(row))


@bp.route("/sharpening/accounts/<id>/suspend", methods=["POST"])
def suspend_account(id):
    ladder.begin("PlatformAdmin")
    row = ladder.must_exist(db.accounts, id, "Account")
    if row["status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE", "The account is not ACTIVE.")
    row["status"] = "SUSPENDED"
    touch(row)
    return envelope.ok(ser.account(row))


@bp.route("/sharpening/accounts/<id>/reinstate", methods=["POST"])
def reinstate_account(id):
    ladder.begin("PlatformAdmin")
    row = ladder.must_exist(db.accounts, id, "Account")
    if row["status"] != "SUSPENDED":
        raise ApiError("ERR_INVALID_STATE", "The account is not SUSPENDED.")
    row["status"] = "ACTIVE"
    touch(row)
    return envelope.ok(ser.account(row))


@bp.route("/sharpening/accounts/<id>/statement", methods=["GET"])
def account_statement(id):
    ctx = ladder.begin("PlatformAdmin", "BillingClerk", "AccountOwner")
    row = ladder.must_exist(db.accounts, id, "Account")
    services.own_account(ctx, row["id"])
    draft_count = len(
        [
            i
            for i in db.invoices.values()
            if i["account_id"] == row["id"] and i["status"] == "DRAFT"
        ]
    )
    unbilled_count = len(
        [
            r
            for r in db.service_requests.values()
            if r["account_id"] == row["id"] and r["billing_status"] == "UNBILLED"
        ]
    )
    subscription = services.account_subscription(row["id"])
    return envelope.ok(
        {
            "account_id": row["id"],
            "outstanding_balance_cents": ser.account_outstanding(row["id"]),
            "draft_invoice_count": draft_count,
            "unbilled_request_count": unbilled_count,
            "allowance_remaining": subscription["allowance_remaining"]
            if subscription
            else 0,
        }
    )
