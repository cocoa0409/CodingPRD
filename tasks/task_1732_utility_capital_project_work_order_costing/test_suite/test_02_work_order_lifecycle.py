"""Work order origination, submission loops, suspension, cancellation, and
list filtering (PRD §3.3, §3.5, §3.7)."""
from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    TEST_USERS,
    assert_work_order,
    create_estimate_payload,
    create_program,
    create_submitted_work_order,
    create_work_order,
    create_work_order_payload,
    get_estimate_for_order,
    get_program,
    get_success_data,
    get_work_order,
    make_headers,
    post_charge,
    setup_charging_world,
    submit,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["admin_headers"]
ENGINEER = TEST_USERS["engineer_headers"]
SUPERVISOR = TEST_USERS["supervisor_headers"]
CONTROLLER = TEST_USERS["controller_headers"]
CLERK = TEST_USERS["clerk_headers"]
AUDITOR = TEST_USERS["auditor_headers"]


class TestWorkOrderCreation:
    def test_work_order_creation_seeds_estimate_and_defaults(self, api):
        """PRD §3.3: "Creation does two things at once: the work order itself starts at `DRAFT`, and the system seeds estimate number one from it — an Estimate carrying `estimate_seq` 1, `status` `PROPOSED`, an `estimated_cost_cents` copied from the `initial_estimated_cost_cents`, and the creator recorded as `submitted_by_user_id`. The order's own `estimate_seq` tracks the most recently created estimate and therefore begins at 1. Its remaining fields start empty or zeroed: `approved_estimate_cents` null until the first approval, `actual_direct_cents`, `afudc_total_cents`, and `cwip_cents` at zero, `variance_posture` at `WITHIN_TOLERANCE`, `ciac_applied_cents` at zero, and `in_service_date`, `in_service_period_id`, `gross_cwip_cents`, `capitalizable_total_cents`, `cancel_writeoff_disposition`, `authorized_by_user_id`, `completed_by_user_id`, and `closed_by_user_id` all unset."
        PRD §2.2: "The `api_request_id` is a server-generated unique identifier for the request that starts with `req_`."

        Design: Corner/entities/work_order_creation_seeds_estimate_and_defaults
        """
        program = create_program(code="CAP-SEED", authorized_amount_cents=5_000_000)
        resp = api.create_work_order(
            create_work_order_payload(program_id=program["id"], title="Seed order",
                                      initial_estimated_cost_cents=250_000),
            ENGINEER)
        wo = validate_success(resp, 201)
        assert_work_order(wo)
        assert wo["status"] == "DRAFT"
        assert wo["variance_posture"] == "WITHIN_TOLERANCE"
        assert wo["actual_direct_cents"] == 0
        assert wo["afudc_total_cents"] == 0
        assert wo["cwip_cents"] == 0
        assert wo["ciac_applied_cents"] == 0
        assert wo["estimate_seq"] == 1
        assert wo["approved_estimate_cents"] is None
        assert wo["created_by_user_id"] == "eng-1"

        request_id = resp.json()["meta"]["api_request_id"]
        assert isinstance(request_id, str) and request_id.startswith("req_")

        estimates, meta = validate_paginated(
            api.list_estimates(AUDITOR, params={"work_order_id": wo["id"]}))
        assert meta["total_count"] == 1
        assert len(estimates) == 1
        seed = estimates[0]
        assert seed["status"] == "PROPOSED"
        assert seed["estimate_seq"] == 1
        assert seed["estimated_cost_cents"] == 250_000
        assert seed["submitted_by_user_id"] == "eng-1"

    def test_work_order_missing_required_field_returns_invalid_request(self, api):
        """PRD §2.8: "4. Request shape — a required field is missing, an enum field takes an undeclared member, a numeric range is violated (amounts greater than zero, `quantity` at least one, `amortization_months` at least one, rate bounds, a debt weight between 0 and 100 inclusive), a date fails to parse, an `end_date` precedes its `start_date`, or a program `code` or catalog `asset_class` duplicates an existing one — `ERR_VALIDATION`."
        PRD §3.4: "A `ProjectEngineer` records a new estimate against an order in `DRAFT`, `SUBMITTED`, `RETURNED`, `AUTHORIZED`, `IN_PROGRESS`, or `SUSPENDED` by supplying the `work_order_id`, an `estimated_cost_cents` greater than zero, the mandatory `expected_work_order_version` implementing the optimistic-concurrency guard of §2.7, and an optional free-text `notes` justification."

        Design: Corner/entities/work_order_missing_required_field_returns_invalid_request
        """
        program = create_program(code="CAP-REQ", authorized_amount_cents=5_000_000)
        # Missing required field `title`.
        resp = api.create_work_order(
            {"program_id": program["id"], "order_type": "CAPITAL",
             "initial_estimated_cost_cents": 250_000}, ENGINEER)
        validate_error(resp, ApiErrorId.ERR_VALIDATION, 400)
        # initial_estimated_cost_cents seeds the estimate, whose cost must be
        # greater than zero.
        resp2 = api.create_work_order(
            create_work_order_payload(program_id=program["id"],
                                      title="Bad amount",
                                      initial_estimated_cost_cents=0), ENGINEER)
        validate_error(resp2, ApiErrorId.ERR_VALIDATION, 400)

    def test_work_order_invalid_enum_returns_invalid_request(self, api):
        """PRD §2.8: "4. Request shape — a required field is missing, an enum field takes an undeclared member, a numeric range is violated (amounts greater than zero, `quantity` at least one, `amortization_months` at least one, rate bounds, a debt weight between 0 and 100 inclusive), a date fails to parse, an `end_date` precedes its `start_date`, or a program `code` or catalog `asset_class` duplicates an existing one — `ERR_VALIDATION`."

        Design: Corner/entities/work_order_invalid_enum_returns_invalid_request
        """
        program = create_program(code="CAP-ENUM", authorized_amount_cents=5_000_000)
        resp = api.create_work_order(
            create_work_order_payload(program_id=program["id"],
                                      order_type="CAPITALISH",
                                      title="Bad enum",
                                      initial_estimated_cost_cents=250_000),
            ENGINEER)
        validate_error(resp, ApiErrorId.ERR_VALIDATION, 400)

    def test_get_missing_work_order_returns_not_found(self, api):
        """PRD §2.9: "The first identifier that does not correspond to an existing resource rejects the request with `ERR_NOT_FOUND` (HTTP 404), and no later reference is examined."

        Design: Corner/entities/get_missing_work_order_returns_not_found
        """
        resp = api.get_work_order(NON_EXISTENT_UUID, AUDITOR)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND, 404)


class TestProgramStateGate:
    def test_work_order_create_rejected_on_closed_program(self, api):
        """PRD §3.1: "Once the program is `CLOSED`, attempting to create a further work order against it fails with `ERR_PROGRAM_CLOSED`."

        Design: Difficulty/cross_entity_state_dependency/work_order_create_blocked_on_closed_program
        """
        shut = create_program(code="CAP-SHUT", authorized_amount_cents=5_000_000)
        closed = validate_success(api.close_capital_program(shut["id"], CONTROLLER))
        assert closed["status"] == "CLOSED"

        resp = api.create_work_order(
            create_work_order_payload(program_id=shut["id"], title="Late order",
                                      initial_estimated_cost_cents=100_000),
            ENGINEER)
        validate_error(resp, ApiErrorId.ERR_PROGRAM_CLOSED, 409)

    def test_work_order_create_allowed_on_open_program(self, api):
        """PRD §3.3: "A `ProjectEngineer` originates a **Work Order** under an `OPEN` program by supplying the `program_id`, an `order_type` of `CAPITAL` or `EXPENSE`, a `title`, and the `initial_estimated_cost_cents`; targeting a `CLOSED` program is rejected with `ERR_PROGRAM_CLOSED`."
        PRD §3.1: "A new program starts `OPEN` with all four derived counters — `committed_amount_cents`, `capitalized_actual_cents`, `expense_writeoff_cents`, and `ciac_contra_balance_cents` — at zero, and its `available_amount_cents` is defined at every moment as the authorized amount minus the committed amount."

        Design: Difficulty/cross_entity_state_dependency/work_order_create_blocked_on_closed_program
        """
        program = create_program(code="CAP-OPEN", authorized_amount_cents=5_000_000)
        assert program["status"] == "OPEN"
        wo = validate_success(api.create_work_order(
            create_work_order_payload(program_id=program["id"], title="Good order",
                                      initial_estimated_cost_cents=100_000),
            ENGINEER), 201)
        assert wo["status"] == "DRAFT"
        assert wo["program_id"] == program["id"]


class TestDraftStateTransitions:
    def test_invalid_transitions_from_draft_state(self, api):
        """PRD §3.3: "Authorization (`SUBMITTED` → `AUTHORIZED`) is the first act that commits program money, and it is guarded by four checks evaluated in the §2.8 order."
        PRD §3.3: "Once authorized, field execution belongs to the `WorkOrderSupervisor`: starting work moves `AUTHORIZED` → `IN_PROGRESS`, suspending moves `IN_PROGRESS` → `SUSPENDED`, and resuming returns `SUSPENDED` → `IN_PROGRESS`, each transition incrementing the version by one."
        PRD §3.3: "A `WorkOrderSupervisor` who is not satisfied returns a `SUBMITTED` order to the engineer — `SUBMITTED` → `RETURNED` — supplying a `reason`, again incrementing the version."
        PRD §3.4: "Deciding an estimate — approval or rejection — is permitted only while the work order stands at `SUBMITTED`, `AUTHORIZED`, `IN_PROGRESS`, or `SUSPENDED`; any other order state is rejected with `ERR_INVALID_STATE`, and the estimate itself must still be `PROPOSED`."

        Design: Corner/state_machines/invalid_transitions_from_draft_state
        """
        program = create_program(code="CAP-INV")
        wo = create_work_order(program["id"], title="Draft order",
                               initial_estimated_cost_cents=100_000)
        assert wo["status"] == "DRAFT"
        est = get_estimate_for_order(wo["id"])

        resp_start = api.start_work_order(wo["id"], SUPERVISOR)
        validate_error(resp_start, ApiErrorId.ERR_INVALID_STATE, 409)

        resp_auth = api.authorize_work_order(wo["id"], SUPERVISOR)
        validate_error(resp_auth, ApiErrorId.ERR_INVALID_STATE, 409)

        resp_ret = api.return_work_order(wo["id"], "not submitted", SUPERVISOR)
        validate_error(resp_ret, ApiErrorId.ERR_INVALID_STATE, 409)

        fresh_version = get_work_order(wo["id"])["version"]
        resp_appr = api.approve_estimate(est["id"], fresh_version, SUPERVISOR)
        validate_error(resp_appr, ApiErrorId.ERR_INVALID_STATE, 409)


class TestCancelledTerminalLockdown:
    def test_cancelled_work_order_terminal_lockdown(self, api):
        """PRD §3.7: "Cancellation is the supervisor's exit ramp, available from `DRAFT`, `SUBMITTED`, `RETURNED`, `AUTHORIZED`, `IN_PROGRESS`, and `SUSPENDED`, with consequences that scale with how committed the order was."
        PRD §3.3: "Submission is the engineer's handshake to supervision: submitting moves `DRAFT` → `SUBMITTED`, and a returned order resubmits along `RETURNED` → `SUBMITTED`, a loop that may repeat as often as review requires; each submission increments the work order's `version` by exactly one."
        PRD §3.5: "The order must stand at `AUTHORIZED` or `IN_PROGRESS`: posting against a `SUSPENDED` order is rejected with `ERR_WORK_ORDER_SUSPENDED`, and any other state — including `COMPLETED`, whose charges are frozen — is `ERR_INVALID_STATE`."

        Design: Corner/state_machines/cancelled_work_order_terminal_lockdown
        """
        world = setup_charging_world(estimate_cents=100_000)
        program = world["program"]
        wo, _est = create_submitted_work_order(program["id"], title="Doomed order",
                                               initial_estimated_cost_cents=100_000)
        cancelled = get_success_data(api.cancel_work_order(wo["id"], SUPERVISOR))
        assert cancelled["status"] == "CANCELLED"

        resp_cancel = api.cancel_work_order(wo["id"], SUPERVISOR)
        validate_error(resp_cancel, ApiErrorId.ERR_INVALID_STATE, 409)

        resp_submit = api.submit_work_order(wo["id"], ENGINEER)
        validate_error(resp_submit, ApiErrorId.ERR_INVALID_STATE, 409)

        resp_charge = api.create_cost_charge(
            {"work_order_id": wo["id"], "cost_type": "MATERIAL",
             "base_amount_cents": 1_000, "charge_date": "2026-08-10"}, CLERK)
        validate_error(resp_charge, ApiErrorId.ERR_INVALID_STATE, 409)


class TestListFiltering:
    def test_list_work_orders_filter_by_status(self, api):
        """PRD §3.3: "Work orders may be listed filtered by `program_id`, `status`, or `order_type`."

        Design: Corner/endpoints/list_filtering_by_status
        """
        program = create_program(code="CAP-FILT")
        create_work_order(program["id"], title="Keep",
                               initial_estimated_cost_cents=100_000)
        w2 = create_work_order(program["id"], title="Drop",
                               initial_estimated_cost_cents=100_000)
        get_success_data(api.cancel_work_order(w2["id"], SUPERVISOR))

        data, meta = validate_paginated(api.list_work_orders(
            AUDITOR, params={"program_id": program["id"], "status": "CANCELLED"}))
        assert meta["total_count"] == 1
        assert len(data) == 1
        assert data[0]["id"] == w2["id"]
        assert data[0]["status"] == "CANCELLED"


class TestReturnResubmitCycle:
    def test_return_blocks_authorize_until_resubmission(self, api):
        """PRD §3.3: "Submission is the engineer's handshake to supervision: submitting moves `DRAFT` → `SUBMITTED`, and a returned order resubmits along `RETURNED` → `SUBMITTED`, a loop that may repeat as often as review requires; each submission increments the work order's `version` by exactly one. A `WorkOrderSupervisor` who is not satisfied returns a `SUBMITTED` order to the engineer — `SUBMITTED` → `RETURNED` — supplying a `reason`, again incrementing the version."
        PRD §3.3: "Authorization (`SUBMITTED` → `AUTHORIZED`) is the first act that commits program money, and it is guarded by four checks evaluated in the §2.8 order."

        Design: Difficulty/non_linear_state_machine/work_order_return_resubmit_and_suspend_resume_cycles
        """
        program = create_program(code="CAP-CYC", authorized_amount_cents=50_000_000)
        wo, est = create_submitted_work_order(
            program["id"], title="Pole replacement",
            initial_estimated_cost_cents=400_000)
        version_after_submit = wo["version"]

        returned = validate_success(api.return_work_order(wo["id"], "scope unclear",
                                                          SUPERVISOR))
        assert returned["status"] == "RETURNED"
        assert returned["version"] == version_after_submit + 1, (
            "return increments the version by exactly one")

        # Authorize is illegal from RETURNED.
        resp = api.authorize_work_order(wo["id"], SUPERVISOR)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE, 409)

        # Resubmission loop: RETURNED -> SUBMITTED, then authorize succeeds.
        resubmitted = validate_success(api.submit_work_order(wo["id"], ENGINEER))
        assert resubmitted["status"] == "SUBMITTED"
        assert resubmitted["version"] == returned["version"] + 1

        approved = get_success_data(api.approve_estimate(
            est["id"], resubmitted["version"], SUPERVISOR))
        assert approved["status"] == "APPROVED"

        authorized = validate_success(api.authorize_work_order(wo["id"], SUPERVISOR))
        assert authorized["status"] == "AUTHORIZED"

    def test_suspend_resume_loop_keeps_budget_committed(self, api):
        """PRD §3.3: "Once authorized, field execution belongs to the `WorkOrderSupervisor`: starting work moves `AUTHORIZED` → `IN_PROGRESS`, suspending moves `IN_PROGRESS` → `SUSPENDED`, and resuming returns `SUSPENDED` → `IN_PROGRESS`, each transition incrementing the version by one."
        PRD §3.3: "Throughout these states the program's budget accounting obeys a conservation law: `committed_amount_cents` is the sum of `approved_estimate_cents` over the program's work orders in `AUTHORIZED`, `IN_PROGRESS`, `SUSPENDED`, or `COMPLETED` — a completed order stays committed until its closeout — and `available_amount_cents` is always the authorized amount minus the committed amount."

        Design: Difficulty/non_linear_state_machine/work_order_return_resubmit_and_suspend_resume_cycles
        """
        program = create_program(code="CAP-CYC2", authorized_amount_cents=50_000_000)
        wo, est = create_submitted_work_order(
            program["id"], title="Suspendable", initial_estimated_cost_cents=400_000)
        get_success_data(api.approve_estimate(est["id"], wo["version"], SUPERVISOR))
        authorized = get_success_data(api.authorize_work_order(wo["id"], SUPERVISOR))
        assert authorized["status"] == "AUTHORIZED"

        started = validate_success(api.start_work_order(wo["id"], SUPERVISOR))
        assert started["status"] == "IN_PROGRESS"
        suspended = validate_success(api.suspend_work_order(wo["id"], SUPERVISOR))
        assert suspended["status"] == "SUSPENDED"
        assert suspended["version"] == started["version"] + 1
        resumed = validate_success(api.resume_work_order(wo["id"], SUPERVISOR))
        assert resumed["status"] == "IN_PROGRESS"
        assert resumed["version"] == suspended["version"] + 1

        program_view = get_program(program["id"])
        assert program_view["committed_amount_cents"] == 400_000, (
            "budget stays committed through the suspend/resume loop")


class TestSuspendedCharges:
    def test_suspended_work_order_rejects_charges(self, api):
        """PRD §3.3: "While an order stands `SUSPENDED`, any attempt to post a charge against it is rejected with `ERR_WORK_ORDER_SUSPENDED`."

        Design: Corner/state_machines/suspended_work_order_rejects_charges
        """
        world = setup_charging_world(estimate_cents=9_000_000)
        wo = world["work_order"]

        charge = post_charge(wo["id"], base_amount_cents=4_000,
                             charge_date="2026-08-05")
        assert charge["total_cents"] == 4_000

        get_success_data(api.suspend_work_order(wo["id"], SUPERVISOR))
        resp = api.create_cost_charge(
            {"work_order_id": wo["id"], "cost_type": "MATERIAL",
             "base_amount_cents": 4_000, "charge_date": "2026-08-06"}, CLERK)
        validate_error(resp, ApiErrorId.ERR_WORK_ORDER_SUSPENDED, 409)

        get_success_data(api.resume_work_order(wo["id"], SUPERVISOR))
        charge2 = post_charge(wo["id"], base_amount_cents=4_000,
                              charge_date="2026-08-07")
        assert charge2["total_cents"] == 4_000
