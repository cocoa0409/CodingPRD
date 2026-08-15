"""Craftsmanship pre-judging slots: window and overlap rules, panel scoping,
book/release conservation, and the craftsmanship scoring phase gate.
"""
import pytest

from test_helpers import (
    ApiErrorId,
    assert_entry,
    assert_prejudging_slot,
    is_iso8601_timestamp,
    is_valid_uuid,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import fixtures as fx
from test_helpers.factories import create_prejudging_slot_payload
from test_helpers.test_users import TEST_USERS, make_contestant_headers

LEAD = TEST_USERS["contest_lead_headers"]


def _contest_with_category():
    contest = fx.create_contest()
    category = fx.create_category(contest["id"])
    return contest, category


def _open_contest_with_approved_entry():
    """Contest REGISTRATION_OPEN, one SAFETY_APPROVED entry (default
    requires_prejudging == true so the craftsmanship panel must see it)."""
    contest, category = _contest_with_category()
    fx.open_registration(contest["id"])
    contestant = fx.create_contestant()
    entry = fx.create_entry(contestant, category["id"], title="E1",
                            requires_prejudging=True)
    fx.approve_entry_safety(entry["id"])
    return contest, category, contestant, entry


# ---------------------------------------------------------------------------
# Slot shape and window validation
# ---------------------------------------------------------------------------

def test_slot_end_equal_to_start_returns_400(api):
    """PRD §3.4: "A `ContestLead` defines a `PreJudgingSlot` by supplying `category_id`, a `panel_name` identifying the judging panel, and a `[start_at, end_at]` window with `end_at` strictly after `start_at`."
    PRD §2.8: "then field-shape validation such as missing fields, bad types, bad enums, and out-of-range scores (`ERR_VALIDATION`)"

    Equal endpoints violate end_at > start_at and are a 400, not a 409 overlap.

    Design: Corner/entities/slot_end_before_start_returns_400
    """
    _, category = _contest_with_category()
    resp = api.create_prejudging_slot(
        create_prejudging_slot_payload(
            category["id"], start_at="2026-08-15T11:00:00Z",
            end_at="2026-08-15T11:00:00Z"),
        LEAD,
    )
    validate_error(resp, ApiErrorId.ERR_VALIDATION)


def test_slot_outside_contest_window_returns_422(api):
    """PRD §3.4: "The slot must lie entirely within its contest's window: the slot's `start_at` must be on or after the contest's `start_at` and the slot's `end_at` must be on or before the contest's `end_at`, otherwise the request is rejected with `ERR_SLOT_OUTSIDE_WINDOW` (HTTP 422)."

    Design: Corner/validations/slot_outside_contest_window_returns_422
    """
    _, category = _contest_with_category()
    resp = api.create_prejudging_slot(
        create_prejudging_slot_payload(
            category["id"], start_at="2026-08-15T08:00:00Z",
            end_at="2026-08-15T08:30:00Z"),
        LEAD,
    )
    validate_error(resp, ApiErrorId.ERR_SLOT_OUTSIDE_WINDOW)


# ---------------------------------------------------------------------------
# Overlap: half-open adjacency on the (category_id, panel_name) resource
# ---------------------------------------------------------------------------

def test_prejudge_slot_overlap_and_half_open_adjacency(api):
    """PRD §3.4: "Within a given `(category_id, panel_name)` pair, slot windows may not overlap — two slots overlap when each starts before the other ends, with half-open adjacency allowed so a slot beginning exactly when another ends is legal; a violating request is rejected with `ERR_SLOT_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/prejudge_slot_panel_half_open_adjacency
    """
    _, category = _contest_with_category()
    fx.create_prejudging_slot(category["id"], panel_name="P1",
                              start_at="2026-08-15T10:00:00Z",
                              end_at="2026-08-15T11:00:00Z")

    # Partially overlapping the existing P1 window -> rejected.
    resp_overlap = api.create_prejudging_slot(
        create_prejudging_slot_payload(
            category["id"], panel_name="P1",
            start_at="2026-08-15T10:30:00Z", end_at="2026-08-15T11:30:00Z"),
        LEAD,
    )
    validate_error(resp_overlap, ApiErrorId.ERR_SLOT_OVERLAP)

    # Back-to-back on the same panel: half-open adjacency is legal.
    resp_adjacent = api.create_prejudging_slot(
        create_prejudging_slot_payload(
            category["id"], panel_name="P1",
            start_at="2026-08-15T11:00:00Z", end_at="2026-08-15T12:00:00Z"),
        LEAD,
    )
    adjacent = validate_success(resp_adjacent, 201)
    assert_prejudging_slot(adjacent)
    assert adjacent["status"] == "OPEN"

    # Same wall-clock window on a different panel of the same category.
    resp_other_panel = api.create_prejudging_slot(
        create_prejudging_slot_payload(
            category["id"], panel_name="P2",
            start_at="2026-08-15T10:30:00Z", end_at="2026-08-15T11:30:00Z"),
        LEAD,
    )
    validate_success(resp_other_panel, 201)


def test_prejudge_slot_overlap_scoped_per_category_and_panel(api):
    """PRD §3.4: "Within a given `(category_id, panel_name)` pair, slot windows may not overlap — two slots overlap when each starts before the other ends, with half-open adjacency allowed so a slot beginning exactly when another ends is legal; a violating request is rejected with `ERR_SLOT_OVERLAP`."

    A fully contained window on the same panel is an overlap; the identical
    window on a different category's same-named panel is not.

    Design: Difficulty/resource_temporal_overlap/prejudge_slot_panel_half_open_adjacency
    """
    contest, category_a = _contest_with_category()
    category_b = fx.create_category(contest["id"], name="Needlework",
                                    skill_division="NOVICE")
    fx.create_prejudging_slot(category_a["id"], panel_name="P1",
                              start_at="2026-08-15T10:00:00Z",
                              end_at="2026-08-15T11:00:00Z")

    resp_contained = api.create_prejudging_slot(
        create_prejudging_slot_payload(
            category_a["id"], panel_name="P1",
            start_at="2026-08-15T10:15:00Z", end_at="2026-08-15T10:45:00Z"),
        LEAD,
    )
    validate_error(resp_contained, ApiErrorId.ERR_SLOT_OVERLAP)

    resp_other_category = api.create_prejudging_slot(
        create_prejudging_slot_payload(
            category_b["id"], panel_name="P1",
            start_at="2026-08-15T10:15:00Z", end_at="2026-08-15T10:45:00Z"),
        LEAD,
    )
    validate_success(resp_other_category, 201)


# ---------------------------------------------------------------------------
# Book / release
# ---------------------------------------------------------------------------

def test_book_slot_of_other_category_returns_mismatch(api):
    """PRD §3.4: "the entry's `category_id` must equal the slot's `category_id` (otherwise `ERR_ENTRY_CATEGORY_MISMATCH`)"

    Design: Corner/validations/book_slot_of_other_category_returns_mismatch
    """
    contest = fx.create_contest()
    cat_a = fx.create_category(contest["id"], name="A")
    cat_b = fx.create_category(contest["id"], name="B", skill_division="NOVICE")
    fx.open_registration(contest["id"])
    contestant = fx.create_contestant()
    entry = fx.create_entry(contestant, cat_b["id"], title="E1")
    fx.approve_entry_safety(entry["id"])
    slot = fx.create_prejudging_slot(cat_a["id"], panel_name="P1")

    resp = api.book_prejudging_slot(
        slot["id"], {"entry_id": entry["id"]}, fx.contestant_headers(contestant)
    )
    validate_error(resp, ApiErrorId.ERR_ENTRY_CATEGORY_MISMATCH)


def test_slot_book_then_release_conserves_count(api):
    """PRD §3.4: "A contestant books an `OPEN` slot by naming the `entry_id` of one of their own entries"
    PRD §3.4: "A booked slot can be released — by the contestant who owns the booked entry (anyone else drawing `ERR_NOT_OWNER`), by a `ContestLead` marking a no-show, or by system cascade — which returns it to `OPEN`, clears `booked_entry_id`, and leaves the entry's own status untouched so it may rebook."

    Design: Difficulty/compensating_invariant/slot_book_release_count_conservation
    """
    _, category, contestant, entry = _open_contest_with_approved_entry()
    headers = fx.contestant_headers(contestant)
    sl1 = fx.create_prejudging_slot(category["id"], panel_name="P1",
                                    start_at="2026-08-15T10:00:00Z",
                                    end_at="2026-08-15T11:00:00Z")
    sl2 = fx.create_prejudging_slot(category["id"], panel_name="P1",
                                    start_at="2026-08-15T11:00:00Z",
                                    end_at="2026-08-15T12:00:00Z")

    booked = fx.book_slot(sl1["id"], contestant, entry["id"])
    assert booked["status"] == "BOOKED"
    assert booked["booked_entry_id"] == entry["id"]
    # The sibling slot is untouched: 1 BOOKED + 1 OPEN == 2 total.
    assert fx.get_prejudging_slot(sl2["id"])["status"] == "OPEN"

    released = validate_success(
        api.release_prejudging_slot(sl1["id"], headers)
    )
    assert released["status"] == "OPEN"
    assert released["booked_entry_id"] is None
    # Slot count conserved: 0 BOOKED + 2 OPEN == 2 total.
    assert fx.get_prejudging_slot(sl2["id"])["status"] == "OPEN"

    # Release does not regress the entry.
    entry_after = fx.get_entry(entry["id"])
    assert entry_after["status"] == "SAFETY_APPROVED"


def test_slot_release_by_non_owner_and_lead_then_rebook(api):
    """PRD §3.4: "A booked slot can be released — by the contestant who owns the booked entry (anyone else drawing `ERR_NOT_OWNER`), by a `ContestLead` marking a no-show, or by system cascade — which returns it to `OPEN`, clears `booked_entry_id`, and leaves the entry's own status untouched so it may rebook."

    Design: Difficulty/compensating_invariant/slot_book_release_count_conservation
    """
    _, category, contestant, entry = _open_contest_with_approved_entry()
    other = fx.create_contestant()
    sl1 = fx.create_prejudging_slot(category["id"], panel_name="P1")
    fx.book_slot(sl1["id"], contestant, entry["id"])

    # A different contestant may not release the booking.
    resp_forbidden = api.release_prejudging_slot(
        sl1["id"], fx.contestant_headers(other)
    )
    validate_error(resp_forbidden, ApiErrorId.ERR_NOT_OWNER)
    assert fx.get_prejudging_slot(sl1["id"])["status"] == "BOOKED"

    # The lead may release it (no-show); the slot count is conserved.
    released = validate_success(api.release_prejudging_slot(sl1["id"], LEAD))
    assert released["status"] == "OPEN"
    assert released["booked_entry_id"] is None

    # The entry may rebook immediately.
    rebooked = fx.book_slot(sl1["id"], contestant, entry["id"])
    assert rebooked["status"] == "BOOKED"
    assert rebooked["booked_entry_id"] == entry["id"]


# ---------------------------------------------------------------------------
# Craftsmanship phase gate
# ---------------------------------------------------------------------------

def test_craftsmanship_sheet_gated_on_prejudged(api):
    """PRD §3.5: "Phase gates apply at the state tier: a `CRAFTSMANSHIP` sheet may be created only for an entry that is `PREJUDGED`, and a `STAGE` sheet only for an entry that is `STAGE_QUEUED` or `PERFORMED`."
    PRD §3.4: "When the panel finishes, a `ContestLead` completes a `BOOKED` slot, which advances the booked entry from `SAFETY_APPROVED` to `PREJUDGED`."
    PRD §3.5: "A sheet starts in `DRAFT`."

    Design: Corner/state_machines/prejudging_flow_gates_craftsmanship_phase
    """
    contest, category, contestant, entry = _open_contest_with_approved_entry()
    judge = fx.create_judge(contest["id"], [category["id"]])
    slot = fx.create_prejudging_slot(category["id"], panel_name="P1")

    # Entry only SAFETY_APPROVED: the CRAFTSMANSHIP phase gate rejects.
    resp_blocked = api.create_scoresheet(
        {"entry_id": entry["id"], "phase": "CRAFTSMANSHIP",
         "craftsmanship": 8, "accuracy": 8, "presentation": 8},
        fx.judge_headers(judge),
    )
    validate_error(resp_blocked, ApiErrorId.ERR_INVALID_STATE)

    fx.book_slot(slot["id"], contestant, entry["id"])
    completed = validate_success(api.complete_prejudging_slot(slot["id"], LEAD))
    assert completed["status"] == "COMPLETED"
    assert fx.get_entry(entry["id"])["status"] == "PREJUDGED"

    resp_ok = api.create_scoresheet(
        {"entry_id": entry["id"], "phase": "CRAFTSMANSHIP",
         "craftsmanship": 8, "accuracy": 8, "presentation": 8},
        fx.judge_headers(judge),
    )
    sheet = validate_success(resp_ok, 201)
    assert sheet["status"] == "DRAFT"


# ---------------------------------------------------------------------------
# Listing: default pagination envelope
# ---------------------------------------------------------------------------

def test_slot_list_default_pagination(api):
    """PRD §2.3: "The `limit` parameter controls the maximum number of items returned; it defaults to 10, has a minimum of 1, and has a maximum of 100. The `offset` parameter controls the number of items skipped before the page begins and defaults to 0."
    PRD §2.3: "The `meta` block of a list response carries `limit`, `offset`, `total_count`, and `has_more`."
    PRD §2.4: "Every top-level resource — `ContestEvent`, `Category`, `Contestant`, `Judge`, `Entry`, `PreJudgingSlot`, `ScoreSheet`, `PerformanceSlot`, `PrizeAward`, and `GreenRoomBooking` — carries four system-managed fields."

    Design: Corner/endpoints/slot_list_pagination_defaults_and_envelope
    """
    _, category = _contest_with_category()
    for i in range(12):
        fx.create_prejudging_slot(category["id"], panel_name=f"P{i + 1:02d}")

    resp1 = api.list_prejudging_slots(LEAD, params={"category_id": category["id"]})
    page1, meta1 = validate_paginated(resp1)
    assert resp1.json()["response_type"] == "array"
    assert len(page1) == 10
    assert meta1["total_count"] == 12
    assert meta1["has_more"] is True
    assert meta1["limit"] == 10
    assert meta1["offset"] == 0
    for item in page1:
        assert is_valid_uuid(item["id"])
        assert is_iso8601_timestamp(item["created_at"])
        assert is_iso8601_timestamp(item["updated_at"])
        assert isinstance(item["version"], int)

    resp2 = api.list_prejudging_slots(
        LEAD, params={"category_id": category["id"], "limit": 10, "offset": 10}
    )
    page2, meta2 = validate_paginated(resp2)
    assert len(page2) == 2
    assert meta2["total_count"] == 12
    assert meta2["has_more"] is False
