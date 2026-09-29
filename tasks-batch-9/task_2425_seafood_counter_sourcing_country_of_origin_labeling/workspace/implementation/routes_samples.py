"""Verification samples: drawing, laboratory round trip and disputes (PRD 3.8)."""

import serializers
import services
from auth import supplier_scope
from common import base_record, touch
from envelope import obj_result
from errors import fail
from store import db
from validators import opt_id, req_number, req_str
from web import listing, route

READ_ROLES = ("ChainAdmin", "SeafoodManager", "ComplianceOfficer", "SupplierRep")


def resolve_sample(sample_id):
    """SupplierRep scope reaches a sample through its lot's supplier."""
    sample = db.samples.get(sample_id)
    if sample is not None:
        lot = db.lots.get(sample["lot_id"])
        if lot is not None:
            supplier_scope(lot["supplier_id"])
    else:
        fail("ERR_SAMPLE_NOT_FOUND")
    return sample


@route("/verification-samples", methods=["POST"], roles=("ComplianceOfficer",))
def draw_sample(body):
    raw_lot = opt_id(body, "lot_id")
    lot = None
    if raw_lot is not None:
        lot = db.lots.get(raw_lot)
        if lot is None:
            fail("ERR_LOT_NOT_FOUND")

    lot_id = req_str(body, "lot_id")
    sampled_weight_g = req_number(body, "sampled_weight_g", None, exclusive_min=0)

    if lot["intake_status"] not in ("CASED", "HELD"):
        fail("ERR_LOT_STATE_INVALID")
    counter = services.lot_counter(lot)
    if counter is not None and counter["posture"] == "SUSPENDED":
        fail("ERR_COUNTER_SUSPENDED")

    record = base_record("sample")
    record.update(
        {
            "lot_id": lot_id,
            "observed_species_id": None,
            "sampled_weight_g": sampled_weight_g,
            "cycle_index": counter["verification_cycle_index"] if counter else 0,
            "status": "DRAFT",
            "lab_reference": None,
            "dispute_reason": None,
            "retest_count": 0,
            "result_recorded_at": None,
        }
    )
    db.samples[record["id"]] = record

    if lot["label_status"] in ("UNVERIFIED", "RELABELED"):
        lot["label_status"] = "SAMPLED"
        touch(lot)
    return obj_result(serializers.sample, record, 201)


@route("/verification-samples/<sample_id>", methods=["GET"], roles=READ_ROLES)
def get_sample(body, sample_id):
    return obj_result(serializers.sample, resolve_sample(sample_id))


@route("/verification-samples", methods=["GET"], roles=READ_ROLES)
def list_samples(body):
    return listing(
        serializers.sample,
        list(db.samples.values()),
        string_fields=("lot_id", "observed_species_id", "status"),
    )


@route(
    "/verification-samples/<sample_id>/send-to-lab",
    methods=["POST"],
    roles=("ComplianceOfficer",),
)
def send_to_lab(body, sample_id):
    sample = db.samples.get(sample_id)
    if sample is None:
        fail("ERR_SAMPLE_NOT_FOUND")
    lab_reference = req_str(body, "lab_reference")

    if sample["status"] not in ("DRAFT", "DISPUTED"):
        fail("ERR_SAMPLE_STATE_INVALID")
    retest = sample["status"] == "DISPUTED"
    if retest and sample["retest_count"] >= 2:
        fail("ERR_RETEST_LIMIT_REACHED")

    sample["lab_reference"] = lab_reference
    sample["status"] = "IN_LAB"
    if retest:
        sample["retest_count"] += 1
    touch(sample)
    return obj_result(serializers.sample, sample)


@route(
    "/verification-samples/<sample_id>/result",
    methods=["POST"],
    roles=("ComplianceOfficer",),
)
def record_result(body, sample_id):
    sample = db.samples.get(sample_id)
    if sample is None:
        fail("ERR_SAMPLE_NOT_FOUND")

    raw_species = opt_id(body, "observed_species_id")
    if raw_species is not None and db.species.get(raw_species) is None:
        fail("ERR_SPECIES_NOT_FOUND")
    observed_species_id = req_str(body, "observed_species_id")

    if sample["status"] != "IN_LAB":
        fail("ERR_SAMPLE_STATE_INVALID")

    lot = db.lots.get(sample["lot_id"])
    services.apply_result(sample, lot, observed_species_id)
    return obj_result(serializers.sample, sample)


@route(
    "/verification-samples/<sample_id>/dispute",
    methods=["POST"],
    roles=("SupplierRep",),
)
def dispute_sample(body, sample_id):
    sample = resolve_sample(sample_id)
    dispute_reason = req_str(body, "dispute_reason")

    if sample["status"] != "MISMATCH":
        fail("ERR_SAMPLE_STATE_INVALID")
    if sample["retest_count"] >= 2:
        fail("ERR_RETEST_LIMIT_REACHED")

    sample["dispute_reason"] = dispute_reason
    sample["status"] = "DISPUTED"
    touch(sample)
    return obj_result(serializers.sample, sample)
