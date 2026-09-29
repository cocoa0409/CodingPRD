"""Entitlement authorization, waivers, suspension and resumption (PRD §3.2, §3.3)."""

from decimal import Decimal

from flask import Blueprint

from db import by_seq, db, touch
from errors import ApiError
from middleware import (
    ROLE_MOVE_COUNSELOR,
    ROLE_PROGRAM_ADMIN,
    ROLE_SERVICE_MEMBER,
    ROLE_TSP_COORDINATOR,
    acting_user_id,
    endpoint,
    require_ownership,
)
from paging import list_response
from response import created, ok
from serializers import serialize
from services import calculations as calc
from services import ledger
from validation import get_body, opt_int, opt_str, req_decimal, req_str

bp = Blueprint("entitlements", __name__)


@bp.get("/entitlements/<entitlement_id>")
@endpoint([ROLE_SERVICE_MEMBER, ROLE_MOVE_COUNSELOR, ROLE_TSP_COORDINATOR, ROLE_PROGRAM_ADMIN])
def read_entitlement(entitlement_id):
    entitlement = ledger.get_entitlement(entitlement_id)
    require_ownership(ledger.member_of_entitlement(entitlement))
    return ok(serialize(entitlement))


@bp.post("/entitlements/<entitlement_id>/authorize")
@endpoint([ROLE_MOVE_COUNSELOR, ROLE_PROGRAM_ADMIN])
def authorize_entitlement(entitlement_id):
    body = get_body()
    bump = opt_int(body, "admin_weight_bump_lbs", default=0, minimum=0, maximum=2000)

    entitlement = ledger.get_entitlement(entitlement_id)

    if entitlement["status"] != "DRAFT":
        raise ApiError(
            "ERR_INVALID_ENTITLEMENT_STATE", "Only a draft entitlement may be authorized."
        )

    entitlement["admin_weight_bump_lbs"] = bump
    entitlement["total_billable_cap_lbs"] = entitlement["base_weight_allowance_lbs"] + bump
    entitlement["authorized_by_user_id"] = acting_user_id()
    entitlement["status"] = "AUTHORIZED"
    touch(entitlement)
    ledger.recompute_entitlement_ledger(entitlement, cascade=False)
    return ok(serialize(entitlement))


@bp.post("/entitlements/<entitlement_id>/excess-cost-waivers")
@endpoint([ROLE_PROGRAM_ADMIN])
def waive_excess_cost(entitlement_id):
    body = get_body()
    waived_amount = req_decimal(body, "waived_amount_usd", minimum=0)
    waiver_reason = req_str(body, "waiver_reason")

    entitlement = ledger.get_entitlement(entitlement_id)

    if (
        entitlement["authorized_by_user_id"] is not None
        and entitlement["authorized_by_user_id"] == acting_user_id()
    ):
        raise ApiError(
            "ERR_WAIVER_SELF_APPROVAL",
            "The user who authorized this entitlement may not waive its excess cost.",
        )
    if entitlement["status"] not in ("AUTHORIZED", "SUSPENDED"):
        raise ApiError(
            "ERR_INVALID_ENTITLEMENT_STATE",
            "Excess cost may only be waived on an authorized or suspended entitlement.",
        )
    amount = calc.money(waived_amount)
    if amount > entitlement["excess_cost_due_usd"]:
        raise ApiError("ERR_WAIVER_EXCEEDS_DUE", "The waived amount exceeds the amount due.")

    entitlement["excess_cost_waived_usd"] = calc.money(
        entitlement["excess_cost_waived_usd"] + amount
    )
    entitlement["waiver_reason"] = waiver_reason
    touch(entitlement)
    ledger.recompute_entitlement_ledger(entitlement, cascade=False)
    return ok(serialize(entitlement))


@bp.post("/entitlements/<entitlement_id>/revoke-waiver")
@endpoint([ROLE_PROGRAM_ADMIN])
def revoke_waiver(entitlement_id):
    body = get_body()
    req_str(body, "revocation_reason")

    entitlement = ledger.get_entitlement(entitlement_id)

    if entitlement["status"] not in ("AUTHORIZED", "SUSPENDED"):
        raise ApiError(
            "ERR_INVALID_ENTITLEMENT_STATE",
            "Waivers may only be revoked on an authorized or suspended entitlement.",
        )
    if entitlement["excess_cost_waived_usd"] == Decimal("0.00"):
        raise ApiError("ERR_NO_WAIVER_TO_REVOKE", "Nothing has been waived on this entitlement.")

    entitlement["excess_cost_waived_usd"] = calc.ZERO
    touch(entitlement)
    ledger.recompute_entitlement_ledger(entitlement, cascade=True)
    return ok(serialize(entitlement))


@bp.post("/entitlements/<entitlement_id>/resume")
@endpoint([ROLE_MOVE_COUNSELOR, ROLE_PROGRAM_ADMIN])
def resume_entitlement(entitlement_id):
    body = get_body()
    opt_str(body, "resume_note")

    entitlement = ledger.get_entitlement(entitlement_id)

    if entitlement["status"] != "SUSPENDED":
        raise ApiError(
            "ERR_INVALID_ENTITLEMENT_STATE", "Only a suspended entitlement may be resumed."
        )
    if entitlement["excess_cost_due_usd"] != Decimal("0.00"):
        raise ApiError("ERR_EXCESS_COST_UNPAID", "Excess cost remains outstanding.")

    entitlement["status"] = "AUTHORIZED"
    entitlement["suspension_reason"] = None
    touch(entitlement)
    for shipment in ledger.shipments_of_entitlement(entitlement["id"]):
        if shipment["movement_status"] == "ON_HOLD":
            shipment["movement_status"] = "AWARDED"
            shipment["hold_reason"] = None
            touch(shipment)
    return ok(serialize(entitlement))


@bp.get("/entitlements/<entitlement_id>/shipments")
@endpoint([ROLE_SERVICE_MEMBER, ROLE_MOVE_COUNSELOR, ROLE_TSP_COORDINATOR, ROLE_PROGRAM_ADMIN])
def list_entitlement_shipments(entitlement_id):
    entitlement = ledger.get_entitlement(entitlement_id)
    require_ownership(ledger.member_of_entitlement(entitlement))
    return list_response(ledger.shipments_of_entitlement(entitlement["id"]))


@bp.get("/entitlements/<entitlement_id>/weight-ledger")
@endpoint([ROLE_SERVICE_MEMBER, ROLE_MOVE_COUNSELOR, ROLE_PROGRAM_ADMIN])
def read_weight_ledger(entitlement_id):
    entitlement = ledger.get_entitlement(entitlement_id)
    require_ownership(ledger.member_of_entitlement(entitlement))
    view = ledger.ledger_view(entitlement)
    data = {
        "entitlement_id": entitlement["id"],
        "total_billable_cap_lbs": entitlement["total_billable_cap_lbs"],
        "charged_billable_weight_lbs": view["charged_billable_weight_lbs"],
        "pro_gear_excluded_total_lbs": view["pro_gear_excluded_total_lbs"],
        "excess_weight_lbs": view["excess_weight_lbs"],
        "excess_pct_over": view["excess_pct_over"],
        "excess_rate_per_cwt": float(view["excess_rate_per_cwt"]),
        "admin_fee_usd": float(view["admin_fee_usd"]),
        "gross_excess_cost_usd": float(view["gross_excess_cost_usd"]),
        "excess_cost_waived_usd": float(view["excess_cost_waived_usd"]),
        "excess_cost_due_usd": float(view["excess_cost_due_usd"]),
        "contributing_shipment_count": view["contributing_shipment_count"],
    }
    return ok(data)
