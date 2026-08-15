from datetime import date as date_cls
from datetime import timedelta
from decimal import Decimal

from flask import Blueprint

from db import store, current_date, now_iso
from errors import ApiError
from helpers import (
    add_trace,
    base_fields,
    ber_threshold_cents,
    create_invoice,
    credit_held,
    get_customer_or_404,
    get_exchange_or_404,
    get_part_or_404,
    get_unit_or_404,
    list_response,
    pub,
    q_cents,
    sort_items,
    touch,
)
from middleware import ALL_ROLES, get_json_body, require_roles, validate_body
from response import ok

bp = Blueprint("exchange", __name__, url_prefix="/mro")

ADMIN_FEE_CENTS = 25000
CORE_RETURN_DAYS = 15
LATE_FEE_PER_DAY_CENTS = 50000


@bp.route("/exchange-agreements", methods=["POST"])
@require_roles("CustomerServiceRep")
def create_exchange():
    body = validate_body(
        get_json_body(), {"customer_id": ("str", True), "part_id": ("str", True)}
    )
    cust = get_customer_or_404(body["customer_id"])
    part = get_part_or_404(body["part_id"])
    ag = dict(base_fields())
    ag.update(
        {
            "customer_id": cust["id"],
            "part_id": part["id"],
            "status": "OPEN",
            "pool_unit_id": None,
            "fulfilled_at": None,
            "core_due_date": None,
            "core_unit_id": None,
            "core_received_at": None,
            "core_ber_flag": False,
            "core_charge_cents": None,
            "late_fee_cents": None,
            "admin_fee_cents": ADMIN_FEE_CENTS,
            "settlement_total_cents": None,
        }
    )
    store.exchanges[ag["id"]] = ag
    return ok(pub(ag), 201)


@bp.route("/exchange-agreements/<agreementId>", methods=["GET"])
@require_roles(*ALL_ROLES)
def get_exchange(agreementId):
    return ok(pub(get_exchange_or_404(agreementId)))


@bp.route("/exchange-agreements", methods=["GET"])
@require_roles(*ALL_ROLES)
def list_exchanges():
    return list_response(
        store.exchanges.values(),
        filters={
            "customer_id": "customer_id",
            "part_id": "part_id",
            "pool_unit_id": "pool_unit_id",
            "core_unit_id": "core_unit_id",
            "status": "status",
        },
    )


@bp.route("/exchange-agreements/<agreementId>/fulfill", methods=["POST"])
@require_roles("CustomerServiceRep")
def fulfill_exchange(agreementId):
    ag = get_exchange_or_404(agreementId)
    if ag["status"] != "OPEN":
        raise ApiError("ERR_EXCHANGE_INVALID_STATE", 409, "Exchange agreement not OPEN")
    # Pool selector: part match, SHOP-owned, IN_POOL, SERVICEABLE;
    # rank cycles_since_overhaul ASC, tie-break created_at ASC (never id).
    candidates = [
        u
        for u in store.units.values()
        if u["part_id"] == ag["part_id"]
        and u["ownership"] == "SHOP"
        and u["custody_status"] == "IN_POOL"
        and u["condition_status"] == "SERVICEABLE"
    ]
    if not candidates:
        raise ApiError("ERR_POOL_EMPTY", 422, "No eligible pool unit")
    candidates.sort(key=lambda u: (u["cycles_since_overhaul"], u["created_at"], u["_seq"]))
    unit = candidates[0]
    cust = store.customers[ag["customer_id"]]
    if credit_held(cust):
        raise ApiError("ERR_CUSTOMER_CREDIT_HOLD", 402, "Customer is on credit hold")
    ag["pool_unit_id"] = unit["id"]
    ag["fulfilled_at"] = now_iso()
    ag["core_due_date"] = (current_date() + timedelta(days=CORE_RETURN_DAYS)).isoformat()
    ag["status"] = "FULFILLED"
    touch(ag)
    unit["custody_status"] = "SHIPPED"
    touch(unit)
    add_trace(unit["id"], "EXCHANGE_OUT", notes=ag["id"])
    return ok(pub(ag))


@bp.route("/exchange-agreements/<agreementId>/core-return", methods=["POST"])
@require_roles("Technician")
def core_return(agreementId):
    ag = get_exchange_or_404(agreementId)
    body = validate_body(
        get_json_body(),
        {"core_unit_id": ("str", True), "core_teardown_estimate_cents": ("int", True)},
    )
    core = get_unit_or_404(body["core_unit_id"])
    # Order: from-state, then core ownership matching, then core part matching.
    if ag["status"] != "FULFILLED":
        raise ApiError("ERR_EXCHANGE_INVALID_STATE", 409, "Exchange agreement not FULFILLED")
    if core["ownership"] != "CUSTOMER" or core["owner_customer_id"] != ag["customer_id"]:
        raise ApiError(
            "ERR_UNIT_OWNER_MISMATCH", 422, "Core owner does not match agreement customer"
        )
    if core["part_id"] != ag["part_id"]:
        raise ApiError("ERR_CORE_PART_MISMATCH", 422, "Core part does not match agreement part")
    part = store.parts[ag["part_id"]]
    # Hop 1: core induction.
    core_ber = body["core_teardown_estimate_cents"] >= ber_threshold_cents(part)
    core["ownership"] = "SHOP"
    core["owner_customer_id"] = None
    if core_ber:
        core["custody_status"] = "IN_SHOP"
    else:
        core["custody_status"] = "IN_POOL"
        core["condition_status"] = "SERVICEABLE"
    touch(core)
    add_trace(core["id"], "CORE_IN", notes=ag["id"])
    # Hop 2: pinned settlement evaluation order (1) core status -> (5) total.
    replacement = part["replacement_value_cents"]
    if core_ber:
        core_charge = q_cents(Decimal("0.80") * Decimal(replacement))
    else:
        core_charge = 0
    return_date = current_date()
    due = date_cls.fromisoformat(ag["core_due_date"])
    late_days = max(0, (return_date - due).days)
    late_fee = min(
        late_days * LATE_FEE_PER_DAY_CENTS, max(0, replacement - core_charge)
    )
    settlement = ADMIN_FEE_CENTS + core_charge + late_fee
    ag["core_unit_id"] = core["id"]
    ag["core_received_at"] = now_iso()
    ag["core_ber_flag"] = core_ber
    ag["core_charge_cents"] = core_charge
    ag["late_fee_cents"] = late_fee
    ag["admin_fee_cents"] = ADMIN_FEE_CENTS
    ag["settlement_total_cents"] = settlement
    inv = create_invoice(
        "EXCHANGE",
        ag["customer_id"],
        exchange_agreement_id=ag["id"],
        other_charge_cents=settlement,
        total_cents=settlement,
    )
    # Hop 3: exposure already updated by create_invoice. Hop 4: close.
    ag["status"] = "CLOSED"
    touch(ag)
    return ok(pub(ag))
