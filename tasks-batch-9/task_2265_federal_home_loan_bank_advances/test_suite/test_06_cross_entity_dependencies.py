"""Transitions gated by the state of a different entity: a child blocked by its
parent, a parent blocked by its children, and a creation blocked by a peer."""
from test_helpers import *  # noqa: F401,F403


class TestAdvanceFundingGatedByMemberPosture:
    """An approved advance the member can afford, refused on posture alone."""

    def _approved_advance_under_a_restricted_member(self, api):
        """Approve while the posture is OPEN, then fail a review to restrict it."""
        env = member_with_eligible_sf(api)
        add_heloc(api, env)
        product = create_product(api)
        advance = approved_advance(
            api,
            env,
            product["id"],
            term_days=360,
            requested_net_proceeds_cents=950_000,
            fund_stock_from_advance=True,
        )
        member_with_failed_review(api, env, env.assets["heloc"]["id"])
        return env, advance

    def test_the_failed_review_restricts_a_member_whose_capacity_is_ample(self, api):
        """PRD §2.8: "The posture becomes `RESTRICTED` if any of three conditions
        holds: `shortfall_status` is `ESCALATED`; or `latest_review_outcome` is `FAIL`;
        or `borrowing_capacity_cents` is strictly less than a 500-basis-point buffer
        over the outstanding book, that buffer being 5 percent of
        `total_outstanding_advances_cents` rounded half up to whole cents."

        Design: Difficulty/cross_entity_state_dependency/advance_fund_rejected_when_member_posture_restricted
        """
        env, _advance = self._approved_advance_under_a_restricted_member(api)

        member = env.refresh()

        assert_fields(
            member,
            latest_review_outcome="FAIL",
            verification_haircut_bps=1_500,
            lendable_collateral_value_cents=12_600_000,
            committed_advances_cents=1_000_000,
            borrowing_capacity_cents=11_600_000,
            collateral_posture="RESTRICTED",
        )
        assert member["shortfall_status"] == "NONE"

    def test_funding_demands_a_posture_of_exactly_open(self, api):
        """PRD §3.6: "Funding demands a stricter posture than approval did:
        `collateral_posture` must be exactly `OPEN`, so a `RESTRICTED` member cannot
        fund at all, and the rejection carries `ERR_COLLATERAL_POSTURE_FROZEN`."

        Design: Difficulty/cross_entity_state_dependency/advance_fund_rejected_when_member_posture_restricted
        """
        _env, advance = self._approved_advance_under_a_restricted_member(api)

        response = api.fund_advance(advance["id"], CREDIT_TWO)

        validate_error(response, "ERR_COLLATERAL_POSTURE_FROZEN", 409)
        after = read_advance(api, advance["id"])
        assert_advance_dimensions(after, "CREDIT_APPROVED", "PENDING_VERIFICATION")
        assert after["funded_at"] is None
        assert after["outstanding_principal_cents"] == 0

    def test_the_refused_funding_issues_no_activity_stock(self, api):
        """PRD §3.6: "When `fund_stock_from_advance` is true, an `ACTIVITY`
        subscription of `amount_cents` equal to `activity_stock_cents` is created with
        its `advance_id` pointing at this advance and is immediately `ISSUED` in the
        same request — its `SUBSCRIBED` state is never observable on this path."

        Design: Difficulty/cross_entity_state_dependency/advance_fund_rejected_when_member_posture_restricted
        """
        env, advance = self._approved_advance_under_a_restricted_member(api)
        version_before = env.version

        api.fund_advance(advance["id"], CREDIT_TWO)

        assert_total_count(
            api.list_stock_subscriptions(CREDIT_ONE, {"advance_id": advance["id"]}), 0
        )
        member = env.refresh()
        assert_fields(
            member, total_outstanding_advances_cents=0, version=version_before
        )


class TestReviewRetestGatedByFindingSeverity:
    """A parent review blocked by an aggregate predicate over its children."""

    def _review_in_remediation_with_one_critical_open(self, api):
        env = pledging_member(api)
        asset = pledge_asset(api, env.member_id)
        review = review_in_field_work(api, env)
        minor = raise_finding(
            api, review["id"], asset["id"], "MINOR", "INELIGIBLE_PROPERTY_TYPE"
        )
        critical = raise_finding(
            api, review["id"], asset["id"], "CRITICAL", "LIEN_DEFECT"
        )
        issued = issue_findings(api, review["id"])
        assert issued["status"] == "REMEDIATION"
        remediate_finding(api, env, minor["id"])
        return env, review, minor, critical

    def test_an_open_critical_finding_blocks_the_retest(self, api):
        """PRD §3.8: "Retest requires that every finding of the review with `severity`
        `CRITICAL` now has `status` `REMEDIATED` or `WAIVED`, else
        `ERR_CRITICAL_FINDINGS_OPEN`; and it requires `retest_count` to be strictly
        below the retest ceiling of 2, else `ERR_RETEST_LIMIT_EXCEEDED`."

        Design: Difficulty/cross_entity_state_dependency/review_retest_rejected_while_critical_finding_open
        """
        _env, review, _minor, _critical = self._review_in_remediation_with_one_critical_open(api)

        response = api.retest_review(review["id"], AUDITOR)

        validate_error(response, "ERR_CRITICAL_FINDINGS_OPEN", 409)
        assert_fields(read_review(api, review["id"]), status="REMEDIATION", retest_count=0)

    def test_the_gate_reads_the_children_statuses_it_claims_to_read(self, api):
        """PRD §3.8: "A `TreasuryOfficer` remediates an `OPEN` finding, moving it to
        `REMEDIATED`, and it thereafter stops contributing to the weighted exception
        score."

        Design: Difficulty/cross_entity_state_dependency/review_retest_rejected_while_critical_finding_open
        """
        _env, review, minor, critical = self._review_in_remediation_with_one_critical_open(api)
        api.retest_review(review["id"], AUDITOR)

        minor_row = get_success_data(api.get_review_finding(minor["id"], AUDITOR))
        critical_row = get_success_data(api.get_review_finding(critical["id"], AUDITOR))

        assert minor_row["status"] == "REMEDIATED"
        assert critical_row["status"] == "OPEN"

    def test_resolving_the_critical_finding_unblocks_the_very_same_retest(self, api):
        """PRD §3.8: "From `REMEDIATION` the auditor may retest, moving the review back
        to `FIELD_WORK` and incrementing `retest_count` by 1."

        Design: Difficulty/cross_entity_state_dependency/review_retest_rejected_while_critical_finding_open
        """
        _env, review, _minor, critical = self._review_in_remediation_with_one_critical_open(api)
        validate_error(
            api.retest_review(review["id"], AUDITOR), "ERR_CRITICAL_FINDINGS_OPEN", 409
        )

        waive_finding(api, critical["id"])
        retested = validate_success(api.retest_review(review["id"], AUDITOR))

        assert_fields(retested, status="FIELD_WORK", retest_count=1)


class TestSafekeepingBookingGatedByAssetLifecycle:
    """A new child row refused because of the state of the row it would hang from."""

    def _substituted_asset_and_its_replacement(self, api):
        env = member_with_eligible_sf(api)
        replacement = substitute_asset(api, env, env.assets["sf"]["id"])
        return env, env.assets["sf"]["id"], replacement

    def test_substitution_retires_the_outgoing_asset_and_parks_the_replacement(self, api):
        """PRD §3.9: "A successful substitution creates a replacement asset from the
        request body with `replaces_asset_id` set to the `id` of the outgoing asset and
        `status` `UNDER_REVIEW`; the replacement is what comes back in the response."

        Design: Difficulty/cross_entity_state_dependency/safekeeping_receipt_rejected_for_substituted_asset
        """
        env, outgoing_id, replacement = self._substituted_asset_and_its_replacement(api)

        assert_fields(
            read_asset(api, outgoing_id), status="SUBSTITUTED", lendable_value_cents=0
        )
        assert_fields(
            read_asset(api, replacement["id"]),
            status="UNDER_REVIEW",
            replaces_asset_id=outgoing_id,
            lendable_value_cents=0,
        )
        assert env.refresh()["lendable_collateral_value_cents"] == 0

    def test_a_delivery_cannot_be_booked_against_a_substituted_asset(self, api):
        """PRD §3.3: "An asset whose `status` is `INELIGIBLE` or `SUBSTITUTED` cannot
        receive a delivery at all, and the attempt is rejected with
        `ERR_ASSET_NOT_ELIGIBLE`."

        Design: Difficulty/cross_entity_state_dependency/safekeeping_receipt_rejected_for_substituted_asset
        """
        _env, outgoing_id, _replacement = self._substituted_asset_and_its_replacement(api)

        response = api.create_safekeeping_receipt(
            outgoing_id, safekeeping_receipt_payload(), CUSTODIAN
        )

        validate_error(response, "ERR_ASSET_NOT_ELIGIBLE", 409)
        assert_total_count(
            api.list_safekeeping_receipts(
                CUSTODIAN, {"collateral_asset_id": outgoing_id}
            ),
            0,
        )

    def test_the_same_booking_succeeds_once_the_replacement_is_eligible(self, api):
        """PRD §3.3: "The new receipt starts with `status` `PENDING_DELIVERY`,
        `received_at` null and `exception_note` null."

        Design: Difficulty/cross_entity_state_dependency/safekeeping_receipt_rejected_for_substituted_asset
        """
        env, _outgoing_id, replacement = self._substituted_asset_and_its_replacement(api)
        review_asset(api, replacement["id"])

        response = api.create_safekeeping_receipt(
            replacement["id"], safekeeping_receipt_payload(), CUSTODIAN
        )

        receipt = validate_success(response, 201)
        assert receipt["status"] == "PENDING_DELIVERY"
        assert env.refresh()["lendable_collateral_value_cents"] == 15_600_000
