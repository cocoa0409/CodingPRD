"""Listing defaults, body-reference resolution and the conditional pugh action."""

from prd_bench_local_runner.testing import (
    NON_EXISTENT_UUID,
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.assertions import assert_acreage, assert_pagination_meta
from test_helpers.test_users import ANALYST_HEADERS, OPERATOR_HEADERS

THREE_TX_TRACTS = (
    {"county": "Reeves", "gross_acres": 640.0000, "operator_activity_tier": "HIGH"},
    {"county": "Loving", "gross_acres": 320.0000, "operator_activity_tier": "MODERATE"},
    {"county": "Ward", "gross_acres": 160.0000, "operator_activity_tier": "LOW"},
)


def test_the_tract_list_applies_its_declared_pagination_defaults(api):
    """An unqualified list returns all three rows under limit 10 / offset 0.

    PRD: "Every collection-listing endpoint is paginated with the same two query
    parameters. `limit` controls page size: it defaults to 10, must be at least 1,
    and must not exceed 100. `offset` controls the starting position: it defaults to
    0 and must not be negative."

    Design: Corner/endpoints/list_tracts_applies_pagination_defaults_and_rejects_out_of_range_limits
    """
    for spec in THREE_TX_TRACTS:
        fx.create_tract(api, **spec)

    items, meta = validate_paginated(api.list_tracts(ANALYST_HEADERS, {"state_code": "TX"}))

    assert len(items) == 3
    assert_pagination_meta(meta, 10, 0, total_count=3, has_more=False)

    tail, tail_meta = validate_paginated(
        api.list_tracts(ANALYST_HEADERS, {"state_code": "TX", "limit": 2, "offset": 2})
    )
    assert len(tail) == 1
    assert_pagination_meta(tail_meta, 2, 2, total_count=3, has_more=False)


def test_pagination_arguments_outside_their_bounds_are_rejected(api):
    """101 and 0 are out of range for limit, -1 is out of range for offset; 100 is fine.

    PRD: "A `limit` outside its bounds or a negative `offset` is rejected with
    `ERR_INVALID_REQUEST` (HTTP 400)."

    Design: Corner/endpoints/list_tracts_applies_pagination_defaults_and_rejects_out_of_range_limits
    """
    for spec in THREE_TX_TRACTS:
        fx.create_tract(api, **spec)

    validate_error(api.list_tracts(ANALYST_HEADERS, {"limit": 101}), "ERR_INVALID_REQUEST", 400)
    validate_error(api.list_tracts(ANALYST_HEADERS, {"limit": 0}), "ERR_INVALID_REQUEST", 400)
    validate_error(api.list_tracts(ANALYST_HEADERS, {"offset": -1}), "ERR_INVALID_REQUEST", 400)

    items, meta = validate_paginated(api.list_tracts(ANALYST_HEADERS, {"limit": 100}))
    assert len(items) == 3
    assert_pagination_meta(meta, 100, 0, total_count=3, has_more=False)


def test_an_allocation_names_which_of_its_two_references_is_missing(api):
    """A bad unit_id is a unit 404 and a bad tract_id is a tract 404.

    PRD: "An unresolvable reference produces the not-found code of the referenced
    kind, not a generic bad-request."

    Design: Corner/endpoints/allocation_link_requires_both_unit_and_tract_and_reports_which_is_missing
    """
    tract = fx.create_certified_tract(api)
    unit = fx.create_unit(api)

    bad_unit = api.create_allocation(
        f.allocation_payload(NON_EXISTENT_UUID, tract["id"]), OPERATOR_HEADERS
    )
    bad_tract = api.create_allocation(
        f.allocation_payload(unit["id"], NON_EXISTENT_UUID), OPERATOR_HEADERS
    )

    validate_error(bad_unit, "ERR_UNIT_NOT_FOUND", 404)
    validate_error(bad_tract, "ERR_TRACT_NOT_FOUND", 404)

    unchanged = fx.read_unit(api, unit["id"])
    assert_acreage(unchanged["unallocated_acres"], "1280.0000", "unallocated_acres")
    assert unchanged["active_allocation_count"] == 0


def test_a_resolvable_allocation_draws_its_acreage_out_of_the_unit(api):
    """320 committed acres leave 960.0000 unallocated behind one ACTIVE row.

    PRD: "Committing acreage draws it out of `unallocated_acres`; a pugh release
    moves exactly `released_acres` from the allocation back to `unallocated_acres`,
    so the identity also holds mid-cycle"

    Design: Corner/endpoints/allocation_link_requires_both_unit_and_tract_and_reports_which_is_missing
    """
    tract = fx.create_certified_tract(api)
    unit = fx.create_unit(api)

    allocation = validate_success(
        api.create_allocation(f.allocation_payload(unit["id"], tract["id"]), OPERATOR_HEADERS),
        201,
    )

    assert allocation["allocation_status"] == "ACTIVE"
    assert_acreage(allocation["released_acres"], "0.0000", "released_acres")
    after = fx.read_unit(api, unit["id"])
    assert_acreage(after["unallocated_acres"], "960.0000", "unallocated_acres")
    assert after["active_allocation_count"] == 1


def test_a_pugh_release_needs_the_clause_switched_on_first(api):
    """Without pugh_clause_active the release is not applicable; the amendment enables it.

    PRD: "The unit's `pugh_clause_active` must be true, or the request is
    `ERR_PUGH_CLAUSE_NOT_APPLICABLE`."

    Design: Corner/endpoints/pugh_release_on_a_unit_without_a_pugh_clause_is_not_applicable
    """
    world = fx.unit_with_allocation_ready(api)
    fx.set_clock(api, "2027-06-01T00:00:00Z")

    refused = api.pugh_release(world["allocation"]["id"], OPERATOR_HEADERS)

    validate_error(refused, "ERR_PUGH_CLAUSE_NOT_APPLICABLE", 409)
    still_active = fx.read_allocation(api, world["allocation"]["id"])
    assert still_active["allocation_status"] == "ACTIVE"
    assert_acreage(still_active["allocated_acres"], "320.0000", "allocated_acres")
    assert_acreage(still_active["released_acres"], "0.0000", "released_acres")

    validate_success(
        api.update_unit(
            world["unit"]["id"],
            {"pugh_clause_active": True, "pugh_deadline": "2026-12-31"},
            OPERATOR_HEADERS,
        ),
        200,
    )
    released = fx.pugh_release(api, world["allocation"]["id"])
    assert released["allocation_status"] == "PUGH_RELEASED"


def test_the_enabled_release_hands_back_one_dead_depth_of_three(api):
    """320.0000 splits into 213.3333 retained and 106.6667 returned to the unit.

    PRD: "The retained figure is the allocation's `allocated_acres` multiplied by
    `producing_depth_count` and divided by `total_depth_count`, rounded half-up to 4
    decimal places."

    Design: Corner/endpoints/pugh_release_on_a_unit_without_a_pugh_clause_is_not_applicable
    """
    world = fx.unit_with_allocation_ready(
        api, unit_overrides={"pugh_clause_active": True, "pugh_deadline": "2026-12-31"}
    )
    fx.set_clock(api, "2027-06-01T00:00:00Z")

    released = fx.pugh_release(api, world["allocation"]["id"])

    assert released["allocation_status"] == "PUGH_RELEASED"
    assert_acreage(released["allocated_acres"], "213.3333", "allocated_acres")
    assert_acreage(released["released_acres"], "106.6667", "released_acres")
    unit = fx.read_unit(api, world["unit"]["id"])
    assert_acreage(unit["unallocated_acres"], "1066.6667", "unallocated_acres")
    assert unit["active_allocation_count"] == 1
