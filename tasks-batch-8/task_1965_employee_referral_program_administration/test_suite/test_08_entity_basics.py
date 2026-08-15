"""Entity creation defaults, required fields, enums, not-found, computed fields (PRD §3.1, §3.2, §2.5)."""
from test_helpers import (
    validate_success,
    validate_error,
    validate_paginated,
    get_success_data,
    ApiErrorId,
    TEST_USERS,
    NON_EXISTENT_UUID,
    make_employee_headers,
    make_recruiter_headers,
    create_employee,
    create_open_requisition,
    create_active_policy,
    create_candidate,
    submit_referral,
    setup_program,
    create_employee_payload,
    api_client,
    assert_instant_eq,
)


class TestEmployeeCreation:
    def test_employee_creation_defaults_and_system_fields_input_ignored(self, api):
        """PRD §3.1: "A new employee starts with `employment_status` set to `ACTIVE`."
        and "Each employee accumulates two anti-abuse counters maintained entirely by the
        system, both starting at zero: `fraud_strikes`, a count of that employee's
        confirmed abuse cases, and `risk_score`, a decayed weighted sum of those cases
        whose mechanics are detailed in §3.7."
        PRD §3.1: "Two further derived counters, `annual_provisional_cents` and
        `annual_committed_cents`, track the employee's calendar-year bonus totals under
        two different status lenses and are defined precisely in §3.5; both default to
        zero."
        PRD §2.5: "`id` (string): a unique, server-generated identifier formatted as a
        UUID" and "`version` (integer): a system-managed integer that increments by one
        with every mutation of the resource".
        PRD §3.1: "The server derives `tenure_days` on every read: the elapsed time
        between `hire_date` and the logical clock, divided into whole days of 86400
        seconds each and rounded down".

        Client-supplied id/version are ignored; server defaults apply; tenure is 212 days
        at the default clock.

        Design: Corner/entities/employee_creation_defaults_and_system_fields_input_ignored
        """
        pa = TEST_USERS["platform_admin_headers"]
        resp = api.create_employee(
            {
                "employee_number": "E101", "full_name": "Ann A", "email": "anna@corp.com",
                "department": "ENGINEERING", "job_level": "IC",
                "hire_date": "2026-01-01T00:00:00Z",
                "id": "11111111-1111-1111-1111-111111111111", "version": 99,
            },
            pa,
        )
        data = validate_success(resp, 201)
        assert data["id"] != "11111111-1111-1111-1111-111111111111"
        assert data["fraud_strikes"] == 0
        assert data["risk_score"] == 0
        assert data["employment_status"] == "ACTIVE"
        assert data["referral_suspended"] is False
        assert data["version"] == 1
        # 2026-01-01 -> 2026-08-01 is 212 days
        assert data["tenure_days"] == 212, f"expected tenure 212, got {data['tenure_days']}"

    def test_employee_missing_required_email_returns_invalid_request(self, api):
        """PRD §2.10: "**Request shape** — required fields are present, types are valid,
        dates parse, enum-like inputs are in range, and structural constraints such as
        "a requisition's `openings` is at least 1" hold; otherwise `ERR_INVALID_REQUEST`."
        PRD §3.1: "Creating an employee records their unique `employee_number` (unique
        across all employees), `full_name`, work `email`, `department` code, `job_level`
        (one of `IC`, `SENIOR`, `MANAGER`, `DIRECTOR`, or `EXECUTIVE`), and `hire_date`".

        Omitting the required email yields 400 ERR_INVALID_REQUEST.

        Design: Corner/entities/employee_missing_required_email_returns_invalid_request
        """
        pa = TEST_USERS["platform_admin_headers"]
        resp = api.create_employee(
            {
                "employee_number": "E101", "full_name": "Ann A",
                "department": "ENGINEERING", "job_level": "IC",
                "hire_date": "2026-01-01T00:00:00Z",
            },
            pa,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)

    def test_employee_invalid_job_level_returns_invalid_enum(self, api):
        """PRD §2.10: "**Enum membership** — every enum field carries a declared member
        (this covers `job_level`, `level`, `case_type`, `filing_status`,
        `withholding_method`, the `to_state` of a stage advancement, and the
        `reason_code` of a rejection); otherwise `ERR_INVALID_ENUM`."
        PRD §3.1: "Creating an employee records their unique `employee_number` (unique
        across all employees), `full_name`, work `email`, `department` code, `job_level`
        (one of `IC`, `SENIOR`, `MANAGER`, `DIRECTOR`, or `EXECUTIVE`), and `hire_date`".

        job_level 'CEO' is not a declared member.

        Design: Corner/entities/employee_invalid_job_level_returns_invalid_enum
        """
        pa = TEST_USERS["platform_admin_headers"]
        resp = api.create_employee(
            create_employee_payload(job_level="CEO"),
            pa,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_ENUM)

    def test_employee_get_nonexistent_returns_not_found(self, api):
        """PRD §2.9: "the server validates the existence of each identifier in path
        order and rejects the request immediately with `ERR_NOT_FOUND` (HTTP 404) at the
        *first* identifier that does not correspond to an existing resource".

        Design: Corner/entities/employee_get_nonexistent_returns_not_found
        """
        pa = TEST_USERS["platform_admin_headers"]
        resp = api.get_employee(NON_EXISTENT_UUID, pa)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND)


class TestCandidateComputedFields:
    def test_candidate_cooldown_until_computed_from_prior_application(self, api):
        """PRD §3.1/§3.3: "Registering a candidate with a `prior_application_at` seeds
        `last_terminal_outcome_at` with that timestamp at creation. The `cooldown_until`
        itself is the result of adding the policy's `duplicate_cooldown_months` calendar
        months to `last_terminal_outcome_at`, with the day clamped to the target month's
        last day as described in §2.4". "A candidate begins with `global_status`
        `AVAILABLE`".
        PRD §3.2: "`duplicate_cooldown_months` 6".

        prior_application_at 2026-02-01 -> cooldown_until 2026-08-01, status AVAILABLE.

        Design: Corner/entities/candidate_cooldown_until_computed_from_prior_application
        """
        ta = TEST_USERS["talent_admin_headers"]
        resp = api.create_candidate(
            {
                "full_name": "Cool Cand", "email": "cool@x.com",
                "prior_application_at": "2026-02-01T00:00:00Z",
            },
            ta,
        )
        data = validate_success(resp, 201)
        assert_instant_eq(data["cooldown_until"], "2026-08-01T00:00:00Z")
        assert data["global_status"] == "AVAILABLE"
        assert_instant_eq(data["last_terminal_outcome_at"], "2026-02-01T00:00:00Z")


class TestRequisitionComputedFields:
    def test_requisition_open_referral_count_computed(self, api):
        """PRD §3.2: "The derived `open_referral_count` reports how many of the
        requisition's referrals are currently non-terminal."
        PRD §3.4: "The referrer themselves may withdraw at any point before hire — from
        `SUBMITTED`, `UNDER_REVIEW`, `NEEDS_INFO`, `QUALIFIED`, `SCREENING`,
        `INTERVIEWING`, or `OFFER_EXTENDED` — moving the referral to `WITHDRAWN` (event
        `WITHDRAW`)".

        2 after two submissions; back to 1 after one withdrawal.

        Design: Corner/entities/requisition_open_referral_count_computed
        """
        create_active_policy()
        emp = create_employee(employee_number="E101", email="anna@corp.com")
        req = create_open_requisition(openings=5)
        r1 = submit_referral(emp["id"], req["id"], candidate_email="c1@x.com",
                             candidate_full_name="C One")
        submit_referral(emp["id"], req["id"], candidate_email="c2@x.com",
                        candidate_full_name="C Two")

        ta = TEST_USERS["talent_admin_headers"]
        req_now = get_success_data(api.get_requisition(req["id"], ta))
        assert req_now["open_referral_count"] == 2

        get_success_data(api.withdraw_referral(r1["id"], make_employee_headers(emp["id"])))
        req_after = get_success_data(api.get_requisition(req["id"], ta))
        assert req_after["open_referral_count"] == 1


class TestReferralEventLog:
    def test_referral_event_append_only_immutable_log(self, api):
        """PRD §2.11: "Every referral carries an append-only log of **ReferralEvent**
        records. Each event stores the `referral_id` it belongs to, the machine name of
        what happened in `event_type` (for example `SUBMIT`, `REVIEW`, `REQUEST_INFO`,
        `PROVIDE_INFO`, `QUALIFY`, `REJECT`, `ADVANCE`, `OFFER_DECLINED`, `HIRE`,
        `NOT_SELECTED`, `WITHDRAW`, `EXPIRE`, `FORFEIT`, `RETENTION_MET`, or
        `RETENTION_FAILED`), the referral's `from_state` and `to_state`
        around the event, the `actor_user_id` of who triggered it (the caller's
        `X-User-ID`, or the literal string `system` for automatic transitions)".
        PRD §2.5: "As an append-only audit record it carries only `id` and `created_at`;
        `updated_at` and `version` are absent because events are never modified after
        being written."

        After submit + review: exactly 2 events with correct actors; no version field.

        Design: Corner/entities/referral_event_append_only_immutable_log
        """
        program = setup_program()
        emp = create_employee(employee_number="E101", email="anna@corp.com")
        ref = submit_referral(emp["id"], program["req"]["id"], candidate_email="c1@x.com",
                              candidate_full_name="C One")
        rec_h = make_recruiter_headers(program["rec"]["id"])
        get_success_data(api.review_referral(ref["id"], rec_h))

        events = get_success_data(api.list_referral_events(ref["id"], rec_h))
        assert len(events) == 2
        assert [e["event_type"] for e in events] == ["SUBMIT", "REVIEW"]
        assert events[0]["from_state"] in (None, "SUBMITTED")
        assert events[0]["to_state"] == "SUBMITTED"
        assert events[1]["from_state"] == "SUBMITTED"
        assert events[1]["to_state"] == "UNDER_REVIEW"
        assert events[0]["actor_user_id"] == emp["id"]
        assert events[1]["actor_user_id"] == program["rec"]["id"]
        for e in events:
            assert "version" not in e, "ReferralEvent must not carry version"
            assert "updated_at" not in e, "ReferralEvent must not carry updated_at"


class TestTaxProfileUpsert:
    def test_tax_profile_upsert_reverts_verified_on_update(self, api):
        """PRD §3.1: "The profile is upserted — created on first write, replaced on
        later writes" and "Any subsequent update to a verified profile re-opens
        verification by returning the status to `SUBMITTED`" and "Reading a tax profile
        returns an array containing zero or one element, reflecting the one-to-one
        relationship."

        After PUT -> verify -> PUT: one row, status SUBMITTED, new filing values.

        Design: Corner/entities/tax_profile_upsert_reverts_verified_on_update
        """
        emp = create_employee(employee_number="E101", email="anna@corp.com")
        emp_h = make_employee_headers(emp["id"])
        pp = TEST_USERS["payroll_processor_headers"]

        get_success_data(
            api.put_tax_profile(
                emp["id"],
                {"filing_status": "SINGLE", "withholding_method": "FLAT", "ytd_carryover_cents": 1000},
                emp_h,
            )
        )
        get_success_data(api.verify_tax_profile(emp["id"], pp))

        get_success_data(
            api.put_tax_profile(
                emp["id"],
                {"filing_status": "MARRIED", "withholding_method": "AGGREGATE"},
                emp_h,
            )
        )
        rows = get_success_data(api.get_tax_profile(emp["id"], pp))
        assert isinstance(rows, list) and len(rows) == 1, (
            f"1:1 upsert must yield exactly one TaxProfile row, got {rows}"
        )
        assert rows[0]["status"] == "SUBMITTED"
        assert rows[0]["filing_status"] == "MARRIED"
        assert rows[0]["withholding_method"] == "AGGREGATE"
        # "replaced on later writes": the omitted carryover returns to its default zero
        assert rows[0]["ytd_carryover_cents"] == 0
