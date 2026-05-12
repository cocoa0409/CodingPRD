"""Site creation, logical-clock advance, sweep tick, sla_breached recompute."""
from __future__ import annotations

import pytest

from test_helpers import (
    DEFAULT_CLOCK_NOW_ISO,
    SLA_MINUTES,
    advance_clock,
    advance_clock_payload,
    api_client,
    assert_site,
    create_ad_hoc_work_order,
    create_site,
    create_site_payload,
    parse_iso,
    run_sweep,
    setup_full_workorder_scenario,
    setup_sla_breach_at_boundary,
    validate_error,
    validate_success,
)


# ---------------------------------------------------------------------------
# 3.1 — site creation initializes clock and sweep counter
# ---------------------------------------------------------------------------
def test_create_site_initializes_clock_and_sweep_index(api,
                                                       site_manager_headers):
    """PRD §3.1: 'The newly created site has clock_now set to
    2026-01-01T00:00:00.000Z and sweep_run_index set to 0.'
    """
    res = api.create_site(create_site_payload(), site_manager_headers)
    site = validate_success(res, expected_status=201)
    assert_site(site)
    assert site["clock_now"] == DEFAULT_CLOCK_NOW_ISO
    assert site["sweep_run_index"] == 0


# ---------------------------------------------------------------------------
# 3.1 — clock advance
# ---------------------------------------------------------------------------
def test_clock_advance_moves_clock(api, site_manager_headers):
    """PRD §3.1: 'the only way time advances is through the test-driving
    capability that adds a strictly positive seconds value to clock_now.'
    """
    from datetime import timedelta
    site = create_site()
    res = api.advance_clock(site["id"], advance_clock_payload(60),
                             site_manager_headers)
    after = validate_success(res, expected_status=200)
    expected = parse_iso(DEFAULT_CLOCK_NOW_ISO) + timedelta(seconds=60)
    assert parse_iso(after["clock_now"]) == expected


def test_clock_advance_does_not_increment_sweep_index(api,
                                                      site_manager_headers):
    """PRD §3.1: 'The clock-advance capability does not by itself trigger
    any plan generation or SLA recomputation — it only moves the clock.'
    """
    site = create_site()
    res = api.advance_clock(site["id"], advance_clock_payload(120),
                             site_manager_headers)
    after = validate_success(res, expected_status=200)
    assert after["sweep_run_index"] == 0


# ---------------------------------------------------------------------------
# 3.1 — sweep tick increments counter
# ---------------------------------------------------------------------------
def test_sweep_tick_increments_index(api, site_manager_headers):
    """PRD §3.1: 'Each invocation increments sweep_run_index by one'."""
    site = create_site()
    res = api.run_sweep(site["id"], site_manager_headers)
    after = validate_success(res, expected_status=200)
    assert after["sweep_run_index"] == 1
    res2 = api.run_sweep(site["id"], site_manager_headers)
    assert validate_success(res2, expected_status=200)["sweep_run_index"] == 2


# ---------------------------------------------------------------------------
# 3.1 + 3.5 — sla_breached strict-greater boundary on sweep
#   (also covers difficulty-design rule_id=boundary_precision_check /
#    sla_breach_strict_greater_than)
# ---------------------------------------------------------------------------
def test_sla_not_breached_at_exact_due_at(api, site_manager_headers):
    """PRD §3.1 / §3.5: 'A work order's sla_breached flag is true exactly
    when the site clock is strictly greater than its sla_due_at and its
    status is not in COMPLETED, CLOSED, or CANCELLED; otherwise it is
    false.'

    Claim: clock == sla_due_at → sla_breached false.
    # difficulty: boundary_precision_check/sla_breach_strict_greater_than
    """
    bag = setup_sla_breach_at_boundary()
    site_id = bag["site"]["id"]
    wo = bag["work_order"]
    sla_seconds = SLA_MINUTES["P1"] * 60  # 14400
    advance_clock(site_id, sla_seconds)
    run_sweep(site_id)
    res = api.get_work_order(site_id, wo["id"], site_manager_headers)
    refreshed = validate_success(res, expected_status=200)
    assert refreshed["sla_breached"] is False, \
        "PRD §3.5: sla_breached requires strict > on clock vs sla_due_at"


def test_sla_breached_one_second_after_due_at(api, site_manager_headers):
    """PRD §3.1 / §3.5: 'A work order's sla_breached flag is true exactly
    when the site clock is strictly greater than its sla_due_at and its
    status is not in COMPLETED, CLOSED, or CANCELLED; otherwise it is
    false.'

    Claim: clock = sla_due_at + 1 second → sla_breached true.
    # difficulty: boundary_precision_check/sla_breach_strict_greater_than
    """
    bag = setup_sla_breach_at_boundary()
    site_id = bag["site"]["id"]
    wo = bag["work_order"]
    sla_seconds = SLA_MINUTES["P1"] * 60
    advance_clock(site_id, sla_seconds + 1)
    run_sweep(site_id)
    res = api.get_work_order(site_id, wo["id"], site_manager_headers)
    refreshed = validate_success(res, expected_status=200)
    assert refreshed["sla_breached"] is True, \
        "PRD §3.5: clock > sla_due_at on a non-terminal WO breaches SLA"
