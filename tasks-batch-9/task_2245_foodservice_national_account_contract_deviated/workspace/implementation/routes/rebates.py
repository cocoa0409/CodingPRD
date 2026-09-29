"""Rebate measurement periods: opening, closing, settlement and its reversal."""

from flask import Blueprint

import errors
import middleware
import response
import validation
from db import db, clock, insert, touch, values
from errors import fail
from routes.common import PREFIX, listing, require_contract_active, require_state
from services.compliance import accrue, measure, rate_for, recompute_posture
from util import half_open_overlap

bp = Blueprint("rebates", __name__)


@bp.post(PREFIX + "/rebate-periods")
def create_period():
    middleware.authenticate(["RebateAccountant"])
    data = validation.body(("contract_id", "period_start", "period_end"))
    contract = middleware.get_contract(db, validation.raw_fk(data, "contract_id"))
    period_start = validation.get_dt(data, "period_start")
    period_end = validation.get_dt(data, "period_end")
    if period_end <= period_start:
        fail(errors.ERR_INVALID_REQUEST, "period_end must be strictly after period_start.")

    require_contract_active(contract)

    for other in values(db.rebate_periods):
        if other["contract_id"] != contract["id"]:
            continue
        if half_open_overlap(period_start, period_end,
                             other["period_start"], other["period_end"]):
            fail(errors.ERR_PERIOD_OVERLAP)

    record = insert(db.rebate_periods, {
        "contract_id": contract["id"],
        "period_start": period_start,
        "period_end": period_end,
        "status": "OPEN",
        "gross_purchases_cents": None,
        "contracted_purchases_cents": None,
        "qualifying_cases": None,
        "contracted_cases": None,
        "compliance_pct": None,
        "rebate_rate_pct": None,
        "operator_rebate_cents": None,
        "manufacturer_funded_cents": None,
        "distributor_funded_cents": None,
        "settled_amount_cents": 0,
        "reopen_count": 0,
        "closed_at": None,
        "settled_at": None,
        "settled_by_user_id": None,
    })
    return response.created(response.serialize(record))


@bp.get(PREFIX + "/rebate-periods/<rebate_period_id>")
def read_period(rebate_period_id):
    middleware.authenticate(["RebateAccountant", "NationalAccountManager", "OperatorBuyer",
                             "ContractAuditor", "ManufacturerRep"])
    record = middleware.get_period(db, rebate_period_id)
    return response.ok(response.serialize(record))


@bp.get(PREFIX + "/rebate-periods")
def list_periods():
    middleware.authenticate(["RebateAccountant", "NationalAccountManager", "OperatorBuyer",
                             "ContractAuditor", "ManufacturerRep"])
    return listing(db.rebate_periods, (
        ("contract_id", "contract_id", None),
        ("status", "status", validation.PERIOD_STATUSES),
    ))


@bp.post(PREFIX + "/rebate-periods/<rebate_period_id>/close")
def close_period(rebate_period_id):
    middleware.authenticate(["RebateAccountant"])
    period = middleware.get_period(db, rebate_period_id)
    validation.body(())
    require_state(period, ("OPEN",), errors.ERR_REBATE_PERIOD_INVALID_STATE)
    contract = db.contracts[period["contract_id"]]
    if contract["status"] not in ("ACTIVE", "SUSPENDED", "EXPIRED"):
        fail(errors.ERR_CONTRACT_INVALID_STATE,
             "A rebate period may only be closed on an ACTIVE, SUSPENDED or EXPIRED contract.")
    if clock() < period["period_end"]:
        fail(errors.ERR_PERIOD_NOT_ENDED)

    measured = measure(contract, period)
    contracted_lines = measured.pop("_contracted_lines")
    rebate_rate_pct = rate_for(measured["compliance_pct"])
    operator_rebate, manufacturer_funded, distributor_funded = accrue(
        contracted_lines, rebate_rate_pct)

    period.update(measured)
    period["rebate_rate_pct"] = rebate_rate_pct
    period["operator_rebate_cents"] = operator_rebate
    period["manufacturer_funded_cents"] = manufacturer_funded
    period["distributor_funded_cents"] = distributor_funded
    period["status"] = "CLOSED"
    period["closed_at"] = clock()
    touch(period)

    contract["rebate_payable_cents"] += operator_rebate
    recompute_posture(contract)
    touch(contract)

    manufacturer = db.manufacturers.get(contract["rebate_funding_manufacturer_id"])
    if manufacturer is not None:
        manufacturer["rebate_funding_payable_cents"] += manufacturer_funded
        touch(manufacturer)

    return response.ok(response.serialize(period))


@bp.post(PREFIX + "/rebate-periods/<rebate_period_id>/settle")
def settle_period(rebate_period_id):
    caller = middleware.authenticate(["RebateAccountant"])
    period = middleware.get_period(db, rebate_period_id)
    data = validation.body(("settlement_reference",))
    validation.get_str(data, "settlement_reference")
    require_state(period, ("CLOSED",), errors.ERR_REBATE_PERIOD_INVALID_STATE)
    contract = db.contracts[period["contract_id"]]
    if contract["compliance_posture"] == "RESTRICTED":
        fail(errors.ERR_CONTRACT_POSTURE_RESTRICTED)

    for dispute in db.pricing_disputes.values():
        if dispute["status"] not in ("OPEN", "UNDER_AUDIT"):
            continue
        line = db.order_lines.get(dispute["order_line_id"])
        if line is not None and line["rebate_period_id"] == period["id"]:
            fail(errors.ERR_OPEN_DISPUTES_BLOCK_SETTLEMENT)

    operator_rebate = period["operator_rebate_cents"] or 0
    manufacturer_funded = period["manufacturer_funded_cents"] or 0

    period["status"] = "SETTLED"
    period["settled_amount_cents"] = operator_rebate
    period["settled_at"] = clock()
    period["settled_by_user_id"] = caller.user_id
    touch(period)

    contract["rebate_payable_cents"] -= operator_rebate
    contract["rebate_settled_total_cents"] += operator_rebate
    recompute_posture(contract)
    touch(contract)

    manufacturer = db.manufacturers.get(contract["rebate_funding_manufacturer_id"])
    if manufacturer is not None:
        manufacturer["rebate_funding_payable_cents"] -= manufacturer_funded
        touch(manufacturer)

    return response.ok(response.serialize(period))


@bp.post(PREFIX + "/rebate-periods/<rebate_period_id>/reverse-settlement")
def reverse_settlement(rebate_period_id):
    middleware.authenticate(["ContractAuditor"])
    period = middleware.get_period(db, rebate_period_id)
    data = validation.body(("reason",))
    validation.get_str(data, "reason")
    require_state(period, ("SETTLED",), errors.ERR_REBATE_PERIOD_INVALID_STATE)

    operator_rebate = period["operator_rebate_cents"] or 0
    manufacturer_funded = period["manufacturer_funded_cents"] or 0

    period["status"] = "CLOSED"
    period["settled_amount_cents"] = 0
    period["settled_at"] = None
    period["settled_by_user_id"] = None
    touch(period)

    contract = db.contracts[period["contract_id"]]
    contract["rebate_payable_cents"] += operator_rebate
    contract["rebate_settled_total_cents"] -= operator_rebate
    recompute_posture(contract)
    touch(contract)

    manufacturer = db.manufacturers.get(contract["rebate_funding_manufacturer_id"])
    if manufacturer is not None:
        manufacturer["rebate_funding_payable_cents"] += manufacturer_funded
        touch(manufacturer)

    return response.ok(response.serialize(period))
