"""Remake and warranty cases, and the four-hop remake chain (PRD 3.8)."""

from datetime import timedelta

from flask import Blueprint, request

import calc
import serializers as S
import services
from auth import require_roles
from envelope import created, listing, ok
from errors import ApiError
from store import db, now, sorted_rows, stamp_common, touch
from validate import F, json_body, validate_body

bp = Blueprint("remakes", __name__)

OPEN_CASE_STATUSES = ("SUBMITTED", "ADJUDICATED")
REMAKE_JOB_STATES = ("EDGED", "PASSED", "RELEASED", "REWORK_QUEUED")


def _warranty_covered(job, warranty_claim):
    if not warranty_claim:
        return False
    released = job.get("released_at")
    if released is None:
        return True
    return now() <= released + timedelta(days=calc.WARRANTY_DAYS)


@bp.post("/remake-cases")
def create_remake_case():
    body = json_body()
    data = validate_body(
        body,
        [
            F("lab_job_id", "string"),
            F("defect_codes", "array", item_kind="string",
              item_enum=calc.REMAKE_DEFECT_CODES, min_items=1),
            F("warranty_claim", "bool"),
            F("quality_inspection_id", "string", required=False),
        ],
    )
    job = services.get_or_404(db.lab_jobs, data["lab_job_id"], "ERR_LAB_JOB_NOT_FOUND")
    inspection = None
    if data["quality_inspection_id"] is not None:
        inspection = services.get_or_404(
            db.quality_inspections, data["quality_inspection_id"], "ERR_QUALITY_INSPECTION_NOT_FOUND"
        )
    require_roles("StoreOptician")

    order = db.rx_orders.get(job["rx_order_id"])
    if order is None or order["fulfillment_status"] not in ("IN_LAB", "LAB_COMPLETE"):
        raise ApiError("ERR_ORDER_STATE_INVALID")

    for case in db.remake_cases.values():
        if case["lab_job_id"] == job["id"] and case["status"] in OPEN_CASE_STATUSES:
            raise ApiError("ERR_OPEN_REMAKE_CASE_EXISTS")

    if job["status"] not in REMAKE_JOB_STATES:
        raise ApiError("ERR_LAB_JOB_STATE_INVALID")

    if order["remake_count"] >= calc.MAX_REMAKES_PER_ORDER:
        raise ApiError("ERR_REMAKE_LIMIT_REACHED")

    if inspection is not None and inspection["lab_job_id"] != job["id"]:
        raise ApiError("ERR_INSPECTION_JOB_MISMATCH")

    # --- HOP 1: the case is opened and the job is scrapped -----------------
    covered = _warranty_covered(job, bool(data["warranty_claim"]))
    row = stamp_common(
        {
            "lab_job_id": job["id"],
            "quality_inspection_id": data["quality_inspection_id"],
            "defect_codes": list(data["defect_codes"]),
            "warranty_claim": bool(data["warranty_claim"]),
            "warranty_covered": covered,
            "responsibility": "UNASSIGNED",
            "adjudication_method": None,
            "lab_share_pct": None,
            "lab_chargeback_cents": 0,
            "status": "SUBMITTED",
        }
    )
    db.remake_cases[row["id"]] = row

    services.release_job_allocation(job, "return")
    job["status"] = "SCRAPPED"
    job["scrap_reason"] = "REMAKE_REQUESTED"
    touch(job)

    # --- HOP 2: the order reopens for a remake -----------------------------
    order["fulfillment_status"] = "REMAKE_PENDING"
    order["remake_count"] += 1
    touch(order)

    # --- HOP 3: the warranty writeoff --------------------------------------
    if covered:
        base = order["patient_portion_cents"] + order["lab_writeoff_cents"]
        pct = calc.REMAKE_WRITEOFF_PCT.get(order["remake_count"])
        if pct is not None:
            previous = order["lab_writeoff_cents"]
            writeoff = calc.cents(calc.D(base) * pct)
            order["lab_writeoff_cents"] = writeoff
            order["patient_portion_cents"] = base - writeoff
            touch(order)
            movement = writeoff - previous
            if movement != 0:
                services.append_entry(order["id"], "LAB_WRITEOFF", -movement,
                                      "Remake warranty writeoff")

        # --- HOP 4: the patient has overpaid the reduced portion -----------
        if (order["patient_paid_cents"] > order["patient_portion_cents"]
                and order["billing_status"] == "PATIENT_SETTLED"):
            order["billing_status"] = "REFUND_DUE"
            touch(order)

    return created(S.remake_case(row))


@bp.get("/remake-cases/<rid>")
def get_remake_case(rid):
    row = services.get_or_404(db.remake_cases, rid, "ERR_REMAKE_CASE_NOT_FOUND")
    require_roles("StoreOptician", "LabTechnician", "QualityInspector", "LabManager")
    return ok(S.remake_case(row))


@bp.get("/remake-cases")
def list_remake_cases():
    require_roles("StoreOptician", "LabTechnician", "QualityInspector", "LabManager")
    rows = sorted_rows(db.remake_cases)
    for arg in ("lab_job_id", "quality_inspection_id", "status", "responsibility"):
        value = request.args.get(arg)
        if value:
            rows = [r for r in rows if r.get(arg) == value]
    return listing(rows, S.remake_case)


@bp.post("/remake-cases/<rid>/adjudicate")
def adjudicate_remake_case(rid):
    body = json_body()
    data = validate_body(
        body,
        [F("adjudication_method", "enum", enum=("PROCESS_AUDIT", "TOLERANCE_DELTA"))],
    )
    case = services.get_or_404(db.remake_cases, rid, "ERR_REMAKE_CASE_NOT_FOUND")
    user_id, _role = require_roles("LabManager")

    if case["status"] != "SUBMITTED":
        raise ApiError("ERR_REMAKE_STATE_INVALID")

    method = data["adjudication_method"]
    inspection = None
    if case["quality_inspection_id"] is not None:
        inspection = db.quality_inspections.get(case["quality_inspection_id"])
    if method == "TOLERANCE_DELTA" and inspection is None:
        raise ApiError("ERR_INSPECTION_REQUIRED_FOR_METHOD")

    if inspection is not None and inspection["inspector_user_id"] == user_id:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES")

    if method == "PROCESS_AUDIT":
        share = calc.process_audit_share(case["defect_codes"])
    else:
        standard = db.tolerance_standards.get(inspection["tolerance_standard_id"])
        share = calc.tolerance_delta_share(inspection, standard)

    job = db.lab_jobs.get(case["lab_job_id"])
    order = db.rx_orders.get(job["rx_order_id"]) if job is not None else None
    design = services.order_design(order) if order is not None else None
    basis = calc.job_cost_basis_cents(design, order, job["route"])

    case["adjudication_method"] = method
    case["lab_share_pct"] = share
    case["responsibility"] = calc.responsibility_for(share)
    case["lab_chargeback_cents"] = calc.cents(calc.D(basis) * calc.D(share) / calc.D(100))
    case["status"] = "ADJUDICATED"
    touch(case)
    return ok(S.remake_case(case))


@bp.post("/remake-cases/<rid>/close")
def close_remake_case(rid):
    case = services.get_or_404(db.remake_cases, rid, "ERR_REMAKE_CASE_NOT_FOUND")
    require_roles("LabManager")
    if case["status"] != "ADJUDICATED":
        raise ApiError("ERR_REMAKE_STATE_INVALID")
    job = db.lab_jobs.get(case["lab_job_id"])
    order = db.rx_orders.get(job["rx_order_id"]) if job is not None else None
    if order is None or order["fulfillment_status"] not in ("LAB_COMPLETE", "DISPENSED"):
        raise ApiError("ERR_REMAKE_NOT_DELIVERABLE")
    case["status"] = "CLOSED"
    touch(case)
    return ok(S.remake_case(case))
