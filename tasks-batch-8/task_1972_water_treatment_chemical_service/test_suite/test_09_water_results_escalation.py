"""Water test results: dual-variant LSI, classification boundary, the
depth-4 escalation cascade into corrective action and auto-drafted
replenishment, the >=3 threshold, lab-TDS confirmation, and segregation of
duties."""
import pytest

from test_helpers import (
    ApiErrorId,
    api_client,
    arrive_and_record,
    arrive_at_stop,
    create_published_route,
    deliver_and_close_order,
    find_pending_action,
    make_chemist_headers,
    post_telemetry,
    record_result,
    set_clock,
    setup_commissioned_asset,
    setup_pending_corrective_action,
    validate_error,
    validate_success,
)
from test_helpers import TEST_USERS

MANAGER = TEST_USERS["manager_headers"]
CHEMIST = TEST_USERS["chemist_headers"]

LSI_DESIGN = {"proposed_coc": 4.0, "inhibitor_target_ppm": 5, "ph_min": 7.0,
              "ph_max": 9.5, "conductivity_max_umhos": 4000}


def _commissioned_with_published_stop(account_name, design_overrides, window):
    subtree = setup_commissioned_asset(account_name=account_name,
                                       design_overrides=design_overrides)
    route, stops = create_published_route(
        subtree["account"]["id"], subtree["asset"]["id"], [window]
    )
    return subtree, stops[0]


def test_lsi_provisional_uses_conductivity_estimate(api):
    """PRD §3.4: "In the provisional variant, used at recording time before
    any lab work returns, the TDS value is estimated as `conductivity_umhos`
    multiplied by 0.7." "The saturation pH is (9.3 plus A plus B) minus (C
    plus D), and the index is the measured `ph` minus that saturation pH,
    stored to 2 decimal places rounded half up."

    Design: Difficulty/dual_variant_calc/lsi_provisional_vs_finalized_on_water_test_result
    """
    subtree, stop = _commissioned_with_published_stop(
        "Acme Plating", LSI_DESIGN, ("2026-08-02T00:00:00Z", "2026-08-03T00:00:00Z")
    )
    set_clock("2026-08-02T12:00:00Z")
    result = arrive_and_record(
        stop["id"], subtree["asset"]["id"],
        ph=8.0, conductivity_umhos=2000, calcium_ppm=300, alkalinity_ppm=150,
        temperature_f=90, inhibitor_residual_ppm=5.5,
    )
    # TDS estimate = 2000 * 0.7 = 1400 -> provisional index 0.79.
    assert result["lsi_provisional"] == pytest.approx(0.79, abs=1e-9)
    assert result["classification"] == "BALANCED"
    assert result["range_status"] == "IN_RANGE"
    assert result["lsi_final"] is None

    stop_after = validate_success(api_client.get_stop(stop["id"], CHEMIST))
    assert stop_after["status"] == "SAMPLED"


def test_lsi_final_recomputed_from_lab_tds_on_confirm(api):
    """PRD §3.4: "`lsi_final` is computed exactly as the provisional, except
    the TDS value is the measured `lab_tds_ppm` rather than the conductivity
    estimate, so identical field inputs yield a different final index whenever
    the lab value differs from the estimate; `classification` is then
    recomputed from the final index's band."

    Design: Difficulty/dual_variant_calc/lsi_provisional_vs_finalized_on_water_test_result
    """
    subtree, stop = _commissioned_with_published_stop(
        "Acme Plating 2", LSI_DESIGN, ("2026-08-02T00:00:00Z", "2026-08-03T00:00:00Z")
    )
    set_clock("2026-08-02T12:00:00Z")
    result = arrive_and_record(
        stop["id"], subtree["asset"]["id"],
        ph=8.0, conductivity_umhos=2000, calcium_ppm=300, alkalinity_ppm=150,
        temperature_f=90, inhibitor_residual_ppm=5.5,
    )
    confirmed = validate_success(
        api_client.confirm_water_test_result(result["id"], {"lab_tds_ppm": 2600}, CHEMIST)
    )
    assert confirmed["status"] == "CONFIRMED"
    # TDS measured = 2600 (vs estimate 1400) -> final index 0.76 != 0.79.
    assert confirmed["lsi_final"] == pytest.approx(0.76, abs=1e-9)
    assert confirmed["lsi_provisional"] == pytest.approx(0.79, abs=1e-9)
    assert confirmed["lsi_final"] != confirmed["lsi_provisional"]
    assert confirmed["classification"] == "BALANCED"


def test_lsi_classification_at_exactly_2_5_is_scale_forming(api):
    """PRD §3.4: "The `classification` follows the index bands: a value of 2.5
    or higher is `SCALE_FORMING`, a value of negative 2.5 or lower is
    `CORROSIVE`, and anything strictly between those bounds is `BALANCED`.
    Both boundaries are inclusive — exactly 2.5 is scale-forming and exactly
    negative 2.5 is corrosive."

    Design: Difficulty/boundary_precision_check/lsi_classification_at_exactly_2_5
    """
    subtree, stop = _commissioned_with_published_stop(
        "Boundary Co",
        {"proposed_coc": 3.0, "inhibitor_target_ppm": 4, "ph_min": 7.0,
         "ph_max": 10.0, "conductivity_max_umhos": 20000},
        ("2026-08-02T00:00:00Z", "2026-08-02T06:00:00Z"),
    )
    set_clock("2026-08-02T01:00:00Z")
    result = arrive_and_record(
        stop["id"], subtree["asset"]["id"],
        ph=8.6211, conductivity_umhos=8000, calcium_ppm=800, alkalinity_ppm=400,
        temperature_f=120, inhibitor_residual_ppm=4,
    )
    assert result["lsi_provisional"] == pytest.approx(2.5, abs=1e-9)
    assert result["classification"] == "SCALE_FORMING"


def test_lsi_classification_just_below_2_5_is_balanced(api):
    """PRD §3.4: "anything strictly between those bounds is `BALANCED`."

    Design: Difficulty/boundary_precision_check/lsi_classification_at_exactly_2_5
    """
    subtree, stop = _commissioned_with_published_stop(
        "Boundary Co 2",
        {"proposed_coc": 3.0, "inhibitor_target_ppm": 4, "ph_min": 7.0,
         "ph_max": 10.0, "conductivity_max_umhos": 20000},
        ("2026-08-02T06:00:00Z", "2026-08-02T12:00:00Z"),
    )
    set_clock("2026-08-02T07:00:00Z")
    result = arrive_and_record(
        stop["id"], subtree["asset"]["id"],
        ph=8.6111, conductivity_umhos=8000, calcium_ppm=800, alkalinity_ppm=400,
        temperature_f=120, inhibitor_residual_ppm=4,
    )
    assert result["lsi_provisional"] == pytest.approx(2.49, abs=1e-9)
    assert result["classification"] == "BALANCED"


def _setup_cascade_station(account_name):
    """Commissioned asset whose station holds 110 - 4 = 106 delivered gallons
    and ~40.0009 gal of trailing-window consumption (4 readings of 7571
    pulses x 5.0 ml)."""
    subtree = setup_commissioned_asset(
        account_name=account_name,
        asset_overrides={"recirculation_rate_gpm": 500, "system_volume_gal": 9000},
        design_overrides=LSI_DESIGN,
    )
    account_id, station_id = subtree["account"]["id"], subtree["station"]["id"]
    deliver_and_close_order(
        account_id, station_id, 110, "2026-08-02T00:00:00Z",
        delivered_gal=110, returned_residual_gal=4,
    )
    for recorded_at in ("2026-08-02T06:00:00Z", "2026-08-03T06:00:00Z",
                        "2026-08-04T06:00:00Z", "2026-08-04T18:00:00Z"):
        set_clock(recorded_at)
        post_telemetry(subtree["station"]["id"], recorded_at=recorded_at,
                       feed_pulses=7571, ml_per_pulse=5.0, level_gal=100)
    return subtree


def _run_three_out_of_range(subtree, recorder_third):
    route, stops = create_published_route(
        subtree["account"]["id"],
        subtree["asset"]["id"],
        [("2026-08-05T00:00:00Z", "2026-08-05T12:00:00Z"),
         ("2026-08-05T12:00:00Z", "2026-08-06T00:00:00Z"),
         ("2026-08-06T00:00:00Z", "2026-08-06T12:00:00Z")],
    )
    results = []
    for stop, clock, uid in (
        (stops[0], "2026-08-05T06:00:00Z", None),
        (stops[1], "2026-08-05T13:00:00Z", None),
        (stops[2], "2026-08-06T06:00:00Z", recorder_third),
    ):
        set_clock(clock)
        arrive_at_stop(stop["id"])
        results.append(
            record_result(stop["id"], subtree["asset"]["id"], out_of_range=True, user_id=uid)
        )
    return route, stops, results


def test_third_out_of_range_result_creates_pending_action(api):
    """PRD §3.5: "If the count has reached the escalation threshold of 3 —
    note the boundary: the second consecutive violation does not escalate,
    the third does — the system auto-creates a corrective action in `PENDING`
    status with `triggering_result_id` set to this result and
    `recorded_by_user_id` set to the current request's `X-User-ID`, and the
    asset's posture becomes `NON_COMPLIANT`."

    Design: Difficulty/transitive_cascade/out_of_range_escalation_cascade_depth4_result_to_autodraft
    """
    subtree = setup_commissioned_asset(account_name="Cascade Co")
    _, _, results = _run_three_out_of_range(subtree, recorder_third="chemist-recorder-1")

    action = find_pending_action(subtree["asset"]["id"])
    assert action["status"] == "PENDING"
    assert action["triggering_result_id"] == results[2]["id"]
    assert action["recorded_by_user_id"] == "chemist-recorder-1"

    asset = validate_success(api_client.get_asset(subtree["asset"]["id"], CHEMIST))
    assert asset["consecutive_out_of_range_count"] == 3
    assert asset["posture"] == "NON_COMPLIANT"


def test_apply_approved_action_recomputes_setpoint_and_autodrafts_order(api):
    """PRD §3.5: "The target station's `setpoint_ml_per_min` is set to the
    smaller of its `capacity_cap_ml_per_min` and the greater of zero and (the
    current setpoint plus `setpoint_delta_ml_per_min`)". "if the recomputed
    `projected_depletion_at` falls within fourteen days of the current clock
    — the boundary inclusive — the system auto-creates a replenishment
    delivery order for this station in `DRAFT` status with `auto_drafted`
    set to `true` and a `quantity_gal` of exactly one `container_size_gal` of
    the station's product." "the asset's `consecutive_out_of_range_count` is
    reset to 0 and its posture recomputed."

    Design: Difficulty/transitive_cascade/out_of_range_escalation_cascade_depth4_result_to_autodraft
    """
    subtree = _setup_cascade_station("Cascade Co 2")
    _, _, results = _run_three_out_of_range(subtree, recorder_third="chemist-recorder-1")
    action = find_pending_action(subtree["asset"]["id"])
    station = validate_success(api_client.get_feed_station(subtree["station"]["id"], CHEMIST))

    approved = validate_success(
        api_client.approve_corrective_action(
            action["id"],
            {
                "setpoint_delta_ml_per_min": 2.5,
                "rationale": "raise inhibitor feed",
                "expected_feed_station_version": station["version"],
            },
            make_chemist_headers("chemist-approver-2"),
        )
    )
    assert approved["status"] == "APPROVED"

    applied = validate_success(api_client.apply_corrective_action(action["id"], CHEMIST))
    assert applied["status"] == "APPLIED"

    station_after = validate_success(
        api_client.get_feed_station(subtree["station"]["id"], CHEMIST)
    )
    # 24.9206 (from the coc-4.0 acceptance) + 2.5, clamped to [0, 50].
    assert station_after["setpoint_ml_per_min"] == pytest.approx(27.4206, abs=1e-4)

    asset_after = validate_success(api_client.get_asset(subtree["asset"]["id"], CHEMIST))
    assert asset_after["consecutive_out_of_range_count"] == 0

    drafts = validate_success(
        api_client.list_delivery_orders(
            MANAGER, params={"station_id": subtree["station"]["id"], "status": "DRAFT"}
        )
    )
    auto_drafted = [o for o in drafts if o["auto_drafted"] is True]
    assert len(auto_drafted) == 1, f"expected exactly one auto-drafted order, got {drafts}"
    assert auto_drafted[0]["quantity_gal"] == pytest.approx(55)
    assert auto_drafted[0]["account_id"] == subtree["account"]["id"]


def test_escalation_threshold_exactly_three_not_two(api):
    """PRD §3.5: "If the count has reached the escalation threshold of 3 —
    note the boundary: the second consecutive violation does not escalate,
    the third does". "Below the threshold, an `OUT_OF_RANGE` result moves a
    `COMPLIANT` asset to `WATCH`."

    Design: Corner/calculations/escalation_threshold_exactly_three_not_two
    """
    subtree = setup_commissioned_asset(account_name="Thresh Co")
    route, stops = create_published_route(
        subtree["account"]["id"],
        subtree["asset"]["id"],
        [("2026-08-02T00:00:00Z", "2026-08-02T06:00:00Z"),
         ("2026-08-02T06:00:00Z", "2026-08-02T12:00:00Z"),
         ("2026-08-02T12:00:00Z", "2026-08-02T18:00:00Z")],
    )
    for stop, clock in zip(stops[:2], ("2026-08-02T01:00:00Z", "2026-08-02T07:00:00Z")):
        set_clock(clock)
        arrive_and_record(stop["id"], subtree["asset"]["id"], out_of_range=True)

    before = validate_success(
        api_client.list_corrective_actions(CHEMIST, params={"asset_id": subtree["asset"]["id"]})
    )
    assert before == [], "no corrective action may exist after only two violations"
    asset_mid = validate_success(api_client.get_asset(subtree["asset"]["id"], CHEMIST))
    assert asset_mid["posture"] == "WATCH"
    assert asset_mid["consecutive_out_of_range_count"] == 2

    # Third consecutive violation crosses the threshold.
    set_clock("2026-08-02T13:00:00Z")
    arrive_and_record(stops[2]["id"], subtree["asset"]["id"], out_of_range=True)

    actions = validate_success(
        api_client.list_corrective_actions(CHEMIST, params={"asset_id": subtree["asset"]["id"]})
    )
    assert len(actions) == 1 and actions[0]["status"] == "PENDING"
    asset_after = validate_success(api_client.get_asset(subtree["asset"]["id"], CHEMIST))
    assert asset_after["posture"] == "NON_COMPLIANT"
    assert asset_after["consecutive_out_of_range_count"] == 3


def test_result_confirm_requires_lab_tds(api):
    """PRD §3.4: "Confirmation — `RECORDED` → `CONFIRMED` — requires
    `lab_tds_ppm` in the payload (`ERR_LAB_TDS_REQUIRED` when absent)".

    Design: Corner/endpoints/result_confirm_requires_lab_tds
    """
    subtree, stop = _commissioned_with_published_stop(
        "Lab Co",
        {"proposed_coc": 3.0, "inhibitor_target_ppm": 4, "ph_min": 7.0,
         "ph_max": 9.5, "conductivity_max_umhos": 3000},
        ("2026-08-02T00:00:00Z", "2026-08-02T06:00:00Z"),
    )
    set_clock("2026-08-02T01:00:00Z")
    result = arrive_and_record(stop["id"], subtree["asset"]["id"])

    resp = api_client.confirm_water_test_result(result["id"], {}, CHEMIST)
    validate_error(resp, ApiErrorId.ERR_LAB_TDS_REQUIRED)
    assert resp.status_code == 422

    confirmed = validate_success(
        api_client.confirm_water_test_result(result["id"], {"lab_tds_ppm": 2600}, CHEMIST)
    )
    assert confirmed["status"] == "CONFIRMED"


def test_segregation_of_duties_same_user_approve_rejected(api):
    """PRD §3.5: "the approving `X-User-ID` must differ from the action's
    `recorded_by_user_id` (`ERR_SEGREGATION_OF_DUTIES`) — the chemist who
    recorded the triggering result may never approve the fix". PRD §2.6 tier
    9: failure is `ERR_SEGREGATION_OF_DUTIES` (HTTP 403).

    Design: Corner/validations/segregation_of_duties_same_user_approve_rejected
    """
    subtree = setup_pending_corrective_action(recorder_id="chemist-A")
    action = subtree["action"]
    station = subtree["station"]

    resp = api_client.approve_corrective_action(
        action["id"],
        {
            "setpoint_delta_ml_per_min": 1.0,
            "rationale": "x",
            "expected_feed_station_version": station["version"],
        },
        make_chemist_headers("chemist-A"),
    )
    validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)
    assert resp.status_code == 403

    after = validate_success(api_client.get_corrective_action(action["id"], CHEMIST))
    assert after["status"] == "PENDING"
