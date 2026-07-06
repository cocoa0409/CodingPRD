"""Composite setup helpers.

Each helper builds its preconditions from scratch using only PRD-declared endpoints,
because the test harness restarts the server (empty DB) before every test. Fixtures use
get_success_data() internally so setup failures surface as clear "Setup failed" errors.

All roles are opaque operator identities (PRD §2.1): X-User-ID is never compared to any
entity id, so the shared TEST_USERS headers are used throughout — there are no
ownership-gated calls in this domain.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .test_users import TEST_USERS
from . import factories as F

AM = TEST_USERS["account_manager_headers"]
MS = TEST_USERS["media_specialist_headers"]
SC = TEST_USERS["scheduling_coordinator_headers"]
PA = TEST_USERS["platform_admin_headers"]


# --------------------------------------------------------------------------- #
# Primitive single-entity helpers
# --------------------------------------------------------------------------- #

def create_client(**overrides) -> dict:
    resp = api_client.create_client(F.create_client_payload(**overrides), AM)
    return get_success_data(resp)


def create_outlet(**overrides) -> dict:
    resp = api_client.create_outlet(F.create_outlet_payload(**overrides), PA)
    return get_success_data(resp)


def create_journalist(outlet_id, **overrides) -> dict:
    resp = api_client.create_journalist(F.create_journalist_payload(outlet_id, **overrides), MS)
    return get_success_data(resp)


def create_campaign(client_id, **overrides) -> dict:
    resp = api_client.create_campaign(F.create_campaign_payload(client_id, **overrides), AM)
    return get_success_data(resp)


def create_spokesperson(client_id, **overrides) -> dict:
    resp = api_client.create_spokesperson(F.create_spokesperson_payload(client_id, **overrides), AM)
    return get_success_data(resp)


def set_clock(to_iso8601) -> dict:
    resp = api_client.set_clock(to_iso8601, PA)
    return get_success_data(resp)


# --------------------------------------------------------------------------- #
# Tier 1: State progression
# --------------------------------------------------------------------------- #

def create_active_campaign(client_overrides=None, campaign_overrides=None):
    """Create client + campaign + activate. Returns (client, campaign)."""
    client = create_client(**(client_overrides or {}))
    campaign = create_campaign(client["id"], **(campaign_overrides or {}))
    get_success_data(api_client.activate_campaign(campaign["id"], AM))
    campaign = get_success_data(api_client.get_campaign(campaign["id"], AM))
    return client, campaign


# --------------------------------------------------------------------------- #
# Tier 2: Entity hierarchy — the canonical "earned-media" preamble
# --------------------------------------------------------------------------- #

def setup_campaign_with_media_list(client_overrides=None, campaign_overrides=None,
                                   outlet_overrides=None, journalist_overrides=None,
                                   activate=True):
    """Client + campaign (activated by default) + outlet + one journalist + an ACTIVE
    media list containing that journalist.

    Returns dict with keys: client, campaign, outlet, journalist, media_list.
    The media-list create uses the campaign's freshly re-read version (OCC).
    """
    client = create_client(**(client_overrides or {}))
    campaign = create_campaign(client["id"], **(campaign_overrides or {}))
    if activate:
        get_success_data(api_client.activate_campaign(campaign["id"], AM))
    outlet = create_outlet(**(outlet_overrides or {}))
    journalist = create_journalist(outlet["id"], **(journalist_overrides or {}))
    # Re-read campaign version for OCC-guarded media-list create.
    campaign = get_success_data(api_client.get_campaign(campaign["id"], AM))
    ml_resp = api_client.create_media_list(
        F.create_media_list_payload(
            campaign["id"], [journalist["id"]], campaign["version"], name="Setup List",
        ),
        MS,
    )
    media_list = get_success_data(ml_resp)
    campaign = get_success_data(api_client.get_campaign(campaign["id"], AM))
    return {
        "client": client,
        "campaign": campaign,
        "outlet": outlet,
        "journalist": journalist,
        "media_list": media_list,
    }


def create_media_list_current(campaign_id, journalist_ids, **overrides) -> dict:
    """Create a media list against a campaign using its current (re-read) version."""
    campaign = get_success_data(api_client.get_campaign(campaign_id, AM))
    resp = api_client.create_media_list(
        F.create_media_list_payload(campaign_id, journalist_ids, campaign["version"], **overrides),
        MS,
    )
    return get_success_data(resp)


# --------------------------------------------------------------------------- #
# Tier 3: Pitch lifecycle shortcuts
# --------------------------------------------------------------------------- #

def create_pitch(campaign_id, media_list_id, journalist_id, **overrides) -> dict:
    resp = api_client.create_pitch(
        F.create_pitch_payload(campaign_id, media_list_id, journalist_id, **overrides), MS)
    return get_success_data(resp)


def create_pitch_in_state(campaign_id, media_list_id, journalist_id, target_state, **overrides):
    """Create a pitch and walk DRAFT -> ... -> target_state.

    target_state one of DRAFT, SENT, RESPONDED, ACCEPTED.
    """
    pitch = create_pitch(campaign_id, media_list_id, journalist_id, **overrides)
    if target_state == "DRAFT":
        return get_success_data(api_client.get_pitch(pitch["id"], MS))
    get_success_data(api_client.send_pitch(pitch["id"], MS))
    if target_state == "SENT":
        return get_success_data(api_client.get_pitch(pitch["id"], MS))
    get_success_data(api_client.respond_pitch(pitch["id"], MS))
    if target_state == "RESPONDED":
        return get_success_data(api_client.get_pitch(pitch["id"], MS))
    get_success_data(api_client.accept_pitch(pitch["id"], MS))
    if target_state == "ACCEPTED":
        return get_success_data(api_client.get_pitch(pitch["id"], MS))
    raise ValueError(f"Unsupported pitch target_state: {target_state}")


# --------------------------------------------------------------------------- #
# Tier 3: Press-release / distribution shortcuts
# --------------------------------------------------------------------------- #

def create_press_release(campaign_id, **overrides) -> dict:
    resp = api_client.create_press_release(F.create_press_release_payload(campaign_id, **overrides), MS)
    return get_success_data(resp)


def create_scheduled_press_release(campaign_id, embargo_until, **overrides) -> dict:
    """Create a press release and schedule it (DRAFT -> SCHEDULED)."""
    pr = create_press_release(campaign_id, embargo_until=embargo_until, **overrides)
    get_success_data(api_client.schedule_press_release(pr["id"], MS))
    return get_success_data(api_client.get_press_release(pr["id"], MS))


def create_distribution(press_release_id, journalist_id, **overrides) -> dict:
    resp = api_client.create_distribution(
        F.create_distribution_payload(press_release_id, journalist_id, **overrides), MS)
    return get_success_data(resp)


# --------------------------------------------------------------------------- #
# Tier 3: Coverage shortcuts
# --------------------------------------------------------------------------- #

def create_coverage(campaign_id, journalist_id, **overrides) -> dict:
    resp = api_client.create_coverage(
        F.create_coverage_payload(campaign_id, journalist_id, **overrides), MS)
    return get_success_data(resp)


def create_verified_coverage(campaign_id, journalist_id, **overrides) -> dict:
    """Log a DRAFT coverage clip then verify it (DRAFT -> VERIFIED)."""
    cov = create_coverage(campaign_id, journalist_id, **overrides)
    get_success_data(api_client.verify_coverage(cov["id"], MS))
    return get_success_data(api_client.get_coverage(cov["id"], MS))


# --------------------------------------------------------------------------- #
# Tier 3: Interview shortcuts
# --------------------------------------------------------------------------- #

def create_interview(campaign_id, spokesperson_id, journalist_id, starts_at, ends_at, **overrides) -> dict:
    resp = api_client.create_interview(
        F.create_interview_payload(campaign_id, spokesperson_id, journalist_id,
                                   starts_at, ends_at, **overrides), SC)
    return get_success_data(resp)


def setup_interview_scenario(starts_at="2026-04-10T10:00:00Z", ends_at="2026-04-10T11:00:00Z",
                             spokesperson_overrides=None, create_the_interview=True):
    """Active campaign + active spokesperson + active journalist (+ one REQUESTED interview).

    Returns dict: client, campaign, outlet, journalist, spokesperson, interview (or None).
    No media list is created; interview create does not require one.
    """
    client = create_client()
    campaign = create_campaign(client["id"])
    get_success_data(api_client.activate_campaign(campaign["id"], AM))
    outlet = create_outlet()
    journalist = create_journalist(outlet["id"])
    spokesperson = create_spokesperson(client["id"], **(spokesperson_overrides or {}))
    interview = None
    if create_the_interview:
        interview = create_interview(
            campaign["id"], spokesperson["id"], journalist["id"], starts_at, ends_at)
    return {
        "client": client,
        "campaign": campaign,
        "outlet": outlet,
        "journalist": journalist,
        "spokesperson": spokesperson,
        "interview": interview,
    }


# --------------------------------------------------------------------------- #
# Tier 4: Retainer / billing threshold targeting
# --------------------------------------------------------------------------- #

def setup_open_period(monthly_hours_cap=20, overage_rate_cents=10000,
                      period_month="2026-03", client_overrides=None):
    """Client (with given cap/rate) + one OPEN retainer period. Returns (client, period)."""
    co = {"monthly_hours_cap": monthly_hours_cap, "overage_rate_cents": overage_rate_cents}
    co.update(client_overrides or {})
    client = create_client(**co)
    resp = api_client.create_retainer_period(
        F.create_retainer_period_payload(client["id"], period_month=period_month), AM)
    period = get_success_data(resp)
    return client, period


def log_time_entry(period_id, billable_hours, headers=None, **overrides) -> dict:
    resp = api_client.create_time_entry(
        F.create_time_entry_payload(period_id, billable_hours=billable_hours, **overrides),
        headers or AM)
    return get_success_data(resp)


def setup_period_with_approved_entries(monthly_hours_cap, overage_rate_cents, hours_list,
                                       period_month="2026-03", logger_headers=None):
    """Open a period and log + approve TimeEntries with the given billable_hours, in order.

    Entries are created in list order (created_at ascending) and each is approved.
    Returns (client, period, [entry_ids]). The period is NOT closed.
    """
    client, period = setup_open_period(monthly_hours_cap, overage_rate_cents, period_month)
    entry_ids = []
    for hours in hours_list:
        entry = log_time_entry(period["id"], hours, headers=logger_headers)
        entry_ids.append(entry["id"])
    for entry_id in entry_ids:
        get_success_data(api_client.approve_time_entry(entry_id, AM))
    period = get_success_data(api_client.get_retainer_period(period["id"], AM))
    return client, period, entry_ids


def close_period_current_version(period_id) -> dict:
    """Close a period using its current (re-read) version. Returns the closed period."""
    period = get_success_data(api_client.get_retainer_period(period_id, AM))
    resp = api_client.close_retainer_period(
        period_id, {"expected_retainer_period_version": period["version"]}, AM)
    return get_success_data(resp)


# --------------------------------------------------------------------------- #
# Tier 5: Crisis-event shortcuts
# --------------------------------------------------------------------------- #

def create_crisis_event(client_id=None, **overrides) -> dict:
    if client_id is None:
        client_id = create_client(industry="HEALTH")["id"]
    resp = api_client.create_crisis_event(F.create_crisis_event_payload(client_id, **overrides), AM)
    return get_success_data(resp)
