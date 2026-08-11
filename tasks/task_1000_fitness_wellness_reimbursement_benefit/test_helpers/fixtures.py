"""Composite setup helpers.

Every fixture builds its preconditions from scratch against PRD-declared
endpoints (the server is restarted with an empty database before each test).
Setup calls use get_success_data() so failures surface as clear setup errors.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import STANDARD_TIER, TEST_DEFAULTS
from .factories import (
    create_employer_payload,
    create_plan_payload,
    tier_payload,
    put_tiers_payload,
    create_member_payload,
    create_dependent_payload,
    create_provider_payload,
    create_enrollment_payload,
    create_visit_payload,
    create_claim_payload,
    line_item,
    create_funding_account_payload,
    create_statement_payload,
)
from .test_users import TEST_USERS, make_member_headers, make_provider_operator_headers

ADMIN = TEST_USERS["benefits_admin_headers"]
REVIEWER = TEST_USERS["claims_reviewer_headers"]
AUDITOR = TEST_USERS["auditor_headers"]
PLATFORM = TEST_USERS["platform_admin_headers"]


# ---------------------------------------------------------------------------
# Tier 1 / 2: single-entity builders and the standard world
# ---------------------------------------------------------------------------

def create_employer(name="ACME", funding_model="PREFUNDED") -> dict:
    resp = api_client.create_employer(create_employer_payload(name=name, funding_model=funding_model), ADMIN)
    return get_success_data(resp)


def create_draft_plan(employer_id, **overrides) -> dict:
    resp = api_client.create_benefit_plan(create_plan_payload(employer_id, **overrides), ADMIN)
    return get_success_data(resp)


def set_plan_tiers(plan_id, tiers=None, expected_plan_version=None) -> dict:
    """Replace the plan's tier set. Returns the updated plan."""
    plan = get_success_data(api_client.get_benefit_plan(plan_id, ADMIN))
    version = expected_plan_version if expected_plan_version is not None else plan["version"]
    payload = put_tiers_payload(tiers or [tier_payload()], version)
    return get_success_data(api_client.put_plan_tiers(plan_id, payload, ADMIN))


def create_active_plan(employer_id, tiers=None, **plan_overrides) -> dict:
    """Draft plan -> replace tiers -> activate. Returns the ACTIVE plan."""
    plan = create_draft_plan(employer_id, **plan_overrides)
    set_plan_tiers(plan["id"], tiers=tiers, expected_plan_version=plan["version"])
    return get_success_data(api_client.activate_plan(plan["id"], ADMIN))


def create_funding_account(employer_id, initial_deposit_cents=None, benefit_year=None) -> dict:
    payload = create_funding_account_payload(employer_id)
    if initial_deposit_cents is not None:
        payload["initial_deposit_cents"] = initial_deposit_cents
    if benefit_year is not None:
        payload["benefit_year"] = benefit_year
    return get_success_data(api_client.create_funding_account(payload, ADMIN))


def create_active_provider(**overrides) -> dict:
    provider = get_success_data(api_client.create_provider(create_provider_payload(**overrides), ADMIN))
    return get_success_data(api_client.activate_provider(provider["id"], ADMIN))


def create_member(employer_id, plan_id, **overrides) -> dict:
    """Default hire_date 2026-03-01 makes the member ELIGIBLE at creation under
    the default clock 2026-05-01 (eligibility_date 2026-03-31 already passed)."""
    return get_success_data(api_client.create_member(create_member_payload(employer_id, plan_id, **overrides), ADMIN))


def create_enrollment(member_id, plan_id) -> dict:
    return get_success_data(api_client.create_enrollment(create_enrollment_payload(member_id, plan_id), ADMIN))


def standard_world(
    funding_cents=TEST_DEFAULTS["FUNDING_OPENING_CENTS"],
    tiers=None,
    plan_overrides=None,
    provider_overrides=None,
    member_overrides=None,
    include_funding=True,
    include_provider=True,
    include_enrollment=True,
) -> dict:
    """Employer + ACTIVE plan (one INDIVIDUAL tier by default) + optional funding
    account + optional ACTIVE IN_NETWORK provider + ELIGIBLE member + optional
    ACTIVE enrollment. Returns a dict of the created entities."""
    world = {}
    employer = create_employer()
    world["employer"] = employer
    plan = create_active_plan(employer["id"], tiers=tiers, **(plan_overrides or {}))
    world["plan"] = plan
    if include_funding:
        world["funding"] = create_funding_account(employer["id"], initial_deposit_cents=funding_cents)
    if include_provider:
        world["provider"] = create_active_provider(**(provider_overrides or {}))
    member = create_member(employer["id"], plan["id"], **(member_overrides or {}))
    world["member"] = member
    if include_enrollment:
        world["enrollment"] = create_enrollment(member["id"], plan["id"])
    return world


# ---------------------------------------------------------------------------
# Tier 3: claim / visit lifecycle shortcuts
# ---------------------------------------------------------------------------

def member_headers(world) -> dict:
    return make_member_headers(world["member"]["id"])


def provider_headers(world) -> dict:
    return make_provider_operator_headers(world["provider"]["id"])


def submit_claim(world, amount_cents, receipt_ref, service_date="2026-05-02T10:00:00Z",
                 visit_ids=None, as_provider=False, claim_type=None, extra_lines=None) -> dict:
    """Submit a claim. Default: Member REIMBURSEMENT with a single untaxed line.

    For REIMBURSEMENT claims the PRD lets the caller supply `provider_id` in
    the body (§3.7); we default to the world's ACTIVE IN_NETWORK provider so
    coverage resolves deterministically to `in_network_pct` instead of
    falling through to an unspecified no-provider case."""
    if extra_lines is not None:
        items = extra_lines
    else:
        items = [line_item(amount_cents)]
    payload = create_claim_payload(
        world["enrollment"]["id"],
        receipt_ref,
        line_items=items,
        service_date=service_date,
    )
    if visit_ids is not None:
        payload["visit_ids"] = visit_ids
    if as_provider:
        payload["claim_type"] = claim_type or "DIRECT_PAY"
        payload["member_id"] = world["member"]["id"]
        headers = provider_headers(world)
    else:
        if claim_type:
            payload["claim_type"] = claim_type
        if visit_ids is None and "provider" in world:
            payload["provider_id"] = world["provider"]["id"]
        headers = member_headers(world)
    return get_success_data(api_client.create_claim(payload, headers))


def review_claim(claim_id) -> dict:
    return get_success_data(api_client.start_review(claim_id, REVIEWER))


def approve_claim(claim_id) -> dict:
    return get_success_data(api_client.approve_claim(claim_id, REVIEWER))


def pay_claim(claim_id) -> dict:
    return get_success_data(api_client.pay_claim(claim_id, ADMIN))


def submit_reviewed_claim(world, amount_cents, receipt_ref, **kwargs) -> dict:
    claim = submit_claim(world, amount_cents, receipt_ref, **kwargs)
    review_claim(claim["id"])
    return claim


def submit_approved_claim(world, amount_cents, receipt_ref, **kwargs) -> dict:
    claim = submit_reviewed_claim(world, amount_cents, receipt_ref, **kwargs)
    return approve_claim(claim["id"])


def submit_paid_claim(world, amount_cents, receipt_ref, **kwargs) -> dict:
    claim = submit_approved_claim(world, amount_cents, receipt_ref, **kwargs)
    return pay_claim(claim["id"])


def record_visit(world, check_in_at, check_out_at, verification_method="GEO_FENCE") -> dict:
    payload = create_visit_payload(
        world["enrollment"]["id"],
        world["member"]["id"],
        check_in_at=check_in_at,
        check_out_at=check_out_at,
        verification_method=verification_method,
    )
    return get_success_data(api_client.create_visit(payload, provider_headers(world)))


def verify_visit(visit_id) -> dict:
    return get_success_data(api_client.verify_visit(visit_id, REVIEWER))


def record_hourly_visits(world, count, start_hour=8, day="2026-05-02", verification_method="GEO_FENCE") -> list:
    """Record `count` adjacent one-hour visits starting at start_hour."""
    visits = []
    for i in range(count):
        visits.append(record_visit(
            world,
            f"{day}T{start_hour + i:02d}:00:00Z",
            f"{day}T{start_hour + i + 1:02d}:00:00Z",
            verification_method=verification_method,
        ))
    return visits


# ---------------------------------------------------------------------------
# Tier 4: fraud-scenario setup
# ---------------------------------------------------------------------------

def setup_flagged_visit(world, verified_geo_count=6) -> dict:
    """Record `verified_geo_count` GEO_FENCE visits and verify them, then record
    and verify one MANUAL_REVIEW visit. The final score of the MANUAL_REVIEW
    visit is 30 (geofence mismatch) + 10 per visit beyond the fifth in the
    VERIFIED-only velocity window, which crosses the flag threshold of 50 when
    verified_geo_count is 6. Returns the flagged visit."""
    visits = record_hourly_visits(world, verified_geo_count)
    for v in visits:
        verify_visit(v["id"])
    flagged = record_visit(
        world,
        f"2026-05-02T{8 + verified_geo_count:02d}:00:00Z",
        f"2026-05-02T{9 + verified_geo_count:02d}:00:00Z",
        verification_method="MANUAL_REVIEW",
    )
    return verify_visit(flagged["id"])


# ---------------------------------------------------------------------------
# Tier 5: statements
# ---------------------------------------------------------------------------

def create_statement(member_id, period_yyyymm="2026-05") -> dict:
    return get_success_data(api_client.create_statement(create_statement_payload(member_id, period_yyyymm), ADMIN))


def set_clock(to_iso8601) -> dict:
    return get_success_data(api_client.set_clock(to_iso8601, PLATFORM))
