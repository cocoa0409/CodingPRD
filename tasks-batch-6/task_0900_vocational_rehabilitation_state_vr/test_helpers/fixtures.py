"""Composite setup helpers for multi-step VR test prerequisites.

Every helper builds its preconditions from scratch through PRD-declared endpoints
(the harness restarts the server with an empty database before every test). Setup
calls use get_success_data() so a broken precondition surfaces as a clear
"setup failed" rather than a confusing assertion deep inside a test.

A setup context ("ctx") returned by the case builders is a plain dict carrying the
created ids and the ownership-correct headers:
    counselor_id, supervisor_id, provider_id, category_id, case_id, ipe_id,
    counselor_headers, supervisor_headers, provider_headers
plus placement_id / auth_id where the builder created them.
"""
from prd_bench_local_runner.testing import get_success_data
from .api_client import api_client
from .factories import (
    create_counselor_payload, create_supervisor_payload, create_provider_payload,
    create_priority_category_payload, create_case_payload, create_ipe_payload,
    create_authorization_payload, create_payment_payload, create_placement_payload,
    create_progress_review_payload,
)
from .test_users import (
    TEST_USERS, make_counselor_headers, make_supervisor_headers, make_provider_headers,
)

VRADMIN = TEST_USERS["vradmin_headers"]
FISCAL = TEST_USERS["fiscal_officer_headers"]


# ─── Primitive creators ───────────────────────────────────────────────

def set_clock(iso: str):
    return get_success_data(api_client.set_clock({"to_iso8601": iso}, VRADMIN))


def create_counselor(**overrides) -> dict:
    return get_success_data(api_client.create_counselor(create_counselor_payload(**overrides), VRADMIN))


def create_supervisor(**overrides) -> dict:
    return get_success_data(api_client.create_supervisor(create_supervisor_payload(**overrides), VRADMIN))


def create_provider(**overrides) -> dict:
    return get_success_data(api_client.create_provider(create_provider_payload(**overrides), VRADMIN))


def create_category(**overrides) -> dict:
    return get_success_data(api_client.create_priority_category(create_priority_category_payload(**overrides), VRADMIN))


def get_case(case_id: str) -> dict:
    return get_success_data(api_client.get_case(case_id, VRADMIN))


def get_case_version(case_id: str) -> int:
    return get_case(case_id)["version"]


# ─── Tier 1 / Tier 2: case state progression ──────────────────────────

def bootstrap_actors(provider=True, provider_overrides=None, category_overrides=None):
    """Create counselor, supervisor, (optional) provider and one rank-1 MSD category.
    Returns a dict of ids + ownership-correct headers."""
    counselor = create_counselor()
    supervisor = create_supervisor()
    category = create_category(**(category_overrides or {}))
    ctx = {
        "counselor_id": counselor["id"],
        "supervisor_id": supervisor["id"],
        "category_id": category["id"],
        "counselor_headers": make_counselor_headers(counselor["id"]),
        "supervisor_headers": make_supervisor_headers(supervisor["id"]),
    }
    if provider:
        prov = create_provider(**(provider_overrides or {}))
        ctx["provider_id"] = prov["id"]
        ctx["provider_headers"] = make_provider_headers(prov["id"])
    return ctx


def create_referral(ctx, **case_overrides) -> str:
    case = get_success_data(api_client.create_case(create_case_payload(**case_overrides), ctx["counselor_headers"]))
    return case["id"]


def advance_to_application(ctx, case_id):
    return get_success_data(api_client.record_application(case_id, ctx["counselor_headers"]))


def make_eligible(ctx, case_id, disability_significance="MSD"):
    return get_success_data(api_client.record_eligibility(
        case_id, {"decision": "ELIGIBLE", "disability_significance": disability_significance},
        ctx["counselor_headers"]))


def setup_plan_development_case(monthly_income_cents=150000, budget_allocated_cents=500000,
                                slot_capacity=5, disability_type="PHYSICAL", provider=True,
                                provider_overrides=None):
    """Bootstrap actors + a case reserved into PLAN_DEVELOPMENT with a DRAFT IPE.
    Returns ctx with case_id and ipe_id."""
    ctx = bootstrap_actors(provider=provider, provider_overrides=provider_overrides,
                           category_overrides={"slot_capacity": slot_capacity})
    case_id = create_referral(ctx, monthly_income_cents=monthly_income_cents,
                              budget_allocated_cents=budget_allocated_cents,
                              disability_type=disability_type)
    advance_to_application(ctx, case_id)
    make_eligible(ctx, case_id)
    ipe = get_success_data(api_client.create_ipe(create_ipe_payload(case_id), ctx["counselor_headers"]))
    ctx["case_id"] = case_id
    ctx["ipe_id"] = ipe["id"]
    return ctx


def setup_services_active_case(monthly_income_cents=150000, budget_allocated_cents=500000,
                               slot_capacity=5, disability_type="PHYSICAL", provider=True,
                               provider_overrides=None):
    """PLAN_DEVELOPMENT case whose IPE is submitted and approved -> case SERVICES_ACTIVE,
    IPE APPROVED. Returns ctx with case_id and ipe_id."""
    ctx = setup_plan_development_case(monthly_income_cents=monthly_income_cents,
                                      budget_allocated_cents=budget_allocated_cents,
                                      slot_capacity=slot_capacity, disability_type=disability_type,
                                      provider=provider, provider_overrides=provider_overrides)
    get_success_data(api_client.submit_ipe(ctx["ipe_id"], ctx["counselor_headers"]))
    get_success_data(api_client.approve_ipe(ctx["ipe_id"], ctx["supervisor_headers"]))
    return ctx


# ─── Tier 3: authorization lifecycle shortcuts ────────────────────────

def new_services_active_case(counselor_headers, supervisor_headers,
                             budget_allocated_cents=1000000, monthly_income_cents=150000,
                             consumer_full_name="Al Ray"):
    """Create a fresh MSD case owned by the given counselor and take it to
    SERVICES_ACTIVE with an APPROVED IPE. Assumes a rank-1 MSD category with a free
    slot already exists. Returns (case_id, ipe_id)."""
    case = get_success_data(api_client.create_case(
        create_case_payload(budget_allocated_cents=budget_allocated_cents,
                            monthly_income_cents=monthly_income_cents,
                            consumer_full_name=consumer_full_name), counselor_headers))
    get_success_data(api_client.record_application(case["id"], counselor_headers))
    get_success_data(api_client.record_eligibility(
        case["id"], {"decision": "ELIGIBLE", "disability_significance": "MSD"}, counselor_headers))
    ipe = get_success_data(api_client.create_ipe(create_ipe_payload(case["id"]), counselor_headers))
    get_success_data(api_client.submit_ipe(ipe["id"], counselor_headers))
    get_success_data(api_client.approve_ipe(ipe["id"], supervisor_headers))
    return case["id"], ipe["id"]


def request_authorization(ctx, **auth_overrides):
    """Create a REQUESTED authorization on ctx's case/ipe/provider. Returns the authorization."""
    return get_success_data(api_client.create_authorization(
        create_authorization_payload(ctx["case_id"], ctx["ipe_id"], ctx["provider_id"], **auth_overrides),
        ctx["counselor_headers"]))


def approve_authorization(ctx, authorization_id, expected_case_version=None):
    """Approve an authorization, defaulting expected_case_version to the case's current version."""
    if expected_case_version is None:
        expected_case_version = get_case_version(ctx["case_id"])
    return get_success_data(api_client.approve_authorization(
        authorization_id, {"expected_case_version": expected_case_version}, ctx["supervisor_headers"]))


def request_and_approve_authorization(ctx, **auth_overrides):
    """Create + approve an authorization (funds committed). Returns the APPROVED authorization."""
    auth = request_authorization(ctx, **auth_overrides)
    return approve_authorization(ctx, auth["id"])


def create_pending_payment(authorization_id, amount_cents):
    return get_success_data(api_client.create_payment(
        create_payment_payload(authorization_id, amount_cents=amount_cents), FISCAL))


def create_issued_payment(authorization_id, amount_cents):
    payment = create_pending_payment(authorization_id, amount_cents)
    return get_success_data(api_client.issue_payment(payment["id"], FISCAL))


# ─── Tier 3/4: placement & stabilization ──────────────────────────────

def setup_employed_case(employment_type="COMPETITIVE_INTEGRATED", weekly_wage_cents=50000,
                        hours_per_week=40, placement_date="2026-05-01",
                        monthly_income_cents=150000, budget_allocated_cents=500000,
                        slot_capacity=5, disability_type="PHYSICAL"):
    """SERVICES_ACTIVE case with a PLACED placement -> case EMPLOYED.
    Returns ctx with placement_id."""
    ctx = setup_services_active_case(monthly_income_cents=monthly_income_cents,
                                     budget_allocated_cents=budget_allocated_cents,
                                     slot_capacity=slot_capacity, disability_type=disability_type,
                                     provider=True)
    placement = get_success_data(api_client.create_placement(
        create_placement_payload(ctx["case_id"], ctx["ipe_id"], employer_name="Acme",
                                 placement_date=placement_date, weekly_wage_cents=weekly_wage_cents,
                                 hours_per_week=hours_per_week, employment_type=employment_type),
        ctx["counselor_headers"]))
    ctx["placement_id"] = placement["id"]
    return ctx


def setup_stabilizing_placement(employment_type="COMPETITIVE_INTEGRATED", weekly_wage_cents=50000,
                                start_clock="2026-05-01T00:00:00Z", **kwargs):
    """EMPLOYED case whose placement has begun stabilization (STABILIZING) with
    stabilization_start_date == start_clock's date. Returns ctx with placement_id.

    The clock is set to start_clock before begin-stabilization so the window origin
    is deterministic; tests advance the clock afterward."""
    set_clock(start_clock)
    ctx = setup_employed_case(employment_type=employment_type, weekly_wage_cents=weekly_wage_cents, **kwargs)
    get_success_data(api_client.begin_stabilization(ctx["placement_id"], ctx["counselor_headers"]))
    return ctx


def add_progress_review(ctx, review_date, reported_weekly_wage_cents, status_ok=None):
    payload = create_progress_review_payload(ctx["placement_id"], review_date, reported_weekly_wage_cents)
    if status_ok is not None:
        payload["status_ok"] = status_ok
    return get_success_data(api_client.create_progress_review(payload, ctx["counselor_headers"]))
