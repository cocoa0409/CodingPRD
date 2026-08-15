"""Composite setup helpers (PRD §3 workflows).

Every fixture builds its preconditions from scratch via PRD-declared endpoints,
since the server restarts against an empty database before each test. Setup
calls use get_success_data() so a setup failure surfaces as a clear error.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    create_employer_payload,
    create_plan_payload,
    create_plan_version_payload,
    create_plan_year_payload,
    create_census_employee_payload,
    create_compensation_record_payload,
    create_contribution_payload,
    create_regulatory_limit_payload,
)
from .test_users import (
    TEST_USERS,
    make_plan_admin_headers,
    make_analyst_headers,
    make_platform_admin_headers,
)

ADMIN = TEST_USERS["plan_admin_headers"]
PLATFORM = TEST_USERS["platform_admin_headers"]
ANALYST = TEST_USERS["analyst_headers"]
AUDITOR = TEST_USERS["auditor_headers"]


# ---------------------------------------------------------------------------
# Tier 1/2: hierarchy builders
# ---------------------------------------------------------------------------

def create_employer(legal_name="Test Employer Corp", entity_type="CORPORATION", **overrides):
    payload = create_employer_payload(legal_name=legal_name, entity_type=entity_type, **overrides)
    return get_success_data(api_client.create_employer(payload, PLATFORM))


def publish_limits_2026():
    return get_success_data(api_client.create_regulatory_limit(create_regulatory_limit_payload(), PLATFORM))


def publish_limits(year_label=2026, **overrides):
    return get_success_data(
        api_client.create_regulatory_limit(
            create_regulatory_limit_payload(year_label=year_label, **overrides), PLATFORM
        )
    )


def create_plan_for(employer_id, plan_name="Test 401k", plan_type="401K", plan_number="001"):
    payload = create_plan_payload(plan_name=plan_name, plan_type=plan_type, plan_number=plan_number)
    return get_success_data(api_client.create_plan(employer_id, payload, ADMIN))


def create_adopted_version(plan_id, comp_definition="W2", safe_harbor_design="NONE", **overrides):
    payload = create_plan_version_payload(
        comp_definition=comp_definition, safe_harbor_design=safe_harbor_design, **overrides
    )
    version = get_success_data(api_client.create_plan_version(plan_id, payload, ADMIN))
    adopted = get_success_data(api_client.adopt_plan_version(version["id"], ADMIN))
    return adopted


def create_plan_year_for(plan_id, **overrides):
    payload = create_plan_year_payload(**overrides)
    return get_success_data(api_client.create_plan_year(plan_id, payload, ADMIN))


def open_census(plan_year_id):
    return get_success_data(api_client.open_census(plan_year_id, ADMIN))


def add_employee(plan_year_id, ssn, full_name, ownership_pct_direct=None, is_officer=None,
                 employment_status="ACTIVE", date_of_termination=None, family_member_of_ssn=None,
                 date_of_birth="1980-01-01", date_of_hire="2020-01-01"):
    overrides = {
        "ssn": ssn,
        "full_name": full_name,
        "date_of_birth": date_of_birth,
        "date_of_hire": date_of_hire,
        "employment_status": employment_status,
    }
    if ownership_pct_direct is not None:
        overrides["ownership_pct_direct"] = ownership_pct_direct
    if is_officer is not None:
        overrides["is_officer"] = is_officer
    if date_of_termination is not None:
        overrides["date_of_termination"] = date_of_termination
    if family_member_of_ssn is not None:
        overrides["family_member_of_ssn"] = family_member_of_ssn
    payload = create_census_employee_payload(**overrides)
    return get_success_data(api_client.create_census_employee(plan_year_id, payload, ADMIN))


def add_compensation(employee_id, amount_cents, comp_source="W2", period="CURRENT_YEAR"):
    payload = create_compensation_record_payload(
        comp_source=comp_source, amount_cents=amount_cents, period=period
    )
    return get_success_data(api_client.create_compensation_record(employee_id, payload, ADMIN))


def add_contribution(employee_id, contribution_type, amount_cents, contribution_date="2026-06-30"):
    payload = create_contribution_payload(
        contribution_type=contribution_type, amount_cents=amount_cents, contribution_date=contribution_date
    )
    return get_success_data(api_client.create_contribution(employee_id, payload, ADMIN))


def current_plan_year_version(plan_year_id) -> int:
    return get_success_data(api_client.get_plan_year(plan_year_id, ADMIN))["version"]


def lock_census(plan_year_id):
    """Lock with a fresh OCC version read (PRD §2.7)."""
    version = current_plan_year_version(plan_year_id)
    return get_success_data(
        api_client.lock_census(plan_year_id, {"expected_plan_year_version": version}, ADMIN)
    )


def queue_and_execute_run(plan_year_id, test_scope, run_mode="FINAL"):
    run = get_success_data(
        api_client.create_test_run(plan_year_id, {"test_scope": test_scope, "run_mode": run_mode}, ANALYST)
    )
    executed = get_success_data(api_client.execute_test_run_synchronously(run["id"], ANALYST))
    return executed


def get_result_lines(test_run_id):
    return get_success_data(api_client.list_result_lines(test_run_id, AUDITOR))


# ---------------------------------------------------------------------------
# Tier 2: standard 401k locked-census scenarios shared by many test claims
# ---------------------------------------------------------------------------

def setup_employer_plan_version_year(
    legal_name="Acme Corp",
    plan_name="Acme 401k",
    plan_type="401K",
    year_label=2026,
    comp_definition="W2",
    safe_harbor_design="NONE",
    publish_limits_first=True,
    sec402g_limit_cents=None,
):
    """Employer + plan + ADOPTED version + plan year in DRAFT. Returns dict of parts.

    sec402g_limit_cents: override the elective-deferral ceiling for scenarios whose
    census needs aggregate deferrals above the standard 2350000 example limit (PRD
    §3.4's guard compares against the year's published limit, PRD §3.3).
    """
    employer = create_employer(legal_name=legal_name)
    limits = (
        publish_limits(year_label, **({"sec402g_limit_cents": sec402g_limit_cents}
                                      if sec402g_limit_cents else {}))
        if publish_limits_first else None
    )
    plan = create_plan_for(employer["id"], plan_name=plan_name, plan_type=plan_type)
    version = create_adopted_version(plan["id"], comp_definition=comp_definition,
                                     safe_harbor_design=safe_harbor_design)
    plan_year = create_plan_year_for(plan["id"], year_label=year_label)
    return {
        "employer": employer,
        "limits": limits,
        "plan": plan,
        "version": version,
        "plan_year": plan_year,
    }


def setup_locked_census_401k(
    legal_name="Acme Corp",
    nhce_specs=((10000000, 400000), (10000000, 600000)),
    hce_spec=(30000000, 3000000, 6),
    plan_name="Acme 401k",
):
    """The canonical failing-ADP locked census (PRD §3.5 lock, §3.6 ADP).

    nhce_specs: iterable of (comp_cents, deferral_cents) for NHCE employees.
    hce_spec: (comp_cents, deferral_cents, ownership_pct_direct) for one HCE.

    ADP math for the default args: NHCE ADRs 4.0000/6.0000 -> avg 5.0000;
    ceiling max(1.25*5, min(5+2, 2*5)) = 7.0000; HCE ADR 10.0000 -> FAIL.

    The published 402(g) limit is raised to 6900000 so the HCE's 3000000 deferral
    ledger is postable under PRD §3.4's aggregate limit guard.
    """
    parts = setup_employer_plan_version_year(
        legal_name=legal_name, plan_name=plan_name, sec402g_limit_cents=6900000
    )
    py_id = parts["plan_year"]["id"]
    open_census(py_id)

    nhces = []
    for i, (comp, deferral) in enumerate(nhce_specs):
        emp = add_employee(py_id, ssn=f"7{i:08d}"[-9:], full_name=f"NHCE {i}")
        add_compensation(emp["id"], comp)
        if deferral:
            add_contribution(emp["id"], "ELECTIVE_DEFERRAL", deferral)
        nhces.append(emp)

    hce_comp, hce_deferral, hce_ownership = hce_spec
    hce = add_employee(py_id, ssn="788888889", full_name="HCE Owner",
                       ownership_pct_direct=hce_ownership)
    add_compensation(hce["id"], hce_comp)
    if hce_deferral:
        add_contribution(hce["id"], "ELECTIVE_DEFERRAL", hce_deferral)

    lock_census(py_id)
    parts["nhces"] = nhces
    parts["hce"] = hce
    parts["plan_year"] = get_success_data(api_client.get_plan_year(py_id, ADMIN))
    return parts


def setup_results_review_with_failing_adp(
    legal_name="Foxtrot Inc",
    nhce_specs=((10000000, 400000), (10000000, 600000)),
    hce_spec=(30000000, 3000000, 6),
    plan_name="Foxtrot 401k",
):
    """Locked census + executed FAILED FINAL ADP run + finalize -> RESULTS_REVIEW."""
    parts = setup_locked_census_401k(
        legal_name=legal_name, nhce_specs=nhce_specs, hce_spec=hce_spec, plan_name=plan_name
    )
    run = queue_and_execute_run(parts["plan_year"]["id"], "ADP_401K", "FINAL")
    get_success_data(api_client.finalize_test_run(run["id"], ANALYST))
    parts["failed_run"] = get_success_data(api_client.get_test_run(run["id"], ANALYST))
    parts["plan_year"] = get_success_data(api_client.get_plan_year(parts["plan_year"]["id"], ADMIN))
    return parts


def setup_correcting_with_proposed_correction(
    legal_name="Hotel Inc",
    correction_amount_cents=2250000,
    correction_type="CORRECTIVE_DISTRIBUTION",
    target="hce",
    proposer_user_id="analyst-proposer",
    nhce_specs=((10000000, 400000), (10000000, 600000)),
    hce_spec=(30000000, 3000000, 6),
):
    """RESULTS_REVIEW + proposed correction -> CORRECTING. Returns parts incl. correction."""
    parts = setup_results_review_with_failing_adp(
        legal_name=legal_name, nhce_specs=nhce_specs, hce_spec=hce_spec
    )
    payload = {
        "test_run_id": parts["failed_run"]["id"],
        "correction_type": correction_type,
        "amount_cents": correction_amount_cents,
    }
    if target == "hce":
        payload["target_census_employee_id"] = parts["hce"]["id"]
    correction = get_success_data(
        api_client.create_correction(
            parts["plan_year"]["id"], payload, make_analyst_headers(proposer_user_id)
        )
    )
    parts["correction"] = correction
    parts["proposer_user_id"] = proposer_user_id
    parts["plan_year"] = get_success_data(api_client.get_plan_year(parts["plan_year"]["id"], ADMIN))
    return parts


def setup_approved_correction(approver_user_id="admin-approver", **kwargs):
    """CORRECTING + APPROVED correction (OCC-guarded approve with fresh version)."""
    parts = setup_correcting_with_proposed_correction(**kwargs)
    version = get_success_data(api_client.get_correction(parts["correction"]["id"], ADMIN))["version"]
    approved = get_success_data(
        api_client.approve_correction(
            parts["correction"]["id"],
            {"expected_correction_version": version},
            make_plan_admin_headers(approver_user_id),
        )
    )
    parts["correction"] = approved
    parts["approver_user_id"] = approver_user_id
    return parts


def set_clock(to_iso8601):
    return get_success_data(
        api_client.set_clock({"to_iso8601": to_iso8601}, PLATFORM)
    )
