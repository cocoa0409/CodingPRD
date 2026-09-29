"""Operating months, the conversion tests, and the audited cost certification.

The operating series is append-only and contiguous, and only its first entry
carries a side effect. Conversion then reads a window of that series through one
of two variants, and the cost certification runs the second and binding answer to
the fifty-percent test — the one that can take the credit trigger away again.
"""

from test_helpers import (
    COMPLIANCE_OFFICER,
    SECOND_ALLOCATION_OFFICER_USER_ID,
    TRUSTEE,
    ApiErrorId,
    assert_fields,
    assert_nulls,
    constants,
    factories,
    fixtures,
    validate_error,
    validate_success,
)


class TestTheOperatingSeries:
    """Append-only, contiguous from one, and a milestone on the first entry alone."""

    def test_the_first_operating_month_places_the_development_in_service_and_the_second_does_not_restamp_it(
        self, api
    ):
        """Two months recorded and then a replay of the first one.

        The placed-in-service side effect belongs to the first recorded month only, so
        the second month appends to the series and moves the issue's version without
        touching the milestone date. That date is read from the logical clock at the
        moment the month is recorded — not from the closing date and not from the
        funding date — and nothing in this chain moves the clock. Replaying month one
        then breaks contiguity rather than replacing the entry.

        PRD: "When the issue's `operating_months` was empty immediately beforehand, recording that month moves the development `UNDER_CONSTRUCTION` → `PLACED_IN_SERVICE` and stamps `placed_in_service_date` from the logical clock at the moment the month is recorded. Later months change no development state."
        PRD: "The series is append-only, is held on the issue as `operating_months` ordered by `month_index` ascending, and must stay contiguous from 1: the supplied `month_index` must be exactly one more than the number of months already recorded. A repeat of an index already present, or an index that is not exactly one past the last, is `ERR_DUPLICATE_OPERATING_MONTH`. Each recorded month increments the issue's `version` by 1."

        Design: Corner/state_machines/first_operating_month_places_the_project_in_service_and_a_second_month_does_not_restamp_it
        """
        deal = fixtures.setup_funded_draw(api)
        assert_fields(
            deal.project, "project", development_status="UNDER_CONSTRUCTION"
        )
        assert_nulls(deal.project, ("placed_in_service_date",), "project")

        after_first = fixtures.record_month(api, deal, 1)
        in_service = fixtures.read_project(api, deal)
        assert_fields(in_service, "project", development_status="PLACED_IN_SERVICE")
        assert in_service["placed_in_service_date"].startswith("2026-08-01T00:00:00"), (
            "the milestone is stamped from the logical clock, got {0}".format(
                in_service["placed_in_service_date"]
            )
        )

        after_second = fixtures.record_month(api, deal, 2)
        assert [month["month_index"] for month in after_second["operating_months"]] == [
            1,
            2,
        ], "the series appends in month_index order"
        assert after_second["version"] == after_first["version"] + 1, (
            "each recorded month increments the issue version by exactly one"
        )

        still_in_service = fixtures.read_project(api, deal)
        assert_fields(
            still_in_service, "project", development_status="PLACED_IN_SERVICE"
        )
        assert still_in_service["placed_in_service_date"] == in_service[
            "placed_in_service_date"
        ], "a later month must not restamp the placed-in-service date"

        validate_error(
            api.record_operating_month(
                deal.bond_issue_id,
                deal.developer_headers,
                **factories.operating_month_payload(1)
            ),
            ApiErrorId.ERR_DUPLICATE_OPERATING_MONTH,
            409,
        )

        issue = fixtures.read_bond_issue(api, deal)
        assert len(issue["operating_months"]) == 2, (
            "the refused replay must not append a third entry"
        )
        assert_fields(issue, "bond_issue", status="ISSUED")
        assert_nulls(issue, ("dscr_bps", "min_occupancy_bps"), "bond_issue")

    def test_conversion_requires_the_whole_window_before_any_ratio_is_computed(self, api):
        """Both variants refused on two months, then the third month converts under T3.

        With two months recorded, `T3` is one month short and `T12` is ten months
        short, and the history check sits above both ratio checks — so the answer is
        the history error even though the coverage those two months imply would pass.
        The third month completes the trailing quarter: coverage annualizes to exactly
        12,000 basis points, the weakest month is fully occupied at 10,000, and the
        conversion unrolls the three-level cascade that stamps both covenant end dates
        onto the agreement and mirrors them onto the development.

        PRD: "If fewer operating months have been recorded than the requested window needs — fewer than three for `T3`, fewer than twelve for `T12` — the attempt is `ERR_INSUFFICIENT_OPERATING_HISTORY`, and this is checked before either ratio."
        PRD: "The `dscr_bps` is annualized net operating income multiplied by 10,000, divided by annualized debt service, floored to a whole basis point. The `min_occupancy_bps` is computed per month and then minimized: for each month in the window, the month's `occupied_units` multiplied by 10,000 divided by the development's `total_units`, floored to a whole basis point, and the smallest of those monthly figures is taken."
        PRD: "The development moves `PLACED_IN_SERVICE` → `STABILIZED` and its `compliance_start_date` is stamped equal to the issue's `conversion_date`. That development transition in turn causes the development's `RECORDED` regulatory agreement to stamp its own two end dates — `compliance_period_end_date` becomes the compliance start date plus the agreement's `compliance_period_years`, and `extended_use_end_date` becomes the compliance start date plus its `extended_use_years` — and those two values are mirrored onto the development as `compliance_end_date` and `extended_use_end_date` respectively."

        Design: Corner/state_machines/conversion_requires_the_whole_operating_window_before_any_ratio_is_computed
        """
        deal = fixtures.setup_operating_months(api, count=2)

        for basis in ("T3", "T12"):
            validate_error(
                api.convert_bond_issue(
                    deal.bond_issue_id,
                    TRUSTEE,
                    dscr_basis=basis,
                    conversion_date=constants.CONVERSION_DATE,
                ),
                ApiErrorId.ERR_INSUFFICIENT_OPERATING_HISTORY,
                422,
            )

        unconverted = fixtures.read_bond_issue(api, deal)
        assert_fields(unconverted, "bond_issue", status="ISSUED")
        assert_nulls(
            unconverted,
            ("dscr_bps", "dscr_basis", "min_occupancy_bps", "conversion_date"),
            "bond_issue",
        )
        assert_fields(
            fixtures.read_project(api, deal),
            "project",
            development_status="PLACED_IN_SERVICE",
        )

        fixtures.record_month(api, deal, 3)
        converted = validate_success(
            api.convert_bond_issue(
                deal.bond_issue_id,
                TRUSTEE,
                dscr_basis="T3",
                conversion_date=constants.CONVERSION_DATE,
            )
        )
        assert_fields(
            converted,
            "bond_issue",
            status="CONVERTED",
            dscr_basis="T3",
            dscr_bps=12000,
            min_occupancy_bps=10000,
        )
        assert converted["conversion_date"].startswith("2027-03-01T00:00:00"), (
            "the conversion stamps the supplied instant, got {0}".format(
                converted["conversion_date"]
            )
        )

        stabilized = fixtures.read_project(api, deal)
        assert_fields(stabilized, "project", development_status="STABILIZED")
        for field, instant in (
            ("compliance_start_date", "2027-03-01T00:00:00"),
            ("compliance_end_date", "2042-03-01T00:00:00"),
            ("extended_use_end_date", "2057-03-01T00:00:00"),
        ):
            assert stabilized[field].startswith(instant), (
                "project.{0} expected {1}, got {2}".format(
                    field, instant, stabilized[field]
                )
            )

        agreement = fixtures.read_agreement(api, deal)
        for field, instant in (
            ("compliance_period_end_date", "2042-03-01T00:00:00"),
            ("extended_use_end_date", "2057-03-01T00:00:00"),
        ):
            assert agreement[field].startswith(instant), (
                "agreement.{0} expected {1}, got {2}".format(
                    field, instant, agreement[field]
                )
            )


class TestTheTwoCoverageVariants:
    """One twelve-month series read two ways, with opposite answers."""

    def test_the_t3_variant_clears_conversion_while_t12_on_the_same_months_is_refused(
        self, api
    ):
        """Nine break-even months followed by three strong ones, judged both ways.

        The trailing quarter sees only the three strong months and annualizes them by
        four, giving exactly 12,000 basis points of coverage. The trailing year sees
        all twelve with a factor of one, and the nine break-even months drag it to
        10,500 — 1,000 basis points below the minimum. The same request therefore
        succeeds under one variant and is refused under the other, and the occupancy
        floor is met exactly at 9,000 basis points on nine of ten units.

        PRD: "Under `T3` the window is the three highest month indices and the annualization factor is 4 — a trailing quarter, annualized — so a strong lease-up quarter can pass even when the trailing year would fail. Under `T12` the window is the twelve highest month indices and the annualization factor is 1 — the trailing year, actual — so weak early months drag both the coverage ratio and the occupancy floor down. Entries outside the selected window are ignored entirely."
        PRD: "Then coverage: `dscr_bps` must be at least 11,500 basis points, which is 115 percent of debt service, and a shortfall is `ERR_DSCR_BELOW_MINIMUM`."

        Design: Difficulty/dual_variant_calc/dscr_variant_t3_clears_conversion_while_t12_on_the_same_months_is_refused
        """
        deal = fixtures.ten_unit_deal(api, stage=fixtures.setup_funded_draw)
        for month_index in range(1, 10):
            fixtures.record_month(
                api,
                deal,
                month_index,
                noi_cents=15000000,
                debt_service_cents=15000000,
                occupied_units=9,
            )
        for month_index in range(10, 13):
            fixtures.record_month(
                api,
                deal,
                month_index,
                noi_cents=18000000,
                debt_service_cents=15000000,
                occupied_units=9,
            )

        validate_error(
            api.convert_bond_issue(
                deal.bond_issue_id,
                TRUSTEE,
                dscr_basis="T12",
                conversion_date="2027-12-01T00:00:00Z",
            ),
            ApiErrorId.ERR_DSCR_BELOW_MINIMUM,
            422,
        )
        assert_fields(
            fixtures.read_bond_issue(api, deal), "bond_issue", status="ISSUED"
        )

        converted = validate_success(
            api.convert_bond_issue(
                deal.bond_issue_id,
                TRUSTEE,
                dscr_basis="T3",
                conversion_date="2027-12-01T00:00:00Z",
            )
        )
        assert_fields(
            converted,
            "bond_issue",
            status="CONVERTED",
            dscr_basis="T3",
            dscr_bps=12000,
            min_occupancy_bps=9000,
        )
        assert_fields(
            fixtures.read_project(api, deal), "project", development_status="STABILIZED"
        )


class TestTheTwoFiftyPercentVariants:
    """The provisional answer at issuance and the binding answer at acceptance."""

    def test_the_provisional_variant_passes_and_the_final_variant_revokes_the_credit(
        self, api
    ):
        """One development that clears the test at closing and fails it on audit.

        The provisional variant divided the par amount by the basis filed at creation
        and landed exactly on the threshold. The final variant reads different figures
        on both sides: funded draw proceeds over the *audited* aggregate basis, which
        the certification restates 10,000,000 higher. That is enough to drop the ratio
        to 4,878 basis points, and acceptance overwrites the credit trigger the
        provisional pass had set — the two ratios coexist on the development,
        deliberately disagreeing.

        PRD: "Its numerator is the summed `approved_amount_cents` of the draws on the development's bond issue whose `status` is `FUNDED` — draws that reached `VOIDED` or `REJECTED`, and draws still merely `APPROVED` or `SUBMITTED`, are all excluded, so proceeds that were authorized but never funded do not count. Its denominator is this certification's `certified_aggregate_basis_cents`."
        PRD: "The development's `automatic_credit_triggered` is then set to whether that final ratio is at least 5,000 basis points, **overwriting** whatever the provisional variant concluded: a development whose provisional test passed can lose its credit trigger here, and one whose provisional test barely passed can be confirmed."
        PRD: "The server solves `certified_aggregate_basis_cents` as the certified land cost plus the certified depreciable basis."

        Design: Difficulty/dual_variant_calc/fifty_percent_test_provisional_passes_then_final_variant_revokes_the_credit
        """
        deal = fixtures.setup_submitted_cost_certification(
            api,
            cost_cert_overrides={
                "certified_land_cost_cents": 45000000,
                "certified_depreciable_basis_cents": 365000000,
            },
        )
        assert_fields(
            deal.bond_issue,
            "bond_issue",
            par_amount_cents=200000000,
            issuance_allowance_cents=3920000,
        )
        before = fixtures.read_project(api, deal)
        assert_fields(
            before,
            "project",
            aggregate_basis_cents=400000000,
            provisional_fifty_percent_ratio_bps=5000,
            automatic_credit_triggered=True,
        )
        assert_fields(
            deal.cost_certification,
            "cost_certification",
            certified_aggregate_basis_cents=410000000,
        )

        accepted = fixtures.review_cost_certification(api, deal, decision="ACCEPT")
        assert_fields(accepted, "cost_certification", status="ACCEPTED")

        after = deal.project
        assert_fields(
            after,
            "project",
            provisional_fifty_percent_ratio_bps=5000,
            final_fifty_percent_ratio_bps=4878,
            automatic_credit_triggered=False,
        )
        assert after["final_fifty_percent_ratio_bps"] != after[
            "provisional_fifty_percent_ratio_bps"
        ], "the two variants must be free to disagree on the same development"


class TestTheCertificationLifecycle:
    """The sponsor-standing gate above it, and the audit loop inside it."""

    def test_certification_submission_waits_on_the_sponsor_being_reinstated(self, api):
        """One suspension and one reinstatement around an otherwise identical submit.

        The blocking state sits neither on the certification nor on its development but
        on the sponsor that owns the development, and the gate is two-way: suspension
        refuses the submission before the certification's own state is consulted, and
        reinstatement clears it again. The refused attempt must leave the certification
        in `DRAFT` with `submission_round` still at zero, which is what proves it never
        counted as a pass.

        PRD: "The owning `Developer`'s `status` must be `ACTIVE` for any project-advancing write: filing a development, requesting cap, sizing a bond issue, closing that issue, submitting a draw, and submitting a cost certification. A `SUSPENDED` or `DEBARRED` sponsor is blocked with `ERR_DEVELOPER_NOT_ACTIVE` (HTTP 409)."
        PRD: "A `REINSTATE` action moves a `SUSPENDED` sponsor back to `ACTIVE` and clears `sanction_reason` to null; this `ACTIVE` → `SUSPENDED` → `ACTIVE` cycle is unbounded and may be repeated indefinitely."
        PRD: "Each submission increments `submission_round` by 1 and clears `deficiency_notes` to null — which is why a certification that was returned once and resubmitted reads `submission_round` 2."

        Design: Difficulty/cross_entity_state_dependency/cost_certification_submission_depends_on_the_sponsor_being_reinstated
        """
        deal = fixtures.setup_drafted_cost_certification(api)
        assert_fields(
            deal.cost_certification,
            "cost_certification",
            status="DRAFT",
            submission_round=0,
            certified_aggregate_basis_cents=400000000,
        )

        suspended = validate_success(
            api.sanction_developer(
                deal.developer_id,
                COMPLIANCE_OFFICER,
                action="SUSPEND",
                reason="unresolved monitoring findings",
            )
        )
        assert_fields(
            suspended,
            "developer",
            status="SUSPENDED",
            sanction_reason="unresolved monitoring findings",
        )

        validate_error(
            api.submit_cost_certification(
                deal.cost_certification_id, deal.developer_headers
            ),
            ApiErrorId.ERR_DEVELOPER_NOT_ACTIVE,
            409,
        )
        blocked = validate_success(
            api.get_cost_certification(
                deal.cost_certification_id, deal.developer_headers
            )
        )
        assert_fields(
            blocked, "cost_certification", status="DRAFT", submission_round=0
        )

        reinstated = validate_success(
            api.sanction_developer(
                deal.developer_id,
                COMPLIANCE_OFFICER,
                action="REINSTATE",
                reason="findings cleared",
            )
        )
        assert_fields(reinstated, "developer", status="ACTIVE")
        assert_nulls(reinstated, ("sanction_reason",), "developer")

        submitted = fixtures.submit_cost_certification(api, deal)
        assert_fields(
            submitted,
            "cost_certification",
            status="SUBMITTED",
            submission_round=1,
            certified_aggregate_basis_cents=400000000,
        )

    def test_the_certification_returns_to_submitted_twice_and_locks_after_acceptance(
        self, api
    ):
        """One audit revision cycle, then acceptance, then a submit that has nowhere to go.

        `SUBMITTED` is not a station the certification passes through once: it is
        re-entered from `RETURNED_FOR_REVISION`, and the two visits are told apart only
        by `submission_round`, which reads 1 and then 2. The resubmission restates the
        audited figures, so the aggregate basis is re-solved, and it clears the
        deficiency notes the return had stamped. Acceptance is terminal, so the third
        submit has no outgoing transition at all — and acceptance is also what writes
        the final fifty-percent ratio, here 5,000 basis points from the 200,000,000 of
        funded proceeds over the restated 400,000,000 basis.

        PRD: "A return moves it `SUBMITTED` → `RETURNED_FOR_REVISION`, stamps the supplied `deficiency_notes` and stamps `reviewed_by_user_id` from the acting `X-User-ID`, and leaves the development's `final_fifty_percent_ratio_bps` untouched; the `SUBMITTED` → `RETURNED_FOR_REVISION` → `SUBMITTED` loop is the audit revision cycle and `submission_round` records how many passes occurred. An acceptance moves it `SUBMITTED` → `ACCEPTED`, which is terminal, stamps `accepted_at` from the logical clock and stamps `reviewed_by_user_id`."
        PRD: "The submission may optionally restate any of `certified_land_cost_cents`, `certified_depreciable_basis_cents` or `certified_eligible_basis_cents`; when any of them is restated, `certified_aggregate_basis_cents` is recomputed."
        PRD: "The ratio is the numerator multiplied by 10,000, divided by the denominator, floored to a whole basis point, and it is written to the development's `final_fifty_percent_ratio_bps`."

        Design: Difficulty/non_linear_state_machine/cost_certification_returns_to_submitted_twice_and_locks_after_acceptance
        """
        deal = fixtures.setup_drafted_cost_certification(api)

        first = fixtures.submit_cost_certification(api, deal)
        assert_fields(
            first, "cost_certification", status="SUBMITTED", submission_round=1
        )

        returned = fixtures.review_cost_certification(
            api,
            deal,
            decision="RETURN",
            deficiency_notes="Developer fee schedule missing",
        )
        assert_fields(
            returned,
            "cost_certification",
            status="RETURNED_FOR_REVISION",
            deficiency_notes="Developer fee schedule missing",
        )

        second = fixtures.submit_cost_certification(
            api,
            deal,
            certified_land_cost_cents=42000000,
            certified_depreciable_basis_cents=358000000,
        )
        assert_fields(
            second,
            "cost_certification",
            status="SUBMITTED",
            submission_round=2,
            certified_aggregate_basis_cents=400000000,
        )
        assert_nulls(second, ("deficiency_notes",), "cost_certification")

        accepted = fixtures.review_cost_certification(api, deal, decision="ACCEPT")
        assert_fields(
            accepted,
            "cost_certification",
            status="ACCEPTED",
            reviewed_by_user_id=SECOND_ALLOCATION_OFFICER_USER_ID,
        )
        assert_fields(
            deal.project,
            "project",
            final_fifty_percent_ratio_bps=5000,
            automatic_credit_triggered=True,
        )

        validate_error(
            api.submit_cost_certification(
                deal.cost_certification_id, deal.developer_headers
            ),
            ApiErrorId.ERR_COST_CERT_STATE_INVALID,
            409,
        )
        locked = validate_success(
            api.get_cost_certification(
                deal.cost_certification_id, deal.developer_headers
            )
        )
        assert_fields(
            locked, "cost_certification", status="ACCEPTED", submission_round=2
        )
