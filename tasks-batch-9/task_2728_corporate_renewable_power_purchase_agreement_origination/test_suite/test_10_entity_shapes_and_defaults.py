"""Creation shapes: declared fields, declared defaults and server-derived fields.

These tests never move a state machine.  They ask what a row looks like the
instant it is created — which fields exist at all, which optionals fall back to
their declared defaults, and which values the server derives for itself no
matter what the client sends.
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
from test_helpers.test_users import (  # noqa: E402
    CREDIT_OFFICER,
    ORIGINATOR,
    ORIGINATOR_ID,
)

#: The five figures the PRD declares null until a submission runs.
COMPUTED_CREDIT_FIELDS = [
    "credit_score",
    "credit_score_variant",
    "credit_tier",
    "sustainability_score",
    "unsecured_credit_limit_usd",
]

#: Northwind: A / SP / 2.5 turns / CDP_AND_TCFD / SBT / RE100 / 2030.
NORTHWIND_SCORE = 83.70
NORTHWIND_SUSTAINABILITY = 100.00
NORTHWIND_LIMIT_USD = 3000000.00

#: Bare Minimum Industrials: BBB / FITCH / 4.0 turns / NONE and nothing else.
BARE_SCORE = 62.10
BARE_SUSTAINABILITY = 0.00
BARE_LIMIT_USD = 400000.00


def test_01_a_settlement_point_is_three_fields_an_id_and_a_creation_stamp(api):
    """The registered node carries its three declared attributes and neither of
    the two common fields the PRD strips from it.

    "`PricingNode` is the single exception: a settlement point is immutable once
    registered, so it carries only `id` and `created_at` — both `updated_at` and
    `version` are absent from it entirely, and there is no operation that amends
    one."

    "A settlement point is registered by an `Originator` or a
    `SettlementAnalyst` with three attributes: a `name` between 1 and 64
    characters, the `iso` that publishes it — one of `CAISO`, `ERCOT`, `PJM` or
    `MISO` — and a `settlement_point_type` that is either `HUB` or `NODE`."

    Design: Corner/entities/pricing_node_created_with_declared_fields_and_no_version
    """
    created = api.create_pricing_node(f.hub_payload(name="SP15 EZ GEN HUB"),
                                      ORIGINATOR)
    node = get_success_data(created, 201)

    asserts.assert_pricing_node_shape(node)
    assert node["name"] == "SP15 EZ GEN HUB", node
    assert node["iso"] == "CAISO", node
    assert node["settlement_point_type"] == "HUB", node
    assert "version" not in node, (
        f"a settlement point carries no version, got {sorted(node.keys())}")
    assert "updated_at" not in node, (
        f"updated_at is absent from a settlement point entirely, "
        f"got {sorted(node.keys())}")

    # The row was persisted, not echoed back.
    fetched = get_success_data(api.get_pricing_node(node["id"], ORIGINATOR), 200)
    asserts.assert_pricing_node_shape(fetched)
    assert fetched["id"] == node["id"], fetched
    assert fetched["name"] == "SP15 EZ GEN HUB", fetched
    assert fetched["iso"] == "CAISO", fetched
    assert fetched["settlement_point_type"] == "HUB", fetched
    assert "version" not in fetched, fetched
    assert "updated_at" not in fetched, fetched
    asserts.assert_instant_equals(fetched["created_at"], node["created_at"],
                                  "created_at")


def test_02_reading_a_buyer_back_separates_stored_inputs_from_derived_scores(api):
    """A create stores the inputs and leaves all five credit figures null; the
    submission derives them; and the read-back returns exactly what the write
    returned, unchanged by being read.

    "On creation `qualification_status` is `DRAFT`, `conditions` is the empty
    array, `claimed_attributes_mwh` is 0, `watchlist_since` is null,
    `decision_by_user_id` is null, and `credit_score`, `credit_score_variant`,
    `credit_tier`, `sustainability_score` and `unsecured_credit_limit_usd` are
    all null — no scoring runs at creation."

    "Both paths recompute `credit_score`, `credit_score_variant`,
    `credit_tier`, `sustainability_score` and `unsecured_credit_limit_usd`, and
    both increment the buyer's `version` by one."

    Design: Corner/entities/offtaker_get_returns_stored_inputs_and_computed_scores
    """
    created = api.create_offtaker(f.anchor_offtaker_payload(), ORIGINATOR)
    buyer = get_success_data(created, 201)
    asserts.assert_common_fields(buyer, expected_version=1)

    assert buyer["legal_name"] == "Northwind Retail Inc", buyer
    assert buyer["credit_rating"] == "A", buyer
    assert buyer["rating_agency"] == "SP", buyer
    assert abs(float(buyer["net_debt_to_ebitda"]) - 2.5) < 0.005, buyer
    assert buyer["registry_account_id"] == "WREGIS-ACC-00417", buyer
    assert buyer["qualification_status"] == "DRAFT", buyer
    asserts.assert_all_null(buyer, COMPUTED_CREDIT_FIELDS + [
        "decision_by_user_id", "watchlist_since"])

    # A read is not a write: the DRAFT record reads back identically.
    read_as_drafted = get_success_data(
        api.get_offtaker(buyer["id"], CREDIT_OFFICER), 200)
    assert read_as_drafted["version"] == buyer["version"], read_as_drafted
    assert read_as_drafted["qualification_status"] == "DRAFT", read_as_drafted
    asserts.assert_all_null(read_as_drafted, COMPUTED_CREDIT_FIELDS)

    submitted = fx.submit_offtaker(api, buyer["id"])
    asserts.assert_version_advanced_by(buyer["version"], submitted["version"], 1,
                                      "offtaker version")

    # And now the read-back must reproduce the five derived figures exactly.
    fetched = get_success_data(api.get_offtaker(buyer["id"], CREDIT_OFFICER), 200)
    assert fetched["version"] == submitted["version"], fetched
    assert fetched["qualification_status"] == "UNDER_REVIEW", fetched
    asserts.assert_score(fetched["credit_score"], NORTHWIND_SCORE,
                         "credit_score")
    assert fetched["credit_score_variant"] == "STANDALONE", fetched
    assert fetched["credit_tier"] == "PRIME", fetched
    asserts.assert_score(fetched["sustainability_score"],
                         NORTHWIND_SUSTAINABILITY, "sustainability_score")
    asserts.assert_money(fetched["unsecured_credit_limit_usd"],
                         NORTHWIND_LIMIT_USD, "unsecured_credit_limit_usd")
    for field in COMPUTED_CREDIT_FIELDS:
        assert fetched[field] == submitted[field], (
            f"{field} must read back as it was written: "
            f"{submitted[field]!r} vs {fetched[field]!r}")
    # The stored inputs are untouched by the scoring run.
    assert fetched["legal_name"] == "Northwind Retail Inc", fetched
    assert fetched["credit_rating"] == "A", fetched
    assert fetched["registry_account_id"] == "WREGIS-ACC-00417", fetched


def test_03_a_six_field_buyer_takes_every_declared_default(api):
    """Only the six required inputs are sent, and every optional lands on its
    declared default — which is the one way to reach a sustainability score of
    exactly 0.00.

    "the optional booleans `has_science_based_target` and `re100_member`, each
    defaulting to false; the optional `scope2_target_year`, which is either null
    or a year from 2026 through 2060 and defaults to null; the optional
    `registry_account_id` naming the buyer's attribute registry account,
    defaulting to null; and the optional `parent_guarantor_offtaker_id` pointing
    at another buyer record whose balance sheet may credit-support this one, also
    defaulting to null."

    "The `created_by_user_id` is stamped from the acting operator and is what the
    qualification-decision segregation check later compares against."

    Design: Corner/entities/offtaker_create_applies_declared_defaults_for_omitted_optionals
    """
    created = api.create_offtaker(
        f.offtaker_payload(legal_name="Bare Minimum Industrials LLC",
                           credit_rating="BBB", rating_agency="FITCH",
                           reported_ebitda_usd=20000000.00,
                           net_debt_to_ebitda=4.0,
                           disclosure_framework="NONE"),
        ORIGINATOR)
    buyer = get_success_data(created, 201)
    asserts.assert_common_fields(buyer, expected_version=1)

    assert buyer["has_science_based_target"] is False, buyer
    assert buyer["re100_member"] is False, buyer
    asserts.assert_all_null(buyer, ["scope2_target_year", "registry_account_id",
                                    "parent_guarantor_offtaker_id",
                                    "watchlist_since", "decision_by_user_id"])
    assert buyer["conditions"] == [], buyer
    assert buyer["claimed_attributes_mwh"] == 0, buyer
    assert buyer["qualification_status"] == "DRAFT", buyer
    assert buyer["created_by_user_id"] == ORIGINATOR_ID, buyer
    asserts.assert_all_null(buyer, COMPUTED_CREDIT_FIELDS)

    # The defaults are what the scoring chain then reads.
    scored = fx.submit_offtaker(api, buyer["id"])
    asserts.assert_score(scored["credit_score"], BARE_SCORE, "credit_score")
    assert scored["credit_tier"] == "STANDARD", scored
    asserts.assert_money(scored["unsecured_credit_limit_usd"], BARE_LIMIT_USD,
                         "unsecured_credit_limit_usd")
    asserts.assert_score(scored["sustainability_score"], BARE_SUSTAINABILITY,
                         "sustainability_score")
    assert scored["credit_score_variant"] == "STANDALONE", scored
    # Still no science-based target, no RE100 and no near-term year.
    assert scored["has_science_based_target"] is False, scored
    assert scored["re100_member"] is False, scored
    assert scored["scope2_target_year"] is None, scored


def test_04_smuggled_credit_figures_are_ignored_rather_than_honoured(api):
    """The request asserts a PRIME tier and a twenty-five million dollar
    unsecured line; the server accepts the request and derives its own far lower
    numbers.

    "Any field whose value the server derives — a computed or system field — is
    silently ignored when a client supplies it, never rejected."

    "`credit_score`, `credit_score_variant`, `credit_tier`,
    `sustainability_score` and `unsecured_credit_limit_usd` are all null — no
    scoring runs at creation."

    Design: Corner/entities/offtaker_create_computed_scores_extra_field_input_ignored
    """
    created = api.create_offtaker(
        f.offtaker_payload(legal_name="Wishful Thinking Corp",
                           credit_rating="BBB", rating_agency="FITCH",
                           reported_ebitda_usd=20000000.00,
                           net_debt_to_ebitda=4.0,
                           disclosure_framework="NONE",
                           credit_score=99.99,
                           credit_tier="PRIME",
                           sustainability_score=100.00,
                           unsecured_credit_limit_usd=25000000.00),
        ORIGINATOR)
    buyer = get_success_data(created, 201)

    # Ignored, not rejected — and ignored means null, because nothing is scored
    # at creation.
    asserts.assert_all_null(buyer, COMPUTED_CREDIT_FIELDS)

    scored = fx.submit_offtaker(api, buyer["id"])
    asserts.assert_score(scored["credit_score"], BARE_SCORE, "credit_score")
    assert scored["credit_score"] != 99.99, scored
    assert scored["credit_tier"] == "STANDARD", scored
    asserts.assert_score(scored["sustainability_score"], BARE_SUSTAINABILITY,
                         "sustainability_score")
    asserts.assert_money(scored["unsecured_credit_limit_usd"], BARE_LIMIT_USD,
                         "unsecured_credit_limit_usd")

    # Nothing client-supplied was persisted anywhere behind the scenes.
    fetched = get_success_data(api.get_offtaker(buyer["id"], CREDIT_OFFICER), 200)
    asserts.assert_score(fetched["credit_score"], BARE_SCORE, "credit_score")
    assert fetched["credit_tier"] == "STANDARD", fetched
    asserts.assert_score(fetched["sustainability_score"], BARE_SUSTAINABILITY,
                         "sustainability_score")
    asserts.assert_money(fetched["unsecured_credit_limit_usd"], BARE_LIMIT_USD,
                         "unsecured_credit_limit_usd")


# ---------------------------------------------------------------------------
# Deals: the system fields a client must not be able to dictate, and the two
# closed enums on the create payload.
# ---------------------------------------------------------------------------

GHOST_USER_ID = "u_ghost_1"

DEAL_ZERO_BUCKETS = [
    "posted_credit_support_usd",
    "released_credit_support_usd",
    "drawn_credit_support_usd",
    "attributes_minted_mwh",
    "attributes_transferred_mwh",
    "attributes_retired_mwh",
]

DEAL_NULL_ON_CREATION = [
    "credit_approved_by_user_id",
    "support_cure_deadline",
    "effective_at",
    "terminated_at",
    "termination_reason",
    "cp_completion_pct",
]

PROJECT_CAPACITY_MW = 100.000
CONTRACTED_MW = 25.000


def _structuring_desk(api):
    """A hub, an injection node, a QUALIFIED anchor buyer and its project."""
    hub = fx.create_hub(api)
    node = fx.create_node(api)
    buyer = fx.create_qualified_offtaker(api)
    project = fx.create_project(api, node["id"], capacity_mw=PROJECT_CAPACITY_MW,
                                cod_target_date="2029-06-01T00:00:00Z")
    return {"hub": hub, "node": node, "buyer": buyer, "project": project}


def test_05_the_header_stamps_the_author_and_the_smuggled_status_is_ignored(api):
    """A create that claims to have been authored by another operator and to be
    already executed is accepted, and every one of those claims is discarded.

    "Any field whose value the server derives — a computed or system field — is
    silently ignored when a client supplies it, never rejected."

    "`status` is `DRAFT` and `credit_status` is `NOT_SUBMITTED`; `round_count` is
    0; `confirmed_allocated_mw` is 0 and `unallocated_mw` equals `contracted_mw`;
    `cp_total_count` is 0; `posted_credit_support_usd`,
    `released_credit_support_usd`, `drawn_credit_support_usd`,
    `attributes_minted_mwh`, `attributes_transferred_mwh` and
    `attributes_retired_mwh` are all 0; `credit_approved_by_user_id`,
    `support_cure_deadline`, `effective_at`, `terminated_at`,
    `termination_reason` and `cp_completion_pct` are all null; and
    `created_by_user_id` is stamped from the acting operator, which is the
    identifier the credit-decision segregation check later compares against."

    Design: Corner/entities/deal_created_by_user_id_from_header_input_ignored
    """
    desk = _structuring_desk(api)
    created = api.create_deal(
        f.deal_payload(desk["project"]["id"], desk["buyer"]["id"],
                       desk["hub"]["id"], product_type="VIRTUAL_CFD",
                       contracted_mw=CONTRACTED_MW, term_years=12,
                       created_by_user_id=GHOST_USER_ID,
                       status="EXECUTED",
                       posted_credit_support_usd=9999999.99),
        ORIGINATOR)
    deal = get_success_data(created, 201)
    asserts.assert_common_fields(deal, expected_version=1)

    assert deal["created_by_user_id"] == ORIGINATOR_ID, deal
    assert deal["created_by_user_id"] != GHOST_USER_ID, deal
    assert deal["id"] != GHOST_USER_ID, "the id is system-assigned too"
    assert deal["status"] == "DRAFT", deal
    assert deal["credit_status"] == "NOT_SUBMITTED", deal
    for field in DEAL_ZERO_BUCKETS:
        assert float(deal[field]) == 0, f"{field} starts at 0, got {deal[field]!r}"
    asserts.assert_all_null(deal, DEAL_NULL_ON_CREATION)
    assert deal["round_count"] == 0, deal
    asserts.assert_mw(deal["confirmed_allocated_mw"], 0.000,
                      "confirmed_allocated_mw")
    asserts.assert_mw(deal["unallocated_mw"], CONTRACTED_MW, "unallocated_mw")
    assert deal["cp_total_count"] == 0, deal

    # The read-back agrees: nothing the client sent was persisted.
    fetched = fx.read_deal(api, deal["id"])
    assert fetched["created_by_user_id"] == ORIGINATOR_ID, fetched
    assert fetched["status"] == "DRAFT", fetched
    asserts.assert_money(fetched["posted_credit_support_usd"], 0.00,
                         "posted_credit_support_usd")


def test_06_a_project_without_a_capacity_is_a_bad_request_not_a_zero_mw_row(api):
    """`capacity_mw` has no default, so omitting it is a 400 — and no project is
    left behind with a capacity of nothing.

    "Request shape: every required field present, every enum value a declared
    member, every numeric inside its declared range, every datetime parseable as
    ISO-8601 UTC, and pagination bounds respected — `ERR_INVALID_REQUEST`."

    "On creation, `contracted_mw` is 0 and `available_mw` equals `capacity_mw`;
    `last_milestone_at` is null and `created_by_user_id` is stamped from the
    acting operator's identifier."

    Design: Corner/entities/project_create_missing_capacity_mw_returns_invalid_request
    """
    node = fx.create_node(api)
    payload = f.project_payload(node["id"],
                               cod_target_date="2029-06-01T00:00:00Z")
    del payload["capacity_mw"]
    assert "node_id" in payload, "the reference in the request stays valid"

    refused = api.create_project(payload, ORIGINATOR)
    validate_error(refused, ApiErrorId.ERR_INVALID_REQUEST.value, 400)
    asserts.assert_error_envelope(refused)

    rows, meta = fx.list_all(api.list_projects(ORIGINATOR))
    assert meta["total_count"] == 0, meta
    assert rows == [], rows


def test_07_a_plausible_but_undeclared_enum_member_is_refused_on_both_fields(api):
    """`SLEEVED` is a real industry term and `QUARTERLY` a real netting cadence,
    and neither is a declared member; both requests are rejected before any
    capacity is reserved.

    "Request shape: every required field present, every enum value a declared
    member, every numeric inside its declared range, every datetime parseable as
    ISO-8601 UTC, and pagination bounds respected — `ERR_INVALID_REQUEST`."

    "It declares the `product_type` — `PHYSICAL_DELIVERY` for real energy
    delivery, `VIRTUAL_CFD` for a financial contract for differences, or
    `AGGREGATED` for a multi-buyer arrangement — the total `contracted_mw` across
    all buyers, carried to at most three decimals and strictly above zero, the
    `term_years` (from 5 to 25), the `first_delivery_year` (from 2026 through
    2040), the `commercial_operation_deadline` that is the outside date by which
    the project must reach `OPERATIONAL`, and the `settlement_frequency` electing
    either `HOURLY` or `MONTHLY` netting."

    Design: Corner/entities/deal_create_invalid_enum_product_type_rejected
    """
    desk = _structuring_desk(api)
    project_id = desk["project"]["id"]
    project_before = fx.read_project(api, project_id)

    bad_product = api.create_deal(
        f.deal_payload(project_id, desk["buyer"]["id"], desk["hub"]["id"],
                       product_type="SLEEVED", contracted_mw=CONTRACTED_MW,
                       term_years=12),
        ORIGINATOR)
    validate_error(bad_product, ApiErrorId.ERR_INVALID_REQUEST.value, 400)
    asserts.assert_error_envelope(bad_product)

    bad_frequency = api.create_deal(
        f.deal_payload(project_id, desk["buyer"]["id"], desk["hub"]["id"],
                       product_type="VIRTUAL_CFD", contracted_mw=CONTRACTED_MW,
                       term_years=12, settlement_frequency="QUARTERLY"),
        ORIGINATOR)
    validate_error(bad_frequency, ApiErrorId.ERR_INVALID_REQUEST.value, 400)

    rows, meta = fx.list_all(api.list_deals(ORIGINATOR))
    assert meta["total_count"] == 0, meta
    assert rows == [], rows

    # No capacity was reserved by a rejected request.
    project_after = fx.read_project(api, project_id)
    asserts.assert_mw(project_after["contracted_mw"], 0.000, "contracted_mw")
    asserts.assert_mw(project_after["available_mw"], PROJECT_CAPACITY_MW,
                      "available_mw")
    assert project_after["version"] == project_before["version"], project_after
