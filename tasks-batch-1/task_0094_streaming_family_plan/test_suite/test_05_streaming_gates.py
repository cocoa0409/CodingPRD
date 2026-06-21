"""The streaming gauntlet: the ordered cascade of start gates — account state,
cross-account coherence, rating, curfew, daily-limit, device single-occupancy,
and the concurrent-stream cap — plus the cross-category priority precedence.

Translates Difficulty/priority_pair_validation_conflict (rating beats limit),
Difficulty/cross_entity_state_dependency (stream needs ACTIVE account),
Difficulty/resource_temporal_overlap (device span, curfew wrap), and
Corner/validations + Corner/errors instances.
"""
from test_helpers import (
    make_owner_headers,
    make_profile_headers,
    validate_success,
    validate_error,
    ApiErrorId,
)
import test_helpers as h


def test_rating_block_beats_daily_limit_on_start(api):
    """PRD §3.10: "The streaming gates then evaluate rating (ERR_RATING_BLOCKED),
    curfew (ERR_CURFEW_BLOCKED), daily limit (ERR_DAILY_LIMIT_EXCEEDED), and
    device occupancy (ERR_DEVICE_BUSY) in that order." PRD §3.6: "a title that
    sits above the ceiling is blocked with ERR_RATING_BLOCKED."

    KID (ceiling G) with daily limit 30 and 30 used, asked to start an R-rated
    60-min title: both rating and daily-limit fail; the higher-priority rating
    gate wins with ERR_RATING_BLOCKED.

    Design: Difficulty/priority_pair_validation_conflict/rating_safety_beats_daily_limit_temporal
    """
    plan = h.create_plan(monthly_fee_cents=1000)
    r_title = h.create_title(name="RMovie", maturity_rating="R", runtime_minutes=60, license_size_mb=400)
    g_title = h.create_title(name="GShort", maturity_rating="G", runtime_minutes=30, license_size_mb=200)
    h.set_clock("2026-06-20T06:00:00Z", run_sweeps=False)
    account = h.create_account(plan["id"], owner_email="owner9@x.com", billing_anchor_day=20)
    profile = h.create_profile(account["id"], display_name="Kiddo", kind="KID")
    h.set_parental_control(account["id"], profile["id"], max_rating="G",
                           daily_watch_limit_minutes=30, curfew_start_min=0, curfew_end_min=0)
    device = h.create_device(account["id"], device_label="TV", platform="TV", supports_hd=True)
    # Consume 30 minutes with a G title (06:00 -> 06:30) so daily usage == 30.
    s0 = h.start_stream(profile["id"], device["id"], g_title["id"])
    h.set_clock("2026-06-20T06:30:00Z", run_sweeps=False)
    h.stop_stream(profile["id"], s0["id"])

    resp = api.create_stream_session(
        {"profile_id": profile["id"], "device_id": device["id"], "title_id": r_title["id"]},
        make_profile_headers(profile["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_RATING_BLOCKED.value, 403)


def test_stream_start_on_suspended_account_returns_invalid_state(api):
    """PRD §3.6: "The account that owns the profile (named by the profile's
    account_id) must be ACTIVE, the profile itself must be ACTIVE, and the device
    must be REGISTERED — a request against a state that forbids the start surfaces
    as ERR_INVALID_STATE."

    Design: Difficulty/cross_entity_state_dependency/stream_start_requires_account_active
    """
    plan = h.create_plan(monthly_fee_cents=1000)
    title = h.create_title(name="Show", maturity_rating="PG", runtime_minutes=50, license_size_mb=300)
    account = h.create_account(plan["id"], owner_email="owner13@x.com")
    profile = h.create_profile(account["id"], display_name="P", kind="ADULT")
    device = h.create_device(account["id"], device_label="TV", platform="TV", supports_hd=True)
    # Device registration mutates the Account (PRD §2.5: counter sync increments
    # version), so re-read the current version for the OCC-guarded suspend.
    current = h.fetch_account(account["id"])
    suspend = api.suspend_account(
        account["id"], {"expected_account_version": current["version"]},
        make_owner_headers(account["id"]),
    )
    assert validate_success(suspend, 200)["status"] == "SUSPENDED"

    resp = api.create_stream_session(
        {"profile_id": profile["id"], "device_id": device["id"], "title_id": title["id"]},
        make_profile_headers(profile["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value, 409)


def test_device_single_occupancy_overlap_blocks_second_stream(api):
    """PRD §3.6: "the target device must have no other ACTIVE StreamSession whose
    projected interval — from that session's started_at_min up to but not
    including started_at_min plus that session's title's runtime_minutes — covers
    the new session's start minute. The interval is half-open ... a genuine
    overlap is rejected with ERR_DEVICE_BUSY."

    First session starts at minute 720 on a 60-min title (interval [720,780)); a
    second start at minute 750 falls inside and is rejected.

    Design: Difficulty/resource_temporal_overlap/device_single_occupancy_halfopen_span
    """
    plan = h.create_plan(monthly_fee_cents=1000, concurrent_stream_cap=4)
    title = h.create_title(name="Hour", maturity_rating="PG", runtime_minutes=60, license_size_mb=400)
    h.set_clock("2026-06-22T12:00:00Z", run_sweeps=False)
    account = h.create_account(plan["id"], owner_email="owner15@x.com", billing_anchor_day=22)
    p1 = h.create_profile(account["id"], display_name="P1", kind="ADULT")
    p2 = h.create_profile(account["id"], display_name="P2", kind="ADULT")
    device = h.create_device(account["id"], device_label="TV", platform="TV", supports_hd=True)
    h.start_stream(p1["id"], device["id"], title["id"])
    h.set_clock("2026-06-22T12:30:00Z", run_sweeps=False)

    resp = api.create_stream_session(
        {"profile_id": p2["id"], "device_id": device["id"], "title_id": title["id"]},
        make_profile_headers(p2["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_DEVICE_BUSY.value, 409)


def test_curfew_window_wrapping_midnight_blocks_start(api):
    """PRD §3.6: "The curfew gate applies when the profile has a control envelope:
    if the current clock-minute falls inside the curfew window (open at
    curfew_start_min inclusive, closed at curfew_end_min exclusive, wrapping past
    midnight when the end precedes the start), the start is blocked with
    ERR_CURFEW_BLOCKED."

    curfew_start=1320 (22:00), curfew_end=360 (06:00) wraps midnight; a 02:00
    start (minute 120) is inside the wrapped window.

    Design: Difficulty/resource_temporal_overlap/curfew_window_wraps_midnight
    """
    plan = h.create_plan(monthly_fee_cents=1000)
    title = h.create_title(name="Cartoon", maturity_rating="G", runtime_minutes=30, license_size_mb=200)
    h.set_clock("2026-06-23T02:00:00Z", run_sweeps=False)
    account = h.create_account(plan["id"], owner_email="owner16@x.com", billing_anchor_day=23)
    profile = h.create_profile(account["id"], display_name="Kid", kind="KID")
    h.set_parental_control(account["id"], profile["id"], max_rating="G",
                           daily_watch_limit_minutes=0, curfew_start_min=1320, curfew_end_min=360)
    device = h.create_device(account["id"], device_label="TV", platform="TV", supports_hd=True)

    resp = api.create_stream_session(
        {"profile_id": profile["id"], "device_id": device["id"], "title_id": title["id"]},
        make_profile_headers(profile["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_CURFEW_BLOCKED.value, 409)


def test_cross_account_device_on_stream_rejected(api):
    """PRD §3.6: "Cross-account coherence is then enforced: the named device must
    belong to the same account as the profile, and a device drawn from a different
    account is rejected with ERR_CROSS_ACCOUNT_REFERENCE."

    Design: Corner/errors/cross_account_device_on_stream_rejected
    """
    plan = h.create_plan(monthly_fee_cents=1000)
    title = h.create_title(name="S", maturity_rating="PG", runtime_minutes=50, license_size_mb=300)
    acct_a = h.create_account(plan["id"], owner_email="xa@x.com")
    acct_b = h.create_account(plan["id"], owner_email="xb@x.com")
    prof_a = h.create_profile(acct_a["id"], display_name="PA", kind="ADULT")
    dev_b = h.create_device(acct_b["id"], device_label="DB", platform="TV", supports_hd=True)

    resp = api.create_stream_session(
        {"profile_id": prof_a["id"], "device_id": dev_b["id"], "title_id": title["id"]},
        make_profile_headers(prof_a["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_CROSS_ACCOUNT_REFERENCE.value, 409)


def test_concurrent_cap_reached_on_third_stream(api):
    """PRD §3.6: "Finally the concurrent-cap gate requires active_stream_count to
    be strictly below the plan's concurrent_stream_cap; an account already at its
    cap is rejected with ERR_CONCURRENT_CAP_REACHED."

    cap=2, two ACTIVE sessions on distinct devices; a third start is rejected.

    Design: Corner/validations/concurrent_cap_reached_on_third_stream
    """
    plan = h.create_plan(monthly_fee_cents=1000, concurrent_stream_cap=2)
    title = h.create_title(name="S", maturity_rating="PG", runtime_minutes=60, license_size_mb=300)
    h.set_clock("2026-06-26T08:00:00Z", run_sweeps=False)
    account = h.create_account(plan["id"], owner_email="cc@x.com", billing_anchor_day=26)
    profile = h.create_profile(account["id"], display_name="P", kind="ADULT")
    d1 = h.create_device(account["id"], device_label="D1", platform="TV", supports_hd=True)
    d2 = h.create_device(account["id"], device_label="D2", platform="TABLET", supports_hd=True)
    d3 = h.create_device(account["id"], device_label="D3", platform="MOBILE", supports_hd=True)
    h.start_stream(profile["id"], d1["id"], title["id"])
    h.start_stream(profile["id"], d2["id"], title["id"])

    resp = api.create_stream_session(
        {"profile_id": profile["id"], "device_id": d3["id"], "title_id": title["id"]},
        make_profile_headers(profile["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_CONCURRENT_CAP_REACHED.value, 409)
