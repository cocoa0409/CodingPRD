"""Settlement, cancellation and reversal book entries."""
from decimal import Decimal

import db
from money import ZERO, q2, q3
from services import bluesky, household, positions as positions_service

SETTLEMENT_REASON = {
    "PURCHASE": "PURCHASE_SETTLEMENT",
    "REDEMPTION": "REDEMPTION_SETTLEMENT",
    "EXCHANGE": "EXCHANGE_OUT",
    "REINVESTMENT": "DIVIDEND_REINVESTMENT",
}


def settle(trade):
    account = db.store.accounts[trade["account_id"]]
    position = positions_service.ensure(trade["account_id"], trade["share_class_id"])
    shares_before = position["shares"]
    cost_before = position["cost_basis_amount"]

    positions_service.move_shares(position, trade["shares_transacted"])
    positions_service.append_ledger_entry(
        position, trade["id"], trade["shares_transacted"],
        SETTLEMENT_REASON[trade["trade_type"]], trade["trade_date"])
    positions_service.recompute_class_shares(trade["share_class_id"])

    if trade["trade_type"] == "PURCHASE":
        db.set_field(position, "cost_basis_amount", q2(cost_before + trade["gross_amount"]))
        if not position["first_purchase_date"]:
            db.set_field(position, "first_purchase_date", trade["trade_date"])
        registration = db.store.registrations.get(trade["blue_sky_registration_id"])
        if registration is not None:
            bluesky.consume_reserved(registration, trade["gross_amount"])
    elif trade["trade_type"] == "REDEMPTION":
        if shares_before > 0:
            reduction = q2(cost_before * trade["shares_requested"] / shares_before)
        else:
            reduction = Decimal("0.00")
        db.set_field(position, "cost_basis_amount", q2(cost_before - reduction))
    elif trade["trade_type"] == "EXCHANGE":
        target = positions_service.ensure(
            trade["account_id"], trade["exchange_target_share_class_id"])
        positions_service.move_shares(target, trade["exchange_target_shares"])
        positions_service.append_ledger_entry(
            target, trade["id"], trade["exchange_target_shares"],
            "EXCHANGE_IN", trade["trade_date"])
        positions_service.recompute_class_shares(trade["exchange_target_share_class_id"])
        registration = db.store.registrations.get(trade["blue_sky_registration_id"])
        if registration is not None:
            bluesky.consume(registration, trade["gross_proceeds_amount"])

    db.set_field(trade, "settlement_status", "SETTLED")
    household.recompute(account)


def reverse(trade):
    account = db.store.accounts[trade["account_id"]]
    position = positions_service.find(trade["account_id"], trade["share_class_id"])
    if position is not None:
        positions_service.move_shares(position, -1 * trade["shares_transacted"])
        positions_service.append_ledger_entry(
            position, trade["id"], -1 * trade["shares_transacted"],
            "TRADE_REVERSAL", trade["trade_date"])
        positions_service.recompute_class_shares(trade["share_class_id"])
        if trade["trade_type"] == "PURCHASE":
            db.set_field(position, "cost_basis_amount",
                         q2(position["cost_basis_amount"] - trade["gross_amount"]))

    if trade["trade_type"] == "PURCHASE":
        registration = db.store.registrations.get(trade["blue_sky_registration_id"])
        if registration is not None:
            bluesky.release_consumed(registration, trade["gross_amount"])

    db.set_field(trade, "settlement_status", "REVERSED")
    household.recompute(account)


def resulting_shares_after_reversal(trade):
    position = positions_service.find(trade["account_id"], trade["share_class_id"])
    held = position["shares"] if position is not None else ZERO
    return q3(held - trade["shares_transacted"])
