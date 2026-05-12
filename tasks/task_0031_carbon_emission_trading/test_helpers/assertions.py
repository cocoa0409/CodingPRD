"""Per-entity assertions and domain invariant checkers.

Field shape and value-range checks are pinned to PRD prose. Each assertion
checks exactly the surface contract the PRD declares; computed-field
presence is asserted only when PRD explicitly states the field is exposed
on the listed endpoint.
"""
from __future__ import annotations
from typing import Any, Dict, Iterable, List, Optional

from prd_bench_local_runner.testing import (
    is_valid_uuid,
    is_iso8601_timestamp,
)


# ---------------------------------------------------------------------------
# Common-fields helpers (PRD §2.4)
# ---------------------------------------------------------------------------
def _assert_versioned(data: Dict[str, Any], label: str) -> None:
    """Common-fields entities expose id, created_at, updated_at, version
    (PRD §2.4)."""
    assert is_valid_uuid(data.get("id", "")), (
        f"{label}.id must be a UUID, got {data.get('id')!r}"
    )
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"{label}.created_at must be ISO 8601 with 3 fractional digits, "
        f"got {data.get('created_at')!r}"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"{label}.updated_at must be ISO 8601 with 3 fractional digits, "
        f"got {data.get('updated_at')!r}"
    )
    version = data.get("version")
    assert isinstance(version, int) and version >= 1, (
        f"{label}.version must be a positive integer, got {version!r}"
    )


def _assert_immutable(data: Dict[str, Any], label: str) -> None:
    """Lighter entities expose only id and created_at (PRD §2.4: 'Objection,
    EmissionDataLine, SupportingDocument, Trade, and AuditLogEntry carry only
    id and created_at; they have neither updated_at nor version')."""
    assert is_valid_uuid(data.get("id", "")), (
        f"{label}.id must be a UUID, got {data.get('id')!r}"
    )
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"{label}.created_at must be ISO 8601, got {data.get('created_at')!r}"
    )


# ---------------------------------------------------------------------------
# Enterprise (PRD §3.1)
# ---------------------------------------------------------------------------
def assert_enterprise(data: Dict[str, Any]) -> None:
    _assert_versioned(data, "Enterprise")
    assert isinstance(data["legal_name"], str) and len(data["legal_name"]) > 0
    assert data["jurisdiction_code"] in {"JD_ALPHA", "JD_BETA", "JD_GAMMA"}
    assert data["industry_code"] in {
        "POWER", "STEEL", "CEMENT", "CHEMICAL", "PETROCHEMICAL"
    }
    assert isinstance(data["contact_email"], str)
    assert data["account_status"] in {
        "PENDING", "OPEN", "RESTRICTED", "CLOSED"
    }
    qb = data["quota_balance"]
    pqb = data["paid_quota_balance"]
    cb = data["ccer_balance"]
    assert isinstance(qb, (int, float)) and qb >= 0
    assert isinstance(pqb, (int, float)) and pqb >= 0
    assert isinstance(cb, (int, float)) and cb >= 0


# ---------------------------------------------------------------------------
# AllocationCycle (PRD §3.1)
# ---------------------------------------------------------------------------
def assert_allocation_cycle(data: Dict[str, Any]) -> None:
    _assert_versioned(data, "AllocationCycle")
    assert isinstance(data["cycle_year"], int)
    assert data["status"] in {
        "DRAFT", "PUBLISHED", "OBJECTION_OPEN", "FINALIZED",
        "COMPLIANCE_OPEN", "SETTLED", "CLOSED",
    }
    fpr = data["free_paid_ratio"]
    cap = data["ccer_cap_pct"]
    assert isinstance(fpr, (int, float)) and 0.0 <= fpr <= 1.0
    assert isinstance(cap, (int, float)) and 0.0 <= cap <= 0.20
    assert isinstance(data["objection_deadline"], str)
    assert isinstance(data["compliance_deadline"], str)


# ---------------------------------------------------------------------------
# Allocation (PRD §3.2)
# ---------------------------------------------------------------------------
def assert_allocation(data: Dict[str, Any]) -> None:
    _assert_versioned(data, "Allocation")
    assert is_valid_uuid(data["enterprise_id"])
    assert data["method"] in {"INDUSTRY_BENCHMARK", "HISTORICAL_EMISSION"}
    assert data["status"] in {
        "PROPOSED", "PUBLISHED", "OBJECTED", "REVISED", "FINALIZED"
    }


def assert_allocation_post_publish(data: Dict[str, Any]) -> None:
    """After publish, total/free/paid_quota are populated (PRD §3.2)."""
    assert_allocation(data)
    for f in ("total_quota", "free_quota", "paid_quota"):
        v = data.get(f)
        assert isinstance(v, (int, float)), (
            f"Allocation.{f} must be numeric after publish, got {v!r}"
        )
    # Identity: free + paid == total exactly (PRD §3.2: "free_quota plus
    # paid_quota always equals total_quota exactly").
    assert (
        round(data["free_quota"] + data["paid_quota"], 2)
        == round(data["total_quota"], 2)
    ), (
        "Allocation invariant violated: free_quota + paid_quota must "
        f"equal total_quota exactly; got {data['free_quota']} + "
        f"{data['paid_quota']} != {data['total_quota']}"
    )


# ---------------------------------------------------------------------------
# Objection (immutable / append-only per PRD §2.4)
# ---------------------------------------------------------------------------
def assert_objection(data: Dict[str, Any]) -> None:
    _assert_immutable(data, "Objection")
    assert is_valid_uuid(data["filer_enterprise_id"])
    assert isinstance(data["ground"], str) and len(data["ground"]) > 0
    assert data["status"] in {"PENDING", "UPHELD", "REJECTED"}
    assert isinstance(data["filed_at"], str)


# ---------------------------------------------------------------------------
# EmissionReport (PRD §3.3)
# ---------------------------------------------------------------------------
def assert_emission_report(data: Dict[str, Any]) -> None:
    # PRD §2.4 lists EmissionReport in the common-fields set.
    assert is_valid_uuid(data.get("id", "")), "id must be UUID"
    assert is_iso8601_timestamp(data.get("created_at", ""))
    assert is_iso8601_timestamp(data.get("updated_at", ""))
    # PRD §2.4: 'EmissionReport carries its own domain-level version
    # integer that tracks the resubmission sequence per (enterprise,
    # cycle_year); this domain version is the same field used for
    # optimistic concurrency control'.
    v = data.get("version")
    assert isinstance(v, int) and v >= 1, (
        f"EmissionReport.version must be int >= 1, got {v!r}"
    )
    assert isinstance(data["cycle_year"], int)
    assert data["status"] in {
        "DRAFT", "SUBMITTED", "UNDER_VERIFICATION",
        "VERIFIED", "DISPUTED", "FINALIZED", "REJECTED",
    }
    assert isinstance(data["is_current_version"], bool)
    assert isinstance(data["supporting_document_count"], int)
    assert data["supporting_document_count"] >= 0
    tre = data.get("total_reported_emissions")
    assert isinstance(tre, (int, float)) and tre >= 0


# ---------------------------------------------------------------------------
# EmissionDataLine (immutable per PRD §2.4)
# ---------------------------------------------------------------------------
def assert_emission_data_line(data: Dict[str, Any]) -> None:
    _assert_immutable(data, "EmissionDataLine")
    assert data["source_category"] in {
        "FUEL", "ELECTRICITY", "PROCESS", "FUGITIVE"
    }
    ad = data["activity_data"]
    ef = data["emission_factor"]
    assert isinstance(ad, (int, float))
    assert isinstance(ef, (int, float))
    sa = data["source_amount"]
    assert isinstance(sa, (int, float)) and sa >= 0


# ---------------------------------------------------------------------------
# SupportingDocument (immutable per PRD §2.4)
# ---------------------------------------------------------------------------
def assert_supporting_document(data: Dict[str, Any]) -> None:
    _assert_immutable(data, "SupportingDocument")
    assert data["document_type"] in {
        "FUEL_INVOICE", "METER_LOG", "PROCESS_SHEET", "EXTERNAL_AUDIT"
    }
    assert isinstance(data["file_uri"], str)


# ---------------------------------------------------------------------------
# VerificationAssignment (PRD §3.4)
# ---------------------------------------------------------------------------
def assert_verification_assignment(data: Dict[str, Any]) -> None:
    _assert_versioned(data, "VerificationAssignment")
    assert isinstance(data["agency_id"], str)
    assert isinstance(data["scheduled_visit_at"], str)
    assert data["status"] in {
        "ASSIGNED", "SCHEDULED", "ON_SITE_DONE",
        "REPORT_ISSUED", "DISPUTED", "RESOLVED",
    }


# ---------------------------------------------------------------------------
# TradingOrder (PRD §3.5)
# ---------------------------------------------------------------------------
def assert_trading_order(data: Dict[str, Any]) -> None:
    _assert_versioned(data, "TradingOrder")
    assert is_valid_uuid(data["enterprise_id"])
    assert data["side"] in {"BUY", "SELL"}
    assert data["instrument"] in {"QUOTA", "CCER"}
    assert data["order_type"] in {"LIMIT", "MARKET"}
    assert data["channel"] in {"EXCHANGE", "BLOCK", "OTC"}
    assert data["status"] in {
        "OPEN", "PARTIALLY_FILLED", "FILLED", "CANCELLED", "REJECTED"
    }
    q = data["quantity"]
    assert isinstance(q, (int, float)) and q > 0
    fq = data["filled_quantity"]
    assert isinstance(fq, (int, float)) and fq >= 0
    assert isinstance(data["placed_at"], str)


# ---------------------------------------------------------------------------
# Trade (immutable per PRD §2.4)
# ---------------------------------------------------------------------------
def assert_trade(data: Dict[str, Any]) -> None:
    _assert_immutable(data, "Trade")
    assert is_valid_uuid(data["buy_order_id"])
    assert is_valid_uuid(data["sell_order_id"])
    assert data["instrument"] in {"QUOTA", "CCER"}
    assert isinstance(data["quantity"], (int, float))
    assert isinstance(data["price"], (int, float))
    assert isinstance(data["gross_value"], (int, float))
    assert isinstance(data["buyer_fee"], (int, float))
    assert isinstance(data["seller_fee"], (int, float))
    assert data["settlement_status"] in {"PENDING", "SETTLED", "FAILED"}
    assert isinstance(data["executed_at"], str)


# ---------------------------------------------------------------------------
# ComplianceDeclaration (PRD §3.6)
# ---------------------------------------------------------------------------
def assert_compliance_declaration(data: Dict[str, Any]) -> None:
    _assert_versioned(data, "ComplianceDeclaration")
    assert isinstance(data["cycle_year"], int)
    assert data["status"] in {
        "DRAFT", "SUBMITTED", "COMPLIANT",
        "NON_COMPLIANT", "PENALIZED", "FINALIZED",
    }


# ---------------------------------------------------------------------------
# PenaltyOrder (PRD §3.6)
# ---------------------------------------------------------------------------
def assert_penalty_order(data: Dict[str, Any]) -> None:
    _assert_versioned(data, "PenaltyOrder")
    assert data["severity"] in {"MINOR", "MODERATE", "SEVERE"}
    pr = data["penalty_rate"]
    assert isinstance(pr, (int, float)) and pr > 0
    da = data["deficit_amount"]
    assert isinstance(da, (int, float)) and da >= 0
    pa = data["penalty_amount"]
    assert isinstance(pa, (int, float)) and pa >= 0
    md = data["mandatory_deduction_amount"]
    assert isinstance(md, (int, float)) and md >= 0
    assert data["payment_status"] in {"UNPAID", "PAID", "OVERDUE"}
    assert isinstance(data["payment_due_at"], str)
    assert isinstance(data["credit_record_reported"], bool)


# ---------------------------------------------------------------------------
# AnnualSettlement (PRD §3.7)
# ---------------------------------------------------------------------------
def assert_annual_settlement(data: Dict[str, Any]) -> None:
    _assert_versioned(data, "AnnualSettlement")
    assert is_valid_uuid(data["enterprise_id"])
    assert data["status"] in {"PENDING", "RECONCILED", "CLOSED"}
    for f in ("opening_quota", "net_traded_quota", "retired_quota",
              "closing_balance", "carry_forward_amount",
              "repurchase_amount", "deficit_purchase_amount"):
        v = data[f]
        assert isinstance(v, (int, float)), (
            f"AnnualSettlement.{f} must be numeric, got {v!r}"
        )


# ---------------------------------------------------------------------------
# AuditLogEntry (immutable per PRD §2.4)
# ---------------------------------------------------------------------------
def assert_audit_log_entry(data: Dict[str, Any]) -> None:
    _assert_immutable(data, "AuditLogEntry")
    assert data["subject_type"] in {
        "QUOTA_CHANGE", "TRADE_RECORD", "EXTERNAL_SYNC"
    }
    assert isinstance(data["subject_id"], str)
    assert isinstance(data["action"], str)
    es = data.get("external_system")
    assert es is None or es in {"BANK", "REGULATOR", "ENERGY_DATA"}, (
        f"AuditLogEntry.external_system must be BANK/REGULATOR/"
        f"ENERGY_DATA/null, got {es!r}"
    )
    assert isinstance(data["occurred_at"], str)


# ---------------------------------------------------------------------------
# Helpers for finding audit entries by predicate
# ---------------------------------------------------------------------------
def find_audit_log_entries(
    entries: Iterable[Dict[str, Any]],
    *,
    subject_type: Optional[str] = None,
    subject_id: Optional[str] = None,
    action: Optional[str] = None,
    enterprise_id: Optional[str] = None,
    external_system: Optional[str] = None,
) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for e in entries:
        if (subject_type is not None
                and e.get("subject_type") != subject_type):
            continue
        if subject_id is not None and e.get("subject_id") != subject_id:
            continue
        if action is not None and e.get("action") != action:
            continue
        if (enterprise_id is not None
                and e.get("enterprise_id") != enterprise_id):
            continue
        if (external_system is not None
                and e.get("external_system") != external_system):
            continue
        out.append(e)
    return out


__all__ = [
    "assert_enterprise",
    "assert_allocation_cycle",
    "assert_allocation",
    "assert_allocation_post_publish",
    "assert_objection",
    "assert_emission_report",
    "assert_emission_data_line",
    "assert_supporting_document",
    "assert_verification_assignment",
    "assert_trading_order",
    "assert_trade",
    "assert_compliance_declaration",
    "assert_penalty_order",
    "assert_annual_settlement",
    "assert_audit_log_entry",
    "find_audit_log_entries",
]
