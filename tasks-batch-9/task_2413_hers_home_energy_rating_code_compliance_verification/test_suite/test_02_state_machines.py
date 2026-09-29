"""Lifecycle transitions of the HERS Rating & Code Compliance API.

Checkpoint closure, confirmation and its re-confirmation self-loop, registry
submission and file locking, voiding and superseding, and the quality-assurance
review branches together with rater standing.
"""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import factories
from test_helpers.api_errors import (
    ERR_INVALID_STATE,
    ERR_MISSING_GOVERNING_TEST,
    ERR_RATING_FILE_LOCKED,
    ERR_RATING_VOID,
)
from test_helpers.assertions import (
    assert_builder_ledger,
    assert_count,
    assert_index,
    assert_normalized_value,
    assert_rater_standing,
    assert_rating_dimensions,
    assert_sample_set_counters,
)
from test_helpers.fixtures import (
    assign_qa_review,
    build_confirmed_world,
    build_rating_world,
    complete_inspection,
    complete_qa_review,
    confirm_rating,
    corrective_actions_of,
    create_home,
    create_rating,
    create_sample_set,
    get_builder,
    get_inspection,
    get_qa_review,
    get_rater,
    get_rating,
    record_test,
    reinstate_rater,
    registry_decision,
    review_corrective_action,
    run_final_checkpoint,
    schedule_inspection,
    set_clock,
    submit_corrective_action,
    submit_to_registry,
    void_rating,
)
from test_helpers.test_users import ADMIN_HEADERS


class TestSampleSetOpening:
    def test_sample_set_initial_state_is_forming_with_zero_members(self, api):
        """PRD §3.5: "A new set starts `FORMING` with `member_count`, `tested_member_count` and `represented_member_count` all zero, a null `tested_home_id` and a null `representative_index`."

        Design: Corner/state_machines/sample_set_initial_state_is_forming_with_zero_members
        """
        world = build_rating_world(
            api,
            with_home=False,
            with_rating=False,
            builder_name="Bristol Homes",
            subdivision_name="Foxglove",
            sampling_enabled=True,
        )

        data = create_sample_set(
            api,
            world.subdivision_id,
            world.rater_id,
            window_start_date="2026-08-01",
            window_end_date="2026-08-31",
        )

        assert_sample_set_counters(
            data,
            status="FORMING",
            member_count=0,
            tested_member_count=0,
            represented_member_count=0,
            tested_home_id=None,
            representative_index=None,
        )


class TestCheckpointClosure:
    def test_complete_rough_in_without_duct_test_rejected(self, api, rating_world):
        """PRD §3.3: "Closure requires that the checkpoint still be `SCHEDULED`, and that the checkpoint's mandatory tests actually exist: a `ROUGH_IN` checkpoint needs at least one `DUCT_LEAKAGE_TOTAL` measurement, and a `FINAL` checkpoint needs one `BLOWER_DOOR` measurement and one `DUCT_LEAKAGE_TOTAL` measurement."
        PRD §3.3: "A closure attempted without them is refused with `ERR_MISSING_GOVERNING_TEST`."

        Design: Corner/state_machines/complete_rough_in_without_duct_test_rejected
        """
        inspection = schedule_inspection(
            api,
            rating_world.rating_id,
            rating_world.inspector_id,
            checkpoint="ROUGH_IN",
            scheduled_start_utc="2026-08-18T09:00:00Z",
            scheduled_end_utc="2026-08-18T10:00:00Z",
            air_handler_installed=False,
        )

        validate_error(
            api.complete_inspection(inspection["id"], rating_world.inspector_headers),
            ERR_MISSING_GOVERNING_TEST,
            409,
        )

        assert get_inspection(api, inspection["id"])["status"] == "SCHEDULED"
        assert_rating_dimensions(
            get_rating(api, rating_world.rating_id), stage="PROJECTED"
        )

    def test_rough_in_completion_advances_rating_to_rough_in_verified(
        self, api, rating_world
    ):
        """PRD §2.7: "At a `ROUGH_IN` checkpoint the limit is 4.0 when `air_handler_installed` is true and 3.0 when it is false."
        PRD §3.3: "Given the required tests, closure branches on the failure counter alone: when `failed_test_count` is zero the checkpoint becomes `PASSED`, and when it is one or more the checkpoint becomes `FAILED`."
        PRD §3.3: "A `ROUGH_IN` checkpoint that closes as `PASSED` advances the rating's `stage` from `PROJECTED` to `ROUGH_IN_VERIFIED`."

        Design: Corner/state_machines/rough_in_completion_advances_rating_to_rough_in_verified
        """
        inspection = schedule_inspection(
            api,
            rating_world.rating_id,
            rating_world.inspector_id,
            checkpoint="ROUGH_IN",
            scheduled_start_utc="2026-08-18T09:00:00Z",
            scheduled_end_utc="2026-08-18T10:00:00Z",
            air_handler_installed=False,
        )
        test = record_test(
            api,
            inspection["id"],
            rating_world.inspector_id,
            "DUCT_LEAKAGE_TOTAL",
            60,
        )
        assert_normalized_value(test["normalized_value"], 2.50)
        assert_normalized_value(test["threshold_value"], 3.0)
        assert test["result"] == "PASS", test

        closed = complete_inspection(api, inspection["id"], rating_world.inspector_id)

        assert closed["status"] == "PASSED", closed
        assert closed["failed_test_count"] == 0, closed

        rating = get_rating(api, rating_world.rating_id)
        assert_rating_dimensions(
            rating, stage="ROUGH_IN_VERIFIED", compliance_status="UNDETERMINED"
        )
        assert rating["confirmed_index"] is None, rating


class TestConfirmation:
    def test_second_confirm_on_passing_rating_rejected(
        self, api, confirmed_passing_world
    ):
        """PRD §3.4: "It is admissible only when `compliance_status` is exactly `REMEDIATION_PENDING`, the file is not locked, and a `FINAL` checkpoint *newer* than the rating's current `confirmed_at` carries both governing measurements; confirming a `CONFIRMED` rating whose `compliance_status` is anything other than `REMEDIATION_PENDING` is `ERR_INVALID_STATE`."
        PRD §3.4: "The rater's `confirmed_rating_count` is **not** incremented a second time for the same rating, however many times it is re-confirmed."

        Design: Corner/state_machines/second_confirm_on_passing_rating_rejected
        """
        world = confirmed_passing_world

        validate_error(
            api.confirm_rating(world.rating_id, world.rater_headers),
            ERR_INVALID_STATE,
            409,
        )

        rating = get_rating(api, world.rating_id)
        assert_rating_dimensions(rating, stage="CONFIRMED", compliance_status="PASSING")
        assert_index(rating["confirmed_index"], 46)
        assert_rater_standing(get_rater(api, world.rater_id), confirmed_rating_count=1)

    def test_remediation_accepted_then_reconfirm_restores_passing(
        self, api, confirmed_failing_world
    ):
        """PRD §3.7: "An `ACCEPT` sets `status` to `ACCEPTED`, lowers the builder's `open_corrective_action_count` by one and recomputes the builder's `sampling_eligible` accordingly, and — where the rating's `compliance_status` was `FAILING` — moves that rating to `REMEDIATION_PENDING`, which is precisely the state that unlocks the re-confirmation self-loop of §3.4."
        PRD §3.4: "Re-confirmation re-evaluates the confirmed index and the compliance-path selection from the newest governing final measurements, rewrites `compliance_status` to `PASSING` or `FAILING` accordingly, writing `compliance_path` to the qualifying path or to `NONE`, and re-stamps `confirmed_at`."
        PRD §3.4: "The rater's `confirmed_rating_count` is **not** incremented a second time for the same rating, however many times it is re-confirmed."

        Design: Corner/state_machines/remediation_accepted_then_reconfirm_restores_passing
        """
        world = confirmed_failing_world
        actions = corrective_actions_of(api, world.rating_id)
        assert_count(actions, 1)
        assert actions[0]["reason"] == "THRESHOLD_FAILURE", actions
        submit_corrective_action(api, actions[0]["id"], world.builder_id)

        # A second, passing FINAL checkpoint recorded after the first confirmation.
        set_clock(api, "2026-08-23T09:00:00Z")
        run_final_checkpoint(
            api,
            world,
            blower_door=1080,
            duct_leakage=96,
            scheduled_start_utc="2026-08-23T09:00:00Z",
            scheduled_end_utc="2026-08-23T11:00:00Z",
        )

        action = review_corrective_action(
            api, actions[0]["id"], "ACCEPT", note="Re-test verified"
        )
        assert action["status"] == "ACCEPTED", action
        assert action["attempt_count"] == 1, action
        assert_builder_ledger(
            get_builder(api, world.builder_id),
            open_corrective_action_count=0,
            sampling_eligible=True,
        )

        rating = confirm_rating(api, world.rating_id, world.rater_id)

        assert_rating_dimensions(rating, stage="CONFIRMED", compliance_status="PASSING")
        assert rating["compliance_path"] == "ERI", rating
        assert_normalized_value(rating["confirmed_ach50"], 3.00)
        assert_index(rating["confirmed_index"], 46)
        assert_rater_standing(get_rater(api, world.rater_id), confirmed_rating_count=1)

    def test_confirm_on_voided_rating_rejected(self, api):
        """PRD §3.8: "`VOID` is terminal for the stage dimension, and a voided rating blocks scheduling, testing, checkpoint closure, confirmation, registry submission, review assignment, remediation submission, package drafting and package issuance, all with `ERR_RATING_VOID`."
        PRD §3.8: "Voiding sets `stage` to `VOID`, forces `compliance_status` to `FAILING`, and sets `file_locked` to true, and it runs a three-hop cascade over the money side of the file."

        Design: Corner/state_machines/confirm_on_voided_rating_rejected
        """
        world = build_rating_world(
            api, builder_name="Bristol Homes", subdivision_name="Foxglove", lot_number="L-3701"
        )
        run_final_checkpoint(api, world, blower_door=1080, duct_leakage=96)
        void_rating(api, world.rating_id, reason="Home withdrawn from the program by the owner")

        validate_error(
            api.confirm_rating(world.rating_id, world.rater_headers),
            ERR_RATING_VOID,
            409,
        )

        rating = get_rating(api, world.rating_id)
        assert_rating_dimensions(rating, stage="VOID", compliance_status="FAILING")
        assert rating["confirmed_index"] is None, rating
        assert rating["file_locked"] is True, rating
        assert_rater_standing(get_rater(api, world.rater_id), confirmed_rating_count=0)

    def test_superseding_rating_after_void_links_by_self_reference(
        self, api, rating_world
    ):
        """PRD §3.2: "If the home already has a rating whose `stage` is any of `PROJECTED`, `ROUGH_IN_VERIFIED`, `CONFIRMED` or `REGISTERED`, a second rating is refused with `ERR_DUPLICATE_ACTIVE_RATING` — unless the request's `supersedes_rating_id` names that very rating *and* that rating has either reached `stage` `VOID` or been failed with `qa_status` of `QA_FAILED`."
        PRD §3.2: "Ratings can be read individually and listed with optional filters on `home_id`, `rater_id`, `plan_model_id`, `supersedes_rating_id` and `stage`."

        Design: Corner/state_machines/superseding_rating_after_void_links_by_self_reference
        """
        voided_id = rating_world.rating_id
        void_rating(api, voided_id, reason="Wrong plan model selected at intake")

        data = validate_success(
            api.create_rating(
                factories.rating_payload(
                    rating_world.home_id,
                    rating_world.rater_id,
                    supersedes_rating_id=voided_id,
                ),
                rating_world.rater_headers,
            ),
            201,
        )

        assert data["supersedes_rating_id"] == voided_id, data
        assert_rating_dimensions(data, stage="PROJECTED")
        assert_index(data["projected_index"], 43)

        superseding, _meta = validate_paginated(
            api.list_ratings(ADMIN_HEADERS, params={"supersedes_rating_id": voided_id})
        )
        assert_count(superseding, 1)

        on_home, _meta = validate_paginated(
            api.list_ratings(ADMIN_HEADERS, params={"home_id": rating_world.home_id})
        )
        assert_count(on_home, 2)


class TestRegistrySubmission:
    def test_registry_rejection_unlocks_file_and_resubmission_returns_to_pending(
        self, api, confirmed_passing_world
    ):
        """PRD §3.8: "A `REJECT` requires a `rejection_reason` in the payload; it sets `registry_status` to `REJECTED`, records the supplied text in `rejection_reason`, clears `submitted_index` back to null, and — importantly — sets `file_locked` back to false so that the file re-opens for correction."
        PRD §3.8: "From `REJECTED` the rater may submit again, at which point `rejection_reason` is cleared to null, `registry_status` returns to `PENDING` and the file locks once more, giving the cycle pending → rejected → pending."

        Design: Corner/state_machines/registry_rejection_unlocks_file_and_resubmission_returns_to_pending
        """
        world = confirmed_passing_world
        submit_to_registry(api, world.rating_id, world.rater_id)

        rejected = registry_decision(
            api,
            world.rating_id,
            outcome="REJECT",
            rejection_reason="Duct leakage worksheet page missing",
        )
        assert_rating_dimensions(rejected, registry_status="REJECTED")
        assert rejected["rejection_reason"] == "Duct leakage worksheet page missing", rejected
        assert rejected["submitted_index"] is None, rejected
        assert rejected["file_locked"] is False, rejected

        resubmitted = submit_to_registry(api, world.rating_id, world.rater_id)

        assert_rating_dimensions(
            resubmitted, stage="CONFIRMED", registry_status="PENDING"
        )
        assert resubmitted["rejection_reason"] is None, resubmitted
        assert_index(resubmitted["submitted_index"], 46)
        assert resubmitted["file_locked"] is True, resubmitted
        assert resubmitted["registry_confirmation_number"] is None, resubmitted

    def test_registry_acceptance_registers_and_locks_the_rating_file(
        self, api, registered_world
    ):
        """PRD §3.8: "An `ACCEPT` requires a `confirmation_number` in the payload; it sets `registry_status` to `ACCEPTED`, records the supplied number in `registry_confirmation_number`, advances the rating's `stage` from `CONFIRMED` to `REGISTERED`, and leaves `file_locked` true."
        PRD §3.8: "From that point the lock blocks any further field work on the file: scheduling a checkpoint, recording a measurement, closing a checkpoint, confirming and re-submitting are all refused with `ERR_RATING_FILE_LOCKED`."

        Design: Corner/state_machines/registry_acceptance_registers_and_locks_the_rating_file
        """
        world = registered_world
        rating = get_rating(api, world.rating_id)

        assert_rating_dimensions(rating, stage="REGISTERED", registry_status="ACCEPTED")
        assert rating["registry_confirmation_number"] == "RESNET-2026-004417", rating
        assert rating["file_locked"] is True, rating

        validate_error(
            api.create_inspection(
                factories.inspection_payload(
                    world.rating_id,
                    world.inspector_id,
                    checkpoint="FINAL",
                    scheduled_start_utc="2026-08-25T09:00:00Z",
                    scheduled_end_utc="2026-08-25T11:00:00Z",
                    air_handler_installed=True,
                ),
                world.inspector_headers,
            ),
            ERR_RATING_FILE_LOCKED,
            409,
        )

        inspections, _meta = validate_paginated(
            api.list_inspections(ADMIN_HEADERS, params={"rating_id": world.rating_id})
        )
        assert_count(inspections, 1)


class TestQualityAssuranceReview:
    def test_qa_review_pass_closes_the_file_without_touching_rater_standing(self, api):
        """PRD §3.6: "The rating's `qa_status` moves from `QA_SELECTED` to `QA_PASSED`."
        PRD §3.6: "The reviewee's `qa_failure_count` does not move and their `certification_status` does not move."
        PRD §3.6: "No corrective action is opened, no package is touched, no sample set is voided, and the builder's counters do not move."
        PRD §3.6: "In all three branches the review's `status` becomes `COMPLETED`, the supplied `result` and `findings_note` are recorded, the reviewee rater's `qa_completed_count` rises by one, and that rater's quota is re-derived afterwards."

        Design: Corner/state_machines/qa_review_pass_closes_the_file_without_touching_rater_standing
        """
        world = build_confirmed_world(
            api,
            builder_name="Bristol Homes",
            subdivision_name="Foxglove",
            lot_number="L-6801",
            permit_date="2026-08-05",
        )
        review = assign_qa_review(
            api, world.rating_id, world.qa_designee_id, review_type="FILE_REVIEW"
        )

        completed = complete_qa_review(
            api,
            review["id"],
            world.qa_designee_id,
            "PASS",
            findings_note="File complete and consistent with the field data",
        )

        assert completed["status"] == "COMPLETED", completed
        assert completed["result"] == "PASS", completed

        rating = get_rating(api, world.rating_id)
        assert_rating_dimensions(rating, qa_status="QA_PASSED")
        assert_index(rating["confirmed_index"], 46)

        assert_rater_standing(
            get_rater(api, world.rater_id),
            certification_status="ACTIVE",
            qa_failure_count=0,
            confirmed_rating_count=1,
            qa_completed_count=1,
            qa_files_owed=0,
            registry_hold=False,
        )
        assert_builder_ledger(
            get_builder(api, world.builder_id),
            open_corrective_action_count=0,
            status="ACTIVE",
        )
        assert_count(corrective_actions_of(api, world.rating_id), 0)

    def test_rater_reinstatement_from_probation_clears_failure_count(self, api):
        """PRD §3.6: "The reviewee's `qa_failure_count` rises by one and their `certification_status` steps one notch down the disciplinary ladder — from `ACTIVE` to `PROBATION`, or from `PROBATION` to `SUSPENDED` if they were already on probation."
        PRD §3.6: "A **`FAIL_MINOR`** is a finding, not a condemnation, and it deliberately does **not** move the quality-assurance dimension: the rating's `qa_status` stays `QA_SELECTED`, because only a major failure fails a file."
        PRD §3.6: "Instead a corrective action with `reason` of `QA_FINDING` and `status` of `OPEN` is opened against the reviewed rating, which raises the builder's `open_corrective_action_count` by one and recomputes that builder's `sampling_eligible` to false."
        PRD §3.6: "Reinstatement sets `certification_status` back to `ACTIVE`, resets `qa_failure_count` to zero, and re-derives the quota at the standard 0.10 rate, which normally clears `qa_files_owed` and `registry_hold`."
        PRD §3.6: "Reinstatement never touches `cert_expires_at`, so a rater whose certificate has lapsed remains `EXPIRED` in `effective_certification_status` and remains blocked no matter how many times they are reinstated — the fix for expiry is a new certificate, not a reinstatement."

        Design: Corner/state_machines/rater_reinstatement_from_probation_clears_failure_count
        """
        world = build_confirmed_world(
            api,
            builder_name="Bristol Homes",
            subdivision_name="Foxglove",
            lot_number="L-3601",
        )
        review = assign_qa_review(
            api, world.rating_id, world.qa_designee_id, review_type="FILE_REVIEW"
        )
        complete_qa_review(
            api,
            review["id"],
            world.qa_designee_id,
            "FAIL_MINOR",
            findings_note="Duct schedule page missing",
        )

        assert_rater_standing(
            get_rater(api, world.rater_id),
            certification_status="PROBATION",
            qa_failure_count=1,
        )
        assert_rating_dimensions(get_rating(api, world.rating_id), qa_status="QA_SELECTED")
        actions = corrective_actions_of(api, world.rating_id)
        assert_count(actions, 1)
        assert actions[0]["reason"] == "QA_FINDING", actions
        assert actions[0]["status"] == "OPEN", actions

        rater = reinstate_rater(
            api,
            world.rater_id,
            training_completed_at="2026-08-30T00:00:00Z",
            note="Remedial file-quality training completed",
        )

        assert_rater_standing(
            rater,
            certification_status="ACTIVE",
            effective_certification_status="ACTIVE",
            qa_failure_count=0,
            qa_completed_count=1,
            qa_files_owed=0,
            registry_hold=False,
        )
        assert rater["cert_expires_at"].startswith("2027-06-30T00:00:00"), rater

    def test_second_qa_failure_suspends_the_rater_then_reinstatement_restores_active(
        self, api
    ):
        """PRD §3.6: "A first qualifying failure — minor or major — takes `certification_status` from `ACTIVE` to `PROBATION`; a second takes it from `PROBATION` to `SUSPENDED`, at which point that person may open no ratings, perform no confirmations, run no inspections and submit no files."
        PRD §3.6: "Provider staff may reinstate a rater from either `PROBATION` or `SUSPENDED` after remedial training, supplying the `training_completed_at` instant and an optional `note`."
        PRD §3.6: "Reinstatement sets `certification_status` back to `ACTIVE`, resets `qa_failure_count` to zero, and re-derives the quota at the standard 0.10 rate, which normally clears `qa_files_owed` and `registry_hold`."

        Design: Corner/state_machines/second_qa_failure_suspends_the_rater_then_reinstatement_restores_active
        """
        world = build_rating_world(
            api,
            builder_name="Bristol Homes",
            subdivision_name="Foxglove",
            with_home=False,
            with_rating=False,
        )
        ratings = []
        for lot_number, permit_date, start, end in (
            ("L-6901", "2026-08-05", "2026-08-20T09:00:00Z", "2026-08-20T11:00:00Z"),
            ("L-6902", "2026-08-06", "2026-08-21T09:00:00Z", "2026-08-21T11:00:00Z"),
        ):
            home = create_home(
                api,
                world.subdivision_id,
                world.plan_model_id,
                world.builder_id,
                lot_number=lot_number,
                permit_date=permit_date,
            )
            world.home = home
            world.rating = create_rating(api, home["id"], world.rater_id)
            run_final_checkpoint(
                api,
                world,
                blower_door=1080,
                duct_leakage=96,
                scheduled_start_utc=start,
                scheduled_end_utc=end,
            )
            ratings.append(confirm_rating(api, world.rating_id, world.rater_id))

        reviews = [
            assign_qa_review(
                api, rating["id"], world.qa_designee_id, review_type="FILE_REVIEW"
            )
            for rating in ratings
        ]

        complete_qa_review(
            api,
            reviews[0]["id"],
            world.qa_designee_id,
            "FAIL_MINOR",
            findings_note="Missing duct schedule page",
        )
        assert_rater_standing(
            get_rater(api, world.rater_id),
            certification_status="PROBATION",
            qa_failure_count=1,
        )

        complete_qa_review(
            api,
            reviews[1]["id"],
            world.qa_designee_id,
            "FAIL_MINOR",
            findings_note="Blower-door worksheet unsigned",
        )
        assert_rater_standing(
            get_rater(api, world.rater_id),
            certification_status="SUSPENDED",
            qa_failure_count=2,
        )

        rater = reinstate_rater(
            api,
            world.rater_id,
            training_completed_at="2026-08-30T00:00:00Z",
            note="Remedial file-quality training completed",
        )

        assert_rater_standing(
            rater,
            certification_status="ACTIVE",
            effective_certification_status="ACTIVE",
            qa_failure_count=0,
            confirmed_rating_count=2,
            qa_completed_count=2,
            qa_files_owed=0,
            registry_hold=False,
        )
        assert rater["cert_expires_at"].startswith("2027-06-30T00:00:00"), rater

        for rating, review in zip(ratings, reviews):
            assert_rating_dimensions(
                get_rating(api, rating["id"]), qa_status="QA_SELECTED"
            )
            assert get_qa_review(api, review["id"])["status"] == "COMPLETED"
            actions = corrective_actions_of(api, rating["id"])
            assert_count(actions, 1)
            assert actions[0]["reason"] == "QA_FINDING", actions
            assert actions[0]["status"] == "OPEN", actions

        assert_builder_ledger(
            get_builder(api, world.builder_id),
            open_corrective_action_count=2,
            sampling_eligible=False,
            status="ACTIVE",
        )
