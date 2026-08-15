"""Composite setup helpers.

Every fixture builds its preconditions from scratch through the public API:
the harness restarts the server before every test, so nothing is carried over.

Technician-scoped execution calls always use headers whose X-User-ID equals
the technician id recorded on the visit / work order.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import (
    DEFAULT_AUDITOR_ID,
    DEFAULT_SCHEDULED_START,
    DEFAULT_TECHNICIAN_ID,
    DEFAULT_WINDOW_END,
    DEFAULT_WINDOW_START,
    SECOND_TECHNICIAN_ID,
)
from .factories import (
    create_asset_payload,
    create_audit_payload,
    create_batch_payload,
    create_building_payload,
    create_deficiency_payload,
    create_evidence_payload,
    create_plan_payload,
    create_property_payload,
    create_template_payload,
    create_unit_payload,
    create_visit_payload,
    create_work_order_payload,
)
from .test_users import (
    TEST_USERS,
    make_auditor_headers,
    make_property_manager_headers,
    make_technician_headers,
)

PM = TEST_USERS["property_manager_headers"]


def _pm(pm):
    return pm if pm is not None else PM


# ---------------------------------------------------------------------------
# Single-entity creators (lenient validator: setup failures surface clearly)
# ---------------------------------------------------------------------------

def create_property(pm=None, **overrides) -> dict:
    resp = api_client.create_property(create_property_payload(**overrides), _pm(pm))
    return get_success_data(resp)


def create_building(property_id, pm=None, **overrides) -> dict:
    resp = api_client.create_building(create_building_payload(property_id, **overrides), _pm(pm))
    return get_success_data(resp)


def create_unit(building_id, pm=None, **overrides) -> dict:
    resp = api_client.create_unit(create_unit_payload(building_id, **overrides), _pm(pm))
    return get_success_data(resp)


def create_asset(unit_id, pm=None, **overrides) -> dict:
    resp = api_client.create_asset(create_asset_payload(unit_id, **overrides), _pm(pm))
    return get_success_data(resp)


def create_template(property_id, pm=None, **overrides) -> dict:
    resp = api_client.create_template(create_template_payload(property_id, **overrides), _pm(pm))
    return get_success_data(resp)


def create_plan(property_id, pm=None, adopt=False, **overrides) -> dict:
    resp = api_client.create_plan(create_plan_payload(property_id, **overrides), _pm(pm))
    plan = get_success_data(resp)
    if adopt:
        resp = api_client.adopt_plan(plan["id"], _pm(pm))
        plan = get_success_data(resp)
    return plan


def adopt_plan(plan_id, pm=None) -> dict:
    return get_success_data(api_client.adopt_plan(plan_id, _pm(pm)))


def create_batch(property_id, pm=None, **overrides) -> dict:
    resp = api_client.create_batch(create_batch_payload(property_id, **overrides), _pm(pm))
    return get_success_data(resp)


def get_batch(batch_id, pm=None) -> dict:
    return get_success_data(api_client.get_batch(batch_id, _pm(pm)))


def add_visit(batch_id, unit_id, template_id, asset_id, plan_id,
              scheduled_start=DEFAULT_SCHEDULED_START,
              technician_id=DEFAULT_TECHNICIAN_ID, pm=None) -> dict:
    payload = create_visit_payload(
        batch_id, unit_id, template_id, asset_id, plan_id,
        scheduled_start=scheduled_start, technician_id=technician_id,
    )
    return get_success_data(api_client.create_visit(payload, _pm(pm)))


def publish_batch(batch_id, pm=None) -> dict:
    """OCC-safe publish: reads the current batch version, then publishes."""
    current = get_batch(batch_id, pm=pm)
    resp = api_client.publish_batch(batch_id, {"expected_batch_version": current["version"]}, _pm(pm))
    return get_success_data(resp)


def lock_batch(batch_id, pm=None) -> dict:
    return get_success_data(api_client.lock_batch(batch_id, _pm(pm)))


def set_clock(iso_ts, pm=None) -> dict:
    return get_success_data(api_client.set_clock({"to_iso8601": iso_ts}, _pm(pm)))


def start_visit(visit_id, technician_id=DEFAULT_TECHNICIAN_ID) -> dict:
    return get_success_data(api_client.start_visit(visit_id, make_technician_headers(technician_id)))


def complete_visit(visit_id, actual_minutes, condition_score,
                   technician_id=DEFAULT_TECHNICIAN_ID) -> dict:
    payload = {"actual_minutes": actual_minutes, "condition_score_recorded": condition_score}
    return get_success_data(api_client.complete_visit(visit_id, payload, make_technician_headers(technician_id)))


def no_access_visit(visit_id, technician_id=DEFAULT_TECHNICIAN_ID) -> dict:
    return get_success_data(api_client.no_access_visit(visit_id, make_technician_headers(technician_id)))


def record_evidence(visit_id, technician_id=DEFAULT_TECHNICIAN_ID, **overrides) -> dict:
    return get_success_data(
        api_client.create_evidence(visit_id, create_evidence_payload(**overrides),
                                   make_technician_headers(technician_id))
    )


def record_deficiency(visit_id, asset_id, technician_id=DEFAULT_TECHNICIAN_ID, **overrides) -> dict:
    return get_success_data(
        api_client.create_deficiency(visit_id, create_deficiency_payload(asset_id, **overrides),
                                     make_technician_headers(technician_id))
    )


def triage_deficiency(deficiency_id, pm=None) -> dict:
    return get_success_data(api_client.triage_deficiency(deficiency_id, _pm(pm)))


def get_deficiency(deficiency_id, pm=None) -> dict:
    return get_success_data(api_client.get_deficiency(deficiency_id, _pm(pm)))


def create_work_order(deficiency_id, plan_id, expected_deficiency_version=None,
                      estimated_cost_cents=100_000, assigned_technician_id=SECOND_TECHNICIAN_ID,
                      pm=None, **overrides) -> dict:
    """Creates a work order; when expected_deficiency_version is None the
    deficiency's current version is read first (OCC-correct create)."""
    if expected_deficiency_version is None:
        expected_deficiency_version = get_deficiency(deficiency_id, pm=pm)["version"]
    payload = create_work_order_payload(
        deficiency_id, plan_id, expected_deficiency_version,
        estimated_cost_cents=estimated_cost_cents,
        assigned_technician_id=assigned_technician_id,
        **overrides,
    )
    return get_success_data(api_client.create_work_order(payload, _pm(pm)))


def get_plan(plan_id, pm=None) -> dict:
    return get_success_data(api_client.get_plan(plan_id, _pm(pm)))


def get_asset(asset_id, pm=None) -> dict:
    return get_success_data(api_client.get_asset(asset_id, _pm(pm)))


def get_visit(visit_id, pm=None) -> dict:
    return get_success_data(api_client.get_visit(visit_id, _pm(pm)))


def get_work_order(wo_id, pm=None) -> dict:
    return get_success_data(api_client.get_work_order(wo_id, _pm(pm)))


def plan_ledger_entries(plan_id, pm=None, params=None) -> list:
    data, _meta = _paginated(api_client.list_plan_ledger(plan_id, _pm(pm), params=params))
    return data


def visit_ledger_entries(visit_id, pm=None) -> list:
    data, _meta = _paginated(api_client.list_visit_ledger_entries(visit_id, _pm(pm)))
    return data


def wo_ledger_entries(wo_id, pm=None) -> list:
    data, _meta = _paginated(api_client.list_wo_ledger_entries(wo_id, _pm(pm)))
    return data


def _paginated(resp):
    from prd_bench_local_runner.testing import validate_paginated
    return validate_paginated(resp)


# ---------------------------------------------------------------------------
# Tier 1/2: base hierarchy — property + building + unit + asset + template + plan
# ---------------------------------------------------------------------------

def setup_property_scaffold(
    *,
    occupancy="VACANT",
    component_type="HVAC",
    estimated_labor_minutes=30,
    frequency_days=90,
    requires_evidence=False,
    rate_cents_per_hour=6000,
    notice_lead_hours=24,
    budget_cents=100_000_000,
    plan_year=2026,
    adopt=True,
    installed_on="2024-01-01T00:00:00Z",
    warranty_months=24,
    expected_life_months=120,
    replacement_cost_cents=400_000,
    unit_number="101",
    pm=None,
) -> dict:
    """Property + building + unit + asset + template + plan. Returns a ctx dict."""
    prop = create_property(
        pm=pm,
        notice_lead_hours=notice_lead_hours,
        default_labor_rate_cents_per_hour=rate_cents_per_hour,
    )
    building = create_building(prop["id"], pm=pm)
    unit = create_unit(building["id"], pm=pm, unit_number=unit_number, occupancy_status=occupancy)
    asset = create_asset(
        unit["id"], pm=pm,
        component_type=component_type,
        installed_on=installed_on,
        warranty_months=warranty_months,
        expected_life_months=expected_life_months,
        replacement_cost_cents=replacement_cost_cents,
    )
    template = create_template(
        prop["id"], pm=pm,
        component_type=component_type,
        frequency_days=frequency_days,
        estimated_labor_minutes=estimated_labor_minutes,
        requires_evidence=requires_evidence,
    )
    plan = create_plan(prop["id"], pm=pm, plan_year=plan_year, budget_cents=budget_cents, adopt=adopt)
    return {
        "property": prop,
        "building": building,
        "unit": unit,
        "asset": asset,
        "template": template,
        "plan": plan,
    }


# ---------------------------------------------------------------------------
# Tier 3: visit lifecycle shortcuts
# ---------------------------------------------------------------------------

def setup_published_visit(
    *,
    window_start=DEFAULT_WINDOW_START,
    window_end=DEFAULT_WINDOW_END,
    scheduled_start=DEFAULT_SCHEDULED_START,
    technician_id=DEFAULT_TECHNICIAN_ID,
    pm=None,
    **scaffold_kwargs,
) -> dict:
    """setup_property_scaffold + batch + one visit + publish. Visit lands NOTIFIED."""
    ctx = setup_property_scaffold(pm=pm, **scaffold_kwargs)
    ctx["batch"] = create_batch(
        ctx["property"]["id"], pm=pm, window_start=window_start, window_end=window_end
    )
    ctx["visit"] = add_visit(
        ctx["batch"]["id"], ctx["unit"]["id"], ctx["template"]["id"], ctx["asset"]["id"],
        ctx["plan"]["id"], scheduled_start=scheduled_start, technician_id=technician_id, pm=pm,
    )
    ctx["batch"] = publish_batch(ctx["batch"]["id"], pm=pm)
    ctx["visit"] = get_visit(ctx["visit"]["id"], pm=pm)
    return ctx


def setup_in_progress_visit(
    *,
    scheduled_start=DEFAULT_SCHEDULED_START,
    technician_id=DEFAULT_TECHNICIAN_ID,
    start_clock=None,
    pm=None,
    **kwargs,
) -> dict:
    """Published visit + clock moved to the visit's scheduled_start + technician start."""
    ctx = setup_published_visit(
        scheduled_start=scheduled_start, technician_id=technician_id, pm=pm, **kwargs
    )
    set_clock(start_clock or scheduled_start, pm=pm)
    ctx["visit"] = start_visit(ctx["visit"]["id"], technician_id=technician_id)
    return ctx


def setup_completed_visit(
    *,
    actual_minutes=30,
    condition_score=4,
    scheduled_start=DEFAULT_SCHEDULED_START,
    technician_id=DEFAULT_TECHNICIAN_ID,
    evidence=None,
    deficiency=None,
    pm=None,
    **kwargs,
) -> dict:
    """Full chain through visit completion.

    evidence: None (no evidence recorded) or a dict of evidence payload overrides.
    deficiency: None or a dict of deficiency payload overrides (recorded while the
    visit is IN_PROGRESS, before completion).
    """
    ctx = setup_in_progress_visit(
        scheduled_start=scheduled_start, technician_id=technician_id, pm=pm, **kwargs
    )
    if evidence is not None:
        ctx["evidence"] = record_evidence(ctx["visit"]["id"], technician_id=technician_id, **evidence)
    if deficiency is not None:
        ctx["deficiency"] = record_deficiency(
            ctx["visit"]["id"], ctx["asset"]["id"], technician_id=technician_id, **deficiency
        )
    ctx["visit"] = complete_visit(
        ctx["visit"]["id"], actual_minutes, condition_score, technician_id=technician_id
    )
    return ctx


# ---------------------------------------------------------------------------
# Tier 3b: deficiency -> work order ladder
# ---------------------------------------------------------------------------

def setup_triaged_deficiency(*, severity="HIGH", description="Corroded flue",
                             pm=None, **kwargs) -> dict:
    """Completed visit + one deficiency (recorded in progress) + triage."""
    ctx = setup_completed_visit(
        pm=pm, deficiency={"severity": severity, "description": description}, **kwargs
    )
    ctx["deficiency"] = triage_deficiency(ctx["deficiency"]["id"], pm=pm)
    return ctx


def setup_work_order(*, estimated_cost_cents=100_000,
                     assigned_technician_id=SECOND_TECHNICIAN_ID,
                     pm=None, **kwargs) -> dict:
    """Triaged deficiency + work order created (status OPEN)."""
    ctx = setup_triaged_deficiency(pm=pm, **kwargs)
    ctx["work_order"] = create_work_order(
        ctx["deficiency"]["id"], ctx["plan"]["id"],
        estimated_cost_cents=estimated_cost_cents,
        assigned_technician_id=assigned_technician_id, pm=pm,
    )
    return ctx


def setup_wo_in_review(pm=None, **kwargs) -> dict:
    ctx = setup_work_order(pm=pm, **kwargs)
    wo = ctx["work_order"]
    ctx["work_order"] = get_success_data(api_client.submit_work_order_review(
        wo["id"], make_technician_headers(wo["assigned_technician_id"])))
    return ctx


def setup_wo_approved(pm=None, **kwargs) -> dict:
    ctx = setup_wo_in_review(pm=pm, **kwargs)
    ctx["work_order"] = get_success_data(api_client.approve_work_order(ctx["work_order"]["id"], _pm(pm)))
    return ctx


def setup_wo_in_progress(pm=None, **kwargs) -> dict:
    ctx = setup_wo_approved(pm=pm, **kwargs)
    wo = ctx["work_order"]
    ctx["work_order"] = get_success_data(api_client.start_work_order(
        wo["id"], make_technician_headers(wo["assigned_technician_id"])))
    return ctx


def setup_wo_completed(*, actual_cost_cents=180_000, pm=None, **kwargs) -> dict:
    ctx = setup_wo_in_progress(pm=pm, **kwargs)
    wo = ctx["work_order"]
    ctx["work_order"] = get_success_data(api_client.complete_work_order(
        wo["id"], {"actual_cost_cents": actual_cost_cents},
        make_technician_headers(wo["assigned_technician_id"])))
    return ctx


def verify_work_order(wo_id, outcome, auditor_id=DEFAULT_AUDITOR_ID) -> dict:
    return get_success_data(api_client.verify_work_order(
        wo_id, {"outcome": outcome}, make_auditor_headers(auditor_id)))


def create_audit(visit_id, outcome, auditor_id=DEFAULT_AUDITOR_ID, **overrides) -> dict:
    return get_success_data(api_client.create_audit(
        visit_id, create_audit_payload(outcome=outcome, **overrides),
        make_auditor_headers(auditor_id)))
