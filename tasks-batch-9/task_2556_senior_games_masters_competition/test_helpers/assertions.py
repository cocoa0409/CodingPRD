"""Per-resource assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp

from .types import (
    GamesEditionStatus,
    SportEventStatus,
    VenueStatus,
    SessionSlotStatus,
    AthleteRegistrationStatus,
    AthleteMedicalStatus,
    SportEntryStatus,
    PersonnelAssignmentStatus,
    CompetitionResultStatus,
    AgeGroupRecordStatus,
    VillageStayStatus,
    SponsorshipCommitmentStatus,
)

_ISO_DATE_LEN = len("YYYY-MM-DD")


def _values(enum_cls):
    return [m.value for m in enum_cls]


def assert_common_properties(data: dict):
    """id / created_at / updated_at / version, as carried by every resource
    except the two immutable rows (PRD §2.5)."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), \
        f"created_at must be ISO 8601, got {data.get('created_at')!r}"
    assert is_iso8601_timestamp(data.get("updated_at", "")), \
        f"updated_at must be ISO 8601, got {data.get('updated_at')!r}"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, \
        f"version must be an integer >= 1, got {data.get('version')!r}"


def assert_immutable_row_properties(data: dict):
    """The reduced property set of QualifyingResult and MedicalScreening: only
    `id` and `created_at`; `updated_at` and `version` are absent entirely."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), \
        f"created_at must be ISO 8601, got {data.get('created_at')!r}"
    assert "updated_at" not in data, "an immutable row must not expose updated_at"
    assert "version" not in data, "an immutable row must not expose version"


def _assert_calendar_date(value, field):
    assert isinstance(value, str) and len(value) == _ISO_DATE_LEN and value[4] == "-" \
        and value[7] == "-", f"{field} must be a YYYY-MM-DD calendar date, got {value!r}"


def assert_games_edition(data: dict):
    assert_common_properties(data)
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["host_city"], str) and data["host_city"]
    assert isinstance(data["host_state_code"], str) and len(data["host_state_code"]) == 2
    assert data["host_state_code"].isupper()
    for f in ("competition_start_date", "competition_end_date", "age_reference_date"):
        _assert_calendar_date(data[f], f)
    assert is_iso8601_timestamp(data["registration_deadline_utc"])
    assert data["age_basis"] in ("REFERENCE_DATE", "FIRST_COMPETITION_DAY")
    assert isinstance(data["municipal_support_cents"], int) and data["municipal_support_cents"] >= 0
    assert data["status"] in _values(GamesEditionStatus), \
        f"unexpected edition status {data['status']!r}"
    assert isinstance(data["ops_epoch"], int) and data["ops_epoch"] >= 0
    assert isinstance(data["sponsorship_recognized_cents"], int)
    assert isinstance(data["provisional_impact_cents"], int)
    assert data["final_impact_cents"] is None or isinstance(data["final_impact_cents"], int)


def assert_sport(data: dict):
    assert_common_properties(data)
    code = data["sport_code"]
    assert isinstance(code, str) and 2 <= len(code) <= 8 and code.isupper() and code.isalpha()
    assert isinstance(data["name"], str) and data["name"]
    assert data["contact_class"] in ("LOW", "MEDIUM", "HIGH")
    assert data["mark_direction"] in ("LOWER_IS_BETTER", "HIGHER_IS_BETTER")
    assert isinstance(data["required_certification_level"], int)
    assert 0 <= data["required_certification_level"] <= 4
    assert isinstance(data["min_age"], int) and data["min_age"] >= 50
    assert isinstance(data["equipment_profile"], dict)
    assert isinstance(data["format_modifications"], dict)


def assert_sport_event(data: dict):
    assert_common_properties(data)
    assert is_valid_uuid(data["sport_id"])
    assert is_valid_uuid(data["games_edition_id"])
    assert isinstance(data["event_code"], str) and data["event_code"]
    assert isinstance(data["age_group_code"], str) and data["age_group_code"]
    assert data["gender_division"] in ("MEN", "WOMEN", "MIXED")
    assert isinstance(data["entry_fee_cents"], int) and data["entry_fee_cents"] >= 0
    assert isinstance(data["capacity"], int) and data["capacity"] >= 1
    assert isinstance(data["min_entries_to_stage"], int) and data["min_entries_to_stage"] >= 1
    assert data["capacity"] >= data["min_entries_to_stage"], \
        "capacity must be at least min_entries_to_stage"
    assert data["status"] in _values(SportEventStatus)
    assert_sport_event_capacity_conserved(data)


def assert_sport_event_capacity_conserved(data: dict):
    """`accepted_entry_count` and `available_slots` always sum to `capacity`,
    and `available_slots` is never negative (PRD §2.8)."""
    assert data["available_slots"] >= 0, \
        f"available_slots must never be negative, got {data['available_slots']}"
    assert data["accepted_entry_count"] + data["available_slots"] == data["capacity"], (
        f"accepted_entry_count {data['accepted_entry_count']} + available_slots "
        f"{data['available_slots']} must equal capacity {data['capacity']}"
    )


def assert_venue(data: dict):
    assert_common_properties(data)
    assert is_valid_uuid(data["games_edition_id"])
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["competition_area_count"], int) and data["competition_area_count"] >= 1
    assert isinstance(data["spectator_capacity"], int) and data["spectator_capacity"] >= 0
    assert isinstance(data["has_onsite_medical_bay"], bool)
    assert data["emergency_protocol_code"] in ("EP_BASIC", "EP_ADVANCED", "EP_CARDIAC")
    assert data["status"] in _values(VenueStatus)


def assert_session_slot(data: dict):
    assert_common_properties(data)
    assert is_valid_uuid(data["venue_id"])
    assert is_valid_uuid(data["sport_event_id"])
    assert is_iso8601_timestamp(data["start_utc"])
    assert is_iso8601_timestamp(data["end_utc"])
    assert data["end_utc"] > data["start_utc"], "end_utc must be strictly after start_utc"
    assert isinstance(data["teardown_buffer_minutes"], int)
    assert 0 <= data["teardown_buffer_minutes"] <= 120
    assert isinstance(data["required_official_count"], int) and data["required_official_count"] >= 1
    assert isinstance(data["confirmed_official_count"], int)
    assert data["confirmed_official_count"] >= 0
    assert data["status"] in _values(SessionSlotStatus)


def assert_athlete(data: dict):
    assert_common_properties(data)
    assert is_valid_uuid(data["games_edition_id"])
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert isinstance(data["email"], str) and data["email"]
    _assert_calendar_date(data["date_of_birth"], "date_of_birth")
    assert isinstance(data["residency_state_code"], str) and len(data["residency_state_code"]) == 2
    assert isinstance(data["age_at_reference"], int)
    assert isinstance(data["age_at_first_day"], int)
    assert isinstance(data["age_group_code"], str) and data["age_group_code"]
    assert data["registration_status"] in _values(AthleteRegistrationStatus)
    assert data["medical_status"] in _values(AthleteMedicalStatus)
    assert isinstance(data["fee_total_cents"], int) and data["fee_total_cents"] >= 0
    assert isinstance(data["fee_paid_cents"], int) and data["fee_paid_cents"] >= 0
    assert isinstance(data["fee_breakdown"], dict)
    assert "status" not in data, \
        "the athlete splits its lifecycle across registration_status and medical_status"


def assert_qualifying_result(data: dict):
    assert_immutable_row_properties(data)
    assert is_valid_uuid(data["athlete_id"])
    assert is_valid_uuid(data["sport_id"])
    assert isinstance(data["event_code"], str) and data["event_code"]
    assert data["mark_value"] > 0, "mark_value must be strictly greater than zero"
    _assert_calendar_date(data["meet_date"], "meet_date")
    assert data["meet_level"] in ("LOCAL", "STATE")
    assert isinstance(data["sanctioned"], bool)


def assert_sport_entry(data: dict):
    assert_common_properties(data)
    assert is_valid_uuid(data["athlete_id"])
    assert is_valid_uuid(data["sport_event_id"])
    assert data["qualification_source"] in (
        "STATE_QUALIFIER", "LOCAL_QUALIFIER", "AGE_EXEMPT", "ORGANIZER_INVITE",
    )
    assert data["qualification_priority"] in (1, 2, 3, 4)
    assert isinstance(data["revision_round"], int) and data["revision_round"] >= 0
    assert data["status"] in _values(SportEntryStatus)


def assert_medical_screening(data: dict):
    assert_immutable_row_properties(data)
    assert is_valid_uuid(data["athlete_id"])
    assert isinstance(data["screened_by_user_id"], str) and data["screened_by_user_id"]
    assert 60 <= data["systolic_bp"] <= 260
    assert 30 <= data["resting_hr"] <= 200
    assert isinstance(data["prior_cardiac_event"], bool)
    assert isinstance(data["contact_sport_count"], int) and data["contact_sport_count"] >= 0
    assert_risk_score_shape(data["risk_score"])
    assert data["recommendation"] in (
        "CLEARED", "CLEARED_WITH_RESTRICTION", "HOLD_PENDING_PHYSICIAN_REVIEW",
    )
    assert is_iso8601_timestamp(data["screened_at_utc"])


def assert_risk_score_shape(risk_score):
    """`risk_score` is carried to one decimal place and clamped so it can never
    exceed 100.0 (PRD §2.8)."""
    assert isinstance(risk_score, (int, float)), f"risk_score must be numeric, got {risk_score!r}"
    assert 0 <= risk_score <= 100.0, f"risk_score must never exceed 100.0, got {risk_score}"
    assert round(float(risk_score), 1) == float(risk_score), \
        f"risk_score must carry one decimal place, got {risk_score}"


def assert_personnel(data: dict):
    assert_common_properties(data)
    assert is_valid_uuid(data["games_edition_id"])
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert data["personnel_type"] in ("OFFICIAL", "VOLUNTEER")
    assert isinstance(data["certification_level"], int)
    assert 0 <= data["certification_level"] <= 4
    assert isinstance(data["certified_sport_codes"], list)
    assert isinstance(data["assigned_minutes_total"], int)
    assert data["assigned_minutes_total"] >= 0, \
        "the served-minutes ledger must never fall below zero"
    assert isinstance(data["no_show_count"], int) and data["no_show_count"] >= 0


def assert_personnel_assignment(data: dict):
    assert_common_properties(data)
    assert is_valid_uuid(data["personnel_id"])
    assert is_valid_uuid(data["session_slot_id"])
    assert data["role_at_event"] in ("CHIEF_JUDGE", "JUDGE", "TIMER", "MARSHAL", "RUNNER")
    assert isinstance(data["duration_minutes"], int) and data["duration_minutes"] > 0
    assert data["status"] in _values(PersonnelAssignmentStatus)


def assert_competition_result(data: dict):
    assert_common_properties(data)
    assert is_valid_uuid(data["sport_entry_id"])
    assert is_valid_uuid(data["session_slot_id"])
    assert is_valid_uuid(data["submitted_by_personnel_id"])
    assert data["mark_value"] > 0, "mark_value must be a positive figure"
    assert isinstance(data["placement"], int) and data["placement"] >= 1
    assert isinstance(data["national_qualifying"], bool)
    assert isinstance(data["protest_round"], int) and data["protest_round"] >= 0
    assert data["status"] in _values(CompetitionResultStatus)


def assert_age_group_record(data: dict):
    assert_common_properties(data)
    assert is_valid_uuid(data["sport_event_id"])
    assert is_valid_uuid(data["competition_result_id"])
    assert is_valid_uuid(data["holder_athlete_id"])
    assert isinstance(data["age_group_code"], str) and data["age_group_code"]
    assert data["mark_value"] > 0
    assert isinstance(data["claimed_by_user_id"], str) and data["claimed_by_user_id"]
    assert data["status"] in _values(AgeGroupRecordStatus)


def assert_accommodation_block(data: dict):
    assert_common_properties(data)
    assert is_valid_uuid(data["games_edition_id"])
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["bed_capacity"], int) and data["bed_capacity"] >= 1
    assert isinstance(data["nightly_rate_cents"], int) and data["nightly_rate_cents"] >= 0
    assert isinstance(data["accessible_units"], int) and data["accessible_units"] >= 0
    assert isinstance(data["reserved_bed_nights"], int) and data["reserved_bed_nights"] >= 0


def assert_village_stay(data: dict):
    assert_common_properties(data)
    assert is_valid_uuid(data["athlete_id"])
    assert is_valid_uuid(data["accommodation_block_id"])
    _assert_calendar_date(data["check_in_date"], "check_in_date")
    _assert_calendar_date(data["check_out_date"], "check_out_date")
    assert data["check_out_date"] > data["check_in_date"], \
        "check_out_date must be strictly later than check_in_date"
    assert isinstance(data["nights"], int) and data["nights"] >= 1
    assert isinstance(data["total_charge_cents"], int) and data["total_charge_cents"] >= 0
    assert data["status"] in _values(VillageStayStatus)


def assert_sponsorship_commitment(data: dict):
    assert_common_properties(data)
    assert is_valid_uuid(data["games_edition_id"])
    assert isinstance(data["sponsor_name"], str) and data["sponsor_name"]
    assert data["sponsor_kind"] in ("CORPORATE", "MUNICIPAL", "FOUNDATION")
    assert data["tier"] in ("BRONZE", "SILVER", "GOLD", "PLATINUM")
    assert isinstance(data["pledged_cents"], int) and data["pledged_cents"] >= 1
    assert isinstance(data["recognized_cents"], int) and data["recognized_cents"] >= 0
    assert isinstance(data["allocation_map"], dict)
    assert data["status"] in _values(SponsorshipCommitmentStatus)


def assert_fee_breakdown_keys(fee_breakdown: dict):
    """The settlement pins seven intermediate values into `fee_breakdown`
    (PRD §3.2 step six)."""
    for key in (
        "entry_count", "event_fees_cents", "subtotal_cents", "discount_pct",
        "discount_cents", "discounted_cents", "surcharge_cents",
    ):
        assert key in fee_breakdown, f"fee_breakdown must carry {key}"


def assert_allocation_map_buckets(allocation_map: dict):
    """The four rounded bucket figures are stored keyed by bucket name."""
    for key in ("VENUE_SIGNAGE", "ATHLETE_SERVICES", "MEDICAL_COVERAGE", "SOCIAL_PROGRAM"):
        assert key in allocation_map, f"allocation_map must carry {key}"
        assert isinstance(allocation_map[key], int), f"{key} must be whole cents"


def assert_cents(value, field="amount"):
    """All monetary quantities are integers denominated in cents (PRD §2.8)."""
    assert isinstance(value, int) and not isinstance(value, bool), \
        f"{field} must be an integer number of cents, got {value!r}"
