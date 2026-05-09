"""Per-entity assertions for the Research Funding API.

Reflects PRD §2.4 (common resource properties), §2.8 (precision), §2.10 (audit log),
and §2.11 (enumerations). Each assertion validates the entity's response shape against
the contract — used in both tests and fixtures for sanity checks.
"""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


# Allowed enum sets (PRD §2.11, §3) ----------------------------------------------------------
_FUNDING_SOURCES = ["NATIONAL", "PROVINCIAL", "ENTERPRISE", "INTERNAL"]
_BUDGET_CATEGORIES = ["PERSONNEL", "EQUIPMENT", "MATERIALS", "TRAVEL", "CONFERENCE", "OUTSOURCING"]
_RESIDUAL_ACTIONS = ["RETURN", "REALLOCATE", "CARRYOVER"]
_RECOMMENDATIONS = ["APPROVE", "REJECT", "REVISE"]
_ALLOCATION_BASES = ["DIRECT_COST", "PERSONNEL_COST", "FLOOR_AREA"]
_SEVERITIES = ["BLOCK", "ESCALATE", "WARN"]
_FINDING_SEVERITIES = ["LOW", "MEDIUM", "HIGH"]

_PROJECT_STATUSES = ["DRAFT", "UNDER_REVIEW", "APPROVED", "ACTIVE", "CLOSING", "CLOSED", "REJECTED"]
_BUDGET_ITEM_STATUSES = ["PENDING", "APPROVED", "LOCKED"]
_BUDGET_ADJ_STATUSES = ["DRAFT", "UNDER_REVIEW", "APPROVED", "REJECTED"]
_REIMB_STATUSES = ["DRAFT", "SUBMITTED", "UNDER_REVIEW", "APPROVED", "PAID", "REJECTED"]
_AUDIT_STATUSES = ["DRAFT", "SUBMITTED", "RECTIFICATION_REQUIRED", "CLOSED"]
_DECISION_STATES = ["PENDING", "APPROVED", "REJECTED"]
_AUDIT_LOG_ACTIONS = ["CREATE", "UPDATE", "APPROVE", "REJECT", "REWORK", "PAY", "LOCK", "ADJUST"]
_AUDIT_LOG_SUBJECTS = ["BUDGET_ITEM", "BUDGET_ADJUSTMENT", "REIMBURSEMENT"]


def _assert_common_mutable(data: dict, name: str = "entity"):
    """Helpers shared across mutable (common_fields=true) entities."""
    assert is_valid_uuid(data.get("id", "")), f"{name}.id must be valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), f"{name}.created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), f"{name}.updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, \
        f"{name}.version must be int >= 1, got {data.get('version')!r}"


def _assert_common_append_only(data: dict, name: str = "entity"):
    """Helpers shared across append-only (common_fields=false) entities."""
    assert is_valid_uuid(data.get("id", "")), f"{name}.id must be valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), f"{name}.created_at must be ISO 8601"


# --- Project ---------------------------------------------------------------------------------

def assert_project(data: dict):
    """Assert a Project response matches PRD §3.1 + §2.4 contract."""
    _assert_common_mutable(data, "Project")
    assert isinstance(data["title"], str) and 1 <= len(data["title"]) <= 200
    assert isinstance(data["principal_investigator_id"], str) and len(data["principal_investigator_id"]) > 0
    assert isinstance(data["department_id"], str) and len(data["department_id"]) > 0
    assert data["funding_source"] in _FUNDING_SOURCES
    assert isinstance(data["proposal_text"], str)
    assert isinstance(data["requested_amount"], (int, float)) and data["requested_amount"] >= 0
    # project_code is null until APPROVED transition
    if data.get("project_code") is not None:
        assert isinstance(data["project_code"], str)
        # Format: YYYY-ABBR-NNNN (e.g., 2026-NTL-0007)
        parts = data["project_code"].split("-")
        assert len(parts) == 3, f"project_code must be YYYY-ABBR-NNNN, got {data['project_code']!r}"
        assert len(parts[0]) == 4 and parts[0].isdigit()
        assert parts[1] in ("NTL", "PRV", "ENT", "INT")
        assert len(parts[2]) == 4 and parts[2].isdigit()
    assert isinstance(data["planned_start_date"], int)
    assert isinstance(data["planned_end_date"], int)
    assert data["status"] in _PROJECT_STATUSES
    # Computed monetary fields (may be 0/null in DRAFT)
    if "total_budget" in data and data["total_budget"] is not None:
        assert isinstance(data["total_budget"], (int, float)) and data["total_budget"] >= 0
    if "total_reimbursed" in data and data["total_reimbursed"] is not None:
        assert isinstance(data["total_reimbursed"], (int, float)) and data["total_reimbursed"] >= 0


# --- PeerReview (append-only) ----------------------------------------------------------------

def assert_peer_review(data: dict):
    """Assert a PeerReview response matches PRD §3.1 — peer reviews are immutable
    once written (PRD §3.1: 'Peer reviews are immutable once written.')."""
    _assert_common_append_only(data, "PeerReview")
    # Append-only: NO updated_at, NO version
    assert "updated_at" not in data or data.get("updated_at") is None, \
        "PeerReview is append-only and must not carry updated_at"
    assert "version" not in data or data.get("version") is None, \
        "PeerReview is append-only and must not carry version"
    assert is_valid_uuid(data["project_id"])
    assert isinstance(data["reviewer_id"], str) and len(data["reviewer_id"]) > 0
    assert isinstance(data["score"], int) and 0 <= data["score"] <= 100
    assert data["recommendation"] in _RECOMMENDATIONS
    assert isinstance(data["comments"], str)


# --- BudgetItem ------------------------------------------------------------------------------

def assert_budget_item(data: dict):
    _assert_common_mutable(data, "BudgetItem")
    assert is_valid_uuid(data["project_id"])
    assert data["category"] in _BUDGET_CATEGORIES
    assert isinstance(data["requested_amount"], (int, float)) and data["requested_amount"] > 0
    assert data["status"] in _BUDGET_ITEM_STATUSES
    if data.get("approved_amount") is not None:
        assert isinstance(data["approved_amount"], (int, float)) and data["approved_amount"] >= 0
    if "spent_amount" in data and data["spent_amount"] is not None:
        assert isinstance(data["spent_amount"], (int, float)) and data["spent_amount"] >= 0
    if "remaining_amount" in data and data["remaining_amount"] is not None:
        assert isinstance(data["remaining_amount"], (int, float))


# --- BudgetAdjustment ------------------------------------------------------------------------

def assert_budget_adjustment(data: dict):
    _assert_common_mutable(data, "BudgetAdjustment")
    assert is_valid_uuid(data["project_id"])
    assert isinstance(data["line_changes"], list) and len(data["line_changes"]) > 0
    for lc in data["line_changes"]:
        assert isinstance(lc, dict)
        assert "budget_item_id" in lc
        assert "delta_amount" in lc
        assert isinstance(lc["delta_amount"], (int, float))
    assert isinstance(data["justification"], str)
    assert data["pi_decision"] in _DECISION_STATES
    assert data["dept_decision"] in _DECISION_STATES
    assert data["finance_decision"] in _DECISION_STATES
    assert data["status"] in _BUDGET_ADJ_STATUSES


# --- Reimbursement ---------------------------------------------------------------------------

def assert_reimbursement(data: dict):
    _assert_common_mutable(data, "Reimbursement")
    assert is_valid_uuid(data["project_id"])
    assert is_valid_uuid(data["budget_item_id"])
    assert data["expense_category"] in _BUDGET_CATEGORIES
    assert isinstance(data["amount"], (int, float)) and data["amount"] > 0
    assert isinstance(data["invoice_number"], str) and len(data["invoice_number"]) > 0
    assert isinstance(data["invoice_date"], int)
    assert isinstance(data["invoice_authenticated"], bool)
    assert isinstance(data["attachments"], list)
    for att in data["attachments"]:
        assert isinstance(att, dict) and "filename" in att and "kind" in att
    assert isinstance(data.get("vendor_id", ""), str)
    assert data["pi_decision"] in _DECISION_STATES
    assert data["dept_decision"] in _DECISION_STATES
    assert data["finance_decision"] in _DECISION_STATES
    assert isinstance(data["rework_count"], int) and 0 <= data["rework_count"] <= 4
    assert isinstance(data.get("compliance_findings", []), list)
    assert data["status"] in _REIMB_STATUSES


# --- ClosingAudit ----------------------------------------------------------------------------

def assert_closing_audit(data: dict):
    _assert_common_mutable(data, "ClosingAudit")
    assert is_valid_uuid(data["project_id"])
    assert isinstance(data["deliverables"], list)
    for d in data["deliverables"]:
        assert isinstance(d, dict) and "title" in d and "kind" in d
    assert data["residual_fund_action"] in _RESIDUAL_ACTIONS
    assert isinstance(data["audit_findings"], list)
    for f in data["audit_findings"]:
        assert isinstance(f, dict)
        assert f["severity"] in _FINDING_SEVERITIES
        assert isinstance(f["rectified"], bool)
    assert data["status"] in _AUDIT_STATUSES
    if data.get("budget_execution_rate") is not None:
        rate = data["budget_execution_rate"]
        assert isinstance(rate, (int, float)) and rate >= 0
    if data.get("forward_execution_rate") is not None:
        rate = data["forward_execution_rate"]
        assert isinstance(rate, (int, float)) and rate >= 0


# --- IndirectCostAllocation (append-only) ----------------------------------------------------

def assert_indirect_cost_allocation(data: dict):
    """Assert an IndirectCostAllocation row — append-only per PRD §2.4."""
    _assert_common_append_only(data, "IndirectCostAllocation")
    assert "updated_at" not in data or data.get("updated_at") is None, \
        "IndirectCostAllocation is append-only and must not carry updated_at"
    assert "version" not in data or data.get("version") is None, \
        "IndirectCostAllocation is append-only and must not carry version"
    assert isinstance(data["allocation_run_id"], str) and len(data["allocation_run_id"]) > 0
    assert is_valid_uuid(data["project_id"])
    assert data["allocation_base"] in _ALLOCATION_BASES
    assert isinstance(data["allocation_rate"], (int, float)) and data["allocation_rate"] >= 0
    assert isinstance(data["base_value"], (int, float)) and data["base_value"] >= 0
    assert isinstance(data["allocated_amount"], (int, float)) and data["allocated_amount"] >= 0


# --- ComplianceRule --------------------------------------------------------------------------

def assert_compliance_rule(data: dict):
    _assert_common_mutable(data, "ComplianceRule")
    assert isinstance(data["rule_code"], str) and len(data["rule_code"]) > 0
    assert data["applies_to_funding_source"] in _FUNDING_SOURCES + ["ALL"]
    assert data["applies_to_category"] in _BUDGET_CATEGORIES + ["ALL"]
    assert isinstance(data["parameters"], dict)
    assert data["severity"] in _SEVERITIES
    assert isinstance(data["active"], bool)


# --- AuditLog (append-only) ------------------------------------------------------------------

def assert_audit_log(data: dict):
    """Assert an AuditLog row — append-only per PRD §2.4 + §2.10."""
    _assert_common_append_only(data, "AuditLog")
    assert "updated_at" not in data or data.get("updated_at") is None
    assert "version" not in data or data.get("version") is None
    assert data["subject_type"] in _AUDIT_LOG_SUBJECTS
    assert isinstance(data["subject_id"], str) and len(data["subject_id"]) > 0
    assert data["action"] in _AUDIT_LOG_ACTIONS
    assert isinstance(data["actor_role"], str) and len(data["actor_role"]) > 0
    assert isinstance(data["actor_id"], str) and len(data["actor_id"]) > 0
    assert is_iso8601_timestamp(data.get("occurred_at", ""))


# --- Domain invariants -----------------------------------------------------------------------

def assert_budget_item_invariants(item: dict):
    """BudgetItem domain invariants per PRD §3.3 (after mark-paid):
       remaining_amount == approved_amount - spent_amount.
    Skipped for items still in PENDING (no approved_amount yet).
    """
    if item.get("status") == "PENDING":
        return
    approved = item.get("approved_amount") or 0
    spent = item.get("spent_amount") or 0
    remaining = item.get("remaining_amount")
    if remaining is None:
        return
    # Tolerance for floating-point representation of two-decimal monetary values.
    assert abs(remaining - (approved - spent)) < 0.01, (
        f"BudgetItem invariant: remaining_amount ({remaining}) must equal "
        f"approved_amount ({approved}) - spent_amount ({spent})"
    )
    assert remaining >= 0 or item.get("status") == "LOCKED", \
        f"BudgetItem.remaining_amount must be non-negative outside LOCKED state, got {remaining}"


def assert_rate_precision(rate: float, places: int = 4):
    """Execution rates and allocation_rate are recorded to four decimal places (PRD §2.8)."""
    if rate is None:
        return
    s = f"{rate:.10f}"
    # Allow up to 'places' decimals (round_half_up at calculation time means
    # the persisted value should not exceed 'places' decimal places).
    integer_part, _, decimal_part = s.partition(".")
    significant = decimal_part.rstrip("0")
    assert len(significant) <= places, (
        f"Expected rate at most {places} decimals; got {rate} -> {significant} significant digits"
    )


def assert_money_precision(amount: float, places: int = 2):
    """Monetary amounts are recorded to two decimal places (PRD §2.8)."""
    if amount is None:
        return
    s = f"{amount:.10f}"
    integer_part, _, decimal_part = s.partition(".")
    significant = decimal_part.rstrip("0")
    assert len(significant) <= places, (
        f"Expected amount at most {places} decimals; got {amount}"
    )
