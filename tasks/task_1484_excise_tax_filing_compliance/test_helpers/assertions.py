"""Entity assertions and domain invariant checkers (PRD §2.5, §3)."""
from prd_bench_local_runner.testing import (
    is_iso8601_timestamp,
    is_valid_uuid,
)


def _assert_common(data: dict, entity: str):
    """Standard system-managed fields (PRD §2.5)."""
    assert is_valid_uuid(data.get("id", "")), (
        f"{entity}.id must be a UUID with no type prefix, got {data.get('id')!r}")
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"{entity}.created_at must be ISO 8601 UTC, got {data.get('created_at')!r}")
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"{entity}.updated_at must be ISO 8601 UTC, got {data.get('updated_at')!r}")
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"{entity}.version must be an integer >= 1, got {data.get('version')!r}")


def assert_registrant(data: dict):
    _assert_common(data, "Registrant")
    assert isinstance(data.get("legal_name"), str) and data["legal_name"]
    assert isinstance(data.get("fein"), str) and data["fein"]
    assert data.get("status") in ["ACTIVE", "SUSPENDED", "CANCELLED"]
    assert isinstance(data.get("aggregate_open_liability_cents"), int)
    assert isinstance(data.get("overpayment_balance_cents"), int)


def assert_jurisdiction(data: dict):
    _assert_common(data, "Jurisdiction")
    assert isinstance(data.get("code"), str) and data["code"]
    assert isinstance(data.get("name"), str) and data["name"]
    assert data.get("level") in ["FEDERAL", "STATE", "LOCAL"]
    assert data.get("return_frequency") in ["MONTHLY", "QUARTERLY"]
    assert data.get("deposit_frequency") in ["SEMI_MONTHLY", "MONTHLY"]
    assert data.get("status") in ["ACTIVE", "RETIRED"]


def assert_product_class(data: dict):
    _assert_common(data, "ProductClass")
    assert isinstance(data.get("code"), str) and data["code"]
    assert isinstance(data.get("description"), str) and data["description"]
    assert data.get("base_unit") in ["GALLON", "PROOF_GALLON", "PACK", "UNIT"]
    assert data.get("status") in ["ACTIVE", "RETIRED"]


def assert_tax_rate(data: dict):
    _assert_common(data, "TaxRate")
    assert is_valid_uuid(data.get("jurisdiction_id", ""))
    assert is_valid_uuid(data.get("product_class_id", ""))
    assert isinstance(data.get("rate_millicents_per_unit"), int)
    assert is_iso8601_timestamp(data.get("effective_from", ""))
    if data.get("effective_to") is not None:
        assert is_iso8601_timestamp(data["effective_to"])
    assert data.get("status") in ["SCHEDULED", "ACTIVE", "SUPERSEDED", "RETIRED"]


def assert_rate_change_notice(data: dict):
    _assert_common(data, "RateChangeNotice")
    assert is_valid_uuid(data.get("jurisdiction_id", ""))
    assert is_valid_uuid(data.get("product_class_id", ""))
    assert isinstance(data.get("new_rate_millicents_per_unit"), int)
    assert is_iso8601_timestamp(data.get("announced_effective_from", ""))
    assert isinstance(data.get("source_reference"), str)
    assert is_iso8601_timestamp(data.get("detected_at", ""))
    assert data.get("status") in ["DETECTED", "VALIDATED", "REJECTED", "APPLIED"]


def assert_registration(data: dict):
    _assert_common(data, "Registration")
    assert is_valid_uuid(data.get("registrant_id", ""))
    assert is_valid_uuid(data.get("jurisdiction_id", ""))
    assert data.get("deposit_method") in ["SAFE_HARBOR", "ACTUAL"]
    assert data.get("status") in [
        "PENDING", "ACTIVE", "BOND_DEFICIENT", "SUSPENDED", "REVOKED"]
    assert isinstance(data.get("bond_required_cents"), int)
    assert isinstance(data.get("bond_coverage_cents"), int)
    assert data.get("requirement_variant") in ["STANDARD", "AGGRAVATED"]


def assert_bond(data: dict):
    _assert_common(data, "Bond")
    assert is_valid_uuid(data.get("registration_id", ""))
    assert isinstance(data.get("surety_name"), str) and data["surety_name"]
    assert isinstance(data.get("principal_amount_cents"), int)
    assert is_iso8601_timestamp(data.get("effective_from", ""))
    assert is_iso8601_timestamp(data.get("effective_to", ""))
    assert data.get("status") in ["DRAFT", "ACTIVE", "CANCELLED", "EXPIRED"]


def assert_exemption_certificate(data: dict):
    _assert_common(data, "ExemptionCertificate")
    assert is_valid_uuid(data.get("registration_id", ""))
    assert isinstance(data.get("customer_reference"), str)
    assert data.get("certificate_type") in ["RESALE", "GOVERNMENT", "EXPORT"]
    assert is_iso8601_timestamp(data.get("valid_from", ""))
    assert is_iso8601_timestamp(data.get("valid_to", ""))
    assert data.get("status") in [
        "PENDING_VERIFICATION", "ACTIVE", "REJECTED", "REVOKED", "EXPIRED"]


def assert_bonded_movement(data: dict):
    _assert_common(data, "BondedMovement")
    assert is_valid_uuid(data.get("registration_id", ""))
    assert is_valid_uuid(data.get("bond_id", ""))
    assert is_valid_uuid(data.get("product_class_id", ""))
    assert isinstance(data.get("quantity_units"), int)
    assert isinstance(data.get("origin_facility"), str)
    assert isinstance(data.get("destination_facility"), str)
    assert isinstance(data.get("transit_deadline_days"), int)
    assert isinstance(data.get("defaulted_quantity_units"), int)
    assert data.get("status") in [
        "INITIATED", "IN_TRANSIT", "RECEIVED", "DISCHARGED",
        "PARTIAL_DEFAULT", "DEFAULTED"]


def assert_taxable_event(data: dict):
    _assert_common(data, "TaxableEvent")
    assert is_valid_uuid(data.get("registration_id", ""))
    assert is_valid_uuid(data.get("jurisdiction_id", ""))
    assert is_valid_uuid(data.get("product_class_id", ""))
    assert is_iso8601_timestamp(data.get("event_date", ""))
    assert isinstance(data.get("quantity_units"), int)
    assert isinstance(data.get("period"), str) and data["period"]
    assert data.get("determination") in ["STANDARD", "DEFAULT_ASSESSMENT"]
    assert isinstance(data.get("gross_tax_cents"), int)
    assert isinstance(data.get("tax_cents"), int)
    assert data.get("status") in [
        "DRAFT", "CLASSIFIED", "RATED", "RETURNED", "ADJUSTED", "VOIDED"]


def assert_tax_return(data: dict):
    _assert_common(data, "TaxReturn")
    assert is_valid_uuid(data.get("registration_id", ""))
    assert is_valid_uuid(data.get("jurisdiction_id", ""))
    assert isinstance(data.get("period"), str) and data["period"]
    assert isinstance(data.get("amendment_sequence"), int)
    assert is_iso8601_timestamp(data.get("due_date", ""))
    assert isinstance(data.get("event_count"), int)
    for field in ("gross_tax_cents", "exempted_cents", "taxable_tax_cents",
                  "credits_cents", "deposits_applied_cents", "penalty_cents",
                  "net_due_cents"):
        assert isinstance(data.get(field), int), (
            f"TaxReturn.{field} must be integer cents, got {data.get(field)!r}")
    assert isinstance(data.get("pinned_rate_snapshot"), list)
    assert data.get("filing_status") in ["DRAFT", "SUBMITTED", "FILED", "SUPERSEDED"]
    assert data.get("settlement_status") in [
        "UNFILED", "AWAITING_PAYMENT", "SETTLED", "OVERPAID"]


def assert_deposit(data: dict):
    _assert_common(data, "Deposit")
    assert is_valid_uuid(data.get("registration_id", ""))
    assert is_valid_uuid(data.get("jurisdiction_id", ""))
    assert isinstance(data.get("period"), str) and data["period"]
    assert data.get("window") in ["A", "B", "M"]
    assert isinstance(data.get("scheduled_amount_cents"), int)
    assert is_iso8601_timestamp(data.get("due_date", ""))
    assert isinstance(data.get("penalty_cents"), int)
    assert isinstance(data.get("applied_amount_cents"), int)
    assert data.get("status") in ["SCHEDULED", "LATE", "PAID", "APPLIED", "WAIVED"]


def assert_credit_claim(data: dict):
    _assert_common(data, "CreditClaim")
    assert is_valid_uuid(data.get("registration_id", ""))
    assert is_valid_uuid(data.get("return_id", ""))
    assert data.get("claim_type") in ["BAD_DEBT", "EXPORT"]
    assert isinstance(data.get("claimed_cents"), int)
    assert isinstance(data.get("event_ids"), list)
    assert isinstance(data.get("justification"), str)
    assert isinstance(data.get("eligible_cents"), int)
    assert isinstance(data.get("applied_cents"), int)
    assert isinstance(data.get("reversed_cents"), int)
    assert data.get("status") in [
        "DRAFT", "SUBMITTED", "DENIED", "APPROVED", "APPLIED",
        "REVERSED", "WITHDRAWN"]


def assert_audit_case(data: dict):
    _assert_common(data, "AuditCase")
    assert is_valid_uuid(data.get("registration_id", ""))
    assert is_valid_uuid(data.get("jurisdiction_id", ""))
    assert isinstance(data.get("period_start"), str)
    assert isinstance(data.get("period_end"), str)
    assert isinstance(data.get("records_hold"), bool)
    assert isinstance(data.get("opened_by_user_id"), str)
    assert data.get("status") in [
        "OPENED", "DOCUMENTS_REQUESTED", "UNDER_REVIEW",
        "CLOSED_NO_CHANGE", "CLOSED_ASSESSMENT"]


def assert_return_money_consistency(data: dict):
    """Domain invariant: exempted = gross - taxable (PRD §3.6)."""
    assert data["exempted_cents"] == data["gross_tax_cents"] - data["taxable_tax_cents"], (
        "exempted_cents must equal gross_tax_cents - taxable_tax_cents")


def assert_movement_quantity_conserved(data: dict):
    """Domain invariant: received + defaulted never exceeds shipped (PRD §3.5)."""
    received = data.get("quantity_received_units") or 0
    defaulted = data.get("defaulted_quantity_units") or 0
    assert received + defaulted <= data["quantity_units"], (
        "received + defaulted must not exceed the shipped quantity")
