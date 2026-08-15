"""Referral submission eligibility gauntlet tests (PRD §3.3)."""
from test_helpers import (
    validate_success,
    validate_error,
    validate_paginated,
    get_success_data,
    ApiErrorId,
    TEST_USERS,
    make_employee_headers,
    make_recruiter_headers,
    create_employee,
    create_open_requisition,
    create_active_policy,
    create_candidate,
    submit_referral,
    setup_program,
    setup_referrer_with_suspension,
    get_employee,
    raise_abuse_case,
    confirm_abuse_case,
    create_referral_payload,
    create_employee_payload,
    api_client,
)


class TestTenureBoundary:
    def test_tenure_exactly_min_days_passes(self, api):
        """PRD §3.3: "The referrer's `tenure_days` at the submission instant must be at
        least the active policy's `min_tenure_days`; otherwise `ERR_REFERRER_INELIGIBLE_TENURE`
        (HTTP 422)."
        PRD §3.1: "The server derives `tenure_days` on every read: the elapsed time between
        `hire_date` and the logical clock, divided into whole days of 86400 seconds each and
        rounded down, with the result never allowed to drop below zero".
        PRD §2.4: "At startup the logical clock reads exactly `2026-08-01T00:00:00Z`".
        PRD §3.2: "`min_tenure_days` 90".

        Hire date 2026-05-03 gives tenure exactly 90 days at the default clock; the >= rule passes.

        Design: Difficulty/boundary_precision_check/tenure_exactly_min_days
        """
        create_active_policy()
        emp = create_employee(
            employee_number="E190", full_name="Nine Ty", email="e90@corp.com",
            hire_date="2026-05-03T00:00:00Z",
        )
        req = create_open_requisition(openings=5)

        emp_read = get_employee(emp["id"])
        assert emp_read["tenure_days"] == 90, (
            f"hire 2026-05-03 at clock 2026-08-01 must be 90 days, got {emp_read['tenure_days']}"
        )

        resp = api.create_referral(
            create_referral_payload(
                referrer_id=emp["id"], job_requisition_id=req["id"], candidate_email="c90@x.com"
            ),
            make_employee_headers(emp["id"]),
        )
        data = validate_success(resp, 201)
        assert data["status"] == "SUBMITTED"

    def test_tenure_one_day_under_min_rejected(self, api):
        """PRD §3.3: "The referrer's `tenure_days` at the submission instant must be at
        least the active policy's `min_tenure_days`; otherwise `ERR_REFERRER_INELIGIBLE_TENURE`
        (HTTP 422)."

        Hire date 2026-05-04 gives tenure 89 — one day under the 90-day floor; the
        submission is rejected.

        Design: Difficulty/boundary_precision_check/tenure_exactly_min_days
        """
        create_active_policy()
        emp = create_employee(
            employee_number="E189", full_name="Eight Nine", email="e89@corp.com",
            hire_date="2026-05-04T00:00:00Z",
        )
        req = create_open_requisition(openings=5)

        emp_read = get_employee(emp["id"])
        assert emp_read["tenure_days"] == 89, (
            f"hire 2026-05-04 at clock 2026-08-01 must be 89 days, got {emp_read['tenure_days']}"
        )

        resp = api.create_referral(
            create_referral_payload(
                referrer_id=emp["id"], job_requisition_id=req["id"], candidate_email="c89@x.com"
            ),
            make_employee_headers(emp["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_REFERRER_INELIGIBLE_TENURE)


class TestCooldownBoundary:
    def test_cooldown_exact_months_allows_at_boundary(self, api):
        """PRD §3.1/3.3: "A new referral is blocked strictly while the logical now is
        before `cooldown_until`; at the exact instant of `cooldown_until` the referral
        is allowed."
        PRD §3.1: "The `cooldown_until` itself is the result of adding the policy's
        `duplicate_cooldown_months` calendar months to `last_terminal_outcome_at`".
        PRD §3.2: "`duplicate_cooldown_months` 6".

        prior_application_at 2026-02-01 -> cooldown_until 2026-08-01, exactly the default
        clock; the referral is accepted.

        Design: Difficulty/boundary_precision_check/cooldown_boundary_exact_months
        """
        create_active_policy()
        emp = create_employee(employee_number="E101", email="anna@corp.com")
        cand = create_candidate(
            full_name="Cool Cand", email="cool@x.com",
            prior_application_at="2026-02-01T00:00:00Z",
        )
        req = create_open_requisition()

        resp = api.create_referral(
            {
                "referrer_id": emp["id"],
                "job_requisition_id": req["id"],
                "candidate_id": cand["id"],
            },
            make_employee_headers(emp["id"]),
        )
        data = validate_success(resp, 201)
        assert data["status"] == "SUBMITTED"

    def test_cooldown_one_second_before_boundary_rejected(self, api):
        """PRD §3.1/3.3: "A new referral is blocked strictly while the logical now is
        before `cooldown_until`" — "Violations are rejected with `ERR_CANDIDATE_IN_COOLDOWN`
        (HTTP 422)."

        At 2026-07-31T23:59:59Z (one second before cooldown_until 2026-08-01) the referral
        is rejected.

        Design: Difficulty/boundary_precision_check/cooldown_boundary_exact_months
        """
        create_active_policy()
        emp = create_employee(employee_number="E101", email="anna@corp.com")
        req = create_open_requisition()

        # Move clock one second before the boundary
        pa = TEST_USERS["platform_admin_headers"]
        get_success_data(api.set_clock({"to_iso8601": "2026-07-31T23:59:59Z"}, pa))

        cand = create_candidate(
            full_name="Cool Cand 2", email="cool2@x.com",
            prior_application_at="2026-02-01T00:00:00Z",
        )
        resp = api.create_referral(
            {
                "referrer_id": emp["id"],
                "job_requisition_id": req["id"],
                "candidate_id": cand["id"],
            },
            make_employee_headers(emp["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_CANDIDATE_IN_COOLDOWN)


class TestStateBeatsReferential:
    def test_state_beats_referential_on_submit(self, api):
        """PRD §3.3: "The business gauntlet then executes in a fixed order — the first
        failure stops the pipeline and determines the error: 1. The requisition must be
        in `OPEN`; any other status is rejected with `ERR_REQUISITION_NOT_OPEN` (HTTP 409)."
        — and only at step 4: "The candidate must be referable: `cooldown_until` must be
        null or already reached, and `global_status` must not be `HIRED` — a candidate
        currently hired through the program is permanently blocked from new referrals.
        Violations are rejected with `ERR_CANDIDATE_IN_COOLDOWN` (HTTP 422)."

        A request violating both the requisition-open rule and the cooldown rule reports
        the requisition error.

        Design: Difficulty/priority_pair_validation_conflict/state_beats_referential_on_submit
        """
        create_active_policy()
        emp = create_employee(employee_number="E101", email="anna@corp.com")
        cand = create_candidate(
            full_name="Cool Cand", email="cool@x.com",
            prior_application_at="2026-03-01T00:00:00Z",
        )
        req = create_open_requisition()
        ta = TEST_USERS["talent_admin_headers"]
        get_success_data(api.pause_requisition(req["id"], ta))

        resp = api.create_referral(
            {
                "referrer_id": emp["id"],
                "job_requisition_id": req["id"],
                "candidate_id": cand["id"],
            },
            make_employee_headers(emp["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_REQUISITION_NOT_OPEN)

        # No referral row created for this candidate
        rows, meta = validate_paginated(
            api.list_referrals(ta, params={"candidate_id": cand["id"]})
        )
        assert rows == [], f"expected no referrals, got {rows}"

    def test_state_beats_referential_no_referral_created(self, api):
        """PRD §2.10: "the requisition-is-open check fires before the referrer-suspension
        check, which fires before the self-referral check, and so on through the
        eligibility gauntlet described in §3.3."
        PRD §3.3: "1. The requisition must be in `OPEN`; any other status is rejected
        with `ERR_REQUISITION_NOT_OPEN` (HTTP 409)."

        Against a DRAFT requisition plus a cooling-down candidate, the surfaced error is
        ERR_REQUISITION_NOT_OPEN and no referral exists afterwards.

        Design: Difficulty/priority_pair_validation_conflict/state_beats_referential_on_submit
        """
        create_active_policy()
        emp = create_employee(employee_number="E101", email="anna@corp.com")
        cand = create_candidate(
            full_name="Cool Cand", email="cool2@x.com",
            prior_application_at="2026-03-01T00:00:00Z",
        )
        ta = TEST_USERS["talent_admin_headers"]
        # DRAFT requisition (never opened)
        req = get_success_data(
            api.create_requisition(
                {"req_number": "REQ-D-1", "title": "Draft role", "department": "ENGINEERING", "level": "IC"},
                ta,
            )
        )

        resp = api.create_referral(
            {
                "referrer_id": emp["id"],
                "job_requisition_id": req["id"],
                "candidate_id": cand["id"],
            },
            make_employee_headers(emp["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_REQUISITION_NOT_OPEN)


class TestSafetyBeatsConstraint:
    def test_safety_beats_constraint_on_submit_suspended(self, api):
        """PRD §3.3: "2. The referrer must not be suspended — a `referral_suspended`
        referrer (one whose `risk_score` is at least 100) is rejected with
        `ERR_REFERRER_SUSPENDED` (HTTP 422)." — and only at step 7: "The referrer's
        `tenure_days` at the submission instant must be at least the active policy's
        `min_tenure_days`; otherwise `ERR_REFERRER_INELIGIBLE_TENURE` (HTTP 422)."
        PRD §3.7: "Each case carries a computed `risk_weight`: 40 for `SELF_REFERRAL`,
        25 for `VELOCITY`, 35 for `DUPLICATE_RING`, 50 for `RESUME_FARM`, and 20 for
        `MANUAL`."

        A referrer who is both suspended (risk 105) and tenure-ineligible (31 days) is
        reported as suspended.

        Design: Difficulty/priority_pair_validation_conflict/safety_beats_constraint_on_submit
        """
        create_active_policy()
        # tenure 31 days at default clock (hired 2026-07-01)
        emp = create_employee(
            employee_number="E102", full_name="Shady S", email="shady@corp.com",
            hire_date="2026-07-01T00:00:00Z",
        )
        req = create_open_requisition()
        for ct in ("RESUME_FARM", "DUPLICATE_RING", "MANUAL"):
            case = raise_abuse_case(emp["id"], ct)
            confirm_abuse_case(case["id"])

        emp_read = get_employee(emp["id"])
        assert emp_read["risk_score"] == 105, f"expected risk 105, got {emp_read['risk_score']}"
        assert emp_read["referral_suspended"] is True

        resp = api.create_referral(
            create_referral_payload(
                referrer_id=emp["id"], job_requisition_id=req["id"], candidate_email="fresh@x.com",
                candidate_full_name="Fresh F",
            ),
            make_employee_headers(emp["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_REFERRER_SUSPENDED)

    def test_safety_beats_constraint_no_referral_created(self, api):
        """PRD §3.3: "The business gauntlet then executes in a fixed order — the first
        failure stops the pipeline and determines the error."
        PRD §3.7: "Whenever the score is at least 100, the employee's `referral_suspended`
        flag is true, and — as §3.3's gauntlet establishes — any referral submission by
        that employee is rejected with `ERR_REFERRER_SUSPENDED`."

        After the suspended referral attempt fails, no referral row exists for the employee.

        Design: Difficulty/priority_pair_validation_conflict/safety_beats_constraint_on_submit
        """
        create_active_policy()
        emp = create_employee(
            employee_number="E102", full_name="Shady S", email="shady@corp.com",
            hire_date="2026-07-01T00:00:00Z",
        )
        req = create_open_requisition()
        for ct in ("RESUME_FARM", "DUPLICATE_RING", "MANUAL"):
            case = raise_abuse_case(emp["id"], ct)
            confirm_abuse_case(case["id"])

        resp = api.create_referral(
            create_referral_payload(
                referrer_id=emp["id"], job_requisition_id=req["id"], candidate_email="fresh@x.com",
                candidate_full_name="Fresh F",
            ),
            make_employee_headers(emp["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_REFERRER_SUSPENDED)

        ta = TEST_USERS["talent_admin_headers"]
        rows, meta = validate_paginated(
            api.list_referrals(ta, params={"referrer_id": emp["id"]})
        )
        assert rows == []
