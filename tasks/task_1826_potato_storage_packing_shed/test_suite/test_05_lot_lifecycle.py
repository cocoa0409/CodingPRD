"""Lot lifecycle: intake defaults, bin assignment gates, assessments and shrink
re-baseline, sprout-inhibitor retreat window, quality holds, condemnation, and
manual close (PRD §3.1, §3.2, §3.8)."""
import pytest

from test_helpers import (
    validate_success, validate_error, validate_paginated, get_success_data, ApiErrorId,
    setup_grower_shed_bin_lot, create_grower, create_shed, create_bin, create_lot,
    create_binned_lot, bin_lot, assess_lot, apply_inhibitor, hold_lot, condemn_lot,
    create_contract, create_order, allocate_order, refresh_lot, refresh_order,
    refresh_contract, make_grower_headers, NON_EXISTENT_UUID,
    TEST_USERS,
)

ADMIN = TEST_USERS["admin_headers"]
INTAKE = TEST_USERS["intake_headers"]
STORAGE = TEST_USERS["storage_headers"]
QA = TEST_USERS["qa_headers"]
SALES = TEST_USERS["sales_headers"]


class TestLotIntakeDefaults:
    def test_new_lot_starts_intake_clear_with_zero_ledgers(self, api):
        """PRD §3.1: "The new lot starts in `storage_status` `INTAKE` with `quality_status` `CLEAR`; it has no `bin_id` yet, and its shrink, packed, cull, condemned, and processing-credit accumulators all start at zero. Its `available_cwt` — the weight-conservation anchor — initially equals the original weight."

        Design: Corner/entities/c_lot_create_defaults_and_initial_state
        """
        grower = create_grower("Grower B", "G-B")
        resp = api.create_field_lot(
            grower["id"],
            {"variety": "RUSSET_BURBANK", "harvest_date": "2026-07-28",
             "original_weight_cwt": 250.50},
            INTAKE,
        )
        lot = validate_success(resp, expected_status=201)
        assert lot["storage_status"] == "INTAKE"
        assert lot["quality_status"] == "CLEAR"
        assert lot["bin_id"] is None
        assert abs(lot["available_cwt"] - 250.50) <= 0.005
        assert abs(lot["reserved_cwt"] - 0.00) <= 0.005
        assert lot["version"] == 1
        assert abs(lot["shrink_cwt"] - 0.00) <= 0.005
        assert abs(lot["packed_total_cwt"] - 0.00) <= 0.005
        assert abs(lot["cull_total_cwt"] - 0.00) <= 0.005
        assert abs(lot["condemned_cwt"] - 0.00) <= 0.005
        assert abs(lot["processing_credit_cwt"] - 0.00) <= 0.005
        assert lot["inhibitor_application_count"] == 0

    def test_create_missing_variety_returns_400(self, api):
        """PRD §3.1: "an `IntakeClerk` can receive a `FieldLot` against that grower by providing the `variety` (one of `RUSSET_BURBANK`, `RUSSET_NORKOTAH`, `RANGER_RUSSET`, `YUKON_GOLD`, or `RED_LASODA`), the `harvest_date` as an ISO 8601 date, and the `original_weight_cwt` scaled at the truck."
        PRD §2.9 tier 9 lists "general required-field and enum membership checks" among shape failures surfacing as "`ERR_INVALID_REQUEST`".

        Design: Corner/entities/c_lot_create_missing_variety_returns_400
        """
        grower = create_grower("Grower C", "G-C")
        resp = api.create_field_lot(
            grower["id"],
            {"harvest_date": "2026-07-28", "original_weight_cwt": 100.00},
            INTAKE,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)
        lots, meta = validate_paginated(
            api.list_field_lots(STORAGE, params={"grower_id": grower["id"]})
        )
        assert lots == []
        assert meta["total_count"] == 0

    def test_create_invalid_variety_enum_returns_400(self, api):
        """PRD §3.1: "an `IntakeClerk` can receive a `FieldLot` against that grower by providing the `variety` (one of `RUSSET_BURBANK`, `RUSSET_NORKOTAH`, `RANGER_RUSSET`, `YUKON_GOLD`, or `RED_LASODA`)".
        PRD §5: `ERR_INVALID_REQUEST` covers "invalid enum".

        Design: Corner/entities/c_lot_create_invalid_variety_enum_returns_400
        """
        grower = create_grower("Grower D", "G-D")
        resp = api.create_field_lot(
            grower["id"],
            {"variety": "PURPLE_MAJESTY", "harvest_date": "2026-07-28",
             "original_weight_cwt": 100.00},
            INTAKE,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


class TestBinAssignment:
    def test_assign_twice_returns_lot_invalid_state(self, api):
        """PRD §3.1: "The operation is permitted only while the lot is in `INTAKE`; a lot already `BINNED` or `CLOSED` is rejected with `ERR_LOT_INVALID_STATE`."

        Design: Corner/state_machines/c_lot_assign_twice_returns_lot_invalid_state
        """
        ctx = setup_grower_shed_bin_lot(
            grower_name="Grower I", grower_code="G-I", shed_name="Shed CD",
            lot_weight_cwt=100.00, harvest_date="2026-07-28",
        )
        bin2 = create_bin(ctx["shed"]["id"], bin_code="B-2")

        resp = api.assign_bin(ctx["lot"]["id"], {"bin_id": bin2["id"]}, INTAKE)
        validate_error(resp, ApiErrorId.ERR_LOT_INVALID_STATE)
        lot = refresh_lot(ctx["lot"]["id"])
        assert lot["bin_id"] == ctx["bin"]["id"]  # still the first bin

    def test_variety_lock_mismatch_rejected(self, api):
        """PRD §3.1: "First, the bin's `variety_lock` must either be unset or equal the lot's variety; a mismatch is `ERR_BIN_VARIETY_MISMATCH`."

        Design: Corner/validations/c_bin_variety_mismatch_returns_409
        """
        ctx = setup_grower_shed_bin_lot(
            grower_name="Grower AB", grower_code="G-AB", shed_name="Shed DM",
            lot_weight_cwt=100.00, harvest_date="2026-07-28",
        )
        l2 = create_lot(ctx["grower"]["id"], variety="YUKON_GOLD",
                        harvest_date="2026-07-28", original_weight_cwt=100.00)

        resp = api.assign_bin(l2["id"], {"bin_id": ctx["bin"]["id"]}, INTAKE)
        validate_error(resp, ApiErrorId.ERR_BIN_VARIETY_MISMATCH)
        lot = refresh_lot(l2["id"])
        assert lot["storage_status"] == "INTAKE"
        bins, _ = validate_paginated(api.list_bins(ctx["shed"]["id"], STORAGE))
        assert abs(bins[0]["occupied_cwt"] - 100.00) <= 0.005

    def test_capacity_exact_fit_then_overflow(self, api):
        """PRD §3.1: "Second, the bin's `occupied_cwt` plus the lot's `available_cwt` must not exceed the bin's `capacity_cwt`; an exact fit is allowed, but any excess is rejected with `ERR_BIN_CAPACITY_EXCEEDED`."

        Design: Corner/validations/c_bin_capacity_exact_fit_boundary
        """
        grower = create_grower("Grower AC", "G-AC")
        shed = create_shed("Shed DN")
        bin_ = create_bin(shed["id"])
        l1 = create_binned_lot(grower["id"], bin_["id"], harvest_date="2026-07-28",
                               original_weight_cwt=1500.00)
        l2 = create_lot(grower["id"], harvest_date="2026-07-28", original_weight_cwt=500.00)
        l3 = create_lot(grower["id"], harvest_date="2026-07-28", original_weight_cwt=0.01)

        # exact fit: 1500.00 + 500.00 == 2000.00 capacity is allowed
        lot2 = bin_lot(l2["id"], bin_["id"])
        assert lot2["storage_status"] == "BINNED"

        resp = api.assign_bin(l3["id"], {"bin_id": bin_["id"]}, INTAKE)
        validate_error(resp, ApiErrorId.ERR_BIN_CAPACITY_EXCEEDED)  # 2000.00 + 0.01 > 2000.00
        lot3 = refresh_lot(l3["id"])
        assert lot3["storage_status"] == "INTAKE"


class TestAssessmentShrinkRebaseline:
    def test_second_assessment_replaces_shrink_baseline(self, api):
        """PRD §3.2: "A newly recorded assessment re-baselines the lot: the lot's `shrink_cwt` is set to the assessment's `cumulative_shrink_cwt` (it replaces, never accumulates), and the lot's `available_cwt` is recomputed as the original weight minus shrink, packed, cull, and condemned."

        Design: Corner/calculations/c_assessment_rebaselines_shrink_not_additive
        """
        ctx = setup_grower_shed_bin_lot(
            grower_name="Grower Q", grower_code="G-Q", shed_name="Shed DA",
            lot_weight_cwt=500.00, harvest_date="2026-07-28",
        )
        l = ctx["lot"]
        assess_lot(l["id"], l["version"], cumulative_shrink_cwt=20.00,
                   assessment_date="2026-08-05")

        lot = refresh_lot(l["id"])
        assess_lot(l["id"], lot["version"], us1_pct=68.0, us2_pct=20.0, cull_pct=12.0,
                   cumulative_shrink_cwt=30.00, assessment_date="2026-08-12")

        lot = refresh_lot(l["id"])
        assert abs(lot["shrink_cwt"] - 30.00) <= 0.005  # re-baselined, not 50.00
        assert abs(lot["available_cwt"] - 470.00) <= 0.005

    def test_assessment_driving_available_to_zero_auto_closes(self, api):
        """PRD §3.2: "If the re-baseline drives `available_cwt` to zero the lot auto-closes from `BINNED` to `CLOSED` with `closed_at` stamped."
        PRD §3.1: "When a bin's occupancy falls back to zero — because every lot in it has closed — its `variety_lock` is cleared back to unset so the bin can receive a different variety."

        Design: Corner/state_machines/c_lot_auto_close_on_zero_available_via_assessment
        """
        ctx = setup_grower_shed_bin_lot(
            grower_name="Grower O", grower_code="G-O", shed_name="Shed CJ",
            lot_weight_cwt=100.00, harvest_date="2026-07-28",
        )
        l = ctx["lot"]
        # cumulative_shrink_cwt == original (100.00) is within the <= ceiling and drives available to 0.
        assess_lot(l["id"], l["version"], us1_pct=0.0, us2_pct=0.0, cull_pct=100.0,
                   cumulative_shrink_cwt=100.00, assessment_date="2026-08-01")

        lot = refresh_lot(l["id"])
        assert abs(lot["available_cwt"] - 0.00) <= 0.005
        assert lot["storage_status"] == "CLOSED"
        bins, _ = validate_paginated(api.list_bins(ctx["shed"]["id"], STORAGE))
        assert abs(bins[0]["occupied_cwt"] - 0.00) <= 0.005
        assert bins[0]["variety_lock"] is None


class TestAssessmentValidation:
    def test_percentage_sum_must_equal_100(self, api):
        """PRD §3.2: "the sample percentages `us1_pct`, `us2_pct`, and `cull_pct` (each between 0 and 100 with two decimal places, and the three must sum to exactly 100.00 — any deviation is `ERR_GRADE_PERCENT_SUM_INVALID`)".

        Design: Corner/validations/c_assessment_pct_sum_returns_422
        """
        ctx = setup_grower_shed_bin_lot(
            grower_name="Grower V", grower_code="G-V", shed_name="Shed DF",
            lot_weight_cwt=100.00, harvest_date="2026-07-28",
        )
        l = ctx["lot"]
        resp = api.create_assessment(
            l["id"],
            {"assessment_date": "2026-08-01", "us1_pct": 70.0, "us2_pct": 20.0,
             "cull_pct": 9.99, "cumulative_shrink_cwt": 0.00,
             "expected_field_lot_version": l["version"]},
            STORAGE,
        )
        validate_error(resp, ApiErrorId.ERR_GRADE_PERCENT_SUM_INVALID)
        assessments, _ = validate_paginated(api.list_assessments(l["id"], STORAGE))
        assert assessments == []

    def test_shrink_monotonic_and_capped(self, api):
        """PRD §3.2: "Two rules govern that cumulative shrink number: it must be at least the previous assessment's cumulative value (shrink is monotonic non-decreasing), and it must not exceed the original weight less what has already been packed, culled, or condemned; violating either bound is `ERR_SHRINK_INVALID`."

        Design: Corner/validations/c_assessment_shrink_monotonic_and_capped_returns_422
        """
        ctx = setup_grower_shed_bin_lot(
            grower_name="Grower W", grower_code="G-W", shed_name="Shed DG",
            lot_weight_cwt=500.00, harvest_date="2026-07-28",
        )
        l = ctx["lot"]
        assess_lot(l["id"], l["version"], cumulative_shrink_cwt=30.00,
                   assessment_date="2026-08-01")
        lot = refresh_lot(l["id"])
        v2 = lot["version"]

        # 25.00 < previous cumulative 30.00 — decreasing is rejected.
        resp = api.create_assessment(
            l["id"],
            {"assessment_date": "2026-08-05", "us1_pct": 70.0, "us2_pct": 20.0,
             "cull_pct": 10.0, "cumulative_shrink_cwt": 25.00,
             "expected_field_lot_version": v2},
            STORAGE,
        )
        validate_error(resp, ApiErrorId.ERR_SHRINK_INVALID)

        # 600.00 > the 500.00 ceiling (original less packed/cull/condemned).
        resp = api.create_assessment(
            l["id"],
            {"assessment_date": "2026-08-05", "us1_pct": 70.0, "us2_pct": 20.0,
             "cull_pct": 10.0, "cumulative_shrink_cwt": 600.00,
             "expected_field_lot_version": v2},
            STORAGE,
        )
        validate_error(resp, ApiErrorId.ERR_SHRINK_INVALID)

        lot = refresh_lot(l["id"])
        assert abs(lot["shrink_cwt"] - 30.00) <= 0.005


class TestSproutInhibitorRetreatWindow:
    def test_exactly_21_days_allowed(self, api):
        """PRD §3.2: "A retreat window applies: a new application must fall at least 21 days after the previous one — an application exactly 21 days after the prior `last_inhibitor_applied_at` is allowed, anything earlier is rejected with `ERR_RETREAT_WINDOW_VIOLATION`."

        Design: Difficulty/boundary_precision_check/retreat_window_exactly_21_days
        """
        ctx = setup_grower_shed_bin_lot(
            grower_name="Grower Thirteen", grower_code="G-13", shed_name="Shed M",
            lot_weight_cwt=500.00, set_clock_to="2026-08-02T00:00:00Z",
        )
        lot_a = ctx["lot"]
        apply_inhibitor(lot_a["id"], "2026-08-03T00:00:00Z")

        # Exactly 21 days after 2026-08-03: allowed.
        lot_a = apply_inhibitor(lot_a["id"], "2026-08-24T00:00:00Z")
        assert lot_a["inhibitor_application_count"] == 2

    def test_twenty_days_rejected_and_state_unchanged(self, api):
        """PRD §3.2: "A retreat window applies: a new application must fall at least 21 days after the previous one — an application exactly 21 days after the prior `last_inhibitor_applied_at` is allowed, anything earlier is rejected with `ERR_RETREAT_WINDOW_VIOLATION`."

        Design: Difficulty/boundary_precision_check/retreat_window_exactly_21_days
        """
        ctx = setup_grower_shed_bin_lot(
            grower_name="Grower Thirteen", grower_code="G-13", shed_name="Shed M",
            lot_weight_cwt=500.00, set_clock_to="2026-08-02T00:00:00Z",
        )
        lot_b = ctx["lot"]
        apply_inhibitor(lot_b["id"], "2026-08-03T00:00:00Z")

        # 20 days after the first application: rejected.
        resp = api.apply_sprout_inhibitor(
            lot_b["id"], {"applied_at": "2026-08-23T00:00:00Z"}, STORAGE
        )
        validate_error(resp, ApiErrorId.ERR_RETREAT_WINDOW_VIOLATION)

        lot_b = refresh_lot(lot_b["id"])
        assert lot_b["inhibitor_application_count"] == 1
        assert lot_b["last_inhibitor_applied_at"].startswith("2026-08-03")

    def test_application_inside_window_rejected_boundary_allowed(self, api):
        """PRD §3.2: "A retreat window applies: a new application must fall at least 21 days after the previous one — an application exactly 21 days after the prior `last_inhibitor_applied_at` is allowed, anything earlier is rejected with `ERR_RETREAT_WINDOW_VIOLATION`."

        Design: Difficulty/resource_temporal_overlap/inhibitor_effective_window_overlap
        """
        ctx = setup_grower_shed_bin_lot(
            grower_name="Grower Seventeen", grower_code="G-17", shed_name="Shed Q",
            lot_weight_cwt=500.00, set_clock_to="2026-08-02T00:00:00Z",
        )
        lot = ctx["lot"]
        apply_inhibitor(lot["id"], "2026-08-03T00:00:00Z")  # window covers [08-03, 08-24)

        # 7 days in: strictly inside the window — rejected.
        resp = api.apply_sprout_inhibitor(
            lot["id"], {"applied_at": "2026-08-10T00:00:00Z"}, STORAGE
        )
        validate_error(resp, ApiErrorId.ERR_RETREAT_WINDOW_VIOLATION)

        lot_mid = refresh_lot(lot["id"])
        assert lot_mid["inhibitor_application_count"] == 1  # failed attempt left it at 1

        # Exactly the window end: allowed.
        lot = apply_inhibitor(lot["id"], "2026-08-24T00:00:00Z")
        assert lot["inhibitor_application_count"] == 2

    def test_successful_application_refreshes_last_applied_timestamp(self, api):
        """PRD §3.2: "Each accepted application increments `inhibitor_application_count`, refreshes `last_inhibitor_applied_at` to the supplied `applied_at`, and bumps the lot's `version`."

        Design: Difficulty/resource_temporal_overlap/inhibitor_effective_window_overlap
        """
        ctx = setup_grower_shed_bin_lot(
            grower_name="Grower Seventeen", grower_code="G-17", shed_name="Shed Q",
            lot_weight_cwt=500.00, set_clock_to="2026-08-02T00:00:00Z",
        )
        lot = ctx["lot"]
        lot = apply_inhibitor(lot["id"], "2026-08-03T00:00:00Z")
        assert lot["inhibitor_application_count"] == 1
        assert lot["last_inhibitor_applied_at"].startswith("2026-08-03")

        lot = apply_inhibitor(lot["id"], "2026-08-24T00:00:00Z")
        assert lot["inhibitor_application_count"] == 2
        assert lot["last_inhibitor_applied_at"].startswith("2026-08-24")

    def test_application_on_hold_lot_rejected(self, api):
        """PRD §3.2: "The operation is refused on a lot whose `quality_status` is `ON_HOLD` (`ERR_LOT_QUALITY_HOLD`)."

        Design: Corner/validations/c_sprout_on_hold_lot_returns_lot_quality_hold
        """
        ctx = setup_grower_shed_bin_lot(
            grower_name="Grower AF", grower_code="G-AF", shed_name="Shed DQ",
            lot_weight_cwt=100.00, harvest_date="2026-07-28",
        )
        lot = ctx["lot"]
        apply_inhibitor(lot["id"], "2026-08-03T00:00:00Z")
        hold_lot(lot["id"])

        # 2026-09-01 would pass the retreat window; the hold gate fires instead.
        resp = api.apply_sprout_inhibitor(
            lot["id"], {"applied_at": "2026-09-01T00:00:00Z"}, STORAGE
        )
        validate_error(resp, ApiErrorId.ERR_LOT_QUALITY_HOLD)
        lot = refresh_lot(lot["id"])
        assert lot["inhibitor_application_count"] == 1


class TestQualityTransitions:
    def test_condemn_from_clear_rejected(self, api):
        """PRD §3.8: "Condemnation is reachable only from `ON_HOLD` — a direct transition from `CLEAR` is `ERR_LOT_INVALID_STATE`".

        Design: Corner/state_machines/c_condemn_from_clear_returns_lot_invalid_state
        """
        ctx = setup_grower_shed_bin_lot(
            grower_name="Grower M", grower_code="G-M", shed_name="Shed CH",
            lot_weight_cwt=100.00, harvest_date="2026-07-28",
        )
        resp = api.quality_transition(
            ctx["lot"]["id"], {"to_status": "CONDEMNED", "diversion_channel": "WASTE"}, QA
        )
        validate_error(resp, ApiErrorId.ERR_LOT_INVALID_STATE)
        lot = refresh_lot(ctx["lot"]["id"])
        assert lot["quality_status"] == "CLEAR"
        assert abs(lot["condemned_cwt"] - 0.00) <= 0.005

    def test_condemn_without_channel_rejected(self, api):
        """PRD §3.8: "Condemnation is a transition whose `to_status` is `CONDEMNED` and which carries a `diversion_channel` of `PROCESSING_CREDIT` or `WASTE`. ... a missing or out-of-set diversion channel is `ERR_INVALID_REQUEST`."

        Design: Corner/validations/c_condemn_without_channel_returns_400
        """
        ctx = setup_grower_shed_bin_lot(
            grower_name="Grower X", grower_code="G-X", shed_name="Shed DH",
            lot_weight_cwt=100.00, harvest_date="2026-07-28",
        )
        hold_lot(ctx["lot"]["id"])
        resp = api.quality_transition(ctx["lot"]["id"], {"to_status": "CONDEMNED"}, QA)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)
        lot = refresh_lot(ctx["lot"]["id"])
        assert lot["quality_status"] == "ON_HOLD"
        assert abs(lot["condemned_cwt"] - 0.00) <= 0.005


class TestManualCloseRemnant:
    def test_remnant_exactly_5_allowed(self, api):
        """PRD §3.2: "the manual close is permitted while `available_cwt` is at most 5.0 hundredweight (exactly 5.0 is allowed; anything larger is `ERR_LOT_REMNANT_TOO_LARGE`). Manual close books the remnant into shrink, setting the lot's `shrink_cwt` to the original weight less what has been packed, culled, and condemned, and stamps `closed_at`."

        Design: Corner/validations/c_lot_close_remnant_boundary
        """
        ctx = setup_grower_shed_bin_lot(
            grower_name="Grower AD", grower_code="G-AD", shed_name="Shed DO",
            lot_weight_cwt=105.00, harvest_date="2026-07-28",
        )
        lot_x = ctx["lot"]
        assess_lot(lot_x["id"], lot_x["version"], cumulative_shrink_cwt=100.00,
                   assessment_date="2026-08-01")

        resp = api.close_lot(lot_x["id"], STORAGE)
        lot_x = validate_success(resp, expected_status=200)
        assert lot_x["storage_status"] == "CLOSED"
        # remnant 5.00 booked into shrink at close
        assert abs(lot_x["shrink_cwt"] - 105.00) <= 0.005

    def test_remnant_over_5_rejected(self, api):
        """PRD §3.2: "the manual close is permitted while `available_cwt` is at most 5.0 hundredweight (exactly 5.0 is allowed; anything larger is `ERR_LOT_REMNANT_TOO_LARGE`)."

        Design: Corner/validations/c_lot_close_remnant_boundary
        """
        ctx = setup_grower_shed_bin_lot(
            grower_name="Grower AD", grower_code="G-AD", shed_name="Shed DO",
            lot_weight_cwt=105.01, harvest_date="2026-07-28",
        )
        lot_y = ctx["lot"]
        assess_lot(lot_y["id"], lot_y["version"], cumulative_shrink_cwt=100.00,
                   assessment_date="2026-08-01")

        resp = api.close_lot(lot_y["id"], STORAGE)
        validate_error(resp, ApiErrorId.ERR_LOT_REMNANT_TOO_LARGE)  # 5.01 > 5.0
        lot_y = refresh_lot(lot_y["id"])
        assert lot_y["storage_status"] == "BINNED"


class TestLotHoldCascade:
    @staticmethod
    def _setup_two_lot_order():
        ctx = setup_grower_shed_bin_lot(
            grower_name="Grower Nine", grower_code="G-NINE", shed_name="Shed I",
            lot_weight_cwt=200.00, set_clock_to="2026-08-02T00:00:00Z",
        )
        g, s, b = ctx["grower"], ctx["shed"], ctx["bin"]
        lc = ctx["lot"]
        assess_lot(lc["id"], lc["version"], us1_pct=60.0, us2_pct=20.0, cull_pct=20.0,
                   cumulative_shrink_cwt=0.00)
        ld = create_binned_lot(g["id"], b["id"], harvest_date="2026-07-25",
                               original_weight_cwt=200.00)
        assess_lot(ld["id"], ld["version"], us1_pct=70.0, us2_pct=20.0, cull_pct=10.0,
                   cumulative_shrink_cwt=0.00)
        contract = create_contract(committed_volume_cwt=400.00, price_cents_per_cwt=2000,
                                   grade_min_us1_pct=80.0, buyer_name="Buyer G")
        order = create_order(s["id"], contract_id=contract["id"], requested_packed_cwt=250.00,
                             grade_min_us1_pct=80.0)
        allocate_order(order["id"])
        return {**ctx, "lot_c": lc, "lot_d": ld, "contract": contract, "order": order}

    def test_hold_releases_reservation_and_resets_order(self, api):
        """PRD §3.8: "The transition bumps the lot's `version` and fires the reservation-release cascade: for every order holding a reservation on the lot, that reservation is released and the order's coverage rechecked, with the full de-allocation reset of §3.6 applying if coverage falls short."
        PRD §3.6: "Every remaining reservation is released (each lot's `reserved_cwt` decremented accordingly), the contract ledger is restored as on a cancellation from `ALLOCATED` (decrementing `allocated_active_cwt` and incrementing `remaining_committed_cwt` by the outstanding need), and the order's status moves from `ALLOCATED` or `PACKING` back to `REQUESTED`."

        Design: Difficulty/transitive_cascade/lot_hold_condemn_cascade
        """
        ctx = self._setup_two_lot_order()

        lc = hold_lot(ctx["lot_c"]["id"])
        assert lc["quality_status"] == "ON_HOLD"

        order = refresh_order(ctx["order"]["id"])
        # coverage 90.00 < need 250.00 triggered full reset, releasing lot D's reservation too
        assert order["status"] == "REQUESTED"
        assert order["reservations"] == []

        contract = refresh_contract(ctx["contract"]["id"])
        assert abs(contract["remaining_committed_cwt"] - 400.00) <= 0.005
        assert abs(contract["allocated_active_cwt"] - 0.00) <= 0.005

    def test_condemn_books_weight_and_processing_credit(self, api):
        """PRD §3.8: "The lot's entire `available_cwt` is booked into `condemned_cwt`; when the diversion channel is `PROCESSING_CREDIT`, the same weight is also added to `processing_credit_cwt`. With availability at zero the lot auto-closes to `CLOSED` with `closed_at` stamped".

        Design: Difficulty/transitive_cascade/lot_hold_condemn_cascade
        """
        ctx = self._setup_two_lot_order()
        hold_lot(ctx["lot_c"]["id"])

        lc = condemn_lot(ctx["lot_c"]["id"], "PROCESSING_CREDIT")
        assert abs(lc["condemned_cwt"] - 200.00) <= 0.005
        assert abs(lc["processing_credit_cwt"] - 200.00) <= 0.005
        assert lc["storage_status"] == "CLOSED"  # condemn auto-closes at zero available
