"""Bench execution: parts consumption, OCC, QA gate, escalation cascade, bays."""
from test_helpers import api_client as api
from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    TEST_USERS,
    consume_part,
    consume_part_ok,
    create_bay,
    create_failure_code,
    create_model,
    create_customer,
    create_part,
    create_unit,
    create_draft_rma,
    authorize_rma,
    receive_rma,
    triage_rma,
    diagnose_rma,
    get_part,
    get_rma,
    get_repair_line,
    make_depot_technician_headers,
    planned_part_line,
    qa_release,
    repair_complete,
    set_clock,
    setup_in_repair_rma,
    setup_qa_hold_rma,
    setup_received_rma,
    setup_triaged_rma,
    ship_rma,
    validate_error,
    validate_success,
)

TECH2 = make_depot_technician_headers("tech-2")


def test_parts_consumption_insufficient_stock_rejected(api):
    """PRD §3.6: "The part's `stock_on_hand` must cover the quantity, otherwise
    the request fails with `ERR_INSUFFICIENT_STOCK`."

    Design: Corner/validations/parts_consumption_insufficient_stock_rejected
    """
    ctx = setup_in_repair_rma(labor_minutes_est=10, planned_qty=2,
                              part_overrides={"initial_stock": 1})
    rma, part, fc = ctx["rma"], ctx["part"], ctx["fc"]
    res = consume_part(rma["id"], part["id"], 2, fc["id"], rma["version"])
    validate_error(res, ApiErrorId.ERR_INSUFFICIENT_STOCK)
    assert res.status_code == 409
    assert get_part(part["id"])["stock_on_hand"] == 1, (
        "a rejected consumption must not decrement stock")
    assert get_rma(rma["id"])["version"] == rma["version"], (
        "a rejected consumption must not bump the RMA version")


def test_occ_parts_consumption_stale_version(api):
    """PRD §2.7: "Three write operations are guarded by optimistic concurrency
    control against the parent RMA: editing a draft RMA, creating a revised
    quote for an RMA, and recording a parts-consumption line on an RMA."
    PRD §2.7: "If the supplied value does not match the RMA's current `version`
    — because another write has advanced the version since the client last read
    it — the request is rejected with `ERR_STALE_RMA_VERSION` (HTTP 412). Each
    of these three writes, on success, increments the RMA's `version` by one."

    Design: Corner/complexity_layers/occ_parts_consumption_stale_version
    """
    ctx = setup_in_repair_rma(labor_minutes_est=10, planned_qty=2)
    rma, part, fc = ctx["rma"], ctx["part"], ctx["fc"]
    v0 = rma["version"]

    line = consume_part_ok(rma["id"], part["id"], 1, fc["id"], v0)
    assert line["status"] == "CONSUMED"
    assert get_rma(rma["id"])["version"] == v0 + 1

    replay = consume_part(rma["id"], part["id"], 1, fc["id"], v0)
    validate_error(replay, ApiErrorId.ERR_STALE_RMA_VERSION)
    assert replay.status_code == 412
    assert get_part(part["id"])["stock_on_hand"] == 9, (
        f"the stale replay must not double-decrement stock; got "
        f"{get_part(part['id'])['stock_on_hand']}")


def test_repair_complete_without_consumed_line_rejected(api):
    """PRD §3.6: "Completing the bench work requires proof of work: the
    technician's repair-complete call is rejected with `ERR_NO_WORK_RECORDED`
    unless at least one `CONSUMED` repair line exists for the RMA."

    Design: Corner/validations/repair_complete_without_consumed_line_rejected
    """
    ctx = setup_in_repair_rma(labor_minutes_est=10, planned_qty=0)
    res = api.repair_complete(ctx["rma"]["id"], TEST_USERS["depot_technician_headers"])
    validate_error(res, ApiErrorId.ERR_NO_WORK_RECORDED)
    assert res.status_code == 409
    assert get_rma(ctx["rma"]["id"])["status"] == "IN_REPAIR"


def test_qa_fail_rework_loop_increments_counter(api):
    """PRD §3.6: "On `FAIL` the RMA loops back from `QA_HOLD` to `IN_REPAIR` and
    its `rework_count` increments by one."

    Design: Corner/state_machines/qa_fail_rework_loop_increments_counter
    """
    ctx = setup_qa_hold_rma()
    failed = qa_release(ctx["rma"]["id"], "FAIL", tech_headers=TECH2)
    assert failed["status"] == "IN_REPAIR", (
        f"QA FAIL must loop back to IN_REPAIR, got {failed['status']}")
    assert failed["rework_count"] == 1, (
        f"rework_count must increment to 1, got {failed['rework_count']}")


def test_qa_release_by_repair_technician_rejected(api):
    """PRD §2.9: "A technician releasing a repair from the quality gate must not
    be the technician recorded in `repair_completed_by`."
    PRD §3.6: "On `PASS`, the gate additionally requires
    `engineering_review_pending` to be false — an RMA under engineering review
    holds at the gate with `ERR_ENGINEERING_REVIEW_PENDING` until engineering
    resolves the escalation — and success moves the RMA from `QA_HOLD` to
    `READY_TO_SHIP`, releasing its bay booking for future overlap checks while
    keeping the window for audit."

    Design: Corner/validations/qa_release_by_repair_technician_rejected
    """
    ctx = setup_qa_hold_rma()  # repair completed by tech-1
    self_release = api.qa_release(ctx["rma"]["id"], {"outcome": "PASS"},
                                  make_depot_technician_headers("tech-1"))
    validate_error(self_release, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)
    assert self_release.status_code == 403

    released = qa_release(ctx["rma"]["id"], "PASS", tech_headers=TECH2)
    assert released["status"] == "READY_TO_SHIP", (
        f"a different technician's PASS must release to READY_TO_SHIP, got "
        f"{released['status']}")


def test_consume_then_reverse_restores_stock(api):
    """PRD §3.6: "the part's `stock_on_hand` decreases by the quantity, the
    RMA's `version` increments by one"
    PRD §3.6: "reversal moves the line to `REVERSED` and returns its quantity to
    the part's `stock_on_hand` as a compensating restock."

    Design: Difficulty/compensating_invariant/part_stock_consume_reverse_invariant
    """
    ctx = setup_in_repair_rma(labor_minutes_est=10, planned_qty=3)
    rma, part, fc = ctx["rma"], ctx["part"], ctx["fc"]

    line = consume_part_ok(rma["id"], part["id"], 3, fc["id"], rma["version"])
    assert get_part(part["id"])["stock_on_hand"] == 7, (
        f"consume(3) from 10 must leave 7, got "
        f"{get_part(part['id'])['stock_on_hand']}")

    reversed_line = validate_success(
        api.reverse_repair_line(line["id"], TEST_USERS["depot_technician_headers"]), 200)
    assert reversed_line["status"] == "REVERSED"
    assert get_part(part["id"])["stock_on_hand"] == 10, (
        f"reverse must restore stock exactly to 10, got "
        f"{get_part(part['id'])['stock_on_hand']}")


def test_reversed_line_preserves_cost_snapshot(api):
    """PRD §3.6: "Success creates a `RepairLine` in `CONSUMED` status with the
    part's `unit_cost_cents` snapshotted onto the line, a `line_total_cents` of
    quantity multiplied by that snapshot unit cost (raw cost accounting, no
    handling uplift), and the recording technician's `X-User-ID` in
    `consumed_by`"

    Design: Difficulty/compensating_invariant/part_stock_consume_reverse_invariant
    """
    ctx = setup_in_repair_rma(labor_minutes_est=10, planned_qty=3)
    rma, part, fc = ctx["rma"], ctx["part"], ctx["fc"]
    line = consume_part_ok(rma["id"], part["id"], 3, fc["id"], rma["version"])
    assert line["unit_cost_cents"] == 5000
    assert line["line_total_cents"] == 15000, (
        f"line_total must be 3 * 5000 = 15000, got {line['line_total_cents']}")
    assert line["consumed_by"] == "tech-1"

    validate_success(
        api.reverse_repair_line(line["id"], TEST_USERS["depot_technician_headers"]), 200)
    after = get_repair_line(line["id"])
    assert after["status"] == "REVERSED"
    assert after["line_total_cents"] == 15000, (
        "the snapshot must be preserved for audit after reversal")


def test_repair_line_reverse_terminal_lockdown(api):
    """PRD §3.6: "An erroneous consumption can be reversed: the line must still
    be `CONSUMED` (reversing an already-`REVERSED` line fails with
    `ERR_INVALID_LINE_STATE`) and its RMA must be in `IN_REPAIR` or
    `AWAITING_PARTS` (else `ERR_INVALID_RMA_STATE`); reversal moves the line to
    `REVERSED` and returns its quantity to the part's `stock_on_hand` as a
    compensating restock."

    Design: Corner/state_machines/repair_line_reverse_terminal_lockdown
    """
    ctx = setup_in_repair_rma(labor_minutes_est=10, planned_qty=1)
    rma, part, fc = ctx["rma"], ctx["part"], ctx["fc"]
    line = consume_part_ok(rma["id"], part["id"], 1, fc["id"], rma["version"])
    validate_success(
        api.reverse_repair_line(line["id"], TEST_USERS["depot_technician_headers"]), 200)

    second = api.reverse_repair_line(line["id"], TEST_USERS["depot_technician_headers"])
    validate_error(second, ApiErrorId.ERR_INVALID_LINE_STATE)
    assert second.status_code == 409
    assert get_part(part["id"])["stock_on_hand"] == 10, (
        "the rejected second reversal must not restock again")


def _setup_closed_prior_rma_with_code():
    """Prior RMA1 (unit SN-1, code F-CAP-02) driven to CLOSED at 2026-06-01;
    current RMA2 triaged with a different code F-PWR-01 and diagnosed at
    2026-08-01. Threshold is 3; RMA1's closure inside 90 days weighs 2."""
    set_clock("2026-06-01T00:00:00Z")
    model = create_model(recurring_failure_threshold=3)
    customer = create_customer()
    unit = create_unit(model["id"], customer["id"], serial_number="SN-ESC-1")
    fc1 = create_failure_code(code="F-PWR-01", description="No power",
                              severity="HIGH")
    fc2 = create_failure_code(code="F-CAP-02", description="Capacitor",
                              severity="MEDIUM")
    part = create_part()

    rma1 = create_draft_rma(customer["id"], unit["id"], reported_issue="first failure")
    authorize_rma(rma1["id"])
    receive_rma(rma1["id"], unit["serial_number"])
    triage_rma(rma1["id"], fc2["id"])
    rma1 = diagnose_rma(rma1["id"], labor_minutes_est=10,
                        planned_parts=[planned_part_line(part["id"], 1)])
    consume_part_ok(rma1["id"], part["id"], 1, fc2["id"], rma1["version"])
    repair_complete(rma1["id"])
    qa_release(rma1["id"], "PASS", tech_headers=TECH2)
    ship_rma(rma1["id"], tech_headers=TECH2)
    validate_success(api.close_rma(rma1["id"], TEST_USERS["intake_agent_headers"]), 200)

    set_clock("2026-08-01T00:00:00Z")
    rma2 = create_draft_rma(customer["id"], unit["id"], reported_issue="second failure")
    authorize_rma(rma2["id"])
    receive_rma(rma2["id"], unit["serial_number"])
    triage_rma(rma2["id"], fc1["id"])
    rma2 = diagnose_rma(rma2["id"], labor_minutes_est=10,
                        planned_parts=[planned_part_line(part["id"], 1)])
    return {"model": model, "customer": customer, "unit": unit, "fc1": fc1,
            "fc2": fc2, "part": part, "rma2": rma2}


def test_parts_consumption_crosses_threshold_opens_escalation(api):
    """PRD §3.6: "the recurring-failure score of §3.3 is recomputed for the
    line's failure code — a threshold crossing opens the escalation and raises
    `engineering_review_pending` exactly as at triage."
    PRD §3.3: "When the score reaches or exceeds the model's
    `recurring_failure_threshold`, and no escalation already exists for the
    (model, failure code) pair in `OPEN`, `ACKNOWLEDGED`, `CONTAINMENT_ACTIVE`,
    or `MONITORING`, the system opens an `EngineeringEscalation` in `OPEN` with
    `trigger_source` `AUTO_RECURRING`, sets `engineering_review_pending` to true
    on the evaluating RMA, and emits an `ESCALATION_OPENED` notification on it."

    Design: Difficulty/transitive_cascade/parts_consumption_escalation_cascade
    """
    ctx = _setup_closed_prior_rma_with_code()
    rma2 = ctx["rma2"]
    # prior CLOSED at 2026-06-01 (inside 90 days -> 2) + current line evidence
    # (+2) = 4 >= threshold 3
    consume_part_ok(rma2["id"], ctx["part"]["id"], 1, ctx["fc2"]["id"],
                    rma2["version"])

    res = api.list_engineering_escalations(
        TEST_USERS["engineering_lead_headers"], params={"rma_id": rma2["id"]})
    escalations = validate_success(res, 200)
    assert len(escalations) == 1, (
        f"exactly one escalation must be opened, got {len(escalations)}")
    esc = escalations[0]
    assert esc["status"] == "OPEN"
    assert esc["trigger_source"] == "AUTO_RECURRING"
    assert esc["failure_code_id"] == ctx["fc2"]["id"]
    assert esc["model_id"] == ctx["model"]["id"]
    assert get_rma(rma2["id"])["engineering_review_pending"] is True, (
        "the cascade must set engineering_review_pending on the evaluating RMA")


def test_engineering_review_pending_blocks_qa_release(api):
    """PRD §3.6: "On `PASS`, the gate additionally requires
    `engineering_review_pending` to be false — an RMA under engineering review
    holds at the gate with `ERR_ENGINEERING_REVIEW_PENDING` until engineering
    resolves the escalation — and success moves the RMA from `QA_HOLD` to
    `READY_TO_SHIP`, releasing its bay booking for future overlap checks while
    keeping the window for audit."

    Design: Difficulty/transitive_cascade/parts_consumption_escalation_cascade
    """
    ctx = _setup_closed_prior_rma_with_code()
    rma2 = ctx["rma2"]
    consume_part_ok(rma2["id"], ctx["part"]["id"], 1, ctx["fc2"]["id"],
                    rma2["version"])
    repair_complete(rma2["id"])

    blocked = api.qa_release(rma2["id"], {"outcome": "PASS"}, TECH2)
    validate_error(blocked, ApiErrorId.ERR_ENGINEERING_REVIEW_PENDING)
    assert blocked.status_code == 409
    assert get_rma(rma2["id"])["status"] == "QA_HOLD", (
        "the blocked gate must leave the RMA in QA_HOLD")


def test_restock_resumes_awaiting_parts_rma(api):
    """PRD §3.6: "Restock is the compensating trigger: a `DepotManager` adding a
    `quantity` of a part increases its `stock_on_hand` by that quantity and
    bumps the part's `version` by one, and every RMA sitting in `AWAITING_PARTS`
    whose `planned_parts` snapshot includes the restocked part automatically
    resumes to `IN_REPAIR`, processed in `created_at` ascending order with no
    identifier tie-break."

    Design: Corner/calculations/restock_resumes_awaiting_parts_rma
    """
    ctx = setup_in_repair_rma(labor_minutes_est=10, planned_qty=1,
                              part_overrides={"initial_stock": 0})
    rma, part = ctx["rma"], ctx["part"]
    waiting = validate_success(
        api.await_parts(rma["id"], TEST_USERS["depot_technician_headers"]), 200)
    assert waiting["status"] == "AWAITING_PARTS"

    restocked = validate_success(
        api.restock_part(part["id"], {"quantity": 5},
                         TEST_USERS["depot_manager_headers"]), 200)
    assert restocked["stock_on_hand"] == 5, (
        f"restock must add 5 to 0, got {restocked['stock_on_hand']}")
    assert get_rma(rma["id"])["status"] == "IN_REPAIR", (
        "restocking a planned part must auto-resume the RMA to IN_REPAIR")


def test_workflow_reference_not_found_fc_part(api):
    """PRD §3.3: "the code must reference an existing failure code, otherwise
    the request fails with `ERR_FAILURE_CODE_NOT_FOUND`."
    PRD §3.4: "Every referenced part must exist; an unknown part reference is
    rejected with `ERR_PART_NOT_FOUND`."

    Design: Corner/errors/workflow_reference_not_found_fc_part_bay_loaner
    """
    ctx = setup_received_rma()
    bad_triage = api.triage_rma(ctx["rma"]["id"],
                                {"primary_failure_code_id": NON_EXISTENT_UUID},
                                TEST_USERS["intake_agent_headers"])
    validate_error(bad_triage, ApiErrorId.ERR_FAILURE_CODE_NOT_FOUND)
    assert bad_triage.status_code == 404

    triage_rma(ctx["rma"]["id"], ctx["fc"]["id"])  # real code succeeds
    bad_diagnose = api.diagnose_rma(
        ctx["rma"]["id"],
        {"labor_minutes_est": 10, "repairability": "REPAIRABLE",
         "planned_parts": [{"part_id": NON_EXISTENT_UUID, "quantity": 1}]},
        TEST_USERS["depot_technician_headers"])
    validate_error(bad_diagnose, ApiErrorId.ERR_PART_NOT_FOUND)
    assert bad_diagnose.status_code == 404
    assert get_rma(ctx["rma"]["id"])["status"] == "TRIAGED"


def _setup_bay_booking_holder():
    """RMA-A in IN_REPAIR holding BAY-1 for the closed window 08-10..08-12;
    returns (bay, rma_b in TRIAGED)."""
    model = create_model()
    customer = create_customer()
    fc = create_failure_code()
    part = create_part()
    bay = create_bay()
    unit_a = create_unit(model["id"], customer["id"], serial_number="SN-BAY-A")
    unit_b = create_unit(model["id"], customer["id"], serial_number="SN-BAY-B")
    rma_a = create_draft_rma(customer["id"], unit_a["id"])
    authorize_rma(rma_a["id"])
    receive_rma(rma_a["id"], unit_a["serial_number"])
    triage_rma(rma_a["id"], fc["id"])
    rma_a = diagnose_rma(rma_a["id"], labor_minutes_est=10,
                         planned_parts=[planned_part_line(part["id"], 1)])
    validate_success(api.schedule_bay(
        rma_a["id"],
        {"bay_id": bay["id"], "start_date": "2026-08-10", "end_date": "2026-08-12"},
        TEST_USERS["depot_technician_headers"]), 200)

    rma_b = create_draft_rma(customer["id"], unit_b["id"])
    authorize_rma(rma_b["id"])
    receive_rma(rma_b["id"], unit_b["serial_number"])
    triage_rma(rma_b["id"], fc["id"])
    return bay, rma_b


def test_booking_within_turnaround_buffer_rejected(api):
    """PRD §3.6: "Bay bookings are closed intervals and carry a one-day
    turnaround buffer on each side: a new booking conflicts, and is rejected
    with `ERR_BAY_OVERLAP`, when the padded interval beginning the day before
    its `start_date` and ending the day after its `end_date` intersects any
    existing booking on the same bay held by an RMA in `TRIAGED`, `DIAGNOSED`,
    `IN_REPAIR`, `AWAITING_PARTS`, `QA_HOLD`, or `READY_TO_SHIP`."

    Design: Difficulty/resource_temporal_overlap/bay_booking_closed_interval_buffer
    """
    bay, rma_b = _setup_bay_booking_holder()
    # padded [08-12 .. 08-16] intersects existing [08-10 .. 08-12] at 08-12
    res = api.schedule_bay(
        rma_b["id"],
        {"bay_id": bay["id"], "start_date": "2026-08-13", "end_date": "2026-08-15"},
        TEST_USERS["depot_technician_headers"])
    validate_error(res, ApiErrorId.ERR_BAY_OVERLAP)
    assert res.status_code == 409


def test_booking_after_turnaround_buffer_succeeds(api):
    """PRD §3.6: "A successful booking pins `bay_id`, `bay_start_date`, and
    `bay_end_date` on the RMA."
    PRD §3.6: "Bay bookings are closed intervals and carry a one-day turnaround
    buffer on each side: a new booking conflicts, and is rejected with
    `ERR_BAY_OVERLAP`, when the padded interval beginning the day before its
    `start_date` and ending the day after its `end_date` intersects any existing
    booking on the same bay held by an RMA in `TRIAGED`, `DIAGNOSED`,
    `IN_REPAIR`, `AWAITING_PARTS`, `QA_HOLD`, or `READY_TO_SHIP`."

    Design: Difficulty/resource_temporal_overlap/bay_booking_closed_interval_buffer
    """
    bay, rma_b = _setup_bay_booking_holder()
    # padded [08-13 .. 08-17] does not intersect existing [08-10 .. 08-12]
    booked = validate_success(api.schedule_bay(
        rma_b["id"],
        {"bay_id": bay["id"], "start_date": "2026-08-14", "end_date": "2026-08-16"},
        TEST_USERS["depot_technician_headers"]), 200)
    assert booked["bay_id"] == bay["id"]
    assert booked["bay_start_date"][:10] == "2026-08-14"
    assert booked["bay_end_date"][:10] == "2026-08-16"


def test_schedule_bay_invalid_window_and_inactive_bay(api):
    """PRD §2.8: "bay window shape (`ERR_INVALID_BAY_WINDOW`) before bay status
    (`ERR_BAY_INACTIVE`) before bay overlap (`ERR_BAY_OVERLAP`)"
    PRD §3.6: "The window must be well-formed — an `end_date` earlier than the
    `start_date` is rejected with `ERR_INVALID_BAY_WINDOW` — and the named bay
    must be `ACTIVE`, else `ERR_BAY_INACTIVE`."

    Design: Corner/validations/schedule_bay_invalid_window_and_inactive_bay
    """
    ctx = setup_triaged_rma()
    bay = create_bay()
    validate_success(api.deactivate_depot_bay(bay["id"],
                                              TEST_USERS["depot_manager_headers"]), 200)

    # Window shape is checked before bay status.
    bad_window = api.schedule_bay(
        ctx["rma"]["id"],
        {"bay_id": bay["id"], "start_date": "2026-08-12", "end_date": "2026-08-10"},
        TEST_USERS["depot_technician_headers"])
    validate_error(bad_window, ApiErrorId.ERR_INVALID_BAY_WINDOW)
    assert bad_window.status_code == 422

    inactive = api.schedule_bay(
        ctx["rma"]["id"],
        {"bay_id": bay["id"], "start_date": "2026-08-10", "end_date": "2026-08-12"},
        TEST_USERS["depot_technician_headers"])
    validate_error(inactive, ApiErrorId.ERR_BAY_INACTIVE)
    assert inactive.status_code == 409
    assert get_rma(ctx["rma"]["id"])["bay_id"] is None, (
        "rejected bookings must not pin a bay")
