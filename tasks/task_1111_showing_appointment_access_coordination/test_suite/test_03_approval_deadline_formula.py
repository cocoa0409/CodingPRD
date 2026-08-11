"""Approval-deadline nested min/max formula (calc_approval_deadline)."""
import pytest

from test_helpers import (
    api_client,
    create_showing_request,
    setup_basic_world,
    validate_success,
)


def test_approval_deadline_clamped_by_min_notice_bound(api):
    """PRD §3.3: "In every other case the request is born PENDING_APPROVAL and
    the deadline is a clamped window: take the later of (a) thirty minutes
    after creation — a minimum review floor — and (b) the earlier of the
    seller's `approval_timeout_minutes` after creation and the listing's
    notice-adjusted latest approval moment, which is `start_at` minus
    `min_notice_minutes`."

    At clock 00:00 with timeout 240 / min_notice 120: start 06:00 clamps to
    04:00 (both bounds meet); start 03:00 clamps to 01:00 (notice bound wins
    over the 30-minute floor).

    Design: Difficulty/combinatorial_formula/approval_deadline_nested_minmax
    """
    world = setup_basic_world(occupancy_type="OCCUPIED", auto_approve=False)
    listing_id = world["listing"]["id"]
    ba_id = world["buyer_agent"]["id"]

    req_a = create_showing_request(listing_id, ba_id,
                                   "2026-05-01T06:00:00Z", "2026-05-01T06:30:00Z")
    assert req_a["approval_deadline"] == "2026-05-01T04:00:00Z", req_a
    assert req_a["status"] == "PENDING_APPROVAL", req_a

    req_b = create_showing_request(listing_id, ba_id,
                                   "2026-05-01T03:00:00Z", "2026-05-01T03:30:00Z")
    assert req_b["approval_deadline"] == "2026-05-01T01:00:00Z", req_b


def test_approval_deadline_collapses_to_created_at_when_vacant_auto_approve(api):
    """PRD §3.3: "When the listing is VACANT and its seller has `auto_approve`
    set, the deadline collapses to the request's own creation time and the
    request is born directly in APPROVED — no occupant touch required."

    Design: Difficulty/combinatorial_formula/approval_deadline_nested_minmax
    """
    world = setup_basic_world(occupancy_type="VACANT", auto_approve=True)
    req = create_showing_request(
        world["listing"]["id"], world["buyer_agent"]["id"],
        "2026-05-02T10:00:00Z", "2026-05-02T10:30:00Z",
    )
    # created at the startup clock reading 2026-05-01T00:00:00Z
    assert req["approval_deadline"] == "2026-05-01T00:00:00Z", req
    assert req["status"] == "APPROVED", req
