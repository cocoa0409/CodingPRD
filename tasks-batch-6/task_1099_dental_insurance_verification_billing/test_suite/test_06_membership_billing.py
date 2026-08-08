"""Membership billing loop, cascade to patient balance, and grace boundary.

Difficulty: non_linear_state_machine (membership cycle), transitive_cascade
(billing run), boundary_precision_check (grace).
Corner: membership_two_missed_periods_cancels.
"""
from test_helpers import (
    validate_success, get_success_data, make_biller_headers, make_manager_headers,
    make_patient_headers,
)
from test_helpers import fixtures as fx


# --------------------------------------------------------------------------
# non_linear_state_machine / membership_active_pastdue_active_cycle
# --------------------------------------------------------------------------
def test_membership_billing_run_flips_to_past_due(api):
    """PRD §3.8: "When a run finds an overdue membership, it adds one period fee
    to the membership's `balance_cents`, increments `past_due_periods` by one,
    moves the membership to `PAST_DUE`."

    Design: Difficulty/non_linear_state_machine/membership_active_pastdue_active_cycle
    """
    _patient, _mp, membership = fx.enrolled_membership(api, clock="2026-05-01T00:00:00Z")
    fx.set_clock(api, "2026-05-17T00:00:00Z")
    fx.run_billing(api)
    m = get_success_data(api.get_membership(membership["id"], make_manager_headers()))
    assert m["status"] == "PAST_DUE", f"expected PAST_DUE, got {m['status']}"
    assert m["balance_cents"] == 2500, f"expected 2500, got {m['balance_cents']}"


def test_membership_pay_returns_to_active(api):
    """PRD §3.8: "A dues payment of `amount_cents` reduces the membership's
    `balance_cents`, advances its `paid_through_date`, resets `past_due_periods`
    to 0, moves the membership from `PAST_DUE` back to `ACTIVE`."

    Design: Difficulty/non_linear_state_machine/membership_active_pastdue_active_cycle
    """
    patient, _mp, membership = fx.enrolled_membership(api, clock="2026-05-01T00:00:00Z")
    fx.set_clock(api, "2026-05-17T00:00:00Z")
    fx.run_billing(api)
    resp = api.pay_membership(membership["id"], 2500, make_patient_headers(patient["id"]))
    data = validate_success(resp, 200)
    assert data["status"] == "ACTIVE", f"expected ACTIVE, got {data['status']}"
    assert data["balance_cents"] == 0, f"expected 0, got {data['balance_cents']}"


# --------------------------------------------------------------------------
# transitive_cascade / billing_run_membership_pastdue_patient_cascade
# --------------------------------------------------------------------------
def test_billing_run_membership_past_due(api):
    """PRD §3.8: "it adds one period fee to the membership's `balance_cents` ...
    and moves the membership to `PAST_DUE`."

    Design: Difficulty/transitive_cascade/billing_run_membership_pastdue_patient_cascade
    """
    _patient, _mp, membership = fx.enrolled_membership(api, clock="2026-05-01T00:00:00Z")
    fx.set_clock(api, "2026-05-17T00:00:00Z")
    fx.run_billing(api)
    m = get_success_data(api.get_membership(membership["id"], make_manager_headers()))
    assert m["status"] == "PAST_DUE"
    assert m["balance_cents"] == 2500, f"expected 2500, got {m['balance_cents']}"


def test_billing_run_cascades_dues_to_patient_balance(api):
    """PRD §3.8: "and cascades the same dues amount into the patient's
    `balance_cents`."

    Design: Difficulty/transitive_cascade/billing_run_membership_pastdue_patient_cascade
    """
    patient, _mp, _membership = fx.enrolled_membership(api, clock="2026-05-01T00:00:00Z")
    fx.set_clock(api, "2026-05-17T00:00:00Z")
    fx.run_billing(api)
    p = get_success_data(api.get_patient(patient["id"], make_biller_headers()))
    assert p["balance_cents"] == 2500, f"expected 2500, got {p['balance_cents']}"


# --------------------------------------------------------------------------
# boundary_precision_check / membership_grace_strict_boundary_on_billing_run
# --------------------------------------------------------------------------
def test_membership_at_grace_boundary_not_overdue(api):
    """PRD §3.8: "A membership is considered overdue only once the clock is
    strictly past its `paid_through_date` plus a 15-day grace window — being
    exactly at the end of grace is not yet overdue."

    Design: Difficulty/boundary_precision_check/membership_grace_strict_boundary_on_billing_run
    """
    _patient, _mp, membership = fx.enrolled_membership(api, clock="2026-05-01T00:00:00Z")
    fx.set_clock(api, "2026-05-16T00:00:00Z")  # exactly paid_through + 15 days
    fx.run_billing(api)
    m = get_success_data(api.get_membership(membership["id"], make_manager_headers()))
    assert m["status"] == "ACTIVE", f"expected ACTIVE at boundary, got {m['status']}"
    assert m["balance_cents"] == 0, f"expected 0, got {m['balance_cents']}"


def test_membership_past_grace_boundary_overdue(api):
    """PRD §3.8: "A membership is considered overdue only once the clock is
    strictly past its `paid_through_date` plus a 15-day grace window."

    Design: Difficulty/boundary_precision_check/membership_grace_strict_boundary_on_billing_run
    """
    _patient, _mp, membership = fx.enrolled_membership(api, clock="2026-05-01T00:00:00Z")
    fx.set_clock(api, "2026-05-16T00:00:00Z")
    fx.run_billing(api)
    fx.set_clock(api, "2026-05-17T00:00:00Z")  # one day past grace
    fx.run_billing(api)
    m = get_success_data(api.get_membership(membership["id"], make_manager_headers()))
    assert m["status"] == "PAST_DUE", f"expected PAST_DUE, got {m['status']}"
    assert m["balance_cents"] == 2500, f"expected 2500, got {m['balance_cents']}"


# --------------------------------------------------------------------------
# Corner: state_machines / membership_two_missed_periods_cancels
# --------------------------------------------------------------------------
def test_membership_two_missed_periods_cancels(api):
    """PRD §3.8: "If that increment brings `past_due_periods` to 2 or more, the
    membership is moved to the terminal `CANCELLED` state."

    Design: Corner/state_machines/membership_two_missed_periods_cancels
    """
    _patient, _mp, membership = fx.enrolled_membership(api, clock="2026-05-01T00:00:00Z")
    fx.set_clock(api, "2026-05-17T00:00:00Z")
    fx.run_billing(api)
    fx.set_clock(api, "2026-06-20T00:00:00Z")
    fx.run_billing(api)
    m = get_success_data(api.get_membership(membership["id"], make_manager_headers()))
    assert m["status"] == "CANCELLED", \
        f"expected CANCELLED after 2 missed periods, got {m['status']}"
