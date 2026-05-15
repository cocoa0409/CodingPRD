"""Entity assertions for the Supply Chain Finance API.

Each assertion validates the dict shape returned by the corresponding
endpoint against the PRD-required fields and value constraints.

PRD §2.4 splits entities into two envelope shapes:
  * MUTABLE entities (``CoreEnterprise``, ``Supplier``,
    ``PayableConfirmation``, ``Receivable``, ``FinancingApplication``,
    ``RepaymentSchedule``, ``CollectionCase``) carry ``id``,
    ``created_at``, ``updated_at``, and ``version``.
  * LEAN entities (``Disbursement``, ``TradeBackgroundVerification``,
    ``AuditLogEntry``) carry only ``id`` and ``created_at``; their
    lifecycle is captured by explicit timestamp fields or the
    ``outcome`` enum.
"""
from __future__ import annotations
from typing import Any, Iterable, Optional

from prd_bench_local_runner.testing import (
    is_iso8601_timestamp,
    is_valid_uuid,
)


# ---------------------------------------------------------------------------
# Common envelope helpers (PRD §2.4)
# ---------------------------------------------------------------------------
def _assert_common_mutable(data: dict, entity_name: str) -> None:
    """PRD §2.4: 'Most entities ... additionally expose created_at,
    updated_at, and a monotonically increasing integer version field
    that is initialised to 1 on creation and incremented by one on every
    server-side mutation.'"""
    assert is_valid_uuid(data.get("id", "")), (
        f"{entity_name}.id must be a valid UUID, got {data.get('id')!r}"
    )
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"{entity_name}.created_at must be ISO 8601 with three fractional "
        f"digits, got {data.get('created_at')!r}"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"{entity_name}.updated_at must be ISO 8601, got "
        f"{data.get('updated_at')!r}"
    )
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"{entity_name}.version must be an int >= 1, got "
        f"{data.get('version')!r}"
    )


def _assert_common_lean(data: dict, entity_name: str) -> None:
    """PRD §2.4: 'Disbursement and TradeBackgroundVerification carry only
    id and created_at (no updated_at, no version).' and 'the
    append-only AuditLogEntry similarly carries id and created_at only,
    with no mutation semantics.'"""
    assert is_valid_uuid(data.get("id", "")), (
        f"{entity_name}.id must be a valid UUID, got {data.get('id')!r}"
    )
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"{entity_name}.created_at must be ISO 8601, got "
        f"{data.get('created_at')!r}"
    )


# ---------------------------------------------------------------------------
# CoreEnterprise (PRD §3.1)
# ---------------------------------------------------------------------------
def assert_core_enterprise(data: dict) -> None:
    _assert_common_mutable(data, "CoreEnterprise")
    assert isinstance(data.get("legal_name"), str) and data["legal_name"]
    assert isinstance(data.get("unified_credit_code"), str)
    assert data["onboarding_status"] in {
        "PENDING", "APPROVED", "REJECTED", "SUSPENDED",
    }, f"CoreEnterprise.onboarding_status invalid: {data.get('onboarding_status')!r}"
    for fld in ("credit_line_total_cents",
                "credit_line_reserved_cents",
                "credit_line_consumed_cents"):
        assert isinstance(data.get(fld), int), (
            f"CoreEnterprise.{fld} must be an int, got {data.get(fld)!r}"
        )
        assert data[fld] >= 0, (
            f"CoreEnterprise.{fld} must be non-negative, got {data[fld]}"
        )
    assert isinstance(data.get("erp_endpoint_url"), str)
    assert isinstance(data.get("joint_liability_flag"), bool), (
        "CoreEnterprise.joint_liability_flag must be a boolean"
    )
    assert data.get("risk_rating") in {"AAA", "AA", "A", "BBB", "BB"}, (
        f"CoreEnterprise.risk_rating invalid: {data.get('risk_rating')!r}"
    )


# ---------------------------------------------------------------------------
# Supplier (PRD §3.2)
# ---------------------------------------------------------------------------
def assert_supplier(data: dict) -> None:
    _assert_common_mutable(data, "Supplier")
    assert isinstance(data.get("legal_name"), str)
    assert isinstance(data.get("unified_credit_code"), str)
    assert isinstance(data.get("tier_to_core"), int)
    assert 1 <= data["tier_to_core"], (
        "Supplier.tier_to_core must be >= 1 (PRD §3.2: 'Tier 1 means the "
        "supplier sells directly to a core enterprise')."
    )
    # parent_supplier_id is null for tier 1, non-null for tier >= 2 per
    # PRD §3.2: "Tier-1 suppliers carry a null parent."
    if data["tier_to_core"] == 1:
        assert data.get("parent_supplier_id") in (None, ""), (
            "Tier-1 supplier MUST have null parent_supplier_id per PRD §3.2."
        )
    else:
        assert data.get("parent_supplier_id"), (
            "Tier >= 2 supplier MUST declare parent_supplier_id per PRD §3.2."
        )
    assert data["kyc_status"] in {"NOT_RUN", "PASSED", "FAILED", "EXPIRED"}
    if data.get("kyc_completed_at") is not None:
        assert is_iso8601_timestamp(data["kyc_completed_at"])
    assert isinstance(data.get("aml_risk_score"), (int, float))
    assert 0.0 <= float(data["aml_risk_score"]) <= 1.0, (
        f"Supplier.aml_risk_score must be in [0.00, 1.00], "
        f"got {data['aml_risk_score']}"
    )
    assert isinstance(data.get("bank_account_number"), str)
    assert data["status"] in {"ACTIVE", "SUSPENDED", "BLACKLISTED"}


# ---------------------------------------------------------------------------
# PayableConfirmation (PRD §3.3)
# ---------------------------------------------------------------------------
def assert_payable_confirmation(data: dict) -> None:
    _assert_common_mutable(data, "PayableConfirmation")
    assert is_valid_uuid(data.get("core_enterprise_id", ""))
    assert is_valid_uuid(data.get("supplier_id", ""))
    assert isinstance(data.get("invoice_number"), str)
    assert isinstance(data.get("contract_number"), str)
    assert isinstance(data.get("amount_cents"), int) and data["amount_cents"] > 0
    assert is_iso8601_timestamp(data.get("due_date", ""))
    assert isinstance(data.get("tier"), int) and 1 <= data["tier"] <= 4
    assert data["status"] in {
        "DRAFT", "PENDING_CONFIRM", "CONFIRMED", "REVOKED", "SETTLED",
    }
    if data.get("confirmed_at") is not None:
        assert is_iso8601_timestamp(data["confirmed_at"])


# ---------------------------------------------------------------------------
# Receivable (PRD §3.4)
# ---------------------------------------------------------------------------
def assert_receivable(data: dict) -> None:
    _assert_common_mutable(data, "Receivable")
    assert is_valid_uuid(data.get("confirmation_id", ""))
    assert is_valid_uuid(data.get("supplier_id", ""))
    assert is_valid_uuid(data.get("core_enterprise_id", ""))
    assert isinstance(data.get("amount_cents"), int) and data["amount_cents"] > 0
    assert is_iso8601_timestamp(data.get("due_date", ""))
    assert isinstance(data.get("invoice_doc_id"), str)
    assert isinstance(data.get("contract_doc_id"), str)
    assert data["status"] in {
        "REGISTERED", "PLEDGED", "TRANSFERRED",
        "FINANCED", "SETTLED", "WRITTEN_OFF",
    }
    assert isinstance(data.get("central_registry_required"), bool)
    if data.get("central_registry_filing_no") is not None:
        assert isinstance(data["central_registry_filing_no"], str)


# ---------------------------------------------------------------------------
# FinancingApplication (PRD §3.5)
# ---------------------------------------------------------------------------
def assert_financing_application(data: dict) -> None:
    _assert_common_mutable(data, "FinancingApplication")
    assert is_valid_uuid(data.get("receivable_id", ""))
    assert is_valid_uuid(data.get("supplier_id", ""))
    assert data["mode"] in {
        "FACTORING", "REVERSE_FACTORING",
        "DYNAMIC_DISCOUNTING", "RECEIVABLE_PLEDGE",
    }
    assert isinstance(data.get("requested_amount_cents"), int)
    assert data["requested_amount_cents"] > 0
    assert isinstance(data.get("term_days"), int)
    assert 1 <= data["term_days"] <= 365, (
        "FinancingApplication.term_days must be between 1 and 365 inclusive "
        "(PRD §3.5)."
    )
    assert isinstance(data.get("supporting_doc_ids"), list)
    assert data["status"] in {
        "DRAFT", "SUBMITTED", "UNDER_REVIEW", "RETURNED_FOR_REVISION",
        "APPROVED", "REJECTED", "DISBURSED", "CANCELLED",
    }
    assert isinstance(data.get("revision_round"), int)
    assert data["revision_round"] >= 0
    if data.get("risk_rating") is not None:
        assert data["risk_rating"] in {"LOW", "MEDIUM", "HIGH", "REJECT"}
    if data.get("approved_amount_cents") is not None:
        assert isinstance(data["approved_amount_cents"], int)
        assert data["approved_amount_cents"] > 0
    if data.get("approved_apr_bps") is not None:
        assert isinstance(data["approved_apr_bps"], int)


# ---------------------------------------------------------------------------
# Disbursement (PRD §3.6) — LEAN entity.
# ---------------------------------------------------------------------------
def assert_disbursement(data: dict) -> None:
    _assert_common_lean(data, "Disbursement")
    assert is_valid_uuid(data.get("application_id", ""))
    assert isinstance(data.get("funder_account_id"), str)
    assert isinstance(data.get("principal_cents"), int)
    assert data["principal_cents"] > 0
    assert isinstance(data.get("discount_cents"), int)
    assert data["discount_cents"] >= 0
    assert isinstance(data.get("fees_cents"), int)
    assert data["fees_cents"] >= 0
    assert isinstance(data.get("net_to_supplier_cents"), int)
    assert is_iso8601_timestamp(data.get("released_at", ""))
    if data.get("reconciled_at") is not None:
        assert is_iso8601_timestamp(data["reconciled_at"])


# ---------------------------------------------------------------------------
# RepaymentSchedule (PRD §3.6, §3.7)
# ---------------------------------------------------------------------------
def assert_repayment_schedule(data: dict) -> None:
    _assert_common_mutable(data, "RepaymentSchedule")
    assert is_valid_uuid(data.get("application_id", ""))
    assert is_iso8601_timestamp(data.get("scheduled_repayment_date", ""))
    assert isinstance(data.get("total_due_cents"), int)
    assert data["total_due_cents"] > 0
    assert isinstance(data.get("paid_cents"), int)
    assert data["paid_cents"] >= 0
    assert data["paid_cents"] <= data["total_due_cents"], (
        f"paid_cents ({data['paid_cents']}) > total_due_cents "
        f"({data['total_due_cents']}) violates RepaymentSchedule invariant"
    )
    assert data["status"] in {
        "SCHEDULED", "PARTIALLY_PAID", "SETTLED", "OVERDUE", "WRITTEN_OFF",
    }
    assert isinstance(data.get("prepayment_count"), int)
    assert data["prepayment_count"] >= 0


# ---------------------------------------------------------------------------
# CollectionCase (PRD §3.8)
# ---------------------------------------------------------------------------
def assert_collection_case(data: dict) -> None:
    _assert_common_mutable(data, "CollectionCase")
    assert is_valid_uuid(data.get("schedule_id", ""))
    if data.get("aging_bucket") is not None:
        assert data["aging_bucket"] in {
            "DPD_1_30", "DPD_31_60", "DPD_61_90", "DPD_OVER_90",
        }
    assert data["stage"] in {
        "SOFT", "HARD", "JOINT_LIABILITY", "LEGAL", "WRITTEN_OFF", "CLOSED",
    }
    assert isinstance(data.get("reminder_count"), int)
    assert data["reminder_count"] >= 0
    assert isinstance(data.get("outstanding_cents"), int)
    assert data["outstanding_cents"] >= 0


# ---------------------------------------------------------------------------
# TradeBackgroundVerification (PRD §3.9) — LEAN entity.
# ---------------------------------------------------------------------------
def assert_trade_background_verification(data: dict) -> None:
    _assert_common_lean(data, "TradeBackgroundVerification")
    assert is_valid_uuid(data.get("receivable_id", ""))
    if data.get("waybill_doc_id") is not None:
        assert isinstance(data["waybill_doc_id"], str)
    if data.get("customs_declaration_doc_id") is not None:
        assert isinstance(data["customs_declaration_doc_id"], str)
    assert isinstance(data.get("capital_flow_match"), bool)
    assert isinstance(data.get("third_party_score"), (int, float))
    assert 0.0 <= float(data["third_party_score"]) <= 1.0
    assert isinstance(data.get("on_site_required"), bool)
    assert isinstance(data.get("on_site_completed"), bool)
    assert data["outcome"] in {"INCONCLUSIVE", "PASS", "FAIL"}


# ---------------------------------------------------------------------------
# AuditLogEntry (PRD §3.10) — LEAN entity.
# ---------------------------------------------------------------------------
def assert_audit_log_entry(data: dict) -> None:
    _assert_common_lean(data, "AuditLogEntry")
    assert data["entity_type"] in {
        "CoreEnterprise", "Supplier", "PayableConfirmation", "Receivable",
        "FinancingApplication", "Disbursement", "RepaymentSchedule",
        "CollectionCase",
    }
    assert is_valid_uuid(data.get("entity_id", ""))
    assert data["action"] in {
        "CONFIRM", "REVOKE", "REGISTER", "APPROVE", "REJECT",
        "DISBURSE", "REPAY", "WRITE_OFF", "CENTRAL_REGISTRY_FILE",
        "ERP_SYNC",
    }
    assert isinstance(data.get("actor_role"), str) and data["actor_role"]
    assert isinstance(data.get("actor_id"), str) and data["actor_id"]
    if data.get("amount_cents") is not None:
        assert isinstance(data["amount_cents"], int)
    assert is_iso8601_timestamp(data.get("occurred_at", ""))


# ===========================================================================
# Domain invariant checkers
# ===========================================================================

def assert_credit_line_invariants(ce: dict) -> None:
    """PRD §2.7: 'Available headroom is the master limit minus reserved
    minus consumed. ... under no circumstance may any of the three
    counters go negative.'"""
    assert ce["credit_line_total_cents"] >= 0
    assert ce["credit_line_reserved_cents"] >= 0
    assert ce["credit_line_consumed_cents"] >= 0
    headroom = (
        ce["credit_line_total_cents"]
        - ce["credit_line_reserved_cents"]
        - ce["credit_line_consumed_cents"]
    )
    assert headroom >= 0, (
        f"Available headroom must be non-negative: total="
        f"{ce['credit_line_total_cents']}, reserved="
        f"{ce['credit_line_reserved_cents']}, consumed="
        f"{ce['credit_line_consumed_cents']}, headroom={headroom}"
    )


def assert_aml_in_range(supplier: dict) -> None:
    """PRD §3.2: 'aml_risk_score (a continuous value in the closed
    interval from 0.00 to 1.00, rounded to two decimal places).' PRD
    §3.9 fail path says the value is 'clamping the result to the closed
    interval from 0.00 to 1.00'."""
    s = float(supplier["aml_risk_score"])
    assert 0.0 <= s <= 1.0, f"aml_risk_score out of [0,1]: {s}"


def assert_apr_within_clamp(application: dict,
                            floor_bps: int, ceiling_bps: int) -> None:
    """PRD §3.5: 'the final approved_apr_bps is the larger of the
    APR_FLOOR_BPS system constant and the smaller of APR_CEILING_BPS
    and the raw sum.'"""
    apr = application["approved_apr_bps"]
    assert apr is not None
    assert floor_bps <= apr <= ceiling_bps, (
        f"approved_apr_bps {apr} outside clamp [{floor_bps}, {ceiling_bps}]"
    )


def find_audit(entries: Iterable[dict],
               *,
               entity_id: Optional[str] = None,
               entity_type: Optional[str] = None,
               action: Optional[str] = None,
               actor_id: Optional[str] = None) -> Optional[dict]:
    """Return the first audit-log entry matching the given filters."""
    for e in entries:
        if entity_id is not None and e.get("entity_id") != entity_id:
            continue
        if entity_type is not None and e.get("entity_type") != entity_type:
            continue
        if action is not None and e.get("action") != action:
            continue
        if actor_id is not None and e.get("actor_id") != actor_id:
            continue
        return e
    return None


__all__ = [
    "assert_core_enterprise",
    "assert_supplier",
    "assert_payable_confirmation",
    "assert_receivable",
    "assert_financing_application",
    "assert_disbursement",
    "assert_repayment_schedule",
    "assert_collection_case",
    "assert_trade_background_verification",
    "assert_audit_log_entry",
    "assert_credit_line_invariants",
    "assert_aml_in_range",
    "assert_apr_within_clamp",
    "find_audit",
]
