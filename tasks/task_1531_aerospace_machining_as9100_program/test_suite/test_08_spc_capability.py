"""SPC capability indices: provisional vs final variants, thresholds, escapes (PRD §3.6)."""
from test_helpers import (
    TEST_USERS,
    api_client,
    assert_work_order,
    get_characteristic,
    get_success_data,
    get_work_order,
    record_spc_series,
    setup_wo_with_key_characteristic,
)

MP = TEST_USERS["manufacturing_planner"]
QM = TEST_USERS["quality_manager"]
CQR = TEST_USERS["customer_quality_rep"]

# Five measurements around a 10.0 nominal with usl 10.10 / lsl 9.90:
# mean 10.00, sum of squared deviations 0.0004.
CAPABLE_SERIES = [10.01, 9.99, 10.01, 9.99, 10.00]
# Same layout with three-hundredths spread: mean 10.00, ssq 0.0036.
INCAPABLE_SERIES = [10.03, 9.97, 10.03, 9.97, 10.00]


# ---------------------------------------------------------------------------
# Difficulty: dual_variant_calc / spc_cpk_provisional_vs_final
# ---------------------------------------------------------------------------

def test_spc_cpk_provisional_sample_stddev(api):
    """PRD §3.6: "Two standard-deviation variants exist: the provisional
    variant, recomputed on every measurement during production, divides the sum
    of squared deviations from the mean by one less than the count — the sample
    standard deviation — while the final variant, computed once at work-order
    completion, divides by the full count — the population standard deviation —
    so identical measurements yield a `cpk_final` larger than the
    `cpk_provisional`."
    PRD §3.6: "The reported index is rounded half up to three decimal places;
    the reported mean and standard deviation are rounded half up to four
    decimal places for display only; and the verdict compares the rounded
    three-decimal index against the capability threshold of 1.33: an index of
    at least 1.33 sets the characteristic's `spc_eval_status` to `CAPABLE`,
    while anything below sets `INCAPABLE`."

    Design: Difficulty/dual_variant_calc/spc_cpk_provisional_vs_final
    """
    bundle = setup_wo_with_key_characteristic(wo_quantity=5, quantity=5)
    record_spc_series(bundle["wo"]["id"], bundle["kc"]["id"], CAPABLE_SERIES)
    kc = get_characteristic(bundle["kc"]["id"])
    # sample stddev s = sqrt(0.0004 / 4) = 0.01; cpk = 0.10 / (3 x 0.01) = 3.333
    assert kc["cpk_provisional"] == 3.333, (
        f"provisional (n-1) index must be 3.333, got {kc['cpk_provisional']}"
    )
    assert kc["spc_eval_status"] == "CAPABLE", (
        f"3.333 >= 1.33 must set CAPABLE, got {kc['spc_eval_status']}"
    )


def test_spc_cpk_final_population_stddev(api):
    """PRD §3.6: "Two standard-deviation variants exist: the provisional
    variant, recomputed on every measurement during production, divides the sum
    of squared deviations from the mean by one less than the count — the sample
    standard deviation — while the final variant, computed once at work-order
    completion, divides by the full count — the population standard deviation —
    so identical measurements yield a `cpk_final` larger than the
    `cpk_provisional`."
    PRD §3.5: "Completion also freezes the statistical picture: for each key
    characteristic with at least five SPC measurements on this work order, the
    final capability index is computed with the population-standard-deviation
    variant of §3.6 and stored as `cpk_final`."

    Design: Difficulty/dual_variant_calc/spc_cpk_provisional_vs_final
    """
    bundle = setup_wo_with_key_characteristic(wo_quantity=5, quantity=5)
    record_spc_series(bundle["wo"]["id"], bundle["kc"]["id"], CAPABLE_SERIES)
    kc_mid = get_characteristic(bundle["kc"]["id"])
    assert kc_mid["cpk_provisional"] == 3.333

    get_success_data(api_client.complete_work_order(bundle["wo"]["id"], MP))
    kc = get_characteristic(bundle["kc"]["id"])
    # population sigma = sqrt(0.0004 / 5) ~= 0.008944; cpk = 0.10 / (3 x sigma) = 3.727
    assert kc["cpk_final"] == 3.727, (
        f"final (n) index must be 3.727, got {kc['cpk_final']}"
    )
    assert kc["cpk_final"] != kc["cpk_provisional"], (
        "identical measurements yield a larger final index than provisional "
        "(population vs sample standard deviation)"
    )


# ---------------------------------------------------------------------------
# Difficulty: boundary_precision_check / spc_min_measurements_boundary
# ---------------------------------------------------------------------------

def test_spc_below_min_measurements_stays_monitoring(api):
    """PRD §3.6: "Fewer than 5 measurements in the window yields no index at
    all, and the characteristic's `spc_eval_status` rests at `MONITORING`."

    Design: Difficulty/boundary_precision_check/spc_min_measurements_boundary
    """
    bundle = setup_wo_with_key_characteristic(wo_quantity=5, quantity=5)
    record_spc_series(
        bundle["wo"]["id"], bundle["kc"]["id"], CAPABLE_SERIES[:4]
    )
    kc = get_characteristic(bundle["kc"]["id"])
    assert kc["spc_eval_status"] == "MONITORING", (
        f"four measurements yield no index; status rests at MONITORING, got "
        f"{kc['spc_eval_status']}"
    )
    assert kc.get("cpk_provisional") is None, (
        f"fewer than 5 measurements yields no index at all, got "
        f"{kc.get('cpk_provisional')}"
    )


def test_spc_fifth_measurement_triggers_evaluation(api):
    """PRD §3.6: "Fewer than 5 measurements in the window yields no index at
    all, and the characteristic's `spc_eval_status` rests at `MONITORING`. With
    5 or more, the mean is the arithmetic average of the windowed values."
    PRD §3.6: "an index of at least 1.33 sets the characteristic's
    `spc_eval_status` to `CAPABLE`, while anything below sets `INCAPABLE`. The
    provisional result is stored as `cpk_provisional`; the completion-time
    result as `cpk_final`."

    Design: Difficulty/boundary_precision_check/spc_min_measurements_boundary
    """
    bundle = setup_wo_with_key_characteristic(wo_quantity=5, quantity=5)
    record_spc_series(bundle["wo"]["id"], bundle["kc"]["id"], CAPABLE_SERIES)
    kc = get_characteristic(bundle["kc"]["id"])
    assert kc["spc_eval_status"] == "CAPABLE", (
        f"the 5th measurement triggers evaluation: 3.333 >= 1.33 -> CAPABLE, "
        f"got {kc['spc_eval_status']}"
    )
    assert kc["cpk_provisional"] == 3.333


# ---------------------------------------------------------------------------
# Corner: calculations / cpk_incapable_auto_ncr_and_flags
# ---------------------------------------------------------------------------

def test_cpk_incapable_auto_ncr_and_flags(api):
    """PRD §3.6: "When a characteristic's posture transitions into `INCAPABLE`,
    the work order's `spc_status` becomes `INCAPABLE`, its
    `requires_100pct_inspection` flag is set true — and never auto-clears — and
    a nonconformance report is auto-created with `origin` `AUTO_SPC`,
    `defect_code` `SPC_CAPABILITY_LOSS`, `quantity_affected` one, and status
    `OPEN`."
    PRD §3.6: "an index of at least 1.33 sets the characteristic's
    `spc_eval_status` to `CAPABLE`, while anything below sets `INCAPABLE`."

    Design: Corner/calculations/cpk_incapable_auto_ncr_and_flags
    """
    bundle = setup_wo_with_key_characteristic(wo_quantity=5, quantity=5)
    wo_id = bundle["wo"]["id"]
    record_spc_series(wo_id, bundle["kc"]["id"], INCAPABLE_SERIES)
    # sample stddev s = sqrt(0.0036 / 4) = 0.03; cpk = 0.10 / (3 x 0.03) = 1.111
    kc = get_characteristic(bundle["kc"]["id"])
    assert kc["cpk_provisional"] == 1.111, (
        f"provisional index must be 1.111, got {kc['cpk_provisional']}"
    )
    assert kc["spc_eval_status"] == "INCAPABLE", (
        f"1.111 < 1.33 must set INCAPABLE, got {kc['spc_eval_status']}"
    )

    wo = get_work_order(wo_id)
    assert_work_order(wo)
    assert wo["spc_status"] == "INCAPABLE"
    assert wo["requires_100pct_inspection"] is True, (
        "crossing into INCAPABLE sets the 100-percent inspection flag"
    )

    ncrs = get_success_data(api_client.list_ncrs(QM, params={"wo_id": wo_id}))
    assert isinstance(ncrs, list) and len(ncrs) == 1, (
        f"exactly one auto-created NCR is expected, got {len(ncrs)}"
    )
    ncr = ncrs[0]
    assert ncr["origin"] == "AUTO_SPC"
    assert ncr["defect_code"] == "SPC_CAPABILITY_LOSS"
    assert ncr["quantity_affected"] == 1
    assert ncr["status"] == "OPEN"
