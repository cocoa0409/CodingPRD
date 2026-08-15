"""Retention rule lifecycle, succession, conflicts, and resolution."""
from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    TEST_USERS,
    activate_rule,
    assert_instant_equals,
    author_rule,
    create_program,
    find_open_conflict,
    get_record,
    get_request,
    get_rule,
    get_success_data,
    list_all_conflicts,
    resolve_conflict_payload,
    run_auto_delete_sweep,
    set_clock,
    setup_conflict_blocking_submitted_request,
    setup_open_conflict,
    setup_schedule,
    setup_schedule_with_record,
    supersede_rule_payload,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["platform_admin_headers"]
RM = TEST_USERS["records_manager_headers"]
LC = TEST_USERS["legal_counsel_headers"]


class TestRuleInvalidTransitions:
    def test_rule_invalid_transitions_rejected(self, api):
        """PRD §2.8: "attempting an action against a rule not in the required
        status (for example, activating a rule that is not `DRAFT`, withdrawing
        one that is not `PENDING_CONFLICT`, or retiring one that is neither
        `DRAFT` nor `ACTIVE`) is rejected with `ERR_RULE_INVALID_STATE` (HTTP
        409)"

        Design: Corner/state_machines/rule_invalid_transitions_rejected
        """
        ctx = setup_schedule(months=12, rule_code="R-ACT")
        active_rule = ctx["rule"]
        version_at_active = active_rule["version"]
        draft = author_rule(ctx["program"]["id"], ctx["record_class"]["id"],
                            ctx["jurisdiction"]["id"], rule_code="R-DRAFT",
                            retention_months=24,
                            effective_from="2030-01-01T00:00:00Z")

        reactivate = api.activate_retention_rule(active_rule["id"], RM)
        validate_error(reactivate, ApiErrorId.ERR_RULE_INVALID_STATE)

        withdraw_draft = api.withdraw_retention_rule(draft["id"], RM)
        validate_error(withdraw_draft, ApiErrorId.ERR_RULE_INVALID_STATE)

        after = get_rule(active_rule["id"])
        assert after["version"] == version_at_active, (
            "rejected transitions mutate nothing"
        )
        assert after["status"] == "ACTIVE"
        assert get_rule(draft["id"])["status"] == "DRAFT"


class TestRuleWindowOverlap:
    def test_adjacent_rule_window_activates_cleanly(self, api):
        """PRD §3.2: "Two half-open windows overlap exactly when one's start
        is strictly before the other's end and the other's start is strictly
        before the one's end; mere adjacency (one's `effective_from` exactly
        equal to the other's `effective_to`) is not overlap."
        PRD §3.2: "With no overlap the rule becomes `ACTIVE`."

        Design: Difficulty/resource_temporal_overlap/rule_window_half_open_adjacency
        """
        ctx = setup_schedule(months=36, rule_code="R-INC",
                             effective_from="2020-01-01T00:00:00Z",
                             effective_to="2025-01-01T00:00:00Z")
        adjacent = author_rule(ctx["program"]["id"], ctx["record_class"]["id"],
                               ctx["jurisdiction"]["id"], rule_code="R-ADJ",
                               retention_months=48,
                               effective_from="2025-01-01T00:00:00Z",
                               effective_to="2030-01-01T00:00:00Z")
        activated = validate_success(
            api.activate_retention_rule(adjacent["id"], RM), 200)
        assert activated["status"] == "ACTIVE", (
            "effective_from == incumbent effective_to is adjacency, not overlap"
        )
        assert list_all_conflicts() == [], "no conflict is spawned by adjacency"

    def test_overlapping_rule_window_lands_in_pending_conflict(self, api):
        """PRD §3.2: "With an undeclared overlap the activation still succeeds
        but the rule lands in `PENDING_CONFLICT` instead of `ACTIVE`, and a
        `RetentionConflict` is created in `OPEN` status with the challenger set
        to the rule just activated; the incumbent is selected from among the
        overlapping `ACTIVE` rules by earliest `created_at`, breaking ties by
        ascending `rule_code`."

        Design: Difficulty/resource_temporal_overlap/rule_window_half_open_adjacency
        """
        ctx = setup_schedule(months=36, rule_code="R-INC",
                             effective_from="2020-01-01T00:00:00Z",
                             effective_to="2025-01-01T00:00:00Z")
        adjacent = author_rule(ctx["program"]["id"], ctx["record_class"]["id"],
                               ctx["jurisdiction"]["id"], rule_code="R-ADJ",
                               retention_months=48,
                               effective_from="2025-01-01T00:00:00Z",
                               effective_to="2030-01-01T00:00:00Z")
        assert activate_rule(adjacent["id"])["status"] == "ACTIVE"

        overlapping = author_rule(ctx["program"]["id"], ctx["record_class"]["id"],
                                  ctx["jurisdiction"]["id"], rule_code="R-OVR",
                                  retention_months=48,
                                  effective_from="2024-06-01T00:00:00Z",
                                  effective_to="2024-12-01T00:00:00Z")
        landed = validate_success(
            api.activate_retention_rule(overlapping["id"], RM), 200)
        assert landed["status"] == "PENDING_CONFLICT"

        open_conflicts = [c for c in list_all_conflicts() if c["status"] == "OPEN"]
        assert len(open_conflicts) == 1, "exactly one OPEN conflict exists"
        assert open_conflicts[0]["incumbent_rule_id"] == ctx["rule"]["id"], (
            "the earliest-created overlapping ACTIVE rule is the incumbent"
        )
        assert open_conflicts[0]["challenger_rule_id"] == overlapping["id"]


class TestConflictTiebreaks:
    def test_conflict_activation_lands_pending_with_incumbent(self, api):
        """PRD §3.2: "With an undeclared overlap the activation still succeeds
        but the rule lands in `PENDING_CONFLICT` instead of `ACTIVE`, and a
        `RetentionConflict` is created in `OPEN` status with the challenger set
        to the rule just activated"

        Design: Difficulty/combinatorial_formula/conflict_tiebreak_newer_rule_wins
        """
        ctx = setup_schedule(months=84, rule_code="R-AAA")
        set_clock("2026-08-02T00:00:00Z")
        challenger = author_rule(ctx["program"]["id"], ctx["record_class"]["id"],
                                 ctx["jurisdiction"]["id"], rule_code="R-ZZZ",
                                 retention_months=84)
        landed = validate_success(
            api.activate_retention_rule(challenger["id"], RM), 200)
        assert landed["status"] == "PENDING_CONFLICT"

        conflict = find_open_conflict(challenger["id"])
        assert conflict["incumbent_rule_id"] == ctx["rule"]["id"]
        assert conflict["challenger_rule_id"] == challenger["id"]

    def test_newer_rule_wins_tiebreak_on_equal_months(self, api):
        """PRD §3.3: "In either strategy, a tie on `retention_months` is broken
        first by `created_at` descending (the newer rule wins), then by
        `rule_code` ascending (lexicographic; never by id)."
        PRD §3.3: "On resolution the winner becomes or stays `ACTIVE`, the
        loser becomes `SUPERSEDED` with its `superseded_by_id` set to the
        winner and its `version` incremented by 1"

        Design: Difficulty/combinatorial_formula/conflict_tiebreak_newer_rule_wins
        """
        ctx = setup_schedule(months=84, rule_code="R-AAA")
        incumbent = ctx["rule"]
        set_clock("2026-08-02T00:00:00Z")
        challenger = author_rule(ctx["program"]["id"], ctx["record_class"]["id"],
                                 ctx["jurisdiction"]["id"], rule_code="R-ZZZ",
                                 retention_months=84)
        activate_rule(challenger["id"])
        conflict = find_open_conflict(challenger["id"])

        resolved = validate_success(api.resolve_retention_conflict(
            conflict["id"], resolve_conflict_payload(strategy="APPLY_LONGEST"),
            RM), 200)
        assert resolved["status"] == "RESOLVED"
        assert resolved["governing_rule_id"] == challenger["id"], (
            "months tie at 84, so created_at DESC picks the newer challenger "
            "(R-ZZZ would lose the rule_code tie-break, which is never reached)"
        )
        assert get_rule(challenger["id"])["status"] == "ACTIVE"
        loser = get_rule(incumbent["id"])
        assert loser["status"] == "SUPERSEDED"
        assert loser["superseded_by_id"] == challenger["id"]

    def test_conflict_tiebreak_rule_code_asc_on_equal_created_at(self, api):
        """PRD §3.3: "In either strategy, a tie on `retention_months` is broken
        first by `created_at` descending (the newer rule wins), then by
        `rule_code` ascending (lexicographic; never by id)."

        Design: Corner/calculations/conflict_tiebreak_rule_code_asc_on_equal_created_at
        """
        ctx = setup_schedule(months=60, rule_code="R-ZZZ")
        incumbent = ctx["rule"]
        # The clock is never advanced, so both rules share one created_at reading.
        challenger = author_rule(ctx["program"]["id"], ctx["record_class"]["id"],
                                 ctx["jurisdiction"]["id"], rule_code="R-AAA",
                                 retention_months=60)
        activate_rule(challenger["id"])
        conflict = find_open_conflict(challenger["id"])

        resolved = validate_success(api.resolve_retention_conflict(
            conflict["id"], resolve_conflict_payload(strategy="APPLY_LONGEST"),
            RM), 200)
        assert resolved["governing_rule_id"] == challenger["id"], (
            "months and created_at both tie, so rule_code ASC decides: "
            "R-AAA beats R-ZZZ"
        )
        assert get_rule(incumbent["id"])["status"] == "SUPERSEDED"


class TestWithdrawCycle:
    def test_withdraw_returns_challenger_to_draft_and_withdraws_conflict(self, api):
        """PRD §3.2: "A `PENDING_CONFLICT` challenger may be withdrawn by a
        `RecordsManager`, returning it to `DRAFT`; the linked `OPEN` conflict
        becomes `WITHDRAWN`"

        Design: Difficulty/non_linear_state_machine/retention_rule_conflict_withdraw_cycle
        """
        ctx, incumbent, challenger, conflict = setup_open_conflict(
            inc_months=84, ch_months=120)
        assert challenger["status"] == "PENDING_CONFLICT"
        assert conflict["status"] == "OPEN"

        withdrawn = validate_success(
            api.withdraw_retention_rule(challenger["id"], RM), 200)
        assert withdrawn["status"] == "DRAFT"
        after = validate_success(api.get_retention_conflict(conflict["id"], RM), 200)
        assert after["status"] == "WITHDRAWN"
        assert get_rule(incumbent["id"])["status"] == "ACTIVE", (
            "the incumbent keeps governing after the challenger withdraws"
        )

    def test_reentry_spawns_new_conflict_then_resolution_activates(self, api):
        """PRD §3.2: "With an undeclared overlap the activation still succeeds
        but the rule lands in `PENDING_CONFLICT` instead of `ACTIVE`, and a
        `RetentionConflict` is created in `OPEN` status with the challenger set
        to the rule just activated"
        PRD §3.3: "On resolution the winner becomes or stays `ACTIVE`, the
        loser becomes `SUPERSEDED` with its `superseded_by_id` set to the
        winner and its `version` incremented by 1, and the conflict moves to
        `RESOLVED`"

        Design: Difficulty/non_linear_state_machine/retention_rule_conflict_withdraw_cycle
        """
        ctx, incumbent, challenger, first_conflict = setup_open_conflict(
            inc_months=84, ch_months=120)
        validate_success(api.withdraw_retention_rule(challenger["id"], RM), 200)

        # Re-entering the cycle spawns a NEW conflict, not the withdrawn one.
        reactivated = validate_success(
            api.activate_retention_rule(challenger["id"], RM), 200)
        assert reactivated["status"] == "PENDING_CONFLICT"
        second_conflict = find_open_conflict(challenger["id"])
        assert second_conflict["id"] != first_conflict["id"]

        resolved = validate_success(api.resolve_retention_conflict(
            second_conflict["id"], resolve_conflict_payload(strategy="APPLY_LONGEST"),
            RM), 200)
        assert resolved["status"] == "RESOLVED"
        assert resolved["governing_rule_id"] == challenger["id"], (
            "APPLY_LONGEST selects max(84, 120) — the challenger"
        )
        assert get_rule(challenger["id"])["status"] == "ACTIVE"
        assert get_rule(incumbent["id"])["status"] == "SUPERSEDED"


class TestResolutionCascade:
    def test_challenger_activation_blocks_record_and_stales_request(self, api):
        """PRD §3.4: "First, if any `OPEN` retention conflict exists for the
        record's (class, jurisdiction), there is no governing rule and the
        record's posture is `CONFLICT_BLOCKED`"
        PRD §3.2: "With an undeclared overlap the activation still succeeds but
        the rule lands in `PENDING_CONFLICT` instead of `ACTIVE`, and a
        `RetentionConflict` is created in `OPEN` status with the challenger set
        to the rule just activated"

        Design: Difficulty/transitive_cascade/conflict_resolution_cascade_record_recompute
        """
        ctx, record, request, incumbent, challenger, conflict = (
            setup_conflict_blocking_submitted_request())
        assert challenger["status"] == "PENDING_CONFLICT"
        assert conflict["status"] == "OPEN"
        assert conflict["incumbent_rule_id"] == incumbent["id"]
        assert conflict["challenger_rule_id"] == challenger["id"]

        blocked = get_record(record["id"])
        assert blocked["disposition_posture"] == "CONFLICT_BLOCKED", (
            "the OPEN conflict strips the record's governing rule"
        )
        assert blocked["governing_rule_id"] is None

    def test_resolution_recomputes_record_and_supersedes_loser(self, api):
        """PRD §3.3: "Every record of the contested (class, jurisdiction) then
        has its `retention_due_date`, `governing_rule_id`, and
        `disposition_posture` recomputed, with the same `stale_item_count`
        adjustments on containing `SUBMITTED`/`APPROVED` requests as in rule
        activation: plus 1 for each record leaving `ELIGIBLE`, minus 1 for each
        entering `ELIGIBLE`."

        Design: Difficulty/transitive_cascade/conflict_resolution_cascade_record_recompute
        """
        ctx, record, request, incumbent, challenger, conflict = (
            setup_conflict_blocking_submitted_request())
        stale_before = get_request(request["id"])["stale_item_count"]
        resolved = validate_success(api.resolve_retention_conflict(
            conflict["id"], resolve_conflict_payload(strategy="APPLY_LONGEST"),
            RM), 200)
        assert resolved["status"] == "RESOLVED"
        assert resolved["governing_rule_id"] == challenger["id"]

        assert get_rule(incumbent["id"])["status"] == "SUPERSEDED"
        recomputed = get_record(record["id"])
        assert recomputed["governing_rule_id"] == challenger["id"]
        # event 2026-06-01 + 120 months -> due 2036-06-01.
        assert_instant_equals(recomputed["retention_due_date"], "2036-06-01T00:00:00Z")
        assert recomputed["disposition_posture"] == "RETAINED"
        assert get_request(request["id"])["stale_item_count"] == stale_before, (
            "the record moved CONFLICT_BLOCKED -> RETAINED, never entering "
            "ELIGIBLE, so the resolution adjusts no counter"
        )


class TestRetireProtection:
    def test_retire_rule_blocked_until_records_destroyed(self, api):
        """PRD §3.2: "an `ACTIVE` rule may retire only when zero
        `ACTIVE`-status records carry it as their `governing_rule_id`;
        otherwise the retirement is rejected with
        `ERR_RULE_HAS_GOVERNED_RECORDS` (HTTP 409). Destroyed-record tombstones
        do not block retirement — only live records do."

        Design: Corner/state_machines/retire_rule_blocked_until_records_destroyed
        """
        ctx, record = setup_schedule_with_record(months=1)
        rule = ctx["rule"]

        blocked = api.retire_retention_rule(rule["id"], RM)
        validate_error(blocked, ApiErrorId.ERR_RULE_HAS_GOVERNED_RECORDS)

        sweep = run_auto_delete_sweep(ctx["program"]["id"])
        assert sweep["destroyed_count"] == 1
        assert get_record(record["id"])["status"] == "DESTROYED"

        retired = validate_success(api.retire_retention_rule(rule["id"], RM), 200)
        assert retired["status"] == "RETIRED", (
            "destroyed tombstones no longer count as governed records"
        )


class TestResolveGuards:
    def test_invalid_enum_on_resolve_returns_400(self, api):
        """PRD §2.8: "an enum field carrying a value outside its declared set
        (across `trigger_basis`, `ack_sla_mode`, `method`, resolution
        `strategy`, and the `disposition_posture` filter) is rejected with
        `ERR_INVALID_ENUM_VALUE` (HTTP 400)."

        Design: Corner/validations/invalid_enum_on_resolve_returns_400
        """
        ctx, incumbent, challenger, conflict = setup_open_conflict(
            inc_months=84, ch_months=120)
        resp = api.resolve_retention_conflict(
            conflict["id"], {"strategy": "BEST_EFFORT"}, RM)
        validate_error(resp, ApiErrorId.ERR_INVALID_ENUM_VALUE)
        after = validate_success(api.get_retention_conflict(conflict["id"], RM), 200)
        assert after["status"] == "OPEN", "a rejected resolve has no side effects"

    def test_resolve_closed_conflict_rejected(self, api):
        """PRD §3.3: "Resolving it (via the resolution action on the conflict)
        requires the conflict to currently be `OPEN` — otherwise
        `ERR_CONFLICT_NOT_OPEN` (HTTP 409)"

        Design: Corner/validations/resolve_closed_conflict_rejected
        """
        ctx, incumbent, challenger, conflict = setup_open_conflict(
            inc_months=84, ch_months=120)
        resolved = validate_success(api.resolve_retention_conflict(
            conflict["id"], resolve_conflict_payload(strategy="APPLY_LONGEST"),
            RM), 200)
        assert resolved["governing_rule_id"] == challenger["id"]

        again = api.resolve_retention_conflict(
            conflict["id"], resolve_conflict_payload(strategy="APPLY_LONGEST"), RM)
        validate_error(again, ApiErrorId.ERR_CONFLICT_NOT_OPEN)
        after = validate_success(api.get_retention_conflict(conflict["id"], RM), 200)
        assert after["governing_rule_id"] == challenger["id"], (
            "the first resolution stands"
        )

    def test_apply_shortest_requires_counsel_and_justification(self, api):
        """PRD §3.3: "The strategy `APPLY_SHORTEST` is a regulatory downgrade
        available only to `LegalCounsel` — any other role is rejected with
        `ERR_SHORTEST_STRATEGY_REQUIRES_COUNSEL` (HTTP 403) — and requires a
        `justification` of at least 20 characters (shorter text is rejected
        with `ERR_JUSTIFICATION_TOO_SHORT`, HTTP 400); it selects the rule with
        the smaller `retention_months`."

        Design: Corner/validations/apply_shortest_requires_counsel_and_justification
        """
        ctx, incumbent, challenger, conflict = setup_open_conflict(
            inc_months=84, ch_months=120)

        by_rm = api.resolve_retention_conflict(
            conflict["id"],
            {"strategy": "APPLY_SHORTEST",
             "justification": "shorter retention approved here"},
            RM)
        validate_error(by_rm, ApiErrorId.ERR_SHORTEST_STRATEGY_REQUIRES_COUNSEL)

        short_text = api.resolve_retention_conflict(
            conflict["id"],
            {"strategy": "APPLY_SHORTEST", "justification": "short"},
            LC)
        validate_error(short_text, ApiErrorId.ERR_JUSTIFICATION_TOO_SHORT)

        resolved = validate_success(api.resolve_retention_conflict(
            conflict["id"],
            {"strategy": "APPLY_SHORTEST",
             "justification": "Counsel approved shorter statutory minimum"},
            LC), 200)
        assert resolved["status"] == "RESOLVED"
        assert resolved["governing_rule_id"] == incumbent["id"], (
            "APPLY_SHORTEST selects min(84, 120) — the incumbent"
        )
        assert get_rule(challenger["id"])["status"] == "SUPERSEDED"


class TestSupersedeConcurrency:
    def test_supersede_with_stale_version_rejected(self, api):
        """PRD §2.6: "The first protected write is the authoring of a
        succession rule: a request to supersede an existing active retention
        rule must carry `expected_retention_rule_version` equal to the target
        rule's current `version`. The target's `version` legitimately advances
        whenever a succession head is claimed, so a client holding an older
        observed version is necessarily working from a stale view of the
        succession chain and is rejected with `ERR_STALE_VERSION` (HTTP 412)."
        PRD §3.2: "Creating the successor also increments the target's
        `version` by 1 — the succession head has been claimed"

        Design: Corner/validations/supersede_with_stale_version_rejected
        """
        ctx = setup_schedule(months=84, rule_code="R-INC")
        incumbent = ctx["rule"]
        observed_version = incumbent["version"]

        first = validate_success(api.supersede_retention_rule(
            incumbent["id"],
            supersede_rule_payload("R-S1", 96, observed_version),
            RM), 201)
        assert first["status"] == "DRAFT"
        assert first["supersedes_rule_id"] == incumbent["id"]
        assert first["record_class_id"] == incumbent["record_class_id"], (
            "the successor inherits program/class/jurisdiction from the target"
        )

        replay = api.supersede_retention_rule(
            incumbent["id"],
            supersede_rule_payload("R-S2", 108, observed_version),
            RM)
        validate_error(replay, ApiErrorId.ERR_STALE_VERSION)

        assert get_rule(incumbent["id"])["version"] == observed_version + 1, (
            "only the winning succession-head claim bumped the target version"
        )


class TestBodyReferenceExistence:
    def test_rule_with_nonexistent_class_returns_404(self, api):
        """PRD §2.4: "Identifiers referenced inside a request body — such as
        `record_ids`, `custodian_ids`, `record_class_id`, `jurisdiction_id`,
        `supersedes_rule_id`, or `program_id` — are validated for existence
        after the path and before domain state checks: a missing record id
        yields `ERR_REFERENCED_RECORD_NOT_FOUND` (HTTP 404), while a missing
        non-record entity id yields `ERR_REFERENCED_ENTITY_NOT_FOUND` (HTTP
        404)."

        Design: Corner/errors/rule_with_nonexistent_class_returns_404
        """
        program = create_program(name="P")
        jur = get_success_data(api.create_jurisdiction(
            {"program_id": program["id"], "code": "US-FED", "name": "Federal"},
            ADMIN))
        resp = api.create_retention_rule(
            {
                "program_id": program["id"],
                "record_class_id": NON_EXISTENT_UUID,
                "jurisdiction_id": jur["id"],
                "rule_code": "R-X",
                "retention_months": 12,
                "trigger_basis": "EVENT_DATE",
                "effective_from": "2020-01-01T00:00:00Z",
            },
            RM,
        )
        validate_error(resp, ApiErrorId.ERR_REFERENCED_ENTITY_NOT_FOUND)
