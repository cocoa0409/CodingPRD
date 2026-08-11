"""Composite setup helpers for multi-step test prerequisites.

All helpers build state purely through PRD-declared endpoints and use
get_success_data() internally so setup failures surface as clear errors.

Timekeeping convention (PRD §2.5): the global logical clock is pinned to the
startup default 2026-05-01T00:00:00Z before the distributor is created, so the
distributor's week_epoch 0 aligns with the week starting 2026-05-01. Helpers
that run multi-week lifecycles advance the logical clock in lockstep with the
weekly close, seven days per epoch, so a report dated inside week N is always
within the distributor's current or prior week_epoch (PRD §3.6).
"""
from datetime import datetime, timedelta, timezone

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    create_distributor_payload,
    create_film_payload,
    create_market_payload,
    create_theatre_payload,
    create_screen_payload,
    create_aggregate_deal_payload,
    create_booking_agreement_payload,
    create_dcp_shipment_payload,
    create_kdm_key_payload,
    create_box_office_report_payload,
    create_marketing_commitment_payload,
    create_zone_clearance_payload,
    create_ancillary_window_payload,
)
from .constants import LOGICAL_CLOCK_START, THEATRICAL_WINDOW_DAYS
from .test_users import TEST_USERS

ADMIN = TEST_USERS["platform_admin_headers"]
BOOKER = TEST_USERS["booker_headers"]
EXHIBITOR = TEST_USERS["exhibitor_headers"]
CLERK = TEST_USERS["settlement_clerk_headers"]
MARKETING = TEST_USERS["marketing_lead_headers"]
AUDITOR = TEST_USERS["auditor_headers"]

EPOCH_ANCHOR = datetime(2026, 5, 1, tzinfo=timezone.utc)


def week_start_iso(week_index: int) -> str:
    """UTC midnight at the start of week `week_index` (7-day weeks from the anchor)."""
    dt = EPOCH_ANCHOR + timedelta(days=7 * week_index)
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


# ---------------------------------------------------------------------------
# Tier 1 / 2: infrastructure and base hierarchies
# ---------------------------------------------------------------------------

def setup_distributor(name="Distro Co", territory="US", set_clock_first=True):
    """Create a Distributor. Optionally pins the logical clock to the startup
    default first so week_epoch 0 aligns with the week of 2026-05-01.
    Returns the Distributor dict."""
    if set_clock_first:
        get_success_data(api_client.set_current_utc({"to_iso8601": LOGICAL_CLOCK_START}, ADMIN))
    res = api_client.create_distributor(
        create_distributor_payload(name=name, territory=territory), ADMIN
    )
    return get_success_data(res)


def setup_market(did, code="NYC", weekly_coop_budget_cents=100000, population_tier="TIER_1"):
    res = api_client.create_market(
        did,
        create_market_payload(
            code=code,
            population_tier=population_tier,
            weekly_coop_budget_cents=weekly_coop_budget_cents,
        ),
        ADMIN,
    )
    return get_success_data(res)


def setup_theatre(did, name="Theatre One", circuit="Alamo", market_code="NYC",
                  house_allowance_cents=100):
    res = api_client.create_theatre(
        did,
        create_theatre_payload(
            name=name, circuit=circuit, market_code=market_code,
            house_allowance_cents=house_allowance_cents,
        ),
        ADMIN,
    )
    return get_success_data(res)


def setup_screen(did, tid, auditorium_label="Auditorium 1", seat_count=200,
                 projection_format="DCP_2K"):
    res = api_client.create_screen(
        did, tid,
        create_screen_payload(
            auditorium_label=auditorium_label, seat_count=seat_count,
            projection_format=projection_format,
        ),
        ADMIN,
    )
    return get_success_data(res)


def setup_film(did, title="Indie Feature", release_pattern="LIMITED",
               target_release_date="2026-05-01T00:00:00Z",
               min_screens_for_wide=0, genre="NARRATIVE", rating="R",
               runtime_minutes=100):
    res = api_client.create_film(
        did,
        create_film_payload(
            title=title, genre=genre, runtime_minutes=runtime_minutes, rating=rating,
            release_pattern=release_pattern, target_release_date=target_release_date,
            min_screens_for_wide=min_screens_for_wide,
        ),
        BOOKER,
    )
    return get_success_data(res)


def setup_distributor_film_theatre_screen(
    film_overrides=None,
    theatre_overrides=None,
    screen_overrides=None,
    distributor_name="Distro Co",
):
    """Distributor + one Film + one Theatre + one Screen.
    Returns dict(distributor, film, theatre, screen)."""
    distributor = setup_distributor(name=distributor_name)
    film = setup_film(distributor["id"], **(film_overrides or {}))
    theatre = setup_theatre(distributor["id"], **(theatre_overrides or {}))
    screen = setup_screen(distributor["id"], theatre["id"], **(screen_overrides or {}))
    return {
        "distributor": distributor,
        "film": film,
        "theatre": theatre,
        "screen": screen,
    }


# ---------------------------------------------------------------------------
# Tier 3: booking negotiation and print pipeline
# ---------------------------------------------------------------------------

def setup_proposed_booking(did, fid, tid, sid, **booking_overrides):
    """Create a BookingAgreement in PROPOSED. Returns the agreement dict."""
    res = api_client.create_booking_agreement(
        did, create_booking_agreement_payload(fid, tid, sid, **booking_overrides), BOOKER
    )
    return get_success_data(res)


def setup_accepted_booking(did, fid, tid, sid, accept_role="Exhibitor", **booking_overrides):
    """Create + accept a BookingAgreement. Returns the accepted agreement dict
    (post-state: deal_status ACCEPTED, print_status DCP_QUEUED)."""
    ba = setup_proposed_booking(did, fid, tid, sid, **booking_overrides)
    headers = EXHIBITOR if accept_role == "Exhibitor" else BOOKER
    res = api_client.accept_booking_agreement(
        did, ba["id"], {"expected_booking_agreement_version": ba["version"]}, headers
    )
    return get_success_data(res)


def setup_delivered_booking(did, fid, tid, sid, tracking_number="TN-0001",
                            content_format="DCP_2K", **booking_overrides):
    """Accepted booking + DCP shipment delivered.
    Returns (agreement, shipment): print_status DCP_DELIVERED."""
    ba = setup_accepted_booking(did, fid, tid, sid, **booking_overrides)
    ship = get_success_data(api_client.create_dcp_shipment(
        did, ba["id"],
        create_dcp_shipment_payload(content_format=content_format, tracking_number=tracking_number),
        BOOKER,
    ))
    get_success_data(api_client.mark_dcp_delivered(did, ba["id"], ship["id"], EXHIBITOR))
    ba = get_success_data(api_client.get_booking_agreement(did, ba["id"], BOOKER))
    return ba, ship


def setup_kdm_issued_booking(did, fid, tid, sid,
                             valid_from_utc="2026-05-01T00:00:00Z",
                             valid_until_utc="2026-07-31T00:00:00Z",
                             screen_cert_fingerprint="FP-1",
                             **booking_overrides):
    """Delivered booking + KDM issued. Returns (agreement, shipment, kdm):
    print_status KDM_ISSUED, key ISSUED."""
    ba, ship = setup_delivered_booking(did, fid, tid, sid, **booking_overrides)
    kdm = get_success_data(api_client.create_kdm_key(
        did, ba["id"],
        create_kdm_key_payload(
            valid_from_utc=valid_from_utc,
            valid_until_utc=valid_until_utc,
            screen_cert_fingerprint=screen_cert_fingerprint,
        ),
        BOOKER,
    ))
    ba = get_success_data(api_client.get_booking_agreement(did, ba["id"], BOOKER))
    return ba, ship, kdm


def setup_in_play_agreement(
    distributor_name="Distro Co",
    film_overrides=None,
    theatre_overrides=None,
    screen_overrides=None,
    booking_overrides=None,
    kdm_overrides=None,
):
    """Full pipeline to an IN_PLAY agreement: distributor, film, theatre,
    screen, accepted booking, delivered DCP, issued KDM, then the logical
    clock driven to the opening date so the key goes LIVE and the agreement
    enters IN_PLAY (PRD §3.5).

    Returns dict(distributor, film, theatre, screen, booking, shipment, kdm).
    """
    env = setup_distributor_film_theatre_screen(
        film_overrides=film_overrides,
        theatre_overrides=theatre_overrides,
        screen_overrides=screen_overrides,
        distributor_name=distributor_name,
    )
    did = env["distributor"]["id"]
    kdm_kw = dict(kdm_overrides or {})
    ba, ship, kdm = setup_kdm_issued_booking(
        did,
        env["film"]["id"],
        env["theatre"]["id"],
        env["screen"]["id"],
        **kdm_kw,
        **(booking_overrides or {}),
    )
    # Drive the logical clock to the opening date: KDM ISSUED -> LIVE,
    # print axis -> KEY_LIVE, deal ACCEPTED -> IN_PLAY (PRD §3.5).
    opening_date = ba["opening_date"]
    get_success_data(api_client.set_current_utc({"to_iso8601": opening_date}, ADMIN))
    ba = get_success_data(api_client.get_booking_agreement(did, ba["id"], BOOKER))
    assert ba["deal_status"] == "IN_PLAY", (
        f"Setup failed: expected IN_PLAY, got {ba['deal_status']} "
        f"(print_status={ba['print_status']})"
    )
    return {
        "distributor": env["distributor"],
        "film": env["film"],
        "theatre": env["theatre"],
        "screen": env["screen"],
        "booking": ba,
        "shipment": ship,
        "kdm": kdm,
    }


# ---------------------------------------------------------------------------
# Tier 4: weekly accumulation — reports, close, settle
# ---------------------------------------------------------------------------

def file_and_submit_report(did, baid, report_date, gross_cents, admissions):
    """File a BoxOfficeReport and submit it. Returns the SUBMITTED report."""
    report = get_success_data(api_client.create_box_office_report(
        did, baid,
        create_box_office_report_payload(
            report_date=report_date, gross_cents=gross_cents, admissions=admissions,
        ),
        EXHIBITOR,
    ))
    return get_success_data(
        api_client.submit_box_office_report(did, baid, report["id"], EXHIBITOR)
    )


def close_week(did):
    """SettlementClerk closes the box-office week. Returns updated Distributor."""
    return get_success_data(api_client.close_box_office_week(did, CLERK))


def close_week_with_reports(did, week_index, reports):
    """File + submit the week's reports per agreement, advance the logical
    clock to the start of the closed week, then close the box-office week.

    `reports` is a list of (baid, gross_cents, admissions) tuples; every report
    is dated at the UTC-midnight start of `week_index`'s 7-day epoch.
    Returns the updated Distributor."""
    for baid, gross_cents, admissions in reports:
        file_and_submit_report(did, baid, week_start_iso(week_index), gross_cents, admissions)
    get_success_data(
        api_client.set_current_utc({"to_iso8601": week_start_iso(week_index)}, ADMIN)
    )
    return close_week(did)


def get_latest_settlement(did, baid):
    """The most recently created Settlement for the agreement."""
    res = api_client.list_settlements(did, baid, CLERK)
    data = res.json()["data"]
    assert len(data) >= 1, f"Setup failed: no settlements for booking {baid}"
    return data[-1]


def get_settlements(did, baid):
    """All settlements for the agreement, in the server's list order."""
    res = api_client.list_settlements(did, baid, CLERK)
    return res.json()["data"]


def settle_latest(did, baid, clerk_headers=None):
    """Mark the latest settlement SETTLED (clerk user differs from the
    booking's creator, satisfying segregation of duties per PRD §3.7).
    Returns the SETTLED settlement."""
    settlement = get_latest_settlement(did, baid)
    return get_success_data(api_client.mark_settlement_settled(
        did, baid, settlement["id"], clerk_headers or CLERK
    ))


def run_settled_week(did, baid, week_index, gross_cents=500000, admissions=2000,
                     clerk_headers=None):
    """One full weekly cycle: report -> submit -> close -> mark settled.
    Advances the agreement's weeks_played by one. Returns the SETTLED settlement."""
    close_week_with_reports(did, week_index, [(baid, gross_cents, admissions)])
    return settle_latest(did, baid, clerk_headers=clerk_headers)


def setup_finalized_settlement(
    distributor_name="Distro Co",
    gross_cents=500000,
    admissions=2000,
    booking_overrides=None,
    house_allowance_cents=100,
    booker_headers=None,
):
    """Full pipeline through one FINALIZED settlement (week 0 closed, report
    locked, settlement finalized, not yet settled).

    Returns dict(distributor, film, theatre, screen, booking, settlement).
    The booking is created by `booker_headers` (defaults to the shared Booker
    user) so tests can control the creator identity for segregation-of-duties
    checks (PRD §3.7)."""
    env = setup_in_play_agreement(
        distributor_name=distributor_name,
        theatre_overrides={"house_allowance_cents": house_allowance_cents},
        booking_overrides=booking_overrides,
    )
    did = env["distributor"]["id"]
    baid = env["booking"]["id"]
    close_week_with_reports(did, 0, [(baid, gross_cents, admissions)])
    settlement = get_latest_settlement(did, baid)
    assert settlement["status"] in ("PENDING_FINAL", "FINALIZED"), (
        f"Setup failed: expected finalized settlement, got {settlement['status']}"
    )
    env["settlement"] = settlement
    return env


def setup_completed_booking(distributor_name="Distro Co", booking_overrides=None):
    """Full pipeline through COMPLETED: IN_PLAY with min_weeks_committed=1,
    one settled week, then a second weekly close auto-completes the agreement
    (PRD §3.8). Returns dict(distributor, film, theatre, screen, booking, ...)."""
    overrides = {"min_weeks_committed": 1}
    overrides.update(booking_overrides or {})
    env = setup_in_play_agreement(
        distributor_name=distributor_name, booking_overrides=overrides
    )
    did = env["distributor"]["id"]
    baid = env["booking"]["id"]
    close_week_with_reports(did, 0, [(baid, 500000, 2000)])
    settle_latest(did, baid)
    close_week(did)
    booking = get_success_data(api_client.get_booking_agreement(did, baid, BOOKER))
    assert booking["deal_status"] == "COMPLETED", (
        f"Setup failed: expected COMPLETED, got {booking['deal_status']}"
    )
    env["booking"] = booking
    return env


# ---------------------------------------------------------------------------
# Tier 4: holdover-eligible states
# ---------------------------------------------------------------------------

def setup_holdover_eligible_agreement(
    distributor_name="Distro Co",
    min_weeks_committed=1,
    week_grosses=None,
):
    """Drive an agreement to IN_PLAY with weeks_played == min_weeks_committed
    (holdover_eligible per PRD §3.3), leaving the current week's settlement
    unfinalized so the next close computes the automatic recommendation
    instead of completing the agreement.

    week_grosses[i] is the total locked gross for week i; defaults to
    250000 per week. Returns dict(distributor, film, theatre, screen, booking, ...).
    """
    n_weeks = min_weeks_committed
    week_grosses = week_grosses or [250000] * n_weeks
    assert len(week_grosses) == n_weeks
    env = setup_in_play_agreement(
        distributor_name=distributor_name,
        booking_overrides={"min_weeks_committed": min_weeks_committed},
    )
    did = env["distributor"]["id"]
    baid = env["booking"]["id"]
    for week_index, gross in enumerate(week_grosses):
        run_settled_week(did, baid, week_index, gross_cents=gross, admissions=2000)
    booking = get_success_data(api_client.get_booking_agreement(did, baid, BOOKER))
    assert booking["weeks_played"] == min_weeks_committed, (
        f"Setup failed: weeks_played={booking['weeks_played']}, "
        f"expected {min_weeks_committed}"
    )
    env["booking"] = booking
    return env


# ---------------------------------------------------------------------------
# Tier 2: co-op marketing helpers
# ---------------------------------------------------------------------------

def setup_committed_marketing_commitment(did, mid, fid, tid=None,
                                         committed_cents=100000,
                                         coop_share_pct=0.50):
    """Create + commit a MarketingCommitment. Returns the COMMITTED commitment."""
    payload = create_marketing_commitment_payload(
        fid, committed_cents=committed_cents, coop_share_pct=coop_share_pct
    )
    if tid is not None:
        payload["theatre_id"] = tid
    mc = get_success_data(api_client.create_marketing_commitment(did, mid, payload, MARKETING))
    return get_success_data(
        api_client.commit_marketing_commitment(did, mid, mc["id"], MARKETING)
    )


# ---------------------------------------------------------------------------
# Tier 3: zone clearance helpers
# ---------------------------------------------------------------------------

def setup_upheld_zone_clearance(did, mid, fid, tid, radius_km=5.0,
                                effective_from_utc="2026-06-01T00:00:00Z",
                                effective_until_utc="2026-06-30T00:00:00Z"):
    """Grant a zone clearance, challenge it as an Exhibitor (a different user
    from the granted theatre, per PRD §3.9), and rule it UPHELD.
    Returns the UPHELD ZoneClearance."""
    zc = get_success_data(api_client.create_zone_clearance(
        did, mid,
        create_zone_clearance_payload(
            fid, tid,
            clearance_radius_km=radius_km,
            effective_from_utc=effective_from_utc,
            effective_until_utc=effective_until_utc,
        ),
        BOOKER,
    ))
    get_success_data(api_client.challenge_zone_clearance(did, mid, zc["id"], EXHIBITOR))
    return get_success_data(
        api_client.rule_zone_clearance(did, mid, zc["id"], {"ruling": "UPHELD"}, BOOKER)
    )


# ---------------------------------------------------------------------------
# Tier 5: ancillary handoff terminal states
# ---------------------------------------------------------------------------

def setup_ancillary_released_film(distributor_name="Distro Co"):
    """Film walked to ANCILLARY_RELEASED: open release (LIMITED, no screen
    gate), request handoff once the clock is within seven days of the
    theatrical window end, schedule an SVOD window past the window end, then
    advance the clock so the handoff fires (PRD §3.9).
    Returns dict(distributor, film, window)."""
    distributor = setup_distributor(name=distributor_name)
    did = distributor["id"]
    film = setup_film(did, target_release_date="2026-05-01T00:00:00Z")
    fid = film["id"]
    film = get_success_data(api_client.open_release(
        did, fid, {"expected_film_version": film["version"]}, BOOKER
    ))
    # Theatrical window ends 2026-05-01 + 90 days = 2026-07-30; a handoff may
    # be requested once the clock reaches seven days before the window end.
    get_success_data(api_client.set_current_utc({"to_iso8601": "2026-07-24T00:00:00Z"}, ADMIN))
    film = get_success_data(api_client.request_ancillary_handoff(did, fid, BOOKER))
    assert film["lifecycle_status"] == "ANCILLARY_PENDING", (
        f"Setup failed: expected ANCILLARY_PENDING, got {film['lifecycle_status']}"
    )
    window = get_success_data(api_client.create_ancillary_window(
        did, fid,
        create_ancillary_window_payload(
            window_kind="SVOD", scheduled_start_utc="2026-08-01T00:00:00Z"
        ),
        BOOKER,
    ))
    get_success_data(api_client.set_current_utc({"to_iso8601": "2026-08-01T00:00:00Z"}, ADMIN))
    film = get_success_data(api_client.get_film(did, fid, AUDITOR))
    assert film["lifecycle_status"] == "ANCILLARY_RELEASED", (
        f"Setup failed: expected ANCILLARY_RELEASED, got {film['lifecycle_status']}"
    )
    return {"distributor": distributor, "film": film, "window": window}
