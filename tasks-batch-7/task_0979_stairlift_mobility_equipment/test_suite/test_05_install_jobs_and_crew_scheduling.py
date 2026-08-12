"""Install job lifecycle gates and technician-crew scheduling discipline
(60-minute install buffer vs daily removal capacity)."""
import pytest

from test_helpers import (
    api_client, TEST_USERS,
    validate_success, validate_error,
    ApiErrorId, MODEL_STRAIGHT,
    set_clock, create_catalog_model, setup_approved_assessment,
    create_agreement, get_agreement, skip_funding, fully_fund_agreement,
    setup_active_agreement, setup_active_purchase_past_cooling_off,
    create_install_job_payload, create_removal_job_payload, fresh_crew,
)

COORD = TEST_USERS["install_coordinator_headers"]


def _setup_bookable_agreement():
    """Agreement past the funding gate (waiver-signed skip-funding), ready to
    book an install job. Returns the create_agreement bag."""
    set_clock("2026-06-01T00:00:00Z")
    create_catalog_model()
    base = setup_approved_assessment()
    bag = create_agreement(base["customer"]["id"], base["assessment"]["id"],
                           liability_waiver_signed=True)
    skip_funding(bag["agreement"]["id"])
    return bag


# ---------------------------------------------------------------------------
# Install start temporal gate
# ---------------------------------------------------------------------------

def test_install_job_start_before_scheduled_time_rejected(api):
    """PRD §3.5: "On the day, the coordinator starts the job — permitted only
    once the logical clock has reached `scheduled_start_utc`, otherwise
    `ERR_TOO_EARLY` (409) — moving it to `IN_PROGRESS`."

    Design: Corner/state_machines/install_job_start_before_scheduled_time_rejected
    """
    bag = _setup_bookable_agreement()
    job = validate_success(
        api.create_install_job(
            bag["agreement"]["id"],
            create_install_job_payload("CREW-E",
                                       scheduled_start_utc="2026-06-10T09:00:00Z",
                                       scheduled_end_utc="2026-06-10T13:00:00Z"),
            COORD), 201)
    # Logical clock is still 2026-06-01, nine days before the scheduled start.
    res = api.start_install_job(job["id"], COORD)
    validate_error(res, ApiErrorId.ERR_TOO_EARLY)


# ---------------------------------------------------------------------------
# Install buffer: half-open intervals extended 60 minutes on both sides
# ---------------------------------------------------------------------------

def test_install_buffer_overlap_rejected_when_gap_below_60_minutes(api):
    """PRD §2.7: "For **install jobs**, bookings on the same
    `technician_crew_id` must respect a 60-minute buffer: each booking is
    treated as a half-open interval from its `scheduled_start_utc` (inclusive)
    to its `scheduled_end_utc` (exclusive), extended by 60 minutes on both
    sides, and a proposed install whose extended interval overlaps the extended
    interval of any existing same-crew install job in `SCHEDULED` or
    `IN_PROGRESS` is rejected with `ERR_CREW_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/install_buffer_interval_semantics
    """
    crew = fresh_crew("CREW-BUF")
    bag1 = _setup_bookable_agreement()
    validate_success(
        api.create_install_job(
            bag1["agreement"]["id"],
            create_install_job_payload(crew,
                                       scheduled_start_utc="2026-06-10T09:00:00Z",
                                       scheduled_end_utc="2026-06-10T13:00:00Z"),
            COORD), 201)

    bag2 = _setup_bookable_agreement()
    # 13:30 start leaves only a 30-minute gap after the first job; the extended
    # intervals ([08:00,14:00) and [12:30,16:30)) overlap.
    res = api.create_install_job(
        bag2["agreement"]["id"],
        create_install_job_payload(crew,
                                   scheduled_start_utc="2026-06-10T13:30:00Z",
                                   scheduled_end_utc="2026-06-10T15:30:00Z"),
        COORD)
    validate_error(res, ApiErrorId.ERR_CREW_OVERLAP)


def test_install_buffer_exactly_adjacent_jobs_allowed(api):
    """PRD §2.7: "Two jobs where one's end is exactly the other's start count
    as adjacent, not overlapping — the buffer applies only when they are not
    exactly adjacent."

    Design: Difficulty/resource_temporal_overlap/install_buffer_interval_semantics
    """
    crew = fresh_crew("CREW-ADJ")
    bag1 = _setup_bookable_agreement()
    validate_success(
        api.create_install_job(
            bag1["agreement"]["id"],
            create_install_job_payload(crew,
                                       scheduled_start_utc="2026-06-10T09:00:00Z",
                                       scheduled_end_utc="2026-06-10T13:00:00Z"),
            COORD), 201)

    bag2 = _setup_bookable_agreement()
    # Second job starts exactly when the first ends: adjacency exception.
    job2 = validate_success(
        api.create_install_job(
            bag2["agreement"]["id"],
            create_install_job_payload(crew,
                                       scheduled_start_utc="2026-06-10T13:00:00Z",
                                       scheduled_end_utc="2026-06-10T15:00:00Z"),
            COORD), 201)
    assert job2["status"] == "SCHEDULED"


# ---------------------------------------------------------------------------
# Removal daily capacity: at most 2 per crew per UTC calendar day
# ---------------------------------------------------------------------------

def test_removal_daily_capacity_third_same_day_rejected(api):
    """PRD §2.7: "For **removal jobs**, the rule is daily capacity rather than
    a buffer: a crew may perform at most 2 removals per UTC calendar day,
    counted among removal jobs in `SCHEDULED` on the calendar date of the
    proposed `scheduled_start_utc`; a third same-day booking on that crew is
    rejected with `ERR_CREW_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/removal_daily_capacity_semantics
    """
    crew = fresh_crew("CREW-CAP")
    bag_a = setup_active_purchase_past_cooling_off(timeline_offset_days=0)
    bag_b = setup_active_purchase_past_cooling_off(timeline_offset_days=45)
    bag_c = setup_active_purchase_past_cooling_off(timeline_offset_days=90)

    # Two non-overlapping removals on the same UTC day both fit the capacity.
    validate_success(
        api.create_removal_job(
            bag_a["agreement"]["id"],
            create_removal_job_payload(crew,
                                       scheduled_start_utc="2026-08-01T08:00:00Z",
                                       scheduled_end_utc="2026-08-01T10:00:00Z"),
            COORD), 201)
    validate_success(
        api.create_removal_job(
            bag_b["agreement"]["id"],
            create_removal_job_payload(crew,
                                       scheduled_start_utc="2026-08-01T22:00:00Z",
                                       scheduled_end_utc="2026-08-01T23:00:00Z"),
            COORD), 201)

    res = api.create_removal_job(
        bag_c["agreement"]["id"],
        create_removal_job_payload(crew,
                                   scheduled_start_utc="2026-08-01T14:00:00Z",
                                   scheduled_end_utc="2026-08-01T16:00:00Z"),
        COORD)
    validate_error(res, ApiErrorId.ERR_CREW_OVERLAP)


def test_removal_daily_capacity_resets_on_next_utc_day(api):
    """PRD §2.7: "For **removal jobs**, the rule is daily capacity rather than
    a buffer: a crew may perform at most 2 removals per UTC calendar day,
    counted among removal jobs in `SCHEDULED` on the calendar date of the
    proposed `scheduled_start_utc`; a third same-day booking on that crew is
    rejected with `ERR_CREW_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/removal_daily_capacity_semantics
    """
    crew = fresh_crew("CREW-CAP2")
    bag_a = setup_active_purchase_past_cooling_off(timeline_offset_days=0)
    bag_b = setup_active_purchase_past_cooling_off(timeline_offset_days=45)
    bag_c = setup_active_purchase_past_cooling_off(timeline_offset_days=90)

    validate_success(
        api.create_removal_job(
            bag_a["agreement"]["id"],
            create_removal_job_payload(crew,
                                       scheduled_start_utc="2026-08-01T08:00:00Z",
                                       scheduled_end_utc="2026-08-01T10:00:00Z"),
            COORD), 201)
    validate_success(
        api.create_removal_job(
            bag_b["agreement"]["id"],
            create_removal_job_payload(crew,
                                       scheduled_start_utc="2026-08-01T22:00:00Z",
                                       scheduled_end_utc="2026-08-01T23:00:00Z"),
            COORD), 201)

    # Same crew, next UTC calendar day: capacity count resets.
    job3 = validate_success(
        api.create_removal_job(
            bag_c["agreement"]["id"],
            create_removal_job_payload(crew,
                                       scheduled_start_utc="2026-08-02T09:00:00Z",
                                       scheduled_end_utc="2026-08-02T11:00:00Z"),
            COORD), 201)
    assert job3["status"] == "SCHEDULED"
