"""Leak survey pipeline, repair authorization budget, and segregation of duties."""
import pytest

from test_helpers import (
    ApiErrorId,
    assert_leak_survey,
    assert_leak_tag,
    create_demand_profile,
    create_facility,
    create_leak_survey,
    create_leak_tag,
    create_verified_survey,
    get_facility,
    lock_demand_profile,
    make_energy_engineer_headers,
    make_facility_manager_headers,
    setup_savings_pipeline,
    validate_error,
    validate_paginated,
    validate_success,
)

ENGINEER = make_energy_engineer_headers("eng-1")


class TestSurveySubmission:
    def test_empty_survey_submit_rejected(self, api):
        """PRD §3.4: "Submission moves the survey from `DRAFT` to `SUBMITTED`. A
        survey must contain at least one tag to be submitted — an empty survey is
        rejected with `ERR_EMPTY_SURVEY` (HTTP 422)."

        Design: Corner/validations/corner_empty_survey_submit_rejected
        """
        facility = create_facility(name="F-ES")
        survey = create_leak_survey(facility["id"])

        resp = api.submit_leak_survey(survey["id"], make_energy_engineer_headers("eng-1"))
        validate_error(resp, ApiErrorId.ERR_EMPTY_SURVEY, 422)
        survey = validate_success(api.get_leak_survey(survey["id"], ENGINEER))
        assert survey["status"] == "DRAFT", "rejected submit must leave the survey DRAFT"

    def test_survey_submit_cascades_tags_to_quoted(self, api):
        """PRD §3.4: "Submitting records the caller in `submitted_by_user_id` and
        cascades every contained tag from `TAGGED` to `QUOTED`."

        Design: Corner/state_machines/corner_survey_submit_cascades_tags_to_quoted
        """
        facility = create_facility(name="F-SM2")
        survey = create_leak_survey(facility["id"])
        t1 = create_leak_tag(survey["id"], 
            location_description="a", cfm_loss=3.0, repair_quote_cents=100000)
        t2 = create_leak_tag(survey["id"], 
            location_description="b", cfm_loss=4.0, repair_quote_cents=120000)

        survey = validate_success(
            api.submit_leak_survey(survey["id"], make_energy_engineer_headers("eng-1"))
        )
        assert_leak_survey(survey)
        assert survey["status"] == "SUBMITTED"
        assert survey["submitted_by_user_id"] == "eng-1"

        data, meta = validate_paginated(
            api.list_leak_tags(ENGINEER, params={"survey_id": survey["id"]})
        )
        assert meta["total_count"] == 2
        statuses = {t["id"]: t["status"] for t in data}
        assert statuses[t1["id"]] == "QUOTED"
        assert statuses[t2["id"]] == "QUOTED"


class TestSurveyVerification:
    def test_survey_verify_from_draft_rejected(self, api):
        """PRD §3.4: "Verification is a second pair of eyes: the `EnergyEngineer`
        who verifies a `SUBMITTED` survey must not be the one who submitted it, and
        a match between the caller and `submitted_by_user_id` is rejected with
        `ERR_SEGREGATION_OF_DUTIES` (HTTP 403)."
        PRD §2.9: "An undeclared transition yields `ERR_INVALID_STATE_TRANSITION`
        (HTTP 409); named gates yield their own errors such as
        `ERR_FACILITY_NOT_ACTIVE` or `ERR_PROFILE_NOT_LOCKED`."

        Design: Corner/state_machines/corner_survey_verify_from_draft_rejected
        """
        facility = create_facility(name="F-SM1")
        survey = create_leak_survey(facility["id"])
        create_leak_tag(survey["id"], 
            location_description="x", cfm_loss=3.0, repair_quote_cents=100000)

        resp = api.verify_leak_survey(survey["id"], make_energy_engineer_headers("eng-9"))
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE_TRANSITION, 409)
        survey = validate_success(api.get_leak_survey(survey["id"], ENGINEER))
        assert survey["status"] == "DRAFT"
        assert survey.get("verified_by_user_id") is None

    def test_verify_assigns_severity_and_priority_rank(self, api):
        """PRD §3.4: "Each tag receives a `severity` — `LOW` when its `cfm_loss` is
        below 2.0, `MEDIUM` when the loss is at least 2.0 and at most 10.0, and
        `HIGH` above 10.0 — and a `priority_rank`: every tag in the survey,
        regardless of its status at verify time, is ordered by `cfm_loss`
        descending, with ties broken by `repair_quote_cents` ascending and any
        remaining ties by `created_at` ascending (never by identifier), and ranks
        are assigned as dense 1-based integers in that order. The survey itself
        gains `total_leak_cfm`, the sum of its tags' `cfm_loss` at one decimal, and
        `tag_count`, the number of tags it contains."

        Design: Corner/state_machines/corner_verify_assigns_severity_and_priority_rank
        """
        facility = create_facility(name="F-RANK")
        survey = create_leak_survey(facility["id"])
        specs = [
            ("L1", 12.5, 400000),
            ("L2", 10.0, 90000),
            ("L3", 10.0, 100000),
            ("L4", 2.0, 300000),
            ("L5", 1.9, 50000),
        ]
        tags = [
            create_leak_tag(survey["id"], 
                location_description=loc, cfm_loss=cfm, repair_quote_cents=quote)
            for loc, cfm, quote in specs
        ]
        validate_success(
            api.submit_leak_survey(survey["id"], make_energy_engineer_headers("eng-1"))
        )

        survey = validate_success(
            api.verify_leak_survey(survey["id"], make_energy_engineer_headers("eng-2"))
        )
        assert survey["status"] == "VERIFIED"
        assert survey["total_leak_cfm"] == pytest.approx(36.4, abs=0.01)
        assert survey["tag_count"] == 5

        expected = {
            tags[0]["id"]: ("HIGH", 1),
            tags[1]["id"]: ("MEDIUM", 2),  # 10.0 is the inclusive MEDIUM upper bound; lower quote wins the tie
            tags[2]["id"]: ("MEDIUM", 3),
            tags[3]["id"]: ("MEDIUM", 4),  # 2.0 is the inclusive MEDIUM lower bound
            tags[4]["id"]: ("LOW", 5),
        }
        for tag_id, (severity, rank) in expected.items():
            tag = validate_success(api.get_leak_tag(tag_id, ENGINEER))
            assert_leak_tag(tag)
            assert tag["severity"] == severity, f"tag {tag_id} severity"
            assert tag["priority_rank"] == rank, f"tag {tag_id} priority_rank"


class TestRepairBudget:
    def test_authorize_before_survey_verify_rejected(self, api):
        """PRD §3.4: "A `FacilityManager` authorizes a `QUOTED` tag, moving it to
        `REPAIR_AUTHORIZED`; the gates are evaluated in order — the tag's current
        state must permit the transition (`ERR_INVALID_STATE_TRANSITION`), the
        facility must be `ACTIVE` (`ERR_FACILITY_NOT_ACTIVE`), the parent survey
        must be `VERIFIED` (`ERR_SURVEY_NOT_VERIFIED`), and only then the fiscal
        gate: the facility's `repair_committed_cents` plus this tag's
        `repair_quote_cents` must not exceed the facility's `repair_budget_cents`,
        where landing exactly on the budget is allowed because the comparison is
        inclusive, and an overflow is rejected with `ERR_REPAIR_BUDGET_EXCEEDED`
        (HTTP 409)."

        Design: Corner/validations/corner_authorize_before_survey_verify_rejected
        """
        facility = create_facility(name="F-SNV")
        survey = create_leak_survey(facility["id"])
        tag = create_leak_tag(survey["id"], 
            location_description="a", cfm_loss=5.0, repair_quote_cents=100000)
        validate_success(
            api.submit_leak_survey(survey["id"], make_energy_engineer_headers("eng-1"))
        )

        resp = api.authorize_repair(tag["id"], make_facility_manager_headers(facility["id"]))
        validate_error(resp, ApiErrorId.ERR_SURVEY_NOT_VERIFIED, 409)
        tag = validate_success(api.get_leak_tag(tag["id"], ENGINEER))
        assert tag["status"] == "QUOTED", "rejected authorization must leave the tag QUOTED"

    def test_repair_budget_exceeded_and_exact_fit(self, api):
        """PRD §3.4: "the facility's `repair_committed_cents` plus this tag's
        `repair_quote_cents` must not exceed the facility's `repair_budget_cents`,
        where landing exactly on the budget is allowed because the comparison is
        inclusive, and an overflow is rejected with `ERR_REPAIR_BUDGET_EXCEEDED`
        (HTTP 409). Authorization commits funds: the facility's
        `repair_committed_cents` grows by the quoted amount."

        Design: Corner/validations/corner_repair_budget_exceeded_and_exact_fit
        """
        facility_a = create_facility(name="FA-BUD", repair_budget_cents=400000)
        _, tags_a = create_verified_survey(
            facility_a["id"],
            tags=[{"location_description": "a", "cfm_loss": 5.0, "repair_quote_cents": 400001}],
        )
        facility_b = create_facility(name="FB-BUD", repair_budget_cents=400000)
        _, tags_b = create_verified_survey(
            facility_b["id"],
            tags=[{"location_description": "b", "cfm_loss": 5.0, "repair_quote_cents": 400000}],
        )

        resp = api.authorize_repair(
            tags_a[0]["id"], make_facility_manager_headers(facility_a["id"])
        )
        validate_error(resp, ApiErrorId.ERR_REPAIR_BUDGET_EXCEEDED, 409)

        tag_b = validate_success(
            api.authorize_repair(
                tags_b[0]["id"], make_facility_manager_headers(facility_b["id"])
            )
        )
        assert tag_b["status"] == "REPAIR_AUTHORIZED", "exact-budget authorization must succeed"
        assert get_facility(facility_b["id"])["repair_committed_cents"] == 400000

    def test_state_beats_fiscal_error_reported(self, api):
        """PRD §3.4: "the gates are evaluated in order — the tag's current state
        must permit the transition (`ERR_INVALID_STATE_TRANSITION`), the facility
        must be `ACTIVE` (`ERR_FACILITY_NOT_ACTIVE`), the parent survey must be
        `VERIFIED` (`ERR_SURVEY_NOT_VERIFIED`), and only then the fiscal gate: the
        facility's `repair_committed_cents` plus this tag's `repair_quote_cents`
        must not exceed the facility's `repair_budget_cents`, where landing exactly
        on the budget is allowed because the comparison is inclusive, and an
        overflow is rejected with `ERR_REPAIR_BUDGET_EXCEEDED` (HTTP 409)."

        Design: Difficulty/priority_pair_validation_conflict/state_beats_fiscal_on_authorize_repair
        """
        facility = create_facility(name="F-PP1", repair_budget_cents=0)
        survey = create_leak_survey(facility["id"])
        tag = create_leak_tag(survey["id"], 
            location_description="valve", cfm_loss=5.0, repair_quote_cents=100000)

        resp = api.authorize_repair(tag["id"], make_facility_manager_headers(facility["id"]))
        # The tag is still TAGGED (survey never submitted): the from-state gate
        # reports before the fiscal gate is ever reached.
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE_TRANSITION, 409)

    def test_state_beats_fiscal_leaves_state_untouched(self, api):
        """PRD §3.4: "the gates are evaluated in order — the tag's current state
        must permit the transition (`ERR_INVALID_STATE_TRANSITION`), the facility
        must be `ACTIVE` (`ERR_FACILITY_NOT_ACTIVE`), the parent survey must be
        `VERIFIED` (`ERR_SURVEY_NOT_VERIFIED`), and only then the fiscal gate: the
        facility's `repair_committed_cents` plus this tag's `repair_quote_cents`
        must not exceed the facility's `repair_budget_cents`, where landing exactly
        on the budget is allowed because the comparison is inclusive, and an
        overflow is rejected with `ERR_REPAIR_BUDGET_EXCEEDED` (HTTP 409)."
        PRD §3.4: "Authorization commits funds: the facility's
        `repair_committed_cents` grows by the quoted amount."

        Design: Difficulty/priority_pair_validation_conflict/state_beats_fiscal_on_authorize_repair
        """
        facility = create_facility(name="F-PP1B", repair_budget_cents=0)
        survey = create_leak_survey(facility["id"])
        tag = create_leak_tag(survey["id"], 
            location_description="valve", cfm_loss=5.0, repair_quote_cents=100000)

        resp = api.authorize_repair(tag["id"], make_facility_manager_headers(facility["id"]))
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE_TRANSITION, 409)
        tag = validate_success(api.get_leak_tag(tag["id"], ENGINEER))
        assert tag["status"] == "TAGGED", "rejected authorization must leave the tag TAGGED"
        assert get_facility(facility["id"])["repair_committed_cents"] == 0, (
            "no funds may be committed by a rejected authorization"
        )


class TestWontFixCompensation:
    def test_wont_fix_releases_budget_commitment(self, api):
        """PRD §3.4: "A `FacilityManager` may mark a tag `WONT_FIX` — a second
        terminal state — from either `QUOTED` or `REPAIR_AUTHORIZED`. Walking away
        from an authorized repair releases the commitment: the facility's
        `repair_committed_cents` is reduced by the tag's `repair_quote_cents`, a
        compensating action that keeps the committed total honest."

        Design: Corner/state_machines/corner_wont_fix_releases_budget_commitment
        """
        facility = create_facility(name="F-WF", repair_budget_cents=5000000)
        _, tags = create_verified_survey(
            facility["id"],
            tags=[{"location_description": "L1", "cfm_loss": 12.5, "repair_quote_cents": 400000}],
        )
        tag = validate_success(
            api.authorize_repair(tags[0]["id"], make_facility_manager_headers(facility["id"]))
        )
        assert get_facility(facility["id"])["repair_committed_cents"] == 400000

        tag = validate_success(
            api.mark_wont_fix(tag["id"], make_facility_manager_headers(facility["id"]))
        )
        assert tag["status"] == "WONT_FIX"
        assert get_facility(facility["id"])["repair_committed_cents"] == 0, (
            "the compensating transition must return the committed total to zero"
        )


class TestSegregationOfDuties:
    def test_sod_survey_verify_and_measurement_close(self, api):
        """PRD §3.4: "Verification is a second pair of eyes: the `EnergyEngineer`
        who verifies a `SUBMITTED` survey must not be the one who submitted it, and
        a match between the caller and `submitted_by_user_id` is rejected with
        `ERR_SEGREGATION_OF_DUTIES` (HTTP 403)."
        PRD §3.6: "segregation of duties forbids the caller from being the engineer
        recorded in the baseline profile's `locked_by_user_id`
        (`ERR_SEGREGATION_OF_DUTIES`)."

        Design: Corner/rbac/corner_sod_survey_verify_and_measurement_close
        """
        pipeline = setup_savings_pipeline(
            name="F-SOD", advance_to="MEASUREMENT_OPEN", baseline_locker="eng-1"
        )
        facility = pipeline["facility"]
        # A survey submitted by eng-1 and never verified yet.
        survey = create_leak_survey(facility["id"])
        create_leak_tag(survey["id"], 
            location_description="a", cfm_loss=5.0, repair_quote_cents=100000)
        validate_success(
            api.submit_leak_survey(survey["id"], make_energy_engineer_headers("eng-1"))
        )
        # Post-measurement profile locked by a third engineer.
        post = create_demand_profile(
            facility["id"],
            window_start_date="2026-06-01",
            window_end_date="2026-06-30",
            measured_kwh=200000,
            measured_avg_cfm=300.0,
            measured_peak_cfm=480.0,
        )
        post = lock_demand_profile(facility["id"], post["id"], user_id="eng-3")

        resp = api.verify_leak_survey(survey["id"], make_energy_engineer_headers("eng-1"))
        validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES, 403)

        resp = api.close_measurement(
            pipeline["case"]["id"],
            {"post_profile_id": post["id"]},
            make_energy_engineer_headers("eng-1"),
        )
        validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES, 403)

        survey = validate_success(
            api.verify_leak_survey(survey["id"], make_energy_engineer_headers("eng-2"))
        )
        assert survey["status"] == "VERIFIED"

        case = validate_success(
            api.close_measurement(
                pipeline["case"]["id"],
                {"post_profile_id": post["id"]},
                make_energy_engineer_headers("eng-2"),
            )
        )
        assert case["savings_status"] == "MEASURED"
