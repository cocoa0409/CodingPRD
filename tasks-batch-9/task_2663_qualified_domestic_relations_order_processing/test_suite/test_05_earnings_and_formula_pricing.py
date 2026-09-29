"""Pricing an assignment: three formula branches, two ceilings, two methods.

The same account is priced under each formula across a revision cycle, both
statutory ceilings are made to bind in turn, the earnings amount is rounded per
source before summing, and the two approaches and the two earnings methods are
run against identical data so their divergence is visible.
"""

from prd_bench_local_runner.testing import validate_success

from test_helpers import constants, factories, fixtures
from test_helpers.assertions import (
    assert_hold,
    assert_plan_account_figures,
)
from test_helpers.test_users import ADMIN_HEADERS, ANALYST_HEADERS, make_analyst_headers
from test_helpers.types import (
    AP_ACCOUNT_ESTABLISHED,
    APPROACH_SEPARATE_INTEREST,
    APPROACH_SHARED_PAYMENT,
    CODE_MISSING_MODEL_LANGUAGE,
    DRAFT_UNDER_REVIEW,
    EARNINGS_PERIOD_END,
    EARNINGS_PRO_RATA_DAILY,
    EMPLOYMENT_RETIRED,
    FORMULA_COVERTURE_FRACTION,
    FORMULA_FLAT_DOLLAR,
    FORMULA_PERCENTAGE_OF_ACCOUNT,
    HOLD_CONVERTED,
    HOLD_HELD,
    HOLD_RELEASED,
    NOTICE_CURED,
    REVIEW_QUALIFIED,
    SEGREGATION_RELEASED_TO_PARTICIPANT,
    SOURCE_AFTER_TAX,
    SOURCE_EMPLOYER_MATCH,
    SOURCE_LOAN_RECEIVABLE,
    SOURCE_PRE_TAX_DEFERRAL,
)

LATTICE_PLAN = {
    "acceptable_formula_codes": [
        FORMULA_PERCENTAGE_OF_ACCOUNT,
        FORMULA_FLAT_DOLLAR,
        FORMULA_COVERTURE_FRACTION,
    ],
    "allowed_approaches": [APPROACH_SEPARATE_INTEREST, APPROACH_SHARED_PAYMENT],
    "requires_model_language": True,
    "review_period_days": 45,
    "segregation_period_days": 548,
    "resubmission_window_days": 60,
    "max_revisions": 3,
    "earnings_adjustment_method": EARNINGS_PERIOD_END,
}


def _mix_case(client, plan_name, plan_overrides, ssn, member_name, payee_name,
              snapshots):
    """A four-bucket account worth 4300000, of which 4000000 is assignable."""
    setup = fixtures.setup_plan_account(
        client,
        plan_name,
        fixtures.FOUR_SOURCE_MIX,
        snapshots=snapshots,
        plan_overrides=plan_overrides,
        participant_overrides={
            "full_name": member_name,
            "ssn_last4": ssn,
            "date_of_birth": "1978-08-08",
            "participation_start_date": "2010-01-01",
            "benefit_commenced": False,
        },
        account_overrides={"monthly_payment_cents": 0},
    )
    assert_plan_account_figures(
        setup["account"],
        vested_balance_cents=4300000,
        assignable_base_cents=4000000,
        after_tax_basis_cents=60000,
    )
    fixtures.set_clock(client, constants.CLOCK_2026_09_01)
    setup["case"] = fixtures.open_case(
        client,
        setup["participant"]["id"],
        alternate_payee_name=payee_name,
        alternate_payee_dob="1980-01-15",
        alternate_payee_address_on_file=True,
        marital_period_start="2012-03-01",
        marital_period_end="2026-02-01",
        valuation_date="2026-06-30",
    )
    return setup


def _flat_dollar_receipt(client, case, document_reference, flat_amount_cents):
    """A flat-dollar receipt carries no percentage term at all."""
    payload = factories.omit(
        factories.draft_order_payload(
            case["id"],
            case["version"],
            document_reference=document_reference,
            uses_model_language=False,
            proposed_formula_code=FORMULA_FLAT_DOLLAR,
            proposed_flat_amount_cents=flat_amount_cents,
        ),
        "proposed_percentage_bps",
    )
    return validate_success(client.create_draft_order(payload, ADMIN_HEADERS), 201)


def test_one_account_priced_under_all_three_formulas_across_a_revision_cycle(client):
    """Flat, percentage and coverture terms re-size the same hold in turn.

    PRD: "Sizing the assignment is the arithmetic heart of receipt, and it is
    recomputed identically on every resubmission, on the projection read, and
    again at qualification when the payee account is funded."

    Design: Difficulty/combinatorial_formula/assigned_amount_three_formula_branches_against_two_ceilings
    """
    setup = _mix_case(
        client,
        "Lattice Retirement Plan",
        dict(LATTICE_PLAN, max_assignable_pct_bps=4500,
             max_assignable_amount_cents=1700000),
        "3388",
        "Selma Ashford",
        "Pilar Ashford",
        (("2026-06-30", 4000000),),
    )
    case, account_id = setup["case"], setup["account"]["id"]
    reviewer = make_analyst_headers("analyst-7")

    # Branch one: a flat 2500000 is trimmed by the tighter amount ceiling.
    draft = _flat_dollar_receipt(client, case, "DRO-2663-L1", 2500000)
    assert draft["deficiency_codes"] == [CODE_MISSING_MODEL_LANGUAGE]
    hold = fixtures.held_hold_for_case(client, case["id"])
    assert_hold(
        hold,
        status=HOLD_HELD,
        hold_amount_cents=1700000,
        placed_at=constants.CLOCK_2026_09_01,
        expires_at="2028-03-02T00:00:00Z",
    )

    first_notice = fixtures.issue_notice(client, draft["id"], headers=reviewer)
    assert first_notice["resubmission_deadline_at"] == "2026-10-31T00:00:00Z"

    # Branch two: 4000 bps of the same base, under both ceilings.
    fixtures.set_clock(client, "2026-09-10T00:00:00Z")
    second = fixtures.resubmit(
        client,
        draft["id"],
        document_reference="DRO-2663-L2",
        uses_model_language=False,
        proposed_formula_code=FORMULA_PERCENTAGE_OF_ACCOUNT,
        proposed_percentage_bps=4000,
    )
    assert second["revision_number"] == 2
    assert fixtures.hold_for_case(client, case["id"])["hold_amount_cents"] == 1600000

    second_notice = fixtures.issue_notice(client, draft["id"], headers=reviewer)
    assert second_notice["resubmission_deadline_at"] == "2026-11-09T00:00:00Z"

    # Branch three: a coverture share of 8441 bps applied to 5000 bps.
    fixtures.set_clock(client, constants.CLOCK_2026_09_20)
    third = fixtures.resubmit(
        client,
        draft["id"],
        document_reference="DRO-2663-L3",
        uses_model_language=False,
        proposed_formula_code=FORMULA_COVERTURE_FRACTION,
        proposed_percentage_bps=5000,
    )
    assert third["revision_number"] == 3
    assert third["status"] == DRAFT_UNDER_REVIEW
    assert third["deficiency_codes"] == [CODE_MISSING_MODEL_LANGUAGE]

    final_hold = fixtures.held_hold_for_case(client, case["id"])
    assert_hold(
        final_hold,
        status=HOLD_HELD,
        hold_amount_cents=1688000,
        placed_at=constants.CLOCK_2026_09_01,
        expires_at="2028-03-02T00:00:00Z",
    )
    projection = validate_success(
        client.get_benefit_projection(case["id"], ANALYST_HEADERS)
    )
    assert projection["assignable_base_cents"] == 4000000
    assert projection["gross_assigned_amount_cents"] == 1688000

    assert_plan_account_figures(
        fixtures.read_plan_account(client, account_id),
        vested_balance_cents=4300000,
        assignable_base_cents=4000000,
        held_amount_cents=1688000,
        available_balance_cents=2612000,
    )
    notices = fixtures.read_notices(client, draft["id"])
    assert [row["notice_sequence"] for row in notices] == [1, 2]
    assert [row["status"] for row in notices] == [NOTICE_CURED, NOTICE_CURED]


def test_both_statutory_ceilings_bind_and_the_tighter_one_always_wins(client):
    """A flat assignment is trimmed by whichever ceiling is lower, never refused.

    PRD: "Note the consequence for flat-dollar orders: a flat assignment above
    half the assignable base is silently trimmed to the percentage ceiling rather
    than being rejected."

    Design: Difficulty/combinatorial_formula/assigned_amount_three_formula_branches_against_two_ceilings
    """
    amount_bound = _mix_case(
        client,
        "Amount Ceiling Plan",
        dict(LATTICE_PLAN, max_assignable_pct_bps=4500,
             max_assignable_amount_cents=1700000),
        "3389",
        "Sigrid Ashford",
        "Perla Ashford",
        (("2026-06-30", 4000000),),
    )
    _flat_dollar_receipt(client, amount_bound["case"], "DRO-2663-CAP-A", 2500000)
    assert (
        fixtures.held_hold_for_case(client, amount_bound["case"]["id"])[
            "hold_amount_cents"
        ]
        == 1700000
    ), "the amount ceiling of 1700000 is tighter than the 1800000 percentage ceiling"
    assert (
        validate_success(
            client.get_benefit_projection(
                amount_bound["case"]["id"], ANALYST_HEADERS
            )
        )["gross_assigned_amount_cents"]
        == 1700000
    )

    percentage_bound = _mix_case(
        client,
        "Percentage Ceiling Plan",
        dict(LATTICE_PLAN, max_assignable_pct_bps=4500,
             max_assignable_amount_cents=100000000),
        "3390",
        "Torvald Ashford",
        "Pomona Ashford",
        (("2026-06-30", 4000000),),
    )
    draft = _flat_dollar_receipt(
        client, percentage_bound["case"], "DRO-2663-CAP-P", 2500000
    )
    assert (
        fixtures.held_hold_for_case(client, percentage_bound["case"]["id"])[
            "hold_amount_cents"
        ]
        == 1800000
    ), "4500 bps of the 4000000 base now binds instead of the amount ceiling"
    assert_plan_account_figures(
        fixtures.read_plan_account(client, percentage_bound["account"]["id"]),
        vested_balance_cents=4300000,
        held_amount_cents=1800000,
        available_balance_cents=2500000,
    )

    # A superseding percentage draft sits under both ceilings, so the raw amount
    # survives untouched and the hold shrinks to it.
    reread = fixtures.read_case(client, percentage_bound["case"]["id"])
    superseding = fixtures.receive_draft(
        client,
        percentage_bound["case"]["id"],
        reread["version"],
        document_reference="DRO-2663-CAP-P2",
        proposed_percentage_bps=4000,
    )
    assert superseding["proposed_formula_code"] == FORMULA_PERCENTAGE_OF_ACCOUNT
    assert (
        fixtures.held_hold_for_case(client, percentage_bound["case"]["id"])[
            "hold_amount_cents"
        ]
        == 1600000
    )
    assert fixtures.read_draft(client, draft["id"])["status"] != DRAFT_UNDER_REVIEW


def test_the_earnings_amount_is_rounded_per_source_before_it_is_summed(client):
    """Three per-source roundings sum to 48001 where one aggregate gives 48000.

    PRD: "With shares of 40000, 596050, and 963950 cents and a credited growth of
    300 basis points, the per-source figures are 1200, 17882, and 28919 cents,
    summing to 48001, whereas rounding the aggregate first would give 48000."

    Design: Difficulty/combinatorial_formula/earnings_adjustment_per_source_rounding_beats_aggregate_rounding
    """
    setup = _mix_case(
        client,
        "Residue Retirement Plan",
        {
            "acceptable_formula_codes": [FORMULA_PERCENTAGE_OF_ACCOUNT],
            "allowed_approaches": [APPROACH_SEPARATE_INTEREST],
            "requires_model_language": True,
            "earnings_adjustment_method": EARNINGS_PERIOD_END,
            "max_assignable_pct_bps": 5000,
            "max_assignable_amount_cents": 2000000,
        },
        "4417",
        "Dana Reyes",
        "Morgan Reyes",
        (("2026-06-30", 4000000), ("2026-12-31", 4120000)),
    )
    case, account_id = setup["case"], setup["account"]["id"]
    draft = fixtures.receive_draft(
        client,
        case["id"],
        case["version"],
        document_reference="DRO-2663-R1",
        proposed_percentage_bps=4000,
    )
    assert draft["deficiency_codes"] == []
    assert fixtures.held_hold_for_case(client, case["id"])["hold_amount_cents"] == (
        1600000
    )

    fixtures.set_clock(client, constants.CLOCK_2026_09_15)
    fixtures.qualify(client, draft["id"])

    assert_hold(
        fixtures.hold_for_case(client, case["id"]),
        status=HOLD_CONVERTED,
        hold_amount_cents=1600000,
        segregation_date="2026-09-15",
        earnings_growth_bps=300,
        earnings_adjustment_cents=48001,
    )
    payee = fixtures.ap_account_for_case(client, case["id"])
    assert payee["balance_cents"] == 1648001, (
        "the payee is funded with the summed per-source earnings, never 48000"
    )
    assert payee["after_tax_basis_cents"] == 24000
    assert payee["status"] == AP_ACCOUNT_ESTABLISHED

    # Every debit is the source's own share plus that share's own earnings.
    balances = fixtures.money_source_balances(client, account_id)
    assert balances == {
        SOURCE_AFTER_TAX: 58800,
        SOURCE_EMPLOYER_MATCH: 876193,
        SOURCE_PRE_TAX_DEFERRAL: 1417006,
        SOURCE_LOAN_RECEIVABLE: 300000,
    }
    debits = {
        SOURCE_AFTER_TAX: 100000 - balances[SOURCE_AFTER_TAX],
        SOURCE_EMPLOYER_MATCH: 1490125 - balances[SOURCE_EMPLOYER_MATCH],
        SOURCE_PRE_TAX_DEFERRAL: 2409875 - balances[SOURCE_PRE_TAX_DEFERRAL],
    }
    assert debits == {
        SOURCE_AFTER_TAX: 41200,
        SOURCE_EMPLOYER_MATCH: 613932,
        SOURCE_PRE_TAX_DEFERRAL: 992869,
    }
    assert sum(debits.values()) == 1648001

    assert_plan_account_figures(
        fixtures.read_plan_account(client, account_id),
        vested_balance_cents=2651999,
        assignable_base_cents=2351999,
        after_tax_basis_cents=36000,
        held_amount_cents=0,
        available_balance_cents=2651999,
    )


def test_the_projection_reports_the_summed_per_source_earnings_before_anything_moves(
    client,
):
    """The pinned order of operations is observable without signing anything.

    PRD: "The earnings **amount** is derived from the allocation vector, and the
    order of operations is pinned: each source's earnings are the share allocated
    to that source multiplied by the credited growth in basis points, divided by
    10000, rounded **half up** to whole cents — and only then are the per-source
    figures summed to give `earnings_adjustment_cents`."

    Design: Difficulty/combinatorial_formula/earnings_adjustment_per_source_rounding_beats_aggregate_rounding
    """
    setup = _mix_case(
        client,
        "Residue Preview Plan",
        {
            "acceptable_formula_codes": [FORMULA_PERCENTAGE_OF_ACCOUNT],
            "allowed_approaches": [APPROACH_SEPARATE_INTEREST],
            "requires_model_language": True,
            "earnings_adjustment_method": EARNINGS_PERIOD_END,
            "max_assignable_pct_bps": 5000,
            "max_assignable_amount_cents": 2000000,
        },
        "4418",
        "Dana Preview",
        "Morgan Preview",
        (("2026-06-30", 4000000), ("2026-12-31", 4120000)),
    )
    case, account_id = setup["case"], setup["account"]["id"]
    fixtures.receive_draft(
        client,
        case["id"],
        case["version"],
        document_reference="DRO-2663-R1-PRE",
        proposed_percentage_bps=4000,
    )
    fixtures.set_clock(client, constants.CLOCK_2026_09_15)

    projection = validate_success(
        client.get_benefit_projection(case["id"], ADMIN_HEADERS)
    )
    assert projection["effective_approach"] == APPROACH_SEPARATE_INTEREST
    assert projection["assignable_base_cents"] == 4000000
    assert projection["gross_assigned_amount_cents"] == 1600000
    assert projection["earnings_growth_bps"] == 300
    assert projection["earnings_adjustment_cents"] == 48001, (
        "1200 plus 17882 plus 28919, each rounded before the sum is taken"
    )
    assert projection["separate_interest_balance_cents"] == 1648001
    assert projection["after_tax_basis_carryover_cents"] == 24000
    assert projection["shared_payment_per_period_cents"] == 0
    assert projection["valuation_snapshot_count"] == 2

    # The preview committed nothing: the buckets are untouched and still held.
    assert fixtures.money_source_balances(client, account_id) == {
        SOURCE_AFTER_TAX: 100000,
        SOURCE_EMPLOYER_MATCH: 1490125,
        SOURCE_PRE_TAX_DEFERRAL: 2409875,
        SOURCE_LOAN_RECEIVABLE: 300000,
    }
    assert_plan_account_figures(
        fixtures.read_plan_account(client, account_id),
        vested_balance_cents=4300000,
        held_amount_cents=1600000,
        available_balance_cents=2700000,
    )
    assert fixtures.read_ap_accounts(client, case["id"]) == []
    assert fixtures.read_case(client, case["id"])["version"] == 2


def _shared_payment_case(client, plan_name, ssn):
    """A retiree in pay status whose case proposes a shared-payment division."""
    setup = fixtures.setup_plan_account(
        client,
        plan_name,
        [(SOURCE_PRE_TAX_DEFERRAL, 1000000, {"basis_cents": 0})],
        snapshots=(("2026-06-30", 1000000), ("2026-12-31", 1030000)),
        plan_overrides={
            "acceptable_formula_codes": [FORMULA_PERCENTAGE_OF_ACCOUNT],
            "allowed_approaches": [
                APPROACH_SEPARATE_INTEREST,
                APPROACH_SHARED_PAYMENT,
            ],
            "earnings_adjustment_method": EARNINGS_PERIOD_END,
            "max_assignable_pct_bps": 5000,
            "max_assignable_amount_cents": 2000000,
        },
        participant_overrides={
            "full_name": "Meridian Member",
            "ssn_last4": ssn,
            "date_of_birth": "1958-02-02",
            "participation_start_date": "1990-01-01",
            "employment_status": EMPLOYMENT_RETIRED,
            "benefit_commenced": True,
        },
        account_overrides={"monthly_payment_cents": 320000},
    )
    fixtures.set_clock(client, constants.CLOCK_2026_09_01)
    setup["case"] = fixtures.open_case(
        client,
        setup["participant"]["id"],
        alternate_payee_name="Meridian Payee",
        alternate_payee_dob="1964-11-02",
        alternate_payee_address_on_file=True,
        marital_period_start="2012-03-01",
        marital_period_end="2026-02-01",
        valuation_date="2026-06-30",
    )
    setup["draft"] = fixtures.receive_draft(
        client,
        setup["case"]["id"],
        setup["case"]["version"],
        document_reference=f"DRO-2663-M{ssn}",
        proposed_approach=APPROACH_SHARED_PAYMENT,
        proposed_percentage_bps=4000,
        proposed_shared_payment_end_date="2031-12-31",
    )
    assert setup["draft"]["deficiency_codes"] == []
    assert fixtures.held_hold_for_case(client, setup["case"]["id"])[
        "hold_amount_cents"
    ] == 400000
    return setup


def test_the_two_approaches_price_identical_case_data_differently(client):
    """One case, two shapes: 412000 of principal or 128000 a period.

    PRD: "The divergence is stark on identical case data: with a
    `monthly_payment_cents` of 320000 and an `assigned_percentage_bps` of 4000,
    the shared-payment shape reports 128000 per period and a balance of 0, while
    the separate-interest shape reports a per-period amount of 0 and a balance
    equal to the gross assigned amount plus earnings."

    Design: Difficulty/dual_variant_calc/separate_interest_versus_shared_payment_projection_divergence
    """
    setup = _shared_payment_case(client, "Meridian 401(k) Plan", "2101")
    case = setup["case"]
    fixtures.set_clock(client, constants.CLOCK_2026_09_15)

    carved = validate_success(
        client.get_benefit_projection(
            case["id"], ADMIN_HEADERS, {"approach": APPROACH_SEPARATE_INTEREST}
        )
    )
    assert carved["effective_approach"] == APPROACH_SEPARATE_INTEREST
    assert carved["gross_assigned_amount_cents"] == 400000
    assert carved["earnings_growth_bps"] == 300
    assert carved["earnings_adjustment_cents"] == 12000
    assert carved["separate_interest_balance_cents"] == 412000
    assert carved["shared_payment_per_period_cents"] == 0

    periodic = validate_success(
        client.get_benefit_projection(case["id"], ANALYST_HEADERS)
    )
    assert periodic["effective_approach"] == APPROACH_SHARED_PAYMENT, (
        "with no override the case's own operative approach is priced"
    )
    assert periodic["gross_assigned_amount_cents"] == 400000
    assert periodic["earnings_growth_bps"] == 0
    assert periodic["earnings_adjustment_cents"] == 0
    assert periodic["separate_interest_balance_cents"] == 0
    assert periodic["shared_payment_per_period_cents"] == 128000
    assert periodic["after_tax_basis_carryover_cents"] == 0


def test_a_shared_payment_determination_releases_the_hold_and_carves_no_principal(
    client,
):
    """Nothing is segregated, so the hold is released and the buckets stay put.

    PRD: "The payee then receives a slice of each periodic payment as it is made,
    principal stays with the participant, and the hold is released rather than
    converted."

    Design: Difficulty/dual_variant_calc/separate_interest_versus_shared_payment_projection_divergence
    """
    setup = _shared_payment_case(client, "Meridian Determination Plan", "2102")
    case, account_id = setup["case"], setup["account"]["id"]
    fixtures.set_clock(client, constants.CLOCK_2026_09_15)
    fixtures.qualify(client, setup["draft"]["id"])

    payee = fixtures.ap_account_for_case(client, case["id"])
    assert payee["payment_mode"] == APPROACH_SHARED_PAYMENT
    assert payee["balance_cents"] == 0
    assert payee["after_tax_basis_cents"] == 0
    assert payee["per_period_amount_cents"] == 128000
    assert payee["shared_payment_end_date"] == "2031-12-31"
    assert payee["total_distributed_gross_cents"] == 0
    assert payee["status"] == AP_ACCOUNT_ESTABLISHED

    assert_hold(
        fixtures.hold_for_case(client, case["id"]),
        status=HOLD_RELEASED,
        hold_amount_cents=400000,
        segregation_date=None,
        earnings_growth_bps=0,
        earnings_adjustment_cents=0,
    )
    reread = fixtures.read_case(client, case["id"])
    assert reread["review_status"] == REVIEW_QUALIFIED
    assert reread["segregation_status"] == SEGREGATION_RELEASED_TO_PARTICIPANT

    assert fixtures.money_source_balances(client, account_id) == {
        SOURCE_PRE_TAX_DEFERRAL: 1000000
    }, "no bucket is debited by a shared-payment determination"
    assert_plan_account_figures(
        fixtures.read_plan_account(client, account_id),
        vested_balance_cents=1000000,
        assignable_base_cents=1000000,
        held_amount_cents=0,
        available_balance_cents=1000000,
    )


def _one_bucket_case(client, plan_name, method, ssn):
    """A single 4000000 bucket, two snapshots 184 days apart, one 4000 bps draft."""
    setup = fixtures.setup_plan_account(
        client,
        plan_name,
        [(SOURCE_PRE_TAX_DEFERRAL, 4000000, {"basis_cents": 0})],
        snapshots=(("2026-06-30", 4000000), ("2026-12-31", 4120000)),
        plan_overrides={
            "acceptable_formula_codes": [FORMULA_PERCENTAGE_OF_ACCOUNT],
            "allowed_approaches": [APPROACH_SEPARATE_INTEREST],
            "earnings_adjustment_method": method,
            "max_assignable_pct_bps": 5000,
            "max_assignable_amount_cents": 2000000,
        },
        participant_overrides={
            "full_name": f"{plan_name.split()[0]} Member",
            "ssn_last4": ssn,
            "date_of_birth": "1977-03-03",
            "participation_start_date": "2005-01-01",
        },
    )
    fixtures.set_clock(client, constants.CLOCK_2026_09_01)
    setup["case"] = fixtures.open_case(
        client,
        setup["participant"]["id"],
        alternate_payee_name=f"{plan_name.split()[0]} Payee",
        alternate_payee_dob="1979-09-09",
        alternate_payee_address_on_file=True,
        marital_period_start="2012-03-01",
        marital_period_end="2026-02-01",
        valuation_date="2026-06-30",
    )
    setup["draft"] = fixtures.receive_draft(
        client,
        setup["case"]["id"],
        setup["case"]["version"],
        document_reference=f"DRO-2663-E{ssn}",
        proposed_percentage_bps=4000,
    )
    assert setup["draft"]["deficiency_codes"] == []
    assert fixtures.held_hold_for_case(client, setup["case"]["id"])[
        "hold_amount_cents"
    ] == 1600000
    return setup


def test_period_end_credits_the_whole_move_while_pro_rata_credits_the_elapsed_part(
    client,
):
    """Identical snapshots fund 1648000 under one method and 1620160 under the other.

    PRD: "Under `PERIOD_END` the growth is credited verbatim — the whole
    valuation-to-valuation move goes to the segregated amount regardless of how
    much of the interval elapsed before segregation."

    Design: Difficulty/dual_variant_calc/period_end_versus_pro_rata_daily_earnings_divergence
    """
    whole = _one_bucket_case(
        client, "Northwind Savings Plan", EARNINGS_PERIOD_END, "3301"
    )
    elapsed = _one_bucket_case(
        client, "Southwind Savings Plan", EARNINGS_PRO_RATA_DAILY, "3302"
    )

    fixtures.set_clock(client, constants.CLOCK_2026_09_15)
    fixtures.qualify(client, whole["draft"]["id"])
    fixtures.qualify(client, elapsed["draft"]["id"])

    whole_hold = fixtures.hold_for_case(client, whole["case"]["id"])
    assert_hold(
        whole_hold,
        status=HOLD_CONVERTED,
        hold_amount_cents=1600000,
        segregation_date="2026-09-15",
        earnings_growth_bps=300,
        earnings_adjustment_cents=48000,
    )
    assert whole_hold["valuation_date"] == "2026-06-30"

    elapsed_hold = fixtures.hold_for_case(client, elapsed["case"]["id"])
    assert_hold(
        elapsed_hold,
        status=HOLD_CONVERTED,
        hold_amount_cents=1600000,
        segregation_date="2026-09-15",
        earnings_growth_bps=126,
        earnings_adjustment_cents=20160,
    )
    assert elapsed_hold["valuation_date"] == "2026-06-30"

    assert (
        fixtures.ap_account_for_case(client, whole["case"]["id"])["balance_cents"]
        == 1648000
    )
    assert (
        fixtures.ap_account_for_case(client, elapsed["case"]["id"])["balance_cents"]
        == 1620160
    )
    assert_plan_account_figures(
        fixtures.read_plan_account(client, whole["account"]["id"]),
        vested_balance_cents=2352000,
        assignable_base_cents=2352000,
        held_amount_cents=0,
        available_balance_cents=2352000,
    )
    assert_plan_account_figures(
        fixtures.read_plan_account(client, elapsed["account"]["id"]),
        vested_balance_cents=2379840,
        assignable_base_cents=2379840,
        held_amount_cents=0,
        available_balance_cents=2379840,
    )


def test_the_pro_rata_credit_is_strictly_smaller_than_the_period_end_credit(client):
    """77 elapsed days out of a 184-day span scale 300 bps down to 126.

    PRD: "Whenever the elapsed portion is shorter than the span, `PRO_RATA_DAILY`
    yields a strictly smaller magnitude than `PERIOD_END`."

    Design: Difficulty/dual_variant_calc/period_end_versus_pro_rata_daily_earnings_divergence
    """
    whole = _one_bucket_case(
        client, "Northwind Preview Plan", EARNINGS_PERIOD_END, "3303"
    )
    elapsed = _one_bucket_case(
        client, "Southwind Preview Plan", EARNINGS_PRO_RATA_DAILY, "3304"
    )
    fixtures.set_clock(client, constants.CLOCK_2026_09_15)

    whole_view = validate_success(
        client.get_benefit_projection(whole["case"]["id"], ADMIN_HEADERS)
    )
    elapsed_view = validate_success(
        client.get_benefit_projection(elapsed["case"]["id"], ADMIN_HEADERS)
    )

    assert whole_view["gross_assigned_amount_cents"] == 1600000
    assert elapsed_view["gross_assigned_amount_cents"] == 1600000, (
        "the two plans differ only in how growth is credited, never in principal"
    )
    assert whole_view["earnings_growth_bps"] == 300
    assert elapsed_view["earnings_growth_bps"] == 126
    assert elapsed_view["earnings_growth_bps"] < whole_view["earnings_growth_bps"]
    assert whole_view["earnings_adjustment_cents"] == 48000
    assert elapsed_view["earnings_adjustment_cents"] == 20160
    assert (
        elapsed_view["earnings_adjustment_cents"]
        < whole_view["earnings_adjustment_cents"]
    )
    assert whole_view["separate_interest_balance_cents"] == 1648000
    assert elapsed_view["separate_interest_balance_cents"] == 1620160

    # Both previews were pure reads: the holds are still live and unconverted.
    for scenario in (whole, elapsed):
        assert_hold(
            fixtures.held_hold_for_case(client, scenario["case"]["id"]),
            status=HOLD_HELD,
            hold_amount_cents=1600000,
            segregation_date=None,
            earnings_growth_bps=0,
            earnings_adjustment_cents=0,
        )
        assert fixtures.read_ap_accounts(client, scenario["case"]["id"]) == []
