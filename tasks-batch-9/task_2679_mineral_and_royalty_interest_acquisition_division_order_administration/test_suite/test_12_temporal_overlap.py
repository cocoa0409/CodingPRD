"""Two occupancy resources with opposite interval conventions: unit and tract."""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.assertions import assert_acreage
from test_helpers.test_users import MANAGER_ALT_HEADERS, OPERATOR_HEADERS

ADJACENT = {
    "allocated_acres": 100.0000,
    "effective_from": "2028-01-01",
    "effective_to": "2029-01-01",
}
OVERLAPPING = {
    "allocated_acres": 100.0000,
    "effective_from": "2027-12-31",
    "effective_to": "2029-01-01",
}


def test_a_single_shared_day_overlaps_the_incumbent_allocation(api):
    """2027-12-31 is still inside [2026-01-01, 2028-01-01), so the commit fails.

    PRD: "The new interval must not overlap the interval of any existing
    allocation on the same unit-and-tract pairing whose `allocation_status` is
    `ACTIVE` or `PUGH_RELEASED`; an overlap is `ERR_ALLOCATION_INTERVAL_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/unit_tract_allocation_half_open_intervals_allow_adjacency_reject_overlap
    """
    world = fx.unit_with_allocation_ready(api)

    response = api.create_allocation(
        f.allocation_payload(world["unit"]["id"], world["tract"]["id"], **OVERLAPPING),
        OPERATOR_HEADERS,
    )

    validate_error(response, "ERR_ALLOCATION_INTERVAL_OVERLAP", 409)


def test_rejected_commit_draws_no_acreage_from_the_unit(api):
    """The unit keeps its one allocation and its 960.0000 unallocated acres.

    PRD: "Committing acreage draws it out of `unallocated_acres`; a pugh release
    moves exactly `released_acres` from the allocation back to
    `unallocated_acres`, so the identity also holds mid-cycle; terminating an
    allocation returns the whole of its remaining `allocated_acres` and drops the
    row out of the summed status set."

    PRD: "A unit is created with `unallocated_acres` equal to `unit_gross_acres`,
    which is what makes the identity hold from the first instant."

    Design: Difficulty/resource_temporal_overlap/unit_tract_allocation_half_open_intervals_allow_adjacency_reject_overlap
    """
    world = fx.unit_with_allocation_ready(api)

    api.create_allocation(
        f.allocation_payload(world["unit"]["id"], world["tract"]["id"], **OVERLAPPING),
        OPERATOR_HEADERS,
    )

    unit = fx.read_unit(api, world["unit"]["id"])
    assert unit["active_allocation_count"] == 1
    assert_acreage(unit["unallocated_acres"], "960.0000", "unallocated_acres")


def test_an_interval_starting_where_the_incumbent_ends_is_accepted(api):
    """Exact adjacency on 2028-01-01 is legal and draws its own acreage.

    PRD: "Because the interval is half-open, exact adjacency is explicitly legal:
    a new allocation whose `effective_from` equals an existing allocation's
    `effective_to` does not conflict."

    Design: Difficulty/resource_temporal_overlap/unit_tract_allocation_half_open_intervals_allow_adjacency_reject_overlap
    """
    world = fx.unit_with_allocation_ready(api)

    adjacent = fx.create_allocation(
        api, world["unit"]["id"], world["tract"]["id"], **ADJACENT
    )

    assert adjacent["allocation_status"] == "ACTIVE"
    assert_acreage(adjacent["allocated_acres"], "100.0000", "allocated_acres")
    unit = fx.read_unit(api, world["unit"]["id"])
    assert unit["active_allocation_count"] == 2
    assert_acreage(unit["unallocated_acres"], "860.0000", "unallocated_acres")


def _tract_with_incumbent_psa_and_second_accepted_offer(api):
    """One certified tract carrying a 0.5 share UNDER_PSA and a 0.25 share ACCEPTED."""
    world = fx.psa_ready(api)
    second = fx.create_interest(
        api,
        world["tract"]["id"],
        world["owner"]["id"],
        seller_share_fraction=0.25,
    )
    fx.create_valuation(api, second["id"])
    second_offer = fx.create_offer(api, second["id"], expires_on="2026-11-01")
    second_offer = fx.accept_offer(api, second_offer["id"], world["owner"]["id"])
    world["second_interest"] = second
    world["second_offer"] = second_offer
    return world


def test_incumbent_window_runs_forty_five_days_plus_a_thirty_day_buffer(api):
    """curative_deadline 2026-09-15 and window_end_with_buffer 2026-10-15.

    PRD: "Its `curative_deadline` is `effective_date` advanced by `curative_days`
    days, and is the last date, inclusive, on which any defect activity is
    permitted. Its `window_end_with_buffer` is `curative_deadline` advanced by a
    further thirty days, and is the inclusive end of the agreement's exclusive
    occupancy window on the tract."

    Design: Difficulty/resource_temporal_overlap/psa_tract_occupancy_closed_window_with_buffer_rejects_touching_endpoints
    """
    world = _tract_with_incumbent_psa_and_second_accepted_offer(api)

    incumbent = fx.read_psa(api, world["psa"]["id"])

    assert incumbent["effective_date"] == "2026-08-01"
    assert incumbent["curative_deadline"] == "2026-09-15"
    assert incumbent["window_end_with_buffer"] == "2026-10-15"
    assert_acreage(world["interest"]["net_mineral_acres"], "40.0000", "first net_mineral_acres")
    assert_acreage(
        world["second_interest"]["net_mineral_acres"], "20.0000", "second net_mineral_acres"
    )


def test_a_second_agreement_touching_the_buffered_end_date_is_rejected(api):
    """Starting exactly on 2026-10-15 intersects the incumbent's closed window.

    PRD: "That span must not intersect the equivalent span of any other agreement
    on the same `tract_id` whose `psa_status` is `EXECUTED` or `TERMINATED`. Two
    spans that merely touch at a single endpoint count as intersecting and are
    rejected."

    Design: Difficulty/resource_temporal_overlap/psa_tract_occupancy_closed_window_with_buffer_rejects_touching_endpoints
    """
    world = _tract_with_incumbent_psa_and_second_accepted_offer(api)
    version = fx.interest_version(api, world["second_interest"]["id"])

    response = api.create_psa(
        f.psa_payload(
            world["second_offer"]["id"],
            version,
            effective_date="2026-10-15",
            curative_days=30,
        ),
        MANAGER_ALT_HEADERS,
    )

    validate_error(response, "ERR_PSA_WINDOW_CONFLICT", 409)
    assert fx.read_interest(api, world["second_interest"]["id"])["interest_status"] == "OFFERED"
    assert fx.read_offer(api, world["second_offer"]["id"])["offer_status"] == "ACCEPTED"


def test_the_day_after_the_buffered_end_date_is_available(api):
    """2026-10-16 clears the incumbent window and the agreement executes.

    PRD: "The two independent state dimensions are initialised to `CURATIVE_OPEN`
    and `UNFUNDED`, the derived `psa_status` reads `EXECUTED`,
    `created_by_user_id` is stamped from the acting `X-User-ID`, and
    `wire_reference`, `recording_county`, `recorded_book_page` and
    `recording_date` are all null. The interest moves to `UNDER_PSA` and its
    `version` increments by 1."

    Design: Difficulty/resource_temporal_overlap/psa_tract_occupancy_closed_window_with_buffer_rejects_touching_endpoints
    """
    world = _tract_with_incumbent_psa_and_second_accepted_offer(api)
    version = fx.interest_version(api, world["second_interest"]["id"])

    second_psa = validate_success(
        api.create_psa(
            f.psa_payload(
                world["second_offer"]["id"],
                version,
                effective_date="2026-10-16",
                curative_days=30,
            ),
            MANAGER_ALT_HEADERS,
        ),
        201,
    )

    assert second_psa["effective_date"] == "2026-10-16"
    assert second_psa["psa_status"] == "EXECUTED"
    assert fx.read_interest(api, world["second_interest"]["id"])["interest_status"] == "UNDER_PSA"
