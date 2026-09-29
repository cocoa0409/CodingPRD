"""Composite state builders.

The server is restarted with an empty database before every test, so each of
these builders drives the public endpoints of PRD §4 from scratch rather than
seeding storage directly. Setup calls are validated with ``get_success_data`` so
a broken precondition fails loudly at the line that broke it.

A few reads worth remembering, because the PRD deliberately does not publish a
single-resource endpoint for everything: a master lease agreement is read by
listing its tenant's leases, a structural analysis by listing its application's
analyses, and an equipment audit by listing its tower's audits. Helpers below
wrap all three.

Identity threading matters. ``Tenant`` and ``Landlord`` are entity-backed roles,
so every call acting as one of them must carry the real row id — the builders
return the headers they used, and callers should reuse those rather than a shared
constant.
"""

from typing import Any, Dict, List, Optional

from prd_bench_local_runner.testing import get_success_data

from . import factories
from .api_client import ApiClient
from .test_users import (
    ADMIN_HEADERS,
    AUDITOR_HEADERS,
    ENGINEER_HEADERS,
    make_landlord_headers,
    make_tenant_headers,
)

# ─── Reads ───────────────────────────────────────────────────────────────────


def read_tower(api: ApiClient, tower_id: str, headers=None) -> Dict[str, Any]:
    return get_success_data(api.get_tower(tower_id, headers or ADMIN_HEADERS))


def read_tower_version(api: ApiClient, tower_id: str, headers=None) -> int:
    """PRD §3.1: reading a tower is the canonical way to obtain its version."""
    return read_tower(api, tower_id, headers or ENGINEER_HEADERS)["version"]


def read_capacity_summary(api: ApiClient, tower_id: str, headers=None) -> Dict[str, Any]:
    return get_success_data(api.get_capacity_summary(tower_id, headers or ADMIN_HEADERS))


def read_ground_lease(api: ApiClient, lease_id: str, headers=None) -> Dict[str, Any]:
    return get_success_data(api.get_ground_lease(lease_id, headers or ADMIN_HEADERS))


def read_tenant(api: ApiClient, tenant_id: str, headers=None) -> Dict[str, Any]:
    return get_success_data(api.get_tenant(tenant_id, headers or ADMIN_HEADERS))


def read_master_lease(api: ApiClient, tenant_id: str, mla_id: str, headers=None) -> Dict[str, Any]:
    """Read one master lease agreement out of its tenant's lease list."""
    data = get_success_data(
        api.list_tenant_master_lease_agreements(
            tenant_id, {"limit": 100}, headers or ADMIN_HEADERS
        )
    )
    for row in data:
        if row["id"] == mla_id:
            return row
    raise AssertionError(f"master lease agreement {mla_id} not found under tenant {tenant_id}")


def read_application(api: ApiClient, app_id: str, headers=None) -> Dict[str, Any]:
    return get_success_data(api.get_colocation_application(app_id, headers or ADMIN_HEADERS))


def read_equipment_line(api: ApiClient, line_id: str, headers=None) -> Dict[str, Any]:
    return get_success_data(api.get_equipment_line(line_id, headers or ADMIN_HEADERS))


def read_analysis(api: ApiClient, app_id: str, analysis_id: str, headers=None) -> Dict[str, Any]:
    """Read one structural analysis out of its application's analysis list."""
    data = get_success_data(
        api.list_application_structural_analyses(
            app_id, {"limit": 100}, headers or ADMIN_HEADERS
        )
    )
    for row in data:
        if row["id"] == analysis_id:
            return row
    raise AssertionError(f"structural analysis {analysis_id} not found under application {app_id}")


def read_amendment(api: ApiClient, amendment_id: str, headers=None) -> Dict[str, Any]:
    return get_success_data(api.get_site_amendment(amendment_id, headers or ADMIN_HEADERS))


def read_project(api: ApiClient, project_id: str, headers=None) -> Dict[str, Any]:
    return get_success_data(api.get_modification_project(project_id, headers or ADMIN_HEADERS))


def read_cost_share(api: ApiClient, share_id: str, headers=None) -> Dict[str, Any]:
    return get_success_data(api.get_cost_share(share_id, headers or ADMIN_HEADERS))


def read_audit(api: ApiClient, tower_id: str, audit_id: str, headers=None) -> Dict[str, Any]:
    """Read one equipment audit out of its tower's audit list."""
    data = get_success_data(
        api.list_tower_equipment_audits(tower_id, {"limit": 100}, headers or ADMIN_HEADERS)
    )
    for row in data:
        if row["id"] == audit_id:
            return row
    raise AssertionError(f"equipment audit {audit_id} not found under tower {tower_id}")


def read_finding(api: ApiClient, finding_id: str, headers=None) -> Dict[str, Any]:
    return get_success_data(api.get_audit_finding(finding_id, headers or ADMIN_HEADERS))


# ─── Logical clock ───────────────────────────────────────────────────────────


def advance_clock(api: ApiClient, to_iso8601: str, headers=None) -> Dict[str, Any]:
    """Advance the logical clock, running both expiry sweeps of PRD §2.4."""
    return get_success_data(
        api.set_clock(factories.clock_payload(to_iso8601), headers or ADMIN_HEADERS)
    )


# ─── Atoms ───────────────────────────────────────────────────────────────────


def new_tower(api: ApiClient, **overrides: Any) -> Dict[str, Any]:
    return get_success_data(
        api.create_tower(factories.tower_payload(**overrides), ADMIN_HEADERS), 201
    )


def new_landlord(api: ApiClient, **overrides: Any) -> Dict[str, Any]:
    return get_success_data(
        api.create_landlord(factories.landlord_payload(**overrides), ADMIN_HEADERS), 201
    )


def new_ground_lease(
    api: ApiClient, tower_id: str, landlord_id: str, **overrides: Any
) -> Dict[str, Any]:
    return get_success_data(
        api.create_ground_lease(
            factories.ground_lease_payload(tower_id, landlord_id, **overrides), ADMIN_HEADERS
        ),
        201,
    )


def new_tenant(api: ApiClient, **overrides: Any) -> Dict[str, Any]:
    return get_success_data(
        api.create_tenant(factories.tenant_payload(**overrides), ADMIN_HEADERS), 201
    )


def new_master_lease(
    api: ApiClient, tenant_id: str, activate: bool = True, **overrides: Any
) -> Dict[str, Any]:
    """Create a master lease agreement, activating it by default (PRD §3.3)."""
    mla = get_success_data(
        api.create_master_lease_agreement(
            factories.master_lease_agreement_payload(tenant_id, **overrides), ADMIN_HEADERS
        ),
        201,
    )
    if activate:
        mla = get_success_data(
            api.activate_master_lease_agreement(mla["id"], {}, ADMIN_HEADERS), 200
        )
    return mla


def new_application(
    api: ApiClient, tower_id: str, mla_id: str, tenant_id: str, **overrides: Any
) -> Dict[str, Any]:
    return get_success_data(
        api.create_colocation_application(
            factories.colocation_application_payload(tower_id, mla_id, **overrides),
            make_tenant_headers(tenant_id),
        ),
        201,
    )


def add_equipment_line(
    api: ApiClient, app_id: str, tenant_id: str, **overrides: Any
) -> Dict[str, Any]:
    return get_success_data(
        api.create_equipment_line(
            app_id, factories.equipment_line_payload(**overrides), make_tenant_headers(tenant_id)
        ),
        201,
    )


def submit_application(api: ApiClient, app_id: str, tenant_id: str) -> Dict[str, Any]:
    return get_success_data(
        api.submit_colocation_application(app_id, {}, make_tenant_headers(tenant_id)), 200
    )


def revise_application(
    api: ApiClient, app_id: str, tenant_id: str, revision_note: Optional[str] = None
) -> Dict[str, Any]:
    return get_success_data(
        api.revise_colocation_application(
            app_id, factories.revise_payload(revision_note), make_tenant_headers(tenant_id)
        ),
        200,
    )


def approve_application(api: ApiClient, app_id: str) -> Dict[str, Any]:
    return get_success_data(api.approve_colocation_application(app_id, {}, ADMIN_HEADERS), 200)


def run_analysis(
    api: ApiClient,
    app_id: str,
    tower_id: str,
    variant: str = "PRELIMINARY",
    headers=None,
    expected_tower_version: Optional[int] = None,
) -> Dict[str, Any]:
    """Create a structural analysis, threading the tower version PRD §2.11 requires."""
    engineer_headers = headers or ENGINEER_HEADERS
    version = (
        expected_tower_version
        if expected_tower_version is not None
        else read_tower_version(api, tower_id, engineer_headers)
    )
    return get_success_data(
        api.create_structural_analysis(
            factories.structural_analysis_payload(app_id, version, variant), engineer_headers
        ),
        201,
    )


def quote_analysis(
    api: ApiClient, analysis_id: str, cost_cents: int, headers=None
) -> Dict[str, Any]:
    return get_success_data(
        api.issue_quotation(
            analysis_id, factories.quotation_payload(cost_cents), headers or ENGINEER_HEADERS
        ),
        200,
    )


def paper_amendment(
    api: ApiClient, mla_id: str, tower_id: str, app_id: str, **overrides: Any
) -> Dict[str, Any]:
    return get_success_data(
        api.create_site_amendment(
            factories.site_amendment_payload(mla_id, tower_id, app_id, **overrides), ADMIN_HEADERS
        ),
        201,
    )


def execute_amendment(
    api: ApiClient, amendment_id: str, signature_received: bool = True
) -> Dict[str, Any]:
    return get_success_data(
        api.execute_site_amendment(
            amendment_id, factories.execute_payload(signature_received), ADMIN_HEADERS
        ),
        200,
    )


def give_notice(api: ApiClient, amendment_id: str, tenant_id: str) -> Dict[str, Any]:
    return get_success_data(
        api.give_termination_notice(amendment_id, {}, make_tenant_headers(tenant_id)), 200
    )


def complete_decommission(api: ApiClient, amendment_id: str) -> Dict[str, Any]:
    return get_success_data(
        api.complete_decommission(
            amendment_id, factories.complete_decommission_payload(True), ADMIN_HEADERS
        ),
        200,
    )


def pay_tenant_balance(api: ApiClient, tenant_id: str, amount_cents: int, headers=None) -> Dict[str, Any]:
    return get_success_data(
        api.create_tenant_payment(
            tenant_id, factories.tenant_payment_payload(amount_cents), headers or ADMIN_HEADERS
        ),
        200,
    )


def record_landlord_payment(
    api: ApiClient, lease_id: str, period_start_date: str, period_end_date: str
) -> Dict[str, Any]:
    return get_success_data(
        api.create_landlord_payment(
            factories.landlord_payment_payload(lease_id, period_start_date, period_end_date),
            ADMIN_HEADERS,
        ),
        201,
    )


# ─── Site with a payee and an active ground lease ────────────────────────────


def site_with_ground_lease(
    api: ApiClient,
    tower_overrides: Optional[Dict[str, Any]] = None,
    landlord_overrides: Optional[Dict[str, Any]] = None,
    lease_overrides: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """A tower, its landlord and an ACTIVE ground lease over it."""
    tower = new_tower(api, **(tower_overrides or {}))
    landlord = new_landlord(api, **(landlord_overrides or {}))
    lease = new_ground_lease(api, tower["id"], landlord["id"], **(lease_overrides or {}))
    return {
        "tower": tower,
        "landlord": landlord,
        "ground_lease": lease,
        "landlord_headers": make_landlord_headers(landlord["id"]),
    }


def carrier_with_active_lease(
    api: ApiClient,
    tenant_overrides: Optional[Dict[str, Any]] = None,
    mla_overrides: Optional[Dict[str, Any]] = None,
    activate: bool = True,
) -> Dict[str, Any]:
    """A tenant plus a master lease agreement, ACTIVE by default."""
    tenant = new_tenant(api, **(tenant_overrides or {}))
    mla = new_master_lease(api, tenant["id"], activate=activate, **(mla_overrides or {}))
    return {
        "tenant": tenant,
        "mla": mla,
        "tenant_headers": make_tenant_headers(tenant["id"]),
    }


# ─── The colocation chain ────────────────────────────────────────────────────

CHAIN_STAGES = ("DRAFT", "SUBMITTED", "REVIEWED", "APPROVED", "PAPERED", "EXECUTED")

DEFAULT_LINES: List[Dict[str, Any]] = [
    {
        "equipment_type": "ANTENNA",
        "model_code": "AX-60",
        "quantity": 3,
        "unit_weight_lbs": 60,
        "wind_area_sqft": 8,
        "mount_elevation_ft": 125,
    },
    {
        "equipment_type": "RRU",
        "model_code": "RU-55",
        "quantity": 6,
        "unit_weight_lbs": 55,
        "wind_area_sqft": 2,
        "mount_elevation_ft": 95,
    },
]


def build_colocation_chain(
    api: ApiClient,
    *,
    stage: str = "EXECUTED",
    tower: Optional[Dict[str, Any]] = None,
    ground_lease: Optional[Dict[str, Any]] = None,
    with_ground_lease: bool = True,
    tower_overrides: Optional[Dict[str, Any]] = None,
    landlord_overrides: Optional[Dict[str, Any]] = None,
    lease_overrides: Optional[Dict[str, Any]] = None,
    tenant: Optional[Dict[str, Any]] = None,
    mla: Optional[Dict[str, Any]] = None,
    tenant_overrides: Optional[Dict[str, Any]] = None,
    mla_overrides: Optional[Dict[str, Any]] = None,
    application_overrides: Optional[Dict[str, Any]] = None,
    lines: Optional[List[Dict[str, Any]]] = None,
    variant: str = "PRELIMINARY",
    engineer_headers=None,
    amendment_overrides: Optional[Dict[str, Any]] = None,
    signature_received: bool = True,
) -> Dict[str, Any]:
    """Drive one carrier's application from DRAFT to any later stage.

    Stages, in order: ``DRAFT`` (application with its equipment lines),
    ``SUBMITTED`` (branched by the tower posture), ``REVIEWED`` (one structural
    analysis issued), ``APPROVED``, ``PAPERED`` (site amendment in DRAFT) and
    ``EXECUTED``.

    Returns a dict with keys ``tower``, ``landlord``, ``ground_lease``,
    ``tenant``, ``tenant_headers``, ``mla``, ``application``, ``lines``,
    ``analysis`` and ``amendment`` — later keys are ``None`` when the requested
    stage stops short of them.
    """
    assert stage in CHAIN_STAGES, f"unknown chain stage {stage!r}"

    landlord = None
    if tower is None:
        if with_ground_lease:
            site = site_with_ground_lease(api, tower_overrides, landlord_overrides, lease_overrides)
            tower, landlord, ground_lease = (
                site["tower"],
                site["landlord"],
                site["ground_lease"],
            )
        else:
            tower = new_tower(api, **(tower_overrides or {}))

    if tenant is None or mla is None:
        carrier = carrier_with_active_lease(api, tenant_overrides, mla_overrides)
        tenant = tenant or carrier["tenant"]
        mla = mla or carrier["mla"]
    tenant_headers = make_tenant_headers(tenant["id"])

    application = new_application(
        api, tower["id"], mla["id"], tenant["id"], **(application_overrides or {})
    )
    created_lines = [
        add_equipment_line(api, application["id"], tenant["id"], **line)
        for line in (DEFAULT_LINES if lines is None else lines)
    ]

    result: Dict[str, Any] = {
        "tower": tower,
        "landlord": landlord,
        "ground_lease": ground_lease,
        "tenant": tenant,
        "tenant_headers": tenant_headers,
        "mla": mla,
        "application": application,
        "lines": created_lines,
        "analysis": None,
        "amendment": None,
    }
    if stage == "DRAFT":
        return result

    result["application"] = submit_application(api, application["id"], tenant["id"])
    if stage == "SUBMITTED":
        return result

    result["analysis"] = run_analysis(
        api, application["id"], tower["id"], variant, engineer_headers
    )
    result["application"] = read_application(api, application["id"])
    if stage == "REVIEWED":
        return result

    result["application"] = approve_application(api, application["id"])
    if stage == "APPROVED":
        return result

    amendment_payload: Dict[str, Any] = {}
    if ground_lease is not None:
        amendment_payload["term_end_date"] = ground_lease["term_end_date"]
    amendment_payload.update(amendment_overrides or {})
    result["amendment"] = paper_amendment(
        api, mla["id"], tower["id"], application["id"], **amendment_payload
    )
    result["application"] = read_application(api, application["id"])
    if stage == "PAPERED":
        return result

    result["amendment"] = execute_amendment(
        api, result["amendment"]["id"], signature_received=signature_received
    )
    result["tower"] = read_tower(api, tower["id"])
    return result


def add_carrier_to_site(
    api: ApiClient,
    site: Dict[str, Any],
    *,
    stage: str = "EXECUTED",
    **kwargs: Any,
) -> Dict[str, Any]:
    """Run another carrier's chain on an existing site."""
    return build_colocation_chain(
        api,
        stage=stage,
        tower=site["tower"],
        ground_lease=site.get("ground_lease"),
        **kwargs,
    )


# ─── Modification projects and cost shares ───────────────────────────────────


def propose_project(
    api: ApiClient, tower_id: str, analysis_id: str, headers=None, **overrides: Any
) -> Dict[str, Any]:
    return get_success_data(
        api.create_modification_project(
            factories.modification_project_payload(tower_id, analysis_id, **overrides),
            headers or ENGINEER_HEADERS,
        ),
        201,
    )


def allocate_shares(api: ApiClient, project_id: str, headers=None) -> Dict[str, Any]:
    return get_success_data(
        api.allocate_cost_shares(project_id, {}, headers or ENGINEER_HEADERS), 200
    )


def list_project_shares(api: ApiClient, project_id: str, headers=None) -> List[Dict[str, Any]]:
    return get_success_data(
        api.list_cost_shares(
            {"modification_project_id": project_id, "limit": 100}, headers or ADMIN_HEADERS
        )
    )


def share_for_tenant(
    api: ApiClient, project_id: str, tenant_id: str, headers=None
) -> Dict[str, Any]:
    """The one cost share of a project belonging to a given tenant."""
    rows = get_success_data(
        api.list_cost_shares(
            {"modification_project_id": project_id, "tenant_id": tenant_id, "limit": 100},
            headers or ADMIN_HEADERS,
        )
    )
    assert rows, f"no cost share for tenant {tenant_id} on project {project_id}"
    return rows[0]


def accept_share(api: ApiClient, share_id: str, tenant_id: str) -> Dict[str, Any]:
    return get_success_data(
        api.accept_cost_share(share_id, {}, make_tenant_headers(tenant_id)), 200
    )


def decline_share(
    api: ApiClient, share_id: str, tenant_id: str, reason: str = "capital plans withdrawn"
) -> Dict[str, Any]:
    return get_success_data(
        api.decline_cost_share(
            share_id, factories.decline_cost_share_payload(reason), make_tenant_headers(tenant_id)
        ),
        200,
    )


def quoted_analysis_with_project(
    api: ApiClient,
    *,
    tower_id: str,
    analysis_id: str,
    cost_cents: int,
    engineer_headers=None,
    project_overrides: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Quote an analysis and propose the reinforcement project it originates."""
    analysis = quote_analysis(api, analysis_id, cost_cents, engineer_headers)
    project = propose_project(
        api, tower_id, analysis_id, engineer_headers, **(project_overrides or {})
    )
    return {"analysis": analysis, "project": project}


# ─── Compliance audits ───────────────────────────────────────────────────────


def schedule_audit(api: ApiClient, tower_id: str, headers=None, **overrides: Any) -> Dict[str, Any]:
    return get_success_data(
        api.create_equipment_audit(
            factories.equipment_audit_payload(tower_id, **overrides), headers or AUDITOR_HEADERS
        ),
        201,
    )


def start_audit(api: ApiClient, audit_id: str, headers=None) -> Dict[str, Any]:
    return get_success_data(
        api.start_equipment_audit(audit_id, {}, headers or AUDITOR_HEADERS), 200
    )


def record_finding(
    api: ApiClient, audit_id: str, tenant_id: str, headers=None, **overrides: Any
) -> Dict[str, Any]:
    return get_success_data(
        api.create_audit_finding(
            audit_id, factories.audit_finding_payload(tenant_id, **overrides), headers or AUDITOR_HEADERS
        ),
        201,
    )


def finalize_audit(api: ApiClient, audit_id: str, headers=None) -> Dict[str, Any]:
    return get_success_data(
        api.finalize_equipment_audit(audit_id, {}, headers or AUDITOR_HEADERS), 200
    )


def audit_with_findings(
    api: ApiClient,
    tower_id: str,
    findings: List[Dict[str, Any]],
    *,
    audit_overrides: Optional[Dict[str, Any]] = None,
    finalize: bool = True,
    headers=None,
) -> Dict[str, Any]:
    """Schedule an audit, start it, record findings and optionally finalize it.

    Each entry of ``findings`` is a dict carrying ``tenant_id`` plus any finding
    field overrides.
    """
    audit = schedule_audit(api, tower_id, headers, **(audit_overrides or {}))
    start_audit(api, audit["id"], headers)
    recorded = []
    for finding in findings:
        payload = dict(finding)
        tenant_id = payload.pop("tenant_id")
        recorded.append(record_finding(api, audit["id"], tenant_id, headers, **payload))
    if finalize:
        audit = finalize_audit(api, audit["id"], headers)
    return {"audit": audit, "findings": recorded}


# The finding below is the smallest single-line walk-down that carries a tenant
# past the 5,000,000-cent delinquency threshold of PRD §2.12: under
# INSTALL_DATE_BASIS a 3,400-load-unit install dated 2023-02-15 found on an
# audit dated 2026-07-31 bills 41 whole months at 85,000 cents per month with
# the 1.5 penalty multiplier, i.e. 5,227,500 cents.
DELINQUENCY_FINDING_TOTAL_CENTS = 5_227_500


def make_tenant_delinquent(
    api: ApiClient, tower_id: str, tenant_id: str, headers=None
) -> Dict[str, Any]:
    """Push one tenant's balance over the delinquency threshold via an audit."""
    return audit_with_findings(
        api,
        tower_id,
        [
            {
                "tenant_id": tenant_id,
                "description": "unauthorized microwave dish at 230 ft",
                "observed_load_units": 3400,
                "installed_on_date": "2023-02-15",
                "mount_elevation_ft": 230,
            }
        ],
        audit_overrides={"audit_date": "2026-07-31", "basis": "INSTALL_DATE_BASIS"},
        finalize=True,
        headers=headers,
    )
