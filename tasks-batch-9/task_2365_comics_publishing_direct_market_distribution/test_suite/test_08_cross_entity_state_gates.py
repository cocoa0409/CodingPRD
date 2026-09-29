"""Cross-entity state gates: a transition blocked by the state of a *different* row."""

from test_helpers import (
    ApiErrorId,
    api_client,
    assert_issue_dimensions,
    assert_issue_unit_ledgers,
    assert_version_unchanged,
    fixtures,
    validate_error,
    validate_success,
)
from test_helpers.test_users import (
    TEST_USERS,
    make_creator_headers,
    make_retailer_headers,
)


def _stage_booked_against_an_unaccepted_assignment() -> dict:
    """A `NOT_STARTED` `SCRIPT` stage booked against a still-`PROPOSED` assignment."""
    state = fixtures.setup_greenlit_title_with_script_assignment(accept=False)
    issue = fixtures.schedule_issue(state["title"]["id"])
    stage = fixtures.book_stage(issue["id"], state["assignment"]["id"], "SCRIPT")
    state.update({"issue": fixtures.read_issue(issue["id"]), "stage": stage})
    return state


def _draft_order_on_an_accepted_but_unpublished_listing() -> dict:
    """A `DRAFT` order on an issue whose accepted listing has not been published."""
    state = fixtures.setup_issue_in_scripting()
    state.update(fixtures.solicit_issue(state["issue"]["id"], publish=False))
    retailer = fixtures.open_retailer()
    order = fixtures.draft_order(retailer["id"], state["issue"]["id"])
    state.update(
        {
            "retailer": retailer,
            "order": order,
            "issue": fixtures.read_issue(state["issue"]["id"]),
        }
    )
    return state


# ─── ProductionStage -> CreativeAssignment ────────────

def test_starting_a_stage_against_a_proposed_assignment_is_refused():
    """A `NOT_STARTED` stage cannot start while its assignment is only `PROPOSED`.

    PRD: "Starting is legal from `NOT_STARTED` and from `KICKED_BACK`; from `NOT_STARTED` the referenced assignment must be `ACCEPTED` or `ACTIVE`, and from `KICKED_BACK` it must be `ACTIVE`, with any other assignment status refused as `ERR_ASSIGNMENT_NOT_ACCEPTED`."

    Design: Difficulty/cross_entity_state_dependency/stage_start_requires_the_assignment_entity_to_be_accepted
    """
    state = _stage_booked_against_an_unaccepted_assignment()
    assert state["assignment"]["status"] == "PROPOSED"
    assert state["stage"]["status"] == "NOT_STARTED"

    response = api_client.start_production_stage(
        state["stage"]["id"], make_creator_headers(state["creator"]["id"])
    )
    validate_error(response, ApiErrorId.ERR_ASSIGNMENT_NOT_ACCEPTED.value)


def test_the_refused_start_leaves_the_stage_and_the_assignment_where_they_were():
    """The rejected start writes nothing: the stage still looks freshly booked.

    PRD: "A booked stage arrives in status `NOT_STARTED` with `slip_days` 0, `kickback_count` 0, `page_fee_cents` 0, and `actual_delivered_at` and `delivered_pages` both null."

    Design: Difficulty/cross_entity_state_dependency/stage_start_requires_the_assignment_entity_to_be_accepted
    """
    state = _stage_booked_against_an_unaccepted_assignment()
    booked_stage = state["stage"]
    booked_issue = state["issue"]

    response = api_client.start_production_stage(
        booked_stage["id"], make_creator_headers(state["creator"]["id"])
    )
    validate_error(response, ApiErrorId.ERR_ASSIGNMENT_NOT_ACCEPTED.value)

    stage = fixtures.read_stage(booked_stage["id"])
    assert stage["status"] == "NOT_STARTED"
    assert stage["slip_days"] == 0
    assert stage["kickback_count"] == 0
    assert stage["page_fee_cents"] == 0
    assert stage["actual_delivered_at"] is None
    assert stage["delivered_pages"] is None
    assert_version_unchanged(booked_stage, stage)

    # Neither the other entity nor the issue derived from the stage set moved.
    assignment = fixtures.read_assignment(state["assignment"]["id"])
    assert assignment["status"] == "PROPOSED"
    assert_version_unchanged(state["assignment"], assignment)
    issue = fixtures.read_issue(booked_issue["id"])
    assert_issue_dimensions(issue, production_status=booked_issue["production_status"])
    assert_version_unchanged(booked_issue, issue)


def test_accepting_the_assignment_unblocks_the_same_stage_start():
    """Once the assignment is `ACCEPTED` the identical start succeeds and promotes it.

    PRD: "A start moves the stage to `IN_PROGRESS`, promotes the assignment `ACCEPTED → ACTIVE` where applicable, and re-derives the issue's production dimension."

    Design: Difficulty/cross_entity_state_dependency/stage_start_requires_the_assignment_entity_to_be_accepted
    """
    state = _stage_booked_against_an_unaccepted_assignment()
    creator_headers = make_creator_headers(state["creator"]["id"])

    validate_error(
        api_client.start_production_stage(state["stage"]["id"], creator_headers),
        ApiErrorId.ERR_ASSIGNMENT_NOT_ACCEPTED.value,
    )

    accepted = fixtures.accept_assignment(
        state["assignment"]["id"], state["creator"]["id"]
    )
    assert accepted["status"] == "ACCEPTED"
    assert fixtures.read_title(state["title"]["id"])["committed_share_bps"] == 5000

    started = validate_success(
        api_client.start_production_stage(state["stage"]["id"], creator_headers)
    )
    assert started["status"] == "IN_PROGRESS"
    assert fixtures.read_assignment(state["assignment"]["id"])["status"] == "ACTIVE"
    assert_issue_dimensions(
        fixtures.read_issue(state["issue"]["id"]), production_status="SCRIPTING"
    )


def test_a_countered_assignment_still_blocks_the_start_until_it_is_accepted():
    """`COUNTERED` is neither `ACCEPTED` nor `ACTIVE`, so the start waits for the deal.

    PRD: "Starting is legal from `NOT_STARTED` and from `KICKED_BACK`; from `NOT_STARTED` the referenced assignment must be `ACCEPTED` or `ACTIVE`, and from `KICKED_BACK` it must be `ACTIVE`, with any other assignment status refused as `ERR_ASSIGNMENT_NOT_ACCEPTED`."

    Design: Difficulty/cross_entity_state_dependency/stage_start_requires_the_assignment_entity_to_be_accepted
    """
    state = _stage_booked_against_an_unaccepted_assignment()
    creator_id = state["creator"]["id"]
    creator_headers = make_creator_headers(creator_id)

    countered = fixtures.counter_assignment(state["assignment"]["id"], creator_id)
    assert countered["status"] == "COUNTERED"

    validate_error(
        api_client.start_production_stage(state["stage"]["id"], creator_headers),
        ApiErrorId.ERR_ASSIGNMENT_NOT_ACCEPTED.value,
    )
    assert fixtures.read_stage(state["stage"]["id"])["status"] == "NOT_STARTED"

    fixtures.repropose_assignment(state["assignment"]["id"])
    fixtures.accept_assignment(state["assignment"]["id"], creator_id)

    started = validate_success(
        api_client.start_production_stage(state["stage"]["id"], creator_headers)
    )
    assert started["status"] == "IN_PROGRESS"
    assert fixtures.read_assignment(state["assignment"]["id"])["status"] == "ACTIVE"


# ─── RetailerOrder -> Issue ───────────────────────────

def test_submitting_an_order_against_an_unsolicited_issue_is_refused():
    """An accepted listing is not an announcement: the unpublished issue blocks the submit.

    PRD: "The issue must be `SOLICITED` for an initial order, or `ON_SALE` for a reorder, with any other commercial status refused as `ERR_ISSUE_NOT_SOLICITED`."

    Design: Difficulty/cross_entity_state_dependency/order_submit_requires_the_issue_entity_to_be_solicited
    """
    state = _draft_order_on_an_accepted_but_unpublished_listing()
    assert state["solicitation"]["status"] == "ACCEPTED"
    assert state["catalog"]["status"] == "LOCKED"
    assert_issue_dimensions(state["issue"], commercial_status="UNSOLICITED")

    # The order itself is impeccable: active account, acknowledged terms, credit free.
    assert state["retailer"]["status"] == "ACTIVE"
    assert state["retailer"]["non_returnable_ack"] is True
    assert state["retailer"]["open_balance_cents"] < state["retailer"]["credit_limit_cents"]

    response = api_client.submit_retailer_order(
        state["order"]["id"], make_retailer_headers(state["retailer"]["id"])
    )
    validate_error(response, ApiErrorId.ERR_ISSUE_NOT_SOLICITED.value)


def test_the_refused_submit_leaves_the_order_a_pristine_draft():
    """The rejected submission writes nothing onto the order or the issue's ledgers.

    PRD: "The draft arrives `DRAFT` with `total_units` 0, `earned_variant_allocations` empty, `discount_tier_applied` null, `merchandise_net_cents`, `handling_fee_cents` and `invoice_total_cents` all 0, and `cancel_reason` null."

    Design: Difficulty/cross_entity_state_dependency/order_submit_requires_the_issue_entity_to_be_solicited
    """
    state = _draft_order_on_an_accepted_but_unpublished_listing()
    drafted = state["order"]

    response = api_client.submit_retailer_order(
        drafted["id"], make_retailer_headers(state["retailer"]["id"])
    )
    validate_error(response, ApiErrorId.ERR_ISSUE_NOT_SOLICITED.value)

    order = fixtures.read_order(drafted["id"])
    assert order["status"] == "DRAFT"
    assert order["total_units"] == 0
    assert order["earned_variant_allocations"] == []
    assert order["discount_tier_applied"] is None
    assert order["merchandise_net_cents"] == 0
    assert order["handling_fee_cents"] == 0
    assert order["invoice_total_cents"] == 0
    assert order["cancel_reason"] is None
    assert_version_unchanged(drafted, order)

    issue = fixtures.read_issue(state["issue"]["id"])
    assert_issue_dimensions(issue, commercial_status="UNSOLICITED")
    assert_issue_unit_ledgers(issue, total_ordered_units=0)
    assert_version_unchanged(state["issue"], issue)


def test_publishing_the_catalog_unblocks_the_same_order_submission():
    """The fan-out to `SOLICITED` is what lets the untouched draft go through.

    PRD: "Submission moves the order `DRAFT → SUBMITTED` and is the retailer's own act on its own order."

    Design: Difficulty/cross_entity_state_dependency/order_submit_requires_the_issue_entity_to_be_solicited
    """
    state = _draft_order_on_an_accepted_but_unpublished_listing()
    retailer_headers = make_retailer_headers(state["retailer"]["id"])

    validate_error(
        api_client.submit_retailer_order(state["order"]["id"], retailer_headers),
        ApiErrorId.ERR_ISSUE_NOT_SOLICITED.value,
    )

    published = validate_success(
        api_client.publish_catalog(
            state["catalog"]["id"], TEST_USERS["sales_director_headers"]
        )
    )
    assert published["status"] == "PUBLISHED"
    assert published["published_at"] is not None
    assert_issue_dimensions(
        fixtures.read_issue(state["issue"]["id"]), commercial_status="SOLICITED"
    )

    submitted = validate_success(
        api_client.submit_retailer_order(state["order"]["id"], retailer_headers)
    )
    assert submitted["status"] == "SUBMITTED"
    assert submitted["cancel_reason"] is None


def test_the_newly_submitted_order_still_contributes_nothing_to_the_issue_ledger():
    """Clearing the gate moves the order, not the unit ledgers: those wait for the cut-off.

    PRD: "An issue's `total_ordered_units` equals the sum of `total_units` over that issue's orders whose status is `FOC_LOCKED`, `INVOICED` or `SHIPPED`; its `shipped_units` equals the same sum restricted to orders whose status is `SHIPPED`; and its `printed_units` equals the sum of `quantity` over that issue's print runs whose status is `PRINTED`."

    Design: Difficulty/cross_entity_state_dependency/order_submit_requires_the_issue_entity_to_be_solicited
    """
    state = _draft_order_on_an_accepted_but_unpublished_listing()
    retailer_headers = make_retailer_headers(state["retailer"]["id"])
    fixtures.publish_catalog(state["catalog"]["id"])

    submitted = validate_success(
        api_client.submit_retailer_order(state["order"]["id"], retailer_headers)
    )
    assert submitted["status"] == "SUBMITTED"
    assert submitted["standard_qty"] == 100

    # Allocations and total_units are frozen at the cut-off, not at submission.
    assert submitted["total_units"] == 0
    assert submitted["earned_variant_allocations"] == []

    issue = fixtures.read_issue(state["issue"]["id"])
    assert_issue_unit_ledgers(
        issue, total_ordered_units=0, printed_units=0, shipped_units=0
    )
    retailer = fixtures.read_retailer(state["retailer"]["id"])
    assert retailer["cumulative_units_ytd"] == state["retailer"]["opening_units_ytd"]
    assert retailer["open_balance_cents"] == 0
