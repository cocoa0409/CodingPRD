"""Composite setup helpers.

Every helper builds its preconditions from scratch using only PRD-declared
endpoints, because the server database is empty at the start of each test.
Setup calls use get_success_data() (lenient) so setup failures surface clearly.

Identity threading: Host and Platform are entity-backed roles. Any ownership-gated
call uses make_host_headers(host["id"]) / make_platform_headers(platform["id"]),
never a shared-constant fallback.
"""
import itertools
from prd_bench_local_runner.testing import get_success_data
from .api_client import api_client
from .test_users import (
    TEST_USERS, make_host_headers, make_platform_headers,
)
from .factories import (
    create_zone_payload, create_host_payload, create_property_payload,
    attest_primary_residence_payload, create_permit_payload,
    create_complaint_payload, create_tax_filing_payload, remit_payload,
    renew_payload, create_lottery_round_payload, draw_payload,
    create_platform_payload, create_listing_report_payload,
)

REGISTRAR = TEST_USERS["registrar_headers"]
TAX_OFFICER = TEST_USERS["tax_officer_headers"]

# Unique-value generators — each entity has uniqueness constraints on
# zone_code / email / street_address, so tests must not collide even though
# every test starts from an empty DB (defense against accidental reuse).
_counter = itertools.count(1)


def _uid() -> int:
    return next(_counter)


# ---------------------------------------------------------------------------
# Tier 1/2: base entity builders
# ---------------------------------------------------------------------------

def create_zone(**overrides) -> dict:
    n = _uid()
    payload = create_zone_payload(zone_code=overrides.pop("zone_code", f"Z{n}"), **overrides)
    return get_success_data(api_client.create_zone(payload, REGISTRAR))


def create_host(**overrides) -> dict:
    n = _uid()
    payload = create_host_payload(
        email=overrides.pop("email", f"host{n}@example.com"),
        full_name=overrides.pop("full_name", f"Host {n}"),
    )
    return get_success_data(api_client.create_host(payload, REGISTRAR))


def create_property(host_id, zone_id, **overrides) -> dict:
    n = _uid()
    payload = create_property_payload(
        host_id, zone_id,
        street_address=overrides.pop("street_address", f"{n} Elm St"),
        **overrides,
    )
    return get_success_data(api_client.create_property(payload, REGISTRAR))


def attest_primary(host_id, property_id) -> dict:
    return get_success_data(
        api_client.attest_primary_residence(
            host_id, attest_primary_residence_payload(property_id),
            make_host_headers(host_id),
        )
    )


def create_platform(**overrides) -> dict:
    n = _uid()
    payload = create_platform_payload(platform_name=overrides.pop("platform_name", f"Platform {n}"))
    return get_success_data(api_client.create_platform(payload, REGISTRAR))


# ---------------------------------------------------------------------------
# Tier 2/3: zone+host+property base setup, primary-residence variant
# ---------------------------------------------------------------------------

def setup_zone_host_property(zone_overrides=None, prop_overrides=None, attest=True):
    """Create a zone, a host, and a property linked to both.

    If attest=True the property is set as the host's primary residence (needed
    for PRIMARY_RESIDENCE permits). Returns (zone, host, property).
    """
    zone = create_zone(**(zone_overrides or {}))
    host = create_host()
    prop = create_property(host["id"], zone["id"], **(prop_overrides or {}))
    if attest:
        attest_primary(host["id"], prop["id"])
    return zone, host, prop


def create_draft_permit(property_id, **permit_overrides) -> dict:
    """Create a DRAFT permit application on the given property."""
    payload = create_permit_payload(property_id, **permit_overrides)
    return get_success_data(api_client.create_permit(payload, REGISTRAR))


def setup_draft_permit(zone_overrides=None, prop_overrides=None,
                       permit_overrides=None, attest=True):
    """Zone + host + (attested) property + DRAFT permit.

    Returns (zone, host, property, permit).
    """
    zone, host, prop = setup_zone_host_property(zone_overrides, prop_overrides, attest)
    permit = create_draft_permit(prop["id"], **(permit_overrides or {}))
    return zone, host, prop, permit


def setup_issued_permit(zone_overrides=None, prop_overrides=None,
                        permit_overrides=None, attest=True):
    """Zone + host + (attested) property + ISSUED permit.

    Returns (zone, host, property, permit) where permit is freshly issued.
    """
    zone, host, prop, permit = setup_draft_permit(
        zone_overrides, prop_overrides, permit_overrides, attest
    )
    issued = get_success_data(api_client.issue_permit(permit["id"], REGISTRAR))
    return zone, host, prop, issued


def setup_active_permit(zone_overrides=None, prop_overrides=None,
                        permit_overrides=None, attest=True):
    """Zone + host + (attested) property + ACTIVE permit (issued then activated).

    Returns (zone, host, property, permit).
    """
    zone, host, prop, issued = setup_issued_permit(
        zone_overrides, prop_overrides, permit_overrides, attest
    )
    active = get_success_data(
        api_client.activate_permit(issued["id"], make_host_headers(host["id"]))
    )
    return zone, host, prop, active


# ---------------------------------------------------------------------------
# Complaints / enforcement ladder
# ---------------------------------------------------------------------------

def file_and_uphold_complaint(permit_id, category) -> dict:
    """File a complaint of the given category and uphold it. Returns the upheld
    complaint object."""
    complaint = get_success_data(
        api_client.create_complaint(create_complaint_payload(permit_id, category), REGISTRAR)
    )
    return get_success_data(api_client.uphold_complaint(complaint["id"], REGISTRAR))


def file_open_complaint(permit_id, category) -> dict:
    return get_success_data(
        api_client.create_complaint(create_complaint_payload(permit_id, category), REGISTRAR)
    )


def setup_suspended_permit():
    """ACTIVE permit pushed to SUSPENDED by one UPHELD OVER_OCCUPANCY (2 pts).

    Returns (zone, host, property, permit) with permit SUSPENDED.
    """
    zone, host, prop, active = setup_active_permit()
    file_and_uphold_complaint(active["id"], "OVER_OCCUPANCY")
    permit = get_success_data(api_client.get_permit(active["id"], REGISTRAR))
    return zone, host, prop, permit


# ---------------------------------------------------------------------------
# Tax filings
# ---------------------------------------------------------------------------

def create_draft_filing(permit_id, **filing_overrides) -> dict:
    payload = create_tax_filing_payload(permit_id, **filing_overrides)
    return get_success_data(api_client.create_tax_filing(payload, TAX_OFFICER))


def setup_filed_filing(filing_overrides=None):
    """Zone + host + property + ISSUED permit + a FILED tax filing.

    Returns (zone, host, property, permit, filing) with filing FILED.

    The reported period defaults to May 2026 so that due_at (last day of the
    period + 30 days = 2026-06-30) lands strictly after the startup clock
    (2026-05-01); otherwise the very next touch of the filing would trip the
    §2.5 lazy DELINQUENT auto-transition and the filing would not remain FILED.
    Callers that want a past-due period supply period_year/period_month.
    """
    overrides = {"period_year": 2026, "period_month": 5}
    overrides.update(filing_overrides or {})
    zone, host, prop, permit = setup_issued_permit()
    draft = create_draft_filing(permit["id"], **overrides)
    filed = get_success_data(api_client.file_tax_filing(draft["id"], TAX_OFFICER))
    return zone, host, prop, permit, filed


def setup_delinquent_filing(clock_to, filing_overrides=None):
    """FILED filing driven to DELINQUENT by advancing the clock past due_at and
    reading it. Returns (zone, host, property, permit, filing) with filing
    DELINQUENT (penalty frozen).

    Uses a March 2026 period (due_at = 2026-04-30) so the filing is already past
    due once the clock is advanced to the supplied instant; the clock_to values
    chosen by callers pin days_late relative to that due_at.
    """
    overrides = {"period_year": 2026, "period_month": 3}
    overrides.update(filing_overrides or {})
    zone, host, prop, permit = setup_issued_permit()
    draft = create_draft_filing(permit["id"], **overrides)
    filed = get_success_data(api_client.file_tax_filing(draft["id"], TAX_OFFICER))
    get_success_data(api_client.set_clock(clock_to, TAX_OFFICER))
    filing = get_success_data(api_client.get_tax_filing(filed["id"], TAX_OFFICER))
    return zone, host, prop, permit, filing


# ---------------------------------------------------------------------------
# Renewal window helpers
# ---------------------------------------------------------------------------

def setup_active_permit_in_renewal_window(clock_to="2027-04-15T00:00:00Z"):
    """ACTIVE permit whose clock has been advanced into its renewal window.

    A permit issued at the default clock (2026-05-01) expires 2027-05-01, so the
    renewal window opens 2027-04-01. Returns (zone, host, property, permit, version)
    where version is the current permit version read after the clock advance.
    """
    zone, host, prop, active = setup_active_permit()
    get_success_data(api_client.set_clock(clock_to, REGISTRAR))
    permit = get_success_data(api_client.get_permit(active["id"], make_host_headers(host["id"])))
    return zone, host, prop, permit, permit["version"]


# ---------------------------------------------------------------------------
# Lottery helpers
# ---------------------------------------------------------------------------

def setup_lottery_pending_permit():
    """Zone with permit_cap 1 + lottery_enabled, one ISSUED permit filling the
    seat, and a second permit routed to LOTTERY_PENDING. Also opens a lottery
    round. Returns (zone, host_a, permit_a, host_b, permit_b, round, round_version).
    """
    zone = create_zone(permit_cap=1, lottery_enabled=True)
    host_a = create_host()
    host_b = create_host()
    prop_a = create_property(host_a["id"], zone["id"])
    prop_b = create_property(host_b["id"], zone["id"])
    attest_primary(host_a["id"], prop_a["id"])
    attest_primary(host_b["id"], prop_b["id"])
    permit_a = create_draft_permit(prop_a["id"])
    permit_a = get_success_data(api_client.issue_permit(permit_a["id"], REGISTRAR))
    permit_b = create_draft_permit(prop_b["id"])
    permit_b = get_success_data(api_client.issue_permit(permit_b["id"], REGISTRAR))
    rnd = get_success_data(
        api_client.create_lottery_round(create_lottery_round_payload(zone["id"], 1), REGISTRAR)
    )
    return zone, host_a, permit_a, host_b, permit_b, rnd, rnd["version"]
