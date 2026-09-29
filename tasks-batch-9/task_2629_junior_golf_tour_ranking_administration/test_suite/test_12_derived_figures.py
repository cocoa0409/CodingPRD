"""The derived numbers: field quality, means testing, pace, differentials, order."""

from prd_bench_local_runner.testing import validate_success

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.assertions import (
    assert_cents,
    assert_entry_status,
    assert_ledger,
    assert_member_eligibility,
    assert_one_decimal,
    assert_slot_census,
    assert_tournament_status,
    assert_two_decimals,
)
from test_helpers.constants import PER_MEMBER_CAP_CENTS, SEASON_ASSISTANCE_BUDGET_CENTS
from test_helpers.test_users import (
    CHIEF_REFEREE,
    RULES_OFFICIAL,
    TOUR_ADMIN,
    member_headers,
)
from test_helpers.types import (
    AID_APPROVED,
    AID_DECISION_APPROVED,
    DISPOSITION_PENALTY_STROKES,
    ELIGIBILITY_VERIFIED,
    ENTRY_ACCEPTED,
    ENTRY_FINISHED,
    ENTRY_WAITLISTED,
    ENTRY_WITHDRAWN,
    EXEMPTION_SPONSOR_INVITE,
    GRANT_ACTIVE,
    GRANT_CONSUMED,
    INCIDENT_ABUSIVE_LANGUAGE,
    INCIDENT_COACHING_VIOLATION,
    PACE_WARNING,
    PEER_VERIFY,
    ROUND_CERTIFIED,
    RULES_CASE_UPHELD,
    RULES_DECISION_UPHELD,
    SANCTION_VENUE_BAN_ONE_EVENT,
    SANCTION_WARNING,
    TIER_LOCAL,
    TOURNAMENT_COMPLETED,
)


class TestFieldQualityAndMeansTesting:
    def test_small_field_earns_no_negative_depth_credit(self, api):
        """A two-player field sits below the depth floor, so the factor is 1.00.

        PRD: "The factor then starts at a baseline of 1.00, adds 0.02 for each
        top-fifty entrant, and adds a further 0.01 for each entrant in the field
        beyond the first twelve (so a field of twelve or fewer earns no depth
        credit at all, and a field of twenty earns eight increments)."

        Design: Corner/calculations/field_quality_depth_term_clamps_at_zero_below_the_floor
        """
        ctx = fx.field_set(api, 2)

        assert_slot_census(ctx["tournament"], accepted_count=2)
        assert_two_decimals(ctx["tournament"]["field_quality_factor"], 1.00,
                            "field_quality_factor")
        assert ctx["tournament"]["field_quality_factor"] != 0.90
        assert ctx["entries"][0]["rank_at_entry"] is None
        assert_two_decimals(
            fx.read_tournament(api, ctx["tournament_id"])["field_quality_factor"],
            1.00, "field_quality_factor",
        )

    def test_income_exactly_on_a_band_ceiling_stays_in_the_richer_band(self, api):
        """One cent past the ceiling drops the household a whole band.

        PRD: "From that figure the `covered_pct` — the share of a fee the
        association will cover — follows as a five-band lookup: an income per
        dependent at or below 1,500,000 cents (fifteen thousand dollars) covers
        the whole fee, giving a `covered_pct` of 1.00; at or below 2,500,000 cents
        it covers 0.90; at or below 4,500,000 cents it covers 0.65; at or below
        7,000,000 cents it covers 0.40; and anything above 7,000,000 cents covers
        nothing at all, giving a `covered_pct` of 0.00, which blocks approval
        outright."

        Design: Corner/calculations/assistance_covered_pct_at_the_second_income_ceiling
        """
        ctx = fx.verified_roster(api, 2)
        on_the_ceiling = fx.submit_aid_application(
            api, ctx["member_ids"][0], ctx["season_id"],
            household_income_cents=2500000, dependents=1,
        )
        one_cent_over = fx.submit_aid_application(
            api, ctx["member_ids"][1], ctx["season_id"],
            household_income_cents=2500001, dependents=1,
        )
        assert_cents(on_the_ceiling["income_per_dependent_cents"], 2500000,
                     "income_per_dependent_cents")
        assert_cents(one_cent_over["income_per_dependent_cents"], 2500001,
                     "income_per_dependent_cents")

        richer_band = validate_success(
            api.decide_aid_application(
                on_the_ceiling["id"], f.aid_decision_payload(AID_DECISION_APPROVED),
                TOUR_ADMIN,
            ),
            200,
        )
        poorer_band = validate_success(
            api.decide_aid_application(
                one_cent_over["id"], f.aid_decision_payload(AID_DECISION_APPROVED),
                TOUR_ADMIN,
            ),
            200,
        )

        assert richer_band["status"] == AID_APPROVED
        assert_two_decimals(richer_band["covered_pct"], 0.90, "covered_pct")
        assert_cents(richer_band["estimated_award_cents"], 22500,
                     "estimated_award_cents")
        assert richer_band["estimated_award_cents"] != 16250
        assert_two_decimals(poorer_band["covered_pct"], 0.65, "covered_pct")
        assert_cents(poorer_band["estimated_award_cents"], 16250,
                     "estimated_award_cents")
        assert_cents(richer_band["per_member_cap_cents"], PER_MEMBER_CAP_CENTS,
                     "per_member_cap_cents")
        assert_cents(richer_band["consumed_cents"], 0, "consumed_cents")
        assert_ledger(fx.read_season(api, ctx["season_id"]),
                      available=SEASON_ASSISTANCE_BUDGET_CENTS, committed=0)


class TestPaceAndScoringArithmetic:
    def test_pace_penalty_never_exceeds_three_strokes(self, api):
        """Six warnings plus a quarter-hour breach still costs only three strokes.

        PRD: "`pace_penalty_strokes` is the sum of the two components, capped at 3
        strokes no matter how badly the group behaved."

        Design: Corner/calculations/pace_penalty_is_capped_at_three_strokes
        """
        ctx = fx.scheduled_round(api)
        readings = []
        for minutes in (4, 6, 8, 10, 20, 12):
            readings.append(
                validate_success(
                    api.record_pace_observation(
                        ctx["round_id"],
                        f.pace_observation_payload(PACE_WARNING, minutes),
                        RULES_OFFICIAL,
                    ),
                    200,
                )
            )

        assert readings[1]["pace_penalty_strokes"] == 0
        assert readings[2]["pace_penalty_strokes"] == 1
        assert readings[4]["pace_penalty_strokes"] == 3
        assert readings[4]["max_minutes_behind"] == 20
        assert readings[5]["pace_warning_count"] == 6
        assert readings[5]["pace_penalty_strokes"] == 3
        assert readings[5]["pace_penalty_strokes"] != 6
        card = validate_success(
            api.submit_score(ctx["round_id"], f.score_payload(70),
                             member_headers(ctx["member_ids"][0])),
            200,
        )
        assert card["adjusted_gross"] == 73
        validate_success(
            api.peer_verify(ctx["round_id"], f.peer_verify_payload(PEER_VERIFY),
                            member_headers(ctx["member_ids"][1])),
            200,
        )
        certified = validate_success(api.certify_round(ctx["round_id"], RULES_OFFICIAL), 200)

        assert_one_decimal(certified["scoring_differential"], 1.4, "scoring_differential")
        assert certified["scoring_differential"] != 4.1
        assert certified["pace_penalty_strokes"] == 3
        assert_one_decimal(
            fx.read_entry(api, ctx["entry_ids"][0])["avg_scoring_differential"], 1.4,
            "avg_scoring_differential",
        )

    def test_negative_differential_rounds_half_up_on_magnitude(self, api):
        """A 71 card on this course stores −0.4, not a truncated −0.3.

        PRD: "`scoring_differential` is then derived from that adjusted total by
        subtracting the tournament's `course_rating`, multiplying the remainder by
        the standard slope of 113, dividing by the tournament's `slope_rating`, and
        rounding the result half up to one decimal place."

        Design: Corner/calculations/scoring_differential_rounds_half_up_and_never_truncates
        """
        ctx = fx.tournament_in_progress(
            api, 2, name="Sandhills One-Day", round_count=1, end_date="2026-09-10",
        )

        certified = fx.play_round(
            api, ctx, 0, 1, 1, fx.TEE_TIME_ROUND_ONE, 71, certify=True
        )

        assert certified["status"] == ROUND_CERTIFIED
        assert certified["adjusted_gross"] == 71
        assert_one_decimal(certified["scoring_differential"], -0.4,
                           "scoring_differential")
        assert certified["scoring_differential"] != -0.3
        entry = fx.read_entry(api, ctx["entry_ids"][0])
        assert_one_decimal(entry["avg_scoring_differential"], -0.4,
                           "avg_scoring_differential")
        assert entry["certified_round_count"] == 1
        assert_entry_status(entry, ENTRY_FINISHED)


class TestOrderingAndAggregation:
    def test_equal_totals_are_split_by_penalty_strokes_not_gross_score(self, api):
        """The cleaner card places higher when the aggregates match.

        PRD: "The finishers are sorted ascending on four components in turn:
        `total_adjusted_strokes` ascending, so the lowest aggregate score wins;
        then the sum of `rules_penalty_strokes` across that entry's `CERTIFIED`
        rounds ascending, so that between two golfers on the same total the one who
        took fewer penalty strokes places higher; then `submitted_at` ascending;
        then `created_at` ascending."

        Design: Corner/calculations/finish_position_tie_breaks_on_rules_penalty_strokes
        """
        ctx = fx.verified_roster(api, 2)
        clean_member, penalised_member = ctx["member_ids"]
        tournament = fx.create_tournament(
            api, ctx["season_id"], name="Sandhills One-Day", round_count=1,
            end_date="2026-09-10",
        )
        validate_success(api.open_entries(tournament["id"], TOUR_ADMIN), 200)
        penalised_entry = fx.submit_entry(api, penalised_member, tournament["id"])
        clean_entry = fx.submit_entry(api, clean_member, tournament["id"])
        fx.set_clock(api, fx.CLOCK_AFTER_ENTRY_CLOSE)
        validate_success(api.close_entries(tournament["id"], TOUR_ADMIN), 200)
        validate_success(api.set_field(tournament["id"], TOUR_ADMIN), 200)
        fx.pay_entry(api, clean_member, clean_entry["id"])
        fx.pay_entry(api, penalised_member, penalised_entry["id"])
        fx.set_clock(api, fx.CLOCK_ROUND_ONE)
        validate_success(api.start_tournament(tournament["id"], TOUR_ADMIN), 200)
        clean_round = fx.create_round(
            api, clean_entry["id"], penalised_member, 1, fx.TEE_TIME_ROUND_ONE
        )
        penalised_round = fx.create_round(
            api, penalised_entry["id"], clean_member, 1, fx.TEE_TIME_ROUND_ONE
        )
        validate_success(
            api.submit_score(clean_round["id"], f.score_payload(71),
                             member_headers(clean_member)),
            200,
        )
        validate_success(
            api.submit_score(penalised_round["id"], f.score_payload(70),
                             member_headers(penalised_member)),
            200,
        )
        validate_success(
            api.peer_verify(clean_round["id"], f.peer_verify_payload(PEER_VERIFY),
                            member_headers(penalised_member)),
            200,
        )
        validate_success(
            api.peer_verify(penalised_round["id"], f.peer_verify_payload(PEER_VERIFY),
                            member_headers(clean_member)),
            200,
        )
        case = validate_success(
            api.report_rules_case(
                f.rules_case_payload(
                    penalised_round["id"], DISPOSITION_PENALTY_STROKES, 1,
                    rule_reference="Rule 10.2 - advice from the caddie",
                ),
                RULES_OFFICIAL,
            ),
            201,
        )
        adjudicated = validate_success(
            api.adjudicate_rules_case(
                case["id"],
                f.adjudication_payload(
                    RULES_DECISION_UPHELD, disposition=DISPOSITION_PENALTY_STROKES,
                    penalty_strokes_applied=1,
                ),
                CHIEF_REFEREE,
            ),
            200,
        )
        assert adjudicated["status"] == RULES_CASE_UPHELD
        penalised_card = fx.read_round(api, penalised_round["id"])
        assert penalised_card["rules_penalty_strokes"] == 1
        assert penalised_card["adjusted_gross"] == 71
        assert penalised_card["open_rules_case_count"] == 0
        validate_success(api.certify_round(clean_round["id"], RULES_OFFICIAL), 200)

        validate_success(api.certify_round(penalised_round["id"], RULES_OFFICIAL), 200)

        completed = fx.read_tournament(api, tournament["id"])
        assert_tournament_status(completed, TOURNAMENT_COMPLETED)
        clean_final = fx.read_entry(api, clean_entry["id"])
        penalised_final = fx.read_entry(api, penalised_entry["id"])
        assert clean_final["total_adjusted_strokes"] == 71
        assert penalised_final["total_adjusted_strokes"] == 71
        assert clean_final["finish_position"] == 1
        assert penalised_final["finish_position"] == 2
        assert completed["winner_entry_id"] == clean_entry["id"]

    def test_a_waitlisted_departure_renumbers_but_promotes_nobody(self, api):
        """Losing a waitlisted entry frees no playing slot.

        PRD: "Withdrawing a `WAITLISTED` entry, possible while the tournament is
        `ENTRY_CLOSED` or `FIELD_SET`, moves it `WAITLISTED → WITHDRAWN`, stamps
        `withdrawn_at`, clears its `waitlist_position`, renumbers the surviving
        waitlist positions to run 1 upward again while preserving their relative
        order, decrements `waitlist_count` and increments `closed_count`."

        Design: Corner/calculations/waitlisted_withdrawal_renumbers_without_promoting
        """
        ctx = fx.verified_roster(api, 3)
        tournament = fx.create_tournament(api, ctx["season_id"], field_size_limit=1)
        validate_success(api.open_entries(tournament["id"], TOUR_ADMIN), 200)
        entries = []
        for index, member_id in enumerate(ctx["member_ids"]):
            fx.set_clock(api, "2026-08-10T0%d:00:00Z" % index)
            entries.append(fx.submit_entry(api, member_id, tournament["id"]))
        fx.set_clock(api, fx.CLOCK_AFTER_ENTRY_CLOSE)
        validate_success(api.close_entries(tournament["id"], TOUR_ADMIN), 200)
        field = validate_success(api.set_field(tournament["id"], TOUR_ADMIN), 200)
        assert_slot_census(field, accepted_count=1, waitlist_count=2)
        assert fx.read_entry(api, entries[2]["id"])["waitlist_position"] == 2
        fx.set_clock(api, "2026-09-02T00:00:00Z")

        withdrawn = validate_success(
            api.withdraw_entry(
                entries[1]["id"], f.withdrawal_payload("junior prom"),
                member_headers(ctx["member_ids"][1]),
            ),
            200,
        )

        assert_entry_status(withdrawn, ENTRY_WITHDRAWN)
        assert withdrawn["waitlist_position"] is None
        assert_entry_status(fx.read_entry(api, entries[0]["id"]), ENTRY_ACCEPTED)
        survivor = fx.read_entry(api, entries[2]["id"])
        assert_entry_status(survivor, ENTRY_WAITLISTED)
        assert survivor["waitlist_position"] == 1
        assert_slot_census(
            fx.read_tournament(api, tournament["id"]),
            entry_count=3, accepted_count=1, waitlist_count=1, closed_count=1,
            open_slot_count=0,
        )
        assert fx.read_member(api, ctx["member_ids"][1])["late_withdrawal_count"] == 0

    def test_priority_band_zero_beats_the_earlier_open_entrant(self, api):
        """The exemption holder takes the only slot despite entering later.

        PRD: "The first component is the entry's frozen `priority_band`, so band 0
        sorts ahead of band 1, which sorts ahead of band 2."

        Design: Corner/calculations/priority_band_zero_exemption_outranks_the_earlier_unranked_entry
        """
        ctx = fx.verified_roster(api, 2, clock="2026-08-06T00:00:00Z")
        exempt_member, open_member = ctx["member_ids"]
        tournament = fx.create_tournament(api, ctx["season_id"], field_size_limit=1)
        grant = fx.create_exemption_grant(
            api, exempt_member, tournament["id"], EXEMPTION_SPONSOR_INVITE,
            "2026-09-01T00:00:00Z",
        )
        assert grant["status"] == GRANT_ACTIVE
        validate_success(api.open_entries(tournament["id"], TOUR_ADMIN), 200)
        fx.set_clock(api, "2026-08-10T00:00:00Z")
        open_entry = fx.submit_entry(api, open_member, tournament["id"])
        fx.set_clock(api, "2026-08-11T00:00:00Z")
        exempt_entry = fx.submit_entry(
            api, exempt_member, tournament["id"], exemption_grant_id=grant["id"]
        )
        assert open_entry["priority_band"] == 2
        assert exempt_entry["priority_band"] == 0
        fx.set_clock(api, fx.CLOCK_AFTER_ENTRY_CLOSE)
        validate_success(api.close_entries(tournament["id"], TOUR_ADMIN), 200)

        field = validate_success(api.set_field(tournament["id"], TOUR_ADMIN), 200)

        assert_slot_census(field, accepted_count=1, waitlist_count=1, open_slot_count=0)
        accepted = fx.read_entry(api, exempt_entry["id"])
        assert_entry_status(accepted, ENTRY_ACCEPTED)
        assert accepted["waitlist_position"] is None
        queued = fx.read_entry(api, open_entry["id"])
        assert_entry_status(queued, ENTRY_WAITLISTED)
        assert queued["waitlist_position"] == 1
        consumed = validate_success(api.get_exemption_grant(grant["id"], TOUR_ADMIN), 200)
        assert consumed["status"] == GRANT_CONSUMED
        assert consumed["consumed_by_entry_id"] == exempt_entry["id"]


class TestConductPointDecay:
    def test_a_sanction_older_than_a_year_no_longer_counts(self, api):
        """Prior history decays, so the second sanction only bans.

        PRD: "Prior history is then added, but it decays: the prior total is the
        sum of `points_assessed` across the junior's *other* conduct cases whose
        `status` is `SANCTIONED` and whose `decided_at` falls within the 365 days
        before the logical clock."

        Design: Corner/calculations/conduct_points_ignore_cases_decided_outside_the_decay_window
        """
        ctx = fx.verified_roster(api, 1)
        member_id = ctx["member_ids"][0]
        tournament = fx.create_tournament(
            api, ctx["season_id"], builder=f.october_tournament_payload,
            name="Piedmont Local", tier=TIER_LOCAL, entry_fee_cents=15000,
            course_rating=70.0, slope_rating=120,
        )
        fx.set_clock(api, "2026-08-12T00:00:00Z")
        old_case = fx.file_conduct_case(
            api, member_id, tournament["id"], INCIDENT_COACHING_VIOLATION,
            subject_name="Marcus Stone",
            narrative="signalled club selection from outside the ropes",
        )
        old_decision = fx.sanction_conduct_case(api, old_case["id"])
        assert old_decision["cumulative_points_at_decision"] == 2
        assert old_decision["sanction_tier"] == SANCTION_WARNING
        fx.set_clock(api, "2027-08-13T00:00:00Z")
        fresh_case = fx.file_conduct_case(
            api, member_id, tournament["id"], INCIDENT_ABUSIVE_LANGUAGE,
            subject_name="Marcus Stone",
            narrative="abused a volunteer scorer in the recording area",
        )

        decided = fx.sanction_conduct_case(api, fresh_case["id"])

        assert decided["points_assessed"] == 3
        assert decided["cumulative_points_at_decision"] == 3
        assert decided["cumulative_points_at_decision"] != 5
        assert decided["sanction_tier"] == SANCTION_VENUE_BAN_ONE_EVENT
        member = fx.read_member(api, member_id)
        assert member["conduct_points"] == 3
        assert_member_eligibility(member, ELIGIBILITY_VERIFIED)
        stale = validate_success(api.get_conduct_case(old_case["id"], TOUR_ADMIN), 200)
        assert stale["points_assessed"] == 2
