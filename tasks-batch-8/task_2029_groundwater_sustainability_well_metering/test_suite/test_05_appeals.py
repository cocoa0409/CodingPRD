"""Penalty appeals: branching decisions, segregation of duties, filing window
(PRD §3.6, §2.1)."""
from test_helpers import (
    ApiErrorId,
    appeal_assessment,
    create_account,
    create_and_appeal_assessment,
    create_penalty_assessment,
    decide_assessment,
    get_account,
    make_appeals_officer_headers,
    make_enforcement_officer_headers,
    make_well_owner_headers,
    pay_assessment,
    set_clock,
    validate_error,
    validate_success,
)


class TestAppealBranches:
    def test_appeal_branches_divergent_side_effects(self, api):
        """PRD §3.6: "`UPHELD` leaves `penalty_balance_cents` unchanged. `OVERTURNED` debits `penalty_balance_cents` by the full `amount_cents` — a full refund. `REDUCED` requires a `reduced_amount_cents` value that is strictly greater than zero and strictly less than `amount_cents` (any other value, or its absence, fails with `ERR_INVALID_REQUEST`); it debits `penalty_balance_cents` by the difference between `amount_cents` and `reduced_amount_cents` — a partial refund — and records the reduced figure on the assessment."
        PRD §3.6: "The `outcome` field selects among three branches, each of which stamps `decided_by`."

        Design: Difficulty/non_linear_state_machine/penalty_appeal_branching_divergent_side_effects
        """
        account = create_account(holder_name="Pumper F")
        assessments = [
            create_and_appeal_assessment(account["id"], "LATE_REPORT", 2026)
            for _ in range(3)
        ]
        mid = get_account(account["id"])
        assert mid["penalty_balance_cents"] == 30000

        upheld = decide_assessment(assessments[0]["id"], "UPHELD")
        overturned = decide_assessment(assessments[1]["id"], "OVERTURNED")
        reduced = decide_assessment(assessments[2]["id"], "REDUCED", reduced_amount_cents=4000)

        assert upheld["status"] == "UPHELD"
        assert overturned["status"] == "OVERTURNED"
        assert reduced["status"] == "REDUCED"
        assert reduced["reduced_amount_cents"] == 4000
        for decided in (upheld, overturned, reduced):
            assert decided["decided_by"] == "ao-1", (
                f"each branch stamps decided_by, got {decided['decided_by']!r}"
            )

        final = get_account(account["id"])
        # 30000 - 0 (UPHELD) - 10000 (OVERTURNED full refund) - 6000 (REDUCED partial)
        assert final["penalty_balance_cents"] == 14000, (
            f"expected 14000 after the three divergent branches, got "
            f"{final['penalty_balance_cents']}"
        )

    def test_reduced_decision_then_pay_reduced_amount(self, api):
        """PRD §3.6: "Payment from `ASSESSED` or `UPHELD` debits `penalty_balance_cents` by `amount_cents` and stamps `paid_amount_cents` equal to `amount_cents`; payment from `REDUCED` debits by `reduced_amount_cents` and stamps `paid_amount_cents` equal to `reduced_amount_cents`."

        Design: Difficulty/non_linear_state_machine/penalty_appeal_branching_divergent_side_effects
        """
        account = create_account(holder_name="Pumper F2")
        assessment = create_and_appeal_assessment(account["id"], "LATE_REPORT", 2026)

        reduced = decide_assessment(assessment["id"], "REDUCED", reduced_amount_cents=4000)
        assert reduced["status"] == "REDUCED"
        assert get_account(account["id"])["penalty_balance_cents"] == 4000

        paid = pay_assessment(assessment["id"], account["id"])
        assert paid["status"] == "PAID"
        assert paid["paid_amount_cents"] == 4000, (
            f"payment from REDUCED must collect reduced_amount_cents, got "
            f"{paid['paid_amount_cents']}"
        )
        assert get_account(account["id"])["penalty_balance_cents"] == 0


class TestAssessOverturnCompensation:
    def test_assess_overturn_restores_penalty_balance(self, api):
        """PRD §3.6: "`UPHELD` leaves `penalty_balance_cents` unchanged. `OVERTURNED` debits `penalty_balance_cents` by the full `amount_cents` — a full refund."
        PRD §3.6: "A new assessment starts in `ASSESSED` status, `assessed_by` is stamped from the caller's `X-User-ID` (or the literal `system` for the auto-created cascade), and the account's `penalty_balance_cents` increases by `amount_cents`."

        Design: Difficulty/compensating_invariant/assess_overturn_restores_penalty_balance
        """
        account = create_account(holder_name="Pumper OS")
        assessment = create_penalty_assessment(account["id"], "LATE_REPORT", 2026)
        assert get_account(account["id"])["penalty_balance_cents"] == 10000

        appeal_assessment(assessment["id"], account["id"], "late fee disputed")
        decided = decide_assessment(assessment["id"], "OVERTURNED")
        assert decided["status"] == "OVERTURNED"

        final = get_account(account["id"])
        assert final["penalty_balance_cents"] == 0, (
            f"assess (+10000) followed by overturn (-10000) must show zero drift, got "
            f"{final['penalty_balance_cents']}"
        )

    def test_assess_overturn_restores_penalty_balance_unmetered(self, api):
        """PRD §3.6: "For `LATE_REPORT` the fee is a flat 10000 cents; for `UNMETERED_PUMPING` it is a flat 50000 cents; flat fees are never multiplied by the basin-condition multiplier."
        PRD §3.6: "`UPHELD` leaves `penalty_balance_cents` unchanged. `OVERTURNED` debits `penalty_balance_cents` by the full `amount_cents` — a full refund."

        Design: Difficulty/compensating_invariant/assess_overturn_restores_penalty_balance
        """
        account = create_account(holder_name="Pumper OS-2")
        assessment = create_penalty_assessment(account["id"], "UNMETERED_PUMPING", 2026)
        assert assessment["amount_cents"] == 50000
        assert get_account(account["id"])["penalty_balance_cents"] == 50000

        appeal_assessment(assessment["id"], account["id"])
        decided = decide_assessment(assessment["id"], "OVERTURNED")
        assert decided["status"] == "OVERTURNED"
        assert get_account(account["id"])["penalty_balance_cents"] == 0, (
            "the conserved money quantity must return to exactly zero"
        )


class TestAppealGates:
    def test_appeal_paid_assessment_rejected(self, api):
        """PRD §3.6: "The account owner may pay an assessment while it is in `ASSESSED`, `UPHELD`, or `REDUCED` — any other status yields `ERR_INVALID_ASSESSMENT_STATE`."
        PRD §3.6: "The owner may instead appeal an `ASSESSED` assessment by supplying `grounds`, provided the logical clock has not passed 30 days after the assessment's `created_at` — filing exactly at the deadline is allowed, and strictly later filings are rejected with `ERR_APPEAL_WINDOW_CLOSED`."

        Design: Corner/state_machines/appeal_paid_assessment_rejected
        """
        account = create_account(holder_name="Pumper PP-1")
        assessment = create_penalty_assessment(account["id"], "LATE_REPORT", 2026)
        paid = pay_assessment(assessment["id"], account["id"])
        assert paid["status"] == "PAID"

        resp = api.appeal_assessment(
            assessment["id"], {"grounds": "too late"},
            make_well_owner_headers(account["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_ASSESSMENT_STATE)

    def test_appeal_at_deadline_allowed_after_deadline_rejected(self, api):
        """PRD §3.6: "The owner may instead appeal an `ASSESSED` assessment by supplying `grounds`, provided the logical clock has not passed 30 days after the assessment's `created_at` — filing exactly at the deadline is allowed, and strictly later filings are rejected with `ERR_APPEAL_WINDOW_CLOSED`."

        Design: Corner/validations/appeal_at_deadline_allowed_after_deadline_rejected
        """
        # Both assessments are created at the default clock 2026-08-01T00:00:00Z,
        # so the 30-day deadline is exactly 2026-08-31T00:00:00Z.
        account = create_account(holder_name="Pumper AP-1")
        first = create_penalty_assessment(account["id"], "LATE_REPORT", 2026)
        second = create_penalty_assessment(account["id"], "LATE_REPORT", 2026)

        set_clock("2026-08-31T00:00:00Z")
        at_deadline = validate_success(
            api.appeal_assessment(first["id"], {"grounds": "at deadline"},
                                  make_well_owner_headers(account["id"]))
        )
        assert at_deadline["status"] == "APPEALED", (
            "filing exactly at created_at + 30 days must be allowed"
        )

        set_clock("2026-08-31T00:00:01Z")
        late = api.appeal_assessment(second["id"], {"grounds": "one second late"},
                                     make_well_owner_headers(account["id"]))
        validate_error(late, ApiErrorId.ERR_APPEAL_WINDOW_CLOSED)

    def test_decide_reduced_missing_amount_returns_invalid_request(self, api):
        """PRD §3.6: "`UPHELD` leaves `penalty_balance_cents` unchanged. `OVERTURNED` debits `penalty_balance_cents` by the full `amount_cents` — a full refund. `REDUCED` requires a `reduced_amount_cents` value that is strictly greater than zero and strictly less than `amount_cents` (any other value, or its absence, fails with `ERR_INVALID_REQUEST`); it debits `penalty_balance_cents` by the difference between `amount_cents` and `reduced_amount_cents` — a partial refund — and records the reduced figure on the assessment."

        Design: Corner/validations/decide_reduced_missing_amount_returns_invalid_request
        """
        account = create_account(holder_name="Pumper DR-1")
        assessment = create_and_appeal_assessment(account["id"], "LATE_REPORT", 2026)

        resp = api.decide_assessment(
            assessment["id"], {"outcome": "REDUCED"},
            make_appeals_officer_headers("ao-1"),
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


class TestSegregationOfDuties:
    def test_enforcement_officer_cannot_decide_appeal(self, api):
        """PRD §2.1: "A request whose role is well-formed but not listed among the endpoint's permitted roles is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403)."
        PRD §4: POST /penalty-assessments/{assessmentId}/decide lists only the AppealsOfficer role.

        Design: Corner/rbac/enforcement_officer_cannot_decide_appeal
        """
        account = create_account(holder_name="Pumper RB-1")
        assessment = create_and_appeal_assessment(account["id"], "LATE_REPORT", 2026)

        resp = api.decide_assessment(
            assessment["id"], {"outcome": "UPHELD"},
            make_enforcement_officer_headers("eo-9"),
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE)

    def test_assessing_user_cannot_decide_own_appeal(self, api):
        """PRD §3.6: "Segregation of duties is enforced: the decider's `X-User-ID` must differ from the assessment's `assessed_by`, or the decision is rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403)."
        PRD §2.1: "the `AppealsOfficer` who decides an appeal must not be the same `X-User-ID` that filed the assessment."

        Design: Corner/rbac/assessing_user_cannot_decide_own_appeal
        """
        account = create_account(holder_name="Pumper RB-2")
        assessment = create_penalty_assessment(account["id"], "LATE_REPORT", 2026,
                                               officer_user_id="eo-1")
        appeal_assessment(assessment["id"], account["id"], "dispute")

        same_user = api.decide_assessment(
            assessment["id"], {"outcome": "UPHELD"},
            make_appeals_officer_headers("eo-1"),
        )
        validate_error(same_user, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)

        other_user = validate_success(
            api.decide_assessment(assessment["id"], {"outcome": "UPHELD"},
                                  make_appeals_officer_headers("ao-1"))
        )
        assert other_user["status"] == "UPHELD"
        assert other_user["decided_by"] == "ao-1"
