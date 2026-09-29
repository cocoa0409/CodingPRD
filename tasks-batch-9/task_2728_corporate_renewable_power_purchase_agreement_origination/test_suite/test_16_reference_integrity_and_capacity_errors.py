"""Reference integrity, the guarantor forest and the project's headroom.

Every refusal below is a *specific* one: a 404 that names the entity of the
offending field rather than a generic not-found, a cycle check that climbs the
whole upward chain rather than glancing at the immediate parent, a tier gate
that answers where a qualification gate does not apply, and a capacity gate
whose ledger counts only the deals the PRD says it counts.  Each test also
proves the refusals were total — no partial write, no consumed version.
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
    DEAL_COMMITTEE,
    ORIGINATOR,
    REGISTRY_AGENT,
    SETTLEMENT_ANALYST,
    make_offtaker_rep_headers,
)

#: The nameplate of the standard project fixture, and the ledger it starts on.
PROJECT_CAPACITY_MW = 100.000

#: The three body foreign keys deal creation carries, each paired with the
#: not-found code of the entity that field references.
DEAL_BODY_REFERENCES = [
    ("project_id", UNKNOWN_UUIDS["project"],
     ApiErrorId.ERR_PROJECT_NOT_FOUND),
    ("anchor_offtaker_id", UNKNOWN_UUIDS["offtaker"],
     ApiErrorId.ERR_OFFTAKER_NOT_FOUND),
    ("settlement_point_id", UNKNOWN_UUIDS["pricing_node"],
     ApiErrorId.ERR_PRICING_NODE_NOT_FOUND),
]


def test_01_each_body_foreign_key_names_its_own_entitys_not_found(api):
    """One endpoint carries three references, and each broken one answers with
    the 404 of the entity it points at while the other two stay valid.

    "Body foreign-key existence: `project_id`, `anchor_offtaker_id`,
    `settlement_point_id`, `offtaker_id`, `guarantor_offtaker_id`,
    `parent_guarantor_offtaker_id` and `transferred_to_offtaker_id` must each
    resolve to a live row, again returning the referenced entity's own not-found
    code."

    "This applies to buyer creation, project creation, deal creation, allocation
    proposal, credit-support registration and attribute transfer."

    "Thereafter `contracted_mw` is always the sum of `contracted_mw` over the
    project's deals whose `status` is `EXECUTED` or `EFFECTIVE`, and
    `available_mw` is `capacity_mw` less `contracted_mw`."

    Design: Corner/errors/deal_create_body_references_return_the_owning_entity_not_found
    """
    node = fx.create_node(api)
    buyer = fx.create_qualified_offtaker(api)
    project = fx.create_project(api, node["id"])

    live = {"project_id": project["id"], "anchor_offtaker_id": buyer["id"],
            "settlement_point_id": node["id"]}
    for field, unknown, expected in DEAL_BODY_REFERENCES:
        references = dict(live)
        references[field] = unknown
        response = api.create_deal(
            f.deal_payload(references["project_id"],
                           references["anchor_offtaker_id"],
                           references["settlement_point_id"],
                           product_type="VIRTUAL_CFD", term_years=12),
            ORIGINATOR)
        validate_error(response, expected.value, 404)
        # The envelope of a 404 is the same envelope as every other error.
        asserts.assert_error_envelope(response)

    # Exactly one limb was ever at fault, and none of the three wrote anything.
    _, meta = fx.list_all(api.list_deals(ORIGINATOR))
    assert meta["total_count"] == 0, meta
    ledger = fx.read_project(api, project["id"])
    asserts.assert_mw(ledger["contracted_mw"], 0.000, "contracted_mw")
    asserts.assert_mw(ledger["available_mw"], PROJECT_CAPACITY_MW,
                      "available_mw")
    assert ledger["version"] == project["version"] == 1, ledger


def test_02_eight_sub_resource_families_resolve_their_own_path_404(api):
    """Eight otherwise-legal calls addressed at eight unknown top-level ids each
    answer with their own family's 404, ahead of the counterparty rung and ahead
    of the stale-version rung.

    "Path existence: every identifier appearing in the request path must resolve
    to a live row, and the identifiers are resolved strictly left to right — the
    outer segment first."

    "The system evaluates its checks in a strict ascending priority order and
    stops at the first violation; no later check is evaluated, and no error is
    aggregated with another."

    "Buyer-side counterparty ownership for an `OfftakerRep` —
    `ERR_NOT_DEAL_COUNTERPARTY`."

    "Optimistic concurrency: the supplied expected parent version equals the
    parent's current `version` — `ERR_STALE_VERSION`."

    Design: Corner/errors/unknown_path_ids_return_not_found_for_each_owning_entity
    """
    node = fx.create_node(api)
    buyer = fx.create_qualified_offtaker(api)
    project = fx.create_project(api, node["id"])
    deal = fx.create_deal(api, project["id"], buyer["id"], node["id"],
                          product_type="VIRTUAL_CFD", term_years=12)
    deal_id = deal["id"]
    current_token = deal["version"]
    buyer_rep = make_offtaker_rep_headers(buyer["id"])

    # Each call is complete, well-typed and made by a permitted role; the
    # credit-support post even carries a genuinely current version token.
    attempts = [
        (api.get_deal(UNKNOWN_UUIDS["deal"], ORIGINATOR),
         ApiErrorId.ERR_DEAL_NOT_FOUND),
        (api.decide_allocation(UNKNOWN_UUIDS["allocation"],
                               f.allocation_decision_payload("CONFIRM"),
                               buyer_rep),
         ApiErrorId.ERR_ALLOCATION_NOT_FOUND),
        (api.respond_to_round(UNKNOWN_UUIDS["round"],
                              f.round_response_payload("ACCEPT"), buyer_rep),
         ApiErrorId.ERR_ROUND_NOT_FOUND),
        (api.post_credit_support(UNKNOWN_UUIDS["credit_support"],
                                 f.post_credit_support_payload(current_token),
                                 CREDIT_OFFICER),
         ApiErrorId.ERR_CREDIT_SUPPORT_NOT_FOUND),
        (api.resolve_condition_precedent(
            UNKNOWN_UUIDS["condition_precedent"],
            f.cp_resolution_payload("SATISFY",
                                    evidence_ref="PERMIT-2026-0001"),
            DEAL_COMMITTEE),
         ApiErrorId.ERR_CONDITION_PRECEDENT_NOT_FOUND),
        (api.get_settlement_period(UNKNOWN_UUIDS["settlement_period"],
                                  SETTLEMENT_ANALYST),
         ApiErrorId.ERR_SETTLEMENT_PERIOD_NOT_FOUND),
        (api.transfer_attribute_batch(UNKNOWN_UUIDS["attribute_batch"],
                                      f.transfer_payload(buyer["id"]),
                                      REGISTRY_AGENT),
         ApiErrorId.ERR_ATTRIBUTE_BATCH_NOT_FOUND),
        (api.review_risk_event(UNKNOWN_UUIDS["risk_event"],
                               f.risk_review_payload("REJECT"),
                               DEAL_COMMITTEE),
         ApiErrorId.ERR_RISK_EVENT_NOT_FOUND),
    ]
    for response, expected in attempts:
        validate_error(response, expected.value, 404)

    # Nothing was mutated, and the one live deal is still the only deal.
    assert fx.deal_version(api, deal_id) == current_token, deal
    _, meta = fx.list_all(api.list_deals(ORIGINATOR))
    assert meta["total_count"] == 1, meta


# ---------------------------------------------------------------------------
# The guarantor forest: three nodes, four refusals, no re-parenting.
# ---------------------------------------------------------------------------

#: A three-deep chain C -> B -> A -> null, built entirely by creation, because
#: "a create attaches a leaf and can never close a cycle".
MIDDLE_CHILD = {
    "legal_name": "Cascadia Foods Co",
    "credit_rating": "BBB",
    "reported_ebitda_usd": 40000000.00,
    "net_debt_to_ebitda": 3.0,
}
LEAF_CHILD = {
    "legal_name": "Puget Logistics LLC",
    "credit_rating": "BB",
    "reported_ebitda_usd": 15000000.00,
    "net_debt_to_ebitda": 3.5,
    "disclosure_framework": "TCFD_ONLY",
}

#: 0.55 * 84 + 0.30 * 75 + 0.15 * 100, the anchor's standalone score.
ANCHOR_SCORE = 83.70


def test_03_a_closing_cycle_is_refused_at_every_depth_of_the_chain(api):
    """A self-edge, a two-node loop and a three-node loop are all refused by the
    same rule, an unknown guarantor is refused one rung earlier, and the root is
    left exactly as it was.

    "Guarantor links must form a forest, never a graph with a cycle. A supplied
    `parent_guarantor_offtaker_id` may not be the buyer's own identifier, and
    walking the existing guarantor chain upward from the proposed parent must
    terminate at a null guarantor without ever revisiting a node; a violation is
    `ERR_GUARANTOR_CYCLE`."

    "Since a freshly created record can only ever be attached as a leaf, the
    cycle case is in practice reachable only by re-parenting an existing record
    during a rating change."

    "A supplied `parent_guarantor_offtaker_id` re-parents the guarantor edge
    **before** any scoring runs, and must both exist and satisfy the forest rule
    — neither equal to this buyer's own identifier nor closing a cycle when the
    upward chain is walked — or the request is refused with
    `ERR_GUARANTOR_CYCLE`."

    "Guarantor-graph well-formedness — `ERR_GUARANTOR_CYCLE`, on buyer creation
    and on a rating change."

    Design: Corner/errors/guarantor_re_parenting_that_closes_a_cycle_is_refused_at_any_depth
    """
    root = fx.create_qualified_offtaker(api)
    middle = fx.create_offtaker(api,
                                parent_guarantor_offtaker_id=root["id"],
                                **MIDDLE_CHILD)
    leaf = fx.create_offtaker(api,
                              parent_guarantor_offtaker_id=middle["id"],
                              **LEAF_CHILD)
    assert middle["parent_guarantor_offtaker_id"] == root["id"], middle
    assert leaf["parent_guarantor_offtaker_id"] == middle["id"], leaf

    # Depth 0, depth 1 and depth 2: only a walk of the whole upward chain
    # catches the third one.
    for proposed in (root["id"], middle["id"], leaf["id"]):
        response = api.change_offtaker_rating(
            root["id"], f.rating_change_payload("A",
                                               parent_guarantor_offtaker_id=proposed),
            CREDIT_OFFICER)
        validate_error(response, ApiErrorId.ERR_GUARANTOR_CYCLE.value, 422)

    # Priority 5 sits ahead of priority 6: an unknown parent is a 404.
    unknown = api.change_offtaker_rating(
        root["id"],
        f.rating_change_payload(
            "A", parent_guarantor_offtaker_id=UNKNOWN_UUIDS["guarantor"]),
        CREDIT_OFFICER)
    validate_error(unknown, ApiErrorId.ERR_OFFTAKER_NOT_FOUND.value, 404)

    # Four refusals, no re-parenting and no re-scoring.
    at_rest = fx.read_offtaker(api, root["id"])
    assert at_rest["parent_guarantor_offtaker_id"] is None, at_rest
    assert at_rest["credit_score_variant"] == "STANDALONE", at_rest
    asserts.assert_score(at_rest["credit_score"], ANCHOR_SCORE, "credit_score")
    assert at_rest["version"] == root["version"], at_rest
    assert at_rest["qualification_status"] == "QUALIFIED", at_rest


# ---------------------------------------------------------------------------
# A declined tier bars re-underwriting.
#
# The tier gate sits at priority 12, one rung below the qualification gate at
# priority 11, and a `DECLINED` tier can never coexist with a `QUALIFIED` or
# `CONDITIONAL` buyer — both decisions refuse that tier outright, and a
# downgrade into it moves the buyer to `WATCHLIST`.  The only submission the
# PRD leaves reachable at priority 12 is therefore the re-underwriting loop
# from `credit_status` `DECLINED`, which is the one path that does not consult
# qualification standing at all.
# ---------------------------------------------------------------------------

#: CCC scores 20 and 8.0 turns of leverage clamp to 20, so
#: 0.55 * 20 + 0.30 * 20 + 0.15 * 100 = 32.00, below the 45.00 floor.
DECLINED_SCORE = 32.00
DECLINED_LIMIT_USD = 0.00
ANCHOR_LIMIT_USD = 3000000.00


def test_04_a_declined_tier_bars_re_underwriting_until_the_rating_recovers(api):
    """A refused package can be resubmitted, but not while the buyer's tier has
    fallen to `DECLINED`; restoring the rating makes the identical call succeed.

    "`DECLINE` moves the deal `SUBMITTED → DECLINED`, sets
    `credit_approved_by_user_id` back to null, and leaves the commercial `status`
    untouched, which is exactly what makes the two dimensions independent."

    "A drop out of `QUALIFIED` into a recomputed `credit_tier` of `SUBPRIME` or
    `DECLINED` moves the buyer `QUALIFIED → WATCHLIST` and fires a four-hop
    cascade."

    "Hop two, caused by hop one's smaller unsecured limit, visits every deal
    anchored by this buyer whose `status` is `TERMS_AGREED`, `EXECUTED` or
    `EFFECTIVE`, re-snapshots that deal's `unsecured_credit_limit_usd` and
    re-sizes its `credit_support_required_usd`."

    "Submission is legal from `NOT_SUBMITTED`, from `DECLINED` — the
    re-underwriting loop after a refused package — and from `SUPPORT_SHORTFALL`,
    and in every case the deal moves to `SUBMITTED`."

    "It also requires the anchor buyer's `credit_tier` to be anything other than
    `DECLINED`; a declined tier carries a 0.00 unsecured limit and has no
    eligible support path, so review is refused outright with
    `ERR_CREDIT_TIER_DECLINED`."

    "Recovery runs the same machinery in reverse. A rating change on a
    watchlisted buyer whose recomputed `credit_tier` is `PRIME` or `STANDARD`
    moves it `WATCHLIST → QUALIFIED`, recomputes the four credit figures, and
    sets `watchlist_since` back to null."

    Design: Corner/errors/submit_credit_is_refused_once_the_anchor_tier_falls_to_declined
    """
    chain = fx.chain_a(api)
    deal_id = chain["deal"]["id"]
    buyer_id = chain["buyer"]["id"]

    fx.submit_credit(api, deal_id)
    refused = fx.decide_credit(api, deal_id, "DECLINE")
    assert refused["credit_status"] == "DECLINED", refused
    assert refused["status"] == "DRAFT", refused
    assert refused["credit_approved_by_user_id"] is None, refused

    downgraded = get_success_data(api.change_offtaker_rating(
        buyer_id, f.rating_change_payload("CCC", net_debt_to_ebitda=8.0),
        CREDIT_OFFICER), 200)
    asserts.assert_score(downgraded["credit_score"], DECLINED_SCORE,
                         "credit_score")
    assert downgraded["credit_tier"] == "DECLINED", downgraded
    asserts.assert_money(downgraded["unsecured_credit_limit_usd"],
                         DECLINED_LIMIT_USD, "unsecured_credit_limit_usd")
    assert downgraded["qualification_status"] == "WATCHLIST", downgraded
    asserts.assert_instant_equals(downgraded["watchlist_since"],
                                  fx.INITIAL_CLOCK, "watchlist_since")

    # A `DRAFT` deal is outside hop two's visit list, so its snapshot stands.
    at_rest = fx.read_deal(api, deal_id)
    asserts.assert_money(at_rest["collateral_threshold_usd"], ANCHOR_LIMIT_USD,
                         "collateral_threshold_usd")
    asserts.assert_money(at_rest["credit_support_required_usd"], 0.00,
                         "credit_support_required_usd")
    assert at_rest["credit_status"] == "DECLINED", at_rest

    # The re-underwriting loop is open on the state dimension, so the answer
    # comes from the tier rung and not from the state gate.
    blocked = api.submit_deal_credit(deal_id, ORIGINATOR)
    validate_error(blocked, ApiErrorId.ERR_CREDIT_TIER_DECLINED.value, 422)
    assert fx.read_deal(api, deal_id)["credit_status"] == "DECLINED"

    restored = get_success_data(api.change_offtaker_rating(
        buyer_id, f.rating_change_payload("A", net_debt_to_ebitda=2.5),
        CREDIT_OFFICER), 200)
    assert restored["credit_tier"] == "PRIME", restored
    assert restored["qualification_status"] == "QUALIFIED", restored
    assert restored["watchlist_since"] is None, restored
    asserts.assert_score(restored["credit_score"], ANCHOR_SCORE, "credit_score")

    resubmitted = fx.submit_credit(api, deal_id)
    assert resubmitted["credit_status"] == "SUBMITTED", resubmitted


# ---------------------------------------------------------------------------
# A settlement point name is an identifier, not a label.
# ---------------------------------------------------------------------------

CLASHING_NAME = "KRAMER JUNCTION 1N"
FREE_NAME = "NORTH GILA 500KV"


def test_05_a_settlement_point_name_is_unique_across_every_iso(api):
    """The uniqueness test reads the name and nothing else, so the same name
    under a different ISO and a different point type is still a duplicate, while
    a fresh name registers happily under a permitted second role.

    "A settlement point is registered by an `Originator` or a `SettlementAnalyst`
    with three attributes: a `name` between 1 and 64 characters, the `iso` that
    publishes it — one of `CAISO`, `ERCOT`, `PJM` or `MISO` — and a
    `settlement_point_type` that is either `HUB` or `NODE`."

    "Because these names are identifiers published by the independent system
    operator and must never be re-used, a second registration under an existing
    `name` is refused with `ERR_DUPLICATE_PRICING_NODE`."

    "Settlement points are immutable: they carry no `version` and there is no
    operation that amends one."

    "Settlement point name uniqueness — `ERR_DUPLICATE_PRICING_NODE`."

    Design: Corner/errors/pricing_node_names_are_globally_unique_across_isos
    """
    first = fx.create_node(api, name=CLASHING_NAME)
    assert first["name"] == CLASHING_NAME, first
    asserts.assert_pricing_node_shape(first)

    # Neither the ISO nor the point type takes any part in the test.
    across_isos = api.create_pricing_node(
        f.pricing_node_payload(name=CLASHING_NAME, iso="ERCOT",
                               settlement_point_type="HUB"), ORIGINATOR)
    validate_error(across_isos, ApiErrorId.ERR_DUPLICATE_PRICING_NODE.value, 409)

    same_shape = api.create_pricing_node(
        f.pricing_node_payload(name=CLASHING_NAME, iso="CAISO",
                               settlement_point_type="NODE"),
        SETTLEMENT_ANALYST)
    validate_error(same_shape, ApiErrorId.ERR_DUPLICATE_PRICING_NODE.value, 409)

    # A free name is accepted, and the analyst may register it.
    second = get_success_data(api.create_pricing_node(
        f.pricing_node_payload(name=FREE_NAME, iso="ERCOT",
                               settlement_point_type="HUB"),
        SETTLEMENT_ANALYST), 201)
    asserts.assert_pricing_node_shape(second)
    assert second["iso"] == "ERCOT", second

    rows, meta = fx.list_all(api.list_pricing_nodes(ORIGINATOR))
    assert meta["total_count"] == 2, meta
    assert sorted(row["name"] for row in rows) == sorted([CLASHING_NAME,
                                                          FREE_NAME]), rows


# ---------------------------------------------------------------------------
# Headroom is measured against the executed book, and equality is allowed.
# ---------------------------------------------------------------------------

SMALL_CAPACITY_MW = 50.000
EXECUTED_DEAL_MW = 30.000
REMAINING_MW = 20.000
OVER_HEADROOM_MW = 25.000
JUST_OVER_HEADROOM_MW = 21.000


def test_06_a_deal_may_take_exactly_the_headroom_but_never_more(api):
    """An executed 30.000 MW deal leaves 20.000 MW open: 25.000 is refused,
    20.000 exactly is accepted, and because a `DRAFT` deal books nothing the same
    20.000 is still open behind it.

    "And the requested `contracted_mw` must not exceed the parent project's
    `available_mw` at the moment of creation, or the request is refused with
    `ERR_PROJECT_CAPACITY_EXCEEDED`; equality is allowed, so a deal may take
    exactly the remaining headroom."

    "Thereafter `contracted_mw` is always the sum of `contracted_mw` over the
    project's deals whose `status` is `EXECUTED` or `EFFECTIVE`, and
    `available_mw` is `capacity_mw` less `contracted_mw`."

    "Execution also recomputes the project's `contracted_mw` and `available_mw`
    and increments the deal's `version` by one."

    "Project capacity headroom at deal creation — `ERR_PROJECT_CAPACITY_EXCEEDED`."

    Design: Corner/errors/deal_creation_beyond_the_projects_remaining_capacity_is_refused
    """
    chain = fx.negotiated_chain(
        api, project_overrides={"capacity_mw": SMALL_CAPACITY_MW},
        deal_overrides={"contracted_mw": EXECUTED_DEAL_MW})
    project_id = chain["project"]["id"]
    buyer_id = chain["buyer"]["id"]
    node_id = chain["node"]["id"]

    executed = fx.execute_deal(api, chain["deal"]["id"])
    assert executed["status"] == "EXECUTED", executed
    booked = fx.read_project(api, project_id)
    asserts.assert_mw(booked["contracted_mw"], EXECUTED_DEAL_MW,
                      "contracted_mw")
    asserts.assert_mw(booked["available_mw"], REMAINING_MW, "available_mw")

    over = api.create_deal(
        f.deal_payload(project_id, buyer_id, node_id,
                       contracted_mw=OVER_HEADROOM_MW), ORIGINATOR)
    validate_error(over, ApiErrorId.ERR_PROJECT_CAPACITY_EXCEEDED.value, 422)

    exact = fx.create_deal(api, project_id, buyer_id, node_id,
                           contracted_mw=REMAINING_MW)
    assert exact["status"] == "DRAFT", exact
    asserts.assert_mw(exact["contracted_mw"], REMAINING_MW, "contracted_mw")

    # The ledger counts the executed deal only, so the headroom is unmoved.
    still_open = fx.read_project(api, project_id)
    asserts.assert_mw(still_open["contracted_mw"], EXECUTED_DEAL_MW,
                      "contracted_mw")
    asserts.assert_mw(still_open["available_mw"], REMAINING_MW, "available_mw")

    just_over = api.create_deal(
        f.deal_payload(project_id, buyer_id, node_id,
                       contracted_mw=JUST_OVER_HEADROOM_MW), ORIGINATOR)
    validate_error(just_over, ApiErrorId.ERR_PROJECT_CAPACITY_EXCEEDED.value,
                   422)

    twin = fx.create_deal(api, project_id, buyer_id, node_id,
                          contracted_mw=REMAINING_MW)
    assert twin["status"] == "DRAFT", twin
    final = fx.read_project(api, project_id)
    asserts.assert_mw(final["contracted_mw"], EXECUTED_DEAL_MW,
                      "contracted_mw")
    asserts.assert_mw(final["available_mw"], REMAINING_MW, "available_mw")
    _, meta = fx.list_all(api.list_deals(ORIGINATOR))
    assert meta["total_count"] == 3, meta
