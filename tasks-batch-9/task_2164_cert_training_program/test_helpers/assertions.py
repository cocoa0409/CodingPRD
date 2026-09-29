"""Entity assertions and domain invariant checkers for the CERT Training Program API."""

import re

from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp

_BARE_UUID = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
)
_ISO_MILLIS = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}(Z|[+-]\d{2}:\d{2})$")


def assert_common_fields(data: dict, entity: str = "entity"):
    """Every entity in this API carries id, created_at, updated_at and version."""
    assert is_valid_uuid(data.get("id", "")), f"{entity}.id must be a UUID string"
    assert _BARE_UUID.match(data["id"]), (
        f"{entity}.id must be a bare UUID with no type prefix, got {data['id']!r}"
    )
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"{entity}.created_at must be an ISO 8601 UTC timestamp"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"{entity}.updated_at must be an ISO 8601 UTC timestamp"
    )
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"{entity}.version must be an integer starting at 1"
    )


def assert_iso8601_with_millis(value: str, label: str = "timestamp"):
    """The PRD pins three fractional-second digits on stored timestamps."""
    assert isinstance(value, str) and _ISO_MILLIS.match(value), (
        f"{label} must be ISO 8601 UTC with three fractional digits, got {value!r}"
    )


def same_instant(actual, expected) -> bool:
    """Compare two ISO 8601 UTC instants that may differ in fractional digits."""
    if actual is None:
        return False

    def norm(v: str) -> str:
        v = v.strip()
        if v.endswith("Z"):
            v = v[:-1]
        if "+" in v[10:]:
            v = v[: v.index("+", 10)]
        if "." in v:
            head, frac = v.split(".", 1)
            frac = (frac + "000")[:3]
            if frac == "000":
                return head
            return head + "." + frac
        return v

    return norm(actual) == norm(expected)


def assert_instant(actual, expected, label="timestamp"):
    assert same_instant(actual, expected), (
        f"Expected {label} == {expected}, got {actual}"
    )


def assert_program(data: dict):
    assert_common_fields(data, "Program")
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["sponsor_agency"], str)
    assert isinstance(data["jurisdiction_code"], str)
    assert isinstance(data["equipment_budget_cents"], int)
    assert isinstance(data["equipment_committed_cents"], int)
    assert data["equipment_committed_cents"] >= 0
    assert isinstance(data["active_member_count"], int)
    assert isinstance(data["pending_graduation_count"], int)


def assert_cohort(data: dict):
    assert_common_fields(data, "Cohort")
    assert data["status"] in [
        "RECRUITING", "SCHEDULED", "IN_SESSION", "GRADUATION_REVIEW", "CLOSED", "CANCELLED",
    ], f"Unexpected cohort status {data['status']}"
    assert isinstance(data["seat_capacity"], int) and data["seat_capacity"] >= 1
    assert isinstance(data["seats_confirmed"], int) and data["seats_confirmed"] >= 0
    assert isinstance(data["seats_waitlisted"], int) and data["seats_waitlisted"] >= 0
    assert isinstance(data["next_waitlist_position"], int) and data["next_waitlist_position"] >= 1
    assert isinstance(data["delivered_contact_hours"], (int, float))


def assert_curriculum_module(data: dict):
    assert_common_fields(data, "CurriculumModule")
    assert data["status"] in ["ACTIVE", "RETIRED"]
    assert isinstance(data["is_core"], bool)
    assert isinstance(data["requires_skills_demo"], bool)
    assert isinstance(data["refresher_eligible"], bool)
    assert data["contact_hours"] > 0
    assert isinstance(data["sequence_index"], int) and data["sequence_index"] >= 1


def assert_facility(data: dict):
    assert_common_fields(data, "Facility")
    assert data["status"] in ["ACTIVE", "CLOSED"]
    assert isinstance(data["capacity_seats"], int) and data["capacity_seats"] >= 1


def assert_instructor(data: dict):
    assert_common_fields(data, "Instructor")
    assert data["status"] in ["ACTIVE", "INACTIVE"]
    assert data["max_daily_contact_hours"] > 0


def assert_class_session(data: dict):
    assert_common_fields(data, "ClassSession")
    assert data["status"] in ["SCHEDULED", "DELIVERED", "CANCELLED"]
    assert isinstance(data["recorded_completion_count"], int)
    assert is_iso8601_timestamp(data["starts_at"])
    assert is_iso8601_timestamp(data["ends_at"])


def assert_trainee(data: dict):
    assert_common_fields(data, "Trainee")
    assert data["enrollment_status"] in [
        "APPLIED", "WAITLISTED", "ENROLLED", "GRADUATED", "WITHDRAWN",
    ]
    assert data["currency_status"] in [
        "NOT_CREDENTIALED", "CURRENT", "LAPSING", "LAPSED", "REVOKED",
    ]
    assert isinstance(data["passed_core_count"], int) and data["passed_core_count"] >= 0
    assert data["earned_contact_hours"] >= 0
    assert 0.0 <= data["readiness_score"] <= 100.0, (
        f"readiness_score must be clamped to 0.00-100.00, got {data['readiness_score']}"
    )
    assert isinstance(data["equipment_liability_cents"], int)


def assert_module_completion(data: dict):
    assert_common_fields(data, "ModuleCompletion")
    assert data["status"] in [
        "RECORDED", "SKILLS_PENDING", "PASSED", "FAILED", "VOIDED",
    ]
    assert isinstance(data["attempt_number"], int) and data["attempt_number"] >= 1
    assert data["attendance_minutes"] >= 0
    assert data["credited_contact_hours"] >= 0


def assert_credential(data: dict):
    assert_common_fields(data, "Credential")
    assert data["status"] in ["ACTIVE", "GRACE", "EXPIRED", "SUSPENDED", "REVOKED"]
    assert isinstance(data["reinstatement_count"], int) and data["reinstatement_count"] >= 0
    assert data["renewal_tier"] in ["STANDARD", "WATCH", "PROBATION"]
    assert data["refresher_hours_in_term"] >= 0


def assert_equipment_asset(data: dict):
    assert_common_fields(data, "EquipmentAsset")
    assert data["status"] in ["IN_STOCK", "ISSUED", "RETIRED", "LOST"]
    assert data["condition"] in ["NEW", "SERVICEABLE", "DAMAGED", "WRITTEN_OFF"]
    assert data["kit_type"] in ["BACKPACK_STANDARD", "BACKPACK_ADVANCED", "RADIO_KIT"]
    assert isinstance(data["unit_value_cents"], int) and data["unit_value_cents"] >= 1
    assert isinstance(data["issue_count"], int) and data["issue_count"] >= 0


def assert_equipment_issuance(data: dict):
    assert_common_fields(data, "EquipmentIssuance")
    assert data["status"] in ["ISSUED", "RETURNED", "LOST_WRITTEN_OFF"]
    assert isinstance(data["settlement_cents"], int)
    if data.get("settlement_variant") is not None:
        assert data["settlement_variant"] in ["DEPRECIATED_WRITEOFF", "FULL_REPLACEMENT"]


def assert_exercise(data: dict):
    assert_common_fields(data, "Exercise")
    assert data["status"] in [
        "PLANNED", "RUNNING", "COMPLETED", "AAR_SUBMITTED", "AAR_ACCEPTED", "CANCELLED",
    ]
    assert data["exercise_type"] in ["TABLETOP", "FUNCTIONAL", "FULL_SCALE"]
    assert isinstance(data["accepted_participant_count"], int)


def assert_exercise_participation(data: dict):
    assert_common_fields(data, "ExerciseParticipation")
    assert data["status"] in ["REGISTERED", "CREDITED", "VOIDED"]
    assert data["role_played"] in [
        "TEAM_LEADER", "SEARCH_RESCUE", "MEDICAL", "LOGISTICS", "OBSERVER",
    ]
    assert data["hours_credited"] >= 0


def assert_activation(data: dict):
    assert_common_fields(data, "Activation")
    assert data["status"] in [
        "REQUESTED", "ROSTERED", "ACTIVATED", "DEMOBILIZED", "CANCELLED",
    ]
    assert data["fill_status"] in ["UNFILLED", "PARTIAL", "FILLED"]
    assert data["severity"] in ["ROUTINE", "URGENT", "CRITICAL"]
    assert isinstance(data["requested_responders"], int) and data["requested_responders"] >= 1
    for counter in ("rostered_count", "accepted_count", "deployed_count"):
        assert isinstance(data[counter], int) and data[counter] >= 0


def assert_roster_assignment(data: dict):
    assert_common_fields(data, "RosterAssignment")
    assert data["status"] in [
        "NOTIFIED", "ACCEPTED", "DECLINED", "NO_RESPONSE", "DEPLOYED", "RELEASED", "WITHDRAWN",
    ]
    assert data["source"] in ["AUTO_ROSTER", "MANUAL_ADD"]
    assert isinstance(data["selection_rank"], int) and data["selection_rank"] >= 1


def assert_fill_status_matches_counts(activation: dict):
    """fill_status is derived from rostered_count against requested_responders."""
    rostered = activation["rostered_count"]
    requested = activation["requested_responders"]
    if rostered == 0:
        expected = "UNFILLED"
    elif rostered < requested:
        expected = "PARTIAL"
    else:
        expected = "FILLED"
    assert activation["fill_status"] == expected, (
        f"fill_status should be {expected} for rostered_count {rostered} "
        f"against requested_responders {requested}, got {activation['fill_status']}"
    )


def assert_hours(actual, expected, label="hours"):
    """Hours are held to one decimal place."""
    assert round(float(actual), 1) == round(float(expected), 1), (
        f"Expected {label} == {expected}, got {actual}"
    )


def assert_score(actual, expected, label="score"):
    """Scores and ratios are compared at two decimal places."""
    assert round(float(actual), 2) == round(float(expected), 2), (
        f"Expected {label} == {expected}, got {actual}"
    )
