"""Entity assertions and domain invariant checkers (PRD §2.4, §3)."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def _assert_common_fields(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), \
        "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), \
        "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, \
        "version must be a positive integer"


def assert_customer(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["company_name"], str) and data["company_name"]
    assert isinstance(data["credit_limit_cents"], int)
    assert data["credit_limit_cents"] > 0
    assert isinstance(data["outstanding_balance_cents"], int)
    assert data["outstanding_balance_cents"] >= 0
    assert data["status"] in ("ACTIVE", "SUSPENDED")


def assert_load(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("customer_id", "")), \
        "customer_id must be a valid UUID"
    assert isinstance(data["cargo_description"], str)
    assert isinstance(data["gross_weight_lbs"], int) and data["gross_weight_lbs"] > 0
    assert isinstance(data["width_in"], int) and data["width_in"] > 0
    assert isinstance(data["height_in"], int) and data["height_in"] > 0
    assert isinstance(data["length_in"], int) and data["length_in"] > 0
    assert isinstance(data["origin"], str)
    assert isinstance(data["destination"], str)
    assert data["status"] in (
        "DRAFT", "PLANNED", "SURVEYED", "CLEARED", "ON_HOLD",
        "IN_TRANSIT", "DELIVERED", "CANCELLED",
    )
    assert "survey_result" in data, "survey_result key must be present (null until surveyed)"


def assert_securement_plan(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("load_id", ""))
    assert data["method"] in ("CHAINS", "STRAPS", "CHAINS_AND_TARPS")
    assert isinstance(data["tiedown_count"], int) and data["tiedown_count"] >= 2
    assert isinstance(data["wll_per_tiedown_lbs"], int)
    assert data["wll_per_tiedown_lbs"] > 0
    assert isinstance(data["aggregate_wll_lbs"], int)
    assert data["status"] in ("SUBMITTED", "APPROVED", "REJECTED")


def assert_permit(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("load_id", ""))
    assert data["state_code"] in ("CA", "NV", "AZ", "TX", "OR")
    assert data["permit_type"] in ("OVERSIZE", "OVERWEIGHT", "SUPERLOAD")
    assert data["status"] in (
        "DRAFT", "FILED", "GRANTED", "DENIED", "REVOKED", "EXPIRED", "WITHDRAWN",
    )


def assert_escort_booking(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("load_id", ""))
    assert isinstance(data["provider_name"], str) and data["provider_name"]
    assert data["position"] in ("FRONT", "REAR", "POLE_FRONT")
    assert is_iso8601_timestamp(data.get("scheduled_start", ""))
    assert is_iso8601_timestamp(data.get("scheduled_end", ""))
    assert isinstance(data["scheduled_minutes"], int)
    assert data["scheduled_minutes"] > 0
    assert isinstance(data["rate_per_hour_cents"], int)
    assert data["rate_per_hour_cents"] > 0
    assert data["status"] in ("CONFIRMED", "COMPLETED", "CANCELLED")


def assert_crane_appointment(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("load_id", ""))
    assert data["site"] in ("ORIGIN", "DESTINATION")
    assert isinstance(data["crane_id"], str) and data["crane_id"]
    assert is_iso8601_timestamp(data.get("window_start", ""))
    assert is_iso8601_timestamp(data.get("window_end", ""))
    assert data["status"] in ("SCHEDULED", "COMPLETED", "CANCELLED")


def assert_delay_event(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("load_id", ""))
    assert data["kind"] in ("CUSTOMER_DELAY", "CARRIER_DELAY", "WEATHER")
    assert is_iso8601_timestamp(data.get("started_at", ""))
    assert is_iso8601_timestamp(data.get("ended_at", ""))
    assert isinstance(data["duration_minutes"], int)
    assert data["duration_minutes"] > 0
    assert isinstance(data["billable_minutes"], int)
    assert data["billable_minutes"] >= 0
    assert isinstance(data["standby_amount_cents"], int)
    assert data["standby_amount_cents"] >= 0


def assert_scale_ticket(data: dict):
    """PRD §2.4: a ScaleTicket carries id and created_at only — updated_at and
    version are absent entirely (append-only audit event)."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), \
        "created_at must be ISO 8601"
    assert "updated_at" not in data, "scale tickets must not expose updated_at"
    assert "version" not in data, "scale tickets must not expose version"
    assert is_valid_uuid(data.get("load_id", ""))
    assert isinstance(data["measured_gross_lbs"], int)
    assert data["measured_gross_lbs"] > 0
    assert is_iso8601_timestamp(data.get("weighed_at", ""))
    assert isinstance(data["excess_lbs"], int) and data["excess_lbs"] >= 0
    assert isinstance(data["is_violation"], bool)


def assert_fine(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("load_id", ""))
    assert data["kind"] in ("OVERWEIGHT", "DAMAGE", "PERMIT_VIOLATION")
    assert isinstance(data["amount_cents"], int) and data["amount_cents"] > 0
    assert isinstance(data["description"], str)
    assert data["liable_party"] in ("CUSTOMER", "CARRIER")
    assert data["status"] in (
        "PENDING", "DISPUTED", "RESOLVED_CUSTOMER_LIABLE",
        "RESOLVED_CARRIER_LIABLE", "APPLIED",
    )


def assert_invoice(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("load_id", ""))
    for field in ("linehaul_cents", "permits_cents", "escorts_cents",
                  "standby_cents", "fines_cents", "subtotal_cents",
                  "fuel_surcharge_cents", "total_cents"):
        assert isinstance(data[field], int) and data[field] >= 0, \
            f"{field} must be a non-negative integer of cents"
    assert data["status"] in ("ISSUED", "PAID", "VOID")


def assert_invoice_arithmetic(data: dict):
    """PRD §3.9: subtotal is the sum of the five lines; total is subtotal plus
    the fuel surcharge."""
    assert data["subtotal_cents"] == (
        data["linehaul_cents"] + data["permits_cents"] + data["escorts_cents"]
        + data["standby_cents"] + data["fines_cents"]
    ), "subtotal_cents must equal the sum of the five line items"
    assert data["total_cents"] == data["subtotal_cents"] + data["fuel_surcharge_cents"], \
        "total_cents must equal subtotal_cents + fuel_surcharge_cents"
