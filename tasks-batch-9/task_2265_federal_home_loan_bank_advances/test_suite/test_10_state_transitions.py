"""Transitions in isolation: where a lifecycle starts, which edges exist, which
terminal states are sealed, and what a legal edge drags along with it."""
from test_helpers import *  # noqa: F401,F403


class TestVerificationReviewEntryState:
    """A scheduled review has done nothing to the member yet."""

    def _scheduled_review(self, api, window_start, window_end):
        env = active_member(api)
        response = api.create_verification_review(
            verification_review_payload(
                env.member_id,
                window_start=window_start,
                window_end=window_end,
                sample_size=40,
            ),
            AUDITOR,
        )
        return env, response

    def test_scheduling_lands_in_scheduled_with_an_empty_scorecard(self, api):
        """PRD §3.8: "A new review starts with `status` `SCHEDULED`, `retest_count` 0,
        `outcome` `PENDING`, `haircut_bps` 0, `weighted_exception_score` 0,
        `exception_rate_pct` 0 and `closed_at` null."

        Design: Corner/state_machines/verification_review_starts_scheduled_with_zero_retests
        """
        env, response = self._scheduled_review(
            api, "2026-08-10T00:00:00Z", "2026-08-20T00:00:00Z"
        )

        review = assert_envelope(response, 201)
        assert_common_fields(review)
        assert_fields(
            review,
            status="SCHEDULED",
            retest_count=0,
            outcome="PENDING",
            haircut_bps=0,
            closed_at=None,
            sample_size=40,
        )
        assert_weighted_score(review, 0)
        assert_exception_rate(review, 0)
        member = env.refresh()
        assert_fields(
            member, verification_haircut_bps=0, latest_review_outcome="NONE"
        )

    def test_a_review_cannot_be_closed_out_of_scheduled(self, api):
        """PRD §3.8: "**Closing a review** is the single heaviest operation in the
        system. The auditor closes from `FINDINGS_ISSUED` — never directly from
        `REMEDIATION` — and only when no finding of the review is both `OPEN` and
        `CRITICAL`, else `ERR_CRITICAL_FINDINGS_OPEN`."

        Design: Corner/state_machines/review_close_directly_from_scheduled_rejected
        """
        env, response = self._scheduled_review(
            api, "2026-08-01T00:00:00Z", "2026-08-20T00:00:00Z"
        )
        review = validate_success(response, 201)

        refused = api.close_review(review["id"], AUDITOR)

        validate_error(refused, "ERR_INVALID_STATE", 409)
        after = read_review(api, review["id"])
        assert_fields(
            after, status="SCHEDULED", outcome="PENDING", version=review["version"]
        )
        assert_fields(
            env.refresh(), verification_haircut_bps=0, latest_review_outcome="NONE"
        )

    def test_neither_issuing_findings_nor_retesting_is_reachable_from_scheduled(self, api):
        """PRD §2.5: "**State legality.** The addressed entity's current state must be a
        declared source state for the requested transition; otherwise `ERR_INVALID_STATE`
        (409)."

        Design: Corner/state_machines/review_close_directly_from_scheduled_rejected
        """
        _env, response = self._scheduled_review(
            api, "2026-08-01T00:00:00Z", "2026-08-20T00:00:00Z"
        )
        review = validate_success(response, 201)

        issued = api.issue_findings(review["id"], AUDITOR)
        retested = api.retest_review(review["id"], AUDITOR)

        validate_error(issued, "ERR_INVALID_STATE", 409)
        validate_error(retested, "ERR_INVALID_STATE", 409)
        assert_fields(
            read_review(api, review["id"]), status="SCHEDULED", retest_count=0
        )


class TestStockSubscriptionTransitions:
    """Issue rolls the parent's holdings; the repurchased state is sealed."""

    def test_issuing_flips_the_row_and_rolls_the_parent_holdings(self, api):
        """PRD §3.1: "A `CreditOfficer` then issues the subscription, moving `status`
        from `SUBSCRIBED` to `ISSUED`. Issue is legal only from `SUBSCRIBED`, and only
        while the owning member's `membership_status` is not `TERMINATED`. Issuing
        recomputes the member's `stock_held_cents`, `stock_deficiency_cents` and
        `excess_stock_cents`."

        Design: Corner/state_machines/stock_subscription_issue_moves_subscribed_to_issued
        """
        env = applicant_member(api)
        subscription = subscribe_stock(api, env.member_id, 9_600_000)
        before = env.refresh()

        issued = assert_envelope(
            api.issue_stock_subscription(subscription["id"], CREDIT_ONE)
        )

        assert_stock_position(before, stock_held_cents=0, stock_deficiency_cents=9_600_000)
        assert_fields(issued, status="ISSUED", shares=960, version=2)
        assert_shares(issued)
        assert issued["updated_at"] == "2026-08-01T00:00:00.000Z"
        assert_stock_position(
            env.refresh(),
            stock_held_cents=9_600_000,
            stock_deficiency_cents=0,
            excess_stock_cents=0,
        )

    def _repurchased_excess_subscription(self, api):
        """Hold 10,600,000 against a 9,600,000 requirement, then hand 1,000,000 back."""
        env = active_member(api)
        excess = subscribe_stock(api, env.member_id, 1_000_000)
        issue_stock(api, excess["id"])
        validate_success(api.request_stock_redemption(excess["id"], env.treasury))
        validate_success(api.repurchase_stock_subscription(excess["id"], CREDIT_ONE))
        return env, excess

    def test_a_repurchased_subscription_refuses_a_second_redemption(self, api):
        """PRD §3.1: "`REPURCHASED` and `CANCELLED` are terminal states for a
        subscription."

        Design: Corner/state_machines/repurchased_subscription_second_redemption_request_rejected
        """
        env, excess = self._repurchased_excess_subscription(api)

        response = api.request_stock_redemption(excess["id"], env.treasury)

        validate_error(response, "ERR_INVALID_STATE", 409)
        assert (
            get_success_data(api.get_stock_subscription(excess["id"], CREDIT_ONE))[
                "status"
            ]
            == "REPURCHASED"
        )
        assert env.refresh()["stock_held_cents"] == 9_600_000

    def test_the_terminal_state_seals_issue_and_repurchase_as_well(self, api):
        """PRD §2.5: "**State legality.** The addressed entity's current state must be a
        declared source state for the requested transition; otherwise `ERR_INVALID_STATE`
        (409)."

        Design: Corner/state_machines/repurchased_subscription_second_redemption_request_rejected
        """
        env, excess = self._repurchased_excess_subscription(api)

        reissued = api.issue_stock_subscription(excess["id"], CREDIT_ONE)
        rebought = api.repurchase_stock_subscription(excess["id"], CREDIT_ONE)

        validate_error(reissued, "ERR_INVALID_STATE", 409)
        validate_error(rebought, "ERR_INVALID_STATE", 409)
        assert env.refresh()["stock_held_cents"] == 9_600_000


class TestMemberActivationGuards:
    """Activation is an edge out of APPLICANT, guarded by issued stock."""

    def test_activation_is_not_an_idempotent_setter(self, api):
        """PRD §3.1: "**Activation** is the `CreditOfficer`'s act of moving
        `membership_status` from `APPLICANT` to `ACTIVE`. It is legal only from
        `APPLICANT`, and only when `stock_held_cents` is at least
        `required_membership_stock_cents`."

        Design: Corner/state_machines/member_activate_twice_second_call_rejected
        """
        env = active_member(api)
        after_first = env.refresh()

        response = api.activate_member_bank(env.member_id, CREDIT_ONE)

        validate_error(response, "ERR_INVALID_STATE", 409)
        member = env.refresh()
        assert_fields(
            member,
            membership_status="ACTIVE",
            version=after_first["version"],
            collateral_posture="OPEN",
        )
        assert member["community_lending_eligible"] is True

    def test_only_issued_stock_satisfies_the_activation_guard(self, api):
        """PRD §3.1: "a member short of its membership stock is rejected with
        `ERR_MEMBERSHIP_STOCK_DEFICIENT`."

        Design: Corner/state_machines/member_activate_without_membership_stock_rejected
        """
        env = applicant_member(api)
        subscription = subscribe_stock(api, env.member_id, 9_600_000)

        refused = api.activate_member_bank(env.member_id, CREDIT_ONE)

        validate_error(refused, "ERR_MEMBERSHIP_STOCK_DEFICIENT", 409)
        assert_fields(env.refresh(), membership_status="APPLICANT")
        assert_stock_position(
            env.refresh(), stock_held_cents=0, stock_deficiency_cents=9_600_000
        )

        issue_stock(api, subscription["id"])

        activated = validate_success(
            api.activate_member_bank(env.member_id, CREDIT_ONE)
        )
        assert activated["membership_status"] == "ACTIVE"


class TestPledgeAndCustodyRepricing:
    """Two edges that reprice collateral without any per-asset call."""

    def test_re_executing_the_pledge_agreement_reprices_eligible_assets(self, api):
        """PRD §3.2: "Execution sets `pledge_agreement_status` to `EXECUTED`, records the
        supplied mode in `pledge_mode` and the supplied date in
        `pledge_agreement_effective_date`, then re-derives `delivery_required`, then
        re-derives `effective_listing_mode`, `discount_factor_bps` and
        `lendable_value_cents` for every `ELIGIBLE` or `SUSPENDED` asset of the member,
        and finally re-runs the capacity and posture computations."

        Design: Corner/state_machines/pledge_agreement_execution_recomputes_listing_mode_and_lendable_value
        """
        env = member_with_eligible_sf(api)

        member = assert_envelope(
            api.execute_pledge_agreement(
                env.member_id,
                pledge_agreement_payload("SPECIFIC_LISTING", CLOCK_START),
                CREDIT_ONE,
            )
        )

        assert_fields(
            member,
            pledge_mode="SPECIFIC_LISTING",
            pledge_agreement_status="EXECUTED",
            lendable_collateral_value_cents=17_200_000,
            borrowing_capacity_cents=17_200_000,
        )
        assert member["delivery_required"] is False
        asset = read_asset(api, env.assets["sf"]["id"])
        assert_fields(
            asset, effective_listing_mode="SPECIFIC", status="ELIGIBLE"
        )
        assert_asset_valuation(asset, 8_600, 17_200_000)

    def test_a_confirmed_receipt_upgrades_the_listing_mode_to_delivered(self, api):
        """PRD §3.3: "The parent asset's `custody_location` is set to
        `FHLB_SAFEKEEPING`. That custody change re-derives the asset's
        `effective_listing_mode` — which, with a received receipt now present, becomes
        `DELIVERED` — and when the asset's `status` is `ELIGIBLE` its
        `discount_factor_bps` and `lendable_value_cents` are recomputed at the richer
        delivered factor."

        Design: Corner/state_machines/safekeeping_confirm_received_upgrades_listing_mode_to_delivered
        """
        env = member_with_eligible_sf(api)
        receipt = book_receipt(
            api,
            env.assets["sf"]["id"],
            delivery_date=CLOCK_START,
            return_date="2026-09-30T00:00:00Z",
        )

        confirmed = assert_envelope(
            api.confirm_safekeeping_receipt(
                receipt["id"], confirm_receipt_payload("RECEIVED"), CUSTODIAN
            )
        )

        assert_fields(
            confirmed, status="RECEIVED", received_at="2026-08-01T00:00:00.000Z"
        )
        asset = read_asset(api, env.assets["sf"]["id"])
        assert_fields(
            asset,
            custody_location="FHLB_SAFEKEEPING",
            effective_listing_mode="DELIVERED",
            status="ELIGIBLE",
        )
        assert_asset_valuation(asset, 9_200, 18_400_000)
        assert_fields(
            env.refresh(),
            lendable_collateral_value_cents=18_400_000,
            borrowing_capacity_cents=18_400_000,
        )

    def test_files_cannot_be_confirmed_before_the_window_opens(self, api):
        """PRD §3.3: "Confirmation is legal only from `PENDING_DELIVERY`, and only once
        the logical clock has reached `delivery_date`; a confirmation attempted before the
        window opens is rejected with `ERR_INVALID_STATE`."

        Design: Corner/state_machines/safekeeping_confirm_before_delivery_date_rejected
        """
        env = member_with_eligible_sf(api)
        receipt = book_receipt(
            api,
            env.assets["sf"]["id"],
            delivery_date="2026-08-10T00:00:00Z",
            return_date="2026-09-30T00:00:00Z",
        )

        response = api.confirm_safekeeping_receipt(
            receipt["id"], confirm_receipt_payload("RECEIVED"), CUSTODIAN
        )

        validate_error(response, "ERR_INVALID_STATE", 409)
        stored = get_success_data(api.get_safekeeping_receipt(receipt["id"], CUSTODIAN))
        assert_fields(stored, status="PENDING_DELIVERY", received_at=None)
        asset = read_asset(api, env.assets["sf"]["id"])
        assert_fields(
            asset, custody_location="MEMBER_VAULT", effective_listing_mode="BLANKET"
        )
        assert_asset_valuation(asset, 7_800, 15_600_000)

    def test_the_identical_confirmation_succeeds_once_the_clock_arrives(self, api):
        """PRD §2.9: "Every date comparison in this system reads a server-held **logical
        clock** rather than wall-clock time: default timestamps, maturity computation,
        remaining-day counts, appraisal-age checks, verification-window gates,
        custody-window gates, quote validity and the shortfall cure deadline all resolve
        against it."

        Design: Corner/state_machines/safekeeping_confirm_before_delivery_date_rejected
        """
        env = member_with_eligible_sf(api)
        receipt = book_receipt(
            api,
            env.assets["sf"]["id"],
            delivery_date="2026-08-10T00:00:00Z",
            return_date="2026-09-30T00:00:00Z",
        )
        validate_error(
            api.confirm_safekeeping_receipt(
                receipt["id"], confirm_receipt_payload("RECEIVED"), CUSTODIAN
            ),
            "ERR_INVALID_STATE",
            409,
        )

        pin_clock(api, "2026-08-10T00:00:00Z")
        confirmed = validate_success(
            api.confirm_safekeeping_receipt(
                receipt["id"], confirm_receipt_payload("RECEIVED"), CUSTODIAN
            )
        )

        assert_fields(
            confirmed, status="RECEIVED", received_at="2026-08-10T00:00:00.000Z"
        )


class TestShortfallCureWindowAndEscalation:
    """The cure window closes on its deadline instant, not before it."""

    def _frozen_member_inside_its_cure_window(self, api):
        """A funded 10,000,000 advance, then the loan file goes missing."""
        env = member_with_eligible_sf(api)
        subscribe_and_issue(api, env.member_id, 450_000, "ACTIVITY")
        product = create_product(api)
        advance = funded_advance(
            api,
            env,
            product["id"],
            term_days=30,
            requested_net_proceeds_cents=10_000_000,
            fund_stock_from_advance=False,
        )
        amend_documentation(
            api, env.assets["sf"]["id"], documentation_status="MISSING"
        )
        return env, advance

    def test_escalation_is_premature_while_the_cure_window_is_open(self, api):
        """PRD §3.9: "A `CreditOfficer` escalates only after the cure period has run out:
        while `shortfall_status` is `OPEN` and the logical clock is still at or before
        `shortfall_cure_deadline`, escalation is premature and rejected with
        `ERR_SHORTFALL_CURE_PERIOD_ACTIVE`."

        Design: Corner/state_machines/escalate_shortfall_during_cure_period_rejected
        """
        env, _advance = self._frozen_member_inside_its_cure_window(api)

        response = api.escalate_shortfall(env.member_id, CREDIT_ONE)

        validate_error(response, "ERR_SHORTFALL_CURE_PERIOD_ACTIVE", 409)
        member = env.refresh()
        assert_shortfall(
            member,
            "OPEN",
            10_200_000,
            shortfall_opened_at="2026-08-01T00:00:00.000Z",
            shortfall_cure_deadline="2026-08-06T00:00:00.000Z",
        )
        assert_fields(member, membership_status="ACTIVE", collateral_posture="FROZEN")
        assert member["delivery_required"] is False

    def test_the_deadline_instant_is_still_inside_the_window(self, api):
        """PRD §3.9: "while `shortfall_status` is `OPEN` and the logical clock is still at
        or before `shortfall_cure_deadline`, escalation is premature and rejected with
        `ERR_SHORTFALL_CURE_PERIOD_ACTIVE`."

        Design: Corner/state_machines/escalate_shortfall_during_cure_period_rejected
        """
        env, _advance = self._frozen_member_inside_its_cure_window(api)
        pin_clock(api, "2026-08-06T00:00:00Z")

        refused = api.escalate_shortfall(env.member_id, CREDIT_ONE)

        validate_error(refused, "ERR_SHORTFALL_CURE_PERIOD_ACTIVE", 409)
        assert_shortfall(env.refresh(), "OPEN", 10_200_000)

    def test_escalation_past_the_deadline_probates_the_member_and_demands_the_files(self, api):
        """PRD §3.9: "Once the deadline has passed, `shortfall_status` moves `OPEN →
        ESCALATED`, `membership_status` moves `ACTIVE → PROBATION`, `collateral_posture`
        stays `FROZEN`, and `delivery_required` becomes true — the Bank now wants the
        physical files."

        Design: Corner/state_machines/shortfall_escalation_moves_member_to_probation_and_forces_delivery
        """
        env, advance = self._frozen_member_inside_its_cure_window(api)
        pin_clock(api, "2026-08-07T00:00:00Z")

        member = assert_envelope(api.escalate_shortfall(env.member_id, CREDIT_ONE))

        assert_fields(
            member,
            shortfall_status="ESCALATED",
            membership_status="PROBATION",
            collateral_posture="FROZEN",
        )
        assert member["delivery_required"] is True
        assert member["shortfall_required_cure_cents"] == 10_200_000
        after = read_advance(api, advance["id"])
        assert after["credit_status"] == "FUNDED"
        assert after["outstanding_principal_cents"] == 10_000_000
