"""Renewable instruments: serial uniqueness, retirement gates, the
retire/void compensating pair, and clock-driven expiry."""
import pytest

from test_helpers import (
    ApiErrorId, create_approved_record, create_instrument_payload,
    get_instrument, make_collecting_cycle, make_factor, make_instrument,
    make_site, recalc_inventory, retire_instrument, retire_payload, set_clock,
    validate_error, validate_success,
)


def _ca_lab_with_approved_electricity(quantity=100):
    """CA site with grid 0.4 / residual 0.5 factors, a collecting cycle, and
    one APPROVED ELECTRICITY record of `quantity` MWh."""
    site = make_site(name="Alpha", grid_region_code="CA")
    grid = make_factor(
        scope_category="SCOPE2_GRID", region_code="CA", unit="MWh",
        value_tco2e_per_unit=0.4,
    )
    make_factor(
        scope_category="SCOPE2_RESIDUAL_MIX", region_code="CA", unit="MWh",
        value_tco2e_per_unit=0.5,
    )
    cycle = make_collecting_cycle()
    create_approved_record(
        cycle["id"], site["id"], grid["id"], activity_type="ELECTRICITY",
        quantity=quantity, unit="MWh",
        period_start="2026-01-01T00:00:00Z", period_end="2026-02-01T00:00:00Z",
    )
    return site, cycle


def test_duplicate_instrument_serial_returns_409(api, manager_headers):
    """PRD §3.6: "The pair of `registry` and `serial_number` must be unique
    among instruments that have not reached `EXPIRED`; a clash is rejected
    with `ERR_DUPLICATE_INSTRUMENT_SERIAL`."

    Design: Corner/validations/duplicate_instrument_serial_returns_409
    """
    make_instrument(serial_number="S-900")
    duplicate = api.create_instrument(
        create_instrument_payload(serial_number="S-900", technology="WIND",
                                  quantity_mwh=5),
        manager_headers,
    )
    validate_error(duplicate, ApiErrorId.ERR_DUPLICATE_INSTRUMENT_SERIAL, 409)

    different = api.create_instrument(
        create_instrument_payload(serial_number="S-901", technology="WIND",
                                  quantity_mwh=5),
        manager_headers,
    )
    validate_success(different, 201)


def test_instrument_retire_requires_active_site(api, manager_headers):
    """PRD §3.1: "Two workflows refuse to touch a decommissioned site:
    creating an activity record against it and retiring a renewable
    instrument for it both fail with `ERR_SITE_INACTIVE`." PRD §3.6: "and the
    target site must be `ACTIVE` (`ERR_SITE_INACTIVE`)."

    Design: Difficulty/cross_entity_state_dependency/instrument_retire_requires_active_site
    """
    site = make_site(name="OldPlant")
    cycle = make_collecting_cycle()
    validate_success(api.decommission_site(site["id"], manager_headers))
    instrument = make_instrument(serial_number="S-300", technology="HYDRO",
                                 vintage_year=2026, quantity_mwh=10)

    resp = api.retire_instrument(
        instrument["id"], retire_payload(cycle["id"], site["id"]), manager_headers
    )
    validate_error(resp, ApiErrorId.ERR_SITE_INACTIVE, 422)


def test_instrument_retire_rejected_site_stays_procured_and_active_site_ok(api, manager_headers):
    """PRD §3.6: "The preconditions, in gauntlet order: the instrument must
    currently be `PROCURED` (`ERR_INVALID_STATE`); the target cycle must be
    collecting (`ERR_CYCLE_NOT_COLLECTING`); the `vintage_year` must be no
    earlier than three years before the cycle's `reporting_year` and no later
    than the `reporting_year` itself (`ERR_VINTAGE_INELIGIBLE`); and the
    target site must be `ACTIVE` (`ERR_SITE_INACTIVE`)."

    Design: Difficulty/cross_entity_state_dependency/instrument_retire_requires_active_site
    """
    dead_site = make_site(name="OldPlant")
    live_site = make_site(name="NewPlant", grid_region_code="TX")
    cycle = make_collecting_cycle()
    validate_success(api.decommission_site(dead_site["id"], manager_headers))
    instrument = make_instrument(serial_number="S-301", technology="HYDRO",
                                 vintage_year=2026, quantity_mwh=10)

    resp = api.retire_instrument(
        instrument["id"], retire_payload(cycle["id"], dead_site["id"]), manager_headers
    )
    validate_error(resp, ApiErrorId.ERR_SITE_INACTIVE, 422)
    assert get_instrument(instrument["id"])["status"] == "PROCURED", (
        "a rejected retirement leaves the instrument PROCURED"
    )

    ok = validate_success(
        api.retire_instrument(
            instrument["id"], retire_payload(cycle["id"], live_site["id"]),
            manager_headers,
        )
    )
    assert ok["status"] == "RETIRED", "the same instrument retires against an ACTIVE site"
    assert ok["retired_for_site_id"] == live_site["id"]


def test_instrument_second_retire_rejected(api, manager_headers):
    """PRD §3.6: "The preconditions, in gauntlet order: the instrument must
    currently be `PROCURED` (`ERR_INVALID_STATE`)".

    Design: Corner/state_machines/instrument_second_retire_rejected
    """
    site = make_site(name="Alpha")
    cycle = make_collecting_cycle()
    instrument = make_instrument(serial_number="S-500", quantity_mwh=10)
    retire_instrument(instrument["id"], cycle["id"], site["id"])

    second = api.retire_instrument(
        instrument["id"], retire_payload(cycle["id"], site["id"]), manager_headers
    )
    validate_error(second, ApiErrorId.ERR_INVALID_STATE, 409)


def test_instrument_retire_void_conserves_quantity_and_market_total(api, manager_headers):
    """PRD §3.6: "While the formerly linked cycle is still collecting, a
    manager may reverse a retirement: void-retirement moves the instrument
    from `RETIRED` back to `PROCURED`, clears both `retired_for_cycle_id` and
    `retired_for_site_id` to null, fires the compensating three-link cascade
    against that cycle, and advances both versions. ... Retire-then-void is
    the compensating pair that conserves instrument quantity."

    Design: Difficulty/compensating_invariant/instrument_retire_void_conserves_quantity
    """
    site, cycle = _ca_lab_with_approved_electricity(quantity=100)
    # No instruments linked yet: market prices all 100 residual MWh at 0.5.
    assert recalc_inventory(cycle["id"])["scope2_market_tco2e"] == pytest.approx(50.0, abs=0.005)

    instrument = make_instrument(serial_number="S-400", quantity_mwh=30)
    retire_instrument(instrument["id"], cycle["id"], site["id"])
    assert recalc_inventory(cycle["id"])["scope2_market_tco2e"] == pytest.approx(35.0, abs=0.005), (
        "while RETIRED: covered 30 at zero + residual 70 x 0.5"
    )

    voided = validate_success(api.void_retirement(instrument["id"], manager_headers))
    assert voided["status"] == "PROCURED"
    assert voided.get("retired_for_cycle_id") is None
    assert voided.get("retired_for_site_id") is None
    assert voided["quantity_mwh"] == pytest.approx(30, abs=1e-9), (
        "quantity_mwh is conserved through retire-then-void"
    )
    assert recalc_inventory(cycle["id"])["scope2_market_tco2e"] == pytest.approx(50.0, abs=0.005), (
        "after void + recalc the market total is exactly restored"
    )


def test_instrument_void_restores_retireability(api, manager_headers):
    """PRD §3.6: "void-retirement moves the instrument from `RETIRED` back to
    `PROCURED`, clears both `retired_for_cycle_id` and `retired_for_site_id`
    to null, fires the compensating three-link cascade against that cycle,
    and advances both versions. Attempted on anything but a `RETIRED`
    instrument it fails with `ERR_INVALID_STATE`".

    Design: Difficulty/compensating_invariant/instrument_retire_void_conserves_quantity
    """
    site, cycle = _ca_lab_with_approved_electricity(quantity=100)
    instrument = make_instrument(serial_number="S-401", quantity_mwh=30)
    retire_instrument(instrument["id"], cycle["id"], site["id"])
    validate_success(api.void_retirement(instrument["id"], manager_headers))

    # A second void on the now-PROCURED instrument is a state error.
    second_void = api.void_retirement(instrument["id"], manager_headers)
    validate_error(second_void, ApiErrorId.ERR_INVALID_STATE, 409)

    # And the instrument is fully reusable after the void.
    retired_again = validate_success(
        api.retire_instrument(
            instrument["id"], retire_payload(cycle["id"], site["id"]), manager_headers
        )
    )
    assert retired_again["status"] == "RETIRED"
    assert retired_again["retired_for_cycle_id"] == cycle["id"]
    assert retired_again["retired_for_site_id"] == site["id"]


def test_clock_expires_procured_instrument_past_vintage_window(api, manager_headers):
    """PRD §3.6: "Separately, instruments age out: when the logical clock's
    calendar year passes `vintage_year` plus three, a `PROCURED` instrument
    automatically becomes `EXPIRED`, its terminal state, freeing its serial
    pair for reuse." and "the instrument must currently be `PROCURED`
    (`ERR_INVALID_STATE`)".

    Design: Corner/cross_cutting_layers/clock_expires_procured_instrument_past_vintage_window
    """
    site = make_site(name="Alpha")
    cycle = make_collecting_cycle()
    instrument = make_instrument(serial_number="S-OLD", technology="HYDRO",
                                 vintage_year=2022, quantity_mwh=10)

    clock = set_clock("2026-08-02T00:00:00Z")
    assert clock["instruments_expired"] == 1, "2026 is past vintage 2022 + 3"
    assert get_instrument(instrument["id"])["status"] == "EXPIRED"

    resp = api.retire_instrument(
        instrument["id"], retire_payload(cycle["id"], site["id"]), manager_headers
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE, 409)
