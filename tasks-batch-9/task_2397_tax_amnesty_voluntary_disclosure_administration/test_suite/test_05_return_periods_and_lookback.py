"""The period gauntlet a disclosure return must survive before it can be filed.

PRD §3.5 stacks six period rules on top of each other and §2.10 fixes the
interval conventions they use, so this module works the boundaries: closed
return periods, half-open term windows, the lookback bounds, the minimum
liability floor and the non-filer requirement.
"""

from test_helpers import (
    ADMIN_HEADERS,
    CANONICAL_GROSS_INTEREST_CENTS,
    CANONICAL_GROSS_LIABILITY_CENTS,
    CANONICAL_GROSS_PENALTY_CENTS,
    CANONICAL_RETURN_PERIOD_END,
    CANONICAL_RETURN_PERIOD_START,
    CANONICAL_TOTAL_DUE_CENTS,
    CANONICAL_WAIVED_AMOUNT_CENTS,
    ApiErrorId,
    assert_fields,
    assert_list_total,
    disclosure_return_payload,
    draft_return,
    file_return,
    read_agreement,
    read_compliance_behavior,
    read_return,
    read_taxpayer,
    setup_executed_agreement,
    validate_error,
    validate_success,
)


class TestLookbackAndOverlapPrecedence:
    """A period can break two rules at once; the earlier one answers."""

    def test_a_period_starting_before_the_lookback_reports_the_lookback_rule(
        self, api
    ):
        """The candidate both escapes the lookback and overlaps a sibling.

        PRD §3.5: "The period must lie inside the agreement's inclusive lookback
        window and inside the half-open eligible window of the matching term,
        per the conventions of §2.10, failing with `ERR_PERIOD_OUTSIDE_LOOKBACK`
        and `ERR_PERIOD_OUTSIDE_ELIGIBLE_WINDOW` respectively. It must not
        overlap another non-`VOIDED` return of the same agreement and tax type,
        failing with `ERR_RETURN_PERIOD_OVERLAP`."

        PRD §2.6: "When more than one rule would reject a request, the rules are
        evaluated in strictly ascending precedence order and the **first**
        violation decides the response."

        Design: Difficulty/priority_pair_validation_conflict/lookback_window_check_precedes_return_period_overlap_check
        """
        ctx = setup_executed_agreement(
            api,
            taxpayer_overrides={
                "legal_name": "Salt Marsh Seafood Co",
                "tin_last4": "9931",
            },
        )
        existing = draft_return(
            api,
            ctx,
            period_start_date="2023-10-01",
            period_end_date="2023-12-31",
            original_due_date="2024-01-31",
            reported_tax_cents=500000,
        )

        response = api.create_return(
            ctx["agreement"]["id"],
            disclosure_return_payload(
                period_start_date="2023-06-01",
                period_end_date="2023-12-31",
                original_due_date="2024-01-31",
                reported_tax_cents=500000,
            ),
            ctx["taxpayer_headers"],
        )
        validate_error(response, ApiErrorId.PERIOD_OUTSIDE_LOOKBACK)
        assert response.json()["data"]["error_id"] != ApiErrorId.RETURN_PERIOD_OVERLAP

        assert_list_total(
            api.list_agreement_returns(
                ctx["agreement"]["id"], ADMIN_HEADERS, {"limit": 100}
            ),
            1,
        )
        assert_fields(read_return(api, existing["id"]), status="DRAFT")

    def test_a_period_inside_the_lookback_reports_the_overlap_rule(self, api):
        """Once the lookback holds, the overlap rule is the one left standing.

        PRD §3.5: "It must not overlap another non-`VOIDED` return of the same
        agreement and tax type, failing with `ERR_RETURN_PERIOD_OVERLAP`."

        Design: Difficulty/priority_pair_validation_conflict/lookback_window_check_precedes_return_period_overlap_check
        """
        ctx = setup_executed_agreement(
            api,
            taxpayer_overrides={
                "legal_name": "Salt Marsh Seafood Co",
                "tin_last4": "9931",
            },
        )
        existing = draft_return(
            api,
            ctx,
            period_start_date="2023-10-01",
            period_end_date="2023-12-31",
            original_due_date="2024-01-31",
            reported_tax_cents=500000,
        )

        validate_error(
            api.create_return(
                ctx["agreement"]["id"],
                disclosure_return_payload(
                    period_start_date="2023-12-01",
                    period_end_date="2024-02-29",
                    original_due_date="2024-03-31",
                    reported_tax_cents=500000,
                ),
                ctx["taxpayer_headers"],
            ),
            ApiErrorId.RETURN_PERIOD_OVERLAP,
        )
        assert_list_total(
            api.list_agreement_returns(
                ctx["agreement"]["id"], ADMIN_HEADERS, {"limit": 100}
            ),
            1,
        )
        assert_fields(read_return(api, existing["id"]), status="DRAFT")


class TestReturnPeriodIntervals:
    """A return period is a closed interval, so its endpoints belong to it."""

    def test_a_period_starting_on_an_existing_end_date_collides(self, api):
        """Both bounds are inclusive, so a shared endpoint is a real overlap.

        PRD §2.10: "A `DisclosureReturn` declares a **closed** period: both
        `period_start_date` and `period_end_date` are inclusive. Two returns of
        the same agreement and tax type whose periods merely touch — a new
        `period_start_date` equal to an existing `period_end_date` — **do**
        overlap and the second is refused"

        Design: Difficulty/resource_temporal_overlap/return_periods_are_closed_intervals_so_touching_endpoints_collide
        """
        ctx = setup_executed_agreement(
            api,
            taxpayer_overrides={
                "legal_name": "Fern Hollow Bakery LLC",
                "tin_last4": "7028",
            },
        )
        first = draft_return(api, ctx, reported_tax_cents=300000)

        validate_error(
            api.create_return(
                ctx["agreement"]["id"],
                disclosure_return_payload(
                    period_start_date="2025-03-31",
                    period_end_date="2025-06-30",
                    reported_tax_cents=300000,
                ),
                ctx["taxpayer_headers"],
            ),
            ApiErrorId.RETURN_PERIOD_OVERLAP,
        )
        assert_fields(read_return(api, first["id"]), status="DRAFT")
        assert_list_total(
            api.list_agreement_returns(
                ctx["agreement"]["id"], ADMIN_HEADERS, {"limit": 100}
            ),
            1,
        )

    def test_a_period_starting_the_day_after_is_merely_adjacent(self, api):
        """Adjacency is not overlap, so the next quarter is accepted.

        PRD §2.10: "adjacency, where the new `period_start_date` is the day
        after an existing `period_end_date`, does not overlap and is accepted."

        Design: Difficulty/resource_temporal_overlap/return_periods_are_closed_intervals_so_touching_endpoints_collide
        """
        ctx = setup_executed_agreement(
            api,
            taxpayer_overrides={
                "legal_name": "Fern Hollow Bakery LLC",
                "tin_last4": "7028",
            },
        )
        first = draft_return(api, ctx, reported_tax_cents=300000)

        second = draft_return(
            api,
            ctx,
            period_start_date="2025-04-01",
            period_end_date="2025-06-30",
            reported_tax_cents=300000,
        )
        assert_fields(second, period_start_date="2025-04-01", status="DRAFT")
        assert_fields(read_return(api, first["id"]), status="DRAFT")
        assert_list_total(
            api.list_agreement_returns(
                ctx["agreement"]["id"], ADMIN_HEADERS, {"limit": 100}
            ),
            2,
        )


class TestTermFloorsAndFlags:
    """The matching tax type term contributes two of the period rules."""

    def test_the_minimum_liability_floor_is_inclusive(self, api):
        """One cent short is refused; the floor itself is accepted.

        PRD §3.5: "And `reported_tax_cents` must be at least the term's
        `min_liability_cents`, otherwise `ERR_BELOW_MINIMUM_LIABILITY`."

        PRD §3.5: "An optional `is_nonfiler_period` flag, false by default,
        marks a period for which no return was ever filed."

        Design: Corner/Table 4 Validations/minimum_liability_is_inclusive_at_the_term_floor
        """
        ctx = setup_executed_agreement(
            api,
            taxpayer_overrides={
                "legal_name": "Ironwood Bay Marina LLC",
                "tin_last4": "4127",
            },
        )

        validate_error(
            api.create_return(
                ctx["agreement"]["id"],
                disclosure_return_payload(reported_tax_cents=49999),
                ctx["taxpayer_headers"],
            ),
            ApiErrorId.BELOW_MINIMUM_LIABILITY,
        )

        accepted = draft_return(api, ctx, reported_tax_cents=50000)
        assert_fields(
            accepted,
            reported_tax_cents=50000,
            status="DRAFT",
            is_nonfiler_period=False,
        )
        assert_list_total(
            api.list_agreement_returns(
                ctx["agreement"]["id"], ADMIN_HEADERS, {"limit": 100}
            ),
            1,
        )

    def test_a_nonfiler_only_term_admits_only_flagged_periods(self, api):
        """The flag is mandatory here, and filing it costs the taxpayer points.

        PRD §3.5: "When the matching term sets `requires_prior_nonfiler`, only a
        return with `is_nonfiler_period` true is accepted, otherwise
        `ERR_NONFILER_PERIOD_REQUIRED`."

        PRD §3.5: "A non-filer period adds a further 5 percentage points on top
        of the tier rate, and the sum is stored in `penalty_rate_applied`."

        PRD §3.5: "when the filed return's `is_nonfiler_period` is true, the
        taxpayer's `nonfiler_period_count` and `compliance_behavior_score` are
        both recomputed, since a newly surfaced unfiled period costs the
        taxpayer 5 points of historical score."

        PRD §3.2: "If the taxpayer holds at least one such agreement, a further
        18 points of participation credit are added."

        Design: Corner/Table 4 Validations/nonfiler_only_term_requires_the_nonfiler_flag
        """
        ctx = setup_executed_agreement(
            api,
            term_overrides={
                "tax_type": "CORPORATE_INCOME",
                "requires_prior_nonfiler": True,
            },
            taxpayer_overrides={
                "legal_name": "Halden Works Inc",
                "tin_last4": "5560",
            },
            tax_types=["CORPORATE_INCOME"],
        )

        validate_error(
            api.create_return(
                ctx["agreement"]["id"],
                disclosure_return_payload(tax_type="CORPORATE_INCOME"),
                ctx["taxpayer_headers"],
            ),
            ApiErrorId.NONFILER_PERIOD_REQUIRED,
        )

        drafted = draft_return(
            api, ctx, tax_type="CORPORATE_INCOME", is_nonfiler_period=True
        )
        filed = file_return(api, ctx, drafted["id"])
        assert_fields(
            filed,
            penalty_rate_applied=0.30,
            gross_penalty_cents=300000,
            gross_interest_cents=CANONICAL_GROSS_INTEREST_CENTS,
            waived_penalty_cents=300000,
            waived_interest_cents=50000,
            balance_due_cents=CANONICAL_TOTAL_DUE_CENTS,
        )

        assert_fields(
            read_taxpayer(api, ctx["taxpayer"]["id"]),
            nonfiler_period_count=1,
            compliance_behavior_score=95,
        )
        assert_fields(
            read_compliance_behavior(api, ctx["taxpayer"]["id"]),
            nonfiler_period_count=1,
            forgiven_nonfiler_period_count=1,
            historical_score=95,
            program_adjusted_score=100,
        )

    def test_the_eligible_term_window_excludes_its_own_end_date(self, api):
        """The last eligible period ends before the term's exclusive end.

        PRD §2.10: "A `ProgramTaxTypeTerm` publishes a **half-open** eligible
        window: `eligible_period_start` is inclusive and `eligible_period_end`
        is exclusive."

        PRD §3.5: "The period must lie inside the agreement's inclusive lookback
        window and inside the half-open eligible window of the matching term,
        per the conventions of §2.10, failing with `ERR_PERIOD_OUTSIDE_LOOKBACK`
        and `ERR_PERIOD_OUTSIDE_ELIGIBLE_WINDOW` respectively."

        Design: Corner/Table 4 Validations/eligible_term_window_is_half_open_at_its_end_date
        """
        ctx = setup_executed_agreement(
            api,
            taxpayer_overrides={
                "legal_name": "Saltmarsh Seafood Co",
                "tin_last4": "6208",
            },
            lookback_end_date="2026-08-31",
        )

        inside = draft_return(
            api,
            ctx,
            period_start_date="2026-06-01",
            period_end_date="2026-06-30",
            original_due_date="2026-07-20",
            reported_tax_cents=400000,
        )
        assert_fields(inside, period_end_date="2026-06-30")

        validate_error(
            api.create_return(
                ctx["agreement"]["id"],
                disclosure_return_payload(
                    period_start_date="2026-07-01",
                    period_end_date="2026-07-31",
                    original_due_date="2026-08-20",
                    reported_tax_cents=400000,
                ),
                ctx["taxpayer_headers"],
            ),
            ApiErrorId.PERIOD_OUTSIDE_ELIGIBLE_WINDOW,
        )
        assert_list_total(
            api.list_agreement_returns(
                ctx["agreement"]["id"], ADMIN_HEADERS, {"limit": 100}
            ),
            1,
        )


class TestFilingIsOnceOnly:
    """Filing consumes the draft, so the second attempt has nothing to file."""

    def test_the_second_filing_attempt_is_refused(self, api):
        """`DRAFT` is the only state that admits filing.

        PRD §3.5: "Filing requires the return to be `DRAFT`, the agreement to be
        `EXECUTED`, the program to be `OPEN` and the current instant strictly
        before `window_close_at`."

        PRD §2.6: "A `DisclosureReturn` must be `DRAFT` to be filed and `FILED`
        to be assessed — otherwise `ERR_RETURN_NOT_DRAFT` or
        `ERR_RETURN_NOT_FILED` (409)."

        Design: Corner/Table 2 State Machines/filing_the_same_return_twice_is_rejected_on_the_second_attempt
        """
        ctx = setup_executed_agreement(
            api,
            taxpayer_overrides={
                "legal_name": "Rowan Gate Cabinetry LLC",
                "tin_last4": "2210",
            },
        )
        drafted = draft_return(api, ctx)

        filed = validate_success(
            api.file_return(drafted["id"], ctx["taxpayer_headers"])
        )
        assert_fields(
            filed,
            status="FILED",
            period_start_date=CANONICAL_RETURN_PERIOD_START,
            period_end_date=CANONICAL_RETURN_PERIOD_END,
            gross_penalty_cents=CANONICAL_GROSS_PENALTY_CENTS,
            gross_interest_cents=CANONICAL_GROSS_INTEREST_CENTS,
        )

        validate_error(
            api.file_return(drafted["id"], ctx["taxpayer_headers"]),
            ApiErrorId.RETURN_NOT_DRAFT,
        )

        assert_fields(
            read_agreement(api, ctx["agreement"]["id"]),
            gross_liability_cents=CANONICAL_GROSS_LIABILITY_CENTS,
            waived_amount_cents=CANONICAL_WAIVED_AMOUNT_CENTS,
            total_due_cents=CANONICAL_TOTAL_DUE_CENTS,
        )
