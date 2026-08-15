"""Entity assertions and domain invariant checkers (PRD §2.5, §3)."""
from datetime import datetime, timezone

from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _parse_instant(value: str) -> datetime:
    """Parse an ISO 8601 UTC timestamp (with or without fractional digits)."""
    assert isinstance(value, str), f"expected an ISO 8601 string, got {value!r}"
    s = value.strip()
    if s.endswith(("Z", "z")):
        s = s[:-1] + "+00:00"
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def assert_same_instant(actual: str, expected: str):
    """Two ISO 8601 strings denote the same instant.

    PRD pins the instant each business timestamp records (e.g. "sets
    `finalized_at` to the logical now", §3.5) but leaves the wire format of
    business datetime fields open — only `created_at`/`updated_at`/
    `api_request_timestamp` carry the three-fractional-digit convention
    (§2.2/§2.5). Compare instants, not string representations.
    """
    assert _parse_instant(actual) == _parse_instant(expected), (
        f"instant mismatch: {actual!r} != {expected!r}"
    )


def _assert_common_fields(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        "created_at must be ISO 8601"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        "updated_at must be ISO 8601"
    )
    assert isinstance(data.get("version"), int), "version must be an integer"


def _assert_ledger_fields(data: dict):
    """Append-only ledgers carry only id + created_at (PRD §2.5)."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        "created_at must be ISO 8601"
    )
    assert "updated_at" not in data, "append-only ledger must not carry updated_at"
    assert "version" not in data, "append-only ledger must not carry version"


def assert_horse(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["name"], str) and data["name"]
    assert data["sex"] in ("MARE", "GELDING", "STALLION")
    assert data["breed_class"] in ("LIGHT", "DRAFT", "PONY")
    assert isinstance(data["estimated_weight_lbs"], int)
    assert data["estimated_weight_lbs"] > 0
    assert isinstance(data["age_years"], int) and data["age_years"] >= 0
    assert isinstance(data["body_condition_score"], int)
    assert 1 <= data["body_condition_score"] <= 9
    assert isinstance(data["temperament_score"], int)
    assert data["training_level"] in ("UNHANDLED", "GREEN", "TRAINED_RIDDEN")
    assert data["status"] in (
        "QUARANTINE", "REHABILITATION", "ADOPTABLE", "ADOPTION_PENDING",
        "ADOPTED", "SANCTUARY", "END_OF_LIFE_REVIEW", "DECEASED",
    )
    assert data["current_location"] in (
        "QUARANTINE_STALL", "REHAB_PADDOCK", "MAIN_PASTURE",
        "SANCTUARY_PASTURE", "OFFSITE_ADOPTED", "NOT_APPLICABLE",
    )
    ration = data["daily_feed_ration_lbs"]
    assert isinstance(ration, (int, float)) and ration > 0


def assert_intake_evaluation(data: dict):
    _assert_common_fields(data)
    assert data["evaluation_type"] in ("MEDICAL", "BEHAVIORAL", "FARRIERY")
    assert data["status"] in ("SCHEDULED", "COMPLETED")


def assert_quarantine_protocol(data: dict):
    _assert_common_fields(data)
    assert data["status"] in ("ACTIVE", "CLEARED")
    assert isinstance(data["min_days"], int) and 1 <= data["min_days"] <= 60
    assert isinstance(data["extension_days"], int) and data["extension_days"] >= 0


def assert_daily_health_log(data: dict):
    _assert_ledger_fields(data)
    assert isinstance(data["temp_f"], (int, float))
    assert 95.0 <= data["temp_f"] <= 110.0
    assert data["appetite"] in ("NORMAL", "REDUCED", "NONE")


def assert_rehabilitation_plan(data: dict):
    _assert_common_fields(data)
    assert data["status"] in ("DRAFT", "ACTIVE", "COMPLETED", "SUPERSEDED")
    assert isinstance(data["completed_visit_count"], int)
    assert 1 <= data["target_body_condition_score"] <= 9
    assert 1 <= data["planned_weeks"] <= 52


def assert_practitioner(data: dict):
    _assert_common_fields(data)
    assert data["specialty"] in ("VETERINARIAN", "FARRIER")
    assert isinstance(data["active"], bool)


def assert_care_service_appointment(data: dict):
    _assert_common_fields(data)
    assert data["service_type"] in (
        "VET_EXAM", "VET_PROCEDURE", "DENTAL", "FARRIER_TRIM", "FARRIER_SHOEING",
    )
    assert data["status"] in ("REQUESTED", "CONFIRMED", "COMPLETED", "CANCELLED")
    assert data["billing_status"] in ("UNBILLED", "BILLED")


def assert_stall(data: dict):
    _assert_common_fields(data)
    assert data["barn_zone"] in ("QUARANTINE_BARN", "MAIN_BARN", "ISOLATION")
    assert isinstance(data["active"], bool)


def assert_stall_assignment(data: dict):
    _assert_common_fields(data)
    assert data["status"] in ("ACTIVE", "ENDED")


def assert_adopter(data: dict):
    _assert_common_fields(data)
    assert data["experience_level"] in ("NOVICE", "INTERMEDIATE", "EXPERT")
    assert data["status"] in ("ACTIVE", "BLOCKED")


def assert_adoption_application(data: dict):
    _assert_common_fields(data)
    assert data["status"] in (
        "SUBMITTED", "UNDER_REVIEW", "HOME_CHECK_SCHEDULED", "HOME_CHECK_PASSED",
        "APPROVED", "FINALIZED", "RETURN_COMPLETED", "REJECTED", "WITHDRAWN",
    )
    assert isinstance(data["home_check_attempts"], int)
    assert isinstance(data["fee_paid_cents"], int)
    assert isinstance(data["refund_cents"], int)


def assert_home_check(data: dict):
    _assert_common_fields(data)
    assert data["status"] in ("SCHEDULED", "COMPLETED")


def assert_follow_up_visit(data: dict):
    _assert_common_fields(data)
    assert data["visit_type"] in ("DAY_30", "DAY_90", "DAY_180")
    assert data["status"] in ("SCHEDULED", "COMPLETED", "CANCELLED")


def assert_sanctuary_care_plan(data: dict):
    _assert_common_fields(data)
    assert data["variant"] in ("ACTUARIAL", "STRAIGHT_LINE")
    assert data["status"] in ("DRAFT", "APPROVED", "SUPERSEDED", "CLOSED")
    assert data["funding_status"] in ("UNFUNDED", "PARTIALLY_FUNDED", "FUNDED")
    assert isinstance(data["projected_months"], int)
    assert isinstance(data["monthly_cost_cents"], int)
    assert isinstance(data["total_lifetime_cost_cents"], int)
    assert isinstance(data["funding_coverage_cents"], int)


def assert_sponsor(data: dict):
    _assert_common_fields(data)
    assert data["status"] in ("ACTIVE", "INACTIVE")


def assert_sponsorship(data: dict):
    _assert_common_fields(data)
    assert data["status"] in (
        "PLEDGED", "ACTIVE", "LAPSED", "COMPLETED", "CANCELLED",
    )
    assert isinstance(data["monthly_pledge_cents"], int)


def assert_feed_lot(data: dict):
    _assert_common_fields(data)
    assert data["feed_type"] in ("GRASS_HAY", "ALFALFA", "GRAIN", "SUPPLEMENT")
    assert isinstance(data["quantity_lbs"], (int, float))
    assert isinstance(data["initial_lbs"], (int, float))
    assert isinstance(data["lot_cost_cents"], int)


def assert_feed_day_close(data: dict):
    _assert_ledger_fields(data)
    assert data["feed_type"] in ("GRASS_HAY", "ALFALFA", "GRAIN", "SUPPLEMENT")
    assert isinstance(data["consumed_lbs"], (int, float))
    assert isinstance(data["wasted_lbs"], (int, float))
    assert isinstance(data["shortfall_lbs"], (int, float))


def assert_purchase_order(data: dict):
    _assert_common_fields(data)
    assert data["feed_type"] in ("GRASS_HAY", "ALFALFA", "GRAIN", "SUPPLEMENT")
    assert data["status"] in (
        "DRAFT", "ORDERED", "PARTIALLY_RECEIVED", "RECEIVED",
    )
    assert isinstance(data["estimated_total_cents"], int)
    assert isinstance(data["actual_total_cents"], int)
    assert isinstance(data["received_lbs"], (int, float))


def assert_volunteer(data: dict):
    _assert_common_fields(data)
    assert data["status"] in ("ACTIVE", "SUSPENDED")
    assert isinstance(data["skills"], list) and len(data["skills"]) > 0
    assert isinstance(data["completed_shift_count"], int)
    assert isinstance(data["no_show_count"], int)
    assert isinstance(data["reliability_score"], int)
    assert 0 <= data["reliability_score"] <= 100


def assert_barn_shift(data: dict):
    _assert_common_fields(data)
    assert data["status"] in ("OPEN", "ASSIGNED", "COMPLETED", "NO_SHOW")
    assert data["barn_zone"] in (
        "QUARANTINE_BARN", "MAIN_BARN", "ISOLATION", "PASTURES",
    )
    assert data["required_skill"] in (
        "FEEDING", "CLEANING", "HANDLING", "MAINTENANCE", "ANY",
    )


def assert_euthanasia_case(data: dict):
    _assert_common_fields(data)
    assert data["status"] in (
        "PROPOSED", "CERTIFIED", "AUTHORIZED", "EXECUTED", "OVERRIDDEN",
    )
    assert isinstance(data["suffering_score"], int)
    assert 1 <= data["suffering_score"] <= 10
    assert isinstance(data["emergency_certified"], bool)


def assert_funding_consistent(plan: dict):
    """PRD §3.6 funding_status derivation must agree with coverage and cost."""
    coverage = plan["funding_coverage_cents"]
    monthly = plan["monthly_cost_cents"]
    if coverage == 0:
        assert plan["funding_status"] == "UNFUNDED"
    elif coverage < monthly:
        assert plan["funding_status"] == "PARTIALLY_FUNDED"
    else:
        assert plan["funding_status"] == "FUNDED"
