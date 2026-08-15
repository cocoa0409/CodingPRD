"""Payer determination rules (state gate, coverage, belonging, amounts), case
totals recompute, immediate consistency, and closure gating on children."""
from test_helpers import (
    ApiErrorId,
    add_claim_line,
    advance_clock,
    begin_payer_review,
    create_audit_case,
    create_demand,
    create_issue_code,
    create_payer,
    denied_outcome,
    get_case,
    get_line,
    make_payer_agent_headers,
    paid_outcome,
    partial_outcome,
    post_determination,
    setup_determined_case,
    submit_records,
    validate_error,
    validate_success,
    write_off_demand,
)
from test_helpers import TEST_USERS

HIM = TEST_USERS["him_headers"]
DIRECTOR = TEST_USERS["director_headers"]


class TestDeterminationStateGate:
    def test_determination_before_payer_review_rejected(self, api):
        """PRD §3.3: "The case stamps `determination_issued_at` with the
        logical now, recomputes its totals, appends a `DETERMINATION_ISSUED`
        event, and moves `UNDER_PAYER_REVIEW → DETERMINATION_ISSUED`."
        PRD §2.9: "State guards — the target must be in a state that permits
        the requested transition, else `ERR_INVALID_STATE_TRANSITION` (409)"

        Design: Corner/state_machines/determination_before_review_rejected
        """
        payer = create_payer(name="P1")
        issue = create_issue_code("MED_NEC", "CLINICAL", "Medical necessity")
        case = create_audit_case(payer["id"])
        line = add_claim_line(case["id"], billed_amount_cents=100000)
        submit_records(case["id"])
        resp = api.post_determination(
            case["id"],
            {"outcomes": [denied_outcome(line["id"], 100000, issue["id"],
                                         "CLINICAL")]},
            make_payer_agent_headers(payer["id"]))
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE_TRANSITION)


class TestDeterminationContentChecks:
    def _reviewing_case(self, billed=(100000, 50000)):
        payer = create_payer(name="P1")
        issue = create_issue_code("MED_NEC", "CLINICAL", "Medical necessity")
        case = create_audit_case(payer["id"])
        lines = [add_claim_line(case["id"], claim_number=f"L-{i}",
                                patient_account_number=f"PA-{i}",
                                billed_amount_cents=b)
                 for i, b in enumerate(billed, start=1)]
        submit_records(case["id"])
        begin_payer_review(case["id"], payer["id"])
        return payer, issue, case, lines

    def test_incomplete_outcome_coverage_rejected(self, api):
        """PRD §3.3: "Coverage: the outcomes must address every `UNDER_AUDIT`
        line of the case exactly once — a missed or duplicated line is rejected
        with `ERR_DETERMINATION_INCOMPLETE` (HTTP 422)."

        Design: Corner/validations/determination_incomplete_rejected
        """
        payer, _issue, case, lines = self._reviewing_case()
        resp = api.post_determination(
            case["id"], {"outcomes": [paid_outcome(lines[0]["id"])]},
            make_payer_agent_headers(payer["id"]))
        validate_error(resp, ApiErrorId.ERR_DETERMINATION_INCOMPLETE)
        assert get_case(case["id"])["status"] == "UNDER_PAYER_REVIEW"

    def test_partial_denial_of_full_billed_amount_rejected(self, api):
        """PRD §3.3: "a `PARTIALLY_DENIED` outcome must carry a denied amount
        strictly greater than zero and strictly less than the billed amount —
        violations are rejected with `ERR_DETERMINATION_AMOUNT_INVALID`
        (HTTP 422)."

        Design: Corner/validations/determination_amount_invalid_rejected
        """
        payer, issue, case, lines = self._reviewing_case(billed=(60000,))
        resp = api.post_determination(
            case["id"],
            {"outcomes": [partial_outcome(lines[0]["id"], 60000, issue["id"],
                                          "CLINICAL")]},
            make_payer_agent_headers(payer["id"]))
        validate_error(resp, ApiErrorId.ERR_DETERMINATION_AMOUNT_INVALID)

    def test_outcome_referencing_other_case_line_rejected(self, api):
        """PRD §3.3: "Belonging: every entry's `claim_line_id` must reference
        a line of this case, else `ERR_DETERMINATION_LINE_INVALID` (HTTP 422)."

        Design: Corner/validations/determination_line_invalid_rejected
        """
        payer, issue, case_a, lines_a = self._reviewing_case(billed=(100000,))
        case_b = create_audit_case(payer["id"], "RAC_AUTOMATED")
        line_b = add_claim_line(case_b["id"], claim_number="B-1",
                                patient_account_number="PA-2",
                                service_start_date="2026-02-01T00:00:00Z",
                                service_end_date="2026-02-03T00:00:00Z",
                                billed_amount_cents=50000)
        submit_records(case_b["id"])
        begin_payer_review(case_b["id"], payer["id"])
        resp = api.post_determination(
            case_a["id"],
            {"outcomes": [paid_outcome(lines_a[0]["id"]),
                          denied_outcome(line_b["id"], 50000, issue["id"],
                                         "CLINICAL")]},
            make_payer_agent_headers(payer["id"]))
        validate_error(resp, ApiErrorId.ERR_DETERMINATION_LINE_INVALID)


class TestDeterminationTotals:
    def test_mixed_outcomes_recompute_case_totals(self, api):
        """PRD §3.3: "`total_denied_active_cents` is the sum of
        `denied_amount_cents` over lines in `DENIED` or `PARTIALLY_DENIED`"
        PRD §3.3: "`total_upheld_cents` is the sum, over lines in
        `PAID_AS_BILLED`, `DENIED`, `PARTIALLY_DENIED`, `OVERTURNED`, or
        `FINAL`, of each line's billed amount minus its denied amount."

        Design: Corner/state_machines/determination_side_effects_case_totals
        """
        payer = create_payer(name="P1")
        issue = create_issue_code("MED_NEC", "CLINICAL", "Medical necessity")
        case = create_audit_case(payer["id"])
        l1 = add_claim_line(case["id"], "L-1", "PA-1", billed_amount_cents=100000)
        l2 = add_claim_line(case["id"], "L-2", "PA-2",
                            service_start_date="2026-01-04T00:00:00Z",
                            service_end_date="2026-01-06T00:00:00Z",
                            billed_amount_cents=40000)
        l3 = add_claim_line(case["id"], "L-3", "PA-3",
                            service_start_date="2026-01-07T00:00:00Z",
                            service_end_date="2026-01-09T00:00:00Z",
                            billed_amount_cents=60000)
        submit_records(case["id"])
        begin_payer_review(case["id"], payer["id"])
        posted = post_determination(case["id"], payer["id"], [
            paid_outcome(l1["id"]),
            denied_outcome(l2["id"], 40000, issue["id"], "CLINICAL"),
            partial_outcome(l3["id"], 20000, issue["id"], "TECHNICAL"),
        ])
        assert posted["status"] == "DETERMINATION_ISSUED"
        assert posted["total_billed_cents"] == 200000
        assert posted["total_denied_active_cents"] == 60000
        assert posted["total_upheld_cents"] == 140000

    def test_determination_response_carries_recomputed_state(self, api):
        """PRD §2.2: "Unless otherwise noted, operations that create or modify
        a resource will return the created or updated resource object in the
        data field."
        PRD §3.3: "The case stamps `determination_issued_at` with the logical
        now, recomputes its totals, appends a `DETERMINATION_ISSUED` event, and
        moves `UNDER_PAYER_REVIEW → DETERMINATION_ISSUED`."
        PRD §2.4: "At server startup the logical clock stands at exactly
        `2026-08-01T00:00:00Z`, regardless of the real time of day."

        Design: Corner/consistency_model/immediate_consistency_determination_response
        """
        payer = create_payer(name="P1")
        issue = create_issue_code("AUTH", "TECHNICAL", "Missing auth")
        case = create_audit_case(payer["id"])
        line = add_claim_line(case["id"], billed_amount_cents=100000)
        submit_records(case["id"])
        begin_payer_review(case["id"], payer["id"])
        posted = post_determination(case["id"], payer["id"],
                                    [denied_outcome(line["id"], 100000,
                                                    issue["id"])])
        assert posted["status"] == "DETERMINATION_ISSUED"
        assert posted["total_denied_active_cents"] == 100000, (
            "Totals are recomputed inside the same 200 response")
        assert posted["determination_issued_at"] == "2026-08-01T00:00:00Z"


class TestCaseClosure:
    def test_close_from_received_rejected(self, api, director_headers):
        """PRD §3.9: "Case closure is the terminal act of the audit workflow,
        moving `DETERMINATION_ISSUED → CLOSED`"
        PRD §2.9: "State guards — the target must be in a state that permits
        the requested transition, else `ERR_INVALID_STATE_TRANSITION` (409)"

        Design: Corner/state_machines/case_close_from_received_rejected
        """
        payer = create_payer(name="P1")
        case = create_audit_case(payer["id"])
        resp = api.close_audit_case(case["id"], director_headers)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE_TRANSITION)
        assert get_case(case["id"])["status"] == "RECEIVED"

    def test_close_blocked_by_non_terminal_line(self, api):
        """PRD §3.9: "Three resolution conditions must all hold, each enforced
        with `ERR_OPEN_APPEALS_EXIST` (HTTP 409): every claim line of the case
        must be in a terminal state — `PAID_AS_BILLED`, `OVERTURNED`, or
        `FINAL`"

        Design: Difficulty/cross_entity_state_dependency/case_close_gated_by_children
        """
        ctx, demand = self._case_with_demand()
        resp = api.close_audit_case(ctx["case"]["id"], DIRECTOR)
        validate_error(resp, ApiErrorId.ERR_OPEN_APPEALS_EXIST)
        advance_clock("2026-09-01T00:00:00Z")
        line = get_line(ctx["lines"][0]["id"])
        assert line["status"] == "FINAL", (
            "The L1 window lapsed with no appeal, so the line finalized")
        resp2 = api.close_audit_case(ctx["case"]["id"], DIRECTOR)
        validate_error(resp2, ApiErrorId.ERR_OPEN_APPEALS_EXIST)
        assert get_case(ctx["case"]["id"])["status"] == "DETERMINATION_ISSUED"

    def test_close_blocked_by_unsettled_demand_then_succeeds(self, api):
        """PRD §3.9: "every recoupment demand of the case must be
        `FULLY_RECOUPED`, `REVERSED`, or `WRITTEN_OFF`"
        PRD §3.9: "no appeal of the case may be `PENDING_DECISION`, and no
        `DRAFT` appeal whose `filed_deadline_at` is still at or after the
        logical now may exist (a stale draft past its deadline does not block
        closure); and every recoupment demand of the case must be
        `FULLY_RECOUPED`, `REVERSED`, or `WRITTEN_OFF`."

        Design: Difficulty/cross_entity_state_dependency/case_close_gated_by_children
        """
        ctx, demand = self._case_with_demand()
        advance_clock("2026-09-01T00:00:00Z")
        resp = api.close_audit_case(ctx["case"]["id"], DIRECTOR)
        validate_error(resp, ApiErrorId.ERR_OPEN_APPEALS_EXIST)
        write_off_demand(demand["id"])
        closed = validate_success(
            api.close_audit_case(ctx["case"]["id"], DIRECTOR), 200)
        assert closed["status"] == "CLOSED"

    def _case_with_demand(self):
        ctx = setup_determined_case(billed_amounts=(100000,))
        demand = create_demand(ctx["case"]["id"], ctx["payer"]["id"], 100000)
        return ctx, demand
