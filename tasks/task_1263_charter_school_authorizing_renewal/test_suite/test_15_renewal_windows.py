"""Renewal windows: the strict finalize boundary, zero-eligibility denial, and
the creation window (PRD §3.6)."""
from test_helpers import (
    validate_success, validate_error, ApiErrorId, CLOCK, assert_same_instant,
    create_open_school, setup_renewal_ready_school, create_renewal_decision,
    add_accepted_report, set_clock,
    make_staff_headers, make_board_headers, api_client,
)

STAFF = make_staff_headers("staff_1")


class TestFinalizeWindowBoundaryStrictlyAfter30Days:
    def test_finalize_at_exactly_30_days_rejected_then_succeeds_one_second_later(self, api):
        """PRD §3.6: "Finalizing requires the decision to be `DECIDED`
        (`ERR_DECISION_INVALID_STATE`), the logical clock to read strictly
        later than thirty days after `decided_at`, and no appeal in `FILED` or
        `HEARING_SCHEDULED` targeting the decision; a window still open — or an
        appeal still pending — is rejected with `ERR_APPEAL_WINDOW_OPEN`."
        PRD §3.6: "For `RENEWED` or `RENEWED_WITH_CONDITIONS`, the system
        drafts the successor contract: a new `DRAFT` `CharterContract` whose
        `prior_contract_id` points at the decided contract, whose `term_start`
        is the day after the prior term's `term_end`, whose `term_end` is
        `granted_term_years` years after that start, and whose
        `framework_version` is copied from its predecessor; the decided
        contract itself moves `ACTIVE` → `RENEWED`."

        Design: Corner/state_machines/sm_finalize_window_boundary_strictly_after_30d
        """
        ctx = setup_renewal_ready_school(school_name="SM Finalize Academy",
                                         applicant_id="applicant_s15")
        decision = create_renewal_decision(ctx["school"]["id"], ctx["contract"]["id"])
        decided = validate_success(api.decide_renewal(
            decision["id"], {"outcome": "RENEWED"}, make_board_headers("board_1")), 200)
        assert decided["status"] == "DECIDED"
        assert_same_instant(decided["decided_at"], CLOCK["RENEWAL_OPEN"])

        # Exactly decided_at + 30 days: still inside the (inclusive) window.
        set_clock(CLOCK["RENEWAL_DECIDED_PLUS_30D"])
        res = api.finalize_renewal(decision["id"], STAFF)
        validate_error(res, ApiErrorId.ERR_APPEAL_WINDOW_OPEN, expected_status=409)

        # One second past: strictly later, finalize succeeds.
        set_clock(CLOCK["RENEWAL_DECIDED_PLUS_30D_1S"])
        finalized = validate_success(api.finalize_renewal(decision["id"], STAFF), 200)
        assert finalized["status"] == "FINAL"

        successors = validate_success(
            api.list_contracts(STAFF, params={"prior_contract_id": ctx["contract"]["id"]}),
            200)
        assert len(successors) == 1
        successor = successors[0]
        assert successor["status"] == "DRAFT"
        assert_same_instant(successor["term_start"], "2032-07-01T00:00:00Z")
        assert successor["framework_version"] == ctx["contract"]["framework_version"]

        prior = validate_success(api.get_contract(ctx["contract"]["id"], STAFF), 200)
        assert prior["status"] == "RENEWED"


class TestRenewalEligibleZeroBarsRenewal:
    def test_eligible_zero_rejects_renewed_but_allows_denied(self, api):
        """PRD §3.6: "anything below earns 0, which bars renewal outright"
        PRD §3.6: "`RENEWED` requires `eligible_term_years` above zero
        (`ERR_RENEWAL_NOT_ELIGIBLE`), and `RENEWED_WITH_CONDITIONS` requires
        `eligible_term_years` of at least 3 (`ERR_TERM_LENGTH_MISMATCH`)."

        Design: Corner/calculations/calc_renewal_eligible_zero_bars_renewal
        """
        ctx = create_open_school(school_name="Calc Ineligible Academy",
                                 applicant_id="applicant_c3")
        # Two ACCEPTED reports at 50/50/50: each index 50.0 -> avg 50.0 (< 60).
        add_accepted_report(ctx["school"]["id"], fiscal_year=2028,
                            academic_score=50, financial_score=50,
                            operational_score=50)
        add_accepted_report(ctx["school"]["id"], fiscal_year=2029,
                            academic_score=50, financial_score=50,
                            operational_score=50)
        set_clock(CLOCK["RENEWAL_OPEN"])
        decision = create_renewal_decision(ctx["school"]["id"], ctx["contract"]["id"])
        assert decision["eligible_term_years"] == 0

        res = api.decide_renewal(decision["id"], {"outcome": "RENEWED"},
                                 make_board_headers("board_1"))
        validate_error(res, ApiErrorId.ERR_RENEWAL_NOT_ELIGIBLE, expected_status=422)

        denied = validate_success(api.decide_renewal(
            decision["id"], {"outcome": "DENIED"}, make_board_headers("board_1")), 200)
        assert denied["status"] == "DECIDED"
        assert denied["decision"] == "DENIED"
        assert denied["granted_term_years"] is None


class TestRenewalWindowNotOpen:
    def test_create_outside_window_rejected(self, api):
        """PRD §3.6: "The logical clock must fall inside the renewal window,
        which runs from 365 days before the contract's `term_end` through 30
        days before `term_end`, both bounds inclusive; outside that window the
        create is rejected with `ERR_RENEWAL_WINDOW_NOT_OPEN`."

        Design: Corner/validations/val_renewal_window_not_open_rejected
        """
        ctx = create_open_school(school_name="Val Window2 Academy",
                                 applicant_id="applicant_v8")
        assert ctx["contract"]["status"] == "ACTIVE"
        # Default clock 2026-05-01 is years before the window for a term
        # ending 2032-06-30.
        res = api.create_renewal_decision(ctx["school"]["id"],
                                          {"contract_id": ctx["contract"]["id"]}, STAFF)
        validate_error(res, ApiErrorId.ERR_RENEWAL_WINDOW_NOT_OPEN,
                       expected_status=422)
