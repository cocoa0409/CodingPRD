"""
Validation-priority tests (PRD §2.7).

Each test sets up two simultaneously-failing conditions and pins the
specific error_id that PRD §2.7's priority order requires the implementation
to surface.
"""

from __future__ import annotations

import pytest

from test_helpers import (
    ADMIN_HEADERS,
    advance_clock_to,
    api_client,
    borrow_for,
    create_cabinet,
    create_device,
    create_location_partner,
    create_pricing_plan,
    create_user,
    deposit,
    heartbeat,
    iso_add_hours,
    make_user_headers,
    setup_borrow_environment,
    setup_funded_user,
    setup_pricing_plans,
    topup_wallet,
    validate_error,
)


# ---------------------------------------------------------------------------
# Priority 6 (DUPLICATE_RENTAL) beats priority 13 (PRICING_NOT_CONFIGURED)
# ---------------------------------------------------------------------------


def test_state_beats_business_referential_on_borrow(api):
    """PRD §2.7: priority 6 (state) fires before priority 13
    (business_referential). When user already has an ACTIVE rental AND target
    cabinet's city has no PricingPlan, the state failure surfaces first.

    PRD §2.7: "Risk-control checks (priorities 14 and 15) fire after pricing-
    plan existence (priority 13) but before the fiscal checks (priorities 16
    and 17), so a refund-abuse user without a pricing plan first sees
    ERR_PRICING_NOT_CONFIGURED, then ERR_REFUND_LIMIT_EXCEEDED ..." which
    pins the relative ordering (priority 13 < 14 < 15 < 16 < 17) and by
    extension the headline ordering 5 < 6 < ... < 13.
    """
    setup_pricing_plans(["BJ"])  # SH plan deliberately absent
    partner = create_location_partner()
    cab_bj = create_cabinet(partner["id"], city_code="BJ", model="SLOT_8")
    cab_sh = create_cabinet(partner["id"], city_code="SH", model="SLOT_8")
    advance_clock_to("2026-01-01T10:00:00Z")
    heartbeat(cab_bj["id"], "2026-01-01T10:00:00Z")
    heartbeat(cab_sh["id"], "2026-01-01T10:00:00Z")
    create_device(cab_bj["id"], 0, battery_level=80)
    create_device(cab_sh["id"], 0, battery_level=80)
    user = setup_funded_user()
    # First borrow at BJ — succeeds.
    borrow_for(user, cab_bj["id"])
    # Second borrow at SH — both ERR_DUPLICATE_RENTAL (priority 6) AND
    # ERR_PRICING_NOT_CONFIGURED (priority 13) would fail. PRD §2.7 says
    # the lower-priority-number error wins → ERR_DUPLICATE_RENTAL.
    res = api.create_rental(
        {"cabinet_id": cab_sh["id"]}, make_user_headers(user["id"])
    )
    validate_error(res, "ERR_DUPLICATE_RENTAL")


# ---------------------------------------------------------------------------
# Priority 8 (CABINET_OFFLINE) beats priority 10 (NO_AVAILABLE_DEVICE)
# ---------------------------------------------------------------------------


def test_business_safety_beats_business_constraint_on_borrow(api):
    """PRD §2.7: priority 8 (business_safety: ERR_CABINET_OFFLINE) fires
    before priority 10 (business_constraint: ERR_NO_AVAILABLE_DEVICE).
    """
    setup_pricing_plans(["BJ"])
    partner = create_location_partner()
    cabinet = create_cabinet(partner["id"], city_code="BJ", model="SLOT_8")
    # Heartbeat 2 hours stale → cabinet OFFLINE at clock=10:00.
    advance_clock_to("2026-01-01T10:00:00Z")
    heartbeat(cabinet["id"], "2026-01-01T08:00:00Z")
    create_device(cabinet["id"], 0, battery_level=10)  # below MIN_BORROW_BATTERY
    user = setup_funded_user()
    res = api.create_rental(
        {"cabinet_id": cabinet["id"]}, make_user_headers(user["id"])
    )
    validate_error(res, "ERR_CABINET_OFFLINE")


# ---------------------------------------------------------------------------
# Priority 13 < 14 < 15 < 16 < 17 — explicit cascade per PRD §2.7
# ---------------------------------------------------------------------------


def test_pricing_not_configured_beats_refund_limit(api):
    """PRD §2.7: "a refund-abuse user without a pricing plan first sees
    ERR_PRICING_NOT_CONFIGURED."
    """
    from test_helpers import setup_user_with_refund_count

    # Build user with 5 refunds (so refund-limit gate would fire).
    env = setup_user_with_refund_count(5)
    # Now create a cabinet in a city with NO pricing plan.
    partner_extra = create_location_partner()
    cab_unconf = create_cabinet(partner_extra["id"], city_code="SH", model="SLOT_8")
    advance_clock_to(env["clock"])
    heartbeat(cab_unconf["id"], env["clock"])
    create_device(cab_unconf["id"], 0, battery_level=80)
    res = api.create_rental(
        {"cabinet_id": cab_unconf["id"]}, make_user_headers(env["user"]["id"])
    )
    validate_error(res, "ERR_PRICING_NOT_CONFIGURED")


# ---------------------------------------------------------------------------
# Priority 1 (UNAUTHENTICATED) beats priority 4 (INVALID_INPUT)
# ---------------------------------------------------------------------------


def test_unauthenticated_beats_invalid_input(api):
    """PRD §2.7 priority 1: auth check fires before any body validation,
    so an entirely missing-header request never reaches the body check.
    """
    res = api.create_pricing_plan(
        {"city_code": "INVALID", "hourly_rate": -1, "daily_cap": -1, "free_minutes": -1, "cross_city_surcharge": -1},
        {},
    )
    validate_error(res, "ERR_UNAUTHENTICATED")


# ---------------------------------------------------------------------------
# Priority 2 (FORBIDDEN) beats priority 4 (INVALID_INPUT)
# ---------------------------------------------------------------------------


def test_forbidden_role_beats_invalid_input(api, user_headers_placeholder):
    """PRD §2.7 priority 2: role-permission fires before body shape check.

    A User submits a malformed body to the Admin-only POST /cabinets — they
    must see ERR_FORBIDDEN, not ERR_INVALID_INPUT.
    """
    res = api.create_cabinet(
        {"cabinet_code": "C1", "city_code": "MARS"},  # malformed
        user_headers_placeholder,
    )
    validate_error(res, "ERR_FORBIDDEN")


# ---------------------------------------------------------------------------
# Priority 3 (NOT_FOUND) beats priority 5 (INVALID_STATE)
# ---------------------------------------------------------------------------


def test_not_found_beats_invalid_state_on_assign(api, operator_headers):
    """PRD §2.7 priority 3: existence check beats state check. A non-existent
    ticket id must surface ERR_NOT_FOUND, not ERR_INVALID_STATE.
    """
    from test_helpers import NON_EXISTENT_UUID

    res = api.assign_ticket(NON_EXISTENT_UUID, operator_headers)
    validate_error(res, "ERR_NOT_FOUND")
