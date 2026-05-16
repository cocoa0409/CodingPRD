"""Entity assertions and domain invariant checkers.

These check the response shape and domain invariants required by the PRD
contract. They are intentionally generous about server-minted fields
(e.g., computed counters): a test that wants to pin a specific computed
value asserts it directly in test code.
"""
from __future__ import annotations

from typing import Any, Dict

from prd_bench_local_runner.testing import (
    is_iso8601_timestamp,
    is_valid_uuid,
)


# ---------------------------------------------------------------------------
# Common-fields predicates — PRD §2.4
# ---------------------------------------------------------------------------
def _assert_id_and_created_at(data: Dict[str, Any]) -> None:
    assert "id" in data, f"missing id; got keys: {list(data)}"
    assert is_valid_uuid(data["id"]), (
        f"id must be a UUID with no type prefix, got {data['id']!r}"
    )
    assert "created_at" in data, "missing created_at"
    assert is_iso8601_timestamp(data["created_at"]), (
        f"created_at must be ISO 8601, got {data['created_at']!r}"
    )


def _assert_updated_at_and_version(data: Dict[str, Any]) -> None:
    """PRD §2.4 four common properties: id, created_at, updated_at,
    version. Asserted for entities that carry version. PRD §2.4
    explicitly states RecruitingCalendar, RecruitingContact, and
    EligibilityRecord do NOT carry these fields."""
    assert "updated_at" in data, "missing updated_at"
    assert is_iso8601_timestamp(data["updated_at"]), (
        f"updated_at must be ISO 8601, got {data['updated_at']!r}"
    )
    assert "version" in data, "missing version"
    assert isinstance(data["version"], int) and data["version"] >= 1, (
        f"version must be a positive integer, got {data.get('version')!r}"
    )


def _assert_no_updated_at_no_version(data: Dict[str, Any]) -> None:
    """PRD §2.4: "Append-only resources do not bear updated_at or
    version." Append-only entities are RecruitingCalendar,
    RecruitingContact, and EligibilityRecord. We tolerate the field
    being absent OR null — both are faithful to PRD prose."""
    # PRD does not forbid these keys outright with a serializer; the
    # contract is that they are not part of the entity. We thus assert
    # that, if present, the value is not a real integer/version-style
    # value.
    if "updated_at" in data:
        assert data["updated_at"] in (None, ""), (
            f"append-only entities must not carry updated_at; "
            f"got {data['updated_at']!r}"
        )
    if "version" in data:
        assert data["version"] in (None, ""), (
            f"append-only entities must not carry version; "
            f"got {data['version']!r}"
        )


# ---------------------------------------------------------------------------
# Program — PRD §3.1
# ---------------------------------------------------------------------------
def assert_program(data: Dict[str, Any]) -> None:
    _assert_id_and_created_at(data)
    _assert_updated_at_and_version(data)
    assert isinstance(data.get("institution_name"), str)
    assert data["institution_name"]
    assert data.get("sport") in {
        "FOOTBALL", "MENS_BASKETBALL", "WOMENS_BASKETBALL",
        "BASEBALL", "SOFTBALL",
    }
    assert data.get("division") in {"DI", "DII", "DIII"}
    assert isinstance(
        data.get("scholarship_cap_equivalencies"), (int, float),
    )
    assert data["scholarship_cap_equivalencies"] >= 0
    assert isinstance(data.get("roster_cap_count"), int)
    assert data["roster_cap_count"] >= 0
    # Computed fields — PRD §3.1, §3.3, §3.7
    assert isinstance(
        data.get("total_equivalencies_used"), (int, float),
    )
    assert data["total_equivalencies_used"] >= 0
    assert isinstance(data.get("active_roster_count"), int)
    assert data["active_roster_count"] >= 0
    assert isinstance(data.get("penalty_points_total"), int)
    assert data["penalty_points_total"] >= 0
    assert data.get("compliance_status") in {"GREEN", "YELLOW", "RED"}


# ---------------------------------------------------------------------------
# Athlete — PRD §3.2
# ---------------------------------------------------------------------------
def assert_athlete(data: Dict[str, Any]) -> None:
    _assert_id_and_created_at(data)
    _assert_updated_at_and_version(data)
    assert isinstance(data.get("full_name"), str)
    assert data["full_name"]
    assert isinstance(data.get("high_school"), str)
    assert isinstance(data.get("graduation_year"), int)
    assert data.get("status") in {
        "PROSPECTIVE", "COMMITTED", "ENROLLED",
        "TRANSFER_PORTAL", "INELIGIBLE",
    }
    # current_program_id is nullable — PRD §3.2: "null while PROSPECTIVE".
    cp = data.get("current_program_id")
    if cp is not None and cp != "":
        assert is_valid_uuid(cp), (
            f"current_program_id must be UUID when set, got {cp!r}"
        )
    assert data.get("amateur_status") in {"AMATEUR", "AT_RISK", "FORFEITED"}
    assert isinstance(data.get("years_of_eligibility_remaining"), int)
    assert isinstance(data.get("nil_deal_lifetime_value_cents"), int)
    assert data["nil_deal_lifetime_value_cents"] >= 0


# ---------------------------------------------------------------------------
# EligibilityRecord — append-only per PRD §2.4
# ---------------------------------------------------------------------------
def assert_eligibility_record(data: Dict[str, Any]) -> None:
    _assert_id_and_created_at(data)
    _assert_no_updated_at_no_version(data)
    assert is_valid_uuid(data.get("athlete_id", ""))
    assert isinstance(data.get("core_gpa"), (int, float))
    assert isinstance(data.get("standardized_test_score"), int)
    assert isinstance(data.get("core_courses_completed"), int)
    assert data.get("decision") in {
        "QUALIFIER", "PARTIAL_QUALIFIER", "NON_QUALIFIER", "INCOMPLETE",
    }
    assert isinstance(data.get("decided_at"), str)
    assert is_iso8601_timestamp(data["decided_at"])


# ---------------------------------------------------------------------------
# ScholarshipSlot — PRD §3.3
# ---------------------------------------------------------------------------
def assert_scholarship_slot(data: Dict[str, Any]) -> None:
    _assert_id_and_created_at(data)
    _assert_updated_at_and_version(data)
    assert is_valid_uuid(data.get("program_id", ""))
    assert is_valid_uuid(data.get("athlete_id", ""))
    assert isinstance(
        data.get("fractional_equivalency"), (int, float),
    )
    fe = data["fractional_equivalency"]
    assert 0.01 <= fe <= 1.00, f"fractional_equivalency out of range: {fe}"
    assert isinstance(data.get("annual_value_cents"), int)
    assert data["annual_value_cents"] > 0
    assert data.get("status") in {
        "OFFERED", "SIGNED", "ACTIVE",
        "WITHDRAWN", "RELEASED", "REVOKED",
    }


# ---------------------------------------------------------------------------
# RecruitingCalendar — append-only per PRD §2.4
# ---------------------------------------------------------------------------
def assert_recruiting_calendar(data: Dict[str, Any]) -> None:
    _assert_id_and_created_at(data)
    _assert_no_updated_at_no_version(data)
    assert is_valid_uuid(data.get("program_id", ""))
    assert data.get("period_type") in {
        "QUIET", "CONTACT", "DEAD", "EVALUATION",
    }
    assert isinstance(data.get("start_date"), str)
    assert isinstance(data.get("end_date"), str)


# ---------------------------------------------------------------------------
# RecruitingContact — append-only per PRD §2.4
# ---------------------------------------------------------------------------
def assert_recruiting_contact(data: Dict[str, Any]) -> None:
    _assert_id_and_created_at(data)
    _assert_no_updated_at_no_version(data)
    assert is_valid_uuid(data.get("program_id", ""))
    assert is_valid_uuid(data.get("athlete_id", ""))
    assert data.get("contact_type") in {
        "PHONE_CALL", "IN_PERSON_OFF_CAMPUS", "IN_PERSON_ON_CAMPUS",
        "TEXT_MESSAGE", "EVALUATION",
    }
    assert isinstance(data.get("contact_at"), str)
    assert is_iso8601_timestamp(data["contact_at"])
    assert data.get("contact_period_type") in {
        "QUIET", "CONTACT", "DEAD", "EVALUATION",
    }
    assert isinstance(data.get("was_permitted"), bool)


# ---------------------------------------------------------------------------
# NILDeal — PRD §3.5, §3.6
# ---------------------------------------------------------------------------
def assert_nil_deal(data: Dict[str, Any]) -> None:
    _assert_id_and_created_at(data)
    _assert_updated_at_and_version(data)
    assert is_valid_uuid(data.get("athlete_id", ""))
    assert isinstance(data.get("sponsor_name"), str)
    assert isinstance(data.get("sponsor_is_booster"), bool)
    assert data.get("deal_category") in {
        "ENDORSEMENT", "APPEARANCE", "SOCIAL_MEDIA_POST",
        "AUTOGRAPH_SIGNING", "CAMP_INSTRUCTION",
    }
    assert isinstance(data.get("stated_value_cents"), int)
    assert data["stated_value_cents"] > 0
    assert isinstance(data.get("deliverables_hours"), (int, float))
    assert data["deliverables_hours"] > 0
    assert isinstance(data.get("market_rate_cents_per_hour"), int)
    assert data["market_rate_cents_per_hour"] > 0
    # Computed fields — PRD §3.5
    assert isinstance(data.get("fmv_calculated_cents"), int)
    assert data["fmv_calculated_cents"] >= 0
    assert isinstance(data.get("pay_for_play_flag"), bool)
    assert data.get("status") in {
        "SUBMITTED", "UNDER_REVIEW", "APPROVED",
        "REJECTED", "SUSPENDED", "REVOKED",
    }
    # approved_value_cents is null until APPROVED — PRD §3.5
    av = data.get("approved_value_cents")
    if av is not None:
        assert isinstance(av, int) and av >= 0


# ---------------------------------------------------------------------------
# TransferPortalEntry — PRD §3.4
# ---------------------------------------------------------------------------
def assert_transfer_portal_entry(data: Dict[str, Any]) -> None:
    _assert_id_and_created_at(data)
    _assert_updated_at_and_version(data)
    assert is_valid_uuid(data.get("athlete_id", ""))
    assert is_valid_uuid(data.get("origin_program_id", ""))
    # destination_program_id is nullable — PRD §3.4 sets it only on COMMITTED.
    dp = data.get("destination_program_id")
    if dp is not None and dp != "":
        assert is_valid_uuid(dp)
    assert isinstance(data.get("entered_at"), str)
    assert is_iso8601_timestamp(data["entered_at"])
    assert isinstance(data.get("window_closes_at"), str)
    assert is_iso8601_timestamp(data["window_closes_at"])
    assert data.get("reason") in {
        "PLAYING_TIME", "COACHING_CHANGE", "FAMILY", "ACADEMIC", "OTHER",
    }
    assert data.get("status") in {
        "ENTERED", "CONTACT_WINDOW",
        "COMMITTED", "WITHDRAWN", "EXPIRED",
    }


# ---------------------------------------------------------------------------
# ComplianceViolation — PRD §3.7
# ---------------------------------------------------------------------------
def assert_violation(data: Dict[str, Any]) -> None:
    _assert_id_and_created_at(data)
    _assert_updated_at_and_version(data)
    assert is_valid_uuid(data.get("program_id", ""))
    assert data.get("subject_type") in {
        "BOOSTER", "COACH", "ATHLETE", "PROGRAM_ADMIN",
    }
    assert isinstance(data.get("subject_ref"), str)
    assert data.get("violation_type") in {
        "IMPERMISSIBLE_BENEFIT", "RECRUITING_CONTACT",
        "NIL_COLLECTIVE_PAYFORPLAY", "ACADEMIC_FRAUD", "OTHER",
    }
    assert data.get("severity") in {
        "LEVEL_I", "LEVEL_II", "LEVEL_III", "LEVEL_IV",
    }
    assert data.get("status") in {
        "REPORTED", "INVESTIGATING", "SUBSTANTIATED",
        "DISMISSED", "APPEALED", "SUSTAINED", "OVERTURNED",
    }
    assert data.get("outcome") in {"PENDING", "SUSTAINED", "CLEARED"}
    assert isinstance(data.get("penalty_points"), int)
    assert data["penalty_points"] >= 0


# ---------------------------------------------------------------------------
# Cross-entity invariants
# ---------------------------------------------------------------------------
def assert_version_incremented_by_one(after: Dict[str, Any],
                                      before_version: int) -> None:
    """PRD §2.4: "version is a non-negative integer that starts at 1 and
    increments by one on every mutation of the resource."""
    assert after["version"] == before_version + 1, (
        f"expected version {before_version + 1}, got {after['version']}"
    )


def assert_approved_value_pinned_to_min(deal: Dict[str, Any]) -> None:
    """PRD §3.6: "approved_value_cents is pinned to the minimum of
    stated_value_cents and fmv_calculated_cents"."""
    assert deal["status"] == "APPROVED"
    expected = min(deal["stated_value_cents"], deal["fmv_calculated_cents"])
    assert deal["approved_value_cents"] == expected, (
        f"approved_value_cents should equal min(stated={deal['stated_value_cents']}, "
        f"fmv={deal['fmv_calculated_cents']}) == {expected}, "
        f"got {deal['approved_value_cents']}"
    )


__all__ = [
    "assert_program",
    "assert_athlete",
    "assert_eligibility_record",
    "assert_scholarship_slot",
    "assert_recruiting_calendar",
    "assert_recruiting_contact",
    "assert_nil_deal",
    "assert_transfer_portal_entry",
    "assert_violation",
    "assert_version_incremented_by_one",
    "assert_approved_value_pinned_to_min",
]
