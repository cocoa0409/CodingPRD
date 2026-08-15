"""Plan change requests: proration, deferred execution, OCC, and the add/drop
window."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    advance_term_week,
    create_and_publish_plan,
    create_holder,
    create_verified_card,
    create_term,
    enroll_holder,
    fund_account,
    get_success_data,
    make_cardholder_headers,
    open_account,
    open_term,
    post_pos_transaction,
    request_plan_change,
    set_clock,
    setup_open_enrollment,
    validate_error,
    validate_paginated,
    validate_success,
)

DINING = TEST_USERS["dining_manager_headers"]
BURSAR = TEST_USERS["bursar_headers"]
ADMIN = TEST_USERS["card_office_admin_headers"]


class TestChangeApprovalGuards:
    def test_change_approval_at_final_week_rejected(self, api):
        """PRD §3.4: "the term's `current_week_index` plus 1 must not exceed
        `total_weeks` (`ERR_PLAN_CHANGE_EFFECTIVE_WEEK_INVALID`)"

        Design: Corner/state_machines/change_approval_at_final_week_rejected
        """
        set_clock("2026-08-24T09:00:00Z")
        term = create_term(term_code="T-2W", end_date="2026-09-06T23:59:59Z",
                           add_drop_deadline="2026-09-05T23:59:59Z",
                           total_weeks=2)
        pa = create_and_publish_plan(plan_code="P-2WA",
                                     eligible_holder_types=["STUDENT_COMMUTER"])
        pb = create_and_publish_plan(plan_code="P-2WB", weekly_swipe_allowance=10,
                                     dining_dollar_allocation_cents=20000,
                                     price_cents=120000,
                                     eligible_holder_types=["STUDENT_COMMUTER"])
        open_term(term["id"])
        holder = create_holder(university_id="U90014", full_name="Nora Week",
                               email="nora@x.edu")
        enrollment = enroll_holder(holder["id"], pa["id"], term["id"])
        advance_term_week(term["id"])  # week 2 of 2
        request = request_plan_change(enrollment, pb["id"])
        assert request["status"] == "SUBMITTED"

        resp = api.approve_change_request(request["id"], DINING)
        validate_error(resp, ApiErrorId.ERR_PLAN_CHANGE_EFFECTIVE_WEEK_INVALID)
        still = get_success_data(api.get_change_request(request["id"], DINING))
        assert still["status"] == "SUBMITTED"

    def test_second_pending_change_request_rejected(self, api):
        """PRD §3.4: "no other change request in `SUBMITTED` or `APPROVED` may
        exist on the enrollment (`ERR_PENDING_CHANGE_EXISTS`)"
        PRD §3.4: "Submitting a change request is itself a mutation of the
        enrollment and bumps its `version`"

        Design: Corner/validations/second_pending_change_request_rejected
        """
        set_clock("2026-08-24T09:00:00Z")
        holder, term, pa, enrollment = setup_open_enrollment(
            {"term_code": "T-PCX"},
            {"plan_code": "P-PCX-A",
             "eligible_holder_types": ["STUDENT_COMMUTER"]},
            {"university_id": "U92005", "full_name": "Ora Pending",
             "email": "ora@x.edu"})
        pb = create_and_publish_plan(plan_code="P-PCX-B", weekly_swipe_allowance=10,
                                     dining_dollar_allocation_cents=20000,
                                     price_cents=120000,
                                     eligible_holder_types=["STUDENT_COMMUTER"])
        request_plan_change(enrollment, pb["id"])

        fresh = get_success_data(api.get_enrollment(enrollment["id"], DINING))
        resp = api.create_change_request(
            enrollment["id"],
            {"new_plan_id": pb["id"],
             "expected_enrollment_version": fresh["version"]},
            make_cardholder_headers(holder["id"]))
        validate_error(resp, ApiErrorId.ERR_PENDING_CHANGE_EXISTS)


class TestChangeRequestOCC:
    def test_occ_change_request_stale_after_swipe(self, api):
        """PRD §2.9: "Requesting a meal plan change against an enrollment requires
        the request body to carry `expected_enrollment_version`, the enrollment
        `version` the client last observed. If the enrollment's current `version`
        has advanced past that value — for example because a swipe purchase in the
        meantime bumped it — the request is rejected with `ERR_STALE_VERSION`
        (HTTP 412), since the proration basis the client saw is stale and the
        request must be re-based on a fresh read."

        Design: Corner/complexity_layers/occ_change_request_stale_after_swipe
        """
        set_clock("2026-08-24T09:00:00Z")
        holder, term, pa, enrollment = setup_open_enrollment(
            {"term_code": "T-OCC"},
            {"plan_code": "P-OCC-A",
             "eligible_holder_types": ["STUDENT_COMMUTER"]},
            {"university_id": "U95001", "full_name": "Eli Occ",
             "email": "elio@x.edu"})
        pb = create_and_publish_plan(plan_code="P-OCC-B", weekly_swipe_allowance=10,
                                     dining_dollar_allocation_cents=20000,
                                     price_cents=120000,
                                     eligible_holder_types=["STUDENT_COMMUTER"])
        card = create_verified_card(holder["id"])
        stale_version = enrollment["version"]
        post_pos_transaction(card["id"], "MEAL_SWIPE", 0)

        stale = api.create_change_request(
            enrollment["id"],
            {"new_plan_id": pb["id"],
             "expected_enrollment_version": stale_version},
            make_cardholder_headers(holder["id"]))
        validate_error(stale, ApiErrorId.ERR_STALE_VERSION)

        fresh = get_success_data(api.get_enrollment(enrollment["id"], DINING))
        assert fresh["version"] == stale_version + 1
        ok = api.create_change_request(
            enrollment["id"],
            {"new_plan_id": pb["id"],
             "expected_enrollment_version": fresh["version"]},
            make_cardholder_headers(holder["id"]))
        created = validate_success(ok, 201)
        assert created["status"] == "SUBMITTED"


class TestDeferredExecution:
    def test_deferred_change_execution_voids_on_insufficient_funds(self, api):
        """PRD §3.4: "Execution of each request re-checks its preconditions: the
        parent enrollment must still be `ACTIVE`, and when the stored
        `charge_delta_cents` is positive, the holder's `CAMPUS_CASH` `balance_cents`
        must cover it. ... On a failed precondition the request becomes `VOID`
        instead — `void_reason` `ENROLLMENT_CANCELLED` when the enrollment is no
        longer active, `INSUFFICIENT_FUNDS` when the balance cannot cover a
        positive delta — the old enrollment remains in its prior state, and no
        ledger entries are posted."

        Design: Corner/complexity_layers/deferred_change_execution_voids_on_insufficient_funds
        """
        set_clock("2026-08-24T09:00:00Z")
        term = create_term(term_code="T-VOID")
        p5 = create_and_publish_plan(
            plan_code="COMM5-V",
            eligible_holder_types=["STUDENT_RESIDENT", "STUDENT_COMMUTER"])
        pu = create_and_publish_plan(
            plan_code="RESUNL-V", weekly_swipe_allowance=0, is_unlimited_swipes=True,
            dining_dollar_allocation_cents=25000, price_cents=220000,
            requires_on_campus_housing=True,
            eligible_holder_types=["STUDENT_RESIDENT"])
        open_term(term["id"])
        holder = create_holder(university_id="U95004", full_name="Hip Void",
                               email="hip@x.edu", holder_type="STUDENT_RESIDENT",
                               housing_status="ON_CAMPUS")
        enrollment = enroll_holder(holder["id"], p5["id"], term["id"])
        advance_term_week(term["id"])  # week 2

        request = request_plan_change(enrollment, pu["id"])
        approved = validate_success(
            api.approve_change_request(request["id"], DINING), 200)
        # W = 3: old_earned = round(90000*2/16) = 11250; credit = 78750;
        # new_due = round(220000*14/16) = 192500; delta = 113750.
        assert approved["charge_delta_cents"] == 113750
        assert approved["effective_week_index"] == 3
        assert approved["status"] == "APPROVED"
        mid = get_success_data(api.get_enrollment(enrollment["id"], DINING))
        assert mid["status"] == "ACTIVE"

        advance_term_week(term["id"])  # week 3: execution sweep runs
        after = get_success_data(api.get_change_request(request["id"], DINING))
        assert after["status"] == "VOID"
        assert after["void_reason"] == "INSUFFICIENT_FUNDS"
        old = get_success_data(api.get_enrollment(enrollment["id"], DINING))
        assert old["status"] == "ACTIVE"
        successors, _ = validate_paginated(
            api.list_enrollments(DINING,
                                 {"supersedes_enrollment_id": enrollment["id"]}))
        assert successors == []

    def test_cancel_enrollment_voids_approved_change_request(self, api):
        """PRD §3.4: "Any change request in `SUBMITTED` or `APPROVED` on the
        enrollment is voided with `void_reason` `ENROLLMENT_CANCELLED`."
        PRD §3.4: "Cancelling an `ACTIVE` enrollment computes a cancellation
        credit: the consumed measure is, under `WEEKLY`, the term's
        `current_week_index` minus the enrollment's `enrolled_week_index`, never
        below zero (the current week is not charged)"

        Design: Corner/state_machines/cancel_enrollment_voids_approved_change_request
        """
        set_clock("2026-08-24T09:00:00Z")
        holder, term, pa, enrollment = setup_open_enrollment(
            {"term_code": "T-CVC"},
            {"plan_code": "P-CVC-A",
             "eligible_holder_types": ["STUDENT_COMMUTER"]},
            {"university_id": "U96002", "full_name": "Lin Void",
             "email": "lin@x.edu"})
        pb = create_and_publish_plan(plan_code="P-CVC-B", weekly_swipe_allowance=10,
                                     dining_dollar_allocation_cents=20000,
                                     price_cents=120000,
                                     eligible_holder_types=["STUDENT_COMMUTER"])
        advance_term_week(term["id"])  # week 2
        request = request_plan_change(enrollment, pb["id"])
        validate_success(api.approve_change_request(request["id"], DINING), 200)

        cancelled = validate_success(api.cancel_enrollment(enrollment["id"], DINING),
                                     200)
        assert cancelled["status"] == "CANCELLED"
        # Cancel at week 2, enrolled week 1: earned = round(90000*1/16) = 5625.
        assert cancelled["credit_cents"] == 84375

        after = get_success_data(api.get_change_request(request["id"], DINING))
        assert after["status"] == "VOID"
        assert after["void_reason"] == "ENROLLMENT_CANCELLED"

        advance_term_week(term["id"])
        successors, _ = validate_paginated(
            api.list_enrollments(DINING,
                                 {"supersedes_enrollment_id": enrollment["id"]}))
        assert successors == []


class TestProrationValues:
    def test_daily_mode_plan_change_values(self, api):
        """PRD §3.4: "under `DAILY`, the old plan's `price_cents` multiplied by
        the calendar days elapsed since `start_date` and divided by the term's
        total days, rounded half-up" and "5. `funding_delta_cents`: under
        `WEEKLY`, the new plan's `dining_dollar_allocation_cents` multiplied by T
        minus W plus 1 and divided by T, rounded half-up; under `DAILY`, that
        allocation multiplied by the remaining days and divided by the total days,
        rounded half-up."

        Design: Corner/calculations/daily_mode_plan_change_values
        """
        set_clock("2026-08-24T09:00:00Z")
        term = create_term(term_code="T-DPC", proration_mode="DAILY")
        p5 = create_and_publish_plan(
            plan_code="COMM5-D",
            eligible_holder_types=["STUDENT_RESIDENT", "STUDENT_COMMUTER"])
        pu = create_and_publish_plan(
            plan_code="RESUNL-D", weekly_swipe_allowance=0, is_unlimited_swipes=True,
            dining_dollar_allocation_cents=25000, price_cents=220000,
            requires_on_campus_housing=True,
            eligible_holder_types=["STUDENT_RESIDENT"])
        open_term(term["id"])
        holder = create_holder(university_id="U91011", full_name="Dee Daily",
                               email="dee2@x.edu", holder_type="STUDENT_RESIDENT",
                               housing_status="ON_CAMPUS")
        enrollment = enroll_holder(holder["id"], p5["id"], term["id"])
        advance_term_week(term["id"])
        advance_term_week(term["id"])
        set_clock("2026-09-09T10:00:00Z")

        request = request_plan_change(enrollment, pu["id"])
        approved = validate_success(
            api.approve_change_request(request["id"], DINING), 200)
        # DAILY (112 total days, 16 consumed):
        # old_earned = round(90000*16/112) = 12857; credit = 90000-12857 = 77143
        # new_due = round(220000*96/112) = 188571; delta = 111428
        # funding = round(25000*96/112) = 21429
        assert approved["charge_delta_cents"] == 111428
        assert approved["funding_delta_cents"] == 21429

    def test_plan_change_proration_deltas_at_approval(self, api):
        """PRD §3.4: "The proration follows a mandatory five-step order that breaks
        the apparent circle between the credit from the old plan and the charge
        owed on the new plan." — "4. `charge_delta_cents` is the new due minus the
        credit from the old plan — a signed value."
        PRD §3.4: "then sets `effective_week_index` to `current_week_index` plus 1,
        computes and stores `charge_delta_cents` and `funding_delta_cents` (both
        null until the request is `APPROVED`), records `decided_by`, and defers all
        money movement to week advancement."

        Design: Difficulty/combinatorial_formula/plan_change_proration_pinned_evaluation_order
        """
        ids = _setup_weekly_plan_change(api)
        approved = validate_success(
            api.approve_change_request(ids["cr_id"], DINING), 200)
        # W=4, T=16: old_earned = round(90000*3/16) = 16875;
        # credit = 90000-16875 = 73125; new_due = round(220000*13/16) = 178750;
        # delta = 178750-73125 = 105625; funding = round(25000*13/16) = 20313.
        assert approved["charge_delta_cents"] == 105625
        assert approved["funding_delta_cents"] == 20313
        assert approved["effective_week_index"] == 4
        assert approved["decided_by"] == "dining-mgr-1"

    def test_plan_change_execution_posts_deltas_and_supersedes(self, api):
        """PRD §3.4: "On success, the old enrollment becomes `SUPERSEDED` with
        `credit_cents` set to its `charge_cents` minus the old plan's earned
        amount; a successor enrollment is created `ACTIVE` with
        `supersedes_enrollment_id` pointing at the old enrollment, the new plan,
        `enrolled_week_index` equal to the `effective_week_index`,
        `swipes_used_this_week` at 0 (post-reset), and `charge_cents` equal to the
        new due amount; a positive delta posts a `PRORATION_DEBIT` to the holder's
        `CAMPUS_CASH` (auto-created `OPEN` when absent), a negative delta posts a
        `PRORATION_CREDIT` of its magnitude, and a zero delta posts nothing; a
        positive `funding_delta_cents` posts an `ALLOCATION_GRANT` to the term
        `DINING_DOLLARS` account; and the request becomes `EXECUTED`."

        Design: Difficulty/combinatorial_formula/plan_change_proration_pinned_evaluation_order
        """
        ids = _setup_weekly_plan_change(api)
        validate_success(api.approve_change_request(ids["cr_id"], DINING), 200)
        advance_term_week(ids["term_id"])  # week 4: executes the request

        request = get_success_data(api.get_change_request(ids["cr_id"], DINING))
        assert request["status"] == "EXECUTED"

        old = get_success_data(api.get_enrollment(ids["enr_id"], DINING))
        assert old["status"] == "SUPERSEDED"
        assert old["credit_cents"] == 73125

        successors, _ = validate_paginated(
            api.list_enrollments(DINING,
                                 {"supersedes_enrollment_id": ids["enr_id"]}))
        assert len(successors) == 1
        assert successors[0]["status"] == "ACTIVE"
        assert successors[0]["charge_cents"] == 178750
        assert successors[0]["plan_id"] == ids["pu_id"]

        cash = get_success_data(api.get_account(ids["cash_id"], BURSAR))
        assert cash["balance_cents"] == 94375  # 200000 - 105625 PRORATION_DEBIT

        dining_accounts, _ = validate_paginated(
            api.list_accounts(BURSAR, {"holder_id": ids["h_id"],
                                       "term_id": ids["term_id"]}))
        assert dining_accounts[0]["balance_cents"] == 30313  # 10000 + 20313


class TestAddDropDeadlineBoundary:
    def test_plan_change_deadline_boundary_second_precision(self, api):
        """PRD §3.4: "the term must be `OPEN` and the clock must read on or before
        the term's `add_drop_deadline` (`ERR_PLAN_CHANGE_WINDOW_CLOSED`)"

        Design: Difficulty/boundary_precision_check/plan_change_deadline_boundary_second_precision
        """
        ids = _setup_deadline_scenario(api)
        set_clock("2026-09-06T23:59:59Z")
        resp = api.create_change_request(
            ids["ea_id"],
            {"new_plan_id": ids["p10_id"],
             "expected_enrollment_version": ids["ea_v"]},
            make_cardholder_headers(ids["ha_id"]))
        created = validate_success(resp, 201)
        assert created["status"] == "SUBMITTED"

    def test_plan_change_one_second_past_deadline_rejected(self, api):
        """PRD §3.4: "the term must be `OPEN` and the clock must read on or before
        the term's `add_drop_deadline` (`ERR_PLAN_CHANGE_WINDOW_CLOSED`)"

        Design: Difficulty/boundary_precision_check/plan_change_deadline_boundary_second_precision
        """
        ids = _setup_deadline_scenario(api)
        set_clock("2026-09-07T00:00:00Z")
        resp = api.create_change_request(
            ids["eb_id"],
            {"new_plan_id": ids["p10_id"],
             "expected_enrollment_version": ids["eb_v"]},
            make_cardholder_headers(ids["hb_id"]))
        validate_error(resp, ApiErrorId.ERR_PLAN_CHANGE_WINDOW_CLOSED)


class TestFraudHoldPrecedence:
    def test_fraud_hold_beats_plan_change_window(self, api):
        """PRD §2.10: "When a request violates several rules at once, the error
        that surfaces is determined by a fixed priority order, evaluated from first
        to last" — item 11 "suspended or fraud-flagged holders blocked from
        value-extending actions (`ERR_FRAUD_HOLD`, 409)" precedes item 12 "plan
        changes requested or approved on or before the add/drop deadline
        (`ERR_PLAN_CHANGE_WINDOW_CLOSED`)".

        Design: Difficulty/priority_pair_validation_conflict/fraud_hold_beats_plan_change_window
        """
        ids = _setup_fraud_hold_scenario(api)
        resp = api.create_change_request(
            ids["enr_id"],
            {"new_plan_id": ids["p10_id"],
             "expected_enrollment_version": ids["enr_v"]},
            make_cardholder_headers(ids["h_id"]))
        validate_error(resp, ApiErrorId.ERR_FRAUD_HOLD)

    def test_fraud_hold_rejection_persists_no_change_request(self, api):
        """PRD §3.4: "The new request starts `SUBMITTED` with `requested_by` set
        to the holder's `X-User-ID`, and an enrollment's change requests can be
        listed" — a rejected request is never created.
        PRD §2.10: "suspended or fraud-flagged holders blocked from value-extending
        actions (`ERR_FRAUD_HOLD`, 409)".

        Design: Difficulty/priority_pair_validation_conflict/fraud_hold_beats_plan_change_window
        """
        ids = _setup_fraud_hold_scenario(api)
        api.create_change_request(
            ids["enr_id"],
            {"new_plan_id": ids["p10_id"],
             "expected_enrollment_version": ids["enr_v"]},
            make_cardholder_headers(ids["h_id"]))
        requests, _ = validate_paginated(
            api.list_enrollment_change_requests(ids["enr_id"], DINING))
        assert requests == []


# ---------------------------------------------------------------------------
# Local helpers
# ---------------------------------------------------------------------------

def _setup_weekly_plan_change(api):
    """FALLPC (WEEKLY) OPEN; COMM5-PC and RESUNL-PC published; holder enrolled in
    COMM5-PC since week 1 (charge 90000, dining grant 10000); term advanced to
    week 3; clock 2026-09-09T10:00; CAMPUS_CASH funded 200000; SUBMITTED change
    request to RESUNL-PC."""
    set_clock("2026-08-24T09:00:00Z")
    term = create_term(term_code="FALLPC")
    p5 = create_and_publish_plan(
        plan_code="COMM5-PC",
        eligible_holder_types=["STUDENT_COMMUTER", "STUDENT_RESIDENT"])
    pu = create_and_publish_plan(
        plan_code="RESUNL-PC", weekly_swipe_allowance=0, is_unlimited_swipes=True,
        dining_dollar_allocation_cents=25000, price_cents=220000,
        requires_on_campus_housing=True,
        eligible_holder_types=["STUDENT_RESIDENT"])
    open_term(term["id"])
    holder = create_holder(university_id="U3003", full_name="Eli Resident",
                           email="eli@x.edu", holder_type="STUDENT_RESIDENT",
                           housing_status="ON_CAMPUS")
    enrollment = enroll_holder(holder["id"], p5["id"], term["id"])
    advance_term_week(term["id"])
    advance_term_week(term["id"])
    set_clock("2026-09-09T10:00:00Z")
    cash = open_account(holder["id"], "CAMPUS_CASH")
    fund_account(cash["id"], 200000)
    request = request_plan_change(enrollment, pu["id"])
    return {"term_id": term["id"], "h_id": holder["id"], "enr_id": enrollment["id"],
            "cr_id": request["id"], "cash_id": cash["id"], "pu_id": pu["id"]}


def _setup_deadline_scenario(api):
    """FALLWB OPEN since week 1 with add_drop_deadline 2026-09-06T23:59:59Z;
    holders UA and UB each with an ACTIVE COMM5-WB enrollment."""
    set_clock("2026-08-24T09:00:00Z")
    term = create_term(term_code="FALLWB",
                       add_drop_deadline="2026-09-06T23:59:59Z")
    p5 = create_and_publish_plan(plan_code="COMM5-WB",
                                 eligible_holder_types=["STUDENT_COMMUTER"])
    p10 = create_and_publish_plan(plan_code="COMM10-WB", weekly_swipe_allowance=10,
                                  dining_dollar_allocation_cents=20000,
                                  price_cents=120000,
                                  eligible_holder_types=["STUDENT_COMMUTER"])
    open_term(term["id"])
    ha = create_holder(university_id="U7002", full_name="Nia A", email="nia@x.edu")
    hb = create_holder(university_id="U7003", full_name="Oli B", email="oli@x.edu")
    ea = enroll_holder(ha["id"], p5["id"], term["id"])
    eb = enroll_holder(hb["id"], p5["id"], term["id"])
    return {"term_id": term["id"], "p10_id": p10["id"], "ha_id": ha["id"],
            "hb_id": hb["id"], "ea_id": ea["id"], "eb_id": eb["id"],
            "ea_v": ea["version"], "eb_v": eb["version"]}


def _setup_fraud_hold_scenario(api):
    """FALLFH (add_drop 2026-09-06) OPEN since week 1; holder with ACTIVE COMM5-FH
    enrollment, then manually suspended; clock moved past the deadline."""
    set_clock("2026-08-24T09:00:00Z")
    term = create_term(term_code="FALLFH",
                       add_drop_deadline="2026-09-06T23:59:59Z")
    p5 = create_and_publish_plan(plan_code="COMM5-FH",
                                 eligible_holder_types=["STUDENT_COMMUTER"])
    p10 = create_and_publish_plan(plan_code="COMM10-FH", weekly_swipe_allowance=10,
                                  dining_dollar_allocation_cents=20000,
                                  price_cents=120000,
                                  eligible_holder_types=["STUDENT_COMMUTER"])
    open_term(term["id"])
    holder = create_holder(university_id="U6002", full_name="Lee Commuter",
                           email="lee@x.edu")
    enrollment = enroll_holder(holder["id"], p5["id"], term["id"])
    get_success_data(api.suspend_card_holder(holder["id"], ADMIN))
    set_clock("2026-09-07T00:00:00Z")
    return {"enr_id": enrollment["id"], "enr_v": enrollment["version"],
            "p10_id": p10["id"], "h_id": holder["id"]}
