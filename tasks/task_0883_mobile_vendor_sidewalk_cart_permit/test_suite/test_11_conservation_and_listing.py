"""Zone-slot conservation across assign/release and reverse-reachability listing
(Difficulty: compensating_invariant; Corner: endpoints)."""
from test_helpers import (
    validate_success, validate_paginated, get_success_data, TEST_USERS,
    make_vendor_headers, make_enforcement_headers, OFFICER_ISSUER_ID,
    create_spot_assignment_payload, create_violation_payload,
    assert_zone_slot_conservation,
)
from test_helpers import fixtures as fx

PO = TEST_USERS["permit_officer_headers"]
EO1 = make_enforcement_headers(OFFICER_ISSUER_ID)


# --------------------------------------------------------------------------- #
# compensating_invariant / slot_conservation_assign_then_release
# --------------------------------------------------------------------------- #
def test_assignment_consumes_a_slot(api):
    """PRD §2.6: "assigned_slots is the number of SpotAssignment records in that zone
    whose status is ACTIVE. available_slots is the zone's capacity_slots minus its
    assigned_slots. These two counters observe a strict partition invariant:
    assigned_slots plus available_slots always equals capacity_slots."

    Design: Difficulty/compensating_invariant/slot_conservation_assign_then_release
    """
    ctx = fx.setup_issued_permit(spot_positions=[100], capacity_slots=5)
    permit, zone, spot = ctx["permit"], ctx["zone"], ctx["spots"][0]
    before = validate_success(api.get_zone(zone["id"], PO), 200)
    assert before["assigned_slots"] == 0 and before["available_slots"] == 5
    assert_zone_slot_conservation(before)
    get_success_data(api.create_spot_assignment(
        permit["id"],
        create_spot_assignment_payload(spot["id"], "2026-06-01T09:00:00Z",
                                       "2026-06-01T17:00:00Z", zone["version"]), PO))
    after = validate_success(api.get_zone(zone["id"], PO), 200)
    assert after["assigned_slots"] == 1 and after["available_slots"] == 4
    assert_zone_slot_conservation(after)


def test_release_restores_the_slot(api):
    """PRD §2.6: "Any operation that creates an active assignment increments
    assigned_slots and decrements available_slots; any release does the reverse."
    PRD §3.5: "the freed spot returns to AVAILABLE, the zone's assigned_slots is
    decremented, available_slots is recomputed"

    Design: Difficulty/compensating_invariant/slot_conservation_assign_then_release
    """
    ctx = fx.setup_issued_permit(spot_positions=[100], capacity_slots=5)
    permit, zone, spot = ctx["permit"], ctx["zone"], ctx["spots"][0]
    assignment = get_success_data(api.create_spot_assignment(
        permit["id"],
        create_spot_assignment_payload(spot["id"], "2026-06-01T09:00:00Z",
                                       "2026-06-01T17:00:00Z", zone["version"]), PO))
    get_success_data(api.release_spot_assignment(assignment["id"], PO))
    restored = validate_success(api.get_zone(zone["id"], PO), 200)
    assert restored["assigned_slots"] == 0 and restored["available_slots"] == 5
    assert_zone_slot_conservation(restored)


# --------------------------------------------------------------------------- #
# Corner endpoints: list_carts_filtered_by_vendor
# --------------------------------------------------------------------------- #
def test_list_carts_filtered_by_vendor(api):
    """PRD §2.9: "List endpoints support reverse lookups by foreign key: carts may be
    filtered by vendor_id, commissary_id, or status"

    Design: Corner/endpoints/list_carts_filtered_by_vendor
    """
    fx.set_clock()
    va = fx.create_vendor(legal_name="A", contact_email="a@x.com")
    vb = fx.create_vendor(legal_name="B", contact_email="b@x.com")
    commissary = fx.create_commissary()
    fx.create_cart(va["id"], commissary["id"], inspect=False, approve=False)
    fx.create_cart(vb["id"], commissary["id"], inspect=False, approve=False)
    resp = api.list_carts(PO, params={"vendor_id": va["id"]})
    data, meta = validate_paginated(resp)
    assert meta["total_count"] == 1
    assert data[0]["vendor_id"] == va["id"]


# --------------------------------------------------------------------------- #
# Corner endpoints: list_violations_reverse_reachability
# --------------------------------------------------------------------------- #
def test_list_violations_for_permit(api):
    """PRD §2.9: "violations and complaints by status within a permit"

    Design: Corner/endpoints/list_violations_reverse_reachability
    """
    ctx = fx.setup_issued_permit()
    vio = get_success_data(api.create_violation(
        ctx["permit"]["id"], create_violation_payload("MINOR", "x"), EO1))
    resp = api.list_violations(ctx["permit"]["id"], PO)
    data, meta = validate_paginated(resp)
    assert meta["total_count"] == 1
    assert data[0]["id"] == vio["id"]
    assert data[0]["permit_id"] == ctx["permit"]["id"]
