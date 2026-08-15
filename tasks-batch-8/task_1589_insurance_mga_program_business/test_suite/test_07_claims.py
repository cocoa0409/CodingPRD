"""Claims: TPA selector ranking and tie-breaks, intake temporal guards,
adjudication authority cap, payment ledger side effects, and the bounded
reopen cycle."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    collect_premium,
    create_active_appointment,
    create_claim_under_review,
    create_issued_policy,
    create_paid_claim,
    create_tpa,
    get_claim_fresh,
    get_policy_fresh,
    get_program_fresh,
    list_ledger,
    make_carrier_underwriter_headers,
    make_tpa_adjuster_headers,
    report_claim,
    set_clock,
    setup_active_program,
    setup_program_with_issued_policy_and_tpa,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["platform_admin_headers"]
UW = TEST_USERS["mga_underwriter_headers"]
FIN = TEST_USERS["mga_finance_headers"]


class TestTpaSelector:
    def test_selector_ranks_highest_authority(self, api):
        """PRD §3.6: "Candidates are ranked by `authority_limit_cents`
        descending; ties break by `created_at` ascending and then by the TPA's
        `license_number` ascending."

        Design: Corner/calculations/tpa_selector_ranks_highest_authority
        """
        carrier, program, _g, _a, _f = setup_active_program()
        tpa_a = create_tpa()
        tpa_b = create_tpa()
        # A created first with the LOWER authority.
        create_active_appointment(program, tpa_a, authority_limit_cents=50000)
        create_active_appointment(program, tpa_b, authority_limit_cents=80000)
        policy = create_issued_policy(program)

        claim = report_claim(policy, occurrence_date="2026-08-10T00:00:00Z",
                             amount_claimed_cents=30000)
        assert claim["assigned_tpa_id"] == tpa_b["id"], \
            "higher authority_limit_cents beats earlier creation"
        assert claim["status"] == "REPORTED"

    def test_selector_tiebreak_earliest_created(self, api):
        """PRD §3.6: "Candidates are ranked by `authority_limit_cents`
        descending; ties break by `created_at` ascending and then by the TPA's
        `license_number` ascending — a business field, never an opaque id."

        Design: Corner/calculations/tpa_selector_tiebreak_earliest_created
        """
        carrier, program, _g, _a, _f = setup_active_program()
        tpa_c = create_tpa(license_number="LIC-TBC")
        tpa_d = create_tpa(license_number="LIC-TBD")
        create_active_appointment(program, tpa_c, authority_limit_cents=100000)
        create_active_appointment(program, tpa_d, authority_limit_cents=100000)
        policy = create_issued_policy(program)

        claim = report_claim(policy, occurrence_date="2026-08-10T00:00:00Z",
                             amount_claimed_cents=30000)
        assert claim["assigned_tpa_id"] == tpa_c["id"], \
            "equal authority -> earliest created_at wins"

    def test_selector_empty_pool_rejected_and_no_claim_persisted(self, api):
        """PRD §3.6: "If the candidate set is empty the claim is not created
        at all, and the report is rejected with `ERR_NO_ELIGIBLE_TPA`."

        Design: Corner/calculations/tpa_selector_empty_pool_rejected
        """
        carrier, program, tpa, appt, policy = \
            setup_program_with_issued_policy_and_tpa()  # LIABILITY appointment only
        resp = api.report_claim(policy["id"], {
            "claim_type": "BODILY_INJURY",
            "occurrence_date": "2026-08-10T00:00:00Z",
            "amount_claimed_cents": 30000}, UW)
        validate_error(resp, ApiErrorId.ERR_NO_ELIGIBLE_TPA)
        rows, meta = validate_paginated(api.list_policy_claims(policy["id"], UW))
        assert meta["total_count"] == 0


class TestClaimIntakeGuards:
    def test_occurrence_outside_coverage_period_rejected(self, api):
        """PRD §3.6: "the occurrence must fall inside the policy term — on or
        after `effective_from` and strictly before `effective_to` — failing
        with `ERR_OUTSIDE_COVERAGE_PERIOD`."

        Design: Corner/validations/claim_occurrence_outside_coverage_period
        """
        carrier, program, tpa, appt, policy = \
            setup_program_with_issued_policy_and_tpa(
                appointment_overrides={"effective_to": "2027-12-31T00:00:00Z"})
        # Policy term is [2026-08-01, 2027-08-01); occurrence 2027-08-05 is out.
        set_clock("2027-08-06T00:00:00Z")
        resp = api.report_claim(policy["id"], {
            "claim_type": "LIABILITY",
            "occurrence_date": "2027-08-05T00:00:00Z",
            "amount_claimed_cents": 30000}, UW)
        validate_error(resp, ApiErrorId.ERR_OUTSIDE_COVERAGE_PERIOD)

    def test_reporting_deadline_boundary(self, api):
        """PRD §3.6: "the occurrence may be no more than sixty days before the
        report clock, failing with `ERR_REPORTING_DEADLINE_MISSED`."

        Design: Corner/validations/claim_reporting_deadline_missed
        """
        carrier, program, tpa, appt, policy = \
            setup_program_with_issued_policy_and_tpa()
        # Occurrence 2026-08-10; report at 2026-10-09 is exactly 60 days.
        set_clock("2026-10-09T00:00:00Z")
        ok = report_claim(policy, occurrence_date="2026-08-10T00:00:00Z",
                          amount_claimed_cents=30000)
        assert ok["status"] == "REPORTED"

        set_clock("2026-10-10T00:00:00Z")  # 61 days
        resp = api.report_claim(policy["id"], {
            "claim_type": "LIABILITY",
            "occurrence_date": "2026-08-10T00:00:00Z",
            "amount_claimed_cents": 31000}, UW)
        validate_error(resp, ApiErrorId.ERR_REPORTING_DEADLINE_MISSED)


class TestClaimStateGates:
    def test_approve_from_reported_rejected(self, api):
        """PRD §3.6: "A TPA adjuster approves only from `UNDER_REVIEW`" —
        approving a `REPORTED` claim is a state-legality violation
        (`ERR_INVALID_STATE`, PRD §2.11).

        Design: Corner/state_machines/claim_approve_from_reported_invalid_state
        """
        carrier, program, tpa, appt, policy = \
            setup_program_with_issued_policy_and_tpa()
        claim = report_claim(policy, occurrence_date="2026-08-01T00:00:00Z",
                             amount_claimed_cents=50000)
        resp = api.approve_claim(claim["id"], {"approved_amount_cents": 50000},
                                 make_tpa_adjuster_headers(tpa["id"]))
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        assert get_claim_fresh(claim["id"])["status"] == "REPORTED"

    def test_closed_claim_is_terminal(self, api):
        """PRD §3.6: "Closure is the carrier's final act: a claim in `PAID` or
        `DENIED` moves to `CLOSED`, which is terminal." PRD §2.11: "An entity
        in a terminal state rejects every further transition with
        `ERR_INVALID_STATE` (HTTP 409)."

        Design: Corner/state_machines/claim_closed_terminal_lockdown
        """
        carrier, program, tpa, appt, policy = \
            setup_program_with_issued_policy_and_tpa()
        claim = create_paid_claim(program, policy, tpa, 40000,
                                  occurrence_date="2026-08-01T00:00:00Z",
                                  amount_claimed_cents=40000)
        cu = make_carrier_underwriter_headers(carrier["id"])
        closed = validate_success(api.close_claim(claim["id"], cu))
        assert closed["status"] == "CLOSED"

        resp = api.deny_claim(claim["id"], {"denial_reason": "too late"}, cu)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


class TestAuthorityBoundary:
    def test_tpa_approve_at_exact_limit_and_one_cent_over(self, api):
        """PRD §3.6: "A TPA adjuster approves only from `UNDER_REVIEW`, only
        while the assigning appointment is `ACTIVE`, and only within the
        appointment's `authority_limit_cents` — an approval above that cap is
        rejected with `ERR_AUTHORITY_LIMIT_EXCEEDED` ... The carrier
        underwriter approves from `UNDER_REVIEW` or `REFERRED` and is bound by
        no authority cap."

        Design: Difficulty/boundary_precision_check/claim_authority_exact_limit_vs_one_cent_over
        """
        carrier, program, tpa, appt, policy = \
            setup_program_with_issued_policy_and_tpa(
                program_overrides={"aggregate_limit_cents": 1000000},
                policy_overrides={"exposure_units": 240,
                                  "coverage_limit_cents": 900000},
                appointment_overrides={"authority_limit_cents": 100000},
                guideline_overrides={"max_policy_premium_cents": 500000},
                allocation_overrides={"allocated_cents": 500000})
        tpa_h = make_tpa_adjuster_headers(tpa["id"])
        cl_a = create_claim_under_review(program, policy, tpa,
                                         occurrence_date="2026-08-10T00:00:00Z",
                                         amount_claimed_cents=150000)
        cl_b = create_claim_under_review(program, policy, tpa,
                                         occurrence_date="2026-08-11T00:00:00Z",
                                         amount_claimed_cents=150000)

        ok = validate_success(api.approve_claim(
            cl_a["id"], {"approved_amount_cents": 100000}, tpa_h))
        assert ok["status"] == "APPROVED", "boundary is inclusive"

        over = api.approve_claim(cl_b["id"], {"approved_amount_cents": 100001}, tpa_h)
        validate_error(over, ApiErrorId.ERR_AUTHORITY_LIMIT_EXCEEDED)

        cu = make_carrier_underwriter_headers(carrier["id"])
        carrier_ok = validate_success(api.approve_claim(
            cl_b["id"], {"approved_amount_cents": 100001}, cu))
        assert carrier_ok["status"] == "APPROVED", "carrier is uncapped"

    def test_tpa_approve_over_cap_keeps_claim_under_review(self, api):
        """PRD §3.6: "an approval above that cap is rejected with
        `ERR_AUTHORITY_LIMIT_EXCEEDED`" — the rejected approval leaves the
        claim in `UNDER_REVIEW` (no partial mutation).

        Design: Difficulty/boundary_precision_check/claim_authority_exact_limit_vs_one_cent_over
        """
        carrier, program, tpa, appt, policy = \
            setup_program_with_issued_policy_and_tpa(
                appointment_overrides={"authority_limit_cents": 50000})
        claim = create_claim_under_review(program, policy, tpa,
                                          occurrence_date="2026-08-10T00:00:00Z",
                                          amount_claimed_cents=80000)
        resp = api.approve_claim(claim["id"], {"approved_amount_cents": 50001},
                                 make_tpa_adjuster_headers(tpa["id"]))
        validate_error(resp, ApiErrorId.ERR_AUTHORITY_LIMIT_EXCEEDED)
        fresh = get_claim_fresh(claim["id"])
        assert fresh["status"] == "UNDER_REVIEW"
        assert fresh["approved_amount_cents"] is None

    def test_approve_amount_above_claimed_rejected_even_for_carrier(self, api):
        """PRD §3.6: "The approved indemnity may never exceed the amount
        claimed: any `approved_amount_cents` above `amount_claimed_cents` is
        rejected with `ERR_APPROVED_EXCEEDS_CLAIMED`, for TPA and carrier
        alike."

        Design: Corner/validations/approve_amount_exceeds_claimed_rejected
        """
        carrier, program, tpa, appt, policy = \
            setup_program_with_issued_policy_and_tpa()
        claim = create_claim_under_review(program, policy, tpa,
                                          occurrence_date="2026-08-05T00:00:00Z",
                                          amount_claimed_cents=80000)
        cu = make_carrier_underwriter_headers(carrier["id"])
        resp = api.approve_claim(claim["id"], {"approved_amount_cents": 90000}, cu)
        validate_error(resp, ApiErrorId.ERR_APPROVED_EXCEEDS_CLAIMED)
        assert get_claim_fresh(claim["id"])["status"] == "UNDER_REVIEW"


class TestPayment:
    def test_pay_posts_claim_payment_entry_and_zeroes_reserve(self, api):
        """PRD §3.6: "Payment posts a `CLAIM_PAYMENT` ledger entry for the
        negative approved amount with the `claim_id` set, sets the claim's
        `paid_cents` to the approved amount, stamps `paid_at`, and zeroes
        `case_reserve_cents`."

        Design: Corner/endpoints/claim_payment_posts_ledger_entry_side_effect
        """
        carrier, program, tpa, appt, policy = \
            setup_program_with_issued_policy_and_tpa()
        tpa_h = make_tpa_adjuster_headers(tpa["id"])
        claim = create_claim_under_review(program, policy, tpa,
                                          occurrence_date="2026-08-05T00:00:00Z",
                                          amount_claimed_cents=50000)
        validate_success(api.set_claim_reserve(
            claim["id"], {"case_reserve_cents": 25000}, tpa_h))
        validate_success(api.approve_claim(
            claim["id"], {"approved_amount_cents": 40000}, tpa_h))
        paid = validate_success(api.pay_claim(claim["id"], tpa_h))
        assert paid["status"] == "PAID"
        assert paid["paid_cents"] == 40000
        assert paid["case_reserve_cents"] == 0
        assert paid["paid_at"] is not None

        entries, meta = validate_paginated(
            api.list_ledger_entries(FIN, params={"claim_id": claim["id"]}))
        assert meta["total_count"] == 1
        entry = entries[0]
        assert entry["entry_type"] == "CLAIM_PAYMENT"
        assert entry["amount_cents"] == -40000
        assert entry["running_balance_cents"] == 115000
        prog = get_program_fresh(program["id"], FIN)
        assert prog["trust_balance_cents"] == 115000

    def test_pay_with_insufficient_trust_rejected(self, api):
        """PRD §3.6: "Payment ... is an adjuster action with a fiduciary
        guard: the program's `trust_balance_cents` must be at least the
        `approved_amount_cents`, failing with `ERR_TRUST_INSUFFICIENT_FUNDS` —
        fiduciary funds may never go negative."

        Design: Corner/validations/claim_pay_with_insufficient_trust_rejected
        """
        carrier, program, tpa, appt, policy = \
            setup_program_with_issued_policy_and_tpa()
        # Drain the trust via a remittance first: collected 155000 -> remit
        # 118575 (net 155000-23250=131750 >= 100000 -> 10% = 13175; remittance
        # 118575), leaving trust at 36425.
        # PRD section 4: recording a remittance creates a resource -> 201.
        validate_success(api.record_remittance(
            program["id"], {"declared_amount_cents": 118575}, FIN),
            expected_status=201)
        prog = get_program_fresh(program["id"], FIN)
        assert prog["trust_balance_cents"] == 36425

        tpa_h = make_tpa_adjuster_headers(tpa["id"])
        claim = create_claim_under_review(program, policy, tpa,
                                          occurrence_date="2026-08-05T00:00:00Z",
                                          amount_claimed_cents=60000)
        validate_success(api.approve_claim(
            claim["id"], {"approved_amount_cents": 60000}, tpa_h))
        resp = api.pay_claim(claim["id"], tpa_h)
        validate_error(resp, ApiErrorId.ERR_TRUST_INSUFFICIENT_FUNDS)
        assert get_claim_fresh(claim["id"])["status"] == "APPROVED"
        entries = list_ledger(program["id"])
        assert all(e["entry_type"] != "CLAIM_PAYMENT" for e in entries)


class TestReopenCycle:
    def test_reopen_cycle_bounded_at_two(self, api):
        """PRD §3.6: "An `MGAUnderwriter` may reopen a `DENIED` claim (`DENIED
        → REOPENED`) at most twice — a claim whose `reopened_count` has already
        reached 2 is rejected with `ERR_REOPEN_LIMIT_EXCEEDED` ... The
        deny–reopen–review loop is bounded by the two-reopen cap."

        Design: Difficulty/non_linear_state_machine/claim_reopen_cycle_bounded_count
        """
        carrier, program, tpa, appt, policy = \
            setup_program_with_issued_policy_and_tpa()
        tpa_h = make_tpa_adjuster_headers(tpa["id"])
        claim = create_claim_under_review(program, policy, tpa,
                                          occurrence_date="2026-08-10T00:00:00Z",
                                          amount_claimed_cents=80000)
        for i in (1, 2):
            validate_success(api.deny_claim(
                claim["id"], {"denial_reason": f"denial {i}"}, tpa_h))
            reopened = validate_success(api.reopen_claim(claim["id"], UW))
            assert reopened["status"] == "REOPENED"
            assert reopened["reopened_count"] == i
            resumed = validate_success(api.resume_claim_review(claim["id"], tpa_h))
            assert resumed["status"] == "UNDER_REVIEW"

        validate_success(api.deny_claim(
            claim["id"], {"denial_reason": "final"}, tpa_h))
        third = api.reopen_claim(claim["id"], UW)
        validate_error(third, ApiErrorId.ERR_REOPEN_LIMIT_EXCEEDED)
        fresh = get_claim_fresh(claim["id"])
        assert fresh["status"] == "DENIED"
        assert fresh["reopened_count"] == 2

    def test_reopen_increments_count_and_resume_returns_to_review(self, api):
        """PRD §3.6: "Each reopen increments `reopened_count`, and the
        assigned TPA then resumes review (`REOPENED → UNDER_REVIEW`), again
        requiring the assigning appointment to be `ACTIVE`
        (`ERR_APPOINTMENT_NOT_ACTIVE`)."

        Design: Difficulty/non_linear_state_machine/claim_reopen_cycle_bounded_count
        """
        carrier, program, tpa, appt, policy = \
            setup_program_with_issued_policy_and_tpa()
        tpa_h = make_tpa_adjuster_headers(tpa["id"])
        claim = create_claim_under_review(program, policy, tpa,
                                          occurrence_date="2026-08-10T00:00:00Z",
                                          amount_claimed_cents=80000)
        validate_success(api.deny_claim(
            claim["id"], {"denial_reason": "no coverage"}, tpa_h))
        reopened = validate_success(api.reopen_claim(claim["id"], UW))
        assert reopened["status"] == "REOPENED"
        assert reopened["reopened_count"] == 1
        resumed = validate_success(api.resume_claim_review(claim["id"], tpa_h))
        assert resumed["status"] == "UNDER_REVIEW"

    def test_reopen_after_ninety_days_rejected(self, api):
        """PRD §3.6: "and only within ninety days of `denied_at`, failing with
        `ERR_REOPEN_WINDOW_CLOSED` after that."

        Design: Corner/validations/reopen_after_90_day_window_rejected
        """
        carrier, program, tpa, appt, policy = \
            setup_program_with_issued_policy_and_tpa()
        tpa_h = make_tpa_adjuster_headers(tpa["id"])
        claim = create_claim_under_review(program, policy, tpa,
                                          occurrence_date="2026-08-02T00:00:00Z",
                                          amount_claimed_cents=30000)
        set_clock("2026-08-05T00:00:00Z")
        validate_success(api.deny_claim(
            claim["id"], {"denial_reason": "no coverage"}, tpa_h))

        set_clock("2026-11-10T00:00:00Z")  # 97 days after denial
        resp = api.reopen_claim(claim["id"], UW)
        validate_error(resp, ApiErrorId.ERR_REOPEN_WINDOW_CLOSED)
        fresh = get_claim_fresh(claim["id"])
        assert fresh["status"] == "DENIED"
        assert fresh["reopened_count"] == 0
