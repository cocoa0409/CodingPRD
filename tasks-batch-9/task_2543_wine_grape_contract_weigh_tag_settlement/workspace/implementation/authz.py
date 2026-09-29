"""Ranks 1-3: auth headers, role authorisation and Grower row ownership."""
from flask import request

from common import DB, fail

GROWER_RELATIONS_MANAGER = "GrowerRelationsManager"
GROWER = "Grower"
HARVEST_COORDINATOR = "HarvestCoordinator"
SCALE_OPERATOR = "ScaleOperator"
QUALITY_LAB_TECH = "QualityLabTech"
ACCOUNTS_PAYABLE_CLERK = "AccountsPayableClerk"

ALL_ROLES = (
    GROWER_RELATIONS_MANAGER,
    GROWER,
    HARVEST_COORDINATOR,
    SCALE_OPERATOR,
    QUALITY_LAB_TECH,
    ACCOUNTS_PAYABLE_CLERK,
)


def auth(*allowed):
    """Rank 1 then rank 2.  Returns (user_id, role)."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if user_id is None or str(user_id).strip() == "":
        fail("ERR_MISSING_AUTH_HEADER", "Header 'X-User-ID' is required and may not be blank.")
    if role is None or str(role).strip() == "":
        fail("ERR_MISSING_AUTH_HEADER", "Header 'X-User-Role' is required and may not be blank.")
    if role not in ALL_ROLES:
        fail("ERR_UNAUTHORIZED", "Role '%s' is not a recognised role." % role)
    if role not in allowed:
        fail("ERR_UNAUTHORIZED", "Role '%s' is not authorised for this endpoint." % role)
    return user_id, role


def own(user_id, role, grower_id):
    """Rank 3: a Grower acts only on its own rows."""
    if role == GROWER and user_id != grower_id:
        fail("ERR_NOT_CONTRACT_GROWER",
             "This producer may not act on another producer's rows.")


# --------------------------------------------------------------------------
# ownership resolution helpers
# --------------------------------------------------------------------------
def grower_of_contract(contract):
    return contract["grower_id"]


def contract_of_pick_call(pick_call):
    return DB["contracts"].get(pick_call["contract_id"])


def pick_call_of_appointment(appointment):
    return DB["pick_calls"].get(appointment["pick_call_id"])


def contract_of_appointment(appointment):
    call = pick_call_of_appointment(appointment)
    if call is None:
        return None
    return contract_of_pick_call(call)


def contract_of_tag(tag):
    appointment = DB["appointments"].get(tag["appointment_id"])
    if appointment is None:
        return None
    return contract_of_appointment(appointment)


def grower_of_tag(tag):
    contract = contract_of_tag(tag)
    if contract is None:
        return None
    return contract["grower_id"]
