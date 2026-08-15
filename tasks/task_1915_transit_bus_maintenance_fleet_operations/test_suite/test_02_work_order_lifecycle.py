"""Work-order state machine: initial state, transitions, cancel cascade,
parallel bus dimensions, AWAITING_PARTS auto-resume, and the QA rework loop."""
from test_helpers import (
    ApiErrorId,
    add_labor,
    assert_part,
    assert_work_order,
    create_in_progress_wo,
    defect_event,
    file_defect,
    get_success_data,
    issue_line,
    line_event,
    make_mechanic_headers,
    new_bus,
    new_mechanic,
    new_mechanic_with_certs,
    new_part,
    new_qa_mechanic,
    new_work_order,
    reserve_line,
    schedule_wo,
    start_wo,
    validate_error,
    validate_success,
    wo_event,
)
from test_helpers import fixtures as fx


def test_work_order_created_in_draft_initial_state(api):
    """PRD §3.3: "At open, the system snapshots `odometer_at_open` from the
    bus's current `odometer_miles`, sets `opened_date` to the logical clock
    date, initializes `labor_entries` to an empty list, `labor_total_cents`,
    `parts_total_cents`, `core_charges_accrued_cents`, `core_credits_cents`,
    `parts_net_cents`, `total_cost_cents`, and `qa_reject_count` to zero, and
    increments the bus's `version` by one."
    PRD §3.3: "A work order is a state machine in `status`, opening at `DRAFT`
    and terminating at either `CLOSED` or `CANCELLED`."
    PRD §2.5: "At server startup, the logical clock reads exactly
    `2026-08-01T00:00:00Z`; it never falls back to wall-clock time."

    Design: Corner/state_machines/work_order_created_in_draft_initial_state
    """
    bus = new_bus(initial_odometer_miles=43_210,
                  base_warranty_expiry_miles=5_000,
                  base_warranty_expiry_date="2024-01-01")
    wo = new_work_order(bus["id"], priority="ELECTIVE")
    assert_work_order(wo)
    assert wo["status"] == "DRAFT"
    assert wo["odometer_at_open"] == 43_210
    assert wo["opened_date"] == "2026-08-01", (
        f"opened_date must be the logical clock date 2026-08-01, "
        f"got {wo['opened_date']}"
    )
    assert wo["labor_entries"] == []
    assert wo["labor_total_cents"] == 0
    assert wo["parts_total_cents"] == 0
    assert wo["core_charges_accrued_cents"] == 0
    assert wo["core_credits_cents"] == 0
    assert wo["parts_net_cents"] == 0
    assert wo["total_cost_cents"] == 0
    assert wo["qa_reject_count"] == 0


def test_wo_submit_qa_from_draft_returns_invalid_state(api):
    """PRD §2.10: "A transition attempted against a resource in a non-terminal
    state that nonetheless is not a valid from-state for that transition is
    rejected with `ERR_INVALID_STATE` (HTTP 409)."
    PRD §3.4: "Once a work order is `IN_PROGRESS`, the lead mechanic (and only
    the lead — the caller's `X-User-ID` must equal `lead_mechanic_id`,
    otherwise `ERR_FORBIDDEN`) submits the work for QA, moving it to
    `PENDING_QA`."

    The caller is the designated lead so only the state gate can fire.

    Design: Corner/state_machines/wo_submit_qa_from_draft_returns_invalid_state
    """
    bus = new_bus(base_warranty_expiry_miles=5_000,
                  base_warranty_expiry_date="2024-01-01")
    lead = new_mechanic()
    wo = new_work_order(bus["id"], lead_mechanic_id=lead["id"])

    res = wo_event(wo["id"], "SUBMIT_QA", headers=make_mechanic_headers(lead["id"]))
    validate_error(res, ApiErrorId.ERR_INVALID_STATE)
    after = get_success_data(api.get_work_order(wo["id"], fx.SUP))
    assert after["status"] == "DRAFT", "WO must remain DRAFT after rejected SUBMIT_QA"


def test_wo_cancel_on_closed_returns_already_terminal(api):
    """PRD §2.10: "A transition attempted against a resource already in a
    terminal state is rejected with `ERR_ALREADY_TERMINAL` (HTTP 409) — every
    transition out of a terminal state is forbidden."

    Design: Corner/state_machines/wo_cancel_on_closed_returns_already_terminal
    """
    bus, wo = fx.setup_closed_wo_scenario(
        bus_overrides={"base_warranty_expiry_miles": 5_000,
                       "base_warranty_expiry_date": "2024-01-01"}
    )
    assert wo["status"] == "CLOSED"

    res = wo_event(wo["id"], "CANCEL", cancel_reason="too late")
    validate_error(res, ApiErrorId.ERR_ALREADY_TERMINAL)
    after = get_success_data(api.get_work_order(wo["id"], fx.SUP))
    assert after["status"] == "CLOSED", "WO must remain CLOSED"


def test_wo_cancel_releases_reserved_parts_and_unlinks_defect(api):
    """PRD §3.3: "On cancel, any still-`RESERVED` part lines are auto-released
    (decrementing each part's `quantity_reserved` and recomputing
    `stock_status`), a linked defect reverts from `WO_LINKED` back to
    `SHOP_QUEUED` with `linked_work_order_id` cleared, an `OVERHAUL` work
    order's bus returns from `OVERHAUL_HOLD` to `ACTIVE`, and the bus
    availability and fleet posture are recomputed."

    Design: Corner/state_machines/wo_cancel_releases_reserved_parts_and_unlinks_defect
    """
    bus = new_bus(initial_odometer_miles=100,
                  base_warranty_expiry_miles=5_000,
                  base_warranty_expiry_date="2024-01-01")
    part = new_part(sku="P-T4", initial_on_hand=5, unit_cost_cents=1_200)
    defect = file_defect(bus["id"], severity="MINOR", defect_code="HVAC",
                         description="rattle", odometer_at_report=100)
    validate_success(defect_event(defect["id"], "TRIAGE", disposition="SHOP"))
    wo = new_work_order(bus["id"], defect_report_id=defect["id"],
                        estimated_cost_cents=2_400)
    schedule_wo(wo["id"])
    line = reserve_line(wo["id"], part["id"], qty=2)

    cancelled = validate_success(
        wo_event(wo["id"], "CANCEL", cancel_reason="duplicate report")
    )
    assert cancelled["status"] == "CANCELLED"

    line_after = get_success_data(api.get_part_line(line["id"], fx.PC))
    assert line_after["issue_status"] == "RELEASED", (
        f"reserved line must be auto-released on cancel, got "
        f"{line_after['issue_status']}"
    )
    part_after = get_success_data(api.get_part(part["id"], fx.PC))
    assert_part(part_after)
    assert part_after["quantity_on_hand"] == 5
    assert part_after["quantity_reserved"] == 0, (
        "cancel must fully compensate the reservation"
    )

    defect_after = get_success_data(api.get_defect_report(defect["id"], fx.SUP))
    assert defect_after["status"] == "SHOP_QUEUED"
    assert defect_after["linked_work_order_id"] is None


def test_bus_parallel_dimensions_overhaul_hold_vs_availability(api):
    """PRD §3.11: "Starting an overhaul moves the bus's `service_status` from
    `ACTIVE` to `OVERHAUL_HOLD`. Closing (or cancelling) the overhaul returns
    the bus to `ACTIVE`; on a close, `last_overhaul_miles` is set to the bus's
    `odometer_miles` at close."
    PRD §2.7: "The derivation consults, in order of precedence from highest to
    lowest: `OUT_OF_SERVICE` when the bus's `service_status` is `RETIRED`; else
    `IN_SHOP` when any work order exists for the bus in one of the statuses
    `IN_PROGRESS`, `AWAITING_PARTS`, `PENDING_QA`, or `REOPENED`; else `HELD`
    when the bus's `hold_reasons` set is non-empty; else `AVAILABLE`."

    Design: Corner/state_machines/bus_parallel_dimensions_overhaul_hold_vs_availability
    """
    bus = new_bus(model_year=2019, in_service_date="2020-01-01",
                  initial_odometer_miles=100_000,
                  base_warranty_expiry_miles=5_000,
                  base_warranty_expiry_date="2022-01-01")
    lead = new_mechanic_with_certs("ENGINE", name="Overhaul Lead")
    qa = new_qa_mechanic()
    wo = new_work_order(
        bus["id"], wo_type="OVERHAUL", planned_start_date="2026-08-02",
        planned_end_date="2026-08-20", estimated_labor_hours=40,
        estimated_cost_cents=5_000_000, lead_mechanic_id=lead["id"],
    )
    schedule_wo(wo["id"])
    start_wo(wo["id"])

    mid = get_success_data(api.get_bus(bus["id"], fx.FM))
    assert mid["service_status"] == "OVERHAUL_HOLD"
    assert mid["availability_status"] == "IN_SHOP"

    add_labor(wo["id"], lead, work_date="2026-08-05", hours=8)
    wo_event(wo["id"], "SUBMIT_QA", headers=make_mechanic_headers(lead["id"]))
    validate_success(
        wo_event(wo["id"], "QA_CERTIFY", headers=make_mechanic_headers(qa["id"]))
    )

    after = get_success_data(api.get_bus(bus["id"], fx.FM))
    assert after["service_status"] == "ACTIVE"
    assert after["availability_status"] == "AVAILABLE"
    assert after["last_overhaul_miles"] == 100_000, (
        "close must stamp last_overhaul_miles with the odometer at close"
    )


def test_awaiting_parts_auto_resume_when_last_line_issued(api):
    """PRD §3.3: "Once started, a work order can be parked in `AWAITING_PARTS`
    (from `IN_PROGRESS`) and later resumed to `IN_PROGRESS` either explicitly
    by a supervisor or mechanic or automatically when the last `RESERVED` part
    line on it reaches `ISSUED` or `RELEASED`."

    Design: Corner/state_machines/awaiting_parts_auto_resume_when_last_line_issued
    """
    bus = new_bus(initial_odometer_miles=100,
                  base_warranty_expiry_miles=5_000,
                  base_warranty_expiry_date="2024-01-01")
    part = new_part(sku="P-T7", initial_on_hand=3, unit_cost_cents=900)
    lead = new_mechanic()
    wo = create_in_progress_wo(bus["id"], lead, estimated_cost_cents=900)

    parked = validate_success(
        wo_event(wo["id"], "SET_AWAITING_PARTS",
                 headers=make_mechanic_headers(lead["id"]))
    )
    assert parked["status"] == "AWAITING_PARTS"

    line = reserve_line(wo["id"], part["id"], qty=1)
    issued = issue_line(line["id"], mechanic=lead)
    assert issued["issue_status"] == "ISSUED"

    wo_after = get_success_data(api.get_work_order(wo["id"], fx.SUP))
    assert wo_after["status"] == "IN_PROGRESS", (
        "issuing the last RESERVED line must auto-resume the WO to IN_PROGRESS; "
        f"got {wo_after['status']}"
    )


class TestWorkOrderReworkCycle:
    """PENDING_QA -> QA_REJECT -> REOPENED -> RESUME_WORK -> IN_PROGRESS."""

    def _setup_pending_qa(self):
        bus = new_bus(fleet_number="B400", vin="VINB400",
                      base_warranty_expiry_miles=5_000,
                      base_warranty_expiry_date="2024-01-01")
        lead = new_mechanic(name="Lead", employee_ref="E30")
        qa = new_qa_mechanic()
        wo = create_in_progress_wo(bus["id"], lead, estimated_cost_cents=13_000)
        add_labor(wo["id"], lead, hours=1)
        wo = get_success_data(
            wo_event(wo["id"], "SUBMIT_QA",
                     headers=make_mechanic_headers(lead["id"]))
        )
        assert wo["status"] == "PENDING_QA"
        return bus, lead, qa, wo

    def test_qa_reject_reopens_and_resume_returns_to_in_progress(self, api):
        """PRD §3.4: "Rejection moves it back to `REOPENED`, increments
        `qa_reject_count` by one, and records the supplied `qa_note`; a
        `REOPENED` work order can be resumed to `IN_PROGRESS` to continue work."

        Design: Difficulty/non_linear_state_machine/work_order_rework_cycle_reopened_resume_recertify
        """
        _, lead, qa, wo = self._setup_pending_qa()

        rejected = validate_success(
            wo_event(wo["id"], "QA_REJECT", qa_note="brake drag persists",
                     headers=make_mechanic_headers(qa["id"]))
        )
        assert rejected["status"] == "REOPENED"
        assert rejected["qa_reject_count"] == 1
        assert rejected["qa_note"] == "brake drag persists"

        resumed = validate_success(
            wo_event(wo["id"], "RESUME_WORK",
                     headers=make_mechanic_headers(lead["id"]))
        )
        assert resumed["status"] == "IN_PROGRESS", (
            "RESUME_WORK must cycle back to IN_PROGRESS, not forward; got "
            f"{resumed['status']}"
        )

    def test_rework_loop_recertifies_to_closed_with_labor_preserved(self, api):
        """PRD §3.4: "Rejection moves it back to `REOPENED`, increments
        `qa_reject_count` by one, and records the supplied `qa_note`; a
        `REOPENED` work order can be resumed to `IN_PROGRESS` to continue work."
        PRD §3.5: "`labor_total_cents` is the sum of those per-entry amounts."

        Design: Difficulty/non_linear_state_machine/work_order_rework_cycle_reopened_resume_recertify
        """
        _, lead, qa, wo = self._setup_pending_qa()

        wo_event(wo["id"], "QA_REJECT", qa_note="brake drag persists",
                 headers=make_mechanic_headers(qa["id"]))
        wo_event(wo["id"], "RESUME_WORK", headers=make_mechanic_headers(lead["id"]))
        add_labor(wo["id"], lead, work_date="2026-08-03", hours=1)
        wo_event(wo["id"], "SUBMIT_QA", headers=make_mechanic_headers(lead["id"]))
        closed = validate_success(
            wo_event(wo["id"], "QA_CERTIFY",
                     headers=make_mechanic_headers(qa["id"]))
        )
        assert closed["status"] == "CLOSED"
        assert closed["labor_total_cents"] == 13_000, (
            "both 1h AM entries (6500 each) survive the reject-rework loop; "
            f"got {closed['labor_total_cents']}"
        )
