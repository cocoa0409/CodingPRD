"""BudgetAdjustment — zero-sum reallocation with version-pinned OCC."""

from decimal import Decimal

from common import (
    money_to_json,
    require_field,
    round_money,
    sort_by_created_at,
    stamp_create,
    stamp_update,
    to_decimal,
)
from db import db
from errors import (
    ERR_ADJUSTMENT_NOT_ZERO_SUM,
    ERR_ALREADY_DECIDED,
    ERR_BUDGET_ADJUSTMENT_NOT_FOUND,
    ERR_BUDGET_ITEM_NOT_FOUND,
    ERR_DEPT_DECISION_PENDING,
    ERR_INVALID_INPUT,
    ERR_INVALID_STATE,
    ERR_JUSTIFICATION_TOO_SHORT,
    ERR_NEGATIVE_BUDGET,
    ERR_NOT_PROJECT_OWNER,
    ERR_PROJECT_NOT_ACTIVE,
    ERR_PROJECT_NOT_FOUND,
    ERR_REJECTION_REASON_REQUIRED,
    ERR_STALE_BUDGET_VERSION,
    raise_error,
)
from services.audit_log import append_log


def get_adjustment_or_404(adjustment_id):
    a = db.budget_adjustments.get(adjustment_id)
    if a is None:
        raise_error(ERR_BUDGET_ADJUSTMENT_NOT_FOUND, f"adjustment {adjustment_id} not found")
    return a


def serialize_adjustment(a):
    return {
        "id": a["id"],
        "project_id": a["project_id"],
        "line_changes": [
            {"budget_item_id": lc["budget_item_id"], "delta_amount": money_to_json(lc["delta_amount"])}
            for lc in a["line_changes"]
        ],
        "justification": a["justification"],
        "pi_decision": a["pi_decision"],
        "dept_decision": a["dept_decision"],
        "finance_decision": a["finance_decision"],
        "pinned_budget_versions": dict(a.get("pinned_budget_versions") or {}),
        "rejection_reason": a.get("rejection_reason"),
        "status": a["status"],
        "created_at": a["created_at"],
        "updated_at": a["updated_at"],
        "version": a["version"],
    }


def create_adjustment(actor_id, body):
    project_id = require_field(body, "project_id", str)
    project = db.projects.get(project_id)
    if project is None:
        raise_error(ERR_PROJECT_NOT_FOUND, f"project {project_id} not found")
    if project["principal_investigator_id"] != actor_id:
        raise_error(ERR_NOT_PROJECT_OWNER, "only PI can create adjustment")

    line_changes_raw = require_field(body, "line_changes", list)
    line_changes = []
    for lc in line_changes_raw:
        if not isinstance(lc, dict):
            raise_error(ERR_INVALID_INPUT, "each line_changes entry must be an object")
        bi_id = lc.get("budget_item_id")
        delta = lc.get("delta_amount")
        if not isinstance(bi_id, str) or delta is None:
            raise_error(ERR_INVALID_INPUT, "line_changes entry needs budget_item_id and delta_amount")
        delta_dec = round_money(to_decimal(delta))
        line_changes.append({"budget_item_id": bi_id, "delta_amount": delta_dec})

    justification = require_field(body, "justification", str)

    aid = db.new_id()
    adj = {
        "id": aid,
        "project_id": project_id,
        "line_changes": line_changes,
        "justification": justification,
        "pi_decision": "PENDING",
        "dept_decision": "PENDING",
        "finance_decision": "PENDING",
        "pinned_budget_versions": {},
        "rejection_reason": None,
        "status": "DRAFT",
    }
    stamp_create(adj)
    db.budget_adjustments[aid] = adj
    # Append CREATE audit log
    append_log("BUDGET_ADJUSTMENT", aid, "CREATE", "PrincipalInvestigator", actor_id,
               {}, {"status": "DRAFT", "project_id": project_id})
    return adj


def list_adjustments(project_id=None, status=None):
    items = list(db.budget_adjustments.values())
    if project_id:
        items = [a for a in items if a["project_id"] == project_id]
    if status:
        items = [a for a in items if a["status"] == status]
    return sort_by_created_at(items)


def submit_adjustment(adjustment_id, actor_id):
    a = get_adjustment_or_404(adjustment_id)
    project = db.projects.get(a["project_id"])
    if project is None:
        raise_error(ERR_PROJECT_NOT_FOUND, "project missing")
    if project["principal_investigator_id"] != actor_id:
        raise_error(ERR_NOT_PROJECT_OWNER, "only PI can submit")
    if a["status"] != "DRAFT":
        raise_error(ERR_INVALID_STATE, f"adjustment must be DRAFT to submit (got {a['status']})")
    if project["status"] != "ACTIVE":
        raise_error(ERR_PROJECT_NOT_ACTIVE, "project not ACTIVE")

    # Zero-sum check (within 0.01 tolerance)
    total = Decimal("0.00")
    for lc in a["line_changes"]:
        total += lc["delta_amount"]
    if abs(total) > Decimal("0.01"):
        raise_error(ERR_ADJUSTMENT_NOT_ZERO_SUM, f"deltas sum to {total}")

    # Negativity check
    for lc in a["line_changes"]:
        bi = db.budget_items.get(lc["budget_item_id"])
        if bi is None:
            raise_error(ERR_BUDGET_ITEM_NOT_FOUND, f"budget item {lc['budget_item_id']} not found")
        approved = bi["approved_amount"] if bi["approved_amount"] is not None else Decimal("0.00")
        if approved + lc["delta_amount"] < 0:
            raise_error(ERR_NEGATIVE_BUDGET, "approved_amount + delta_amount < 0")

    # Justification length check
    if len(a["justification"]) < 20:
        raise_error(ERR_JUSTIFICATION_TOO_SHORT, "justification < 20 chars")

    # Capture pinned versions
    pinned = {}
    for lc in a["line_changes"]:
        bi = db.budget_items[lc["budget_item_id"]]
        pinned[bi["id"]] = bi["version"]
    a["pinned_budget_versions"] = pinned
    a["status"] = "UNDER_REVIEW"
    a["pi_decision"] = "APPROVED"
    stamp_update(a)
    return a


def dept_approve_adjustment(adjustment_id, actor_id):
    a = get_adjustment_or_404(adjustment_id)
    if a["status"] != "UNDER_REVIEW":
        raise_error(ERR_INVALID_STATE, f"adjustment not UNDER_REVIEW (got {a['status']})")
    if a["dept_decision"] != "PENDING":
        raise_error(ERR_ALREADY_DECIDED, "dept decision already made")
    a["dept_decision"] = "APPROVED"
    stamp_update(a)
    append_log("BUDGET_ADJUSTMENT", a["id"], "APPROVE", "DepartmentApprover", actor_id,
               {"dept_decision": "PENDING"}, {"dept_decision": "APPROVED"})
    return a


def finance_approve_adjustment(adjustment_id, actor_id):
    a = get_adjustment_or_404(adjustment_id)
    # PRD §3.2: "Two simultaneous finance-approvals racing on the same adjustment
    # serialize on BudgetAdjustment.status: at most one finance-approve succeeds,
    # and the loser receives ERR_ALREADY_DECIDED." When the adjustment has already
    # been finance-approved (or finance-rejected), surface ERR_ALREADY_DECIDED.
    if a["finance_decision"] != "PENDING":
        raise_error(ERR_ALREADY_DECIDED, "finance decision already made")
    if a["status"] != "UNDER_REVIEW":
        raise_error(ERR_INVALID_STATE, f"adjustment not UNDER_REVIEW (got {a['status']})")
    if a["dept_decision"] != "APPROVED":
        raise_error(ERR_DEPT_DECISION_PENDING, "department decision pending")

    pinned = a.get("pinned_budget_versions") or {}
    # Stale version revalidation
    for lc in a["line_changes"]:
        bi = db.budget_items.get(lc["budget_item_id"])
        if bi is None:
            raise_error(ERR_BUDGET_ITEM_NOT_FOUND, f"budget item {lc['budget_item_id']} not found")
        pinned_v = pinned.get(bi["id"])
        if pinned_v is None or bi["version"] != pinned_v:
            raise_error(ERR_STALE_BUDGET_VERSION, f"version mismatch for {bi['id']}")

    # Commit deltas atomically (all preconditions checked)
    project = db.projects[a["project_id"]]
    for lc in a["line_changes"]:
        bi = db.budget_items[lc["budget_item_id"]]
        before = {"approved_amount": money_to_json(bi["approved_amount"]), "version": bi["version"]}
        new_approved = round_money((bi["approved_amount"] or Decimal("0.00")) + lc["delta_amount"])
        bi["approved_amount"] = new_approved
        if bi["spent_amount"] is None:
            bi["spent_amount"] = Decimal("0.00")
        bi["remaining_amount"] = round_money(bi["approved_amount"] - bi["spent_amount"])
        stamp_update(bi)
        after = {"approved_amount": money_to_json(bi["approved_amount"]), "version": bi["version"]}
        append_log("BUDGET_ITEM", bi["id"], "UPDATE", "FinanceOfficer", actor_id, before, after)

    # Recompute project total_budget
    total = Decimal("0.00")
    for bi in db.budget_items.values():
        if bi["project_id"] == project["id"] and bi["approved_amount"] is not None:
            total += bi["approved_amount"]
    project["total_budget"] = round_money(total)
    stamp_update(project)

    a["status"] = "APPROVED"
    a["finance_decision"] = "APPROVED"
    stamp_update(a)
    append_log("BUDGET_ADJUSTMENT", a["id"], "ADJUST", "FinanceOfficer", actor_id,
               {"status": "UNDER_REVIEW"}, {"status": "APPROVED"})
    return a


def reject_adjustment(adjustment_id, actor_id, actor_role, body):
    a = get_adjustment_or_404(adjustment_id)
    if a["status"] != "UNDER_REVIEW":
        raise_error(ERR_INVALID_STATE, f"adjustment not UNDER_REVIEW (got {a['status']})")
    rejection_reason = (body or {}).get("rejection_reason", "")
    if not isinstance(rejection_reason, str) or not rejection_reason.strip():
        raise_error(ERR_REJECTION_REASON_REQUIRED, "rejection_reason required")
    if actor_role == "DepartmentApprover":
        a["dept_decision"] = "REJECTED"
    elif actor_role == "FinanceOfficer":
        a["finance_decision"] = "REJECTED"
    a["rejection_reason"] = rejection_reason
    a["status"] = "REJECTED"
    stamp_update(a)
    append_log("BUDGET_ADJUSTMENT", a["id"], "REJECT", actor_role, actor_id,
               {"status": "UNDER_REVIEW"}, {"status": "REJECTED"})
    return a
