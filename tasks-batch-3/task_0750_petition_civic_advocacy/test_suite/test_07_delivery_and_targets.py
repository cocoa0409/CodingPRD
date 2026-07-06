"""Delivery-meeting scheduling gates and buffer, the target-unreachable cascade, and
optimistic-concurrency on decision-maker changes.

Queue-A depth: target_deactivation_cancels_meetings_depth2,
schedule_delivery_requires_target_active, delivery_meeting_buffer_conflict.
Queue-B breadth: occ_target_supersede_success_bumps_version,
occ_target_supersede_stale_version_rejected.
"""
import pytest
from test_helpers import (
    validate_success, validate_error, get_success_data,
    ApiErrorId,
    register_member, create_draft_petition, set_petition_target,
    create_meeting,
    TEST_USERS, make_member_headers,
)

ADMIN = TEST_USERS["admin_headers"]
GUEST = TEST_USERS["guest_headers"]


def _petition_with_active_target(api, category="POLITICS"):
    author = register_member()
    pet = create_draft_petition(author["id"], category=category, goal=100)
    target = set_petition_target(pet["id"], author["id"], pet["version"])
    return author["id"], pet["id"], target["id"]


# ── transitive_cascade / target_deactivation_cancels_meetings_depth2 ─────────
def test_deactivating_target_marks_it_unreachable(api):
    """PRD §3.2: "An administrator may mark a target unreachable, moving it from ACTIVE to
    UNREACHABLE."

    Design: Difficulty/transitive_cascade/target_deactivation_cancels_meetings_depth2
    """
    author_id, pet_id, target_id = _petition_with_active_target(api)
    create_meeting(pet_id, target_id, author_id,
                   "2026-05-01T10:00:00Z", "2026-05-01T11:00:00Z")
    target = validate_success(api.deactivate_target(target_id, ADMIN))
    assert target["status"] == "UNREACHABLE"


def test_deactivating_target_cancels_requested_meeting(api):
    """PRD §3.2: "This triggers the target-unreachable cascade: every `DeliveryMeeting` for
    that target still in `REQUESTED` or `CONFIRMED` is moved to `CANCELLED`."

    Design: Difficulty/transitive_cascade/target_deactivation_cancels_meetings_depth2
    """
    author_id, pet_id, target_id = _petition_with_active_target(api)
    meeting = create_meeting(pet_id, target_id, author_id,
                             "2026-05-01T10:00:00Z", "2026-05-01T11:00:00Z")
    api.deactivate_target(target_id, ADMIN)
    fetched = get_success_data(api.get_delivery_meeting(meeting["id"], GUEST))
    assert fetched["status"] == "CANCELLED"


# ── cross_entity_state_dependency / schedule_delivery_requires_target_active ──
def test_schedule_meeting_on_unreachable_target_rejected(api):
    """PRD §3.5: "The referenced Target must be ACTIVE at scheduling time, or the request
    is refused with ERR_TARGET_UNREACHABLE."

    Design: Difficulty/cross_entity_state_dependency/schedule_delivery_requires_target_active
    """
    author_id, pet_id, target_id = _petition_with_active_target(api)
    api.deactivate_target(target_id, ADMIN)
    resp = api.create_delivery_meeting(
        {"petition_id": pet_id, "target_id": target_id,
         "window_start": "2026-05-02T10:00:00Z", "window_end": "2026-05-02T11:00:00Z"},
        make_member_headers(author_id))
    validate_error(resp, ApiErrorId.ERR_TARGET_UNREACHABLE.value, expected_status=409)


def test_schedule_meeting_on_superseded_target_rejected(api):
    """PRD §3.5: "The referenced Target must be ACTIVE at scheduling time, or the request
    is refused with ERR_TARGET_UNREACHABLE."

    Design: Difficulty/cross_entity_state_dependency/schedule_delivery_requires_target_active
    """
    author = register_member()
    pet = create_draft_petition(author["id"], category="POLITICS", goal=100)
    target1 = set_petition_target(pet["id"], author["id"], pet["version"])
    current = get_success_data(api.get_petition(pet["id"], GUEST))
    set_petition_target(pet["id"], author["id"], current["version"])  # supersedes target1
    resp = api.create_delivery_meeting(
        {"petition_id": pet["id"], "target_id": target1["id"],
         "window_start": "2026-05-02T10:00:00Z", "window_end": "2026-05-02T11:00:00Z"},
        make_member_headers(author["id"]))
    validate_error(resp, ApiErrorId.ERR_TARGET_UNREACHABLE.value, expected_status=409)


# ── resource_temporal_overlap / delivery_meeting_buffer_conflict ─────────────
def test_meeting_within_buffer_rejected(api):
    """PRD §3.5: "A requested window that falls within 15 minutes of an existing REQUESTED
    or CONFIRMED meeting on the same target is rejected with ERR_MEETING_CONFLICT; because
    windows are half-open, two windows that merely touch at an endpoint do not themselves
    overlap, but the 15-minute buffer between them must still be respected."

    Design: Difficulty/resource_temporal_overlap/delivery_meeting_buffer_conflict
    """
    author_id, pet_id, target_id = _petition_with_active_target(api)
    create_meeting(pet_id, target_id, author_id,
                   "2026-05-01T10:00:00Z", "2026-05-01T11:00:00Z")
    resp = api.create_delivery_meeting(
        {"petition_id": pet_id, "target_id": target_id,
         "window_start": "2026-05-01T11:10:00Z", "window_end": "2026-05-01T12:00:00Z"},
        make_member_headers(author_id))
    validate_error(resp, ApiErrorId.ERR_MEETING_CONFLICT.value, expected_status=409)


def test_meeting_with_exact_15_minute_gap_allowed(api):
    """PRD §3.5: "A target holds at most one live meeting at a time: consecutive meetings
    on the same target must leave a gap of at least 15 minutes, measured between the
    earlier meeting's window_end and the later meeting's window_start."

    Design: Difficulty/resource_temporal_overlap/delivery_meeting_buffer_conflict
    """
    author_id, pet_id, target_id = _petition_with_active_target(api)
    create_meeting(pet_id, target_id, author_id,
                   "2026-05-01T10:00:00Z", "2026-05-01T11:00:00Z")
    resp = api.create_delivery_meeting(
        {"petition_id": pet_id, "target_id": target_id,
         "window_start": "2026-05-01T11:15:00Z", "window_end": "2026-05-01T12:00:00Z"},
        make_member_headers(author_id))
    data = validate_success(resp, expected_status=201)
    assert data["status"] == "REQUESTED"


# ── Corner instances ─────────────────────────────────────────────────────────
def test_target_supersede_success_supersedes_prior_and_bumps_version(api):
    """PRD §3.2: "Setting a replacement target automatically supersedes the prior one: the
    previously ACTIVE Target moves from ACTIVE to SUPERSEDED, and the petition's version
    increments by 1."

    Design: Corner/cross_cutting_complexity_layers/occ_target_supersede_success_bumps_version
    """
    author = register_member()
    pet = create_draft_petition(author["id"], goal=10)
    target1 = set_petition_target(pet["id"], author["id"], pet["version"])
    before = get_success_data(api.get_petition(pet["id"], GUEST))
    target2 = set_petition_target(pet["id"], author["id"], before["version"])
    t1 = get_success_data(api.get_target(target1["id"], GUEST))
    t2 = get_success_data(api.get_target(target2["id"], GUEST))
    after = get_success_data(api.get_petition(pet["id"], GUEST))
    assert t1["status"] == "SUPERSEDED"
    assert t2["status"] == "ACTIVE"
    assert after["version"] == before["version"] + 1


def test_target_supersede_with_stale_version_rejected(api):
    """PRD §2.6: "If another writer has advanced the petition's version since the client
    last read it — for instance by already replacing the decision-maker and superseding
    the prior one — the client's view is stale, and the request is rejected with
    ERR_STALE_PETITION_VERSION (HTTP 412)."

    Design: Corner/cross_cutting_complexity_layers/occ_target_supersede_stale_version_rejected
    """
    author = register_member()
    pet = create_draft_petition(author["id"], goal=10)
    stale_version = pet["version"]
    set_petition_target(pet["id"], author["id"], stale_version)  # advances version
    resp = api.set_target(
        pet["id"],
        {"name": "T2", "title": "T", "office": "O", "expected_petition_version": stale_version},
        make_member_headers(author["id"]))
    validate_error(resp, ApiErrorId.ERR_STALE_PETITION_VERSION.value, expected_status=412)
