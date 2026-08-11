from flask import Blueprint, request
from decimal import Decimal
from middleware import get_caller, require_role, get_json_body
from services.common import (require_string, require_enum, require_int,
                             parse_pagination, occ_check, round_half_up_cents)
from response import success_object, success_list
from errors import ApiError
from db import db, new_common, touch, CLOCK, add_days, new_id, now_iso
from services.serialize import serialize
from services.core import recompute_landlord_totals

bp = Blueprint("settlements", __name__)
READ_ROLES = {"FarmManager", "Landlord", "Tenant"}
PRICE_SOURCES = {"ESTIMATED", "ACTUAL"}


def _compute_amounts(lease, field, crop_year, price_source, yield_bu, price_cents):
    """Compute gross_revenue, landlord_amount, input_share_total, net. Returns dict."""
    gross = yield_bu * price_cents * field["acres"]
    if lease["lease_type"] == "FLEX":
        base_total = lease["base_rent_cents_per_acre"] * field["acres"]
        raw_bonus = (Decimal(gross) - Decimal(lease["revenue_trigger_cents"])) \
            * Decimal(str(lease["landlord_bonus_pct"]))
        if raw_bonus <= 0:
            bonus = 0
        else:
            bonus = min(lease["flex_cap_cents"], round_half_up_cents(raw_bonus))
        landlord_amount = base_total + bonus
    else:  # SHARE
        landlord_amount = round_half_up_cents(
            Decimal(gross) * Decimal(str(lease["landlord_share_pct"])))
    # Input sharing: per-line rounded sum over APPROVED expenses of lease+crop_year
    input_total = 0
    for exp in db.expenses.values():
        if (exp["lease_id"] == lease["id"] and exp["crop_year"] == crop_year
                and exp["status"] == "APPROVED"):
            input_total += exp["landlord_share_cents"]
    net = landlord_amount - input_total
    return {
        "gross_revenue_cents": gross,
        "landlord_amount_cents": landlord_amount,
        "input_share_total_cents": input_total,
        "net_settlement_cents": net,
    }


@bp.route("/settlements", methods=["POST"])
def create_settlement():
    _, role = get_caller()
    require_role(role, {"FarmManager"})
    body = get_json_body()
    lease_id = require_string(body, "lease_id")
    crop_year = require_int(body, "crop_year")
    price_source = require_enum(body, "price_source", PRICE_SOURCES)
    yield_bu = require_int(body, "yield_bu_per_acre", minimum=1)
    price_cents = require_int(body, "harvest_price_cents_per_bu", minimum=1)

    # Existence
    lease = db.leases.get(lease_id)
    if lease is None:
        raise ApiError("ERR_NOT_FOUND", 404, f"Lease {lease_id} not found")

    # OCC on expected_lease_version
    occ_check(body, "expected_lease_version", lease["version"])

    # State: lease ACTIVE/TERMINATION_PENDING/TERMINATED
    if lease["status"] not in ("ACTIVE", "TERMINATION_PENDING", "TERMINATED"):
        raise ApiError("ERR_LEASE_NOT_ACTIVE", 409,
                       "Settlement requires lease ACTIVE, TERMINATION_PENDING, or TERMINATED")

    # Type applicability
    if lease["lease_type"] == "CASH":
        raise ApiError("ERR_SETTLEMENT_NOT_APPLICABLE", 409,
                       "Settlements do not apply to CASH leases")

    # Uniqueness: non-VOID sibling rules
    for s in db.settlements.values():
        if s["lease_id"] == lease_id and s["crop_year"] == crop_year:
            if s["status"] in ("FINALIZED", "DISPUTED", "COUNTERSIGNED"):
                raise ApiError("ERR_SETTLEMENT_YEAR_FINAL_EXISTS", 409,
                               "A finalized settlement already exists for this lease+crop_year")

    # Supersede existing PROVISIONAL sibling
    for s in db.settlements.values():
        if s["lease_id"] == lease_id and s["crop_year"] == crop_year and s["status"] == "PROVISIONAL":
            s["status"] = "VOID"
            touch(s)

    field = db.fields.get(lease["field_id"])
    amounts = _compute_amounts(lease, field, crop_year, price_source, yield_bu, price_cents)

    rec = new_common()
    rec.update({
        "lease_id": lease_id,
        "crop_year": crop_year,
        "price_source": price_source,
        "yield_bu_per_acre": yield_bu,
        "harvest_price_cents_per_bu": price_cents,
        "gross_revenue_cents": amounts["gross_revenue_cents"],
        "landlord_amount_cents": amounts["landlord_amount_cents"],
        "input_share_total_cents": amounts["input_share_total_cents"],
        "net_settlement_cents": amounts["net_settlement_cents"],
        "billed_amount_cents": None,
        "true_up_cents": None,
        "finalized_by": None,
        "status": "PROVISIONAL",
    })
    db.settlements[rec["id"]] = rec
    touch(lease)  # settlement creation increments Lease.version
    return success_object(serialize("settlement", rec), status=201)


@bp.route("/settlements/<settlementId>", methods=["GET"])
def get_settlement(settlementId):
    _, role = get_caller()
    require_role(role, READ_ROLES)
    rec = db.settlements.get(settlementId)
    if rec is None:
        raise ApiError("ERR_NOT_FOUND", 404, f"Settlement {settlementId} not found")
    return success_object(serialize("settlement", rec))


@bp.route("/settlements", methods=["GET"])
def list_settlements():
    _, role = get_caller()
    require_role(role, READ_ROLES)
    limit, offset = parse_pagination(request.args)
    items = sorted(db.settlements.values(), key=lambda r: r["created_at"])
    lease_q = request.args.get("lease_id")
    if lease_q is not None:
        items = [r for r in items if r["lease_id"] == lease_q]
    status_q = request.args.get("status")
    if status_q is not None:
        items = [r for r in items if r["status"] == status_q]
    cy_q = request.args.get("crop_year")
    if cy_q is not None:
        try:
            cy = int(cy_q)
            items = [r for r in items if r["crop_year"] == cy]
        except ValueError:
            raise ApiError("ERR_VALIDATION", 400, "crop_year must be an integer")
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([serialize("settlement", r) for r in page], limit, offset, total)


@bp.route("/settlements/<settlementId>/finalize", methods=["POST"])
def finalize_settlement(settlementId):
    user_id, role = get_caller()
    require_role(role, {"FarmManager"})
    rec = db.settlements.get(settlementId)
    if rec is None:
        raise ApiError("ERR_NOT_FOUND", 404, f"Settlement {settlementId} not found")
    if rec["status"] != "PROVISIONAL":
        raise ApiError("ERR_INVALID_STATE", 409,
                       f"Settlement in state {rec['status']} cannot be finalized")
    if rec["price_source"] != "ACTUAL":
        raise ApiError("ERR_PRICE_NOT_FINAL", 409,
                       "Only ACTUAL settlements can be finalized")
    lease = db.leases.get(rec["lease_id"])
    field = db.fields.get(lease["field_id"]) if lease else None
    amounts = _compute_amounts(lease, field, rec["crop_year"], rec["price_source"],
                               rec["yield_bu_per_acre"], rec["harvest_price_cents_per_bu"])
    rec.update(amounts)
    rec["finalized_by"] = user_id
    rec["status"] = "FINALIZED"
    touch(rec)
    return success_object(serialize("settlement", rec))


@bp.route("/settlements/<settlementId>/countersign", methods=["POST"])
def countersign_settlement(settlementId):
    user_id, role = get_caller()
    require_role(role, {"FarmManager"})
    rec = db.settlements.get(settlementId)
    if rec is None:
        raise ApiError("ERR_NOT_FOUND", 404, f"Settlement {settlementId} not found")
    if rec["status"] != "FINALIZED":
        raise ApiError("ERR_INVALID_STATE", 409,
                       f"Settlement in state {rec['status']} cannot be countersigned")
    if rec.get("finalized_by") == user_id:
        raise ApiError("ERR_DUTY_SEGREGATION_VIOLATION", 403,
                       "Countersigner must differ from finalized_by")

    lease = db.leases.get(rec["lease_id"])
    # True-up: billed = sum of amount_cents over installments whose term_index maps
    # to crop_year, excluding adjustment installments created by THIS settlement.
    # Term mapping: term whose term_start year == crop_year. term_index starts at 1
    # for term_start_date's year, so mapped term_index = crop_year - term_start.year + 1.
    term_start_year = lease["term_start_date"].year
    mapped_term_index = rec["crop_year"] - term_start_year + 1
    billed = 0
    for inst in db.installments.values():
        if inst["lease_id"] == lease["id"] and inst["term_index"] == mapped_term_index:
            if inst.get("_adjustment_of") == rec["id"]:
                continue  # exclude this settlement's own adjustment
            billed += inst["amount_cents"]
    true_up = rec["net_settlement_cents"] - billed
    rec["billed_amount_cents"] = billed
    rec["true_up_cents"] = true_up
    rec["status"] = "COUNTERSIGNED"
    touch(rec)

    if true_up > 0:
        adj = new_common()
        adj.update({
            "lease_id": lease["id"],
            "term_index": lease["term_index"],  # current term_index per PRD
            "due_date": add_days(CLOCK.get(), 30),
            "amount_cents": true_up,
            "late_fee_cents": 0,
            "paid_cents": 0,
            "last_payment_at": None,
            "paid_recorded_by": None,
            "status": "SCHEDULED",
            "_adjustment_of": rec["id"],
        })
        db.installments[adj["id"]] = adj
    elif true_up < 0:
        lease["landlord_credit_cents"] = lease.get("landlord_credit_cents", 0) + (-true_up)
        touch(lease)
    recompute_landlord_totals(lease["landlord_id"])
    return success_object(serialize("settlement", rec))


@bp.route("/settlements/<settlementId>/dispute", methods=["POST"])
def dispute_settlement(settlementId):
    user_id, role = get_caller()
    require_role(role, {"Tenant", "Landlord"})
    rec = db.settlements.get(settlementId)
    if rec is None:
        raise ApiError("ERR_NOT_FOUND", 404, f"Settlement {settlementId} not found")
    lease = db.leases.get(rec["lease_id"])
    if lease is None:
        raise ApiError("ERR_NOT_FOUND", 404, "Settlement lease missing")
    # Ownership: caller must be a lease party
    if role == "Tenant" and lease["tenant_id"] != user_id:
        raise ApiError("ERR_NOT_RESOURCE_OWNER", 403, "Caller is not the lease tenant")
    if role == "Landlord" and lease["landlord_id"] != user_id:
        raise ApiError("ERR_NOT_RESOURCE_OWNER", 403, "Caller is not the lease landlord")
    if rec["status"] != "FINALIZED":
        raise ApiError("ERR_INVALID_STATE", 409,
                       f"Settlement in state {rec['status']} cannot be disputed")
    rec["status"] = "DISPUTED"
    touch(rec)
    return success_object(serialize("settlement", rec))


@bp.route("/settlements/<settlementId>/refinalize", methods=["POST"])
def refinalize_settlement(settlementId):
    user_id, role = get_caller()
    require_role(role, {"FarmManager"})
    body = get_json_body()
    yield_bu = require_int(body, "yield_bu_per_acre", minimum=1)
    price_cents = require_int(body, "harvest_price_cents_per_bu", minimum=1)

    rec = db.settlements.get(settlementId)
    if rec is None:
        raise ApiError("ERR_NOT_FOUND", 404, f"Settlement {settlementId} not found")
    if rec["status"] != "DISPUTED":
        raise ApiError("ERR_INVALID_STATE", 409,
                       f"Settlement in state {rec['status']} cannot be refinalized")
    rec["yield_bu_per_acre"] = yield_bu
    rec["harvest_price_cents_per_bu"] = price_cents
    lease = db.leases.get(rec["lease_id"])
    field = db.fields.get(lease["field_id"]) if lease else None
    amounts = _compute_amounts(lease, field, rec["crop_year"], rec["price_source"],
                               yield_bu, price_cents)
    rec.update(amounts)
    rec["finalized_by"] = user_id
    rec["status"] = "FINALIZED"
    touch(rec)
    return success_object(serialize("settlement", rec))
