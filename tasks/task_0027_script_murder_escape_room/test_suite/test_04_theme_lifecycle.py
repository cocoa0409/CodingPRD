"""Theme creation, publish, publish-revision, retire."""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    ThemeStatus,
    advance_clock_to,
    assert_theme,
    create_published_theme,
    create_room,
    create_session_slot,
    create_staff_member,
    create_theme_payload,
    create_venue,
    make_script_author_headers,
    publish_theme_revision_payload,
    setup_basic_scenario,
    unique_chain_id,
    validate_error,
    validate_success,
)


def test_create_theme_starts_in_draft(api):
    """PRD §3.2: "On creation, `current_version` is set to 1 and `status` is `DRAFT`."

    Claim: a freshly-created theme has status=DRAFT and current_version=1.
    """
    chain_id = unique_chain_id()
    venue = create_venue(chain_id=chain_id)
    room = create_room(venue)
    author = create_staff_member(chain_id)
    headers = make_script_author_headers(author["id"])
    payload = create_theme_payload(chain_id, [room["id"]])
    theme = validate_success(api.create_theme(payload, headers), expected_status=201)
    assert_theme(theme)
    assert theme["status"] == ThemeStatus.DRAFT.value
    assert theme["current_version"] == 1


def test_publish_theme_advances_to_published_no_version_bump(api):
    """PRD §3.2: "Publishing a theme advances `Theme.status` from `DRAFT` to `PUBLISHED`."
    PRD §3.2: "The first publication does not change `current_version`, which remains 1."

    Claim: first publish leaves current_version unchanged at 1.
    """
    chain_id = unique_chain_id()
    venue = create_venue(chain_id=chain_id)
    room = create_room(venue)
    author = create_staff_member(chain_id)
    headers = make_script_author_headers(author["id"])
    theme = validate_success(api.create_theme(create_theme_payload(chain_id, [room["id"]]), headers), expected_status=201)
    published = validate_success(api.publish_theme(theme["id"], headers))
    assert published["status"] == ThemeStatus.PUBLISHED.value
    assert published["current_version"] == 1


def test_publish_revision_bumps_current_version(api):
    """PRD §3.2: "this transition keeps `Theme.status` at `PUBLISHED` but increments `current_version` by 1."

    Claim: publish-revision keeps PUBLISHED and bumps current_version by 1.
    """
    chain_id = unique_chain_id()
    venue = create_venue(chain_id=chain_id)
    room = create_room(venue)
    author = create_staff_member(chain_id)
    headers = make_script_author_headers(author["id"])
    theme = create_published_theme(chain_id, [room["id"]], author_staff_member=author)
    revised = validate_success(api.publish_theme_revision(theme["id"], publish_theme_revision_payload(True), headers))
    assert revised["status"] == ThemeStatus.PUBLISHED.value
    assert revised["current_version"] == 2


def test_publish_revision_requires_bumps_version_true(api):
    """PRD §3.2: "The body must explicitly set `bumps_version` to `true` (otherwise `ERR_INVALID_REQUEST`)."

    Claim: publish-revision with bumps_version=false yields ERR_INVALID_REQUEST.
    """
    chain_id = unique_chain_id()
    venue = create_venue(chain_id=chain_id)
    room = create_room(venue)
    author = create_staff_member(chain_id)
    headers = make_script_author_headers(author["id"])
    theme = create_published_theme(chain_id, [room["id"]], author_staff_member=author)
    resp = api.publish_theme_revision(theme["id"], {"bumps_version": False}, headers)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)


def test_existing_slot_keeps_pinned_version_after_revision(api):
    """PRD §3.2: "existing `SessionSlot` rows retain their previously pinned `theme_version_pinned` value, while any new slot created after the revision pins the new `current_version`."

    Claim: a slot created against version 1 keeps theme_version_pinned=1 even after the theme is revised to version 2.
    """
    chain_id = unique_chain_id()
    venue = create_venue(chain_id=chain_id)
    room = create_room(venue)
    author = create_staff_member(chain_id)
    headers = make_script_author_headers(author["id"])
    theme = create_published_theme(chain_id, [room["id"]], author_staff_member=author)
    slot = create_session_slot(venue, room, theme, visibility="PRIVATE_ONLY", required_seats_for_launch=theme["min_players"])
    assert slot["theme_version_pinned"] == 1
    # Revise theme to version 2.
    validate_success(api.publish_theme_revision(theme["id"], publish_theme_revision_payload(True), headers))
    # Refresh the slot. PRD §4: GET /session-slots/{slotId} authorises
    # PlatformAdmin, VenueOperator, Player — NOT ScriptAuthor — so we use the
    # owning venue operator's headers here (the slot is read-only either way).
    from test_helpers import make_venue_operator_headers
    refreshed = validate_success(api.get_session_slot(slot["id"], make_venue_operator_headers(venue["id"])))
    assert refreshed["theme_version_pinned"] == 1


def test_retire_blocked_by_open_session(api):
    """PRD §3.2: "Retiring a theme advances it to `RETIRED` from either `DRAFT` or `PUBLISHED`, but only when no `SessionSlot` exists with `theme_id` equal to this theme and `schedule_status` in `SCHEDULED` or `LIVE`; otherwise the request is rejected with `ERR_THEME_HAS_FUTURE_SESSIONS`."

    Claim: an open SCHEDULED slot blocks theme retirement.
    """
    chain_id = unique_chain_id()
    venue = create_venue(chain_id=chain_id)
    room = create_room(venue)
    author = create_staff_member(chain_id)
    headers = make_script_author_headers(author["id"])
    theme = create_published_theme(chain_id, [room["id"]], author_staff_member=author)
    create_session_slot(venue, room, theme, visibility="PRIVATE_ONLY", required_seats_for_launch=theme["min_players"])
    resp = api.retire_theme(theme["id"], headers)
    validate_error(resp, ApiErrorId.ERR_THEME_HAS_FUTURE_SESSIONS.value)


def test_create_slot_against_draft_theme_rejected(api):
    """PRD §3.2: "Slot creation on a theme not in `PUBLISHED` status — that is, on a `DRAFT` or `RETIRED` theme — is rejected with `ERR_THEME_NOT_PUBLISHED`."

    Claim: creating a slot against a DRAFT theme yields ERR_THEME_NOT_PUBLISHED.
    """
    chain_id = unique_chain_id()
    venue = create_venue(chain_id=chain_id)
    room = create_room(venue)
    author = create_staff_member(chain_id)
    author_headers = make_script_author_headers(author["id"])
    draft_theme = validate_success(
        api.create_theme(create_theme_payload(chain_id, [room["id"]]), author_headers),
        expected_status=201,
    )
    # Operator tries to create a slot against the DRAFT theme.
    from test_helpers import make_venue_operator_headers, create_session_slot_payload, future_iso
    op_headers = make_venue_operator_headers(venue["id"])
    payload = create_session_slot_payload(
        theme_id=draft_theme["id"],
        starts_at=future_iso(48),
        visibility="PRIVATE_ONLY",
        required_seats_for_launch=draft_theme["min_players"],
    )
    resp = api.create_session_slot(venue["id"], room["id"], payload, op_headers)
    validate_error(resp, ApiErrorId.ERR_THEME_NOT_PUBLISHED.value)
