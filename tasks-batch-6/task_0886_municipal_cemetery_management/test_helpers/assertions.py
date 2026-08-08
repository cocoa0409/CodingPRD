"""Entity assertions and domain invariant checkers (PRD §2.4, §2.6, §2.7)."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"


def _assert_append_only(data: dict):
    """PRD §2.4: Decedent / Payment / CareFundEntry carry ONLY id + created_at."""
    assert is_valid_uuid(data.get("id", "")), "id must be a UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "version" not in data, "append-only record must not carry version"
    assert "updated_at" not in data, "append-only record must not carry updated_at"


def assert_cemetery(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert isinstance(data["perpetual_care_fund_balance_cents"], int)


def assert_plot(data: dict):
    _assert_common(data)
    assert data["status"] in ("AVAILABLE", "RESERVED", "SOLD", "RETIRED")
    assert data["plot_type"] in ("GRAVE", "LAWN_CRYPT", "NICHE", "MAUSOLEUM")
    assert isinstance(data["interment_capacity"], int) and data["interment_capacity"] >= 1
    assert isinstance(data["interments_used"], int) and data["interments_used"] >= 0


def assert_holder(data: dict):
    _assert_common(data)
    assert isinstance(data["full_name"], str) and len(data["full_name"]) > 0
    assert isinstance(data["email"], str)


def assert_decedent(data: dict):
    _assert_append_only(data)
    assert isinstance(data["full_name"], str) and len(data["full_name"]) > 0
    assert isinstance(data["death_year"], int)


def assert_deed(data: dict):
    _assert_common(data)
    assert data["status"] in ("PENDING_PAYMENT", "ISSUED", "TRANSFER_PENDING", "SURRENDERED")
    assert data["sale_type"] in ("NEW_SALE", "RESALE")
    assert isinstance(data["care_fund_contribution_cents"], int)


def assert_interment(data: dict):
    _assert_common(data)
    assert data["operational_status"] in (
        "SCHEDULED", "OPENED", "COMPLETED", "CANCELLED", "DISINTERRED")
    assert data["billing_status"] in ("INVOICED", "PAID", "VOIDED")
    assert data["day_type"] in ("WEEKDAY", "WEEKEND", "HOLIDAY")
    assert isinstance(data["service_fee_cents"], int)


def assert_disinterment(data: dict):
    _assert_common(data)
    assert data["status"] in ("REQUESTED", "APPROVED", "DENIED", "EXECUTED")
    assert data["disinterment_type"] in ("RELOCATION", "REMOVAL")
    assert isinstance(data["health_cleared"], bool)
    assert isinstance(data["nok_consented"], bool)


def assert_marker_permit(data: dict):
    _assert_common(data)
    assert data["status"] in (
        "APPLIED", "APPROVED", "INSTALLED", "REJECTED", "CANCELLED", "DECOMMISSIONED")
    assert data["marker_type"] in ("FLAT", "UPRIGHT", "MONUMENT")
    assert isinstance(data["foundation_fee_cents"], int)


def assert_invoice(data: dict):
    _assert_common(data)
    assert data["status"] in ("ISSUED", "PAID", "VOID")
    assert data["subject_type"] in (
        "DEED_SALE", "INTERMENT_SERVICE", "MARKER_FOUNDATION", "DISINTERMENT")
    assert isinstance(data["lines"], list)
    assert isinstance(data["subtotal_cents"], int)
    assert isinstance(data["tax_cents"], int)
    assert isinstance(data["total_cents"], int)
    # PRD §2.6: total = subtotal + tax
    assert data["total_cents"] == data["subtotal_cents"] + data["tax_cents"]


def assert_payment(data: dict):
    _assert_append_only(data)
    assert isinstance(data["amount_cents"], int)
    assert data["method"] in ("CARD", "CHECK", "CASH", "ACH")


def assert_care_fund_entry(data: dict):
    _assert_append_only(data)
    assert data["entry_type"] in ("CONTRIBUTION", "DISBURSEMENT", "INTEREST")
    assert isinstance(data["amount_cents"], int) and data["amount_cents"] >= 0


def assert_fund_non_negative(data: dict):
    """PRD §2.7: the fund may reach exactly zero but never go negative."""
    assert data["perpetual_care_fund_balance_cents"] >= 0, "care fund must never be negative"
