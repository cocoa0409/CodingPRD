"""CSA referral report tests: intake, forwarding, duplicates (PRD §3.2)."""
import pytest

from test_helpers import (
    validate_success, validate_error, get_success_data,
    create_active_csa, create_geography, create_received_referral,
    set_clock, make_csa_headers,
    ApiErrorId, assert_referral, NON_EXISTENT_UUID, TEST_USERS,
)

COORD = TEST_USERS["coordinator_headers"]


def test_referral_with_unknown_geography_reference_not_found(api):
    """PRD §2.6: "Foreign keys carried in a request body, namely `geography_id`
    and `referral_id`, resolve separately and produce `ERR_REFERENCE_NOT_FOUND`
    (HTTP 404) when the referenced entity does not exist."

    Design: Corner/entities/referral_with_unknown_geography_reference_not_found
    """
    csa, _ = create_active_csa(
        completed_at="2026-05-01T10:00:00Z", score=95,
        full_name="Dan Dean", email="dan@example.edu",
        department="Students", csa_category="DEAN",
    )
    res = api.create_referral(
        {
            "occurred_at": "2026-06-01T10:00:00Z",
            "geography_id": NON_EXISTENT_UUID,
            "offense_suspicion": "BURGLARY",
            "narrative": "Seen at dorm",
        },
        make_csa_headers(csa["id"]),
    )
    validate_error(res, ApiErrorId.ERR_REFERENCE_NOT_FOUND.value, expected_status=404)


def test_forward_sets_forwarded_fields(api):
    """PRD §3.2: "From `RECEIVED`, the CSA forwards the report to campus police
    ... Forwarding stamps `forwarded_at` and computes `forward_overdue`, which
    is true when the forward happened strictly more than 24 hours after
    `received_at` and false when it happened within or exactly at 24 hours."

    Design: Corner/endpoints/forward_sets_forwarded_fields
    """
    csa, _ = create_active_csa(
        completed_at="2026-06-15T10:00:00Z", score=93,
        full_name="Nora Nurse", email="nora@example.edu",
        department="Health", csa_category="OTHER_OFFICIAL",
    )
    geography = create_geography(name="Clinic", category="ON_CAMPUS")
    referral = create_received_referral(
        csa, geography["id"],
        occurred_at="2026-07-31T21:00:00Z",
        offense_suspicion="DATING_VIOLENCE",
        narrative="x",
    )
    assert referral["status"] == "RECEIVED"

    # Forward at the same logical instant as creation (default clock).
    forwarded = validate_success(
        api.forward_referral(referral["id"], make_csa_headers(csa["id"])), 200
    )
    assert_referral(forwarded)
    assert forwarded["status"] == "FORWARDED"
    assert forwarded["forwarded_at"] == "2026-08-01T00:00:00Z"
    assert forwarded["forward_overdue"] is False


def test_referral_forward_overdue_flag(api):
    """PRD §3.2: "Forwarding stamps `forwarded_at` and computes
    `forward_overdue`, which is true when the forward happened strictly more
    than 24 hours after `received_at` and false when it happened within or
    exactly at 24 hours."

    Design: Corner/calculations/referral_forward_overdue_flag
    """
    csa, _ = create_active_csa(
        completed_at="2026-07-01T10:00:00Z", score=91,
        full_name="Cory Coach", email="cory@example.edu",
        department="Athletics", csa_category="COACH",
    )
    geography = create_geography(name="Field", category="ON_CAMPUS")
    csa_headers = make_csa_headers(csa["id"])

    # R1 created at the default clock 2026-08-01T00:00:00Z.
    r1 = create_received_referral(
        csa, geography["id"],
        occurred_at="2026-07-31T22:00:00Z",
        offense_suspicion="DRUG_LAW_REFERRAL", narrative="R1",
    )
    # Advance the clock 24h00m01s past R1's received_at.
    set_clock("2026-08-02T00:00:01Z")
    # R2 created at 2026-08-02T00:00:01Z and forwarded at the same instant.
    r2 = create_received_referral(
        csa, geography["id"],
        occurred_at="2026-08-01T22:00:00Z",
        offense_suspicion="LIQUOR_LAW_REFERRAL", narrative="R2",
    )

    r1_after = validate_success(api.forward_referral(r1["id"], csa_headers), 200)
    assert r1_after["forward_overdue"] is True, (
        "24h00m01s after received_at is strictly more than 24h -> overdue"
    )
    assert r1_after["status"] == "FORWARDED"

    r2_after = validate_success(api.forward_referral(r2["id"], csa_headers), 200)
    assert r2_after["forward_overdue"] is False, (
        "Forwarding at the creation instant is within 24h -> not overdue"
    )
    assert r2_after["forwarded_at"] == "2026-08-02T00:00:01Z"


def test_referral_mark_duplicate_twice_returns_invalid_state(api):
    """PRD §3.2: "A `CleryCoordinator` may instead mark a `RECEIVED` or
    `FORWARDED` referral as `DUPLICATE` when it duplicates an already-known
    incident; marking from any other status is rejected with
    `ERR_INVALID_STATE`."

    Design: Corner/state_machines/referral_mark_duplicate_twice_returns_invalid_state
    """
    csa, _ = create_active_csa(
        completed_at="2026-06-01T10:00:00Z", score=90,
        full_name="Ann RA", email="ann@example.edu",
        department="Housing", csa_category="RESIDENT_ADVISOR",
    )
    geography = create_geography(
        name="Dorm Row", category="ON_CAMPUS_RESIDENTIAL", is_residential_facility=True
    )
    referral = create_received_referral(
        csa, geography["id"],
        occurred_at="2026-07-01T22:00:00Z",
        offense_suspicion="LIQUOR_LAW_REFERRAL", narrative="Noise and alcohol",
    )

    first = validate_success(api.mark_referral_duplicate(referral["id"], COORD), 200)
    assert first["status"] == "DUPLICATE"

    res = api.mark_referral_duplicate(referral["id"], COORD)
    validate_error(res, ApiErrorId.ERR_INVALID_STATE.value, expected_status=409)

    after = validate_success(api.get_referral(referral["id"], COORD), 200)
    assert after["status"] == "DUPLICATE", "A terminal DUPLICATE referral must not move"


def test_csa_cannot_forward_others_referral(api):
    """PRD §3.2: "only the owning CSA may forward — a caller whose `X-User-ID`
    does not equal the report's `csa_id` is rejected with `ERR_FORBIDDEN`."

    Design: Corner/rbac/csa_cannot_forward_others_referral
    """
    csa1, _ = create_active_csa(
        completed_at="2026-06-01T10:00:00Z", score=90,
        full_name="One", email="one@example.edu", department="A", csa_category="DEAN",
    )
    csa2, _ = create_active_csa(
        completed_at="2026-06-01T10:00:00Z", score=90,
        full_name="Two", email="two@example.edu", department="B", csa_category="COACH",
    )
    geography = create_geography(name="K", category="ON_CAMPUS")
    referral = create_received_referral(
        csa1, geography["id"],
        occurred_at="2026-07-30T21:00:00Z",
        offense_suspicion="STALKING", narrative="x",
    )

    res = api.forward_referral(referral["id"], make_csa_headers(csa2["id"]))
    validate_error(res, ApiErrorId.ERR_FORBIDDEN.value, expected_status=403)

    after = validate_success(api.get_referral(referral["id"], COORD), 200)
    assert after["status"] == "RECEIVED", (
        "A non-owning CSA's forward attempt must leave the referral RECEIVED"
    )
