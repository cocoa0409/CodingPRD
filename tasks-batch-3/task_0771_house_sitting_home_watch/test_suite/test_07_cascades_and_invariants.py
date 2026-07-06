"""Multi-hop cascades (assign/unassign cycle, booking-cancel depth-3, incident
exhaustion depth-2) and conserved-quantity invariants (key custody, invoice subtotal)."""
from test_helpers import validate_success, make_coordinator_headers
from test_helpers import factories as f
from test_helpers import fixtures as fx

COORD = make_coordinator_headers()


# ---------------------------------------------------------------------------
# Difficulty/non_linear_state_machine/booking_assign_unassign_cycle
# ---------------------------------------------------------------------------

def test_unassign_returns_booking_to_pool_and_voids_invoice(api):
    """PRD 3.4: "Unassignment cancels every SCHEDULED visit of the booking (moving each to
    CANCELLED), voids the booking's invoice (to VOID), and clears sitter_id back to null, so the
    booking can be assigned afresh."

    Design: Difficulty/non_linear_state_machine/booking_assign_unassign_cycle
    """
    ctx = fx.setup_scheduled_booking(api, property_overrides={"size_tier": "MEDIUM"})
    fx.get_success_data(api.unassign_booking(ctx["booking"]["id"], COORD))
    booking = fx.get_booking(api, ctx["booking"]["id"])
    assert booking["status"] == "PENDING_ASSIGNMENT", booking
    assert booking["sitter_id"] is None, booking
    assert fx.invoice_for_booking(api, ctx["booking"]["id"])["status"] == "VOID"


def test_reassign_after_unassign_returns_to_scheduled(api):
    """PRD 3.4: "When all four qualifications pass, assignment records sitter_id on the booking,
    generates the visit rows, and creates the booking's invoice in DRAFT with a subtotal of zero."

    Design: Difficulty/non_linear_state_machine/booking_assign_unassign_cycle
    """
    ctx = fx.setup_scheduled_booking(api, property_overrides={"size_tier": "MEDIUM"})
    fx.get_success_data(api.unassign_booking(ctx["booking"]["id"], COORD))
    fx.assign_booking(api, ctx["booking"]["id"], ctx["sitter"]["id"])
    booking = fx.get_booking(api, ctx["booking"]["id"])
    assert booking["status"] == "SCHEDULED", booking
    assert booking["sitter_id"] == ctx["sitter"]["id"], booking


# ---------------------------------------------------------------------------
# Difficulty/transitive_cascade/booking_cancel_cascade_booking_visit_invoice_depth3
# ---------------------------------------------------------------------------

def _active_booking_one_done_visit(api):
    return fx.setup_done_visit(
        api,
        property_overrides={"size_tier": "MEDIUM", "has_pets": True,
                            "checklist_config": ["MAIL"], "key_copies_total": 1},
        booking_overrides={"booking_type": "VACATION",
                           "start_date": "2026-06-01T00:00:00Z",
                           "end_date": "2026-06-01T00:00:00Z"},
        checkin_clock="2026-06-01T09:00:00Z", checkout_clock="2026-06-01T09:30:00Z",
        completed_tasks=["MAIL"])


def test_cancel_active_booking_cancels_booking_and_visit(api):
    """PRD 3.9: "Cancelling a booking that had progressed to SCHEDULED or ACTIVE triggers a cascade
    in three hops: first, every visit not already CANCELLED or MISSED — that is, any visit in
    SCHEDULED, IN_PROGRESS, FLAGGED, or DONE — moves to CANCELLED".

    Design: Difficulty/transitive_cascade/booking_cancel_cascade_booking_visit_invoice_depth3
    """
    ctx = _active_booking_one_done_visit(api)
    fx.get_success_data(api.cancel_booking(ctx["booking"]["id"], COORD))
    assert fx.get_booking(api, ctx["booking"]["id"])["status"] == "CANCELLED"
    assert fx.get_visit(api, ctx["visit"]["id"])["status"] == "CANCELLED"


def test_cancel_active_booking_reverses_charge_voids_invoice_returns_key(api):
    """PRD 3.9: "second, each such visit that had already billed a charge (one that was DONE) has
    that charge reversed, so the invoice's subtotal_cents is decremented and the invoice financials
    are recomputed; third, the invoice moves to VOID. In addition, any CHECKED_OUT key assignment for
    this booking is returned, moving to RETURNED and releasing its key copy back to the office."

    Design: Difficulty/transitive_cascade/booking_cancel_cascade_booking_visit_invoice_depth3
    """
    ctx = _active_booking_one_done_visit(api)
    assert fx.invoice_for_booking(api, ctx["booking"]["id"])["subtotal_cents"] == 6500
    fx.get_success_data(api.cancel_booking(ctx["booking"]["id"], COORD))
    invoice = fx.invoice_for_booking(api, ctx["booking"]["id"])
    assert invoice["status"] == "VOID", invoice
    assert invoice["subtotal_cents"] == 0, invoice
    assert fx.get_key_assignment(api, ctx["key"]["id"])["status"] == "RETURNED"


# ---------------------------------------------------------------------------
# Difficulty/transitive_cascade/incident_resolve_exhaust_suspend_depth2
# ---------------------------------------------------------------------------

def _escalated_emergency_incident(api):
    return fx.setup_escalated_incident(api, severity="EMERGENCY", liability_coverage=100000)


def test_resolve_escalated_incident_settles_and_pays_out(api):
    """PRD 3.7: "In both cases the settled payout, stored in settled_payout_cents, is the lesser of
    the assessed damage and the policy's coverage_amount_cents."
    PRD 3.7: "Resolving from ESCALATED computes settled_payout_cents, releases the previously placed
    reserve by subtracting the incident's estimated_exposure_cents from the policy's
    reserved_exposure_cents, and adds the settled payout to the policy's paid_out_cents."

    Design: Difficulty/transitive_cascade/incident_resolve_exhaust_suspend_depth2
    """
    ctx = _escalated_emergency_incident(api)
    fx.get_success_data(api.resolve_incident(ctx["incident"]["id"], f.resolve_payload(250000), COORD))
    incident = fx.get_incident(api, ctx["incident"]["id"])
    policy = fx.get_coverage_policy(api, ctx["liability_policy"]["id"])
    assert incident["status"] == "RESOLVED", incident
    assert incident["settled_payout_cents"] == 100000, incident
    assert policy["paid_out_cents"] == 100000, policy


def test_resolve_exhausts_policy_and_suspends_sitter(api):
    """PRD 3.7: "If, after this, the policy's paid_out_cents is at or above its coverage_amount_cents,
    the policy becomes EXHAUSTED, and — caused by that exhaustion — the sitter's status moves to SUSPENDED."

    Design: Difficulty/transitive_cascade/incident_resolve_exhaust_suspend_depth2
    """
    ctx = _escalated_emergency_incident(api)
    fx.get_success_data(api.resolve_incident(ctx["incident"]["id"], f.resolve_payload(250000), COORD))
    policy = fx.get_coverage_policy(api, ctx["liability_policy"]["id"])
    sitter = fx.get_sitter(api, ctx["sitter"]["id"])
    assert policy["status"] == "EXHAUSTED", policy
    assert sitter["status"] == "SUSPENDED", sitter


# ---------------------------------------------------------------------------
# Difficulty/compensating_invariant/key_custody_conservation_checkout_then_return
# ---------------------------------------------------------------------------

def _property_with_at_office_key(api):
    fx.set_clock(api, "2026-05-01T00:00:00Z")
    client = fx.create_client(api)
    prop = fx.create_property(api, client["id"], key_copies_total=2)
    sitter = fx.onboard_cleared_bonded_sitter(api)
    booking = fx.create_booking(api, prop["id"])
    fx.submit_booking(api, booking["id"])
    fx.assign_booking(api, booking["id"], sitter["id"])
    key = fx.get_success_data(api.create_key_assignment(
        f.create_key_assignment_payload(prop["id"], sitter["id"], booking["id"]), COORD))
    return prop["id"], key["id"]


def test_key_checkout_decrements_available_copies(api):
    """PRD 3.5: "Checking a copy out — an action available to a Coordinator or the Sitter — moves the
    assignment from AT_OFFICE to CHECKED_OUT, stamps checked_out_at with the current clock, and
    decrements the property's available_key_copies by one."

    Design: Difficulty/compensating_invariant/key_custody_conservation_checkout_then_return
    """
    prop_id, key_id = _property_with_at_office_key(api)
    fx.get_success_data(api.check_out_key(key_id, COORD))
    assert fx.get_property(api, prop_id)["available_key_copies"] == 1


def test_key_return_restores_available_copies(api):
    """PRD 3.5: "Returning a copy moves the assignment from CHECKED_OUT to RETURNED, stamps
    returned_at, and increments available_key_copies by one."

    Design: Difficulty/compensating_invariant/key_custody_conservation_checkout_then_return
    """
    prop_id, key_id = _property_with_at_office_key(api)
    fx.get_success_data(api.check_out_key(key_id, COORD))
    fx.get_success_data(api.return_key(key_id, COORD))
    assert fx.get_property(api, prop_id)["available_key_copies"] == 2
    assert fx.get_key_assignment(api, key_id)["status"] == "RETURNED"


# ---------------------------------------------------------------------------
# Difficulty/compensating_invariant/invoice_subtotal_reconciliation_checkout_then_cancel
# ---------------------------------------------------------------------------

def test_invoice_subtotal_reflects_billed_visit_charge(api):
    """PRD 3.6: "On a successful checkout the provisional charge is added to the invoice's
    subtotal_cents, the invoice's billed_visit_count is incremented by one, and the invoice
    financials are recomputed as described in Section 3.9."

    Design: Difficulty/compensating_invariant/invoice_subtotal_reconciliation_checkout_then_cancel
    """
    ctx = _active_booking_one_done_visit(api)
    assert fx.invoice_for_booking(api, ctx["booking"]["id"])["subtotal_cents"] == 6500


def test_cancel_reverses_charge_back_to_zero_subtotal(api):
    """PRD 3.9: "each such visit that had already billed a charge (one that was DONE) has that charge
    reversed, so the invoice's subtotal_cents is decremented and the invoice financials are
    recomputed; third, the invoice moves to VOID."

    Design: Difficulty/compensating_invariant/invoice_subtotal_reconciliation_checkout_then_cancel
    """
    ctx = _active_booking_one_done_visit(api)
    fx.get_success_data(api.cancel_booking(ctx["booking"]["id"], COORD))
    invoice = fx.invoice_for_booking(api, ctx["booking"]["id"])
    assert invoice["subtotal_cents"] == 0, invoice
    assert invoice["status"] == "VOID", invoice
