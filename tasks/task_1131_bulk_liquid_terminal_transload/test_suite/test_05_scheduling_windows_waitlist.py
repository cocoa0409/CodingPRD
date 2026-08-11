"""Movement creation gating, resource window occupation semantics, validation
ordering on the schedule path, and waitlist promotion (PRD §2.7, §2.9, §3.5)."""
import pytest

from test_helpers import (
    ApiErrorId,
    create_customer,
    create_lease,
    create_movement_payload,
    setup_lease_with_allocation,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.fixtures import (
    MANAGER,
    OPERATOR,
    SCHEDULER,
    create_resource,
    create_tank,
    get_movement,
    nominate_movement,
    release_allocation,
    schedule_movement,
    set_clock,
    suspend_lease,
)


def _nominate_100(bundle, window_start="2026-05-10T08:00:00Z", window_end="2026-05-10T12:00:00Z"):
    return nominate_movement(bundle["lease"]["id"], bundle["tank"]["id"],
                             declared_volume_bbl=100,
                             window_start=window_start, window_end=window_end)


class TestMovementCreateRequiresActiveLease:
    def _draft_lease_setup(self):
        customer = create_customer(name="Atlas Commodities", contact_email="ops@atlas.example")
        tank = create_tank()
        lease = create_lease(customer["id"])  # DRAFT: no allocation, never activated
        return lease, tank

    def test_create_on_draft_lease_rejected(self, api):
        """PRD §3.2: "Creating a movement and scheduling it both require the
        lease to be `ACTIVE`." and "Each of these violations surfaces as
        `ERR_LEASE_NOT_ACTIVE` (HTTP 409)."

        Design: Difficulty/cross_entity_state_dependency/movement_create_requires_active_lease
        """
        lease, tank = self._draft_lease_setup()
        payload = create_movement_payload(lease["id"], tank["id"])
        resp = api.create_movement(payload, SCHEDULER)
        validate_error(resp, ApiErrorId.ERR_LEASE_NOT_ACTIVE)
        assert resp.status_code == 409

    def test_rejected_create_persists_no_movement(self, api):
        """PRD §3.2: "Creating a movement and scheduling it both require the
        lease to be `ACTIVE`." The rejected nomination must not persist a
        movement: a fresh list read returns an empty data array.

        Design: Difficulty/cross_entity_state_dependency/movement_create_requires_active_lease
        """
        lease, tank = self._draft_lease_setup()
        payload = create_movement_payload(lease["id"], tank["id"])
        validate_error(api.create_movement(payload, SCHEDULER), ApiErrorId.ERR_LEASE_NOT_ACTIVE)
        data, meta = validate_paginated(api.list_movements(SCHEDULER))
        assert data == [], f"no Movement row may be created, got {len(data)}"
        assert meta["total_count"] == 0


class TestDockWindowOccupation:
    def _dock_setup(self):
        bundle = setup_lease_with_allocation(customer_name="Great Lakes Terminal")
        resource = create_resource("DOCK")
        return bundle, resource

    def test_adjacent_windows_allowed(self, api):
        """PRD §2.7: "Occupation windows are half-open intervals: a movement
        occupies its resource from `window_start` inclusive to `window_end`
        exclusive." and "Pure adjacency is allowed: an existing window whose
        end equals the candidate's start does not conflict."
        A occupies [08:00, 12:00); B nominates [12:00, 16:00): both SCHEDULED.

        Design: Difficulty/resource_temporal_overlap/dock_window_adjacency_allowed_overlap_rejected
        """
        bundle, resource = self._dock_setup()
        ma = _nominate_100(bundle, "2026-05-10T08:00:00Z", "2026-05-10T12:00:00Z")
        schedule_movement(ma["id"], resource["id"])
        mb = _nominate_100(bundle, "2026-05-10T12:00:00Z", "2026-05-10T16:00:00Z")
        scheduled_b = schedule_movement(mb["id"], resource["id"])
        assert get_movement(ma["id"])["status"] == "SCHEDULED"
        assert scheduled_b["status"] == "SCHEDULED", (
            "adjacent start == predecessor window_end must not conflict"
        )

    def test_straddling_window_rejected(self, api):
        """PRD §2.7: "a candidate window conflicts with an existing one
        whenever the candidate's start is before the existing window's end and
        the existing window's start is before the candidate's end, considering
        movements in `SCHEDULED`, `ARRIVED`, `IN_PROGRESS`, or `SUSPENDED`
        status on that resource." and "A schedule attempt that collides under
        these rules is rejected with `ERR_WINDOW_CONFLICT` (HTTP 409)."
        C nominates [11:00, 13:00), straddling A [08:00,12:00) and B
        [12:00,16:00).

        Design: Difficulty/resource_temporal_overlap/dock_window_adjacency_allowed_overlap_rejected
        """
        bundle, resource = self._dock_setup()
        ma = _nominate_100(bundle, "2026-05-10T08:00:00Z", "2026-05-10T12:00:00Z")
        schedule_movement(ma["id"], resource["id"])
        mb = _nominate_100(bundle, "2026-05-10T12:00:00Z", "2026-05-10T16:00:00Z")
        schedule_movement(mb["id"], resource["id"])
        mc = _nominate_100(bundle, "2026-05-10T11:00:00Z", "2026-05-10T13:00:00Z")
        resp = api.schedule_movement(mc["id"], {"resource_id": resource["id"]}, SCHEDULER)
        validate_error(resp, ApiErrorId.ERR_WINDOW_CONFLICT)
        assert resp.status_code == 409
        assert get_movement(mc["id"])["status"] == "NOMINATED"


class TestScheduleValidationOrdering:
    def _suspended_lease_released_allocation(self):
        bundle = setup_lease_with_allocation(customer_name="Pioneer Logistics")
        resource = create_resource("DOCK")
        movement = _nominate_100(bundle)
        suspend_lease(bundle["lease"]["id"])
        release_allocation(bundle["allocation"]["id"])
        return bundle, resource, movement

    def test_suspended_lease_error_returned(self, api):
        """PRD §3.5: "The schedule path checks, in the order established by
        §2.9: the lease is `ACTIVE` (`ERR_LEASE_NOT_ACTIVE`); the tank is
        `AVAILABLE` (`ERR_TANK_NOT_AVAILABLE`); the named resource is `ACTIVE`
        (`ERR_RESOURCE_UNAVAILABLE`) and its type matches the movement's mode
        per the fixed mapping (`ERR_RESOURCE_TYPE_MISMATCH`); the requested
        window does not conflict under the occupation semantics of §2.7
        (`ERR_WINDOW_CONFLICT`); an `ACTIVE` allocation covers the
        lease-and-tank pair (`ERR_NO_ACTIVE_ALLOCATION`); and
        `declared_volume_bbl` does not exceed that allocation's
        `allocated_bbl` (`ERR_VOLUME_EXCEEDS_ALLOCATION`)."
        The lease check precedes the allocation check, so a request violating
        both returns ERR_LEASE_NOT_ACTIVE.

        Design: Difficulty/priority_pair_validation_conflict/schedule_suspended_lease_beats_missing_allocation
        """
        bundle, resource, movement = self._suspended_lease_released_allocation()
        resp = api.schedule_movement(movement["id"], {"resource_id": resource["id"]}, SCHEDULER)
        validate_error(resp, ApiErrorId.ERR_LEASE_NOT_ACTIVE)
        assert resp.status_code == 409

    def test_rejected_schedule_leaves_movement_nominated(self, api):
        """PRD §3.5: "The schedule path checks, in the order established by
        §2.9: the lease is `ACTIVE` (`ERR_LEASE_NOT_ACTIVE`)". The fiscal-tier
        ERR_NO_ACTIVE_ALLOCATION must not mask the state-tier error, and the
        rejected schedule leaves the movement in NOMINATED.

        Design: Difficulty/priority_pair_validation_conflict/schedule_suspended_lease_beats_missing_allocation
        """
        bundle, resource, movement = self._suspended_lease_released_allocation()
        resp = api.schedule_movement(movement["id"], {"resource_id": resource["id"]}, SCHEDULER)
        err = validate_error(resp, ApiErrorId.ERR_LEASE_NOT_ACTIVE)
        assert err["error_id"] != "ERR_NO_ACTIVE_ALLOCATION"
        assert get_movement(movement["id"])["status"] == "NOMINATED"


class TestWaitlistPromotion:
    def _scheduled_plus_waiters(self, api, num_waiters=1, stagger_clock=False):
        bundle = setup_lease_with_allocation(customer_name="Waitlist Co")
        resource = create_resource("DOCK")
        ma = _nominate_100(bundle)
        schedule_movement(ma["id"], resource["id"])
        waiters = []
        for i in range(num_waiters):
            if stagger_clock:
                set_clock(f"2026-05-01T00:0{i + 1}:00Z")
            w = _nominate_100(bundle)
            resp = api.schedule_movement(w["id"], {"resource_id": resource["id"]}, SCHEDULER)
            validate_error(resp, ApiErrorId.ERR_WINDOW_CONFLICT)  # waiter blocked pre-cancel
            waiters.append(w)
        return bundle, resource, ma, waiters

    def test_cancel_promotes_waitlisted_movement(self, api):
        """PRD §3.5: "Cancelling a `SCHEDULED` movement frees its resource
        window and immediately runs waitlist promotion: among all movements
        still `NOMINATED` whose mode maps to the freed resource's type and
        whose window would not conflict with the remaining occupation on that
        resource under the same occupation rule used at schedule time, the
        system ranks candidates by `created_at` ascending with `sequence_no`
        ascending as the tie-break — never by id — and promotes the single
        top-ranked candidate to `SCHEDULED`, setting its `resource_id` and
        computing its `demurrage_estimated_amount`."

        Design: Difficulty/transitive_cascade/cancel_triggers_waitlist_promotion
        """
        bundle, resource, ma, waiters = self._scheduled_plus_waiters(api)
        mb = waiters[0]
        cancelled = validate_success(api.cancel_movement(ma["id"], SCHEDULER))
        assert cancelled["status"] == "CANCELLED"
        promoted = get_movement(mb["id"])
        assert promoted["status"] == "SCHEDULED", "the freed window must promote the waiter"
        assert promoted["resource_id"] == resource["id"]

    def test_cancel_marks_cancelled_and_promotion_visible_on_reread(self, api):
        """PRD §3.5: "Cancelling a movement is possible from `NOMINATED` or
        `SCHEDULED`." and "promotes the single top-ranked candidate to
        `SCHEDULED`, setting its `resource_id`". Both outcomes are re-readable:
        the cancelled movement stays CANCELLED and the promoted movement reads
        SCHEDULED with the freed resource assigned.

        Design: Difficulty/transitive_cascade/cancel_triggers_waitlist_promotion
        """
        bundle, resource, ma, waiters = self._scheduled_plus_waiters(api)
        mb = waiters[0]
        api.cancel_movement(ma["id"], SCHEDULER)
        assert get_movement(ma["id"])["status"] == "CANCELLED"
        promoted = get_movement(mb["id"])
        assert promoted["status"] == "SCHEDULED"
        assert promoted["resource_id"] == resource["id"]

    def test_promotion_prefers_earlier_created(self, api):
        """PRD §3.5: "the system ranks candidates by `created_at` ascending
        with `sequence_no` ascending as the tie-break — never by id — and
        promotes the single top-ranked candidate to `SCHEDULED`". B (created at
        00:01) beats C (created at 00:02); C remains NOMINATED, which is a
        no-op rather than an error: "An empty candidate set is a no-op, not an
        error."

        Design: Corner/calculations/waitlist_promotion_prefers_earlier_created
        """
        bundle, resource, ma, waiters = self._scheduled_plus_waiters(api, num_waiters=2,
                                                                     stagger_clock=True)
        mb, mc = waiters
        api.cancel_movement(ma["id"], SCHEDULER)
        assert get_movement(mb["id"])["status"] == "SCHEDULED", "earlier created_at wins"
        assert get_movement(mc["id"])["status"] == "NOMINATED", "later candidate is not promoted"


class TestImmediateConsistency:
    def test_schedule_response_contains_estimated_demurrage(self, api):
        """PRD §3.5: "On success the movement's `resource_id` is set and its
        `demurrage_estimated_amount` is computed as the forward-looking
        estimate of §3.9."
        PRD §3.9: "The scheduled estimate, computed when a movement is
        scheduled and stored as `demurrage_estimated_amount`, is
        forward-looking: it takes the exact rational duration in hours from
        `window_start` to `window_end`, subtracts the mode's free hours, clamps
        the result below at zero, multiplies by the mode's hourly rate, and
        rounds half-up to 2 decimal places."
        A 30-hour VESSEL window: (30 - 24) * 1200.00 == 7200.00, visible in the
        mutating response itself.

        Design: Corner/consistency_model/schedule_response_immediately_shows_estimate
        """
        bundle = setup_lease_with_allocation(customer_name="Immediate Co")
        resource = create_resource("DOCK")
        movement = nominate_movement(
            bundle["lease"]["id"], bundle["tank"]["id"], declared_volume_bbl=100,
            window_start="2026-05-10T00:00:00Z", window_end="2026-05-11T06:00:00Z")
        resp = api.schedule_movement(movement["id"], {"resource_id": resource["id"]}, SCHEDULER)
        data = validate_success(resp)
        assert data["status"] == "SCHEDULED"
        assert data["demurrage_estimated_amount"] == pytest.approx(7200.00, abs=0.01), (
            f"estimate must be in the schedule response, got {data['demurrage_estimated_amount']}"
        )
