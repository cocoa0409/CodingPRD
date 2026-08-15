"""ExistingContract endpoints."""
from flask import Blueprint

import db
from errors import ApiError, ERR_INVALID_REQUEST, ERR_DUPLICATE_CONTRACT_NUMBER, ERR_NOT_FOUND
from middleware import require_roles
from response import success_object
from routes.common import (
    get_json_body,
    optional_bool,
    optional_int,
    require_bool,
    require_date,
    require_int,
    require_str,
)
from services.serializers import contract_view

bp = Blueprint("contracts", __name__)


def _validate_surrender_schedule(sched):
    if not isinstance(sched, list) or len(sched) == 0:
        raise ApiError(
            ERR_INVALID_REQUEST,
            "surrender_schedule must be a non-empty list",
            400,
        )
    expected_year = 1
    for entry in sched:
        if not isinstance(entry, dict):
            raise ApiError(ERR_INVALID_REQUEST, "surrender_schedule entries must be objects", 400)
        cy = entry.get("contract_year")
        pct = entry.get("pct_bps")
        if not isinstance(cy, int) or isinstance(cy, bool):
            raise ApiError(ERR_INVALID_REQUEST, "contract_year must be an integer", 400)
        if not isinstance(pct, int) or isinstance(pct, bool):
            raise ApiError(ERR_INVALID_REQUEST, "pct_bps must be an integer", 400)
        if cy != expected_year:
            raise ApiError(
                ERR_INVALID_REQUEST,
                "surrender_schedule years must be strictly ascending from 1",
                400,
            )
        if pct < 0 or pct > 10000:
            raise ApiError(
                ERR_INVALID_REQUEST,
                "pct_bps must be between 0 and 10000",
                400,
            )
        expected_year += 1


@bp.route("/contracts", methods=["POST"])
def create_contract():
    require_roles("Producer", "CarrierAdmin")
    body = get_json_body()
    client_id = require_str(body, "client_id")
    carrier_name = require_str(body, "carrier_name")
    contract_number = require_str(body, "contract_number")
    issue_date = require_date(body, "issue_date")
    account_value_cents = require_int(body, "account_value_cents", positive=True)
    tax_basis_cents = require_int(body, "tax_basis_cents", min_value=0)

    if "surrender_schedule" not in body:
        raise ApiError(ERR_INVALID_REQUEST, "Field 'surrender_schedule' is required", 400)
    sched = body["surrender_schedule"]
    _validate_surrender_schedule(sched)
    surrender_schedule = [
        {"contract_year": int(e["contract_year"]), "pct_bps": int(e["pct_bps"])}
        for e in sched
    ]

    living_benefit_rider = require_bool(body, "living_benefit_rider")
    rider_benefit_base_cents = optional_int(body, "rider_benefit_base_cents", 0, min_value=0)
    rider_annual_fee_bps = optional_int(body, "rider_annual_fee_bps", 0, min_value=0, max_value=10000)

    last_exchange_completed_at = body.get("last_exchange_completed_at")
    if last_exchange_completed_at is not None:
        if not isinstance(last_exchange_completed_at, str) or last_exchange_completed_at == "":
            raise ApiError(
                ERR_INVALID_REQUEST,
                "last_exchange_completed_at must be an ISO-8601 timestamp or null",
                400,
            )

    # FK resolution: client must exist (body FKs resolved left-to-right)
    if client_id not in db.clients:
        raise ApiError(ERR_NOT_FOUND, "client_id does not resolve to an existing client", 404)

    # (carrier_name, contract_number) case-insensitive uniqueness
    pair = (carrier_name.lower(), contract_number.lower())
    for ct in db.contracts.values():
        if (ct["carrier_name"].lower(), ct["contract_number"].lower()) == pair:
            raise ApiError(
                ERR_DUPLICATE_CONTRACT_NUMBER,
                "(carrier_name, contract_number) pair already registered",
                409,
            )

    now = db.now_formatted()
    contract = {
        "id": db.new_id(),
        "client_id": client_id,
        "carrier_name": carrier_name,
        "contract_number": contract_number,
        "issue_date": issue_date,
        "account_value_cents": account_value_cents,
        "tax_basis_cents": tax_basis_cents,
        "surrender_schedule": surrender_schedule,
        "living_benefit_rider": living_benefit_rider,
        "rider_benefit_base_cents": rider_benefit_base_cents,
        "rider_annual_fee_bps": rider_annual_fee_bps,
        "last_exchange_completed_at": last_exchange_completed_at,
        "status": "IN_FORCE",
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    db.contracts[contract["id"]] = contract
    return success_object(contract_view(contract), 201)
