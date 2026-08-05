"""IPE authoring, submission, return, amendment loop.

Difficulty queue (§1.8): non_linear_state_machine / ipe_amendment_cycle.
Corner queue (§1.9): state_machines + validations for the IPE lifecycle.
"""
from test_helpers import (
    validate_success, validate_error, get_success_data, api_client,
    setup_plan_development_case, setup_services_active_case, create_ipe_payload,
    TEST_USERS,
)

VRADMIN = TEST_USERS["vradmin_headers"]


# ─── Difficulty: IPE amendment cycle (APPROVED -> AMENDING -> APPROVED) ──

def test_ipe_amendment_cycle_returns_to_approved(api):
    """PRD §3.4: "A `Counselor` opens an `APPROVED` IPE for amendment, moving it to
    `AMENDING`. A `Supervisor` then re-approves, moving `AMENDING` back to
    `APPROVED`, again recording `approved_by_supervisor_id` and re-pinning
    `approved_plan_version` to the post-increment `version`; because the case is
    already `SERVICES_ACTIVE` or later, its status is left unchanged."

    Design: Difficulty/non_linear_state_machine/ipe_amendment_cycle
    """
    ctx = setup_services_active_case()
    amending = validate_success(api.amend_ipe(ctx["ipe_id"], ctx["counselor_headers"]), 200)
    assert amending["status"] == "AMENDING"
    reapproved = validate_success(api.approve_ipe(ctx["ipe_id"], ctx["supervisor_headers"]), 200)
    assert reapproved["status"] == "APPROVED"
    # Case remains SERVICES_ACTIVE (re-approval does not re-advance it).
    case = validate_success(api.get_case(ctx["case_id"], VRADMIN), 200)
    assert case["status"] == "SERVICES_ACTIVE"


def test_ipe_amendment_reapproval_bumps_approved_plan_version(api):
    """PRD §3.4: "A `Supervisor` then re-approves, moving `AMENDING` back to
    `APPROVED`, again recording `approved_by_supervisor_id` and re-pinning
    `approved_plan_version` to the post-increment `version`".

    Design: Difficulty/non_linear_state_machine/ipe_amendment_cycle
    """
    ctx = setup_services_active_case()
    before = validate_success(api.get_ipe(ctx["ipe_id"], VRADMIN), 200)
    first_pinned = before["approved_plan_version"]
    api.amend_ipe(ctx["ipe_id"], ctx["counselor_headers"])
    reapproved = validate_success(api.approve_ipe(ctx["ipe_id"], ctx["supervisor_headers"]), 200)
    assert reapproved["approved_plan_version"] > first_pinned
    assert reapproved["approved_plan_version"] == reapproved["version"]


# ─── Corner: IPE state-machine and validations ───────────────────────

def test_ipe_submit_twice_invalid_state(api):
    """PRD §3.4: "Submitting a `DRAFT` IPE is permitted only while the IPE is in
    `DRAFT` and its case is in `PLAN_DEVELOPMENT`; it advances the IPE to
    `SUBMITTED`."

    Design: Corner/state_machines/ipe_submit_twice_invalid_state
    """
    ctx = setup_plan_development_case()
    submitted = validate_success(api.submit_ipe(ctx["ipe_id"], ctx["counselor_headers"]), 200)
    assert submitted["status"] == "SUBMITTED"
    res = api.submit_ipe(ctx["ipe_id"], ctx["counselor_headers"])
    validate_error(res, "ERR_INVALID_STATE")
    still = validate_success(api.get_ipe(ctx["ipe_id"], VRADMIN), 200)
    assert still["status"] == "SUBMITTED"


def test_ipe_return_submitted_to_draft(api):
    """PRD §3.4: "A `Supervisor` reviews a `SUBMITTED` IPE and either returns it or
    approves it. Returning it moves it back to `DRAFT` for revision."

    Design: Corner/state_machines/ipe_return_submitted_to_draft
    """
    ctx = setup_plan_development_case()
    api.submit_ipe(ctx["ipe_id"], ctx["counselor_headers"])
    returned = validate_success(api.return_ipe(ctx["ipe_id"], ctx["supervisor_headers"]), 200)
    assert returned["status"] == "DRAFT"
    case = validate_success(api.get_case(ctx["case_id"], VRADMIN), 200)
    assert case["status"] == "PLAN_DEVELOPMENT"


def test_second_active_ipe_rejected(api):
    """PRD §3.4: "A case may hold only one active IPE at a time; if the case already
    has an IPE in `DRAFT`, `SUBMITTED`, `APPROVED`, or `AMENDING`, creating another
    is rejected with `ERR_ACTIVE_IPE_EXISTS`."

    Design: Corner/validations/second_active_ipe_rejected
    """
    ctx = setup_plan_development_case()
    res = api.create_ipe(create_ipe_payload(ctx["case_id"], employment_goal="Cashier",
                                            goal_wage_target_cents=55000), ctx["counselor_headers"])
    validate_error(res, "ERR_ACTIVE_IPE_EXISTS")
