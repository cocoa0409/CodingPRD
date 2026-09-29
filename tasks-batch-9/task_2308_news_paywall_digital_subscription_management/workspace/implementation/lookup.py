"""Path and body identifier resolution (PRD 2.9: strictly left to right)."""
from db import db
from errors import fail

_NOT_FOUND = {
    "offer_plans": "ERR_OFFER_PLAN_NOT_FOUND",
    "paywall_rules": "ERR_PAYWALL_RULE_NOT_FOUND",
    "articles": "ERR_ARTICLE_NOT_FOUND",
    "readers": "ERR_READER_NOT_FOUND",
    "subscriptions": "ERR_SUBSCRIPTION_NOT_FOUND",
    "invoices": "ERR_INVOICE_NOT_FOUND",
    "cancellation_requests": "ERR_CANCELLATION_REQUEST_NOT_FOUND",
    "save_offers": "ERR_SAVE_OFFER_NOT_FOUND",
    "holds": "ERR_HOLD_NOT_FOUND",
    "group_accounts": "ERR_GROUP_ACCOUNT_NOT_FOUND",
    "seats": "ERR_SEAT_NOT_FOUND",
}


def require(collection, entity_id, error_id=None):
    row = getattr(db, collection).get(entity_id)
    if row is None:
        fail(error_id or _NOT_FOUND[collection])
    return row


def offer_plan(plan_id):
    return require("offer_plans", plan_id)


def paywall_rule(rule_id):
    return require("paywall_rules", rule_id)


def article(article_id):
    return require("articles", article_id)


def reader(reader_id):
    return require("readers", reader_id)


def subscription(subscription_id):
    return require("subscriptions", subscription_id)


def invoice(invoice_id):
    return require("invoices", invoice_id)


def cancellation_request(request_id):
    return require("cancellation_requests", request_id)


def save_offer(offer_id):
    return require("save_offers", offer_id)


def hold(hold_id):
    return require("holds", hold_id)


def group_account(group_id):
    return require("group_accounts", group_id)


def seat(seat_id):
    return require("seats", seat_id)


def group_account_body(group_id):
    """PRD 2.8 step 6: a supplied body group_account_id answers ERR_ARTICLE_NOT_FOUND."""
    return require("group_accounts", group_id, "ERR_ARTICLE_NOT_FOUND")
