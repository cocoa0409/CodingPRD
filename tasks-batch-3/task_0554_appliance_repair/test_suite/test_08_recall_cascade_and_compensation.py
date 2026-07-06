"""Recall activation cascade and the compensating reversal of reservations and claims."""
from test_helpers import (
    validate_success,
    assert_appliance, assert_truck_stock_item, assert_warranty_contract,
    setup_scheduled_request, setup_approved_request, create_and_activate_recall,
    get_appliance, get_service_request, get_truck_stock, get_warranty_contract,
    TEST_USERS,
)

ADMIN = TEST_USERS["service_admin_headers"]

_EXTENDED = {"coverage_type": "EXTENDED", "coverage_start": "2025-01-01",
             "coverage_end": "2027-01-01", "deductible_cents": 5000, "coverage_cap_cents": 100000}


# ─── Difficulty: recall_activation_safety_hold_cascade_depth4 ──────────────
def test_recall_activation_recalls_appliance_and_holds_request(api):
    """PRD §2.6: "First, every `Appliance` matching the recall's `brand` and `model` has its
    `recall_status` set to `RECALLED`."
    PRD §2.6: "Second, every non-terminal `ServiceRequest` on a now-recalled appliance is driven
    to `SAFETY_HOLD`, and in doing so any warranty claim and any part reservation that request
    had committed are reversed (the exact reversal is described in §3.7)."

    Design: Difficulty/transitive_cascade/recall_activation_safety_hold_cascade_depth4
    """
    ctx = setup_scheduled_request(model="M700")
    create_and_activate_recall("Kenmore", "M700")
    app = get_appliance(ctx)
    assert_appliance(app)
    assert app["recall_status"] == "RECALLED"
    sr = get_service_request(ctx)
    assert sr["status"] == "SAFETY_HOLD"


def test_recall_activation_cancels_booked_appointment(api):
    """PRD §2.6: "Third, each such request's currently `BOOKED` `Appointment` is transitioned to
    `CANCELLED`, and the cancelled appointment releases the zone concurrent-window slot it had
    occupied."

    Design: Difficulty/transitive_cascade/recall_activation_safety_hold_cascade_depth4
    """
    ctx = setup_scheduled_request(model="M701")
    create_and_activate_recall("Kenmore", "M701")
    appt = validate_success(api.get_appointment(ctx["appt_id"], ADMIN), 200)
    assert appt["status"] == "CANCELLED"


# ─── Difficulty: truck_stock_reserve_release_conserved ─────────────────────
def test_recall_hold_releases_truck_stock_reservation(api):
    """PRD §3.7: "If the held request had already been `APPROVED` — meaning it had reserved parts
    and committed a warranty claim — those commitments are compensated exactly: for each reserved
    `required_parts` line the reserved `quantity` is subtracted back out of the technician's
    `quantity_reserved`, and the committed `warranty_covered_cents` is subtracted back out of the
    covering contract's `claimed_cents`."

    Design: Difficulty/compensating_invariant/truck_stock_reserve_release_conserved
    """
    ctx = setup_approved_request(model="MH10", quantity_on_hand=5)  # reserves 2
    create_and_activate_recall("Kenmore", "MH10")
    ts = get_truck_stock(ctx)
    assert_truck_stock_item(ts)
    assert ts["quantity_reserved"] == 0


def test_recall_hold_restores_available_units_and_holds_request(api):
    """PRD §2.9: "releasing the same quantity subtracts it back out (the exact inverse of a
    reservation)".
    PRD §3.7: "A non-terminal request on a newly recalled appliance is driven to `SAFETY_HOLD`,
    and its `BOOKED` appointment is cancelled with its zone slot released."

    Design: Difficulty/compensating_invariant/truck_stock_reserve_release_conserved
    """
    ctx = setup_approved_request(model="MH11", quantity_on_hand=5)
    create_and_activate_recall("Kenmore", "MH11")
    ts = get_truck_stock(ctx)
    assert ts["quantity_available"] == 5, "released reservation restores full availability"
    sr = get_service_request(ctx)
    assert sr["status"] == "SAFETY_HOLD"


# ─── Difficulty: warranty_claim_commit_reverse_conserved ───────────────────
def test_recall_hold_reverses_committed_warranty_claim(api):
    """PRD §2.9: "when a recall hold reverses an approved repair, the committed warranty-covered
    amount is subtracted back out of `claimed_cents`."

    Design: Difficulty/compensating_invariant/warranty_claim_commit_reverse_conserved
    """
    ctx = setup_approved_request(model="MI10", warranty=_EXTENDED, purchase_date="2024-01-15",
                                 part_price_cents=4500,
                                 labor_tasks=[{"minutes": 40}, {"minutes": 20}])
    create_and_activate_recall("Kenmore", "MI10")
    wc = get_warranty_contract(ctx)
    assert_warranty_contract(wc)
    assert wc["claimed_cents"] == 0


def test_recall_hold_restores_remaining_coverage(api):
    """PRD §2.9: "Its `remaining_coverage_cents` is always its `coverage_cap_cents` minus its
    `claimed_cents`."
    PRD §3.7: "the committed `warranty_covered_cents` is subtracted back out of the covering
    contract's `claimed_cents`."

    Design: Difficulty/compensating_invariant/warranty_claim_commit_reverse_conserved
    """
    ctx = setup_approved_request(model="MI11", warranty=_EXTENDED, purchase_date="2024-01-15",
                                 part_price_cents=4500,
                                 labor_tasks=[{"minutes": 40}, {"minutes": 20}])
    create_and_activate_recall("Kenmore", "MI11")
    wc = get_warranty_contract(ctx)
    assert wc["remaining_coverage_cents"] == 100000
    sr = get_service_request(ctx)
    assert sr["status"] == "SAFETY_HOLD"
