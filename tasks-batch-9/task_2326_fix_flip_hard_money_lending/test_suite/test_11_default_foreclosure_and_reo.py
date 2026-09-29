"""Default declaration and its cascade, the foreclosure timeline and REO settlement."""

from test_helpers import (
    ApiErrorId,
    ApplicationStatus,
    BorrowerStatus,
    DrawRequestStatus,
    ForeclosureCaseStatus,
    LedgerEntryType,
    LoanConstructionStatus,
    LoanExitStatus,
    LoanPaymentStatus,
    MilestoneType,
    PropertyStatus,
    RehabLineItemStatus,
    api_client,
    assert_loan_buckets,
    factories,
    fixtures,
    validate_error,
    validate_paginated,
    validate_success,
    CREDIT_COMMITTEE,
    LOAN_OFFICER,
    SERVICER,
    SERVICER_2,
)

CLOSING_DATE = "2026-08-10"
DRAW_CLOCK = "2026-09-01T12:00:00Z"
FUNDING_DATE = "2026-09-01"
DELINQUENT_CLOCK = "2027-02-16T12:00:00Z"
DEFAULT_CLOCK = "2027-02-26T09:00:00Z"
DEFAULT_DATE = "2027-02-26"
REDEMPTION_EXPIRY = "2027-05-27"
SALE_DATE = "2027-07-28"
BUDGET_CAP = 6_400_000


def _drain_the_reserve(ctx):
    """Two accruals take the 802,338 reserve to zero and leave 333 unpaid."""
    fixtures.set_clock(DELINQUENT_CLOCK)
    fixtures.accrue(ctx.loan_id, CLOSING_DATE, "2027-02-15")
    fixtures.accrue(ctx.loan_id, "2027-02-16", "2027-02-16")
    return ctx.refresh_loan()


def _defaulted_loan():
    """A closed loan aged into `DEFAULT` through the ten-day delinquency test."""
    ctx = fixtures.build_closed_loan()
    _drain_the_reserve(ctx)
    fixtures.set_clock(DEFAULT_CLOCK)
    fixtures.declare_default(ctx.loan_id)
    ctx.refresh_loan()
    return ctx


def _reo_ready_case():
    """Default, notice, the split-rate accrual and the takeover, in order."""
    ctx = _defaulted_loan()
    case = fixtures.open_foreclosure_case(ctx.loan_id, DEFAULT_DATE)
    fixtures.set_clock("2027-03-31T12:00:00Z")
    fixtures.accrue(ctx.loan_id, "2027-02-17", "2027-03-31")
    fixtures.set_clock(f"{REDEMPTION_EXPIRY}T09:00:00Z")
    case = fixtures.take_over(case["id"], REDEMPTION_EXPIRY)
    ctx.refresh_loan()
    return ctx, case


def _budget_attempt(case_id, budget_cents, expected_version):
    return api_client.set_completion_budget(
        case_id,
        factories.completion_budget_payload(budget_cents, expected_version),
        SERVICER,
    )


def _disposition_attempt(case_id, sale_price_cents, completion_spend_cents):
    return api_client.dispose_foreclosure_case(
        case_id,
        factories.disposition_payload(
            sale_price_cents, SALE_DATE, completion_spend_cents
        ),
        SERVICER,
    )


class TestDefaultCascade:
    def test_one_declaration_reaches_four_levels_down_and_stops_where_it_should(self):
        """Loan to sponsor to the sponsor's other application to that application's lines.

        The closed application and its funded scope-line history are deliberately
        left alone, and the sideways branch suspends only the still-open draw, so a
        one-level implementation would leave the draft application and its lines
        live. The PRD states: "A level below that, every *other* application of that
        sponsor whose `status` is `DRAFT` or `SIZED` moves to `WITHDRAWN`; and a level
        below that, every scope line of those applications in `PROPOSED`,
        `REVISION_REQUESTED` or `APPROVED` moves to `VOID`."

        Design: Difficulty/transitive_cascade/default_declaration_cascades_loan_to_sponsor_to_apps_to_scope_lines
        """
        ctx = fixtures.build_closed_loan()
        fixtures.file_waiver(ctx.loan_id, ctx.contractor_id(0), 3_400_000)
        fixtures.file_waiver(ctx.loan_id, ctx.contractor_id(1), 700_000)
        fixtures.set_clock(DRAW_CLOCK)
        roof = ctx.line_by_code("ROOF")["id"]
        kitchen = ctx.line_by_code("KITCHEN")["id"]
        electrical = ctx.line_by_code("ELECTRICAL")["id"]
        funded_draw, _ = fixtures.build_inspected_draw(
            ctx,
            [(roof, 0.60), (kitchen, 0.45), (electrical, 0.33)],
            [(roof, 0.50), (kitchen, 0.45), (electrical, 0.30)],
        )
        fixtures.review_draw(funded_draw["id"])
        fixtures.fund_draw(funded_draw["id"], SERVICER_2, FUNDING_DATE)
        open_draw = fixtures.submit_draw(ctx, [(electrical, 0.60)])
        assert open_draw["status"] == DrawRequestStatus.SUBMITTED.value

        other_property = fixtures.register_property(address_line="42 Cholla Way")
        draft = fixtures.open_application(ctx.borrower_id, other_property["id"])
        draft_lines = [
            fixtures.add_scope_line(
                draft["id"], spec, ctx.contractor_id(spec.contractor)
            )
            for spec in fixtures.TWO_LINE_SCOPE
        ]
        assert draft["status"] == ApplicationStatus.DRAFT.value
        for line in draft_lines:
            assert line["status"] == RehabLineItemStatus.PROPOSED.value

        fixtures.set_clock("2027-01-31T12:00:00Z")
        fixtures.accrue(ctx.loan_id, CLOSING_DATE, "2027-01-31")
        assert ctx.refresh_loan()["payment_status"] == LoanPaymentStatus.DELINQUENT.value

        fixtures.set_clock("2027-02-11T09:00:00Z")
        loan = fixtures.declare_default(ctx.loan_id)
        assert loan["payment_status"] == LoanPaymentStatus.DEFAULT.value
        assert loan["default_effective_date"] == "2027-02-11"
        assert loan["default_rate_bps"] == 1750

        sponsor = validate_success(
            api_client.get_borrower(ctx.borrower_id, LOAN_OFFICER), 200
        )
        assert sponsor["status"] == BorrowerStatus.SUSPENDED.value
        assert sponsor["suspension_reason"] == "LOAN_DEFAULT"
        assert sponsor["prior_default_count"] == 1

        assert fixtures.read_application(draft["id"])["status"] == (
            ApplicationStatus.WITHDRAWN.value
        )
        for line in draft_lines:
            assert fixtures.read_line(line["id"])["status"] == (
                RehabLineItemStatus.VOID.value
            ), "the fourth level of the cascade must void the draft's scope lines"

        assert fixtures.read_draw_request(open_draw["id"])["status"] == (
            DrawRequestStatus.SUSPENDED.value
        )
        assert fixtures.read_draw_request(funded_draw["id"])["status"] == (
            DrawRequestStatus.FUNDED.value
        ), "a funded draw is history and must not be suspended"

        assert ctx.refresh_application()["status"] == ApplicationStatus.CLOSED.value
        surviving = fixtures.read_line(roof)
        assert surviving["status"] == RehabLineItemStatus.APPROVED.value
        assert surviving["released_cents"] == 1_800_000

        loan = ctx.refresh_loan()
        assert_loan_buckets(
            loan,
            funded_principal_cents=17_846_213,
            reserved_release_cents=0,
            undisbursed_holdback_cents=6_107_500,
        )
        assert loan["commitment_balance_check_cents"] == 0

        validate_error(
            api_client.borrower_status_action(
                ctx.borrower_id, factories.reinstate_payload(), CREDIT_COMMITTEE
            ),
            ApiErrorId.BORROWER_NOT_ELIGIBLE.value,
        )
        still_suspended = validate_success(
            api_client.get_borrower(ctx.borrower_id, LOAN_OFFICER), 200
        )
        assert still_suspended["status"] == BorrowerStatus.SUSPENDED.value

    def test_the_cascade_follows_the_sponsor_and_never_crosses_to_a_peer(self):
        """A maturity-breach default withdraws its own sponsor's sized deal and nothing else.

        A second sponsor's draft application and proposed lines sit untouched on the
        far side of the cascade boundary, so the propagation is scoped by sponsor
        rather than applied platform-wide. The PRD states: "A `CURRENT` loan may be
        declared in default on a maturity breach, when the logical-clock date is
        strictly later than `maturity_date`, moving `CURRENT → DEFAULT`."

        Design: Difficulty/transitive_cascade/default_declaration_cascades_loan_to_sponsor_to_apps_to_scope_lines
        """
        ctx = fixtures.build_closed_loan()
        sized_property = fixtures.register_property(address_line="42 Cholla Way")
        sized = fixtures.open_application(ctx.borrower_id, sized_property["id"])
        sized_lines = [
            fixtures.add_scope_line(
                sized["id"], spec, ctx.contractor_id(spec.contractor)
            )
            for spec in fixtures.TWO_LINE_SCOPE
        ]
        for spec, line in zip(fixtures.TWO_LINE_SCOPE, sized_lines):
            fixtures.approve_scope_line(line["id"], spec.cost_cents)
        validate_success(
            api_client.size_application(
                sized["id"], factories.size_payload(), LOAN_OFFICER
            ),
            200,
        )
        assert fixtures.read_application(sized["id"])["status"] == (
            ApplicationStatus.SIZED.value
        )

        peer = fixtures.build_approved_sponsor(
            legal_entity_name="Sagebrush Holdings LLC"
        )
        peer_property = fixtures.register_property(address_line="9 Ocotillo Ln")
        peer_draft = fixtures.open_application(peer["id"], peer_property["id"])
        peer_line = fixtures.add_scope_line(
            peer_draft["id"], fixtures.TWO_LINE_SCOPE[0], ctx.contractor_id(0)
        )

        assert ctx.loan["maturity_date"] == "2027-05-10"
        fixtures.set_clock("2027-05-11T09:00:00Z")
        loan = fixtures.declare_default(ctx.loan_id)
        assert loan["payment_status"] == LoanPaymentStatus.DEFAULT.value
        assert loan["default_effective_date"] == "2027-05-11"
        assert loan["delinquent_since"] is None, (
            "the maturity ground does not run through delinquency"
        )

        assert fixtures.read_application(sized["id"])["status"] == (
            ApplicationStatus.WITHDRAWN.value
        )
        for line in sized_lines:
            assert fixtures.read_line(line["id"])["status"] == (
                RehabLineItemStatus.VOID.value
            ), "an APPROVED line on a withdrawn application is voided too"

        untouched_peer = validate_success(
            api_client.get_borrower(peer["id"], LOAN_OFFICER), 200
        )
        assert untouched_peer["status"] == BorrowerStatus.APPROVED_SPONSOR.value
        assert untouched_peer["prior_default_count"] == 0
        assert fixtures.read_application(peer_draft["id"])["status"] == (
            ApplicationStatus.DRAFT.value
        )
        assert fixtures.read_line(peer_line["id"])["status"] == (
            RehabLineItemStatus.PROPOSED.value
        )


class TestForeclosureTiming:
    def test_the_default_and_the_takeover_each_reject_one_day_early(self):
        """Nine days of delinquency is not ten, and 2027-05-26 is not the expiry date.

        Both gates are day-count comparisons against a stored date, and each one
        turns from a refusal into a success on the day itself with no other change to
        the loan or the case. The PRD states: "It requires the logical-clock date to
        be on or after `redemption_expires_on` — an attempt during the redemption
        window is rejected with `ERR_REDEMPTION_PERIOD_ACTIVE` — and the loan's
        `payment_status` to be `DEFAULT`."

        Design: Corner/state_machines/default_and_takeover_each_enforce_their_own_timing_precondition
        """
        ctx = fixtures.build_closed_loan()
        loan = _drain_the_reserve(ctx)
        assert loan["payment_status"] == LoanPaymentStatus.DELINQUENT.value
        assert loan["delinquent_since"] == "2027-02-16"
        assert loan["maturity_date"] == "2027-05-10"

        fixtures.set_clock("2027-02-25T09:00:00Z")
        validate_error(
            api_client.declare_default(
                ctx.loan_id, factories.default_declaration_payload(), SERVICER
            ),
            ApiErrorId.DEFAULT_PRECONDITION_NOT_MET.value,
        )
        assert ctx.refresh_loan()["payment_status"] == LoanPaymentStatus.DELINQUENT.value

        fixtures.set_clock(DEFAULT_CLOCK)
        loan = fixtures.declare_default(ctx.loan_id)
        assert loan["payment_status"] == LoanPaymentStatus.DEFAULT.value
        assert loan["default_effective_date"] == DEFAULT_DATE
        sponsor = validate_success(
            api_client.get_borrower(ctx.borrower_id, LOAN_OFFICER), 200
        )
        assert sponsor["status"] == BorrowerStatus.SUSPENDED.value
        assert sponsor["suspension_reason"] == "LOAN_DEFAULT"
        assert sponsor["prior_default_count"] == 1

        validate_error(
            api_client.create_extension(
                ctx.loan_id, factories.extension_payload(1), SERVICER
            ),
            ApiErrorId.LOAN_NOT_SERVICEABLE.value,
        )
        validate_error(
            api_client.create_exit_milestone(
                ctx.loan_id,
                factories.milestone_payload(MilestoneType.LISTED.value, DEFAULT_DATE),
                SERVICER,
            ),
            ApiErrorId.LOAN_NOT_SERVICEABLE.value,
        )
        _, milestone_meta = validate_paginated(
            api_client.list_exit_milestones(ctx.loan_id, SERVICER)
        )
        assert milestone_meta["total_count"] == 0

        case = fixtures.open_foreclosure_case(ctx.loan_id, DEFAULT_DATE)
        assert case["status"] == ForeclosureCaseStatus.NOTICE_FILED.value
        assert case["redemption_expires_on"] == REDEMPTION_EXPIRY
        assert case["takeover_date"] is None
        assert case["completion_budget_cents"] is None
        assert case["completion_advanced_cents"] == 0

        validate_error(
            _disposition_attempt(case["id"], 18_000_000, 0),
            ApiErrorId.FORECLOSURE_CASE_STATE_INVALID.value,
        )

        fixtures.set_clock("2027-05-26T09:00:00Z")
        validate_error(
            api_client.takeover_foreclosure_case(
                case["id"], factories.takeover_payload("2027-05-26"), SERVICER
            ),
            ApiErrorId.REDEMPTION_PERIOD_ACTIVE.value,
        )
        assert fixtures.read_foreclosure_case(case["id"])["status"] == (
            ForeclosureCaseStatus.NOTICE_FILED.value
        )

        fixtures.set_clock(f"{REDEMPTION_EXPIRY}T09:00:00Z")
        taken = fixtures.take_over(case["id"], REDEMPTION_EXPIRY)
        assert taken["status"] == ForeclosureCaseStatus.TAKEOVER_COMPLETE.value
        assert taken["takeover_date"] == REDEMPTION_EXPIRY
        assert fixtures.read_property(ctx.property_id)["status"] == (
            PropertyStatus.LENDER_REO.value
        )
        loan = ctx.refresh_loan()
        assert loan["exit_status"] == LoanExitStatus.FORECLOSED.value
        assert loan["construction_status"] == LoanConstructionStatus.LENDER_COMPLETING.value
        assert_loan_buckets(
            loan,
            committed_amount_cents=23_953_713,
            undisbursed_holdback_cents=0,
            decommitted_holdback_cents=10_000_000,
        )
        assert loan["commitment_balance_check_cents"] == 0

        entries, _ = validate_paginated(
            api_client.list_ledger_entries(
                ctx.loan_id,
                SERVICER,
                {"entry_type": LedgerEntryType.HOLDBACK_DECOMMIT.value},
            )
        )
        assert len(entries) == 1, f"one decommit entry expected, got {len(entries)}"
        assert entries[0]["amount_cents"] == 10_000_000


class TestServiceabilityFence:
    def test_default_closes_the_servicing_endpoints_and_leaves_recovery_open(self):
        """Draws, extensions and milestones are shut while payments and notices work.

        All five calls hit the same loan at the same clock, so the partition is
        per-endpoint rather than a blanket freeze, and the extension refusal is the
        serviceability row rather than the repetition limit because the count is
        still zero. The PRD states: "New draw requests, draw reviews, draw funding,
        extensions and new exit milestones are all refused with
        `ERR_LOAN_NOT_SERVICEABLE`; foreclosure actions and a reinstatement payoff
        remain available."

        Design: Corner/endpoints/after_default_only_the_recovery_endpoints_stay_open
        """
        ctx = _defaulted_loan()
        assert ctx.loan["payment_status"] == LoanPaymentStatus.DEFAULT.value
        assert ctx.loan["extension_count"] == 0
        assert ctx.loan["accrued_interest_unpaid_cents"] == 333
        assert ctx.loan["funded_principal_cents"] == 13_953_713

        fresh_version = ctx.loan["version"]
        validate_error(
            api_client.create_draw_request(
                ctx.loan_id,
                factories.draw_request_payload(
                    [factories.line_allocation(ctx.line_by_code("ROOF")["id"], 0.50)],
                    fresh_version,
                ),
                ctx.borrower_headers,
            ),
            ApiErrorId.LOAN_NOT_SERVICEABLE.value,
        )
        validate_error(
            api_client.create_extension(
                ctx.loan_id, factories.extension_payload(1), SERVICER
            ),
            ApiErrorId.LOAN_NOT_SERVICEABLE.value,
        )
        validate_error(
            api_client.create_exit_milestone(
                ctx.loan_id,
                factories.milestone_payload(MilestoneType.LISTED.value, DEFAULT_DATE),
                SERVICER,
            ),
            ApiErrorId.LOAN_NOT_SERVICEABLE.value,
        )
        assert ctx.refresh_loan()["exit_status"] == LoanExitStatus.NOT_LISTED.value

        paid = fixtures.pay(ctx.loan_id, 100_000, DEFAULT_DATE)
        assert paid["fee_balance_cents"] == 0
        assert paid["accrued_interest_unpaid_cents"] == 0
        assert paid["funded_principal_cents"] == 13_854_046
        assert paid["repaid_principal_cents"] == 99_667
        assert paid["payment_status"] == LoanPaymentStatus.DEFAULT.value, (
            "the cure to CURRENT is only reachable from DELINQUENT"
        )
        assert paid["commitment_balance_check_cents"] == 0

        case = fixtures.open_foreclosure_case(ctx.loan_id, DEFAULT_DATE)
        assert case["status"] == ForeclosureCaseStatus.NOTICE_FILED.value
        assert case["notice_date"] == DEFAULT_DATE
        assert case["redemption_expires_on"] == REDEMPTION_EXPIRY

        entries, _ = validate_paginated(
            api_client.list_ledger_entries(
                ctx.loan_id,
                SERVICER,
                {"entry_type": LedgerEntryType.BORROWER_PAYMENT.value},
            )
        )
        assert len(entries) == 1
        assert entries[0]["amount_cents"] == 100_000


class TestCompletionBudgetConcurrency:
    def test_every_budget_write_consumes_the_case_version_it_quoted(self):
        """The pre-takeover version is stale, and so is the version the first budget used.

        Each refusal leaves the case's budget and the loan's commitment exactly
        where they were, so no commitment delta is ever applied twice. The PRD
        states: "If `expected_foreclosure_case_version` does not equal the case's
        current `version`, the request is rejected with
        `ERR_STALE_FORECLOSURE_CASE_VERSION` (HTTP 412) and neither the case nor the
        loan changes."

        Design: Corner/cross_cutting_complexity_layers/the_completion_budget_revision_is_guarded_by_the_case_version
        """
        ctx = _defaulted_loan()
        case = fixtures.open_foreclosure_case(ctx.loan_id, DEFAULT_DATE)
        notice_version = case["version"]
        fixtures.set_clock("2027-03-31T12:00:00Z")
        fixtures.accrue(ctx.loan_id, "2027-02-17", "2027-03-31")
        fixtures.set_clock(f"{REDEMPTION_EXPIRY}T09:00:00Z")
        fixtures.take_over(case["id"], REDEMPTION_EXPIRY)

        validate_error(
            _budget_attempt(case["id"], 5_000_000, notice_version),
            ApiErrorId.STALE_FORECLOSURE_CASE_VERSION.value,
            412,
        )
        after_refusal = fixtures.read_foreclosure_case(case["id"])
        assert after_refusal["status"] == ForeclosureCaseStatus.TAKEOVER_COMPLETE.value
        assert after_refusal["completion_budget_cents"] is None
        assert after_refusal["version"] == notice_version + 1, (
            "the takeover write is what moved the case past the captured version"
        )
        assert ctx.refresh_loan()["committed_amount_cents"] == 23_953_713

        current_version = after_refusal["version"]
        funded = fixtures.set_completion_budget(
            case["id"], 5_000_000, current_version
        )
        assert funded["status"] == ForeclosureCaseStatus.COMPLETION_FUNDED.value
        assert funded["completion_budget_cents"] == 5_000_000
        assert funded["version"] == current_version + 1
        loan = ctx.refresh_loan()
        assert_loan_buckets(
            loan,
            committed_amount_cents=28_953_713,
            undisbursed_holdback_cents=5_000_000,
        )
        assert loan["commitment_balance_check_cents"] == 0

        validate_error(
            _budget_attempt(case["id"], 4_000_000, current_version),
            ApiErrorId.STALE_FORECLOSURE_CASE_VERSION.value,
            412,
        )
        unchanged_case = fixtures.read_foreclosure_case(case["id"])
        assert unchanged_case["completion_budget_cents"] == 5_000_000
        assert unchanged_case["version"] == current_version + 1
        unchanged_loan = ctx.refresh_loan()
        assert unchanged_loan["committed_amount_cents"] == 28_953_713, (
            "the refused revision applied no delta"
        )
        assert unchanged_loan["undisbursed_holdback_cents"] == 5_000_000


class TestCompletionCeilings:
    def test_the_budget_cap_and_the_spend_cap_each_refuse_by_one_cent(self):
        """6,400,001 breaks the ARV cap and 5,000,001 breaks the approved budget.

        The two ceilings are nested — the budget is bounded by the collateral and the
        spend is bounded by the budget — and the settlement that follows the accepted
        pair still balances the commitment identity to zero. The PRD states: "In both
        cases `budget_cents` may not exceed the floor of 20 percent of the property's
        `arv_cents`, and a larger figure is rejected with
        `ERR_COMPLETION_BUDGET_EXCEEDS_CAP`."

        Design: Corner/errors/the_completion_budget_is_capped_and_the_spend_is_capped_by_the_budget
        """
        ctx, case = _reo_ready_case()
        assert case["status"] == ForeclosureCaseStatus.TAKEOVER_COMPLETE.value
        assert case["completion_budget_cents"] is None
        assert fixtures.read_property(ctx.property_id)["arv_cents"] == 32_000_000

        validate_error(
            _budget_attempt(case["id"], BUDGET_CAP + 1, case["version"]),
            ApiErrorId.COMPLETION_BUDGET_EXCEEDS_CAP.value,
        )
        assert fixtures.read_foreclosure_case(case["id"])["completion_budget_cents"] is None
        assert ctx.refresh_loan()["committed_amount_cents"] == 23_953_713

        funded = fixtures.set_completion_budget(
            case["id"], 5_000_000, case["version"]
        )
        assert funded["completion_budget_cents"] == 5_000_000
        assert funded["status"] == ForeclosureCaseStatus.COMPLETION_FUNDED.value
        loan = ctx.refresh_loan()
        assert loan["committed_amount_cents"] == 28_953_713
        assert loan["undisbursed_holdback_cents"] == 5_000_000
        assert loan["accrued_interest_unpaid_cents"] == 271_074
        assert loan["funded_principal_cents"] == 13_953_713

        fixtures.set_clock(f"{SALE_DATE}T09:00:00Z")
        validate_error(
            _disposition_attempt(case["id"], 18_000_000, 5_000_001),
            ApiErrorId.COMPLETION_SPEND_EXCEEDS_BUDGET.value,
        )
        still_open = fixtures.read_foreclosure_case(case["id"])
        assert still_open["status"] == ForeclosureCaseStatus.COMPLETION_FUNDED.value
        assert still_open["sale_price_cents"] is None

        resolved = validate_success(
            _disposition_attempt(case["id"], 18_000_000, 4_500_000), 200
        )
        assert resolved["status"] == ForeclosureCaseStatus.RESOLVED.value
        assert resolved["completion_advanced_cents"] == 4_500_000
        assert resolved["sale_price_cents"] == 18_000_000
        assert resolved["selling_costs_cents"] == 1_080_000
        assert resolved["net_proceeds_cents"] == 16_920_000
        assert resolved["recovery_cents"] == 16_920_000
        assert resolved["charge_off_cents"] == 2_872_283
        assert resolved["surplus_returned_cents"] == 0

        loan = ctx.refresh_loan()
        assert loan["payment_status"] == LoanPaymentStatus.CHARGED_OFF.value
        assert loan["construction_status"] == LoanConstructionStatus.LENDER_COMPLETE.value
        assert_loan_buckets(
            loan,
            committed_amount_cents=28_953_713,
            funded_principal_cents=0,
            repaid_principal_cents=18_453_713,
            undisbursed_holdback_cents=0,
            decommitted_holdback_cents=10_500_000,
        )
        assert loan["accrued_interest_unpaid_cents"] == 0
        assert loan["fee_balance_cents"] == 0
        assert loan["commitment_balance_check_cents"] == 0
        assert fixtures.read_property(ctx.property_id)["status"] == (
            PropertyStatus.SOLD.value
        )

        entries, _ = validate_paginated(
            api_client.list_ledger_entries(ctx.loan_id, SERVICER)
        )
        tail = [(entry["entry_type"], entry["amount_cents"]) for entry in entries[-2:]]
        assert tail == [
            (LedgerEntryType.REO_SALE_PROCEEDS.value, 16_920_000),
            (LedgerEntryType.CHARGE_OFF.value, 2_872_283),
        ], f"the settlement writes proceeds then the charge-off, got {tail}"
        assert any(
            entry["entry_type"] == LedgerEntryType.COMPLETION_ADVANCE.value
            and entry["amount_cents"] == 4_500_000
            for entry in entries
        ), "the completion advance is its own ledger entry"
