"""Shared route plumbing: existence gates, body FK gates, listing and scoping."""
from flask import request

import response
import validate
from errors import ApiError
from store import db, ordered
from services import volume


def must(collection, key, error_id):
    if not key or not isinstance(key, str):
        raise ApiError(error_id)
    row = collection.get(key)
    if row is None:
        raise ApiError(error_id)
    return row


def winery(key):
    return must(db.wineries, key, "ERR_WINERY_NOT_FOUND")


def state_rule(key):
    return must(db.state_rules, key, "ERR_STATE_RULE_NOT_FOUND")


def state_permit(key):
    return must(db.state_permits, key, "ERR_STATE_PERMIT_NOT_FOUND")


def carrier_program(key):
    return must(db.carrier_programs, key, "ERR_CARRIER_PROGRAM_NOT_FOUND")


def carrier_enrollment(key):
    return must(db.carrier_enrollments, key, "ERR_CARRIER_ENROLLMENT_NOT_FOUND")


def consumer(key):
    return must(db.consumers, key, "ERR_CONSUMER_NOT_FOUND")


def club_subscription(key):
    return must(db.club_subscriptions, key, "ERR_CLUB_SUBSCRIPTION_NOT_FOUND")


def order(key):
    return must(db.orders, key, "ERR_ORDER_NOT_FOUND")


def shipment(key):
    return must(db.shipments, key, "ERR_SHIPMENT_NOT_FOUND")


def compliance_exception(key):
    return must(db.compliance_exceptions, key, "ERR_COMPLIANCE_EXCEPTION_NOT_FOUND")


def remittance(key):
    return must(db.remittances, key, "ERR_REMITTANCE_NOT_FOUND")


def ledger_entry(key):
    return must(db.ledger_entries, key, "ERR_VOLUME_LEDGER_ENTRY_NOT_FOUND")


def rule_for_state(state_code):
    """A supplied state code must have a StateRule governing it (PRD 2.8)."""
    rule = volume.state_rule_for(state_code)
    if rule is None:
        raise ApiError("ERR_STATE_RULE_NOT_FOUND",
                       "No state rule governs '%s'." % state_code)
    return rule


def arg(name):
    value = request.args.get(name)
    if value is None or value == "":
        return None
    return value


def scope_filter(requested, uid, role, role_name, error_message):
    """A Consumer/WineryOperator list is auto-scoped to its own rows; naming
    somebody else's is ERR_FORBIDDEN_RESOURCE_OWNER (PRD 2.1)."""
    if role != role_name:
        return requested
    if requested is not None and requested != uid:
        raise ApiError("ERR_FORBIDDEN_RESOURCE_OWNER", error_message)
    return uid


def scope_consumer(requested, uid, role):
    return scope_filter(requested, uid, role, "Consumer",
                        "This resource belongs to another consumer.")


def scope_winery(requested, uid, role):
    return scope_filter(requested, uid, role, "WineryOperator",
                        "This resource belongs to another winery.")


def listing(rows, serializer):
    limit, offset = validate.pagination()
    rows = ordered(rows)
    total = len(rows)
    window = validate.page(rows, limit, offset)
    return response.arr([serializer(r) for r in window], limit, offset, total)
