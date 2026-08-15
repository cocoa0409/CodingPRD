"""Leadership terms: tenure gate, succession chain, term limits, and the
leadership-gap cascade fired by resignation and by the clock sweep."""
import pytest

from test_helpers import (
    ApiErrorId,
    advance_clock,
    create_active_group,
    create_funding_request,
    create_leader_term,
    create_leadership_term_payload,
    create_open_program,
    create_sponsor,
    make_group_leader_headers,
    setup_active_group_with_leader,
    sponsor_decide_funding,
    validate_error,
    validate_success,
)
from test_helpers.fixtures import DEI_HEADERS


class TestTenureGate:
    def test_term_tenure_boundary_89_vs_90_days(self, api):
        """PRD §3.6: "Three further gates apply: the group must be `ACTIVE` (`ERR_GROUP_NOT_ACTIVE`); no other term of the group may be `ACTIVE` (`ERR_ACTIVE_TERM_EXISTS`); and the prospective leader must hold an `ACTIVE` membership in the group whose `joined_at` is at least 90 days in the past relative to the current logical time (`ERR_TERM_TENURE_NOT_MET`)."

        Design: Corner/validations/term_tenure_boundary_89_vs_90_days
        """
        program = create_open_program(100000)
        sponsor = create_sponsor("emp_sp29", max_groups=3, max_mentees=2)
        # Founding member emp_f01 joined at the default clock 2026-08-01T00:00:00Z.
        group = create_active_group(
            program["id"], sponsor["id"], "Tenure", "AFFINITY", "emp_l44"
        )

        # At 2026-10-29 the membership is 89 days old: below the 90-day gate.
        advance_clock("2026-10-29T00:00:00Z")
        resp = api.create_leadership_term(
            create_leadership_term_payload(group["id"], "emp_f01", "2027-01-30T00:00:00Z"),
            DEI_HEADERS,
        )
        validate_error(resp, ApiErrorId.ERR_TERM_TENURE_NOT_MET.value, 409)

        # At 2026-10-30 the membership is exactly 90 days old: gate satisfied.
        advance_clock("2026-10-30T00:00:00Z")
        resp = api.create_leadership_term(
            create_leadership_term_payload(group["id"], "emp_f01", "2027-01-30T00:00:00Z"),
            DEI_HEADERS,
        )
        data = validate_success(resp, 201)
        assert data["status"] == "ACTIVE"


class TestSuccessionChain:
    def test_term_succession_chain_rules(self, api):
        """PRD §3.6: "no other term of the group may be `ACTIVE` (`ERR_ACTIVE_TERM_EXISTS`)"
        PRD §3.6: "The chain rule is strict: `predecessor_term_id` must identify the prior term with the latest `ends_at`, breaking ties by the latest `created_at`; a mismatched, missing, or unexpectedly supplied predecessor (including supplying one for the group's very first term) is rejected with `ERR_PREDECESSOR_MISMATCH`."
        PRD §3.6: "An employee may hold at most 2 terms in the same group across all statuses — a third appointment is rejected with `ERR_TERM_LIMIT_EXCEEDED`."

        Design: Corner/validations/term_succession_chain_rules
        """
        program = create_open_program(100000)
        sponsor = create_sponsor("emp_sp30", max_groups=3, max_mentees=2)
        # emp_f01 and emp_f02 are founding members (joined 2026-08-01).
        group = create_active_group(
            program["id"], sponsor["id"], "Succession", "AFFINITY", "emp_l45"
        )
        advance_clock("2026-11-01T00:00:00Z")
        t1 = create_leader_term(group["id"], "emp_f01", "2027-02-01T00:00:00Z")

        # A second ACTIVE term for the group is rejected while t1 is ACTIVE.
        resp = api.create_leadership_term(
            create_leadership_term_payload(group["id"], "emp_f02", "2027-05-01T00:00:00Z",
                                           predecessor_term_id=t1["id"]),
            DEI_HEADERS,
        )
        validate_error(resp, ApiErrorId.ERR_ACTIVE_TERM_EXISTS.value, 409)

        validate_success(api.resign_leadership_term(t1["id"], DEI_HEADERS), 200)

        # Once a prior term exists, omitting the predecessor is rejected.
        resp = api.create_leadership_term(
            create_leadership_term_payload(group["id"], "emp_f02", "2027-05-01T00:00:00Z"),
            DEI_HEADERS,
        )
        validate_error(resp, ApiErrorId.ERR_PREDECESSOR_MISMATCH.value, 409)

        # The correct predecessor (the latest prior term) is accepted.
        t2 = validate_success(
            api.create_leadership_term(
                create_leadership_term_payload(group["id"], "emp_f02",
                                               "2027-05-01T00:00:00Z",
                                               predecessor_term_id=t1["id"]),
                DEI_HEADERS,
            ),
            201,
        )
        assert t2["status"] == "ACTIVE"

        validate_success(api.resign_leadership_term(t2["id"], DEI_HEADERS), 200)

        # emp_f01's second term (t1 was the first): predecessor is t2, the
        # prior term with the latest ends_at.
        t3 = validate_success(
            api.create_leadership_term(
                create_leadership_term_payload(group["id"], "emp_f01",
                                               "2027-08-01T00:00:00Z",
                                               predecessor_term_id=t2["id"]),
                DEI_HEADERS,
            ),
            201,
        )
        validate_success(api.resign_leadership_term(t3["id"], DEI_HEADERS), 200)

        # A third term for emp_f01 violates the lifetime two-term limit.
        resp = api.create_leadership_term(
            create_leadership_term_payload(group["id"], "emp_f01",
                                           "2027-11-01T00:00:00Z",
                                           predecessor_term_id=t3["id"]),
            DEI_HEADERS,
        )
        validate_error(resp, ApiErrorId.ERR_TERM_LIMIT_EXCEEDED.value, 409)


class TestGapCascade:
    def test_resign_triggers_gap_withdrawal_cascade(self, api):
        """PRD §3.6: "The leader may resign (a `GroupLeader` caller whose `X-User-ID` equals the term's `leader_employee_id`, or a `DeiAdmin`), moving the term `ACTIVE` → `RESIGNED`; resigning a term that is not `ACTIVE` is `ERR_INVALID_STATE_TRANSITION`."
        PRD §3.6: "Both endings fire the same gap cascade when they leave the group with no remaining `ACTIVE` term: `has_active_leader` flips to false and every funding request of the group in `SUBMITTED` or `COUNTERED` status moves to `WITHDRAWN`."

        Design: Corner/state_machines/resign_triggers_gap_withdrawal_cascade
        """
        program = create_open_program(500000)
        sponsor = create_sponsor("emp_sp22", max_groups=3, max_mentees=2)
        group, term = setup_active_group_with_leader(
            program["id"], sponsor["id"], "Resign Gap", "AFFINITY", "emp_l29", "emp_f01"
        )
        request = create_funding_request(
            group["id"], "emp_f01", "OTHER", "Countered then orphaned", 60000, 0
        )
        sponsor_decide_funding(request["id"], sponsor["id"], "COUNTER", 40000)

        # The leader resigns their own term.
        data = validate_success(
            api.resign_leadership_term(term["id"], make_group_leader_headers("emp_f01")), 200
        )
        assert data["status"] == "RESIGNED"

        group_data = validate_success(api.get_group(group["id"], DEI_HEADERS), 200)
        assert group_data["has_active_leader"] is False
        request_data = validate_success(
            api.get_funding_request(request["id"], DEI_HEADERS), 200
        )
        assert request_data["status"] == "WITHDRAWN", (
            "COUNTERED requests are cascade-withdrawn on leadership gap"
        )

    def test_clock_sweep_expires_term_and_clears_leader_flag(self, api):
        """PRD §2.5: "Advancing the clock runs a term-expiry sweep: every `LeadershipTerm` in `ACTIVE` status whose `ends_at` is at or before the new clock value flips to `EXPIRED`, and each such expiry fires the leadership-gap cascade described in §3.6."

        Design: Difficulty/transitive_cascade/term_expiry_gap_withdrawal_cascade
        """
        program = create_open_program(500000)
        sponsor = create_sponsor("emp_sp9", max_groups=3, max_mentees=2)
        group, term = setup_active_group_with_leader(
            program["id"], sponsor["id"], "Cascade One", "AFFINITY", "emp_l9", "emp_f01"
        )
        request = create_funding_request(
            group["id"], "emp_f01", "OTHER", "Doomed request", 100000, 0
        )

        # Advance past the term's 2027-02-01 expiry.
        advance_clock("2027-02-02T00:00:00Z")

        term_data = validate_success(api.get_leadership_term(term["id"], DEI_HEADERS), 200)
        assert term_data["status"] == "EXPIRED", "link 1: clock sweep expires the term"
        group_data = validate_success(api.get_group(group["id"], DEI_HEADERS), 200)
        assert group_data["has_active_leader"] is False, (
            "link 2: the expiry leaves the group with no ACTIVE term"
        )

    def test_clock_sweep_withdraws_orphaned_funding_request(self, api):
        """PRD §3.6: "Both endings fire the same gap cascade when they leave the group with no remaining `ACTIVE` term: `has_active_leader` flips to false and every funding request of the group in `SUBMITTED` or `COUNTERED` status moves to `WITHDRAWN`."

        Design: Difficulty/transitive_cascade/term_expiry_gap_withdrawal_cascade
        """
        program = create_open_program(500000)
        sponsor = create_sponsor("emp_sp9", max_groups=3, max_mentees=2)
        group, term = setup_active_group_with_leader(
            program["id"], sponsor["id"], "Cascade One", "AFFINITY", "emp_l9", "emp_f01"
        )
        request = create_funding_request(
            group["id"], "emp_f01", "OTHER", "Doomed request", 100000, 0
        )

        advance_clock("2027-02-02T00:00:00Z")

        request_data = validate_success(
            api.get_funding_request(request["id"], DEI_HEADERS), 200
        )
        assert request_data["status"] == "WITHDRAWN", (
            "link 3: the SUBMITTED request is withdrawn by the gap cascade"
        )
