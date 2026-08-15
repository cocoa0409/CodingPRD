"""Routes: audit cases and audit scope items (PRD §3.5, §3.7)."""

from flask import Blueprint, request

import db
import services as svc
from errors import (
    raise_err,
    ERR_VENDOR_NOT_FOUND, ERR_PRODUCT_NOT_FOUND, ERR_AUDIT_CASE_NOT_FOUND,
    ERR_SCOPE_ITEM_NOT_FOUND, ERR_AUDIT_CASE_INVALID_STATE,
    ERR_SCOPE_ITEM_INVALID_STATE, ERR_RESPONSE_DEADLINE_PASSED,
    ERR_SCOPE_ITEMS_PENDING, ERR_EMPTY_AUDIT_SCOPE,
    ERR_NO_RELEASED_SUBMISSION, ERR_FINDINGS_INCOMPLETE,
    ERR_EXPOSURE_NOT_ZERO, ERR_DUPLICATE_SCOPE_ITEM,
    ERR_PRODUCT_UNDER_CONCURRENT_AUDIT,
)
from middleware import require_role, ALL_ROLES
from response import success_object, success_list, paginate
from validation import body, req_string, req_enum, req_datetime

bp = Blueprint("audit", __name__)

CASE_STATUSES = (
    "NOTICE_RECEIVED", "SCOPE_NEGOTIATION", "EVIDENCE_COLLECTION",
    "FINDINGS_REVIEW", "SETTLEMENT_NEGOTIATION", "CLOSED_SETTLED",
    "CLOSED_NO_ACTION", "WITHDRAWN",
)


def _get_case(cid):
    rec = db.audit_cases.get(cid)
    if rec is None:
        raise_err(ERR_AUDIT_CASE_NOT_FOUND, "AuditCase not found")
    return rec


def _get_scope_item(sid):
    rec = db.scope_items.get(sid)
    if rec is None:
        raise_err(ERR_SCOPE_ITEM_NOT_FOUND, "AuditScopeItem not found")
    return rec


# ---------------------------------------------------------------------------
# Audit cases
# ---------------------------------------------------------------------------

@bp.post("/sam/audit-cases")
def create_audit_case():
    require_role(["LegalCounsel"])
    data = body()
    vendor_id = req_string(data, "vendor_id")
    firm = req_string(data, "audit_firm_name")
    notice = req_datetime(data, "notice_received_on")
    vendor = db.vendors.get(vendor_id)
    if vendor is None:
        raise_err(ERR_VENDOR_NOT_FOUND, "vendor_id does not exist")
    deadline = svc.compute_response_deadline(
        notice, vendor["notice_response_deadline_days"])
    rec = svc.stamp_new({
        "vendor_id": vendor_id,
        "audit_firm_name": firm,
        "notice_received_on": notice,
        "response_deadline_on": deadline,
        "status": "NOTICE_RECEIVED",
        "provisional_case_exposure_cents": 0,
        "worst_case_exposure_cents": 0,
        "settled_amount_cents": None,
        "accepted_future_discount_pct": None,
        "last_tendered_offer_id": None,
    })
    db.audit_cases[rec["id"]] = rec
    return success_object(rec, 201)


@bp.get("/sam/audit-cases")
def list_audit_cases():
    require_role(ALL_ROLES)
    records = list(db.audit_cases.values())
    v = request.args.get("vendor_id")
    if v is not None:
        if v not in db.vendors:
            raise_err(ERR_VENDOR_NOT_FOUND, "vendor_id does not exist")
        records = [c for c in records if c["vendor_id"] == v]
    status = request.args.get("status")
    if status is not None:
        records = [c for c in records if c["status"] == status]
    page, total, limit, offset = paginate(records)
    return success_list(page, total, limit, offset)


@bp.get("/sam/audit-cases/<cid>")
def get_audit_case(cid):
    require_role(ALL_ROLES)
    return success_object(_get_case(cid))


@bp.post("/sam/audit-cases/<cid>/advance")
def advance_audit_case(cid):
    require_role(["LegalCounsel"])
    data = body()
    to_state = req_enum(data, "to_state", CASE_STATUSES)
    case = _get_case(cid)
    now = db.clock.now()
    if to_state == "SCOPE_NEGOTIATION":
        if case["status"] != "NOTICE_RECEIVED":
            raise_err(ERR_AUDIT_CASE_INVALID_STATE,
                      "Only a NOTICE_RECEIVED case can advance to "
                      "SCOPE_NEGOTIATION")
        if now > db.parse_iso(case["response_deadline_on"]):
            raise_err(ERR_RESPONSE_DEADLINE_PASSED,
                      "The response deadline has passed")
    elif to_state == "EVIDENCE_COLLECTION":
        if case["status"] != "SCOPE_NEGOTIATION":
            raise_err(ERR_AUDIT_CASE_INVALID_STATE,
                      "Only a SCOPE_NEGOTIATION case can advance to "
                      "EVIDENCE_COLLECTION")
        items = [it for it in db.scope_items.values()
                 if it["audit_case_id"] == cid]
        if any(it["scope_status"] in ("PROPOSED", "DISPUTED") for it in items):
            raise_err(ERR_SCOPE_ITEMS_PENDING,
                      "PROPOSED or DISPUTED scope items remain")
        if not any(it["scope_status"] == "CONFIRMED" for it in items):
            raise_err(ERR_EMPTY_AUDIT_SCOPE,
                      "At least one CONFIRMED scope item is required")
    elif to_state == "FINDINGS_REVIEW":
        if case["status"] != "EVIDENCE_COLLECTION":
            raise_err(ERR_AUDIT_CASE_INVALID_STATE,
                      "Only an EVIDENCE_COLLECTION case can advance to "
                      "FINDINGS_REVIEW")
        if not any(s["audit_case_id"] == cid and s["status"] == "RELEASED"
                   for s in db.submissions.values()):
            raise_err(ERR_NO_RELEASED_SUBMISSION,
                      "At least one RELEASED data submission is required")
    elif to_state == "SETTLEMENT_NEGOTIATION":
        if case["status"] != "FINDINGS_REVIEW":
            raise_err(ERR_AUDIT_CASE_INVALID_STATE,
                      "Only a FINDINGS_REVIEW case can advance to "
                      "SETTLEMENT_NEGOTIATION")
        for it in db.scope_items.values():
            if it["audit_case_id"] == cid and it["scope_status"] == "CONFIRMED" \
                    and it["vendor_finding_amount_cents"] is None:
                raise_err(ERR_FINDINGS_INCOMPLETE,
                          "Every CONFIRMED scope item needs a vendor finding")
    elif to_state == "CLOSED_NO_ACTION":
        if case["status"] != "FINDINGS_REVIEW":
            raise_err(ERR_AUDIT_CASE_INVALID_STATE,
                      "Only a FINDINGS_REVIEW case can advance to "
                      "CLOSED_NO_ACTION")
        if case["worst_case_exposure_cents"] != 0:
            raise_err(ERR_EXPOSURE_NOT_ZERO,
                      "worst_case_exposure_cents must be exactly zero")
    else:
        # NOTICE_RECEIVED / CLOSED_SETTLED / WITHDRAWN are never valid
        # advance targets.
        raise_err(ERR_AUDIT_CASE_INVALID_STATE,
                  f"Cannot advance an audit case to {to_state}")
    case["status"] = to_state
    svc.touch(case)
    return success_object(case)


@bp.post("/sam/audit-cases/<cid>/reopen-evidence")
def reopen_evidence(cid):
    require_role(["VendorAuditor"])
    case = _get_case(cid)
    if case["status"] != "FINDINGS_REVIEW":
        raise_err(ERR_AUDIT_CASE_INVALID_STATE,
                  "Only a FINDINGS_REVIEW case can be reopened for evidence")
    case["status"] = "EVIDENCE_COLLECTION"
    svc.touch(case)
    return success_object(case)


@bp.post("/sam/audit-cases/<cid>/withdraw")
def withdraw_audit_case(cid):
    require_role(["VendorAuditor"])
    case = _get_case(cid)
    if case["status"] in svc.TERMINAL_CASE_STATES:
        raise_err(ERR_AUDIT_CASE_INVALID_STATE,
                  "A closed or withdrawn case cannot be withdrawn")
    # Cascade through the case's open work.
    for o in db.offers.values():
        if o["audit_case_id"] == cid and o["status"] == "TENDERED":
            o["status"] = "WITHDRAWN"
            svc.touch(o)
    case["last_tendered_offer_id"] = None
    for it in db.scope_items.values():
        if it["audit_case_id"] == cid and \
                it["scope_status"] in ("PROPOSED", "DISPUTED"):
            it["scope_status"] = "EXCLUDED"
            svc.touch(it)
    case["status"] = "WITHDRAWN"
    svc.touch(case)
    return success_object(case)


# ---------------------------------------------------------------------------
# Audit scope items
# ---------------------------------------------------------------------------

@bp.post("/sam/audit-scope-items")
def create_scope_item():
    user_id, role = require_role(["SAMManager", "VendorAuditor"])
    data = body()
    audit_case_id = req_string(data, "audit_case_id")
    product_id = req_string(data, "product_id")
    rationale = req_string(data, "inclusion_rationale")
    # Existence per PRD §2.10 body-id order: product_id before audit_case_id.
    product = db.products.get(product_id)
    if product is None:
        raise_err(ERR_PRODUCT_NOT_FOUND, "product_id does not exist")
    case = db.audit_cases.get(audit_case_id)
    if case is None:
        raise_err(ERR_AUDIT_CASE_NOT_FOUND, "audit_case_id does not exist")
    if case["status"] not in ("NOTICE_RECEIVED", "SCOPE_NEGOTIATION"):
        raise_err(ERR_AUDIT_CASE_INVALID_STATE,
                  "Scope items may only be proposed while the case is "
                  "NOTICE_RECEIVED or SCOPE_NEGOTIATION")
    for it in db.scope_items.values():
        if it["audit_case_id"] == audit_case_id \
                and it["product_id"] == product_id \
                and it["scope_status"] in ("PROPOSED", "CONFIRMED", "DISPUTED"):
            raise_err(ERR_DUPLICATE_SCOPE_ITEM,
                      "A scope item for this case and product already exists")
    proposed_by = "VENDOR" if role == "VendorAuditor" else "CUSTOMER"
    rec = svc.stamp_new({
        "audit_case_id": audit_case_id,
        "product_id": product_id,
        "proposed_by": proposed_by,
        "inclusion_rationale": rationale,
        "dispute_rationale": None,
        "scope_status": "PROPOSED",
        "vendor_finding_amount_cents": None,
    })
    db.scope_items[rec["id"]] = rec
    return success_object(rec, 201)


@bp.get("/sam/audit-cases/<cid>/scope-items")
def list_case_scope_items(cid):
    require_role(ALL_ROLES)
    _get_case(cid)
    records = [it for it in db.scope_items.values()
               if it["audit_case_id"] == cid]
    status = request.args.get("scope_status")
    if status is not None:
        records = [it for it in records if it["scope_status"] == status]
    page, total, limit, offset = paginate(records)
    return success_list(page, total, limit, offset)


@bp.get("/sam/products/<pid>/audit-scope-items")
def list_product_scope_items(pid):
    require_role(ALL_ROLES)
    if pid not in db.products:
        raise_err(ERR_PRODUCT_NOT_FOUND, "Product not found")
    records = [it for it in db.scope_items.values()
               if it["product_id"] == pid]
    page, total, limit, offset = paginate(records)
    return success_list(page, total, limit, offset)


@bp.post("/sam/audit-scope-items/<sid>/confirm")
def confirm_scope_item(sid):
    require_role(["LegalCounsel"])
    item = _get_scope_item(sid)
    if item["scope_status"] != "PROPOSED":
        raise_err(ERR_SCOPE_ITEM_INVALID_STATE,
                  "Only a PROPOSED scope item can be confirmed")
    case = db.audit_cases[item["audit_case_id"]]
    if case["status"] != "SCOPE_NEGOTIATION":
        raise_err(ERR_AUDIT_CASE_INVALID_STATE,
                  "Scope items may only be confirmed while the case is in "
                  "SCOPE_NEGOTIATION")
    if db.clock.now() > db.parse_iso(case["response_deadline_on"]):
        raise_err(ERR_RESPONSE_DEADLINE_PASSED,
                  "The response deadline has passed")
    if svc.product_under_concurrent_audit(item["product_id"], case["id"]):
        raise_err(ERR_PRODUCT_UNDER_CONCURRENT_AUDIT,
                  "Product is CONFIRMED in the scope of another non-terminal "
                  "audit case")
    item["scope_status"] = "CONFIRMED"
    svc.touch(item)
    svc.recompute_case_rollups(case)
    svc.touch(case)
    return success_object(item)


@bp.post("/sam/audit-scope-items/<sid>/dispute")
def dispute_scope_item(sid):
    require_role(["LegalCounsel"])
    data = body()
    rationale = req_string(data, "dispute_rationale")
    item = _get_scope_item(sid)
    if item["scope_status"] != "PROPOSED":
        raise_err(ERR_SCOPE_ITEM_INVALID_STATE,
                  "Only a PROPOSED scope item can be disputed")
    case = db.audit_cases[item["audit_case_id"]]
    if case["status"] != "SCOPE_NEGOTIATION":
        raise_err(ERR_AUDIT_CASE_INVALID_STATE,
                  "Scope items may only be disputed while the case is in "
                  "SCOPE_NEGOTIATION")
    item["scope_status"] = "DISPUTED"
    item["dispute_rationale"] = rationale
    svc.touch(item)
    return success_object(item)


@bp.post("/sam/audit-scope-items/<sid>/repropose")
def repropose_scope_item(sid):
    require_role(["SAMManager", "VendorAuditor"])
    data = body()
    rationale = req_string(data, "inclusion_rationale")
    item = _get_scope_item(sid)
    if item["scope_status"] != "DISPUTED":
        raise_err(ERR_SCOPE_ITEM_INVALID_STATE,
                  "Only a DISPUTED scope item can be re-proposed")
    case = db.audit_cases[item["audit_case_id"]]
    if case["status"] != "SCOPE_NEGOTIATION":
        raise_err(ERR_AUDIT_CASE_INVALID_STATE,
                  "Scope items may only be re-proposed while the case is in "
                  "SCOPE_NEGOTIATION")
    item["scope_status"] = "PROPOSED"
    item["inclusion_rationale"] = rationale
    svc.touch(item)
    return success_object(item)


@bp.post("/sam/audit-scope-items/<sid>/exclude")
def exclude_scope_item(sid):
    require_role(["LegalCounsel"])
    item = _get_scope_item(sid)
    if item["scope_status"] not in ("PROPOSED", "DISPUTED", "CONFIRMED"):
        raise_err(ERR_SCOPE_ITEM_INVALID_STATE,
                  "An EXCLUDED scope item cannot be excluded again")
    case = db.audit_cases[item["audit_case_id"]]
    if case["status"] != "SCOPE_NEGOTIATION":
        raise_err(ERR_AUDIT_CASE_INVALID_STATE,
                  "Scope items may only be excluded while the case is in "
                  "SCOPE_NEGOTIATION")
    was_confirmed = item["scope_status"] == "CONFIRMED"
    item["scope_status"] = "EXCLUDED"
    svc.touch(item)
    if was_confirmed:
        svc.recompute_case_rollups(case)
        svc.touch(case)
    return success_object(item)


@bp.post("/sam/audit-scope-items/<sid>/vendor-finding")
def record_vendor_finding(sid):
    require_role(["VendorAuditor"])
    item = _get_scope_item(sid)
    if item["scope_status"] != "CONFIRMED":
        raise_err(ERR_SCOPE_ITEM_INVALID_STATE,
                  "Vendor findings may only be recorded on CONFIRMED items")
    case = db.audit_cases[item["audit_case_id"]]
    if case["status"] != "FINDINGS_REVIEW":
        raise_err(ERR_AUDIT_CASE_INVALID_STATE,
                  "Vendor findings may only be recorded while the case is "
                  "in FINDINGS_REVIEW")
    pos = svc.position_for_product(item["product_id"])
    item["vendor_finding_amount_cents"] = svc.vendor_finding_line_cents(pos)
    svc.touch(item)
    if pos["position_basis"] == "SELF_AUDIT":
        pos["position_basis"] = "VENDOR_MEASURED"
        svc.touch(pos)
    svc.recompute_case_rollups(case)
    svc.touch(case)
    return success_object(item)
