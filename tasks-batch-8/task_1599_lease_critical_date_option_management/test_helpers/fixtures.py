"""Composite setup helpers.

Every test starts against an empty database (the harness restarts the server
before each test), so these helpers build complete precondition chains out of
PRD-declared endpoints only.

Identity threading: AssetManager, Broker, and LandlordCounsel calls are
entity-backed by Contact. Every workspace dict carries per-instance headers
built from the real Contact ids via the make_* builders; ownership-gated
calls never fall back to the shared constants.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    create_amendment_payload,
    create_comparable_assessment_payload,
    create_contact_payload,
    create_dispute_payload,
    create_lease_payload,
    create_notice_payload,
    create_option_payload,
    create_portfolio_payload,
    propose_amendment_payload,
    withdraw_option_payload,
)
from .test_users import (
    TEST_USERS,
    make_am_headers,
    make_bk_headers,
    make_lc_headers,
)

ADMIN = TEST_USERS["admin_headers"]


# ---------------------------------------------------------------------------
# Tier 1: single-resource creation
# ---------------------------------------------------------------------------

def create_portfolio(name="P", region="WEST", laddering_max_pct_per_year=40):
    """Create a portfolio. Returns the portfolio."""
    payload = create_portfolio_payload(
        name=name, region=region,
        laddering_max_pct_per_year=laddering_max_pct_per_year)
    return get_success_data(api_client.create_portfolio(payload, ADMIN))


def add_contact(portfolio_id, full_name, email, contact_kind):
    """Register a contact under the portfolio. Returns the contact."""
    payload = create_contact_payload(
        full_name=full_name, email=email, contact_kind=contact_kind)
    return get_success_data(api_client.create_contact(portfolio_id, payload, ADMIN))


def create_lease(portfolio_id, am_headers, premises_label="HQ-1",
                 rentable_square_feet=5000, base_rent_cents_per_rsf_year=4000,
                 commencement_date="2026-01-01T00:00:00Z",
                 expiration_date="2027-12-31T00:00:00Z",
                 holdover_tier1_pct=150, holdover_tier2_pct=200,
                 holdover_tier1_days=None):
    """Create a lease in DRAFT. Returns the lease."""
    payload = create_lease_payload(
        premises_label=premises_label,
        rentable_square_feet=rentable_square_feet,
        base_rent_cents_per_rsf_year=base_rent_cents_per_rsf_year,
        commencement_date=commencement_date,
        expiration_date=expiration_date,
        holdover_tier1_pct=holdover_tier1_pct,
        holdover_tier2_pct=holdover_tier2_pct,
    )
    if holdover_tier1_days is not None:
        payload["holdover_tier1_days"] = holdover_tier1_days
    return get_success_data(api_client.create_lease(portfolio_id, payload, am_headers))


def activate_lease(portfolio_id, lease_id, am_headers, enforce_ladder=None):
    """Activate a DRAFT lease. Returns the activated lease."""
    payload = {}
    if enforce_ladder is not None:
        payload["enforce_ladder"] = enforce_ladder
    return get_success_data(
        api_client.activate_lease(portfolio_id, lease_id, payload, am_headers))


def create_and_activate_lease(portfolio_id, am_headers, **kwargs):
    """Create a lease then activate it. Returns the activated lease."""
    lease = create_lease(portfolio_id, am_headers, **kwargs)
    return activate_lease(portfolio_id, lease["id"], am_headers)


def create_option(portfolio_id, lease_id, am_headers, **overrides):
    """Register an option on a lease. Returns the option."""
    payload = create_option_payload(**overrides)
    return get_success_data(
        api_client.create_option(portfolio_id, lease_id, payload, am_headers))


def set_clock(to_iso8601):
    """Advance the logical clock. Returns the ClockEvent."""
    return get_success_data(api_client.set_clock(to_iso8601, ADMIN))


# ---------------------------------------------------------------------------
# Tier 2: portfolio + contacts workspace
# ---------------------------------------------------------------------------

def setup_portfolio_with_contacts(name="P", region="WEST",
                                  laddering_max_pct_per_year=40,
                                  with_am=True, with_bk=False, with_lc=False):
    """Portfolio + the requested contacts. Returns a workspace dict with
    portfolio, am, bk, lc contacts and their per-instance headers."""
    portfolio = create_portfolio(name=name, region=region,
                                 laddering_max_pct_per_year=laddering_max_pct_per_year)
    pid = portfolio["id"]
    ws = {
        "portfolio": portfolio,
        "pid": pid,
        "am": None, "bk": None, "lc": None,
        "am_headers": None, "bk_headers": None, "lc_headers": None,
        "admin_headers": ADMIN,
    }
    if with_am:
        am = add_contact(pid, "Asset Manager", f"am-{name.lower()}@x.com", "ASSET_MANAGER")
        ws["am"] = am
        ws["am_headers"] = make_am_headers(am["id"])
    if with_bk:
        bk = add_contact(pid, "Broker", f"bk-{name.lower()}@x.com", "BROKER")
        ws["bk"] = bk
        ws["bk_headers"] = make_bk_headers(bk["id"])
    if with_lc:
        lc = add_contact(pid, "Landlord Counsel", f"lc-{name.lower()}@x.com",
                         "LANDLORD_COUNSEL")
        ws["lc"] = lc
        ws["lc_headers"] = make_lc_headers(lc["id"])
    return ws


# ---------------------------------------------------------------------------
# Tier 3: full lease lifecycle shortcuts
# ---------------------------------------------------------------------------

def setup_active_lease(name="P", region="WEST", laddering_max_pct_per_year=40,
                       with_bk=False, with_lc=False, **lease_kwargs):
    """Portfolio + AM contact (+ optional BK/LC) + ACTIVE lease.
    Returns workspace dict with lease added."""
    ws = setup_portfolio_with_contacts(
        name=name, region=region,
        laddering_max_pct_per_year=laddering_max_pct_per_year,
        with_am=True, with_bk=with_bk, with_lc=with_lc)
    lease = create_and_activate_lease(ws["pid"], ws["am_headers"], **lease_kwargs)
    ws["lease"] = lease
    ws["lid"] = lease["id"]
    return ws


def setup_option_on_active_lease(name="P", region="WEST",
                                 laddering_max_pct_per_year=40,
                                 with_bk=False, with_lc=False,
                                 option_overrides=None, **lease_kwargs):
    """Workspace with ACTIVE lease + one option in AVAILABLE.
    Returns workspace dict with lease and option."""
    ws = setup_active_lease(
        name=name, region=region,
        laddering_max_pct_per_year=laddering_max_pct_per_year,
        with_bk=with_bk, with_lc=with_lc, **lease_kwargs)
    option = create_option(ws["pid"], ws["lid"], ws["am_headers"],
                           **(option_overrides or {}))
    ws["option"] = option
    ws["oid"] = option["id"]
    return ws


def create_notice_for_option(ws, delivery_method="COURIER", expected_lease_version=None):
    """Create an exercise notice for the workspace's option.
    Reads the current lease version if not supplied."""
    if expected_lease_version is None:
        lease = get_success_data(
            api_client.get_lease(ws["pid"], ws["lid"], ws["am_headers"]))
        expected_lease_version = lease["version"]
    payload = create_notice_payload(
        expected_lease_version, delivery_method=delivery_method)
    return get_success_data(api_client.create_notice(
        ws["pid"], ws["lid"], ws["oid"], payload, ws["am_headers"]))


def setup_notice_sent(name="P", region="WEST", with_bk=True, with_lc=False,
                      option_overrides=None, clock="2026-09-01T00:00:00Z",
                      delivery_method="COURIER", **lease_kwargs):
    """Workspace with ACTIVE lease + option + a SENT exercise notice.
    Returns workspace with notice added."""
    ws = setup_option_on_active_lease(
        name=name, region=region, with_bk=with_bk, with_lc=with_lc,
        option_overrides=option_overrides, **lease_kwargs)
    set_clock(clock)
    notice = create_notice_for_option(ws, delivery_method=delivery_method)
    ws["notice"] = notice
    ws["nid"] = notice["id"]
    return ws


def setup_notice_delivered(name="P", region="WEST", with_lc=True,
                           option_overrides=None, clock="2026-09-01T00:00:00Z",
                           delivery_method="COURIER", **lease_kwargs):
    """Workspace with ACTIVE lease + option + notice SENT then DELIVERED."""
    ws = setup_notice_sent(
        name=name, region=region, with_bk=True, with_lc=with_lc,
        option_overrides=option_overrides, clock=clock,
        delivery_method=delivery_method, **lease_kwargs)
    get_success_data(api_client.deliver_notice(
        ws["pid"], ws["lid"], ws["oid"], ws["nid"], ws["bk_headers"]))
    return ws


def setup_option_exercised(name="P", region="WEST",
                           option_overrides=None, clock="2026-09-01T00:00:00Z",
                           **lease_kwargs):
    """Workspace with option fully exercised (notice SENT, DELIVERED, ACKNOWLEDGED).
    Returns workspace with exercised option."""
    ws = setup_notice_delivered(
        name=name, region=region, with_lc=True,
        option_overrides=option_overrides, clock=clock, **lease_kwargs)
    get_success_data(api_client.acknowledge_notice(
        ws["pid"], ws["lid"], ws["oid"], ws["nid"], ws["lc_headers"]))
    # refresh option and lease snapshots
    ws["option"] = get_success_data(api_client.get_option(
        ws["pid"], ws["lid"], ws["oid"], ADMIN))
    ws["lease"] = get_success_data(api_client.get_lease(ws["pid"], ws["lid"], ADMIN))
    return ws


# ---------------------------------------------------------------------------
# Tier 4: amendment lifecycle
# ---------------------------------------------------------------------------

def create_amendment(ws, kind="RENEWAL_TERM",
                     new_expiration_date="2032-12-31T00:00:00Z",
                     new_base_rent_cents_per_rsf_year=5500,
                     supersedes_amendment_id=None):
    """Create an amendment in DRAFT. Returns the amendment."""
    payload = create_amendment_payload(
        kind=kind,
        new_expiration_date=new_expiration_date,
        new_base_rent_cents_per_rsf_year=new_base_rent_cents_per_rsf_year,
    )
    if supersedes_amendment_id is not None:
        payload["supersedes_amendment_id"] = supersedes_amendment_id
    return get_success_data(api_client.create_amendment(
        ws["pid"], ws["lid"], payload, ws["am_headers"]))


def propose_amendment(ws, amendment_id):
    """Propose a DRAFT amendment. Returns the amendment (PROPOSED)."""
    lease = get_success_data(
        api_client.get_lease(ws["pid"], ws["lid"], ws["am_headers"]))
    payload = propose_amendment_payload(lease["version"])
    return get_success_data(api_client.propose_amendment(
        ws["pid"], ws["lid"], amendment_id, payload, ws["am_headers"]))


def agree_amendment(ws, amendment_id, lc_headers=None):
    """LandlordCounsel agrees to a PROPOSED/COUNTERED amendment."""
    headers = lc_headers or ws["lc_headers"]
    return get_success_data(api_client.agree_amendment(
        ws["pid"], ws["lid"], amendment_id, headers))


def execute_amendment(ws, amendment_id, am_headers=None, enforce_ladder=None):
    """AssetManager executes an AGREED amendment."""
    headers = am_headers or ws["am_headers"]
    lease = get_success_data(
        api_client.get_lease(ws["pid"], ws["lid"], ws["am_headers"]))
    payload = {"expected_lease_version": lease["version"]}
    if enforce_ladder is not None:
        payload["enforce_ladder"] = enforce_ladder
    return get_success_data(api_client.execute_amendment(
        ws["pid"], ws["lid"], amendment_id, payload, headers))


# ---------------------------------------------------------------------------
# Tier 5: holdover and settlement helpers
# ---------------------------------------------------------------------------

def setup_lease_in_holdover(name="P", region="WEST",
                            rentable_square_feet=10000,
                            base_rent_cents_per_rsf_year=5000,
                            holdover_tier1_pct=150, holdover_tier2_pct=200,
                            holdover_tier1_days=None,
                            commencement_date="2026-01-01T00:00:00Z",
                            expiration_date="2026-12-31T00:00:00Z",
                            holdover_advance_to="2027-01-01T00:00:00Z"):
    """Workspace with lease in HOLDOVER state.
    The lease expires at expiration_date; the clock is advanced past it so the
    sweep moves the lease to HOLDOVER."""
    ws = setup_active_lease(
        name=name, region=region, with_bk=False, with_lc=True,
        rentable_square_feet=rentable_square_feet,
        base_rent_cents_per_rsf_year=base_rent_cents_per_rsf_year,
        commencement_date=commencement_date,
        expiration_date=expiration_date,
        holdover_tier1_pct=holdover_tier1_pct,
        holdover_tier2_pct=holdover_tier2_pct,
        holdover_tier1_days=holdover_tier1_days,
    )
    set_clock(holdover_advance_to)
    ws["lease"] = get_success_data(api_client.get_lease(ws["pid"], ws["lid"], ADMIN))
    return ws
