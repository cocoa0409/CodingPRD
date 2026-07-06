"""On-site field work: the CO safety threshold, parallel job/safety dimensions,
and flue-inspection condemnation."""
import pytest
from test_helpers import (
    api_client, TEST_USERS, make_technician_headers, validate_success,
)
from test_helpers import factories as F
from test_helpers import fixtures as fx

DISPATCHER = TEST_USERS["dispatcher_headers"]


# ---------------------------------------------------------------- bpc CO threshold
@pytest.mark.parametrize(
    "co_ppm,expected_outcome,expected_posture",
    [
        (8, "PASS", "SAFE"),    # below the 9 ppm boundary — passes
        (9, "FAIL", "UNSAFE"),  # exactly at the inclusive boundary — fails
    ],
)
def test_co_ppm_unsafe_boundary(co_ppm, expected_outcome, expected_posture):
    """PRD §3.4: "if `co_ppm` is at least 70 the outcome is `CONDEMN`; otherwise if
    `co_ppm` is at least 9 or spillage was detected the outcome is `FAIL`;
    otherwise if the draft test did not pass the outcome is `CONDITIONS`; otherwise
    the outcome is `PASS`."
    PRD §2.7: "The boundary is inclusive at 9 — a reading of 8 ppm passes that
    particular check, a reading of 9 ppm does not."

    Design: Difficulty/boundary_precision_check/bpc_co_ppm_unsafe_threshold
    """
    setup = fx.setup_job(job_overrides={"inspection_level": 2})
    job_id = setup["job"]["id"]
    sc = fx.record_safety_check(job_id, setup["technician"], co_ppm=co_ppm, draft_ok=True)
    assert sc["outcome"] == expected_outcome
    assert fx.get_job(job_id)["safety_posture"] == expected_posture


def test_co_ppm_condemn_threshold():
    """PRD §3.4: "if `co_ppm` is at least 70 the outcome is `CONDEMN`; otherwise if
    `co_ppm` is at least 9 or spillage was detected the outcome is `FAIL`;
    otherwise if the draft test did not pass the outcome is `CONDITIONS`; otherwise
    the outcome is `PASS`."
    PRD §3.4: "A `CONDEMN` sets the posture to `CONDEMNED` from any posture and is
    final."

    Design: Difficulty/boundary_precision_check/bpc_co_ppm_unsafe_threshold
    """
    setup = fx.setup_job(job_overrides={"inspection_level": 2})
    job_id = setup["job"]["id"]
    sc = fx.record_safety_check(job_id, setup["technician"], co_ppm=70, draft_ok=True)
    assert sc["outcome"] == "CONDEMN"
    assert fx.get_job(job_id)["safety_posture"] == "CONDEMNED"


# ---------------------------------------------------------------- nlsm parallel dims
def test_arrival_sets_in_progress_leaving_posture_pending():
    """PRD §2.7: "A job can be `IN_PROGRESS` while its posture is anything; the two
    are orthogonal."
    PRD §3.3: "The arrival step is significant beyond the appointment itself: it
    advances the parent job `SCHEDULED → IN_PROGRESS`."

    Design: Difficulty/non_linear_state_machine/nlsm_servicejob_parallel_dimensions
    """
    setup = fx.setup_in_progress_job(job_overrides={"inspection_level": 2})
    job = fx.get_job(setup["job"]["id"])
    assert job["job_status"] == "IN_PROGRESS"
    assert job["safety_posture"] == "PENDING"


def test_safety_and_sweep_move_posture_without_touching_job_status():
    """PRD §2.7: "A job can be `IN_PROGRESS` while its posture is anything; the two
    are orthogonal."
    PRD §3.4: "A heavy sweep also affects safety: when the `measured_creosote_class`
    is 3, and only if the current posture is `PENDING` or `SAFE`, the posture moves
    to `CONDITIONS`."

    Design: Difficulty/non_linear_state_machine/nlsm_servicejob_parallel_dimensions
    """
    setup = fx.setup_in_progress_job(job_overrides={"inspection_level": 2})
    tech = setup["technician"]
    job_id = setup["job"]["id"]
    fx.record_safety_check(job_id, tech, co_ppm=4, draft_ok=True)  # PASS -> SAFE
    fx.record_sweep(job_id, tech, measured_creosote_class=3)       # class 3 -> CONDITIONS
    job = fx.get_job(job_id)
    assert job["job_status"] == "IN_PROGRESS"
    assert job["safety_posture"] == "CONDITIONS"


# ---------------------------------------------------------------- corner: inspect BLOCKED
def test_inspect_blocked_condemns_job():
    """PRD §3.4: "A `BLOCKED` result is a hard stop: it condemns the appliance,
    driving `safety_posture` to `CONDEMNED` regardless of the current posture."
    PRD §3.4: "Recording a result stores it on the job."

    Design: Corner/state_machines/posture_condemned_on_inspect_blocked
    """
    setup = fx.setup_job(job_overrides={"inspection_level": 3})
    resp = api_client.inspect_service_job(
        setup["job"]["id"], {"flue_assessment": "BLOCKED"}, make_technician_headers(setup["technician"]["id"])
    )
    data = validate_success(resp, 200)
    assert data["flue_assessment"] == "BLOCKED"
    assert data["safety_posture"] == "CONDEMNED"
