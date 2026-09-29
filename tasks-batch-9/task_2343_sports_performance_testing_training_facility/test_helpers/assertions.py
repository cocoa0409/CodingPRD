"""Entity assertions and domain invariant checkers for the Sports Performance Facility API."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common_fields(data: dict, label: str):
    """Every resource carries id, created_at, updated_at and version (PRD §2.5)."""
    assert is_valid_uuid(data.get("id", "")), f"{label}.id must be a bare UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), \
        f"{label}.created_at must be an ISO 8601 UTC timestamp"
    assert is_iso8601_timestamp(data.get("updated_at", "")), \
        f"{label}.updated_at must be an ISO 8601 UTC timestamp"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, \
        f"{label}.version must be a positive integer counter"


# ─── Athlete (PRD §3.1) ─────────────────────────────────────────────────────

def assert_athlete(data: dict):
    _assert_common_fields(data, "Athlete")
    assert isinstance(data["full_name"], str) and 1 <= len(data["full_name"]) <= 120
    assert data["sport"] in ["BASKETBALL", "SOCCER", "BASEBALL", "VOLLEYBALL", "TRACK"]
    assert isinstance(data["position"], str) and 1 <= len(data["position"]) <= 40
    assert data["membership_status"] in ["PENDING_INTAKE", "ACTIVE", "SUSPENDED"]
    assert data["training_clearance"] in ["SCREEN_PENDING", "CLEARED", "RESTRICTED",
                                         "MEDICAL_HOLD"]
    assert isinstance(data["age_years"], int) and data["age_years"] >= 0
    assert -36 <= data["maturity_offset_months"] <= 36
    for counter in ("screen_count", "attended_count", "no_show_count", "no_show_strikes"):
        assert isinstance(data[counter], int) and data[counter] >= 0, \
            f"Athlete.{counter} must be a non-negative integer"
    assert 0 <= data["readiness_index"] <= 100, "readiness_index is confined to 0 through 100"
    if data.get("injury_risk_score") is not None:
        assert 0 <= data["injury_risk_score"] <= 30.00, "risk_score is capped at 30.00"


# ─── Injury record (PRD §3.2) ───────────────────────────────────────────────

def assert_injury_record(data: dict):
    _assert_common_fields(data, "InjuryRecord")
    assert is_valid_uuid(data["athlete_id"])
    assert data["body_region"] in ["KNEE", "SHOULDER", "ANKLE", "HIP", "LUMBAR", "ELBOW"]
    assert data["severity"] in ["MILD", "MODERATE", "SEVERE"]
    assert isinstance(data["rts_required"], bool)
    assert data["status"] in ["ACTIVE_REHAB", "RESOLVED"]


# ─── Test session (PRD §3.1, §3.2) ──────────────────────────────────────────

def assert_test_session(data: dict):
    _assert_common_fields(data, "TestSession")
    assert is_valid_uuid(data["athlete_id"])
    assert data["battery_type"] in ["MOVEMENT_SCREEN", "PERFORMANCE_BATTERY"]
    assert data["status"] in ["DRAFT", "FINALIZED"]
    assert isinstance(data["result_count"], int) and data["result_count"] >= 0
    assert isinstance(data["results"], list)
    assert len(data["results"]) == data["result_count"], \
        "result_count must match the number of stored result rows"


def assert_draft_test_session(data: dict):
    """A new session is DRAFT with every scoring field still null (PRD §3.1)."""
    assert_test_session(data)
    assert data["status"] == "DRAFT"
    assert data["result_count"] == 0
    assert data["results"] == []
    for field in ("age_years_at_test", "effective_age_years", "metric_percentiles",
                  "composite_percentile", "risk_score", "asymmetry_points",
                  "variant_applied", "finalized_at"):
        assert data.get(field) is None, f"a new session must have {field} null"


# ─── Training program and block (PRD §3.3) ──────────────────────────────────

def assert_training_program(data: dict):
    _assert_common_fields(data, "TrainingProgram")
    assert is_valid_uuid(data["athlete_id"])
    assert data["status"] in ["DRAFT", "ACTIVE", "ARCHIVED"]
    assert isinstance(data["block_count"], int) and data["block_count"] >= 0
    assert isinstance(data["total_weeks"], int) and data["total_weeks"] >= 0
    assert data["planned_load_units"] >= 0


def assert_program_block(data: dict):
    _assert_common_fields(data, "ProgramBlock")
    assert is_valid_uuid(data["training_program_id"])
    assert data["phase"] in ["GENERAL_PREP", "SPECIFIC_PREP", "COMPETITION", "TAPER",
                             "TRANSITION"]
    assert data["start_week"] >= 1
    assert data["end_week"] >= data["start_week"]
    assert 40 <= data["target_intensity_pct"] <= 105
    assert data["weekly_volume_units"] > 0
    assert data["status"] in ["PLANNED", "PINNED"]
    assert isinstance(data["sequence_index"], int) and data["sequence_index"] >= 0


# ─── Group session (PRD §3.5) ───────────────────────────────────────────────

def assert_group_session(data: dict):
    _assert_common_fields(data, "GroupSession")
    assert data["site_code"] in ["ONSITE", "OFFSITE"]
    assert 1 <= data["station_count"] <= 12
    assert data["phase_focus"] in ["GENERAL_PREP", "SPECIFIC_PREP", "COMPETITION",
                                   "TRANSITION"]
    assert 1 <= data["max_athletes"] <= 40
    assert data["session_status"] in ["SCHEDULED", "ROSTER_LOCKED", "IN_PROGRESS",
                                      "COMPLETED", "CANCELED"]
    assert data["staffing_status"] in ["STAFF_PENDING", "UNDERSTAFFED", "STAFFED"]
    assert isinstance(data["assigned_staff"], list)
    for counter in ("reserved_count", "waitlisted_count", "attended_count",
                    "no_show_count", "compliant_coach_count"):
        assert isinstance(data[counter], int) and data[counter] >= 0
    assert data["required_coach_count"] >= 1, \
        "every session needs at least one coach no matter how empty it is"
    assert data["athlete_units"] >= 0
    if data["site_code"] == "OFFSITE":
        assert data.get("offsite_location"), \
            "offsite_location is required and non-empty when site_code is OFFSITE"
    else:
        assert data.get("offsite_location") in (None, ""), \
            "offsite_location must be absent or null when site_code is ONSITE"


def assert_staffing_status_consistent(data: dict):
    """staffing_status follows mechanically from the two coach counters (PRD §3.5)."""
    if not data["assigned_staff"] and data["compliant_coach_count"] == 0:
        assert data["staffing_status"] == "STAFF_PENDING"
    elif data["compliant_coach_count"] < data["required_coach_count"]:
        assert data["staffing_status"] == "UNDERSTAFFED"
    else:
        assert data["staffing_status"] == "STAFFED"


# ─── Enrollment (PRD §3.7) ──────────────────────────────────────────────────

def assert_enrollment(data: dict):
    _assert_common_fields(data, "Enrollment")
    assert is_valid_uuid(data["athlete_id"])
    assert is_valid_uuid(data["group_session_id"])
    assert data["status"] in ["RESERVED", "WAITLISTED", "ATTENDED", "NO_SHOW",
                              "LATE_CANCEL", "CANCELED"]
    assert data["funding_preference"] in ["ANY", "PACKAGE_ONLY", "DROP_IN_OK"]
    assert data["funding_source"] in ["TEAM_CONTRACT", "MEMBERSHIP_PACKAGE", "DROP_IN",
                                      "UNFUNDED"]
    assert isinstance(data["charge_cents"], int) and data["charge_cents"] >= 0
    assert isinstance(data["no_show_fee_cents"], int) and data["no_show_fee_cents"] >= 0
    assert isinstance(data["promoted_from_waitlist"], bool)


def assert_waitlisted_enrollment(data: dict):
    """WAITLISTED rows run no funding allocation whatsoever (PRD §3.7)."""
    assert_enrollment(data)
    assert data["status"] == "WAITLISTED"
    assert data["funding_source"] == "UNFUNDED"
    assert data["charge_cents"] == 0
    assert data["membership_package_id"] is None
    assert data["station_number"] is None


# ─── Staff member and certification (PRD §3.4) ──────────────────────────────

def assert_staff_member(data: dict):
    _assert_common_fields(data, "StaffMember")
    assert data["role_title"] in ["HEAD_COACH", "PERFORMANCE_COACH", "INTERN"]
    assert data["credential_status"] in ["COMPLIANT", "EXPIRING", "LAPSED"]
    for counter in ("valid_certification_count", "lapsed_certification_count",
                    "ceu_credits_earned_total"):
        assert isinstance(data[counter], int) and data[counter] >= 0


def assert_certification(data: dict):
    _assert_common_fields(data, "Certification")
    assert is_valid_uuid(data["staff_member_id"])
    assert data["cert_code"] in ["CSCS", "USAW", "CPR_AED", "SCCC"]
    assert data["status"] in ["VALID", "EXPIRING", "LAPSED"]
    assert 0 <= data["ceu_credits_required"] <= 40
    assert data["ceu_credits_earned"] >= 0
    assert data["renewal_count"] >= 0
    assert data["expires_on"] > data["issued_on"], \
        "expires_on must be strictly later than issued_on"


def assert_credential_status_derivation(staff: dict, certification_statuses: list,
                                        insurance_expired: bool):
    """credential_status is decided in the order LAPSED, then EXPIRING, then COMPLIANT."""
    lapsed = sum(1 for s in certification_statuses if s == "LAPSED")
    valid = sum(1 for s in certification_statuses if s in ("VALID", "EXPIRING"))
    if lapsed >= 1 or insurance_expired or valid == 0:
        expected = "LAPSED"
    elif any(s == "EXPIRING" for s in certification_statuses):
        expected = "EXPIRING"
    else:
        expected = "COMPLIANT"
    assert staff["credential_status"] == expected, \
        f"expected credential_status {expected}, got {staff['credential_status']}"


# ─── Funding instruments (PRD §3.6) ─────────────────────────────────────────

def assert_membership_package(data: dict):
    _assert_common_fields(data, "MembershipPackage")
    assert is_valid_uuid(data["athlete_id"])
    assert data["status"] in ["ACTIVE", "FROZEN", "DEPLETED", "EXPIRED"]
    assert 1 <= data["sessions_purchased"] <= 100
    assert data["price_cents"] >= 0
    for counter in ("sessions_remaining", "sessions_reserved", "sessions_consumed",
                    "sessions_forfeited", "frozen_days_total"):
        assert isinstance(data[counter], int) and data[counter] >= 0
    assert_package_conservation(data)


def assert_package_conservation(data: dict):
    """Every credit ever purchased is at all times either remaining, reserved,
    consumed or forfeited (PRD §3.6 conservation identity)."""
    total = (data["sessions_remaining"] + data["sessions_reserved"]
             + data["sessions_consumed"] + data["sessions_forfeited"])
    assert total == data["sessions_purchased"], (
        f"conservation identity broken: {data['sessions_purchased']} purchased but "
        f"remaining {data['sessions_remaining']} + reserved {data['sessions_reserved']} "
        f"+ consumed {data['sessions_consumed']} + forfeited "
        f"{data['sessions_forfeited']} = {total}"
    )


def assert_team_contract(data: dict):
    _assert_common_fields(data, "TeamContract")
    assert data["organization_type"] in ["SCHOOL", "CLUB"]
    assert 1 <= data["contracted_sessions"] <= 500
    assert data["base_rate_cents"] >= 0
    assert data["offsite_allowance"] >= 0
    assert data["status"] in ["DRAFT", "ACTIVE", "CLOSED"]
    assert data["rate_tier"] in ["TIER_1", "TIER_2", "TIER_3"]
    for counter in ("sessions_available", "sessions_reserved", "sessions_delivered",
                    "offsite_sessions_used", "billed_amount_cents"):
        assert isinstance(data[counter], int) and data[counter] >= 0
    assert_contract_slot_conservation(data)


def assert_contract_slot_conservation(data: dict):
    """A contract's slots are at all times available, reserved or delivered."""
    total = (data["sessions_available"] + data["sessions_reserved"]
             + data["sessions_delivered"])
    assert total == data["contracted_sessions"], (
        f"contract slot ledger broken: {data['contracted_sessions']} contracted but "
        f"available {data['sessions_available']} + reserved {data['sessions_reserved']} "
        f"+ delivered {data['sessions_delivered']} = {total}"
    )


def assert_rate_tier_derivation(data: dict):
    """rate_tier is a derived view of sessions_delivered (PRD §3.6)."""
    delivered = data["sessions_delivered"]
    if delivered < 2:
        expected = "TIER_1"
    elif delivered < 5:
        expected = "TIER_2"
    else:
        expected = "TIER_3"
    assert data["rate_tier"] == expected, \
        f"expected rate_tier {expected} at sessions_delivered {delivered}"


# ─── Return to sport and clearance documents (PRD §3.9) ─────────────────────

def assert_rts_plan(data: dict):
    _assert_common_fields(data, "RtsPlan")
    assert is_valid_uuid(data["athlete_id"])
    assert is_valid_uuid(data["injury_record_id"])
    assert data["status"] in ["STAGE_ACTIVE", "STAGE_TESTING", "MEDICAL_REVIEW",
                              "CLEARED", "ABORTED"]
    assert 3 <= data["target_stage_count"] <= 5
    assert 1 <= data["current_stage"] <= data["target_stage_count"]
    assert 0 <= data["stage_attempts"] <= 2, "the maximum attempts allowed at one stage is 2"
    assert data["total_failed_attempts"] >= 0


def assert_clearance_document(data: dict):
    _assert_common_fields(data, "ClearanceDocument")
    assert is_valid_uuid(data["athlete_id"])
    assert data["document_type"] in ["STAGE_CLEARANCE", "FULL_RELEASE",
                                     "MEDICAL_HOLD_RELEASE"]
    assert data["status"] in ["PENDING", "SIGNED", "REVOKED", "EXPIRED"]
    if data["document_type"] == "STAGE_CLEARANCE":
        assert data["rts_plan_id"] is not None
        assert data["stage_number"] is not None and data["stage_number"] >= 1
    elif data["document_type"] == "FULL_RELEASE":
        assert data["rts_plan_id"] is not None
        assert data["stage_number"] is None
    else:
        assert data["rts_plan_id"] is None
        assert data["stage_number"] is None


# ─── Cross-cutting helpers ──────────────────────────────────────────────────

def assert_one_decimal(value, label="value"):
    """Percentile-family figures are carried to one decimal place (PRD §2.7)."""
    assert value is not None, f"{label} must not be null"
    assert round(float(value), 1) == float(value), \
        f"{label} must be rounded to one decimal place, got {value}"


def assert_two_decimals(value, label="value"):
    """Score-family figures are carried to two decimal places (PRD §2.7)."""
    assert value is not None, f"{label} must not be null"
    assert round(float(value), 2) == float(value), \
        f"{label} must be rounded to two decimal places, got {value}"


def assert_whole_cents(value, label="value"):
    """Money is carried as an integer count of cents (PRD §2.7)."""
    assert isinstance(value, int), f"{label} must be an integer count of cents, got {value!r}"


def find_assigned_staff_ids(session: dict) -> list:
    """The staff_member_id of every row in assigned_staff, in order."""
    return [row.get("staff_member_id") for row in session.get("assigned_staff", [])]


def find_metric_percentile(session: dict, metric_code: str):
    """The metric_percentiles entry for one metric code, or None."""
    for row in session.get("metric_percentiles") or []:
        if row.get("metric_code") == metric_code:
            return row
    return None
