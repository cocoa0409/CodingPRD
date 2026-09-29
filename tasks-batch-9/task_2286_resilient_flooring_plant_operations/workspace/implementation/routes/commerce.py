"""Distributor allocations, substitution fills and warranty adjudication (PRD 3.8, 3.9)."""

from decimal import Decimal

from flask import Blueprint, request

import calc
import cascades
from calc import d, rhu
from db import db, new_row, serialize as _ser, touch
from errors import ApiError
from middleware import authorize, find, owner_guard, user_id
from response import enum_filter, list_response, object_response, string_filter
from support import STATUS_CREATED, body, unique
from validate import field as F
from validate import validate

bp = Blueprint("commerce", __name__)

ALLOCATION_STATUS = ("OPEN", "PARTIALLY_FILLED", "FILLED", "RELEASED", "CANCELLED")
SUBSTITUTION_POLICY = ("STRICT_SKU", "ALLOW_UNDERLAYMENT_UPGRADE", "ALLOW_WEAR_LAYER_UPGRADE")
LINE_STATUS = ("ACTIVE", "VOIDED")

CLAIM_TYPE = ("WEAR_LAYER_WEARTHROUGH", "DELAMINATION", "DIMENSIONAL_MOVEMENT", "LOCK_FAILURE")
CLAIM_STATUS = ("SUBMITTED", "TRIAGE", "ADJUDICATION_READY", "APPROVED", "DENIED")
REVIEW_KIND = ("MATERIALS", "FIELD")
REVIEW_OUTCOME = ("DEFECT_CONFIRMED", "NO_DEFECT", "INCONCLUSIVE")
OUTCOME_FIELD = {"MATERIALS": "materials_review_outcome", "FIELD": "field_review_outcome"}

ALLOCATION_READERS = ("PlantAdmin", "ProductionPlanner", "Distributor")
CLAIM_READERS = ("PlantAdmin", "WarrantyAdjuster", "QaTechnician", "Distributor")

ZERO2 = Decimal("0.00")


# ---------------------------------------------------------------------------
# Allocation
# ---------------------------------------------------------------------------

@bp.post("/allocations")
def create_allocation():
    authorize("Distributor", "PlantAdmin")
    data = validate([
        F("allocation_code", "string", required=True),
        F("distributor_id", "string", required=True),
        F("sku_id", "string", required=True),
        F("requested_quantity_sqm", "number", required=True, exclusive_min=0, decimals=2),
        F("substitution_policy", "string", enum=SUBSTITUTION_POLICY, default="STRICT_SKU"),
    ], body())
    sku = find("product_skus", data["sku_id"])
    distributor = find("distributors", data["distributor_id"])
    owner_guard(distributor["id"])
    unique("allocations", "allocation_code", data["allocation_code"])
    if sku["certification_status"] != "CERTIFIED":
        raise ApiError("ERR_SKU_NOT_PRODUCIBLE")

    row = new_row()
    row.update({
        "allocation_code": data["allocation_code"],
        "distributor_id": distributor["id"],
        "sku_id": sku["id"],
        "requested_quantity_sqm": data["requested_quantity_sqm"],
        "allocated_quantity_sqm": ZERO2,
        "substitution_policy": data["substitution_policy"],
        "upgrade_cost_total_cents": 0,
        "status": "OPEN",
    })
    db.allocations[row["id"]] = row
    return object_response(_ser(row), STATUS_CREATED)


@bp.get("/allocations")
def list_allocations():
    authorize(*ALLOCATION_READERS)
    status = enum_filter(request.args, "status", ALLOCATION_STATUS)
    distributor_id = string_filter(request.args, "distributor_id")
    sku_id = string_filter(request.args, "sku_id")
    rows = [r for r in db.allocations.values()
            if (status is None or r["status"] == status)
            and (distributor_id is None or r["distributor_id"] == distributor_id)
            and (sku_id is None or r["sku_id"] == sku_id)]
    return list_response(rows, request.args, _ser)


@bp.get("/allocations/<row_id>")
def read_allocation(row_id):
    authorize(*ALLOCATION_READERS)
    allocation = find("allocations", row_id)
    owner_guard(allocation["distributor_id"])
    return object_response(_ser(allocation))


@bp.get("/allocations/<row_id>/lines")
def allocation_lines(row_id):
    authorize(*ALLOCATION_READERS)
    allocation = find("allocations", row_id)
    owner_guard(allocation["distributor_id"])
    status = enum_filter(request.args, "status", LINE_STATUS)
    rows = [line for line in db.allocation_lines.values()
            if line["allocation_id"] == allocation["id"]
            and (status is None or line["status"] == status)]
    return list_response(rows, request.args, _ser)


@bp.post("/allocations/<row_id>/fill")
def fill_allocation(row_id):
    authorize("Distributor")
    data = validate([F("expected_allocation_version", "integer", required=True)], body())
    allocation = find("allocations", row_id)
    owner_guard(allocation["distributor_id"])
    if allocation["status"] in ("RELEASED", "CANCELLED"):
        raise ApiError("ERR_INVALID_ALLOCATION_STATE")
    if data["expected_allocation_version"] != allocation["version"]:
        raise ApiError("ERR_STALE_ALLOCATION_VERSION")

    requested_sku = db.product_skus.get(allocation["sku_id"])
    if requested_sku is None or requested_sku["commercial_status"] != "RELEASED":
        raise ApiError("ERR_SKU_NOT_PRODUCIBLE")
    if d(allocation["allocated_quantity_sqm"]) >= d(allocation["requested_quantity_sqm"]):
        raise ApiError("ERR_ALLOCATION_OVER_REQUEST")

    candidates = calc.fill_candidates(allocation)
    if not candidates:
        raise ApiError("ERR_NO_ELIGIBLE_BATCH")

    remaining = rhu(d(allocation["requested_quantity_sqm"])
                    - d(allocation["allocated_quantity_sqm"]), 2)
    for batch, kind in candidates:
        if remaining <= 0:
            break
        available = d(batch["available_quantity_sqm"])
        draw = remaining if remaining < available else available
        draw = rhu(draw, 2)
        if draw <= 0:
            continue
        candidate_sku = db.product_skus.get(batch["sku_id"])
        if kind == "EXACT":
            delta = 0
        else:
            premium = calc.upgrade_premium_per_sqm(candidate_sku, requested_sku)
            delta = int(rhu(draw * Decimal(premium), 0))
        line = new_row()
        line.update({
            "allocation_id": allocation["id"],
            "batch_id": batch["id"],
            "quantity_sqm": draw,
            "substitution_kind": kind,
            "upgrade_cost_delta_cents": delta,
            "status": "ACTIVE",
            "void_reason": None,
        })
        db.allocation_lines[line["id"]] = line
        batch["available_quantity_sqm"] = rhu(available - draw, 2)
        touch(batch)
        remaining = rhu(remaining - draw, 2)

    cascades.recompute_allocation(allocation)
    return object_response(_ser(allocation))


@bp.post("/allocations/<row_id>/release")
def release_allocation(row_id):
    authorize("Distributor")
    allocation = find("allocations", row_id)
    owner_guard(allocation["distributor_id"])
    if allocation["status"] not in ("OPEN", "PARTIALLY_FILLED", "FILLED"):
        raise ApiError("ERR_INVALID_ALLOCATION_STATE")

    for line in cascades.active_lines_of_allocation(allocation):
        line["status"] = "VOIDED"
        line["void_reason"] = "ALLOCATION_RELEASED"
        touch(line)
        batch = db.batches.get(line["batch_id"])
        if batch is not None:
            batch["available_quantity_sqm"] = rhu(
                d(batch["available_quantity_sqm"]) + d(line["quantity_sqm"]), 2)
            touch(batch)
    allocation["allocated_quantity_sqm"] = ZERO2
    allocation["upgrade_cost_total_cents"] = 0
    allocation["status"] = "RELEASED"
    touch(allocation)
    return object_response(_ser(allocation))


# ---------------------------------------------------------------------------
# WarrantyClaim
# ---------------------------------------------------------------------------

def _traceable(batch):
    """Band 14 (V-REF-5)."""
    if batch.get("traceability_snapshot") is None or batch["status"] == "IN_PRODUCTION":
        raise ApiError("ERR_BATCH_NOT_TRACEABLE")


def _claim_state_guard(claim, allowed):
    if claim["status"] not in allowed:
        raise ApiError("ERR_INVALID_CLAIM_STATE")


@bp.post("/warranty-claims")
def create_claim():
    authorize("Distributor", "WarrantyAdjuster")
    data = validate([
        F("claim_code", "string", required=True),
        F("batch_id", "string", required=True),
        F("distributor_id", "string", required=True),
        F("claim_type", "string", required=True, enum=CLAIM_TYPE),
        F("claimed_area_sqm", "number", required=True, exclusive_min=0, decimals=2),
        F("installed_on", "datetime", required=True),
        F("reported_on", "datetime", required=True),
        F("installed_by_certified_installer", "boolean", default=False),
    ], body())
    if data["reported_on"] < data["installed_on"]:
        raise ApiError("ERR_CLAIM_DATES_INVALID")
    distributor = find("distributors", data["distributor_id"])
    batch = find("batches", data["batch_id"])
    owner_guard(distributor["id"])
    unique("warranty_claims", "claim_code", data["claim_code"])
    _traceable(batch)

    row = new_row()
    row.update({
        "claim_code": data["claim_code"],
        "batch_id": batch["id"],
        "distributor_id": distributor["id"],
        "claim_type": data["claim_type"],
        "claimed_area_sqm": data["claimed_area_sqm"],
        "installed_on": data["installed_on"],
        "reported_on": data["reported_on"],
        "installed_by_certified_installer": data["installed_by_certified_installer"],
        "status": "SUBMITTED",
        "required_reviews": None,
        "materials_review_outcome": None,
        "field_review_outcome": None,
        "assigned_adjuster_user_id": None,
        "elapsed_months": None,
        "settlement_variant": None,
        "replacement_value_cents": None,
        "labor_allowance_cents": None,
        "settlement_amount_cents": None,
        "denial_reason": None,
    })
    db.warranty_claims[row["id"]] = row
    return object_response(_ser(row), STATUS_CREATED)


@bp.get("/warranty-claims")
def list_claims():
    authorize(*CLAIM_READERS)
    status = enum_filter(request.args, "status", CLAIM_STATUS)
    batch_id = string_filter(request.args, "batch_id")
    distributor_id = string_filter(request.args, "distributor_id")
    claim_type = enum_filter(request.args, "claim_type", CLAIM_TYPE)
    rows = [r for r in db.warranty_claims.values()
            if (status is None or r["status"] == status)
            and (batch_id is None or r["batch_id"] == batch_id)
            and (distributor_id is None or r["distributor_id"] == distributor_id)
            and (claim_type is None or r["claim_type"] == claim_type)]
    return list_response(rows, request.args, _ser)


@bp.get("/warranty-claims/<row_id>")
def read_claim(row_id):
    authorize(*CLAIM_READERS)
    claim = find("warranty_claims", row_id)
    owner_guard(claim["distributor_id"])
    return object_response(_ser(claim))


@bp.post("/warranty-claims/<row_id>/triage")
def triage_claim(row_id):
    authorize("WarrantyAdjuster")
    claim = find("warranty_claims", row_id)
    _claim_state_guard(claim, ("SUBMITTED",))
    batch = db.batches.get(claim["batch_id"])
    if batch is None or batch["status"] == "SCRAPPED":
        raise ApiError("ERR_INVALID_BATCH_STATE")
    _traceable(batch)

    if claim["claim_type"] in calc.STEPPED_TYPES:
        claim["required_reviews"] = ["MATERIALS", "FIELD"]
    else:
        claim["required_reviews"] = ["FIELD"]
    claim["assigned_adjuster_user_id"] = user_id()
    claim["status"] = "TRIAGE"
    touch(claim)
    return object_response(_ser(claim))


@bp.post("/warranty-claims/<row_id>/reviews")
def record_review(row_id):
    authorize("WarrantyAdjuster")
    data = validate([
        F("review_kind", "string", required=True, enum=REVIEW_KIND),
        F("outcome", "string", required=True, enum=REVIEW_OUTCOME),
        F("note", "string"),
    ], body())
    claim = find("warranty_claims", row_id)
    _claim_state_guard(claim, ("TRIAGE",))
    required = claim["required_reviews"] or []
    kind = data["review_kind"]
    if kind not in required:
        raise ApiError("ERR_INVALID_REQUEST")
    if claim[OUTCOME_FIELD[kind]] is not None:
        raise ApiError("ERR_INVALID_REQUEST")

    claim[OUTCOME_FIELD[kind]] = data["outcome"]
    if all(claim[OUTCOME_FIELD[arm]] is not None for arm in required):
        claim["status"] = "ADJUDICATION_READY"
    touch(claim)
    return object_response(_ser(claim))


@bp.post("/warranty-claims/<row_id>/adjudicate")
def adjudicate_claim(row_id):
    authorize("WarrantyAdjuster")
    data = validate([
        F("decision", "string", required=True, enum=("APPROVE", "DENY")),
        F("denial_reason", "string"),
    ], body())
    claim = find("warranty_claims", row_id)
    _claim_state_guard(claim, ("ADJUDICATION_READY",))
    if user_id() == claim["assigned_adjuster_user_id"]:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES")

    if data["decision"] == "DENY":
        claim["status"] = "DENIED"
        claim["denial_reason"] = data["denial_reason"]
        touch(claim)
        return object_response(_ser(claim))

    batch = db.batches.get(claim["batch_id"])
    sku = db.product_skus.get(batch["sku_id"]) if batch is not None else None
    elapsed = calc.elapsed_whole_months(claim["installed_on"], claim["reported_on"])
    coverage_months = (sku["warranty_years"] * 12) if sku is not None else 0
    if elapsed >= coverage_months:
        raise ApiError("ERR_WARRANTY_EXPIRED")
    for arm in (claim["required_reviews"] or []):
        if claim[OUTCOME_FIELD[arm]] != "DEFECT_CONFIRMED":
            raise ApiError("ERR_REVIEW_OUTCOME_CONFLICT")

    claim["elapsed_months"] = elapsed
    claim.update(calc.warranty_settlement(claim, batch, sku))
    claim["status"] = "APPROVED"
    touch(claim)
    return object_response(_ser(claim))


__all__ = ["bp"]
