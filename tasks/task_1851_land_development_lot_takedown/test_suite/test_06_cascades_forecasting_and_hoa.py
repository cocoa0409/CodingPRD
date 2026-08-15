"""Finalize and default cascades, absorption forecasting, and HOA transfer."""
import pytest

from test_helpers import (
    DEV,
    ApiErrorId,
    assert_lot_inventory_conserved,
    create_acquired_parcel,
    create_active_agreement,
    create_active_loan,
    create_builder,
    create_formed_hoa,
    create_phase,
    create_posted_bond,
    finalize_closing,
    get_closing,
    get_hoa,
    get_loan,
    get_lot,
    get_parcel,
    get_phase,
    list_phase_lots,
    make_hoa_manager_headers,
    reserve_and_open_closing,
    reserve_lot,
    setup_absorption_divergence_scenario,
    setup_finalize_cascade_scenario,
    setup_hoa_threshold_scenario,
    setup_selling_scenario,
    setup_trailing_edge_scenario,
    validate_error,
    validate_success,
    walk_phase_to_recorded,
)


class TestFinalizeCascade:
    def test_finalize_cascade_drains_loan_to_paid_off(self, api):
        """PRD §3.5: "The lot's `sales_status` moves from `UNDER_CONTRACT` to `CLOSED` and its `lien_status` from `RELEASE_PENDING` to `RELEASED` — the lender releases the lot from the loan lien — and `finalized_at` is stamped with the current clock."
        PRD §3.5: "The release payment lands on the loan: `payment_applied_cents` is set to the lesser of the closing's frozen `release_price_cents` and the loan's current `outstanding_balance_cents` — the clamp guarantees the balance can never go negative — then the loan's `outstanding_balance_cents` decreases by that payment, its `total_release_paid_cents` increases by the same amount, and the loan's `version` increments."
        PRD §3.5: "If the balance change leaves `outstanding_balance_cents` at exactly zero while `total_drawn_cents` is greater than zero, the loan auto-transitions from `ACTIVE` to terminal `PAID_OFF`."

        Design: Difficulty/transitive_cascade/closing_finalize_cascade
        """
        scenario = setup_finalize_cascade_scenario()
        for closing in scenario["closings"]:
            finalize_closing(closing["id"])

        lot = get_lot(scenario["lots"][0]["id"])
        assert lot["sales_status"] == "CLOSED"
        assert lot["lien_status"] == "RELEASED"

        loan = get_loan(scenario["loan"]["id"])
        # first finalize applies min(4243600 release price, 1890500 balance);
        # the later finalizes clamp to zero on the drained loan
        assert loan["total_release_paid_cents"] == 1890500
        assert loan["outstanding_balance_cents"] == 0
        assert loan["status"] == "PAID_OFF"

    def test_finalize_cascade_recomputes_parcel_and_transfers_hoa(self, api):
        """PRD §3.5: "The parcel's derived fields recompute — `lots_closed_count`, `lots_available_count`, `closed_pct`, the paces, `projected_months_to_sellout`, and `next_phase_release_eligible` — and the parcel's `version` increments."
        PRD §3.5: "Following the closed ratio sideways: each homeowners association of this parcel sitting in `DECLARANT_CONTROL` whose transfer threshold is now satisfied auto-transitions to `TRANSITIONING`, per the threshold rule of §3.8."

        Design: Difficulty/transitive_cascade/closing_finalize_cascade
        """
        scenario = setup_finalize_cascade_scenario()
        for closing in scenario["closings"]:
            finalize_closing(closing["id"])

        parcel = get_parcel(scenario["parcel"]["id"])
        assert parcel["lots_closed_count"] == 3
        assert parcel["closed_pct"] == 75.0

        # 3*10000 >= 4*7500 at exactly 75% — no explicit evaluate-control call
        hoa = get_hoa(scenario["hoa"]["id"])
        assert hoa["status"] == "TRANSITIONING"


class TestDeclareDefaultCascade:
    def test_declare_default_cancels_pending_closing_and_reverts_lot(self, api):
        """PRD §3.7: "1. Every `PENDING` closing whose lot is reserved under this agreement is cancelled to `CANCELLED`."
        PRD §3.7: "2. Each such cancellation reverts its lot on both dimensions: `lien_status` from `RELEASE_PENDING` back to `ENCUMBERED` and `sales_status` from `UNDER_CONTRACT` back to `RESERVED` — so a lot that was mid-closing hops through `RESERVED` on its way out."
        PRD §3.7: "3. Every lot whose `reserved_agreement_id` names this agreement and whose `sales_status` now reads `RESERVED` — including both lots that were merely reserved and lots that just hopped back from `UNDER_CONTRACT` — is released to `PLATTED` with `reserved_agreement_id` cleared to null."

        Design: Difficulty/transitive_cascade/agreement_default_cascade
        """
        scenario = setup_selling_scenario(num_lots=3)
        builder_id = scenario["builder"]["id"]
        agreement_id = scenario["agreement"]["id"]
        lot_a, lot_b = scenario["lots"][0], scenario["lots"][1]
        closing = reserve_and_open_closing(lot_a["id"], agreement_id, builder_id)
        reserve_lot(lot_b["id"], agreement_id, builder_id)

        validate_success(api.declare_default(
            agreement_id, {"reason": "schedule default"}, DEV))

        # cascade-cancelled, not by a direct cancel call
        assert get_closing(closing["id"])["status"] == "CANCELLED"
        after_a = get_lot(lot_a["id"])
        assert after_a["lien_status"] == "ENCUMBERED"
        assert after_a["sales_status"] == "PLATTED"
        assert after_a["reserved_agreement_id"] is None

    def test_declare_default_releases_lots_and_restores_availability(self, api):
        """PRD §3.7: "3. Every lot whose `reserved_agreement_id` names this agreement and whose `sales_status` now reads `RESERVED` — including both lots that were merely reserved and lots that just hopped back from `UNDER_CONTRACT` — is released to `PLATTED` with `reserved_agreement_id` cleared to null."
        PRD §3.7: "4. The parcel's derived fields recompute (`lots_available_count` rises as lots return, and `closed_pct`, the paces, `projected_months_to_sellout`, and `next_phase_release_eligible` follow), and the parcel's `version` increments, as does the agreement's."

        Design: Difficulty/transitive_cascade/agreement_default_cascade
        """
        scenario = setup_selling_scenario(num_lots=3)
        builder_id = scenario["builder"]["id"]
        agreement_id = scenario["agreement"]["id"]
        lot_a, lot_b = scenario["lots"][0], scenario["lots"][1]
        reserve_and_open_closing(lot_a["id"], agreement_id, builder_id)
        reserve_lot(lot_b["id"], agreement_id, builder_id)

        validate_success(api.declare_default(
            agreement_id, {"reason": "schedule default"}, DEV))

        after_b = get_lot(lot_b["id"])
        assert after_b["sales_status"] == "PLATTED"
        assert after_b["lien_status"] == "ENCUMBERED"
        parcel = get_parcel(scenario["parcel"]["id"])
        assert parcel["lots_available_count"] == 3


class TestHOAControlThreshold:
    def test_hoa_evaluate_rejected_below_threshold(self, api):
        """PRD §3.8: "The ratio path uses integer cross-multiplication without floating point: transfer is due when `lots_closed_count` times ten thousand is greater than or equal to `total_lots_planned` times `control_transfer_pct_bp` — the boundary is inclusive, so a parcel sitting exactly on the threshold transfers; the ratio path also requires `total_lots_planned` greater than zero, since zero lots can never satisfy it."
        PRD §3.8: "Evaluating control — which a `DeveloperOperator`, or the `HOAManager` of that association, may invoke — moves the association from `DECLARANT_CONTROL` to `TRANSITIONING` when either condition holds and is rejected with `ERR_CONTROL_THRESHOLD_NOT_MET` when neither does."

        Design: Difficulty/boundary_precision_check/hoa_transfer_at_exactly_75_pct
        """
        # 2 of 4 lots closed: 2*10000 < 4*7500, and the statutory sunset
        # (2030-01-01) is not past at the default clock
        scenario = setup_hoa_threshold_scenario(pre_closed=2, total_lots=4)
        resp = api.evaluate_control(scenario["hoa"]["id"], DEV)
        validate_error(resp, ApiErrorId.ERR_CONTROL_THRESHOLD_NOT_MET)
        assert get_hoa(scenario["hoa"]["id"])["status"] == "DECLARANT_CONTROL"

    def test_hoa_auto_transitions_at_exactly_75_percent(self, api):
        """PRD §3.8: "The ratio path uses integer cross-multiplication without floating point: transfer is due when `lots_closed_count` times ten thousand is greater than or equal to `total_lots_planned` times `control_transfer_pct_bp` — the boundary is inclusive, so a parcel sitting exactly on the threshold transfers; the ratio path also requires `total_lots_planned` greater than zero, since zero lots can never satisfy it."
        PRD §3.8: "The same threshold also fires automatically: any closing finalize that carries the ratio to the threshold auto-transitions every `DECLARANT_CONTROL` association of the parcel to `TRANSITIONING` as the seventh link of the finalize cascade."

        Design: Difficulty/boundary_precision_check/hoa_transfer_at_exactly_75_pct
        """
        scenario = setup_hoa_threshold_scenario(pre_closed=2, total_lots=4)
        finalize_closing(scenario["pending_closing"]["id"])
        # 3/4 closed: 3*10000 >= 4*7500 holds at equality
        assert get_hoa(scenario["hoa"]["id"])["status"] == "TRANSITIONING"


class TestLotInventoryConservation:
    def test_reserve_moves_availability_but_conserves_recorded_count(self, api):
        """PRD §2.9: "**Lot inventory conservation.** For every phase, `recorded_lot_count` always equals the sum of that phase's lots across the four sales statuses — `PLATTED` plus `RESERVED` plus `UNDER_CONTRACT` plus `CLOSED`."
        PRD §3.5: "A successful reservation moves the lot from `PLATTED` to `RESERVED`, records the holding agreement on `reserved_agreement_id`, decrements the parcel's `lots_available_count` by one, and increments both the lot's `version` and the parcel's `version`."

        Design: Difficulty/compensating_invariant/lot_inventory_reserve_default_conservation
        """
        scenario = setup_selling_scenario(num_lots=3)
        assert scenario["phase"]["recorded_lot_count"] == 3
        reserve_lot(scenario["lots"][0]["id"], scenario["agreement"]["id"],
                    scenario["builder"]["id"])

        parcel = get_parcel(scenario["parcel"]["id"])
        # 3 PLATTED -> 2 PLATTED + 1 RESERVED; the bucket sum never changes
        assert parcel["lots_available_count"] == 2
        phase = get_phase(scenario["phase"]["id"])
        assert_lot_inventory_conserved(phase, list_phase_lots(phase["id"]))

    def test_default_release_restores_availability_exactly(self, api):
        """PRD §2.9: "Lots are created at recordation and never destroyed; they only move between statuses. A reserve followed by an agreement declare-default therefore leaves the phase's `PLATTED` count exactly where it started."

        Design: Difficulty/compensating_invariant/lot_inventory_reserve_default_conservation
        """
        scenario = setup_selling_scenario(num_lots=3)
        reserve_lot(scenario["lots"][0]["id"], scenario["agreement"]["id"],
                    scenario["builder"]["id"])
        validate_success(api.declare_default(
            scenario["agreement"]["id"], {"reason": "behind schedule"}, DEV))

        parcel = get_parcel(scenario["parcel"]["id"])
        assert parcel["lots_available_count"] == 3
        phase = get_phase(scenario["phase"]["id"])
        lots = list_phase_lots(phase["id"])
        assert all(lot["sales_status"] == "PLATTED" for lot in lots)
        assert_lot_inventory_conserved(phase, lots)


class TestAbsorptionForecasting:
    def test_absorption_pace_variants_diverge(self, api):
        """PRD §3.8: "The `straight_line_pace_pm` is the `total_lots_planned` divided by `planned_sellout_months`, rounded half-up to four decimal places, and reads zero when `planned_sellout_months` is zero; it derives from plan and ignores actual closings."
        PRD §3.8: "The `selected_pace_pm` is the straight-line figure when the parcel's `absorption_method` is `STRAIGHT_LINE` and the trailing-weighted figure when it is `TRAILING_WEIGHTED`; for identical parcel data the two paces diverge whenever actual closings diverge from plan."

        Design: Difficulty/dual_variant_calc/absorption_pace_straight_line_vs_trailing
        """
        scenario = setup_absorption_divergence_scenario()
        parcel = get_parcel(scenario["parcel"]["id"])
        # 8 recorded lots over 24 planned months, 4dp
        assert parcel["straight_line_pace_pm"] == pytest.approx(0.3333, abs=1e-9)
        # 0.5*2 + 0.3*1 + 0.2*0 over the trailing 30-day windows at 2026-08-01
        assert parcel["trailing_weighted_pace_pm"] == pytest.approx(1.3, abs=1e-9)
        assert parcel["straight_line_pace_pm"] != \
            parcel["trailing_weighted_pace_pm"]
        # TRAILING_WEIGHTED method selects the trailing variant
        assert parcel["selected_pace_pm"] == pytest.approx(1.3, abs=1e-9)

    def test_trailing_weighted_pace_from_window_composition(self, api):
        """PRD §3.8: "The `trailing_weighted_pace_pm` derives from actuals: count the parcel's `CLOSED` closings whose `finalized_at` falls in the trailing thirty-day window ending at the current clock — both endpoints included — and call it C1; count those in the window from sixty to thirty days back, including the sixty-day end but excluding the thirty-day end, as C2; and those from ninety to sixty days back on the same half-open basis as C3."

        Design: Difficulty/dual_variant_calc/absorption_pace_straight_line_vs_trailing
        """
        scenario = setup_absorption_divergence_scenario()
        parcel = get_parcel(scenario["parcel"]["id"])
        assert parcel["lots_closed_count"] == 3
        # the two 2026-07-20 closings land in C1 ([2026-07-02, 2026-08-01]);
        # the 2026-06-05 closing lands in C2 ([2026-06-01, 2026-07-02)); C3 empty
        assert parcel["trailing_weighted_pace_pm"] == pytest.approx(
            0.5 * 2 + 0.3 * 1 + 0.2 * 0, abs=1e-9)

    def test_trailing_window_edge_closing_counted_once(self, api):
        """PRD §3.8: "The `trailing_weighted_pace_pm` derives from actuals: count the parcel's `CLOSED` closings whose `finalized_at` falls in the trailing thirty-day window ending at the current clock — both endpoints included — and call it C1; count those in the window from sixty to thirty days back, including the sixty-day end but excluding the thirty-day end, as C2; and those from ninety to sixty days back on the same half-open basis as C3. A closing exactly thirty days back therefore belongs to C1 and is never double-counted."

        Design: Corner/calculations/trailing_window_edge_assignment
        """
        scenario = setup_trailing_edge_scenario()
        parcel = get_parcel(scenario["parcel"]["id"])
        # the closing finalized at 2026-07-02 sits exactly thirty days back from
        # 2026-08-01: C1's inclusive lower edge, counted exactly once at 0.5*1
        assert parcel["trailing_weighted_pace_pm"] == pytest.approx(0.5, abs=1e-9)

    def test_derived_fields_reconcile_after_record_and_finalize(self, api):
        """PRD §3.8: "`total_lots_planned` is the count of recorded lots across all of the parcel's phases; lots exist only after recordation, so plats that are merely approved contribute nothing yet. `lots_closed_count` counts the parcel's lots whose `sales_status` is `CLOSED`, and `lots_available_count` those in `PLATTED`. The `closed_pct` is one hundred times the closed count divided by the total, rounded half-up to two decimal places, and reads zero while no lots are recorded."
        PRD §3.8: "From the selected pace, `projected_months_to_sellout` is the remaining lot count — `total_lots_planned` minus `lots_closed_count` — divided by the selected pace, rounded half-up to one decimal place; when the selected pace is zero the projection is null. The `next_phase_release_eligible` flag reads true exactly when the projection is not null and is at most six months — the lead time the pipeline assumes for bringing the next phase to market."

        Design: Corner/cross_cutting_layers/derived_fields_reconcile_after_record_and_closing
        """
        parcel = create_acquired_parcel(parcel_name="DFP", planned_sellout_months=24)
        phase = create_phase(parcel["id"], planned_lot_count=2)
        walk_phase_to_recorded(phase["id"], 2)
        after_record = get_parcel(parcel["id"])
        assert after_record["total_lots_planned"] == 2
        assert after_record["lots_available_count"] == 2
        assert after_record["closed_pct"] == 0

        create_posted_bond(phase["id"])
        validate_success(api.activate_phase(phase["id"], DEV))
        builder = create_builder(builder_name="DFB", license_number="LIC-DF",
                                 contact_email="df@example.com")
        agreement = create_active_agreement(parcel["id"], builder["id"],
                                            scheduled_lot_count=2)
        create_active_loan(parcel["id"])
        lot = list_phase_lots(phase["id"])[0]
        closing = reserve_and_open_closing(lot["id"], agreement["id"],
                                           builder["id"])
        finalize_closing(closing["id"])

        after = get_parcel(parcel["id"])
        assert after["total_lots_planned"] == 2
        assert after["lots_closed_count"] == 1
        assert after["lots_available_count"] == 1
        assert after["closed_pct"] == 50.0
        # straight-line pace 2/24 at 4dp; projection 1 / 0.0833 at 1dp
        assert after["straight_line_pace_pm"] == pytest.approx(0.0833, abs=1e-9)
        assert after["projected_months_to_sellout"] == pytest.approx(12.0, abs=1e-9)
        # 12.0 months is beyond the six-month release lead time
        assert after["next_phase_release_eligible"] is False


class TestHOATransitionCompletion:
    def test_complete_transition_requires_three_seated(self, api):
        """PRD §3.8: "The statutory path is due when the current clock falls strictly later than `statutory_control_end` — the boundary is exclusive, so the clock reading exactly the sunset date does not transfer."
        PRD §3.8: "Completing the transition belongs to the association's own `HOAManager`. Supplying a `seated_board_count` of at least three seated homeowner board members moves the association from `TRANSITIONING` to terminal `HOMEOWNER_CONTROL` and records the count on `board_seated_count` (which is null until that moment); a request naming fewer than three is rejected with `ERR_BOARD_NOT_SEATED`."

        Design: Corner/errors/error_board_not_seated_via_statutory_transition
        """
        parcel = create_acquired_parcel(parcel_name="HP")
        hoa = create_formed_hoa(parcel["id"], hoa_name="HP HOA",
                                statutory_control_end="2026-01-01T00:00:00Z")
        # default clock 2026-08-01 falls strictly past the 2026-01-01 sunset
        evaluated = validate_success(api.evaluate_control(hoa["id"], DEV))
        assert evaluated["status"] == "TRANSITIONING"

        resp = api.complete_transition(hoa["id"], {"seated_board_count": 2},
                                       make_hoa_manager_headers(hoa["id"]))
        validate_error(resp, ApiErrorId.ERR_BOARD_NOT_SEATED)

    def test_hoa_manager_other_association_forbidden(self, api):
        """PRD §2.1: "When `X-User-Role` is `HOAManager`, `X-User-ID` is the `id` of the acting `HOAAssociation`; ownership checks compare the association's own `id` to `X-User-ID`, so a manager may evaluate or complete the control transition only for their own association."

        Design: Corner/rbac/hoa_manager_other_association_returns_403
        """
        parcel = create_acquired_parcel(parcel_name="HOP")
        hoa_one = create_formed_hoa(parcel["id"], hoa_name="HOA One",
                                    statutory_control_end="2030-01-01T00:00:00Z")
        hoa_two = create_formed_hoa(parcel["id"], hoa_name="HOA Two",
                                    statutory_control_end="2026-01-01T00:00:00Z")
        resp = api.evaluate_control(
            hoa_two["id"], make_hoa_manager_headers(hoa_one["id"]))
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE)
