"""Test-driving clock endpoints (PRD §2.10).

POST /_clock/set_current_utc sets the server wall clock.
POST /_clock/roll_anniversary rolls a contract to its next anniversary:
high-water mark, free-corridor reset, version bump.
"""

from flask import Blueprint

import errors
import validation as v
from clock import iso8601, parse_iso8601
from db import store
from middleware import authenticate, authorize
from response import object_response
from services import contract as contract_svc
from services import lookups

bp = Blueprint("clock_routes", __name__)


@bp.post("/_clock/set_current_utc")
def set_current_utc():
    _, role = authenticate()
    authorize(role, {"ContractAdmin"})
    body = v.get_json_body()
    raw = v.require_string(body, "to_iso8601")
    dt = parse_iso8601(raw)
    if dt is None:
        raise errors.invalid_request("to_iso8601 must be an ISO 8601 timestamp.")
    store.clock.set_now(dt)
    return object_response({"current_utc": store.clock.iso_now()}, 200, store.clock.now())


@bp.post("/_clock/roll_anniversary")
def roll_anniversary():
    _, role = authenticate()
    authorize(role, {"ContractAdmin"})
    body = v.get_json_body()
    contract_id = v.require_string(body, "contract_id")
    contract = lookups.ref_contract(contract_id)

    # Roll defined only for an ACTIVE contract.
    if contract["status"] != "ACTIVE":
        raise errors.invalid_state("Contract is not ACTIVE.")

    acc = contract_svc.accumulation_value_cents(contract)
    contract["highest_anniversary_value_cents"] = max(
        contract["highest_anniversary_value_cents"], acc
    )
    contract["free_withdrawal_used_cents"] = 0
    contract_svc.bump(contract)

    return object_response(contract_svc.serialize(contract), 200, store.clock.now())
