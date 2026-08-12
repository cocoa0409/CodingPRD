"""Composite setup helpers for multi-step test preconditions.

Every helper builds its state from scratch through PRD-declared endpoints
(the harness restarts the server before every test, so nothing carries over).
Setup calls use get_success_data() so a setup failure surfaces as a clear
"Setup step failed" error rather than a confusing assertion failure.

Grade discipline: when a test raises an order's cleanliness grade, the lot
certificate, tool grade, and spec grade must rise with it (PRD §2.5/§3.5) —
pass the matching overrides at the call site.
"""
from prd_bench_local_runner.testing import get_success_data, validate_paginated

from .api_client import api_client
from .constants import (
    CERT_ISSUED_AT,
    CERT_EXPIRES_AT,
    INSPECTOR_1,
    INSPECTOR_2,
    PLANNER_1,
    PLANNER_2,
)
from .factories import (
    create_approve_production_payload,
    create_assembly_task_payload,
    create_batch_decide_payload,
    create_cleanliness_certificate_payload,
    create_clock_payload,
    create_disposition_payload,
    create_forming_run_payload,
    create_machine_resource_payload,
    create_material_allocation_payload,
    create_material_lot_payload,
    create_packaging_spec_payload,
    create_production_order_payload,
    create_quality_inspection_payload,
    create_regrind_batch_payload,
    create_run_complete_payload,
    create_scrap_certify_payload,
    create_spec_decide_payload,
    create_stage_payload,
    create_tool_payload,
)
from .test_users import (
    TEST_USERS,
    make_inspector_headers,
    make_planner_headers,
)

_PLANNER = TEST_USERS["materials_planner_headers"]
_ENGINEER = TEST_USERS["tooling_engineer_headers"]
_PACKAGING = TEST_USERS["packaging_engineer_headers"]
_MANAGER = TEST_USERS["plant_manager_headers"]
_SCHEDULER = TEST_USERS["production_scheduler_headers"]
_INSPECTOR = TEST_USERS["quality_inspector_headers"]
_ANY = TEST_USERS["any_headers"]


# ─── Certificates and the logical clock (PRD §2.5) ──────────────────────────

def issue_certificate(subject_type, subject_id, grade,
                      issued_at=CERT_ISSUED_AT, expires_at=CERT_EXPIRES_AT,
                      cert_body="LabA"):
    """Issue a cleanliness certificate for a lot / batch / tool / spec."""
    payload = create_cleanliness_certificate_payload(
        subject_type, subject_id,
        grade=grade, issued_at=issued_at, expires_at=expires_at, cert_body=cert_body,
    )
    return get_success_data(api_client.create_cleanliness_certificate(payload, _INSPECTOR))


def set_logical_clock(to_iso8601):
    """Advance the server logical clock (PRD §2.5). Returns the new reading."""
    data = get_success_data(api_client.set_current_utc(create_clock_payload(to_iso8601), _ANY))
    return data


# ─── Material lots (PRD §3.1) ───────────────────────────────────────────────

def create_lot(**lot_overrides):
    """Create a virgin lot (lands in QUARANTINE). Returns the lot."""
    return get_success_data(
        api_client.create_material_lot(create_material_lot_payload(**lot_overrides), _PLANNER)
    )


def create_certified_lot(cert_grade=None, **lot_overrides):
    """Create a lot and issue a certificate at grade >= its required grade,
    releasing it QUARANTINE -> CERTIFIED (PRD §3.1). Returns the lot."""
    payload = create_material_lot_payload(**lot_overrides)
    lot = get_success_data(api_client.create_material_lot(payload, _PLANNER))
    grade = cert_grade or payload["cleanliness_grade_required"]
    issue_certificate("MATERIAL_LOT", lot["id"], grade)
    return get_success_data(api_client.get_material_lot(lot["id"], _ANY))


def get_lot(lot_id):
    return get_success_data(api_client.get_material_lot(lot_id, _ANY))


# ─── Tools (PRD §3.3) ───────────────────────────────────────────────────────

def create_tool_draft(**tool_overrides):
    """Register a tool in DRAFT. Returns the tool."""
    return get_success_data(api_client.create_tool(create_tool_payload(**tool_overrides), _ENGINEER))


def create_tool_prototype(**tool_overrides):
    """DRAFT -> PROTOTYPE via complete-prototype. Returns the tool."""
    tool = create_tool_draft(**tool_overrides)
    return get_success_data(api_client.complete_prototype(tool["id"], _ENGINEER))


def create_tool_production(production_cost=8000.00, rated_lifetime_shots=80000,
                           with_cert=True, **tool_overrides):
    """Walk a tool DRAFT -> PROTOTYPE -> QUALIFICATION -> PRODUCTION, issuing a
    TOOL cleanliness certificate at the tool's grade (PRD §3.3 cert gate).
    Returns the PRODUCTION tool."""
    tool = create_tool_prototype(**tool_overrides)
    tool = get_success_data(api_client.submit_qualification(tool["id"], _ENGINEER))
    if with_cert:
        issue_certificate("TOOL", tool["id"], tool.get("cleanliness_grade", "INDUSTRIAL"))
    return get_success_data(
        api_client.approve_production(
            tool["id"],
            create_approve_production_payload(
                production_cost=production_cost,
                rated_lifetime_shots=rated_lifetime_shots,
            ),
            _ENGINEER,
        )
    )


def get_tool(tool_id):
    return get_success_data(api_client.get_tool(tool_id, _ANY))


# ─── Packaging specs (PRD §3.4) ─────────────────────────────────────────────

def create_stock_spec(**spec_overrides):
    """STOCK spec — born ACTIVE. Returns the spec."""
    spec_overrides.setdefault("spec_type", "STOCK")
    return get_success_data(
        api_client.create_packaging_spec(create_packaging_spec_payload(**spec_overrides), _PACKAGING)
    )


def create_custom_spec(**spec_overrides):
    """CUSTOM spec — born PENDING_APPROVAL. Returns the spec."""
    spec_overrides.setdefault("spec_type", "CUSTOM")
    return get_success_data(
        api_client.create_packaging_spec(create_packaging_spec_payload(**spec_overrides), _PACKAGING)
    )


def approve_custom_spec(spec, cert_grade=None):
    """Issue the PACKAGING_SPEC certificate and decide APPROVED (PRD §3.4)."""
    issue_certificate("PACKAGING_SPEC", spec["id"], cert_grade or spec["cleanliness_grade"])
    return get_success_data(
        api_client.decide_packaging_spec(spec["id"], create_spec_decide_payload("APPROVED"), _MANAGER)
    )


# ─── Machine resources (PRD §3.6) ───────────────────────────────────────────

def create_station(**overrides):
    """Register a FORMING_STATION. Returns the resource."""
    overrides.setdefault("resource_type", "FORMING_STATION")
    overrides.setdefault("machine_rate_per_hour", 55.00)
    return get_success_data(
        api_client.create_machine_resource(create_machine_resource_payload(**overrides), _SCHEDULER)
    )


def create_booth(**overrides):
    """Register an INSPECTION_BOOTH. Returns the resource."""
    overrides.setdefault("resource_type", "INSPECTION_BOOTH")
    overrides.setdefault("machine_rate_per_hour", 25.00)
    return get_success_data(
        api_client.create_machine_resource(create_machine_resource_payload(**overrides), _SCHEDULER)
    )


# ─── Production orders and allocations (PRD §3.5) ───────────────────────────

def create_order(tool, spec, **order_overrides):
    """Create a production order against the given tool/spec.

    part_number defaults to the tool's part number (PRD §3.5 match rule) and
    is_prototype_order defaults to true exactly when the tool is PROTOTYPE
    (PRD §3.5 prototype-order rule)."""
    order_overrides.setdefault("part_number", tool["part_number"])
    if "is_prototype_order" not in order_overrides:
        order_overrides["is_prototype_order"] = tool["status"] == "PROTOTYPE"
    payload = create_production_order_payload(tool["id"], spec["id"], **order_overrides)
    return get_success_data(api_client.create_production_order(payload, _SCHEDULER))


def get_order(order_id):
    return get_success_data(api_client.get_production_order(order_id, _ANY))


def order_version(order_id):
    return get_order(order_id)["version"]


def reserve_virgin(order_id, lot_id, qty_kg):
    """Reserve virgin lot mass against an order. Returns the allocation."""
    payload = create_material_allocation_payload(
        order_id, source_type="VIRGIN_LOT", lot_id=lot_id, qty_kg=qty_kg
    )
    return get_success_data(api_client.create_material_allocation(payload, _SCHEDULER))


def reserve_regrind(order_id, batch_id, qty_kg):
    """Reserve regrind batch mass against an order. Returns the allocation."""
    payload = create_material_allocation_payload(
        order_id, source_type="REGRIND", regrind_batch_id=batch_id, qty_kg=qty_kg
    )
    return get_success_data(api_client.create_material_allocation(payload, _SCHEDULER))


def get_allocation(allocation_id):
    return get_success_data(api_client.get_material_allocation(allocation_id, _ANY))


def stage_order(order_id):
    """Stage an order under OCC using its current version (PRD §2.7)."""
    version = order_version(order_id)
    return get_success_data(
        api_client.stage_order(order_id, create_stage_payload(version), _SCHEDULER)
    )


def setup_staged_order(alloc_qty_kg=5.900, tool_production=True,
                       production_cost=8000.00, rated_lifetime_shots=80000,
                       order_overrides=None, lot_overrides=None,
                       tool_overrides=None, spec_overrides=None,
                       lot_cert_grade=None):
    """Certified lot + tool (PROTOTYPE or PRODUCTION) + ACTIVE stock spec +
    order + one virgin allocation + stage.

    Returns dict(lot, tool, spec, order, allocation). `order` is the
    post-stage representation (STAGED)."""
    lot = create_certified_lot(cert_grade=lot_cert_grade, **(lot_overrides or {}))
    if tool_production:
        tool = create_tool_production(
            production_cost=production_cost,
            rated_lifetime_shots=rated_lifetime_shots,
            **(tool_overrides or {}),
        )
    else:
        tool = create_tool_prototype(**(tool_overrides or {}))
    spec = create_stock_spec(**(spec_overrides or {}))
    order = create_order(tool, spec, **(order_overrides or {}))
    allocation = reserve_virgin(order["id"], lot["id"], alloc_qty_kg)
    order = stage_order(order["id"])
    return {
        "lot": lot,
        "tool": tool,
        "spec": spec,
        "order": order,
        "allocation": allocation,
    }


# ─── Forming runs (PRD §3.6) ────────────────────────────────────────────────

def schedule_run(order_id, station_id, start="2026-05-02T10:00:00Z",
                 end="2026-05-02T10:30:00Z", **run_overrides):
    """Schedule a forming run on a station. Returns the SCHEDULED run."""
    payload = create_forming_run_payload(
        order_id, station_id, planned_start=start, planned_end=end, **run_overrides
    )
    return get_success_data(api_client.create_forming_run(payload, _SCHEDULER))


def complete_run(run_id, shots_completed, scrap_weight_kg=0.000,
                 actual_end="2026-05-02T10:30:00Z"):
    """Complete a run. Returns the COMPLETED run."""
    payload = create_run_complete_payload(shots_completed, scrap_weight_kg, actual_end)
    return get_success_data(api_client.complete_forming_run(run_id, payload, _SCHEDULER))


def get_run(run_id):
    return get_success_data(api_client.get_forming_run(run_id, _ANY))


def setup_running_order(run_window=("2026-05-02T10:00:00Z", "2026-05-02T10:30:00Z"),
                        shots_planned=10, station_overrides=None, **kwargs):
    """Staged order + station + first run (order auto-flips STAGED -> RUNNING,
    PRD §3.6). The run is left SCHEDULED. Returns the staged-order context
    plus station and run."""
    ctx = setup_staged_order(**kwargs)
    station = create_station(**(station_overrides or {}))
    run = schedule_run(ctx["order"]["id"], station["id"],
                       start=run_window[0], end=run_window[1],
                       shots_planned=shots_planned)
    ctx["station"] = station
    ctx["run"] = run
    ctx["order"] = get_order(ctx["order"]["id"])
    return ctx


def setup_order_with_completed_run(run_shots=10, run_scrap_kg=0.000,
                                   run_window=("2026-05-02T10:00:00Z", "2026-05-02T10:30:00Z"),
                                   **kwargs):
    """Running order whose first run is COMPLETED with the given good shots and
    scrap mass (PRD §3.6). Returns the context including the completed run."""
    ctx = setup_running_order(run_window=run_window, shots_planned=run_shots, **kwargs)
    run = complete_run(ctx["run"]["id"], run_shots, run_scrap_kg,
                       actual_end=run_window[1])
    ctx["run"] = run
    ctx["order"] = get_order(ctx["order"]["id"])
    return ctx


# ─── Quality inspections (PRD §3.7) ─────────────────────────────────────────

def record_inspection(order_id, booth_id, measurements=None,
                      inspection_type="FIRST_ARTICLE", run_id=None,
                      window=("2026-05-02T12:00:00Z", "2026-05-02T12:30:00Z"),
                      recorder_id=INSPECTOR_1):
    """Record an inspection on a booth window. Returns the RECORDED inspection."""
    payload = create_quality_inspection_payload(
        order_id,
        booth_id,
        forming_run_id=run_id,
        inspection_type=inspection_type,
        scheduled_start=window[0],
        scheduled_end=window[1],
        wall_measurements_mm=measurements or [1.240, 1.250],
    )
    return get_success_data(
        api_client.create_quality_inspection(payload, make_inspector_headers(recorder_id))
    )


def disposition_inspection_ok(inspection_id, disposition="PASS", scrapped_qty=None,
                              dispositioner_id=INSPECTOR_2):
    """Disposition an inspection (segregated from the recorder, PRD §3.7).
    Returns the DISPOSITIONED inspection."""
    payload = create_disposition_payload(disposition, scrapped_qty)
    return get_success_data(
        api_client.disposition_inspection(
            inspection_id, payload, make_inspector_headers(dispositioner_id)
        )
    )


def setup_quality_released_order(inspection_window=("2026-05-02T11:30:00Z", "2026-05-02T12:00:00Z"),
                                 booth_overrides=None, **kwargs):
    """Order with a COMPLETED first run and a PASS-dispositioned FIRST_ARTICLE
    inspection: quality_status is RELEASED (PRD §3.7). Returns the context."""
    ctx = setup_order_with_completed_run(**kwargs)
    booth = create_booth(**(booth_overrides or {}))
    inspection = record_inspection(
        ctx["order"]["id"], booth["id"], run_id=ctx["run"]["id"],
        inspection_type="FIRST_ARTICLE", window=inspection_window,
    )
    inspection = disposition_inspection_ok(inspection["id"], "PASS")
    ctx["booth"] = booth
    ctx["inspection"] = inspection
    ctx["order"] = get_order(ctx["order"]["id"])
    return ctx


def setup_completed_order(**kwargs):
    """Full lifecycle to schedule COMPLETED: shots target met and quality
    RELEASED (PRD §3.6 automatic completion). Returns the context."""
    kwargs.setdefault("run_shots", 100)
    ctx = setup_quality_released_order(**kwargs)
    # Default order qty is 100; the single 100-shot completed run plus the
    # PASS disposition fires the completion cascade.
    ctx["order"] = get_order(ctx["order"]["id"])
    return ctx


# ─── Regrind loop (PRD §3.2) ────────────────────────────────────────────────

def find_scrap_record_for_run(run_id):
    """Reverse-reachability lookup of the run's scrap record (PRD §4 filters)."""
    data, _meta = validate_paginated(
        api_client.list_scrap_records(_ANY, params={"forming_run_id": run_id})
    )
    assert len(data) == 1, f"expected exactly one scrap record for run {run_id}, got {len(data)}"
    return data[0]


def create_batch(creator_id=PLANNER_1, **batch_overrides):
    """Open a regrind batch (ACCEPTING) as the given planner. Returns the batch."""
    return get_success_data(
        api_client.create_regrind_batch(
            create_regrind_batch_payload(**batch_overrides),
            make_planner_headers(creator_id),
        )
    )


def get_batch(batch_id):
    return get_success_data(api_client.get_regrind_batch(batch_id, _ANY))


def certify_scrap_into_batch(scrap_id, batch_id, planner_id=PLANNER_1):
    """CERTIFY a PENDING scrap record into an ACCEPTING batch (PRD §3.2)."""
    payload = create_scrap_certify_payload(batch_id, "CERTIFY")
    return get_success_data(
        api_client.certify_scrap_record(scrap_id, payload, make_planner_headers(planner_id))
    )


def decide_batch(batch_id, decision="CERTIFIED", certified_grade=None,
                 decider_id=PLANNER_2):
    """Decide a PENDING_CERT batch as a planner other than its creator."""
    payload = create_batch_decide_payload(decision, certified_grade)
    return get_success_data(
        api_client.decide_regrind_batch(batch_id, payload, make_planner_headers(decider_id))
    )


def setup_certified_regrind_batch(source_grade="INDUSTRIAL",
                                  decided_grade="INDUSTRIAL",
                                  target_kg=2.000, scrap_kg=2.500,
                                  decision="CERTIFIED"):
    """Full donor chain producing a decided regrind batch (PRD §3.2/§3.5):

    donor order runs and reports `scrap_kg` of scrap -> PENDING scrap record;
    planner-1 opens a batch (target_kg) and certifies the scrap into it (the
    batch auto-advances ACCEPTING -> PENDING_CERT at target); a REGRIND_BATCH
    cleanliness certificate is issued at the decided grade (the regrind
    branch of PRD §3.5 applies the same two-step certificate rule as the
    virgin branch); planner-2 (not the creator) decides the batch.

    Returns dict(batch, scrap_record, donor).
    """
    donor = setup_order_with_completed_run(run_shots=10, run_scrap_kg=scrap_kg)
    scrap = find_scrap_record_for_run(donor["run"]["id"])
    batch = create_batch(
        creator_id=PLANNER_1,
        resin_type="PETG",
        source_grade=source_grade,
        target_kg=target_kg,
    )
    scrap = certify_scrap_into_batch(scrap["id"], batch["id"], planner_id=PLANNER_1)
    issue_certificate("REGRIND_BATCH", batch["id"], decided_grade)
    batch = decide_batch(batch["id"], decision, decided_grade, decider_id=PLANNER_2)
    return {"batch": batch, "scrap_record": scrap, "donor": donor}


# ─── Assembly tasks (PRD §3.8) ──────────────────────────────────────────────

def create_task(order_id, task_type="TRIM", sequence_no=1, insert_part_code=None):
    """Add a secondary-operation task to an order. Returns the PENDING task."""
    payload = create_assembly_task_payload(
        order_id, task_type=task_type, sequence_no=sequence_no,
        insert_part_code=insert_part_code,
    )
    return get_success_data(api_client.create_assembly_task(payload, _SCHEDULER))


def complete_task(task_id):
    return get_success_data(api_client.complete_assembly_task(task_id, _SCHEDULER))


def get_task(task_id):
    return get_success_data(api_client.get_assembly_task(task_id, _ANY))


__all__ = [
    "issue_certificate",
    "set_logical_clock",
    "create_lot",
    "create_certified_lot",
    "get_lot",
    "create_tool_draft",
    "create_tool_prototype",
    "create_tool_production",
    "get_tool",
    "create_stock_spec",
    "create_custom_spec",
    "approve_custom_spec",
    "create_station",
    "create_booth",
    "create_order",
    "get_order",
    "order_version",
    "reserve_virgin",
    "reserve_regrind",
    "get_allocation",
    "stage_order",
    "setup_staged_order",
    "schedule_run",
    "complete_run",
    "get_run",
    "setup_running_order",
    "setup_order_with_completed_run",
    "record_inspection",
    "disposition_inspection_ok",
    "setup_quality_released_order",
    "setup_completed_order",
    "find_scrap_record_for_run",
    "create_batch",
    "get_batch",
    "certify_scrap_into_batch",
    "decide_batch",
    "setup_certified_regrind_batch",
    "create_task",
    "complete_task",
    "get_task",
]
