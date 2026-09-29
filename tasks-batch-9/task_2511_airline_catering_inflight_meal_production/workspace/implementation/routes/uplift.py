"""Uplift dispositions, bonded waste manifests and their reads."""

from flask import Blueprint

import db
import validate
from errors import fail
from middleware import COMPLIANCE_OFFICER, authenticate
from routes.helpers import created, guard_scope, one, resolve, simple_list
from services import calc

bp = Blueprint("uplift", __name__)

UPLIFT_STATUSES = ["DRAFT", "DISPOSITIONED", "CLOSED"]
WASTE_STATUSES = ["DRAFT", "SEALED", "DISPOSED", "REJECTED"]
DISPOSAL_METHODS = ["INCINERATION", "RENDERING", "LANDFILL"]
REGIMES = ["BONDED", "DOMESTIC"]


def _airline_of_record(record):
    flight = db.get("flights", record["flight_id"])
    return calc.airline_of_flight(flight) if flight else None


# ---------------------------------------------------------------------------
# dispositions — the GROSS_UPLIFTED -> NET_CONSUMED switch


@bp.route("/uplift-records/<record_id>/dispositions", methods=["POST"])
def record_dispositions(record_id):
    authenticate(COMPLIANCE_OFFICER)
    data = validate.body([
        ("dispositions", {
            "type": "array", "required": True, "min_items": 1,
            "item": {"type": "object", "fields": [
                ("meal_specification_id", {"type": "id", "required": True}),
                ("reuse_units", {"type": "int", "required": True, "min": 0}),
                ("donate_units", {"type": "int", "required": True, "min": 0}),
                ("destroy_units", {"type": "int", "required": True, "min": 0}),
            ]},
        }),
    ])
    record = resolve("uplift_records", record_id)
    entries = data["dispositions"]
    for entry in entries:
        resolve("meal_specifications", entry["meal_specification_id"])

    by_spec = {}
    for entry in entries:
        spec_id = entry["meal_specification_id"]
        if spec_id in by_spec:
            fail("ERR_INVALID_REQUEST",
                 "dispositions carries more than one entry for a specification.")
        by_spec[spec_id] = entry
    line_ids = [line["meal_specification_id"] for line in record["lines"]]
    if sorted(by_spec) != sorted(line_ids):
        fail("ERR_INVALID_REQUEST",
             "dispositions must carry exactly one entry per uplift line.")

    # band 70
    if record["status"] != "DRAFT":
        fail("ERR_INVALID_RESOURCE_STATE")

    # band 85 — bonded waste may be neither re-used nor donated
    airline = _airline_of_record(record)
    if airline is not None and airline["waste_regime"] == "BONDED":
        for entry in entries:
            if entry["reuse_units"] != 0 or entry["donate_units"] != 0:
                fail("ERR_BONDED_REUSE_FORBIDDEN")

    # band 100 — per-line conservation
    for line in record["lines"]:
        entry = by_spec[line["meal_specification_id"]]
        total = entry["reuse_units"] + entry["donate_units"] + entry["destroy_units"]
        if total != line["returned_units"]:
            fail("ERR_DISPOSITION_UNITS_MISMATCH")

    credit_basis = 0
    for line in record["lines"]:
        entry = by_spec[line["meal_specification_id"]]
        line["reuse_units"] = entry["reuse_units"]
        line["donate_units"] = entry["donate_units"]
        line["destroy_units"] = entry["destroy_units"]
        credit_basis += entry["reuse_units"] + entry["donate_units"]

    gross = record["gross_cost_cents"]
    rate = calc.weighted_rate_cents(gross, record["uplifted_units"])
    recovery_pct = airline["unused_recovery_rate_pct"] if airline else 0
    credit = calc.recovery_credit_cents(credit_basis, rate, recovery_pct)
    net = gross - credit
    handling = calc.handling_fee_cents(net)
    late = calc.late_penalty_cents(record["flight_id"])

    record["net_cost_cents"] = net
    record["handling_fee_cents"] = handling
    record["late_penalty_cents"] = late
    record["billing_total_cents"] = net + handling + late
    record["status"] = "DISPOSITIONED"
    db.touch(record)

    destroyed_specs = {
        line["meal_specification_id"] for line in record["lines"]
        if line["destroy_units"] >= 1
    }
    for batch in calc.flight_batches(record["flight_id"]):
        if (batch["production_status"] == "RELEASED"
                and batch["meal_specification_id"] in destroyed_specs):
            batch["production_status"] = "DISPOSED"
            db.touch(batch)
    return one("uplift_records", record)


@bp.route("/uplift-records", methods=["GET"])
def list_records():
    authenticate()
    return simple_list("uplift_records", {
        "flight_id": {"type": "string"},
        "status": {"type": "enum", "values": UPLIFT_STATUSES},
    })


@bp.route("/uplift-records/<record_id>", methods=["GET"])
def read_record(record_id):
    authenticate()
    record = resolve("uplift_records", record_id)
    guard_scope("uplift_records", record)
    return one("uplift_records", record)


# ---------------------------------------------------------------------------
# waste manifests


def _seal_taken(seal_number, manifest_id=None):
    for cart in db.rows("carts"):
        if cart["seal_number"] == seal_number:
            return True
    for waste in db.rows("waste_manifests"):
        if waste["id"] == manifest_id:
            continue
        if waste["status"] != "REJECTED" and waste["seal_number"] == seal_number:
            return True
    return False


@bp.route("/waste-manifests", methods=["POST"])
def create_waste_manifest():
    authenticate(COMPLIANCE_OFFICER)
    data = validate.body([
        ("uplift_record_id", {"type": "id", "required": True}),
        ("disposal_method", {"type": "enum", "required": True, "values": DISPOSAL_METHODS}),
        ("seal_number", {"type": "string", "required": True, "non_empty": True}),
    ])
    record = resolve("uplift_records", data["uplift_record_id"])

    # band 70
    if record["status"] != "DISPOSITIONED":
        fail("ERR_INVALID_RESOURCE_STATE")

    # band 85 — the regime constrains the disposal route
    airline = _airline_of_record(record)
    regime = airline["waste_regime"] if airline else "DOMESTIC"
    if data["disposal_method"] not in calc.ALLOWED_DISPOSAL[regime]:
        fail("ERR_BONDED_WASTE_DISPOSAL_INVALID")

    # band 100 — the customs seal is unique across carts and live manifests
    if _seal_taken(data["seal_number"]):
        fail("ERR_SEAL_NUMBER_DUPLICATE")

    manifest = db.insert("waste_manifests", {
        "uplift_record_id": record["id"],
        "regime": regime,
        "disposal_method": data["disposal_method"],
        "seal_number": data["seal_number"],
        "sealed_weight_grams": calc.waste_mass_grams(record),
        "status": "DRAFT",
        "rejection_reason": None,
    })

    for cart in calc.flight_carts(record["flight_id"]):
        if cart["build_status"] != "LOADED":
            continue
        cart["build_status"] = "RETURNED"
        if cart["seal_status"] in ("SEALED", "RESEALED"):
            cart["seal_status"] = "BROKEN"
            cart["sealed_by_user_id"] = None
        db.touch(cart)
    return created("waste_manifests", manifest)


@bp.route("/waste-manifests/<manifest_id>/transitions", methods=["POST"])
def transition_waste_manifest(manifest_id):
    authenticate(COMPLIANCE_OFFICER)
    data = validate.body([
        ("action", {"type": "enum", "required": True, "values": ["SEAL", "DISPOSE", "REJECT"]}),
        ("rejection_reason", {"type": "string", "nullable": True}),
    ])
    action = data["action"]
    reason = data.get("rejection_reason")
    if action == "REJECT" and (reason is None or reason.strip() == ""):
        fail("ERR_INVALID_REQUEST", "rejection_reason is required for REJECT.")

    manifest = resolve("waste_manifests", manifest_id)
    record = db.get("uplift_records", manifest["uplift_record_id"])

    if action == "SEAL":
        if manifest["status"] != "DRAFT":
            fail("ERR_INVALID_RESOURCE_STATE")
        flight = db.get("flights", record["flight_id"]) if record else None
        if flight is None or flight["status"] != "RECONCILED":
            fail("ERR_INVALID_RESOURCE_STATE")
        manifest["status"] = "SEALED"
    elif action == "DISPOSE":
        if manifest["status"] != "SEALED":
            fail("ERR_INVALID_RESOURCE_STATE")
        manifest["status"] = "DISPOSED"
        if record is not None and record["status"] == "DISPOSITIONED":
            record["status"] = "CLOSED"
            db.touch(record)
    else:
        if manifest["status"] not in ("DRAFT", "SEALED"):
            fail("ERR_INVALID_RESOURCE_STATE")
        manifest["status"] = "REJECTED"
        manifest["rejection_reason"] = reason

    db.touch(manifest)
    return one("waste_manifests", manifest)


@bp.route("/waste-manifests", methods=["GET"])
def list_waste_manifests():
    authenticate()
    return simple_list("waste_manifests", {
        "uplift_record_id": {"type": "string"},
        "regime": {"type": "enum", "values": REGIMES},
        "disposal_method": {"type": "enum", "values": DISPOSAL_METHODS},
        "status": {"type": "enum", "values": WASTE_STATUSES},
    })


@bp.route("/waste-manifests/<manifest_id>", methods=["GET"])
def read_waste_manifest(manifest_id):
    authenticate()
    manifest = resolve("waste_manifests", manifest_id)
    guard_scope("waste_manifests", manifest)
    return one("waste_manifests", manifest)
