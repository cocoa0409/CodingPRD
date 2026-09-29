"""Role authorization and entity-backed ownership: who may act, and on whose rows."""

from test_helpers import (
    ApiErrorId,
    api_client,
    assert_ids_in_order,
    assert_retailer_ledgers,
    assert_statement_money,
    assert_version_advanced,
    assert_version_unchanged,
    factories,
    fixtures,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.test_users import (
    TEST_USERS,
    make_creator_headers,
    make_retailer_headers,
)


def test_both_editorial_roles_may_register_a_creator():
    """`EditorInChief` and `ManagingEditor` each register a creator successfully.

    PRD: "If the header pair is well formed but the named role does not appear in the authorized-role list for the requested endpoint (see §4), the request is rejected with `ERR_UNAUTHORIZED`."

    Design: Corner/rbac/role_allowed_creator_registration_is_open_to_both_editorial_roles
    """
    fixtures.set_clock(headers=TEST_USERS["editor_in_chief_headers"])

    writer = validate_success(
        api_client.create_creator(
            factories.creator_payload(
                full_name="Wanda Writer",
                crafts=["SCRIPT"],
                default_page_rate_cents=12000,
            ),
            TEST_USERS["editor_in_chief_headers"],
        ),
        expected_status=201,
    )
    inker = validate_success(
        api_client.create_creator(
            factories.creator_payload(
                full_name="Ida Inker",
                crafts=["INKS", "LETTERS"],
                default_page_rate_cents=7000,
            ),
            TEST_USERS["managing_editor_headers"],
        ),
        expected_status=201,
    )

    assert writer["crafts"] == ["SCRIPT"]
    assert writer["active_assignment_count"] == 0
    assert inker["crafts"] == ["INKS", "LETTERS"]
    assert inker["default_page_rate_cents"] == 7000
    assert inker["active_assignment_count"] == 0


def test_the_royalty_accountant_lists_the_roster_both_editors_wrote():
    """A read-only role on this resource sees both editors' creators in one page.

    PRD: "List responses carry `limit`, `offset`, `total_count` and `has_more` inside the `meta` object of the envelope, where `total_count` is the number of rows matching the filters before pagination is applied and `has_more` states whether further rows exist beyond the current page."

    Design: Corner/rbac/role_allowed_creator_registration_is_open_to_both_editorial_roles
    """
    fixtures.set_clock(headers=TEST_USERS["editor_in_chief_headers"])

    writer = validate_success(
        api_client.create_creator(
            factories.creator_payload(full_name="Wanda Writer", crafts=["SCRIPT"]),
            TEST_USERS["editor_in_chief_headers"],
        ),
        expected_status=201,
    )
    inker = validate_success(
        api_client.create_creator(
            factories.creator_payload(
                full_name="Ida Inker",
                crafts=["INKS", "LETTERS"],
                default_page_rate_cents=7000,
            ),
            TEST_USERS["managing_editor_headers"],
        ),
        expected_status=201,
    )

    rows, meta = validate_paginated(
        api_client.list_creators(
            TEST_USERS["royalty_accountant_headers"], params={"limit": 100, "offset": 0}
        )
    )
    assert meta["total_count"] == 2
    assert meta["has_more"] is False
    assert_ids_in_order(rows, [writer["id"], inker["id"]])


def test_a_retailer_may_not_greenlight_a_pitched_title():
    """Greenlighting is the editor-in-chief's act, so a retailer identity is refused.

    PRD: "No role may perform another's exclusive work."

    Design: Corner/rbac/role_denied_a_retailer_cannot_greenlight_and_a_salesdirector_cannot_create_issues
    """
    fixtures.set_clock(headers=TEST_USERS["editor_in_chief_headers"])
    retailer = fixtures.open_retailer(
        account_no="DM-1001", name="Panel Palace", credit_limit_cents=5_000_000
    )
    title = fixtures.pitch_title()

    response = api_client.greenlight_title(
        title["id"], make_retailer_headers(retailer["id"])
    )
    validate_error(response, ApiErrorId.ERR_UNAUTHORIZED.value)

    unchanged = fixtures.read_title(title["id"])
    assert unchanged["status"] == "PITCHED"
    assert unchanged["greenlit_at"] is None
    assert_version_unchanged(title, unchanged)


def test_the_wrong_role_on_issue_creation_is_refused_before_the_greenlight_gate():
    """A `SalesDirector` scheduling an issue on a `PITCHED` title sees the role refusal.

    PRD: "Beyond path resolution, several checks may be applicable to the same request, and the order in which they are evaluated is part of the contract, because it decides which error a client sees."

    Design: Corner/rbac/role_denied_a_retailer_cannot_greenlight_and_a_salesdirector_cannot_create_issues
    """
    fixtures.set_clock(headers=TEST_USERS["editor_in_chief_headers"])
    title = fixtures.pitch_title()

    response = api_client.create_issue(
        title["id"],
        factories.issue_payload(),
        TEST_USERS["sales_director_headers"],
    )
    validate_error(response, ApiErrorId.ERR_UNAUTHORIZED.value)

    rows, meta = validate_paginated(
        api_client.list_title_issues(
            title["id"], TEST_USERS["managing_editor_headers"]
        )
    )
    assert meta["total_count"] == 0
    assert rows == []
    unchanged = fixtures.read_title(title["id"])
    assert unchanged["status"] == "PITCHED"
    assert_version_unchanged(title, unchanged)


def test_a_creator_may_not_open_a_solicitation_catalog():
    """The commercial surface belongs to the sales director, not to a creator identity.

    PRD: "Duties are deliberately segregated: `EditorInChief` owns the title portfolio and the creative-terms surface, `ManagingEditor` owns the issue slate and the production board, `SalesDirector` owns the entire commercial surface (catalogs, covers, retailer accounts, the order cut-off, invoicing, shipping and release), and `RoyaltyAccountant` owns the money-out surface (revenue events and royalty statements)."

    Design: Corner/rbac/role_denied_a_retailer_cannot_greenlight_and_a_salesdirector_cannot_create_issues
    """
    fixtures.set_clock(headers=TEST_USERS["editor_in_chief_headers"])
    creator = fixtures.register_all_craft_creator()

    response = api_client.create_catalog(
        factories.catalog_payload(), make_creator_headers(creator["id"])
    )
    validate_error(response, ApiErrorId.ERR_UNAUTHORIZED.value)

    rows, meta = validate_paginated(
        api_client.list_catalogs(TEST_USERS["sales_director_headers"])
    )
    assert meta["total_count"] == 0
    assert rows == []


def test_a_creator_may_not_cut_a_royalty_statement_for_a_colleague():
    """The money-out surface refuses a `Creator` identity on statement creation.

    PRD: "Duties are deliberately segregated: `EditorInChief` owns the title portfolio and the creative-terms surface, `ManagingEditor` owns the issue slate and the production board, `SalesDirector` owns the entire commercial surface (catalogs, covers, retailer accounts, the order cut-off, invoicing, shipping and release), and `RoyaltyAccountant` owns the money-out surface (revenue events and royalty statements)."

    Design: Corner/rbac/role_denied_a_creator_cannot_cut_or_issue_a_statement_but_may_read_one
    """
    state = fixtures.setup_royalty_revenue_ledger()
    title_id = state["title"]["id"]
    writer = state["creators"]["SCRIPT"]
    penciller = state["creators"]["PENCILS"]
    fixtures.create_statement(
        title_id, writer["id"], period="2026-12", basis="ESTIMATED"
    )

    response = api_client.create_royalty_statement(
        factories.statement_payload(
            title_id, penciller["id"], period="2026-12", basis="ESTIMATED"
        ),
        make_creator_headers(writer["id"]),
    )
    validate_error(response, ApiErrorId.ERR_UNAUTHORIZED.value)

    rows, meta = validate_paginated(
        api_client.list_royalty_statements(
            TEST_USERS["royalty_accountant_headers"],
            params={"title_id": title_id, "creator_id": penciller["id"]},
        )
    )
    assert meta["total_count"] == 0
    assert rows == []
    assert fixtures.read_title(title_id)["royalty_accrued_cents"] == 0


def test_a_creator_may_not_issue_the_statement_cut_in_their_name():
    """Posting a statement to the ledgers stays with the accountant.

    PRD: "Issuing a statement is a `RoyaltyAccountant` act from `DRAFT`."

    Design: Corner/rbac/role_denied_a_creator_cannot_cut_or_issue_a_statement_but_may_read_one
    """
    state = fixtures.setup_royalty_revenue_ledger()
    title_id = state["title"]["id"]
    writer = state["creators"]["SCRIPT"]
    statement = fixtures.create_statement(
        title_id, writer["id"], period="2026-12", basis="ESTIMATED"
    )

    response = api_client.issue_royalty_statement(
        statement["id"], make_creator_headers(writer["id"])
    )
    validate_error(response, ApiErrorId.ERR_UNAUTHORIZED.value)

    unchanged = fixtures.read_statement(statement["id"])
    assert unchanged["status"] == "DRAFT"
    assert unchanged["issued_by_user_id"] is None
    assert_version_unchanged(statement, unchanged)
    assert fixtures.read_title(title_id)["royalty_accrued_cents"] == 0
    assignment = fixtures.read_assignment(state["assignments"]["SCRIPT"]["id"])
    assert assignment["unrecouped_advance_cents"] == 25000


def test_a_creator_reads_the_statement_the_accountant_computed():
    """The same `Creator` identity that is denied the writes is allowed the read.

    PRD: "If the header pair is well formed but the named role does not appear in the authorized-role list for the requested endpoint (see §4), the request is rejected with `ERR_UNAUTHORIZED`."

    Design: Corner/rbac/role_denied_a_creator_cannot_cut_or_issue_a_statement_but_may_read_one
    """
    state = fixtures.setup_royalty_revenue_ledger()
    writer = state["creators"]["SCRIPT"]
    statement = fixtures.create_statement(
        state["title"]["id"], writer["id"], period="2026-12", basis="ESTIMATED"
    )

    read = validate_success(
        api_client.get_royalty_statement(
            statement["id"], make_creator_headers(writer["id"])
        )
    )
    assert read["id"] == statement["id"]
    assert read["status"] == "DRAFT"
    assert_statement_money(
        read,
        gross_royalty_cents=85432,
        recoupment_applied_cents=25000,
        payable_cents=60432,
    )


def test_a_creator_may_not_accept_a_colleagues_creative_assignment():
    """The writer's identity cannot accept the penciller's offer.

    PRD: "An entity-backed identity acting on a resource it does not own is rejected with `ERR_FORBIDDEN_RESOURCE`."

    Design: Corner/rbac/forbidden_resource_a_creator_cannot_act_on_another_creators_assignment_or_stage
    """
    state = fixtures.setup_issue_in_scripting(
        creator_overrides={"full_name": "Wanda Writer", "crafts": ["SCRIPT"]},
        stage_overrides={
            "planned_start_date": "2026-08-05",
            "planned_due_date": "2026-09-20",
        },
    )
    title_id = state["title"]["id"]
    penciller = fixtures.register_creator(
        full_name="Pablo Penciller", crafts=["PENCILS"], default_page_rate_cents=9000
    )
    pencils = fixtures.offer_assignment(
        title_id,
        penciller["id"],
        "PENCILS",
        page_rate_cents=9000,
        royalty_share_bps=3000,
        booking_start_date="2026-08-01",
        booking_end_date="2026-12-01",
    )

    response = api_client.accept_creative_assignment(
        pencils["id"], make_creator_headers(state["creator"]["id"])
    )
    validate_error(response, ApiErrorId.ERR_FORBIDDEN_RESOURCE.value)

    unchanged = fixtures.read_assignment(pencils["id"])
    assert unchanged["status"] == "PROPOSED"
    assert_version_unchanged(pencils, unchanged)
    assert fixtures.read_title(title_id)["committed_share_bps"] == 5000


def test_a_creator_may_not_deliver_another_creators_production_stage():
    """Stage ownership follows the `creator_id` of the assignment the stage was booked under.

    PRD: "When `X-User-Role` is `Creator`, `X-User-ID` is the `id` of the acting `Creator` record; ownership checks on any resource that references a `Creator` compare that resource's `creator_id` to `X-User-ID`, and for a production stage the comparison is made against the `creator_id` of the assignment the stage was booked under."

    Design: Corner/rbac/forbidden_resource_a_creator_cannot_act_on_another_creators_assignment_or_stage
    """
    state = fixtures.setup_issue_in_scripting(
        creator_overrides={"full_name": "Wanda Writer", "crafts": ["SCRIPT"]},
        stage_overrides={
            "planned_start_date": "2026-08-05",
            "planned_due_date": "2026-09-20",
        },
    )
    penciller = fixtures.register_creator(
        full_name="Pablo Penciller", crafts=["PENCILS"], default_page_rate_cents=9000
    )
    fixtures.offer_assignment(
        state["title"]["id"],
        penciller["id"],
        "PENCILS",
        page_rate_cents=9000,
        royalty_share_bps=3000,
        booking_start_date="2026-08-01",
        booking_end_date="2026-12-01",
    )
    stage = state["stage"]

    response = api_client.deliver_production_stage(
        stage["id"],
        factories.deliver_payload(delivered_pages=22),
        make_creator_headers(penciller["id"]),
    )
    validate_error(response, ApiErrorId.ERR_FORBIDDEN_RESOURCE.value)

    unchanged = fixtures.read_stage(stage["id"])
    assert unchanged["status"] == "IN_PROGRESS"
    assert unchanged["delivered_pages"] is None
    assert unchanged["actual_delivered_at"] is None
    assert unchanged["slip_days"] == 0
    assert_version_unchanged(stage, unchanged)


def test_the_named_creator_accepts_their_own_assignment_and_commits_the_pool():
    """The owner's own acceptance passes the ownership check and moves the roster.

    PRD: "On success the assignment becomes `ACCEPTED` and the title's `committed_share_bps` — the sum of `royalty_share_bps` over its non-`COVER` assignments whose status is `ACCEPTED`, `ACTIVE` or `COMPLETED` — is recomputed."

    Design: Corner/rbac/forbidden_resource_a_creator_cannot_act_on_another_creators_assignment_or_stage
    """
    state = fixtures.setup_issue_in_scripting(
        creator_overrides={"full_name": "Wanda Writer", "crafts": ["SCRIPT"]},
        stage_overrides={
            "planned_start_date": "2026-08-05",
            "planned_due_date": "2026-09-20",
        },
    )
    title_id = state["title"]["id"]
    penciller = fixtures.register_creator(
        full_name="Pablo Penciller", crafts=["PENCILS"], default_page_rate_cents=9000
    )
    pencils = fixtures.offer_assignment(
        title_id,
        penciller["id"],
        "PENCILS",
        page_rate_cents=9000,
        royalty_share_bps=3000,
        booking_start_date="2026-08-01",
        booking_end_date="2026-12-01",
    )

    accepted = validate_success(
        api_client.accept_creative_assignment(
            pencils["id"], make_creator_headers(penciller["id"])
        )
    )
    assert accepted["status"] == "ACCEPTED"
    assert_version_advanced(pencils, accepted)
    assert fixtures.read_title(title_id)["committed_share_bps"] == 8000


def test_a_retailer_may_not_submit_another_accounts_order():
    """Order ownership compares the row's `retailer_id` to the acting identity.

    PRD: "When `X-User-Role` is `Retailer`, `X-User-ID` is the `id` of the acting `Retailer` record; ownership checks on any resource that references a `Retailer` compare that resource's `retailer_id` to `X-User-ID`."

    Design: Corner/rbac/forbidden_resource_a_retailer_cannot_order_or_submit_on_another_account
    """
    state = fixtures.setup_solicited_issue_in_scripting()
    issue = state["issue"]
    panel_palace = fixtures.open_retailer(
        account_no="DM-1001", name="Panel Palace", credit_limit_cents=5_000_000
    )
    order = fixtures.draft_order(panel_palace["id"], issue["id"], standard_qty=100)
    splash_page = fixtures.open_retailer(
        account_no="DM-1002", name="Splash Page Comics", credit_limit_cents=5_000_000
    )

    response = api_client.submit_retailer_order(
        order["id"], make_retailer_headers(splash_page["id"])
    )
    validate_error(response, ApiErrorId.ERR_FORBIDDEN_RESOURCE.value)

    unchanged = fixtures.read_order(order["id"])
    assert unchanged["status"] == "DRAFT"
    assert unchanged["total_units"] == 0
    assert_version_unchanged(order, unchanged)
    assert_retailer_ledgers(
        fixtures.read_retailer(splash_page["id"]),
        cumulative_units_ytd=0,
        open_balance_cents=0,
        discount_tier="ENTRY",
    )


def test_a_drafted_order_must_name_the_acting_retailers_own_account():
    """Ownership is enforced on the body's `retailer_id`, not only on the path.

    PRD: "This ownership check guards exactly eight operations: countering an assignment, accepting an assignment, starting a production stage, delivering a production stage, drafting a retailer order (where the body's `retailer_id` must itself equal `X-User-ID`), submitting an order, adjusting an order, and cancelling an order."

    Design: Corner/rbac/forbidden_resource_a_retailer_cannot_order_or_submit_on_another_account
    """
    state = fixtures.setup_solicited_issue_in_scripting()
    issue = state["issue"]
    panel_palace = fixtures.open_retailer(
        account_no="DM-1001", name="Panel Palace", credit_limit_cents=5_000_000
    )
    order = fixtures.draft_order(panel_palace["id"], issue["id"], standard_qty=100)
    splash_page = fixtures.open_retailer(
        account_no="DM-1002", name="Splash Page Comics", credit_limit_cents=5_000_000
    )

    response = api_client.create_retailer_order(
        factories.order_payload(panel_palace["id"], issue["id"], standard_qty=25),
        make_retailer_headers(splash_page["id"]),
    )
    validate_error(response, ApiErrorId.ERR_FORBIDDEN_RESOURCE.value)

    rows, meta = validate_paginated(
        api_client.list_retailer_orders(
            TEST_USERS["sales_director_headers"], params={"issue_id": issue["id"]}
        )
    )
    assert meta["total_count"] == 1
    assert_ids_in_order(rows, [order["id"]])
    unchanged = fixtures.read_order(order["id"])
    assert unchanged["status"] == "DRAFT"
    assert unchanged["standard_qty"] == 100
    assert_version_unchanged(order, unchanged)


def test_the_owning_retailer_submits_the_order_it_drafted_for_itself():
    """The account that owns the order passes the ownership check and submits it.

    PRD: "Submission moves the order `DRAFT → SUBMITTED` and is the retailer's own act on its own order."

    Design: Corner/rbac/forbidden_resource_a_retailer_cannot_order_or_submit_on_another_account
    """
    state = fixtures.setup_solicited_issue_in_scripting()
    issue = state["issue"]
    panel_palace = fixtures.open_retailer(
        account_no="DM-1001", name="Panel Palace", credit_limit_cents=5_000_000
    )
    order = fixtures.draft_order(panel_palace["id"], issue["id"], standard_qty=100)

    submitted = validate_success(
        api_client.submit_retailer_order(
            order["id"], make_retailer_headers(panel_palace["id"])
        )
    )
    assert submitted["status"] == "SUBMITTED"
    assert submitted["retailer_id"] == panel_palace["id"]
    assert_version_advanced(order, submitted)
    # A SUBMITTED order has not reached any ledger yet.
    assert_retailer_ledgers(
        fixtures.read_retailer(panel_palace["id"]),
        cumulative_units_ytd=0,
        open_balance_cents=0,
    )
    assert fixtures.read_issue(issue["id"])["total_ordered_units"] == 0
