"""Judge panels: required-count constants, selector eligibility and ranking,
and the Rotation -> JudgePanel ACTIVE dependency for opening scoring."""
from test_helpers import (
    ApiErrorId,
    assign_all_entries,
    create_entry,
    create_gymnast,
    create_judge,
    create_meet,
    create_panel,
    create_session,
    create_squad,
    fmt_ts,
    generate_rotations,
    get_success_data,
    parse_ts,
    publish_meet,
    set_clock,
    setup_competition_ready,
    validate_error,
    validate_success,
)
from test_helpers.test_users import TEST_USERS

DIRECTOR = TEST_USERS["meet_director_headers"]
REFEREE = TEST_USERS["meet_referee_headers"]


class TestPanelRequiredCount:
    def test_required_judge_count_per_apparatus(self, api, meet_referee_headers):
        """PRD §3.4: "A panel is born `FORMING`, and its `required_judge_count` is computed
        from the apparatus under the USAG rule: `BALANCE_BEAM` and `FLOOR_EXERCISE` panels
        require four judges, while `VAULT` and `UNEVEN_BARS` panels require two."

        Design: Corner/calculations/judge_panel_required_count_per_apparatus
        """
        set_clock()
        meet = create_meet()
        session = create_session(meet["id"])
        expected = {"VAULT": 2, "UNEVEN_BARS": 2, "BALANCE_BEAM": 4, "FLOOR_EXERCISE": 4}
        for apparatus, required in expected.items():
            panel = validate_success(api.create_judge_panel(
                session["id"], {"meet_id": meet["id"], "apparatus": apparatus},
                meet_referee_headers), 201)
            assert panel["required_judge_count"] == required, (
                f"{apparatus} panel must require {required} judges, got "
                f"{panel['required_judge_count']}")
            assert panel["panel_state"] == "FORMING"


class TestSelectorEligibility:
    def test_conflicted_and_unavailable_judge_excluded_from_pool(
            self, api, meet_referee_headers):
        """PRD §3.4: "A judge is eligible when their rating permits the session's level band
        — `BREVET`, `NATIONAL`, and `USA` ratings may judge any band, a `LEVEL_10` rating
        covers `L10` sessions and below, and the remaining ratings follow the same descending
        pattern — when their availability window fully covers the session's `scheduled_start`
        through `scheduled_end`, when they hold no confirmed assignment on another panel
        whose session overlaps this one in time, and when their `affiliated_gym` matches the
        `home_gym` of no athlete entered in the session."
        PRD §3.4: "If the eligible pool is smaller than the panel's required count, the run
        fails with `ERR_INSUFFICIENT_JUDGE_POOL` (HTTP 422)."

        Design: Difficulty/priority_pair_validation_conflict/judge_safety_vs_temporal_availability_conflict
        """
        set_clock()
        meet = create_meet()
        session = create_session(meet["id"])
        create_entry(session["id"], create_gymnast(home_gym="Metro")["id"])
        # Judge violates BOTH filters: affiliated_gym matches the entered athlete's
        # home_gym, and the one-hour window cannot cover the 14:00-18:00 session.
        create_judge(affiliated_gym="Metro",
                     availability_start="2026-05-02T14:00:00Z",
                     availability_end="2026-05-02T15:00:00Z")
        panel = create_panel(session["id"], meet["id"], "VAULT")
        res = api.auto_assign_panel(panel["id"], meet_referee_headers)
        validate_error(res, ApiErrorId.ERR_INSUFFICIENT_JUDGE_POOL)

    def test_unavailable_alone_excludes_from_pool(self, api, meet_referee_headers):
        """PRD §3.4: "A judge is eligible when their rating permits the session's level band
        ... when their availability window fully covers the session's `scheduled_start`
        through `scheduled_end` ... and when their `affiliated_gym` matches the `home_gym`
        of no athlete entered in the session."
        PRD §3.4: "If the eligible pool is smaller than the panel's required count, the run
        fails with `ERR_INSUFFICIENT_JUDGE_POOL` (HTTP 422)."

        Design: Difficulty/priority_pair_validation_conflict/judge_safety_vs_temporal_availability_conflict
        """
        set_clock()
        meet = create_meet()
        session = create_session(meet["id"])
        create_entry(session["id"], create_gymnast(home_gym="Metro")["id"])
        # No conflict (different gym) but the availability window ends at 15:00,
        # well before the session's 18:00 scheduled end.
        create_judge(affiliated_gym="Neutral Club",
                     availability_start="2026-05-02T14:00:00Z",
                     availability_end="2026-05-02T15:00:00Z")
        panel = create_panel(session["id"], meet["id"], "VAULT")
        res = api.auto_assign_panel(panel["id"], meet_referee_headers)
        validate_error(res, ApiErrorId.ERR_INSUFFICIENT_JUDGE_POOL)


class TestSelectorTiebreak:
    def test_identical_ratings_broken_by_usag_judge_number(self, api, meet_referee_headers):
        """PRD §3.4: "Eligible judges are ranked by rating tier descending — `BREVET`
        highest, then `NATIONAL`, `USA`, `LEVEL_10`, `LEVEL_9`, `LEVEL_8`, `LEVEL_7`,
        `LEVEL_4_5`, and `XCEL` lowest — with ties broken by `usag_judge_number` in
        lexicographic ascending order, and the selector takes the first
        `required_judge_count` of them, creating their assignments in `PROPOSED`."

        Design: Corner/cross_cutting/selector_policy_judge_panel_deterministic_tiebreak
        """
        set_clock()
        meet = create_meet()
        session = create_session(meet["id"])
        # Register highest-numbered judge first so selection order cannot be
        # creation order: the tie-break must consult usag_judge_number.
        create_judge(usag_judge_number="J3333333")
        create_judge(usag_judge_number="J1111111")
        create_judge(usag_judge_number="J2222222")
        panel = create_panel(session["id"], meet["id"], "VAULT")  # requires 2
        assignments = validate_success(
            api.auto_assign_panel(panel["id"], meet_referee_headers))
        assert len(assignments) == 2, f"expected 2 proposed assignments, got {len(assignments)}"
        selected_numbers = set()
        for assignment in assignments:
            assert assignment["assignment_state"] == "PROPOSED"
            judge = get_success_data(api.get_judge(assignment["judge_id"], meet_referee_headers))
            selected_numbers.add(judge["usag_judge_number"])
        assert selected_numbers == {"J1111111", "J2222222"}, (
            f"tie-break must select the two lowest usag_judge_number values, got "
            f"{selected_numbers}")


class TestRotationOpenRequiresActivePanel:
    def test_open_scoring_rejected_while_panel_forming(self, api, meet_director_headers):
        """PRD §3.5: "The meet director then opens scoring — `TIMED_WARMUP_HELD` →
        `OPEN_FOR_SCORING` — which requires the judge panel covering this session and
        apparatus to be `ACTIVE` and the logical clock to have reached the rotation's
        `scheduled_start`; the opening stamps `actual_start`, which is null until then."
        PRD §3.4: "A panel cannot go `ACTIVE` while short of its required confirmed count —
        including at the moment a rotation beneath it is opened for scoring; the shortfall is
        reported as `ERR_PANEL_UNDERSTAFFED` (HTTP 422)."

        Design: Difficulty/cross_entity_state_dependency/rotation_open_requires_panel_active
        """
        set_clock()
        meet = create_meet()
        session = create_session(meet["id"])
        create_squad(session["id"], "A", "VAULT")
        create_entry(session["id"], create_gymnast()["id"])
        assign_all_entries(session["id"])
        # Panel exists but has no confirmed judges, so it stays FORMING.
        panel = create_panel(session["id"], meet["id"], "VAULT")
        publish_meet(meet["id"])
        rotations = generate_rotations(session["id"])
        latest_start = max(parse_ts(r["scheduled_start"]) for r in rotations)
        set_clock(fmt_ts(latest_start))
        res = api.open_rotation_scoring(rotations[0]["id"], meet_director_headers)
        validate_error(res, ApiErrorId.ERR_PANEL_UNDERSTAFFED)
        panel_after = get_success_data(api.get_judge_panel(panel["id"], meet_director_headers))
        assert panel_after["panel_state"] == "FORMING"
        rotation_after = get_success_data(api.get_rotation(rotations[0]["id"], meet_director_headers))
        assert rotation_after["state"] == "TIMED_WARMUP_HELD", (
            f"rejected open-scoring must not advance the rotation, got "
            f"{rotation_after['state']}")
        assert rotation_after.get("actual_start") in (None, "")

    def test_open_scoring_succeeds_once_panel_active(self, api, meet_director_headers):
        """PRD §3.4: "When competition begins, every `FULL` panel goes `ACTIVE` as part of
        the meet's cascade into `IN_COMPETITION`, and panels end their service `RELEASED`."
        PRD §3.5: "The meet director then opens scoring — `TIMED_WARMUP_HELD` →
        `OPEN_FOR_SCORING` — which requires the judge panel covering this session and
        apparatus to be `ACTIVE` and the logical clock to have reached the rotation's
        `scheduled_start`; the opening stamps `actual_start`, which is null until then."

        Design: Difficulty/cross_entity_state_dependency/rotation_open_requires_panel_active
        """
        ctx = setup_competition_ready(num_athletes=1)
        rotation = ctx["rotations"][0]
        assert ctx["meet"]["posture"] == "IN_COMPETITION"
        assert get_success_data(api.get_judge_panel(
            ctx["panels"]["VAULT"]["id"], meet_director_headers))["panel_state"] == "ACTIVE"
        opened = validate_success(api.open_rotation_scoring(rotation["id"], meet_director_headers))
        assert opened["state"] == "OPEN_FOR_SCORING"
        assert opened.get("actual_start"), "opening must stamp actual_start"
