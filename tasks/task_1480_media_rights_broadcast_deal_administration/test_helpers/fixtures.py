"""
Composite setup helpers for multi-step test prerequisites.

Every fixture builds preconditions from scratch via PRD-declared endpoints
(the harness restarts the server before every test, so each test starts
against an empty database). Setup calls use get_success_data() so a failed
precondition surfaces as a clear "Setup step failed" message.

Identity threading: BidCoordinator calls are ownership-gated on the
Broadcaster id, so every bid/sublicense/renewal call goes through
make_bid_coordinator_headers(broadcaster["id"]).

Clock discipline: the logical clock starts at 2026-08-01T00:00:00Z (PRD
§2.4). Fixture default due dates are on/after that instant so invoicing and
on-time payment are reachable without moving the clock; overdue scenarios
are produced by advancing the clock forward past the due date.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import TEST_DEFAULTS
from .factories import (
    create_rights_asset_payload,
    create_broadcaster_payload,
    create_package_payload,
    create_bid_payload,
    execute_deal_payload,
    create_payment_milestone_payload,
    create_production_obligation_payload,
    create_broadcast_event_payload,
    create_audience_measurement_payload,
    create_sublicense_request_payload,
    create_blackout_window_payload,
)
from .test_users import TEST_USERS, make_bid_coordinator_headers

RM = TEST_USERS["rights_manager_headers"]
FC = TEST_USERS["finance_controller_headers"]
PA = TEST_USERS["production_auditor_headers"]
CO = TEST_USERS["compliance_officer_headers"]


# ─── Tier 1: single-entity creation & state progression ────────────────

def create_rights_asset(**overrides) -> dict:
    """Create a rights asset. Returns the created asset (status OPEN)."""
    res = api_client.create_rights_asset(create_rights_asset_payload(**overrides), RM)
    return get_success_data(res)


def create_accredited_broadcaster(**overrides) -> dict:
    """Register + accredit a broadcaster. Returns the ACCREDITED broadcaster."""
    broadcaster = get_success_data(
        api_client.create_broadcaster(create_broadcaster_payload(**overrides), RM)
    )
    res = api_client.accredit_broadcaster(broadcaster["id"], RM)
    return get_success_data(res)


def create_package(asset_id: str, **overrides) -> dict:
    """Create a rights package under an asset. Returns the DRAFT package."""
    res = api_client.create_package(create_package_payload(asset_id, **overrides), RM)
    return get_success_data(res)


def lock_asset_packages(asset_id: str) -> dict:
    """Lock an asset's package slate (asset -> PACKAGES_LOCKED)."""
    return get_success_data(api_client.lock_packages(asset_id, RM))


def advance_clock(to_iso8601: str) -> dict:
    """Advance the logical clock forward (RightsManager-only capability)."""
    return get_success_data(
        api_client.set_clock({"to_iso8601": to_iso8601}, RM)
    )


def get_deal(deal_id: str) -> dict:
    return get_success_data(api_client.get_deal(deal_id, RM))


def get_package(package_id: str) -> dict:
    return get_success_data(api_client.get_package(package_id, RM))


def get_bid(package_id: str, bid_id: str) -> dict:
    return get_success_data(api_client.get_bid(package_id, bid_id, RM))


def get_milestone(deal_id: str, milestone_id: str) -> dict:
    return get_success_data(api_client.get_payment_milestone(deal_id, milestone_id, RM))


def get_obligation(deal_id: str, obligation_id: str) -> dict:
    return get_success_data(
        api_client.get_production_obligation(deal_id, obligation_id, RM)
    )


def get_broadcaster(broadcaster_id: str) -> dict:
    return get_success_data(api_client.get_broadcaster(broadcaster_id, RM))


def get_sublicense(deal_id: str, request_id: str) -> dict:
    return get_success_data(api_client.get_sublicense_request(deal_id, request_id, RM))


# ─── Tier 2: market hierarchy (asset -> package -> open for bids) ───────

def setup_open_market(asset_overrides=None, package_overrides=None) -> tuple:
    """Create asset + one package, lock the slate. Returns (asset, package).

    After this fixture the package is OPEN_FOR_BIDS and the asset is
    PACKAGES_LOCKED.
    """
    asset = create_rights_asset(**(asset_overrides or {}))
    package = create_package(asset["id"], **(package_overrides or {}))
    lock_asset_packages(asset["id"])
    package = get_package(package["id"])
    return asset, package


# ─── Tier 3: bidding lifecycle shortcuts ────────────────────────────────

def file_bid(package_id: str, broadcaster_id: str, **overrides) -> dict:
    """File a DRAFT bid on a package as the broadcaster's BidCoordinator."""
    res = api_client.create_bid(
        package_id,
        create_bid_payload(bidder_id=broadcaster_id, **overrides),
        make_bid_coordinator_headers(broadcaster_id),
    )
    return get_success_data(res)


def submit_bid(package_id: str, bid_id: str, broadcaster_id: str) -> dict:
    """Submit a DRAFT bid (bidder-side act)."""
    res = api_client.submit_bid(
        package_id, bid_id, make_bid_coordinator_headers(broadcaster_id)
    )
    return get_success_data(res)


def walk_bid_to_shortlisted(package_id: str, bid_id: str) -> dict:
    """Drive a SUBMITTED bid through UNDER_REVIEW to SHORTLISTED."""
    get_success_data(api_client.start_review_bid(package_id, bid_id, RM))
    res = api_client.shortlist_bid(package_id, bid_id, RM)
    return get_success_data(res)


def setup_submitted_bid(
    asset_overrides=None,
    package_overrides=None,
    broadcaster_overrides=None,
    bid_overrides=None,
) -> dict:
    """Open market + accredited broadcaster + one SUBMITTED bid.

    The package flips to UNDER_NEGOTIATION on the first submission.
    """
    asset, package = setup_open_market(asset_overrides, package_overrides)
    broadcaster = create_accredited_broadcaster(**(broadcaster_overrides or {}))
    bid = file_bid(package["id"], broadcaster["id"], **(bid_overrides or {}))
    bid = submit_bid(package["id"], bid["id"], broadcaster["id"])
    return {
        "asset": asset,
        "package": get_package(package["id"]),
        "broadcaster": broadcaster,
        "bid": bid,
    }


def setup_shortlisted_bid(
    asset_overrides=None,
    package_overrides=None,
    broadcaster_overrides=None,
    bid_overrides=None,
) -> dict:
    """Market + broadcaster + one SHORTLISTED bid (package UNDER_NEGOTIATION)."""
    bundle = setup_submitted_bid(
        asset_overrides, package_overrides, broadcaster_overrides, bid_overrides
    )
    bid = walk_bid_to_shortlisted(bundle["package"]["id"], bundle["bid"]["id"])
    bundle["bid"] = bid
    bundle["package"] = get_package(bundle["package"]["id"])
    return bundle


def accept_winning_bid(package_id: str, bid_id: str) -> dict:
    """Accept a SHORTLISTED bid with a fresh expected_package_version (OCC).

    Returns the auto-created Deal (status DRAFT).
    """
    package = get_package(package_id)
    res = api_client.accept_bid(
        package_id, bid_id, {"expected_package_version": package["version"]}, RM
    )
    return get_success_data(res)


def setup_awarded_deal(
    asset_overrides=None,
    package_overrides=None,
    broadcaster_overrides=None,
    bid_overrides=None,
) -> dict:
    """Full award flow: package AWARDED, bid ACCEPTED, deal auto-created DRAFT."""
    bundle = setup_shortlisted_bid(
        asset_overrides, package_overrides, broadcaster_overrides, bid_overrides
    )
    deal = accept_winning_bid(bundle["package"]["id"], bundle["bid"]["id"])
    bundle["deal"] = deal
    bundle["bid"] = get_bid(bundle["package"]["id"], bundle["bid"]["id"])
    bundle["package"] = get_package(bundle["package"]["id"])
    return bundle


# ─── Tier 4: deal schedule, execution, and activation ───────────────────

def add_payment_milestone(
    deal_id: str,
    season_index: int = 1,
    sequence_in_season: int = 1,
    due_date: str = TEST_DEFAULTS["DUE_DATE"],
    milestone_weight: float = 1.0,
) -> dict:
    """Create a payment milestone (FinanceController)."""
    res = api_client.create_payment_milestone(
        deal_id,
        create_payment_milestone_payload(
            season_index=season_index,
            sequence_in_season=sequence_in_season,
            due_date=due_date,
            milestone_weight=milestone_weight,
        ),
        FC,
    )
    return get_success_data(res)


def add_production_obligation(deal_id: str, season_index: int = 1) -> dict:
    """Create a production obligation for a season (ProductionAuditor)."""
    res = api_client.create_production_obligation(
        deal_id, create_production_obligation_payload(season_index=season_index), PA
    )
    return get_success_data(res)


def execute_deal(
    deal_id: str,
    term_start: str = TEST_DEFAULTS["TERM_START"],
    term_end: str = TEST_DEFAULTS["TERM_END"],
) -> dict:
    """Execute a DRAFT deal with a fresh expected_deal_version (OCC)."""
    deal = get_deal(deal_id)
    res = api_client.execute_deal(
        deal_id,
        execute_deal_payload(
            deal["version"], term_start=term_start, term_end=term_end
        ),
        RM,
    )
    return get_success_data(res)


def setup_executed_deal(
    milestone_specs=None,
    obligation_seasons=(1,),
    term_start=TEST_DEFAULTS["TERM_START"],
    term_end=TEST_DEFAULTS["TERM_END"],
    **scenario_overrides,
) -> dict:
    """Awarded deal + payment milestones + production obligations, EXECUTED.

    milestone_specs: iterable of (season_index, sequence_in_season, due_date,
    milestone_weight) tuples. Defaults to one milestone for season 1 due
    2026-09-01 (after the startup clock).
    """
    bundle = setup_awarded_deal(
        asset_overrides=scenario_overrides.get("asset_overrides"),
        package_overrides=scenario_overrides.get("package_overrides"),
        broadcaster_overrides=scenario_overrides.get("broadcaster_overrides"),
        bid_overrides=scenario_overrides.get("bid_overrides"),
    )
    deal_id = bundle["deal"]["id"]
    specs = milestone_specs
    if specs is None:
        specs = [(1, 1, TEST_DEFAULTS["DUE_DATE"], 1.0)]
    milestones = [
        add_payment_milestone(
            deal_id,
            season_index=s,
            sequence_in_season=q,
            due_date=d,
            milestone_weight=w,
        )
        for (s, q, d, w) in specs
    ]
    obligations = [add_production_obligation(deal_id, season_index=s) for s in obligation_seasons]
    bundle["milestones"] = milestones
    bundle["obligations"] = obligations
    bundle["deal"] = execute_deal(deal_id, term_start=term_start, term_end=term_end)
    return bundle


def pay_milestone_on_time(deal_id: str, milestone_id: str) -> dict:
    """Invoice + record payment while the clock is on/before the due date."""
    get_success_data(api_client.invoice_milestone(deal_id, milestone_id, FC))
    res = api_client.record_payment(deal_id, milestone_id, FC)
    return get_success_data(res)


def setup_active_deal(**kwargs) -> dict:
    """Executed deal whose first milestone is PAID: the deal is ACTIVE."""
    bundle = setup_executed_deal(**kwargs)
    first = bundle["milestones"][0]
    pay_milestone_on_time(bundle["deal"]["id"], first["id"])
    bundle["deal"] = get_deal(bundle["deal"]["id"])
    bundle["milestones"][0] = get_milestone(bundle["deal"]["id"], first["id"])
    return bundle


def create_delivered_events(
    deal_id: str,
    obligation_id: str,
    count: int,
    start_date: str = "2026-03-01T00:00:00Z",
    spacing_days: int = 4,
) -> list:
    """Schedule + mark-delivered `count` broadcast events on an obligation.

    Event kickoffs walk forward from start_date in spacing_days steps; the
    delivered timestamp equals the scheduled kickoff.
    """
    from datetime import datetime, timedelta

    base = datetime.strptime(start_date, "%Y-%m-%dT%H:%M:%SZ")
    events = []
    for i in range(count):
        kickoff = (base + timedelta(days=i * spacing_days)).strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        )
        event = get_success_data(
            api_client.create_broadcast_event(
                deal_id,
                create_broadcast_event_payload(
                    obligation_id, scheduled_kickoff_utc=kickoff
                ),
                PA,
            )
        )
        delivered = get_success_data(
            api_client.mark_delivered(
                deal_id, event["id"], {"actual_air_start_utc": kickoff}, PA
            )
        )
        events.append(delivered)
    return events


def file_sublicense_request(deal_id: str, broadcaster_id: str, **overrides) -> dict:
    """File a PENDING sublicense request as the deal broadcaster's coordinator."""
    res = api_client.create_sublicense_request(
        deal_id,
        create_sublicense_request_payload(**overrides),
        make_bid_coordinator_headers(broadcaster_id),
    )
    return get_success_data(res)


def create_blackout_window(asset_id: str, **overrides) -> dict:
    """Create a blackout window (ComplianceOfficer)."""
    res = api_client.create_blackout_window(
        create_blackout_window_payload(asset_id, **overrides), CO
    )
    return get_success_data(res)


def list_conflicts(params=None) -> list:
    """List rights-conflict monitor rows (data list only)."""
    data = get_success_data(api_client.list_rights_conflicts(RM, params=params))
    return data if isinstance(data, list) else data.get("items", [])
