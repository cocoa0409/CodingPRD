"""The endpoint surface and the two gates in front of it.

List filters compose conjunctively with the page window; a deal is a three-way
link whose settlement point need not be the project's own node; and the auth
ladder runs header presence, then the role list, then the request body, with two
further identity checks — counterparty ownership and segregation of duties —
that bite on requests whose role is already correct.
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
    DEAL_COMMITTEE_SECOND,
    DUAL_HAT_CREDIT_OFFICER,
    DUAL_HAT_DEAL_COMMITTEE,
    ORIGINATOR,
    REGISTRY_AGENT,
    SETTLEMENT_ANALYST,
    make_offtaker_rep_headers,
)

# ---------------------------------------------------------------------------
# Filters AND together, and the page window is measured against the filtered
# population rather than the whole book.
# ---------------------------------------------------------------------------

DEFAULT_LIMIT = 10
SECOND_PROJECT = {
    "name": "Kramer Junction Solar II",
    "capacity_mw": 50.000,
    "p50_annual_mwh": 122640.00,
    "cod_target_date": "2030-06-30T00:00:00Z",
}


def test_01_deal_list_filters_are_conjunctive_and_compose_with_the_window(api):
    """Three deals across two projects make every filter discriminating: the two
    filters AND to an empty page, `total_count` counts the filtered population
    rather than the page, and a `limit` of 0 is refused rather than clamped.

    "Deals are listed with optional `project_id`, `anchor_offtaker_id`,
    `settlement_point_id`, `status` and `credit_status` filters; those first three
    are the reverse-reachability channels from a project, a buyer or a settlement
    point back to the agreements that reference them."

    "`limit` controls page size: its default is 10, its minimum is 1 and its maximum
    is 100."

    "A `limit` below 1 or above 100, or a negative `offset`, is a request-shape
    violation and yields `ERR_INVALID_REQUEST`."

    "Every list response reports `limit`, `offset`, `total_count` and `has_more`
    inside `meta`, where `total_count` is the number of rows matching the filters
    before pagination is applied and `has_more` indicates whether any matching row
    remains beyond the current page."

    "The new round is created with `round_number` equal to the deal's `round_count`
    plus one, `status` `OPEN`, `responded_at` null and `responded_by_user_id` null;
    the deal's `round_count` then increments and its `version` increments by one."

    Design: Corner/endpoints/deal_list_filters_are_conjunctive_and_compose_with_the_page_window
    """
    node = fx.create_node(api)
    buyer = fx.create_qualified_offtaker(api)
    first_project = fx.create_project(api, node["id"])
    second_project = fx.create_project(api, node["id"], **SECOND_PROJECT)

    first_deal = fx.create_deal(api, first_project["id"], buyer["id"],
                                node["id"], product_type="VIRTUAL_CFD",
                                contracted_mw=25.000, term_years=12)
    second_deal = fx.create_deal(api, first_project["id"], buyer["id"],
                                 node["id"], contracted_mw=30.000,
                                 settlement_frequency="MONTHLY",
                                 base_fixed_price_usd_per_mwh=24.00,
                                 basis_responsibility="BUYER")
    third_deal = fx.create_deal(api, second_project["id"], buyer["id"],
                                node["id"], product_type="VIRTUAL_CFD",
                                contracted_mw=10.000, term_years=15,
                                base_fixed_price_usd_per_mwh=26.00,
                                basis_responsibility="SELLER",
                                commercial_operation_deadline="2030-12-31T00:00:00Z")
    for drafted in (first_deal, second_deal, third_deal):
        assert drafted["status"] == "DRAFT", drafted
        assert drafted["round_count"] == 0, drafted

    # Issuing a round moves only the third deal off DRAFT.
    fx.table_round(api, third_deal["id"],
                   proposed_fixed_price_usd_per_mwh=26.00,
                   proposed_basis_responsibility="SELLER",
                   response_deadline="2026-09-01T00:00:00Z")

    everything, meta = fx.list_all(api.list_deals(ORIGINATOR))
    assert len(everything) == 3, everything
    asserts.assert_page_meta(meta, total_count=3, limit=DEFAULT_LIMIT, offset=0,
                             has_more=False)
    asserts.assert_sorted_by_created_at(everything)
    for row in everything:
        asserts.assert_common_fields(row)
    assert asserts.row_by_id(everything, third_deal["id"])["round_count"] == 1, \
        everything
    assert asserts.row_by_id(everything, first_deal["id"])["round_count"] == 0, \
        everything

    drafts, draft_meta = fx.list_all(
        api.list_deals(ORIGINATOR, {"status": "DRAFT"}))
    assert sorted(asserts.ids_of(drafts)) == sorted(
        [first_deal["id"], second_deal["id"]]), drafts
    asserts.assert_page_meta(draft_meta, total_count=2, limit=DEFAULT_LIMIT,
                             offset=0, has_more=False)

    # total_count reports the filtered population, not the page.
    page_one, page_one_meta = fx.list_all(api.list_deals(
        ORIGINATOR, {"project_id": first_project["id"], "limit": 1,
                     "offset": 0}))
    assert len(page_one) == 1, page_one
    asserts.assert_page_meta(page_one_meta, total_count=2, limit=1, offset=0,
                             has_more=True)

    page_two, page_two_meta = fx.list_all(api.list_deals(
        ORIGINATOR, {"project_id": first_project["id"], "limit": 1,
                     "offset": 1}))
    assert len(page_two) == 1, page_two
    asserts.assert_page_meta(page_two_meta, total_count=2, limit=1, offset=1,
                             has_more=False)
    assert page_one[0]["id"] != page_two[0]["id"], (page_one, page_two)
    assert sorted([page_one[0]["id"], page_two[0]["id"]]) == sorted(
        [first_deal["id"], second_deal["id"]]), (page_one, page_two)

    # The two filters are ANDed, and an empty result is not an error.
    empty, empty_meta = fx.list_all(api.list_deals(
        ORIGINATOR, {"project_id": first_project["id"],
                     "status": "TERM_SHEET_ISSUED"}))
    assert empty == [], empty
    asserts.assert_page_meta(empty_meta, total_count=0, limit=DEFAULT_LIMIT,
                             offset=0, has_more=False)

    # A limit below the declared minimum is a request-shape violation.
    clamped = api.list_deals(ORIGINATOR, {"limit": 0})
    validate_error(clamped, ApiErrorId.ERR_INVALID_REQUEST.value, 400)
    negative = api.list_deals(ORIGINATOR, {"offset": -1})
    validate_error(negative, ApiErrorId.ERR_INVALID_REQUEST.value, 400)


# ---------------------------------------------------------------------------
# One project, two settlement points, two independent links.
# ---------------------------------------------------------------------------

NODE_DEAL_PRICE = 22.00
HUB_DEAL_PRICE = 23.50
PROJECT_CAPACITY_MW = 100.000


def test_02_a_deal_may_settle_at_a_hub_that_is_not_its_projects_node(api):
    """The same project carries a node-settled deal and a hub-settled one, each
    priced by its own basis allocation and each independently discoverable through
    the settlement point filter, while the project's own `node_id` is untouched.

    "The payload names the `project_id` supplying the energy, the
    `anchor_offtaker_id` of the lead corporate buyer that will sign, and the
    `settlement_point_id` whose published price settles the contract."

    "The basis adder is keyed on `basis_responsibility` alone: 1.50 USD per MWh when
    the seller bears basis risk, 0.75 when it is shared, and nothing when the buyer
    bears it."

    "Deals are listed with optional `project_id`, `anchor_offtaker_id`,
    `settlement_point_id`, `status` and `credit_status` filters; those first three
    are the reverse-reachability channels from a project, a buyer or a settlement
    point back to the agreements that reference them."

    "Finally it recomputes the parent project's `contracted_mw` and `available_mw`
    and increments that project's `version` by one."

    "Thereafter `contracted_mw` is always the sum of `contracted_mw` over the
    project's deals whose `status` is `EXECUTED` or `EFFECTIVE`, and `available_mw`
    is `capacity_mw` less `contracted_mw`."

    Design: Corner/endpoints/deal_creation_links_three_parents_and_permits_hub_settlement_off_node
    """
    node = fx.create_node(api)
    hub = fx.create_hub(api)
    buyer = fx.create_qualified_offtaker(api)
    project = fx.create_project(api, node["id"])
    assert project["node_id"] == node["id"], project

    node_deal = fx.create_deal(api, project["id"], buyer["id"], node["id"],
                               contracted_mw=25.000, term_years=12,
                               settlement_frequency="MONTHLY",
                               basis_responsibility="BUYER")
    hub_deal = fx.create_deal(api, project["id"], buyer["id"], hub["id"],
                              product_type="VIRTUAL_CFD", contracted_mw=30.000,
                              term_years=12, basis_responsibility="SELLER")

    for linked in (node_deal, hub_deal):
        assert linked["project_id"] == project["id"], linked
        assert linked["anchor_offtaker_id"] == buyer["id"], linked

    # Settling off-node is permitted, not an error.
    assert node_deal["settlement_point_id"] == node["id"], node_deal
    assert hub_deal["settlement_point_id"] == hub["id"], hub_deal
    asserts.assert_money(node_deal["contract_price_usd_per_mwh"],
                         NODE_DEAL_PRICE, "contract_price_usd_per_mwh")
    asserts.assert_money(hub_deal["contract_price_usd_per_mwh"], HUB_DEAL_PRICE,
                         "contract_price_usd_per_mwh")

    filtered, meta = fx.list_all(api.list_deals(
        ORIGINATOR, {"settlement_point_id": hub["id"]}))
    assert asserts.ids_of(filtered) == [hub_deal["id"]], filtered
    assert meta["total_count"] == 1, meta

    # Both creations recomputed the ledger and bumped the project's version, but
    # the ledger counts only EXECUTED or EFFECTIVE deals, and both are DRAFT.
    reread = fx.read_project(api, project["id"])
    assert reread["node_id"] == node["id"], reread
    asserts.assert_mw(reread["contracted_mw"], 0.000, "contracted_mw")
    asserts.assert_mw(reread["available_mw"], PROJECT_CAPACITY_MW,
                      "available_mw")
    asserts.assert_version_advanced_by(project["version"], reread["version"], 2,
                                       "project version")


# ---------------------------------------------------------------------------
# The auth ladder, walked with one body that is malformed throughout.
# ---------------------------------------------------------------------------

#: `TRANSFORMER` is not a member of the declared settlement point enum, so this
#: body deserves a 400 the moment anything looks at it.
MALFORMED_NODE = {
    "name": "MIDWAY 2N",
    "iso": "CAISO",
    "settlement_point_type": "TRANSFORMER",
}

#: Each of these header sets is missing or empties one of the two.
BROKEN_HEADER_SETS = [
    {},
    {"X-User-ID": "u_orig_1"},
    {"X-User-Role": "Originator"},
    {"X-User-ID": "", "X-User-Role": "Originator"},
    {"X-User-ID": "u_orig_1", "X-User-Role": ""},
]


def test_03_the_header_gate_answers_before_the_role_the_body_and_the_path(api):
    """One malformed body climbs the ladder: no headers gives 401 even on a deal id
    that does not exist, a role outside the endpoint's list gives 403 rather than
    the 400 the body deserves, the permitted role finally reaches the enum check,
    and only a well-formed body persists anything.

    "Every request to the API, without exception, must carry two headers:
    `X-User-ID`, identifying the acting operator, and `X-User-Role`, declaring the
    capacity in which that operator acts."

    "If either header is absent or empty the request is rejected with
    `ERR_UNAUTHENTICATED` before anything else happens — before the path is
    resolved, before the body is parsed, and before any resource is looked up, so a
    request for a non-existent identifier that also omits its headers returns 401
    rather than 404."

    "Once the headers are present, the role named in `X-User-Role` must appear among
    the roles the target endpoint authorizes; if it does not, the request is refused
    with `ERR_ROLE_NOT_PERMITTED`, and this refusal precedes request-shape parsing,
    so a wrong-role request carrying a malformed body still returns 403 rather than
    400."

    "A settlement point is registered by an `Originator` or a `SettlementAnalyst`
    with three attributes: a `name` between 1 and 64 characters, the `iso` that
    publishes it — one of `CAISO`, `ERCOT`, `PJM` or `MISO` — and a
    `settlement_point_type` that is either `HUB` or `NODE`."

    Design: Corner/rbac/missing_headers_return_unauthenticated_before_the_role_gate_or_the_body_check
    """
    existing = fx.create_node(api)

    for headers in BROKEN_HEADER_SETS:
        unauthenticated = api.create_pricing_node(MALFORMED_NODE, headers)
        validate_error(unauthenticated, ApiErrorId.ERR_UNAUTHENTICATED.value,
                       401)

    # 401 precedes path resolution, so an absent deal id is never revealed.
    hidden = api.get_deal(UNKNOWN_UUIDS["deal"], {})
    validate_error(hidden, ApiErrorId.ERR_UNAUTHENTICATED.value, 401)

    # A CreditOfficer is not on this endpoint's role list, and the role gate
    # precedes request-shape parsing.
    wrong_role = api.create_pricing_node(MALFORMED_NODE, CREDIT_OFFICER)
    validate_error(wrong_role, ApiErrorId.ERR_ROLE_NOT_PERMITTED.value, 403)
    also_wrong = api.create_pricing_node(MALFORMED_NODE, REGISTRY_AGENT)
    validate_error(also_wrong, ApiErrorId.ERR_ROLE_NOT_PERMITTED.value, 403)

    # The same body under a permitted role finally reaches the enum check.
    bad_body = api.create_pricing_node(MALFORMED_NODE, ORIGINATOR)
    validate_error(bad_body, ApiErrorId.ERR_INVALID_REQUEST.value, 400)
    bad_body_analyst = api.create_pricing_node(MALFORMED_NODE,
                                               SETTLEMENT_ANALYST)
    validate_error(bad_body_analyst, ApiErrorId.ERR_INVALID_REQUEST.value, 400)

    accepted = get_success_data(api.create_pricing_node(
        f.pricing_node_payload(name="MIDWAY 2N", settlement_point_type="HUB"),
        ORIGINATOR), 201)
    assert accepted["settlement_point_type"] == "HUB", accepted
    asserts.assert_pricing_node_shape(accepted)

    # None of the refused calls persisted anything.
    rows, meta = fx.list_all(api.list_pricing_nodes(ORIGINATOR))
    assert meta["total_count"] == 2, meta
    assert sorted(asserts.ids_of(rows)) == sorted([existing["id"],
                                                   accepted["id"]]), rows


# ---------------------------------------------------------------------------
# Six roles, one lifecycle, and one endpoint whose two roles own two different
# actions.
# ---------------------------------------------------------------------------

PERIOD_START = "2026-08-01T00:00:00Z"
PERIOD_END = "2026-09-01T00:00:00Z"
HOUR_MWH = 30.0000
MINTABLE_MWH = 30
DISPUTE_REASON = "Index price for the first hour is under review."


def test_04_each_role_runs_only_the_operations_that_are_its_own(api):
    """One deal is carried from an empty database to a disputed invoice by six
    different roles, and the advance endpoint proves that clearing the role gate is
    not the same as being allowed the action: the analyst invoices and only the
    anchor's own representative disputes.

    "Money only starts moving once a deal is `EFFECTIVE`."

    "A `SettlementAnalyst` opens a settlement window by supplying `period_start`,
    the inclusive beginning of the window, and `period_end`, its exclusive end."

    "Metered hours are loaded one at a time by a `SettlementAnalyst`."

    "Running the settlement is a `SettlementAnalyst` action with no payload, and it
    is the only route by which an accepted risk claim reaches the money."

    "A `RegistryAgent` mints a batch from a period whose `status` is `CALCULATED`,
    `INVOICED` or `SETTLED`, supplying the whole-megawatt-hour `quantity_mwh` (at
    least 1) and the `registry` holding the certificates — `WREGIS`, `MRETS` or
    `NAR`."

    "`DISPUTE` requires `status` `INVOICED`, moves the period `INVOICED →
    DISPUTED`, and stores the supplied `dispute_reason`."

    "`INVOICE` and `SETTLE` are available only to a `SettlementAnalyst`; `DISPUTE`
    is available only to an `OfftakerRep`, who must be the deal's
    `anchor_offtaker_id`, and who must supply a `dispute_reason`."

    Design: Corner/rbac/each_of_the_six_roles_runs_its_own_exclusive_operations_across_one_lifecycle
    """
    chain = fx.chain_c(api)
    deal = chain["deal"]
    buyer_id = chain["buyer"]["id"]
    assert deal["status"] == "EFFECTIVE", deal
    assert deal["created_by_user_id"] == "u_orig_1", deal
    assert deal["credit_approved_by_user_id"] == "u_credit_1", deal

    # The SettlementAnalyst opens, meters and calculates.
    period = fx.open_period(api, deal["id"], PERIOD_START, PERIOD_END)
    assert period["status"] == "OPEN", period
    assert period["netting_method"] == "HOURLY", period
    assert period["interval_count"] == 0, period

    interval = fx.post_interval(api, period["id"], PERIOD_START, HOUR_MWH)
    assert interval["posted_by_user_id"] == "u_analyst_1", interval
    calculated = fx.calculate_period(api, period["id"])
    assert calculated["status"] == "CALCULATED", calculated
    asserts.assert_instant_equals(calculated["calculated_at"], fx.INITIAL_CLOCK,
                                  "calculated_at")
    asserts.assert_mwh(calculated["total_metered_mwh"], HOUR_MWH,
                       "total_metered_mwh")
    assert calculated["mintable_attributes_mwh"] == MINTABLE_MWH, calculated
    assert calculated["interval_count"] == 1, calculated

    # Minting is the RegistryAgent's exclusive operation.
    batch = fx.mint_batch(api, period["id"], MINTABLE_MWH, registry="MRETS")
    assert batch["status"] == "MINTED", batch
    assert batch["registry"] == "MRETS", batch
    assert batch["quantity_mwh"] == MINTABLE_MWH, batch

    # The advance endpoint lists two roles, and each owns different actions.
    invoiced = fx.advance_period(api, period["id"], "INVOICE")
    assert invoiced["status"] == "INVOICED", invoiced
    asserts.assert_instant_equals(invoiced["invoiced_at"], fx.INITIAL_CLOCK,
                                  "invoiced_at")

    disputed = fx.advance_period(api, period["id"], "DISPUTE",
                                 dispute_reason=DISPUTE_REASON,
                                 headers=make_offtaker_rep_headers(buyer_id))
    assert disputed["status"] == "DISPUTED", disputed
    assert disputed["dispute_reason"] == DISPUTE_REASON, disputed
    asserts.assert_version_advanced_by(invoiced["version"],
                                       disputed["version"], 1,
                                       "settlement period version")


# ---------------------------------------------------------------------------
# Three endpoints on one entity, three different role lists.
# ---------------------------------------------------------------------------

PERMIT_EVIDENCE = "CUP-2026-0301"


def test_05_one_project_carries_three_different_role_lists(api):
    """A representative may read one project but may not list them; the signing role
    may read and list but may not record a permit; and every refusal is a role
    refusal that leaves the project exactly as it was.

    "Every endpoint below is reachable only with both the `X-User-ID` and
    `X-User-Role` headers present, and only to the roles named in its last column."

    "Role authorization for the endpoint — `ERR_ROLE_NOT_PERMITTED`."

    "| GET | `/ppa/projects/{id}` | Fetch one generation project. | `Originator`,
    `CreditOfficer`, `DealCommittee`, `SettlementAnalyst`, `RegistryAgent`,
    `OfftakerRep` |"

    "| GET | `/ppa/projects` | List generation projects, filterable by `status`,
    `technology` and `node_id`. | `Originator`, `CreditOfficer`, `DealCommittee`,
    `SettlementAnalyst` |"

    "| POST | `/ppa/projects/{id}/advance-milestone` | Advance the project's
    development status one step along the permitting, notice-to-proceed,
    construction and operation path. | `Originator` |"

    "On creation, `contracted_mw` is 0 and `available_mw` equals `capacity_mw`;
    `last_milestone_at` is null and `created_by_user_id` is stamped from the acting
    operator's identifier."

    "Each advance sets `last_milestone_at` to the logical clock and increments the
    project's `version` by one."

    Design: Corner/rbac/project_single_reads_span_all_roles_while_the_list_and_the_write_are_forbidden
    """
    node = fx.create_node(api)
    buyer = fx.create_qualified_offtaker(api)
    project = fx.create_project(api, node["id"])
    rep = make_offtaker_rep_headers(buyer["id"])

    # The single read is open to the buyer's own representative.
    seen = get_success_data(api.get_project(project["id"], rep), 200)
    assert seen["status"] == "PRE_DEVELOPMENT", seen
    asserts.assert_mw(seen["contracted_mw"], 0.000, "contracted_mw")
    asserts.assert_mw(seen["available_mw"], PROJECT_CAPACITY_MW, "available_mw")
    assert seen["last_milestone_at"] is None, seen

    # The collection read is not.
    listed_by_rep = api.list_projects(rep)
    validate_error(listed_by_rep, ApiErrorId.ERR_ROLE_NOT_PERMITTED.value, 403)
    listed_by_registry = api.list_projects(REGISTRY_AGENT)
    validate_error(listed_by_registry, ApiErrorId.ERR_ROLE_NOT_PERMITTED.value,
                   403)

    rows, meta = fx.list_all(api.list_projects(SETTLEMENT_ANALYST))
    assert asserts.ids_of(rows) == [project["id"]], rows
    asserts.assert_page_meta(meta, total_count=1, limit=DEFAULT_LIMIT, offset=0,
                             has_more=False)

    # The signing role may read the project but may not move it.
    refused = api.advance_project_milestone(
        project["id"], f.advance_milestone_payload("PERMITTED", PERMIT_EVIDENCE),
        DEAL_COMMITTEE)
    validate_error(refused, ApiErrorId.ERR_ROLE_NOT_PERMITTED.value, 403)
    untouched = fx.read_project(api, project["id"], DEAL_COMMITTEE)
    assert untouched["status"] == "PRE_DEVELOPMENT", untouched
    assert untouched["last_milestone_at"] is None, untouched
    assert untouched["version"] == project["version"], untouched

    advanced = fx.advance_milestone(api, project["id"], "PERMITTED",
                                    PERMIT_EVIDENCE)
    assert advanced["status"] == "PERMITTED", advanced
    asserts.assert_instant_equals(advanced["last_milestone_at"],
                                  fx.INITIAL_CLOCK, "last_milestone_at")
    asserts.assert_version_advanced_by(project["version"], advanced["version"],
                                       1, "project version")

    # The registry operator reads the same row the Originator just moved.
    by_registry = fx.read_project(api, project["id"], REGISTRY_AGENT)
    assert by_registry["status"] == "PERMITTED", by_registry
    assert by_registry["version"] == advanced["version"], by_registry


# ---------------------------------------------------------------------------
# Two identity checks that bite on requests whose role is already correct.
# ---------------------------------------------------------------------------

OUTSIDER = {
    "legal_name": "Puget Foods Cooperative",
    "credit_rating": "AA",
    "reported_ebitda_usd": 90000000.00,
    "net_debt_to_ebitda": 1.0,
    "registry_account_id": "WREGIS-ACC-00902",
}
AGREED_PRICE = 22.75
SLICE_MW = 25.000
CP_TOTAL_COUNT = 3


def test_06_counterparty_and_signing_checks_read_the_user_id(api):
    """An outsider holding the right role is refused on both the round answer and the
    deal read, and the one operator who approved the credit is refused at signing
    even though the DealCommittee role is exactly what signing requires.

    "When `X-User-Role` is `OfftakerRep`, `X-User-ID` is the `id` of the acting
    `Offtaker`; ownership checks on any resource that references an `Offtaker`
    compare the resource's foreign-key field to `X-User-ID`."

    "Concretely, an `OfftakerRep` acting on a deal must be either that deal's
    `anchor_offtaker_id` or the `offtaker_id` of one of that deal's `CONFIRMED`
    allocations; otherwise the request is refused with
    `ERR_NOT_DEAL_COUNTERPARTY`."

    "That check is applied after existence resolution — an unknown deal still returns
    its 404 — but before any state precondition, so a non-counterparty acting on a
    wrongly-stated deal receives 403 rather than 409."

    "Buyer-side counterparty ownership for an `OfftakerRep` —
    `ERR_NOT_DEAL_COUNTERPARTY`."

    "Segregation of duties on `X-User-ID` — `ERR_SEGREGATION_OF_DUTIES`."

    "The credit decision itself belongs to a `CreditOfficer` who is not the operator
    recorded as the deal's `created_by_user_id`."

    "`APPROVE` requires that `posted_credit_support_usd` is at least
    `credit_support_required_usd`, moves the deal `SUBMITTED → APPROVED`, and stamps
    `credit_approved_by_user_id` with the deciding operator — the identifier that
    later bars that same person from executing."

    "Signing is a `DealCommittee` act with no payload, and it is the most heavily
    guarded operation in the system."

    "The acting operator must not be the one recorded as
    `credit_approved_by_user_id`."

    Design: Corner/rbac/signing_and_counterparty_checks_read_x_user_id_not_just_x_user_role
    """
    node = fx.create_node(api)
    buyer = fx.create_qualified_offtaker(api)
    outsider = fx.create_offtaker(api, **OUTSIDER)
    project = fx.create_project(api, node["id"])
    deal = fx.create_deal(api, project["id"], buyer["id"], node["id"])
    asserts.assert_money(deal["contract_price_usd_per_mwh"], AGREED_PRICE,
                         "contract_price_usd_per_mwh")
    round_one = fx.table_round(api, deal["id"],
                              response_deadline="2026-09-01T00:00:00Z")
    fx.confirmed_allocation(api, deal["id"], buyer["id"], SLICE_MW)

    outsider_rep = make_offtaker_rep_headers(outsider["id"])
    not_counterparty = api.respond_to_round(
        round_one["id"], f.round_response_payload("ACCEPT"), outsider_rep)
    validate_error(not_counterparty,
                   ApiErrorId.ERR_NOT_DEAL_COUNTERPARTY.value, 403)

    # The same gate guards the read, so an outsider cannot even see the terms.
    peeked = api.get_deal(deal["id"], outsider_rep)
    validate_error(peeked, ApiErrorId.ERR_NOT_DEAL_COUNTERPARTY.value, 403)

    rounds, _ = fx.list_all(api.list_rounds(deal["id"], ORIGINATOR))
    assert asserts.row_by_id(rounds, round_one["id"])["status"] == "OPEN", rounds
    assert fx.read_deal(api, deal["id"])["status"] == "TERM_SHEET_ISSUED", deal

    accepted = fx.respond_accept(api, round_one["id"], buyer["id"])
    assert accepted["status"] == "ACCEPTED", accepted
    agreed = fx.read_deal(api, deal["id"])
    assert agreed["status"] == "TERMS_AGREED", agreed
    asserts.assert_money(agreed["contract_price_usd_per_mwh"], AGREED_PRICE,
                         "contract_price_usd_per_mwh")

    fx.submit_credit(api, deal["id"])
    approved = fx.decide_credit(api, deal["id"], "APPROVE",
                                headers=DUAL_HAT_CREDIT_OFFICER)
    assert approved["credit_status"] == "APPROVED", approved
    assert approved["credit_approved_by_user_id"] == "u_dual_1", approved

    # The same natural person now wears the signing hat, and is refused.
    self_signed = api.execute_deal(deal["id"], DUAL_HAT_DEAL_COMMITTEE)
    validate_error(self_signed, ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value, 403)
    still_agreed = fx.read_deal(api, deal["id"])
    assert still_agreed["status"] == "TERMS_AGREED", still_agreed
    assert still_agreed["effective_at"] is None, still_agreed
    assert still_agreed["cp_total_count"] == 0, still_agreed

    executed = fx.execute_deal(api, deal["id"], DEAL_COMMITTEE_SECOND)
    assert executed["status"] == "EXECUTED", executed
    assert executed["cp_total_count"] == CP_TOTAL_COUNT, executed
    asserts.assert_money(executed["cp_completion_pct"], 0.00,
                         "cp_completion_pct")
    assert len(fx.conditions_of(api, deal["id"])) == CP_TOTAL_COUNT, executed
