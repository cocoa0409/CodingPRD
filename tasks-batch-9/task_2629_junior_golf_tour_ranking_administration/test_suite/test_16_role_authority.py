"""Who may act: authentication, role exclusivity, and segregation of duties."""

from prd_bench_local_runner.testing import (
    NON_EXISTENT_UUID,
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_errors import (
    ERR_SELF_ADJUDICATION,
    ERR_UNAUTHENTICATED,
    ERR_UNAUTHORIZED,
)
from test_helpers.assertions import (
    assert_entry_status,
    assert_one_decimal,
    assert_round_status,
    assert_slot_census,
    assert_tournament_status,
)
from test_helpers.constants import STANDARD_ENTRY_FEE_CENTS
from test_helpers.test_users import (
    ANONYMOUS,
    CHIEF_REFEREE,
    COACH,
    CONDUCT_COMMITTEE,
    NO_ROLE_HEADERS,
    RULES_OFFICIAL,
    RULES_OFFICIAL_USER_ID,
    SECOND_CHIEF_REFEREE,
    SECOND_CHIEF_REFEREE_USER_ID,
    TOUR_ADMIN,
    member_headers,
    rules_official_headers,
    unknown_role_headers,
)
from test_helpers.types import (
    CONDUCT_DECISION_SANCTIONED,
    CONDUCT_SANCTIONED,
    DISPOSITION_PENALTY_STROKES,
    ENTRY_COMPETING,
    INCIDENT_COACHING_VIOLATION,
    PACE_WARNING,
    PEER_VERIFY,
    ROUND_CERTIFIED,
    ROUND_PEER_VERIFIED,
    ROUND_SCHEDULED,
    ROUND_SUBMITTED,
    RULES_CASE_UPHELD,
    RULES_DECISION_UPHELD,
    SANCTION_WARNING,
    TOURNAMENT_ENTRY_CLOSED,
    TOURNAMENT_ENTRY_OPEN,
    TOURNAMENT_FIELD_SET,
    TOURNAMENT_IN_PROGRESS,
)


class TestAuthenticationAndRoleScope:
    def test_a_missing_or_invented_role_is_unauthenticated(self, api):
        """Anonymous is a declared role and reads the schedule; Spectator is not.

        PRD: "A request whose `X-User-Role` header is absent, or whose value is
        not one of those seven names, is rejected with `ERR_UNAUTHENTICATED`
        (HTTP 401)."

        Design: Corner/rbac/a_missing_or_unknown_role_header_is_unauthenticated
        """
        fx.set_clock(api, fx.CLOCK_ENTRY_WINDOW)
        season = fx.create_season(api)

        validate_error(
            api.get_season(season["id"], NO_ROLE_HEADERS), ERR_UNAUTHENTICATED, 401
        )
        validate_error(
            api.get_season(season["id"], unknown_role_headers("Spectator")),
            ERR_UNAUTHENTICATED,
            401,
        )
        rows, _meta = validate_paginated(api.list_tournaments(None, ANONYMOUS))
        assert rows == []

    def test_officiating_authority_belongs_to_one_role_each(self, api):
        """Only the committee decides conduct, and the role gate runs before lookup.

        PRD: "A `ConductCommittee` is the sole decider of parent and caddie
        conduct cases and therefore the only role that can suspend a junior; it
        holds no power over the schedule, the field, scoring or money."

        Design: Corner/rbac/officiating_authority_is_exclusive_to_its_own_role
        """
        ctx = fx.scheduled_tournament(api, member_count=1)
        case = fx.file_conduct_case(
            api, ctx["member_ids"][0], ctx["tournament_id"],
            INCIDENT_COACHING_VIOLATION, headers=TOUR_ADMIN,
            narrative="advice shouted from the gallery",
        )
        sanction = f.conduct_decision_payload(CONDUCT_DECISION_SANCTIONED)

        validate_error(
            api.decide_conduct_case(case["id"], sanction, TOUR_ADMIN),
            ERR_UNAUTHORIZED,
            403,
        )
        validate_error(
            api.decide_conduct_case(case["id"], sanction, CHIEF_REFEREE),
            ERR_UNAUTHORIZED,
            403,
        )
        validate_error(
            api.adjudicate_rules_case(
                NON_EXISTENT_UUID,
                f.adjudication_payload(RULES_DECISION_UPHELD),
                CONDUCT_COMMITTEE,
            ),
            ERR_UNAUTHORIZED,
            403,
        )

        decided = validate_success(
            api.decide_conduct_case(case["id"], sanction, CONDUCT_COMMITTEE), 200
        )
        assert decided["status"] == CONDUCT_SANCTIONED
        assert decided["sanction_tier"] == SANCTION_WARNING

    def test_a_coach_reads_the_schedule_but_writes_no_competition_row(self, api):
        """Entry submission and scheduling are closed to recruiters and the public.

        PRD: "A request whose role is recognised but is not listed among the
        target endpoint's authorised roles is rejected with `ERR_UNAUTHORIZED`
        (HTTP 403); that authorisation check applies to every endpoint without
        exception, including the two public ones."

        Design: Corner/rbac/a_coach_may_read_the_schedule_but_never_write_competition_rows
        """
        ctx = fx.entry_open_tournament(api, member_count=1, field_size_limit=4)
        member_id = ctx["member_ids"][0]
        entry_body = f.entry_payload(member_id, ctx["tournament_id"])

        validate_error(api.submit_entry(entry_body, COACH), ERR_UNAUTHORIZED, 403)
        validate_error(
            api.create_tournament(
                f.october_tournament_payload(
                    ctx["season_id"], name="Coach Invitational"
                ),
                COACH,
            ),
            ERR_UNAUTHORIZED,
            403,
        )
        validate_error(api.list_entries(None, COACH), ERR_UNAUTHORIZED, 403)
        validate_error(api.submit_entry(entry_body, ANONYMOUS), ERR_UNAUTHORIZED, 403)

        rows, _meta = validate_paginated(
            api.list_tournaments({"season_id": ctx["season_id"]}, COACH)
        )
        assert [row["id"] for row in rows] == [ctx["tournament_id"]]
        assert_slot_census(
            fx.read_tournament(api, ctx["tournament_id"]), entry_count=0
        )


class TestSegregationOfDuties:
    def test_nobody_rules_on_a_matter_they_raised_or_attested(self, api):
        """A second referee may adjudicate and a non-marker official may certify.

        PRD: "Immediately after ownership comes segregation of duties,
        `ERR_SELF_ADJUDICATION` (HTTP 409): the `X-User-ID` adjudicating a rules
        case must differ from that case's `reported_by_user_id`, the `X-User-ID`
        deciding a conduct case must differ from that case's
        `filed_by_user_id`, and the `X-User-ID` certifying a round must differ
        from that round's `marker_member_id`."

        Design: Corner/rbac/no_user_may_judge_a_matter_they_raised_or_attested
        """
        ctx = fx.peer_verified_round(api, gross_strokes=72)
        marker_id = ctx["member_ids"][1]
        case = validate_success(
            api.report_rules_case(
                f.rules_case_payload(
                    ctx["round_id"], DISPOSITION_PENALTY_STROKES, 1,
                    rule_reference="Rule 9.4 - ball lifted by the player",
                ),
                CHIEF_REFEREE,
            ),
            201,
        )
        verdict = f.adjudication_payload(
            RULES_DECISION_UPHELD,
            disposition=DISPOSITION_PENALTY_STROKES,
            penalty_strokes_applied=1,
        )

        validate_error(
            api.adjudicate_rules_case(case["id"], verdict, CHIEF_REFEREE),
            ERR_SELF_ADJUDICATION,
            409,
        )
        upheld = validate_success(
            api.adjudicate_rules_case(case["id"], verdict, SECOND_CHIEF_REFEREE), 200
        )
        assert upheld["status"] == RULES_CASE_UPHELD
        assert upheld["adjudicated_by_user_id"] == SECOND_CHIEF_REFEREE_USER_ID

        validate_error(
            api.certify_round(ctx["round_id"], rules_official_headers(marker_id)),
            ERR_SELF_ADJUDICATION,
            409,
        )
        certified = validate_success(
            api.certify_round(ctx["round_id"], RULES_OFFICIAL), 200
        )
        assert_round_status(certified, ROUND_CERTIFIED)
        assert certified["adjusted_gross"] == 73
        assert_one_decimal(certified["scoring_differential"], 1.4)
        assert certified["certified_by_user_id"] == RULES_OFFICIAL_USER_ID

    def test_each_role_drives_its_own_step_of_the_scoring_pipeline(self, api):
        """Admin, referee, official, competitor and marker each act in turn.

        PRD: "A `RulesOfficial` works on the course — it alone records
        pace-of-play observations, and it shares score submission, peer
        verification, round certification and rules-case reporting with others;
        it may not decide the cases it reports."

        Design: Corner/rbac/every_role_performs_its_own_step_of_the_scoring_pipeline
        """
        ctx = fx.verified_roster(
            api, member_count=2, member_overrides={1: {"publication_opt_in": True}}
        )
        competitor, marker = ctx["member_ids"]
        tournament = fx.create_tournament(
            api, ctx["season_id"], name="Carolina Regional U17", field_size_limit=4
        )

        opened = validate_success(api.open_entries(tournament["id"], TOUR_ADMIN), 200)
        assert_tournament_status(opened, TOURNAMENT_ENTRY_OPEN)
        entries = [
            fx.submit_entry(api, member_id, tournament["id"])
            for member_id in (competitor, marker)
        ]

        fx.set_clock(api, fx.CLOCK_AFTER_ENTRY_CLOSE)
        closed = validate_success(api.close_entries(tournament["id"], TOUR_ADMIN), 200)
        assert_tournament_status(closed, TOURNAMENT_ENTRY_CLOSED)
        selected = validate_success(api.set_field(tournament["id"], TOUR_ADMIN), 200)
        assert_tournament_status(selected, TOURNAMENT_FIELD_SET)
        assert_slot_census(selected, accepted_count=2)
        for member_id, entry in zip((competitor, marker), entries):
            fx.pay_entry(api, member_id, entry["id"], STANDARD_ENTRY_FEE_CENTS)

        fx.set_clock(api, fx.CLOCK_ROUND_ONE)
        started = validate_success(
            api.start_tournament(tournament["id"], CHIEF_REFEREE), 200
        )
        assert_tournament_status(started, TOURNAMENT_IN_PROGRESS)

        round_row = validate_success(
            api.create_round(
                f.round_payload(
                    entries[0]["id"], 1, fx.TEE_TIME_ROUND_ONE, marker
                ),
                CHIEF_REFEREE,
            ),
            201,
        )
        assert_round_status(round_row, ROUND_SCHEDULED)

        paced = validate_success(
            api.record_pace_observation(
                round_row["id"], f.pace_observation_payload(PACE_WARNING, 4),
                RULES_OFFICIAL,
            ),
            200,
        )
        assert paced["pace_warning_count"] == 1
        assert paced["pace_penalty_strokes"] == 0

        submitted = validate_success(
            api.submit_score(
                round_row["id"], f.score_payload(72), member_headers(competitor)
            ),
            200,
        )
        assert_round_status(submitted, ROUND_SUBMITTED)
        verified = validate_success(
            api.peer_verify(
                round_row["id"], f.peer_verify_payload(PEER_VERIFY),
                member_headers(marker),
            ),
            200,
        )
        assert_round_status(verified, ROUND_PEER_VERIFIED)
        certified = validate_success(
            api.certify_round(round_row["id"], RULES_OFFICIAL), 200
        )
        assert_round_status(certified, ROUND_CERTIFIED)
        assert certified["adjusted_gross"] == 72
        assert_one_decimal(certified["scoring_differential"], 0.5)

        played = fx.read_entry(api, entries[0]["id"])
        assert played["certified_round_count"] == 1
        assert_entry_status(played, ENTRY_COMPETING)
