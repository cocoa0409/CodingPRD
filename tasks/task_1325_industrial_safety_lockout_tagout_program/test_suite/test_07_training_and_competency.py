"""Training records and competency: expiry variants, qualification
recomputation, and the competency gate on session planning."""
from test_helpers import (
    ApiErrorId,
    assert_instant_equal,
    assert_training_record,
    bootstrap_manager,
    create_lockout_session_payload,
    create_training_record_payload,
    get_employee,
    make_authorized_employee_headers,
    make_ehs_manager_headers,
    register_employee,
    set_logical_clock,
    setup_machine_with_active_procedure,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestTrainingCompletion:
    def test_complete_recomputes_qualification_and_expiry(self, api):
        """PRD §3.4: "The record starts `ASSIGNED`, stamped with `assigned_at`
        from the clock, with the assignment deadline `due_at` set 30 days after
        assignment."
        PRD §3.4: "For `IN_PERSON` delivery, expiry is anchored to the completion
        instant: exactly 365 days after it, to the second."
        PRD §3.4: "The flag is true exactly when the employee's `qualification`
        is `AUTHORIZED` and at least one of their training records has a
        `course_code` of `LOTO_AUTHORIZED_INITIAL` or `LOTO_AUTHORIZED_REFRESH`,
        a status of `COMPLETED`, and an `expires_at` strictly later than the
        current clock."
        PRD §2.4: "Before the clock has been explicitly set, it reads exactly
        2026-08-01T00:00:00Z; the server must never fall back to wall-clock time."

        Design: Corner/endpoints/training_complete_recomputes_qualification
        """
        mgr = bootstrap_manager("E-MGR-TQ", "Mgr TQ")
        employee = register_employee(mgr, "E-W1-TQ", "W1 TQ")
        assert get_employee(mgr, employee["id"])["is_currently_qualified"] is False

        record = validate_success(api.create_training_record(
            create_training_record_payload(employee["id"],
                                           course_code="LOTO_AUTHORIZED_INITIAL",
                                           delivery_mode="IN_PERSON"),
            make_ehs_manager_headers(mgr["id"])), expected_status=201)
        assert_training_record(record)
        assert record["status"] == "ASSIGNED"
        assert_instant_equal(record["due_at"], "2026-08-31T00:00:00Z")

        completed = validate_success(api.complete_training_record(
            record["id"], make_ehs_manager_headers(mgr["id"])))
        assert completed["status"] == "COMPLETED"
        assert_instant_equal(completed["completed_at"], "2026-08-01T00:00:00Z")
        assert_instant_equal(completed["expires_at"], "2027-08-01T00:00:00Z")

        assert get_employee(mgr, employee["id"])["is_currently_qualified"] is True


class TestTrainingExpiryVariants:
    def _setup_two_trainees(self, api):
        """W1 IN_PERSON and W2 ONLINE, both completed at 2026-08-02T10:00:00Z."""
        mgr = bootstrap_manager("E-MGR-TV", "Mgr TV")
        w1 = register_employee(mgr, "E-W1-TV", "W1 TV")
        w2 = register_employee(mgr, "E-W2-TV", "W2 TV")
        set_logical_clock(mgr, "2026-08-02T10:00:00Z")
        headers = make_ehs_manager_headers(mgr["id"])
        t1 = validate_success(api.create_training_record(
            create_training_record_payload(w1["id"],
                                           course_code="LOTO_AUTHORIZED_INITIAL",
                                           delivery_mode="IN_PERSON"),
            headers), expected_status=201)
        t2 = validate_success(api.create_training_record(
            create_training_record_payload(w2["id"],
                                           course_code="LOTO_AUTHORIZED_INITIAL",
                                           delivery_mode="ONLINE"),
            headers), expected_status=201)
        t1 = validate_success(api.complete_training_record(t1["id"], headers))
        t2 = validate_success(api.complete_training_record(t2["id"], headers))
        return mgr, w1, w2, t1, t2

    def test_anniversary_and_calendar_variants_expire_differently(self, api):
        """PRD §3.4: "For `IN_PERSON` delivery, expiry is anchored to the
        completion instant: exactly 365 days after it, to the second. For
        `ONLINE` delivery, expiry is anchored to the calendar: 23:59:59 UTC on
        December 31 of the year following the year of completion — a course
        completed on 2026-01-10 therefore expires at 2027-12-31T23:59:59Z, not on
        its one-year anniversary."

        Design: Difficulty/dual_variant_calc/training_expiry_variants_diverge
        """
        _mgr, _w1, _w2, t1, t2 = self._setup_two_trainees(api)
        assert_instant_equal(t1["expires_at"], "2027-08-02T10:00:00Z")
        assert_instant_equal(t2["expires_at"], "2027-12-31T23:59:59Z")
        assert t1["expires_at"] != t2["expires_at"], \
            "the two delivery-mode variants diverge for the same completion instant"

    def test_qualification_diverges_between_anniversary_and_calendar(self, api):
        """PRD §3.4: "The flag is true exactly when the employee's
        `qualification` is `AUTHORIZED` and at least one of their training
        records has a `course_code` of `LOTO_AUTHORIZED_INITIAL` or
        `LOTO_AUTHORIZED_REFRESH`, a status of `COMPLETED`, and an `expires_at`
        strictly later than the current clock."
        PRD §3.4: "For `IN_PERSON` delivery, expiry is anchored to the completion
        instant: exactly 365 days after it, to the second. For `ONLINE` delivery,
        expiry is anchored to the calendar: 23:59:59 UTC on December 31 of the
        year following the year of completion — a course completed on 2026-01-10
        therefore expires at 2027-12-31T23:59:59Z, not on its one-year
        anniversary."

        Design: Difficulty/dual_variant_calc/training_expiry_variants_diverge
        """
        mgr, w1, w2, _t1, _t2 = self._setup_two_trainees(api)
        set_logical_clock(mgr, "2027-09-01T00:00:00Z")
        assert get_employee(mgr, w1["id"])["is_currently_qualified"] is False, \
            "IN_PERSON record expired 2027-08-02"
        assert get_employee(mgr, w2["id"])["is_currently_qualified"] is True, \
            "ONLINE record remains valid until 2027-12-31T23:59:59Z"


class TestCompetencyGate:
    def test_untrained_employee_cannot_plan_session(self, api):
        """PRD §3.4: "Three operations demand current authorized-employee
        competency and fail with `ERR_TRAINING_NOT_CURRENT` when the actor's
        `is_currently_qualified` is false: planning a lockout session, issuing an
        employee lock, and scheduling a procedure audit."
        PRD §3.4: "New employees start with `status` `ACTIVE` — employment status
        never leaves `ACTIVE` anywhere in this API surface — with
        `is_currently_qualified` false and an `outstanding_lock_count` of zero."

        Design: Corner/validations/untrained_employee_cannot_create_session
        """
        mgr = bootstrap_manager("E-MGR-TNC", "Mgr TNC")
        untrained = register_employee(mgr, "E-W1-TNC", "W1 TNC")
        machine, survey, procedure = setup_machine_with_active_procedure(
            mgr, untrained, asset_tag="A-TNC-1")

        resp = api.create_lockout_session(
            create_lockout_session_payload(machine["id"], procedure["id"],
                                           session_type="INDIVIDUAL"),
            make_authorized_employee_headers(untrained["id"]))
        validate_error(resp, ApiErrorId.ERR_TRAINING_NOT_CURRENT)
        _sessions, meta = validate_paginated(api.list_lockout_sessions(
            make_ehs_manager_headers(mgr["id"]),
            params={"machine_id": machine["id"]}))
        assert meta["total_count"] == 0
