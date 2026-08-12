"""Compensating invariants and boundary metrics: the posted-credit ledger,
active-equivalency cardinality, and the PLA cap boundary."""
import pytest

from test_helpers import (
    validate_error,
    get_success_data,
    api_client,
    ApiErrorId,
    TEST_USERS,
    create_transcript_course_payload,
    fixtures,
)

ADMIN = TEST_USERS["admin_headers"]
EVALUATOR = TEST_USERS["evaluator_headers"]
EVAL_A = fixtures.EVAL_A
EVAL_B = fixtures.EVAL_B


class TestPostReopenConservesPostedCreditTotal:
    def _setup_posted(self):
        return fixtures.setup_posted_evaluation(
            course_kwargs={"code": "MATH-150", "credit_hours": 4.0, "department": "MATH"},
            equivalency_kwargs={"external_course_code": "M-101", "external_credit_hours": 4.0},
            transcript_courses=[create_transcript_course_payload(
                external_course_code="M-101", title="Calc", credit_hours=4.0, grade="A")],
        )

    def test_post_adds_exactly_waterfall_sum(self):
        """PRD §3.6: "The student's `total_posted_transfer_credits` is, at all
        times, exactly the sum of `applied_credits` over that student's lines
        currently in `POSTED`; a post adds exactly its waterfall sum and the
        paired reopen subtracts exactly the same amount."

        Design: Difficulty/compensating_invariant/post_reopen_conserves_posted_credit_total
        """
        ctx = self._setup_posted()
        student = get_success_data(api_client.get_student(ctx["student"]["id"], EVALUATOR))
        assert student["total_posted_transfer_credits"] == pytest.approx(4.0, abs=1e-9), (
            "post added exactly sum(applied_credits) == 4.0"
        )

        lines = get_success_data(api_client.list_line_items(
            EVALUATOR, params={"evaluation_id": ctx["evaluation"]["id"], "status": "POSTED"}
        ))
        assert sum(l["applied_credits"] for l in lines) == pytest.approx(
            student["total_posted_transfer_credits"], abs=1e-9
        ), "ledger invariant: student total equals sum of POSTED applied_credits"

    def test_reopen_restores_pre_post_total_and_deletes_applications(self):
        """PRD §2.10: "Posted credit is likewise compensable — reopening an
        evaluation removes exactly the credit its posting added, so the student's
        posted totals after a paired post-and-reopen equal the totals before it
        whenever no other writes intervened."
        PRD §3.6: "all `RequirementApplication` rows belonging to the evaluation
        are deleted".

        Design: Difficulty/compensating_invariant/post_reopen_conserves_posted_credit_total
        """
        ctx = self._setup_posted()
        student_id = ctx["student"]["id"]
        before = get_success_data(api_client.get_student(student_id, EVALUATOR))
        assert before["total_posted_transfer_credits"] == pytest.approx(4.0, abs=1e-9)

        get_success_data(api_client.reopen_evaluation(
            ctx["evaluation"]["id"], {"reason": "Recheck requested"}, EVALUATOR
        ))

        after = get_success_data(api_client.get_student(student_id, EVALUATOR))
        assert after["total_posted_transfer_credits"] == pytest.approx(0.0, abs=1e-9), (
            "paired post+reopen conserves the ledger at its pre-post value"
        )
        rows = get_success_data(api_client.list_requirement_applications(
            EVALUATOR, params={"student_id": student_id}
        ))
        assert rows == [], "requirement applications deleted by reopen compensation"


class TestSuspendReactivateConservesActiveEquivalencyCount:
    def _setup_two_equivalencies(self):
        partner = fixtures.create_partner(name="Count College", code="CT")
        c1 = fixtures.create_course(code="MATH-150", credit_hours=4.0, department="MATH")
        c2 = fixtures.create_course(code="ENGL-150", title="Literature", credit_hours=3.0,
                                    department="ENGL")
        agreement = fixtures.create_agreement(partner["id"])
        fixtures.activate_agreement(agreement["id"])
        eq1 = fixtures.add_equivalency(agreement["id"], c1["id"], "MATH-101",
                                       external_title="Calc", external_credit_hours=4.0)
        eq2 = fixtures.add_equivalency(agreement["id"], c2["id"], "ENGL-101",
                                       external_title="Lit", external_credit_hours=3.0)
        return agreement, eq1, eq2

    def _active_count(self, agreement_id):
        rows = get_success_data(api_client.list_course_equivalencies(
            ADMIN, params={"agreement_id": agreement_id, "status": "ACTIVE"}
        ))
        return len(rows)

    def test_suspend_reactivate_restores_exact_set(self):
        """PRD §2.10: "when a suspended agreement is reactivated, exactly the set
        of equivalencies that was inactivated by the paired suspension is
        restored — the count of `ACTIVE` equivalencies immediately after
        reactivation equals the count immediately before the suspension."

        Design: Difficulty/compensating_invariant/suspend_reactivate_conserves_active_equivalency_count
        """
        agreement, eq1, eq2 = self._setup_two_equivalencies()
        count_before = self._active_count(agreement["id"])
        assert count_before == 2

        get_success_data(api_client.suspend_agreement(agreement["id"], ADMIN))
        assert self._active_count(agreement["id"]) == 0
        for eq in (eq1, eq2):
            stored = get_success_data(api_client.get_course_equivalency(eq["id"], ADMIN))
            assert stored["status"] == "INACTIVE"

        get_success_data(api_client.reactivate_agreement(agreement["id"], ADMIN))
        count_after = self._active_count(agreement["id"])
        assert count_after == count_before == 2
        for eq in (eq1, eq2):
            stored = get_success_data(api_client.get_course_equivalency(eq["id"], ADMIN))
            assert stored["status"] == "ACTIVE"

    def test_suspend_flips_all_active_equivalencies_inactive(self):
        """PRD §3.2: "every equivalency of the agreement in `ACTIVE` becomes
        `INACTIVE`".

        Design: Difficulty/compensating_invariant/suspend_reactivate_conserves_active_equivalency_count
        """
        agreement, eq1, eq2 = self._setup_two_equivalencies()
        get_success_data(api_client.suspend_agreement(agreement["id"], ADMIN))

        stored1 = get_success_data(api_client.get_course_equivalency(eq1["id"], ADMIN))
        stored2 = get_success_data(api_client.get_course_equivalency(eq2["id"], ADMIN))
        assert stored1["status"] == "INACTIVE"
        assert stored2["status"] == "INACTIVE"
        agreement_after = fixtures.get_agreement(agreement["id"])
        assert agreement_after["status"] == "SUSPENDED"


class TestPlaCapExactThirtyBoundary:
    def test_crediting_to_exactly_cap_allowed(self):
        """PRD §3.8: "the student's lifetime prior-learning credit is bounded at
        30.0, and the credit is allowed exactly when the student's current
        `total_posted_pla_credits` plus the `verified_credits` does not exceed
        that bound — landing exactly on 30.0 is permitted".

        Design: Difficulty/boundary_precision_check/pla_cap_exact_thirty_boundary
        """
        student, pla1 = fixtures.setup_student_with_credited_pla(credits=24.0)
        pla2 = fixtures.create_pla(student["id"], claimed_credits=6.0, source_type="CLEP",
                                   credential_ref="CLEP-2")
        fixtures.verify_pla(pla2["id"], 6.0)

        credited = fixtures.credit_pla(pla2["id"])
        assert credited["status"] == "CREDITED", "24.0 + 6.0 == 30.0 lands exactly on the cap"
        stored = get_success_data(api_client.get_student(student["id"], EVALUATOR))
        assert stored["total_posted_pla_credits"] == pytest.approx(30.0, abs=1e-9)

    def test_beyond_cap_rejected(self):
        """PRD §3.8: "anything beyond fails with `ERR_PLA_CAP_EXCEEDED`
        (HTTP 422)".

        Design: Difficulty/boundary_precision_check/pla_cap_exact_thirty_boundary
        """
        student, pla1 = fixtures.setup_student_with_credited_pla(credits=24.0)
        pla2 = fixtures.create_pla(student["id"], claimed_credits=6.0, source_type="CLEP",
                                   credential_ref="CLEP-2")
        fixtures.verify_pla(pla2["id"], 6.0)
        fixtures.credit_pla(pla2["id"])

        pla3 = fixtures.create_pla(student["id"], claimed_credits=1.0, source_type="AP",
                                   credential_ref="AP-3")
        fixtures.verify_pla(pla3["id"], 1.0)
        resp = api_client.credit_pla(pla3["id"], EVALUATOR)
        validate_error(resp, ApiErrorId.ERR_PLA_CAP_EXCEEDED)

        stored = get_success_data(api_client.get_student(student["id"], EVALUATOR))
        assert stored["total_posted_pla_credits"] == pytest.approx(30.0, abs=1e-9)
        pla3_after = get_success_data(api_client.get_pla(pla3["id"], EVALUATOR))
        assert pla3_after["status"] == "VERIFIED"
