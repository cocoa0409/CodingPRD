"""The payable ledger: posting, disputes, umpire rounds, cash and reversals (PRD 3.9)."""

from flask import Blueprint, g

import calc
import services
from core import (
    ApiError,
    db,
    endpoint,
    f_enum,
    f_num,
    f_str,
    filter_eq,
    paginate,
    payload,
    sort_rows,
    touch,
)

bp = Blueprint("settlement", __name__)

SETTLEMENT_READ_ROLES = [
    "PlatformAdmin",
    "SettlementAccountant",
    "SupplierRep",
    "PlantOperator",
    "AssayTechnician",
]


@endpoint(bp, "/recycling/settlements", ["GET"], SETTLEMENT_READ_ROLES, 200)
def list_settlements():
    data = payload()
    rows = sort_rows(db.settlements.values())
    rows = filter_eq(rows, data, "intake_id")
    rows = filter_eq(rows, data, "supplier_id")
    rows = filter_eq(rows, data, "variant")
    rows = filter_eq(rows, data, "state")
    return paginate(rows, data)


@endpoint(
    bp, "/recycling/settlements/<settlement_id>", ["GET"], SETTLEMENT_READ_ROLES, 200
)
def get_settlement(settlement_id):
    return services.settlement_or_404(settlement_id)


@endpoint(
    bp,
    "/recycling/settlements/<settlement_id>/post",
    ["POST"],
    ["SettlementAccountant"],
    200,
)
def post_settlement(settlement_id):
    settlement = services.settlement_or_404(settlement_id)
    if settlement["state"] != "DRAFT":
        raise ApiError("ERR_SETTLEMENT_NOT_DRAFT")
    supplier = db.suppliers.get(settlement["supplier_id"])

    # link 1
    settlement["posted_amount_cents"] = settlement["net_payable_cents"]
    settlement["state"] = "POSTED"
    touch(settlement)
    if supplier is not None:
        # link 2
        supplier["payable_balance_cents"] += settlement["posted_amount_cents"]
        touch(supplier)
        # links 3 and 4
        services.apply_credit_hold(supplier)
    return settlement


@endpoint(
    bp, "/recycling/settlements/<settlement_id>/dispute", ["POST"], ["SupplierRep"], 200
)
def dispute_settlement(settlement_id):
    settlement = services.settlement_or_404(settlement_id)
    if g.user_id != settlement["supplier_id"]:
        raise ApiError("ERR_NOT_OWNER")
    data = payload()
    reason = f_str(data, "dispute_reason")
    if settlement["state"] != "POSTED":
        raise ApiError("ERR_SETTLEMENT_NOT_POSTED")
    if settlement["dispute_round"] >= calc.DISPUTE_ROUND_LIMIT:
        raise ApiError("ERR_DISPUTE_ROUNDS_EXHAUSTED")
    variance = settlement["max_variance_pp"]
    if (
        settlement["variant"] != "FINAL"
        or variance is None
        or variance <= calc.DISPUTE_TOLERANCE_PP
    ):
        raise ApiError("ERR_VARIANCE_WITHIN_TOLERANCE")

    settlement["dispute_reason"] = reason
    settlement["dispute_round"] += 1
    settlement["state"] = "DISPUTED"
    touch(settlement)
    return settlement


@endpoint(
    bp,
    "/recycling/settlements/<settlement_id>/umpire-assay",
    ["POST"],
    ["AssayTechnician"],
    200,
)
def umpire_assay(settlement_id):
    data = payload()
    metal = f_enum(data, "metal", calc.PAYABLE_METALS)
    contained = f_num(data, "umpire_contained_kg", ge=0)
    settlement = services.settlement_or_404(settlement_id)
    if settlement["state"] != "DISPUTED":
        raise ApiError("ERR_SETTLEMENT_NOT_DISPUTED")

    lot = db.lots.get(settlement.get("_lot_id"))
    outputs = calc.lot_outputs(lot["id"]) if lot is not None else []
    if not any(output["metal"] == metal for output in outputs):
        raise ApiError(
            "ERR_INVALID_REQUEST",
            "'metal' has no assay line on the contributing lot.",
        )

    settlement["umpire_metal"] = metal
    settlement["umpire_contained_kg"] = contained
    settlement["state"] = "UMPIRE_ROUND"
    touch(settlement)
    return settlement


@endpoint(
    bp,
    "/recycling/settlements/<settlement_id>/apply-umpire",
    ["POST"],
    ["SettlementAccountant"],
    200,
)
def apply_umpire(settlement_id):
    settlement = services.settlement_or_404(settlement_id)
    if settlement["state"] != "UMPIRE_ROUND":
        raise ApiError("ERR_SETTLEMENT_NOT_IN_UMPIRE_ROUND")

    intake = db.intakes.get(settlement["intake_id"])
    supplier = db.suppliers.get(settlement["supplier_id"])
    lot = db.lots.get(settlement.get("_lot_id"))

    services.price_settlement(
        settlement,
        intake,
        supplier,
        "FINAL",
        lot["finalized_at"] if lot is not None else settlement["price_basis_date"],
        lot=lot,
        umpire_metal=settlement["umpire_metal"],
        umpire_contained_kg=settlement["umpire_contained_kg"],
    )

    old_posted = settlement["posted_amount_cents"]
    settlement["posted_amount_cents"] = 0
    settlement["state"] = "DRAFT"
    touch(settlement)
    if supplier is not None:
        supplier["payable_balance_cents"] -= old_posted
        touch(supplier)
        services.release_credit_hold(supplier)
    return settlement


@endpoint(
    bp,
    "/recycling/settlements/<settlement_id>/settle",
    ["POST"],
    ["SettlementAccountant"],
    200,
)
def settle_settlement(settlement_id):
    data = payload()
    reference = f_str(data, "payment_reference")
    settlement = services.settlement_or_404(settlement_id)
    if settlement["state"] != "POSTED":
        raise ApiError("ERR_SETTLEMENT_NOT_POSTED")
    settlement["payment_reference"] = reference
    settlement["state"] = "SETTLED"
    touch(settlement)
    supplier = db.suppliers.get(settlement["supplier_id"])
    if supplier is not None:
        amount = settlement["posted_amount_cents"]
        supplier["paid_to_date_cents"] += amount
        supplier["payable_balance_cents"] -= amount
        touch(supplier)
        services.release_credit_hold(supplier)
    return settlement


@endpoint(
    bp,
    "/recycling/settlements/<settlement_id>/void",
    ["POST"],
    ["SettlementAccountant"],
    200,
)
def void_settlement(settlement_id):
    data = payload()
    reason = f_str(data, "void_reason")
    settlement = services.settlement_or_404(settlement_id)
    if settlement["state"] != "POSTED":
        raise ApiError("ERR_SETTLEMENT_NOT_POSTED")
    old_posted = settlement["posted_amount_cents"]
    settlement["void_reason"] = reason
    settlement["posted_amount_cents"] = 0
    settlement["state"] = "VOIDED"
    touch(settlement)
    supplier = db.suppliers.get(settlement["supplier_id"])
    if supplier is not None:
        supplier["payable_balance_cents"] -= old_posted
        touch(supplier)
        services.release_credit_hold(supplier)
    return settlement
