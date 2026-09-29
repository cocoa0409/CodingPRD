"""The figuring loop and its two exits: the thickness floor and non-convergence."""

from test_helpers import (
    SCRAP_REASON_FIGURE_CONVERGENCE_FAILURE,
    SCRAP_REASON_MIN_THICKNESS_BREACH,
    assert_blank_ledger,
    assert_booked_minutes,
    assert_removal_ledger,
    assert_wavefront_value,
    create_certified_lot,
    create_instrument,
    create_released_design,
    make_plant_admin_headers,
    make_process_technician_headers,
    make_procurement_officer_headers,
    open_work_order,
    run_stage_pass,
    validate_success,
)

ACCEPTED_POLISHING_REPORT = {
    "surface_rms_waves": 0.0200,
    "surface_roughness_nm_rms": 0.8000,
}
REWORKED_FIGURING_REPORT = {
    "surface_rms_waves": 0.0200,
    "surface_roughness_nm_rms": 0.8000,
    "transmitted_wavefront_rms_waves": 0.1200,
}
FIGURE_OUT_OF_BUDGET_REPORT = {
    "surface_rms_waves": 0.0400,
    "surface_roughness_nm_rms": 0.8000,
    "transmitted_wavefront_rms_waves": 0.0500,
}


def _read_order(api, work_order_id):
    """Read one work order as the process technician who owns it."""
    return validate_success(
        api.get_work_order(work_order_id, make_process_technician_headers()),
        expected_status=200,
    )


def _read_lot(api, lot_id):
    """Read one melt lot as the procurement officer who booked it in."""
    return validate_success(
        api.get_glass_lot(lot_id, make_procurement_officer_headers()),
        expected_status=200,
    )


def _read_instrument(api, instrument_id):
    """Read one metrology station as the plant administrator."""
    return validate_success(
        api.get_metrology_instrument(instrument_id, make_plant_admin_headers()),
        expected_status=200,
    )


def _order_in_figuring(api, design_overrides=None, lot_overrides=None):
    """One order carried to FIGURING by an accepted 500 nm polishing pass."""
    design = create_released_design(
        api, design_code="OD-2540-FL", **(design_overrides or {})
    )
    lot = create_certified_lot(api, lot_code="GL-2540-FL", **(lot_overrides or {}))
    instrument = create_instrument(api, instrument_code="IF-2540-1")
    order = open_work_order(api, design["id"], lot["id"], lot["version"], element_count=2)
    run_stage_pass(
        api,
        order["id"],
        instrument["id"],
        "POLISHING",
        "2026-08-01T08:00:00Z",
        "2026-08-01T10:00:00Z",
        material_removed_nm=500.0,
        report_overrides=ACCEPTED_POLISHING_REPORT,
    )
    return {
        "design": design,
        "lot": lot,
        "instrument": instrument,
        "work_order": order,
    }


class TestFiguringLoopExhaustsItsIterations:
    """Two figuring reworks is one too many for the shop."""

    def test_the_first_figuring_rework_takes_the_loop_back_to_polishing(self, api):
        """Iteration one is spent and the order returns for another polishing pass.

        The PRD states that "A rework verdict on a `FIGURING`-stage run first
        increments `figuring_iteration_count`, which counts precisely the signed
        figuring-stage reports that came back `REWORK_REQUIRED`, and recomputes the
        removal ledger." and that "Otherwise the order takes the rework loop `FIGURING
        → POLISHING`, so that a further polishing pass can be scheduled and the cycle
        `FIGURING → POLISHING → FIGURING` repeats."

        Design: Corner/state_machines/second_figuring_rework_scraps_the_order_for_convergence_failure
        """
        ctx = _order_in_figuring(api)
        assert _read_order(api, ctx["work_order"]["id"])["process_status"] == "FIGURING"

        first_figuring = run_stage_pass(
            api,
            ctx["work_order"]["id"],
            ctx["instrument"]["id"],
            "FIGURING",
            "2026-08-01T11:00:00Z",
            "2026-08-01T12:00:00Z",
            material_removed_nm=500.0,
            report_overrides=REWORKED_FIGURING_REPORT,
        )

        assert first_figuring["signed"]["verdict"] == "REWORK_REQUIRED", (
            "0.1200 waves transmitted exceeds the 0.1050 budget, got "
            f"{first_figuring['signed']['verdict']}"
        )
        assert_wavefront_value(
            first_figuring["signed"]["stage_figure_budget_waves"],
            0.0250,
            "stage_figure_budget_waves",
        )
        order = _read_order(api, ctx["work_order"]["id"])
        assert order["process_status"] == "POLISHING", (
            f"the rework loop returns to POLISHING, got {order['process_status']}"
        )
        assert order["scrap_reason"] is None, (
            f"scrap_reason must stay null, got {order['scrap_reason']}"
        )
        assert_removal_ledger(order, 1000.0, 6199.0000, 1)

    def test_the_second_figuring_rework_scraps_the_order_for_non_convergence(self, api):
        """The count reaches two and the substrate is written off.

        The PRD states that "Second, if `figuring_iteration_count` after the increment
        has reached two or more, the order is scrapped with `scrap_reason` set to
        `FIGURE_CONVERGENCE_FAILURE` — the shop permits at most two figuring iterations
        before declaring the surface non-convergent." and that hop two "writes off the
        substrate: the lot's `reserved_blank_count` falls by the order's frozen
        `reserved_blank_count` and its `scrapped_blank_count` rises by exactly the same
        amount, `available_blank_count` is recomputed, and if the lot is in `RELEASED`
        with both `available_blank_count` and `reserved_blank_count` at zero it moves
        `RELEASED → DEPLETED`."

        Design: Corner/state_machines/second_figuring_rework_scraps_the_order_for_convergence_failure
        """
        ctx = _order_in_figuring(api)
        order_id = ctx["work_order"]["id"]
        instrument_id = ctx["instrument"]["id"]
        run_stage_pass(
            api,
            order_id,
            instrument_id,
            "FIGURING",
            "2026-08-01T11:00:00Z",
            "2026-08-01T12:00:00Z",
            material_removed_nm=500.0,
            report_overrides=REWORKED_FIGURING_REPORT,
        )
        run_stage_pass(
            api,
            order_id,
            instrument_id,
            "POLISHING",
            "2026-08-01T13:00:00Z",
            "2026-08-01T14:00:00Z",
            material_removed_nm=300.0,
            report_overrides=ACCEPTED_POLISHING_REPORT,
        )
        assert_removal_ledger(_read_order(api, order_id), 1300.0, 6198.7000, 1)

        second_figuring = run_stage_pass(
            api,
            order_id,
            instrument_id,
            "FIGURING",
            "2026-08-01T15:00:00Z",
            "2026-08-01T16:00:00Z",
            material_removed_nm=200.0,
            report_overrides=REWORKED_FIGURING_REPORT,
        )

        assert second_figuring["signed"]["verdict"] == "REWORK_REQUIRED", (
            f"verdict must be REWORK_REQUIRED, got {second_figuring['signed']['verdict']}"
        )
        run = validate_success(
            api.get_process_run(
                second_figuring["run"]["id"], make_process_technician_headers()
            ),
            expected_status=200,
        )
        assert run["run_status"] == "REWORK_REQUIRED", (
            f"run_status must be REWORK_REQUIRED, got {run['run_status']}"
        )
        order = _read_order(api, order_id)
        assert order["process_status"] == "SCRAPPED", (
            f"process_status must be SCRAPPED, got {order['process_status']}"
        )
        assert order["scrap_reason"] == SCRAP_REASON_FIGURE_CONVERGENCE_FAILURE, (
            "scrap_reason must be FIGURE_CONVERGENCE_FAILURE, got "
            f"{order['scrap_reason']}"
        )
        assert_removal_ledger(order, 1500.0, 6198.5000, 2)
        lot = _read_lot(api, ctx["lot"]["id"])
        assert_blank_ledger(
            lot, reserved=0, consumed=0, scrapped=3, available=17, total=20
        )
        assert lot["lot_status"] == "RELEASED", (
            "seventeen blanks remain available, so the lot is not depleted, got "
            f"{lot['lot_status']}"
        )
        assert_booked_minutes(_read_instrument(api, instrument_id), 300)


class TestThicknessFloorIsTestedBeforeTheIterationCount:
    """Two twin orders differ by three hundred nanometres of glass."""

    @staticmethod
    def _thin_margin_setup(api):
        """A design whose thickness floor leaves one micrometre of margin."""
        design = create_released_design(
            api, design_code="OD-2540-THIN", min_center_thickness_um=6199.0
        )
        lot = create_certified_lot(
            api, lot_code="GL-2540-THIN", blank_center_thickness_um=6200.0
        )
        instrument = create_instrument(api, instrument_code="IF-2540-1")
        first = open_work_order(
            api, design["id"], lot["id"], lot["version"], element_count=2
        )
        refreshed = _read_lot(api, lot["id"])
        second = open_work_order(
            api, design["id"], lot["id"], refreshed["version"], element_count=2
        )
        return {
            "design": design,
            "lot": lot,
            "instrument": instrument,
            "first": first,
            "second": second,
        }

    @staticmethod
    def _polish_then_figure(api, ctx, order, day, figuring_removal_nm):
        """One accepted 800 nm polishing pass then one reworked figuring pass."""
        run_stage_pass(
            api,
            order["id"],
            ctx["instrument"]["id"],
            "POLISHING",
            f"2026-08-{day}T08:00:00Z",
            f"2026-08-{day}T10:00:00Z",
            material_removed_nm=800.0,
            report_overrides=ACCEPTED_POLISHING_REPORT,
        )
        return run_stage_pass(
            api,
            order["id"],
            ctx["instrument"]["id"],
            "FIGURING",
            f"2026-08-{day}T11:00:00Z",
            f"2026-08-{day}T12:00:00Z",
            material_removed_nm=figuring_removal_nm,
            report_overrides=FIGURE_OUT_OF_BUDGET_REPORT,
        )

    def test_the_thickness_breach_scraps_the_order_on_its_very_first_rework(self, api):
        """One micrometre of margin is gone at 1200 nanometres of cumulative removal.

        The PRD states that "First, if `remaining_center_thickness_um` after
        recomputation is strictly less than the design's `min_center_thickness_um`, the
        order is scrapped with `scrap_reason` set to the literal string
        `MIN_THICKNESS_BREACH`." and that "The order of the two scrap tests matters: an
        order that simultaneously breached the thickness floor and exhausted its
        iterations is recorded as `MIN_THICKNESS_BREACH`, because thickness is tested
        first."

        Design: Corner/complexity_layers/the_thickness_threshold_scraps_an_order_on_its_first_rework_while_a_thinner_cut_survives
        """
        ctx = self._thin_margin_setup(api)

        figuring = self._polish_then_figure(api, ctx, ctx["first"], "01", 400.0)

        assert figuring["signed"]["verdict"] == "REWORK_REQUIRED", (
            "0.0400 waves exceeds the 0.0250 figuring budget, got "
            f"{figuring['signed']['verdict']}"
        )
        assert_wavefront_value(
            figuring["signed"]["stage_figure_budget_waves"],
            0.0250,
            "stage_figure_budget_waves",
        )
        order = _read_order(api, ctx["first"]["id"])
        assert order["process_status"] == "SCRAPPED", (
            f"process_status must be SCRAPPED, got {order['process_status']}"
        )
        assert order["scrap_reason"] == SCRAP_REASON_MIN_THICKNESS_BREACH, (
            f"scrap_reason must be MIN_THICKNESS_BREACH, got {order['scrap_reason']}"
        )
        assert_removal_ledger(order, 1200.0, 6198.8000, 1)

    def test_the_thinner_cut_survives_and_takes_the_rework_loop_instead(self, api):
        """A hundred-nanometre cut leaves the floor intact by a tenth of a micrometre.

        The PRD states that "`remaining_center_thickness_um` is the order's
        `blank_center_thickness_um` less that cumulative removal converted from
        nanometres to micrometres by dividing by one thousand, rounded half up to four
        decimal places."

        Design: Corner/complexity_layers/the_thickness_threshold_scraps_an_order_on_its_first_rework_while_a_thinner_cut_survives
        """
        ctx = self._thin_margin_setup(api)
        self._polish_then_figure(api, ctx, ctx["first"], "01", 400.0)

        survivor = self._polish_then_figure(api, ctx, ctx["second"], "02", 100.0)

        assert survivor["signed"]["verdict"] == "REWORK_REQUIRED", (
            f"verdict must be REWORK_REQUIRED, got {survivor['signed']['verdict']}"
        )
        order = _read_order(api, ctx["second"]["id"])
        assert order["process_status"] == "POLISHING", (
            "6199.1 is not below the 6199.0 floor, so the rework loop is taken, got "
            f"{order['process_status']}"
        )
        assert order["scrap_reason"] is None, (
            f"scrap_reason must stay null, got {order['scrap_reason']}"
        )
        assert_removal_ledger(order, 900.0, 6199.1000, 1)
        lot = _read_lot(api, ctx["lot"]["id"])
        assert_blank_ledger(
            lot, reserved=3, consumed=0, scrapped=3, available=14, total=20
        )
