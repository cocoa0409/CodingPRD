"""Optimistic concurrency on pre-order re-quote (version supersede).

Each test docstring cites the verbatim PRD sentence it asserts and ends with a
Design: traceability tag mapping it to its originating design-index instance.
"""
import pytest
from test_helpers import (
    validate_success, validate_error,
    make_flavor, make_station, make_pre_order, get_pre_order,
    TEST_USERS,
)

MGR = TEST_USERS["manager_headers"]


def test_requote_stale_version_conflict(api):
    """PRD 2.9: "A re-quote request must carry `expected_preorder_version`, a
    non-optional field holding the `version` of the target `PreOrder` that the
    client last observed. If `expected_preorder_version` does not equal the
    pre-order's current `version`, the request is rejected with `ERR_STALE_VERSION`
    (HTTP 412)".

    Design: Corner/cross_cutting/requote_stale_version_conflict
    """
    flavor = make_flavor(par_level_ml=300)
    station = make_station()
    po = make_pre_order(flavor["id"], station["id"], quoted_price_cents=4000)
    stale_version = po["version"]  # e.g. 1
    # First re-quote with the fresh version succeeds and advances the version.
    validate_success(api.requote_pre_order(
        po["id"], {"quoted_price_cents": 4500, "expected_preorder_version": stale_version}, MGR), 200)
    # Second re-quote still carrying the now-stale version is rejected.
    res = api.requote_pre_order(
        po["id"], {"quoted_price_cents": 4800, "expected_preorder_version": stale_version}, MGR)
    validate_error(res, "ERR_STALE_VERSION")


def test_requote_correct_version_supersedes_and_bumps(api):
    """PRD 3.6: "A `Manager` re-quotes it, replacing `quoted_price_cents` with a new
    value and incrementing the pre-order's `version` by one."

    Design: Corner/cross_cutting/requote_correct_version_supersedes_and_bumps
    """
    flavor = make_flavor(par_level_ml=300)
    station = make_station()
    po = make_pre_order(flavor["id"], station["id"], quoted_price_cents=4000)
    v1 = po["version"]
    updated = validate_success(api.requote_pre_order(
        po["id"], {"quoted_price_cents": 4500, "expected_preorder_version": v1}, MGR), 200)
    assert updated["quoted_price_cents"] == 4500
    assert updated["version"] == v1 + 1
