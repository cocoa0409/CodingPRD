"""Entity assertions and domain invariant checkers (PRD §2.2, §2.4, §3)."""
from datetime import datetime

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


# ---------------------------------------------------------------------------
# Instant comparison: PRD pins statutory dates to the instant (day
# granularity, §2.6), not to a specific ISO string rendering, so compare
# parsed instants rather than raw strings.
# ---------------------------------------------------------------------------

def _parse_instant(value: str) -> datetime:
    assert isinstance(value, str), f"Expected ISO 8601 string, got {value!r}"
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def assert_iso_instant_equal(actual: str, expected: str) -> None:
    """Assert two ISO 8601 timestamps denote the same instant."""
    assert _parse_instant(actual) == _parse_instant(expected), (
        f"Expected instant {expected}, got {actual}"
    )


def _assert_common_fields(data: dict) -> None:
    """PRD §2.4: id, created_at, updated_at, version are universal."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"


def _assert_nullable_iso(value) -> None:
    assert value is None or is_iso8601_timestamp(value), (
        f"Expected null or ISO 8601 timestamp, got {value!r}"
    )


# ---------------------------------------------------------------------------
# Per-entity structural assertions
# ---------------------------------------------------------------------------

def assert_landlord(data: dict) -> None:
    _assert_common_fields(data)
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["contact_email"], str) and data["contact_email"]
    assert isinstance(data["absentee"], bool)
    assert data["report_channel"] in ("EMAIL", "MAIL", "PORTAL")
    assert isinstance(data["ack_required_days"], int) and data["ack_required_days"] > 0
    assert isinstance(data["total_received_cents"], int)
    assert isinstance(data["pending_receivable_cents"], int)


def assert_tenant(data: dict) -> None:
    _assert_common_fields(data)
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["years_experience"], int) and data["years_experience"] >= 0
    assert data["status"] in ("APPLICANT", "APPROVED", "SUSPENDED")
    assert isinstance(data["compliance_score"], int)
    assert 0 <= data["compliance_score"] <= 100, "compliance_score must stay in [0, 100]"


def assert_field(data: dict) -> None:
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("landlord_id", "")), "landlord_id must be a UUID"
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["acres"], int) and data["acres"] > 0
    assert isinstance(data["soil_csr2"], (int, float))
    assert data["drainage_status"] in ("POOR", "ADEQUATE", "TILED")
    assert data["status"] in ("AVAILABLE", "LEASED")


def assert_offering(data: dict) -> None:
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("field_id", "")), "field_id must be a UUID"
    assert isinstance(data["term_years"], int) and 1 <= data["term_years"] <= 5
    assert is_iso8601_timestamp(data["term_start_date"])
    assert isinstance(data["min_bid_per_acre_cents"], int)
    assert data["min_bid_per_acre_cents"] >= 0
    assert isinstance(data["reference_yield_bu_per_acre"], int)
    assert data["reference_yield_bu_per_acre"] > 0
    assert isinstance(data["reference_price_cents_per_bu"], int)
    assert data["reference_price_cents_per_bu"] > 0
    assert is_iso8601_timestamp(data["bid_deadline"])
    assert data["status"] in ("OPEN", "CLOSED", "AWARDED", "CANCELLED")
    assert isinstance(data["eligible_bid_count"], int) and data["eligible_bid_count"] >= 0


def assert_bid(data: dict) -> None:
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("offering_id", "")), "offering_id must be a UUID"
    assert is_valid_uuid(data.get("tenant_id", "")), "tenant_id must be a UUID"
    assert data["lease_type"] in ("CASH", "FLEX", "SHARE")
    assert isinstance(data["cash_equivalent_bid_cents_per_acre"], int)
    assert isinstance(data["evaluation_score"], (int, float))
    assert data["status"] in ("SUBMITTED", "SHORTLISTED", "ACCEPTED", "REJECTED", "WITHDRAWN")
    _assert_nullable_iso(data.get("accepted_at"))


def assert_lease(data: dict) -> None:
    _assert_common_fields(data)
    for fk in ("bid_id", "field_id", "landlord_id", "tenant_id"):
        assert is_valid_uuid(data.get(fk, "")), f"{fk} must be a UUID"
    assert data["lease_type"] in ("CASH", "FLEX", "SHARE")
    assert is_iso8601_timestamp(data["term_start_date"])
    assert is_iso8601_timestamp(data["term_end_date"])
    assert isinstance(data["term_index"], int) and data["term_index"] >= 1
    assert isinstance(data["base_rent_cents_per_acre"], int)
    assert data["escalation_type"] in ("NONE", "FIXED_PCT")
    assert data["payment_pattern"] in ("MAR_NOV_50_50", "QUARTERLY", "FULL_MAR", "NONE")
    assert isinstance(data["notice_lead_days"], int) and data["notice_lead_days"] > 0
    assert is_iso8601_timestamp(data["current_notice_deadline"])
    assert isinstance(data["landlord_credit_cents"], int)
    assert data["status"] in ("DRAFT", "ACTIVE", "TERMINATION_PENDING", "TERMINATED", "CANCELLED")


def assert_installment(data: dict) -> None:
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("lease_id", "")), "lease_id must be a UUID"
    assert isinstance(data["term_index"], int) and data["term_index"] >= 1
    assert is_iso8601_timestamp(data["due_date"])
    assert isinstance(data["amount_cents"], int) and data["amount_cents"] >= 0
    assert isinstance(data["late_fee_cents"], int) and data["late_fee_cents"] >= 0
    assert isinstance(data["paid_cents"], int) and data["paid_cents"] >= 0
    _assert_nullable_iso(data.get("last_payment_at"))
    assert data.get("paid_recorded_by") is None or isinstance(data["paid_recorded_by"], str)
    assert data["status"] in ("SCHEDULED", "OPEN", "LATE", "PAID", "WAIVED")


def assert_settlement(data: dict) -> None:
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("lease_id", "")), "lease_id must be a UUID"
    assert isinstance(data["crop_year"], int)
    assert data["price_source"] in ("ESTIMATED", "ACTUAL")
    assert isinstance(data["yield_bu_per_acre"], int) and data["yield_bu_per_acre"] > 0
    assert isinstance(data["harvest_price_cents_per_bu"], int)
    assert data["harvest_price_cents_per_bu"] > 0
    for f in ("gross_revenue_cents", "landlord_amount_cents", "input_share_total_cents",
              "net_settlement_cents"):
        assert isinstance(data[f], int), f"{f} must be an integer"
    assert data.get("billed_amount_cents") is None or isinstance(data["billed_amount_cents"], int)
    assert data.get("true_up_cents") is None or isinstance(data["true_up_cents"], int)
    assert data.get("finalized_by") is None or isinstance(data["finalized_by"], str)
    assert data["status"] in ("PROVISIONAL", "FINALIZED", "DISPUTED", "COUNTERSIGNED", "VOID")


def assert_expense(data: dict) -> None:
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("lease_id", "")), "lease_id must be a UUID"
    assert data["category"] in ("SEED", "FERTILIZER", "CHEMICAL", "FUEL", "OTHER")
    assert isinstance(data["total_cost_cents"], int) and data["total_cost_cents"] > 0
    assert is_iso8601_timestamp(data["incurred_date"])
    assert isinstance(data["crop_year"], int)
    assert isinstance(data["landlord_share_pct"], (int, float))
    assert isinstance(data["landlord_share_cents"], int) and data["landlord_share_cents"] >= 0
    _assert_nullable_iso(data.get("approved_at"))
    assert data["status"] in ("SUBMITTED", "APPROVED", "REJECTED")


def assert_compliance_record(data: dict) -> None:
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("lease_id", "")), "lease_id must be a UUID"
    assert data["practice_type"] in ("COVER_CROP", "NO_TILL", "BUFFER_STRIP", "NUTRIENT_PLAN")
    assert is_iso8601_timestamp(data["due_date"])
    assert is_iso8601_timestamp(data["cure_deadline"])
    assert data.get("evidence_note") is None or isinstance(data["evidence_note"], str)
    _assert_nullable_iso(data.get("noncompliant_at"))
    assert data.get("verified_by") is None or isinstance(data["verified_by"], str)
    assert data["status"] in (
        "PENDING", "EVIDENCE_SUBMITTED", "REJECTED", "VERIFIED", "NON_COMPLIANT", "WAIVED",
    )


def assert_improvement(data: dict) -> None:
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("field_id", "")), "field_id must be a UUID"
    assert data.get("lease_id") is None or is_valid_uuid(data["lease_id"])
    assert data["project_type"] in ("TILE_DRAINAGE", "IRRIGATION", "LIMING", "FENCING")
    assert isinstance(data["total_cost_cents"], int) and data["total_cost_cents"] > 0
    assert isinstance(data["landlord_share_pct"], (int, float))
    assert isinstance(data["tenant_share_pct"], (int, float))
    assert data["reimbursement_method"] in ("STRAIGHT_LINE", "AGREED_VALUE")
    assert isinstance(data["amortization_years"], int) and 1 <= data["amortization_years"] <= 10
    assert isinstance(data["tenant_paid_cents"], int) and data["tenant_paid_cents"] >= 0
    _assert_nullable_iso(data.get("completed_at"))
    assert data.get("reimbursement_due_cents") is None or isinstance(
        data["reimbursement_due_cents"], int
    )
    assert data["reimbursement_status"] in ("NONE", "DUE", "PAID")
    assert data["status"] in ("PROPOSED", "APPROVED", "REJECTED", "COMPLETED", "CANCELLED")


def assert_notice(data: dict) -> None:
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("lease_id", "")), "lease_id must be a UUID"
    assert data["served_by"] in ("LANDLORD", "TENANT")
    assert is_iso8601_timestamp(data["served_date"])
    assert is_iso8601_timestamp(data["statutory_deadline"])
    assert is_iso8601_timestamp(data["effective_date"])
    assert data["status"] in ("SERVED", "EFFECTIVE", "WITHDRAWN")


def assert_owner_report(data: dict) -> None:
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("landlord_id", "")), "landlord_id must be a UUID"
    assert data["report_type"] in ("QUARTERLY", "ANNUAL", "SETTLEMENT", "TERMINATION")
    assert is_iso8601_timestamp(data["period_start"])
    assert is_iso8601_timestamp(data["period_end"])
    assert isinstance(data["rent_collected_cents"], int)
    assert isinstance(data["expenses_approved_cents"], int)
    assert isinstance(data["noncompliant_count"], int)
    _assert_nullable_iso(data.get("sent_at"))
    _assert_nullable_iso(data.get("ack_due_date"))
    _assert_nullable_iso(data.get("acknowledged_at"))
    assert isinstance(data["escalation_required"], bool)
    assert data["status"] in ("DRAFT", "SENT", "ACKNOWLEDGED")


# ---------------------------------------------------------------------------
# Domain invariants (PRD §2.10 landlord ledger)
# ---------------------------------------------------------------------------

def assert_landlord_ledger(data: dict, *, total_received_cents: int,
                           pending_receivable_cents: int) -> None:
    """Landlord ledger balances after a triggering mutation (immediate
    consistency per PRD §2.10)."""
    assert data["total_received_cents"] == total_received_cents, (
        f"total_received_cents: expected {total_received_cents}, "
        f"got {data['total_received_cents']}"
    )
    assert data["pending_receivable_cents"] == pending_receivable_cents, (
        f"pending_receivable_cents: expected {pending_receivable_cents}, "
        f"got {data['pending_receivable_cents']}"
    )
