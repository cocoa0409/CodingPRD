"""Optimistic concurrency control on PATCH endpoints, plus the PRD-defined
race outcomes from §3.7."""
from __future__ import annotations

import pytest

from test_helpers import (
    api_client,
    assert_exactly_one_succeeds,
    create_spare_part,
    create_technician,
    make_technician_headers,
    patch_spare_part_payload,
    patch_technician_payload,
    run_race,
    setup_pending_workorder,
    validate_error,
    validate_success,
)


# ---------------------------------------------------------------------------
# 2.5 — OCC version match on PATCH
# ---------------------------------------------------------------------------
def test_patch_with_stale_version_rejected(api, storekeeper_headers):
    """PRD §2.5: 'When version is supplied, it must equal the current
    entity version; a mismatch is rejected with ERR_VERSION_CONFLICT and
    HTTP 409.'
    """
    bag = setup_pending_workorder()
    spare = create_spare_part(bag["site"]["id"])
    stale_version = spare["version"]
    # Bump the spare via a real PATCH (replenishment delivery)
    api.patch_spare_part(
        bag["site"]["id"], spare["id"],
        patch_spare_part_payload(stale_version, stock_delta=5),
        storekeeper_headers,
    )
    # Now retry with the stale version
    res = api.patch_spare_part(
        bag["site"]["id"], spare["id"],
        patch_spare_part_payload(stale_version, reorder_point=3),
        storekeeper_headers,
    )
    validate_error(res, "ERR_VERSION_CONFLICT", expected_status=409)


def test_patch_omitted_version_skips_occ(api, storekeeper_headers):
    """PRD §2.5: 'When version is omitted, the OCC check is skipped and
    the mutation proceeds against whatever the latest state happens to be.'
    """
    bag = setup_pending_workorder()
    spare = create_spare_part(bag["site"]["id"])
    payload = {"stock_delta": 1}  # no 'version' field
    res = api.patch_spare_part(
        bag["site"]["id"], spare["id"], payload, storekeeper_headers,
    )
    after = validate_success(res, expected_status=200)
    assert after["stock_on_hand"] == spare["stock_on_hand"] + 1


def test_patch_increments_version_by_one(api, site_manager_headers):
    """PRD §2.5: 'On every successful mutation that returns a 200 response,
    the entity's version increments by exactly one and updated_at is
    refreshed to the site clock.'
    """
    bag = setup_pending_workorder()
    tech = create_technician(bag["site"]["id"], skills=["MECHANICAL"])
    res = api.patch_technician(
        bag["site"]["id"], tech["id"],
        patch_technician_payload(tech["version"], skills=["ELECTRICAL"]),
        site_manager_headers,
    )
    after = validate_success(res, expected_status=200)
    assert after["version"] == tech["version"] + 1


# ---------------------------------------------------------------------------
# 3.7 — race: two starts on same WO → exactly one wins
# ---------------------------------------------------------------------------
def test_race_two_starts_exactly_one_wins(api):
    """PRD §3.7: 'Two technicians attempting to start the same PENDING
    work order serialize first-writer-wins on WorkOrder.status. Exactly
    one start succeeds; the loser observes the order is already
    IN_PROGRESS and is rejected with ERR_INVALID_STATE and HTTP 409.'

    We run two parallel start calls from the SAME assigned technician (a
    test bug if assigned vs others; PRD specifies state-conflict). The
    framework's run_race serializes; assert exactly one 2xx and one 4xx.
    """
    bag = setup_pending_workorder()
    site_id = bag["site"]["id"]
    wo_id = bag["work_order"]["id"]
    tech_headers = make_technician_headers(bag["technician"]["id"])

    a, b = run_race(
        lambda: api.start_work_order(site_id, wo_id, tech_headers),
        lambda: api.start_work_order(site_id, wo_id, tech_headers),
    )
    outcome = assert_exactly_one_succeeds(a, b)
    loser = outcome["failures"][0]
    assert loser.status_code == 409
    body = loser.json()
    assert body["data"]["error_id"] == "ERR_INVALID_STATE"
