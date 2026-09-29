"""Compensating actions that must return a conserved quantity exactly."""
from test_helpers import assertions as asrt
from test_helpers import fixtures as fx

EARNED_ONLY = (
    {
        "source_type": "EARNED",
        "gross_monthly_cents": 40000,
        "is_recurring": True,
        "verification_status": "VERIFIED",
    },
)

STANDARD_INCOMES = (
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
)


def _case_with_forty_five_thousand_committed_and_a_second_request(api, name):
    """Transportation headroom down to 15000, with a 30000 request pending."""
    context = fx.build_active_case(
        api,
        household_overrides={"head_of_household_name": name},
        incomes=EARNED_ONLY,
    )
    assignment = fx.create_active_assignment(
        api,
        context.case_id,
        activity_category="COMMUNITY_SERVICE",
        scheduled_weekly_hours=20,
        start_date="2026-08-01",
        end_date="2026-12-01",
    )
    committed = fx.build_authorized_service(
        api,
        context.case_id,
        assignment["id"],
        service_type="TRANSPORTATION",
        requested_amount_cents=45000,
        period_start="2026-08-01",
        period_end="2026-08-31",
    )
    pending = fx.request_authorization(
        api,
        context.case_id,
        assignment["id"],
        service_type="TRANSPORTATION",
        requested_amount_cents=30000,
        period_start="2026-09-01",
        period_end="2026-09-30",
    )
    return context, assignment["id"], committed["id"], pending["id"]


def test_the_waterfall_awards_only_the_remaining_headroom(api):
    """PRD §3.8: "When the waterfall lands strictly between zero and the requested
    amount, the authorization still moves `REQUESTED → AUTHORIZED` and carries the
    smaller figure."
    PRD §3.8: "On a successful authorization the case's
    `supportive_fy_authorized_cents` is recomputed as the total of
    `authorized_amount_cents` across the case's `AUTHORIZED` authorizations whose
    fiscal year matches the *current* federal fiscal year derived from the logical
    clock — note that this rollup tracks the current year, while the waterfall itself
    is evaluated against the candidate authorization's own fiscal year."

    Design: Difficulty/compensating_invariant/voiding_a_partial_authorization_restores_the_transportation_fiscal_year_headroom
    """
    context, _assignment_id, _committed_id, pending_id = _case_with_forty_five_thousand_committed_and_a_second_request(
        api, "Conserved Cap A Household"
    )

    fx.authorize(api, pending_id)

    asrt.assert_authorization(
        fx.read_authorization(api, pending_id),
        status="AUTHORIZED",
        authorized_amount_cents=15000,
    )
    asrt.assert_money(
        fx.read_case(api, context.case_id)["supportive_fy_authorized_cents"],
        60000,
        "supportive fiscal-year total",
    )


def test_voiding_returns_the_awarded_amount_and_nothing_more(api):
    """PRD §3.8: "The row moves to `VOIDED`, stores the supplied free-text
    `void_reason`, returns `authorized_amount_cents` to 0, and the case's
    `supportive_fy_authorized_cents` is recomputed so that the freed per-service-type
    and per-case headroom is restored *exactly*."
    PRD §3.8: "Voided authorizations do not block a replacement period."

    Design: Difficulty/compensating_invariant/voiding_a_partial_authorization_restores_the_transportation_fiscal_year_headroom
    """
    context, assignment_id, committed_id, pending_id = _case_with_forty_five_thousand_committed_and_a_second_request(
        api, "Conserved Cap B Household"
    )
    fx.authorize(api, pending_id)

    fx.void_authorization(api, pending_id, void_reason="SERVICE_NOT_DELIVERED")

    asrt.assert_authorization(
        fx.read_authorization(api, pending_id),
        status="VOIDED",
        authorized_amount_cents=0,
    )
    asrt.assert_authorization(
        fx.read_authorization(api, committed_id),
        status="AUTHORIZED",
        authorized_amount_cents=45000,
    )
    asrt.assert_money(
        fx.read_case(api, context.case_id)["supportive_fy_authorized_cents"],
        45000,
        "supportive fiscal-year total after the void",
    )

    replacement = fx.request_authorization(
        api,
        context.case_id,
        assignment_id,
        service_type="TRANSPORTATION",
        requested_amount_cents=30000,
        period_start="2026-09-01",
        period_end="2026-09-30",
    )
    fx.authorize(api, replacement["id"])

    asrt.assert_authorization(
        fx.read_authorization(api, replacement["id"]),
        status="AUTHORIZED",
        authorized_amount_cents=15000,
    )
    asrt.assert_money(
        fx.read_case(api, context.case_id)["supportive_fy_authorized_cents"],
        60000,
        "supportive fiscal-year total after the replacement",
    )


def _household_with_three_issued_months_and_a_pending_extension(api, name):
    """Three issued months and a two-month hardship request from 2026-09."""
    context = fx.build_active_case(
        api,
        household_overrides={"head_of_household_name": name},
        incomes=EARNED_ONLY,
        benefit_months=("2026-08", "2026-09", "2026-10"),
    )
    extension = fx.request_extension(
        api,
        context.case_id,
        extension_type="HARDSHIP_DISABILITY",
        months_requested=2,
        first_effective_month="2026-09",
    )
    return context, extension["id"]


def test_granting_moves_two_months_from_the_state_clock_into_the_extension_count(api):
    """PRD §3.4: "On success the extension moves `REQUESTED → GRANTED`, stores the
    granted count, derives `last_effective_month` as the first effective month
    advanced by one fewer than the granted count so that the span is inclusive at both
    ends, and records the acting supervisor in `decided_by_user_id`."
    PRD §3.4: "Every time-limit month of that case whose benefit month falls within the
    inclusive span from `first_effective_month` through `last_effective_month` is
    flipped to state-non-countable with `non_countable_reason` `GRANTED_EXTENSION`, and
    its federal countability is left exactly as it was."

    Design: Difficulty/compensating_invariant/revoking_a_hardship_extension_restores_the_state_clock_months_it_shielded
    """
    context, extension_id = _household_with_three_issued_months_and_a_pending_extension(
        api, "Conserved Months A Household"
    )
    asrt.assert_household_clocks(
        fx.read_household(api, context.household_id),
        state_clock_months_used=3,
        issued_countable_months=3,
    )

    fx.grant_extension(api, extension_id, 2)

    extension = fx.read_extension(api, context.case_id, extension_id)
    assert extension["status"] == "GRANTED"
    assert extension["last_effective_month"] == "2026-10"
    asrt.assert_household_clocks(
        fx.read_household(api, context.household_id),
        state_clock_months_used=1,
        federal_clock_months_used=3,
        extension_months_used=2,
        issued_countable_months=3,
    )
    rows = fx.list_time_limit_months(api, context.case_id)
    asrt.assert_time_limit_month(
        asrt.find_time_limit_month(rows, "2026-09"),
        state_clock_countable=False,
        federal_clock_countable=True,
        non_countable_reason="GRANTED_EXTENSION",
    )


def test_revoking_returns_the_shielded_months_to_the_state_clock_exactly(api):
    """PRD §3.4: "The extension's `months_granted` returns to 0 and its
    `last_effective_month` returns to null."
    PRD §3.4: "Every time-limit month this extension had shielded is restored to
    state-countable with `non_countable_reason` `NONE`, *unless* another
    still-`GRANTED` extension of the case also covers that month, in which case it
    stays shielded and keeps its `GRANTED_EXTENSION` reason."
    PRD §2.11: "state-countable months beyond the carried-in prior state figure, plus
    extension months used, equals the issued countable months, which equals
    federal-countable months beyond the carried-in prior federal figure."

    Design: Difficulty/compensating_invariant/revoking_a_hardship_extension_restores_the_state_clock_months_it_shielded
    """
    context, extension_id = _household_with_three_issued_months_and_a_pending_extension(
        api, "Conserved Months B Household"
    )
    fx.grant_extension(api, extension_id, 2)

    fx.revoke_extension(api, extension_id, revocation_reason="MEDICAL_REVIEW_CLEARED")

    extension = fx.read_extension(api, context.case_id, extension_id)
    assert extension["status"] == "REVOKED"
    assert extension["months_granted"] == 0
    asrt.assert_household_clocks(
        fx.read_household(api, context.household_id),
        state_clock_months_used=3,
        federal_clock_months_used=3,
        extension_months_used=0,
        issued_countable_months=3,
    )
    rows = fx.list_time_limit_months(api, context.case_id)
    asrt.assert_time_limit_month(
        asrt.find_time_limit_month(rows, "2026-10"),
        state_clock_countable=True,
        non_countable_reason="NONE",
    )
    asrt.assert_case_state(fx.read_case(api, context.case_id), benefit_status="ACTIVE")


def _established_claim_of_thirty_thousand(api, name):
    """A CLIENT_ERROR claim of 30000 cents established against a live grant."""
    context = fx.build_active_case(
        api,
        household_overrides={"head_of_household_name": name},
        incomes=STANDARD_INCOMES,
    )
    claim = fx.build_established_overpayment(
        api,
        context.case_id,
        claim_type="CLIENT_ERROR",
        months_covered=["2026-08"],
        computation_method="GROSS",
        gross_amount_cents=30000,
    )
    return context, claim["id"]


def test_a_cash_payment_moves_money_from_the_balance_into_the_recovered_total(api):
    """PRD §3.9: "The `monthly_recoupment_cents` figure is that percentage of the
    case's *current* `benefit_amount_cents`, rounded half up to a whole cent, and then
    raised to a floor of 1000 cents if it came out lower — a family with a tiny grant
    still repays at least ten dollars a month."
    PRD §3.9: "After each entry the claim's `total_recovered_cents` becomes the sum of
    `signed_amount_cents` across all of that claim's entries, and `balance_cents`
    becomes the established amount less that total, which keeps the conserved debt
    identity of §2.11 true at every point."

    Design: Difficulty/compensating_invariant/recoupment_reversal_returns_the_overpayment_ledger_to_its_established_balance
    """
    _context, claim_id = _established_claim_of_thirty_thousand(
        api, "Conserved Ledger A Household"
    )
    asrt.assert_overpayment_ledger(
        fx.read_overpayment(api, claim_id),
        established_amount_cents=30000,
        monthly_recoupment_cents=1700,
        balance_cents=30000,
    )

    payment = fx.post_recovery(
        api,
        claim_id,
        method="CASH_PAYMENT",
        amount_cents=12000,
        applied_month="2026-09",
    )

    assert payment["signed_amount_cents"] == 12000
    asrt.assert_overpayment_ledger(
        fx.read_overpayment(api, claim_id),
        status="IN_RECOVERY",
        total_recovered_cents=12000,
        balance_cents=18000,
    )


def test_a_reversal_credits_the_ledger_back_without_deleting_the_payment(api):
    """PRD §3.9: "Each entry's `signed_amount_cents` is the negative of its stated
    amount when the method is `RECOUPMENT_REVERSAL` and the positive of its stated
    amount otherwise — a reversal credits the participant back."
    PRD §3.9: "Recovery transactions are append-only ledger rows with no `updated_at`
    and no `version`, per §2.4."

    Design: Difficulty/compensating_invariant/recoupment_reversal_returns_the_overpayment_ledger_to_its_established_balance
    """
    _context, claim_id = _established_claim_of_thirty_thousand(
        api, "Conserved Ledger B Household"
    )
    fx.post_recovery(
        api,
        claim_id,
        method="CASH_PAYMENT",
        amount_cents=12000,
        applied_month="2026-09",
    )

    reversal = fx.post_recovery(
        api,
        claim_id,
        method="RECOUPMENT_REVERSAL",
        amount_cents=12000,
        applied_month="2026-10",
    )

    assert reversal["signed_amount_cents"] == -12000
    asrt.assert_append_only_record(reversal)
    asrt.assert_overpayment_ledger(
        fx.read_overpayment(api, claim_id),
        status="IN_RECOVERY",
        total_recovered_cents=0,
        balance_cents=30000,
    )
    assert len(fx.list_recoveries(api, claim_id)) == 2
