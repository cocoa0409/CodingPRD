"""Rate resets: periodic cap, lifetime bound clamping, silent clamping.

Covers PRD §3.5 (RateReset computation, periodic-then-lifetime clamp
order, current_rate_bps update side effect) and §3.5 state-based
rejections (PENDING / CLOSED).
"""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    assert_rate_reset,
    assert_version_incremented_by_one,
    create_rate_reset_payload,
    get_heloc,
    post_rate_reset,
    setup_active_heloc,
    setup_heloc_closed_no_balance,
    setup_pending_heloc,
    validate_error,
    validate_success,
)


# ===========================================================================
# §3.5 RateReset success path
# ===========================================================================
class TestRateResetSuccess:

    def test_reset_no_clamping_updates_current_rate(
        self, api, servicer_headers,
    ):
        """PRD §3.5: "The requested_rate_bps is the supplied
        prime_rate_bps plus the HELOC's margin_bps, with no clamping."
        PRD §3.5: "The resulting applied_rate_bps becomes the HELOC's
        new current_rate_bps".
        """
        _, _, _, heloc = setup_active_heloc(
            margin_bps=300,
            periodic_cap_bps=500,
            lifetime_cap_bps=2500,
            lifetime_floor_bps=100,
            prime_rate_bps_at_origination=500,  # → current=800
        )
        before_version = heloc["version"]
        # New prime=700 → requested=1000, delta=200 < 500 (no
        # periodic cap), within lifetime bounds → applied=1000.
        resp = api.create_rate_reset(
            heloc["id"],
            create_rate_reset_payload(prime_rate_bps=700),
            servicer_headers,
        )
        reset = validate_success(resp, 201)
        assert_rate_reset(reset)
        assert reset["prime_rate_bps"] == 700
        assert reset["requested_rate_bps"] == 1000
        assert reset["applied_rate_bps"] == 1000

        h = get_heloc(heloc["id"])
        assert h["current_rate_bps"] == 1000
        assert_version_incremented_by_one(h, heloc)


# ===========================================================================
# §3.5 Periodic cap clamping (delta > periodic_cap_bps)
# ===========================================================================
class TestPeriodicCapClamp:

    def test_periodic_cap_clamps_upward_move(
        self, api, servicer_headers,
    ):
        """PRD §3.5: "the difference between requested_rate_bps and the
        HELOC's current_rate_bps immediately before the reset is
        compared to periodic_cap_bps; if the difference is strictly
        greater than periodic_cap_bps, the periodic-clamped value is
        current_rate_bps + periodic_cap_bps".
        """
        _, _, _, heloc = setup_active_heloc(
            margin_bps=300,
            periodic_cap_bps=200,
            lifetime_cap_bps=2500,
            lifetime_floor_bps=100,
            prime_rate_bps_at_origination=500,  # → current=800
        )
        # prime=1500 → requested=1800. delta = 1800-800 = 1000 > 200.
        # periodic_clamped = 800 + 200 = 1000. Within lifetime →
        # applied = 1000.
        resp = api.create_rate_reset(
            heloc["id"],
            create_rate_reset_payload(prime_rate_bps=1500),
            servicer_headers,
        )
        reset = validate_success(resp, 201)
        assert reset["requested_rate_bps"] == 1800
        assert reset["applied_rate_bps"] == 1000
        h = get_heloc(heloc["id"])
        assert h["current_rate_bps"] == 1000

    def test_periodic_cap_clamps_downward_move(
        self, api, servicer_headers,
    ):
        """PRD §3.5: "if the difference is strictly less than the
        negative of periodic_cap_bps, the periodic-clamped value is
        current_rate_bps - periodic_cap_bps".
        """
        _, _, _, heloc = setup_active_heloc(
            margin_bps=300,
            periodic_cap_bps=200,
            lifetime_cap_bps=2500,
            lifetime_floor_bps=100,
            prime_rate_bps_at_origination=500,  # → current=800
        )
        # prime=0 → requested=300. delta = 300-800 = -500 < -200.
        # periodic_clamped = 800 - 200 = 600. Within bounds.
        resp = api.create_rate_reset(
            heloc["id"],
            create_rate_reset_payload(prime_rate_bps=0),
            servicer_headers,
        )
        reset = validate_success(resp, 201)
        assert reset["requested_rate_bps"] == 300
        assert reset["applied_rate_bps"] == 600
        h = get_heloc(heloc["id"])
        assert h["current_rate_bps"] == 600

    def test_periodic_cap_exact_delta_not_clamped(
        self, api, servicer_headers,
    ):
        """PRD §3.5: "if the difference is strictly greater than
        periodic_cap_bps, the periodic-clamped value is
        current_rate_bps + periodic_cap_bps; ... otherwise the
        periodic-clamped value is exactly the requested_rate_bps."

        delta == cap (not strictly greater) → no clamping.
        """
        _, _, _, heloc = setup_active_heloc(
            margin_bps=300,
            periodic_cap_bps=200,
            lifetime_cap_bps=2500,
            lifetime_floor_bps=100,
            prime_rate_bps_at_origination=500,  # → current=800
        )
        # prime=700 → requested=1000. delta = 1000-800 = 200 ==
        # cap. Not strictly greater → unclamped.
        resp = api.create_rate_reset(
            heloc["id"],
            create_rate_reset_payload(prime_rate_bps=700),
            servicer_headers,
        )
        reset = validate_success(resp, 201)
        assert reset["applied_rate_bps"] == 1000


# ===========================================================================
# §3.5 Lifetime cap & floor clamping
# ===========================================================================
class TestLifetimeBoundClamp:

    def test_lifetime_cap_caps_upward_after_periodic(
        self, api, servicer_headers,
    ):
        """PRD §3.5: "The second clamp is the lifetime bound: the
        periodic-clamped value is then bounded below by
        lifetime_floor_bps and above by lifetime_cap_bps to produce
        applied_rate_bps."

        With prime=2000, requested=2200; periodic-clamped=min(2000+300,
        2200)=2200 (delta 1200 > 300 → clamped to 2100). Then lifetime
        cap = 2100 → applied=2100.
        """
        _, _, _, heloc = setup_active_heloc(
            margin_bps=200,
            periodic_cap_bps=300,
            lifetime_cap_bps=2100,
            lifetime_floor_bps=100,
            prime_rate_bps_at_origination=1800,
            # initial_rate = clamp(1800+200, 100, 2100) = 2000
        )
        assert heloc["current_rate_bps"] == 2000
        resp = api.create_rate_reset(
            heloc["id"],
            create_rate_reset_payload(prime_rate_bps=2000),
            servicer_headers,
        )
        reset = validate_success(resp, 201)
        # requested = 2000+200=2200; periodic_clamped = min(2000+300,
        # 2200) = 2200 (delta 200 not > 300); lifetime → 2100.
        assert reset["requested_rate_bps"] == 2200
        assert reset["applied_rate_bps"] == 2100


# ===========================================================================
# §3.5 Silent clamping, no validation error
# ===========================================================================
class TestSilentClamping:

    def test_clamping_returns_201_not_validation_error(
        self, api, servicer_headers,
    ):
        """PRD §3.5: "The clamping is silent: if the periodic or
        lifetime bounds were active, the persisted
        RateReset.applied_rate_bps will simply differ from the
        requested_rate_bps, and no validation error is raised against
        the request — the reset still succeeds and the difference is
        the audit trail."
        """
        _, _, _, heloc = setup_active_heloc(
            margin_bps=300,
            periodic_cap_bps=200,
            lifetime_cap_bps=2000,
            lifetime_floor_bps=100,
            prime_rate_bps_at_origination=500,
        )
        # prime=2500 → requested=2800; periodic_clamped=1000; lifetime
        # → 1000.
        resp = api.create_rate_reset(
            heloc["id"],
            create_rate_reset_payload(prime_rate_bps=2500),
            servicer_headers,
        )
        assert resp.status_code == 201
        reset = validate_success(resp, 201)
        assert reset["requested_rate_bps"] != reset["applied_rate_bps"]


# ===========================================================================
# §3.5 State gates
# ===========================================================================
class TestRateResetStateGates:

    def test_rate_reset_on_pending_rejected(
        self, api, servicer_headers,
    ):
        """PRD §3.5: "Rate resets are accepted while the HELOC's
        status is in DRAW, REPAY, or DEFAULT; attempts while the
        HELOC is in PENDING or CLOSED are rejected with
        ERR_INVALID_STATE".
        """
        _, _, _, heloc = setup_pending_heloc()
        resp = api.create_rate_reset(
            heloc["id"],
            create_rate_reset_payload(prime_rate_bps=500),
            servicer_headers,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)

    def test_rate_reset_on_closed_returns_heloc_closed(
        self, api, servicer_headers,
    ):
        """PRD §3.5: "an attempt while CLOSED returns the more
        specific ERR_HELOC_CLOSED".
        """
        _, _, _, heloc = setup_heloc_closed_no_balance()
        resp = api.create_rate_reset(
            heloc["id"],
            create_rate_reset_payload(prime_rate_bps=500),
            servicer_headers,
        )
        validate_error(resp, ApiErrorId.ERR_HELOC_CLOSED.value)
