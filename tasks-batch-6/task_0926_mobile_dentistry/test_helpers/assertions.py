"""Entity assertions, instant/date comparison helpers and conservation-identity checkers.

Instant comparison policy
-------------------------
PRD §2.4 states that "Comparisons between instants are performed at millisecond
resolution on the underlying values, not on their string renderings."  Every
assertion in this suite that concerns an instant-valued field therefore goes
through :func:`assert_same_instant` (or :func:`parse_instant`), never through a
raw ``==`` on the rendered string.
"""

from datetime import date, datetime, timedelta, timezone
from typing import Optional

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .constants import (
    CONSENT_TIER_RANK,
    PROCEDURE_CHAIR_MINUTES,
    PROCEDURE_CHARGE_CENTS,
    PROCEDURE_REQUIRED_TIER,
)


# ─── Instant and date helpers ────────────────────────────────────────────────

def parse_instant(value: str) -> datetime:
    """Parse an ISO 8601 UTC instant into a timezone-aware datetime.

    Accepts any fractional-second precision (or none) and either a ``Z`` suffix
    or an explicit ``+00:00`` offset, so that comparisons are semantic rather
    than textual.
    """
    assert isinstance(value, str) and value, f"Expected an ISO 8601 instant string, got {value!r}"
    raw = value.strip()
    if raw.endswith("Z"):
        raw = raw[:-1] + "+00:00"
    parsed = datetime.fromisoformat(raw)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _truncate_to_ms(value: datetime) -> datetime:
    return value.replace(microsecond=(value.microsecond // 1000) * 1000)


def assert_same_instant(actual: Optional[str], expected: str, label: str = "instant") -> None:
    """Assert two ISO 8601 instants denote the same moment at millisecond resolution."""
    assert actual is not None, f"{label}: expected {expected}, got None"
    got = _truncate_to_ms(parse_instant(actual))
    want = _truncate_to_ms(parse_instant(expected))
    assert got == want, f"{label}: expected instant {expected} ({want}), got {actual} ({got})"


def assert_instant_rendering(value: str, label: str = "instant") -> None:
    """Assert a rendered instant is a valid ISO 8601 UTC timestamp."""
    assert is_iso8601_timestamp(value), f"{label}: not an ISO 8601 UTC timestamp: {value!r}"


def parse_calendar_date(value: str) -> date:
    """Parse a bare ``YYYY-MM-DD`` calendar date (PRD §2.4 date family)."""
    assert isinstance(value, str) and value, f"Expected a YYYY-MM-DD date string, got {value!r}"
    return date.fromisoformat(value.strip())


def assert_same_date(actual: Optional[str], expected: str, label: str = "date") -> None:
    """Assert two bare calendar dates denote the same day."""
    assert actual is not None, f"{label}: expected {expected}, got None"
    got = parse_calendar_date(actual)
    want = parse_calendar_date(expected)
    assert got == want, f"{label}: expected {expected}, got {actual}"


def add_business_days(base_iso: str, business_days: int) -> str:
    """Step forward one calendar day at a time, counting only Monday–Friday.

    Mirrors PRD §2.5's business-day addition: the time of day is preserved and no
    holiday calendar is applied. Returned in canonical three-fractional-digit form.
    """
    moment = parse_instant(base_iso)
    counted = 0
    while counted < business_days:
        moment = moment + timedelta(days=1)
        if moment.weekday() < 5:
            counted += 1
    return moment.strftime("%Y-%m-%dT%H:%M:%S.") + f"{moment.microsecond // 1000:03d}Z"


# ─── Common-field assertions ─────────────────────────────────────────────────

def assert_common_fields(data: dict, entity: str = "resource") -> None:
    """Every one of the fifteen entity types carries id, created_at, updated_at and version."""
    assert is_valid_uuid(data.get("id", "")), f"{entity}.id must be a bare UUID, got {data.get('id')!r}"
    assert_instant_rendering(data.get("created_at", ""), f"{entity}.created_at")
    assert_instant_rendering(data.get("updated_at", ""), f"{entity}.updated_at")
    assert isinstance(data.get("version"), int), f"{entity}.version must be an integer"
    assert data["version"] >= 1, f"{entity}.version starts at 1, got {data['version']}"


# ─── Per-entity assertions ───────────────────────────────────────────────────

def assert_program_period(data: dict) -> None:
    assert_common_fields(data, "ProgramPeriod")
    assert isinstance(data["name"], str) and 1 <= len(data["name"]) <= 120
    parse_calendar_date(data["starts_on"])
    parse_calendar_date(data["ends_on"])
    assert parse_calendar_date(data["starts_on"]) < parse_calendar_date(data["ends_on"])
    assert data["status"] in ("OPEN", "REPORTING", "SUBMITTED", "CLOSED")


def assert_site(data: dict) -> None:
    assert_common_fields(data, "Site")
    assert isinstance(data["name"], str) and 1 <= len(data["name"]) <= 160
    assert data["site_type"] in ("SCHOOL", "SNF")
    assert isinstance(data["state_code"], str) and len(data["state_code"]) == 2
    assert data["state_code"].isupper()
    assert data["status"] in ("ACTIVE", "SUSPENDED")
    assert data["roster_disclosure_level"] in ("SUMMARY_ONLY", "CLINICAL_DETAIL")
    assert isinstance(data["active_hold_count"], int) and data["active_hold_count"] >= 0


def assert_site_hold(data: dict) -> None:
    assert_common_fields(data, "SiteHold")
    assert is_valid_uuid(data["site_id"])
    assert data["hold_type"] in ("WEATHER_CLOSURE", "OUTBREAK_LOCKDOWN", "ADMINISTRATIVE")
    assert parse_instant(data["starts_at"]) < parse_instant(data["ends_at"])
    assert data["hold_status"] in ("ACTIVE", "RELEASED")
    assert isinstance(data["blocked_visit_count"], int) and data["blocked_visit_count"] >= 0


def assert_patient(data: dict) -> None:
    assert_common_fields(data, "Patient")
    assert is_valid_uuid(data["site_id"])
    assert data["patient_type"] in ("STUDENT", "RESIDENT")
    assert isinstance(data["external_ref"], str) and data["external_ref"]
    assert isinstance(data["first_name"], str) and data["first_name"]
    assert isinstance(data["last_name"], str) and data["last_name"]
    parse_calendar_date(data["date_of_birth"])
    assert isinstance(data["household_size"], int) and data["household_size"] >= 1
    if data.get("annual_household_income_cents") is not None:
        assert isinstance(data["annual_household_income_cents"], int)
        assert data["annual_household_income_cents"] >= 0
    assert data["capacity_determination"] in ("NOT_ASSESSED", "HAS_CAPACITY", "LACKS_CAPACITY")
    assert isinstance(data["varnish_applications_in_period"], int)
    assert data["varnish_applications_in_period"] >= 0
    if data.get("last_varnish_date") is not None:
        parse_calendar_date(data["last_varnish_date"])


def assert_consent(data: dict) -> None:
    assert_common_fields(data, "Consent")
    assert is_valid_uuid(data["patient_id"])
    assert is_valid_uuid(data["site_id"])
    assert is_valid_uuid(data["program_period_id"])
    assert data["regime"] in ("SCHOOL_GUARDIAN", "SNF_RESPONSIBLE_PARTY")
    assert data["scope_tier"] in CONSENT_TIER_RANK
    assert data["status"] in (
        "PENDING_VERIFICATION", "ACTIVE", "REVOKED", "EXPIRED", "SUPERSEDED",
    )
    assert_instant_rendering(data["signed_at"], "Consent.signed_at")
    if data.get("expires_at") is not None:
        assert_instant_rendering(data["expires_at"], "Consent.expires_at")
    assert isinstance(data["invalidated_procedure_count"], int)


def assert_portable_unit(data: dict) -> None:
    assert_common_fields(data, "PortableUnit")
    assert isinstance(data["unit_code"], str) and data["unit_code"]
    assert data["status"] in ("AVAILABLE", "IN_SERVICE", "QUARANTINED")
    assert data["calibration_status"] in ("CURRENT", "DUE", "EXPIRED")
    if data.get("last_calibrated_on") is not None:
        parse_calendar_date(data["last_calibrated_on"])
    if data.get("calibration_due_on") is not None:
        parse_calendar_date(data["calibration_due_on"])


def assert_sterilization_load(data: dict) -> None:
    assert_common_fields(data, "SterilizationLoad")
    assert is_valid_uuid(data["portable_unit_id"])
    assert is_valid_uuid(data["loaded_by_staff_id"])
    assert isinstance(data["load_number"], str) and data["load_number"]
    assert_instant_rendering(data["cycle_completed_at"], "SterilizationLoad.cycle_completed_at")
    assert_instant_rendering(data["incubation_ends_at"], "SterilizationLoad.incubation_ends_at")
    assert data["spore_result"] in ("PENDING", "PASSED", "FAILED")
    assert isinstance(data["auto_failed"], bool)
    assert isinstance(data["tainted_procedure_count"], int)


def assert_staff_member(data: dict) -> None:
    assert_common_fields(data, "StaffMember")
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert data["staff_role"] in (
        "DENTIST", "HYGIENIST", "PUBLIC_HEALTH_HYGIENIST", "DENTAL_ASSISTANT",
    )
    assert isinstance(data["license_number"], str) and data["license_number"]
    assert isinstance(data["license_state"], str) and len(data["license_state"]) == 2
    assert data["supervision_level"] in ("DIRECT", "INDIRECT", "GENERAL", "SELF")
    assert data["credential_status"] in ("ACTIVE", "LAPSED", "INACTIVE")


def assert_site_visit(data: dict) -> None:
    assert_common_fields(data, "SiteVisit")
    assert is_valid_uuid(data["site_id"])
    assert is_valid_uuid(data["program_period_id"])
    assert is_valid_uuid(data["portable_unit_id"])
    assert is_valid_uuid(data["lead_staff_id"])
    assert parse_instant(data["scheduled_start_at"]) < parse_instant(data["scheduled_end_at"])
    assert isinstance(data["chair_count"], int) and data["chair_count"] >= 1
    assert isinstance(data["capacity_chair_minutes"], int)
    assert isinstance(data["booked_chair_minutes"], int)
    assert data["status"] in (
        "SCHEDULED", "HOLD_BLOCKED", "IN_PROGRESS", "COMPLETED", "CANCELLED",
    )
    assert isinstance(data["reschedule_count"], int) and data["reschedule_count"] >= 0


def assert_coverage(data: dict) -> None:
    assert_common_fields(data, "Coverage")
    assert is_valid_uuid(data["patient_id"])
    assert data["payer_type"] in ("MEDICAID_MCO", "COMMERCIAL_FFS", "UNINSURED")
    assert data["verification_status"] in ("UNVERIFIED", "VERIFIED", "EXPIRED")
    if data.get("sliding_fee_band") is not None:
        assert data["sliding_fee_band"] in ("A", "B", "C", "D", "E")
    if data.get("fpl_percent") is not None:
        assert isinstance(data["fpl_percent"], (int, float))


def assert_encounter(data: dict) -> None:
    assert_common_fields(data, "Encounter")
    assert is_valid_uuid(data["site_visit_id"])
    assert is_valid_uuid(data["patient_id"])
    assert is_valid_uuid(data["consent_id"])
    assert data["clinical_status"] in (
        "REGISTERED", "SCREENED", "EXAMINED", "TREATED", "CLOSED", "DEFERRED", "NO_SHOW",
    )
    assert data["billing_status"] in ("UNBILLED", "PRICED", "CLAIMED", "PAID", "DENIED")
    if data.get("triage_band") is not None:
        assert data["triage_band"] in ("URGENT", "EARLY_CARE_NEEDED", "NO_OBVIOUS_PROBLEM")
    if data.get("pricing_regime") is not None:
        assert data["pricing_regime"] in (
            "MEDICAID_ENCOUNTER_RATE", "COMMERCIAL_FEE_SCHEDULE", "UNINSURED_SLIDING_FEE",
        )
    for money in (
        "subtotal_cents", "supply_surcharge_cents", "total_charge_cents",
        "allowed_amount_cents", "patient_responsibility_cents",
        "plan_paid_cents", "write_off_cents",
    ):
        assert isinstance(data[money], int), f"Encounter.{money} must be whole integer cents"
    assert isinstance(data["tainted_procedure_count"], int)


def assert_procedure(data: dict) -> None:
    assert_common_fields(data, "Procedure")
    assert is_valid_uuid(data["encounter_id"])
    code = data["procedure_code"]
    assert code in PROCEDURE_CHARGE_CENTS, f"Unknown procedure_code {code!r}"
    assert data["required_tier"] == PROCEDURE_REQUIRED_TIER[code]
    assert data["chair_minutes"] == PROCEDURE_CHAIR_MINUTES[code]
    assert data["charge_cents"] == PROCEDURE_CHARGE_CENTS[code]
    assert data["status"] in ("PLANNED", "PERFORMED", "INELIGIBLE", "VOIDED", "TAINTED")
    if data.get("tooth_number") is not None:
        assert 1 <= data["tooth_number"] <= 32
    if data.get("surface") is not None:
        assert data["surface"] in ("O", "B", "L", "M", "D")


def assert_treatment_plan(data: dict) -> None:
    assert_common_fields(data, "TreatmentPlan")
    assert is_valid_uuid(data["encounter_id"])
    assert is_valid_uuid(data["patient_id"])
    assert is_valid_uuid(data["authoring_staff_id"])
    assert data["plan_status"] in ("DRAFT", "ACTIVE", "COMPLETED", "SUPERSEDED", "CANCELLED")
    assert data["urgency_band"] in ("URGENT", "EARLY_CARE_NEEDED", "NO_OBVIOUS_PROBLEM")
    assert data["follow_up_status"] in ("NOT_DUE", "DUE", "OVERDUE", "CONTACTED")
    assert isinstance(data["contact_attempt_count"], int)
    assert isinstance(data["planned_procedure_codes"], list)


def assert_referral(data: dict) -> None:
    assert_common_fields(data, "Referral")
    assert is_valid_uuid(data["treatment_plan_id"])
    assert is_valid_uuid(data["patient_id"])
    assert isinstance(data["dental_home_name"], str) and data["dental_home_name"]
    assert data["status"] in (
        "OPEN", "SENT", "ACCEPTED", "DECLINED", "NO_RESPONSE", "COMPLETED", "ABANDONED",
    )
    assert isinstance(data["attempt_count"], int) and data["attempt_count"] >= 0


def assert_report(data: dict) -> None:
    assert_common_fields(data, "Report")
    assert is_valid_uuid(data["program_period_id"])
    assert data["report_type"] in ("PARENT", "FACILITY_ROSTER", "PROGRAM_PERIOD")
    assert data["status"] in ("DRAFT", "GENERATED", "STALE", "SUBMITTED")


# ─── Conservation identities (PRD §2.10) ─────────────────────────────────────

def assert_money_split_closes(encounter: dict) -> None:
    """total_charge_cents == plan_paid_cents + patient_responsibility_cents + write_off_cents."""
    total = encounter["total_charge_cents"]
    parts = (
        encounter["plan_paid_cents"]
        + encounter["patient_responsibility_cents"]
        + encounter["write_off_cents"]
    )
    assert total == parts, (
        "Money split must close exactly: total_charge_cents "
        f"{total} != plan_paid {encounter['plan_paid_cents']} + patient_responsibility "
        f"{encounter['patient_responsibility_cents']} + write_off {encounter['write_off_cents']}"
    )


def assert_chair_ledger_matches(visit: dict, live_procedures: list) -> None:
    """booked_chair_minutes == sum of chair_minutes over PLANNED-or-PERFORMED procedures."""
    expected = sum(
        p["chair_minutes"] for p in live_procedures if p["status"] in ("PLANNED", "PERFORMED")
    )
    assert visit["booked_chair_minutes"] == expected, (
        f"booked_chair_minutes {visit['booked_chair_minutes']} != sum over live procedures {expected}"
    )
