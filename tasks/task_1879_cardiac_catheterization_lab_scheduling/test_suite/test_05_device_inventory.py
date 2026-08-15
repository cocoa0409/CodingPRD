"""Device lots: dual availability views, reservation boundaries, implant,
release, expiry, restock, and derived lot status."""
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    add_radiation_record,
    assert_device_lot_invariants,
    create_device_lot,
    get_lot,
    reserve_device_usage,
    set_clock,
    setup_case_workspace,
    setup_in_progress_workspace,
    validate_error,
    validate_paginated,
    validate_success,
)

SCHEDULER = TEST_USERS["scheduler_headers"]
TECHNOLOGIST = TEST_USERS["technologist_headers"]


class TestDualAvailabilityViews:
    def _setup_reserved_lot(self, api):
        workspace = setup_case_workspace()
        lot = create_device_lot(ownership="CONSIGNMENT", quantity_on_hand=5,
                                reorder_threshold=2)
        usage = reserve_device_usage(workspace["case"]["id"], lot["id"], 2)
        return workspace, lot, usage

    def test_device_lot_physical_view_ignores_reservation(self, api):
        """PRD §3.5: "Note also that a lot carries two readings: the scheduling
        view, `available_units`, subtracts reservations and drives both reservation
        validation and status derivation, while the physical view,
        `quantity_on_hand`, does not subtract them and is what consignment and
        shelf reconciliation read. The two diverge whenever any usage of the lot is
        `RESERVED`."
        PRD §3.5: "`allocated_units` is the sum of `quantity` over that lot's
        device usages in `RESERVED` status — `IMPLANTED` and `RELEASED` usages do
        not count — and `available_units` is `quantity_on_hand` minus
        `allocated_units`."

        Design: Difficulty/dual_variant_calc/device_availability_scheduling_vs_physical_view
        """
        _, lot, _ = self._setup_reserved_lot(api)
        current = get_lot(lot["id"])
        assert current["quantity_on_hand"] == 5, \
            "physical view: reservation does not consume shelf stock"
        assert current["allocated_units"] == 2

    def test_device_lot_scheduling_view_subtracts_reservation(self, api):
        """PRD §3.5: "`allocated_units` is the sum of `quantity` over that lot's
        device usages in `RESERVED` status — `IMPLANTED` and `RELEASED` usages do
        not count — and `available_units` is `quantity_on_hand` minus
        `allocated_units`."
        PRD §3.5: "The lot's `status` is fully derived from those figures after
        every mutation that touches either counter — creation, reservation,
        release, implantation, restock: `DEPLETED` when nothing is available;
        otherwise `LOW_STOCK` when the available figure is below the
        `reorder_threshold`; otherwise `ACTIVE`."

        Design: Difficulty/dual_variant_calc/device_availability_scheduling_vs_physical_view
        """
        _, lot, _ = self._setup_reserved_lot(api)
        current = get_lot(lot["id"])
        assert current["available_units"] == 3, "scheduling view: 5 - 2"
        assert current["status"] == "ACTIVE", "available 3 >= threshold 2"
        assert_device_lot_invariants(current)


class TestReservationBoundary:
    def _setup_lot_and_case(self, api):
        workspace = setup_case_workspace()
        lot = create_device_lot(quantity_on_hand=5, reorder_threshold=2)
        return workspace, lot

    def test_reserve_exactly_available_units_succeeds(self, api):
        """PRD §3.5: "And the lot's `available_units` must cover the request — a
        request equal to the available figure is allowed, while anything larger is
        refused with `ERR_INSUFFICIENT_DEVICE_STOCK`."
        PRD §3.5: "The lot's `status` is fully derived from those figures after
        every mutation that touches either counter — creation, reservation,
        release, implantation, restock: `DEPLETED` when nothing is available;
        otherwise `LOW_STOCK` when the available figure is below the
        `reorder_threshold`; otherwise `ACTIVE`."

        Design: Difficulty/boundary_precision_check/device_reserve_exactly_available_succeeds_one_more_fails
        """
        workspace, lot = self._setup_lot_and_case(api)
        usage = reserve_device_usage(workspace["case"]["id"], lot["id"], 5)
        assert usage["status"] == "RESERVED", "5 == available 5: allowed"
        current = get_lot(lot["id"])
        assert current["available_units"] == 0
        assert current["status"] == "DEPLETED"

    def test_reserve_one_above_available_rejected(self, api):
        """PRD §3.5: "And the lot's `available_units` must cover the request — a
        request equal to the available figure is allowed, while anything larger is
        refused with `ERR_INSUFFICIENT_DEVICE_STOCK`."

        Design: Difficulty/boundary_precision_check/device_reserve_exactly_available_succeeds_one_more_fails
        """
        workspace, lot = self._setup_lot_and_case(api)
        reserve_device_usage(workspace["case"]["id"], lot["id"], 5)
        resp = api.create_device_usage(workspace["case"]["id"],
                                       {"lot_id": lot["id"], "quantity": 1},
                                       TECHNOLOGIST)
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_DEVICE_STOCK,
                       expected_status=409)
        current = get_lot(lot["id"])
        assert current["available_units"] == 0
        assert current["allocated_units"] == 5, "the rejected reserve changed nothing"


class TestReserveReleaseConservation:
    def _setup(self, api):
        workspace = setup_case_workspace(procedure_type="DEVICE_IMPLANT")
        lot = create_device_lot(device_type="ICD_LEAD", model_number="IL-9",
                                lot_number="LOT-I", ownership="CONSIGNMENT",
                                quantity_on_hand=5, reorder_threshold=2)
        return workspace, lot

    def test_reserve_conserves_unit_accountability(self, api):
        """PRD §3.5: "A successful reservation creates the usage in `RESERVED`,
        recorded against its case as `case_id`, raises the lot's `allocated_units`
        by the reserved `quantity`, and recomputes the derived status."

        Design: Difficulty/compensating_invariant/device_reserve_release_pair_conserves_unit_accountability
        """
        workspace, lot = self._setup(api)
        usage = reserve_device_usage(workspace["case"]["id"], lot["id"], 3)
        assert usage["status"] == "RESERVED"
        current = get_lot(lot["id"])
        assert current["quantity_on_hand"] == 5
        assert current["allocated_units"] == 3
        # Unit accountability conserved: 5 on hand + 3 reserved == 5 + 3.
        assert_device_lot_invariants(current)

    def test_release_restores_unit_accountability_without_drift(self, api):
        """PRD §3.5: "Releasing a reservation — manually by the technologist, or
        automatically when the case is bumped, cancelled, or completed — returns
        the units to the available pool: the usage moves `RESERVED` → `RELEASED`,
        `allocated_units` falls by the released `quantity`, `quantity_on_hand` is
        untouched, and the status recomputes."

        Design: Difficulty/compensating_invariant/device_reserve_release_pair_conserves_unit_accountability
        """
        workspace, lot = self._setup(api)
        usage = reserve_device_usage(workspace["case"]["id"], lot["id"], 3)
        released = validate_success(
            api.release_device_usage(usage["id"], TECHNOLOGIST))
        assert released["status"] == "RELEASED"
        current = get_lot(lot["id"])
        assert current["quantity_on_hand"] == 5, "release never touches the shelf"
        assert current["allocated_units"] == 0, "zero drift after the pair"
        assert current["status"] == "ACTIVE", "available 5 >= threshold 2"
        assert_device_lot_invariants(current)


class TestExpiryAndPriority:
    def _setup_expired_scenario(self, api):
        set_clock("2026-08-01T00:00:00Z")
        workspace = setup_case_workspace()
        lot = create_device_lot(device_type="STENT_BMS", model_number="BS-1",
                                lot_number="LOT-X", quantity_on_hand=1,
                                reorder_threshold=0,
                                expiration_date="2026-08-01T00:00:00Z")
        reserve_device_usage(workspace["case"]["id"], lot["id"], 1)
        set_clock("2026-08-02T00:00:00Z")  # strictly past the expiration date
        return workspace, lot

    def test_expired_lot_reserve_temporal_error_beats_quota(self, api):
        """PRD §2.10: "Rejection checks run in a fixed priority order, so a request
        that would fail several checks always reports the earliest applicable one."
        PRD §2.10: "Seventh, temporal conflicts and deadlines
        (`ERR_ROOM_WINDOW_CONFLICT`, `ERR_STAFF_WINDOW_CONFLICT`,
        `ERR_DEVICE_EXPIRED`, `ERR_SUBMISSION_WINDOW_EXPIRED`)."
        PRD §2.10: "Ninth, capacity and selector fallbacks
        (`ERR_INSUFFICIENT_DEVICE_STOCK`, `ERR_NO_RECOVERY_BED`,
        `ERR_NO_STEMI_ROOM`)."

        Design: Difficulty/priority_pair_validation_conflict/reserve_expired_lot_with_insufficient_stock_temporal_beats_quota
        """
        workspace, lot = self._setup_expired_scenario(api)
        # Both failures hold: the lot is expired (temporal) and available 0 < 1
        # (quota). The temporal check is earlier in the fixed order.
        resp = api.create_device_usage(workspace["case"]["id"],
                                       {"lot_id": lot["id"], "quantity": 1},
                                       TECHNOLOGIST)
        validate_error(resp, ApiErrorId.ERR_DEVICE_EXPIRED, expected_status=422)

    def test_expired_lot_reserve_persists_nothing(self, api):
        """PRD §3.5: "When the current logical date falls strictly after the lot's
        `expiration_date`, the reservation fails with `ERR_DEVICE_EXPIRED`; on the
        expiration date itself the lot remains reservable."

        Design: Difficulty/priority_pair_validation_conflict/reserve_expired_lot_with_insufficient_stock_temporal_beats_quota
        """
        workspace, lot = self._setup_expired_scenario(api)
        resp = api.create_device_usage(workspace["case"]["id"],
                                       {"lot_id": lot["id"], "quantity": 1},
                                       TECHNOLOGIST)
        validate_error(resp, ApiErrorId.ERR_DEVICE_EXPIRED, expected_status=422)
        current = get_lot(lot["id"])
        assert current["allocated_units"] == 1, "no second reservation persisted"
        assert current["available_units"] == 0
        usages, meta = validate_paginated(
            api.list_lot_usages(lot["id"], TECHNOLOGIST))
        assert meta["total_count"] == 1

    def test_device_expiry_on_expiration_date_itself_allowed(self, api):
        """PRD §3.5: "When the current logical date falls strictly after the lot's
        `expiration_date`, the reservation fails with `ERR_DEVICE_EXPIRED`; on the
        expiration date itself the lot remains reservable."

        Design: Corner/calculations/device_expiry_on_expiration_date_itself_allowed
        """
        set_clock("2026-08-10T08:00:00Z")
        workspace = setup_case_workspace(
            scheduled_start="2026-08-10T14:00:00Z")
        lot = create_device_lot(lot_number="LOT-E", quantity_on_hand=2,
                                reorder_threshold=1,
                                expiration_date="2026-08-10T00:00:00Z")
        set_clock("2026-08-10T13:00:00Z")  # same calendar date as the expiry
        usage = reserve_device_usage(workspace["case"]["id"], lot["id"], 1)
        assert usage["status"] == "RESERVED", "expiry compares dates strictly-after"
        assert get_lot(lot["id"])["allocated_units"] == 1


class TestDerivedLotStatus:
    def test_device_lot_status_low_stock_boundary_at_threshold(self, api):
        """PRD §3.5: "The lot's `status` is fully derived from those figures after
        every mutation that touches either counter — creation, reservation,
        release, implantation, restock: `DEPLETED` when nothing is available;
        otherwise `LOW_STOCK` when the available figure is below the
        `reorder_threshold`; otherwise `ACTIVE`. The boundary belongs to `ACTIVE` —
        availability exactly equal to the reorder threshold is healthy."

        Design: Corner/state_machines/device_lot_status_low_stock_boundary_at_threshold
        """
        lot = create_device_lot(device_type="CLOSURE_DEVICE", model_number="CD-2",
                                lot_number="LOT-C", quantity_on_hand=3,
                                reorder_threshold=3)
        assert lot["status"] == "ACTIVE", \
            "creation boundary: available 3 == threshold 3 is ACTIVE"
        workspace = setup_case_workspace()
        reserve_device_usage(workspace["case"]["id"], lot["id"], 1)
        current = get_lot(lot["id"])
        assert current["available_units"] == 2
        assert current["status"] == "LOW_STOCK", "2 < 3 flips the lot LOW_STOCK"
        assert_device_lot_invariants(current)


class TestUsageStateGates:
    def test_implant_requires_in_progress_case(self, api):
        """PRD §3.5: "Marking reserved units as implanted is restricted to a case
        `IN_PROGRESS` (anything else is `ERR_CASE_INVALID_STATE`) and to a usage
        still `RESERVED` (else `ERR_USAGE_INVALID_STATE`)."

        Design: Corner/state_machines/implant_requires_in_progress_case
        """
        workspace = setup_case_workspace()
        lot = create_device_lot(quantity_on_hand=3, reorder_threshold=1)
        usage = reserve_device_usage(workspace["case"]["id"], lot["id"], 1)
        resp = api.implant_device_usage(usage["id"], TECHNOLOGIST)
        validate_error(resp, ApiErrorId.ERR_CASE_INVALID_STATE, expected_status=409)
        usages, _ = validate_paginated(
            api.list_lot_usages(lot["id"], TECHNOLOGIST))
        assert usages[0]["status"] == "RESERVED"
        assert get_lot(lot["id"])["quantity_on_hand"] == 3

    def test_double_release_usage_returns_invalid_state(self, api):
        """PRD §3.5: "Releasing a usage that is not `RESERVED` is likewise
        `ERR_USAGE_INVALID_STATE`."

        Design: Corner/errors/double_release_usage_returns_invalid_state
        """
        workspace = setup_case_workspace()
        lot = create_device_lot(lot_number="LOT-G", quantity_on_hand=2,
                                reorder_threshold=1)
        usage = reserve_device_usage(workspace["case"]["id"], lot["id"], 1)
        validate_success(api.release_device_usage(usage["id"], TECHNOLOGIST))
        resp = api.release_device_usage(usage["id"], TECHNOLOGIST)
        validate_error(resp, ApiErrorId.ERR_USAGE_INVALID_STATE, expected_status=409)
        usages, _ = validate_paginated(
            api.list_lot_usages(lot["id"], TECHNOLOGIST))
        assert usages[0]["status"] == "RELEASED"
        assert get_lot(lot["id"])["allocated_units"] == 0


class TestInputSetFiltering:
    def test_input_set_filtering_excludes_terminal_usage_and_voided_doses(self, api):
        """PRD §3.5: "`allocated_units` is the sum of `quantity` over that lot's
        device usages in `RESERVED` status — `IMPLANTED` and `RELEASED` usages do
        not count"
        PRD §3.6: "The case's `cumulative_radiation_mgy` is the sum of those
        per-record rounded totals over its non-voided radiation entries."
        PRD §3.6: "The entry moves `ACTIVE` → `VOIDED`, and both cumulative totals
        are recomputed over the remaining `ACTIVE` entries."

        Design: Corner/calculations/input_set_filtering_excludes_terminal_usage_and_voided_doses
        """
        workspace = setup_in_progress_workspace()
        case = workspace["case"]
        assert case["status"] == "IN_PROGRESS"
        lot = create_device_lot(lot_number="LOT-F", quantity_on_hand=6,
                                reorder_threshold=1)
        u1 = reserve_device_usage(case["id"], lot["id"], 2)
        reserve_device_usage(case["id"], lot["id"], 1)  # stays RESERVED
        implanted = validate_success(
            api.implant_device_usage(u1["id"], TECHNOLOGIST))
        assert implanted["status"] == "IMPLANTED"
        record = add_radiation_record(case["id"], 40, 0)
        validate_success(api.void_dose_record(record["id"], TECHNOLOGIST))

        current = get_lot(lot["id"])
        assert current["quantity_on_hand"] == 4, "implant consumed 2 of 6"
        assert current["allocated_units"] == 1, "only the RESERVED usage counts"
        assert current["available_units"] == 3
        assert_device_lot_invariants(current)
        updated_case = validate_success(api.get_case(case["id"], SCHEDULER))
        assert updated_case["cumulative_radiation_mgy"] == pytest.approx(0.0), \
            "the VOIDED record leaves the input set"
