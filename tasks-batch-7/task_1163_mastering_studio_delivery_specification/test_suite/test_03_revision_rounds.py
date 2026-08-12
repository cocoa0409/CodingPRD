"""Revision round cycles, reject cascades, and terminal lockdown (PRD §3.6, §2.5)."""
from test_helpers import (
    validate_success, validate_error_is_one_of, is_iso8601_timestamp,
    setup_project_in_revision, setup_project_approved, reject_current_round,
    make_client_headers, TEST_USERS, ApiErrorId,
)

MANAGER = TEST_USERS["manager_headers"]

REJECT_QUOTE = (
    "Rejection moves the round `SUBMITTED → REJECTED`, stamps `resolved_at`, and "
    "immediately opens the next round with `round_index` one higher in `OPEN` "
    "status; the project's `current_revision_round_id` retargets, its "
    "`revision_round_count` increments, the client's `lifetime_revision_count` "
    "increments, and the project's `version` increments as the project returns "
    "`REVISION → MASTERING`."
)

TERMINAL_QUOTE = (
    "Fifth (priority 5), state admissibility: the resource's current state must "
    "permit the requested transition on every action endpoint, failing with "
    "`ERR_INVALID_STATE` (HTTP 409); an entity that has already reached a terminal "
    "state rejects further transitions with `ERR_ALREADY_TERMINAL` (HTTP 409)."
)

TERMINAL_ERROR_IDS = [
    ApiErrorId.ERR_INVALID_STATE,
    ApiErrorId.ERR_ALREADY_TERMINAL,
    ApiErrorId.ERR_NO_ACTIVE_ROUND,
]


class TestMasteringRevisionCycle:

    def test_reject_returns_project_to_mastering_with_new_open_round(self, api):
        """PRD §3.6: "%s"

        After one reject the project is back in MASTERING, its round count is 2, and
        current_revision_round_id points at the freshly opened round.

        Design: Difficulty/non_linear_state_machine/project_mastering_revision_cycle
        """ % REJECT_QUOTE
        ctx = setup_project_in_revision()
        round1_id = ctx["round1"]["id"]
        ctx = reject_current_round(ctx)

        project = ctx["project"]
        assert project["status"] == "MASTERING"
        assert project["revision_round_count"] == 2
        assert project["current_revision_round_id"] is not None
        assert project["current_revision_round_id"] != round1_id
        assert ctx["round"]["status"] == "OPEN"

    def test_reject_marks_old_round_rejected(self, api):
        """PRD §3.6: "%s"

        The rejected round lands in REJECTED with resolved_at stamped.

        Design: Difficulty/non_linear_state_machine/project_mastering_revision_cycle
        """ % REJECT_QUOTE
        ctx = setup_project_in_revision()
        round1_id = ctx["round1"]["id"]
        ctx = reject_current_round(ctx)

        round1 = validate_success(api.get_revision_round(round1_id, MANAGER), 200)
        assert round1["status"] == "REJECTED"
        assert is_iso8601_timestamp(round1.get("resolved_at", "")), (
            "resolved_at must be stamped on rejection")
        assert ctx["round"]["round_index"] == round1["round_index"] + 1


class TestRoundRejectCascade:

    def test_reject_opens_next_round_with_incremented_index(self, api):
        """PRD §3.6: "%s" PRD §3.6: "Round indexes are one-based, monotonically
        increasing per project, and never reused".

        Round 1 REJECTED; round 2 exists with round_index == 2 in OPEN status.

        Design: Difficulty/transitive_cascade/round_reject_depth2_cascade
        """ % REJECT_QUOTE
        ctx = setup_project_in_revision()
        round1_id = ctx["round1"]["id"]
        ctx = reject_current_round(ctx)

        round1 = validate_success(api.get_revision_round(round1_id, MANAGER), 200)
        assert round1["status"] == "REJECTED"
        assert ctx["round"]["round_index"] == 2
        assert ctx["round"]["status"] == "OPEN"

    def test_reject_increments_project_and_client_round_counters(self, api):
        """PRD §3.6: "%s"

        Project returns to MASTERING with revision_round_count == 2, and the owning
        client's lifetime_revision_count reaches 2 (one per opened round).

        Design: Difficulty/transitive_cascade/round_reject_depth2_cascade
        """ % REJECT_QUOTE
        ctx = setup_project_in_revision()
        ctx = reject_current_round(ctx)

        assert ctx["project"]["status"] == "MASTERING"
        assert ctx["project"]["revision_round_count"] == 2
        client = validate_success(api.get_client(ctx["client"]["id"], MANAGER), 200)
        assert client["lifetime_revision_count"] == 2


class TestRevisionRoundTerminalLockdown:

    def test_reject_of_approved_round_rejected(self, api):
        """PRD §2.5: "%s" PRD §3.6: "a project with no open current round for the
        requested operation fails with `ERR_NO_ACTIVE_ROUND` (HTTP 409)."

        An APPROVED round is terminal; rejecting it must fail with a 409 conflict
        and no new round opens.

        Design: Corner/state_machines/revision_round_terminal_lockdown
        """ % TERMINAL_QUOTE
        ctx = setup_project_approved()
        round_id = ctx["round1"]["id"]
        res = api.reject_round(ctx["project"]["id"], round_id, {},
                               make_client_headers(ctx["client"]["id"]))
        assert res.status_code == 409
        validate_error_is_one_of(res, TERMINAL_ERROR_IDS)
        project = validate_success(api.get_project(ctx["project"]["id"], MANAGER), 200)
        assert project["revision_round_count"] == 1, (
            "no new round may open when the reject is rejected")

    def test_second_approve_rejected_without_double_debit(self, api):
        """PRD §2.5: "%s" PRD §2.5: "a failure at an earlier step halts evaluation
        and masks every later check." PRD §3.6: "Approval moves the round `SUBMITTED
        → APPROVED`, stamps `resolved_at`, runs the final quote and writes
        `final_price_cents` in place of the provisional figure, debits the client's
        `account_credit_cents` by that amount".

        The second approve on an already-APPROVED round fails with 409 and the
        client's balance is not debited twice.

        Design: Corner/state_machines/idempotency_second_approve_returns_invalid_state
        """ % TERMINAL_QUOTE
        ctx = setup_project_approved(credit_cents=100000)
        credit_after_first = ctx["client"]["account_credit_cents"]
        round_id = ctx["round1"]["id"]
        res = api.approve_round(ctx["project"]["id"], round_id,
                                make_client_headers(ctx["client"]["id"]))
        assert res.status_code == 409
        validate_error_is_one_of(res, TERMINAL_ERROR_IDS)
        client = validate_success(api.get_client(ctx["client"]["id"], MANAGER), 200)
        assert client["account_credit_cents"] == credit_after_first, (
            "a rejected re-approval must not debit the client again")
