"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

SANCTION_STATUSES = ["GOOD_STANDING", "PROBATION", "SUSPENDED"]
CREDENTIAL_STATUSES = ["BACKGROUND_PENDING", "CLEARED", "DENIED", "EXPIRED", "REVOKED"]
SEASON_STATUSES = [
    "PLANNED", "PRACTICE_OPEN", "REGULAR_SEASON", "SEEDING_LOCKED",
    "PLAYOFFS", "COMPLETED", "ABANDONED",
]
CASE_STATUSES = [
    "INTAKE", "UNDER_REVIEW", "UNDER_APPEAL", "PROVISIONAL_ELIGIBLE",
    "ELIGIBLE", "MEDICALLY_SUSPENDED", "INELIGIBLE",
]
FEE_STATUSES = [
    "ASSESSED", "PARTIALLY_PAID", "PAID", "WAIVER_REQUESTED",
    "WAIVED", "WAIVER_DENIED", "REFUNDED",
]
CONTEST_STATUSES = ["SCHEDULED", "OFFICIALS_ASSIGNED", "CONFIRMED", "PLAYED", "FORFEITED"]
ASSIGNMENT_STATUSES = ["OFFERED", "ACCEPTED", "DECLINED", "WITHDRAWN"]
TRANSPORT_STATUSES = ["REQUESTED", "APPROVED", "CANCELLED", "COMPLETED"]
INJURY_STATUSES = ["REPORTED", "RTP_IN_PROGRESS", "CLEARED", "SEASON_ENDED"]


def _assert_common_fields(data: dict, entity: str):
    """id, created_at, updated_at and version, as carried by the ten full families."""
    assert is_valid_uuid(data.get("id", "")), f"{entity}.id must be a server-generated UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"{entity}.created_at must be an ISO 8601 UTC timestamp"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"{entity}.updated_at must be an ISO 8601 UTC timestamp"
    )
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"{entity}.version must be an integer beginning at 1"
    )


def _assert_subordinate_fields(data: dict, entity: str):
    """id and created_at only - the two record types that are never edited."""
    assert is_valid_uuid(data.get("id", "")), f"{entity}.id must be a server-generated UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"{entity}.created_at must be an ISO 8601 UTC timestamp"
    )
    assert "updated_at" not in data, f"{entity} must not carry updated_at"
    assert "version" not in data, f"{entity} must not carry version"


def assert_school(data: dict):
    _assert_common_fields(data, "School")
    assert isinstance(data["name"], str) and data["name"]
    assert data["classification"] in ["C1A", "C2A", "C3A", "C4A", "C5A"]
    assert isinstance(data["region_code"], str)
    assert data["sanction_status"] in SANCTION_STATUSES
    assert isinstance(data["forfeit_count"], int) and data["forfeit_count"] >= 0
    assert isinstance(data["release_minutes_used"], int) and data["release_minutes_used"] >= 0
    assert isinstance(data["fee_collected_cents"], int)
    assert isinstance(data["credential_gap_sports"], list)
    assert isinstance(data["bus_fleet_size"], int) and data["bus_fleet_size"] >= 1
    assert isinstance(data["max_release_minutes_per_request"], int)
    assert isinstance(data["fee_cap_cents"], int)
    assert isinstance(data["venue_concurrent_capacity"], int)
    assert isinstance(data["school_day_end_utc_hhmm"], str)


def assert_student(data: dict):
    _assert_common_fields(data, "Student")
    assert is_valid_uuid(data["school_id"])
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert isinstance(data["birth_date"], str)
    assert isinstance(data["grade_level"], int) and 9 <= data["grade_level"] <= 12
    assert isinstance(data["residency_verified"], bool)
    assert isinstance(data["hardship_waiver_granted"], bool)
    assert isinstance(data["free_reduced_lunch"], bool)
    assert isinstance(data["credits_prior_period"], int)
    assert isinstance(data["credits_current_period"], int)


def assert_staff_credential(data: dict):
    _assert_common_fields(data, "StaffCredential")
    assert is_valid_uuid(data["school_id"])
    assert data["sport"] in ["FOOTBALL", "BASKETBALL", "TRACK", "SOCCER"]
    assert data["role_title"] in ["HEAD_COACH", "ASSISTANT_COACH"]
    assert data["status"] in CREDENTIAL_STATUSES
    assert isinstance(data["certification_expires_on"], str)


def assert_sport_season(data: dict):
    _assert_common_fields(data, "SportSeason")
    assert data["sport"] in ["FOOTBALL", "BASKETBALL", "TRACK", "SOCCER"]
    assert data["classification"] in ["C1A", "C2A", "C3A", "C4A", "C5A"]
    assert data["sport_tier"] in ["TIER_A", "TIER_B", "TIER_C"]
    assert data["status"] in SEASON_STATUSES
    assert isinstance(data["contest_limit"], int) and data["contest_limit"] >= 1
    assert isinstance(data["required_officials"], int) and data["required_officials"] >= 1
    assert isinstance(data["scheduled_contest_count"], int)
    assert isinstance(data["seeded_school_count"], int)
    assert isinstance(data["unseeded_school_count"], int)


def assert_eligibility_case(data: dict):
    _assert_common_fields(data, "EligibilityCase")
    assert is_valid_uuid(data["student_id"])
    assert is_valid_uuid(data["sport_season_id"])
    assert data["status"] in CASE_STATUSES
    assert data["fee_status"] in FEE_STATUSES
    assert data["ineligibility_reason"] in [
        None, "AGE_LIMIT", "RESIDENCY_UNVERIFIED", "TRANSFER_SITOUT",
        "DOCS_INCOMPLETE", "ACADEMIC_GPA",
    ]
    assert data["gpa_variant_applied"] in [None, "PROVISIONAL", "FINAL"]
    for money in ("fee_amount_cents", "fee_paid_cents", "fee_waived_cents",
                  "fee_refunded_cents", "fee_outstanding_cents"):
        assert isinstance(data[money], int), f"EligibilityCase.{money} must be whole cents"
    assert isinstance(data["appeal_count"], int)
    assert isinstance(data["evaluation_count"], int)
    assert_case_fee_ledger(data)


def assert_case_fee_ledger(data: dict):
    """fee_outstanding_cents = amount - paid - waived + refunded, at all times."""
    expected = (
        data["fee_amount_cents"]
        - data["fee_paid_cents"]
        - data["fee_waived_cents"]
        + data["fee_refunded_cents"]
    )
    assert data["fee_outstanding_cents"] == expected, (
        f"fee_outstanding_cents must equal fee_amount_cents less fee_paid_cents, "
        f"less fee_waived_cents, plus fee_refunded_cents: expected {expected}, "
        f"got {data['fee_outstanding_cents']}"
    )


def assert_clearance_document(data: dict):
    _assert_subordinate_fields(data, "ClearanceDocument")
    assert data["doc_type"] in ["PHYSICAL", "PARENT_CONSENT", "CONCUSSION_ACK"]
    assert isinstance(data["issued_on"], str)
    assert isinstance(data["expires_on"], str)
    assert isinstance(data["signer_name"], str)


def assert_contest(data: dict):
    _assert_common_fields(data, "Contest")
    assert is_valid_uuid(data["sport_season_id"])
    assert is_valid_uuid(data["home_school_id"])
    assert is_valid_uuid(data["away_school_id"])
    assert data["status"] in CONTEST_STATUSES
    assert isinstance(data["accepted_official_count"], int)
    assert data["hold_reason"] in [None, "COACH_CREDENTIAL_REVOKED", "ADMIN_POSTPONE"]
    assert isinstance(data["is_playoff"], bool)


def assert_official(data: dict):
    _assert_common_fields(data, "Official")
    assert data["certification_level"] in ["LEVEL_1", "LEVEL_2", "LEVEL_3"]
    assert isinstance(data["accepted_assignment_count"], int)
    assert isinstance(data["full_name"], str) and data["full_name"]


def assert_official_assignment(data: dict):
    _assert_common_fields(data, "OfficialAssignment")
    assert is_valid_uuid(data["contest_id"])
    assert is_valid_uuid(data["official_id"])
    assert data["status"] in ASSIGNMENT_STATUSES
    assert data["stipend_cents"] is None or isinstance(data["stipend_cents"], int)


def assert_transport_request(data: dict):
    _assert_common_fields(data, "TransportRequest")
    assert is_valid_uuid(data["contest_id"])
    assert is_valid_uuid(data["requesting_school_id"])
    assert data["status"] in TRANSPORT_STATUSES
    assert isinstance(data["bus_count"], int) and data["bus_count"] >= 1
    assert isinstance(data["release_minutes"], int) and data["release_minutes"] >= 0
    assert data["cancelled_reason"] in [None, "SCHOOL_REQUEST", "CONTEST_HOLD_CASCADE"]


def assert_injury_report(data: dict):
    _assert_common_fields(data, "InjuryReport")
    assert is_valid_uuid(data["student_id"])
    assert data["injury_type"] in ["CONCUSSION", "FRACTURE", "SPRAIN", "OTHER"]
    assert data["status"] in INJURY_STATUSES
    assert isinstance(data["rtp_stage"], int) and 0 <= data["rtp_stage"] <= 5
    assert isinstance(data["recurrence_count"], int)
    assert isinstance(data["reported_by_user_id"], str) and data["reported_by_user_id"]


def assert_playoff_seed(data: dict):
    _assert_subordinate_fields(data, "PlayoffSeed")
    assert is_valid_uuid(data["sport_season_id"])
    assert is_valid_uuid(data["school_id"])
    for counter in ("wins", "losses", "forfeit_losses", "seed_number"):
        assert isinstance(data[counter], int), f"PlayoffSeed.{counter} must be an integer"
    assert data["seed_number"] >= 1
    assert data["tiebreak_trace"] in [
        "POWER_RATING", "RAW_WIN_PCT", "HEAD_TO_HEAD",
        "FORFEIT_LOSSES", "OPP_AVG_WIN_PCT", "CREATED_AT",
    ]


def assert_four_decimal_places(value, label="value"):
    """Win percentages, opponent averages and power ratings carry four decimals."""
    assert value is not None, f"{label} must be present"
    assert round(float(value), 4) == float(value), (
        f"{label} must be carried to four decimal places, got {value}"
    )


def assert_three_decimal_places(value, label="effective_gpa"):
    """Grade point averages are carried to three decimal places."""
    assert value is not None, f"{label} must be present"
    assert round(float(value), 3) == float(value), (
        f"{label} must be carried to three decimal places, got {value}"
    )


def find_seed(seeds, school_id):
    """Pick one school's bracket row out of a seed listing."""
    matches = [s for s in seeds if s["school_id"] == school_id]
    assert len(matches) == 1, (
        f"Expected exactly one bracket row for school {school_id}, found {len(matches)}"
    )
    return matches[0]


def parse_instant(value: str):
    """Parse an ISO 8601 UTC instant, tolerating a trailing Z and optional millis."""
    from datetime import datetime

    assert isinstance(value, str) and value, f"expected an ISO 8601 instant, got {value!r}"
    text = value.replace("Z", "+00:00")
    return datetime.fromisoformat(text)


def assert_same_instant(actual, expected, label="instant"):
    """Compare two ISO 8601 instants by value rather than by string spelling."""
    assert parse_instant(actual) == parse_instant(expected), (
        f"{label}: expected {expected}, got {actual}"
    )
