"""As-found assessment lifecycle: birth state, submit/return cycle, guarded
acceptance, and terminal lockdown."""

import test_helpers as fx
from test_helpers import (
    PM,
    ApiErrorId,
    make_assessor_headers,
    validate_error,
    validate_success,
)

ASSESSOR_1 = "assessor-1"


def _machine_with_draft_assessment():
    customer = fx.create_customer()
    machine = fx.create_machine(customer["id"])
    assessment = fx.create_assessment(machine["id"], assessor_id=ASSESSOR_1)
    return customer, machine, assessment


def test_assessment_initial_state_draft(api):
    """PRD §3.2: "An assessment is born in `DRAFT`."
    PRD §3.2: "Second, the machine's `version` increments by one; on the very first filing for a machine, the machine additionally transitions from `REGISTERED` to `UNDER_ASSESSMENT` — subsequent filings leave the machine's `status` untouched while still bumping its version."

    Design: Corner/state_machines/assessment_initial_state_draft
    """
    customer = fx.create_customer()
    machine = fx.create_machine(customer["id"])
    assessment = fx.create_assessment(machine["id"], assessor_id=ASSESSOR_1)

    assert assessment["status"] == "DRAFT"
    fx.assert_assessment(assessment)

    machine_after = fx.get_machine(machine["id"])
    assert machine_after["status"] == "UNDER_ASSESSMENT"
    assert machine_after["version"] == machine["version"] + 1


def test_assessment_return_resubmit_cycle(api):
    """PRD §3.2: "A `ProjectManager` reviews a submitted assessment and either returns it for rework, moving it to `RETURNED`, or accepts it."
    PRD §3.2: "A returned assessment may be resubmitted by its assessor, re-entering `SUBMITTED`, and this submit–return cycle may repeat."

    Design: Corner/state_machines/assessment_return_resubmit_cycle
    """
    _, _, assessment = _machine_with_draft_assessment()
    assessment = fx.submit_assessment(assessment["id"], assessor_id=ASSESSOR_1)
    assert assessment["status"] == "SUBMITTED"

    returned = validate_success(api.return_assessment(assessment["id"], PM), 200)
    assert returned["status"] == "RETURNED"

    resubmitted = fx.submit_assessment(assessment["id"], assessor_id=ASSESSOR_1)
    assert resubmitted["status"] == "SUBMITTED"


def test_assessment_accept_from_draft_rejected(api):
    """PRD §3.2: "A `ProjectManager` reviews a submitted assessment and either returns it for rework, moving it to `RETURNED`, or accepts it."
    PRD §2.8: "The target entity is in the state the action requires per its state machine; otherwise one of `ERR_INVALID_STATE`, `ERR_PROJECT_NOT_IN_WARRANTY`, `ERR_COMMERCIAL_NOT_APPROVED`, `ERR_QUOTE_REQUIRED`, or `ERR_PROJECT_NOT_AWAITING_ACCEPTANCE` (HTTP 409)."
    PRD §3.2: "Acceptance moves the assessment to the terminal `ACCEPTED`, moves the machine to `ASSESSED`, and — critically — auto-creates the RebuildProject that will carry the engagement: the project is born with `work_status` of `SCOPED`, `commercial_status` of `QUOTE_DRAFT`, `decision` of `NONE`, and its `assessment_id`, `machine_id`, and `customer_id` all linked from the accepted assessment and its machine."

    Design: Corner/state_machines/assessment_accept_from_draft_rejected
    """
    _, _, assessment = _machine_with_draft_assessment()

    res = api.accept_assessment(assessment["id"], PM)
    validate_error(res, ApiErrorId.ERR_INVALID_STATE.value)

    after = validate_success(api.get_assessment(assessment["id"], PM), 200)
    assert after["status"] == "DRAFT"

    projects = api.list_projects(PM, params={"assessment_id": assessment["id"]}).json()["data"]
    assert projects == [], "no project may be created by a rejected acceptance"


def test_assessment_terminal_lockdown_submit_after_accept_rejected(api):
    """PRD §3.2: "Acceptance moves the assessment to the terminal `ACCEPTED`, moves the machine to `ASSESSED`, and — critically — auto-creates the RebuildProject that will carry the engagement: the project is born with `work_status` of `SCOPED`, `commercial_status` of `QUOTE_DRAFT`, `decision` of `NONE`, and its `assessment_id`, `machine_id`, and `customer_id` all linked from the accepted assessment and its machine."
    PRD §2.8: "The target entity is in the state the action requires per its state machine; otherwise one of `ERR_INVALID_STATE`, `ERR_PROJECT_NOT_IN_WARRANTY`, `ERR_COMMERCIAL_NOT_APPROVED`, `ERR_QUOTE_REQUIRED`, or `ERR_PROJECT_NOT_AWAITING_ACCEPTANCE` (HTTP 409)."

    Design: Corner/state_machines/assessment_terminal_lockdown_submit_after_accept_rejected
    """
    _, _, assessment = _machine_with_draft_assessment()
    fx.submit_assessment(assessment["id"], assessor_id=ASSESSOR_1)
    accepted = fx.accept_assessment(assessment["id"])
    assert accepted["status"] == "ACCEPTED"

    res = api.submit_assessment(assessment["id"], make_assessor_headers(ASSESSOR_1))
    validate_error(res, ApiErrorId.ERR_INVALID_STATE.value)

    after = validate_success(api.get_assessment(assessment["id"], PM), 200)
    assert after["status"] == "ACCEPTED"
