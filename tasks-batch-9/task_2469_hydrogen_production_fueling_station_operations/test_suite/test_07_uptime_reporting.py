"""Uptime-report amendment and the conservation of holdback cents on the agreement."""

import pytest
from test_helpers import (
    add_emergency_responders,
    amend_report,
    commission_vessel,
    create_uptime_report,
    finalize_report,
    open_acknowledge_and_clear_event,
    read_agreement,
    read_report,
    set_clock,
    setup_station,
)

PERIOD_START = "2026-07-01T00:00:00Z"
PERIOD_END = "2026-08-01T00:00:00Z"


# ─── Recipe builder ───────────────────────────────────────────────────────


def _finalised_report_with_a_penalty():
    """One July period carrying three cleared overpressure outages, reported and final."""
    scenario = setup_station(
        clock=PERIOD_START,
        agreement_overrides={
            "min_uptime_pct": 99.000,
            "penalty_per_point_cents": 250000,
            "initial_holdback_cents": 500000,
            "uptime_method": "NOZZLE_WEIGHTED",
        },
        station_overrides={
            "nozzle_count": 4,
            "offload_bay_count": 1,
            "storage_capacity_kg": 900.000,
            "reserve_floor_kg": 10.000,
            "max_pressure_class": "H70",
        },
    )
    station_id = scenario["station"]["id"]
    commission_vessel(
        station_id,
        bank_tier="HIGH",
        water_volume_l=600.0,
        mawp_bar=1000.00,
        min_residual_bar=200.00,
        initial_pressure_bar=950.00,
        next_inspection_due_date="2027-06-30",
    )
    add_emergency_responders(station_id, count=2)

    # A partial outage: two of four nozzles for six hours.
    open_acknowledge_and_clear_event(
        station_id,
        "2026-07-10T00:00:00Z",
        "2026-07-10T06:00:00Z",
        kind="OVERPRESSURE",
        severity="MAJOR",
        affected_nozzle_count=2,
        detected_by="SENSOR",
    )
    # Two back-to-back full outages: six hours, then two more.
    open_acknowledge_and_clear_event(
        station_id,
        "2026-07-15T00:00:00Z",
        "2026-07-15T06:00:00Z",
        kind="OVERPRESSURE",
        severity="CRITICAL",
        affected_nozzle_count=4,
        detected_by="SENSOR",
    )
    open_acknowledge_and_clear_event(
        station_id,
        "2026-07-15T06:00:00Z",
        "2026-07-15T08:00:00Z",
        kind="OVERPRESSURE",
        severity="MAJOR",
        affected_nozzle_count=4,
        detected_by="OPERATOR_ROUND",
    )

    set_clock(PERIOD_END)
    draft = create_uptime_report(
        station_id,
        scenario["agreement"]["id"],
        period_start=PERIOD_START,
        period_end=PERIOD_END,
    )
    scenario["draft"] = draft
    scenario["final"] = finalize_report(draft["id"])
    return scenario


# ─── Holdback conservation across an amendment ────────────────────────────


def test_amending_a_final_report_restores_the_superseded_penalty_to_the_holdback():
    """The holdback returns to its initial figure because AMENDED reports stop counting.

    "Finally the agreement's `holdback_balance_cents` is recomputed, which restores
    the superseded penalty because `AMENDED` reports are excluded from the charge,
    and the agreement's `version` is incremented by one."

    Design: Difficulty/compensating_invariant/report_amendment_conserves_holdback_cents_against_the_agreement
    """
    scenario = _finalised_report_with_a_penalty()
    agreement_id = scenario["agreement"]["id"]
    assert scenario["final"]["status"] == "FINAL"
    assert scenario["final"]["penalty_cents"] == 119500, (
        "0.478 shortfall points at 250000 cents per point"
    )
    charged = read_agreement(agreement_id)
    assert charged["holdback_balance_cents"] == 380500

    amend_report(scenario["final"]["id"], PERIOD_START, PERIOD_END)

    superseded = read_report(scenario["final"]["id"])
    assert superseded["status"] == "AMENDED"
    assert superseded["penalty_cents"] == 119500, (
        "the superseded figure is retained for audit"
    )
    agreement = read_agreement(agreement_id)
    assert agreement["holdback_balance_cents"] == 500000
    assert agreement["initial_holdback_cents"] == 500000
    assert (
        agreement["holdback_balance_cents"] - charged["holdback_balance_cents"]
        == superseded["penalty_cents"]
    ), "exactly the superseded penalty came back to the pool"
    assert agreement["version"] > charged["version"]


def test_the_replacement_draft_repeats_the_uptime_and_charges_nothing_yet():
    """The replacement carries the same figures but no penalty until it is finalised.

    "In its place a replacement report is created with `status` of `DRAFT`,
    `amended_from_report_id` pointing at the cited report, and every uptime figure
    recomputed from current safety-event data — which is the point of amending, since
    events cleared after the original finalisation now fall inside the period."  It
    "leaves `penalty_cents` at 0 because nothing is charged against the holdback until
    finalisation", and "The replacement draft must itself be finalised before its own
    penalty is charged."

    Design: Difficulty/compensating_invariant/report_amendment_conserves_holdback_cents_against_the_agreement
    """
    scenario = _finalised_report_with_a_penalty()
    original = scenario["final"]
    assert original["nozzle_count_snapshot"] == 4
    assert original["downtime_nozzle_minutes"] == pytest.approx(2640, abs=0.001), (
        "720 partial nozzle-minutes plus 1440 plus 480 full ones"
    )
    assert original["full_outage_minutes"] == pytest.approx(480, abs=0.001), (
        "the two adjacent full outages merge into a single eight-hour interval"
    )
    assert original["uptime_pct_nozzle_weighted"] == pytest.approx(98.522, abs=0.0005)
    assert original["uptime_pct_station_level"] == pytest.approx(98.925, abs=0.0005)
    assert original["uptime_pct"] == pytest.approx(98.522, abs=0.0005)
    assert original["shortfall_points"] == pytest.approx(0.478, abs=0.0005)

    replacement = amend_report(
        original["id"],
        PERIOD_START,
        PERIOD_END,
        amend_reason="Nozzle count snapshot corrected after audit.",
    )

    assert replacement["status"] == "DRAFT"
    assert replacement["amended_from_report_id"] == original["id"]
    assert replacement["penalty_cents"] == 0
    assert replacement["uptime_pct"] == pytest.approx(98.522, abs=0.0005)
    assert replacement["shortfall_points"] == pytest.approx(0.478, abs=0.0005)
    assert read_report(original["id"])["amend_reason"] == (
        "Nozzle count snapshot corrected after audit."
    )
