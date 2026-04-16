"""Tests for HomeVisit subworkflow.

Covers: PRD Section 3.4 (The Home Visit Subworkflow),
Table 2 (HomeVisit state machine), Table 3 (home_visit_scoring),
Table 4 priorities 17, 21.
"""
import pytest
from test_helpers import (
    api_client, validate_success, validate_error, get_success_data,
    NON_EXISTENT_UUID, ApiErrorId, TEST_USERS,
    assert_home_visit,
    create_home_visit_payload, complete_home_visit_payload,
    future_date, past_date, iso_now_offset,
    create_application_home_visit_required, create_home_visit_scheduled,
    user_id_from_headers,
)

_manager = TEST_USERS["manager_headers"]
_case_worker = TEST_USERS["case_worker_headers"]
_case_worker2 = TEST_USERS["case_worker_headers_2"]


class TestHomeVisitCreation:
    """PRD 3.4: Schedule a home visit."""

    def test_create_home_visit_success(self):
        shelter, animal, adopter, app, reviewer = create_application_home_visit_required()
        resp = api_client.create_home_visit(
            create_home_visit_payload(app["id"]), reviewer
        )
        data = validate_success(resp, 201)
        assert_home_visit(data)
        assert data["application_id"] == app["id"]
        assert data["case_worker_id"] == user_id_from_headers(reviewer)
        assert data["status"] == "SCHEDULED"
        # Application now HOME_VISIT_SCHEDULED
        refreshed = get_success_data(api_client.get_adoption_application(app["id"], _manager))
        assert refreshed["status"] == "HOME_VISIT_SCHEDULED"
        assert refreshed["home_visit_id"] == data["id"]

    def test_create_home_visit_past_date_rejected(self):
        """scheduled_date must be strictly > current_time."""
        shelter, animal, adopter, app, reviewer = create_application_home_visit_required()
        payload = create_home_visit_payload(app["id"])
        payload["scheduled_date"] = past_date(days=1)
        resp = api_client.create_home_visit(payload, reviewer)
        validate_error(resp, ApiErrorId.ERR_INVALID_DATES)

    def test_create_home_visit_application_not_found(self):
        resp = api_client.create_home_visit(
            create_home_visit_payload(NON_EXISTENT_UUID), _case_worker
        )
        validate_error(resp, ApiErrorId.ERR_APPLICATION_NOT_FOUND)


class TestHomeVisitCompleteScoring:
    """PRD 3.4 + Table 3 (home_visit_scoring): complete triggers scoring."""

    def test_complete_all_true_yields_pass(self):
        """All booleans favorable -> score 100 -> PASS."""
        shelter, animal, adopter, app, hv, reviewer = create_home_visit_scheduled()
        resp = api_client.complete_home_visit(
            hv["id"],
            complete_home_visit_payload(
                yard_adequate=True, space_adequate=True,
                safety_hazards_found=False, existing_pets_compatible=True,
            ),
            reviewer,
        )
        data = validate_success(resp)
        # yard 25 + space 30 + no_hazard 25 + pets 20 = 100 -> PASS
        assert data["overall_score"] == 100
        assert data["result"] == "PASS"
        assert data["status"] == "COMPLETED"
        # Application should move to REVIEWED
        refreshed_app = get_success_data(
            api_client.get_adoption_application(app["id"], _manager)
        )
        assert refreshed_app["status"] == "REVIEWED"

    def test_complete_yields_conditional_pass(self):
        """Score in [50, 70) -> CONDITIONAL_PASS.

        yard=True(25) + space=False(0) + no_hazard=True(25) + pets=True(20) = 70 -> PASS
        yard=True(25) + space=False(0) + hazard=True(0) + pets=True(20) = 45 -> FAIL
        To get CONDITIONAL, use yard=True(25) + space=True(30) + hazard=True(0) + pets=False(0) = 55.
        """
        shelter, animal, adopter, app, hv, reviewer = create_home_visit_scheduled()
        resp = api_client.complete_home_visit(
            hv["id"],
            complete_home_visit_payload(
                yard_adequate=True, space_adequate=True,
                safety_hazards_found=True, existing_pets_compatible=False,
            ),
            reviewer,
        )
        data = validate_success(resp)
        # 25 + 30 + 0 + 0 = 55 -> CONDITIONAL_PASS
        assert data["overall_score"] == 55
        assert data["result"] == "CONDITIONAL_PASS"
        # Application still moves to REVIEWED
        refreshed_app = get_success_data(
            api_client.get_adoption_application(app["id"], _manager)
        )
        assert refreshed_app["status"] == "REVIEWED"

    def test_complete_boundary_pass_exactly_70(self):
        """Score == 70 is PASS (>= 70).

        yard=True(25) + space=False(0) + no_hazard=True(25) + pets=True(20) = 70 -> PASS
        """
        shelter, animal, adopter, app, hv, reviewer = create_home_visit_scheduled()
        resp = api_client.complete_home_visit(
            hv["id"],
            complete_home_visit_payload(
                yard_adequate=True, space_adequate=False,
                safety_hazards_found=False, existing_pets_compatible=True,
            ),
            reviewer,
        )
        data = validate_success(resp)
        assert data["overall_score"] == 70
        assert data["result"] == "PASS"

    def test_complete_boundary_conditional_exactly_50(self):
        """Score == 50 is CONDITIONAL_PASS (50 <= s < 70).

        yard=True(25) + space=False(0) + no_hazard=True(25) + pets=False(0) = 50 -> CONDITIONAL
        """
        shelter, animal, adopter, app, hv, reviewer = create_home_visit_scheduled()
        resp = api_client.complete_home_visit(
            hv["id"],
            complete_home_visit_payload(
                yard_adequate=True, space_adequate=False,
                safety_hazards_found=False, existing_pets_compatible=False,
            ),
            reviewer,
        )
        data = validate_success(resp)
        assert data["overall_score"] == 50
        assert data["result"] == "CONDITIONAL_PASS"

    def test_complete_boundary_fail_below_50(self):
        """Score < 50 is FAIL.

        yard=False(0) + space=False(0) + no_hazard=True(25) + pets=True(20) = 45 -> FAIL
        """
        shelter, animal, adopter, app, hv, reviewer = create_home_visit_scheduled()
        resp = api_client.complete_home_visit(
            hv["id"],
            complete_home_visit_payload(
                yard_adequate=False, space_adequate=False,
                safety_hazards_found=False, existing_pets_compatible=True,
            ),
            reviewer,
        )
        data = validate_success(resp)
        assert data["overall_score"] == 45
        assert data["result"] == "FAIL"
        # Application transitions to REJECTED
        refreshed_app = get_success_data(
            api_client.get_adoption_application(app["id"], _manager)
        )
        assert refreshed_app["status"] == "REJECTED"
        assert refreshed_app["rejection_reason"] == "Home visit failed"

    def test_complete_updates_adopter_latest_home_visit(self):
        """PRD 3.4: adopter.latest_home_visit_id and latest_home_visit_result updated."""
        shelter, animal, adopter, app, hv, reviewer = create_home_visit_scheduled()
        get_success_data(api_client.complete_home_visit(
            hv["id"],
            complete_home_visit_payload(
                yard_adequate=True, space_adequate=True,
                safety_hazards_found=False, existing_pets_compatible=True,
            ),
            reviewer,
        ))
        refreshed_adopter = get_success_data(api_client.get_adopter(adopter["id"], _manager))
        assert refreshed_adopter["latest_home_visit_id"] == hv["id"]
        assert refreshed_adopter["latest_home_visit_result"] == "PASS"


class TestHomeVisitCompleteAssessorMismatch:
    """PRD 3.4: X-User-ID must equal case_worker_id on /complete."""

    def test_wrong_assessor_rejected(self):
        shelter, animal, adopter, app, hv, reviewer = create_home_visit_scheduled()
        # case_worker2 is a different user
        resp = api_client.complete_home_visit(
            hv["id"],
            complete_home_visit_payload(),
            _case_worker2,
        )
        validate_error(resp, ApiErrorId.ERR_ASSESSOR_MISMATCH)


class TestHomeVisitCompleteMissingBody:
    """PRD 3.4: complete body must contain four booleans + notes."""

    @pytest.mark.parametrize("missing_field", [
        "yard_adequate", "space_adequate", "safety_hazards_found",
        "existing_pets_compatible", "notes",
    ])
    def test_missing_required_assessment_field(self, missing_field):
        shelter, animal, adopter, app, hv, reviewer = create_home_visit_scheduled()
        payload = complete_home_visit_payload()
        del payload[missing_field]
        resp = api_client.complete_home_visit(hv["id"], payload, reviewer)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


class TestHomeVisitCompleteYardOptionalVariant:
    """PRD 3.4 + Table 3 variant: yard_optional for CAT/BIRD/RABBIT."""

    def test_cat_yard_weight_zero_space_55(self):
        """For CAT: yard=False(0) + space=True(55) + no_hazard=True(25) + pets=True(20) = 100."""
        # Build a CAT-based home-visit-required application manually by creating
        # a heavy CAT (weight_kg >= 25) which triggers requires_home_visit.
        from test_helpers import setup_basic_adoption_scenario
        from test_helpers import create_adoption_application_payload
        shelter, animal, adopter = setup_basic_adoption_scenario(
            species="CAT", weight_kg=25.0
        )
        app = get_success_data(api_client.create_adoption_application(
            create_adoption_application_payload(animal["id"], adopter["id"]),
            _case_worker,
        ))
        assert app["requires_home_visit"] is True
        app = get_success_data(api_client.start_review_application(app["id"], _case_worker))
        app = get_success_data(api_client.require_home_visit(app["id"], _case_worker))
        hv = get_success_data(api_client.create_home_visit(
            create_home_visit_payload(app["id"]), _case_worker
        ))
        resp = api_client.complete_home_visit(
            hv["id"],
            complete_home_visit_payload(
                yard_adequate=False, space_adequate=True,
                safety_hazards_found=False, existing_pets_compatible=True,
            ),
            _case_worker,
        )
        data = validate_success(resp)
        # yard optional: yard=0, space=55, no_hazard=25, pets=20 => 100
        assert data["overall_score"] == 100
        assert data["result"] == "PASS"


class TestHomeVisitCancel:
    """PRD 3.4: /cancel SCHEDULED -> CANCELLED."""

    def test_cancel_success(self):
        shelter, animal, adopter, app, hv, reviewer = create_home_visit_scheduled()
        resp = api_client.cancel_home_visit(hv["id"], reviewer)
        data = validate_success(resp)
        assert data["status"] == "CANCELLED"
        # Application reverts to HOME_VISIT_REQUIRED
        refreshed_app = get_success_data(
            api_client.get_adoption_application(app["id"], _manager)
        )
        assert refreshed_app["status"] == "HOME_VISIT_REQUIRED"
        assert refreshed_app["home_visit_id"] is None

    def test_cancel_wrong_state(self):
        """Cannot cancel a COMPLETED home visit."""
        shelter, animal, adopter, app, hv, reviewer = create_home_visit_scheduled()
        get_success_data(api_client.complete_home_visit(
            hv["id"], complete_home_visit_payload(), reviewer
        ))
        resp = api_client.cancel_home_visit(hv["id"], reviewer)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


class TestHomeVisitExpireDue:
    """PRD 3.4: /expire-due sweeps SCHEDULED visits with past scheduled_date."""

    def test_expire_due_requires_shelter_manager(self):
        """CaseWorker cannot call expire-due."""
        resp = api_client.expire_due_home_visits(_case_worker)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)

    def test_expire_due_success(self):
        """A scheduled visit whose date has passed transitions to EXPIRED.

        Note: since scheduled_date at creation must be strictly > current_time,
        we schedule it a short time ahead and then wait. To keep the test fast,
        we use a small sleep (several seconds is enough).
        """
        import time
        from test_helpers import create_home_visit_payload
        shelter, animal, adopter, app, reviewer = create_application_home_visit_required()
        # Need to create a home visit that is SCHEDULED but whose scheduled_date
        # becomes past. We'll schedule in 3 seconds, sleep 5, sweep.
        payload = create_home_visit_payload(app["id"])
        payload["scheduled_date"] = iso_now_offset(seconds=3)
        hv = get_success_data(api_client.create_home_visit(payload, reviewer))
        time.sleep(6)
        get_success_data(api_client.expire_due_home_visits(_manager))
        refreshed_hv = get_success_data(api_client.get_home_visit(hv["id"], _manager))
        assert refreshed_hv["status"] == "EXPIRED"
        # Application reverts to HOME_VISIT_REQUIRED
        refreshed_app = get_success_data(
            api_client.get_adoption_application(app["id"], _manager)
        )
        assert refreshed_app["status"] == "HOME_VISIT_REQUIRED"


class TestHomeVisitRetrieval:
    def test_get_home_visit(self):
        shelter, animal, adopter, app, hv, reviewer = create_home_visit_scheduled()
        resp = api_client.get_home_visit(hv["id"], _manager)
        data = validate_success(resp)
        assert_home_visit(data)

    def test_get_home_visit_not_found(self):
        resp = api_client.get_home_visit(NON_EXISTENT_UUID, _manager)
        validate_error(resp, ApiErrorId.ERR_HOME_VISIT_NOT_FOUND)
