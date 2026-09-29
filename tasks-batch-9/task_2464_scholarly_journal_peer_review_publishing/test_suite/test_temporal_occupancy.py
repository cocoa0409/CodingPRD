"""Occupancy in time: half-open reviewer windows and the closed typesetting interval."""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import ApiErrorId
from test_helpers import assertions as a
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers import PRODUCTION_STAFF_HEADERS, api_client


def _invitation_request(manuscript_id, reviewer_id, handling_headers):
    payload = f.review_invitation_payload(manuscript_id)
    payload["reviewer_id"] = reviewer_id
    return api_client.create_review_invitation(payload, handling_headers)


def _slot_request(job_id, slot_start, slot_end):
    version = fx.get_production_job(job_id)["version"]
    return api_client.book_typeset_slot(
        job_id,
        f.typeset_slot_payload(slot_start, slot_end, version),
        PRODUCTION_STAFF_HEADERS,
    )


def test_overlapping_window_exhausts_the_reviewers_aggregate_capacity():
    """One open window already fills a journal that allows one.

    PRD: "If that count is at least the journal's `reviewer_concurrent_window_limit`, the invitation is refused with `ERR_REVIEWER_WINDOW_CAPACITY`."

    Design: Difficulty/resource_temporal_overlap/reviewer_half_open_window_aggregate_capacity_and_adjacency
    """
    world = fx.setup_reviewer_window_pair()
    a.assert_fields(
        world["invitation"],
        invited_at="2026-08-01T00:00:00.000Z",
        due_at="2026-08-22T00:00:00.000Z",
        state="INVITED",
    )

    response = _invitation_request(
        world["m2"]["id"], world["reviewer"]["id"], world["handling_headers"]
    )

    validate_error(
        response, ApiErrorId.ERR_REVIEWER_WINDOW_CAPACITY.value, expected_status=409
    )


def test_window_starting_exactly_at_the_open_deadline_does_not_overlap():
    """Touching intervals are not overlapping intervals, so the invitation is allowed.

    PRD: "Two intervals overlap when the first starts strictly before the second ends and the second starts strictly before the first ends — strict on both sides, so two windows that merely touch, where one's start equals the other's end, do **not** overlap."

    Design: Difficulty/resource_temporal_overlap/reviewer_half_open_window_aggregate_capacity_and_adjacency
    """
    world = fx.setup_reviewer_window_pair()
    _invitation_request(
        world["m2"]["id"], world["reviewer"]["id"], world["handling_headers"]
    )

    fx.set_clock("2026-08-22T00:00:00Z")
    second = validate_success(
        _invitation_request(
            world["m2"]["id"], world["reviewer"]["id"], world["handling_headers"]
        ),
        expected_status=201,
    )

    a.assert_fields(
        second,
        invited_at="2026-08-22T00:00:00.000Z",
        due_at="2026-09-12T00:00:00.000Z",
        state="INVITED",
    )


def test_capacity_caps_overlapping_windows_and_not_the_total_open_load():
    """The reviewer now holds two open invitations on a limit of one.

    PRD: "Reviewer capacity is enforced as an **aggregate**, not as exclusivity."

    Design: Difficulty/resource_temporal_overlap/reviewer_half_open_window_aggregate_capacity_and_adjacency
    """
    world = fx.setup_reviewer_window_pair()
    fx.set_clock("2026-08-22T00:00:00Z")
    validate_success(
        _invitation_request(
            world["m2"]["id"], world["reviewer"]["id"], world["handling_headers"]
        ),
        expected_status=201,
    )

    reviewer = fx.get_reviewer(world["reviewer"]["id"])
    a.assert_fields(reviewer, open_invitation_count=2, invited_count=2)


def test_slot_starting_inside_the_changeover_buffer_conflicts():
    """A start two days after the existing end is still inside the buffer.

    PRD: "Two closed intervals conflict when the journal's `typeset_changeover_buffer_days` buffer, applied symmetrically to both, brings them into contact: the proposed slot's start falls on or before the existing slot's end plus the buffer, **and** the existing slot's start falls on or before the proposed slot's end plus the buffer."

    Design: Difficulty/resource_temporal_overlap/typeset_slot_closed_interval_buffer_exclusivity
    """
    world = fx.setup_two_production_jobs()

    response = _slot_request(world["job_two"]["id"], "2026-09-07", "2026-09-09")

    validate_error(
        response, ApiErrorId.ERR_TYPESET_SLOT_CONFLICT.value, expected_status=409
    )
    assert fx.get_production_job(world["job_two"]["id"]).get("slot_start") is None


def test_earliest_legal_start_is_the_existing_end_plus_three_days():
    """One day later than the refused start is accepted.

    PRD: "Concretely, with a two-day buffer, the earliest legal start after an existing slot is the day after the existing end plus the buffer — that is, the existing end plus three days."

    Design: Difficulty/resource_temporal_overlap/typeset_slot_closed_interval_buffer_exclusivity
    """
    world = fx.setup_two_production_jobs()

    booked = validate_success(
        _slot_request(world["job_two"]["id"], "2026-09-08", "2026-09-10")
    )

    a.assert_fields(booked, slot_start="2026-09-08", slot_end="2026-09-10")


def test_refused_booking_leaves_both_jobs_exactly_as_they_were():
    """The conflicting request writes nothing on either side of the comparison.

    PRD: "Any single conflicting job is fatal, and the booking is refused with `ERR_TYPESET_SLOT_CONFLICT`."

    Design: Difficulty/resource_temporal_overlap/typeset_slot_closed_interval_buffer_exclusivity
    """
    world = fx.setup_two_production_jobs()

    _slot_request(world["job_two"]["id"], "2026-09-07", "2026-09-09")

    job_one = fx.get_production_job(world["job_one"]["id"])
    a.assert_fields(job_one, slot_start="2026-09-01", slot_end="2026-09-05")
    job_two = fx.get_production_job(world["job_two"]["id"])
    assert job_two["content_stage"] == "COPYEDITING"
