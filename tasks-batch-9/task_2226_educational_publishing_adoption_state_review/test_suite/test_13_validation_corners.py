"""Corner cases of the gates that stand between a draft and a hearing.

Filing is guarded by nine simultaneous conditions and a slot reservation by four
scheduling rules, and when several of them could reject one request the contract
fixes which one answers. Each test here arranges exactly one refusal, then reads
the record back to prove the refused write left nothing behind.
"""

from datetime import datetime

import pytest

from test_helpers import (
    ApiErrorId,
    REVIEW_STATUS_DRAFT,
    REVIEW_STATUS_FILED,
    SAMPLING_STATUS_PARTIAL,
    SAMPLING_STATUS_SHIPPED,
    assert_decimal_equals,
    factories as f,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.fixtures import (
    ADMIN,
    CLOCK_INSIDE_SUBMISSION_WINDOW,
    EDITOR,
    file_submission,
    seed_draft_submission,
    seed_open_cycle,
    seed_panel,
    seed_title,
    reserve_slot,
    ship_sampling_copies_to,
)


def _instant(value: str) -> datetime:
    """Read an ISO 8601 UTC timestamp as a comparable instant."""
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def test_partial_sampling_blocks_filing_until_the_last_copies_ship(api):
    """PRD 3.5: "And `sampling_status` must be either `NOT_REQUIRED` or
    `SHIPPED`, else `ERR_SAMPLING_INCOMPLETE`; a `PARTIAL` shipment record is not
    enough." "A successful filing moves `review_status` from `DRAFT` to `FILED`
    and performs the **content pin**: `pinned_content_revision` is set to the
    edition's current `content_revision` and `content_pin_stale` is set to false,
    capturing exactly which revision of the edition the state is being asked to
    review." "`filed_at` records the logical clock instant of the filing." PRD
    3.4: "After each shipment, `sampling_status` is recomputed against the state's
    `sampling_copies_required`: it is `NOT_REQUIRED` when the state requires zero
    copies; otherwise it is `SHIPPED` once `sample_copies_shipped` has reached the
    required number or gone beyond it, `PARTIAL` when at least one copy has
    shipped but the requirement is not yet met, and `PENDING` when nothing has
    shipped." "Each accepted shipment adds its `units` to the submission's
    cumulative `sample_copies_shipped`, and simultaneously draws the copies out of
    the warehouse: the edition's `on_hand_units` decreases by `units` and its
    `sample_reserved_units` increases by the same `units`."

    Utah asks for thirty sample copies. The identical filing request is refused
    while only ten have shipped and accepted once twenty more have followed, so
    the gate turns on the sampling requirement alone.

    Design: Corner/validations/sampling_requirement_gates_filing_only_when_state_requires_copies
    """
    world = seed_open_cycle(
        api,
        "UT",
        subject="ELA",
        grade=4,
        state_overrides={
            "sampling_copies_required": 30,
            "min_verified_coverage_pct": 50.00,
        },
        title_overrides={
            "content_tags": ["CLOSE_READING"],
            "page_count": 300,
            "list_price_cents": 8800,
        },
        receipt_units=100,
    )
    seed_draft_submission(api, world)
    ship_sampling_copies_to(api, world, 10)

    partial = validate_success(api.get_submission(world.submission_id, EDITOR))
    assert partial["sampling_status"] == SAMPLING_STATUS_PARTIAL

    refused = api.file_submission(world.submission_id, EDITOR)
    validate_error(refused, ApiErrorId.ERR_SAMPLING_INCOMPLETE, expected_status=422)

    unchanged = validate_success(api.get_submission(world.submission_id, EDITOR))
    assert unchanged["review_status"] == REVIEW_STATUS_DRAFT

    ship_sampling_copies_to(api, world, 20)
    ready = validate_success(api.get_submission(world.submission_id, EDITOR))
    assert ready["sampling_status"] == SAMPLING_STATUS_SHIPPED

    filed = validate_success(api.file_submission(world.submission_id, EDITOR))
    assert filed["review_status"] == REVIEW_STATUS_FILED
    assert _instant(filed["filed_at"]) == _instant(CLOCK_INSIDE_SUBMISSION_WINDOW)
    assert filed["content_pin_stale"] is False

    title = validate_success(api.get_title(world.title_id, EDITOR))
    assert title["on_hand_units"] == 70


def test_three_individually_legal_slots_exceed_the_declared_minute_cap(api):
    """PRD 3.8: "Finally, the panel's minute budget must accommodate the slot: the
    panel's current `reserved_minutes` plus the new slot's `duration_minutes` must
    be at most `slot_minutes_capacity`, else `ERR_PANEL_CAPACITY_EXCEEDED` — and
    because `slot_minutes_capacity` may sit well below the wall-clock session
    length, a window that comfortably fits inside the session can still be refused
    on budget." "The panel also carries a `slot_minutes_capacity`: a policy cap,
    in whole minutes, on the total presentation time the panel will seat."
    "Panels are born `SCHEDULED` with `reserved_minutes` at 0." "An accepted
    reservation adds the slot's `duration_minutes` to the panel's
    `reserved_minutes` and increments the panel's `version` by 1, and moves the
    submission's `review_status` from `FILED` to `SCHEDULED` while incrementing the
    cycle's `scheduled_submission_count` by 1." PRD 3.1:
    "`scheduled_submission_count` is the number whose `review_status` is exactly
    `SCHEDULED`."

    The Nevada panel sits for four hours but will only seat sixty minutes of
    presentation. Two half-hour hearings spend that budget exactly; a third
    half-hour window that sits inside the session and clears the turnover buffer
    against both neighbours is still refused, and the refusal leaves the panel's
    reserved minutes and the third publisher's status untouched.

    Design: Corner/validations/three_legal_slots_collectively_exceed_declared_minute_cap
    """
    world = seed_open_cycle(
        api,
        "NV",
        subject="MATH",
        grade=1,
        title_overrides={
            "content_tags": ["NUMBER_SENSE"],
            "page_count": 240,
            "list_price_cents": 8100,
        },
    )
    title_ids = [world.title_id]
    for page_count, list_price in ((250, 8200), (260, 8300)):
        title_ids.append(
            seed_title(
                api,
                world,
                subject="MATH",
                grade_low=1,
                grade_high=1,
                page_count=page_count,
                list_price_cents=list_price,
            )
        )

    submission_ids = [
        seed_draft_submission(api, world, title_id=title_id) for title_id in title_ids
    ]
    for submission_id in submission_ids:
        file_submission(api, world, submission_id=submission_id)

    seed_panel(
        api,
        world,
        panel_label="NV MATH Panel A",
        buffer_minutes=10,
        slot_minutes_capacity=60,
        member_count=3,
        quorum_required=2,
    )
    reserve_slot(
        api,
        world,
        submission_id=submission_ids[0],
        start_at="2026-10-20T14:00:00Z",
        end_at="2026-10-20T14:30:00Z",
    )
    reserve_slot(
        api,
        world,
        submission_id=submission_ids[1],
        start_at="2026-10-20T14:40:00Z",
        end_at="2026-10-20T15:10:00Z",
    )

    spent = validate_success(api.get_committee_panel(world.panel_id, world.officer))
    assert spent["reserved_minutes"] == 60
    assert spent["slot_minutes_capacity"] == 60

    # 15:20 is exactly one buffer past the 15:10 end of the second hearing and
    # 15:50 is well inside the 18:00 close of the session, so only the budget
    # can refuse this window.
    refused = api.reserve_slot(
        world.panel_id,
        f.slot_payload(
            submission_ids[2],
            spent["version"],
            start_at="2026-10-20T15:20:00Z",
            end_at="2026-10-20T15:50:00Z",
        ),
        world.officer,
    )
    validate_error(refused, ApiErrorId.ERR_PANEL_CAPACITY_EXCEEDED, expected_status=409)

    after = validate_success(api.get_committee_panel(world.panel_id, world.officer))
    assert after["reserved_minutes"] == 60

    third = validate_success(api.get_submission(submission_ids[2], EDITOR))
    assert third["review_status"] == REVIEW_STATUS_FILED

    cycle = validate_success(api.get_adoption_cycle(world.cycle_id, world.officer))
    assert cycle["scheduled_submission_count"] == 2

    slots, meta = validate_paginated(
        api.list_presentation_slots(world.officer, {"panel_id": world.panel_id})
    )
    assert meta["total_count"] == 2
    assert len(slots) == 2


def test_empty_correlation_set_answers_before_the_coverage_floor_does(api):
    """PRD 2.6: "More broadly, when several checks could reject one request, they
    are evaluated in a fixed order and the **first** failing check supplies the
    response." "51. The submission has at least one correlation entry, else
    `ERR_CORRELATION_SET_EMPTY` (422), on filing." "53. Self-reported coverage
    reaches the state's minimum, else `ERR_COVERAGE_BELOW_MINIMUM` (422), on
    filing." PRD 3.5: "At least one correlation entry must exist, else
    `ERR_CORRELATION_SET_EMPTY`." "The submission's `self_reported_coverage_pct`
    must be at least the state's `min_verified_coverage_pct`, else
    `ERR_COVERAGE_BELOW_MINIMUM`." PRD 3.1: "`min_verified_coverage_pct` is the
    minimum correlation coverage percentage; it defaults to 85.00, must lie
    between 0.00 and 100.00, and is carried at two decimals." PRD 3.4: "If there
    are no candidates, the standard contributes nothing." "The coverage percentage
    is then 100 multiplied by the numerator, divided by the denominator, rounded
    half up to 2 decimal places, and finally capped at 100.00."

    West Virginia keeps the default coverage floor of 85.00 and the draft carries
    no correlation evidence at all, so both the emptiness rule and the coverage
    rule are violated by the same filing. The emptier rule is the earlier one and
    it is the one that answers.

    Design: Corner/validations/empty_correlation_set_is_caught_before_the_coverage_computation
    """
    world = seed_open_cycle(
        api,
        "WV",
        subject="SCIENCE",
        grade=6,
        state_overrides={"min_verified_coverage_pct": None},
        title_overrides={
            "content_tags": ["LAB_SAFETY"],
            "page_count": 330,
            "list_price_cents": 9400,
        },
    )
    state = validate_success(api.get_state_profile(world.state_id, ADMIN))
    assert_decimal_equals(
        state["min_verified_coverage_pct"], "85.00", "min_verified_coverage_pct"
    )

    submission_id = seed_draft_submission(api, world, depth_levels=())
    empty = validate_success(api.get_submission(submission_id, EDITOR))
    assert_decimal_equals(
        empty["self_reported_coverage_pct"], "0.00", "self_reported_coverage_pct"
    )

    # The coverage floor is violated too, but the emptiness rule is checked first
    # and validate_error pins the exact identifier the server must return.
    refused = api.file_submission(submission_id, EDITOR)
    validate_error(refused, ApiErrorId.ERR_CORRELATION_SET_EMPTY, expected_status=422)

    unchanged = validate_success(api.get_submission(submission_id, EDITOR))
    assert unchanged["review_status"] == REVIEW_STATUS_DRAFT

    cycle = validate_success(api.get_adoption_cycle(world.cycle_id, world.officer))
    assert cycle["submission_count"] == 0
