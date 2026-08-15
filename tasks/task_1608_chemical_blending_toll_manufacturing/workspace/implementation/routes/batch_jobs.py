"""BatchJob endpoints — includes release/complete lifecycle."""
from decimal import Decimal
from flask import Blueprint, request

import db
import errors
from middleware import require_role
from response import success_object, success_list
from services.common import (
    new_id,
    now_iso,
    pagination_params,
    paginate,
    sort_by_created_at,
    serialize_batch_job,
    serialize_batch_charge,
    to_decimal,
    to_int,
    parse_iso,
    as_float_3dp,
    reconcile_lot_quantities,
)
from services.calculations import (
    compute_theoretical_output_kg,
    compute_density_corrected_output_l,
    compute_yield_variance_pct,
    price_batch_job,
    zone_admits,
    ghs_pair_compatible,
    ceil_l,
)

bp = Blueprint("batch_jobs", __name__)

NON_TERMINAL_BATCH_STATUSES = {"INTAKE", "RELEASED", "CHARGING", "MIXING", "HOLD_QA"}


def _customer_or_404(cid):
    c = db.customers.get(cid)
    if c is None:
        raise errors.not_found("customer not found")
    return c


def _batch_or_404(customer_id, batch_id):
    b = db.batch_jobs.get(batch_id)
    if b is None or b["customer_id"] != customer_id:
        raise errors.not_found("batch job not found")
    return b


def _charge_or_404(batch_id, charge_id):
    c = db.batch_charges.get(charge_id)
    if c is None or c["batch_job_id"] != batch_id:
        raise errors.not_found("batch charge not found")
    return c


def _windows_overlap(a_start, a_end, b_start, b_end):
    return a_start < b_end and b_start < a_end


# ---------------- Batch jobs collection ----------------

@bp.route("/toll-operations/customers/<id>/batch-jobs", methods=["POST"])
def create_batch_job(id):
    require_role({"BatchScheduler"})
    customer = _customer_or_404(id)
    body = request.get_json(silent=True) or {}

    recipe_id = body.get("recipe_id")
    pricing_agreement_id = body.get("pricing_agreement_id")
    tank_id = body.get("tank_id")
    if not recipe_id or not isinstance(recipe_id, str):
        raise errors.invalid_request("recipe_id required")
    if not pricing_agreement_id or not isinstance(pricing_agreement_id, str):
        raise errors.invalid_request("pricing_agreement_id required")
    if not tank_id or not isinstance(tank_id, str):
        raise errors.invalid_request("tank_id required")

    batch_size_l = to_int(body.get("batch_size_l"), "batch_size_l")
    if batch_size_l <= 0:
        raise errors.invalid_request("batch_size_l must be > 0")
    scheduled_start = body.get("scheduled_start")
    scheduled_end = body.get("scheduled_end")
    if not scheduled_start or not scheduled_end:
        raise errors.invalid_request("scheduled_start/scheduled_end required")
    ss = parse_iso(scheduled_start)
    se = parse_iso(scheduled_end)
    if not (se > ss):
        raise errors.invalid_request("scheduled_end must be > scheduled_start")

    # FK existence
    recipe = db.recipes.get(recipe_id)
    if recipe is None:
        raise errors.not_found("recipe not found")
    agreement = db.pricing_agreements.get(pricing_agreement_id)
    if agreement is None:
        raise errors.not_found("pricing agreement not found")
    tank = db.tanks.get(tank_id)
    if tank is None:
        raise errors.not_found("tank not found")

    # Customer credit-hold gate at create
    if customer["status"] != "ACTIVE" or customer["credit_hold"]:
        raise errors.ApiError(errors.ERR_CUSTOMER_CREDIT_HOLD, 403, "customer on credit hold or not ACTIVE")

    # Recipe must be APPROVED
    if recipe["status"] != "APPROVED":
        raise errors.ApiError(errors.ERR_RECIPE_NOT_APPROVED, 409, "recipe not APPROVED")

    # Compute theoretical_output_kg
    theo_kg = compute_theoretical_output_kg(
        batch_size_l,
        recipe["target_density_kg_per_l"],
        recipe["theoretical_yield_pct"],
    )

    now = now_iso()
    bid = new_id()
    batch = {
        "id": bid,
        "customer_id": id,
        "recipe_id": recipe_id,
        "pricing_agreement_id": pricing_agreement_id,
        "tank_id": tank_id,
        "batch_size_l": batch_size_l,
        "scheduled_start": scheduled_start,
        "scheduled_end": scheduled_end,
        "theoretical_output_kg": theo_kg,
        "actual_output_kg": None,
        "density_corrected_output_l": None,
        "yield_variance_pct": None,
        "quoted_price_cents": None,
        "invoiced_price_cents": None,
        "highest_component_ghs_snapshot": recipe["highest_component_ghs"],
        "status": "INTAKE",
        "version": 1,
        "created_at": now,
        "updated_at": now,
    }
    # Provisional price
    batch["quoted_price_cents"] = price_batch_job(agreement, batch, "PROVISIONAL")
    db.batch_jobs[bid] = batch
    return success_object(serialize_batch_job(batch), status=201)


@bp.route("/toll-operations/customers/<id>/batch-jobs", methods=["GET"])
def list_batch_jobs(id):
    require_role({"Any"})
    _customer_or_404(id)
    limit, offset = pagination_params()
    rows = [b for b in db.batch_jobs.values() if b["customer_id"] == id]
    status = request.args.get("status")
    if status:
        rows = [b for b in rows if b["status"] == status]
    rows = sort_by_created_at(rows)
    slice_, total = paginate(rows, limit, offset)
    return success_list([serialize_batch_job(b) for b in slice_], limit, offset, total)


@bp.route("/toll-operations/customers/<id>/batch-jobs/<batchJobId>", methods=["GET"])
def get_batch_job(id, batchJobId):
    require_role({"Any"})
    _customer_or_404(id)
    b = _batch_or_404(id, batchJobId)
    return success_object(serialize_batch_job(b))


# ---------------- Batch lifecycle transitions ----------------

@bp.route("/toll-operations/customers/<id>/batch-jobs/<batchJobId>/release", methods=["POST"])
def release_batch_job(id, batchJobId):
    require_role({"BatchScheduler"})
    customer = _customer_or_404(id)
    batch = _batch_or_404(id, batchJobId)

    if batch["status"] != "INTAKE":
        raise errors.invalid_state("batch job not INTAKE")

    # Customer credit hold
    if customer["status"] != "ACTIVE" or customer["credit_hold"]:
        raise errors.ApiError(errors.ERR_CUSTOMER_CREDIT_HOLD, 403, "customer not ACTIVE or on credit hold")

    # Tank checks
    tank = db.tanks.get(batch["tank_id"])
    if tank is None:
        raise errors.not_found("tank not found")

    if tank["cleaning_state"] != "CLEAN_VALIDATED":
        raise errors.ApiError(errors.ERR_TANK_NOT_CLEAN_VALIDATED, 409, "tank not CLEAN_VALIDATED")

    # Segregation: batch's GHS vs tank zone
    snap_ghs = batch["highest_component_ghs_snapshot"]
    if not zone_admits(snap_ghs, tank["current_zone"]):
        raise errors.ApiError(errors.ERR_INCOMPATIBLE_SEGREGATION, 409, "batch GHS incompatible with tank zone")
    # If last_product_ghs non-null and cleaning short of CLEAN_VALIDATED — actually
    # cleaning_state == CLEAN_VALIDATED is enforced above, and when CLEAN_VALIDATED
    # the last_product_ghs is cleared to null. So this check is mostly redundant,
    # but we keep it for robustness per validation #8.
    if tank.get("last_product_ghs") is not None and tank["cleaning_state"] != "CLEAN_VALIDATED":
        if not ghs_pair_compatible(snap_ghs, tank["last_product_ghs"]):
            raise errors.ApiError(errors.ERR_INCOMPATIBLE_SEGREGATION, 409, "incompatible with prior product")

    # Pricing agreement temporal
    agreement = db.pricing_agreements.get(batch["pricing_agreement_id"])
    if agreement is None:
        raise errors.not_found("pricing agreement not found")
    if agreement["status"] != "ACTIVE":
        raise errors.ApiError(errors.ERR_AGREEMENT_NOT_ACTIVE, 409, "agreement not ACTIVE")
    now_clock = db.get_clock()
    now_dt = parse_iso(now_clock)
    ef_dt = parse_iso(agreement["effective_from"])
    et_dt = parse_iso(agreement["effective_to"])
    if not (ef_dt <= now_dt < et_dt):
        raise errors.ApiError(errors.ERR_AGREEMENT_NOT_ACTIVE, 409, "current_utc outside agreement window")

    # Tank schedule overlap
    b_ss = parse_iso(batch["scheduled_start"])
    b_se = parse_iso(batch["scheduled_end"])
    for other in db.batch_jobs.values():
        if other["id"] == batch["id"]:
            continue
        if other["tank_id"] != tank["id"]:
            continue
        if other["status"] not in NON_TERMINAL_BATCH_STATUSES:
            continue
        o_ss = parse_iso(other["scheduled_start"])
        o_se = parse_iso(other["scheduled_end"])
        if _windows_overlap(b_ss, b_se, o_ss, o_se):
            raise errors.ApiError(errors.ERR_TANK_SCHEDULE_OVERLAP, 409, "tank schedule overlap")

    # Capacity
    if batch["batch_size_l"] > tank["working_capacity_l"]:
        raise errors.ApiError(errors.ERR_BATCH_SIZE_EXCEEDS_CAPACITY, 422, "batch_size_l exceeds working_capacity_l")

    # OCC last
    body = request.get_json(silent=True) or {}
    expected = body.get("expected_batch_job_version")
    if expected is None:
        raise errors.ApiError(errors.ERR_STALE_VERSION, 412, "expected_batch_job_version required")
    try:
        expected_int = int(expected)
    except (TypeError, ValueError):
        raise errors.ApiError(errors.ERR_STALE_VERSION, 412, "expected_batch_job_version invalid")
    if expected_int != batch["version"]:
        raise errors.ApiError(errors.ERR_STALE_VERSION, 412, "stale batch version")

    # Cascade: reserve tank
    now = now_iso()
    tank["operational_state"] = "RESERVED"
    tank["occupied_by_batch_id"] = batch["id"]
    tank["version"] += 1
    tank["updated_at"] = now

    batch["status"] = "RELEASED"
    batch["version"] += 1
    batch["updated_at"] = now
    return success_object(serialize_batch_job(batch))


@bp.route("/toll-operations/customers/<id>/batch-jobs/<batchJobId>/start-charging", methods=["POST"])
def start_charging(id, batchJobId):
    require_role({"TankOperator"})
    _customer_or_404(id)
    batch = _batch_or_404(id, batchJobId)
    if batch["status"] != "RELEASED":
        raise errors.invalid_state("batch not RELEASED")

    # Verify every recipe component has exactly one COMMITTED charge with matching material_code
    recipe = db.recipes.get(batch["recipe_id"])
    components = recipe["components"] if recipe else []
    charges = [c for c in db.batch_charges.values() if c["batch_job_id"] == batch["id"]]
    committed_charges = [c for c in charges if c["status"] == "COMMITTED"]

    # Build charge_order -> component
    comp_by_order = {c["charge_order"]: c for c in components}
    charge_orders_seen = {}
    for ch in committed_charges:
        co = ch["charge_order"]
        if co not in comp_by_order:
            raise errors.ApiError(errors.ERR_INCOMPLETE_CHARGES, 409, f"charge_order {co} not in recipe")
        if co in charge_orders_seen:
            raise errors.ApiError(errors.ERR_INCOMPLETE_CHARGES, 409, "duplicate charge_order")
        # material code match
        lot = db.raw_material_lots.get(ch["raw_material_lot_id"])
        if lot is None:
            raise errors.ApiError(errors.ERR_INCOMPLETE_CHARGES, 409, "lot missing")
        if lot["material_code"] != comp_by_order[co]["material_code"]:
            raise errors.ApiError(errors.ERR_INCOMPLETE_CHARGES, 409, "material_code mismatch")
        if lot["customer_id"] != batch["customer_id"]:
            raise errors.ApiError(errors.ERR_INCOMPLETE_CHARGES, 409, "lot not owned by batch customer")
        charge_orders_seen[co] = ch
    if len(charge_orders_seen) != len(components):
        raise errors.ApiError(errors.ERR_INCOMPLETE_CHARGES, 409, "not all components charged")

    now = now_iso()
    # Tank cascade RESERVED -> IN_USE
    tank = db.tanks.get(batch["tank_id"])
    if tank is not None and tank.get("occupied_by_batch_id") == batch["id"]:
        tank["operational_state"] = "IN_USE"
        tank["version"] += 1
        tank["updated_at"] = now

    # COMMITTED -> CONSUMED
    for ch in committed_charges:
        ch["status"] = "CONSUMED"
        ch["version"] += 1
        ch["updated_at"] = now

    # Reconcile lots
    lot_ids = {ch["raw_material_lot_id"] for ch in committed_charges}
    for lid in lot_ids:
        reconcile_lot_quantities(lid)
        lot = db.raw_material_lots.get(lid)
        if lot is not None:
            lot["version"] += 1
            lot["updated_at"] = now

    batch["status"] = "CHARGING"
    batch["version"] += 1
    batch["updated_at"] = now
    return success_object(serialize_batch_job(batch))


@bp.route("/toll-operations/customers/<id>/batch-jobs/<batchJobId>/start-mixing", methods=["POST"])
def start_mixing(id, batchJobId):
    require_role({"TankOperator"})
    _customer_or_404(id)
    batch = _batch_or_404(id, batchJobId)
    if batch["status"] != "CHARGING":
        raise errors.invalid_state("batch not CHARGING")
    # All charges must be CONSUMED
    charges = [c for c in db.batch_charges.values() if c["batch_job_id"] == batch["id"]]
    for ch in charges:
        if ch["status"] != "CONSUMED":
            raise errors.invalid_state("not all charges CONSUMED")
    batch["status"] = "MIXING"
    batch["version"] += 1
    batch["updated_at"] = now_iso()
    return success_object(serialize_batch_job(batch))


@bp.route("/toll-operations/customers/<id>/batch-jobs/<batchJobId>/hold-for-qa", methods=["POST"])
def hold_for_qa(id, batchJobId):
    require_role({"TankOperator"})
    _customer_or_404(id)
    batch = _batch_or_404(id, batchJobId)
    if batch["status"] != "MIXING":
        raise errors.invalid_state("batch not MIXING")
    batch["status"] = "HOLD_QA"
    batch["version"] += 1
    batch["updated_at"] = now_iso()
    return success_object(serialize_batch_job(batch))


@bp.route("/toll-operations/customers/<id>/batch-jobs/<batchJobId>/complete", methods=["POST"])
def complete_batch(id, batchJobId):
    require_role({"QAValidator"})
    _customer_or_404(id)
    batch = _batch_or_404(id, batchJobId)
    if batch["status"] != "HOLD_QA":
        raise errors.invalid_state("batch not HOLD_QA")

    body = request.get_json(silent=True) or {}
    actual_output_kg = body.get("actual_output_kg")
    if actual_output_kg is None:
        raise errors.invalid_request("actual_output_kg required")
    actual_d = to_decimal(actual_output_kg, "actual_output_kg")
    if actual_d < 0:
        raise errors.invalid_request("actual_output_kg must be >= 0")

    # SDS gate
    sds_issued = None
    for s in db.sds_documents.values():
        if s["batch_job_id"] == batch["id"] and s["status"] == "ISSUED":
            sds_issued = s
            break
    if sds_issued is None:
        raise errors.ApiError(errors.ERR_SDS_NOT_ISSUED, 409, "no ISSUED SDS")

    # Package config gate
    pkg = None
    for p in db.package_configs.values():
        if p["batch_job_id"] == batch["id"]:
            pkg = p
            break
    # Get classification from latest non-SUPERSEDED SDS
    ghs_classification = sds_issued["ghs_classification"]

    # UN-rated check
    if pkg is None:
        # Package config must exist; PRD §3.6 "The package configuration must exist"
        raise errors.ApiError(errors.ERR_PACKAGE_VOLUME_INSUFFICIENT, 422, "package config missing")
    if not pkg["un_rated"] and ghs_classification != "NON_HAZ":
        raise errors.ApiError(errors.ERR_UN_RATED_PACKAGE_REQUIRED, 422, "un_rated required for non-NON_HAZ")

    # Compute density_corrected_output_l
    recipe = db.recipes.get(batch["recipe_id"])
    density = recipe["target_density_kg_per_l"]
    dco_l = compute_density_corrected_output_l(actual_d, density)
    needed_l = ceil_l(dco_l)
    if pkg["total_volume_l"] < needed_l:
        raise errors.ApiError(errors.ERR_PACKAGE_VOLUME_INSUFFICIENT, 422, "package volume insufficient")

    # Placard check
    if pkg["placard_required"]:
        if pkg["placard_class"] is None:
            raise errors.ApiError(errors.ERR_PLACARD_MISSING, 422, "placard_class missing")
        # Find shipment
        shipment = None
        for s in db.shipments.values():
            if s["batch_job_id"] == batch["id"]:
                shipment = s
                break
        if shipment is None:
            raise errors.ApiError(errors.ERR_PLACARD_MISSING, 422, "shipment missing")
        if pkg["placard_class"] not in (shipment.get("vehicle_placards") or []):
            raise errors.ApiError(errors.ERR_PLACARD_MISSING, 422, "placard_class not mounted on vehicle")

    # Heel disposition check: every component lot must have >=1 POSTED heel disposal
    component_material_codes = {c["material_code"] for c in (recipe["components"] if recipe else [])}
    # Find all lots charged into this batch (any charge row)
    charged_lot_ids = set()
    for ch in db.batch_charges.values():
        if ch["batch_job_id"] == batch["id"]:
            charged_lot_ids.add(ch["raw_material_lot_id"])
    # For each charged lot, check at least one POSTED heel disposal
    for lot_id in charged_lot_ids:
        has_posted = any(
            h["batch_job_id"] == batch["id"]
            and h["raw_material_lot_id"] == lot_id
            and h["status"] == "POSTED"
            for h in db.heel_disposals.values()
        )
        if not has_posted:
            raise errors.ApiError(errors.ERR_HEEL_NOT_DISPOSITIONED, 409, f"lot {lot_id} heel not dispositioned")

    # Apply side effects
    batch["actual_output_kg"] = as_float_3dp(actual_d)
    batch["density_corrected_output_l"] = dco_l
    batch["yield_variance_pct"] = compute_yield_variance_pct(actual_d, batch["theoretical_output_kg"])

    agreement = db.pricing_agreements.get(batch["pricing_agreement_id"])
    batch["invoiced_price_cents"] = price_batch_job(agreement, batch, "FINAL")

    now = now_iso()
    batch["status"] = "COMPLETED"
    batch["version"] += 1
    batch["updated_at"] = now

    # Tank cascade IN_USE -> AVAILABLE
    tank = db.tanks.get(batch["tank_id"])
    if tank is not None and tank.get("occupied_by_batch_id") == batch["id"]:
        tank["operational_state"] = "AVAILABLE"
        tank["occupied_by_batch_id"] = None
        tank["last_product_ghs"] = batch["highest_component_ghs_snapshot"]
        tank["cleaning_state"] = "DIRTY"
        tank["version"] += 1
        tank["updated_at"] = now

    return success_object(serialize_batch_job(batch))


@bp.route("/toll-operations/customers/<id>/batch-jobs/<batchJobId>/reject-qa", methods=["POST"])
def reject_qa_batch(id, batchJobId):
    require_role({"QAValidator"})
    _customer_or_404(id)
    batch = _batch_or_404(id, batchJobId)
    if batch["status"] != "HOLD_QA":
        raise errors.invalid_state("batch not HOLD_QA")

    now = now_iso()
    # Tank cascade
    tank = db.tanks.get(batch["tank_id"])
    if tank is not None and tank.get("occupied_by_batch_id") == batch["id"]:
        tank["operational_state"] = "AVAILABLE"
        tank["occupied_by_batch_id"] = None
        tank["last_product_ghs"] = batch["highest_component_ghs_snapshot"]
        tank["cleaning_state"] = "DIRTY"
        tank["version"] += 1
        tank["updated_at"] = now

    # COMMITTED charges -> RELEASED, reconcile lot
    affected_lots = set()
    for ch in db.batch_charges.values():
        if ch["batch_job_id"] == batch["id"] and ch["status"] == "COMMITTED":
            ch["status"] = "RELEASED"
            ch["version"] += 1
            ch["updated_at"] = now
            affected_lots.add(ch["raw_material_lot_id"])
    for lid in affected_lots:
        reconcile_lot_quantities(lid)
        lot = db.raw_material_lots.get(lid)
        if lot is not None:
            lot["version"] += 1
            lot["updated_at"] = now

    batch["status"] = "REJECTED_QA"
    batch["version"] += 1
    batch["updated_at"] = now
    return success_object(serialize_batch_job(batch))


@bp.route("/toll-operations/customers/<id>/batch-jobs/<batchJobId>/cancel", methods=["POST"])
def cancel_batch(id, batchJobId):
    require_role({"BatchScheduler"})
    _customer_or_404(id)
    batch = _batch_or_404(id, batchJobId)
    if batch["status"] not in {"INTAKE", "RELEASED"}:
        raise errors.invalid_state("batch not INTAKE or RELEASED")

    now = now_iso()
    if batch["status"] == "RELEASED":
        # Tank cascade RESERVED -> AVAILABLE; cleaning_state and last_product_ghs unchanged
        tank = db.tanks.get(batch["tank_id"])
        if tank is not None and tank.get("occupied_by_batch_id") == batch["id"]:
            tank["operational_state"] = "AVAILABLE"
            tank["occupied_by_batch_id"] = None
            tank["version"] += 1
            tank["updated_at"] = now

    # COMMITTED charges -> RELEASED
    affected_lots = set()
    for ch in db.batch_charges.values():
        if ch["batch_job_id"] == batch["id"] and ch["status"] == "COMMITTED":
            ch["status"] = "RELEASED"
            ch["version"] += 1
            ch["updated_at"] = now
            affected_lots.add(ch["raw_material_lot_id"])
    for lid in affected_lots:
        reconcile_lot_quantities(lid)
        lot = db.raw_material_lots.get(lid)
        if lot is not None:
            lot["version"] += 1
            lot["updated_at"] = now

    batch["status"] = "CANCELLED"
    batch["version"] += 1
    batch["updated_at"] = now
    return success_object(serialize_batch_job(batch))


# ---------------- Batch charges ----------------

@bp.route("/toll-operations/customers/<id>/batch-jobs/<batchJobId>/batch-charges", methods=["POST"])
def create_batch_charge(id, batchJobId):
    require_role({"TankOperator"})
    _customer_or_404(id)
    batch = _batch_or_404(id, batchJobId)
    body = request.get_json(silent=True) or {}
    lot_id = body.get("raw_material_lot_id")
    if not lot_id:
        raise errors.invalid_request("raw_material_lot_id required")
    charge_order = to_int(body.get("charge_order"), "charge_order")
    charged_qty_kg = to_decimal(body.get("charged_qty_kg"), "charged_qty_kg")
    if charged_qty_kg <= 0:
        raise errors.invalid_request("charged_qty_kg must be > 0")

    lot = db.raw_material_lots.get(lot_id)
    if lot is None:
        raise errors.not_found("raw material lot not found")

    # Lot availability check
    avail = Decimal(str(lot["quantity_kg_available"]))
    if charged_qty_kg > avail:
        raise errors.ApiError(errors.ERR_INSUFFICIENT_LOT_QUANTITY, 422, "charged_qty_kg > available")

    now = now_iso()
    cid = new_id()
    charge = {
        "id": cid,
        "batch_job_id": batch["id"],
        "raw_material_lot_id": lot_id,
        "charge_order": charge_order,
        "charged_qty_kg": as_float_3dp(charged_qty_kg),
        "status": "COMMITTED",
        "version": 1,
        "created_at": now,
        "updated_at": now,
    }
    db.batch_charges[cid] = charge
    reconcile_lot_quantities(lot_id)
    lot["version"] += 1
    lot["updated_at"] = now
    batch["version"] += 1
    batch["updated_at"] = now
    return success_object(serialize_batch_charge(charge), status=201)


@bp.route("/toll-operations/customers/<id>/batch-jobs/<batchJobId>/batch-charges", methods=["GET"])
def list_batch_charges(id, batchJobId):
    require_role({"Any"})
    _customer_or_404(id)
    _batch_or_404(id, batchJobId)
    limit, offset = pagination_params()
    rows = [c for c in db.batch_charges.values() if c["batch_job_id"] == batchJobId]
    rows = sort_by_created_at(rows)
    slice_, total = paginate(rows, limit, offset)
    return success_list([serialize_batch_charge(c) for c in slice_], limit, offset, total)


@bp.route("/toll-operations/customers/<id>/batch-jobs/<batchJobId>/batch-charges/<chargeId>", methods=["GET"])
def get_batch_charge(id, batchJobId, chargeId):
    require_role({"Any"})
    _customer_or_404(id)
    _batch_or_404(id, batchJobId)
    c = _charge_or_404(batchJobId, chargeId)
    return success_object(serialize_batch_charge(c))
