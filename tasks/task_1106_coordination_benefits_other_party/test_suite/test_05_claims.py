"""Claim adjudication payment-position arithmetic and adjudication gating
(PRD §3.6)."""
from test_helpers import (
    TEST_USERS,
    assert_claim,
    create_claim_line_payload,
    create_claim_payload,
    create_config,
    create_member,
    create_provider,
    create_verified_coverage,
    draft_and_finalize_determination,
    draft_determination,
    get_success_data,
    setup_member_with_our_plan,
    setup_member_with_our_plan_and_group,
    setup_secondary_position_claim,
    validate_error,
    validate_paginated,
    validate_success,
)

COB = TEST_USERS["cob_analyst_headers"]
EXAMINER = TEST_USERS["claims_examiner_headers"]


class TestSecondaryPaymentPosition:
    def test_secondary_adjudication_pays_residual_after_primary(self, api):
        """PRD §3.6: "each line's `paid_cents` is the greater of zero and the
        amount by which the lesser of `allowed_cents` and `billed_cents` exceeds
        the line's `primary_paid_cents` — the plan pays the residual after the
        primary's payment, capped at what it would have paid as primary."
        allowed 80000 - primary_paid 50000 = 30000.

        Design: Difficulty/dual_variant_calc/provisional_vs_final_secondary_on_claimline
        """
        ctx = setup_secondary_position_claim(
            line_specs=[dict(billed_cents=100000, allowed_cents=80000,
                             primary_paid_cents=50000)]
        )
        claim = ctx["claim"]
        assert_claim(claim)
        assert claim["status"] == "ADJUDICATED"
        assert claim["total_paid_cents"] == 30000
        assert claim["total_primary_paid_cents"] == 50000

    def test_secondary_adjudication_line_level_and_determination_link(self, api):
        """PRD §3.6: "Adjudication records that determination's `id` on the claim
        and computes each line's `paid_cents`" and "this provisional pass uses
        the `primary_paid_cents` supplied on the line by the provider or
        remittance".

        Design: Difficulty/dual_variant_calc/provisional_vs_final_secondary_on_claimline
        """
        ctx = setup_secondary_position_claim(
            line_specs=[dict(billed_cents=100000, allowed_cents=80000,
                             primary_paid_cents=50000)]
        )
        claim = ctx["claim"]
        assert claim["primacy_determination_id"] == ctx["determination"]["id"]

        lines, _ = validate_paginated(api.list_claim_lines(claim["id"], EXAMINER))
        assert len(lines) == 1
        assert lines[0]["paid_cents"] == 30000
        assert lines[0]["primary_paid_cents"] == 50000


class TestPerLineThenSumRounding:
    def test_secondary_totals_are_sums_of_per_line_amounts(self, api):
        """PRD §3.6: "Claim totals are the sums across lines: `total_paid_cents`
        over `paid_cents`, `total_primary_paid_cents` over `primary_paid_cents`,
        and `total_allowed_cents` over `allowed_cents`, again rounded per line
        then summed, with the sum never re-rounded." Lines pay 3000, 6001, 8002.

        Design: Difficulty/combinatorial_formula/secondary_payment_per_line_rounding_then_sum
        """
        ctx = setup_secondary_position_claim(line_specs=[
            dict(billed_cents=10001, allowed_cents=8001, primary_paid_cents=5001,
                 procedure_code="A"),
            dict(billed_cents=20002, allowed_cents=15002, primary_paid_cents=9001,
                 procedure_code="B"),
            dict(billed_cents=30003, allowed_cents=25003, primary_paid_cents=17001,
                 procedure_code="C"),
        ])
        claim = ctx["claim"]
        assert claim["total_paid_cents"] == 17003
        assert claim["total_allowed_cents"] == 48006
        assert claim["total_primary_paid_cents"] == 31003

    def test_secondary_per_line_paid_values(self, api):
        """PRD §2.5: "Payment mathematics are performed per claim line and
        rounded half-up to integer cents on each line; claim-level totals are
        then formed by summing the already-rounded line values, and a sum is
        never re-rounded."

        Design: Difficulty/combinatorial_formula/secondary_payment_per_line_rounding_then_sum
        """
        ctx = setup_secondary_position_claim(line_specs=[
            dict(billed_cents=10001, allowed_cents=8001, primary_paid_cents=5001,
                 procedure_code="A"),
            dict(billed_cents=20002, allowed_cents=15002, primary_paid_cents=9001,
                 procedure_code="B"),
            dict(billed_cents=30003, allowed_cents=25003, primary_paid_cents=17001,
                 procedure_code="C"),
        ])
        lines, _ = validate_paginated(api.list_claim_lines(ctx["claim"]["id"], EXAMINER))
        by_number = {line["line_number"]: line for line in lines}
        assert by_number[1]["paid_cents"] == 3000
        assert by_number[2]["paid_cents"] == 6001
        assert by_number[3]["paid_cents"] == 8002


class TestAdjudicationGating:
    def test_adjudicate_with_only_draft_determination_rejected(self, api):
        """PRD §3.6: "requires exactly one `FINALIZED` primacy determination to
        exist for the member and service date — if none or several match,
        adjudication is rejected with `ERR_NO_FINAL_PRIMACY` (HTTP 422)." A DRAFT
        determination is not FINALIZED, so none matches.

        Design: Difficulty/cross_entity_state_dependency/claim_adjudicate_requires_final_determination
        """
        member, _own = setup_member_with_our_plan()
        provider = create_provider()
        draft_determination(member["id"], "2026-02-10")  # stays DRAFT
        claim = get_success_data(api.create_claim(
            create_claim_payload(member["id"], provider["id"]), EXAMINER,
        ))
        get_success_data(api.add_claim_line(
            claim["id"], create_claim_line_payload(
                line_number=1, billed_cents=10000, allowed_cents=8000,
            ), EXAMINER,
        ))
        res = api.adjudicate_claim(claim["id"], EXAMINER)
        validate_error(res, "ERR_NO_FINAL_PRIMACY", expected_status=422)

    def test_adjudicate_with_no_determination_rejected(self, api):
        """PRD §3.6: "requires exactly one `FINALIZED` primacy determination to
        exist for the member and service date — if none or several match,
        adjudication is rejected with `ERR_NO_FINAL_PRIMACY` (HTTP 422)."

        Design: Difficulty/cross_entity_state_dependency/claim_adjudicate_requires_final_determination
        """
        member, _own = setup_member_with_our_plan()
        provider = create_provider()
        claim = get_success_data(api.create_claim(
            create_claim_payload(member["id"], provider["id"]), EXAMINER,
        ))
        get_success_data(api.add_claim_line(
            claim["id"], create_claim_line_payload(
                line_number=1, billed_cents=10000, allowed_cents=8000,
            ), EXAMINER,
        ))
        res = api.adjudicate_claim(claim["id"], EXAMINER)
        validate_error(res, "ERR_NO_FINAL_PRIMACY", expected_status=422)


def test_claim_cannot_skip_adjudicate_to_pay(api):
    """PRD §3.6: "Payment moves the claim from `ADJUDICATED` to `PAID` and
    increments its `version`" and §2.9: "Whether the entity is in a state from
    which the requested transition is valid (`ERR_INVALID_STATE`)." A claim
    still RECEIVED cannot be paid.

    Design: Corner/state_machines/claim_cannot_skip_adjudicate_to_pay
    """
    member, _own = setup_member_with_our_plan()
    provider = create_provider()
    claim = get_success_data(api.create_claim(
        create_claim_payload(member["id"], provider["id"]), EXAMINER,
    ))
    assert claim["status"] == "RECEIVED"
    res = api.pay_claim(claim["id"], EXAMINER)
    validate_error(res, "ERR_INVALID_STATE", expected_status=409)
