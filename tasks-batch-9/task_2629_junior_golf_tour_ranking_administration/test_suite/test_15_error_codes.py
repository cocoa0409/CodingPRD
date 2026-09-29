"""The refusal codes themselves: per-route 404s, ownership, and settled states."""

from prd_bench_local_runner.testing import (
    NON_EXISTENT_UUID,
    validate_error,
    validate_success,
)

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_errors import (
    ERR_APPEAL_WINDOW_EXPIRED,
    ERR_CASE_NOT_FOUND,
    ERR_ENTRY_NOT_FOUND,
    ERR_FORBIDDEN_RESOURCE,
    ERR_INVALID_CASE_STATE,
    ERR_INVALID_CONDUCT_STATE,
    ERR_INVALID_GRANT_STATE,
    ERR_REOPEN_WINDOW_EXPIRED,
    ERR_ROUND_NOT_FOUND,
    ERR_SEASON_NOT_FOUND,
)
from test_helpers.assertions import assert_member_eligibility, assert_round_status
from test_helpers.test_users import (
    CHIEF_REFEREE,
    CONDUCT_COMMITTEE,
    RULES_OFFICIAL,
    SECOND_COACH,
    TOUR_ADMIN,
    member_headers,
)
from test_helpers.types import (
    AID_APPROVED,
    AID_DECISION_DENIED,
    COACH_DECISION_DENIED,
    COACH_GRANT_DENIED,
    COACH_GRANT_GRANTED,
    CONDUCT_APPEAL_OPEN,
    CONDUCT_DECISION_CLEARED,
    CONDUCT_SANCTIONED,
    CONDUCT_UNDER_REVIEW,
    DISPOSITION_PENALTY_STROKES,
    ELIGIBILITY_VERIFIED,
    INCIDENT_CADDIE_ADVICE_BREACH,
    INCIDENT_COACHING_VIOLATION,
    ROUND_CERTIFIED,
    RULES_CASE_REPORTED,
    RULES_CASE_UPHELD,
    RULES_DECISION_DISMISSED,
    RULES_DECISION_UPHELD,
    SANCTION_WARNING,
)


class TestNotFoundAndOwnership:
    def test_each_route_family_reports_its_own_not_found_code(self, api):
        """A real conduct case addressed as a rules case is still not found.

        PRD: "Then a `caseId` that resolves to no `RulesCase` on a rules-case
        route, or to no `ConductCase` on a conduct-case route, yields
        `ERR_CASE_NOT_FOUND` on every read and write under either route family."

        Design: Corner/errors/not_found_is_reported_per_route_family
        """
        ctx = fx.scheduled_tournament(api, member_count=1)
        conduct_case = fx.file_conduct_case(
            api, ctx["member_ids"][0], ctx["tournament_id"],
            INCIDENT_COACHING_VIOLATION, headers=TOUR_ADMIN,
        )

        validate_error(
            api.get_season(NON_EXISTENT_UUID, TOUR_ADMIN), ERR_SEASON_NOT_FOUND, 404
        )
        validate_error(
            api.get_entry(NON_EXISTENT_UUID, TOUR_ADMIN), ERR_ENTRY_NOT_FOUND, 404
        )
        validate_error(
            api.get_round(NON_EXISTENT_UUID, TOUR_ADMIN), ERR_ROUND_NOT_FOUND, 404
        )
        validate_error(
            api.get_rules_case(NON_EXISTENT_UUID, TOUR_ADMIN), ERR_CASE_NOT_FOUND, 404
        )
        validate_error(
            api.get_rules_case(conduct_case["id"], TOUR_ADMIN),
            ERR_CASE_NOT_FOUND,
            404,
        )

        on_its_own_route = validate_success(
            api.get_conduct_case(conduct_case["id"], TOUR_ADMIN), 200
        )
        assert on_its_own_route["status"] == CONDUCT_UNDER_REVIEW

    def test_a_junior_may_read_only_their_own_rows(self, api):
        """The gate is row ownership, so the same reads succeed on one's own rows.

        PRD: "A `Member` caller addressing another junior's row is rejected with
        `ERR_FORBIDDEN_RESOURCE` (HTTP 403)."

        Design: Corner/errors/a_member_reading_another_members_rows_is_forbidden
        """
        ctx = fx.verified_roster(
            api, member_count=2, member_overrides={1: {"publication_opt_in": True}}
        )
        subject, intruder = ctx["member_ids"]

        validate_error(
            api.get_member(subject, member_headers(intruder)),
            ERR_FORBIDDEN_RESOURCE,
            403,
        )
        validate_error(
            api.get_ranking(subject, member_headers(intruder)),
            ERR_FORBIDDEN_RESOURCE,
            403,
        )

        own_row = validate_success(
            api.get_member(intruder, member_headers(intruder)), 200
        )
        assert own_row["id"] == intruder
        own_ranking = validate_success(
            api.get_ranking(intruder, member_headers(intruder)), 200
        )
        assert own_ranking["member_id"] == intruder


class TestSettledGrantsAndCases:
    def test_one_code_covers_both_kinds_of_settled_grant(self, api):
        """Re-deciding an approved application or a settled grant is refused alike.

        PRD: "An attempt to decide a grant that is not `REQUESTED`, or to revoke
        one that is not `GRANTED`, yields `ERR_INVALID_GRANT_STATE`."

        Design: Corner/errors/deciding_or_revoking_a_settled_grant_is_refused
        """
        ctx = fx.verified_roster(api, member_count=1)
        member_id = ctx["member_ids"][0]
        application = fx.approved_aid_application(api, member_id, ctx["season_id"])
        assert application["status"] == AID_APPROVED
        live_grant = fx.granted_coach_grant(api, member_id)
        assert live_grant["status"] == COACH_GRANT_GRANTED

        rival = validate_success(
            api.request_coach_access(
                f.coach_access_payload(
                    member_id, fx.member_version(api, member_id),
                    coach_school="Coastal College",
                ),
                SECOND_COACH,
            ),
            201,
        )
        denied_grant = validate_success(
            api.decide_coach_access(
                rival["id"], f.coach_decision_payload(COACH_DECISION_DENIED),
                member_headers(member_id),
            ),
            200,
        )
        assert denied_grant["status"] == COACH_GRANT_DENIED

        validate_error(
            api.decide_aid_application(
                application["id"], f.aid_decision_payload(AID_DECISION_DENIED),
                TOUR_ADMIN,
            ),
            ERR_INVALID_GRANT_STATE,
            409,
        )
        validate_error(
            api.decide_coach_access(
                live_grant["id"], f.coach_decision_payload(COACH_DECISION_DENIED),
                TOUR_ADMIN,
            ),
            ERR_INVALID_GRANT_STATE,
            409,
        )
        validate_error(
            api.revoke_coach_access(
                denied_grant["id"], f.revocation_payload(), TOUR_ADMIN
            ),
            ERR_INVALID_GRANT_STATE,
            409,
        )

        assert validate_success(
            api.get_aid_application(application["id"], TOUR_ADMIN), 200
        )["status"] == AID_APPROVED
        assert validate_success(
            api.get_coach_access_grant(live_grant["id"], TOUR_ADMIN), 200
        )["status"] == COACH_GRANT_GRANTED
        assert validate_success(
            api.get_coach_access_grant(denied_grant["id"], TOUR_ADMIN), 200
        )["status"] == COACH_GRANT_DENIED

    def test_an_upheld_rules_case_cannot_be_adjudicated_twice(self, api):
        """The applied penalty stroke is neither doubled nor reversed.

        PRD: "A case may be adjudicated only from `REPORTED` or `APPEAL_OPEN`
        status, and the adjudicating referee's `X-User-ID` must differ from the
        case's `reported_by_user_id` — a referee who reported the incident may
        never rule on it, and the attempt is refused with
        `ERR_SELF_ADJUDICATION`."

        Design: Corner/errors/re_adjudicating_an_upheld_rules_case_is_refused
        """
        ctx = fx.peer_verified_round(api, gross_strokes=72)
        case = validate_success(
            api.report_rules_case(
                f.rules_case_payload(
                    ctx["round_id"], DISPOSITION_PENALTY_STROKES, 1
                ),
                RULES_OFFICIAL,
            ),
            201,
        )
        upheld = validate_success(
            api.adjudicate_rules_case(
                case["id"],
                f.adjudication_payload(
                    RULES_DECISION_UPHELD,
                    disposition=DISPOSITION_PENALTY_STROKES,
                    penalty_strokes_applied=1,
                ),
                CHIEF_REFEREE,
            ),
            200,
        )
        assert upheld["status"] == RULES_CASE_UPHELD
        assert upheld["penalty_strokes_applied"] == 1
        before = fx.read_round(api, ctx["round_id"])
        assert before["rules_penalty_strokes"] == 1
        assert before["open_rules_case_count"] == 0

        validate_error(
            api.adjudicate_rules_case(
                case["id"],
                # PRD 3.7: the adjudication payload "carries a `decision` that is
                # either `UPHELD` or `DISMISSED`, a `disposition` that is either
                # `PENALTY_STROKES` or `DISQUALIFICATION`" — only
                # `penalty_strokes_applied` is optional, so the second attempt has
                # to be a well-formed one for the state gate to be the refusal.
                f.adjudication_payload(RULES_DECISION_DISMISSED,
                                       disposition=DISPOSITION_PENALTY_STROKES),
                CHIEF_REFEREE,
            ),
            ERR_INVALID_CASE_STATE,
            409,
        )

        assert fx.read_round(api, ctx["round_id"])["rules_penalty_strokes"] == 1
        settled = validate_success(api.get_rules_case(case["id"], TOUR_ADMIN), 200)
        assert settled["status"] == RULES_CASE_UPHELD
        assert settled["penalty_strokes_applied"] == 1


class TestTemporalWindows:
    def test_the_reopen_window_admits_hour_48_and_refuses_hour_49(self, api):
        """A certified card may be reopened for exactly 48 hours, no longer.

        PRD: "A case may be reported against a round whose `status` is
        `SUBMITTED`, `DISPUTED`, `PEER_VERIFIED` or `CERTIFIED`; a `CERTIFIED`
        round additionally requires that the logical clock is within 48 hours of
        the round's `certified_at`, and a later attempt is refused with
        `ERR_REOPEN_WINDOW_EXPIRED`."

        Design: Corner/errors/rules_case_against_a_certified_round_needs_the_48_hour_window
        """
        ctx = fx.peer_verified_round(api, gross_strokes=72)
        fx.set_clock(api, "2026-09-10T14:00:00Z")
        certified = validate_success(
            api.certify_round(ctx["round_id"], RULES_OFFICIAL), 200
        )
        assert_round_status(certified, ROUND_CERTIFIED)
        assert certified["certified_at"].startswith("2026-09-10T14:00:00")

        fx.set_clock(api, "2026-09-12T15:00:00Z")
        too_late = api.report_rules_case(
            f.rules_case_payload(
                ctx["round_id"], DISPOSITION_PENALTY_STROKES, 2,
                rule_reference="Rule 4.1 - non-conforming club",
            ),
            RULES_OFFICIAL,
        )
        validate_error(too_late, ERR_REOPEN_WINDOW_EXPIRED, 409)

        fx.set_clock(api, "2026-09-12T14:00:00Z")
        on_the_edge = validate_success(
            api.report_rules_case(
                f.rules_case_payload(
                    ctx["round_id"], DISPOSITION_PENALTY_STROKES, 2,
                    rule_reference="Rule 4.1 - non-conforming club",
                ),
                RULES_OFFICIAL,
            ),
            201,
        )
        assert on_the_edge["status"] == RULES_CASE_REPORTED
        reopened = fx.read_round(api, ctx["round_id"])
        assert reopened["open_rules_case_count"] == 1
        assert_round_status(reopened, ROUND_CERTIFIED)

    def test_a_conduct_appeal_closes_fourteen_days_after_the_decision(self, api):
        """The conduct window is 14 days inclusive, unlike the rules-case window.

        PRD: "The junior themselves — their `X-User-ID` must equal the case's
        `member_id` — or a `TourAdmin` may appeal by supplying `grounds`, and the
        appeal must be filed within 14 days of the case's `decided_at` or it is
        refused with `ERR_APPEAL_WINDOW_EXPIRED`."

        Design: Corner/errors/conduct_appeal_closes_fourteen_days_after_the_decision
        """
        ctx = fx.scheduled_tournament(api, member_count=1)
        member_id = ctx["member_ids"][0]
        case = fx.file_conduct_case(
            api, member_id, ctx["tournament_id"], INCIDENT_CADDIE_ADVICE_BREACH,
            subject_type="CADDIE", subject_name="Rick Vance",
            narrative="club selection called out on the 7th",
        )
        decided = fx.sanction_conduct_case(api, case["id"])
        assert decided["decided_at"].startswith("2026-08-10T00:00:00")
        assert decided["appeal_count"] == 0

        fx.set_clock(api, "2026-08-24T00:00:01Z")
        too_late = api.appeal_conduct_case(
            case["id"],
            f.appeal_payload(grounds="the caddie was not inside the ropes"),
            member_headers(member_id),
        )
        validate_error(too_late, ERR_APPEAL_WINDOW_EXPIRED, 409)

        fx.set_clock(api, "2026-08-24T00:00:00Z")
        appealed = validate_success(
            api.appeal_conduct_case(
                case["id"],
                f.appeal_payload(grounds="the caddie was not inside the ropes"),
                member_headers(member_id),
            ),
            200,
        )
        assert appealed["status"] == CONDUCT_APPEAL_OPEN
        assert appealed["appeal_count"] == 1
        assert fx.read_member(api, member_id)["conduct_points"] == 2

    def test_a_sanctioned_conduct_case_cannot_be_decided_again(self, api):
        """The junior's conduct points are assessed once, not twice.

        PRD: "A decision is admissible only from `UNDER_REVIEW` or
        `APPEAL_OPEN`; anything else yields `ERR_INVALID_CONDUCT_STATE`."

        Design: Corner/errors/deciding_an_already_sanctioned_conduct_case_is_refused
        """
        ctx = fx.scheduled_tournament(api, member_count=1)
        member_id = ctx["member_ids"][0]
        case = fx.file_conduct_case(
            api, member_id, ctx["tournament_id"], INCIDENT_COACHING_VIOLATION,
            headers=TOUR_ADMIN,
            narrative="line of play indicated from outside the ropes",
        )
        assert case["status"] == CONDUCT_UNDER_REVIEW
        sanctioned = fx.sanction_conduct_case(api, case["id"])
        assert sanctioned["status"] == CONDUCT_SANCTIONED
        assert sanctioned["sanction_tier"] == SANCTION_WARNING
        assert sanctioned["cumulative_points_at_decision"] == 2

        validate_error(
            api.decide_conduct_case(
                case["id"], f.conduct_decision_payload(CONDUCT_DECISION_CLEARED),
                CONDUCT_COMMITTEE,
            ),
            ERR_INVALID_CONDUCT_STATE,
            409,
        )

        member = fx.read_member(api, member_id)
        assert member["conduct_points"] == 2
        assert_member_eligibility(member, ELIGIBILITY_VERIFIED)
        settled = validate_success(api.get_conduct_case(case["id"], TOUR_ADMIN), 200)
        assert settled["status"] == CONDUCT_SANCTIONED
        assert settled["points_assessed"] == 2
