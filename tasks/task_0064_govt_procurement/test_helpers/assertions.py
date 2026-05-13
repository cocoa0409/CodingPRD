"""Entity assertions and domain invariant checkers.

Validates the response-body shape implementers must return for each
entity. Field names match PRD §2.11 / §3 exactly (e.g.,
'registration_status', 'bid_status', 'amendment_round', 'award_amount_cents',
'frozen_reason'). PRD §2.4 mandates that EvaluationCommittee,
ContractAmendment, AuditLog, and ClockState are append-only — they
carry only id + created_at and MUST omit updated_at and version.
"""
from __future__ import annotations
from typing import Any, Dict

from prd_bench_local_runner.testing import (
    is_iso8601_timestamp,
    is_valid_uuid,
)


# ===========================================================================
# Common helpers
# ===========================================================================
def _assert_versioned_common(data: Dict[str, Any], label: str) -> None:
    """PRD §2.4: "Every persisted entity carries a server-minted id
    field that is a freshly generated UUID with no type prefix, along
    with a created_at timestamp in ISO 8601 UTC with three fractional
    digits. Entities marked as carrying common fields additionally
    carry updated_at ... and version (a non-negative integer that
    starts at the value implied by the entity's initial creation and
    increments by one on every mutation)."
    """
    assert is_valid_uuid(data.get("id", "")), (
        f"{label}.id must be a UUID, got {data.get('id')!r}"
    )
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"{label}.created_at must be ISO 8601 UTC, got {data.get('created_at')!r}"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"{label}.updated_at must be ISO 8601 UTC, got {data.get('updated_at')!r}"
    )
    assert isinstance(data.get("version"), int) and data["version"] >= 0, (
        f"{label}.version must be non-negative int, got {data.get('version')!r}"
    )


def _assert_append_only_common(data: Dict[str, Any], label: str) -> None:
    """PRD §2.4: "Three entities are intentionally lighter:
    EvaluationCommittee, ContractAmendment, AuditLog, and ClockState
    carry only id and created_at — neither updated_at nor version is
    exposed on these resources."""
    assert is_valid_uuid(data.get("id", "")), (
        f"{label}.id must be a UUID, got {data.get('id')!r}"
    )
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"{label}.created_at must be ISO 8601 UTC, got {data.get('created_at')!r}"
    )
    assert "updated_at" not in data, (
        f"{label} is append-only — must omit updated_at (PRD §2.4); "
        f"got {data.get('updated_at')!r}"
    )
    assert "version" not in data, (
        f"{label} is append-only — must omit version (PRD §2.4); "
        f"got {data.get('version')!r}"
    )


# ===========================================================================
# Supplier
# ===========================================================================
SUPPLIER_STATUSES = {"PENDING", "VERIFIED", "BLACKLISTED", "REVOKED"}


def assert_supplier(data: Dict[str, Any]) -> None:
    _assert_versioned_common(data, "Supplier")
    assert isinstance(data.get("legal_name"), str) and data["legal_name"], (
        "Supplier.legal_name must be non-empty string"
    )
    assert isinstance(data.get("tax_id"), str) and data["tax_id"], (
        "Supplier.tax_id must be non-empty string"
    )
    assert data.get("registration_status") in SUPPLIER_STATUSES, (
        f"Supplier.registration_status invalid: "
        f"{data.get('registration_status')!r}"
    )
    score = data.get("credit_score")
    assert isinstance(score, int) and 0 <= score <= 1000, (
        f"Supplier.credit_score must be 0..1000 int, got {score!r}"
    )
    bl = data.get("blacklist_until", None)
    assert bl is None or is_iso8601_timestamp(bl), (
        f"Supplier.blacklist_until must be null or ISO 8601, got {bl!r}"
    )
    quals = data.get("qualifications", [])
    assert isinstance(quals, list), (
        f"Supplier.qualifications must be list, got {type(quals)}"
    )


# ===========================================================================
# ProcurementPlan
# ===========================================================================
PLAN_STATUSES = {
    "DRAFT", "UNDER_REVIEW", "PUBLISHED",
    "AMENDING", "ARCHIVED", "REJECTED",
}


def assert_procurement_plan(data: Dict[str, Any]) -> None:
    _assert_versioned_common(data, "ProcurementPlan")
    assert isinstance(data.get("agency_id"), str) and data["agency_id"], (
        "ProcurementPlan.agency_id must be non-empty string"
    )
    fy = data.get("fiscal_year")
    assert isinstance(fy, int) and 2000 <= fy <= 2100, (
        f"ProcurementPlan.fiscal_year must be int 2000..2100, got {fy!r}"
    )
    assert data.get("status") in PLAN_STATUSES, (
        f"ProcurementPlan.status invalid: {data.get('status')!r}"
    )
    assert isinstance(data.get("total_budget_cents"), int), (
        "ProcurementPlan.total_budget_cents must be int"
    )
    assert isinstance(data.get("amendment_round"), int), (
        "ProcurementPlan.amendment_round must be int"
    )
    pub_at = data.get("published_at", None)
    assert pub_at is None or is_iso8601_timestamp(pub_at), (
        f"ProcurementPlan.published_at must be null or ISO 8601, got {pub_at!r}"
    )


# ===========================================================================
# PlanItem
# ===========================================================================
PLAN_ITEM_STATUSES = {
    "PROPOSED", "APPROVED", "REJECTED",
    "PUBLISHED", "EXECUTED", "CANCELLED",
}
PLAN_ITEM_CATEGORIES = {"GOODS", "SERVICES", "WORKS"}


def assert_plan_item(data: Dict[str, Any]) -> None:
    _assert_versioned_common(data, "PlanItem")
    assert isinstance(data.get("plan_id"), str), "PlanItem.plan_id must be string"
    assert isinstance(data.get("title"), str) and data["title"], (
        "PlanItem.title must be non-empty string"
    )
    assert data.get("category") in PLAN_ITEM_CATEGORIES, (
        f"PlanItem.category invalid: {data.get('category')!r}"
    )
    budget = data.get("budget_cents")
    assert isinstance(budget, int) and budget > 0, (
        f"PlanItem.budget_cents must be positive int, got {budget!r}"
    )
    assert data.get("item_status") in PLAN_ITEM_STATUSES, (
        f"PlanItem.item_status invalid: {data.get('item_status')!r}"
    )
    exec_amt = data.get("executed_amount_cents")
    assert isinstance(exec_amt, int) and exec_amt >= 0, (
        f"PlanItem.executed_amount_cents must be non-negative int, "
        f"got {exec_amt!r}"
    )


# ===========================================================================
# Project
# ===========================================================================
PROJECT_STATUSES = {
    "DRAFT", "PRESCREEN_OPEN", "BIDDING_OPEN", "BIDDING_CLOSED",
    "EVALUATING", "AWARDED", "CONTRACT_SIGNED", "CANCELLED", "FROZEN",
}
PROJECT_EVAL_METHODS = {"LOWEST_PRICE", "COMPREHENSIVE_SCORING"}
PROJECT_FROZEN_REASONS = {None, "COMPLAINT_UPHELD", "REGULATORY_HOLD"}


def assert_project(data: Dict[str, Any]) -> None:
    _assert_versioned_common(data, "Project")
    assert isinstance(data.get("plan_item_id"), str)
    assert isinstance(data.get("title"), str) and data["title"]
    assert data.get("project_status") in PROJECT_STATUSES, (
        f"Project.project_status invalid: {data.get('project_status')!r}"
    )
    assert data.get("evaluation_method") in PROJECT_EVAL_METHODS, (
        f"Project.evaluation_method invalid: {data.get('evaluation_method')!r}"
    )
    for ts_field in ("bid_submission_deadline", "query_window_close_at",
                     "bid_opening_at"):
        assert is_iso8601_timestamp(data.get(ts_field, "")), (
            f"Project.{ts_field} must be ISO 8601, got {data.get(ts_field)!r}"
        )
    est = data.get("estimated_value_cents")
    assert isinstance(est, int) and est > 0, (
        f"Project.estimated_value_cents must be positive int, got {est!r}"
    )
    quals = data.get("required_qualifications", [])
    assert isinstance(quals, list)
    fr = data.get("frozen_reason", None)
    assert fr in PROJECT_FROZEN_REASONS, (
        f"Project.frozen_reason invalid: {fr!r}"
    )


# ===========================================================================
# TenderDocument
# ===========================================================================
TENDER_DOC_STATUSES = {
    "DRAFT", "PUBLISHED", "CLARIFYING", "AMENDING", "SUPERSEDED",
}


def assert_tender_document(data: Dict[str, Any]) -> None:
    # PRD §2.4 declares TenderDocument carries the common fields. The
    # domain-level `version` here doubles as the document version counter
    # (PRD §3.4: "The document enters DRAFT with a domain-level version of
    # 1"), and PRD §2.5 distinguishes it from the OCC version pointer.
    assert is_valid_uuid(data.get("id", "")), "TenderDocument.id must be UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        "TenderDocument.created_at must be ISO 8601"
    )
    assert isinstance(data.get("project_id"), str)
    assert isinstance(data.get("template_id"), str) and data["template_id"]
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"TenderDocument.version must be int >= 1, got {data.get('version')!r}"
    )
    assert data.get("doc_status") in TENDER_DOC_STATUSES, (
        f"TenderDocument.doc_status invalid: {data.get('doc_status')!r}"
    )
    assert isinstance(data.get("technical_spec"), str) and data["technical_spec"]
    assert isinstance(data.get("commercial_spec"), str) and data["commercial_spec"]
    assert isinstance(data.get("qualification_requirements"), list)
    assert isinstance(data.get("evaluation_criteria"), dict)
    pinned = data.get("pinned_at", None)
    assert pinned is None or is_iso8601_timestamp(pinned), (
        f"TenderDocument.pinned_at must be null or ISO 8601, got {pinned!r}"
    )


# ===========================================================================
# Bid
# ===========================================================================
BID_STATUSES = {
    "SUBMITTED", "WITHDRAWN", "OPENED", "EVALUATED",
    "AWARDED", "LOST", "DISQUALIFIED",
}


def assert_bid(data: Dict[str, Any]) -> None:
    _assert_versioned_common(data, "Bid")
    assert isinstance(data.get("project_id"), str)
    assert isinstance(data.get("supplier_id"), str)
    assert isinstance(data.get("tender_document_version"), int)
    price = data.get("bid_price_cents")
    assert isinstance(price, int) and price > 0, (
        f"Bid.bid_price_cents must be positive int, got {price!r}"
    )
    raw = data.get("technical_score_raw")
    assert isinstance(raw, int) and raw >= 0, (
        f"Bid.technical_score_raw must be non-negative int, got {raw!r}"
    )
    assert data.get("bid_status") in BID_STATUSES, (
        f"Bid.bid_status invalid: {data.get('bid_status')!r}"
    )
    assert isinstance(data.get("prescreen_passed"), bool), (
        "Bid.prescreen_passed must be boolean"
    )
    fs = data.get("final_score", None)
    assert fs is None or isinstance(fs, (int, float)), (
        f"Bid.final_score must be null or number, got {fs!r}"
    )


# ===========================================================================
# EvaluationCommittee (PRD §2.4: append-only common)
# ===========================================================================
COMMITTEE_STATUSES = {"FORMED", "EVALUATING", "FINALIZED", "DISSOLVED"}


def assert_evaluation_committee(data: Dict[str, Any]) -> None:
    _assert_append_only_common(data, "EvaluationCommittee")
    assert isinstance(data.get("project_id"), str)
    members = data.get("members")
    assert isinstance(members, list) and len(members) >= 3, (
        f"EvaluationCommittee.members must be list of >=3, got {members!r}"
    )
    # PRD §3.7 pins each member object shape.
    for m in members:
        assert isinstance(m, dict) and isinstance(m.get("expert_id"), str), (
            f"committee member must carry expert_id string, got {m!r}"
        )
        assert is_iso8601_timestamp(m.get("selected_at", "")), (
            f"committee member.selected_at must be ISO 8601, got {m!r}"
        )
        assert m.get("conflict_cleared") is True, (
            f"committee member.conflict_cleared must be true, got {m!r}"
        )
    assert isinstance(data.get("selection_seed"), str)
    assert data.get("committee_status") in COMMITTEE_STATUSES, (
        f"EvaluationCommittee.committee_status invalid: "
        f"{data.get('committee_status')!r}"
    )


# ===========================================================================
# Award
# ===========================================================================
AWARD_STATUSES = {"DECIDED", "PUBLISHED", "REVOKED"}


def assert_award(data: Dict[str, Any]) -> None:
    _assert_versioned_common(data, "Award")
    assert isinstance(data.get("project_id"), str)
    assert isinstance(data.get("winning_bid_id"), str)
    assert data.get("award_status") in AWARD_STATUSES, (
        f"Award.award_status invalid: {data.get('award_status')!r}"
    )
    pub = data.get("published_at", None)
    assert pub is None or is_iso8601_timestamp(pub), (
        f"Award.published_at must be null or ISO 8601, got {pub!r}"
    )
    amt = data.get("award_amount_cents")
    assert isinstance(amt, int) and amt > 0, (
        f"Award.award_amount_cents must be positive int, got {amt!r}"
    )


# ===========================================================================
# Contract
# ===========================================================================
CONTRACT_STATUSES = {
    "PENDING_SIGNATURE", "ACTIVE", "AMENDING", "EXECUTED", "TERMINATED",
}


def assert_contract(data: Dict[str, Any]) -> None:
    _assert_versioned_common(data, "Contract")
    assert isinstance(data.get("project_id"), str)
    assert isinstance(data.get("award_id"), str)
    assert isinstance(data.get("supplier_id"), str)
    amt = data.get("contract_amount_cents")
    assert isinstance(amt, int) and amt > 0, (
        f"Contract.contract_amount_cents must be positive int, got {amt!r}"
    )
    assert isinstance(data.get("payment_terms"), str)
    assert data.get("contract_status") in CONTRACT_STATUSES, (
        f"Contract.contract_status invalid: {data.get('contract_status')!r}"
    )
    paid = data.get("paid_amount_cents")
    assert isinstance(paid, int) and paid >= 0, (
        f"Contract.paid_amount_cents must be non-negative int, got {paid!r}"
    )


# ===========================================================================
# ContractAmendment (PRD §2.4: append-only)
# ===========================================================================
def assert_contract_amendment(data: Dict[str, Any]) -> None:
    _assert_append_only_common(data, "ContractAmendment")
    assert isinstance(data.get("contract_id"), str)
    assert isinstance(data.get("delta_amount_cents"), int)
    assert isinstance(data.get("reason"), str) and data["reason"]
    assert is_iso8601_timestamp(data.get("filed_at", "")), (
        "ContractAmendment.filed_at must be ISO 8601"
    )


# ===========================================================================
# Query
# ===========================================================================
QUERY_STATUSES = {"OPEN", "ANSWERED", "EXPIRED"}


def assert_query(data: Dict[str, Any]) -> None:
    _assert_versioned_common(data, "Query")
    assert isinstance(data.get("project_id"), str)
    assert isinstance(data.get("supplier_id"), str)
    assert isinstance(data.get("question"), str) and data["question"]
    assert data.get("query_status") in QUERY_STATUSES, (
        f"Query.query_status invalid: {data.get('query_status')!r}"
    )
    resp = data.get("response", None)
    assert resp is None or isinstance(resp, str), (
        f"Query.response must be null or string, got {resp!r}"
    )


# ===========================================================================
# Complaint
# ===========================================================================
COMPLAINT_STATUSES = {
    "SUBMITTED", "UNDER_REVIEW", "UPHELD", "DISMISSED", "WITHDRAWN",
}
COMPLAINT_SUBJECTS = {"PRESCREEN_RESULT", "EVALUATION", "AWARD", "CONTRACT"}
CORRECTIVE_ACTIONS = {
    None, "REOPEN_PRESCREEN", "REOPEN_EVALUATION",
    "REVOKE_AWARD", "FREEZE_PROJECT",
}


def assert_complaint(data: Dict[str, Any]) -> None:
    _assert_versioned_common(data, "Complaint")
    assert isinstance(data.get("project_id"), str)
    assert isinstance(data.get("complainant_supplier_id"), str)
    assert data.get("subject") in COMPLAINT_SUBJECTS, (
        f"Complaint.subject invalid: {data.get('subject')!r}"
    )
    assert isinstance(data.get("narrative"), str) and data["narrative"]
    assert data.get("complaint_status") in COMPLAINT_STATUSES, (
        f"Complaint.complaint_status invalid: {data.get('complaint_status')!r}"
    )
    da = data.get("decision_at", None)
    assert da is None or is_iso8601_timestamp(da), (
        f"Complaint.decision_at must be null or ISO 8601, got {da!r}"
    )
    ca = data.get("corrective_action", None)
    assert ca in CORRECTIVE_ACTIONS, (
        f"Complaint.corrective_action invalid: {ca!r}"
    )


# ===========================================================================
# AuditLog (PRD §2.4 + §2.8: append-only)
# ===========================================================================
AUDIT_TARGET_TYPES = {"EVALUATION", "COMPLAINT", "CONTRACT", "TENDER", "AWARD"}


def assert_audit_log(data: Dict[str, Any]) -> None:
    _assert_append_only_common(data, "AuditLog")
    assert data.get("target_type") in AUDIT_TARGET_TYPES, (
        f"AuditLog.target_type invalid: {data.get('target_type')!r}"
    )
    assert isinstance(data.get("target_id"), str)
    assert isinstance(data.get("actor_role"), str)
    assert isinstance(data.get("actor_id"), str)
    assert isinstance(data.get("action"), str) and data["action"]
    assert isinstance(data.get("payload"), dict)


# ===========================================================================
# ClockState (PRD §2.4: append-only common)
# ===========================================================================
def assert_clock_state(data: Dict[str, Any]) -> None:
    _assert_append_only_common(data, "ClockState")
    assert is_iso8601_timestamp(data.get("current_time", "")), (
        f"ClockState.current_time must be ISO 8601, got {data.get('current_time')!r}"
    )


__all__ = [
    "assert_supplier",
    "assert_procurement_plan",
    "assert_plan_item",
    "assert_project",
    "assert_tender_document",
    "assert_bid",
    "assert_evaluation_committee",
    "assert_award",
    "assert_contract",
    "assert_contract_amendment",
    "assert_query",
    "assert_complaint",
    "assert_audit_log",
    "assert_clock_state",
    "SUPPLIER_STATUSES",
    "PLAN_STATUSES",
    "PLAN_ITEM_STATUSES",
    "PLAN_ITEM_CATEGORIES",
    "PROJECT_STATUSES",
    "PROJECT_EVAL_METHODS",
    "PROJECT_FROZEN_REASONS",
    "TENDER_DOC_STATUSES",
    "BID_STATUSES",
    "COMMITTEE_STATUSES",
    "AWARD_STATUSES",
    "CONTRACT_STATUSES",
    "QUERY_STATUSES",
    "COMPLAINT_STATUSES",
    "COMPLAINT_SUBJECTS",
    "CORRECTIVE_ACTIONS",
    "AUDIT_TARGET_TYPES",
]
