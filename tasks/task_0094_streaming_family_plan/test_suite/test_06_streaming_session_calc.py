"""Stream-session computations and side effects: ad-break counting (ad-free vs
tiered, cadence floor boundary), watch-minute attribution (same-day and
midnight-cross), the stop side effects, the initial ACTIVE state, and the
immediate counter visibility.

Translates Difficulty/dual_variant_calc (watch minutes),
Difficulty/combinatorial_formula + Difficulty/boundary_precision_check (ad
breaks), and Corner/calculations + Corner/endpoints + Corner/state_machines +
Corner/consistency_model instances.
"""
from test_helpers import (
    make_owner_headers,
    make_profile_headers,
    validate_success,
    validate_error,
    ApiErrorId,
)
import test_helpers as h


def test_ad_break_count_tiered_on_ad_supported_plan(api):
    """PRD §3.6: "On an ad-supported plan, the session earns one pre-roll break
    before playback plus one mid-roll break for every full 30 minutes of the
    title's runtime_minutes — that is, one plus the runtime divided by 30 and
    rounded down to a whole number."

    90-min title on an ad-supported plan: 1 + floor(90/30) = 4.

    Design: Difficulty/combinatorial_formula/ad_break_tiered_nonlinear_mode_a
    """
    plan = h.create_ad_supported_plan()
    title = h.create_title(name="Movie90", maturity_rating="R", runtime_minutes=90, license_size_mb=500)
    h.set_clock("2026-06-05T12:00:00Z", run_sweeps=False)
    account = h.create_account(plan["id"], owner_email="owner3@x.com", billing_anchor_day=5)
    profile = h.create_profile(account["id"], display_name="Dad", kind="ADULT")
    device = h.create_device(account["id"], device_label="TV1", platform="TV", supports_hd=False)

    resp = api.create_stream_session(
        {"profile_id": profile["id"], "device_id": device["id"], "title_id": title["id"]},
        make_profile_headers(profile["id"]),
    )
    data = validate_success(resp, 201)
    assert data["ad_breaks_served"] == 4


def test_ad_cadence_floor_boundary_90_vs_89(api):
    """PRD §3.6: "A runtime of exactly a multiple of 30 yields that many
    mid-rolls; one minute short of a multiple yields one fewer."

    runtime 90 (=3*30) => 1 + 3 = 4 ad breaks; runtime 89 => 1 + 2 = 3.

    Design: Difficulty/boundary_precision_check/ad_cadence_floor_boundary_90_vs_89
    """
    plan = h.create_ad_supported_plan(concurrent_stream_cap=4)
    t90 = h.create_title(name="T90", maturity_rating="R", runtime_minutes=90, license_size_mb=500)
    t89 = h.create_title(name="T89", maturity_rating="R", runtime_minutes=89, license_size_mb=500)
    account = h.create_account(plan["id"], owner_email="owner11@x.com")
    profile = h.create_profile(account["id"], display_name="Dad", kind="ADULT")
    dev1 = h.create_device(account["id"], device_label="TV1", platform="TV", supports_hd=False)
    dev2 = h.create_device(account["id"], device_label="TV2", platform="TV", supports_hd=False)

    r90 = api.create_stream_session(
        {"profile_id": profile["id"], "device_id": dev1["id"], "title_id": t90["id"]},
        make_profile_headers(profile["id"]),
    )
    assert validate_success(r90, 201)["ad_breaks_served"] == 4

    r89 = api.create_stream_session(
        {"profile_id": profile["id"], "device_id": dev2["id"], "title_id": t89["id"]},
        make_profile_headers(profile["id"]),
    )
    assert validate_success(r89, 201)["ad_breaks_served"] == 3


def test_ad_free_plan_serves_zero_ads(api):
    """PRD §3.6: "On any plan whose ad_free flag is true, ad_breaks_served is 0
    regardless of runtime."

    Design: Corner/calculations/ad_free_plan_zero_ads
    """
    plan = h.create_ad_free_plan()
    title = h.create_title(name="Long", maturity_rating="PG", runtime_minutes=120, license_size_mb=700)
    account = h.create_account(plan["id"], owner_email="adfree@x.com")
    profile = h.create_profile(account["id"], display_name="P", kind="ADULT")
    device = h.create_device(account["id"], device_label="TV", platform="TV", supports_hd=False)

    resp = api.create_stream_session(
        {"profile_id": profile["id"], "device_id": device["id"], "title_id": title["id"]},
        make_profile_headers(profile["id"]),
    )
    assert validate_success(resp, 201)["ad_breaks_served"] == 0


def test_watch_minutes_midnight_cross_attribution(api):
    """PRD §3.6: "If the stop falls after a UTC-midnight rollover — the current
    minute-of-day is below started_at_min — the elapsed time is 1440 minus
    started_at_min, plus the current minute-of-day; a session begun at 23:50
    (minute 1430) and stopped at 00:10 (minute 10) thus elapses 20 minutes, never
    a negative number." PRD §3.6: minutes_watched "is folded into the profile's
    running total".

    Design: Difficulty/dual_variant_calc/watch_minutes_midnight_cross_vs_naive_on_profile
    """
    plan = h.create_plan(monthly_fee_cents=1000)
    title = h.create_title(name="Movie120", maturity_rating="PG", runtime_minutes=120, license_size_mb=700)
    h.set_clock("2026-06-10T23:50:00Z", run_sweeps=False)
    account = h.create_account(plan["id"], owner_email="owner2@x.com", billing_anchor_day=10)
    profile = h.create_profile(account["id"], display_name="Adult", kind="ADULT")
    device = h.create_device(account["id"], device_label="TV1", platform="TV", supports_hd=True)
    session = h.start_stream(profile["id"], device["id"], title["id"])
    # No midnight sweep, so daily usage is not reset.
    h.set_clock("2026-06-11T00:10:00Z", run_sweeps=False)

    stop = api.stop_stream_session(session["id"], make_profile_headers(profile["id"]))
    stopped = validate_success(stop, 200)
    assert stopped["minutes_watched"] == 20

    prof = h.fetch_profile(account["id"], profile["id"])
    assert prof["daily_watch_minutes_used"] == 20


def test_stop_session_decrements_count_and_folds_minutes(api):
    """PRD §3.6: stopping a session "computes the session's minutes_watched, folds
    that figure into the profile's daily_watch_minutes_used, and decrements
    active_stream_count by one." PRD §3.6: same-day elapsed "is the current
    minute-of-day minus started_at_min" — 09:00 to 09:45 is 45 minutes.

    Design: Corner/endpoints/stop_session_decrements_active_count_and_folds_minutes
    """
    plan = h.create_plan(monthly_fee_cents=1000)
    title = h.create_title(name="Long", maturity_rating="PG", runtime_minutes=120, license_size_mb=700)
    h.set_clock("2026-06-28T09:00:00Z", run_sweeps=False)
    account = h.create_account(plan["id"], owner_email="stop@x.com", billing_anchor_day=28)
    profile = h.create_profile(account["id"], display_name="P", kind="ADULT")
    device = h.create_device(account["id"], device_label="TV", platform="TV", supports_hd=True)
    session = h.start_stream(profile["id"], device["id"], title["id"])
    h.set_clock("2026-06-28T09:45:00Z", run_sweeps=False)

    stop = api.stop_stream_session(session["id"], make_profile_headers(profile["id"]))
    assert validate_success(stop, 200)["minutes_watched"] == 45

    acct = h.fetch_account(account["id"])
    assert acct["active_stream_count"] == 0
    prof = h.fetch_profile(account["id"], profile["id"])
    assert prof["daily_watch_minutes_used"] == 45


def test_stream_session_initial_state_active(api):
    """PRD §3.6: "When every gate passes, a new session is created in ACTIVE
    status".

    Design: Corner/state_machines/stream_session_initial_state_active
    """
    plan = h.create_plan(monthly_fee_cents=1000)
    title = h.create_title(name="Show", maturity_rating="PG", runtime_minutes=50, license_size_mb=300)
    account = h.create_account(plan["id"], owner_email="init@x.com")
    profile = h.create_profile(account["id"], display_name="P", kind="ADULT")
    device = h.create_device(account["id"], device_label="TV", platform="TV", supports_hd=True)

    resp = api.create_stream_session(
        {"profile_id": profile["id"], "device_id": device["id"], "title_id": title["id"]},
        make_profile_headers(profile["id"]),
    )
    assert validate_success(resp, 201)["status"] == "ACTIVE"


def test_stop_already_ended_session_returns_invalid_state(api):
    """PRD §3.6: "Stopping a session drives it from ACTIVE to ENDED, may be
    requested only while it is ACTIVE".

    Design: Corner/state_machines/stop_already_ended_session_returns_invalid_state
    """
    plan = h.create_plan(monthly_fee_cents=1000)
    title = h.create_title(name="Show", maturity_rating="PG", runtime_minutes=50, license_size_mb=300)
    h.set_clock("2026-06-25T10:00:00Z", run_sweeps=False)
    account = h.create_account(plan["id"], owner_email="ended@x.com", billing_anchor_day=25)
    profile = h.create_profile(account["id"], display_name="P", kind="ADULT")
    device = h.create_device(account["id"], device_label="TV", platform="TV", supports_hd=True)
    session = h.start_stream(profile["id"], device["id"], title["id"])
    h.stop_stream(profile["id"], session["id"])

    resp = api.stop_stream_session(session["id"], make_profile_headers(profile["id"]))
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value, 409)


def test_active_stream_count_immediately_visible(api):
    """PRD §2.5: "active_stream_count, the number of its StreamSessions presently
    in ACTIVE state ... Every transition that opens or closes a stream ... must
    keep its counter exactly synchronized with reality". PRD §3.6: on a started
    session "active_stream_count is incremented by one, and ad_breaks_served is
    computed for the session."

    Design: Corner/consistency_model/immediate_visibility_active_stream_count
    """
    plan = h.create_plan(monthly_fee_cents=1000)
    title = h.create_title(name="Now", maturity_rating="PG", runtime_minutes=50, license_size_mb=300)
    h.set_clock("2026-06-30T10:00:00Z", run_sweeps=False)
    account = h.create_account(plan["id"], owner_email="imm@x.com", billing_anchor_day=28)
    profile = h.create_profile(account["id"], display_name="P", kind="ADULT")
    device = h.create_device(account["id"], device_label="TV", platform="TV", supports_hd=True)
    h.start_stream(profile["id"], device["id"], title["id"])

    acct = h.fetch_account(account["id"])
    assert acct["active_stream_count"] == 1
