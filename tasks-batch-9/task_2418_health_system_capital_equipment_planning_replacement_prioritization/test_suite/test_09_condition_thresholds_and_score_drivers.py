"""Boundary arithmetic: the trailing service window, the derate floor and the four drivers."""

from test_helpers import (
    TEST_USERS,
    add_service_event,
    assert_asset,
    assert_cents,
    assert_decimal,
    assert_priority_score,
    close_intake,
    get_success_data,
    make_asset,
    make_cycle,
    make_department,
    make_facility,
    make_request,
    open_intake,
    pin_clock,
    refresh_asset,
    refresh_cycle,
    refresh_department,
    refresh_request,
    run_scoring,
    schedule_audit,
    score_rows,
    screen,
    service_event_rows,
    setup_implemented_request,
    submit,
    validate_success,
)

CLOCK = "2026-08-01T00:00:00Z"
_PLANNER = TEST_USERS["planner_headers"]
_AUDITOR = TEST_USERS["auditor_headers"]


def _ct_estate():
    """Facility NRH with one CT department, clock pinned at the startup instant."""
    pin_clock(CLOCK)
    facility = make_facility(
        name="North Regional Hospital", code="NRH", region="NORTH",
        max_concurrent_construction=1,
    )
    department = make_department(
        facility["id"], name="Diagnostic Imaging CT", modality_scope="CT"
    )
    return facility, department


def _scanner(facility, department, model_name, **overrides):
    """A CT scanner installed 2020-08-02 — exactly 2190 days, so 6.00 years old."""
    payload = {
        "modality": "CT",
        "model_name": model_name,
        "install_date": "2020-08-02T00:00:00Z",
        "acquisition_cost_cents": 100000000,
        "oem_support_end_date": "2029-06-01T00:00:00Z",
    }
    payload.update(overrides)
    return make_asset(facility["id"], department["id"], **payload)


def _derated_rows(api, department_id):
    return get_success_data(
        api.list_assets(_PLANNER, params={"department_id": department_id, "status": "DERATED"})
    )


# ─── The closed trailing service window ───────────────────────────────


def test_a_service_event_exactly_two_years_old_still_counts_while_one_day_older_does_not(api):
    """PRD §3.2: "Over the closed trailing window of seven hundred thirty days — two years —
    ending at `ruls_as_of`, the server counts every service event whose `category` is
    `CORRECTIVE` into `corrective_count_24m`, and sums the `downtime_hours` of events of
    **every** category into `downtime_hours_24m`."
    PRD §3.2: "From those, `service_penalty_points` is three points for each corrective event
    plus half a point for each downtime hour, rounded half up to two decimals, and then capped
    at 40.00; the cap applies to this penalty term alone and never to the sum of all
    penalties."
    PRD §2.6: "`version` is an integer that starts at 1 when the row is created and increases
    by exactly one on every mutation of that row, including mutations performed as a side
    effect of an operation on another resource."

    Design: Corner/calculations/service_event_exactly_730_days_old_is_inside_the_window_and_731_is_outside
    """
    facility, department = _ct_estate()
    inside = _scanner(facility, department, "Aquilon CT-IN", expected_life_years=10)
    outside = _scanner(facility, department, "Aquilon CT-OUT", expected_life_years=10)

    add_service_event(inside["id"], "2024-08-01T00:00:00Z", "CORRECTIVE",
                      downtime_hours=4.00, cost_cents=250000)
    add_service_event(outside["id"], "2024-07-31T00:00:00Z", "CORRECTIVE",
                      downtime_hours=4.00, cost_cents=250000)

    counted = refresh_asset(inside["id"])
    assert_asset(counted)
    assert counted["corrective_count_24m"] == 1
    assert_decimal(counted["downtime_hours_24m"], 4.00, "downtime_hours_24m")
    assert_decimal(counted["service_penalty_points"], 5.00, "service_penalty_points")
    assert_decimal(counted["nominal_ruls_score"], 40.00, "nominal_ruls_score")
    assert_decimal(counted["adjusted_ruls_score"], 35.00, "adjusted_ruls_score")
    assert counted["status"] == "IN_SERVICE"
    assert counted["version"] == 2

    ignored = refresh_asset(outside["id"])
    assert ignored["corrective_count_24m"] == 0
    assert_decimal(ignored["downtime_hours_24m"], 0.00, "downtime_hours_24m")
    assert_decimal(ignored["service_penalty_points"], 0.00, "service_penalty_points")
    assert_decimal(ignored["adjusted_ruls_score"], 40.00, "adjusted_ruls_score")
    assert ignored["status"] == "IN_SERVICE"
    assert ignored["version"] == 2

    assert len(service_event_rows(inside["id"])) == 1
    assert len(service_event_rows(outside["id"])) == 1, (
        "the out-of-window event is still stored; only the aggregation ignores it"
    )


def test_the_service_penalty_cap_clips_one_term_and_drives_the_curve_to_the_floor(api):
    """PRD §3.2: "From those, `service_penalty_points` is three points for each corrective event
    plus half a point for each downtime hour, rounded half up to two decimals, and then capped
    at 40.00; the cap applies to this penalty term alone and never to the sum of all
    penalties."
    PRD §3.2: "`adjusted_ruls_score` is the nominal score with the service penalty, the
    end-of-support penalty and the recall penalty **subtracted** from it, the result rounded
    half up to two decimals and clamped into the range 0.00 through 100.00."
    PRD §3.2: "The **derate gate** sets the asset's `status` to `DERATED` when
    `adjusted_ruls_score` is at most 15.00 or when `unresolved_recall` is true, and to
    `IN_SERVICE` otherwise."

    Design: Corner/calculations/service_penalty_cap_binds_only_the_service_term_and_can_drive_the_score_to_zero
    """
    facility, department = _ct_estate()
    asset = _scanner(facility, department, "Aquilon CT-CAP", expected_life_years=10)

    appended = validate_success(
        api.create_service_event(
            asset["id"],
            {"event_date": "2026-03-01T00:00:00Z", "category": "CORRECTIVE",
             "downtime_hours": 100.00},
            _PLANNER,
        ),
        201,
    )
    assert appended["category"] == "CORRECTIVE"

    after = refresh_asset(asset["id"])
    assert after["corrective_count_24m"] == 1
    assert_decimal(after["downtime_hours_24m"], 100.00, "downtime_hours_24m")
    assert_decimal(after["service_penalty_points"], 40.00, "service_penalty_points")
    assert_decimal(after["nominal_ruls_score"], 40.00, "nominal_ruls_score")
    assert_decimal(after["adjusted_ruls_score"], 0.00, "adjusted_ruls_score")
    assert after["status"] == "DERATED"


def test_an_old_unresolved_recall_derates_a_healthy_scanner_until_it_is_resolved(api):
    """PRD §3.2: "Separately, `unresolved_recall` is true when the most recent recall event of
    the asset, chosen over the asset's entire history rather than only the trailing window and
    ordered by `event_date` descending and then `created_at` descending, has `recall_resolved`
    false; it is false when the asset has no recall event at all."
    PRD §3.2: "An unresolved recall contributes a further penalty of 10.00."
    PRD §3.2: "On a service-event append or an asset edit the gate drives the pair of
    transitions `IN_SERVICE → DERATED` and `DERATED → IN_SERVICE`: the machine falls out of
    service when the adjusted score drops to 15.00 or below or an unresolved recall appears,
    and it returns to service only when the adjusted score is strictly above 15.00 and
    `unresolved_recall` is false — which happens when a later recall event records the
    resolution, or when an old downtime window rolls out of the trailing two-year span."

    Design: Corner/calculations/unresolved_recall_is_read_over_all_history_and_gates_status_both_ways
    """
    facility, department = _ct_estate()
    asset = _scanner(facility, department, "Aquilon CT-REC", expected_life_years=10)

    add_service_event(asset["id"], "2023-01-01T00:00:00Z", "RECALL", downtime_hours=0.00,
                      recall_resolved=False, notes="Vendor recall on the tube assembly.")
    recalled = refresh_asset(asset["id"])
    assert recalled["unresolved_recall"] is True
    assert_decimal(recalled["service_penalty_points"], 0.00, "service_penalty_points")
    assert_decimal(recalled["adjusted_ruls_score"], 30.00, "adjusted_ruls_score")
    assert recalled["status"] == "DERATED", "the recall flag alone derates a 30.00 asset"

    add_service_event(asset["id"], "2026-07-01T00:00:00Z", "RECALL", downtime_hours=0.00,
                      recall_resolved=True, notes="Tube assembly replaced under the recall.")
    cleared = refresh_asset(asset["id"])
    assert cleared["unresolved_recall"] is False
    assert_decimal(cleared["adjusted_ruls_score"], 40.00, "adjusted_ruls_score")
    assert cleared["status"] == "IN_SERVICE"
    assert cleared["version"] == 3

    assert len(service_event_rows(asset["id"], category="RECALL")) == 2


def test_an_asset_already_at_the_derate_floor_is_created_derated(api):
    """PRD §3.2: "On asset creation the gate decides the status the new row is born with, so an
    asset whose adjusted score is already at or below 15.00, or that is created with an
    unresolved recall, starts life `DERATED` rather than `IN_SERVICE`."
    PRD §3.2: "The **derate gate** sets the asset's `status` to `DERATED` when
    `adjusted_ruls_score` is at most 15.00 or when `unresolved_recall` is true, and to
    `IN_SERVICE` otherwise."
    PRD §3.1: "Assets can be listed filtered by `facility_id`, `department_id`, `modality`,
    `status` and `disposition_status`."

    Design: Corner/state_machines/asset_created_at_or_below_the_derate_floor_is_born_derated
    """
    facility, department = _ct_estate()

    asset = validate_success(
        api.create_asset(
            {"facility_id": facility["id"], "department_id": department["id"], "modality": "CT",
             "model_name": "Aquilon CT-1", "install_date": "2019-08-02T00:00:00Z",
             "expected_life_years": 8, "acquisition_cost_cents": 100000000,
             "oem_support_end_date": "2029-06-01T00:00:00Z"},
            _PLANNER,
        ),
        201,
    )
    assert_asset(asset)
    assert_decimal(asset["age_years"], 7.00, "age_years")
    assert_decimal(asset["nominal_ruls_score"], 12.50, "nominal_ruls_score")
    assert_decimal(asset["adjusted_ruls_score"], 12.50, "adjusted_ruls_score")
    assert asset["status"] == "DERATED"
    assert asset["version"] == 1
    assert_decimal(asset["service_penalty_points"], 0.00, "service_penalty_points")
    assert asset["unresolved_recall"] is False
    assert asset["disposition_status"] == "NONE"

    rows = _derated_rows(api, department["id"])
    assert [row["id"] for row in rows] == [asset["id"]]


def test_the_derate_floor_is_reached_by_accumulation_and_left_by_a_life_correction(api):
    """PRD §3.2: "The two aggregates deliberately use different category filters: a
    planned-maintenance or upgrade event contributes its downtime but not to the corrective
    count."
    PRD §3.2: "The **derate gate** sets the asset's `status` to `DERATED` when
    `adjusted_ruls_score` is at most 15.00 or when `unresolved_recall` is true, and to
    `IN_SERVICE` otherwise."
    PRD §3.1: "A planner may later edit `model_name`, `install_date`, `expected_life_years`,
    `oem_support_end_date` and `acquisition_cost_cents`; every such edit re-runs the scoring,
    re-applies the derate gate, and re-scores any replacement request of that asset that is
    currently `SCORED`, appending a fresh score row whose `reason` is
    `ASSET_CONDITION_CHANGE`."

    Design: Corner/cross_cutting_complexity_layers/the_derate_floor_is_crossed_cumulatively_and_reset_by_a_life_correction
    """
    facility, department = _ct_estate()
    asset = _scanner(facility, department, "Aquilon CT-8", expected_life_years=8)

    first = add_service_event(asset["id"], "2026-07-01T00:00:00Z", "CORRECTIVE",
                              downtime_hours=0.00)
    assert first["category"] == "CORRECTIVE"
    step_one = refresh_asset(asset["id"])
    assert step_one["corrective_count_24m"] == 1
    assert_decimal(step_one["downtime_hours_24m"], 0.00, "downtime_hours_24m")
    assert_decimal(step_one["service_penalty_points"], 3.00, "service_penalty_points")
    assert_decimal(step_one["adjusted_ruls_score"], 22.00, "adjusted_ruls_score")
    assert step_one["status"] == "IN_SERVICE"

    add_service_event(asset["id"], "2026-07-05T00:00:00Z", "CORRECTIVE", downtime_hours=0.00)
    step_two = refresh_asset(asset["id"])
    assert step_two["corrective_count_24m"] == 2
    assert_decimal(step_two["service_penalty_points"], 6.00, "service_penalty_points")
    assert_decimal(step_two["adjusted_ruls_score"], 19.00, "adjusted_ruls_score")
    assert step_two["status"] == "IN_SERVICE"

    add_service_event(asset["id"], "2026-07-10T00:00:00Z", "CORRECTIVE", downtime_hours=1.00)
    step_three = refresh_asset(asset["id"])
    assert step_three["corrective_count_24m"] == 3
    assert_decimal(step_three["downtime_hours_24m"], 1.00, "downtime_hours_24m")
    assert_decimal(step_three["service_penalty_points"], 9.50, "service_penalty_points")
    assert_decimal(step_three["adjusted_ruls_score"], 15.50, "adjusted_ruls_score")
    assert step_three["status"] == "IN_SERVICE", "15.50 sits half a point above the floor"
    assert_decimal(step_three["nominal_ruls_score"], 25.00, "nominal_ruls_score")

    add_service_event(asset["id"], "2026-07-15T00:00:00Z", "PM", downtime_hours=1.00)
    at_floor = refresh_asset(asset["id"])
    assert at_floor["corrective_count_24m"] == 3, "a PM event carries downtime but no corrective"
    assert_decimal(at_floor["downtime_hours_24m"], 2.00, "downtime_hours_24m")
    assert_decimal(at_floor["service_penalty_points"], 10.00, "service_penalty_points")
    assert_decimal(at_floor["adjusted_ruls_score"], 15.00, "adjusted_ruls_score")
    assert at_floor["status"] == "DERATED", "the bar is inclusive at 15.00"
    assert len(_derated_rows(api, department["id"])) == 1

    corrected = validate_success(
        api.patch_asset(asset["id"], {"expected_life_years": 10}, _PLANNER)
    )
    assert corrected["expected_life_years"] == 10
    assert_decimal(corrected["age_years"], 6.00, "age_years")
    assert_decimal(corrected["nominal_ruls_score"], 40.00, "nominal_ruls_score")
    assert_decimal(corrected["service_penalty_points"], 10.00, "service_penalty_points")
    assert_decimal(corrected["adjusted_ruls_score"], 30.00, "adjusted_ruls_score")
    assert corrected["status"] == "IN_SERVICE"
    assert _derated_rows(api, department["id"]) == []


# ─── The four prioritization drivers at their breaks ──────────────────


def test_one_extra_projected_procedure_rounds_growth_up_into_the_next_tier(api):
    """PRD §3.5: "The growth percentage is the projected annual volume less the current annual
    volume, divided by the current annual volume or by 1 when the current volume is zero,
    multiplied by one hundred, and rounded half up to two decimals."
    PRD §3.5: "That rounding happens **before** the tier lookup, so a raw ratio of 9.995
    percent becomes 10.00 and crosses into the next tier."
    PRD §3.5: "A growth percentage below 0.00 yields a driver of 0.00; from 0.00 up to but not
    including 10.00 yields 25.00; from 10.00 up to but not including 25.00 yields 50.00; from
    25.00 up to but not including 50.00 yields 75.00; and 50.00 or above yields 100.00."
    PRD §3.5: "A score row carries the `request_id` it belongs to, a one-based `sequence` equal
    to one more than the highest sequence already recorded for that request, a `reason` of
    `CYCLE_SCORING`, `ASSET_CONDITION_CHANGE` or `DEPARTMENT_PENALTY_CHANGE`, the pinned
    `asset_adjusted_ruls_snapshot` and `corrective_count_snapshot` taken from the asset at
    scoring time, the four values `safety_driver`, `growth_driver`, `regulatory_driver` and
    `eos_driver`, the `department_penalty_points` subtracted in that row, that row's own
    `composite_score`, and that row's own `expedited`."

    Design: Corner/calculations/growth_tier_break_is_read_after_the_two_decimal_rounding
    """
    facility, department = _ct_estate()
    asset_up = _scanner(facility, department, "Aquilon CT-8", expected_life_years=8)
    asset_down = _scanner(facility, department, "Aquilon CT-8B", expected_life_years=8)
    cycle = make_cycle(plan_year=2027, plan_year_start="2027-01-01T00:00:00Z",
                       total_capital_cents=500000000, contingency_pct=0.00,
                       facility_contingency_pct=0.00)
    open_intake(cycle["id"])

    volumes = {"current_annual_volume": 20000, "estimated_capital_cents": 100000000,
               "annual_service_contract_cents": 10000000, "disposable_unit_cents": 500}
    request_up = make_request(cycle["id"], department["id"], asset_up["id"],
                              clinical_justification="Growth at the rounding edge.",
                              projected_annual_volume=21999, **volumes)
    request_down = make_request(cycle["id"], department["id"], asset_down["id"],
                                clinical_justification="Growth one unit below the rounding edge.",
                                projected_annual_volume=21998, **volumes)
    for request in (request_up, request_down):
        submit(request["id"], department["id"])
        screen(request["id"], "ACCEPT")
    close_intake(cycle["id"])

    scored = validate_success(api.score_cycle(cycle["id"], _PLANNER))
    assert scored["scored_count"] == 2
    assert scored["expedited_count"] == 0

    crossed = refresh_request(request_up["id"])
    assert_decimal(crossed["growth_driver"], 50.00, "growth_driver")
    assert_decimal(crossed["safety_driver"], 56.25, "safety_driver")
    assert_decimal(crossed["regulatory_driver"], 0.00, "regulatory_driver")
    assert_decimal(crossed["eos_driver"], 0.00, "eos_driver")
    assert_decimal(crossed["composite_score"], 29.69, "composite_score")
    assert crossed["expedited"] is False
    assert crossed["status"] == "SCORED"

    below = refresh_request(request_down["id"])
    assert_decimal(below["growth_driver"], 25.00, "growth_driver")
    assert_decimal(below["composite_score"], 24.69, "composite_score")

    rows = score_rows(request_up["id"])
    assert len(rows) == 1
    row = rows[0]
    assert_priority_score(row)
    assert row["sequence"] == 1
    assert row["reason"] == "CYCLE_SCORING"
    assert_decimal(row["asset_adjusted_ruls_snapshot"], 25.00, "asset_adjusted_ruls_snapshot")
    assert row["corrective_count_snapshot"] == 0
    assert row["department_penalty_points"] == 0
    assert_decimal(row["composite_score"], 29.69, "composite_score")


def test_one_day_of_support_moves_the_driver_while_neither_asset_takes_a_penalty(api):
    """PRD §3.5: "The **end-of-support driver** is 100.00 when the asset's
    `oem_support_end_date` falls at or before the cycle's `plan_year_start`, 60.00 when it
    falls at or before seven hundred thirty days — two years — after `plan_year_start`, and
    0.00 otherwise."
    PRD §3.5: "Note the deliberate asymmetry with §3.2: this driver is measured against the
    cycle's `plan_year_start`, while the end-of-support penalty inside the remaining-useful-life
    score is measured against the logical clock."
    PRD §3.2: "An end-of-support penalty of 20.00 applies when `oem_support_end_date` is at or
    before `ruls_as_of`; a penalty of 8.00 applies when the support end falls after
    `ruls_as_of` but at or within three hundred sixty-five days — one year — of it; otherwise
    the end-of-support penalty is zero."

    Design: Corner/calculations/eos_driver_measures_plan_year_start_while_the_eos_penalty_measures_the_clock
    """
    facility, department = _ct_estate()
    asset_in = _scanner(facility, department, "Aquilon CT-EOS-IN", expected_life_years=8,
                        oem_support_end_date="2028-12-31T00:00:00Z")
    asset_out = _scanner(facility, department, "Aquilon CT-EOS-OUT", expected_life_years=8,
                         oem_support_end_date="2029-01-01T00:00:00Z")
    cycle = make_cycle(plan_year=2027, plan_year_start="2027-01-01T00:00:00Z",
                       total_capital_cents=500000000, contingency_pct=0.00,
                       facility_contingency_pct=0.00)
    open_intake(cycle["id"])

    request_in = make_request(cycle["id"], department["id"], asset_in["id"],
                              clinical_justification="Support ends inside the two-year horizon.")
    request_out = make_request(cycle["id"], department["id"], asset_out["id"],
                               clinical_justification="Support ends one day outside the horizon.")
    for request in (request_in, request_out):
        submit(request["id"], department["id"])
        screen(request["id"], "ACCEPT")
    close_intake(cycle["id"])
    run_scoring(cycle["id"])

    inside = refresh_request(request_in["id"])
    assert_decimal(inside["eos_driver"], 60.00, "eos_driver")
    assert_decimal(inside["composite_score"], 51.69, "composite_score")
    assert inside["expedited"] is False

    outside = refresh_request(request_out["id"])
    assert_decimal(outside["eos_driver"], 0.00, "eos_driver")
    assert_decimal(outside["composite_score"], 39.69, "composite_score")
    assert outside["expedited"] is False

    for asset in (asset_in, asset_out):
        after = refresh_asset(asset["id"])
        assert_decimal(after["adjusted_ruls_score"], 25.00, "adjusted_ruls_score")
        assert_decimal(after["nominal_ruls_score"], 25.00, "nominal_ruls_score")

    assert refresh_cycle(cycle["id"])["expedited_count"] == 0


def test_one_cent_of_overrun_fails_the_audit_and_reprices_the_other_request(api):
    """PRD §3.11: "`opex_variance_pct` is `actual_annual_opex_cents` less
    `baseline_year1_opex_snapshot`, divided by `baseline_year1_opex_snapshot`, multiplied by one
    hundred, rounded half up to two decimals; a negative variance means the equipment came in
    under its business-case operating cost."
    PRD §3.11: "The audit moves `SCHEDULED → UNDERPERFORMING` when the attainment falls below
    80.00 or the variance exceeds 10.00."
    PRD §3.11: "Because the verdict is underperforming, the owning department's
    `utilization_penalty_points` becomes the smaller of 20 and its current value plus 10, its
    `underperformance_flag` becomes true, and the department's `version` is incremented — so
    the penalty accumulates ten points per underperforming audit and stops at twenty."
    PRD §3.11: "Because the department penalty changed, every request of that department
    standing in `SCORED` whose cycle stands in `SCORING` or `ALLOCATED` is re-scored with the
    new penalty subtracted, receiving a fresh score row whose `reason` is
    `DEPARTMENT_PENALTY_CHANGE`, with that request's `version` incremented and its cycle's
    `expedited_count` refreshed."
    PRD §3.11: "Requests in a cycle that has already reached `COMMITTED`, and requests no
    longer standing in `SCORED`, are left alone."

    Design: Corner/calculations/audit_opex_bar_flips_one_cent_past_ten_percent_and_cascades_the_department_penalty
    """
    ctx = setup_implemented_request(allocation_method="RANK_ORDERED")
    department = ctx["department"]
    second_asset = make_asset(
        ctx["facility"]["id"], department["id"],
        modality="CT", model_name="Aquilon CT-3", install_date="2020-08-02T00:00:00Z",
        expected_life_years=8, acquisition_cost_cents=100000000,
        oem_support_end_date="2031-01-01T00:00:00Z",
    )
    next_cycle = make_cycle(plan_year=2028, plan_year_start="2028-01-01T00:00:00Z",
                            total_capital_cents=500000000, contingency_pct=0.00,
                            facility_contingency_pct=0.00)
    open_intake(next_cycle["id"])
    next_request = make_request(next_cycle["id"], department["id"], second_asset["id"],
                                clinical_justification="Second CT in the 2028 plan year.")
    submit(next_request["id"], department["id"])
    screen(next_request["id"], "ACCEPT")
    close_intake(next_cycle["id"])
    run_scoring(next_cycle["id"])
    assert_decimal(refresh_request(next_request["id"])["composite_score"], 39.69,
                   "composite_score")

    audit = schedule_audit(ctx["request"]["id"], ctx["project"]["id"], CLOCK,
                           "2027-08-01T00:00:00Z")
    assert audit["projected_annual_volume_snapshot"] == 2000
    assert_cents(audit["baseline_year1_opex_snapshot"], 10850000,
                 "baseline_year1_opex_snapshot")

    collected = validate_success(
        api.collect_audit(
            audit["id"],
            {"actual_annual_volume": 1600, "actual_annual_opex_cents": 11935543},
            _AUDITOR,
        )
    )
    assert collected["status"] == "UNDERPERFORMING"
    assert_decimal(collected["volume_attainment_pct"], 80.00, "volume_attainment_pct")
    assert_decimal(collected["opex_variance_pct"], 10.01, "opex_variance_pct")
    assert collected["version"] == 2

    assert refresh_request(ctx["request"]["id"])["status"] == "AUDITED"

    penalised = refresh_department(department["id"])
    assert penalised["utilization_penalty_points"] == 10
    assert penalised["underperformance_flag"] is True
    assert penalised["version"] == 2

    rescored = refresh_request(next_request["id"])
    assert_decimal(rescored["composite_score"], 29.69, "composite_score")
    assert rescored["expedited"] is False
    cascade_rows = score_rows(next_request["id"], reason="DEPARTMENT_PENALTY_CHANGE")
    assert len(cascade_rows) == 1
    assert cascade_rows[0]["sequence"] == 2
    assert cascade_rows[0]["department_penalty_points"] == 10

    after_next = refresh_cycle(next_cycle["id"])
    assert after_next["status"] == "SCORING"
    assert after_next["expedited_count"] == 0

    settled = refresh_cycle(ctx["cycle"]["id"])
    assert settled["status"] == "COMMITTED"
    assert_decimal(refresh_request(ctx["request"]["id"])["composite_score"], 39.69,
                   "composite_score")
