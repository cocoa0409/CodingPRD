"""Derived-figure corners of the streaming royalty distribution API.

Everything under test here is a computed number or a computed selection: the
matcher's candidate set and its pinned tie-break, the governing rate schedule's
status filter, the three competing pool-sizing figures and the rounding
direction of each, the floor-rounded per-line attribution and the residual it
leaves behind, and the election of the holder that receives that residual.
"""

from test_helpers import (
    TEST_USERS,
    ANALYST_FUZZY_MATCHER_USER_ID,
    ApiErrorId,
    assert_play_count_conservation,
    assert_pool_value_conservation,
    assert_rights_registration,
    assert_royalty_pool,
    assert_statement_line,
    assert_usage_batch,
    assert_usage_line,
    assert_work,
    append_line,
    calculate_pool,
    create_batch,
    create_composition,
    create_holder,
    create_label,
    create_period,
    create_pool,
    create_publisher,
    create_recording,
    create_schedule,
    create_statement,
    file_and_approve_registration,
    file_registration,
    finalize_pool,
    promulgate_schedule,
    seal_and_match_batch,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN_HEADERS = TEST_USERS["royalty_admin_headers"]
ANALYST_HEADERS = TEST_USERS["rights_ops_analyst_headers"]
REGULATOR_HEADERS = TEST_USERS["regulatory_officer_headers"]

# The canonical GB/INDIVIDUAL rate layer used by every pool-sizing case below.
GB_INDIVIDUAL_SCHEDULE = dict(
    proceeding_ref="CRB-2026-01",
    territory_code="GB",
    subscription_tier="INDIVIDUAL",
    revenue_share_bps=7000,
    per_subscriber_minimum_cents=500,
    mechanical_share_bps=4000,
    performance_share_bps=6000,
    statutory_floor_per_play_millicents=100,
    effective_from="2026-01-01",
    effective_to="2026-12-31",
)


# ─────────────────────────────────────────────────────
# Composite preambles built from the fixtures.py atoms
# ─────────────────────────────────────────────────────

def _setup_tie_break_catalogue(api):
    """Two identically-titled recordings plus a same-titled composition, and one
    matched batch of four reported cells that exercises every scoring rung.

    The recordings are inserted in identifier-DESCENDING order, so the row
    created first is the one with the larger identifier.
    """
    period = create_period(api)
    recording_high = create_recording(
        api,
        identifier="GBABC2600002",
        title="Midnight Ledger",
        artist="The Reconcilers",
    )
    recording_low = create_recording(
        api,
        identifier="GBABC2600001",
        title="MIDNIGHT LEDGER",
        artist="the reconcilers",
    )
    composition = create_composition(api, identifier="T9001234567", title="Midnight Ledger")

    batch = create_batch(api, period["id"], source_label="UK client feed")
    batch_id = batch["id"]

    line_title_artist = append_line(
        api,
        batch_id,
        reported_title="midnight   ledger!!",
        reported_artist="THE RECONCILERS",
        territory_code="GB",
        subscription_tier="INDIVIDUAL",
        play_count=1000,
    )
    line_exact_isrc = append_line(
        api,
        batch_id,
        reported_isrc="GBABC2600002",
        reported_title="Midnight Ledger",
        territory_code="GB",
        subscription_tier="INDIVIDUAL",
        play_count=2000,
    )
    line_composition_isrc = append_line(
        api,
        batch_id,
        reported_isrc="T9001234567",
        reported_title="Unknown Signal",
        territory_code="GB",
        subscription_tier="INDIVIDUAL",
        play_count=3000,
    )
    line_title_only = append_line(
        api,
        batch_id,
        reported_title="Midnight Ledger",
        territory_code="GB",
        subscription_tier="INDIVIDUAL",
        play_count=4000,
    )

    batch_after_match = seal_and_match_batch(api, batch_id)

    return {
        "period": period,
        "recording_high": recording_high,
        "recording_low": recording_low,
        "composition": composition,
        "batch": batch_after_match,
        "line_title_artist": line_title_artist,
        "line_exact_isrc": line_exact_isrc,
        "line_composition_isrc": line_composition_isrc,
        "line_title_only": line_title_only,
    }


def _setup_single_exact_matched_line(
    api, *, play_count=450000, with_schedule=True, schedule_overrides=None
):
    """One GB/INDIVIDUAL line resolved by exact ISRC, so the batch is MATCHED and
    the period has bubbled up to USAGE_SEALED."""
    fixture = {}
    if with_schedule:
        terms = dict(GB_INDIVIDUAL_SCHEDULE)
        terms.update(schedule_overrides or {})
        schedule = create_schedule(api, **terms)
        fixture["schedule"] = promulgate_schedule(api, schedule["id"])

    fixture["period"] = create_period(api)
    fixture["recording"] = create_recording(
        api,
        identifier="GBABC2600001",
        title="Midnight Ledger",
        artist="The Reconcilers",
    )
    batch = create_batch(api, fixture["period"]["id"], source_label="UK client feed")
    fixture["line"] = append_line(
        api,
        batch["id"],
        reported_isrc="GBABC2600001",
        reported_title="Midnight Ledger",
        territory_code="GB",
        subscription_tier="INDIVIDUAL",
        play_count=play_count,
    )
    fixture["batch"] = seal_and_match_batch(api, batch["id"])
    return fixture


def _setup_proposed_schedule_and_draft_pool(api):
    """The exact-matched period with a matching schedule left PROPOSED, and the
    GB/INDIVIDUAL pool still in DRAFT."""
    fixture = _setup_single_exact_matched_line(api, with_schedule=False)
    fixture["proposed_schedule"] = create_schedule(api, **GB_INDIVIDUAL_SCHEDULE)
    fixture["pool"] = create_pool(
        api,
        fixture["period"]["id"],
        territory_code="GB",
        subscription_tier="INDIVIDUAL",
        subscriber_count=1000,
        gross_revenue_cents=1428570,
    )
    return fixture


def _setup_effective_schedule_and_calculated_pool(api):
    """The same fixture with the schedule promulgated and the pool CALCULATED
    against it."""
    fixture = _setup_proposed_schedule_and_draft_pool(api)
    fixture["schedule"] = promulgate_schedule(api, fixture["proposed_schedule"]["id"])
    fixture["calculated_pool"] = calculate_pool(api, fixture["pool"]["id"])
    return fixture


def _setup_sized_pool(
    api, *, play_count, subscriber_count, gross_revenue_cents, schedule_overrides=None
):
    """One exact-matched line under the canonical schedule, with a DRAFT pool
    whose subscriber count and revenue are chosen by the caller."""
    fixture = _setup_single_exact_matched_line(
        api, play_count=play_count, schedule_overrides=schedule_overrides
    )
    fixture["pool"] = create_pool(
        api,
        fixture["period"]["id"],
        territory_code="GB",
        subscription_tier="INDIVIDUAL",
        subscriber_count=subscriber_count,
        gross_revenue_cents=gross_revenue_cents,
    )
    return fixture


def _setup_two_rival_master_claims_and_a_publisher(api):
    """A label and a publisher holding APPROVED claims over the two sides of one
    copyright, a distributor whose rival MASTER claim is left SUBMITTED, and the
    GB/INDIVIDUAL pool CALCULATED over a single exact-matched line."""
    label = create_label(api, legal_name="Northbeam Records", territory="GB", rate_bps=800)
    publisher = create_publisher(
        api, legal_name="Tidewater Songs", territory="GB", rate_bps=1000
    )
    distributor = create_holder(
        api,
        legal_name="Harborline Distribution",
        holder_type="DISTRIBUTOR",
        home_territory_code="GB",
        direct_deal_rate_bps=800,
    )

    schedule = create_schedule(api, **GB_INDIVIDUAL_SCHEDULE)
    schedule = promulgate_schedule(api, schedule["id"])

    composition = create_composition(api, identifier="T9001234567", title="Midnight Ledger")
    recording = create_recording(
        api,
        identifier="GBABC2600001",
        title="Midnight Ledger",
        artist="The Reconcilers",
        linked_work_id=composition["id"],
    )

    period = create_period(api)
    batch = create_batch(api, period["id"], source_label="UK client feed")
    line = append_line(
        api,
        batch["id"],
        reported_isrc="GBABC2600001",
        reported_title="Midnight Ledger",
        territory_code="GB",
        subscription_tier="INDIVIDUAL",
        play_count=450000,
    )
    batch = seal_and_match_batch(api, batch["id"])

    master_registration = file_and_approve_registration(
        api,
        recording["id"],
        label["id"],
        right_type="MASTER",
        routing="DIRECT",
        share_bps=10000,
        territory_set=["WORLD"],
    )
    mechanical_registration = file_and_approve_registration(
        api,
        composition["id"],
        publisher["id"],
        right_type="MECHANICAL",
        routing="DIRECT",
        share_bps=10000,
        territory_set=["WORLD"],
    )
    rival_registration = file_registration(
        api,
        recording["id"],
        distributor["id"],
        right_type="MASTER",
        routing="DIRECT",
        share_bps=10000,
        territory_set=["WORLD"],
    )

    pool = create_pool(
        api,
        period["id"],
        territory_code="GB",
        subscription_tier="INDIVIDUAL",
        subscriber_count=1000,
        gross_revenue_cents=1428570,
    )
    calculated_pool = calculate_pool(api, pool["id"])

    return {
        "label": label,
        "publisher": publisher,
        "distributor": distributor,
        "schedule": schedule,
        "composition": composition,
        "recording": recording,
        "period": period,
        "batch": batch,
        "line": line,
        "master_registration": master_registration,
        "mechanical_registration": mechanical_registration,
        "rival_registration": rival_registration,
        "pool": calculated_pool,
    }


def _setup_unclaimed_two_line_pool(api):
    """Two GB/INDIVIDUAL lines that match no catalogued work at all, and the pool
    that funds their holding account, CALCULATED."""
    schedule = create_schedule(api, **GB_INDIVIDUAL_SCHEDULE)
    schedule = promulgate_schedule(api, schedule["id"])

    period = create_period(api)
    batch = create_batch(api, period["id"], source_label="Partner feed")
    line_large = append_line(
        api,
        batch["id"],
        reported_title="Unknown Signal",
        territory_code="GB",
        subscription_tier="INDIVIDUAL",
        play_count=150000,
    )
    line_small = append_line(
        api,
        batch["id"],
        reported_title="Second Unknown",
        territory_code="GB",
        subscription_tier="INDIVIDUAL",
        play_count=50000,
    )
    batch = seal_and_match_batch(api, batch["id"])

    pool = create_pool(
        api,
        period["id"],
        territory_code="GB",
        subscription_tier="INDIVIDUAL",
        subscriber_count=100,
        gross_revenue_cents=100001,
    )
    calculated_pool = calculate_pool(api, pool["id"])

    return {
        "schedule": schedule,
        "period": period,
        "batch": batch,
        "line_large": line_large,
        "line_small": line_small,
        "pool": calculated_pool,
    }


def _read_usage_line(api, line_id):
    line = validate_success(api.get_usage_line(line_id, ANALYST_HEADERS), 200)
    assert_usage_line(line)
    return line


def _read_work(api, work_id):
    work = validate_success(api.get_work(work_id, ANALYST_HEADERS), 200)
    assert_work(work)
    return work


def _read_pool(api, pool_id):
    pool = validate_success(api.get_pool(pool_id, ADMIN_HEADERS), 200)
    assert_royalty_pool(pool)
    return pool


# ─────────────────────────────────────────────────────
# Matching: candidate set and deterministic tie-break
# ─────────────────────────────────────────────────────

class TestMatchingCandidateSetAndTieBreak:

    def test_title_and_artist_tie_is_broken_by_the_smaller_identifier(self, api):
        """Two recordings that agree on title and artist tie at 7,500 and share a
        created_at, so the winner is the alphabetically smaller identifier rather
        than the row inserted first.

        PRD: "Third, the winner is the candidate with the highest score; ties are broken by the earlier `created_at`, and a remaining tie by the lexicographically smaller `identifier`."

        Design: Corner/calculations/usage_line_matching_candidate_set_and_deterministic_tie_break
        """
        fixture = _setup_tie_break_catalogue(api)

        line = _read_usage_line(api, fixture["line_title_artist"]["id"])

        assert line["work_id"] == fixture["recording_low"]["id"]
        assert line["work_id"] != fixture["recording_high"]["id"]
        assert line["match_confidence_bps"] == 7500
        assert line["match_status"] == "AUTO_MATCHED"

    def test_fuzzy_win_stamps_the_provisional_matcher_on_the_winning_work_only(self, api):
        """A win accepted at 7,500 stamps the calling analyst on the winning work
        and leaves the losing candidate unstamped.

        PRD: "When the score is at least 7,500, the line takes `work_id` from the winner and moves to `match_status` `AUTO_MATCHED`; and when that accepted score is strictly below 10,000 — that is, when the service accepted a metadata inference rather than an identifier hit — the winning work's `provisional_match_by_user_id` is stamped with the `X-User-ID` of the calling analyst."

        Design: Corner/calculations/usage_line_matching_candidate_set_and_deterministic_tie_break
        """
        fixture = _setup_tie_break_catalogue(api)

        winner = _read_work(api, fixture["recording_low"]["id"])
        loser = _read_work(api, fixture["recording_high"]["id"])

        assert winner["provisional_match_by_user_id"] == ANALYST_FUZZY_MATCHER_USER_ID
        assert loser["provisional_match_by_user_id"] != ANALYST_FUZZY_MATCHER_USER_ID

    def test_exact_isrc_hit_outranks_a_title_only_agreement(self, api):
        """A line carrying the ISRC of one recording scores 10,000 on that
        recording and takes it, beating the 5,000 title-only agreement available
        on the other.

        PRD: "A candidate scores 10,000 when the line's `reported_isrc` is present and the candidate's `identifier` equals it — an exact identifier hit."

        Design: Corner/calculations/usage_line_matching_candidate_set_and_deterministic_tie_break
        """
        fixture = _setup_tie_break_catalogue(api)

        line = _read_usage_line(api, fixture["line_exact_isrc"]["id"])

        assert line["work_id"] == fixture["recording_high"]["id"]
        assert line["work_id"] != fixture["recording_low"]["id"]
        assert line["match_confidence_bps"] == 10000
        assert line["match_status"] == "AUTO_MATCHED"

    def test_exact_identifier_win_leaves_provisional_match_null(self, api):
        """The recording won by an exact identifier hit keeps
        provisional_match_by_user_id null, because nothing was inferred.

        PRD: "Finally, `provisional_match_by_user_id` records the `X-User-ID` of the `RightsOpsAnalyst` whose matching run last attached a usage line to this work at a confidence strictly below 10,000 basis points; it is null until such a fuzzy match happens, and it is the input to the segregation-of-duties rule that later blocks that same analyst from approving the claim that monetises the guess."

        Design: Corner/calculations/usage_line_matching_candidate_set_and_deterministic_tie_break
        """
        fixture = _setup_tie_break_catalogue(api)

        exact_winner = _read_work(api, fixture["recording_high"]["id"])

        assert exact_winner["provisional_match_by_user_id"] is None

    def test_composition_carrying_the_reported_isrc_is_not_a_candidate(self, api):
        """A composition whose identifier is exactly the reported ISRC is filtered
        out by work type, so the candidate set is empty and the line records zero
        confidence while the composition itself is untouched.

        PRD: "Compositions are never candidates; usage is always reported against recordings."

        Design: Corner/calculations/usage_line_matching_candidate_set_and_deterministic_tie_break
        """
        fixture = _setup_tie_break_catalogue(api)

        line = _read_usage_line(api, fixture["line_composition_isrc"]["id"])
        composition = _read_work(api, fixture["composition"]["id"])

        assert line["work_id"] is None
        assert line["match_confidence_bps"] == 0
        assert line["match_confidence_bps"] != 10000
        assert line["match_status"] == "UNMATCHED"
        assert composition["rights_state"] == "UNMATCHED"
        assert composition["provisional_match_by_user_id"] is None

    def test_title_only_score_is_recorded_but_the_line_is_not_attached(self, api):
        """A best score of 5,000 is written to match_confidence_bps even though it
        is below the acceptance threshold, so work_id stays null and the line
        stays UNMATCHED.

        PRD: "When the score is below 7,500 — in practice a title-only agreement scoring 5,000 — the line is **not** attached: `work_id` stays null and `match_status` stays `UNMATCHED`, but the line still records the best score it achieved, so a later claim can see how close the catalogue came."

        Design: Corner/calculations/usage_line_matching_candidate_set_and_deterministic_tie_break
        """
        fixture = _setup_tie_break_catalogue(api)

        line = _read_usage_line(api, fixture["line_title_only"]["id"])

        assert line["match_confidence_bps"] == 5000
        assert line["work_id"] is None
        assert line["match_status"] == "UNMATCHED"

    def test_batch_forks_to_partially_matched_with_the_exact_play_split(self, api):
        """Two accepted and two refused lines leave unmatched plays behind, so the
        batch forks to PARTIALLY_MATCHED with 3,000 matched and 7,000 unmatched
        plays.

        PRD: "When `unmatched_play_count` is 1 or more, the batch moves `SEALED → PARTIALLY_MATCHED` instead; the divergence is not cosmetic, because those still-`UNMATCHED` lines are precisely what will fund pool holding accounts at calculation time."

        Design: Corner/calculations/usage_line_matching_candidate_set_and_deterministic_tie_break
        """
        fixture = _setup_tie_break_catalogue(api)
        batch = fixture["batch"]
        assert_usage_batch(batch)

        assert batch["status"] == "PARTIALLY_MATCHED"
        assert batch["matched_play_count"] == 3000
        assert batch["unmatched_play_count"] == 7000
        assert batch["disputed_play_count"] == 0
        assert batch["total_play_count"] == 10000
        assert_play_count_conservation(batch)


# ─────────────────────────────────────────────────────
# Rate schedule selection reads EFFECTIVE rows only
# ─────────────────────────────────────────────────────

class TestRateScheduleSelectionStatusFilter:

    def test_proposed_schedule_is_invisible_to_selection(self, api):
        """A schedule matching the pool on territory, tier and window but still
        PROPOSED yields an empty candidate set, so the calculate is refused and
        the pool stays DRAFT with nothing sized.

        PRD: "If the candidate set is empty, the calculation is refused with `ERR_NO_EFFECTIVE_RATE_SCHEDULE`."

        Design: Corner/calculations/rate_schedule_selection_ignores_proposed_and_superseded_rows
        """
        fixture = _setup_proposed_schedule_and_draft_pool(api)

        assert fixture["proposed_schedule"]["status"] == "PROPOSED"

        validate_error(
            api.calculate_pool(fixture["pool"]["id"], ADMIN_HEADERS),
            ApiErrorId.ERR_NO_EFFECTIVE_RATE_SCHEDULE.value,
            422,
        )

        pool = _read_pool(api, fixture["pool"]["id"])
        assert pool["status"] == "DRAFT"
        assert pool["distributable_cents"] == 0
        assert pool["applied_rate_schedule_id"] is None

    def test_promulgated_schedule_sizes_the_pool_from_its_revenue_share(self, api):
        """Once the same schedule is EFFECTIVE the identical calculate succeeds,
        recording it as the applied rate and sizing distributable_cents at
        999,999 from a 7,000-bps share of 1,428,570 cents.

        PRD: "`revenue_share_pool_cents` is `gross_revenue_cents` multiplied by the schedule's `revenue_share_bps`, divided by 10,000, rounded half up to a whole cent."

        Design: Corner/calculations/rate_schedule_selection_ignores_proposed_and_superseded_rows
        """
        fixture = _setup_proposed_schedule_and_draft_pool(api)
        schedule = promulgate_schedule(api, fixture["proposed_schedule"]["id"])
        assert schedule["status"] == "EFFECTIVE"

        pool = calculate_pool(api, fixture["pool"]["id"])
        assert_royalty_pool(pool)

        assert pool["applied_rate_schedule_id"] == schedule["id"]
        assert pool["revenue_share_pool_cents"] == 999999
        assert pool["minimum_pool_cents"] == 500000
        assert pool["statutory_floor_cents"] == 45000
        assert pool["distributable_cents"] == 999999
        assert pool["allocation_basis"] == "REVENUE_SHARE"
        assert pool["status"] == "CALCULATED"

    def test_superseded_predecessor_is_excluded_so_recalculation_reprices(self, api):
        """Promulgating a successor with supersede_incumbent hides the incumbent
        from selection, so recalculating the very same pool applies the successor
        and moves distributable_cents from 999,999 to 857,142 with no change to
        usage or revenue.

        PRD: "Schedules in `PROPOSED` or `SUPERSEDED` status are excluded entirely."

        Design: Corner/calculations/rate_schedule_selection_ignores_proposed_and_superseded_rows
        """
        fixture = _setup_effective_schedule_and_calculated_pool(api)
        incumbent_id = fixture["schedule"]["id"]
        assert fixture["calculated_pool"]["distributable_cents"] == 999999

        remand = create_schedule(
            api,
            proceeding_ref="CRB-2026-07-REMAND",
            territory_code="GB",
            subscription_tier="INDIVIDUAL",
            revenue_share_bps=6000,
            per_subscriber_minimum_cents=500,
            mechanical_share_bps=4000,
            performance_share_bps=6000,
            statutory_floor_per_play_millicents=100,
            effective_from="2026-06-01",
            effective_to="2026-12-31",
        )
        remand = promulgate_schedule(api, remand["id"], supersede_incumbent=True)
        assert remand["status"] == "EFFECTIVE"

        displaced = validate_success(api.get_rate_schedule(incumbent_id, REGULATOR_HEADERS), 200)
        assert displaced["status"] == "SUPERSEDED"

        pool = calculate_pool(api, fixture["pool"]["id"])
        assert_royalty_pool(pool)

        assert pool["applied_rate_schedule_id"] == remand["id"]
        assert pool["applied_rate_schedule_id"] != incumbent_id
        assert pool["distributable_cents"] == 857142
        assert pool["distributable_cents"] != 999999
        assert pool["allocation_basis"] == "REVENUE_SHARE"
        assert pool["status"] == "CALCULATED"


# ─────────────────────────────────────────────────────
# Revenue-share sizing rounds half up
# ─────────────────────────────────────────────────────

class TestRevenueShareHalfUpRounding:

    def test_exact_half_cent_revenue_share_rounds_away_from_zero(self, api):
        """A revenue share landing on exactly 500,000.5 cents rounds up to
        500,001, not to the even 500,000 a banker's rule would produce.

        PRD: "The default rounding method throughout the system is round half up to a whole cent: a computed amount whose fractional part is exactly one half rounds away from zero."

        Design: Corner/calculations/pool_distributable_revenue_share_rounds_half_up_not_half_even
        """
        # 1000001 * 5000 / 10000 = 500000.5, an exact half cent.
        fixture = _setup_sized_pool(
            api,
            play_count=450000,
            subscriber_count=1000,
            gross_revenue_cents=1000001,
            schedule_overrides={"revenue_share_bps": 5000},
        )

        pool = calculate_pool(api, fixture["pool"]["id"])
        assert_royalty_pool(pool)

        assert pool["revenue_share_pool_cents"] == 500001
        assert pool["revenue_share_pool_cents"] != 500000
        assert pool["distributable_cents"] == 500001
        assert pool["distributable_cents"] != 500000
        assert pool["total_play_count"] == 450000

    def test_half_up_share_clears_the_minimum_and_takes_the_revenue_share_basis(self, api):
        """With 500,001 sitting above the 500,000 per-subscriber minimum, at or
        above the 45,000 floor and under the 1,500,000 cap, allocation_basis is
        REVENUE_SHARE.

        PRD: "It is `REVENUE_SHARE` when `revenue_share_pool_cents` is greater than or equal to `minimum_pool_cents`, and greater than or equal to `statutory_floor_cents`, and less than or equal to three times `minimum_pool_cents`."

        Design: Corner/calculations/pool_distributable_revenue_share_rounds_half_up_not_half_even
        """
        fixture = _setup_sized_pool(
            api,
            play_count=450000,
            subscriber_count=1000,
            gross_revenue_cents=1000001,
            schedule_overrides={"revenue_share_bps": 5000},
        )

        pool = calculate_pool(api, fixture["pool"]["id"])
        assert_royalty_pool(pool)

        assert pool["minimum_pool_cents"] == 500000
        assert pool["statutory_floor_cents"] == 45000
        assert pool["distributable_cents"] == 500001
        assert pool["allocation_basis"] == "REVENUE_SHARE"


# ─────────────────────────────────────────────────────
# The statutory floor rounds up and can win outright
# ─────────────────────────────────────────────────────

class TestStatutoryFloorCeiling:

    def test_statutory_floor_rounds_up_and_wins_the_outer_maximum(self, api):
        """450,001 plays at 100 millicents is 45,000.1 cents, which the ceiling
        lifts to 45,001, and on a thin-revenue pool that floor outranks both
        other figures and labels the basis STATUTORY_FLOOR.

        PRD: "`statutory_floor_cents` is `total_play_count` multiplied by the schedule's `statutory_floor_per_play_millicents`, divided by 1,000 to convert thousandths of a cent into cents, and then rounded **up** to the next whole cent."

        Design: Corner/calculations/statutory_floor_uses_ceiling_and_can_beat_both_other_inputs
        """
        fixture = _setup_sized_pool(
            api, play_count=450001, subscriber_count=1, gross_revenue_cents=1000
        )

        pool = calculate_pool(api, fixture["pool"]["id"])
        assert_royalty_pool(pool)

        assert pool["revenue_share_pool_cents"] == 700
        assert pool["minimum_pool_cents"] == 500
        assert pool["statutory_floor_cents"] == 45001
        assert pool["statutory_floor_cents"] != 45000
        assert pool["distributable_cents"] == 45001
        assert pool["allocation_basis"] == "STATUTORY_FLOOR"
        assert pool["total_play_count"] == 450001

    def test_floor_sized_pool_is_fully_attributed_to_its_single_line(self, api):
        """With the claim window still open the denominator is all reported
        usage, so the single matched line absorbs the whole 45,001-cent floor
        even though the pool holds 45 times its own revenue.

        PRD: "Every other line receives `distributable_cents` multiplied by its own `play_count`, divided by `denominator_play_count`, rounded **down** to a whole cent."

        Design: Corner/calculations/statutory_floor_uses_ceiling_and_can_beat_both_other_inputs
        """
        fixture = _setup_sized_pool(
            api, play_count=450001, subscriber_count=1, gross_revenue_cents=1000
        )

        pool = calculate_pool(api, fixture["pool"]["id"])
        assert_royalty_pool(pool)
        line = _read_usage_line(api, fixture["line"]["id"])

        assert pool["denominator_basis"] == "ALL_USAGE"
        assert pool["denominator_play_count"] == 450001
        assert line["attributed_revenue_cents"] == 45001
        assert pool["matched_attributed_cents"] == 45001
        assert pool["holding_cents"] == 0
        assert pool["rounding_residual_cents"] == 0
        assert_pool_value_conservation(pool)


# ─────────────────────────────────────────────────────
# Residual payee election ranks APPROVED claims by gross
# ─────────────────────────────────────────────────────

class TestResidualPayeeElection:

    def test_rival_master_claim_is_admitted_at_submitted(self, api):
        """A second holder may file an identical 10,000-bps MASTER claim over an
        already fully claimed recording, and it lands at SUBMITTED rather than
        being refused at the door.

        PRD: "Only one `DRAFT`-or-`ISSUED` statement may exist per holder and period, but registrations carry no such uniqueness constraint; competing claims are resolved by adjudication, not by rejection at the door."

        Design: Corner/calculations/residual_payee_is_ranked_by_gross_over_approved_registrations_only
        """
        fixture = _setup_two_rival_master_claims_and_a_publisher(api)
        rival = fixture["rival_registration"]
        assert_rights_registration(rival)

        assert rival["status"] == "SUBMITTED"
        assert rival["share_bps"] == 10000
        assert rival["right_type"] == "MASTER"
        assert fixture["master_registration"]["status"] == "APPROVED"

    def test_single_matched_line_absorbs_the_pool_and_leaves_no_residual(self, api):
        """One matched line carrying every reported play is attributed the whole
        999,999 cents, so nothing is left in holding and the rounding residual is
        exactly zero.

        PRD: "`rounding_residual_cents` is `distributable_cents` minus the sum of `attributed_revenue_cents` over **all** in-scope lines."

        Design: Corner/calculations/residual_payee_is_ranked_by_gross_over_approved_registrations_only
        """
        fixture = _setup_two_rival_master_claims_and_a_publisher(api)
        pool = fixture["pool"]
        assert_royalty_pool(pool)
        line = _read_usage_line(api, fixture["line"]["id"])

        assert pool["distributable_cents"] == 999999
        assert line["attributed_revenue_cents"] == 999999
        assert pool["matched_attributed_cents"] == 999999
        assert pool["holding_cents"] == 0
        assert pool["rounding_residual_cents"] == 0
        assert_pool_value_conservation(pool)

    def test_residual_payee_is_the_holder_with_the_largest_projected_gross(self, api):
        """The label's projected 749,999-cent master gross beats the publisher's
        100,000-cent mechanical gross, so finalizing elects the label as residual
        payee.

        PRD: "`residual_payee_holder_id` is chosen by totalling, for every holder that would receive at least one non-residual line from this pool under the statement-assembly rules of §3.7, the gross it would receive; the holder with the largest total wins, with ties broken by the earlier `RightsHolder.created_at` and then by the lexicographically smaller `legal_name`."

        Design: Corner/calculations/residual_payee_is_ranked_by_gross_over_approved_registrations_only
        """
        fixture = _setup_two_rival_master_claims_and_a_publisher(api)

        pool = finalize_pool(api, fixture["pool"]["id"])
        assert_royalty_pool(pool)

        assert pool["status"] == "FINALIZED"
        assert pool["residual_payee_holder_id"] == fixture["label"]["id"]
        assert pool["residual_payee_holder_id"] != fixture["publisher"]["id"]

    def test_submitted_rival_claim_produces_no_residual_payee_candidate(self, api):
        """The distributor's identical 10,000-bps MASTER claim contributes no
        projected gross at all while it is merely SUBMITTED, so it is absent from
        the residual ranking.

        PRD: "Only `APPROVED` registrations produce payees for this purpose; claims that are `SUBMITTED`, `UNDER_REVIEW`, `NEEDS_EVIDENCE` or `DISPUTED` produce none."

        Design: Corner/calculations/residual_payee_is_ranked_by_gross_over_approved_registrations_only
        """
        fixture = _setup_two_rival_master_claims_and_a_publisher(api)

        pool = finalize_pool(api, fixture["pool"]["id"])
        assert_royalty_pool(pool)

        assert fixture["rival_registration"]["status"] == "SUBMITTED"
        assert pool["residual_payee_holder_id"] != fixture["distributor"]["id"]
        assert pool["residual_payee_holder_id"] == fixture["label"]["id"]

    def test_elected_residual_payee_gets_no_residual_line_on_a_zero_residual(self, api):
        """Election and payment are separate steps: with rounding_residual_cents
        at zero the elected payee's statement carries no RESIDUAL line.

        PRD: "When the pool's `residual_payee_holder_id` equals this statement's `rights_holder_id` and the pool's `rounding_residual_cents` is not zero, the statement also carries a residual line: `line_type` `RESIDUAL`, `work_id` null, `right_type` null, `routing` null, `play_count` 0, `share_bps` 10,000, `gross_cents` equal to the pool's `rounding_residual_cents`, `admin_fee_cents` 0, and `net_cents` equal to that same residual."

        Design: Corner/calculations/residual_payee_is_ranked_by_gross_over_approved_registrations_only
        """
        fixture = _setup_two_rival_master_claims_and_a_publisher(api)

        pool = finalize_pool(api, fixture["pool"]["id"])
        assert pool["residual_payee_holder_id"] == fixture["label"]["id"]
        assert pool["rounding_residual_cents"] == 0

        statement = create_statement(api, fixture["label"]["id"], fixture["period"]["id"])
        lines, _meta = validate_paginated(
            api.list_statement_lines(ADMIN_HEADERS, params={"statement_id": statement["id"]})
        )
        for line in lines:
            assert_statement_line(line)

        assert [line for line in lines if line["line_type"] == "RESIDUAL"] == []


# ─────────────────────────────────────────────────────
# An empty residual-payee candidate set
# ─────────────────────────────────────────────────────

class TestResidualPayeeEmptyCandidateSet:

    def test_floor_rounded_attributions_leave_a_one_cent_residual(self, api):
        """Attributing 70,001 cents across 150,000 and 50,000 plays floors to
        52,500 and 17,500, which sum to 70,000 and leave a residual of exactly
        one cent.

        PRD: "The per-usage-line attribution of a pool's distributable amount is rounded **down** to a whole cent, so that attribution drift is always non-negative and lands in a single explicitly tracked residual instead of over-committing the pool."

        Design: Corner/calculations/residual_payee_empty_set_leaves_null_and_finalize_still_succeeds
        """
        fixture = _setup_unclaimed_two_line_pool(api)
        pool = fixture["pool"]
        assert_royalty_pool(pool)

        large = _read_usage_line(api, fixture["line_large"]["id"])
        small = _read_usage_line(api, fixture["line_small"]["id"])

        assert pool["revenue_share_pool_cents"] == 70001
        assert pool["minimum_pool_cents"] == 50000
        assert pool["statutory_floor_cents"] == 20000
        assert pool["distributable_cents"] == 70001
        assert pool["allocation_basis"] == "REVENUE_SHARE"
        assert large["attributed_revenue_cents"] == 52500
        assert small["attributed_revenue_cents"] == 17500
        assert large["attributed_revenue_cents"] + small["attributed_revenue_cents"] == 70000
        assert pool["rounding_residual_cents"] == 1
        assert_pool_value_conservation(pool)

    def test_unmatched_lines_are_funded_under_the_all_usage_denominator(self, api):
        """With the clock inside the claim window the denominator is all 200,000
        reported plays, so the two UNMATCHED lines are attributed and their whole
        value lands in the holding account.

        PRD: "While the current instant is at or before the period's `claim_window_closes_at`, `denominator_basis` is `ALL_USAGE` and `denominator_play_count` is the pool's `total_play_count`; once the current instant has passed `claim_window_closes_at`, `denominator_basis` is `MATCHED_ONLY` and `denominator_play_count` is the sum of `play_count` over in-scope lines whose `match_status` is `AUTO_MATCHED` or `CLAIM_MATCHED`."

        Design: Corner/calculations/residual_payee_empty_set_leaves_null_and_finalize_still_succeeds
        """
        fixture = _setup_unclaimed_two_line_pool(api)
        pool = fixture["pool"]
        assert_royalty_pool(pool)
        batch = fixture["batch"]
        assert_usage_batch(batch)

        large = _read_usage_line(api, fixture["line_large"]["id"])
        small = _read_usage_line(api, fixture["line_small"]["id"])

        assert batch["status"] == "PARTIALLY_MATCHED"
        assert batch["unmatched_play_count"] == 200000
        assert large["match_status"] == "UNMATCHED"
        assert small["match_status"] == "UNMATCHED"
        assert pool["denominator_basis"] == "ALL_USAGE"
        assert pool["denominator_play_count"] == 200000
        assert pool["holding_cents"] == 70000
        assert pool["matched_attributed_cents"] == 0

    def test_finalize_with_no_qualifying_holder_leaves_the_residual_payee_null(self, api):
        """No APPROVED registration exists, so the residual candidate set is
        empty: the finalize still succeeds and the orphan cent stays on the pool
        with residual_payee_holder_id null.

        PRD: "When no holder qualifies at all, `residual_payee_holder_id` stays null, the residual is simply not paid out, `rounding_residual_cents` keeps its value, and the pool finalizes anyway."

        Design: Corner/calculations/residual_payee_empty_set_leaves_null_and_finalize_still_succeeds
        """
        fixture = _setup_unclaimed_two_line_pool(api)

        pool = validate_success(api.finalize_pool(fixture["pool"]["id"], ADMIN_HEADERS), 200)
        assert_royalty_pool(pool)

        assert pool["status"] == "FINALIZED"
        assert pool["residual_payee_holder_id"] is None
        assert pool["rounding_residual_cents"] == 1
        assert pool["holding_cents"] == 70000
        assert_pool_value_conservation(pool)

    def test_period_bubbles_up_to_distributed_once_its_only_pool_is_frozen(self, api):
        """Finalizing the period's only pool bubbles the period from USAGE_SEALED
        to DISTRIBUTED.

        PRD: "When the period owns at least one pool and every pool of the period has `status` `FINALIZED`, the period moves `USAGE_SEALED → DISTRIBUTED`, or `REOPENED → DISTRIBUTED` when it was reopened by a rate cascade; the second form closes the reopen cycle."

        Design: Corner/calculations/residual_payee_empty_set_leaves_null_and_finalize_still_succeeds
        """
        fixture = _setup_unclaimed_two_line_pool(api)
        finalize_pool(api, fixture["pool"]["id"])

        period = validate_success(
            api.get_period(fixture["period"]["id"], ADMIN_HEADERS), 200
        )

        assert period["status"] == "DISTRIBUTED"

    def test_period_holding_total_sums_the_pool_holding_accounts(self, api):
        """The period reports the 70,000 cents sitting in its single pool's
        holding account as total_holding_cents.

        PRD: "A period also reports `total_holding_cents`, the sum of `holding_cents` across its pools, which is the number the closing rule in §3.8 cares about."

        Design: Corner/calculations/residual_payee_empty_set_leaves_null_and_finalize_still_succeeds
        """
        fixture = _setup_unclaimed_two_line_pool(api)
        pool = finalize_pool(api, fixture["pool"]["id"])

        period = validate_success(
            api.get_period(fixture["period"]["id"], ADMIN_HEADERS), 200
        )

        assert pool["holding_cents"] == 70000
        assert period["total_holding_cents"] == 70000
