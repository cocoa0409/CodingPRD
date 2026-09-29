"""Non-linear lifecycles: an advance's two independent dimensions, the bounded
field-work retest cycle, and a collateral asset's suspension-and-restore loop."""
from test_helpers import *  # noqa: F401,F403


class TestAdvanceParallelDimensions:
    """One advance, two state machines that move on different triggers."""

    def _funded_advance_then_documentation_exception(self, api):
        """Fund 15,000,000 against 15,600,000 of collateral, then void the file."""
        env = member_with_eligible_sf(api)
        subscribe_and_issue(api, env.member_id, 680_000, "ACTIVITY")
        product = create_product(api)
        advance = funded_advance(
            api,
            env,
            product["id"],
            term_days=360,
            requested_net_proceeds_cents=15_000_000,
            fund_stock_from_advance=False,
        )
        assert_advance_dimensions(advance, "FUNDED", "SECURED")
        amend_documentation(
            api, env.assets["sf"]["id"], documentation_status="EXCEPTION"
        )
        return env, advance

    def test_documentation_amendment_zeroes_the_asset_and_the_member_aggregate(self, api):
        """PRD §3.4: "The amendment always pushes the asset back to `UNDER_REVIEW` —
        from `ELIGIBLE`, from `INELIGIBLE` or from `SUSPENDED` alike — updates the
        supplied fields, sets `discount_factor_bps` and `lendable_value_cents` to 0
        for as long as the asset stays `UNDER_REVIEW`, recomputes
        `collateral_basis_cents` and `effective_listing_mode`, and then recomputes the
        member's `lendable_collateral_value_cents` and `borrowing_capacity_cents` and
        re-derives `collateral_posture`."

        Design: Difficulty/non_linear_state_machine/advance_credit_dimension_holds_while_collateral_dimension_moves_to_shortfall
        """
        env, _advance = self._funded_advance_then_documentation_exception(api)

        asset = read_asset(api, env.assets["sf"]["id"])
        assert_fields(
            asset,
            status="UNDER_REVIEW",
            discount_factor_bps=0,
            lendable_value_cents=0,
        )
        member = env.refresh()
        assert_fields(
            member,
            lendable_collateral_value_cents=0,
            borrowing_capacity_cents=-15_000_000,
        )

    def test_negative_capacity_freezes_the_member_and_sizes_the_cure(self, api):
        """PRD §3.9: "The first term is the negation of the certified
        `borrowing_capacity_cents` at that instant; because that capacity is strictly
        negative there, the term is positive and equals the size of the hole. The
        second term is a 200-basis-point buffer over the outstanding book:
        `total_outstanding_advances_cents` multiplied by 200, divided by 10,000,
        rounded half up to whole cents."

        Design: Difficulty/non_linear_state_machine/advance_credit_dimension_holds_while_collateral_dimension_moves_to_shortfall
        """
        env, _advance = self._funded_advance_then_documentation_exception(api)

        member = env.refresh()

        assert member["collateral_posture"] == "FROZEN"
        assert_shortfall(
            member,
            "OPEN",
            15_300_000,
            shortfall_opened_at="2026-08-01T00:00:00.000Z",
            shortfall_cure_deadline="2026-08-06T00:00:00.000Z",
        )

    def test_the_credit_dimension_holds_through_the_collateral_freeze(self, api):
        """PRD §3.6: "`collateral_status` may oscillate `SECURED → SHORTFALL →
        SECURED` while `credit_status` stays `FUNDED` throughout, and no
        collateral-dimension movement ever changes `credit_status` on its own."

        Design: Difficulty/non_linear_state_machine/advance_credit_dimension_holds_while_collateral_dimension_moves_to_shortfall
        """
        _env, advance = self._funded_advance_then_documentation_exception(api)

        after = read_advance(api, advance["id"])

        assert after["credit_status"] == "FUNDED"
        assert after["outstanding_principal_cents"] == 15_000_000
        assert after["funded_at"] == "2026-08-01T00:00:00.000Z"
        assert after["maturity_date"] == "2027-07-27T00:00:00.000Z"


class TestReviewRetestCycle:
    """The field-work cycle, bounded by a retest ceiling of two."""

    def _review_at_its_retest_ceiling(self, api):
        """Run the cycle twice, leaving the review in REMEDIATION at count 2."""
        env = pledging_member(api)
        asset = pledge_asset(api, env.member_id)
        review = review_in_field_work(api, env)
        counts = []
        for finding_type in ("LIEN_DEFECT", "MISSING_NOTE"):
            finding = raise_finding(
                api, review["id"], asset["id"], "CRITICAL", finding_type
            )
            issued = issue_findings(api, review["id"])
            assert issued["status"] == "REMEDIATION"
            waive_finding(api, finding["id"])
            counts.append(retest_review(api, review["id"])["retest_count"])
        third = raise_finding(
            api, review["id"], asset["id"], "CRITICAL", "STALE_APPRAISAL"
        )
        issue_findings(api, review["id"])
        waive_finding(api, third["id"])
        return env, review, counts

    def test_each_retest_returns_the_review_to_field_work_and_increments_the_counter(self, api):
        """PRD §3.8: "From `REMEDIATION` the auditor may retest, moving the review
        back to `FIELD_WORK` and incrementing `retest_count` by 1."

        Design: Difficulty/non_linear_state_machine/review_field_work_remediation_cycle_third_retest_rejected
        """
        _env, _review, counts = self._review_at_its_retest_ceiling(api)

        assert counts == [1, 2]

    def test_third_retest_is_refused_and_consumes_nothing(self, api):
        """PRD §3.8: "Retest requires that every finding of the review with `severity`
        `CRITICAL` now has `status` `REMEDIATED` or `WAIVED`, else
        `ERR_CRITICAL_FINDINGS_OPEN`; and it requires `retest_count` to be strictly
        below the retest ceiling of 2, else `ERR_RETEST_LIMIT_EXCEEDED`."

        Design: Difficulty/non_linear_state_machine/review_field_work_remediation_cycle_third_retest_rejected
        """
        _env, review, _counts = self._review_at_its_retest_ceiling(api)

        response = api.retest_review(review["id"], AUDITOR)

        validate_error(response, "ERR_RETEST_LIMIT_EXCEEDED", 409)
        after = read_review(api, review["id"])
        assert_fields(after, status="REMEDIATION", retest_count=2)

    def test_every_finding_of_the_cycle_ended_waived(self, api):
        """PRD §3.8: "A `CreditOfficer` waives an `OPEN` finding, moving it to
        `WAIVED`, recording the acting `X-User-ID` in `waived_by_user_id`, and it
        likewise stops contributing."

        Design: Difficulty/non_linear_state_machine/review_field_work_remediation_cycle_third_retest_rejected
        """
        _env, review, _counts = self._review_at_its_retest_ceiling(api)

        response = api.list_review_findings(
            AUDITOR, {"collateral_verification_review_id": review["id"]}
        )

        rows = assert_total_count(response, 3)
        assert [row["status"] for row in rows] == ["WAIVED", "WAIVED", "WAIVED"]
        assert all(
            row["waived_by_user_id"] == CREDIT_OFFICER_ONE_USER_ID for row in rows
        )


class TestCollateralAssetSuspensionCycle:
    """ELIGIBLE to SUSPENDED to UNDER_REVIEW, held there by a data condition."""

    def _suspended_then_amended_heloc(self, api):
        env = member_with_eligible_sf(api)
        heloc = add_heloc(api, env)
        _review, findings = closed_review(
            api, env, heloc["id"], severities=("MAJOR",) * 4
        )
        suspended = read_asset(api, heloc["id"])
        amend_documentation(
            api, heloc["id"], documentation_status="COMPLETE", delinquency_days=0
        )
        return env, heloc, findings, suspended

    def test_close_suspends_the_asset_carrying_unresolved_findings(self, api):
        """PRD §3.8: "In addition, every `ELIGIBLE` asset carrying an `UNRESOLVED`
        finding from this review whose `severity` is `MAJOR` or `CRITICAL` transitions
        `ELIGIBLE → SUSPENDED`, with `lendable_value_cents` set to 0,
        `discount_factor_bps` set to 0 and `ineligibility_reason` set to
        `UNRESOLVED_REVIEW_FINDING`."

        Design: Difficulty/non_linear_state_machine/collateral_asset_cycles_eligible_suspended_under_review_eligible
        """
        _env, _heloc, _findings, suspended = self._suspended_then_amended_heloc(api)

        assert_fields(
            suspended,
            status="SUSPENDED",
            lendable_value_cents=0,
            discount_factor_bps=0,
            ineligibility_reason="UNRESOLVED_REVIEW_FINDING",
        )

    def test_haircut_reprices_the_surviving_asset_and_restricts_the_member(self, api):
        """PRD §2.8: "**Step three** runs only when step two did not produce `FROZEN`.
        The posture becomes `RESTRICTED` if any of three conditions holds:
        `shortfall_status` is `ESCALATED`; or `latest_review_outcome` is `FAIL`; or
        `borrowing_capacity_cents` is strictly less than a 500-basis-point buffer over
        the outstanding book, that buffer being 5 percent of
        `total_outstanding_advances_cents` rounded half up to whole cents."

        Design: Difficulty/non_linear_state_machine/collateral_asset_cycles_eligible_suspended_under_review_eligible
        """
        env, _heloc, _findings, _suspended = self._suspended_then_amended_heloc(api)

        member = env.refresh()

        assert_fields(
            member,
            verification_haircut_bps=1_500,
            latest_review_outcome="FAIL",
            lendable_collateral_value_cents=12_600_000,
            collateral_posture="RESTRICTED",
        )
        assert read_asset(api, env.assets["sf"]["id"])["discount_factor_bps"] == 6_300

    def test_amendment_reopens_the_asset_but_the_unresolved_findings_block_approval(self, api):
        """PRD §3.4: "Second, no `ReviewFinding` against this asset may stand in
        `UNRESOLVED` status, else `ERR_CRITICAL_FINDINGS_OPEN`."

        Design: Difficulty/non_linear_state_machine/collateral_asset_cycles_eligible_suspended_under_review_eligible
        """
        _env, heloc, findings, _suspended = self._suspended_then_amended_heloc(api)

        reopened = read_asset(api, heloc["id"])
        assert_fields(reopened, status="UNDER_REVIEW", lendable_value_cents=0)
        assert all(
            get_success_data(api.get_review_finding(finding["id"], AUDITOR))["status"]
            == "UNRESOLVED"
            for finding in findings
        )

        response = api.review_asset_eligibility(heloc["id"], CREDIT_ONE, {})

        validate_error(response, "ERR_CRITICAL_FINDINGS_OPEN", 409)
        assert read_asset(api, heloc["id"])["status"] == "UNDER_REVIEW"
