"""Clock-driven boundaries: the inclusive renewal-alert window, the exclusive
obligation-breach window, the at-threshold risk gate, and the initial-vs-renewal
expiry projection.

Tests here translate queue A (Difficulty) rules dual_variant_calc (expiry),
boundary_precision_check, and resource_temporal_overlap, plus the queue B corner
validations/renew_before_window_returns_not_due.
"""
import pytest

from test_helpers import (
    api_client,
    validate_success, validate_error,
    factories as F, fixtures as FX,
    ApiErrorId,
)

ADMIN = FX.ADMIN
MGR = FX.MGR


@pytest.fixture
def api():
    return api_client


# ─── dual_variant_calc: expiry initial vs renewal anchor ──────────────

def test_expiry_initial_anchored_on_effective_date(api):
    """PRD §3.6: "When a contract activates, its expiry_date is computed as its
    effective_date plus term_months calendar months."

    Design: Difficulty/dual_variant_calc/expiry_projection_initial_vs_renewal_anchor
    """
    setup = FX.setup_simple_active(api, auto_renew=True, activation_clock="2026-06-01T00:00:00Z")
    contract = FX.get_contract(api, setup["contract"]["id"])
    assert contract["expiry_date"] == "2027-06-01T00:00:00.000Z", \
        f"initial expiry must be effective 2026-06-01 + 12mo = 2027-06-01, got {contract['expiry_date']}"


def test_expiry_renewal_anchored_on_prior_expiry_not_clock(api):
    """PRD §3.7: "recomputes expiry_date as that new effective date plus term_months
    calendar months — anchoring on the prior expiry rather than the renewal clock
    time keeps renewed terms gap-free". So renewing at clock 2027-05-02 yields expiry
    2028-06-01, not 2028-05-02.

    Design: Difficulty/dual_variant_calc/expiry_projection_initial_vs_renewal_anchor
    """
    setup = FX.setup_simple_active(api, auto_renew=False, activation_clock="2026-06-01T00:00:00Z")
    contract_id = setup["contract"]["id"]
    FX.set_clock(api, "2027-05-02T00:00:00Z")  # alert DUE
    active = FX.get_contract(api, contract_id)
    data = validate_success(api.renew_contract(contract_id, F.occ_payload(active["version"]), MGR), 200)
    assert data["expiry_date"] == "2028-06-01T00:00:00.000Z", \
        f"renewed expiry must anchor on prior expiry (2027-06-01 + 12mo = 2028-06-01), got {data['expiry_date']}"
    assert data["renewal_cycle_index"] == 1, \
        f"renewal_cycle_index must be 1 after one renewal, got {data['renewal_cycle_index']}"


# ─── boundary_precision: risk at exactly threshold blocks send ────────

def test_risk_at_exactly_threshold_blocks_send(api):
    """PRD §2.8: a contract scoring "at or above its tenant's tolerance cannot be
    sent for signature until the offending deviations have been formally cleared."
    PRD §3.5: "The risk gate requires either that the contract's risk_score be
    strictly below the organization's risk_appetite_threshold, or that every clause
    template deviated in the current version have a GRANTED deviation approval...
    failing this, the send is refused with ERR_DEVIATION_REQUIRED."

    Design: Difficulty/boundary_precision_check/risk_threshold_at_exactly_appetite_blocks_send
    """
    # Org threshold 70; two uncovered deviations w=40 + w=30 = 70 (exactly at threshold).
    setup = FX.setup_approved_contract(
        api,
        clause_defs=[
            {"clause_key": "LIABILITY_CAP", "risk_weight": 40, "category": "LIABILITY"},
            {"clause_key": "INDEMNITY", "risk_weight": 30, "category": "INDEMNITY"},
        ],
        clauses_spec=[
            {"clause_index": 0, "is_deviation": True, "text": "edit"},
            {"clause_index": 1, "is_deviation": True, "text": "edit"},
        ],
        org_overrides={"risk_appetite_threshold": 70},
    )
    approved = setup["contract_approved"]
    assert approved["risk_score"] == 70, \
        f"risk must be exactly at threshold 70, got {approved['risk_score']}"
    resp = api.send_for_signature(
        approved["id"], F.send_for_signature_payload(approved["version"], F.default_signers()), MGR
    )
    validate_error(resp, ApiErrorId.ERR_DEVIATION_REQUIRED.value, 409)


def test_risk_below_threshold_clears_send_gate(api):
    """PRD §3.5: "The risk gate requires either that the contract's risk_score be
    strictly below the organization's risk_appetite_threshold" — so a contract whose
    risk is strictly below threshold (the X-1 side of the '>=' gate) sends without any
    deviation approval.

    Design: Difficulty/boundary_precision_check/risk_threshold_at_exactly_appetite_blocks_send
    """
    # Org threshold 70; a single uncovered deviation w=40 -> risk 40 < 70.
    setup = FX.setup_approved_contract(
        api,
        clause_defs=[{"clause_key": "LIABILITY_CAP", "risk_weight": 40, "category": "LIABILITY"}],
        clauses_spec=[{"clause_index": 0, "is_deviation": True, "text": "edit"}],
        org_overrides={"risk_appetite_threshold": 70},
    )
    approved = setup["contract_approved"]
    assert approved["risk_score"] == 40, \
        f"risk must be 40 (strictly below threshold 70), got {approved['risk_score']}"
    resp = api.send_for_signature(
        approved["id"], F.send_for_signature_payload(approved["version"], F.default_signers()), MGR
    )
    validate_success(resp, 200)


def test_renewal_alert_due_at_exact_trigger_date(api):
    """PRD §3.6: "an alert whose trigger_date has been reached — that is, when the
    current clock time is at or after trigger_date, inclusive of the exact boundary
    instant — and whose parent contract is still ACTIVE moves from SCHEDULED to DUE."

    Design: Difficulty/boundary_precision_check/renewal_alert_due_at_exact_trigger_date
    """
    setup = FX.setup_simple_active(api, auto_renew=False, activation_clock="2026-06-01T00:00:00Z")
    contract_id = setup["contract"]["id"]
    FX.set_clock(api, "2027-05-02T00:00:00Z")  # exactly trigger_date (expiry 2027-06-01 - 30d)
    alerts = FX.get_success_data(api.list_renewal_alerts(contract_id, MGR))
    assert alerts[0]["trigger_date"] == "2027-05-02T00:00:00.000Z", \
        f"trigger_date must be expiry - 30 days = 2027-05-02, got {alerts[0]['trigger_date']}"
    assert alerts[0]["status"] == "DUE", \
        f"alert must be DUE at exactly trigger_date (inclusive >=), got {alerts[0]['status']}"


def test_renewal_alert_not_due_one_day_before_trigger(api):
    """PRD §3.6: the alert moves to DUE only "when the current clock time is at or
    after trigger_date, inclusive of the exact boundary instant" — so one tick before
    trigger_date it is still SCHEDULED (the X-1 side of the inclusive boundary).

    Design: Difficulty/boundary_precision_check/renewal_alert_due_at_exact_trigger_date
    """
    setup = FX.setup_simple_active(api, auto_renew=False, activation_clock="2026-06-01T00:00:00Z")
    contract_id = setup["contract"]["id"]
    FX.set_clock(api, "2027-05-01T00:00:00Z")  # one day before trigger_date 2027-05-02
    alerts = FX.get_success_data(api.list_renewal_alerts(contract_id, MGR))
    assert alerts[0]["status"] == "SCHEDULED", \
        f"alert must still be SCHEDULED before trigger_date, got {alerts[0]['status']}"


# ─── resource_temporal_overlap: obligation '>' vs alert '>=' ──────────

def test_obligation_not_breached_at_exactly_due_date(api):
    """PRD §3.6: "any obligation still OPEN whose due_date is strictly in the past
    relative to the current clock time, on a contract that is still ACTIVE, moves
    from OPEN to BREACHED" — so at exactly the due date it is still OPEN.

    Design: Difficulty/resource_temporal_overlap/obligation_breach_vs_due_window_inclusive
    """
    setup = FX.setup_simple_active(api, auto_renew=False, activation_clock="2026-06-01T00:00:00Z")
    contract_id = setup["contract"]["id"]
    obl = FX.get_success_data(api.create_obligation(
        contract_id, F.create_obligation_payload(contract_id, "2026-12-01T00:00:00Z"), MGR
    ))
    FX.set_clock(api, "2026-12-01T00:00:00Z")  # exactly due_date
    obls = FX.get_success_data(api.list_obligations(contract_id, MGR))
    at_due = next(o for o in obls if o["id"] == obl["id"])
    assert at_due["status"] == "OPEN", \
        f"at exactly due_date the obligation must still be OPEN (strict '>' window), got {at_due['status']}"


def test_obligation_breaches_one_day_past_due_date(api):
    """PRD §3.6: "any obligation still OPEN whose due_date is strictly in the past
    relative to the current clock time, on a contract that is still ACTIVE, moves
    from OPEN to BREACHED" — the X+1 side of the exclusive '>' window.

    Design: Difficulty/resource_temporal_overlap/obligation_breach_vs_due_window_inclusive
    """
    setup = FX.setup_simple_active(api, auto_renew=False, activation_clock="2026-06-01T00:00:00Z")
    contract_id = setup["contract"]["id"]
    obl = FX.get_success_data(api.create_obligation(
        contract_id, F.create_obligation_payload(contract_id, "2026-12-01T00:00:00Z"), MGR
    ))
    FX.set_clock(api, "2026-12-02T00:00:00Z")  # strictly past due_date
    obls = FX.get_success_data(api.list_obligations(contract_id, MGR))
    past_due = next(o for o in obls if o["id"] == obl["id"])
    assert past_due["status"] == "BREACHED", \
        f"obligation strictly past due_date must be BREACHED, got {past_due['status']}"


def test_renewal_alert_window_inclusive_vs_obligation_exclusive(api):
    """PRD §3.6: the renewal alert "moves from SCHEDULED to DUE" "when the current
    clock time is at or after trigger_date, inclusive of the exact boundary instant"
    — the opposite adjacency treatment from the obligation's strict-past breach window.

    Design: Difficulty/resource_temporal_overlap/renewal_alert_window_inclusive_vs_obligation_exclusive
    """
    setup = FX.setup_simple_active(api, auto_renew=False, activation_clock="2026-06-01T00:00:00Z")
    contract_id = setup["contract"]["id"]
    FX.set_clock(api, "2027-05-02T00:00:00Z")  # exactly trigger_date
    alerts = FX.get_success_data(api.list_renewal_alerts(contract_id, MGR))
    assert alerts[0]["status"] == "DUE", \
        f"the renewal alert window is inclusive ('>='): DUE at exactly trigger_date, got {alerts[0]['status']}"


def test_renewal_alert_scheduled_strictly_before_trigger(api):
    """PRD §3.6: the alert becomes DUE only "when the current clock time is at or
    after trigger_date" — so strictly before trigger_date it remains SCHEDULED,
    confirming the inclusive lower edge that contrasts with the obligation window.

    Design: Difficulty/resource_temporal_overlap/renewal_alert_window_inclusive_vs_obligation_exclusive
    """
    setup = FX.setup_simple_active(api, auto_renew=False, activation_clock="2026-06-01T00:00:00Z")
    contract_id = setup["contract"]["id"]
    FX.set_clock(api, "2027-05-01T00:00:00Z")  # strictly before trigger_date 2027-05-02
    alerts = FX.get_success_data(api.list_renewal_alerts(contract_id, MGR))
    assert alerts[0]["status"] == "SCHEDULED", \
        f"alert must remain SCHEDULED strictly before trigger_date, got {alerts[0]['status']}"


# ─── Queue B: renew before window returns not-due ─────────────────────

def test_renew_before_window_returns_not_due(api):
    """PRD §3.7: "manual renewal requires that a renewal alert with status DUE exist
    for the contract (otherwise ERR_RENEWAL_NOT_DUE)".

    Design: Corner/validations/renew_before_window_returns_not_due
    """
    # Activate but DO NOT advance the clock — the alert stays SCHEDULED, not DUE.
    setup = FX.setup_simple_active(api, auto_renew=True, activation_clock="2026-06-01T00:00:00Z")
    contract_id = setup["contract"]["id"]
    active = FX.get_contract(api, contract_id)
    resp = api.renew_contract(contract_id, F.occ_payload(active["version"]), MGR)
    validate_error(resp, ApiErrorId.ERR_RENEWAL_NOT_DUE.value, 409)
