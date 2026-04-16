"""Adopter registration + home-visit lifecycle — PRD §3.3."""
import pytest
from test_helpers import (
    api_client, TEST_USERS, ApiErrorId, NON_EXISTENT_UUID,
    validate_success, validate_error,
    assert_adopter, assert_home_visit,
    create_adopter_payload, create_home_visit_payload, submit_home_visit_payload,
    create_adopter, schedule_home_visit, submit_home_visit,
    create_adopter_with_passed_home_visit,
    make_inspector_headers, make_reviewer_headers, make_adopter_headers,
    future_iso, past_iso,
    HOME_VISIT_PASS_THRESHOLD,
)


class TestAdopterRegistration:
    def test_create_adopter_defaults(self):
        """PRD §3.3: "created with home_visit_status set to PENDING and disqualified
        initialised to false"."""
        adopter = create_adopter()
        assert adopter["home_visit_status"] == "PENDING"
        assert adopter["disqualified"] is False
        assert_adopter(adopter)

    def test_shelter_admin_can_register(self):
        """PRD §3.3: "self-registers — or is registered by a ShelterAdmin"."""
        resp = api_client.create_adopter(create_adopter_payload(),
                                         TEST_USERS["shelter_admin_headers"])
        validate_success(resp, expected_status=201)

    def test_create_adopter_missing_full_name_rejected(self):
        """PRD §2.7: missing required field → ERR_INVALID_REQUEST."""
        payload = create_adopter_payload()
        payload.pop("full_name")
        resp = api_client.create_adopter(payload, TEST_USERS["adopter_headers"])
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)

    def test_get_adopter_not_found(self):
        """PRD §2.5: ERR_ADOPTER_NOT_FOUND for missing adopter id."""
        resp = api_client.get_adopter(NON_EXISTENT_UUID, TEST_USERS["shelter_admin_headers"])
        validate_error(resp, ApiErrorId.ERR_ADOPTER_NOT_FOUND.value)


class TestHomeVisitScheduling:
    def test_reviewer_schedules_visit(self):
        """PRD §3.3: "An AdoptionReviewer schedules a visit through
        POST /adopters/{id}/home-visits"."""
        adopter = create_adopter()
        resp = api_client.create_home_visit(
            adopter["id"], create_home_visit_payload(),
            TEST_USERS["adoption_reviewer_headers"])
        data = validate_success(resp, expected_status=201)
        assert data["status"] == "SCHEDULED"
        assert_home_visit(data)

    def test_non_reviewer_cannot_schedule(self):
        """PRD §3.3: scheduling is the AdoptionReviewer's exclusive operation."""
        adopter = create_adopter()
        resp = api_client.create_home_visit(
            adopter["id"], create_home_visit_payload(),
            TEST_USERS["adopter_headers"])
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS.value)

    def test_schedule_adopter_not_found(self):
        """PRD §2.5: ERR_ADOPTER_NOT_FOUND on missing adopter path."""
        resp = api_client.create_home_visit(
            NON_EXISTENT_UUID, create_home_visit_payload(),
            TEST_USERS["adoption_reviewer_headers"])
        validate_error(resp, ApiErrorId.ERR_ADOPTER_NOT_FOUND.value)


class TestHomeVisitSubmit:
    def test_submit_passes_at_threshold(self):
        """PRD §3.3: "transitions automatically to PASSED when the score is at least 70"
        — boundary 70 is PASSED."""
        adopter = create_adopter()
        hv = schedule_home_visit(adopter["id"], inspector_user_id="inspector-x")
        resp = api_client.submit_home_visit(
            adopter["id"], hv["id"],
            submit_home_visit_payload(safety_score=HOME_VISIT_PASS_THRESHOLD),
            make_inspector_headers("inspector-x"),
        )
        data = validate_success(resp)
        assert data["status"] == "PASSED"

    def test_submit_fails_below_threshold(self):
        """PRD §3.3: "or to FAILED otherwise" — score 69 fails."""
        adopter = create_adopter()
        hv = schedule_home_visit(adopter["id"], inspector_user_id="inspector-y")
        resp = api_client.submit_home_visit(
            adopter["id"], hv["id"],
            submit_home_visit_payload(safety_score=HOME_VISIT_PASS_THRESHOLD - 1),
            make_inspector_headers("inspector-y"),
        )
        data = validate_success(resp)
        assert data["status"] == "FAILED"

    def test_submit_score_out_of_range_rejected_high(self):
        """PRD §3.3: "outside the band yields ERR_INVALID_SCORE"."""
        adopter = create_adopter()
        hv = schedule_home_visit(adopter["id"], inspector_user_id="inspector-z")
        resp = api_client.submit_home_visit(
            adopter["id"], hv["id"],
            submit_home_visit_payload(safety_score=101),
            make_inspector_headers("inspector-z"),
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_SCORE.value)

    def test_submit_score_out_of_range_rejected_low(self):
        """PRD §3.3: "safety_score in the [0..100] band"."""
        adopter = create_adopter()
        hv = schedule_home_visit(adopter["id"], inspector_user_id="inspector-z2")
        resp = api_client.submit_home_visit(
            adopter["id"], hv["id"],
            submit_home_visit_payload(safety_score=-1),
            make_inspector_headers("inspector-z2"),
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_SCORE.value)

    def test_submit_by_non_assigned_inspector_rejected(self):
        """PRD §3.3: "The platform rejects submission from anyone other than the
        assigned inspector with ERR_INSUFFICIENT_PERMISSIONS"."""
        adopter = create_adopter()
        hv = schedule_home_visit(adopter["id"], inspector_user_id="inspector-correct")
        resp = api_client.submit_home_visit(
            adopter["id"], hv["id"],
            submit_home_visit_payload(safety_score=85),
            make_inspector_headers("inspector-wrong"),
        )
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS.value)

    def test_pass_updates_adopter_home_visit_status(self):
        """PRD §3.3: "A pass sets Adopter.home_visit_status to PASSED and writes
        home_visit_expires_at"."""
        adopter = create_adopter_with_passed_home_visit(
            safety_score=90, inspector_user_id="insp-pass")
        assert adopter["home_visit_status"] == "PASSED"
        assert adopter.get("home_visit_expires_at") is not None

    def test_fail_updates_adopter_home_visit_status(self):
        """PRD §3.3 / state machine: FAILED submit sets Adopter.home_visit_status=FAILED."""
        adopter = create_adopter()
        hv = schedule_home_visit(adopter["id"], inspector_user_id="insp-fail")
        submit_home_visit(adopter["id"], hv["id"], "insp-fail", safety_score=10)
        resp = api_client.get_adopter(adopter["id"], TEST_USERS["shelter_admin_headers"])
        data = validate_success(resp)
        assert data["home_visit_status"] == "FAILED"

    def test_submit_already_submitted_rejected(self):
        """PRD Table 2 (HomeVisit): only SCHEDULED -> SUBMITTED is valid; else ERR_INVALID_STATE."""
        adopter = create_adopter()
        hv = schedule_home_visit(adopter["id"], inspector_user_id="insp-twice")
        submit_home_visit(adopter["id"], hv["id"], "insp-twice", safety_score=85)
        resp = api_client.submit_home_visit(
            adopter["id"], hv["id"],
            submit_home_visit_payload(safety_score=85),
            make_inspector_headers("insp-twice"),
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


class TestHomeVisitCancel:
    def test_adopter_can_cancel(self):
        """PRD §3.3: "may be cancelled by either the adopter or the inspector"."""
        adopter = create_adopter()
        hv = schedule_home_visit(adopter["id"], inspector_user_id="insp-cancel")
        resp = api_client.cancel_home_visit(
            adopter["id"], hv["id"],
            make_adopter_headers(adopter["id"]),
        )
        data = validate_success(resp)
        assert data["status"] == "CANCELLED"

    def test_inspector_can_cancel(self):
        """PRD §3.3: "may be cancelled by either the adopter or the inspector"."""
        adopter = create_adopter()
        hv = schedule_home_visit(adopter["id"], inspector_user_id="insp-cancel2")
        resp = api_client.cancel_home_visit(
            adopter["id"], hv["id"],
            make_inspector_headers("insp-cancel2"),
        )
        data = validate_success(resp)
        assert data["status"] == "CANCELLED"

    def test_cancel_unknown_hv_not_found(self):
        """PRD §2.5: ERR_HOME_VISIT_NOT_FOUND for missing hv id."""
        adopter = create_adopter()
        resp = api_client.cancel_home_visit(adopter["id"], NON_EXISTENT_UUID,
                                            TEST_USERS["adopter_headers"])
        validate_error(resp, ApiErrorId.ERR_HOME_VISIT_NOT_FOUND.value)
