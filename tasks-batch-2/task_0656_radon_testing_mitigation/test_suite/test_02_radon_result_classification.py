"""Recording a radon result: the CONTINUOUS_MONITOR valid-hours mean (warm-up
hours dropped) vs the naive all-hours mean, the inclusive 4.0 pCi/L action-level
boundary, and the empty-valid-set rejection on retrieve.
"""
import pytest
from test_helpers import (
    api_client, validate_success, validate_error, get_success_data,
    create_inspector, create_property, set_clock, get_property,
    create_radon_test_payload, retrieve_continuous_payload,
    retrieve_short_term_payload, make_inspector_headers,
    CLOCK_AFTER_48H, ApiErrorId,
)


def test_continuous_monitor_uses_valid_hours_mean_not_all_hours(api):
    """PRD §3.3: "the first `warmup_hours_dropped` entries of `hourly_readings`
    are discarded as warm-up, the remaining readings are summed and divided by
    the count of those remaining readings, and that quotient is rounded half up
    to one decimal place."
    PRD §3.3: "averaging every reading including the leading warm-up hours is
    incorrect, because elevated warm-up spikes can push the all-hours mean from
    below 4.0 (where the valid-hours mean sits) to at or above 4.0, flipping the
    outcome."

    Design: Difficulty/dual_variant_calc/dvc_continuous_monitor_valid_vs_all_hours_mean
    """
    inspector = create_inspector()
    insp = make_inspector_headers(inspector["id"])
    prop = create_property(foundation_type="BASEMENT", floor_area_sqft=2200)
    test = get_success_data(api.create_radon_test(
        create_radon_test_payload(prop["id"], inspector["id"],
                                  test_kind="CONTINUOUS_MONITOR", purpose="INITIAL",
                                  placement_window_hours=48, warmup_hours_dropped=4),
        insp))
    set_clock(CLOCK_AFTER_48H)
    # 4 warm-up readings of 9.0 then 44 readings of 3.5.
    readings = [9, 9, 9, 9] + [3.5] * 44
    api.retrieve_radon_test(test["id"], retrieve_continuous_payload(readings), insp)
    result = validate_success(api.record_result(test["id"], insp), 200)
    assert result["result_pci_l"] == 3.5
    assert result["action_outcome"] == "NO_ACTION"


def test_continuous_monitor_valid_hours_result_drives_property_latest(api):
    """PRD §3.3: "For a `CONTINUOUS_MONITOR` test, the result is the mean of the
    **valid** hourly readings: the first `warmup_hours_dropped` entries of
    `hourly_readings` are discarded as warm-up, the remaining readings are summed
    and divided by the count of those remaining readings, and that quotient is
    rounded half up to one decimal place."
    PRD §2.6: "a computed `latest_result_pci_l` (the `result_pci_l` of the most
    recent `RESULT_READY` test on that property, taken by `created_at`
    descending, or null when none exists)."

    Design: Difficulty/dual_variant_calc/dvc_continuous_monitor_valid_vs_all_hours_mean
    """
    inspector = create_inspector()
    insp = make_inspector_headers(inspector["id"])
    prop = create_property(foundation_type="BASEMENT", floor_area_sqft=2200)
    test = get_success_data(api.create_radon_test(
        create_radon_test_payload(prop["id"], inspector["id"],
                                  test_kind="CONTINUOUS_MONITOR", purpose="INITIAL",
                                  placement_window_hours=48, warmup_hours_dropped=4),
        insp))
    set_clock(CLOCK_AFTER_48H)
    readings = [9, 9, 9, 9] + [3.5] * 44
    api.retrieve_radon_test(test["id"], retrieve_continuous_payload(readings), insp)
    validate_success(api.record_result(test["id"], insp), 200)
    prop_now = get_property(prop["id"])
    assert prop_now["latest_result_pci_l"] == 3.5


def test_action_level_inclusive_at_exactly_4_0(api):
    """PRD §3.3: "The boundary is inclusive: when `result_pci_l` is at least 4.0
    the outcome is `ACTION_RECOMMENDED`, and when it is strictly below 4.0 (for
    example 3.9) the outcome is `NO_ACTION`."

    Design: Difficulty/boundary_precision_check/bpc_action_level_inclusive_4_0_on_record_result
    """
    inspector = create_inspector()
    insp = make_inspector_headers(inspector["id"])
    prop = create_property()
    test = get_success_data(api.create_radon_test(
        create_radon_test_payload(prop["id"], inspector["id"],
                                  test_kind="SHORT_TERM_48HR", purpose="INITIAL",
                                  placement_window_hours=48),
        insp))
    set_clock(CLOCK_AFTER_48H)
    api.retrieve_radon_test(test["id"], retrieve_short_term_payload(4.0), insp)
    result = validate_success(api.record_result(test["id"], insp), 200)
    assert result["result_pci_l"] == 4.0
    assert result["action_outcome"] == "ACTION_RECOMMENDED"


def test_action_level_below_4_0_is_no_action(api):
    """PRD §3.3: "The boundary is inclusive: when `result_pci_l` is at least 4.0
    the outcome is `ACTION_RECOMMENDED`, and when it is strictly below 4.0 (for
    example 3.9) the outcome is `NO_ACTION`."

    Design: Difficulty/boundary_precision_check/bpc_action_level_inclusive_4_0_on_record_result
    """
    inspector = create_inspector()
    insp = make_inspector_headers(inspector["id"])
    prop = create_property()
    test = get_success_data(api.create_radon_test(
        create_radon_test_payload(prop["id"], inspector["id"],
                                  test_kind="SHORT_TERM_48HR", purpose="INITIAL",
                                  placement_window_hours=48),
        insp))
    set_clock(CLOCK_AFTER_48H)
    api.retrieve_radon_test(test["id"], retrieve_short_term_payload(3.9), insp)
    result = validate_success(api.record_result(test["id"], insp), 200)
    assert result["result_pci_l"] == 3.9
    assert result["action_outcome"] == "NO_ACTION"


def test_continuous_retrieve_empty_after_warmup_rejected(api):
    """PRD §3.2: "A `CONTINUOUS_MONITOR` retrieval supplies `hourly_readings`, an
    array of hourly pCi/L numbers, and the array must contain strictly more
    entries than `warmup_hours_dropped` (otherwise `ERR_INSUFFICIENT_READINGS`)."

    Design: Difficulty/boundary_precision_check/bpc_continuous_readings_empty_after_warmup_on_retrieve
    """
    inspector = create_inspector()
    insp = make_inspector_headers(inspector["id"])
    prop = create_property()
    test = get_success_data(api.create_radon_test(
        create_radon_test_payload(prop["id"], inspector["id"],
                                  test_kind="CONTINUOUS_MONITOR", purpose="INITIAL",
                                  placement_window_hours=48, warmup_hours_dropped=4),
        insp))
    set_clock(CLOCK_AFTER_48H)
    # Exactly 4 readings == warmup_hours_dropped → valid set is empty.
    res = api.retrieve_radon_test(test["id"],
                                  retrieve_continuous_payload([5.0, 5.0, 5.0, 5.0]),
                                  insp)
    validate_error(res, ApiErrorId.ERR_INSUFFICIENT_READINGS.value)


def test_continuous_retrieve_at_warmup_count_leaves_test_placed(api):
    """PRD §3.2: "the array must contain strictly more entries than
    `warmup_hours_dropped` (otherwise `ERR_INSUFFICIENT_READINGS`)."
    PRD §3.2: "Retrieval is the inspector's act of collecting the device and
    supplying its data, moving the test from `PLACED` to `RETRIEVED`."

    Design: Difficulty/boundary_precision_check/bpc_continuous_readings_empty_after_warmup_on_retrieve
    """
    inspector = create_inspector()
    insp = make_inspector_headers(inspector["id"])
    prop = create_property()
    test = get_success_data(api.create_radon_test(
        create_radon_test_payload(prop["id"], inspector["id"],
                                  test_kind="CONTINUOUS_MONITOR", purpose="INITIAL",
                                  placement_window_hours=48, warmup_hours_dropped=4),
        insp))
    set_clock(CLOCK_AFTER_48H)
    validate_error(
        api.retrieve_radon_test(test["id"],
                                retrieve_continuous_payload([5.0, 5.0, 5.0, 5.0]),
                                insp),
        ApiErrorId.ERR_INSUFFICIENT_READINGS.value)
    # The rejected retrieve did not transition the test out of PLACED.
    fetched = validate_success(api.get_radon_test(test["id"], insp), 200)
    assert fetched["status"] == "PLACED"
