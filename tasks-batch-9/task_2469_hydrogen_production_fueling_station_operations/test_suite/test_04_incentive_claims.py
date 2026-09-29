"""Incentive claim netting, the bounded revision loop and submission guard ordering."""

import pytest
from test_helpers import (
    AUDITOR,
    COMPLIANCE,
    STANDARD_BANK,
    api_client,
    arrive_delivery,
    book_tube_trailer_delivery,
    create_claim,
    create_production_lot,
    create_session,
    complete_session,
    fuel_session,
    list_meta,
    offload_delivery,
    read_claim,
    read_lot,
    read_station,
    resubmit_payload,
    revision_note_payload,
    run_settled_fill,
    settle_session,
    setup_canonical_released_lot,
    setup_operational_station,
    submit_claim,
    validate_error,
    validate_success,
    void_session_meter,
    CANONICAL_LOT,
    CANONICAL_LOT_CI_ANNUAL,
)

H35_HEAVY_TRUCK = {
    "vehicle_class": "HEAVY_TRUCK",
    "target_pressure_class": "H35",
    "fill_protocol": "SAE_J2601_TABLE",
    "ambient_temp_c": 0.0,
}
H35_TRANSIT_BUS = {**H35_HEAVY_TRUCK, "vehicle_class": "TRANSIT_BUS"}
H35_LIGHT_DUTY_MILD = {
    "vehicle_class": "LIGHT_DUTY",
    "target_pressure_class": "H35",
    "fill_protocol": "SAE_J2601_TABLE",
    "ambient_temp_c": 20.0,
}

WIDE_BANK = (
    {
        "bank_tier": "HIGH",
        "water_volume_l": 600.0,
        "mawp_bar": 1000.00,
        "min_residual_bar": 200.00,
        "initial_pressure_bar": 950.00,
    },
    {
        "bank_tier": "MEDIUM",
        "water_volume_l": 20000.0,
        "mawp_bar": 1000.00,
        "min_residual_bar": 100.00,
        "initial_pressure_bar": 100.00,
    },
    {
        "bank_tier": "LOW",
        "water_volume_l": 5000.0,
        "mawp_bar": 1000.00,
        "min_residual_bar": 100.00,
        "initial_pressure_bar": 950.00,
    },
)


# ─── Recipe builders ──────────────────────────────────────────────────────


def _deliver_lot(scenario, planned_kg, receiving_tier="MEDIUM"):
    """Book, arrive and offload one tube-trailer load of a freshly released lot."""
    lot_scenario = setup_canonical_released_lot()
    station_id = scenario["station"]["id"]
    delivery = book_tube_trailer_delivery(
        station_id,
        lot_scenario["lot"]["id"],
        scenario["vessels"][receiving_tier]["id"],
        planned_kg=planned_kg,
        window_start="2026-08-02T00:00:00Z",
        window_end="2026-08-02T06:00:00Z",
        departed_at="2026-08-01T12:00:00Z",
        trailer_water_volume_l=2500.0,
        trailer_final_pressure_bar=210.00,
    )
    arrive_delivery(delivery["id"], at_clock="2026-08-02T02:00:00Z")
    scenario["delivery"] = offload_delivery(delivery["id"], station_id)
    scenario["asset"] = lot_scenario["asset"]
    scenario["lot"] = read_lot(lot_scenario["lot"]["id"])
    return scenario


def _station_with_a_mid_tier_fill():
    """One settled 166.700 kg fill against a lot delivered inside the claim period."""
    scenario = setup_operational_station(
        station_overrides={
            "nozzle_count": 4,
            "offload_bay_count": 1,
            "storage_capacity_kg": 2000.000,
            "reserve_floor_kg": 100.000,
            "max_pressure_class": "H70",
        },
        bank=WIDE_BANK,
        responders=2,
        vessel_due_date="2027-06-30",
    )
    _deliver_lot(scenario, 300.000)
    scenario["session"] = run_settled_fill(
        scenario["station"]["id"], 166.000, 165.377, -20.0, 700.00, 438.00, **H35_HEAVY_TRUCK
    )
    return scenario


def _station_with_a_low_tier_fill():
    """One settled 80.489 kg fill, small enough to sit in the lowest fee tier."""
    scenario = setup_operational_station(
        station_overrides={
            "nozzle_count": 4,
            "offload_bay_count": 1,
            "storage_capacity_kg": 900.000,
            "reserve_floor_kg": 100.000,
            "max_pressure_class": "H70",
        },
        bank=STANDARD_BANK,
        responders=2,
        vessel_due_date="2027-06-30",
    )
    _deliver_lot(scenario, 60.000)
    scenario["session"] = run_settled_fill(
        scenario["station"]["id"], 80.000, 79.850, -20.0, 700.00, 438.00, **H35_TRANSIT_BUS
    )
    return scenario


def _claim_in_its_second_revision_round(scenario):
    """Walk a fresh claim through two request-revision / resubmit cycles."""
    claim = create_claim(
        scenario["station"]["id"],
        [scenario["lot"]["id"]],
        program="LCFS",
        period_start="2026-08-01",
        period_end="2026-08-03",
    )
    trail = [claim]
    for note in (
        "Attach the meter calibration certificate.",
        "Calibration certificate is illegible; resend.",
    ):
        trail.append(
            validate_success(
                api_client.request_claim_revision(
                    claim["id"], revision_note_payload(revision_note=note), AUDITOR
                ),
                expected_status=200,
            )
        )
        trail.append(
            validate_success(
                api_client.resubmit_incentive_claim(
                    claim["id"], resubmit_payload([scenario["lot"]["id"]]), COMPLIANCE
                ),
                expected_status=200,
            )
        )
    return claim, trail


def _station_with_no_metered_sessions():
    """A station whose only fills are one PENDING and one VOIDED — no METERED row."""
    scenario = setup_operational_station(
        station_overrides={
            "nozzle_count": 4,
            "offload_bay_count": 1,
            "storage_capacity_kg": 900.000,
            "reserve_floor_kg": 100.000,
            "max_pressure_class": "H70",
        },
        bank=STANDARD_BANK,
        responders=2,
        vessel_due_date="2027-06-30",
    )
    station_id = scenario["station"]["id"]
    _deliver_lot(scenario, 60.000)

    pending = create_session(station_id, planned_kg=20.000, **H35_LIGHT_DUTY_MILD)
    fuel_session(pending["id"], station_id, -30.0)
    scenario["pending_session"] = complete_session(
        pending["id"], station_id, 20.000, 700.00, 438.00
    )

    voided = create_session(station_id, planned_kg=10.000, **H35_LIGHT_DUTY_MILD)
    fuel_session(voided["id"], station_id, -30.0)
    complete_session(voided["id"], station_id, 10.000, 700.00, 438.00)
    settle_session(voided["id"])
    scenario["voided_session"] = void_session_meter(
        voided["id"], void_reason="METER_FAULT"
    )
    return scenario


def _station_with_one_claim_and_one_uncertified_lot():
    """A station holding one submitted claim plus a second, never-certified lot."""
    scenario = setup_operational_station(
        station_overrides={
            "nozzle_count": 4,
            "offload_bay_count": 1,
            "storage_capacity_kg": 900.000,
            "reserve_floor_kg": 100.000,
            "max_pressure_class": "H70",
        },
        bank=STANDARD_BANK,
        responders=2,
        vessel_due_date="2027-06-30",
    )
    _deliver_lot(scenario, 60.000)
    scenario["claim_one"] = create_claim(
        scenario["station"]["id"],
        [scenario["lot"]["id"]],
        program="LCFS",
        period_start="2026-08-01",
        period_end="2026-08-05",
    )
    scenario["uncertified_lot"] = create_production_lot(
        scenario["asset"]["id"],
        **{
            **CANONICAL_LOT,
            "mass_kg": 500.000,
            "energy_consumed_kwh": 26000.0,
            "production_start_at": "2026-07-23T00:00:00Z",
            "production_end_at": "2026-07-24T00:00:00Z",
        },
    )
    return scenario


# ─── The administrative fee tier ──────────────────────────────────────────


def test_admin_fee_tier_is_selected_from_gross_credits_at_the_tier_boundary():
    """Gross credits landing exactly on 1.200 take the mid rate, not the low rate.

    "Second, `admin_fee_rate` is selected from a tier table keyed on **gross**
    credits: a gross of at least 3.600 metric tonnes takes the high rate of 0.030,
    otherwise a gross of at least 1.200 metric tonnes takes the mid rate of 0.020,
    otherwise the low rate of 0.010 applies. The tier is keyed on gross credits and
    never on net credits; keying it on the net figure would be self-referential and
    is forbidden."

    Design: Difficulty/combinatorial_formula/incentive_admin_fee_tier_keyed_on_gross_not_net_mode_c
    """
    scenario = _station_with_a_mid_tier_fill()
    assert scenario["session"]["corrected_kg"] == pytest.approx(166.700, abs=0.001)

    claim = create_claim(
        scenario["station"]["id"],
        [scenario["lot"]["id"]],
        program="LCFS",
        period_start="2026-08-01",
        period_end="2026-08-03",
    )

    assert claim["gross_credits_mt"] == pytest.approx(1.200, abs=0.001)
    assert claim["admin_fee_rate"] == pytest.approx(0.020, abs=0.0001), (
        "a gross of exactly 1.200 mt reaches the mid tier"
    )
    assert claim["admin_fee_mt"] == pytest.approx(0.024, abs=0.001)
    assert claim["net_credits_mt"] == pytest.approx(1.176, abs=0.001)
    assert claim["net_credits_mt"] != pytest.approx(1.188, abs=0.001), (
        "1.188 is what a tier keyed on the netted total would yield"
    )


def test_claim_volume_and_intensity_feed_the_credit_conversion():
    """Volume, energy and pathway intensity are established before any netting.

    "Step one establishes volume: `dispensed_kg` is the sum of `corrected_kg`
    across the station's dispensing sessions whose `billing_status` is `METERED`
    and whose `started_at` date lies within the inclusive claim period, rounded
    half-up to three decimal places; `energy_mj` is `dispensed_kg` multiplied by
    the lower heating value of hydrogen, 120 megajoules per kilogram, rounded
    half-up to three decimal places."

    Design: Difficulty/combinatorial_formula/incentive_admin_fee_tier_keyed_on_gross_not_net_mode_c
    """
    scenario = _station_with_a_mid_tier_fill()

    claim = create_claim(
        scenario["station"]["id"],
        [scenario["lot"]["id"]],
        program="LCFS",
        period_start="2026-08-01",
        period_end="2026-08-03",
    )

    assert claim["dispensed_kg"] == pytest.approx(166.700, abs=0.001)
    assert claim["energy_mj"] == pytest.approx(20004.000, abs=0.001)
    assert claim["pathway_ci_gco2e_per_mj"] == pytest.approx(
        CANONICAL_LOT_CI_ANNUAL, abs=0.01
    )
    assert claim["status"] == "SUBMITTED"
    assert claim["revision_round"] == 0


# ─── The bounded revision loop ────────────────────────────────────────────


def test_a_third_revision_request_denies_the_claim_instead_of_erroring():
    """The revision ceiling is enforced by automatic denial, not by a refusal.

    "When `revision_round` was already exactly two, the claim moves `SUBMITTED →
    DENIED` instead — the bound is enforced by automatic denial rather than by an
    error, so a third revision request succeeds as a request and terminates the
    claim. `DENIED` is terminal and no credits are ever issued against it;
    `revision_round` is left at three in that case."

    Design: Difficulty/non_linear_state_machine/incentive_claim_revision_cycle_auto_denies_on_third_request
    """
    scenario = _station_with_a_low_tier_fill()
    claim, trail = _claim_in_its_second_revision_round(scenario)
    assert [row["revision_round"] for row in trail] == [0, 1, 1, 2, 2]
    assert [row["status"] for row in trail] == [
        "SUBMITTED",
        "REVISION_REQUESTED",
        "SUBMITTED",
        "REVISION_REQUESTED",
        "SUBMITTED",
    ]

    denied = validate_success(
        api_client.request_claim_revision(
            claim["id"],
            revision_note_payload(revision_note="Third strike: certificate still missing."),
            AUDITOR,
        ),
        expected_status=200,
    )

    assert denied["status"] == "DENIED"
    assert denied["revision_round"] == 3


def test_a_denied_claim_keeps_its_netting_and_issues_no_credits():
    """Denial terminates adjudication without disturbing the computed credits.

    "Issuing credits is the last step and is accepted only while the claim's
    `status` is `CERTIFIED` and its `net_credits_mt` is strictly greater than
    zero" — a `DENIED` claim never reaches that step, and the station's
    `credits_issued_total_mt` "is recomputed as the sum of `net_credits_mt` across
    every claim for that station whose `status` is `CREDITS_ISSUED`".

    Design: Difficulty/non_linear_state_machine/incentive_claim_revision_cycle_auto_denies_on_third_request
    """
    scenario = _station_with_a_low_tier_fill()
    claim, _ = _claim_in_its_second_revision_round(scenario)

    validate_success(
        api_client.request_claim_revision(
            claim["id"],
            revision_note_payload(revision_note="Third strike: certificate still missing."),
            AUDITOR,
        ),
        expected_status=200,
    )

    denied = read_claim(claim["id"])
    assert denied["net_credits_mt"] == pytest.approx(0.573, abs=0.001)
    assert denied["certified_by_user_id"] is None
    assert read_station(scenario["station"]["id"])[
        "credits_issued_total_mt"
    ] == pytest.approx(0.000, abs=0.001)


# ─── Guard ordering at submission ─────────────────────────────────────────


def test_uncertified_lot_is_reported_before_the_overlapping_claim_period():
    """The certified-intensity guard is evaluated ahead of the period-overlap guard.

    "Three domain rules guard submission, evaluated in this order. Every lot named
    in `production_lot_ids` must have `ci_status` of `CERTIFIED`, or the claim is
    refused with `ERR_LOT_CI_NOT_CERTIFIED` — an uncertified lot has no carbon
    intensity to weight."

    Design: Difficulty/priority_pair_validation_conflict/uncertified_lot_referential_error_outranks_claim_period_overlap_temporal_error
    """
    scenario = _station_with_one_claim_and_one_uncertified_lot()
    assert scenario["claim_one"]["status"] == "SUBMITTED"
    assert scenario["uncertified_lot"]["ci_status"] == "PENDING"

    response = submit_claim(
        scenario["station"]["id"],
        [scenario["uncertified_lot"]["id"]],
        program="LCFS",
        period_start="2026-08-03",
        period_end="2026-08-07",
    )

    error_data = validate_error(
        response, "ERR_LOT_CI_NOT_CERTIFIED", expected_status=422
    )
    assert error_data["error_id"] != "ERR_CLAIM_PERIOD_OVERLAP", (
        "the temporal conflict must not pre-empt the referential one"
    )


def test_the_refused_second_claim_leaves_the_first_claim_untouched():
    """A refused submission writes nothing, so only the original claim survives.

    "Finally, no other claim for the same `station_id` and the same `program`
    whose `status` is anything other than `DENIED` may have an inclusive date range
    from `period_start` to `period_end` that intersects the requested range, or the
    claim is refused with `ERR_CLAIM_PERIOD_OVERLAP` (HTTP 409)."  That later
    conflict is real, yet the uncertified lot is reported first and no row is
    created either way.

    Design: Difficulty/priority_pair_validation_conflict/uncertified_lot_referential_error_outranks_claim_period_overlap_temporal_error
    """
    scenario = _station_with_one_claim_and_one_uncertified_lot()

    validate_error(
        submit_claim(
            scenario["station"]["id"],
            [scenario["uncertified_lot"]["id"]],
            program="LCFS",
            period_start="2026-08-03",
            period_end="2026-08-07",
        ),
        "ERR_LOT_CI_NOT_CERTIFIED",
        expected_status=422,
    )

    listing = api_client.list_station_incentive_claims(
        scenario["station"]["id"], COMPLIANCE, params={"limit": 100, "offset": 0}
    )
    assert list_meta(listing)["total_count"] == 1, "the refused claim created no row"
    survivor = read_claim(scenario["claim_one"]["id"])
    assert survivor["status"] == "SUBMITTED"
    assert survivor["revision_round"] == 0


# ─── An empty metered set ─────────────────────────────────────────────────


def test_a_claim_over_no_metered_sessions_nets_zero_credits():
    """A claim period containing no `METERED` fill yields a zero-volume claim.

    "Step one establishes volume: `dispensed_kg` is the sum of `corrected_kg`
    across the station's dispensing sessions whose `billing_status` is `METERED`
    and whose `started_at` date lies within the inclusive claim period, rounded
    half-up to three decimal places; `energy_mj` is `dispensed_kg` multiplied by
    the lower heating value of hydrogen, 120 megajoules per kilogram, rounded
    half-up to three decimal places."  The station's only fills are `PENDING` and
    `VOIDED`, so the sum is empty.

    Design: Difficulty/boundary_precision_check/incentive_claim_with_empty_metered_session_set_yields_zero_credits
    """
    scenario = _station_with_no_metered_sessions()
    assert scenario["pending_session"]["billing_status"] == "PENDING"
    assert scenario["voided_session"]["billing_status"] == "VOIDED"

    response = submit_claim(
        scenario["station"]["id"],
        [scenario["lot"]["id"]],
        program="LCFS",
        period_start="2026-08-01",
        period_end="2026-08-03",
    )

    claim = validate_success(response, expected_status=201)
    assert claim["dispensed_kg"] == pytest.approx(0.000, abs=0.001)
    assert claim["energy_mj"] == pytest.approx(0.000, abs=0.001)
    assert claim["pathway_ci_gco2e_per_mj"] == pytest.approx(
        CANONICAL_LOT_CI_ANNUAL, abs=0.01
    ), "the declared lot still carries a certified intensity"
    assert claim["gross_credits_mt"] == pytest.approx(0.000, abs=0.001)
    assert claim["status"] == "SUBMITTED"


def test_zero_gross_credits_still_take_the_lowest_fee_tier():
    """A zero gross does not reach either upper tier, so the low rate applies.

    "The tier is keyed on gross credits and never on net credits; keying it on the
    net figure would be self-referential and is forbidden."  A gross of 0.000 mt
    reaches neither 3.600 nor 1.200, so the low rate of 0.010 applies and the fee
    is itself 0.000.  "When the input set is empty, `metered_kg_mtd`,
    `corrected_kg_mtd` and `metering_error_pct_mtd` are all 0.000 and the flag is
    `WITHIN_TOLERANCE`."

    Design: Difficulty/boundary_precision_check/incentive_claim_with_empty_metered_session_set_yields_zero_credits
    """
    scenario = _station_with_no_metered_sessions()

    claim = create_claim(
        scenario["station"]["id"],
        [scenario["lot"]["id"]],
        program="LCFS",
        period_start="2026-08-01",
        period_end="2026-08-03",
    )

    assert claim["admin_fee_rate"] == pytest.approx(0.010, abs=0.0001)
    assert claim["admin_fee_mt"] == pytest.approx(0.000, abs=0.001)
    assert claim["net_credits_mt"] == pytest.approx(0.000, abs=0.001)
    station = read_station(scenario["station"]["id"])
    assert station["metered_kg_mtd"] == pytest.approx(0.000, abs=0.001)
    assert station["corrected_kg_mtd"] == pytest.approx(0.000, abs=0.001)
    assert station["metering_accuracy_flag"] == "WITHIN_TOLERANCE"
    assert station["onsite_inventory_kg"] == pytest.approx(209.600, abs=0.001)
    assert station["credits_issued_total_mt"] == pytest.approx(0.000, abs=0.001)
