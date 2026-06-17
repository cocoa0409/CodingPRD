"""Composite setup helpers.

Each test runs against an empty database (the runner restarts the server before every
test). These helpers build the multi-step preconditions that interesting claims require,
using only PRD-declared endpoints. Setup calls use get_success_data() so setup failures
surface as clear "Setup failed" errors.

Identity threading: ListingBroker and TenantBroker are entity-backed roles. After a
broker is created, every ownership-gated call uses make_listing_broker_headers(lb_id)
or make_tenant_broker_headers(tb_id) with the actual Broker.id.
"""
import itertools
from prd_bench_local_runner.testing import get_success_data
from .api_client import api_client
from .test_users import (
    make_admin_headers, make_listing_broker_headers, make_tenant_broker_headers,
)

# Unique license-number generator so repeated fixture calls never collide on uniqueness.
_license_seq = itertools.count(1)


def _next_license(prefix: str) -> str:
    return f"{prefix}-{next(_license_seq):06d}"


# ---------------------------------------------------------------------------
# Tier 1: Firms + brokers
# ---------------------------------------------------------------------------
def create_brokerage(side="DUAL", default_commission_pct=None, name="Brokerage"):
    payload = {"name": name, "side": side}
    if default_commission_pct is not None:
        payload["default_commission_pct"] = default_commission_pct
    return get_success_data(api_client.create_brokerage(payload, make_admin_headers()))


def create_broker(brokerage_id, role, full_name="Broker", license_no=None):
    payload = {
        "brokerage_id": brokerage_id,
        "full_name": full_name,
        "license_no": license_no or _next_license("LIC"),
        "role": role,
    }
    return get_success_data(api_client.create_broker(payload, make_admin_headers()))


def setup_two_firms(default_commission_pct=None):
    """Two distinct brokerages (LISTING + TENANT_REP) with one broker each.
    Returns (listing_broker, tenant_broker) — different brokerages => co-broke deals."""
    bkrg_a = create_brokerage("LISTING", default_commission_pct, "Listing Firm")
    bkrg_b = create_brokerage("TENANT_REP", default_commission_pct, "Tenant Rep Firm")
    lb = create_broker(bkrg_a["id"], "LISTING_BROKER", "Listing Broker", _next_license("L"))
    tb = create_broker(bkrg_b["id"], "TENANT_BROKER", "Tenant Broker", _next_license("T"))
    return lb, tb


def setup_one_firm(side="DUAL", default_commission_pct=None):
    """One brokerage with a listing broker and a tenant broker (same firm => in-house)."""
    bkrg = create_brokerage(side, default_commission_pct, "House Firm")
    lb = create_broker(bkrg["id"], "LISTING_BROKER", "House Listing Broker", _next_license("L"))
    tb = create_broker(bkrg["id"], "TENANT_BROKER", "House Tenant Broker", _next_license("T"))
    return bkrg, lb, tb


# ---------------------------------------------------------------------------
# Tier 1/2: Property + Space + Listing
# ---------------------------------------------------------------------------
def create_property(lb_id, market="SOMA-SF", asset_class="OFFICE", total_sf=50000, name="Property"):
    payload = {
        "listing_broker_id": lb_id, "name": name, "market": market,
        "asset_class": asset_class, "total_sf": total_sf,
    }
    return get_success_data(api_client.create_property(payload, make_listing_broker_headers(lb_id)))


def create_space(lb_id, property_id, suite_no, rentable_sf, asking_rent_psf_yr,
                 free_rent_months=None, ti_allowance_psf=None):
    payload = {
        "property_id": property_id, "suite_no": suite_no,
        "rentable_sf": rentable_sf, "asking_rent_psf_yr": asking_rent_psf_yr,
    }
    if free_rent_months is not None:
        payload["free_rent_months"] = free_rent_months
    if ti_allowance_psf is not None:
        payload["ti_allowance_psf"] = ti_allowance_psf
    return get_success_data(api_client.create_space(payload, make_listing_broker_headers(lb_id)))


def publish_space(lb_id, space_id):
    return get_success_data(api_client.publish_space(space_id, make_listing_broker_headers(lb_id)))


def create_published_space(lb_id, property_id, suite_no="100", rentable_sf=3000,
                           asking_rent_psf_yr=50, free_rent_months=None, ti_allowance_psf=None):
    """Create + publish a space (DRAFT -> AVAILABLE). Returns the AVAILABLE space."""
    create_space(lb_id, property_id, suite_no, rentable_sf, asking_rent_psf_yr,
                 free_rent_months, ti_allowance_psf)
    # publish returns the updated space
    space = None
    spaces = get_success_data(
        api_client.list_spaces(make_listing_broker_headers(lb_id), {"property_id": property_id}))
    # locate the just-created suite
    for s in spaces:
        if s["suite_no"] == suite_no:
            space = s
            break
    return publish_space(lb_id, space["id"])


def create_listing(lb_id, space_id, term_months=60, annual_escalation_pct=None,
                   co_broke_offered_pct=None):
    payload = {"space_id": space_id, "listing_broker_id": lb_id, "term_months": term_months}
    if annual_escalation_pct is not None:
        payload["annual_escalation_pct"] = annual_escalation_pct
    if co_broke_offered_pct is not None:
        payload["co_broke_offered_pct"] = co_broke_offered_pct
    return get_success_data(api_client.create_listing(payload, make_listing_broker_headers(lb_id)))


def activate_listing(lb_id, listing_id):
    return get_success_data(api_client.activate_listing(listing_id, make_listing_broker_headers(lb_id)))


def create_active_listing(lb_id, property_id, suite_no="100", rentable_sf=3000,
                          asking_rent_psf_yr=50, term_months=60, annual_escalation_pct=None,
                          co_broke_offered_pct=None):
    """Create+publish a space, create a listing, activate it. Returns (space, listing)."""
    space = create_published_space(lb_id, property_id, suite_no, rentable_sf, asking_rent_psf_yr)
    listing = create_listing(lb_id, space["id"], term_months, annual_escalation_pct, co_broke_offered_pct)
    listing = activate_listing(lb_id, listing["id"])
    return space, listing


# ---------------------------------------------------------------------------
# Requirement
# ---------------------------------------------------------------------------
def create_requirement(tb_id, market="SOMA-SF", asset_class="OFFICE", min_sf=1000,
                       max_sf=9000, max_rent_psf_yr=70, tenant_name="Tenant"):
    payload = {
        "tenant_broker_id": tb_id, "tenant_name": tenant_name, "market": market,
        "asset_class": asset_class, "min_sf": min_sf, "max_sf": max_sf,
        "max_rent_psf_yr": max_rent_psf_yr,
    }
    return get_success_data(api_client.create_requirement(payload, make_tenant_broker_headers(tb_id)))


# ---------------------------------------------------------------------------
# Tier 2/3: Full negotiation skeletons
# ---------------------------------------------------------------------------
def setup_prospect_deal(co_broke=True, market="SOMA-SF", asset_class="OFFICE",
                        rentable_sf=3000, asking_rent_psf_yr=50, term_months=60,
                        annual_escalation_pct=None, co_broke_offered_pct=None,
                        max_rent_psf_yr=70, default_commission_pct=None, suite_no="100"):
    """Build a PROSPECT Deal (version 1) on an ACTIVE listing + OPEN requirement.

    Returns a context dict with keys:
      lb, tb, property, space, listing, requirement, deal
    The deal is opened by the listing broker; deal['version'] is its current OCC version.
    co_broke=True => listing firm != tenant firm (Deal.is_co_broke true).
    co_broke=False => same firm on both sides (in-house).
    """
    if co_broke:
        lb, tb = setup_two_firms(default_commission_pct)
    else:
        _, lb, tb = setup_one_firm("DUAL", default_commission_pct)
    prop = create_property(lb["id"], market, asset_class)
    space, listing = create_active_listing(
        lb["id"], prop["id"], suite_no, rentable_sf, asking_rent_psf_yr,
        term_months, annual_escalation_pct, co_broke_offered_pct)
    req = create_requirement(tb["id"], market, asset_class, 1000, 9000, max_rent_psf_yr)
    deal = get_success_data(api_client.create_deal(
        {"listing_id": listing["id"], "requirement_id": req["id"]},
        make_listing_broker_headers(lb["id"])))
    return {"lb": lb, "tb": tb, "property": prop, "space": space,
            "listing": listing, "requirement": req, "deal": deal}


def _refresh_deal_version(ctx):
    deal = get_success_data(api_client.get_deal(ctx["deal"]["id"], make_listing_broker_headers(ctx["lb"]["id"])))
    return deal["version"]


def submit_first_proposal(ctx, from_side="LISTING", base_rent_psf_yr=50, term_months=60,
                          free_rent_months=None, ti_allowance_psf=None, annual_escalation_pct=None):
    """Author the first proposal on the PROSPECT deal (-> LOI_DRAFT). Returns the proposal."""
    deal = ctx["deal"]
    payload = {
        "from_side": from_side, "base_rent_psf_yr": base_rent_psf_yr,
        "term_months": term_months, "expected_deal_version": deal["version"],
    }
    if free_rent_months is not None:
        payload["free_rent_months"] = free_rent_months
    if ti_allowance_psf is not None:
        payload["ti_allowance_psf"] = ti_allowance_psf
    if annual_escalation_pct is not None:
        payload["annual_escalation_pct"] = annual_escalation_pct
    headers = (make_listing_broker_headers(ctx["lb"]["id"]) if from_side == "LISTING"
               else make_tenant_broker_headers(ctx["tb"]["id"]))
    prop = get_success_data(api_client.create_proposal(deal["id"], payload, headers))
    ctx["deal"]["version"] = _refresh_deal_version(ctx)
    return prop


def accept_deal(ctx, accepting_side="TENANT"):
    """Accept the latest PENDING proposal (-> LOI_ACCEPTED). accepting_side is the side
    that did NOT author the latest pending proposal. Returns the updated deal."""
    deal_id = ctx["deal"]["id"]
    version = _refresh_deal_version(ctx)
    headers = (make_tenant_broker_headers(ctx["tb"]["id"]) if accepting_side == "TENANT"
               else make_listing_broker_headers(ctx["lb"]["id"]))
    deal = get_success_data(api_client.accept_deal(
        deal_id, {"from_side": accepting_side, "expected_deal_version": version}, headers))
    ctx["deal"]["version"] = deal["version"]
    return deal


def lease_out_deal(ctx):
    """Send the lease out (LOI_ACCEPTED -> LEASE_OUT). Listing broker only."""
    deal_id = ctx["deal"]["id"]
    version = _refresh_deal_version(ctx)
    deal = get_success_data(api_client.lease_out_deal(
        deal_id, {"expected_deal_version": version}, make_listing_broker_headers(ctx["lb"]["id"])))
    ctx["deal"]["version"] = deal["version"]
    return deal


def execute_deal(ctx):
    """Execute the lease (LEASE_OUT -> EXECUTED). Listing broker only. Returns updated deal."""
    deal_id = ctx["deal"]["id"]
    version = _refresh_deal_version(ctx)
    deal = get_success_data(api_client.execute_deal(
        deal_id, {"expected_deal_version": version}, make_listing_broker_headers(ctx["lb"]["id"])))
    ctx["deal"]["version"] = deal["version"]
    return deal


def setup_accepted_deal(co_broke=True, base_rent_psf_yr=50, term_months=60,
                        annual_escalation_pct=0, free_rent_months=None, ti_allowance_psf=None,
                        rentable_sf=3000, asking_rent_psf_yr=50, max_rent_psf_yr=70,
                        co_broke_offered_pct=None, default_commission_pct=None, market="SOMA-SF",
                        asset_class="OFFICE", suite_no="100"):
    """PROSPECT -> first LISTING proposal -> TENANT accept. Deal is LOI_ACCEPTED, space UNDER_LOI.
    The proposal/listing escalation are aligned so consideration is deterministic.
    Returns the context dict (with deal at LOI_ACCEPTED)."""
    ctx = setup_prospect_deal(
        co_broke=co_broke, market=market, asset_class=asset_class, rentable_sf=rentable_sf,
        asking_rent_psf_yr=asking_rent_psf_yr, term_months=term_months,
        annual_escalation_pct=annual_escalation_pct, co_broke_offered_pct=co_broke_offered_pct,
        max_rent_psf_yr=max_rent_psf_yr, default_commission_pct=default_commission_pct,
        suite_no=suite_no)
    submit_first_proposal(ctx, "LISTING", base_rent_psf_yr, term_months,
                          free_rent_months, ti_allowance_psf, annual_escalation_pct)
    accept_deal(ctx, "TENANT")
    return ctx


def setup_executed_deal(co_broke=True, base_rent_psf_yr=50, term_months=60,
                        annual_escalation_pct=0, free_rent_months=None, ti_allowance_psf=None,
                        rentable_sf=3000, asking_rent_psf_yr=50, max_rent_psf_yr=70,
                        co_broke_offered_pct=None, default_commission_pct=None, market="SOMA-SF",
                        asset_class="OFFICE", suite_no="100"):
    """Full lifecycle through EXECUTED: accept -> lease-out -> execute.
    Returns the context dict (with deal at EXECUTED, commission splits + comp written)."""
    ctx = setup_accepted_deal(
        co_broke=co_broke, base_rent_psf_yr=base_rent_psf_yr, term_months=term_months,
        annual_escalation_pct=annual_escalation_pct, free_rent_months=free_rent_months,
        ti_allowance_psf=ti_allowance_psf, rentable_sf=rentable_sf,
        asking_rent_psf_yr=asking_rent_psf_yr, max_rent_psf_yr=max_rent_psf_yr,
        co_broke_offered_pct=co_broke_offered_pct, default_commission_pct=default_commission_pct,
        market=market, asset_class=asset_class, suite_no=suite_no)
    lease_out_deal(ctx)
    execute_deal(ctx)
    return ctx


def get_commission_splits_for_deal(ctx, deal_id=None):
    """Return the list of CommissionSplit rows for a deal."""
    deal_id = deal_id or ctx["deal"]["id"]
    return get_success_data(api_client.list_commission_splits(
        make_listing_broker_headers(ctx["lb"]["id"]), {"deal_id": deal_id}))


def split_by_side(splits, side):
    """Locate the single CommissionSplit with the given side."""
    matching = [s for s in splits if s["side"] == side]
    assert len(matching) == 1, f"expected exactly one {side} split, got {len(matching)}"
    return matching[0]


# ---------------------------------------------------------------------------
# Tier 1/4: Tours
# ---------------------------------------------------------------------------
def create_tour(tb_id, requirement_id, space_id, window_start, window_end):
    payload = {
        "requirement_id": requirement_id, "tenant_broker_id": tb_id, "space_id": space_id,
        "window_start": window_start, "window_end": window_end,
    }
    return get_success_data(api_client.create_tour(payload, make_tenant_broker_headers(tb_id)))


def confirm_tour(lb_id, tour_id, hold=False):
    return get_success_data(api_client.confirm_tour(
        tour_id, make_listing_broker_headers(lb_id), {"hold": hold}))


def setup_published_space_and_requirement(market="SOMA-SF", asset_class="OFFICE",
                                          rentable_sf=2500, asking_rent_psf_yr=45,
                                          max_rent_psf_yr=60):
    """Two firms, one published (AVAILABLE) space, one OPEN requirement, no listing/deal.
    Returns dict: lb, tb, property, space, requirement."""
    lb, tb = setup_two_firms()
    prop = create_property(lb["id"], market, asset_class)
    space = create_published_space(lb["id"], prop["id"], "T1", rentable_sf, asking_rent_psf_yr)
    req = create_requirement(tb["id"], market, asset_class, 1000, 5000, max_rent_psf_yr)
    return {"lb": lb, "tb": tb, "property": prop, "space": space, "requirement": req}


def setup_confirmed_tour_holding_space(window_start="2026-07-01T10:00:00Z",
                                       window_end="2026-07-01T11:00:00Z"):
    """A CONFIRMED tour holding its space (Space ON_HOLD, Requirement TOURING).
    Returns dict: lb, tb, property, space, requirement, tour."""
    base = setup_published_space_and_requirement(market="ARTS-LA", asset_class="FLEX")
    tour = create_tour(base["tb"]["id"], base["requirement"]["id"], base["space"]["id"],
                       window_start, window_end)
    confirm_tour(base["lb"]["id"], tour["id"], hold=True)
    base["tour"] = tour
    return base
