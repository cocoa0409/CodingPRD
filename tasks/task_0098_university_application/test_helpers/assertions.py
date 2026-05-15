"""Entity assertions and domain invariant checkers.

Per PRD §2.4: Applicant, University, Program, Application,
RecommendationRequest, FinancialAidPackage, WaitlistEntry carry
id/created_at/updated_at/version. EssaySubmission and YieldSweep
are append-only — they carry only id and created_at; assertions on
those entities MUST NOT require updated_at or version.
"""
from __future__ import annotations

from typing import Any, Dict, Iterable, List, Optional

from prd_bench_local_runner.testing import (
    is_iso8601_timestamp,
    is_valid_uuid,
)


# ---------------------------------------------------------------------------
# Lookup helpers — fish a specific row out of a list of dicts.
# ---------------------------------------------------------------------------
def find_row(rows: List[Dict[str, Any]], **predicates: Any) -> Dict[str, Any]:
    for row in rows:
        if all(row.get(k) == v for k, v in predicates.items()):
            return row
    raise AssertionError(
        f"No row matching {predicates}. Saw: "
        f"{[dict((k, r.get(k)) for k in predicates) for r in rows]}"
    )


def select_rows(rows: List[Dict[str, Any]],
                **predicates: Any) -> List[Dict[str, Any]]:
    return [
        r for r in rows
        if all(r.get(k) == v for k, v in predicates.items())
    ]


def count_rows(rows: List[Dict[str, Any]], **predicates: Any) -> int:
    return len(select_rows(rows, **predicates))


# ---------------------------------------------------------------------------
# Common-fields helpers (PRD §2.4)
# ---------------------------------------------------------------------------
def _assert_common_fields(data: Dict[str, Any]) -> None:
    """Entities that carry id/created_at/updated_at/version."""
    assert is_valid_uuid(data.get("id", "")), (
        f"id must be a valid UUID, got {data.get('id')!r}"
    )
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"created_at must be ISO 8601, got {data.get('created_at')!r}"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"updated_at must be ISO 8601, got {data.get('updated_at')!r}"
    )
    version = data.get("version")
    assert isinstance(version, int) and version >= 1, (
        f"version must be a positive integer, got {version!r}"
    )


def _assert_append_only_fields(data: Dict[str, Any]) -> None:
    """Append-only entities — id and created_at only.

    Per PRD §2.4: EssaySubmission and YieldSweep "carry only id and
    created_at — neither updated_at nor version is present on those
    resources." Assertions on append-only entities therefore MUST NOT
    require updated_at or version (an implementation that correctly
    follows PRD will not emit them).
    """
    assert is_valid_uuid(data.get("id", "")), (
        f"id must be a valid UUID, got {data.get('id')!r}"
    )
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"created_at must be ISO 8601, got {data.get('created_at')!r}"
    )


def assert_version_incremented_by_one(before: Dict[str, Any],
                                      after: Dict[str, Any]) -> None:
    """PRD §2.4: every successful mutation increments version by one."""
    assert after["version"] == before["version"] + 1, (
        f"version expected {before['version'] + 1}, got {after['version']}"
    )


# ---------------------------------------------------------------------------
# Applicant (PRD §3.1)
# ---------------------------------------------------------------------------
def assert_applicant(data: Dict[str, Any]) -> None:
    _assert_common_fields(data)
    assert isinstance(data.get("full_name"), str) and \
        1 <= len(data["full_name"]) <= 200, "full_name length"
    assert isinstance(data.get("email"), str) and "@" in data["email"], "email"
    assert isinstance(data.get("date_of_birth"), str), "date_of_birth"
    gpa = data.get("high_school_gpa")
    assert isinstance(gpa, (int, float)) and 0.0 <= gpa <= 4.0, (
        f"high_school_gpa must be 0.0..4.0, got {gpa!r}"
    )
    income = data.get("household_income_cents")
    assert isinstance(income, int) and income >= 0, (
        f"household_income_cents must be non-negative int, got {income!r}"
    )
    # Optional EFCs may be null.
    assert data.get("fafsa_efc_cents") is None or \
        (isinstance(data["fafsa_efc_cents"], int)
         and data["fafsa_efc_cents"] >= 0), "fafsa_efc_cents"
    assert data.get("css_profile_efc_cents") is None or \
        (isinstance(data["css_profile_efc_cents"], int)
         and data["css_profile_efc_cents"] >= 0), "css_profile_efc_cents"
    # ed_commitment_application_id is null OR a UUID-like string.
    edc = data.get("ed_commitment_application_id")
    assert edc is None or isinstance(edc, str), "ed_commitment_application_id"


# ---------------------------------------------------------------------------
# University (PRD §3.2)
# ---------------------------------------------------------------------------
def assert_university(data: Dict[str, Any]) -> None:
    _assert_common_fields(data)
    assert isinstance(data.get("name"), str) and len(data["name"]) > 0
    ytc = data.get("yield_target_count")
    assert isinstance(ytc, int) and ytc >= 1, (
        f"yield_target_count must be >= 1, got {ytc!r}"
    )
    assert isinstance(data.get("regular_decision_deadline"), str)
    assert isinstance(data.get("early_decision_deadline"), str)
    assert isinstance(data.get("rolling_admission_enabled"), bool)
    ec = data.get("enrolled_count")
    assert isinstance(ec, int) and ec >= 0, (
        f"enrolled_count must be non-negative int, got {ec!r}"
    )


# ---------------------------------------------------------------------------
# Program (PRD §3.2)
# ---------------------------------------------------------------------------
def assert_program(data: Dict[str, Any]) -> None:
    _assert_common_fields(data)
    assert isinstance(data.get("university_id"), str)
    assert isinstance(data.get("name"), str)
    cap = data.get("capacity")
    assert isinstance(cap, int) and cap >= 1, (
        f"capacity must be >= 1, got {cap!r}"
    )
    ac = data.get("admitted_count")
    assert isinstance(ac, int) and ac >= 0, (
        f"admitted_count must be non-negative int, got {ac!r}"
    )


# ---------------------------------------------------------------------------
# Application (PRD §3.3, §3.6, §3.7, §3.10)
# ---------------------------------------------------------------------------
APPLICATION_STATES = {
    "DRAFT", "SUBMITTED", "UNDER_REVIEW",
    "ADMITTED", "REJECTED", "WAITLISTED",
    "ENROLLED", "WITHDRAWN",
}

APPLICATION_ROUNDS = {"EARLY_DECISION", "REGULAR_DECISION", "ROLLING"}


def assert_application(data: Dict[str, Any]) -> None:
    _assert_common_fields(data)
    assert isinstance(data.get("applicant_id"), str)
    assert isinstance(data.get("program_id"), str)
    assert data.get("round") in APPLICATION_ROUNDS, (
        f"round must be one of {APPLICATION_ROUNDS}, got {data.get('round')!r}"
    )
    assert data.get("status") in APPLICATION_STATES, (
        f"status must be one of {APPLICATION_STATES}, got {data.get('status')!r}"
    )
    rrc = data.get("required_recommendation_count")
    assert rrc in (2, 3), (
        f"required_recommendation_count must be 2 or 3, got {rrc!r}"
    )
    # essay_id null until attached.
    assert data.get("essay_id") is None or isinstance(data["essay_id"], str)


# ---------------------------------------------------------------------------
# EssaySubmission (PRD §3.4) — APPEND-ONLY (id + created_at only)
# ---------------------------------------------------------------------------
def assert_essay(data: Dict[str, Any]) -> None:
    _assert_append_only_fields(data)
    assert isinstance(data.get("application_id"), str)
    assert isinstance(data.get("prompt_code"), str)
    assert isinstance(data.get("body"), str)
    wc = data.get("word_count")
    assert isinstance(wc, int) and wc >= 0, (
        f"word_count must be non-negative int, got {wc!r}"
    )
    cs = data.get("customization_score")
    assert isinstance(cs, (int, float)) and 0.0 <= cs <= 1.0, (
        f"customization_score must be 0.0..1.0, got {cs!r}"
    )


# ---------------------------------------------------------------------------
# RecommendationRequest (PRD §3.5)
# ---------------------------------------------------------------------------
RECOMMENDATION_STATES = {
    "REQUESTED", "ACCEPTED", "SUBMITTED", "DECLINED", "EXPIRED",
}


def assert_recommendation(data: Dict[str, Any]) -> None:
    _assert_common_fields(data)
    assert isinstance(data.get("application_id"), str)
    assert isinstance(data.get("recommender_email"), str)
    assert data.get("status") in RECOMMENDATION_STATES, (
        f"status must be one of {RECOMMENDATION_STATES}, got {data.get('status')!r}"
    )
    assert isinstance(data.get("invitation_expires_at"), str)


# ---------------------------------------------------------------------------
# FinancialAidPackage (PRD §3.8)
# ---------------------------------------------------------------------------
FINANCIAL_AID_STATES = {
    "REQUESTED", "OFFERED", "ACCEPTED", "DECLINED", "REVOKED",
}

AID_METHODS = {"FEDERAL_METHODOLOGY", "INSTITUTIONAL_METHODOLOGY"}


def assert_financial_aid(data: Dict[str, Any]) -> None:
    _assert_common_fields(data)
    assert isinstance(data.get("application_id"), str)
    assert data.get("aid_method") in AID_METHODS, (
        f"aid_method must be one of {AID_METHODS}, got {data.get('aid_method')!r}"
    )
    assert data.get("status") in FINANCIAL_AID_STATES, (
        f"status must be one of {FINANCIAL_AID_STATES}, got {data.get('status')!r}"
    )
    coa = data.get("cost_of_attendance_cents")
    assert isinstance(coa, int) and coa >= 0, "cost_of_attendance_cents"
    for fld in ("grant_cents", "loan_cents", "work_study_cents",
                "total_award_cents"):
        v = data.get(fld)
        assert isinstance(v, int) and v >= 0, (
            f"{fld} must be non-negative int, got {v!r}"
        )


def assert_aid_award_totals(pkg: Dict[str, Any]) -> None:
    """PRD §3.8: 'total_award_cents is stored as the sum of grant_cents,
    loan_cents, and work_study_cents.'"""
    expected = pkg["grant_cents"] + pkg["loan_cents"] + pkg["work_study_cents"]
    assert pkg["total_award_cents"] == expected, (
        f"total_award_cents={pkg['total_award_cents']} but "
        f"grant+loan+ws={expected}"
    )


# ---------------------------------------------------------------------------
# WaitlistEntry (PRD §3.9)
# ---------------------------------------------------------------------------
WAITLIST_STATES = {"ACTIVE", "OFFERED", "ACCEPTED", "EXPIRED", "RELEASED"}


def assert_waitlist_entry(data: Dict[str, Any]) -> None:
    _assert_common_fields(data)
    assert isinstance(data.get("application_id"), str)
    assert isinstance(data.get("program_id"), str)
    assert data.get("status") in WAITLIST_STATES, (
        f"status must be one of {WAITLIST_STATES}, got {data.get('status')!r}"
    )
    rs = data.get("rank_score")
    assert isinstance(rs, (int, float)) and 0.0 <= rs <= 100.0, (
        f"rank_score must be 0.0..100.0, got {rs!r}"
    )


# ---------------------------------------------------------------------------
# YieldSweep (PRD §3.9) — APPEND-ONLY (id + created_at only)
# ---------------------------------------------------------------------------
def assert_yield_sweep(data: Dict[str, Any]) -> None:
    _assert_append_only_fields(data)
    assert isinstance(data.get("university_id"), str)
    ep = data.get("epoch")
    assert isinstance(ep, int) and ep >= 1, (
        f"epoch must be >= 1, got {ep!r}"
    )
    ecs = data.get("enrolled_count_at_start")
    assert isinstance(ecs, int) and ecs >= 0, "enrolled_count_at_start"
    oe = data.get("offers_extended")
    assert isinstance(oe, int) and oe >= 0, "offers_extended"
    assert isinstance(data.get("ran_at"), str), "ran_at"


# ---------------------------------------------------------------------------
# Score-precision helpers (PRD §2.9)
# ---------------------------------------------------------------------------
def assert_two_decimal_places(value: float, *, name: str = "score") -> None:
    """PRD §2.9: scores use two decimal places."""
    # Compare against the rounded-to-two-decimals form.
    rounded = round(value + 1e-9, 2)
    diff = abs(value - rounded)
    assert diff < 1e-6, (
        f"{name}={value} does not appear to be rounded to 2 decimal places "
        f"(rounded form is {rounded})"
    )


__all__ = [
    "find_row",
    "select_rows",
    "count_rows",
    "assert_version_incremented_by_one",
    "assert_applicant",
    "assert_university",
    "assert_program",
    "assert_application",
    "assert_essay",
    "assert_recommendation",
    "assert_financial_aid",
    "assert_aid_award_totals",
    "assert_waitlist_entry",
    "assert_yield_sweep",
    "assert_two_decimal_places",
    "APPLICATION_STATES",
    "APPLICATION_ROUNDS",
    "RECOMMENDATION_STATES",
    "FINANCIAL_AID_STATES",
    "AID_METHODS",
    "WAITLIST_STATES",
]
