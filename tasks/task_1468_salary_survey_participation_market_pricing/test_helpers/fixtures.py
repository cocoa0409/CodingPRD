"""Composite setup helpers.

Every test starts against an empty database (the runner restarts the server
before each test), so these helpers build complete precondition chains out of
PRD-declared endpoints only:

  org -> job -> employees -> strategy (ACTIVE) -> vendor (ACTIVE)
      -> survey (OPEN) -> benchmark -> submission -> READY -> SUBMITTED
      -> close -> ACCEPTED -> match -> REVIEWED -> APPROVED
      -> composite -> recompute -> publish -> cycle -> adjustment ...

Identity threading: CompAnalyst / CompManager / HRDirector are entity-backed
by Employee, so every call whose semantics compare the caller to a persisted
person uses make_*_headers(employee["id"]) — never the shared constants.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    create_adjustment_payload,
    create_benchmark_payload,
    create_composite_payload,
    create_cycle_payload,
    create_employee_payload,
    create_job_payload,
    create_match_payload,
    create_org_payload,
    create_report_payload,
    create_strategy_payload,
    create_submission_payload,
    create_survey_payload,
    create_vendor_payload,
    snapshot_entry,
)
from .test_users import TEST_USERS, make_analyst_headers, make_manager_headers

VENDOR_ADMIN = TEST_USERS["vendor_admin_headers"]
BOOTSTRAP_MANAGER = make_manager_headers("emp_mgr_bootstrap")


# ---------------------------------------------------------------------------
# Tier 1: bootstrap — org, job, employees, strategy
# ---------------------------------------------------------------------------

def create_org(**overrides):
    """Create an Organization. Returns the org."""
    return get_success_data(api_client.create_org(create_org_payload(**overrides),
                                                  VENDOR_ADMIN))


def create_job(org_id, **overrides):
    return get_success_data(api_client.create_job(
        org_id, create_job_payload(**overrides), BOOTSTRAP_MANAGER))


def create_employee(org_id, job_id, **overrides):
    return get_success_data(api_client.create_employee(
        org_id, create_employee_payload(job_id, **overrides), BOOTSTRAP_MANAGER))


def bootstrap_org(job_overrides=None, market_as_of_date="2026-08-01",
                  subject_salary=9000000):
    """Org + one job + analyst/manager/subject employees.

    Returns dict(org, job, analyst, manager, subject).
    """
    org = create_org(market_as_of_date=market_as_of_date)
    job = create_job(org["id"], **(job_overrides or {}))
    analyst = create_employee(org["id"], job["id"], full_name="Analyst A",
                              email="analyst@x.com",
                              base_salary_annual_cents=10000000,
                              hire_date="2024-01-01")
    manager = create_employee(org["id"], job["id"], full_name="Manager M",
                              email="manager@x.com",
                              base_salary_annual_cents=15000000,
                              hire_date="2023-01-01")
    subject = create_employee(org["id"], job["id"], full_name="Subject S",
                              email="subject@x.com",
                              base_salary_annual_cents=subject_salary,
                              hire_date="2024-06-01")
    return {"org": org, "job": job, "analyst": analyst,
            "manager": manager, "subject": subject}


def mgr_headers(bundle):
    return make_manager_headers(bundle["manager"]["id"])


def analyst_headers(bundle):
    return make_analyst_headers(bundle["analyst"]["id"])


def add_active_strategy(bundle, geo_differential_policy="NATIONAL",
                        industry_cut="ALL_INDUSTRIES", target_percentile=50,
                        effective_from="2026-01-01", effective_to="2027-01-01",
                        name="FY26"):
    """Create + activate a MarketStrategyPolicy. Returns the ACTIVE strategy."""
    strategy = get_success_data(api_client.create_strategy(
        bundle["org"]["id"],
        create_strategy_payload(
            name=name, target_percentile=target_percentile,
            geo_differential_policy=geo_differential_policy,
            industry_cut=industry_cut,
            effective_from=effective_from, effective_to=effective_to),
        mgr_headers(bundle)))
    return get_success_data(api_client.activate_strategy(
        strategy["id"], mgr_headers(bundle)))


def create_draft_strategy(bundle, **overrides):
    """Create a strategy and leave it in DRAFT."""
    return get_success_data(api_client.create_strategy(
        bundle["org"]["id"], create_strategy_payload(**overrides),
        mgr_headers(bundle)))


def add_successor_strategy(bundle, **overrides):
    """Create + activate a second ACTIVE strategy whose half-open window abuts
    the default first window ([2027-01-01, 2028-01-01)), so activation passes
    the ERR_STRATEGY_WINDOW_OVERLAP guard of PRD §3.1.

    Needed by supersession scenarios: PRD §3.6 rejects publishing a composite
    while another PUBLISHED composite for the same job shares its
    strategy_policy_id (ERR_ALREADY_PUBLISHED), so a second publish that is
    meant to supersede the prior composite must pin a different strategy.
    """
    defaults = dict(name="FY27", effective_from="2027-01-01",
                    effective_to="2028-01-01")
    defaults.update(overrides)
    return add_active_strategy(bundle, **defaults)


# ---------------------------------------------------------------------------
# Tier 2: vendor / survey / benchmark chain
# ---------------------------------------------------------------------------

def create_active_vendor(bundle, data_use_scope="FULL_PARTICIPATION", **overrides):
    """Create + activate a SurveyVendor. Returns the ACTIVE vendor."""
    vendor = get_success_data(api_client.create_vendor(
        bundle["org"]["id"],
        create_vendor_payload(data_use_scope=data_use_scope, **overrides),
        VENDOR_ADMIN))
    return get_success_data(api_client.activate_vendor(vendor["id"], VENDOR_ADMIN))


def create_open_survey(bundle, vendor, **overrides):
    """Create + open a Survey under an ACTIVE vendor. Returns the OPEN survey."""
    survey = get_success_data(api_client.create_survey(
        vendor["id"], create_survey_payload(**overrides), VENDOR_ADMIN))
    return get_success_data(api_client.open_survey(survey["id"], VENDOR_ADMIN))


def add_benchmark(bundle, survey, **overrides):
    return get_success_data(api_client.create_benchmark(
        survey["id"], create_benchmark_payload(**overrides), VENDOR_ADMIN))


def create_draft_submission(bundle, survey, entries=None):
    """Create a SurveySubmission (DRAFT) for the bundle's subject employee."""
    if entries is None:
        entries = [snapshot_entry(bundle["subject"]["id"], bundle["job"]["id"],
                                  base_salary_annual_cents=
                                  bundle["subject"]["base_salary_annual_cents"])]
    return get_success_data(api_client.create_submission(
        survey["id"],
        create_submission_payload(bundle["analyst"]["id"], entries),
        analyst_headers(bundle)))


def move_submission_to_submitted(bundle, submission_id):
    """DRAFT -> READY -> SUBMITTED."""
    get_success_data(api_client.mark_submission_ready(
        submission_id, analyst_headers(bundle)))
    return get_success_data(api_client.submit_submission(
        submission_id, analyst_headers(bundle)))


def setup_accepted_survey(bundle, vendor=None, benchmark_overrides=None,
                          survey_overrides=None, vendor_overrides=None):
    """ACTIVE vendor + OPEN survey + benchmark + one SUBMITTED package,
    then close + accept. Returns dict(vendor, survey, benchmark, submission).
    """
    if vendor is None:
        vendor = create_active_vendor(bundle, **(vendor_overrides or {}))
    survey = create_open_survey(bundle, vendor, **(survey_overrides or {}))
    benchmark = add_benchmark(bundle, survey, **(benchmark_overrides or {}))
    submission = create_draft_submission(bundle, survey)
    move_submission_to_submitted(bundle, submission["id"])
    survey = get_success_data(api_client.close_survey(survey["id"], VENDOR_ADMIN))
    survey = get_success_data(api_client.accept_survey(survey["id"], VENDOR_ADMIN))
    return {"vendor": vendor, "survey": survey, "benchmark": benchmark,
            "submission": submission}


# ---------------------------------------------------------------------------
# Tier 3: matches and composites
# ---------------------------------------------------------------------------

def propose_match(bundle, survey, job, benchmark, match_confidence="HIGH",
                  match_weight_pct=100):
    return get_success_data(api_client.create_match(
        survey["id"],
        create_match_payload(job["id"], benchmark["id"],
                             bundle["analyst"]["id"],
                             match_confidence=match_confidence,
                             match_weight_pct=match_weight_pct),
        analyst_headers(bundle)))


def review_and_approve_match(bundle, match_id):
    """PROPOSED -> REVIEWED -> APPROVED as the manager (SoD-safe)."""
    get_success_data(api_client.review_match(match_id, mgr_headers(bundle)))
    return get_success_data(api_client.approve_match(match_id, mgr_headers(bundle)))


def create_recomputed_composite(bundle, job, strategy, job_geo_code="US-SF"):
    """Create a DRAFT composite and recompute it. Returns the composite."""
    composite = get_success_data(api_client.create_composite(
        job["id"], create_composite_payload(strategy["id"],
                                            job_geo_code=job_geo_code),
        mgr_headers(bundle)))
    return get_success_data(api_client.recompute_composite(
        composite["id"], mgr_headers(bundle)))


def publish_composite(bundle, job_id, composite_id):
    """Publish a recomputed composite with a fresh expected_job_version."""
    job = get_success_data(api_client.get_job(job_id, mgr_headers(bundle)))
    return get_success_data(api_client.publish_composite(
        composite_id, {"expected_job_version": job["version"]},
        mgr_headers(bundle)))


def setup_published_job(job_overrides=None, strategy_overrides=None,
                        benchmark_overrides=None, subject_salary=9000000,
                        market_as_of_date="2026-08-01",
                        survey_overrides=None, composite_geo_code="US-SF"):
    """Full canonical chain ending in a PUBLISHED composite for the job.

    Returns dict(org, job, analyst, manager, subject, strategy, vendor,
    survey, benchmark, submission, match, composite).
    """
    bundle = bootstrap_org(job_overrides=job_overrides,
                           market_as_of_date=market_as_of_date,
                           subject_salary=subject_salary)
    bundle["strategy"] = add_active_strategy(bundle, **(strategy_overrides or {}))
    chain = setup_accepted_survey(
        bundle,
        benchmark_overrides=benchmark_overrides,
        survey_overrides=survey_overrides)
    bundle.update(chain)
    match = propose_match(bundle, bundle["survey"], bundle["job"],
                          bundle["benchmark"])
    bundle["match"] = review_and_approve_match(bundle, match["id"])
    bundle["composite"] = create_recomputed_composite(
        bundle, bundle["job"], bundle["strategy"],
        job_geo_code=composite_geo_code)
    bundle["composite"] = publish_composite(bundle, bundle["job"]["id"],
                                            bundle["composite"]["id"])
    return bundle


# ---------------------------------------------------------------------------
# Tier 4: adjustment cycles
# ---------------------------------------------------------------------------

def create_open_cycle(bundle, **overrides):
    return get_success_data(api_client.create_cycle(
        bundle["org"]["id"], create_cycle_payload(**overrides),
        mgr_headers(bundle)))


def create_draft_adjustment(bundle, cycle, employee=None, proposed_amount_cents=100000):
    employee = employee or bundle["subject"]
    return get_success_data(api_client.create_adjustment(
        cycle["id"],
        create_adjustment_payload(employee["id"], bundle["analyst"]["id"],
                                  proposed_amount_cents=proposed_amount_cents),
        analyst_headers(bundle)))


def submit_adjustment(bundle, adjustment_id):
    return get_success_data(api_client.submit_adjustment(
        adjustment_id, analyst_headers(bundle)))


def approve_adjustment(bundle, adjustment_id):
    """Approve with a freshly-read expected_cycle_version (OCC, PRD §2.8)."""
    adj = get_success_data(api_client.get_adjustment(
        adjustment_id, mgr_headers(bundle)))
    cycle = get_success_data(api_client.get_cycle(adj["cycle_id"],
                                                  mgr_headers(bundle)))
    return get_success_data(api_client.approve_adjustment(
        adjustment_id, {"expected_cycle_version": cycle["version"]},
        mgr_headers(bundle)))


def get_cycle(bundle, cycle_id):
    return get_success_data(api_client.get_cycle(cycle_id, mgr_headers(bundle)))


def get_job(bundle, job_id):
    return get_success_data(api_client.get_job(job_id, mgr_headers(bundle)))


def get_submission(bundle, submission_id):
    return get_success_data(api_client.get_submission(submission_id,
                                                      analyst_headers(bundle)))


def get_adjustment(bundle, adjustment_id):
    return get_success_data(api_client.get_adjustment(adjustment_id,
                                                      mgr_headers(bundle)))


def get_composite(bundle, composite_id):
    return get_success_data(api_client.get_composite(composite_id,
                                                     mgr_headers(bundle)))


def get_survey(survey_id):
    return get_success_data(api_client.get_survey(survey_id, VENDOR_ADMIN))


def get_vendor(vendor_id):
    return get_success_data(api_client.get_vendor(vendor_id, VENDOR_ADMIN))


# ---------------------------------------------------------------------------
# Tier 5: reports
# ---------------------------------------------------------------------------

def create_draft_report(bundle, strategy, **overrides):
    return get_success_data(api_client.create_report(
        bundle["org"]["id"], create_report_payload(strategy["id"], **overrides),
        mgr_headers(bundle)))
