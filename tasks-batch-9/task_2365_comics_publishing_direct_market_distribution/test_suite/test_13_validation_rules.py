"""Validation rules: uniqueness, state gates, timing windows and check ordering."""

from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    api_client,
    assert_instant_equals,
    assert_invoice_figures,
    assert_issue_dimensions,
    assert_issue_unit_ledgers,
    assert_retailer_ledgers,
    assert_version_advanced,
    assert_version_unchanged,
    factories,
    fixtures,
    make_creator_headers,
    make_retailer_headers,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.test_users import TEST_USERS

STANDARD_COVER_ONLY = (fixtures.DEFAULT_COVER_SPECS[0],)


def _solicited_issue_with_retailer(**retailer_overrides) -> dict:
    """A `SOLICITED` issue plus one retailer account, built through the API."""
    state = fixtures.setup_solicited_issue_in_scripting(
        cover_specs=STANDARD_COVER_ONLY
    )
    state["retailer"] = fixtures.open_retailer(**retailer_overrides)
    return state


def test_a_repeated_issue_number_is_refused_even_when_the_cadence_buffer_is_clear():
    """A second Issue #1 is refused as a duplicate number, not as a cadence conflict.

    PRD: "Each issue declares its `issue_number` within the title (at least 1, and unique among that title's issues, with a repeat refused as `ERR_DUPLICATE_ISSUE_NUMBER`), its interior `page_count` (from 1 to 64), its standard `cover_price_cents` (at least 1), and its planned direct-market `target_on_sale_date`."

    Design: Corner/validations/violation_to_error_duplicate_issue_number_is_rejected
    """
    fixtures.set_clock()
    title = fixtures.pitch_and_greenlight_title()
    first = fixtures.schedule_issue(
        title["id"], issue_number=1, target_on_sale_date="2026-10-14"
    )
    before = fixtures.read_title(title["id"])

    # 2026-11-11 is 28 days after 2026-10-14, so the 21-day cadence buffer holds.
    response = api_client.create_issue(
        title["id"],
        factories.issue_payload(issue_number=1, target_on_sale_date="2026-11-11"),
        TEST_USERS["managing_editor_headers"],
    )
    validate_error(response, ApiErrorId.ERR_DUPLICATE_ISSUE_NUMBER.value)

    rows, meta = validate_paginated(
        api_client.list_title_issues(
            title["id"],
            TEST_USERS["managing_editor_headers"],
            {"limit": 100, "offset": 0},
        )
    )
    assert meta["total_count"] == 1, meta
    assert len(rows) == 1, rows

    surviving = fixtures.read_issue(first["id"])
    assert_instant_equals(surviving["target_on_sale_date"], "2026-10-14T00:00:00Z")
    assert_instant_equals(surviving["foc_date"], "2026-09-23T00:00:00Z")
    assert_version_unchanged(before, fixtures.read_title(title["id"]))


def test_submitting_a_draft_order_against_a_solicited_issue_stamps_the_clock():
    """A draft order whose four submission gates all hold moves to `SUBMITTED`.

    PRD: "Submission moves the order `DRAFT → SUBMITTED` and is the retailer's own act on its own order."

    Design: Corner/validations/satisfaction_to_pass_order_submit_clears_all_four_gates_at_once
    """
    state = _solicited_issue_with_retailer(credit_limit_cents=5_000_000)
    retailer = state["retailer"]
    assert retailer["status"] == "ACTIVE"
    assert retailer["non_returnable_ack"] is True
    assert retailer["open_balance_cents"] < retailer["credit_limit_cents"]
    assert_issue_dimensions(state["issue"], commercial_status="SOLICITED")

    order = fixtures.draft_order(retailer["id"], state["issue"]["id"], standard_qty=100)
    assert order["status"] == "DRAFT"

    submitted = validate_success(
        api_client.submit_retailer_order(
            order["id"], make_retailer_headers(retailer["id"])
        )
    )
    assert submitted["status"] == "SUBMITTED"
    assert_version_advanced(order, submitted)


def test_a_submitted_order_leaves_every_unit_ledger_at_zero():
    """`SUBMITTED` sits outside the qualifying set, so no counter moves at submission.

    PRD: "Orders in `DRAFT`, `SUBMITTED` or `CANCELLED` contribute nothing to any of these figures, which is exactly what makes order cancellation an exact compensating action rather than an approximate one."

    Design: Corner/validations/satisfaction_to_pass_order_submit_clears_all_four_gates_at_once
    """
    state = _solicited_issue_with_retailer(credit_limit_cents=5_000_000)
    retailer = state["retailer"]

    order = fixtures.draft_and_submit_order(
        retailer["id"], state["issue"]["id"], standard_qty=100
    )
    assert order["status"] == "SUBMITTED"
    assert order["total_units"] == 0
    assert order["earned_variant_allocations"] == []
    assert_invoice_figures(
        order,
        merchandise_net_cents=0,
        handling_fee_cents=0,
        invoice_total_cents=0,
    )
    assert order["discount_tier_applied"] is None

    assert_retailer_ledgers(
        fixtures.read_retailer(retailer["id"]),
        cumulative_units_ytd=0,
        open_balance_cents=0,
        discount_tier="ENTRY",
    )
    issue = fixtures.read_issue(state["issue"]["id"])
    assert_issue_unit_ledgers(issue, total_ordered_units=0)
    assert_issue_dimensions(issue, commercial_status="SOLICITED")


def test_scheduling_an_issue_under_a_pitched_title_is_refused():
    """A pitch is not staffable, so the issue creation is refused outright.

    PRD: "Only from that point may creative assignments and issues be created; either attempt against a `PITCHED`, `COMPLETED` or `CANCELLED` title is refused with `ERR_TITLE_NOT_GREENLIT`, while a title that has moved on to `IN_PRODUCTION` or `PUBLISHING` remains staffable."

    Design: Corner/validations/cross_entity_validation_issue_creation_depends_on_the_titles_state
    """
    fixtures.set_clock()
    title = fixtures.pitch_title()
    assert title["status"] == "PITCHED"

    response = api_client.create_issue(
        title["id"],
        factories.issue_payload(issue_number=1, target_on_sale_date="2026-10-14"),
        TEST_USERS["managing_editor_headers"],
    )
    validate_error(response, ApiErrorId.ERR_TITLE_NOT_GREENLIT.value)

    after = fixtures.read_title(title["id"])
    assert after["status"] == "PITCHED"
    assert_version_unchanged(title, after)
    _, meta = validate_paginated(
        api_client.list_title_issues(
            title["id"],
            TEST_USERS["managing_editor_headers"],
            {"limit": 100, "offset": 0},
        )
    )
    assert meta["total_count"] == 0, meta


def test_the_same_issue_body_is_accepted_once_the_title_is_greenlit():
    """After the greenlight the identical body creates the issue and bubbles the title.

    PRD: "Creating the very first issue of a title also moves that title from `GREENLIT` to `IN_PRODUCTION` and bumps its `version`."

    Design: Corner/validations/cross_entity_validation_issue_creation_depends_on_the_titles_state
    """
    fixtures.set_clock()
    title = fixtures.pitch_title()
    greenlit = fixtures.greenlight(title["id"])
    assert greenlit["status"] == "GREENLIT"

    issue = validate_success(
        api_client.create_issue(
            title["id"],
            factories.issue_payload(issue_number=1, target_on_sale_date="2026-10-14"),
            TEST_USERS["managing_editor_headers"],
        ),
        expected_status=201,
    )
    assert_instant_equals(issue["foc_date"], "2026-09-23T00:00:00Z")

    after = fixtures.read_title(title["id"])
    assert after["status"] == "IN_PRODUCTION"
    assert_version_advanced(greenlit, after)


def test_a_retailer_may_replace_its_quantity_while_the_cut_off_is_still_ahead():
    """An adjustment before the `foc_date` replaces `standard_qty` and keeps the status.

    PRD: "A retailer may adjust its own `SUBMITTED` order repeatedly, replacing `standard_qty` with the newly requested quantity and, when supplied, replacing `exclusive_variant_qty` as well; the order stays `SUBMITTED` and only its `version` moves."

    Design: Corner/validations/temporal_validation_order_adjust_is_legal_before_foc_and_rejected_on_the_foc_date
    """
    state = _solicited_issue_with_retailer(credit_limit_cents=5_000_000)
    retailer = state["retailer"]
    order = fixtures.draft_and_submit_order(
        retailer["id"], state["issue"]["id"], standard_qty=100
    )

    fixtures.set_clock("2026-09-22T00:00:00Z")
    adjusted = validate_success(
        api_client.adjust_retailer_order(
            order["id"],
            factories.adjust_payload(standard_qty=150),
            make_retailer_headers(retailer["id"]),
        )
    )
    assert adjusted["standard_qty"] == 150
    assert adjusted["status"] == "SUBMITTED"
    assert_version_advanced(order, adjusted)


def test_an_adjustment_on_the_foc_date_itself_is_refused():
    """The cut-off instant is already too late, so the last legal quantity stands.

    PRD: "Adjustment is a pre-cut-off privilege: the logical clock must be strictly before the issue's `foc_date`, and an attempt at or after that instant is refused with `ERR_FOC_ALREADY_PASSED`."

    Design: Corner/validations/temporal_validation_order_adjust_is_legal_before_foc_and_rejected_on_the_foc_date
    """
    state = _solicited_issue_with_retailer(credit_limit_cents=5_000_000)
    retailer = state["retailer"]
    assert_instant_equals(state["issue"]["foc_date"], "2026-09-23T00:00:00Z")

    order = fixtures.draft_and_submit_order(
        retailer["id"], state["issue"]["id"], standard_qty=100
    )
    fixtures.set_clock("2026-09-22T00:00:00Z")
    adjusted = fixtures.adjust_order(order["id"], retailer["id"], standard_qty=150)
    assert adjusted["standard_qty"] == 150

    fixtures.set_clock("2026-09-23T00:00:00Z")
    response = api_client.adjust_retailer_order(
        order["id"],
        factories.adjust_payload(standard_qty=200),
        make_retailer_headers(retailer["id"]),
    )
    validate_error(response, ApiErrorId.ERR_FOC_ALREADY_PASSED.value)

    unchanged = fixtures.read_order(order["id"])
    assert unchanged["standard_qty"] == 150
    assert unchanged["status"] == "SUBMITTED"
    assert_version_unchanged(adjusted, unchanged)


def test_the_second_acceptance_that_would_fill_the_royalty_pool_is_refused():
    """Two individually legal 5000-bps shares cannot both be committed under an 8500-bps budget.

    PRD: "An acceptance that would push the roster past that ceiling is refused with `ERR_ROYALTY_SHARE_POOL_EXCEEDED`."

    Design: Corner/validations/aggregate_validation_two_individually_legal_shares_exceed_the_royalty_pool
    """
    fixtures.set_clock()
    writer = fixtures.register_creator(
        full_name="Wanda Writer", crafts=["SCRIPT"], default_page_rate_cents=12000
    )
    coauthor = fixtures.register_creator(
        full_name="Vic Coauthor", crafts=["SCRIPT"], default_page_rate_cents=11000
    )
    title = fixtures.pitch_and_greenlight_title(cover_participation_bps=1500)

    writer_assignment = fixtures.offer_assignment(
        title["id"],
        writer["id"],
        "SCRIPT",
        page_rate_cents=12000,
        royalty_share_bps=5000,
        booking_start_date="2026-08-01",
        booking_end_date="2026-09-01",
    )
    coauthor_assignment = fixtures.offer_assignment(
        title["id"],
        coauthor["id"],
        "SCRIPT",
        page_rate_cents=11000,
        royalty_share_bps=5000,
        booking_start_date="2026-09-01",
        booking_end_date="2026-10-01",
    )
    fixtures.accept_assignment(writer_assignment["id"], writer["id"])
    before = fixtures.read_title(title["id"])
    assert before["committed_share_bps"] == 5000

    response = api_client.accept_creative_assignment(
        coauthor_assignment["id"], make_creator_headers(coauthor["id"])
    )
    validate_error(response, ApiErrorId.ERR_ROYALTY_SHARE_POOL_EXCEEDED.value)

    refused = fixtures.read_assignment(coauthor_assignment["id"])
    assert refused["status"] == "PROPOSED"
    assert_version_unchanged(coauthor_assignment, refused)
    assert fixtures.read_assignment(writer_assignment["id"])["status"] == "ACCEPTED"

    after = fixtures.read_title(title["id"])
    assert after["committed_share_bps"] == 5000
    assert_version_unchanged(before, after)
    assert fixtures.read_creator(coauthor["id"])["active_assignment_count"] == 1


def test_the_non_returnable_gate_stops_only_the_unacknowledged_account():
    """One retailer's missing acknowledgement blocks it while the acknowledged one submits.

    PRD: "A retailer account carries a `non_returnable_ack` flag, and until that flag is true the account may neither submit an order nor be invoiced; either attempt is rejected with `ERR_NON_RETURNABLE_ACK_REQUIRED`."

    Design: Corner/validations/conditional_validation_non_returnable_ack_gate_applies_only_to_the_unacknowledged_retailer
    """
    state = fixtures.setup_solicited_issue_in_scripting(cover_specs=STANDARD_COVER_ONLY)
    issue_id = state["issue"]["id"]

    acknowledged = fixtures.open_retailer(
        account_no="DM-1001",
        name="Panel Palace",
        credit_limit_cents=5_000_000,
        non_returnable_ack=True,
    )
    unacknowledged = fixtures.open_retailer(
        account_no="DM-1009",
        name="Returns Barn",
        credit_limit_cents=5_000_000,
        non_returnable_ack=False,
    )
    good_order = fixtures.draft_order(acknowledged["id"], issue_id, standard_qty=100)
    blocked_order = fixtures.draft_order(
        unacknowledged["id"], issue_id, standard_qty=100
    )

    response = api_client.submit_retailer_order(
        blocked_order["id"], make_retailer_headers(unacknowledged["id"])
    )
    validate_error(response, ApiErrorId.ERR_NON_RETURNABLE_ACK_REQUIRED.value)

    still_draft = fixtures.read_order(blocked_order["id"])
    assert still_draft["status"] == "DRAFT"
    assert_version_unchanged(blocked_order, still_draft)

    submitted = validate_success(
        api_client.submit_retailer_order(
            good_order["id"], make_retailer_headers(acknowledged["id"])
        )
    )
    assert submitted["status"] == "SUBMITTED"
    assert fixtures.read_retailer(unacknowledged["id"])["non_returnable_ack"] is False
    assert fixtures.read_retailer(acknowledged["id"])["non_returnable_ack"] is True


def test_an_unknown_issue_id_is_reported_before_the_exclusive_cover_check():
    """The body-referenced issue must resolve first, so the 404 wins over the 422.

    PRD: "Identifiers named in a request body must resolve, each reporting its own code: `creator_id` yields `ERR_CREATOR_NOT_FOUND`, `assignment_id` yields `ERR_ASSIGNMENT_NOT_FOUND`, `issue_id` yields `ERR_ISSUE_NOT_FOUND`, `retailer_id` yields `ERR_RETAILER_NOT_FOUND`, `title_id` yields `ERR_TITLE_NOT_FOUND`, and a member of `variant_cover_ids` that does not exist, or that belongs to a different issue than the one being solicited, yields `ERR_VARIANT_COVER_NOT_FOUND`."

    Design: Corner/validations/cascading_validation_body_reference_existence_runs_before_the_variant_availability_check
    """
    fixtures.set_clock()
    title = fixtures.pitch_and_greenlight_title()
    issue = fixtures.schedule_issue(title["id"])
    fixtures.add_cover(issue["id"], code="A", kind="STANDARD", cover_price_cents=399)
    retailer = fixtures.open_retailer(credit_limit_cents=5_000_000)

    response = api_client.create_retailer_order(
        factories.order_payload(
            retailer["id"],
            NON_EXISTENT_UUID,
            standard_qty=100,
            exclusive_variant_qty=5,
        ),
        make_retailer_headers(retailer["id"]),
    )
    validate_error(response, ApiErrorId.ERR_ISSUE_NOT_FOUND.value)

    _, meta = validate_paginated(
        api_client.list_retailer_orders(
            TEST_USERS["sales_director_headers"], {"limit": 100, "offset": 0}
        )
    )
    assert meta["total_count"] == 0, meta


def test_an_exclusive_request_without_an_exclusive_cover_is_refused():
    """Once the issue resolves, the missing `RETAILER_EXCLUSIVE` cover is what refuses the draft.

    PRD: "A positive exclusive request requires the issue to actually carry a `RETAILER_EXCLUSIVE` cover, or the draft is refused with `ERR_VARIANT_NOT_AVAILABLE`."

    Design: Corner/validations/cascading_validation_body_reference_existence_runs_before_the_variant_availability_check
    """
    fixtures.set_clock()
    title = fixtures.pitch_and_greenlight_title()
    issue = fixtures.schedule_issue(title["id"])
    fixtures.add_cover(issue["id"], code="A", kind="STANDARD", cover_price_cents=399)
    retailer = fixtures.open_retailer(credit_limit_cents=5_000_000)

    response = api_client.create_retailer_order(
        factories.order_payload(
            retailer["id"], issue["id"], standard_qty=100, exclusive_variant_qty=5
        ),
        make_retailer_headers(retailer["id"]),
    )
    validate_error(response, ApiErrorId.ERR_VARIANT_NOT_AVAILABLE.value)

    order = validate_success(
        api_client.create_retailer_order(
            factories.order_payload(
                retailer["id"], issue["id"], standard_qty=100, exclusive_variant_qty=0
            ),
            make_retailer_headers(retailer["id"]),
        ),
        expected_status=201,
    )
    assert order["exclusive_variant_qty"] == 0

    rows, meta = validate_paginated(
        api_client.list_retailer_orders(
            TEST_USERS["sales_director_headers"], {"limit": 100, "offset": 0}
        )
    )
    assert meta["total_count"] == 1, meta
    assert [row["id"] for row in rows] == [order["id"]]


def test_an_unauthorized_role_cannot_probe_which_title_ids_exist():
    """Role authorization is evaluated before path existence, so the refusal is the 403.

    PRD: "Beyond path resolution, several checks may be applicable to the same request, and the order in which they are evaluated is part of the contract, because it decides which error a client sees."

    Design: Corner/validations/priority_ordering_role_check_at_priority_2_beats_existence_at_priority_4
    """
    fixtures.set_clock()

    response = api_client.greenlight_title(
        NON_EXISTENT_UUID, TEST_USERS["managing_editor_headers"]
    )
    validate_error(response, ApiErrorId.ERR_UNAUTHORIZED.value)

    _, meta = validate_paginated(
        api_client.list_titles(
            TEST_USERS["editor_in_chief_headers"], {"limit": 100, "offset": 0}
        )
    )
    assert meta["total_count"] == 0, meta


def test_the_authorized_role_sees_the_missing_title_as_a_not_found():
    """With the role check satisfied, the same absent identifier reports its own 404.

    PRD: "Each identifier has its own 404 code — `ERR_TITLE_NOT_FOUND`, `ERR_ISSUE_NOT_FOUND`, `ERR_CREATOR_NOT_FOUND`, `ERR_ASSIGNMENT_NOT_FOUND`, `ERR_STAGE_NOT_FOUND`, `ERR_CATALOG_NOT_FOUND`, `ERR_SOLICITATION_NOT_FOUND`, `ERR_RETAILER_NOT_FOUND`, `ERR_ORDER_NOT_FOUND`, `ERR_PRINT_RUN_NOT_FOUND` and `ERR_STATEMENT_NOT_FOUND` — and the code reported is the one belonging to the leftmost missing segment."

    Design: Corner/validations/priority_ordering_role_check_at_priority_2_beats_existence_at_priority_4
    """
    fixtures.set_clock()

    response = api_client.greenlight_title(
        NON_EXISTENT_UUID, TEST_USERS["editor_in_chief_headers"]
    )
    validate_error(response, ApiErrorId.ERR_TITLE_NOT_FOUND.value)

    _, meta = validate_paginated(
        api_client.list_titles(
            TEST_USERS["editor_in_chief_headers"], {"limit": 100, "offset": 0}
        )
    )
    assert meta["total_count"] == 0, meta
