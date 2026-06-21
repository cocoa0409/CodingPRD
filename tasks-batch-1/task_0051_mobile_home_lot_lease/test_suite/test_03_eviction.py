"""Eviction: the branching cure/adjudicate/dismiss machine, the depth-3
adjudication cascade, the cure-window and adjudication-window deadline gates,
arrears thresholds, cure-deadline derivation, and occupied-lot-count conservation.
"""
from test_helpers import (
    validate_success,
    validate_error,
    get_success_data,
    ApiErrorId,
    TEST_USERS,
    make_resident_headers,
    fixtures as fx,
)

MGR = TEST_USERS["manager_headers"]


class TestEvictionBranches:
    def test_dismiss_returns_lot_to_occupied(self, api):
        """PRD §3.7: "Alternatively a `ParkManager` may dismiss a `NOTICE_SERVED`
        case, moving it `NOTICE_SERVED → DISMISSED` and returning the lot
        `EVICTING → OCCUPIED` with its `version` incremented; dismissal requires
        the case to be `NOTICE_SERVED`."

        Design: Difficulty/non_linear_state_machine/eviction_case_branch_cure_vs_adjudicate_vs_dismiss
        """
        community, lot, resident, lease, case = fx.setup_lease_violation_eviction(
            state_code="CA", notice_iso="2026-01-01T00:00:00.000Z", api=api
        )
        dismissed = get_success_data(api.dismiss_eviction(case["id"], MGR))
        assert dismissed["status"] == "DISMISSED"
        lot_after = get_success_data(api.get_lot(lot["id"], MGR))
        assert lot_after["status"] == "OCCUPIED"

    def test_lease_violation_cure_branch_restores_occupancy(self, api):
        """PRD §3.7: "A successful cure moves the case `NOTICE_SERVED → CURED`,
        returns the lot `EVICTING → OCCUPIED`, restores the resident's `standing`
        from `DELINQUENT` to `GOOD`, and increments the lot's `version` by one."

        Design: Difficulty/non_linear_state_machine/eviction_case_branch_cure_vs_adjudicate_vs_dismiss
        """
        # The CURE branch from NOTICE_SERVED (a LEASE_VIOLATION case has no arrears
        # precondition), distinct from the DISMISS branch above.
        community, lot, resident, lease, case = fx.setup_lease_violation_eviction(
            state_code="CA", notice_iso="2026-01-01T00:00:00.000Z", api=api
        )
        fx.set_clock("2026-02-01T00:00:00.000Z", api)  # within the 60-day window
        res_headers = make_resident_headers(resident["id"])
        cured = get_success_data(api.cure_eviction(case["id"], res_headers))
        assert cured["status"] == "CURED"
        lot_after = get_success_data(api.get_lot(lot["id"], MGR))
        assert lot_after["status"] == "OCCUPIED"

    def test_cure_nonpayment_after_payment_restores_occupancy(self, api):
        """PRD §3.7: "A successful cure moves the case `NOTICE_SERVED → CURED`,
        returns the lot `EVICTING → OCCUPIED`, restores the resident's `standing`
        from `DELINQUENT` to `GOOD`, and increments the lot's `version` by one."
        PRD §3.7: "For a `NONPAYMENT` case, curing additionally requires that a
        posted payment has brought arrears below the threshold of 50000 cents; if
        arrears remain at or above the threshold the cure is rejected with
        `ERR_ARREARS_NOT_CLEARED` (HTTP 409)."

        Design: Corner/state_machines/cure_nonpayment_after_payment_restores_occupancy
        """
        community, lot, resident, lease, case = fx.setup_nonpayment_eviction(
            state_code="CA", rent_cents=55000, notice_iso="2026-01-01T00:00:00.000Z", api=api
        )
        # Pay 10000 -> arrears 45000 (below 50000).
        get_success_data(api.post_payment(lease["id"], 10000, MGR))
        fx.set_clock("2026-02-01T00:00:00.000Z", api)
        res_headers = make_resident_headers(resident["id"])
        cured = get_success_data(api.cure_eviction(case["id"], res_headers))
        assert cured["status"] == "CURED"
        lot_after = get_success_data(api.get_lot(lot["id"], MGR))
        assert lot_after["status"] == "OCCUPIED"
        resident_after = get_success_data(api.get_resident(resident["id"], MGR))
        assert resident_after["standing"] == "GOOD"

    def test_cure_after_dismiss_terminal_rejected(self, api):
        """PRD §3.7: "A `Resident` may cure the case. Curing requires the case to
        be `NOTICE_SERVED`, and the current instant must be on or before the
        `cure_deadline`; a cure attempted strictly after the deadline is rejected
        with `ERR_CURE_PERIOD_EXPIRED` (HTTP 409)."

        Design: Corner/state_machines/cure_after_dismiss_terminal_returns_invalid_state
        """
        community, lot, resident, lease, case = fx.setup_lease_violation_eviction(
            state_code="CA", notice_iso="2026-01-01T00:00:00.000Z", api=api
        )
        get_success_data(api.dismiss_eviction(case["id"], MGR))
        res_headers = make_resident_headers(resident["id"])
        resp = api.cure_eviction(case["id"], res_headers)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


class TestAdjudicationCascade:
    def test_adjudicate_cascade_terminates_lease_vacates_lot_evicts_resident(self, api):
        """PRD §3.7: "Upholding moves the case `NOTICE_SERVED → ADJUDICATED` and
        cascades the lot from `EVICTING → VACANT`: the lease transitions `ACTIVE →
        TERMINATED`, the lot's `current_lease_id` is cleared to null, the
        resident's `standing` becomes `EVICTED`, the community's
        `occupied_lot_count` decreases by one, and the lot's `version` increments
        by one."

        Design: Difficulty/transitive_cascade/eviction_adjudicate_depth3_cascade
        """
        community, lot, resident, lease, case = fx.setup_nonpayment_eviction(
            state_code="CA", rent_cents=60000, notice_iso="2026-01-01T00:00:00.000Z", api=api
        )
        fx.set_clock("2026-04-01T00:00:00.000Z", api)  # past the 60-day deadline
        adjudicated = get_success_data(api.adjudicate_eviction(case["id"], MGR))
        assert adjudicated["status"] == "ADJUDICATED"
        lease_after = get_success_data(api.get_lease(lease["id"], MGR))
        assert lease_after["status"] == "TERMINATED"
        lot_after = get_success_data(api.get_lot(lot["id"], MGR))
        assert lot_after["status"] == "VACANT"
        assert lot_after["current_lease_id"] is None
        resident_after = get_success_data(api.get_resident(resident["id"], MGR))
        assert resident_after["standing"] == "EVICTED"
        community_after = get_success_data(api.get_community(community["id"], MGR))
        assert community_after["occupied_lot_count"] == 0

    def test_adjudicate_clears_current_lease_and_evicts_resident(self, api):
        """PRD §3.7: "the lot's `current_lease_id` is cleared to null, the
        resident's `standing` becomes `EVICTED`, the community's
        `occupied_lot_count` decreases by one, and the lot's `version` increments
        by one."

        Design: Difficulty/transitive_cascade/eviction_adjudicate_depth3_cascade
        """
        community, lot, resident, lease, case = fx.setup_nonpayment_eviction(
            state_code="CA", rent_cents=60000, notice_iso="2026-01-01T00:00:00.000Z", api=api
        )
        version_before = get_success_data(api.get_lot(lot["id"], MGR))["version"]
        fx.set_clock("2026-04-01T00:00:00.000Z", api)
        get_success_data(api.adjudicate_eviction(case["id"], MGR))
        lot_after = get_success_data(api.get_lot(lot["id"], MGR))
        assert lot_after["current_lease_id"] is None
        assert lot_after["version"] > version_before
        resident_after = get_success_data(api.get_resident(resident["id"], MGR))
        assert resident_after["standing"] == "EVICTED"

    def test_occupied_lot_count_conserved_across_activate_then_evict(self, api):
        """PRD §2.5: "A community's `occupied_lot_count` is the number of its lots
        in `OCCUPIED` status; it rises by one when a lot becomes occupied and
        falls by one when an occupied lot is vacated by eviction."

        Design: Difficulty/compensating_invariant/occupied_lot_count_conserved_across_evict_then_reactivate
        """
        community, lot, resident, lease, case = fx.setup_nonpayment_eviction(
            state_code="CA", rent_cents=55000, notice_iso="2026-01-01T00:00:00.000Z", api=api
        )
        fx.set_clock("2026-04-01T00:00:00.000Z", api)
        get_success_data(api.adjudicate_eviction(case["id"], MGR))
        community_after = get_success_data(api.get_community(community["id"], MGR))
        assert community_after["occupied_lot_count"] == 0

class TestDeadlineWindows:
    def test_adjudicate_before_deadline_rejected(self, api):
        """PRD §3.7: "Adjudication requires the case to be `NOTICE_SERVED`, and the
        current instant must be strictly after the `cure_deadline`; an
        adjudication attempted on or before the deadline is rejected with
        `ERR_CURE_PERIOD_ACTIVE` (HTTP 409)."

        Design: Difficulty/resource_temporal_overlap/eviction_cure_window_adjudicate_before_deadline
        """
        community, lot, resident, lease, case = fx.setup_nonpayment_eviction(
            state_code="CA", rent_cents=55000, notice_iso="2026-01-01T00:00:00.000Z", api=api
        )
        fx.set_clock("2026-02-01T00:00:00.000Z", api)  # still inside the 60-day window
        resp = api.adjudicate_eviction(case["id"], MGR)
        validate_error(resp, ApiErrorId.ERR_CURE_PERIOD_ACTIVE.value)

    def test_adjudicate_right_after_notice_rejected(self, api):
        """PRD §3.7: "Adjudication requires the case to be `NOTICE_SERVED`, and the
        current instant must be strictly after the `cure_deadline`; an
        adjudication attempted on or before the deadline is rejected with
        `ERR_CURE_PERIOD_ACTIVE` (HTTP 409)."

        Design: Difficulty/resource_temporal_overlap/eviction_cure_window_adjudicate_before_deadline
        """
        community, lot, resident, lease, case = fx.setup_nonpayment_eviction(
            state_code="CA", rent_cents=55000, notice_iso="2026-01-01T00:00:00.000Z", api=api
        )
        # The day after the notice is still well inside the 60-day cure window.
        fx.set_clock("2026-01-02T00:00:00.000Z", api)
        resp = api.adjudicate_eviction(case["id"], MGR)
        validate_error(resp, ApiErrorId.ERR_CURE_PERIOD_ACTIVE.value)

    def test_cure_after_deadline_rejected_temporal_beats_arrears(self, api):
        """PRD §3.7: "Curing requires the case to be `NOTICE_SERVED`, and the
        current instant must be on or before the `cure_deadline`; a cure attempted
        strictly after the deadline is rejected with `ERR_CURE_PERIOD_EXPIRED`
        (HTTP 409)."

        Design: Difficulty/priority_pair_validation_conflict/cure_expired_temporal_beats_arrears_safety
        """
        # Arrears 55000 remain unpaid AND clock is past the deadline; the temporal
        # rule (lower priority number) wins, so ERR_CURE_PERIOD_EXPIRED is returned.
        community, lot, resident, lease, case = fx.setup_nonpayment_eviction(
            state_code="CA", rent_cents=55000, notice_iso="2026-01-01T00:00:00.000Z", api=api
        )
        fx.set_clock("2026-04-01T00:00:00.000Z", api)  # past the 60-day deadline
        res_headers = make_resident_headers(resident["id"])
        resp = api.cure_eviction(case["id"], res_headers)
        validate_error(resp, ApiErrorId.ERR_CURE_PERIOD_EXPIRED.value)

    def test_expired_cure_leaves_case_notice_served(self, api):
        """PRD §3.7: "a cure attempted strictly after the deadline is rejected with
        `ERR_CURE_PERIOD_EXPIRED` (HTTP 409)."

        Design: Difficulty/priority_pair_validation_conflict/cure_expired_temporal_beats_arrears_safety
        """
        # Both the temporal (past-deadline) and safety (arrears unpaid) conditions
        # fail; the rejected cure must leave the case untouched at NOTICE_SERVED.
        community, lot, resident, lease, case = fx.setup_nonpayment_eviction(
            state_code="CA", rent_cents=55000, notice_iso="2026-01-01T00:00:00.000Z", api=api
        )
        fx.set_clock("2026-04-01T00:00:00.000Z", api)
        res_headers = make_resident_headers(resident["id"])
        api.cure_eviction(case["id"], res_headers)
        case_after = get_success_data(api.get_eviction_case(case["id"], MGR))
        assert case_after["status"] == "NOTICE_SERVED"


class TestArrearsAndDeadlineDerivation:
    def test_nonpayment_below_threshold_rejected(self, api):
        """PRD §3.7: "A `NONPAYMENT` notice may be served only when the resident's
        `arrears_cents` is at least 50000 cents — that is, five hundred dollars —
        at notice time; serving a nonpayment notice below that threshold is
        rejected with `ERR_ARREARS_BELOW_THRESHOLD` (HTTP 409)."

        Design: Corner/calculations/nonpayment_eviction_below_threshold_rejected
        """
        fx.set_clock("2026-01-01T00:00:00.000Z", api)
        community, lot, resident, lease = fx.setup_occupied_lot(
            api,
            community_overrides={"state_code": "CA"},
            lot_overrides={"lot_number": "BT", "base_rent_cents": 40000},
        )
        resp = api.create_eviction_case(
            fx.f.create_eviction_case_payload(lease["id"], reason="NONPAYMENT"), MGR
        )
        validate_error(resp, ApiErrorId.ERR_ARREARS_BELOW_THRESHOLD.value)

    def test_tx_cure_deadline_is_notice_plus_14_days(self, api):
        """PRD §3.7: "The `cure_deadline` is computed from the notice date — the
        date portion of the case's `created_at` — plus a state-specific number of
        days, then taken at the end of that day: California allows 60 days, Oregon
        allows 30 days, Florida allows 30 days, and Texas allows 14 days."

        Design: Corner/calculations/cure_deadline_tx_14_days
        """
        fx.set_clock("2026-01-01T00:00:00.000Z", api)
        community, lot, resident, lease = fx.setup_occupied_lot(
            api,
            community_overrides={"state_code": "TX"},
            lot_overrides={"lot_number": "TX1"},
        )
        case = get_success_data(
            api.create_eviction_case(
                fx.f.create_eviction_case_payload(lease["id"], reason="LEASE_VIOLATION"), MGR
            )
        )
        assert case["cure_deadline"][:10] == "2026-01-15"
