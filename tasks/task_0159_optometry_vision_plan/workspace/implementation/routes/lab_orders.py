"""LabOrder lifecycle: place, get, list, send-to-lab, dispense, remake, cancel."""
from flask import Blueprint, request, g

import clock
import errors
import helpers
import response
import serialize
import serialize as ser
from db import db, new_id, stamp_create, touch
from middleware import require_roles
from services import benefit, materials

bp = Blueprint("lab_orders", __name__)

FRAME_TIERS = {"STANDARD", "PREMIUM", "DESIGNER"}
REMAKE_WINDOW_DAYS = 90
MAX_REMAKES = 2
SURCHARGE_REMAKE_THRESHOLD = 2
REMAKE_SURCHARGE_CENTS = 2500


def _rx_dispensable(rx):
    """Effective status is ACTIVE and not expired."""
    return ser.effective_rx_status(rx) == "ACTIVE"


@bp.post("/lab-orders")
@require_roles("Optician")
def create_lab_order():
    body = helpers.get_json_body()
    prescription_id = helpers.require_str(body, "prescription_id")

    # body FK existence (priority 4)
    rx = db.prescriptions.get(prescription_id)
    if rx is None:
        raise errors.reference_not_found("prescription_id references no Prescription")

    eligibility_id = helpers.require_str(body, "eligibility_id", required=False)
    elig = None
    if eligibility_id is not None:
        elig = db.eligibilities.get(eligibility_id)
        if elig is None:
            raise errors.reference_not_found(
                "eligibility_id references no Eligibility")

    frame_charge = helpers.require_int(body, "frame_charge_cents", minimum=0)
    lens_charge = helpers.require_int(body, "lens_charge_cents", minimum=0)
    frame_tier = helpers.require_enum(body, "frame_brand_tier", FRAME_TIERS,
                                      required=False, default="STANDARD")

    is_benefit_draw = eligibility_id is not None
    expected_version = None
    if is_benefit_draw:
        # expected_eligibility_version required when eligibility_id is set (§2.10)
        expected_version = helpers.require_int(body, "expected_eligibility_version")

    # ---- business gates (PRD §3.5 ordering) ----
    # 1. prescription dispensability (priority 8)
    if not _rx_dispensable(rx):
        raise errors.prescription_not_dispensable(
            "Prescription is not ACTIVE/unexpired")

    if is_benefit_draw:
        patient = db.patients.get(rx["patient_id"])
        # 2. carrier matching (priority 10): patient plan_carrier must not be NONE
        if patient is None or patient["plan_carrier"] == "NONE":
            raise errors.carrier_mismatch(
                "Benefit draw requires a patient with a plan carrier")
        # 3. benefit-period currency (priority 11)
        if not benefit.is_in_period(elig, clock.current_date()):
            raise errors.benefit_period_closed("Eligibility is not in-period")
        # 4. stale-eligibility-version OCC (priority 13)
        if expected_version != elig["version"]:
            raise errors.stale_eligibility_version(
                "expected_eligibility_version does not match current version")
        # 5. benefit exhaustion (priority 14)
        if elig["status"] != "ACTIVE":
            raise errors.benefit_exhausted("Eligibility is not ACTIVE")
        materials_pool = benefit.pool_of_type(eligibility_id, "MATERIALS")
        if materials_pool is None or materials_pool["remaining_cents"] <= 0:
            raise errors.benefit_exhausted("Materials pool is exhausted")

    record = {
        "id": new_id(),
        "prescription_id": prescription_id,
        "eligibility_id": eligibility_id,
        "dispensing_optician_id": None,
        "expected_eligibility_version": expected_version,
        "frame_charge_cents": frame_charge,
        "lens_charge_cents": lens_charge,
        "frame_brand_tier": frame_tier,
        "materials_draw_cents": 0,
        "patient_materials_cost_cents": 0,
        "status": "PLACED",
        "remake_count": 0,
        "dispensed_at": None,
    }

    if is_benefit_draw:
        # available room at placement = pool.remaining_cents (own draw is 0)
        available = materials_pool["remaining_cents"]
        draw, patient_cost = materials.compute_draw(
            frame_charge, lens_charge, frame_tier, available)
        record["materials_draw_cents"] = draw
        record["patient_materials_cost_cents"] = patient_cost
        # commit draw to the pool
        materials_pool["consumed_cents"] += draw
        benefit.recompute_pool_remaining(materials_pool)
        touch(materials_pool)
        # bump eligibility version on a benefit draw
        touch(elig)
        # exhaustion bubble-up
        if materials_pool["remaining_cents"] == 0 and elig["status"] == "ACTIVE":
            elig["status"] = "EXHAUSTED"
    else:
        # self-pay: no draw, full retail is patient cost
        retail = frame_charge + lens_charge
        record["materials_draw_cents"] = 0
        record["patient_materials_cost_cents"] = retail

    stamp_create(record)
    db.lab_orders[record["id"]] = record
    return response.object_response(serialize.lab_order(record), 201)


@bp.get("/lab-orders/<lab_order_id>")
@require_roles("FrontDesk", "Optician", "Biller")
def get_lab_order(lab_order_id):
    record = db.lab_orders.get(lab_order_id)
    if record is None:
        raise errors.not_found("LabOrder not found")
    return response.object_response(serialize.lab_order(record), 200)


@bp.get("/lab-orders")
@require_roles("FrontDesk", "Optician", "Biller")
def list_lab_orders():
    limit, offset = helpers.parse_pagination()
    prescription_id = request.args.get("prescription_id")
    eligibility_id = request.args.get("eligibility_id")
    dispensing_optician_id = request.args.get("dispensing_optician_id")
    status = request.args.get("status")
    records = list(db.lab_orders.values())
    if prescription_id is not None:
        records = [r for r in records if r["prescription_id"] == prescription_id]
    if eligibility_id is not None:
        records = [r for r in records if r.get("eligibility_id") == eligibility_id]
    if dispensing_optician_id is not None:
        records = [r for r in records
                   if r.get("dispensing_optician_id") == dispensing_optician_id]
    if status is not None:
        records = [r for r in records if r["status"] == status]
    page, total = helpers.paginate(records, limit, offset)
    return response.array_response(
        [serialize.lab_order(r) for r in page], limit, offset, total, 200)


@bp.post("/lab-orders/<lab_order_id>/send-to-lab")
@require_roles("Optician")
def send_to_lab(lab_order_id):
    record = db.lab_orders.get(lab_order_id)
    if record is None:
        raise errors.not_found("LabOrder not found")
    if record["status"] not in ("PLACED", "REMAKE_REQUESTED"):
        raise errors.invalid_state(
            "LabOrder must be PLACED or REMAKE_REQUESTED to send to lab")

    if record["status"] == "REMAKE_REQUESTED":
        # compute prospective new count, derive surcharge, then commit count
        new_count = record["remake_count"] + 1
        if new_count >= SURCHARGE_REMAKE_THRESHOLD:
            record["patient_materials_cost_cents"] += REMAKE_SURCHARGE_CENTS
        record["remake_count"] = new_count

    record["status"] = "IN_LAB"
    touch(record)
    return response.object_response(serialize.lab_order(record), 200)


@bp.post("/lab-orders/<lab_order_id>/dispense")
@require_roles("Optician")
def dispense(lab_order_id):
    record = db.lab_orders.get(lab_order_id)
    if record is None:
        raise errors.not_found("LabOrder not found")

    body = helpers.get_json_body()
    dispensing_optician_id = helpers.require_str(body, "dispensing_optician_id")
    optician = db.providers.get(dispensing_optician_id)
    if optician is None:
        raise errors.reference_not_found(
            "dispensing_optician_id references no Provider")

    # state legality (priority 6)
    if record["status"] != "IN_LAB":
        raise errors.invalid_state("LabOrder must be IN_LAB to dispense")

    # provider role check (priority 7)
    if optician["role"] != "OPTICIAN":
        raise errors.wrong_provider_role(
            "Dispensing provider must have role OPTICIAN")

    # prescription dispensability (priority 8)
    rx = db.prescriptions.get(record["prescription_id"])
    if rx is None or not _rx_dispensable(rx):
        raise errors.prescription_not_dispensable(
            "Prescription is not ACTIVE/unexpired")

    # recompute materials draw as final if benefit-drawing
    if record.get("eligibility_id") is not None:
        elig = db.eligibilities.get(record["eligibility_id"])
        materials_pool = benefit.pool_of_type(record["eligibility_id"], "MATERIALS")
        if materials_pool is not None:
            old_draw = record["materials_draw_cents"]
            # available = pool.remaining + this order's own committed draw
            available = materials_pool["remaining_cents"] + old_draw
            new_draw, patient_cost = materials.compute_draw(
                record["frame_charge_cents"], record["lens_charge_cents"],
                record["frame_brand_tier"], available)
            delta = new_draw - old_draw
            if delta != 0:
                materials_pool["consumed_cents"] += delta
                benefit.recompute_pool_remaining(materials_pool)
                touch(materials_pool)
                record["materials_draw_cents"] = new_draw
                record["patient_materials_cost_cents"] = patient_cost
                # exhaustion / restoration bubble-up on the eligibility
                if elig is not None:
                    if materials_pool["remaining_cents"] == 0 and elig["status"] == "ACTIVE":
                        elig["status"] = "EXHAUSTED"
                        touch(elig)
                    elif materials_pool["remaining_cents"] > 0 and elig["status"] == "EXHAUSTED":
                        elig["status"] = "ACTIVE"
                        touch(elig)

    record["status"] = "DISPENSED"
    record["dispensed_at"] = clock.now_iso()
    record["dispensing_optician_id"] = dispensing_optician_id
    touch(record)
    return response.object_response(serialize.lab_order(record), 200)


@bp.post("/lab-orders/<lab_order_id>/request-remake")
@require_roles("Optician")
def request_remake(lab_order_id):
    record = db.lab_orders.get(lab_order_id)
    if record is None:
        raise errors.not_found("LabOrder not found")

    helpers.get_json_body()  # optional reason; tolerate body

    if record["status"] != "DISPENSED":
        raise errors.invalid_state("LabOrder must be DISPENSED to request remake")

    # remake window: clock now <= dispensed_at + 90 days, remake_count < MAX
    dispensed_at = clock.parse_iso8601(record["dispensed_at"])
    deadline = dispensed_at + _timedelta_days(REMAKE_WINDOW_DAYS)
    if clock.now() > deadline:
        raise errors.remake_window_closed("Remake window has closed")
    if record["remake_count"] >= MAX_REMAKES:
        raise errors.remake_window_closed("Maximum remakes reached")

    record["status"] = "REMAKE_REQUESTED"
    touch(record)
    return response.object_response(serialize.lab_order(record), 200)


def _timedelta_days(days):
    from datetime import timedelta
    return timedelta(days=days)


@bp.post("/lab-orders/<lab_order_id>/cancel")
@require_roles("Optician")
def cancel(lab_order_id):
    record = db.lab_orders.get(lab_order_id)
    if record is None:
        raise errors.not_found("LabOrder not found")
    if record["status"] not in ("PLACED", "IN_LAB"):
        raise errors.invalid_state("LabOrder must be PLACED or IN_LAB to cancel")

    # release materials draw back to the pool
    eligibility_id = record.get("eligibility_id")
    if eligibility_id is not None and record["materials_draw_cents"] > 0:
        elig = db.eligibilities.get(eligibility_id)
        materials_pool = benefit.pool_of_type(eligibility_id, "MATERIALS")
        if materials_pool is not None:
            materials_pool["consumed_cents"] -= record["materials_draw_cents"]
            if materials_pool["consumed_cents"] < 0:
                materials_pool["consumed_cents"] = 0
            benefit.recompute_pool_remaining(materials_pool)
            touch(materials_pool)
            if elig is not None:
                # bubble-up: EXHAUSTED -> ACTIVE if room restored
                if (elig["status"] == "EXHAUSTED"
                        and materials_pool["remaining_cents"] > 0):
                    elig["status"] = "ACTIVE"
                touch(elig)
    elif eligibility_id is not None:
        # benefit order with zero draw: still bump eligibility version per spec
        elig = db.eligibilities.get(eligibility_id)
        if elig is not None:
            touch(elig)

    record["status"] = "CANCELLED"
    touch(record)
    return response.object_response(serialize.lab_order(record), 200)
