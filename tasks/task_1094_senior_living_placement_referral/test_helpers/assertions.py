"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _common(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be a dashed UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"


def _mutable_common(data: dict):
    _common(data)
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, "version must be int >= 1"


def assert_advisor(data: dict):
    _mutable_common(data)
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert isinstance(data["email"], str)
    assert data["status"] in ("ACTIVE", "PAUSED", "INACTIVE")
    assert isinstance(data["is_va_certified"], bool)
    assert isinstance(data["caseload_capacity"], int)
    assert isinstance(data["active_caseload_count"], int) and data["active_caseload_count"] >= 0


def assert_community(data: dict):
    _mutable_common(data)
    assert data["contract_tier"] in ("STANDARD", "PREFERRED", "PREMIER")
    assert data["status"] in ("ACTIVE", "SUSPENDED", "TERMINATED")
    assert isinstance(data["fee_balance_cents"], int)
    assert isinstance(data["satisfaction_survey_count"], int)


def assert_inventory(data: dict):
    _mutable_common(data)
    assert data["care_level"] in ("INDEPENDENT_LIVING", "ASSISTED_LIVING", "MEMORY_CARE", "SKILLED_NURSING")
    assert data["status"] in ("OPEN", "CLOSED")
    assert_inventory_conservation(data)


def assert_inventory_conservation(data: dict):
    """available_units == total_units - reserved_units - occupied_units, never negative."""
    assert data["available_units"] >= 0, "available_units must never be negative"
    assert data["available_units"] == data["total_units"] - data["reserved_units"] - data["occupied_units"], (
        f"unit conservation broken: available={data['available_units']} "
        f"total={data['total_units']} reserved={data['reserved_units']} occupied={data['occupied_units']}"
    )


def assert_family(data: dict):
    _mutable_common(data)
    assert "@" in data["email"]
    assert data["relationship_to_senior"] in ("SELF", "SPOUSE", "ADULT_CHILD", "OTHER_RELATIVE", "FRIEND")
    assert 55 <= data["senior_age"] <= 120


def assert_inquiry(data: dict):
    _mutable_common(data)
    assert data["status"] in ("NEW", "ASSIGNED", "ASSESSED", "MATCHING", "TOURING", "PLACED", "ON_HOLD", "CLOSED_LOST")
    assert data["origin"] in ("WEB", "PHONE", "PARTNER_REFERRAL")
    assert isinstance(data["priority_score"], (int, float))
    assert isinstance(data["match_count"], int)


def assert_assessment(data: dict):
    _mutable_common(data)
    assert data["status"] in ("DRAFT", "SUBMITTED", "REVISION_REQUESTED", "APPROVED")
    assert data["recommended_care_level"] in ("INDEPENDENT_LIVING", "ASSISTED_LIVING", "MEMORY_CARE", "SKILLED_NURSING")
    assert 0 <= data["adl_score"] <= 10
    assert 0 <= data["cognitive_score"] <= 10
    assert 0 <= data["mobility_score"] <= 10
    assert isinstance(data["revision_count"], int)


def assert_match(data: dict):
    _mutable_common(data)
    assert data["status"] in ("PROPOSED", "SHORTLISTED", "TOUR_SCHEDULED", "TOURED", "SELECTED", "DECLINED", "WITHDRAWN")
    assert isinstance(data["quoted_monthly_rate_cents"], int)
    assert isinstance(data["fit_score"], (int, float))
    assert isinstance(data["tour_round"], int)


def assert_tour(data: dict):
    _mutable_common(data)
    assert data["status"] in ("SCHEDULED", "COMPLETED", "CANCELLED", "NO_SHOW")
    assert data["mode"] in ("IN_PERSON", "VIRTUAL")


def assert_placement(data: dict):
    _mutable_common(data)
    assert data["residency_status"] in ("PENDING_MOVE_IN", "MOVED_IN", "RESIDENT_CONFIRMED", "MOVED_OUT", "CANCELLED")
    assert data["billing_status"] in ("NOT_INVOICED", "INVOICE_DRAFTED", "INVOICED", "PAID", "CLAWED_BACK", "VOIDED")
    assert isinstance(data["estimated_fee_cents"], int)


def assert_invoice(data: dict):
    _mutable_common(data)
    assert data["status"] in ("DRAFT", "ISSUED", "DISPUTED", "ACCEPTED", "PAID", "VOIDED", "CLAWED_BACK")
    assert isinstance(data["final_fee_cents"], int)
    assert isinstance(data["paid_amount_cents"], int)
    assert isinstance(data["net_recognized_fee_cents"], int)
    assert isinstance(data["adjustment_count"], int)


def assert_guidance(data: dict):
    _mutable_common(data)
    assert data["status"] in ("ISSUED", "SUPERSEDED")
    assert data["benefit_type"] in ("VA_AID_ATTENDANCE", "VA_SURVIVOR_PENSION", "LTC_INSURANCE", "BRIDGE_LOAN")
    assert isinstance(data["estimated_monthly_benefit_cents"], int)


def assert_caseload_assignment(data: dict):
    _mutable_common(data)
    assert data["status"] in ("ACTIVE", "RELEASED", "REASSIGNED")


def assert_ledger_entry(data: dict):
    """Append-only: id + created_at only, NO updated_at, NO version."""
    _common(data)
    assert "updated_at" not in data, "FeeLedgerEntry is append-only and must not carry updated_at"
    assert "version" not in data, "FeeLedgerEntry is append-only and must not carry version"
    assert data["entry_type"] in ("ACCRUAL", "ADJUSTMENT", "PAYMENT", "CLAWBACK", "WRITE_OFF")
    assert isinstance(data["amount_cents"], int)
    assert isinstance(data["balance_after_cents"], int)


def assert_survey(data: dict):
    """Append-only: id + created_at only, NO updated_at, NO version."""
    _common(data)
    assert "updated_at" not in data, "SatisfactionSurvey is append-only and must not carry updated_at"
    assert "version" not in data, "SatisfactionSurvey is append-only and must not carry version"
    assert 0 <= data["nps_score"] <= 10
    assert 1 <= data["care_rating"] <= 5
    assert 1 <= data["value_rating"] <= 5
