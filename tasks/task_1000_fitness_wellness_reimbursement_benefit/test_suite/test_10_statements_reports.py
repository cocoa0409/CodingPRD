"""Statement lifecycle, provisional/final totals, and utilization reporting."""
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    create_statement,
    get_success_data,
    standard_world,
    submit_approved_claim,
    submit_claim,
    submit_paid_claim,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["benefits_admin_headers"]
AUDITOR = TEST_USERS["auditor_headers"]
REVIEWER = TEST_USERS["claims_reviewer_headers"]


class TestStatementProvisionalVsFinal:
    """Claim A: 3000 PAID; claim B: 2000 SUBMITTED; claim C: 1500 APPROVED
    UNPAID — all with May 2026 service dates."""

    def _setup(self, api):
        world = standard_world()
        submit_paid_claim(world, 3000, "R-A")
        submit_claim(world, 2000, "R-B", service_date="2026-05-03T10:00:00Z")
        submit_approved_claim(world, 1500, "R-C", service_date="2026-05-04T10:00:00Z")
        return world

    def test_provisional_includes_open_and_unpaid(self, api):
        """PRD §3.9: "Creating a statement with `member_id` and
        `period_yyyymm` opens an `OPEN` statement whose `claim_count` tallies
        the member's claims with `service_date` inside that month and whose
        `provisional_total_cents` looks forward: the claimed amounts of claims
        still in `SUBMITTED`, `UNDER_REVIEW`, or `NEEDS_INFO`, plus the
        approved amounts of claims `APPROVED` and still `UNPAID`, plus the
        approved amounts of claims `PAID`, minus the approved amounts of
        claims `CLAWED_BACK` whose payment fell inside the period"

        Design: Difficulty/dual_variant_calc/statement_provisional_vs_final
        """
        world = self._setup(api)
        statement = create_statement(world["member"]["id"], "2026-05")
        assert statement["provisional_total_cents"] == 6500, (
            f"2000 claimed + 1500 approved-unpaid + 3000 paid = 6500, got {statement['provisional_total_cents']}"
        )
        assert statement["claim_count"] == 3
        assert statement["status"] == "OPEN"

    def test_final_counts_paid_only(self, api):
        """PRD §3.9: "Finalizing moves `OPEN → FINALIZED` (any other state
        yields `ERR_STATEMENT_NOT_OPEN`) and computes `finalized_total_cents`
        on stricter terms: the approved amounts of claims `PAID` with payment
        inside the period, minus the approved amounts of claims `CLAWED_BACK`
        with payment inside the period."
        PRD §3.9: "On identical data the final total is never higher than the
        provisional one."

        Design: Difficulty/dual_variant_calc/statement_provisional_vs_final
        """
        world = self._setup(api)
        statement = create_statement(world["member"]["id"], "2026-05")
        finalized = validate_success(api.finalize_statement(statement["id"], ADMIN))
        assert finalized["finalized_total_cents"] == 3000, (
            f"final counts PAID only = 3000, got {finalized['finalized_total_cents']}"
        )
        assert finalized["finalized_total_cents"] <= statement["provisional_total_cents"]
        assert finalized["finalized_total_cents"] != statement["provisional_total_cents"]


class TestStatementFinalizeReopenCycle:
    def _setup(self, api):
        world = standard_world()
        submit_paid_claim(world, 3000, "R-S")
        statement = create_statement(world["member"]["id"], "2026-05")
        validate_success(api.finalize_statement(statement["id"], ADMIN))
        return world, statement

    def test_reopen_clears_finalized_total(self, api):
        """PRD §3.9: "Reopening moves `FINALIZED → OPEN` (otherwise
        `ERR_STATEMENT_NOT_FINALIZED`), resets `finalized_total_cents` to
        null, recomputes the provisional total, and accepts an optional
        `reason`."

        Design: Difficulty/non_linear_state_machine/statement_finalize_reopen_cycle
        """
        world, statement = self._setup(api)
        reopened = validate_success(api.reopen_statement(statement["id"], ADMIN, {"reason": "correction"}))
        assert reopened["status"] == "OPEN"
        assert reopened["finalized_total_cents"] is None, (
            f"reopen must reset finalized_total_cents to null, got {reopened['finalized_total_cents']}"
        )
        assert reopened["provisional_total_cents"] == 3000

    def test_refinalize_recomputes_final_total(self, api):
        """PRD §3.9: "Finalizing moves `OPEN → FINALIZED` (any other state
        yields `ERR_STATEMENT_NOT_OPEN`) and computes `finalized_total_cents`
        on stricter terms: the approved amounts of claims `PAID` with payment
        inside the period, minus the approved amounts of claims `CLAWED_BACK`
        with payment inside the period."

        Design: Difficulty/non_linear_state_machine/statement_finalize_reopen_cycle
        """
        world, statement = self._setup(api)
        validate_success(api.reopen_statement(statement["id"], ADMIN, {"reason": "correction"}))
        refinalized = validate_success(api.finalize_statement(statement["id"], ADMIN))
        assert refinalized["status"] == "FINALIZED"
        assert refinalized["finalized_total_cents"] == 3000, (
            f"re-finalize after reopen must recompute 3000, got {refinalized['finalized_total_cents']}"
        )


def test_statement_reopen_delivered_rejected(api, admin_headers):
    """PRD §3.9: "`DELIVERED` is terminal and refuses any further transition
    with `ERR_STATEMENT_LOCKED`."

    Design: Corner/state_machines/statement_reopen_delivered_rejected
    """
    world = standard_world()
    statement = create_statement(world["member"]["id"], "2026-05")
    validate_success(api.finalize_statement(statement["id"], ADMIN))
    validate_success(api.deliver_statement(statement["id"], ADMIN))

    resp = api.reopen_statement(statement["id"], ADMIN, {"reason": "too late"})
    validate_error(resp, ApiErrorId.ERR_STATEMENT_LOCKED)
    after = get_success_data(api.get_statement(statement["id"], admin_headers))
    assert after["status"] == "DELIVERED"


def test_utilization_report_math(api, auditor_headers):
    """PRD §3.9: "Over the employer's enrollments in `ACTIVE`, `EXHAUSTED`, or
    `CLOSED`, it aggregates `total_allowance_cents` and `total_used_cents`;
    `enrolled_members` counts those enrollments; `utilization_pct` is one
    hundred times the total used divided by the total allowance, rounded half
    up to two decimal places, and is zero when the total allowance is zero.
    The report also returns `paid_claim_count` — claims with `payment_status`
    `PAID` whose payment fell inside the period month — and
    `open_fraud_flags`, the count of `OPEN` fraud flags on visits and claims
    of the employer's members."

    Design: Corner/calculations/utilization_report_math
    """
    world = standard_world()
    submit_paid_claim(world, 3000, "R-U")

    resp = api.get_utilization_report(auditor_headers, params={
        "employer_id": world["employer"]["id"], "period_yyyymm": "2026-05",
    })
    report = validate_success(resp)
    assert report["total_allowance_cents"] == 30000
    assert report["total_used_cents"] == 3000
    assert report["utilization_pct"] == pytest.approx(10.0, abs=0.001), (
        f"round_half_up(100 * 3000 / 30000, 2) = 10.0, got {report['utilization_pct']}"
    )
    assert report["paid_claim_count"] == 1
    assert report["enrolled_members"] == 1
    assert report["open_fraud_flags"] == 0
