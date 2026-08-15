"""Entity assertions and domain invariant checkers."""
from datetime import datetime, timezone

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


# ---------------------------------------------------------------------------
# Instant comparison helpers
# ---------------------------------------------------------------------------
def parse_instant(value: str) -> datetime:
    """Parse an ISO 8601 UTC timestamp into an aware datetime."""
    assert isinstance(value, str) and value, f"expected ISO timestamp, got {value!r}"
    text = value.replace("Z", "+00:00")
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def assert_instant_equals(actual: str, expected_iso: str, label: str = "instant"):
    """Two ISO 8601 timestamps denote the same UTC instant."""
    assert parse_instant(actual) == parse_instant(expected_iso), (
        f"{label}: expected instant {expected_iso}, got {actual}"
    )


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a bare UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), \
        "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), \
        "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, \
        "version must be a positive integer"


# ---------------------------------------------------------------------------
# Per-entity assertions
# ---------------------------------------------------------------------------
def assert_client(data: dict):
    _assert_common(data)
    assert isinstance(data["legal_name"], str) and data["legal_name"]
    assert data["certification_scheme"] in ("KOSHER", "HALAL", "DUAL")
    assert isinstance(data["contact_email"], str) and data["contact_email"]
    assert data["status"] in ("PROSPECT", "APPLICANT", "CERTIFIED", "SUSPENDED",
                              "WITHDRAWN", "TERMINATED")
    assert isinstance(data["open_nc_score"], int) and data["open_nc_score"] >= 0
    assert data["risk_tier"] in ("LOW", "MEDIUM", "HIGH")
    assert isinstance(data["total_billed_cents"], int) \
        and data["total_billed_cents"] >= 0


def assert_facility(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("client_id", ""))
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["address"], str)
    assert data["facility_role"] in ("OWNED", "CO_PACKER")
    assert data["status"] in ("PENDING_REVIEW", "APPROVED", "SUSPENDED",
                              "DECOMMISSIONED")


def assert_equipment_line(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("facility_id", ""))
    assert isinstance(data["designation"], str) and data["designation"]
    assert data["dedication_status"] in ("UNASSESSED", "DEDICATED", "SHARED")
    assert data["kosherization_state"] in ("NONE", "VALID", "EXPIRED",
                                           "COMPROMISED")
    if data["kosherization_state"] == "VALID":
        assert data.get("kosherized_valid_until") is not None
        assert is_iso8601_timestamp(data["kosherized_valid_until"])
    else:
        assert data.get("kosherized_valid_until") is None, \
            "kosherized_valid_until must be null unless state is VALID"


def assert_ingredient(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("client_id", ""))
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["manufacturer"], str) and data["manufacturer"]
    assert data["source_category"] in ("ANIMAL", "PLANT", "MICROBIAL", "MINERAL",
                                       "SYNTHETIC")
    assert isinstance(data["has_species_documentation"], bool)
    assert data["status"] in ("SUBMITTED", "UNDER_REVIEW", "APPROVED", "REJECTED",
                              "CHANGE_PENDING")


def assert_product(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("client_id", ""))
    assert isinstance(data["brand"], str) and data["brand"]
    assert isinstance(data["name"], str) and data["name"]
    assert data["status"] in ("DRAFT", "IN_REVIEW", "CERTIFIABLE", "REVIEW_HOLD",
                              "WITHDRAWN")


def assert_product_ingredient(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("product_id", ""))
    assert is_valid_uuid(data.get("ingredient_id", ""))
    assert data["status"] in ("ACTIVE", "PENDING_REAPPROVAL", "BLOCKED", "REMOVED")


def assert_visit(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("facility_id", ""))
    assert data["visit_type"] in ("INITIAL", "ROUTINE", "UNANNOUNCED",
                                  "SPECIAL_HOLIDAY")
    assert isinstance(data["inspector_user_id"], str) and data["inspector_user_id"]
    assert is_iso8601_timestamp(data["scheduled_start"])
    assert is_iso8601_timestamp(data["scheduled_end"])
    assert data["status"] in ("SCHEDULED", "IN_PROGRESS", "COMPLETED", "CANCELLED",
                              "NO_ACCESS")


def assert_finding(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("visit_id", ""))
    assert is_valid_uuid(data.get("facility_id", ""))
    assert data["severity"] in ("MINOR", "MAJOR", "CRITICAL")
    assert isinstance(data["description"], str)
    assert is_iso8601_timestamp(data["remediation_deadline"])
    assert data["origin"] in ("MANUAL", "AUTO_NO_ACCESS")
    assert data["status"] in ("OPEN", "REMEDIATION_SUBMITTED", "REOPENED",
                              "ESCALATED", "VERIFIED_CLOSED")


def assert_agreement(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("client_id", ""))
    assert data["scheme"] in ("KOSHER", "HALAL", "DUAL")
    assert data["billing_cycle"] in ("ANNIVERSARY", "CALENDAR_YEAR")
    assert isinstance(data["term_start_date"], str) and data["term_start_date"]
    assert isinstance(data["term_end_date"], str) and data["term_end_date"]
    assert isinstance(data["per_product_fee_cents"], int)
    assert data["status"] in ("DRAFT", "ACTIVE", "SUPERSEDED", "EXPIRED")
    if data["status"] in ("ACTIVE", "SUPERSEDED", "EXPIRED"):
        assert isinstance(data["annual_fee_snapshot_cents"], int)


def assert_invoice(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("client_id", ""))
    assert data["invoice_type"] in ("ANNUAL_CERTIFICATION", "PRODUCT_ADDITION",
                                    "RENEWAL", "REINSTATEMENT")
    assert isinstance(data["subtotal_cents"], int)
    assert isinstance(data["discount_cents"], int) and data["discount_cents"] >= 0
    assert isinstance(data["total_cents"], int) and data["total_cents"] >= 0
    assert data["total_cents"] == data["subtotal_cents"] - data["discount_cents"], \
        "total_cents must equal subtotal_cents - discount_cents"
    assert is_iso8601_timestamp(data["due_date"])
    assert data["status"] in ("ISSUED", "PAID", "OVERDUE", "VOID")
    if data["status"] == "PAID":
        assert isinstance(data.get("paid_recorded_by"), str) \
            and data["paid_recorded_by"]


def assert_certificate(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("client_id", ""))
    assert data["scheme"] in ("KOSHER", "HALAL", "DUAL")
    assert data["term_type"] in ("ANNUAL", "SEASONAL")
    assert isinstance(data["facility_ids"], list)
    assert data["status"] in ("DRAFT", "ACTIVE", "SUSPENDED", "EXPIRED", "REVOKED",
                              "SUPERSEDED")
    assert data["scope_status"] in ("FULL", "PARTIAL_FROZEN")
    assert isinstance(data["active_product_count"], int) \
        and data["active_product_count"] >= 0
    if data["status"] in ("ACTIVE", "SUSPENDED", "EXPIRED", "SUPERSEDED"):
        assert data.get("issued_at") is not None
        assert is_iso8601_timestamp(data["issued_at"])
        assert data.get("valid_until") is not None
        assert is_iso8601_timestamp(data["valid_until"])


def assert_certificate_product(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("certificate_id", ""))
    assert is_valid_uuid(data.get("product_id", ""))
    assert data["status"] in ("INCLUDED", "FROZEN", "REMOVED")


def assert_holiday_window(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("facility_id", ""))
    assert data["holiday_code"] in ("PASSOVER", "ROSH_HASHANAH", "RAMADAN",
                                    "EID_AL_FITR")
    assert is_iso8601_timestamp(data["window_start"])
    assert is_iso8601_timestamp(data["window_end"])
    assert data["status"] in ("REQUESTED", "CONFIRMED", "COMPLETED", "CANCELLED")
    if data["status"] in ("CONFIRMED", "COMPLETED"):
        assert isinstance(data.get("assigned_supervisor_id"), str) \
            and data["assigned_supervisor_id"]


# ---------------------------------------------------------------------------
# Domain invariants
# ---------------------------------------------------------------------------
def assert_risk_tier_matches_score(client: dict):
    """risk_tier derives from open_nc_score: LOW <= 2, MEDIUM 3..7, HIGH >= 8."""
    score = client["open_nc_score"]
    expected = "LOW" if score <= 2 else ("MEDIUM" if score <= 7 else "HIGH")
    assert client["risk_tier"] == expected, (
        f"risk_tier {client['risk_tier']} inconsistent with score {score} "
        f"(expected {expected})"
    )
