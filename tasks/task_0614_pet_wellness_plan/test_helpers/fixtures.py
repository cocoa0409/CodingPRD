"""Composite setup helpers for multi-step test prerequisites.

Most interesting claims require the system to be walked into a specific state
(catalogue -> account -> membership -> pets -> activate -> visits -> epochs).
These helpers encapsulate those chains so tests focus on assertions.

Uses get_success_data() (lenient 2xx validator) for setup calls so a setup
failure surfaces as a clear "Setup failed" rather than a confusing assertion.

Identity threading: a Member is entity_backed on its MemberAccount, so every
ownership-gated call uses make_member_headers(account_id) with the real account
id — never the shared constant.
"""
import itertools
from prd_bench_local_runner.testing import get_success_data
from .api_client import api_client
from .factories import (
    create_plan_payload,
    create_plan_service_payload,
    create_clinic_payload,
    create_member_account_payload,
    create_membership_payload,
    create_pet_payload,
    record_visit_payload,
    set_clock_payload,
)
from .test_users import TEST_USERS, make_member_headers

PLAN_ADMIN = TEST_USERS["plan_admin_headers"]
CLINIC_STAFF = TEST_USERS["clinic_staff_headers"]
BILLING_ADMIN = TEST_USERS["billing_admin_headers"]

# Unique-email counter so multiple accounts created within one test never collide.
_email_seq = itertools.count(1)


def unique_email(prefix="m"):
    return f"{prefix}{next(_email_seq)}@example.com"


# ---------------------------------------------------------------------------
# Clock helpers
# ---------------------------------------------------------------------------
def set_clock(iso8601: str):
    """Advance the logical clock (PlanAdmin/BillingAdmin capability)."""
    return get_success_data(api_client.set_clock(set_clock_payload(iso8601), PLAN_ADMIN))


def run_epoch():
    """Run the billing epoch as BillingAdmin."""
    return api_client.run_epoch(BILLING_ADMIN)


# ---------------------------------------------------------------------------
# Tier 1: Catalogue primitives
# ---------------------------------------------------------------------------
def create_plan(**overrides) -> dict:
    return get_success_data(api_client.create_plan(create_plan_payload(**overrides), PLAN_ADMIN))


def add_plan_service(plan_id, **overrides) -> dict:
    return get_success_data(
        api_client.create_plan_service(create_plan_service_payload(plan_id, **overrides), PLAN_ADMIN)
    )


def create_clinic(**overrides) -> dict:
    return get_success_data(api_client.create_clinic(create_clinic_payload(**overrides), PLAN_ADMIN))


def create_member_account(home_clinic_id, email=None, **overrides) -> dict:
    email = email or unique_email()
    return get_success_data(
        api_client.create_member_account(
            create_member_account_payload(home_clinic_id, email, **overrides),
            TEST_USERS["member_headers"],
        )
    )


# ---------------------------------------------------------------------------
# Tier 2: Catalogue with inclusion lines
# ---------------------------------------------------------------------------
def create_plan_with_services(services, **plan_overrides):
    """Create a plan plus its inclusion lines.

    services: list of dicts each with service_code/included_quantity/unit_value_cents.
    Returns (plan, [plan_service, ...]).
    """
    plan = create_plan(**plan_overrides)
    created = []
    for svc in services:
        created.append(add_plan_service(plan["id"], **svc))
    return plan, created


def setup_catalogue(services=None, plan_overrides=None, clinic_overrides=None):
    """Clock at 2026-01-01, a plan with inclusion lines, and a clinic.

    Returns (plan, plan_services, clinic). Defaults: EXAM 2@6000 inclusion line.
    """
    set_clock("2026-01-01T00:00:00Z")
    if services is None:
        services = [{"service_code": "EXAM", "included_quantity": 2, "unit_value_cents": 6000}]
    plan, plan_services = create_plan_with_services(services, **(plan_overrides or {}))
    clinic = create_clinic(**(clinic_overrides or {}))
    return plan, plan_services, clinic


# ---------------------------------------------------------------------------
# Tier 3: Membership lifecycle
# ---------------------------------------------------------------------------
def create_account_and_membership(plan_id, clinic_id, billing_anchor_day=1,
                                  auto_renew=None, email=None):
    """Register an account and create a PENDING_PAYMENT membership under it.

    Returns (account, membership). The membership is owned by the new account,
    so subsequent ownership-gated calls must use make_member_headers(account_id).
    """
    account = create_member_account(clinic_id, email=email)
    overrides = {"billing_anchor_day": billing_anchor_day}
    if auto_renew is not None:
        overrides["auto_renew"] = auto_renew
    membership = get_success_data(
        api_client.create_membership(
            create_membership_payload(account["id"], plan_id, **overrides),
            make_member_headers(account["id"]),
        )
    )
    return account, membership


def add_pet(membership_id, account_id, **pet_overrides) -> dict:
    return get_success_data(
        api_client.add_pet(membership_id, create_pet_payload(**pet_overrides),
                           make_member_headers(account_id))
    )


def activate_membership(membership_id, account_id) -> dict:
    return get_success_data(
        api_client.activate_membership(membership_id, make_member_headers(account_id))
    )


def setup_pending_membership(services=None, plan_overrides=None,
                             billing_anchor_day=1, auto_renew=None,
                             pet_overrides=None, with_pet=True):
    """Catalogue + account + PENDING_PAYMENT membership (+ one pet by default).

    Returns dict with keys: plan, plan_services, clinic, account, membership, pet.
    `pet` is None when with_pet is False.
    """
    plan, plan_services, clinic = setup_catalogue(services=services, plan_overrides=plan_overrides)
    account, membership = create_account_and_membership(
        plan["id"], clinic["id"], billing_anchor_day=billing_anchor_day, auto_renew=auto_renew
    )
    pet = None
    if with_pet:
        pet = add_pet(membership["id"], account["id"], **(pet_overrides or {}))
    return {
        "plan": plan,
        "plan_services": plan_services,
        "clinic": clinic,
        "account": account,
        "membership": membership,
        "pet": pet,
    }


def setup_enrolled_membership(services=None, plan_overrides=None,
                              billing_anchor_day=1, auto_renew=None,
                              pet_overrides=None):
    """Full chain through activation: an ENROLLED membership with its first
    ACTIVE ContractTerm, granted ServiceCredit buckets, and first BillingCycle.

    Returns dict with keys: plan, plan_services, clinic, account, membership
    (post-activate), pet, term (first ContractTerm).
    """
    ctx = setup_pending_membership(
        services=services, plan_overrides=plan_overrides,
        billing_anchor_day=billing_anchor_day, auto_renew=auto_renew,
        pet_overrides=pet_overrides, with_pet=True,
    )
    membership = activate_membership(ctx["membership"]["id"], ctx["account"]["id"])
    ctx["membership"] = membership
    ctx["term"] = first_active_term(membership["id"])
    return ctx


# ---------------------------------------------------------------------------
# Tier 4: Visits
# ---------------------------------------------------------------------------
def record_visit(membership_id, enrolled_pet_id, clinic_id, service_code) -> dict:
    return get_success_data(
        api_client.record_visit(
            membership_id,
            record_visit_payload(enrolled_pet_id, clinic_id, service_code),
            CLINIC_STAFF,
        )
    )


def void_visit(visit_id) -> dict:
    return get_success_data(api_client.void_visit(visit_id, CLINIC_STAFF))


# ---------------------------------------------------------------------------
# Read helpers (lenient) — used inside fixtures to discover derived ids.
# ---------------------------------------------------------------------------
def list_terms(membership_id):
    data, _meta = _paginate(api_client.list_contract_terms,
                            params={"membership_id": membership_id, "limit": 100})
    return data


def first_active_term(membership_id):
    for term in list_terms(membership_id):
        if term["status"] == "ACTIVE":
            return term
    # Fall back to term_index 1 if no ACTIVE term is present.
    terms = sorted(list_terms(membership_id), key=lambda t: t["term_index"])
    return terms[0] if terms else None


def term_by_index(membership_id, term_index):
    for term in list_terms(membership_id):
        if term["term_index"] == term_index:
            return term
    return None


def get_term(term_id):
    return get_success_data(api_client.get_contract_term(term_id, BILLING_ADMIN))


def list_term_credits(term_id, **params):
    data, _meta = _paginate(lambda headers, params=None: api_client.list_term_credits(term_id, headers, params),
                            params={**params, "limit": 100})
    return data


def get_membership(membership_id):
    return get_success_data(api_client.get_membership(membership_id, BILLING_ADMIN))


def get_account(account_id):
    return get_success_data(api_client.get_member_account(account_id, BILLING_ADMIN))


def get_pet(membership_id, pet_id):
    return get_success_data(api_client.get_pet(membership_id, pet_id, BILLING_ADMIN))


def get_visit(visit_id):
    return get_success_data(api_client.get_visit(visit_id, BILLING_ADMIN))


def list_billing_cycles(membership_id):
    data, meta = _paginate(api_client.list_billing_cycles,
                           params={"membership_id": membership_id, "limit": 100})
    return data, meta


def _paginate(list_fn, params=None):
    """Call a list endpoint as BillingAdmin (broad read role) and return (data, meta)."""
    resp = list_fn(BILLING_ADMIN, params=params)
    body = resp.json()
    data = body.get("data", [])
    meta = body.get("meta", {})
    return data, meta
