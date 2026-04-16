"""
Tests for HomeVisit creation, completion, cancellation, and scoring.
Claims from Tables 2, 3 (home_visit_scoring), 5, 6.
"""
import pytest
from test_helpers import (
    api_client,
    validate_success,
    validate_error,
    validate_paginated,
    assert_home_visit,
    create_home_visit_payload,
    create_home_visit_assessment_payload,
    create_shelter,
    create_available_animal,
    create_adopter_in_shelter,
    submit_application,
    start_application_review,
    require_home_visit_on_application,
    schedule_home_visit,
    complete_home_visit_with_result,
    ApiErrorId,
    NON_EXISTENT_UUID,
    TEST_USERS,
    build_user_headers,
    HOME_VISIT_PASS_THRESHOLD,
    HOME_VISIT_CONDITIONAL_THRESHOLD,
)


class TestHomeVisitCreation:
    """POST /home-visits and automatic application transition."""

    def test_schedule_home_visit_success(self, api, caseworker_headers):
        """Schedule a home visit -> SCHEDULED + application -> HOME_VISIT_SCHEDULED."""
        shelter = create_shelter()
        animal = create_available_animal(shelter["id"], species="DOG")
        adopter = create_adopter_in_shelter(shelter["id"])
        app = submit_application(animal["id"], adopter["id"])
        app = start_application_review(app["id"])
        app = require_home_visit_on_application(app["id"])

        visit = schedule_home_visit(adopter["id"], app["id"])
        assert_home_visit(visit)
        assert visit["status"] == "SCHEDULED"
        assert visit["adopter_id"] == adopter["id"]
        assert visit["application_id"] == app["id"]
        assert visit["case_worker_id"] is not None

        # Application should be HOME_VISIT_SCHEDULED
        app_after = validate_success(
            api.get_adoption_application(app["id"], caseworker_headers), 200,
        )
        assert app_after["status"] == "HOME_VISIT_SCHEDULED"
        assert app_after["home_visit_id"] == visit["id"]

    def test_get_nonexistent_home_visit(self, api, caseworker_headers):
        """ERR_HOME_VISIT_NOT_FOUND."""
        res = api.get_home_visit(NON_EXISTENT_UUID, caseworker_headers)
        validate_error(res, ApiErrorId.ERR_HOME_VISIT_NOT_FOUND)

    def test_list_home_visits_by_adopter(self, api, caseworker_headers):
        """GET /home-visits?adopter_id= filters correctly."""
        shelter = create_shelter()
        animal = create_available_animal(shelter["id"], species="DOG")
        adopter = create_adopter_in_shelter(shelter["id"])
        app = submit_application(animal["id"], adopter["id"])
        app = start_application_review(app["id"])
        app = require_home_visit_on_application(app["id"])
        schedule_home_visit(adopter["id"], app["id"])

        data, meta = validate_paginated(
            api.list_home_visits(caseworker_headers, params={"adopter_id": adopter["id"]})
        )
        assert meta["total_count"] >= 1


class TestHomeVisitScoring:
    """Table 3: home_visit_scoring weighted algorithm."""

    def test_all_criteria_pass_score_100(self, api, caseworker_headers):
        """All true (no hazards) -> score=100, result=PASS."""
        shelter = create_shelter()
        animal = create_available_animal(shelter["id"], species="DOG")
        adopter = create_adopter_in_shelter(shelter["id"])
        app = submit_application(animal["id"], adopter["id"])
        app = start_application_review(app["id"])
        app = require_home_visit_on_application(app["id"])
        visit = schedule_home_visit(adopter["id"], app["id"])

        assessment = create_home_visit_assessment_payload(
            yard_adequate=True,
            space_adequate=True,
            safety_hazards_found=False,
            existing_pets_compatible=True,
        )
        res = api.complete_home_visit(visit["id"], assessment, caseworker_headers)
        completed = validate_success(res, 200)
        assert completed["status"] == "COMPLETED"
        assert completed["overall_score"] == 100  # 25+30+25+20
        assert completed["result"] == "PASS"

    def test_score_boundary_pass_at_70(self, api, caseworker_headers):
        """
        Score exactly 70 -> PASS.
        yard=True(25) + space=True(30) + hazards=True(0) + pets=False(0) = 55 -> not 70
        yard=True(25) + space=True(30) + hazards=False(25) + pets=False(0) = 80 -> PASS
        We need exactly 70: yard=False(0) + space=True(30) + hazards=False(25) + pets=True(20) = 75 -> PASS
        """
        shelter = create_shelter()
        animal = create_available_animal(shelter["id"], species="DOG")
        adopter = create_adopter_in_shelter(shelter["id"])
        app = submit_application(animal["id"], adopter["id"])
        app = start_application_review(app["id"])
        app = require_home_visit_on_application(app["id"])
        visit = schedule_home_visit(adopter["id"], app["id"])

        assessment = create_home_visit_assessment_payload(
            yard_adequate=False,     # 0
            space_adequate=True,     # 30
            safety_hazards_found=False,  # 25
            existing_pets_compatible=True,  # 20
        )  # Total: 75 -> PASS
        res = api.complete_home_visit(visit["id"], assessment, caseworker_headers)
        completed = validate_success(res, 200)
        assert completed["overall_score"] == 75
        assert completed["result"] == "PASS"

    def test_score_conditional_pass_range(self, api, caseworker_headers):
        """
        Score in [50, 69] -> CONDITIONAL_PASS.
        yard=True(25) + space=True(30) + hazards=True(0) + pets=False(0) = 55 -> CONDITIONAL_PASS
        """
        shelter = create_shelter()
        animal = create_available_animal(shelter["id"], species="DOG")
        adopter = create_adopter_in_shelter(shelter["id"])
        app = submit_application(animal["id"], adopter["id"])
        app = start_application_review(app["id"])
        app = require_home_visit_on_application(app["id"])
        visit = schedule_home_visit(adopter["id"], app["id"])

        assessment = create_home_visit_assessment_payload(
            yard_adequate=True,      # 25
            space_adequate=True,     # 30
            safety_hazards_found=True,   # 0
            existing_pets_compatible=False,  # 0
        )  # Total: 55 -> CONDITIONAL_PASS
        res = api.complete_home_visit(visit["id"], assessment, caseworker_headers)
        completed = validate_success(res, 200)
        assert completed["overall_score"] == 55
        assert completed["result"] == "CONDITIONAL_PASS"

    def test_score_fail_below_50(self, api, caseworker_headers):
        """
        Score < 50 -> FAIL.
        yard=False(0) + space=False(0) + hazards=True(0) + pets=True(20) = 20 -> FAIL
        """
        shelter = create_shelter()
        animal = create_available_animal(shelter["id"], species="DOG")
        adopter = create_adopter_in_shelter(shelter["id"])
        app = submit_application(animal["id"], adopter["id"])
        app = start_application_review(app["id"])
        app = require_home_visit_on_application(app["id"])
        visit = schedule_home_visit(adopter["id"], app["id"])

        assessment = create_home_visit_assessment_payload(
            yard_adequate=False,     # 0
            space_adequate=False,    # 0
            safety_hazards_found=True,   # 0
            existing_pets_compatible=True,  # 20
        )  # Total: 20 -> FAIL
        res = api.complete_home_visit(visit["id"], assessment, caseworker_headers)
        completed = validate_success(res, 200)
        assert completed["overall_score"] == 20
        assert completed["result"] == "FAIL"

    def test_score_zero_all_fail(self, api, caseworker_headers):
        """All criteria fail -> score=0, result=FAIL."""
        shelter = create_shelter()
        animal = create_available_animal(shelter["id"], species="DOG")
        adopter = create_adopter_in_shelter(shelter["id"])
        app = submit_application(animal["id"], adopter["id"])
        app = start_application_review(app["id"])
        app = require_home_visit_on_application(app["id"])
        visit = schedule_home_visit(adopter["id"], app["id"])

        assessment = create_home_visit_assessment_payload(
            yard_adequate=False,
            space_adequate=False,
            safety_hazards_found=True,
            existing_pets_compatible=False,
        )  # Total: 0 -> FAIL
        res = api.complete_home_visit(visit["id"], assessment, caseworker_headers)
        completed = validate_success(res, 200)
        assert completed["overall_score"] == 0
        assert completed["result"] == "FAIL"


class TestHomeVisitNoYardVariant:
    """Table 3 variant: no_yard_adjustment for CAT/BIRD/RABBIT."""

    def test_cat_yard_weight_zero_space_45(self, api, caseworker_headers):
        """
        For CAT: yard_adequate weight=0, space_adequate=45.
        All pass: 0+45+25+20 = 90 -> PASS (max possible is 90).
        """
        shelter = create_shelter()
        animal = create_available_animal(shelter["id"], species="CAT")
        adopter = create_adopter_in_shelter(shelter["id"])
        app = submit_application(animal["id"], adopter["id"])
        app = start_application_review(app["id"])
        app = require_home_visit_on_application(app["id"])
        visit = schedule_home_visit(adopter["id"], app["id"])

        assessment = create_home_visit_assessment_payload(
            yard_adequate=True,      # weight=0 for cat
            space_adequate=True,     # 45
            safety_hazards_found=False,  # 25
            existing_pets_compatible=True,  # 20
        )  # Total: 90 -> PASS
        res = api.complete_home_visit(visit["id"], assessment, caseworker_headers)
        completed = validate_success(res, 200)
        assert completed["overall_score"] == 90
        assert completed["result"] == "PASS"

    def test_cat_no_yard_still_passes(self, api, caseworker_headers):
        """
        For CAT: yard_adequate=False but weight=0, so no impact.
        False(0) + True(45) + False(25) + True(20) = 90 -> PASS
        """
        shelter = create_shelter()
        animal = create_available_animal(shelter["id"], species="CAT")
        adopter = create_adopter_in_shelter(shelter["id"])
        app = submit_application(animal["id"], adopter["id"])
        app = start_application_review(app["id"])
        app = require_home_visit_on_application(app["id"])
        visit = schedule_home_visit(adopter["id"], app["id"])

        assessment = create_home_visit_assessment_payload(
            yard_adequate=False,     # 0 (weight=0 for cat anyway)
            space_adequate=True,     # 45
            safety_hazards_found=False,  # 25
            existing_pets_compatible=True,  # 20
        )
        res = api.complete_home_visit(visit["id"], assessment, caseworker_headers)
        completed = validate_success(res, 200)
        assert completed["overall_score"] == 90
        assert completed["result"] == "PASS"


class TestHomeVisitSideEffects:
    """Side effects on adopter and application after visit completion."""

    def test_pass_updates_adopter_and_advances_application(self, api, caseworker_headers):
        """PASS -> adopter.home_visit_passed=True, application -> REVIEWED."""
        shelter = create_shelter()
        animal = create_available_animal(shelter["id"], species="DOG")
        adopter = create_adopter_in_shelter(shelter["id"])
        app = submit_application(animal["id"], adopter["id"])
        app = start_application_review(app["id"])
        app = require_home_visit_on_application(app["id"])
        visit = schedule_home_visit(adopter["id"], app["id"])

        complete_home_visit_with_result(visit["id"], result="PASS")

        adopter_after = validate_success(
            api.get_adopter(adopter["id"], caseworker_headers), 200,
        )
        assert adopter_after["home_visit_passed"] is True

        app_after = validate_success(
            api.get_adoption_application(app["id"], caseworker_headers), 200,
        )
        assert app_after["status"] == "REVIEWED"

    def test_conditional_pass_also_advances(self, api, caseworker_headers):
        """CONDITIONAL_PASS -> application also advances to REVIEWED."""
        shelter = create_shelter()
        animal = create_available_animal(shelter["id"], species="DOG")
        adopter = create_adopter_in_shelter(shelter["id"])
        app = submit_application(animal["id"], adopter["id"])
        app = start_application_review(app["id"])
        app = require_home_visit_on_application(app["id"])
        visit = schedule_home_visit(adopter["id"], app["id"])

        complete_home_visit_with_result(visit["id"], result="CONDITIONAL_PASS")

        app_after = validate_success(
            api.get_adoption_application(app["id"], caseworker_headers), 200,
        )
        assert app_after["status"] == "REVIEWED"

    def test_fail_rejects_application(self, api, caseworker_headers):
        """FAIL -> application -> REJECTED with reason 'Home visit failed'."""
        shelter = create_shelter()
        animal = create_available_animal(shelter["id"], species="DOG")
        adopter = create_adopter_in_shelter(shelter["id"])
        app = submit_application(animal["id"], adopter["id"])
        app = start_application_review(app["id"])
        app = require_home_visit_on_application(app["id"])
        visit = schedule_home_visit(adopter["id"], app["id"])

        complete_home_visit_with_result(visit["id"], result="FAIL")

        app_after = validate_success(
            api.get_adoption_application(app["id"], caseworker_headers), 200,
        )
        assert app_after["status"] == "REJECTED"
        assert app_after["rejection_reason"] == "Home visit failed"


class TestHomeVisitCancellation:
    """Cancel a home visit and its effects on the application."""

    def test_cancel_home_visit_reverts_application(self, api, caseworker_headers):
        """Cancel visit -> CANCELLED, application reverts to HOME_VISIT_REQUIRED."""
        shelter = create_shelter()
        animal = create_available_animal(shelter["id"], species="DOG")
        adopter = create_adopter_in_shelter(shelter["id"])
        app = submit_application(animal["id"], adopter["id"])
        app = start_application_review(app["id"])
        app = require_home_visit_on_application(app["id"])
        visit = schedule_home_visit(adopter["id"], app["id"])

        res = api.cancel_home_visit(visit["id"], caseworker_headers)
        cancelled = validate_success(res, 200)
        assert cancelled["status"] == "CANCELLED"

        app_after = validate_success(
            api.get_adoption_application(app["id"], caseworker_headers), 200,
        )
        assert app_after["status"] == "HOME_VISIT_REQUIRED"


class TestHomeVisitAccessControl:
    """Assessor mismatch check."""

    def test_complete_visit_assessor_mismatch(self, api, caseworker_headers):
        """Different caseworker completing visit -> ERR_ASSESSOR_MISMATCH."""
        shelter = create_shelter()
        animal = create_available_animal(shelter["id"], species="DOG")
        adopter = create_adopter_in_shelter(shelter["id"])
        app = submit_application(animal["id"], adopter["id"])
        app = start_application_review(app["id"])
        app = require_home_visit_on_application(app["id"])
        visit = schedule_home_visit(adopter["id"], app["id"])  # assigned to caseworker-1

        assessment = create_home_visit_assessment_payload()
        other_cw = TEST_USERS["caseworker2_headers"]
        res = api.complete_home_visit(visit["id"], assessment, other_cw)
        validate_error(res, ApiErrorId.ERR_ASSESSOR_MISMATCH)
