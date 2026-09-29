"""Money the system holds is let go only by an explicit act, and never twice.

Two rules govern the locked funds from opposite directions. The release reads a
state that belongs to another entity entirely, so the same hold id answers a
different error as its own status changes; and the capacity ceiling is collective,
so an assignment that is legal on its own terms can still be refused because of
what else is in flight on the same account.
"""

from test_helpers import api_errors, constants, factories, fixtures
from test_helpers.assertions import (
    assert_case_dimensions,
    assert_communication_sequence,
    assert_error_envelope,
    assert_hold,
    assert_plan_account_figures,
    assert_statuses_in_order,
)
from test_helpers.test_users import ADMIN_HEADERS, ANALYST_HEADERS
from test_helpers.types import (
    APPROACH_SEPARATE_INTEREST,
    CODE_MISSING_MODEL_LANGUAGE,
    DENIAL_ORDER_NOT_QUALIFIABLE,
    DISCLOSURE_FULL,
    DISCLOSURE_LIMITED,
    DRAFT_DENIED,
    EARNINGS_PERIOD_END,
    FORMULA_PERCENTAGE_OF_ACCOUNT,
    HOLD_HELD,
    HOLD_RELEASED,
    ORIGIN_SYSTEM,
    RECIPIENT_ALTERNATE_PAYEE,
    RECIPIENT_PARTICIPANT,
    REVIEW_DENIED,
    REVIEW_INTAKE,
    REVIEW_UNDER_REVIEW,
    SEGREGATION_HELD,
    SEGREGATION_NONE,
    SEGREGATION_RELEASED_TO_PARTICIPANT,
    SOURCE_PRE_TAX_DEFERRAL,
    TEMPLATE_DETERMINATION_DENIED,
    TEMPLATE_RECEIPT_ACKNOWLEDGMENT,
    TEMPLATE_RELEASE_NOTICE,
)

RELEASE_PLAN = {
    "acceptable_formula_codes": [FORMULA_PERCENTAGE_OF_ACCOUNT],
    "allowed_approaches": [APPROACH_SEPARATE_INTEREST],
    "earnings_adjustment_method": EARNINGS_PERIOD_END,
    "requires_model_language": True,
    "permits_benefit_not_otherwise_available": False,
    "max_assignable_pct_bps": 5000,
    "max_assignable_amount_cents": 2000000,
}

# Four adjacent, non-overlapping marital periods on one participant, so four
# cases may be in flight against the single plan account at once.
ADJACENT_PERIODS = [
    ("Payee One", "1971-01-01", "2000-01-01", "2006-01-01"),
    ("Payee Two", "1972-02-02", "2006-01-01", "2012-01-01"),
    ("Payee Three", "1973-03-03", "2012-01-01", "2018-01-01"),
    ("Payee Four", "1974-04-04", "2018-01-01", "2024-01-01"),
]


def _held_and_deficient(client, plan_name, reference="DRO-2663-R1"):
    """A held case whose live draft is faulty, so a denial is available."""
    setup = fixtures.setup_case_with_held_hold(
        client,
        plan_name,
        plan_overrides=RELEASE_PLAN,
        participant_overrides={
            "full_name": "Teodoro Vasquez",
            "ssn_last4": "4410",
            "date_of_birth": "1974-04-04",
            "participation_start_date": "2010-01-01",
        },
        case_overrides={
            "alternate_payee_name": "Rosalia Vasquez",
            "alternate_payee_dob": "1977-09-09",
            "marital_period_start": "2012-03-01",
            "marital_period_end": "2026-02-01",
        },
        draft_overrides={
            "document_reference": reference,
            "uses_model_language": False,
        },
    )
    assert setup["draft"]["deficiency_codes"] == [CODE_MISSING_MODEL_LANGUAGE]
    assert setup["hold"]["status"] == HOLD_HELD
    assert setup["hold"]["hold_amount_cents"] == 400000
    assert_plan_account_figures(
        setup["account"],
        vested_balance_cents=1000000,
        held_amount_cents=400000,
        available_balance_cents=600000,
    )
    return setup


def test_the_release_reads_a_state_that_is_not_the_hold_s_own(client):
    """A HELD hold on a live case cannot be released, and a denial keeps it HELD.

    PRD: "One thing the denial deliberately does *not* do is let the money go:
    the segregation hold stays `HELD` and the account's
    `available_balance_cents` stays depressed. Restoring the funds is a separate,
    explicit second act."

    Design: Difficulty/cross_entity_state_dependency/hold_release_blocked_until_case_review_status_denied
    """
    setup = _held_and_deficient(client, "Release Gate Plan")
    case_id = setup["case"]["id"]
    hold_id = setup["hold"]["id"]
    account_id = setup["account"]["id"]

    # The hold's own status admits the release; the case's review track refuses it.
    assert_error_envelope(
        client.release_segregation_hold(hold_id, ADMIN_HEADERS),
        api_errors.ERR_CASE_NOT_DENIED,
        409,
    )
    assert fixtures.read_hold(client, hold_id)["status"] == HOLD_HELD
    assert_plan_account_figures(
        fixtures.read_plan_account(client, account_id),
        held_amount_cents=400000,
        available_balance_cents=600000,
    )
    assert_case_dimensions(
        fixtures.read_case(client, case_id),
        review_status=REVIEW_UNDER_REVIEW,
        segregation_status=SEGREGATION_HELD,
        version=2,
    )

    # The denial ends the review track but deliberately leaves the money locked.
    denied = fixtures.deny(client, setup["draft"]["id"], DENIAL_ORDER_NOT_QUALIFIABLE)
    assert denied["status"] == DRAFT_DENIED
    assert denied["denial_reason"] == DENIAL_ORDER_NOT_QUALIFIABLE
    assert_hold(
        fixtures.read_hold(client, hold_id),
        status=HOLD_HELD,
        hold_amount_cents=400000,
        segregation_date=None,
    )
    assert_plan_account_figures(
        fixtures.read_plan_account(client, account_id),
        held_amount_cents=400000,
        available_balance_cents=600000,
    )
    assert_case_dimensions(
        fixtures.read_case(client, case_id),
        review_status=REVIEW_DENIED,
        segregation_status=SEGREGATION_HELD,
        version=3,
    )

    # Only now does the same request against the same hold id succeed.
    released = fixtures.release_hold(client, hold_id)
    assert released["status"] == HOLD_RELEASED
    assert released["segregation_date"] is None
    assert_plan_account_figures(
        fixtures.read_plan_account(client, account_id),
        vested_balance_cents=1000000,
        held_amount_cents=0,
        available_balance_cents=1000000,
    )
    assert_case_dimensions(
        fixtures.read_case(client, case_id),
        review_status=REVIEW_DENIED,
        segregation_status=SEGREGATION_RELEASED_TO_PARTICIPANT,
        version=4,
    )


def test_the_replay_is_refused_by_the_hold_s_own_state_instead(client):
    """The second release answers a different error id and moves no money.

    PRD: "Release moves the hold `HELD → RELEASED`, recomputes the account's
    derived balances so that `held_amount_cents` drops and
    `available_balance_cents` is fully restored to `vested_balance_cents`, moves
    the case's `segregation_status` to `RELEASED_TO_PARTICIPANT`, increments the
    case's `version` by one"

    Design: Difficulty/cross_entity_state_dependency/hold_release_blocked_until_case_review_status_denied
    """
    setup = _held_and_deficient(client, "Release Replay Plan", "DRO-2663-R2")
    case_id = setup["case"]["id"]
    hold_id = setup["hold"]["id"]
    account_id = setup["account"]["id"]

    fixtures.deny(client, setup["draft"]["id"], DENIAL_ORDER_NOT_QUALIFIABLE)
    assert fixtures.release_hold(client, hold_id)["status"] == HOLD_RELEASED

    # The case is still DENIED, so the cross-entity gate would pass; the hold's
    # own status is what answers now.
    assert_error_envelope(
        client.release_segregation_hold(hold_id, ADMIN_HEADERS),
        api_errors.ERR_HOLD_NOT_HELD,
        409,
    )
    assert_hold(
        fixtures.read_hold(client, hold_id),
        status=HOLD_RELEASED,
        hold_amount_cents=400000,
        placed_at=constants.CLOCK_2026_09_01,
        segregation_date=None,
    )
    assert_plan_account_figures(
        fixtures.read_plan_account(client, account_id),
        vested_balance_cents=1000000,
        held_amount_cents=0,
        available_balance_cents=1000000,
    )
    assert_case_dimensions(
        fixtures.read_case(client, case_id),
        review_status=REVIEW_DENIED,
        segregation_status=SEGREGATION_RELEASED_TO_PARTICIPANT,
        version=4,
    )
    assert_statuses_in_order(
        fixtures.read_holds(client, qdro_case_id=case_id), [HOLD_RELEASED]
    )

    # Five letters: the receipt, the denial pair, the release pair. The refused
    # replay appended no sixth.
    assert_communication_sequence(
        fixtures.read_communications(client, case_id),
        [
            (RECIPIENT_PARTICIPANT, TEMPLATE_RECEIPT_ACKNOWLEDGMENT,
             DISCLOSURE_LIMITED, ORIGIN_SYSTEM),
            (RECIPIENT_PARTICIPANT, TEMPLATE_DETERMINATION_DENIED,
             DISCLOSURE_FULL, ORIGIN_SYSTEM),
            (RECIPIENT_ALTERNATE_PAYEE, TEMPLATE_DETERMINATION_DENIED,
             DISCLOSURE_LIMITED, ORIGIN_SYSTEM),
            (RECIPIENT_PARTICIPANT, TEMPLATE_RELEASE_NOTICE,
             DISCLOSURE_FULL, ORIGIN_SYSTEM),
            (RECIPIENT_ALTERNATE_PAYEE, TEMPLATE_RELEASE_NOTICE,
             DISCLOSURE_LIMITED, ORIGIN_SYSTEM),
        ],
    )


def _four_cases_on_one_account(client, plan_name):
    """One account, four intake cases with adjacent marital periods."""
    setup = fixtures.setup_plan_account(
        client,
        plan_name,
        sources=[(SOURCE_PRE_TAX_DEFERRAL, 1000000, {"basis_cents": 0})],
        plan_overrides=RELEASE_PLAN,
        participant_overrides={
            "full_name": "Emeric Szabo",
            "ssn_last4": "7070",
            "date_of_birth": "1968-08-08",
            "participation_start_date": "1996-01-01",
        },
    )
    assert_plan_account_figures(
        setup["account"],
        vested_balance_cents=1000000,
        assignable_base_cents=1000000,
        held_amount_cents=0,
        available_balance_cents=1000000,
    )
    fixtures.set_clock(client, constants.CLOCK_2026_09_01)
    setup["cases"] = [
        fixtures.open_case(
            client,
            setup["participant"]["id"],
            alternate_payee_name=payee_name,
            alternate_payee_dob=payee_dob,
            marital_period_start=period_start,
            marital_period_end=period_end,
        )
        for payee_name, payee_dob, period_start, period_end in ADJACENT_PERIODS
    ]
    for case in setup["cases"]:
        assert_case_dimensions(
            case,
            review_status=REVIEW_INTAKE,
            segregation_status=SEGREGATION_NONE,
            version=1,
        )
    return setup


def test_two_legal_assignments_coexist_but_the_third_overflows_the_account(client):
    """Each order is well under the ceiling; their simultaneous custody is not.

    PRD: "If that total is **strictly greater** than the account's
    `vested_balance_cents`, the request is refused with
    `ERR_HOLD_CAPACITY_EXCEEDED`; exposure exactly equal to the vested balance is
    permitted."

    Design: Difficulty/resource_temporal_overlap/aggregate_segregation_hold_capacity_refused_though_each_is_legal
    """
    setup = _four_cases_on_one_account(client, "Capacity Plan")
    cases = setup["cases"]
    account_id = setup["account"]["id"]

    first = fixtures.receive_draft(
        client, cases[0]["id"], cases[0]["version"], document_reference="DRO-2663-C1"
    )
    assert first["deficiency_codes"] == []
    fixtures.receive_draft(
        client,
        cases[1]["id"],
        cases[1]["version"],
        document_reference="DRO-2663-C2",
        uses_model_language=False,
    )
    assert_plan_account_figures(
        fixtures.read_plan_account(client, account_id),
        vested_balance_cents=1000000,
        held_amount_cents=800000,
        available_balance_cents=200000,
    )

    # The candidate is 3000 bps of the assignable base — 300000 — not 3000 bps
    # of the 200000 that happens to be available, so 1100000 overflows.
    assert_error_envelope(
        client.create_draft_order(
            factories.draft_order_payload(
                cases[2]["id"],
                cases[2]["version"],
                document_reference="DRO-2663-C3-too-big",
                proposed_percentage_bps=3000,
            ),
            ANALYST_HEADERS,
        ),
        api_errors.ERR_HOLD_CAPACITY_EXCEEDED,
        409,
    )
    assert_case_dimensions(
        fixtures.read_case(client, cases[2]["id"]),
        review_status=REVIEW_INTAKE,
        segregation_status=SEGREGATION_NONE,
        version=1,
    )
    assert fixtures.read_holds(client, qdro_case_id=cases[2]["id"]) == []
    assert_plan_account_figures(
        fixtures.read_plan_account(client, account_id),
        held_amount_cents=800000,
        available_balance_cents=200000,
    )

    # The case version was never consumed, so the retry may reuse it: 200000
    # brings the total to exactly the vested balance, which is permitted.
    retried = fixtures.receive_draft(
        client,
        cases[2]["id"],
        cases[2]["version"],
        document_reference="DRO-2663-C3",
        proposed_percentage_bps=2000,
    )
    assert retried["qdro_case_id"] == cases[2]["id"]
    third_hold = fixtures.hold_for_case(client, cases[2]["id"])
    assert_hold(third_hold, status=HOLD_HELD, hold_amount_cents=200000)
    assert_plan_account_figures(
        fixtures.read_plan_account(client, account_id),
        vested_balance_cents=1000000,
        held_amount_cents=1000000,
        available_balance_cents=0,
    )

    # Fully committed, the account cannot take even a 100 bps assignment.
    assert_error_envelope(
        client.create_draft_order(
            factories.draft_order_payload(
                cases[3]["id"],
                cases[3]["version"],
                document_reference="DRO-2663-C4-early",
                proposed_percentage_bps=100,
            ),
            ANALYST_HEADERS,
        ),
        api_errors.ERR_HOLD_CAPACITY_EXCEEDED,
        409,
    )
    assert fixtures.read_holds(client, qdro_case_id=cases[3]["id"]) == []


def test_releasing_an_earlier_hold_restores_capacity_for_the_refused_request(client):
    """A RELEASED hold leaves the aggregate, so the identical filing now fits.

    PRD: "holds in `CONVERTED`, `RELEASED`, or `EXPIRED` are excluded entirely,
    which is how an expired hold frees capacity for the next order"

    Design: Difficulty/resource_temporal_overlap/aggregate_segregation_hold_capacity_refused_though_each_is_legal
    """
    setup = _four_cases_on_one_account(client, "Capacity Release Plan")
    cases = setup["cases"]
    account_id = setup["account"]["id"]

    fixtures.receive_draft(
        client, cases[0]["id"], cases[0]["version"], document_reference="DRO-2663-D1"
    )
    faulty = fixtures.receive_draft(
        client,
        cases[1]["id"],
        cases[1]["version"],
        document_reference="DRO-2663-D2",
        uses_model_language=False,
    )
    fixtures.receive_draft(
        client,
        cases[2]["id"],
        cases[2]["version"],
        document_reference="DRO-2663-D3",
        proposed_percentage_bps=2000,
    )
    assert_plan_account_figures(
        fixtures.read_plan_account(client, account_id),
        held_amount_cents=1000000,
        available_balance_cents=0,
    )
    fourth_filing = factories.draft_order_payload(
        cases[3]["id"],
        cases[3]["version"],
        document_reference="DRO-2663-D4",
        proposed_percentage_bps=100,
    )
    assert_error_envelope(
        client.create_draft_order(fourth_filing, ANALYST_HEADERS),
        api_errors.ERR_HOLD_CAPACITY_EXCEEDED,
        409,
    )

    # The second case is denied and its hold released, which takes 400000 of
    # exposure out of the sum without touching any money source.
    fixtures.deny(client, faulty["id"], DENIAL_ORDER_NOT_QUALIFIABLE)
    second_hold = fixtures.hold_for_case(client, cases[1]["id"])
    assert fixtures.release_hold(client, second_hold["id"])["status"] == HOLD_RELEASED
    assert_plan_account_figures(
        fixtures.read_plan_account(client, account_id),
        vested_balance_cents=1000000,
        held_amount_cents=600000,
        available_balance_cents=400000,
    )

    # The byte-identical request that was refused a moment ago now succeeds.
    accepted = fixtures.receive_draft(
        client,
        cases[3]["id"],
        cases[3]["version"],
        document_reference="DRO-2663-D4",
        proposed_percentage_bps=100,
    )
    assert accepted["qdro_case_id"] == cases[3]["id"]
    assert_hold(
        fixtures.hold_for_case(client, cases[3]["id"]),
        status=HOLD_HELD,
        hold_amount_cents=10000,
    )
    assert_plan_account_figures(
        fixtures.read_plan_account(client, account_id),
        vested_balance_cents=1000000,
        held_amount_cents=610000,
        available_balance_cents=390000,
    )
    assert_statuses_in_order(
        fixtures.read_holds(client, plan_account_id=account_id),
        [HOLD_HELD, HOLD_RELEASED, HOLD_HELD, HOLD_HELD],
    )
    assert fixtures.money_source_balances(client, account_id) == {
        SOURCE_PRE_TAX_DEFERRAL: 1000000
    }, "holds never debit a money source"
