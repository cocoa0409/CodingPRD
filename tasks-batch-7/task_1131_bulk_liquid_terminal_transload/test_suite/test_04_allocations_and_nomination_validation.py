"""Tank allocation capacity sweep, allocation lifecycle lockdown, and movement
nomination validations (PRD §2.9, §3.4, §3.5)."""
import pytest

from test_helpers import (
    ApiErrorId,
    create_customer,
    create_lease,
    create_movement_payload,
    setup_lease_with_allocation,
    validate_error,
    validate_success,
)
from test_helpers.fixtures import (
    MANAGER,
    OPERATOR,
    SCHEDULER,
    activate_allocation,
    create_allocation,
    create_tank,
    release_allocation,
)


class TestAggregateCapacitySweep:
    def _two_lease_boundary_setup(self, api):
        """Two leases on one 200000-bbl tank (working capacity 189900);
        L1 ACTIVE with 100000 over May–Jul, L2 ACTIVE with 89900 over
        Jun–Aug — overlapping June/July dates sum to exactly the cap."""
        c1 = create_customer(name="Lakeshore Chemical", contact_email="lease@lakeshore.example")
        c2 = create_customer(name="Prairie Fuels", contact_email="lease@prairie.example")
        tank = create_tank(capacity_bbl=200000, heel_bbl=100)
        assert tank["working_capacity_bbl"] == 189900
        l1 = create_lease(c1["id"], committed_capacity_bbl=150000)
        a1 = create_allocation(l1["id"], tank["id"], allocated_bbl=100000,
                               period_start="2026-05-01", period_end="2026-07-31")
        activate_allocation(a1["id"])
        l2 = create_lease(c2["id"], committed_capacity_bbl=120000)
        a2 = create_allocation(l2["id"], tank["id"], allocated_bbl=89900,
                               period_start="2026-06-01", period_end="2026-08-31")
        return tank, l2, a2

    def test_overlap_at_exact_working_capacity_allowed(self, api):
        """PRD §3.4: "if any date's existing total plus the candidate's
        `allocated_bbl` would exceed the tank's `working_capacity_bbl`, the
        operation is rejected with `ERR_ALLOCATION_CAPACITY_EXCEEDED`
        (HTTP 409). Exact equality — the summed total landing exactly on
        working capacity — is allowed."
        100000 + 89900 == 189900 == working capacity: activation succeeds.

        Design: Difficulty/resource_temporal_overlap/tank_allocation_aggregate_capacity_overlap
        """
        _, _, a2 = self._two_lease_boundary_setup(api)
        activated = activate_allocation(a2["id"])
        assert activated["status"] == "ACTIVE"

    def test_one_barrel_over_capacity_rejected(self, api):
        """PRD §3.4: "if any date's existing total plus the candidate's
        `allocated_bbl` would exceed the tank's `working_capacity_bbl`, the
        operation is rejected with `ERR_ALLOCATION_CAPACITY_EXCEEDED`
        (HTTP 409)."
        100000 + 89900 + 1 == 189901 > 189900 on the overlapping June dates.

        Design: Difficulty/resource_temporal_overlap/tank_allocation_aggregate_capacity_overlap
        """
        tank, l2, a2 = self._two_lease_boundary_setup(api)
        activate_allocation(a2["id"])
        resp = api.create_tank_allocation(
            l2["id"],
            {"tank_id": tank["id"], "allocated_bbl": 1,
             "period_start": "2026-06-01", "period_end": "2026-06-30"},
            OPERATOR)
        validate_error(resp, ApiErrorId.ERR_ALLOCATION_CAPACITY_EXCEEDED)
        assert resp.status_code == 409


class TestAllocationLifecycle:
    def test_release_twice_rejected(self, api):
        """PRD §3.4: "Release — the compensating action of activation — moves
        an `ACTIVE` allocation to `RELEASED`".
        PRD §2.9: "then state-machine from-state matching (`ERR_INVALID_STATE`)"
        — RELEASED is terminal, so a second release is rejected.

        Design: Corner/state_machines/allocation_release_twice_rejected
        """
        bundle = setup_lease_with_allocation(customer_name="Release Co", allocated_bbl=10000,
                                             activate_lease_flag=False)
        release_allocation(bundle["allocation"]["id"])
        resp = api.release_tank_allocation(bundle["allocation"]["id"], OPERATOR)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        assert resp.status_code == 409
        alloc = validate_success(api.get_tank_allocation(bundle["allocation"]["id"], OPERATOR))
        assert alloc["status"] == "RELEASED"

    def test_period_outside_lease_dates_rejected(self, api):
        """PRD §3.4: "The period must satisfy `period_end` on or after
        `period_start` and must lie entirely within the lease's `start_date` to
        `end_date`; violations are rejected with
        `ERR_ALLOCATION_PERIOD_INVALID` (HTTP 422)."

        Design: Corner/validations/allocation_period_outside_lease_rejected
        """
        customer = create_customer(name="Period Co", contact_email="pe@example.com")
        tank = create_tank()
        lease = create_lease(customer["id"])  # 2026-01-01 .. 2026-12-31
        resp = api.create_tank_allocation(
            lease["id"],
            {"tank_id": tank["id"], "allocated_bbl": 10000,
             "period_start": "2026-06-01", "period_end": "2027-01-31"},
            OPERATOR)
        validate_error(resp, ApiErrorId.ERR_ALLOCATION_PERIOD_INVALID)
        assert resp.status_code == 422

    def test_activate_nonexistent_allocation_returns_404(self, api):
        """PRD §2.9: "the system resolves path identifiers strictly left to
        right and rejects with the 404 variant corresponding to the first
        identifier that fails to resolve", and reference resolution precedes
        state-machine matching, so an unknown allocation id yields
        ERR_ALLOCATION_NOT_FOUND (HTTP 404), never a state error.

        Design: Corner/validations/nonexistent_allocation_activate_returns_not_found
        """
        create_customer(name="404 Probe Co", contact_email="404@example.com")
        resp = api.activate_tank_allocation("11111111-2222-3333-4444-555555555555", OPERATOR)
        validate_error(resp, ApiErrorId.ERR_ALLOCATION_NOT_FOUND)
        assert resp.status_code == 404


class TestMovementNominationValidation:
    def test_window_end_equal_to_start_rejected(self, api):
        """PRD §3.5: "The window must open before it closes: a `window_end` not
        strictly after `window_start` is rejected with `ERR_WINDOW_INVALID`
        (HTTP 422)."

        Design: Corner/validations/window_end_not_after_start_rejected
        """
        bundle = setup_lease_with_allocation(customer_name="Window Co")
        payload = create_movement_payload(
            bundle["lease"]["id"], bundle["tank"]["id"],
            window_start="2026-05-10T08:00:00Z", window_end="2026-05-10T08:00:00Z")
        resp = api.create_movement(payload, SCHEDULER)
        validate_error(resp, ApiErrorId.ERR_WINDOW_INVALID)
        assert resp.status_code == 422

    def test_product_mismatch_rejected(self, api):
        """PRD §3.5: "The movement's `product_grade` must equal both the
        lease's and the tank's grade; a mismatch is rejected with
        `ERR_PRODUCT_MISMATCH` (HTTP 422)."

        Design: Corner/validations/product_mismatch_on_movement_create_rejected
        """
        bundle = setup_lease_with_allocation(customer_name="Mismatch Co")
        payload = create_movement_payload(
            bundle["lease"]["id"], bundle["tank"]["id"], product_grade="GASOLINE")
        resp = api.create_movement(payload, SCHEDULER)
        validate_error(resp, ApiErrorId.ERR_PRODUCT_MISMATCH)
        assert resp.status_code == 422

    def test_declared_volume_exceeding_allocation_rejected(self, api):
        """PRD §3.5: "`declared_volume_bbl` must be greater than zero and no
        greater than that allocation's `allocated_bbl`, failing which the
        request is rejected with `ERR_VOLUME_EXCEEDS_ALLOCATION` (HTTP 422)."
        1500 declared against a 1000-bbl ACTIVE allocation.

        Design: Corner/validations/volume_exceeding_allocation_rejected
        """
        bundle = setup_lease_with_allocation(customer_name="Overvolume Co", allocated_bbl=1000)
        payload = create_movement_payload(
            bundle["lease"]["id"], bundle["tank"]["id"], declared_volume_bbl=1500)
        resp = api.create_movement(payload, SCHEDULER)
        validate_error(resp, ApiErrorId.ERR_VOLUME_EXCEEDS_ALLOCATION)
        assert resp.status_code == 422
