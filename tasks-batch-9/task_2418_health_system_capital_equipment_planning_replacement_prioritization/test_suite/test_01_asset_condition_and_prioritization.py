"""Asset condition scoring, the two remaining-useful-life thresholds and prioritization.

Every test builds its own estate from scratch: the server is restarted before
each test, so nothing is carried over between them.
"""

from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    add_service_event,
    assert_asset,
    assert_cents,
    assert_decimal,
    assert_instant,
    assert_priority_score,
    assert_request,
    close_intake,
    latest_score,
    make_asset,
    make_clinical_requester_headers,
    make_cycle,
    make_department,
    make_facility,
    make_request,
    open_intake,
    pin_clock,
    refresh_asset,
    refresh_cycle,
    refresh_request,
    run_scoring,
    score_rows,
    screen,
    submit,
    validate_error,
    validate_success,
)

CLOCK = "2026-08-01T00:00:00Z"
_PLANNER = TEST_USERS["planner_headers"]


# ─── Setup builders ───────────────────────────────────────────────────


def _ct_estate():
    """Facility NRH with its CT department and the CT-16 scanner carrying two outages."""
    pin_clock(CLOCK)
    facility = make_facility(
        name="North Regional Hospital", code="NRH", region="NORTH",
        max_concurrent_construction=1,
    )
    department = make_department(
        facility["id"], name="Diagnostic Imaging CT", modality_scope="CT"
    )
    asset = make_asset(
        facility["id"], department["id"],
        modality="CT", model_name="Aquilon CT-16", install_date="2020-08-02T00:00:00Z",
        expected_life_years=10, acquisition_cost_cents=240000000,
        oem_support_end_date="2029-01-01T00:00:00Z",
    )
    add_service_event(asset["id"], "2026-05-01T00:00:00Z", "CORRECTIVE",
                      downtime_hours=4.00, cost_cents=500000)
    add_service_event(asset["id"], "2026-06-01T00:00:00Z", "CORRECTIVE",
                      downtime_hours=4.00, cost_cents=500000)
    return facility, department, refresh_asset(asset["id"])


def _mri_estate_scored_cycle():
    """SMC's MRI suite, its 1.5T magnet and a 2027 cycle whose intake has closed."""
    pin_clock(CLOCK)
    facility = make_facility(
        name="South Metro Center", code="SMC", region="SOUTH", max_concurrent_construction=2
    )
    department = make_department(
        facility["id"], name="Advanced MRI Suite", modality_scope="MRI"
    )
    asset = make_asset(
        facility["id"], department["id"],
        modality="MRI", model_name="Helion MR-1.5T", install_date="2020-08-02T00:00:00Z",
        expected_life_years=10, acquisition_cost_cents=300000000,
        oem_support_end_date="2026-12-01T00:00:00Z",
    )
    for event_date in ("2026-02-01T00:00:00Z", "2026-03-01T00:00:00Z",
                      "2026-04-01T00:00:00Z", "2026-05-01T00:00:00Z"):
        add_service_event(asset["id"], event_date, "CORRECTIVE", downtime_hours=0.00)
    cycle = make_cycle(
        plan_year=2027, plan_year_start="2027-01-01T00:00:00Z",
        total_capital_cents=500000000, contingency_pct=0.10, facility_contingency_pct=0.05,
    )
    cycle = open_intake(cycle["id"])
    request = make_request(
        cycle["id"], department["id"], asset["id"],
        clinical_justification=(
            "1.5T magnet loses OEM support in 2026; replacement is required to keep "
            "the MRI suite compliant."
        ),
        current_annual_volume=20000, projected_annual_volume=21999,
        estimated_capital_cents=150000000, annual_service_contract_cents=9000001,
        disposable_unit_cents=100, facility_modification_cents=40000000,
        regulatory_mandate_flag=True, mandate_deadline="2027-06-30T00:00:00Z",
    )
    submit(request["id"], department["id"])
    screen(request["id"], "ACCEPT")
    close_intake(cycle["id"])
    return facility, department, asset, cycle, request


def _two_ct_scanners_at_the_eligibility_bar():
    """Two CT-16 units whose only difference is a hundredth of an hour of downtime."""
    facility, department, asset_a1 = _ct_estate()
    asset_a2 = make_asset(
        facility["id"], department["id"],
        modality="CT", model_name="Aquilon CT-16B", install_date="2020-08-02T00:00:00Z",
        expected_life_years=10, acquisition_cost_cents=240000000,
        oem_support_end_date="2029-01-01T00:00:00Z",
    )
    add_service_event(asset_a2["id"], "2026-05-01T00:00:00Z", "CORRECTIVE", downtime_hours=3.99)
    add_service_event(asset_a2["id"], "2026-06-01T00:00:00Z", "CORRECTIVE", downtime_hours=3.99)
    cycle = make_cycle(
        plan_year=2027, plan_year_start="2027-01-01T00:00:00Z",
        total_capital_cents=500000000, contingency_pct=0.10, facility_contingency_pct=0.05,
    )
    cycle = open_intake(cycle["id"])
    request_1 = make_request(
        cycle["id"], department["id"], asset_a1["id"],
        clinical_justification=(
            "CT-16 scanner at end of service life; replacement restores stroke "
            "protocol throughput."
        ),
        current_annual_volume=1200, projected_annual_volume=1801,
        estimated_capital_cents=250000001, annual_service_contract_cents=12345678,
        disposable_unit_cents=1230, facility_modification_cents=60000000,
        regulatory_mandate_flag=True, mandate_deadline="2027-06-30T00:00:00Z",
    )
    request_2 = make_request(
        cycle["id"], department["id"], asset_a2["id"],
        clinical_justification="Second CT-16 unit proposed for replacement in the same plan year.",
        current_annual_volume=1000, projected_annual_volume=1500,
        estimated_capital_cents=100000000, annual_service_contract_cents=10000000,
        disposable_unit_cents=500,
    )
    return department, refresh_asset(asset_a1["id"]), refresh_asset(asset_a2["id"]), \
        request_1, request_2


def _scored_request_on_a_degrading_scanner():
    """A SCORED request whose asset already carries two corrective outages."""
    facility, department, asset = _ct_estate()
    cycle = make_cycle(
        plan_year=2027, plan_year_start="2027-01-01T00:00:00Z",
        total_capital_cents=500000000, contingency_pct=0.10, facility_contingency_pct=0.05,
    )
    cycle = open_intake(cycle["id"])
    request = make_request(
        cycle["id"], department["id"], asset["id"],
        clinical_justification=(
            "CT scanner reliability is degrading; replacement doubles projected volume."
        ),
        current_annual_volume=1000, projected_annual_volume=2000,
        estimated_capital_cents=100000000, annual_service_contract_cents=1000000,
        disposable_unit_cents=100,
    )
    submit(request["id"], department["id"])
    screen(request["id"], "ACCEPT")
    close_intake(cycle["id"])
    cycle = run_scoring(cycle["id"])
    return department, asset, cycle, refresh_request(request["id"])


def _two_scanners_astride_the_expedite_bar():
    """Two CT-18 units whose planned-maintenance downtime differs by two hundredths."""
    pin_clock(CLOCK)
    facility = make_facility(
        name="North Regional Hospital", code="NRH", region="NORTH",
        max_concurrent_construction=1,
    )
    department = make_department(
        facility["id"], name="Diagnostic Imaging CT", modality_scope="CT"
    )
    asset_a3 = make_asset(
        facility["id"], department["id"],
        modality="CT", model_name="Aquilon CT-18", install_date="2020-08-02T00:00:00Z",
        expected_life_years=10, acquisition_cost_cents=200000000,
        oem_support_end_date="2026-12-01T00:00:00Z",
    )
    add_service_event(asset_a3["id"], "2026-05-01T00:00:00Z", "PM", downtime_hours=16.34)
    asset_a4 = make_asset(
        facility["id"], department["id"],
        modality="CT", model_name="Aquilon CT-18B", install_date="2020-08-02T00:00:00Z",
        expected_life_years=10, acquisition_cost_cents=200000000,
        oem_support_end_date="2026-12-01T00:00:00Z",
    )
    add_service_event(asset_a4["id"], "2026-05-01T00:00:00Z", "PM", downtime_hours=16.32)
    cycle = make_cycle(
        plan_year=2028, plan_year_start="2028-01-01T00:00:00Z",
        total_capital_cents=500000000, contingency_pct=0.00, facility_contingency_pct=0.00,
    )
    cycle = open_intake(cycle["id"])
    requests = []
    for asset in (asset_a3, asset_a4):
        request = make_request(
            cycle["id"], department["id"], asset["id"],
            clinical_justification=(
                "CT-18 unit is out of manufacturer support and must be replaced this plan year."
            ),
            current_annual_volume=1000, projected_annual_volume=1500,
            estimated_capital_cents=100000000, annual_service_contract_cents=10000000,
            disposable_unit_cents=500, regulatory_mandate_flag=True,
            mandate_deadline="2028-06-30T00:00:00Z",
        )
        submit(request["id"], department["id"])
        screen(request["id"], "ACCEPT")
        requests.append(request)
    close_intake(cycle["id"])
    return (refresh_asset(asset_a3["id"]), refresh_asset(asset_a4["id"]), cycle,
            requests[0], requests[1])


# ─── The two remaining-useful-life variants ───────────────────────────


def test_asset_nominal_ruls_ignores_the_service_history_the_adjusted_score_reads(api):
    """PRD §3.2: "Third, the **nominal** score, stored as `nominal_ruls_score`, is that
    fraction multiplied by one hundred, rounded half up to two decimals and then clamped
    into the range 0.00 through 100.00; the nominal variant reads nothing but
    `install_date` and `expected_life_years`, and it is never consulted for eligibility,
    for derating or for the safety driver."
    PRD §3.2: "`adjusted_ruls_score` is the nominal score with the service penalty, the
    end-of-support penalty and the recall penalty **subtracted** from it, the result
    rounded half up to two decimals and clamped into the range 0.00 through 100.00."

    Design: Difficulty/dual_variant_calc/asset_nominal_vs_adjusted_ruls_diverge_on_same_asset
    """
    _facility, _department, asset = _ct_estate()

    data = validate_success(api.get_asset(asset["id"], _PLANNER))
    assert_asset(data)
    assert_decimal(data["nominal_ruls_score"], 40.00, "nominal_ruls_score")
    assert_decimal(data["service_penalty_points"], 10.00, "service_penalty_points")
    assert_decimal(data["adjusted_ruls_score"], 30.00, "adjusted_ruls_score")
    divergence = float(data["nominal_ruls_score"]) - float(data["adjusted_ruls_score"])
    assert abs(divergence - 10.00) < 0.005, (
        f"the two variants must diverge by the service penalty, got {divergence}"
    )


def test_asset_trailing_window_aggregates_leave_the_scanner_in_service(api):
    """PRD §3.2: "Over the closed trailing window of seven hundred thirty days — two
    years — ending at `ruls_as_of`, the server counts every service event whose
    `category` is `CORRECTIVE` into `corrective_count_24m`, and sums the
    `downtime_hours` of events of **every** category into `downtime_hours_24m`."
    PRD §3.2: "The **derate gate** sets the asset's `status` to `DERATED` when
    `adjusted_ruls_score` is at most 15.00 or when `unresolved_recall` is true, and to
    `IN_SERVICE` otherwise."

    Design: Difficulty/dual_variant_calc/asset_nominal_vs_adjusted_ruls_diverge_on_same_asset
    """
    _facility, _department, asset = _ct_estate()

    data = validate_success(api.get_asset(asset["id"], _PLANNER))
    assert data["corrective_count_24m"] == 2, "both corrective outages sit in the window"
    assert_decimal(data["downtime_hours_24m"], 8.00, "downtime_hours_24m")
    assert data["unresolved_recall"] is False, "the asset carries no recall event"
    assert data["status"] == "IN_SERVICE", "an adjusted score above 15.00 stays in service"
    assert_instant(data["ruls_as_of"], CLOCK, "ruls_as_of")


# ─── The eligibility gate at exactly 30.00 ────────────────────────────


def test_submit_admits_an_asset_at_exactly_thirty_adjusted_ruls(api):
    """PRD §3.2: "The boundary is inclusive on the eligible side: an adjusted score of
    exactly 30.00 is eligible, and 30.01 is not."
    PRD §3.4: "Each of the five years is rounded to whole cents **before** the
    summation, and `budgetary_operating_5y_cents` is the sum over the five years of that
    year's service cost plus that year's disposables cost."

    Design: Difficulty/boundary_precision_check/ruls_eligibility_at_exactly_thirty_on_submit
    """
    department, asset_a1, _asset_a2, request_1, _request_2 = \
        _two_ct_scanners_at_the_eligibility_bar()

    assert_decimal(asset_a1["downtime_hours_24m"], 8.00, "downtime_hours_24m")
    assert_decimal(asset_a1["service_penalty_points"], 10.00, "service_penalty_points")
    assert_decimal(asset_a1["nominal_ruls_score"], 40.00, "nominal_ruls_score")
    assert_decimal(asset_a1["adjusted_ruls_score"], 30.00, "adjusted_ruls_score")
    assert asset_a1["status"] == "IN_SERVICE"

    data = validate_success(
        api.submit_request(request_1["id"], make_clinical_requester_headers(department["id"]))
    )
    assert_request(data)
    assert data["status"] == "SUBMITTED"
    assert_cents(data["budgetary_operating_5y_cents"], 78961530, "budgetary_operating_5y_cents")
    assert_cents(data["budgetary_tco_cents"], 388961531, "budgetary_tco_cents")
    assert_cents(data["baseline_year1_opex_cents"], 14228624, "baseline_year1_opex_cents")


def test_submit_refuses_an_asset_one_hundredth_above_the_eligibility_bar(api):
    """PRD §3.2: "An asset whose adjusted score is above 30.00 while its status is not
    `DERATED` and it carries no unresolved recall fails the gate, and the submission is
    rejected with `ERR_ASSET_NOT_REPLACEMENT_ELIGIBLE`."
    PRD §3.2: "The boundary is inclusive on the eligible side: an adjusted score of
    exactly 30.00 is eligible, and 30.01 is not."

    Design: Difficulty/boundary_precision_check/ruls_eligibility_at_exactly_thirty_on_submit
    """
    department, _asset_a1, asset_a2, request_1, request_2 = \
        _two_ct_scanners_at_the_eligibility_bar()

    validate_success(
        api.submit_request(request_1["id"], make_clinical_requester_headers(department["id"]))
    )
    assert_decimal(asset_a2["downtime_hours_24m"], 7.98, "downtime_hours_24m")
    assert_decimal(asset_a2["service_penalty_points"], 9.99, "service_penalty_points")
    assert_decimal(asset_a2["adjusted_ruls_score"], 30.01, "adjusted_ruls_score")
    assert asset_a2["status"] == "IN_SERVICE"

    response = api.submit_request(
        request_2["id"], make_clinical_requester_headers(department["id"])
    )
    validate_error(response, ApiErrorId.ERR_ASSET_NOT_REPLACEMENT_ELIGIBLE.value, 422)

    after = refresh_request(request_2["id"])
    assert after["status"] == "DRAFT", "the rejected submission writes no transition"
    assert_cents(after["budgetary_tco_cents"], 0, "budgetary_tco_cents")
    assert after["revision_count"] == 0


# ─── Service history cascading into the derate gate and the score ─────


def test_service_event_deepens_the_penalty_and_derates_the_scanner(api):
    """PRD §3.2: "From those, `service_penalty_points` is three points for each
    corrective event plus half a point for each downtime hour, rounded half up to two
    decimals, and then capped at 40.00; the cap applies to this penalty term alone and
    never to the sum of all penalties."
    PRD §3.2: "The **derate gate** sets the asset's `status` to `DERATED` when
    `adjusted_ruls_score` is at most 15.00 or when `unresolved_recall` is true, and to
    `IN_SERVICE` otherwise."

    Design: Difficulty/transitive_cascade/service_event_cascades_asset_derate_and_request_rescore
    """
    _department, asset, _cycle, _request = _scored_request_on_a_degrading_scanner()

    add_service_event(
        asset["id"], "2026-05-02T00:00:00Z", "CORRECTIVE",
        downtime_hours=40.00, cost_cents=2500000,
        notes="Gantry drive failure; extended outage.",
    )

    data = validate_success(api.get_asset(asset["id"], _PLANNER))
    assert data["corrective_count_24m"] == 3
    assert_decimal(data["downtime_hours_24m"], 48.00, "downtime_hours_24m")
    assert_decimal(data["service_penalty_points"], 33.00, "service_penalty_points")
    assert_decimal(data["adjusted_ruls_score"], 7.00, "adjusted_ruls_score")
    assert_decimal(data["nominal_ruls_score"], 40.00, "nominal_ruls_score")
    assert data["status"] == "DERATED"


def test_derate_gate_rescores_the_scored_request_with_its_own_reason(api):
    """PRD §3.2: "Every replacement request of that asset that is currently `SCORED` is
    re-scored, receiving a new score row whose `reason` is `ASSET_CONDITION_CHANGE`, and
    the request's own `composite_score` and `expedited` are refreshed from it, with the
    request's `version` incremented."
    PRD §3.5: "The **safety driver** is one hundred less the asset's
    `adjusted_ruls_score`, multiplied by seventy-five hundredths, plus four points for
    every corrective service event in the asset's trailing two-year window, the sum
    rounded half up to two decimals and then capped at 100.00."

    Design: Difficulty/transitive_cascade/service_event_cascades_asset_derate_and_request_rescore
    """
    _department, asset, cycle, request = _scored_request_on_a_degrading_scanner()

    add_service_event(
        asset["id"], "2026-05-02T00:00:00Z", "CORRECTIVE",
        downtime_hours=40.00, cost_cents=2500000,
        notes="Gantry drive failure; extended outage.",
    )

    after = refresh_request(request["id"])
    assert_decimal(after["safety_driver"], 81.75, "safety_driver")
    assert_decimal(after["composite_score"], 48.61, "composite_score")
    assert after["status"] == "SCORED", "a re-score keeps the request in SCORED"

    rows = score_rows(request["id"])
    assert len(rows) == 2, f"expected two score rows, found {len(rows)}"
    by_sequence = {row["sequence"]: row for row in rows}
    second = by_sequence[2]
    assert_priority_score(second)
    assert second["reason"] == "ASSET_CONDITION_CHANGE"
    assert_decimal(second["asset_adjusted_ruls_snapshot"], 7.00, "asset_adjusted_ruls_snapshot")
    assert second["corrective_count_snapshot"] == 3
    assert_decimal(second["composite_score"], 48.61, "row composite_score")
    assert second["expedited"] is False
    first = by_sequence[1]
    assert first["reason"] == "CYCLE_SCORING", "history is never rewritten in place"
    assert_decimal(first["asset_adjusted_ruls_snapshot"], 30.00, "asset_adjusted_ruls_snapshot")
    assert_decimal(first["composite_score"], 41.18, "row composite_score")

    cycle_after = refresh_cycle(cycle["id"])
    assert cycle_after["expedited_count"] == 0
    assert cycle_after["scored_count"] == 1


# ─── The composite score across four interacting drivers ──────────────


def test_composite_score_pairs_a_minimum_tier_growth_with_two_full_drivers(api):
    """PRD §3.5: "That rounding happens **before** the tier lookup, so a raw ratio of
    9.995 percent becomes 10.00 and crosses into the next tier."
    PRD §3.5: "The weighted sum applies thirty-five hundredths to the safety driver,
    twenty hundredths to the growth driver, twenty-five hundredths to the regulatory
    driver and twenty hundredths to the end-of-support driver."

    Design: Difficulty/combinatorial_formula/composite_score_nonlinear_min_tier_and_penalty_interaction
    """
    _facility, _department, _asset, cycle, request = _mri_estate_scored_cycle()

    validate_success(api.score_cycle(cycle["id"], _PLANNER))

    after = refresh_request(request["id"])
    assert after["status"] == "SCORED"
    assert_decimal(after["safety_driver"], 76.00, "safety_driver")
    assert_decimal(after["growth_driver"], 50.00, "growth_driver")
    assert_decimal(after["regulatory_driver"], 100.00, "regulatory_driver")
    assert_decimal(after["eos_driver"], 100.00, "eos_driver")
    assert_decimal(after["composite_score"], 81.60, "composite_score")
    assert after["expedited"] is False, "81.60 sits below the inclusive 85.00 bar"


def test_scoring_run_pins_one_score_row_and_refreshes_the_cycle_counts(api):
    """PRD §3.5: "A score row carries the `request_id` it belongs to, a one-based
    `sequence` equal to one more than the highest sequence already recorded for that
    request, a `reason` of `CYCLE_SCORING`, `ASSET_CONDITION_CHANGE` or
    `DEPARTMENT_PENALTY_CHANGE`, the pinned `asset_adjusted_ruls_snapshot` and
    `corrective_count_snapshot` taken from the asset at scoring time, the four values
    `safety_driver`, `growth_driver`, `regulatory_driver` and `eos_driver`, the
    `department_penalty_points` subtracted in that row, that row's own
    `composite_score`, and that row's own `expedited`."
    PRD §3.3: "A scoring run requires `SCORING` and leaves the cycle in `SCORING` — the
    self-transition `SCORING → SCORING` — so it may be repeated."

    Design: Difficulty/combinatorial_formula/composite_score_nonlinear_min_tier_and_penalty_interaction
    """
    _facility, _department, _asset, cycle, request = _mri_estate_scored_cycle()

    validate_success(api.score_cycle(cycle["id"], _PLANNER))

    rows = score_rows(request["id"])
    assert len(rows) == 1, f"one scoring run appends exactly one row, found {len(rows)}"
    row = rows[0]
    assert_priority_score(row)
    assert row["sequence"] == 1
    assert row["reason"] == "CYCLE_SCORING"
    assert_decimal(row["asset_adjusted_ruls_snapshot"], 20.00, "asset_adjusted_ruls_snapshot")
    assert row["corrective_count_snapshot"] == 4
    assert row["department_penalty_points"] == 0
    assert_decimal(row["composite_score"], 81.60, "row composite_score")

    cycle_after = refresh_cycle(cycle["id"])
    assert cycle_after["scored_count"] == 1
    assert cycle_after["expedited_count"] == 0
    assert cycle_after["status"] == "SCORING"


# ─── The expedite flag at exactly 85.00 ───────────────────────────────


def test_expedite_flag_set_at_a_composite_of_exactly_eighty_five(api):
    """PRD §3.5: "Finally, `expedited` is true when `composite_score` is at least 85.00,
    and false below it; the comparison is inclusive at 85.00."
    PRD §3.5: "The four products are summed exactly and the **total** is rounded half up
    to two decimals once; the individual products are never rounded."

    Design: Difficulty/boundary_precision_check/expedite_flag_at_exactly_eighty_five_on_score
    """
    asset_a3, _asset_a4, cycle, request_5, _request_6 = _two_scanners_astride_the_expedite_bar()

    assert_decimal(asset_a3["service_penalty_points"], 8.17, "service_penalty_points")
    assert_decimal(asset_a3["adjusted_ruls_score"], 23.83, "adjusted_ruls_score")
    assert asset_a3["corrective_count_24m"] == 0, "a PM event never counts as corrective"
    assert_decimal(asset_a3["downtime_hours_24m"], 16.34, "downtime_hours_24m")

    validate_success(api.score_cycle(cycle["id"], _PLANNER))

    after = refresh_request(request_5["id"])
    assert after["status"] == "SCORED"
    assert_decimal(after["safety_driver"], 57.13, "safety_driver")
    assert_decimal(after["growth_driver"], 100.00, "growth_driver")
    assert_decimal(after["regulatory_driver"], 100.00, "regulatory_driver")
    assert_decimal(after["eos_driver"], 100.00, "eos_driver")
    assert_decimal(after["composite_score"], 85.00, "composite_score")
    assert after["expedited"] is True, "exactly 85.00 is expedited"

    row = latest_score(request_5["id"])
    assert row["expedited"] is True
    assert row["department_penalty_points"] == 0


def test_expedite_flag_clear_one_hundredth_below_the_bar(api):
    """PRD §3.5: "Finally, `expedited` is true when `composite_score` is at least 85.00,
    and false below it; the comparison is inclusive at 85.00."
    PRD §3.5: "In both cases a new score row is appended with `reason` `CYCLE_SCORING`,
    the request's `version` is incremented, and after the sweep the cycle's
    `scored_count` and `expedited_count` are refreshed and the cycle's `version` is
    incremented."

    Design: Difficulty/boundary_precision_check/expedite_flag_at_exactly_eighty_five_on_score
    """
    _asset_a3, asset_a4, cycle, _request_5, request_6 = _two_scanners_astride_the_expedite_bar()

    assert_decimal(asset_a4["service_penalty_points"], 8.16, "service_penalty_points")
    assert_decimal(asset_a4["adjusted_ruls_score"], 23.84, "adjusted_ruls_score")

    validate_success(api.score_cycle(cycle["id"], _PLANNER))

    after = refresh_request(request_6["id"])
    assert after["status"] == "SCORED"
    assert_decimal(after["safety_driver"], 57.12, "safety_driver")
    assert_decimal(after["composite_score"], 84.99, "composite_score")
    assert after["expedited"] is False, "84.99 falls below the bar"

    row = latest_score(request_6["id"])
    assert row["expedited"] is False

    cycle_after = refresh_cycle(cycle["id"])
    assert cycle_after["scored_count"] == 2
    assert cycle_after["expedited_count"] == 1
    assert cycle_after["status"] == "SCORING"
