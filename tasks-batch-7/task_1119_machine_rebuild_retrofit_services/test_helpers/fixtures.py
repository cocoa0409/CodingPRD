"""Composite setup helpers for multi-step test prerequisites.

Every helper builds its preconditions from scratch through PRD-declared
endpoints, because the harness restarts the server (and therefore empties the
database) before every individual test. Setup calls use the lenient
``get_success_data`` validator so a broken precondition reports as a setup
failure rather than a confusing assertion failure.
"""
from types import SimpleNamespace

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    PASSING_SAMPLES,
    create_assessment_payload,
    create_begin_training_payload,
    create_customer_payload,
    create_decision_payload,
    create_downtime_window_payload,
    create_fabricate_payload,
    create_machine_payload,
    create_part_line_payload,
    create_part_payload,
    create_quote_payload,
    create_record_payload,
    create_shipment_stage_payload,
    create_trade_in_offer_payload,
    create_warranty_claim_payload,
)
from .test_users import (
    ADMIN,
    LOGISTICS,
    PM,
    WARRANTY_ADMIN,
    make_assessor_headers,
    make_customer_headers,
    make_engineer_headers,
    make_inspector_headers,
    make_trainer_headers,
)

# Opaque operator identifiers used across fixtures (PRD §2.1).
ASSESSOR_1 = "assessor-1"
ENGINEER_1 = "eng-1"      # the project's assigned rebuild engineer
FABRICATOR = "eng-2"      # RE-job fabricator, distinct from the validator
INSPECTOR_1 = "qi-1"      # acceptance inspector, distinct from the engineer
TRAINER_1 = "tr-1"

DELIVERY_CLOCK = "2026-06-01T00:00:00Z"
PAST_WARRANTY_CLOCK = "2027-07-01T00:00:00Z"


# ─── Tier 0: primitive builders ───────────────────────


def set_clock(to_iso8601: str) -> dict:
    """Advance the logical clock; PlatformAdmin only (PRD §2.7)."""
    return get_success_data(api_client.set_clock(to_iso8601, ADMIN))


def create_customer(**overrides) -> dict:
    return get_success_data(api_client.create_customer(create_customer_payload(**overrides), ADMIN))


def create_machine(customer_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_machine(create_machine_payload(customer_id, **overrides), ADMIN)
    )


def get_machine(machine_id: str) -> dict:
    return get_success_data(api_client.get_machine(machine_id, PM))


def create_part(**overrides) -> dict:
    return get_success_data(api_client.create_part(create_part_payload(**overrides), ADMIN))


def get_part(part_id: str) -> dict:
    return get_success_data(api_client.get_part(part_id, PM))


def get_project(project_id: str) -> dict:
    return get_success_data(api_client.get_project(project_id, PM))


def get_stage(stage_id: str) -> dict:
    return get_success_data(api_client.get_shipment_stage(stage_id, LOGISTICS))


def get_window(window_id: str) -> dict:
    return get_success_data(api_client.get_downtime_window(window_id, LOGISTICS))


# ─── Tier 1: assessment → project birth ───────────────


def create_assessment(machine_id: str, assessor_id: str = ASSESSOR_1, **overrides) -> dict:
    """Create an assessment against the machine's current version (PRD §2.6 OCC)."""
    machine = get_machine(machine_id)
    return get_success_data(
        api_client.create_assessment(
            machine_id,
            create_assessment_payload(machine["version"], **overrides),
            make_assessor_headers(assessor_id),
        )
    )


def submit_assessment(assessment_id: str, assessor_id: str = ASSESSOR_1) -> dict:
    return get_success_data(
        api_client.submit_assessment(assessment_id, make_assessor_headers(assessor_id))
    )


def accept_assessment(assessment_id: str) -> dict:
    return get_success_data(api_client.accept_assessment(assessment_id, PM))


def find_project_for_assessment(assessment_id: str) -> dict:
    """The cascade-created project is reachable through the filtered list (PRD §3.3)."""
    resp = api_client.list_projects(PM, params={"assessment_id": assessment_id})
    items = resp.json()["data"]
    assert len(items) == 1, f"expected exactly one project for assessment {assessment_id}"
    return items[0]


def find_training_record_for_project(project_id: str) -> dict:
    resp = api_client.list_training_records(PM, params={"project_id": project_id})
    items = resp.json()["data"]
    assert len(items) == 1, f"expected exactly one training record for project {project_id}"
    return items[0]


def find_re_jobs_for_project(project_id: str) -> list:
    resp = api_client.list_re_jobs(PM, params={"project_id": project_id})
    return resp.json()["data"]


def setup_project_scoped(
    pd: float = 10, sr: float = 8, bl: float = 6,
    assessor_id: str = ASSESSOR_1, customer_overrides=None, machine_overrides=None,
) -> SimpleNamespace:
    """Customer + machine + accepted assessment + auto-created SCOPED project."""
    customer = create_customer(**(customer_overrides or {}))
    machine = create_machine(customer["id"], **(machine_overrides or {}))
    assessment = create_assessment(
        machine["id"], assessor_id=assessor_id,
        positioning_deviation_microns=pd, spindle_runout_microns=sr, backlash_microns=bl,
    )
    submit_assessment(assessment["id"], assessor_id=assessor_id)
    assessment = accept_assessment(assessment["id"])
    project = find_project_for_assessment(assessment["id"])
    return SimpleNamespace(
        customer=customer, machine=machine, assessment=assessment, project=project,
        assessor_id=assessor_id,
    )


# ─── Tier 2: decision, bill of materials, quote ───────

# Default parts plan: one ACTIVE part, quantity 1 at 1,250,000 cents.
DEFAULT_PARTS_SPEC = [
    {"oem_status": "ACTIVE", "unit_cost_cents": 1_250_000, "stock_quantity": 10, "quantity": 1},
]


def record_decision(project_id: str, decision: str = "MECHANICAL_REBUILD",
                    engineer_id: str = ENGINEER_1, decision_reason=None) -> dict:
    payload = create_decision_payload(decision=decision, assigned_engineer_id=engineer_id)
    if decision_reason is not None:
        payload["decision_reason"] = decision_reason
    return get_success_data(api_client.record_decision(project_id, payload, PM))


def add_part_line(project_id: str, part_id: str, quantity: int) -> dict:
    return get_success_data(
        api_client.add_part_line(project_id, create_part_line_payload(part_id, quantity=quantity), PM)
    )


def setup_project_decided(
    decision: str = "MECHANICAL_REBUILD", parts_spec=None, decision_reason=None,
    engineer_id: str = ENGINEER_1, **kwargs,
) -> SimpleNamespace:
    """SCOPED project + decision recorded + part lines added (project DECIDED).

    parts_spec: list of dicts with keys oem_status, unit_cost_cents,
    stock_quantity, quantity (plus optional part_number / description).
    """
    ctx = setup_project_scoped(**kwargs)
    project = record_decision(ctx.project["id"], decision=decision,
                              engineer_id=engineer_id, decision_reason=decision_reason)
    ctx.project = project
    ctx.decision = decision
    ctx.engineer_id = engineer_id
    ctx.parts = []
    ctx.lines = []
    for spec in (parts_spec if parts_spec is not None else DEFAULT_PARTS_SPEC):
        spec = dict(spec)
        quantity = spec.pop("quantity")
        part = create_part(**spec)
        line = add_part_line(project["id"], part["id"], quantity)
        ctx.parts.append(part)
        ctx.lines.append(line)
    return ctx


def compute_quote(project_id: str) -> dict:
    """Recompute the quote against the project's current version (PRD §2.6 OCC)."""
    project = get_project(project_id)
    return get_success_data(
        api_client.compute_quote(project_id, create_quote_payload(project["version"]), PM)
    )


def send_quote(project_id: str) -> dict:
    return get_success_data(api_client.send_quote(project_id, PM))


def approve_quote(project_id: str, customer_id: str) -> dict:
    return get_success_data(api_client.approve_quote(project_id, make_customer_headers(customer_id)))


def setup_project_quoted(**kwargs) -> SimpleNamespace:
    """DECIDED project with one computed quote (commercial QUOTE_DRAFT)."""
    ctx = setup_project_decided(**kwargs)
    ctx.project = compute_quote(ctx.project["id"])
    return ctx


def setup_project_approved(**kwargs) -> SimpleNamespace:
    """Quoted project sent and approved by its customer (commercial APPROVED)."""
    ctx = setup_project_quoted(**kwargs)
    ctx.project = send_quote(ctx.project["id"])
    ctx.project = approve_quote(ctx.project["id"], ctx.customer["id"])
    return ctx


# ─── Tier 3: sourcing, rebuild, acceptance ────────────


def fulfill_line(line_id: str) -> dict:
    return get_success_data(api_client.fulfill_part_line(line_id, LOGISTICS))


def complete_re_jobs(project_id: str, fabricator_id: str = FABRICATOR,
                     validator_id: str = INSPECTOR_1, re_cost_cents: int = 500_000) -> list:
    """Walk every spawned reverse-engineering job to VALIDATED (PRD §3.4)."""
    jobs = []
    for job in find_re_jobs_for_project(project_id):
        get_success_data(api_client.capture_spec(job["id"], make_engineer_headers(fabricator_id)))
        get_success_data(
            api_client.fabricate(
                job["id"], create_fabricate_payload(re_cost_cents=re_cost_cents),
                make_engineer_headers(fabricator_id),
            )
        )
        job = get_success_data(api_client.validate_re_job(job["id"], make_inspector_headers(validator_id)))
        jobs.append(job)
    return jobs


def setup_project_sourced(complete_re: bool = True, **kwargs) -> SimpleNamespace:
    """APPROVED project with sourcing opened; ACTIVE lines fulfilled and RE jobs
    validated (unless complete_re=False), so all lines are terminal."""
    ctx = setup_project_approved(**kwargs)
    ctx.project = get_success_data(api_client.begin_sourcing(ctx.project["id"], PM))
    for line in ctx.lines:
        refreshed = get_success_data(api_client.get_part_line(line["id"], PM))
        if refreshed["status"] == "RESERVED":
            fulfill_line(line["id"])
    if complete_re:
        ctx.re_jobs = complete_re_jobs(ctx.project["id"])
    return ctx


def setup_project_rebuild_in_progress(**kwargs) -> SimpleNamespace:
    ctx = setup_project_sourced(**kwargs)
    ctx.project = get_success_data(api_client.start_rebuild(ctx.project["id"], PM))
    return ctx


def declare_ready(project_id: str, engineer_id: str = ENGINEER_1) -> dict:
    return get_success_data(api_client.declare_ready(project_id, make_engineer_headers(engineer_id)))


def setup_project_awaiting_acceptance(**kwargs) -> SimpleNamespace:
    ctx = setup_project_rebuild_in_progress(**kwargs)
    ctx.project = declare_ready(ctx.project["id"], engineer_id=ctx.engineer_id)
    return ctx


def schedule_acceptance_test(project_id: str, inspector_id: str = INSPECTOR_1) -> dict:
    return get_success_data(
        api_client.create_acceptance_test(project_id, make_inspector_headers(inspector_id))
    )


def record_test(test_id: str, samples=None, repeatability: float = 5.0,
                inspector_id: str = INSPECTOR_1) -> dict:
    return get_success_data(
        api_client.record_acceptance_test(
            test_id,
            create_record_payload(samples=samples, repeatability_microns=repeatability),
            make_inspector_headers(inspector_id),
        )
    )


def setup_scheduled_test(inspector_id: str = INSPECTOR_1, **kwargs) -> SimpleNamespace:
    """Project AWAITING_ACCEPTANCE with one SCHEDULED acceptance test."""
    ctx = setup_project_awaiting_acceptance(**kwargs)
    ctx.test = schedule_acceptance_test(ctx.project["id"], inspector_id=inspector_id)
    ctx.inspector_id = inspector_id
    return ctx


def setup_project_accepted(samples=None, repeatability: float = 5.0, **kwargs) -> SimpleNamespace:
    """Project driven through a passing acceptance record (work ACCEPTED)."""
    ctx = setup_scheduled_test(**kwargs)
    ctx.test = record_test(ctx.test["id"], samples=samples or PASSING_SAMPLES,
                           repeatability=repeatability, inspector_id=ctx.inspector_id)
    ctx.project = get_project(ctx.project["id"])
    return ctx


# ─── Tier 4: training and handover ────────────────────


def setup_project_handover_ready(trainer_id: str = TRAINER_1, **kwargs) -> SimpleNamespace:
    """ACCEPTED project with training completed (work HANDOVER_READY)."""
    ctx = setup_project_accepted(**kwargs)
    record = get_success_data(
        api_client.begin_training(
            ctx.project["id"], create_begin_training_payload(trainer_id=trainer_id), PM
        )
    )
    for _ in range(record["sessions_required"]):
        record = get_success_data(api_client.log_session(record["id"], make_trainer_headers(trainer_id)))
    record = get_success_data(
        api_client.deliver_documentation(record["id"], make_trainer_headers(trainer_id))
    )
    ctx.training_record = record
    ctx.trainer_id = trainer_id
    ctx.project = get_project(ctx.project["id"])
    return ctx


# ─── Tier 5: windows, stages, delivery into warranty ──


def create_window(customer_id: str, starts_at: str = "2026-06-01T00:00:00Z",
                  ends_at: str = "2026-07-01T00:00:00Z") -> dict:
    return get_success_data(
        api_client.create_downtime_window(
            create_downtime_window_payload(customer_id, starts_at=starts_at, ends_at=ends_at),
            LOGISTICS,
        )
    )


def create_stage(project_id: str, window_id: str, stage_sequence: int = 1,
                 ship: str = "2026-06-10T00:00:00Z", ret: str = "2026-06-15T00:00:00Z") -> dict:
    return get_success_data(
        api_client.create_shipment_stage(
            project_id,
            create_shipment_stage_payload(
                window_id, stage_sequence=stage_sequence,
                planned_ship_date=ship, planned_return_date=ret,
            ),
            LOGISTICS,
        )
    )


def ship_receive_install(stage_id: str) -> dict:
    get_success_data(api_client.ship_stage(stage_id, LOGISTICS))
    get_success_data(api_client.receive_stage(stage_id, LOGISTICS))
    return get_success_data(api_client.install_stage(stage_id, LOGISTICS))


def setup_project_delivered(delivery_clock: str = DELIVERY_CLOCK, **kwargs) -> SimpleNamespace:
    """Full lifecycle through delivery: HANDOVER_READY + one INSTALLED stage,
    clock pinned, project delivered into WARRANTY_ACTIVE."""
    ctx = setup_project_handover_ready(**kwargs)
    window = create_window(ctx.customer["id"])
    stage = create_stage(ctx.project["id"], window["id"])
    ship_receive_install(stage["id"])
    set_clock(delivery_clock)
    ctx.window = window
    ctx.stage = get_stage(stage["id"])
    ctx.project = get_success_data(api_client.deliver_project(ctx.project["id"], PM))
    return ctx


# ─── Trade-in helpers ─────────────────────────────────


def create_offer(machine_id: str, valuation_variant: str = "MARKET_COMPARABLE") -> dict:
    """Create a trade-in offer against the machine's current version (§2.6 OCC)."""
    machine = get_machine(machine_id)
    return get_success_data(
        api_client.create_trade_in_offer(
            machine_id,
            create_trade_in_offer_payload(machine["version"], valuation_variant=valuation_variant),
            PM,
        )
    )


def accept_offer(offer_id: str, customer_id: str) -> dict:
    return get_success_data(
        api_client.accept_trade_in_offer(offer_id, make_customer_headers(customer_id))
    )


def setup_accepted_offer(machine_overrides=None, valuation_variant: str = "COST_APPROACH",
                         customer=None) -> SimpleNamespace:
    """A standalone machine with an ACCEPTED trade-in offer on it."""
    customer = customer or create_customer()
    machine = create_machine(customer["id"], **(machine_overrides or {}))
    offer = create_offer(machine["id"], valuation_variant=valuation_variant)
    offer = accept_offer(offer["id"], customer["id"])
    return SimpleNamespace(customer=customer, machine=machine, offer=offer)


# ─── Warranty claim helpers ───────────────────────────


def file_claim(project_id: str, customer_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_warranty_claim(
            project_id, create_warranty_claim_payload(**overrides),
            make_customer_headers(customer_id),
        )
    )


def adjudicate_claim(claim_id: str, action: str = "approve", notes=None) -> dict:
    payload = {} if notes is None else {"resolution_notes": notes}
    method = {
        "approve": api_client.approve_claim,
        "reject": api_client.reject_claim,
        "remediate": api_client.remediate_claim,
    }[action]
    return get_success_data(method(claim_id, payload, WARRANTY_ADMIN))
