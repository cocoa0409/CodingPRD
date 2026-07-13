"""Commodity index publication, idempotency, and window-overlap rules."""
from test_helpers import validate_success, validate_error, ApiErrorId, TEST_USERS
from test_helpers.fixtures import create_index, publish_index, create_and_publish_index

TRADER = TEST_USERS["commodity_trader_headers"]


def test_publish_already_published_index_rejected(api):
    """PRD §3.2: "Publishing an index advances it from `DRAFT` to `PUBLISHED`.
    Publication is only permitted on an index currently in `DRAFT`; otherwise it is
    rejected with `ERR_INDEX_NOT_DRAFT`."

    Design: Corner/state_machines/corner_publish_index_twice_idempotency_rejected
    """
    idx = create_and_publish_index(api, "OCC", 8000)
    resp = api.publish_commodity_index(idx["id"], TRADER)
    validate_error(resp, ApiErrorId.ERR_INDEX_NOT_DRAFT.value)


def test_publish_interior_overlapping_window_rejected(api):
    """PRD §3.2: "Finally, the new window must not overlap any existing `PUBLISHED`
    index for the same commodity; because the windows are half-open, mere adjacency
    (one window's `effective_end` equal to the next window's `effective_start`) is
    permitted, but any true overlap is rejected with `ERR_INDEX_WINDOW_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/index_half_open_interior_overlap_conflict
    """
    create_and_publish_index(api, "OCC", 8000,
                             "2026-03-01T00:00:00Z", "2026-03-15T00:00:00Z")
    idx2 = create_index(api, "OCC", 8100,
                        "2026-03-10T00:00:00Z", "2026-03-20T00:00:00Z")
    resp = api.publish_commodity_index(idx2["id"], TRADER)
    validate_error(resp, ApiErrorId.ERR_INDEX_WINDOW_OVERLAP.value)


def test_publish_adjacent_window_allowed(api):
    """PRD §3.2: "because the windows are half-open, mere adjacency (one window's
    `effective_end` equal to the next window's `effective_start`) is permitted, but
    any true overlap is rejected with `ERR_INDEX_WINDOW_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/index_half_open_interior_overlap_conflict
    """
    create_and_publish_index(api, "OCC", 8000,
                             "2026-03-01T00:00:00Z", "2026-03-15T00:00:00Z")
    idx2 = create_index(api, "OCC", 8100,
                        "2026-03-15T00:00:00Z", "2026-03-20T00:00:00Z")
    published = validate_success(api.publish_commodity_index(idx2["id"], TRADER))
    assert published["status"] == "PUBLISHED"
