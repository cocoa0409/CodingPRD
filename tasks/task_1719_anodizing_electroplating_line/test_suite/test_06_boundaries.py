"""Boundary precision: amp-hour capacity, thickness spec, discharge limits, rounding."""
from test_helpers import (
    ApiErrorId,
    CHEM,
    EHS,
    MGR,
    OP,
    QC,
    abort_load_run,
    complete_load_run,
    create_compat_rule,
    create_customer,
    create_permit,
    create_titrated_bath,
    get_bath,
    get_bath_version,
    get_permit,
    get_success_data,
    get_work_order,
    inspect_work_order,
    record_sample,
    setup_awaiting_inspection,
    setup_routed_order,
    start_load_run,
    validate_error,
)
from test_helpers.api_client import api_client


def test_bath_capacity_inclusive_equality_allows_exact_fit():
    """PRD §3.5: "the nameplate ceiling must hold, meaning the bath's used plus reserved
    plus the new estimate is at most `amp_hour_capacity` with equality permitted (else
    `ERR_BATH_CAPACITY_EXCEEDED`)"

    Design: Difficulty/boundary_precision_check/bath_capacity_inclusive_equality
    """
    customer = create_customer(company_name="Lambda Signage")
    create_compat_rule()
    bath = create_titrated_bath(
        bath_code="ANO-11", routing_modes_supported=["BARREL"], amp_hour_capacity=540,
    )
    # Driver: one 450 Ah load (10 dm2 x 3.0 A/dm2 x 900 min / 60), completed + passed.
    wa = setup_routed_order(customer["id"], bath["id"], part_number="PN-110A",
                            part_count=10, surface_area_dm2_per_part=1.0,
                            planned_duration_minutes=900,
                            planned_current_density_a_dm2=3.0)
    lra = start_load_run(wa["id"], bath_id=bath["id"], duration_minutes=900,
                         current_density_a_dm2=3.0)
    assert lra["estimated_amp_hours"] == 450.0
    complete_load_run(lra["id"])
    inspect_work_order(wa["id"], defect_type="NONE")
    detail = get_bath(bath["id"])
    assert detail["amp_hour_used"] == 450.0
    # Boundary: 450 + 0 + 90.0 == 540 == capacity (inclusive) -> start allowed.
    wb = setup_routed_order(customer["id"], bath["id"], part_number="PN-110B",
                            part_count=10, surface_area_dm2_per_part=1.0)
    lrb = start_load_run(wb["id"], bath_id=bath["id"], duration_minutes=540,
                         current_density_a_dm2=1.0)
    assert lrb["estimated_amp_hours"] == 90.0
    assert lrb["status"] == "RUNNING"


def test_bath_capacity_exceeded_above_capacity_and_abort_zero_drift():
    """PRD §3.5: "the nameplate ceiling must hold, meaning the bath's used plus reserved
    plus the new estimate is at most `amp_hour_capacity` with equality permitted (else
    `ERR_BATH_CAPACITY_EXCEEDED`)"
    PRD §3.5: "No amp-hours are debited; `amp_hour_used` is invariant under abort."

    Design: Difficulty/boundary_precision_check/bath_capacity_inclusive_equality
    """
    customer = create_customer(company_name="Lambda Signage 2")
    create_compat_rule()
    bath = create_titrated_bath(
        bath_code="ANO-11B", routing_modes_supported=["BARREL"], amp_hour_capacity=540,
    )
    wa = setup_routed_order(customer["id"], bath["id"], part_number="PN-110A2",
                            part_count=10, surface_area_dm2_per_part=1.0,
                            planned_duration_minutes=900,
                            planned_current_density_a_dm2=3.0)
    lra = start_load_run(wa["id"], bath_id=bath["id"], duration_minutes=900,
                         current_density_a_dm2=3.0)
    complete_load_run(lra["id"])
    inspect_work_order(wa["id"], defect_type="NONE")
    wb = setup_routed_order(customer["id"], bath["id"], part_number="PN-110B2",
                            part_count=10, surface_area_dm2_per_part=1.0)
    # Start the exact-fit load then abort it: reserved returns to 0, used stays 450.
    lrb = start_load_run(wb["id"], bath_id=bath["id"], duration_minutes=540,
                         current_density_a_dm2=1.0)
    abort_load_run(lrb["id"])
    detail = get_bath(bath["id"])
    assert detail["amp_hour_reserved"] == 0
    assert detail["amp_hour_used"] == 450.0
    # Over-boundary: 546 min x 1.0 x 10 dm2 / 60 = 91.0 -> 450 + 91.0 = 541 > 540.
    resp = api_client.start_load_run(
        wb["id"],
        {"duration_minutes": 546, "current_density_a_dm2": 1.0,
         "expected_bath_version": detail["version"]},
        OP,
    )
    validate_error(resp, ApiErrorId.ERR_BATH_CAPACITY_EXCEEDED)


def test_thickness_spec_inclusive_bounds_pass_at_equality():
    """PRD §3.6: "`thickness_ok`, true exactly when the minimum reading is at least
    `thickness_spec_min_um` and the maximum reading is at most `thickness_spec_max_um`,
    both bounds inclusive so a reading equal to a spec bound passes."
    PRD §3.6: "`PASS` requires `thickness_ok` and a `defect_type` of `NONE`: the order
    moves to `COMPLETE`"

    Design: Difficulty/boundary_precision_check/thickness_spec_inclusive_bounds
    """
    customer = create_customer(company_name="Mu Enclosures")
    create_compat_rule()
    bath = create_titrated_bath(bath_code="ANO-12", routing_modes_supported=["BARREL"])
    wa, _lr = setup_awaiting_inspection(customer["id"], bath["id"], part_number="PN-120A")
    report = inspect_work_order(wa["id"], thickness_readings_um=[12.0, 15.0, 18.0],
                                defect_type="NONE")
    assert report["thickness_ok"] is True
    assert report["disposition"] == "PASS"
    assert get_work_order(wa["id"])["status"] == "COMPLETE"


def test_thickness_below_min_by_point_one_is_reworkable_reject():
    """PRD §3.6: "`thickness_ok`, true exactly when the minimum reading is at least
    `thickness_spec_min_um` and the maximum reading is at most `thickness_spec_max_um`,
    both bounds inclusive so a reading equal to a spec bound passes."
    PRD §3.6: "Everything else — defects `STAIN`, `PITTING`, or `UNDERTHICKNESS`, or a
    thickness failure with `rework_count` below two — is a `REWORKABLE_REJECT`: the
    order moves to `REJECTED` with `pending_strip` set true and the defect recorded as
    `last_defect_type`."

    Design: Difficulty/boundary_precision_check/thickness_spec_inclusive_bounds
    """
    customer = create_customer(company_name="Mu Enclosures 2")
    create_compat_rule()
    bath = create_titrated_bath(bath_code="ANO-12B", routing_modes_supported=["BARREL"])
    wb, _lr = setup_awaiting_inspection(customer["id"], bath["id"], part_number="PN-120B")
    report = inspect_work_order(wb["id"], thickness_readings_um=[11.9, 15.0, 18.0],
                                defect_type="NONE")
    assert report["thickness_min_um"] == 11.9
    assert report["thickness_ok"] is False
    assert report["disposition"] == "REWORKABLE_REJECT"
    refreshed = get_work_order(wb["id"])
    assert refreshed["status"] == "REJECTED"
    assert refreshed["pending_strip"] is True


def test_discharge_limit_strict_greater_than_equality_compliant():
    """PRD §3.8: "A sample is an exceedance — `is_exceedance` true — when any reading's
    concentration is strictly greater than its limit's `max_concentration_mg_l`, or
    when any analyte's cumulative mass after adding the sample is strictly greater than
    its `monthly_mass_cap_g`; equality on either measure is compliant."

    Design: Difficulty/boundary_precision_check/discharge_limit_strict_greater_than
    """
    permit = create_permit(outfall_code="OUTFALL-13", effective_from="2026-08-01",
                           effective_to="2026-08-31",
                           limits=[{"analyte_code": "NICKEL", "max_concentration_mg_l": 2.0,
                                    "monthly_mass_cap_g": 500.0}])
    s1 = record_sample(permit["id"], flow_liters=10000,
                       readings=[{"analyte_code": "NICKEL", "concentration_mg_l": 2.0}])
    assert s1["is_exceedance"] is False  # exactly at the limit: compliant
    # 2.0 mg/L x 10000 L / 1000 = 20.0 g
    assert s1["masses_g"]["NICKEL"] == 20.0
    assert get_permit(permit["id"])["status"] == "ACTIVE"


def test_discharge_limit_strict_greater_than_over_limit_exceeds():
    """PRD §3.8: "A sample is an exceedance — `is_exceedance` true — when any reading's
    concentration is strictly greater than its limit's `max_concentration_mg_l`"
    PRD §3.8: "Recording an exceedance sample flips the permit from `ACTIVE` to
    `EXCEEDED`, sets `exceedance_active` true"

    Design: Difficulty/boundary_precision_check/discharge_limit_strict_greater_than
    """
    permit = create_permit(outfall_code="OUTFALL-13B", effective_from="2026-08-01",
                           effective_to="2026-08-31",
                           limits=[{"analyte_code": "NICKEL", "max_concentration_mg_l": 2.0,
                                    "monthly_mass_cap_g": 500.0}])
    s1 = record_sample(permit["id"], flow_liters=10000,
                       readings=[{"analyte_code": "NICKEL", "concentration_mg_l": 2.0}])
    assert s1["is_exceedance"] is False
    s2 = record_sample(permit["id"], flow_liters=10000,
                       readings=[{"analyte_code": "NICKEL", "concentration_mg_l": 2.001}])
    assert s2["is_exceedance"] is True  # strictly greater
    assert get_permit(permit["id"])["status"] == "EXCEEDED"


def test_waste_mass_per_sample_rounding_before_summing():
    """PRD §3.8: "For each analyte reading, the sample's `masses_g` entry is the
    concentration in milligrams per liter multiplied by the flow in liters, divided by
    one thousand, rounded half-up to three decimal places — each per-analyte mass
    rounded first, and the monthly cumulative for that analyte is the plain sum of
    those already-rounded per-sample masses, never re-rounded and never computed as a
    sum-then-round."

    Design: Difficulty/combinatorial_formula/waste_mass_per_sample_rounding_mode_b
    """
    permit = create_permit(outfall_code="OUTFALL-9", effective_from="2026-08-01",
                           effective_to="2026-08-31",
                           limits=[{"analyte_code": "NICKEL", "max_concentration_mg_l": 2.0,
                                    "monthly_mass_cap_g": 500.0}])
    # 0.0005 mg/L x 1000 L / 1000 = 0.0005 -> rounded half-up per-sample to 0.001.
    s1 = record_sample(permit["id"], flow_liters=1000,
                       readings=[{"analyte_code": "NICKEL", "concentration_mg_l": 0.0005}])
    assert s1["masses_g"]["NICKEL"] == 0.001
    assert s1["is_exceedance"] is False
    record_sample(permit["id"], flow_liters=1000,
                  readings=[{"analyte_code": "NICKEL", "concentration_mg_l": 0.0005}])
    detail = get_permit(permit["id"])
    # Round-then-sum: 0.001 + 0.001 = 0.002 (sum-then-round would give 0.001).
    assert detail["cumulative_mass_g"]["NICKEL"] == 0.002
    assert detail["status"] == "ACTIVE"
    assert detail["current_month"] == "2026-08"


def test_waste_mass_rounding_keeps_permit_active_under_cap():
    """PRD §3.8: "when the sample's month equals `current_month`, each analyte's
    rounded mass accumulates into the running totals"
    PRD §3.8: "equality on either measure is compliant"

    Design: Difficulty/combinatorial_formula/waste_mass_per_sample_rounding_mode_b
    """
    permit = create_permit(outfall_code="OUTFALL-9B", effective_from="2026-08-01",
                           effective_to="2026-08-31",
                           limits=[{"analyte_code": "NICKEL", "max_concentration_mg_l": 2.0,
                                    "monthly_mass_cap_g": 500.0}])
    s = record_sample(permit["id"], flow_liters=1000,
                      readings=[{"analyte_code": "NICKEL", "concentration_mg_l": 0.0005}])
    assert s["is_exceedance"] is False
    s2 = record_sample(permit["id"], flow_liters=1000,
                       readings=[{"analyte_code": "NICKEL", "concentration_mg_l": 0.0005}])
    assert s2["is_exceedance"] is False
    detail = get_permit(permit["id"])
    assert detail["status"] == "ACTIVE"
    assert detail["current_month"] == "2026-08"
