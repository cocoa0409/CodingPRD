"""Composite setup helpers for the Moving-Labor Marketplace API.

These encapsulate the multi-step preambles that most interesting claims require (create
config -> draft job -> quote -> book -> crew -> execute -> settle). Every fixture uses the
lenient get_success_data() validator internally, so a broken precondition surfaces as a
clear "Setup failed" rather than a confusing assertion. Each test starts against an empty
database, so fixtures always build their preconditions from scratch.

Identity threading: a Customer/Helper is entity_backed, so any ownership-gated call uses
make_customer_headers(customer_id) / make_helper_headers(helper_id) with the real id.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .test_users import (
    TEST_USERS, make_customer_headers, make_helper_headers,
)
from . import factories as f

ADMIN = TEST_USERS["admin_headers"]
DISPATCHER = TEST_USERS["dispatcher_headers"]


# ---------------------------------------------------------------------------
# Low-level creators (each returns the created / refreshed resource dict)
# ---------------------------------------------------------------------------
def create_rate_card(api=api_client, **overrides) -> dict:
    return get_success_data(api.create_rate_card(f.create_rate_card_payload(**overrides), ADMIN))


def create_insurance_policy(api=api_client, **overrides) -> dict:
    return get_success_data(api.create_insurance_policy(f.create_insurance_policy_payload(**overrides), ADMIN))


def create_customer(api=api_client, **overrides) -> dict:
    return get_success_data(api.create_customer(f.create_customer_payload(**overrides), ADMIN))


def create_truck(api=api_client, **overrides) -> dict:
    return get_success_data(api.create_truck(f.create_truck_payload(**overrides), ADMIN))


def create_helper(api=api_client, **overrides) -> dict:
    """Create a helper (begins PENDING_REVIEW)."""
    return get_success_data(api.create_helper(f.create_helper_payload(**overrides), ADMIN))


def vet_helper(api, helper_id, decision) -> dict:
    return get_success_data(api.vet_helper(helper_id, f.vet_payload(decision), ADMIN))


def create_approved_helper(api=api_client, **overrides) -> dict:
    """Create a helper and vet it APPROVED. Returns the refreshed helper."""
    helper = create_helper(api, **overrides)
    vet_helper(api, helper["id"], "APPROVE")
    return get_success_data(api.get_helper(helper["id"], ADMIN))


def set_clock(api, iso: str):
    return get_success_data(api.set_clock(f.clock_payload(iso), ADMIN))


def create_config(api=api_client, policy_tier="BASIC", policy_overrides=None, rate_overrides=None):
    """Baseline reference data + a customer. Returns (rate_card, policy, customer)."""
    rate_card = create_rate_card(api, **(rate_overrides or {}))
    policy = create_insurance_policy(api, tier=policy_tier, **(policy_overrides or {}))
    customer = create_customer(api)
    return rate_card, policy, customer


# ---------------------------------------------------------------------------
# Job progression helpers
# ---------------------------------------------------------------------------
def create_draft_job(api, rate_card_id, insurance_policy_id, customer_id, **overrides) -> dict:
    """POST /jobs as the owning customer. Returns the DRAFT job."""
    payload = f.create_job_payload(rate_card_id, insurance_policy_id, **overrides)
    return get_success_data(api.create_job(payload, make_customer_headers(customer_id)))


def add_addon(api, job_id, customer_id, addon_type, quantity, unit_fee_cents) -> dict:
    return get_success_data(api.add_addon(
        job_id, f.create_addon_payload(addon_type, quantity, unit_fee_cents),
        make_customer_headers(customer_id),
    ))


def request_quote(api, job_id, customer_id) -> dict:
    """POST /jobs/{id}/quote. Returns the newly created ACTIVE quote."""
    return get_success_data(api.quote_job(job_id, make_customer_headers(customer_id)))


def read_job_version(api, job_id, customer_id) -> int:
    return get_success_data(api.get_job(job_id, make_customer_headers(customer_id)))["version"]


def book_job(api, job_id, customer_id, quote_id, expected_version=None) -> dict:
    """POST /jobs/{id}/book. Reads the live version when expected_version is not supplied."""
    if expected_version is None:
        expected_version = read_job_version(api, job_id, customer_id)
    return get_success_data(api.book_job(
        job_id, f.book_payload(quote_id, expected_version), make_customer_headers(customer_id),
    ))


def create_quoted_job(api, rate_card_id, policy_id, customer_id, addons=None, **job_overrides):
    """Draft job (+ optional add-ons) then quote. Returns (job, quote); job is QUOTED."""
    job = create_draft_job(api, rate_card_id, policy_id, customer_id, **job_overrides)
    for addon in (addons or []):
        add_addon(api, job["id"], customer_id, addon["addon_type"], addon["quantity"], addon["unit_fee_cents"])
    quote = request_quote(api, job["id"], customer_id)
    return job, quote


def create_booked_job(api, rate_card_id, policy_id, customer_id, addons=None, **job_overrides):
    """Draft -> quote -> book. Returns (job_after_book, quote)."""
    job, quote = create_quoted_job(api, rate_card_id, policy_id, customer_id, addons=addons, **job_overrides)
    booked = book_job(api, job["id"], customer_id, quote["id"])
    return booked, quote


def setup_booked_job(api, policy_tier="BASIC", policy_overrides=None, rate_overrides=None,
                     addons=None, **job_overrides):
    """Full stack from empty DB to a BOOKED job.

    Returns (rate_card, policy, customer, job, quote)."""
    rate_card, policy, customer = create_config(
        api, policy_tier=policy_tier, policy_overrides=policy_overrides, rate_overrides=rate_overrides,
    )
    job, quote = create_booked_job(api, rate_card["id"], policy["id"], customer["id"],
                                   addons=addons, **job_overrides)
    return rate_card, policy, customer, job, quote


# ---------------------------------------------------------------------------
# Crewing helpers
# ---------------------------------------------------------------------------
def assign_helper(api, job_id, helper_id, **overrides) -> dict:
    return get_success_data(api.create_assignment(
        f.create_assignment_payload(job_id, helper_id, **overrides), DISPATCHER,
    ))


def check_in(api, assignment_id, helper_id) -> dict:
    return get_success_data(api.check_in(assignment_id, make_helper_headers(helper_id)))


def check_out(api, assignment_id, helper_id) -> dict:
    return get_success_data(api.check_out(assignment_id, make_helper_headers(helper_id)))


# ---------------------------------------------------------------------------
# Full lifecycle: settle a job and produce a payout
# ---------------------------------------------------------------------------
def setup_settled_job_with_payout(api, helper_pay_rate=4000, actual_hours=3.0,
                                  estimated_hours=3.0, tip_cents=1500, stars=5,
                                  policy_tier="BASIC", policy_overrides=None):
    """Empty DB -> SETTLED job with one RELEASED payout for the crew helper.

    crew_size 1, weekday window; helper assigned LEAD, checked in, job started, checked out,
    completed with actual_hours, rated with stars+tip, then settled.

    Returns dict with keys: rate_card, policy, customer, helper, job, assignment, rating, payout.
    """
    rate_card, policy, customer = create_config(
        api, policy_tier=policy_tier, policy_overrides=policy_overrides,
    )
    helper = create_approved_helper(api, base_hourly_rate_cents=helper_pay_rate, email="hs@x.com")
    job, quote = create_booked_job(
        api, rate_card["id"], policy["id"], customer["id"],
        crew_size=1, estimated_hours=estimated_hours,
        window_start="2026-03-10T09:00:00Z", window_end="2026-03-10T12:00:00Z",
    )
    assignment = assign_helper(api, job["id"], helper["id"], role="LEAD")
    check_in(api, assignment["id"], helper["id"])
    get_success_data(api.start_job(job["id"], DISPATCHER))
    check_out(api, assignment["id"], helper["id"])
    get_success_data(api.complete_job(job["id"], f.complete_payload(actual_hours), DISPATCHER))
    rating = get_success_data(api.create_rating(
        f.create_rating_payload(job["id"], helper["id"], stars, tip_cents=tip_cents),
        make_customer_headers(customer["id"]),
    ))
    get_success_data(api.settle_job(job["id"], ADMIN))
    payouts = get_success_data(api.list_payouts(ADMIN, params={"job_id": job["id"]}))
    payout = payouts[0]
    return {
        "rate_card": rate_card, "policy": policy, "customer": customer, "helper": helper,
        "job": job, "assignment": assignment, "rating": rating, "payout": payout,
    }


def setup_completed_ratable_job(api, helper, rate_card, policy, customer,
                                window_start="2026-03-10T09:00:00Z",
                                window_end="2026-03-10T12:00:00Z",
                                estimated_hours=3.0, actual_hours=3.0):
    """Drive a job to COMPLETED with `helper` as checked-out crew (ratable). Returns (job, assignment)."""
    job, quote = create_booked_job(
        api, rate_card["id"], policy["id"], customer["id"],
        crew_size=1, estimated_hours=estimated_hours,
        window_start=window_start, window_end=window_end,
    )
    assignment = assign_helper(api, job["id"], helper["id"], role="LEAD")
    check_in(api, assignment["id"], helper["id"])
    get_success_data(api.start_job(job["id"], DISPATCHER))
    check_out(api, assignment["id"], helper["id"])
    job = get_success_data(api.complete_job(job["id"], f.complete_payload(actual_hours), DISPATCHER))
    return job, assignment
