"""Resolving identifiers and screening request shape.

The first rungs of the evaluation ladder: an unresolvable identifier names the
collection it failed in, a malformed body is refused before any lookup happens,
and a child may only be created under a parent that exists in the right
collection.
"""

from prd_bench_local_runner.testing import NON_EXISTENT_UUID, validate_success

from test_helpers import api_errors, constants, factories, fixtures
from test_helpers.assertions import (
    assert_error_envelope,
    assert_plan_account_figures,
)
from test_helpers.test_users import ADMIN_HEADERS, ANALYST_HEADERS
from test_helpers.types import (
    REVIEW_INTAKE,
    SEGREGATION_NONE,
    SOURCE_AFTER_TAX,
    SOURCE_PRE_TAX_DEFERRAL,
    SOURCE_ROTH,
)


def test_unknown_identifiers_name_the_collection_they_failed_in(client):
    """A dead identifier answers with the not-found error of its own entity type.

    PRD: "A path `{id}` that does not resolve yields the not-found error
    belonging to that entity type: `ERR_PLAN_NOT_FOUND`,
    `ERR_PARTICIPANT_NOT_FOUND`, `ERR_PLAN_ACCOUNT_NOT_FOUND`,
    `ERR_QDRO_CASE_NOT_FOUND`, `ERR_DRAFT_ORDER_NOT_FOUND`,
    `ERR_SEGREGATION_HOLD_NOT_FOUND`, `ERR_AP_ACCOUNT_NOT_FOUND`,
    `ERR_DISTRIBUTION_NOT_FOUND`, `ERR_AUTHORIZATION_NOT_FOUND`, or
    `ERR_TAX_REPORT_NOT_FOUND`, each with HTTP 404."

    Design: Corner/entities/unknown_path_and_body_ids_return_collection_specific_not_found
    """
    ghost = NON_EXISTENT_UUID
    path_reads = [
        ("plans", client.get_plan(ghost, ADMIN_HEADERS)),
        ("participants", client.get_participant(ghost, ADMIN_HEADERS)),
        ("plan-accounts", client.get_plan_account(ghost, ADMIN_HEADERS)),
        ("qdro-cases", client.get_qdro_case(ghost, ADMIN_HEADERS)),
        ("draft-orders", client.get_draft_order(ghost, ANALYST_HEADERS)),
        ("segregation-holds", client.get_segregation_hold(ghost, ADMIN_HEADERS)),
        (
            "alternate-payee-accounts",
            client.get_alternate_payee_account(ghost, ADMIN_HEADERS),
        ),
        ("distributions", client.get_distribution(ghost, ADMIN_HEADERS)),
        (
            "attorney-authorizations",
            client.revoke_attorney_authorization(ghost, ADMIN_HEADERS),
        ),
        ("tax-reports", client.get_tax_report(ghost, ADMIN_HEADERS)),
    ]
    for collection, response in path_reads:
        expected = api_errors.NOT_FOUND_BY_COLLECTION[collection]
        assert_error_envelope(response, expected, 404)

    # A nested list resolves its parent path segment, not its own collection.
    assert_error_envelope(
        client.list_deficiency_notices(ghost, ADMIN_HEADERS),
        api_errors.ERR_DRAFT_ORDER_NOT_FOUND,
        404,
    )
    assert_error_envelope(
        client.list_money_sources(ghost, ADMIN_HEADERS),
        api_errors.ERR_PLAN_ACCOUNT_NOT_FOUND,
        404,
    )
    assert_error_envelope(
        client.list_plan_participants(ghost, ADMIN_HEADERS),
        api_errors.ERR_PLAN_NOT_FOUND,
        404,
    )

    # A body foreign key resolves to the very same identifier and status.
    assert_error_envelope(
        client.create_participant(factories.participant_payload(ghost), ADMIN_HEADERS),
        api_errors.ERR_PLAN_NOT_FOUND,
        404,
    )
    assert_error_envelope(
        client.create_qdro_case(factories.qdro_case_payload(ghost), ADMIN_HEADERS),
        api_errors.ERR_PARTICIPANT_NOT_FOUND,
        404,
    )


def test_a_malformed_body_is_refused_before_any_identifier_is_resolved(client):
    """Request shape is screened ahead of path existence and ahead of concurrency.

    PRD: "This ordering is part of the contract: two independently invalid
    requests that differ only in which rung they trip must produce different
    error identifiers, and a request that is invalid on several rungs at once
    must report the earliest one."

    Design: Corner/entities/missing_required_input_fields_are_rejected_before_any_lookup
    """
    setup = fixtures.setup_plan_account(
        client, "Screening Plan", fixtures.SINGLE_SOURCE
    )
    fixtures.set_clock(client, constants.CLOCK_2026_09_01)

    assert_error_envelope(
        client.create_plan(
            factories.omit(factories.plan_payload(), "plan_name"), ADMIN_HEADERS
        ),
        api_errors.ERR_INVALID_REQUEST,
        400,
    )
    assert_error_envelope(
        client.create_qdro_case(
            factories.omit(
                factories.qdro_case_payload(setup["participant"]["id"]),
                "valuation_date",
            ),
            ADMIN_HEADERS,
        ),
        api_errors.ERR_INVALID_REQUEST,
        400,
    )
    assert_error_envelope(
        client.create_valuation_snapshot(
            setup["account"]["id"],
            factories.omit(
                factories.valuation_snapshot_payload("2026-06-30", 1000000),
                "balance_cents",
            ),
            ADMIN_HEADERS,
        ),
        api_errors.ERR_INVALID_REQUEST,
        400,
    )

    case = fixtures.open_case(client, setup["participant"]["id"])
    missing_version = client.create_draft_order(
        factories.omit(
            factories.draft_order_payload(case["id"], case["version"]),
            "expected_case_version",
        ),
        ADMIN_HEADERS,
    )
    # The absent concurrency token is a shape fault, never a stale version.
    assert_error_envelope(missing_version, api_errors.ERR_INVALID_REQUEST, 400)

    # Shape sits on rung 3 and path existence on rung 4, so a body fault on a
    # request aimed at a dead identifier reports the body fault.
    both_wrong = client.deny_draft_order(NON_EXISTENT_UUID, {}, ADMIN_HEADERS)
    assert_error_envelope(both_wrong, api_errors.ERR_INVALID_REQUEST, 400)

    # None of the refusals moved the case along either of its two dimensions.
    unchanged = fixtures.read_case(client, case["id"])
    assert unchanged["review_status"] == REVIEW_INTAKE
    assert unchanged["segregation_status"] == SEGREGATION_NONE
    assert unchanged["version"] == 1
    assert fixtures.read_holds(client, qdro_case_id=case["id"]) == []


def test_undeclared_literals_and_out_of_range_numbers_are_refused(client):
    """Enum vocabularies and numeric ranges are closed, and nothing is coerced.

    PRD: "Every non-optional input field is present; every enum-typed field
    carries a declared literal; every integer field whose name ends in `_cents`,
    `_bps`, or `_days` is zero or greater; calendar dates are ISO 8601 calendar
    dates and datetimes are ISO 8601 UTC instants; when both are supplied,
    `marital_period_start` is strictly earlier than `marital_period_end`; and
    `assigned_percentage_bps` and its proposed counterpart do not exceed 10000."

    Design: Corner/entities/enum_and_range_constraints_refuse_undeclared_literals
    """
    setup = fixtures.setup_plan_account(
        client, "Vocabulary Plan", fixtures.SINGLE_SOURCE
    )
    plan_id = setup["plan"]["id"]
    account_id = setup["account"]["id"]
    fixtures.set_clock(client, constants.CLOCK_2026_09_01)
    case = fixtures.open_case(client, setup["participant"]["id"])

    refusals = [
        client.create_plan(
            factories.plan_payload(
                plan_name="Rejected Plan", plan_type="DEFINED_BENEFIT"
            ),
            ADMIN_HEADERS,
        ),
        client.create_plan(
            factories.plan_payload(
                plan_name="Rejected Plan", max_assignable_pct_bps=constants.MAX_BPS + 1
            ),
            ADMIN_HEADERS,
        ),
        client.create_participant(
            factories.participant_payload(plan_id, ssn_last4="12A4"), ADMIN_HEADERS
        ),
        client.create_money_source(
            account_id,
            factories.money_source_payload(
                SOURCE_AFTER_TAX, 50000, basis_cents=60000
            ),
            ADMIN_HEADERS,
        ),
        client.create_money_source(
            account_id, factories.money_source_payload(SOURCE_ROTH, -1), ADMIN_HEADERS
        ),
        client.create_qdro_case(
            factories.qdro_case_payload(
                setup["participant"]["id"],
                marital_period_start="2020-01-01",
                marital_period_end="2020-01-01",
            ),
            ADMIN_HEADERS,
        ),
        client.create_attorney_authorization(
            case["id"],
            factories.attorney_authorization_payload(
                effective_from="2026-08-01", expires_at="2026-08-01T00:00:00Z"
            ),
            ADMIN_HEADERS,
        ),
        client.create_draft_order(
            factories.draft_order_payload(
                case["id"],
                case["version"],
                proposed_percentage_bps=constants.MAX_BPS + 1,
            ),
            ADMIN_HEADERS,
        ),
    ]
    for response in refusals:
        assert_error_envelope(response, api_errors.ERR_INVALID_REQUEST, 400)

    # Every refusal was total: no partially written row survives any of them.
    assert list(fixtures.money_source_balances(client, account_id)) == [
        SOURCE_PRE_TAX_DEFERRAL
    ]
    cases = validate_success(
        client.list_participant_qdro_cases(setup["participant"]["id"], ADMIN_HEADERS)
    )
    assert [row["id"] for row in cases] == [case["id"]]
    assert (
        validate_success(
            client.list_attorney_authorizations(case["id"], ADMIN_HEADERS)
        )
        == []
    )
    assert_plan_account_figures(
        fixtures.read_plan_account(client, account_id),
        vested_balance_cents=1000000,
        assignable_base_cents=1000000,
    )


def test_a_child_needs_a_parent_that_lives_in_the_right_collection(client):
    """A nested creation resolves its parent segment before it writes anything.

    PRD: "Foreign keys supplied inside a request body are resolved with the same
    errors and the same status."

    Design: Corner/entities/child_creation_requires_a_resolvable_parent_in_the_right_collection
    """
    setup = fixtures.setup_plan_account(
        client, "Topology Guard Plan", fixtures.SINGLE_SOURCE
    )
    fixtures.set_clock(client, constants.CLOCK_2026_09_01)
    case = fixtures.open_case(client, setup["participant"]["id"])
    ghost = NON_EXISTENT_UUID

    assert_error_envelope(
        client.create_money_source(
            ghost,
            factories.money_source_payload(SOURCE_AFTER_TAX, 100000),
            ADMIN_HEADERS,
        ),
        api_errors.ERR_PLAN_ACCOUNT_NOT_FOUND,
        404,
    )
    assert_error_envelope(
        client.create_valuation_snapshot(
            ghost, factories.valuation_snapshot_payload("2026-06-30", 100000),
            ADMIN_HEADERS,
        ),
        api_errors.ERR_PLAN_ACCOUNT_NOT_FOUND,
        404,
    )
    assert_error_envelope(
        client.open_plan_account(ghost, factories.plan_account_payload(), ADMIN_HEADERS),
        api_errors.ERR_PARTICIPANT_NOT_FOUND,
        404,
    )
    assert_error_envelope(
        client.create_attorney_authorization(
            ghost, factories.attorney_authorization_payload(), ADMIN_HEADERS
        ),
        api_errors.ERR_QDRO_CASE_NOT_FOUND,
        404,
    )
    assert_error_envelope(
        client.create_communication(
            ghost, factories.communication_payload(), ANALYST_HEADERS
        ),
        api_errors.ERR_QDRO_CASE_NOT_FOUND,
        404,
    )

    # The draft order carries its parent in the body rather than the path.
    assert_error_envelope(
        client.create_draft_order(
            factories.draft_order_payload(ghost, 1), ADMIN_HEADERS
        ),
        api_errors.ERR_QDRO_CASE_NOT_FOUND,
        404,
    )
    # Shape precedes body foreign-key resolution, so an undeclared approach on
    # the same dead parent reports the shape fault instead.
    assert_error_envelope(
        client.create_draft_order(
            factories.draft_order_payload(
                ghost, 1, proposed_approach="JOINT_INTEREST"
            ),
            ADMIN_HEADERS,
        ),
        api_errors.ERR_INVALID_REQUEST,
        400,
    )

    accepted = fixtures.receive_draft(client, case["id"], case["version"])
    found = validate_success(
        client.list_draft_orders(ADMIN_HEADERS, {"qdro_case_id": case["id"]})
    )
    assert [row["id"] for row in found] == [accepted["id"]]


def test_holds_stay_bound_to_both_branches_of_the_hierarchy(client):
    """Each hold answers to exactly one case and exactly one funding account.

    PRD: "`held_amount_cents` is the sum of `hold_amount_cents` over the
    segregation holds on the account whose `status` is `HELD`; holds in
    `CONVERTED`, `RELEASED`, or `EXPIRED` contribute zero."

    Design: Corner/entities/cross_aggregate_associations_are_validated_across_the_hierarchy
    """
    plan = fixtures.create_published_plan(client, plan_name="Topology Plan")
    first = fixtures.enroll_participant(
        client, plan["id"], full_name="Anja Lindqvist", ssn_last4="1111"
    )
    second = fixtures.enroll_participant(
        client, plan["id"], full_name="Bo Lindqvist", ssn_last4="2222"
    )
    first_account = fixtures.open_plan_account(client, first["id"])
    fixtures.add_money_source(
        client, first_account["id"], SOURCE_PRE_TAX_DEFERRAL, 1000000
    )
    second_account = fixtures.open_plan_account(client, second["id"])
    fixtures.add_money_source(
        client, second_account["id"], SOURCE_PRE_TAX_DEFERRAL, 500000
    )
    fixtures.set_clock(client, constants.CLOCK_2026_09_01)

    # Two adjacent, non-overlapping marital periods on the first participant.
    case_one = fixtures.open_case(
        client,
        first["id"],
        alternate_payee_name="Cecilia Lindqvist",
        marital_period_start="2005-06-01",
        marital_period_end="2015-01-01",
    )
    fixtures.receive_draft(
        client, case_one["id"], case_one["version"], proposed_percentage_bps=3000
    )
    case_two = fixtures.open_case(
        client,
        first["id"],
        alternate_payee_name="Dagny Lindqvist",
        marital_period_start="2015-01-01",
        marital_period_end="2024-01-01",
    )
    fixtures.receive_draft(
        client,
        case_two["id"],
        case_two["version"],
        document_reference="DRO-2663-T2",
        proposed_percentage_bps=2000,
    )
    case_three = fixtures.open_case(
        client, second["id"], alternate_payee_name="Eira Lindqvist"
    )
    fixtures.receive_draft(
        client,
        case_three["id"],
        case_three["version"],
        document_reference="DRO-2663-T3",
        proposed_percentage_bps=4000,
    )

    by_account = fixtures.read_holds(client, plan_account_id=first_account["id"])
    assert {row["qdro_case_id"] for row in by_account} == {
        case_one["id"],
        case_two["id"],
    }
    assert sorted(row["hold_amount_cents"] for row in by_account) == [200000, 300000]

    by_case = fixtures.read_holds(client, qdro_case_id=case_one["id"])
    assert len(by_case) == 1
    assert by_case[0]["plan_account_id"] == first_account["id"]
    assert by_case[0]["hold_amount_cents"] == 300000

    other = fixtures.read_holds(client, plan_account_id=second_account["id"])
    assert [row["qdro_case_id"] for row in other] == [case_three["id"]]
    assert other[0]["hold_amount_cents"] == 200000

    assert_plan_account_figures(
        fixtures.read_plan_account(client, first_account["id"]),
        vested_balance_cents=1000000,
        held_amount_cents=500000,
        available_balance_cents=500000,
    )
    assert_plan_account_figures(
        fixtures.read_plan_account(client, second_account["id"]),
        vested_balance_cents=500000,
        held_amount_cents=200000,
        available_balance_cents=300000,
    )
    assert validate_success(client.get_plan(plan["id"], ADMIN_HEADERS))[
        "participant_count"
    ] == 2

    cases_of_first = validate_success(
        client.list_participant_qdro_cases(first["id"], ADMIN_HEADERS)
    )
    assert {row["id"] for row in cases_of_first} == {case_one["id"], case_two["id"]}
    cases_of_second = validate_success(
        client.list_participant_qdro_cases(second["id"], ADMIN_HEADERS)
    )
    assert [row["id"] for row in cases_of_second] == [case_three["id"]]
