"""The member version as a concurrency token: the two write endpoints that demand it,
the indirect writes that advance it, and the verification haircut that proves a band is
recomputed from scratch rather than accumulated."""
from test_helpers import *  # noqa: F401,F403


class TestAdvanceCreateAgainstAStaleMember:
    """The advance sizes itself against a snapshot, so the snapshot must be current."""

    def _member_repriced_after_the_client_read_it(self, api):
        """The client captures version V, then a tier change moves the member past V."""
        env = member_with_eligible_sf(api)
        product = create_product(api)
        stale_version = env.version
        amend_condition(api, env.member_id, credit_rating_tier=2)
        return env, product, stale_version

    def test_a_version_read_before_the_reprice_is_refused_on_the_version_alone(self, api):
        """PRD §2.7: "In each case the request carries `expected_member_bank_version`, a
        non-optional integer field holding the `version` of the `MemberBank` the client last
        read. If the value does not equal the member's current `version`, the request is
        rejected with `ERR_STALE_MEMBER_VERSION` and HTTP 412, and nothing is written."

        Design: Corner/complexity_layers/advance_create_with_stale_member_version_returns_4XX
        """
        env, product, stale_version = self._member_repriced_after_the_client_read_it(api)

        refused = api.create_advance(
            advance_payload(
                env.member_id,
                product["id"],
                stale_version,
                term_days=30,
                requested_net_proceeds_cents=1_000_000,
            ),
            env.treasury,
        )

        validate_error(refused, "ERR_STALE_MEMBER_VERSION", 412)
        assert_total_count(
            api.list_advances(CREDIT_ONE, {"member_bank_id": env.member_id}), 0
        )
        member = env.refresh()
        assert_fields(
            member,
            committed_advances_cents=0,
            credit_rating_tier=2,
            version=stale_version + 1,
        )

    def test_the_identical_request_carrying_the_fresh_version_succeeds(self, api):
        """PRD §3.5: "The provisional figure that was used is preserved on the advance as
        `capacity_at_request_cents`. ... Creation then recomputes the member's
        `committed_advances_cents` and certified `borrowing_capacity_cents` — the certified
        variant now counting this `REQUESTED` advance as a commitment — and runs the posture
        recomputation."

        Design: Corner/complexity_layers/advance_create_with_stale_member_version_returns_4XX
        """
        env, product, stale_version = self._member_repriced_after_the_client_read_it(api)
        fresh_version = env.version

        accepted = validate_success(
            api.create_advance(
                advance_payload(
                    env.member_id,
                    product["id"],
                    fresh_version,
                    term_days=30,
                    requested_net_proceeds_cents=1_000_000,
                ),
                env.treasury,
            ),
            201,
        )

        assert fresh_version == stale_version + 1
        assert_fields(
            accepted,
            credit_status="REQUESTED",
            gross_principal_cents=1_000_000,
            capacity_at_request_cents=14_040_000,
        )
        assert_fields(
            env.refresh(),
            committed_advances_cents=1_000_000,
            borrowing_capacity_cents=13_040_000,
        )


class TestSubstitutionAgainstAStaleMember:
    """The same token guards the other write, and the pool is left untouched."""

    def _heloc_and_a_bumped_version(self, api):
        env = applicant_member(api)
        execute_pledge_agreement(api, env.member_id)
        heloc = add_heloc(api, env)
        stale_version = env.version
        amend_condition(api, env.member_id, credit_rating_tier=2)
        return env, heloc, stale_version

    def _replacement(self, expected_version):
        return substitution_payload(
            expected_version,
            asset_class="HELOC",
            unpaid_principal_balance_cents=1_200_000,
            market_value_cents=1_200_000,
            ltv_bps=7_000,
        )

    def test_a_stale_substitution_never_reaches_the_collateral_pool(self, api):
        """PRD §2.7: "The second is **pledge substitution**. A substitution is judged
        against the member's current lendable value and posture, and each preceding
        substitution or eligibility decision advances the member's `version`. Substituting a
        different, still-pledged asset would succeed under identical product rules, so again
        only the stale version distinguishes the rejected call from the accepted one."

        Design: Corner/complexity_layers/substitute_with_stale_member_version_returns_4XX
        """
        env, heloc, stale_version = self._heloc_and_a_bumped_version(api)

        refused = api.substitute_collateral_asset(
            heloc["id"], self._replacement(stale_version), env.treasury
        )

        validate_error(refused, "ERR_STALE_MEMBER_VERSION", 412)
        stayed = read_asset(api, heloc["id"])
        assert stayed["status"] == "ELIGIBLE"
        assert_asset_valuation(stayed, 5_000, 500_000)
        assert_total_count(
            api.list_collateral_assets(CREDIT_ONE, {"replaces_asset_id": heloc["id"]}), 0
        )
        assert env.refresh()["lendable_collateral_value_cents"] == 500_000

    def test_the_fresh_version_substitutes_the_asset_out(self, api):
        """PRD §3.9: "A successful substitution creates a replacement asset from the request
        body with `replaces_asset_id` set to the `id` of the outgoing asset and `status`
        `UNDER_REVIEW`; the replacement is what comes back in the response. The outgoing
        asset moves to `SUBSTITUTED` — from `ELIGIBLE`, from `SUSPENDED` or from
        `INELIGIBLE` alike, with identical effects in every case — and its
        `lendable_value_cents` and `discount_factor_bps` are set to 0."

        Design: Corner/complexity_layers/substitute_with_stale_member_version_returns_4XX
        """
        env, heloc, _stale_version = self._heloc_and_a_bumped_version(api)

        replacement = assert_envelope(
            api.substitute_collateral_asset(
                heloc["id"], self._replacement(env.version), env.treasury
            ),
            201,
        )

        assert_fields(
            replacement,
            replaces_asset_id=heloc["id"],
            status="UNDER_REVIEW",
            asset_class="HELOC",
            collateral_basis_cents=1_200_000,
        )
        outgoing = read_asset(api, heloc["id"])
        assert outgoing["status"] == "SUBSTITUTED"
        assert_asset_valuation(outgoing, 0, 0)
        assert_asset_valuation(review_asset(api, replacement["id"]), 5_000, 600_000)


class TestMemberVersionCounter:
    """A child write that moves an aggregate is a mutation of the parent."""

    def test_each_listed_operation_advances_the_counter_by_exactly_one(self, api):
        """PRD §2.4: "That includes activation, a condition change, execution of a pledge
        agreement, shortfall escalation, issuing or repurchasing stock, requesting
        redemption, an eligibility decision on an asset, a documentation update, a
        substitution, a safekeeping confirmation in either of its two outcomes, creating an
        advance, approving it, funding it, repaying it, settling a prepayment, and closing a
        verification review. A single request increments the member's `version` at most
        once, no matter how many aggregate fields the cascade touched."

        Design: Corner/complexity_layers/member_bank_version_increments_on_every_write
        """
        pin_clock(api)
        member = create_member(api)
        subscription = subscribe_stock(api, member["id"], 9_600_000)
        before_issue = read_member(api, member["id"])["version"]
        issue_stock(api, subscription["id"])
        after_issue = read_member(api, member["id"])["version"]
        activate_member(api, member["id"])
        after_activation = read_member(api, member["id"])["version"]
        execute_pledge_agreement(api, member["id"])
        after_pledge = read_member(api, member["id"])["version"]
        asset = pledge_asset(api, member["id"])
        before_review = read_member(api, member["id"])["version"]
        review_asset(api, asset["id"])
        after_review = read_member(api, member["id"])

        assert member["version"] == 1
        assert after_issue == before_issue + 1
        assert after_activation == after_issue + 1
        assert after_pledge == after_activation + 1
        assert after_review["version"] == before_review + 1
        assert after_review["version"] > 1
        assert_fields(
            after_review,
            lendable_collateral_value_cents=15_600_000,
            borrowing_capacity_cents=15_600_000,
        )

    def test_reads_never_move_the_counter(self, api):
        """PRD §2.4: "`version` (integer): a counter that starts at 1 when the resource is
        created and increases by exactly 1 on each subsequent mutation of that resource."

        Design: Corner/complexity_layers/member_bank_version_increments_on_every_write
        """
        env = member_with_eligible_sf(api)
        settled = env.version

        for _ in range(3):
            assert read_member(api, env.member_id)["version"] == settled
        env.capacity("CERTIFIED")
        env.capacity("PROVISIONAL")
        read_asset(api, env.assets["sf"]["id"])
        assert_total_count(api.list_collateral_assets(CREDIT_ONE), 1)

        assert env.refresh()["version"] == settled


class TestVerificationHaircutBand:
    """The haircut is a level read off the latest close, not a running total."""

    def _four_minor_findings_closed(self, api):
        """Four MINOR findings on a sample of 20 is exactly 5.00 percent."""
        env = member_with_eligible_sf(api)
        review = review_in_field_work(
            api,
            env,
            window_start=CLOCK_START,
            window_end="2026-08-10T00:00:00Z",
            sample_size=20,
        )
        for finding_type in (
            "STALE_APPRAISAL",
            "MISSING_NOTE",
            "LIEN_DEFECT",
            "UNREPORTED_DELINQUENCY",
        ):
            raise_finding(
                api,
                review["id"],
                env.assets["sf"]["id"],
                severity="MINOR",
                finding_type=finding_type,
            )
        issue_findings(api, review["id"])
        return env, close_review(api, review["id"])

    def test_the_first_review_prices_a_seven_hundred_point_haircut(self, api):
        """PRD §3.8: "`haircut_bps` is then selected by band from that rounded percentage,
        with every lower bound inclusive: 0 basis points below 2.00 percent; 300 basis
        points from 2.00 percent up to but not including 5.00 percent; 700 basis points
        from 5.00 percent up to but not including 10.00 percent; and 1,500 basis points at
        10.00 percent or above."

        Design: Corner/complexity_layers/verification_haircut_band_resets_to_zero_after_a_clean_review
        """
        env, closed = self._four_minor_findings_closed(api)

        assert_fields(
            closed, status="CLOSED", haircut_bps=700, outcome="QUALIFIED"
        )
        assert_weighted_score(closed, 1.0)
        assert_exception_rate(closed, 5.00)
        findings = assert_total_count(
            api.list_review_findings(
                AUDITOR, {"collateral_verification_review_id": closed["id"]}
            ),
            4,
        )
        assert all(row["status"] == "UNRESOLVED" for row in findings)
        asset = read_asset(api, env.assets["sf"]["id"])
        assert asset["status"] == "ELIGIBLE"
        assert_asset_valuation(asset, 7_100, 14_200_000)
        assert_fields(
            env.refresh(),
            verification_haircut_bps=700,
            latest_review_outcome="QUALIFIED",
            lendable_collateral_value_cents=14_200_000,
        )

    def test_a_clean_second_review_takes_the_band_back_to_zero(self, api):
        """PRD §3.8: "The member's `verification_haircut_bps` therefore always reflects the
        most recently closed review and is one of 0, 300, 700 or 1,500."

        Design: Corner/complexity_layers/verification_haircut_band_resets_to_zero_after_a_clean_review
        """
        env, _first = self._four_minor_findings_closed(api)
        pin_clock(api, "2026-08-10T00:00:00Z")
        clean = review_in_field_work(
            api,
            env,
            window_start="2026-08-10T00:00:00Z",
            window_end="2026-08-20T00:00:00Z",
            sample_size=20,
        )
        issue_findings(api, clean["id"])

        closed = assert_envelope(api.close_review(clean["id"], AUDITOR))

        assert_fields(
            closed, status="CLOSED", haircut_bps=0, outcome="PASS"
        )
        assert_weighted_score(closed, 0.0)
        assert_exception_rate(closed, 0.00)
        assert_asset_valuation(
            read_asset(api, env.assets["sf"]["id"]), 7_800, 15_600_000
        )
        assert_fields(
            env.refresh(),
            verification_haircut_bps=0,
            latest_review_outcome="PASS",
            lendable_collateral_value_cents=15_600_000,
            borrowing_capacity_cents=15_600_000,
        )
