"""Adoption pipeline: home checks, approval gates, precedence, uniqueness."""
from test_helpers import (
    api_client, TEST_USERS, ApiErrorId, NON_EXISTENT_UUID,
    validate_success, validate_error, get_success_data,
    adoption_application_payload, home_check_payload,
    make_adopter_headers, make_veterinarian_headers,
    intake_horse, get_horse, complete_medical_pass, clear_active_protocol,
    release_horse, set_clock, register_vet, register_adopter,
    submit_application, start_review, pass_home_check, get_application,
    setup_released_horse, setup_application_home_check_passed,
)

INTAKE = TEST_USERS["intake_headers"]
OFFICER_1 = TEST_USERS["officer_1_headers"]
OFFICER_2 = TEST_USERS["officer_2_headers"]


def _bundle_under_review(horse_overrides=None, pickup="2026-08-25T00:00:00Z",
                         adopter_overrides=None):
    bundle = setup_released_horse("ADOPTABLE", horse_overrides)
    adopter = register_adopter(**(adopter_overrides or {}))
    app = submit_application(adopter["id"], bundle["horse"]["id"], pickup)
    start_review(app["id"])
    return {"horse": bundle["horse"], "vet_id": bundle["vet_id"],
            "adopter": adopter, "application": get_application(app["id"])}


class TestHomeCheckRetryLoop:
    def test_conditional_home_check_loops_back_to_under_review(self):
        """PRD §3.3: "A `FAILED` or `CONDITIONAL` outcome loops the application
        back to `UNDER_REVIEW` for another attempt — with one exception: a
        `FAILED` outcome when `home_check_attempts` has reached 2 skips the loop
        entirely and auto-rejects the application, moving it to `REJECTED` with
        `decision_reason` recorded as `HOME_CHECK_LIMIT`."
        PRD §3.3: "Each creation increments `home_check_attempts` by one and moves
        the application `UNDER_REVIEW` → `HOME_CHECK_SCHEDULED`; the check itself
        begins `SCHEDULED`."

        Design: Difficulty/non_linear_state_machine/application_home_check_retry_loop
        """
        bundle = _bundle_under_review()
        app_id = bundle["application"]["id"]
        hc1 = pass_home_check(app_id, outcome="CONDITIONAL",
                              findings="fence repair needed",
                              scheduled_date="2026-08-16T10:00:00Z")
        assert hc1["status"] == "COMPLETED"
        assert hc1["outcome"] == "CONDITIONAL"
        app = get_application(app_id)
        assert app["status"] == "UNDER_REVIEW"
        assert app["home_check_attempts"] == 1

    def test_second_home_check_passed_closes_loop(self):
        """PRD §3.3: "A `PASSED` outcome advances the application
        `HOME_CHECK_SCHEDULED` → `HOME_CHECK_PASSED`."
        PRD §3.3: "Each creation increments `home_check_attempts` by one and moves
        the application `UNDER_REVIEW` → `HOME_CHECK_SCHEDULED`; the check itself
        begins `SCHEDULED`."

        Design: Difficulty/non_linear_state_machine/application_home_check_retry_loop
        """
        bundle = _bundle_under_review()
        app_id = bundle["application"]["id"]
        pass_home_check(app_id, outcome="CONDITIONAL",
                        scheduled_date="2026-08-16T10:00:00Z")
        hc2 = pass_home_check(app_id, outcome="PASSED",
                              scheduled_date="2026-08-18T10:00:00Z")
        assert hc2["outcome"] == "PASSED"
        app = get_application(app_id)
        assert app["status"] == "HOME_CHECK_PASSED"
        assert app["home_check_attempts"] == 2


class TestApproveGatedByHorseAdoptable:
    def test_approve_rejected_when_horse_quarantined(self):
        """PRD §3.4: "the horse must be `ADOPTABLE` (`ERR_HORSE_NOT_ADOPTABLE`)"

        Design: Difficulty/cross_entity_state_dependency/approve_gated_by_horse_adoptable
        """
        bundle = setup_application_home_check_passed(pickup="2026-09-01T00:00:00Z")
        get_success_data(api_client.requarantine_horse(
            bundle["horse"]["id"], {"min_days": 7, "reason": "EXPOSURE"}, INTAKE))
        resp = api_client.approve_application(
            bundle["application"]["id"], OFFICER_2)
        validate_error(resp, ApiErrorId.ERR_HORSE_NOT_ADOPTABLE, 409)

    def test_approve_succeeds_after_horse_returns_adoptable(self):
        """PRD §3.4: "Approval stamps `approved_at` at the logical now, snapshots
        `quoted_fee_cents` from the QUOTED variant of the fee calculation
        described below, and cascades onto the horse: `ADOPTABLE` →
        `ADOPTION_PENDING`, the horse's `active_application_id` set to the
        approved application, and the horse's `version` incremented."

        Design: Difficulty/cross_entity_state_dependency/approve_gated_by_horse_adoptable
        """
        bundle = setup_application_home_check_passed(pickup="2026-09-01T00:00:00Z")
        horse_id = bundle["horse"]["id"]
        get_success_data(api_client.requarantine_horse(
            horse_id, {"min_days": 7, "reason": "EXPOSURE"}, INTAKE))
        # Ride out the second quarantine episode: eval 08-20, clear 08-22.
        complete_medical_pass(horse_id, at="2026-08-20T12:00:00Z")
        clear_active_protocol(horse_id, bundle["vet_id"],
                              at="2026-08-22T00:00:00Z")
        release_horse(horse_id, "ADOPTABLE")

        approved = validate_success(api_client.approve_application(
            bundle["application"]["id"], OFFICER_2))
        assert approved["status"] == "APPROVED"
        horse = get_horse(horse_id)
        assert horse["status"] == "ADOPTION_PENDING"
        assert horse["active_application_id"] == bundle["application"]["id"]


class TestApprovePriorityPair:
    def _setup_two_passed_applications(self):
        bundle = setup_released_horse("ADOPTABLE",
                                      {"name": "H", "age_years": 8})
        ad1 = register_adopter(full_name="Ad One", contact_email="a1@x.com")
        app1 = submit_application(ad1["id"], bundle["horse"]["id"],
                                  "2026-08-20T00:00:00Z")
        start_review(app1["id"])
        pass_home_check(app1["id"], scheduled_date="2026-08-15T10:00:00Z")
        ad2 = register_adopter(full_name="Ad Two", contact_email="a2@x.com",
                               experience_level="NOVICE", has_stall_facility=False)
        app2 = submit_application(ad2["id"], bundle["horse"]["id"],
                                  "2026-08-21T00:00:00Z")
        start_review(app2["id"])
        pass_home_check(app2["id"], scheduled_date="2026-08-15T11:00:00Z")
        return bundle, ad1, app1, ad2, app2

    def test_state_error_outranks_adopter_blocked(self):
        """PRD §2.7: "Evaluation stops at the first failing tier, so the error a
        caller receives is always the highest-priority failure their request would
        have produced."
        PRD §2.7: "9. **Horse posture gates.** Adoption application creation
        requires the horse `ADOPTABLE` (`ERR_HORSE_NOT_ADOPTABLE`)"
        PRD §2.7: "12. **Adopter standing.** A `BLOCKED` adopter may not submit an
        application and may not be approved; failure is `ERR_ADOPTER_BLOCKED`
        (HTTP 422)."

        Design: Difficulty/priority_pair_validation_conflict/approve_state_vs_safety_priority
        """
        bundle, _ad1, app1, ad2, app2 = self._setup_two_passed_applications()
        get_success_data(api_client.block_adopter(
            ad2["id"], {"reason": "prior neglect conviction"}, OFFICER_1))
        get_success_data(api_client.approve_application(app1["id"], OFFICER_2))
        assert get_horse(bundle["horse"]["id"])["status"] == "ADOPTION_PENDING"

        resp = api_client.approve_application(app2["id"], OFFICER_2)
        validate_error(resp, ApiErrorId.ERR_HORSE_NOT_ADOPTABLE, 409)

    def test_losing_application_unchanged_after_priority_rejection(self):
        """PRD §2.7: "Evaluation stops at the first failing tier, so the error a
        caller receives is always the highest-priority failure their request would
        have produced."
        PRD §3.4: "the horse must be `ADOPTABLE` (`ERR_HORSE_NOT_ADOPTABLE`)"

        Design: Difficulty/priority_pair_validation_conflict/approve_state_vs_safety_priority
        """
        bundle, _ad1, app1, ad2, app2 = self._setup_two_passed_applications()
        get_success_data(api_client.block_adopter(
            ad2["id"], {"reason": "prior neglect conviction"}, OFFICER_1))
        get_success_data(api_client.approve_application(app1["id"], OFFICER_2))
        api_client.approve_application(app2["id"], OFFICER_2)

        app2_after = get_application(app2["id"])
        assert app2_after["status"] == "HOME_CHECK_PASSED", (
            "failed approve must not move the application")
        app1_after = get_application(app1["id"])
        assert app1_after["status"] == "APPROVED"


class TestHomeCheckCapsAndAutoReject:
    def test_home_check_cap_third_attempt_rejected(self):
        """PRD §3.3: "the attempt cap is hard: creating a home check while
        `home_check_attempts` has already reached 2 fails with
        `ERR_HOME_CHECK_LIMIT_EXCEEDED`."

        Design: Corner/state_machines/home_check_cap_third_attempt_rejected
        """
        bundle = _bundle_under_review()
        app_id = bundle["application"]["id"]
        pass_home_check(app_id, outcome="FAILED",
                        scheduled_date="2026-08-16T10:00:00Z")
        pass_home_check(app_id, outcome="CONDITIONAL",
                        scheduled_date="2026-08-18T10:00:00Z")
        resp = api_client.create_home_check(
            home_check_payload(app_id, scheduled_date="2026-08-20T10:00:00Z"),
            OFFICER_1)
        validate_error(resp, ApiErrorId.ERR_HOME_CHECK_LIMIT_EXCEEDED, 422)
        app = get_application(app_id)
        assert app["status"] == "UNDER_REVIEW"
        assert app["home_check_attempts"] == 2

    def test_home_check_second_failed_auto_rejects(self):
        """PRD §3.3: "a `FAILED` outcome when `home_check_attempts` has reached 2
        skips the loop entirely and auto-rejects the application, moving it to
        `REJECTED` with `decision_reason` recorded as `HOME_CHECK_LIMIT`."

        Design: Corner/state_machines/home_check_second_failed_auto_rejects
        """
        bundle = _bundle_under_review(
            adopter_overrides={"experience_level": "NOVICE",
                               "has_stall_facility": False})
        app_id = bundle["application"]["id"]
        pass_home_check(app_id, outcome="FAILED",
                        scheduled_date="2026-08-16T10:00:00Z")
        pass_home_check(app_id, outcome="FAILED", findings="no water source",
                        scheduled_date="2026-08-18T10:00:00Z")
        app = get_application(app_id)
        assert app["status"] == "REJECTED"
        assert app["decision_reason"] == "HOME_CHECK_LIMIT"
        assert app["home_check_attempts"] == 2


class TestApproveGuards:
    def test_duty_segregation_adoption_approve(self):
        """PRD §3.4: "segregation of duties forbids the approving officer's
        `X-User-ID` from equaling the `completed_by_user_id` of the passed home
        check (`ERR_DUTY_SEGREGATION`)"

        Design: Corner/validations/duty_segregation_adoption_approve
        """
        bundle = setup_application_home_check_passed()
        resp = api_client.approve_application(
            bundle["application"]["id"], OFFICER_1)
        validate_error(resp, ApiErrorId.ERR_DUTY_SEGREGATION, 422)
        approved = validate_success(api_client.approve_application(
            bundle["application"]["id"], OFFICER_2))
        assert approved["status"] == "APPROVED"

    def test_home_check_expired_after_180_days(self):
        """PRD §3.4: "the latest completed home check's `completed_at` must lie
        within 180 days of the logical now (`ERR_HOME_CHECK_EXPIRED`)"

        Design: Corner/validations/home_check_expired_after_180_days
        """
        bundle = setup_application_home_check_passed(pickup="2026-08-25T00:00:00Z")
        set_clock("2027-02-12T00:00:00Z")  # 181 days after the 2026-08-15 check
        resp = api_client.approve_application(
            bundle["application"]["id"], OFFICER_2)
        validate_error(resp, ApiErrorId.ERR_HOME_CHECK_EXPIRED, 422)

    def test_precedence_blocked_later_submitted(self):
        """PRD §3.4: "no other application for the same horse may sit in
        `UNDER_REVIEW`, `HOME_CHECK_SCHEDULED`, or `HOME_CHECK_PASSED` with a
        `submitted_at` strictly earlier than this application's — equal timestamps
        do not block — (`ERR_APPLICATION_PRECEDENCE_BLOCKED`)"

        Design: Corner/validations/precedence_blocked_later_submitted
        """
        bundle = setup_released_horse("ADOPTABLE",
                                      {"name": "H", "age_years": 8})
        horse_id = bundle["horse"]["id"]
        ad1 = register_adopter(full_name="Ad One", contact_email="a1@x.com")
        app1 = submit_application(ad1["id"], horse_id, "2026-08-25T00:00:00Z")
        start_review(app1["id"])

        set_clock("2026-08-15T01:00:00Z")  # app2 submitted strictly later
        ad2 = register_adopter(full_name="Ad Two", contact_email="a2@x.com",
                               experience_level="NOVICE", has_stall_facility=False)
        app2 = submit_application(ad2["id"], horse_id, "2026-08-26T00:00:00Z")
        start_review(app2["id"])
        pass_home_check(app2["id"], scheduled_date="2026-08-15T11:00:00Z")

        resp = api_client.approve_application(app2["id"], OFFICER_2)
        validate_error(resp, ApiErrorId.ERR_APPLICATION_PRECEDENCE_BLOCKED, 422)
        assert get_application(app2["id"])["status"] == "HOME_CHECK_PASSED"


class TestSubmissionGates:
    def test_duplicate_application_rejected(self):
        """PRD §3.3: "Each adopter–horse pair admits at most one non-terminal
        application: while an application from the same adopter for the same horse
        sits in `SUBMITTED`, `UNDER_REVIEW`, `HOME_CHECK_SCHEDULED`,
        `HOME_CHECK_PASSED`, or `APPROVED`, a fresh submission is refused with
        `ERR_DUPLICATE_APPLICATION`."

        Design: Corner/validations/duplicate_application_rejected
        """
        vet_id = register_vet()
        h1 = intake_horse(name="H1", age_years=8)
        h2 = intake_horse(name="H2", sex="GELDING", estimated_weight_lbs=950,
                          age_years=7)
        complete_medical_pass(h1["id"], at="2026-08-14T12:00:00Z")
        complete_medical_pass(h2["id"], at="2026-08-14T12:30:00Z")
        clear_active_protocol(h1["id"], vet_id)
        clear_active_protocol(h2["id"], vet_id)
        release_horse(h1["id"], "ADOPTABLE")
        release_horse(h2["id"], "ADOPTABLE")
        adopter = register_adopter()
        submit_application(adopter["id"], h1["id"])

        resp = api_client.create_adoption_application(
            adoption_application_payload(
                adopter["id"], h1["id"],
                proposed_pickup_date="2026-08-26T00:00:00Z"),
            make_adopter_headers(adopter["id"]))
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_APPLICATION, 409)

        other = validate_success(api_client.create_adoption_application(
            adoption_application_payload(
                adopter["id"], h2["id"],
                proposed_pickup_date="2026-08-26T00:00:00Z"),
            make_adopter_headers(adopter["id"])), 201)
        assert other["status"] == "SUBMITTED"

    def test_blocked_adopter_create_rejected(self):
        """PRD §3.3: "While `BLOCKED`, an adopter can neither submit an
        application nor be approved on one; both attempts fail with
        `ERR_ADOPTER_BLOCKED`."

        Design: Corner/validations/blocked_adopter_create_rejected
        """
        bundle = setup_released_horse("ADOPTABLE", {"age_years": 8})
        adopter = register_adopter(experience_level="NOVICE",
                                   has_stall_facility=False)
        get_success_data(api_client.block_adopter(
            adopter["id"], {"reason": "failed reference check"}, OFFICER_1))
        resp = api_client.create_adoption_application(
            adoption_application_payload(
                adopter["id"], bundle["horse"]["id"],
                proposed_pickup_date="2026-08-25T00:00:00Z"),
            make_adopter_headers(adopter["id"]))
        validate_error(resp, ApiErrorId.ERR_ADOPTER_BLOCKED, 422)

    def test_body_fk_horse_not_found(self):
        """PRD §2.7: "Foreign keys supplied in the request body are resolved: an
        unknown `horse_id` fails with `ERR_HORSE_NOT_FOUND`, `adopter_id` with
        `ERR_ADOPTER_NOT_FOUND`, `practitioner_id` with
        `ERR_PRACTITIONER_NOT_FOUND`, `stall_id` with `ERR_STALL_NOT_FOUND`,
        `sponsor_id` with `ERR_SPONSOR_NOT_FOUND`, `application_id` with
        `ERR_APPLICATION_NOT_FOUND`, and `rehab_plan_id` with
        `ERR_REHAB_PLAN_NOT_FOUND` (all HTTP 404)."

        Design: Corner/errors/body_fk_horse_not_found
        """
        adopter = register_adopter()
        resp = api_client.create_adoption_application(
            adoption_application_payload(
                adopter["id"], NON_EXISTENT_UUID,
                proposed_pickup_date="2026-08-25T00:00:00Z"),
            make_adopter_headers(adopter["id"]))
        validate_error(resp, ApiErrorId.ERR_HORSE_NOT_FOUND, 404)
