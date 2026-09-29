"""Computed read-throughs, cross-referenced links, conditional actions and the clock."""

from __future__ import annotations

import pytest

from test_helpers import (
    CERTIFICATION_AGENCY_ID,
    NON_EXISTENT_UUID,
    TEST_DEFAULTS,
    THRESHOLDS,
    assert_conditioning_run,
    assert_eligibility_assessment,
    assert_harvest_equipment,
    assert_lot_sample,
    bagged_lot_state,
    cleanout_certification_payload,
    create_conditioning_run_payload,
    create_eligibility_assessment_payload,
    create_lot_sample_payload,
    create_production_contract_payload,
    get_success_data,
    harvested_lot_state,
    make_certification_agency_headers,
    make_conditioning_manager_headers,
    make_field_history_record,
    make_field_officer_headers,
    make_grower,
    make_harvest_equipment,
    make_production_field,
    make_program_admin_headers,
    make_treatment_product,
    make_variety,
    run_stage,
    set_clock,
    set_clock_payload,
    treatment_label_text,
    validate_error,
    validate_paginated,
    validate_success,
)

SHORTFALL_FIELD_CODE = "F-South-4"
SHORTFALL_ISOLATION_DISTANCE_M = 150.0
EXPECTED_SHORTFALL_M = 50.0
RESTRICTED_CROP_YEARS = (2024, 2025)
EXPECTED_RESTRICTED_RECORD_COUNT = 2
EXPECTED_HISTORY_COMPONENT = 75.00
EXPECTED_ISOLATION_COMPONENT = 25.00
EXPECTED_RISK_SCORE = 100.00
COMMERCIAL_CLASS = "COMMERCIAL_INCREASE"


def _field_failing_history_and_isolation(api):
    """A field 50 m short on isolation that also carries two restricted wheat crops."""
    variety = make_variety(api)
    grower = make_grower(api)
    field = make_production_field(
        api,
        grower["id"],
        field_code=SHORTFALL_FIELD_CODE,
        isolation_distance_m=SHORTFALL_ISOLATION_DISTANCE_M,
    )
    for crop_year in RESTRICTED_CROP_YEARS:
        make_field_history_record(
            api, field["id"], crop_kind=TEST_DEFAULTS["CROP_KIND"], crop_year=crop_year
        )
    return {"variety": variety, "grower": grower, "field": field}


class TestEligibilityAssessmentReportsBothVariants:
    def test_the_assessment_reports_every_component_and_both_verdicts_at_once(self, api):
        """Two decayed records and a metre shortfall sum to a score both variants refuse.

        PRD: "Both a `ProgramAdmin` and a `FieldOfficer` may also ask that question directly,
        without touching contract state, through a computed read-through assessment that names a
        candidate `variety_id`, `season_year` and `seed_class` against a field."

        PRD: "That assessment begins by selecting the field's **restricted history records**: every
        history record of the field whose `crop_kind` appears in the variety's
        `restricted_prior_crop_kinds` and whose `crop_year` is strictly greater than the season year
        minus the variety's `restricted_prior_crop_years`."

        PRD: "The assessment then computes the **isolation shortfall in metres** as the variety's
        `isolation_min_m` minus the field's `isolation_distance_m`, floored at zero so that a field
        with surplus isolation reports a shortfall of exactly 0."

        PRD: "Under the **strict history** variant, the field is ineligible if it carries even one
        restricted record inside the look-back window, no matter how long ago that crop was grown;
        if there is no restricted record but the isolation shortfall is greater than zero, the field
        is also ineligible; otherwise it is eligible."

        PRD: "Each restricted record contributes a history component of 100.0 multiplied by one half
        raised to the power of the number of elapsed years, where the elapsed years are the season
        year minus that record's crop year, and each record's contribution is rounded half-up to two
        decimal places before it is added in."

        PRD: "A record from the season year itself therefore contributes the full 100.00, a record
        one year old contributes 50.00, a record two years old contributes 25.00, and so on."

        PRD: "The isolation component is the isolation shortfall in metres multiplied by 0.5 risk
        points per metre, rounded half-up to two decimal places."

        PRD: "When the decay-weighted verdict is ineligible, the blocking error is
        `ERR_FIELD_HISTORY_RESTRICTED` if the history component is strictly greater than the
        isolation component, and `ERR_ISOLATION_DISTANCE_INSUFFICIENT` otherwise; when the verdict
        is eligible there is no blocking error."

        PRD: "Which variant actually binds is selected by the contract's `seed_class`: the strict
        history variant applies when the class is `FOUNDATION`, `REGISTERED` or `CERTIFIED`, and the
        decay weighted variant applies when the class is `COMMERCIAL_INCREASE`."

        PRD: "The read-through assessment response makes all of this explicit, returning
        `strict_history_result` and `decay_weighted_result` as the two variant verdicts,
        `restricted_record_count` as the number of restricted history records selected,
        `history_component`, `isolation_component` and `contamination_risk_score` as the
        decay-weighted intermediates, `isolation_shortfall_m` as the shortfall in metres,
        `applied_variant` as the variant the supplied class selects, `applied_result` as that
        variant's verdict, and `blocking_error_id` as the error the applied variant would raise, or
        null when the applied verdict is eligible."

        PRD: "Under this variant the field is eligible while the contamination risk score is at or
        below 25.00, and ineligible once it rises above 25.00."

        Design: Corner/endpoints/eligibility_assessment_computed_read_returns_both_variants
        """
        state = _field_failing_history_and_isolation(api)

        assessment = validate_success(
            api.create_eligibility_assessment(
                state["field"]["id"],
                create_eligibility_assessment_payload(
                    state["variety"]["id"], seed_class=COMMERCIAL_CLASS
                ),
                make_field_officer_headers(),
            ),
            200,
        )
        assert_eligibility_assessment(assessment)

        assert assessment["restricted_record_count"] == EXPECTED_RESTRICTED_RECORD_COUNT
        assert assessment["isolation_shortfall_m"] == pytest.approx(EXPECTED_SHORTFALL_M, abs=0.01)
        assert assessment["history_component"] == pytest.approx(
            EXPECTED_HISTORY_COMPONENT, abs=0.01
        )
        assert assessment["isolation_component"] == pytest.approx(
            EXPECTED_ISOLATION_COMPONENT, abs=0.01
        )
        assert assessment["contamination_risk_score"] == pytest.approx(
            EXPECTED_RISK_SCORE, abs=0.01
        )
        assert assessment["contamination_risk_score"] > THRESHOLDS["DECAY_ELIGIBILITY_MAX_SCORE"]

        assert assessment["strict_history_result"] == "INELIGIBLE"
        assert assessment["decay_weighted_result"] == "INELIGIBLE"
        assert assessment["applied_variant"] == "DECAY_WEIGHTED"
        assert assessment["applied_result"] == "INELIGIBLE"
        assert assessment["blocking_error_id"] == "ERR_FIELD_HISTORY_RESTRICTED"

    def test_the_read_through_touches_no_contract_but_stamps_the_field_score(self, api):
        """The assessment's one declared write is the field's score and version.

        PRD: "The assessment does not mutate any contract, but it is not entirely side-effect free:
        it writes the computed contamination risk score onto the field's `last_assessed_risk_score`
        and increments the field's `version` by 1."

        Design: Corner/endpoints/eligibility_assessment_computed_read_returns_both_variants
        """
        state = _field_failing_history_and_isolation(api)
        field_id = state["field"]["id"]
        contract = get_success_data(
            api.create_production_contract(
                create_production_contract_payload(
                    state["grower"]["id"],
                    state["variety"]["id"],
                    field_id,
                    seed_class=COMMERCIAL_CLASS,
                ),
                make_program_admin_headers(),
            )
        )

        before = get_success_data(api.get_production_field(field_id, make_field_officer_headers()))
        assert before["last_assessed_risk_score"] is None

        validate_success(
            api.create_eligibility_assessment(
                field_id,
                create_eligibility_assessment_payload(
                    state["variety"]["id"], seed_class=COMMERCIAL_CLASS
                ),
                make_program_admin_headers(),
            ),
            200,
        )

        after = get_success_data(api.get_production_field(field_id, make_field_officer_headers()))
        assert after["last_assessed_risk_score"] == pytest.approx(EXPECTED_RISK_SCORE, abs=0.01)
        assert after["version"] == before["version"] + 1

        unchanged = get_success_data(
            api.get_production_contract(contract["id"], make_program_admin_headers())
        )
        assert unchanged["status"] == "DRAFT"
        assert unchanged["version"] == contract["version"]
        assert unchanged["eligibility_variant_applied"] is None
        assert unchanged["eligibility_risk_score"] is None


class TestCleanoutCertificationLink:
    def test_the_certification_resolves_its_variety_before_it_stamps_the_machine(self, api):
        """An unknown variety leaves the machine dirty; the real one clears it by name.

        PRD: "A newly registered machine starts in `DIRTY` status with `cleanout_certified` false
        and both `last_cleanout_at` and `last_cleanout_variety_id` null; its `status` is one of
        `AVAILABLE`, `DIRTY` or `OUT_OF_SERVICE`."

        PRD: "A `cleaned_at` after the current logical clock instant is refused with
        `ERR_DATE_IN_FUTURE`, and an unresolvable variety reference is refused with
        `ERR_VARIETY_NOT_FOUND`."

        PRD: "A successful certification sets the machine's `status` to `AVAILABLE`, sets
        `cleanout_certified` to true, sets `last_cleanout_variety_id` to the supplied variety and
        `last_cleanout_at` to the supplied instant, and increments the machine's `version` by 1."

        PRD: "Harvest machines may be filtered by `last_cleanout_variety_id` and `status`."

        Design: Corner/endpoints/cleanout_certification_links_equipment_to_variety
        """
        variety = make_variety(api)
        equipment = make_harvest_equipment(api)
        set_clock(api, TEST_DEFAULTS["HARVEST_CLOCK"])

        assert equipment["status"] == "DIRTY"
        assert equipment["cleanout_certified"] is False
        assert equipment["last_cleanout_variety_id"] is None
        assert equipment["last_cleanout_at"] is None

        response = api.certify_equipment_cleanout(
            equipment["id"],
            cleanout_certification_payload(NON_EXISTENT_UUID),
            make_conditioning_manager_headers(),
        )
        validate_error(response, "ERR_VARIETY_NOT_FOUND", 404)

        still_dirty = get_success_data(
            api.get_harvest_equipment(equipment["id"], make_conditioning_manager_headers())
        )
        assert still_dirty["cleanout_certified"] is False
        assert still_dirty["status"] == "DIRTY"
        assert still_dirty["last_cleanout_variety_id"] is None
        assert still_dirty["version"] == equipment["version"]

        certified = validate_success(
            api.certify_equipment_cleanout(
                equipment["id"],
                cleanout_certification_payload(variety["id"]),
                make_conditioning_manager_headers(),
            ),
            200,
        )
        assert_harvest_equipment(certified)
        assert certified["cleanout_certified"] is True
        assert certified["status"] == "AVAILABLE"
        assert certified["last_cleanout_variety_id"] == variety["id"]
        assert certified["last_cleanout_at"] == TEST_DEFAULTS["CLEANED_AT"]
        assert certified["version"] == equipment["version"] + 1

        machines, meta = validate_paginated(
            api.list_harvest_equipment(
                make_conditioning_manager_headers(), {"last_cleanout_variety_id": variety["id"]}
            )
        )
        assert meta["total_count"] == 1
        assert machines[0]["id"] == equipment["id"]


TREATED_VARIETY_NAME = "HRW-Ember"
LABEL_MAX_RATE_G_PER_100KG = 150.0
TREATING_WINDOW_START = "2026-09-12T18:00:00Z"
TREATING_WINDOW_END = "2026-09-12T20:00:00Z"
INCOMPLETE_LABEL_TEXT = "Treated seed - do not use for food, feed or oil purposes."


def _sized_lot_of_a_treatment_required_variety(api):
    """A SIZED lot of a variety that declares treatment mandatory before bagging."""
    state = harvested_lot_state(
        api,
        variety_overrides={
            "variety_name": TREATED_VARIETY_NAME,
            "treatment_required": True,
        },
    )
    lot_id = state["seed_lot"]["id"]
    line_id = state["line"]["id"]
    state["cleaning_run"] = run_stage(
        api,
        lot_id,
        line_id,
        "CLEANING",
        TEST_DEFAULTS["CLEANING_OUTPUT_KG"],
        window_start=TEST_DEFAULTS["CLEANING_WINDOW_START"],
        window_end=TEST_DEFAULTS["CLEANING_WINDOW_END"],
        input_kg=TEST_DEFAULTS["GROSS_WEIGHT_KG"],
    )
    state["sizing_run"] = run_stage(
        api,
        lot_id,
        line_id,
        "SIZING",
        TEST_DEFAULTS["SIZING_OUTPUT_KG"],
        window_start=TEST_DEFAULTS["SIZING_WINDOW_START"],
        window_end=TEST_DEFAULTS["SIZING_WINDOW_END"],
        input_kg=TEST_DEFAULTS["CLEANING_OUTPUT_KG"],
    )
    state["product"] = make_treatment_product(
        api, max_rate_g_per_100kg=LABEL_MAX_RATE_G_PER_100KG
    )
    return state


class TestBaggingIsConditionalOnTreatment:
    def test_a_variety_that_requires_treatment_loses_the_direct_bagging_shortcut(self, api):
        """The `SIZED`-to-`BAGGING` branch is only open to untreated varieties.

        PRD: "Finally, `treatment_required` declares whether a treating stage is mandatory before
        bagging for this variety; it defaults to false."

        PRD: "The one branch is that a `SIZED` lot may go directly to `BAGGING`, skipping treatment
        entirely, but only when the lot's variety has `treatment_required` false; when the variety
        requires treatment, the direct `SIZED`-to-`BAGGING` shortcut is not available."

        PRD: "Any stage that is not the immediate successor under these rules is refused with
        `ERR_STAGE_OUT_OF_ORDER`."

        Design: Corner/endpoints/bagging_conditional_on_variety_treatment_requirement
        """
        state = _sized_lot_of_a_treatment_required_variety(api)
        lot_id = state["seed_lot"]["id"]

        assert state["variety"]["treatment_required"] is True

        response = api.create_conditioning_run(
            create_conditioning_run_payload(
                lot_id,
                state["line"]["id"],
                "BAGGING",
                window_start=TEST_DEFAULTS["BAGGING_WINDOW_START"],
                window_end=TEST_DEFAULTS["BAGGING_WINDOW_END"],
                input_kg=TEST_DEFAULTS["SIZING_OUTPUT_KG"],
            ),
            make_conditioning_manager_headers(),
        )
        validate_error(response, "ERR_STAGE_OUT_OF_ORDER", 409)

        lot = get_success_data(api.get_seed_lot(lot_id, make_conditioning_manager_headers()))
        assert lot["conditioning_status"] == "SIZED"
        assert lot["current_kg"] == pytest.approx(TEST_DEFAULTS["SIZING_OUTPUT_KG"], abs=0.001)
        assert lot["bag_count"] == 0
        assert lot["final_clean_units"] is None

    def test_the_treating_run_is_accepted_only_once_the_label_discloses_everything(self, api):
        """A label missing the registration number and the dye statement is refused first.

        PRD: "The requested `treatment_rate_g_per_100kg` may not exceed the product's
        `max_rate_g_per_100kg`; a rate exactly at the label maximum is permitted, and anything above
        it is refused with `ERR_TREATMENT_RATE_EXCEEDS_LABEL`."

        PRD: "The supplied `label_text` must always contain the product's
        `epa_registration_number` as a substring."

        PRD: "When the product's `requires_dye` flag is true, the label text must additionally
        contain the literal string `DYED`, because treated seed that must be dyed has to be disclosed
        as such on the bag."

        PRD: "A label text missing any applicable one of those three elements is refused with
        `ERR_TREATMENT_LABEL_INCOMPLETE`."

        PRD: "A planned run lands in `PLANNED` status with `output_kg`, `shrink_kg` and `bag_count`
        all null and `reversal_reason` null; its `status` is one of `PLANNED`, `COMPLETED`, `ABORTED`
        or `REVERSED`."

        PRD: "The lot's conditioning axis advances one rung — `RAW → CLEANED` for a cleaning run,
        `CLEANED → SIZED` for a sizing run, `SIZED → TREATED` for a treating run, and either
        `SIZED → BAGGED` or `TREATED → BAGGED` for a bagging run — and the lot's `version` increments
        by 1."

        Design: Corner/endpoints/bagging_conditional_on_variety_treatment_requirement
        """
        state = _sized_lot_of_a_treatment_required_variety(api)
        lot_id = state["seed_lot"]["id"]
        product = state["product"]
        assert product["requires_dye"] is True
        assert product["max_rate_g_per_100kg"] == pytest.approx(
            LABEL_MAX_RATE_G_PER_100KG, abs=0.01
        )

        treating_payload = create_conditioning_run_payload(
            lot_id,
            state["line"]["id"],
            "TREATING",
            window_start=TREATING_WINDOW_START,
            window_end=TREATING_WINDOW_END,
            input_kg=TEST_DEFAULTS["SIZING_OUTPUT_KG"],
            treatment_product_id=product["id"],
            treatment_rate_g_per_100kg=LABEL_MAX_RATE_G_PER_100KG,
            label_text=INCOMPLETE_LABEL_TEXT,
        )
        response = api.create_conditioning_run(
            treating_payload, make_conditioning_manager_headers()
        )
        validate_error(response, "ERR_TREATMENT_LABEL_INCOMPLETE", 422)

        complete_label = treatment_label_text(
            epa_registration_number=product["epa_registration_number"],
            signal_word=product["label_signal_word"],
        )
        assert product["epa_registration_number"] in complete_label
        assert "DYED" in complete_label

        planned = validate_success(
            api.create_conditioning_run(
                dict(treating_payload, label_text=complete_label),
                make_conditioning_manager_headers(),
            ),
            201,
        )
        assert_conditioning_run(planned)
        assert planned["stage"] == "TREATING"
        assert planned["status"] == "PLANNED"
        assert planned["treatment_product_id"] == product["id"]
        assert planned["treatment_rate_g_per_100kg"] == pytest.approx(
            LABEL_MAX_RATE_G_PER_100KG, abs=0.01
        )
        assert planned["label_text"] == complete_label
        assert planned["output_kg"] is None
        assert planned["shrink_kg"] is None
        assert planned["bag_count"] is None

        lot = get_success_data(api.get_seed_lot(lot_id, make_conditioning_manager_headers()))
        assert lot["conditioning_status"] == "SIZED"


REWOUND_CLOCK = "2026-09-13T00:00:00Z"


class TestClockEndpointGovernsDateRules:
    def test_the_instant_the_clock_echoes_is_the_instant_the_date_rules_read(self, api):
        """One sampling call is refused before the move and accepted after it, unchanged.

        PRD: "A `ProgramAdmin` may reposition the clock through the administrative test-driving
        capability `POST /_clock/set_current_utc`, supplying the target instant as `current_utc`."

        PRD: "The response echoes `{ current_utc }`."

        PRD: "Any other combination is refused with `ERR_INVALID_LOT_STATE`, and a `sampled_on`
        after the current logical clock date is refused with `ERR_DATE_IN_FUTURE`."

        PRD: "Drawing a sample records the drawing operator's `X-User-ID` as `sampler_user_id`, puts
        the sample in `PENDING` result state with `germination_pct`, `purity_pct`, `inert_pct`,
        `weed_seed_count_per_kg`, `tested_at` and `germination_valid_until` all null, moves the lot's
        certification status to `SAMPLED` while leaving its conditioning status exactly where it was,
        and increments the lot's `version` by 1."

        Design: Corner/endpoints/clock_endpoint_sets_and_echoes_logical_instant
        """
        state = bagged_lot_state(api)
        lot_id = state["seed_lot"]["id"]

        rewound = validate_success(
            api.set_clock(set_clock_payload(REWOUND_CLOCK), make_program_admin_headers()), 200
        )
        assert rewound["current_utc"] == REWOUND_CLOCK

        sample_payload = create_lot_sample_payload(lot_id, sampled_on=TEST_DEFAULTS["SAMPLED_ON"])
        response = api.create_lot_sample(sample_payload, make_certification_agency_headers())
        validate_error(response, "ERR_DATE_IN_FUTURE", 422)

        before = get_success_data(api.get_seed_lot(lot_id, make_conditioning_manager_headers()))
        assert before["certification_status"] == "UNSAMPLED"

        moved = validate_success(
            api.set_clock(
                set_clock_payload(TEST_DEFAULTS["HARVEST_CLOCK"]), make_program_admin_headers()
            ),
            200,
        )
        assert moved["current_utc"] == TEST_DEFAULTS["HARVEST_CLOCK"]

        sample = validate_success(
            api.create_lot_sample(sample_payload, make_certification_agency_headers()), 201
        )
        assert_lot_sample(sample)
        assert sample["sampled_on"] == TEST_DEFAULTS["SAMPLED_ON"]
        assert sample["sample_kind"] == "INITIAL"
        assert sample["result"] == "PENDING"
        assert sample["sampler_user_id"] == CERTIFICATION_AGENCY_ID
        assert sample["germination_pct"] is None
        assert sample["germination_valid_until"] is None

        lot = get_success_data(api.get_seed_lot(lot_id, make_conditioning_manager_headers()))
        assert lot["certification_status"] == "SAMPLED"
        assert lot["conditioning_status"] == "BAGGED"
        assert lot["version"] == before["version"] + 1
