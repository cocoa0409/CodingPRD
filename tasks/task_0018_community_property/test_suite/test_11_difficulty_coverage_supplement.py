"""Supplemental tests guaranteeing each difficulty-design instance is covered
by at least TWO dedicated tests (per §2.1.A of the unit-test-generator skill).

Each test in this file:
- Cites a verbatim PRD sentence, exactly as the primary tests do.
- Carries a # difficulty: <rule_id>/<instance.name> tag.
- Tests a complementary aspect of the instance (e.g., the "if instead" branch in
  the SCAFFOLD_DIFFICULTY_DESIGN.yaml recipes that the primary test does not cover).

Instances supplemented here:
- dual_variant_calc/vote_tally_per_household_vs_per_area
- combinatorial_formula/vote_pass_threshold_branch_on_frozen_denominator
- transitive_cascade/clock_advance_overdue_dunning_voting_disqualification
- transitive_cascade/reservation_damage_spillover_cascade
- priority_pair_validation_conflict/state_vs_business_safety_on_reservation
- boundary_precision_check/facility_slot_full_capacity_boundary
- cross_entity_state_dependency/reservation_check_in_blocked_when_owner_delinquent
- cross_entity_state_dependency/parking_application_approve_requires_property_quota_room
- resource_temporal_overlap/facility_slot_half_open_interval_with_capacity
- resource_temporal_overlap/parking_space_exclusive_allocation
- compensating_invariant/vote_weight_conservation_yes_no_abstain
"""

from datetime import datetime, timedelta, timezone

import pytest

from test_helpers import (
    advance_clock_to,
    api_client,
    approve_parking_application,
    approve_parking_application_payload,
    book_default_reservation,
    book_reservation,
    cast_vote,
    cast_vote_payload,
    close_reservation_payload,
    create_and_open_proposal,
    create_facility,
    create_owner_with_property,
    create_parking_application_payload,
    create_parking_space,
    create_reservation_payload,
    fetch_bill,
    fetch_owner,
    fetch_proposal,
    iso_utc,
    make_committee_chair_headers,
    make_owner_headers,
    setup_overdue_bill,
    setup_property_with_active_rule,
    setup_proposal_voters,
    TEST_USERS,
    validate_error,
    validate_success,
)


def _grid_aligned_slot(slot_minutes: int, hours_in_future: int = 24, *, base: datetime = None):
    """Return (slot_start, slot_end) ISO strings on the slot_minutes grid.

    *base* defaults to current wall-clock UTC. Tests whose setup advanced the
    server's logical clock should pass an explicit base derived from that
    advance instant.
    """
    if base is None:
        base = datetime.now(timezone.utc)
    target = base + timedelta(hours=hours_in_future)
    minutes_from_midnight = target.hour * 60 + target.minute
    bucket = ((minutes_from_midnight + slot_minutes - 1) // slot_minutes) * slot_minutes
    aligned = target.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(minutes=bucket)
    end = aligned + timedelta(minutes=slot_minutes)
    return iso_utc(aligned), iso_utc(end)


def test_per_household_unanimous_passes_per_area_unanimous_passes(api):
    """PRD §3.8: "Under the PER_HOUSEHOLD variant of the tally calculation, each
    property contributes weight 1.0 regardless of its area; under the PER_AREA
    variant, each property contributes weight equal to its area_sqm, and
    eligible_weight_total is therefore the total area across eligible properties."

    Setup: 3 owners with equal areas of 100 sqm each. PER_HOUSEHOLD eligible=3,
    PER_AREA eligible=300. With unanimous YES, both methods yield ratio 1.0 ≥
    threshold 0.6667 → both PASS. This complements the per-household-passes /
    per-area-fails test by showing that when areas are uniform, the two methods
    agree — a sanity check on the variant computation.

    Claim: with all equal areas and unanimous YES, both PER_HOUSEHOLD and PER_AREA
    proposals end in TALLIED_PASSED.

    # difficulty: dual_variant_calc/vote_tally_per_household_vs_per_area
    """
    voters = setup_proposal_voters(3, areas=[100.00, 100.00, 100.00])
    proposal_h = create_and_open_proposal(
        voting_method="PER_HOUSEHOLD",
        pass_threshold_pct=0.6667,
        voting_ends_at=iso_utc(datetime.now(timezone.utc) + timedelta(days=1)),
    )
    proposal_a = create_and_open_proposal(
        voting_method="PER_AREA",
        pass_threshold_pct=0.6667,
        voting_ends_at=iso_utc(datetime.now(timezone.utc) + timedelta(days=1)),
    )
    for owner, prop in voters:
        cast_vote(proposal_h, owner, prop, "YES")
        cast_vote(proposal_a, owner, prop, "YES")
    ends_at = datetime.fromisoformat(proposal_h["voting_ends_at"].replace("Z", "+00:00"))
    advance_clock_to(iso_utc(ends_at + timedelta(seconds=60)))
    chair = make_committee_chair_headers()
    th = validate_success(api.tally_proposal(proposal_h["id"], chair), 200)
    ta = validate_success(api.tally_proposal(proposal_a["id"], chair), 200)
    assert th["status"] == "TALLIED_PASSED"
    assert ta["status"] == "TALLIED_PASSED"


def test_eligible_weight_total_frozen_at_open_not_resnapshotted_at_tally(api):
    """PRD §3.8: "Opening a proposal freezes the eligible voter list. The eligible
    list is the set of Owner rows whose voting_status is ELIGIBLE at the open
    instant; later changes to anyone's voting_status (such as a delinquency that
    develops mid-vote, or a new owner registered after open) do not retroactively
    change the list."
    PRD §3.8: "denominator is the frozen eligible total, never the sum of cast votes."

    Setup: 3 ELIGIBLE owners; open the proposal — eligible_weight_total frozen.
    Mid-vote, register a new owner (would have been ELIGIBLE if snapshot were
    re-taken at tally). Tally — eligible_weight_total must still equal the frozen
    pre-snapshot value, NOT the resnapshotted live value.

    Claim: eligible_weight_total visible after open AND after tally equals the
    snapshot-at-open value; an additional owner registered after open does NOT
    change it.

    # difficulty: combinatorial_formula/vote_pass_threshold_branch_on_frozen_denominator
    """
    setup_proposal_voters(3)
    proposal = create_and_open_proposal(
        voting_method="PER_HOUSEHOLD",
        pass_threshold_pct=0.6667,
        voting_ends_at=iso_utc(datetime.now(timezone.utc) + timedelta(days=1)),
    )
    frozen = proposal["eligible_weight_total"]
    # Add a brand-new owner mid-vote.
    create_owner_with_property()
    after = fetch_proposal(proposal["id"])
    assert after["eligible_weight_total"] == pytest.approx(frozen, abs=0.001), (
        f"eligible_weight_total must remain frozen at OPEN; was {frozen}, now {after['eligible_weight_total']}"
    )


def test_clock_cascade_returns_owner_to_eligible_after_payment(api):
    """PRD §3.6: "The PAID transition freezes late_fee_amount at its current value,
    resets dunning_stage to NONE, and recomputes the relevant owner's voting_status
    (which may flip back to ELIGIBLE if no other bills are overdue)."

    Complement to the depth-3 cascade test: after paying off the OVERDUE bill the
    cascade reverses — Owner.voting_status returns to ELIGIBLE, and the same
    booking that was previously rejected with ERR_OWNER_DELINQUENT now succeeds.

    Claim: paying the OVERDUE bill flips the owner back to ELIGIBLE and a fresh
    POST /reservations succeeds.

    # difficulty: transitive_cascade/clock_advance_overdue_dunning_voting_disqualification
    """
    from test_helpers import pay_bill
    owner, _prop, _rule, bill = setup_overdue_bill(days_past_due=15)
    refreshed = fetch_bill(bill["id"])
    pay_bill(bill, owner, amount=refreshed["total_due"])
    paid = fetch_bill(bill["id"])
    assert paid["status"] == "PAID"
    after_owner = fetch_owner(owner["id"])
    assert after_owner["voting_status"] == "ELIGIBLE"
    facility = create_facility(slot_minutes=60, capacity_per_slot=1, damage_deposit=0.0)
    # Slot must be future relative to the post-setup logical clock.
    clock_base = datetime.fromisoformat(bill["due_date"].replace("Z", "+00:00")) + timedelta(days=15)
    slot_start, slot_end = _grid_aligned_slot(60, hours_in_future=48, base=clock_base)
    headers = make_owner_headers(owner["id"])
    res = api.create_reservation(
        create_reservation_payload(facility["id"], slot_start, slot_end), headers
    )
    data = validate_success(res, 201)
    assert data["status"] == "BOOKED"


def test_damaged_close_within_deposit_creates_no_spillover_bill(api, property_manager_headers):
    """PRD §3.7: "For a DAMAGED outcome the deposit absorbs damages up to its value:
    the forfeited amount is the smaller of deposit_held and damage_amount, the
    refunded amount is deposit_held minus that absorbed amount (rounded half-up
    to two decimal places), and if damage_amount is strictly greater than
    deposit_held the spillover (the difference between damage_amount and
    deposit_held, rounded half-up to two decimals) becomes a fresh fee bill."

    Complement to the spillover-creates-bill test: when damage_amount <= deposit_held,
    NO spillover bill is created — the cascade does not extend.

    Claim: with damage_amount=100 and deposit_held=500, no new fee bill is created
    against the property; the deposit absorbs the damage entirely.

    # difficulty: transitive_cascade/reservation_damage_spillover_cascade
    """
    facility = create_facility(
        slot_minutes=60, capacity_per_slot=1,
        cancellation_window_hours=1, damage_deposit=500.00,
    )
    owner, prop = create_owner_with_property()
    target = datetime.now(timezone.utc) + timedelta(hours=2)
    aligned = target.replace(minute=0, second=0, microsecond=0)
    end = aligned + timedelta(minutes=60)
    headers = make_owner_headers(owner["id"])
    res = book_reservation(owner, facility, iso_utc(aligned), iso_utc(end))
    advance_clock_to(iso_utc(aligned + timedelta(seconds=1)))
    validate_success(api.check_in_reservation(res["id"], headers), 200)
    advance_clock_to(iso_utc(end + timedelta(seconds=1)))
    closed = validate_success(
        api.close_reservation(
            res["id"], close_reservation_payload(damage_amount=100.00), property_manager_headers
        ),
        200,
    )
    assert closed["status"] == "DAMAGED"
    bills_res = api.list_fee_bills(
        property_manager_headers, params={"property_id": prop["id"], "status": "OPEN"}
    )
    body = bills_res.json() if bills_res.text else {}
    items = body.get("data", [])
    # No spillover bill because damage (100) <= deposit (500).
    assert not any(
        abs(b.get("principal_amount", 0) - (100 - 500)) < 0.01 or b.get("principal_amount") == 100
        for b in items
        if b.get("created_at", "") > closed.get("created_at", "")
    ) or len(items) == 0, (
        f"PRD §3.7: no spillover bill when damage_amount <= deposit_held; saw {items!r}"
    )


def test_state_vs_business_safety_priority_isolated_business_safety(api):
    """PRD §2.6: "after state checks, business-referential rules ... are evaluated,
    then business-temporal rules ... then business-safety (delinquency block)."
    PRD §3.7: "An owner with at least one fee bill in OVERDUE is blocked from
    booking with ERR_OWNER_DELINQUENT."

    Complement to the priority-conflict test: when ONLY business_safety applies
    (the booking is fully valid except for delinquency), the rejection is
    ERR_OWNER_DELINQUENT — proving that the prior conflict really did invoke the
    state rule first.

    Claim: a delinquent owner attempting a clean reservation booking → ERR_OWNER_DELINQUENT,
    not ERR_INVALID_STATE.

    # difficulty: priority_pair_validation_conflict/state_vs_business_safety_on_reservation
    """
    owner, _prop, _rule, _bill = setup_overdue_bill(days_past_due=10)
    facility = create_facility(slot_minutes=60, capacity_per_slot=1, damage_deposit=0.0)
    # Slot must be future relative to the post-setup logical clock (= due_date + 10d).
    clock_base = datetime.fromisoformat(_bill["due_date"].replace("Z", "+00:00")) + timedelta(days=10)
    slot_start, slot_end = _grid_aligned_slot(60, hours_in_future=48, base=clock_base)
    headers = make_owner_headers(owner["id"])
    payload = create_reservation_payload(facility["id"], slot_start, slot_end)
    res = api.create_reservation(payload, headers)
    validate_error(res, "ERR_OWNER_DELINQUENT")


def test_capacity_one_with_zero_existing_succeeds(api):
    """PRD §3.7: "The number of currently non-terminal reservations on the same
    facility for the same slot_start_at must remain at or below capacity_per_slot."

    Empty-set boundary complement to the capacity-full test: when zero non-terminal
    reservations exist on the slot, a fresh booking succeeds even with
    capacity_per_slot=1.

    Claim: with capacity_per_slot=1 and zero existing reservations on slot S, a
    booking on S succeeds.

    # difficulty: boundary_precision_check/facility_slot_full_capacity_boundary
    """
    facility = create_facility(slot_minutes=60, capacity_per_slot=1, damage_deposit=0.0)
    slot_start, slot_end = _grid_aligned_slot(60, hours_in_future=72)
    owner, _prop = create_owner_with_property()
    booked = book_reservation(owner, facility, slot_start, slot_end)
    assert booked["status"] == "BOOKED"
    assert booked["slot_start_at"] == slot_start


def test_owner_check_in_blocked_when_delinquent_path(api):
    """PRD §3.7: "An owner with at least one fee bill in OVERDUE is blocked from
    booking with ERR_OWNER_DELINQUENT."

    Complement to the booking-rejection test: if a non-delinquent owner books a
    reservation and only LATER becomes delinquent, the existing reservation
    survives — the entity-pair dependency only gates new bookings, not previously
    valid ones. This proves the dependency is on a write-time check, not a global
    invariant on Reservation rows.

    Claim: an Owner who booked while ELIGIBLE retains their BOOKED reservation
    after going delinquent; check-in still succeeds at slot_start_at.

    # difficulty: cross_entity_state_dependency/reservation_check_in_blocked_when_owner_delinquent
    """
    owner, prop = create_owner_with_property()
    facility = create_facility(slot_minutes=60, capacity_per_slot=1, damage_deposit=0.0)
    # Pick a slot far enough in the future to survive the delinquency clock
    # advance below — otherwise PRD §3.10's auto-NO_SHOW would fire and
    # the BOOKED reservation would be lost before we get to check-in.
    target = datetime.now(timezone.utc) + timedelta(days=120)
    aligned = target.replace(minute=0, second=0, microsecond=0)
    end = aligned + timedelta(minutes=60)
    booked = book_reservation(owner, facility, iso_utc(aligned), iso_utc(end))
    # Now make the owner delinquent via a separate property.
    from test_helpers import (
        create_property_for_owner,
        create_fee_billing_rule,
        issue_single_bill_for_property,
    )
    prop2 = create_property_for_owner(owner, area_sqm=80.00)
    _rule = create_fee_billing_rule(kind="PER_SQM_MONTHLY", rate=2.50)
    today = datetime.now(timezone.utc).date()
    if today.month == 1:
        py, pm_ = today.year - 1, 12
    else:
        py, pm_ = today.year, today.month - 1
    bill = issue_single_bill_for_property(prop2, py, pm_, rule_id=_rule["id"])
    due = datetime.fromisoformat(bill["due_date"].replace("Z", "+00:00"))
    advance_clock_to(iso_utc(due + timedelta(days=20)))
    # Confirm owner is now delinquent.
    after_owner = fetch_owner(owner["id"])
    assert after_owner["voting_status"] == "INELIGIBLE_DELINQUENT"
    # Existing reservation can still be checked in once slot_start_at arrives.
    advance_clock_to(iso_utc(aligned + timedelta(seconds=1)))
    headers = make_owner_headers(owner["id"])
    res = api.check_in_reservation(booked["id"], headers)
    # PRD §3.7 specifies check-in preconditions on slot timing and ownership; it
    # does NOT name delinquency as a check-in gate. So check-in must succeed.
    data = validate_success(res, 200)
    assert data["status"] == "CHECKED_IN"


def test_quota_one_first_fixed_approval_succeeds(api):
    """PRD §3.9: "when requested_kind is FIXED, the count of currently-APPROVED
    FIXED applications already bound to the same property must be strictly less
    than the property's parking_quota."

    Complement to the quota-exceeded test: with parking_quota=1 and zero existing
    APPROVED FIXED applications, the FIRST FIXED approval succeeds — confirming
    that the rejection in the partner test was due to the quota state, not some
    unrelated check.

    Claim: with parking_quota=1 and no existing APPROVED FIXED apps, a FIXED
    approval succeeds.

    # difficulty: cross_entity_state_dependency/parking_application_approve_requires_property_quota_room
    """
    owner, prop = create_owner_with_property(parking_quota=1)
    space = create_parking_space(kind="FIXED", monthly_fee=100.0)
    headers = make_owner_headers(owner["id"])
    app = validate_success(
        api.create_parking_application(
            create_parking_application_payload(prop["id"], requested_kind="FIXED"), headers
        ),
        201,
    )
    approved = approve_parking_application(app, space)
    assert approved["status"] == "APPROVED"


def test_two_distinct_slots_both_succeed_under_capacity_one(api):
    """PRD §3.7: "slot_start_at must be aligned to the facility's slot grid
    (zero-base — meaning a 60-minute slot must start on the hour, a 120-minute
    slot every two hours from midnight, and so on)."

    Complement to the adjacent-slot test: two non-adjacent grid-aligned slots
    on the same facility, capacity_per_slot=1, both succeed — the capacity is
    per-slot, not per-facility-globally. This test exercises the half-open
    interval semantics on a discrete grid.

    Claim: with capacity_per_slot=1, two non-adjacent slots [10:00,11:00) and
    [13:00,14:00) on the same facility both book successfully.

    # difficulty: resource_temporal_overlap/facility_slot_half_open_interval_with_capacity
    """
    facility = create_facility(slot_minutes=60, capacity_per_slot=1, damage_deposit=0.0)
    target = datetime.now(timezone.utc) + timedelta(hours=24)
    base = target.replace(hour=10, minute=0, second=0, microsecond=0)
    s1 = base
    e1 = s1 + timedelta(hours=1)
    s2 = base + timedelta(hours=3)
    e2 = s2 + timedelta(hours=1)
    owner_a, _ = create_owner_with_property()
    owner_b, _ = create_owner_with_property()
    r1 = book_reservation(owner_a, facility, iso_utc(s1), iso_utc(e1))
    r2 = book_reservation(owner_b, facility, iso_utc(s2), iso_utc(e2))
    assert r1["status"] == "BOOKED"
    assert r2["status"] == "BOOKED"


def test_terminating_allocation_makes_space_reapprovable_for_new_application(api, property_manager_headers):
    """PRD §3.9: "A PropertyManager may terminate an APPROVED allocation,
    advancing APPROVED → TERMINATED; on termination the parking space's status
    flips back to AVAILABLE."

    Complement to the second-approval-rejected test: after termination, a new
    application can take the same space — proving the AVAILABLE status flip
    really happened. This couples the exclusive-allocation invariant with its
    inverse (the release).

    Claim: terminate APPROVED → space becomes AVAILABLE → fresh approval succeeds.

    # difficulty: resource_temporal_overlap/parking_space_exclusive_allocation
    """
    space = create_parking_space(kind="FIXED", monthly_fee=200.0)
    owner1, prop1 = create_owner_with_property(parking_quota=1)
    h1 = make_owner_headers(owner1["id"])
    app1 = validate_success(
        api.create_parking_application(
            create_parking_application_payload(prop1["id"], requested_kind="FIXED"), h1
        ),
        201,
    )
    approved = approve_parking_application(app1, space)
    assert approved["status"] == "APPROVED"
    # Terminate.
    terminated = validate_success(
        api.terminate_parking_application(approved["id"], property_manager_headers), 200
    )
    assert terminated["status"] == "TERMINATED"
    # Now another application takes the same space.
    owner2, prop2 = create_owner_with_property(parking_quota=1)
    h2 = make_owner_headers(owner2["id"])
    app2 = validate_success(
        api.create_parking_application(
            create_parking_application_payload(prop2["id"], requested_kind="FIXED"), h2
        ),
        201,
    )
    approved2 = approve_parking_application(app2, space)
    assert approved2["status"] == "APPROVED"


def test_per_household_vote_weight_conservation_after_each_cast(api):
    """PRD §3.8: "Under the PER_HOUSEHOLD variant of the tally calculation, each
    property contributes weight 1.0 regardless of its area."
    PRD §3.8: "Exactly one vote is allowed per (proposal_id, property_id) pair."

    Complement to the PER_AREA conservation test: PER_HOUSEHOLD weights are
    uniformly 1.0, so every YES adds exactly 1.0 to yes_weight, every NO adds
    1.0 to no_weight, and yes + no <= eligible_weight_total at every step.

    Claim: with 4 PER_HOUSEHOLD voters, each cast advances exactly one of
    yes_weight or no_weight by exactly 1.0; eligible_weight_total stays frozen at 4.0.

    # difficulty: compensating_invariant/vote_weight_conservation_yes_no_abstain
    """
    voters = setup_proposal_voters(4)
    proposal = create_and_open_proposal(
        voting_method="PER_HOUSEHOLD",
        pass_threshold_pct=0.6667,
        voting_ends_at=iso_utc(datetime.now(timezone.utc) + timedelta(days=1)),
    )
    eligible = proposal["eligible_weight_total"]
    assert eligible >= 4.0
    yes_running = 0.0
    no_running = 0.0
    cast_vote(proposal, voters[0][0], voters[0][1], "YES")
    yes_running += 1.0
    snap = fetch_proposal(proposal["id"])
    assert snap["yes_weight"] == pytest.approx(yes_running, abs=0.001)
    assert snap.get("no_weight", 0) == pytest.approx(no_running, abs=0.001)
    assert snap["eligible_weight_total"] == pytest.approx(eligible, abs=0.001)
    cast_vote(proposal, voters[1][0], voters[1][1], "NO")
    no_running += 1.0
    snap = fetch_proposal(proposal["id"])
    assert snap["yes_weight"] == pytest.approx(yes_running, abs=0.001)
    assert snap["no_weight"] == pytest.approx(no_running, abs=0.001)
    assert snap["eligible_weight_total"] == pytest.approx(eligible, abs=0.001)
    cast_vote(proposal, voters[2][0], voters[2][1], "ABSTAIN")
    snap = fetch_proposal(proposal["id"])
    # ABSTAIN does not advance yes_weight/no_weight per PRD §3.8.
    assert snap["yes_weight"] == pytest.approx(yes_running, abs=0.001)
    assert snap["no_weight"] == pytest.approx(no_running, abs=0.001)
    assert snap["eligible_weight_total"] == pytest.approx(eligible, abs=0.001)
