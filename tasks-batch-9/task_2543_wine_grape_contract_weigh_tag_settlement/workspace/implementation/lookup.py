"""Rank-5 / rank-6 existence resolution with the family-specific 404 ids."""
from common import DB, fail

NOT_FOUND = {
    "growers": "ERR_GROWER_NOT_FOUND",
    "blocks": "ERR_BLOCK_NOT_FOUND",
    "specs": "ERR_QUALITY_SPEC_NOT_FOUND",
    "contracts": "ERR_CONTRACT_NOT_FOUND",
    "allocations": "ERR_ALLOCATION_NOT_FOUND",
    "lanes": "ERR_LANE_NOT_FOUND",
    "crews": "ERR_CREW_NOT_FOUND",
    "visits": "ERR_SAMPLING_VISIT_NOT_FOUND",
    "pick_calls": "ERR_PICK_CALL_NOT_FOUND",
    "appointments": "ERR_APPOINTMENT_NOT_FOUND",
    "weigh_tags": "ERR_WEIGH_TAG_NOT_FOUND",
    "grades": "ERR_GRADE_NOT_FOUND",
    "lines": "ERR_SETTLEMENT_LINE_NOT_FOUND",
    "installments": "ERR_INSTALLMENT_NOT_FOUND",
}

LABEL = {
    "growers": "Producer",
    "blocks": "Vineyard block",
    "specs": "Quality specification",
    "contracts": "Grape contract",
    "allocations": "Contract block allocation",
    "lanes": "Crush-pad lane",
    "crews": "Sampling crew",
    "visits": "Sampling visit",
    "pick_calls": "Pick call",
    "appointments": "Delivery appointment",
    "weigh_tags": "Weigh tag",
    "grades": "Quality grade",
    "lines": "Settlement line",
    "installments": "Payment installment",
}


def find(table, ident):
    row = DB[table].get(ident) if isinstance(ident, str) else None
    if row is None:
        fail(NOT_FOUND[table], "%s '%s' was not found." % (LABEL[table], ident))
    return row


TERMINAL_LIFECYCLE = ("CLOSED", "TERMINATED", "WITHDRAWN")


def contract_writable(contract):
    """No write of any kind is accepted once the lifecycle is terminal."""
    if contract["lifecycle_status"] in TERMINAL_LIFECYCLE:
        fail("ERR_CONTRACT_STATE_INVALID",
             "Contract lifecycle '%s' is terminal and accepts no writes."
             % contract["lifecycle_status"])
    return contract


def contract_in(contract, states):
    if contract["lifecycle_status"] not in states:
        fail("ERR_CONTRACT_STATE_INVALID",
             "Contract lifecycle '%s' does not permit this action."
             % contract["lifecycle_status"])
    return contract


def not_suspended(grower):
    if grower["status"] == "SUSPENDED":
        fail("ERR_GROWER_SUSPENDED", "This producer is suspended.")
    return grower
