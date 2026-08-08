"""Entity assertions, instant/date comparison helpers and invariant checkers."""

from datetime import date, datetime, timezone

import pytest

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .constants import THRESHOLDS

# ---------------------------------------------------------------------------
# Instant and calendar-date comparison
#
# Instant-valued fields (created_at, updated_at, api_request_timestamp,
# current_utc) are rendered with exactly three fractional digits and a
# trailing Z.  Comparing them as raw strings is wrong: two renderings of the
# same moment differ textually.  Every instant comparison in this suite goes
# through parse_instant / assert_same_instant.
#
# Date-valued fields are plain YYYY-MM-DD calendar dates.  They go through
# assert_calendar_date, which compares parsed date objects.
# ---------------------------------------------------------------------------


def parse_instant(value) -> datetime:
    """Parse an ISO 8601 UTC instant into an aware datetime."""
    assert isinstance(value, str) and value, f"Expected an instant string, got {value!r}"
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def assert_same_instant(actual, expected, field: str = "instant") -> None:
    """Assert two instant-valued strings denote the same moment in time."""
    got = parse_instant(actual)
    want = parse_instant(expected)
    assert got == want, (
        f"{field}: expected the instant {expected} ({want.isoformat()}), "
        f"got {actual} ({got.isoformat()})"
    )


def parse_calendar_date(value) -> date:
    """Parse a plain YYYY-MM-DD calendar date."""
    assert isinstance(value, str) and value, f"Expected a YYYY-MM-DD date, got {value!r}"
    assert "T" not in value, f"A date field must carry no time component, got {value!r}"
    return date.fromisoformat(value)


def assert_calendar_date(actual, expected, field: str = "date") -> None:
    """Assert a date-valued field equals the expected calendar date."""
    got = parse_calendar_date(actual)
    want = parse_calendar_date(expected)
    assert got == want, f"{field}: expected {want.isoformat()}, got {got.isoformat()}"


def assert_instant_rendering(value, field: str = "instant") -> None:
    """Assert the uniform instant rendering: three fractional digits, trailing Z."""
    assert isinstance(value, str), f"{field} must be a string, got {value!r}"
    assert is_iso8601_timestamp(value), f"{field} must be ISO 8601, got {value!r}"
    assert value.endswith("Z"), f"{field} must end with Z, got {value!r}"
    assert len(value) >= 24 and value[-5] == ".", (
        f"{field} must carry exactly three fractional-second digits, got {value!r}"
    )


def assert_is_null(value, field: str) -> None:
    assert value is None, f"{field} must be null, got {value!r}"


def approx_mm(value):
    """Millimetre quantities are carried to 2 decimal places."""
    return pytest.approx(value, abs=0.005)


def approx_rate(value):
    """Rates and pct_reduction are carried to 4 decimal places."""
    return pytest.approx(value, abs=0.00005)


def approx_index(value):
    """Apnoea-hypopnoea indices are carried to 1 decimal place."""
    return pytest.approx(value, abs=0.05)


# ---------------------------------------------------------------------------
# Common-field shape
# ---------------------------------------------------------------------------


def assert_versioned_row(data: dict, entity: str) -> None:
    """id + created_at + updated_at + version, per PRD 2.4 and 2.5."""
    assert is_valid_uuid(data.get("id", "")), f"{entity}.id must be a UUID string"
    assert_instant_rendering(data.get("created_at"), f"{entity}.created_at")
    assert_instant_rendering(data.get("updated_at"), f"{entity}.updated_at")
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"{entity}.version must be a positive integer, got {data.get('version')!r}"
    )


def assert_event_row(data: dict, entity: str) -> None:
    """id + created_at only — no updated_at and no version."""
    assert is_valid_uuid(data.get("id", "")), f"{entity}.id must be a UUID string"
    assert_instant_rendering(data.get("created_at"), f"{entity}.created_at")
    assert "updated_at" not in data, f"{entity} must not carry updated_at"
    assert "version" not in data, f"{entity} must not carry version"


# ---------------------------------------------------------------------------
# Per-entity assertions
# ---------------------------------------------------------------------------


def assert_provider(data: dict) -> None:
    assert_versioned_row(data, "Provider")
    assert isinstance(data["npi"], str) and len(data["npi"]) == 10
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert data["provider_type"] in ("SLEEP_PHYSICIAN", "DENTIST", "DENTAL_LAB")
    assert data["status"] in ("ACTIVE", "SUSPENDED")
    assert isinstance(data["open_efficacy_loop_count"], int)
    assert "state_license" in data and "dme_supplier_number" in data


def assert_payer(data: dict) -> None:
    assert_versioned_row(data, "Payer")
    assert isinstance(data["name"], str) and data["name"]
    assert data["payer_kind"] in ("MEDICAL", "DENTAL")
    assert isinstance(data["prior_auth_required"], bool)
    assert isinstance(data["useful_lifetime_months"], int)
    assert 0.0 <= data["coinsurance_pct"] <= 1.0
    assert isinstance(data["appeal_limit"], int)
    assert isinstance(data["residual_ahi_target"], (int, float))
    assert isinstance(data["pct_reduction_target"], (int, float))


def assert_patient(data: dict) -> None:
    assert_versioned_row(data, "Patient")
    assert isinstance(data["mrn"], str) and data["mrn"]
    assert isinstance(data["full_name"], str) and data["full_name"]
    parse_calendar_date(data["date_of_birth"])
    assert is_valid_uuid(data["medical_payer_id"])
    assert "dental_payer_id" in data
    assert isinstance(data["deductible_remaining_cents"], int)
    assert data["deductible_remaining_cents"] >= 0
    assert 0 <= data["epworth_score"] <= 24
    assert isinstance(data["records_frozen"], bool)


def assert_sleep_study(data: dict) -> None:
    assert_versioned_row(data, "SleepStudy")
    assert is_valid_uuid(data["patient_id"])
    assert is_valid_uuid(data["ordering_physician_id"])
    assert data["modality"] in ("HSAT", "PSG")
    assert data["study_purpose"] in ("DIAGNOSTIC", "EFFICACY")
    assert data["status"] in ("ORDERED", "DIAGNOSTIC_VALID", "NON_DIAGNOSTIC")
    assert data["severity_band"] in (None, "NONE", "MILD", "MODERATE", "SEVERE")
    assert isinstance(data["repeat_count"], int)
    for key in ("appliance_id", "performed_on", "respiratory_events",
                "recording_minutes", "sleep_minutes", "severity_index"):
        assert key in data, f"SleepStudy must serialize {key}"


def assert_referral(data: dict) -> None:
    assert_versioned_row(data, "Referral")
    assert is_valid_uuid(data["patient_id"])
    assert is_valid_uuid(data["referring_physician_id"])
    assert is_valid_uuid(data["treating_dentist_id"])
    assert data["referring_physician_id"] != data["treating_dentist_id"]
    assert data["cpap_history"] in ("NONE", "FAILURE", "INTOLERANCE", "REFUSAL")
    assert data["loop_status"] in ("OPEN", "CLOSED")
    assert data["status"] in ("ISSUED", "ACCEPTED", "DECLINED", "EXPIRED", "CLOSED")
    assert data["severity_band_at_referral"] in (
        None, "NONE", "MILD", "MODERATE", "SEVERE",
    )
    assert data["eligibility_basis"] in (
        None, "FIRST_LINE_MILD_MODERATE", "CPAP_INTOLERANT_SEVERE",
    )


def assert_written_order(data: dict) -> None:
    assert_versioned_row(data, "WrittenOrder")
    assert is_valid_uuid(data["patient_id"])
    assert is_valid_uuid(data["ordering_physician_id"])
    assert data["item_hcpcs"] in ("E0486", "A9270", "K0739")
    parse_calendar_date(data["order_date"])
    parse_calendar_date(data["f2f_encounter_date"])
    assert data["status"] in ("DRAFT", "SIGNED", "SUPERSEDED")
    assert "signed_on" in data and "f2f_age_days" in data


def assert_prior_auth(data: dict) -> None:
    assert_versioned_row(data, "PriorAuth")
    assert is_valid_uuid(data["patient_id"])
    assert is_valid_uuid(data["payer_id"])
    assert is_valid_uuid(data["referral_id"])
    assert data["requested_hcpcs"] in ("E0486", "A9270", "K0739")
    assert data["status"] in (
        "SUBMITTED", "APPROVED", "DENIED", "APPEALED", "DENIED_FINAL", "EXPIRED",
    )
    assert isinstance(data["appeal_attempts"], int)
    assert data["denial_reason"] in (
        None, "NOT_MEDICALLY_NECESSARY", "MISSING_DOCUMENTATION", "NON_COVERED_ITEM",
    )


def assert_lab_order(data: dict) -> None:
    assert_versioned_row(data, "LabOrder")
    assert is_valid_uuid(data["referral_id"])
    assert is_valid_uuid(data["lab_provider_id"])
    assert data["appliance_kind"] in ("CUSTOM_FABRICATED", "PREFABRICATED")
    assert data["capture_method"] in ("PVS_IMPRESSION", "DIGITAL_SCAN")
    assert 4.00 <= data["max_protrusive_mm"] <= 12.00
    assert isinstance(data["remake_count"], int)
    assert data["status"] in (
        "RECORDS_CAPTURED", "IN_FABRICATION", "SHIPPED",
        "RECEIVED_ACCEPTED", "REMAKE_REQUIRED", "CANCELLED",
    )


def assert_appliance_lot(data: dict) -> None:
    assert_versioned_row(data, "ApplianceLot")
    assert isinstance(data["manufacturer"], str) and data["manufacturer"]
    assert isinstance(data["lot_code"], str) and data["lot_code"]
    assert data["status"] in ("ACTIVE", "RECALL_ISSUED", "REMEDIATION_COMPLETE")
    for counter in ("affected_device_count", "remediated_count",
                    "pending_remediation_count", "retired_count"):
        assert isinstance(data[counter], int), f"ApplianceLot.{counter} must be an int"
    assert data["recall_severity"] in (None, "CLASS_I", "CLASS_II", "CLASS_III")


def assert_appliance(data: dict) -> None:
    assert_versioned_row(data, "Appliance")
    assert is_valid_uuid(data["patient_id"])
    assert is_valid_uuid(data["lab_order_id"])
    assert is_valid_uuid(data["lot_id"])
    assert isinstance(data["serial_number"], str) and data["serial_number"]
    assert isinstance(data["has_microrecorder"], bool)
    assert data["appliance_kind"] in ("CUSTOM_FABRICATED", "PREFABRICATED")
    assert data["hcpcs_code"] in ("E0486", "A9270")
    assert data["lifecycle_status"] in (
        "FABRICATED", "DELIVERED", "IN_TITRATION", "TITRATION_SUSPENDED",
        "TITRATION_PLATEAU", "EFFICACY_PENDING", "ACTIVE_THERAPY",
        "RETIRED", "REPLACED",
    )
    assert data["device_hold_status"] in ("NONE", "RECALL_HOLD")
    assert data["recall_status"] in ("NOT_SCHEDULED", "NOT_DUE", "DUE", "LAPSED")
    assert data["pod_method"] in (None, "IN_PERSON", "SHIPPED")
    assert isinstance(data["applied_visit_count"], int)
    assert isinstance(data["recall_cycle_index"], int)


def assert_titration_visit(data: dict) -> None:
    assert_versioned_row(data, "TitrationVisit")
    assert is_valid_uuid(data["appliance_id"])
    assert is_valid_uuid(data["performed_by_dentist_id"])
    assert isinstance(data["visit_seq"], int) and data["visit_seq"] >= 1
    parse_calendar_date(data["scheduled_for"])
    assert 0.25 <= data["requested_increment_mm"] <= 2.00
    assert data["side_effect_severity"] in (None, "NONE", "MILD", "MODERATE", "SEVERE")
    assert data["status"] in (
        "SCHEDULED", "APPLIED", "REDUCED", "HELD", "SUPERSEDED", "VOIDED_BY_HOLD",
    )


def assert_adherence_download(data: dict) -> None:
    assert_event_row(data, "AdherenceDownload")
    assert is_valid_uuid(data["appliance_id"])
    assert data["source"] in ("OBJECTIVE_MICRORECORDER", "PATIENT_ATTESTED")
    parse_calendar_date(data["window_start"])
    parse_calendar_date(data["window_end"])
    assert 0 <= data["nights_at_or_above_min_hours"] <= data["nights_recorded"]
    assert data["nights_recorded"] <= THRESHOLDS["ADHERENCE_WINDOW_DAYS"]
    assert isinstance(data["compliant"], bool)


def assert_efficacy_report(data: dict) -> None:
    assert_versioned_row(data, "EfficacyReport")
    assert is_valid_uuid(data["patient_id"])
    assert is_valid_uuid(data["referral_id"])
    assert is_valid_uuid(data["appliance_id"])
    assert is_valid_uuid(data["efficacy_study_id"])
    assert data["outcome"] in ("COMPLETE", "PARTIAL", "FAILED")
    assert isinstance(data["meets_absolute_target"], bool)
    assert isinstance(data["meets_relative_target"], bool)
    assert isinstance(data["revision_count"], int)
    assert data["status"] in (
        "DRAFT", "SUBMITTED", "SIGNED", "DISPUTED", "WITHDRAWN", "SUPERSEDED",
    )


def assert_claim(data: dict) -> None:
    assert_versioned_row(data, "Claim")
    assert is_valid_uuid(data["patient_id"])
    assert is_valid_uuid(data["payer_id"])
    assert is_valid_uuid(data["appliance_id"])
    assert data["claim_type"] in (
        "INITIAL_DEVICE", "REPAIR", "REPLACEMENT", "CONTINUED_USE",
    )
    assert data["hcpcs_code"] in ("E0486", "A9270", "K0739")
    parse_calendar_date(data["date_of_service"])
    assert isinstance(data["billed_cents"], int) and data["billed_cents"] >= 0
    assert isinstance(data["appeal_attempts"], int)
    assert data["status"] in (
        "DRAFT", "SUBMITTED", "PAID", "DENIED", "APPEALED", "DENIED_FINAL", "VOIDED",
    )


def assert_repair_order(data: dict) -> None:
    assert_versioned_row(data, "RepairOrder")
    assert is_valid_uuid(data["appliance_id"])
    assert data["reason"] in ("DEFECT", "WEAR", "ABUSE", "LOSS")
    parse_calendar_date(data["reported_on"])
    assert isinstance(data["labor_minutes"], int) and data["labor_minutes"] >= 0
    assert isinstance(data["in_warranty"], bool)
    assert isinstance(data["billable"], bool)
    assert isinstance(data["labor_units"], int)
    assert isinstance(data["repair_charge_cents"], int)
    assert isinstance(data["resets_useful_lifetime"], bool)
    assert data["status"] in (
        "OPEN", "IN_LAB", "CLOSED_REPAIRED", "CLOSED_NOT_COVERED",
    )


def assert_audit_hold(data: dict) -> None:
    assert_versioned_row(data, "AuditHold")
    assert is_valid_uuid(data["patient_id"])
    assert is_valid_uuid(data["payer_id"])
    parse_calendar_date(data["opened_on"])
    assert data["status"] in ("OPEN", "CLOSED")


# ---------------------------------------------------------------------------
# The three conservation invariants (PRD 2.10)
# ---------------------------------------------------------------------------


def assert_protrusive_conservation(appliance: dict, visits: list) -> None:
    """Conservation 1 — current advancement equals start plus applied/reduced sum."""
    contributing = [v for v in visits if v["status"] in ("APPLIED", "REDUCED")]
    total = appliance["starting_advancement_mm"] + sum(
        v["applied_increment_mm"] for v in contributing
    )
    assert appliance["current_advancement_mm"] == approx_mm(total), (
        "Conservation 1 broken: current_advancement_mm "
        f"{appliance['current_advancement_mm']} != starting {appliance['starting_advancement_mm']}"
        f" + sum of applied/reduced increments ({total})"
    )
    assert appliance["applied_visit_count"] == len(contributing), (
        "applied_visit_count must be the size of the APPLIED/REDUCED set"
    )
    assert 0.00 <= appliance["current_advancement_mm"] <= appliance["max_protrusive_mm"] + 0.005


def assert_money_conservation(claim: dict) -> None:
    """Conservation 2 — money legs of a PAID claim reconcile."""
    assert claim["status"] == "PAID", "money conservation applies to a PAID claim"
    assert claim["allowed_cents"] == claim["payer_paid_cents"] + claim[
        "patient_responsibility_cents"
    ], "Conservation 2 broken: allowed != payer_paid + patient_responsibility"
    assert claim["billed_cents"] == claim["allowed_cents"] + claim["adjustment_cents"], (
        "Conservation 2 broken: billed != allowed + adjustment"
    )


def assert_denied_claim_writes_no_money(claim: dict) -> None:
    for field in (
        "deductible_applied_cents",
        "coinsurance_cents",
        "patient_responsibility_cents",
        "payer_paid_cents",
    ):
        assert_is_null(claim[field], f"Claim.{field} on a denied claim")


def assert_lot_population_conservation(lot: dict) -> None:
    """Conservation 3 — affected == remediated + pending."""
    assert lot["affected_device_count"] == lot["remediated_count"] + lot[
        "pending_remediation_count"
    ], (
        "Conservation 3 broken: affected_device_count "
        f"{lot['affected_device_count']} != remediated {lot['remediated_count']}"
        f" + pending {lot['pending_remediation_count']}"
    )
