"""CoreUnit and CoreDepositInvoice endpoints."""

import math
import uuid
from datetime import timedelta

from flask import Blueprint, request

from db import db
from errors import (
    ApiError, ERR_INVOICE_NOT_FOUND, ERR_CORE_NOT_FOUND,
    ERR_INVOICE_NOT_OPEN, ERR_CORE_NOT_INSPECTABLE,
    ERR_INVOICE_NOT_DISPUTABLE, ERR_INVOICE_NOT_DISPUTED,
    ERR_DOCK_OVERLAP, ERR_ADJUSTMENT_OUT_OF_RANGE, ERR_PART_NOT_FOUND,
)
from middleware import require_role
from response import success
from services.calculations import (
    FINDING_ENUM, compute_grade, compute_final_credit,
)
from services.serializers import core_view, invoice_view
from validators import (
    get_json_body, require_fields, check_string, check_int, check_enum,
    invalid, parse_iso8601, parse_limit_offset, paginate,
)

bp = Blueprint("cores", __name__)

DOCK_BUFFER = timedelta(minutes=30)


def _get_invoice(iid):
    inv = db.core_deposit_invoices.get(iid)
    if inv is None:
        raise ApiError(
            ERR_INVOICE_NOT_FOUND, "CoreDepositInvoice id does not exist", 404
        )
    return inv


def _get_core(cid):
    c = db.core_units.get(cid)
    if c is None:
        raise ApiError(ERR_CORE_NOT_FOUND, "CoreUnit id does not exist", 404)
    return c


def _settle_from_inspection(core):
    """Run grading + settlement cascade for the core's current findings.
    Updates the core, its invoice, and (on SETTLED_FULL) the linked order."""
    deduction_score, grade = compute_grade(core["case_cracked"], core["findings"])
    core["deduction_score"] = deduction_score
    core["grade"] = grade

    inv = db.core_deposit_invoices[core["core_deposit_invoice_id"]]
    credit, forfeited, inv_status = compute_final_credit(
        inv["deposit_cents"], grade, core["days_late"]
    )
    inv["final_credit_cents"] = credit
    inv["forfeited_cents"] = forfeited
    inv["status"] = inv_status

    # PRD §3.6: when the grade is REJECTED or the core arrived more than 45
    # days late, the invoice is FORFEITED and the core's status records
    # REJECTED. Otherwise the core records GRADED.
    if grade == "REJECTED" or inv_status == "FORFEITED":
        core["status"] = "REJECTED"
    else:
        core["status"] = "GRADED"

    now = db.now()
    core["updated_at"] = now
    core["version"] += 1
    inv["updated_at"] = now
    inv["version"] += 1

    if inv_status == "SETTLED_FULL":
        order = db.reman_orders.get(inv["reman_order_id"])
        if order is not None and order["core_settlement_status"] == "PENDING":
            order["core_settlement_status"] = "CLOSED"
            order["updated_at"] = now
            order["version"] += 1


# ---------------- CoreUnit ----------------

@bp.post("/api/core-units")
def register_core():
    require_role({"CoreIntakeClerk"})
    body = get_json_body()
    require_fields(
        body, ["core_deposit_invoice_id", "dock_code", "dock_start_utc", "dock_end_utc"]
    )
    check_string(body["core_deposit_invoice_id"], "core_deposit_invoice_id")
    check_string(body["dock_code"], "dock_code")
    dock_start = parse_iso8601(body["dock_start_utc"], "dock_start_utc")
    dock_end = parse_iso8601(body["dock_end_utc"], "dock_end_utc")
    # Malformed window (priority 3) precedes invoice existence (4).
    if dock_end <= dock_start:
        invalid("dock_end_utc must be > dock_start_utc")

    inv = db.core_deposit_invoices.get(body["core_deposit_invoice_id"])
    if inv is None:
        raise ApiError(
            ERR_INVOICE_NOT_FOUND, "CoreDepositInvoice id does not exist", 404
        )
    # Invoice OPEN gate (priority 6) precedes dock-overlap check (priority 9).
    if inv["status"] != "OPEN":
        raise ApiError(
            ERR_INVOICE_NOT_OPEN, "core registration requires invoice status OPEN", 409
        )

    # Closed interval + 30-minute turnaround buffer on the same dock.
    for c in db.core_units.values():
        if c["dock_code"] != body["dock_code"]:
            continue
        occ_start = c["dock_start_utc"]
        occ_end = c["dock_end_utc"] + DOCK_BUFFER
        # Closed-interval conflict: intervals [dock_start, dock_end] and
        # [occ_start, occ_end] overlap when start <= occ_end and occ_start <= end.
        if dock_start <= occ_end and occ_start <= dock_end:
            raise ApiError(
                ERR_DOCK_OVERLAP,
                "closed dock interval plus 30-minute turnaround buffer conflicts with an existing appointment on the same dock",
                409,
            )

    now = db.now()
    days_late = math.floor((now - inv["issued_at"]).total_seconds() / 86400)
    core = {
        "id": str(uuid.uuid4()),
        "core_deposit_invoice_id": inv["id"],
        "dock_code": body["dock_code"],
        "dock_start_utc": dock_start,
        "dock_end_utc": dock_end,
        "received_at": now,
        "days_late": days_late,
        "case_cracked": None,
        "findings": [],
        "deduction_score": None,
        "grade": None,
        "status": "RECEIVED",
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    db.core_units[core["id"]] = core
    # Cascade: invoice OPEN -> AWAITING_GRADE (atomic with registration).
    inv["status"] = "AWAITING_GRADE"
    inv["updated_at"] = now
    inv["version"] += 1
    return success(core_view(core), "object", 201)


@bp.get("/api/core-units")
def list_cores():
    require_role({"Any"})
    items = list(db.core_units.values())
    iid = request.args.get("core_deposit_invoice_id")
    status = request.args.get("status")
    if iid is not None:
        items = [c for c in items if c["core_deposit_invoice_id"] == iid]
    if status is not None:
        items = [c for c in items if c["status"] == status]
    items.sort(key=lambda c: c["created_at"])
    limit, offset = parse_limit_offset(request.args)
    page, pg = paginate(items, limit, offset)
    return success([core_view(c) for c in page], "array", 200, pg)


@bp.get("/api/core-units/<cid>")
def get_core(cid):
    require_role({"Any"})
    return success(core_view(_get_core(cid)), "object", 200)


@bp.post("/api/core-units/<cid>/inspect")
def inspect_core(cid):
    require_role({"CoreInspector"})
    body = get_json_body()
    require_fields(body, ["case_cracked", "findings"])
    if not isinstance(body["case_cracked"], bool):
        invalid("Field case_cracked must be a boolean")
    if not isinstance(body["findings"], list):
        invalid("Field findings must be an array")
    for f in body["findings"]:
        check_enum(f, "findings", FINDING_ENUM)

    core = _get_core(cid)
    if core["status"] not in {"RECEIVED", "RE_INSPECTION"}:
        raise ApiError(
            ERR_CORE_NOT_INSPECTABLE,
            "inspect requires core status RECEIVED or RE_INSPECTION",
            409,
        )
    core["case_cracked"] = body["case_cracked"]
    core["findings"] = list(body["findings"])
    _settle_from_inspection(core)
    return success(core_view(core), "object", 200)


# ---------------- CoreDepositInvoice ----------------

@bp.get("/api/core-deposit-invoices")
def list_invoices():
    require_role({"Any"})
    items = list(db.core_deposit_invoices.values())
    oid = request.args.get("reman_order_id")
    status = request.args.get("status")
    if oid is not None:
        items = [i for i in items if i["reman_order_id"] == oid]
    if status is not None:
        items = [i for i in items if i["status"] == status]
    items.sort(key=lambda i: i["created_at"])
    limit, offset = parse_limit_offset(request.args)
    page, pg = paginate(items, limit, offset)
    return success([invoice_view(i) for i in page], "array", 200, pg)


@bp.get("/api/core-deposit-invoices/<iid>")
def get_invoice(iid):
    require_role({"Any"})
    return success(invoice_view(_get_invoice(iid)), "object", 200)


@bp.post("/api/core-deposit-invoices/<iid>/dispute")
def dispute_invoice(iid):
    require_role({"CoreIntakeClerk"})
    inv = _get_invoice(iid)
    if inv["status"] not in {"SETTLED_PARTIAL", "FORFEITED"}:
        raise ApiError(
            ERR_INVOICE_NOT_DISPUTABLE,
            "dispute requires status SETTLED_PARTIAL or FORFEITED",
            409,
        )
    inv["status"] = "DISPUTED"
    inv["updated_at"] = db.now()
    inv["version"] += 1
    return success(invoice_view(inv), "object", 200)


@bp.post("/api/core-deposit-invoices/<iid>/resolve-dispute")
def resolve_dispute(iid):
    require_role({"ProgramAdmin"})
    body = get_json_body()
    require_fields(body, ["action"])
    check_enum(body["action"], "action", {"REINSPECT", "ADJUST"})
    adjusted = body.get("adjusted_credit_cents")
    if body["action"] == "ADJUST":
        if adjusted is None:
            invalid("adjusted_credit_cents is required for action ADJUST")
        check_int(adjusted, "adjusted_credit_cents")

    inv = _get_invoice(iid)
    if inv["status"] != "DISPUTED":
        raise ApiError(
            ERR_INVOICE_NOT_DISPUTED, "resolve-dispute requires status DISPUTED", 409
        )
    now = db.now()
    if body["action"] == "REINSPECT":
        inv["status"] = "AWAITING_GRADE"
        inv["updated_at"] = now
        inv["version"] += 1
        # Cascade: linked CoreUnit GRADED|REJECTED -> RE_INSPECTION.
        for c in db.core_units.values():
            if c["core_deposit_invoice_id"] == inv["id"] and c["status"] in {
                "GRADED",
                "REJECTED",
            }:
                c["status"] = "RE_INSPECTION"
                c["updated_at"] = now
                c["version"] += 1
        return success(invoice_view(inv), "object", 200)

    # ADJUST
    if adjusted < 0 or adjusted > inv["deposit_cents"]:
        raise ApiError(
            ERR_ADJUSTMENT_OUT_OF_RANGE,
            "adjusted_credit_cents outside [0, deposit_cents]",
            422,
        )
    inv["final_credit_cents"] = adjusted
    inv["forfeited_cents"] = inv["deposit_cents"] - adjusted
    inv["status"] = "SETTLED_ADJUSTED"
    inv["updated_at"] = now
    inv["version"] += 1
    order = db.reman_orders.get(inv["reman_order_id"])
    if order is not None and order["core_settlement_status"] == "PENDING":
        order["core_settlement_status"] = "CLOSED"
        order["updated_at"] = now
        order["version"] += 1
    return success(invoice_view(inv), "object", 200)
