"""InspectionReport service."""

from flask import g

from common import (
    get_json_body,
    paginate,
    parse_pagination,
    require_field,
    sort_by_created_at,
    stamp_create,
    stamp_update,
    truncate_6dp,
)
from clock import clock
from db import db
from errors import (
    ERR_FORBIDDEN,
    ERR_INVALID_STATE,
    ERR_NOT_FOUND,
    ERR_SEGREGATION_VIOLATION,
    ERR_VALIDATION,
    ERR_VERSION_CONFLICT,
    raise_error,
)
from services.audit import record_audit
from services.planting_batch import get_batch_or_404, recompute_posture


VALID_TEST_ITEMS = {"PESTICIDE_RESIDUE", "HEAVY_METALS", "MICROORGANISMS"}
VALID_SAMPLING = {"RANDOM_5PCT", "FIXED_3KG", "FULL_LOT"}

MAX_PESTICIDE_MG_PER_KG = "0.50"
MAX_HEAVY_METAL_MG_PER_KG = "0.20"
MAX_MICRO_CFU_PER_G = 100000


def _serialize(r: dict) -> dict:
    return {
        "id": r["id"],
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
        "version": r["version"],
        "planting_batch_id": r["planting_batch_id"],
        "sampling_rule": r["sampling_rule"],
        "test_items": list(r["test_items"]),
        "pesticide_residue_mg_per_kg": r.get("pesticide_residue_mg_per_kg"),
        "heavy_metals_mg_per_kg": r.get("heavy_metals_mg_per_kg"),
        "microorganism_cfu_per_g": r.get("microorganism_cfu_per_g"),
        "status": r["status"],
        "result": r["result"],
        "issued_at": r.get("issued_at"),
        "inspector_id": r["inspector_id"],
    }


def get_report_or_404(rid):
    r = db.inspection_reports.get(rid)
    if r is None:
        raise_error(ERR_NOT_FOUND, f"inspection report {rid} not found")
    return r


def create_draft(batch_id):
    body = get_json_body()
    sampling_rule = require_field(body, "sampling_rule", str)
    test_items = body.get("test_items")
    if test_items is None:
        raise_error(ERR_VALIDATION, "missing required field test_items")
    if not isinstance(test_items, list) or not test_items:
        raise_error(ERR_VALIDATION, "test_items must be a non-empty array")
    if sampling_rule not in VALID_SAMPLING:
        raise_error(ERR_VALIDATION, "sampling_rule invalid")
    for ti in test_items:
        if ti not in VALID_TEST_ITEMS:
            raise_error(ERR_VALIDATION, f"unknown test_item: {ti}")
    # Required measurements per selected test_item
    if "PESTICIDE_RESIDUE" in test_items and body.get("pesticide_residue_mg_per_kg") is None:
        raise_error(ERR_VALIDATION, "pesticide_residue_mg_per_kg required when PESTICIDE_RESIDUE selected")
    if "HEAVY_METALS" in test_items and body.get("heavy_metals_mg_per_kg") is None:
        raise_error(ERR_VALIDATION, "heavy_metals_mg_per_kg required when HEAVY_METALS selected")
    if "MICROORGANISMS" in test_items and body.get("microorganism_cfu_per_g") is None:
        raise_error(ERR_VALIDATION, "microorganism_cfu_per_g required when MICROORGANISMS selected")

    # numeric parsing
    pr = body.get("pesticide_residue_mg_per_kg")
    hm = body.get("heavy_metals_mg_per_kg")
    micro = body.get("microorganism_cfu_per_g")
    if pr is not None:
        try:
            pr = float(pr)
        except Exception:
            raise_error(ERR_VALIDATION, "pesticide_residue_mg_per_kg must be numeric")
    if hm is not None:
        try:
            hm = float(hm)
        except Exception:
            raise_error(ERR_VALIDATION, "heavy_metals_mg_per_kg must be numeric")
    if micro is not None:
        try:
            micro_int = int(micro)
        except Exception:
            raise_error(ERR_VALIDATION, "microorganism_cfu_per_g must be integer")
        micro = micro_int

    with db.lock:
        batch = get_batch_or_404(batch_id)
        # State: requires at least one harvest (status in HARVESTED, INSPECTED_PASS,
        # INSPECTED_FAIL all imply a previous harvest existed)
        if batch["status"] not in {"HARVESTED", "INSPECTED_PASS", "INSPECTED_FAIL"}:
            raise_error(ERR_INVALID_STATE, f"cannot create draft on batch in {batch['status']}")

        report = {
            "id": db.new_id(),
            "planting_batch_id": batch_id,
            "sampling_rule": sampling_rule,
            "test_items": list(test_items),
            "pesticide_residue_mg_per_kg": pr,
            "heavy_metals_mg_per_kg": hm,
            "microorganism_cfu_per_g": micro,
            "status": "DRAFT",
            "result": "PENDING",
            "issued_at": None,
            "inspector_id": g.user_id,
        }
        stamp_create(report)
        db.inspection_reports[report["id"]] = report
        record_audit(
            "InspectionReport", report["id"], "CREATE", "DRAFT",
            before_state=None,
            change_summary={"batch_id": batch_id, "test_items": list(test_items)},
        )
    return _serialize(report)


def _evaluate_pass_fail(report):
    """Walk test_items in order and short-circuit on first failure."""
    failing_item = None
    for ti in report["test_items"]:
        if ti == "PESTICIDE_RESIDUE":
            v = truncate_6dp(report["pesticide_residue_mg_per_kg"])
            from decimal import Decimal
            if v > Decimal(MAX_PESTICIDE_MG_PER_KG):
                failing_item = ti
                break
        elif ti == "HEAVY_METALS":
            v = truncate_6dp(report["heavy_metals_mg_per_kg"])
            from decimal import Decimal
            if v > Decimal(MAX_HEAVY_METAL_MG_PER_KG):
                failing_item = ti
                break
        elif ti == "MICROORGANISMS":
            v = int(report["microorganism_cfu_per_g"])
            if v >= MAX_MICRO_CFU_PER_G:  # strict: == FAILS
                failing_item = ti
                break
    if failing_item is None:
        return "PASS", None
    return "FAIL", failing_item


def issue_report(report_id):
    body = get_json_body()
    with db.lock:
        report = get_report_or_404(report_id)
        if "version" in body and body["version"] is not None:
            if body["version"] != report["version"]:
                raise_error(ERR_VERSION_CONFLICT, "version mismatch")
        if report["status"] != "DRAFT":
            raise_error(ERR_INVALID_STATE, f"cannot issue report in {report['status']}")
        batch = db.planting_batches.get(report["planting_batch_id"])
        if batch is None:
            raise_error(ERR_NOT_FOUND, "parent batch missing")
        # Segregation of duties — PRD §3.5: "the inspector's X-User-ID equals
        # the batch's grower_id" is evaluated against the *issuer's* current
        # X-User-ID at issuance time, not against the persisted inspector_id.
        if g.user_id == batch["grower_id"]:
            raise_error(ERR_SEGREGATION_VIOLATION, "inspector X-User-ID cannot equal batch grower_id")
        if batch["status"] != "HARVESTED":
            raise_error(ERR_INVALID_STATE, f"batch not in HARVESTED (got {batch['status']})")

        result, failing_item = _evaluate_pass_fail(report)
        before_report_status = report["status"]
        report["status"] = "ISSUED"
        report["result"] = result
        report["issued_at"] = clock.now_iso()
        stamp_update(report)

        before_batch_status = batch["status"]
        if result == "PASS":
            batch["status"] = "INSPECTED_PASS"
        else:
            batch["status"] = "INSPECTED_FAIL"
            batch["posture"] = "BLOCKED"
            # PRD §3.5: A FAIL "rejects every LogisticsLeg of the batch
            # currently in PLANNED" — that rejection is enforced operationally
            # via posture=BLOCKED at depart time (PRD §3.6 "Departure is rejected
            # when posture is BLOCKED"). The legs themselves remain in PLANNED;
            # only the recall cascade (PRD §2.5) marks legs ABNORMAL.
        stamp_update(batch)

        record_audit(
            "InspectionReport", report["id"], "STATE_TRANSITION", "ISSUED",
            before_state=before_report_status,
            change_summary={"result": result, "failing_item": failing_item},
        )
        record_audit(
            "PlantingBatch", batch["id"], "STATE_TRANSITION", batch["status"],
            before_state=before_batch_status,
            change_summary={"trigger": "inspection_issue", "result": result,
                            "failing_item": failing_item},
        )
    return _serialize(report)


def revoke_report(report_id):
    body = get_json_body()
    with db.lock:
        report = get_report_or_404(report_id)
        if "version" in body and body["version"] is not None:
            if body["version"] != report["version"]:
                raise_error(ERR_VERSION_CONFLICT, "version mismatch")
        if report["status"] != "ISSUED":
            raise_error(ERR_INVALID_STATE, f"cannot revoke report in {report['status']}")
        batch = db.planting_batches.get(report["planting_batch_id"])
        if batch is None:
            raise_error(ERR_NOT_FOUND, "parent batch missing")
        if batch["status"] in {"DELIVERED", "DISPOSED"}:
            raise_error(ERR_INVALID_STATE, "cannot revoke when batch is terminal")
        before = report["status"]
        report["status"] = "REVOKED"
        stamp_update(report)
        record_audit(
            "InspectionReport", report["id"], "STATE_TRANSITION", "REVOKED",
            before_state=before,
            change_summary={"trigger": "revoke"},
        )
        # Cascade: revert batch to HARVESTED
        before_batch = batch["status"]
        batch["status"] = "HARVESTED"
        recompute_posture(batch)
        stamp_update(batch)
        record_audit(
            "PlantingBatch", batch["id"], "STATE_TRANSITION", "HARVESTED",
            before_state=before_batch,
            change_summary={"trigger": "inspection_revoke"},
        )
    return _serialize(report)
