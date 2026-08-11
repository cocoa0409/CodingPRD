"""Tanker receipts, lab tests, component assays (PRD 3.2-3.5)."""
from flask import Blueprint, request

from db import STORE, base_record, now, touch
from errors import (
    ApiError,
    ERR_ANTIBIOTIC_POSITIVE,
    ERR_BATCH_ALREADY_CODED,
    ERR_HAULER_LICENSE_EXPIRED,
    ERR_LAB_TESTS_PENDING,
    ERR_NO_REJECTION_CRITERION,
    ERR_PERMIT_NOT_ACTIVE,
    ERR_PRODUCER_SUSPENDED,
    ERR_RECEIPT_NOT_IN_QUARANTINE,
    ERR_SCC_EXCEEDED,
    ERR_SOD_VIOLATION,
    ERR_STALE_PRODUCER_VERSION,
    ERR_TEMPERATURE_EXCEEDED,
    bad_input,
    invalid_state,
    not_found,
)
from helpers import (
    body,
    req_dt,
    req_enum,
    req_num,
    req_str,
    sort_and_paginate,
)
from middleware import require_roles
from response import success_list, success_object
from services import (
    SCC_LIMIT,
    TEMP_LIMIT_F,
    TEST_TYPES,
    apply_rejection_cascade,
    component_lbs,
    latest_permit,
    quantize_pct,
    recompute_draft_settlements,
    ser_assay,
    ser_lab_test,
    ser_receipt,
)

bp = Blueprint("receipts", __name__)

_QA = "QualityAssuranceManager"
_LT = "LabTechnician"
_PC = "PlantController"
_SI = "StateInspector"


def _get_receipt(rid):
    receipt = STORE["receipts"].get(rid)
    if receipt is None:
        raise not_found("TankerReceipt not found")
    return receipt


# ---------------------------------------------------------------------------
# Tanker receipts
# ---------------------------------------------------------------------------
@bp.route("/dairy/tanker-receipts", methods=["POST"])
def create_receipt():
    user_id = require_roles(_QA)
    data = body()
    producer_id = req_str(data, "producer_id")
    hauler_id = req_str(data, "hauler_id")
    arrived_at = req_dt(data, "arrived_at")
    gross = req_num(data, "gross_weight_lbs")
    tare = req_num(data, "tare_weight_lbs")
    temperature = req_num(data, "temperature_f")
    if not tare < gross:
        raise bad_input("tare_weight_lbs must be strictly less than gross_weight_lbs")
    if producer_id not in STORE["producers"]:
        raise not_found("Producer not found")
    if hauler_id not in STORE["haulers"]:
        raise not_found("Hauler not found")
    permit = latest_permit()
    if permit is not None and permit["status"] == "REVOKED":
        raise ApiError(
            ERR_PERMIT_NOT_ACTIVE,
            422,
            "Grade A permit has been revoked; tanker intake is blocked",
        )
    rec = base_record()
    rec.update({
        "producer_id": producer_id,
        "hauler_id": hauler_id,
        "arrived_at": arrived_at,
        "gross_weight_lbs": gross,
        "tare_weight_lbs": tare,
        "net_weight_lbs": gross - tare,
        "temperature_f": temperature,
        "antibiotic_result": "PENDING",
        "scc_cells_per_ml": None,
        "rejection_reason": None,
        "disposition": "QUARANTINE",
        "_created_by": user_id,
        "_rejected_at": None,
    })
    STORE["receipts"][rec["id"]] = rec
    return success_object(ser_receipt(rec), 201)


@bp.route("/dairy/tanker-receipts", methods=["GET"])
def list_receipts():
    require_roles(_QA, _PC, _SI)
    producer_id = request.args.get("producer_id")
    hauler_id = request.args.get("hauler_id")
    disposition = request.args.get("disposition")
    records = list(STORE["receipts"].values())
    if producer_id is not None:
        records = [r for r in records if r["producer_id"] == producer_id]
    if hauler_id is not None:
        records = [r for r in records if r["hauler_id"] == hauler_id]
    if disposition is not None:
        records = [r for r in records if r["disposition"] == disposition]
    page, pagination = sort_and_paginate(records)
    return success_list([ser_receipt(r) for r in page], pagination)


@bp.route("/dairy/tanker-receipts/<rid>", methods=["GET"])
def get_receipt(rid):
    require_roles(_QA, _PC, _SI, _LT)
    return success_object(ser_receipt(_get_receipt(rid)))


@bp.route("/dairy/tanker-receipts/<rid>/release", methods=["POST"])
def release_receipt(rid):
    require_roles(_QA)
    receipt = _get_receipt(rid)
    if receipt["disposition"] != "QUARANTINE":
        raise invalid_state("TankerReceipt is not in QUARANTINE")

    data = body()
    expected = data.get("expected_producer_version")
    if isinstance(expected, bool) or not isinstance(expected, int):
        raise bad_input("Field 'expected_producer_version' must be an integer")
    producer = STORE["producers"].get(receipt["producer_id"])
    if producer is None:
        raise not_found("Producer not found")
    if producer["version"] != expected:
        raise ApiError(
            ERR_STALE_PRODUCER_VERSION,
            412,
            "expected_producer_version does not match Producer.version",
        )

    tests = [t for t in STORE["lab_tests"].values()
             if t["tanker_receipt_id"] == rid and t["status"] == "COMPLETED"]
    if not any(t["test_type"] == "ANTIBIOTIC" for t in tests) \
            or not any(t["test_type"] == "SCC" for t in tests):
        raise ApiError(
            ERR_LAB_TESTS_PENDING, 422,
            "Required lab tests (ANTIBIOTIC, SCC) not all COMPLETED",
        )
    if receipt["antibiotic_result"] != "NEGATIVE":
        raise ApiError(ERR_ANTIBIOTIC_POSITIVE, 422,
                       "TankerReceipt.antibiotic_result is not NEGATIVE")
    scc = receipt["scc_cells_per_ml"]
    if scc is None or scc >= SCC_LIMIT:
        raise ApiError(ERR_SCC_EXCEEDED, 422,
                       "scc_cells_per_ml >= 750000 on release")
    if receipt["temperature_f"] > TEMP_LIMIT_F:
        raise ApiError(ERR_TEMPERATURE_EXCEEDED, 422,
                       "temperature_f > 45 on release")
    hauler = STORE["haulers"].get(receipt["hauler_id"])
    if hauler is None:
        raise not_found("Hauler not found")
    if hauler["status"] != "ACTIVE" \
            or hauler["license_expires_at"] <= receipt["arrived_at"]:
        raise ApiError(ERR_HAULER_LICENSE_EXPIRED, 422,
                       "Hauler license not valid at arrived_at")
    if producer["status"] != "ACTIVE":
        raise ApiError(ERR_PRODUCER_SUSPENDED, 422,
                       "Producer.status is not ACTIVE")
    permit = latest_permit()
    if permit is None or permit["status"] != "ACTIVE" \
            or permit["expires_at"] <= now():
        raise ApiError(ERR_PERMIT_NOT_ACTIVE, 422,
                       "Grade A permit is not ACTIVE or is expired")

    receipt["disposition"] = "RELEASED_FOR_PROCESSING"
    touch(receipt)
    touch(producer)  # release increments Producer.version by 1 (OCC pivot)
    recompute_draft_settlements()
    return success_object(ser_receipt(receipt), 200)


@bp.route("/dairy/tanker-receipts/<rid>/reject", methods=["POST"])
def reject_receipt(rid):
    require_roles(_QA)
    receipt = _get_receipt(rid)
    if receipt["disposition"] != "QUARANTINE":
        raise invalid_state("TankerReceipt is not in QUARANTINE")

    hauler = STORE["haulers"].get(receipt["hauler_id"])
    license_expired = hauler is not None \
        and hauler["license_expires_at"] <= receipt["arrived_at"]
    scc = receipt["scc_cells_per_ml"]
    criteria = []
    if receipt["antibiotic_result"] == "POSITIVE":
        criteria.append("ANTIBIOTIC_POSITIVE")
    if scc is not None and scc >= SCC_LIMIT:
        criteria.append("SCC_EXCEEDED")
    if receipt["temperature_f"] > TEMP_LIMIT_F:
        criteria.append("TEMPERATURE_EXCEEDED")
    if license_expired:
        criteria.append("HAULER_LICENSE_EXPIRED")
    if not criteria:
        raise ApiError(ERR_NO_REJECTION_CRITERION, 422,
                       "No rejection criterion is met")
    # Highest-priority matching criterion wins (list built in priority order).
    receipt["rejection_reason"] = criteria[0]
    receipt["disposition"] = "REJECTED"
    receipt["_rejected_at"] = now()
    touch(receipt)

    producer = STORE["producers"].get(receipt["producer_id"])
    if producer is not None:
        apply_rejection_cascade(producer)
        touch(producer)
    return success_object(ser_receipt(receipt), 200)


@bp.route("/dairy/tanker-receipts/<rid>/divert", methods=["POST"])
def divert_receipt(rid):
    require_roles(_QA)
    receipt = _get_receipt(rid)
    if receipt["disposition"] != "RELEASED_FOR_PROCESSING":
        raise invalid_state("TankerReceipt is not in RELEASED_FOR_PROCESSING")

    month = receipt["arrived_at"].strftime("%Y-%m")
    for batch in STORE["batches"].values():
        if batch["status"] != "CODED":
            continue
        run = STORE["runs"].get(batch["pasteurizer_run_id"])
        if run is not None \
                and run["scheduled_start_at"].strftime("%Y-%m") == month:
            raise ApiError(
                ERR_BATCH_ALREADY_CODED, 422,
                "A ProductBatch for the pool month has already been CODED",
            )

    receipt["disposition"] = "DIVERTED"
    touch(receipt)
    recompute_draft_settlements()
    return success_object(ser_receipt(receipt), 200)


# ---------------------------------------------------------------------------
# Lab tests (nested under receipt)
# ---------------------------------------------------------------------------
@bp.route("/dairy/tanker-receipts/<rid>/lab-tests", methods=["POST"])
def create_lab_test(rid):
    require_roles(_LT)
    _get_receipt(rid)
    data = body()
    test_type = req_enum(data, "test_type", TEST_TYPES)
    result_value = req_num(data, "result_value")
    lab_technician_id = req_str(data, "lab_technician_id")
    rec = base_record()
    rec.update({
        "tanker_receipt_id": rid,
        "test_type": test_type,
        "result_value": result_value,
        "result_disposition": None,
        "completed_at": None,
        "lab_technician_id": lab_technician_id,
        "status": "DRAFT",
    })
    STORE["lab_tests"][rec["id"]] = rec
    return success_object(ser_lab_test(rec), 201)


@bp.route("/dairy/tanker-receipts/<rid>/lab-tests", methods=["GET"])
def list_lab_tests(rid):
    require_roles(_QA, _LT, _PC, _SI)
    _get_receipt(rid)
    records = [t for t in STORE["lab_tests"].values()
               if t["tanker_receipt_id"] == rid]
    page, pagination = sort_and_paginate(records)
    return success_list([ser_lab_test(t) for t in page], pagination)


@bp.route("/dairy/tanker-receipts/<rid>/lab-tests/<test_id>/complete",
          methods=["POST"])
def complete_lab_test(rid, test_id):
    user_id = require_roles(_LT)
    receipt = _get_receipt(rid)
    test = STORE["lab_tests"].get(test_id)
    if test is None or test["tanker_receipt_id"] != rid:
        raise not_found("LabTest not found")
    if test["status"] != "DRAFT":
        raise invalid_state("LabTest is not in DRAFT")
    if receipt["disposition"] != "QUARANTINE":
        raise ApiError(ERR_RECEIPT_NOT_IN_QUARANTINE, 422,
                       "Parent TankerReceipt is no longer in QUARANTINE")
    creator = receipt.get("_created_by")
    if user_id == creator or test["lab_technician_id"] == creator:
        raise ApiError(
            ERR_SOD_VIOLATION, 403,
            "Completing technician must differ from the receipt's QA creator",
        )

    value = test["result_value"]
    if test["test_type"] == "ANTIBIOTIC":
        passed = value == 0
    elif test["test_type"] == "SCC":
        passed = value < SCC_LIMIT
    else:  # TEMPERATURE_RECHECK
        passed = value <= TEMP_LIMIT_F
    test["result_disposition"] = "PASS" if passed else "FAIL"
    test["completed_at"] = now()
    test["status"] = "COMPLETED"
    touch(test)

    if test["test_type"] == "ANTIBIOTIC":
        receipt["antibiotic_result"] = "NEGATIVE" if passed else "POSITIVE"
    elif test["test_type"] == "SCC":
        receipt["scc_cells_per_ml"] = (
            int(value) if float(value).is_integer() else value
        )
    else:
        receipt["temperature_f"] = value
    touch(receipt)
    return success_object(ser_lab_test(test), 200)


# ---------------------------------------------------------------------------
# Component assays (nested under receipt)
# ---------------------------------------------------------------------------
@bp.route("/dairy/tanker-receipts/<rid>/component-assays", methods=["POST"])
def create_assay(rid):
    require_roles(_LT)
    receipt = _get_receipt(rid)
    data = body()
    butterfat_pct = quantize_pct(req_num(data, "butterfat_pct"))
    protein_pct = quantize_pct(req_num(data, "protein_pct"))
    other_solids_pct = quantize_pct(req_num(data, "other_solids_pct"))
    if receipt["disposition"] != "RELEASED_FOR_PROCESSING":
        raise invalid_state(
            "ComponentAssay requires a RELEASED_FOR_PROCESSING receipt"
        )
    net = receipt["net_weight_lbs"]
    rec = base_record()
    rec.update({
        "tanker_receipt_id": rid,
        "butterfat_pct": butterfat_pct,
        "protein_pct": protein_pct,
        "other_solids_pct": other_solids_pct,
        "butterfat_lbs": component_lbs(net, butterfat_pct),
        "protein_lbs": component_lbs(net, protein_pct),
        "other_solids_lbs": component_lbs(net, other_solids_pct),
    })
    STORE["assays"][rec["id"]] = rec
    return success_object(ser_assay(rec), 201)


@bp.route("/dairy/tanker-receipts/<rid>/component-assays", methods=["GET"])
def list_assays(rid):
    require_roles(_LT, _PC, _QA)
    _get_receipt(rid)
    records = [a for a in STORE["assays"].values()
               if a["tanker_receipt_id"] == rid]
    page, pagination = sort_and_paginate(records)
    return success_list([ser_assay(a) for a in page], pagination)
