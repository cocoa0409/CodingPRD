"""Composite setup helpers for the Government One-Stop Approval test suite.

Most interesting test claims require the system to be in a specific
state that takes 5-15 API calls to reach: a Department + MaterialTemplate
+ CertificateTemplate set, a published MatterVersion, an Application
posted by a known applicant, IDENTITY_VERIFIED + PAYMENT_SETTLED events
to push it into UNDER_REVIEW, and one or more correction-issue /
resubmit cycles before the assertion under test.

Identity threading (PRD §2.1):

- CatalogManager, Reviewer, LeadReviewer are entity-backed by
  Department. Fixtures create real Department rows and pass the
  Department.id through make_catalog_manager_headers /
  make_reviewer_headers / make_lead_reviewer_headers so any ownership
  comparison (matter.owning_department_id == X-User-ID,
  ReviewTask.department_id == X-User-ID, escalation lead-department
  match) resolves correctly.

- PlatformAdmin, CertificateOfficer, Applicant carry opaque
  identifiers; the shared TEST_USERS constants are canonical for
  PlatformAdmin / CertificateOfficer.

- Each Application MUST be submitted with a known applicant_id so the
  same id can later be threaded through make_applicant_headers for
  withdraw / resubmit ownership comparisons (PRD §2.1: 'ownership
  checks on application-scoped reads and on withdrawal and resubmission
  compare applicant_user_id to X-User-ID').

Setup calls use get_success_data (lenient validator) so broken
preconditions surface as obvious 'Setup failed' errors rather than
confusing assertion failures inside tests.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

from prd_bench_local_runner.testing import (
    get_success_data,
    validate_paginated,
)

from .api_client import api_client
from .constants import (
    CORRECTION_WINDOW_DAYS_DEFAULT,
    DAY_SECONDS,
    WORKING_DAY_SECONDS,
)
from .factories import (
    clock_advance_payload,
    create_certificate_template_payload,
    create_department_payload,
    create_material_template_payload,
    create_matter_payload,
    create_matter_version_payload,
    decide_review_task_payload,
    deficiency_entry,
    emit_event_payload,
    issue_correction_notice_payload,
    make_routing,
    resolve_escalation_payload,
    resubmit_correction_payload,
    submit_application_payload,
    submitted_material_entry,
    unique_applicant_id,
)
from .test_users import (
    TEST_USERS,
    make_applicant_headers,
    make_catalog_manager_headers,
    make_lead_reviewer_headers,
    make_reviewer_headers,
)


# ===========================================================================
# Time helpers (PRD §2.4)
# ===========================================================================
def iso_z(dt: datetime) -> str:
    """Format a datetime as ISO 8601 UTC with three fractional digits.

    PRD §2.4: 'an ISO 8601 UTC timestamp with three fractional digits'.
    """
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    base = dt.strftime("%Y-%m-%dT%H:%M:%S")
    millis = f"{dt.microsecond // 1000:03d}"
    return f"{base}.{millis}Z"


def parse_iso(s: str) -> datetime:
    """Parse an ISO 8601 string (with optional trailing 'Z') to tz-aware."""
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    return datetime.fromisoformat(s)


def add_seconds(dt_iso: str, seconds: int) -> str:
    return iso_z(parse_iso(dt_iso) + timedelta(seconds=seconds))


def add_working_days(dt_iso: str, days: int) -> str:
    return add_seconds(dt_iso, days * WORKING_DAY_SECONDS)


def add_calendar_days(dt_iso: str, days: int) -> str:
    return add_seconds(dt_iso, days * DAY_SECONDS)


# ===========================================================================
# Clock + sweep primitives (PRD §2.14)
# ===========================================================================
def advance_clock(seconds: int,
                  admin_headers: Optional[Dict[str, str]] = None
                  ) -> Dict[str, Any]:
    """Advance the server's logical clock by `seconds` seconds.

    PRD §2.14: 'A test-only clock-advance capability (admin-restricted)
    accepts a seconds integer and advances the server's logical now()
    by that amount.'
    """
    headers = admin_headers or TEST_USERS["platform_admin_headers"]
    resp = api_client.advance_clock(clock_advance_payload(seconds), headers)
    return get_success_data(resp)


def run_sweep(admin_headers: Optional[Dict[str, str]] = None
              ) -> Dict[str, Any]:
    """Run the periodic sweep (correction-expiry, certificate-expiry,
    warning-evaluator).

    PRD §2.14: 'A test-only sweep capability (also admin-restricted)
    runs the periodic sweep on demand.'
    """
    headers = admin_headers or TEST_USERS["platform_admin_headers"]
    resp = api_client.run_sweep(headers)
    return get_success_data(resp)


# ===========================================================================
# Department bootstrap
# ===========================================================================
def create_department(
    *,
    code: Optional[str] = None,
    name: Optional[str] = None,
    parent_department_id: Optional[str] = None,
    admin_headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """Create a Department as PlatformAdmin and return the dict.

    PRD §3.1: 'A new department is registered by PlatformAdmin.'
    """
    headers = admin_headers or TEST_USERS["platform_admin_headers"]
    payload = create_department_payload(
        code=code,
        name=name,
        parent_department_id=parent_department_id,
        include_parent=parent_department_id is not None,
    )
    resp = api_client.create_department(payload, headers)
    return get_success_data(resp)


# ===========================================================================
# Template bootstrap (publishes them so they are ready to reference)
# ===========================================================================
def create_published_material_template(
    *,
    catalog_manager_headers: Dict[str, str],
    code: Optional[str] = None,
    title: Optional[str] = None,
    material_type: str = "ORIGINAL",
    e_form_schema: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Create a MaterialTemplate and publish it.

    PRD §3.3: 'New templates start in DRAFT; a separate publish step
    transitions them to PUBLISHED.' Tests need PUBLISHED templates to
    pass MatterVersion publish-time and Application submit-time checks.
    """
    payload = create_material_template_payload(
        code=code,
        title=title,
        material_type=material_type,
        e_form_schema=e_form_schema,
        include_e_form_schema=e_form_schema is not None,
    )
    resp = api_client.create_material_template(payload, catalog_manager_headers)
    template = get_success_data(resp)
    pub = api_client.publish_material_template(template["id"], catalog_manager_headers)
    return get_success_data(pub)


def create_published_certificate_template(
    *,
    cert_officer_headers: Optional[Dict[str, str]] = None,
    code: Optional[str] = None,
    body_template: Optional[str] = None,
    required_variables: Optional[List[str]] = None,
    validity_days: Optional[int] = None,
    official_seal_id: str = "SEAL-DEFAULT",
) -> Dict[str, Any]:
    """Create a CertificateTemplate and publish it.

    PRD §3.3: 'Templates begin in DRAFT; only PUBLISHED certificate
    templates can be referenced from a MatterVersion's
    certificate_template_id at publish time.'
    """
    headers = cert_officer_headers or TEST_USERS["certificate_officer_headers"]
    payload = create_certificate_template_payload(
        code=code,
        body_template=body_template,
        required_variables=required_variables,
        validity_days=validity_days,
        official_seal_id=official_seal_id,
    )
    resp = api_client.create_certificate_template(payload, headers)
    template = get_success_data(resp)
    pub = api_client.publish_certificate_template(template["id"], headers)
    return get_success_data(pub)


# ===========================================================================
# Matter + version bootstrap
# ===========================================================================
def create_matter(
    *,
    catalog_manager_headers: Dict[str, str],
    owning_department_id: str,
    code: Optional[str] = None,
    theme: str = "OTHER",
) -> Dict[str, Any]:
    """Create a Matter shell. The catalog_manager_headers MUST be built
    via make_catalog_manager_headers(owning_department_id) so the
    ownership check on subsequent edits resolves."""
    payload = create_matter_payload(
        owning_department_id=owning_department_id,
        code=code,
        theme=theme,
    )
    resp = api_client.create_matter(payload, catalog_manager_headers)
    return get_success_data(resp)


def create_matter_version_draft(
    *,
    matter_id: str,
    catalog_manager_headers: Dict[str, str],
    required_material_template_ids: List[str],
    certificate_template_id: str,
    review_routing: Dict[str, Any],
    statutory_time_limit_days: int = 15,
    committed_time_limit_days: int = 10,
    fee_amount_cents: Optional[int] = None,
    channels: Optional[List[str]] = None,
    max_correction_rounds: Optional[int] = None,
    correction_window_days: Optional[int] = None,
    warning_threshold_pct: Optional[int] = None,
    version_label: Optional[str] = None,
) -> Dict[str, Any]:
    """Create a DRAFT MatterVersion."""
    payload = create_matter_version_payload(
        required_material_template_ids=required_material_template_ids,
        certificate_template_id=certificate_template_id,
        review_routing=review_routing,
        version_label=version_label,
        statutory_time_limit_days=statutory_time_limit_days,
        committed_time_limit_days=committed_time_limit_days,
        warning_threshold_pct=warning_threshold_pct,
        fee_amount_cents=fee_amount_cents,
        channels=channels,
        max_correction_rounds=max_correction_rounds,
        correction_window_days=correction_window_days,
    )
    resp = api_client.create_matter_version(matter_id, payload, catalog_manager_headers)
    return get_success_data(resp)


def publish_matter_version(
    *,
    matter_id: str,
    version_id: str,
    catalog_manager_headers: Dict[str, str],
) -> Dict[str, Any]:
    resp = api_client.publish_matter_version(
        matter_id, version_id, catalog_manager_headers,
    )
    return get_success_data(resp)


# ===========================================================================
# Composite setup: a single-stage SERIAL routing on one department.
# ===========================================================================
def setup_single_department_published_version(
    *,
    fee_amount_cents: int = 0,
    statutory_time_limit_days: int = 15,
    committed_time_limit_days: int = 10,
    warning_threshold_pct: Optional[int] = None,
    max_correction_rounds: int = 2,
    correction_window_days: int = 7,
    channels: Optional[List[str]] = None,
    extra_material_count: int = 0,
    e_form_schema: Optional[Dict[str, Any]] = None,
    matter_code: Optional[str] = None,
) -> Dict[str, Any]:
    """Bootstrap a fully-published catalog with one department, one
    primary material template, an optional set of extra material
    templates, one certificate template, one matter, and one PUBLISHED
    MatterVersion that uses single-stage SERIAL routing on the lone
    department.

    Returns a context dict carrying:
        department, owning_department_id (Department.id),
        catalog_manager_headers (built from owning_department_id),
        reviewer_headers (built from owning_department_id),
        material_template (primary), extra_material_templates,
        all_required_material_template_ids,
        certificate_template, matter, version.
    """
    department = create_department()
    catalog_manager_headers = make_catalog_manager_headers(department["id"])
    reviewer_headers = make_reviewer_headers(department["id"])

    primary_material = create_published_material_template(
        catalog_manager_headers=catalog_manager_headers,
        e_form_schema=e_form_schema,
    )
    extra_materials: List[Dict[str, Any]] = []
    for _ in range(extra_material_count):
        extra_materials.append(
            create_published_material_template(
                catalog_manager_headers=catalog_manager_headers,
            )
        )
    cert_template = create_published_certificate_template()

    matter = create_matter(
        catalog_manager_headers=catalog_manager_headers,
        owning_department_id=department["id"],
        code=matter_code,
    )

    routing = make_routing(
        mode="SERIAL",
        lead_department_id=department["id"],
        stages=[{"department_id": department["id"], "sla_days": 5}],
        aggregation_rule=None,
    )
    required_ids = [primary_material["id"]] + [m["id"] for m in extra_materials]
    version = create_matter_version_draft(
        matter_id=matter["id"],
        catalog_manager_headers=catalog_manager_headers,
        required_material_template_ids=required_ids,
        certificate_template_id=cert_template["id"],
        review_routing=routing,
        statutory_time_limit_days=statutory_time_limit_days,
        committed_time_limit_days=committed_time_limit_days,
        fee_amount_cents=fee_amount_cents,
        channels=channels,
        max_correction_rounds=max_correction_rounds,
        correction_window_days=correction_window_days,
        warning_threshold_pct=warning_threshold_pct,
    )
    version = publish_matter_version(
        matter_id=matter["id"],
        version_id=version["id"],
        catalog_manager_headers=catalog_manager_headers,
    )
    return {
        "department": department,
        "owning_department_id": department["id"],
        "catalog_manager_headers": catalog_manager_headers,
        "reviewer_headers": reviewer_headers,
        "material_template": primary_material,
        "extra_material_templates": extra_materials,
        "all_required_material_template_ids": required_ids,
        "certificate_template": cert_template,
        "matter": matter,
        "version": version,
    }


# ===========================================================================
# Composite setup: parallel routing on N departments (with lead).
# ===========================================================================
def setup_parallel_routing_published_version(
    *,
    department_count: int = 2,
    aggregation_rule: str = "ALL_AGREE",
    fee_amount_cents: int = 0,
    statutory_time_limit_days: int = 15,
    committed_time_limit_days: int = 10,
    max_correction_rounds: int = 2,
    correction_window_days: int = 7,
    parent_for_lead: bool = False,
) -> Dict[str, Any]:
    """Bootstrap a published MatterVersion with PARALLEL routing across
    `department_count` departments. The first department is the lead.

    Returns a context dict carrying:
        departments (list, lead first), lead_department,
        owning_department_id, catalog_manager_headers (lead-owned),
        reviewer_headers_by_dept_id (dict),
        lead_reviewer_headers, material_template,
        certificate_template, matter, version, parent_department
        (only when parent_for_lead=True).

    PRD §3.9: 'A LeadReviewer of the lead department of a PARALLEL
    routing whose aggregation_rule is not LEAD_DECIDES may escalate.'
    With parent_for_lead=True, the lead department is created with a
    parent department so escalation routes to that parent rather than
    PlatformAdmin.
    """
    if department_count < 1:
        raise ValueError("department_count must be >= 1")

    parent_department: Optional[Dict[str, Any]] = None
    if parent_for_lead:
        parent_department = create_department()

    departments: List[Dict[str, Any]] = []
    for i in range(department_count):
        dept = create_department(
            parent_department_id=(
                parent_department["id"]
                if i == 0 and parent_department is not None
                else None
            ),
        )
        departments.append(dept)
    lead_department = departments[0]

    # Catalog manager identity = lead department.id.
    catalog_manager_headers = make_catalog_manager_headers(lead_department["id"])

    primary_material = create_published_material_template(
        catalog_manager_headers=catalog_manager_headers,
    )
    cert_template = create_published_certificate_template()
    matter = create_matter(
        catalog_manager_headers=catalog_manager_headers,
        owning_department_id=lead_department["id"],
    )

    stages = [
        {"department_id": d["id"], "sla_days": 5} for d in departments
    ]
    routing = make_routing(
        mode="PARALLEL",
        lead_department_id=lead_department["id"],
        stages=stages,
        aggregation_rule=aggregation_rule,
    )
    version = create_matter_version_draft(
        matter_id=matter["id"],
        catalog_manager_headers=catalog_manager_headers,
        required_material_template_ids=[primary_material["id"]],
        certificate_template_id=cert_template["id"],
        review_routing=routing,
        statutory_time_limit_days=statutory_time_limit_days,
        committed_time_limit_days=committed_time_limit_days,
        fee_amount_cents=fee_amount_cents,
        max_correction_rounds=max_correction_rounds,
        correction_window_days=correction_window_days,
    )
    version = publish_matter_version(
        matter_id=matter["id"],
        version_id=version["id"],
        catalog_manager_headers=catalog_manager_headers,
    )

    reviewer_headers_by_dept_id = {
        d["id"]: make_reviewer_headers(d["id"]) for d in departments
    }
    lead_reviewer_headers = make_lead_reviewer_headers(lead_department["id"])
    return {
        "departments": departments,
        "lead_department": lead_department,
        "owning_department_id": lead_department["id"],
        "parent_department": parent_department,
        "catalog_manager_headers": catalog_manager_headers,
        "reviewer_headers_by_dept_id": reviewer_headers_by_dept_id,
        "lead_reviewer_headers": lead_reviewer_headers,
        "material_template": primary_material,
        "certificate_template": cert_template,
        "matter": matter,
        "version": version,
    }


# ===========================================================================
# Composite setup: SERIAL routing on N departments.
# ===========================================================================
def setup_serial_routing_published_version(
    *,
    department_count: int = 2,
    fee_amount_cents: int = 0,
    statutory_time_limit_days: int = 15,
    committed_time_limit_days: int = 10,
    sla_days_per_stage: int = 5,
) -> Dict[str, Any]:
    """Bootstrap a published MatterVersion with SERIAL routing across
    `department_count` departments. The lead is the first stage."""
    if department_count < 1:
        raise ValueError("department_count must be >= 1")
    departments = [create_department() for _ in range(department_count)]
    lead_department = departments[0]
    catalog_manager_headers = make_catalog_manager_headers(lead_department["id"])
    primary_material = create_published_material_template(
        catalog_manager_headers=catalog_manager_headers,
    )
    cert_template = create_published_certificate_template()
    matter = create_matter(
        catalog_manager_headers=catalog_manager_headers,
        owning_department_id=lead_department["id"],
    )
    stages = [
        {"department_id": d["id"], "sla_days": sla_days_per_stage}
        for d in departments
    ]
    routing = make_routing(
        mode="SERIAL",
        lead_department_id=lead_department["id"],
        stages=stages,
        aggregation_rule=None,
    )
    version = create_matter_version_draft(
        matter_id=matter["id"],
        catalog_manager_headers=catalog_manager_headers,
        required_material_template_ids=[primary_material["id"]],
        certificate_template_id=cert_template["id"],
        review_routing=routing,
        statutory_time_limit_days=statutory_time_limit_days,
        committed_time_limit_days=committed_time_limit_days,
        fee_amount_cents=fee_amount_cents,
    )
    version = publish_matter_version(
        matter_id=matter["id"],
        version_id=version["id"],
        catalog_manager_headers=catalog_manager_headers,
    )
    reviewer_headers_by_dept_id = {
        d["id"]: make_reviewer_headers(d["id"]) for d in departments
    }
    return {
        "departments": departments,
        "lead_department": lead_department,
        "owning_department_id": lead_department["id"],
        "catalog_manager_headers": catalog_manager_headers,
        "reviewer_headers_by_dept_id": reviewer_headers_by_dept_id,
        "material_template": primary_material,
        "certificate_template": cert_template,
        "matter": matter,
        "version": version,
    }


# ===========================================================================
# Application bootstrap helpers
# ===========================================================================
def submit_application(
    *,
    ctx: Dict[str, Any],
    applicant_id: Optional[str] = None,
    channel: str = "ONLINE",
    e_form_payload_for_primary: Optional[Dict[str, Any]] = None,
    extra_material_payload_overrides: Optional[List[Dict[str, Any]]] = None,
) -> Tuple[Dict[str, Any], Dict[str, str], str]:
    """Submit an Application against ctx['version'].

    PRD §3.4: 'A successful submit creates an Application whose
    review_status is SUBMITTED, whose applicant_user_id is the
    X-User-ID of the submitting principal.'

    Returns (application, applicant_headers, applicant_id) so any
    downstream ownership-gated call (withdraw / resubmit) can use
    applicant_headers. Identity threading: applicant_headers is built
    via make_applicant_headers(applicant_id) where applicant_id is the
    same id stamped on Application.applicant_user_id.
    """
    applicant_id = applicant_id or unique_applicant_id()
    applicant_headers = make_applicant_headers(applicant_id)
    materials = [
        submitted_material_entry(
            ctx["material_template"]["id"],
            e_form_payload=e_form_payload_for_primary,
        )
    ]
    extra = extra_material_payload_overrides or []
    for i, mt in enumerate(ctx.get("extra_material_templates", []) or []):
        if i < len(extra):
            materials.append(extra[i])
        else:
            materials.append(submitted_material_entry(mt["id"]))
    payload = submit_application_payload(
        matter_version_id=ctx["version"]["id"],
        submitted_materials=materials,
        channel=channel,
    )
    resp = api_client.submit_application(payload, applicant_headers)
    return get_success_data(resp), applicant_headers, applicant_id


def emit_identity_verified(application_id: str,
                           admin_headers: Optional[Dict[str, str]] = None
                           ) -> Dict[str, Any]:
    """PRD §3.5: 'An IDENTITY_VERIFIED event flips identity_verified to
    true on the named application.'
    """
    headers = admin_headers or TEST_USERS["platform_admin_headers"]
    resp = api_client.emit_event(
        emit_event_payload("IDENTITY_VERIFIED", application_id), headers
    )
    return get_success_data(resp)


def emit_payment_settled(application_id: str,
                         admin_headers: Optional[Dict[str, str]] = None
                         ) -> Dict[str, Any]:
    """PRD §3.5: 'A PAYMENT_SETTLED event flips payment_status from
    PENDING to PAID.'
    """
    headers = admin_headers or TEST_USERS["platform_admin_headers"]
    resp = api_client.emit_event(
        emit_event_payload("PAYMENT_SETTLED", application_id), headers
    )
    return get_success_data(resp)


def drive_to_under_review(
    *,
    ctx: Dict[str, Any],
    application: Dict[str, Any],
    fee_amount_cents: int = 0,
) -> Dict[str, Any]:
    """Walk an application from SUBMITTED to UNDER_REVIEW.

    PRD §3.5: 'The instant both prerequisites hold ... the system
    transitions the application from SUBMITTED to UNDER_REVIEW.' Always
    emit IDENTITY_VERIFIED. Emit PAYMENT_SETTLED only when fee>0
    (fee==0 already auto-flips payment_status to PAID at submit time
    per PRD §3.4).
    """
    emit_identity_verified(application["id"])
    if fee_amount_cents > 0:
        emit_payment_settled(application["id"])
    refreshed = get_success_data(
        api_client.get_application(
            application["id"], TEST_USERS["platform_admin_headers"],
        )
    )
    return refreshed


def setup_application_under_review_single_dept(
    *,
    fee_amount_cents: int = 0,
    statutory_time_limit_days: int = 15,
    committed_time_limit_days: int = 10,
    warning_threshold_pct: Optional[int] = None,
    correction_window_days: int = 7,
    max_correction_rounds: int = 2,
    channel: str = "ONLINE",
    e_form_schema: Optional[Dict[str, Any]] = None,
    e_form_payload_for_primary: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """End-to-end shortcut: bootstrap a single-department version,
    submit an application, walk it to UNDER_REVIEW, and return:
      - everything from setup_single_department_published_version()
      - application (refreshed dict, status UNDER_REVIEW)
      - applicant_headers / applicant_id
      - review_tasks (list of dicts, one stage)
    """
    ctx = setup_single_department_published_version(
        fee_amount_cents=fee_amount_cents,
        statutory_time_limit_days=statutory_time_limit_days,
        committed_time_limit_days=committed_time_limit_days,
        warning_threshold_pct=warning_threshold_pct,
        correction_window_days=correction_window_days,
        max_correction_rounds=max_correction_rounds,
        e_form_schema=e_form_schema,
    )
    application, applicant_headers, applicant_id = submit_application(
        ctx=ctx,
        channel=channel,
        e_form_payload_for_primary=e_form_payload_for_primary,
    )
    application = drive_to_under_review(
        ctx=ctx, application=application, fee_amount_cents=fee_amount_cents,
    )
    review_tasks = list_review_tasks(application["id"], ctx["reviewer_headers"])
    ctx["application"] = application
    ctx["applicant_headers"] = applicant_headers
    ctx["applicant_id"] = applicant_id
    ctx["review_tasks"] = review_tasks
    return ctx


def setup_application_under_review_parallel(
    *,
    department_count: int = 2,
    aggregation_rule: str = "ALL_AGREE",
    fee_amount_cents: int = 0,
    statutory_time_limit_days: int = 15,
    committed_time_limit_days: int = 10,
    correction_window_days: int = 7,
    max_correction_rounds: int = 2,
    parent_for_lead: bool = False,
) -> Dict[str, Any]:
    """End-to-end shortcut: PARALLEL routing variant. Returns a context
    dict carrying everything from setup_parallel_routing_published_version
    plus application, applicant_headers, applicant_id, review_tasks.
    """
    ctx = setup_parallel_routing_published_version(
        department_count=department_count,
        aggregation_rule=aggregation_rule,
        fee_amount_cents=fee_amount_cents,
        statutory_time_limit_days=statutory_time_limit_days,
        committed_time_limit_days=committed_time_limit_days,
        correction_window_days=correction_window_days,
        max_correction_rounds=max_correction_rounds,
        parent_for_lead=parent_for_lead,
    )
    application, applicant_headers, applicant_id = submit_application(
        ctx=ctx,
    )
    application = drive_to_under_review(
        ctx=ctx, application=application, fee_amount_cents=fee_amount_cents,
    )
    review_tasks = list_review_tasks(
        application["id"], ctx["lead_reviewer_headers"]
    )
    ctx["application"] = application
    ctx["applicant_headers"] = applicant_headers
    ctx["applicant_id"] = applicant_id
    ctx["review_tasks"] = review_tasks
    return ctx


def setup_application_under_review_serial(
    *,
    department_count: int = 2,
    fee_amount_cents: int = 0,
    statutory_time_limit_days: int = 15,
    committed_time_limit_days: int = 10,
) -> Dict[str, Any]:
    """End-to-end shortcut: SERIAL routing variant."""
    ctx = setup_serial_routing_published_version(
        department_count=department_count,
        fee_amount_cents=fee_amount_cents,
        statutory_time_limit_days=statutory_time_limit_days,
        committed_time_limit_days=committed_time_limit_days,
    )
    application, applicant_headers, applicant_id = submit_application(ctx=ctx)
    application = drive_to_under_review(
        ctx=ctx, application=application, fee_amount_cents=fee_amount_cents,
    )
    review_tasks = list_review_tasks(
        application["id"], TEST_USERS["platform_admin_headers"],
    )
    ctx["application"] = application
    ctx["applicant_headers"] = applicant_headers
    ctx["applicant_id"] = applicant_id
    ctx["review_tasks"] = review_tasks
    return ctx


# ===========================================================================
# Read helpers
# ===========================================================================
def list_review_tasks(application_id: str,
                      headers: Dict[str, str]) -> List[Dict[str, Any]]:
    resp = api_client.list_review_tasks(application_id, headers)
    data, _meta = validate_paginated(resp)
    # Sort stable by stage_index then created_at for deterministic
    # downstream selection.
    data.sort(key=lambda t: (t.get("stage_index", 0), t.get("created_at", "")))
    return data


def list_correction_notices(application_id: str,
                            headers: Dict[str, str],
                            ) -> List[Dict[str, Any]]:
    resp = api_client.list_correction_notices(application_id, headers)
    data, _meta = validate_paginated(resp)
    return data


def get_application(application_id: str,
                    headers: Optional[Dict[str, str]] = None
                    ) -> Dict[str, Any]:
    headers = headers or TEST_USERS["platform_admin_headers"]
    resp = api_client.get_application(application_id, headers)
    return get_success_data(resp)


def list_audit_logs_filtered(headers: Optional[Dict[str, str]] = None,
                             *,
                             target_entity: Optional[str] = None,
                             target_id: Optional[str] = None,
                             action: Optional[str] = None,
                             ) -> List[Dict[str, Any]]:
    headers = headers or TEST_USERS["platform_admin_headers"]
    params: Dict[str, Any] = {"limit": 100}
    if target_entity is not None:
        params["target_entity"] = target_entity
    if target_id is not None:
        params["target_id"] = target_id
    if action is not None:
        params["action"] = action
    resp = api_client.list_audit_logs(headers, params=params)
    data, _meta = validate_paginated(resp)
    return data


# ===========================================================================
# Decision / correction / escalation helpers
# ===========================================================================
def decide(review_task_id: str,
           decision: str,
           reviewer_headers: Dict[str, str],
           opinion_text: Optional[str] = None,
           ) -> Dict[str, Any]:
    """Wrap POST /review-tasks/{id}/decide. reviewer_headers MUST be
    built via make_reviewer_headers(department_id) of the task's
    department, otherwise PRD §2.1 ownership rejects the call."""
    resp = api_client.decide_review_task(
        review_task_id,
        decide_review_task_payload(
            decision, opinion_text=opinion_text,
            include_opinion=opinion_text is not None,
        ),
        reviewer_headers,
    )
    return get_success_data(resp)


def issue_correction_notice(
    application_id: str,
    *,
    deficiencies: List[Dict[str, Any]],
    issued_by_review_task_id: str,
    reviewer_headers: Dict[str, str],
) -> Dict[str, Any]:
    """Wrap POST /applications/{id}/correction-notices."""
    payload = issue_correction_notice_payload(
        deficiencies=deficiencies,
        issued_by_review_task_id=issued_by_review_task_id,
    )
    resp = api_client.issue_correction_notice(
        application_id, payload, reviewer_headers,
    )
    return get_success_data(resp)


def resubmit_correction(
    application_id: str,
    correction_notice_id: str,
    *,
    submitted_materials: List[Dict[str, Any]],
    applicant_headers: Dict[str, str],
) -> Dict[str, Any]:
    """Wrap POST /applications/{id}/correction-notices/{cid}/resubmit."""
    payload = resubmit_correction_payload(submitted_materials=submitted_materials)
    resp = api_client.resubmit_correction(
        application_id, correction_notice_id, payload, applicant_headers,
    )
    return get_success_data(resp)


def issue_correction_for_primary_material(
    *,
    ctx: Dict[str, Any],
    application_id: Optional[str] = None,
    review_task: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Convenience wrapper: issue a 1-deficiency notice referencing the
    primary material template, attributed to the lead-department's only
    review task. Returns the CorrectionNotice."""
    application_id = application_id or ctx["application"]["id"]
    if review_task is None:
        # Pick the review task owned by the reviewer_headers in ctx.
        review_tasks = list_review_tasks(application_id, ctx.get("reviewer_headers")
                                         or ctx.get("lead_reviewer_headers"))
        in_progress = [t for t in review_tasks if t["status"] == "IN_PROGRESS"]
        if not in_progress:
            raise AssertionError(
                "Setup failed: no IN_PROGRESS ReviewTask available to issue correction"
            )
        review_task = in_progress[0]
    reviewer_headers = ctx.get("reviewer_headers") or ctx.get(
        "reviewer_headers_by_dept_id", {}
    ).get(review_task["department_id"]) or ctx.get("lead_reviewer_headers")
    return issue_correction_notice(
        application_id,
        deficiencies=[deficiency_entry(ctx["material_template"]["id"], "missing")],
        issued_by_review_task_id=review_task["id"],
        reviewer_headers=reviewer_headers,
    )


def resubmit_primary_material(
    *,
    ctx: Dict[str, Any],
    correction_notice_id: str,
    application_id: Optional[str] = None,
    applicant_headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """Convenience wrapper: resubmit covering the primary material."""
    application_id = application_id or ctx["application"]["id"]
    applicant_headers = applicant_headers or ctx["applicant_headers"]
    materials = [
        submitted_material_entry(ctx["material_template"]["id"])
    ]
    for mt in ctx.get("extra_material_templates", []) or []:
        materials.append(submitted_material_entry(mt["id"]))
    return resubmit_correction(
        application_id, correction_notice_id,
        submitted_materials=materials,
        applicant_headers=applicant_headers,
    )


def escalate(application_id: str,
             lead_reviewer_headers: Dict[str, str]) -> Dict[str, Any]:
    """Wrap POST /applications/{id}/escalate."""
    resp = api_client.escalate_application(application_id, lead_reviewer_headers)
    return get_success_data(resp)


def resolve_escalation(application_id: str,
                       decision: str,
                       admin_headers: Optional[Dict[str, str]] = None,
                       ) -> Dict[str, Any]:
    headers = admin_headers or TEST_USERS["platform_admin_headers"]
    resp = api_client.resolve_escalation(
        application_id, resolve_escalation_payload(decision), headers,
    )
    return get_success_data(resp)


# ===========================================================================
# Tier 4: cumulative state -- application carried through correction rounds.
# ===========================================================================
def setup_application_at_correction_round(
    *,
    target_round: int,
    fee_amount_cents: int = 1000,
    max_correction_rounds: int = 2,
    correction_window_days: int = 7,
    statutory_time_limit_days: int = 15,
    committed_time_limit_days: int = 10,
    leave_open_at_target: bool = False,
) -> Dict[str, Any]:
    """Bring an application to a state where Application.correction_round
    has reached `target_round`.

    Each round = (issue correction notice -> Application enters
    AWAITING_CORRECTION) followed by (applicant resubmits -> Application
    returns to UNDER_REVIEW). With leave_open_at_target=True the LAST
    round leaves the notice OPEN (Application stays in
    AWAITING_CORRECTION). Useful for fee-breakdown tests at
    correction_round in {0, 1, 2, 3} and for max-rounds boundary tests.
    """
    if target_round < 0:
        raise ValueError("target_round must be >= 0")
    if target_round > max_correction_rounds and not leave_open_at_target:
        # allowed: bumping correction_round to a value above the cap
        # itself fails, so the caller asks us to walk to max and stop.
        target_round = max_correction_rounds
    ctx = setup_application_under_review_single_dept(
        fee_amount_cents=fee_amount_cents,
        max_correction_rounds=max_correction_rounds,
        correction_window_days=correction_window_days,
        statutory_time_limit_days=statutory_time_limit_days,
        committed_time_limit_days=committed_time_limit_days,
    )
    notices: List[Dict[str, Any]] = []
    for r in range(target_round):
        notice = issue_correction_for_primary_material(ctx=ctx)
        notices.append(notice)
        is_last = (r == target_round - 1)
        if is_last and leave_open_at_target:
            break
        # Resubmit to bring Application back to UNDER_REVIEW so the next
        # correction can be issued.
        resubmit_primary_material(
            ctx=ctx, correction_notice_id=notice["id"],
        )
    refreshed = get_application(ctx["application"]["id"])
    ctx["application"] = refreshed
    ctx["correction_notices"] = notices
    return ctx


# ===========================================================================
# Tier 5: terminal states (APPROVED with Certificate, REJECTED, WITHDRAWN).
# ===========================================================================
def setup_approved_application_with_certificate(
    *,
    fee_amount_cents: int = 0,
    validity_days: int = 1,
    statutory_time_limit_days: int = 15,
    committed_time_limit_days: int = 10,
) -> Dict[str, Any]:
    """End-to-end approval: walk through a single-stage SERIAL route,
    AGREE the only review task, return ctx including the issued
    Certificate.
    """
    department = create_department()
    catalog_manager_headers = make_catalog_manager_headers(department["id"])
    reviewer_headers = make_reviewer_headers(department["id"])

    primary_material = create_published_material_template(
        catalog_manager_headers=catalog_manager_headers,
    )
    cert_template = create_published_certificate_template(
        validity_days=validity_days,
    )
    matter = create_matter(
        catalog_manager_headers=catalog_manager_headers,
        owning_department_id=department["id"],
    )
    routing = make_routing(
        mode="SERIAL",
        lead_department_id=department["id"],
        stages=[{"department_id": department["id"], "sla_days": 5}],
        aggregation_rule=None,
    )
    version = create_matter_version_draft(
        matter_id=matter["id"],
        catalog_manager_headers=catalog_manager_headers,
        required_material_template_ids=[primary_material["id"]],
        certificate_template_id=cert_template["id"],
        review_routing=routing,
        statutory_time_limit_days=statutory_time_limit_days,
        committed_time_limit_days=committed_time_limit_days,
        fee_amount_cents=fee_amount_cents,
    )
    version = publish_matter_version(
        matter_id=matter["id"],
        version_id=version["id"],
        catalog_manager_headers=catalog_manager_headers,
    )
    ctx = {
        "department": department,
        "owning_department_id": department["id"],
        "catalog_manager_headers": catalog_manager_headers,
        "reviewer_headers": reviewer_headers,
        "material_template": primary_material,
        "extra_material_templates": [],
        "all_required_material_template_ids": [primary_material["id"]],
        "certificate_template": cert_template,
        "matter": matter,
        "version": version,
    }
    application, applicant_headers, applicant_id = submit_application(ctx=ctx)
    application = drive_to_under_review(
        ctx=ctx, application=application, fee_amount_cents=fee_amount_cents,
    )
    tasks = list_review_tasks(application["id"], reviewer_headers)
    decide(tasks[0]["id"], "AGREED", reviewer_headers, opinion_text="ok")
    application = get_application(application["id"])
    cert_resp = api_client.get_application_certificate(
        application["id"], TEST_USERS["platform_admin_headers"],
    )
    certificate = get_success_data(cert_resp)
    ctx["application"] = application
    ctx["applicant_headers"] = applicant_headers
    ctx["applicant_id"] = applicant_id
    ctx["review_tasks"] = tasks
    ctx["certificate"] = certificate
    return ctx


__all__ = [
    "iso_z",
    "parse_iso",
    "add_seconds",
    "add_working_days",
    "add_calendar_days",
    "advance_clock",
    "run_sweep",
    "create_department",
    "create_published_material_template",
    "create_published_certificate_template",
    "create_matter",
    "create_matter_version_draft",
    "publish_matter_version",
    "setup_single_department_published_version",
    "setup_parallel_routing_published_version",
    "setup_serial_routing_published_version",
    "submit_application",
    "emit_identity_verified",
    "emit_payment_settled",
    "drive_to_under_review",
    "setup_application_under_review_single_dept",
    "setup_application_under_review_parallel",
    "setup_application_under_review_serial",
    "list_review_tasks",
    "list_correction_notices",
    "get_application",
    "list_audit_logs_filtered",
    "decide",
    "issue_correction_notice",
    "resubmit_correction",
    "issue_correction_for_primary_material",
    "resubmit_primary_material",
    "escalate",
    "resolve_escalation",
    "setup_application_at_correction_round",
    "setup_approved_application_with_certificate",
]
