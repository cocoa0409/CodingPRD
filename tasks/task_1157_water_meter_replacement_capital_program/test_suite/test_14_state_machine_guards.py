"""Corner coverage — state machines: initial states, terminal lockdowns,
invalid transitions, precondition gates (PRD 2.8, 3.2–3.8)."""
import pytest

from test_helpers import (
    ApiErrorId, TEST_USERS, api_client, assign_contractor, book_appointment,
    complete_appointment, create_contractor, create_installed_account,
    create_meter, create_notification_payload, create_program,
    create_program_payload, create_wave, create_work_order, fc,
    get_success_data, send_and_deliver_notification, setup_filed_complaint,
    setup_no_access_case, setup_program_wave_contractor,
    setup_work_order_completed_visit, setup_work_order_created,
    setup_work_order_qa_review, validate_error, validate_success,
)

PM = TEST_USERS["program_manager_headers"]
SCHED = TEST_USERS["scheduler_headers"]
CS = TEST_USERS["customer_service_headers"]


def test_work_order_initial_state(api):
    """PRD §3.3: "At creation the system captures the account's currently
    `INSTALLED` meter as the work order's `old_meter_id`, books a budget
    commitment equal to the program's `default_unit_allowance_cents` into
    `committed_amount_cents`, moves the account `ELIGIBLE` → `IN_PROGRAM`,
    recomputes the program budget, and leaves the work order in
    `lifecycle_status` `CREATED` with `hold_status` `CLEAR`,
    `no_access_strikes` at zero, and `contractor_id` and `new_meter_id` not
    yet set."

    Design: Corner/state_machines/work_order_initial_state
    """
    ctx = setup_work_order_created()
    wo = ctx["work_order"]
    assert wo["lifecycle_status"] == "CREATED"
    assert wo["hold_status"] == "CLEAR"
    assert wo["no_access_strikes"] == 0
    assert wo["committed_amount_cents"] == 20000
    assert wo["old_meter_id"] == ctx["old_meter"]["id"]
    assert wo["new_meter_id"] is None
    assert wo["contractor_id"] is None
    acct = get_success_data(api_client.get_account(ctx["account"]["id"], SCHED))
    assert acct["status"] == "IN_PROGRAM"


def test_cancelled_work_order_lockdown(api):
    """PRD §3.3: "Cancellation is terminal (`→ CANCELLED`)"
    PRD §2.8: "a resource sitting in a terminal state rejects every further
    transition with `ERR_INVALID_STATE`."

    Design: Corner/state_machines/cancelled_work_order_lockdown
    """
    prog = create_program()
    contr = create_contractor(prog["id"])
    wave = create_wave(prog["id"])
    acct, oldm = create_installed_account()
    wo = create_work_order(wave["id"], acct["id"])
    get_success_data(api_client.cancel_work_order(wo["id"], SCHED))
    wo = get_success_data(api_client.get_work_order(wo["id"], SCHED))
    # Current version used, so OCC is not the rejection cause.
    resp = api.assign_work_order(wo["id"], {
        "contractor_id": contr["id"],
        "expected_work_order_version": wo["version"]}, SCHED)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)
    after = get_success_data(api_client.get_work_order(wo["id"], SCHED))
    assert after["lifecycle_status"] == "CANCELLED"


def test_completed_appointment_rejects_no_access(api):
    """PRD §2.8: "A transition is legal only from its declared from-states"
    PRD §3.4: "the assigned `FieldContractor` reports no-access on a `BOOKED`
    or `CONFIRMED` appointment."

    Design: Corner/state_machines/completed_appointment_rejects_no_access
    """
    prog, wave, contr = setup_program_wave_contractor()
    ctx = setup_work_order_completed_visit(contr["id"])
    resp = api.no_access_appointment(ctx["appointment"]["id"], fc(contr["id"]))
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)
    appt = get_success_data(api_client.get_appointment(ctx["appointment"]["id"], SCHED))
    assert appt["status"] == "COMPLETED"
    wo = get_success_data(api_client.get_work_order(ctx["work_order"]["id"], SCHED))
    assert wo["no_access_strikes"] == 0


def test_notification_terminal_lockdown(api):
    """PRD §2.8: "A transition is legal only from its declared from-states; a
    resource sitting in a terminal state rejects every further transition with
    `ERR_INVALID_STATE`."
    PRD §3.4: "Delivery is later confirmed by the `Scheduler` with an
    `outcome` of `DELIVERED`, `FAILED`, or `RETURNED`; a `DELIVERED` outcome
    also records the supplied `delivered_at` instant."

    Design: Corner/state_machines/notification_terminal_lockdown
    """
    ctx = setup_work_order_created()
    notif = send_and_deliver_notification(ctx["work_order"]["id"])
    assert notif["status"] == "DELIVERED"
    resp = api.confirm_delivery(notif["id"], {"outcome": "FAILED"}, SCHED)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)
    after = get_success_data(api_client.get_notification(notif["id"], SCHED))
    assert after["status"] == "DELIVERED"


def test_wave_open_requires_active_program(api):
    """PRD §3.3: "Opening a wave (`DRAFT` → `OPEN`) requires the program to be
    `ACTIVE`, failing otherwise with `ERR_PROGRAM_NOT_ACTIVE`"

    Design: Corner/state_machines/wave_open_requires_active_program
    """
    prog = get_success_data(api_client.create_program(
        create_program_payload(budget_total_cents=1000000,
                               target_meter_count=100), PM))
    wave = create_wave(prog["id"], open_it=False)
    resp = api.open_wave(wave["id"], PM)
    validate_error(resp, ApiErrorId.ERR_PROGRAM_NOT_ACTIVE.value)
    after = get_success_data(api_client.get_wave(wave["id"], PM))
    assert after["status"] == "DRAFT"


def test_no_access_advance_requires_stage_delivery(api):
    """PRD §3.4: "Any advance without the current stage's delivered
    notification is refused with `ERR_ESCALATION_STEP_REQUIRED`."

    Design: Corner/state_machines/no_access_advance_requires_stage_delivery
    """
    prog, wave, contr = setup_program_wave_contractor(
        contractor_overrides={"crew_capacity_per_window": 3})
    ctx = setup_no_access_case(contr["id"])
    case = ctx["case"]
    # The auto-created stage-1 DOOR_HANGER is still SENT, not DELIVERED.
    resp = api.advance_no_access_case(case["id"], SCHED)
    validate_error(resp, ApiErrorId.ERR_ESCALATION_STEP_REQUIRED.value)
    after = get_success_data(api_client.get_no_access_case(case["id"], SCHED))
    assert after["stage"] == "STAGE_1_DOOR_HANGER"
    assert after["status"] == "OPEN"


def test_forced_entry_before_stage4_rejected(api):
    """PRD §3.4: "Resolution by the `Scheduler` closes the case into
    `RESOLVED` with a `resolution` of `ACCESS_GAINED`, `ACCOUNT_EXEMPTED`, or
    `FORCED_ENTRY` — the last permitted only from `STAGE_4_FIELD_VISIT`,
    earlier attempts failing with `ERR_FORCED_ENTRY_NOT_AUTHORIZED`."

    Design: Corner/state_machines/forced_entry_before_stage4_rejected
    """
    prog, wave, contr = setup_program_wave_contractor(
        contractor_overrides={"crew_capacity_per_window": 3})
    ctx = setup_no_access_case(contr["id"])
    case = ctx["case"]
    resp = api.resolve_no_access_case(case["id"], {"resolution": "FORCED_ENTRY"}, SCHED)
    validate_error(resp, ApiErrorId.ERR_FORCED_ENTRY_NOT_AUTHORIZED.value)
    after = get_success_data(api_client.get_no_access_case(case["id"], SCHED))
    assert after["status"] == "OPEN"
    # ACCESS_GAINED is not stage-gated: succeeds from STAGE_1.
    resp = api.resolve_no_access_case(case["id"], {"resolution": "ACCESS_GAINED"}, SCHED)
    data = validate_success(resp)
    assert data["status"] == "RESOLVED"
    assert data["resolution"] == "ACCESS_GAINED"


def test_complaint_hold_blocks_close(api):
    """PRD §3.8: "Filing also flips the work order's parallel hold dimension:
    while `hold_status` is `CLEAR`, a new `FILED` complaint moves it to
    `ON_HOLD`, and an `ON_HOLD` work order cannot be booked, swapped, or
    closed until the hold clears."
    PRD §3.7: "the work order's `hold_status` must be `CLEAR` (otherwise
    `ERR_INVALID_STATE`)"

    Design: Corner/state_machines/complaint_hold_blocks_close
    """
    prog, wave, contr = setup_program_wave_contractor()
    ctx = setup_work_order_qa_review(contr["id"])
    cmp = setup_filed_complaint(ctx, claimed_bill_cents=16800,
                                baseline_bill_cents=12000)
    wo = get_success_data(api_client.get_work_order(ctx["work_order"]["id"], SCHED))
    assert wo["lifecycle_status"] == "QA_REVIEW"
    assert wo["hold_status"] == "ON_HOLD"
    resp = api.close_work_order(ctx["work_order"]["id"], SCHED)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)
    get_success_data(api_client.withdraw_complaint(cmp["id"], CS))
    wo = get_success_data(api_client.get_work_order(ctx["work_order"]["id"], SCHED))
    assert wo["hold_status"] == "CLEAR"
    closed = validate_success(api.close_work_order(ctx["work_order"]["id"], SCHED))
    assert closed["lifecycle_status"] == "CLOSED"


def test_meter_dispose_requires_bench(api):
    """PRD §3.2: "disposal by the `Scheduler` moves a `BENCH_PASSED` meter to
    `DISPOSED` or a `BENCH_FAILED` meter to `RETURNED_TO_VENDOR`, both
    terminal."
    PRD §2.8: "A transition is legal only from its declared from-states"

    Design: Corner/state_machines/meter_dispose_requires_bench
    """
    meter = create_meter(serial_number="L-0010", size_code="S_1",
                         technology="LEGACY")
    assert meter["status"] == "IN_STOCK"
    resp = api.dispose_meter(meter["id"], SCHED)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)
    after = get_success_data(api_client.get_meter(meter["id"], SCHED))
    assert after["status"] == "IN_STOCK"
