"""Retainer ledger: optimistic reservation vs actual consumption, and the
reservation-conservation invariant on cancel.

Translations of:
 - SCAFFOLD_DIFFICULTY_DESIGN.yaml queue A rule `dual_variant_calc` instance
   `dual_variant_retainer_optimistic_vs_actual`.
 - SCAFFOLD_DIFFICULTY_DESIGN.yaml queue A rule `compensating_invariant` instance
   `invariant_retainer_reservation_conserved_on_cancel`.
 - SCAFFOLD_CORNER_DESIGN.yaml queue B section `validations` instance
   `retainer_exhausted_when_estimate_exceeds_available`.
"""
import pytest
from test_helpers import (
    api_client, validate_success, validate_error, TEST_USERS,
)
from test_helpers import (
    create_client, create_asset, create_draft_engagement,
    create_authorized_engagement, get_period_ledger, queue_scan,
    create_active_engagement,
)

ADMIN = TEST_USERS["platform_admin_headers"]
LEAD = TEST_USERS["engagement_lead_headers"]
CONTACT = TEST_USERS["client_contact_headers"]


# ─── dual_variant_retainer_optimistic_vs_actual ─────────────────────────────

def test_retainer_optimistic_reservation_on_authorize(api):
    """PRD §3.3: "reserves estimated_hours on the open ledger (raising
    hours_reserved and lowering hours_available)."
    PRD §2.7: "at authorize time the full estimate is reserved up front as a
    worst-case projection."

    Design: Difficulty/dual_variant_calc/dual_variant_retainer_optimistic_vs_actual
    """
    client = create_client(tier="ESSENTIAL", retainer_hours_per_period=100)
    asset = create_asset(client["id"], hostname="db-01", criticality="MEDIUM")
    create_authorized_engagement(client["id"], [asset["id"]], estimated_hours=40)
    ledger = get_period_ledger(client["id"], 0)
    assert ledger["hours_reserved"] == pytest.approx(40, abs=0.001)
    assert ledger["hours_available"] == pytest.approx(60, abs=0.001)


def test_retainer_actual_consumption_after_scan_complete(api):
    """PRD §3.4: "it debits the retainer: hours_consumed rises by actual_hours,
    hours_reserved falls by the smaller of actual_hours and the parent engagement's
    remaining reservation (floored at zero), and available hours are recomputed."
    PRD §2.7: "after scans and incidents complete that optimistic reservation is
    released and replaced by the measured actual consumption, so the difference
    between estimate and actual flows back into available hours."

    Design: Difficulty/dual_variant_calc/dual_variant_retainer_optimistic_vs_actual
    """
    client = create_client(tier="ESSENTIAL", retainer_hours_per_period=100)
    asset = create_asset(client["id"], hostname="db-02", criticality="MEDIUM")
    eng = create_active_engagement(client["id"], [asset["id"]], estimated_hours=40)
    scan = queue_scan(eng["id"], eng["version"])
    validate_success(api.start_scan(scan["id"], LEAD), 200)
    validate_success(api.complete_scan(
        scan["id"], {"actual_hours": 30, "raw_finding_count": 0}, LEAD), 200)

    ledger = get_period_ledger(client["id"], 0)
    # PRD §3.4 + §2.7: "hours_consumed rises by actual_hours" / consumed is the sum
    # of actual_hours over the client's COMPLETED scans whose work fell in this
    # period — both readings give consumed = 30.
    # NOTE: the hours_reserved/hours_available assertions were removed: PRD §2.7
    # defines reserved as the sum over engagements "whose `status` is `AUTHORIZED`",
    # but a started engagement is `ACTIVE` (§3.2: AUTHORIZED -> ACTIVE), so the
    # canonical recompute formula (§2.7) and the delta description (§3.4) diverge on
    # the reserved value for an ACTIVE engagement. The outcome is not uniquely
    # derivable; only the consumed assertion is kept.
    assert ledger["hours_consumed"] == pytest.approx(30, abs=0.001)


# ─── invariant_retainer_reservation_conserved_on_cancel ─────────────────────

def test_authorize_reserves_then_cancel_releases_to_zero(api):
    """PRD §3.3: "reserves estimated_hours on the open ledger (raising hours_reserved
    and lowering hours_available)."
    PRD §3.3: "Cancelling an AUTHORIZED engagement (AUTHORIZED → CANCELLED) is a
    compensating action: it releases the full reservation by reducing hours_reserved
    by estimated_hours and recomputes available hours, keeping reservation
    accounting conserved."

    Design: Difficulty/compensating_invariant/invariant_retainer_reservation_conserved_on_cancel
    """
    client = create_client(tier="ESSENTIAL", retainer_hours_per_period=100)
    asset = create_asset(client["id"], hostname="inv1-01", criticality="MEDIUM")
    eng = create_authorized_engagement(client["id"], [asset["id"]], estimated_hours=40)
    ledger = get_period_ledger(client["id"], 0)
    assert ledger["hours_reserved"] == pytest.approx(40, abs=0.001)
    assert ledger["hours_available"] == pytest.approx(60, abs=0.001)

    validate_success(api.cancel_engagement(eng["id"], LEAD), 200)
    ledger = get_period_ledger(client["id"], 0)
    assert ledger["hours_reserved"] == pytest.approx(0, abs=0.001)
    assert ledger["hours_available"] == pytest.approx(100, abs=0.001)


def test_cancel_authorized_restores_pre_authorize_available(api):
    """PRD §3.3: "it releases the full reservation by reducing hours_reserved by
    estimated_hours and recomputes available hours, keeping reservation accounting
    conserved."
    PRD §2.7: "hours_available, which is hours_granted minus hours_reserved minus
    hours_consumed."

    Design: Difficulty/compensating_invariant/invariant_retainer_reservation_conserved_on_cancel
    """
    client = create_client(tier="ESSENTIAL", retainer_hours_per_period=100)
    asset = create_asset(client["id"], hostname="inv1-02", criticality="MEDIUM")
    before = get_period_ledger(client["id"], 0)
    eng = create_authorized_engagement(client["id"], [asset["id"]], estimated_hours=40)
    validate_success(api.cancel_engagement(eng["id"], LEAD), 200)
    after = get_period_ledger(client["id"], 0)
    assert after["hours_available"] == pytest.approx(before["hours_available"], abs=0.001)
    assert after["hours_reserved"] == pytest.approx(0, abs=0.001)


# ─── validations: retainer_exhausted ────────────────────────────────────────

def test_authorize_over_budget_returns_retainer_exhausted(api):
    """PRD §3.3: "its hours_available must be at least the engagement's
    estimated_hours, or the request is rejected with ERR_RETAINER_EXHAUSTED."

    Design: Corner/validations/retainer_exhausted_when_estimate_exceeds_available
    """
    client = create_client(tier="ESSENTIAL", retainer_hours_per_period=50)
    asset = create_asset(client["id"], hostname="val1-01", criticality="MEDIUM")
    eng = create_draft_engagement(client["id"], [asset["id"]], estimated_hours=60)
    res = api.authorize_engagement(eng["id"], CONTACT)
    validate_error(res, "ERR_RETAINER_EXHAUSTED")
