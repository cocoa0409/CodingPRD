"""Entity-shape assertions and domain invariant checkers."""

import pytest
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .constants import RATIO_TOLERANCE, SCORE_TOLERANCE

# ---------------------------------------------------------------------------
# Generic helpers
# ---------------------------------------------------------------------------


def assert_common_fields(entity: dict, label: str = "entity") -> None:
    """Every persisted resource carries id, created_at, updated_at and version."""
    assert is_valid_uuid(entity.get("id")), f"{label}.id must be a UUID, got {entity.get('id')!r}"
    assert is_iso8601_timestamp(
        entity.get("created_at")
    ), f"{label}.created_at must be an ISO 8601 UTC timestamp, got {entity.get('created_at')!r}"
    assert is_iso8601_timestamp(
        entity.get("updated_at")
    ), f"{label}.updated_at must be an ISO 8601 UTC timestamp, got {entity.get('updated_at')!r}"
    assert isinstance(
        entity.get("version"), int
    ), f"{label}.version must be an integer, got {entity.get('version')!r}"
    assert entity["version"] >= 1, f"{label}.version starts at 1, got {entity['version']}"


def assert_score(actual, expected: float, label: str) -> None:
    """Two-decimal score, density, index or deduction comparison."""
    assert actual is not None, f"{label} must be present"
    assert float(actual) == pytest.approx(
        expected, abs=SCORE_TOLERANCE
    ), f"{label} should be {expected}, got {actual}"


def assert_ratio(actual, expected: float, label: str) -> None:
    """Four-decimal study ratio comparison."""
    assert actual is not None, f"{label} must be present"
    assert float(actual) == pytest.approx(
        expected, abs=RATIO_TOLERANCE
    ), f"{label} should be {expected}, got {actual}"


def assert_is_null(entity: dict, field: str, label: str = "entity") -> None:
    """A field the PRD says is null: absent or explicitly None both satisfy."""
    assert (
        entity.get(field) is None
    ), f"{label}.{field} should be null, got {entity.get(field)!r}"


def assert_timestamp_equals(actual, expected_prefix: str, label: str) -> None:
    """Compare a minted timestamp against an instant, ignoring fractional digits.

    The PRD stamps ``_at`` values from the logical clock and renders them with
    three fractional digits, so ``2026-10-05T09:00:00Z`` may be serialized as
    ``2026-10-05T09:00:00.000Z``.
    """
    assert actual is not None, f"{label} must be present"
    stem = expected_prefix.rstrip("Z")
    assert str(actual).startswith(
        stem
    ), f"{label} should be {expected_prefix}, got {actual}"


# ---------------------------------------------------------------------------
# Per-entity shape assertions
# ---------------------------------------------------------------------------


def assert_project(project: dict) -> None:
    assert_common_fields(project, "Project")
    for field in ("name", "voltage_class", "jurisdiction_state", "stage", "schedule_posture"):
        assert field in project, f"Project must expose {field}"
    assert project["voltage_class"] in ("KV_138", "KV_345", "KV_500")
    assert project["stage"] in (
        "PLANNING",
        "ROUTING",
        "APPLICATION_FILED",
        "CERTIFICATED",
        "CONSTRUCTION",
        "ENERGIZED",
    )
    assert project["schedule_posture"] in ("ON_TRACK", "AT_RISK", "CRITICAL")
    assert isinstance(project.get("right_of_way_hold"), bool)
    for field in (
        "escrow_funded_cents",
        "escrow_balance_cents",
        "escrow_disbursed_cents",
        "easement_committed_cents",
    ):
        assert isinstance(project.get(field), int), f"Project.{field} must be integer cents"


def assert_planning_study(study: dict) -> None:
    assert_common_fields(study, "PlanningStudy")
    assert study["status"] in (
        "DRAFT",
        "ALTERNATIVES_ANALYZED",
        "CERTIFIED_SUFFICIENT",
        "INSUFFICIENT",
    )
    assert "authored_by_user_id" in study, "PlanningStudy must record authored_by_user_id"


def assert_alternative(alternative: dict) -> None:
    assert_common_fields(alternative, "Alternative")
    assert alternative["kind"] in ("TRANSMISSION", "NON_TRANSMISSION", "HYBRID")
    assert alternative["screening_status"] in ("SUBMITTED", "SCREENED_IN", "SCREENED_OUT")
    assert alternative.get("levelized_cost_cents_per_mw") is not None


def assert_route(route: dict) -> None:
    assert_common_fields(route, "Route")
    assert route["kind"] in ("PROPOSED", "ALTERNATE")
    assert route["status"] in (
        "DRAFT",
        "CONSTRAINT_MAPPED",
        "PUBLISHED_FOR_COMMENT",
        "REFINING",
        "NOMINATED",
        "CERTIFIED",
        "REJECTED",
    )
    assert isinstance(route.get("segment_count"), int)
    assert isinstance(route.get("refinement_round"), int)


def assert_route_segment(segment: dict) -> None:
    assert_common_fields(segment, "RouteSegment")
    assert segment["survey_status"] in ("DESKTOP", "FIELD_VERIFIED")
    assert segment["federal_permit_status"] in (
        "NOT_REQUIRED",
        "REQUIRED",
        "APPLIED",
        "ISSUED",
        "DENIED",
    )
    assert segment["construction_state"] in ("PENDING", "ACTIVE", "HALTED", "COMPLETE")
    for rating in (
        "land_use_rating",
        "environmental_rating",
        "cultural_rating",
        "engineering_rating",
    ):
        assert 0 <= segment[rating] <= 5, f"RouteSegment.{rating} must be 0..5"


def assert_public_comment(comment: dict) -> None:
    assert_common_fields(comment, "PublicComment")
    assert comment["materiality"] in ("MATERIAL", "GENERAL")
    assert comment["status"] in ("RECEIVED", "ACKNOWLEDGED", "INCORPORATED", "DISMISSED")


def assert_siting_application(application: dict) -> None:
    assert_common_fields(application, "SitingApplication")
    assert application["review_status"] in (
        "FILED",
        "DEFICIENT",
        "ACCEPTED",
        "GRANTED",
        "DENIED",
    )
    assert application["record_status"] in (
        "NOT_OPENED",
        "SCHEDULING",
        "EVIDENTIARY_REQUIRED",
        "RECORD_OPEN",
        "RECORD_CLOSED",
    )
    for field in ("party_count", "suspension_days", "amendment_round"):
        assert isinstance(application.get(field), int), f"SitingApplication.{field} must be int"


def assert_hearing_session(session: dict) -> None:
    assert_common_fields(session, "HearingSession")
    assert session["kind"] in ("PREHEARING", "EVIDENTIARY", "PUBLIC_TESTIMONY")
    assert session["status"] in ("SCHEDULED", "HELD")
    assert "presiding_user_id" in session


def assert_intervention(intervention: dict) -> None:
    assert_common_fields(intervention, "Intervention")
    assert intervention["petitioner_kind"] in ("LANDOWNER", "INTEREST_GROUP")
    assert intervention["status"] in ("PETITIONED", "GRANTED", "DENIED")


def assert_certificate(certificate: dict) -> None:
    assert_common_fields(certificate, "Certificate")
    assert certificate["status"] in ("ISSUED", "CLOSED")
    assert certificate["posture"] in ("ACTIVE", "STOP_WORK", "REVOKED")
    assert certificate["escrow_tier"] in ("TIER_1", "TIER_2", "TIER_3")
    for field in (
        "mitigation_base_cents",
        "contingency_cents",
        "condition_surcharge_cents",
        "escrow_required_cents",
    ):
        assert isinstance(certificate.get(field), int), f"Certificate.{field} must be integer cents"


def assert_certificate_condition(condition: dict) -> None:
    assert_common_fields(condition, "CertificateCondition")
    assert condition["category"] in (
        "ENVIRONMENTAL",
        "CULTURAL",
        "LAND_USE",
        "ENGINEERING",
        "PUBLIC_SAFETY",
    )
    assert condition["constraint_kind"] in (
        "SEASONAL_BLACKOUT",
        "CREW_LIMIT",
        "NOTICE",
        "MONITORING",
    )
    assert condition["status"] in ("ACTIVE", "VIOLATED", "WAIVED")
    assert 1 <= condition["severity_weight"] <= 5


def assert_landowner(landowner: dict) -> None:
    assert_common_fields(landowner, "Landowner")
    for field in ("name", "email", "mailing_address"):
        assert field in landowner, f"Landowner must expose {field}"


def assert_easement_tract(tract: dict) -> None:
    assert_common_fields(tract, "EasementTract")
    assert tract["acquisition_status"] in (
        "NOT_STARTED",
        "OFFERED",
        "AGREED",
        "REJECTED",
        "CONDEMNATION_FILED",
        "AWARDED",
    )
    assert tract["payment_status"] in ("UNPAID", "PAID", "RESCINDED")
    assert isinstance(tract.get("offer_round"), int)
    assert isinstance(tract.get("committed_cents"), int)


def assert_construction_activity(activity: dict) -> None:
    assert_common_fields(activity, "ConstructionActivity")
    assert activity["activity_kind"] in ("CLEARING", "FOUNDATION", "STRINGING")
    assert activity["status"] in (
        "SCHEDULED",
        "IN_PROGRESS",
        "SUSPENDED",
        "COMPLETE",
        "CANCELLED",
    )
    assert activity["crew_count"] >= 1


def assert_nonconformance(finding: dict) -> None:
    assert_common_fields(finding, "Nonconformance")
    assert finding["severity"] in ("MINOR", "MAJOR", "SEVERE")
    assert finding["status"] in ("OPEN", "CORRECTED", "VOIDED")
    assert finding.get("deduction_points") is not None


# ---------------------------------------------------------------------------
# Domain invariants
# ---------------------------------------------------------------------------


def assert_escrow_conservation(project: dict) -> None:
    """PRD §2.9: the funded total always equals balance plus disbursed."""
    funded = project["escrow_funded_cents"]
    balance = project["escrow_balance_cents"]
    disbursed = project["escrow_disbursed_cents"]
    assert funded == balance + disbursed, (
        "Escrow conservation broken: funded "
        f"{funded} != balance {balance} + disbursed {disbursed}"
    )


def assert_posture_matches_indices(certificate: dict) -> None:
    """PRD §3.9: posture is derived from the two indices, in a fixed order."""
    rolling = float(certificate["compliance_index_rolling"])
    cumulative = float(certificate["compliance_index_cumulative"])
    if cumulative < 25.00:
        expected = "REVOKED"
    elif rolling < 60.00:
        expected = "STOP_WORK"
    else:
        expected = "ACTIVE"
    assert certificate["posture"] == expected, (
        f"posture should be {expected} for rolling {rolling} / cumulative "
        f"{cumulative}, got {certificate['posture']}"
    )


def assert_hold_matches_posture(project: dict) -> None:
    """PRD §3.5: right_of_way_hold is true exactly when posture is AT_RISK or CRITICAL."""
    expected = project["schedule_posture"] in ("AT_RISK", "CRITICAL")
    assert project["right_of_way_hold"] is expected, (
        f"right_of_way_hold should be {expected} for schedule_posture "
        f"{project['schedule_posture']}, got {project['right_of_way_hold']}"
    )
