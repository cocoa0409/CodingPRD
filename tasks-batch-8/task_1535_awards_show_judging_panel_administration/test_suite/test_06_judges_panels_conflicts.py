"""Judge lifecycle, panel assembly thresholds, conflict-of-interest bars,
suspend cascades, and optimistic concurrency (PRD §2.9, §3.5).
"""
from test_helpers import (
    ApiErrorId,
    assert_assignment,
    assert_judge,
    create_conflict_payload,
    create_judge_payload,
    make_judge_headers,
    validate_error,
    validate_success,
)
from test_helpers import fixtures as fx
from test_helpers.test_users import TEST_USERS

ADMIN = TEST_USERS["program_admin_headers"]


class TestJudgeLifecycle:
    def test_new_judge_starts_invited(self, api):
        """PRD §3.5: "New judges are `INVITED` with a `reliability_score_bp` of
        10,000."

        Design: Corner/state_machines/initial_state_on_create
        """
        resp = api.create_judge(
            create_judge_payload(full_name="Fresh Judge", email="fj@x.com"), ADMIN
        )
        judge = validate_success(resp, expected_status=201)
        assert_judge(judge)
        assert judge["status"] == "INVITED"
        assert judge["reliability_score_bp"] == 10000

    def test_declined_judge_cannot_be_activated(self, api):
        """PRD §3.5: "The invited judge personally accepts or declines the
        invitation; declining is terminal (`DECLINED`)."
        PRD §3.8: "Throughout the lifecycle, every state change on an entity
        already in a terminal state is refused with `ERR_ALREADY_TERMINAL`"

        Design: Corner/state_machines/judge_decline_terminal_no_activate
        """
        judge = fx.get_success_data(
            api.create_judge(
                create_judge_payload(full_name="Declining Judge", email="dj@x.com"),
                ADMIN,
            )
        )
        declined = validate_success(
            api.decline_judge(judge["id"], make_judge_headers(judge["id"]))
        )
        assert declined["status"] == "DECLINED"
        resp = api.activate_judge(judge["id"], ADMIN)
        validate_error(resp, ApiErrorId.ERR_ALREADY_TERMINAL)


class TestPanelLockThreshold:
    def _setup_round_with_active_panel(self, api, code: str, num_confirmed: int):
        bundle = fx.setup_season_closed_with_eligible_entries(
            num_entries=1, code=code, panel_size=3
        )
        judges = fx.create_active_judges(3)
        payload = {
            "round_index": 1,
            "scoring_mode": "RAW_RANK",
            "scheduled_window_start": "2026-09-05T00:00:00Z",
            "scheduled_window_end": "2026-09-07T00:00:00Z",
            "advance_count": 1,
        }
        round_ = fx.get_success_data(
            api.create_round(bundle["category"]["id"], payload, ADMIN)
        )
        for position, judge in enumerate(judges[:num_confirmed]):
            role = "CHAIR" if position == 0 else "MEMBER"
            assignment = fx.propose_assignment(round_["id"], judge["id"], role)
            fx.confirm_assignment(assignment["id"], judge["id"])
        return bundle, round_, judges

    def test_lock_panel_below_size_rejected(self, api):
        """PRD §3.6: "Locking the panel moves a round from `CONFIGURING` to
        `PANEL_LOCKED` and requires the season to be `SUBMISSION_CLOSED` or
        `JUDGING`, at least `panel_size` `ACTIVE` assignments, and exactly one
        `ACTIVE` assignment in the `CHAIR` role; a shortfall is
        `ERR_PANEL_INCOMPLETE`"

        Design: Difficulty/boundary_precision_check/panel_size_threshold_exactness
        """
        _, round_, _ = self._setup_round_with_active_panel(api, "GALA-BND1", 2)
        resp = api.lock_panel(round_["id"], ADMIN)
        validate_error(resp, ApiErrorId.ERR_PANEL_INCOMPLETE)
        fetched = validate_success(api.get_round(round_["id"], ADMIN))
        assert fetched["status"] == "CONFIGURING"

    def test_lock_panel_at_exact_size_succeeds(self, api):
        """PRD §3.6: "Locking the panel moves a round from `CONFIGURING` to
        `PANEL_LOCKED` and requires the season to be `SUBMISSION_CLOSED` or
        `JUDGING`, at least `panel_size` `ACTIVE` assignments, and exactly one
        `ACTIVE` assignment in the `CHAIR` role; a shortfall is
        `ERR_PANEL_INCOMPLETE`"

        Design: Difficulty/boundary_precision_check/panel_size_threshold_exactness
        """
        _, round_, _ = self._setup_round_with_active_panel(api, "GALA-BND1B", 3)
        locked = validate_success(api.lock_panel(round_["id"], ADMIN))
        assert locked["status"] == "PANEL_LOCKED"


class TestJudgeSuspendCascade:
    def _setup_locked_panel(self, api, code: str):
        bundle = fx.setup_season_closed_with_eligible_entries(
            num_entries=1, code=code
        )
        round_, judges, assignments = fx.setup_locked_round(
            bundle["category"]["id"],
            round_index=1,
            scoring_mode="RAW_RANK",
            window=("2026-09-05T00:00:00Z", "2026-09-07T00:00:00Z"),
            advance_count=1,
        )
        return bundle, round_, judges, assignments

    def test_suspend_judge_removes_assignments(self, api):
        """PRD §3.5: "Suspending an `ACTIVE` judge removes every `PROPOSED` or
        `ACTIVE` panel assignment of theirs (to `REMOVED`)"

        Design: Difficulty/transitive_cascade/judge_suspend_cascade_round_demotion
        """
        _, round_, judges, assignments = self._setup_locked_panel(api, "GALA-CASC")
        suspended = validate_success(api.suspend_judge(judges[0]["id"], ADMIN))
        assert suspended["status"] == "SUSPENDED"
        listed = validate_success(api.list_round_assignments(round_["id"], ADMIN))
        by_judge = {a["judge_id"]: a for a in listed}
        assert by_judge[judges[0]["id"]]["status"] == "REMOVED"

    def test_suspend_judge_demotes_locked_round(self, api):
        """PRD §3.5: "Suspending an `ACTIVE` judge removes every `PROPOSED` or
        `ACTIVE` panel assignment of theirs (to `REMOVED`) and re-evaluates
        panel completeness: any `PANEL_LOCKED` round that drops below its
        category's `panel_size` is demoted back to `CONFIGURING`."

        Design: Difficulty/transitive_cascade/judge_suspend_cascade_round_demotion
        """
        _, round_, judges, _ = self._setup_locked_panel(api, "GALA-CASC2")
        validate_success(api.suspend_judge(judges[0]["id"], ADMIN))
        fetched = validate_success(api.get_round(round_["id"], ADMIN))
        assert fetched["status"] == "CONFIGURING", (
            "ACTIVE count 2 < panel_size 3 must demote the round"
        )
        listed = validate_success(api.list_round_assignments(round_["id"], ADMIN))
        by_judge = {a["judge_id"]: a["status"] for a in listed}
        assert by_judge[judges[1]["id"]] == "ACTIVE"
        assert by_judge[judges[2]["id"]] == "ACTIVE"


class TestConflictBarOnBallot:
    def _setup_open_round_with_conflicted_judge(self, api, code: str):
        bundle = fx.setup_season_closed_with_eligible_entries(
            num_entries=1, code=code
        )
        round_, judges, _ = fx.setup_locked_round(
            bundle["category"]["id"],
            round_index=1,
            scoring_mode="RAW_RANK",
            window=("2026-09-05T00:00:00Z", "2026-09-07T00:00:00Z"),
            advance_count=1,
        )
        fx.begin_judging(bundle["season"]["id"])
        fx.open_round(round_["id"])
        entry = bundle["entries"][0]
        conflicted = judges[0]
        fx.file_conflict(
            conflicted["id"], bundle["season"]["id"], bundle["entrants"][0]["id"]
        )
        return bundle, round_, entry, conflicted

    def test_conflicted_judge_ballot_rejected_despite_incomplete_map(self, api):
        """PRD §3.6: "a judge is barred from scoring any entry whose entrant
        they conflict with — the conflict bar is enforced both when the ballot
        is created and when it is submitted, and either attempt is refused with
        `ERR_CONFLICT_OF_INTEREST`."
        PRD §2.5: "Every request is evaluated against a fixed validation
        pipeline. Checks run in the order below, and the first failure
        short-circuits the remainder, so an earlier error always masks a later
        one." (conflict-of-interest precedes structural constraints)

        Design: Difficulty/priority_pair_validation_conflict/safety_beats_constraint_on_conflicted_incomplete_score
        """
        _, round_, entry, conflicted = self._setup_open_round_with_conflicted_judge(
            api, "GALA-PRIO2"
        )
        payload = {
            "entry_id": entry["id"],
            "judge_id": conflicted["id"],
            "criterion_scores": {"CRAFT": 8},  # incomplete: IMPACT missing
            "expected_scoring_round_version": fx.current_round_version(round_["id"]),
        }
        resp = api.create_score(
            round_["id"], payload, make_judge_headers(conflicted["id"])
        )
        validate_error(resp, ApiErrorId.ERR_CONFLICT_OF_INTEREST)
        scores = fx.list_round_scores(round_["id"])
        assert scores == [], "a rejected ballot must not persist a Score row"

    def test_conflicted_judge_complete_ballot_rejected(self, api):
        """PRD §3.6: "a judge is barred from scoring any entry whose entrant
        they conflict with — the conflict bar is enforced both when the ballot
        is created and when it is submitted, and either attempt is refused with
        `ERR_CONFLICT_OF_INTEREST`."

        Design: Difficulty/priority_pair_validation_conflict/safety_beats_constraint_on_conflicted_incomplete_score
        """
        _, round_, entry, conflicted = self._setup_open_round_with_conflicted_judge(
            api, "GALA-PRIO2B"
        )
        payload = {
            "entry_id": entry["id"],
            "judge_id": conflicted["id"],
            "criterion_scores": {"CRAFT": 8, "IMPACT": 4},  # complete map
            "expected_scoring_round_version": fx.current_round_version(round_["id"]),
        }
        resp = api.create_score(
            round_["id"], payload, make_judge_headers(conflicted["id"])
        )
        validate_error(resp, ApiErrorId.ERR_CONFLICT_OF_INTEREST)
        scores = fx.list_round_scores(round_["id"])
        assert scores == []


class TestOptimisticConcurrency:
    def test_stale_round_version_rejects_assignment(self, api):
        """PRD §2.9: "`POST /awards/scoring-rounds/{id}/panel-assignments`
        requires `expected_scoring_round_version` matching the target
        `ScoringRound`'s current `version`."
        PRD §2.9: "If the parent entity's `version` has advanced since the
        client last read it — because another writer proposed or confirmed an
        assignment, the judge's affiliation set or status changed, or a ballot
        was posted against the round — the write is rejected with
        `ERR_STALE_VERSION` (HTTP 412) rather than being merged against a stale
        baseline."

        Design: Corner/complexity_layers/occ_stale_version_panel_assignment
        """
        bundle = fx.setup_season_closed_with_eligible_entries(
            num_entries=1, code="GALA-OCC1"
        )
        judges = fx.create_active_judges(2)
        payload = {
            "round_index": 1,
            "scoring_mode": "RAW_RANK",
            "scheduled_window_start": "2026-09-05T00:00:00Z",
            "scheduled_window_end": "2026-09-07T00:00:00Z",
            "advance_count": 1,
        }
        round_ = fx.get_success_data(
            api.create_round(bundle["category"]["id"], payload, ADMIN)
        )
        stale_version = round_["version"]
        first = api.create_panel_assignment(
            round_["id"],
            {
                "judge_id": judges[0]["id"],
                "role": "CHAIR",
                "expected_scoring_round_version": stale_version,
            },
            ADMIN,
        )
        validate_success(first, expected_status=201)
        stale_resp = api.create_panel_assignment(
            round_["id"],
            {
                "judge_id": judges[1]["id"],
                "role": "MEMBER",
                "expected_scoring_round_version": stale_version,
            },
            ADMIN,
        )
        validate_error(stale_resp, ApiErrorId.ERR_STALE_VERSION)

    def test_stale_judge_version_rejects_declaration(self, api):
        """PRD §2.9: "`POST /awards/judges/{id}/conflict-declarations` requires
        `expected_judge_version` matching the target `Judge`'s current
        `version`."
        PRD §2.9: "If the parent entity's `version` has advanced since the
        client last read it — because another writer proposed or confirmed an
        assignment, the judge's affiliation set or status changed, or a ballot
        was posted against the round — the write is rejected with
        `ERR_STALE_VERSION` (HTTP 412) rather than being merged against a stale
        baseline."

        Design: Corner/complexity_layers/occ_stale_version_conflict_declaration
        """
        judge = fx.get_success_data(
            api.create_judge(create_judge_payload(email="j1@x.com"), ADMIN)
        )
        stale_version = judge["version"]
        validate_success(api.accept_judge(judge["id"], make_judge_headers(judge["id"])))
        season = fx.create_season("GALA-OCC2")
        entrant = fx.register_entrant("e1@x.com", "Entrant 1")
        resp = api.create_conflict_declaration(
            judge["id"],
            create_conflict_payload(
                season_id=season["id"],
                entrant_id=entrant["id"],
                conflict_type="PERSONAL",
                severity="SOFT",
                expected_judge_version=stale_version,
            ),
            make_judge_headers(judge["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)


class TestJudgeReliability:
    def test_reliability_recomputed_after_completion_and_recusal(self, api):
        """PRD §3.5: "Reliability is the share of decided assignments — those
        `COMPLETED`, `REMOVED`, or `RECUSED` — that were completed, expressed in
        basis points: a judge with no decided assignments keeps 10,000;
        otherwise the value is the completed count divided by the decided count,
        multiplied by 10,000, and rounded half-up to a whole number."

        Design: Corner/calculations/judge_reliability_recomputed_on_completion
        """
        # One season, two published categories, one eligible entry each.
        season, cat_a = fx.setup_open_season_with_category(
            "GALA-REL", category_overrides={"code": "CAT-RA"}
        )
        cat_b = fx.create_published_category(season["id"], code="CAT-RB")
        entrant = fx.register_entrant("e1@x.com", "Entrant 1")
        for ordinal, category in enumerate((cat_a, cat_b), start=1):
            entry = fx.create_draft_entry(
                category["id"], entrant["id"], title=f"Work {ordinal}"
            )
            fx.attach_accepted_material(entry["id"], entrant["id"], ordinal=ordinal)
            fx.submit_entry(entry["id"], entrant["id"])
            fx.pay_invoice(fx.get_only_invoice(entry["id"])["id"], entrant["id"])
            fx.mark_eligible(entry["id"])
            if category["id"] == cat_a["id"]:
                entry_a = entry
        fx.close_season_submissions(season["id"])

        judges = fx.create_active_judges(3)
        round_a, _, assignments_a = fx.setup_locked_round(
            cat_a["id"], round_index=1, scoring_mode="RAW_RANK",
            window=("2026-09-05T00:00:00Z", "2026-09-07T00:00:00Z"),
            advance_count=1, judges=judges,
        )
        round_b, _, assignments_b = fx.setup_locked_round(
            cat_b["id"], round_index=1, scoring_mode="RAW_RANK",
            window=("2026-09-08T00:00:00Z", "2026-09-10T00:00:00Z"),
            advance_count=1, judges=judges,
        )
        fx.begin_judging(season["id"])
        fx.open_round(round_a["id"])
        fx.score_entries(
            round_a["id"],
            [entry_a],
            judges,
            matrix={(0, 0): {"CRAFT": 8, "IMPACT": 4},
                    (1, 0): {"CRAFT": 8, "IMPACT": 4},
                    (2, 0): {"CRAFT": 8, "IMPACT": 4}},
        )
        fx.close_round(round_a["id"])
        fx.normalize_round(round_a["id"])

        j1 = judges[0]
        after_completion = validate_success(api.get_judge(j1["id"], ADMIN))
        assert after_completion["reliability_score_bp"] == 10000, (
            "1 COMPLETED of 1 decided assignment keeps full reliability"
        )

        # Recusal from the second (still PANEL_LOCKED) round.
        recused = validate_success(
            api.recuse_assignment(assignments_b[0]["id"], make_judge_headers(j1["id"]))
        )
        assert_assignment(recused)
        assert recused["status"] == "RECUSED"
        after_recusal = validate_success(api.get_judge(j1["id"], ADMIN))
        assert after_recusal["reliability_score_bp"] == 5000, (
            "1 COMPLETED of 2 decided assignments -> 5000 bp"
        )
        round_b_now = validate_success(api.get_round(round_b["id"], ADMIN))
        assert round_b_now["status"] == "CONFIGURING", (
            "round demotes when ACTIVE membership falls below panel_size"
        )
