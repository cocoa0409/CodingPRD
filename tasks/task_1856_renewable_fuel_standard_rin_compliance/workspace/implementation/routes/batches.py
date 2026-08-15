"""RetirementBatch endpoints: create, get, list, submit, decide."""
from flask import Blueprint, request

import db
from errors import (
    invalid_request, not_found, reference_not_found, invalid_state,
    d_code_not_eligible, deadline_passed, insufficient_rins,
    carryover_cap_exceeded,
)
from middleware import require_roles, json_body
from response import ok_object, ok_list, parse_pagination, paginate
from serializers import batch_view
from services import calculations

bp = Blueprint("batches", __name__)

_CATEGORIES = ("CELLULOSIC", "BIOMASS_DIESEL", "ADVANCED", "TOTAL_RENEWABLE")
_D_CODES = ("D3", "D4", "D5", "D6")


def _get_batch(batch_id):
    batch = db.retirement_batches.get(batch_id)
    if batch is None:
        raise not_found("Retirement batch not found")
    return batch


@bp.route("/rfs/retirement-batches", methods=["POST"])
def create_batch():
    require_roles("ComplianceManager")
    body = json_body()

    obligation_year_id = body.get("obligation_year_id")
    category = body.get("category")
    d_code = body.get("d_code")
    rin_qty = body.get("rin_qty")

    # --- Request shape (priority 5) ---
    for field, value in (("obligation_year_id", obligation_year_id), ("category", category),
                         ("d_code", d_code), ("rin_qty", rin_qty)):
        if value is None:
            raise invalid_request(f"{field} is required")
    if category not in _CATEGORIES:
        raise invalid_request("category must be one of CELLULOSIC, BIOMASS_DIESEL, ADVANCED, TOTAL_RENEWABLE")
    if d_code not in _D_CODES:
        raise invalid_request("d_code must be one of D3, D4, D5, D6")
    if not isinstance(rin_qty, int) or isinstance(rin_qty, bool) or rin_qty <= 0:
        raise invalid_request("rin_qty must be a positive integer")

    # --- Referential integrity (priority 6) ---
    year = db.obligation_years.get(obligation_year_id)
    if year is None:
        raise reference_not_found("Referenced obligation year does not exist")

    # --- State (priority 8): no batches for a FINALIZED year ---
    if year["status"] == "FINALIZED":
        raise invalid_state("No retirement batches may be created for a FINALIZED year")

    # --- Regulatory gate (priority 9): d_code must be eligible for category ---
    if category not in calculations.D_CODE_CATEGORY_MAP[d_code]:
        raise d_code_not_eligible("D-code is not eligible for the batch category")

    now = db.now_utc()
    batch = {
        "id": db.new_id(),
        "obligation_year_id": obligation_year_id,
        "category": category,
        "d_code": d_code,
        "rin_qty": rin_qty,
        "allocations": [],
        "prior_vintage_qty": 0,
        "status": "DRAFT",
        "submitted_at": None,
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    db.retirement_batches[batch["id"]] = batch
    return ok_object(batch_view(batch), status=201)


@bp.route("/rfs/retirement-batches/<batch_id>", methods=["GET"])
def get_batch(batch_id):
    require_roles("OpsAdmin", "ComplianceManager", "Trader")
    return ok_object(batch_view(_get_batch(batch_id)))


@bp.route("/rfs/retirement-batches", methods=["GET"])
def list_batches():
    require_roles("OpsAdmin", "ComplianceManager", "Trader")
    limit, offset = parse_pagination(request.args)
    obligation_year_id = request.args.get("obligation_year_id")
    rows = list(db.retirement_batches.values())
    if obligation_year_id is not None:
        rows = [r for r in rows if r["obligation_year_id"] == obligation_year_id]
    rows.sort(key=lambda r: r["created_at"])
    page, total = paginate(rows, limit, offset)
    return ok_list([batch_view(r) for r in page], limit, offset, total)


@bp.route("/rfs/retirement-batches/<batch_id>/submit", methods=["POST"])
def submit_batch(batch_id):
    require_roles("ComplianceManager")
    batch = _get_batch(batch_id)
    year = db.obligation_years[batch["obligation_year_id"]]

    # State: batch must be DRAFT; year must be OPEN or VOLUME_CLOSED
    if batch["status"] != "DRAFT":
        raise invalid_state("Retirement batch is not DRAFT")
    if year["status"] == "FINALIZED":
        raise invalid_state("Obligation year is FINALIZED")

    # Temporal gate: submit at or before (year+1)-03-31T23:59:59Z
    now = db.now_utc()
    if now > db.march31_deadline(year["year"] + 1):
        raise deadline_passed("Retirement submission deadline has passed")

    # FIFO allocation (also computes prior_vintage_qty)
    result = calculations.fifo_allocate(year, batch["d_code"], batch["rin_qty"])
    if result is None:
        raise insufficient_rins("FIFO-eligible RIN supply is below the batch rin_qty")
    allocations, prior_vintage_qty = result

    # Carryover cap: batch prior + retired prior <= cap (at-cap passes)
    suffix = calculations.category_suffix(batch["category"])
    cap = calculations.carryover_cap(year, batch["category"])
    if prior_vintage_qty + year[f"retired_prior_{suffix}_rins"] > cap:
        raise carryover_cap_exceeded("Prior-vintage RINs would exceed the 20% carryover cap")

    # Commit: record allocations, move lot quantities separated -> pending_retired
    batch["allocations"] = allocations
    batch["prior_vintage_qty"] = prior_vintage_qty
    batch["status"] = "SUBMITTED"
    batch["submitted_at"] = now
    batch["version"] += 1
    batch["updated_at"] = now

    for alloc in allocations:
        lot = db.rin_lots[alloc["rin_lot_id"]]
        lot["separated_qty"] -= alloc["qty"]
        lot["pending_retired_qty"] += alloc["qty"]
        calculations.sync_available(lot)
        lot["version"] += 1
        lot["updated_at"] = now

    return ok_object(batch_view(batch))


@bp.route("/rfs/retirement-batches/<batch_id>/decide", methods=["POST"])
def decide_batch(batch_id):
    require_roles("OpsAdmin")
    batch = _get_batch(batch_id)
    body = json_body()
    decision = body.get("decision")
    if decision not in ("ACCEPT", "REJECT"):
        raise invalid_request("decision must be ACCEPT or REJECT")

    if batch["status"] != "SUBMITTED":
        raise invalid_state("Retirement batch is not SUBMITTED")

    year = db.obligation_years[batch["obligation_year_id"]]
    now = db.now_utc()

    if decision == "ACCEPT":
        # Precondition: every allocated lot still ACTIVE with pending covering its allocation
        for alloc in batch["allocations"]:
            lot = db.rin_lots.get(alloc["rin_lot_id"])
            if lot is None or lot["status"] != "ACTIVE" or lot["pending_retired_qty"] < alloc["qty"]:
                raise insufficient_rins("An allocated lot expired or was invalidated while SUBMITTED")
        # Debit each lot: pending -> retired; EXHAUSTED when available reaches 0
        for alloc in batch["allocations"]:
            lot = db.rin_lots[alloc["rin_lot_id"]]
            lot["pending_retired_qty"] -= alloc["qty"]
            lot["retired_qty"] += alloc["qty"]
            calculations.sync_available(lot)
            if lot["available_qty"] == 0:
                lot["status"] = "EXHAUSTED"
            lot["version"] += 1
            lot["updated_at"] = now
        batch["status"] = "ACCEPTED"
        batch["version"] += 1
        batch["updated_at"] = now
        # Re-derive year counters (nested mapping) and posture
        calculations.rederive_year_retirement_counters(year)
        calculations.rederive_posture(year)
        year["version"] += 1
        year["updated_at"] = now
    else:
        # REJECT: release pending allocations back onto separated_qty
        for alloc in batch["allocations"]:
            lot = db.rin_lots.get(alloc["rin_lot_id"])
            if lot is None:
                continue
            lot["pending_retired_qty"] -= alloc["qty"]
            lot["separated_qty"] += alloc["qty"]
            calculations.sync_available(lot)
            lot["version"] += 1
            lot["updated_at"] = now
        batch["status"] = "REJECTED"
        batch["version"] += 1
        batch["updated_at"] = now

    return ok_object(batch_view(batch))
