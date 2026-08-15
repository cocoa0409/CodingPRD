"""Recruitment fee reviews: FX rounding, the reimbursement ledger, link gates."""
from test_helpers import (
    OFFICER,
    ApiErrorId,
    assert_fee_review,
    assert_reimbursement,
    assert_reimbursement_balance,
    confirm_violation,
    create_fee_review,
    create_facility,
    fee_item,
    file_grievance,
    get_review,
    make_auditor_headers,
    record_reimbursement,
    resolve_grievance,
    setup_confirmed_review,
    setup_in_progress_audit,
    validate_error,
    validate_success,
)


def three_bdt_review(supplier_name="Coral Foods Co"):
    """IN_PROGRESS audit plus a fee review of three 300-BDT items."""
    ctx = setup_in_progress_audit(supplier_name=supplier_name, sector="FOOD",
                                  facility_name="Fresno Plant")
    items = [fee_item(worker_ref=f"W{i}") for i in (1, 2, 3)]
    review = create_fee_review(
        ctx["audit"]["id"], ctx["auditor"]["id"], workers_assessed=3,
        fee_items=items,
    )
    ctx["review"] = review
    return ctx


class TestFeeReviewRounding:
    def test_fee_review_per_item_rounding_then_sum(self, api):
        """PRD §3.8: "Each fee item is converted at the program's
        USD-cents-per-minor-unit rates — USD 1.0, EUR 1.08, INR 0.012, BDT
        0.0115 — and each line is rounded half up to whole cents first;
        `total_reimbursement_cents` is the sum of those rounded lines. The
        rounding order is pinned — per-item rounding, then summation — because
        the two orders diverge: three items of 300 BDT minor units convert to
        3.45 cents each, round to 3 cents each, and total 9, whereas summing
        first would round 10.35 to 10."
        PRD §3.8: "Otherwise it starts `PENDING_CONFIRMATION` with
        `reimbursed_cents` at 0 and `outstanding_reimbursement_cents` equal to
        the total."

        Design: Difficulty/combinatorial_formula/recruitment_fee_per_item_rounding_then_sum
        """
        ctx = three_bdt_review()
        review = ctx["review"]
        assert_fee_review(review)
        # Per-item round_half_up(300 * 0.0115) = 3; total 3+3+3 = 9.
        assert review["total_reimbursement_cents"] == 9, (
            "per-item rounding then summation; the sum-then-round order would "
            "yield 10 and is the rejected alternative"
        )
        assert review["reimbursed_cents"] == 0
        assert review["outstanding_reimbursement_cents"] == 9
        assert review["status"] == "PENDING_CONFIRMATION"

    def test_fee_review_total_consistent_on_reread(self, api):
        """PRD §2.10: "Consistency is immediate: every cascade and recompute
        described in §3 completes synchronously within the triggering request"
        PRD §3.8: "the conserved quantity holds at all times:
        `total_reimbursement_cents` always equals `reimbursed_cents` plus
        `outstanding_reimbursement_cents`."

        Design: Difficulty/combinatorial_formula/recruitment_fee_per_item_rounding_then_sum
        """
        ctx = three_bdt_review()
        reread = get_review(ctx["review"]["id"])
        assert reread["total_reimbursement_cents"] == 9, (
            "an independent read returns the same per-item-rounded total"
        )
        assert_reimbursement_balance(reread)
        assert reread["status"] == "PENDING_CONFIRMATION"


class TestReimbursementLedger:
    def test_reimbursement_balance_conservation_on_record(self, api):
        """PRD §3.8: "A new reimbursement is `RECORDED`; the review's
        `reimbursed_cents` is the sum of its `RECORDED` payments and its
        `outstanding_reimbursement_cents` is the total minus the reimbursed
        sum. When a recorded payment brings the outstanding balance to exactly
        zero, the review advances automatically to `REIMBURSED`, which is
        terminal."
        PRD §3.8: "the conserved quantity holds at all times:
        `total_reimbursement_cents` always equals `reimbursed_cents` plus
        `outstanding_reimbursement_cents`."

        Design: Difficulty/compensating_invariant/reimbursement_balance_conservation_on_reverse
        """
        ctx = setup_confirmed_review(num_items=3, supplier_name="Romeo Foods",
                                     facility_name="Modesto Plant")
        review = ctx["review"]
        assert review["total_reimbursement_cents"] == 9
        assert review["outstanding_reimbursement_cents"] == 9

        reb1 = record_reimbursement(review["id"], 5, worker_ref="W1")
        assert_reimbursement(reb1)
        assert reb1["status"] == "RECORDED"
        step1 = get_review(review["id"])
        assert (step1["reimbursed_cents"],
                step1["outstanding_reimbursement_cents"]) == (5, 4)
        assert_reimbursement_balance(step1)
        assert step1["status"] == "VIOLATION_CONFIRMED"

        reb2 = record_reimbursement(review["id"], 4, worker_ref="W2")
        assert_reimbursement(reb2)
        step2 = get_review(review["id"])
        assert (step2["reimbursed_cents"],
                step2["outstanding_reimbursement_cents"]) == (9, 0)
        assert_reimbursement_balance(step2)
        assert step2["status"] == "REIMBURSED", (
            "outstanding hits exactly zero: the review auto-advances"
        )

    def test_reimbursement_reverse_restores_balance(self, api):
        """PRD §3.8: "A `ComplianceOfficer` may reverse a reimbursement that is
        `RECORDED` (`ERR_REIMBURSEMENT_INVALID_STATE` otherwise), moving it to
        `REVERSED`, which is terminal. The review's reimbursed sum decreases and
        its outstanding sum increases by the reversed `amount_cents`, and if the
        review had already reached `REIMBURSED` it drops back to
        `VIOLATION_CONFIRMED` because money is owed again. Recording and
        reversing thus restore the same balance"

        Design: Difficulty/compensating_invariant/reimbursement_balance_conservation_on_reverse
        """
        ctx = setup_confirmed_review(num_items=3, supplier_name="Romeo Foods",
                                     facility_name="Modesto Plant")
        review = ctx["review"]
        record_reimbursement(review["id"], 5, worker_ref="W1")
        reb2 = record_reimbursement(review["id"], 4, worker_ref="W2")
        assert get_review(review["id"])["status"] == "REIMBURSED"

        reversed_reb = validate_success(
            api.reverse_reimbursement(reb2["id"], OFFICER)
        )
        assert reversed_reb["status"] == "REVERSED"
        step3 = get_review(review["id"])
        assert (step3["reimbursed_cents"],
                step3["outstanding_reimbursement_cents"]) == (5, 4), (
            "reversal restores the pre-payment balance"
        )
        assert_reimbursement_balance(step3)
        assert step3["status"] == "VIOLATION_CONFIRMED", (
            "REIMBURSED drops back once money is owed again"
        )


class TestReviewLifecycleGuards:
    def test_review_cleared_on_empty_fee_items(self, api):
        """PRD §3.8: "When `fee_items` is empty, no fees were found and the
        review is created directly in `CLEARED`, which is terminal."

        Design: Corner/state_machines/review_cleared_on_empty_fee_items
        """
        ctx = setup_in_progress_audit(supplier_name="Hotel Goods", sector="FOOD",
                                      facility_name="Site O")
        review = create_fee_review(
            ctx["audit"]["id"], ctx["auditor"]["id"], workers_assessed=5,
            fee_items=[],
        )
        assert_fee_review(review)
        assert review["status"] == "CLEARED"
        assert review["total_reimbursement_cents"] == 0

    def test_duplicate_fee_review_rejected(self, api):
        """PRD §3.8: "The assigned auditor records the audit's fee review —
        again exactly one per audit, with a second attempt rejected as
        `ERR_RECORD_ALREADY_EXISTS`"

        Design: Corner/validations/duplicate_fee_review_rejected
        """
        ctx = setup_in_progress_audit(supplier_name="Whiskey B", sector="FOOD",
                                      facility_name="Site B2")
        first = create_fee_review(
            ctx["audit"]["id"], ctx["auditor"]["id"], workers_assessed=2,
            fee_items=[],
        )
        resp = api.create_recruitment_fee_review(
            ctx["audit"]["id"],
            {"workers_assessed": 3, "fee_items": []},
            make_auditor_headers(ctx["auditor"]["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_RECORD_ALREADY_EXISTS, 409)
        assert get_review(first["id"])["status"] == "CLEARED", (
            "the first review is unchanged"
        )

    def test_confirm_violation_twice_rejected(self, api):
        """PRD §3.8: "Confirmation belongs to a `ComplianceOfficer` and is valid
        only from `PENDING_CONFIRMATION` (`ERR_REVIEW_INVALID_STATE`)."

        Design: Corner/validations/confirm_twice_review_rejected
        """
        ctx = setup_in_progress_audit(supplier_name="India C", sector="FOOD",
                                      facility_name="Site P2")
        review = create_fee_review(
            ctx["audit"]["id"], ctx["auditor"]["id"], workers_assessed=1,
            fee_items=[fee_item()],
        )
        confirmed = confirm_violation(review["id"])
        assert confirmed["status"] == "VIOLATION_CONFIRMED"
        resp = api.confirm_fee_violation(review["id"], OFFICER)
        validate_error(resp, ApiErrorId.ERR_REVIEW_INVALID_STATE, 409)

    def test_reimbursement_amount_guardrails(self, api):
        """PRD §3.8: "giving an `amount_cents` that must be greater than zero
        (`ERR_INVALID_REQUEST`) and no more than the review's current
        `outstanding_reimbursement_cents`
        (`ERR_REIMBURSEMENT_EXCEEDS_OUTSTANDING`, 422)"

        Design: Corner/validations/reimbursement_exceeds_outstanding_rejected
        """
        ctx = setup_confirmed_review(num_items=1, supplier_name="Juliet C",
                                     facility_name="Site O2")
        review = ctx["review"]
        assert review["outstanding_reimbursement_cents"] == 3

        over = api.create_reimbursement(
            review["id"], {"amount_cents": 10, "worker_ref": "W1"}, OFFICER
        )
        validate_error(over, ApiErrorId.ERR_REIMBURSEMENT_EXCEEDS_OUTSTANDING,
                       422)
        zero = api.create_reimbursement(
            review["id"], {"amount_cents": 0, "worker_ref": "W1"}, OFFICER
        )
        validate_error(zero, ApiErrorId.ERR_INVALID_REQUEST, 400)

        after = get_review(review["id"])
        assert after["outstanding_reimbursement_cents"] == 3, (
            "rejected payments leave the ledger untouched"
        )
        assert after["reimbursed_cents"] == 0

    def test_reverse_already_reversed_rejected(self, api):
        """PRD §3.8: "A `ComplianceOfficer` may reverse a reimbursement that is
        `RECORDED` (`ERR_REIMBURSEMENT_INVALID_STATE` otherwise), moving it to
        `REVERSED`, which is terminal."

        Design: Corner/validations/reverse_already_reversed_rejected
        """
        ctx = setup_confirmed_review(num_items=1, supplier_name="Kilo C",
                                     facility_name="Site N2")
        review = ctx["review"]
        reb = record_reimbursement(review["id"], 3, worker_ref="W1")
        reversed_reb = validate_success(
            api.reverse_reimbursement(reb["id"], OFFICER)
        )
        assert reversed_reb["status"] == "REVERSED"
        resp = api.reverse_reimbursement(reb["id"], OFFICER)
        validate_error(resp, ApiErrorId.ERR_REIMBURSEMENT_INVALID_STATE, 409)


class TestLinkedGrievanceGates:
    def mismatched_unresolved_scenario(self):
        """Grievance filed at facility Two (SUBMITTED, HIGH); a review on
        facility One's audit links to it."""
        ctx = setup_in_progress_audit(supplier_name="Juliet Goods",
                                      sector="HARDLINES",
                                      facility_name="Facility One")
        fac_two = create_facility(ctx["supplier"]["id"], name="Facility Two")
        grievance = file_grievance(
            fac_two["id"], category="RECRUITMENT_FEES", severity="HIGH",
            description="Agents charged fees",
        )
        review = create_fee_review(
            ctx["audit"]["id"], ctx["auditor"]["id"], workers_assessed=2,
            fee_items=[fee_item()], linked_grievance_id=grievance["id"],
        )
        assert review["status"] == "PENDING_CONFIRMATION"
        return ctx, grievance, review

    def test_safety_error_beats_referential_on_confirm(self, api):
        """PRD §3.8: "When a `linked_grievance_id` is set, two guards apply in a
        fixed order: the linked grievance must already be `RESOLVED`
        (`ERR_LINKED_GRIEVANCE_UNRESOLVED`) — this safety check outranks the
        second guard — and the grievance's `facility_id` must equal the facility
        of the review's audit (`ERR_GRIEVANCE_FACILITY_MISMATCH`, 400)."
        The linked grievance below is both unresolved AND attached to a
        different facility; the safety error must surface.

        Design: Difficulty/priority_pair_validation_conflict/safety_beats_referential_on_unresolved_mismatched_grievance
        """
        ctx, grievance, review = self.mismatched_unresolved_scenario()
        resp = api.confirm_fee_violation(review["id"], OFFICER)
        validate_error(resp, ApiErrorId.ERR_LINKED_GRIEVANCE_UNRESOLVED, 409)

    def test_unresolved_mismatched_link_leaves_review_pending(self, api):
        """PRD §3.8: "the linked grievance must already be `RESOLVED`
        (`ERR_LINKED_GRIEVANCE_UNRESOLVED`) — this safety check outranks the
        second guard"
        PRD §3.8: "Confirmation moves the review to `VIOLATION_CONFIRMED`" — a
        rejected confirmation performs no such move.

        Design: Difficulty/priority_pair_validation_conflict/safety_beats_referential_on_unresolved_mismatched_grievance
        """
        ctx, grievance, review = self.mismatched_unresolved_scenario()
        resp = api.confirm_fee_violation(review["id"], OFFICER)
        validate_error(resp, ApiErrorId.ERR_LINKED_GRIEVANCE_UNRESOLVED)
        assert get_review(review["id"])["status"] == "PENDING_CONFIRMATION", (
            "the failed confirmation leaves the review untouched"
        )
        grievance_after = validate_success(
            api.get_grievance(grievance["id"], OFFICER)
        )
        assert grievance_after["status"] == "SUBMITTED"

    def test_grievance_facility_mismatch_on_resolved_link(self, api):
        """PRD §3.8: "and the grievance's `facility_id` must equal the facility
        of the review's audit (`ERR_GRIEVANCE_FACILITY_MISMATCH`, 400)."

        Design: Corner/validations/grievance_facility_mismatch_on_resolved_link_rejected
        """
        ctx = setup_in_progress_audit(supplier_name="November C", sector="FOOD",
                                      facility_name="Site A3")
        fac_b = create_facility(ctx["supplier"]["id"], name="Site B3")
        grievance = file_grievance(
            fac_b["id"], category="RECRUITMENT_FEES", severity="MEDIUM",
            description="Fee complaint",
        )
        resolve_grievance(grievance["id"], resolution_note="Worker repaid")
        review = create_fee_review(
            ctx["audit"]["id"], ctx["auditor"]["id"], workers_assessed=1,
            fee_items=[fee_item()], linked_grievance_id=grievance["id"],
        )
        resp = api.confirm_fee_violation(review["id"], OFFICER)
        validate_error(resp, ApiErrorId.ERR_GRIEVANCE_FACILITY_MISMATCH, 400)
