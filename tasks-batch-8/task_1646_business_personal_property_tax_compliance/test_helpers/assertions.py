"""Entity assertions and domain invariant checkers (PRD §2.2, §2.4, §3)."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def _assert_common_fields(data: dict, entity: str):
    """Every resource except audit events carries id/created_at/updated_at/version (§2.4)."""
    assert is_valid_uuid(data.get("id", "")), f"{entity}.id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), \
        f"{entity}.created_at must be ISO 8601 UTC"
    assert is_iso8601_timestamp(data.get("updated_at", "")), \
        f"{entity}.updated_at must be ISO 8601 UTC"
    assert isinstance(data.get("version"), int), f"{entity}.version must be an integer"


def assert_date_is(value, expected_date: str, field: str = "date"):
    """Assert a date/datetime field falls on the expected calendar date.

    The PRD pins calendar dates, not serialization formats, so accept both
    'YYYY-MM-DD' and full ISO 8601 datetimes for the same date.
    """
    assert isinstance(value, str), f"{field} must be a string, got {value!r}"
    assert value.startswith(expected_date), \
        f"{field} must fall on {expected_date}, got {value!r}"


def assert_client_account(data: dict):
    _assert_common_fields(data, "ClientAccount")
    assert isinstance(data.get("legal_name"), str) and data["legal_name"]
    assert isinstance(data.get("contact_email"), str) and data["contact_email"]
    assert isinstance(data.get("forecast_sequence"), int), \
        "forecast_sequence must be an integer"


def assert_operator(data: dict):
    _assert_common_fields(data, "Operator")
    assert isinstance(data.get("display_name"), str) and data["display_name"]
    assert data.get("operator_role") in ("TAX_ANALYST", "SENIOR_MANAGER")


def assert_jurisdiction(data: dict):
    _assert_common_fields(data, "Jurisdiction")
    assert isinstance(data.get("county_name"), str) and data["county_name"]
    assert isinstance(data.get("state_code"), str) and len(data["state_code"]) == 2
    assert isinstance(data.get("base_deadline_mmdd"), str)
    assert isinstance(data.get("max_extension_days"), int)
    assert isinstance(data.get("late_penalty_pct_per_month"), int)
    assert isinstance(data.get("max_late_penalty_pct"), int)
    assert data.get("penalty_base") in ("VALUE_BASE", "TAX_BASE")
    assert isinstance(data.get("tax_rate"), (int, float))
    assert isinstance(data.get("offered_exemption_types"), list)
    assert isinstance(data.get("max_exemption_pct"), int)


def assert_class_rule(data: dict):
    _assert_common_fields(data, "JurisdictionClassRule")
    assert is_valid_uuid(data.get("jurisdiction_id", ""))
    assert data.get("category") in (
        "MACHINERY", "FURNITURE", "COMPUTER", "VEHICLE", "INVENTORY",
        "LEASEHOLD_IMPROVEMENT",
    )
    assert isinstance(data.get("is_taxable"), bool)
    assert data.get("depreciation_convention") in ("FULL_YEAR", "HALF_YEAR")
    assert isinstance(data.get("percent_good_vector"), list)
    assert isinstance(data.get("percent_good_floor_pct"), int)
    assert isinstance(data.get("de_minimis_line_cents"), int)


def assert_asset(data: dict):
    _assert_common_fields(data, "Asset")
    assert is_valid_uuid(data.get("client_id", ""))
    assert is_valid_uuid(data.get("jurisdiction_id", ""))
    assert isinstance(data.get("asset_tag"), str) and data["asset_tag"]
    assert data.get("category") in (
        "MACHINERY", "FURNITURE", "COMPUTER", "VEHICLE", "INVENTORY",
        "LEASEHOLD_IMPROVEMENT",
    )
    assert isinstance(data.get("acquisition_cost_cents"), int)
    assert data["acquisition_cost_cents"] > 0
    assert data.get("lifecycle_status") in ("ACTIVE", "DISPOSED")
    assert data.get("classification_status") in ("UNCLASSIFIED", "CLASSIFIED", "OVERRIDDEN")
    if data.get("taxable_classification") is not None:
        assert data["taxable_classification"] in ("TAXABLE", "NON_TAXABLE", "EXEMPT_FLAGGED")


def assert_disposal_record(data: dict):
    _assert_common_fields(data, "DisposalRecord")
    assert is_valid_uuid(data.get("asset_id", ""))
    assert isinstance(data.get("disposal_proceeds_cents"), int)
    assert data["disposal_proceeds_cents"] >= 0
    assert data.get("disposal_status") in ("RECORDED", "RECONCILED", "REVERSED")


def find_rendition_line(rendition: dict, asset_id: str) -> dict:
    """Return the generated line for an asset, failing loudly when absent."""
    for line in rendition.get("lines", []):
        if line.get("asset_id") == asset_id:
            return line
    raise AssertionError(
        f"No rendition line for asset {asset_id}; lines: {rendition.get('lines')}"
    )


def assert_rendition(data: dict):
    _assert_common_fields(data, "Rendition")
    assert is_valid_uuid(data.get("client_id", ""))
    assert is_valid_uuid(data.get("jurisdiction_id", ""))
    assert isinstance(data.get("tax_year"), int)
    assert data.get("rendition_status") in ("DRAFT", "FILED", "AMENDMENT_OPEN", "ACCEPTED")
    assert isinstance(data.get("lines"), list)
    assert isinstance(data.get("total_assessed_value_cents"), int)
    for line in data["lines"]:
        assert isinstance(line.get("line_no"), int)
        assert is_valid_uuid(line.get("asset_id", ""))
        assert isinstance(line.get("assessed_value_cents"), int)
        assert isinstance(line.get("included"), bool)
        if not line["included"]:
            assert line.get("exclusion_reason") in ("DISPOSED", "DEMINIMIS", "NON_TAXABLE")


def assert_filing_extension(data: dict):
    _assert_common_fields(data, "FilingExtension")
    assert is_valid_uuid(data.get("rendition_id", ""))
    assert data.get("extension_status") in ("GRANTED", "SUPERSEDED", "EXPIRED")


def assert_assessment_notice(data: dict):
    _assert_common_fields(data, "AssessmentNotice")
    assert is_valid_uuid(data.get("rendition_id", ""))
    assert isinstance(data.get("notice_value_cents"), int)
    assert data["notice_value_cents"] > 0
    assert data.get("notice_status") in ("RECEIVED", "ACCEPTED", "PROTESTED", "FINALIZED")


def assert_appeal(data: dict):
    _assert_common_fields(data, "Appeal")
    assert is_valid_uuid(data.get("notice_id", ""))
    assert isinstance(data.get("claimed_value_cents"), int)
    assert data.get("appeal_status") in (
        "FILED", "HEARING_SCHEDULED", "DECIDED", "ACCEPTED", "ESCALATED", "CLOSED",
        "WITHDRAWN",
    )
    if data.get("decision") is not None:
        assert data["decision"] in ("GRANTED_REDUCTION", "DENIED")


def find_installment(bill: dict, installment_no: int) -> dict:
    """Return the installment row by number, failing loudly when absent."""
    for inst in bill.get("installments", []):
        if inst.get("installment_no") == installment_no:
            return inst
    raise AssertionError(
        f"No installment_no {installment_no}; installments: {bill.get('installments')}"
    )


def assert_tax_bill(data: dict):
    _assert_common_fields(data, "TaxBill")
    assert is_valid_uuid(data.get("notice_id", ""))
    assert isinstance(data.get("billed_amount_cents"), int)
    assert data["billed_amount_cents"] > 0
    assert isinstance(data.get("tax_rate"), (int, float))
    assert data.get("validation_status") in ("PENDING", "MATCHED", "DISCREPANCY")
    assert data.get("payment_status") in (
        "UNSCHEDULED", "SCHEDULED", "PARTIALLY_PAID", "PAID", "DELINQUENT",
    )
    assert isinstance(data.get("installments"), list)
    for inst in data["installments"]:
        assert isinstance(inst.get("installment_no"), int)
        assert isinstance(inst.get("amount_cents"), int)
        assert inst.get("installment_status") in ("SCHEDULED", "LATE", "PAID", "CANCELLED")


def assert_exemption_application(data: dict):
    _assert_common_fields(data, "ExemptionApplication")
    assert is_valid_uuid(data.get("asset_id", ""))
    assert data.get("exemption_type") in ("FREEPORT", "POLLUTION_CONTROL", "HISTORIC")
    assert isinstance(data.get("exemption_pct"), int)
    assert data.get("application_status") in (
        "DRAFT", "SUBMITTED", "APPROVED", "DENIED", "SUSPENDED", "REVOKED",
    )


def assert_abatement_agreement(data: dict):
    _assert_common_fields(data, "AbatementAgreement")
    assert is_valid_uuid(data.get("asset_id", ""))
    assert isinstance(data.get("first_tax_year"), int)
    assert isinstance(data.get("last_tax_year"), int)
    assert data["last_tax_year"] >= data["first_tax_year"]
    assert isinstance(data.get("abatement_pct"), int)
    assert data.get("agreement_status") in ("ACTIVE", "RECERTIFICATION_DUE", "TERMINATED")
    assert isinstance(data.get("last_recertified_year"), int)


def assert_accrual_forecast(data: dict):
    _assert_common_fields(data, "AccrualForecast")
    assert is_valid_uuid(data.get("client_id", ""))
    assert isinstance(data.get("tax_year"), int)
    assert data.get("variant") in ("NOTICE_BASED", "RENDERED_CONSERVATIVE")
    assert isinstance(data.get("forecasted_liability_cents"), int)
    assert isinstance(data.get("component_count"), int)
    assert data.get("forecast_status") in ("PUBLISHED", "SUPERSEDED")
    assert isinstance(data.get("needs_regeneration"), bool)


def assert_audit_event(data: dict):
    """Audit records are immutable: only id + created_at (no updated_at/version, §2.4)."""
    assert is_valid_uuid(data.get("id", "")), "AuditEvent.id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), \
        "AuditEvent.created_at must be ISO 8601 UTC"
    assert "updated_at" not in data, "AuditEvent must not carry updated_at"
    assert "version" not in data, "AuditEvent must not carry version"
    assert data.get("event_type") in AUDIT_EVENT_TYPES
    assert isinstance(data.get("message"), str) and data["message"]
    assert isinstance(data.get("actor_id"), str) and data["actor_id"]


AUDIT_EVENT_TYPES = (
    "DISPOSAL_RECORDED", "DISPOSAL_REVERSED", "DISPOSAL_RECONCILED",
    "RENDITION_FILED", "AMENDMENT_OPENED", "AMENDMENT_WITHDRAWN",
    "EXTENSION_GRANTED", "EXTENSION_SUPERSEDED", "NOTICE_FINALIZED",
    "APPEAL_RESOLVED", "BILL_VALIDATED", "BILL_REVALIDATED",
    "SCHEDULE_CREATED", "SCHEDULE_CANCELLED", "INSTALLMENT_PAID",
    "INSTALLMENT_LATE", "FORECAST_PUBLISHED", "FORECAST_STALENESS_FLAGGED",
    "ABATEMENT_TERMINATED", "EXEMPTION_SUSPENDED", "EXEMPTION_REVOKED",
)


def audit_event_types(events: list) -> list:
    """Extract the ordered event_type list from an audit trail page."""
    return [e.get("event_type") for e in events]


def assert_bill_allocation_invariant(bill: dict):
    """validated == sum(non-CANCELLED installments) + unscheduled (PRD §3.6)."""
    validated = bill.get("validated_amount_cents")
    unscheduled = bill.get("unscheduled_amount_cents")
    if validated is None or unscheduled is None:
        return
    scheduled_sum = sum(
        inst["amount_cents"]
        for inst in bill.get("installments", [])
        if inst.get("installment_status") != "CANCELLED"
    )
    assert validated == scheduled_sum + unscheduled, (
        f"Bill allocation broken: validated {validated} != "
        f"non-cancelled installments {scheduled_sum} + unscheduled {unscheduled}"
    )
