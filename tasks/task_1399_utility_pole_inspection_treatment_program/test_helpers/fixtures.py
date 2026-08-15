"""Composite setup helpers.

Every helper builds preconditions from scratch using only PRD-declared
endpoints (each test runs against a freshly restarted server with an empty
database). Setup calls use get_success_data so failures surface as clear
"Setup failed" errors. Ownership-gated Contractor calls always thread the real
ContractorCrew.id through make_contractor_headers (PRD §2.1).
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    adjudicate_claim_payload,
    create_budget_payload,
    create_crew_payload,
    create_cycle_payload,
    create_inspection_task_payload,
    create_pole_payload,
    create_replacement_order_payload,
    create_treatment_order_payload,
    create_warranty_claim_payload,
    fund_order_payload,
    schedule_treatment_payload,
    set_clock_payload,
    submit_task_payload,
)
from .test_users import TEST_USERS, make_contractor_headers

_PM = TEST_USERS["program_manager_headers"]
_INSP = TEST_USERS["inspector_headers"]
_QA = TEST_USERS["qa_reviewer_headers"]


def _fail(step, resp):
    raise AssertionError(f"Setup failed at {step}: HTTP {resp.status_code} {resp.text}")


def _ok(step, resp, expected_status=None):
    data = get_success_data(resp)
    if expected_status is not None and isinstance(data, dict):
        status = data.get("status")
        assert status == expected_status, (
            f"Setup failed at {step}: expected status {expected_status}, got {status}"
        )
    return data


# ---------------------------------------------------------------------------
# Tier 1 — foundational resources (budget / pole / crew / cycle)
# ---------------------------------------------------------------------------

def create_budget(fiscal_year=2026, total_cents=1_000_000):
    resp = api_client.create_budget(
        create_budget_payload(fiscal_year=fiscal_year, total_cents=total_cents), _PM
    )
    return _ok("create_budget", resp)


def create_pole(**overrides):
    resp = api_client.create_pole(create_pole_payload(**overrides), _PM)
    return _ok("create_pole", resp, expected_status="IN_SERVICE")


def create_crew(crew_code=None, region="NW"):
    overrides = {}
    if crew_code is not None:
        overrides["crew_code"] = crew_code
    resp = api_client.create_contractor_crew(
        create_crew_payload(region=region, **overrides), _PM
    )
    return _ok("create_contractor_crew", resp, expected_status="ACTIVE")


def create_cycle(year=2026, cycle_length_years=10, sample_pct=0,
                 strength_variant_policy="CONSERVATIVE", **overrides):
    resp = api_client.create_inspection_cycle(
        create_cycle_payload(
            year=year,
            cycle_length_years=cycle_length_years,
            sample_pct=sample_pct,
            strength_variant_policy=strength_variant_policy,
            **overrides,
        ),
        _PM,
    )
    return _ok("create_inspection_cycle", resp, expected_status="DRAFT")


def open_cycle(cycle_id):
    resp = api_client.open_inspection_cycle(cycle_id, _PM)
    return _ok("open_inspection_cycle", resp, expected_status="OPEN")


def create_open_cycle(**kwargs):
    """Create a cycle and open it (PRD §3.2). Returns the OPEN cycle."""
    cycle = create_cycle(**kwargs)
    return open_cycle(cycle["id"])


def set_clock(to_iso8601):
    resp = api_client.set_current_utc(set_clock_payload(to_iso8601), _PM)
    return _ok("set_current_utc", resp)


def reconcile_cycle(cycle_id, budget_id):
    resp = api_client.reconcile_inspection_cycle(cycle_id, {"budget_id": budget_id}, _PM)
    return _ok("reconcile_inspection_cycle", resp, expected_status="RECONCILED")


# ---------------------------------------------------------------------------
# Tier 2 — inspection tasks: create / submit / review
# ---------------------------------------------------------------------------

def create_manual_task(cycle_id, pole_id,
                       due_window_start="2026-08-10T00:00:00Z",
                       due_window_end="2026-08-20T00:00:00Z"):
    resp = api_client.create_inspection_task(
        create_inspection_task_payload(
            cycle_id, pole_id,
            due_window_start=due_window_start, due_window_end=due_window_end,
        ),
        _PM,
    )
    return _ok("create_inspection_task", resp, expected_status="OPEN")


def setup_open_cycle_with_task(pole_overrides=None, cycle_overrides=None,
                               due_window_start="2026-08-10T00:00:00Z",
                               due_window_end="2026-08-20T00:00:00Z"):
    """Open cycle (sample_pct 0 by default) + pole + one manual OPEN task."""
    pole = create_pole(**(pole_overrides or {}))
    cycle = create_open_cycle(**(cycle_overrides or {}))
    task = create_manual_task(cycle["id"], pole["id"],
                              due_window_start=due_window_start,
                              due_window_end=due_window_end)
    return pole, cycle, task


def submit_task(task_id, inspector_headers=None, **submit_overrides):
    resp = api_client.submit_inspection_task(
        task_id, submit_task_payload(**submit_overrides), inspector_headers or _INSP
    )
    return _ok("submit_inspection_task", resp, expected_status="SUBMITTED")


def qa_review_task(task_id, decision, qa_headers=None, **payload_overrides):
    payload = {"decision": decision}
    payload.update(payload_overrides)
    resp = api_client.qa_review_inspection_task(task_id, payload, qa_headers or _QA)
    return _ok("qa_review_inspection_task", resp)


def submit_and_accept_task(task_id, inspector_headers=None, qa_headers=None,
                           **submit_overrides):
    submitted = submit_task(task_id, inspector_headers=inspector_headers,
                            **submit_overrides)
    accepted = qa_review_task(task_id, "ACCEPT", qa_headers=qa_headers)
    assert accepted["status"] == "ACCEPTED", (
        f"Setup failed at accept: expected ACCEPTED, got {accepted['status']}"
    )
    return submitted, accepted


def setup_accepted_pole(pole_overrides=None, cycle_overrides=None,
                        submit_overrides=None):
    """Pole + open cycle + task submitted and ACCEPTED. Returns (pole, cycle, task)."""
    pole, cycle, task = setup_open_cycle_with_task(
        pole_overrides=pole_overrides, cycle_overrides=cycle_overrides
    )
    _, accepted = submit_and_accept_task(task["id"], **(submit_overrides or {}))
    pole = _ok("get_pole", api_client.get_pole(pole["id"], _PM))
    return pole, cycle, accepted


# ---------------------------------------------------------------------------
# Tier 3 — treatment pipeline: create -> schedule -> apply -> qa
# ---------------------------------------------------------------------------

def create_treatment_order(pole_id, product_code="CCA_WRAP", cost_cents=17500):
    resp = api_client.create_treatment_work_order(
        create_treatment_order_payload(
            pole_id, product_code=product_code, cost_cents=cost_cents
        ),
        _PM,
    )
    return _ok("create_treatment_work_order", resp, expected_status="CREATED")


def schedule_treatment(order_id, crew_id, work_start_date="2026-08-10",
                       work_end_date="2026-08-12"):
    resp = api_client.schedule_treatment_work_order(
        order_id,
        schedule_treatment_payload(
            crew_id, work_start_date=work_start_date, work_end_date=work_end_date
        ),
        _PM,
    )
    return _ok("schedule_treatment_work_order", resp, expected_status="SCHEDULED")


def apply_treatment(order_id, crew_id):
    """Apply as the owning crew (Contractor identity == ContractorCrew.id)."""
    resp = api_client.apply_treatment_work_order(
        order_id, make_contractor_headers(crew_id)
    )
    return _ok("apply_treatment_work_order", resp, expected_status="APPLIED")


def qa_review_treatment(order_id, decision, qa_headers=None, **payload_overrides):
    payload = {"decision": decision}
    payload.update(payload_overrides)
    resp = api_client.qa_review_treatment_work_order(order_id, payload, qa_headers or _QA)
    return _ok("qa_review_treatment_work_order", resp)


def drive_treatment_to_qa(pole_id, crew_id, decision, product_code="CCA_WRAP",
                          cost_cents=17500, work_start_date="2026-08-10",
                          work_end_date="2026-08-12"):
    """Full pipeline: CREATED -> SCHEDULED -> APPLIED -> qa decision. Returns the order."""
    order = create_treatment_order(pole_id, product_code=product_code, cost_cents=cost_cents)
    schedule_treatment(order["id"], crew_id,
                       work_start_date=work_start_date, work_end_date=work_end_date)
    apply_treatment(order["id"], crew_id)
    reviewed = qa_review_treatment(order["id"], decision)
    expected = "VERIFIED" if decision == "PASS" else "FAILED_QA"
    assert reviewed["status"] == expected, (
        f"Setup failed at treatment qa: expected {expected}, got {reviewed['status']}"
    )
    return reviewed


def setup_crew_with_qa_history(decisions, crew_code=None, product_code="CCA_WRAP",
                               cost_cents=17500, work_start_date="2026-08-10",
                               work_end_date="2026-08-12"):
    """Crew + pole + one decided treatment order per entry in `decisions`
    (chronological order). Returns (crew, pole, orders)."""
    crew = create_crew(crew_code=crew_code)
    pole = create_pole()
    orders = [
        drive_treatment_to_qa(
            pole["id"], crew["id"], decision,
            product_code=product_code, cost_cents=cost_cents,
            work_start_date=work_start_date, work_end_date=work_end_date,
        )
        for decision in decisions
    ]
    return crew, pole, orders


def create_verified_treatment(pole_id, crew_id, product_code="CCA_WRAP",
                              cost_cents=17500, work_start_date="2026-08-10",
                              work_end_date="2026-08-12"):
    """Treatment order driven to VERIFIED (PASS). Returns the order."""
    return drive_treatment_to_qa(
        pole_id, crew_id, "PASS",
        product_code=product_code, cost_cents=cost_cents,
        work_start_date=work_start_date, work_end_date=work_end_date,
    )


# ---------------------------------------------------------------------------
# Tier 4 — warranty claims and attachment audits
# ---------------------------------------------------------------------------

def file_claim(treatment_order_id, claim_reason="DECAY_RECURRENCE"):
    resp = api_client.create_warranty_claim(
        create_warranty_claim_payload(treatment_order_id, claim_reason=claim_reason), _PM
    )
    return _ok("create_warranty_claim", resp, expected_status="FILED")


def setup_verified_order_with_claim(product_code="PENTA_GEL", cost_cents=21000,
                                    claim_reason="DECAY_RECURRENCE"):
    """Pole + crew + VERIFIED treatment order + one FILED claim."""
    pole = create_pole()
    crew = create_crew()
    order = create_verified_treatment(pole["id"], crew["id"],
                                      product_code=product_code, cost_cents=cost_cents)
    claim = file_claim(order["id"], claim_reason=claim_reason)
    return pole, crew, order, claim


def list_claims_for_order(order_id):
    resp = api_client.list_warranty_claims_for_order(order_id, _PM)
    return _ok("list_warranty_claims_for_order", resp)


def adjudicate_claim(claim_id, outcome, **payload_overrides):
    resp = api_client.adjudicate_warranty_claim(
        claim_id, adjudicate_claim_payload(outcome, **payload_overrides), _PM
    )
    return _ok("adjudicate_warranty_claim", resp)


def list_audits(params=None):
    resp = api_client.list_attachment_audits(_PM, params=params)
    return _ok("list_attachment_audits", resp)


def get_audit_for_task(task_id):
    data = list_audits(params={"inspection_task_id": task_id})
    assert len(data) >= 1, f"Setup failed: no attachment audit found for task {task_id}"
    return data[0]


def setup_submitted_joint_use_task(found_attachment_count, declared=2,
                                   pole_overrides=None):
    """Joint-use pole + open cycle + task submitted with found_attachment_count,
    which auto-creates the AttachmentAudit (PRD §3.7). Returns (pole, cycle, task, audit)."""
    overrides = {"joint_use": True, "attachment_count_declared": declared}
    overrides.update(pole_overrides or {})
    pole, cycle, task = setup_open_cycle_with_task(pole_overrides=overrides)
    submit_task(task["id"], found_attachment_count=found_attachment_count)
    audit = get_audit_for_task(task["id"])
    return pole, cycle, task, audit


def setup_notified_audit(found_attachment_count=3, declared=1, accept_task=True):
    """Joint-use audit driven to violation NOTIFIED (PRD §3.7).

    Submits (auto-creating the audit), optionally ACCEPTs the task so the cycle
    can later reconcile, then adjudicates the audit. Returns (pole, cycle, task, audit)."""
    pole, cycle, task, audit = setup_submitted_joint_use_task(
        found_attachment_count, declared=declared
    )
    if accept_task:
        qa_review_task(task["id"], "ACCEPT")
    resp = api_client.adjudicate_attachment_audit(audit["id"], _PM)
    audit = _ok("adjudicate_attachment_audit", resp)
    assert audit["violation_status"] == "NOTIFIED", (
        f"Setup failed: expected NOTIFIED violation, got {audit['violation_status']}"
    )
    return pole, cycle, task, audit


# ---------------------------------------------------------------------------
# Tier 5 — replacement queue, funding, reconcile
# ---------------------------------------------------------------------------

def create_replacement_order(pole_id, estimated_cost_cents=200000):
    resp = api_client.create_replacement_work_order(
        create_replacement_order_payload(pole_id, estimated_cost_cents=estimated_cost_cents),
        _PM,
    )
    return _ok("create_replacement_work_order", resp, expected_status="QUEUED")


def fund_order(order_id, budget_id, expected_budget_version):
    resp = api_client.fund_replacement_work_order(
        order_id, fund_order_payload(budget_id, expected_budget_version), _PM
    )
    return _ok("fund_replacement_work_order", resp, expected_status="FUNDED")


def get_order(order_id):
    return _ok("get_replacement_work_order",
               api_client.get_replacement_work_order(order_id, _PM))


def get_budget(budget_id):
    return _ok("get_budget", api_client.get_budget(budget_id, _PM))


def get_pole(pole_id):
    pid = pole_id["id"] if isinstance(pole_id, dict) else pole_id
    return _ok("get_pole", api_client.get_pole(pid, _PM))


def get_task(task_id):
    return _ok("get_inspection_task", api_client.get_inspection_task(task_id, _PM))


def get_cycle(cycle_id):
    return _ok("get_inspection_cycle", api_client.get_inspection_cycle(cycle_id, _PM))


def get_crew(crew_id):
    return _ok("get_contractor_crew", api_client.get_contractor_crew(crew_id, _PM))


def get_treatment(order_id):
    return _ok("get_treatment_work_order",
               api_client.get_treatment_work_order(order_id, _PM))


def get_snapshots_for_cycle(cycle_id):
    resp = api_client.list_backlog_snapshots(_PM, params={"cycle_id": cycle_id})
    return _ok("list_backlog_snapshots", resp)
