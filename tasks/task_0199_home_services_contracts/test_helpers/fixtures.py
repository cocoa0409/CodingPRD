"""Composite setup helpers for the Home Services Contracts API.

Most interesting claims need the system walked through a multi-step preamble:
clock -> plan -> customer -> site -> membership -> activate -> visit -> dispatch ->
depart -> arrive -> complete, with technicians, equipment, warranty claims, and
renewal offers layered on. These helpers encapsulate those sequences so the tests
read as assertions, not plumbing.

All setup calls use get_success_data() (lenient 2xx) so a broken precondition fails
loudly as "Setup step failed ...". Identity threading is honored: Technician and
Customer are entity-backed, so on-site and ownership calls use
make_technician_headers(tech_id) / make_customer_headers(customer_id) with the real id.
"""
from prd_bench_local_runner.testing import get_success_data
from .api_client import api_client
from .test_users import (
    TEST_USERS,
    make_technician_headers,
    make_customer_headers,
)
from . import factories as f
from .constants import BASE_CLOCK

ADMIN = TEST_USERS["contract_admin_headers"]
DISPATCHER = TEST_USERS["dispatcher_headers"]


# ---------------------------------------------------------------------------
# Tier 0: clock control
# ---------------------------------------------------------------------------
def set_clock(to_iso8601: str = BASE_CLOCK):
    """Pin the logical UTC clock (PRD §3.11)."""
    get_success_data(api_client.set_clock(to_iso8601, ADMIN))


def advance_clock(to_iso8601: str):
    """Advance the logical clock, firing offer auto-resolution (PRD §3.11)."""
    get_success_data(api_client.advance_clock(to_iso8601, ADMIN))


# ---------------------------------------------------------------------------
# Tier 1: single-entity creators
# ---------------------------------------------------------------------------
def create_plan(**overrides) -> dict:
    return get_success_data(api_client.create_service_plan(f.create_service_plan_payload(**overrides), ADMIN))


def create_customer(**overrides) -> dict:
    return get_success_data(api_client.create_customer(f.create_customer_payload(**overrides), ADMIN))


def create_site(customer_id: str, **overrides) -> dict:
    return get_success_data(api_client.create_site(f.create_site_payload(customer_id, **overrides), ADMIN))


def create_equipment(site_id: str, **overrides) -> dict:
    return get_success_data(api_client.create_equipment(f.create_equipment_payload(site_id, **overrides), ADMIN))


def create_technician(**overrides) -> dict:
    return get_success_data(api_client.create_technician(f.create_technician_payload(**overrides), ADMIN))


# ---------------------------------------------------------------------------
# Tier 2: membership lifecycle
# ---------------------------------------------------------------------------
def create_membership(customer_id: str, site_id: str, plan_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_membership(
            f.create_membership_payload(customer_id, site_id, plan_id, **overrides), ADMIN
        )
    )


def create_and_activate_membership(plan_overrides=None, membership_overrides=None,
                                   customer_overrides=None, site_overrides=None):
    """Build clock + plan + customer + site + ACTIVE membership.

    Returns dict with keys: plan, customer, site, membership (the activated row,
    so membership['version'] is the post-activation version).
    """
    set_clock()
    plan = create_plan(**(plan_overrides or {}))
    customer = create_customer(**(customer_overrides or {}))
    site = create_site(customer["id"], **(site_overrides or {}))
    membership = create_membership(customer["id"], site["id"], plan["id"], **(membership_overrides or {}))
    activated = get_success_data(api_client.activate_membership(membership["id"], ADMIN))
    return {"plan": plan, "customer": customer, "site": site, "membership": activated}


def setup_active_membership_with_tech(plan_overrides=None, tech_overrides=None,
                                     membership_overrides=None, site_overrides=None):
    """ACTIVE membership plus a region/trade-matching EPA technician.

    Returns dict: plan, customer, site, membership, technician.
    """
    ctx = create_and_activate_membership(
        plan_overrides=plan_overrides,
        membership_overrides=membership_overrides,
        site_overrides=site_overrides,
    )
    technician = create_technician(**(tech_overrides or {}))
    ctx["technician"] = technician
    return ctx


def setup_active_membership_with_equipment_and_tech(plan_overrides=None, equipment_overrides=None,
                                                   tech_overrides=None, membership_overrides=None):
    """ACTIVE membership + one Equipment at the site + an EPA technician.

    Returns dict: plan, customer, site, membership, equipment, technician.
    """
    ctx = setup_active_membership_with_tech(
        plan_overrides=plan_overrides,
        tech_overrides=tech_overrides,
        membership_overrides=membership_overrides,
    )
    ctx["equipment"] = create_equipment(ctx["site"]["id"], **(equipment_overrides or {}))
    return ctx


# ---------------------------------------------------------------------------
# Tier 3: service-visit lifecycle shortcuts
# ---------------------------------------------------------------------------
def book_visit(membership: dict, **visit_overrides) -> dict:
    """Book one ServiceVisit against an ACTIVE membership (Dispatcher).

    Uses the membership's current version for expected_membership_version.
    """
    payload = f.create_service_visit_payload(membership["id"], membership["version"], **visit_overrides)
    return get_success_data(api_client.create_service_visit(payload, DISPATCHER))


def dispatch_visit(visit_id: str, technician_id: str) -> dict:
    return get_success_data(
        api_client.dispatch_service_visit(visit_id, f.dispatch_payload(technician_id), DISPATCHER)
    )


def drive_visit_to_on_site(visit_id: str, technician_id: str) -> dict:
    """dispatch -> depart -> arrive. Returns the ON_SITE visit."""
    dispatch_visit(visit_id, technician_id)
    tech_headers = make_technician_headers(technician_id)
    get_success_data(api_client.depart_service_visit(visit_id, tech_headers))
    return get_success_data(api_client.arrive_service_visit(visit_id, tech_headers))


def drive_visit_to_completed(visit_id: str, technician_id: str) -> dict:
    """dispatch -> depart -> arrive -> complete. Returns the COMPLETED visit."""
    drive_visit_to_on_site(visit_id, technician_id)
    tech_headers = make_technician_headers(technician_id)
    return get_success_data(api_client.complete_service_visit(visit_id, tech_headers))


def setup_visit_on_site(plan_overrides=None, equipment_overrides=None, tech_overrides=None,
                       visit_overrides=None, with_equipment=True):
    """Full preamble to a single ON_SITE visit with its assigned EPA technician.

    Returns dict: plan, customer, site, membership, technician, visit (ON_SITE),
    and equipment when with_equipment is True.
    """
    if with_equipment:
        ctx = setup_active_membership_with_equipment_and_tech(
            plan_overrides=plan_overrides,
            equipment_overrides=equipment_overrides,
            tech_overrides=tech_overrides,
        )
    else:
        ctx = setup_active_membership_with_tech(
            plan_overrides=plan_overrides,
            tech_overrides=tech_overrides,
        )
    visit = book_visit(ctx["membership"], **(visit_overrides or {}))
    ctx["visit"] = drive_visit_to_on_site(visit["id"], ctx["technician"]["id"])
    return ctx


def complete_n_seasonal_visits(ctx: dict, n: int):
    """Book and complete n SEASONAL visits on the context's membership/tech, on
    distinct windows. Returns the list of completed visit dicts.

    The membership's current term window covers the windows used here, so each
    completion counts toward visits_consumed for the term.
    """
    completed = []
    for i in range(n):
        day = 2 + i  # 2026-07-02, 03, 04, ...
        visit = book_visit(
            ctx["membership"],
            visit_kind="SEASONAL",
            requested_at=f"2026-07-{day:02d}T08:00:00Z",
            window_start=f"2026-07-{day:02d}T09:00:00Z",
            window_end=f"2026-07-{day:02d}T11:00:00Z",
        )
        completed.append(drive_visit_to_completed(visit["id"], ctx["technician"]["id"]))
    return completed


# ---------------------------------------------------------------------------
# Tier 4: renewal lifecycle
# ---------------------------------------------------------------------------
def create_renewal_offer(membership: dict, offered_plan_id: str = None, **overrides) -> dict:
    """Create a PENDING renewal offer; flips the membership ACTIVE -> RENEWAL_PENDING.

    membership['version'] must be the current version. Returns the offer.
    """
    plan_id = offered_plan_id or membership["plan_id"]
    payload = f.create_renewal_offer_payload(plan_id, membership["version"], **overrides)
    return get_success_data(api_client.create_renewal_offer(membership["id"], payload, ADMIN))


def setup_membership_in_renewal_pending(plan_overrides=None, membership_overrides=None,
                                       offer_overrides=None):
    """ACTIVE membership advanced to RENEWAL_PENDING with one PENDING offer.

    Returns dict: plan, customer, site, membership (activated row), offer.
    """
    ctx = create_and_activate_membership(
        plan_overrides=plan_overrides,
        membership_overrides=membership_overrides,
    )
    ctx["offer"] = create_renewal_offer(ctx["membership"], **(offer_overrides or {}))
    return ctx


# ---------------------------------------------------------------------------
# Tier 5: warranty claim lifecycle
# ---------------------------------------------------------------------------
def setup_completed_warranty_visit(plan_overrides=None, equipment_overrides=None,
                                   tech_overrides=None):
    """ACTIVE membership + equipment + a COMPLETED WARRANTY visit at the site.

    Returns dict: plan, customer, site, membership, technician, equipment,
    warranty_visit (COMPLETED).
    """
    ctx = setup_active_membership_with_equipment_and_tech(
        plan_overrides=plan_overrides,
        equipment_overrides=equipment_overrides,
        tech_overrides=tech_overrides,
    )
    visit = book_visit(ctx["membership"], visit_kind="WARRANTY")
    ctx["warranty_visit"] = drive_visit_to_completed(visit["id"], ctx["technician"]["id"])
    return ctx


def file_warranty_claim(equipment_id: str, origin_visit_id: str, claimed_amount_cents: int) -> dict:
    return get_success_data(
        api_client.create_warranty_claim(
            f.create_warranty_claim_payload(equipment_id, origin_visit_id, claimed_amount_cents), ADMIN
        )
    )


def setup_claim_in_state(target: str, claimed_amount_cents: int = 50000,
                        approved_amount_cents: int = 30000, plan_overrides=None,
                        equipment_overrides=None):
    """Build a WarrantyClaim from a COMPLETED WARRANTY visit, walked to `target`.

    target in {SUBMITTED, UNDER_REVIEW, APPROVED, DENIED, SETTLED}. Returns dict:
    plan, customer, site, membership, technician, equipment, warranty_visit, claim.
    """
    ctx = setup_completed_warranty_visit(
        plan_overrides=plan_overrides,
        equipment_overrides=equipment_overrides,
    )
    claim = file_warranty_claim(ctx["equipment"]["id"], ctx["warranty_visit"]["id"], claimed_amount_cents)
    if target == "SUBMITTED":
        ctx["claim"] = claim
        return ctx
    claim = get_success_data(api_client.start_review_warranty_claim(claim["id"], ADMIN))
    if target == "UNDER_REVIEW":
        ctx["claim"] = claim
        return ctx
    if target in ("APPROVED", "SETTLED"):
        claim = get_success_data(
            api_client.approve_warranty_claim(claim["id"], f.approve_claim_payload(approved_amount_cents), ADMIN)
        )
        if target == "APPROVED":
            ctx["claim"] = claim
            return ctx
        claim = get_success_data(api_client.settle_warranty_claim(claim["id"], ADMIN))
        ctx["claim"] = claim
        return ctx
    if target == "DENIED":
        claim = get_success_data(
            api_client.deny_warranty_claim(claim["id"], f.deny_claim_payload(), ADMIN)
        )
        ctx["claim"] = claim
        return ctx
    raise ValueError(f"unknown target claim state {target!r}")


# ---------------------------------------------------------------------------
# Convenience read helpers (use ADMIN, which can read everything)
# ---------------------------------------------------------------------------
def get_customer(customer_id: str) -> dict:
    return get_success_data(api_client.get_customer(customer_id, ADMIN))


def get_membership(membership_id: str) -> dict:
    return get_success_data(api_client.get_membership(membership_id, ADMIN))


def get_equipment(equipment_id: str) -> dict:
    return get_success_data(api_client.get_equipment(equipment_id, ADMIN))


def get_visit(visit_id: str) -> dict:
    return get_success_data(api_client.get_service_visit(visit_id, ADMIN))


def get_offer(offer_id: str) -> dict:
    return get_success_data(api_client.get_renewal_offer(offer_id, ADMIN))


def get_claim(claim_id: str) -> dict:
    return get_success_data(api_client.get_warranty_claim(claim_id, ADMIN))


__all__ = [
    "ADMIN", "DISPATCHER",
    "set_clock", "advance_clock",
    "create_plan", "create_customer", "create_site", "create_equipment", "create_technician",
    "create_membership", "create_and_activate_membership",
    "setup_active_membership_with_tech", "setup_active_membership_with_equipment_and_tech",
    "book_visit", "dispatch_visit", "drive_visit_to_on_site", "drive_visit_to_completed",
    "setup_visit_on_site", "complete_n_seasonal_visits",
    "create_renewal_offer", "setup_membership_in_renewal_pending",
    "setup_completed_warranty_visit", "file_warranty_claim", "setup_claim_in_state",
    "get_customer", "get_membership", "get_equipment", "get_visit", "get_offer", "get_claim",
    "make_technician_headers", "make_customer_headers",
]
