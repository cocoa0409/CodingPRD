"""Validation rules and the normative §2.8 evaluation order."""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import factories
from test_helpers.api_errors import (
    ERR_CERT_LEVEL_INSUFFICIENT,
    ERR_DUPLICATE_ACTIVE_RATING,
    ERR_DUPLICATE_LOT_NUMBER,
    ERR_DUPLICATE_PLAN_CODE,
    ERR_HOME_ALREADY_SAMPLED,
    ERR_HOME_PERMIT_OUTSIDE_WINDOW,
    ERR_HOME_SUBDIVISION_MISMATCH,
    ERR_OPEN_CORRECTIVE_ACTION,
    ERR_PROGRAM_BUDGET_EXCEEDED,
    ERR_RATING_NOT_COMPLIANT,
    ERR_REPRESENTED_HOME_NOT_TESTABLE,
    ERR_SAMPLE_SET_SIZE_INVALID,
    ERR_SAMPLING_NOT_ENABLED,
    ERR_SEGREGATION_OF_DUTIES,
)
from test_helpers.assertions import (
    assert_builder_ledger,
    assert_count,
    assert_coverage_ledger,
    assert_home_sampling_state,
    assert_index,
    assert_package_state,
    assert_rater_standing,
    assert_rating_dimensions,
    assert_sample_set_counters,
)
from test_helpers.fixtures import (
    add_sample_member,
    assign_qa_review,
    build_confirmed_world,
    close_sample_set,
    complete_inspection,
    complete_qa_review,
    confirm_rating,
    corrective_actions_of,
    create_builder,
    create_home,
    create_plan_model,
    create_rater,
    create_rating,
    create_sample_set,
    create_subdivision,
    draft_package,
    get_builder,
    get_home,
    get_qa_review,
    get_rater,
    get_rating,
    get_sample_set,
    get_subdivision,
    list_packages,
    record_test,
    schedule_inspection,
    select_sample_set,
)
from test_helpers.test_users import (
    ADMIN_HEADERS,
    make_builder_rep_headers,
    make_certified_rater_headers,
    make_qa_designee_headers,
)


class TestUniquenessScoping:
    def test_duplicate_lot_number_is_scoped_to_the_subdivision(self, api):
        """§3.2: "A builder representative registers each lot it intends to have rated as a `Home`, supplying the `subdivision_id`, the `plan_model_id` of the plan being built on that lot, a `lot_number` unique within the subdivision, and a `permit_date` as a `YYYY-MM-DD` calendar date."

        §3.2: "A repeated lot number in the same subdivision is `ERR_DUPLICATE_LOT_NUMBER`."

        Design: Corner/validations/duplicate_lot_number_within_subdivision_rejected
        """
        builder = create_builder(api, name="Bristol Homes")
        foxglove = create_subdivision(api, builder["id"], name="Foxglove")
        hawthorn = create_subdivision(api, builder["id"], name="Hawthorn")
        rater = create_rater(api)
        foxglove_plan = create_plan_model(api, foxglove["id"], rater["id"])
        hawthorn_plan = create_plan_model(api, hawthorn["id"], rater["id"])
        create_home(
            api,
            foxglove["id"],
            foxglove_plan["id"],
            builder["id"],
            lot_number="L-5001",
            permit_date="2026-08-05",
        )

        collision = api.create_home(
            factories.home_payload(
                foxglove["id"],
                foxglove_plan["id"],
                lot_number="L-5001",
                permit_date="2026-08-06",
            ),
            make_builder_rep_headers(builder["id"]),
        )
        validate_error(collision, ERR_DUPLICATE_LOT_NUMBER, 409)

        elsewhere = create_home(
            api,
            hawthorn["id"],
            hawthorn_plan["id"],
            builder["id"],
            lot_number="L-5001",
            permit_date="2026-08-06",
        )
        assert elsewhere["lot_number"] == "L-5001"
        assert_coverage_ledger(get_subdivision(api, foxglove["id"]), homes_count=1)
        assert_coverage_ledger(get_subdivision(api, hawthorn["id"]), homes_count=1)

    def test_duplicate_plan_code_within_the_subdivision_is_rejected(self, api):
        """§3.1: "A plan model is created against a `subdivision_id` and carries a `plan_code` that must be unique within its subdivision — a collision is rejected with `ERR_DUPLICATE_PLAN_CODE`."

        §3.1: "Registration computes the plan's `projected_index` on the spot and sets `status` to `ACTIVE`; the only other value `status` can ever take is `ARCHIVED`, which a cascade described in §3.6 writes."

        Design: Corner/validations/duplicate_plan_code_within_subdivision_rejected
        """
        builder = create_builder(api, name="Bristol Homes")
        subdivision = create_subdivision(api, builder["id"], name="Foxglove")
        rater = create_rater(api)
        original = create_plan_model(api, subdivision["id"], rater["id"])

        collision = api.create_plan_model(
            factories.plan_model_payload(
                subdivision["id"],
                plan_code="STD-2400",
                conditioned_floor_area_sqft=2600,
                conditioned_volume_cuft=23400,
                envelope_ua_btu_per_hr_f=380,
            ),
            make_certified_rater_headers(rater["id"]),
        )
        validate_error(collision, ERR_DUPLICATE_PLAN_CODE, 409)

        plans, _meta = validate_paginated(
            api.list_plan_models(subdivision["id"], ADMIN_HEADERS)
        )
        assert_count(plans, 1)
        assert_index(original["projected_index"], 43)
        assert original["status"] == "ACTIVE", original

    def test_second_live_rating_on_the_same_home_is_rejected(self, api):
        """§3.2: "A home may carry only one live rating."

        §3.2: "If the home already has a rating whose `stage` is any of `PROJECTED`, `ROUGH_IN_VERIFIED`, `CONFIRMED` or `REGISTERED`, a second rating is refused with `ERR_DUPLICATE_ACTIVE_RATING` — unless the request's `supersedes_rating_id` names that very rating *and* that rating has either reached `stage` `VOID` or been failed with `qa_status` of `QA_FAILED`."

        Design: Corner/validations/second_active_rating_on_the_same_home_rejected
        """
        builder = create_builder(api, name="Bristol Homes")
        subdivision = create_subdivision(api, builder["id"], name="Foxglove")
        rater_of_record = create_rater(api, full_name="Rae Tarrant")
        other_rater = create_rater(api, full_name="Otis Vane")
        plan = create_plan_model(api, subdivision["id"], rater_of_record["id"])
        home = create_home(
            api,
            subdivision["id"],
            plan["id"],
            builder["id"],
            lot_number="L-5201",
            permit_date="2026-08-05",
        )
        first = create_rating(api, home["id"], rater_of_record["id"])
        assert_rating_dimensions(first, stage="PROJECTED")

        second = api.create_rating(
            factories.rating_payload(home["id"], other_rater["id"]),
            make_certified_rater_headers(other_rater["id"]),
        )
        validate_error(second, ERR_DUPLICATE_ACTIVE_RATING, 409)

        ratings, _meta = validate_paginated(
            api.list_ratings(ADMIN_HEADERS, params={"home_id": home["id"]})
        )
        assert_count(ratings, 1)
        assert ratings[0]["rater_id"] == rater_of_record["id"], ratings[0]


class TestSampleMembershipCoherence:
    def test_permit_date_outside_the_window_is_rejected_and_leaves_the_version(self, api):
        """§3.5: "The home's `permit_date` must lie inside the closed interval running from `window_start_date` through `window_end_date` inclusive, or the addition fails with `ERR_HOME_PERMIT_OUTSIDE_WINDOW`."

        §2.9: "A successful addition increases the set's `version` by 1."

        Design: Corner/validations/home_permit_date_outside_sample_window_rejected
        """
        builder = create_builder(api, name="Bristol Homes")
        subdivision = create_subdivision(
            api, builder["id"], name="Foxglove", sampling_enabled=True
        )
        rater = create_rater(api)
        plan = create_plan_model(api, subdivision["id"], rater["id"])
        outside = create_home(
            api,
            subdivision["id"],
            plan["id"],
            builder["id"],
            lot_number="L-5301",
            permit_date="2026-09-05",
        )
        on_the_end_date = create_home(
            api,
            subdivision["id"],
            plan["id"],
            builder["id"],
            lot_number="L-5302",
            permit_date="2026-08-31",
        )
        sample_set = create_sample_set(
            api,
            subdivision["id"],
            rater["id"],
            window_start_date="2026-08-01",
            window_end_date="2026-08-31",
        )
        version_at_creation = sample_set["version"]

        rejected = api.add_sample_set_home(
            sample_set["id"],
            factories.sample_set_membership_payload(outside["id"], version_at_creation),
            make_certified_rater_headers(rater["id"]),
        )
        validate_error(rejected, ERR_HOME_PERMIT_OUTSIDE_WINDOW, 422)

        accepted = api.add_sample_set_home(
            sample_set["id"],
            factories.sample_set_membership_payload(
                on_the_end_date["id"], version_at_creation
            ),
            make_certified_rater_headers(rater["id"]),
        )
        validate_success(accepted, 201)

        assert_home_sampling_state(
            get_home(api, outside["id"]),
            sampling_role="UNASSIGNED",
            sample_set_id=None,
        )
        assert_home_sampling_state(
            get_home(api, on_the_end_date["id"]),
            sampling_role="MEMBER",
            sample_set_id=sample_set["id"],
        )
        stored_set = get_sample_set(api, sample_set["id"])
        assert_sample_set_counters(stored_set, member_count=1)
        assert stored_set["version"] == version_at_creation + 1, stored_set
        assert_coverage_ledger(
            get_subdivision(api, subdivision["id"]),
            homes_count=2,
            sampled_home_count=1,
            unsampled_home_count=1,
        )

    def test_home_from_another_subdivision_cannot_join_the_set(self, api):
        """§3.5: "The home must belong to the same subdivision as the set, or the addition fails with `ERR_HOME_SUBDIVISION_MISMATCH`."

        Design: Corner/validations/home_from_another_subdivision_rejected_on_membership_add
        """
        builder = create_builder(api, name="Bristol Homes")
        foxglove = create_subdivision(
            api, builder["id"], name="Foxglove", sampling_enabled=True
        )
        hawthorn = create_subdivision(
            api, builder["id"], name="Hawthorn", sampling_enabled=True
        )
        rater = create_rater(api)
        hawthorn_plan = create_plan_model(api, hawthorn["id"], rater["id"])
        stranger = create_home(
            api,
            hawthorn["id"],
            hawthorn_plan["id"],
            builder["id"],
            lot_number="H-5401",
            permit_date="2026-08-05",
        )
        sample_set = create_sample_set(
            api,
            foxglove["id"],
            rater["id"],
            window_start_date="2026-08-01",
            window_end_date="2026-08-31",
        )

        response = api.add_sample_set_home(
            sample_set["id"],
            factories.sample_set_membership_payload(
                stranger["id"], sample_set["version"]
            ),
            make_certified_rater_headers(rater["id"]),
        )
        validate_error(response, ERR_HOME_SUBDIVISION_MISMATCH, 422)

        stored_set = get_sample_set(api, sample_set["id"])
        assert_sample_set_counters(stored_set, member_count=0)
        assert stored_set["version"] == sample_set["version"], stored_set
        assert_home_sampling_state(get_home(api, stranger["id"]), sample_set_id=None)

    def test_home_already_in_a_set_outranks_the_permit_window_check(self, api):
        """§3.5: "The home must not already belong to some set — its `sample_set_id` must be null — or the addition fails with `ERR_HOME_ALREADY_SAMPLED`."

        §2.8: "This ordering is normative: when two checks would both fail on the same request, the lower-numbered one is the error the client sees."

        Design: Corner/validations/home_already_in_another_sample_set_rejected
        """
        builder = create_builder(api, name="Bristol Homes")
        subdivision = create_subdivision(
            api, builder["id"], name="Foxglove", sampling_enabled=True
        )
        rater = create_rater(api)
        plan = create_plan_model(api, subdivision["id"], rater["id"])
        home = create_home(
            api,
            subdivision["id"],
            plan["id"],
            builder["id"],
            lot_number="L-5601",
            permit_date="2026-08-05",
        )
        august = create_sample_set(
            api,
            subdivision["id"],
            rater["id"],
            window_start_date="2026-08-01",
            window_end_date="2026-08-31",
        )
        september = create_sample_set(
            api,
            subdivision["id"],
            rater["id"],
            window_start_date="2026-09-01",
            window_end_date="2026-09-30",
        )
        add_sample_member(api, august["id"], home["id"], rater["id"])

        response = api.add_sample_set_home(
            september["id"],
            factories.sample_set_membership_payload(home["id"], september["version"]),
            make_certified_rater_headers(rater["id"]),
        )
        validate_error(response, ERR_HOME_ALREADY_SAMPLED, 409)

        assert_home_sampling_state(
            get_home(api, home["id"]), sample_set_id=august["id"]
        )
        assert_sample_set_counters(get_sample_set(api, august["id"]), member_count=1)
        stored_september = get_sample_set(api, september["id"])
        assert_sample_set_counters(stored_september, member_count=0)
        assert stored_september["version"] == september["version"], stored_september

    def test_individually_flagged_home_outranks_membership_and_window_checks(self, api):
        """§3.5: "And a home whose `individual_testing_required` flag is true may never be sampled again, so its addition fails with `ERR_REPRESENTED_HOME_NOT_TESTABLE`."

        §3.5: "First, every member home other than the tested home has `individual_testing_required` set to `true` and its `sampling_role` set to `REPRESENTED`."

        §2.8: "This ordering is normative: when two checks would both fail on the same request, the lower-numbered one is the error the client sees."

        Design: Corner/validations/adding_an_individually_flagged_home_to_a_new_set_rejected
        """
        builder = create_builder(api, name="Bristol Homes")
        subdivision = create_subdivision(
            api, builder["id"], name="Foxglove", sampling_enabled=True
        )
        rater = create_rater(api, full_name="Rae Tarrant")
        inspector = create_rater(
            api, full_name="Ines Pike", cert_level="RATING_FIELD_INSPECTOR"
        )
        big_plan = create_plan_model(
            api,
            subdivision["id"],
            rater["id"],
            plan_code="BIG-3000",
            conditioned_floor_area_sqft=3000,
            conditioned_volume_cuft=27000,
            bedrooms=5,
            envelope_ua_btu_per_hr_f=520,
            design_ach50=4.00,
            design_duct_leakage_cfm25_per_100sqft=4.00,
            hvac_efficiency_index=8,
            pv_capacity_kw_dc=0,
        )
        standard_plan = create_plan_model(api, subdivision["id"], rater["id"])
        tested_home = create_home(
            api,
            subdivision["id"],
            big_plan["id"],
            builder["id"],
            lot_number="L-5801",
            permit_date="2026-08-05",
        )
        sibling_home = create_home(
            api,
            subdivision["id"],
            standard_plan["id"],
            builder["id"],
            lot_number="L-5802",
            permit_date="2026-08-05",
        )
        tested_rating = create_rating(api, tested_home["id"], rater["id"])
        august = create_sample_set(
            api,
            subdivision["id"],
            rater["id"],
            window_start_date="2026-08-01",
            window_end_date="2026-08-31",
        )
        september = create_sample_set(
            api,
            subdivision["id"],
            rater["id"],
            window_start_date="2026-09-01",
            window_end_date="2026-09-30",
        )
        add_sample_member(api, august["id"], tested_home["id"], rater["id"])
        add_sample_member(api, august["id"], sibling_home["id"], rater["id"])
        select_sample_set(api, august["id"])

        inspection = schedule_inspection(
            api,
            tested_rating["id"],
            inspector["id"],
            checkpoint="FINAL",
            scheduled_start_utc="2026-08-20T09:00:00Z",
            scheduled_end_utc="2026-08-20T11:00:00Z",
            air_handler_installed=True,
        )
        record_test(api, inspection["id"], inspector["id"], "BLOWER_DOOR", 1620)
        record_test(api, inspection["id"], inspector["id"], "DUCT_LEAKAGE_TOTAL", 150)
        complete_inspection(api, inspection["id"], inspector["id"])
        confirm_rating(api, tested_rating["id"], rater["id"])
        close_sample_set(api, august["id"])

        response = api.add_sample_set_home(
            september["id"],
            factories.sample_set_membership_payload(
                sibling_home["id"], september["version"]
            ),
            make_certified_rater_headers(rater["id"]),
        )
        validate_error(response, ERR_REPRESENTED_HOME_NOT_TESTABLE, 422)

        stored_rating = get_rating(api, tested_rating["id"])
        assert_index(stored_rating["confirmed_index"], 62)
        assert_rating_dimensions(stored_rating, compliance_status="FAILING")
        assert_sample_set_counters(
            get_sample_set(api, august["id"]), status="FAILED_EXPANDED"
        )
        assert_home_sampling_state(
            get_home(api, sibling_home["id"]),
            sampling_role="REPRESENTED",
            sample_set_id=august["id"],
            individual_testing_required=True,
        )
        stored_september = get_sample_set(api, september["id"])
        assert_sample_set_counters(stored_september, member_count=0)
        assert stored_september["version"] == september["version"], stored_september
        assert_builder_ledger(
            get_builder(api, builder["id"]), status="SAMPLING_SUSPENDED"
        )


class TestSamplingGates:
    def test_sampling_disabled_subdivision_cannot_open_a_sample_set(self, api):
        """§3.5: "A subdivision with `sampling_enabled` false refuses the request with `ERR_SAMPLING_NOT_ENABLED`, and a builder that is not `sampling_eligible` — because it is `CUSTOM`, because its `status` is `SAMPLING_SUSPENDED`, or because it has open corrective actions — refuses it with `ERR_BUILDER_SAMPLING_INELIGIBLE`."

        §3.1: "It is true when, and only when, all three of the following hold: `builder_type` is `PRODUCTION`, `status` is `ACTIVE`, and `open_corrective_action_count` is zero."

        Design: Corner/validations/sampling_disabled_subdivision_cannot_open_a_sample_set
        """
        builder = create_builder(api, name="Bristol Homes", builder_type="PRODUCTION")
        disabled = create_subdivision(
            api, builder["id"], name="Foxglove", sampling_enabled=False
        )
        enabled = create_subdivision(
            api, builder["id"], name="Hawthorn", sampling_enabled=True
        )
        rater = create_rater(api)

        refused = api.create_sample_set(
            factories.sample_set_payload(
                disabled["id"],
                window_start_date="2026-08-01",
                window_end_date="2026-08-31",
            ),
            make_certified_rater_headers(rater["id"]),
        )
        validate_error(refused, ERR_SAMPLING_NOT_ENABLED, 422)

        allowed = create_sample_set(
            api,
            enabled["id"],
            rater["id"],
            window_start_date="2026-08-01",
            window_end_date="2026-08-31",
        )
        assert allowed["subdivision_id"] == enabled["id"], allowed
        assert_sample_set_counters(allowed, status="FORMING")
        assert_builder_ledger(get_builder(api, builder["id"]), sampling_eligible=True)

        sets, _meta = validate_paginated(
            api.list_sample_sets(ADMIN_HEADERS, params={"subdivision_id": disabled["id"]})
        )
        assert_count(sets, 0)

    def test_selection_of_a_single_member_set_is_refused_on_size(self, api):
        """§3.5: "Selection requires the set to be `FORMING`, the subdivision to still have `sampling_enabled` true, the builder to still be `sampling_eligible`, and the membership to number at least two and at most seven — a set with fewer than two members cannot be selected and is refused with `ERR_SAMPLE_SET_SIZE_INVALID`."

        §2.8: "This ordering is normative: when two checks would both fail on the same request, the lower-numbered one is the error the client sees."

        Design: Corner/validations/select_with_a_single_member_rejected
        """
        builder = create_builder(api, name="Bristol Homes")
        subdivision = create_subdivision(
            api, builder["id"], name="Foxglove", sampling_enabled=True
        )
        rater = create_rater(api)
        plan = create_plan_model(api, subdivision["id"], rater["id"])
        home = create_home(
            api,
            subdivision["id"],
            plan["id"],
            builder["id"],
            lot_number="L-5701",
            permit_date="2026-08-05",
        )
        create_rating(api, home["id"], rater["id"])
        sample_set = create_sample_set(
            api,
            subdivision["id"],
            rater["id"],
            window_start_date="2026-08-01",
            window_end_date="2026-08-31",
        )
        add_sample_member(api, sample_set["id"], home["id"], rater["id"])

        response = api.select_sample_set(sample_set["id"], ADMIN_HEADERS)
        validate_error(response, ERR_SAMPLE_SET_SIZE_INVALID, 422)

        assert_sample_set_counters(
            get_sample_set(api, sample_set["id"]),
            status="FORMING",
            member_count=1,
            tested_home_id=None,
        )
        assert_home_sampling_state(get_home(api, home["id"]), sampling_role="MEMBER")


class TestRegistryAndQualityAssuranceGates:
    def test_failing_rating_is_refused_on_compliance_before_paperwork(
        self, api, confirmed_failing_world
    ):
        """§3.8: "A rating whose `compliance_status` is not `PASSING`, or whose `qa_status` is `QA_FAILED`, is refused with `ERR_RATING_NOT_COMPLIANT`."

        §2.8: "This ordering is normative: when two checks would both fail on the same request, the lower-numbered one is the error the client sees."

        Design: Corner/validations/failing_rating_registry_submission_rejected
        """
        world = confirmed_failing_world

        response = api.submit_rating_to_registry(world.rating_id, world.rater_headers)
        validate_error(response, ERR_RATING_NOT_COMPLIANT, 422)

        rating = get_rating(api, world.rating_id)
        assert_index(rating["confirmed_index"], 46)
        assert_rating_dimensions(
            rating, compliance_status="FAILING", registry_status="NOT_SUBMITTED"
        )
        assert rating["submitted_index"] is None, rating
        assert rating["file_locked"] is False, rating
        assert_builder_ledger(
            get_builder(api, world.builder_id), open_corrective_action_count=1
        )

    def test_open_qa_finding_action_blocks_submission_of_a_passing_file(self, api):
        """§3.8: "A rating carrying a corrective action in `OPEN`, `SUBMITTED`, `REJECTED` or `ESCALATED` status is refused with `ERR_OPEN_CORRECTIVE_ACTION` — note that this list includes `REJECTED`, so a builder mid-appeal blocks submission."

        §3.6: "A **`FAIL_MINOR`** is a finding, not a condemnation, and it deliberately does **not** move the quality-assurance dimension: the rating's `qa_status` stays `QA_SELECTED`, because only a major failure fails a file."

        §3.6: "Instead a corrective action with `reason` of `QA_FINDING` and `status` of `OPEN` is opened against the reviewed rating, which raises the builder's `open_corrective_action_count` by one and recomputes that builder's `sampling_eligible` to false."

        Design: Corner/validations/submission_with_open_qa_finding_action_rejected
        """
        world = build_confirmed_world(api, lot_number="L-6001")
        review = assign_qa_review(
            api, world.rating_id, world.qa_designee_id, review_type="FILE_REVIEW"
        )
        complete_qa_review(
            api,
            review["id"],
            world.qa_designee_id,
            "FAIL_MINOR",
            findings_note="Missing photo of the mechanical closet",
        )

        response = api.submit_rating_to_registry(world.rating_id, world.rater_headers)
        validate_error(response, ERR_OPEN_CORRECTIVE_ACTION, 409)

        rating = get_rating(api, world.rating_id)
        assert_rating_dimensions(
            rating,
            compliance_status="PASSING",
            qa_status="QA_SELECTED",
            registry_status="NOT_SUBMITTED",
        )
        assert_rater_standing(
            get_rater(api, world.rater_id), qa_files_owed=0, registry_hold=False
        )
        actions = corrective_actions_of(api, world.rating_id)
        assert_count(actions, 1)
        assert actions[0]["reason"] == "QA_FINDING", actions[0]
        assert actions[0]["status"] == "OPEN", actions[0]

    def test_reviewer_without_the_qa_designee_level_cannot_complete_a_review(self, api):
        """§2.11: "Only a `QA_DESIGNEE` may record a quality-assurance outcome."

        §2.11: "A mismatch — a rating field inspector attempting a confirmation, or a rater attempting to close out a quality-assurance review — is rejected with `ERR_CERT_LEVEL_INSUFFICIENT` (HTTP 422)."

        Design: Corner/validations/non_qa_designee_reviewer_cannot_complete_review
        """
        world = build_confirmed_world(api, lot_number="L-6101")
        second_inspector = create_rater(
            api, full_name="Dara Holm", cert_level="RATING_FIELD_INSPECTOR"
        )
        review = assign_qa_review(
            api, world.rating_id, second_inspector["id"], review_type="FILE_REVIEW"
        )

        response = api.complete_qa_review(
            review["id"],
            factories.qa_review_completion_payload("PASS", findings_note="File complete"),
            make_qa_designee_headers(second_inspector["id"]),
        )
        validate_error(response, ERR_CERT_LEVEL_INSUFFICIENT, 422)

        stored_review = get_qa_review(api, review["id"])
        assert stored_review["status"] == "ASSIGNED", stored_review
        assert stored_review["result"] is None, stored_review
        assert_rating_dimensions(
            get_rating(api, world.rating_id), qa_status="QA_SELECTED"
        )
        assert_rater_standing(get_rater(api, world.rater_id), qa_completed_count=0)

    def test_rating_rater_cannot_be_assigned_as_its_own_qa_reviewer(self, api):
        """§2.11: "A quality-assurance review may never be assigned to, nor completed by, the rating's own rater of record: the review's `reviewer_id` must differ from the rating's `rater_id`."

        §2.11: "Either violation yields `ERR_SEGREGATION_OF_DUTIES` (HTTP 422), and it is checked both when the review is assigned and again when its outcome is recorded."

        Design: Corner/validations/rating_rater_cannot_be_assigned_as_qa_reviewer
        """
        world = build_confirmed_world(api, lot_number="L-6201")

        response = api.create_qa_review(
            factories.qa_review_payload(
                world.rating_id, world.rater_id, review_type="FILE_REVIEW"
            ),
            ADMIN_HEADERS,
        )
        validate_error(response, ERR_SEGREGATION_OF_DUTIES, 422)

        reviews, _meta = validate_paginated(
            api.list_qa_reviews(ADMIN_HEADERS, params={"rating_id": world.rating_id})
        )
        assert_count(reviews, 0)
        assert_rating_dimensions(
            get_rating(api, world.rating_id), qa_status="NOT_SELECTED"
        )


class TestFiscalGates:
    def test_utility_issuance_beyond_the_program_budget_is_refused(self, api):
        """§3.9: "The builder's `utility_program_budget_cents` is a hard ceiling on how much utility-programme money may be certified against it at once: if the builder's current `certified_incentive_cents` plus this package's newly computed certified amount would exceed `utility_program_budget_cents`, the issuance is refused with `ERR_PROGRAM_BUDGET_EXCEEDED`."

        §3.9: "Drafting computes the **provisional** amount into `provisional_amount_cents`, and issuance recomputes the very same routine in its **certified** variant into `certified_amount_cents`."

        Design: Corner/validations/utility_issue_over_program_budget_rejected
        """
        world = build_confirmed_world(
            api,
            builder_name="Thrift Homes",
            utility_program_budget_cents=1000,
            lot_number="L-6301",
        )
        package = draft_package(
            api, world.rating_id, world.builder_id, "UTILITY_PROGRAM"
        )

        response = api.issue_document_package(package["id"], ADMIN_HEADERS)
        validate_error(response, ERR_PROGRAM_BUDGET_EXCEEDED, 422)

        packages = list_packages(api, world.rating_id)
        stored = next(item for item in packages if item["id"] == package["id"])
        assert_package_state(
            stored,
            status="DRAFT",
            provisional_amount_cents=132500,
            certified_amount_cents=None,
        )
        assert stored["issued_at"] is None, stored
        assert_builder_ledger(
            get_builder(api, world.builder_id), certified_incentive_cents=0
        )
