"""Composite setup helpers.

Every test starts against an empty database, so these helpers build complete
precondition chains (developer -> cluster -> project -> deposit -> milestones
-> study -> publish/finalize -> agreement -> execute) out of PRD-declared
endpoints only.

Identity threading: Developer is entity-backed by Developer, so every
ownership-gated call uses make_developer_headers(developer["id"]) — never the
shared fallback constant.
"""
from prd_bench_local_runner.testing import get_success_data, validate_paginated

from .api_client import api_client
from .factories import (
    create_agreement_payload,
    create_cluster_group_payload,
    create_curtailment_limit_payload,
    create_developer_payload,
    create_deposit_payload,
    create_extension_payload,
    create_milestone_submission_payload,
    create_project_payload,
    create_resubmit_payload,
    create_review_payload,
    create_study_payload,
    create_transparency_report_payload,
)
from .test_users import (
    TEST_USERS,
    make_developer_headers,
)

ADMIN = TEST_USERS["queue_admin_headers"]
ENGINEER = TEST_USERS["study_engineer_headers"]
REGULATOR = TEST_USERS["regulator_headers"]

DEFAULT_WINDOW_OPEN = "2026-08-01T00:00:00Z"
DEFAULT_WINDOW_CLOSE = "2026-09-01T00:00:00Z"
DEFAULT_TARGET_COD = "2027-06-01T00:00:00Z"


# ---------------------------------------------------------------------------
# Tier 0: single-resource creation
# ---------------------------------------------------------------------------

def create_developer(legal_name="Acme Renewables LLC",
                     contact_email="queue@acme.example", developer_type="IPP"):
    resp = api_client.create_developer(
        create_developer_payload(legal_name=legal_name, contact_email=contact_email,
                                 developer_type=developer_type), ADMIN)
    return get_success_data(resp)


def create_cluster_group(name="Cluster 2026-A", region="WEST",
                         application_window_open=DEFAULT_WINDOW_OPEN,
                         application_window_close=DEFAULT_WINDOW_CLOSE,
                         capacity_mw=200):
    resp = api_client.create_cluster_group(
        create_cluster_group_payload(
            name=name, region=region,
            application_window_open=application_window_open,
            application_window_close=application_window_close,
            capacity_mw=capacity_mw), ADMIN)
    return get_success_data(resp)


def setup_developer_and_cluster(cluster_capacity_mw=200, region="WEST",
                                name="Cluster 2026-A",
                                application_window_open=DEFAULT_WINDOW_OPEN,
                                application_window_close=DEFAULT_WINDOW_CLOSE,
                                developer_name="Acme Renewables LLC"):
    """One onboarded developer + one FORMING cluster. Returns (developer, cluster)."""
    developer = create_developer(legal_name=developer_name)
    cluster = create_cluster_group(
        name=name, region=region,
        application_window_open=application_window_open,
        application_window_close=application_window_close,
        capacity_mw=cluster_capacity_mw)
    return developer, cluster


def create_project(developer_id, cluster_group_id, project_name="P1",
                   technology="SOLAR", capacity_mw=10, service_type="ENERGY_ONLY",
                   point_of_interconnection="SUB-1", extra_fields=None):
    payload = create_project_payload(
        developer_id, cluster_group_id, project_name=project_name,
        technology=technology, capacity_mw=capacity_mw, service_type=service_type,
        point_of_interconnection=point_of_interconnection)
    if extra_fields:
        payload.update(extra_fields)
    resp = api_client.create_project(payload, make_developer_headers(developer_id))
    return get_success_data(resp)


# ---------------------------------------------------------------------------
# Tier 1: project state progression (SUBMITTED -> QUEUED -> READY)
# ---------------------------------------------------------------------------

def post_deposit(project_id, developer_id, amount_cents):
    resp = api_client.post_deposit(
        project_id, create_deposit_payload(amount_cents),
        make_developer_headers(developer_id))
    return get_success_data(resp)


def post_full_deposit(project, developer_id):
    """Post exactly the project's required deposit; promotes SUBMITTED -> QUEUED."""
    return post_deposit(project["id"], developer_id, project["deposit_required_cents"])


def create_queued_project(developer_id, cluster_group_id, **kwargs):
    """Project with its full deposit posted. Returns the project (QUEUED)."""
    project = create_project(developer_id, cluster_group_id, **kwargs)
    post_full_deposit(project, developer_id)
    return get_project(project["id"])


def submit_milestone(project_id, developer_id, milestone_type,
                     evidence_uri="s3://ev/site.pdf"):
    resp = api_client.create_milestone_submission(
        project_id,
        create_milestone_submission_payload(milestone_type=milestone_type,
                                            evidence_uri=evidence_uri),
        make_developer_headers(developer_id))
    return get_success_data(resp)


def review_milestone(submission_id, decision, review_note=None):
    resp = api_client.review_milestone_submission(
        submission_id, create_review_payload(decision, review_note=review_note), ADMIN)
    return get_success_data(resp)


def resubmit_milestone(submission_id, developer_id, evidence_uri):
    resp = api_client.resubmit_milestone_submission(
        submission_id, create_resubmit_payload(evidence_uri),
        make_developer_headers(developer_id))
    return get_success_data(resp)


def satisfy_readiness(project_id, developer_id, evidence_prefix="s3://ev/p"):
    """Submit and accept both required milestone types. Returns the two submissions."""
    site = submit_milestone(project_id, developer_id, "SITE_CONTROL",
                            evidence_uri=f"{evidence_prefix}-site.pdf")
    tech = submit_milestone(project_id, developer_id, "TECHNICAL_DATA",
                            evidence_uri=f"{evidence_prefix}-tech.pdf")
    site = review_milestone(site["id"], "ACCEPTED")
    tech = review_milestone(tech["id"], "ACCEPTED")
    return site, tech


def create_ready_project(developer_id, cluster_group_id, evidence_prefix="s3://ev/p",
                         **kwargs):
    """Project with full deposit and both milestone types accepted (READY)."""
    project = create_queued_project(developer_id, cluster_group_id, **kwargs)
    satisfy_readiness(project["id"], developer_id, evidence_prefix=evidence_prefix)
    return get_project(project["id"])


# ---------------------------------------------------------------------------
# Tier 2: study lifecycle (scope -> publish -> finalize)
# ---------------------------------------------------------------------------

def scope_study(cluster_group_id, total_cost_cents=1000000):
    resp = api_client.create_study(
        cluster_group_id, create_study_payload(total_cost_cents), ENGINEER)
    return get_success_data(resp)


def publish_results(study_id):
    return get_success_data(api_client.publish_study_results(study_id, ENGINEER))


def finalize_study(study_id):
    return get_success_data(api_client.finalize_study(study_id, ENGINEER))


def setup_study_scenario(member_specs, total_cost_cents=1000000, publish=False,
                         finalize=False, cluster_capacity_mw=200, region="WEST",
                         cluster_name="Cluster 2026-A"):
    """One developer + one cluster + N READY member projects, then the cluster
    study is scoped. member_specs: list of dicts accepted by create_project
    (project_name, technology, capacity_mw, service_type, point_of_interconnection).

    Returns dict(developer, cluster, projects, study). With publish=True the
    study is RESULTS_PUBLISHED and members are STUDY_COMPLETE; finalize=True
    additionally finalizes the study (cluster STUDY_COMPLETE).
    """
    developer, cluster = setup_developer_and_cluster(
        cluster_capacity_mw=cluster_capacity_mw, region=region, name=cluster_name)
    projects = []
    for i, spec in enumerate(member_specs, start=1):
        spec.setdefault("project_name", f"P{i}")
        spec.setdefault("point_of_interconnection", f"SUB-{i}")
        projects.append(create_ready_project(
            developer["id"], cluster["id"],
            evidence_prefix=f"s3://ev/p{i}", **spec))
    study = scope_study(cluster["id"], total_cost_cents=total_cost_cents)
    if publish:
        study = publish_results(study["id"])
    if finalize:
        study = finalize_study(study["id"])
    projects = [get_project(p["id"]) for p in projects]
    return {"developer": developer, "cluster": get_cluster_group(cluster["id"]),
            "projects": projects, "study": study}


# ---------------------------------------------------------------------------
# Tier 3: agreements
# ---------------------------------------------------------------------------

def issue_agreement(project_id, target_cod=DEFAULT_TARGET_COD, max_injection_mw=None,
                    curtailment_hours_cap=0, expected_project_version=None):
    """Issue an agreement, defaulting the OCC version to a fresh read and the
    injection limit to the project's nameplate. Returns the ISSUED agreement."""
    project = get_project(project_id)
    if expected_project_version is None:
        expected_project_version = project["version"]
    if max_injection_mw is None:
        max_injection_mw = project["capacity_mw"]
    resp = api_client.issue_agreement(
        project_id,
        create_agreement_payload(
            expected_project_version, target_cod=target_cod,
            max_injection_mw=max_injection_mw,
            curtailment_hours_cap=curtailment_hours_cap),
        ADMIN)
    return get_success_data(resp)


def execute_agreement(agreement_id, developer_id):
    return get_success_data(api_client.execute_agreement(
        agreement_id, make_developer_headers(developer_id)))


def setup_project_agreement_pending(target_cod=DEFAULT_TARGET_COD, capacity_mw=10,
                                    technology="SOLAR", service_type="ENERGY_ONLY",
                                    curtailment_hours_cap=0, total_cost_cents=1000000,
                                    finalize=True):
    """Single-project cluster walked to AGREEMENT_PENDING (study published, and
    finalized unless finalize=False). Returns dict(developer, cluster, project,
    study, agreement)."""
    scenario = setup_study_scenario(
        [{"capacity_mw": capacity_mw, "technology": technology,
          "service_type": service_type}],
        total_cost_cents=total_cost_cents, publish=True, finalize=finalize)
    project = scenario["projects"][0]
    agreement = issue_agreement(project["id"], target_cod=target_cod,
                                curtailment_hours_cap=curtailment_hours_cap)
    scenario["project"] = get_project(project["id"])
    scenario["agreement"] = agreement
    return scenario


def setup_project_agreement_executed(**kwargs):
    """Single-project cluster walked to AGREEMENT_EXECUTED (study FINALIZED,
    agreement executed at the current logical clock). Returns the scenario dict."""
    scenario = setup_project_agreement_pending(finalize=True, **kwargs)
    agreement = execute_agreement(scenario["agreement"]["id"],
                                  scenario["developer"]["id"])
    scenario["agreement"] = agreement
    scenario["project"] = get_project(scenario["project"]["id"])
    return scenario


# ---------------------------------------------------------------------------
# Tier 4: withdrawals, commercial operation, curtailment, transparency
# ---------------------------------------------------------------------------

def withdraw_project(project_id, acting_developer_id=None):
    """Withdraw as the owning developer unless acting_developer_id overrides."""
    if acting_developer_id is None:
        acting_developer_id = get_project(project_id)["developer_id"]
    return get_success_data(api_client.withdraw_project(
        project_id, make_developer_headers(acting_developer_id)))


def admin_withdraw_project(project_id):
    return get_success_data(api_client.withdraw_project(project_id, ADMIN))


def declare_commercial_operation(project_id, developer_id):
    return get_success_data(api_client.declare_commercial_operation(
        project_id, make_developer_headers(developer_id)))


def create_curtailment_limit(project_id, **overrides):
    resp = api_client.create_curtailment_limit(
        project_id, create_curtailment_limit_payload(**overrides), ADMIN)
    return get_success_data(resp)


def create_transparency_report(reporting_period="2026-Q3"):
    resp = api_client.create_transparency_report(
        create_transparency_report_payload(reporting_period=reporting_period), ADMIN)
    return get_success_data(resp)


def request_extension(agreement_id, developer_id, new_target_cod):
    resp = api_client.request_extension(
        agreement_id, create_extension_payload(new_target_cod),
        make_developer_headers(developer_id))
    return get_success_data(resp)


# ---------------------------------------------------------------------------
# Tier 5: reads and clock
# ---------------------------------------------------------------------------

def get_developer(developer_id):
    return get_success_data(api_client.get_developer(developer_id, ADMIN))


def get_project(project_id):
    return get_success_data(api_client.get_project(project_id, ADMIN))


def get_cluster_group(cluster_group_id):
    return get_success_data(api_client.get_cluster_group(cluster_group_id, ADMIN))


def get_study(study_id):
    return get_success_data(api_client.get_study(study_id, ADMIN))


def get_transparency_report(report_id):
    return get_success_data(api_client.get_transparency_report(report_id, ADMIN))


def list_deposit_ledger(project_id, params=None):
    data, _meta = validate_paginated(api_client.list_deposits(project_id, ADMIN,
                                                              params=params))
    return data


def list_project_cost_shares(project_id, params=None):
    data, _meta = validate_paginated(
        api_client.list_project_cost_shares(project_id, ADMIN, params=params))
    return data


def list_study_cost_shares(study_id, params=None):
    data, _meta = validate_paginated(
        api_client.list_study_cost_shares(study_id, ADMIN, params=params))
    return data


def list_project_agreements(project_id, params=None):
    data, _meta = validate_paginated(
        api_client.list_project_agreements(project_id, ADMIN, params=params))
    return data


def list_milestone_submissions(project_id, params=None):
    data, _meta = validate_paginated(
        api_client.list_milestone_submissions(project_id, ADMIN, params=params))
    return data


def list_curtailment_limits(project_id, params=None):
    data, _meta = validate_paginated(
        api_client.list_curtailment_limits(project_id, ADMIN, params=params))
    return data


def set_clock(to_iso8601):
    return get_success_data(api_client.set_clock(to_iso8601, ADMIN))
