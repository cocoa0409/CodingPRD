"""Closing: the four preconditions, the minted loan and its seeded money buckets."""

from test_helpers import (
    ApiErrorId,
    ApplicationStatus,
    DayCountConvention,
    LedgerEntryType,
    LoanConstructionStatus,
    LoanExitStatus,
    LoanPaymentStatus,
    PropertyStatus,
    api_client,
    assert_loan_axes,
    assert_loan_buckets,
    assert_contractor_payability,
    assert_system_fields,
    factories,
    fixtures,
    validate_error,
    validate_paginated,
    validate_success,
    CREDIT_COMMITTEE,
    LOAN_OFFICER,
    SERVICER,
)

EXPIRED_TRADE = {
    "business_name": "Ortiz Electric",
    "license_number": "LIC-8820",
    "license_expires_on": "2026-08-05",
}
NO_W9_TRADE = {
    "business_name": "Ortiz Electric",
    "license_number": "LIC-8820",
    "license_expires_on": "2027-12-31",
    "w9_on_file": False,
}
TWO_LINES_ONE_TRADE = [
    fixtures.ScopeSpec("ROOF", 2_500_000, 0, "Tear-off and re-deck"),
    fixtures.ScopeSpec("BATH", 2_500_000, 0, "Primary bath gut"),
]


def _two_line_scope_on_second_trade():
    return [
        fixtures.ScopeSpec("ROOF", 2_500_000, 0, "Tear-off and re-deck"),
        fixtures.ScopeSpec("ELECTRICAL", 2_500_000, 1, "Full rewire and panel"),
    ]


class TestClosePrecedence:
    def test_the_application_state_rule_outranks_the_contractor_payability_rule(self):
        """Both rules are broken by one call; the lower priority number answers.

        The application is still `SIZED` and one of its approved lines names a
        contractor whose licence lapsed on 2026-08-05 against a 2026-08-10 clock,
        so both refusals are live — and the state refusal is the one returned. The
        PRD states: "Closing an application that is not `APPROVED` is rejected
        with `ERR_APPLICATION_STATE_INVALID`."

        Design: Difficulty/priority_pair_validation_conflict/close_state_priority_9_beats_contractor_payable_priority_14
        """
        ctx = fixtures.build_sized_application(
            scope=_two_line_scope_on_second_trade(),
            contractor_overrides=[fixtures.CONTRACTOR_ONE, EXPIRED_TRADE],
        )
        lapsed = fixtures.read_contractor(ctx.contractor_id(1))
        assert_contractor_payability(lapsed, license_status="EXPIRED", payable=False)
        assert ctx.application["status"] == ApplicationStatus.SIZED.value

        validate_error(
            api_client.close_application(
                ctx.application_id, factories.close_payload(), SERVICER
            ),
            ApiErrorId.APPLICATION_STATE_INVALID.value,
        )
        assert ctx.refresh_application()["status"] == ApplicationStatus.SIZED.value
        assert fixtures.read_property(ctx.property_id)["status"] == (
            PropertyStatus.UNDER_CONTRACT.value
        )

        fixtures.decide_application(ctx)
        assert ctx.application["status"] == ApplicationStatus.APPROVED.value
        assert ctx.application["approved_loan_amount_cents"] == 22_442_141

        validate_error(
            api_client.close_application(
                ctx.application_id, factories.close_payload(), SERVICER
            ),
            ApiErrorId.CONTRACTOR_NOT_PAYABLE.value,
        )
        assert ctx.refresh_application()["status"] == ApplicationStatus.APPROVED.value
        assert fixtures.read_property(ctx.property_id)["status"] == (
            PropertyStatus.UNDER_CONTRACT.value
        )

    def test_each_of_the_two_close_rules_answers_alone_when_it_is_the_only_breach(self):
        """Isolating each breach shows the pairing above was a genuine conflict.

        A sized application whose trades are all payable still refuses on state,
        and an approved application with a lapsed trade refuses on payability, so
        neither error is simply the endpoint's default answer. The PRD states:
        "every contractor referenced by an `APPROVED` scope line must have
        `payable` reading true, with a lapsed licence or missing W-9 rejected as
        `ERR_CONTRACTOR_NOT_PAYABLE`."

        Design: Difficulty/priority_pair_validation_conflict/close_state_priority_9_beats_contractor_payable_priority_14
        """
        state_only = fixtures.build_sized_application(
            scope=_two_line_scope_on_second_trade()
        )
        assert fixtures.read_contractor(state_only.contractor_id(1))["payable"] is True
        validate_error(
            api_client.close_application(
                state_only.application_id, factories.close_payload(), SERVICER
            ),
            ApiErrorId.APPLICATION_STATE_INVALID.value,
        )

        payability_only = fixtures.build_approved_application(
            clock=None,
            scope=_two_line_scope_on_second_trade(),
            contractor_overrides=[fixtures.CONTRACTOR_ONE, EXPIRED_TRADE],
        )
        assert payability_only.application["status"] == ApplicationStatus.APPROVED.value
        validate_error(
            api_client.close_application(
                payability_only.application_id, factories.close_payload(), SERVICER
            ),
            ApiErrorId.CONTRACTOR_NOT_PAYABLE.value,
        )


class TestNonPayableContractorGate:
    def test_closing_is_blocked_by_a_non_payable_contractor_on_the_scope(self):
        """The gate reaches application to scope line to contractor, two hops out.

        The first application is refused only because its electrical line names a
        trade with no W-9 on file, while a second application whose lines both
        name the payable trade closes on the same clock date. The PRD states: "The
        derived `payable` flag is true only when `license_status` is `ACTIVE`
        **and** `w9_on_file` is true."

        Design: Corner/validations/closing_is_blocked_by_a_non_payable_contractor_on_the_scope
        """
        blocked = fixtures.build_approved_application(
            scope=_two_line_scope_on_second_trade(),
            contractor_overrides=[fixtures.CONTRACTOR_ONE, NO_W9_TRADE],
        )
        unpayable = fixtures.read_contractor(blocked.contractor_id(1))
        assert_contractor_payability(unpayable, license_status="ACTIVE", payable=False)
        assert unpayable["w9_on_file"] is False

        validate_error(
            api_client.close_application(
                blocked.application_id, factories.close_payload(), SERVICER
            ),
            ApiErrorId.CONTRACTOR_NOT_PAYABLE.value,
        )

        second_property = fixtures.register_property(address_line="42 Cholla Way")
        clean = fixtures.open_application(
            blocked.borrower_id, second_property["id"]
        )
        clean_lines = [
            fixtures.add_scope_line(clean["id"], spec, blocked.contractor_id(0))
            for spec in TWO_LINES_ONE_TRADE
        ]
        for spec, line in zip(TWO_LINES_ONE_TRADE, clean_lines):
            fixtures.approve_scope_line(line["id"], spec.cost_cents)
        validate_success(
            api_client.size_application(
                clean["id"], factories.size_payload(), LOAN_OFFICER
            ),
            200,
        )
        validate_success(
            api_client.decide_application(
                clean["id"], factories.decision_payload(), CREDIT_COMMITTEE
            ),
            200,
        )
        loan = validate_success(
            api_client.close_application(
                clean["id"], factories.close_payload(), SERVICER
            ),
            201,
        )
        assert_loan_buckets(
            loan,
            committed_amount_cents=22_442_141,
            funded_principal_cents=16_439_218,
            interest_reserve_balance_cents=1_002_923,
            undisbursed_holdback_cents=5_000_000,
        )
        assert fixtures.read_application(blocked.application_id)["status"] == (
            ApplicationStatus.APPROVED.value
        )


class TestMintedLoan:
    def test_closing_populates_every_computed_money_bucket(self):
        """Nothing about the loan's money is supplied at close; it is all derived.

        The 23,953,713 commitment splits into 13,151,375 of funded principal,
        802,338 of interest reserve and 10,000,000 of holdback, with the other
        three buckets at zero, so the conservation check is exactly 0 on the very
        first write. The PRD states: "The field `commitment_balance_check_cents`
        reports `committed_amount_cents` less the sum of those six buckets, and it
        must read exactly zero after every single write that touches any loan money
        bucket."

        Design: Corner/entities/closing_populates_every_computed_money_bucket
        """
        ctx = fixtures.build_closed_loan()
        loan = ctx.loan
        assert_system_fields(loan, expected_version=1)
        assert loan["application_id"] == ctx.application_id
        assert loan["borrower_id"] == ctx.borrower_id
        assert loan["closing_date"] == "2026-08-10"

        assert_loan_buckets(
            loan,
            committed_amount_cents=23_953_713,
            funded_principal_cents=13_151_375,
            interest_reserve_balance_cents=802_338,
            undisbursed_holdback_cents=10_000_000,
            reserved_release_cents=0,
            repaid_principal_cents=0,
            decommitted_holdback_cents=0,
        )
        assert loan["commitment_balance_check_cents"] == 0
        assert loan["available_rehab_pool_cents"] == 10_000_000
        assert loan["interest_reserve_funded_cents"] == 802_338
        assert loan["accrued_interest_unpaid_cents"] == 0
        assert loan["fee_balance_cents"] == 0

        assert loan["term_months"] == 9
        assert loan["day_count_convention"] == DayCountConvention.PER_DIEM_360.value
        assert loan["note_rate_bps"] == 1150
        assert loan["default_rate_bps"] == 1750, (
            "default_rate_bps is note_rate_bps plus the 600 bps default spread"
        )
        assert loan["maturity_date"] == "2027-05-10", (
            "maturity is the closing date advanced by term_months calendar months"
        )
        assert loan["extension_count"] == 0
        assert loan["extension_months_total"] == 0
        assert loan["last_accrual_through"] is None
        assert loan["delinquent_since"] is None
        assert loan["default_effective_date"] is None

    def test_closing_fires_all_four_declared_side_effects_and_nothing_more(self):
        """The loan, the buckets, one ledger entry and the property cascade — and no more.

        Exactly one `INITIAL_FUNDING` entry is written for the initial funding
        amount rather than one entry per bucket, the property moves to
        `BORROWER_OWNED`, and no accrual period appears until an accrual is
        actually run. The PRD states: "A ledger entry of type `INITIAL_FUNDING` is
        written for the initial funding amount, and the property cascades
        `UNDER_CONTRACT → BORROWER_OWNED`."

        Design: Corner/state_machines/closing_fires_all_four_declared_side_effects_and_nothing_more
        """
        ctx = fixtures.build_origination()
        fixtures.size_application(ctx)
        fixtures.decide_application(ctx)
        assert fixtures.read_property(ctx.property_id)["status"] == (
            PropertyStatus.UNDER_CONTRACT.value
        )

        loan = validate_success(
            api_client.close_application(
                ctx.application_id, factories.close_payload("2026-08-10"), SERVICER
            ),
            201,
        )
        assert ctx.refresh_application()["status"] == ApplicationStatus.CLOSED.value
        assert_loan_axes(
            loan,
            payment_status=LoanPaymentStatus.CURRENT.value,
            construction_status=LoanConstructionStatus.NOT_STARTED.value,
            exit_status=LoanExitStatus.NOT_LISTED.value,
        )
        assert_loan_buckets(
            loan,
            funded_principal_cents=13_151_375,
            interest_reserve_balance_cents=802_338,
            undisbursed_holdback_cents=10_000_000,
        )

        entries, meta = validate_paginated(
            api_client.list_ledger_entries(loan["id"], SERVICER)
        )
        assert meta["total_count"] == 1, (
            f"closing writes exactly one ledger entry, got {meta['total_count']}"
        )
        entry = entries[0]
        assert entry["entry_type"] == LedgerEntryType.INITIAL_FUNDING.value
        assert entry["amount_cents"] == 13_151_375
        assert entry["loan_id"] == loan["id"]
        assert "updated_at" not in entry, "ledger entries are immutable"
        assert "version" not in entry, "ledger entries carry no version"

        _, period_meta = validate_paginated(
            api_client.list_interest_periods(loan["id"], SERVICER)
        )
        assert period_meta["total_count"] == 0, (
            "closing does not create an interest accrual period"
        )

        assert fixtures.read_property(ctx.property_id)["status"] == (
            PropertyStatus.BORROWER_OWNED.value
        )


class TestSecondCloseOnTheSameCollateral:
    def _second_application(self, ctx):
        application = fixtures.open_application(ctx.borrower_id, ctx.property_id)
        lines = [
            fixtures.add_scope_line(
                application["id"], spec, ctx.contractor_id(spec.contractor)
            )
            for spec in fixtures.THREE_LINE_SCOPE
        ]
        for spec, line in zip(fixtures.THREE_LINE_SCOPE, lines):
            fixtures.approve_scope_line(line["id"], spec.cost_cents)
        validate_success(
            api_client.size_application(
                application["id"], factories.size_payload(), LOAN_OFFICER
            ),
            200,
        )
        return validate_success(
            api_client.decide_application(
                application["id"], factories.decision_payload(), CREDIT_COMMITTEE
            ),
            200,
        )

    def test_the_second_close_fails_on_the_peer_propertys_state(self):
        """Two approved applications may share collateral, but only one may close.

        Closing consumes the property's `UNDER_CONTRACT` state, so the second
        close is refused on the property rather than on its own status, which is
        still `APPROVED`. The PRD states: "the property must still be
        `UNDER_CONTRACT`, with any other property status reported as
        `ERR_PROPERTY_STATE_INVALID`".

        Design: Difficulty/cross_entity_state_dependency/second_close_on_the_same_property_is_gated_by_the_property_state
        """
        first = fixtures.build_approved_application(scope=TWO_LINES_ONE_TRADE)
        second = self._second_application(first)
        assert second["property_id"] == first.property_id
        assert second["sized_committed_amount_cents"] == 23_953_713
        assert second["status"] == ApplicationStatus.APPROVED.value

        fixtures.close_application(first)
        assert_loan_buckets(
            first.loan,
            funded_principal_cents=16_439_218,
            interest_reserve_balance_cents=1_002_923,
            undisbursed_holdback_cents=5_000_000,
        )
        assert fixtures.read_property(first.property_id)["status"] == (
            PropertyStatus.BORROWER_OWNED.value
        )

        validate_error(
            api_client.close_application(
                second["id"], factories.close_payload(), SERVICER
            ),
            ApiErrorId.PROPERTY_STATE_INVALID.value,
        )
        stranded = fixtures.read_application(second["id"])
        assert stranded["status"] == ApplicationStatus.APPROVED.value, (
            "the refused close must not move the losing application"
        )
        assert fixtures.read_property(first.property_id)["status"] == (
            PropertyStatus.BORROWER_OWNED.value
        )
        _, meta = validate_paginated(api_client.list_loans(SERVICER))
        assert meta["total_count"] == 1, f"only one loan may exist, got {meta['total_count']}"

    def test_the_same_sponsor_may_still_close_on_different_collateral(self):
        """The block is the property's state, not a limit on the sponsor.

        After the first close the same sponsor closes a third application against
        a different property, while the stranded application on the consumed
        collateral is still refused. The PRD states: "A new property's `status`
        begins at `UNDER_CONTRACT` with `valuation_revision_count` at 0, and the
        status track runs `UNDER_CONTRACT → BORROWER_OWNED` at closing".

        Design: Difficulty/cross_entity_state_dependency/second_close_on_the_same_property_is_gated_by_the_property_state
        """
        first = fixtures.build_approved_application(scope=TWO_LINES_ONE_TRADE)
        stranded = self._second_application(first)
        fixtures.close_application(first)

        other_property = fixtures.register_property(address_line="42 Cholla Way")
        elsewhere = fixtures.open_application(first.borrower_id, other_property["id"])
        elsewhere_lines = [
            fixtures.add_scope_line(elsewhere["id"], spec, first.contractor_id(0))
            for spec in TWO_LINES_ONE_TRADE
        ]
        for spec, line in zip(TWO_LINES_ONE_TRADE, elsewhere_lines):
            fixtures.approve_scope_line(line["id"], spec.cost_cents)
        validate_success(
            api_client.size_application(
                elsewhere["id"], factories.size_payload(), LOAN_OFFICER
            ),
            200,
        )
        validate_success(
            api_client.decide_application(
                elsewhere["id"], factories.decision_payload(), CREDIT_COMMITTEE
            ),
            200,
        )
        second_loan = validate_success(
            api_client.close_application(
                elsewhere["id"], factories.close_payload(), SERVICER
            ),
            201,
        )
        assert second_loan["borrower_id"] == first.borrower_id
        assert second_loan["committed_amount_cents"] == 22_442_141
        assert fixtures.read_property(other_property["id"])["status"] == (
            PropertyStatus.BORROWER_OWNED.value
        )

        validate_error(
            api_client.close_application(
                stranded["id"], factories.close_payload(), SERVICER
            ),
            ApiErrorId.PROPERTY_STATE_INVALID.value,
        )
        assert fixtures.read_application(stranded["id"])["status"] == (
            ApplicationStatus.APPROVED.value
        )
        _, meta = validate_paginated(api_client.list_loans(SERVICER))
        assert meta["total_count"] == 2, (
            f"two loans on two properties may coexist, got {meta['total_count']}"
        )
