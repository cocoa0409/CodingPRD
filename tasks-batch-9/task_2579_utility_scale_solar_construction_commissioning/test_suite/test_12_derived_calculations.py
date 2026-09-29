"""Derived arithmetic: commissioning results, availability ledgers, thresholds.

Every figure asserted here is derived from the formulas PRD section 3 pins,
including the rounding order those formulas fix. Each test builds its own state
from scratch through the endpoints of PRD section 4, because the server is
restarted and the database wiped before every individual test.
"""

from test_helpers import (
    assert_cents,
    assert_delivery_receipt,
    assert_pile_disposition,
    assert_ratio,
    factories as f,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.api_errors import (
    ERR_DISTURBED_ACREAGE_EXCEEDED,
    ERR_INSUFFICIENT_ACCEPTED_MODULES,
    ERR_REMEDIATION_STILL_OUT_OF_TOLERANCE,
)
from test_helpers.fixtures import (
    accepted_area,
    accepted_module_delivery,
    append_interval,
    create_block,
    create_grading_area,
    create_payroll_week,
    create_pile,
    create_project,
    create_yard_zone,
    energize_substation,
    mech_complete_block,
    piles_complete_block,
    post_labor_entry,
    receive_delivery,
    reserve_delivery,
    reset_clock,
    run_labor_compliance,
    schedule_commissioning_test,
    wired_circuit,
)


def test_performance_ratio_sums_raw_measurements_and_ignores_the_variant(
    api, commissioning_headers, epc_headers
):
    """A PERFORMANCE_RATIO verdict is one rounding of raw power over raw irradiance.

    PRD 3.7: "`reported_performance_ratio` is the numerator divided by the denominator, rounded half up to four decimal places — one rounding, applied once to the ratio."

    Design: Corner/calculations/performance_ratio_is_computed_from_raw_measurements_and_ignores_the_variant
    """
    reset_clock(api)
    project = create_project(api, name="Ratio Mesa")
    energize_substation(api, project["id"])
    test = schedule_commissioning_test(
        api,
        project["id"],
        test_type="PERFORMANCE_RATIO",
        correction_variant="WEATHER_CORRECTED",
    )
    append_interval(api, test["id"], "2026-08-10T02:35:00Z", 800, 76.00)
    append_interval(api, test["id"], "2026-08-10T02:40:00Z", 900, 85.00)
    append_interval(api, test["id"], "2026-08-10T02:45:00Z", 500, 10.00)

    rows, _meta = validate_paginated(
        api.list_test_intervals(test["id"], commissioning_headers)
    )
    assert [row["is_valid"] for row in rows] == [True, True, False], (
        "the 500 W/m2 sample is below the 600 W/m2 filter and must be invalid"
    )

    finalized = validate_success(
        api.finalize_commissioning_test(
            test["id"], f.finalization_payload(), commissioning_headers
        )
    )
    assert finalized["interval_count"] == 3
    assert finalized["valid_interval_count"] == 2
    # 76.00 + 85.00 = 161.00 over 130 * 0.8 + 130 * 0.9 = 221.00.
    assert_ratio(
        finalized["reported_performance_ratio"], 0.7285, "reported_performance_ratio"
    )
    assert finalized["status"] == "PASSED", "0.7285 clears the guaranteed 0.69"
    assert finalized["reported_kw_ac"] is None
    assert finalized["pass_threshold_kw_ac"] is None
    assert (
        finalized["correction_variant"] == "WEATHER_CORRECTED"
    ), "the declared variant is echoed back although it changed no arithmetic"


def test_module_availability_counts_only_accepted_module_deliveries(
    api, foreman_headers, procurement_headers
):
    """Mechanical completion is ceilinged by accepted MODULE units, less units installed elsewhere.

    PRD 3.4: "If the reported `modules_installed_qty` exceeds the delivered total less the amount already installed elsewhere, the declaration is refused with `ERR_INSUFFICIENT_ACCEPTED_MODULES`."

    Design: Corner/calculations/module_availability_counts_only_accepted_module_deliveries
    """
    project = create_project(api, name="Availability Flat")
    area = accepted_area(api, project["id"])
    zone = create_yard_zone(api, project["id"], pallet_capacity=300)

    accepted = reserve_delivery(
        api,
        project["id"],
        zone["id"],
        component_type="MODULE",
        unit_qty=60,
        pallets=60,
        planned_arrival_at="2026-08-03T09:00:00Z",
    )
    receive_delivery(api, accepted["id"], 60, 3)
    still_reserved = reserve_delivery(
        api,
        project["id"],
        zone["id"],
        component_type="MODULE",
        unit_qty=100,
        pallets=60,
        planned_arrival_at="2026-08-04T09:00:00Z",
    )
    rejected = reserve_delivery(
        api,
        project["id"],
        zone["id"],
        component_type="MODULE",
        unit_qty=60,
        pallets=60,
        planned_arrival_at="2026-08-05T09:00:00Z",
    )
    receive_delivery(api, rejected["id"], 60, 4)
    tracker = reserve_delivery(
        api,
        project["id"],
        zone["id"],
        component_type="TRACKER",
        unit_qty=100,
        pallets=60,
        planned_arrival_at="2026-08-06T09:00:00Z",
    )
    receive_delivery(api, tracker["id"], 100, 0)

    assert_delivery_receipt(
        validate_success(api.get_delivery(accepted["id"], procurement_headers)),
        status="ACCEPTED",
        accepted_unit_qty=57,
        damage_ratio=0.05,
    )
    assert_delivery_receipt(
        validate_success(api.get_delivery(rejected["id"], procurement_headers)),
        status="REJECTED",
        accepted_unit_qty=0,
        damage_ratio=0.0667,
    )
    assert (
        validate_success(api.get_delivery(still_reserved["id"], procurement_headers))[
            "status"
        ]
        == "RESERVED"
    )
    assert (
        validate_success(api.get_delivery(tracker["id"], procurement_headers))["status"]
        == "ACCEPTED"
    )

    first = piles_complete_block(api, project["id"], area["id"], block_code="B1")
    second = piles_complete_block(api, project["id"], area["id"], block_code="B2")

    validate_error(
        api.declare_mechanical_completion(
            first["id"], f.mechanical_completion_payload(58, 18.0), foreman_headers
        ),
        ERR_INSUFFICIENT_ACCEPTED_MODULES,
    )
    completed = validate_success(
        api.declare_mechanical_completion(
            first["id"], f.mechanical_completion_payload(57, 18.0), foreman_headers
        )
    )
    assert completed["mechanical_status"] == "MECH_COMPLETE"
    assert completed["modules_installed_qty"] == 57

    validate_error(
        api.declare_mechanical_completion(
            second["id"], f.mechanical_completion_payload(1, 18.0), foreman_headers
        ),
        ERR_INSUFFICIENT_ACCEPTED_MODULES,
    )
    untouched = validate_success(api.get_block(second["id"], foreman_headers))
    assert untouched["mechanical_status"] == "PILES_COMPLETE"
    assert untouched["modules_installed_qty"] is None


def test_string_test_constants_gate_insulation_before_voltage_and_polarity(
    api, foreman_headers
):
    """Insulation is judged first at an inclusive 40.0, against a 3% band on the corrected voltage.

    PRD 3.5: "First, if `insulation_resistance_mohm` is strictly below 40.0 megaohms, the test fails and `test_failure_reason` is `INSULATION`."

    Design: Corner/calculations/string_test_constants_gate_insulation_before_voltage_and_polarity
    """
    project = create_project(api, name="Insulation Ridge")
    area = accepted_area(api, project["id"])
    zone = create_yard_zone(api, project["id"])
    accepted_module_delivery(api, project["id"], zone["id"])
    block = mech_complete_block(api, project["id"], area["id"])
    circuit = wired_circuit(api, block["id"], modules_in_series=15)
    assert circuit["status"] == "WIRED"

    # 15 * 49.50 * (1 + (-0.0028) * (40 - 25)) = 711.32, so the 3% band is 21.3396 V.
    first = validate_success(
        api.create_string_test_result(
            circuit["id"],
            f.string_test_payload(
                insulation_resistance_mohm=39.9,
                measured_voc_v=705.00,
                ambient_c=40,
                polarity_ok=True,
            ),
            foreman_headers,
        )
    )
    assert_ratio(first["expected_voc_v"], 711.32, "expected_voc_v")
    assert first["test_failure_reason"] == "INSULATION"
    assert first["status"] == "FAILED"

    second = validate_success(
        api.create_string_test_result(
            circuit["id"],
            f.string_test_payload(
                insulation_resistance_mohm=39.9,
                measured_voc_v=680.00,
                ambient_c=40,
                polarity_ok=False,
            ),
            foreman_headers,
        )
    )
    assert second["test_failure_reason"] == "INSULATION", (
        "the 31.32 V deviation and the reversed polarity are both later checks"
    )

    third = validate_success(
        api.create_string_test_result(
            circuit["id"],
            f.string_test_payload(
                insulation_resistance_mohm=40.0,
                measured_voc_v=680.00,
                ambient_c=40,
                polarity_ok=False,
            ),
            foreman_headers,
        )
    )
    assert third["test_failure_reason"] == "VOC_DEVIATION", (
        "insulation at exactly 40.0 passes, so the voltage band answers next"
    )

    fourth = validate_success(
        api.create_string_test_result(
            circuit["id"],
            f.string_test_payload(
                insulation_resistance_mohm=40.0,
                measured_voc_v=705.00,
                ambient_c=40,
                polarity_ok=False,
            ),
            foreman_headers,
        )
    )
    assert fourth["test_failure_reason"] == "POLARITY", (
        "a 6.32 V deviation sits inside the 21.3396 V band"
    )

    fifth = validate_success(
        api.create_string_test_result(
            circuit["id"],
            f.string_test_payload(
                insulation_resistance_mohm=40.0,
                measured_voc_v=705.00,
                ambient_c=40,
                polarity_ok=True,
            ),
            foreman_headers,
        )
    )
    assert fifth["test_failure_reason"] is None
    assert fifth["status"] == "TESTED"

    recovered = validate_success(api.get_block(block["id"], foreman_headers))
    assert recovered["electrical_status"] == "TESTED"
    assert recovered["circuits_failed_count"] == 0


def test_earthwork_ledger_admits_the_limit_and_refuses_one_hundredth_over(
    api, civil_headers
):
    """The two-decimal acreage ledger is compared with a strictly-greater-than gate.

    PRD 3.2: "Fifth and last, the acreage ledger gate: the area's current `disturbed_acreage_current` plus the candidate's `acreage_disturbed_delta`, rounded half up to two decimal places, may not exceed the `disturbed_acreage_limit`; exceeding it is `ERR_DISTURBED_ACREAGE_EXCEEDED`."

    Design: Corner/calculations/earthwork_disturbance_gate_admits_the_limit_and_refuses_one_hundredth_over
    """
    reset_clock(api)
    project = create_project(api, name="Precision Bench")
    area = create_grading_area(
        api, project["id"], disturbed_acreage_limit=20.00
    )

    cleared = validate_success(
        api.create_earthwork_log(
            area["id"],
            f.earthwork_log_payload(
                "CLEARING", "2026-08-01T12:00:00Z", "2026-08-01T20:00:00Z", 12.34
            ),
            civil_headers,
        )
    )
    assert_ratio(cleared["disturbed_acreage_current"], 12.34, "disturbed_acreage_current")
    assert cleared["status"] == "CLEARED"

    graded = validate_success(
        api.create_earthwork_log(
            area["id"],
            f.earthwork_log_payload(
                "GRADING", "2026-08-02T12:00:00Z", "2026-08-02T20:00:00Z", 7.66
            ),
            civil_headers,
        )
    )
    assert_ratio(graded["disturbed_acreage_current"], 20.00, "disturbed_acreage_current")
    assert graded["status"] == "GRADED", "landing exactly on the limit is admitted"

    validate_error(
        api.create_earthwork_log(
            area["id"],
            f.earthwork_log_payload(
                "DRAINAGE", "2026-08-03T12:00:00Z", "2026-08-03T20:00:00Z", 0.01
            ),
            civil_headers,
        ),
        ERR_DISTURBED_ACREAGE_EXCEEDED,
    )

    after = validate_success(api.get_grading_area(area["id"], civil_headers))
    assert_ratio(after["disturbed_acreage_current"], 20.00, "disturbed_acreage_current")
    assert len(after["earthwork_windows"]) == 2, "the refused log appended nothing"
    assert after["status"] == "GRADED"


def test_pile_disposition_thresholds_select_across_all_four_outcomes(
    api, foreman_headers
):
    """Embedment and plumb thresholds pick ACCEPTED, OUT_OF_TOLERANCE, REFUSED and remediation.

    PRD 3.4: "When `refusal` is reported false, no relief applies: the pile becomes `ACCEPTED` only when `actual_embedment_mm` is at least the full `design_embedment_mm` *and* the plumb check passes, and becomes `OUT_OF_TOLERANCE` in every other case."

    Design: Corner/calculations/pile_disposition_thresholds_select_across_all_four_outcomes
    """
    project = create_project(api, name="Disposition Draw")
    area = accepted_area(api, project["id"])
    block = create_block(api, project["id"], area["id"], planned_pile_count=5)

    piles = [
        create_pile(api, block["id"], row_index=1, position_index=index)
        for index in range(1, 6)
    ]

    # No relief: the full 3000 mm design embedment with plumb inside 12.0 mm.
    assert_pile_disposition(
        validate_success(
            api.create_drive_result(
                piles[0]["id"], f.drive_result_payload(3000, 5.0), foreman_headers
            )
        ),
        "ACCEPTED",
    )
    assert_pile_disposition(
        validate_success(
            api.create_drive_result(
                piles[1]["id"], f.drive_result_payload(2999, 5.0), foreman_headers
            )
        ),
        "OUT_OF_TOLERANCE",
    )
    # Refusal relief admits 90% of design, and 2700 is exactly that floor.
    assert_pile_disposition(
        validate_success(
            api.create_drive_result(
                piles[2]["id"],
                f.drive_result_payload(2700, 5.0, refusal=True),
                foreman_headers,
            )
        ),
        "ACCEPTED",
    )
    assert_pile_disposition(
        validate_success(
            api.create_drive_result(
                piles[3]["id"],
                f.drive_result_payload(3000, 12.1, refusal=True),
                foreman_headers,
            )
        ),
        "OUT_OF_TOLERANCE",
    )
    refused = validate_success(
        api.create_drive_result(
            piles[4]["id"],
            f.drive_result_payload(2699, 5.0, refusal=True),
            foreman_headers,
        )
    )
    assert_pile_disposition(refused, "REFUSED")

    validate_error(
        api.create_remediation(
            piles[1]["id"],
            f.remediation_payload("SPLICE", 2650, 5.0),
            foreman_headers,
        ),
        ERR_REMEDIATION_STILL_OUT_OF_TOLERANCE,
    )
    still_out = validate_success(api.get_pile(piles[1]["id"], foreman_headers))
    assert_pile_disposition(still_out, "OUT_OF_TOLERANCE")
    assert still_out["remediated"] is False

    repaired = validate_success(
        api.create_remediation(
            piles[1]["id"],
            f.remediation_payload("SPLICE", 2700, 12.0),
            foreman_headers,
        )
    )
    assert_pile_disposition(repaired, "ACCEPTED")
    assert repaired["remediated"] is True
    assert repaired["remediation_method"] == "SPLICE"

    rolled_up = validate_success(api.get_block(block["id"], foreman_headers))
    assert rolled_up["piles_accepted_count"] == 3
    assert rolled_up["piles_refused_count"] == 1
    assert rolled_up["mechanical_status"] == "HOLD", (
        "a refused pile holds the block regardless of the accepted count"
    )


def test_labor_compliance_run_reconciles_restitution_after_a_void(api, labor_headers):
    """A recomputation reads only live lines, so voiding the deficient line clears the ledger.

    PRD 3.8: "It is `QUALIFIED` when apprenticeship qualification holds *and* `wage_restitution_owed_cents` is exactly 0; in every other case it is `DISQUALIFIED`."

    Design: Corner/calculations/labor_compliance_run_reconciles_restitution_after_a_void
    """
    project = create_project(
        api,
        name="Restitution Valley",
        prevailing_wage_election="REMEDIABLE",
        apprenticeship_basis="PROJECT_AGGREGATE",
        apprenticeship_min_pct=15.00,
    )
    week = create_payroll_week(api, project["id"], week_start_date="2026-08-03")
    apprentice = post_labor_entry(
        api,
        week["id"],
        worker_ref="W-APP",
        is_apprentice=True,
        hours=20.00,
        paid_rate_cents=4200,
        fringe_rate_cents=800,
        prevailing_rate_cents=5000,
    )
    deficient = post_labor_entry(
        api,
        week["id"],
        worker_ref="W-JNY",
        is_apprentice=False,
        hours=80.00,
        paid_rate_cents=4000,
        fringe_rate_cents=500,
        prevailing_rate_cents=5000,
    )

    run_labor_compliance(api, project["id"])
    scored = validate_success(api.get_project(project["id"], labor_headers))
    # 20.00 of 100.00 hours is 20.00 percent, so apprenticeship qualifies.
    assert_ratio(scored["apprentice_hours_pct"], 20.00, "apprentice_hours_pct")
    assert scored["apprenticeship_basis_applied"] == "PROJECT_AGGREGATE"
    # 500 cents short across 80.00 hours is 40000 cents, plus 20 percent damages.
    assert_cents(
        scored["wage_restitution_owed_cents"], 40000, "wage_restitution_owed_cents"
    )
    assert_cents(
        scored["wage_liquidated_damages_cents"], 8000, "wage_liquidated_damages_cents"
    )
    assert scored["tax_credit_status"] == "DISQUALIFIED", (
        "restitution above zero disqualifies even when apprenticeship holds"
    )

    short_line = validate_success(api.get_labor_entry(deficient["id"], labor_headers))
    assert_cents(short_line["shortfall_cents_per_hour"], 500, "shortfall_cents_per_hour")
    assert_cents(short_line["restitution_cents"], 40000, "restitution_cents")
    compliant_line = validate_success(api.get_labor_entry(apprentice["id"], labor_headers))
    assert_cents(compliant_line["shortfall_cents_per_hour"], 0, "shortfall_cents_per_hour")
    assert_cents(compliant_line["restitution_cents"], 0, "restitution_cents")

    voided = validate_success(
        api.void_labor_entry(deficient["id"], f.void_payload(), labor_headers)
    )
    assert voided["status"] == "VOIDED"
    assert_cents(voided["restitution_cents"], 0, "restitution_cents")

    run_labor_compliance(api, project["id"])
    rescored = validate_success(api.get_project(project["id"], labor_headers))
    assert_ratio(rescored["apprentice_hours_pct"], 100.00, "apprentice_hours_pct")
    assert_cents(
        rescored["wage_restitution_owed_cents"], 0, "wage_restitution_owed_cents"
    )
    assert_cents(
        rescored["wage_liquidated_damages_cents"], 0, "wage_liquidated_damages_cents"
    )
    assert rescored["tax_credit_status"] == "QUALIFIED"
