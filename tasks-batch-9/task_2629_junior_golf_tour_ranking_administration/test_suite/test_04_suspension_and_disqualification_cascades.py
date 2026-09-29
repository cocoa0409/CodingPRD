"""Multi-hop consequences of one write: a sanctioned conduct case reaching through
entries, exemptions, the waitlist and the purse, and an upheld disqualification
reaching backwards into a finished event.
"""

from prd_bench_local_runner.testing import validate_success

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.assertions import assert_cents, assert_two_decimals
from test_helpers.test_users import CHIEF_REFEREE, RULES_OFFICIAL, TOUR_ADMIN
from test_helpers.types import (
    CONDUCT_SANCTIONED,
    DISPOSITION_DISQUALIFICATION,
    ELIGIBILITY_SUSPENDED,
    ENTRY_ACCEPTED,
    ENTRY_DISQUALIFIED,
    ENTRY_FORFEITED,
    ENTRY_REJECTED,
    ENTRY_WAITLISTED,
    EXEMPTION_DEFENDING_CHAMPION,
    INCIDENT_PHYSICAL_ALTERCATION,
    FEE_AID_COVERED,
    FEE_FORFEITED_FEE,
    GRANT_CONSUMED,
    GRANT_REVOKED,
    REJECTION_MEMBER_SUSPENDED,
    ROUND_DISQUALIFIED,
    RULES_CASE_UPHELD,
    RULES_DECISION_UPHELD,
    SANCTION_MEMBER_SUSPENSION,
)


class TestSuspensionCascade:
    """One sanction moves a junior, an entry, a grant, the waitlist and the money."""

    def test_sanctioned_altercation_forfeits_the_slot_and_backfills_the_waitlist(self, api):
        """Five hops from a single decision, ending in a disbursed award.

        PRD: "Hop four is the backfill: each slot vacated by one of those
        forfeitures promotes the waitlisted entry holding the lowest
        `waitlist_position`, and the surviving waitlist positions renumber, exactly
        as in an ordinary withdrawal."

        Design: Difficulty/transitive_cascade/conduct_suspension_cascade_depth_five
        """
        ctx = fx.verified_roster(api, member_count=3)
        first_id, second_id, third_id = ctx["member_ids"]
        application = fx.approved_aid_application(
            api, first_id, ctx["season_id"],
            household_income_cents=3000000, dependents=2,
        )
        assert_two_decimals(application["covered_pct"], 1.00, "covered_pct")

        tournament = fx.create_tournament(api, ctx["season_id"], field_size_limit=1)
        validate_success(api.open_entries(tournament["id"], TOUR_ADMIN), 200)
        grant = fx.create_exemption_grant(
            api, first_id, tournament["id"], EXEMPTION_DEFENDING_CHAMPION,
            "2026-09-01T00:00:00Z",
        )

        exempt_entry = fx.submit_entry(
            api, first_id, tournament["id"],
            request_assistance=True, aid_application_id=application["id"],
            exemption_grant_id=grant["id"],
        )
        assert_cents(exempt_entry["aid_award_cents"], 25000, "aid_award_cents")
        assert exempt_entry["fee_status"] == FEE_AID_COVERED

        fx.set_clock(api, "2026-08-10T01:00:00Z")
        second_entry = fx.submit_entry(api, second_id, tournament["id"])
        fx.set_clock(api, "2026-08-10T02:00:00Z")
        third_entry = fx.submit_entry(api, third_id, tournament["id"])

        fx.set_clock(api, fx.CLOCK_AFTER_ENTRY_CLOSE)
        validate_success(api.close_entries(tournament["id"], TOUR_ADMIN), 200)
        field = validate_success(api.set_field(tournament["id"], TOUR_ADMIN), 200)
        assert field["accepted_count"] == 1
        assert field["waitlist_count"] == 2

        fx.set_clock(api, "2026-09-02T00:00:00Z")
        case = fx.file_conduct_case(
            api, first_id, tournament["id"], INCIDENT_PHYSICAL_ALTERCATION,
            subject_name="Marcus Stone",
            narrative="Struck a volunteer marshal on the 9th tee after a ruling.",
        )
        decided = fx.sanction_conduct_case(api, case["id"])
        assert decided["sanction_tier"] == SANCTION_MEMBER_SUSPENSION
        assert decided["cumulative_points_at_decision"] == 6
        assert decided["status"] == CONDUCT_SANCTIONED
        assert decided["points_assessed"] == 6

        suspended = fx.read_member(api, first_id)
        assert suspended["eligibility_status"] == ELIGIBILITY_SUSPENDED
        assert suspended["conduct_points"] == 6

        forfeited = fx.read_entry(api, exempt_entry["id"])
        assert forfeited["entry_status"] == ENTRY_FORFEITED
        assert forfeited["fee_status"] == FEE_FORFEITED_FEE
        # The grant was consumed by the accepted entry at the selector run, so the
        # sweep — which only touches grants whose status is ACTIVE — leaves it
        # alone. PRD: "A consumed exemption grant stays `CONSUMED`: forfeiture
        # never restores an exemption." and "a forfeiture leaves it `CONSUMED`
        # forever."
        assert validate_success(
            api.get_exemption_grant(grant["id"], TOUR_ADMIN), 200
        )["status"] == GRANT_CONSUMED

        season = fx.read_season(api, ctx["season_id"])
        assert_cents(season["assistance_committed_cents"], 0,
                     "assistance_committed_cents")
        assert_cents(season["assistance_disbursed_cents"], 25000,
                     "assistance_disbursed_cents")
        assert_cents(season["assistance_available_cents"], 475000,
                     "assistance_available_cents")
        assert_cents(
            validate_success(api.get_aid_application(application["id"], TOUR_ADMIN),
                             200)["consumed_cents"],
            25000, "consumed_cents",
        )

        promoted = fx.read_entry(api, second_entry["id"])
        assert promoted["entry_status"] == ENTRY_ACCEPTED
        assert promoted["waitlist_position"] is None
        renumbered = fx.read_entry(api, third_entry["id"])
        assert renumbered["entry_status"] == ENTRY_WAITLISTED
        assert renumbered["waitlist_position"] == 1

        after = fx.read_tournament(api, tournament["id"])
        assert after["accepted_count"] == 1
        assert after["waitlist_count"] == 1
        assert after["open_slot_count"] == 0

    def test_the_sweep_rejects_a_waitlisted_entry_and_revokes_a_live_exemption(self, api):
        """A suspended junior loses a queued slot and an unused exemption alike.

        PRD: "Hop three is the reservation sweep: every entry of that junior whose
        `entry_status` is `APPLIED` or `WAITLISTED` moves to `REJECTED` with
        `rejection_reason` set to `MEMBER_SUSPENDED`; every entry of that junior
        whose `entry_status` is `ACCEPTED` and whose tournament is `FIELD_SET`
        moves to `FORFEITED`; and every exemption grant of that junior whose
        `status` is `ACTIVE` moves to `REVOKED`."

        Design: Difficulty/transitive_cascade/conduct_suspension_cascade_depth_five
        """
        ctx = fx.field_set(api, member_count=2, field_size_limit=1)
        waitlisted_member_id = ctx["member_ids"][1]
        waitlisted_entry = ctx["entries"][1]
        assert waitlisted_entry["entry_status"] == ENTRY_WAITLISTED

        later = fx.create_tournament(api, ctx["season_id"], f.october_tournament_payload)
        grant = fx.create_exemption_grant(
            api, waitlisted_member_id, later["id"], EXEMPTION_DEFENDING_CHAMPION,
            "2026-10-14T00:00:00Z",
        )

        fx.suspend_member(api, waitlisted_member_id, ctx["tournament_id"])

        rejected = fx.read_entry(api, waitlisted_entry["id"])
        assert rejected["entry_status"] == ENTRY_REJECTED
        assert rejected["rejection_reason"] == REJECTION_MEMBER_SUSPENDED
        assert rejected["waitlist_position"] is None
        assert validate_success(
            api.get_exemption_grant(grant["id"], TOUR_ADMIN), 200
        )["status"] == GRANT_REVOKED

        tournament = fx.read_tournament(api, ctx["tournament_id"])
        assert tournament["waitlist_count"] == 0
        assert tournament["closed_count"] == 1
        assert tournament["accepted_count"] == 1
        assert fx.read_member(api, waitlisted_member_id)["late_withdrawal_count"] == 0


class TestRetroactiveDisqualificationCascade:
    """An upheld disqualification rewrites the live figures and spares the certified."""

    def test_disqualifying_a_certified_round_zeroes_live_points_only(self, api):
        """The certified snapshot keeps 101.25 while the provisional figure falls to 0.00.

        PRD: "What is emphatically **not** touched is the junior's certified
        ranking: `certified_ranking_points`, `certified_counted_events` and
        `certified_rank_position` all keep their previous values until the next
        ranking run is executed."

        Design: Difficulty/transitive_cascade/rules_disqualification_retroactive_ranking_cascade
        """
        ctx = fx.completed_event(api)
        winner_id, runner_up_id = ctx["member_ids"]

        run = fx.run_ranking(api, ctx["season_id"], as_of_date="2026-09-10")
        assert run["ranking_epoch"] == 1

        before = fx.read_ranking(api, winner_id)
        assert_two_decimals(before["provisional_ranking_points"], 405.00,
                            "provisional_ranking_points before adjudication")
        assert_two_decimals(before["certified_ranking_points"], 101.25,
                            "certified_ranking_points before adjudication")
        assert before["certified_rank_position"] == 1

        second_round_id = ctx["rounds"][2]["id"]
        case = validate_success(
            api.report_rules_case(
                f.rules_case_payload(
                    second_round_id, DISPOSITION_DISQUALIFICATION, None,
                    rule_reference="Rule 4.1b - non-conforming club carried",
                ),
                RULES_OFFICIAL,
            ),
            201,
        )
        upheld = validate_success(
            api.adjudicate_rules_case(
                case["id"],
                f.adjudication_payload(RULES_DECISION_UPHELD,
                                       disposition=DISPOSITION_DISQUALIFICATION),
                CHIEF_REFEREE,
            ),
            200,
        )
        assert upheld["status"] == RULES_CASE_UPHELD
        assert upheld["disposition"] == DISPOSITION_DISQUALIFICATION

        assert fx.read_round(api, second_round_id)["status"] == ROUND_DISQUALIFIED
        entry = fx.read_entry(api, ctx["entry_ids"][0])
        assert entry["entry_status"] == ENTRY_DISQUALIFIED
        assert_two_decimals(entry["event_points"], 0.00, "event_points")
        assert entry["finish_position"] is None

        after = fx.read_member(api, winner_id)
        assert_two_decimals(after["provisional_ranking_points"], 0.00,
                            "provisional_ranking_points after adjudication")
        assert after["provisional_counted_events"] == 0
        assert_two_decimals(after["certified_ranking_points"], 101.25,
                            "certified_ranking_points after adjudication")
        assert after["certified_rank_position"] == 1

        peer = fx.read_member(api, runner_up_id)
        assert_two_decimals(peer["provisional_ranking_points"], 285.00,
                            "peer provisional_ranking_points")
        assert_two_decimals(peer["certified_ranking_points"], 71.25,
                            "peer certified_ranking_points")

    def test_a_disqualified_entry_keeps_occupying_its_slot(self, api):
        """finished_count falls by one and accepted_count does not move.

        PRD: "the tournament's `finished_count` falls by one while its
        `accepted_count` is left unchanged, because a `DISQUALIFIED` entry still
        occupies its slot"

        Design: Difficulty/transitive_cascade/rules_disqualification_retroactive_ranking_cascade
        """
        ctx = fx.completed_event(api)
        before = fx.read_tournament(api, ctx["tournament_id"])
        assert before["finished_count"] == 2
        assert before["accepted_count"] == 2

        case = validate_success(
            api.report_rules_case(
                f.rules_case_payload(
                    ctx["rounds"][2]["id"], DISPOSITION_DISQUALIFICATION, None,
                    rule_reference="Rule 4.1b - non-conforming club carried",
                ),
                RULES_OFFICIAL,
            ),
            201,
        )
        validate_success(
            api.adjudicate_rules_case(
                case["id"],
                f.adjudication_payload(RULES_DECISION_UPHELD,
                                       disposition=DISPOSITION_DISQUALIFICATION),
                CHIEF_REFEREE,
            ),
            200,
        )

        after = fx.read_tournament(api, ctx["tournament_id"])
        assert after["finished_count"] == 1
        assert after["accepted_count"] == 2
