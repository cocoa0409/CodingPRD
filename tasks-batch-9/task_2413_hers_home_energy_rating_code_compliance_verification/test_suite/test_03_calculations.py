"""Derived arithmetic of the HERS Rating & Code Compliance API.

Measurement normalization against the checkpoint-dependent thresholds, the
compliance-path waterfall, the quality-assurance quota, the utility-program
incentive with its per-package cap, and the tested-home selector's ranking.
"""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers.api_errors import (
    ERR_NO_ELIGIBLE_SAMPLE_HOME,
    ERR_RATER_QA_DEFICIT,
)
from test_helpers.assertions import (
    assert_builder_ledger,
    assert_cents,
    assert_count,
    assert_home_sampling_state,
    assert_index,
    assert_line_items,
    assert_normalized_value,
    assert_package_state,
    assert_rater_standing,
    assert_rating_dimensions,
    assert_sample_set_counters,
)
from test_helpers.fixtures import (
    assign_qa_review,
    build_rating_world,
    build_sample_world,
    complete_inspection,
    complete_qa_review,
    confirm_rating,
    corrective_actions_of,
    create_home,
    create_rating,
    draft_package,
    get_builder,
    get_home,
    get_rater,
    get_rating,
    get_sample_set,
    issue_package,
    record_test,
    run_final_checkpoint,
    schedule_inspection,
    select_sample_set,
)
from test_helpers.test_users import ADMIN_HEADERS

BIG_3000_PLAN = {
    "plan_code": "BIG-3000",
    "conditioned_floor_area_sqft": 3000,
    "conditioned_volume_cuft": 27000,
    "bedrooms": 5,
    "envelope_ua_btu_per_hr_f": 520,
    "design_ach50": 4.00,
    "design_duct_leakage_cfm25_per_100sqft": 4.00,
    "hvac_efficiency_index": 8,
    "pv_capacity_kw_dc": 0,
}

TIGHT_2400_PLAN = {"plan_code": "TIGHT-2400", "envelope_ua_btu_per_hr_f": 280}

PERF_2400_PLAN = {
    "plan_code": "PERF-2400",
    "bedrooms": 3,
    "envelope_ua_btu_per_hr_f": 336,
    "hvac_efficiency_index": 5,
}

CAP_3600_PLAN = {
    "plan_code": "CAP-3600",
    "conditioned_floor_area_sqft": 3600,
    "conditioned_volume_cuft": 32400,
    "bedrooms": 5,
    "envelope_ua_btu_per_hr_f": 480,
    "design_ach50": 3.00,
    "design_duct_leakage_cfm25_per_100sqft": 3.00,
    "hvac_efficiency_index": 9,
    "pv_capacity_kw_dc": 0,
}

TIE_2000_PLAN = {
    "plan_code": "TIE-2000",
    "conditioned_floor_area_sqft": 2000,
    "conditioned_volume_cuft": 18000,
    "bedrooms": 3,
    "envelope_ua_btu_per_hr_f": 256,
}


class TestMeasurementThresholds:
    def test_duct_leakage_threshold_switches_with_air_handler_presence(self, api):
        """PRD §2.7: "At the rough-in checkpoint the limit depends on whether the air handler was already installed when the test was run: 4.0 with the air handler in place, and the tighter 3.0 without it."
        PRD §3.3: "Recording a duct-leakage reading normalizes it per unit floor area: multiply the `measured_value` by 100, divide by the pinned plan's `conditioned_floor_area_sqft`, and round the quotient half-up to two decimal places to obtain `normalized_value`."
        PRD §3.3: "In both cases the graded outcome follows one rule: `result` is `PASS` when the rounded `normalized_value` is less than or equal to `threshold_value`, and `FAIL` otherwise."
        PRD §3.3: "A `ROUGH_IN` checkpoint that closes as `FAILED` leaves the rating's `stage` exactly where it was — a failed rough-in never verifies, and the rating remains `PROJECTED`."

        Design: Corner/calculations/duct_leakage_threshold_switches_with_air_handler_presence
        """
        world = build_rating_world(
            api,
            builder_name="Bristol Homes",
            subdivision_name="Foxglove",
            plan_overrides=BIG_3000_PLAN,
            with_home=False,
            with_rating=False,
        )

        inspections = []
        ratings = []
        for lot_number, air_handler_installed, start, end in (
            ("L-4001", True, "2026-08-18T09:00:00Z", "2026-08-18T10:00:00Z"),
            ("L-4002", False, "2026-08-18T13:00:00Z", "2026-08-18T14:00:00Z"),
        ):
            home = create_home(
                api,
                world.subdivision_id,
                world.plan_model_id,
                world.builder_id,
                lot_number=lot_number,
            )
            rating = create_rating(api, home["id"], world.rater_id)
            ratings.append(rating)
            inspections.append(
                schedule_inspection(
                    api,
                    rating["id"],
                    world.inspector_id,
                    checkpoint="ROUGH_IN",
                    scheduled_start_utc=start,
                    scheduled_end_utc=end,
                    air_handler_installed=air_handler_installed,
                )
            )

        with_handler = record_test(
            api, inspections[0]["id"], world.inspector_id, "DUCT_LEAKAGE_TOTAL", 100
        )
        without_handler = record_test(
            api, inspections[1]["id"], world.inspector_id, "DUCT_LEAKAGE_TOTAL", 100
        )

        assert_normalized_value(with_handler["normalized_value"], 3.33)
        assert_normalized_value(with_handler["threshold_value"], 4.0)
        assert with_handler["result"] == "PASS", with_handler

        assert_normalized_value(without_handler["normalized_value"], 3.33)
        assert_normalized_value(without_handler["threshold_value"], 3.0)
        assert without_handler["result"] == "FAIL", without_handler

        passed = complete_inspection(api, inspections[0]["id"], world.inspector_id)
        failed = complete_inspection(api, inspections[1]["id"], world.inspector_id)

        assert passed["status"] == "PASSED", passed
        assert passed["failed_test_count"] == 0, passed
        assert failed["status"] == "FAILED", failed
        assert failed["failed_test_count"] == 1, failed

        assert_rating_dimensions(
            get_rating(api, ratings[0]["id"]), stage="ROUGH_IN_VERIFIED"
        )
        assert_rating_dimensions(get_rating(api, ratings[1]["id"]), stage="PROJECTED")


class TestCompliancePathWaterfall:
    def test_prescriptive_election_fails_when_envelope_ua_exceeds_cap(self, api):
        """PRD §3.4: "If the subdivision's `compliance_path_preference` is `PRESCRIPTIVE_PATH`, only the prescriptive path is available and the waterfall never continues past this step."
        PRD §3.4: "The rating passes on the prescriptive path — `compliance_path` becomes `PRESCRIPTIVE` and `compliance_status` becomes `PASSING` — when the airtightness test passes, the duct test passes, and the pinned plan's `envelope_ua_btu_per_hr_f` is less than or equal to 0.12 multiplied by its `conditioned_floor_area_sqft`."
        PRD §3.4: "Otherwise, and regardless of how good the index is, `compliance_path` becomes `NONE` and `compliance_status` becomes `FAILING`."
        PRD §3.4: "If the selection landed on `FAILING`, it opens a corrective action against this rating with `reason` of `THRESHOLD_FAILURE` and `status` of `OPEN`, which raises the owning builder's `open_corrective_action_count` and thereby recomputes that builder's `sampling_eligible` to false."

        Design: Corner/calculations/prescriptive_election_fails_when_envelope_ua_exceeds_cap
        """
        world = build_rating_world(
            api,
            builder_name="Larkspur Custom",
            builder_type="CUSTOM",
            subdivision_name="Larkspur",
            compliance_path_preference="PRESCRIPTIVE_PATH",
            lot_number="L-4101",
        )
        run_final_checkpoint(
            api,
            world,
            blower_door=1080,
            duct_leakage=96,
            scheduled_start_utc="2026-08-20T09:00:00Z",
            scheduled_end_utc="2026-08-20T11:00:00Z",
        )

        rating = validate_success(
            api.confirm_rating(world.rating_id, world.rater_headers), 200
        )

        assert_rating_dimensions(rating, stage="CONFIRMED", compliance_status="FAILING")
        assert_index(rating["confirmed_index"], 46)
        assert_normalized_value(rating["confirmed_ach50"], 3.00)
        assert_normalized_value(
            rating["confirmed_duct_leakage_cfm25_per_100sqft"], 4.00
        )
        assert rating["compliance_path"] == "NONE", rating

        actions = corrective_actions_of(api, world.rating_id)
        assert_count(actions, 1)
        assert actions[0]["reason"] == "THRESHOLD_FAILURE", actions
        assert actions[0]["status"] == "OPEN", actions
        assert_builder_ledger(
            get_builder(api, world.builder_id), open_corrective_action_count=1
        )

    def test_prescriptive_election_passes_when_envelope_ua_within_cap(self, api):
        """PRD §3.4: "The rating passes on the prescriptive path — `compliance_path` becomes `PRESCRIPTIVE` and `compliance_status` becomes `PASSING` — when the airtightness test passes, the duct test passes, and the pinned plan's `envelope_ua_btu_per_hr_f` is less than or equal to 0.12 multiplied by its `conditioned_floor_area_sqft`."
        PRD §3.4: "A prescriptive-election subdivision therefore never records `ERI` or `PERFORMANCE` on any rating."

        Design: Corner/calculations/prescriptive_election_passes_when_envelope_ua_within_cap
        """
        world = build_rating_world(
            api,
            builder_name="Larkspur Custom",
            builder_type="CUSTOM",
            subdivision_name="Larkspur North",
            compliance_path_preference="PRESCRIPTIVE_PATH",
            plan_overrides=TIGHT_2400_PLAN,
            lot_number="L-4201",
        )
        run_final_checkpoint(
            api,
            world,
            blower_door=1080,
            duct_leakage=96,
            scheduled_start_utc="2026-08-20T09:00:00Z",
            scheduled_end_utc="2026-08-20T11:00:00Z",
        )

        rating = validate_success(
            api.confirm_rating(world.rating_id, world.rater_headers), 200
        )

        assert_index(rating["projected_index"], 39)
        assert_index(rating["confirmed_index"], 41)
        assert rating["compliance_path"] == "PRESCRIPTIVE", rating
        assert_rating_dimensions(rating, compliance_status="PASSING")
        assert_builder_ledger(
            get_builder(api, world.builder_id), open_corrective_action_count=0
        )

    def test_performance_path_selected_when_index_lands_within_target_tolerance(
        self, api
    ):
        """PRD §3.4: "If step 1 did not qualify, the home gets a second chance with a looser index allowance and a tighter envelope gate: if `confirmed_index` is less than or equal to the ERI target plus a tolerance of 5 index points, and the airtightness test passes, and the duct test passes, and the pinned plan's `envelope_ua_btu_per_hr_f` is less than or equal to 0.14 multiplied by its `conditioned_floor_area_sqft`, then `compliance_path` becomes `PERFORMANCE` and `compliance_status` becomes `PASSING`."
        PRD §3.1: "Second, an **equipment multiplier** is derived from the plan's `hvac_efficiency_index`: take 1.35, subtract 0.05 multiplied by the efficiency index, then clamp the result into the closed range from 0.62 to 1.05 — that is, any value above 1.05 becomes exactly 1.05 and any value below 0.62 becomes exactly 0.62."

        Design: Corner/calculations/performance_path_selected_when_index_lands_within_target_tolerance
        """
        world = build_rating_world(
            api,
            builder_name="Bristol Homes",
            subdivision_name="Foxglove",
            plan_overrides=PERF_2400_PLAN,
            lot_number="L-4301",
        )
        run_final_checkpoint(
            api,
            world,
            blower_door=1080,
            duct_leakage=96,
            scheduled_start_utc="2026-08-20T09:00:00Z",
            scheduled_end_utc="2026-08-20T11:00:00Z",
        )

        rating = confirm_rating(api, world.rating_id, world.rater_id)

        assert_index(rating["projected_index"], 55)
        assert_index(rating["confirmed_index"], 58)
        assert rating["compliance_path"] == "PERFORMANCE", rating
        assert_rating_dimensions(rating, compliance_status="PASSING")
        assert_builder_ledger(
            get_builder(api, world.builder_id), open_corrective_action_count=0
        )


class TestQualityAssuranceQuota:
    def test_probation_quota_rate_blocks_the_next_registry_submission(self, api):
        """PRD §3.6: "A rater in good standing is sampled at one file in ten — a rate of 0.10 — while a rater on `PROBATION` is sampled at every file, a rate of 1.00."
        PRD §3.6: "The quota is then: multiply the applicable rate by `confirmed_rating_count` in exact decimal arithmetic and take the floor of that product to get the number of files required; subtract `qa_completed_count` from it; and take the greater of that difference and zero to get `qa_files_owed`."
        PRD §3.6: "Immediately after the review that caused the probation those two typically read zero and false, since the review just completed brought the counts level; the rater's very next confirmation raises `confirmed_rating_count` without raising `qa_completed_count`, and the hold bites at that point."
        PRD §3.8: "A rater carrying a quality-assurance deficit, meaning `registry_hold` is true because `qa_files_owed` is above zero, is refused with `ERR_RATER_QA_DEFICIT`."

        Design: Corner/calculations/probation_quota_rate_blocks_the_next_registry_submission
        """
        world = build_rating_world(
            api,
            builder_name="Bristol Homes",
            subdivision_name="Foxglove",
            with_home=False,
            with_rating=False,
        )

        first_home = create_home(
            api,
            world.subdivision_id,
            world.plan_model_id,
            world.builder_id,
            lot_number="L-4401",
        )
        world.home = first_home
        world.rating = create_rating(api, first_home["id"], world.rater_id)
        first_rating_id = world.rating_id
        run_final_checkpoint(
            api,
            world,
            blower_door=1080,
            duct_leakage=96,
            scheduled_start_utc="2026-08-18T09:00:00Z",
            scheduled_end_utc="2026-08-18T11:00:00Z",
        )
        confirm_rating(api, first_rating_id, world.rater_id)

        review = assign_qa_review(
            api, first_rating_id, world.qa_designee_id, review_type="FILE_REVIEW"
        )
        complete_qa_review(
            api,
            review["id"],
            world.qa_designee_id,
            "FAIL_MINOR",
            findings_note="Duct schedule mislabeled",
        )

        # One confirmed file and one completed review at the 1.00 probation rate.
        assert_rater_standing(
            get_rater(api, world.rater_id),
            certification_status="PROBATION",
            qa_files_owed=0,
            registry_hold=False,
        )

        second_home = create_home(
            api,
            world.subdivision_id,
            world.plan_model_id,
            world.builder_id,
            lot_number="L-4402",
        )
        world.home = second_home
        world.rating = create_rating(api, second_home["id"], world.rater_id)
        second_rating_id = world.rating_id
        run_final_checkpoint(
            api,
            world,
            blower_door=1080,
            duct_leakage=96,
            scheduled_start_utc="2026-08-20T09:00:00Z",
            scheduled_end_utc="2026-08-20T11:00:00Z",
        )
        confirm_rating(api, second_rating_id, world.rater_id)

        validate_error(
            api.submit_rating_to_registry(second_rating_id, world.rater_headers),
            ERR_RATER_QA_DEFICIT,
            422,
        )

        assert_rater_standing(
            get_rater(api, world.rater_id),
            certification_status="PROBATION",
            confirmed_rating_count=2,
            qa_completed_count=1,
            qa_files_owed=1,
            registry_hold=True,
        )
        rating = get_rating(api, second_rating_id)
        assert_rating_dimensions(rating, registry_status="NOT_SUBMITTED")
        assert rating["file_locked"] is False, rating


class TestIncentiveAmounts:
    def test_utility_package_amount_capped_after_line_items_are_summed(self, api):
        """PRD §3.9: "For a **`UTILITY_PROGRAM`** package the amount is the sum of four per-measure line items, computed in a pinned rounding order that must not be rearranged: **each line item is rounded to whole cents first, the rounded line items are then summed, and the cap is applied last.**"
        PRD §3.9: "The four rounded amounts are then added together, and the package amount is the smaller of that subtotal and a per-package cap of 150,000 cents — one thousand five hundred dollars."
        PRD §3.9: "The `line_items` array records the uncapped per-measure amounts even when the cap bites."
        PRD §3.9: "A successful issuance recomputes the certified variant into `certified_amount_cents` and rewrites `line_items` from the measured values, sets `status` to `ISSUED`, stamps `issued_at` from the logical clock, and raises the builder's `certified_incentive_cents` by the certified amount."

        Design: Corner/calculations/utility_package_amount_capped_after_line_items_are_summed
        """
        world = build_rating_world(
            api,
            builder_name="Cardinal Homes",
            utility_program_budget_cents=500000,
            subdivision_name="Cardinal Ridge",
            plan_overrides=CAP_3600_PLAN,
            lot_number="L-4501",
        )
        run_final_checkpoint(
            api,
            world,
            blower_door=1620,
            duct_leakage=144,
            scheduled_start_utc="2026-08-20T09:00:00Z",
            scheduled_end_utc="2026-08-20T11:00:00Z",
        )
        rating = confirm_rating(api, world.rating_id, world.rater_id)
        assert_index(rating["projected_index"], 45)
        assert_index(rating["confirmed_index"], 47)

        draft = draft_package(
            api, world.rating_id, world.builder_id, package_type="UTILITY_PROGRAM"
        )
        assert_package_state(draft, provisional_amount_cents=150000)

        package = issue_package(api, draft["id"])

        assert_package_state(
            package,
            status="ISSUED",
            provisional_amount_cents=150000,
            certified_amount_cents=150000,
        )
        assert_line_items(
            package,
            [("ENVELOPE", 135000), ("DUCTS", 0), ("AIR", 3000), ("INDEX", 29250)],
        )

        builder = get_builder(api, world.builder_id)
        assert_builder_ledger(builder, certified_incentive_cents=150000)
        assert_cents(builder["utility_program_budget_cents"], 500000)


class TestTestedHomeSelector:
    def test_tested_home_selection_tie_breaks_on_floor_area_then_created_at(self, api):
        """PRD §3.5: "Otherwise the candidates are ranked by their rating's `projected_index` in descending order — the highest, worst index first."
        PRD §3.5: "Ties are broken in a fixed two-stage order: first by the `conditioned_floor_area_sqft` of the home's pinned plan model in descending order, largest first; and then, if still tied, by the home's `created_at` in ascending order, earliest first, compared at millisecond precision."
        PRD §3.5: "Selection then records the winner's identifier in the set's `tested_home_id`, moves that home's `sampling_role` from `MEMBER` to `TESTED`, sets `tested_member_count` to 1, and moves the set's `status` from `FORMING` to `SELECTED`."

        Design: Corner/calculations/tested_home_selection_tie_breaks_on_floor_area_then_created_at
        """
        world = build_sample_world(
            api,
            member_count=3,
            lot_numbers=["L-4601", "L-4602", "L-4603"],
            permit_dates=["2026-08-05", "2026-08-05", "2026-08-05"],
            plan_overrides_per_home=[None, None, TIE_2000_PLAN],
        )
        for rating in world.ratings:
            assert_index(rating["projected_index"], 43)

        sample_set = select_sample_set(api, world.sample_set_id)

        assert_sample_set_counters(
            sample_set,
            status="SELECTED",
            member_count=3,
            tested_member_count=1,
            tested_home_id=world.homes[0]["id"],
        )
        assert_home_sampling_state(
            get_home(api, world.homes[0]["id"]), sampling_role="TESTED"
        )
        assert_home_sampling_state(
            get_home(api, world.homes[1]["id"]), sampling_role="MEMBER"
        )
        assert_home_sampling_state(
            get_home(api, world.homes[2]["id"]), sampling_role="MEMBER"
        )

    def test_select_with_no_rated_member_homes_rejected(self, api):
        """PRD §3.5: "It first filters the set's own member homes down to candidates, keeping a member only when its `individual_testing_required` flag is false and when there exists a rating on that home whose `stage` is `PROJECTED` and whose `registry_status` is `NOT_SUBMITTED`."
        PRD §3.5: "If the candidate list comes out empty the whole selection is rejected with `ERR_NO_ELIGIBLE_SAMPLE_HOME` and nothing changes."

        Design: Corner/calculations/select_with_no_rated_member_homes_rejected
        """
        world = build_sample_world(
            api,
            member_count=2,
            lot_numbers=["L-4701", "L-4702"],
            permit_dates=["2026-08-05", "2026-08-05"],
            open_ratings=False,
        )
        ratings, _meta = validate_paginated(
            api.list_ratings(
                ADMIN_HEADERS, params={"home_id": world.homes[0]["id"]}
            )
        )
        assert_count(ratings, 0)

        validate_error(
            api.select_sample_set(world.sample_set_id, ADMIN_HEADERS),
            ERR_NO_ELIGIBLE_SAMPLE_HOME,
            422,
        )

        assert_sample_set_counters(
            get_sample_set(api, world.sample_set_id),
            status="FORMING",
            member_count=2,
            tested_member_count=0,
            tested_home_id=None,
        )
