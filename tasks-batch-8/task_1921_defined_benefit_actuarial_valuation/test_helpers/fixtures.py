"""Composite setup helpers — multi-step scenario builders shared across tests.

Every fixture builds its preconditions from scratch against an empty DB using
only PRD-declared endpoints. Fixtures use get_success_data() (lenient) so a
setup failure surfaces as a clear "Setup step failed" error.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    create_plan_payload,
    create_actuary_payload,
    create_census_batch_payload,
    create_participants_payload,
    create_assumption_set_payload,
    create_asset_statement_payload,
    create_asset_valuation_payload,
    create_valuation_run_payload,
)
from .test_users import (
    TEST_USERS,
    make_actuary_headers,
    make_senior_actuary_headers,
)

PLAN_ADMIN = TEST_USERS["plan_admin_headers"]
FIRM_ADMIN = TEST_USERS["firm_admin_headers"]
AUDITOR = TEST_USERS["auditor_headers"]


# ---------------------------------------------------------------------------
# Tier 1: State Progression — actuary registry, plans, assumption sets
# ---------------------------------------------------------------------------

def register_actuary(full_name="Prep Act", credential_id="EA-1", enrollment_status="ENROLLED"):
    """Register one actuary. Returns the Actuary dict."""
    resp = api_client.create_actuary(
        create_actuary_payload(
            full_name=full_name,
            credential_id=credential_id,
            enrollment_status=enrollment_status,
        ),
        FIRM_ADMIN,
    )
    return get_success_data(resp, 201)


def register_prep_and_review_actuaries():
    """Register the canonical preparer + reviewer pair (both ENROLLED).
    Returns (prep_actuary, review_actuary)."""
    prep = register_actuary("Prep Act", "EA-1", "ENROLLED")
    rev = register_actuary("Rev Act", "EA-2", "ENROLLED")
    return prep, rev


def create_plan(sponsor_name="Test Co", plan_year=2028, accrual_rate=0.01,
                normal_retirement_age=62, prior_aftap_pct=90.00,
                initial_carryover_balance=None, initial_prefunding_balance=None):
    """Create a plan. Returns the Plan dict."""
    overrides = {}
    if initial_carryover_balance is not None:
        overrides["initial_carryover_balance"] = initial_carryover_balance
    if initial_prefunding_balance is not None:
        overrides["initial_prefunding_balance"] = initial_prefunding_balance
    resp = api_client.create_plan(
        create_plan_payload(
            sponsor_name=sponsor_name,
            plan_year=plan_year,
            accrual_rate=accrual_rate,
            normal_retirement_age=normal_retirement_age,
            prior_aftap_pct=prior_aftap_pct,
            **overrides,
        ),
        PLAN_ADMIN,
    )
    return get_success_data(resp, 201)


def get_plan(plan_id):
    resp = api_client.get_plan(plan_id, PLAN_ADMIN)
    return get_success_data(resp, 200)


def get_plan_version(plan_id):
    return get_plan(plan_id)["version"]


# ---------------------------------------------------------------------------
# Tier 2: Entity Hierarchy — census batch walk to LOCKED
# ---------------------------------------------------------------------------

def create_census_batch(plan_id, plan_year=2028, source_label="census-1"):
    resp = api_client.create_census_batch(
        plan_id,
        create_census_batch_payload(plan_year=plan_year, source_label=source_label),
        PLAN_ADMIN,
    )
    return get_success_data(resp, 201)


def add_participants(batch_id, rows):
    resp = api_client.add_participants(batch_id, create_participants_payload(rows), PLAN_ADMIN)
    return get_success_data(resp, 200)


def submit_screening(batch_id):
    resp = api_client.submit_screening(batch_id, PLAN_ADMIN)
    return get_success_data(resp, 200)


def lock_census_batch(batch_id):
    resp = api_client.lock_census_batch(batch_id, PLAN_ADMIN)
    return get_success_data(resp, 200)


def create_locked_census(plan_id, participant_rows, plan_year=2028, source_label="census-1"):
    """Create batch -> append rows -> screen -> lock. Returns the LOCKED CensusBatch."""
    batch = create_census_batch(plan_id, plan_year=plan_year, source_label=source_label)
    add_participants(batch["id"], participant_rows)
    submit_screening(batch["id"])
    return lock_census_batch(batch["id"])


# ---------------------------------------------------------------------------
# Tier 2: Assumption set walk to LOCKED
# ---------------------------------------------------------------------------

def create_assumption_set(plan_id, prep_actuary_id, plan_year=2028, label="base",
                          funding_discount_rate=0.05, disclosure_discount_rate=0.04,
                          retirement_age=62, mortality_table="TEST_TABLE_4AGE"):
    """Create a DRAFT assumption set as the given preparer (Actuary role)."""
    resp = api_client.create_assumption_set(
        plan_id,
        create_assumption_set_payload(
            plan_year=plan_year,
            label=label,
            mortality_table=mortality_table,
            funding_discount_rate=funding_discount_rate,
            disclosure_discount_rate=disclosure_discount_rate,
            retirement_age=retirement_age,
        ),
        make_actuary_headers(prep_actuary_id),
    )
    return get_success_data(resp, 201)


def submit_assumption_set(aset_id, prep_actuary_id):
    resp = api_client.submit_assumption_set(aset_id, make_actuary_headers(prep_actuary_id))
    return get_success_data(resp, 200)


def approve_assumption_set(aset_id, review_actuary_id):
    resp = api_client.approve_assumption_set(aset_id, make_senior_actuary_headers(review_actuary_id))
    return get_success_data(resp, 200)


def lock_assumption_set(aset_id, review_actuary_id):
    resp = api_client.lock_assumption_set(aset_id, make_senior_actuary_headers(review_actuary_id))
    return get_success_data(resp, 200)


def create_locked_assumption_set(plan_id, prep_actuary_id, review_actuary_id, **kwargs):
    """Create -> submit -> approve -> lock. Returns the LOCKED AssumptionSet."""
    aset = create_assumption_set(plan_id, prep_actuary_id, **kwargs)
    submit_assumption_set(aset["id"], prep_actuary_id)
    approve_assumption_set(aset["id"], review_actuary_id)
    return lock_assumption_set(aset["id"], review_actuary_id)


# ---------------------------------------------------------------------------
# Tier 2: Asset statement + valuation
# ---------------------------------------------------------------------------

def create_asset_statement(plan_id, plan_year=2028, market_value_begin=1000,
                           contributions_received=0, benefits_paid=50,
                           investment_return=50):
    resp = api_client.create_asset_statement(
        plan_id,
        create_asset_statement_payload(
            plan_year=plan_year,
            market_value_begin=market_value_begin,
            contributions_received=contributions_received,
            benefits_paid=benefits_paid,
            investment_return=investment_return,
        ),
        PLAN_ADMIN,
    )
    return get_success_data(resp, 201)


def create_asset_valuation(plan_id, actuary_id, plan_year=2028):
    resp = api_client.create_asset_valuation(
        plan_id,
        create_asset_valuation_payload(plan_year=plan_year),
        make_actuary_headers(actuary_id),
    )
    return get_success_data(resp, 201)


# ---------------------------------------------------------------------------
# Tier 3: Valuation run lifecycle
# ---------------------------------------------------------------------------

def create_valuation_run(plan_id, actuary_id, census_batch_id, assumption_set_id,
                         asset_valuation_id, plan_year=2028):
    resp = api_client.create_valuation_run(
        plan_id,
        create_valuation_run_payload(
            plan_year=plan_year,
            census_batch_id=census_batch_id,
            assumption_set_id=assumption_set_id,
            asset_valuation_id=asset_valuation_id,
        ),
        make_actuary_headers(actuary_id),
    )
    return get_success_data(resp, 201)


def compute_run(run_id, actuary_id):
    resp = api_client.compute_valuation_run(run_id, make_actuary_headers(actuary_id))
    return get_success_data(resp, 200)


def certify_run(run_id, review_actuary_id, expected_plan_version):
    resp = api_client.certify_valuation_run(
        run_id,
        {"expected_plan_version": expected_plan_version},
        make_senior_actuary_headers(review_actuary_id),
    )
    return get_success_data(resp, 200)


def get_run(run_id):
    resp = api_client.get_valuation_run(run_id, PLAN_ADMIN)
    return get_success_data(resp, 200)


def list_accruals(run_id):
    resp = api_client.list_accruals_by_run(run_id, PLAN_ADMIN)
    return get_success_data(resp, 200)


def list_demands(plan_id):
    resp = api_client.list_contribution_demands(plan_id, PLAN_ADMIN)
    return get_success_data(resp, 200)


def get_demand(demand_id):
    resp = api_client.get_contribution_demand(demand_id, PLAN_ADMIN)
    return get_success_data(resp, 200)


def get_ledger(plan_id):
    """Returns the single ledger entry (index 0 of the 0-1 array)."""
    resp = api_client.get_credit_balance_ledger(plan_id, PLAN_ADMIN)
    data = get_success_data(resp, 200)
    return data[0]


def list_elections_for_demand(demand_id):
    resp = api_client.list_elections_by_demand(demand_id, PLAN_ADMIN)
    return get_success_data(resp, 200)


def list_elections_for_plan(plan_id):
    resp = api_client.list_credit_balance_elections(plan_id, PLAN_ADMIN)
    return get_success_data(resp, 200)


def create_election(plan_id, demand_id, amount):
    """Create an election against the plan's current version. Returns the election."""
    plan_v = get_plan_version(plan_id)
    resp = api_client.create_credit_balance_election(
        plan_id,
        {
            "contribution_demand_id": demand_id,
            "amount": amount,
            "expected_plan_version": plan_v,
        },
        PLAN_ADMIN,
    )
    return get_success_data(resp, 201)


def create_payment(demand_id, amount, paid_on="2028-05-01"):
    resp = api_client.create_contribution_payment(
        demand_id,
        {"amount": amount, "paid_on": paid_on},
        PLAN_ADMIN,
    )
    return get_success_data(resp, 201)


def set_clock(to_iso8601):
    resp = api_client.set_clock({"to_iso8601": to_iso8601}, FIRM_ADMIN)
    return get_success_data(resp, 200)


def create_pbgc_filing(plan_id, run_id, premium_method="STANDARD"):
    resp = api_client.create_pbgc_filing(
        plan_id,
        {"valuation_run_id": run_id, "premium_method": premium_method},
        PLAN_ADMIN,
    )
    return get_success_data(resp, 201)


def get_pbgc_filing(filing_id):
    resp = api_client.get_pbgc_filing(filing_id, PLAN_ADMIN)
    return get_success_data(resp, 200)


def create_disclosure_report(plan_id, run_id):
    resp = api_client.create_disclosure_report(
        plan_id,
        {"valuation_run_id": run_id},
        PLAN_ADMIN,
    )
    return get_success_data(resp, 201)


# ---------------------------------------------------------------------------
# Tier 5: Full lifecycle — certified plan (the canonical "Family A" fixture)
# ---------------------------------------------------------------------------

def setup_certified_plan(
    sponsor_name="Family A Co",
    participant_rows=None,
    market_value_begin=60000,
    contributions_received=0,
    benefits_paid=2000,
    investment_return=3000,
    initial_carryover_balance=None,
    initial_prefunding_balance=None,
    prior_aftap_pct=84.00,
):
    """Build a plan through to a CERTIFIED valuation run.

    Default census = the canonical 3-participant family:
      ACTIVE age 62 yos 10 comp 100000, ACTIVE age 60 yos 5 comp 60000,
      RETIREE age 63 benefit 50000  -> FT 67172.20, NC 1958.24.
    Default asset statement: mv_begin 60000, benefits 2000, return 3000
      -> mv_end == smoothed == 61000.00 (gain 0).

    Returns a dict with keys: plan, prep, rev, batch, aset, stmt, ava, run,
    and demand (first demand of the plan).
    """
    if participant_rows is None:
        participant_rows = [
            {"external_ref": "A1", "date_of_birth": "1966-03-10", "status": "ACTIVE",
             "years_of_service": 10, "annual_compensation": 100000},
            {"external_ref": "A2", "date_of_birth": "1968-11-20", "status": "ACTIVE",
             "years_of_service": 5, "annual_compensation": 60000},
            {"external_ref": "R1", "date_of_birth": "1965-01-30", "status": "RETIREE",
             "current_annual_benefit": 50000},
        ]

    plan = create_plan(
        sponsor_name=sponsor_name,
        prior_aftap_pct=prior_aftap_pct,
        initial_carryover_balance=initial_carryover_balance,
        initial_prefunding_balance=initial_prefunding_balance,
    )
    plan_id = plan["id"]
    prep, rev = register_prep_and_review_actuaries()
    batch = create_locked_census(plan_id, participant_rows)
    aset = create_locked_assumption_set(plan_id, prep["id"], rev["id"])
    stmt = create_asset_statement(
        plan_id,
        market_value_begin=market_value_begin,
        contributions_received=contributions_received,
        benefits_paid=benefits_paid,
        investment_return=investment_return,
    )
    ava = create_asset_valuation(plan_id, prep["id"])
    run = create_valuation_run(plan_id, prep["id"], batch["id"], aset["id"], ava["id"])
    compute_run(run["id"], prep["id"])
    plan_v = get_plan_version(plan_id)
    certify_run(run["id"], rev["id"], plan_v)
    demands = list_demands(plan_id)
    return {
        "plan": get_plan(plan_id),
        "prep": prep,
        "rev": rev,
        "batch": batch,
        "aset": aset,
        "stmt": stmt,
        "ava": ava,
        "run": get_run(run["id"]),
        "demand": demands[0] if demands else None,
    }
