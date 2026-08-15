"""Entity assertions and domain invariant checkers.

Each assert_* validates the common system-managed fields from PRD §2.4 plus
the status enum membership; monetary fields must be integer cents per PRD §2.7.
"""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        "version must be an integer starting at 1"
    )


def _assert_cents(data: dict, field: str):
    assert isinstance(data.get(field), int) and not isinstance(data.get(field), bool), (
        f"{field} must be integer cents, got {data.get(field)!r}"
    )


def assert_shipper(data: dict):
    _assert_common(data)
    assert data["status"] in ("ACTIVE", "SUSPENDED")
    assert isinstance(data["legal_name"], str) and data["legal_name"]
    _assert_cents(data, "credit_limit_cents")
    _assert_cents(data, "credit_exposure_posted_cents")
    _assert_cents(data, "credit_exposure_forward_cents")
    assert data["credit_terms"] in ("PREPAID_ONLY", "NET_7", "NET_30")


def assert_tariff(data: dict):
    _assert_common(data)
    assert data["status"] in ("DRAFT", "PUBLISHED", "SUPERSEDED", "RETIRED")
    assert data["commodity_type"] in ("GENERAL", "REEFER", "HAZMAT")
    assert data["mode"] in ("FCL", "LCL")
    _assert_cents(data, "rate_per_unit_cents")


def assert_carrier_contract(data: dict):
    _assert_common(data)
    assert data["status"] in ("NEGOTIATION", "ACTIVE", "SUSPENDED", "EXPIRED")
    assert isinstance(data["container_rates"], list)
    _assert_cents(data, "detention_per_diem_cents")


def assert_surety_bond(data: dict):
    _assert_common(data)
    assert data["status"] in ("INACTIVE", "ACTIVE", "EXPIRED")
    _assert_cents(data, "coverage_amount_cents")
    _assert_cents(data, "available_coverage_cents")


def assert_voyage(data: dict):
    _assert_common(data)
    assert data["status"] in ("SCHEDULED", "BOOKING_OPEN", "DEPARTED", "ARRIVED",
                              "CLOSED", "BLANKED")
    assert is_iso8601_timestamp(data.get("etd", ""))
    assert is_iso8601_timestamp(data.get("eta", ""))


def assert_booking(data: dict):
    _assert_common(data)
    assert data["status"] in ("QUOTED", "CONFIRMED", "DOCUMENTATION_CLEARED",
                              "LOADED", "DEPARTED", "ARRIVED", "DELIVERED",
                              "ROLLED", "CANCELLED")
    assert data["mode"] in ("FCL", "LCL")
    assert data["rate_source"] in ("CONTRACT", "SPOT")
    assert data["terms"] in ("PREPAID", "COLLECT")
    assert isinstance(data["booking_number"], str) and data["booking_number"].startswith("BK-")
    _assert_cents(data, "estimated_freight_cents")
    assert isinstance(data["rollover_count"], int)


def assert_consolidation(data: dict):
    _assert_common(data)
    assert data["status"] in ("OPEN", "CLOSED", "TENDERED", "DEPARTED",
                              "ARRIVED", "CANCELLED")
    assert isinstance(data["consolidation_number"], str) and data[
        "consolidation_number"].startswith("CON-")


def assert_container_assignment(data: dict):
    _assert_common(data)
    assert data["status"] in ("STUFFED", "GATED_IN", "LOADED", "DISCHARGED",
                              "GATED_OUT", "EMPTY_RETURNED", "CANCELLED")
    assert data["assignment_mode"] in ("FCL", "LCL")
    _assert_cents(data, "provisional_demurrage_cents")
    _assert_cents(data, "provisional_detention_cents")
    _assert_cents(data, "demurrage_charge_cents")
    _assert_cents(data, "detention_charge_cents")


def assert_bill_of_lading(data: dict):
    _assert_common(data)
    assert data["status"] in ("DRAFT", "ISSUED", "AMENDMENT_PENDING",
                              "SURRENDERED", "RELEASED", "VOIDED")
    assert data["bl_type"] in ("HOUSE", "MASTER")
    assert data["release_mode"] in ("ORIGINAL", "SEAWAY", "TELEX")
    assert isinstance(data["bl_number"], str) and data["bl_number"].startswith("BL-")
    assert isinstance(data["amendment_count"], int)


def assert_compliance_filing(data: dict):
    _assert_common(data)
    assert data["status"] in ("PENDING", "SUBMITTED", "ACCEPTED", "REJECTED")
    assert data["filing_type"] in ("ISF", "AMS")
    assert data["penalty_status"] in ("NONE", "ACCRUED", "PAID", "WAIVED")
    assert isinstance(data["is_late"], bool)
    _assert_cents(data, "penalty_amount_cents")


def assert_invoice(data: dict):
    _assert_common(data)
    assert data["status"] in ("DRAFT", "ISSUED", "PARTIALLY_PAID", "PAID", "VOID")
    assert data["invoice_type"] in ("FREIGHT", "DEMURRAGE_DETENTION", "CANCELLATION")
    assert isinstance(data["invoice_number"], str) and data[
        "invoice_number"].startswith("INV-")
    assert isinstance(data["lines"], list)
    for line in data["lines"]:
        assert line["line_type"] in (
            "OCEAN_FREIGHT", "BAF", "THC", "DOC_FEE", "INSURANCE_PREMIUM",
            "ROLLOVER_FEE", "CANCELLATION_FEE", "DEMURRAGE", "DETENTION",
            "MANUAL_ADJUSTMENT")
        _assert_cents(line, "amount_cents")
    _assert_cents(data, "total_cents")
    _assert_cents(data, "paid_cents")
    _assert_cents(data, "balance_cents")
    assert data["balance_cents"] == data["total_cents"] - data["paid_cents"], (
        "balance_cents must equal total_cents - paid_cents"
    )


def assert_insurance_policy(data: dict):
    _assert_common(data)
    assert data["status"] in ("QUOTED", "BOUND", "CANCELLED", "EXPIRED")
    assert data["coverage_type"] in ("ALL_RISK", "WA", "FPA")
    assert isinstance(data["policy_number"], str) and data[
        "policy_number"].startswith("POL-")
    _assert_cents(data, "cargo_value_cents")
    _assert_cents(data, "insured_value_cents")
    _assert_cents(data, "freight_base_cents")
    _assert_cents(data, "premium_cents")


def assert_cargo_claim(data: dict):
    _assert_common(data)
    assert data["status"] in ("FILED", "UNDER_REVIEW", "APPROVED", "DENIED", "SETTLED")
    assert data["claim_type"] in ("DAMAGE", "LOSS", "SHORTAGE", "DELAY")
    assert isinstance(data["claim_number"], str) and data["claim_number"].startswith("CLM-")
    _assert_cents(data, "claimed_amount_cents")
    _assert_cents(data, "settlement_amount_cents")


def assert_shipper_invariants(data: dict):
    """Credit-exposure invariants that must hold on every shipper read.

    PRD §3.1: the forward variant is always greater than or equal to the
    posted variant.
    """
    assert data["credit_exposure_forward_cents"] >= data["credit_exposure_posted_cents"], (
        "forward exposure must be >= posted exposure"
    )
