"""One determination, six entity types, and the shape of every refusal.

The qualification cascade is read back from the four endpoints that own the rows
it wrote, and the error contract is checked where the same identifier is
reachable from two different rungs.
"""

from prd_bench_local_runner.testing import NON_EXISTENT_UUID, validate_success

from test_helpers import api_errors, constants, factories, fixtures
from test_helpers.assertions import (
    assert_case_dimensions,
    assert_communication_sequence,
    assert_derived_from_money_sources,
    assert_error_envelope,
    assert_hold,
    assert_list_response,
    assert_plan_account_figures,
    assert_settlement,
    assert_single_resource,
)
from test_helpers.test_users import (
    ADMIN_HEADERS,
    ANALYST_HEADERS,
    make_admin_headers,
    make_alternate_payee_headers,
    make_participant_headers,
)
from test_helpers.types import (
    AP_ACCOUNT_CLOSED,
    AP_ACCOUNT_ESTABLISHED,
    APPROACH_SEPARATE_INTEREST,
    DISCLOSURE_FULL,
    DISCLOSURE_LIMITED,
    DRAFT_QUALIFIED,
    EARNINGS_PERIOD_END,
    ELECTION_CASH,
    EMPLOYMENT_ACTIVE,
    FORMULA_PERCENTAGE_OF_ACCOUNT,
    HOLD_CONVERTED,
    ORIGIN_MANUAL,
    ORIGIN_SYSTEM,
    PROCEDURES_DRAFT,
    PROCEDURES_PUBLISHED,
    RECIPIENT_ALTERNATE_PAYEE,
    RECIPIENT_PARTICIPANT,
    REVIEW_INTAKE,
    REVIEW_QUALIFIED,
    SEGREGATION_CONVERTED,
    SEGREGATION_NONE,
    SOURCE_AFTER_TAX,
    SOURCE_EMPLOYER_MATCH,
    SOURCE_LOAN_RECEIVABLE,
    SOURCE_PRE_TAX_DEFERRAL,
    TEMPLATE_DETERMINATION_QUALIFIED,
    TEMPLATE_RECEIPT_ACKNOWLEDGMENT,
)

CASCADE_PLAN = {
    "acceptable_formula_codes": [FORMULA_PERCENTAGE_OF_ACCOUNT],
    "allowed_approaches": [APPROACH_SEPARATE_INTEREST],
    "earnings_adjustment_method": EARNINGS_PERIOD_END,
    "requires_model_language": True,
    "permits_benefit_not_otherwise_available": False,
    "review_period_days": 45,
    "segregation_period_days": 548,
    "resubmission_window_days": 60,
    "max_revisions": 3,
    "max_assignable_pct_bps": 5000,
    "max_assignable_amount_cents": 2000000,
}


def _ready_to_sign(client, plan_name):
    """A faultless draft on a four-source account, priced but not yet signed."""
    setup = fixtures.setup_case_with_held_hold(
        client,
        plan_name,
        sources=fixtures.FOUR_SOURCE_MIX,
        snapshots=(("2026-06-30", 4000000), ("2026-12-31", 4120000)),
        plan_overrides=CASCADE_PLAN,
        participant_overrides={
            "full_name": "Dana Reyes",
            "ssn_last4": "4417",
            "date_of_birth": "1979-04-12",
            "participation_start_date": "2010-01-01",
        },
        case_overrides={
            "alternate_payee_name": "Morgan Reyes",
            "alternate_payee_dob": "1981-07-05",
            "marital_period_start": "2012-03-01",
            "marital_period_end": "2026-02-01",
        },
        draft_overrides={"document_reference": "DRO-2663-K1"},
    )
    assert setup["draft"]["deficiency_codes"] == []
    assert setup["hold"]["hold_amount_cents"] == 1600000
    # A later instant than either valuation date, so the stamped segregation date
    # cannot be confused with a copied one.
    fixtures.set_clock(client, constants.CLOCK_2026_09_15)
    return setup


def test_the_determination_converts_the_hold_and_establishes_the_payee(client):
    """Levels one through four: the draft, the case, the hold, and the new account.

    PRD: "For a `SEPARATE_INTEREST` case the hold moves `HELD → CONVERTED`, and
    three fields are stamped on the way out: `segregation_date` becomes the
    logical clock's calendar date, `earnings_growth_bps` becomes the credited
    growth computed in §3.5, and `earnings_adjustment_cents` becomes the
    per-source-rounded earnings amount."

    Design: Difficulty/transitive_cascade/qualification_six_level_segregation_to_payee_cascade
    """
    setup = _ready_to_sign(client, "Cascade Plan")

    signed = validate_success(
        client.qualify_draft_order(setup["draft"]["id"], ADMIN_HEADERS)
    )
    assert signed["status"] == DRAFT_QUALIFIED
    assert signed["deficiency_codes"] == []
    assert signed["denial_reason"] is None

    assert_case_dimensions(
        fixtures.read_case(client, setup["case"]["id"]),
        review_status=REVIEW_QUALIFIED,
        segregation_status=SEGREGATION_CONVERTED,
    )

    # 4000000 to 4120000 is three percent of growth, credited per source and then
    # summed: 1200 + 17882 + 28919.
    assert_hold(
        fixtures.hold_for_case(client, setup["case"]["id"]),
        status=HOLD_CONVERTED,
        hold_amount_cents=1600000,
        placed_at=constants.CLOCK_2026_09_01,
        expires_at=constants.CLOCK_2028_03_02,
        segregation_date="2026-09-15",
        earnings_growth_bps=300,
        earnings_adjustment_cents=48001,
    )

    payee = fixtures.ap_account_for_case(client, setup["case"]["id"])
    assert payee["qdro_case_id"] == setup["case"]["id"]
    assert payee["payment_mode"] == APPROACH_SEPARATE_INTEREST
    assert payee["balance_cents"] == 1648001, "the hold plus its earnings adjustment"
    assert payee["after_tax_basis_cents"] == 24000
    assert payee["per_period_amount_cents"] == 0
    assert payee["shared_payment_end_date"] is None
    assert payee["total_distributed_gross_cents"] == 0
    assert payee["established_at"] == constants.CLOCK_2026_09_15
    assert payee["status"] == AP_ACCOUNT_ESTABLISHED
    assert payee["version"] == 1
    assert len(fixtures.read_ap_accounts(client, setup["case"]["id"])) == 1, (
        "the listing of a case's payee accounts holds zero or one row"
    )


def test_the_determination_debits_each_source_and_appends_the_pinned_pair(client):
    """Levels five through seven, and a chain that refuses to run a second time.

    PRD: "Each assignable money source, in `source_code` ascending order, is
    debited by the sum of its allocated share and its own per-source earnings
    figure, both from §3.5."

    Design: Difficulty/transitive_cascade/qualification_six_level_segregation_to_payee_cascade
    """
    setup = _ready_to_sign(client, "Cascade Ledger Plan")
    account_id = setup["account"]["id"]
    case_id = setup["case"]["id"]
    assert fixtures.money_source_balances(client, account_id) == {
        SOURCE_AFTER_TAX: 100000,
        SOURCE_EMPLOYER_MATCH: 1490125,
        SOURCE_PRE_TAX_DEFERRAL: 2409875,
        SOURCE_LOAN_RECEIVABLE: 300000,
    }

    fixtures.qualify(client, setup["draft"]["id"])

    # Allocation plus that source's own rounded earnings share, source by source.
    sources = fixtures.read_money_sources(client, account_id)
    debited = {row["source_code"]: row["balance_cents"] for row in sources}
    assert debited == {
        SOURCE_AFTER_TAX: 58800,
        SOURCE_EMPLOYER_MATCH: 876193,
        SOURCE_PRE_TAX_DEFERRAL: 1417006,
        SOURCE_LOAN_RECEIVABLE: 300000,
    }
    by_code = {row["source_code"]: row for row in sources}
    assert by_code[SOURCE_AFTER_TAX]["basis_cents"] == 36000
    assert by_code[SOURCE_LOAN_RECEIVABLE]["balance_cents"] == 300000, (
        "a non-assignable source is never touched by an assignment"
    )

    account = fixtures.read_plan_account(client, account_id)
    assert_plan_account_figures(
        account,
        vested_balance_cents=2651999,
        assignable_base_cents=2351999,
        after_tax_basis_cents=36000,
        held_amount_cents=0,
        available_balance_cents=2651999,
    )
    assert_derived_from_money_sources(
        account, sources, fixtures.read_holds(client, plan_account_id=account_id)
    )

    payee = fixtures.ap_account_for_case(client, case_id)
    assert (100000 - 58800) + (1490125 - 876193) + (2409875 - 1417006) == payee[
        "balance_cents"
    ], "every cent credited to the payee left a named money source"
    assert account["vested_balance_cents"] + payee["balance_cents"] == 4300000, (
        "the account's original vested balance is conserved across the chain"
    )

    case = fixtures.read_case(client, case_id)
    assert_case_dimensions(
        case,
        review_status=REVIEW_QUALIFIED,
        segregation_status=SEGREGATION_CONVERTED,
        version=3,
    )

    letters = fixtures.read_communications(client, case_id)
    assert_communication_sequence(
        letters,
        [
            (
                RECIPIENT_PARTICIPANT,
                TEMPLATE_RECEIPT_ACKNOWLEDGMENT,
                DISCLOSURE_LIMITED,
                ORIGIN_SYSTEM,
            ),
            (
                RECIPIENT_PARTICIPANT,
                TEMPLATE_DETERMINATION_QUALIFIED,
                DISCLOSURE_FULL,
                ORIGIN_SYSTEM,
            ),
            (
                RECIPIENT_ALTERNATE_PAYEE,
                TEMPLATE_DETERMINATION_QUALIFIED,
                DISCLOSURE_FULL,
                ORIGIN_SYSTEM,
            ),
        ],
    )
    assert [row["sent_at"] for row in letters] == [
        constants.CLOCK_2026_09_01,
        constants.CLOCK_2026_09_15,
        constants.CLOCK_2026_09_15,
    ]
    assert [row["attorney_email"] for row in letters] == [None, None, None]

    # The chain is not accidentally idempotent: it simply cannot run again.
    assert_error_envelope(
        client.qualify_draft_order(setup["draft"]["id"], ADMIN_HEADERS),
        api_errors.ERR_DRAFT_ORDER_NOT_UNDER_REVIEW,
        409,
    )
    assert fixtures.money_source_balances(client, account_id) == debited
    assert fixtures.read_ap_account(client, payee["id"])["balance_cents"] == 1648001
    assert fixtures.read_case(client, case_id)["version"] == 3


def test_every_level_of_the_chain_is_readable_on_the_very_next_call(client):
    """No level of the cascade is deferred to a sweep or to a later request.

    PRD: "A determination that survives all seven fires a seven-level cascade in
    a fixed order, and each level exists *because* of the one before it."

    Design: Corner/consistency_model/every_cascade_level_is_visible_in_the_same_instant_it_was_written
    """
    setup = fixtures.setup_case_with_held_hold(
        client,
        "Immediate Plan",
        plan_overrides=CASCADE_PLAN,
        draft_overrides={"document_reference": "DRO-2663-IMD"},
    )
    account_id = setup["account"]["id"]
    assert setup["draft"]["deficiency_codes"] == []
    assert_plan_account_figures(
        setup["account"],
        vested_balance_cents=1000000,
        held_amount_cents=400000,
        available_balance_cents=600000,
    )
    assert fixtures.read_ap_accounts(client, setup["case"]["id"]) == []

    # The action's own body already carries the outcome.
    signed = validate_success(
        client.qualify_draft_order(setup["draft"]["id"], ADMIN_HEADERS)
    )
    assert signed["status"] == DRAFT_QUALIFIED

    # The very next read shows the debit and the freed availability at once,
    # with no instant in which the money is counted twice or not at all.
    account = fixtures.read_plan_account(client, account_id)
    assert_plan_account_figures(
        account,
        vested_balance_cents=600000,
        held_amount_cents=0,
        available_balance_cents=600000,
    )

    payee = fixtures.ap_account_for_case(client, setup["case"]["id"])
    assert payee["balance_cents"] == 400000
    assert payee["status"] == AP_ACCOUNT_ESTABLISHED
    assert fixtures.hold_for_case(client, setup["case"]["id"])["status"] == (
        HOLD_CONVERTED
    )
    assert account["vested_balance_cents"] + payee["balance_cents"] == 1000000, (
        "conservation holds at the observation point, with no transient window"
    )

    determinations = fixtures.read_communications(
        client, setup["case"]["id"], template_code=TEMPLATE_DETERMINATION_QUALIFIED
    )
    assert [row["recipient_type"] for row in determinations] == [
        RECIPIENT_PARTICIPANT,
        RECIPIENT_ALTERNATE_PAYEE,
    ], "both appended letters are readable immediately and in the pinned order"


def test_creations_answer_201_actions_answer_200_and_both_are_reachable(client):
    """The two mutation families keep their declared codes and settle at once.

    PRD: "An operation that brings a new resource into existence answers with
    HTTP 201 and the created resource in `data`; an operation that modifies or
    transitions an existing resource, and every read, answers with HTTP 200."

    Design: Corner/endpoints/creations_return_201_actions_return_200_and_both_are_immediately_reachable
    """
    plan = assert_single_resource(
        client.create_plan(factories.minimal_plan_payload(plan_name="CRUD Plan"), ADMIN_HEADERS),
        201,
    )
    assert plan["procedures_status"] == PROCEDURES_DRAFT
    assert plan["version"] == 1

    # A named action answers 200 and returns the resource whose state it moved.
    moved = assert_single_resource(
        client.set_procedure_status(
            plan["id"],
            factories.procedure_status_payload(PROCEDURES_PUBLISHED),
            ADMIN_HEADERS,
        ),
        200,
    )
    assert moved["procedures_status"] == PROCEDURES_PUBLISHED
    assert moved["version"] == 2, (
        "the action's own response already carries the incremented version"
    )

    member = assert_single_resource(
        client.create_participant(
            factories.participant_payload(
                plan["id"],
                full_name="Crud Member",
                ssn_last4="2323",
                date_of_birth="1971-03-03",
                participation_start_date="2005-01-01",
            ),
            ADMIN_HEADERS,
        ),
        201,
    )
    assert member["employment_status"] == EMPLOYMENT_ACTIVE

    rows, meta = assert_list_response(
        client.list_plan_participants(
            plan["id"],
            ANALYST_HEADERS,
            {"employment_status": EMPLOYMENT_ACTIVE, "limit": 10, "offset": 0},
        )
    )
    assert [row["id"] for row in rows] == [member["id"]]
    assert meta["total_count"] == 1, "the row is listed in the same instant"

    account = assert_single_resource(
        client.open_plan_account(
            member["id"], factories.plan_account_payload(), ADMIN_HEADERS
        ),
        201,
    )
    source = assert_single_resource(
        client.create_money_source(
            account["id"],
            factories.money_source_payload(SOURCE_AFTER_TAX, 250000, basis_cents=250000),
            ADMIN_HEADERS,
        ),
        201,
    )
    assert source["is_assignable"] is True

    listed, _ = assert_list_response(
        client.list_money_sources(account["id"], make_participant_headers(member["id"]))
    )
    assert [row["id"] for row in listed] == [source["id"]]
    assert listed[0]["basis_cents"] == 250000

    assert validate_success(client.get_plan(plan["id"], ANALYST_HEADERS))[
        "procedures_status"
    ] == PROCEDURES_PUBLISHED
    accounts = validate_success(
        client.list_participant_plan_accounts(member["id"], ADMIN_HEADERS)
    )
    assert len(accounts) == 1
    assert_plan_account_figures(
        accounts[0],
        vested_balance_cents=250000,
        after_tax_basis_cents=250000,
        held_amount_cents=0,
        available_balance_cents=250000,
    )


def test_a_missing_prerequisite_is_one_unit_away_from_success(client):
    """Two refusals describe an absent precondition, not a malformed request.

    PRD: "A determination letter composed against a case still sitting at
    `review_status` `INTAKE`, with no draft order ever received, is refused with
    `ERR_NO_ACTIVE_DRAFT_ORDER`."

    Design: Corner/errors/prerequisite_errors_fire_when_the_object_of_the_action_does_not_exist_yet
    """
    setup = fixtures.setup_plan_account(
        client,
        "Prerequisite Plan",
        fixtures.SINGLE_SOURCE,
        snapshots=(("2026-06-30", 1000000),),
        plan_overrides=CASCADE_PLAN,
    )
    fixtures.set_clock(client, constants.CLOCK_2026_09_01)
    case = fixtures.open_case(client, setup["participant"]["id"])
    assert_case_dimensions(
        case,
        review_status=REVIEW_INTAKE,
        segregation_status=SEGREGATION_NONE,
        version=1,
    )

    # The case is readable, so the refusal cannot be a not-found.
    assert_error_envelope(
        client.create_communication(
            case["id"], factories.communication_payload(), ANALYST_HEADERS
        ),
        api_errors.ERR_NO_ACTIVE_DRAFT_ORDER,
        409,
    )

    draft = fixtures.receive_draft(
        client, case["id"], case["version"], document_reference="DRO-2663-PREREQ"
    )
    composed = validate_success(
        client.create_communication(
            case["id"], factories.communication_payload(), ANALYST_HEADERS
        ),
        201,
    )
    assert composed["origin"] == ORIGIN_MANUAL, (
        "the identical call succeeds once a draft exists, so the prerequisite is "
        "the case's draft set and nothing else"
    )

    signed = fixtures.qualify(client, draft["id"], headers=make_admin_headers())
    assert signed["status"] == DRAFT_QUALIFIED
    payee = fixtures.ap_account_for_case(client, case["id"])
    assert payee["balance_cents"] == 400000
    assert payee["version"] == 1
    payee_headers = make_alternate_payee_headers(payee["id"])

    # One cent over the live balance is refused; the comparison is strict.
    assert_error_envelope(
        client.create_distribution(
            payee["id"],
            factories.distribution_payload(payee["version"], 400001),
            payee_headers,
        ),
        api_errors.ERR_INSUFFICIENT_DISTRIBUTABLE_BALANCE,
        409,
    )
    untouched = fixtures.read_ap_account(client, payee["id"], headers=payee_headers)
    assert untouched["balance_cents"] == 400000
    assert untouched["total_distributed_gross_cents"] == 0
    assert untouched["version"] == 1

    # Exactly the balance is permitted.
    settled = validate_success(
        client.create_distribution(
            payee["id"],
            factories.distribution_payload(payee["version"], 400000),
            payee_headers,
        ),
        201,
    )
    assert_settlement(
        settled,
        gross_amount_cents=400000,
        basis_recovery_cents=0,
        taxable_amount_cents=400000,
        federal_withheld_cents=80000,
        net_before_fee_cents=320000,
        admin_fee_cents=5000,
        net_amount_cents=315000,
        tax_year=2026,
    )
    assert settled["election"] == ELECTION_CASH
    exhausted = fixtures.read_ap_account(client, payee["id"], headers=payee_headers)
    assert exhausted["balance_cents"] == 0
    assert exhausted["total_distributed_gross_cents"] == 400000
    assert exhausted["status"] == AP_ACCOUNT_CLOSED


def test_one_error_id_keeps_one_status_and_one_envelope_everywhere(client):
    """The same identifier from two rungs, and the same envelope every time.

    PRD: "The `meta` object for error responses contains only `api_request_id`
    and `api_request_timestamp`."

    Design: Corner/errors/one_error_id_keeps_one_status_and_one_envelope_shape_wherever_it_is_raised
    """
    setup = fixtures.setup_plan_account(
        client, "Envelope Contract Plan", fixtures.SINGLE_SOURCE
    )
    fixtures.set_clock(client, constants.CLOCK_2026_09_01)
    case = fixtures.open_case(client, setup["participant"]["id"])

    # The same id from a path segment and from a body foreign key.
    from_path = client.get_qdro_case(NON_EXISTENT_UUID, ADMIN_HEADERS)
    from_body = client.create_draft_order(
        factories.draft_order_payload(NON_EXISTENT_UUID, case["version"]),
        ADMIN_HEADERS,
    )
    # The same id from an administrator-only and from an analyst-only endpoint.
    analyst_on_admin_endpoint = client.set_current_utc(
        factories.clock_payload("2026-09-02T00:00:00Z"), ANALYST_HEADERS
    )
    admin_on_analyst_endpoint = client.create_communication(
        case["id"], factories.communication_payload(), ADMIN_HEADERS
    )

    expectations = [
        (from_path, api_errors.ERR_QDRO_CASE_NOT_FOUND, 404),
        (from_body, api_errors.ERR_QDRO_CASE_NOT_FOUND, 404),
        (analyst_on_admin_endpoint, api_errors.ERR_FORBIDDEN_ROLE, 403),
        (admin_on_analyst_endpoint, api_errors.ERR_FORBIDDEN_ROLE, 403),
    ]
    for response, error_id, status in expectations:
        data = assert_error_envelope(response, error_id, status)
        assert set(data.keys()) == {"error_id", "message"}, (
            f"error data must carry exactly two keys, got {sorted(data.keys())}"
        )
        assert NON_EXISTENT_UUID not in data["message"], (
            "the message must not echo an unknown identifier as if it resolved"
        )

    # None of the four refusals mutated anything.
    reread = fixtures.read_case(client, case["id"])
    assert reread["version"] == case["version"]
    assert reread["review_status"] == REVIEW_INTAKE
    rows, meta = assert_list_response(client.list_draft_orders(ADMIN_HEADERS))
    assert rows == []
    assert meta["total_count"] == 0
