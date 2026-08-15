"""Docket entry lifecycle: revision loop, extensions, deadline discipline,
cancellation gates, open-count conservation, cross-entity application gates
(PRD §3.3)."""
from test_helpers import (
    api_client,
    validate_success,
    validate_error,
    ApiErrorId,
    TEST_USERS,
    create_us_rule,
    create_client,
    create_family,
    create_pending_application,
    create_granted_application,
    create_docket_entry_payload,
    create_office_action_payload,
    setup_world_us,
    setup_oa_response_entry,
    get_application,
)

ANY = TEST_USERS["any_headers"]
CLERK = TEST_USERS["clerk_headers"]
MGR = TEST_USERS["manager_headers"]


class TestDocketEntryRejectionRevisionLoop:
    def _started_extended_entry(self):
        create_us_rule()
        client = create_client("LoopCo")
        family = create_family(client["id"], budget_cap_cents=1000000)
        app = create_pending_application(family["id"], application_number="US-L")
        _, entry = setup_oa_response_entry(app["id"], mail_date="2026-05-20")
        validate_success(api_client.start_docket_entry(entry["id"], CLERK), 200)
        validate_success(api_client.request_extension(entry["id"], CLERK), 200)
        validate_success(
            api_client.record_response(entry["id"], {"response_filed_date": "2026-09-20"}, CLERK), 200)
        return app, entry

    def test_record_rejection_resets_due_dates_and_extension_count(self):
        """PRD §3.3: "recording that rejection moves the entry `RESPONSE_FILED →
        IN_PROGRESS`: the request supplies a `new_base_due_date`, both
        `base_due_date` and `current_due_date` reset to it, and
        `extension_count` resets to zero."

        Design: Difficulty/non_linear_state_machine/docket_entry_rejection_revision_loop
        """
        _, entry = self._started_extended_entry()
        data = validate_success(
            api_client.record_rejection(entry["id"], {"new_base_due_date": "2026-12-31"}, CLERK), 200)
        assert data["status"] == "IN_PROGRESS"
        assert data["current_due_date"] == "2026-12-31"
        assert data["extension_count"] == 0

    def test_revision_loop_may_repeat_and_completes(self):
        """PRD §3.3: "This revision loop may repeat without limit" and
        "Completing the entry moves `RESPONSE_FILED → COMPLETED`, decrements
        the application's `open_docket_count` by one, and — when an office
        action references the entry and is `UNDER_RESPONSE` — closes that
        office action to `CLOSED`."

        Design: Difficulty/non_linear_state_machine/docket_entry_rejection_revision_loop
        """
        app, entry = self._started_extended_entry()
        validate_success(
            api_client.record_rejection(entry["id"], {"new_base_due_date": "2026-12-31"}, CLERK), 200)
        refiled = validate_success(
            api_client.record_response(entry["id"], {"response_filed_date": "2026-12-15"}, CLERK), 200)
        assert refiled["status"] == "RESPONSE_FILED"
        done = validate_success(api_client.complete_docket_entry(entry["id"], CLERK), 200)
        assert done["status"] == "COMPLETED"
        assert get_application(app["id"])["open_docket_count"] == 0


class TestRecordResponseRequiresApplicationPending:
    def test_record_response_accepted_while_pending(self):
        """PRD §3.3: "Recording a filed response moves `IN_PROGRESS →
        RESPONSE_FILED`; the request carries the `response_filed_date`, which
        must fall on or before the `current_due_date` (`ERR_DEADLINE_PASSED`),
        and the application must be `PENDING` (`ERR_APPLICATION_NOT_OPEN`)."

        Design: Difficulty/cross_entity_state_dependency/record_response_requires_application_pending
        """
        create_us_rule()
        client = create_client("XCo")
        family = create_family(client["id"], budget_cap_cents=1000000)
        app = create_pending_application(family["id"], application_number="US-X")
        e1 = validate_success(api_client.create_docket_entry(
            app["id"], create_docket_entry_payload(entry_type="STATUTORY", title="E1",
                                                   base_due_date="2026-09-01"), CLERK), 201)
        validate_success(api_client.start_docket_entry(e1["id"], CLERK), 200)
        data = validate_success(
            api_client.record_response(e1["id"], {"response_filed_date": "2026-08-10"}, CLERK), 200)
        assert data["status"] == "RESPONSE_FILED"

    def test_record_response_rejected_once_granted_but_start_still_allowed(self):
        """PRD §3.3: "the application must be `PENDING`
        (`ERR_APPLICATION_NOT_OPEN`)" for record-response, while "Starting work
        moves an entry `PENDING → IN_PROGRESS`; it requires the application to
        be `PENDING` or `GRANTED` (`ERR_APPLICATION_NOT_OPEN`)."

        Design: Difficulty/cross_entity_state_dependency/record_response_requires_application_pending
        """
        create_us_rule()
        client = create_client("XCo")
        family = create_family(client["id"], budget_cap_cents=1000000)
        app = create_granted_application(family["id"], application_number="US-X")
        e2 = validate_success(api_client.create_docket_entry(
            app["id"], create_docket_entry_payload(entry_type="STATUTORY", title="E2",
                                                   base_due_date="2026-10-01"), CLERK), 201)
        started = validate_success(api_client.start_docket_entry(e2["id"], CLERK), 200)
        assert started["status"] == "IN_PROGRESS"
        validate_error(
            api_client.record_response(e2["id"], {"response_filed_date": "2026-08-10"}, CLERK),
            ApiErrorId.ERR_APPLICATION_NOT_OPEN)


class TestExtensionChain:
    def _oa_entry_started(self):
        create_us_rule()
        client = create_client("ExtCo")
        family = create_family(client["id"], budget_cap_cents=1000000)
        app = create_pending_application(family["id"], application_number="US-EX")
        _, entry = setup_oa_response_entry(app["id"], mail_date="2026-05-20")
        validate_success(api_client.start_docket_entry(entry["id"], CLERK), 200)
        return entry

    def test_extension_chain_accumulates_fees_and_moves_due_date(self):
        """PRD §3.3: "Each granted extension increments `extension_count` by
        one, recomputes `current_due_date` as the `base_due_date` shifted
        forward by `extension_count` times the rule's `extension_months`, and
        adds the rule's `extension_fee_cents` to `extension_fees_total_cents`."

        Design: Corner/calculations/extension_chain_fee_accumulation_and_limit
        """
        entry = self._oa_entry_started()
        first = validate_success(api_client.request_extension(entry["id"], CLERK), 200)
        assert first["extension_count"] == 1
        assert first["current_due_date"] == "2026-09-20"
        assert first["extension_fees_total_cents"] == 20000
        second = validate_success(api_client.request_extension(entry["id"], CLERK), 200)
        assert second["extension_count"] == 2
        assert second["current_due_date"] == "2026-10-20"
        assert second["extension_fees_total_cents"] == 40000

    def test_request_beyond_max_extensions_rejected(self):
        """PRD §3.3: "a request that would raise `extension_count` to exactly
        the maximum succeeds, and the request beyond it fails with
        `ERR_EXTENSION_LIMIT_REACHED`."

        Design: Corner/calculations/extension_chain_fee_accumulation_and_limit
        """
        entry = self._oa_entry_started()
        validate_success(api_client.request_extension(entry["id"], CLERK), 200)
        validate_success(api_client.request_extension(entry["id"], CLERK), 200)
        # max_extensions is 2; the third request is the one beyond the limit.
        validate_error(api_client.request_extension(entry["id"], CLERK),
                       ApiErrorId.ERR_EXTENSION_LIMIT_REACHED)

    def test_extension_on_non_oa_entry_type_rejected(self):
        """PRD §3.3: "Extensions of time are available only on
        `OFFICE_ACTION_RESPONSE` entries; requesting one on any other type is
        rejected with `ERR_EXTENSION_NOT_ALLOWED_TYPE`."

        Design: Corner/calculations/extension_rejected_on_non_oa_entry_type
        """
        create_us_rule()
        client = create_client("ExtTypeCo")
        family = create_family(client["id"], budget_cap_cents=1000000)
        app = create_pending_application(family["id"], application_number="US-ET")
        entry = validate_success(api_client.create_docket_entry(
            app["id"], create_docket_entry_payload(entry_type="STATUTORY", title="S",
                                                   base_due_date="2026-09-01"), CLERK), 201)
        validate_error(api_client.request_extension(entry["id"], CLERK),
                       ApiErrorId.ERR_EXTENSION_NOT_ALLOWED_TYPE)


class TestDeadlinePassedOnRecordResponse:
    def test_response_after_extended_due_date_rejected_then_on_date_accepted(self):
        """PRD §3.3: "the request carries the `response_filed_date`, which must
        fall on or before the `current_due_date` (`ERR_DEADLINE_PASSED`), and
        the application must be `PENDING` (`ERR_APPLICATION_NOT_OPEN`)."

        Design: Corner/validations/deadline_passed_on_record_response
        """
        create_us_rule()
        client = create_client("DlCo")
        family = create_family(client["id"], budget_cap_cents=1000000)
        app = create_pending_application(family["id"], application_number="US-DL")
        _, entry = setup_oa_response_entry(app["id"], mail_date="2026-05-20")
        validate_success(api_client.start_docket_entry(entry["id"], CLERK), 200)
        validate_success(api_client.request_extension(entry["id"], CLERK), 200)
        # Extended current_due_date is 2026-09-20; one day past it fails.
        validate_error(
            api_client.record_response(entry["id"], {"response_filed_date": "2026-09-21"}, CLERK),
            ApiErrorId.ERR_DEADLINE_PASSED)
        # Filing exactly on the extended due date succeeds.
        data = validate_success(
            api_client.record_response(entry["id"], {"response_filed_date": "2026-09-20"}, CLERK), 200)
        assert data["status"] == "RESPONSE_FILED"


class TestEntryCancelBlockedByLiveInstruction:
    def test_cancel_blocked_until_linked_instruction_terminal(self):
        """PRD §3.3: "It is blocked while any outside counsel instruction
        linked to the entry is in `DRAFT`, `SENT`, `ACKNOWLEDGED`, or
        `CONFIRMED` status, surfacing `ERR_ENTRY_NOT_CANCELLABLE`; a successful
        cancellation moves the entry to `CANCELLED` and decrements
        `open_docket_count`."

        Design: Corner/validations/entry_cancel_blocked_by_live_instruction
        """
        from test_helpers import setup_counsel_firm, send_instruction
        create_us_rule()
        firm = setup_counsel_firm()
        client = create_client("LnkCo")
        family = create_family(client["id"], budget_cap_cents=1000000)
        app = create_pending_application(family["id"], application_number="US-LK")
        _, entry = setup_oa_response_entry(app["id"], mail_date="2026-05-20")
        ins = send_instruction(app["id"], firm, instruction_type="OA_RESPONSE",
                               due_date="2026-08-20", docket_entry_id=entry["id"])
        validate_error(api_client.cancel_docket_entry(entry["id"], MGR),
                       ApiErrorId.ERR_ENTRY_NOT_CANCELLABLE)
        # Once the linked instruction is cancelled (terminal) the entry cancels.
        validate_success(api_client.cancel_instruction(ins["id"], MGR), 200)
        data = validate_success(api_client.cancel_docket_entry(entry["id"], MGR), 200)
        assert data["status"] == "CANCELLED"
        assert get_application(app["id"])["open_docket_count"] == 0


class TestTerminalLockdownInstructionAndEntry:
    def test_declined_instruction_rejects_acknowledge(self):
        """PRD §3.7: "`COMPLETED`, `DECLINED`, and `CANCELLED` are terminal";
        PRD §2.9: "any transition attempted on a resource already in a terminal
        state is rejected with `ERR_ALREADY_TERMINAL`."

        Design: Corner/state_machines/terminal_lockdown_instruction_and_entry
        """
        from test_helpers import setup_counsel_firm, send_instruction, make_outside_counsel_headers
        create_us_rule()
        firm = setup_counsel_firm()
        client = create_client("TLCo")
        family = create_family(client["id"], budget_cap_cents=1000000)
        app = create_pending_application(family["id"], application_number="US-TL")
        ins = send_instruction(app["id"], firm, due_date="2026-09-01")
        validate_success(
            api_client.decline_instruction(ins["id"], make_outside_counsel_headers(firm["id"])), 200)
        validate_error(
            api_client.acknowledge_instruction(ins["id"], make_outside_counsel_headers(firm["id"])),
            ApiErrorId.ERR_ALREADY_TERMINAL)

    def test_completed_entry_rejects_cancel(self):
        """PRD §3.3: "`COMPLETED`, `CANCELLED`, and `LAPSED` are terminal";
        PRD §2.9: "any transition attempted on a resource already in a terminal
        state is rejected with `ERR_ALREADY_TERMINAL`."

        Design: Corner/state_machines/terminal_lockdown_instruction_and_entry
        """
        create_us_rule()
        client = create_client("TLCo")
        family = create_family(client["id"], budget_cap_cents=1000000)
        app = create_pending_application(family["id"], application_number="US-TL")
        entry = validate_success(api_client.create_docket_entry(
            app["id"], create_docket_entry_payload(entry_type="STATUTORY", title="E1",
                                                   base_due_date="2026-09-01"), CLERK), 201)
        validate_success(api_client.start_docket_entry(entry["id"], CLERK), 200)
        validate_success(
            api_client.record_response(entry["id"], {"response_filed_date": "2026-08-10"}, CLERK), 200)
        validate_success(api_client.complete_docket_entry(entry["id"], CLERK), 200)
        validate_error(api_client.cancel_docket_entry(entry["id"], MGR),
                       ApiErrorId.ERR_ALREADY_TERMINAL)


class TestOpenDocketCountConservation:
    def test_create_then_cancel_restores_open_count(self):
        """PRD §3.3: "the parent application's `open_docket_count` — the count
        of its entries currently `PENDING` or `IN_PROGRESS`, maintained on
        every entry creation, completion, cancellation, and lapse — increases
        by one" on creation, and "a successful cancellation moves the entry to
        `CANCELLED` and decrements `open_docket_count`."

        Design: Difficulty/compensating_invariant/docket_entry_create_cancel_conserves_open_count
        """
        create_us_rule()
        client = create_client("CntCo")
        family = create_family(client["id"], budget_cap_cents=1000000)
        app = create_pending_application(family["id"], application_number="US-CT")
        assert get_application(app["id"])["open_docket_count"] == 0
        entry = validate_success(api_client.create_docket_entry(
            app["id"], create_docket_entry_payload(entry_type="RECORDATION",
                                                   title="Track recordation",
                                                   base_due_date="2026-09-01"), CLERK), 201)
        assert get_application(app["id"])["open_docket_count"] == 1
        validate_success(api_client.cancel_docket_entry(entry["id"], MGR), 200)
        assert get_application(app["id"])["open_docket_count"] == 0
        data = validate_success(api_client.get_docket_entry(entry["id"], ANY), 200)
        assert data["status"] == "CANCELLED"

    def test_two_entries_two_cancels_restore_open_count_stepwise(self):
        """PRD §3.3: "the parent application's `open_docket_count` — the count
        of its entries currently `PENDING` or `IN_PROGRESS`, maintained on
        every entry creation, completion, cancellation, and lapse — increases
        by one."

        Design: Difficulty/compensating_invariant/docket_entry_create_cancel_conserves_open_count
        """
        create_us_rule()
        client = create_client("CntCo")
        family = create_family(client["id"], budget_cap_cents=1000000)
        app = create_pending_application(family["id"], application_number="US-CT")
        e1 = validate_success(api_client.create_docket_entry(
            app["id"], create_docket_entry_payload(entry_type="STATUTORY", title="A",
                                                   base_due_date="2026-09-01"), CLERK), 201)
        e2 = validate_success(api_client.create_docket_entry(
            app["id"], create_docket_entry_payload(entry_type="RECORDATION", title="B",
                                                   base_due_date="2026-10-01"), CLERK), 201)
        assert get_application(app["id"])["open_docket_count"] == 2
        validate_success(api_client.cancel_docket_entry(e1["id"], MGR), 200)
        assert get_application(app["id"])["open_docket_count"] == 1
        validate_success(api_client.cancel_docket_entry(e2["id"], MGR), 200)
        assert get_application(app["id"])["open_docket_count"] == 0
