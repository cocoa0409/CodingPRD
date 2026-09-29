"""Season passes, payment plans, installments, renewals."""

from flask import Blueprint

import serializers
from db import add_months, db, fmt_day, parse_day
from errors import ApiError
from middleware import (ROLE_COMPLIANCE_OFFICER, ROLE_PASS_OFFICE_CLERK, ROLE_PASSHOLDER,
                        ROLE_PROGRAM_ADMIN, require)
from response import created_response, list_response, object_response
from services import calc, domain
from validate import field, pagination, query_enum, query_string, read_body

bp = Blueprint("passes", __name__)

PAYMENT_MODES = ("PAY_IN_FULL", "PAYMENT_PLAN")
PASS_STATUSES = ("PENDING_PROCESSING", "ACTIVE", "SUSPENDED", "REVOKED", "EXPIRED")
BILLING_STATUSES = ("UNBILLED", "PLAN_CURRENT", "DELINQUENT", "DEFAULTED", "PAID_IN_FULL")
PLAN_STATUSES = ("ACTIVE", "SUPERSEDED", "COMPLETED", "TERMINATED_ON_REVOCATION")
INSTALLMENT_STATUSES = ("SCHEDULED", "SETTLED", "MISSED", "WAIVED", "VOIDED")

SELL_PROGRAM_STATUSES = ("SALES_OPEN", "SEASON_ACTIVE", "RENEWAL_OPEN")

READ_MONEY_ROLES = (
    ROLE_PROGRAM_ADMIN,
    ROLE_PASS_OFFICE_CLERK,
    ROLE_COMPLIANCE_OFFICER,
    ROLE_PASSHOLDER,
)


def _mint_pass(program, tier, passholder_id, payment_mode, contract_value_cents,
               renewed_from_pass_id=None):
    paid = contract_value_cents if payment_mode == "PAY_IN_FULL" else 0
    billing_status = "PAID_IN_FULL" if payment_mode == "PAY_IN_FULL" else "UNBILLED"
    return db.insert("season_passes", {
        "program_id": program["id"],
        "tier_id": tier["id"],
        "passholder_id": passholder_id,
        "renewed_from_pass_id": renewed_from_pass_id,
        "media_number": db.next_media_number(),
        "payment_mode": payment_mode,
        "pass_status": "PENDING_PROCESSING",
        "billing_status": billing_status,
        "photo_captured": False,
        "photo_hash": None,
        "identity_bound": False,
        "government_id_last4": None,
        "contract_value_cents": contract_value_cents,
        "billed_total_cents": contract_value_cents,
        "paid_to_date_cents": paid,
        "suspension_count": 0,
    })


# ------------------------------------------------------------- season passes
@bp.post("/season-passes")
def create_pass():
    require(ROLE_PASS_OFFICE_CLERK)
    body = read_body({
        "program_id": field("string", required=True),
        "tier_id": field("string", required=True),
        "passholder_id": field("string", required=True),
        "payment_mode": field("enum", required=True, enum=PAYMENT_MODES),
    })
    program = domain.get_program(body["program_id"])
    tier = domain.get_tier(body["tier_id"])
    holder = domain.get_passholder(body["passholder_id"])
    if program["status"] not in SELL_PROGRAM_STATUSES:
        raise ApiError("ERR_PROGRAM_STATUS_INVALID")
    if tier["status"] != "PUBLISHED":
        raise ApiError("ERR_TIER_NOT_PUBLISHED")
    if tier["program_id"] != program["id"]:
        raise ApiError("ERR_TIER_PROGRAM_MISMATCH")
    for existing in domain.program_passes(program["id"]):
        if (
            existing["passholder_id"] == holder["id"]
            and existing["pass_status"] in domain.LIVE_PASS_STATUSES
        ):
            raise ApiError("ERR_DUPLICATE_ACTIVE_PASS")
    record = _mint_pass(program, tier, holder["id"], body["payment_mode"],
                        tier["base_price_cents"])
    db.commit()
    return created_response(serializers.pass_out(record))


@bp.get("/season-passes")
def list_passes():
    user_id, role = require()
    limit, offset = pagination()
    filters = {
        "program_id": query_string("program_id"),
        "tier_id": query_string("tier_id"),
        "passholder_id": query_string("passholder_id"),
        "renewed_from_pass_id": query_string("renewed_from_pass_id"),
    }
    pass_status = query_enum("pass_status", PASS_STATUSES)
    billing_status = query_enum("billing_status", BILLING_STATUSES)
    rows = db.rows("season_passes")
    for name, value in filters.items():
        if value is not None:
            rows = [r for r in rows if r[name] == value]
    if pass_status is not None:
        rows = [r for r in rows if r["pass_status"] == pass_status]
    if billing_status is not None:
        rows = [r for r in rows if r["billing_status"] == billing_status]
    if role == ROLE_PASSHOLDER:
        rows = [r for r in rows if r["passholder_id"] == user_id]
    rows = sorted(rows, key=lambda r: r["media_number"])
    return list_response([serializers.pass_out(r) for r in rows], limit, offset)


@bp.get("/season-passes/<pass_id>")
def get_pass(pass_id):
    user_id, role = require()
    season_pass = domain.get_pass(pass_id)
    if role == ROLE_PASSHOLDER and season_pass["passholder_id"] != user_id:
        raise ApiError("ERR_NOT_PASS_OWNER")
    return object_response(serializers.pass_out(season_pass))


@bp.post("/season-passes/<pass_id>/process")
def process_pass(pass_id):
    require(ROLE_PASS_OFFICE_CLERK)
    body = read_body({
        "photo_hash": field("string", required=True),
        "government_id_last4": field("string", required=True),
    })
    season_pass = domain.get_pass(pass_id)
    program = domain.get_program(season_pass["program_id"])
    if program["status"] not in SELL_PROGRAM_STATUSES:
        raise ApiError("ERR_PROGRAM_STATUS_INVALID")
    if season_pass["pass_status"] != "PENDING_PROCESSING":
        raise ApiError("ERR_PASS_ALREADY_PROCESSED")
    season_pass["photo_hash"] = body["photo_hash"]
    season_pass["government_id_last4"] = body["government_id_last4"]
    season_pass["photo_captured"] = True
    season_pass["identity_bound"] = True
    season_pass["pass_status"] = "ACTIVE"
    db.commit()
    return object_response(serializers.pass_out(season_pass))


# ------------------------------------------------------------- payment plans
@bp.post("/season-passes/<pass_id>/payment-plans")
def create_plan(pass_id):
    require(ROLE_PASS_OFFICE_CLERK)
    body = read_body({
        "down_payment_cents": field("integer", required=True),
        "installment_count": field("integer", required=True),
        "first_due_date": field("date", required=True),
        "expected_season_pass_version": field("integer", required=True),
    })
    season_pass = domain.get_pass(pass_id)
    if body["expected_season_pass_version"] != season_pass["version"]:
        raise ApiError("ERR_STALE_PASS_VERSION")
    if season_pass["pass_status"] != "ACTIVE":
        raise ApiError("ERR_PASS_NOT_ACTIVE")
    count = body["installment_count"]
    if count < calc.MIN_INSTALLMENT_COUNT or count > calc.MAX_INSTALLMENT_COUNT:
        raise ApiError("ERR_INSTALLMENT_COUNT_OUT_OF_RANGE")
    minimum = calc.min_down_payment_cents(season_pass["contract_value_cents"])
    if body["down_payment_cents"] < minimum:
        raise ApiError("ERR_DOWN_PAYMENT_TOO_LOW")

    outstanding = domain.pass_outstanding_cents(season_pass)
    previous = domain.active_plan(season_pass["id"])
    if previous is not None:
        previous["plan_status"] = "SUPERSEDED"
        for installment in domain.plan_installments(previous["id"]):
            if installment["status"] == "SCHEDULED":
                installment["status"] = "VOIDED"

    financed, monthly, final = calc.amortize(outstanding, body["down_payment_cents"], count)
    plan = db.insert("payment_plans", {
        "season_pass_id": season_pass["id"],
        "plan_status": "ACTIVE",
        "down_payment_cents": body["down_payment_cents"],
        "setup_fee_cents": calc.PLAN_SETUP_FEE_CENTS,
        "financed_amount_cents": financed,
        "installment_count": count,
        "first_due_date": body["first_due_date"],
        "monthly_amount_cents": monthly,
        "final_installment_cents": final,
    })
    first_due = parse_day(body["first_due_date"])
    for sequence in range(1, count + 1):
        amount = monthly if sequence < count else final
        db.insert("installments", {
            "payment_plan_id": plan["id"],
            "sequence_no": sequence,
            "due_date": fmt_day(add_months(first_due, sequence - 1)),
            "amount_cents": amount,
            "status": "SCHEDULED",
            "settled_at": None,
        })
    season_pass["billed_total_cents"] += calc.PLAN_SETUP_FEE_CENTS
    season_pass["paid_to_date_cents"] += body["down_payment_cents"]
    season_pass["billing_status"] = "PLAN_CURRENT"
    db.commit()
    return created_response(serializers.plan_out(plan))


@bp.get("/payment-plans")
def list_plans():
    require(*READ_MONEY_ROLES)
    limit, offset = pagination()
    season_pass_id = query_string("season_pass_id")
    plan_status = query_enum("plan_status", PLAN_STATUSES)
    rows = db.rows("payment_plans")
    if season_pass_id is not None:
        rows = [r for r in rows if r["season_pass_id"] == season_pass_id]
    if plan_status is not None:
        rows = [r for r in rows if r["plan_status"] == plan_status]
    rows = sorted(rows, key=lambda r: r["created_at"])
    return list_response([serializers.plan_out(r) for r in rows], limit, offset)


@bp.get("/payment-plans/<plan_id>")
def get_plan(plan_id):
    require(*READ_MONEY_ROLES)
    return object_response(serializers.plan_out(domain.get_plan(plan_id)))


# --------------------------------------------------------------- reinstate
@bp.post("/season-passes/<pass_id>/reinstate")
def reinstate(pass_id):
    require(ROLE_PASS_OFFICE_CLERK)
    body = read_body({
        "cure_amount_cents": field("integer", required=True),
        "waive_installment_id": field("string"),
    })
    season_pass = domain.get_pass(pass_id)
    plan = domain.active_plan(season_pass["id"])
    waived = None
    if "waive_installment_id" in body:
        waived = domain.get_installment(body["waive_installment_id"])
        if plan is None or waived["payment_plan_id"] != plan["id"]:
            raise ApiError("ERR_INSTALLMENT_NOT_FOUND")
    if season_pass["pass_status"] != "SUSPENDED":
        raise ApiError("ERR_PASS_NOT_SUSPENDED")
    missed = []
    if plan is not None:
        missed = [i for i in domain.plan_installments(plan["id"]) if i["status"] == "MISSED"]
    expected = sum(i["amount_cents"] for i in missed)
    if waived is not None:
        expected -= waived["amount_cents"]
    if body["cure_amount_cents"] != expected:
        raise ApiError("ERR_CURE_AMOUNT_MISMATCH")

    settled_at = db.clock_echo
    for installment in missed:
        if waived is not None and installment["id"] == waived["id"]:
            installment["status"] = "WAIVED"
            season_pass["billed_total_cents"] -= installment["amount_cents"]
        else:
            installment["status"] = "SETTLED"
            installment["settled_at"] = settled_at
    season_pass["paid_to_date_cents"] += body["cure_amount_cents"]
    remaining_scheduled = 0
    if plan is not None:
        remaining_scheduled = sum(
            1 for i in domain.plan_installments(plan["id"]) if i["status"] == "SCHEDULED"
        )
    season_pass["billing_status"] = "PLAN_CURRENT" if remaining_scheduled else "PAID_IN_FULL"
    season_pass["pass_status"] = "ACTIVE"
    db.commit()
    return object_response(serializers.pass_out(season_pass))


# --------------------------------------------------------------- installments
@bp.get("/installments")
def list_installments():
    require(*READ_MONEY_ROLES)
    limit, offset = pagination()
    plan_id = query_string("payment_plan_id")
    status = query_enum("status", INSTALLMENT_STATUSES)
    rows = db.rows("installments")
    if plan_id is not None:
        rows = [r for r in rows if r["payment_plan_id"] == plan_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    rows = domain.sorted_installments(rows)
    return list_response([serializers.installment_out(r) for r in rows], limit, offset)


@bp.get("/installments/<installment_id>")
def get_installment(installment_id):
    require(*READ_MONEY_ROLES)
    return object_response(serializers.installment_out(domain.get_installment(installment_id)))


@bp.post("/installments/<installment_id>/settle")
def settle_installment(installment_id):
    require(ROLE_PASS_OFFICE_CLERK)
    body = read_body({
        "amount_cents": field("integer", required=True),
        "paid_at": field("datetime"),
    })
    installment = domain.get_installment(installment_id)
    plan = domain.get_plan(installment["payment_plan_id"])
    season_pass = domain.get_pass(plan["season_pass_id"])
    if (
        installment["status"] not in ("SCHEDULED", "MISSED")
        or plan["plan_status"] != "ACTIVE"
        or season_pass["pass_status"] == "REVOKED"
    ):
        raise ApiError("ERR_INSTALLMENT_NOT_PAYABLE")
    if body["amount_cents"] != installment["amount_cents"]:
        raise ApiError("ERR_PAYMENT_AMOUNT_MISMATCH")

    installment["status"] = "SETTLED"
    installment["settled_at"] = body.get("paid_at", db.clock_echo)
    season_pass["paid_to_date_cents"] += body["amount_cents"]

    remaining = domain.plan_installments(plan["id"])
    if domain.plan_counts(plan)["missed_count"] == 0 and season_pass["billing_status"] == "DELINQUENT":
        season_pass["billing_status"] = "PLAN_CURRENT"
    open_installments = [i for i in remaining if i["status"] in ("SCHEDULED", "MISSED")]
    if not open_installments:
        plan["plan_status"] = "COMPLETED"
        if season_pass["billing_status"] == "PLAN_CURRENT":
            season_pass["billing_status"] = "PAID_IN_FULL"
    db.commit()
    return object_response(serializers.installment_out(installment))


# ------------------------------------------------------------------ renewals
@bp.get("/season-passes/<pass_id>/renewal-quote")
def get_renewal_quote(pass_id):
    require(ROLE_PROGRAM_ADMIN, ROLE_PASS_OFFICE_CLERK, ROLE_PASSHOLDER)
    target_tier_id = query_string("target_tier_id")
    target_tier = None
    if target_tier_id is not None:
        target_tier = domain.get_tier(target_tier_id)
    season_pass = domain.get_pass(pass_id)
    if target_tier is None:
        target_tier = domain.get_tier(season_pass["tier_id"])
    if not domain.pass_is_renewable(season_pass):
        raise ApiError("ERR_PASS_NOT_RENEWABLE")
    quote = domain.renewal_quote(season_pass, target_tier)
    return object_response({
        "season_pass_id": quote["season_pass_id"],
        "target_tier_id": quote["target_tier_id"],
        "standard_price_cents": quote["standard_price_cents"],
        "early_bird_applied": quote["early_bird_applied"],
        "discounted_price_cents": quote["discounted_price_cents"],
        "retention_credit_cents": quote["retention_credit_cents"],
        "quoted_price_cents": quote["quoted_price_cents"],
    })


@bp.post("/season-passes/<pass_id>/renew")
def renew_pass(pass_id):
    require(ROLE_PASS_OFFICE_CLERK)
    body = read_body({
        "target_program_id": field("string", required=True),
        "target_tier_id": field("string", required=True),
        "payment_mode": field("enum", required=True, enum=PAYMENT_MODES),
    })
    target_program = domain.get_program(body["target_program_id"])
    target_tier = domain.get_tier(body["target_tier_id"])
    season_pass = domain.get_pass(pass_id)
    if target_program["status"] != "RENEWAL_OPEN":
        raise ApiError("ERR_PROGRAM_NOT_IN_RENEWAL")
    if target_tier["status"] != "PUBLISHED":
        raise ApiError("ERR_TIER_NOT_PUBLISHED")
    if not domain.pass_is_renewable(season_pass):
        raise ApiError("ERR_PASS_NOT_RENEWABLE")
    if target_tier["program_id"] != target_program["id"]:
        raise ApiError("ERR_TIER_PROGRAM_MISMATCH")
    quote = domain.renewal_quote(season_pass, target_tier)
    record = _mint_pass(
        target_program,
        target_tier,
        season_pass["passholder_id"],
        body["payment_mode"],
        quote["quoted_price_cents"],
        renewed_from_pass_id=season_pass["id"],
    )
    db.commit()
    return created_response(serializers.pass_out(record))
