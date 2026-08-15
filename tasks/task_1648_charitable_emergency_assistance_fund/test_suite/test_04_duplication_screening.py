"""Duplication-of-benefits screening: check state machine, the approval gates,
and the ProgramManager override path."""
from test_helpers import (
    ApiErrorId,
    approve_application,
    get_application,
    get_application_version,
    open_cleared_duplication_check,
    open_duplication_check,
    override_duplication_check_payload,
    pass_verification,
    resolve_duplication_check,
    setup_pending_decision,
    setup_submitted_application,
    TEST_USERS,
    validate_error,
    validate_success,
)

CW1 = TEST_USERS["caseworker_headers"]
PM1 = TEST_USERS["program_manager_headers"]


class TestDuplicationCheckStates:
    def test_duplication_override_on_pending_check_rejected(self, api):
        """PRD §3.4: "A `ProgramManager` may then override the flag — moving the
        check `FLAGGED → CLEARED` — by supplying an `override_justification`;
        override attempted on anything other than a `FLAGGED` check likewise
        fails with `ERR_INVALID_DUPLICATION_CHECK_STATE`."

        Design: Corner/state_machines/duplication_override_on_pending_check_rejected
        """
        ctx = setup_submitted_application(requested_amount_cents=5000)
        check = open_duplication_check(
            ctx["application"]["id"], get_application_version(ctx["application"]["id"])
        )
        assert check["status"] == "PENDING"
        resp = api.override_duplication_check(
            check["id"],
            override_duplication_check_payload("verified by phone"),
            PM1,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_DUPLICATION_CHECK_STATE)

    def test_flagged_duplication_blocks_approve_until_manager_override(self, api):
        """PRD §3.4: "Approving or waitlisting an application that has no
        duplication check recorded at all is rejected with
        `ERR_DUPLICATION_CHECK_REQUIRED`, and the same actions are rejected with
        `ERR_DUPLICATION_UNRESOLVED` while any of the application's checks remains
        `PENDING` or `FLAGGED`."
        PRD §3.4: "A `ProgramManager` may then override the flag — moving the
        check `FLAGGED → CLEARED` — by supplying an `override_justification`"

        Design: Corner/validations/flagged_duplication_blocks_approve_until_manager_override
        """
        ctx = setup_pending_decision(requested_amount_cents=5000, resolve_check="FLAGGED")
        app_id = ctx["application"]["id"]
        assert ctx["check"]["status"] == "FLAGGED"
        resp = api.approve_application(app_id, PM1)
        validate_error(resp, ApiErrorId.ERR_DUPLICATION_UNRESOLVED)
        overridden = validate_success(
            api.override_duplication_check(
                ctx["check"]["id"],
                override_duplication_check_payload("agency confirmed different month"),
                PM1,
            ),
            200,
        )
        assert overridden["status"] == "CLEARED"
        assert overridden["override_justification"] == "agency confirmed different month"
        approved = approve_application(app_id)
        assert approved["status"] == "APPROVED"
        award = validate_success(api.get_award(approved["active_award_id"], PM1), 200)
        assert award["awarded_amount_cents"] == 5000


class TestApproveGatedByDuplicationChecks:
    def test_approve_without_any_duplication_check_rejected(self, api):
        """PRD §3.4: "Approving or waitlisting an application that has no
        duplication check recorded at all is rejected with
        `ERR_DUPLICATION_CHECK_REQUIRED`, and the same actions are rejected with
        `ERR_DUPLICATION_UNRESOLVED` while any of the application's checks remains
        `PENDING` or `FLAGGED`."

        Design: Difficulty/cross_entity_state_dependency/approve_gated_by_duplication_check_states
        """
        ctx = setup_pending_decision(
            requested_amount_cents=10000, with_duplication_check=False
        )
        assert ctx["application"]["status"] == "PENDING_DECISION"
        resp = api.approve_application(ctx["application"]["id"], PM1)
        validate_error(resp, ApiErrorId.ERR_DUPLICATION_CHECK_REQUIRED)
        assert get_application(ctx["application"]["id"])["status"] == "PENDING_DECISION"

    def test_approve_succeeds_once_check_cleared(self, api):
        """PRD §3.4: "Approving or waitlisting an application that has no
        duplication check recorded at all is rejected with
        `ERR_DUPLICATION_CHECK_REQUIRED`, and the same actions are rejected with
        `ERR_DUPLICATION_UNRESOLVED` while any of the application's checks remains
        `PENDING` or `FLAGGED`."
        PRD §3.5: "A successful approval creates the AssistanceAward in `ACTIVE`
        status, pins its `policy_id` to the application's pinned policy, stamps
        its `benefit_year` with the clock's current calendar year, sets its
        `awarded_amount_cents` to the determined amount, points the application's
        `active_award_id` at it, moves the application from `PENDING_DECISION`
        into `APPROVED`, and bumps the application's `version`."

        Design: Difficulty/cross_entity_state_dependency/approve_gated_by_duplication_check_states
        """
        ctx = setup_pending_decision(
            requested_amount_cents=10000, with_duplication_check=False
        )
        app_id = ctx["application"]["id"]
        resp = api.approve_application(app_id, PM1)
        validate_error(resp, ApiErrorId.ERR_DUPLICATION_CHECK_REQUIRED)
        open_cleared_duplication_check(app_id, get_application_version(app_id))
        approved = approve_application(app_id)
        assert approved["status"] == "APPROVED"
        award = validate_success(api.get_award(approved["active_award_id"], PM1), 200)
        assert award["awarded_amount_cents"] == 10000
        assert award["status"] == "ACTIVE"
