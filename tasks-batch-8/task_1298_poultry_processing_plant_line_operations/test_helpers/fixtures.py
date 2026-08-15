"""Composite setup helpers for the poultry plant line-operations workflows.

Each helper builds its preconditions from scratch using only PRD-declared
endpoints (the server restarts with an empty database before every test).
Setup calls use get_success_data() so failures surface as clear setup errors.
"""
import pytest

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    create_line_payload,
    create_shift_payload,
    staffing_payload,
    create_sanitation_run_payload,
    create_preop_inspection_payload,
    create_waiver_payload,
    create_flock_lot_payload,
    receive_flock_lot_payload,
    create_line_run_payload,
    complete_run_payload,
    create_condemnation_record_payload,
    create_utility_reading_payload,
    create_order_payload,
    create_deboning_batch_payload,
    complete_batch_payload,
    create_chill_chain_log_payload,
)
from .test_users import (
    TEST_USERS,
    make_qa_technician_headers,
    make_sanitation_lead_headers,
    make_usda_inspector_headers,
)

PM = TEST_USERS["plant_manager_headers"]
SUP = TEST_USERS["shift_supervisor_headers"]
RCV = TEST_USERS["receiving_clerk_headers"]
OP = TEST_USERS["line_operator_headers"]
QA = TEST_USERS["qa_technician_headers"]
SAN = TEST_USERS["sanitation_lead_headers"]
USDA = TEST_USERS["usda_inspector_headers"]
PLAN = TEST_USERS["order_planner_headers"]

# Named operator ids used across segregation-of-duties boundaries (PRD §2.1/§3).
SAN_USER = "san-1"
QA_VERIFIER = "qa-1"
QA_PREOP_INSPECTOR = "qa-2"
QA_RECORDER = "qa-1"
USDA_USER = "usda-1"


# ---------------------------------------------------------------------------
# Tier 1/2: configuration, hygiene gates, receiving
# ---------------------------------------------------------------------------

def make_line(line_code="EV-1", line_type="EVISCERATION", rated_speed_bpm=200):
    """Register a processing line. Returns the line resource."""
    return get_success_data(api_client.create_line(
        create_line_payload(line_code=line_code, line_type=line_type,
                            rated_speed_bpm=rated_speed_bpm), PM))


def make_shift(shift_date="2026-08-01", shift_code="DAY_A",
               shackle_capacity_birds=20000, labor_hours_budget=100.0,
               staffing=None):
    """Create a shift; optionally set staffing (full EV+DB crew by default)."""
    shift = get_success_data(api_client.create_shift(
        create_shift_payload(shift_date=shift_date, shift_code=shift_code,
                             shackle_capacity_birds=shackle_capacity_birds,
                             labor_hours_budget=labor_hours_budget), PM))
    if staffing is not None:
        payload = staffing_payload(shift["version"], **staffing)
        shift = get_success_data(api_client.set_shift_staffing(shift["id"], payload, SUP))
    return shift


def fully_staffed_shift(**kwargs):
    """Create a shift staffed at the full requirement for both line types."""
    kwargs.setdefault("staffing", {
        "shacklers_present": 10, "eviscerators_present": 20,
        "deboners_present": 12, "qa_techs_present": 2,
    })
    return make_shift(**kwargs)


def create_verified_sanitation(shift_id, line_id, completer_user_id=SAN_USER,
                               verifier_user_id=QA_VERIFIER,
                               window_start="2026-08-01T00:00:00Z",
                               window_end="2026-08-01T02:00:00Z"):
    """SCHEDULED -> IN_PROGRESS -> COMPLETED -> VERIFIED for (shift, line)."""
    run = get_success_data(api_client.create_sanitation_run(
        create_sanitation_run_payload(shift_id, line_id,
                                      window_start=window_start, window_end=window_end),
        SAN))
    api_client.advance_sanitation_run(
        run["id"], {"to_status": "IN_PROGRESS"}, make_sanitation_lead_headers(completer_user_id))
    api_client.advance_sanitation_run(
        run["id"], {"to_status": "COMPLETED"}, make_sanitation_lead_headers(completer_user_id))
    run = get_success_data(api_client.advance_sanitation_run(
        run["id"], {"to_status": "VERIFIED"}, make_qa_technician_headers(verifier_user_id)))
    return run


def create_passed_preop(shift_id, line_id, inspector_user_id=QA_PREOP_INSPECTOR,
                        completer_user_id=SAN_USER, verifier_user_id=QA_VERIFIER):
    """Verified sanitation plus a PASSED pre-op by an inspector who is NOT the
    sanitation completer (segregation of duties, PRD §3.2)."""
    create_verified_sanitation(shift_id, line_id,
                               completer_user_id=completer_user_id,
                               verifier_user_id=verifier_user_id)
    preop = get_success_data(api_client.create_preop_inspection(
        create_preop_inspection_payload(shift_id, line_id), QA))
    preop = get_success_data(api_client.advance_preop_inspection(
        preop["id"], {"to_status": "PASSED"}, make_qa_technician_headers(inspector_user_id)))
    return preop


def book_and_receive_lot(shift_id, lot_code="FL-100", grower_name="GrowerA",
                         booked_head_count=10000, head_count_received=10000,
                         doa_count=50, total_live_weight_lb=50000.0,
                         expected_avg_live_weight_lb=5.0):
    """Book a flock lot into the shift and receive it. Returns the lot."""
    lot = get_success_data(api_client.create_flock_lot(
        create_flock_lot_payload(shift_id, lot_code=lot_code, grower_name=grower_name,
                                 booked_head_count=booked_head_count,
                                 expected_avg_live_weight_lb=expected_avg_live_weight_lb), RCV))
    lot = get_success_data(api_client.receive_flock_lot(
        lot["id"], receive_flock_lot_payload(head_count_received=head_count_received,
                                             doa_count=doa_count,
                                             total_live_weight_lb=total_live_weight_lb), RCV))
    return lot


def queue_run(shift_id, line_id, flock_lot_id, planned_speed_bpm=175):
    """Queue a flock lot onto an EVISCERATION line. Returns the run (QUEUED)."""
    return get_success_data(api_client.create_line_run(
        create_line_run_payload(shift_id, line_id, flock_lot_id,
                                planned_speed_bpm=planned_speed_bpm), SUP))


def open_shift(shift_id):
    """SCHEDULED -> RUNNING."""
    return get_success_data(api_client.transition_shift(
        shift_id, {"to_status": "RUNNING"}, SUP))


def set_clock(to_iso8601):
    """Advance the plant's logical clock."""
    return get_success_data(api_client.set_clock({"to_iso8601": to_iso8601}, PM))


# ---------------------------------------------------------------------------
# Tier 3: full production-chain lifecycle shortcuts
# ---------------------------------------------------------------------------

def setup_running_shift_with_run(line_code="EV-1", rated_speed_bpm=200,
                                 lot_code="FL-100", planned_speed_bpm=175,
                                 booked_head_count=10000, head_count_received=10000,
                                 doa_count=50, total_live_weight_lb=50000.0,
                                 labor_hours_budget=100.0, staffing=None,
                                 waiver_max_speed_bpm=None,
                                 waiver_window=("2026-08-01T00:00:00Z", "2026-08-02T00:00:00Z")):
    """Full open-production preamble: EV line (+ optional ACTIVE waiver), fully
    staffed shift, sanitation VERIFIED + pre-op PASSED (distinct operator ids),
    lot received, run queued, shift opened, run started.

    Returns dict(line, shift, lot, run).
    """
    if staffing is None:
        staffing = {"shacklers_present": 10, "eviscerators_present": 20,
                    "deboners_present": 12, "qa_techs_present": 2}
    line = make_line(line_code=line_code, rated_speed_bpm=rated_speed_bpm)
    if waiver_max_speed_bpm is not None:
        waiver = get_success_data(api_client.create_waiver(
            line["id"], create_waiver_payload(
                line["version"], max_speed_bpm=waiver_max_speed_bpm,
                effective_from=waiver_window[0], effective_to=waiver_window[1]), PM))
        get_success_data(api_client.advance_waiver(waiver["id"], {"to_status": "SUBMITTED"}, PM))
        get_success_data(api_client.advance_waiver(
            waiver["id"], {"to_status": "APPROVED"}, make_usda_inspector_headers(USDA_USER)))
    shift = make_shift(labor_hours_budget=labor_hours_budget, staffing=staffing)
    create_passed_preop(shift["id"], line["id"])
    lot = book_and_receive_lot(
        shift["id"], lot_code=lot_code, booked_head_count=booked_head_count,
        head_count_received=head_count_received, doa_count=doa_count,
        total_live_weight_lb=total_live_weight_lb)
    run = queue_run(shift["id"], line["id"], lot["id"], planned_speed_bpm=planned_speed_bpm)
    shift = open_shift(shift["id"])
    run = get_success_data(api_client.advance_line_run(run["id"], {"to_status": "RUNNING"}, OP))
    return {"line": line, "shift": shift, "lot": lot, "run": run}


def complete_run(run_id, birds_hung=9950, carcass_weight_lb=36000.0):
    """RUNNING -> COMPLETED with measured birds/weight."""
    return get_success_data(api_client.advance_line_run(
        run_id, complete_run_payload(birds_hung=birds_hung, carcass_weight_lb=carcass_weight_lb), OP))


def setup_completed_run(completion_clock="2026-08-01T06:00:00Z", condemnation=None,
                        condemn_user_id=QA_RECORDER, birds_hung=9950,
                        carcass_weight_lb=36000.0, **kwargs):
    """Running-shift scenario with the run COMPLETED at `completion_clock`.
    Optionally records one DRAFT condemnation record of the given count.
    Returns dict(line, shift, lot, run, record?)."""
    env = setup_running_shift_with_run(**kwargs)
    if completion_clock is not None:
        set_clock(completion_clock)
    env["run"] = complete_run(env["run"]["id"], birds_hung=birds_hung,
                              carcass_weight_lb=carcass_weight_lb)
    if condemnation is not None:
        env["record"] = get_success_data(api_client.create_condemnation_record(
            create_condemnation_record_payload(env["run"]["id"], carcass_count=condemnation),
            make_qa_technician_headers(condemn_user_id)))
    return env


def setup_chilled_lot(lot_code="FL-100", condemnation=None, condemn_user_id=QA_RECORDER,
                      **kwargs):
    """Completed-run scenario with the clock advanced past the 4h chill hold so
    the lot reads CHILLED. Returns env dict (with optional DRAFT record)."""
    env = setup_completed_run(completion_clock="2026-08-01T06:00:00Z",
                              condemnation=condemnation, condemn_user_id=condemn_user_id,
                              lot_code=lot_code, **kwargs)
    set_clock("2026-08-01T10:00:00Z")
    env["lot"] = get_success_data(api_client.get_flock_lot(env["lot"]["id"], PM))
    assert env["lot"]["status"] == "CHILLED", (
        f"setup failed: lot status {env['lot']['status']} != CHILLED")
    return env


def setup_settled_lot(lot_code="FL-100", **kwargs):
    """Zero-condemnation CHILLED lot advanced to SETTLED (certified yield computed)."""
    env = setup_chilled_lot(lot_code=lot_code, **kwargs)
    env["lot"] = get_success_data(api_client.advance_flock_lot(
        env["lot"]["id"], {"to_status": "SETTLED"}, SUP))
    assert env["lot"]["status"] == "SETTLED", "setup failed: settle rejected"
    return env


def make_order(pounds_ordered=500.0, temperature_requirement="FROZEN",
               due_at="2026-08-03T00:00:00Z", customer_name="CustX",
               product_code="WINGS"):
    """Create a customer order (PENDING / UNALLOCATED)."""
    return get_success_data(api_client.create_order(
        create_order_payload(pounds_ordered=pounds_ordered,
                             temperature_requirement=temperature_requirement,
                             due_at=due_at, customer_name=customer_name,
                             product_code=product_code), PLAN))


def make_batch(order_id, flock_lot_id, shift_id, line_id, crew_count=12,
               input_weight_lb=1000.0):
    """Schedule a deboning batch (SCHEDULED)."""
    return get_success_data(api_client.create_deboning_batch(
        create_deboning_batch_payload(order_id, flock_lot_id, shift_id, line_id,
                                      crew_count=crew_count, input_weight_lb=input_weight_lb), SUP))


def setup_production_line_for_deboning(order_pounds=500.0,
                                       temperature_requirement="FROZEN",
                                       input_weight_lb=1000.0, crew_count=12,
                                       due_at="2026-08-03T00:00:00Z",
                                       labor_hours_budget=100.0,
                                       lot_code="FL-100",
                                       customer_name="CustX", product_code="WINGS",
                                       **kwargs):
    """EV line + DB line, RUNNING shift, CHILLED lot, order, one SCHEDULED batch.
    Returns dict(env fields + deboning_line, order, batch)."""
    env = setup_chilled_lot(lot_code=lot_code, labor_hours_budget=labor_hours_budget, **kwargs)
    db_line = make_line(line_code="DB-1", line_type="DEBONING", rated_speed_bpm=50)
    order = make_order(pounds_ordered=order_pounds,
                       temperature_requirement=temperature_requirement, due_at=due_at,
                       customer_name=customer_name, product_code=product_code)
    batch = make_batch(order["id"], env["lot"]["id"], env["shift"]["id"], db_line["id"],
                       crew_count=crew_count, input_weight_lb=input_weight_lb)
    env.update({"deboning_line": db_line, "order": order, "batch": batch})
    return env


def complete_batch(batch_id, actual_output_weight_lb=980.0, actual_labor_hours=2.0):
    """SCHEDULED -> IN_PROGRESS -> COMPLETED. Returns the COMPLETED batch."""
    get_success_data(api_client.advance_deboning_batch(batch_id, {"to_status": "IN_PROGRESS"}, OP))
    return get_success_data(api_client.advance_deboning_batch(
        batch_id, complete_batch_payload(actual_output_weight_lb=actual_output_weight_lb,
                                         actual_labor_hours=actual_labor_hours), OP))


def first_finished_lot():
    """Discover the finished lot cascade-created by a batch completion."""
    data, _ = _list_finished_lots()
    assert len(data) >= 1, "setup failed: expected at least one finished lot"
    return data[0]


def _list_finished_lots(params=None):
    from prd_bench_local_runner.testing import validate_paginated
    return validate_paginated(api_client.list_finished_lots(QA, params=params))


def setup_finished_lot_open(temperature_requirement="FROZEN", output_weight_lb=980.0,
                            order_pounds=500.0, settle_lot=False, **kwargs):
    """Full chain through a COMPLETED batch: finished lot exists, status OPEN.
    Returns env dict with 'finished_lot' added."""
    env = setup_production_line_for_deboning(
        order_pounds=order_pounds, temperature_requirement=temperature_requirement, **kwargs)
    if settle_lot:
        env["lot"] = get_success_data(api_client.advance_flock_lot(
            env["lot"]["id"], {"to_status": "SETTLED"}, SUP))
    env["batch"] = complete_batch(env["batch"]["id"], actual_output_weight_lb=output_weight_lb)
    env["finished_lot"] = first_finished_lot()
    return env


def setup_trace_locked_lot(temperature_requirement="FROZEN", chill_temp_c=3.5,
                           output_weight_lb=500.0, input_weight_lb=500.0,
                           order_pounds=400.0, settle_lot=True, **kwargs):
    """Full chain through trace-lock: settled source lot, compliant chill log,
    finished lot TRACE_LOCKED. Returns env dict with routing captured."""
    env = setup_finished_lot_open(temperature_requirement=temperature_requirement,
                                  output_weight_lb=output_weight_lb,
                                  input_weight_lb=input_weight_lb,
                                  order_pounds=order_pounds, settle_lot=settle_lot, **kwargs)
    if chill_temp_c is not None:
        get_success_data(api_client.create_chill_chain_log(
            create_chill_chain_log_payload(env["finished_lot"]["id"],
                                           temperature_c=chill_temp_c), QA))
    env["finished_lot"] = get_success_data(api_client.trace_lock_finished_lot(
        env["finished_lot"]["id"], {}, QA))
    assert env["finished_lot"]["status"] == "TRACE_LOCKED", "setup failed: trace-lock rejected"
    return env


def setup_shipped_lot(**kwargs):
    """Trace-locked lot advanced to SHIPPED."""
    env = setup_trace_locked_lot(**kwargs)
    env["finished_lot"] = get_success_data(api_client.advance_finished_lot(
        env["finished_lot"]["id"], {"to_status": "SHIPPED"}, SUP))
    return env
