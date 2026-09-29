"""Entity assertions, timestamp canonicalisation and program invariant checkers."""
import re
from typing import Optional

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

_TS_RE = re.compile(
    r"^(\d{4})-(\d{2})-(\d{2})"
    r"(?:[T ](\d{2}):(\d{2})(?::(\d{2}))?(?:\.(\d+))?)?"
    r"(?:Z|[+-]\d{2}:?\d{2})?$"
)


def canonical_ts(value: Optional[str]) -> Optional[str]:
    """Canonicalise an instant to `YYYY-MM-DDTHH:MM:SS.mmmZ`.

    Sub-second digit width and an omitted time-of-day both collapse to the same
    canonical form, so an instant can be compared for equality without pinning
    the serializer's exact spelling.
    """
    if value is None:
        return None
    assert isinstance(value, str), f"expected a timestamp string, got {value!r}"
    m = _TS_RE.match(value.strip())
    assert m, f"not a parseable ISO-8601 instant: {value!r}"
    y, mo, d, hh, mm, ss, frac = m.groups()
    hh = hh or "00"
    mm = mm or "00"
    ss = ss or "00"
    frac = (frac or "")[:3].ljust(3, "0")
    return f"{y}-{mo}-{d}T{hh}:{mm}:{ss}.{frac}Z"


def same_instant(actual: Optional[str], expected: Optional[str]) -> bool:
    """True when two serialisations denote the same instant."""
    if actual is None or expected is None:
        return actual is expected or actual == expected
    return canonical_ts(actual) == canonical_ts(expected)


def assert_same_instant(actual: Optional[str], expected: str, field: str = "timestamp") -> None:
    assert actual is not None, f"{field} must be set, got None"
    assert same_instant(actual, expected), (
        f"{field}: expected instant {expected}, got {actual}"
    )


def date_part(value: Optional[str]) -> Optional[str]:
    """The calendar-date prefix of a date or datetime serialisation."""
    if value is None:
        return None
    assert isinstance(value, str), f"expected a date string, got {value!r}"
    assert _TS_RE.match(value.strip()), f"not a parseable date: {value!r}"
    return value.strip()[:10]


def assert_same_date(actual: Optional[str], expected: str, field: str = "date") -> None:
    """Compare a date-valued field at calendar-date granularity."""
    assert actual is not None, f"{field} must be set, got None"
    assert date_part(actual) == date_part(expected), (
        f"{field}: expected date {expected}, got {actual}"
    )


def assert_common_record_fields(data: dict, entity: str = "record") -> None:
    """id + created_at + updated_at + version, as every non-append-only row carries."""
    assert is_valid_uuid(data.get("id", "")), f"{entity}.id must be a UUID: {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"{entity}.created_at must be an ISO 8601 UTC timestamp: {data.get('created_at')!r}"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"{entity}.updated_at must be an ISO 8601 UTC timestamp: {data.get('updated_at')!r}"
    )
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"{entity}.version must be an integer starting at 1: {data.get('version')!r}"
    )


def assert_money_is_integer_cents(value, field: str) -> None:
    assert isinstance(value, int) and not isinstance(value, bool), (
        f"{field} must be an integer number of cents, got {value!r}"
    )
    assert value >= 0, f"{field} must be non-negative, got {value}"


def assert_two_decimal_places(value, field: str) -> None:
    assert isinstance(value, (int, float)) and not isinstance(value, bool), (
        f"{field} must be numeric, got {value!r}"
    )
    assert round(float(value), 2) == float(value), (
        f"{field} must carry at most two decimal places, got {value}"
    )


# ── Per-entity assertions ───────────────────────────────────────────────────

def assert_party(data: dict) -> None:
    assert_common_record_fields(data, "Party")
    assert data["kind"] in ("LANDOWNER", "DEVELOPER", "MUNICIPAL_BANK"), data["kind"]
    assert isinstance(data["legal_name"], str) and 1 <= len(data["legal_name"]) <= 120
    assert "@" in data["contact_email"]
    assert_money_is_integer_cents(data["cash_balance_cents"], "Party.cash_balance_cents")
    assert_money_is_integer_cents(data["fee_revenue_cents"], "Party.fee_revenue_cents")
    assert isinstance(data["units_held"], int) and data["units_held"] >= 0
    assert isinstance(data["certificates_held_count"], int) and data["certificates_held_count"] >= 0
    assert data["status"] in ("ACTIVE", "SUSPENDED"), data["status"]


def assert_sending_area(data: dict) -> None:
    assert_common_record_fields(data, "SendingArea")
    assert 3 <= len(data["code"]) <= 16
    assert data["allocation_formula_version"] in ("V1_NET_ACRE", "V2_GROSS_DISCOUNTED")
    assert data["equity_tier"] in ("HIGH_VALUE", "MODERATE", "UNDERSERVED")
    assert 0 < float(data["base_rate_units_per_acre"]) <= 4
    assert 0 < float(data["gross_discount_factor"]) <= 1
    assert isinstance(data["sending_cap_units"], int) and data["sending_cap_units"] > 0
    assert isinstance(data["severed_units_total"], int) and data["severed_units_total"] >= 0
    assert isinstance(data["issued_certificate_count"], int)
    assert data["status"] in ("DRAFT", "ACTIVE", "CLOSED"), data["status"]


def assert_receiving_area(data: dict) -> None:
    assert_common_record_fields(data, "ReceivingArea")
    assert 3 <= len(data["code"]) <= 16
    assert 0 < float(data["base_density_units_per_acre"]) <= 40
    assert 0 < float(data["max_bonus_pct"]) <= 1
    assert isinstance(data["absorption_cap_units"], int) and data["absorption_cap_units"] > 0
    assert isinstance(data["design_review_required"], bool)
    assert isinstance(data["eligible_sending_area_codes"], list)
    assert isinstance(data["absorbed_units"], int) and data["absorbed_units"] >= 0
    assert isinstance(data["reserved_units"], int) and data["reserved_units"] >= 0
    assert data["status"] in ("DRAFT", "ACTIVE", "SUSPENDED"), data["status"]


def assert_appraisal_schedule(data: dict) -> None:
    assert_common_record_fields(data, "AppraisalSchedule")
    assert isinstance(data["per_unit_value_cents"], int) and data["per_unit_value_cents"] > 0
    assert -5000 <= data["equity_adjustment_bps"] <= 5000
    assert data["status"] in ("ACTIVE", "SUPERSEDED"), data["status"]


def assert_sending_parcel(data: dict) -> None:
    assert_common_record_fields(data, "SendingParcel")
    assert 4 <= len(data["apn"]) <= 24
    assert data["soil_class"] in ("PRIME", "STATEWIDE", "LOCAL", "NONE")
    assert_two_decimal_places(data["gross_acres"], "SendingParcel.gross_acres")
    assert_two_decimal_places(data["constrained_acres"], "SendingParcel.constrained_acres")
    assert_two_decimal_places(data["restricted_acres"], "SendingParcel.restricted_acres")
    assert isinstance(data["baseline_allocation_units"], int) and data["baseline_allocation_units"] >= 0
    assert data["easement_status"] in ("NONE", "RECORDED")
    assert data["parcel_status"] in ("UNSEVERED", "PARTIALLY_SEVERED", "FULLY_SEVERED")
    assert data["remaining_units"] == data["baseline_allocation_units"] - data["severed_units"], (
        "remaining_units must equal baseline_allocation_units less severed_units: "
        f"{data['remaining_units']} != {data['baseline_allocation_units']} - {data['severed_units']}"
    )


def assert_severance_application(data: dict) -> None:
    assert_common_record_fields(data, "SeveranceApplication")
    assert data["status"] in (
        "SUBMITTED", "UNDER_REVIEW", "REVISION_REQUESTED", "APPROVED",
        "CERTIFIED", "DENIED", "SUSPENDED",
    ), data["status"]
    assert isinstance(data["requested_units"], int) and data["requested_units"] > 0
    assert isinstance(data["revision_round"], int) and 0 <= data["revision_round"] <= 2


def assert_conservation_easement(data: dict) -> None:
    assert_common_record_fields(data, "ConservationEasement")
    assert data["recording_status"] in ("PENDING_RECORDING", "RECORDED", "AMENDED")
    assert data["compliance_status"] in (
        "COMPLIANT", "VIOLATION_NOTICED", "UNDER_CURE", "CURED", "ESCALATED",
    )
    assert_two_decimal_places(data["restricted_acres"], "ConservationEasement.restricted_acres")
    assert_easement_units_conserved(data)


def assert_certificate(data: dict) -> None:
    assert_common_record_fields(data, "Certificate")
    assert data["lifecycle_status"] in ("ISSUED", "PARTIALLY_REDEEMED", "REDEEMED", "RETIRED")
    assert data["market_status"] in ("HELD", "UNDER_CONTRACT", "FROZEN")
    assert isinstance(data["generation"], int) and data["generation"] >= 1
    assert isinstance(data["serial_number"], str) and data["serial_number"]
    assert_certificate_units_conserved(data)


def assert_certificate_transfer(data: dict) -> None:
    """A chain-of-title row carries only id and created_at beyond its own fields."""
    assert is_valid_uuid(data.get("id", "")), f"CertificateTransfer.id must be a UUID: {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), data.get("created_at")
    assert "updated_at" not in data, "an append-only chain-of-title row carries no updated_at"
    assert "version" not in data, "an append-only chain-of-title row carries no version"
    assert isinstance(data["seq_no"], int) and data["seq_no"] >= 1
    assert data["transfer_type"] in (
        "ISSUANCE", "PRIVATE_SALE", "BANK_PURCHASE", "BANK_RESALE",
        "SPLIT_OUT", "REDEMPTION", "RETIREMENT", "REVERSAL",
    ), data["transfer_type"]
    assert isinstance(data["units"], int) and data["units"] > 0


def assert_market_transaction(data: dict) -> None:
    assert_common_record_fields(data, "MarketTransaction")
    assert data["channel"] in ("PRIVATE", "BANK_PURCHASE", "BANK_RESALE")
    assert data["status"] in ("PROPOSED", "SETTLED", "REVERSED", "CANCELLED")
    assert isinstance(data["units"], int) and data["units"] > 0
    for field in (
        "applied_per_unit_value_cents", "appraised_reference_cents", "gross_price_cents",
        "program_fee_cents", "equity_surcharge_cents", "net_to_seller_cents",
    ):
        assert isinstance(data[field], int), f"MarketTransaction.{field} must be integer cents"
    assert isinstance(data["price_deviation_bps"], int)
    assert data["conveyance_mode"] in (None, "WHOLE", "PARTIAL")


def assert_receiving_site_application(data: dict) -> None:
    assert_common_record_fields(data, "ReceivingSiteApplication")
    assert data["status"] in (
        "SUBMITTED", "DESIGN_REVIEW", "REVISIONS_REQUIRED", "DESIGN_APPROVED",
        "BACKING_DEFICIENT", "FINALIZED", "DENIED",
    ), data["status"]
    for field in (
        "base_units", "max_bonus_units", "required_backing_units", "provisional_bonus_units",
        "allocated_bonus_units", "backed_units", "pending_backed_units",
    ):
        assert isinstance(data[field], int), f"ReceivingSiteApplication.{field} must be an integer"
    assert isinstance(data["design_review_round"], int) and 0 <= data["design_review_round"] <= 2


def assert_certificate_redemption(data: dict) -> None:
    assert_common_record_fields(data, "CertificateRedemption")
    assert data["status"] in ("ALLOCATED", "HELD_PENDING_COMPLIANCE", "CONFIRMED", "RELEASED")
    assert isinstance(data["units"], int) and data["units"] > 0


def assert_monitoring_inspection(data: dict) -> None:
    assert_common_record_fields(data, "MonitoringInspection")
    assert data["finding"] in ("COMPLIANT", "MINOR_VIOLATION", "MAJOR_VIOLATION")
    assert data["status"] in ("OPEN", "CURE_PENDING", "CURED", "ESCALATED", "CLOSED")
    assert_two_decimal_places(data["severity_score"], "MonitoringInspection.severity_score")


def assert_program_evaluation(data: dict) -> None:
    assert_common_record_fields(data, "ProgramEvaluation")
    assert data["equity_weighting"] in ("ACREAGE_WEIGHTED", "PARCEL_COUNT_WEIGHTED")
    assert data["status"] in ("COMPUTED", "SUPERSEDED")
    assert_two_decimal_places(data["absorption_pct"], "ProgramEvaluation.absorption_pct")
    assert_two_decimal_places(data["equity_index"], "ProgramEvaluation.equity_index")
    assert_two_decimal_places(data["preserved_acres"], "ProgramEvaluation.preserved_acres")


# ── Program invariants ──────────────────────────────────────────────────────

def assert_certificate_units_conserved(cert: dict) -> None:
    """units_remaining = units_face - units_split_out - units_redeemed - units_retired,
    and units_encumbered never exceeds units_remaining."""
    expected = (
        cert["units_face"] - cert["units_split_out"]
        - cert["units_redeemed"] - cert["units_retired"]
    )
    assert cert["units_remaining"] == expected, (
        "certificate rights not conserved: units_remaining "
        f"{cert['units_remaining']} != {cert['units_face']} - {cert['units_split_out']} "
        f"- {cert['units_redeemed']} - {cert['units_retired']} = {expected}"
    )
    assert cert["units_encumbered"] <= cert["units_remaining"], (
        f"units_encumbered {cert['units_encumbered']} exceeds units_remaining "
        f"{cert['units_remaining']}"
    )


def assert_easement_units_conserved(easement: dict) -> None:
    """units_issued_total = units_redeemed_confirmed + units_retired + units_outstanding."""
    total = (
        easement["units_redeemed_confirmed"] + easement["units_retired"]
        + easement["units_outstanding"]
    )
    assert easement["units_issued_total"] == total, (
        "easement rights not conserved: units_issued_total "
        f"{easement['units_issued_total']} != {easement['units_redeemed_confirmed']} + "
        f"{easement['units_retired']} + {easement['units_outstanding']} = {total}"
    )


def program_cash_total(parties: list) -> int:
    """Summed cash_balance_cents plus fee_revenue_cents across every party."""
    return sum(p["cash_balance_cents"] + p["fee_revenue_cents"] for p in parties)


def assert_program_cash_conserved(before: int, after: int, note: str = "") -> None:
    assert before == after, (
        f"program-wide cash total moved{' ' + note if note else ''}: {before} -> {after}"
    )
