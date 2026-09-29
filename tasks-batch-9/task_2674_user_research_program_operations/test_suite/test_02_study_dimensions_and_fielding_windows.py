"""The study's two independent state dimensions, and the closed-interval overlap
test that meters a pool's concurrent-fielding capacity."""

import pytest

from test_helpers import (
    RESEARCHER_HEADERS,
    approve_guide,
    complete_session,
    create_study,
    close_fielding,
    field_study,
    grant_consent,
    invite,
    read_recruitment,
    read_study,
    schedule,
    screen,
    setup_approved_request,
    setup_fielding_study,
    setup_two_fielding_studies_sharing_pool,
    validate_error,
    validate_paginated,
    validate_success,
    write_guide,
)

SESSION_START = "2026-08-05T14:00:00Z"
SESSION_END = "2026-08-05T15:00:00Z"


def _fielded_study_with_one_seat(api):
    """An INTERVIEW study in the field whose completed-session goal is a single
    participant, plus that participant's consent already on file."""
    ctx = setup_fielding_study(
        api,
        participant_count=1,
        target_participant_count=1,
        fielding_start="2026-08-03T00:00:00Z",
        fielding_end="2026-08-21T00:00:00Z",
    )
    grant_consent(
        ctx["participants"][0]["id"],
        ctx["study"]["id"],
        api,
        scopes=["RECORDING"],
        retention_days=60,
    )
    return ctx


def _scheduled_single_session(api):
    """The same study with its one seat invited, screened in and booked."""
    ctx = _fielded_study_with_one_seat(api)
    recruitment = invite(ctx["study"]["id"], ctx["participants"][0]["id"], api)
    screen(recruitment["id"], api)
    schedule(recruitment["id"], SESSION_START, SESSION_END, api)
    ctx["recruitment"] = read_recruitment(recruitment["id"], api)
    ctx["study"] = read_study(ctx["study"]["id"], api)
    return ctx


def test_fielding_leaves_the_recruitment_axis_untouched_until_the_first_invitation(api):
    """The execution axis reaches FIELDING on its own; the recruitment axis only
    starts moving when a recruitment row actually exists.

    PRD 3.3: "Fielding does not touch `recruitment_status`, which stays at
    `NOT_STARTED` until the study's first invitation is actually created."

    PRD 3.4: "When the study had no recruitments at all before this call, this is
    also the moment `recruitment_status` moves `NOT_STARTED → RECRUITING`."

    Design: Difficulty/non_linear_state_machine/study_execution_and_recruitment_dimensions_advance_independently
    """
    ctx = _fielded_study_with_one_seat(api)
    fielded = read_study(ctx["study"]["id"], api)
    assert fielded["execution_status"] == "FIELDING", (
        f"Expected the execution axis to read FIELDING after the field call, got "
        f"{fielded['execution_status']}"
    )
    assert fielded["recruitment_status"] == "NOT_STARTED", (
        f"Expected fielding to leave the recruitment axis at NOT_STARTED, got "
        f"{fielded['recruitment_status']}"
    )
    assert fielded["fielded_at"] is not None, (
        "Expected fielded_at to be stamped by the field call, got null"
    )

    invite(ctx["study"]["id"], ctx["participants"][0]["id"], api)
    after_invite = read_study(ctx["study"]["id"], api)
    assert after_invite["recruitment_status"] == "RECRUITING", (
        f"Expected the study's first invitation to move the recruitment axis to "
        f"RECRUITING, got {after_invite['recruitment_status']}"
    )
    assert after_invite["execution_status"] == "FIELDING", (
        f"Expected the execution axis to stay at FIELDING while the recruitment "
        f"axis moved, got {after_invite['execution_status']}"
    )
    assert after_invite["invited_count"] == 1, (
        f"Expected invited_count 1 after the first invitation, got "
        f"{after_invite['invited_count']}"
    )


def test_completing_the_last_session_leaves_the_execution_axis_in_fielding(api):
    """Filling the study's only seat drives the recruitment axis to QUOTA_MET
    without moving the execution axis off FIELDING.

    PRD 3.5: "The study's `completed_count` is recomputed as the number of its
    recruitments standing in `COMPLETED`, and its `recruitment_status`
    re-derived: once the number of the study's recruitments sitting in
    `SCHEDULED` or `COMPLETED` reaches `target_participant_count`, the study
    moves `RECRUITING → QUOTA_MET` and further invitations are refused with
    `ERR_RECRUITMENT_CLOSED`."

    PRD 3.3: "Closing fielding carries `execution_status` `FIELDING → ANALYSIS`,
    and it is refused with `ERR_INVALID_STATE` while any recruitment of the study
    is still sitting in `SCHEDULED` — every booked session must be resolved as
    completed, a no-show or a withdrawal before analysis begins."

    Design: Difficulty/non_linear_state_machine/study_execution_and_recruitment_dimensions_advance_independently
    """
    ctx = _scheduled_single_session(api)
    complete_session(ctx["recruitment"]["id"], api, actual_duration_min=50)

    study = read_study(ctx["study"]["id"], api)
    assert study["completed_count"] == 1, (
        f"Expected completed_count 1 after the only session completed, got "
        f"{study['completed_count']}"
    )
    assert study["recruitment_status"] == "QUOTA_MET", (
        f"Expected the recruitment axis to read QUOTA_MET once the single seat was "
        f"filled, got {study['recruitment_status']}"
    )
    assert study["execution_status"] == "FIELDING", (
        f"Expected the execution axis to stay at FIELDING while the recruitment "
        f"axis reached QUOTA_MET, got {study['execution_status']}"
    )
    assert study["fielding_closed_at"] is None, (
        f"Expected fielding_closed_at to stay null until fielding is closed, got "
        f"{study['fielding_closed_at']!r}"
    )


def test_the_recruitment_row_moves_its_workflow_axis_without_its_money_axis(api):
    """A recruitment carries two axes of its own, and completing the session moves
    only the workflow one.

    PRD 3.4: "A successful invitation writes a recruitment in `status` `INVITED`
    with `incentive_state` `RESERVED` and its `reserved_cents` stored, sets
    `screen_score`, `scheduled_start`, `scheduled_end`, `moderator_user_id`,
    `actual_duration_min` and `closure_reason` to null with `reschedule_count` at
    0 and `paid_cents` at 0, and copies the study's `guide_version_pinned` onto
    the recruitment's own `guide_version_pinned` so the session is forever tied to
    the guide version that was in force."

    PRD 3.5: "Completion carries `SCHEDULED → COMPLETED` and records
    `actual_duration_min`, the duration the moderator reports."

    Design: Difficulty/non_linear_state_machine/study_execution_and_recruitment_dimensions_advance_independently
    """
    ctx = _scheduled_single_session(api)
    assert ctx["recruitment"]["incentive_state"] == "RESERVED", (
        f"Expected the invitation to leave incentive_state RESERVED, got "
        f"{ctx['recruitment']['incentive_state']}"
    )

    complete_session(ctx["recruitment"]["id"], api, actual_duration_min=50)
    recruitment = read_recruitment(ctx["recruitment"]["id"], api)
    assert recruitment["status"] == "COMPLETED", (
        f"Expected the workflow axis to read COMPLETED after the session, got "
        f"{recruitment['status']}"
    )
    assert recruitment["incentive_state"] == "RESERVED", (
        f"Expected completion to leave the money axis at RESERVED, got "
        f"{recruitment['incentive_state']}"
    )
    assert recruitment["actual_duration_min"] == 50, (
        f"Expected the reported duration of 50 minutes to be stored, got "
        f"{recruitment['actual_duration_min']}"
    )
    assert recruitment["paid_cents"] == 0, (
        f"Expected paid_cents to stay at 0 before settlement, got "
        f"{recruitment['paid_cents']}"
    )


def test_closing_fielding_advances_only_the_execution_axis(api):
    """Closing fielding is a move on the execution axis alone; the recruitment axis
    stays exactly where the recruitment dimension had already put it.

    PRD 3.3: "Closing fielding carries `execution_status` `FIELDING → ANALYSIS`,
    and it is refused with `ERR_INVALID_STATE` while any recruitment of the study
    is still sitting in `SCHEDULED` — every booked session must be resolved as
    completed, a no-show or a withdrawal before analysis begins."

    PRD 3.3: "On success `fielding_closed_at` is set to the clock instant and two
    doors open: findings of this study may now be locked, and the binding form of
    incentive settlement becomes permitted."

    PRD 3.3: "Any other study leaves `recruitment_status` exactly where the
    recruitment dimension had already put it — `RECRUITING` or `QUOTA_MET`."

    Design: Difficulty/non_linear_state_machine/study_execution_and_recruitment_dimensions_advance_independently
    """
    ctx = _scheduled_single_session(api)
    complete_session(ctx["recruitment"]["id"], api, actual_duration_min=50)
    before = read_study(ctx["study"]["id"], api)

    close_fielding(ctx["study"]["id"], api)
    after = read_study(ctx["study"]["id"], api)

    assert after["execution_status"] == "ANALYSIS", (
        f"Expected close-fielding to carry the execution axis to ANALYSIS, got "
        f"{after['execution_status']}"
    )
    assert after["recruitment_status"] == "QUOTA_MET", (
        f"Expected the recruitment axis to stay at QUOTA_MET across close-fielding, "
        f"got {after['recruitment_status']}"
    )
    assert after["fielding_closed_at"] is not None, (
        "Expected fielding_closed_at to be stamped by close-fielding, got null"
    )
    assert after["fielded_at"] == before["fielded_at"], (
        f"Expected fielded_at to be unchanged by close-fielding, got "
        f"{after['fielded_at']!r} where it had been {before['fielded_at']!r}"
    )
    assert after["completed_count"] == 1, (
        f"Expected completed_count to stay at 1 across close-fielding, got "
        f"{after['completed_count']}"
    )


# Two incumbents already in the field against one pool: 2026-08-03 to 2026-08-21
# and 2026-08-05 to 2026-08-25.
INCUMBENT_WINDOWS = (
    ("2026-08-03T00:00:00Z", "2026-08-21T00:00:00Z"),
    ("2026-08-05T00:00:00Z", "2026-08-25T00:00:00Z"),
)
# Shares exactly one endpoint day, 2026-08-21, with the first incumbent, and
# genuinely overlaps the second.
ENDPOINT_SHARING_WINDOW = ("2026-08-21T00:00:00Z", "2026-08-30T00:00:00Z")
# Starts the day after the later incumbent closes, so it overlaps neither.
CLEAR_WINDOW = ("2026-08-26T00:00:00Z", "2026-08-30T00:00:00Z")

CAPACITY_POOL = {
    "pool_type": "EXTERNAL_PANEL",
    "contact_cap_per_window": 4,
    "contact_window_days": 30,
    "incentive_budget_cents": 200000,
}


def _two_incumbents_in_the_field(api):
    return setup_two_fielding_studies_sharing_pool(
        api,
        windows=INCUMBENT_WINDOWS,
        participant_count=4,
        method="INTERVIEW",
        pool_overrides=dict(CAPACITY_POOL),
    )


def _guide_approved_study_on_pool(api, pool_id, window):
    """A third or fourth study of the same pool, guide approved and ready to field."""
    intake = setup_approved_request(api, method="INTERVIEW")
    study = create_study(
        intake["request"]["id"],
        pool_id,
        api,
        method="INTERVIEW",
        target_participant_count=2,
        fielding_start=window[0],
        fielding_end=window[1],
    )
    write_guide(study["id"], api, guide_version_label="G1", guide_question_count=5)
    return approve_guide(study["id"], api)


def test_a_single_shared_endpoint_day_counts_as_an_overlapping_fielding_window(api):
    """A window that touches an incumbent's last fielding day overlaps it, so the
    pool's third overlapping study is refused.

    PRD 3.3: "And the pool must have concurrent-fielding headroom: at most two
    studies of a single pool may share any instant in the field, so the request is
    refused with `ERR_POOL_FIELDING_CAPACITY` when two or more *other* studies of
    the same `participant_pool_id`, each with `execution_status` `FIELDING`,
    already have a fielding window that overlaps this study's window."

    PRD 3.3: "Overlap here is closed-interval arithmetic on both windows: a single
    shared endpoint day already counts, so a study running to a `fielding_end` of
    the 10th overlaps a study whose `fielding_start` is the 10th."

    Design: Difficulty/resource_temporal_overlap/pool_concurrent_fielding_windows_use_closed_intervals
    """
    ctx = _two_incumbents_in_the_field(api)
    contender = _guide_approved_study_on_pool(
        api, ctx["pool"]["id"], ENDPOINT_SHARING_WINDOW
    )

    validate_error(
        api.field_study(contender["id"], RESEARCHER_HEADERS),
        "ERR_POOL_FIELDING_CAPACITY",
    )

    refused = read_study(contender["id"], api)
    assert refused["execution_status"] == "GUIDE_APPROVED", (
        f"Expected the refused study to stay at GUIDE_APPROVED, got "
        f"{refused['execution_status']}"
    )
    assert refused["fielded_at"] is None, (
        f"Expected the refused study to leave fielded_at unset, got "
        f"{refused['fielded_at']!r}"
    )
    assert refused["guide_status"] == "APPROVED", (
        f"Expected the refused study to keep its APPROVED guide, got "
        f"{refused['guide_status']}"
    )

    for incumbent in ctx["studies"]:
        still = read_study(incumbent["id"], api)
        assert still["execution_status"] == "FIELDING", (
            f"Expected incumbent {incumbent['id']} to remain FIELDING after the "
            f"refusal, got {still['execution_status']}"
        )


def test_a_window_starting_after_both_incumbents_close_fields_without_contention(api):
    """Headroom is measured per overlapping window, so a window that begins the day
    after the later incumbent ends fields normally.

    PRD 3.3: "And the pool must have concurrent-fielding headroom: at most two
    studies of a single pool may share any instant in the field, so the request is
    refused with `ERR_POOL_FIELDING_CAPACITY` when two or more *other* studies of
    the same `participant_pool_id`, each with `execution_status` `FIELDING`,
    already have a fielding window that overlaps this study's window."

    PRD 3.3: "On success `fielded_at` is set to the current logical clock instant
    and the study's recruitment operations open up."

    Design: Difficulty/resource_temporal_overlap/pool_concurrent_fielding_windows_use_closed_intervals
    """
    ctx = _two_incumbents_in_the_field(api)
    contender = _guide_approved_study_on_pool(api, ctx["pool"]["id"], CLEAR_WINDOW)

    fielded = validate_success(api.field_study(contender["id"], RESEARCHER_HEADERS))
    assert fielded["execution_status"] == "FIELDING", (
        f"Expected a non-overlapping window to field, got "
        f"{fielded['execution_status']}"
    )
    assert fielded["fielded_at"] is not None, (
        "Expected fielded_at to be stamped on the successful field call, got null"
    )
    assert fielded["recruitment_status"] == "NOT_STARTED", (
        f"Expected fielding to leave the recruitment axis at NOT_STARTED, got "
        f"{fielded['recruitment_status']}"
    )

    for incumbent in ctx["studies"]:
        still = read_study(incumbent["id"], api)
        assert still["execution_status"] == "FIELDING", (
            f"Expected incumbent {incumbent['id']} to remain FIELDING, got "
            f"{still['execution_status']}"
        )


def test_the_capacity_check_counts_overlapping_windows_not_the_pools_total(api):
    """Three of the pool's studies end up in the field at once; what the cap forbids
    is a third window overlapping the same instant.

    PRD 3.3: "And the pool must have concurrent-fielding headroom: at most two
    studies of a single pool may share any instant in the field, so the request is
    refused with `ERR_POOL_FIELDING_CAPACITY` when two or more *other* studies of
    the same `participant_pool_id`, each with `execution_status` `FIELDING`,
    already have a fielding window that overlaps this study's window."

    PRD 3.3: "Studies can be read individually — the read exposes both state
    dimensions and all three recruitment counters — or listed with optional
    `research_request_id`, `participant_pool_id`, `execution_status` and
    `recruitment_status` filters in `created_at` ascending order."

    Design: Difficulty/resource_temporal_overlap/pool_concurrent_fielding_windows_use_closed_intervals
    """
    ctx = _two_incumbents_in_the_field(api)
    pool_id = ctx["pool"]["id"]
    overlapping = _guide_approved_study_on_pool(api, pool_id, ENDPOINT_SHARING_WINDOW)
    clear = _guide_approved_study_on_pool(api, pool_id, CLEAR_WINDOW)

    validate_error(
        api.field_study(overlapping["id"], RESEARCHER_HEADERS),
        "ERR_POOL_FIELDING_CAPACITY",
    )
    validate_success(api.field_study(clear["id"], RESEARCHER_HEADERS))

    rows, _meta = validate_paginated(
        api.list_studies(RESEARCHER_HEADERS, {"participant_pool_id": pool_id})
    )
    fielding_ids = {
        row["id"] for row in rows if row["execution_status"] == "FIELDING"
    }
    expected_ids = {study["id"] for study in ctx["studies"]} | {clear["id"]}
    assert fielding_ids == expected_ids, (
        f"Expected exactly the two incumbents plus the non-overlapping study to be "
        f"FIELDING, got {sorted(fielding_ids)} against {sorted(expected_ids)}"
    )
    assert overlapping["id"] not in fielding_ids, (
        f"Expected the refused study {overlapping['id']} to be absent from the "
        f"pool's FIELDING studies"
    )
