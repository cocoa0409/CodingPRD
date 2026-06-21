"""Trainer double-booking (buffered) and dog session overlap (strict, no buffer).

Covers the trainer 15-minute buffer rule (§3.3) and the dog strict-overlap rule (§3.10),
both surfaced through ClassSession creation and makeup confirmation.
"""
import pytest

from test_helpers import (
    api_client, validate_success, validate_error, get_success_data,
    TEST_USERS, make_owner_headers,
    create_trainer, create_series_draft, create_session,
    create_class_session_payload, set_clock,
    setup_missed_provider_with_makeup_slot,
)


def test_trainer_double_booked_zero_gap_rejected(api):
    """PRD §3.3: "A gap of exactly 15 minutes is permitted; anything less, including
    back-to-back sessions with zero gap, is rejected."

    Design: Difficulty/resource_temporal_overlap/trainer_double_booked_with_buffer_on_class_sessions
    """
    trainer = create_trainer(certified_levels=["BASIC"])
    series1 = create_series_draft(level="BASIC", modality="GROUP", capacity=5, session_count=1)
    series2 = create_series_draft(level="BASIC", modality="GROUP", capacity=5, session_count=1)
    create_session(series1, trainer, 1, "2026-07-01T09:00:00Z", "2026-07-01T10:00:00Z")

    # Second session 10:00-11:00 for the same trainer: zero gap after the first ends -> conflict.
    res = api.create_class_session(
        create_class_session_payload(series2["id"], trainer["id"], sequence_index=1,
                                     starts_at="2026-07-01T10:00:00Z", ends_at="2026-07-01T11:00:00Z"),
        TEST_USERS["admin_manager_headers"])
    validate_error(res, "ERR_TRAINER_DOUBLE_BOOKED", expected_status=409)


def test_trainer_exactly_15_minute_gap_permitted(api):
    """PRD §3.3: "The candidate and an existing session are considered separated only if the
    gap between them is at least 15 minutes — that is, the number of minutes from the earlier
    session's `ends_at` to the later session's `starts_at` is 15 or more." PRD §3.3: "A gap of
    exactly 15 minutes is permitted".

    Design: Difficulty/resource_temporal_overlap/trainer_double_booked_with_buffer_on_class_sessions
    """
    trainer = create_trainer(certified_levels=["BASIC"])
    series1 = create_series_draft(level="BASIC", modality="GROUP", capacity=5, session_count=1)
    series2 = create_series_draft(level="BASIC", modality="GROUP", capacity=5, session_count=1)
    create_session(series1, trainer, 1, "2026-07-01T09:00:00Z", "2026-07-01T10:00:00Z")

    # Second session starts exactly 15 minutes after the first ends (10:15) -> allowed.
    res = api.create_class_session(
        create_class_session_payload(series2["id"], trainer["id"], sequence_index=1,
                                     starts_at="2026-07-01T10:15:00Z", ends_at="2026-07-01T11:00:00Z"),
        TEST_USERS["admin_manager_headers"])
    created = validate_success(res, 201)
    assert created["status"] == "SCHEDULED"


def test_trainer_within_buffer_gap_rejected(api):
    """PRD §3.3: "If, for the existing session, neither the gap before nor the gap after the
    candidate reaches 15 minutes, the two conflict and the request is rejected with
    `ERR_TRAINER_DOUBLE_BOOKED`."

    Design: Difficulty/resource_temporal_overlap/trainer_double_booked_with_buffer_on_class_sessions
    """
    trainer = create_trainer(certified_levels=["BASIC"])
    series1 = create_series_draft(level="BASIC", modality="GROUP", capacity=5, session_count=1)
    series2 = create_series_draft(level="BASIC", modality="GROUP", capacity=5, session_count=1)
    create_session(series1, trainer, 1, "2026-07-01T09:00:00Z", "2026-07-01T10:00:00Z")

    # 14 minutes after the first ends (10:14) -> below the 15-minute buffer -> rejected.
    res = api.create_class_session(
        create_class_session_payload(series2["id"], trainer["id"], sequence_index=1,
                                     starts_at="2026-07-01T10:14:00Z", ends_at="2026-07-01T11:00:00Z"),
        TEST_USERS["admin_manager_headers"])
    validate_error(res, "ERR_TRAINER_DOUBLE_BOOKED", expected_status=409)


def test_dog_session_overlap_strict_on_makeup_confirm(api):
    """PRD §3.10: "Two intervals conflict only when they strictly overlap — that is, when one
    starts before the other ends and the second starts before the first ends." PRD §3.10:
    "Any strict overlap rejects the operation with `ERR_DOG_SESSION_OVERLAP`." PRD §3.11:
    "Confirmation also runs the dog schedule-overlap check (§3.10)."

    Design: Difficulty/resource_temporal_overlap/dog_session_overlap_strict_no_buffer_on_makeup_confirm
    """
    # Makeup slot strictly overlaps the dog's kept 07-02 09:00-10:00 session (09:30-10:30).
    # Assign the makeup slot to a second trainer so the trainer-overlap check at creation
    # passes, isolating the dog-overlap check at confirm time.
    second_trainer = create_trainer(certified_levels=["BASIC"], full_name="Second Trainer")
    bundle = setup_missed_provider_with_makeup_slot(
        makeup_trainer=second_trainer,
        makeup_starts="2026-07-02T09:30:00Z", makeup_ends="2026-07-02T10:30:00Z")
    makeup = bundle["makeup_booking"]

    res = api.confirm_makeup_booking(makeup["id"], TEST_USERS["front_desk_headers"])
    validate_error(res, "ERR_DOG_SESSION_OVERLAP", expected_status=409)


def test_dog_session_no_overlap_when_adjacent(api):
    """PRD §3.10: "Exact adjacency, where one session's `ends_at` equals the next session's
    `starts_at`, does not conflict; there is no buffer for a dog's own schedule."

    The complement of the strict-overlap rejection: a makeup slot that merely touches the
    kept session (10:00-11:00, touching the 09:00-10:00 session) confirms cleanly.

    Design: Difficulty/resource_temporal_overlap/dog_session_overlap_strict_no_buffer_on_makeup_confirm
    """
    second_trainer = create_trainer(certified_levels=["BASIC"], full_name="Second Trainer Adj")
    bundle = setup_missed_provider_with_makeup_slot(
        makeup_trainer=second_trainer,
        makeup_starts="2026-07-02T10:00:00Z", makeup_ends="2026-07-02T11:00:00Z")
    makeup = bundle["makeup_booking"]

    res = api.confirm_makeup_booking(makeup["id"], TEST_USERS["front_desk_headers"])
    confirmed = validate_success(res, 200)
    assert confirmed["status"] == "CONFIRMED", "touching endpoints (10:00==10:00) do not conflict"
