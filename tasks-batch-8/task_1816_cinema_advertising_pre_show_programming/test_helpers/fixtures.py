"""Composite setup helpers.

Every helper builds its preconditions from scratch against a fresh server using
only PRD-declared endpoints. Setup calls use the lenient get_success_data() so
that a setup failure surfaces as a clear "Setup failed" message rather than a
confusing assertion error.
"""
from prd_bench_local_runner.testing import get_success_data

from . import constants
from .api_client import api_client
from .factories import (
    acknowledge_delivery_payload, apply_make_good_payload,
    create_advertiser_payload, create_attendance_report_payload,
    create_campaign_payload, create_feature_payload,
    create_invoice_payload, create_playlog_payload, create_screen_payload,
    create_showtime_payload, create_slot_payload, create_theater_payload,
    lock_reel_payload, review_attendance_payload, review_make_good_payload,
    set_clock_payload,
)
from .test_users import (
    make_auditor_headers, make_network_ops_headers, make_sales_manager_headers,
    make_theater_ops_headers,
)

SM_CREATOR = "sm-1"
SM_APPROVER = "sm-2"
AUDITOR_1 = "aud-1"
AUDITOR_2 = "aud-2"


def _setup_failed(step: str, resp):
    raise AssertionError(f"Setup failed at {step}: {resp.status_code} {resp.text}")


def _ok(resp, step: str):
    data = get_success_data(resp)
    if data is None:
        _setup_failed(step, resp)
    return data


# ---------------------------------------------------------------------------
# Tier 2: master-data hierarchy
# ---------------------------------------------------------------------------

def create_theater(**overrides):
    """Create a theater. Returns the theater dict."""
    resp = api_client.create_theater(create_theater_payload(**overrides),
                                     make_network_ops_headers())
    return _ok(resp, "create_theater")


def create_screen(theater_id, **overrides):
    resp = api_client.create_screen(theater_id, create_screen_payload(**overrides),
                                    make_network_ops_headers())
    return _ok(resp, "create_screen")


def create_feature(**overrides):
    resp = api_client.create_feature(create_feature_payload(**overrides),
                                     make_network_ops_headers())
    return _ok(resp, "create_feature")


def setup_theater_screen_feature(theater_overrides=None, screen_overrides=None,
                                 feature_overrides=None):
    """Theater + 200-seat screen + PG13 feature released 2026-08-10.

    Returns (theater, screen, feature)."""
    theater = create_theater(**(theater_overrides or {}))
    screen = create_screen(theater["id"], **(screen_overrides or {}))
    feature = create_feature(**(feature_overrides or {}))
    return theater, screen, feature


def create_showtime_with_reel(screen_id, feature_id, starts_at=constants.OPENING_EVENING_START):
    """Schedule a showtime; returns (showtime, reel)."""
    resp = api_client.create_showtime(screen_id, create_showtime_payload(feature_id, starts_at=starts_at),
                                      make_network_ops_headers())
    showtime = _ok(resp, "create_showtime")
    reel_resp = api_client.get_showtime_reel(showtime["id"], make_network_ops_headers())
    reels = _ok(reel_resp, "get_showtime_reel")
    assert isinstance(reels, list) and len(reels) == 1, "Setup failed: expected exactly one reel per showtime"
    return showtime, reels[0]


def setup_showtime_with_reel(starts_at=constants.OPENING_EVENING_START, **kwargs):
    """Full master-data chain through a showtime and its auto-created reel.

    Returns (theater, screen, feature, showtime, reel)."""
    theater, screen, feature = setup_theater_screen_feature(**kwargs)
    showtime, reel = create_showtime_with_reel(screen["id"], feature["id"], starts_at)
    return theater, screen, feature, showtime, reel


# ---------------------------------------------------------------------------
# Tier 1/2: advertiser + campaign state progression
# ---------------------------------------------------------------------------

def create_advertiser(**overrides):
    resp = api_client.create_advertiser(create_advertiser_payload(**overrides),
                                        make_sales_manager_headers(SM_CREATOR))
    return _ok(resp, "create_advertiser")


def create_campaign(advertiser_id, creator=SM_CREATOR, **overrides):
    resp = api_client.create_campaign(create_campaign_payload(advertiser_id, **overrides),
                                      make_sales_manager_headers(creator))
    return _ok(resp, "create_campaign")


def create_approved_campaign(advertiser_id=None, creator=SM_CREATOR,
                             approver=SM_APPROVER, **overrides):
    """Advertiser (if not given) + campaign walked DRAFT -> SUBMITTED -> APPROVED."""
    if advertiser_id is None:
        advertiser_id = create_advertiser()["id"]
    campaign = create_campaign(advertiser_id, creator=creator, **overrides)
    resp = api_client.submit_campaign(campaign["id"], make_sales_manager_headers(creator))
    _ok(resp, "submit_campaign")
    resp = api_client.approve_campaign(campaign["id"], make_sales_manager_headers(approver))
    return _ok(resp, "approve_campaign")


def get_reel_version(reel_id, role_headers=None):
    headers = role_headers or make_network_ops_headers()
    resp = api_client.get_reel(reel_id, headers)
    reel = _ok(resp, "get_reel")
    return reel["version"]


def reserve_slot(reel_id, campaign_id, start_offset_seconds=0, duration_seconds=60,
                 reel_version=None, caller=SM_CREATOR):
    """Reserve a slot against an ASSEMBLING reel; re-reads the reel version when
    not supplied. Returns the created slot dict."""
    if reel_version is None:
        reel_version = get_reel_version(reel_id)
    resp = api_client.create_slot(
        reel_id,
        create_slot_payload(campaign_id, reel_version,
                            start_offset_seconds=start_offset_seconds,
                            duration_seconds=duration_seconds),
        make_sales_manager_headers(caller),
    )
    return _ok(resp, "create_slot")


def lock_reel(reel_id):
    """Lock an ASSEMBLING reel (fresh version read). Returns the LOCKED reel."""
    version = get_reel_version(reel_id)
    resp = api_client.lock_reel(reel_id, lock_reel_payload(version), make_network_ops_headers())
    return _ok(resp, "lock_reel")


def dispatch_and_deliver(reel_id, theater_id):
    """LOCKED -> IN_TRANSIT -> DELIVERED with the owning theater's identity."""
    resp = api_client.dispatch_reel(reel_id, make_network_ops_headers())
    _ok(resp, "dispatch_reel")
    resp = api_client.acknowledge_delivery(reel_id, acknowledge_delivery_payload(),
                                           make_theater_ops_headers(theater_id))
    return _ok(resp, "acknowledge_delivery")


def set_clock(to_iso8601):
    resp = api_client.set_current_utc(set_clock_payload(to_iso8601), make_network_ops_headers())
    return _ok(resp, "set_current_utc")


def submit_and_accept_attendance(showtime_id, theater_id, reported_attendance):
    """Theater files a report; NetworkOps ACCEPTs it. Returns the ACCEPTED report."""
    resp = api_client.create_attendance_report(
        showtime_id, create_attendance_report_payload(reported_attendance=reported_attendance),
        make_theater_ops_headers(theater_id))
    report = _ok(resp, "create_attendance_report")
    resp = api_client.review_attendance_report(report["id"], review_attendance_payload("ACCEPT"),
                                               make_network_ops_headers())
    return _ok(resp, "review_attendance_report")


def record_playlog(slot_id, theater_id, outcome="VERIFIED"):
    resp = api_client.create_playlog(slot_id, create_playlog_payload(outcome=outcome),
                                     make_theater_ops_headers(theater_id))
    return _ok(resp, "create_playlog")


# ---------------------------------------------------------------------------
# Tier 3/5: full airing chains
# ---------------------------------------------------------------------------

def setup_bookable_slot(starts_at=constants.OPENING_EVENING_START, campaign_overrides=None,
                        duration_seconds=60):
    """Master data + APPROVED campaign + one RESERVED slot in an ASSEMBLING reel.

    Returns dict(theater, screen, feature, showtime, reel, campaign, slot)."""
    theater, screen, feature, showtime, reel = setup_showtime_with_reel(starts_at=starts_at)
    campaign = create_approved_campaign(**(campaign_overrides or {}))
    slot = reserve_slot(reel["id"], campaign["id"], duration_seconds=duration_seconds,
                        reel_version=reel["version"])
    return {
        "theater": theater, "screen": screen, "feature": feature,
        "showtime": showtime, "reel": reel, "campaign": campaign, "slot": slot,
    }


def setup_confirmed_slot(starts_at=constants.OPENING_EVENING_START, campaign_overrides=None):
    """Bookable chain + reel lock (slot CONFIRMED). Returns the same dict, with
    'reel' refreshed to its LOCKED state."""
    ctx = setup_bookable_slot(starts_at=starts_at, campaign_overrides=campaign_overrides)
    ctx["reel"] = lock_reel(ctx["reel"]["id"])
    return ctx


def setup_played_slot(reported_attendance=175, outcome="VERIFIED",
                      starts_at=constants.OPENING_EVENING_START,
                      clock=constants.AFTER_SHOW_CLOCK, campaign_overrides=None):
    """Full airing chain: slot CONFIRMED, reel DELIVERED, attendance ACCEPTED,
    playlog recorded. Returns the context dict extended with 'report'."""
    ctx = setup_confirmed_slot(starts_at=starts_at, campaign_overrides=campaign_overrides)
    dispatch_and_deliver(ctx["reel"]["id"], ctx["theater"]["id"])
    set_clock(clock)
    report = submit_and_accept_attendance(ctx["showtime"]["id"], ctx["theater"]["id"],
                                          reported_attendance)
    record_playlog(ctx["slot"]["id"], ctx["theater"]["id"], outcome=outcome)
    ctx["report"] = report
    return ctx


def setup_certified_invoice(reported_attendance=940, contracted_impressions=1000,
                            starts_at=constants.OPENING_EVENING_START,
                            clock=constants.AFTER_SHOW_CLOCK, outcome="VERIFIED",
                            issuer=SM_APPROVER, certifier=AUDITOR_1,
                            campaign_overrides=None):
    """Full chain through a CERTIFIED invoice.

    Returns dict(theater, screen, feature, showtime, reel, campaign, slot,
    report, invoice)."""
    overrides = {"contracted_impressions": contracted_impressions}
    overrides.update(campaign_overrides or {})
    ctx = setup_played_slot(reported_attendance=reported_attendance, outcome=outcome,
                            starts_at=starts_at, clock=clock, campaign_overrides=overrides)
    resp = api_client.create_invoice(ctx["campaign"]["id"], create_invoice_payload(),
                                     make_sales_manager_headers(SM_CREATOR))
    invoice = _ok(resp, "create_invoice")
    resp = api_client.issue_invoice(invoice["id"], make_sales_manager_headers(issuer))
    invoice = _ok(resp, "issue_invoice")
    resp = api_client.certify_invoice(invoice["id"], make_auditor_headers(certifier))
    invoice = _ok(resp, "certify_invoice")
    ctx["invoice"] = invoice
    return ctx


def propose_make_good(invoice_id, proposer=AUDITOR_1):
    resp = api_client.create_make_good(invoice_id, make_auditor_headers(proposer))
    return _ok(resp, "create_make_good")


def approve_make_good(make_good_id, reviewer=AUDITOR_2):
    resp = api_client.review_make_good(make_good_id, review_make_good_payload("APPROVE"),
                                       make_auditor_headers(reviewer))
    return _ok(resp, "review_make_good")


def get_invoice_version(invoice_id):
    resp = api_client.get_invoice(invoice_id, make_sales_manager_headers(SM_CREATOR))
    return _ok(resp, "get_invoice")["version"]


def apply_make_good(make_good_id, invoice_id, applier=SM_CREATOR):
    resp = api_client.apply_make_good(
        make_good_id, apply_make_good_payload(get_invoice_version(invoice_id)),
        make_sales_manager_headers(applier))
    return _ok(resp, "apply_make_good")
