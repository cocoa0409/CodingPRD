"""Cost change notices, market indexing and the four-hop activation cascade."""

from flask import Blueprint

import errors
import middleware
import response
import validation
from db import db, clock, insert, touch, values
from errors import fail
from routes.common import PREFIX, listing, owned_contract, require_contract_active, require_state
from services import cascade
from services.pricing import (
    MAJOR_CHANGE_PCT, MINOR_NOTICE_DAYS, NOTICE_WINDOW_DAYS,
    cost_on_basis, has_active_tier,
)
from util import add_days, cents, dec, pct

bp = Blueprint("notices", __name__)

NOTICE_INPUT = ("cost_basis", "effective_at", "published_index_value", "proposed_cost_cents")


def _read_inputs(data):
    cost_basis = validation.get_enum(data, "cost_basis", validation.COST_BASES)
    effective_at = validation.get_dt(data, "effective_at")
    index_value = validation.get_decimal(data, "published_index_value", required=False,
                                        default=None, exclusive_minimum=0)
    proposed_cost = validation.get_int(data, "proposed_cost_cents", required=False,
                                       default=None, minimum=1)
    return cost_basis, effective_at, index_value, proposed_cost


def _require_supplied(product, index_value, proposed_cost):
    """The item dictates which of the two price inputs is mandatory."""
    if product["is_market_indexed"]:
        if index_value is None:
            fail(errors.ERR_INDEX_VALUE_REQUIRED)
    elif proposed_cost is None:
        fail(errors.ERR_INDEX_VALUE_REQUIRED)


def _require_exclusive(product, index_value, proposed_cost):
    if product["is_market_indexed"]:
        if proposed_cost is not None:
            fail(errors.ERR_INDEX_VALUE_REQUIRED)
    elif index_value is not None:
        fail(errors.ERR_INDEX_VALUE_REQUIRED)


def _derive(contract, product, cost_basis, effective_at, index_value, proposed_cost):
    """market_index_cost_reset: new cost, signed delta, notice window."""
    if product["is_market_indexed"]:
        new_cost_cents = cents(dec(product["index_baseline_cost_cents"]) * dec(index_value)
                               / dec(product["index_baseline_value"]))
    else:
        new_cost_cents = proposed_cost

    current_cost = cost_on_basis(product, cost_basis)
    if current_cost in (None, 0):
        delta_pct = dec("0.00")
    else:
        delta_pct = pct(dec(new_cost_cents - current_cost) * dec(100) / dec(current_cost))

    if abs(delta_pct) >= MAJOR_CHANGE_PCT:
        notice_required_days = contract["notice_period_days"]
    else:
        notice_required_days = MINOR_NOTICE_DAYS

    submitted_at = clock()
    earliest_effective_at = add_days(submitted_at, notice_required_days)
    if effective_at < earliest_effective_at:
        fail(errors.ERR_NOTICE_PERIOD_TOO_SHORT)

    return {
        "new_cost_cents": new_cost_cents,
        "delta_pct": delta_pct,
        "notice_required_days": notice_required_days,
        "submitted_at": submitted_at,
        "earliest_effective_at": earliest_effective_at,
    }


@bp.post(PREFIX + "/price-change-notices")
def create_notice():
    middleware.authenticate(["PricingAnalyst"])
    data = validation.body(("contract_id", "product_id") + NOTICE_INPUT)
    contract = middleware.get_contract(db, validation.raw_fk(data, "contract_id"))
    product = middleware.get_product(db, validation.raw_fk(data, "product_id"))
    cost_basis, effective_at, index_value, proposed_cost = _read_inputs(data)

    require_contract_active(contract)

    if cost_on_basis(product, cost_basis) is None or not has_active_tier(
            contract["id"], product["product_class_code"]):
        fail(errors.ERR_NO_TIER_FOR_PRODUCT_CLASS)

    _require_supplied(product, index_value, proposed_cost)

    for other in values(db.price_change_notices):
        if other["product_id"] != product["id"]:
            continue
        if other["status"] not in ("PENDING", "ACKNOWLEDGED"):
            continue
        gap = other["effective_at"] - effective_at
        if abs(gap.total_seconds()) < NOTICE_WINDOW_DAYS * 86400:
            fail(errors.ERR_NOTICE_WINDOW_CONFLICT)

    derived = _derive(contract, product, cost_basis, effective_at,
                      index_value, proposed_cost)
    _require_exclusive(product, index_value, proposed_cost)

    record = insert(db.price_change_notices, dict({
        "contract_id": contract["id"],
        "product_id": product["id"],
        "cost_basis": cost_basis,
        "published_index_value": index_value,
        "proposed_cost_cents": proposed_cost,
        "effective_at": effective_at,
        "status": "PENDING",
        "dispute_note": None,
    }, **derived))
    return response.created(response.serialize(record))


@bp.get(PREFIX + "/price-change-notices/<price_change_notice_id>")
def read_notice(price_change_notice_id):
    middleware.authenticate(["PricingAnalyst", "NationalAccountManager", "OperatorBuyer",
                             "ContractAuditor"])
    record = middleware.get_notice(db, price_change_notice_id)
    return response.ok(response.serialize(record))


@bp.get(PREFIX + "/price-change-notices")
def list_notices():
    middleware.authenticate(["PricingAnalyst", "NationalAccountManager", "OperatorBuyer",
                             "ContractAuditor"])
    return listing(db.price_change_notices, (
        ("contract_id", "contract_id", None),
        ("product_id", "product_id", None),
        ("status", "status", validation.NOTICE_STATUSES),
    ))


@bp.post(PREFIX + "/price-change-notices/<price_change_notice_id>/acknowledge")
def acknowledge_notice(price_change_notice_id):
    caller = middleware.authenticate(["OperatorBuyer"])
    notice = middleware.get_notice(db, price_change_notice_id)
    owned_contract(caller, db.contracts[notice["contract_id"]])
    validation.body(())
    require_state(notice, ("PENDING", "DISPUTED"), errors.ERR_NOTICE_INVALID_STATE)
    notice["status"] = "ACKNOWLEDGED"
    touch(notice)
    return response.ok(response.serialize(notice))


@bp.post(PREFIX + "/price-change-notices/<price_change_notice_id>/dispute")
def dispute_notice(price_change_notice_id):
    caller = middleware.authenticate(["OperatorBuyer"])
    notice = middleware.get_notice(db, price_change_notice_id)
    owned_contract(caller, db.contracts[notice["contract_id"]])
    data = validation.body(("note",))
    note = validation.get_str(data, "note")
    require_state(notice, ("PENDING",), errors.ERR_NOTICE_INVALID_STATE)
    notice["status"] = "DISPUTED"
    notice["dispute_note"] = note
    touch(notice)
    return response.ok(response.serialize(notice))


@bp.post(PREFIX + "/price-change-notices/<price_change_notice_id>/revise")
def revise_notice(price_change_notice_id):
    middleware.authenticate(["PricingAnalyst"])
    notice = middleware.get_notice(db, price_change_notice_id)
    data = validation.body(NOTICE_INPUT)
    cost_basis, effective_at, index_value, proposed_cost = _read_inputs(data)

    require_state(notice, ("DISPUTED",), errors.ERR_NOTICE_INVALID_STATE)
    contract = db.contracts[notice["contract_id"]]
    require_contract_active(contract)

    product = db.products[notice["product_id"]]
    _require_supplied(product, index_value, proposed_cost)
    derived = _derive(contract, product, cost_basis, effective_at,
                      index_value, proposed_cost)
    _require_exclusive(product, index_value, proposed_cost)

    notice["cost_basis"] = cost_basis
    notice["effective_at"] = effective_at
    notice["published_index_value"] = index_value
    notice["proposed_cost_cents"] = proposed_cost
    notice.update(derived)
    notice["dispute_note"] = None
    notice["status"] = "PENDING"
    touch(notice)
    return response.ok(response.serialize(notice))


@bp.post(PREFIX + "/price-change-notices/<price_change_notice_id>/activate")
def activate_notice(price_change_notice_id):
    middleware.authenticate(["PricingAnalyst"])
    notice = middleware.get_notice(db, price_change_notice_id)
    validation.body(())
    require_state(notice, ("ACKNOWLEDGED",), errors.ERR_NOTICE_INVALID_STATE)
    contract = db.contracts[notice["contract_id"]]
    require_contract_active(contract)
    now = clock()
    if now < notice["effective_at"]:
        fail(errors.ERR_NOTICE_NOT_YET_EFFECTIVE)

    notice["status"] = "EFFECTIVE"
    touch(notice)
    cascade.notice_activation_cascade(notice, now)
    return response.ok(response.serialize(notice))


@bp.post(PREFIX + "/price-change-notices/<price_change_notice_id>/withdraw")
def withdraw_notice(price_change_notice_id):
    middleware.authenticate(["PricingAnalyst"])
    notice = middleware.get_notice(db, price_change_notice_id)
    validation.body(("reason",))
    require_state(notice, ("PENDING", "ACKNOWLEDGED", "DISPUTED"),
                  errors.ERR_NOTICE_INVALID_STATE)
    notice["status"] = "WITHDRAWN"
    touch(notice)
    return response.ok(response.serialize(notice))
