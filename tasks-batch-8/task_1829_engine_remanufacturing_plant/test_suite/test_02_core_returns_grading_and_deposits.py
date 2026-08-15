"""Core returns: provisional/final credit, dispute cycle, linked-deposit
close, aging sweep, and gatekeeping on the return endpoints."""
from test_helpers import (
    NON_EXISTENT_UUID,
    TEST_USERS,
    ApiErrorId,
    assert_core_deposit,
    assert_core_return,
    build_user_headers,
    create_active_spec,
    create_core_return_payload,
    create_distributor,
    create_graded_return,
    create_received_return,
    get_core_return,
    get_deposit,
    get_distributor,
    grade_core_return,
    grade_return_payload,
    make_distributor_headers,
    produce_sealed_engine,
    respond_grading_payload,
    respond_to_grading,
    run_aging_sweep,
    sell_engine_to,
    set_logical_clock,
    validate_error,
    validate_paginated,
)

ADMIN = TEST_USERS["plant_admin_headers"]
INSPECTOR = TEST_USERS["core_inspector_headers"]


class TestCoreCreditCalculation:
    def test_provisional_credit_assumes_perfect_core_at_receipt(self, api):
        """PRD §3.3: "At receipt the system posts an optimistic estimate into
        `provisional_credit_cents`: the spec's `core_base_credit_cents`
        multiplied by 1.00 — the provisional variant assumes a perfect
        `GRADE_A` core with no missing components, because inspection has not
        yet happened — rounded half-up to whole cents."
        PRD §3.3: "The base component is the spec's `core_base_credit_cents`
        multiplied by the grade multiplier — 1.00 for `GRADE_A`, 0.60 for
        `GRADE_B`, 0.30 for `GRADE_C`, and 0.00 for `REJECT` — with the
        product rounded half-up to whole cents."

        Design: Difficulty/dual_variant_calc/core_credit_provisional_vs_final
        """
        set_logical_clock()
        distributor = create_distributor(distributor_code="D-100",
                                         name="Midwest Parts",
                                         volume_discount_pct=0.15)
        spec = create_active_spec(application_code="C1500-1996")

        ret = create_received_return(distributor, spec)
        assert_core_return(ret)
        assert ret["status"] == "RECEIVED"
        assert ret["grade"] is None
        assert ret["final_credit_cents"] is None
        assert ret["provisional_credit_cents"] == 100000, (
            "provisional variant: 100000 x 1.00 with zero deductions")

        graded = grade_core_return(ret["id"], "GRADE_B", ["CAMSHAFT"])
        # final variant: 60000 - round_half_up(33335 x 0.60) = 60000 - 20001
        assert graded["final_credit_cents"] == 39999
        assert graded["final_credit_cents"] != ret["provisional_credit_cents"], (
            "the two variants must diverge whenever grade != GRADE_A or "
            "components are missing")

    def test_final_credit_posts_to_distributor_ledger(self, api):
        """PRD §3.3: "Grading fans out into two chains. First, the credit
        chain: the distributor's `credit_balance_cents` increases by
        `final_credit_cents`."
        PRD §3.3: "Grading is performed by a `CoreInspector` and moves the
        return from `RECEIVED` to `GRADED`."

        Design: Difficulty/dual_variant_calc/core_credit_provisional_vs_final
        """
        set_logical_clock()
        distributor = create_distributor(distributor_code="D-100",
                                         name="Midwest Parts",
                                         volume_discount_pct=0.15)
        spec = create_active_spec(application_code="C1500-1996")
        ret = create_received_return(distributor, spec)

        graded = grade_core_return(ret["id"], "GRADE_B", ["CAMSHAFT"])
        assert graded["status"] == "GRADED"
        assert graded["final_credit_cents"] == 39999

        after = get_distributor(distributor["id"])
        assert after["credit_balance_cents"] == 39999, (
            "credit chain: balance increases by final_credit_cents")
        assert after["deposits_held_cents"] == 0

    def test_per_line_deduction_rounding_pins_value(self, api):
        """PRD §3.3: "Each entry in `missing_components`, processed in the
        order listed in the request, contributes a deduction line: a per-part
        deduction amount multiplied by the same grade multiplier, with each
        line rounded half-up to whole cents before any summing takes place."
        PRD §3.3: "The deduction lines are then summed — only after each has
        been individually rounded; the system never multiplies the unrounded
        aggregate and rounds once at the end — and the final credit is the
        base component minus the total deductions, floored at zero."

        Design: Difficulty/combinatorial_formula/core_credit_per_line_deduction_rounding
        """
        set_logical_clock()
        distributor = create_distributor(distributor_code="D-200",
                                         name="Parts House")
        spec = create_active_spec(application_code="K2500-1997")
        ret = create_received_return(distributor, spec)

        graded = grade_core_return(ret["id"], "GRADE_C",
                                   ["CAMSHAFT", "CYLINDER_HEAD"])
        # Per-line: 30000 - round(33335x0.30) - round(25005x0.30)
        #         = 30000 - 10001 - 7502 = 12497
        assert graded["status"] == "GRADED"
        assert graded["final_credit_cents"] == 12497, (
            f"per-line rounding yields 12497, got "
            f"{graded['final_credit_cents']}")

    def test_per_line_deduction_rounding_posts_exact_credit(self, api):
        """PRD §3.3: "The per-part deduction amounts are 40000 cents for a
        `CRANKSHAFT`, 25005 cents for a `CYLINDER_HEAD`, 50000 cents for an
        `ENGINE_BLOCK`, and 33335 cents for a `CAMSHAFT`."
        PRD §3.3: "First, the credit chain: the distributor's
        `credit_balance_cents` increases by `final_credit_cents`."

        Design: Difficulty/combinatorial_formula/core_credit_per_line_deduction_rounding
        """
        set_logical_clock()
        distributor = create_distributor(distributor_code="D-200",
                                         name="Parts House")
        spec = create_active_spec(application_code="K2500-1997")
        ret = create_received_return(distributor, spec)

        graded = grade_core_return(ret["id"], "GRADE_C",
                                   ["CAMSHAFT", "CYLINDER_HEAD"])
        assert graded["final_credit_cents"] == 12497
        assert graded["final_credit_cents"] != 12498, (
            "12498 is the value the forbidden sum-then-round order produces")

        after = get_distributor(distributor["id"])
        assert after["credit_balance_cents"] == 12497, (
            "the ledger must post the per-line-rounded figure exactly")


class TestDisputeRegradeCycle:
    def test_dispute_suspends_posted_credit(self, api):
        """PRD §3.3: "Dispute moves it from `GRADED` to `DISPUTED`, increments
        `dispute_count` by 1, and pulls the just-posted credit back out of
        `credit_balance_cents` — the credit sits in suspense while the dispute
        is open."

        Design: Difficulty/non_linear_state_machine/core_return_dispute_regrade_cycle
        """
        set_logical_clock()
        distributor = create_distributor(distributor_code="D-300",
                                         name="Cycle Parts")
        spec = create_active_spec(application_code="S10-1994")
        ret = create_received_return(distributor, spec)

        graded = grade_core_return(ret["id"], "GRADE_B", [])
        assert graded["final_credit_cents"] == 60000  # 100000 x 0.60
        assert get_distributor(distributor["id"])["credit_balance_cents"] == 60000

        disputed = respond_to_grading(ret, distributor, "DISPUTE")
        assert disputed["status"] == "DISPUTED"
        assert disputed["dispute_count"] == 1
        assert get_distributor(distributor["id"])["credit_balance_cents"] == 0, (
            "dispute suspends the credit while it is open")

    def test_regrade_reposts_new_credit_then_accept_closes(self, api):
        """PRD §3.3: "A disputed return can be graded again: the same grading
        capability moves it from `DISPUTED` back to `GRADED`, recomputing
        `final_credit_cents` from the new `grade` and `missing_components` and
        re-stamping `graded_at`."
        PRD §3.3: "Acceptance moves the return from `GRADED` to `CLOSED`, the
        terminal state, with no further ledger effect."

        Design: Difficulty/non_linear_state_machine/core_return_dispute_regrade_cycle
        """
        set_logical_clock()
        distributor = create_distributor(distributor_code="D-300",
                                         name="Cycle Parts")
        spec = create_active_spec(application_code="S10-1994")
        ret = create_received_return(distributor, spec)
        grade_core_return(ret["id"], "GRADE_B", [])
        respond_to_grading(ret, distributor, "DISPUTE")

        regraded = grade_core_return(ret["id"], "GRADE_A", [])
        assert regraded["status"] == "GRADED"
        assert regraded["final_credit_cents"] == 100000
        assert get_distributor(distributor["id"])["credit_balance_cents"] == 100000, (
            "re-grade re-posts the new credit (net +40000 vs the first "
            "grading after the dispute suspension)")

        closed = respond_to_grading(ret, distributor, "ACCEPT")
        assert closed["status"] == "CLOSED"
        assert get_distributor(distributor["id"])["credit_balance_cents"] == 100000


def _setup_linked_return_at_age(api, close_clock):
    """D-G buys an engine at the default clock (deposit HELD 200000), then
    registers a return linked to that deposit; the logical clock is advanced
    to close_clock. Returns (distributor, deposit, return)."""
    set_logical_clock()
    core_source = create_distributor(distributor_code="D-SRC2",
                                     name="Core Source 2")
    buyer = create_distributor(distributor_code="D-G", name="Grading Buyer",
                               credit_limit_cents=2000000)
    spec = create_active_spec(application_code="CAPRICE-1995")
    produce_sealed_engine(spec, core_source, slot=0)
    sale = sell_engine_to(buyer, spec)
    ret = create_received_return(buyer, spec,
                                 core_deposit_id=sale["deposit"]["id"])
    set_logical_clock(close_clock)
    return buyer, sale["deposit"], ret


class TestGradeClosesLinkedDeposit:
    def test_grade_closes_deposit_at_eighty_percent(self, api):
        """PRD §3.3: "Second, when the return carries a non-null
        `core_deposit_id`, the deposit chain: the linked deposit closes in the
        same transaction per the aging-bracket refund rules of §3.4 — moving
        to `CLOSED_REFUNDED` when its bracket percentage is positive, or to
        `FORFEITED` when the bracket percentage is zero".
        PRD §3.4: "an age of more than 30 but at most 60 days refunds 80%".

        Design: Difficulty/transitive_cascade/grade_closes_linked_deposit_chain
        """
        buyer, deposit, ret = _setup_linked_return_at_age(
            api, "2026-09-10T00:00:00Z")  # day 40 -> 80% bracket

        graded = grade_core_return(ret["id"], "GRADE_A", [])
        assert graded["final_credit_cents"] == 100000

        closed = get_deposit(deposit["id"])
        assert_core_deposit(closed)
        assert closed["status"] == "CLOSED_REFUNDED"
        assert closed["age_days_at_close"] == 40
        assert closed["refunded_cents"] == 160000   # 200000 x 0.80
        assert closed["forfeited_cents"] == 40000
        assert closed["closed_at"] is not None

    def test_grade_close_cascade_reconciles_ledger(self, api):
        """PRD §3.3: "and the distributor's `deposits_held_cents` falls by the
        deposit's `amount_cents` while `credit_balance_cents` rises by the
        `refunded_cents`."
        PRD §3.4: "Every close cascades to the distributor ledger:
        `deposits_held_cents` decreases by the deposit's `amount_cents`, and —
        on the refund path only — `credit_balance_cents` increases by the
        `refunded_cents`."

        Design: Difficulty/transitive_cascade/grade_closes_linked_deposit_chain
        """
        buyer, deposit, ret = _setup_linked_return_at_age(
            api, "2026-09-10T00:00:00Z")
        assert get_distributor(buyer["id"])["deposits_held_cents"] == 200000

        grade_core_return(ret["id"], "GRADE_A", [])

        after = get_distributor(buyer["id"])
        assert after["deposits_held_cents"] == 0, "deposit released by the close"
        # core credit 100000 + refund 160000
        assert after["credit_balance_cents"] == 260000


def _setup_two_linked_deposits(api):
    """D-X buys two engines at the default clock; returns (buyer, dep1, ret1,
    dep2, ret2) with both returns RECEIVED and linked."""
    set_logical_clock()
    core_source = create_distributor(distributor_code="D-SRC4",
                                     name="Core Source 4")
    buyer = create_distributor(distributor_code="D-X", name="Boundary Buyer",
                               credit_limit_cents=2000000)
    spec = create_active_spec(application_code="CORVETTE-1996")
    produce_sealed_engine(spec, core_source, slot=0)
    produce_sealed_engine(spec, core_source, slot=1)
    sale1 = sell_engine_to(buyer, spec)
    sale2 = sell_engine_to(buyer, spec)
    ret1 = create_received_return(buyer, spec,
                                  core_deposit_id=sale1["deposit"]["id"])
    ret2 = create_received_return(buyer, spec,
                                  core_deposit_id=sale2["deposit"]["id"])
    return buyer, sale1["deposit"], ret1, sale2["deposit"], ret2


class TestDepositRefundBoundary:
    def test_deposit_refund_day30_full_refund(self, api):
        """PRD §3.4: "The brackets have inclusive upper bounds: an age of at
        most 30 days refunds 100% of the deposit; an age of more than 30 but
        at most 60 days refunds 80%; an age of more than 60 but at most 90
        days refunds 50%; an age of 91 days or more refunds nothing, and the
        deposit is forfeited."
        PRD §3.4: "Exactly 30 days therefore yields a full refund".

        Design: Difficulty/boundary_precision_check/deposit_refund_day30_vs_day31_boundary
        """
        buyer, dep1, ret1, dep2, ret2 = _setup_two_linked_deposits(api)
        set_logical_clock("2026-08-31T00:00:00Z")  # exactly 30 days after sale

        grade_core_return(ret1["id"], "GRADE_A", [])

        closed = get_deposit(dep1["id"])
        assert closed["status"] == "CLOSED_REFUNDED"
        assert closed["age_days_at_close"] == 30
        assert closed["refunded_cents"] == 200000, (
            "inclusive boundary: exactly 30 days refunds 100%")
        assert closed["forfeited_cents"] == 0

    def test_deposit_refund_day31_eighty_percent(self, api):
        """PRD §3.4: "an age of more than 30 but at most 60 days refunds 80%".
        PRD §3.4: "Every close cascades to the distributor ledger:
        `deposits_held_cents` decreases by the deposit's `amount_cents`, and —
        on the refund path only — `credit_balance_cents` increases by the
        `refunded_cents`."

        Design: Difficulty/boundary_precision_check/deposit_refund_day30_vs_day31_boundary
        """
        buyer, dep1, ret1, dep2, ret2 = _setup_two_linked_deposits(api)
        set_logical_clock("2026-08-31T00:00:00Z")
        grade_core_return(ret1["id"], "GRADE_A", [])
        set_logical_clock("2026-09-01T00:00:00Z")  # day 31 for the second

        grade_core_return(ret2["id"], "GRADE_A", [])

        closed2 = get_deposit(dep2["id"])
        assert closed2["status"] == "CLOSED_REFUNDED"
        assert closed2["age_days_at_close"] == 31
        assert closed2["refunded_cents"] == 160000  # 200000 x 0.80
        assert closed2["forfeited_cents"] == 40000

        after = get_distributor(buyer["id"])
        assert after["deposits_held_cents"] == 0
        # two GRADE_A credits (2 x 100000) + refunds 200000 + 160000
        assert after["credit_balance_cents"] == 560000


class TestAgingSweep:
    def test_aging_run_sweeps_only_expired_held_deposits(self, api):
        """PRD §3.10: "A `PlantAdmin` triggers the aging sweep, an ops-run
        checkpoint that selects exactly the deposits still in `HELD` status
        whose age — whole days from `sold_at` to the current logical clock —
        exceeds 90 days, processes them in `sold_at` ascending order with
        `created_at` ascending as the tie-break, and forfeits each one".
        PRD §3.10: "The sweep reports how many deposits it forfeited and their
        identifiers — a response carrying `forfeited_count` and
        `forfeited_deposit_ids`."

        Design: Corner/calculations/aging_run_sweeps_only_expired_held_deposits
        """
        set_logical_clock()
        core_source = create_distributor(distributor_code="D-SRC6",
                                         name="Core Source 6")
        buyer = create_distributor(distributor_code="D-Z", name="Sweep Buyer",
                                   credit_limit_cents=2000000)
        spec = create_active_spec(application_code="C1500-1994")
        produce_sealed_engine(spec, core_source, slot=0)
        sale_old = sell_engine_to(buyer, spec)          # sold 2026-08-01
        produce_sealed_engine(spec, core_source, slot=1)
        set_logical_clock("2026-09-30T00:00:00Z")
        sale_young = sell_engine_to(buyer, spec)        # sold 2026-09-30

        set_logical_clock("2026-11-01T00:00:00Z")
        result = run_aging_sweep()
        assert result["forfeited_count"] == 1
        assert result["forfeited_deposit_ids"] == [sale_old["deposit"]["id"]]

        old = get_deposit(sale_old["deposit"]["id"])
        assert_core_deposit(old)
        assert old["status"] == "FORFEITED"
        assert old["age_days_at_close"] == 92
        assert old["refunded_cents"] == 0
        assert old["forfeited_cents"] == 200000

        young = get_deposit(sale_young["deposit"]["id"])
        assert young["status"] == "HELD", "32-day deposit must be excluded"

        after = get_distributor(buyer["id"])
        assert after["deposits_held_cents"] == 200000, (
            "only the forfeited 200000 leaves the held total")
        assert after["credit_balance_cents"] == 0, "forfeiture posts no credit"


class TestCoreReturnGatekeeping:
    def test_create_return_missing_required_beats_not_found(self, api):
        """PRD §2.8: "Existence checks never precede authentication and body
        well-formedness: missing or malformed headers yield
        `ERR_UNAUTHENTICATED` first, then role authorization, then request-body
        well-formedness (`ERR_VALIDATION`, HTTP 400 — required fields present,
        no undeclared fields, enum values within their declared sets, types
        correct, numeric ranges respected, `scheduled_end` strictly after
        `scheduled_start`, `ended_at` strictly after `started_at`), and only
        then existence."

        Design: Corner/validations/create_return_missing_required_beats_not_found
        """
        resp = api.create_core_return(
            {"distributor_id": NON_EXISTENT_UUID},
            build_user_headers(NON_EXISTENT_UUID, "Distributor"))
        validate_error(resp, ApiErrorId.ERR_VALIDATION)

    def test_deposit_link_from_other_distributor_rejected(self, api):
        """PRD §3.3: "When a `core_deposit_id` is supplied, it must name a
        deposit still in `HELD` status and owned by the returning distributor;
        anything else is rejected with `ERR_DEPOSIT_NOT_LINKABLE` (HTTP 422)."

        Design: Corner/validations/deposit_link_from_other_distributor_rejected
        """
        set_logical_clock()
        core_source = create_distributor(distributor_code="D-SRC7",
                                         name="Core Source 7")
        owner = create_distributor(distributor_code="D-A", name="Owner A",
                                   credit_limit_cents=2000000)
        other = create_distributor(distributor_code="D-B", name="Other B")
        spec = create_active_spec(application_code="CAPRICE-1994")
        produce_sealed_engine(spec, core_source, slot=0)
        sale = sell_engine_to(owner, spec)
        deposit = sale["deposit"]
        assert deposit["status"] == "HELD"

        resp = api.create_core_return(
            create_core_return_payload(other["id"], spec["id"],
                                       core_deposit_id=deposit["id"]),
            make_distributor_headers(other["id"]))
        validate_error(resp, ApiErrorId.ERR_DEPOSIT_NOT_LINKABLE)

    def test_grade_already_graded_return_rejected(self, api):
        """PRD §3.3: "Grading is performed by a `CoreInspector` and moves the
        return from `RECEIVED` to `GRADED`."
        PRD §3.3: "A disputed return can be graded again: the same grading
        capability moves it from `DISPUTED` back to `GRADED`".

        Design: Corner/state_machines/grade_already_graded_return_rejected
        """
        set_logical_clock()
        distributor = create_distributor(distributor_code="D-GG",
                                         name="Double Grade Co")
        spec = create_active_spec(application_code="MONTECARLO-1996")
        ret = create_graded_return(distributor, spec, "GRADE_A", [])
        assert ret["final_credit_cents"] == 100000

        resp = api.grade_core_return(ret["id"],
                                     grade_return_payload("GRADE_B", []),
                                     INSPECTOR)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

        after = get_core_return(ret["id"])
        assert after["grade"] == "GRADE_A"
        assert after["final_credit_cents"] == 100000, (
            "the rejected second grading changed nothing")

    def test_respond_on_closed_return_terminal_lockdown(self, api):
        """PRD §3.3: "Acceptance moves the return from `GRADED` to `CLOSED`,
        the terminal state, with no further ledger effect."

        Design: Corner/state_machines/respond_on_closed_return_terminal_lockdown
        """
        set_logical_clock()
        distributor = create_distributor(distributor_code="D-TL",
                                         name="Terminal Co")
        spec = create_active_spec(application_code="BERETTA-1996")
        ret = create_graded_return(distributor, spec, "GRADE_B", [])
        closed = respond_to_grading(ret, distributor, "ACCEPT")
        assert closed["status"] == "CLOSED"

        resp = api.respond_core_return(
            ret["id"], respond_grading_payload("DISPUTE"),
            make_distributor_headers(distributor["id"]))
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

        after = get_core_return(ret["id"])
        assert after["status"] == "CLOSED"
        assert after["dispute_count"] == 0

    def test_grade_as_distributor_forbidden(self, api):
        """PRD §2.1: "Access to each operation is restricted by role; a caller
        whose role is not listed for the endpoint will be rejected with
        `ERR_FORBIDDEN_ROLE` (HTTP 403)."
        PRD §3.3: "Grading is performed by a `CoreInspector`".

        Design: Corner/rbac/grade_as_distributor_forbidden
        """
        set_logical_clock()
        distributor = create_distributor(distributor_code="D-RB",
                                         name="Role Block Co")
        spec = create_active_spec(application_code="S10-1994")
        ret = create_received_return(distributor, spec)

        resp = api.grade_core_return(
            ret["id"], grade_return_payload("GRADE_A", []),
            make_distributor_headers(distributor["id"]))
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE)

        assert get_core_return(ret["id"])["status"] == "RECEIVED"

    def test_respond_as_non_owner_distributor_forbidden(self, api):
        """PRD §3.3: "Only the owning distributor may respond; a response
        naming a return owned by another distributor is rejected with
        `ERR_FORBIDDEN_OWNERSHIP`."

        Design: Corner/rbac/respond_as_non_owner_distributor_forbidden
        """
        set_logical_clock()
        owner = create_distributor(distributor_code="D-OA", name="Owner A Co")
        other = create_distributor(distributor_code="D-OB", name="Other B Co")
        spec = create_active_spec(application_code="TRACKER-1995")
        ret = create_graded_return(owner, spec, "GRADE_A", [])

        resp = api.respond_core_return(
            ret["id"], respond_grading_payload("ACCEPT"),
            make_distributor_headers(other["id"]))
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_OWNERSHIP)

        assert get_core_return(ret["id"])["status"] == "GRADED"


class TestCoreReturnListing:
    def test_list_endpoints_filter_and_shape(self, api):
        """PRD §2.3: "The `limit` parameter specifies the maximum number of
        items to return; when omitted it defaults to 10, with a minimum
        allowed value of 1 and a maximum of 100. The `offset` parameter
        specifies how many items to skip and defaults to 0."
        PRD §2.3: "The `meta` object of a list response carries the pagination
        fields `limit`, `offset`, `total_count`, and `has_more`."
        PRD §2.2: "The `response_type` is either "object" for a single
        resource or "array" for a list of resources."

        Design: Corner/endpoints/list_endpoints_filter_and_shape
        """
        set_logical_clock()
        distributor = create_distributor(distributor_code="D-LF",
                                         name="List Filter Co")
        spec = create_active_spec(application_code="C1500-1993")
        ret1 = create_received_return(distributor, spec)
        ret2 = create_received_return(distributor, spec)
        grade_core_return(ret1["id"], "GRADE_B", [])

        resp = api.list_core_returns(ADMIN)
        assert resp.json()["response_type"] == "array"
        data, meta = validate_paginated(resp)
        assert len(data) == 2
        assert meta["total_count"] == 2
        assert meta["has_more"] is False
        assert meta["limit"] == 10, "default limit is 10"
        assert meta["offset"] == 0

        page1, meta1 = validate_paginated(
            api.list_core_returns(ADMIN, params={"limit": 1, "offset": 0}))
        assert len(page1) == 1
        assert meta1["total_count"] == 2
        assert meta1["has_more"] is True

        page2, meta2 = validate_paginated(
            api.list_core_returns(ADMIN, params={"limit": 1, "offset": 1}))
        assert len(page2) == 1
        assert meta2["has_more"] is False
        assert page1[0]["id"] != page2[0]["id"]
        assert {page1[0]["id"], page2[0]["id"]} == {ret1["id"], ret2["id"]}
