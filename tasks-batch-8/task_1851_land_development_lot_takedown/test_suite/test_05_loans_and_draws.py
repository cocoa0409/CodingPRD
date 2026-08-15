"""Development loans, the draw pipeline, disbursement rounding, and SoD."""
from test_helpers import (
    DEV,
    LENDER,
    ApiErrorId,
    assert_draw,
    create_acquired_parcel,
    create_draw_payload,
    create_funded_draw,
    create_loan,
    create_loan_payload,
    create_requested_draw,
    finalize_closing,
    get_loan,
    make_developer_operator_headers,
    make_lender_officer_headers,
    reserve_and_open_closing,
    setup_active_loan_scenario,
    setup_selling_scenario,
    validate_error,
    validate_success,
)


class TestDrawDisbursementRounding:
    def test_draw_disbursement_pinned_rounding_order(self, api):
        """PRD §3.6: "The `retainage_cents` is five percent of the gross — the gross times 500 basis points over ten thousand — rounded half-up to whole cents; this is the first rounding step. The `draw_fee_cents` is one-half percent of the post-retainage base — the gross minus the retainage, times 50 basis points over ten thousand — rounded half-up to whole cents; this is the second rounding step, computed on the post-retainage base, not on the gross."
        PRD §3.6: "The order is load-bearing: a gross of 1,000,100 cents yields retainage of 50,005 cents, a fee of 4,750 cents on the remaining 950,095, and a net of 945,345 cents, whereas computing the fee first and the retainage second would yield 945,344 cents and is incorrect."

        Design: Difficulty/combinatorial_formula/draw_disbursement_nested_rounding
        """
        scenario = setup_active_loan_scenario(commitment_amount_cents=20000000)
        draw = validate_success(api.create_draw(
            {"loan_id": scenario["loan"]["id"],
             "line_items": [{"description": "grading", "amount_cents": 1000100}]},
            make_developer_operator_headers("dev-user-1")), 201)
        assert_draw(draw)
        assert draw["gross_amount_cents"] == 1000100
        # first rounding step: round_half_up(1000100 * 500/10000)
        assert draw["retainage_cents"] == 50005
        # second rounding step on the post-retainage base:
        # round_half_up((1000100 - 50005) * 50/10000)
        assert draw["draw_fee_cents"] == 4750
        assert draw["net_disbursed_cents"] == 945345
        assert draw["requested_by_user_id"] == "dev-user-1"
        assert draw["status"] == "REQUESTED"

    def test_draw_gross_sums_multiple_line_items(self, api):
        """PRD §3.6: "The `gross_amount_cents` is the plain sum of the line items' amounts — integer cents, no rounding at this step."

        Design: Difficulty/combinatorial_formula/draw_disbursement_nested_rounding
        """
        scenario = setup_active_loan_scenario(commitment_amount_cents=20000000)
        draw = validate_success(api.create_draw(
            {"loan_id": scenario["loan"]["id"],
             "line_items": [
                 {"description": "grading", "amount_cents": 600000},
                 {"description": "utilities", "amount_cents": 400100},
             ]},
            make_developer_operator_headers("dev-user-1")), 201)
        assert_draw(draw)
        assert draw["gross_amount_cents"] == 1000100
        assert draw["retainage_cents"] == 50005
        assert draw["draw_fee_cents"] == 4750
        assert draw["net_disbursed_cents"] == 945345


class TestDrawValidationOrder:
    def test_draw_on_draft_loan_rejected_referential_first(self, api):
        """PRD §2.8: "Requests are screened against a fixed, ordered validation cascade so that the same failure always surfaces as the same error, regardless of how many rules it would violate."
        PRD §2.8: "10. **Cross-entity referential gates** — rules that read the state of a *related* resource: parcel-acquired gates, agreement-active gates, phase readiness, bond-posted gates, parcel/agreement matching, loan selectability, and the behind-schedule precondition (409)."
        PRD §2.8: "11. **Fiscal gates** — money checks are evaluated last: the draw commitment cap, the bond posting floor, and the bond reduction thresholds (402)."
        PRD §3.6: "A `DeveloperOperator` requests a draw against a loan by supplying the `loan_id` and a `line_items` array; the loan must be `ACTIVE` (`ERR_LOAN_NOT_ACTIVE` otherwise)."

        Design: Difficulty/priority_pair_validation_conflict/draw_create_referential_vs_fiscal
        """
        scenario = setup_active_loan_scenario(commitment_amount_cents=500000,
                                              activate_loan=False)
        # both conditions hold: loan DRAFT (referential) and gross 99999999
        # far beyond the 500000 commitment (fiscal) — referential wins
        resp = api.create_draw(
            {"loan_id": scenario["loan"]["id"],
             "line_items": [{"description": "oversized", "amount_cents": 99999999}]},
            make_developer_operator_headers("dev-user-1"))
        validate_error(resp, ApiErrorId.ERR_LOAN_NOT_ACTIVE)

    def test_draw_on_draft_loan_rejected_even_within_commitment(self, api):
        """PRD §3.6: "A `DeveloperOperator` requests a draw against a loan by supplying the `loan_id` and a `line_items` array; the loan must be `ACTIVE` (`ERR_LOAN_NOT_ACTIVE` otherwise)."

        Design: Difficulty/priority_pair_validation_conflict/draw_create_referential_vs_fiscal
        """
        scenario = setup_active_loan_scenario(commitment_amount_cents=500000,
                                              activate_loan=False)
        resp = api.create_draw(
            {"loan_id": scenario["loan"]["id"],
             "line_items": [{"description": "small", "amount_cents": 100000}]},
            make_developer_operator_headers("dev-user-1"))
        validate_error(resp, ApiErrorId.ERR_LOAN_NOT_ACTIVE)


class TestDrawPipeline:
    def test_fund_moves_loan_balance(self, api):
        """PRD §3.6: "Funding an `APPROVED` draw requires the loan still to be `ACTIVE` (`ERR_LOAN_NOT_ACTIVE` otherwise), moves the draw to `FUNDED`, and adds `net_disbursed_cents` to both the loan's `outstanding_balance_cents` and its `total_drawn_cents`, incrementing both resources' versions."

        Design: Difficulty/compensating_invariant/loan_balance_fund_reverse_conservation
        """
        scenario = setup_active_loan_scenario(commitment_amount_cents=20000000)
        loan = scenario["loan"]
        assert loan["outstanding_balance_cents"] == 0
        draw = create_requested_draw(loan["id"], 2000000)
        validate_success(api.approve_draw(
            draw["id"], make_lender_officer_headers("lo-user-1")))
        funded = validate_success(api.fund_draw(
            draw["id"], make_lender_officer_headers("lo-user-1")))
        assert funded["status"] == "FUNDED"
        after = get_loan(loan["id"])
        # net = 2000000 - 100000 retainage - 9500 fee
        assert after["outstanding_balance_cents"] == 1890500
        assert after["total_drawn_cents"] == 1890500

    def test_reverse_restores_loan_balance(self, api):
        """PRD §3.6: "Reversing a `FUNDED` draw moves it to terminal `REVERSED` and subtracts the same `net_disbursed_cents` from both loan aggregates — the compensating action that preserves the balance-conservation invariant."
        PRD §2.9: "**Loan balance conservation.** A draw's funding paired with its later reversal leaves `outstanding_balance_cents` and `total_drawn_cents` exactly unchanged; a `REVERSED` draw contributes zero to both aggregates."

        Design: Difficulty/compensating_invariant/loan_balance_fund_reverse_conservation
        """
        scenario = setup_active_loan_scenario(commitment_amount_cents=20000000)
        draw = create_funded_draw(scenario["loan"]["id"], 2000000)
        reversed_draw = validate_success(api.reverse_draw(
            draw["id"], make_lender_officer_headers("lo-user-1")))
        assert reversed_draw["status"] == "REVERSED"
        loan = get_loan(scenario["loan"]["id"])
        assert loan["outstanding_balance_cents"] == 0
        assert loan["total_drawn_cents"] == 0

    def test_fund_requested_draw_rejected(self, api):
        """PRD §3.6: "Each disposal step is state-guarded: approving or rejecting requires `REQUESTED`, funding requires `APPROVED`, and reversing requires `FUNDED`, with any other from-state rejected as `ERR_DRAW_INVALID_STATE`."

        Design: Corner/errors/error_fund_requested_draw_returns_invalid_state
        """
        scenario = setup_active_loan_scenario(commitment_amount_cents=20000000)
        draw = create_requested_draw(scenario["loan"]["id"], 100000)
        resp = api.fund_draw(draw["id"], make_lender_officer_headers("lo-user-1"))
        validate_error(resp, ApiErrorId.ERR_DRAW_INVALID_STATE)

    def test_approve_by_requester_rejected_segregation_of_duties(self, api):
        """PRD §3.6: "Approving moves the draw from `REQUESTED` to `APPROVED` and records the approver's `X-User-ID` on `approved_by_user_id`, but the approver must not be the requester — an approval whose `X-User-ID` equals the draw's `requested_by_user_id` is rejected with `ERR_SEGREGATION_OF_DUTIES`."

        Design: Corner/rbac/sod_approver_is_requester_returns_403
        """
        scenario = setup_active_loan_scenario(commitment_amount_cents=20000000)
        draw = create_requested_draw(scenario["loan"]["id"], 100000,
                                     requester_id="dev-user-1")
        resp = api.approve_draw(
            draw["id"], make_lender_officer_headers("dev-user-1"))
        validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)
        approved = validate_success(api.approve_draw(
            draw["id"], make_lender_officer_headers("lo-user-9")))
        assert approved["status"] == "APPROVED"
        assert approved["approved_by_user_id"] == "lo-user-9"

    def test_lender_cannot_create_draw(self, api):
        """PRD §3.6: "A `DeveloperOperator` requests a draw against a loan by supplying the `loan_id` and a `line_items` array; the loan must be `ACTIVE` (`ERR_LOAN_NOT_ACTIVE` otherwise)."
        PRD §2.1: "A request whose role is not permitted for the target endpoint — or that fails an entity-backed ownership check — is rejected with `ERR_FORBIDDEN_ROLE`."

        Design: Corner/rbac/lender_cannot_create_draw_returns_403
        """
        scenario = setup_active_loan_scenario(commitment_amount_cents=20000000)
        resp = api.create_draw(
            create_draw_payload(scenario["loan"]["id"], 100000), LENDER)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE)


class TestLoanGates:
    def test_second_open_loan_per_parcel_rejected(self, api):
        """PRD §3.6: "Only one open loan may exist per parcel: creating a second loan while one sits in `DRAFT` or `ACTIVE` is rejected with `ERR_LOAN_ALREADY_EXISTS`, though a `PAID_OFF` loan does not block a successor."

        Design: Corner/validations/second_open_loan_per_parcel_rejected
        """
        parcel = create_acquired_parcel(parcel_name="LP")
        create_loan(parcel["id"], commitment_amount_cents=1000000)
        resp = api.create_loan(create_loan_payload(
            parcel["id"], commitment_amount_cents=2000000,
            release_price_floor_bp=7500), DEV)
        validate_error(resp, ApiErrorId.ERR_LOAN_ALREADY_EXISTS)

    def test_draw_exceeding_commitment_rejected(self, api):
        """PRD §3.6: "Creation is also subject to the commitment cap: the cumulative gross of the loan's draws in `REQUESTED`, `APPROVED`, or `FUNDED` status plus the new draw's gross must not exceed `commitment_amount_cents`, and a breach is rejected with `ERR_DRAW_EXCEEDS_COMMITMENT`."

        Design: Corner/errors/error_draw_exceeds_commitment
        """
        scenario = setup_active_loan_scenario(commitment_amount_cents=500000)
        create_requested_draw(scenario["loan"]["id"], 300000)
        # 300000 REQUESTED + 300000 new = 600000 > 500000 commitment
        resp = api.create_draw(
            create_draw_payload(scenario["loan"]["id"], 300000),
            make_developer_operator_headers("dev-user-1"))
        validate_error(resp, ApiErrorId.ERR_DRAW_EXCEEDS_COMMITMENT)


class TestReleasePaymentClamp:
    def test_release_payment_clamped_at_zero_balance(self, api):
        """PRD §3.5: "The release payment lands on the loan: `payment_applied_cents` is set to the lesser of the closing's frozen `release_price_cents` and the loan's current `outstanding_balance_cents` — the clamp guarantees the balance can never go negative — then the loan's `outstanding_balance_cents` decreases by that payment, its `total_release_paid_cents` increases by the same amount, and the loan's `version` increments."
        PRD §3.5: "If the balance change leaves `outstanding_balance_cents` at exactly zero while `total_drawn_cents` is greater than zero, the loan auto-transitions from `ACTIVE` to terminal `PAID_OFF`."

        Design: Corner/calculations/release_payment_clamped_at_outstanding
        """
        scenario = setup_selling_scenario(
            num_lots=1, agreement_overrides={"scheduled_lot_count": 2})
        closing = reserve_and_open_closing(
            scenario["lots"][0]["id"], scenario["agreement"]["id"],
            scenario["builder"]["id"])
        # frozen at 80% of the 5304500 contract price
        assert closing["release_price_cents"] == 4243600

        finalized = finalize_closing(closing["id"])
        assert finalized["status"] == "CLOSED"
        # the loan has no draws, so the payment clamps to the zero balance
        assert finalized["payment_applied_cents"] == 0

        loan = get_loan(scenario["loan"]["id"])
        assert loan["outstanding_balance_cents"] == 0
        # PAID_OFF requires total_drawn_cents > 0, so the loan stays ACTIVE
        assert loan["status"] == "ACTIVE"
