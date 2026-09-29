"""ProductionLot and JointIntegritySample endpoints (PRD 3.6)."""

from flask import Blueprint, g

import calc
import cascade
import lookup
import response
import serialize
import store
import validate
from auth import authorize
from errors import fail
from routes._common import paged
from store import db, mark_dirty, now

bp = Blueprint("production", __name__)

LOT_READERS = (
    "ProductionSupervisor",
    "TestLabTechnician",
    "ComplianceOfficer",
    "CertificationBody",
    "SafetyDirector",
)


@bp.post("/production-lots")
@authorize("ProductionSupervisor")
def create_production_lot():
    data = validate.body()

    product = None
    if validate.present(data, "product_id"):
        product = lookup.product(data["product_id"])
    revision = None
    if validate.present(data, "design_revision_id"):
        revision = lookup.design_revision(data["design_revision_id"])

    validate.req_id(data, "product_id")
    validate.req_id(data, "design_revision_id")
    lot_code = validate.req_str(data, "lot_code")
    planned_units = validate.req_int(data, "planned_units", minimum=1)
    extrusion_heat_number = validate.opt_str(data, "extrusion_heat_number")
    pultrusion_batch_id = validate.opt_str(data, "pultrusion_batch_id")

    # step 32
    if revision["product_id"] != product["id"]:
        fail("ERR_REVISION_PRODUCT_MISMATCH", "revision belongs to another product")

    # step 57
    for existing in db.production_lots.values():
        if existing["lot_code"] == lot_code:
            fail("ERR_DUPLICATE_KEY", "lot_code already exists: %s" % lot_code)

    lot = store.base_record()
    lot.update(
        {
            "product_id": product["id"],
            "design_revision_id": revision["id"],
            "lot_code": lot_code,
            "planned_units": planned_units,
            "extrusion_heat_number": extrusion_heat_number,
            "pultrusion_batch_id": pultrusion_batch_id,
            "produced_units": 0,
            "units_wip": 0,
            "units_quarantined": 0,
            "units_released": 0,
            "units_scrapped": 0,
            "status": "OPEN",
            "joint_sample_count": 0,
            "joint_fail_count": 0,
            "required_joint_sample_count": 0,
            "conformance_index": None,
            "released_at": None,
            "quarantine_reason_code": None,
            "disposition": None,
        }
    )
    db.production_lots[lot["id"]] = lot
    store.register_new(lot)
    return response.created(lot, serialize.production_lot)


@bp.get("/production-lots/<lot_id>")
@authorize(*LOT_READERS)
def get_production_lot(lot_id):
    lot = lookup.production_lot(lot_id)
    return response.obj(lot, serialize.production_lot)


@bp.get("/production-lots")
@authorize(*LOT_READERS)
def list_production_lots():
    spec = {
        "product_id": "product_id",
        "design_revision_id": "design_revision_id",
        "status": "status",
        "lot_code": "lot_code",
    }
    return paged(lookup.rows(db.production_lots), spec, serialize.production_lot)


@bp.post("/production-lots/<lot_id>/start-production")
@authorize("ProductionSupervisor")
def start_production(lot_id):
    lot = lookup.production_lot(lot_id)
    data = validate.body()
    produced_units = validate.req_int(data, "produced_units")

    # step 16
    if lot["status"] != "OPEN":
        fail("ERR_LOT_STATE_INVALID", "status must be OPEN to start production")

    revision = db.design_revisions[lot["design_revision_id"]]
    product = db.products[lot["product_id"]]

    # step 36
    if revision["status"] != "APPROVED" or revision["superseded_at"] is not None:
        fail("ERR_REVISION_NOT_APPROVED", "the pinned revision must be APPROVED and not superseded")

    # step 37
    if product["design_status"] != "DESIGN_FROZEN":
        fail("ERR_DESIGN_NOT_FROZEN", "design_status must be DESIGN_FROZEN")

    # step 42
    if product["material"] == "FIBERGLASS_PULTRUSION" and not lot["pultrusion_batch_id"]:
        fail("ERR_PROCESS_TRACEABILITY_MISSING", "pultrusion_batch_id is required")
    if product["material"] == "ALUMINUM_EXTRUSION" and not lot["extrusion_heat_number"]:
        fail("ERR_PROCESS_TRACEABILITY_MISSING", "extrusion_heat_number is required")

    # step 43
    if produced_units <= 0 or produced_units > lot["planned_units"]:
        fail("ERR_PRODUCED_UNITS_INVALID", "produced_units must be within 1..planned_units")

    lot["status"] = "IN_PROCESS"
    lot["produced_units"] = produced_units
    lot["units_wip"] = produced_units
    lot["required_joint_sample_count"] = calc.required_joint_sample_count(produced_units)
    mark_dirty(lot)
    return response.obj(lot, serialize.production_lot)


@bp.post("/production-lots/<lot_id>/joint-samples")
@authorize("TestLabTechnician", "ProductionSupervisor")
def create_joint_sample(lot_id):
    lot = lookup.production_lot(lot_id)
    data = validate.body()
    sample_seq = validate.req_int(data, "sample_seq", minimum=1)
    pull_force_lbf = validate.req_number(data, "pull_force_lbf", minimum=0, exclusive_min=True)

    # step 16
    if lot["status"] != "IN_PROCESS":
        fail("ERR_LOT_STATE_INVALID", "status must be IN_PROCESS to add joint samples")

    # step 57
    for existing in lookup.samples_of_lot(lot["id"]):
        if existing["sample_seq"] == sample_seq:
            fail("ERR_DUPLICATE_KEY", "sample_seq already exists on this lot")

    product = db.products[lot["product_id"]]
    required = product["required_pull_force_lbf"]
    sample = store.base_record(versioned=False)
    sample.update(
        {
            "production_lot_id": lot["id"],
            "sample_seq": sample_seq,
            "pull_force_lbf": pull_force_lbf,
            "required_pull_force_lbf": required,
            "margin_pct": calc.sample_margin_pct(pull_force_lbf, required),
            "result": "PASS" if pull_force_lbf >= required else "FAIL",
        }
    )
    db.joint_samples[sample["id"]] = sample
    store.register_new(sample)
    cascade.recompute_lot_samples(lot, product)
    return response.created(sample, serialize.joint_sample)


@bp.get("/production-lots/<lot_id>/joint-samples")
@authorize(
    "TestLabTechnician",
    "ProductionSupervisor",
    "ComplianceOfficer",
    "CertificationBody",
    "SafetyDirector",
)
def list_joint_samples(lot_id):
    lot = lookup.production_lot(lot_id)
    spec = {"result": "result"}
    return paged(lookup.samples_of_lot(lot["id"]), spec, serialize.joint_sample)


@bp.post("/production-lots/<lot_id>/release")
@authorize("ProductionSupervisor")
def release_production_lot(lot_id):
    lot = lookup.production_lot(lot_id)

    # step 16
    if lot["status"] != "IN_PROCESS":
        fail("ERR_LOT_STATE_INVALID", "status must be IN_PROCESS to release")
    # step 26
    if lot["joint_sample_count"] <= 0:
        fail("ERR_NO_JOINT_SAMPLES", "the lot has no joint integrity samples")
    # step 27
    if lot["joint_sample_count"] < lot["required_joint_sample_count"]:
        fail("ERR_JOINT_SAMPLE_COUNT_SHORT", "not enough joint integrity samples")
    # step 28
    if lot["joint_fail_count"] != 0:
        fail("ERR_JOINT_INTEGRITY_FAILURE", "a joint integrity sample failed")
    # step 29
    if lot["conformance_index"] is None or lot["conformance_index"] < calc.MIN_CONFORMANCE_INDEX:
        fail(
            "ERR_CONFORMANCE_BELOW_MINIMUM",
            "conformance_index must be at least %s" % calc.MIN_CONFORMANCE_INDEX,
        )

    lot["units_released"] = lot["units_released"] + lot["units_wip"]
    lot["units_wip"] = 0
    lot["status"] = "RELEASED"
    lot["released_at"] = now()
    mark_dirty(lot)

    product = db.products[lot["product_id"]]
    cascade.recompute_dhf_retention(product)
    return response.obj(lot, serialize.production_lot)


@bp.post("/production-lots/<lot_id>/quarantine")
@authorize("ProductionSupervisor", "ComplianceOfficer", "SafetyDirector")
def quarantine_production_lot(lot_id):
    lot = lookup.production_lot(lot_id)
    data = validate.body()
    reason_code = validate.req_enum(data, "reason_code", calc.QUARANTINE_REASONS)

    if lot["status"] not in ("IN_PROCESS", "RELEASED"):
        fail("ERR_LOT_STATE_INVALID", "status must be IN_PROCESS or RELEASED to quarantine")

    cascade.lot_quarantine(lot, reason_code)
    return response.obj(lot, serialize.production_lot)


@bp.post("/production-lots/<lot_id>/disposition")
@authorize("ProductionSupervisor", "SafetyDirector")
def disposition_production_lot(lot_id):
    lot = lookup.production_lot(lot_id)
    data = validate.body()
    disposition = validate.req_enum(data, "disposition", calc.DISPOSITIONS)

    # step 16
    if lot["status"] != "QUARANTINED":
        fail("ERR_LOT_STATE_INVALID", "status must be QUARANTINED to disposition")
    # step 25
    if disposition == "SCRAP" and g.role != "SafetyDirector":
        fail("ERR_SCRAP_REQUIRES_SAFETY_DIRECTOR", "only a SafetyDirector may scrap a lot")

    product = db.products[lot["product_id"]]

    if disposition == "RELEASE":
        # step 28 / 29
        if lot["joint_fail_count"] != 0:
            fail("ERR_JOINT_INTEGRITY_FAILURE", "a joint integrity sample failed")
        if (
            lot["conformance_index"] is None
            or lot["conformance_index"] < calc.MIN_CONFORMANCE_INDEX
        ):
            fail(
                "ERR_CONFORMANCE_BELOW_MINIMUM",
                "conformance_index must be at least %s" % calc.MIN_CONFORMANCE_INDEX,
            )
        lot["units_released"] = lot["units_released"] + lot["units_quarantined"]
        lot["units_quarantined"] = 0
        lot["status"] = "RELEASED"
        lot["disposition"] = "RELEASE"
        # PRD 3.6: RELEASE disposition clears quarantine_reason_code to null.
        lot["quarantine_reason_code"] = None
        mark_dirty(lot)
    else:
        lot["units_scrapped"] = lot["units_scrapped"] + lot["units_quarantined"]
        lot["units_quarantined"] = 0
        lot["status"] = "SCRAPPED"
        lot["disposition"] = "SCRAP"
        mark_dirty(lot)

    # PRD 3.6: both dispositions clear hold_flag to false on every consumer
    # registration of the lot and recompute the model's held_registration_count.
    for registration in lookup.registrations_of_lot(lot["id"]):
        if registration["hold_flag"]:
            registration["hold_flag"] = False
            mark_dirty(registration)
    cascade.recompute_held_registration_count(product)

    return response.obj(lot, serialize.production_lot)
