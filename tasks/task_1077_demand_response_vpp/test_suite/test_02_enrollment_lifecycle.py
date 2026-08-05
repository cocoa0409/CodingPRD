"""Enrollment activation, the opt-out / re-enroll cycle, and its ledger invariants.

Queue A: enrollment_active_optout_reenroll_cycle, enrollment_committed_kw_conserved,
enrollment_activate_requires_program_active.
Queue B: activate_active_program_rejected, duplicate_enrollment_rejected,
decommissioned_device_not_eligible_rejected.
"""
from test_helpers import (
    validate_success, validate_error, get_success_data,
    ApiErrorId, TEST_USERS,
    make_aggregator_headers, make_customer_headers,
    create_program_payload, create_enrollment_payload,
    onboard_aggregator, onboard_customer, create_program, register_device,
    enroll_active,
)
from test_helpers.api_client import api_client

OP = TEST_USERS["program_operator_headers"]


def _pending_enrollment(committed_kw=5, program_active=True, device_type="THERMOSTAT",
                        nameplate_kw=3, program_overrides=None):
    """Active-or-draft program + device + a freshly created PENDING enrollment."""
    agg = onboard_aggregator()
    cust = onboard_customer()
    prog = create_program(active=program_active, **(program_overrides or {}))
    dev = register_device(agg["id"], cust["id"], device_type=device_type,
                          nameplate_kw=nameplate_kw, capacity_kwh=None)
    agg_h = make_aggregator_headers(agg["id"])
    enr = get_success_data(api_client.create_enrollment(
        create_enrollment_payload(dev["id"], prog["id"], committed_kw), agg_h))
    return {"agg_id": agg["id"], "cust_id": cust["id"], "prog_id": prog["id"],
            "dev_id": dev["id"], "enr_id": enr["id"], "agg_h": agg_h, "enr": enr}


# --------------------------------------------------------------------------- #
# non_linear_state_machine / enrollment_active_optout_reenroll_cycle
# --------------------------------------------------------------------------- #
def test_enrollment_optout_reenroll_returns_to_active(api):
    """PRD §3.3: "Opting out is allowed only from ACTIVE status (else
    ERR_INVALID_STATE); it moves the enrollment to OPTED_OUT, increments its
    version by 1, and subtracts the pledged committed_kw from both
    Program.total_committed_kw and the aggregator's enrolled_committed_kw."
    PRD §3.3: "Re-enrollment is the inverse and is reserved to the Aggregator: it
    moves an OPTED_OUT enrollment back to ACTIVE, subject to the same
    aggregator-ownership check, the program being ACTIVE (else
    ERR_PROGRAM_NOT_ACTIVE), and the device being ACTIVE (else
    ERR_DEVICE_NOT_ELIGIBLE); it re-adds the committed_kw to both ledgers and
    increments version by 1."

    Design: Difficulty/non_linear_state_machine/enrollment_active_optout_reenroll_cycle
    """
    ctx = _pending_enrollment(committed_kw=5)
    get_success_data(api.activate_enrollment(ctx["enr_id"], ctx["agg_h"]))
    opted = validate_success(api.opt_out_enrollment(ctx["enr_id"], make_customer_headers(ctx["cust_id"])))
    assert opted["status"] == "OPTED_OUT"
    reenr = validate_success(api.re_enroll_enrollment(ctx["enr_id"], ctx["agg_h"]))
    assert reenr["status"] == "ACTIVE", "cycle must close back to ACTIVE"


def test_enrollment_cycle_version_advances_to_four(api):
    """PRD §2.4: "The version starts at 1 when the resource is created and
    increments by exactly 1 on every mutation that the workflow narratives below
    describe as bumping the version; updated_at is refreshed to the current
    logical-clock instant on each such mutation."

    Design: Difficulty/non_linear_state_machine/enrollment_active_optout_reenroll_cycle
    """
    ctx = _pending_enrollment(committed_kw=5)
    assert ctx["enr"]["version"] == 1, "create -> version 1"
    get_success_data(api.activate_enrollment(ctx["enr_id"], ctx["agg_h"]))
    get_success_data(api.opt_out_enrollment(ctx["enr_id"], make_customer_headers(ctx["cust_id"])))
    final = validate_success(api.re_enroll_enrollment(ctx["enr_id"], ctx["agg_h"]))
    # create 1 -> activate 2 -> opt-out 3 -> re-enroll 4
    assert final["version"] == 4, f"expected version 4 after the cycle, got {final['version']}"


# --------------------------------------------------------------------------- #
# compensating_invariant / enrollment_committed_kw_conserved_on_optout_reenroll
# --------------------------------------------------------------------------- #
def test_optout_debits_program_committed_kw(api):
    """PRD §2.9: "Program.total_committed_kw always equals the sum of committed_kw
    over that program's enrollments currently in ACTIVE status, and
    Aggregator.enrolled_committed_kw always equals the sum of committed_kw over
    the ACTIVE enrollments whose device belongs to that aggregator."

    Design: Difficulty/compensating_invariant/enrollment_committed_kw_conserved_on_optout_reenroll
    """
    ctx = _pending_enrollment(committed_kw=5)
    get_success_data(api.activate_enrollment(ctx["enr_id"], ctx["agg_h"]))
    before = validate_success(api.get_program(ctx["prog_id"], OP))
    assert before["total_committed_kw"] == 5.0
    get_success_data(api.opt_out_enrollment(ctx["enr_id"], make_customer_headers(ctx["cust_id"])))
    mid = validate_success(api.get_program(ctx["prog_id"], OP))
    assert mid["total_committed_kw"] == 0.0, "opt-out must debit the pledged capacity"


def test_reenroll_restores_committed_kw_without_drift(api):
    """PRD §3.3: "Because opt-out subtracts exactly what activation added and
    re-enrollment re-adds exactly that amount, the pledged capacity is conserved
    across any number of opt-out/re-enroll cycles."

    Design: Difficulty/compensating_invariant/enrollment_committed_kw_conserved_on_optout_reenroll
    """
    ctx = _pending_enrollment(committed_kw=5)
    get_success_data(api.activate_enrollment(ctx["enr_id"], ctx["agg_h"]))
    get_success_data(api.opt_out_enrollment(ctx["enr_id"], make_customer_headers(ctx["cust_id"])))
    get_success_data(api.re_enroll_enrollment(ctx["enr_id"], ctx["agg_h"]))
    after = validate_success(api.get_program(ctx["prog_id"], OP))
    assert after["total_committed_kw"] == 5.0, "re-enroll must credit back exactly, no drift"


# --------------------------------------------------------------------------- #
# cross_entity_state_dependency / enrollment_activate_requires_program_active
# --------------------------------------------------------------------------- #
def test_activate_enrollment_rejected_when_program_draft(api):
    """PRD §3.3: "The target program must be in ACTIVE status, else
    ERR_PROGRAM_NOT_ACTIVE (HTTP 409)."

    Design: Difficulty/cross_entity_state_dependency/enrollment_activate_requires_program_active
    """
    ctx = _pending_enrollment(committed_kw=5, program_active=False)
    resp = api.activate_enrollment(ctx["enr_id"], ctx["agg_h"])
    validate_error(resp, ApiErrorId.ERR_PROGRAM_NOT_ACTIVE.value)


def test_activate_enrollment_under_draft_program_leaves_enrollment_pending(api):
    """PRD §3.3: "On success the enrollment becomes ACTIVE, its own version
    increments by 1, and the pledged committed_kw is added to both
    Program.total_committed_kw and the owning Aggregator.enrolled_committed_kw."

    Design: Difficulty/cross_entity_state_dependency/enrollment_activate_requires_program_active
    """
    ctx = _pending_enrollment(committed_kw=5, program_active=False)
    api.activate_enrollment(ctx["enr_id"], ctx["agg_h"])
    still = validate_success(api.get_enrollment(ctx["enr_id"], OP))
    assert still["status"] == "PENDING", "refused activation must not change status"
    assert still["version"] == 1, "refused activation must not bump version"


# --------------------------------------------------------------------------- #
# Corner: state_machines / activate_active_program_rejected
# --------------------------------------------------------------------------- #
def test_activate_already_active_program_rejected(api):
    """PRD §3.1: "Activation is refused with ERR_INVALID_STATE unless the program
    is currently DRAFT."

    Design: Corner/state_machines/activate_active_program_rejected
    """
    prog = get_success_data(api.create_program(create_program_payload(name="P"), OP))
    get_success_data(api.activate_program(prog["id"], OP))
    resp = api.activate_program(prog["id"], OP)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


# --------------------------------------------------------------------------- #
# Corner: state_machines / duplicate_enrollment_rejected
# --------------------------------------------------------------------------- #
def test_duplicate_active_enrollment_rejected(api):
    """PRD §3.3: "And no other enrollment for the same device_id and program_id
    pair may already be ACTIVE, else ERR_DUPLICATE_ENROLLMENT (HTTP 409)."

    Design: Corner/state_machines/duplicate_enrollment_rejected
    """
    agg = onboard_aggregator()
    cust = onboard_customer()
    prog = create_program(active=True)
    dev = register_device(agg["id"], cust["id"], capacity_kwh=20)
    agg_h = make_aggregator_headers(agg["id"])
    enroll_active(dev["id"], prog["id"], agg["id"], committed_kw=5)
    enr2 = get_success_data(api.create_enrollment(
        create_enrollment_payload(dev["id"], prog["id"], 3), agg_h))
    resp = api.activate_enrollment(enr2["id"], agg_h)
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_ENROLLMENT.value)


# --------------------------------------------------------------------------- #
# Corner: state_machines / decommissioned_device_not_eligible_rejected
# --------------------------------------------------------------------------- #
def test_activate_enrollment_on_decommissioned_device_rejected(api):
    """PRD §3.3: "The device must be in ACTIVE status, else ERR_DEVICE_NOT_ELIGIBLE
    (HTTP 409)."

    Design: Corner/state_machines/decommissioned_device_not_eligible_rejected
    """
    agg = onboard_aggregator()
    cust = onboard_customer()
    prog = create_program(active=True)
    dev = register_device(agg["id"], cust["id"], capacity_kwh=20)
    agg_h = make_aggregator_headers(agg["id"])
    enr = get_success_data(api.create_enrollment(
        create_enrollment_payload(dev["id"], prog["id"], 5), agg_h))
    get_success_data(api.decommission_device(dev["id"], agg_h))
    resp = api.activate_enrollment(enr["id"], agg_h)
    validate_error(resp, ApiErrorId.ERR_DEVICE_NOT_ELIGIBLE.value)
