"""What feeds the assignment arithmetic, and what is deliberately kept out.

The assignable base excludes the buckets an order may not reach, the held
exposure excludes the holds that are no longer live, the coverture share counts
half-open days and cannot exceed the whole account, the projection prices
either shape without writing anything, the deficiency evaluator returns one
sorted set, and the earnings interval is bounded by two snapshots chosen by
date rather than by recency.
"""

from prd_bench_local_runner.testing import validate_success

from test_helpers import api_errors, constants, factories, fixtures
from test_helpers.assertions import (
    assert_error_envelope,
    assert_hold,
    assert_plan_account_figures,
)
from test_helpers.test_users import ADMIN_HEADERS, ANALYST_HEADERS
from test_helpers.types import (
    AP_ACCOUNT_ESTABLISHED,
    APPROACH_SEPARATE_INTEREST,
    APPROACH_SHARED_PAYMENT,
    CODE_AP_IDENTIFICATION_INCOMPLETE,
    CODE_FORMULA_NOT_ACCEPTABLE,
    CODE_MISSING_MODEL_LANGUAGE,
    CODE_PROHIBITED_ALREADY_ASSIGNED,
    CODE_PROHIBITED_BENEFIT_NOT_AVAILABLE,
    CODE_PROHIBITED_FORM_NOT_OFFERED,
    CODE_PROHIBITED_INCREASED_BENEFIT,
    DRAFT_SUPERSEDED,
    FORMULA_COVERTURE_FRACTION,
    FORMULA_FLAT_DOLLAR,
    FORMULA_PERCENTAGE_OF_ACCOUNT,
    HOLD_CONVERTED,
    HOLD_HELD,
    PROVISION_ASSIGNS_BENEFITS_ALREADY_ASSIGNED,
    PROVISION_BENEFIT_NOT_OTHERWISE_AVAILABLE,
    PROVISION_LUMP_SUM_ELECTION,
    PROVISION_REQUIRES_INCREASED_TOTAL_BENEFIT,
    PROVISION_REQUIRES_QJSA_FOR_AP_SPOUSE,
    PROVISION_SURVIVOR_ANNUITY_FOR_AP,
    REVIEW_INTAKE,
    REVIEW_UNDER_REVIEW,
    SEGREGATION_HELD,
    SEGREGATION_NONE,
    SNAPSHOT_RECORDKEEPER_FEED,
    SOURCE_AFTER_TAX,
    SOURCE_EMPLOYER_MATCH,
    SOURCE_LOAN_RECEIVABLE,
    SOURCE_PRE_TAX_DEFERRAL,
)

ONE_FORMULA = [FORMULA_PERCENTAGE_OF_ACCOUNT]


def test_non_assignable_buckets_and_dead_holds_drop_out_of_their_input_sets(client):
    """A loan bucket funds nothing and a converted hold holds nothing.

    PRD: "A bucket a domestic relations order may not reach — the loan
    receivable being the standing example — is created with `is_assignable`
    false, which keeps it inside the vested balance while excluding it from the
    assignable base."

    Design: Corner/calculations/non_assignable_sources_and_non_held_holds_are_excluded_from_their_input_sets
    """
    setup = fixtures.setup_plan_account(
        client,
        "Filter Plan",
        [
            (SOURCE_AFTER_TAX, 200000, {"basis_cents": 50000}),
            (SOURCE_PRE_TAX_DEFERRAL, 500000, {"basis_cents": 0}),
            (SOURCE_LOAN_RECEIVABLE, 300000, {"is_assignable": False}),
        ],
        snapshots=(("2026-06-30", 1000000),),
        plan_overrides={
            "acceptable_formula_codes": ONE_FORMULA,
            "allowed_approaches": [APPROACH_SEPARATE_INTEREST],
        },
        participant_overrides={
            "full_name": "Loan Holder",
            "ssn_last4": "5050",
            "date_of_birth": "1972-05-05",
            "participation_start_date": "2004-01-01",
        },
    )
    account_id = setup["account"]["id"]
    assert_plan_account_figures(
        setup["account"],
        vested_balance_cents=1000000,
        assignable_base_cents=700000,
        after_tax_basis_cents=50000,
        held_amount_cents=0,
        available_balance_cents=1000000,
    )

    fixtures.set_clock(client, constants.CLOCK_2026_09_01)
    case = fixtures.open_case(
        client,
        setup["participant"]["id"],
        alternate_payee_name="Filter Payee",
        alternate_payee_dob="1974-04-04",
        marital_period_start="2012-03-01",
        marital_period_end="2026-02-01",
    )
    draft = fixtures.receive_draft(
        client,
        case["id"],
        case["version"],
        document_reference="DRO-2663-FILT",
        proposed_percentage_bps=4000,
    )
    hold = fixtures.held_hold_for_case(client, case["id"])
    assert hold["hold_amount_cents"] == 280000, (
        "4000 bps of the 700000 assignable base, not of the 1000000 vested total"
    )
    assert_plan_account_figures(
        fixtures.read_plan_account(client, account_id),
        held_amount_cents=280000,
        available_balance_cents=720000,
    )

    fixtures.set_clock(client, constants.CLOCK_2026_09_15)
    fixtures.qualify(client, draft["id"])

    payee = fixtures.ap_account_for_case(client, case["id"])
    assert payee["balance_cents"] == 280000
    assert payee["after_tax_basis_cents"] == 20000, (
        "the carryover follows only the assigned share of the after-tax bucket"
    )
    assert payee["status"] == AP_ACCOUNT_ESTABLISHED

    balances = fixtures.money_source_balances(client, account_id)
    assert balances == {
        SOURCE_AFTER_TAX: 120000,
        SOURCE_LOAN_RECEIVABLE: 300000,
        SOURCE_PRE_TAX_DEFERRAL: 300000,
    }, "only the two assignable buckets were debited"
    rows = fixtures.read_money_sources(client, account_id)
    assert rows[0]["source_code"] == SOURCE_AFTER_TAX
    assert rows[0]["balance_cents"] == 120000

    assert_plan_account_figures(
        fixtures.read_plan_account(client, account_id),
        vested_balance_cents=720000,
        assignable_base_cents=420000,
        after_tax_basis_cents=30000,
        held_amount_cents=0,
        available_balance_cents=720000,
    )

    # The hold that funded the conversion is no longer part of the held set.
    assert (
        fixtures.read_holds(client, plan_account_id=account_id, status=HOLD_HELD) == []
    )
    all_holds = fixtures.read_holds(client, plan_account_id=account_id)
    assert len(all_holds) == 1
    assert all_holds[0]["status"] == HOLD_CONVERTED


def test_the_coverture_share_counts_half_open_days_and_caps_at_the_whole_account(client):
    """Three tenures, one marital window: a fraction, a cap and a zero.

    PRD: "Otherwise the share is 10000 multiplied by the numerator, divided by
    the denominator, and rounded **half up** to a whole basis point. The result
    is then capped at 10000, because a marital period longer than the period of
    participation cannot represent more than the whole account."

    Design: Corner/calculations/coverture_fraction_uses_half_open_day_counts_and_caps_at_one_hundred_percent
    """
    plan = fixtures.create_published_plan(
        client,
        plan_name="Coverture Plan",
        acceptable_formula_codes=[
            FORMULA_COVERTURE_FRACTION,
            FORMULA_PERCENTAGE_OF_ACCOUNT,
        ],
        allowed_approaches=[APPROACH_SEPARATE_INTEREST],
    )
    tenures = {
        "normal": ("Normal Tenure", "6060", "1970-06-06", "2004-01-01"),
        "late": ("Late Tenure", "7070", "1970-07-07", "2020-01-01"),
        "same": ("Same Day Tenure", "8080", "1970-08-08", "2026-06-30"),
    }
    accounts = {}
    participants = {}
    for key, (name, ssn, dob, started) in tenures.items():
        participant = fixtures.enroll_participant(
            client,
            plan["id"],
            full_name=name,
            ssn_last4=ssn,
            date_of_birth=dob,
            participation_start_date=started,
        )
        account = fixtures.open_plan_account(client, participant["id"])
        fixtures.add_money_source(
            client, account["id"], SOURCE_PRE_TAX_DEFERRAL, 1000000
        )
        participants[key] = participant
        accounts[key] = account

    fixtures.set_clock(client, constants.CLOCK_2026_09_01)
    cases = {}
    for key in tenures:
        cases[key] = fixtures.open_case(
            client,
            participants[key]["id"],
            alternate_payee_name=f"{tenures[key][0]} Payee",
            alternate_payee_dob="1972-02-02",
            alternate_payee_address_on_file=True,
            marital_period_start="2012-03-01",
            marital_period_end="2026-02-01",
            valuation_date="2026-06-30",
        )

    # 5085 marital days over 8216 days of participation is 6189 bps half up;
    # 5000 bps of that is 3094 bps after rounding the share down.
    fixtures.receive_draft(
        client,
        cases["normal"]["id"],
        cases["normal"]["version"],
        document_reference="DRO-2663-COVN",
        proposed_formula_code=FORMULA_COVERTURE_FRACTION,
        proposed_percentage_bps=5000,
    )
    normal_hold = fixtures.held_hold_for_case(client, cases["normal"]["id"])
    assert normal_hold["hold_amount_cents"] == 309400

    projection = validate_success(
        client.get_benefit_projection(cases["normal"]["id"], ANALYST_HEADERS)
    )
    assert projection["assignable_base_cents"] == 1000000
    assert projection["gross_assigned_amount_cents"] == 309400
    assert projection["effective_approach"] == APPROACH_SEPARATE_INTEREST

    # The same 5085 marital days over only 2372 days of participation exceeds
    # the whole account, so the share is clamped and 4000 bps applies in full.
    fixtures.receive_draft(
        client,
        cases["late"]["id"],
        cases["late"]["version"],
        document_reference="DRO-2663-COVL",
        proposed_formula_code=FORMULA_COVERTURE_FRACTION,
        proposed_percentage_bps=4000,
    )
    late_hold = fixtures.held_hold_for_case(client, cases["late"]["id"])
    assert late_hold["hold_amount_cents"] == 400000, (
        "a share capped at 10000 bps leaves the assigned percentage untouched"
    )

    # A participation start on the valuation date leaves a zero denominator, so
    # the share is 0 bps and the priced assignment is exactly nothing.
    refusal = client.create_draft_order(
        factories.draft_order_payload(
            cases["same"]["id"],
            cases["same"]["version"],
            document_reference="DRO-2663-COVS",
            proposed_formula_code=FORMULA_COVERTURE_FRACTION,
            proposed_percentage_bps=5000,
        ),
        ADMIN_HEADERS,
    )
    assert_error_envelope(refusal, api_errors.ERR_ASSIGNED_AMOUNT_ZERO, 422)
    untouched = fixtures.read_case(client, cases["same"]["id"])
    assert untouched["review_status"] == REVIEW_INTAKE
    assert untouched["segregation_status"] == SEGREGATION_NONE
    assert fixtures.read_holds(client, plan_account_id=accounts["same"]["id"]) == []

    assert_plan_account_figures(
        fixtures.read_plan_account(client, accounts["normal"]["id"]),
        vested_balance_cents=1000000,
        held_amount_cents=309400,
        available_balance_cents=690600,
    )
    assert_plan_account_figures(
        fixtures.read_plan_account(client, accounts["late"]["id"]),
        vested_balance_cents=1000000,
        held_amount_cents=400000,
        available_balance_cents=600000,
    )


def test_the_projection_prices_the_road_not_taken_and_writes_nothing(client):
    """One fixture answers 660000 or 128000 depending only on the override.

    PRD: "By default the read prices the case's own operative `approach`; an
    optional `approach` input overrides it, which lets a caller price the road
    not taken."

    Design: Corner/calculations/benefit_projection_prices_the_road_not_taken_without_mutating_anything
    """
    setup = fixtures.setup_plan_account(
        client,
        "Projection Plan",
        [(SOURCE_PRE_TAX_DEFERRAL, 1000000, {"basis_cents": 0})],
        snapshots=(("2026-06-30", 1000000), ("2026-09-30", 1100000)),
        plan_overrides={
            "acceptable_formula_codes": ONE_FORMULA,
            "allowed_approaches": [APPROACH_SEPARATE_INTEREST, APPROACH_SHARED_PAYMENT],
        },
        participant_overrides={
            "full_name": "Projected Participant",
            "ssn_last4": "9191",
            "date_of_birth": "1959-09-09",
            "participation_start_date": "1995-01-01",
            "benefit_commenced": True,
        },
        account_overrides={"monthly_payment_cents": 320000},
    )
    account_id = setup["account"]["id"]
    fixtures.set_clock(client, constants.CLOCK_2026_09_01)
    case = fixtures.open_case(
        client,
        setup["participant"]["id"],
        alternate_payee_name="Projected Payee",
        alternate_payee_dob="1961-01-01",
        marital_period_start="2012-03-01",
        marital_period_end="2026-02-01",
    )
    fixtures.receive_draft(
        client,
        case["id"],
        case["version"],
        document_reference="DRO-2663-PROJ",
        proposed_approach=APPROACH_SHARED_PAYMENT,
        proposed_percentage_bps=4000,
        proposed_shared_payment_end_date="2027-12-31",
    )
    fixtures.set_clock(client, constants.CLOCK_2026_09_15)

    analyst_read = validate_success(
        client.get_benefit_projection(case["id"], ANALYST_HEADERS)
    )
    assert analyst_read["effective_approach"] == APPROACH_SHARED_PAYMENT

    default_read = validate_success(
        client.get_benefit_projection(case["id"], ADMIN_HEADERS)
    )
    assert default_read["effective_approach"] == APPROACH_SHARED_PAYMENT
    assert default_read["shared_payment_per_period_cents"] == 128000
    assert default_read["separate_interest_balance_cents"] == 0
    assert default_read["earnings_growth_bps"] == 0
    assert default_read["earnings_adjustment_cents"] == 0
    assert default_read["valuation_snapshot_count"] == 2, (
        "both snapshots are on file even though the shape credits no earnings"
    )

    carved = validate_success(
        client.get_benefit_projection(
            case["id"], ADMIN_HEADERS, {"approach": APPROACH_SEPARATE_INTEREST}
        )
    )
    assert carved["effective_approach"] == APPROACH_SEPARATE_INTEREST
    assert carved["shared_payment_per_period_cents"] == 0
    assert carved["gross_assigned_amount_cents"] == 400000
    assert carved["earnings_growth_bps"] == 1000
    assert carved["earnings_adjustment_cents"] == 40000
    assert carved["separate_interest_balance_cents"] == 440000
    assert carved["after_tax_basis_carryover_cents"] == 0

    # New principal arrives after receipt; the projection re-reads it at once.
    fixtures.add_money_source(client, account_id, SOURCE_EMPLOYER_MATCH, 500000)
    grown = validate_success(
        client.get_benefit_projection(
            case["id"], ADMIN_HEADERS, {"approach": APPROACH_SEPARATE_INTEREST}
        )
    )
    assert grown["assignable_base_cents"] == 1500000
    assert grown["gross_assigned_amount_cents"] == 600000
    assert grown["earnings_adjustment_cents"] == 60000, (
        "20000 on the match share plus 40000 on the deferral share"
    )
    assert grown["separate_interest_balance_cents"] == 660000

    periodic = validate_success(
        client.get_benefit_projection(
            case["id"], ADMIN_HEADERS, {"approach": APPROACH_SHARED_PAYMENT}
        )
    )
    assert periodic["shared_payment_per_period_cents"] == 128000, (
        "the periodic slice is keyed on the monthly payment, not on principal"
    )
    assert periodic["separate_interest_balance_cents"] == 0

    # Five reads later nothing has moved: the hold is still the one receipt sized.
    hold = fixtures.held_hold_for_case(client, case["id"])
    assert hold["hold_amount_cents"] == 400000
    after = fixtures.read_case(client, case["id"])
    assert after["version"] == 2, "only the draft receipt ever moved the case"
    assert after["review_status"] == REVIEW_UNDER_REVIEW
    assert len(fixtures.read_communications(client, case["id"])) == 1


def test_deficiency_codes_come_back_as_one_deterministic_sorted_set(client):
    """Six provisions plus three predicates collapse into seven sorted codes.

    PRD: "The codes are a set, then sorted ASCII ascending for determinism. One
    prohibited provision raises at most one code, and the two annuity-form
    provisions collapse into the single `PROHIBITED_FORM_NOT_OFFERED`, so a
    draft carrying both yields one code, not two."

    Design: Corner/calculations/deficiency_codes_propagate_to_a_deterministic_sorted_set
    """
    plan = fixtures.create_published_plan(
        client,
        plan_name="Deficiency Plan",
        acceptable_formula_codes=[
            FORMULA_PERCENTAGE_OF_ACCOUNT,
            FORMULA_COVERTURE_FRACTION,
        ],
        allowed_approaches=[APPROACH_SEPARATE_INTEREST],
        requires_model_language=True,
        permits_benefit_not_otherwise_available=False,
    )
    members = {}
    for key, (name, ssn, dob) in {
        "collapse": ("Collapse Member", "1414", "1971-04-04"),
        "openend": ("Openend Member", "1515", "1971-05-05"),
        "dirty": ("Dirty Member", "1616", "1971-06-06"),
    }.items():
        participant = fixtures.enroll_participant(
            client,
            plan["id"],
            full_name=name,
            ssn_last4=ssn,
            date_of_birth=dob,
            participation_start_date="2004-01-01",
        )
        account = fixtures.open_plan_account(client, participant["id"])
        fixtures.add_money_source(
            client, account["id"], SOURCE_PRE_TAX_DEFERRAL, 1000000
        )
        members[key] = {"participant": participant, "account": account}

    fixtures.set_clock(client, constants.CLOCK_2026_09_01)
    collapse_case = fixtures.open_case(
        client,
        members["collapse"]["participant"]["id"],
        alternate_payee_name="Collapse Payee",
        alternate_payee_dob="1973-03-03",
        marital_period_start="2012-03-01",
        marital_period_end="2026-02-01",
    )
    openend_case = validate_success(
        client.create_qdro_case(
            factories.omit(
                factories.qdro_case_payload(
                    members["openend"]["participant"]["id"],
                    alternate_payee_name="Openend Payee",
                    alternate_payee_dob="1973-03-03",
                    marital_period_start="2012-03-01",
                ),
                "marital_period_end",
            ),
            ANALYST_HEADERS,
        ),
        201,
    )
    dirty_case = validate_success(
        client.create_qdro_case(
            factories.omit(
                factories.qdro_case_payload(
                    members["dirty"]["participant"]["id"],
                    alternate_payee_name="Dirty Payee",
                    alternate_payee_address_on_file=False,
                    marital_period_start="2012-03-01",
                    marital_period_end="2026-02-01",
                ),
                "alternate_payee_dob",
            ),
            ANALYST_HEADERS,
        ),
        201,
    )

    collapsed = fixtures.receive_draft(
        client,
        collapse_case["id"],
        collapse_case["version"],
        document_reference="DRO-2663-COLL",
        provisions=[
            PROVISION_SURVIVOR_ANNUITY_FOR_AP,
            PROVISION_REQUIRES_QJSA_FOR_AP_SPOUSE,
            PROVISION_LUMP_SUM_ELECTION,
        ],
    )
    assert collapsed["deficiency_codes"] == [CODE_PROHIBITED_FORM_NOT_OFFERED], (
        "two annuity provisions make one code and the lump-sum election makes none"
    )

    clean = fixtures.receive_draft(
        client,
        openend_case["id"],
        openend_case["version"],
        document_reference="DRO-2663-OPEN",
        provisions=[PROVISION_LUMP_SUM_ELECTION],
    )
    assert clean["deficiency_codes"] == [], (
        "an undefined marital end is no deficiency under percentage of account"
    )

    # The set is recomputed on every receipt, so a superseding draft on the very
    # same case answers with a different set.
    reread_case = fixtures.read_case(client, openend_case["id"])
    superseding = fixtures.receive_draft(
        client,
        openend_case["id"],
        reread_case["version"],
        document_reference="DRO-2663-OPEN-2",
        provisions=[PROVISION_ASSIGNS_BENEFITS_ALREADY_ASSIGNED],
    )
    assert superseding["deficiency_codes"] == [CODE_PROHIBITED_ALREADY_ASSIGNED]
    assert fixtures.read_draft(client, clean["id"])["status"] == DRAFT_SUPERSEDED

    dirty_payload = factories.omit(
        factories.draft_order_payload(
            dirty_case["id"],
            dirty_case["version"],
            document_reference="DRO-2663-DIRTY",
            uses_model_language=False,
            proposed_formula_code=FORMULA_FLAT_DOLLAR,
            proposed_flat_amount_cents=250000,
            provisions=[
                PROVISION_BENEFIT_NOT_OTHERWISE_AVAILABLE,
                PROVISION_REQUIRES_INCREASED_TOTAL_BENEFIT,
                PROVISION_ASSIGNS_BENEFITS_ALREADY_ASSIGNED,
                PROVISION_SURVIVOR_ANNUITY_FOR_AP,
                PROVISION_REQUIRES_QJSA_FOR_AP_SPOUSE,
                PROVISION_LUMP_SUM_ELECTION,
            ],
        ),
        "proposed_percentage_bps",
    )
    dirty = validate_success(
        client.create_draft_order(dirty_payload, ANALYST_HEADERS), 201
    )
    seven_codes = [
        CODE_AP_IDENTIFICATION_INCOMPLETE,
        CODE_FORMULA_NOT_ACCEPTABLE,
        CODE_MISSING_MODEL_LANGUAGE,
        CODE_PROHIBITED_ALREADY_ASSIGNED,
        CODE_PROHIBITED_BENEFIT_NOT_AVAILABLE,
        CODE_PROHIBITED_FORM_NOT_OFFERED,
        CODE_PROHIBITED_INCREASED_BENEFIT,
    ]
    assert dirty["deficiency_codes"] == seven_codes, (
        "seven codes in ASCII-ascending order, the annuity pair still collapsed"
    )
    assert dirty["deficiency_codes"] == sorted(dirty["deficiency_codes"])

    # Derived, not stored from the request: the reads agree with the receipts.
    assert fixtures.read_draft(client, collapsed["id"])["deficiency_codes"] == [
        CODE_PROHIBITED_FORM_NOT_OFFERED
    ]
    assert fixtures.read_draft(client, dirty["id"])["deficiency_codes"] == seven_codes

    # A deficient draft is still received, and it still places its hold.
    dirty_hold = fixtures.held_hold_for_case(client, dirty_case["id"])
    assert dirty_hold["hold_amount_cents"] == 250000, (
        "the flat amount sits under the 500000 percentage ceiling"
    )
    assert fixtures.read_case(client, dirty_case["id"])["review_status"] == (
        REVIEW_UNDER_REVIEW
    )


SNAPSHOT_PLAN_OVERRIDES = {
    "acceptable_formula_codes": ONE_FORMULA,
    "allowed_approaches": [APPROACH_SEPARATE_INTEREST],
    "requires_model_language": True,
    "permits_benefit_not_otherwise_available": False,
    "max_assignable_pct_bps": 5000,
    "max_assignable_amount_cents": 2000000,
}


def _snapshot_case(client, plan_name, ssn, snapshots, payee_name):
    """One account with a pinned snapshot history, one case, one faultless draft."""
    setup = fixtures.setup_plan_account(
        client,
        plan_name,
        [(SOURCE_PRE_TAX_DEFERRAL, 1000000, {"basis_cents": 0})],
        plan_overrides=SNAPSHOT_PLAN_OVERRIDES,
        participant_overrides={
            "full_name": payee_name.replace("Payee", "Member"),
            "ssn_last4": ssn,
            "date_of_birth": "1979-01-01",
            "participation_start_date": "2010-01-01",
        },
        account_overrides={"monthly_payment_cents": 0},
    )
    for as_of_date, balance_cents, source in snapshots:
        extra = {"source": source} if source is not None else {}
        fixtures.add_snapshot(
            client, setup["account"]["id"], as_of_date, balance_cents, **extra
        )
    fixtures.set_clock(client, constants.CLOCK_2026_09_01)
    setup["case"] = fixtures.open_case(
        client,
        setup["participant"]["id"],
        alternate_payee_name=payee_name,
        alternate_payee_dob="1981-05-05",
        marital_period_start="2012-03-01",
        marital_period_end="2026-02-01",
        valuation_date="2026-06-30",
    )
    setup["draft"] = fixtures.receive_draft(
        client,
        setup["case"]["id"],
        setup["case"]["version"],
        document_reference=f"DRO-2663-N-{ssn}",
        proposed_percentage_bps=4000,
    )
    assert setup["draft"]["deficiency_codes"] == []
    return setup


def test_an_empty_post_segregation_snapshot_set_credits_no_growth_at_all(client):
    """A snapshot inside the interval is ignored, so the endpoint is the baseline.

    PRD: "When that candidate set is empty, the endpoint snapshot is taken to be
    the baseline snapshot itself, which drives the whole calculation to 0.
    Snapshots falling strictly between the valuation date and the segregation
    date are ignored entirely."

    Design: Difficulty/boundary_precision_check/empty_post_segregation_snapshot_set_yields_zero_earnings
    """
    setup = _snapshot_case(
        client,
        "Snapshot Set Plan",
        "1001",
        [
            ("2026-06-30", 1000000, None),
            ("2026-08-15", 1200000, SNAPSHOT_RECORDKEEPER_FEED),
        ],
        "Ada Cassini Payee",
    )
    fixtures.set_clock(client, constants.CLOCK_2026_09_15)
    fixtures.qualify(client, setup["draft"]["id"])

    hold = fixtures.hold_for_case(client, setup["case"]["id"])
    assert_hold(
        hold,
        status=HOLD_CONVERTED,
        hold_amount_cents=400000,
        segregation_date="2026-09-15",
        earnings_growth_bps=0,
        earnings_adjustment_cents=0,
    )

    payee = fixtures.ap_account_for_case(client, setup["case"]["id"])
    assert payee["balance_cents"] == 400000, (
        "the 1200000 snapshot is the most recent on file and still contributes "
        "nothing, so the payee is funded with bare principal"
    )
    assert (
        fixtures.money_source_balances(client, setup["account"]["id"])[
            SOURCE_PRE_TAX_DEFERRAL
        ]
        == 600000
    )
    assert_plan_account_figures(
        fixtures.read_plan_account(client, setup["account"]["id"]),
        vested_balance_cents=600000,
        assignable_base_cents=600000,
        held_amount_cents=0,
        available_balance_cents=600000,
    )


def test_a_snapshot_on_the_segregation_date_counts_but_a_baseline_one_day_off_does_not(
    client,
):
    """The endpoint predicate is inclusive; the baseline predicate is exact.

    PRD: "The baseline snapshot is the one whose `as_of_date` exactly equals the
    case's `valuation_date`; a snapshot one day off does not qualify, and if none
    exists the determination is refused with `ERR_VALUATION_SNAPSHOT_MISSING`."

    Design: Difficulty/boundary_precision_check/empty_post_segregation_snapshot_set_yields_zero_earnings
    """
    on_the_day = _snapshot_case(
        client,
        "Snapshot Set Plan",
        "1002",
        [
            ("2026-06-30", 1000000, None),
            ("2026-09-15", 1100000, SNAPSHOT_RECORDKEEPER_FEED),
        ],
        "Bo Cassini Payee",
    )
    one_day_off = _snapshot_case(
        client,
        "Off By One Plan",
        "1003",
        [("2026-07-01", 1000000, None)],
        "Cleo Cassini Payee",
    )

    fixtures.set_clock(client, constants.CLOCK_2026_09_15)
    fixtures.qualify(client, on_the_day["draft"]["id"])
    assert_hold(
        fixtures.hold_for_case(client, on_the_day["case"]["id"]),
        status=HOLD_CONVERTED,
        hold_amount_cents=400000,
        earnings_growth_bps=1000,
        earnings_adjustment_cents=40000,
    )
    assert (
        fixtures.ap_account_for_case(client, on_the_day["case"]["id"])["balance_cents"]
        == 440000
    ), "a snapshot dated exactly on the segregation date is a candidate"
    assert (
        fixtures.money_source_balances(client, on_the_day["account"]["id"])[
            SOURCE_PRE_TAX_DEFERRAL
        ]
        == 560000
    )

    refusal = client.qualify_draft_order(one_day_off["draft"]["id"], ADMIN_HEADERS)
    assert_error_envelope(refusal, api_errors.ERR_VALUATION_SNAPSHOT_MISSING, 422)

    # The refusal left the whole scenario exactly where receipt had put it.
    stalled = fixtures.read_case(client, one_day_off["case"]["id"])
    assert stalled["review_status"] == REVIEW_UNDER_REVIEW
    assert stalled["segregation_status"] == SEGREGATION_HELD
    assert_hold(
        fixtures.hold_for_case(client, one_day_off["case"]["id"]),
        status=HOLD_HELD,
        hold_amount_cents=400000,
        segregation_date=None,
    )
    assert fixtures.read_ap_accounts(client, one_day_off["case"]["id"]) == [], (
        "a hold is placeable without any snapshot, but a determination is not"
    )
    assert_plan_account_figures(
        fixtures.read_plan_account(client, one_day_off["account"]["id"]),
        vested_balance_cents=1000000,
        held_amount_cents=400000,
        available_balance_cents=600000,
    )
