"""Boundary precision across the royalty chain.

The comparisons exercised here are the ones whose strictness or inclusivity the
PRD pins explicitly: the two match-confidence acceptance thresholds, the
allocation-basis tie between the revenue share and the per-subscriber minimum,
the claim window bound to the second, the per-territory aggregate share
ceiling, and the administration-fee tier ceilings.
"""

from test_helpers import (
    ADMIN,
    ADMIN_TIER_1_BPS,
    ADMIN_TIER_1_CEILING_CENTS,
    ADMIN_TIER_2_BPS,
    ANALYST,
    ANALYST_FUZZY_MATCHER_USER_ID,
    AUTO_MATCH_MIN_CONFIDENCE_BPS,
    CLAIM_MATCH_MIN_CONFIDENCE_BPS,
    MAX_SHARE_BPS_PER_TERRITORY,
    REVIEWER,
    TEST_DEFAULTS,
    ApiErrorId,
    append_line,
    approve_registration,
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
    file_registration,
    finalize_pool,
    get_success_data,
    make_rights_holder_user_headers,
    period_version,
    review_registration,
    rights_registration_payload,
    seal_and_match_batch,
    set_clock,
    statement_payload,
    validate_error,
    validate_paginated,
    validate_success,
    work_version,
)

CLAIM_WINDOW_CLOSES_AT = "2026-08-29T00:00:00Z"
ONE_SECOND_PAST_CLAIM_WINDOW = "2026-08-29T00:00:01Z"


# ─────────────────────────────────────────────────────
# Composite preambles
# ─────────────────────────────────────────────────────

def _setup_confidence_ladder_batch(api):
    """One sealed, matched GB/INDIVIDUAL batch whose three lines land on each
    rung of the confidence ladder: an exact ISRC hit, a title-and-artist
    agreement, and a title-only agreement."""
    fixture = {"label": create_label(api)}
    fixture["period"] = create_period(api)
    fixture["recording_a"] = create_recording(
        api,
        identifier=TEST_DEFAULTS["RECORDING_A_ISRC"],
        title=TEST_DEFAULTS["RECORDING_A_TITLE"],
        artist=TEST_DEFAULTS["RECORDING_A_ARTIST"],
    )
    fixture["recording_b"] = create_recording(
        api,
        identifier=TEST_DEFAULTS["RECORDING_B_ISRC"],
        title=TEST_DEFAULTS["RECORDING_B_TITLE"],
        artist=TEST_DEFAULTS["RECORDING_B_ARTIST"],
    )
    fixture["batch"] = create_batch(api, fixture["period"]["id"])
    batch_id = fixture["batch"]["id"]

    fixture["line_isrc_hit"] = append_line(
        api,
        batch_id,
        reported_isrc=TEST_DEFAULTS["RECORDING_A_ISRC"],
        reported_title="Wrong Title Entirely",
        territory_code="GB",
        subscription_tier="INDIVIDUAL",
        play_count=300000,
    )
    fixture["line_title_and_artist"] = append_line(
        api,
        batch_id,
        reported_title=TEST_DEFAULTS["MESSY_TITLE_A"],
        reported_artist=TEST_DEFAULTS["MESSY_ARTIST_A"],
        territory_code="GB",
        subscription_tier="INDIVIDUAL",
        play_count=150000,
    )
    fixture["line_title_only"] = append_line(
        api,
        batch_id,
        reported_title=TEST_DEFAULTS["RECORDING_B_TITLE"],
        territory_code="GB",
        subscription_tier="INDIVIDUAL",
        play_count=50000,
    )
    fixture["batch_after_match"] = seal_and_match_batch(api, batch_id)
    return fixture


def _setup_equal_candidate_pools(api):
    """Two GB pools on identical gross revenue whose only difference is one
    subscriber, so the revenue share equals the per-subscriber minimum exactly
    in one pool and falls one step short in the other."""
    fixture = {}
    fixture["schedule_family"] = create_effective_schedule(
        api,
        proceeding_ref="CRB-2026-FAM",
        territory_code="WORLD",
        subscription_tier="FAMILY",
        revenue_share_bps=7000,
        per_subscriber_minimum_cents=500,
        mechanical_share_bps=4000,
        performance_share_bps=6000,
        statutory_floor_per_play_millicents=100,
        effective_from="2026-01-01",
        effective_to="2026-12-31",
    )
    fixture["schedule_student"] = create_effective_schedule(
        api,
        proceeding_ref="CRB-2026-STU",
        territory_code="WORLD",
        subscription_tier="STUDENT",
        revenue_share_bps=7000,
        per_subscriber_minimum_cents=500,
        mechanical_share_bps=4000,
        performance_share_bps=6000,
        statutory_floor_per_play_millicents=100,
        effective_from="2026-01-01",
        effective_to="2026-12-31",
    )
    fixture["period"] = create_period(api)
    fixture["recording_a"] = create_recording(
        api,
        identifier=TEST_DEFAULTS["RECORDING_A_ISRC"],
        title=TEST_DEFAULTS["RECORDING_A_TITLE"],
        artist=TEST_DEFAULTS["RECORDING_A_ARTIST"],
    )
    fixture["batch"] = create_batch(api, fixture["period"]["id"])
    for tier in ("FAMILY", "STUDENT"):
        append_line(
            api,
            fixture["batch"]["id"],
            reported_isrc=TEST_DEFAULTS["RECORDING_A_ISRC"],
            reported_title=TEST_DEFAULTS["RECORDING_A_TITLE"],
            territory_code="GB",
            subscription_tier=tier,
            play_count=200000,
        )
    fixture["batch_after_match"] = seal_and_match_batch(api, fixture["batch"]["id"])

    fixture["pool_at_tie"] = create_pool(
        api,
        fixture["period"]["id"],
        territory_code="GB",
        subscription_tier="FAMILY",
        subscriber_count=1400,
        gross_revenue_cents=1000000,
    )
    fixture["pool_one_over"] = create_pool(
        api,
        fixture["period"]["id"],
        territory_code="GB",
        subscription_tier="STUDENT",
        subscriber_count=1401,
        gross_revenue_cents=1000000,
    )
    return fixture


def _setup_period_with_matched_usage_at_window_close(api):
    """A 2026-06 period whose single usage line matched a recording by exact
    ISRC, with the clock parked on the instant the claim window closes."""
    fixture = {"label": create_label(api)}
    fixture["rival_label"] = create_label(
        api, legal_name="Kestrel Tapes", territory="IE", rate_bps=800
    )
    fixture["period"] = create_period(api)
    fixture["recording_a"] = create_recording(
        api,
        identifier=TEST_DEFAULTS["RECORDING_A_ISRC"],
        title=TEST_DEFAULTS["RECORDING_A_TITLE"],
        artist=TEST_DEFAULTS["RECORDING_A_ARTIST"],
    )
    fixture["batch"] = create_batch(api, fixture["period"]["id"])
    append_line(
        api,
        fixture["batch"]["id"],
        reported_isrc=TEST_DEFAULTS["RECORDING_A_ISRC"],
        reported_title=TEST_DEFAULTS["RECORDING_A_TITLE"],
        territory_code="GB",
        subscription_tier="INDIVIDUAL",
        play_count=300000,
    )
    fixture["batch_after_match"] = seal_and_match_batch(api, fixture["batch"]["id"])
    set_clock(api, CLAIM_WINDOW_CLOSES_AT)
    return fixture


def _setup_three_mechanical_claims_under_review(api):
    """One composition carrying three GB MECHANICAL claims of 4000, 6000 and 1
    basis points, every one of them taken into review."""
    fixture = {}
    fixture["publisher_one"] = create_publisher(
        api, legal_name="Harbourline Publishing", territory="GB", rate_bps=800
    )
    fixture["publisher_two"] = create_publisher(
        api, legal_name="Tidewater Songs", territory="GB", rate_bps=800
    )
    fixture["publisher_three"] = create_publisher(
        api, legal_name="Foghorn Editions", territory="GB", rate_bps=800
    )
    fixture["composition"] = create_composition(api)

    claims = []
    for publisher, share_bps in (
        (fixture["publisher_one"], 4000),
        (fixture["publisher_two"], 6000),
        (fixture["publisher_three"], 1),
    ):
        claims.append(
            file_registration(
                api,
                fixture["composition"]["id"],
                publisher["id"],
                right_type="MECHANICAL",
                routing="DIRECT",
                share_bps=share_bps,
                territory_set=["GB"],
            )
        )
    for claim in claims:
        review_registration(api, claim["id"])

    fixture["claim_4000"], fixture["claim_6000"], fixture["claim_1"] = claims
    return fixture


def _setup_collective_performance_pools(api):
    """Two STUDENT pools falling back to a WORLD schedule that routes the whole
    publishing slice to performance, engineered so the collective's two
    performance lines land at exactly 100000 and at 99999 cents of gross."""
    fixture = {}
    fixture["publisher"] = create_publisher(
        api, legal_name="Harbourline Publishing", territory="GB"
    )
    fixture["collective"] = create_collective(
        api, legal_name="British Mechanical Collective", territory="WORLD"
    )
    fixture["schedule"] = create_effective_schedule(
        api,
        proceeding_ref="CRB-2026-STU",
        territory_code="WORLD",
        subscription_tier="STUDENT",
        revenue_share_bps=7000,
        per_subscriber_minimum_cents=500,
        mechanical_share_bps=0,
        performance_share_bps=10000,
        statutory_floor_per_play_millicents=0,
        effective_from="2026-01-01",
        effective_to="2026-12-31",
    )
    fixture["period"] = create_period(api)
    fixture["composition"] = create_composition(api)
    fixture["recording"] = create_recording(
        api,
        identifier=TEST_DEFAULTS["RECORDING_A_ISRC"],
        title=TEST_DEFAULTS["RECORDING_A_TITLE"],
        artist=TEST_DEFAULTS["RECORDING_A_ARTIST"],
        linked_work_id=fixture["composition"]["id"],
    )
    fixture["batch"] = create_batch(api, fixture["period"]["id"])
    for territory in ("GB", "IE"):
        append_line(
            api,
            fixture["batch"]["id"],
            reported_isrc=TEST_DEFAULTS["RECORDING_A_ISRC"],
            reported_title=TEST_DEFAULTS["RECORDING_A_TITLE"],
            territory_code=territory,
            subscription_tier="STUDENT",
            play_count=1000,
        )
    fixture["batch_after_match"] = seal_and_match_batch(api, fixture["batch"]["id"])

    registration = file_registration(
        api,
        fixture["composition"]["id"],
        fixture["publisher"]["id"],
        right_type="PERFORMANCE",
        routing="COLLECTIVE",
        collective_id=fixture["collective"]["id"],
        share_bps=10000,
        territory_set=["WORLD"],
    )
    review_registration(api, registration["id"])
    fixture["registration"] = approve_registration(api, registration["id"])

    pool_at_ceiling = create_pool(
        api,
        fixture["period"]["id"],
        territory_code="GB",
        subscription_tier="STUDENT",
        subscriber_count=500,
        gross_revenue_cents=571429,
    )
    pool_below_ceiling = create_pool(
        api,
        fixture["period"]["id"],
        territory_code="IE",
        subscription_tier="STUDENT",
        subscriber_count=500,
        gross_revenue_cents=571423,
    )
    fixture["pool_at_ceiling"] = calculate_pool(api, pool_at_ceiling["id"])
    fixture["pool_below_ceiling"] = calculate_pool(api, pool_below_ceiling["id"])
    fixture["pool_at_ceiling"] = finalize_pool(api, pool_at_ceiling["id"])
    fixture["pool_below_ceiling"] = finalize_pool(api, pool_below_ceiling["id"])
    return fixture


def _build_collective_statement(api, fixture):
    """Build the collective's statement, reading the period version immediately
    beforehand, and return the header together with its lines."""
    statement = validate_success(
        api.create_statement(
            statement_payload(
                fixture["collective"]["id"],
                fixture["period"]["id"],
                period_version(api, fixture["period"]["id"]),
            ),
            ADMIN,
        ),
        201,
    )
    lines, _meta = validate_paginated(
        api.list_statement_lines(ADMIN, params={"statement_id": statement["id"]})
    )
    return statement, lines


def _usage_line_for_territory(api, batch_id, territory_code):
    lines, _meta = validate_paginated(
        api.list_usage_lines(
            ADMIN, params={"batch_id": batch_id, "territory_code": territory_code}
        )
    )
    assert len(lines) == 1, (
        f"expected exactly one {territory_code} usage line, got {len(lines)}"
    )
    return lines[0]


def _line_for_territory(api, statement_id, territory_code):
    lines, _meta = validate_paginated(
        api.list_statement_lines(
            ADMIN,
            params={"statement_id": statement_id, "territory_code": territory_code},
        )
    )
    assert len(lines) == 1, (
        f"expected exactly one {territory_code} statement line, got {len(lines)}"
    )
    return lines[0]


# ─────────────────────────────────────────────────────
# match_confidence_at_and_below_auto_threshold
# ─────────────────────────────────────────────────────

class TestMatchConfidenceAtAndBelowAutoThreshold:

    def test_exact_isrc_hit_scores_10000_and_auto_matches(self, api):
        """An exact identifier hit scores 10,000 and auto-matches even when the reported title is wrong.

        PRD: "When the score is at least 7,500, the line takes `work_id` from the winner and moves to `match_status` `AUTO_MATCHED`; and when that accepted score is strictly below 10,000 — that is, when the service accepted a metadata inference rather than an identifier hit — the winning work's `provisional_match_by_user_id` is stamped with the `X-User-ID` of the calling analyst."

        Design: Difficulty/boundary_precision_check/match_confidence_at_and_below_auto_threshold
        """
        fixture = _setup_confidence_ladder_batch(api)

        line = validate_success(
            api.get_usage_line(fixture["line_isrc_hit"]["id"], ANALYST), 200
        )

        assert line["match_confidence_bps"] == 10000
        assert line["match_status"] == "AUTO_MATCHED"
        assert line["work_id"] == fixture["recording_a"]["id"]
        assert line["work_id"] != fixture["recording_b"]["id"]

    def test_title_and_artist_score_exactly_at_auto_threshold_auto_matches(self, api):
        """A title-and-artist agreement scoring exactly 7,500 satisfies the inclusive auto-match bound and stamps the matching analyst on the winning work.

        PRD: "When the score is at least 7,500, the line takes `work_id` from the winner and moves to `match_status` `AUTO_MATCHED`; and when that accepted score is strictly below 10,000 — that is, when the service accepted a metadata inference rather than an identifier hit — the winning work's `provisional_match_by_user_id` is stamped with the `X-User-ID` of the calling analyst."

        Design: Difficulty/boundary_precision_check/match_confidence_at_and_below_auto_threshold
        """
        fixture = _setup_confidence_ladder_batch(api)

        line = validate_success(
            api.get_usage_line(fixture["line_title_and_artist"]["id"], ANALYST), 200
        )

        assert line["match_confidence_bps"] == 7500
        assert line["match_confidence_bps"] == AUTO_MATCH_MIN_CONFIDENCE_BPS
        assert line["match_status"] == "AUTO_MATCHED"
        assert line["match_status"] != "UNMATCHED"
        assert line["work_id"] == fixture["recording_a"]["id"]

        recording_a = validate_success(
            api.get_work(fixture["recording_a"]["id"], ANALYST), 200
        )
        assert recording_a["provisional_match_by_user_id"] == ANALYST_FUZZY_MATCHER_USER_ID

    def test_title_only_score_below_auto_threshold_stays_unmatched(self, api):
        """A title-only agreement scoring 5,000 falls below the auto-match bound, so the line keeps a null work and forks the batch to PARTIALLY_MATCHED.

        PRD: "When the score is below 7,500 — in practice a title-only agreement scoring 5,000 — the line is **not** attached: `work_id` stays null and `match_status` stays `UNMATCHED`, but the line still records the best score it achieved, so a later claim can see how close the catalogue came."

        Design: Difficulty/boundary_precision_check/match_confidence_at_and_below_auto_threshold
        """
        fixture = _setup_confidence_ladder_batch(api)

        line = validate_success(
            api.get_usage_line(fixture["line_title_only"]["id"], ANALYST), 200
        )

        assert line["match_confidence_bps"] == 5000
        assert line["match_status"] == "UNMATCHED"
        assert line["match_status"] != "AUTO_MATCHED"
        assert line["work_id"] is None

        batch = fixture["batch_after_match"]
        assert batch["status"] == "PARTIALLY_MATCHED"
        assert batch["matched_play_count"] == 450000
        assert batch["unmatched_play_count"] == 50000

        recording_b = validate_success(
            api.get_work(fixture["recording_b"]["id"], ANALYST), 200
        )
        assert recording_b["provisional_match_by_user_id"] is None

    def test_same_score_exactly_at_claim_threshold_claim_matches(self, api):
        """The identical 5,000 score that failed the auto-match bound satisfies the inclusive claim-match bound once an owner is adjudicated.

        PRD: "Then the service re-runs the matcher in claim mode over unattached usage: every usage line whose `work_id` is still null, whose batch belongs to a period where the current instant is at or before `claim_window_closes_at`, and whose best score against **this newly approved work alone** is at least 5,000, takes `work_id` from that work, records that score in `match_confidence_bps`, and moves to `match_status` `CLAIM_MATCHED`."

        Design: Difficulty/boundary_precision_check/match_confidence_at_and_below_auto_threshold
        """
        fixture = _setup_confidence_ladder_batch(api)
        registration = file_registration(
            api,
            fixture["recording_b"]["id"],
            fixture["label"]["id"],
            right_type="MASTER",
            routing="DIRECT",
            share_bps=10000,
            territory_set=["WORLD"],
        )
        review_registration(api, registration["id"])
        approve_registration(api, registration["id"])

        line = validate_success(
            api.get_usage_line(fixture["line_title_only"]["id"], ANALYST), 200
        )

        assert line["match_confidence_bps"] == 5000
        assert line["match_confidence_bps"] == CLAIM_MATCH_MIN_CONFIDENCE_BPS
        assert line["match_status"] == "CLAIM_MATCHED"
        assert line["match_status"] != "AUTO_MATCHED"
        assert line["work_id"] == fixture["recording_b"]["id"]


# ─────────────────────────────────────────────────────
# revenue_share_exactly_equals_minimum_pool
# ─────────────────────────────────────────────────────

class TestRevenueShareExactlyEqualsMinimumPool:

    def test_revenue_share_equal_to_minimum_pool_reports_revenue_share_basis(self, api):
        """A revenue share exactly equal to the per-subscriber minimum satisfies the non-strict comparison and reports REVENUE_SHARE.

        PRD: "It is `REVENUE_SHARE` when `revenue_share_pool_cents` is greater than or equal to `minimum_pool_cents`, and greater than or equal to `statutory_floor_cents`, and less than or equal to three times `minimum_pool_cents`."

        Design: Difficulty/boundary_precision_check/revenue_share_exactly_equals_minimum_pool
        """
        fixture = _setup_equal_candidate_pools(api)

        pool = validate_success(
            api.calculate_pool(fixture["pool_at_tie"]["id"], ADMIN), 200
        )

        assert pool["revenue_share_pool_cents"] == 700000
        assert pool["minimum_pool_cents"] == 700000
        assert pool["statutory_floor_cents"] == 20000
        assert pool["distributable_cents"] == 700000
        assert pool["allocation_basis"] == "REVENUE_SHARE"
        assert pool["allocation_basis"] != "PER_SUBSCRIBER_MINIMUM"
        assert 3 * pool["minimum_pool_cents"] == 2100000

    def test_revenue_share_one_step_short_reports_per_subscriber_minimum_basis(self, api):
        """One extra subscriber lifts the minimum pool past the revenue share, so the basis falls through to PER_SUBSCRIBER_MINIMUM and the amount rises with it.

        PRD: "Otherwise it is `PER_SUBSCRIBER_MINIMUM` when `minimum_pool_cents` is greater than or equal to `statutory_floor_cents`."

        Design: Difficulty/boundary_precision_check/revenue_share_exactly_equals_minimum_pool
        """
        fixture = _setup_equal_candidate_pools(api)

        pool = validate_success(
            api.calculate_pool(fixture["pool_one_over"]["id"], ADMIN), 200
        )

        assert pool["revenue_share_pool_cents"] == 700000
        assert pool["minimum_pool_cents"] == 700500
        assert pool["distributable_cents"] == 700500
        assert pool["allocation_basis"] == "PER_SUBSCRIBER_MINIMUM"
        assert pool["allocation_basis"] != "REVENUE_SHARE"
        assert 3 * pool["minimum_pool_cents"] == 2101500


# ─────────────────────────────────────────────────────
# claim_window_inclusive_bound_to_the_second
# ─────────────────────────────────────────────────────

class TestClaimWindowInclusiveBoundToTheSecond:

    def test_claim_window_closes_sixty_days_after_usage_end_at_midnight(self, api):
        """A period covering 2026-06-01 to 2026-06-30 closes its claim window at 2026-08-29T00:00:00Z.

        PRD: "An `AccountingPeriod` computes `claim_window_closes_at` as its `usage_end` taken at midnight UTC — that is, at `00:00:00.000Z` on that date — advanced by 60 days; the bound is inclusive, so the current instant exactly equal to `claim_window_closes_at` still counts as open."

        Design: Difficulty/boundary_precision_check/claim_window_inclusive_bound_to_the_second
        """
        period = create_period(api)

        fetched = validate_success(api.get_period(period["id"], ADMIN), 200)

        assert fetched["usage_end"] == "2026-06-30"
        assert (
            fetched["claim_window_closes_at"].replace(".000Z", "Z")
            == CLAIM_WINDOW_CLOSES_AT
        )

    def test_registration_filed_exactly_at_window_close_is_accepted(self, api):
        """A claim filed at the instant exactly equal to claim_window_closes_at is still inside the window and is created.

        PRD: "The bound is inclusive: the current instant exactly equal to `claim_window_closes_at` is still open."

        Design: Difficulty/boundary_precision_check/claim_window_inclusive_bound_to_the_second
        """
        fixture = _setup_period_with_matched_usage_at_window_close(api)
        work_id = fixture["recording_a"]["id"]
        claimant_id = fixture["label"]["id"]

        registration = validate_success(
            api.create_rights_registration(
                rights_registration_payload(
                    work_id,
                    claimant_id,
                    work_version(api, work_id),
                    right_type="MASTER",
                    routing="DIRECT",
                    share_bps=6000,
                    territory_set=["GB"],
                    effective_from="2026-01-01",
                    effective_to="2027-01-01",
                ),
                make_rights_holder_user_headers(claimant_id),
            ),
            201,
        )

        assert registration["status"] == "SUBMITTED"
        assert registration["share_bps"] == 6000

    def test_registration_filed_one_second_past_window_close_is_refused(self, api):
        """A claim filed one second after claim_window_closes_at is outside the at-or-before bound and is refused.

        PRD: "A registration may be filed only while the current instant is at or before `claim_window_closes_at` for **every** accounting period that already carries at least one usage line touching the claimed work — for a `MASTER` claim, a line whose `work_id` is the claimed work; for a `MECHANICAL` or `PERFORMANCE` claim, a line whose matched work's `linked_work_id` is the claimed work."

        Design: Difficulty/boundary_precision_check/claim_window_inclusive_bound_to_the_second
        """
        fixture = _setup_period_with_matched_usage_at_window_close(api)
        work_id = fixture["recording_a"]["id"]
        first_claimant_id = fixture["label"]["id"]
        late_claimant_id = fixture["rival_label"]["id"]

        file_registration(
            api,
            work_id,
            first_claimant_id,
            right_type="MASTER",
            routing="DIRECT",
            share_bps=6000,
            territory_set=["GB"],
        )
        set_clock(api, ONE_SECOND_PAST_CLAIM_WINDOW)

        response = api.create_rights_registration(
            rights_registration_payload(
                work_id,
                late_claimant_id,
                work_version(api, work_id),
                right_type="MASTER",
                routing="DIRECT",
                share_bps=4000,
                territory_set=["IE"],
                effective_from="2026-01-01",
                effective_to="2027-01-01",
            ),
            make_rights_holder_user_headers(late_claimant_id),
        )

        validate_error(response, ApiErrorId.ERR_CLAIM_WINDOW_CLOSED.value, 422)

        registrations, meta = validate_paginated(
            api.list_rights_registrations(ANALYST, params={"work_id": work_id})
        )
        assert meta["total_count"] == 1
        assert len(registrations) == 1
        assert registrations[0]["claimant_id"] == first_claimant_id


# ─────────────────────────────────────────────────────
# aggregate_share_exactly_10000_per_territory
# ─────────────────────────────────────────────────────

class TestAggregateShareExactly10000PerTerritory:

    def test_aggregate_share_reaching_exactly_10000_is_approved(self, api):
        """Two GB claims of 4,000 and 6,000 basis points bring the territory aggregate to exactly 10,000 and both are approved.

        PRD: "If any territory's total exceeds 10,000 basis points, the approval is refused with `ERR_SHARE_OVERSUBSCRIBED`; a total of exactly 10,000 is accepted and a total of 10,001 is not."

        Design: Difficulty/boundary_precision_check/aggregate_share_exactly_10000_per_territory
        """
        fixture = _setup_three_mechanical_claims_under_review(api)

        first = validate_success(
            api.approve_rights_registration(fixture["claim_4000"]["id"], REVIEWER), 200
        )
        second = validate_success(
            api.approve_rights_registration(fixture["claim_6000"]["id"], REVIEWER), 200
        )

        assert first["status"] == "APPROVED"
        assert second["status"] == "APPROVED"
        assert first["share_bps"] == 4000
        assert second["share_bps"] == 6000
        assert first["share_bps"] + second["share_bps"] == MAX_SHARE_BPS_PER_TERRITORY

    def test_aggregate_share_exceeding_by_one_basis_point_is_refused(self, api):
        """A third GB claim of a single basis point pushes the territory aggregate to 10,001 and is refused without changing its own status.

        PRD: "If any territory's total exceeds 10,000 basis points, the approval is refused with `ERR_SHARE_OVERSUBSCRIBED`; a total of exactly 10,000 is accepted and a total of 10,001 is not."

        Design: Difficulty/boundary_precision_check/aggregate_share_exactly_10000_per_territory
        """
        fixture = _setup_three_mechanical_claims_under_review(api)
        validate_success(
            api.approve_rights_registration(fixture["claim_4000"]["id"], REVIEWER), 200
        )
        validate_success(
            api.approve_rights_registration(fixture["claim_6000"]["id"], REVIEWER), 200
        )

        response = api.approve_rights_registration(fixture["claim_1"]["id"], REVIEWER)

        validate_error(response, ApiErrorId.ERR_SHARE_OVERSUBSCRIBED.value, 409)

        refused = get_success_data(
            api.get_rights_registration(fixture["claim_1"]["id"], ANALYST)
        )
        assert refused["status"] == "UNDER_REVIEW"
        assert refused["status"] != "REJECTED"
        assert refused["status"] != "APPROVED"
        assert refused["share_bps"] == 1


# ─────────────────────────────────────────────────────
# admin_tier_ceiling_strict_less_than
# ─────────────────────────────────────────────────────

class TestAdminTierCeilingStrictLessThan:

    def test_gross_exactly_at_tier_ceiling_takes_the_cheaper_rate(self, api):
        """A collective-routed line whose gross is exactly 100,000 cents fails the strict below-ceiling test and pays the cheaper 900 basis point rate.

        PRD: "Both ceilings are compared strictly, so a `gross_cents` exactly equal to a ceiling falls into the higher band and therefore gets the cheaper rate."

        Design: Difficulty/boundary_precision_check/admin_tier_ceiling_strict_less_than
        """
        fixture = _setup_collective_performance_pools(api)

        assert fixture["pool_at_ceiling"]["revenue_share_pool_cents"] == 400000
        assert fixture["pool_at_ceiling"]["minimum_pool_cents"] == 250000
        assert fixture["pool_at_ceiling"]["statutory_floor_cents"] == 0
        assert fixture["pool_at_ceiling"]["distributable_cents"] == 400000
        assert fixture["pool_at_ceiling"]["rounding_residual_cents"] == 0

        usage_line = _usage_line_for_territory(api, fixture["batch"]["id"], "GB")
        assert usage_line["attributed_revenue_cents"] == 400000

        statement, _lines = _build_collective_statement(api, fixture)
        line = _line_for_territory(api, statement["id"], "GB")

        assert line["gross_cents"] == 100000
        assert line["gross_cents"] == ADMIN_TIER_1_CEILING_CENTS
        assert line["admin_fee_cents"] == 9000
        assert line["admin_fee_cents"] != 12000
        assert line["net_cents"] == 91000
        assert line["right_type"] == "PERFORMANCE"
        assert line["routing"] == "COLLECTIVE"

    def test_gross_one_cent_below_tier_ceiling_pays_the_dearer_rate(self, api):
        """A collective-routed line whose gross is one cent below the ceiling stays in the first band and pays the dearer 1,200 basis point rate.

        PRD: "On a line whose `routing` is `COLLECTIVE`, the rate is 1,200 basis points while `gross_cents` is below 100,000 cents, 900 basis points while `gross_cents` is below 1,000,000 cents, and 600 basis points otherwise."

        Design: Difficulty/boundary_precision_check/admin_tier_ceiling_strict_less_than
        """
        fixture = _setup_collective_performance_pools(api)

        assert fixture["pool_below_ceiling"]["revenue_share_pool_cents"] == 399996
        assert fixture["pool_below_ceiling"]["distributable_cents"] == 399996
        assert fixture["pool_below_ceiling"]["rounding_residual_cents"] == 0

        usage_line = _usage_line_for_territory(api, fixture["batch"]["id"], "IE")
        assert usage_line["attributed_revenue_cents"] == 399996

        statement, _lines = _build_collective_statement(api, fixture)
        line = _line_for_territory(api, statement["id"], "IE")

        assert line["gross_cents"] == 99999
        assert line["admin_fee_cents"] == 12000
        assert line["admin_fee_cents"] != 9000
        assert line["net_cents"] == 87999
        assert line["right_type"] == "PERFORMANCE"
        assert line["routing"] == "COLLECTIVE"

    def test_smaller_gross_carries_the_larger_fee_across_the_ceiling(self, api):
        """Across the ceiling the fee is non-monotonic: the smaller 99,999 cent gross pays 12,000 cents while the larger 100,000 cent gross pays only 9,000.

        PRD: "Both ceilings are compared strictly, so a `gross_cents` exactly equal to a ceiling falls into the higher band and therefore gets the cheaper rate."

        Design: Difficulty/boundary_precision_check/admin_tier_ceiling_strict_less_than
        """
        fixture = _setup_collective_performance_pools(api)

        statement, lines = _build_collective_statement(api, fixture)
        at_ceiling = _line_for_territory(api, statement["id"], "GB")
        below_ceiling = _line_for_territory(api, statement["id"], "IE")

        assert below_ceiling["gross_cents"] < at_ceiling["gross_cents"]
        assert below_ceiling["admin_fee_cents"] > at_ceiling["admin_fee_cents"]
        assert at_ceiling["admin_fee_cents"] == 9000
        assert below_ceiling["admin_fee_cents"] == 12000
        assert ADMIN_TIER_2_BPS == 900
        assert ADMIN_TIER_1_BPS == 1200

        assert len(lines) == 2
        assert statement["line_count"] == 2
        assert statement["gross_cents"] == 199999
        assert statement["admin_fee_cents"] == 21000
        assert statement["net_payable_cents"] == 178999
