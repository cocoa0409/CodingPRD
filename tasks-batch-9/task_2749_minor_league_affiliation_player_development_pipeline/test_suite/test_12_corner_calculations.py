"""Derived arithmetic: weighted blends, weighted scores, means, aggregations,
marginal tiers, inclusive constant boundaries and the two cap waterfalls.
"""

from test_helpers import (
    COMPLIANCE_OFFICER_HEADERS,
    COMPLIANCE_OFFICER_USER_ID,
    FARM_DIRECTOR_HEADERS,
    FARM_DIRECTOR_USER_ID,
    ApiClient,
    ApiErrorId,
    assert_decimal,
    assert_deficiency_banding,
    assert_integer,
    assert_iso_timestamp,
    assert_money,
    assert_status,
    factories,
    fixtures,
    validate_error,
    validate_paginated,
)


def _create_assignment(api: ApiClient, player_id: str, affiliate_id: str, **overrides):
    """Raw assignment create, so a refusal can be inspected rather than raised."""
    expected = overrides.pop("expected_player_version", None)
    if expected is None:
        expected = fixtures.player_version(api, player_id)
    return api.create_assignment(
        factories.assignment_payload(player_id, affiliate_id, expected, **overrides),
        FARM_DIRECTOR_HEADERS,
    )


def _readiness_fixture(api: ApiClient, service_days: int, city_a: str, city_b: str) -> dict:
    """One player on a single-module plan at a SINGLE_A club, plus a DOUBLE_A club.

    The plan budgets `0.50` of weekly workload, so the pressure denominator is
    exactly `1.00` and one hundred pitches drive the headroom term to zero.
    """
    fixtures.set_clock(api, "2026-04-01T00:00:00Z")
    lower = fixtures.licensed_affiliate(
        api,
        affiliate_overrides={
            "name": f"Readiness Single A {city_a}",
            "level": "SINGLE_A",
            "market_city": city_a,
            "meal_stipend_cents_per_day": 2600,
        },
    )
    upper = fixtures.licensed_affiliate(
        api,
        affiliate_overrides={
            "name": f"Readiness Double A {city_b}",
            "level": "DOUBLE_A",
            "market_city": city_b,
            "meal_stipend_cents_per_day": 2900,
        },
        agreement_overrides={
            "facility_standard_tier": "TIER_1",
            "club_reimbursement_cap_cents": 1200000,
            "minimum_active_players": 0,
        },
    )
    bundle = fixtures.active_assignment(
        api,
        lower["affiliate_id"],
        player_overrides={
            "full_name": "Readiness Prospect",
            "origin": "DOMESTIC_DRAFT",
            "signed_date": "2025-06-10",
            "service_days_accrued": service_days,
        },
        effective_date="2026-04-01",
        end_date="2026-06-30",
    )
    plan = fixtures.create_plan(
        api,
        bundle["assignment_id"],
        target_level="DOUBLE_A",
        curriculum_modules=["MOD_MECHANICS"],
        workload_limit_weekly_index=0.50,
    )
    return {
        "lower_id": lower["affiliate_id"],
        "upper_id": upper["affiliate_id"],
        "player_id": bundle["player_id"],
        "assignment_id": bundle["assignment_id"],
        "plan_id": plan["id"],
    }


def test_one_outing_blends_three_measures_and_takes_the_pinned_level_multiplier(api: ApiClient):
    """All three measure terms and the level multiplier land in one figure.

    PRD 3.7: "Each outing's raw contribution is a weighted blend of its three
    measures: fifty-five hundredths of the pitch count divided by one hundred,
    plus thirty hundredths of the innings figure divided by ten, plus fifteen
    hundredths of the conditioning minutes divided by sixty. That raw contribution
    is then multiplied by a level multiplier read from the owning assignment's
    pinned `level_at_assignment`: `SINGLE_A` multiplies by `1.00`, `HIGH_A` by
    `1.05`, `DOUBLE_A` by `1.12`, `TRIPLE_A` by `1.18`, `COMPLEX` by `1.25` and
    `DOMINICAN_ACADEMY` by `1.30`."  Rounding happens once, at the end — PRD 3.7:
    "No rounding is applied to any of this arithmetic; every intermediate term is
    carried as an exact decimal." — and with no `ACTIVE` plan the projected figure
    adds nothing, per PRD 3.7: "then adds a forward-looking plan allowance equal
    to the `workload_limit_weekly_index` of the player's `ACTIVE` development
    plan, or zero when the player has no `ACTIVE` plan, then rounds half-up to two
    decimal places and takes the smaller of that figure and `25.00`."

    Design: Corner/calculations/workload_index_sums_three_weighted_measures_with_the_level_multiplier
    """
    fixtures.set_clock(api, "2026-05-10T00:00:00Z")
    club = fixtures.licensed_affiliate(
        api,
        affiliate_overrides={
            "name": "Multiplier Club",
            "level": "HIGH_A",
            "market_city": "Beloit",
            "meal_stipend_cents_per_day": 2800,
        },
    )
    bundle = fixtures.active_assignment(
        api,
        club["affiliate_id"],
        player_overrides={
            "full_name": "Measure Mixer",
            "origin": "DOMESTIC_DRAFT",
            "signed_date": "2025-06-10",
        },
        effective_date="2026-05-01",
        end_date="2026-08-31",
    )
    assert bundle["assignment"]["level_at_assignment"] == "HIGH_A", (
        "the assignment pins the club level it was created at, got "
        f"{bundle['assignment']['level_at_assignment']!r}"
    )

    fixtures.log_outing(
        api,
        bundle["assignment_id"],
        "2026-05-10",
        pitches_thrown=90,
        innings_pitched=6.0,
        high_intensity_minutes=45,
    )

    player = fixtures.read_player(api, bundle["player_id"])
    assert_decimal(player["workload_index"], "0.83", 2, "Player.workload_index")
    assert_decimal(
        player["workload_index_projected"], "0.83", 2, "Player.workload_index_projected"
    )


def test_readiness_reaches_the_threshold_exactly_and_the_promotion_is_admitted(api: ApiClient):
    """One player, three readings of the score, and an inclusive boundary pass.

    PRD 3.7: "The score is then forty hundredths of the module ratio, plus
    twenty-five hundredths of the workload headroom, plus thirty-five hundredths
    of the service ratio — three weights that sum to exactly one — rounded
    half-up to four decimal places in a single final step, with every
    intermediate term carried as an exact decimal."  The three terms come from
    PRD 3.7: "The module ratio is `completed_module_count` divided by the number
    of members in `curriculum_modules`. The workload pressure is the player's
    `workload_index_projected` divided by the plan's `workload_limit_weekly_index`
    multiplied by a two-week pressure horizon, capped at one; the workload
    headroom is one minus that pressure, floored at zero. The service ratio is the
    player's `service_days_accrued` divided by 120, capped at one."  The move is
    then admitted at the boundary, because PRD 3.7 makes both floors inclusive:
    "The player's `promotion_readiness` must be at least `0.7500`, the threshold
    being inclusive so a score of exactly `0.7500` passes. The player's
    `service_days_accrued` must be at least 120, again inclusive."

    Design: Corner/calculations/promotion_readiness_lands_exactly_on_the_threshold_and_admits_the_move
    """
    bundle = _readiness_fixture(api, 120, "Lansing", "Akron")

    fixtures.dispose_plan(api, bundle["plan_id"], "ACTIVATE")
    at_activation = fixtures.read_player(api, bundle["player_id"])
    assert_decimal(
        at_activation["promotion_readiness"], "0.4750", 4, "Player.promotion_readiness"
    )

    progressed = fixtures.dispose_plan(
        api, bundle["plan_id"], "RECORD_PROGRESS", completed_module_count=1
    )
    assert_decimal(progressed["completion_pct"], "100.00", 2, "DevelopmentPlan.completion_pct")
    after_progress = fixtures.read_player(api, bundle["player_id"])
    assert_decimal(
        after_progress["promotion_readiness"], "0.8750", 4, "Player.promotion_readiness"
    )

    fixtures.log_outing(
        api,
        bundle["assignment_id"],
        "2026-04-01",
        pitches_thrown=100,
        innings_pitched=0.0,
        high_intensity_minutes=0,
    )
    at_threshold = fixtures.read_player(api, bundle["player_id"])
    assert_decimal(at_threshold["workload_index"], "0.55", 2, "Player.workload_index")
    assert_decimal(
        at_threshold["workload_index_projected"], "1.05", 2, "Player.workload_index_projected"
    )
    assert_decimal(
        at_threshold["promotion_readiness"], "0.7500", 4, "Player.promotion_readiness"
    )

    promotion = fixtures.create_assignment(
        api,
        bundle["player_id"],
        bundle["upper_id"],
        movement_reason="PROMOTION",
        effective_date="2026-05-01",
        end_date="2026-08-31",
        superseded_assignment_id=bundle["assignment_id"],
    )
    activated = fixtures.dispose_assignment(api, promotion["id"], "ACTIVATE")
    assert_status(activated, "ACTIVE", "PlayerAssignment")

    assert_status(
        fixtures.read_assignment(api, bundle["assignment_id"]), "COMPLETED", "PlayerAssignment"
    )
    lapsed = fixtures.plans_for(api, bundle["assignment_id"])
    assert_status(lapsed[0], "LAPSED", "DevelopmentPlan")

    promoted = fixtures.read_player(api, bundle["player_id"])
    assert_decimal(promoted["promotion_readiness"], "0.0000", 4, "Player.promotion_readiness")
    assert promoted["current_affiliate_id"] == bundle["upper_id"], (
        f"the mirror follows the live assignment, got {promoted['current_affiliate_id']!r}"
    )
    assert_integer(
        fixtures.read_affiliate(api, bundle["upper_id"])["active_roster_count"],
        1,
        "active_roster_count",
    )
    assert_integer(
        fixtures.read_affiliate(api, bundle["lower_id"])["active_roster_count"],
        0,
        "active_roster_count",
    )


def test_readiness_below_the_threshold_blocks_the_promotion_outright(api: ApiClient):
    """Sixty service days instead of one hundred and twenty, and the move is refused.

    PRD 3.7: "A promotion is admitted only when three conditions hold together.
    The player's `promotion_readiness` must be at least `0.7500`, the threshold
    being inclusive so a score of exactly `0.7500` passes."  The refusal is fixed,
    as is the moment it lands — PRD 3.7: "Any of the three failing produces
    `ERR_PROMOTION_CRITERIA_NOT_MET`, and both assignment creation and assignment
    activation enforce the check." — and PRD 3.6 repeats it for the create side:
    "A `PROMOTION` creation is additionally held to the full promotion criteria
    described in Section 3.7, and a movement that fails any of the three is
    refused with `ERR_PROMOTION_CRITERIA_NOT_MET`."

    Design: Corner/calculations/promotion_readiness_below_threshold_blocks_the_promotion_activation
    """
    bundle = _readiness_fixture(api, 60, "Lakeland", "Erie")

    fixtures.dispose_plan(api, bundle["plan_id"], "ACTIVATE")
    fixtures.dispose_plan(api, bundle["plan_id"], "RECORD_PROGRESS", completed_module_count=1)
    fixtures.log_outing(
        api,
        bundle["assignment_id"],
        "2026-04-01",
        pitches_thrown=100,
        innings_pitched=0.0,
        high_intensity_minutes=0,
    )

    unready = fixtures.read_player(api, bundle["player_id"])
    assert_decimal(unready["promotion_readiness"], "0.5750", 4, "Player.promotion_readiness")

    refused = _create_assignment(
        api,
        bundle["player_id"],
        bundle["upper_id"],
        movement_reason="PROMOTION",
        effective_date="2026-05-01",
        end_date="2026-08-31",
        superseded_assignment_id=bundle["assignment_id"],
    )
    validate_error(refused, ApiErrorId.ERR_PROMOTION_CRITERIA_NOT_MET.value, 422)

    assert_status(
        fixtures.read_assignment(api, bundle["assignment_id"]), "ACTIVE", "PlayerAssignment"
    )
    assert_integer(
        fixtures.read_affiliate(api, bundle["upper_id"])["active_roster_count"],
        0,
        "active_roster_count",
    )
    still_there = fixtures.read_player(api, bundle["player_id"])
    assert still_there["current_affiliate_id"] == bundle["lower_id"], (
        f"the refused move leaves the player where they were, got {still_there['current_affiliate_id']!r}"
    )
    assert_integer(still_there["option_years_used"], 1, "option_years_used")

    rows, meta = validate_paginated(
        api.list_assignments(FARM_DIRECTOR_HEADERS, {"player_id": bundle["player_id"]})
    )
    assert_integer(meta["total_count"], 1, "assignment total_count")
    assert rows[0]["id"] == bundle["assignment_id"], (
        f"the refused create must not have persisted a row, got {rows[0]['id']!r}"
    )


def test_the_facility_score_is_the_two_decimal_mean_of_the_latest_score_per_category(api: ApiClient):
    """Three categories, a repeating decimal mean, and one rounding step.

    PRD 2.9: "The affiliate's `facility_score` is the arithmetic mean of those
    per-category latest scores, rounded half-up to 2 decimal places; when the
    affiliate has no non-waived inspection at all, `facility_score` reads
    `100.00`."  The banding that decides the standing is PRD 2.9's: "Each
    inspection carries a `deficiency_level` derived from its `score` with
    inclusive boundaries: a score of 85 or above is `NONE`, a score from 70
    through 84 inclusive is `MINOR`, and a score of 69 or below is `MAJOR`."  Two
    open minor findings with no major one therefore land the club in the middle
    band, per PRD 2.9: "From these, `facility_status` is `DEFICIENT` when the
    open-major tally is at least 1; `PROVISIONAL` when the open-major tally is
    exactly 0 and the open-minor tally is at least 1; and `COMPLIANT` otherwise."

    Design: Corner/calculations/facility_score_is_the_two_decimal_mean_of_the_latest_review_per_category
    """
    fixtures.set_clock(api, "2026-03-01T00:00:00Z")
    club = fixtures.create_affiliate(
        api,
        COMPLIANCE_OFFICER_HEADERS,
        name="Precision Club",
        level="DOUBLE_A",
        market_city="Portland",
        meal_stipend_cents_per_day=2900,
    )

    clean = fixtures.file_facility_review(api, club["id"], "CLUBHOUSE", "2026-03-01", 85)
    assert_deficiency_banding(clean)
    assert_status(clean, "CLOSED", "FacilityStandardReview")
    assert clean["remediation_due_date"] is None, (
        f"a clean inspection waits for nobody, got {clean['remediation_due_date']!r}"
    )

    minor = fixtures.file_facility_review(api, club["id"], "WEIGHT_ROOM", "2026-03-01", 84)
    assert_deficiency_banding(minor)
    assert_status(minor, "OPEN", "FacilityStandardReview")
    assert minor["remediation_due_date"] == "2026-04-30", (
        f"a minor finding gives sixty days from the review date, got {minor['remediation_due_date']!r}"
    )

    fixtures.file_facility_review(api, club["id"], "FIELD_SURFACE", "2026-03-01", 84)

    affiliate = fixtures.read_affiliate(api, club["id"])
    assert_decimal(affiliate["facility_score"], "84.33", 2, "Affiliate.facility_score")
    assert_integer(
        affiliate["open_major_deficiency_count"], 0, "open_major_deficiency_count"
    )
    assert affiliate["facility_status"] == "PROVISIONAL", (
        f"two open minor findings and no major one is PROVISIONAL, got {affiliate['facility_status']!r}"
    )


def test_the_rollup_reads_only_the_latest_review_per_category_and_drops_a_waived_one(api: ApiClient):
    """One category, two reviews: the newer scores, the older still counts, the waiver clears it.

    PRD 2.9: "For the score roll-up, the server takes, for each inspected
    category, the single most recent inspection for that affiliate and category
    whose status is anything other than `WAIVED`, choosing the one with the
    greatest `review_date` and breaking a tie on `review_date` in favour of the
    later `created_at`."  The tallies read a different set — PRD 2.9: "Separately,
    `open_major_deficiency_count` is the number of the affiliate's inspections
    whose `deficiency_level` is `MAJOR` and whose status is `OPEN`,
    `REMEDIATION_SUBMITTED` or `REOPENED`, and the parallel minor tally counts
    inspections whose `deficiency_level` is `MINOR` in those same three statuses."
    — so the superseded finding still bites until it is waived, and PRD 3.1 says
    what the waiver does: "A waiver from `OPEN` records
    `waiver_granted_by_user_id` from the acting `X-User-ID`, drops the inspection
    out of both the `facility_score` mean and the deficiency tallies, and
    recomputes `facility_status`."

    Design: Corner/calculations/facility_rollup_takes_the_latest_per_category_and_drops_waived_reviews
    """
    fixtures.set_clock(api, "2026-04-01T00:00:00Z")
    club = fixtures.create_affiliate(
        api,
        COMPLIANCE_OFFICER_HEADERS,
        name="Filter Club",
        level="HIGH_A",
        market_city="Aberdeen",
        meal_stipend_cents_per_day=2800,
    )
    older = fixtures.file_facility_review(api, club["id"], "CLUBHOUSE", "2026-03-01", 80)
    assert_deficiency_banding(older)
    assert_status(older, "OPEN", "FacilityStandardReview")

    fixtures.file_facility_review(api, club["id"], "CLUBHOUSE", "2026-04-01", 90)

    before = fixtures.read_affiliate(api, club["id"])
    assert_decimal(before["facility_score"], "90.00", 2, "Affiliate.facility_score")
    assert before["facility_status"] == "PROVISIONAL", (
        "the superseded minor finding is still open, so the club is PROVISIONAL, got "
        f"{before['facility_status']!r}"
    )

    waived = fixtures.dispose_facility_review(
        api, older["id"], "WAIVE", note="temporary clubhouse works accepted by the league"
    )
    assert_status(waived, "WAIVED", "FacilityStandardReview")
    assert waived["waiver_granted_by_user_id"] == COMPLIANCE_OFFICER_USER_ID, (
        f"the waiver stamps its grantor, got {waived['waiver_granted_by_user_id']!r}"
    )

    after = fixtures.read_affiliate(api, club["id"])
    assert_decimal(after["facility_score"], "90.00", 2, "Affiliate.facility_score")
    assert after["facility_status"] == "COMPLIANT", (
        f"the waiver clears the last open finding, got {after['facility_status']!r}"
    )

    rows, meta = validate_paginated(
        api.list_facility_reviews(club["id"], COMPLIANCE_OFFICER_HEADERS, {"status": "WAIVED"})
    )
    assert_integer(meta["total_count"], 1, "facility-review total_count")
    assert rows[0]["id"] == older["id"], (
        f"the waived row is retained, only excluded from the arithmetic, got {rows[0]['id']!r}"
    )


def test_the_roster_and_rehab_counters_aggregate_separately_over_active_rows_only(api: ApiClient):
    """A level bed and a rehab slot at one club, filled and emptied independently.

    PRD 3.6: "The counters themselves are pure aggregations over the club's
    assignment rows. `active_roster_count` is the number of assignments at the
    club with status `ACTIVE` and type `LEVEL` or `COMPLEX`. `rehab_assignment_count`
    is the number at the club with status `ACTIVE` and type `REHAB`."  Only live
    rows occupy anything, per PRD 3.6: "Only `ACTIVE` assignments occupy a slot:
    rows in `PENDING_CLEARANCE`, `SUSPENDED`, `COMPLETED` or `REVOKED` release
    their slot immediately."  The rehab activation also leaves the roster
    dimension alone and charges nothing, because PRD 3.6 conditions both effects
    on the type: "When the assignment is `LEVEL` or `COMPLEX` and its
    `projected_optional_days` is 20 or more, the server charges an option year"
    and "For a `LEVEL` or `COMPLEX` assignment, the player's `roster_status`
    advances to `ACTIVE` and `current_affiliate_id` is set to the receiving club."

    Design: Corner/calculations/roster_counters_count_only_active_assignments_and_split_by_type
    """
    fixtures.set_clock(api, "2026-04-01T00:00:00Z")
    club = fixtures.licensed_affiliate(
        api,
        affiliate_overrides={
            "name": "Counter Club",
            "level": "DOUBLE_A",
            "market_city": "Midland",
            "meal_stipend_cents_per_day": 2900,
        },
    )
    level_player = fixtures.cleared_player(
        api,
        clearance_type="LEVEL_ASSIGNMENT",
        full_name="Level Larry",
        origin="DOMESTIC_DRAFT",
        signed_date="2025-06-10",
    )
    rehab_player = fixtures.cleared_player(
        api,
        clearance_type="REHAB_START",
        cleared_workload_ceiling_index=8.00,
        full_name="Rehab Rita",
        origin="DOMESTIC_DRAFT",
        signed_date="2025-06-11",
    )

    level_assignment = fixtures.create_assignment(
        api,
        level_player["player_id"],
        club["affiliate_id"],
        effective_date="2026-04-01",
        end_date="2026-06-30",
    )
    assert_integer(
        fixtures.read_affiliate(api, club["affiliate_id"])["active_roster_count"],
        0,
        "active_roster_count",
    )
    fixtures.dispose_assignment(api, level_assignment["id"], "ACTIVATE")

    rehab_assignment = fixtures.create_assignment(
        api,
        rehab_player["player_id"],
        club["affiliate_id"],
        assignment_type="REHAB",
        movement_reason="REHAB_START",
        effective_date="2026-04-05",
        end_date="2026-05-05",
    )
    activated_rehab = fixtures.dispose_assignment(api, rehab_assignment["id"], "ACTIVATE")
    assert activated_rehab["option_year_charged"] is False, (
        f"a rehab assignment charges no option year, got {activated_rehab!r}"
    )

    both = fixtures.read_affiliate(api, club["affiliate_id"])
    assert_integer(both["active_roster_count"], 1, "active_roster_count")
    assert_integer(both["rehab_assignment_count"], 1, "rehab_assignment_count")

    rehabbing = fixtures.read_player(api, rehab_player["player_id"])
    assert rehabbing["roster_status"] == "RESERVE_LIST", (
        f"a rehab activation leaves the roster dimension alone, got {rehabbing['roster_status']!r}"
    )
    assert_integer(rehabbing["option_years_used"], 0, "option_years_used")

    fixtures.dispose_assignment(api, level_assignment["id"], "COMPLETE")

    after = fixtures.read_affiliate(api, club["affiliate_id"])
    assert_integer(after["active_roster_count"], 0, "active_roster_count")
    assert_integer(after["rehab_assignment_count"], 1, "rehab_assignment_count")
    assert_integer(
        fixtures.read_player(api, level_player["player_id"])["option_years_used"],
        1,
        "option_years_used",
    )


def test_the_late_filing_fee_is_priced_across_two_marginal_tiers(api: ApiClient):
    """Six days late costs two days at fifty dollars and four at one hundred and fifty.

    PRD 3.8: "The fee written to `late_fee_cents` is the sum of the three segment
    amounts: 5000 multiplied by the smaller of the days late and two, plus 15000
    multiplied by the days late minus two clamped to lie between zero and five,
    plus 30000 multiplied by the days late minus seven floored at zero."  The
    deadline and the day count are PRD 3.8's too: "A report's `filing_deadline` is
    two days after the producing assignment's `effective_date`." and "The number
    of days late is the reference date minus the deadline in whole days, floored
    at zero, and `is_late` reads true whenever that count is positive."  Filing is
    what prices the row, per PRD 3.8: "Filing records `certified_by_user_id` from
    the acting `X-User-ID` and stamps `filed_at` with the logical clock instant,
    then recomputes `is_late` and writes `late_fee_cents`."

    Design: Corner/calculations/late_filing_fee_crosses_from_tier_one_into_tier_two
    """
    fixtures.set_clock(api, "2026-04-01T00:00:00Z")
    club = fixtures.licensed_affiliate(
        api,
        affiliate_overrides={
            "name": "Filing Club",
            "level": "HIGH_A",
            "market_city": "Dayton",
            "meal_stipend_cents_per_day": 2800,
        },
    )
    late_bundle = fixtures.active_assignment(
        api,
        club["affiliate_id"],
        player_overrides={
            "full_name": "Late Filing Player",
            "origin": "DOMESTIC_DRAFT",
            "signed_date": "2025-06-10",
        },
        effective_date="2026-04-01",
        end_date="2026-06-30",
    )
    late_report = fixtures.reports_for(api, late_bundle["assignment_id"])[0]
    assert late_report["filing_deadline"] == "2026-04-03", (
        f"the deadline is two days after the effective date, got {late_report['filing_deadline']!r}"
    )
    assert late_report["transaction_type"] == "OPTIONAL_ASSIGNMENT", (
        f"an INITIAL movement files as an optional assignment, got {late_report['transaction_type']!r}"
    )
    assert late_report["initiated_by_user_id"] == FARM_DIRECTOR_USER_ID, (
        f"the report copies its initiator, got {late_report['initiated_by_user_id']!r}"
    )

    fixtures.set_clock(api, "2026-04-09T00:00:00Z")
    filed = fixtures.dispose_report(api, late_report["id"], "FILE")
    assert_status(filed, "FILED", "TransactionReport")
    assert filed["is_late"] is True, f"six days past the deadline is late, got {filed!r}"
    assert_money(filed["late_fee_cents"], 70000, "late_fee_cents")
    assert filed["certified_by_user_id"] == COMPLIANCE_OFFICER_USER_ID, (
        f"filing stamps its certifier, got {filed['certified_by_user_id']!r}"
    )
    assert_iso_timestamp(filed["filed_at"], "TransactionReport.filed_at")

    prompt_bundle = fixtures.active_assignment(
        api,
        club["affiliate_id"],
        player_overrides={
            "full_name": "Prompt Filing Player",
            "origin": "DOMESTIC_DRAFT",
            "signed_date": "2025-06-12",
        },
        effective_date="2026-04-09",
        end_date="2026-07-31",
    )
    prompt_report = fixtures.reports_for(api, prompt_bundle["assignment_id"])[0]
    assert prompt_report["filing_deadline"] == "2026-04-11", (
        f"the second deadline is two days out as well, got {prompt_report['filing_deadline']!r}"
    )

    prompt_filed = fixtures.dispose_report(api, prompt_report["id"], "FILE")
    assert prompt_filed["is_late"] is False, (
        f"filing two days early is not late, got {prompt_filed!r}"
    )
    assert_money(prompt_filed["late_fee_cents"], 0, "late_fee_cents")


def test_a_nineteen_day_window_charges_nothing_while_a_twenty_day_one_charges(api: ApiClient):
    """The inclusive day count straddles the constant, one day on each side.

    PRD 3.6: "`projected_optional_days` is computed as the number of days from
    `effective_date` to `end_date` plus one, so a single-day assignment projects
    one optional day and a thirty-day window projects thirty."  The charge is
    inclusive at twenty, per PRD 3.6: "When the assignment is `LEVEL` or `COMPLEX`
    and its `projected_optional_days` is 20 or more, the server charges an option
    year: it creates an option-year record in status `CHARGED` whose
    `triggering_assignment_id` is this assignment, whose `season_year` is the
    calendar year of the assignment's `effective_date`, whose `optional_days`
    snapshots the assignment's `projected_optional_days` at charge time, and whose
    `charged_at` is the current logical clock instant; the assignment's
    `option_year_charged` flips to true."  Both windows still fill a roster slot,
    because PRD 3.6 makes occupancy a function of status and type alone:
    "`active_roster_count` is the number of assignments at the club with status
    `ACTIVE` and type `LEVEL` or `COMPLEX`."

    Design: Corner/calculations/option_year_charge_boundary_at_nineteen_and_twenty_optional_days
    """
    fixtures.set_clock(api, "2026-04-01T00:00:00Z")
    club = fixtures.licensed_affiliate(
        api,
        affiliate_overrides={
            "name": "Boundary Club",
            "level": "SINGLE_A",
            "market_city": "Clearwater",
            "meal_stipend_cents_per_day": 2600,
        },
    )
    below = fixtures.pending_assignment(
        api,
        club["affiliate_id"],
        player_overrides={
            "full_name": "Nineteen Days",
            "origin": "DOMESTIC_DRAFT",
            "signed_date": "2025-06-10",
        },
        effective_date="2026-04-01",
        end_date="2026-04-19",
    )
    assert_integer(
        fixtures.read_assignment(api, below["assignment_id"])["projected_optional_days"],
        19,
        "projected_optional_days",
    )
    activated_below = fixtures.dispose_assignment(api, below["assignment_id"], "ACTIVATE")
    assert activated_below["option_year_charged"] is False, (
        f"nineteen days sits below the threshold, got {activated_below!r}"
    )

    lean_player = fixtures.read_player(api, below["player_id"])
    assert_integer(lean_player["option_years_used"], 0, "option_years_used")
    assert_integer(lean_player["option_years_remaining"], 3, "option_years_remaining")
    _, below_meta = validate_paginated(
        api.list_option_years(below["assignment_id"], FARM_DIRECTOR_HEADERS)
    )
    assert_integer(below_meta["total_count"], 0, "option-year total_count")

    at_threshold = fixtures.pending_assignment(
        api,
        club["affiliate_id"],
        player_overrides={
            "full_name": "Twenty Days",
            "origin": "DOMESTIC_DRAFT",
            "signed_date": "2025-06-11",
        },
        effective_date="2026-04-01",
        end_date="2026-04-20",
    )
    assert_integer(
        fixtures.read_assignment(api, at_threshold["assignment_id"])["projected_optional_days"],
        20,
        "projected_optional_days",
    )
    activated_at = fixtures.dispose_assignment(api, at_threshold["assignment_id"], "ACTIVATE")
    assert activated_at["option_year_charged"] is True, (
        f"twenty days reaches the threshold, got {activated_at!r}"
    )

    charged_player = fixtures.read_player(api, at_threshold["player_id"])
    assert_integer(charged_player["option_years_used"], 1, "option_years_used")
    assert_integer(charged_player["option_years_remaining"], 2, "option_years_remaining")

    rows = fixtures.option_years_for(api, at_threshold["assignment_id"])
    assert len(rows) == 1, f"the charge writes exactly one record, got {rows}"
    assert_status(rows[0], "CHARGED", "OptionYearRecord")
    assert_integer(rows[0]["season_year"], 2026, "season_year")
    assert_integer(rows[0]["optional_days"], 20, "optional_days")

    assert_integer(
        fixtures.read_affiliate(api, club["affiliate_id"])["active_roster_count"],
        2,
        "active_roster_count",
    )


def test_a_cap_with_headroom_leaves_both_cap_variants_overflow_free(api: ApiClient):
    """Every club line fits under both the shared bucket and its own sub-cap.

    PRD 3.3: "The per-category club line is therefore the gross figure for that
    category multiplied by that category's club share, rounded half-up to a whole
    number of cents."  The submission drains one shared bucket, per PRD 3.3: "When
    all four categories have been walked, `provisional_club_obligation_cents` is
    the running allocation, and `affiliate_overflow_cents` is the sum of the four
    club lines minus that allocation."  The settlement instead splits it, per PRD
    3.3: "Each category's final line is then the smaller of its club line and its
    own sub-cap. `final_club_obligation_cents` is the sum of the four final lines,
    and `affiliate_overflow_cents` is overwritten with the sum of the four club
    lines minus the sum of the four final lines."  With 2600000 of cap against
    lines of 750000, 540000, 400000 and 200000 neither mechanism bites, so both
    obligations land on 1890000 with zero overflow.

    Design: Corner/calculations/expense_cap_headroom_leaves_no_overflow_in_either_variant
    """
    fixtures.set_clock(api, "2026-08-01T00:00:00Z")
    affiliate = fixtures.create_affiliate(
        api,
        name="Headroom Club",
        level="TRIPLE_A",
        market_city="Toledo",
        meal_stipend_cents_per_day=3300,
    )
    agreement = fixtures.create_agreement(
        api,
        affiliate["id"],
        facility_standard_tier="TIER_1",
        club_reimbursement_cap_cents=2600000,
        minimum_active_players=0,
        housing_expense_cents=1000000,
        meal_expense_cents=900000,
        travel_expense_cents=400000,
        upkeep_expense_cents=800000,
    )

    submitted = fixtures.submit_agreement(api, agreement["id"], affiliate["id"])
    assert_status(submitted, "SUBMITTED", "AffiliationAgreement")
    assert_money(
        submitted["provisional_club_obligation_cents"], 1890000, "provisional_club_obligation_cents"
    )
    assert_money(submitted["affiliate_overflow_cents"], 0, "affiliate_overflow_cents")

    fixtures.activate_agreement(api, agreement["id"])
    settled = fixtures.dispose_agreement(api, agreement["id"], "SETTLE")

    assert_status(settled, "ACTIVE", "AffiliationAgreement")
    assert settled["settlement_status"] == "SETTLED", (
        f"settlement moves the ledger flag only, got {settled['settlement_status']!r}"
    )
    assert_money(settled["final_club_obligation_cents"], 1890000, "final_club_obligation_cents")
    assert_money(settled["affiliate_overflow_cents"], 0, "affiliate_overflow_cents")
    for field in (
        "audited_housing_expense_cents",
        "audited_meal_expense_cents",
        "audited_travel_expense_cents",
        "audited_upkeep_expense_cents",
    ):
        assert settled[field] is None, (
            f"an unsupplied audited figure stays null, got {field}={settled[field]!r}"
        )
