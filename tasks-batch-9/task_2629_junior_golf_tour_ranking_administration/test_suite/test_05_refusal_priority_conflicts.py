"""Requests that break two rules at once. Only the higher-ranked refusal may be
reported, and nothing may be written on the way out.
"""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_errors import (
    ERR_AID_BUDGET_EXHAUSTED,
    ERR_INVALID_MARKER,
    ERR_INVALID_TOURNAMENT_STATE,
    ERR_MEMBER_SUSPENDED,
    ERR_TEE_SLOT_FULL,
)
from test_helpers.assertions import assert_cents
from test_helpers.test_users import CHIEF_REFEREE, TOUR_ADMIN, member_headers
from test_helpers.types import (
    ENTRY_ACCEPTED,
    INCIDENT_PHYSICAL_ALTERCATION,
    ROUND_SCHEDULED,
    SANCTION_MEMBER_SUSPENSION,
    SUBJECT_CADDIE,
    TOURNAMENT_ENTRY_CLOSED,
    TOURNAMENT_SCHEDULED,
)

def _over_ceiling_member(api):
    """A verified junior whose handicap index of 12.5 is above every ceiling used here."""
    fx.set_clock(api, fx.CLOCK_ENTRY_WINDOW)
    season = fx.create_season(api)
    member = fx.register_member(api, season["id"], f.fourth_member_payload)
    fx.verify_member(api, member["id"])
    return season, member


class TestStateGateOutranksHandicapCeiling:
    """A closed tournament is reported before an ineligible handicap index."""

    def test_closed_entry_window_is_reported_and_not_the_handicap_ceiling(self, api):
        """Both rules are broken; the tournament state gate is checked first.

        PRD: "**State gates, fifth.** Each aggregate is checked for admissibility
        in its own right, and the aggregates are checked in a fixed order:
        tournament status (`ERR_INVALID_TOURNAMENT_STATE`), then entry status
        (`ERR_INVALID_ENTRY_STATE`), then round status
        (`ERR_INVALID_ROUND_STATE`), then rules-case status
        (`ERR_INVALID_CASE_STATE`), then conduct-case status
        (`ERR_INVALID_CONDUCT_STATE`), then assistance-application and
        recruiting-grant status (`ERR_INVALID_GRANT_STATE`)."

        Design: Difficulty/priority_pair_validation_conflict/entry_state_gate_outranks_handicap_ceiling
        """
        season, member = _over_ceiling_member(api)
        tournament = fx.create_tournament(api, season["id"])
        validate_success(api.open_entries(tournament["id"], TOUR_ADMIN), 200)

        fx.set_clock(api, fx.CLOCK_AFTER_ENTRY_CLOSE)
        closed = validate_success(api.close_entries(tournament["id"], TOUR_ADMIN), 200)
        assert closed["status"] == TOURNAMENT_ENTRY_CLOSED

        validate_error(
            api.submit_entry(
                f.entry_payload(member["id"], tournament["id"]),
                member_headers(member["id"]),
            ),
            ERR_INVALID_TOURNAMENT_STATE,
            409,
        )

        after = fx.read_tournament(api, tournament["id"])
        assert after["entry_count"] == 0
        assert after["applied_count"] == 0

    def test_a_scheduled_tournament_is_also_reported_before_the_ceiling(self, api):
        """An unopened event refuses on its status, not on the junior's index.

        PRD: "**Business and referential constraints, seventh.** In ascending
        order: division match (`ERR_DIVISION_MISMATCH`, on entry submission and
        exemption-grant minting), the handicap ceiling
        (`ERR_HANDICAP_ABOVE_LIMIT`, on entry submission), handicap freshness and
        provenance (`ERR_HANDICAP_STALE`, on entry submission and eligibility
        verification), exemption applicability
        (`ERR_EXEMPTION_NOT_APPLICABLE`, on entry submission), assistance approval
        (`ERR_AID_NOT_APPROVED`, on entry submission), and duplication
        (`ERR_DUPLICATE_ENTRY`, on entry submission and assistance-application
        creation)."

        Design: Difficulty/priority_pair_validation_conflict/entry_state_gate_outranks_handicap_ceiling
        """
        season, member = _over_ceiling_member(api)
        tournament = fx.create_tournament(api, season["id"])
        assert tournament["status"] == TOURNAMENT_SCHEDULED

        validate_error(
            api.submit_entry(
                f.entry_payload(member["id"], tournament["id"]),
                member_headers(member["id"]),
            ),
            ERR_INVALID_TOURNAMENT_STATE,
            409,
        )
        assert fx.read_tournament(api, tournament["id"])["entry_count"] == 0


class TestSuspensionOutranksBudgetExhaustion:
    """A safety gate is reported ahead of an exhausted purse."""

    def test_suspended_junior_against_an_empty_purse_reports_the_suspension(self, api):
        """The award cannot be funded either way, but the money rule is the weaker one.

        PRD: "An entry submitted for a suspended junior against an exhausted
        assistance pool reports `ERR_MEMBER_SUSPENDED`, never
        `ERR_AID_BUDGET_EXHAUSTED`."

        Design: Difficulty/priority_pair_validation_conflict/member_suspension_safety_outranks_budget_exhaustion
        """
        fx.set_clock(api, fx.CLOCK_ENTRY_WINDOW)
        season = fx.create_season(api, assistance_budget_cents=20000)
        member = fx.register_member(api, season["id"], f.second_member_payload)
        fx.verify_member(api, member["id"])
        application = fx.approved_aid_application(
            api, member["id"], season["id"],
            household_income_cents=3000000, dependents=2,
        )
        assert_cents(application["estimated_award_cents"], 25000,
                     "estimated_award_cents")

        tournament = fx.create_tournament(api, season["id"])
        validate_success(api.open_entries(tournament["id"], TOUR_ADMIN), 200)

        decided = fx.file_conduct_case(
            api, member["id"], tournament["id"], INCIDENT_PHYSICAL_ALTERCATION,
            subject_type=SUBJECT_CADDIE, subject_name="Rick Doyle",
            narrative="Shoved a competitor's caddie in the scoring tent.",
        )
        sanctioned = fx.sanction_conduct_case(api, decided["id"])
        assert sanctioned["sanction_tier"] == SANCTION_MEMBER_SUSPENSION

        validate_error(
            api.submit_entry(
                f.entry_payload(member["id"], tournament["id"],
                                request_assistance=True,
                                aid_application_id=application["id"]),
                TOUR_ADMIN,
            ),
            ERR_MEMBER_SUSPENDED,
            409,
        )

        after = fx.read_season(api, season["id"])
        assert_cents(after["assistance_available_cents"], 20000,
                     "assistance_available_cents")
        assert_cents(after["assistance_committed_cents"], 0,
                     "assistance_committed_cents")
        assert_cents(
            validate_success(api.get_aid_application(application["id"], TOUR_ADMIN),
                             200)["consumed_cents"],
            0, "consumed_cents",
        )
        assert fx.read_tournament(api, tournament["id"])["entry_count"] == 0

    def test_the_purse_rule_does_fire_once_the_junior_is_in_good_standing(self, api):
        """The same request from a verified junior is refused on the budget instead.

        PRD: "If the clamped award exceeds the season's current
        `assistance_available_cents`, the submission is refused with
        `ERR_AID_BUDGET_EXHAUSTED`: the association never part-funds an entry, so
        an award that cannot be granted whole is not granted at all."

        Design: Difficulty/priority_pair_validation_conflict/member_suspension_safety_outranks_budget_exhaustion
        """
        fx.set_clock(api, fx.CLOCK_ENTRY_WINDOW)
        season = fx.create_season(api, assistance_budget_cents=20000)
        member = fx.register_member(api, season["id"], f.second_member_payload)
        fx.verify_member(api, member["id"])
        application = fx.approved_aid_application(
            api, member["id"], season["id"],
            household_income_cents=3000000, dependents=2,
        )
        tournament = fx.create_tournament(api, season["id"])
        validate_success(api.open_entries(tournament["id"], TOUR_ADMIN), 200)

        validate_error(
            api.submit_entry(
                f.entry_payload(member["id"], tournament["id"],
                                request_assistance=True,
                                aid_application_id=application["id"]),
                member_headers(member["id"]),
            ),
            ERR_AID_BUDGET_EXHAUSTED,
            409,
        )
        assert_cents(fx.read_season(api, season["id"])["assistance_available_cents"],
                     20000, "assistance_available_cents")


class TestMarkerSafetyOutranksTeeSlotCapacity:
    """A junior may never mark his own card, whatever the tee sheet says."""

    def test_self_marker_is_reported_ahead_of_a_full_tee_slot(self, api):
        """Both rules read the same two fields; the marker gate is a safety gate.

        PRD: "Last of the safety gates, round creation validates its peer marker
        and refuses with `ERR_INVALID_MARKER`."

        Design: Difficulty/priority_pair_validation_conflict/round_marker_safety_outranks_tee_slot_capacity
        """
        ctx = fx.field_set(api, member_count=2, name="Sandhills Regional",
                           tee_group_size=1)
        assert ctx["tournament"]["accepted_count"] == 2
        first_entry_id, second_entry_id = ctx["entry_ids"]
        first_member_id, second_member_id = ctx["member_ids"]

        occupying = fx.create_round(
            api, second_entry_id, first_member_id, 1, fx.TEE_TIME_ROUND_ONE
        )

        validate_error(
            api.create_round(
                f.round_payload(first_entry_id, 1, fx.TEE_TIME_ROUND_ONE,
                                first_member_id),
                CHIEF_REFEREE,
            ),
            ERR_INVALID_MARKER,
            409,
        )

        assert fx.read_round(api, occupying["id"])["status"] == ROUND_SCHEDULED
        assert fx.read_entry(api, first_entry_id)["entry_status"] == ENTRY_ACCEPTED

    def test_the_tee_slot_rule_does_fire_once_the_marker_is_a_peer(self, api):
        """With a legitimate marker named, the full 13:00 slot is what refuses.

        PRD: "**Capacity, overlap and consent, ninth.** The schedule-overlap rule
        (`ERR_SCHEDULE_CONFLICT`, on entry submission), the tee-slot capacity rule
        (`ERR_TEE_SLOT_FULL`, on round creation), the non-empty-field rule
        (`ERR_EMPTY_FIELD`, on starting play), the open-rules-case bar on
        certification (`ERR_OPEN_RULES_CASE`, on certification), publication
        consent (`ERR_PUBLICATION_NOT_CONSENTED`, on the published-results view
        and on recruiting-access requests), and live coach access
        (`ERR_COACH_ACCESS_DENIED`, on the published-results view and on the
        ranking view)."

        Design: Difficulty/priority_pair_validation_conflict/round_marker_safety_outranks_tee_slot_capacity
        """
        ctx = fx.field_set(api, member_count=2, name="Sandhills Regional",
                           tee_group_size=1)
        first_entry_id, second_entry_id = ctx["entry_ids"]
        first_member_id, second_member_id = ctx["member_ids"]

        fx.create_round(api, second_entry_id, first_member_id, 1,
                        fx.TEE_TIME_ROUND_ONE)

        validate_error(
            api.create_round(
                f.round_payload(first_entry_id, 1, fx.TEE_TIME_ROUND_ONE,
                                second_member_id),
                CHIEF_REFEREE,
            ),
            ERR_TEE_SLOT_FULL,
            409,
        )
