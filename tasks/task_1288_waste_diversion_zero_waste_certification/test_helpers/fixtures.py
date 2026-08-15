"""Composite setup helpers — multi-step preconditions built from PRD endpoints.

Every fixture creates its own entities from scratch (the runner restarts the
server before every test). Identity threading: VendorUser calls always use
make_vendor_user_headers(vendor["id"]); other roles use the shared opaque
constants from TEST_USERS unless a specific X-User-ID is required (e.g.
submitted_by / segregation-of-duties scenarios).
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import DEFAULT_CLOCK_ISO, DEFAULT_TICKET_DATE
from .factories import (
    create_site_payload, create_vendor_payload, create_contract_payload,
    create_ticket_payload, create_period_payload, create_goal_payload,
    create_audit_payload, create_contamination_event_payload,
    create_application_payload,
)
from .test_users import (
    TEST_USERS, make_vendor_user_headers, make_manager_headers, make_officer_headers,
)

MGR = TEST_USERS["manager_headers"]
STEWARD = TEST_USERS["steward_headers"]
AUDITOR = TEST_USERS["auditor_headers"]
OFFICER = TEST_USERS["officer_headers"]


# ---------------------------------------------------------------- Tier 1: primitives

def set_clock(to_iso8601: str = DEFAULT_CLOCK_ISO):
    """Advance the logical clock (default 2026-08-10)."""
    return get_success_data(api_client.set_clock({"to_iso8601": to_iso8601}, OFFICER))


def create_site(name: str = "Site", **overrides) -> dict:
    payload = create_site_payload(name=name, **overrides)
    return get_success_data(api_client.create_site(payload, MGR))


def create_vendor(name: str = "HaulerCo", **overrides) -> dict:
    payload = create_vendor_payload(name=name, **overrides)
    return get_success_data(api_client.create_vendor(payload, OFFICER))


def create_contract(site_id: str, vendor_id: str, **overrides) -> dict:
    payload = create_contract_payload(site_id, vendor_id, **overrides)
    return get_success_data(api_client.create_contract(payload, MGR))


def create_active_contract(site_id: str, vendor_id: str, **overrides) -> dict:
    contract = create_contract(site_id, vendor_id, **overrides)
    return get_success_data(api_client.activate_contract(contract["id"], MGR))


def create_period(site_id: str, **overrides) -> dict:
    payload = create_period_payload(site_id, **overrides)
    return get_success_data(api_client.create_period(payload, OFFICER))


def create_goal(site_id: str, **overrides) -> dict:
    payload = create_goal_payload(site_id, **overrides)
    return get_success_data(api_client.create_goal(payload, MGR))


def create_ticket(site_id: str, vendor_id: str, contract_id: str, **overrides) -> dict:
    """Create a PENDING ticket as the owning VendorUser."""
    payload = create_ticket_payload(site_id, vendor_id, contract_id, **overrides)
    return get_success_data(
        api_client.create_ticket(payload, make_vendor_user_headers(vendor_id))
    )


def validate_ticket(ticket_id: str) -> dict:
    return get_success_data(api_client.validate_ticket(ticket_id, STEWARD))


def reject_ticket(ticket_id: str, reason: str = "rejected") -> dict:
    return get_success_data(api_client.reject_ticket(ticket_id, {"reason": reason}, STEWARD))


def create_audit(site_id: str, **overrides) -> dict:
    payload = create_audit_payload(site_id, **overrides)
    return get_success_data(api_client.create_audit(payload, AUDITOR))


def create_event(site_id: str, **overrides) -> dict:
    payload = create_contamination_event_payload(site_id, **overrides)
    return get_success_data(api_client.create_contamination_event(payload, AUDITOR))


# ---------------------------------------------------------------- Tier 2: standard scenario

def setup_site_with_active_contract(site_name="Site", clock: str = DEFAULT_CLOCK_ISO,
                                    site_overrides=None, contract_overrides=None):
    """Clock set; site + ACTIVE vendor + ACTIVE contract. Returns (site, vendor, contract)."""
    set_clock(clock)
    site = create_site(site_name, **(site_overrides or {}))
    vendor = create_vendor()
    contract = create_active_contract(site["id"], vendor["id"], **(contract_overrides or {}))
    return site, vendor, contract


def setup_open_period_scenario(site_name="Site", clock: str = DEFAULT_CLOCK_ISO,
                               site_overrides=None, contract_overrides=None,
                               period_overrides=None):
    """Site + vendor + ACTIVE contract + OPEN period (Aug 2026 by default).

    Returns (site, vendor, contract, period).
    """
    site, vendor, contract = setup_site_with_active_contract(
        site_name, clock, site_overrides, contract_overrides
    )
    period = create_period(site["id"], **(period_overrides or {}))
    return site, vendor, contract, period


def create_validated_ticket(site_id, vendor_id, contract_id, **overrides) -> dict:
    """Create a ticket then validate it. Returns the VALIDATED ticket."""
    t = create_ticket(site_id, vendor_id, contract_id, **overrides)
    return validate_ticket(t["id"])


# ---------------------------------------------------------------- Tier 3: certification flow

def setup_closed_period_with_rate(site_name="Site", clock: str = DEFAULT_CLOCK_ISO,
                                  tickets=None, period_overrides=None):
    """Full flow through a CLOSED period with the given ticket mix validated.

    `tickets` is a list of ticket payload overrides (defaults RECYCLING 2000/1000).
    Returns (site, vendor, contract, period).
    """
    site, vendor, contract, period = setup_open_period_scenario(
        site_name, clock, period_overrides=period_overrides
    )
    for i, over in enumerate(tickets if tickets is not None else [{}]):
        over.setdefault("external_ticket_ref", f"CL-T{i+1}")
        t = create_ticket(site["id"], vendor["id"], contract["id"], **over)
        validate_ticket(t["id"])
    closed = get_success_data(api_client.close_period(period["id"], OFFICER))
    return site, vendor, contract, closed


def setup_application_under_review(site_name="Site", level="BRONZE",
                                   submitter_id="mgr-1",
                                   tickets=None, clock: str = DEFAULT_CLOCK_ISO):
    """Closed period + DRAFT application + submit + start_review.

    Returns (site, period, application). The application is UNDER_REVIEW.
    """
    site, vendor, contract, period = setup_closed_period_with_rate(
        site_name, clock, tickets
    )
    # Re-read site for the OCC version.
    site_now = get_success_data(api_client.get_site(site["id"], OFFICER))
    app = get_success_data(api_client.create_application(
        create_application_payload(
            site["id"], period["id"], site_now["version"], level_requested=level,
        ),
        MGR,
    ))
    submitted = get_success_data(
        api_client.submit_application(app["id"], make_manager_headers(submitter_id))
    )
    reviewed = get_success_data(api_client.start_review(submitted["id"], OFFICER))
    return site, period, reviewed
