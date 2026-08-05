"""Entity assertions, timestamp helpers and domain invariant checkers."""

from datetime import datetime, timedelta, timezone
from typing import Optional

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .constants import CODE_STATUS_RANKS

# ---------------------------------------------------------------------------
# Timestamp handling
#
# Server-rendered instants and the instants supplied in request bodies are the
# same moments in time but may be written differently (three fractional digits
# versus none, `Z` versus an explicit offset). Every datetime comparison in this
# suite therefore parses both sides and compares instants, never strings.
# ---------------------------------------------------------------------------


def parse_instant(value: str) -> datetime:
    """Parse an ISO 8601 instant into a timezone-aware UTC datetime."""
    assert isinstance(value, str) and value, f"expected an ISO 8601 string, got {value!r}"
    text = value.strip()
    if text.endswith("Z") or text.endswith("z"):
        text = text[:-1] + "+00:00"
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def assert_same_instant(actual: str, expected: str, label: str = "timestamp") -> None:
    """Assert two ISO 8601 strings denote the same instant."""
    assert actual is not None, f"{label} is missing (expected {expected})"
    got = parse_instant(actual)
    want = parse_instant(expected)
    assert got == want, f"{label}: expected instant {expected}, got {actual}"


def assert_instant_equals_offset(
    actual: str, base: str, *, minutes: float = 0, hours: float = 0, days: float = 0,
    label: str = "timestamp",
) -> None:
    """Assert `actual` is `base` advanced by the supplied offset."""
    want = parse_instant(base) + timedelta(minutes=minutes, hours=hours, days=days)
    got = parse_instant(actual)
    assert got == want, (
        f"{label}: expected {want.isoformat()} "
        f"({base} + {days}d {hours}h {minutes}m), got {actual}"
    )


def assert_render_pattern(value: str, label: str = "timestamp") -> None:
    """Assert a server-emitted instant uses the YYYY-MM-DDTHH:MM:SS.mmmZ pattern."""
    assert isinstance(value, str), f"{label} must be a string, got {value!r}"
    assert is_iso8601_timestamp(value), f"{label} must be ISO 8601, got {value!r}"
    assert value.endswith("Z"), f"{label} must end with Z, got {value!r}"
    assert len(value) == 24 and value[19] == ".", (
        f"{label} must carry exactly three fractional-second digits, got {value!r}"
    )


# ---------------------------------------------------------------------------
# Common record properties
# ---------------------------------------------------------------------------
def assert_common_record_fields(data: dict, label: str = "record") -> None:
    """Every persisted record carries id, created_at, updated_at and version."""
    assert is_valid_uuid(data.get("id", "")), (
        f"{label}.id must be a bare server-minted UUID, got {data.get('id')!r}"
    )
    assert_render_pattern(data.get("created_at"), f"{label}.created_at")
    assert_render_pattern(data.get("updated_at"), f"{label}.updated_at")
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"{label}.version must be a positive integer, got {data.get('version')!r}"
    )


# ---------------------------------------------------------------------------
# Per-entity assertions
# ---------------------------------------------------------------------------
def assert_patient(data: dict) -> None:
    assert_common_record_fields(data, "Patient")
    assert data["program_status"] in (
        "REFERRED", "ACTIVE", "HOSPICE_ELECTED", "DECEASED",
    ), f"unexpected program_status {data['program_status']!r}"
    assert data["capacity_status"] in ("HAS_CAPACITY", "LACKS_CAPACITY")
    assert data["code_status"] in CODE_STATUS_RANKS
    assert data["code_status_rank"] == CODE_STATUS_RANKS[data["code_status"]], (
        "code_status_rank must always agree with code_status: "
        f"{data['code_status']} should be rank "
        f"{CODE_STATUS_RANKS[data['code_status']]}, got {data['code_status_rank']}"
    )
    assert isinstance(data["records_frozen"], bool)
    assert isinstance(data["mrn"], str) and data["mrn"]
    assert data["jurisdiction_code"] in ("JUR_TWO_WITNESS", "JUR_NOTARY")
    assert data["opioid_status"] in ("OPIOID_NAIVE", "OPIOID_TOLERANT")
    assert float(data["active_daily_mme"]) >= 0
    assert int(data["acp_minutes_claimed"]) >= 0
    assert int(data["acp_paid_cents_ytd"]) >= 0
    assert int(data["open_symptom_count"]) >= 0


def assert_referral(data: dict) -> None:
    assert_common_record_fields(data, "Referral")
    assert data["status"] in ("RECEIVED", "ACCEPTED", "DECLINED")
    assert data["triage_variant"] in ("PAYER_SOURCED", "CLINICIAN_SOURCED")
    assert isinstance(data["triage_score"], int)
    assert 0 <= data["triage_score"] <= 100, "triage_score is capped at 100"
    assert 0 <= data["re_referral_count"] <= 2


def assert_surrogate(data: dict) -> None:
    assert_common_record_fields(data, "SurrogateDesignation")
    assert data["status"] in ("PROPOSED", "ACTIVE", "REVOKED")
    assert data["hierarchy_rank"] in (1, 2, 3, 4, 5)
    assert isinstance(data["is_beneficiary"], bool)


def assert_document(data: dict) -> None:
    assert_common_record_fields(data, "AdvanceCareDocument")
    assert data["status"] in (
        "DRAFT", "PENDING_EXECUTION", "EXECUTED", "SUPERSEDED", "REVOKED",
    )
    assert data["document_type"] in ("LIVING_WILL", "HEALTHCARE_PROXY", "POLST")
    assert data["stated_code_status"] in CODE_STATUS_RANKS
    for counter in (
        "witness_signature_count",
        "notary_signature_count",
        "physician_signature_count",
        "patient_or_surrogate_signature_count",
    ):
        assert isinstance(data[counter], int) and data[counter] >= 0
    assert isinstance(data["execution_ready"], bool)
    assert isinstance(data["signature_log"], list)
    assert len(data["signature_log"]) == (
        data["witness_signature_count"]
        + data["notary_signature_count"]
        + data["physician_signature_count"]
        + data["patient_or_surrogate_signature_count"]
    ), "signature_log length must equal the sum of the four signature counters"


def assert_code_status_order(data: dict) -> None:
    assert_common_record_fields(data, "CodeStatusOrder")
    assert data["status"] in (
        "DRAFT", "ATTESTED", "CONFLICT_HOLD", "EFFECTIVE", "SUPERSEDED",
    )
    assert data["requested_code_status"] in CODE_STATUS_RANKS
    assert data["ladder_direction"] in ("DE_ESCALATION", "RE_ESCALATION", "NO_CHANGE")
    assert 0 <= data["attestation_count"] <= 2


def assert_care_plan(data: dict) -> None:
    assert_common_record_fields(data, "CarePlan")
    assert data["status"] in ("DRAFT", "ACTIVE", "UNDER_REVISION", "CLOSED")
    assert isinstance(data["problem_list"], list)
    assert isinstance(data["revision_number"], int) and data["revision_number"] >= 0


def assert_symptom_assessment(data: dict) -> None:
    assert_common_record_fields(data, "SymptomAssessment")
    assert data["triage_status"] in ("OPEN", "ACKNOWLEDGED", "RESOLVED")
    assert data["escalation_status"] in ("NONE", "ESCALATED", "DISPOSITIONED")
    assert data["severity_tier"] in ("MINIMAL", "MILD", "MODERATE", "SEVERE")
    assert isinstance(data["distress_score"], int)
    assert 0 <= data["distress_score"] <= 100, "distress_score is capped at 100"
    assert_render_pattern(data["response_due_at"], "SymptomAssessment.response_due_at")


def assert_conference(data: dict) -> None:
    assert_common_record_fields(data, "CareConference")
    assert data["status"] in (
        "SCHEDULED", "HELD", "QUORUM_FAILED", "ATTESTED", "CONSENT_INVALIDATED",
    )
    assert data["conference_type"] in ("IDT", "FAMILY")
    assert data["modality"] in ("TELEHEALTH", "IN_PERSON")
    assert isinstance(data["quorum_met"], bool)
    assert isinstance(data["attestation_complete"], bool)
    assert isinstance(data["consent_recorded"], bool)
    assert parse_instant(data["scheduled_end"]) > parse_instant(data["scheduled_start"])


def assert_medication_order(data: dict) -> None:
    assert_common_record_fields(data, "MedicationOrder")
    assert data["status"] in (
        "PENDING_VERIFICATION", "ACTIVE", "REVIEW_REQUIRED", "DISCONTINUED",
    )
    assert data["drug"] in (
        "MORPHINE_PO", "OXYCODONE_PO", "HYDROMORPHONE_PO", "FENTANYL_TD",
    )
    assert data["mme_variant"] in ("TOLERANT", "NAIVE")
    assert float(data["dose_amount"]) > 0
    assert 1 <= int(data["days_supply"]) <= 90
    assert_one_decimal_place(data["mme_daily"], "MedicationOrder.mme_daily")
    if data.get("breakthrough_drug") is None:
        assert data.get("breakthrough_dose_mg") is None, (
            "breakthrough_dose_mg must be null whenever breakthrough_drug is null"
        )


def assert_dme_inventory(data: dict) -> None:
    assert_common_record_fields(data, "DmeInventoryItem")
    assert data["device_type"] in (
        "OXYGEN_CONCENTRATOR", "HOSPITAL_BED", "WHEELCHAIR", "SUCTION_MACHINE",
    )
    assert isinstance(data["prior_auth_required"], bool)
    assert_inventory_conserved(data)


def assert_dme_order(data: dict) -> None:
    assert_common_record_fields(data, "DmeOrder")
    assert data["status"] in (
        "REQUESTED", "PENDING_AUTH", "SCHEDULED", "DELIVERED", "CLOSED",
    )
    assert 1 <= int(data["quantity"]) <= 10
    assert parse_instant(data["delivery_window_end"]) > parse_instant(
        data["delivery_window_start"]
    )


def assert_hospice_election(data: dict) -> None:
    assert_common_record_fields(data, "HospiceElection")
    assert data["status"] in (
        "PENDING_CERT", "CERTIFIED", "ELECTED", "REVOKED", "CLOSED_ON_DEATH",
    )
    assert 0 <= data["certification_count"] <= 2
    assert data["current_period_number"] >= 0
    assert data["cumulative_benefit_days"] >= 0
    assert data["revocation_count"] >= 0


def assert_escalation(data: dict) -> None:
    assert_common_record_fields(data, "OnCallEscalation")
    assert data["status"] in (
        "TIER_NOTIFIED", "ACKNOWLEDGED", "DISPOSITIONED", "CLOSED",
    )
    assert data["tier"] in (1, 2, 3)
    assert_render_pattern(data["tier_notified_at"], "OnCallEscalation.tier_notified_at")
    assert_render_pattern(data["ack_due_at"], "OnCallEscalation.ack_due_at")


def assert_claim(data: dict) -> None:
    assert_common_record_fields(data, "AcpBillingClaim")
    assert data["status"] in ("DRAFT", "ATTESTED", "SUBMITTED", "PAID", "DENIED")
    assert data["modality"] in ("TELEHEALTH", "IN_PERSON")
    assert 1 <= int(data["billable_units"]) <= 4
    for cents_field in (
        "allowed_amount_cents",
        "patient_responsibility_cents",
        "net_payable_cents",
    ):
        assert isinstance(data[cents_field], int), (
            f"{cents_field} must be whole cents held as an integer, "
            f"got {data[cents_field]!r}"
        )
    assert float(data["coinsurance_pct"]) in (0.1, 0.2)
    assert (
        data["net_payable_cents"]
        == data["allowed_amount_cents"] - data["patient_responsibility_cents"]
    ), "net_payable_cents must be allowed_amount_cents minus patient_responsibility_cents"
    assert isinstance(data["documentation_attested"], bool)


# ---------------------------------------------------------------------------
# Domain invariants
# ---------------------------------------------------------------------------
def assert_inventory_conserved(item: dict) -> None:
    """total_units equals available + reserved + delivered after every move."""
    total = item["total_units"]
    parts = item["available_units"] + item["reserved_units"] + item["delivered_units"]
    assert total == parts, (
        "equipment ledger drifted: total_units "
        f"{total} != available {item['available_units']} + reserved "
        f"{item['reserved_units']} + delivered {item['delivered_units']}"
    )
    assert item["available_units"] >= 0
    assert item["reserved_units"] >= 0
    assert item["delivered_units"] >= 0


def assert_one_decimal_place(value, label: str = "value") -> None:
    """mme_daily and breakthrough_dose_mg carry exactly one decimal place."""
    if value is None:
        return
    scaled = round(float(value) * 10)
    assert abs(float(value) * 10 - scaled) < 1e-6, (
        f"{label} must carry at most one decimal place, got {value!r}"
    )


def assert_mme_ledger(patient: dict, expected: float) -> None:
    actual = float(patient["active_daily_mme"])
    assert abs(actual - expected) < 1e-6, (
        f"active_daily_mme: expected {expected}, got {actual}"
    )


def assert_ids(data_list, expected_ids, label: str = "result set") -> None:
    got = [row["id"] for row in data_list]
    assert got == list(expected_ids), f"{label}: expected ids {list(expected_ids)}, got {got}"


def find_by_id(rows, row_id: str) -> Optional[dict]:
    for row in rows:
        if row.get("id") == row_id:
            return row
    return None
