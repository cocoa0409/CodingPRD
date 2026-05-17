"""Entity assertions and domain invariant checkers.

These check the response shape and domain invariants required by the
PRD contract. They are intentionally permissive on optional fields —
when PRD prose is silent on a specific projection, the assertion does
not pin it.
"""
from __future__ import annotations

import re
from typing import Any, Dict

from prd_bench_local_runner.testing import (
    is_iso8601_timestamp,
    is_valid_uuid,
)


# ---------------------------------------------------------------------------
# ISO date helper — PRD §3.1 etc. use YYYY-MM-DD calendar dates.
# ---------------------------------------------------------------------------
_ISO_DATE_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def is_iso8601_date(s: str) -> bool:
    """PRD uses 'YYYY-MM-DD' ISO 8601 calendar dates for assessment_date,
    visit_date, license_expiration_date, start_date, end_date, and
    recert_due_date.
    """
    return isinstance(s, str) and bool(_ISO_DATE_PATTERN.match(s))


# ---------------------------------------------------------------------------
# Common-fields helpers — PRD §2.4
# ---------------------------------------------------------------------------
def _assert_id_and_created_at(data: Dict[str, Any]) -> None:
    """PRD §2.4: "a system-managed id (UUID string, no type prefix), a
    created_at ISO 8601 UTC timestamp with three fractional digits
    indicating when it was first written"."""
    assert "id" in data, f"missing id; got keys: {list(data)}"
    assert is_valid_uuid(data["id"]), (
        f"id must be a UUID without type prefix, got {data['id']!r}"
    )
    assert "created_at" in data, "missing created_at"
    assert is_iso8601_timestamp(data["created_at"]), (
        f"created_at must be ISO 8601, got {data['created_at']!r}"
    )


def _assert_updated_at_and_version(data: Dict[str, Any]) -> None:
    """PRD §2.4: "an updated_at ISO 8601 UTC timestamp refreshed on any
    subsequent mutation, and a version integer that begins at 1 and
    increases by exactly 1 every time the resource is mutated."""
    assert "updated_at" in data, "missing updated_at"
    assert is_iso8601_timestamp(data["updated_at"]), (
        f"updated_at must be ISO 8601, got {data['updated_at']!r}"
    )
    assert "version" in data, "missing version"
    assert isinstance(data["version"], int) and data["version"] >= 1, (
        f"version must be a positive integer, "
        f"got {data.get('version')!r}"
    )


def _assert_no_updated_at_or_version(data: Dict[str, Any]) -> None:
    """PRD §2.4: "MileageLog is immutable once recorded; the row carries
    id and created_at but does not carry updated_at and does not carry
    version — both fields are absent from the JSON response."""
    assert "updated_at" not in data, (
        "MileageLog must not carry updated_at"
    )
    assert "version" not in data, (
        "MileageLog must not carry version"
    )


# ---------------------------------------------------------------------------
# Patient — PRD §3.1
# ---------------------------------------------------------------------------
def assert_patient(data: Dict[str, Any]) -> None:
    _assert_id_and_created_at(data)
    _assert_updated_at_and_version(data)
    assert isinstance(data.get("full_name"), str) and data["full_name"]
    assert isinstance(data.get("medicare_id"), str) and data["medicare_id"]
    assert isinstance(data.get("home_zip"), str)
    # PRD §3.1 / §2.6: "The system computes wage_index from home_zip at
    # patient creation and stores it on the patient row."
    assert "wage_index" in data, "missing wage_index"
    assert isinstance(data["wage_index"], (int, float))
    assert data["wage_index"] > 0


# ---------------------------------------------------------------------------
# Clinician — PRD §3.2
# ---------------------------------------------------------------------------
def assert_clinician(data: Dict[str, Any]) -> None:
    _assert_id_and_created_at(data)
    _assert_updated_at_and_version(data)
    assert isinstance(data.get("full_name"), str) and data["full_name"]
    # PRD §3.2: discipline is one of SN, PT, OT, SLP, HHA.
    assert data.get("discipline") in {"SN", "PT", "OT", "SLP", "HHA"}
    # PRD §3.2: license_expiration_date is a YYYY-MM-DD string.
    assert is_iso8601_date(data.get("license_expiration_date", "")), (
        "license_expiration_date must be YYYY-MM-DD, got "
        f"{data.get('license_expiration_date')!r}"
    )
    # PRD §3.2: status is either AVAILABLE or SUSPENDED.
    assert data.get("status") in {"AVAILABLE", "SUSPENDED"}


# ---------------------------------------------------------------------------
# OASISAssessment — PRD §3.3
# ---------------------------------------------------------------------------
def assert_oasis_assessment(data: Dict[str, Any]) -> None:
    _assert_id_and_created_at(data)
    _assert_updated_at_and_version(data)
    assert is_valid_uuid(data.get("patient_id", ""))
    # PRD §3.3: assessment_reason is START_OF_CARE | RECERTIFICATION |
    # RESUMPTION_OF_CARE.
    assert data.get("assessment_reason") in {
        "START_OF_CARE", "RECERTIFICATION", "RESUMPTION_OF_CARE",
    }
    assert is_iso8601_date(data.get("assessment_date", ""))
    # PRD §3.3: clinical_grouping enum.
    assert data.get("clinical_grouping") in {
        "MMTA_OTHER", "NEURO", "WOUND", "MS_REHAB",
        "BEHAVIORAL", "COMPLEX",
    }
    # PRD §3.3: functional_impairment_level enum.
    assert data.get("functional_impairment_level") in {
        "LOW", "MEDIUM", "HIGH",
    }
    # PRD §3.3: admission_source enum.
    assert data.get("admission_source") in {
        "COMMUNITY", "INSTITUTIONAL",
    }
    # PRD §3.3: hha_companion_hours_ordered "defaults to 0".
    hours = data.get("hha_companion_hours_ordered")
    assert isinstance(hours, (int, float)) and hours >= 0
    # PRD §3.3: OASIS lifecycle.
    assert data.get("status") in {"DRAFT", "LOCKED", "SUPERSEDED"}


# ---------------------------------------------------------------------------
# Episode — PRD §3.4
# ---------------------------------------------------------------------------
def assert_episode(data: Dict[str, Any]) -> None:
    _assert_id_and_created_at(data)
    _assert_updated_at_and_version(data)
    assert is_valid_uuid(data.get("patient_id", ""))
    assert is_valid_uuid(data.get("source_oasis_id", ""))
    # PRD §3.4: episode_type derived from assessment_reason.
    assert data.get("episode_type") in {"INITIAL", "RECERT", "ROC"}
    assert is_iso8601_date(data.get("start_date", ""))
    assert is_iso8601_date(data.get("end_date", ""))
    # PRD §3.4: timing_category EARLY | LATE.
    assert data.get("timing_category") in {"EARLY", "LATE"}
    assert is_iso8601_date(data.get("recert_due_date", ""))
    # PRD §3.4: lifecycle.
    assert data.get("status") in {"OPEN", "CLOSED", "EXPIRED"}


# ---------------------------------------------------------------------------
# Visit — PRD §3.5
# ---------------------------------------------------------------------------
def assert_visit(data: Dict[str, Any]) -> None:
    _assert_id_and_created_at(data)
    _assert_updated_at_and_version(data)
    assert is_valid_uuid(data.get("episode_id", ""))
    assert is_valid_uuid(data.get("clinician_id", ""))
    # PRD §3.5: visit_type enum.
    assert data.get("visit_type") in {"SN", "PT", "OT", "SLP", "HHA"}
    assert is_iso8601_date(data.get("visit_date", ""))
    # PRD §3.5: "start_minute and end_minute are minute-of-day integers
    # from 0 through 1439 inclusive."
    sm = data.get("start_minute")
    em = data.get("end_minute")
    assert isinstance(sm, int) and 0 <= sm <= 1439
    assert isinstance(em, int) and 0 <= em <= 1439
    assert em > sm
    # PRD §3.5: hha_hours computed. Non-HHA = 0; HHA = (em-sm)/60
    # rounded half-up to 2 decimals.
    hha = data.get("hha_hours")
    assert isinstance(hha, (int, float))
    if data["visit_type"] != "HHA":
        assert hha == 0, f"non-HHA visit must have hha_hours=0, got {hha}"
    else:
        assert hha >= 0
    # PRD §3.5: status enum.
    assert data.get("status") in {"SCHEDULED", "COMPLETED", "CANCELLED"}


# ---------------------------------------------------------------------------
# MileageLog — PRD §3.6 (append-only — no updated_at, no version)
# ---------------------------------------------------------------------------
def assert_mileage_log(data: Dict[str, Any]) -> None:
    _assert_id_and_created_at(data)
    _assert_no_updated_at_or_version(data)
    assert is_valid_uuid(data.get("visit_id", ""))
    assert is_valid_uuid(data.get("episode_id", ""))
    # PRD §3.6: miles_driven strictly > 0.
    miles = data.get("miles_driven")
    assert isinstance(miles, (int, float)) and miles > 0
    # PRD §3.6 / §2.6: reimbursement_amount computed and stored at 2dp.
    reimb = data.get("reimbursement_amount")
    assert isinstance(reimb, (int, float)) and reimb >= 0
    assert_money_2dp(reimb)


# ---------------------------------------------------------------------------
# PDGMClaim — PRD §3.7
# ---------------------------------------------------------------------------
def assert_pdgm_claim(data: Dict[str, Any]) -> None:
    _assert_id_and_created_at(data)
    _assert_updated_at_and_version(data)
    assert is_valid_uuid(data.get("episode_id", ""))
    # PRD §3.7: "five-character classification".
    hipps = data.get("hipps_code")
    assert isinstance(hipps, str) and len(hipps) == 5, (
        f"hipps_code must be 5 chars, got {hipps!r}"
    )
    # PRD §3.7: positional encoding.
    assert hipps[0] in {"1", "2"}, (
        f"hipps[0] must be timing (1 EARLY or 2 LATE), got {hipps[0]!r}"
    )
    assert hipps[1] in {"A", "B", "C", "D", "E", "F"}, (
        f"hipps[1] must be clinical_grouping letter A..F, "
        f"got {hipps[1]!r}"
    )
    assert hipps[2] in {"F", "G", "H"}, (
        f"hipps[2] must be functional level F/G/H, got {hipps[2]!r}"
    )
    assert hipps[3] in {"J", "K"}, (
        f"hipps[3] must be admission J/K, got {hipps[3]!r}"
    )
    assert hipps[4] == "1", (
        f"hipps[4] must be the literal '1', got {hipps[4]!r}"
    )
    # PRD §2.6: case_mix_weight stored to 4 decimals.
    cmw = data.get("case_mix_weight")
    assert isinstance(cmw, (int, float)) and cmw > 0
    # PRD §3.7: provisional_payment present once Episode opens.
    pp = data.get("provisional_payment")
    assert isinstance(pp, (int, float)) and pp > 0
    assert_money_2dp(pp)
    # PRD §3.7: status PENDING | FINALIZED.
    assert data.get("status") in {"PENDING", "FINALIZED"}
    if data["status"] == "FINALIZED":
        # PRD §3.4 / §3.7: final_payment, lupa_applied, and
        # total_mileage_reimbursement are written when claim transitions
        # PENDING -> FINALIZED.
        fp = data.get("final_payment")
        assert isinstance(fp, (int, float)) and fp >= 0
        assert_money_2dp(fp)
        assert isinstance(data.get("lupa_applied"), bool)
        tmr = data.get("total_mileage_reimbursement")
        assert isinstance(tmr, (int, float)) and tmr >= 0
        assert_money_2dp(tmr)


# ---------------------------------------------------------------------------
# ClockState — PRD §2.4 / §2.7
# ---------------------------------------------------------------------------
def assert_clock_state(data: Dict[str, Any]) -> None:
    """PRD §2.4: "The ClockState singleton … Its sole exposed attribute
    is current_date." PRD §2.7: current_date is an ISO date."""
    assert "current_date" in data, "ClockState missing current_date"
    assert is_iso8601_date(data["current_date"])


# ---------------------------------------------------------------------------
# Numeric / monetary precision — PRD §2.6
# ---------------------------------------------------------------------------
def assert_money_2dp(value: float) -> None:
    """PRD §2.6: "Two-decimal precision (cents) is the API surface for
    the PDGM claim's provisional_payment and final_payment, for the
    total_mileage_reimbursement aggregated onto the claim, and for the
    per-row reimbursement_amount recorded on each MileageLog."
    """
    # Allow a tiny float fudge; value must round to itself at 2dp.
    rounded = round(value + 1e-9, 2)
    assert abs(value - rounded) < 1e-6, (
        f"monetary value {value} must be at two decimal places"
    )


def assert_case_mix_weight_4dp(value: float) -> None:
    """PRD §2.6: "The PDGM case_mix_weight is itself stored to four
    decimals."""
    rounded = round(value + 1e-11, 4)
    assert abs(value - rounded) < 1e-7, (
        f"case_mix_weight {value} must be at four decimal places"
    )


# ---------------------------------------------------------------------------
# Version-bump invariant — PRD §2.4
# ---------------------------------------------------------------------------
def assert_version_incremented_by_one(after: Dict[str, Any],
                                      before_version: int) -> None:
    """PRD §2.4: "a version integer that begins at 1 and increases by
    exactly 1 every time the resource is mutated."""
    assert after["version"] == before_version + 1, (
        f"expected version {before_version + 1}, "
        f"got {after['version']}"
    )


__all__ = [
    "is_iso8601_date",
    "assert_patient",
    "assert_clinician",
    "assert_oasis_assessment",
    "assert_episode",
    "assert_visit",
    "assert_mileage_log",
    "assert_pdgm_claim",
    "assert_clock_state",
    "assert_money_2dp",
    "assert_case_mix_weight_4dp",
    "assert_version_incremented_by_one",
]
