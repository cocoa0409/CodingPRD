"""Multi-hop cascades and conserved-quantity invariants (PRD §2.7, §3.2, §3.3, §3.7)."""
from test_helpers import (
    validate_success, validate_paginated, TEST_USERS, assert_facility_counter_invariant,
)
from test_helpers import fixtures as fx

VM = TEST_USERS["vault_manager_headers"]


def _monitoring_status(api, agreement_id, monitoring_id):
    data, _ = validate_paginated(api.list_monitoring(agreement_id, VM))
    sub = next(s for s in data if s["id"] == monitoring_id)
    return sub["status"]


# ---------------------------------------------------------------------------
# Difficulty: transitive_cascade / terminate_cascade_unit_release_then_waitlist_promotion
# ---------------------------------------------------------------------------
def test_terminate_closes_agreement_and_cancels_monitoring(api):
    """PRD §3.3: "Termination then runs a three-link cascade: first, every `ACTIVE`
    monitoring subscription on the agreement is moved to `CANCELLED`; second, the
    assigned unit is released from `OCCUPIED` back to `AVAILABLE` ... and third, that
    unit becoming available runs waitlist promotion".

    Design: Difficulty/transitive_cascade/terminate_cascade_unit_release_then_waitlist_promotion
    """
    ctx = fx.setup_occupied_unit_with_waiter(api)
    closed = validate_success(api.terminate(ctx["agreement_id"], VM))
    assert closed["status"] == "CLOSED"
    assert _monitoring_status(api, ctx["agreement_id"], ctx["monitoring_id"]) == "CANCELLED"


def test_terminate_release_promotes_top_waiter_and_reserves_unit(api):
    """PRD §3.7: "Promotion transitions the selected entry `WAITING → OFFERED`: its
    `offered_unit_id` is set to the released unit, the unit itself transitions
    `AVAILABLE → RESERVED` (its `version` bumped and facility counters recomputed),
    and `offer_expires_at` is set to 48 hours after the moment of the offer".

    Design: Difficulty/transitive_cascade/terminate_cascade_unit_release_then_waitlist_promotion
    """
    ctx = fx.setup_occupied_unit_with_waiter(api)
    validate_success(api.terminate(ctx["agreement_id"], VM))
    entry = validate_success(api.get_waitlist(ctx["waitlist_id"], VM))
    assert entry["status"] == "OFFERED"
    assert entry["offered_unit_id"] == ctx["unit_id"]
    unit = validate_success(api.get_unit(ctx["unit_id"], VM))
    assert unit["status"] == "RESERVED"


# ---------------------------------------------------------------------------
# Difficulty: transitive_cascade / coi_revoke_cascade_vehicle_lapse_then_delivery_cancel
# ---------------------------------------------------------------------------
def test_revoke_coi_lapses_vehicle_insurance(api):
    """PRD §3.2: "A vault manager may **revoke** a certificate, moving it from `ACTIVE`
    to `REVOKED` ... when the recomputation leaves the vehicle without any active
    covering certificate, its `insurance_status` becomes `LAPSED`".

    Design: Difficulty/transitive_cascade/coi_revoke_cascade_vehicle_lapse_then_delivery_cancel
    """
    ctx = fx.setup_scheduled_delivery(api, declared_value_cents=30_000_000,
                                      coverage_amount_cents=30_000_000)
    coi = validate_success(api.revoke_coi(ctx["coi_id"], VM))
    assert coi["status"] == "REVOKED"
    veh = validate_success(api.get_vehicle(ctx["vehicle_id"], VM))
    assert veh["insurance_status"] == "LAPSED"


def test_revoke_coi_cascade_cancels_scheduled_delivery(api):
    """PRD §3.2: "that lapse in turn auto-cancels every delivery job for that vehicle
    that is still in `SCHEDULED` status, moving each to `CANCELLED` and releasing the
    transporter window it held".

    Design: Difficulty/transitive_cascade/coi_revoke_cascade_vehicle_lapse_then_delivery_cancel
    """
    ctx = fx.setup_scheduled_delivery(api, declared_value_cents=30_000_000,
                                      coverage_amount_cents=30_000_000)
    validate_success(api.revoke_coi(ctx["coi_id"], VM))
    dj = validate_success(api.get_delivery_job(ctx["delivery_job_id"], VM))
    assert dj["status"] == "CANCELLED"


# ---------------------------------------------------------------------------
# Difficulty: compensating_invariant / facility_unit_count_conserved_on_occupy_release
# ---------------------------------------------------------------------------
def test_facility_counts_after_move_in_occupy(api):
    """PRD §2.7: "These four counters always sum to the total number of storage units
    under the facility; that conservation identity must hold after every operation."
    PRD §3.3: "On success the assigned unit transitions from `AVAILABLE` or `RESERVED`
    to `OCCUPIED`, and the facility counters are recomputed."

    Design: Difficulty/compensating_invariant/facility_unit_count_conserved_on_occupy_release
    """
    ctx = fx.setup_pending_agreement(api, total_units=1, document=True)
    validate_success(api.move_in(ctx["agreement_id"], VM))
    fac = validate_success(api.get_facility(ctx["facility_id"], VM))
    assert fac["units_available"] == 0
    assert fac["units_occupied"] == 1
    assert_facility_counter_invariant(fac, 1)


def test_facility_counts_restored_after_terminate_release(api):
    """PRD §3.3: "the assigned unit is released from `OCCUPIED` back to `AVAILABLE`
    (its `version` bumped and facility counters recomputed)".
    PRD §2.7: "These four counters always sum to the total number of storage units
    under the facility; that conservation identity must hold after every operation."

    Design: Difficulty/compensating_invariant/facility_unit_count_conserved_on_occupy_release
    """
    ctx = fx.setup_pending_agreement(api, total_units=1, document=True)
    validate_success(api.move_in(ctx["agreement_id"], VM))
    validate_success(api.terminate(ctx["agreement_id"], VM))
    fac = validate_success(api.get_facility(ctx["facility_id"], VM))
    assert fac["units_available"] == 1
    assert fac["units_occupied"] == 0
    assert_facility_counter_invariant(fac, 1)
