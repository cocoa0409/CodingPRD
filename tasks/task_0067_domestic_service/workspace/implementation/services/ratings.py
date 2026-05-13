"""OrderRating + abnormal events."""
from decimal import Decimal

from db import store
from errors import (
    ERR_VALIDATION_ERROR, ERR_NOT_FOUND, ERR_RATING_NOT_ALLOWED,
    ERR_RATING_OUT_OF_RANGE, ERR_RATING_ALREADY_EXISTS, ERR_INVALID_STATE,
    raise_error,
)
from services.utils import stamp_create, round_half_up_4
from services.personnel import recompute_tier


def create_rating(order_id: str, body: dict, caller_role: str, caller_id: str) -> dict:
    if order_id not in store.orders:
        raise_error(ERR_NOT_FOUND, "Order not found")
    o = store.orders[order_id]
    if caller_id != o["customer_id"]:
        raise_error(ERR_NOT_FOUND, "Order not found")
    if o["status"] != "ACCEPTED_BY_CUSTOMER":
        raise_error(ERR_RATING_NOT_ALLOWED, "Rating only allowed after customer-accept")
    # Range validation
    scores = {}
    for f in ("quality_score", "punctuality_score", "attitude_score"):
        if f not in body or body[f] is None:
            raise_error(ERR_VALIDATION_ERROR, f"Missing required field: {f}")
        try:
            v = int(body[f])
        except (TypeError, ValueError):
            raise_error(ERR_RATING_OUT_OF_RANGE, f"{f} must be an integer in [1,5]")
        if v < 1 or v > 5:
            raise_error(ERR_RATING_OUT_OF_RANGE, f"{f} must be in [1,5]")
        scores[f] = v
    # Uniqueness
    if o["id"] in store.ratings_by_order:
        raise_error(ERR_RATING_ALREADY_EXISTS, "Rating already exists for this order")
    composite = round_half_up_4(
        Decimal("0.5") * Decimal(scores["quality_score"])
        + Decimal("0.3") * Decimal(scores["punctuality_score"])
        + Decimal("0.2") * Decimal(scores["attitude_score"])
    )
    investigation_status = "OPEN" if composite < Decimal("3.0") else "NONE"

    record = {
        "order_id": o["id"],
        "quality_score": scores["quality_score"],
        "punctuality_score": scores["punctuality_score"],
        "attitude_score": scores["attitude_score"],
        "text_review": body.get("text_review", ""),
        "anonymous": bool(body.get("anonymous", False)),
        "composite_score": float(composite),
        "investigation_status": investigation_status,
    }
    record["id"] = store.new_id()
    record["created_at"] = store.now_iso()
    store.ratings[record["id"]] = record
    store.ratings_by_order[o["id"]] = record["id"]
    o["rated"] = True

    # Update personnel running average and tier
    p = store.personnel.get(o["assigned_personnel_id"])
    if p:
        old_count = int(p.get("rating_count", 0))
        old_score = Decimal(str(p.get("rating_score", 0)))
        new_count = old_count + 1
        new_score = round_half_up_4(
            (old_score * Decimal(old_count) + composite) / Decimal(new_count)
        )
        p["rating_count"] = new_count
        p["rating_score"] = float(new_score)
        recompute_tier(p)
        # bump version/timestamps
        p["updated_at"] = store.now_iso()
        p["version"] = int(p.get("version", 1)) + 1
    return record


def close_investigation(rating_id: str) -> dict:
    if rating_id not in store.ratings:
        raise_error(ERR_NOT_FOUND, "Rating not found")
    r = store.ratings[rating_id]
    if r["investigation_status"] != "OPEN":
        raise_error(ERR_INVALID_STATE, "Investigation is not OPEN")
    r["investigation_status"] = "CLOSED"
    return r


# ---------- AbnormalEvent ----------
VALID_CATEGORIES = {"INJURY", "PROPERTY_DAMAGE", "NO_SHOW", "OTHER"}


def create_abnormal_event(order_id: str, body: dict, caller_role: str, caller_id: str):
    if order_id not in store.orders:
        raise_error(ERR_NOT_FOUND, "Order not found")
    o = store.orders[order_id]
    category = body.get("category")
    if category not in VALID_CATEGORIES:
        raise_error(ERR_VALIDATION_ERROR, "Invalid category")
    description = body.get("description", "")
    reporter_role = {
        "Customer": "CUSTOMER",
        "ServicePersonnel": "PERSONNEL",
        "PlatformOperator": "OPERATOR",
    }.get(caller_role, "OPERATOR")
    # Customer must own order; personnel must be the assignee
    if caller_role == "Customer" and caller_id != o["customer_id"]:
        raise_error(ERR_NOT_FOUND, "Order not found")
    if caller_role == "ServicePersonnel" and caller_id != o.get("assigned_personnel_id"):
        raise_error(ERR_NOT_FOUND, "Order not found")
    triggers_claim = category in {"INJURY", "PROPERTY_DAMAGE"}
    record = {
        "order_id": o["id"],
        "reporter_role": reporter_role,
        "category": category,
        "description": description,
        "triggers_claim": triggers_claim,
    }
    record["id"] = store.new_id()
    record["created_at"] = store.now_iso()
    store.abnormal_events[record["id"]] = record

    # Flip execution.abnormal_reported if there is one
    if o["id"] in store.executions_by_order:
        ex = store.executions[store.executions_by_order[o["id"]]]
        ex["abnormal_reported"] = True

    claim = None
    if triggers_claim:
        claim_type = "ON_JOB_INJURY" if category == "INJURY" else "PROPERTY_DAMAGE"
        claim = {
            "order_id": o["id"],
            "abnormal_event_id": record["id"],
            "claim_type": claim_type,
            "status": "REPORTED",
            "claimed_amount_cents": int(body.get("claimed_amount_cents", 0)),
            "paid_amount_cents": 0,
            "evidence_count": 0,
        }
        stamp_create(claim)
        store.insurance_claims[claim["id"]] = claim

    return record, claim
