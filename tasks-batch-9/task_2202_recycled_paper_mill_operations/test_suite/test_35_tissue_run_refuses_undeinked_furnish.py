"""A tissue run reaches for furnish that never saw the deink plant: the third start gate
fires ahead of the tonnage gate, and nothing downstream moves.
"""
import pytest

from test_helpers import (
    api_client, validate_error, get_success_data, ApiErrorId, TEST_USERS,
    register_machine, register_permit, setup_cleaned_deink_batch, schedule_run,
    set_clock,
)

PLANNER = TEST_USERS["planner_headers"]
OPERATOR = TEST_USERS["operator_headers"]
ENV = TEST_USERS["env_officer_headers"]

PM1 = {"name": "PM1", "wire_width_mm": 5600, "max_tons_per_hour": 20.00,
       "changeover_buffer_minutes": 30, "steam_tph_per_ton": 2.500}
MILL_PERMIT = {"permit_number": "MILL-NPDES-1", "bod_limit_kg_per_day": 500.00,
               "tss_limit_kg_per_day": 400.00, "flow_limit_m3_per_day": 9000.00,
               "rolling_window_days": 30}


def test_a_tissue_run_refuses_furnish_that_never_saw_the_deink_plant():
    """PRD §3.5: "Third, if the run's product specification has `requires_deink_pulp` set, the
    drawn batch's `deink_pass_count` must be at least 1, and a batch that has never been
    deinked is rejected with `ERR_DEINK_PULP_REQUIRED` (HTTP 409)."
    PRD §3.5: "Fourth, the pulp must actually be there: the referenced batch must be in
    `APPROVED` and its `available_tons` must be at least the run's `pulp_draw_tons`, with the
    boundary inclusive, and a shortfall or an unapproved batch is rejected with
    `ERR_INSUFFICIENT_PULP` (HTTP 409)."
    PRD §3.3: "A product that **does** require deinked pulp cannot be approved from `CLEANED`
    at all — the approval precondition explicitly requires the target specification's deink
    requirement to be false — and must instead enter the deink loop, `CLEANED → DEINKING`, at
    the hands of a `MachineOperator`, which additionally requires the batch's `pulper_line` to
    be `DIP_LINE`."
    PRD §3.3: "A `QualityLab` operator submits `brightness_iso`, a value from 0 through 100 at
    one decimal place measured after the pass just run; the field reads null on a batch that
    has never had a pass."

    Design: Corner/errors/a_tissue_run_refuses_furnish_that_never_saw_the_deink_plant
    """
    set_clock("2026-08-01T00:00:00Z")
    permit = register_permit(**MILL_PERMIT)
    machine = register_machine(**PM1)
    bundle = setup_cleaned_deink_batch(tons_charged=1.000, measured_reject_tons=0.300)
    batch_id = bundle["batch"]["id"]
    assert get_success_data(api_client.get_effluent_permit(
        permit["id"], ENV))["compliance_posture"] == "COMPLIANT"
    run = schedule_run(machine["id"], "TIS_16", batch_id,
                       window_start="2026-09-01T06:00:00Z",
                       window_end="2026-09-01T14:00:00Z", pulp_draw_tons=0.500)

    response = api_client.start_run(machine["id"], run["id"], OPERATOR)
    validate_error(response, ApiErrorId.ERR_DEINK_PULP_REQUIRED.value, 409)

    unstarted = get_success_data(api_client.get_run(run["id"], PLANNER))
    assert unstarted["run_status"] == "SCHEDULED"
    assert unstarted["started_by_user_id"] is None
    undeinked = get_success_data(api_client.get_pulp_batch(batch_id, OPERATOR))
    assert undeinked["deink_pass_count"] == 0
    assert undeinked["brightness_iso"] is None
    assert undeinked["consumed_tons"] == pytest.approx(0.000, abs=1e-6)
    assert undeinked["status"] == "CLEANED", \
        "a deink-requiring target has no road from CLEANED to APPROVED"
