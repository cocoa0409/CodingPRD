"""Leasing and home-sale supersede: first-occupancy gating, supersede blocked by
an open eviction, optimistic concurrency on the lot version, rent riding with the
lot, lease initial state, double-activation, and arrears recompute on payment.
"""
from test_helpers import (
    validate_success,
    validate_error,
    get_success_data,
    ApiErrorId,
    TEST_USERS,
    fixtures as fx,
)

MGR = TEST_USERS["manager_headers"]


class TestFirstOccupancyGating:
    def test_second_first_occupancy_lease_on_occupied_lot_rejected(self, api):
        """PRD §3.2: "The target lot must be `VACANT`; a non-vacant lot is
        rejected with `ERR_LOT_NOT_VACANT` (HTTP 409)."

        Design: Difficulty/cross_entity_state_dependency/lease_activate_depends_on_lot_status
        """
        community, lot, resident_a, lease_a = fx.setup_occupied_lot(
            api, community_overrides={"state_code": "CA"}, lot_overrides={"lot_number": "X1"}
        )
        resident_b = fx.create_resident(community["id"], api, full_name="RB")
        lease_b = fx.create_lease(
            lot["id"], resident_b["id"], api, start_date="2026-02-01"
        )
        resp = api.activate_lease(lease_b["id"], MGR)
        validate_error(resp, ApiErrorId.ERR_LOT_NOT_VACANT.value)

    def test_rejected_second_activation_leaves_lease_pending(self, api):
        """PRD §3.2: "The target lot must be `VACANT`; a non-vacant lot is
        rejected with `ERR_LOT_NOT_VACANT` (HTTP 409)."

        Design: Difficulty/cross_entity_state_dependency/lease_activate_depends_on_lot_status
        """
        community, lot, resident_a, lease_a = fx.setup_occupied_lot(
            api, community_overrides={"state_code": "CA"}, lot_overrides={"lot_number": "X1b"}
        )
        resident_b = fx.create_resident(community["id"], api, full_name="RB")
        lease_b = fx.create_lease(lot["id"], resident_b["id"], api, start_date="2026-02-01")
        api.activate_lease(lease_b["id"], MGR)
        # The rejected activation must not occupy the lot with lease B.
        lease_b_after = get_success_data(api.get_lease(lease_b["id"], MGR))
        assert lease_b_after["status"] == "PENDING"
        lot_after = get_success_data(api.get_lot(lot["id"], MGR))
        assert lot_after["current_lease_id"] == lease_a["id"]

    def test_activate_already_active_lease_rejected(self, api):
        """PRD §3.2: "To activate a first-occupancy lease the lease must be
        `PENDING`; otherwise the request fails with `ERR_INVALID_STATE` (HTTP
        409)."

        Design: Corner/state_machines/activate_already_active_lease_returns_invalid_state
        """
        community, lot, resident, lease = fx.setup_occupied_lot(
            api, community_overrides={"state_code": "CA"}, lot_overrides={"lot_number": "S1"}
        )
        resp = api.activate_lease(lease["id"], MGR)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)

    def test_lease_starts_pending_on_create(self, api):
        """PRD §3.2: "A freshly created lease is `PENDING`."

        Design: Corner/state_machines/lease_initial_state_pending_on_create
        """
        community = fx.create_community(api, state_code="CA")
        lot = fx.create_lot(community["id"], api, lot_number="IN", base_rent_cents=60000)
        resident = fx.create_resident(community["id"], api, full_name="RIn")
        lease = get_success_data(
            api.create_lease(fx.f.create_lease_payload(lot["id"], resident["id"]), MGR)
        )
        assert lease["status"] == "PENDING"


class TestSupersede:
    def test_supersede_blocked_leaves_prior_lease_active(self, api):
        """PRD §3.3: "The supersede is blocked when an eviction case is open on the
        lot's prior lease, in which case the request is rejected with
        `ERR_EVICTION_IN_PROGRESS` (HTTP 409)."

        Design: Difficulty/cross_entity_state_dependency/supersede_blocked_by_open_eviction_on_lease
        """
        fx.set_clock("2026-01-01T00:00:00.000Z", api)
        community, lot, resident_a, lease_a = fx.setup_occupied_lot(
            api, community_overrides={"state_code": "CA"}, lot_overrides={"lot_number": "X2b"}
        )
        get_success_data(
            api.create_eviction_case(
                fx.f.create_eviction_case_payload(lease_a["id"], reason="LEASE_VIOLATION"), MGR
            )
        )
        lot_now = get_success_data(api.get_lot(lot["id"], MGR))
        resident_b = fx.create_resident(community["id"], api, full_name="RB")
        lease_b = fx.create_lease(
            lot["id"], resident_b["id"], api,
            start_date="2026-02-01",
            supersedes_lease_id=lease_a["id"],
            expected_lot_version=lot_now["version"],
        )
        api.activate_lease(lease_b["id"], MGR, payload={"expected_lot_version": lot_now["version"]})
        # The blocked supersede must not transfer the prior lease away.
        lease_a_after = get_success_data(api.get_lease(lease_a["id"], MGR))
        assert lease_a_after["status"] == "ACTIVE"

    def test_supersede_with_stale_lot_version_rejected(self, api):
        """PRD §2.7: "If another writer has advanced the lot's version since the
        client read it — for example, a prior successor lease already activated,
        or a rent schedule went effective and bumped the lot version — the values
        differ and the activation is rejected with `ERR_STALE_LOT_VERSION` (HTTP
        412)."

        Design: Corner/errors/stale_lot_version_on_supersede
        """
        community, lot, resident_a, lease_a = fx.setup_occupied_lot(
            api, community_overrides={"state_code": "CA"}, lot_overrides={"lot_number": "OC"}
        )
        stale_version = lot["version"]
        # An EFFECTIVE increase bumps the lot version beyond the client's snapshot.
        fx.make_effective_schedule(lot["id"], resident_a["id"], 62000, "2027-01-01", api=api)
        resident_b = fx.create_resident(community["id"], api, full_name="ROb")
        lease_b = fx.create_lease(
            lot["id"], resident_b["id"], api,
            start_date="2026-02-01",
            supersedes_lease_id=lease_a["id"],
            expected_lot_version=stale_version,
        )
        resp = api.activate_lease(
            lease_b["id"], MGR, payload={"expected_lot_version": stale_version}
        )
        validate_error(resp, ApiErrorId.ERR_STALE_LOT_VERSION.value)

    def test_supersede_with_current_version_succeeds(self, api):
        """PRD §3.3: "When all conditions hold, the prior lease transitions
        `ACTIVE → TRANSFERRED`, the successor lease transitions `PENDING → ACTIVE`
        with its `rent_cents_at_signing` snapshotted from the lot's
        `current_rent_cents`, the lot's `current_lease_id` is repointed to the
        successor lease, and the lot's `version` increments by one."

        Design: Corner/cross_cutting_complexity_layers/occ_correct_version_supersede_succeeds
        """
        community, lot, resident_a, lease_a, resident_b, lease_b, lot_version = (
            fx.setup_supersede_pending(api=api, raise_rent=False)
        )
        activated = get_success_data(
            api.activate_lease(lease_b["id"], MGR, payload={"expected_lot_version": lot_version})
        )
        assert activated["status"] == "ACTIVE"
        lease_a_after = get_success_data(api.get_lease(lease_a["id"], MGR))
        assert lease_a_after["status"] == "TRANSFERRED"
        lot_after = get_success_data(api.get_lot(lot["id"], MGR))
        assert lot_after["current_lease_id"] == lease_b["id"]

    def test_rent_rides_with_lot_on_supersede(self, api):
        """PRD §3.3: "the successor lease transitions `PENDING → ACTIVE` with its
        `rent_cents_at_signing` snapshotted from the lot's `current_rent_cents`"
        PRD §3.3: "the buyer takes over the lot's lease rather than starting a
        fresh tenancy, and the rent rides with the lot, not with the departing
        home."

        Design: Corner/cross_cutting_complexity_layers/rent_rides_with_lot_on_home_sale_supersede
        """
        # Lot raised 60000 -> 63000 EFFECTIVE before the supersede; the successor
        # lease must sign at the lot's current 63000.
        community, lot, resident_a, lease_a, resident_b, lease_b, lot_version = (
            fx.setup_supersede_pending(api=api, raise_rent=True)
        )
        activated = get_success_data(
            api.activate_lease(lease_b["id"], MGR, payload={"expected_lot_version": lot_version})
        )
        assert activated["rent_cents_at_signing"] == 63000


class TestArrearsRecompute:
    def test_payment_recomputes_arrears(self, api):
        """PRD §3.6: "A resident's `arrears_cents` is the sum of the signed amounts
        of all ledger entries on that resident's active lease, with the result
        floored at zero so it is never negative; entries belonging to prior
        `TRANSFERRED` or `TERMINATED` leases are excluded."

        Design: Corner/cross_cutting_complexity_layers/rate_threshold_arrears_recompute_on_payment
        """
        community, lot, resident, lease = fx.setup_occupied_lot(
            api,
            community_overrides={"state_code": "CA"},
            lot_overrides={"lot_number": "RT", "base_rent_cents": 55000},
        )
        # Opening RENT_CHARGE 55000; pay 10000 -> arrears 45000.
        get_success_data(api.post_payment(lease["id"], 10000, MGR))
        resident_after = get_success_data(api.get_resident(resident["id"], MGR))
        assert resident_after["arrears_cents"] == 45000
