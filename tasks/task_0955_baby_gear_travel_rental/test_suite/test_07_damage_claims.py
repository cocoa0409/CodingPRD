"""Damage claims: capture-amount computation, the dispute/reopen cycle, and
segregation of duties."""
import pytest

from test_helpers import (
    TEST_USERS,
    approve_claim,
    create_insurance_plan,
    file_damage_claim,
    get_claim,
    make_customer_headers,
    make_inspector_headers,
    make_ops_headers,
    setup_returned_reservation,
    validate_error,
    validate_success,
)


class TestDamageCaptureNestedMinMax:
    def test_insured_minor_claim_captures_deductible_only(self, api):
        """PRD 3.7: "Severity scales the base by 0.25 for `COSMETIC`, 0.60 for
        `MINOR`, or 1.00 for `MAJOR`, while `TOTAL_LOSS` is not
        severity-scaled. The assigned unit's `condition_grade` at approval time
        then scales the result by 1.0, 0.8, or 0.6 for grades `A`, `B`, `C`,
        and the product is rounded half-up to the cent."
        PRD 3.7: "Insurance then reshapes the charge if the reservation carries
        a plan and the claim's severity is among the plan's
        `covered_severities`: the customer pays the lesser of the charged
        amount and the plan's `deductible_cents`, plus any part of the charged
        amount exceeding the plan's `coverage_cap_cents` — the insurer absorbs
        the middle band between deductible and cap."

        Grade-B unit, MINOR, repair 10000 -> charged
        round_half_up(10000 x 0.60 x 0.8) = 4800; insured with deductible 1000,
        cap 20000, MINOR covered -> capture min(4800, 1000) + max(0, 4800 -
        20000) = 1000.

        Design: Difficulty/combinatorial_formula/damage_capture_nested_min_max_with_insurance
        """
        plan = create_insurance_plan(
            code="INS-NESTED",
            pricing_model="PER_DAY",
            rate_value=200,
            deductible_cents=1000,
            coverage_cap_cents=20000,
            covered_severities=["MINOR", "MAJOR"],
        )
        ctx = setup_returned_reservation(
            grade="B",
            insurance_plan_id=plan["id"],
            pickup_clock="2026-06-13T04:00:00Z",
        )
        claim = file_damage_claim(
            ctx["lines"][0]["id"],
            severity="MINOR",
            repair_cost_cents=10000,
            description="bent frame",
        )
        approved = approve_claim(claim["id"], reviewer_user_id="ops-1")
        assert approved["status"] == "APPROVED"
        assert approved["capture_amount_cents"] == 1000

    def test_uninsured_branch_captures_full_charged_amount(self, api):
        """PRD 3.7: "Without applicable coverage the customer bears the full
        charged amount."

        Same inputs as the insured branch — grade-B unit, MINOR, repair 10000 —
        but no insurance plan: capture is the full charged 4800, not the
        1000 deductible-limited figure.

        Design: Difficulty/combinatorial_formula/damage_capture_nested_min_max_with_insurance
        """
        ctx = setup_returned_reservation(
            grade="B", pickup_clock="2026-06-13T04:00:00Z"
        )
        claim = file_damage_claim(
            ctx["lines"][0]["id"],
            severity="MINOR",
            repair_cost_cents=10000,
            description="bent frame",
        )
        approved = approve_claim(claim["id"], reviewer_user_id="ops-1")
        assert approved["status"] == "APPROVED"
        assert approved["capture_amount_cents"] == 4800


class TestDamageClaimDisputeReopenCycle:
    def _setup_returned_with_claim(self):
        ctx = setup_returned_reservation(pickup_clock="2026-06-13T04:00:00Z")
        claim = file_damage_claim(
            ctx["lines"][0]["id"],
            severity="MAJOR",
            repair_cost_cents=8000,
            description="cracked shell",
        )
        return ctx, claim

    def test_deny_dispute_reopen_resets_reviewer(self, api):
        """PRD 3.7: "Denial moves the claim to `DENIED` — not terminal. The
        owning customer may dispute a denied claim, moving it to `DISPUTED`,
        and an OperationsAdmin may reopen a disputed claim back to
        `UNDER_REVIEW`, resetting `reviewed_by_user_id` to null for a fresh
        review."

        Design: Difficulty/non_linear_state_machine/damage_claim_dispute_reopen_cycle
        """
        ctx, claim = self._setup_returned_with_claim()
        denied = validate_success(
            api.deny_damage_claim(claim["id"], make_ops_headers("ops-1")), 200
        )
        assert denied["status"] == "DENIED"
        assert denied["reviewed_by_user_id"] == "ops-1"
        disputed = validate_success(
            api.dispute_damage_claim(
                claim["id"], make_customer_headers(ctx["customer"]["id"])
            ),
            200,
        )
        assert disputed["status"] == "DISPUTED"
        reopened = validate_success(
            api.reopen_damage_claim(claim["id"], make_ops_headers("ops-2")), 200
        )
        assert reopened["status"] == "UNDER_REVIEW"
        assert reopened["reviewed_by_user_id"] is None, (
            "reopen must reset reviewed_by_user_id for a fresh review"
        )

    def test_second_round_approve_computes_capture(self, api):
        """PRD 3.7: "for other severities the base is `repair_cost_cents`.
        Severity scales the base by 0.25 for `COSMETIC`, 0.60 for `MINOR`, or
        1.00 for `MAJOR`, while `TOTAL_LOSS` is not severity-scaled. The
        assigned unit's `condition_grade` at approval time then scales the
        result by 1.0, 0.8, or 0.6 for grades `A`, `B`, `C`, and the product is
        rounded half-up to the cent."

        After the DENIED -> DISPUTED -> UNDER_REVIEW loop, a fresh approve by a
        reviewer distinct from the filer succeeds and computes
        round_half_up(8000 x 1.00 x 1.0) = 8000 (grade A, uninsured).

        Design: Difficulty/non_linear_state_machine/damage_claim_dispute_reopen_cycle
        """
        ctx, claim = self._setup_returned_with_claim()
        validate_success(
            api.deny_damage_claim(claim["id"], make_ops_headers("ops-1")), 200
        )
        validate_success(
            api.dispute_damage_claim(
                claim["id"], make_customer_headers(ctx["customer"]["id"])
            ),
            200,
        )
        validate_success(
            api.reopen_damage_claim(claim["id"], make_ops_headers("ops-2")), 200
        )
        approved = validate_success(
            api.approve_damage_claim(claim["id"], make_ops_headers("ops-1")), 200
        )
        assert approved["status"] == "APPROVED"
        assert approved["capture_amount_cents"] == 8000


def test_inspector_cannot_approve_damage_claim(api):
    """PRD 2.1: "An Inspector can file damage claims and resolve cleaning
    tickets but can never approve or deny a claim."
    PRD 2.1: "A request whose role is recognized but not permitted for the
    endpoint — or that fails an entity-backed ownership check — is rejected
    with `ERR_FORBIDDEN` (HTTP 403)."

    An Inspector calling approve is rejected ERR_FORBIDDEN regardless of which
    operator id it carries; the claim stays UNDER_REVIEW.

    Design: Corner/rbac/inspector_cannot_approve_damage_claim
    """
    ctx = setup_returned_reservation(pickup_clock="2026-06-13T04:00:00Z")
    claim = file_damage_claim(
        ctx["lines"][0]["id"],
        severity="MINOR",
        repair_cost_cents=5000,
        description="scratch",
    )
    res = api.approve_damage_claim(claim["id"], make_inspector_headers("insp-2"))
    validate_error(res, "ERR_FORBIDDEN", expected_status=403)
    assert get_claim(claim["id"])["status"] == "UNDER_REVIEW"


def test_segregation_of_duties_same_user_rejected(api):
    """PRD 3.7: "Segregation of duties binds both approval and denial: the
    reviewing operator's `X-User-ID` must differ from `filed_by_user_id`, else
    `ERR_SEGREGATION_OF_DUTIES`."
    PRD 2.1: "Segregation of duties still applies to an OperationsAdmin who
    filed a damage claim: that same id cannot later approve or deny it."

    The admin who filed the claim (ops-9) cannot approve it as ops-9; a
    different admin (ops-1) can.

    Design: Corner/rbac/segregation_of_duties_same_user_rejected
    """
    ctx = setup_returned_reservation(pickup_clock="2026-06-13T04:00:00Z")
    claim = file_damage_claim(
        ctx["lines"][0]["id"],
        severity="MINOR",
        repair_cost_cents=5000,
        description="bent bar",
        filer_headers=make_ops_headers("ops-9"),
    )
    res = api.approve_damage_claim(claim["id"], make_ops_headers("ops-9"))
    validate_error(res, "ERR_SEGREGATION_OF_DUTIES", expected_status=403)
    approved = validate_success(
        api.approve_damage_claim(claim["id"], make_ops_headers("ops-1")), 200
    )
    assert approved["status"] == "APPROVED"
    assert approved["reviewed_by_user_id"] == "ops-1"
