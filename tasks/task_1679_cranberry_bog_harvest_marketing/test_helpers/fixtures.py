"""Composite setup helpers for multi-step test prerequisites.

Every helper builds preconditions from scratch using only PRD-declared
endpoints (each test runs against a freshly started server with an empty
database). Setup calls use get_success_data() so a setup failure surfaces a
clear "Setup step failed" error instead of a confusing assertion failure.

Identity threading (PRD §2.1): GrowerMember calls carry the owning Member.id
and StationOperator receive/grade calls carry the ReceivingStation.id via the
make_*_headers builders — never the shared fallback constants.
"""
from types import SimpleNamespace

from prd_bench_local_runner.testing import get_success_data, validate_paginated

from .api_client import api_client
from .constants import TEST_DEFAULTS as D
from .factories import (
    create_bog_payload,
    create_delivery_payload,
    create_estimate_payload,
    create_frost_event_payload,
    create_member_payload,
    create_pool_payload,
    create_season_payload,
    create_station_payload,
    create_ticket_payload,
    grade_delivery_payload,
    patch_quota_payload,
    receive_delivery_payload,
    settle_pool_payload,
)
from .test_users import (
    TEST_USERS,
    make_grower_headers,
    make_station_operator_headers,
)

ADMIN = TEST_USERS["coop_admin_headers"]
OFFICER = TEST_USERS["field_officer_headers"]
POOL_MGR = TEST_USERS["pool_manager_headers"]


# ─── Members ──────────────────────────────────────────────────────────────────

def create_member(member_code="M100", full_name="Alice Grower"):
    """Register a member (starts PENDING)."""
    return get_success_data(api_client.create_member(
        create_member_payload(member_code=member_code, full_name=full_name), ADMIN))


def transition_member(member_id, to):
    return get_success_data(api_client.transition_member(
        member_id, {"to": to}, ADMIN))


def create_active_member(member_code="M100", full_name="Alice Grower"):
    """Member registered and activated (PENDING -> ACTIVE)."""
    member = create_member(member_code, full_name)
    return transition_member(member["id"], "ACTIVE")


def get_member(member_id):
    return get_success_data(api_client.get_member(member_id, ADMIN))


# ─── Bogs ─────────────────────────────────────────────────────────────────────

def create_bog_for(member_id, **overrides):
    """Register a bog owned by member_id (GrowerMember caller becomes owner)."""
    return get_success_data(api_client.create_bog(
        create_bog_payload(**overrides), make_grower_headers(member_id)))


def transition_bog(bog_id, to, headers):
    return get_success_data(api_client.transition_bog(bog_id, {"to": to}, headers))


def get_bog(bog_id):
    return get_success_data(api_client.get_bog(bog_id, ADMIN))


# ─── Seasons ──────────────────────────────────────────────────────────────────

def create_season(**overrides):
    """Create a season (starts SETUP)."""
    return get_success_data(api_client.create_season(
        create_season_payload(**overrides), ADMIN))


def open_season(season_id):
    """Open a SETUP season; creates one MemberQuota per ACTIVE member."""
    return get_success_data(api_client.open_season(season_id, ADMIN))


def get_season(season_id):
    return get_success_data(api_client.get_season(season_id, ADMIN))


# ─── Stations ─────────────────────────────────────────────────────────────────

def create_station(name="Station A", daily_capacity_barrels=None):
    return get_success_data(api_client.create_station(
        create_station_payload(
            name=name,
            daily_capacity_barrels=daily_capacity_barrels or D["STATION_CAPACITY"]),
        ADMIN))


# ─── Quotas ───────────────────────────────────────────────────────────────────

def get_quota_for(member_id, season_id):
    """Return the single MemberQuota row for (member, season) via the list filter."""
    resp = api_client.list_quotas(ADMIN, params={"member_id": member_id,
                                                 "season_id": season_id})
    data, _meta = validate_paginated(resp)
    assert len(data) == 1, (
        f"Expected exactly one quota row for member={member_id} "
        f"season={season_id}, got {len(data)}"
    )
    return data[0]


def get_quota(quota_id):
    return get_success_data(api_client.get_quota(quota_id, ADMIN))


def override_quota(quota_id, base_quota_barrels, expected_quota_version=None):
    """PATCH a quota override. Reads the current version when none is given."""
    if expected_quota_version is None:
        expected_quota_version = get_quota(quota_id)["version"]
    return get_success_data(api_client.patch_quota(
        quota_id, patch_quota_payload(base_quota_barrels, expected_quota_version),
        ADMIN))


# ─── Yield estimates ──────────────────────────────────────────────────────────

def create_estimate(bog_id, season_id, member_id, estimated_barrels=2300):
    return get_success_data(api_client.create_yield_estimate(
        create_estimate_payload(bog_id, season_id,
                                estimated_barrels=estimated_barrels),
        make_grower_headers(member_id)))


def transition_estimate(estimate_id, payload, headers):
    return get_success_data(api_client.transition_yield_estimate(
        estimate_id, payload, headers))


def approve_estimate(estimate_id):
    return transition_estimate(estimate_id, {"to": "APPROVED"}, OFFICER)


def create_and_approve_estimate(bog_id, season_id, member_id, estimated_barrels):
    estimate = create_estimate(bog_id, season_id, member_id, estimated_barrels)
    return approve_estimate(estimate["id"])


def get_estimate(estimate_id):
    return get_success_data(api_client.get_yield_estimate(estimate_id, OFFICER))


# ─── Harvest tickets ──────────────────────────────────────────────────────────

def create_ticket(bog_id, season_id, member_id, **overrides):
    return get_success_data(api_client.create_harvest_ticket(
        create_ticket_payload(bog_id, season_id, **overrides),
        make_grower_headers(member_id)))


def approve_ticket(ticket_id):
    return get_success_data(api_client.transition_harvest_ticket(
        ticket_id, {"to": "APPROVED"}, OFFICER))


def get_ticket(ticket_id):
    return get_success_data(api_client.get_harvest_ticket(ticket_id, OFFICER))


# ─── Frost events ─────────────────────────────────────────────────────────────

def create_frost_event(bog_id, season_id, **overrides):
    return get_success_data(api_client.create_frost_event(
        create_frost_event_payload(bog_id, season_id, **overrides), OFFICER))


def transition_frost_event(event_id, payload):
    return get_success_data(api_client.transition_frost_event(
        event_id, payload, OFFICER))


def get_frost_event(event_id):
    return get_success_data(api_client.get_frost_event(event_id, OFFICER))


# ─── Pools ────────────────────────────────────────────────────────────────────

def create_pool(season_id, code="MAIN", rate=None, retain_pct=None):
    rate = D["ADVANCE_RATE_MAIN"] if rate is None else rate
    retain_pct = D["RETAIN_PCT"] if retain_pct is None else retain_pct
    return get_success_data(api_client.create_pool(
        create_pool_payload(season_id, code=code,
                            provisional_advance_rate_per_barrel=rate,
                            retain_pct=retain_pct),
        POOL_MGR))


def get_pool(pool_id):
    return get_success_data(api_client.get_pool(pool_id, POOL_MGR))


def transition_pool(pool_id, to):
    return get_success_data(api_client.transition_pool(pool_id, {"to": to}, POOL_MGR))


def close_pool(pool_id):
    return transition_pool(pool_id, "CLOSED")


def settle_pool(pool_id, realized_revenue, operating_costs,
                expected_pool_version=None):
    """Settle a CLOSED pool. Reads the current version when none is given."""
    if expected_pool_version is None:
        expected_pool_version = get_pool(pool_id)["version"]
    return get_success_data(api_client.settle_pool(
        pool_id,
        settle_pool_payload(realized_revenue, operating_costs,
                            expected_pool_version),
        POOL_MGR))


# ─── Deliveries ───────────────────────────────────────────────────────────────

def create_delivery(season_id, bog_id, station_id, member_id, **overrides):
    return get_success_data(api_client.create_delivery(
        create_delivery_payload(season_id, bog_id, station_id, **overrides),
        make_grower_headers(member_id)))


def get_delivery(delivery_id):
    return get_success_data(api_client.get_delivery(delivery_id, POOL_MGR))


def receive_delivery(delivery_id, station_id, gross_barrels, tare_barrels):
    return get_success_data(api_client.receive_delivery(
        delivery_id, receive_delivery_payload(gross_barrels, tare_barrels),
        make_station_operator_headers(station_id)))


def grade_delivery(delivery_id, station_id, color_score, firmness_score,
                   foreign_matter_pct):
    return get_success_data(api_client.grade_delivery(
        delivery_id,
        grade_delivery_payload(color_score, firmness_score, foreign_matter_pct),
        make_station_operator_headers(station_id)))


def accept_delivery(delivery_id):
    return get_success_data(api_client.accept_delivery(delivery_id, POOL_MGR))


def dispute_delivery(delivery_id, member_id):
    return get_success_data(api_client.dispute_delivery(
        delivery_id, make_grower_headers(member_id)))


def void_delivery(delivery_id):
    return get_success_data(api_client.void_delivery(delivery_id, POOL_MGR))


# ─── Distributions ────────────────────────────────────────────────────────────

def list_distributions(pool_id=None, member_id=None):
    params = {}
    if pool_id is not None:
        params["pool_id"] = pool_id
    if member_id is not None:
        params["member_id"] = member_id
    data, meta = validate_paginated(api_client.list_distributions(POOL_MGR,
                                                                  params=params))
    return data, meta


# ─── Composite scenarios ──────────────────────────────────────────────────────

def setup_campaign(member_code="M100", full_name="Alice Grower", acres=10,
                   variety="STEVENS", baseline=None, bog_overrides=None):
    """ACTIVE member + ACTIVE bog + OPEN season + the member's quota row."""
    member = create_active_member(member_code, full_name)
    bog = create_bog_for(member["id"], acres=acres, variety=variety,
                         **(bog_overrides or {}))
    season = create_season(
        baseline_barrels_per_acre=baseline or D["BASELINE_BARRELS_PER_ACRE"])
    open_season(season["id"])
    quota = get_quota_for(member["id"], season["id"])
    return SimpleNamespace(member=member, bog=bog, season=season, quota=quota)


def setup_campaign_with_station(member_code="M100", acres=10, capacity=None,
                                baseline=None):
    """Campaign + one receiving station."""
    ctx = setup_campaign(member_code=member_code, acres=acres, baseline=baseline)
    station = create_station(daily_capacity_barrels=capacity or D["STATION_CAPACITY"])
    return SimpleNamespace(**vars(ctx), station=station)


def setup_campaign_with_pool(member_code="M100", acres=10, capacity=None,
                             baseline=None, rate=None, retain_pct=None,
                             over_quota_pool=False, over_quota_rate=None):
    """Campaign + station + OPEN MAIN pool (and optionally an OVER_QUOTA pool)."""
    ctx = setup_campaign_with_station(member_code=member_code, acres=acres,
                                      capacity=capacity, baseline=baseline)
    main_pool = create_pool(ctx.season["id"], code="MAIN", rate=rate,
                            retain_pct=retain_pct)
    oq_pool = None
    if over_quota_pool:
        oq_pool = create_pool(ctx.season["id"], code="OVER_QUOTA",
                              rate=over_quota_rate if over_quota_rate is not None
                              else D["ADVANCE_RATE_OVER_QUOTA"],
                              retain_pct=retain_pct)
    return SimpleNamespace(**vars(ctx), main_pool=main_pool, oq_pool=oq_pool)


def setup_scheduled_delivery(ctx, scheduled_date=None, expected_barrels=150,
                             harvest_ticket_id=None):
    """One SCHEDULED delivery for the campaign's member/bog/station."""
    overrides = {"scheduled_date": scheduled_date or D["SCHEDULED_DATE"],
                 "expected_barrels": expected_barrels}
    if harvest_ticket_id is not None:
        overrides["harvest_ticket_id"] = harvest_ticket_id
    return create_delivery(ctx.season["id"], ctx.bog["id"], ctx.station["id"],
                           ctx.member["id"], **overrides)


def setup_received_delivery(ctx, gross_barrels, tare_barrels,
                            scheduled_date=None, expected_barrels=150):
    """SCHEDULED -> RECEIVED (net_barrels computed)."""
    delivery = setup_scheduled_delivery(ctx, scheduled_date=scheduled_date,
                                        expected_barrels=expected_barrels)
    return receive_delivery(delivery["id"], ctx.station["id"],
                            gross_barrels, tare_barrels)


def setup_graded_delivery(ctx, gross_barrels, tare_barrels, color_score,
                          firmness_score, foreign_matter_pct,
                          scheduled_date=None, expected_barrels=150):
    """SCHEDULED -> RECEIVED -> GRADED (or REJECTED for failing scores)."""
    delivery = setup_received_delivery(
        ctx, gross_barrels, tare_barrels, scheduled_date=scheduled_date,
        expected_barrels=expected_barrels)
    return grade_delivery(delivery["id"], ctx.station["id"], color_score,
                          firmness_score, foreign_matter_pct)


def setup_accepted_delivery(ctx, gross_barrels, tare_barrels, color_score,
                            firmness_score, foreign_matter_pct,
                            scheduled_date=None, expected_barrels=150):
    """Full pipeline through to ACCEPTED (requires an OPEN MAIN pool)."""
    delivery = setup_graded_delivery(
        ctx, gross_barrels, tare_barrels, color_score, firmness_score,
        foreign_matter_pct, scheduled_date=scheduled_date,
        expected_barrels=expected_barrels)
    return accept_delivery(delivery["id"])


def setup_settled_main_pool(realized_revenue=2000, operating_costs=200):
    """Single-member campaign: one ACCEPTED A-grade delivery (net 950,
    weighted 1045, advance 522.50 at the 0.50 rate), MAIN pool CLOSED
    (season auto HARVEST_CLOSED), then settled.

    Returns ctx with member/bog/season/station/main_pool/delivery/pool_after.
    """
    ctx = setup_campaign_with_pool()
    delivery = setup_accepted_delivery(
        ctx, gross_barrels=1000, tare_barrels=50, color_score=9.0,
        firmness_score=8.5, foreign_matter_pct=1.5, expected_barrels=1000)
    close_pool(ctx.main_pool["id"])
    pool_after = settle_pool(ctx.main_pool["id"], realized_revenue,
                             operating_costs)
    return SimpleNamespace(**vars(ctx), delivery=delivery,
                           pool_after=pool_after)
