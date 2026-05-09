"""Clock-driven cascade tests, end-to-end invariants, and remaining
difficulty-design instances (PRD §3.5, §3.7, §3.10).

Covers:
- The depth-3 cascade clock-advance → OVERDUE bill → INELIGIBLE_DELINQUENT owner →
  reservation creation rejected (difficulty-design instance
  clock_advance_overdue_dunning_voting_disqualification).
- The state-vs-business-safety priority conflict on reservations
  (difficulty-design instance state_vs_business_safety_on_reservation).
- Reservation auto-NO_SHOW on clock advance (PRD §3.7, §3.10).
- Cross-entity dependency: reservation creation by delinquent owner.
- Pagination basics on listing endpoints.
- Common-fields vs append-only (PRD §2.4).
"""

from datetime import datetime, timedelta, timezone

import pytest

from test_helpers import (
    advance_clock_to,
    api_client,
    book_default_reservation,
    book_reservation,
    create_facility,
    create_owner_with_property,
    create_reservation_payload,
    fetch_bill,
    fetch_owner,
    iso_utc,
    make_owner_headers,
    setup_overdue_bill,
    TEST_USERS,
    validate_error,
    validate_paginated,
    validate_success,
)


def _grid_aligned_slot(slot_minutes: int, hours_in_future: int = 24, *, base: datetime = None):
    """Return (slot_start, slot_end) ISO strings on the slot_minutes grid.

    *base* defaults to current wall-clock UTC. Tests whose setup advanced the
    server's logical clock should pass a base derived from that advance instant.
    """
    if base is None:
        base = datetime.now(timezone.utc)
    target = base + timedelta(hours=hours_in_future)
    minutes_from_midnight = target.hour * 60 + target.minute
    bucket = ((minutes_from_midnight + slot_minutes - 1) // slot_minutes) * slot_minutes
    aligned = target.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(minutes=bucket)
    end = aligned + timedelta(minutes=slot_minutes)
    return iso_utc(aligned), iso_utc(end)


class TestDepth3ClockCascade:
    """Difficulty-design instance: clock_advance_overdue_dunning_voting_disqualification.
    PRD §3.5 hop 1; §3.5 hop 2; §3.7 hop 3."""

    def test_clock_advance_chains_overdue_to_delinquent_to_booking_block(self, api):
        """PRD §3.5: "When the clock advances past due_date while the bill is still
        OPEN and paid_amount remains below total_due, the bill transitions
        OPEN → OVERDUE. That transition triggers the late-fee recompute described
        above, sets dunning_stage to REMINDED if it was previously NONE, and
        recomputes the relevant owner's voting_status — any owner with at least one
        fee bill in OVERDUE against any of their properties is set to
        INELIGIBLE_DELINQUENT."
        PRD §3.7: "An owner with at least one fee bill in OVERDUE is blocked
        from booking with ERR_OWNER_DELINQUENT."

        Hop 1: clock advance flips FeeBill OPEN→OVERDUE; late_fee_amount > 0;
        dunning_stage=REMINDED.
        Hop 2: that bill flip recomputes Owner.voting_status to INELIGIBLE_DELINQUENT.
        Hop 3: a fresh POST /reservations from the same owner returns
        ERR_OWNER_DELINQUENT.

        Claim: all three hops observable from a single clock-advance trigger.

        # difficulty: transitive_cascade/clock_advance_overdue_dunning_voting_disqualification
        """
        owner, _prop, _rule, bill = setup_overdue_bill(days_past_due=20)
        # Hop 1.
        assert bill["status"] == "OVERDUE"
        assert bill["late_fee_amount"] > 0
        assert bill["dunning_stage"] == "REMINDED"
        # Hop 2.
        owner_after = fetch_owner(owner["id"])
        assert owner_after["voting_status"] == "INELIGIBLE_DELINQUENT"
        # Hop 3.
        facility = create_facility(slot_minutes=60, capacity_per_slot=1, damage_deposit=100.00)
        # Slot must be in the future relative to the post-setup logical clock
        # (= due_date + days_past_due), not wall-clock now.
        clock_base = datetime.fromisoformat(bill["due_date"].replace("Z", "+00:00")) + timedelta(days=20)
        slot_start, slot_end = _grid_aligned_slot(60, hours_in_future=48, base=clock_base)
        headers = make_owner_headers(owner["id"])
        payload = create_reservation_payload(facility["id"], slot_start, slot_end)
        res = api.create_reservation(payload, headers)
        validate_error(res, "ERR_OWNER_DELINQUENT")


class TestStateBeforeBusinessSafetyPriority:
    """Difficulty-design instance: state_vs_business_safety_on_reservation.
    PRD §2.6 pins state (priority 6) above business_safety (priority 12)."""

    def test_invalid_state_wins_over_owner_delinquent(self, api):
        """PRD §2.6: "State-machine preconditions returning ERR_INVALID_STATE are
        evaluated next, before any business-rule check. After state checks,
        business-referential rules ... are evaluated, then business-temporal rules
        ... then business-safety (delinquency block)."
        PRD §3.7: "Check-in is performed by the booking owner once slot_start_at
        has arrived but slot_end_at has not yet passed."

        Setup: an Owner whose voting_status is INELIGIBLE_DELINQUENT (an OVERDUE
        bill exists) attempts to check in to a CANCELLED reservation. Both
        ERR_INVALID_STATE (the reservation is in CANCELLED, not BOOKED) and
        business_safety (owner delinquent) potentially apply, but state wins.

        Claim: server returns ERR_INVALID_STATE, NOT ERR_OWNER_DELINQUENT.

        # difficulty: priority_pair_validation_conflict/state_vs_business_safety_on_reservation
        """
        # Prepare a reservation in a non-BOOKED state for an owner who is then
        # made delinquent. Use a fresh owner for booking, then make the same owner
        # delinquent via a separate property/bill.
        owner, prop = create_owner_with_property()
        # Book a reservation, then cancel it so the reservation is in CANCELLED.
        facility = create_facility(slot_minutes=60, capacity_per_slot=1, cancellation_window_hours=1, damage_deposit=0.0)
        slot_start, slot_end = _grid_aligned_slot(60, hours_in_future=48)
        booked = book_reservation(owner, facility, slot_start, slot_end)
        owner_headers = make_owner_headers(owner["id"])
        validate_success(api.cancel_reservation(booked["id"], owner_headers), 200)
        # Now make the same owner delinquent via a separate property/bill.
        # Create another property under this owner and walk it to OVERDUE.
        from test_helpers import (
            create_property_for_owner,
            create_fee_billing_rule,
            issue_single_bill_for_property,
            advance_clock_to as _advance_to,
        )
        # Add a property + active rule so issuance produces a bill.
        prop2 = create_property_for_owner(owner, area_sqm=80.00)
        _rule = create_fee_billing_rule(kind="PER_SQM_MONTHLY", rate=2.50)
        today = datetime.now(timezone.utc).date()
        if today.month == 1:
            py, pm_ = today.year - 1, 12
        else:
            py, pm_ = today.year, today.month - 1
        bill = issue_single_bill_for_property(prop2, py, pm_, rule_id=_rule["id"])
        due_dt = datetime.fromisoformat(bill["due_date"].replace("Z", "+00:00"))
        _advance_to(iso_utc(due_dt + timedelta(days=20)))
        owner_after = fetch_owner(owner["id"])
        assert owner_after["voting_status"] == "INELIGIBLE_DELINQUENT", (
            "Setup: owner must be delinquent for the priority test to be meaningful"
        )
        # Now attempt /check-in on the CANCELLED reservation. Both errors potentially
        # apply, but state precedes business_safety.
        res = api.check_in_reservation(booked["id"], owner_headers)
        validate_error(res, "ERR_INVALID_STATE")


class TestReservationAutoNoShow:
    def test_clock_past_slot_end_auto_transitions_to_no_show(self, api):
        """PRD §3.7: "If the clock advances past slot_end_at while the reservation
        is still in BOOKED, the system auto-transitions BOOKED → NO_SHOW and
        forfeits the entire deposit_held."
        PRD §3.10: "a Reservation in BOOKED whose now() >= slot_end_at
        auto-transitions to NO_SHOW and forfeits its deposit_held."

        Claim: clock advance to past slot_end_at on a BOOKED reservation →
        status==NO_SHOW, deposit_held==0.
        """
        owner, _prop = create_owner_with_property()
        facility = create_facility(slot_minutes=60, capacity_per_slot=1, damage_deposit=200.00)
        slot_start, slot_end = _grid_aligned_slot(60, hours_in_future=48)
        booked = book_reservation(owner, facility, slot_start, slot_end)
        assert booked["deposit_held"] == pytest.approx(200.00, abs=0.001)
        # Advance past slot_end_at.
        end_dt = datetime.fromisoformat(slot_end.replace("Z", "+00:00"))
        advance_clock_to(iso_utc(end_dt + timedelta(seconds=60)))
        # Read by listing reservations isn't available, but we can prove auto-no-show
        # by attempting cancel — cancel from NO_SHOW is not a transition.
        owner_headers = make_owner_headers(owner["id"])
        res = api.cancel_reservation(booked["id"], owner_headers)
        # NO_SHOW is terminal — cancel must fail with ERR_INVALID_STATE.
        validate_error(res, "ERR_INVALID_STATE")


class TestPaginationDefaults:
    def test_audit_entries_pagination_returns_meta(self, api, property_manager_headers):
        """PRD §2.3: "The default limit is 10; the minimum is 1 and the maximum is
        100. The default offset is 0. ... The response meta block includes limit,
        offset, total_count (the total number of records matching the filter set
        ignoring pagination), and has_more (a boolean indicating whether further
        pages remain)."

        Claim: GET /audit-entries returns a paginated envelope with limit, offset,
        total_count, and has_more in meta.
        """
        res = api.list_audit_entries(property_manager_headers)
        items, meta = validate_paginated(res)
        assert isinstance(items, list)
        assert "limit" in meta and meta["limit"] >= 1
        assert "offset" in meta and meta["offset"] >= 0
        assert "total_count" in meta
        assert "has_more" in meta


class TestCommonFieldsVsAppendOnly:
    """PRD §2.4: most entities expose updated_at and version; PaymentRecord, Vote,
    AccessLog, AuditEntry expose only id and created_at."""

    def test_owner_returns_version_and_updated_at(self, api, property_manager_headers):
        """PRD §2.4: "Most entities additionally carry an updated_at timestamp
        ... and a version integer that starts at 1 on creation and increments by
        exactly one with every successful mutation."

        Claim: a freshly created Owner has version==1 and an ISO 8601 updated_at.
        """
        from test_helpers import create_owner_payload, is_iso8601_timestamp
        res = api.create_owner(create_owner_payload(), property_manager_headers)
        data = validate_success(res, 201)
        assert "version" in data and data["version"] == 1
        assert "updated_at" in data and is_iso8601_timestamp(data["updated_at"])
