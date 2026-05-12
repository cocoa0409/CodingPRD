"""Complaint lifecycle and resolution side-effects."""
from decimal import Decimal

import db
from errors import err
from services.audit import audit
from services.util import require_str, require_enum, check_occ


CATEGORIES = {"NURSE_MISCONDUCT", "SERVICE_QUALITY", "BILLING", "SAFETY", "OTHER"}


def submit_complaint(patient_id: str, body: dict) -> dict:
    order_id = require_str(body, "order_id")
    category = require_enum(body, "category", CATEGORIES)
    description = require_str(body, "description")

    order = db.orders.get(order_id)
    if order is None:
        raise err("ERR_ORDER_NOT_FOUND", f"order {order_id} not found")
    if order.get("patient_id") != patient_id:
        raise err("ERR_INSUFFICIENT_PERMISSIONS", "not your order")
    if order["status"] != "COMPLETED":
        raise err("ERR_INVALID_STATE", "complaints can only be filed against completed orders")

    # Find assigned nurse via accepted dispatch
    nurse_id = None
    for d in db.dispatches.values():
        if d.get("order_id") == order_id and d.get("status") == "ACCEPTED":
            nurse_id = d.get("nurse_id")
            break

    c = {
        "order_id": order_id,
        "nurse_id": nurse_id,
        "patient_id": patient_id,
        "category": category,
        "routing": None,
        "description": description,
        "stage": "SUBMITTED",
        "rating_impact": 0,
        "compensation_cents": 0,
        "resolution_notes": None,
    }
    db.stamp_create(c, common_fields=True)
    db.complaints[c["id"]] = c
    audit("COMPLAINT", c["id"], "COMPLAINT_SUBMIT",
          payload={"order_id": order_id, "category": category})
    return c


def list_complaints_scoped(role: str, user_id: str, limit: int, offset: int, stage=None):
    rows = list(db.complaints.values())
    if stage is not None:
        rows = [r for r in rows if r.get("stage") == stage]
    if role == "Patient":
        rows = [r for r in rows if r.get("patient_id") == user_id]
    rows.sort(key=lambda r: r["_seq"])
    total = len(rows)
    return rows[offset: offset + limit], total


def get_complaint(complaint_id: str) -> dict:
    c = db.complaints.get(complaint_id)
    if c is None:
        raise err("ERR_COMPLAINT_NOT_FOUND", f"complaint {complaint_id} not found")
    return c


def triage(complaint_id: str, body: dict) -> dict:
    c = get_complaint(complaint_id)
    if c["stage"] != "SUBMITTED":
        raise err("ERR_INVALID_STATE", f"complaint is {c['stage']}")
    check_occ(c, body or {})
    routing = "NURSE_RELATED" if c["category"] in ("NURSE_MISCONDUCT", "SAFETY") else "SERVICE_RELATED"
    c["routing"] = routing
    c["stage"] = "TRIAGE"
    db.stamp_update(c)
    return c


def escalate(complaint_id: str, body: dict) -> dict:
    c = get_complaint(complaint_id)
    if c["stage"] != "TRIAGE":
        raise err("ERR_INVALID_STATE", f"complaint is {c['stage']}")
    check_occ(c, body or {})
    c["stage"] = "MEDIATION"
    db.stamp_update(c)
    return c


def resolve(complaint_id: str, body: dict) -> dict:
    from services.settlement import get_settlement_for_order
    from services.rating import apply_rating_impact_clamped, recompute_rating

    c = get_complaint(complaint_id)
    if c["stage"] not in ("TRIAGE", "MEDIATION"):
        raise err("ERR_INVALID_STATE", f"complaint is {c['stage']}")

    decision = body.get("decision")
    if decision not in ("UPHOLD", "REJECT"):
        raise err("ERR_INVALID_REQUEST", "decision must be UPHOLD or REJECT")
    check_occ(c, body or {})

    notes = body.get("resolution_notes")
    if notes is not None and not isinstance(notes, str):
        raise err("ERR_INVALID_REQUEST", "resolution_notes must be a string")
    c["resolution_notes"] = notes

    if decision == "REJECT":
        c["stage"] = "REJECTED"
        db.stamp_update(c)
        audit("COMPLAINT", c["id"], "COMPLAINT_REJECT", payload={"order_id": c["order_id"]})
        return c

    # UPHOLD only valid from MEDIATION
    if c["stage"] != "MEDIATION":
        raise err("ERR_INVALID_STATE", "UPHOLD requires MEDIATION stage")

    compensation = body.get("compensation_cents", 0)
    if compensation is None:
        compensation = 0
    if isinstance(compensation, bool) or not isinstance(compensation, int):
        raise err("ERR_INVALID_REQUEST", "compensation_cents must be an integer")
    if compensation < 0:
        raise err("ERR_INVALID_REQUEST", "compensation_cents must be >= 0")

    rating_impact = body.get("rating_impact", 0)
    if rating_impact is None:
        rating_impact = 0
    if isinstance(rating_impact, bool) or not isinstance(rating_impact, (int, float)):
        raise err("ERR_INVALID_REQUEST", "rating_impact must be a number")

    # Caps and routing-specific rules
    settlement = get_settlement_for_order(c["order_id"])
    if settlement is not None:
        if compensation > int(settlement["gross_fee_cents"]):
            raise err("ERR_COMPENSATION_EXCEEDS_FEE",
                      "compensation_cents exceeds settlement gross_fee_cents")

    if c["routing"] == "NURSE_RELATED":
        if not (-1.0 <= float(rating_impact) <= 0.0):
            raise err("ERR_INVALID_REQUEST",
                      "rating_impact must be in [-1.0, 0] for NURSE_RELATED")
    else:
        if float(rating_impact) != 0.0:
            raise err("ERR_INVALID_REQUEST",
                      "rating_impact must be 0 for SERVICE_RELATED")

    # Apply rating impact
    if c["routing"] == "NURSE_RELATED" and float(rating_impact) != 0.0 and c.get("nurse_id"):
        apply_rating_impact_clamped(c["nurse_id"], float(rating_impact))

    # Apply compensation
    if compensation > 0 and settlement is not None:
        settlement["refund_cents"] = int(settlement.get("refund_cents") or 0) + compensation
        if settlement["status"] in ("FINALIZED", "PAID_OUT"):
            settlement["status"] = "REVERSED"

    c["compensation_cents"] = compensation
    c["rating_impact"] = float(rating_impact)
    c["stage"] = "RESOLVED"
    db.stamp_update(c)

    # Recompute rating from scratch (window-based) once the resolution lands
    if c.get("nurse_id"):
        recompute_rating(c["nurse_id"])

    audit("COMPLAINT", c["id"], "COMPLAINT_RESOLVE",
          payload={"compensation_cents": compensation, "rating_impact": float(rating_impact)})
    return c
