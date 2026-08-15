"""Composite setup helpers.

Every test starts against an empty database (the harness restarts the server
before each test), so these helpers build complete precondition chains out of
PRD-declared endpoints only. Internal setup calls use the lenient
get_success_data validator so setup failures surface as clear "Setup failed"
errors naming the failing step.

Identity threading: the Inventor role is entity-backed, so every
ownership-gated Inventor call (submit disclosure, confirm entry, dispute
entry) is made with make_inventor_headers(inventor["id"]) built from the real
entity id — never the shared fallback constant.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import CLOCK_START
from .factories import (
    add_roster_entry_payload,
    agency_response_payload,
    approve_distribution_payload,
    assessment_payload,
    create_coi_plan_payload,
    create_compliance_report_payload,
    create_cost_payload,
    create_department_payload,
    create_disclosure_payload,
    create_inventor_payload,
    create_license_payload,
    create_milestone_payload,
    create_patent_application_payload,
    create_royalty_report_payload,
    create_startup_payload,
    decision_payload,
    dispute_payload,
    execute_license_payload,
    finalize_payload,
    resolve_dispute_payload,
    set_clock_payload,
)
from .test_users import (
    TEST_USERS,
    make_inventor_headers,
)

ADMIN = TEST_USERS["system_admin_headers"]
TTO = TEST_USERS["tto_headers"]
LM = TEST_USERS["licensing_manager_headers"]
CO = TEST_USERS["compliance_officer_headers"]
CD = TEST_USERS["compliance_director_headers"]
FO = TEST_USERS["finance_officer_headers"]
FD = TEST_USERS["finance_director_headers"]
ANY_READER = TEST_USERS["system_admin_headers"]


def _ok(resp, what):
    """Lenient setup validation with a clear failure message."""
    data = get_success_data(resp)
    assert resp.status_code < 300, \
        f"Setup failed at {what}: {resp.status_code} {resp.text}"
    return data


# ---------------------------------------------------------------------------
# Tier 1: single-resource creation
# ---------------------------------------------------------------------------

def create_department(name="EECS", college_name="Engineering"):
    return _ok(api_client.create_department(
        create_department_payload(name=name, college_name=college_name), ADMIN),
        "create_department")


def create_inventor(department_id, full_name="Ada Lovelace", email="ada@uni.edu",
                    appointment_type="FACULTY"):
    return _ok(api_client.create_inventor(
        create_inventor_payload(department_id, full_name=full_name, email=email,
                                appointment_type=appointment_type), ADMIN),
        "create_inventor")


def setup_department_and_inventor(dept_name="EECS", college="Engineering",
                                  inventor_name="Ada Lovelace",
                                  email="ada@uni.edu", appointment="FACULTY"):
    """One department plus one inventor housed in it. Returns (dept, inventor)."""
    dept = create_department(dept_name, college)
    inv = create_inventor(dept["id"], inventor_name, email, appointment)
    return dept, inv


def submit_disclosure(inventor, funding_source="NON_FEDERAL", title="Tensor Compiler",
                      description="Novel compiler", federal_agency=None,
                      grant_number=None, public_disclosure_date=None):
    """Submit a disclosure as the given inventor. Returns the disclosure."""
    payload = create_disclosure_payload(
        title=title, description=description, funding_source=funding_source)
    if federal_agency is not None:
        payload["federal_agency"] = federal_agency
    if grant_number is not None:
        payload["grant_number"] = grant_number
    if public_disclosure_date is not None:
        payload["public_disclosure_date"] = public_disclosure_date
    return _ok(api_client.create_disclosure(
        payload, make_inventor_headers(inventor["id"])), "submit_disclosure")


def add_roster_entry(disclosure_id, inventor_id, share_bp):
    return _ok(api_client.add_roster_entry(
        disclosure_id, add_roster_entry_payload(inventor_id, share_bp), TTO),
        "add_roster_entry")


def confirm_entry(entry_id, inventor_id):
    return _ok(api_client.confirm_entry(
        entry_id, make_inventor_headers(inventor_id)), "confirm_entry")


def get_disclosure(disclosure_id):
    return _ok(api_client.get_disclosure(disclosure_id, ANY_READER),
               "get_disclosure")


def add_cost(application_id, amount_cents, cost_type="ATTORNEY_FEE",
             incurred_date="2026-03-01T00:00:00Z"):
    """Record a prosecution cost on an application. Returns the cost row."""
    return _ok(api_client.add_cost(
        application_id,
        create_cost_payload(amount_cents, cost_type=cost_type,
                            incurred_date=incurred_date),
        TTO), "add_cost")


def set_clock(to_iso8601):
    return _ok(api_client.set_clock(set_clock_payload(to_iso8601), ADMIN),
               "set_clock")


# ---------------------------------------------------------------------------
# Tier 2: disclosure gating chain (roster -> confirm -> finalize -> assess ->
# decision)
# ---------------------------------------------------------------------------

def gate_disclosure_to_patent_pursued(disclosure_id, entries,
                                      patentability="HIGH", market="HIGH"):
    """Confirm every roster entry, finalize inventorship, record the
    assessment, and decide PURSUE_PATENT. `entries` is a list of
    (entry_id, inventor_id) tuples. Returns the final disclosure."""
    for entry_id, inventor_id in entries:
        confirm_entry(entry_id, inventor_id)
    version = get_disclosure(disclosure_id)["version"]
    _ok(api_client.finalize_inventorship(
        disclosure_id, finalize_payload(version), TTO), "finalize_inventorship")
    _ok(api_client.record_assessment(
        disclosure_id, assessment_payload(patentability, market), TTO),
        "record_assessment")
    return _ok(api_client.record_decision(
        disclosure_id, decision_payload("PURSUE_PATENT"), TTO), "record_decision")


def setup_patent_pursued_disclosure(funding_source="NON_FEDERAL",
                                    share_vector=(10000,),
                                    patentability="HIGH", market="HIGH",
                                    title="Tensor Compiler",
                                    public_disclosure_date=None,
                                    num_departments=1):
    """Full intake chain: departments, one inventor per share, disclosure,
    roster, confirmations, finalize, assessment, PURSUE_PATENT.

    Inventors are distributed across the created departments round-robin.
    Returns dict(depts, inventors, disclosure, entries).
    """
    depts = [create_department(f"Dept{i}", "Engineering") if i else
             create_department("EECS", "Engineering")
             for i in range(num_departments)]
    inventors = []
    entries = []
    disclosure = None
    for i, share_bp in enumerate(share_vector):
        dept = depts[i % len(depts)]
        inv = create_inventor(dept["id"], full_name=f"Inventor {i + 1}",
                              email=f"inv{i + 1}@uni.edu")
        inventors.append(inv)
        if disclosure is None:
            kwargs = {}
            if funding_source in ("FEDERAL", "MIXED"):
                kwargs["federal_agency"] = "NSF"
                kwargs["grant_number"] = "12345"
            if public_disclosure_date is not None:
                kwargs["public_disclosure_date"] = public_disclosure_date
            disclosure = submit_disclosure(inv, funding_source=funding_source,
                                           title=title, **kwargs)
        entry = add_roster_entry(disclosure["id"], inv["id"], share_bp)
        entries.append(entry)
    gate_disclosure_to_patent_pursued(
        disclosure["id"], [(e["id"], e["inventor_id"]) for e in entries],
        patentability, market)
    disclosure = get_disclosure(disclosure["id"])
    return {"depts": depts, "inventors": inventors, "disclosure": disclosure,
            "entries": entries}


# ---------------------------------------------------------------------------
# Tier 3: license lifecycle shortcuts
# ---------------------------------------------------------------------------

def create_license(disclosure_id, **overrides):
    return _ok(api_client.create_license(
        disclosure_id, create_license_payload(**overrides), LM),
        "create_license")


def execute_license(license_id, version):
    return _ok(api_client.execute_license(
        license_id, execute_license_payload(version), LM), "execute_license")


def activate_license(license_id, version, sweep_to=CLOCK_START):
    """Execute then advance the logical clock so the sweep flips the license
    EXECUTED -> ACTIVE (effective_date already reached). Returns the license."""
    execute_license(license_id, version)
    set_clock(sweep_to)
    return _ok(api_client.get_license(license_id, ANY_READER), "get_license")


def setup_active_license(disclosure_id=None, ctx=None, **license_overrides):
    """PATENT_PURSUED disclosure plus an ACTIVE license. Pass an existing
    disclosure_id or a ctx dict from setup_patent_pursued_disclosure.
    Returns a ctx dict augmented with the license."""
    if ctx is None:
        ctx = setup_patent_pursued_disclosure() if disclosure_id is None else \
            {"disclosure": get_disclosure(disclosure_id), "depts": [],
             "inventors": [], "entries": []}
    lic = create_license(ctx["disclosure"]["id"], **license_overrides)
    lic = activate_license(lic["id"], lic["version"])
    ctx["license"] = lic
    return ctx


def add_milestone(license_id, due_date="2026-06-01T00:00:00Z", description="M",
                  amount_cents=1000):
    return _ok(api_client.create_milestone(
        license_id, create_milestone_payload(due_date=due_date,
                                             description=description,
                                             amount_cents=amount_cents), LM),
        "create_milestone")


def setup_defaulted_license(milestone_due="2026-06-01T00:00:00Z",
                            default_clock=CLOCK_START, **license_overrides):
    """ACTIVE license with one overdue PENDING milestone, already declared in
    default at `default_clock`. Returns (ctx, milestone)."""
    ctx = setup_active_license(**license_overrides)
    milestone = add_milestone(ctx["license"]["id"], due_date=milestone_due)
    set_clock(default_clock)
    _ok(api_client.declare_default(ctx["license"]["id"], {"reason": "overdue"}, LM),
        "declare_default")
    return ctx, milestone


# ---------------------------------------------------------------------------
# Tier 4: royalty reporting and distributions
# ---------------------------------------------------------------------------

def submit_report(license_id, sales_cents,
                  period_start="2026-01-01T00:00:00Z",
                  period_end="2026-07-01T00:00:00Z"):
    return _ok(api_client.create_royalty_report(
        license_id,
        create_royalty_report_payload(sales_cents, period_start=period_start,
                                      period_end=period_end), LM),
        "create_royalty_report")


def accept_report(report_id, headers=None):
    return _ok(api_client.accept_royalty_report(report_id, headers or FO),
               "accept_royalty_report")


def setup_accepted_report(sales_cents=10_000_000, patent_costs=None,
                          with_startup=False, **license_overrides):
    """ACTIVE license plus one ACCEPTED report of `sales_cents`.
    Optionally records patent costs (list of amount_cents) on a fresh
    PROVISIONAL application and/or links the license to a COI-covered
    startup. Returns ctx with keys disclosure, license, report, entries,
    inventors, depts, and optionally application/costs/startup."""
    ctx = setup_patent_pursued_disclosure(
        funding_source=license_overrides.pop("funding_source",
                                             "NON_FEDERAL"))
    if with_startup:
        su = create_startup_fixture(ctx["disclosure"]["id"])
        plan = create_approved_coi_plan(su["id"], ctx["entries"][0]["inventor_id"])
        ctx["startup"] = su
        ctx["coi_plan"] = plan
        license_overrides["startup_id"] = su["id"]
    lic = create_license(ctx["disclosure"]["id"], **license_overrides)
    lic = activate_license(lic["id"], lic["version"])
    ctx["license"] = lic
    if patent_costs:
        app = _ok(api_client.create_patent_application(
            ctx["disclosure"]["id"], create_patent_application_payload(), TTO),
            "create_patent_application")
        costs = [_ok(api_client.add_cost(app["id"], create_cost_payload(a), TTO),
                     "add_cost") for a in patent_costs]
        ctx["application"] = app
        ctx["costs"] = costs
    report = submit_report(lic["id"], sales_cents)
    ctx["report"] = accept_report(report["id"])
    return ctx


def create_distribution(report_id, headers=None):
    return _ok(api_client.create_distribution(report_id, headers or FO),
               "create_distribution")


def setup_calculated_distribution(sales_cents=10_000_000, patent_costs=None,
                                  **license_overrides):
    """Accepted report plus its CALCULATED distribution (prepared by the
    default FinanceOfficer user). Returns ctx augmented with distribution."""
    ctx = setup_accepted_report(sales_cents, patent_costs=patent_costs,
                                **license_overrides)
    ctx["distribution"] = create_distribution(ctx["report"]["id"])
    return ctx


def approve_distribution(distribution_id, version, headers=None):
    return _ok(api_client.approve_distribution(
        distribution_id, approve_distribution_payload(version), headers or FD),
        "approve_distribution")


def setup_approved_distribution(sales_cents=10_000_000, patent_costs=None,
                                **license_overrides):
    """CALCULATED distribution approved by a FinanceDirector distinct from the
    preparing FinanceOfficer. Returns ctx augmented with distribution."""
    ctx = setup_calculated_distribution(sales_cents, patent_costs=patent_costs,
                                        **license_overrides)
    dist = ctx["distribution"]
    ctx["distribution"] = approve_distribution(dist["id"], dist["version"])
    return ctx


# ---------------------------------------------------------------------------
# Tier 5: startup / COI helpers
# ---------------------------------------------------------------------------

def create_startup_fixture(disclosure_id, name="SpinCo", equity_model="FIXED",
                           founded_date="2026-02-01T00:00:00Z"):
    return _ok(api_client.create_startup(
        disclosure_id,
        create_startup_payload(name=name, equity_model=equity_model,
                               founded_date=founded_date), TTO),
        "create_startup")


def create_coi_plan(startup_id, inventor_id,
                    coverage_start="2026-01-01T00:00:00Z",
                    coverage_end="2027-01-01T00:00:00Z",
                    management_plan_text="Recusal plan"):
    return _ok(api_client.create_coi_plan(
        startup_id,
        create_coi_plan_payload(inventor_id, coverage_start=coverage_start,
                                coverage_end=coverage_end,
                                management_plan_text=management_plan_text), CO),
        "create_coi_plan")


def create_approved_coi_plan(startup_id, inventor_id, **window):
    plan = create_coi_plan(startup_id, inventor_id, **window)
    return _ok(api_client.approve_coi_plan(plan["id"], CD), "approve_coi_plan")


# ---------------------------------------------------------------------------
# Federal compliance helpers
# ---------------------------------------------------------------------------

def create_compliance_report(disclosure_id, report_type="INITIAL_DISCLOSURE",
                             headers=None, **overrides):
    return _ok(api_client.create_compliance_report(
        disclosure_id, create_compliance_report_payload(report_type, **overrides),
        headers or CO), "create_compliance_report")


def submit_compliance_report(report_id, headers=None):
    return _ok(api_client.submit_compliance_report(report_id, headers or CO),
               "submit_compliance_report")


def certify_compliance_report(report_id, headers=None):
    return _ok(api_client.certify_compliance_report(report_id, headers or CD),
               "certify_compliance_report")


def setup_certified_compliance_report(disclosure_id,
                                      report_type="INITIAL_DISCLOSURE",
                                      **overrides):
    """Compliance report walked DRAFT -> PENDING_CERTIFICATION -> SUBMITTED
    (prepared by the ComplianceOfficer, certified by a distinct
    ComplianceDirector)."""
    rep = create_compliance_report(disclosure_id, report_type, **overrides)
    submit_compliance_report(rep["id"])
    return certify_compliance_report(rep["id"])


def agency_response(report_id, outcome="ACCEPTED", **overrides):
    return _ok(api_client.record_agency_response(
        report_id, agency_response_payload(outcome, **overrides), CD),
        "record_agency_response")


def raise_dispute(entry_id, inventor_id, reason="Share allocation contested"):
    return _ok(api_client.dispute_entry(
        entry_id, dispute_payload(reason), make_inventor_headers(inventor_id)),
        "dispute_entry")


def resolve_dispute(dispute_id, adjusted_shares, resolution_notes="Resolved"):
    return _ok(api_client.resolve_dispute(
        dispute_id, resolve_dispute_payload(adjusted_shares, resolution_notes),
        TTO), "resolve_dispute")
