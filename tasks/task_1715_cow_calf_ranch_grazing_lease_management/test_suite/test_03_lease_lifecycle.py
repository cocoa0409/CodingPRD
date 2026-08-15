"""Grazing lease lifecycle: suspend/reinstate cycle, aggregate capacity,
lazy expiry, terminal lockdown, and payload well-formedness."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    create_and_activate_lease,
    create_lease,
    create_lease_payload,
    create_pasture,
    create_ranch,
    get_success_data,
    set_clock,
    validate_error,
    validate_success,
)

RANCH_MGR = TEST_USERS["ranch_manager_headers"]
RANGE_MGR = TEST_USERS["range_manager_headers"]


def _cycle_lease(api):
    """Lease on a LEASED pasture, then run two full suspend/reinstate cycles
    and terminate. Returns (lease_id, created_version, final_lease)."""
    ranch = create_ranch(name="Cycle Ranch", hq_state="UT")
    pasture = create_pasture(ranch["id"], name="Lease Section", acreage=2000,
                             tenure="LEASED", base_capacity_aum=500)
    lease = create_lease(ranch["id"], pasture["id"], lessor_name="State Land Board",
                         aum_allotment=200, minimum_commit_aum=100,
                         overage_tier1_cap_aum=50, rate_per_aum_cents=2200,
                         overage_tier1_rate_cents=2600,
                         overage_tier2_rate_cents=3200)
    v0 = lease["version"]

    lease = validate_success(api.activate_lease(lease["id"], RANGE_MGR))
    assert lease["lease_status"] == "ACTIVE"
    assert lease["version"] == v0 + 1
    lease = validate_success(api.suspend_lease(lease["id"], RANGE_MGR))
    assert lease["lease_status"] == "SUSPENDED"
    assert lease["version"] == v0 + 2
    lease = validate_success(api.reinstate_lease(lease["id"], RANGE_MGR))
    assert lease["lease_status"] == "ACTIVE"
    assert lease["version"] == v0 + 3
    lease = validate_success(api.suspend_lease(lease["id"], RANGE_MGR))
    assert lease["lease_status"] == "SUSPENDED"
    assert lease["version"] == v0 + 4
    lease = validate_success(api.reinstate_lease(lease["id"], RANGE_MGR))
    assert lease["lease_status"] == "ACTIVE"
    assert lease["version"] == v0 + 5
    lease = validate_success(api.suspend_lease(lease["id"], RANGE_MGR))
    assert lease["lease_status"] == "SUSPENDED"
    assert lease["version"] == v0 + 6
    lease = validate_success(api.terminate_lease(lease["id"], RANCH_MGR))
    assert lease["lease_status"] == "TERMINATED"
    assert lease["version"] == v0 + 7
    return lease["id"], v0, lease


class TestLeaseSuspendReinstateCycle:
    def test_suspend_reinstate_cycle_unrestricted_with_version_hops(self, api):
        """PRD §3.2: "An `ACTIVE` lease may be suspended, moving to `SUSPENDED`
        with no further preconditions, and a suspended lease may be reinstated
        to `ACTIVE`, which re-runs the same aggregate-capacity check against
        whatever commitments exist at that moment; the suspend–reinstate cycle
        is unrestricted in count. Every activation, suspension, reinstatement,
        and termination increments the lease's `version`."

        Design: Difficulty/non_linear_state_machine/lease_suspend_reinstate_cycle
        """
        _lease_id, v0, final_lease = _cycle_lease(api)
        # Two full cycles traversed DRAFT -> ACTIVE -> SUSPENDED twice over,
        # then TERMINATED; every hop moved the version by exactly one.
        assert final_lease["version"] == v0 + 7

    def test_terminated_lease_rejects_reinstate(self, api):
        """PRD §3.2: "Termination is the hard stop and belongs to the
        `RanchManager` alone: a lease in `DRAFT`, `ACTIVE`, or `SUSPENDED` moves
        to `TERMINATED`"
        PRD §2.8: "Terminal-state rejection: a resource that has reached a
        terminal state refuses all further transitions (`ERR_ALREADY_TERMINAL`)."

        Design: Difficulty/non_linear_state_machine/lease_suspend_reinstate_cycle
        """
        lease_id, _v0, final_lease = _cycle_lease(api)
        resp = api.reinstate_lease(lease_id, RANGE_MGR)
        validate_error(resp, ApiErrorId.ERR_ALREADY_TERMINAL)
        after = get_success_data(api.get_lease(lease_id, RANGE_MGR))
        assert after["lease_status"] == "TERMINATED"
        assert after["version"] == final_lease["version"], (
            "a rejected transition must not bump the version"
        )


class TestLeaseAggregateCapacity:
    def _setup_three_leases(self, api):
        ranch = create_ranch(name="Split Ranch", hq_state="ID")
        pasture = create_pasture(ranch["id"], name="Split Section", acreage=640,
                                 tenure="LEASED", base_capacity_aum=100)
        mk = lambda name, allot: create_lease(
            ranch["id"], pasture["id"], lessor_name=name, aum_allotment=allot,
            minimum_commit_aum=0, overage_tier1_cap_aum=10,
            rate_per_aum_cents=2400, overage_tier1_rate_cents=2800,
            overage_tier2_rate_cents=3500)
        return mk("L1", 60), mk("L2", 40), mk("L3", 1)

    def test_overlapping_leases_admitted_within_aggregate_capacity(self, api):
        """PRD §3.2: "the sum of `aum_allotment` over all `ACTIVE` leases on
        that pasture, the candidate included, must not exceed the pasture's
        `base_capacity_aum`, or the activation fails with
        `ERR_LEASE_CAPACITY_EXCEEDED` (HTTP 422). Lease windows may overlap on
        the same pasture — the discipline is aggregate capacity, not calendar
        exclusivity."

        Design: Difficulty/resource_temporal_overlap/lease_allotment_aggregate_capacity
        """
        l1, l2, _l3 = self._setup_three_leases(api)
        l1 = validate_success(api.activate_lease(l1["id"], RANGE_MGR))
        l2 = validate_success(api.activate_lease(l2["id"], RANGE_MGR))
        # Fully overlapping windows, admitted because 60 + 40 == 100 <= 100.
        assert l1["lease_status"] == "ACTIVE"
        assert l2["lease_status"] == "ACTIVE"

    def test_aggregate_capacity_overflow_rejected(self, api):
        """PRD §3.2: "the sum of `aum_allotment` over all `ACTIVE` leases on
        that pasture, the candidate included, must not exceed the pasture's
        `base_capacity_aum`, or the activation fails with
        `ERR_LEASE_CAPACITY_EXCEEDED` (HTTP 422)."

        Design: Difficulty/resource_temporal_overlap/lease_allotment_aggregate_capacity
        """
        l1, l2, l3 = self._setup_three_leases(api)
        activate = api.activate_lease
        validate_success(activate(l1["id"], RANGE_MGR))
        validate_success(activate(l2["id"], RANGE_MGR))
        # 60 + 40 + 1 = 101 > 100 — the third lease cannot join.
        resp = api.activate_lease(l3["id"], RANGE_MGR)
        validate_error(resp, ApiErrorId.ERR_LEASE_CAPACITY_EXCEEDED,
                       expected_status=422)
        after = get_success_data(api.get_lease(l3["id"], RANGE_MGR))
        assert after["lease_status"] == "DRAFT"


class TestLeaseStateGates:
    def test_suspend_draft_lease_rejected(self, api):
        """PRD §2.8: "Generic transition validity: the requested transition
        exists from the resource's current, non-terminal state
        (`ERR_INVALID_STATE_TRANSITION`)."
        PRD §3.2: "An `ACTIVE` lease may be suspended, moving to `SUSPENDED`
        with no further preconditions"

        Design: Corner/state_machines/lease_invalid_transition_from_draft
        """
        ranch = create_ranch(name="R")
        pasture = create_pasture(ranch["id"], name="P", acreage=400,
                                 tenure="LEASED", base_capacity_aum=100)
        lease = create_lease(ranch["id"], pasture["id"], aum_allotment=50,
                             minimum_commit_aum=10, overage_tier1_cap_aum=10)
        resp = api.suspend_lease(lease["id"], RANGE_MGR)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE_TRANSITION)
        after = get_success_data(api.get_lease(lease["id"], RANGE_MGR))
        assert after["lease_status"] == "DRAFT"

    def test_lease_auto_expires_past_end_date(self, api):
        """PRD §3.2: "Expiry is lazy: when the current date passes a lease's
        `end_date`, an `ACTIVE` lease reads as `EXPIRED` on the next read or
        mutation, with no operator action required."

        Design: Corner/state_machines/lease_auto_expires_past_end_date
        """
        ranch = create_ranch(name="R")
        pasture = create_pasture(ranch["id"], name="P", acreage=400,
                                 tenure="LEASED", base_capacity_aum=100)
        # The window must straddle the startup clock (2026-08-01, PRD §2.4) so
        # the lease is genuinely ACTIVE at activation; lazy expiry is then
        # observed by advancing the clock past end_date.
        lease = create_and_activate_lease(
            ranch["id"], pasture["id"], aum_allotment=50, minimum_commit_aum=10,
            overage_tier1_cap_aum=10, start_date="2026-08-01",
            end_date="2026-12-31")
        assert lease["lease_status"] == "ACTIVE"
        set_clock("2027-01-01T00:00:00Z")
        after = get_success_data(api.get_lease(lease["id"], RANGE_MGR))
        assert after["lease_status"] == "EXPIRED", (
            "2027-01-01 is past the 2026-12-31 end_date"
        )

    def test_lease_create_missing_required_field_rejected(self, api):
        """PRD §3.2: "A `RangeManager` drafts a grazing lease against a pasture
        whose tenure is `LEASED` — a lease may never be written against deeded
        ground — supplying the `ranch_id`, the `pasture_id`, the landowner's
        `lessor_name`, an inclusive lease window from `start_date` through
        `end_date`, the contracted `aum_allotment`, the `rate_per_aum_cents`,
        the take-or-pay floor `minimum_commit_aum`, the two overage tiers
        `overage_tier1_cap_aum` with `overage_tier1_rate_cents` and
        `overage_tier2_rate_cents`, and the `settlement_basis` of `ALLOTMENT` or
        `ACTUAL_USE`."
        PRD §2.8: "Request-body well-formedness: required fields are present,
        enum members are valid, no computed, system-managed, or unknown fields
        are supplied, quantities are positive, and any window's start precedes
        its end (`ERR_INVALID_REQUEST`)."

        Design: Corner/validations/lease_create_missing_required_field_rejected
        """
        ranch = create_ranch(name="R")
        pasture = create_pasture(ranch["id"], name="P", acreage=400,
                                 tenure="LEASED", base_capacity_aum=100)
        payload = create_lease_payload(ranch["id"], pasture["id"],
                                       aum_allotment=50, minimum_commit_aum=10,
                                       overage_tier1_cap_aum=10)
        del payload["rate_per_aum_cents"]
        resp = api.create_lease(payload, RANGE_MGR)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)
