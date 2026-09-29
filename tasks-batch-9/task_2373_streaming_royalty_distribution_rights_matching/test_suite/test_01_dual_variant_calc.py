"""Variant-selected calculations of the streaming royalty distribution API.

Three calculations in this API each have two legal shapes chosen by something
other than the stored rows: pool attribution's denominator (chosen by the
logical clock against the claim window), a statement line's administration fee
(chosen by the producing registration's routing), and usage matching's
acceptance threshold (7,500 for the batch run, 5,000 for the claim-mode run
inside the approval cascade).
"""

from test_helpers import (
    TEST_USERS,
    append_line,
    assert_play_count_conservation,
    assert_pool_value_conservation,
    assert_statement_totals,
    calculate_pool,
    create_batch,
    create_collective,
    create_composition,
    create_effective_schedule,
    create_label,
    create_period,
    create_pool,
    create_publisher,
    create_recording,
    create_statement,
    file_and_approve_registration,
    file_registration_under_review,
    finalize_pool,
    seal_and_match_batch,
    set_clock,
    setup_canonical_pool_calculated,
    statement_lines,
    validate_success,
)

ADMIN_HEADERS = TEST_USERS["royalty_admin_headers"]
ANALYST_HEADERS = TEST_USERS["rights_ops_analyst_headers"]
REVIEWER_HEADERS = TEST_USERS["reviewer_headers"]

CLOCK_AFTER_CLAIM_WINDOW = "2026-08-30T00:00:00Z"


# ─────────────────────────────────────────────────────
# Composite preambles this module needs and fixtures.py does not carry
# ─────────────────────────────────────────────────────

def _setup_dual_routing_performance_statements(api):
    """One period whose GB and IE usage funds two PERFORMANCE lines of identical
    gross, one routed COLLECTIVE and one routed DIRECT.

    A GB/INDIVIDUAL schedule and an identically-valued WORLD/INDIVIDUAL fallback
    are brought into force, one batch reports 300000/150000/50000 plays in GB and
    the same three figures in IE, the master claim and a GB mechanical claim are
    approved, and the two PERFORMANCE claims over the same composition — GB via
    the collective, IE direct to the claimant — are approved as well. Both pools
    are calculated at the default clock and finalized, then the collective's and
    the claimant publisher's draft statements are built.
    """
    fixture = {}
    fixture["label"] = create_label(api)
    fixture["mechanical_publisher"] = create_publisher(
        api, legal_name="Harbourline Publishing", territory="GB"
    )
    fixture["performance_publisher"] = create_publisher(
        api, legal_name="Tidewater Songs", territory="GB", rate_bps=800
    )
    fixture["collective"] = create_collective(api)

    fixture["schedule_gb"] = create_effective_schedule(api)
    fixture["schedule_world"] = create_effective_schedule(
        api, territory_code="WORLD", proceeding_ref="CRB-2026-01-WORLD"
    )

    fixture["period"] = create_period(api)
    fixture["composition"] = create_composition(api)
    fixture["recording"] = create_recording(
        api, linked_work_id=fixture["composition"]["id"]
    )

    batch = create_batch(api, fixture["period"]["id"])
    fixture["batch"] = batch
    lines = {}
    for prefix, territory in (("gb", "GB"), ("ie", "IE")):
        lines[f"{prefix}_exact_large"] = append_line(
            api,
            batch["id"],
            reported_isrc=fixture["recording"]["identifier"],
            reported_title=fixture["recording"]["title"],
            reported_artist=fixture["recording"]["artist_credit"],
            territory_code=territory,
            subscription_tier="INDIVIDUAL",
            play_count=300000,
        )
        lines[f"{prefix}_exact_small"] = append_line(
            api,
            batch["id"],
            reported_isrc=fixture["recording"]["identifier"],
            reported_title=fixture["recording"]["title"],
            reported_artist=fixture["recording"]["artist_credit"],
            territory_code=territory,
            subscription_tier="INDIVIDUAL",
            play_count=150000,
        )
        lines[f"{prefix}_unresolved"] = append_line(
            api,
            batch["id"],
            reported_title="Neon Ledger",
            territory_code=territory,
            subscription_tier="INDIVIDUAL",
            play_count=50000,
        )
    fixture["usage_lines"] = lines
    fixture["batch_after_match"] = seal_and_match_batch(api, batch["id"])

    fixture["master_registration"] = file_and_approve_registration(
        api,
        fixture["recording"]["id"],
        fixture["label"]["id"],
        right_type="MASTER",
        routing="DIRECT",
        share_bps=10000,
        territory_set=["WORLD"],
    )
    fixture["mechanical_registration"] = file_and_approve_registration(
        api,
        fixture["composition"]["id"],
        fixture["mechanical_publisher"]["id"],
        right_type="MECHANICAL",
        routing="COLLECTIVE",
        collective_id=fixture["collective"]["id"],
        share_bps=6000,
        territory_set=["GB"],
    )
    fixture["collective_performance_registration"] = file_and_approve_registration(
        api,
        fixture["composition"]["id"],
        fixture["performance_publisher"]["id"],
        right_type="PERFORMANCE",
        routing="COLLECTIVE",
        collective_id=fixture["collective"]["id"],
        share_bps=10000,
        territory_set=["GB"],
    )
    fixture["direct_performance_registration"] = file_and_approve_registration(
        api,
        fixture["composition"]["id"],
        fixture["performance_publisher"]["id"],
        right_type="PERFORMANCE",
        routing="DIRECT",
        share_bps=10000,
        territory_set=["IE"],
    )

    pool_gb = create_pool(api, fixture["period"]["id"], territory_code="GB")
    pool_ie = create_pool(api, fixture["period"]["id"], territory_code="IE")
    fixture["pool_gb"] = calculate_pool(api, pool_gb["id"])
    fixture["pool_ie"] = calculate_pool(api, pool_ie["id"])
    fixture["pool_gb"] = finalize_pool(api, pool_gb["id"])
    fixture["pool_ie"] = finalize_pool(api, pool_ie["id"])

    fixture["statement_collective"] = create_statement(
        api, fixture["collective"]["id"], fixture["period"]["id"]
    )
    fixture["statement_publisher"] = create_statement(
        api, fixture["performance_publisher"]["id"], fixture["period"]["id"]
    )
    return fixture


def _setup_title_only_claim_under_review(api):
    """A sealed and matched batch whose single line agrees with a catalogued
    recording on title alone, plus that recording's master claim in UNDER_REVIEW.

    The line reports 'Neon Ledger' with neither an ISRC nor an artist, so only
    the title-only rung can fire and the batch run leaves the line unattached.
    One approve then drives the claim-mode re-match over it.
    """
    fixture = {}
    fixture["label"] = create_label(api)
    fixture["period"] = create_period(api)
    fixture["recording"] = create_recording(
        api, identifier="GBABC2600002", title="Neon Ledger", artist="Halfsleep"
    )
    batch = create_batch(api, fixture["period"]["id"])
    fixture["batch"] = batch
    fixture["usage_line"] = append_line(
        api,
        batch["id"],
        reported_title="Neon Ledger",
        territory_code="GB",
        subscription_tier="INDIVIDUAL",
        play_count=50000,
    )
    fixture["batch_after_match"] = seal_and_match_batch(api, batch["id"])
    fixture["registration"] = file_registration_under_review(
        api,
        fixture["recording"]["id"],
        fixture["label"]["id"],
        right_type="MASTER",
        routing="DIRECT",
        share_bps=10000,
        territory_set=["WORLD"],
    )
    return fixture


# ─────────────────────────────────────────────────────
# pool_attribution_denominator_variant_divergence
# ─────────────────────────────────────────────────────

class TestPoolAttributionDenominatorVariant:

    def test_all_usage_denominator_funds_the_holding_account(self, api):
        """A pool calculated while the claim window is still open spreads its distributable amount over all 500000 reported plays, so the unmatched line takes 99999 cents into the holding account.

        PRD: "While the current instant is at or before the period's `claim_window_closes_at`, `denominator_basis` is `ALL_USAGE` and `denominator_play_count` is the pool's `total_play_count`; once the current instant has passed `claim_window_closes_at`, `denominator_basis` is `MATCHED_ONLY` and `denominator_play_count` is the sum of `play_count` over in-scope lines whose `match_status` is `AUTO_MATCHED` or `CLAIM_MATCHED`."

        Design: Difficulty/dual_variant_calc/pool_attribution_denominator_variant_divergence
        """
        fixture = setup_canonical_pool_calculated(api)
        pool = fixture["pool"]

        assert pool["denominator_basis"] == "ALL_USAGE"
        assert pool["denominator_basis"] != "MATCHED_ONLY"
        assert pool["total_play_count"] == 500000
        assert pool["denominator_play_count"] == 500000
        assert pool["denominator_play_count"] != 450000
        assert pool["distributable_cents"] == 999999

        exact, fuzzy, unresolved = fixture["usage_lines"]
        exact_line = validate_success(api.get_usage_line(exact["id"], ANALYST_HEADERS), 200)
        fuzzy_line = validate_success(api.get_usage_line(fuzzy["id"], ANALYST_HEADERS), 200)
        unresolved_line = validate_success(
            api.get_usage_line(unresolved["id"], ANALYST_HEADERS), 200
        )

        assert exact_line["attributed_revenue_cents"] == 599999
        assert exact_line["attributed_revenue_cents"] != 666666
        assert fuzzy_line["attributed_revenue_cents"] == 299999
        assert fuzzy_line["attributed_revenue_cents"] != 333333
        assert unresolved_line["match_status"] == "UNMATCHED"
        assert unresolved_line["attributed_revenue_cents"] == 99999
        assert unresolved_line["attributed_revenue_cents"] != 0

        assert pool["matched_attributed_cents"] == 899998
        assert pool["holding_cents"] == 99999
        assert pool["rounding_residual_cents"] == 2
        assert_pool_value_conservation(pool)

    def test_matched_only_denominator_zeroes_the_unmatched_line(self, api):
        """Recalculating the identical stored usage once the claim window has closed switches the denominator to the 450000 matched plays, pays the unmatched line exactly 0 and empties the holding account.

        PRD: "The consequence of the two denominator variants is worth stating plainly: under `ALL_USAGE` the unmatched and disputed lines receive a positive attribution that funds the holding account, whereas under `MATCHED_ONLY` they receive exactly 0, `holding_cents` becomes 0, and their value is redistributed across the matched lines by the smaller denominator, so identical stored usage yields a strictly larger `attributed_revenue_cents` on every matched line."

        Design: Difficulty/dual_variant_calc/pool_attribution_denominator_variant_divergence
        """
        fixture = setup_canonical_pool_calculated(api)
        set_clock(api, CLOCK_AFTER_CLAIM_WINDOW)
        pool = calculate_pool(api, fixture["pool"]["id"])

        assert pool["denominator_basis"] == "MATCHED_ONLY"
        assert pool["denominator_basis"] != "ALL_USAGE"
        assert pool["total_play_count"] == 500000
        assert pool["denominator_play_count"] == 450000
        assert pool["denominator_play_count"] != 500000
        assert pool["distributable_cents"] == 999999

        exact, fuzzy, unresolved = fixture["usage_lines"]
        exact_line = validate_success(api.get_usage_line(exact["id"], ANALYST_HEADERS), 200)
        fuzzy_line = validate_success(api.get_usage_line(fuzzy["id"], ANALYST_HEADERS), 200)
        unresolved_line = validate_success(
            api.get_usage_line(unresolved["id"], ANALYST_HEADERS), 200
        )

        assert exact_line["attributed_revenue_cents"] == 666666
        assert exact_line["attributed_revenue_cents"] != 599999
        assert fuzzy_line["attributed_revenue_cents"] == 333333
        assert fuzzy_line["attributed_revenue_cents"] != 299999
        assert unresolved_line["match_status"] == "UNMATCHED"
        assert unresolved_line["attributed_revenue_cents"] == 0
        assert unresolved_line["attributed_revenue_cents"] != 99999

        assert pool["matched_attributed_cents"] == 999999
        assert pool["holding_cents"] == 0
        assert pool["rounding_residual_cents"] == 0
        assert_pool_value_conservation(pool)

    def test_matched_line_attribution_delta_between_the_two_variants(self, api):
        """The same 300000-play line attributed under both denominators differs by exactly 66667 cents, because only the divisor changed.

        PRD: "Every other line receives `distributable_cents` multiplied by its own `play_count`, divided by `denominator_play_count`, rounded **down** to a whole cent."

        Design: Difficulty/dual_variant_calc/pool_attribution_denominator_variant_divergence
        """
        fixture = setup_canonical_pool_calculated(api)
        exact = fixture["usage_lines"][0]

        all_usage_line = validate_success(
            api.get_usage_line(exact["id"], ANALYST_HEADERS), 200
        )
        assert all_usage_line["attributed_revenue_cents"] == 599999

        set_clock(api, CLOCK_AFTER_CLAIM_WINDOW)
        calculate_pool(api, fixture["pool"]["id"])
        matched_only_line = validate_success(
            api.get_usage_line(exact["id"], ANALYST_HEADERS), 200
        )
        assert matched_only_line["attributed_revenue_cents"] == 666666

        delta = (
            matched_only_line["attributed_revenue_cents"]
            - all_usage_line["attributed_revenue_cents"]
        )
        assert delta == 66667
        assert matched_only_line["play_count"] == all_usage_line["play_count"] == 300000


# ─────────────────────────────────────────────────────
# admin_fee_routing_variant_divergence
# ─────────────────────────────────────────────────────

class TestAdminFeeRoutingVariant:

    def test_collective_routed_line_draws_the_volume_tiered_rate(self, api):
        """A PERFORMANCE line of 135000 gross routed COLLECTIVE draws the 900 basis point band, so its fee is 12150 cents and its net is 122850.

        PRD: "On a line whose `routing` is `COLLECTIVE`, the rate is 1,200 basis points while `gross_cents` is below 100,000 cents, 900 basis points while `gross_cents` is below 1,000,000 cents, and 600 basis points otherwise."

        Design: Difficulty/dual_variant_calc/admin_fee_routing_variant_divergence
        """
        fixture = _setup_dual_routing_performance_statements(api)

        assert fixture["pool_gb"]["applied_rate_schedule_id"] == fixture["schedule_gb"]["id"]
        assert fixture["pool_gb"]["distributable_cents"] == 999999

        lines = statement_lines(
            api, fixture["statement_collective"]["id"], right_type="PERFORMANCE"
        )
        assert len(lines) == 1
        line = lines[0]

        assert line["routing"] == "COLLECTIVE"
        assert line["gross_cents"] == 135000
        assert line["admin_fee_cents"] == 12150
        assert line["admin_fee_cents"] != 10800
        assert line["net_cents"] == 122850
        assert line["net_cents"] != 124200
        assert line["payee_holder_id"] == fixture["collective"]["id"]
        assert line["share_bps"] == 10000
        assert line["work_id"] == fixture["composition"]["id"]

    def test_direct_routed_line_draws_the_flat_direct_deal_rate(self, api):
        """A PERFORMANCE line of the same 135000 gross routed DIRECT draws the payee's flat 800 basis point deal rate, so its fee is 10800 cents and its net is 124200.

        PRD: "On a line whose `routing` is `DIRECT`, the rate is instead the flat `direct_deal_rate_bps` of the payee holder, regardless of volume."

        Design: Difficulty/dual_variant_calc/admin_fee_routing_variant_divergence
        """
        fixture = _setup_dual_routing_performance_statements(api)

        assert fixture["pool_ie"]["applied_rate_schedule_id"] == fixture["schedule_world"]["id"]
        assert fixture["pool_ie"]["applied_rate_schedule_id"] != fixture["schedule_gb"]["id"]
        assert fixture["pool_ie"]["distributable_cents"] == 999999

        lines = statement_lines(
            api, fixture["statement_publisher"]["id"], right_type="PERFORMANCE"
        )
        assert len(lines) == 1
        line = lines[0]

        assert line["routing"] == "DIRECT"
        assert line["gross_cents"] == 135000
        assert line["admin_fee_cents"] == 10800
        assert line["admin_fee_cents"] != 12150
        assert line["net_cents"] == 124200
        assert line["net_cents"] != 122850
        assert line["payee_holder_id"] == fixture["performance_publisher"]["id"]
        assert line["share_bps"] == 10000
        assert line["work_id"] == fixture["composition"]["id"]

    def test_the_two_routings_diverge_in_both_amount_and_recipient(self, api):
        """On identical gross the two routings send 1350 cents more of fee and the whole net to different holders, and each statement header aggregates only its own lines.

        PRD: "The two routings therefore differ in both the amount and the recipient of the money: a collective-administered share is paid to the registration's `collective_id` at a volume-tiered rate, while a direct-deal share is paid to the `claimant_id` at a flat rate, and on identical gross amounts the nets diverge whenever `direct_deal_rate_bps` differs from the applicable band."

        Design: Difficulty/dual_variant_calc/admin_fee_routing_variant_divergence
        """
        fixture = _setup_dual_routing_performance_statements(api)

        collective_perf = statement_lines(
            api, fixture["statement_collective"]["id"], right_type="PERFORMANCE"
        )[0]
        direct_perf = statement_lines(
            api, fixture["statement_publisher"]["id"], right_type="PERFORMANCE"
        )[0]

        assert collective_perf["gross_cents"] == direct_perf["gross_cents"] == 135000
        assert collective_perf["admin_fee_cents"] - direct_perf["admin_fee_cents"] == 1350
        assert collective_perf["payee_holder_id"] == fixture["collective"]["id"]
        assert direct_perf["payee_holder_id"] == fixture["performance_publisher"]["id"]
        assert collective_perf["payee_holder_id"] != direct_perf["payee_holder_id"]

        collective_lines = statement_lines(api, fixture["statement_collective"]["id"])
        assert fixture["statement_collective"]["gross_cents"] == 189000
        assert fixture["statement_collective"]["admin_fee_cents"] == 18630
        assert fixture["statement_collective"]["net_payable_cents"] == 170370
        assert fixture["statement_collective"]["line_count"] == 2
        assert_statement_totals(fixture["statement_collective"], collective_lines)

        publisher_lines = statement_lines(api, fixture["statement_publisher"]["id"])
        assert fixture["statement_publisher"]["gross_cents"] == 135000
        assert fixture["statement_publisher"]["admin_fee_cents"] == 10800
        assert fixture["statement_publisher"]["net_payable_cents"] == 124200
        assert fixture["statement_publisher"]["line_count"] == 1
        assert_statement_totals(fixture["statement_publisher"], publisher_lines)


# ─────────────────────────────────────────────────────
# usage_matching_threshold_variant_divergence
# ─────────────────────────────────────────────────────

class TestUsageMatchingThresholdVariant:

    def test_batch_run_refuses_the_title_only_agreement(self, api):
        """The batch matching run scores the title-only agreement at 5000 basis points and refuses to attach it, leaving work_id null and match_status UNMATCHED.

        PRD: "When the score is below 7,500 — in practice a title-only agreement scoring 5,000 — the line is **not** attached: `work_id` stays null and `match_status` stays `UNMATCHED`, but the line still records the best score it achieved, so a later claim can see how close the catalogue came."

        Design: Difficulty/dual_variant_calc/usage_matching_threshold_variant_divergence
        """
        fixture = _setup_title_only_claim_under_review(api)

        line = validate_success(
            api.get_usage_line(fixture["usage_line"]["id"], ANALYST_HEADERS), 200
        )
        assert line["match_confidence_bps"] == 5000
        assert line["match_status"] == "UNMATCHED"
        assert line["match_status"] != "AUTO_MATCHED"
        assert line["work_id"] is None
        assert line["work_id"] != fixture["recording"]["id"]

    def test_claim_mode_run_accepts_the_same_title_only_agreement(self, api):
        """The approval cascade re-scores the very same line at the same 5000 basis points and does attach it, moving it to CLAIM_MATCHED against the newly approved recording.

        PRD: "Then the service re-runs the matcher in claim mode over unattached usage: every usage line whose `work_id` is still null, whose batch belongs to a period where the current instant is at or before `claim_window_closes_at`, and whose best score against **this newly approved work alone** is at least 5,000, takes `work_id` from that work, records that score in `match_confidence_bps`, and moves to `match_status` `CLAIM_MATCHED`."

        Design: Difficulty/dual_variant_calc/usage_matching_threshold_variant_divergence
        """
        fixture = _setup_title_only_claim_under_review(api)

        approved = validate_success(
            api.approve_rights_registration(
                fixture["registration"]["id"], REVIEWER_HEADERS
            ),
            200,
        )
        assert approved["status"] == "APPROVED"

        line = validate_success(
            api.get_usage_line(fixture["usage_line"]["id"], ANALYST_HEADERS), 200
        )
        assert line["match_confidence_bps"] == 5000
        assert line["match_status"] == "CLAIM_MATCHED"
        assert line["match_status"] != "UNMATCHED"
        assert line["match_status"] != "AUTO_MATCHED"
        assert line["work_id"] == fixture["recording"]["id"]

    def test_claim_mode_attachment_promotes_the_batch(self, api):
        """The plays the batch run left unmatched move into matched_play_count when the claim-mode run attaches them, promoting the batch from PARTIALLY_MATCHED to MATCHED.

        PRD: "Every affected usage batch recomputes `matched_play_count` and `unmatched_play_count`, and any batch whose `unmatched_play_count` has reached 0 moves `PARTIALLY_MATCHED → MATCHED`, which in turn lets the parent period re-evaluate its `OPEN → USAGE_SEALED` bubble-up."

        Design: Difficulty/dual_variant_calc/usage_matching_threshold_variant_divergence
        """
        fixture = _setup_title_only_claim_under_review(api)

        before = fixture["batch_after_match"]
        assert before["status"] == "PARTIALLY_MATCHED"
        assert before["total_play_count"] == 50000
        assert before["matched_play_count"] == 0
        assert before["unmatched_play_count"] == 50000
        assert_play_count_conservation(before)

        validate_success(
            api.approve_rights_registration(
                fixture["registration"]["id"], REVIEWER_HEADERS
            ),
            200,
        )

        after = validate_success(
            api.get_usage_batch(fixture["batch"]["id"], ADMIN_HEADERS), 200
        )
        assert after["status"] == "MATCHED"
        assert after["status"] != "PARTIALLY_MATCHED"
        assert after["total_play_count"] == 50000
        assert after["matched_play_count"] == 50000
        assert after["unmatched_play_count"] == 0
        assert after["disputed_play_count"] == 0
        assert_play_count_conservation(after)
