"""Rosters, entries, and squads: identifier formats, double-entry guard,
check-in floor-access precondition, and the scratch cascade."""
import pytest

from test_helpers import (
    ApiErrorId,
    add_published_score,
    create_credentialed_coach,
    create_entry,
    create_gymnast,
    create_gymnast_payload,
    create_judge_payload,
    create_meet,
    create_score_payload,
    create_session,
    create_squad,
    generate_rotations,
    get_success_data,
    make_coach_headers,
    make_judge_panel_chief_headers,
    open_rotation,
    set_clock,
    setup_competition_ready,
    validate_error,
    validate_error_is_one_of,
    validate_success,
)
from test_helpers.test_users import TEST_USERS

DIRECTOR = TEST_USERS["meet_director_headers"]


class TestGymnastRegistration:
    def test_gymnast_usag_number_format_enforced(self, api, meet_director_headers):
        """PRD §3.2: "A `MeetDirector` registers a Gymnast with a globally unique
        `usag_member_number` (the uppercase letter A followed by exactly seven digits)".
        PRD §2.6: "A request body that is missing a required field or is malformed at the
        schema level is rejected with `ERR_INVALID_REQUEST` (HTTP 400) before any business
        rule is evaluated."

        Design: Corner/entities/gymnast_usag_number_format_constraint
        """
        set_clock()
        res = api.create_gymnast(
            create_gymnast_payload(usag_member_number="X1234567"), meet_director_headers)
        validate_error(res, ApiErrorId.ERR_INVALID_REQUEST)


class TestDoubleEntry:
    def test_gymnast_double_entry_in_same_meet_rejected(self, api, meet_director_headers):
        """PRD §3.2: "Second, the double-entry rule: the same gymnast must not already hold
        an entry in another session of the same meet whose `entry_status` is anything other
        than `SCRATCHED`; a violation is rejected with `ERR_GYMNAST_DOUBLE_ENTERED`
        (HTTP 409)."

        Design: Corner/validations/gymnast_double_entry_in_same_meet
        """
        set_clock()
        meet = create_meet()
        session_one = create_session(
            meet["id"], session_label="S1", scheduled_start="2026-05-02T09:00:00Z",
            scheduled_end="2026-05-02T12:00:00Z")
        session_two = create_session(meet["id"], session_label="S2")
        gymnast = create_gymnast()
        validate_success(
            api.create_athlete_entry(session_one["id"], {"gymnast_id": gymnast["id"]},
                                     meet_director_headers), 201)
        res = api.create_athlete_entry(session_two["id"], {"gymnast_id": gymnast["id"]},
                                       meet_director_headers)
        validate_error(res, ApiErrorId.ERR_GYMNAST_DOUBLE_ENTERED)


class TestCheckInPreconditions:
    def test_check_in_requires_floor_access_granted(self, api, meet_director_headers):
        """PRD §3.2: "On meet day a `Coach` checks the athlete in — `REGISTERED` →
        `CHECKED_IN` — provided the coach holds a pass with floor access granted on the
        parent meet and the coach's `affiliated_gym` matches the gymnast's `home_gym`."
        PRD §2.9: "then the entity-specific state precondition of the requested transition
        (`ERR_INVALID_STATE`, HTTP 409)." PRD §2.9 also names coach credential validity
        (`ERR_COACH_CREDENTIAL_LAPSED`) as the safety-tier rejection for coach-gated
        actions; PRD does not pin which of the two fires when the pass is not granted,
        so either catalogue member satisfies the stated rule.

        Design: Corner/state_machines/coach_check_in_requires_floor_access_granted
        """
        set_clock()
        meet = create_meet()
        session = create_session(meet["id"])
        gymnast = create_gymnast(home_gym="Metro")
        entry = create_entry(session["id"], gymnast["id"])
        coach = create_credentialed_coach(gym="Metro")
        # Pass is ISSUED only — floor access never granted.
        meet_pass = get_success_data(
            api.issue_coach_pass(meet["id"], {"coach_id": coach["id"]}, DIRECTOR))
        assert meet_pass["pass_state"] == "ISSUED"
        res = api.check_in_entry(entry["id"], make_coach_headers(coach["id"]))
        validate_error_is_one_of(res, [ApiErrorId.ERR_INVALID_STATE,
                                       ApiErrorId.ERR_COACH_CREDENTIAL_LAPSED])
        after = get_success_data(api.get_athlete_entry(entry["id"], meet_director_headers))
        assert after["entry_status"] == "REGISTERED", "denied check-in must not transition"


class TestScratchCascade:
    def test_scratch_voids_draft_scores_and_recomputes_squad_count(
            self, api, meet_director_headers, meet_referee_headers):
        """PRD §3.2: "Scratching cascades: every score of the entry still in `DRAFT`
        transitions to `VOID`, and the parent squad's `athlete_count` is recomputed."
        PRD §3.2: "its `athlete_count` is the derived count of entries linked to the squad
        whose `entry_status` is `REGISTERED` or `CHECKED_IN`."

        Design: Difficulty/transitive_cascade/scratch_cascade_entry_to_score_to_squad_to_panel
        """
        set_clock()
        meet = create_meet()
        session = create_session(meet["id"])
        squad = create_squad(session["id"], "A", "VAULT")
        entries = [create_entry(session["id"], create_gymnast()["id"]) for _ in range(3)]
        get_success_data(api.assign_squads(session["id"], meet_director_headers))
        squad_before = get_success_data(api.get_squad(squad["id"], meet_director_headers))
        assert squad_before["athlete_count"] == 3

        rotations = generate_rotations(session["id"])
        judge = get_success_data(api.create_judge(create_judge_payload(),
                                                  meet_referee_headers))
        draft = get_success_data(api.create_score(
            entries[0]["id"],
            create_score_payload(rotations[0]["id"], "VAULT", 5.0, 8.0),
            make_judge_panel_chief_headers(judge["id"])))
        assert draft["score_state"] == "DRAFT"

        scratched = validate_success(api.scratch_entry(
            entries[0]["id"], {"scratch_reason": "INJURY"}, meet_director_headers))
        assert scratched["entry_status"] == "SCRATCHED"

        score_after = get_success_data(api.get_score(draft["id"], meet_director_headers))
        assert score_after["score_state"] == "VOID", (
            f"DRAFT score of a scratched entry must cascade to VOID, got "
            f"{score_after['score_state']}")
        squad_after = get_success_data(api.get_squad(squad["id"], meet_director_headers))
        assert squad_after["athlete_count"] == 2, (
            f"squad athlete_count must drop 3 -> 2 after the scratch, got "
            f"{squad_after['athlete_count']}")

    def test_scratch_from_competing_retains_published_score(
            self, api, meet_director_headers):
        """PRD §3.2: "For an entry scratched from `COMPETING`, scores already past `DRAFT`
        are retained as historical record rather than voided."

        Design: Difficulty/transitive_cascade/scratch_cascade_entry_to_score_to_squad_to_panel
        """
        ctx = setup_competition_ready(num_athletes=1)
        rotation = ctx["rotations"][0]
        open_rotation(rotation["id"])
        published = add_published_score(ctx, ctx["entries"][0], rotation, 5.0, 8.0, 0.0)
        assert published["score_state"] == "PUBLISHED"
        competing = get_success_data(
            api.get_athlete_entry(ctx["entries"][0]["id"], meet_director_headers))
        assert competing["entry_status"] == "COMPETING"

        scratched = validate_success(api.scratch_entry(
            competing["id"], {"scratch_reason": "INJURY"}, meet_director_headers))
        assert scratched["entry_status"] == "SCRATCHED"

        score_after = get_success_data(api.get_score(published["id"], meet_director_headers))
        assert score_after["score_state"] == "PUBLISHED", (
            f"a score past DRAFT must be retained when its entry is scratched from "
            f"COMPETING, got {score_after['score_state']}")
        assert score_after["provisional_total"] == pytest.approx(13.0, abs=0.001)
