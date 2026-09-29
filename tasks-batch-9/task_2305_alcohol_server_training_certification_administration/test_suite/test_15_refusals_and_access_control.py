"""Refusals that arrive after a decision has already been recorded, ceilings that each answer in
their own code, and the two ways a caller can be turned away: wrong role, or right role over
someone else's row.
"""
from test_helpers import (
    ADMIN,
    REGULATOR,
    ApiErrorId,
    assert_same_instant,
    certificates_for_server,
    certify_one_server,
    course_payload,
    create_certified_trainer,
    create_scheduled_session,
    enroll_server,
    enrollment_payload,
    get_approval,
    get_certificate_row,
    get_enrollment_row,
    get_location,
    get_session,
    lock_roster,
    make_alcohol_server_headers,
    make_trainer_headers,
    register_alcohol_server,
    reject_decision_payload,
    resubmit_payload,
    setup_employer_account,
    setup_training_base,
    submissions_for_certificate,
    transmit_payload,
    validate_error,
    validate_paginated,
    validate_success,
)

CLOCK = "2026-08-03T09:00:00Z"
COMPLETION_CLOCK = "2026-08-10T18:30:00Z"
REGISTRY_DUE_AT = "2026-08-25T18:30:00Z"
ONE_LOCATION = [{"location_name": "Alamo Taproom", "annual_premium_cents": 4821734}]
STRICT_TX = {
    "min_passing_score_pct": 70,
    "proctor_separation_required": False,
    "certificate_validity_months": 24,
    "registry_deadline_days": 15,
}


class TestRefusalsAfterASettledDecision:
    def test_an_approved_filing_refuses_a_second_decision_and_a_resubmission(self, api):
        """PRD §3.3: "A regulator decision names a `decision` and applies only while the record is
        `SUBMITTED`; deciding anything else is `ERR_APPROVAL_INVALID_STATE`."
        PRD §3.3: "Resubmitting from `STALE` additionally clears `pinned_course_version`, which
        stays cleared until the next `APPROVE` decision re-pins it. Resubmitting from any other
        status is `ERR_APPROVAL_INVALID_STATE`."
        PRD §3.3: "It records all three, stamps `decided_at` from the logical clock, and pins
        `pinned_course_version` to the course's current `version` — the anti-drift token that a
        later content revision will invalidate."

        Design: Corner/errors/a_decided_approval_refuses_both_a_second_decision_and_a_resubmission
        """
        base = setup_training_base(clock=CLOCK, with_session=False)
        approval_id = base["approval"]["id"]

        validate_error(api.decide_course_approval(
            approval_id, reject_decision_payload(), REGULATOR),
            ApiErrorId.ERR_APPROVAL_INVALID_STATE, 409)
        validate_error(api.resubmit_course_approval(
            approval_id, resubmit_payload(submission_note="second look"), ADMIN),
            ApiErrorId.ERR_APPROVAL_INVALID_STATE, 409)

        settled = get_approval(approval_id)
        assert settled["approval_status"] == "APPROVED"
        assert settled["approval_number"] == "TX-ABC-2026-001", (
            "neither refused call disturbed the pinned filing number, got "
            f"{settled['approval_number']}")
        assert_same_instant(settled["decided_at"], CLOCK, "decided_at")
        assert settled["review_round"] == 1, (
            f"a refused resubmission does not open a round, got {settled['review_round']}")

    def test_an_empty_ledger_a_settled_registry_and_a_live_assignment_each_answer_alone(
            self, api):
        """PRD §3.5: "A sponsored seat requires the sponsoring account to have
        `seat_credit_balance` of at least one, failing with `ERR_INSUFFICIENT_SEAT_CREDITS` (HTTP
        402), and requires the account's `account_status` not to be `SUSPENDED`, failing with
        `ERR_ACCOUNT_INVALID_STATE`."
        PRD §3.7: "It requires the certificate's `registry_state` to be `PENDING_SUBMISSION` or
        `RESUBMIT_REQUIRED` and its `validity_state` not to be `SUPERSEDED`; anything else is
        `ERR_CERTIFICATE_INVALID_STATE`. The transmission record names the `certificate_id`, lands
        in `submission_state` `TRANSMITTED` with `acknowledged_at` null and `rejection_code` at
        `NONE`, stamps `transmitted_at` from the logical clock, takes `attempt_number` as one plus
        the number of prior transmissions for this certificate — rejected ones included — and
        snapshots `due_at` from the certificate's `registry_due_at`. The certificate's
        `registry_state` becomes `SUBMITTED`."
        PRD §3.7: "When `transmitted_at` is at or before `due_at`, `late_days` is zero."
        PRD §3.8: "The same server may hold only one live assignment per location — a second while
        one is `ACTIVE` or `WORK_RESTRICTED` is `ERR_DUPLICATE_ASSIGNMENT`."

        Design: Corner/errors/zero_balance_sponsorship_repeat_registry_submission_and_duplicate_assignment_are_each_refused
        """
        base = setup_training_base(clock=CLOCK, jurisdiction_overrides=STRICT_TX)
        second_session = create_scheduled_session(
            base["course"]["id"], base["jurisdiction"]["id"], base["trainer"]["id"],
            scheduled_start_at="2026-08-20T14:00:00Z",
            scheduled_end_at="2026-08-20T18:00:00Z")
        employer = setup_employer_account(base["jurisdiction"]["id"], seat_quantity=0,
                                          location_specs=ONE_LOCATION)
        account_id = employer["account"]["id"]
        employer_headers = employer["employer_headers"]
        location_id = employer["locations"][0]["id"]

        bo = register_alcohol_server(base["jurisdiction"]["id"],
                                     full_name="Bo Nakamura", email="bo@example.com")
        walk = certify_one_server(base)
        ari = walk["server"]

        validate_error(api.create_enrollment(
            enrollment_payload(second_session["id"], bo["id"],
                               get_session(second_session["id"])["version"],
                               sponsoring_employer_account_id=account_id),
            employer_headers), ApiErrorId.ERR_INSUFFICIENT_SEAT_CREDITS, 402)
        assert validate_success(api.get_employer_account(
            account_id, employer_headers), 200)["seat_credit_balance"] == 0
        assert get_session(second_session["id"])["enrolled_count"] == 0, (
            "the refused sponsorship claimed no seat")

        certificate_id = certificates_for_server(ari["id"])[0]["id"]
        submission = validate_success(api.transmit_certificate(
            certificate_id, ADMIN,
            payload=transmit_payload(batch_reference="TX-BATCH-001")), 201)
        assert submission["submission_state"] == "TRANSMITTED"
        assert submission["attempt_number"] == 1
        assert_same_instant(submission["transmitted_at"], COMPLETION_CLOCK, "transmitted_at")
        assert_same_instant(submission["due_at"], REGISTRY_DUE_AT, "due_at")
        assert submission["late_days"] == 0
        assert submission["penalty_fee_cents"] == 0

        transmitted = get_certificate_row(certificate_id)
        assert transmitted["registry_state"] == "SUBMITTED", (
            "the certificate's registry dimension reads SUBMITTED once transmitted, got "
            f"{transmitted['registry_state']}")
        assert transmitted["validity_state"] == "ACTIVE"

        validate_error(api.transmit_certificate(
            certificate_id, ADMIN,
            payload=transmit_payload(batch_reference="TX-BATCH-002")),
            ApiErrorId.ERR_CERTIFICATE_INVALID_STATE, 409)
        assert len(submissions_for_certificate(certificate_id)) == 1, (
            "the refused retransmission left one record on file")

        first = validate_success(api.create_server_assignment(
            location_id, {"alcohol_server_id": ari["id"], "role_title": "Bartender"},
            employer_headers), 201)
        assert first["assignment_state"] == "ACTIVE"
        validate_error(api.create_server_assignment(
            location_id, {"alcohol_server_id": ari["id"], "role_title": "Shift Lead"},
            employer_headers), ApiErrorId.ERR_DUPLICATE_ASSIGNMENT, 409)
        assert get_location(location_id)["assigned_server_count"] == 1, (
            "the same server counts once at one location")


class TestRoleAndOwnershipDenials:
    def test_five_exclusive_operations_each_refuse_the_wrong_role(self, api):
        """PRD §2.1: "When both headers are well formed but the named role is not among the roles
        authorised for the requested endpoint, the rejection is `ERR_ROLE_NOT_PERMITTED` (HTTP
        403)."
        PRD §2.10: "A regulator attempting to author, revise, publish, submit or resubmit is
        refused with `ERR_ROLE_NOT_PERMITTED`, and so is a `ProgramAdmin` attempting to render a
        decision."
        PRD §2.9: "2. The role is authorised for this endpoint — `ERR_ROLE_NOT_PERMITTED`."

        Design: Corner/rbac/every_exclusive_operation_returns_forbidden_for_the_wrong_role
        """
        base = setup_training_base(clock=CLOCK)
        trainer_headers = base["trainer_headers"]
        server = register_alcohol_server(base["jurisdiction"]["id"])
        employer = setup_employer_account(base["jurisdiction"]["id"], seat_quantity=0,
                                          location_specs=ONE_LOCATION)
        location_id = employer["locations"][0]["id"]

        validate_error(api.create_course(
            course_payload(title="Regulator-authored course"), REGULATOR),
            ApiErrorId.ERR_ROLE_NOT_PERMITTED, 403)
        validate_error(api.create_enrollment(
            enrollment_payload(base["session"]["id"], server["id"],
                               base["session"]["version"]),
            trainer_headers), ApiErrorId.ERR_ROLE_NOT_PERMITTED, 403)
        validate_error(api.create_compliance_run(employer["employer_headers"]),
                       ApiErrorId.ERR_ROLE_NOT_PERMITTED, 403)
        validate_error(api.get_location_compliance_dashboard(
            location_id, make_alcohol_server_headers(server["id"])),
            ApiErrorId.ERR_ROLE_NOT_PERMITTED, 403)
        validate_error(api.decide_course_approval(
            base["approval"]["id"], reject_decision_payload(), ADMIN),
            ApiErrorId.ERR_ROLE_NOT_PERMITTED, 403)

        _, catalogue_meta = validate_paginated(api.list_courses(ADMIN, {"limit": 50}))
        assert catalogue_meta["total_count"] == 1, (
            "the regulator's course was never authored, got "
            f"{catalogue_meta['total_count']}")

        assert get_session(base["session"]["id"])["enrolled_count"] == 0
        _, roster_meta = validate_paginated(api.list_enrollments(ADMIN))
        assert roster_meta["total_count"] == 0, (
            f"the trainer claimed no seat, got {roster_meta['total_count']}")
        assert get_approval(base["approval"]["id"])["approval_status"] == "APPROVED", (
            "the administrator's decision never applied")

    def test_a_second_trainer_cannot_drive_a_class_they_do_not_instruct(self, api):
        """PRD §2.1: "Any entity-backed role acting on a resource it does not own — the wrong
        trainer, the wrong proctor, the wrong employer account, the wrong server — is rejected with
        `ERR_NOT_RESOURCE_OWNER` (HTTP 403). The ownership test is applied on exactly these
        operations: locking a roster, opening an exam, completing and cancelling a class; marking
        attendance and withdrawing a seat; opening and submitting an exam attempt; every write
        beneath an employer account path (setting standing, buying seat credits, adding a location,
        issuing dram-shop documentation); assigning a server to a location; and ending an
        assignment."
        PRD §3.6: "The acting trainer must be the session's instructor, though a `ProgramAdmin` may
        lock any roster without ownership."
        PRD §3.6: "With the roster locked, the instructor marks each seat present or absent by
        supplying `attended`."

        Design: Corner/rbac/a_trainer_cannot_drive_another_trainers_roster
        """
        base = setup_training_base(clock=CLOCK,
                                   jurisdiction_overrides={"proctor_separation_required": False})
        outsider = create_certified_trainer(
            trainer_overrides={"full_name": "Elm Ortiz", "email": "elm@tips.example"})
        outsider_headers = make_trainer_headers(outsider["id"])

        server = register_alcohol_server(base["jurisdiction"]["id"])
        seat = enroll_server(base["session"]["id"], server["id"],
                             headers=make_alcohol_server_headers(server["id"]))

        validate_error(api.lock_roster(base["session"]["id"], outsider_headers),
                       ApiErrorId.ERR_NOT_RESOURCE_OWNER, 403)
        assert get_session(base["session"]["id"])["session_status"] == "SCHEDULED", (
            "the outsider's refusal left the class unlocked")

        locked = lock_roster(base["session"]["id"], base["trainer_headers"])
        assert locked["session_status"] == "ROSTER_LOCKED", (
            "the instructor of record locks their own roster")

        validate_error(api.mark_attendance(seat["id"], {"attended": True}, outsider_headers),
                       ApiErrorId.ERR_NOT_RESOURCE_OWNER, 403)
        assert get_enrollment_row(seat["id"])["enrollment_state"] == "REGISTERED", (
            "the seat is still unmarked after the refused call")
