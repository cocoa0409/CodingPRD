"""Collections, pagination bounds and the shape of the reference graph.

The pagination half pins `total_count` to the filtered-but-unpaginated set and
refuses out-of-band bounds rather than clamping them.  The reference half pins
the graph: a child's parent comes from the URL, the allocation junction carries
two buyers on one deal, the guarantor edge stays a forest, and a wrong
identifier names the family it failed to find.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from prd_bench_local_runner.testing import (  # noqa: E402
    get_success_data,
    validate_error,
)

from test_helpers import assertions as asserts  # noqa: E402
from test_helpers import factories as f  # noqa: E402
from test_helpers import fixtures as fx  # noqa: E402
from test_helpers.api_errors import ApiErrorId  # noqa: E402
from test_helpers.constants import UNKNOWN_UUIDS  # noqa: E402
from test_helpers.test_users import (  # noqa: E402
    CREDIT_OFFICER,
    ORIGINATOR,
    SETTLEMENT_ANALYST,
    make_offtaker_rep_headers,
)

DEFAULT_LIMIT = 10
DEFAULT_OFFSET = 0
MAX_LIMIT = 100


def _three_settlement_points(api):
    """Two CAISO points and one ERCOT hub, the last registered by an analyst."""
    hub = fx.create_hub(api, name="SP15 EZ GEN HUB")
    node = fx.create_node(api, name="KRAMER JUNCTION 1N")
    ercot = get_success_data(
        api.create_pricing_node(f.hub_payload(name="ERCOT WEST HUB",
                                              iso="ERCOT"),
                                SETTLEMENT_ANALYST), 201)
    return [hub, node, ercot]


def test_01_total_count_survives_paging_and_follows_the_filter(api):
    """Two pages of a three-row collection both report the same unpaginated
    count, and a filtered request counts only what the filter admits.

    "Every list endpoint accepts two optional query parameters. `limit` controls
    page size: its default is 10, its minimum is 1 and its maximum is 100.
    `offset` controls the starting position: its default is 0 and its minimum is
    0."

    "Every list response reports `limit`, `offset`, `total_count` and `has_more`
    inside `meta`, where `total_count` is the number of rows matching the filters
    before pagination is applied and `has_more` indicates whether any matching row
    remains beyond the current page."

    Design: Corner/entities/pricing_node_listing_paginates_with_total_count_and_has_more
    """
    nodes = _three_settlement_points(api)
    buyer = fx.create_offtaker(api)
    reader = make_offtaker_rep_headers(buyer["id"])

    first_page, meta = fx.list_all(
        api.list_pricing_nodes(reader, params={"limit": 2, "offset": 0}))
    assert len(first_page) == 2, first_page
    asserts.assert_page_meta(meta, total_count=3, limit=2, offset=0,
                             has_more=True)

    second_page, meta = fx.list_all(
        api.list_pricing_nodes(reader, params={"limit": 2, "offset": 2}))
    assert len(second_page) == 1, second_page
    asserts.assert_page_meta(meta, total_count=3, limit=2, offset=2,
                             has_more=False)

    # The two pages between them cover the collection exactly once.
    paged_ids = asserts.ids_of(first_page) + asserts.ids_of(second_page)
    assert sorted(paged_ids) == sorted(asserts.ids_of(nodes)), paged_ids

    # total_count reflects the filtered set, not the whole collection, and the
    # omitted bounds fall back to their declared defaults.
    filtered, meta = fx.list_all(api.list_pricing_nodes(
        reader, params={"iso": "CAISO", "settlement_point_type": "HUB"}))
    assert len(filtered) == 1, filtered
    assert filtered[0]["name"] == "SP15 EZ GEN HUB", filtered
    asserts.assert_page_meta(meta, total_count=1, limit=DEFAULT_LIMIT,
                            offset=DEFAULT_OFFSET, has_more=False)


def test_02_out_of_band_pagination_bounds_are_refused_not_clamped(api):
    """A one-row collection would hide silent clamping, so the bounds are pinned
    directly: 101, 0 and a negative offset are refused while 100 exactly is not.

    "A `limit` below 1 or above 100, or a negative `offset`, is a request-shape
    violation and yields `ERR_INVALID_REQUEST`."

    Design: Corner/entities/pricing_node_listing_limit_above_max_returns_invalid_request
    """
    fx.create_hub(api, name="SP15 EZ GEN HUB")

    too_large = api.list_pricing_nodes(ORIGINATOR, params={"limit": 101})
    validate_error(too_large, ApiErrorId.ERR_INVALID_REQUEST.value, 400)
    asserts.assert_error_envelope(too_large)

    too_small = api.list_pricing_nodes(ORIGINATOR, params={"limit": 0})
    validate_error(too_small, ApiErrorId.ERR_INVALID_REQUEST.value, 400)

    negative = api.list_pricing_nodes(ORIGINATOR, params={"offset": -1})
    validate_error(negative, ApiErrorId.ERR_INVALID_REQUEST.value, 400)

    # Exactly at the declared maximum is allowed.
    rows, meta = fx.list_all(
        api.list_pricing_nodes(ORIGINATOR, params={"limit": MAX_LIMIT}))
    assert len(rows) == 1, rows
    asserts.assert_page_meta(meta, total_count=1, limit=MAX_LIMIT,
                            offset=DEFAULT_OFFSET, has_more=False)


# ---------------------------------------------------------------------------
# The allocation junction: parent from the URL, two buyers on one deal.
# ---------------------------------------------------------------------------

CONTRACTED_MW = 25.000
FIRST_SLICE_MW = 15.000
SECOND_SLICE_MW = 10.000
FIRST_SHARE_PCT = 60.0000
SECOND_SHARE_PCT = 40.0000
SOLO_SLICE_MW = 10.000
SOLO_SHARE_PCT = 40.0000


def _deal_admitting_allocations(api, product_type="VIRTUAL_CFD"):
    """A `TERM_SHEET_ISSUED` deal of 25.000 MW settling at the hub."""
    hub = fx.create_hub(api)
    node = fx.create_node(api)
    buyer = fx.create_qualified_offtaker(api)
    project = fx.create_project(api, node["id"],
                                cod_target_date="2029-06-01T00:00:00Z")
    deal = fx.create_deal(api, project["id"], buyer["id"], hub["id"],
                          product_type=product_type,
                          contracted_mw=CONTRACTED_MW, term_years=12)
    round_row = fx.table_round(api, deal["id"])
    return {"hub": hub, "node": node, "buyer": buyer, "project": project,
            "deal": fx.read_deal(api, deal["id"]), "round": round_row}


def test_03_an_allocation_belongs_to_the_deal_in_its_url_or_to_no_deal_at_all(api):
    """The identical body under an unknown deal is a 404 about the deal, and
    under the real deal the child carries the URL's parent.

    "Path existence: every identifier appearing in the request path must resolve
    to a live row, and the identifiers are resolved strictly left to right — the
    outer segment first."

    "A new slice is created with `status` `PROPOSED`, `confirmed_at` null,
    `deal_id` taken from the path rather than the payload, and
    `created_by_user_id` stamped from the proposing operator. Its
    `allocation_share_pct` is one hundred multiplied by `allocated_mw` divided by
    the deal's `contracted_mw`, rounded half up to four decimal places."

    Design: Corner/entities/allocation_requires_existing_parent_deal_and_lists_under_it
    """
    chain = _deal_admitting_allocations(api)
    deal_id = chain["deal"]["id"]
    buyer_id = chain["buyer"]["id"]
    token = chain["deal"]["version"]
    body = f.allocation_payload(buyer_id, SOLO_SLICE_MW, token)

    orphan = api.create_allocation(UNKNOWN_UUIDS["deal"], body, ORIGINATOR)
    validate_error(orphan, ApiErrorId.ERR_DEAL_NOT_FOUND.value, 404)
    asserts.assert_error_envelope(orphan)

    rows, meta = fx.list_all(api.list_allocations(deal_id, ORIGINATOR))
    assert meta["total_count"] == 0, meta
    assert rows == [], rows

    created = api.create_allocation(deal_id, body, ORIGINATOR)
    slice_row = get_success_data(created, 201)
    assert slice_row["deal_id"] == deal_id, slice_row
    assert slice_row["offtaker_id"] == buyer_id, slice_row
    assert slice_row["status"] == "PROPOSED", slice_row
    assert slice_row["confirmed_at"] is None, slice_row
    asserts.assert_share_pct(slice_row["allocation_share_pct"], SOLO_SHARE_PCT)
    asserts.assert_mw(slice_row["allocated_mw"], SOLO_SLICE_MW, "allocated_mw")

    # Reachable from the deal side and from the buyer side of the junction.
    rows, meta = fx.list_all(api.list_allocations(deal_id, ORIGINATOR))
    assert meta["total_count"] == 1, meta
    assert rows[0]["id"] == slice_row["id"], rows

    rows, meta = fx.list_all(
        api.list_offtaker_allocations(buyer_id, ORIGINATOR))
    assert meta["total_count"] == 1, meta
    assert rows[0]["id"] == slice_row["id"], rows
    assert rows[0]["deal_id"] == deal_id, rows


def test_04_two_buyers_hold_live_slices_of_the_same_agreement(api):
    """The junction carries both buyers at once: the deal side sees two rows, each
    buyer sees only its own, and the two shares sum to exactly one hundred.

    "An aggregated arrangement lets one agreement carry several corporate buyers,
    each taking a slice of the contracted capacity."

    "Equality is allowed, and confirming exactly to the contracted total drives
    `unallocated_mw` to 0.000."

    Design: Corner/entities/allocation_junction_links_two_offtakers_to_one_deal
    """
    chain = _deal_admitting_allocations(api, product_type="AGGREGATED")
    deal_id = chain["deal"]["id"]
    first_buyer = chain["buyer"]["id"]
    second_buyer = fx.create_qualified_offtaker(
        api, legal_name="Aurora Compute Inc",
        registry_account_id="WREGIS-ACC-00902")["id"]

    first = fx.propose_allocation(api, deal_id, first_buyer, FIRST_SLICE_MW)
    second = fx.propose_allocation(api, deal_id, second_buyer, SECOND_SLICE_MW,
                                   joint_and_several=True)
    assert first["joint_and_several"] is False, first
    assert second["joint_and_several"] is True, second

    first = fx.confirm_allocation(api, first["id"], first_buyer)
    second = fx.confirm_allocation(api, second["id"], second_buyer)
    for row in (first, second):
        assert row["status"] == "CONFIRMED", row
        asserts.assert_instant_equals(row["confirmed_at"], fx.INITIAL_CLOCK,
                                      "confirmed_at")
    asserts.assert_share_pct(first["allocation_share_pct"], FIRST_SHARE_PCT)
    asserts.assert_share_pct(second["allocation_share_pct"], SECOND_SHARE_PCT)
    assert (float(first["allocation_share_pct"])
            + float(second["allocation_share_pct"])) == 100.0, (
        "a fully subscribed deal's shares sum to one hundred")

    deal = fx.read_deal(api, deal_id)
    asserts.assert_mw(deal["confirmed_allocated_mw"], CONTRACTED_MW,
                      "confirmed_allocated_mw")
    asserts.assert_mw(deal["unallocated_mw"], 0.000, "unallocated_mw")

    rows, meta = fx.list_all(api.list_allocations(deal_id, ORIGINATOR))
    assert meta["total_count"] == 2, meta
    assert sorted(asserts.ids_of(rows)) == sorted([first["id"], second["id"]])

    live, meta = fx.list_all(
        api.list_allocations(deal_id, ORIGINATOR, params={"status": "CONFIRMED"}))
    assert meta["total_count"] == 2, meta

    for buyer_id, own_slice in ((first_buyer, first), (second_buyer, second)):
        mine, meta = fx.list_all(
            api.list_offtaker_allocations(buyer_id, ORIGINATOR))
        assert meta["total_count"] == 1, meta
        assert mine[0]["id"] == own_slice["id"], mine
        assert mine[0]["deal_id"] == deal_id, mine


# ---------------------------------------------------------------------------
# The guarantor edge is self-referential, and must stay a forest.
# ---------------------------------------------------------------------------

PARENT_SCORE = 92.60
PARENT_LIMIT_USD = 25000000.00
CHILD_SCORE = 83.70
CHILD_SUSTAINABILITY = 10.00
CHILD_LIMIT_USD = 1500000.00


def _guarantor_pair(api):
    """`AR -> AH -> null`: a QUALIFIED parent and a scored, supported child."""
    parent = fx.create_qualified_offtaker(
        api, anchor=False, legal_name="Aurora Holdings PLC", credit_rating="AA",
        rating_agency="SP", reported_ebitda_usd=500000000.00,
        net_debt_to_ebitda=1.0, disclosure_framework="CDP_AND_TCFD",
        has_science_based_target=True, re100_member=True, scope2_target_year=2030)
    child = fx.create_offtaker(
        api, legal_name="Aurora Retail Sub", credit_rating="BB",
        rating_agency="SP", reported_ebitda_usd=30000000.00,
        net_debt_to_ebitda=6.0, disclosure_framework="CDP_ONLY",
        parent_guarantor_offtaker_id=parent["id"])
    child = fx.submit_offtaker(api, child["id"])
    return parent, child


def test_05_re_parenting_that_would_close_a_cycle_changes_nothing(api):
    """Pointing the parent at its own child, and at itself, are both refused; an
    unknown guarantor fails earlier still, as an existence failure.

    "A supplied `parent_guarantor_offtaker_id` re-parents the guarantor edge
    **before** any scoring runs, and must both exist and satisfy the forest rule —
    neither equal to this buyer's own identifier nor closing a cycle when the
    upward chain is walked — or the request is refused with
    `ERR_GUARANTOR_CYCLE`."

    "Body foreign keys are validated in the order in which the endpoint declares
    its input fields, and always after path existence — so a request with both a
    bad path identifier and a bad body foreign key returns the path entity's
    404."

    Design: Corner/entities/offtaker_guarantor_reparenting_cycle_rejected
    """
    parent, child = _guarantor_pair(api)
    parent = fx.read_offtaker(api, parent["id"])

    asserts.assert_score(parent["credit_score"], PARENT_SCORE, "credit_score")
    assert parent["credit_tier"] == "PRIME", parent
    assert parent["credit_score_variant"] == "STANDALONE", parent
    assert parent["parent_guarantor_offtaker_id"] is None, parent
    asserts.assert_money(parent["unsecured_credit_limit_usd"], PARENT_LIMIT_USD,
                         "unsecured_credit_limit_usd")

    # The child inherits the notched rating and the better leverage, and keeps
    # its own disclosure component.
    asserts.assert_score(child["credit_score"], CHILD_SCORE, "credit_score")
    assert child["credit_score_variant"] == "GUARANTOR_SUPPORTED", child
    assert child["credit_tier"] == "PRIME", child
    asserts.assert_score(child["sustainability_score"], CHILD_SUSTAINABILITY,
                         "sustainability_score")
    asserts.assert_money(child["unsecured_credit_limit_usd"], CHILD_LIMIT_USD,
                         "unsecured_credit_limit_usd")

    two_node_cycle = api.change_offtaker_rating(
        parent["id"],
        f.rating_change_payload("AA", parent_guarantor_offtaker_id=child["id"]),
        CREDIT_OFFICER)
    validate_error(two_node_cycle, ApiErrorId.ERR_GUARANTOR_CYCLE.value, 422)
    asserts.assert_error_envelope(two_node_cycle)

    self_cycle = api.change_offtaker_rating(
        parent["id"],
        f.rating_change_payload("AA",
                                parent_guarantor_offtaker_id=parent["id"]),
        CREDIT_OFFICER)
    validate_error(self_cycle, ApiErrorId.ERR_GUARANTOR_CYCLE.value, 422)

    # A guarantor that does not exist fails the existence check first.
    unknown_guarantor = api.change_offtaker_rating(
        parent["id"],
        f.rating_change_payload(
            "AA", parent_guarantor_offtaker_id=UNKNOWN_UUIDS["guarantor"]),
        CREDIT_OFFICER)
    validate_error(unknown_guarantor, ApiErrorId.ERR_OFFTAKER_NOT_FOUND.value,
                   404)

    # Nothing partial leaked from any of the three refusals.
    parent_after = fx.read_offtaker(api, parent["id"])
    assert parent_after["parent_guarantor_offtaker_id"] is None, parent_after
    asserts.assert_score(parent_after["credit_score"], PARENT_SCORE,
                         "credit_score")
    assert parent_after["version"] == parent["version"], parent_after
    assert parent_after["qualification_status"] == "QUALIFIED", parent_after

    child_after = fx.read_offtaker(api, child["id"])
    asserts.assert_score(child_after["credit_score"], CHILD_SCORE,
                         "credit_score")
    assert child_after["credit_score_variant"] == "GUARANTOR_SUPPORTED", \
        child_after
    assert child_after["version"] == child["version"], child_after
    assert child_after["parent_guarantor_offtaker_id"] == parent["id"], \
        child_after


def test_06_each_family_of_identifier_has_its_own_not_found_code(api):
    """Five well-formed but unknown identifiers produce five different codes, and
    the one identifier that does exist still resolves.

    "The error is the specific per-entity not-found code:
    `ERR_PRICING_NODE_NOT_FOUND`, `ERR_OFFTAKER_NOT_FOUND`,
    `ERR_PROJECT_NOT_FOUND`, `ERR_DEAL_NOT_FOUND`, `ERR_ALLOCATION_NOT_FOUND`,
    `ERR_ROUND_NOT_FOUND`, `ERR_CREDIT_SUPPORT_NOT_FOUND`,
    `ERR_CONDITION_PRECEDENT_NOT_FOUND`, `ERR_SETTLEMENT_PERIOD_NOT_FOUND`,
    `ERR_ATTRIBUTE_BATCH_NOT_FOUND` or `ERR_RISK_EVENT_NOT_FOUND`."

    Design: Corner/entities/path_id_not_found_returns_entity_scoped_404_per_family
    """
    buyer = fx.create_anchor_offtaker(api)

    misses = [
        (api.get_pricing_node(UNKNOWN_UUIDS["pricing_node"], ORIGINATOR),
         ApiErrorId.ERR_PRICING_NODE_NOT_FOUND.value),
        (api.get_offtaker(UNKNOWN_UUIDS["offtaker"], ORIGINATOR),
         ApiErrorId.ERR_OFFTAKER_NOT_FOUND.value),
        (api.get_project(UNKNOWN_UUIDS["project"], ORIGINATOR),
         ApiErrorId.ERR_PROJECT_NOT_FOUND.value),
        (api.get_deal(UNKNOWN_UUIDS["deal"], ORIGINATOR),
         ApiErrorId.ERR_DEAL_NOT_FOUND.value),
        (api.get_settlement_period(UNKNOWN_UUIDS["settlement_period"],
                                   SETTLEMENT_ANALYST),
         ApiErrorId.ERR_SETTLEMENT_PERIOD_NOT_FOUND.value),
    ]
    for response, expected_error_id in misses:
        validate_error(response, expected_error_id, 404)
        body = asserts.assert_error_envelope(response)
        assert body["message"], f"{expected_error_id} must carry a message"

    # The five 404s are about the identifiers, not about the endpoints.
    found = get_success_data(api.get_offtaker(buyer["id"], ORIGINATOR), 200)
    assert found["id"] == buyer["id"], found
