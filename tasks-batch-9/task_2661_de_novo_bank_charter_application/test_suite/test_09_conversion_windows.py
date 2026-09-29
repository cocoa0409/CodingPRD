"""
Core-conversion windows: an aggregate capacity of two, adjacency, and the signature gate.
"""

from prd_bench_local_runner.testing import get_success_data, validate_error

from test_helpers import COUNSEL_HEADERS, fixtures as fx
from test_helpers.assertions import (
    assert_fields_equal,
    assert_two_decimal_places,
    assert_version_unchanged,
)
from test_helpers.factories import conversion_window_payload
from test_helpers.types import (
    VENDOR_SELECTED,
    VENDOR_SIGNED,
    WINDOW_CONFIRMED,
    WINDOW_RESERVED,
)


def _selected_core_vendor(api):
    """A group with its critical core-processing contract selected but not yet signed."""
    world = fx.open_group(api)
    world["vc_id"] = fx.add_vendor_contract(api, world)
    fx.advance_vendor(api, world["vc_id"], VENDOR_SELECTED)
    return world


def _two_overlapping_reservations(api):
    """
    Two migrations already booked against the same contract and overlapping each other:
    [2026-09-01T08:00:00Z, 2026-09-02T08:00:00Z) and
    [2026-09-01T20:00:00Z, 2026-09-02T20:00:00Z).
    """
    world = _selected_core_vendor(api)
    world["w1"] = fx.reserve_window(
        api, world["vc_id"], "2026-09-01T08:00:00Z", "2026-09-02T08:00:00Z"
    )
    world["w2"] = fx.reserve_window(
        api, world["vc_id"], "2026-09-01T20:00:00Z", "2026-09-02T20:00:00Z"
    )
    world["vc_version"] = fx.contract_version(api, world["vc_id"])
    return world


def _reserve(api, world, window_start_utc, window_end_utc):
    return api.create_conversion_window(
        conversion_window_payload(
            world["vc_id"], world["vc_version"], window_start_utc, window_end_utc
        ),
        COUNSEL_HEADERS,
    )


# ---------------------------------------------------------------------------
# Difficulty / resource_temporal_overlap
# ---------------------------------------------------------------------------
def test_a_third_simultaneous_migration_exhausts_the_aggregate_capacity(api):
    """
    The two standing reservations already run concurrently through the small hours of
    2026-09-02, so a window pitched into that overlap has two occupants against it rather
    than one and is the booking that fails. Nothing is written: the contract still counts
    two active windows at the version the client held.

    PRD: "The reservation is refused with `ERR_CONVERSION_CAPACITY_EXCEEDED` when the number of overlapping occupants is 2 or more; one overlapping occupant is therefore accepted and becomes the second concurrent window, and a third simultaneous booking is the one that fails."

    Design: Difficulty/resource_temporal_overlap/conversion_window_aggregate_capacity_two_allows_adjacency
    """
    world = _two_overlapping_reservations(api)
    before = fx.read_contract(api, world["vc_id"])
    assert_fields_equal(before, active_window_count=2)

    validate_error(
        _reserve(api, world, "2026-09-02T00:00:00Z", "2026-09-02T12:00:00Z"),
        "ERR_CONVERSION_CAPACITY_EXCEEDED",
        expected_status=409,
    )
    after = fx.read_contract(api, world["vc_id"])
    assert_fields_equal(after, active_window_count=2)
    assert_version_unchanged(before, after)


def test_a_window_starting_where_another_ends_is_adjacent_and_books(api):
    """
    Pushed back to begin at exactly the instant the later reservation closes, the same
    twelve-hour migration overlaps nothing at all and is accepted as a third booking. The
    contract now counts three active windows even though only two ever run at once, since
    the count is of occupants and not of overlaps.

    PRD: "Because the interval is half-open with no buffer at all, a window starting at exactly the instant another ends is adjacent rather than overlapping and consumes no capacity."
    PRD: "On success the window begins in `RESERVED`, the contract's `active_window_count` is recomputed as the number of its `RESERVED` or `CONFIRMED` windows — counting all occupants, not merely the overlapping ones — and the contract's `version` increments by one."

    Design: Difficulty/resource_temporal_overlap/conversion_window_aggregate_capacity_two_allows_adjacency
    """
    world = _two_overlapping_reservations(api)

    w4 = get_success_data(
        _reserve(api, world, "2026-09-02T20:00:00Z", "2026-09-03T08:00:00Z"),
        expected_status=201,
    )
    assert_fields_equal(w4, status=WINDOW_RESERVED)
    assert_two_decimal_places(w4["duration_hours"], 12.00, "duration_hours")

    for window_id in (world["w1"], world["w2"]):
        window = fx.read_window(api, window_id)
        assert_fields_equal(window, status=WINDOW_RESERVED)
        assert_two_decimal_places(window["duration_hours"], 24.00, "duration_hours")

    assert_fields_equal(fx.read_contract(api, world["vc_id"]), active_window_count=3)


# ---------------------------------------------------------------------------
# Difficulty / cross_entity_state_dependency
# ---------------------------------------------------------------------------
def test_confirming_against_a_merely_selected_contract_is_refused(api):
    """
    Selection was enough to hold the slot but not to commit to it. The confirmation is
    refused on the parent contract's status and the window stays reserved, its
    twenty-four hour duration untouched.

    PRD: "The parent contract must be `SIGNED`: being `SELECTED` is enough to *reserve* a window but not to *confirm* one, and confirming against a merely selected contract is refused with `ERR_VENDOR_CONTRACT_NOT_SIGNED`."

    Design: Difficulty/cross_entity_state_dependency/conversion_window_confirm_requires_signed_vendor_contract
    """
    world = _selected_core_vendor(api)
    w1 = fx.reserve_window(
        api, world["vc_id"], "2026-09-01T08:00:00Z", "2026-09-02T08:00:00Z"
    )
    before = fx.read_window(api, w1)

    validate_error(
        api.confirm_conversion_window(w1, COUNSEL_HEADERS),
        "ERR_VENDOR_CONTRACT_NOT_SIGNED",
        expected_status=409,
    )

    after = fx.read_window(api, w1)
    assert_fields_equal(after, status=WINDOW_RESERVED)
    assert_two_decimal_places(after["duration_hours"], 24.00, "duration_hours")
    assert_version_unchanged(before, after)
    assert_fields_equal(fx.read_contract(api, world["vc_id"]), status=VENDOR_SELECTED)


def test_signing_the_contract_unlocks_the_confirmation(api):
    """
    Once the vendor is actually under signature the very same confirmation goes through
    and the window commits. The count of active windows does not move, because a reserved
    window and a confirmed one occupy the calendar alike.

    PRD: "On success `status` becomes `CONFIRMED` and the window's `version` increments by one; because both `RESERVED` and `CONFIRMED` count as occupants, confirmation does not change `active_window_count`."

    Design: Difficulty/cross_entity_state_dependency/conversion_window_confirm_requires_signed_vendor_contract
    """
    world = _selected_core_vendor(api)
    w1 = fx.reserve_window(
        api, world["vc_id"], "2026-09-01T08:00:00Z", "2026-09-02T08:00:00Z"
    )
    assert_fields_equal(
        fx.advance_vendor(api, world["vc_id"], VENDOR_SIGNED), status=VENDOR_SIGNED
    )

    confirmed = get_success_data(api.confirm_conversion_window(w1, COUNSEL_HEADERS))
    assert_fields_equal(confirmed, status=WINDOW_CONFIRMED, version=2)
    assert_two_decimal_places(confirmed["duration_hours"], 24.00, "duration_hours")
    assert_fields_equal(fx.read_contract(api, world["vc_id"]), active_window_count=1)
