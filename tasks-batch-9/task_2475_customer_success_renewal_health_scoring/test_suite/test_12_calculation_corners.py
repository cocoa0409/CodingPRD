"""Corner cases of the health, adoption, support, executive and qualification formulas.

Every literal below was re-derived from the PRD formulas with decimal arithmetic
and ROUND_HALF_UP at exactly the rounding points the PRD pins.
"""

from test_helpers import (
    ENGAGEMENT_HELD,
    ENGAGEMENT_TYPE_EBR,
    HEALTH_AMBER,
    HEALTH_GREEN,
    HEALTH_RED,
    LIKELIHOOD_UPSIDE,
    OPPORTUNITY_IDENTIFIED,
    OUTCOME_HELD,
    SEVERITY_S1,
    EXECUTIVE_HEADERS,
    ApiClient,
    add_buyer_sponsor,
    add_sponsor,
    add_support_signal,
    add_usage_signal,
    assert_created,
    assert_field,
    assert_ok,
    assert_page,
    assert_score,
    assert_scores,
    create_account,
    create_csm,
    factories,
    read_account,
    read_health_summary,
    recompute_health,
    schedule_engagement,
    OPS_ADMIN_HEADERS,
)


class TestUsageRowPrecision:
    """Half-up rounding on a usage row and its propagation into the health scores."""

    def test_seat_utilisation_and_usage_row_index_round_half_up(
        self, api: ApiClient, clock: str
    ) -> None:
        """489 of 4,000 seats is exactly 12.225 percent and must render 12.23.

        PRD §2.6: "All non-integer arithmetic is performed with decimal arithmetic — never binary floating point — and every rounding step uses **round half up**."
        PRD §3.2: "`seat_utilisation_pct` is 0.00 when `licensed_seats` is 0; otherwise it is `weekly_active_users` divided by `licensed_seats`, multiplied by 100, capped at 100.00 so an over-provisioned population cannot exceed the ceiling, and rounded half up to two decimal places."
        PRD §3.2: "`usage_row_index` blends utilisation and breadth: 0.60 of `seat_utilisation_pct` plus 0.40 of `feature_depth_pct`, rounded half up to two decimal places."
        PRD §3.2: "`adoption_index` is the sum of each row's `usage_row_index` multiplied by its weight, divided by the sum of **only the weights actually used**, rounded half up to two decimal places once after the division."
        PRD §3.2: "A usage row recomputes `adoption_index`; a support row recomputes `support_risk_penalty`; and either kind then recomputes both health variants, re-derives `health_tier`, recomputes `renewal_likelihood` and recomputes `coverage_posture`."
        PRD §3.2: "With no ticket in the window, `support_risk_penalty` is 0.00."
        PRD §3.2: "Each variant is then 0.35 of its adoption term plus 0.25 of the support component plus 0.15 of the executive term plus 0.25 of the outcome term, rounded half up to two decimal places once after the entire weighted sum."
        PRD §3.3: "An account with no engagements and no active economic buyer scores 25.00; with an active economic buyer and still no engagements it scores 50.00; one held `QBR` with a `CXO` sponsor who is that active buyer brings it to 65.00; and four held `CXO` engagements, whose uncapped senior credit of 60.00 is trimmed to 45.00, bring it to 95.00."
        PRD §3.3: "When the input set is empty, `outcome_attainment_index` takes the substitute value 60.00 rather than 0.00, so that an account which has simply not yet defined its goals is not punished as though it had missed them."
        PRD §3.2: "`health_tier` is derived from `snapshot_health_score` **only**: the tier is `RED` when `snapshot_health_score` is below 50.00, `AMBER` when it is at least 50.00 and below 75.00, and `GREEN` when it is at least 75.00."

        Design: Corner/calculations/seat_utilisation_and_usage_row_index_round_half_up_to_two_decimals
        """
        csm = create_csm(api)
        account = create_account(api)

        signal = add_usage_signal(
            api,
            account["id"],
            csm["id"],
            period_end_date="2026-07-31",
            weekly_active_users=489,
            licensed_seats=4000,
            feature_depth_pct=0.00,
        )

        # 489 / 4000 * 100 = 12.225 exactly; half up on the hundredth gives 12.23.
        assert_score(signal["seat_utilisation_pct"], 12.23, "seat_utilisation_pct")
        # 0.60 * 12.23 + 0.40 * 0.00 = 7.338, which rounds half up to 7.34.
        assert_score(signal["usage_row_index"], 7.34, "usage_row_index")

        updated = read_account(api, account["id"])
        # A lone usage row renormalises by the 0.50 weight actually used, so the
        # index equals that row's own 7.34 rather than half of it.
        assert_score(updated["adoption_index"], 7.34, "adoption_index")
        # 0.35 * 7.34 + 0.25 * 100.00 + 0.15 * 25.00 + 0.25 * 60.00 = 46.319 -> 46.32.
        assert_scores(
            updated,
            {"snapshot_health_score": 46.32, "trended_health_score": 46.32},
        )
        assert_field(updated, "health_tier", HEALTH_RED)


class TestAdoptionInputSet:
    """The trailing-three input set of the account adoption figure."""

    def test_fourth_oldest_usage_row_is_excluded_from_adoption(
        self, api: ApiClient, clock: str
    ) -> None:
        """A fourth row written last but dated oldest leaves `adoption_index` at 67.00.

        PRD §3.2: "The input set is the three most recent usage rows of the account, ordered by `period_end_date` descending with `created_at` ascending as the only tie-break; support rows are excluded, and any usage row beyond the third-most-recent is excluded entirely."
        PRD §3.2: "The newest of those rows is weighted 0.50, the second 0.30 and the third 0.20."
        PRD §3.2: "`adoption_index` is the sum of each row's `usage_row_index` multiplied by its weight, divided by the sum of **only the weights actually used**, rounded half up to two decimal places once after the division."
        PRD §3.2: "For the point-in-time view the adoption term is the `usage_row_index` of the single most recent usage row (again `period_end_date` descending, `created_at` ascending as tie-break), or 0.00 when the account has no usage row at all."
        PRD §3.2: "For the trailing view the adoption term is `adoption_index`, the recency-weighted mean over the trailing three usage rows."
        PRD §3.2: "With no ticket in the window, `support_risk_penalty` is 0.00."
        PRD §3.3: "An account with no engagements and no active economic buyer scores 25.00; with an active economic buyer and still no engagements it scores 50.00; one held `QBR` with a `CXO` sponsor who is that active buyer brings it to 65.00; and four held `CXO` engagements, whose uncapped senior credit of 60.00 is trimmed to 45.00, bring it to 95.00."
        PRD §3.3: "When the input set is empty, `outcome_attainment_index` takes the substitute value 60.00 rather than 0.00, so that an account which has simply not yet defined its goals is not punished as though it had missed them."
        PRD §3.2: "Each variant is then 0.35 of its adoption term plus 0.25 of the support component plus 0.15 of the executive term plus 0.25 of the outcome term, rounded half up to two decimal places once after the entire weighted sum."
        PRD §3.2: "For inspection there is a read-only health projection that adds no state of its own and exposes the model's internals side by side: `adoption_index`, `support_component` (the complement of `support_risk_penalty`), `exec_engagement_score`, `outcome_attainment_index`, `snapshot_health_score`, `trended_health_score`, `variant_delta` (the point-in-time figure minus the trailing figure), `health_tier`, and `usage_rows_considered` (the number of usage rows the adoption calculation actually used, which is the smaller of 3 and the account's usage-row count)."
        PRD §2.4: "They have **no** `updated_at` field and **no** `version` field, because a signal row is immutable once written: there is no endpoint that edits or deletes one, and the server never rewrites the input fields of a signal after creation."

        Design: Corner/calculations/adoption_index_excludes_the_fourth_oldest_usage_row
        """
        csm = create_csm(api)
        account = create_account(api)

        for period_end_date, weekly_active_users, feature_depth_pct in (
            ("2026-05-31", 40, 30.00),
            ("2026-06-30", 60, 50.00),
            ("2026-07-31", 90, 80.00),
        ):
            add_usage_signal(
                api,
                account["id"],
                csm["id"],
                period_end_date=period_end_date,
                weekly_active_users=weekly_active_users,
                licensed_seats=100,
                feature_depth_pct=feature_depth_pct,
            )

        # Written last, but its period closed before all three others.
        oldest = add_usage_signal(
            api,
            account["id"],
            csm["id"],
            period_end_date="2026-04-30",
            weekly_active_users=100,
            licensed_seats=100,
            feature_depth_pct=90.00,
        )
        # 0.60 * 100.00 + 0.40 * 90.00 = 96.00: the row itself is scored.
        assert_score(oldest["usage_row_index"], 96.00, "usage_row_index")

        summary = read_health_summary(api, account["id"])
        assert_field(summary, "usage_rows_considered", 3)
        # 0.50 * 86.00 + 0.30 * 56.00 + 0.20 * 36.00 = 67.00 over a denominator of 1.00.
        assert_score(summary["adoption_index"], 67.00, "adoption_index")
        # Point-in-time adoption term 86.00 gives 73.85; the trailing 67.00 gives 67.20.
        assert_scores(
            summary,
            {
                "snapshot_health_score": 73.85,
                "trended_health_score": 67.20,
                "variant_delta": 6.65,
            },
        )

        # The excluded row left the input set, not storage.
        rows = assert_page(
            api.list_signals(account["id"], OPS_ADMIN_HEADERS, {"limit": 100}),
            expected_total=4,
        )
        assert len(rows) == 4


class TestSupportPenaltyCap:
    """The support penalty is capped once, after summation over the window."""

    def test_support_risk_penalty_caps_at_forty_five_after_summation(
        self, api: ApiClient, clock: str
    ) -> None:
        """Five S1 tickets raise 60 raw points but the account penalty holds at 45.00.

        PRD §3.2: "Its `penalty_points` is an integer sum of three terms: a severity term worth 12 points for `S1`, 7 for `S2`, 3 for `S3` and 1 for `S4`; a further 5 points when `breached_sla` is true; and a further 4 points when `csat_score` is present and is at most 2."
        PRD §3.2: "The uncapped total is the sum of `penalty_points` across that set; `support_risk_penalty` is the smaller of 45.00 and that total, rendered with two decimal places."
        PRD §3.2: "The cap is applied once after summation and never per row, so five `S1` tickets with no SLA breaches and no CSAT scores produce an uncapped 60 points and a `support_risk_penalty` of 45.00."
        PRD §3.2: "The health model consumes the complement of this penalty, a figure this document calls the **support component**, equal to 100.00 minus `support_risk_penalty` — 55.00 in the capped example above, 100.00 for a clean account."
        PRD §3.2: "A usage row recomputes `adoption_index`; a support row recomputes `support_risk_penalty`; and either kind then recomputes both health variants, re-derives `health_tier`, recomputes `renewal_likelihood` and recomputes `coverage_posture`."
        PRD §3.2: "Each variant is then 0.35 of its adoption term plus 0.25 of the support component plus 0.15 of the executive term plus 0.25 of the outcome term, rounded half up to two decimal places once after the entire weighted sum."
        PRD §3.3: "An account with no engagements and no active economic buyer scores 25.00; with an active economic buyer and still no engagements it scores 50.00; one held `QBR` with a `CXO` sponsor who is that active buyer brings it to 65.00; and four held `CXO` engagements, whose uncapped senior credit of 60.00 is trimmed to 45.00, bring it to 95.00."
        PRD §3.3: "When the input set is empty, `outcome_attainment_index` takes the substitute value 60.00 rather than 0.00, so that an account which has simply not yet defined its goals is not punished as though it had missed them."
        PRD §3.2: "`health_tier` is derived from `snapshot_health_score` **only**: the tier is `RED` when `snapshot_health_score` is below 50.00, `AMBER` when it is at least 50.00 and below 75.00, and `GREEN` when it is at least 75.00."

        Design: Corner/calculations/support_risk_penalty_is_capped_at_forty_five_after_summation
        """
        csm = create_csm(api)
        account = create_account(api)
        add_usage_signal(
            api,
            account["id"],
            csm["id"],
            period_end_date="2026-07-31",
            weekly_active_users=90,
            licensed_seats=100,
            feature_depth_pct=80.00,
        )

        tickets = [
            add_support_signal(
                api,
                account["id"],
                csm["id"],
                opened_at="2026-07-15T09:00:00Z",
                ticket_severity=SEVERITY_S1,
            )
            for _ in range(5)
        ]
        # Each row keeps its own uncapped severity term.
        assert_field(tickets[0], "penalty_points", 12)
        assert_field(tickets[4], "penalty_points", 12)

        updated = read_account(api, account["id"])
        assert_score(
            updated["support_risk_penalty"], 45.00, "support_risk_penalty"
        )
        summary = read_health_summary(api, account["id"])
        assert_score(summary["support_component"], 55.00, "support_component")

        # 0.35 * 86.00 + 0.25 * 55.00 + 0.15 * 25.00 + 0.25 * 60.00 = 62.60.
        assert_scores(
            updated,
            {"snapshot_health_score": 62.60, "trended_health_score": 62.60},
        )
        assert_field(updated, "health_tier", HEALTH_AMBER)


class TestExecutiveEngagementCredit:
    """The executive component credits a held engagement with a senior sponsor."""

    def test_held_cxo_engagement_credits_fifteen_points(
        self, api: ApiClient, clock: str
    ) -> None:
        """One held CXO meeting takes the executive score to 65.00 and health to 49.75.

        PRD §3.3: "An outcome of `HELD` carries the engagement `SCHEDULED → HELD` and requires that the logical clock be at or after `start_at`."
        PRD §3.3: "Its input set is the account's engagements whose state is `HELD` or `NO_SHOW` and whose `start_at` falls strictly after the instant 180 days before the logical clock and at or before the logical clock; `SCHEDULED` and `CANCELLED` engagements are excluded."
        PRD §3.3: "The senior credit is 15.00 for each `HELD` engagement whose sponsor is a `CXO` or a `VP`, capped at 45.00."
        PRD §3.3: "A further buyer debit of 25.00 applies whenever the account has no sponsor contact with `is_economic_buyer` true and `status` `ACTIVE`, and is 0.00 otherwise."
        PRD §3.3: "`exec_engagement_score` is then 50.00 plus the senior credit plus the junior credit minus the no-show debit minus the buyer debit, clamped into the range 0.00 to 100.00 once, at the very end."
        PRD §3.3: "Both stamp `outcome_recorded_at` with the logical clock and then recompute `exec_engagement_score`, both health variants, `health_tier`, `renewal_likelihood` and `coverage_posture`."
        PRD §3.2: "An account with no usage row at all has `adoption_index` 0.00."
        PRD §3.2: "With no ticket in the window, `support_risk_penalty` is 0.00."
        PRD §3.3: "When the input set is empty, `outcome_attainment_index` takes the substitute value 60.00 rather than 0.00, so that an account which has simply not yet defined its goals is not punished as though it had missed them."
        PRD §3.2: "Each variant is then 0.35 of its adoption term plus 0.25 of the support component plus 0.15 of the executive term plus 0.25 of the outcome term, rounded half up to two decimal places once after the entire weighted sum."
        PRD §3.2: "`health_tier` is derived from `snapshot_health_score` **only**: the tier is `RED` when `snapshot_health_score` is below 50.00, `AMBER` when it is at least 50.00 and below 75.00, and `GREEN` when it is at least 75.00."

        Design: Corner/calculations/exec_engagement_score_credits_a_held_cxo_engagement
        """
        csm = create_csm(api)
        account = create_account(api)
        sponsor = add_sponsor(api, account["id"], csm["id"], full_name="Grace Chen")
        engagement = schedule_engagement(
            api,
            account["id"],
            csm["id"],
            sponsor["id"],
            "2026-07-20T15:00:00Z",
            "2026-07-20T16:00:00Z",
            engagement_type=ENGAGEMENT_TYPE_EBR,
        )

        held = assert_ok(
            api.record_engagement_outcome(
                engagement["id"],
                factories.engagement_outcome(OUTCOME_HELD),
                EXECUTIVE_HEADERS,
            )
        )
        assert_field(held, "state", ENGAGEMENT_HELD)

        updated = read_account(api, account["id"])
        # 50.00 base + 15.00 senior credit, with no no-show and no buyer debit.
        assert_score(
            updated["exec_engagement_score"], 65.00, "exec_engagement_score"
        )
        # 0.35 * 0.00 + 0.25 * 100.00 + 0.15 * 65.00 + 0.25 * 60.00 = 49.75.
        assert_scores(
            updated,
            {"snapshot_health_score": 49.75, "trended_health_score": 49.75},
        )
        # 49.75 sits a quarter point below the inclusive AMBER floor of 50.00.
        assert_field(updated, "health_tier", HEALTH_RED)


class TestHealthTierVariantSelection:
    """The tier reads the point-in-time variant even when the trailing one disagrees."""

    def test_health_tier_follows_the_snapshot_variant_only(
        self, api: ApiClient, clock: str, trending_account: dict
    ) -> None:
        """Snapshot 77.60 is GREEN while trailing 70.95 would read AMBER.

        PRD §3.2: "For the point-in-time view the adoption term is the `usage_row_index` of the single most recent usage row (again `period_end_date` descending, `created_at` ascending as tie-break), or 0.00 when the account has no usage row at all."
        PRD §3.2: "For the trailing view the adoption term is `adoption_index`, the recency-weighted mean over the trailing three usage rows."
        PRD §3.2: "The newest of those rows is weighted 0.50, the second 0.30 and the third 0.20."
        PRD §3.2: "With no ticket in the window, `support_risk_penalty` is 0.00."
        PRD §3.3: "When the input set is empty, `outcome_attainment_index` takes the substitute value 60.00 rather than 0.00, so that an account which has simply not yet defined its goals is not punished as though it had missed them."
        PRD §3.2: "Each variant is then 0.35 of its adoption term plus 0.25 of the support component plus 0.15 of the executive term plus 0.25 of the outcome term, rounded half up to two decimal places once after the entire weighted sum."
        PRD §3.2: "`health_tier` is derived from `snapshot_health_score` **only**: the tier is `RED` when `snapshot_health_score` is below 50.00, `AMBER` when it is at least 50.00 and below 75.00, and `GREEN` when it is at least 75.00."
        PRD §3.2: "`trended_health_score` is the **only** health figure that feeds `renewal_likelihood` and the expansion qualification score."
        PRD §3.2: "The server first computes the number of whole days from the logical clock date to the account's `contract_end_date`."
        PRD §3.2: "Otherwise, if `trended_health_score` is at least 75.00 and `open_save_play_count` is 0, the category is `COMMIT`."
        PRD §3.2: "Otherwise, if `trended_health_score` is at least 60.00 and the days-to-renewal figure is strictly greater than 60, the category is `UPSIDE`."
        PRD §3.3: "An account with no engagements and no active economic buyer scores 25.00; with an active economic buyer and still no engagements it scores 50.00; one held `QBR` with a `CXO` sponsor who is that active buyer brings it to 65.00; and four held `CXO` engagements, whose uncapped senior credit of 60.00 is trimmed to 45.00, bring it to 95.00."

        Design: Corner/calculations/health_tier_is_derived_from_the_snapshot_variant_only
        """
        state = add_buyer_sponsor(api, trending_account, full_name="Grace Chen")
        account = recompute_health(api, state["account_id"])

        # 0.35 * 86.00 + 0.25 * 100.00 + 0.15 * 50.00 + 0.25 * 60.00 = 77.60, while
        # the trailing adoption term of 67.00 gives 0.35 * 67.00 + 47.50 = 70.95.
        assert_scores(
            account,
            {"snapshot_health_score": 77.60, "trended_health_score": 70.95},
        )
        assert_field(account, "health_tier", HEALTH_GREEN)
        # Trailing 70.95 clears the 60.00 floor but not 75.00, and the term ends
        # 152 days after the clock date, which is strictly more than 60.
        assert_field(account, "renewal_likelihood", LIKELIHOOD_UPSIDE)

        summary = read_health_summary(api, state["account_id"])
        assert_score(summary["variant_delta"], 6.65, "variant_delta")


class TestQualificationScoreVariantSelection:
    """The qualification score reads the trailing health figure."""

    def test_qualification_score_uses_the_trended_variant(
        self, api: ApiClient, clock: str, trending_account: dict
    ) -> None:
        """The opportunity scores 67.58 from trailing 70.95, not 70.90 from snapshot 77.60.

        PRD §3.7: "The `qualification_score` is computed at the moment the row is written and is never refreshed afterwards, so it records the account's condition when the opportunity was raised."
        PRD §3.7: "A revenue term is the account's `arr_cents` divided by a normaliser of 50,000,000, multiplied by 100, rounded half up to two decimal places and then capped at 100.00 — so an account at or above 500,000 dollars of ARR saturates that term."
        PRD §3.7: "The score is 0.50 of the account's `trended_health_score`, plus 0.30 of its `adoption_index`, plus 0.20 of the revenue term, rounded half up to two decimal places."
        PRD §3.7: "The row is created in state `IDENTIFIED` with `identified_at` stamped from the logical clock, `recycled_from_opportunity_id` null, `handoff_ae_user_id` null and `rejection_reason` null."
        PRD §3.2: "`trended_health_score` is the **only** health figure that feeds `renewal_likelihood` and the expansion qualification score."
        PRD §3.2: "For the trailing view the adoption term is `adoption_index`, the recency-weighted mean over the trailing three usage rows."
        PRD §3.2: "The newest of those rows is weighted 0.50, the second 0.30 and the third 0.20."
        PRD §3.2: "`adoption_index` is the sum of each row's `usage_row_index` multiplied by its weight, divided by the sum of **only the weights actually used**, rounded half up to two decimal places once after the division."
        PRD §3.2: "With no ticket in the window, `support_risk_penalty` is 0.00."
        PRD §3.3: "An account with no engagements and no active economic buyer scores 25.00; with an active economic buyer and still no engagements it scores 50.00; one held `QBR` with a `CXO` sponsor who is that active buyer brings it to 65.00; and four held `CXO` engagements, whose uncapped senior credit of 60.00 is trimmed to 45.00, bring it to 95.00."
        PRD §3.3: "When the input set is empty, `outcome_attainment_index` takes the substitute value 60.00 rather than 0.00, so that an account which has simply not yet defined its goals is not punished as though it had missed them."
        PRD §3.2: "Each variant is then 0.35 of its adoption term plus 0.25 of the support component plus 0.15 of the executive term plus 0.25 of the outcome term, rounded half up to two decimal places once after the entire weighted sum."

        Design: Corner/calculations/qualification_score_uses_the_trended_variant_not_the_snapshot
        """
        state = add_buyer_sponsor(api, trending_account, full_name="Grace Chen")
        account = recompute_health(api, state["account_id"])
        assert_scores(
            account,
            {"snapshot_health_score": 77.60, "trended_health_score": 70.95},
        )

        response = api.create_expansion_opportunity(
            factories.expansion_opportunity(
                state["account_id"], estimated_value_cents=6_000_000
            ),
            state["csm_headers"],
        )
        opportunity = assert_created(response)

        # 0.50 * 70.95 + 0.30 * 67.00 + 0.20 * 60.00 = 67.575, which rounds to 67.58;
        # the point-in-time figure would have produced 70.90 instead.
        assert_score(
            opportunity["qualification_score"], 67.58, "qualification_score"
        )
        assert_field(opportunity, "state", OPPORTUNITY_IDENTIFIED)
