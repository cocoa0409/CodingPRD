"""SLA deadline projection vs live breach evaluation (dual-variant calculation).

Translation of SCAFFOLD_DIFFICULTY_DESIGN.yaml queue A rule `dual_variant_calc`
instance `dual_variant_sla_deadline_vs_live_breach`.
"""
import pytest
from test_helpers import (
    api_client, validate_success, TEST_USERS,
)
from test_helpers import (
    create_client, create_asset, create_completed_scan, create_finding,
    reset_clock, set_clock,
)

LEAD = TEST_USERS["engagement_lead_headers"]


@pytest.fixture(autouse=True)
def _clock():
    """Each test runs against a fresh server; pin the clock to the PRD default."""
    reset_clock()
    yield


def _elite_finding_cvss_7_5():
    """ELITE client, HIGH asset, cvss 7.5 -> severity CRITICAL, SLA = +12h.

    HIGH base band escalated by HIGH criticality -> CRITICAL. CRITICAL base
    window 24h * ELITE multiplier 0.5 = 12h.
    """
    client = create_client(tier="ELITE", retainer_hours_per_period=100)
    asset = create_asset(client["id"], hostname="web-01", ip_address="10.0.0.1",
                        criticality="HIGH", exposure="EXTERNAL")
    eng, scan = create_completed_scan(client["id"], [asset["id"]])
    finding = create_finding(scan["id"], asset["id"], cvss_base=7.5, title="RCE")
    return finding


def test_sla_breach_false_before_deadline(api):
    """PRD §3.5: "The sla_breached flag, by contrast, is evaluated live against the
    logical clock on every read: it is true exactly when the clock is strictly past
    sla_due_at and the finding's status is none of REMEDIATED, RISK_ACCEPTED, or
    FALSE_POSITIVE."
    PRD §3.5: "a HIGH-criticality asset bumps it up one band only when the base band
    is MEDIUM or HIGH."

    Design: Difficulty/dual_variant_calc/dual_variant_sla_deadline_vs_live_breach
    """
    finding = _elite_finding_cvss_7_5()
    assert finding["severity"] == "CRITICAL"
    # Clock is still at the 2026-03-01 default, well before the +12h deadline.
    fetched = validate_success(api.get_finding(finding["id"], LEAD), 200)
    assert fetched["sla_breached"] is False


def test_sla_breach_flips_true_after_clock_advance_deadline_frozen(api):
    """PRD §3.5: "it is true exactly when the clock is strictly past sla_due_at and
    the finding's status is none of REMEDIATED, RISK_ACCEPTED, or FALSE_POSITIVE."
    PRD §3.5: "The deadline does not move if severity later changes — it is anchored
    to created_at."

    Design: Difficulty/dual_variant_calc/dual_variant_sla_deadline_vs_live_breach
    """
    finding = _elite_finding_cvss_7_5()
    pre = validate_success(api.get_finding(finding["id"], LEAD), 200)
    due_before = pre["sla_due_at"]
    assert pre["sla_breached"] is False

    # Advance well past the +12h deadline (default is 2026-03-01T00:00Z).
    set_clock("2026-03-05T00:00:00Z")
    post = validate_success(api.get_finding(finding["id"], LEAD), 200)
    assert post["sla_breached"] is True
    # sla_due_at is frozen against created_at — identical across both reads.
    assert post["sla_due_at"] == due_before
