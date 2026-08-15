"""Entity assertions and domain invariant checkers (PRD sections 2.2-2.4, 3.x)."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def _assert_common_fields(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"created_at must be ISO 8601, got {data.get('created_at')!r}"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"updated_at must be ISO 8601, got {data.get('updated_at')!r}"
    )
    assert isinstance(data.get("version"), int), (
        f"version must be an integer, got {data.get('version')!r}"
    )


def assert_program_year(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["school_year_label"], str)
    assert isinstance(data["start_date"], str)
    assert isinstance(data["end_date"], str)
    assert data["local_radius_miles"] >= 25
    assert data["preference_model"] in ("LINEAR", "TIERED")
    assert isinstance(data["grant_award_cents"], int)
    assert isinstance(data["grant_drawn_cents"], int)
    assert isinstance(data["grant_remaining_cents"], int)
    assert data["status"] in ("DRAFT", "OPEN", "CLOSED")


def assert_farm(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["legal_name"], str)
    assert isinstance(data["contact_email"], str)
    assert isinstance(data["distance_miles_to_hub"], int)
    assert data["status"] in ("APPLIED", "APPROVED", "SUSPENDED")
    assert isinstance(data["is_small_farm"], bool)
    assert isinstance(data["required_insurance_cents"], int)
    assert data["compliance_posture"] in ("COMPLIANT", "NON_COMPLIANT")


def assert_compliance_document(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["farm_id"])
    assert data["doc_type"] in ("SAFETY_CERT", "LIABILITY_INSURANCE")
    assert isinstance(data["issuer"], str)
    assert isinstance(data["effective_on"], str)
    assert isinstance(data["expires_on"], str)
    assert data["status"] in ("ACTIVE", "EXPIRED", "REVOKED")


def assert_product(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["name"], str)
    assert data["category"] in ("PRODUCE", "DAIRY", "PROTEIN", "GRAIN")
    assert data["unit"] in ("LB", "CASE", "GALLON", "DOZEN")
    assert 1 <= data["season_start_week"] <= 52
    assert 1 <= data["season_end_week"] <= 52
    assert data["status"] in ("ACTIVE", "DISCONTINUED")


def assert_offering(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["farm_id"])
    assert is_valid_uuid(data["program_year_id"])
    assert is_valid_uuid(data["product_id"])
    assert data["price_cents_per_unit"] > 0
    assert data["max_weekly_quantity"] > 0
    assert isinstance(data["is_local_eligible"], bool)
    assert isinstance(data["preference_points"], int)
    assert data["status"] in (
        "DRAFT",
        "SUBMITTED",
        "VERIFIED",
        "REJECTED",
        "SUSPENDED",
        "WITHDRAWN",
    )


def assert_forecast_line(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["program_year_id"])
    assert is_valid_uuid(data["product_id"])
    assert 1 <= data["week_number"] <= 52
    assert data["planned_quantity"] >= 1
    assert isinstance(data["reserved_quantity"], int)
    assert isinstance(data["uncovered_quantity"], int)


def assert_kitchen(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["name"], str)


def assert_receiving_window(data: dict):
    # PRD section 2.4: windows carry only id and created_at among system fields.
    assert is_valid_uuid(data.get("id", "")), "id must be a UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        "created_at must be ISO 8601"
    )
    assert "updated_at" not in data, "receiving window must not carry updated_at"
    assert "version" not in data, "receiving window must not carry version"
    assert is_valid_uuid(data["kitchen_id"])
    assert data["weekday"] in ("MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN")
    assert 0 <= data["start_minute"] <= 1439
    assert 1 <= data["end_minute"] <= 1440
    assert data["capacity_deliveries"] >= 1


def assert_agreement(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["program_year_id"])
    assert is_valid_uuid(data["offering_id"])
    assert data["committed_quantity"] >= 1
    assert isinstance(data["unit_price_cents"], int)
    assert isinstance(data["local_eligible"], bool)
    assert isinstance(data["delivered_quantity"], int)
    assert isinstance(data["remaining_quantity"], int)
    assert isinstance(data["released_quantity"], int)
    assert data["status"] in (
        "PROPOSED",
        "SIGNED",
        "AMENDMENT_PROPOSED",
        "FULFILLING",
        "COMPLETED",
        "BREACHED",
        "CANCELLED",
    )


def assert_amendment(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["agreement_id"])
    assert data["proposed_by_role"] in ("FarmManager", "DistrictProgramAdmin")
    assert data["status"] in ("PROPOSED", "ACCEPTED", "REJECTED", "SUPERSEDED")


def assert_delivery(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["agreement_id"])
    assert is_valid_uuid(data["kitchen_id"])
    assert is_valid_uuid(data["window_id"])
    assert isinstance(data["delivery_date"], str)
    assert data["quantity"] >= 1
    assert 1 <= data["week_number"] <= 52
    assert data["status"] in (
        "SCHEDULED",
        "CHECKED_IN",
        "ACCEPTED",
        "REJECTED",
        "DISPUTED",
        "CLOSED_REJECTED",
        "CANCELLED",
        "NO_SHOW",
    )


def assert_invoice(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["farm_id"])
    assert is_valid_uuid(data["delivery_id"])
    assert is_valid_uuid(data["agreement_id"])
    assert isinstance(data["invoice_number"], str)
    assert isinstance(data["quantity_billed"], int)
    assert isinstance(data["unit_price_cents"], int)
    assert isinstance(data["subtotal_cents"], int)
    assert isinstance(data["incentive_credit_cents"], int)
    assert isinstance(data["total_cents"], int)
    assert isinstance(data["farm_compliant_at_delivery"], bool)
    assert data["status"] in (
        "DRAFT",
        "SUBMITTED",
        "APPROVED",
        "REJECTED",
        "PAID",
        "VOIDED",
    )


def assert_claim(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["program_year_id"])
    assert isinstance(data["period_month"], str)
    assert isinstance(data["total_claimed_cents"], int)
    assert isinstance(data["total_awarded_cents"], int)
    assert isinstance(data["match_provisional_cents"], int)
    assert data["status"] in (
        "OPEN",
        "SUBMITTED",
        "UNDER_REVIEW",
        "AWARDED",
        "PARTIALLY_AWARDED",
        "REJECTED",
        "RECONCILED",
        "REVERSED",
    )


def assert_claim_line(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["claim_id"])
    assert is_valid_uuid(data["invoice_id"])
    assert isinstance(data["claimed_amount_cents"], int)
    assert data["audit_status"] in ("PENDING", "ALLOWED", "DISALLOWED")
    assert isinstance(data["disallowed_amount_cents"], int)


def assert_substitution_request(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["forecast_line_id"])
    assert is_valid_uuid(data["substitute_product_id"])
    assert data["quantity"] >= 1
    assert data["reason"] in ("SEASONALITY_GAP", "SUPPLY_SHORTFALL", "QUALITY_FAILURE")
    assert data["status"] in ("REQUESTED", "APPROVED", "DENIED")


def assert_grant_ledger_conserved(year: dict):
    """PRD section 3.1: grant_remaining is always award minus drawn."""
    assert year["grant_drawn_cents"] + year["grant_remaining_cents"] == (
        year["grant_award_cents"]
    ), (
        f"grant ledger not conserved: drawn {year['grant_drawn_cents']} + "
        f"remaining {year['grant_remaining_cents']} != award {year['grant_award_cents']}"
    )


def assert_agreement_quantity_conserved(agreement: dict):
    """PRD section 3.4: committed == delivered + remaining + released."""
    total = (
        agreement["delivered_quantity"]
        + agreement["remaining_quantity"]
        + agreement["released_quantity"]
    )
    assert total == agreement["committed_quantity"], (
        f"agreement quantities not conserved: {agreement['delivered_quantity']} + "
        f"{agreement['remaining_quantity']} + {agreement['released_quantity']} != "
        f"{agreement['committed_quantity']}"
    )
