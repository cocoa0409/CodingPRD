"""Existence resolution (ladder rungs 6 and 7) and list filtering (PRD §2.3)."""
from flask import request

import db
from errors import ApiError


def _find(table, resource_id, error_id):
    if not isinstance(resource_id, str):
        raise ApiError(error_id, 404)
    rec = table.get(resource_id)
    if rec is None:
        raise ApiError(error_id, 404)
    return rec


def program(resource_id):
    return _find(db.store.programs, resource_id, "ERR_PROGRAM_NOT_FOUND")


def state_expiry_rule(resource_id):
    return _find(db.store.state_expiry_rules, resource_id, "ERR_STATE_EXPIRY_RULE_NOT_FOUND")


def cohort(resource_id):
    return _find(db.store.cohorts, resource_id, "ERR_COHORT_NOT_FOUND")


def member(resource_id):
    return _find(db.store.members, resource_id, "ERR_MEMBER_NOT_FOUND")


def period(resource_id):
    return _find(db.store.periods, resource_id, "ERR_PERIOD_NOT_FOUND")


def partner_agreement(resource_id):
    return _find(db.store.partner_agreements, resource_id, "ERR_PARTNER_AGREEMENT_NOT_FOUND")


def point_lot(resource_id):
    return _find(db.store.point_lots, resource_id, "ERR_POINT_LOT_NOT_FOUND")


def redemption_event(resource_id):
    return _find(db.store.redemption_events, resource_id, "ERR_REDEMPTION_EVENT_NOT_FOUND")


def breakage_estimate(resource_id):
    return _find(db.store.breakage_estimates, resource_id, "ERR_BREAKAGE_ESTIMATE_NOT_FOUND")


def settlement_statement(resource_id):
    return _find(db.store.settlement_statements, resource_id, "ERR_SETTLEMENT_STATEMENT_NOT_FOUND")


def change_order(resource_id):
    return _find(db.store.change_orders, resource_id, "ERR_CHANGE_ORDER_NOT_FOUND")


def _matches_one(value, raw):
    if isinstance(value, bool):
        text = raw.strip().lower()
        if text in ("true", "1"):
            return value is True
        if text in ("false", "0"):
            return value is False
        return False
    if value is None:
        return False
    return str(value) == raw


def filtered(rows, *fields):
    """Apply every supplied optional query-parameter filter to a row list."""
    out = rows
    for field in fields:
        raw = request.args.get(field)
        if raw is None or raw == "":
            continue
        out = [r for r in out if _matches_one(r.get(field), raw)]
    return out
