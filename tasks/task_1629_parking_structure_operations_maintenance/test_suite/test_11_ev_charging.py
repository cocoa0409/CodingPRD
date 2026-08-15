"""EV charger lifecycle, charging session gating and fault cascade, and the
dual-basis utilization recompute with its cumulative review flag."""
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    commission_ev_charger,
    create_charging_session_payload,
    create_ev_charger,
    create_facility,
    get_success_data,
    run_close_of_business,
    set_clock,
    validate_error,
    validate_success,
)

FM = TEST_USERS["facility_manager_headers"]
MS = TEST_USERS["maintenance_supervisor_headers"]


def test_charger_out_of_service_return_cycle(api):
    """PRD: "the first commissioning stamps `commissioned_at` (null until that
    moment), and later recommissionings leave that original stamp untouched.
    A `COMMISSIONED` charger may be taken out of service (`COMMISSIONED` to
    `OUT_OF_SERVICE`) and returned (`OUT_OF_SERVICE` back to `COMMISSIONED`)
    as a cyclic pair"

    Design: Corner/state_machines/charger_out_of_service_return_cycle
    """
    facility = create_facility(name="EVC Fac")
    charger = commission_ev_charger(facility["id"], charger_label="EV-02")
    commissioned_at = charger["commissioned_at"]
    assert commissioned_at.startswith("2026-08-01T00:00:00"), (
        "stamped from the logical clock startup default")

    out = validate_success(api.take_ev_charger_out_of_service(charger["id"], MS), 200)
    assert out["charger_status"] == "OUT_OF_SERVICE"
    back = validate_success(api.return_ev_charger_to_service(charger["id"], MS), 200)
    assert back["charger_status"] == "COMMISSIONED"
    assert back["commissioned_at"] == commissioned_at, "first commissioning only"
    out2 = validate_success(api.take_ev_charger_out_of_service(charger["id"], MS), 200)
    assert out2["charger_status"] == "OUT_OF_SERVICE", "cyclic pair re-traversable"


def test_charging_fault_cascades_charger_out_of_service(api):
    """PRD: "Faulting the session, with a free-text `fault_description`, moves
    it to the terminal `FAULTED`, stamps `ended_at`, and cascades the charger
    from `COMMISSIONED` to `OUT_OF_SERVICE` in the same act."

    Design: Corner/state_machines/charging_fault_cascades_charger_out_of_service
    """
    facility = create_facility(name="CF Fac")
    charger = commission_ev_charger(facility["id"], charger_label="EV-03")
    session = get_success_data(api.create_charging_session(
        create_charging_session_payload(charger["id"]), MS))

    faulted = validate_success(api.fault_charging_session(
        session["id"], "ground fault trip", MS), 200)
    assert faulted["session_status"] == "FAULTED"
    charger_after = get_success_data(api.get_ev_charger(charger["id"], FM))
    assert charger_after["charger_status"] == "OUT_OF_SERVICE"


def test_charger_unavailable_while_session_active(api):
    """PRD: "Three conditions gate the start, all reported as
    `ERR_CHARGER_UNAVAILABLE`: the charger must stand `COMMISSIONED`, it must
    have no other session standing `CHARGING`, and a supplied agreement must
    stand `ACTIVE`."

    Design: Corner/validations/charger_unavailable_while_session_active
    """
    facility = create_facility(name="CU Fac")
    busy = commission_ev_charger(facility["id"], charger_label="EV-A")
    get_success_data(api.create_charging_session(
        create_charging_session_payload(busy["id"]), MS))
    proposed = create_ev_charger(facility["id"], charger_label="EV-B")

    res = api.create_charging_session(create_charging_session_payload(busy["id"]), MS)
    validate_error(res, ApiErrorId.ERR_CHARGER_UNAVAILABLE)
    res = api.create_charging_session(create_charging_session_payload(proposed["id"]), MS)
    validate_error(res, ApiErrorId.ERR_CHARGER_UNAVAILABLE)


class TestUtilizationDualBasis:
    """Same completed session yields a time-basis and an energy-basis figure."""

    def _build(self, api):
        facility = create_facility(name="EV Fac")
        charger = get_success_data(api.create_ev_charger(
            {"facility_id": facility["id"], "charger_label": "EV-01", "max_kw": 7}, MS))
        set_clock("2026-08-01T00:00:00Z")
        get_success_data(api.permit_ev_charger(charger["id"], MS))
        get_success_data(api.install_ev_charger(charger["id"], MS))
        get_success_data(api.commission_ev_charger(charger["id"], MS))
        set_clock("2026-08-10T10:00:00Z")
        session = get_success_data(api.create_charging_session(
            create_charging_session_payload(charger["id"]), MS))
        set_clock("2026-08-10T12:00:00Z")
        get_success_data(api.complete_charging_session(
            session["id"], {"kwh_delivered": 7.2}, MS))
        set_clock("2026-08-29T00:00:00Z")
        run_close_of_business(facility["id"])
        return get_success_data(api.get_ev_charger(charger["id"], FM))

    def test_session_time_basis_utilization(self, api):
        """PRD: "The measurement window opens at the later of the charger's
        `commissioned_at` and the business date minus twenty-eight days, and
        closes at the run instant; the whole minutes between them are the
        available minutes."
        PRD: "The session-time basis, `utilization_session_pct`, is one
        hundred times the summed minutes from `started_at` to `ended_at`
        across those eligible sessions, divided by the available minutes,
        rounded half-up to two decimal places."

        Design: Difficulty/dual_variant_calc/ev_utilization_session_vs_energy_basis
        """
        charger = self._build(api)
        assert charger["utilization_session_pct"] == pytest.approx(0.30, abs=1e-9), (
            "120 min over 40320 min window -> 0.30%")

    def test_energy_basis_utilization_differs(self, api):
        """PRD: "The energy basis, `utilization_energy_pct`, is one hundred
        times the summed `kwh_delivered` across the same sessions, divided by
        the energy the nameplate could have delivered — `max_kw` multiplied by
        the available hours (available minutes divided by sixty) — again
        rounded half-up to two decimal places; identical raw data therefore
        yields two different percentages, one measuring occupied time and the
        other delivered energy."

        Design: Difficulty/dual_variant_calc/ev_utilization_session_vs_energy_basis
        """
        charger = self._build(api)
        assert charger["utilization_energy_pct"] == pytest.approx(0.15, abs=1e-9), (
            "7.2 kWh over (7 kW * 672 h) -> 0.15%")
        assert charger["utilization_session_pct"] != charger["utilization_energy_pct"]


def test_utilization_review_flag_after_two_low_runs(api):
    """PRD: "Bookkeeping rides on the session basis: when
    `utilization_session_pct` falls below five percent, the charger's
    `low_util_run_count` — initially zero — grows by one, and any run at or
    above five percent resets that count to zero; once the count reaches two
    consecutive low runs, `utilization_review_flag` — initially false — turns
    true and stays set, marking the charger for decommission review."

    Design: Corner/calculations/utilization_review_flag_after_two_low_runs
    """
    facility = create_facility(name="UR Fac")
    charger = commission_ev_charger(facility["id"], charger_label="EV-04")

    set_clock("2026-08-02T00:00:00Z")
    run_close_of_business(facility["id"])
    after_one = get_success_data(api.get_ev_charger(charger["id"], FM))
    assert after_one["low_util_run_count"] == 1, "no sessions -> 0.0% < 5%"
    assert after_one["utilization_review_flag"] is False

    set_clock("2026-08-03T00:00:00Z")
    run_close_of_business(facility["id"])
    after_two = get_success_data(api.get_ev_charger(charger["id"], FM))
    assert after_two["low_util_run_count"] == 2
    assert after_two["utilization_review_flag"] is True, (
        "second consecutive low run sets the decommission-review flag")
