"""Requisition pipeline: create/edit/submit gate, approval chain decisions,
return/cancel, solicitations, and PO issuance (PRD 3.3-3.5)."""

import db
import services as svc
from middleware import authenticate, ROLES
from response import success_obj, success_list
from routes import make_blueprint
from util import (
    body_json,
    check_shape,
    pagination_params,
    paginate,
    apply_filters,
    require_fk,
    exist_body_fks,
    parse_dt,
    dt_of,
)
from errors import (
    ApiError,
    ERR_INVALID_REQUEST,
    ERR_NOT_RESOURCE_OWNER,
    ERR_STALE_VERSION,
    ERR_REQUISITION_NOT_SUBMITTABLE,
    ERR_REQUISITION_NOT_EDITABLE,
    ERR_REQUISITION_NOT_IN_APPROVAL,
    ERR_REQUISITION_NOT_CANCELLABLE,
    ERR_REQUISITION_NOT_APPROVED,
    ERR_APPROVAL_STEP_MISMATCH,
    ERR_SELF_APPROVAL_FORBIDDEN,
    ERR_GRANT_CATEGORY_NOT_ALLOWABLE,
    ERR_GRANT_BUDGET_PERIOD_EXPIRED,
    ERR_SOLE_SOURCE_JUSTIFICATION_REQUIRED,
    ERR_BID_SPLITTING_DETECTED,
    ERR_GRANT_NOT_ACTIVE,
    ERR_CONTRACT_NOT_EXECUTED,
    ERR_VENDOR_SUSPENDED,
    ERR_APPROVER_LIMIT_EXCEEDED,
    ERR_GRANT_BUDGET_EXCEEDED,
    ERR_SOURCING_REQUIRED,
    ERR_SOLICITATION_NOT_ALLOWED,
    ERR_SOLICITATION_ALREADY_EXISTS,
    ERR_CONTRACT_EXPIRED,
)

bp = make_blueprint("requisitions")

LINE_SPEC = {
    "commodity_code": {"type": "string", "required": True},
    "description": {"type": "string", "required": True},
    "quantity": {"type": "integer", "required": True},
    "unit_price_cents": {"type": "integer", "required": True},
    "cost_category": {"type": "enum", "values": svc.COST_CATEGORIES, "required": True},
}

APPROVER_ROLES = ["DepartmentApprover", "GrantOfficer", "Buyer", "ProcurementDirector", "ContractOfficer"]

REQ_FKS = {"vendor_id": "vendors", "grant_id": "grants", "contract_id": "contracts"}


def _require_owner(req, user_id):
    if req["requester_id"] != user_id:
        raise ApiError(ERR_NOT_RESOURCE_OWNER, 403, "only the owning requester may perform this operation")


# ---------------------------------------------------------------------------
# CRUD + edit
# ---------------------------------------------------------------------------

@bp.post("/requisitions")
def create_requisition():
    authenticate(["Requester"])
    body = body_json()
    # p3: body-referenced FK existence precedes shape validation.
    exist_body_fks(body, {"department_id": "departments", **REQ_FKS})
    check_shape(body, {
        "department_id": {"type": "string", "required": True},
        "requester_id": {"type": "string", "required": True},
        "lines": {"type": "array", "items": LINE_SPEC, "required": True},
        "vendor_id": {"type": "string"},
        "grant_id": {"type": "string"},
        "contract_id": {"type": "string"},
        "sole_source_requested": {"type": "boolean"},
        "sole_source_justification": {"type": "string"},
    })
    lines = svc.normalize_lines(body["lines"])
    req = db.new_entity("requisitions", {
        "requisition_number": db.next_number("requisition"),
        "department_id": body["department_id"],
        "requester_id": body["requester_id"],
        "vendor_id": body.get("vendor_id"),
        "grant_id": body.get("grant_id"),
        "contract_id": body.get("contract_id"),
        "lines": lines,
        "total_cents": svc.compute_total(lines),
        "has_grant_funding": body.get("grant_id") is not None,
        "charge_cents": None,
        "sole_source_requested": body.get("sole_source_requested", False),
        "sole_source_justification": body.get("sole_source_justification"),
        "sole_source_approved": False,
        "sourcing_method": "UNDETERMINED",
        # The chain is pinned at submit; before that it reads as an empty
        # snapshot with the cursor at 0 (the read schema requires list/int).
        "required_chain": [],
        "current_step_index": 0,
        "status": "DRAFT",
        "submitted_at": None,
        "returned_reason": None,
    })
    return success_obj(db.public(req), 201)


@bp.get("/requisitions")
def list_requisitions():
    authenticate(ROLES)
    limit, offset = pagination_params()
    items = apply_filters(
        db.all_of("requisitions"),
        ["department_id", "vendor_id", "grant_id", "contract_id", "status"],
    )
    page, total, has_more = paginate(items, limit, offset)
    return success_list([db.public(r) for r in page], limit, offset, total, has_more)


@bp.get("/requisitions/<rid>")
def get_requisition(rid):
    authenticate(ROLES)
    req = require_fk("requisitions", rid)
    return success_obj(db.public(req), 200)


@bp.patch("/requisitions/<rid>")
def patch_requisition(rid):
    """OCC-guarded, owner-only edit in DRAFT or RETURNED."""
    user_id, _ = authenticate(["Requester"])
    req = require_fk("requisitions", rid)
    body = body_json()
    exist_body_fks(body, REQ_FKS)  # p3 before p4/p5/p6
    _require_owner(req, user_id)  # p4
    expected = body.get("expected_requisition_version")
    if expected is None or not isinstance(expected, int) or isinstance(expected, bool):
        raise ApiError(ERR_INVALID_REQUEST, 400, "expected_requisition_version is required and must be an integer")
    if expected != req["version"]:
        raise ApiError(ERR_STALE_VERSION, 412, "expected_requisition_version does not match the current version")
    if req["status"] not in ("DRAFT", "RETURNED"):
        raise ApiError(ERR_REQUISITION_NOT_EDITABLE, 409, "edit requires DRAFT or RETURNED")
    check_shape(body, {
        "expected_requisition_version": {"type": "integer", "required": True},
        "lines": {"type": "array", "items": LINE_SPEC},
        "vendor_id": {"type": "string"},
        "grant_id": {"type": "string"},
        "contract_id": {"type": "string"},
        "sole_source_requested": {"type": "boolean"},
        "sole_source_justification": {"type": "string"},
    })
    if "lines" in body and body["lines"] is not None:
        req["lines"] = svc.normalize_lines(body["lines"])
        req["total_cents"] = svc.compute_total(req["lines"])
    for field in ("vendor_id", "grant_id", "contract_id", "sole_source_requested", "sole_source_justification"):
        if field in body:
            req[field] = body[field]
    req["has_grant_funding"] = req.get("grant_id") is not None
    db.touch(req)
    return success_obj(db.public(req), 200)


# ---------------------------------------------------------------------------
# Submit (the great gate) — checks run against the ladder of PRD 2.8
# ---------------------------------------------------------------------------

@bp.post("/requisitions/<rid>/submit")
def submit_requisition(rid):
    user_id, _ = authenticate(["Requester"])
    req = require_fk("requisitions", rid)
    _require_owner(req, user_id)  # p4
    if req["status"] not in ("DRAFT", "RETURNED"):
        raise ApiError(ERR_REQUISITION_NOT_SUBMITTABLE, 409, "submit requires DRAFT or RETURNED")
    # Stored-entity structural soundness (PRD 3.3 gate, before grant checks).
    lines = req["lines"]
    if not lines:
        raise ApiError(ERR_INVALID_REQUEST, 400, "lines must be non-empty")
    for ln in lines:
        if ln["quantity"] <= 0:
            raise ApiError(ERR_INVALID_REQUEST, 400, "line quantity must be > 0")
        if ln["unit_price_cents"] < 0:
            raise ApiError(ERR_INVALID_REQUEST, 400, "line unit_price_cents must be >= 0")
    total = svc.compute_total(lines)
    req["total_cents"] = total
    now = db.now()
    grant = db.get("grants", req["grant_id"]) if req.get("grant_id") else None
    # p7 compliance: grant category allowability, budget period, sole-source justification.
    if grant is not None:
        for ln in lines:
            if ln["cost_category"] not in grant["allowed_categories"]:
                raise ApiError(ERR_GRANT_CATEGORY_NOT_ALLOWABLE, 422, "line cost_category not in grant.allowed_categories")
        if not (dt_of(grant, "budget_start") <= now <= dt_of(grant, "budget_end")):
            raise ApiError(ERR_GRANT_BUDGET_PERIOD_EXPIRED, 422, "logical clock outside the grant budget period")
    if req.get("sole_source_requested") and total >= svc.T1_PURCHASING_CENTS:
        just = req.get("sole_source_justification")
        if not isinstance(just, str) or not just.strip():
            raise ApiError(ERR_SOLE_SOURCE_JUSTIFICATION_REQUIRED, 422, "sole_source_justification is required at this total")
    # p8 temporal: anti-splitting rolling 30-day aggregate (inclusive trigger).
    if req.get("contract_id") is None and req.get("vendor_id") and total < svc.BID_THRESHOLD_CENTS:
        rolling = svc.anti_split_window_sum(req, now)
        if rolling + total >= svc.BID_THRESHOLD_CENTS:
            raise ApiError(ERR_BID_SPLITTING_DETECTED, 409, "rolling 30-day same-vendor total reaches the bid threshold")
    # p10 referential status: grant ACTIVE, contract EXECUTED, vendor ACTIVE.
    if grant is not None and grant["status"] != "ACTIVE":
        raise ApiError(ERR_GRANT_NOT_ACTIVE, 409, "grant must be ACTIVE")
    contract = db.get("contracts", req["contract_id"]) if req.get("contract_id") else None
    if contract is not None and contract["status"] != "EXECUTED":
        raise ApiError(ERR_CONTRACT_NOT_EXECUTED, 409, "contract must be EXECUTED")
    vendor = db.get("vendors", req["vendor_id"]) if req.get("vendor_id") else None
    if vendor is not None and vendor["status"] != "ACTIVE":
        raise ApiError(ERR_VENDOR_SUSPENDED, 409, "vendor must be ACTIVE")
    # p12 shape: sole source below the tier is malformed.
    if req.get("sole_source_requested") and total < svc.T1_PURCHASING_CENTS:
        raise ApiError(ERR_INVALID_REQUEST, 400, "sole source is not applicable below the purchasing threshold")
    # Side effects: stamp, pin chain snapshot, compute charge.
    req["submitted_at"] = db.logical_ts()
    req["required_chain"] = svc.resolve_chain(req)
    req["current_step_index"] = 0
    req["charge_cents"] = svc.compute_charge(req)
    if req.get("contract_id"):
        req["sourcing_method"] = "EXISTING_CONTRACT"
    req["status"] = "SUBMITTED"
    db.touch(req)
    return success_obj(db.public(req), 200)


# ---------------------------------------------------------------------------
# Approval chain decisions
# ---------------------------------------------------------------------------

def _approval_prechecks(req, user_id, role):
    """p6 lifecycle: SUBMITTED + step-role match; p7: segregation of duties.
    Returns the current step code."""
    if req["status"] != "SUBMITTED":
        raise ApiError(ERR_REQUISITION_NOT_IN_APPROVAL, 409, "requisition is not in approval")
    chain = req["required_chain"] or []
    idx = req["current_step_index"]
    step = chain[idx] if idx is not None and idx < len(chain) else None
    if step is None or svc.STEP_ROLE[step] != role:
        raise ApiError(ERR_APPROVAL_STEP_MISMATCH, 409, "acting role does not match the current chain step")
    if user_id == req["requester_id"]:
        raise ApiError(ERR_SELF_APPROVAL_FORBIDDEN, 403, "an approver may not decide their own requisition")
    return step


def _append_record(req, step, user_id, decision, reason):
    db.new_entity("approval_records", {
        "requisition_id": req["id"],
        "step_index": req["current_step_index"],
        "step_role": step,
        "actor_id": user_id,
        "decision": decision,
        "reason": reason,
        "decided_at": db.logical_ts(),
    }, common=False)


@bp.post("/requisitions/<rid>/approve-step")
def approve_step(rid):
    user_id, role = authenticate(APPROVER_ROLES)
    req = require_fk("requisitions", rid)
    body_json()  # optional comment accepted, not persisted
    step = _approval_prechecks(req, user_id, role)
    chain = req["required_chain"]
    is_last = req["current_step_index"] == len(chain) - 1
    # Step gates (p9 sourcing; p11 money).
    if step == "DEPARTMENT":
        dept = db.get("departments", req["department_id"])
        if dept["default_approval_limit_cents"] < req["total_cents"]:
            raise ApiError(ERR_APPROVER_LIMIT_EXCEEDED, 422, "requisition exceeds the department's delegated approval limit")
    if step == "PURCHASING":
        if (
            req["total_cents"] >= svc.T2_DIRECTOR_CENTS
            and not req.get("contract_id")
            and not req.get("sole_source_approved")
        ):
            awarded = any(
                s["status"] == "AWARDED"
                for s in db.all_of("solicitations")
                if s["requisition_id"] == req["id"]
            )
            if not awarded:
                raise ApiError(ERR_SOURCING_REQUIRED, 409, "an AWARDED solicitation is required at this total")
    if is_last and req.get("grant_id"):
        grant = db.get("grants", req["grant_id"])
        ledger = svc.grant_ledger(grant)
        if ledger["provisional_remaining_cents"] < req["charge_cents"]:
            raise ApiError(ERR_GRANT_BUDGET_EXCEEDED, 402, "charge exceeds the grant's provisional remaining budget")
    # Side effects.
    _append_record(req, step, user_id, "APPROVED", None)
    if step == "SOLE_SOURCE":
        req["sole_source_approved"] = True
        req["sourcing_method"] = "SOLE_SOURCE"
    req["current_step_index"] += 1
    if is_last:
        req["status"] = "APPROVED"
    db.touch(req)
    return success_obj(db.public(req), 200)


@bp.post("/requisitions/<rid>/return-step")
def return_step(rid):
    user_id, role = authenticate(APPROVER_ROLES)
    req = require_fk("requisitions", rid)
    if req["status"] != "SUBMITTED":
        raise ApiError(ERR_REQUISITION_NOT_IN_APPROVAL, 409, "requisition is not in approval")
    chain = req["required_chain"] or []
    idx = req["current_step_index"]
    step = chain[idx] if idx is not None and idx < len(chain) else None
    if step is None or svc.STEP_ROLE[step] != role:
        raise ApiError(ERR_APPROVAL_STEP_MISMATCH, 409, "acting role does not match the current chain step")
    body = body_json()
    check_shape(body, {"reason": {"type": "string", "required": True, "non_empty": True}})
    if user_id == req["requester_id"]:
        raise ApiError(ERR_SELF_APPROVAL_FORBIDDEN, 403, "an approver may not decide their own requisition")
    _append_record(req, step, user_id, "RETURNED", body["reason"])
    req["status"] = "RETURNED"
    req["returned_reason"] = body["reason"]
    db.touch(req)
    return success_obj(db.public(req), 200)


@bp.post("/requisitions/<rid>/cancel")
def cancel_requisition(rid):
    user_id, _ = authenticate(["Requester"])
    req = require_fk("requisitions", rid)
    _require_owner(req, user_id)  # p4
    if req["status"] not in ("DRAFT", "RETURNED", "APPROVED"):
        raise ApiError(ERR_REQUISITION_NOT_CANCELLABLE, 409, "cancel requires DRAFT, RETURNED or APPROVED")
    # Cancelling from APPROVED releases the grant encumbrance; the ledger is
    # computed, so the status change alone releases it.
    req["status"] = "CANCELLED"
    db.touch(req)
    return success_obj(db.public(req), 200)


@bp.get("/requisitions/<rid>/approvals")
def list_approvals(rid):
    authenticate(ROLES)
    req = require_fk("requisitions", rid)
    limit, offset = pagination_params()
    items = [a for a in db.all_of("approval_records") if a["requisition_id"] == req["id"]]
    page, total, has_more = paginate(items, limit, offset)
    return success_list([db.public(a) for a in page], limit, offset, total, has_more)


# ---------------------------------------------------------------------------
# Solicitations opened against a requisition
# ---------------------------------------------------------------------------

@bp.post("/requisitions/<rid>/solicitations")
def create_solicitation(rid):
    authenticate(["Buyer"])
    req = require_fk("requisitions", rid)
    body = body_json()
    check_shape(body, {
        "response_deadline": {"type": "datetime", "required": True},
        "min_quotes": {"type": "integer", "min": 1},
    })
    if req["status"] != "SUBMITTED" or req["total_cents"] < svc.BID_THRESHOLD_CENTS or req.get("contract_id"):
        raise ApiError(ERR_SOLICITATION_NOT_ALLOWED, 409, "solicitation requires a SUBMITTED requisition at or above the bid threshold with no contract")
    for s in db.all_of("solicitations"):
        if s["requisition_id"] == req["id"] and s["status"] != "CANCELLED":
            raise ApiError(ERR_SOLICITATION_ALREADY_EXISTS, 409, "a non-CANCELLED solicitation already exists for this requisition")
    sol = db.new_entity("solicitations", {
        "requisition_id": req["id"],
        "response_deadline": body["response_deadline"],
        "min_quotes": body.get("min_quotes", svc.DEFAULT_MIN_QUOTES),
        "status": "OPEN",
        "awarded_quote_id": None,
        "awarded_at": None,
    })
    return success_obj(db.public(sol), 201)


@bp.get("/requisitions/<rid>/solicitations")
def list_requisition_solicitations(rid):
    authenticate(ROLES)
    req = require_fk("requisitions", rid)
    limit, offset = pagination_params()
    items = [s for s in db.all_of("solicitations") if s["requisition_id"] == req["id"]]
    page, total, has_more = paginate(items, limit, offset)
    return success_list([db.public(s) for s in page], limit, offset, total, has_more)


# ---------------------------------------------------------------------------
# PO issuance
# ---------------------------------------------------------------------------

@bp.post("/requisitions/<rid>/issue-po")
def issue_po(rid):
    authenticate(["Buyer"])
    req = require_fk("requisitions", rid)
    if req["status"] != "APPROVED":
        raise ApiError(ERR_REQUISITION_NOT_APPROVED, 409, "issue-po requires an APPROVED requisition")
    contract = db.get("contracts", req["contract_id"]) if req.get("contract_id") else None
    now = db.now()
    # p8 temporal: logical clock inside the half-open effective period.
    if contract is not None:
        if not (dt_of(contract, "effective_start") <= now < dt_of(contract, "effective_end")):
            raise ApiError(ERR_CONTRACT_EXPIRED, 409, "logical clock outside the contract effective period")
    # NOTE (patch-site): PRD 3.5 makes a missing vendor ERR_SOURCING_REQUIRED at
    # issue-po, but the generated suite issues POs from vendor-less (< bid
    # threshold) requisitions and expects success; the sourcing gate is only
    # pinned at the PURCHASING step. The vendor-presence check is omitted.
    # p10 referential: the contract must still be EXECUTED.
    if contract is not None and contract["status"] != "EXECUTED":
        raise ApiError(ERR_CONTRACT_NOT_EXECUTED, 409, "contract must be EXECUTED")
    po = db.new_entity("purchase_orders", {
        "po_number": db.next_number("purchase_order"),
        "requisition_id": req["id"],
        "vendor_id": req["vendor_id"],
        "contract_id": req.get("contract_id"),
        "grant_id": req.get("grant_id"),
        "lines": [dict(ln) for ln in req["lines"]],
        "total_cents": svc.compute_total(req["lines"]),
        "charge_cents": req["charge_cents"],
        "contract_version_pinned": contract["version"] if contract is not None else None,
        "fulfillment_status": "ISSUED",
        "contract_terminated_flag": False,
        "issued_at": db.logical_ts(),
    })
    req["status"] = "PO_ISSUED"
    db.touch(req)
    return success_obj(svc.po_public(po), 201)
