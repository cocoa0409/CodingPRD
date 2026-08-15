"""Outside counsel instructions and assignment recordation: exclusivity
windows, accreditation, scope, jurisdiction gates, segregation of duties
(PRD §3.7, §3.8, §3.5, §3.4)."""
from test_helpers import (
    api_client,
    validate_success,
    validate_error,
    ApiErrorId,
    TEST_USERS,
    create_us_rule,
    create_rule,
    create_client,
    create_contact,
    create_family,
    create_application,
    create_pending_application,
    create_granted_application,
    create_application_payload,
    create_jurisdiction_rule_payload,
    setup_counsel_firm,
    send_instruction,
    acknowledge_instruction,
    confirm_instruction,
    authorize_obligation,
    release_authorization,
    request_authorization,
    approve_authorization,
    list_obligations,
    make_outside_counsel_headers,
    EP_RULE_PAYLOAD,
)

ANY = TEST_USERS["any_headers"]
ADMIN = TEST_USERS["platform_admin_headers"]
CLERK = TEST_USERS["clerk_headers"]
REC = TEST_USERS["records_headers"]
REC2 = TEST_USERS["records2_headers"]
FIN = TEST_USERS["finance_headers"]


class TestInstructionExclusivityWindow:
    def _exclusivity_world(self):
        from test_helpers import set_clock
        set_clock("2026-08-02T00:00:00Z")
        create_us_rule()
        firm = setup_counsel_firm()
        client = create_client("InsCo")
        family = create_family(client["id"], budget_cap_cents=1000000)
        app = create_pending_application(family["id"], application_number="US-I")
        i1 = validate_success(api_client.create_instruction(
            app["id"],
            {"counsel_firm_id": firm["id"], "instruction_type": "FILING", "due_date": "2026-08-20"},
            CLERK), 201)
        set_clock("2026-08-20T00:00:00Z")
        return firm, app, i1

    def test_touching_closed_windows_conflict(self):
        """PRD §3.7: "because both intervals are closed, windows that merely
        touch at an endpoint already conflict and are rejected with
        `ERR_INSTRUCTION_EXCLUSIVE_CONFLICT`."

        Design: Difficulty/resource_temporal_overlap/instruction_exclusivity_closed_interval_touching_conflicts
        """
        firm, app, _ = self._exclusivity_world()
        # I1 occupies the closed window [2026-08-02, 2026-08-20]; the new
        # instruction's window starts 2026-08-20 (today), touching I1's due date.
        validate_error(api_client.create_instruction(
            app["id"],
            {"counsel_firm_id": firm["id"], "instruction_type": "FILING", "due_date": "2026-08-25"},
            CLERK), ApiErrorId.ERR_INSTRUCTION_EXCLUSIVE_CONFLICT)

    def test_different_instruction_type_partitions_the_channel(self):
        """PRD §3.7: "for the same application and instruction type,
        instructions enjoy an exclusivity window: the closed interval from the
        new instruction's creation date through its `due_date` — both endpoint
        dates included — must not share a single calendar date with the
        corresponding closed window of any existing instruction of that
        application and type that is still `DRAFT`, `SENT`, `ACKNOWLEDGED`, or
        `CONFIRMED`"

        Design: Difficulty/resource_temporal_overlap/instruction_exclusivity_closed_interval_touching_conflicts
        """
        firm, app, _ = self._exclusivity_world()
        data = validate_success(api_client.create_instruction(
            app["id"],
            {"counsel_firm_id": firm["id"], "instruction_type": "OA_RESPONSE", "due_date": "2026-08-25"},
            CLERK), 201)
        assert data["status"] == "DRAFT"


class TestCounselAccreditation:
    def test_firm_not_accredited_for_application_jurisdiction(self):
        """PRD §3.7: "The firm must be accredited for the application's
        jurisdiction (`ERR_COUNSEL_NOT_ACCREDITED`)."

        Design: Corner/validations/counsel_not_accredited_for_jurisdiction
        """
        create_us_rule()
        create_rule(EP_RULE_PAYLOAD)
        firm = setup_counsel_firm(accredited=("EP",), display_name="EP Only")
        client = create_client("AccCo")
        family = create_family(client["id"], budget_cap_cents=1000000)
        app_us = create_application(family["id"], application_number="US-AC")
        app_ep = create_application(family["id"], jurisdiction="EP", application_number="EP-AC")
        validate_error(api_client.create_instruction(
            app_us["id"],
            {"counsel_firm_id": firm["id"], "instruction_type": "FILING", "due_date": "2026-09-01"},
            CLERK), ApiErrorId.ERR_COUNSEL_NOT_ACCREDITED)
        ok = validate_success(api_client.create_instruction(
            app_ep["id"],
            {"counsel_firm_id": firm["id"], "instruction_type": "FILING", "due_date": "2026-09-01"},
            CLERK), 201)
        assert ok["status"] == "DRAFT"


class TestOutsideCounselScope:
    def test_wrong_firm_cannot_acknowledge(self):
        """PRD §3.7: "All three counsel actions are scope-checked — the acting
        `X-User-ID` must be the `id` of the counsel firm recorded on the
        instruction (`ERR_SCOPE_VIOLATION`)."

        Design: Corner/validations/scope_violation_outside_counsel_wrong_firm
        """
        create_us_rule()
        firm1 = setup_counsel_firm(display_name="F1")
        firm2 = setup_counsel_firm(display_name="F2")
        client = create_client("ScopeCo")
        family = create_family(client["id"], budget_cap_cents=1000000)
        app = create_pending_application(family["id"], application_number="US-SV")
        ins = send_instruction(app["id"], firm1)
        validate_error(
            api_client.acknowledge_instruction(ins["id"], make_outside_counsel_headers(firm2["id"])),
            ApiErrorId.ERR_SCOPE_VIOLATION)
        data = validate_success(
            api_client.acknowledge_instruction(ins["id"], make_outside_counsel_headers(firm1["id"])), 200)
        assert data["status"] == "ACKNOWLEDGED"


class TestCounselInstructionGateForPayment:
    def test_confirmed_annuity_payment_instruction_required(self):
        """PRD §3.5: "when the rule enables
        `requires_confirmed_instruction_for_payment`, an outside counsel
        instruction of type `ANNUITY_PAYMENT` on the application must be
        `CONFIRMED` or `COMPLETED` (`ERR_COUNSEL_INSTRUCTION_REQUIRED`)";
        PRD §2.5: "An update may change the response period, the extension
        policy, the surcharge policy, the entity-size multiplier, the four tier
        fees, the exchange rate, and the three gates; the `jurisdiction`
        code, the annuity schedule bounds (`annuity_start_year`,
        `term_years`), the tier-bound layout (`fee_tier_bounds`), and the two
        priority windows (`paris_window_months`, `pct_window_months`) are
        fixed at creation and cannot be patched."

        Design: Corner/validations/counsel_instruction_gate_for_payment_conditional_on_rule
        """
        rule = create_rule(EP_RULE_PAYLOAD)
        firm = setup_counsel_firm(accredited=("EP",), display_name="EP Firm")
        client = create_client("GatePay")
        contact = create_contact(client["id"])
        family = create_family(client["id"], budget_cap_cents=1000000)
        app = create_granted_application(
            family["id"], jurisdiction="EP", application_number="EP-GP")
        obligation = list_obligations(app["id"])[0]
        au = authorize_obligation(obligation["id"], 10255, contact["id"])
        release_authorization(au["id"])
        # Flip the gate on after grant (rule updates are permitted).
        validate_success(api_client.update_jurisdiction_rule(
            rule["id"], {"requires_confirmed_instruction_for_payment": True}, ADMIN), 200)
        validate_error(api_client.instruct_payment(obligation["id"], FIN),
                       ApiErrorId.ERR_COUNSEL_INSTRUCTION_REQUIRED)
        ins = send_instruction(app["id"], firm, instruction_type="ANNUITY_PAYMENT",
                               due_date="2026-09-01")
        acknowledge_instruction(ins["id"], firm["id"])
        confirm_instruction(ins["id"], firm["id"])
        data = validate_success(api_client.instruct_payment(obligation["id"], FIN), 200)
        assert data["status"] == "PAYMENT_INSTRUCTED"


class TestRecordationGateForGrant:
    def test_executed_assignment_is_not_enough_recorded_lifts_gate(self):
        """PRD §3.4: "When the application's jurisdiction rule enables
        `requires_recorded_assignment_for_grant`, grant is blocked until a
        `RECORDED` assignment record exists for the application
        (`ERR_ASSIGNMENT_RECORDATION_REQUIRED`)."

        Design: Corner/validations/recordation_gate_for_grant_conditional_on_rule
        """
        create_rule(create_jurisdiction_rule_payload(
            jurisdiction="KR", requires_recorded_assignment_for_grant=True))
        client = create_client("RecCo")
        inventor = validate_success(api_client.create_inventor(
            client["id"], {"full_name": "Inv 1", "email": "i1@x.com"}, REC), 201)
        family = create_family(client["id"], budget_cap_cents=1000000)
        app = create_pending_application(
            family["id"], jurisdiction="KR", application_number="KR-R")
        asg = validate_success(api_client.create_assignment(
            app["id"],
            {"assignee_name": "RecCo", "inventor_ids": [inventor["id"]],
             "execution_date": "2026-03-01"},
            REC), 201)
        validate_success(api_client.execute_assignment(asg["id"], REC), 200)
        # An EXECUTED-but-unrecorded assignment does not lift the gate.
        validate_error(api_client.grant_application(app["id"], {"grant_date": "2026-03-01"}, CLERK),
                       ApiErrorId.ERR_ASSIGNMENT_RECORDATION_REQUIRED)
        validate_success(api_client.record_assignment(
            asg["id"], {"register_recordation_number": "KR-2026-001"}, REC2), 200)
        data = validate_success(
            api_client.grant_application(app["id"], {"grant_date": "2026-03-01"}, CLERK), 200)
        assert data["status"] == "GRANTED"


class TestInventorClientMismatch:
    def test_inventor_from_other_client_rejected(self):
        """PRD §3.8: "every element of `inventor_ids` must resolve to an
        existing inventor and belong to the same client as the application,
        else `ERR_INVENTOR_CLIENT_MISMATCH` — and a suspended client rejects
        the creation with `ERR_CLIENT_SUSPENDED`."

        Design: Corner/validations/inventor_client_mismatch_on_assignment
        """
        create_us_rule()
        client_a = create_client("CliA")
        client_b = create_client("CliB")
        inv_a = validate_success(api_client.create_inventor(
            client_a["id"], {"full_name": "Inv A", "email": "ia@x.com"}, REC), 201)
        inv_b = validate_success(api_client.create_inventor(
            client_b["id"], {"full_name": "Inv B", "email": "ib@x.com"}, REC), 201)
        family_b = create_family(client_b["id"], budget_cap_cents=1000000)
        app_b = create_application(family_b["id"], application_number="US-IM")
        validate_error(api_client.create_assignment(
            app_b["id"],
            {"assignee_name": "CliB Inc", "inventor_ids": [inv_a["id"]],
             "execution_date": "2026-03-01"},
            REC), ApiErrorId.ERR_INVENTOR_CLIENT_MISMATCH)
        ok = validate_success(api_client.create_assignment(
            app_b["id"],
            {"assignee_name": "CliB Inc", "inventor_ids": [inv_b["id"]],
             "execution_date": "2026-03-01"},
            REC), 201)
        assert ok["status"] == "DRAFT"


class TestAssignmentSegregationOfDuties:
    def _executed_assignment(self):
        create_us_rule()
        client = create_client("SoDCo2")
        inventor = validate_success(api_client.create_inventor(
            client["id"], {"full_name": "Inv 1", "email": "i1@x.com"}, REC), 201)
        family = create_family(client["id"], budget_cap_cents=1000000)
        app = create_application(family["id"], application_number="US-SA")
        asg = validate_success(api_client.create_assignment(
            app["id"],
            {"assignee_name": "SoDCo2", "inventor_ids": [inventor["id"]],
             "execution_date": "2026-03-01"},
            REC), 201)
        validate_success(api_client.execute_assignment(asg["id"], REC), 200)
        return asg

    def test_executor_cannot_record(self):
        """PRD §3.8: "the recording specialist's `X-User-ID` must differ from
        the recorded `executed_by_user_id` — the same user performing both
        steps is rejected with `ERR_SEGREGATION_OF_DUTIES`."

        Design: Corner/rbac/sod_assignment_executor_cannot_record
        """
        asg = self._executed_assignment()
        validate_error(api_client.record_assignment(
            asg["id"], {"register_recordation_number": "US-001"}, REC),
            ApiErrorId.ERR_SEGREGATION_OF_DUTIES)
        data = validate_success(api_client.record_assignment(
            asg["id"], {"register_recordation_number": "US-001"}, REC2), 200)
        assert data["status"] == "RECORDED"
        assert data["register_recordation_number"] == "US-001"


class TestAssignmentReexecutionLoop:
    def test_recordation_rejected_reexecute_record(self):
        """PRD §3.8: "an assignment sitting in `RECORDATION_REJECTED` may be
        re-executed — `RECORDATION_REJECTED → EXECUTED`, recording a fresh
        `executed_by_user_id` — and then recorded again, forming a re-execution
        loop."

        Design: Corner/rbac/assignment_recordation_rejection_reexecute_loop
        """
        create_us_rule()
        client = create_client("LoopAsg")
        inventor = validate_success(api_client.create_inventor(
            client["id"], {"full_name": "Inv 1", "email": "i1@x.com"}, REC), 201)
        family = create_family(client["id"], budget_cap_cents=1000000)
        app = create_application(family["id"], application_number="US-LA")
        asg = validate_success(api_client.create_assignment(
            app["id"],
            {"assignee_name": "LoopAsg", "inventor_ids": [inventor["id"]],
             "execution_date": "2026-03-01"},
            REC), 201)
        validate_success(api_client.execute_assignment(asg["id"], REC), 200)
        validate_success(api_client.record_assignment_rejection(asg["id"], REC), 200)
        # Re-execute as a different specialist so the original executor may record.
        rexec = validate_success(api_client.execute_assignment(asg["id"], REC2), 200)
        assert rexec["status"] == "EXECUTED"
        recorded = validate_success(api_client.record_assignment(
            asg["id"], {"register_recordation_number": "US-002"}, REC), 200)
        assert recorded["status"] == "RECORDED"
