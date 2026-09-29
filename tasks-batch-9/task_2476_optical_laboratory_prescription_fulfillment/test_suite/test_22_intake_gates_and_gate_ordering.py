"""Compatibility gates, boundary satisfaction and the order the gates fire in."""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import factories as f, fixtures
from test_helpers.api_errors import ApiErrorId
from test_helpers.test_users import (
    BENEFITS_A_HEADERS,
    MANAGER_A_HEADERS,
    OPTICIAN_A_HEADERS,
    TECHNICIAN_A_HEADERS,
)

FUTURE_ISSUE_DATE = "2026-08-02"
PRIOR_AUTH_REFERENCE = "PA-2026-118"
SPECIALTY_GROSS = 63490
SPECIALTY_BENEFIT = 16495
TIGHT_CAP_CENTS = 19995
OVERSIZED_TRACE = {"a_mm": 58.0, "b_mm": 28.0, "ed_mm": 62.0, "dbl_mm": 20.0}


def _draft_order_with_a_low_fitting_height(api):
    """A progressive order traced at 10.0 mm against an 18.0 mm design minimum."""
    fixtures.set_clock(api)
    prescriber = fixtures.create_prescriber(api)
    patient = fixtures.create_self_pay_patient(api)
    design = fixtures.create_progressive_design(api)
    scenario = {
        "prescriber_id": prescriber["id"],
        "patient_id": patient["id"],
        "design_id": design["id"],
    }
    scenario = fixtures.surfaced_verified_prescription(api, scenario)
    assert design["min_fitting_height_mm"] == 18.0
    order = validate_success(
        api.create_rx_order(
            f.create_progressive_rx_order_payload(
                scenario["patient_id"],
                scenario["prescription_id"],
                scenario["design_id"],
                fitting_height_mm=10.0,
            ),
            OPTICIAN_A_HEADERS,
        ),
        expected_status=201,
    )
    scenario["order_id"] = order["id"]
    scenario["order_version"] = order["version"]
    return scenario


def _specialty_plan_order_payload(api):
    """An insured specialty order that the plan wants authorised."""
    fixtures.set_clock(api)
    prescriber = fixtures.create_prescriber(api)
    plan = fixtures.create_basic_plan(api, plan_code="SPEC-AUTH")
    assert plan["specialty_requires_prior_auth"] is True
    patient = fixtures.create_insured_patient(api, plan["id"])
    design = validate_success(
        api.create_lens_design(
            f.create_lens_design_payload(
                design_code="SPEC-PRISM",
                design_type="SPECIALTY",
                material="TRIVEX",
                allowed_coatings=["HARDCOAT"],
                retail_price_cents=45995,
                min_fitting_height_mm=18.0,
                min_blank_diameter_mm=70.0,
                product_tier="ECONOMY",
                stock_sku_available=False,
                base_curve=4.0,
            ),
            MANAGER_A_HEADERS,
        ),
        expected_status=201,
    )
    scenario = {
        "prescriber_id": prescriber["id"],
        "plan_id": plan["id"],
        "patient_id": patient["id"],
        "design_id": design["id"],
    }
    scenario = fixtures.stock_verified_prescription(api, scenario)
    payload = f.create_rx_order_payload(
        scenario["patient_id"], scenario["prescription_id"], scenario["design_id"]
    )
    payload["frame_sku"] = "FRM-X40"
    payload["frame_retail_cents"] = 15000
    payload["requested_coatings"] = ["HARDCOAT"]
    payload["fitting_height_mm"] = 22.0
    return scenario, payload


def _order_whose_layout_needs_a_ninety_millimetre_blank(api):
    """A wide trace on a progressive design, with no blank lot on the shelf."""
    fixtures.set_clock(api)
    prescriber = fixtures.create_prescriber(api)
    patient = fixtures.create_self_pay_patient(api)
    design = fixtures.create_progressive_design(api)
    scenario = {
        "prescriber_id": prescriber["id"],
        "patient_id": patient["id"],
        "design_id": design["id"],
    }
    scenario = fixtures.surfaced_verified_prescription(api, scenario)
    order = validate_success(
        api.create_rx_order(
            f.create_progressive_rx_order_payload(
                scenario["patient_id"],
                scenario["prescription_id"],
                scenario["design_id"],
                monocular_pd_od_mm=30.0,
                monocular_pd_os_mm=30.0,
                fitting_height_mm=22.0,
            ),
            OPTICIAN_A_HEADERS,
        ),
        expected_status=201,
    )
    scenario["order_id"] = order["id"]
    scenario["order_version"] = order["version"]
    layout = validate_success(
        api.create_frame_layout(
            f.create_progressive_frame_layout_payload(
                scenario["order_id"], scenario["order_version"], **OVERSIZED_TRACE
            ),
            OPTICIAN_A_HEADERS,
        ),
        expected_status=201,
    )
    scenario["layout"] = layout
    scenario["layout_id"] = layout["id"]
    return scenario


def test_a_coating_the_design_does_not_offer_is_refused(api):
    """POLARIZED is a real coating, just not one this design carries.

    PRD 3.3: "Every coating in `requested_coatings` must appear in the design's
    `allowed_coatings`; a coating the design does not offer yields
    `ERR_COATING_NOT_AVAILABLE_FOR_DESIGN`."

    Design: Corner/validations/coating_not_offered_by_the_design_is_refused
    """
    scenario = fixtures.stock_verified_prescription(api)

    validate_error(
        api.create_rx_order(
            f.create_rx_order_payload(
                scenario["patient_id"],
                scenario["prescription_id"],
                scenario["design_id"],
                requested_coatings=["POLARIZED"],
            ),
            OPTICIAN_A_HEADERS,
        ),
        ApiErrorId.COATING_NOT_AVAILABLE_FOR_DESIGN.value,
        422,
    )

    rows, meta = validate_paginated(
        api.list_rx_orders(OPTICIAN_A_HEADERS, {"patient_id": scenario["patient_id"]})
    )
    assert rows == []
    assert meta["total_count"] == 0
    assert (
        fixtures.read_prescription(api, scenario["prescription_id"])[
            "verification_status"
        ]
        == "VERIFIED"
    )


def test_a_monocular_pair_exactly_one_millimetre_off_is_accepted(api):
    """The gate fires above 1.0 mm, so a gap of exactly 1.0 mm passes.

    PRD 3.3: "The two monocular measurements must be consistent with the prescribed
    binocular figure: if the absolute difference between the sum of
    `monocular_pd_od_mm` and `monocular_pd_os_mm` and the prescription's
    `pd_distance_mm` is greater than 1.0 millimetre, the response is
    `ERR_MONOCULAR_PD_INCONSISTENT`. A difference of exactly 1.0 millimetre is
    accepted."

    Design: Corner/validations/monocular_pd_sum_exactly_one_millimetre_off_the_binocular_pd_passes
    """
    scenario = fixtures.stock_verified_prescription(api, pd_distance_mm=62.0)

    order = validate_success(
        api.create_rx_order(
            f.create_rx_order_payload(
                scenario["patient_id"],
                scenario["prescription_id"],
                scenario["design_id"],
                monocular_pd_od_mm=31.0,
                monocular_pd_os_mm=30.0,
            ),
            OPTICIAN_A_HEADERS,
        ),
        expected_status=201,
    )

    assert order["monocular_pd_od_mm"] == 31.0
    assert order["monocular_pd_os_mm"] == 30.0
    assert order["fulfillment_status"] == "DRAFT"
    assert order["gross_charge_cents"] == 26985


def test_a_nonsense_trace_is_reported_as_a_nonsense_trace(api):
    """The 35.0 mm effective diameter answers first, not the 10.0 mm fitting height.

    PRD 3.4: "Ordering the dimension gate above the fitting-height gate is deliberate;
    a nonsense trace should be reported as a nonsense trace, not as a design-minimum
    violation computed from it."

    Design: Corner/validations/trace_range_outranks_the_fitting_height_minimum_on_one_layout_call
    """
    scenario = _draft_order_with_a_low_fitting_height(api)

    validate_error(
        api.create_frame_layout(
            f.create_progressive_frame_layout_payload(
                scenario["order_id"], scenario["order_version"], ed_mm=35.0
            ),
            OPTICIAN_A_HEADERS,
        ),
        ApiErrorId.TRACE_DIMENSIONS_OUT_OF_RANGE.value,
        400,
    )

    order = fixtures.read_order(api, scenario["order_id"])
    assert order["fulfillment_status"] == "DRAFT"
    assert order["version"] == 1


def test_the_fitting_height_minimum_still_answers_a_sane_trace(api):
    """With the geometry legal, the losing gate becomes reachable.

    PRD 3.4: "Fourth, and only once the dimensions are known to be sane, the
    fitting-height gate: if the effective fitting height is below the design's
    `min_fitting_height_mm`, the response is
    `ERR_FITTING_HEIGHT_BELOW_DESIGN_MINIMUM`."

    Design: Corner/validations/trace_range_outranks_the_fitting_height_minimum_on_one_layout_call
    """
    scenario = _draft_order_with_a_low_fitting_height(api)
    validate_error(
        api.create_frame_layout(
            f.create_progressive_frame_layout_payload(
                scenario["order_id"], scenario["order_version"], ed_mm=35.0
            ),
            OPTICIAN_A_HEADERS,
        ),
        ApiErrorId.TRACE_DIMENSIONS_OUT_OF_RANGE.value,
        400,
    )

    validate_error(
        api.create_frame_layout(
            f.create_progressive_frame_layout_payload(
                scenario["order_id"], scenario["order_version"]
            ),
            OPTICIAN_A_HEADERS,
        ),
        ApiErrorId.FITTING_HEIGHT_BELOW_DESIGN_MINIMUM.value,
        422,
    )

    order = fixtures.read_order(api, scenario["order_id"])
    assert order["fulfillment_status"] == "DRAFT"
    assert order["version"] == 1
    _, meta = validate_paginated(
        api.list_order_frame_layouts(scenario["order_id"], OPTICIAN_A_HEADERS)
    )
    assert meta["total_count"] == 0


def test_an_add_power_prescription_cannot_be_filled_single_vision(api):
    """Both rows are individually valid; only the pairing is refused.

    PRD 3.3: "A multifocal prescription cannot be filled with a single-vision lens:
    when the prescription's `requires_multifocal` is true and the design's
    `design_type` is `SINGLE_VISION`, the response is
    `ERR_DESIGN_INCOMPATIBLE_WITH_RX`."

    Design: Corner/validations/multifocal_prescription_on_a_single_vision_design_is_refused
    """
    scenario = fixtures.stock_verified_prescription(api, add_power=2.0)
    prescription = fixtures.read_prescription(api, scenario["prescription_id"])
    assert prescription["requires_multifocal"] is True
    assert prescription["add_power_od"] == 2.0
    assert prescription["add_power_os"] == 2.0

    validate_error(
        api.create_rx_order(
            f.create_rx_order_payload(
                scenario["patient_id"],
                scenario["prescription_id"],
                scenario["design_id"],
            ),
            OPTICIAN_A_HEADERS,
        ),
        ApiErrorId.DESIGN_INCOMPATIBLE_WITH_RX.value,
        422,
    )

    _, meta = validate_paginated(
        api.list_rx_orders(OPTICIAN_A_HEADERS, {"patient_id": scenario["patient_id"]})
    )
    assert meta["total_count"] == 0


def test_an_issue_date_after_the_logical_clock_is_refused(api):
    """Tomorrow's paper prescription cannot be transcribed today.

    PRD 3.2: "Third, the issue-date check: an `issued_on` later than the logical
    clock's UTC date is rejected with `ERR_RX_ISSUE_DATE_IN_FUTURE`."

    Design: Corner/validations/prescription_issued_after_the_logical_clock_is_refused
    """
    fixtures.set_clock(api)
    prescriber = fixtures.create_prescriber(api)
    patient = fixtures.create_self_pay_patient(api)

    validate_error(
        api.create_prescription(
            f.create_prescription_payload(
                patient["id"], prescriber["id"], issued_on=FUTURE_ISSUE_DATE
            ),
            OPTICIAN_A_HEADERS,
        ),
        ApiErrorId.RX_ISSUE_DATE_IN_FUTURE.value,
        400,
    )

    _, meta = validate_paginated(
        api.list_prescriptions(OPTICIAN_A_HEADERS, {"patient_id": patient["id"]})
    )
    assert meta["total_count"] == 0
    assert fixtures.read_prescriber(api, prescriber["id"])["verified_rx_count"] == 0


def test_a_second_application_is_refused_once_the_cap_is_consumed(api):
    """The first order took the whole 19995-cent cap, so the second gets nothing.

    PRD 3.9: "Three gates apply in order: `billing_status` must be
    `PROVISIONAL_QUOTED` or `BENEFIT_VOIDED`, and anything else yields
    `ERR_BILLING_STATE_INVALID`; the order must have a lab job whose `status` is not
    `SCRAPPED`, because without a known `route` neither the surfacing surcharge nor the
    surfacing turnaround penalty is determined, and the absence of one yields
    `ERR_ROUTE_NOT_DETERMINED`; and for a patient attached to a plan, the annual cap
    must not be fully consumed, with a zero remaining cap yielding
    `ERR_BENEFIT_CAP_EXHAUSTED`."

    Design: Corner/validations/second_order_is_refused_once_the_annual_cap_is_fully_consumed
    """
    scenario = fixtures.near_cap_insured_scenario(api, TIGHT_CAP_CENTS)
    assert scenario["first_order"]["insurance_benefit_cents"] == TIGHT_CAP_CENTS
    scenario = fixtures.second_order_on_same_prescription(api, scenario)
    second_before = fixtures.read_order(api, scenario["second_order_id"])
    assert second_before["estimated_benefit_cents"] == TIGHT_CAP_CENTS

    validate_error(
        api.apply_benefit(scenario["second_order_id"], BENEFITS_A_HEADERS),
        ApiErrorId.BENEFIT_CAP_EXHAUSTED.value,
        422,
    )

    second = fixtures.read_order(api, scenario["second_order_id"])
    assert second["billing_status"] == "PROVISIONAL_QUOTED"
    assert second["quote_variant"] == "PROVISIONAL"
    assert second["insurance_benefit_cents"] == 0
    assert second["patient_portion_cents"] == 6990
    assert fixtures.read_patient(api, scenario["patient_id"])["benefit_used_cents"] == (
        TIGHT_CAP_CENTS
    )
    _, meta = validate_paginated(
        api.list_order_settlement_entries(
            scenario["second_order_id"], BENEFITS_A_HEADERS
        )
    )
    assert meta["total_count"] == 0


def test_a_specialty_order_without_an_authorisation_reference_is_refused(api):
    """All three conditions hold at once: specialty design, demanding plan, null field.

    PRD 3.3: "Finally, prior authorisation: when the design's `design_type` is
    `SPECIALTY`, the patient is attached to a plan whose `specialty_requires_prior_auth`
    is true, and `prior_auth_reference` is null, the response is
    `ERR_PRIOR_AUTH_REQUIRED`. A self-pay patient never needs a prior-authorisation
    reference, and neither does a plan that does not demand one."

    Design: Corner/validations/specialty_design_needs_a_prior_auth_reference_only_when_the_plan_demands_one
    """
    scenario, payload = _specialty_plan_order_payload(api)

    validate_error(
        api.create_rx_order(payload, OPTICIAN_A_HEADERS),
        ApiErrorId.PRIOR_AUTH_REQUIRED.value,
        422,
    )

    _, meta = validate_paginated(
        api.list_rx_orders(OPTICIAN_A_HEADERS, {"patient_id": scenario["patient_id"]})
    )
    assert meta["total_count"] == 0


def test_the_same_specialty_order_succeeds_once_the_reference_is_supplied(api):
    """One added field turns the refusal into a 16495-cent projection.

    PRD 3.9: "The uncapped benefit is the sum of all component allowances plus the sum
    of all per-component coinsurance contributions, plus `expedite_fee_cents` in full
    when the plan's `expedite_covered` is true."

    Design: Corner/validations/specialty_design_needs_a_prior_auth_reference_only_when_the_plan_demands_one
    """
    scenario, payload = _specialty_plan_order_payload(api)
    validate_error(
        api.create_rx_order(payload, OPTICIAN_A_HEADERS),
        ApiErrorId.PRIOR_AUTH_REQUIRED.value,
        422,
    )

    payload["prior_auth_reference"] = PRIOR_AUTH_REFERENCE
    order = validate_success(
        api.create_rx_order(payload, OPTICIAN_A_HEADERS), expected_status=201
    )

    assert order["prior_auth_reference"] == PRIOR_AUTH_REFERENCE
    assert order["gross_charge_cents"] == SPECIALTY_GROSS
    assert order["estimated_benefit_cents"] == SPECIALTY_BENEFIT
    assert order["patient_portion_cents"] == SPECIALTY_GROSS - SPECIALTY_BENEFIT
    assert order["product_tier"] == "ECONOMY"
    assert order["promised_tat_hours"] == 120
    assert order["insurance_benefit_cents"] == 0
    assert order["quote_variant"] == "PROVISIONAL"

    _, meta = validate_paginated(
        api.list_rx_orders(OPTICIAN_A_HEADERS, {"patient_id": scenario["patient_id"]})
    )
    assert meta["total_count"] == 1


def test_an_unusable_layout_answers_before_the_empty_shelf_does(api):
    """The 90.0 mm requirement is refused as a layout fault, not as missing stock.

    PRD 3.5: "Third, the layout-usability gate: if the order's newest layout has
    `layout_status` of `BLANK_TOO_SMALL` or `SUPERSEDED`, or the order has no layout at
    all, the response is `ERR_LAYOUT_NOT_USABLE`."

    Design: Corner/validations/unusable_layout_blocks_job_creation_before_the_blank_search_can_fail
    """
    scenario = _order_whose_layout_needs_a_ninety_millimetre_blank(api)
    assert scenario["layout"]["required_blank_diameter_mm"] == 90.0
    assert scenario["layout"]["layout_status"] == "BLANK_TOO_SMALL"
    order_before = fixtures.read_order(api, scenario["order_id"])
    assert order_before["fulfillment_status"] == "LAYOUT_READY"
    assert order_before["version"] == 2

    error = validate_error(
        api.create_lab_job(
            f.create_lab_job_payload(scenario["order_id"]), TECHNICIAN_A_HEADERS
        ),
        ApiErrorId.LAYOUT_NOT_USABLE.value,
        422,
    )
    assert error["error_id"] != ApiErrorId.NO_ELIGIBLE_BLANK_LOT.value

    _, meta = validate_paginated(
        api.list_lab_jobs(TECHNICIAN_A_HEADERS, {"rx_order_id": scenario["order_id"]})
    )
    assert meta["total_count"] == 0
