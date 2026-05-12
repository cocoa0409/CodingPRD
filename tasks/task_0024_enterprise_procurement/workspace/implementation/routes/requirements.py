"""Requirement endpoints (PRD §3.2 / §3.3 / §3.5)."""

from __future__ import annotations

import datetime as _dt

from flask import Blueprint, g, jsonify, request

from db import db, parse_iso, stamp_create, stamp_update, serialize, serialize_list, order_by_created_then_seq
from errors import err
from middleware import enforce_role, require_roles
from pagination import paginate, parse_limit_offset
from response import success_array, success_object
from services.calculations import recompute_pool_scores, tier_for_amount
from services.lookups import find_budget_account, find_quote, find_requirement
from validate import get_json_body, require_enum, require_fields, require_int, require_string

bp = Blueprint("requirements", __name__)

CATEGORIES = {
    "IT_HARDWARE", "IT_SOFTWARE", "OFFICE_SUPPLIES",
    "PROFESSIONAL_SERVICES", "MARKETING", "CAPEX_EQUIPMENT",
}


def _parse_delivery_date(value: str, created_at_iso: str) -> None:
    """Validate expected_delivery_date >= created_at + 1 day."""
    try:
        delivery_dt = parse_iso(value)
    except Exception:
        raise err("ERR_VALIDATION", "expected_delivery_date must be ISO 8601.")
    created_dt = parse_iso(created_at_iso)
    if delivery_dt < created_dt + _dt.timedelta(days=1):
        raise err(
            "ERR_DELIVERY_DATE_TOO_EARLY",
            "expected_delivery_date must be at least 1 day after creation.",
        )


@bp.post("/requirements")
@require_roles("Requester")
def create_requirement():
    body = get_json_body()
    require_fields(body, [
        "category", "specification", "quantity", "unit",
        "expected_delivery_date", "budget_account_id", "estimated_unit_price_cents",
    ])
    category = body["category"]
    require_enum(category, CATEGORIES, "category")
    specification = require_string(body["specification"], "specification")
    quantity = require_int(body["quantity"], "quantity", min_value=1)
    unit = require_string(body["unit"], "unit")
    delivery = require_string(body["expected_delivery_date"], "expected_delivery_date")
    ba_id = require_string(body["budget_account_id"], "budget_account_id")
    eup = require_int(body["estimated_unit_price_cents"], "estimated_unit_price_cents", min_value=0)
    attachment_uri = body.get("attachment_uri")
    if attachment_uri is not None and not isinstance(attachment_uri, str):
        raise err("ERR_VALIDATION", "attachment_uri must be a string.")

    # Validate budget account exists (it's in the body, so this is a business
    # ref check, not a path-existence check). Per priority ordering, schema
    # validation is priority 20; ERR_VALIDATION is acceptable for "unknown" id.
    if ba_id not in db.budget_accounts:
        raise err("ERR_VALIDATION", "budget_account_id does not exist.")

    row = {
        "requester_id": g.user_id,
        "category": category,
        "specification": specification,
        "quantity": quantity,
        "unit": unit,
        "expected_delivery_date": delivery,
        "budget_account_id": ba_id,
        "estimated_unit_price_cents": eup,
        "estimated_total_cents": quantity * eup,
        "attachment_uri": attachment_uri,
        "status": "DRAFT",
        "justification": None,
    }
    stamp_create(row, common=True)
    # Now run delivery-date check (priority 17 — ERR_DELIVERY_DATE_TOO_EARLY).
    _parse_delivery_date(delivery, row["created_at"])
    db.requirements[row["id"]] = row
    return jsonify(success_object(serialize(row))), 201


@bp.post("/requirements/<rid>/submit")
@require_roles("Requester")
def submit_requirement(rid: str):
    row = find_requirement(rid)
    enforce_role()
    if row["status"] != "DRAFT":
        raise err("ERR_INVALID_STATE", "Requirement is not in DRAFT.")
    ba = db.budget_accounts.get(row["budget_account_id"])
    if ba is None or ba.get("status") != "ACTIVE":
        raise err("ERR_INVALID_STATE", "Bound BudgetAccount is not ACTIVE.")
    # Re-check delivery-date temporal rule per PRD §3.2 last sentence
    _parse_delivery_date(row["expected_delivery_date"], row["created_at"])
    row["status"] = "SUBMITTED"
    stamp_update(row)
    return jsonify(success_object(serialize(row))), 200


@bp.post("/requirements/<rid>/quotes")
@require_roles("Buyer")
def add_quote(rid: str):
    requirement = find_requirement(rid)
    enforce_role()
    body = get_json_body()
    require_fields(body, ["supplier_id", "unit_price_cents", "lead_time_days", "technical_score"])
    supplier_id = require_string(body["supplier_id"], "supplier_id")
    unit_price = require_int(body["unit_price_cents"], "unit_price_cents", min_value=1)
    lead_time = require_int(body["lead_time_days"], "lead_time_days", min_value=0)
    tech = body["technical_score"]
    if isinstance(tech, bool) or not isinstance(tech, (int, float)):
        raise err("ERR_VALIDATION", "technical_score must be a number.")
    if tech < 0 or tech > 100:
        raise err("ERR_VALIDATION", "technical_score must be 0..100.")

    # State precondition (priority 5): requirement must be SUBMITTED or IN_SOURCING.
    if requirement["status"] not in ("SUBMITTED", "IN_SOURCING"):
        raise err("ERR_INVALID_STATE", "Requirement is not in SUBMITTED/IN_SOURCING.")

    # Priority 6: supplier qualification gate (atomic).
    supplier = db.suppliers.get(supplier_id)
    now = db.now()
    if supplier is None:
        raise err("ERR_SUPPLIER_NOT_QUALIFIED", "Supplier not found or not qualified.")
    if supplier.get("qualification_status") != "QUALIFIED":
        raise err("ERR_SUPPLIER_NOT_QUALIFIED", "Supplier is not QUALIFIED.")
    if requirement["category"] not in (supplier.get("qualification_categories") or []):
        raise err("ERR_SUPPLIER_NOT_QUALIFIED", "Supplier not qualified for this category.")
    try:
        qexp = parse_iso(supplier["qualification_expires_at"])
    except Exception:
        raise err("ERR_SUPPLIER_NOT_QUALIFIED", "Supplier qualification_expires_at invalid.")
    if not (qexp > now):
        raise err("ERR_SUPPLIER_NOT_QUALIFIED", "Supplier qualification has expired.")

    quote = {
        "requirement_id": rid,
        "supplier_id": supplier_id,
        "unit_price_cents": unit_price,
        "lead_time_days": lead_time,
        "technical_score": float(tech),
        "commercial_score": 0,
        "composite_score": 0,
        "status": "SUBMITTED",
    }
    stamp_create(quote, common=True)
    db.quotes[quote["id"]] = quote

    # Pool-relative scoring (incremental_recompute)
    recompute_pool_scores(rid)

    # First valid quote moves SUBMITTED -> IN_SOURCING
    if requirement["status"] == "SUBMITTED":
        requirement["status"] = "IN_SOURCING"
        stamp_update(requirement)

    return jsonify(success_object(serialize(quote))), 201


@bp.post("/requirements/<rid>/shortlist")
@require_roles("Buyer")
def shortlist_quotes(rid: str):
    requirement = find_requirement(rid)
    enforce_role()
    body = get_json_body()
    require_fields(body, ["quote_ids"])
    quote_ids = body["quote_ids"]
    if not isinstance(quote_ids, list) or not quote_ids:
        raise err("ERR_VALIDATION", "quote_ids must be a non-empty list.")
    if requirement["status"] != "IN_SOURCING":
        raise err("ERR_INVALID_STATE", "Requirement is not IN_SOURCING.")

    # Validate that every quote belongs to this requirement and is SUBMITTED.
    quotes = []
    for qid in quote_ids:
        if not isinstance(qid, str):
            raise err("ERR_VALIDATION", "quote_ids items must be strings.")
        q = db.quotes.get(qid)
        if q is None or q.get("requirement_id") != rid:
            raise err("ERR_VALIDATION", f"Quote {qid} does not belong to this requirement.")
        if q.get("status") != "SUBMITTED":
            raise err("ERR_INVALID_STATE", f"Quote {qid} is not in SUBMITTED status.")
        # Supplier still qualified at shortlist time (PRD §3.2 last paragraph)
        sup = db.suppliers.get(q.get("supplier_id"))
        if sup is None or sup.get("qualification_status") != "QUALIFIED":
            raise err("ERR_SUPPLIER_NOT_QUALIFIED", f"Supplier of quote {qid} is not QUALIFIED.")
        quotes.append(q)

    # Re-run pool-relative scoring before flipping anyone — pool is the SUBMITTED set.
    recompute_pool_scores(rid)

    # Move named quotes to SHORTLISTED, stamping update
    for q in quotes:
        q["status"] = "SHORTLISTED"
        stamp_update(q)

    return jsonify(success_object({"shortlisted_quote_ids": [q["id"] for q in quotes]})), 200


@bp.post("/requirements/<rid>/award")
@require_roles("Buyer")
def award_requirement(rid: str):
    requirement = find_requirement(rid)
    enforce_role()
    body = get_json_body()
    # PRD §2.8 priority 11: empty justification at award is reported as
    # ERR_INSUFFICIENT_QUOTES, not ERR_VALIDATION. Therefore exclude
    # justification from the priority-20 non-empty schema check; only
    # require it to be present and a string here, and let the priority-11
    # block below decide on emptiness.
    require_fields(body, ["awarded_quote_id"])
    awarded_qid = require_string(body["awarded_quote_id"], "awarded_quote_id")
    if "justification" not in body:
        raise err("ERR_VALIDATION", "Missing required field 'justification'.")
    justification = body.get("justification")
    if not isinstance(justification, str):
        raise err("ERR_VALIDATION", "justification must be a string.")

    # Race-loser detection: if requirement is no longer IN_SOURCING and is in
    # AWARDED/IN_APPROVAL/etc., return ERR_REQUIREMENT_ALREADY_AWARDED.
    if requirement["status"] != "IN_SOURCING":
        if requirement["status"] in ("AWARDED", "IN_APPROVAL", "APPROVED", "REJECTED"):
            raise err("ERR_REQUIREMENT_ALREADY_AWARDED",
                      "Requirement is no longer IN_SOURCING.")
        raise err("ERR_INVALID_STATE", "Requirement is not in IN_SOURCING.")

    # Priority 11 — at least 3 SHORTLISTED, awarded among them, justification non-empty
    shortlisted = [q for q in db.quotes.values()
                   if q.get("requirement_id") == rid and q.get("status") == "SHORTLISTED"]
    if len(shortlisted) < 3:
        raise err("ERR_INSUFFICIENT_QUOTES", "Need at least 3 SHORTLISTED quotes.")
    awarded = next((q for q in shortlisted if q["id"] == awarded_qid), None)
    if awarded is None:
        raise err("ERR_INSUFFICIENT_QUOTES",
                  "awarded_quote_id is not among the SHORTLISTED set.")
    if justification.strip() == "":
        raise err("ERR_INSUFFICIENT_QUOTES", "justification must be non-empty.")

    # Compute PO total and tier
    total_cents = int(awarded["unit_price_cents"]) * int(requirement["quantity"])
    tier = tier_for_amount(total_cents)

    # Priority 14 — budget commitment must fit
    ba = db.budget_accounts.get(requirement["budget_account_id"])
    if ba is None:
        raise err("ERR_VALIDATION", "BudgetAccount missing.")
    if ba["committed_amount_cents"] + total_cents > ba["total_amount_cents"]:
        raise err("ERR_BUDGET_WOULD_EXCEED",
                  "PurchaseOrder would push committed amount beyond budget total.")

    # Commit
    ba["committed_amount_cents"] += total_cents
    stamp_update(ba)

    # Flip requirement to AWARDED then IN_APPROVAL (cascade per PRD §3.3)
    requirement["status"] = "IN_APPROVAL"
    requirement["justification"] = justification
    stamp_update(requirement)

    # Awarded quote → AWARDED; sibling SHORTLISTED → REJECTED
    awarded["status"] = "AWARDED"
    stamp_update(awarded)
    for q in shortlisted:
        if q["id"] != awarded_qid:
            q["status"] = "REJECTED"
            stamp_update(q)

    # Create PO
    po = {
        "requirement_id": rid,
        "awarded_quote_id": awarded_qid,
        "supplier_id": awarded["supplier_id"],
        "budget_account_id": requirement["budget_account_id"],
        "total_amount_cents": total_cents,
        "tier": tier,
        "status": "PENDING_APPROVAL",
        "approval_started_at": db.now_iso(),
        "approved_at": None,
    }
    stamp_create(po, common=True)
    db.purchase_orders[po["id"]] = po

    # Generate ApprovalStep records per tier
    from services.approval import create_approval_steps
    create_approval_steps(po, tier)

    return jsonify(success_object(serialize(po))), 201


@bp.post("/requirements/<rid>/rework")
@require_roles("Requester")
def rework_requirement(rid: str):
    row = find_requirement(rid)
    enforce_role()
    if row["status"] != "REJECTED":
        raise err("ERR_INVALID_STATE", "Requirement is not REJECTED.")
    row["status"] = "DRAFT"
    row["justification"] = None
    stamp_update(row)
    return jsonify(success_object(serialize(row))), 200


@bp.post("/requirements/<rid>/cancel")
@require_roles("Requester")
def cancel_requirement(rid: str):
    row = find_requirement(rid)
    enforce_role()
    if row["status"] not in ("DRAFT", "SUBMITTED"):
        raise err("ERR_INVALID_STATE", "Requirement is not DRAFT/SUBMITTED.")
    row["status"] = "CANCELLED"
    stamp_update(row)
    return jsonify(success_object(serialize(row))), 200


@bp.get("/requirements/<rid>")
@require_roles("Requester", "Buyer", "FinanceApprover", "DepartmentHead", "GeneralManager", "LegalApprover")
def get_requirement(rid: str):
    row = find_requirement(rid)
    enforce_role()
    return jsonify(success_object(serialize(row))), 200


@bp.get("/requirements")
@require_roles("Requester", "Buyer", "FinanceApprover", "DepartmentHead", "GeneralManager", "LegalApprover")
def list_requirements():
    limit, offset = parse_limit_offset()
    status = request.args.get("status")
    category = request.args.get("category")
    requester_id = request.args.get("requester_id")
    ba_id = request.args.get("budget_account_id")
    rows = list(db.requirements.values())
    if status is not None:
        rows = [r for r in rows if r.get("status") == status]
    if category is not None:
        rows = [r for r in rows if r.get("category") == category]
    if requester_id is not None:
        rows = [r for r in rows if r.get("requester_id") == requester_id]
    if ba_id is not None:
        rows = [r for r in rows if r.get("budget_account_id") == ba_id]
    rows = order_by_created_then_seq(rows)
    page, total = paginate(rows, limit, offset)
    return jsonify(success_array(serialize_list(page), limit, offset, total)), 200


@bp.get("/requirements/<rid>/quotes/comparison-table")
@require_roles("Buyer", "FinanceApprover", "GeneralManager")
def comparison_table(rid: str):
    requirement = find_requirement(rid)
    enforce_role()
    quotes = [q for q in db.quotes.values() if q.get("requirement_id") == rid]
    quotes = order_by_created_then_seq(quotes)
    table = [
        {
            "quote_id": q["id"],
            "supplier_id": q.get("supplier_id"),
            "unit_price_cents": q.get("unit_price_cents"),
            "lead_time_days": q.get("lead_time_days"),
            "technical_score": q.get("technical_score"),
            "commercial_score": q.get("commercial_score"),
            "composite_score": q.get("composite_score"),
            "status": q.get("status"),
        }
        for q in quotes
    ]
    return jsonify(success_object({"requirement_id": requirement["id"], "quotes": table})), 200
