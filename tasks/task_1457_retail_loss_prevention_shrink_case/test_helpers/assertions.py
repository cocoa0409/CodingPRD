"""Entity assertions and domain invariant checkers (PRD §2.2-§2.4, §3)."""
import re
from datetime import datetime

import pytest
from prd_bench_local_runner.testing import (
    is_iso8601_timestamp,
    is_valid_uuid,
)

_THREE_FRACTION_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$")


def assert_common_quartet(data: dict):
    """PRD §2.4: every primary resource carries id/created_at/updated_at/version;
    created_at and updated_at are ISO 8601 UTC with three fractional digits."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    created = data.get("created_at", "")
    updated = data.get("updated_at", "")
    assert is_iso8601_timestamp(created), f"created_at must be ISO 8601, got {created!r}"
    assert is_iso8601_timestamp(updated), f"updated_at must be ISO 8601, got {updated!r}"
    assert _THREE_FRACTION_RE.match(created), (
        f"created_at must carry three fractional digits, got {created!r}"
    )
    assert _THREE_FRACTION_RE.match(updated), (
        f"updated_at must carry three fractional digits, got {updated!r}"
    )
    assert isinstance(data.get("version"), int), "version must be an integer"


def assert_instants_equal(actual: str, expected_iso: str, label: str = "timestamp"):
    """Compare two ISO 8601 instants by value, tolerant of fractional-digit style."""
    assert is_iso8601_timestamp(actual), f"{label} must be ISO 8601, got {actual!r}"
    a = datetime.fromisoformat(actual.replace("Z", "+00:00"))
    e = datetime.fromisoformat(expected_iso.replace("Z", "+00:00"))
    assert a == e, f"{label}: expected instant {expected_iso}, got {actual}"


def assert_store(data: dict):
    assert_common_quartet(data)
    assert isinstance(data["store_number"], str) and data["store_number"]
    assert isinstance(data["name"], str)
    assert isinstance(data["region_code"], str)
    assert data["status"] in ("ACTIVE", "CLOSED")
    assert isinstance(data["total_adjudicated_loss_cents"], int)
    assert isinstance(data["restitution_collected_cents"], int)


def assert_employee(data: dict):
    assert_common_quartet(data)
    assert isinstance(data["store_id"], str)
    assert isinstance(data["employee_ref"], str) and data["employee_ref"]
    assert isinstance(data["full_name"], str)
    assert data["status"] in ("ACTIVE", "SUSPENDED", "TERMINATED")
    assert isinstance(data["prior_substantiated_count"], int)


def assert_event(data: dict):
    assert_common_quartet(data)
    assert isinstance(data["store_id"], str)
    assert isinstance(data["register_ref"], str)
    assert isinstance(data["txn_ref"], str)
    assert data["exception_type"] in (
        "REFUND_NO_RECEIPT",
        "HIGH_VALUE_VOID",
        "PRICE_OVERRIDE",
        "NO_SALE_DRAWER",
        "SUSPEND_CANCEL",
        "SWEETHEART_SCAN",
        "SELF_CHECKOUT_MISMATCH",
    )
    assert isinstance(data["amount_cents"], int) and data["amount_cents"] > 0
    assert is_iso8601_timestamp(data["occurred_at"])
    assert data["status"] in ("UNAGGREGATED", "AGGREGATED")


def assert_alert(data: dict):
    assert_common_quartet(data)
    assert isinstance(data["store_id"], str)
    assert data["subject_type"] in ("EMPLOYEE", "UNKNOWN")
    assert isinstance(data["score"], (int, float))
    assert isinstance(data["event_count"], int) and data["event_count"] >= 1
    assert isinstance(data["total_amount_cents"], int)
    assert is_iso8601_timestamp(data["window_start"])
    assert is_iso8601_timestamp(data["window_end"])
    assert data["status"] in ("OPEN", "ESCALATED", "CONVERTED", "DISMISSED")


def assert_case(data: dict):
    assert_common_quartet(data)
    assert isinstance(data["case_number"], str) and data["case_number"].startswith("LP-")
    assert isinstance(data["store_id"], str)
    assert data["source"] in ("ALERT", "MANUAL", "SHRINK_VARIANCE")
    assert data["subject_type"] in ("EMPLOYEE", "EXTERNAL", "UNKNOWN")
    assert data["status"] in (
        "OPEN",
        "INVESTIGATING",
        "READY_FOR_INTERVIEW",
        "INTERVIEWED",
        "ADJUDICATING",
        "CLOSED_SUBSTANTIATED",
        "CLOSED_UNSUBSTANTIATED",
        "CLOSED_REFERRED",
        "MERGED",
    )
    assert isinstance(data["created_by"], str) and data["created_by"]
    assert isinstance(data["manual_loss_cents"], int)
    assert isinstance(data["recovered_value_cents"], int)
    assert isinstance(data["total_loss_cents"], int)
    assert data["priority"] in ("STANDARD", "HIGH")
    assert data["restitution_status"] in ("NONE", "OUTSTANDING", "SETTLED")
    assert isinstance(data["loss_posted_cents"], int)


def assert_interview(data: dict):
    assert_common_quartet(data)
    assert isinstance(data["case_id"], str)
    assert isinstance(data["interviewer_id"], str)
    assert is_iso8601_timestamp(data["scheduled_start"])
    assert is_iso8601_timestamp(data["scheduled_end"])
    assert data["status"] in ("SCHEDULED", "HELD", "NO_SHOW", "CANCELLED", "DOCUMENTED")
    assert isinstance(data["doc_stale"], bool)


def assert_evidence_item(data: dict):
    assert_common_quartet(data)
    assert isinstance(data["case_id"], str)
    assert data["evidence_type"] in (
        "VIDEO_CLIP",
        "TRANSACTION_LOG",
        "PHOTO",
        "WRITTEN_STATEMENT",
        "AUDIO",
    )
    assert is_iso8601_timestamp(data["captured_at"])
    assert data["retention_class"] in ("STANDARD", "EXTENDED", "CASE_HOLD")
    assert data["status"] in ("ACTIVE", "SEALED", "RELEASED", "EXPIRED", "PURGED")
    assert isinstance(data["legal_hold"], bool)


def assert_custody_event(data: dict):
    """PRD §2.4: custody entries carry only id and created_at from the common
    fields; updated_at and version are absent."""
    assert is_valid_uuid(data.get("id", "")), "id must be a UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "updated_at" not in data, "custody events must not carry updated_at"
    assert "version" not in data, "custody events must not carry version"
    assert isinstance(data["evidence_id"], str)
    assert data["action"] in (
        "COLLECTED",
        "SEALED",
        "ACCESSED",
        "TRANSFERRED",
        "RELEASED_TO_LE",
        "RETURNED_FROM_LE",
    )
    assert isinstance(data["actor_id"], str) and data["actor_id"]


def assert_civil_demand(data: dict):
    assert_common_quartet(data)
    assert isinstance(data["case_id"], str)
    assert data["basis"] in ("STATUTORY", "ACTUAL_LOSS")
    assert isinstance(data["priors_offense_count"], int)
    assert isinstance(data["recovery_cost_cents"], int)
    assert isinstance(data["merchandise_loss_cents"], int)
    assert isinstance(data["statutory_penalty_cents"], int)
    assert isinstance(data["amount_due_cents"], int)
    assert isinstance(data["fees_incurred_cents"], int)
    assert isinstance(data["paid_to_date_cents"], int)
    assert isinstance(data["outstanding_cents"], int)
    assert data["status"] in (
        "DRAFT",
        "ISSUED",
        "PARTIALLY_PAID",
        "PAID_IN_FULL",
        "WRITTEN_OFF",
        "CANCELLED",
    )
    assert isinstance(data["created_by"], str) and data["created_by"]


def assert_payment(data: dict):
    assert_common_quartet(data)
    assert isinstance(data["demand_id"], str)
    assert isinstance(data["amount_cents"], int) and data["amount_cents"] > 0
    assert data["method"] in ("CASH", "CARD", "MONEY_ORDER", "PAYROLL_DEDUCT")
    assert data["status"] in ("RECEIVED", "POSTED", "RETURNED")
    assert isinstance(data["applied_fees_cents"], int)
    assert isinstance(data["applied_penalty_cents"], int)
    assert isinstance(data["applied_merch_cents"], int)


def assert_orc_group(data: dict):
    assert_common_quartet(data)
    assert isinstance(data["name"], str) and data["name"]
    assert data["status"] in (
        "IDENTIFIED",
        "ACTIVE_MONITORING",
        "DISRUPTED",
        "DISMISSED",
    )
    assert isinstance(data["confirmed_case_count"], int)
    assert isinstance(data["distinct_store_count"], int)
    assert isinstance(data["exposure_cents"], int)


def assert_case_link(data: dict):
    assert_common_quartet(data)
    assert isinstance(data["case_id"], str)
    assert isinstance(data["orc_group_id"], str)
    assert isinstance(data["link_score"], int)
    assert 0 <= data["link_score"] <= 100
    assert data["status"] in ("PROPOSED", "CONFIRMED", "REJECTED")


def assert_shrink_period(data: dict):
    assert_common_quartet(data)
    assert isinstance(data["store_id"], str)
    assert is_iso8601_timestamp(data["period_start"])
    assert is_iso8601_timestamp(data["period_end"])
    assert isinstance(data["book_inventory_cents"], int) and data["book_inventory_cents"] > 0
    assert isinstance(data["period_sales_cents"], int) and data["period_sales_cents"] >= 0
    assert isinstance(data["known_loss_posted_cents"], int)
    assert isinstance(data["accrual_case_basis_cents"], int)
    assert isinstance(data["accrual_sales_basis_cents"], int)
    assert data["status"] in ("OPEN", "COUNTED", "RECONCILED", "CLOSED")


def assert_referral_packet(data: dict):
    assert_common_quartet(data)
    assert isinstance(data["case_id"], str)
    assert isinstance(data["jurisdiction_code"], str)
    assert data["status"] in ("DRAFT", "SEALED", "SUBMITTED", "ACKNOWLEDGED", "RETURNED")
    assert isinstance(data["packet_exposure_cents"], int)


def assert_demand_outstanding_invariant(demand: dict):
    """PRD §3.6: after every post and every return,
    outstanding_cents == amount_due_cents + fees_incurred_cents - paid_to_date_cents."""
    expected = (
        demand["amount_due_cents"]
        + demand["fees_incurred_cents"]
        - demand["paid_to_date_cents"]
    )
    assert demand["outstanding_cents"] == expected, (
        f"Outstanding invariant broken: outstanding {demand['outstanding_cents']} "
        f"!= amount_due {demand['amount_due_cents']} + fees {demand['fees_incurred_cents']} "
        f"- paid_to_date {demand['paid_to_date_cents']}"
    )


def assert_case_loss_invariants(case: dict):
    """PRD §3.3: total_loss_cents floors at zero; posted loss never negative."""
    assert case["total_loss_cents"] >= 0
    assert case["loss_posted_cents"] >= 0


def approx_pct(value):
    """4-decimal-place percentage comparison tolerance."""
    return pytest.approx(value, abs=1e-6)
