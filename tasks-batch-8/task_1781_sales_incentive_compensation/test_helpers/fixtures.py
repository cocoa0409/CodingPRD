"""Composite setup helpers.

Every test starts against an empty database (the harness restarts the server
before each test), so these helpers build complete precondition chains out of
PRD-declared endpoints only. Setup calls use the lenient get_success_data()
validator so a failed precondition raises a clear "Setup step failed" error.

Identity threading: Rep calls are identity-backed by the Rep entity, so every
accept/decline/dispute call is made with make_rep_headers(rep["id"]) built
from the real entity id — never the shared fallback constant.
"""
from prd_bench_local_runner.testing import get_success_data, validate_paginated

from .api_client import api_client
from .constants import (
    ANALYST_USER_ID,
    DEFAULT_QUOTA_CENTS,
    DEFAULT_TRANSACTION_DATE,
    MANAGER_USER_ID,
    PLAN_CREATOR_USER_ID,
    PLAN_PUBLISHER_USER_ID,
)
from .factories import (
    close_period_payload,
    create_adjustment_payload,
    create_assignment_payload,
    create_dispute_payload,
    create_payroll_export_payload,
    create_plan_payload,
    create_program_payload,
    create_rep_payload,
    create_transaction_payload,
    revise_plan_payload,
)
from .test_users import (
    TEST_USERS,
    make_comp_admin_headers,
    make_comp_analyst_headers,
    make_comp_manager_headers,
    make_rep_headers,
)

ADMIN = TEST_USERS["comp_admin_headers"]
ADMIN_ALT = TEST_USERS["comp_admin_alt_headers"]
ANALYST = TEST_USERS["comp_analyst_headers"]
MANAGER = TEST_USERS["comp_manager_headers"]


# ---------------------------------------------------------------------------
# Tier 1: single-resource creation and reads
# ---------------------------------------------------------------------------

def create_program(name="Test Program"):
    """Create a program. Returns the program (period 1, accrual 0)."""
    resp = api_client.create_program(create_program_payload(name=name), ADMIN)
    return get_success_data(resp)


def get_program(program_id):
    resp = api_client.get_program(program_id, ADMIN)
    return get_success_data(resp)


def create_plan(program_id, *, creator_user_id=PLAN_CREATOR_USER_ID,
                **overrides):
    """Create a DRAFT plan (document_version 1) as the given creator."""
    payload = create_plan_payload(program_id, **overrides)
    headers = make_comp_admin_headers(creator_user_id)
    resp = api_client.create_plan(payload, headers)
    return get_success_data(resp)


def publish_plan(plan_id, *, publisher_user_id=PLAN_PUBLISHER_USER_ID):
    """Publish a DRAFT plan as an operator other than the creator."""
    headers = make_comp_admin_headers(publisher_user_id)
    resp = api_client.publish_plan(plan_id, headers)
    return get_success_data(resp)


def create_published_plan(program_id, *, creator_user_id=PLAN_CREATOR_USER_ID,
                          publisher_user_id=PLAN_PUBLISHER_USER_ID,
                          **overrides):
    """Create + publish a plan. Returns the PUBLISHED plan."""
    plan = create_plan(program_id, creator_user_id=creator_user_id,
                       **overrides)
    return publish_plan(plan["id"], publisher_user_id=publisher_user_id)


def revise_plan(plan_id, expected_plan_version, *,
                reviser_user_id=PLAN_PUBLISHER_USER_ID, **fields):
    """Issue a new plan document version as a non-creator operator."""
    headers = make_comp_admin_headers(reviser_user_id)
    payload = revise_plan_payload(expected_plan_version, **fields)
    resp = api_client.revise_plan(plan_id, payload, headers)
    return get_success_data(resp)


def archive_plan(plan_id):
    resp = api_client.archive_plan(plan_id, ADMIN)
    return get_success_data(resp)


def create_rep(program_id, name, employee_ref, manager_id=None):
    overrides = {}
    if manager_id is not None:
        overrides["manager_id"] = manager_id
    payload = create_rep_payload(program_id, name, employee_ref, **overrides)
    resp = api_client.create_rep(payload, ADMIN)
    return get_success_data(resp)


def create_assignment(program_id, rep_id, plan_id, *,
                      quota_cents=DEFAULT_QUOTA_CENTS, **overrides):
    """Create an assignment (status ACTIVE, acceptance OFFERED)."""
    payload = create_assignment_payload(program_id, rep_id, plan_id,
                                        quota_cents=quota_cents, **overrides)
    resp = api_client.create_assignment(payload, ADMIN)
    return get_success_data(resp)


def get_assignment(assignment_id):
    resp = api_client.get_assignment(assignment_id, ADMIN)
    return get_success_data(resp)


def accept_assignment(assignment_id, rep_id):
    """Owning rep accepts the current plan document."""
    resp = api_client.accept_assignment(assignment_id, make_rep_headers(rep_id))
    return get_success_data(resp)


def decline_assignment(assignment_id, rep_id):
    resp = api_client.decline_assignment(assignment_id,
                                         make_rep_headers(rep_id))
    return get_success_data(resp)


def terminate_assignment(assignment_id):
    resp = api_client.terminate_assignment(assignment_id, ADMIN)
    return get_success_data(resp)


def book_transaction(program_id, external_ref, amount_cents, splits, *,
                     transaction_date=DEFAULT_TRANSACTION_DATE,
                     analyst_user_id=ANALYST_USER_ID):
    """Book a transaction. Returns the BOOKED transaction."""
    payload = create_transaction_payload(
        program_id, external_ref, amount_cents, splits,
        transaction_date=transaction_date)
    resp = api_client.create_transaction(
        payload, make_comp_analyst_headers(analyst_user_id))
    return get_success_data(resp)


def cancel_transaction(transaction_id, *, analyst_user_id=ANALYST_USER_ID):
    resp = api_client.cancel_transaction(
        transaction_id, make_comp_analyst_headers(analyst_user_id))
    return get_success_data(resp)


def close_period(program_id, expected_program_version=None):
    """Close the program's current open period (OCC-guarded).

    When expected_program_version is omitted the program's live version is
    read first, so routine closes never trip the stale-version guard.
    Returns the post-close program.
    """
    if expected_program_version is None:
        expected_program_version = get_program(program_id)["version"]
    resp = api_client.close_period(
        program_id, close_period_payload(expected_program_version), ADMIN)
    return get_success_data(resp)


def advance_periods(program_id, count):
    """Close `count` periods in sequence. Returns the final program."""
    program = None
    for _ in range(count):
        program = close_period(program_id)
    return program


def create_manual_adjustment(assignment_id, amount_cents, reason,
                             *, analyst_user_id=ANALYST_USER_ID):
    payload = create_adjustment_payload(assignment_id, amount_cents, reason)
    resp = api_client.create_adjustment(
        payload, make_comp_analyst_headers(analyst_user_id))
    return get_success_data(resp)


def approve_adjustment(adjustment_id, *, manager_user_id=MANAGER_USER_ID):
    resp = api_client.approve_adjustment(
        adjustment_id, make_comp_manager_headers(manager_user_id))
    return get_success_data(resp)


def file_dispute(assignment_id, rep_id, period_index, reason,
                 requested_amount_cents, credit_entry_id=None):
    """Owning rep files a dispute. Returns the SUBMITTED dispute."""
    overrides = {}
    if credit_entry_id is not None:
        overrides["credit_entry_id"] = credit_entry_id
    payload = create_dispute_payload(assignment_id, period_index, reason,
                                     requested_amount_cents, **overrides)
    resp = api_client.create_dispute(payload, make_rep_headers(rep_id))
    return get_success_data(resp)


# ---------------------------------------------------------------------------
# Tier 2: filtered-list lookups
# ---------------------------------------------------------------------------

def _list_single(list_fn, params, description):
    data, _meta = validate_paginated(list_fn(ADMIN, params=params))
    assert len(data) == 1, (
        f"Expected exactly 1 {description} for {params}, got {len(data)}"
    )
    return data[0]


def list_credit_entries(**params):
    data, _meta = validate_paginated(
        api_client.list_credit_entries(ADMIN, params=params))
    return data


def get_only_credit_entry(**params):
    return _list_single(api_client.list_credit_entries, params, "credit entry")


def list_adjustments(**params):
    data, _meta = validate_paginated(
        api_client.list_adjustments(ADMIN, params=params))
    return data


def list_disputes(**params):
    data, _meta = validate_paginated(
        api_client.list_disputes(ADMIN, params=params))
    return data


def list_statements(**params):
    data, _meta = validate_paginated(
        api_client.list_statements(ADMIN, params=params))
    return data


def get_statement_for(assignment_id, period_index):
    """The unique statement of (assignment, period)."""
    return _list_single(api_client.list_statements,
                        {"assignment_id": assignment_id,
                         "period_index": period_index},
                        "payout statement")


# ---------------------------------------------------------------------------
# Tier 3: composite scenarios
# ---------------------------------------------------------------------------

def setup_program_with_plan(*, program_name="Test Program",
                            plan_name="Test Plan", publish=True,
                            creator_user_id=PLAN_CREATOR_USER_ID,
                            publisher_user_id=PLAN_PUBLISHER_USER_ID,
                            **plan_overrides):
    """Program + plan (PUBLISHED unless publish=False).

    Returns {"program", "plan"}.
    """
    program = create_program(program_name)
    if publish:
        plan = create_published_plan(
            program["id"], creator_user_id=creator_user_id,
            publisher_user_id=publisher_user_id, name=plan_name,
            **plan_overrides)
    else:
        plan = create_plan(program["id"], creator_user_id=creator_user_id,
                           name=plan_name, **plan_overrides)
    return {"program": program, "plan": plan}


def setup_assignment(program, plan, rep, *, accept=False,
                     quota_cents=DEFAULT_QUOTA_CENTS, **assignment_overrides):
    """Create the rep's assignment on the plan; optionally accept the doc."""
    assignment = create_assignment(program["id"], rep["id"], plan["id"],
                                   quota_cents=quota_cents,
                                   **assignment_overrides)
    if accept:
        assignment = accept_assignment(assignment["id"], rep["id"])
    return assignment


def setup_accepted_assignment(*, program_name="Test Program",
                              plan_name="Test Plan", rep_name="Test Rep",
                              employee_ref="R-1", quota_cents=DEFAULT_QUOTA_CENTS,
                              accept=True, plan_overrides=None,
                              assignment_overrides=None):
    """Program + PUBLISHED plan + one rep + assignment (ACCEPTED by default).

    Returns {"program", "plan", "rep", "assignment"}.
    """
    base = setup_program_with_plan(program_name=program_name,
                                   plan_name=plan_name,
                                   **(plan_overrides or {}))
    rep = create_rep(base["program"]["id"], rep_name, employee_ref)
    assignment = setup_assignment(base["program"], base["plan"], rep,
                                  accept=accept, quota_cents=quota_cents,
                                  **(assignment_overrides or {}))
    return {**base, "rep": rep, "assignment": assignment}


def setup_manager_rep(*, program_name="Test Program", plan_name="Test Plan",
                      rollup_rate_bps=None, attainment_mode=None,
                      curve_tiers=None,
                      manager_accepted=True, rep_accepted=True,
                      manager_ref="M-1", rep_ref="R-1",
                      quota_cents=DEFAULT_QUOTA_CENTS):
    """Program + PUBLISHED plan + manager M and rep R (R.manager = M), each
    with an assignment on the plan, accepted per the flags.

    Returns {"program", "plan", "manager", "rep", "manager_assignment",
    "rep_assignment"}.
    """
    plan_overrides = {}
    if rollup_rate_bps is not None:
        plan_overrides["rollup_rate_bps"] = rollup_rate_bps
    if attainment_mode is not None:
        plan_overrides["attainment_mode"] = attainment_mode
    if curve_tiers is not None:
        plan_overrides["curve_tiers"] = curve_tiers
    base = setup_program_with_plan(program_name=program_name,
                                   plan_name=plan_name, **plan_overrides)
    manager = create_rep(base["program"]["id"], "Manager", manager_ref)
    rep = create_rep(base["program"]["id"], "Rep", rep_ref,
                     manager_id=manager["id"])
    manager_assignment = setup_assignment(base["program"], base["plan"],
                                          manager, accept=manager_accepted,
                                          quota_cents=quota_cents)
    rep_assignment = setup_assignment(base["program"], base["plan"], rep,
                                      accept=rep_accepted,
                                      quota_cents=quota_cents)
    return {**base, "manager": manager, "rep": rep,
            "manager_assignment": manager_assignment,
            "rep_assignment": rep_assignment}


def setup_posted_credit(*, amount_cents=200000, external_ref="T-1",
                        transaction_date=DEFAULT_TRANSACTION_DATE,
                        accept=True, **scenario_kwargs):
    """Accepted rep + one transaction booked 100% to the rep.

    With accept=True the DIRECT credit lands POSTED immediately.
    Returns the scenario dict plus "transaction" and "credit".
    """
    sc = setup_accepted_assignment(accept=accept, **scenario_kwargs)
    transaction = book_transaction(
        sc["program"]["id"], external_ref, amount_cents,
        [{"rep_id": sc["rep"]["id"], "split_bps": 10000}],
        transaction_date=transaction_date)
    credit = get_only_credit_entry(transaction_id=transaction["id"],
                                   rep_id=sc["rep"]["id"])
    return {**sc, "transaction": transaction, "credit": credit}


def setup_closed_period(*, amount_cents=200000, **scenario_kwargs):
    """Posted credit + period close. Returns scenario dict plus "statement"
    (the DRAFT statement of period 1) and the post-close "program"."""
    sc = setup_posted_credit(amount_cents=amount_cents, **scenario_kwargs)
    program = close_period(sc["program"]["id"])
    statement = get_statement_for(sc["assignment"]["id"], 1)
    return {**sc, "program": program, "statement": statement}


def setup_exported_period(*, amount_cents=200000, **scenario_kwargs):
    """Full cycle: posted credit -> close -> statement approve -> payroll
    export. Returns scenario dict plus "statement" (now EXPORTED), "export",
    and the post-export "program"."""
    sc = setup_closed_period(amount_cents=amount_cents, **scenario_kwargs)
    resp = api_client.approve_statement(sc["statement"]["id"], MANAGER)
    approved = get_success_data(resp)
    export = get_success_data(api_client.create_payroll_export(
        create_payroll_export_payload(sc["program"]["id"], 1), ADMIN))
    program = get_program(sc["program"]["id"])
    return {**sc, "statement": approved, "export": export,
            "program": program}
