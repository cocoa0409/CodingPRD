"""Distribution pipeline: verify, schedule, pay, cascades, and the six-month
delay for specified employees.

PRD §3.6 (Distributions from Request to Payment), §3.5 (delay rule).
"""
from test_helpers import (
    TEST_USERS,
    add_member,
    advance_clock,
    create_active_plan,
    create_distribution,
    create_draft_specified_list,
    create_document_finding_payload,
    create_operational_failure_payload,
    determine_case,
    enroll_participant,
    finalize_list,
    get_account,
    get_distribution,
    get_participant,
    get_plan,
    list_ledger_entries,
    make_participant_headers,
    open_account,
    open_separation_case,
    schedule_distribution,
    setup_funded_account,
    standard_evidence,
    validate_error,
    validate_paginated,
    validate_success,
    verify_distribution,
)

PS = TEST_USERS["plan_sponsor_headers"]
BA = TEST_USERS["benefits_admin_headers"]
CO = TEST_USERS["compliance_officer_headers"]


def _setup_fixed_time_request(api, amount=40000, fixed_date="2027-06-01",
                              plan_name="Plan FT", funded=100000):
    """Funded vested account + a verified, scheduled FIXED_TIME request."""
    ctx = setup_funded_account(
        funded,
        plan_overrides={"name": plan_name, "distribution_events_allowed": ["FIXED_TIME"],
                        "vesting_cliff_years": 3},
        participant_overrides={"employee_ref": "EMP-FT"})
    overrides = {"fixed_date": fixed_date}
    if amount is not None:
        overrides["requested_amount_cents"] = amount
    request = create_distribution(ctx["account"]["id"], ctx["participant"]["id"],
                                  "FIXED_TIME", **overrides)
    ctx["request"] = verify_distribution(request["id"])
    ctx["request"] = schedule_distribution(request["id"])
    return ctx


class TestPaymentTerminalAndTiming:
    def test_distribution_pay_twice_terminal_lockdown(self, api):
        """PRD §3.6: "The request must be `PAYABLE` — a request still `SCHEDULED`
        ahead of its payment date, or in any other non-payable state, is rejected
        with `ERR_DISTRIBUTION_NOT_PAYABLE`."
        PRD §3.6: "The paying request stamps `paid_at` and settles into `PAID`."

        PAID is terminal: a second pay fails and no second DISTRIBUTION_DEBIT is
        posted.

        Design: Corner/state_machines/distribution_pay_twice_terminal_lockdown
        """
        ctx = _setup_fixed_time_request(api, plan_name="Plan PT")
        advance_clock("2027-06-01T00:00:00Z")
        paid = validate_success(api.pay_distribution(ctx["request"]["id"], BA), 200)
        assert paid["status"] == "PAID"
        assert paid["paid_at"] is not None

        again = api.pay_distribution(ctx["request"]["id"], BA)
        validate_error(again, "ERR_DISTRIBUTION_NOT_PAYABLE", expected_status=409)

        debits = [e for e in list_ledger_entries(distribution_request_id=ctx["request"]["id"])
                  if e["entry_type"] == "DISTRIBUTION_DEBIT"]
        assert len(debits) == 1, "exactly one debit posted for the single payment"
        assert debits[0]["amount_cents"] == -40000

    def test_distribution_pay_before_date_not_payable(self, api):
        """PRD §3.6: "a request still `SCHEDULED` ahead of its payment date, or
        in any other non-payable state, is rejected with
        `ERR_DISTRIBUTION_NOT_PAYABLE`."
        PRD §3.6: "The request is then `SCHEDULED`, and the clock sweep promotes
        it to `PAYABLE` once the clock date reaches the scheduled payment date."

        Pay at 2027-05-31 against a 2027-06-01 schedule fails; at exactly
        2027-06-01 the sweep flips the request to PAYABLE and pay succeeds
        (inclusive date boundary).

        Design: Corner/errors/distribution_pay_before_date_not_payable
        """
        ctx = _setup_fixed_time_request(api, plan_name="Plan PD")
        assert ctx["request"]["scheduled_payment_date"] == "2027-06-01"

        advance_clock("2027-05-31T00:00:00Z")
        early = api.pay_distribution(ctx["request"]["id"], BA)
        validate_error(early, "ERR_DISTRIBUTION_NOT_PAYABLE", expected_status=409)
        assert get_distribution(ctx["request"]["id"])["status"] == "SCHEDULED"

        advance_clock("2027-06-01T00:00:00Z")
        assert get_distribution(ctx["request"]["id"])["status"] == "PAYABLE"
        paid = validate_success(api.pay_distribution(ctx["request"]["id"], BA), 200)
        assert paid["status"] == "PAID"
        assert get_account(ctx["account"]["id"])["settled_balance_cents"] == 60000


class TestAccountCloseCascade:
    def test_payment_zero_balance_account_close_cascade(self, api):
        """PRD §3.6: "An accepted payment runs a four-link cascade. First, a
        `DISTRIBUTION_DEBIT` ledger entry is posted in `POSTED` status for the
        negated locked amount, linked back to the request. Second, the account's
        balances are recomputed by ledger replay. Third, if the settled balance
        has reached zero — with at least one distribution debit now present —
        the account closes to `CLOSED`. Fourth, that closure cancels every
        sibling distribution request of the account still sitting in
        `REQUESTED`, `EVENT_VERIFIED`, `SCHEDULED`, `PAYABLE`, or `ON_HOLD`,
        sweeping each to `CANCELLED`."

        Request A (SEPARATION, full vested) pays the account to exactly zero;
        the sibling SCHEDULED request B is force-cancelled without any API call
        touching it.

        Design: Difficulty/transitive_cascade/payment_zero_balance_account_close_cascade
        """
        ctx = setup_funded_account(
            100000,
            plan_overrides={"name": "Plan CC",
                            "distribution_events_allowed": ["SEPARATION", "FIXED_TIME"],
                            "processing_lag_days": 30, "vesting_cliff_years": 3},
            participant_overrides={"employee_ref": "EMP-CC"})
        case = open_separation_case(ctx["participant"]["id"], "2027-03-15", "TERMINATION")
        standard_evidence(case["id"])
        determine_case(case["id"], "CONFIRMED_SEPARATION")

        req_a = create_distribution(ctx["account"]["id"], ctx["participant"]["id"],
                                    "SEPARATION", separation_case_id=case["id"])
        verify_distribution(req_a["id"])
        scheduled_a = schedule_distribution(req_a["id"])
        assert scheduled_a["locked_amount_cents"] == 100000
        assert scheduled_a["scheduled_payment_date"] == "2027-04-14"

        req_b = create_distribution(ctx["account"]["id"], ctx["participant"]["id"],
                                    "FIXED_TIME", fixed_date="2028-06-01")
        verify_distribution(req_b["id"])
        scheduled_b = schedule_distribution(req_b["id"])
        assert scheduled_b["status"] == "SCHEDULED"

        advance_clock("2027-04-14T00:00:00Z")  # A PAYABLE; B still SCHEDULED
        assert get_distribution(req_b["id"])["status"] == "SCHEDULED"

        paid = validate_success(api.pay_distribution(req_a["id"], BA), 200)
        assert paid["status"] == "PAID"

        debits = [e for e in list_ledger_entries(distribution_request_id=req_a["id"])
                  if e["entry_type"] == "DISTRIBUTION_DEBIT"]
        assert len(debits) == 1 and debits[0]["amount_cents"] == -100000, "link 1"
        assert debits[0]["entry_status"] == "POSTED"

        account = get_account(ctx["account"]["id"])
        assert account["settled_balance_cents"] == 0, "link 2: replay recompute"
        assert account["status"] == "CLOSED", "link 3: zero-balance auto-close"

        assert get_distribution(req_b["id"])["status"] == "CANCELLED", (
            "link 4: sibling cascade, no API call touched B"
        )

    def test_partial_payment_leaves_account_open_and_sibling_alive(self, api):
        """PRD §3.6: "Third, if the settled balance has reached zero — with at
        least one distribution debit now present — the account closes to
        `CLOSED`."

        The same cascade condition on the negative branch: a partial payment
        that leaves a positive settled balance does not close the account and
        does not cancel the sibling request.

        Design: Difficulty/transitive_cascade/payment_zero_balance_account_close_cascade
        """
        ctx = setup_funded_account(
            100000,
            plan_overrides={"name": "Plan PP3", "distribution_events_allowed": ["FIXED_TIME"],
                            "vesting_cliff_years": 3},
            participant_overrides={"employee_ref": "EMP-PP3"})
        req_a = create_distribution(ctx["account"]["id"], ctx["participant"]["id"],
                                    "FIXED_TIME", fixed_date="2027-06-01",
                                    requested_amount_cents=40000)
        req_b = create_distribution(ctx["account"]["id"], ctx["participant"]["id"],
                                    "FIXED_TIME", fixed_date="2027-06-01",
                                    requested_amount_cents=30000)
        for req in (req_a, req_b):
            verify_distribution(req["id"])
            schedule_distribution(req["id"])

        advance_clock("2027-06-01T00:00:00Z")
        paid_a = validate_success(api.pay_distribution(req_a["id"], BA), 200)
        assert paid_a["status"] == "PAID"

        account = get_account(ctx["account"]["id"])
        assert account["settled_balance_cents"] == 60000
        assert account["status"] == "ACTIVE", "no closure while settled > 0"
        assert get_distribution(req_b["id"])["status"] == "PAYABLE", "sibling unaffected"

        paid_b = validate_success(api.pay_distribution(req_b["id"], BA), 200)
        assert paid_b["status"] == "PAID"
        account = get_account(ctx["account"]["id"])
        assert account["settled_balance_cents"] == 30000
        assert account["status"] == "ACTIVE"


class TestPayGuardsAndPriorities:
    def _setup_lapse_scenario(self, api, with_finding):
        ctx = setup_funded_account(
            100000,
            plan_overrides={"name": "Plan DL", "distribution_events_allowed": ["FIXED_TIME"],
                            "vesting_cliff_years": 3},
            participant_overrides={"employee_ref": "EMP-DL"})
        req_a = create_distribution(ctx["account"]["id"], ctx["participant"]["id"],
                                    "FIXED_TIME", fixed_date="2027-06-01")
        req_b = create_distribution(ctx["account"]["id"], ctx["participant"]["id"],
                                    "FIXED_TIME", fixed_date="2027-06-01",
                                    requested_amount_cents=40000)
        for req in (req_a, req_b):
            verify_distribution(req["id"])
            schedule_distribution(req["id"])
        advance_clock("2027-06-01T00:00:00Z")
        if with_finding:
            validate_success(api.create_document_finding(
                create_document_finding_payload(
                    ctx["plan"]["id"], description="Missing distribution timing language",
                    failure_year=2026), CO), 201)
        paid_b = validate_success(api.pay_distribution(req_b["id"], BA), 200)
        assert paid_b["status"] == "PAID"
        assert get_account(ctx["account"]["id"])["settled_balance_cents"] == 60000
        return ctx, req_a

    def test_document_lapse_beats_insufficient_balance_on_pay(self, api):
        """PRD §2.8: "Every request passes through a single ordered validation
        pipeline, and the order is observable when several violations coincide."
        Stage 8 (business safety) names "The document-compliance gate blocks
        payment while a plan's document posture is lapsed
        (`ERR_PLAN_DOCUMENT_LAPSED`)" and stage 11 (fiscal limits) names
        "`ERR_INSUFFICIENT_VESTED_BALANCE`" — fiscal limits "are enforced last".
        PRD §3.6: "the plan's `document_posture` must not be `LAPSED_FAILURE`
        (`ERR_PLAN_DOCUMENT_LAPSED`), and the account's `settled_balance_cents`
        must cover the `locked_amount_cents` (`ERR_INSUFFICIENT_VESTED_BALANCE`)."

        At pay time the plan posture is LAPSED_FAILURE AND settled 60000 <
        locked 100000; the safety gate wins.

        Design: Difficulty/priority_pair_validation_conflict/document_lapse_beats_insufficient_balance_on_pay
        """
        ctx, req_a = self._setup_lapse_scenario(api, with_finding=True)
        advance_clock("2029-01-01T00:00:00Z")  # finding (deadline 2028-12-31) lapses
        plan = get_plan(ctx["plan"]["id"])
        assert plan["document_posture"] == "LAPSED_FAILURE"

        blocked = api.pay_distribution(req_a["id"], BA)
        validate_error(blocked, "ERR_PLAN_DOCUMENT_LAPSED", expected_status=403)
        assert get_distribution(req_a["id"])["status"] == "PAYABLE", "unchanged"

    def test_insufficient_settled_balance_on_pay_isolated(self, api):
        """PRD §3.6: "the account's `settled_balance_cents` must cover the
        `locked_amount_cents` (`ERR_INSUFFICIENT_VESTED_BALANCE`)."

        The same pay call without the lapsed document: with no safety violation
        present, the fiscal guard surfaces alone (settled 60000 < locked
        100000).

        Design: Difficulty/priority_pair_validation_conflict/document_lapse_beats_insufficient_balance_on_pay
        """
        ctx, req_a = self._setup_lapse_scenario(api, with_finding=False)
        blocked = api.pay_distribution(req_a["id"], BA)
        validate_error(blocked, "ERR_INSUFFICIENT_VESTED_BALANCE", expected_status=402)
        assert get_distribution(req_a["id"])["status"] == "PAYABLE", "unchanged"


class TestCreationAndVerifyGuards:
    def test_emergency_exceeds_need_at_verify_rejected(self, api):
        """PRD §3.6: "An `UNFORESEEABLE_EMERGENCY` request verifies only while
        its `requested_amount_cents` does not exceed its `emergency_need_cents`,
        else `ERR_EXCEEDS_EMERGENCY_NEED`."

        Design: Corner/validations/emergency_exceeds_need_at_verify_rejected
        """
        ctx = setup_funded_account(
            100000,
            plan_overrides={"name": "Plan EM",
                            "distribution_events_allowed": ["UNFORESEEABLE_EMERGENCY"],
                            "vesting_cliff_years": 3},
            participant_overrides={"employee_ref": "EMP-EM"})
        request = create_distribution(ctx["account"]["id"], ctx["participant"]["id"],
                                      "UNFORESEEABLE_EMERGENCY",
                                      requested_amount_cents=60000,
                                      emergency_need_cents=50000)
        blocked = api.verify_distribution_event(request["id"], CO)
        validate_error(blocked, "ERR_EXCEEDS_EMERGENCY_NEED", expected_status=402)
        assert get_distribution(request["id"])["status"] == "REQUESTED"

    def test_request_over_vested_rejected(self, api):
        """PRD §3.6: "`requested_amount_cents` is optional for a partial
        distribution — omitting it requests the full vested balance — but it is
        required for `UNFORESEEABLE_EMERGENCY`, must be strictly positive
        whenever present, and may not exceed the account's
        `vested_balance_cents` (`ERR_INSUFFICIENT_VESTED_BALANCE`)."

        100001 > 100000 vested fails at creation; no row is created.

        Design: Corner/validations/request_over_vested_rejected
        """
        ctx = setup_funded_account(
            100000,
            plan_overrides={"name": "Plan RV", "distribution_events_allowed": ["FIXED_TIME"],
                            "vesting_cliff_years": 3},
            participant_overrides={"employee_ref": "EMP-RV"})
        blocked = api.create_distribution_request({
            "account_id": ctx["account"]["id"], "event_type": "FIXED_TIME",
            "fixed_date": "2027-06-01", "requested_amount_cents": 100001,
        }, make_participant_headers(ctx["participant"]["id"]))
        validate_error(blocked, "ERR_INSUFFICIENT_VESTED_BALANCE", expected_status=402)

        _, meta = validate_paginated(api.list_distribution_requests(
            BA, params={"account_id": ctx["account"]["id"]}))
        assert meta["total_count"] == 0

    def test_event_type_not_permitted_rejected(self, api):
        """PRD §3.6: "The request names the `account_id` and an `event_type`,
        which must be among the plan's permitted `distribution_events_allowed`
        (`ERR_EVENT_TYPE_NOT_PERMITTED`)".

        Design: Corner/validations/event_type_not_permitted_rejected
        """
        plan = create_active_plan(name="Plan ET", distribution_events_allowed=["SEPARATION"])
        participant = enroll_participant(plan["id"], employee_ref="EMP-ET")
        account = open_account(participant["id"], plan["id"])

        blocked = api.create_distribution_request({
            "account_id": account["id"], "event_type": "UNFORESEEABLE_EMERGENCY",
            "requested_amount_cents": 1000, "emergency_need_cents": 5000,
        }, make_participant_headers(participant["id"]))
        validate_error(blocked, "ERR_EVENT_TYPE_NOT_PERMITTED", expected_status=409)

    def test_fixed_time_requires_future_fixed_date(self, api):
        """PRD §3.6: "A `FIXED_TIME` request must carry a `fixed_date` that falls
        after the creation clock date (`ERR_INVALID_DATE_RANGE`), null for other
        types".
        PRD §2.8: "The request body must contain all required fields with
        matching types, valid enum members, parseable date strings, and — for
        any date-range input — a start that falls before its end. Violations
        surface as `ERR_INVALID_REQUEST` or `ERR_INVALID_DATE_RANGE`."

        At the startup clock 2026-08-01: a missing fixed_date fails
        well-formedness; a fixed_date of 2026-07-01 is not after the clock date.

        Design: Corner/validations/fixed_time_requires_future_fixed_date
        """
        plan = create_active_plan(name="Plan FT2", distribution_events_allowed=["FIXED_TIME"])
        participant = enroll_participant(plan["id"], employee_ref="EMP-FT2")
        account = open_account(participant["id"], plan["id"])

        missing = api.create_distribution_request(
            {"account_id": account["id"], "event_type": "FIXED_TIME"},
            make_participant_headers(participant["id"]))
        validate_error(missing, "ERR_INVALID_REQUEST", expected_status=400)

        past = api.create_distribution_request(
            {"account_id": account["id"], "event_type": "FIXED_TIME",
             "fixed_date": "2026-07-01"},
            make_participant_headers(participant["id"]))
        validate_error(past, "ERR_INVALID_DATE_RANGE", expected_status=400)


class TestSixMonthDelay:
    def _setup_separated_specified_scenario(self, api, six_month_delay_enabled):
        ctx = setup_funded_account(
            100000,
            plan_overrides={"name": "Plan SD",
                            "distribution_events_allowed": ["SEPARATION", "FIXED_TIME"],
                            "six_month_delay_enabled": six_month_delay_enabled,
                            "processing_lag_days": 30, "vesting_cliff_years": 3},
            participant_overrides={"employee_ref": "EMP-SD"})
        case = open_separation_case(ctx["participant"]["id"], "2027-03-15", "TERMINATION")
        standard_evidence(case["id"])
        determine_case(case["id"], "CONFIRMED_SEPARATION")
        ctx["case"] = case
        return ctx

    def test_six_month_delay_nested_max_scheduling(self, api):
        """PRD §3.5: "for `SEPARATION`, the alleged separation date from the
        linked case plus the plan's `processing_lag_days`".
        PRD §3.5: "On top of the base date sits the six-month delay, which
        applies exactly when three conditions coincide: the event type is
        `SEPARATION`, the plan's `six_month_delay_enabled` is set, and the
        participant is a specified employee at schedule time. When it applies,
        a delay floor is computed as the separation date plus six calendar
        months, keeping the same day of month and clamping to the end of the
        month when the target month is shorter; payment exactly on the floor
        date is permitted, just never before it. The `scheduled_payment_date`
        is then the later of the base date and the delay floor — and simply the
        base date when the delay does not apply."
        PRD §3.5: "for each participant whose flag flips from false to true,
        every `SCHEDULED` distribution request of theirs with event type
        `SEPARATION` under a plan whose `six_month_delay_enabled` is set has its
        `scheduled_payment_date` recomputed under the delay rule".

        Same separation (2027-03-15, lag 30): not-specified yields
        max(2027-04-14, -) = 2027-04-14; after a FIVE_PERCENT_OWNER list
        finalizes, the nested max selects 2027-09-15.

        Design: Difficulty/combinatorial_formula/six_month_delay_nested_max_scheduling
        """
        ctx = self._setup_separated_specified_scenario(api, six_month_delay_enabled=True)

        req_a = create_distribution(ctx["account"]["id"], ctx["participant"]["id"],
                                    "SEPARATION", separation_case_id=ctx["case"]["id"])
        verify_distribution(req_a["id"])
        sched_a = schedule_distribution(req_a["id"])
        assert sched_a["scheduled_payment_date"] == "2027-04-14", (
            "base = separation 2027-03-15 + 30 lag days; delay inapplicable while "
            "not specified"
        )
        assert sched_a["locked_amount_cents"] == 100000, (
            "full vested balance when requested_amount_cents omitted"
        )

        lst = create_draft_specified_list(ctx["plan"]["id"],
                                          identification_date="2027-01-01",
                                          effective_date="2027-04-01")
        add_member(lst["id"], ctx["participant"]["id"], "FIVE_PERCENT_OWNER", 30000000)
        finalize_list(lst["id"])
        assert get_participant(ctx["participant"]["id"])["is_specified_employee"] is True

        after = get_distribution(req_a["id"])
        assert after["scheduled_payment_date"] == "2027-09-15", (
            "finalize cascade recomputed max(base, separation+6 calendar months)"
        )

        req_b = create_distribution(ctx["account"]["id"], ctx["participant"]["id"],
                                    "SEPARATION", separation_case_id=ctx["case"]["id"],
                                    requested_amount_cents=50000)
        verify_distribution(req_b["id"])
        sched_b = schedule_distribution(req_b["id"])
        assert sched_b["scheduled_payment_date"] == "2027-09-15", (
            "nested max selects the six-month delay floor for a specified employee"
        )

    def test_six_month_delay_disabled_plan_ignores_specified_status(self, api):
        """PRD §3.5: "On top of the base date sits the six-month delay, which
        applies exactly when three conditions coincide: the event type is
        `SEPARATION`, the plan's `six_month_delay_enabled` is set, and the
        participant is a specified employee at schedule time."
        PRD §3.5: "The `scheduled_payment_date` is then the later of the base
        date and the delay floor — and simply the base date when the delay does
        not apply."

        With the plan flag disabled, even a specified employee's separation
        distribution lands on the base date 2027-04-14.

        Design: Difficulty/combinatorial_formula/six_month_delay_nested_max_scheduling
        """
        ctx = self._setup_separated_specified_scenario(api, six_month_delay_enabled=False)

        lst = create_draft_specified_list(ctx["plan"]["id"],
                                          identification_date="2027-01-01",
                                          effective_date="2027-04-01")
        add_member(lst["id"], ctx["participant"]["id"], "FIVE_PERCENT_OWNER", 30000000)
        finalize_list(lst["id"])
        assert get_participant(ctx["participant"]["id"])["is_specified_employee"] is True

        request = create_distribution(ctx["account"]["id"], ctx["participant"]["id"],
                                      "SEPARATION", separation_case_id=ctx["case"]["id"])
        verify_distribution(request["id"])
        scheduled = schedule_distribution(request["id"])
        assert scheduled["scheduled_payment_date"] == "2027-04-14", (
            "delay requires the plan flag; base date applies"
        )
