"""Validation-precedence conflicts where two checks are simultaneously violated and
the earlier check in the PRD's fixed order wins (Difficulty:
priority_pair_validation_conflict)."""
from test_helpers import (
    api_client, validate_success, validate_error, get_success_data,
    TEST_USERS, create_spot_assignment_payload,
)
from test_helpers import fixtures as fx

PO = TEST_USERS["permit_officer_headers"]


# --------------------------------------------------------------------------- #
# priority_pair_validation_conflict / issue_safety_beats_temporal_overlap
# --------------------------------------------------------------------------- #
def _issue_with_lapsed_insurance_and_overlap():
    """pA ISSUED on a cart while insurance is briefly ACTIVE; pB SUBMITTED on the same
    cart; clock advanced so insurance has LAPSED yet pA's window still overlaps."""
    fx.set_clock("2026-06-01T00:00:00Z")
    vendor = fx.create_insured_vendor(insurance_overrides={
        "insurance_expires_at": "2026-06-15T00:00:00Z"})
    commissary = fx.create_commissary()
    cart = fx.create_cart(vendor["id"], commissary["id"])
    zone = fx.create_zone(zone_type="STANDARD")
    pA = fx.create_issued_permit(vendor["id"], cart["id"], zone["id"])
    pB = fx.create_submitted_permit(vendor["id"], cart["id"], zone["id"])
    fx.set_clock("2026-06-20T00:00:00Z")  # insurance LAPSED; pA still ISSUED & overlapping
    return pA, pB


def test_issue_reports_insurance_over_overlap(api):
    """PRD §3.3: "Issuance is gated by three checks, in this order: the vendor's
    insurance_status must be ACTIVE, otherwise ERR_INSURANCE_NOT_ACTIVE; the permit's
    cart must be APPROVED, otherwise ERR_CART_NOT_APPROVED; and no other permit for
    the same cart may already be ISSUED with a validity window that overlaps the new
    term, otherwise ERR_PERMIT_OVERLAP."

    Design: Difficulty/priority_pair_validation_conflict/issue_safety_beats_temporal_overlap
    """
    _, pB = _issue_with_lapsed_insurance_and_overlap()
    res = api.issue_permit(pB["id"], PO)
    validate_error(res, "ERR_INSURANCE_NOT_ACTIVE", expected_status=422)


def test_issue_conflict_leaves_permit_submitted(api):
    """PRD §3.3: "the vendor's insurance_status must be ACTIVE, otherwise
    ERR_INSURANCE_NOT_ACTIVE"

    Design: Difficulty/priority_pair_validation_conflict/issue_safety_beats_temporal_overlap
    """
    _, pB = _issue_with_lapsed_insurance_and_overlap()
    api.issue_permit(pB["id"], PO)
    after = validate_success(api.get_permit(pB["id"], PO), 200)
    assert after["status"] == "SUBMITTED"


# --------------------------------------------------------------------------- #
# priority_pair_validation_conflict / assignment_state_beats_capacity
# --------------------------------------------------------------------------- #
def _suspended_permit_in_full_zone():
    """Zone capacity 1: pA holds the only slot; pB ISSUED then SUSPENDED; spotB free
    but the zone is at capacity."""
    fx.set_clock("2026-06-01T00:00:00Z")
    vendor = fx.create_insured_vendor()
    commissary = fx.create_commissary()
    cartA = fx.create_cart(vendor["id"], commissary["id"])
    cartB = fx.create_cart(vendor["id"], commissary["id"])
    zone = fx.create_zone(zone_type="STANDARD", capacity_slots=1, spacing_min_feet=20)
    spotA = fx.create_spot(zone["id"], label="SA", position_feet=100)
    spotB = fx.create_spot(zone["id"], label="SB", position_feet=400)
    pA = fx.create_issued_permit(vendor["id"], cartA["id"], zone["id"])
    get_success_data(fx.assign_spot(
        pA["id"], spotA["id"], "2026-06-01T09:00:00Z", "2026-06-01T17:00:00Z",
        expected_zone_version=zone["version"]))
    pB = fx.create_issued_permit(vendor["id"], cartB["id"], zone["id"])
    get_success_data(api_client.suspend_permit(pB["id"], PO, {"reason": "hold"}))
    zvc = fx.zone_version(zone["id"])
    return pB, spotB, zvc


# NOTE: test_assignment_reports_invalid_state_over_capacity DELETED.
# It asserted that a direct spot assignment to a SUSPENDED permit yields
# ERR_INVALID_STATE (state legality) *before* the ERR_ZONE_CAPACITY_FULL capacity
# check. PRD §3.5 gives an exhaustive ordered check list for direct assignment
# (time-conflict → spacing → zone-availability → stale-version) and NOWHERE states
# that the permit must be ISSUED; the word "SUSPENDED" never appears near spot
# assignment, and a create is not a permit transition, so §4's transition rule does
# not apply. Two PRD-faithful impls diverge: one infers a permit-state check from
# the generic "state legality" phrase (ERR_INVALID_STATE), the other follows §3.5's
# stated checks and rejects on capacity (ERR_ZONE_CAPACITY_FULL) — and on a non-full
# zone would even permit the assignment. State-legality-precedence silence → not
# uniquely determined → deleted. (The companion "creates no assignment" check below
# is retained: it holds under either reading.)


def test_assignment_rejection_creates_no_assignment(api):
    """PRD §3.5: "Beyond authentication, ownership, existence, body validity, and
    state legality, the direct assignment is subjected to these business checks"
    PRD §2.6: "A newly created zone begins with assigned_slots at 0 and
    available_slots equal to capacity_slots. Any operation that creates an active
    assignment increments assigned_slots and decrements available_slots"

    Design: Difficulty/priority_pair_validation_conflict/assignment_state_beats_capacity
    """
    pB, spotB, zvc = _suspended_permit_in_full_zone()
    api.create_spot_assignment(
        pB["id"],
        create_spot_assignment_payload(spotB["id"], "2026-06-01T09:00:00Z",
                                       "2026-06-01T17:00:00Z", zvc),
        PO)
    # No assignment exists for the suspended permit pB.
    from test_helpers import validate_paginated
    resp = api.list_spot_assignments(PO, params={"permit_id": pB["id"]})
    data, meta = validate_paginated(resp)
    assert meta["total_count"] == 0
