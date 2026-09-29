"""Distribution declaration, record date, payment and reversal (PRD 3.7)."""
from decimal import Decimal

from flask import Blueprint, request

import clock
import dates
import db
import response
import serializers
import validation
from constants import (ACCOUNT_PARTICIPATING, BACKUP_WITHHOLDING_RATE, DISTRIBUTION_OPEN,
                       DISTRIBUTION_TYPES, NAV_PRICED, PAYMENT_STATUSES,
                       TAX_ADVANTAGED_REGISTRATIONS)
from errors import ApiError, invalid
from middleware import ALL_ROLES, ROLE_CO, ROLE_FA, authenticate
from money import ZERO, q2, q3
from routes import helpers
from services import household, navs as nav_service, positions as positions_service

bp = Blueprint("distributions", __name__)


@bp.route("/distributions", methods=["POST"])
def declare_distribution():
    authenticate((ROLE_FA,))
    body = validation.body()
    share_class_id = validation.get_id(body, "share_class_id", required=True)
    distribution_type = validation.get_enum(body, "distribution_type", DISTRIBUTION_TYPES,
                                            required=True)
    rate_per_share = validation.get_decimal(body, "rate_per_share", 4, required=True, positive=True)
    record_date = validation.get_date(body, "record_date", required=True)
    ex_date = validation.get_date(body, "ex_date", required=True)
    pay_date = validation.get_date(body, "pay_date", required=True)
    if ex_date < record_date:
        raise invalid("ex_date must be on or after record_date.")
    if pay_date < ex_date:
        raise invalid("pay_date must be on or after ex_date.")

    share_class = helpers.get_share_class(share_class_id)

    new_from = dates.fmt_date(record_date)
    new_to = dates.fmt_date(pay_date)
    for existing in db.store.distributions.values():
        if existing["share_class_id"] != share_class["id"]:
            continue
        if existing["distribution_type"] != distribution_type:
            continue
        if existing["status"] not in DISTRIBUTION_OPEN:
            continue
        if new_from <= existing["pay_date"] and existing["record_date"] <= new_to:
            raise ApiError("ERR_DISTRIBUTION_PERIOD_OVERLAP",
                           "The declaration period overlaps an existing declaration.")

    distribution = db.create(db.store.distributions, {
        "share_class_id": share_class["id"],
        "distribution_type": distribution_type,
        "rate_per_share": rate_per_share,
        "record_date": new_from,
        "ex_date": dates.fmt_date(ex_date),
        "pay_date": new_to,
        "status": "DECLARED",
        "payment_count": 0,
        "total_gross_amount": q2(ZERO),
        "total_withholding_amount": q2(ZERO),
        "total_cash_amount": q2(ZERO),
        "total_reinvested_amount": q2(ZERO),
        "reinvest_nav_per_share": None,
    })
    return response.created(serializers.distribution(distribution))


@bp.route("/distributions/<distribution_id>", methods=["GET"])
def read_distribution(distribution_id):
    authenticate(ALL_ROLES)
    distribution = helpers.get_distribution(distribution_id)
    return response.ok(serializers.distribution(distribution))


@bp.route("/distributions/<distribution_id>/record", methods=["POST"])
def record_distribution(distribution_id):
    authenticate((ROLE_FA,))
    distribution = helpers.get_distribution(distribution_id)
    if distribution["status"] != "DECLARED":
        raise ApiError("ERR_INVALID_DISTRIBUTION_STATE",
                       "Only a DECLARED distribution may be recorded.")
    if dates.fmt_date(clock.today()) < distribution["record_date"]:
        raise ApiError("ERR_INVALID_DISTRIBUTION_STATE",
                       "The record date has not been reached on the logical clock.")

    eligible = [p for p in positions_service.for_class(distribution["share_class_id"])
                if p["shares"] > 0]
    eligible = helpers.sorted_records(eligible)

    total_gross = ZERO
    total_withholding = ZERO
    count = 0
    for position in eligible:
        account = db.store.accounts.get(position["account_id"])
        if account is None or account["status"] not in ACCOUNT_PARTICIPATING:
            continue
        shares_of_record = q3(position["shares"])
        gross = q2(shares_of_record * distribution["rate_per_share"])
        if (not account["tin_certified"]
                and account["registration_type"] not in TAX_ADVANTAGED_REGISTRATIONS):
            withholding = q2(gross * BACKUP_WITHHOLDING_RATE)
        else:
            withholding = q2(ZERO)
        net = q2(gross - withholding)
        db.create(db.store.payments, {
            "distribution_id": distribution["id"],
            "account_id": account["id"],
            "position_id": position["id"],
            "reinvestment_trade_id": None,
            "shares_of_record": shares_of_record,
            "gross_amount": gross,
            "withholding_amount": withholding,
            "net_amount": net,
            "cash_amount": q2(ZERO),
            "reinvested_shares": q3(ZERO),
            "payout_option": account["dividend_option"],
            "status": "PENDING",
        })
        total_gross += gross
        total_withholding += withholding
        count += 1

    distribution["status"] = "RECORDED"
    distribution["payment_count"] = count
    distribution["total_gross_amount"] = q2(total_gross)
    distribution["total_withholding_amount"] = q2(total_withholding)
    db.touch(distribution)
    return response.ok(serializers.distribution(distribution))


def _payments_of(distribution_id):
    return helpers.sorted_records(
        [p for p in db.store.payments.values() if p["distribution_id"] == distribution_id])


@bp.route("/distributions/<distribution_id>/pay", methods=["POST"])
def pay_distribution(distribution_id):
    caller = authenticate((ROLE_FA,))
    distribution = helpers.get_distribution(distribution_id)
    if distribution["status"] != "RECORDED":
        raise ApiError("ERR_INVALID_DISTRIBUTION_STATE",
                       "Only a RECORDED distribution may be paid.")
    if dates.fmt_date(clock.today()) < distribution["pay_date"]:
        raise ApiError("ERR_INVALID_DISTRIBUTION_STATE",
                       "The pay date has not been reached on the logical clock.")

    nav_record = nav_service.find_for(distribution["share_class_id"], distribution["ex_date"])
    if nav_record is None:
        raise ApiError("ERR_NAV_NOT_AVAILABLE",
                       "No NAV record exists for the class on the ex date.")
    if nav_record["status"] not in NAV_PRICED:
        raise ApiError("ERR_NAV_NOT_FINAL",
                       "The ex-date NAV record must be FINAL or CORRECTED.")

    reinvest_nav = nav_record["nav_per_share"]
    total_cash = ZERO
    total_reinvested = ZERO
    touched_accounts = []
    touched_classes = set()

    for payment in _payments_of(distribution["id"]):
        account = db.store.accounts.get(payment["account_id"])
        if payment["payout_option"] == "REINVEST":
            shares = q3(payment["net_amount"] / reinvest_nav)
            payment["reinvested_shares"] = shares
            payment["cash_amount"] = q2(ZERO)
            trade = db.create(db.store.trades, {
                "account_id": payment["account_id"],
                "share_class_id": distribution["share_class_id"],
                "exchange_target_share_class_id": None,
                "parent_distribution_id": distribution["id"],
                "originating_plan_id": None,
                "blue_sky_registration_id": None,
                "trade_type": "REINVESTMENT",
                "gross_amount": None,
                "shares_requested": None,
                "as_of_date": None,
                "dealer_reference": None,
                "received_at": clock.now_iso(),
                "trade_date": distribution["ex_date"],
                "execution_status": "PRICED_FINAL",
                "settlement_status": "SETTLED",
                "pricing_variant": "FINAL_NAV",
                "nav_per_share_applied": reinvest_nav,
                "roa_qualifying_amount": None,
                "roa_basis_variant": None,
                "sales_load_pct": Decimal("0.0000"),
                "sales_load_amount": q2(ZERO),
                "net_invested_amount": payment["net_amount"],
                "shares_transacted": shares,
                "gross_proceeds_amount": None,
                "cdsc_amount": None,
                "net_proceeds_amount": None,
                "exchange_target_shares": None,
                "restated_share_delta": None,
                "captured_by_user_id": caller.user_id,
                "approved_by_user_id": None,
                "cancel_reason": None,
                "reversal_reason": None,
            })
            payment["reinvestment_trade_id"] = trade["id"]

            position = db.store.positions.get(payment["position_id"])
            if position is not None:
                positions_service.move_shares(position, shares)
                db.set_field(position, "reinvested_shares",
                             q3(position["reinvested_shares"] + shares))
                db.set_field(position, "cost_basis_amount",
                             q2(position["cost_basis_amount"] + payment["net_amount"]))
                positions_service.append_ledger_entry(
                    position, trade["id"], shares, "DIVIDEND_REINVESTMENT",
                    distribution["ex_date"])
                touched_classes.add(position["share_class_id"])
            total_reinvested += payment["net_amount"]
        else:
            payment["cash_amount"] = payment["net_amount"]
            payment["reinvested_shares"] = q3(ZERO)
            total_cash += payment["cash_amount"]
        payment["status"] = "PAID"
        db.touch(payment)
        if account is not None:
            touched_accounts.append(account)

    for share_class_id in touched_classes:
        positions_service.recompute_class_shares(share_class_id)

    distribution["status"] = "PAID"
    distribution["reinvest_nav_per_share"] = reinvest_nav
    distribution["total_cash_amount"] = q2(total_cash)
    distribution["total_reinvested_amount"] = q2(total_reinvested)
    db.touch(distribution)

    household.recompute_many(touched_accounts)
    return response.ok(serializers.distribution(distribution))


@bp.route("/distributions/<distribution_id>/reverse", methods=["POST"])
def reverse_distribution(distribution_id):
    authenticate((ROLE_CO,))
    body = validation.body()
    reason = validation.get_string(body, "reversal_reason")

    distribution = helpers.get_distribution(distribution_id)
    if distribution["status"] != "PAID":
        raise ApiError("ERR_INVALID_DISTRIBUTION_STATE",
                       "Only a PAID distribution may be reversed.")

    payments = _payments_of(distribution["id"])
    for payment in payments:
        trade_id = payment["reinvestment_trade_id"]
        if not trade_id:
            continue
        trade = db.store.trades.get(trade_id)
        if trade is None or trade["settlement_status"] != "SETTLED":
            raise ApiError("ERR_INVALID_DISTRIBUTION_STATE",
                           "A reinvestment order has already been unwound.")

    touched_accounts = []
    touched_classes = set()
    for payment in payments:
        trade_id = payment["reinvestment_trade_id"]
        if trade_id:
            trade = db.store.trades[trade_id]
            position = db.store.positions.get(payment["position_id"])
            if position is not None:
                positions_service.move_shares(position, -1 * payment["reinvested_shares"])
                db.set_field(position, "reinvested_shares",
                             q3(position["reinvested_shares"] - payment["reinvested_shares"]))
                db.set_field(position, "cost_basis_amount",
                             q2(position["cost_basis_amount"] - payment["net_amount"]))
                positions_service.append_ledger_entry(
                    position, trade["id"], -1 * payment["reinvested_shares"],
                    "DISTRIBUTION_REVERSAL", trade["trade_date"])
                touched_classes.add(position["share_class_id"])
            trade["settlement_status"] = "REVERSED"
            if reason:
                trade["reversal_reason"] = reason
            db.touch(trade)
        payment["status"] = "REVERSED"
        db.touch(payment)
        account = db.store.accounts.get(payment["account_id"])
        if account is not None:
            touched_accounts.append(account)

    for share_class_id in touched_classes:
        positions_service.recompute_class_shares(share_class_id)

    distribution["status"] = "REVERSED"
    distribution["total_cash_amount"] = q2(ZERO)
    distribution["total_reinvested_amount"] = q2(ZERO)
    distribution["total_withholding_amount"] = q2(ZERO)
    distribution["total_gross_amount"] = q2(ZERO)
    db.touch(distribution)

    household.recompute_many(touched_accounts)
    return response.ok(serializers.distribution(distribution))


@bp.route("/distribution-payments/<payment_id>", methods=["GET"])
def read_payment(payment_id):
    authenticate(ALL_ROLES)
    payment = helpers.get_payment(payment_id)
    return response.ok(serializers.payment(payment))


@bp.route("/distribution-payments", methods=["GET"])
def list_payments():
    authenticate(ALL_ROLES)
    limit, offset = validation.pagination()
    records = db.values(db.store.payments)
    records = helpers.filter_equals(records, "distribution_id",
                                    request.args.get("distribution_id"))
    records = helpers.filter_equals(records, "account_id", request.args.get("account_id"))
    records = helpers.filter_equals(records, "position_id", request.args.get("position_id"))
    records = helpers.filter_equals(records, "reinvestment_trade_id",
                                    request.args.get("reinvestment_trade_id"))
    records = helpers.filter_equals(records, "status",
                                    validation.query_enum("status", PAYMENT_STATUSES))
    items, total = helpers.page(records, limit, offset)
    return response.listing([serializers.payment(r) for r in items], total, limit, offset)
