"""Payload factories — one per entity, input fields only."""

DEFAULTS = {
    "MEASUREMENT_YEAR": 2026,
    "RATING_YEAR": 2028,
    "BENCHMARK_PMPM": 950.0,
    "PLAN_CONTRACT": "H1234",
    "ENROLLED_MONTHS": 12,
    "TARGET_STAR": 5,
    "UNIT_REWARD_PER_GAP": 250.0,
    "MAX_POOL_AMOUNT": 10000.0,
    "SAMPLE_SIZE": 100,
}


def create_rating_cycle_payload(measurement_year=DEFAULTS["MEASUREMENT_YEAR"],
                                rating_year=DEFAULTS["RATING_YEAR"],
                                benchmark_pmpm=DEFAULTS["BENCHMARK_PMPM"],
                                **overrides) -> dict:
    payload = {
        "measurement_year": measurement_year,
        "rating_year": rating_year,
        "benchmark_pmpm": benchmark_pmpm,
    }
    payload.update(overrides)
    return payload


def create_measure_payload(rating_cycle_id, code="BCS", title=None,
                           domain="STAYING_HEALTHY", measure_type="PROCESS",
                           direction="HIGHER_BETTER", data_source="HEDIS",
                           improvement_eligible=False, prior_cycle_star=None,
                           **overrides) -> dict:
    payload = {
        "rating_cycle_id": rating_cycle_id,
        "code": code,
        "title": title if title is not None else f"Measure {code}",
        "domain": domain,
        "measure_type": measure_type,
        "direction": direction,
        "data_source": data_source,
        "improvement_eligible": improvement_eligible,
    }
    if prior_cycle_star is not None:
        payload["prior_cycle_star"] = prior_cycle_star
    payload.update(overrides)
    return payload


def cutpoint_row(measure_id, band_2_floor, band_3_floor, band_4_floor,
                 band_5_floor) -> dict:
    return {
        "measure_id": measure_id,
        "band_2_floor": band_2_floor,
        "band_3_floor": band_3_floor,
        "band_4_floor": band_4_floor,
        "band_5_floor": band_5_floor,
    }


def create_cutpoint_set_payload(rating_cycle_id, label="draft-2028", rows=None,
                                **overrides) -> dict:
    payload = {
        "rating_cycle_id": rating_cycle_id,
        "label": label,
        "rows": rows if rows is not None else [],
    }
    payload.update(overrides)
    return payload


def create_measure_performance_payload(rating_cycle_id, measure_id, numerator,
                                       denominator, exclusion_count=None,
                                       **overrides) -> dict:
    payload = {
        "rating_cycle_id": rating_cycle_id,
        "measure_id": measure_id,
        "numerator": numerator,
        "denominator": denominator,
    }
    if exclusion_count is not None:
        payload["exclusion_count"] = exclusion_count
    payload.update(overrides)
    return payload


def create_member_payload(member_ref, plan_contract=DEFAULTS["PLAN_CONTRACT"],
                          enrolled_months=DEFAULTS["ENROLLED_MONTHS"],
                          **overrides) -> dict:
    payload = {
        "member_ref": member_ref,
        "plan_contract": plan_contract,
        "enrolled_months": enrolled_months,
    }
    payload.update(overrides)
    return payload


def create_care_gap_payload(member_id, measure_id, gap_type="SCREENING",
                            **overrides) -> dict:
    payload = {
        "member_id": member_id,
        "measure_id": measure_id,
        "gap_type": gap_type,
    }
    payload.update(overrides)
    return payload


def create_provider_group_payload(name, program_type, linked_measure_id,
                                  target_star=DEFAULTS["TARGET_STAR"],
                                  unit_reward_per_gap=DEFAULTS["UNIT_REWARD_PER_GAP"],
                                  max_pool_amount=DEFAULTS["MAX_POOL_AMOUNT"],
                                  **overrides) -> dict:
    payload = {
        "name": name,
        "program_type": program_type,
        "linked_measure_id": linked_measure_id,
        "target_star": target_star,
        "unit_reward_per_gap": unit_reward_per_gap,
        "max_pool_amount": max_pool_amount,
    }
    payload.update(overrides)
    return payload


def create_incentive_payout_payload(provider_group_id, **overrides) -> dict:
    payload = {"provider_group_id": provider_group_id}
    payload.update(overrides)
    return payload


def create_survey_vendor_payload(name, max_concurrent_waves=5, **overrides) -> dict:
    payload = {"name": name, "max_concurrent_waves": max_concurrent_waves}
    payload.update(overrides)
    return payload


def create_survey_wave_payload(rating_cycle_id, survey_type, vendor_id,
                              window_start, window_end,
                              sample_size=DEFAULTS["SAMPLE_SIZE"],
                              **overrides) -> dict:
    payload = {
        "rating_cycle_id": rating_cycle_id,
        "survey_type": survey_type,
        "vendor_id": vendor_id,
        "window_start": window_start,
        "window_end": window_end,
        "sample_size": sample_size,
    }
    payload.update(overrides)
    return payload


def create_complaint_case_payload(rating_cycle_id, member_id, category="BILLING",
                                  filed_at="2026-08-01T00:00:00Z",
                                  **overrides) -> dict:
    payload = {
        "rating_cycle_id": rating_cycle_id,
        "member_id": member_id,
        "category": category,
        "filed_at": filed_at,
    }
    payload.update(overrides)
    return payload


def create_rating_forecast_payload(rating_cycle_id, basis="DRAFT_CUTPOINTS",
                                   **overrides) -> dict:
    payload = {"rating_cycle_id": rating_cycle_id, "basis": basis}
    payload.update(overrides)
    return payload
