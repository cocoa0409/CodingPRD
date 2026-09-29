"""Policy files: the three independent dimensions, the issuance guards and timeliness."""

from test_helpers import (
    ApiErrorId,
    add_line,
    approve_referral,
    assert_issuance_status,
    assert_money_equal,
    assert_policy_dimensions,
    assert_posture,
    assert_total_count,
    assert_unremitted_ledger,
    create_policy_file,
    create_statement,
    factories,
    issue_policy,
    lapse_license,
    onboard_agency,
    read_agency,
    reconcile_statement,
    request_letter,
    submit_statement,
    terminate_agency,
    transition_letter,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.fixtures import COUNSEL, OFFICER


class TestIndependentStatusDimensions:
    """One row, three dimensions, three different triggers."""

    def test_reconciliation_advances_only_the_accounting_dimension(self, api, env):
        """After reconciliation the row reads `ISSUED` / `REPORTED` / `NOT_REQUIRED`.

        PRD: "`remittance_status` is the accounting dimension and is advanced *only* by
        remittance statement transitions, never by a direct request against the file."

        Design: Difficulty/non_linear_state_machine/policy_file_three_dimensions_advance_independently
        """
        policy_file = create_policy_file(
            api, env, closing_date="2026-07-10", gross_premium_cents=1_000_000
        )
        issued = issue_policy(api, env, policy_file["id"])
        assert_policy_dimensions(issued, "ISSUED", "UNREPORTED", "NOT_REQUIRED")

        statement = create_statement(api, env, "2026-07-01", "2026-07-31")
        add_line(api, env, statement["id"], policy_file["id"], 1_000_000)
        submit_statement(api, env, statement["id"])
        reconcile_statement(api, statement["id"])

        after = validate_success(api.get_policy_file(policy_file["id"], OFFICER))
        assert_policy_dimensions(after, "ISSUED", "REPORTED", "NOT_REQUIRED")

    def test_termination_advances_only_the_wind_down_dimension(self, api, env):
        """Termination moves `transfer_status` and leaves the other two dimensions alone.

        PRD: "every policy file of the agency whose `issuance_status` is `ISSUED` or
        `LATE_ISSUED` and whose `transfer_status` is `NOT_REQUIRED` moves to
        `PENDING_TRANSFER` with `transferee_agency_id` copied from the agency's
        `transferee_agency_id`, after which the agency's `pending_transfer_count` is
        recomputed."

        Design: Difficulty/non_linear_state_machine/policy_file_three_dimensions_advance_independently
        """
        policy_file = create_policy_file(
            api, env, closing_date="2026-07-10", gross_premium_cents=1_000_000
        )
        issue_policy(api, env, policy_file["id"])
        statement = create_statement(api, env, "2026-07-01", "2026-07-31")
        add_line(api, env, statement["id"], policy_file["id"], 1_000_000)
        submit_statement(api, env, statement["id"])
        reconcile_statement(api, statement["id"])

        terminated = terminate_agency(api, env.agency_id, termination_reason="VOLUNTARY")

        after = validate_success(api.get_policy_file(policy_file["id"], OFFICER))
        assert_policy_dimensions(after, "ISSUED", "REPORTED", "PENDING_TRANSFER")
        assert terminated["appointment_status"] == "TERMINATED", (
            f"the agency should read TERMINATED, got {terminated['appointment_status']}"
        )
        assert_posture(terminated, "FROZEN")
        assert terminated["pending_transfer_count"] == 1, (
            "one in-force file awaits transfer, so pending_transfer_count must be 1, "
            f"got {terminated['pending_transfer_count']}"
        )


class TestIssuanceTimelinessBoundary:
    """The elapsed-day comparison is inclusive on the timely side."""

    def test_exactly_thirty_elapsed_days_lands_on_issued(self, api, env):
        """A closing 30 days back is still timely against a 30-day deadline.

        PRD: "With a `policy_issuance_deadline_days` of 30 and a logical clock reading
        2026-08-01, a `closing_date` of 2026-07-02 gives 30 elapsed days and lands on
        `ISSUED`, while a `closing_date` of 2026-07-01 gives 31 and lands on
        `LATE_ISSUED`."

        Design: Difficulty/boundary_precision_check/policy_issued_at_exactly_thirty_elapsed_days_is_timely
        """
        on_time = create_policy_file(
            api, env, closing_date="2026-07-02", gross_premium_cents=500_000
        )

        issued = issue_policy(api, env, on_time["id"], policy_number="POL-61")

        assert issued["issuance_elapsed_days"] == 30, (
            "2026-07-02 to 2026-08-01 is 30 whole days, got "
            f"{issued['issuance_elapsed_days']}"
        )
        assert_issuance_status(issued, "ISSUED")

    def test_thirty_one_elapsed_days_lands_on_late_issued(self, api, env):
        """One day earlier crosses the deadline, and both statuses feed the ledger.

        PRD: "When that elapsed count is less than or equal to the state's
        `policy_issuance_deadline_days` the file becomes `ISSUED`; when it is strictly
        greater the file becomes `LATE_ISSUED`."

        Design: Difficulty/boundary_precision_check/policy_issued_at_exactly_thirty_elapsed_days_is_timely
        """
        on_time = create_policy_file(
            api, env, closing_date="2026-07-02", gross_premium_cents=500_000
        )
        issue_policy(api, env, on_time["id"], policy_number="POL-61")
        late = create_policy_file(
            api, env, closing_date="2026-07-01", gross_premium_cents=500_000
        )

        issued_late = issue_policy(api, env, late["id"], policy_number="POL-62")

        assert issued_late["issuance_elapsed_days"] == 31, (
            "2026-07-01 to 2026-08-01 is 31 whole days, got "
            f"{issued_late['issuance_elapsed_days']}"
        )
        assert_issuance_status(issued_late, "LATE_ISSUED")
        assert_unremitted_ledger(read_agency(api, env.agency_id), 1_000_000)


class TestIssuanceGuardPrecedence:
    """Pairing P2: the coverage error outranks the appointment error."""

    def test_lapsed_coverage_is_reported_ahead_of_the_missing_appointment(
        self, api, state_program
    ):
        """Both guards are violated, both are 422, and the coverage error must win.

        PRD: "An appointment with `status` `ACTIVE` must exist for the pair, else
        `ERR_NO_ACTIVE_APPOINTMENT_IN_STATE` — and when both the coverage and the
        appointment have failed, pairing P2 dictates that the coverage error is the one
        returned."

        Design: Difficulty/priority_pair_validation_conflict/policy_issue_eo_lapse_outranks_missing_appointment_returns_422
        """
        env = onboard_agency(
            api,
            state_program=state_program,
            review_overrides={"submitted_eo_expires_on": "2026-06-30"},
        )
        policy_file = create_policy_file(api, env)
        lapse_license(api, env.appointment_id)

        response = api.transition_issuance(
            policy_file["id"],
            factories.issuance_state_payload("ISSUED", policy_number="POL-51"),
            env.principal,
        )

        validate_error(response, ApiErrorId.ERR_EO_COVERAGE_LAPSED.value, 422)
        body = response.json()
        assert (
            body["data"]["error_id"]
            != ApiErrorId.ERR_NO_ACTIVE_APPOINTMENT_IN_STATE.value
        ), (
            "the referential error must not surface while the coverage has lapsed, but "
            f"the response carried {body['data']['error_id']}"
        )

    def test_the_refused_issuance_leaves_the_file_pending(self, api, state_program):
        """Nothing is written: the file stays `PENDING` with no policy number.

        PRD: "The effective `eo_expires_on` must be non-null and on or after the clock's
        current date, else `ERR_EO_COVERAGE_LAPSED`."

        Design: Difficulty/priority_pair_validation_conflict/policy_issue_eo_lapse_outranks_missing_appointment_returns_422
        """
        env = onboard_agency(
            api,
            state_program=state_program,
            review_overrides={"submitted_eo_expires_on": "2026-06-30"},
        )
        policy_file = create_policy_file(api, env)
        lapsed = lapse_license(api, env.appointment_id)
        assert lapsed["status"] == "LAPSED", (
            f"the appointment should read LAPSED, got {lapsed['status']}"
        )
        assert_posture(read_agency(api, env.agency_id), "OPEN")

        refused = api.transition_issuance(
            policy_file["id"],
            factories.issuance_state_payload("ISSUED", policy_number="POL-51"),
            env.principal,
        )
        validate_error(refused, ApiErrorId.ERR_EO_COVERAGE_LAPSED.value, 422)

        after = validate_success(api.get_policy_file(policy_file["id"], OFFICER))
        assert_issuance_status(after, "PENDING")
        assert after["policy_number"] is None, (
            f"policy_number must still be null, got {after['policy_number']!r}"
        )
        assert_unremitted_ledger(read_agency(api, env.agency_id), 0)


class TestCitedLetterCondition:
    """The letter precondition is evaluated only when `cpl_id` is non-null."""

    def test_letter_check_applies_only_to_the_file_that_cites_one(self, api, env):
        """A file with no letter issues; the file citing a `REQUESTED` letter waits.

        PRD: "When the file carries a non-null `cpl_id`, that letter's `status` must be
        `ISSUED`, else `ERR_CPL_NOT_ISSUED` (HTTP 422)."

        Design: Corner/validations/conditional_validation_cpl_issuance_check_applies_only_when_policy_cites_a_letter
        """
        letter = request_letter(api, env, requested_coverage_cents=30_000_000)
        cites_letter = create_policy_file(
            api,
            env,
            cpl_id=letter["id"],
            closing_date="2026-07-20",
            gross_premium_cents=400_000,
        )
        cites_nothing = create_policy_file(
            api, env, closing_date="2026-07-20", gross_premium_cents=400_000
        )

        free_file = issue_policy(api, env, cites_nothing["id"], policy_number="POL-752")
        assert_issuance_status(free_file, "ISSUED")

        blocked = api.transition_issuance(
            cites_letter["id"],
            factories.issuance_state_payload("ISSUED", policy_number="POL-751"),
            env.principal,
        )
        validate_error(blocked, ApiErrorId.ERR_CPL_NOT_ISSUED.value, 422)
        assert_issuance_status(
            validate_success(api.get_policy_file(cites_letter["id"], OFFICER)), "PENDING"
        )

        transition_letter(
            api, letter["id"], "ISSUED", OFFICER, rationale="Letter released"
        )

        now_issued = issue_policy(api, env, cites_letter["id"], policy_number="POL-751")
        assert_issuance_status(now_issued, "ISSUED")
        assert_unremitted_ledger(read_agency(api, env.agency_id), 800_000)


class TestAuthorityLimitAndReferral:
    """The fiscal authority check reads the outcome of the referral decision."""

    def test_counsel_referral_lifts_the_authority_limit(self, api, env):
        """An 80,000,000 liability is issuable only because counsel decided the referral.

        PRD: "Finally, in the fiscal tier, either the file's `approved_liability_cents`
        must not exceed the agency's `underwriting_authority_limit_cents`, or the file
        must carry a non-null `referral_decided_by_user_id` — a counsel referral
        decision lifts the authority limit — and failing both gives
        `ERR_UNDERWRITING_AUTHORITY_EXCEEDED` (HTTP 422)."

        Design: Corner/validations/cascading_validation_counsel_referral_lifts_the_authority_limit
        """
        policy_file = create_policy_file(
            api,
            env,
            closing_date="2026-07-20",
            liability_amount_cents=80_000_000,
            gross_premium_cents=800_000,
        )
        assert_issuance_status(policy_file, "PENDING_REFERRAL")
        assert_money_equal(
            policy_file["approved_liability_cents"], 0, "approved_liability_cents"
        )

        over_approval = api.transition_issuance(
            policy_file["id"],
            factories.issuance_state_payload(
                "PENDING",
                approved_liability_cents=90_000_000,
                rationale="Over-approval attempt",
            ),
            COUNSEL,
        )
        validate_error(
            over_approval, ApiErrorId.ERR_APPROVED_LIABILITY_ABOVE_REQUEST.value, 422
        )

        approved = approve_referral(api, policy_file["id"], 80_000_000)
        assert_issuance_status(approved, "PENDING")
        assert_money_equal(
            approved["approved_liability_cents"], 80_000_000, "approved_liability_cents"
        )
        assert approved["referral_decided_by_user_id"] == "counsel-1", (
            "the counsel's own identifier is the segregation-of-duties anchor, got "
            f"{approved['referral_decided_by_user_id']!r}"
        )

        issued = issue_policy(api, env, policy_file["id"], policy_number="POL-761")
        assert_issuance_status(issued, "ISSUED")
        assert issued["issuance_elapsed_days"] == 12, (
            "2026-07-20 to 2026-08-01 is 12 whole days, got "
            f"{issued['issuance_elapsed_days']}"
        )
        assert_unremitted_ledger(read_agency(api, env.agency_id), 800_000)


class TestPolicyNumberAndLineUniqueness:
    """Two collisions further down the lifecycle."""

    def test_reused_policy_number_and_repeated_line_are_refused(self, api, env):
        """An issued number is reserved, and one statement reports a policy once.

        PRD: "The supplied `policy_number` must not already be in use among that same
        agency's policy files whose `issuance_status` is `ISSUED` or `LATE_ISSUED`, else
        `ERR_DUPLICATE_POLICY_NUMBER` (HTTP 409); numbers on pending, declined or voided
        files do not reserve anything."

        Design: Corner/errors/policy_number_and_line_uniqueness_are_enforced_returns_409
        """
        first = create_policy_file(
            api, env, closing_date="2026-07-10", gross_premium_cents=33_333
        )
        second = create_policy_file(
            api, env, closing_date="2026-07-11", gross_premium_cents=33_333
        )
        issue_policy(api, env, first["id"], policy_number="POL-901")

        collision = api.transition_issuance(
            second["id"],
            factories.issuance_state_payload("ISSUED", policy_number="POL-901"),
            env.principal,
        )
        validate_error(collision, ApiErrorId.ERR_DUPLICATE_POLICY_NUMBER.value, 409)
        assert_issuance_status(
            validate_success(api.get_policy_file(second["id"], OFFICER)), "PENDING"
        )

        freed = issue_policy(api, env, second["id"], policy_number="POL-902")
        assert_issuance_status(freed, "ISSUED")

        statement = create_statement(api, env, "2026-07-01", "2026-07-31")
        add_line(api, env, statement["id"], first["id"], 33_333)

        repeat = api.create_line(
            statement["id"],
            factories.create_line_payload(first["id"], 33_333),
            env.principal,
        )
        validate_error(repeat, ApiErrorId.ERR_POLICY_ALREADY_ON_STATEMENT.value, 409)

        _rows, meta = validate_paginated(api.list_lines(statement["id"], OFFICER))
        assert_total_count(meta, 1)
