"""The IRS determination letter track and case closure: DLR filing windows and
outcomes, closure gates, the reconciliation revert edge, and the fiduciary
record."""
from test_helpers import (
    ApiErrorId,
    add_participant,
    begin_distributions,
    create_case,
    create_cleared_rollover,
    create_closure_signoff,
    create_dlr_with_covering_notice,
    create_recorded_forfeiture,
    effectuate_termination,
    file_dlr_on,
    get_case,
    get_participant,
    issue_noit,
    locate_participant,
    setup_case_in_distribution,
    setup_exhausted_search,
    setup_fully_resolved_case,
    validate_error,
    validate_paginated,
    validate_success,
    TEST_USERS,
)

ADMIN = TEST_USERS["admin_headers"]
FIDUCIARY = TEST_USERS["fiduciary_headers"]


def _close_ready_case_with_dlr(api, file_it=True, adverse=False,
                               plan_name="Dlr Gate Co 401k", plan_number="081"):
    """Case in FINAL_RECONCILIATION with one resolved participant, a
    CLOSURE_SIGNOFF entry, and a DLR in DRAFT / FILED / ADVERSE."""
    case = create_case(plan_name=plan_name, plan_number=plan_number)
    participant = add_participant(
        case["id"], 200000, full_name="Dl R", ssn="800000002"
    )
    dlr = create_dlr_with_covering_notice(case["id"])
    if file_it:
        file_dlr_on(dlr["id"])
        if adverse:
            validate_success(
                api.record_determination(dlr["id"], {"outcome": "ADVERSE"}, ADMIN)
            )
    issue_noit(case["id"])
    effectuate_termination(case["id"])
    begin_distributions(case["id"])
    create_cleared_rollover(participant["id"])
    case = validate_success(api.advance_to_reconciliation(case["id"], ADMIN))
    assert case["status"] == "FINAL_RECONCILIATION"
    create_closure_signoff(case["id"])
    return get_case(case["id"]), participant, dlr


class TestCloseBlockedByPendingDlr:
    def test_close_blocked_by_filed_dlr(self, api):
        """PRD §3.7: "no determination letter request may be `DRAFT` or `FILED`
        (otherwise `ERR_DLR_PENDING_BLOCKS_CLOSE`, HTTP 409)".

        Design: Difficulty/cross_entity_state_dependency/close_blocked_by_pending_dlr
        """
        case, _, dlr = _close_ready_case_with_dlr(api, file_it=True)
        resp = api.close_case(case["id"], FIDUCIARY)
        validate_error(resp, ApiErrorId.ERR_DLR_PENDING_BLOCKS_CLOSE)
        assert get_case(case["id"])["status"] == "FINAL_RECONCILIATION"
        data, _ = validate_paginated(api.list_dlrs(case["id"], ADMIN))
        assert data[0]["status"] == "FILED", (
            "the DLR state dependency is isolated: every other close gate held"
        )

    def test_close_blocked_by_draft_dlr(self, api):
        """PRD §3.7: "no determination letter request may be `DRAFT` or `FILED`
        (otherwise `ERR_DLR_PENDING_BLOCKS_CLOSE`, HTTP 409)".

        Design: Difficulty/cross_entity_state_dependency/close_blocked_by_pending_dlr
        """
        case, _, dlr = _close_ready_case_with_dlr(api, file_it=False)
        resp = api.close_case(case["id"], FIDUCIARY)
        validate_error(resp, ApiErrorId.ERR_DLR_PENDING_BLOCKS_CLOSE)
        assert get_case(case["id"])["status"] == "FINAL_RECONCILIATION"


class TestAdverseDlrAndClosure:
    def test_dlr_adverse_blocks_close_then_withdraw_allows_close(self, api):
        """PRD §3.7: "no request may be `ADVERSE` (otherwise
        `ERR_DLR_ADVERSE_BLOCKS_CLOSE`, HTTP 409 — withdraw first)".
        PRD §3.7: "Withdrawal is available from `DRAFT`, `FILED`, or `ADVERSE`
        (otherwise `ERR_DLR_INVALID_STATE`) and moves the request to
        `WITHDRAWN`. Note that `ADVERSE` is not terminal: the sponsor must
        withdraw the adverse request — and may file a fresh one — before the
        case can close."
        PRD §3.7: "A successful close moves the case to the terminal `CLOSED`."
        PRD §3.2: "Beginning distributions requires the case to be
        `TERMINATION_EFFECTIVE` (otherwise `ERR_CASE_INVALID_STATE`)".

        Design: Corner/state_machines/dlr_adverse_blocks_close_then_withdraw_allows_close
        """
        case, _, dlr = _close_ready_case_with_dlr(api, file_it=True, adverse=True)
        resp = api.close_case(case["id"], FIDUCIARY)
        validate_error(resp, ApiErrorId.ERR_DLR_ADVERSE_BLOCKS_CLOSE)
        assert get_case(case["id"])["status"] == "FINAL_RECONCILIATION"

        dlr = validate_success(api.withdraw_dlr(dlr["id"], ADMIN))
        assert dlr["status"] == "WITHDRAWN"
        case = validate_success(api.close_case(case["id"], FIDUCIARY))
        assert case["status"] == "CLOSED"

        # CLOSED is terminal: every further transition is rejected.
        resp = api.begin_distributions(case["id"], ADMIN)
        validate_error(resp, ApiErrorId.ERR_CASE_INVALID_STATE)

    def test_plan_administrator_cannot_close_case(self, api):
        """PRD §2.1: "A request whose role is not authorized for the target
        endpoint is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403)."
        PRD §4: "| POST | `/termination-cases/{id}/close` | FINAL_RECONCILIATION
        → CLOSED; final fiduciary sign-off | IndependentFiduciary |"

        Design: Corner/rbac/plan_administrator_cannot_close_case
        """
        case, _, _ = setup_fully_resolved_case(
            plan_name="Rbac Five Co 401k", plan_number="174"
        )
        resp = api.close_case(case["id"], ADMIN)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE)
        assert get_case(case["id"])["status"] == "FINAL_RECONCILIATION"


class TestFiduciaryRecord:
    def test_narrative_too_short_rejected(self, api):
        """PRD §3.8: "Creating a `FiduciaryLogEntry` carries the case's
        `termination_case_id`, an `entry_type` of `SEARCH_PROTOCOL_SUMMARY`,
        `NOTICE_DECISION`, `DISTRIBUTION_DECISION`, `FORFEITURE_RATIONALE`,
        `PBGC_TRANSFER_RATIONALE`, or `CLOSURE_SIGNOFF`, a free-text `narrative`
        of at least 50 characters (a shorter narrative is rejected with
        `ERR_NARRATIVE_TOO_SHORT`, HTTP 422)".

        Design: Corner/validations/narrative_too_short_returns_error
        """
        case = create_case(plan_name="Narrative Co 401k", plan_number="155")
        resp = api.create_fiduciary_log_entry(
            {
                "termination_case_id": case["id"],
                "entry_type": "NOTICE_DECISION",
                "narrative": "Too short.",
            },
            ADMIN,
        )
        validate_error(resp, ApiErrorId.ERR_NARRATIVE_TOO_SHORT)
        data, _ = validate_paginated(api.list_fiduciary_log_entries(case["id"], ADMIN))
        assert data == [], "the rejected entry is not persisted"


class TestReconciliationRevert:
    def _revert_scenario(self, api):
        """p1 (200000) resolved via cleared rollover; p2 (800000) MISSING with
        an exhausted, documented search and a RECORDED forfeiture; case advanced
        to FINAL_RECONCILIATION."""
        case, plist = setup_case_in_distribution(
            participants=[(200000, 100), (800000, 100)],
            plan_name="Revert Co 401k", plan_number="042",
        )
        p1, p2 = plist
        create_cleared_rollover(p1["id"])
        setup_exhausted_search(case["id"], p2["id"], document=True)
        create_recorded_forfeiture(p2["id"])
        case = validate_success(api.advance_to_reconciliation(case["id"], ADMIN))
        assert case["status"] == "FINAL_RECONCILIATION"
        assert case["all_participants_resolved"] is True
        assert case["remaining_undistributed_cents"] == 0
        return case, p1, p2

    def test_revert_cycle_reopens_distributions(self, api):
        """PRD §3.4: "A case in `FINAL_RECONCILIATION` containing such a
        restored participant may be moved back to `DISTRIBUTION_IN_PROGRESS` by
        a `PlanAdministrator` — the revert edge that a resurfaced forfeited
        participant forces."

        Design: Difficulty/non_linear_state_machine/termination_case_reconciliation_revert_cycle
        """
        case, _, p2 = self._revert_scenario(api)
        locate_participant(p2["id"], verified_address="3 Back St")
        participant = get_participant(p2["id"])
        assert participant["distribution_status"] == "RESTORED"
        case = get_case(case["id"])
        assert case["resolved_participant_count"] == 1, (
            "the restoration knocks one participant back out of the resolved set"
        )
        case = validate_success(api.reopen_distributions(case["id"], ADMIN))
        assert case["status"] == "DISTRIBUTION_IN_PROGRESS"

    def test_reopen_without_restored_participant_rejected(self, api):
        """PRD §3.4: "This reopen requires at least one participant in
        `RESTORED`, failing which the call is rejected with
        `ERR_NO_REOPENABLE_PARTICIPANT` (HTTP 409)."

        Design: Difficulty/non_linear_state_machine/termination_case_reconciliation_revert_cycle
        """
        case, _, _ = self._revert_scenario(api)
        resp = api.reopen_distributions(case["id"], ADMIN)
        validate_error(resp, ApiErrorId.ERR_NO_REOPENABLE_PARTICIPANT)
        assert get_case(case["id"])["status"] == "FINAL_RECONCILIATION"
