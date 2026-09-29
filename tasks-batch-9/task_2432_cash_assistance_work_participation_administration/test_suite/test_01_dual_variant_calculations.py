"""Paired calculation variants that consume the same inputs differently."""
from test_helpers import assertions as asrt
from test_helpers import fixtures as fx

# The same four reported income rows are attached to both applications.
IDENTICAL_INCOME_ROWS = (
    {
        "source_type": "EARNED",
        "gross_monthly_cents": 40000,
        "month_1_cents": 41000,
        "month_2_cents": 40000,
        "month_3_cents": 39000,
        "is_recurring": True,
        "verification_status": "VERIFIED",
    },
    {
        "source_type": "EARNED",
        "gross_monthly_cents": 30000,
        "month_1_cents": 31000,
        "month_2_cents": 30000,
        "month_3_cents": 29000,
        "is_recurring": False,
    },
    {
        "source_type": "UNEARNED_CHILD_SUPPORT",
        "gross_monthly_cents": 20000,
        "month_1_cents": 20000,
        "month_2_cents": 20000,
        "month_3_cents": 20000,
        "is_recurring": True,
        "verification_status": "VERIFIED",
    },
    {
        "source_type": "UNEARNED_UI",
        "gross_monthly_cents": 15000,
        "month_1_cents": 15000,
        "month_2_cents": 15000,
        "month_3_cents": 15000,
        "is_recurring": True,
        "verification_status": "REFUSED",
    },
)


def _determine_both_methods(api):
    """Determine two identical applications, one per budgeting method."""
    prospective = fx.build_determined_application(
        api,
        household_overrides={"head_of_household_name": "Prospective Household"},
        application_overrides={"budgeting_method": "PROSPECTIVE"},
        incomes=IDENTICAL_INCOME_ROWS,
    )
    retrospective = fx.build_determined_application(
        api,
        household_overrides={"head_of_household_name": "Retrospective Household"},
        application_overrides={"budgeting_method": "RETROSPECTIVE"},
        incomes=IDENTICAL_INCOME_ROWS,
    )
    return (
        fx.read_application(api, prospective["application"]["id"]),
        fx.read_application(api, retrospective["application"]["id"]),
    )


def test_budgeting_methods_diverge_on_countable_income(api):
    """PRD §3.2: "Under `PROSPECTIVE` budgeting, only income sources whose
    `verification_status` is `VERIFIED` **and** whose `is_recurring` flag is true
    participate, and each participating source contributes its
    `gross_monthly_cents` unchanged."
    PRD §3.2: "Under `RETROSPECTIVE` budgeting, income sources whose
    `verification_status` is either `VERIFIED` or `UNVERIFIED` participate — only
    `REFUSED` sources are excluded, and the recurrence flag is ignored entirely —
    and each participating source contributes the sum of its three base-month
    figures divided by three and then floored."

    Design: Difficulty/dual_variant_calc/prospective_vs_retrospective_budgeting_diverge_on_identical_income_records
    """
    prospective, retrospective = _determine_both_methods(api)

    asrt.assert_money(
        prospective["countable_income_cents"], 29000, "prospective countable income"
    )
    asrt.assert_money(
        retrospective["countable_income_cents"], 44000, "retrospective countable income"
    )
    assert prospective["snapshot_family_type"] == "SINGLE_PARENT"
    assert retrospective["snapshot_family_type"] == "SINGLE_PARENT"


def test_budgeting_methods_diverge_on_determined_benefit(api):
    """PRD §3.2: "Countable income is computed by two genuinely distinct pipelines
    selected by `budgeting_method`; they differ both in which income sources
    participate and in how each participating source's monthly figure is derived."
    PRD §3.2: "Step two takes the deficit as the payment standard less countable
    income, floored at zero."

    Design: Difficulty/dual_variant_calc/prospective_vs_retrospective_budgeting_diverge_on_identical_income_records
    """
    prospective, retrospective = _determine_both_methods(api)

    asrt.assert_money(
        prospective["determined_benefit_cents"], 17000, "prospective benefit"
    )
    asrt.assert_money(
        retrospective["determined_benefit_cents"], 4250, "retrospective benefit"
    )
    assert (
        prospective["determined_benefit_cents"] != retrospective["determined_benefit_cents"]
    ), "identical income records must not produce identical grants under both methods"


def _case_with_three_issued_months(api):
    """An ACTIVE case with 2026-08, 2026-09 and 2026-10 issued."""
    context = fx.build_active_case(
        api,
        benefit_months=("2026-08", "2026-09", "2026-10"),
        household_overrides={"head_of_household_name": "Clock Divergence Household"},
        incomes=(
            {
                "source_type": "EARNED",
                "gross_monthly_cents": 40000,
                "is_recurring": True,
                "verification_status": "VERIFIED",
            },
            {
                "source_type": "UNEARNED_CHILD_SUPPORT",
                "gross_monthly_cents": 20000,
                "is_recurring": True,
                "verification_status": "VERIFIED",
            },
        ),
    )
    return context


def test_granted_extension_shields_the_state_clock_but_not_the_federal_clock(api):
    """PRD §3.4: "Hardship extension months are state-funded and therefore do not
    stop the federal clock at all."
    PRD §3.4: "`state_clock_months_used` is `prior_state_clock_months` plus the
    number of state-countable rows."
    PRD §3.4: "`federal_clock_months_used` is `prior_federal_clock_months` plus the
    number of federal-countable rows."

    Design: Difficulty/dual_variant_calc/state_clock_and_federal_clock_diverge_over_extension_covered_months
    """
    context = _case_with_three_issued_months(api)
    extension = fx.request_extension(
        api,
        context.case_id,
        extension_type="HARDSHIP_DISABILITY",
        months_requested=3,
        first_effective_month="2026-09",
    )

    fx.grant_extension(api, extension["id"], 2)

    household = fx.read_household(api, context.household_id)
    asrt.assert_household_clocks(
        household,
        state_clock_months_used=1,
        federal_clock_months_used=3,
        extension_months_used=2,
        issued_countable_months=3,
    )
    asrt.assert_case_state(
        fx.read_case(api, context.case_id), benefit_status="ACTIVE"
    )


def test_extension_grant_flips_only_state_countability_on_covered_rows(api):
    """PRD §3.4: "Every time-limit month of that case whose benefit month falls
    within the inclusive span from `first_effective_month` through
    `last_effective_month` is flipped to state-non-countable with
    `non_countable_reason` `GRANTED_EXTENSION`, and its federal countability is
    left exactly as it was."
    PRD §3.4: "On success the extension moves `REQUESTED → GRANTED`, stores the
    granted count, derives `last_effective_month` as the first effective month
    advanced by one fewer than the granted count so that the span is inclusive at
    both ends, and records the acting supervisor in `decided_by_user_id`."

    Design: Difficulty/dual_variant_calc/state_clock_and_federal_clock_diverge_over_extension_covered_months
    """
    context = _case_with_three_issued_months(api)
    extension = fx.request_extension(
        api,
        context.case_id,
        extension_type="HARDSHIP_DISABILITY",
        months_requested=3,
        first_effective_month="2026-09",
    )

    fx.grant_extension(api, extension["id"], 2)

    stored = fx.read_extension(api, context.case_id, extension["id"])
    assert stored["status"] == "GRANTED"
    assert stored["months_granted"] == 2
    assert stored["last_effective_month"] == "2026-10"

    rows = fx.list_time_limit_months(api, context.case_id)
    august = asrt.find_time_limit_month(rows, "2026-08")
    september = asrt.find_time_limit_month(rows, "2026-09")
    october = asrt.find_time_limit_month(rows, "2026-10")
    asrt.assert_time_limit_month(
        august,
        state_clock_countable=True,
        federal_clock_countable=True,
        non_countable_reason="NONE",
    )
    for shielded in (september, october):
        asrt.assert_time_limit_month(
            shielded,
            state_clock_countable=False,
            federal_clock_countable=True,
            non_countable_reason="GRANTED_EXTENSION",
        )


def _two_claims_over_one_issued_month(api):
    """One ACTIVE case with two DRAFT claims that differ only in method."""
    context = fx.build_active_case(
        api,
        household_overrides={"head_of_household_name": "Overpayment Variant Household"},
        incomes=(
            {
                "source_type": "EARNED",
                "gross_monthly_cents": 40000,
                "is_recurring": True,
                "verification_status": "VERIFIED",
            },
            {
                "source_type": "UNEARNED_CHILD_SUPPORT",
                "gross_monthly_cents": 20000,
                "is_recurring": True,
                "verification_status": "VERIFIED",
            },
        ),
    )
    claim_inputs = {
        "claim_type": "CLIENT_ERROR",
        "months_covered": ["2026-08"],
        "gross_amount_cents": 34000,
        "offsetting_underpayment_cents": 4000,
    }
    gross = fx.draft_overpayment(
        api, context.case_id, computation_method="GROSS", **claim_inputs
    )
    net = fx.draft_overpayment(
        api, context.case_id, computation_method="NET", **claim_inputs
    )
    return context, gross["id"], net["id"]


def test_gross_establishment_ignores_the_offsetting_underpayment(api):
    """PRD §3.9: "Under `GROSS`, the established amount is the
    `gross_amount_cents` figure and the `offsetting_underpayment_cents` figure is
    ignored entirely."
    PRD §3.9: "Establishment also sets `balance_cents` to the established amount
    less the total recovered, records the acting user in `established_by_user_id`,
    sets `recoupment_status` to `NOT_STARTED`, and moves the claim
    `DRAFT → ESTABLISHED`."

    Design: Difficulty/dual_variant_calc/gross_versus_net_overpayment_establishment_from_identical_claim_inputs
    """
    _context, gross_id, _net_id = _two_claims_over_one_issued_month(api)

    fx.establish_overpayment(api, gross_id)

    asrt.assert_overpayment_ledger(
        fx.read_overpayment(api, gross_id),
        status="ESTABLISHED",
        recoupment_status="NOT_STARTED",
        established_amount_cents=34000,
        total_recovered_cents=0,
        balance_cents=34000,
        monthly_recoupment_cents=1700,
    )


def test_net_establishment_subtracts_the_offsetting_underpayment(api):
    """PRD §3.9: "Under `NET`, the established amount is the gross figure less the
    offsetting underpayment, floored at zero so that an offset larger than the
    overissuance establishes nothing rather than a credit."
    PRD §3.9: "The applicable percentage is 5 percent for an `AGENCY_ERROR` claim,
    10 percent for a `CLIENT_ERROR` claim and 20 percent for a `SUSPECTED_FRAUD`
    claim — unless the claim's `fraud_referral_status` has already reached
    `SUBSTANTIATED`, in which case the percentage is 25 percent regardless of
    claim type."

    Design: Difficulty/dual_variant_calc/gross_versus_net_overpayment_establishment_from_identical_claim_inputs
    """
    _context, gross_id, net_id = _two_claims_over_one_issued_month(api)

    fx.establish_overpayment(api, gross_id)
    fx.establish_overpayment(api, net_id)

    asrt.assert_overpayment_ledger(
        fx.read_overpayment(api, net_id),
        status="ESTABLISHED",
        established_amount_cents=30000,
        balance_cents=30000,
        monthly_recoupment_cents=1700,
    )
    gross_claim = fx.read_overpayment(api, gross_id)
    assert gross_claim["established_amount_cents"] == 34000, (
        "the two computation methods must diverge on identical claim inputs, got "
        f"{gross_claim['established_amount_cents']}"
    )
