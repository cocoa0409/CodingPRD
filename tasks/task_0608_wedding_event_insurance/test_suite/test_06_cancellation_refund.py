"""Cancellation, the free-look window, refund settlement, and cancel cascades.

Queue A:
  dual_variant_calc / cancellation_refund_free_look_full_refund
  boundary_precision_check / cancel_exactly_on_free_look_day_still_full_refund
  transitive_cascade / policy_cancel_cascades_billing_refunded_and_children_voided
  compensating_invariant / premium_money_conserved_bind_charge_minus_refund
Queue B:
  state_machines / cancel_blocked_by_open_claim
"""
from test_helpers import (
    validate_success, validate_error, validate_paginated,
    make_policyholder_headers, TEST_USERS,
)
from test_helpers import fixtures as FX
from test_helpers.assertions import ledger_net_cents

_admin = TEST_USERS["admin_headers"]
_uw = TEST_USERS["underwriter_headers"]
_ph = make_policyholder_headers("ph-1")


def _bound_paid_canc_liab_rings():
    """Bound+paid SINGLE_EVENT policy: CANC + LIAB + RINGS rider.

    total_premium_cents = 65000 + 45000 + 18000 = 128000. bind_at = 2026-01-01.
    Returns the policy id.
    """
    canc = FX.create_cancellation_product()
    liab = FX.create_liability_product()
    venue = FX.create_venue()
    policy = FX.create_quoted_policy(free_look_days=15)
    FX.add_event_profile(policy["id"], venue["id"], expected_attendance=150)
    FX.add_coverage(policy["id"], canc["id"])
    FX.add_coverage(policy["id"], liab["id"])
    FX.add_rider(policy["id"], "RINGS", 1200000)  # raw 18000 within clamp
    FX.bind_policy(policy["id"])
    FX.pay_policy(policy["id"], 128000)
    return policy["id"]


def test_cancellation_refund_free_look_full_refund(api):
    """PRD §3.6: "If that number of whole days is less than or equal to the policy's
    `free_look_days`, the cancellation falls inside the free-look window: the entire
    premium is refunded, so `refund_due_cents` is set to `total_premium_cents` and
    `premium_earned_cents` is set to zero."
    PRD §3.6: "If `refund_due_cents` is greater than zero, the policy's `billing_status`
    becomes `REFUNDED`".

    Design: Difficulty/dual_variant_calc/cancellation_refund_free_look_full_refund
    """
    pid = _bound_paid_canc_liab_rings()
    FX.set_clock("2026-01-10T00:00:00Z")  # day 9, within free-look
    cancelled = validate_success(api.cancel_policy(pid, _ph), 200)
    assert cancelled["refund_due_cents"] == 128000
    assert cancelled["premium_earned_cents"] == 0
    assert cancelled["lifecycle_status"] == "CANCELLED"
    assert cancelled["billing_status"] == "REFUNDED"


def test_cancellation_refund_free_look_appends_negative_refund_ledger(api):
    """PRD §3.6: "the entire premium is refunded, so `refund_due_cents` is set to
    `total_premium_cents` and `premium_earned_cents` is set to zero."
    PRD §3.6: "the policy's `billing_status` becomes `REFUNDED` and a `REFUND` ledger entry
    is appended whose `amount_cents` is the negative of `refund_due_cents`".

    Design: Difficulty/dual_variant_calc/cancellation_refund_free_look_full_refund
    """
    pid = _bound_paid_canc_liab_rings()
    FX.set_clock("2026-01-10T00:00:00Z")  # day 9, within free-look
    cancelled = validate_success(api.cancel_policy(pid, _ph), 200)
    assert cancelled["refund_due_cents"] == 128000
    assert cancelled["premium_earned_cents"] == 0
    data, _ = validate_paginated(api.list_ledger(pid, _uw))
    refunds = [e for e in data if e["entry_kind"] == "REFUND"]
    assert len(refunds) == 1
    assert refunds[0]["amount_cents"] == -128000


def test_cancel_exactly_on_free_look_day_still_full_refund(api):
    """PRD §3.6: "The boundary is inclusive — a cancellation on exactly the free-look day
    still receives the full refund."

    Design: Difficulty/boundary_precision_check/cancel_exactly_on_free_look_day_still_full_refund
    """
    pid = _bound_paid_canc_liab_rings()
    FX.set_clock("2026-01-16T00:00:00Z")  # exactly day 15 == free_look_days
    cancelled = validate_success(api.cancel_policy(pid, _ph), 200)
    assert cancelled["refund_due_cents"] == 128000
    assert cancelled["premium_earned_cents"] == 0
    assert cancelled["billing_status"] == "REFUNDED"


def test_cancel_one_day_after_free_look_pro_rata(api):
    """PRD §3.6: "If instead the number of whole days exceeds `free_look_days`, the
    free-look window has passed and a pro-rata earned amount applies: the carrier retains
    an earned amount equal to the `total_premium_cents` multiplied by the minimum earned
    ratio of 25 percent, rounded up to the next whole cent, recorded as
    `premium_earned_cents`; the `refund_due_cents` is then the `total_premium_cents` minus
    that earned amount".

    Design: Difficulty/boundary_precision_check/cancel_exactly_on_free_look_day_still_full_refund
    """
    pid = _bound_paid_canc_liab_rings()
    FX.set_clock("2026-01-17T00:00:00Z")  # day 16 > free_look_days 15
    cancelled = validate_success(api.cancel_policy(pid, _ph), 200)
    # ceil(128000 * 0.25) == 32000 ; refund == 128000 - 32000 == 96000
    assert cancelled["premium_earned_cents"] == 32000
    assert cancelled["refund_due_cents"] == 96000
    assert cancelled["billing_status"] == "REFUNDED"


def test_policy_cancel_cascades_billing_refunded_and_children_voided(api):
    """PRD §3.6: "If `refund_due_cents` is greater than zero, the policy's `billing_status`
    becomes `REFUNDED` and a `REFUND` ledger entry is appended whose `amount_cents` is the
    negative of `refund_due_cents`".
    PRD §3.6: "every `ACTIVE` coverage line is flipped to `VOIDED`, every `ACTIVE` rider is
    flipped to `VOIDED`, and every `ISSUED` certificate is flipped to `REVOKED`."

    Design: Difficulty/transitive_cascade/policy_cancel_cascades_billing_refunded_and_children_voided
    """
    # Bound+paid+in-force LIABILITY-only policy with one ISSUED certificate, clock post free-look.
    liab = FX.create_liability_product()
    venue = FX.create_venue()
    policy = FX.create_quoted_policy(free_look_days=15)
    FX.add_event_profile(policy["id"], venue["id"], expected_attendance=150)
    FX.add_coverage(policy["id"], liab["id"])
    cert = FX.add_certificate(policy["id"], venue["id"], additional_insured_name="Grand Hall LLC")
    FX.bind_policy(policy["id"])
    FX.pay_policy(policy["id"], 45000)
    FX.activate_coverage(policy["id"])
    validate_success(api.issue_certificate(policy["id"], cert["id"], _uw), 200)
    FX.set_clock("2026-03-01T00:00:00Z")  # post free-look
    cancelled = validate_success(api.cancel_policy(policy["id"], _ph), 200)
    # ceil(45000 * 0.25) == 11250 ; refund == 45000 - 11250 == 33750
    assert cancelled["premium_earned_cents"] == 11250
    assert cancelled["refund_due_cents"] == 33750
    assert cancelled["billing_status"] == "REFUNDED"
    cert_after = validate_success(api.list_certificates(policy["id"], _uw), 200)
    issued = next(c for c in cert_after if c["id"] == cert["id"])
    assert issued["status"] == "REVOKED"


def test_policy_cancel_voids_active_coverage_in_cascade(api):
    """PRD §3.6: "Regardless of the split, the cascade fans out across the aggregate: every
    `ACTIVE` coverage line is flipped to `VOIDED`, every `ACTIVE` rider is flipped to
    `VOIDED`, and every `ISSUED` certificate is flipped to `REVOKED`."

    Design: Difficulty/transitive_cascade/policy_cancel_cascades_billing_refunded_and_children_voided
    """
    ctx = FX.setup_in_force_policy_canc_only()  # ACTIVE CANCELLATION coverage
    pid = ctx["policy"]["id"]
    FX.set_clock("2026-03-01T00:00:00Z")  # post free-look
    cancelled = validate_success(api.cancel_policy(pid, _ph), 200)
    assert cancelled["lifecycle_status"] == "CANCELLED"
    cov = validate_success(api.get_coverage(pid, ctx["coverage"]["id"], _uw), 200)
    assert cov["status"] == "VOIDED"


def test_premium_money_conserved_bind_charge_minus_refund(api):
    """PRD §3.6: "the entire premium is refunded, so `refund_due_cents` is set to
    `total_premium_cents` and `premium_earned_cents` is set to zero."
    PRD §3.6: "a `REFUND` ledger entry is appended whose `amount_cents` is the negative of
    `refund_due_cents`".

    Design: Difficulty/compensating_invariant/premium_money_conserved_bind_charge_minus_refund
    """
    pid = _bound_paid_canc_liab_rings()
    FX.set_clock("2026-01-10T00:00:00Z")  # day 9, free-look -> full refund
    cancelled = validate_success(api.cancel_policy(pid, _ph), 200)
    data, _ = validate_paginated(api.list_ledger(pid, _uw))
    # PREMIUM_CHARGE +128000 then REFUND -128000 -> net 0
    assert ledger_net_cents(data) == 0
    assert cancelled["premium_earned_cents"] == 0
    assert cancelled["refund_due_cents"] == 128000


def test_premium_money_ledger_holds_charge_and_refund_rows(api):
    """PRD §3.4: "The premium charge written to the ledger at bind is a `PREMIUM_CHARGE`
    entry whose `amount_cents` equals the positive `total_premium_cents`."
    PRD §3.6: "a `REFUND` ledger entry is appended whose `amount_cents` is the negative of
    `refund_due_cents`".

    Design: Difficulty/compensating_invariant/premium_money_conserved_bind_charge_minus_refund
    """
    pid = _bound_paid_canc_liab_rings()
    FX.set_clock("2026-01-10T00:00:00Z")  # free-look -> full refund
    validate_success(api.cancel_policy(pid, _ph), 200)
    from test_helpers.assertions import ledger_sum_by_kind
    data, _ = validate_paginated(api.list_ledger(pid, _uw))
    assert ledger_sum_by_kind(data, "PREMIUM_CHARGE") == 128000
    assert ledger_sum_by_kind(data, "REFUND") == -128000


def test_cancel_blocked_by_open_claim(api):
    """PRD §3.6: "Cancellation is barred while the policy has any open claim — that is, any
    claim whose status is `SUBMITTED`, `INFO_REQUESTED`, or `APPROVED` — and such an
    attempt is rejected with `ERR_OPEN_CLAIM_BLOCKS_CANCEL`."

    Design: Corner/state_machines/cancel_blocked_by_open_claim
    """
    ctx, claim = FX.setup_submitted_claim(claimed_amount_cents=1000000)
    pid = ctx["policy"]["id"]
    res = api.cancel_policy(pid, _ph)
    validate_error(res, "ERR_OPEN_CLAIM_BLOCKS_CANCEL", 409)
    refreshed = validate_success(api.get_policy(pid, _uw), 200)
    assert refreshed["lifecycle_status"] == "IN_FORCE"
