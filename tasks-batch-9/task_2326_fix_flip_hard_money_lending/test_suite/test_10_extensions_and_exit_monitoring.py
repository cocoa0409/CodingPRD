"""Extensions, the exit-watch gate and the milestone log the gate is projected from."""

from test_helpers import (
    ApiErrorId,
    LedgerEntryType,
    LoanExitStatus,
    LoanPaymentStatus,
    MilestoneType,
    api_client,
    assert_append_only_record,
    assert_exit_monitoring,
    factories,
    fixtures,
    validate_error,
    validate_paginated,
    validate_success,
    SERVICER,
)

CLOSING_DATE = "2026-08-10"
FIRST_FEE = 131_514
SECOND_FEE = 263_028


def _extension_limit_refusal(loan_id, months=1):
    return validate_error(
        api_client.create_extension(
            loan_id, factories.extension_payload(months), SERVICER
        ),
        ApiErrorId.EXTENSION_LIMIT_REACHED.value,
    )


def _extension_attempt(loan_id, months=1):
    return api_client.create_extension(
        loan_id, factories.extension_payload(months), SERVICER
    )


def _listed_loan(listing_date, clock=None):
    """A closed loan carrying one `LISTED` milestone and no money movement since."""
    ctx = fixtures.build_closed_loan()
    fixtures.set_clock(f"{listing_date}T09:00:00Z")
    fixtures.file_milestone(ctx.loan_id, MilestoneType.LISTED.value, listing_date)
    if clock is not None:
        fixtures.set_clock(clock)
    return ctx


class TestExitWatchGatesTheExtension:
    def test_the_same_grant_flips_on_the_watch_flag_the_clock_produces(self):
        """90 days grants, 91 days refuses, and only the milestone log changed in between.

        No write touches the loan between the accepted grant and the refused one —
        the clock crossing 90 days is what turns the flag on, and the flag is what
        closes the endpoint. The PRD states: "An exit-watched loan may not be
        extended: a grant attempted while `exit_watch_flag` is true is rejected with
        `ERR_EXTENSION_BLOCKED_BY_EXIT_WATCH`, which forces the sponsor to reprice
        the listing before buying more time."

        Design: Difficulty/cross_entity_state_dependency/extension_gate_reads_exit_watch_flag_derived_from_child_milestones
        """
        ctx = _listed_loan("2026-09-01", clock="2026-11-30T09:00:00Z")
        at_ninety = fixtures.read_loan(ctx.loan_id)
        assert_exit_monitoring(at_ninety, days_on_market=90, exit_watch_flag=False)
        assert at_ninety["exit_status"] == LoanExitStatus.LISTED.value

        granted = fixtures.extend(ctx.loan_id, 1)
        assert granted["fee_balance_cents"] == FIRST_FEE
        assert granted["note_rate_bps"] == 1200
        assert granted["default_rate_bps"] == 1800
        assert granted["extension_count"] == 1
        assert granted["extension_months_total"] == 1
        assert granted["maturity_date"] == "2027-06-10"
        assert granted["committed_amount_cents"] == 23_953_713
        assert granted["commitment_balance_check_cents"] == 0

        fixtures.set_clock("2026-12-01T09:00:00Z")
        at_ninety_one = fixtures.read_loan(ctx.loan_id)
        assert_exit_monitoring(at_ninety_one, days_on_market=91, exit_watch_flag=True)

        validate_error(
            _extension_attempt(ctx.loan_id),
            ApiErrorId.EXTENSION_BLOCKED_BY_EXIT_WATCH.value,
        )
        blocked = fixtures.read_loan(ctx.loan_id)
        assert blocked["extension_count"] == 1, "the refused grant must not count"
        assert blocked["fee_balance_cents"] == FIRST_FEE
        assert blocked["note_rate_bps"] == 1200
        assert blocked["maturity_date"] == "2027-06-10"
        assert blocked["commitment_balance_check_cents"] == 0

    def test_a_reprice_clears_the_flag_without_resetting_the_day_count(self):
        """The reprice reopens the endpoint while `days_on_market` stays at 91.

        Filing a `PRICE_REDUCED` milestone dated on or after the governing listing
        clears the watch flag, but it is not a delisting, so the counter keeps
        running from the 2026-09-01 listing and the very next grant is admitted. The
        PRD states: "A stale listing that has never been repriced is the exit-watch
        signal; a single price reduction dated on or after the governing listing
        clears the flag permanently, while a price reduction dated *before* the
        governing listing does not clear it."

        Design: Difficulty/cross_entity_state_dependency/extension_gate_reads_exit_watch_flag_derived_from_child_milestones
        """
        ctx = _listed_loan("2026-09-01", clock="2026-11-30T09:00:00Z")
        fixtures.extend(ctx.loan_id, 1)
        fixtures.set_clock("2026-12-01T09:00:00Z")
        validate_error(
            _extension_attempt(ctx.loan_id),
            ApiErrorId.EXTENSION_BLOCKED_BY_EXIT_WATCH.value,
        )

        fixtures.file_milestone(
            ctx.loan_id,
            MilestoneType.PRICE_REDUCED.value,
            "2026-12-01",
            listing_price_cents=30_500_000,
        )
        repriced = fixtures.read_loan(ctx.loan_id)
        assert_exit_monitoring(repriced, days_on_market=91, exit_watch_flag=False)
        assert repriced["exit_status"] == LoanExitStatus.LISTED.value, (
            "a price reduction maps to LISTED, so the axis does not move"
        )

        second = fixtures.extend(ctx.loan_id, 1)
        assert second["fee_balance_cents"] == SECOND_FEE, (
            "the second fee is charged on the unchanged principal, not on the first fee"
        )
        assert second["note_rate_bps"] == 1250
        assert second["default_rate_bps"] == 1850
        assert second["extension_count"] == 2
        assert second["extension_months_total"] == 2
        assert second["maturity_date"] == "2027-07-10"
        assert second["committed_amount_cents"] == 23_953_713
        assert second["commitment_balance_check_cents"] == 0

        _extension_limit_refusal(ctx.loan_id)
        exhausted = fixtures.read_loan(ctx.loan_id)
        assert exhausted["extension_count"] == 2
        assert exhausted["exit_watch_flag"] is False, (
            "the fourth attempt is refused by the count, not by the watch flag"
        )


class TestExtensionCeiling:
    def test_the_second_grant_lands_on_the_limit_and_the_third_is_refused(self):
        """Two grants take the loan to the ceiling; the third changes nothing at all.

        Each grant charges one percent of the unchanged 13,151,375 principal, so the
        fee balance doubles rather than compounding, and the refused third grant
        leaves the fee, the rate, the count and the maturity date exactly where the
        second grant left them. The PRD states: "**Extension repricing** computes a
        fee as `funded_principal_cents` multiplied by 100 basis points — one
        percent — divided by 10000, multiplied by the granted `months`, rounded half
        up to whole cents; so a one-month extension costs one percent of outstanding
        principal and a three-month extension costs three percent."

        Design: Corner/calculations/the_third_extension_is_refused_at_the_declared_maximum
        """
        ctx = fixtures.build_closed_loan()
        first = fixtures.extend(ctx.loan_id, 1)
        assert first["extension_count"] == 1
        assert first["fee_balance_cents"] == FIRST_FEE
        assert first["maturity_date"] == "2027-06-10"
        assert first["note_rate_bps"] == 1200

        second = fixtures.extend(ctx.loan_id, 1)
        assert second["extension_count"] == 2
        assert second["extension_months_total"] == 2
        assert second["fee_balance_cents"] == SECOND_FEE
        assert second["maturity_date"] == "2027-07-10"
        assert second["note_rate_bps"] == 1250
        assert second["default_rate_bps"] == 1850
        assert second["funded_principal_cents"] == 13_151_375, (
            "the fee is revenue and never joins principal"
        )
        assert second["commitment_balance_check_cents"] == 0

        _extension_limit_refusal(ctx.loan_id)
        after = fixtures.read_loan(ctx.loan_id)
        assert after["extension_count"] == 2
        assert after["extension_months_total"] == 2
        assert after["fee_balance_cents"] == SECOND_FEE
        assert after["maturity_date"] == "2027-07-10"
        assert after["note_rate_bps"] == 1250

        entries, _ = validate_paginated(
            api_client.list_ledger_entries(
                ctx.loan_id, SERVICER, {"entry_type": LedgerEntryType.EXTENSION_FEE.value}
            )
        )
        assert len(entries) == 2, f"two fee entries expected, got {len(entries)}"
        assert [entry["amount_cents"] for entry in entries] == [FIRST_FEE, FIRST_FEE]


class TestMilestoneProjection:
    def test_the_delisting_hands_the_governing_listing_to_the_later_relisting(self):
        """Four rows replay into 91 days on market and a watch flag the August reprice cannot clear.

        The delisting zeroes the count and disqualifies the first listing, so the
        governing listing becomes the 2026-09-05 one and the price reduction filed
        back in August is dated before it and therefore powerless. The PRD states:
        "The *governing* listing is the loan's `LISTED` milestone with the greatest
        `effective_date`, tie-broken by the greatest `created_at`, whose
        `effective_date` is later than the `effective_date` of the most recent
        `DELISTED` milestone if any exists; when no such milestone exists the
        governing listing is null."

        Design: Corner/calculations/exit_status_and_days_on_market_replay_the_milestone_history
        """
        ctx = fixtures.build_closed_loan()
        fixtures.set_clock("2026-08-20T09:00:00Z")
        first = fixtures.file_milestone(
            ctx.loan_id, MilestoneType.LISTED.value, "2026-08-20"
        )
        assert first["derived_exit_status"] == LoanExitStatus.LISTED.value
        loan = fixtures.read_loan(ctx.loan_id)
        assert loan["exit_status"] == LoanExitStatus.LISTED.value
        assert_exit_monitoring(loan, days_on_market=0, exit_watch_flag=False)

        fixtures.set_clock("2026-08-25T09:00:00Z")
        fixtures.file_milestone(
            ctx.loan_id,
            MilestoneType.PRICE_REDUCED.value,
            "2026-08-25",
            listing_price_cents=31_000_000,
        )
        loan = fixtures.read_loan(ctx.loan_id)
        assert_exit_monitoring(loan, days_on_market=5, exit_watch_flag=False)
        assert loan["exit_status"] == LoanExitStatus.LISTED.value

        fixtures.set_clock("2026-09-01T09:00:00Z")
        delisting = fixtures.file_milestone(
            ctx.loan_id, MilestoneType.DELISTED.value, "2026-09-01"
        )
        assert delisting["derived_exit_status"] == LoanExitStatus.NOT_LISTED.value
        loan = fixtures.read_loan(ctx.loan_id)
        assert loan["exit_status"] == LoanExitStatus.NOT_LISTED.value
        assert_exit_monitoring(loan, days_on_market=0, exit_watch_flag=False)

        fixtures.set_clock("2026-09-05T09:00:00Z")
        fixtures.file_milestone(
            ctx.loan_id,
            MilestoneType.LISTED.value,
            "2026-09-05",
            listing_price_cents=30_000_000,
        )
        loan = fixtures.read_loan(ctx.loan_id)
        assert loan["exit_status"] == LoanExitStatus.LISTED.value
        assert_exit_monitoring(loan, days_on_market=0, exit_watch_flag=False)

        fixtures.set_clock("2026-12-05T09:00:00Z")
        loan = fixtures.read_loan(ctx.loan_id)
        assert_exit_monitoring(loan, days_on_market=91, exit_watch_flag=True)
        assert loan["payment_status"] == LoanPaymentStatus.CURRENT.value
        assert loan["funded_principal_cents"] == 13_151_375, (
            "the milestone log never touches money"
        )

        validate_error(
            api_client.create_exit_milestone(
                ctx.loan_id,
                factories.milestone_payload(
                    MilestoneType.PRICE_REDUCED.value,
                    "2026-09-01",
                    listing_price_cents=29_000_000,
                ),
                SERVICER,
            ),
            ApiErrorId.MILESTONE_BACKDATED.value,
        )
        rows, meta = validate_paginated(
            api_client.list_exit_milestones(ctx.loan_id, SERVICER)
        )
        assert meta["total_count"] == 4, (
            f"the backdated attempt writes no row, got {meta['total_count']}"
        )
        assert [row["milestone_type"] for row in rows] == [
            MilestoneType.LISTED.value,
            MilestoneType.PRICE_REDUCED.value,
            MilestoneType.DELISTED.value,
            MilestoneType.LISTED.value,
        ]
        assert fixtures.read_loan(ctx.loan_id)["exit_watch_flag"] is True


class TestAppendOnlyJournals:
    def test_the_three_journals_expose_only_an_id_and_a_creation_stamp(self):
        """A second milestone is a new row, not an edit of the first.

        Milestones, ledger entries and accrual periods all come back without a
        version or an update stamp, and the collection endpoints answer with an empty
        array rather than a 404 when nothing has been written yet. The PRD states:
        "Three record types are append-only journals and therefore carry only `id`
        and `created_at` — both `updated_at` and `version` are absent from ledger
        entries, interest accrual periods and exit milestones."

        Design: Corner/entities/immutable_child_rows_carry_no_version_and_no_update_path
        """
        ctx = fixtures.build_closed_loan()
        fixtures.set_clock("2026-09-15T09:00:00Z")
        first = fixtures.file_milestone(
            ctx.loan_id, MilestoneType.LISTED.value, "2026-09-01"
        )
        assert_append_only_record(first)
        second = fixtures.file_milestone(
            ctx.loan_id,
            MilestoneType.PRICE_REDUCED.value,
            "2026-09-10",
            listing_price_cents=31_000_000,
        )
        assert_append_only_record(second)
        assert second["id"] != first["id"], (
            "the reprice is a new row and must not overwrite the listing"
        )

        rows, meta = validate_paginated(
            api_client.list_exit_milestones(ctx.loan_id, SERVICER)
        )
        assert meta["total_count"] == 2
        assert rows[0]["milestone_type"] == MilestoneType.LISTED.value
        assert rows[0]["id"] == first["id"]

        periods, period_meta = validate_paginated(
            api_client.list_interest_periods(ctx.loan_id, SERVICER)
        )
        assert period_meta["total_count"] == 0, (
            "no accrual has been filed, and the empty collection is still a 200"
        )
        assert periods == []

        entries, entry_meta = validate_paginated(
            api_client.list_ledger_entries(ctx.loan_id, SERVICER)
        )
        assert entry_meta["total_count"] == 1
        assert entries[0]["entry_type"] == LedgerEntryType.INITIAL_FUNDING.value
        assert entries[0]["amount_cents"] == 13_151_375
        assert entries[0]["effective_date"] == CLOSING_DATE
        assert_append_only_record(entries[0])

        assert fixtures.read_loan(ctx.loan_id)["exit_status"] == (
            LoanExitStatus.LISTED.value
        ), "immutable rows still drive the parent projection"

        accrual = validate_success(
            api_client.create_interest_accrual(
                ctx.loan_id,
                factories.accrual_payload(CLOSING_DATE, "2026-09-09"),
                SERVICER,
            ),
            201,
        )
        assert_append_only_record(accrual)
