"""Entity assertions and domain invariant checkers (PRD §2.4, §3)."""
from prd_bench_local_runner.testing import (
    is_valid_uuid,
    is_iso8601_timestamp,
)


def _assert_common_fields(data: dict, label: str = "entity") -> None:
    """Every primary resource carries id, created_at, updated_at, version
    per PRD §2.4."""
    assert is_valid_uuid(data.get("id", "")), (
        f"{label}.id must be a valid UUID; got {data.get('id')!r}"
    )
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"{label}.created_at must be ISO 8601; got {data.get('created_at')!r}"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"{label}.updated_at must be ISO 8601; got {data.get('updated_at')!r}"
    )
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"{label}.version must be a positive int; got {data.get('version')!r}"
    )


# ─── Program (PRD §3.1) ─────────────────────────────────


def assert_program(data: dict) -> None:
    _assert_common_fields(data, "Program")
    assert data["sport_code"] in (
        "FOOTBALL", "MBB", "WBB", "BASEBALL", "SOFTBALL",
    )
    assert isinstance(data["school_name"], str) and data["school_name"]
    assert isinstance(data["scholarship_slot_cap"], int)
    assert 1 <= data["scholarship_slot_cap"] <= 130
    assert isinstance(data["slots_committed"], int)
    assert data["slots_committed"] >= 0
    assert isinstance(data["slots_projected"], int)
    assert data["slots_projected"] >= 0
    assert data["penalty_tier"] in (
        "NONE", "LEVEL_I", "LEVEL_II", "POSTSEASON_BAN",
    )


def assert_program_invariants(data: dict) -> None:
    """Invariants from PRD §2.9 / §3.4 that must hold after any operation."""
    assert data["slots_committed"] >= 0
    assert data["slots_committed"] <= data["scholarship_slot_cap"]


# ─── Period (PRD §3.1) ──────────────────────────────────


def assert_period(data: dict) -> None:
    _assert_common_fields(data, "Period")
    assert is_valid_uuid(data["program_id"])
    assert data["period_type"] in ("CONTACT", "QUIET", "DEAD")
    assert is_iso8601_timestamp(data["starts_at"])
    assert is_iso8601_timestamp(data["ends_at"])
    assert data["starts_at"] < data["ends_at"]


# ─── StudentAthlete (PRD §3.2) ──────────────────────────


def assert_student_athlete(data: dict) -> None:
    _assert_common_fields(data, "StudentAthlete")
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert data["sport_code"] in (
        "FOOTBALL", "MBB", "WBB", "BASEBALL", "SOFTBALL",
    )
    assert isinstance(data["gpa"], (int, float))
    assert 0.0 <= float(data["gpa"]) <= 4.0
    assert isinstance(data["amateurism_flag"], bool)
    assert data["eligibility_status"] in (
        "UNCERTIFIED", "CERTIFIED", "INELIGIBLE",
    )
    assert isinstance(data["in_transfer_portal"], bool)


# ─── EligibilityCertification (PRD §3.2) ────────────────


def assert_eligibility_certification(data: dict) -> None:
    _assert_common_fields(data, "EligibilityCertification")
    assert is_valid_uuid(data["student_athlete_id"])
    assert data["status"] in ("PENDING", "APPROVED", "DENIED")


# ─── RecruitingContact (PRD §3.3) ───────────────────────


def assert_recruiting_contact(data: dict) -> None:
    _assert_common_fields(data, "RecruitingContact")
    assert is_valid_uuid(data["program_id"])
    assert is_valid_uuid(data["student_athlete_id"])
    assert isinstance(data["coach_user_id"], str) and data["coach_user_id"]
    assert is_iso8601_timestamp(data["contact_at"])
    assert data["channel"] in ("IN_PERSON", "PHONE", "DM", "EMAIL")
    # PRD §3.3: period_type_at_contact is always one of CONTACT or QUIET on
    # a successfully created contact, never DEAD.
    assert data["period_type_at_contact"] in ("CONTACT", "QUIET")


# ─── ScholarshipOffer (PRD §3.4) ────────────────────────


def assert_scholarship_offer(data: dict) -> None:
    _assert_common_fields(data, "ScholarshipOffer")
    assert is_valid_uuid(data["program_id"])
    assert is_valid_uuid(data["student_athlete_id"])
    assert data["status"] in (
        "DRAFT", "SENT", "ACCEPTED", "DECLINED", "WITHDRAWN",
    )
    assert isinstance(data["annual_value_cents"], int)
    assert data["annual_value_cents"] >= 0


# ─── NILDeal (PRD §3.5) ─────────────────────────────────


def assert_nil_deal(data: dict) -> None:
    _assert_common_fields(data, "NILDeal")
    assert is_valid_uuid(data["student_athlete_id"])
    assert isinstance(data["brand_name"], str) and data["brand_name"]
    assert isinstance(data["gross_value_cents"], int)
    assert data["gross_value_cents"] >= 0
    assert isinstance(data["agent_fee_pct"], (int, float))
    assert 0.0 <= float(data["agent_fee_pct"]) <= 0.30
    assert isinstance(data["net_value_cents"], int)
    assert data["net_value_cents"] >= 0
    assert data["tier"] in ("DE_MINIMIS", "STANDARD", "HIGH_VALUE")
    assert isinstance(data["review_round"], int) and data["review_round"] >= 0
    assert data["status"] in (
        "PROPOSED", "UNDER_REVIEW", "APPROVED", "REJECTED",
    )


# ─── TransferPortalEntry (PRD §3.6) ─────────────────────


def assert_transfer_portal_entry(data: dict) -> None:
    _assert_common_fields(data, "TransferPortalEntry")
    assert is_valid_uuid(data["student_athlete_id"])
    assert is_valid_uuid(data["source_program_id"])
    assert is_iso8601_timestamp(data["entered_at"])
    assert is_iso8601_timestamp(data["window_closes_at"])
    assert data["status"] in (
        "ENTERED", "MATCHED", "WITHDRAWN", "EXPIRED",
    )


# ─── BoosterIncident (PRD §3.7) ─────────────────────────


def assert_booster_incident(data: dict) -> None:
    _assert_common_fields(data, "BoosterIncident")
    assert is_valid_uuid(data["program_id"])
    assert isinstance(data["booster_name"], str) and data["booster_name"]
    assert is_valid_uuid(data["student_athlete_id"])
    assert isinstance(data["alleged_value_cents"], int)
    assert data["alleged_value_cents"] >= 0
    assert isinstance(data["severity_weight"], int)
    assert data["severity_weight"] >= 0
    assert data["status"] in (
        "REPORTED", "INVESTIGATING", "SUSTAINED", "DISMISSED",
    )
