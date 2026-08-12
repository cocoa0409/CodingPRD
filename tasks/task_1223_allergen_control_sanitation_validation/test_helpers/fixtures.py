"""Composite setup helpers for multi-step test prerequisites.

Every helper builds its preconditions from scratch against an empty database
using only PRD-declared endpoints. Setup calls use get_success_data() so a
setup failure surfaces as a clear "Setup failed" error, not a confusing
assertion failure inside a test.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    create_allergen_payload,
    create_production_line_payload,
    create_matrix_entry_payload,
    create_product_payload,
    create_production_run_payload,
    create_changeover_procedure_payload,
    create_changeover_payload,
    create_swab_result_payload,
    create_technician_payload,
    create_label_reconciliation_payload,
    create_rework_batch_payload,
    create_incident_payload,
    create_audit_finding_payload,
)
from .test_users import TEST_USERS, make_qa_technician_headers, make_auditor_headers
from .constants import TEST_DEFAULTS

MANAGER = TEST_USERS["qa_manager_headers"]
SUPERVISOR = TEST_USERS["qa_supervisor_headers"]
OPERATOR = TEST_USERS["line_operator_headers"]


def _setup_fail(step: str, res):
    raise AssertionError(
        f"Setup failed at {step}: HTTP {res.status_code} body={res.text[:400]}"
    )


def _ok(res, step: str):
    if res.status_code >= 400:
        _setup_fail(step, res)
    return get_success_data(res)


# ─── Tier 1: single-entity creation shortcuts ────────────────────────────────

def create_allergen(code="PEANUT", regulatory_class="MAJOR_9", **overrides) -> dict:
    res = api_client.create_allergen(
        create_allergen_payload(code=code, display_name=code.title(),
                                regulatory_class=regulatory_class, **overrides),
        MANAGER)
    return _ok(res, f"create allergen {code}")


def create_line(line_code="LINE-1", sanitation_class="WET_WASH") -> dict:
    res = api_client.create_production_line(
        create_production_line_payload(line_code=line_code, sanitation_class=sanitation_class),
        MANAGER)
    return _ok(res, f"create line {line_code}")


def create_matrix_entry(line_id, allergen_id, handling="REQUIRES_CHANGEOVER",
                        changeover_minutes=30) -> dict:
    res = api_client.create_matrix_entry(
        create_matrix_entry_payload(line_id, allergen_id, handling=handling,
                                    changeover_minutes=changeover_minutes),
        MANAGER)
    return _ok(res, "create matrix entry")


def create_product(sku="P-001", allergen_set=None, rework_class="NO_REWORK", **overrides) -> dict:
    res = api_client.create_product(
        create_product_payload(sku=sku, allergen_set=allergen_set if allergen_set is not None else [],
                               rework_class=rework_class, **overrides),
        MANAGER)
    return _ok(res, f"create product {sku}")


def create_technician(tech_code="TECH-001", certified_allergen_ids=None,
                      certification_expiry_utc=TEST_DEFAULTS["CERT_EXPIRY_UTC"]) -> dict:
    res = api_client.create_technician(
        create_technician_payload(tech_code=tech_code,
                                  certified_allergen_ids=certified_allergen_ids or [],
                                  certification_expiry_utc=certification_expiry_utc),
        MANAGER)
    return _ok(res, f"create technician {tech_code}")


def create_procedure(target_allergen_id, procedure_code="COP-TEST-V1", **overrides) -> dict:
    """Create a DRAFT changeover procedure."""
    res = api_client.create_changeover_procedure(
        create_changeover_procedure_payload(target_allergen_id, procedure_code=procedure_code,
                                            **overrides),
        MANAGER)
    return _ok(res, f"create procedure {procedure_code}")


def approve_procedure(procedure: dict) -> dict:
    """Approve a DRAFT procedure with a fresh OCC token (its current version)."""
    res = api_client.approve_procedure(
        procedure["id"], {"expected_procedure_version": procedure["version"]}, MANAGER)
    return _ok(res, f"approve procedure {procedure['id']}")


def create_and_approve_procedure(target_allergen_id, procedure_code="COP-TEST-V1", **overrides) -> dict:
    return approve_procedure(create_procedure(target_allergen_id, procedure_code, **overrides))


def create_run(line_id, product_id,
               start=TEST_DEFAULTS["RUN_START_UTC"],
               end=TEST_DEFAULTS["RUN_END_UTC"]) -> dict:
    """Create a DRAFT production run."""
    res = api_client.create_production_run(
        create_production_run_payload(line_id, product_id,
                                      planned_start_utc=start, planned_end_utc=end),
        SUPERVISOR)
    return _ok(res, "create production run")


def get_line_version(line_id) -> int:
    line = _ok(api_client.get_production_line(line_id, SUPERVISOR), "get line for version")
    return line["version"]


def schedule_run(run: dict) -> dict:
    """Schedule a DRAFT run with a fresh OCC line version."""
    version = get_line_version(run["line_id"])
    res = api_client.schedule_run(run["id"], {"expected_line_version": version}, SUPERVISOR)
    return _ok(res, f"schedule run {run['id']}")


def create_changeover(line_id, to_run_id, procedure_id, scheduled_minutes,
                      from_run_id=None) -> dict:
    res = api_client.create_changeover(
        create_changeover_payload(line_id, to_run_id, procedure_id,
                                  from_run_id=from_run_id, scheduled_minutes=scheduled_minutes),
        SUPERVISOR)
    return _ok(res, "create changeover")


def set_clock(to_iso8601: str) -> dict:
    res = api_client.set_clock({"to_iso8601": to_iso8601}, MANAGER)
    return _ok(res, f"set clock {to_iso8601}")


# ─── Tier 2/3: composite changeover scenarios ────────────────────────────────

def setup_changeover_scenario(
    allergen_code="PEANUT",
    line_code="LINE-1",
    sanitation_class="WET_WASH",
    handling="REQUIRES_CHANGEOVER",
    changeover_minutes=30,
    sku="P-001",
    allergen_set=None,
    procedure_code="COP-TEST-V1",
    min_swab_zones=1,
    atp_action_level_rlu=150,
    allergen_action_level_ppm=2.0,
    scheduled_minutes=None,
    actual_minutes=None,
    tech_code="TECH-001",
    run_start=TEST_DEFAULTS["RUN_START_UTC"],
    run_end=TEST_DEFAULTS["RUN_END_UTC"],
    schedule_the_run=True,
) -> dict:
    """Full chain: allergen + line + matrix entry + product + approved
    procedure + certified technician + DRAFT run + covering changeover
    (+ run scheduled).

    Returns a context dict with every entity. When schedule_the_run is True
    the run is SCHEDULED; the changeover stays PLANNED until begun.
    """
    allergen_set = allergen_set if allergen_set is not None else [allergen_code]
    ctx = {}
    ctx["allergen"] = create_allergen(allergen_code)
    ctx["line"] = create_line(line_code, sanitation_class)
    ctx["matrix_entry"] = create_matrix_entry(
        ctx["line"]["id"], ctx["allergen"]["id"],
        handling=handling, changeover_minutes=changeover_minutes)
    ctx["product"] = create_product(sku, allergen_set)
    ctx["procedure"] = create_and_approve_procedure(
        ctx["allergen"]["id"], procedure_code,
        min_swab_zones=min_swab_zones,
        atp_action_level_rlu=atp_action_level_rlu,
        allergen_action_level_ppm=allergen_action_level_ppm)
    ctx["tech"] = create_technician(tech_code, [ctx["allergen"]["id"]])
    ctx["run"] = create_run(ctx["line"]["id"], ctx["product"]["id"], run_start, run_end)
    minutes = scheduled_minutes if scheduled_minutes is not None else changeover_minutes
    ctx["changeover"] = create_changeover(
        ctx["line"]["id"], ctx["run"]["id"], ctx["procedure"]["id"], minutes)
    if schedule_the_run:
        ctx["run"] = schedule_run(ctx["run"])
    return ctx


def drive_changeover_to_swab_pending(ctx: dict, actual_minutes=30) -> dict:
    """PLANNED -> IN_EXECUTION -> SWAB_PENDING. Returns updated changeover."""
    co_id = ctx["changeover"]["id"]
    _ok(api_client.begin_changeover(co_id, OPERATOR), "begin changeover")
    res = api_client.finish_changeover_execution(co_id, {"actual_minutes": actual_minutes}, OPERATOR)
    ctx["changeover"] = _ok(res, "finish changeover execution")
    return ctx["changeover"]


def setup_swab_pending_changeover(actual_minutes=30, **kwargs) -> dict:
    """Scenario with the changeover already in SWAB_PENDING."""
    ctx = setup_changeover_scenario(**kwargs)
    drive_changeover_to_swab_pending(ctx, actual_minutes=actual_minutes)
    return ctx


def record_swab(ctx: dict, zone_code="Z1", swab_type="ATP", measured_value=50,
                invalidated_reason=None) -> dict:
    """Record a swab as the scenario's certified technician (entity-backed
    headers: X-User-ID is the technician's id, matching recorded_by_id)."""
    tech = ctx["tech"]
    payload = create_swab_result_payload(
        tech["id"], zone_code=zone_code, swab_type=swab_type, measured_value=measured_value)
    if invalidated_reason is not None:
        payload["invalidated_reason"] = invalidated_reason
    res = api_client.record_swab_result(
        ctx["changeover"]["id"], payload, make_qa_technician_headers(tech["id"]))
    return res


def record_swab_ok(ctx: dict, **kwargs) -> dict:
    return _ok(record_swab(ctx, **kwargs), "record swab")


def get_changeover(changeover_id) -> dict:
    return _ok(api_client.get_changeover(changeover_id, SUPERVISOR), "get changeover")


def get_run(run_id) -> dict:
    return _ok(api_client.get_production_run(run_id, SUPERVISOR), "get run")


def get_line(line_id) -> dict:
    return _ok(api_client.get_production_line(line_id, SUPERVISOR), "get line")


# ─── Technician / audit helpers ──────────────────────────────────────────────

def setup_technician_pair(allergen_code="MILK"):
    """Allergen + two certified technicians: (allergen, auditee, auditor)."""
    allergen = create_allergen(allergen_code)
    auditee = create_technician("TECH-A1", [allergen["id"]])
    auditor = create_technician("TECH-A2", [allergen["id"]])
    return allergen, auditee, auditor


def record_finding(technician: dict, auditor: dict, severity="MINOR",
                   finding_type="PROCEDURE_DEVIATION",
                   due=TEST_DEFAULTS["FINDING_DUE_UTC"]):
    """Record an audit finding as the Auditor role with the auditor technician's
    entity-backed identity. Returns the raw response."""
    payload = create_audit_finding_payload(
        technician["id"], auditor["id"], severity=severity,
        finding_type=finding_type, corrective_action_due_utc=due)
    return api_client.create_audit_finding(payload, make_auditor_headers(auditor["id"]))


def record_finding_ok(technician: dict, auditor: dict, **kwargs) -> dict:
    return _ok(record_finding(technician, auditor, **kwargs), "create audit finding")


def get_technician(tech_id) -> dict:
    return _ok(api_client.get_technician(tech_id, MANAGER), "get technician")


# ─── Incident helpers ─────────────────────────────────────────────────────────

def create_incident_ok(incident_type="LABEL_MISMATCH", severity="LOW",
                       line_id=None, product_id=None, description="t") -> dict:
    payload = create_incident_payload(incident_type=incident_type, severity=severity,
                                      description=description)
    if line_id is not None:
        payload["line_id"] = line_id
    if product_id is not None:
        payload["product_id"] = product_id
    return _ok(api_client.create_incident(payload, SUPERVISOR), "create incident")


def drive_incident_to_contained(incident_id) -> dict:
    """OPEN -> INVESTIGATING -> CONTAINED."""
    _ok(api_client.begin_incident_investigation(incident_id, SUPERVISOR), "begin investigation")
    res = api_client.contain_incident(incident_id, {"containment_action": "Hold product"}, SUPERVISOR)
    return _ok(res, "contain incident")
