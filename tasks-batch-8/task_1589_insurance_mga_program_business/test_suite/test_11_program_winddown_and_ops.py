"""Program wind-down: termination gates (bordereaux, trust, in-force
policies, open claims), the capacity-release endpoint, and termination
cascades onto guidelines and tranches."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    bind_policy,
    collect_premium,
    create_active_appointment,
    create_allocation_payload,
    create_carrier,
    create_issued_policy,
    create_program,
    create_program_payload,
    create_tpa,
    get_policy_fresh,
    get_program_fresh,
    issue_policy,
    make_carrier_underwriter_headers,
    make_tpa_adjuster_headers,
    quote_policy,
    report_claim,
    run_daily,
    set_clock,
    setup_active_program,
    setup_program_with_issued_policy_and_tpa,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["platform_admin_headers"]
UW = TEST_USERS["mga_underwriter_headers"]
FIN = TEST_USERS["mga_finance_headers"]


class TestTerminationGates:
    def test_terminate_blocked_by_submitted_bordereau_then_succeeds(self, api):
        """PRD §3.8: "Termination (`RUN_OFF → TERMINATED`) is the final
        accounting ... it is permitted only when ... no bordereau remains in
        `DRAFT`, `SUBMITTED`, or `REJECTED` (`ERR_UNACCEPTED_BORDEREAUX`)"
        and "Termination marks every guideline of the program `INACTIVE`,
        releases the non-terminal tranche to `RELEASED`, and records the
        `termination_reason`." PRD §3.7: "Acceptance (`SUBMITTED → ACCEPTED`)
        marks the underlying records as reported: on a `PREMIUM` bordereau
        each referenced policy's `reported_premium_bordereau_id` is set to
        the accepting bordereau."

        Design: Difficulty/cross_entity_state_dependency/program_terminate_requires_bordereaux_settled
        """
        carrier, program, guideline, allocation, _f = setup_active_program()
        # Issue then flat-cancel the only policy: full refund returns trust to 0.
        policy = create_issued_policy(program, insured_name="Term Co")
        validate_success(api.cancel_policy(
            policy["id"], {"cancellation_date": "2026-08-01T00:00:00Z",
                           "reason": "CARRIER_REQUEST"}, UW))
        run_daily()
        assert get_policy_fresh(policy["id"])["status"] == "CANCELLED"
        assert get_program_fresh(program["id"])["trust_balance_cents"] == 0

        cu = make_carrier_underwriter_headers(carrier["id"])
        validate_success(api.enter_runoff_program(program["id"], cu))
        bor = validate_success(api.create_bordereau(program["id"], {
            "bordereau_type": "PREMIUM", "period_label": "2026-08",
            "due_date": "2026-09-15T00:00:00Z",
            "rows": [{"policy_id": policy["id"], "written_premium_cents": 155000,
                      "commission_cents": 23250}],
            "declared_totals": {"premium_cents": 155000,
                                "commission_cents": 23250}}, FIN),
            expected_status=201)
        validate_success(api.submit_bordereau(bor["id"], FIN))

        blocked = api.terminate_program(
            program["id"], {"termination_reason": "wind-down blocked test"}, cu)
        validate_error(blocked, ApiErrorId.ERR_UNACCEPTED_BORDEREAUX)
        assert get_program_fresh(program["id"])["status"] == "RUN_OFF"

        validate_success(api.accept_bordereau(bor["id"], cu))
        terminated = validate_success(api.terminate_program(
            program["id"], {"termination_reason": "wind-down complete"}, cu))
        assert terminated["status"] == "TERMINATED"
        assert terminated["termination_reason"] == "wind-down complete"

        g_fresh = validate_success(api.get_guideline(guideline["id"], UW))
        assert g_fresh["status"] == "INACTIVE"
        a_fresh = validate_success(api.get_allocation(allocation["id"], cu))
        assert a_fresh["status"] == "RELEASED"
        assert get_policy_fresh(policy["id"])["reported_premium_bordereau_id"] == bor["id"]

    def test_draft_bordereau_also_blocks_termination(self, api):
        """PRD §3.8: "it is permitted only when ... no bordereau remains in
        `DRAFT`, `SUBMITTED`, or `REJECTED` (`ERR_UNACCEPTED_BORDEREAUX`)" —
        the gate covers a never-submitted `DRAFT` bordereau too, not just a
        submitted one.

        Design: Difficulty/cross_entity_state_dependency/program_terminate_requires_bordereaux_settled
        """
        carrier, program, _g, _a, _f = setup_active_program()
        cu = make_carrier_underwriter_headers(carrier["id"])
        validate_success(api.enter_runoff_program(program["id"], cu))
        validate_success(api.create_bordereau(program["id"], {
            "bordereau_type": "PREMIUM", "period_label": "2026-08",
            "due_date": "2026-09-15T00:00:00Z"}, FIN), expected_status=201)

        resp = api.terminate_program(
            program["id"], {"termination_reason": "draft blocks"}, cu)
        validate_error(resp, ApiErrorId.ERR_UNACCEPTED_BORDEREAUX)
        assert get_program_fresh(program["id"])["status"] == "RUN_OFF"

    def test_terminate_blocked_by_nonzero_trust(self, api):
        """PRD §3.8: "it is permitted only when no policy of the program
        remains in `QUOTED`, `BOUND`, `ISSUED`, or `PENDING_CANCELLATION`
        (`ERR_PROGRAM_HAS_ACTIVE_POLICIES`), no claim remains in `REPORTED`,
        `UNDER_REVIEW`, `REFERRED`, `APPROVED`, or `REOPENED`
        (`ERR_OPEN_CLAIMS_EXIST`), no bordereau remains in `DRAFT`,
        `SUBMITTED`, or `REJECTED` (`ERR_UNACCEPTED_BORDEREAUX`), and the
        trust balance is exactly zero (`ERR_TRUST_NOT_ZERO`)."

        Design: Corner/validations/terminate_with_nonzero_trust_rejected
        """
        carrier, program, _g, _a, _f = setup_active_program()
        policy = create_issued_policy(program, insured_name="Trust Left")
        # Let the policy expire: fully earned, no refund, trust retains 155000.
        set_clock("2027-08-02T00:00:00Z")
        run_daily()
        assert get_policy_fresh(policy["id"])["status"] == "EXPIRED"

        cu = make_carrier_underwriter_headers(carrier["id"])
        validate_success(api.enter_runoff_program(program["id"], cu))
        resp = api.terminate_program(
            program["id"], {"termination_reason": "wind-down"}, cu)
        validate_error(resp, ApiErrorId.ERR_TRUST_NOT_ZERO)
        assert get_program_fresh(program["id"])["status"] == "RUN_OFF"

    def test_terminate_blocked_by_in_force_policy_then_succeeds(self, api):
        """PRD §3.8: "it is permitted only when no policy of the program
        remains in `QUOTED`, `BOUND`, `ISSUED`, or `PENDING_CANCELLATION`
        (`ERR_PROGRAM_HAS_ACTIVE_POLICIES`)."

        Design: Corner/validations/terminate_with_in_force_policy_rejected
        """
        carrier, program, _g, _a, _f = setup_active_program()
        policy = quote_policy(program, insured_name="In Force")
        policy = bind_policy(policy)  # never collected -> trust stays 0
        cu = make_carrier_underwriter_headers(carrier["id"])
        validate_success(api.enter_runoff_program(program["id"], cu))

        blocked = api.terminate_program(
            program["id"], {"termination_reason": "blocked"}, cu)
        validate_error(blocked, ApiErrorId.ERR_PROGRAM_HAS_ACTIVE_POLICIES)

        # Flat-cancel the bound policy and process it: now termination clears.
        validate_success(api.cancel_policy(
            policy["id"], {"cancellation_date": "2026-08-01T00:00:00Z",
                           "reason": "CARRIER_REQUEST"}, UW))
        run_daily()
        assert get_policy_fresh(policy["id"])["status"] == "CANCELLED"
        ok = validate_success(api.terminate_program(
            program["id"], {"termination_reason": "clean"}, cu))
        assert ok["status"] == "TERMINATED"

    def test_terminate_blocked_by_open_tail_claim(self, api):
        """PRD §3.8: "it is permitted only when ... no claim remains in
        `REPORTED`, `UNDER_REVIEW`, `REFERRED`, `APPROVED`, or `REOPENED`
        (`ERR_OPEN_CLAIMS_EXIST`)."

        Design: Corner/validations/terminate_with_open_claim_rejected
        """
        carrier, program, tpa, appt, policy = \
            setup_program_with_issued_policy_and_tpa()
        # Flat-cancel + run-daily: policy CANCELLED, trust fully refunded to 0.
        validate_success(api.cancel_policy(
            policy["id"], {"cancellation_date": "2026-08-01T00:00:00Z",
                           "reason": "CARRIER_REQUEST"}, UW))
        set_clock("2026-08-05T00:00:00Z")
        run_daily()
        assert get_policy_fresh(policy["id"])["status"] == "CANCELLED"
        assert get_program_fresh(program["id"])["trust_balance_cents"] == 0

        cu = make_carrier_underwriter_headers(carrier["id"])
        validate_success(api.enter_runoff_program(program["id"], cu))
        # Tail claim on the cancelled policy, occurrence inside the term.
        claim = report_claim(policy, occurrence_date="2026-08-01T00:00:00Z",
                             amount_claimed_cents=30000)
        assert claim["status"] == "REPORTED"

        resp = api.terminate_program(
            program["id"], {"termination_reason": "blocked by tail claim"}, cu)
        validate_error(resp, ApiErrorId.ERR_OPEN_CLAIMS_EXIST)
        assert get_program_fresh(program["id"])["status"] == "RUN_OFF"


class TestCapacityReleaseEndpoint:
    def test_release_is_terminal(self, api):
        """PRD §3.2: "The carrier may instead release a non-terminal tranche
        outright, moving it to `RELEASED` and freeing the unconsumed
        remainder." PRD §2.11: "An entity in a terminal state rejects every
        further transition with `ERR_INVALID_STATE` (HTTP 409)."

        Design: Corner/endpoints/capacity_release_endpoint_terminal
        """
        carrier = create_carrier()
        program = create_program(carrier)
        cu = make_carrier_underwriter_headers(carrier["id"])
        current = get_program_fresh(program["id"], cu)
        alloc = validate_success(api.create_capacity_allocation(
            program["id"],
            create_allocation_payload(current["version"], allocated_cents=300000),
            cu), expected_status=201)

        released = validate_success(api.release_allocation(alloc["id"], cu))
        assert released["status"] == "RELEASED"
        again = api.release_allocation(alloc["id"], cu)
        validate_error(again, ApiErrorId.ERR_INVALID_STATE)
