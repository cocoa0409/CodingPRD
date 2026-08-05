"""Demand-response enrollment, settlement, reserved-capacity, and season rules.

Queue A: the committed-vs-performed incentive dual variant, the closed-season
14-day buffer conflict, and the conserved reserved_dr_kw invariant. Queue B:
the account-enrolled activation gate and the season-not-started performance gate.
"""
from test_helpers import (
    validate_success, validate_error, get_success_data, ApiErrorId,
)
import test_helpers.fixtures as fx
import test_helpers.factories as fac


# ===========================================================================
# Difficulty: dual_variant_calc / dr_committed_vs_performed_incentive
# ===========================================================================

def test_dr_provisional_incentive_from_committed_kw(api):
    """PRD §3.6: "Enrollment opens the record in ENROLLED, pins its
    provisional_incentive_cents as the committed_kw multiplied by
    incentive_per_kw_cents, and raises the account's reserved_dr_kw by the
    committed_kw."

    Design: Difficulty/dual_variant_calc/dr_committed_vs_performed_incentive
    """
    ctx = fx.setup_active_dr_on_enrolled_account(api, committed_kw=100, incentive_per_kw_cents=4500)
    dr = get_success_data(api.get_dr_enrollment(ctx["dr"]["id"], ctx["agent_headers"]))
    assert dr["provisional_incentive_cents"] == 450000  # 100 * 4500


def test_dr_settled_incentive_applies_shortfall_penalty(api):
    """PRD §3.6: "If performed_kw falls short of committed_kw, the shortfall in
    kilowatts (the commitment minus the performance) draws a penalty of 2,000
    cents ($20) per shortfall kilowatt: the settled incentive is the performed_kw
    times incentive_per_kw_cents, less the shortfall kilowatts times the
    $20-per-kW penalty, floored at 0 so it never goes negative."

    Design: Difficulty/dual_variant_calc/dr_committed_vs_performed_incentive
    """
    ctx = fx.setup_active_dr_on_enrolled_account(api, committed_kw=100, incentive_per_kw_cents=4500)
    fx.set_clock(api, "2026-08-15T00:00:00Z")
    get_success_data(api.record_dr_performance(ctx["dr"]["id"], {"performed_kw": 80}, ctx["ops_headers"]))
    dr = get_success_data(api.settle_dr(ctx["dr"]["id"], ctx["mgr1_headers"]))
    # 80*4500 - (100-80)*2000 = 360000 - 40000 = 320000
    assert dr["settled_incentive_cents"] == 320000
    assert dr["status"] == "SETTLED"


# ===========================================================================
# Difficulty: resource_temporal_overlap / dr_season_within_buffer_conflict_closed
# ===========================================================================

def _account_with_dr_season(api):
    agent = fx.new_agent(api)
    customer = fx.new_customer(api, agent["id"])
    account = fx.new_account(api, customer["id"], agent["id"])
    hdr = fx.make_agent_headers(agent["id"])
    dr1 = get_success_data(api.create_dr_enrollment(
        fac.create_dr_enrollment_payload(
            account["id"], program_name="Summer DR", season_start="2026-08-01T00:00:00Z",
            season_end="2026-09-30T00:00:00Z", committed_kw=50, incentive_per_kw_cents=4500),
        hdr))
    return agent, account, hdr, dr1


def test_dr_season_within_buffer_conflict_rejected(api):
    """PRD §3.6: "for every DR enrollment on the account whose status is ENROLLED,
    ACTIVE, or PERFORMED, the new season must not overlap it and must additionally
    be separated from it by at least a 14-day buffer on either side; a season that
    overlaps or falls within 14 days of an existing live season is rejected with
    ERR_DR_SEASON_CONFLICT."

    Design: Difficulty/resource_temporal_overlap/dr_season_within_buffer_conflict_closed
    """
    agent, account, hdr, dr1 = _account_with_dr_season(api)
    resp = api.create_dr_enrollment(
        fac.create_dr_enrollment_payload(
            account["id"], program_name="Fall DR", season_start="2026-10-05T00:00:00Z",
            season_end="2026-11-30T00:00:00Z", committed_kw=50, incentive_per_kw_cents=4500),
        hdr)  # 5-day gap after 2026-09-30 < 14-day buffer
    validate_error(resp, ApiErrorId.ERR_DR_SEASON_CONFLICT.value)
    first = get_success_data(api.get_dr_enrollment(dr1["id"], hdr))
    assert first["status"] == "ENROLLED"


def test_dr_season_beyond_buffer_allowed(api):
    """PRD §3.6: "the new season must not overlap it and must additionally be
    separated from it by at least a 14-day buffer on either side; a season that
    overlaps or falls within 14 days of an existing live season is rejected with
    ERR_DR_SEASON_CONFLICT."

    Design: Difficulty/resource_temporal_overlap/dr_season_within_buffer_conflict_closed
    """
    agent, account, hdr, dr1 = _account_with_dr_season(api)
    dr2 = get_success_data(api.create_dr_enrollment(
        fac.create_dr_enrollment_payload(
            account["id"], program_name="Winter DR", season_start="2026-11-01T00:00:00Z",
            season_end="2026-12-31T00:00:00Z", committed_kw=50, incentive_per_kw_cents=4500),
        hdr))  # 32-day gap after 2026-09-30 -> clears the buffer
    assert dr2["status"] == "ENROLLED"


# ===========================================================================
# Difficulty: compensating_invariant / dr_reserved_kw_conserved_on_enroll_then_withdraw
# ===========================================================================

def _fresh_account(api):
    agent = fx.new_agent(api)
    customer = fx.new_customer(api, agent["id"])
    account = fx.new_account(api, customer["id"], agent["id"])
    return agent, account, fx.make_agent_headers(agent["id"])


def test_reserved_dr_kw_conserved_across_enroll_then_withdraw(api):
    """PRD §3.6: "An agent may withdraw a DR enrollment while it is still ENROLLED
    or ACTIVE, moving it to WITHDRAWN; withdrawal releases the pledge, so the
    account's reserved_dr_kw falls back by that enrollment's committed_kw."

    Design: Difficulty/compensating_invariant/dr_reserved_kw_conserved_on_enroll_then_withdraw
    """
    agent, account, hdr = _fresh_account(api)
    assert get_success_data(api.get_account(account["id"], hdr))["reserved_dr_kw"] == 0

    dr = get_success_data(api.create_dr_enrollment(
        fac.create_dr_enrollment_payload(account["id"], committed_kw=100), hdr))
    assert get_success_data(api.get_account(account["id"], hdr))["reserved_dr_kw"] == 100

    withdrawn = get_success_data(api.withdraw_dr(dr["id"], hdr))
    assert get_success_data(api.get_account(account["id"], hdr))["reserved_dr_kw"] == 0
    assert withdrawn["status"] == "WITHDRAWN"


def test_reserved_dr_kw_rises_on_enroll(api):
    """PRD §3.6: "Enrollment opens the record in ENROLLED, pins its
    provisional_incentive_cents as the committed_kw multiplied by
    incentive_per_kw_cents, and raises the account's reserved_dr_kw by the
    committed_kw."

    Design: Difficulty/compensating_invariant/dr_reserved_kw_conserved_on_enroll_then_withdraw
    """
    agent, account, hdr = _fresh_account(api)
    dr = get_success_data(api.create_dr_enrollment(
        fac.create_dr_enrollment_payload(account["id"], committed_kw=100), hdr))
    assert dr["status"] == "ENROLLED"
    assert get_success_data(api.get_account(account["id"], hdr))["reserved_dr_kw"] == 100


# ===========================================================================
# Corner: activation gate, season-not-started gate
# ===========================================================================

def test_dr_activate_requires_account_enrolled(api):
    """PRD §3.6: "Operations activates an enrollment, advancing it ENROLLED →
    ACTIVE, but only if the account is ENROLLED — that is, the account has a live
    supply contract (else ERR_ACCOUNT_NOT_ENROLLED)."

    Design: Corner/state_machines/dr_activate_requires_account_enrolled
    """
    agent, account, hdr = _fresh_account(api)  # account PENDING_LOA, no ACTIVE contract
    dr = get_success_data(api.create_dr_enrollment(
        fac.create_dr_enrollment_payload(account["id"], committed_kw=50), hdr))
    resp = api.activate_dr(dr["id"], fx.ops_headers())
    validate_error(resp, ApiErrorId.ERR_ACCOUNT_NOT_ENROLLED.value)
    after = get_success_data(api.get_dr_enrollment(dr["id"], hdr))
    assert after["status"] == "ENROLLED"


def test_dr_record_performance_before_season_start_rejected(api):
    """PRD §3.6: "this may occur only once the logical clock has reached or passed
    season_start (else ERR_DR_SEASON_NOT_STARTED)."

    Design: Corner/state_machines/dr_record_performance_before_season_start
    """
    ctx = fx.setup_active_dr_on_enrolled_account(api)  # season_start 2026-08-01, clock default 2026-05-01
    resp = api.record_dr_performance(ctx["dr"]["id"], {"performed_kw": 80}, ctx["ops_headers"])
    validate_error(resp, ApiErrorId.ERR_DR_SEASON_NOT_STARTED.value)
    after = get_success_data(api.get_dr_enrollment(ctx["dr"]["id"], ctx["agent_headers"]))
    assert after["status"] == "ACTIVE"
