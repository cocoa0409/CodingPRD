"""Payer contract routes."""

from flask import Blueprint

import constants as C
from db import base_row, db
from domain import (
    contract_status,
    contract_view,
    get_contract,
    get_facility,
    rows_of,
)
from errors import ApiError
from response import created, ok, ok_list, paginate
from validate import (
    auth,
    body,
    pagination,
    query_enum,
    req_date,
    req_enum,
    req_int,
    req_rate,
    req_str,
)

bp = Blueprint("contracts", __name__)


@bp.post("/facilities/<fid>/payer-contracts")
def create_contract(fid):
    auth("FacilityAdministrator", "ComplianceOfficer")
    data = body()
    payer_name = req_str(data, "payer_name", 1, 120)
    network_status = req_enum(data, "network_status", C.NETWORK_STATUSES)
    qpa = req_int(data, "qualifying_payment_amount_cents", minimum=0)
    rate = req_rate(data, "in_network_coinsurance_rate")
    deductible = req_int(data, "in_network_deductible_remaining_cents", minimum=0)
    regime = req_enum(data, "state_protection_regime", C.STATE_PROTECTION_REGIMES)
    start_date = req_date(data, "effective_start_date")
    end_date = req_date(data, "effective_end_date")
    if end_date < start_date:
        raise ApiError(
            "ERR_INVALID_REQUEST",
            "effective_end_date must not be earlier than effective_start_date",
        )

    facility = get_facility(fid)

    contract = base_row()
    contract.update(
        {
            "facility_id": facility["id"],
            "payer_name": payer_name,
            "network_status": network_status,
            "qualifying_payment_amount_cents": qpa,
            "in_network_coinsurance_rate": rate,
            "in_network_deductible_remaining_cents": deductible,
            "state_protection_regime": regime,
            "effective_start_date": start_date,
            "effective_end_date": end_date,
        }
    )
    db.contracts[contract["id"]] = contract
    return created(contract_view(contract))


@bp.get("/facilities/<fid>/payer-contracts")
def list_contracts(fid):
    auth("FacilityAdministrator", "ComplianceOfficer", "PayerRepresentative")
    status = query_enum("status", C.CONTRACT_STATUSES)
    network_status = query_enum("network_status", C.NETWORK_STATUSES)
    limit, offset = pagination()
    facility = get_facility(fid)
    rows = rows_of(db.contracts, facility_id=facility["id"])
    if status is not None:
        rows = [r for r in rows if contract_status(r) == status]
    if network_status is not None:
        rows = [r for r in rows if r["network_status"] == network_status]
    page = paginate(rows, limit, offset)
    return ok_list([contract_view(r) for r in page], limit, offset, len(rows))


@bp.get("/payer-contracts/<cid>")
def read_contract(cid):
    auth("FacilityAdministrator", "ComplianceOfficer", "PayerRepresentative")
    return ok(contract_view(get_contract(cid)))
