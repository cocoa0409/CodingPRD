"""Composite setup helpers (PRD §3 pipeline ladder).

Each helper builds its preconditions from scratch via PRD-declared endpoints
(every test starts against an empty database). Setup calls use the lenient
get_success_data() validator so failures surface as clear "Setup step failed"
errors rather than confusing assertion output.

Pipeline ladder:
  market (SCREENING) -> evaluated (QUALIFIED) -> stores
  site DRAFT -> SCREENED -> MODELED (model locked) -> SCORED (visit >= 70.00)
    -> FORECAST_LOCKED (forecast locked) -> IN_COMMITTEE (review OPEN)
    -> APPROVED (ratified) -> LOI_ACTIVE (LOI sent) -> LEASE_EXECUTED
    -> BUILD_OUT (BUILD_START completed) -> OPEN (BUILD_COMPLETE completed)
    -> MEASURING (first snapshot finalized) -> UNDERPERFORMING (two misses)
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import REVIEW_DEADLINE
from .factories import (
    create_committee_member_payload,
    create_lease_payload,
    create_loi_payload,
    create_market_payload,
    create_construction_crew_payload,
    create_performance_snapshot_payload,
    create_permit_milestone_payload,
    create_sales_forecast_payload,
    create_site_payload,
    create_site_visit_payload,
    create_store_payload,
    create_submit_committee_payload,
    create_trade_area_model_payload,
    create_competitor_listing_payload,
    create_vote_payload,
)
from .test_users import (
    TEST_USERS,
    make_committee_chair_headers,
    make_committee_member_headers,
)

ADMIN = TEST_USERS["admin_headers"]
ANALYST = TEST_USERS["analyst_headers"]
MANAGER = TEST_USERS["manager_headers"]
CONSTRUCTION = TEST_USERS["construction_headers"]

# Default ANALOG store roster producing a 1,000,000,000-cent STANDARD mean.
DEFAULT_ANALOG_STORES = (
    ("N1", "STANDARD", 1200000000),
    ("N2", "STANDARD", 1000000000),
)


# ---------------------------------------------------------------------------
# Tier 1: single-entity creation and state progression
# ---------------------------------------------------------------------------

def create_market(**overrides):
    """Create a market in SCREENING. Returns the market dict."""
    payload = create_market_payload(**overrides)
    return get_success_data(api_client.create_market(payload, ADMIN))


def create_qualified_market(**overrides):
    """Create a market and run its screening evaluation. Returns the
    evaluated market dict (QUALIFIED for the default qualifying inputs)."""
    market = create_market(**overrides)
    return get_success_data(api_client.evaluate_market(market["id"], ADMIN))


def create_stores(market_id, specs=DEFAULT_ANALOG_STORES):
    """Register OPERATING stores. specs: iterable of (store_code, format_type,
    annual_sales_cents). Returns list of store dicts."""
    stores = []
    for code, format_type, sales in specs:
        payload = create_store_payload(
            market_id=market_id, store_code=code, format_type=format_type,
            annual_sales_cents=sales,
        )
        stores.append(get_success_data(api_client.create_store(payload, ADMIN)))
    return stores


def create_site(market_id, **overrides):
    """Create a candidate site in DRAFT. Returns the site dict."""
    payload = create_site_payload(market_id=market_id, **overrides)
    return get_success_data(api_client.create_site(payload, ANALYST))


def create_screened_site(market_id, **overrides):
    """Create a site and pass the screening gate (DRAFT -> SCREENED)."""
    site = create_site(market_id, **overrides)
    get_success_data(api_client.run_site_screening(site["id"], ANALYST))
    return get_success_data(api_client.get_site(site["id"], ANALYST))


def get_site_version(site_id):
    """Read the site's current OCC version."""
    return get_success_data(api_client.get_site(site_id, ANALYST))["version"]


def create_draft_model(site_id, **overrides):
    """Create a trade-area model in DRAFT for the site."""
    payload = create_trade_area_model_payload(site_id=site_id, **overrides)
    return get_success_data(api_client.create_trade_area_model(payload, ANALYST))


def lock_model(model_id, site_id):
    """Lock a DRAFT model, threading the site's current version (OCC)."""
    site_v = get_site_version(site_id)
    return get_success_data(
        api_client.lock_trade_area_model(
            model_id, {"expected_site_version": site_v}, ANALYST
        )
    )


def add_competitor_listing(model_id, **overrides):
    """Attach a competitor/co-tenant listing to a DRAFT model."""
    payload = create_competitor_listing_payload(
        trade_area_model_id=model_id, **overrides
    )
    return get_success_data(api_client.create_competitor_listing(payload, ANALYST))


def add_site_visit(site_id, **overrides):
    """Record a site visit; computes the weighted total and bubbles the site."""
    payload = create_site_visit_payload(site_id=site_id, **overrides)
    return get_success_data(api_client.create_site_visit(payload, ANALYST))


# ---------------------------------------------------------------------------
# Tier 2: analytical artifact chain (site -> model -> visit -> forecast)
# ---------------------------------------------------------------------------

def create_modeled_site(market_id, site_overrides=None, model_overrides=None,
                        listings=None, store_drive_times=None):
    """Site SCREENED -> MODELED via a LOCKED model. Returns
    {"site": ..., "model": ...}."""
    site = create_screened_site(market_id, **(site_overrides or {}))
    model_kw = dict(model_overrides or {})
    if store_drive_times is not None:
        model_kw["store_drive_times"] = store_drive_times
    model = create_draft_model(site["id"], **model_kw)
    for listing in (listings or []):
        add_competitor_listing(model["id"], **listing)
    model = lock_model(model["id"], site["id"])
    site = get_success_data(api_client.get_site(site["id"], ANALYST))
    return {"site": site, "model": model}


def create_scored_site(market_id, site_overrides=None, model_overrides=None,
                       listings=None, store_drive_times=None,
                       visit_overrides=None):
    """Site through MODELED -> SCORED (passing visit). Returns
    {"site", "model", "visit"}."""
    ctx = create_modeled_site(
        market_id, site_overrides=site_overrides,
        model_overrides=model_overrides, listings=listings,
        store_drive_times=store_drive_times,
    )
    visit = add_site_visit(ctx["site"]["id"], **(visit_overrides or {}))
    ctx["visit"] = visit
    ctx["site"] = get_success_data(api_client.get_site(ctx["site"]["id"], ANALYST))
    return ctx


def create_draft_forecast(site_id, model_id, model_variant="ANALOG"):
    """Create a forecast in DRAFT against the site's LOCKED model."""
    payload = create_sales_forecast_payload(
        site_id=site_id, trade_area_model_id=model_id, model_variant=model_variant,
    )
    return get_success_data(api_client.create_sales_forecast(payload, ANALYST))


def lock_forecast(forecast_id):
    """Committee-lock a DRAFT forecast."""
    return get_success_data(api_client.lock_sales_forecast(forecast_id, ANALYST))


def create_forecast_locked_site(market_id, site_overrides=None,
                                model_overrides=None, listings=None,
                                store_drive_times=None, visit_overrides=None,
                                forecast_variant="ANALOG"):
    """Site through SCORED -> FORECAST_LOCKED. Returns
    {"site", "model", "visit", "forecast"}."""
    ctx = create_scored_site(
        market_id, site_overrides=site_overrides,
        model_overrides=model_overrides, listings=listings,
        store_drive_times=store_drive_times, visit_overrides=visit_overrides,
    )
    forecast = create_draft_forecast(
        ctx["site"]["id"], ctx["model"]["id"], model_variant=forecast_variant,
    )
    forecast = lock_forecast(forecast["id"])
    ctx["forecast"] = forecast
    ctx["site"] = get_success_data(api_client.get_site(ctx["site"]["id"], ANALYST))
    return ctx


# ---------------------------------------------------------------------------
# Tier 3: committee chain (roster -> submit -> ballots -> ratify)
# ---------------------------------------------------------------------------

def create_committee_roster(num_voters=3, sponsor_is_chair=False):
    """Register sponsor + chair + N plain voters. Returns
    {"sponsor": member, "chair": member, "voters": [member, ...]}.

    With sponsor_is_chair=True the sponsor holds the chair (and no separate
    chair is registered); num_voters then counts additional plain voters.
    """
    sponsor = get_success_data(api_client.create_committee_member(
        create_committee_member_payload(
            display_name="Sponsor", is_chair=sponsor_is_chair
        ), ADMIN,
    ))
    if sponsor_is_chair:
        chair = sponsor
    else:
        chair = get_success_data(api_client.create_committee_member(
            create_committee_member_payload(display_name="Chair", is_chair=True),
            ADMIN,
        ))
    voters = []
    for i in range(num_voters):
        voters.append(get_success_data(api_client.create_committee_member(
            create_committee_member_payload(display_name=f"Voter{i + 1}"), ADMIN,
        )))
    return {"sponsor": sponsor, "chair": chair, "voters": voters}


def submit_to_committee(site_id, forecast_id, sponsor_member_id,
                        expires_at=REVIEW_DEADLINE, chair_override=None):
    """Submit a FORECAST_LOCKED site; returns the OPEN CommitteeReview."""
    payload = create_submit_committee_payload(
        sales_forecast_id=forecast_id, sponsor_member_id=sponsor_member_id,
        expires_at=expires_at,
    )
    if chair_override is not None:
        payload["chair_override"] = chair_override
    return get_success_data(
        api_client.submit_site_to_committee(site_id, payload, MANAGER)
    )


def cast_ballot(review_id, member_id, ballot, as_chair=False):
    """Cast one ballot, threading the review's current version (OCC)."""
    current = get_success_data(api_client.get_committee_review(review_id, MANAGER))
    headers = (
        make_committee_chair_headers(member_id)
        if as_chair else make_committee_member_headers(member_id)
    )
    payload = create_vote_payload(
        ballot=ballot, expected_review_version=current["version"],
    )
    return api_client.cast_vote(review_id, payload, headers)


def run_ballot_plan(review_id, plan):
    """Cast a sequence of ballots. plan: iterable of (member_id, ballot,
    as_chair). Returns the list of vote responses (in cast order)."""
    responses = []
    for member_id, ballot, as_chair in plan:
        responses.append(cast_ballot(review_id, member_id, ballot, as_chair))
    return responses


def approve_and_ratify(review_id, chair_id, voter_ids=()):
    """Unanimous-approve plan covering full turnout (every voter plus the
    chair), then chair ratification. Returns the RATIFIED review."""
    for vid in voter_ids:
        cast_ballot(review_id, vid, "APPROVE")
    cast_ballot(review_id, chair_id, "APPROVE", as_chair=True)
    return get_success_data(
        api_client.ratify_review(review_id, make_committee_chair_headers(chair_id))
    )


def create_in_committee_site(market_id=None, stores=DEFAULT_ANALOG_STORES,
                             num_voters=3, site_overrides=None,
                             model_overrides=None, listings=None,
                             store_drive_times=None, visit_overrides=None,
                             forecast_variant="ANALOG",
                             expires_at=REVIEW_DEADLINE, chair_override=None,
                             market_overrides=None, roster=None):
    """Full chain through IN_COMMITTEE with an OPEN review (no votes cast).
    Returns {"market", "site", "model", "visit", "forecast", "roster",
    "review"}.

    Pass an existing `roster` (from create_committee_roster) when several
    sites in one test share the committee: the chair is a chain-wide
    singleton, so a second roster creation would be rejected.
    """
    if market_id is None:
        market = create_qualified_market(**(market_overrides or {}))
        market_id = market["id"]
    else:
        market = get_success_data(api_client.get_market(market_id, ADMIN))
    if stores:
        create_stores(market_id, stores)
    ctx = create_forecast_locked_site(
        market_id, site_overrides=site_overrides,
        model_overrides=model_overrides, listings=listings,
        store_drive_times=store_drive_times, visit_overrides=visit_overrides,
        forecast_variant=forecast_variant,
    )
    if roster is None:
        roster = create_committee_roster(num_voters=num_voters)
    review = submit_to_committee(
        ctx["site"]["id"], ctx["forecast"]["id"], roster["sponsor"]["id"],
        expires_at=expires_at, chair_override=chair_override,
    )
    ctx.update({"market": market, "roster": roster, "review": review})
    ctx["site"] = get_success_data(api_client.get_site(ctx["site"]["id"], MANAGER))
    return ctx


def create_approved_site(market_id=None, stores=DEFAULT_ANALOG_STORES,
                         num_voters=3, site_overrides=None, **kwargs):
    """Full chain through ratified APPROVE; site APPROVED. Returns the
    create_in_committee_site context plus the ratified review."""
    ctx = create_in_committee_site(
        market_id=market_id, stores=stores, num_voters=num_voters,
        site_overrides=site_overrides, **kwargs,
    )
    ctx["review"] = approve_and_ratify(
        ctx["review"]["id"], ctx["roster"]["chair"]["id"],
        [v["id"] for v in ctx["roster"]["voters"]],
    )
    ctx["site"] = get_success_data(api_client.get_site(ctx["site"]["id"], MANAGER))
    return ctx


# ---------------------------------------------------------------------------
# Tier 4: LOI / lease / build-out chain
# ---------------------------------------------------------------------------

def create_draft_loi(site_id, **overrides):
    """Create an LOI in DRAFT for an APPROVED/LOI_ACTIVE site."""
    payload = create_loi_payload(site_id=site_id, **overrides)
    return get_success_data(api_client.create_loi(payload, MANAGER))


def send_loi(loi_id):
    return get_success_data(api_client.send_loi(loi_id, MANAGER))


def accept_loi(loi_id):
    return get_success_data(api_client.accept_loi(loi_id, MANAGER))


def create_sent_loi(site_id, **overrides):
    """Create + send an LOI. First send bubbles the site APPROVED ->
    LOI_ACTIVE."""
    loi = create_draft_loi(site_id, **overrides)
    return send_loi(loi["id"])


def create_accepted_loi(site_id, **overrides):
    """Create + send + accept an LOI (accept from SENT pins rent_psf_cents)."""
    loi = create_sent_loi(site_id, **overrides)
    return accept_loi(loi["id"])


def create_loi_active_site(market_id=None, num_voters=3, loi_overrides=None,
                           **kwargs):
    """Site through APPROVED -> LOI_ACTIVE with a SENT LOI. Returns context
    plus "loi"."""
    ctx = create_approved_site(market_id=market_id, num_voters=num_voters,
                               **kwargs)
    ctx["loi"] = create_sent_loi(ctx["site"]["id"], **(loi_overrides or {}))
    ctx["site"] = get_success_data(api_client.get_site(ctx["site"]["id"], MANAGER))
    return ctx


def create_accepted_loi_site(market_id=None, num_voters=3, loi_overrides=None,
                             **kwargs):
    """Site LOI_ACTIVE with an ACCEPTED LOI. Returns context plus "loi"."""
    ctx = create_approved_site(market_id=market_id, num_voters=num_voters,
                               **kwargs)
    ctx["loi"] = create_accepted_loi(ctx["site"]["id"], **(loi_overrides or {}))
    ctx["site"] = get_success_data(api_client.get_site(ctx["site"]["id"], MANAGER))
    return ctx


def create_crew(crew_code="CREW-1"):
    """Register an ACTIVE construction crew."""
    return get_success_data(api_client.create_construction_crew(
        create_construction_crew_payload(crew_code=crew_code), ADMIN,
    ))


def create_negotiating_lease(loi_id, crew_id, **overrides):
    """Draft a lease in NEGOTIATING from an ACCEPTED LOI."""
    payload = create_lease_payload(loi_id=loi_id, crew_id=crew_id, **overrides)
    return get_success_data(api_client.create_lease(payload, MANAGER))


def create_executed_lease(loi_id, crew_id, **overrides):
    """Draft + execute a lease; bubbles the site LOI_ACTIVE -> LEASE_EXECUTED."""
    lease = create_negotiating_lease(loi_id, crew_id, **overrides)
    return get_success_data(api_client.execute_lease(lease["id"], MANAGER))


def create_lease_executed_site(market_id=None, num_voters=3,
                               crew_code="CREW-1", lease_overrides=None,
                               **kwargs):
    """Site through LEASE_EXECUTED. Returns context plus "loi", "crew",
    "lease"."""
    ctx = create_accepted_loi_site(market_id=market_id, num_voters=num_voters,
                                   **kwargs)
    crew = create_crew(crew_code)
    lease = create_executed_lease(ctx["loi"]["id"], crew["id"],
                                  **(lease_overrides or {}))
    ctx.update({"crew": crew, "lease": lease})
    ctx["site"] = get_success_data(api_client.get_site(ctx["site"]["id"], MANAGER))
    return ctx


MILESTONE_PLAN = (
    ("PERMIT_SUBMITTED", "2026-09-05"),
    ("PERMIT_APPROVED", "2026-09-20"),
    ("BUILD_START", "2026-10-01"),
    ("BUILD_COMPLETE", "2026-10-15"),
)


def plan_milestones(site_id, types=None):
    """Plan milestones (PENDING) for a LEASE_EXECUTED/BUILD_OUT site.
    Returns dict of milestone_type -> milestone."""
    result = {}
    for mtype, planned in MILESTONE_PLAN:
        if types is not None and mtype not in types:
            continue
        result[mtype] = get_success_data(api_client.create_permit_milestone(
            create_permit_milestone_payload(
                site_id=site_id, milestone_type=mtype, planned_date=planned,
            ), CONSTRUCTION,
        ))
    return result


def complete_milestone(milestone_id, actual_date):
    return get_success_data(api_client.complete_permit_milestone(
        milestone_id, {"actual_date": actual_date}, CONSTRUCTION,
    ))


def complete_milestones_in_order(milestones, through="BUILD_START"):
    """Complete milestones in type order up to and including `through`."""
    completed = {}
    for mtype, planned in MILESTONE_PLAN:
        if mtype not in milestones:
            continue
        completed[mtype] = complete_milestone(milestones[mtype]["id"], planned)
        if mtype == through:
            break
    return completed


def create_build_out_site(market_id=None, num_voters=3, crew_code="CREW-1",
                          **kwargs):
    """Site through BUILD_OUT (BUILD_START completed). Returns context plus
    "milestones"."""
    ctx = create_lease_executed_site(
        market_id=market_id, num_voters=num_voters, crew_code=crew_code, **kwargs,
    )
    milestones = plan_milestones(ctx["site"]["id"])
    complete_milestones_in_order(milestones, through="BUILD_START")
    ctx["milestones"] = milestones
    ctx["site"] = get_success_data(api_client.get_site(ctx["site"]["id"], MANAGER))
    return ctx


def create_open_site(market_id=None, num_voters=3, crew_code="CREW-1",
                     **kwargs):
    """Site through OPEN (BUILD_COMPLETE completed + open gate). Returns
    context with "milestones"."""
    ctx = create_build_out_site(
        market_id=market_id, num_voters=num_voters, crew_code=crew_code, **kwargs,
    )
    complete_milestone(
        ctx["milestones"]["BUILD_COMPLETE"]["id"], "2026-10-15",
    )
    get_success_data(api_client.open_site(ctx["site"]["id"], MANAGER))
    ctx["site"] = get_success_data(api_client.get_site(ctx["site"]["id"], MANAGER))
    return ctx


# ---------------------------------------------------------------------------
# Tier 5: performance measurement chain
# ---------------------------------------------------------------------------

def record_snapshot(site_id, period_index, actual_sales_cents):
    payload = create_performance_snapshot_payload(
        site_id=site_id, period_index=period_index,
        actual_sales_cents=actual_sales_cents,
    )
    return get_success_data(api_client.create_performance_snapshot(payload, MANAGER))


def finalize_snapshot(snapshot_id):
    return get_success_data(
        api_client.finalize_performance_snapshot(snapshot_id, MANAGER)
    )


def create_measuring_site(actual_sales_cents=100000000, market_id=None,
                          stores=(("N1", "STANDARD", 1100000000),
                                  ("N2", "STANDARD", 1300000000)),
                          **kwargs):
    """Site through OPEN plus one FINALIZED snapshot (site MEASURING, forecast
    ACTUALIZED). Default stores net 1,200,000,000 via ANALOG, so the expected
    period figure is 100,000,000; default actual equals it (variance 0)."""
    ctx = create_open_site(market_id=market_id, stores=stores, **kwargs)
    snap = record_snapshot(ctx["site"]["id"], 1, actual_sales_cents)
    ctx["snapshot1"] = finalize_snapshot(snap["id"])
    ctx["site"] = get_success_data(api_client.get_site(ctx["site"]["id"], MANAGER))
    return ctx


def create_underperforming_site(miss_sales_cents=80000000, **kwargs):
    """Site through MEASURING into UNDERPERFORMING via two consecutive
    -2000 bp misses (miss threshold inclusive)."""
    ctx = create_measuring_site(actual_sales_cents=miss_sales_cents, **kwargs)
    snap2 = record_snapshot(ctx["site"]["id"], 2, miss_sales_cents)
    ctx["snapshot2"] = finalize_snapshot(snap2["id"])
    ctx["site"] = get_success_data(api_client.get_site(ctx["site"]["id"], MANAGER))
    return ctx
