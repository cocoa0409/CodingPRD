"""Two claims on the same stretch of time, and the exact instant they stop clashing.

A panel's minutes and a state's submission window are both scarce resources whose
overlap tests the contract states with explicit inclusivity.
"""

from test_helpers import (
    CYCLE_STATUS_SCHEDULED,
    REVIEW_STATUS_FILED,
    REVIEW_STATUS_SCHEDULED,
    SLOT_STATUS_RESERVED,
    ApiErrorId,
    factories,
    fixtures,
    get_success_data,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_a_five_minute_gap_falls_inside_the_mandatory_turnover(api):
    """A window starting five minutes after the last one ends clashes on the buffer.

    PRD 3.8: "The **buffered closed-interval rule** then compares the new window
    against every existing slot of the panel whose `status` is `RESERVED`,
    `PRESENTED`, `TALLIED` or `NO_SHOW`: the new slot is acceptable only if, for
    each such existing slot, the new `start_at` is at or after that slot's `end_at`
    advanced by `buffer_minutes`, **or** the new `end_at` advanced by
    `buffer_minutes` is at or before that slot's `start_at`."

    Design: Difficulty/resource_temporal_overlap/panel_slot_buffered_closed_interval_conflict
    """
    world = fixtures.seed_filed_submission(api, "SC")
    companion = fixtures.seed_companion_filed_submission(api, world, "9780000001501")
    second_submission = companion["submission_id"]
    panel_id = fixtures.seed_panel(api, world)
    fixtures.reserve_slot(
        api,
        world,
        start_at="2026-10-20T14:00:00Z",
        end_at="2026-10-20T14:30:00Z",
    )

    version = api.read_panel_version(panel_id, world.officer)
    validate_error(
        api.reserve_slot(
            panel_id,
            factories.slot_payload(
                second_submission,
                version,
                start_at="2026-10-20T14:35:00Z",
                end_at="2026-10-20T15:05:00Z",
            ),
            world.officer,
        ),
        ApiErrorId.ERR_SLOT_BUFFER_CONFLICT,
        409,
    )

    panel = validate_success(api.get_committee_panel(panel_id, world.officer))
    assert panel["reserved_minutes"] == 30

    submission = validate_success(api.get_submission(second_submission, fixtures.EDITOR))
    assert submission["review_status"] == REVIEW_STATUS_FILED


def test_a_ten_minute_gap_clears_the_turnover_exactly(api):
    """Starting at the buffered boundary instant is accepted and books the minutes.

    PRD 3.8: "An accepted reservation adds the slot's `duration_minutes` to the
    panel's `reserved_minutes` and increments the panel's `version` by 1, and moves
    the submission's `review_status` from `FILED` to `SCHEDULED` while incrementing
    the cycle's `scheduled_submission_count` by 1."

    Design: Difficulty/resource_temporal_overlap/panel_slot_buffered_closed_interval_conflict
    """
    world = fixtures.seed_filed_submission(api, "SC")
    companion = fixtures.seed_companion_filed_submission(api, world, "9780000001501")
    second_submission = companion["submission_id"]
    panel_id = fixtures.seed_panel(api, world)
    fixtures.reserve_slot(
        api,
        world,
        start_at="2026-10-20T14:00:00Z",
        end_at="2026-10-20T14:30:00Z",
    )

    version = api.read_panel_version(panel_id, world.officer)
    slot = validate_success(
        api.reserve_slot(
            panel_id,
            factories.slot_payload(
                second_submission,
                version,
                start_at="2026-10-20T14:40:00Z",
                end_at="2026-10-20T15:10:00Z",
            ),
            world.officer,
        ),
        201,
    )
    assert slot["status"] == SLOT_STATUS_RESERVED
    assert slot["duration_minutes"] == 30

    panel = validate_success(api.get_committee_panel(panel_id, world.officer))
    assert panel["reserved_minutes"] == 60

    submission = validate_success(api.get_submission(second_submission, fixtures.EDITOR))
    assert submission["review_status"] == REVIEW_STATUS_SCHEDULED

    cycle = validate_success(api.get_adoption_cycle(world.cycle_id, world.officer))
    assert cycle["scheduled_submission_count"] == 2


def test_a_window_opening_exactly_when_the_last_one_closes_is_accepted(api):
    """The window excludes its closing instant, so touching endpoints do not clash.

    PRD 3.1: "Two windows that merely touch at an endpoint — one closing exactly
    when the next opens — do not intersect and are accepted."

    Design: Difficulty/resource_temporal_overlap/cycle_submission_window_half_open_overlap
    """
    world = fixtures.seed_state(api, "VA")
    fixtures.seed_cycle(api, world)

    touching = validate_success(
        api.create_adoption_cycle(
            factories.adoption_cycle_payload(
                world.state_id,
                subject="MATH",
                cycle_year=2028,
                submission_open_at="2026-10-01T00:00:00Z",
                submission_deadline_at="2026-11-01T00:00:00Z",
                committee_review_at="2026-11-15T00:00:00Z",
                public_comment_start_at="2026-12-01T00:00:00Z",
                public_comment_end_at="2026-12-15T00:00:00Z",
                adoption_decision_at="2027-01-01T00:00:00Z",
            ),
            world.officer,
        ),
        201,
    )
    assert touching["status"] == CYCLE_STATUS_SCHEDULED
    assert touching["phase_epoch"] == 0
    assert touching["submission_open_at"].startswith("2026-10-01T00:00:00")


def test_a_window_reaching_one_day_back_into_the_first_one_is_refused(api):
    """Opening a day before the earlier window closes is a genuine intersection.

    PRD 3.1: "A new cycle is refused with `ERR_CYCLE_WINDOW_OVERLAP` when its window
    intersects the window of any existing cycle sharing the same state and the same
    `subject`."

    Design: Difficulty/resource_temporal_overlap/cycle_submission_window_half_open_overlap
    """
    world = fixtures.seed_state(api, "VA")
    first_cycle = fixtures.seed_cycle(api, world)
    get_success_data(
        api.create_adoption_cycle(
            factories.adoption_cycle_payload(
                world.state_id,
                subject="MATH",
                cycle_year=2028,
                submission_open_at="2026-10-01T00:00:00Z",
                submission_deadline_at="2026-11-01T00:00:00Z",
                committee_review_at="2026-11-15T00:00:00Z",
                public_comment_start_at="2026-12-01T00:00:00Z",
                public_comment_end_at="2026-12-15T00:00:00Z",
                adoption_decision_at="2027-01-01T00:00:00Z",
            ),
            world.officer,
        )
    )

    validate_error(
        api.create_adoption_cycle(
            factories.adoption_cycle_payload(
                world.state_id,
                subject="MATH",
                cycle_year=2029,
                submission_open_at="2026-09-30T00:00:00Z",
                submission_deadline_at="2026-10-05T00:00:00Z",
                committee_review_at="2026-11-15T00:00:00Z",
                public_comment_start_at="2026-12-01T00:00:00Z",
                public_comment_end_at="2026-12-15T00:00:00Z",
                adoption_decision_at="2027-01-01T00:00:00Z",
            ),
            world.officer,
        ),
        ApiErrorId.ERR_CYCLE_WINDOW_OVERLAP,
        409,
    )

    untouched = validate_success(api.get_adoption_cycle(first_cycle, world.officer))
    assert untouched["submission_deadline_at"].startswith("2026-10-01T00:00:00")

    cycles, meta = validate_paginated(
        api.list_adoption_cycles(
            world.officer, params={"state_id": world.state_id, "subject": "MATH"}
        )
    )
    assert meta["total_count"] == 2
    assert {cycle["cycle_year"] for cycle in cycles} == {2027, 2028}
