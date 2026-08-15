"""Assignments: creation defaults and guards, the published-plan dependency,
the half-open window rule, and termination's credit compensation."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assert_plan_assignment,
    book_transaction,
    create_assignment,
    create_rep,
    get_assignment,
    get_only_credit_entry,
    publish_plan,
    setup_assignment,
    setup_program_with_plan,
    terminate_assignment,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["comp_admin_headers"]


class TestAssignmentCreation:
    def test_assignment_creation_defaults(self, api):
        """PRD §3.3: "`draw_amount_cents_per_period` — default 0, never
        negative — is paid each closed period while the assignment remains
        `ACTIVE`. `draw_recoverable` — default true — decides whether paid
        draws accrue as debt into `draw_outstanding_cents` for later recovery
        out of gross payout, or are simply paid and never accrued.
        `guarantee_amount_cents_per_period` — default 0, never negative — sets
        a minimum net payable floor per closed period, with 0 meaning no
        guarantee."
        PRD §3.3: "The lifecycle dimension, `status`, begins at `ACTIVE` and
        ends at `TERMINATED`. The document dimension, `acceptance_status`,
        begins at `OFFERED` and moves among `OFFERED`, `ACCEPTED`, and
        `DECLINED`; the assignment's `accepted_document_version` — null until
        the first acceptance — records which plan `document_version` the rep
        last accepted."

        Design: Corner/entities/assignment_creation_defaults
        """
        sc = setup_program_with_plan(program_name="Prog AD", plan_name="Plan AD")
        rep = create_rep(sc["program"]["id"], "Rep AD", "AD-R1")
        resp = api.create_assignment(
            {"program_id": sc["program"]["id"], "rep_id": rep["id"],
             "plan_id": sc["plan"]["id"], "quota_cents": 1000000,
             "effective_start_date": "2026-01-01"},
            ADMIN)
        assignment = validate_success(resp, 201)
        assert_plan_assignment(assignment)
        assert assignment["draw_amount_cents_per_period"] == 0
        assert assignment["draw_recoverable"] is True
        assert assignment["guarantee_amount_cents_per_period"] == 0
        assert assignment["status"] == "ACTIVE"
        assert assignment["acceptance_status"] == "OFFERED"
        assert assignment["draw_outstanding_cents"] == 0
        assert assignment.get("accepted_document_version") is None

    def test_assignment_quota_zero_rejected(self, api):
        """PRD §3.3: "and the quota must be positive (`ERR_QUOTA_INVALID`)."

        Design: Corner/validations/assignment_quota_zero_returns_400
        """
        sc = setup_program_with_plan(program_name="Prog QZ", plan_name="Plan QZ")
        rep = create_rep(sc["program"]["id"], "Rep QZ", "QZ-R1")
        resp = api.create_assignment(
            {"program_id": sc["program"]["id"], "rep_id": rep["id"],
             "plan_id": sc["plan"]["id"], "quota_cents": 0,
             "effective_start_date": "2026-01-01"},
            ADMIN)
        validate_error(resp, ApiErrorId.ERR_QUOTA_INVALID, 400)

    def test_assignment_create_on_draft_plan_rejected(self, api):
        """PRD §3.3: "The checks fire in the ladder order of §2.9: the plan
        must be `PUBLISHED` (`ERR_PLAN_NOT_PUBLISHED`); the rep's assignment
        windows must not collide — each assignment occupies a half-open
        interval in which the start date counts and the end date does not, a
        null `effective_end_date` means open-ended, the end when present must
        fall after the start (`ERR_INVALID_REQUEST`), and any intersection with
        another non-`TERMINATED` assignment of the same rep is rejected with
        `ERR_ASSIGNMENT_WINDOW_OVERLAP` (mere adjacency, one window's end equal
        to the other's start, is allowed); and the quota must be positive
        (`ERR_QUOTA_INVALID`)."

        Design: Difficulty/cross_entity_state_dependency/assignment_creation_requires_published_plan
        """
        sc = setup_program_with_plan(program_name="Prog XDep",
                                     plan_name="Plan X", publish=False)
        rep = create_rep(sc["program"]["id"], "Rep X", "X-R1")

        resp = api.create_assignment(
            {"program_id": sc["program"]["id"], "rep_id": rep["id"],
             "plan_id": sc["plan"]["id"], "quota_cents": 1000000,
             "effective_start_date": "2026-01-01"},
            ADMIN)
        validate_error(resp, ApiErrorId.ERR_PLAN_NOT_PUBLISHED, 409)
        data, _meta = validate_paginated(
            api.list_assignments(ADMIN, params={"rep_id": rep["id"]}))
        assert data == [], "no assignment may be created against a DRAFT plan"

    def test_assignment_create_after_plan_publish_succeeds(self, api):
        """PRD §3.1: "Only `PUBLISHED` plans can receive assignments."

        Design: Difficulty/cross_entity_state_dependency/assignment_creation_requires_published_plan
        """
        sc = setup_program_with_plan(program_name="Prog XDep2",
                                     plan_name="Plan X2", publish=False)
        rep = create_rep(sc["program"]["id"], "Rep X2", "X2-R1")

        blocked = api.create_assignment(
            {"program_id": sc["program"]["id"], "rep_id": rep["id"],
             "plan_id": sc["plan"]["id"], "quota_cents": 1000000,
             "effective_start_date": "2026-01-01"},
            ADMIN)
        validate_error(blocked, ApiErrorId.ERR_PLAN_NOT_PUBLISHED, 409)

        publish_plan(sc["plan"]["id"])
        ok = api.create_assignment(
            {"program_id": sc["program"]["id"], "rep_id": rep["id"],
             "plan_id": sc["plan"]["id"], "quota_cents": 1000000,
             "effective_start_date": "2026-01-01"},
            ADMIN)
        assignment = validate_success(ok, 201)
        assert assignment["status"] == "ACTIVE"
        assert assignment["acceptance_status"] == "OFFERED"


class TestAssignmentWindowHalfOpen:
    def test_assignment_window_adjacency_allowed(self, api):
        """PRD §3.3: "the rep's assignment windows must not collide — each
        assignment occupies a half-open interval in which the start date counts
        and the end date does not, a null `effective_end_date` means
        open-ended, the end when present must fall after the start
        (`ERR_INVALID_REQUEST`), and any intersection with another
        non-`TERMINATED` assignment of the same rep is rejected with
        `ERR_ASSIGNMENT_WINDOW_OVERLAP` (mere adjacency, one window's end equal
        to the other's start, is allowed)"

        Design: Difficulty/resource_temporal_overlap/assignment_window_half_open_adjacency
        """
        sc = setup_program_with_plan(program_name="Prog Aw", plan_name="Plan AW")
        rep = create_rep(sc["program"]["id"], "Rep AW", "AW-R1")
        create_assignment(sc["program"]["id"], rep["id"], sc["plan"]["id"],
                          quota_cents=1000000,
                          effective_start_date="2026-01-01",
                          effective_end_date="2026-06-30")

        # Adjacent: the new start EQUALS the previous (exclusive) end.
        resp = api.create_assignment(
            {"program_id": sc["program"]["id"], "rep_id": rep["id"],
             "plan_id": sc["plan"]["id"], "quota_cents": 900000,
             "effective_start_date": "2026-06-30"},
            ADMIN)
        adjacent = validate_success(resp, 201)
        assert adjacent["status"] == "ACTIVE"

    def test_assignment_window_mid_overlap_rejected(self, api):
        """PRD §3.3: "the rep's assignment windows must not collide — each
        assignment occupies a half-open interval in which the start date counts
        and the end date does not, a null `effective_end_date` means
        open-ended, the end when present must fall after the start
        (`ERR_INVALID_REQUEST`), and any intersection with another
        non-`TERMINATED` assignment of the same rep is rejected with
        `ERR_ASSIGNMENT_WINDOW_OVERLAP` (mere adjacency, one window's end equal
        to the other's start, is allowed)"

        Design: Difficulty/resource_temporal_overlap/assignment_window_half_open_adjacency
        """
        sc = setup_program_with_plan(program_name="Prog Aw2",
                                     plan_name="Plan AW2")
        rep = create_rep(sc["program"]["id"], "Rep AW2", "AW2-R1")
        create_assignment(sc["program"]["id"], rep["id"], sc["plan"]["id"],
                          quota_cents=1000000,
                          effective_start_date="2026-01-01",
                          effective_end_date="2026-06-30")
        create_assignment(sc["program"]["id"], rep["id"], sc["plan"]["id"],
                          quota_cents=900000,
                          effective_start_date="2026-06-30")  # open-ended

        resp = api.create_assignment(
            {"program_id": sc["program"]["id"], "rep_id": rep["id"],
             "plan_id": sc["plan"]["id"], "quota_cents": 800000,
             "effective_start_date": "2026-06-15",
             "effective_end_date": "2026-08-01"},
            ADMIN)
        validate_error(resp, ApiErrorId.ERR_ASSIGNMENT_WINDOW_OVERLAP, 409)


class TestTerminationCompensation:
    def test_terminate_reverses_pending_and_posted_credits(self, api):
        """PRD §3.3: "Termination unwinds the open period: every `PENDING`
        credit of the assignment is `REVERSED`, every `POSTED` credit whose
        `posted_period_index` is the program's current open period is likewise
        `REVERSED` with `current_period_earned_cents` decremented by each
        entry's amount as compensation — while credits already `LOCKED` by an
        earlier period close survive termination untouched."

        Design: Corner/state_machines/assignment_terminate_reverses_pending_and_posted_credits
        """
        sc = setup_program_with_plan(program_name="Prog TC", plan_name="Plan TC")
        rep_a = create_rep(sc["program"]["id"], "Rep TCA", "TC-RA")
        rep_b = create_rep(sc["program"]["id"], "Rep TCB", "TC-RB")
        asg_a = setup_assignment(sc["program"], sc["plan"], rep_a)  # OFFERED
        asg_b = setup_assignment(sc["program"], sc["plan"], rep_b, accept=True)

        txn_a = book_transaction(sc["program"]["id"], "TC-TA", 50000,
                                 [{"rep_id": rep_a["id"], "split_bps": 10000}])
        txn_b = book_transaction(sc["program"]["id"], "TC-TB", 70000,
                                 [{"rep_id": rep_b["id"], "split_bps": 10000}])
        credit_a = get_only_credit_entry(transaction_id=txn_a["id"])
        credit_b = get_only_credit_entry(transaction_id=txn_b["id"])
        assert credit_a["status"] == "PENDING"
        assert credit_b["status"] == "POSTED"
        assert get_assignment(asg_b["id"])["current_period_earned_cents"] == 70000

        terminated_a = terminate_assignment(asg_a["id"])
        assert terminated_a["status"] == "TERMINATED"
        terminated_b = terminate_assignment(asg_b["id"])
        assert terminated_b["status"] == "TERMINATED"

        assert get_only_credit_entry(transaction_id=txn_a["id"])["status"] == "REVERSED"
        assert get_only_credit_entry(transaction_id=txn_b["id"])["status"] == "REVERSED"
        assert get_assignment(asg_b["id"])["current_period_earned_cents"] == 0, (
            "the same-period POSTED reversal compensates the earned counter"
        )
