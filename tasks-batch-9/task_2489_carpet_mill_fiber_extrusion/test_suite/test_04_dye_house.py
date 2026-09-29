"""Dye-house compliance tests: vessel registration and aggregate capacity over
closed touching windows, dye-lot formulation and the dye window gate,
spectrophotometer readings under the mandatory version check, the CIE76 colour
difference and the shade-band thresholds, the approve / re-dye / reject
dispositions and the bounded re-dye loop, the two uncommitted-yardage variants
and dye-lot exhaustion.
"""

import pytest

from test_helpers import (
    TEST_USERS,
    factories,
    fixtures,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.constants import DYE_WINDOW_OPEN_UTC, RUN_WINDOW_OPEN_UTC

PLANNER = TEST_USERS["mill_planner_headers"]
DYER = TEST_USERS["dye_house_operator_headers"]

# A reading that lands exactly on the band-A ceiling: the CIE76 distance from the
# target triple (55.00, 12.00, -8.00) is 0.80 to two places.
BAND_A_EDGE_READING = {
    "measured_lab_l": 55.48,
    "measured_lab_a": 12.64,
    "measured_lab_b": -8.0,
}
# A reading whose raw distance is 0.804301..., i.e. above 0.80 before rounding.
BAND_A_UNROUNDED_READING = {
    "measured_lab_l": 55.5,
    "measured_lab_a": 12.63,
    "measured_lab_b": -8.0,
}
# A reading three L* units off target: distance 3.00, band OUT.
BAND_OUT_READING = {
    "measured_lab_l": 58.0,
    "measured_lab_a": 12.0,
    "measured_lab_b": -8.0,
}
# A reading exactly on the band-C ceiling: distance 2.50.
BAND_C_EDGE_READING = {
    "measured_lab_l": 56.5,
    "measured_lab_a": 14.0,
    "measured_lab_b": -8.0,
}


def _backed_piece_dyed_run(
    vessel_overrides=None,
    greige_yards=None,
    machine_overrides=None,
):
    """Walk a piece-dyed style to a BACKED run and register a dye vessel.

    Returns a context dict with polymer_lot, fiber_batch, style, machine, vessel
    and run. The shared composite fixture pins the greige yardage, so this local
    variant exists only to let a test choose it.
    """
    polymer_lot = fixtures.create_polymer_lot()
    fiber_batch = fixtures.create_released_fiber_batch(
        polymer_lot["id"], dye_method="PIECE_DYED_READY", solution_color_code=None
    )
    style = fixtures.create_active_piece_dyed_style()
    machine = fixtures.create_tufting_machine(**(machine_overrides or {}))
    vessel = fixtures.create_dye_vessel(**(vessel_overrides or {}))
    run = fixtures.create_scheduled_run(
        style["id"], machine["id"], fiber_batch["id"]
    )
    greige_overrides = {} if greige_yards is None else {"greige_yards": greige_yards}
    run = fixtures.advance_run_to_backed(run["id"], greige_overrides=greige_overrides)
    return {
        "polymer_lot": polymer_lot,
        "fiber_batch": fiber_batch,
        "style": style,
        "machine": machine,
        "vessel": vessel,
        "run": run,
    }


def _measure(api, dye_lot_id, expected_version, reading):
    """Record one spectrophotometer reading and return the updated lot."""
    return validate_success(
        api.record_dye_lot_measurement(
            dye_lot_id,
            factories.measurement_payload(expected_version, **reading),
            DYER,
        ),
        200,
    )


class TestDyeVesselRegistrationAndCapacity:
    """Registering a vessel and booking mass into its shared, closed windows."""

    def test_touching_window_load_above_capacity_is_refused(self, api):
        """A lot starting exactly when a resident lot ends is refused when their
        aggregate mass exceeds the vessel's capacity at that instant.

        PRD: "If the load at any probe instant is strictly greater than the vessel's
        `capacity_kg`, the booking is refused with `ERR_VESSEL_CAPACITY_EXCEEDED`; a
        load exactly equal to capacity is admissible."

        PRD: "Because both ends are inclusive, a lot whose `dye_start_utc` equals
        another lot's `dye_end_utc` does contend for capacity."

        Design: Difficulty/resource_temporal_overlap/dye_vessel_capacity_aggregates_over_closed_touching_windows
        """
        ctx = _backed_piece_dyed_run(
            vessel_overrides={"capacity_kg": 1000.0}, greige_yards=900.0
        )
        resident = fixtures.create_dye_lot(
            ctx["run"]["id"],
            ctx["vessel"]["id"],
            lot_code="DL-01",
            lot_kg=600.0,
            dye_start_utc="2026-08-06T08:00:00Z",
            dye_end_utc="2026-08-06T12:00:00Z",
            dyed_yards=300.0,
        )

        response = api.create_dye_lot(
            factories.create_dye_lot_payload(
                ctx["run"]["id"],
                ctx["vessel"]["id"],
                lot_code="DL-02",
                lot_kg=401.0,
                dye_start_utc="2026-08-06T12:00:00Z",
                dye_end_utc="2026-08-06T16:00:00Z",
                dyed_yards=300.0,
            ),
            DYER,
        )
        validate_error(response, "ERR_VESSEL_CAPACITY_EXCEEDED")

        lots, _ = validate_paginated(
            api.list_dye_lots(DYER, params={"limit": 100, "offset": 0})
        )
        codes = [lot["lot_code"] for lot in lots]
        assert "DL-02" not in codes, (
            f"the refused booking must persist nothing, but the vessel now holds {codes}"
        )

        resident_after = fixtures.refresh_dye_lot(resident["id"])
        assert resident_after["status"] == "FORMULATED", (
            "the resident lot must be untouched by the refused booking, got status "
            f"{resident_after['status']}"
        )
        assert resident_after["lot_kg"] == pytest.approx(600.0, abs=0.01), (
            f"expected 600.0 resident kg, got {resident_after['lot_kg']}"
        )

    def test_touching_window_load_exactly_at_capacity_is_admitted(self, api):
        """A lot booked from the resident lot's end instant is admitted when the
        aggregate load lands exactly on capacity.

        PRD: "If the load at any probe instant is strictly greater than the vessel's
        `capacity_kg`, the booking is refused with `ERR_VESSEL_CAPACITY_EXCEEDED`; a
        load exactly equal to capacity is admissible."

        Design: Difficulty/resource_temporal_overlap/dye_vessel_capacity_aggregates_over_closed_touching_windows
        """
        ctx = _backed_piece_dyed_run(
            vessel_overrides={"capacity_kg": 1000.0}, greige_yards=900.0
        )
        resident = fixtures.create_dye_lot(
            ctx["run"]["id"],
            ctx["vessel"]["id"],
            lot_code="DL-01",
            lot_kg=600.0,
            dye_start_utc="2026-08-06T08:00:00Z",
            dye_end_utc="2026-08-06T12:00:00Z",
            dyed_yards=300.0,
        )

        response = api.create_dye_lot(
            factories.create_dye_lot_payload(
                ctx["run"]["id"],
                ctx["vessel"]["id"],
                lot_code="DL-03",
                lot_kg=400.0,
                dye_start_utc="2026-08-06T12:00:00Z",
                dye_end_utc="2026-08-06T16:00:00Z",
                dyed_yards=300.0,
            ),
            DYER,
        )
        admitted = validate_success(response, 201)
        assert admitted["status"] == "FORMULATED", (
            f"a booking exactly on capacity must be admitted, got {admitted['status']}"
        )
        assert admitted["lot_kg"] == pytest.approx(400.0, abs=0.01), (
            f"expected 400.0 kg booked, got {admitted['lot_kg']}"
        )
        assert admitted["dye_start_utc"][:19] == resident["dye_end_utc"][:19], (
            "the admitted lot must start exactly when the resident lot ends: "
            f"{admitted['dye_start_utc']} vs {resident['dye_end_utc']}"
        )

    def test_unknown_vessel_type_is_rejected_and_persists_nothing(self, api):
        """A vessel_type outside the declared set is a malformed request and no
        vessel row is created.

        PRD: "a `vessel_type` of either `BECK` or `JET`"

        PRD: "every enum value lies in its declared set, every numeric lies in its
        declared range"

        Design: Corner/entities/create_dye_vessel_with_unknown_vessel_type_returns_invalid_request
        """
        response = api.create_dye_vessel(
            factories.create_dye_vessel_payload(vessel_type="KETTLE"), DYER
        )
        validate_error(response, "ERR_INVALID_REQUEST")

        _, meta = validate_paginated(
            api.list_dye_vessels(DYER, params={"limit": 10, "offset": 0})
        )
        assert meta["total_count"] == 0, (
            f"no vessel may be persisted by a rejected registration, got "
            f"{meta['total_count']}"
        )


class TestDyeWindowGate:
    """Charging a lot into its booked vessel before the window opens."""

    def test_start_dyeing_before_the_window_opens_is_refused(self, api):
        """With the clock still on the run's day, charging a lot whose dye window
        opens the next day is refused and the lot stays FORMULATED.

        PRD: "the logical clock must have reached the lot's `dye_start_utc`, failing
        which the refusal is `ERR_DYE_WINDOW_NOT_OPEN`"

        PRD: "A new lot begins with `status` of `FORMULATED`, `redye_count` of 0,
        `scrapped_yards` of 0, a null `parent_dye_lot_id`, null `measured_lab_l`,
        `measured_lab_a`, `measured_lab_b`, `delta_e` and `shade_band`"

        Design: Corner/state_machines/start_dyeing_before_dye_window_returns_dye_window_not_open
        """
        ctx = _backed_piece_dyed_run(machine_overrides={"changeover_minutes": 0})
        lot = fixtures.create_dye_lot(
            ctx["run"]["id"],
            ctx["vessel"]["id"],
            dye_start_utc=DYE_WINDOW_OPEN_UTC,
            dye_end_utc="2026-08-06T14:00:00Z",
        )
        # The backed run left the clock on the run window, a full day before the
        # lot's dye window opens.
        fixtures.set_clock(RUN_WINDOW_OPEN_UTC)

        validate_error(
            api.start_dyeing(lot["id"], DYER), "ERR_DYE_WINDOW_NOT_OPEN"
        )

        after = fixtures.refresh_dye_lot(lot["id"])
        assert after["status"] == "FORMULATED", (
            f"the lot must stay FORMULATED, got {after['status']}"
        )
        assert after["delta_e"] is None, (
            f"delta_e must still be null, got {after['delta_e']}"
        )
        assert after["shade_band"] is None, (
            f"shade_band must still be null, got {after['shade_band']}"
        )
        assert after["version"] == 1, (
            f"a refused charge must not mutate the lot, but version is {after['version']}"
        )


class TestDeltaEAndShadeBands:
    """The CIE76 colour difference, its single rounding, and the band thresholds."""

    def test_shade_band_thresholds_are_inclusive_at_each_ceiling(self, api):
        """Rounded delta_e values of 0.80, 1.50 and 2.50 land in bands A, B and C
        respectively, and 3.00 lands in OUT.

        PRD: "`A` when `delta_e` is at most 0.80, otherwise `B` when it is at most
        1.50, otherwise `C` when it is at most 2.50, otherwise `OUT`"

        PRD: "All three comparisons are inclusive, so a `delta_e` of exactly 0.80 is
        band `A`, exactly 1.50 is band `B` and exactly 2.50 is band `C`"

        Design: Difficulty/boundary_precision_check/shade_band_thresholds_inclusive_at_080_150_and_250
        """
        lots = self._four_measured_lots(api)
        expectations = [
            ("DL-01", 0.80, "A"),
            ("DL-02", 1.50, "B"),
            ("DL-03", 2.50, "C"),
            ("DL-04", 3.00, "OUT"),
        ]
        for code, expected_delta_e, expected_band in expectations:
            measured = lots[code]
            assert measured["delta_e"] == pytest.approx(expected_delta_e, abs=0.01), (
                f"{code}: expected delta_e {expected_delta_e}, got "
                f"{measured['delta_e']}"
            )
            assert measured["shade_band"] == expected_band, (
                f"{code}: delta_e {measured['delta_e']} must band as "
                f"{expected_band}, got {measured['shade_band']}"
            )

    def test_band_out_lot_cannot_be_approved(self, api):
        """A lot whose rounded delta_e is 3.00 bands OUT and its approval is refused,
        leaving it in MEASURED.

        PRD: "a lot banded `OUT` cannot be approved and is refused with
        `ERR_SHADE_BAND_NOT_APPROVABLE`"

        Design: Difficulty/boundary_precision_check/shade_band_thresholds_inclusive_at_080_150_and_250
        """
        lots = self._four_measured_lots(api)
        out_lot = lots["DL-04"]
        assert out_lot["shade_band"] == "OUT", (
            f"setup expectation: DL-04 must band OUT, got {out_lot['shade_band']}"
        )

        validate_error(
            api.disposition_dye_lot(out_lot["id"], {"disposition": "APPROVE"}, DYER),
            "ERR_SHADE_BAND_NOT_APPROVABLE",
        )

        after = fixtures.refresh_dye_lot(out_lot["id"])
        assert after["status"] == "MEASURED", (
            f"the refused approval must leave the lot MEASURED, got {after['status']}"
        )

    def test_band_c_ceiling_lot_is_approvable(self, api):
        """A lot whose rounded delta_e is exactly 2.50 is inside band C, not OUT, so
        its approval succeeds.

        PRD: "All three comparisons are inclusive, so a `delta_e` of exactly 0.80 is
        band `A`, exactly 1.50 is band `B` and exactly 2.50 is band `C`"

        Design: Difficulty/boundary_precision_check/shade_band_thresholds_inclusive_at_080_150_and_250
        """
        lots = self._four_measured_lots(api)
        edge_lot = lots["DL-03"]
        assert edge_lot["delta_e"] == pytest.approx(2.50, abs=0.01), (
            f"setup expectation: DL-03 delta_e must be 2.50, got {edge_lot['delta_e']}"
        )

        approved = validate_success(
            api.disposition_dye_lot(edge_lot["id"], {"disposition": "APPROVE"}, DYER),
            200,
        )
        assert approved["status"] == "APPROVED", (
            f"a band-C lot must be approvable, got {approved['status']}"
        )
        assert approved["shade_band"] == "C", (
            f"approval must not re-band the lot, got {approved['shade_band']}"
        )

    def test_delta_e_rounds_once_after_the_square_root(self, api):
        """A raw CIE76 distance of 0.804301... rounds to 0.80 and therefore bands A,
        which banding on the unrounded root would not.

        PRD: "take the square root of that sum; and round the result half-up to 2
        decimal places exactly once, after the square root"

        PRD: "The shade band is assigned immediately afterwards from the **rounded**
        `delta_e`, never from the raw square root"

        Design: Corner/calculations/delta_e_rounds_once_after_the_square_root
        """
        ctx = _backed_piece_dyed_run(machine_overrides={"changeover_minutes": 0})
        lot = fixtures.create_dye_lot(ctx["run"]["id"], ctx["vessel"]["id"])
        dyeing = fixtures.start_dyeing(lot["id"], clock_to=DYE_WINDOW_OPEN_UTC)

        measured = _measure(
            api, lot["id"], dyeing["version"], BAND_A_UNROUNDED_READING
        )
        assert measured["delta_e"] == pytest.approx(0.80, abs=0.01), (
            f"expected delta_e 0.80 from a raw root of 0.804301, got "
            f"{measured['delta_e']}"
        )
        assert measured["shade_band"] == "A", (
            f"a rounded delta_e of 0.80 must band A, got {measured['shade_band']}"
        )
        assert measured["status"] == "MEASURED", (
            f"the reading must advance the lot to MEASURED, got {measured['status']}"
        )

        approved = validate_success(
            api.disposition_dye_lot(lot["id"], {"disposition": "APPROVE"}, DYER), 200
        )
        assert approved["status"] == "APPROVED", (
            f"expected APPROVED, got {approved['status']}"
        )
        assert approved["redye_count"] == 0, (
            f"a first-pass approval must leave redye_count at 0, got "
            f"{approved['redye_count']}"
        )
        assert approved["uncommitted_yards"] == pytest.approx(400.0, abs=0.01), (
            f"expected 400.0 uncommitted yards, got {approved['uncommitted_yards']}"
        )
        assert approved["shipped_basis_uncommitted_yards"] == pytest.approx(
            400.0, abs=0.01
        ), (
            "expected 400.0 shipped-basis uncommitted yards, got "
            f"{approved['shipped_basis_uncommitted_yards']}"
        )

    @staticmethod
    def _four_measured_lots(api):
        """Four lots on one vessel, identical targets, four different readings."""
        ctx = _backed_piece_dyed_run(vessel_overrides={"vessel_type": "JET"})
        readings = {
            "DL-01": BAND_A_EDGE_READING,
            "DL-02": {
                "measured_lab_l": 56.2,
                "measured_lab_a": 12.9,
                "measured_lab_b": -8.0,
            },
            "DL-03": BAND_C_EDGE_READING,
            "DL-04": BAND_OUT_READING,
        }
        lots = {}
        for code in readings:
            lots[code] = fixtures.create_dye_lot(
                ctx["run"]["id"],
                ctx["vessel"]["id"],
                lot_code=code,
                dyed_yards=100.0,
            )
        fixtures.set_clock(DYE_WINDOW_OPEN_UTC)
        measured = {}
        for code, reading in readings.items():
            dyeing = fixtures.start_dyeing(lots[code]["id"], clock_to=None)
            measured[code] = _measure(
                api, lots[code]["id"], dyeing["version"], reading
            )
        return measured


class TestDyeLotDispositions:
    """The approve / re-dye / reject decision and the bounded re-dye loop."""

    def test_redye_charge_clears_the_reading_and_counts_the_cycle(self, api):
        """Re-queueing an OUT lot records the head of the chain, and the next charge
        increments redye_count and clears the previous reading.

        PRD: "A permitted re-dye sets `status` to `REDYE_QUEUED` and, when
        `parent_dye_lot_id` is still null, sets `parent_dye_lot_id` to this lot's own
        `id`"

        PRD: "From `REDYE_QUEUED` the charge additionally increments `redye_count` by
        1 and clears `measured_lab_l`, `measured_lab_a`, `measured_lab_b`, `delta_e`
        and `shade_band` all back to null"

        Design: Difficulty/non_linear_state_machine/dye_lot_redye_revision_loop_bounded_by_max_redye_count
        """
        lot_id = self._formulated_lot()

        first = fixtures.start_dyeing(lot_id, clock_to=DYE_WINDOW_OPEN_UTC)
        measured = _measure(api, lot_id, first["version"], BAND_OUT_READING)
        assert measured["delta_e"] == pytest.approx(3.00, abs=0.01), (
            f"expected delta_e 3.00 on the first bath, got {measured['delta_e']}"
        )
        assert measured["shade_band"] == "OUT", (
            f"expected band OUT on the first bath, got {measured['shade_band']}"
        )

        requeued = validate_success(
            api.disposition_dye_lot(lot_id, {"disposition": "REDYE"}, DYER), 200
        )
        assert requeued["status"] == "REDYE_QUEUED", (
            f"expected REDYE_QUEUED, got {requeued['status']}"
        )
        assert requeued["parent_dye_lot_id"] == lot_id, (
            "the head of the re-dye chain must be the lot's own id, got "
            f"{requeued['parent_dye_lot_id']}"
        )

        second = fixtures.start_dyeing(lot_id, clock_to=None)
        assert second["status"] == "DYEING", (
            f"the re-dye charge must re-enter DYEING, got {second['status']}"
        )
        assert second["redye_count"] == 1, (
            f"expected redye_count 1 after the second charge, got "
            f"{second['redye_count']}"
        )
        assert second["delta_e"] is None, (
            f"the re-dye charge must clear delta_e, got {second['delta_e']}"
        )
        assert second["shade_band"] is None, (
            f"the re-dye charge must clear shade_band, got {second['shade_band']}"
        )

        remeasured = _measure(api, lot_id, second["version"], BAND_C_EDGE_READING)
        assert remeasured["delta_e"] == pytest.approx(2.50, abs=0.01), (
            f"expected delta_e 2.50 on the second bath, got {remeasured['delta_e']}"
        )
        assert remeasured["shade_band"] == "C", (
            f"expected band C on the second bath, got {remeasured['shade_band']}"
        )

    def test_third_redye_is_refused_at_the_cycle_limit(self, api):
        """After two completed re-dye cycles the third re-dye request is refused and
        the lot is left exactly as it was.

        PRD: "requires `redye_count` to be strictly less than the maximum of 2
        completed re-dye cycles, failing which the refusal is
        `ERR_REDYE_LIMIT_REACHED`"

        Design: Difficulty/non_linear_state_machine/dye_lot_redye_revision_loop_bounded_by_max_redye_count
        """
        lot_id = self._formulated_lot()

        first = fixtures.start_dyeing(lot_id, clock_to=DYE_WINDOW_OPEN_UTC)
        _measure(api, lot_id, first["version"], BAND_OUT_READING)
        fixtures.disposition_dye_lot(lot_id, "REDYE")

        second = fixtures.start_dyeing(lot_id, clock_to=None)
        _measure(api, lot_id, second["version"], BAND_C_EDGE_READING)
        fixtures.disposition_dye_lot(lot_id, "REDYE")

        third = fixtures.start_dyeing(lot_id, clock_to=None)
        assert third["redye_count"] == 2, (
            f"expected redye_count 2 after the third charge, got "
            f"{third['redye_count']}"
        )
        _measure(api, lot_id, third["version"], BAND_C_EDGE_READING)

        validate_error(
            api.disposition_dye_lot(lot_id, {"disposition": "REDYE"}, DYER),
            "ERR_REDYE_LIMIT_REACHED",
        )

        after = fixtures.refresh_dye_lot(lot_id)
        assert after["status"] == "MEASURED", (
            f"the refused re-dye must leave the lot MEASURED, got {after['status']}"
        )
        assert after["redye_count"] == 2, (
            f"the refused re-dye must not move redye_count, got {after['redye_count']}"
        )

    def test_band_c_lot_is_approvable_after_the_redye_budget_is_spent(self, api):
        """Band C is legal for both dispositions, so a lot that has exhausted its
        re-dye budget at band C can still be approved.

        PRD: "Note that band `C` is deliberately legal for both `APPROVE` and
        `REDYE`: it is the operator's judgement call whether to sell a marginal match
        or run it again."

        Design: Difficulty/non_linear_state_machine/dye_lot_redye_revision_loop_bounded_by_max_redye_count
        """
        lot_id = self._formulated_lot()

        first = fixtures.start_dyeing(lot_id, clock_to=DYE_WINDOW_OPEN_UTC)
        _measure(api, lot_id, first["version"], BAND_OUT_READING)
        fixtures.disposition_dye_lot(lot_id, "REDYE")
        second = fixtures.start_dyeing(lot_id, clock_to=None)
        _measure(api, lot_id, second["version"], BAND_C_EDGE_READING)
        fixtures.disposition_dye_lot(lot_id, "REDYE")
        third = fixtures.start_dyeing(lot_id, clock_to=None)
        _measure(api, lot_id, third["version"], BAND_C_EDGE_READING)
        validate_error(
            api.disposition_dye_lot(lot_id, {"disposition": "REDYE"}, DYER),
            "ERR_REDYE_LIMIT_REACHED",
        )

        approved = validate_success(
            api.disposition_dye_lot(lot_id, {"disposition": "APPROVE"}, DYER), 200
        )
        assert approved["status"] == "APPROVED", (
            f"a band-C lot must remain approvable, got {approved['status']}"
        )
        assert approved["shade_band"] == "C", (
            f"expected band C to be preserved, got {approved['shade_band']}"
        )
        assert approved["uncommitted_yards"] == pytest.approx(400.0, abs=0.01), (
            f"expected 400.0 uncommitted yards on approval, got "
            f"{approved['uncommitted_yards']}"
        )

    def test_shade_band_gates_which_disposition_a_measured_lot_may_take(self, api):
        """A band-A lot may be approved but not re-dyed, while a band-OUT lot may be
        re-dyed but not approved.

        PRD: "`APPROVE` requires the lot to be in `MEASURED` and its `shade_band` to
        be `A`, `B` or `C`; a lot banded `OUT` cannot be approved and is refused with
        `ERR_SHADE_BAND_NOT_APPROVABLE`"

        PRD: "`REDYE` requires the lot to be in `MEASURED` and its `shade_band` to be
        `C` or `OUT` — a lot that already landed in band `A` or `B` has nothing to
        gain from a second bath and is refused with `ERR_SHADE_BAND_NOT_REDYEABLE`"

        Design: Corner/validations/shade_band_gates_which_dispositions_a_measured_lot_may_take
        """
        ctx = _backed_piece_dyed_run(machine_overrides={"changeover_minutes": 0})
        band_a = fixtures.create_dye_lot(
            ctx["run"]["id"],
            ctx["vessel"]["id"],
            lot_code="DL-01",
            lot_kg=200.0,
            dyed_yards=200.0,
            dye_start_utc="2026-08-06T08:00:00Z",
            dye_end_utc="2026-08-06T14:00:00Z",
        )
        band_out = fixtures.create_dye_lot(
            ctx["run"]["id"],
            ctx["vessel"]["id"],
            lot_code="DL-02",
            lot_kg=200.0,
            dyed_yards=200.0,
            dye_start_utc="2026-08-06T14:00:00Z",
            dye_end_utc="2026-08-06T20:00:00Z",
        )
        fixtures.set_clock("2026-08-06T14:00:00Z")

        a_dyeing = fixtures.start_dyeing(band_a["id"], clock_to=None)
        out_dyeing = fixtures.start_dyeing(band_out["id"], clock_to=None)
        a_measured = _measure(
            api, band_a["id"], a_dyeing["version"], BAND_A_UNROUNDED_READING
        )
        out_measured = _measure(
            api, band_out["id"], out_dyeing["version"], BAND_OUT_READING
        )
        assert a_measured["delta_e"] == pytest.approx(0.80, abs=0.01), (
            f"expected DL-01 delta_e 0.80, got {a_measured['delta_e']}"
        )
        assert a_measured["shade_band"] == "A", (
            f"expected DL-01 in band A, got {a_measured['shade_band']}"
        )
        assert out_measured["delta_e"] == pytest.approx(3.00, abs=0.01), (
            f"expected DL-02 delta_e 3.00, got {out_measured['delta_e']}"
        )
        assert out_measured["shade_band"] == "OUT", (
            f"expected DL-02 in band OUT, got {out_measured['shade_band']}"
        )

        validate_error(
            api.disposition_dye_lot(band_a["id"], {"disposition": "REDYE"}, DYER),
            "ERR_SHADE_BAND_NOT_REDYEABLE",
        )
        validate_error(
            api.disposition_dye_lot(band_out["id"], {"disposition": "APPROVE"}, DYER),
            "ERR_SHADE_BAND_NOT_APPROVABLE",
        )

        approved = validate_success(
            api.disposition_dye_lot(band_a["id"], {"disposition": "APPROVE"}, DYER),
            200,
        )
        assert approved["status"] == "APPROVED", (
            f"the band-A lot must be approvable, got {approved['status']}"
        )
        requeued = validate_success(
            api.disposition_dye_lot(band_out["id"], {"disposition": "REDYE"}, DYER),
            200,
        )
        assert requeued["status"] == "REDYE_QUEUED", (
            f"the band-OUT lot must be re-dyeable, got {requeued['status']}"
        )
        assert requeued["parent_dye_lot_id"] == band_out["id"], (
            "the re-dyed lot must record itself as the head of the chain, got "
            f"{requeued['parent_dye_lot_id']}"
        )

    @staticmethod
    def _formulated_lot():
        """A FORMULATED lot on a backed piece-dyed run, targeting 55/12/-8."""
        ctx = _backed_piece_dyed_run()
        lot = fixtures.create_dye_lot(ctx["run"]["id"], ctx["vessel"]["id"])
        return lot["id"]


class TestUncommittedYardageVariants:
    """The commitment-aware figure, the shipped-only figure, and exhaustion."""

    def test_reservation_moves_only_the_commitment_aware_figure(self, api):
        """Immediately after allocation the two persisted figures differ by exactly
        the reserved yardage.

        PRD: "`uncommitted_yards` subtracts the sum of `yards` over allocation lines
        drawn from rolls of this lot whose status is `RESERVED`, `CUT` or `SHIPPED`,
        so a merely reserved commitment already removes the yardage from the sellable
        pool. `shipped_basis_uncommitted_yards` subtracts only the sum of `yards`
        over lines whose status is `SHIPPED`, so reserved and cut-but-unshipped
        yardage still counts as sellable."

        Design: Difficulty/dual_variant_calc/dye_lot_uncommitted_yards_commitment_aware_vs_shipped_only
        """
        ctx = self._order_against_one_approved_lot()

        order = validate_success(
            api.allocate_cut_order(ctx["cut_order"]["id"], PLANNER), 200
        )
        assert order["status"] == "ALLOCATED", (
            f"expected ALLOCATED, got {order['status']}"
        )
        assert order["allocated_yards"] == pytest.approx(120.0, abs=0.01), (
            f"expected 120.0 allocated yards, got {order['allocated_yards']}"
        )
        assert order["gross_cents"] == 513000, (
            f"expected gross_cents 513000, got {order['gross_cents']}"
        )
        assert order["freight_cents"] == 0, (
            f"expected freight_cents 0, got {order['freight_cents']}"
        )
        assert order["net_invoice_cents"] == 513000, (
            f"expected net_invoice_cents 513000, got {order['net_invoice_cents']}"
        )

        lot = fixtures.refresh_dye_lot(ctx["dye_lot"]["id"])
        assert lot["uncommitted_yards"] == pytest.approx(280.0, abs=0.01), (
            "the reserved 120.0 yards must leave the commitment-aware pool, expected "
            f"280.0, got {lot['uncommitted_yards']}"
        )
        assert lot["shipped_basis_uncommitted_yards"] == pytest.approx(
            400.0, abs=0.01
        ), (
            "nothing has shipped, so the shipped-basis figure must still be 400.0, "
            f"got {lot['shipped_basis_uncommitted_yards']}"
        )
        gap = lot["shipped_basis_uncommitted_yards"] - lot["uncommitted_yards"]
        assert gap == pytest.approx(120.0, abs=0.01), (
            f"the gap must equal the reserved yardage 120.0, got {gap}"
        )
        assert lot["status"] == "APPROVED", (
            f"280.0 yards remain uncommitted, so the lot stays APPROVED, got "
            f"{lot['status']}"
        )

        roll = fixtures.refresh_roll_good(ctx["roll_good"]["id"])
        assert roll["available_yards"] == pytest.approx(80.0, abs=0.01), (
            f"expected 80.0 available roll yards, got {roll['available_yards']}"
        )
        assert roll["inventory_status"] == "AVAILABLE", (
            f"a roll with yardage left stays AVAILABLE, got {roll['inventory_status']}"
        )

    def test_shipment_converges_both_figures(self, api):
        """Once the order ships, the shipped-only figure moves down to meet the
        commitment-aware figure.

        PRD: "Both uncommitted-yardage figures are recomputed for every dye lot
        touched by the shipment — the shipped-only figure moves for the first time
        here"

        PRD: "the order's `reserved_credit_cents` hold is replaced by its
        `net_invoice_cents`"

        Design: Difficulty/dual_variant_calc/dye_lot_uncommitted_yards_commitment_aware_vs_shipped_only
        """
        ctx = self._order_against_one_approved_lot()
        order_id = ctx["cut_order"]["id"]

        fixtures.allocate_cut_order(order_id)
        fixtures.cut_cut_order(order_id)
        shipped = validate_success(api.ship_cut_order(order_id, PLANNER), 200)
        assert shipped["status"] == "SHIPPED", (
            f"expected SHIPPED, got {shipped['status']}"
        )

        lot = fixtures.refresh_dye_lot(ctx["dye_lot"]["id"])
        assert lot["uncommitted_yards"] == pytest.approx(280.0, abs=0.01), (
            f"expected 280.0 uncommitted yards after shipping, got "
            f"{lot['uncommitted_yards']}"
        )
        assert lot["shipped_basis_uncommitted_yards"] == pytest.approx(
            280.0, abs=0.01
        ), (
            "the shipped-basis figure must now match, expected 280.0, got "
            f"{lot['shipped_basis_uncommitted_yards']}"
        )
        assert lot["scrapped_yards"] == pytest.approx(0.0, abs=0.01), (
            f"no yardage was scrapped, got {lot['scrapped_yards']}"
        )

        account = fixtures.refresh_account(ctx["account"]["id"])
        assert account["credit_used_cents"] == 513000, (
            "the shipped order must be counted at its invoiced value 513000, got "
            f"{account['credit_used_cents']}"
        )

    def test_lot_exhausts_when_the_commitment_aware_figure_reaches_zero(self, api):
        """Allocating the last dyed yard drives uncommitted_yards to 0.0 and flips
        the lot APPROVED to EXHAUSTED, while the shipped-only figure is untouched.

        PRD: "When a lot in `APPROVED` has an `uncommitted_yards` of zero or less
        after any such recomputation, it transitions `APPROVED` to `EXHAUSTED`, which
        is terminal"

        Design: Corner/state_machines/dye_lot_auto_exhausts_when_uncommitted_yards_reach_zero
        """
        ctx = fixtures.setup_submitted_cut_order(
            piece_dyed=True,
            machine_overrides={"changeover_minutes": 0},
            dye_lot_overrides={"dyed_yards": 100.0},
            measurement_overrides=dict(BAND_A_EDGE_READING),
            roll_overrides={"initial_yards": 100.0},
            order_overrides={
                "requested_yards": 100.0,
                "shade_tolerance": "SINGLE_LOT",
            },
        )

        order = validate_success(
            api.allocate_cut_order(ctx["cut_order"]["id"], PLANNER), 200
        )
        assert order["status"] == "ALLOCATED", (
            f"expected ALLOCATED, got {order['status']}"
        )
        assert order["allocated_yards"] == pytest.approx(100.0, abs=0.01), (
            f"expected 100.0 allocated yards, got {order['allocated_yards']}"
        )
        assert order["gross_cents"] == 427500, (
            f"expected gross_cents 427500, got {order['gross_cents']}"
        )
        assert order["freight_cents"] == 0, (
            f"expected freight_cents 0, got {order['freight_cents']}"
        )
        assert order["net_invoice_cents"] == 427500, (
            f"expected net_invoice_cents 427500, got {order['net_invoice_cents']}"
        )

        lot = fixtures.refresh_dye_lot(ctx["dye_lot"]["id"])
        assert lot["uncommitted_yards"] == pytest.approx(0.0, abs=0.01), (
            f"expected 0.0 uncommitted yards, got {lot['uncommitted_yards']}"
        )
        assert lot["status"] == "EXHAUSTED", (
            f"a lot with no uncommitted yardage must be EXHAUSTED, got {lot['status']}"
        )
        assert lot["shipped_basis_uncommitted_yards"] == pytest.approx(
            100.0, abs=0.01
        ), (
            "nothing has shipped, so the shipped-basis figure must still be 100.0, "
            f"got {lot['shipped_basis_uncommitted_yards']}"
        )
        assert lot["scrapped_yards"] == pytest.approx(0.0, abs=0.01), (
            f"no yardage was scrapped, got {lot['scrapped_yards']}"
        )

        roll = fixtures.refresh_roll_good(ctx["roll_good"]["id"])
        assert roll["available_yards"] == pytest.approx(0.0, abs=0.01), (
            f"expected 0.0 available roll yards, got {roll['available_yards']}"
        )
        assert roll["inventory_status"] == "COMMITTED", (
            f"a fully reserved passed roll reads COMMITTED, got "
            f"{roll['inventory_status']}"
        )

    @staticmethod
    def _order_against_one_approved_lot():
        """One approved 400-yard lot, one 200-yard roll, and a 120-yard order."""
        return fixtures.setup_submitted_cut_order(
            piece_dyed=True,
            measurement_overrides=dict(BAND_A_EDGE_READING),
            order_overrides={"shade_tolerance": "ANY"},
        )


class TestRejectedLotBlocksAllocation:
    """Rejecting a lot scraps its rolls and closes them to further commitment."""

    def test_rejected_lot_refuses_a_manual_line_off_its_rolls(self, api):
        """A roll that was allocatable a moment ago is refused once its dye lot is
        rejected, and the dye-lot error is what comes back.

        PRD: "no allocation may draw from a roll whose dye lot is `REJECTED` —
        `ERR_DYE_LOT_EXHAUSTED` (409)"

        PRD: "every roll good whose dye lot is this lot and whose `inventory_status`
        is not already `SCRAPPED` has its `qa_status` set to `FAILED`, its
        `inventory_status` set to `SCRAPPED` and its `available_yards` forced to 0"

        Design: Corner/validations/a_rejected_dye_lot_blocks_allocation_from_the_rolls_it_dyed
        """
        ctx = fixtures.setup_submitted_cut_order(
            piece_dyed=True,
            machine_overrides={"changeover_minutes": 0},
            measurement_overrides=dict(BAND_A_UNROUNDED_READING),
            roll_overrides={"initial_yards": 100.0},
            order_overrides={
                "requested_yards": 50.0,
                "shade_tolerance": "SINGLE_LOT",
            },
        )
        roll_before = fixtures.refresh_roll_good(ctx["roll_good"]["id"])
        assert roll_before["shade_band"] == "A", (
            f"the roll must snapshot band A from its lot, got {roll_before['shade_band']}"
        )
        assert roll_before["qa_status"] == "PASSED", (
            f"expected qa_status PASSED before rejection, got {roll_before['qa_status']}"
        )
        assert roll_before["inventory_status"] == "AVAILABLE", (
            f"expected AVAILABLE before rejection, got {roll_before['inventory_status']}"
        )
        assert roll_before["available_yards"] == pytest.approx(100.0, abs=0.01), (
            f"expected 100.0 free yards before rejection, got "
            f"{roll_before['available_yards']}"
        )

        rejected = validate_success(
            api.disposition_dye_lot(
                ctx["dye_lot"]["id"], {"disposition": "REJECT"}, DYER
            ),
            200,
        )
        assert rejected["status"] == "REJECTED", (
            f"expected REJECTED, got {rejected['status']}"
        )

        roll_after = validate_success(
            api.get_roll_good(ctx["roll_good"]["id"], PLANNER), 200
        )
        assert roll_after["qa_status"] == "FAILED", (
            f"the rejection cascade must fail the roll, got {roll_after['qa_status']}"
        )
        assert roll_after["inventory_status"] == "SCRAPPED", (
            f"the rejection cascade must scrap the roll, got "
            f"{roll_after['inventory_status']}"
        )

        validate_error(
            api.create_manual_allocation(
                ctx["cut_order"]["id"],
                factories.manual_allocation_payload(
                    ctx["roll_good"]["id"], 50.0, roll_after["version"]
                ),
                PLANNER,
            ),
            "ERR_DYE_LOT_EXHAUSTED",
        )

        _, meta = validate_paginated(
            api.list_cut_allocations(
                PLANNER,
                params={
                    "cut_order_id": ctx["cut_order"]["id"],
                    "limit": 100,
                    "offset": 0,
                },
            )
        )
        assert meta["total_count"] == 0, (
            f"the refused line must create nothing, got {meta['total_count']} lines"
        )

        order = fixtures.refresh_cut_order(ctx["cut_order"]["id"])
        assert order["status"] == "SUBMITTED", (
            f"the order must stay SUBMITTED, got {order['status']}"
        )
        assert order["allocated_yards"] == pytest.approx(0.0, abs=0.01), (
            f"expected 0 allocated yards, got {order['allocated_yards']}"
        )


class TestSingleLotShadeContinuity:
    """Manual-line shade continuity is compared on the dye lot, not the band."""

    def test_single_lot_refuses_a_second_lot_at_the_same_band(self, api):
        """Under SINGLE_LOT a line off a second lot is refused even though both lots
        band A, while a further line off the first lot is accepted.

        PRD: "under a `shade_tolerance` of `SINGLE_LOT` the roll's `dye_lot_id` must
        equal the `dye_lot_id` of the roll behind the order's earliest-created line
        in status `RESERVED`, `CUT` or `SHIPPED`"

        PRD: "A violation is refused with `ERR_SHADE_BAND_MISMATCH`."

        Design: Corner/validations/single_lot_tolerance_refuses_a_second_lot_even_at_the_same_shade_band
        """
        ctx = _backed_piece_dyed_run(machine_overrides={"changeover_minutes": 0})
        run_id = ctx["run"]["id"]
        lot_one = fixtures.create_dye_lot(
            run_id,
            ctx["vessel"]["id"],
            lot_code="DL-01",
            lot_kg=200.0,
            dyed_yards=200.0,
            dye_start_utc="2026-08-06T08:00:00Z",
            dye_end_utc="2026-08-06T14:00:00Z",
        )
        lot_two = fixtures.create_dye_lot(
            run_id,
            ctx["vessel"]["id"],
            lot_code="DL-02",
            lot_kg=200.0,
            dyed_yards=200.0,
            dye_start_utc="2026-08-06T14:00:00Z",
            dye_end_utc="2026-08-06T20:00:00Z",
        )
        fixtures.set_clock("2026-08-06T14:00:00Z")
        for lot in (lot_one, lot_two):
            dyeing = fixtures.start_dyeing(lot["id"], clock_to=None)
            _measure(api, lot["id"], dyeing["version"], BAND_A_UNROUNDED_READING)
            approved = fixtures.disposition_dye_lot(lot["id"], "APPROVE")
            assert approved["shade_band"] == "A", (
                f"{lot['lot_code']} must land in band A, got {approved['shade_band']}"
            )

        roll_one = fixtures.doff_roll_good(
            run_id, dye_lot_id=lot_one["id"], roll_number="RG-1", initial_yards=100.0
        )
        roll_two = fixtures.doff_roll_good(
            run_id, dye_lot_id=lot_two["id"], roll_number="RG-2", initial_yards=100.0
        )
        fixtures.issue_flammability_certification(ctx["style"]["id"], roll_one["id"])
        roll_one = fixtures.release_roll_good(roll_one["id"])
        roll_two = fixtures.release_roll_good(roll_two["id"])
        account = fixtures.create_account()
        order = fixtures.create_cut_order(
            account["id"],
            ctx["style"]["id"],
            requested_yards=150.0,
            shade_tolerance="SINGLE_LOT",
        )

        first_line = validate_success(
            api.create_manual_allocation(
                order["id"],
                factories.manual_allocation_payload(
                    roll_one["id"], 60.0, roll_one["version"]
                ),
                PLANNER,
            ),
            201,
        )
        assert first_line["shade_band"] == "A", (
            f"the first line must snapshot band A, got {first_line['shade_band']}"
        )
        assert first_line["line_cents"] == 256500, (
            f"expected line_cents 256500 for 60.0 band-A yards, got "
            f"{first_line['line_cents']}"
        )

        validate_error(
            api.create_manual_allocation(
                order["id"],
                factories.manual_allocation_payload(
                    roll_two["id"], 90.0, roll_two["version"]
                ),
                PLANNER,
            ),
            "ERR_SHADE_BAND_MISMATCH",
        )
        roll_two_after = fixtures.refresh_roll_good(roll_two["id"])
        assert roll_two_after["available_yards"] == pytest.approx(100.0, abs=0.01), (
            f"the refused line must not draw yardage, got "
            f"{roll_two_after['available_yards']}"
        )
        assert roll_two_after["inventory_status"] == "AVAILABLE", (
            f"the refused roll stays AVAILABLE, got {roll_two_after['inventory_status']}"
        )

        roll_one_reread = fixtures.refresh_roll_good(roll_one["id"])
        second_line = validate_success(
            api.create_manual_allocation(
                order["id"],
                factories.manual_allocation_payload(
                    roll_one["id"], 40.0, roll_one_reread["version"]
                ),
                PLANNER,
            ),
            201,
        )
        assert second_line["yards"] == pytest.approx(40.0, abs=0.01), (
            f"expected 40.0 yards on the second line, got {second_line['yards']}"
        )
        assert second_line["line_cents"] == 171000, (
            f"expected line_cents 171000 for 40.0 band-A yards, got "
            f"{second_line['line_cents']}"
        )

        order_after = fixtures.refresh_cut_order(order["id"])
        assert order_after["allocated_yards"] == pytest.approx(100.0, abs=0.01), (
            f"expected 100.0 allocated yards, got {order_after['allocated_yards']}"
        )
        roll_one_after = fixtures.refresh_roll_good(roll_one["id"])
        assert roll_one_after["available_yards"] == pytest.approx(0.0, abs=0.01), (
            f"expected the first roll drawn to 0.0, got "
            f"{roll_one_after['available_yards']}"
        )
        assert roll_one_after["inventory_status"] == "COMMITTED", (
            f"a fully reserved passed roll reads COMMITTED, got "
            f"{roll_one_after['inventory_status']}"
        )
        lot_one_after = fixtures.refresh_dye_lot(lot_one["id"])
        lot_two_after = fixtures.refresh_dye_lot(lot_two["id"])
        assert lot_one_after["uncommitted_yards"] == pytest.approx(100.0, abs=0.01), (
            f"expected 100.0 uncommitted yards on DL-01, got "
            f"{lot_one_after['uncommitted_yards']}"
        )
        assert lot_two_after["uncommitted_yards"] == pytest.approx(200.0, abs=0.01), (
            f"expected 200.0 uncommitted yards on DL-02, got "
            f"{lot_two_after['uncommitted_yards']}"
        )


class TestMeasurementStaleVersion:
    """The mandatory version check on a spectrophotometer reading."""

    def test_stale_expected_dye_lot_version_is_refused_and_mutates_nothing(self, api):
        """A reading carrying an outdated version is refused, leaves the lot in
        DYEING with no colour recorded, and the matching version then succeeds.

        PRD: "When the supplied `expected_dye_lot_version` does not equal the lot's
        current `version`, the request is rejected with `ERR_STALE_DYE_LOT_VERSION`
        and HTTP status 412."

        PRD: "On success, the lot's `version` increases by 1, which means a caller
        must re-read before submitting another reading."

        Design: Corner/cross_cutting_complexity_layers/stale_expected_dye_lot_version_is_refused_then_state_takes_over
        """
        polymer_lot = fixtures.create_polymer_lot()
        fiber_batch = fixtures.create_released_fiber_batch(
            polymer_lot["id"], dye_method="PIECE_DYED_READY", solution_color_code=None
        )
        style = fixtures.create_active_piece_dyed_style()
        machine = fixtures.create_tufting_machine(changeover_minutes=0)
        vessel = fixtures.create_dye_vessel()
        run = fixtures.create_scheduled_run(
            style["id"], machine["id"], fiber_batch["id"]
        )
        fixtures.advance_run_to_greige(run["id"])
        lot = fixtures.create_dye_lot(
            run["id"],
            vessel["id"],
            color_code="PD-BEIGE-01",
            lot_kg=1200.0,
            dye_start_utc="2026-08-06T08:00:00Z",
            dye_end_utc="2026-08-06T16:00:00Z",
        )
        dyeing = fixtures.start_dyeing(lot["id"], clock_to=DYE_WINDOW_OPEN_UTC)
        fresh_version = dyeing["version"]

        validate_error(
            api.record_dye_lot_measurement(
                lot["id"],
                factories.measurement_payload(
                    fresh_version - 1,
                    measured_lab_l=40.0,
                    measured_lab_a=12.0,
                    measured_lab_b=-8.0,
                ),
                DYER,
            ),
            "ERR_STALE_DYE_LOT_VERSION",
        )

        after_refusal = fixtures.refresh_dye_lot(lot["id"])
        assert after_refusal["status"] == "DYEING", (
            f"the refused reading must leave the lot DYEING, got "
            f"{after_refusal['status']}"
        )
        assert after_refusal["delta_e"] is None, (
            f"the refused reading must not compute delta_e, got "
            f"{after_refusal['delta_e']}"
        )
        assert after_refusal["shade_band"] is None, (
            f"the refused reading must not band the lot, got "
            f"{after_refusal['shade_band']}"
        )
        assert after_refusal["measured_lab_l"] is None, (
            f"the refused reading must not be persisted, got "
            f"{after_refusal['measured_lab_l']}"
        )
        assert after_refusal["version"] == fresh_version, (
            f"the refused reading must not bump the version: expected "
            f"{fresh_version}, got {after_refusal['version']}"
        )

        measured = _measure(
            api, lot["id"], fresh_version, BAND_A_UNROUNDED_READING
        )
        assert measured["status"] == "MEASURED", (
            f"the matching reading must advance the lot, got {measured['status']}"
        )
        assert measured["delta_e"] == pytest.approx(0.80, abs=0.01), (
            f"expected delta_e 0.80, got {measured['delta_e']}"
        )
        assert measured["shade_band"] == "A", (
            f"expected band A, got {measured['shade_band']}"
        )
        assert measured["version"] == fresh_version + 1, (
            f"a successful reading bumps the version to {fresh_version + 1}, got "
            f"{measured['version']}"
        )
