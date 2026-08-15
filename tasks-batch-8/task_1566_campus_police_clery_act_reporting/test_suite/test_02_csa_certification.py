"""CSA certification and training-record tests (PRD §3.7, §2.4)."""
import pytest

from test_helpers import (
    validate_success, validate_error, get_success_data,
    create_pending_csa, create_active_csa, create_csa_payload,
    create_training_record_payload, create_geography,
    create_received_referral, set_clock, make_csa_headers,
    ApiErrorId, assert_csa, assert_training_record, TEST_USERS,
)

ADMIN = TEST_USERS["admin_headers"]


def test_csa_created_pending_training(api):
    """PRD §3.7: "A new CSA is `PENDING_TRAINING` with `certification_expires_at`
    null until its first passing training record and `active_training_record_id`
    null."

    Design: Corner/entities/csa_created_pending_training
    """
    csa = validate_success(api.create_csa(
        create_csa_payload(
            full_name="Coach Kim", email="kim@example.edu",
            department="Athletics", csa_category="COACH",
        ),
        ADMIN,
    ), 201)
    assert_csa(csa)
    fetched = validate_success(api.get_csa(csa["id"], ADMIN), 200)
    assert fetched["status"] == "PENDING_TRAINING"
    assert fetched["certification_expires_at"] is None


def test_training_record_computed_window_and_pass(api):
    """PRD §3.7: "Each record derives `passed` from that threshold,
    `training_year` as the calendar year of `completed_at`, `valid_from` equal
    to `completed_at`, and `valid_to` as September 30 of the year after
    `training_year` at 23:59:59 UTC, defining a half-open validity window that
    includes `valid_from` and excludes `valid_to`."
    PRD §3.7: "A passing record recorded while the CSA is `PENDING_TRAINING` or
    `LAPSED` flips the CSA to `ACTIVE`, sets `certification_expires_at` to the
    new record's `valid_to`, and points `active_training_record_id` at the new
    record."

    Design: Corner/entities/training_record_computed_window_and_pass
    """
    csa = create_pending_csa(
        full_name="Rita RA", email="rita@example.edu",
        department="Housing", csa_category="RESIDENT_ADVISOR",
    )
    record = validate_success(api.create_training_record(
        csa["id"],
        {"completed_at": "2026-03-01T10:00:00Z", "score": 88},
        ADMIN,
    ), 201)
    assert_training_record(record)
    assert record["passed"] is True
    assert record["training_year"] == 2026
    assert record["valid_from"] == "2026-03-01T10:00:00Z"
    assert record["valid_to"] == "2027-09-30T23:59:59Z"

    csa_after = validate_success(api.get_csa(csa["id"], ADMIN), 200)
    assert csa_after["status"] == "ACTIVE"
    assert csa_after["certification_expires_at"] == "2027-09-30T23:59:59Z"
    assert csa_after["active_training_record_id"] == record["id"]


def test_training_score_79_not_passed(api):
    """PRD §3.7: "A score of at least 80 passes — exactly 80 passes."

    Design: Corner/entities/training_score_79_not_passed
    """
    csa = create_pending_csa(
        full_name="Sam Sec", email="sam@example.edu",
        department="Security", csa_category="SECURITY_STAFF",
    )
    record = validate_success(api.create_training_record(
        csa["id"],
        {"completed_at": "2026-03-01T10:00:00Z", "score": 79},
        ADMIN,
    ), 201)
    assert record["passed"] is False, "Score 79 is one below the pass threshold of 80"

    csa_after = validate_success(api.get_csa(csa["id"], ADMIN), 200)
    assert csa_after["status"] == "PENDING_TRAINING", (
        "A failing score must not activate the CSA"
    )


def test_csa_lapses_when_clock_passes_expiry(api):
    """PRD §3.7: "When the logical clock passes `certification_expires_at`, the
    CSA transitions `ACTIVE → LAPSED` and the training record currently
    conferring certification flips `ACTIVE → EXPIRED`; both transitions are
    evaluated lazily per §2.4."

    Design: Corner/state_machines/csa_lapses_when_clock_passes_expiry
    """
    csa, record = create_active_csa(
        completed_at="2025-06-01T10:00:00Z", score=92,
        full_name="Ollie Official", email="ollie@example.edu",
        department="Admin", csa_category="OTHER_OFFICIAL",
    )
    assert csa["status"] == "ACTIVE"

    # valid_to for training_year 2025 is 2026-09-30T23:59:59Z; move past it.
    set_clock("2026-10-01T00:00:00Z")

    csa_after = validate_success(api.get_csa(csa["id"], ADMIN), 200)
    assert csa_after["status"] == "LAPSED"

    records = get_success_data(api.list_training_records(csa["id"], ADMIN))
    records_list = records if isinstance(records, list) else records.get("items", records)
    statuses = {r["id"]: r["status"] for r in records_list}
    assert statuses[record["id"]] == "EXPIRED", (
        "The certification-conferring record must flip to EXPIRED once the clock passes valid_to"
    )


def test_csa_training_half_open_window_overlap_rejected(api):
    """PRD §3.7: "A new passing record is rejected with
    `ERR_TRAINING_WINDOW_OVERLAP` (HTTP 409) whenever any existing record of
    the same CSA has a window overlapping the new one — that is, the existing
    record's `valid_from` is earlier than the new record's `valid_to` and the
    new record's `valid_from` is earlier than the existing record's
    `valid_to`."

    Design: Difficulty/resource_temporal_overlap/csa_training_half_open_window_overlap
    """
    csa, _ = create_active_csa(
        completed_at="2026-01-15T10:00:00Z", score=90,
        full_name="Dana Dean", email="dana@example.edu",
        department="Student Affairs", csa_category="DEAN",
    )
    # The existing record's window is [2026-01-15T10:00:00Z, 2027-09-30T23:59:59Z).
    # A new record completed 2027-06-01 starts strictly inside that window.
    res = api.create_training_record(
        csa["id"], {"completed_at": "2027-06-01T09:00:00Z", "score": 85}, ADMIN
    )
    validate_error(res, ApiErrorId.ERR_TRAINING_WINDOW_OVERLAP.value, expected_status=409)


def test_csa_training_window_adjacency_permitted(api):
    """PRD §3.7: "Adjacency is not overlap: a new record whose `valid_from`
    equals an existing record's `valid_to` is permitted."

    Design: Difficulty/resource_temporal_overlap/csa_training_half_open_window_overlap
    """
    csa, _ = create_active_csa(
        completed_at="2026-01-15T10:00:00Z", score=90,
        full_name="Dana Dean", email="dana@example.edu",
        department="Student Affairs", csa_category="DEAN",
    )
    # 2027-10-05 is strictly after the existing valid_to 2027-09-30T23:59:59Z.
    record = validate_success(api.create_training_record(
        csa["id"], {"completed_at": "2027-10-05T09:00:00Z", "score": 85}, ADMIN
    ), 201)
    assert record["valid_to"] == "2028-09-30T23:59:59Z"

    csa_after = validate_success(api.get_csa(csa["id"], ADMIN), 200)
    assert csa_after["status"] == "ACTIVE"
    assert csa_after["certification_expires_at"] == "2028-09-30T23:59:59Z"


def test_lapsed_csa_cannot_file_referral(api):
    """PRD §3.2: "Filing is only possible while the caller CSA is `ACTIVE`; a
    referral from a `PENDING_TRAINING`, `LAPSED`, or `INACTIVE` authority is
    rejected with `ERR_CSA_NOT_CERTIFIED` (HTTP 422)."

    Design: Corner/validations/lapsed_csa_cannot_file_referral
    """
    csa, _ = create_active_csa(
        completed_at="2025-06-01T10:00:00Z", score=88,
        full_name="Lee Lapsed", email="lee@example.edu",
        department="Housing", csa_category="RESIDENT_ADVISOR",
    )
    # valid_to = 2026-09-30T23:59:59Z; advance beyond it so the CSA reads LAPSED.
    set_clock("2026-10-02T00:00:00Z")
    csa_after = validate_success(api.get_csa(csa["id"], ADMIN), 200)
    assert csa_after["status"] == "LAPSED"

    geography = create_geography(
        name="Hall E", category="ON_CAMPUS_RESIDENTIAL", is_residential_facility=True
    )
    res = api.create_referral(
        {
            "occurred_at": "2026-10-01T22:00:00Z",
            "geography_id": geography["id"],
            "offense_suspicion": "DRUG_LAW_REFERRAL",
            "narrative": "x",
        },
        make_csa_headers(csa["id"]),
    )
    validate_error(res, ApiErrorId.ERR_CSA_NOT_CERTIFIED.value, expected_status=422)
