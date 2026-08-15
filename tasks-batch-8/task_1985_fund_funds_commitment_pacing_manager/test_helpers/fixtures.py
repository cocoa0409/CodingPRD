"""Composite setup helpers (multi-step fixtures).

Every fixture builds preconditions from scratch using only PRD-declared
endpoints (the runner restarts the server before every test, so each test
starts against an empty database). Fixtures use get_success_data() so setup
failures surface as clear "Setup failed" errors rather than confusing
assertion failures.

Identity threading: Analyst / InvestmentCommittee / OperationsAnalyst are
entity-backed roles — every call in those roles passes the StaffUser.id that
the fixture registered, via make_*_headers().
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    create_call_payload,
    create_distribution_payload,
    create_manager_payload,
    create_pacing_plan_payload,
    create_program_payload,
    create_proposal_payload,
    create_snapshot_payload,
    create_staff_payload,
    create_vehicle_payload,
)
from .test_users import (
    make_analyst_headers,
    make_cio_headers,
    make_ic_headers,
    make_ops_headers,
)


class Ctx(dict):
    """Attribute-access dict used as the fixture return container."""

    def __getattr__(self, item):
        try:
            return self[item]
        except KeyError as exc:  # pragma: no cover
            raise AttributeError(item) from exc

    def __setattr__(self, key, value):
        self[key] = value


# ---------------------------------------------------------------------------
# Tier 0: staff + program primitives
# ---------------------------------------------------------------------------

def register_staff(display_name="Staff", staff_role="ANALYST", email=None):
    """Register a StaffUser row (CIO-only endpoint). Returns the row dict."""
    payload = create_staff_payload(staff_role=staff_role, display_name=display_name)
    if email is not None:
        payload["email"] = email
    resp = api_client.create_staff_user(payload, make_cio_headers())
    return get_success_data(resp)


def make_staff_trio(prefix="s"):
    """Register one StaffUser per entity-backed role.

    Returns (analyst_headers, ic_headers, ops_headers, ids_dict).
    Emails are distinct per row so the SoD check never trips by accident.
    """
    ana = register_staff(f"Ana {prefix}", "ANALYST", f"ana.{prefix}.{id(object()) & 0xffff}@x.com")
    ic = register_staff(f"IC {prefix}", "IC_MEMBER", f"ic.{prefix}.{id(object()) & 0xffff}@x.com")
    ops = register_staff(f"Ops {prefix}", "OPS_ANALYST", f"ops.{prefix}.{id(object()) & 0xffff}@x.com")
    ids = {"analyst_id": ana["id"], "ic_id": ic["id"], "ops_id": ops["id"]}
    return (
        make_analyst_headers(ana["id"]),
        make_ic_headers(ic["id"]),
        make_ops_headers(ops["id"]),
        ids,
    )


def create_program_only(**overrides):
    """POST /fof/programs as CIO. Returns the program dict (status DRAFT)."""
    resp = api_client.create_program(create_program_payload(**overrides), make_cio_headers())
    return get_success_data(resp)


def contribute(program_id, amount, ops_headers, note=None, entry_kind="CONTRIBUTION"):
    """Append a manual ledger entry. Returns the CashLedgerEntry dict."""
    payload = {"entry_kind": entry_kind, "amount": amount}
    if note is not None:
        payload["note"] = note
    resp = api_client.create_ledger_entry(program_id, payload, ops_headers)
    return get_success_data(resp)


def create_funded_program(cash=20_000_000, ops_headers=None, **program_overrides):
    """Create program + post a CONTRIBUTION. Returns (program, entry)."""
    if ops_headers is None:
        _, _, ops_headers, _ = make_staff_trio("fp")
    program = create_program_only(**program_overrides)
    entry = contribute(program["id"], cash, ops_headers)
    return program, entry


def create_open_program(cash=20_000_000, ops_headers=None, **program_overrides):
    """Create program + CONTRIBUTION + open. Returns the OPEN program dict."""
    if ops_headers is None:
        _, _, ops_headers, _ = make_staff_trio("op")
    program, _ = create_funded_program(cash=cash, ops_headers=ops_headers, **program_overrides)
    resp = api_client.open_program(program["id"], make_cio_headers())
    return get_success_data(resp)


def get_program(program_id, headers=None):
    resp = api_client.get_program(program_id, headers or make_cio_headers())
    return get_success_data(resp)


def program_version(program_id, headers=None):
    return get_program(program_id, headers)["version"]


# ---------------------------------------------------------------------------
# Tier 1: pacing plan state progression
# ---------------------------------------------------------------------------

def create_plan(program_id, analyst_headers, **overrides):
    resp = api_client.create_pacing_plan(
        program_id, create_pacing_plan_payload(**overrides), analyst_headers
    )
    return get_success_data(resp)


def create_approved_plan(program_id, analyst_headers, **overrides):
    """Create + approve a pacing plan. Returns the APPROVED plan dict."""
    plan = create_plan(program_id, analyst_headers, **overrides)
    resp = api_client.approve_pacing_plan(program_id, plan["id"], make_cio_headers())
    return get_success_data(resp)


# ---------------------------------------------------------------------------
# Tier 2: manager + vehicle hierarchy and the diligence ladder
# ---------------------------------------------------------------------------

def create_manager(analyst_headers, **overrides):
    resp = api_client.create_manager(create_manager_payload(**overrides), analyst_headers)
    return get_success_data(resp)


def create_vehicle(manager_id, analyst_headers, **overrides):
    resp = api_client.create_vehicle(
        manager_id, create_vehicle_payload(**overrides), analyst_headers
    )
    return get_success_data(resp)


def get_latest_review(vehicle_id, analyst_headers):
    """Latest DD review for a vehicle (highest round_index)."""
    resp = api_client.list_dd_reviews(vehicle_id, analyst_headers)
    data = get_success_data(resp)
    rows = data if isinstance(data, list) else data.get("items", data)
    assert rows, f"Setup failed: no DD reviews for vehicle {vehicle_id}"
    return max(rows, key=lambda r: r["round_index"])


def score_and_submit_review(vehicle_id, review_id, analyst_headers, score=80):
    """Set all four scores and submit. Returns the SUBMITTED review."""
    api_client.update_dd_review(
        vehicle_id,
        review_id,
        {
            "score_strategy_fit": score,
            "score_track_record": score,
            "score_operations": score,
            "score_compliance": score,
        },
        analyst_headers,
    )
    resp = api_client.submit_dd_review(vehicle_id, review_id, analyst_headers)
    return get_success_data(resp)


def complete_review(vehicle_id, review_id, ic_headers):
    resp = api_client.complete_dd_review(vehicle_id, review_id, ic_headers)
    return get_success_data(resp)


def run_vehicle_to_approved(manager_id, vehicle_id, analyst_headers, ic_headers, score=80):
    """begin-diligence -> score -> submit -> complete -> approve-vehicle.

    Returns the APPROVED vehicle dict. Approving the first vehicle of a
    PROSPECT manager also promotes the manager to APPROVED (PRD §3.3).
    """
    resp = api_client.begin_diligence(manager_id, vehicle_id, analyst_headers)
    get_success_data(resp)
    review = get_latest_review(vehicle_id, analyst_headers)
    score_and_submit_review(vehicle_id, review["id"], analyst_headers, score=score)
    complete_review(vehicle_id, review["id"], ic_headers)
    resp = api_client.approve_vehicle(manager_id, vehicle_id, ic_headers)
    return get_success_data(resp)


def create_approved_vehicle(analyst_headers, ic_headers, score=80, **vehicle_overrides):
    """Manager + vehicle walked all the way to APPROVED. Returns (manager, vehicle)."""
    manager = create_manager(analyst_headers)
    vehicle = create_vehicle(manager["id"], analyst_headers, **vehicle_overrides)
    vehicle = run_vehicle_to_approved(manager["id"], vehicle["id"], analyst_headers, ic_headers, score=score)
    return manager, vehicle


# ---------------------------------------------------------------------------
# Tier 3: proposal lifecycle -> commitment
# ---------------------------------------------------------------------------

def create_proposal(vehicle_id, program_id, plan_id, analyst_headers, proposed_amount=10_000_000):
    resp = api_client.create_proposal(
        vehicle_id,
        create_proposal_payload(program_id, plan_id, proposed_amount),
        analyst_headers,
    )
    return get_success_data(resp)


def create_recommended_proposal(vehicle_id, program_id, plan_id, analyst_headers, proposed_amount=10_000_000):
    proposal = create_proposal(vehicle_id, program_id, plan_id, analyst_headers, proposed_amount)
    resp = api_client.recommend_proposal(proposal["id"], analyst_headers)
    return get_success_data(resp)


def create_ic_approved_proposal(vehicle_id, program_id, plan_id, analyst_headers, ic_headers, proposed_amount=10_000_000):
    proposal = create_recommended_proposal(
        vehicle_id, program_id, plan_id, analyst_headers, proposed_amount
    )
    resp = api_client.ic_approve_proposal(proposal["id"], ic_headers)
    return get_success_data(resp)


def commitment_for_proposal(proposal_id, headers):
    """The single Commitment spawned by an IC approval (list of 0 or 1)."""
    resp = api_client.list_proposal_commitments(proposal_id, headers)
    data = get_success_data(resp)
    rows = data if isinstance(data, list) else data.get("items", data)
    assert rows, f"Setup failed: no commitment spawned for proposal {proposal_id}"
    return rows[0]


# ---------------------------------------------------------------------------
# Tier 4: full-commitment scenarios (the workhorse fixture)
# ---------------------------------------------------------------------------

def setup_open_program_with_plan(cash=20_000_000, staff_prefix="w", plan_overrides=None, **program_overrides):
    """OPEN program + APPROVED pacing plan. Returns Ctx with headers and rows."""
    ana_h, ic_h, ops_h, ids = make_staff_trio(staff_prefix)
    program = create_open_program(cash=cash, ops_headers=ops_h, **program_overrides)
    plan = create_approved_plan(program["id"], ana_h, **(plan_overrides or {}))
    return Ctx(
        program=program,
        plan=plan,
        analyst_headers=ana_h,
        ic_headers=ic_h,
        ops_headers=ops_h,
        **ids,
    )


def setup_with_executed_commitment(
    cash=20_000_000,
    proposed_amount=10_000_000,
    sized_amount=None,
    staff_prefix="x",
    plan_overrides=None,
    vehicle_overrides=None,
    **program_overrides,
):
    """Full ladder: OPEN program + APPROVED plan + APPROVED vehicle +
    IC_APPROVED proposal + EXECUTED commitment.

    Returns Ctx(program, plan, manager, vehicle, proposal, commitment, headers...).
    """
    ctx = setup_open_program_with_plan(
        cash=cash, staff_prefix=staff_prefix, plan_overrides=plan_overrides, **program_overrides
    )
    manager, vehicle = create_approved_vehicle(
        ctx.analyst_headers, ctx.ic_headers, **(vehicle_overrides or {})
    )
    proposal = create_ic_approved_proposal(
        vehicle["id"], ctx.program["id"], ctx.plan["id"],
        ctx.analyst_headers, ctx.ic_headers, proposed_amount,
    )
    commitment = commitment_for_proposal(proposal["id"], ctx.ops_headers)
    pv = program_version(ctx.program["id"], ctx.ops_headers)
    resp = api_client.execute_commitment(
        ctx.program["id"],
        commitment["id"],
        {
            "sized_amount": sized_amount if sized_amount is not None else proposed_amount,
            "expected_program_version": pv,
        },
        ctx.ops_headers,
    )
    ctx.update(
        manager=manager,
        vehicle=vehicle,
        proposal=proposal,
        commitment=get_success_data(resp),
    )
    ctx.program = get_program(ctx.program["id"], ctx.ops_headers)
    return ctx


def issue_call(ctx, amount=1_000_000, purpose="INVESTMENT", due_date="2026-08-20T00:00:00Z"):
    """Issue a capital call against ctx.commitment. Returns the CapitalCall."""
    resp = api_client.create_capital_call(
        ctx.program["id"],
        ctx.commitment["id"],
        create_call_payload(amount=amount, purpose=purpose, due_date=due_date),
        ctx.ops_headers,
    )
    return get_success_data(resp)


def issue_and_pay_call(ctx, amount=1_000_000, purpose="INVESTMENT", due_date="2026-08-20T00:00:00Z"):
    """Issue + pay a capital call. Returns the PAID CapitalCall."""
    call = issue_call(ctx, amount=amount, purpose=purpose, due_date=due_date)
    resp = api_client.pay_call(call["id"], ctx.ops_headers)
    return get_success_data(resp)


def create_pending_distribution(ctx, amount=1_000_000, distribution_type="INCOME", received_at="2026-08-25T00:00:00Z"):
    resp = api_client.create_distribution(
        ctx.program["id"],
        ctx.commitment["id"],
        create_distribution_payload(
            amount=amount, distribution_type=distribution_type, received_at=received_at
        ),
        ctx.ops_headers,
    )
    return get_success_data(resp)


def record_snapshot(ctx, as_of_quarter="2026-Q3", reported_nav=10_500_000, commitment_id=None):
    resp = api_client.create_snapshot(
        commitment_id or ctx.commitment["id"],
        create_snapshot_payload(as_of_quarter=as_of_quarter, reported_nav=reported_nav),
        ctx.ops_headers,
    )
    return get_success_data(resp)


def advance_clock(ctx, to_iso8601):
    resp = api_client.set_current_utc({"to_iso8601": to_iso8601}, ctx.ops_headers)
    return get_success_data(resp)


# ---------------------------------------------------------------------------
# Tier 5: valuation-report-ready scenarios
# ---------------------------------------------------------------------------

def setup_report_scenario(staff_prefix="vr", nav=10_500_000, quarter="2026-Q3", **kwargs):
    """Executed commitment + one PROVISIONAL snapshot + OPEN valuation report.

    Returns Ctx with .report added.
    """
    ctx = setup_with_executed_commitment(staff_prefix=staff_prefix, **kwargs)
    advance_clock(ctx, "2026-10-15T00:00:00Z")
    ctx.snapshot = record_snapshot(ctx, as_of_quarter=quarter, reported_nav=nav)
    resp = api_client.create_valuation_report(
        ctx.program["id"], {"as_of_quarter": quarter}, ctx.ops_headers
    )
    ctx.report = get_success_data(resp)
    return ctx
