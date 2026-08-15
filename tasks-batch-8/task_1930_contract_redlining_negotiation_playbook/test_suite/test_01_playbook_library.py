"""Playbook library: creation defaults, clause governance, publish/deprecate/retire."""
from test_helpers import (
    validate_success, validate_error, get_success_data,
    ApiErrorId, TEST_USERS,
    create_playbook_payload, create_clause_payload,
    assert_playbook, assert_clause_template,
    setup_user_directory, headers_by_id, create_active_playbook,
    setup_redlining_ctx, record_deviation, approve_deviation,
    set_logical_clock,
)

OPS = TEST_USERS["ops_admin_headers"]


class TestPlaybookCreation:
    def test_playbook_creation_returns_draft_with_zeroed_counters(self, api):
        """A new playbook starts in DRAFT with null published_at and zeroed counters.

        PRD §3.1: "creates a playbook by supplying a `name`; the new playbook starts in
        `DRAFT` status with `published_at` null and both derived counters at zero."

        Design: Corner/entities/playbook_creation_returns_201_with_defaults
        """
        users = setup_user_directory()
        cc = headers_by_id(users)[users["cc"]["id"]]

        resp = api.create_playbook(create_playbook_payload(name="Fresh"), cc)
        data = validate_success(resp, expected_status=201)
        assert_playbook(data)
        assert data["status"] == "DRAFT", f"expected DRAFT, got {data['status']}"
        assert data["clause_count"] == 0
        assert data["active_negotiation_count"] == 0
        assert data["published_at"] is None, "published_at must be null until publication"
        assert isinstance(data["version"], int) and data["version"] >= 1

    def test_clause_with_empty_fallback_positions_is_created_active(self, api):
        """An empty fallback_positions array is stored as-is; clauses start ACTIVE.

        PRD §3.1: "an empty array declares that no fallback is permitted at all."
        PRD §3.1: "Every clause starts in `ACTIVE` status."

        Design: Corner/entities/clause_template_fallback_positions_default_applied
        """
        users = setup_user_directory()
        hdrs = headers_by_id(users)
        resp = api.create_playbook(create_playbook_payload(name="EmptyFB"), hdrs[users["cc"]["id"]])
        playbook = get_success_data(resp)

        resp = api.create_clause(
            playbook["id"],
            create_clause_payload(clause_key="K", fallback_positions=[]),
            hdrs[users["cc"]["id"]],
        )
        clause = validate_success(resp, expected_status=201)
        assert_clause_template(clause)
        assert clause["fallback_positions"] == [], (
            f"empty fallback array must round-trip, got {clause['fallback_positions']}")
        assert clause["status"] == "ACTIVE"


class TestPlaybookPublicationGuards:
    def test_publish_playbook_with_zero_clauses_fails(self, api):
        """A playbook with no clause templates at all cannot publish.

        PRD §3.1: "a playbook with no clause templates at all cannot publish
        (`ERR_PLAYBOOK_EMPTY`)".

        Design: Corner/validations/publish_playbook_with_zero_clauses_fails
        """
        users = setup_user_directory()
        hdrs = headers_by_id(users)
        playbook = get_success_data(api.create_playbook(
            create_playbook_payload(name="NoClauses"), hdrs[users["cc"]["id"]]))

        resp = api.publish_playbook(playbook["id"], hdrs[users["cc"]["id"]])
        validate_error(resp, ApiErrorId.ERR_PLAYBOOK_EMPTY)
        assert resp.status_code == 409

    def test_deprecate_already_deprecated_playbook_rejected(self, api):
        """DEPRECATED is terminal; a second deprecate is an invalid transition.

        PRD §3.1: "`DEPRECATED` is terminal: a deprecated playbook can never be
        restored to any earlier status." — no transition out of or repeating into
        DEPRECATED is defined, so the generic state guard fires.

        Design: Corner/state_machines/playbook_deprecate_from_deprecated_returns_invalid_state
        """
        users = setup_user_directory()
        hdrs = headers_by_id(users)
        playbook, _ = create_active_playbook(hdrs[users["cc"]["id"]],
                                             clause_specs=[{"clause_key": "K"}])
        get_success_data(api.deprecate_playbook(playbook["id"], hdrs[users["cc"]["id"]]))

        resp = api.deprecate_playbook(playbook["id"], hdrs[users["cc"]["id"]])
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE_TRANSITION)
        assert resp.status_code == 409


class TestClauseRetireCrossEntityGuard:
    def test_clause_retire_blocked_while_deviation_open(self, api):
        """Retiring a clause referenced by an OPEN deviation is refused.

        PRD §3.1: "third that no deviation in `OPEN`, `IN_REVIEW`, or `ESCALATED`
        status still references the clause (`ERR_CLAUSE_HAS_OPEN_DEVIATIONS`)."

        Design: Difficulty/cross_entity_state_dependency/clause_retire_blocked_by_open_deviation
        """
        ctx = setup_redlining_ctx(clause_specs=[{
            "clause_key": "A", "category": "OPERATIONAL", "standard_text": "a",
            "fallback_positions": ["a_fb"], "approver_role_required": "LEGAL_COUNSEL",
            "deviation_severity_cap": "MEDIUM"}])
        dev = record_deviation(ctx, clause_index=0, proposed_text="altA", fallback_index=0)
        assert dev["status"] == "OPEN"
        cc = ctx.headers[ctx.users["cc"]["id"]]

        resp = api.retire_clause(ctx.playbook["id"], ctx.clauses[0]["id"], cc)
        validate_error(resp, ApiErrorId.ERR_CLAUSE_HAS_OPEN_DEVIATIONS)
        assert resp.status_code == 409

        clause = get_success_data(api.get_clause(
            ctx.playbook["id"], ctx.clauses[0]["id"], cc))
        assert clause["status"] == "ACTIVE", "clause must remain ACTIVE after refused retire"

    def test_clause_retire_succeeds_after_deviation_resolved(self, api):
        """Once the referencing deviation is APPROVED, retire succeeds and the
        playbook's clause_count decrements.

        PRD §3.1: "A retired clause moves `ACTIVE → RETIRED`, a transition from which
        it never returns; the playbook's `clause_count` decrements by one and its
        `version` increments."

        Design: Difficulty/cross_entity_state_dependency/clause_retire_blocked_by_open_deviation
        """
        ctx = setup_redlining_ctx(clause_specs=[{
            "clause_key": "A", "category": "OPERATIONAL", "standard_text": "a",
            "fallback_positions": ["a_fb"], "approver_role_required": "LEGAL_COUNSEL",
            "deviation_severity_cap": "MEDIUM"}])
        dev = record_deviation(ctx, clause_index=0, proposed_text="altA", fallback_index=0)
        approve_deviation(ctx, dev)
        assert get_success_data(api.get_deviation(
            ctx.negotiation["id"], dev["id"], ctx.headers[ctx.users["ca"]["id"]]))["status"] == "APPROVED"
        cc = ctx.headers[ctx.users["cc"]["id"]]

        resp = api.retire_clause(ctx.playbook["id"], ctx.clauses[0]["id"], cc)
        clause = validate_success(resp, expected_status=200)
        assert clause["status"] == "RETIRED"

        playbook = get_success_data(api.get_playbook(ctx.playbook["id"], cc))
        assert playbook["clause_count"] == 0, (
            f"clause_count must decrement to 0, got {playbook['clause_count']}")
