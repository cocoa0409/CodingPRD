"""Second-pass coverage for every §1.8 difficulty instance — a distinct angle on
the same rule (a sibling boundary, the positive/negative counterpart, the
isolated lower-priority trigger, or a second observable facet of the same
computation/cascade/invariant). Each remains grounded in verbatim PRD prose and
uniquely derivable from it.
"""
from test_helpers import (
    make_owner_headers,
    make_profile_headers,
    make_anonymous_headers,
    validate_success,
    validate_error,
    ApiErrorId,
)
import test_helpers as h


# Rule 1: dual_variant_calc ----------------------------------------------------

def test_midperiod_upgrade_records_direction_upgrade(api):
    """PRD §3.3: a successful change "classifies the change's direction by
    comparing the two plans' monthly_fee_cents: UPGRADE when the destination costs
    more, DOWNGRADE when it costs less, and LATERAL when the fees are equal."

    Moving from a 500 plan to a 1000 plan is an UPGRADE.

    Design: Difficulty/dual_variant_calc/cycle_charge_prorated_vs_flat_on_account
    """
    s = h.setup_two_plans_with_midperiod_upgrade(
        period_open_iso="2026-09-01T00:00:00Z", day1_iso="2026-09-02T00:00:00Z",
        ad_fee=500, prem_fee=1000, initial_credit_cents=100000, billing_anchor_day=1,
    )
    assert s["plan_change"]["direction"] == "UPGRADE"


def test_watch_minutes_same_day_elapsed(api):
    """PRD §3.6: "If the stop occurs on the same UTC clock-day as the start — that
    is, the current minute-of-day is at or after the session's started_at_min —
    the elapsed time is the current minute-of-day minus started_at_min." The
    minutes_watched "is folded into the profile's running total".

    Start 10:00 (minute 600), stop 10:30 (minute 630) => 30 minutes, same day.

    Design: Difficulty/dual_variant_calc/watch_minutes_midnight_cross_vs_naive_on_profile
    """
    plan = h.create_plan(monthly_fee_cents=1000)
    title = h.create_title(name="Day", maturity_rating="PG", runtime_minutes=120, license_size_mb=700)
    h.set_clock("2026-06-10T10:00:00Z", run_sweeps=False)
    account = h.create_account(plan["id"], owner_email="sameday@x.com", billing_anchor_day=10)
    profile = h.create_profile(account["id"], display_name="Adult", kind="ADULT")
    device = h.create_device(account["id"], device_label="TV1", platform="TV", supports_hd=True)
    session = h.start_stream(profile["id"], device["id"], title["id"])
    h.set_clock("2026-06-10T10:30:00Z", run_sweeps=False)

    stopped = validate_success(api.stop_stream_session(session["id"], make_profile_headers(profile["id"])), 200)
    assert stopped["minutes_watched"] == 30
    prof = h.fetch_profile(account["id"], profile["id"])
    assert prof["daily_watch_minutes_used"] == 30


# Rule 2: combinatorial_formula -----------------------------------------------

def test_ad_break_tiered_60_minute_title(api):
    """PRD §3.6: "On an ad-supported plan, the session earns one pre-roll break
    before playback plus one mid-roll break for every full 30 minutes of the
    title's runtime_minutes — that is, one plus the runtime divided by 30 and
    rounded down to a whole number."

    60-min title => 1 + floor(60/30) = 3.

    Design: Difficulty/combinatorial_formula/ad_break_tiered_nonlinear_mode_a
    """
    plan = h.create_ad_supported_plan()
    title = h.create_title(name="Movie60", maturity_rating="R", runtime_minutes=60, license_size_mb=400)
    h.set_clock("2026-06-05T12:00:00Z", run_sweeps=False)
    account = h.create_account(plan["id"], owner_email="ad60@x.com", billing_anchor_day=5)
    profile = h.create_profile(account["id"], display_name="Dad", kind="ADULT")
    device = h.create_device(account["id"], device_label="TV1", platform="TV", supports_hd=False)

    resp = api.create_stream_session(
        {"profile_id": profile["id"], "device_id": device["id"], "title_id": title["id"]},
        make_profile_headers(profile["id"]),
    )
    assert validate_success(resp, 201)["ad_breaks_served"] == 3


def test_cycle_charge_sum_then_round_signed_adjustment(api):
    """PRD §2.6: "The proration_adjustment_cents is then that rounded
    period_charge_cents minus the current plan's monthly_fee_cents: positive when
    mid-period upgrades pushed the prorated total above one flat period of the
    final plan, negative on a net downgrade."

    period_charge 983, final plan fee 1000 => adjustment 983 - 1000 = -17.

    Design: Difficulty/combinatorial_formula/cycle_charge_sum_then_round_mode_b
    """
    s = h.setup_two_plans_with_midperiod_upgrade(
        period_open_iso="2026-10-01T00:00:00Z", day1_iso="2026-10-02T00:00:00Z",
        ad_fee=500, prem_fee=1000, initial_credit_cents=50000, billing_anchor_day=1,
    )
    acct = h.fetch_account(s["account"]["id"])
    assert acct["proration_adjustment_cents"] == -17


# Rule 3: non_linear_state_machine --------------------------------------------

def test_suspend_then_reactivate_increments_version_each_leg(api):
    """PRD §3.2: suspension "resets active_stream_count to 0 and increments the
    account's version by one." PRD §3.2: a successful reactivation "drives the
    account back from SUSPENDED to ACTIVE, and increments version by one."

    From version 1: suspend -> 2, reactivate -> 3.

    Design: Difficulty/non_linear_state_machine/account_suspend_reactivate_revert_loop
    """
    plan = h.create_plan(monthly_fee_cents=1000)
    account = h.create_account(plan["id"], owner_email="ver5@x.com", initial_credit_cents=5000)
    suspended = validate_success(api.suspend_account(
        account["id"], {"expected_account_version": account["version"]},
        make_owner_headers(account["id"])), 200)
    assert suspended["version"] == 2
    reactivated = validate_success(api.reactivate_account(
        account["id"], {"expected_account_version": suspended["version"]},
        make_owner_headers(account["id"])), 200)
    assert reactivated["version"] == 3


def test_invite_accept_commits_seat_hold(api):
    """PRD §3.8: a successful accept "commits the seat hold: the held
    hold_amount_cents stays debited from the wallet as the permanent seat fee
    rather than being returned."

    After accept, wallet stays reduced by the seat hold (does not return to the
    pre-send balance).

    Design: Difficulty/non_linear_state_machine/invite_pending_fork_divergent_branches
    """
    s = h.create_account_with_pending_invite(invitee_email="commit@x.com", initial_credit_cents=10000)
    invite = s["invite"]
    hold = invite["hold_amount_cents"]
    h.accept_invite(invite["id"], invite["token"])
    acct = h.fetch_account(s["account"]["id"])
    assert acct["wallet_credit_cents"] == 10000 - hold


# Rule 4: transitive_cascade --------------------------------------------------

def test_account_close_invoices_open_period(api):
    """PRD §3.2: the close cascade, "if billing_status is still OPEN — invoices
    the current period through the cycle-charge computation, finalizing
    period_charge_cents and debiting the wallet by the net charge." PRD §3.2:
    "the account's version is incremented by one as it moves to CLOSED."

    Design: Difficulty/transitive_cascade/account_close_depth3_cascade
    """
    plan = h.create_plan(monthly_fee_cents=1000)
    account = h.create_account(plan["id"], owner_email="closeinv@x.com", initial_credit_cents=5000)
    closed = validate_success(api.close_account(
        account["id"], {"expected_account_version": account["version"]},
        make_owner_headers(account["id"])), 200)
    assert closed["status"] == "CLOSED"
    assert closed["billing_status"] == "INVOICED"
    assert closed["wallet_credit_cents"] == 4000


def test_deregister_sets_device_deregistered_and_decrements_count(api):
    """PRD §3.5: "Deregistering a device drives it from REGISTERED to
    DEREGISTERED ... A successful deregistration decrements registered_device_count
    by one and cascades a deletion of every DOWNLOADING or READY Download licensed
    to that device".

    Design: Difficulty/transitive_cascade/deregister_depth2_cascade_frees_quota
    """
    plan = h.create_ad_free_plan(download_quota_per_profile=1)
    account = h.create_account(plan["id"], owner_email="dereg2@x.com")
    device = h.create_device(account["id"], device_label="Tab", platform="TABLET", supports_hd=False)
    before = h.fetch_account(account["id"])
    assert before["registered_device_count"] == 1

    dereg = validate_success(api.deregister_device(device["id"], make_owner_headers(account["id"])), 200)
    assert dereg["status"] == "DEREGISTERED"
    after = h.fetch_account(account["id"])
    assert after["registered_device_count"] == 0


# Rule 5: priority_pair_validation_conflict -----------------------------------

def test_daily_limit_exceeded_in_isolation(api):
    """PRD §3.6: "The daily-limit gate also applies only when a control sets a
    positive daily_watch_limit_minutes: the profile's daily_watch_minutes_used
    plus the title's runtime_minutes must be no greater than
    daily_watch_limit_minutes, and a start that would push the projected total
    past the allowance is blocked with ERR_DAILY_LIMIT_EXCEEDED."

    With only the daily-limit violated (the title is within the rating ceiling),
    the daily-limit error fires on its own.

    Design: Difficulty/priority_pair_validation_conflict/rating_safety_beats_daily_limit_temporal
    """
    plan = h.create_plan(monthly_fee_cents=1000)
    g_title = h.create_title(name="G30", maturity_rating="G", runtime_minutes=30, license_size_mb=200)
    h.set_clock("2026-06-20T06:00:00Z", run_sweeps=False)
    account = h.create_account(plan["id"], owner_email="dl-iso@x.com", billing_anchor_day=20)
    profile = h.create_profile(account["id"], display_name="Kiddo", kind="KID")
    h.set_parental_control(account["id"], profile["id"], max_rating="G",
                           daily_watch_limit_minutes=30, curfew_start_min=0, curfew_end_min=0)
    device = h.create_device(account["id"], device_label="TV", platform="TV", supports_hd=True)
    # Use 30 of 30 minutes with an in-rating G title.
    s0 = h.start_stream(profile["id"], device["id"], g_title["id"])
    h.set_clock("2026-06-20T06:30:00Z", run_sweeps=False)
    h.stop_stream(profile["id"], s0["id"])

    # A second in-rating G title would push 30 + 30 = 60 > 30.
    resp = api.create_stream_session(
        {"profile_id": profile["id"], "device_id": device["id"], "title_id": g_title["id"]},
        make_profile_headers(profile["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_DAILY_LIMIT_EXCEEDED.value, 409)


def test_insufficient_credit_on_reactivate_in_isolation(api):
    """PRD §3.2: reactivation is permitted "only when wallet_credit_cents is at
    least one period of the current plan's monthly_fee_cents — reactivation
    requires one full period of credit on hand, and falling short is rejected with
    ERR_INSUFFICIENT_CREDIT."

    A genuinely SUSPENDED account (state legal) with wallet 0 fails only the
    fiscal check, so ERR_INSUFFICIENT_CREDIT fires on its own.

    Design: Difficulty/priority_pair_validation_conflict/state_beats_fiscal_on_reactivate
    """
    plan = h.create_plan(monthly_fee_cents=1000)
    account = h.create_account(plan["id"], owner_email="cred-iso@x.com", initial_credit_cents=0)
    suspended = validate_success(api.suspend_account(
        account["id"], {"expected_account_version": account["version"]},
        make_owner_headers(account["id"])), 200)
    resp = api.reactivate_account(
        account["id"], {"expected_account_version": suspended["version"]},
        make_owner_headers(account["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_CREDIT.value, 402)


# Rule 6: boundary_precision_check --------------------------------------------

def test_ad_cadence_floor_at_first_multiple_30(api):
    """PRD §3.6: "A runtime of exactly a multiple of 30 yields that many mid-rolls;
    one minute short of a multiple yields one fewer."

    runtime 30 (=1*30) => 1 + 1 = 2 ad breaks (the first cadence multiple).

    Design: Difficulty/boundary_precision_check/ad_cadence_floor_boundary_90_vs_89
    """
    plan = h.create_ad_supported_plan()
    t30 = h.create_title(name="T30", maturity_rating="R", runtime_minutes=30, license_size_mb=300)
    account = h.create_account(plan["id"], owner_email="ad30@x.com")
    profile = h.create_profile(account["id"], display_name="Dad", kind="ADULT")
    device = h.create_device(account["id"], device_label="TV1", platform="TV", supports_hd=False)

    resp = api.create_stream_session(
        {"profile_id": profile["id"], "device_id": device["id"], "title_id": t30["id"]},
        make_profile_headers(profile["id"]),
    )
    assert validate_success(resp, 201)["ad_breaks_served"] == 2


def test_download_quota_one_allows_first_blocks_second(api):
    """PRD §3.7: "the profile's combined count of DOWNLOADING and READY downloads
    must be below the plan's download_quota_per_profile, and a profile already at
    its quota is rejected with ERR_DOWNLOAD_QUOTA_REACHED."

    quota=1: the first download succeeds (0 < 1); the second is rejected (1 < 1 is
    false) — the positive-then-negative boundary neighbor of the zero edge.

    Design: Difficulty/boundary_precision_check/download_quota_zero_empty_edge
    """
    plan = h.create_ad_supported_plan(download_quota_per_profile=1)
    ta = h.create_title(name="QA", maturity_rating="G", runtime_minutes=40, license_size_mb=250)
    tb = h.create_title(name="QB", maturity_rating="G", runtime_minutes=40, license_size_mb=250)
    account = h.create_account(plan["id"], owner_email="quota1@x.com")
    profile = h.create_profile(account["id"], display_name="P", kind="ADULT")
    device = h.create_device(account["id"], device_label="Tab", platform="TABLET", supports_hd=False)

    first = api.create_download(
        {"profile_id": profile["id"], "device_id": device["id"], "title_id": ta["id"], "quality": "SD"},
        make_profile_headers(profile["id"]),
    )
    validate_success(first, 201)
    second = api.create_download(
        {"profile_id": profile["id"], "device_id": device["id"], "title_id": tb["id"], "quality": "SD"},
        make_profile_headers(profile["id"]),
    )
    validate_error(second, ApiErrorId.ERR_DOWNLOAD_QUOTA_REACHED.value, 409)


# Rule 7: cross_entity_state_dependency ---------------------------------------

def test_stream_start_blocked_when_profile_archived(api):
    """PRD §3.6: "the profile itself must be ACTIVE ... a request against a state
    that forbids the start surfaces as ERR_INVALID_STATE." PRD §3.4: "Archiving a
    profile drives it from ACTIVE to ARCHIVED".

    A stream start against an ARCHIVED profile is rejected with ERR_INVALID_STATE
    (a different cross-entity dependency than the SUSPENDED-account case).

    Design: Difficulty/cross_entity_state_dependency/stream_start_requires_account_active
    """
    plan = h.create_plan(monthly_fee_cents=1000)
    title = h.create_title(name="Show", maturity_rating="PG", runtime_minutes=50, license_size_mb=300)
    account = h.create_account(plan["id"], owner_email="arch-stream@x.com")
    profile = h.create_profile(account["id"], display_name="P", kind="ADULT")
    device = h.create_device(account["id"], device_label="TV", platform="TV", supports_hd=True)
    h.api_client.archive_profile(profile["id"], make_owner_headers(account["id"]))

    resp = api.create_stream_session(
        {"profile_id": profile["id"], "device_id": device["id"], "title_id": title["id"]},
        make_profile_headers(profile["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value, 409)


def test_deregister_succeeds_after_session_stopped(api):
    """PRD §3.5: deregistration "is permitted only while it is REGISTERED and only
    when no ACTIVE StreamSession references it. A successful deregistration
    decrements registered_device_count by one".

    The positive counterpart: once the blocking session is stopped, deregister
    succeeds.

    Design: Difficulty/cross_entity_state_dependency/deregister_blocked_by_active_session_on_device
    """
    plan = h.create_plan(monthly_fee_cents=1000)
    title = h.create_title(name="Show", maturity_rating="PG", runtime_minutes=50, license_size_mb=300)
    h.set_clock("2026-06-21T12:00:00Z", run_sweeps=False)
    account = h.create_account(plan["id"], owner_email="dereg-ok@x.com", billing_anchor_day=21)
    profile = h.create_profile(account["id"], display_name="P", kind="ADULT")
    device = h.create_device(account["id"], device_label="TV", platform="TV", supports_hd=True)
    session = h.start_stream(profile["id"], device["id"], title["id"])
    h.set_clock("2026-06-21T12:30:00Z", run_sweeps=False)
    h.stop_stream(profile["id"], session["id"])

    resp = api.deregister_device(device["id"], make_owner_headers(account["id"]))
    assert validate_success(resp, 200)["status"] == "DEREGISTERED"


# Rule 8: resource_temporal_overlap -------------------------------------------

def test_device_start_exactly_at_interval_end_does_not_collide(api):
    """PRD §3.6: "The interval is half-open, so a session that begins exactly at
    the minute another session's interval ends does not collide".

    First session: start minute 720 on a 60-min title => interval [720,780). A
    second start at minute 780 (exactly the interval end) is allowed.

    Design: Difficulty/resource_temporal_overlap/device_single_occupancy_halfopen_span
    """
    plan = h.create_plan(monthly_fee_cents=1000, concurrent_stream_cap=4)
    title = h.create_title(name="Hour", maturity_rating="PG", runtime_minutes=60, license_size_mb=400)
    h.set_clock("2026-06-22T12:00:00Z", run_sweeps=False)
    account = h.create_account(plan["id"], owner_email="edge-end@x.com", billing_anchor_day=22)
    p1 = h.create_profile(account["id"], display_name="P1", kind="ADULT")
    p2 = h.create_profile(account["id"], display_name="P2", kind="ADULT")
    device = h.create_device(account["id"], device_label="TV", platform="TV", supports_hd=True)
    h.start_stream(p1["id"], device["id"], title["id"])
    # Advance to minute 780 (13:00) — exactly when the first interval ends.
    h.set_clock("2026-06-22T13:00:00Z", run_sweeps=False)

    resp = api.create_stream_session(
        {"profile_id": p2["id"], "device_id": device["id"], "title_id": title["id"]},
        make_profile_headers(p2["id"]),
    )
    assert validate_success(resp, 201)["status"] == "ACTIVE"


def test_stream_outside_curfew_window_succeeds(api):
    """PRD §3.6: "The curfew gate applies when the profile has a control envelope:
    if the current clock-minute falls inside the curfew window (open at
    curfew_start_min inclusive, closed at curfew_end_min exclusive, wrapping past
    midnight when the end precedes the start), the start is blocked with
    ERR_CURFEW_BLOCKED."

    With the same wrapped window [1320,1440)U[0,360), a 12:00 start (minute 720)
    is OUTSIDE the window and the start succeeds.

    Design: Difficulty/resource_temporal_overlap/curfew_window_wraps_midnight
    """
    plan = h.create_plan(monthly_fee_cents=1000)
    title = h.create_title(name="Cartoon", maturity_rating="G", runtime_minutes=30, license_size_mb=200)
    h.set_clock("2026-06-23T12:00:00Z", run_sweeps=False)
    account = h.create_account(plan["id"], owner_email="curfew-out@x.com", billing_anchor_day=23)
    profile = h.create_profile(account["id"], display_name="Kid", kind="KID")
    h.set_parental_control(account["id"], profile["id"], max_rating="G",
                           daily_watch_limit_minutes=0, curfew_start_min=1320, curfew_end_min=360)
    device = h.create_device(account["id"], device_label="TV", platform="TV", supports_hd=True)

    resp = api.create_stream_session(
        {"profile_id": profile["id"], "device_id": device["id"], "title_id": title["id"]},
        make_profile_headers(profile["id"]),
    )
    assert validate_success(resp, 201)["status"] == "ACTIVE"


# Rule 9: compensating_invariant ----------------------------------------------

def test_invite_revoke_releases_hold_conserving_wallet(api):
    """PRD §3.8: "Revoking is the owner's cancellation of a still-PENDING invite:
    it releases the hold and drives the invite to REVOKED". PRD §3.8: "An owner
    sends an invite ... and debits a per-seat hold_amount_cents as a hold against
    the account's wallet_credit_cents."

    Send debit + revoke release => wallet returns to its pre-send balance (10000)
    — the same money invariant via a different compensating action than decline.

    Design: Difficulty/compensating_invariant/invite_hold_release_conserves_wallet_money
    """
    s = h.create_account_with_pending_invite(invitee_email="revoke@x.com", initial_credit_cents=10000)
    invite = s["invite"]
    revoke = api.revoke_invite(invite["id"], make_owner_headers(s["account"]["id"]))
    validate_success(revoke, 200)
    acct = h.fetch_account(s["account"]["id"])
    assert acct["wallet_credit_cents"] == 10000


def test_download_delete_then_refill_to_cap(api):
    """PRD §3.7: "Deleting a download ... drives it to DELETED, and frees one slot
    of the profile's download quota."

    quota=2: fill to cap (2), delete one, then create one more to return to the
    cap — proving the deleted slot was conserved and reusable.

    Design: Difficulty/compensating_invariant/download_delete_conserves_profile_quota_slots
    """
    plan = h.create_ad_free_plan(download_quota_per_profile=2)
    ta = h.create_title(name="RA", maturity_rating="G", runtime_minutes=40, license_size_mb=250)
    tb = h.create_title(name="RB", maturity_rating="G", runtime_minutes=40, license_size_mb=250)
    tc = h.create_title(name="RC", maturity_rating="G", runtime_minutes=40, license_size_mb=250)
    account = h.create_account(plan["id"], owner_email="refill@x.com")
    profile = h.create_profile(account["id"], display_name="P", kind="ADULT")
    device = h.create_device(account["id"], device_label="Tab", platform="TABLET", supports_hd=False)
    dl_a = h.create_download(profile["id"], device["id"], ta["id"], quality="SD")
    h.create_download(profile["id"], device["id"], tb["id"], quality="SD")

    deleted = validate_success(api.delete_download(dl_a["id"], make_profile_headers(profile["id"])), 200)
    assert deleted["status"] == "DELETED"

    refill = api.create_download(
        {"profile_id": profile["id"], "device_id": device["id"], "title_id": tc["id"], "quality": "SD"},
        make_profile_headers(profile["id"]),
    )
    assert validate_success(refill, 201)["status"] == "DOWNLOADING"
