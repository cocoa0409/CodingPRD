"""Transitive cascades: participant exit (plan close -> voucher cancel -> fund release)
and provider suspension (program suspend -> draft voucher cancel)."""
from test_helpers import (
    validate_success, ApiErrorId,
    setup_obligated_voucher, setup_training_ready, create_voucher,
    ADMIN, CM, ANY,
)


# --- Participant exit cascade ---
def test_exit_closes_plan_and_cancels_obligated_voucher(api):
    """PRD §2.9: "every `CareerPlan` of that participant currently in `ACTIVE` or
    `UNDER_REVISION` transitions to `CLOSED`; as each plan closes, every `ITAVoucher` of
    the participant that references that plan and is currently `OBLIGATED` transitions to
    `CANCELLED`, and the un-expended remainder of each such voucher is released back into
    the area's available budget."

    Design: Difficulty/transitive_cascade/participant_exit_closes_plan_cancels_voucher_releases_funds
    """
    ctx = setup_obligated_voucher(api, authorized_cost_cents=800000)
    exited = validate_success(api.exit_participant(ctx["p_id"], CM))
    assert exited["enrollment_status"] == "EXITED", exited
    plan = validate_success(api.get_career_plan(ctx["cp_id"], ANY))
    assert plan["status"] == "CLOSED", plan
    voucher = validate_success(api.get_voucher(ctx["v_id"], ANY))
    assert voucher["status"] == "CANCELLED", voucher


def test_exit_cascade_releases_obligated_funds(api):
    """PRD §2.9: "the un-expended remainder of each such voucher is released back into the
    area's available budget."

    Design: Difficulty/transitive_cascade/participant_exit_closes_plan_cancels_voucher_releases_funds
    """
    ctx = setup_obligated_voucher(api, authorized_cost_cents=800000)  # total 5,000,000
    validate_success(api.exit_participant(ctx["p_id"], CM))
    area = validate_success(api.get_local_area(ctx["la_id"], ANY))
    assert area["ita_budget_available_cents"] == 5000000, area
    assert area["ita_budget_obligated_cents"] == 0, area


# --- Provider suspension cascade ---
def test_suspend_provider_suspends_its_program(api):
    """PRD §2.9: "When a training provider is suspended, every `TrainingProgram` offered by
    that provider transitions from `ACTIVE` to `SUSPENDED`".

    Design: Difficulty/transitive_cascade/provider_suspend_suspends_program_cancels_draft_voucher
    """
    ctx = setup_training_ready(api)
    create_voucher(api, ctx["p_id"], ctx["prog_id"], ctx["cp_id"], authorized_cost_cents=100000)
    provider = validate_success(api.suspend_provider(ctx["prov_id"], ADMIN))
    assert provider["etpl_status"] == "SUSPENDED", provider
    program = validate_success(api.get_program(ctx["prog_id"], ANY))
    assert program["status"] == "SUSPENDED", program


def test_suspend_provider_cancels_draft_voucher(api):
    """PRD §2.9: "as each program is suspended, every `ITAVoucher` referencing that program
    that is still in `DRAFT` transitions to `CANCELLED`. Draft vouchers hold no obligation,
    so no funds move during this cascade."

    Design: Difficulty/transitive_cascade/provider_suspend_suspends_program_cancels_draft_voucher
    """
    ctx = setup_training_ready(api)
    v = create_voucher(api, ctx["p_id"], ctx["prog_id"], ctx["cp_id"], authorized_cost_cents=100000)
    validate_success(api.suspend_provider(ctx["prov_id"], ADMIN))
    voucher = validate_success(api.get_voucher(v["id"], ANY))
    assert voucher["status"] == "CANCELLED", voucher
