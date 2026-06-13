"""Composite setup helpers.

Every fixture builds its preconditions from scratch using only PRD-declared
endpoints, because the harness restarts the server (empty DB) before each test.
Setup calls use get_success_data() (lenient) so setup failures surface as clear
"Setup failed" errors rather than confusing assertion failures.

Identity threading: after creating a Supplier (entity_backed), any ownership-gated
call uses make_supplier_headers(supplier["id"]) — never the shared constant.
"""
from prd_bench_local_runner.testing import get_success_data
from .api_client import api_client
from .test_users import (
    TEST_USERS, make_supplier_headers,
)
from . import factories as F

PM = TEST_USERS["program_manager_headers"]
HM = TEST_USERS["hiring_manager_headers"]
FIN = TEST_USERS["finance_headers"]


# ---------------------------------------------------------------------------
# Tier 1: primitive creators
# ---------------------------------------------------------------------------

def create_program(**overrides) -> dict:
    """Create an ACTIVE program. Returns the program dict."""
    resp = api_client.create_program(F.create_program_payload(**overrides), PM)
    return get_success_data(resp)


def set_clock(program_id: str, to_iso8601: str) -> dict:
    """Set the program clock WITHOUT firing sweeps (seed helper, PRD §2.4)."""
    resp = api_client.set_clock(program_id, {"to_iso8601": to_iso8601}, PM)
    return get_success_data(resp)


def advance_clock(program_id: str, to_iso8601: str) -> dict:
    """Advance the program clock; fires time-gated sweeps (PRD §2.4)."""
    resp = api_client.advance_clock(program_id, {"to_iso8601": to_iso8601}, PM)
    return get_success_data(resp)


def create_supplier(program_id: str, **overrides) -> dict:
    resp = api_client.create_supplier(F.create_supplier_payload(program_id, **overrides), PM)
    return get_success_data(resp)


def create_worker(program_id: str, **overrides) -> dict:
    resp = api_client.create_worker(F.create_worker_payload(program_id, **overrides), PM)
    return get_success_data(resp)


def create_requisition(program_id: str, **overrides) -> dict:
    resp = api_client.create_requisition(F.create_requisition_payload(program_id, **overrides), PM)
    return get_success_data(resp)


def distribute(requisition_id: str, supplier_ids: list) -> dict:
    resp = api_client.distribute_requisition(
        requisition_id, {"supplier_ids": supplier_ids}, PM
    )
    return get_success_data(resp)


# ---------------------------------------------------------------------------
# Tier 2: distributed requisition with a fresh submittal
# ---------------------------------------------------------------------------

def setup_distributed_requisition(program_overrides=None, req_overrides=None):
    """Active program + one tier-1 supplier + one worker + a DISTRIBUTED
    requisition. Returns dict with program, supplier, worker, requisition,
    req_version (the version after distribute), and supplier_headers."""
    program = create_program(**(program_overrides or {}))
    supplier = create_supplier(program["id"])
    worker = create_worker(program["id"])
    requisition = create_requisition(program["id"], **(req_overrides or {}))
    dist = distribute(requisition["id"], [supplier["id"]])
    return {
        "program": program,
        "supplier": supplier,
        "worker": worker,
        "requisition": requisition,
        "req_version": dist["version"],
        "supplier_headers": make_supplier_headers(supplier["id"]),
    }


def create_submittal(requisition_id, supplier_id, worker_profile_id, **overrides) -> dict:
    """Create a SUBMITTED submittal as the owning supplier."""
    headers = make_supplier_headers(supplier_id)
    resp = api_client.create_submittal(
        F.create_submittal_payload(requisition_id, supplier_id, worker_profile_id, **overrides),
        headers,
    )
    return get_success_data(resp)


def setup_submitted_submittal(program_overrides=None, req_overrides=None, submittal_overrides=None):
    """DISTRIBUTED requisition + one SUBMITTED submittal. Returns the
    setup_distributed_requisition dict plus 'submittal'."""
    base = setup_distributed_requisition(program_overrides, req_overrides)
    submittal = create_submittal(
        base["requisition"]["id"], base["supplier"]["id"], base["worker"]["id"],
        **(submittal_overrides or {}),
    )
    base["submittal"] = submittal
    return base


def _advance_submittal_to_offered(submittal_id, supplier_headers, propose_overrides=None):
    """Walk a SUBMITTED submittal: shortlist -> start_interview -> propose_rate
    -> offer. Leaves it OFFERED."""
    get_success_data(api_client.shortlist_submittal(submittal_id, HM))
    get_success_data(api_client.start_interview(submittal_id, HM))
    propose = propose_overrides or {"pay_rate_cents": F.DEFAULTS["PAY_RATE_CENTS"]}
    get_success_data(api_client.propose_rate(submittal_id, propose, supplier_headers))
    get_success_data(api_client.offer_submittal(submittal_id, HM))


def setup_offered_submittal(program_overrides=None, req_overrides=None,
                            submittal_overrides=None, propose_overrides=None):
    """DISTRIBUTED requisition + one OFFERED submittal. Returns the
    setup_submitted_submittal dict plus the submittal at OFFERED. Re-reads the
    requisition version after the offer (offer does not bump version, but the
    caller may want the current value)."""
    base = setup_submitted_submittal(program_overrides, req_overrides, submittal_overrides)
    _advance_submittal_to_offered(
        base["submittal"]["id"], base["supplier_headers"], propose_overrides,
    )
    req = get_success_data(api_client.get_requisition(base["requisition"]["id"], PM))
    base["req_version"] = req["version"]
    return base


# ---------------------------------------------------------------------------
# Tier 3: hired -> live assignment
# ---------------------------------------------------------------------------

def setup_active_assignment(program_overrides=None, req_overrides=None,
                            start_date="2026-01-01T00:00:00.000Z",
                            planned_end_date="2026-06-01T00:00:00.000Z",
                            clock_iso=None):
    """Full lifecycle through a live ACTIVE Assignment. If clock_iso is given,
    the program clock is seeded (no sweeps) before hire so start_date math is
    deterministic. Returns the setup_offered_submittal dict plus 'assignment'."""
    base = setup_offered_submittal(program_overrides, req_overrides)
    if clock_iso is not None:
        set_clock(base["program"]["id"], clock_iso)
    resp = api_client.hire_submittal(
        base["submittal"]["id"],
        F.hire_payload(base["req_version"], start_date, planned_end_date),
        PM,
    )
    base["submittal"] = get_success_data(resp)
    # The hire returns the submittal; find the created assignment for this worker.
    assignments = get_success_data(
        api_client.list_assignments(PM, params={"worker_profile_id": base["worker"]["id"]})
    )
    base["assignment"] = assignments[0] if isinstance(assignments, list) else assignments
    return base


def setup_active_assignment_with_draft_timesheet(week_start_date="2026-01-05T00:00:00.000Z",
                                                 timesheet_overrides=None,
                                                 program_overrides=None,
                                                 clock_iso=None):
    """ACTIVE assignment + one DRAFT timesheet. Returns the setup_active_assignment
    dict plus 'timesheet'."""
    base = setup_active_assignment(program_overrides=program_overrides, clock_iso=clock_iso,
                                   planned_end_date="2026-12-01T00:00:00.000Z")
    payload = F.create_timesheet_payload(base["assignment"]["id"], week_start_date,
                                         **(timesheet_overrides or {}))
    resp = api_client.create_timesheet(payload, base["supplier_headers"])
    base["timesheet"] = get_success_data(resp)
    return base


def setup_submitted_timesheet(week_start_date="2026-01-05T00:00:00.000Z",
                              timesheet_overrides=None, program_overrides=None,
                              clock_iso=None):
    """ACTIVE assignment + one SUBMITTED timesheet. Returns the dict plus
    'timesheet' (SUBMITTED)."""
    base = setup_active_assignment_with_draft_timesheet(
        week_start_date, timesheet_overrides, program_overrides, clock_iso,
    )
    resp = api_client.submit_timesheet(base["timesheet"]["id"], base["supplier_headers"])
    base["timesheet"] = get_success_data(resp)
    return base


def setup_active_assignment_with_submitted_expense(category="MEALS", amount_cents=6000,
                                                   program_overrides=None):
    """ACTIVE assignment + one SUBMITTED expense. Returns the dict plus 'expense'."""
    base = setup_active_assignment(program_overrides=program_overrides,
                                   planned_end_date="2026-12-01T00:00:00.000Z")
    resp = api_client.create_expense(
        F.create_expense_payload(base["assignment"]["id"], category, amount_cents),
        base["supplier_headers"],
    )
    expense = get_success_data(resp)
    submitted = get_success_data(
        api_client.submit_expense(expense["id"], base["supplier_headers"])
    )
    base["expense"] = submitted
    return base


# ---------------------------------------------------------------------------
# Tier 4: SOW + milestones
# ---------------------------------------------------------------------------

def setup_draft_sow(total_value_cents=100000, program_overrides=None):
    """DRAFT SOW with an eligible supplier (no milestones). Returns dict with
    program, supplier, sow, supplier_headers."""
    program = create_program(**(program_overrides or {}))
    supplier = create_supplier(program["id"])
    resp = api_client.create_sow(
        F.create_sow_payload(program["id"], supplier["id"], total_value_cents=total_value_cents),
        PM,
    )
    sow = get_success_data(resp)
    return {
        "program": program,
        "supplier": supplier,
        "sow": sow,
        "supplier_headers": make_supplier_headers(supplier["id"]),
    }


def add_milestone(sow_id, name, milestone_amount_cents, sequence) -> dict:
    resp = api_client.create_milestone(
        F.create_milestone_payload(sow_id, name=name,
                                   milestone_amount_cents=milestone_amount_cents,
                                   sequence=sequence),
        PM,
    )
    return get_success_data(resp)


def setup_active_sow(milestones, total_value_cents=100000, program_overrides=None):
    """ACTIVE SOW with the given milestones. `milestones` is a list of
    (name, amount_cents, sequence). Returns setup_draft_sow dict plus
    'milestones' (list of created milestone dicts, in input order)."""
    base = setup_draft_sow(total_value_cents, program_overrides)
    created = [add_milestone(base["sow"]["id"], n, amt, seq) for (n, amt, seq) in milestones]
    get_success_data(api_client.activate_sow(base["sow"]["id"], PM))
    base["milestones"] = created
    return base


def setup_accepted_milestone(amount_cents=50000, total_value_cents=100000):
    """ACTIVE SOW + a single milestone walked to ACCEPTED. Returns the
    setup_active_sow dict; 'milestones'[0] is the ACCEPTED milestone."""
    base = setup_active_sow([("M1", amount_cents, 1)], total_value_cents)
    m = base["milestones"][0]
    sh = base["supplier_headers"]
    get_success_data(api_client.start_milestone(m["id"], sh))
    get_success_data(api_client.submit_milestone(m["id"], sh))
    get_success_data(api_client.accept_milestone(m["id"], HM))
    base["milestones"][0] = get_success_data(api_client.get_milestone(m["id"], PM))
    return base
