"""Small reusable state / precondition guards (PRD 2.11 priorities 12-13)."""
from core import ApiError, find, offering_of_session

CONTRACT_TERMINAL = ("TERMINATED", "WITHDRAWN")
SESSION_TERMINAL = ("COMPLETED", "CANCELLED_NO_COVER", "CANCELLED_CLIENT", "CANCELLED_FACILITY")
ASSIGNMENT_TERMINAL = ("RELEASED", "COMPLETED")
INCIDENT_TERMINAL = ("CLOSED_NO_CLAIM", "CLAIM_CLOSED")
INVOICE_TERMINAL = ("PAID", "SUPERSEDED")


def terminal(condition):
    if condition:
        raise ApiError("ERR_TERMINAL_STATE", 409)


def invalid_transition():
    raise ApiError("ERR_INVALID_STATE_TRANSITION", 409)


def require_contract_active(contract):
    if contract is None or contract["status"] != "ACTIVE":
        raise ApiError("ERR_CONTRACT_NOT_ACTIVE", 409)


def contract_of_offering(offering):
    return find("contract", offering["contract_id"])


def contract_of_session(session):
    offering = offering_of_session(session)
    if offering is None:
        return None
    return find("contract", offering["contract_id"])


def contract_of_staff(staff):
    return find("contract", staff["contract_id"])
