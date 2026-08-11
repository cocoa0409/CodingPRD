"""Claim review, objection, settlement, and the reconsideration cycle."""
from test_helpers import (
    api_client, validate_success, validate_error, get_success_data,
    ApiErrorId, TEST_USERS, create_objection_payload, make_creditor_headers,
    create_creditor, file_claim, get_case, review_claim, allow_claim,
    review_and_allow_claim, object_to_claim, setup_case_in_claims_administration,
    setup_case_in_distribution,
)

TRUSTEE = TEST_USERS["trustee_headers"]
CLERK = TEST_USERS["clerk_headers"]
COURT = TEST_USERS["court_headers"]


def _case_with_allowed_claim(case_number, amount=500000):
    ctx = setup_case_in_claims_administration(case_number=case_number)
    claim = file_claim(ctx["case"]["id"], ctx["creditor"]["id"],
                       filed_amount_cents=amount)
    review_and_allow_claim(claim["id"])
    return ctx, claim


class TestReconsiderationCycle:
    def test_reopen_unwinds_allowed_amount_and_register_total(self, api):
        """PRD §3.3: "Reopening subtracts the claim's prior
        `allowed_amount_cents` from `allowed_claims_total_cents` and zeroes the
        claim's `allowed_amount_cents`."

        Design: Difficulty/non_linear_state_machine/claim_reconsideration_cycle_allowed_to_review_to_objected_to_allowed
        """
        ctx, claim = _case_with_allowed_claim("26-10005", amount=500000)
        case_id = ctx["case"]["id"]
        assert get_case(case_id)["allowed_claims_total_cents"] == 500000

        reopened = validate_success(api.reopen_claim(claim["id"], TRUSTEE))
        assert reopened["status"] == "UNDER_REVIEW"
        assert reopened["allowed_amount_cents"] == 0
        assert get_case(case_id)["allowed_claims_total_cents"] == 0, \
            "reopen unwinds the register total before re-adjudication"

    def test_reopen_object_settle_partial_reallows_at_reduced_amount(self, api):
        """PRD §3.3: "a `PARTIAL` outcome resolves it as `ALLOWED` at the
        supplied `settled_amount_cents` and `settled_priority_class`."
        PRD §3.3: "Where the settlement changes the claim's class,
        `allowed_claims_total_cents` reflects the new amount only, never a
        stale residue under the old class."

        Design: Difficulty/non_linear_state_machine/claim_reconsideration_cycle_allowed_to_review_to_objected_to_allowed
        """
        ctx, claim = _case_with_allowed_claim("26-10005", amount=500000)
        case_id = ctx["case"]["id"]

        validate_success(api.reopen_claim(claim["id"], TRUSTEE))
        obj = object_to_claim(claim["id"], grounds="AMOUNT_DISPUTED",
                              proposed_allowed_amount_cents=200000)
        validate_success(api.settle_objection(
            obj["id"],
            {"outcome": "PARTIAL", "settled_amount_cents": 200000,
             "settled_priority_class": "GENERAL_UNSECURED"},
            TRUSTEE))

        final_claim = validate_success(api.get_claim(claim["id"], TRUSTEE))
        assert final_claim["status"] == "ALLOWED"
        assert final_claim["allowed_amount_cents"] == 200000
        assert get_case(case_id)["allowed_claims_total_cents"] == 200000


class TestRegisterTotalConservation:
    def test_reopen_zeroes_then_reallow_restores_register_total(self, api):
        """PRD §3.3: "an `UNDER_REVIEW` claim becomes `ALLOWED`, its
        `allowed_amount_cents` is set equal to its `filed_amount_cents`, and
        the case's `allowed_claims_total_cents` increases by that amount, with
        the case `version` bumping accordingly."
        PRD §3.3: "Reopening subtracts the claim's prior `allowed_amount_cents`
        from `allowed_claims_total_cents` and zeroes the claim's
        `allowed_amount_cents`."

        Design: Difficulty/compensating_invariant/reopen_reallow_preserves_allowed_register_total
        """
        ctx, claim = _case_with_allowed_claim("26-10018", amount=300000)
        case_id = ctx["case"]["id"]
        total_before = get_case(case_id)["allowed_claims_total_cents"]
        assert total_before == 300000

        validate_success(api.reopen_claim(claim["id"], TRUSTEE))
        assert get_case(case_id)["allowed_claims_total_cents"] == 0

        validate_success(api.allow_claim(claim["id"], TRUSTEE))
        total_after = get_case(case_id)["allowed_claims_total_cents"]
        assert total_after == total_before, \
            "register total is conserved across the compensate/re-apply cycle"

    def test_reopen_reallow_claim_fields_track_the_cycle(self, api):
        """PRD §3.3: "The trustee may reopen an `ALLOWED` claim, returning it
        to `UNDER_REVIEW`"
        PRD §3.3: "an `UNDER_REVIEW` claim becomes `ALLOWED`, its
        `allowed_amount_cents` is set equal to its `filed_amount_cents`, and
        the case's `allowed_claims_total_cents` increases by that amount, with
        the case `version` bumping accordingly."

        Design: Difficulty/compensating_invariant/reopen_reallow_preserves_allowed_register_total
        """
        ctx, claim = _case_with_allowed_claim("26-10018", amount=300000)

        validate_success(api.reopen_claim(claim["id"], TRUSTEE))
        mid = validate_success(api.get_claim(claim["id"], TRUSTEE))
        assert mid["status"] == "UNDER_REVIEW"
        assert mid["allowed_amount_cents"] == 0

        validate_success(api.allow_claim(claim["id"], TRUSTEE))
        end = validate_success(api.get_claim(claim["id"], TRUSTEE))
        assert end["status"] == "ALLOWED"
        assert end["allowed_amount_cents"] == 300000


class TestObjectionGuards:
    def test_objection_on_filed_claim_rejected_invalid_state(self, api):
        """PRD §3.3: "Two guards protect the register: the claim must currently
        be `UNDER_REVIEW` (else `ERR_INVALID_STATE`), and no other objection
        may already be `PENDING` against the claim (else
        `ERR_OBJECTION_ALREADY_PENDING`)."

        Design: Corner/state_machines/objection_on_filed_claim_rejected_invalid_state
        """
        ctx = setup_case_in_claims_administration(case_number="26-20011")
        claim = file_claim(ctx["case"]["id"], ctx["creditor"]["id"])
        resp = api.create_objection(claim["id"], create_objection_payload(), TRUSTEE)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    def test_second_objection_rejected_while_one_pending(self, api):
        """PRD §3.3: "Two guards protect the register: the claim must currently
        be `UNDER_REVIEW` (else `ERR_INVALID_STATE`), and no other objection
        may already be `PENDING` against the claim (else
        `ERR_OBJECTION_ALREADY_PENDING`)."
        PRD §2.11: "5. From-state validity for the requested transition —
        `ERR_INVALID_STATE`."
        PRD §2.11: "When several checks could reject the same request, the
        server evaluates them in a fixed priority order, and the earliest
        failing tier determines the error surfaced:"

        While the first objection is PENDING the claim is `OBJECTED`, so the
        second objection fails the from-state guard (priority 5), which
        pre-empts the one-pending-objection guard (priority 9).

        Design: Difficulty/resource_temporal_overlap/one_pending_objection_per_claim_exclusion
        """
        ctx = setup_case_in_claims_administration(case_number="26-10016")
        claim = file_claim(ctx["case"]["id"], ctx["creditor"]["id"])
        review_claim(claim["id"])
        object_to_claim(claim["id"], proposed_allowed_amount_cents=50000)

        resp = api.create_objection(
            claim["id"],
            create_objection_payload(grounds="DUPLICATE",
                                     proposed_allowed_amount_cents=0),
            TRUSTEE)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    def test_objection_after_sustain_rejected_from_terminal_claim(self, api):
        """PRD §3.3: "The objection becomes `SUSTAINED`, the claim becomes
        `DISALLOWED` with `allowed_amount_cents` zeroed, and the claim's
        `objection_id` clears to null."
        PRD §3.3: "Two guards protect the register: the claim must currently
        be `UNDER_REVIEW` (else `ERR_INVALID_STATE`), and no other objection
        may already be `PENDING` against the claim (else
        `ERR_OBJECTION_ALREADY_PENDING`)."
        PRD §2.11: "5. From-state validity for the requested transition —
        `ERR_INVALID_STATE`."

        A PENDING objection pins the claim in `OBJECTED`, so a second
        objection fails the from-state guard (priority 5), which per §2.11
        pre-empts the one-pending-objection guard (priority 9).

        Design: Difficulty/resource_temporal_overlap/one_pending_objection_per_claim_exclusion
        """
        ctx = setup_case_in_claims_administration(case_number="26-10016")
        claim = file_claim(ctx["case"]["id"], ctx["creditor"]["id"])
        review_claim(claim["id"])
        obj = object_to_claim(claim["id"], proposed_allowed_amount_cents=50000)

        # While the first objection is PENDING the claim is OBJECTED, so the
        # from-state guard fires first.
        resp = api.create_objection(claim["id"], create_objection_payload(
            grounds="DUPLICATE"), TRUSTEE)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

        validate_success(api.sustain_objection(obj["id"], COURT))
        claim_after = validate_success(api.get_claim(claim["id"], TRUSTEE))
        assert claim_after["status"] == "DISALLOWED"

        # The exclusion is released, but the terminal claim blocks anew.
        resp2 = api.create_objection(claim["id"], create_objection_payload(
            grounds="DUPLICATE"), TRUSTEE)
        validate_error(resp2, ApiErrorId.ERR_INVALID_STATE)


class TestSettleValidation:
    def test_settle_partial_not_partial_rejected(self, api):
        """PRD §3.3: "A partial settlement must name a `settled_amount_cents`
        strictly less than the claim's `filed_amount_cents` — anything at or
        above the filed amount is rejected with `ERR_SETTLEMENT_NOT_PARTIAL`
        (HTTP 422)."

        Design: Corner/validations/settle_partial_not_partial_rejected
        """
        ctx = setup_case_in_claims_administration(case_number="26-20023")
        claim = file_claim(ctx["case"]["id"], ctx["creditor"]["id"],
                           filed_amount_cents=100000)
        review_claim(claim["id"])
        obj = object_to_claim(claim["id"], proposed_allowed_amount_cents=50000)

        resp = api.settle_objection(
            obj["id"],
            {"outcome": "PARTIAL", "settled_amount_cents": 100000,
             "settled_priority_class": "GENERAL_UNSECURED"},
            TRUSTEE)
        validate_error(resp, ApiErrorId.ERR_SETTLEMENT_NOT_PARTIAL)


class TestWithdrawalAndIdempotency:
    def test_withdraw_of_disallowed_claim_rejected_terminal_lockdown(self, api):
        """PRD §3.3: "A creditor may also withdraw its own claim. From `FILED`,
        withdrawal requires the presented `X-User-ID` to equal the claim's
        `creditor_id` (else `ERR_NOT_ASSIGNED_TRUSTEE`) and requires that no
        `POSTED` dividend reference the claim (else `ERR_DIVIDEND_POSTED`).
        From `UNDER_REVIEW`, the same identity match is required."
        PRD §2.11: "5. From-state validity for the requested transition —
        `ERR_INVALID_STATE`."

        Design: Corner/state_machines/withdraw_of_disallowed_claim_rejected_terminal_lockdown
        """
        ctx = setup_case_in_claims_administration(case_number="26-20012")
        cred_id = ctx["creditor"]["id"]
        claim = file_claim(ctx["case"]["id"], cred_id)
        review_claim(claim["id"])
        obj = object_to_claim(claim["id"], grounds="NOT_OWED")
        validate_success(api.sustain_objection(obj["id"], COURT))

        resp = api.withdraw_claim(claim["id"], make_creditor_headers(cred_id))
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    def test_second_allow_call_rejected_idempotency(self, api):
        """PRD §3.3: "Allowance is the trustee's determination that the claim
        stands as filed: an `UNDER_REVIEW` claim becomes `ALLOWED`, its
        `allowed_amount_cents` is set equal to its `filed_amount_cents`, and
        the case's `allowed_claims_total_cents` increases by that amount, with
        the case `version` bumping accordingly."
        PRD §2.11: "5. From-state validity for the requested transition —
        `ERR_INVALID_STATE`."

        Design: Corner/state_machines/second_allow_call_rejected_idempotency
        """
        ctx = setup_case_in_claims_administration(case_number="26-20014")
        claim = file_claim(ctx["case"]["id"], ctx["creditor"]["id"])
        review_claim(claim["id"])
        allow_claim(claim["id"])

        resp = api.allow_claim(claim["id"], TRUSTEE)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


class TestReopenGate:
    def test_reopen_rejected_once_case_in_distribution(self, api):
        """PRD §3.3: "The trustee may reopen an `ALLOWED` claim, returning it
        to `UNDER_REVIEW`, but only while the case is in
        `CLAIMS_ADMINISTRATION` or `LIQUIDATION` — once the case enters
        `DISTRIBUTION` the register is fixed and reopening is rejected with
        `ERR_CASE_BEYOND_REOPEN` — and only while no `POSTED` dividend
        references the claim (else `ERR_DIVIDEND_POSTED`)."

        Design: Corner/errors/error_case_beyond_reopen_triggered
        """
        ctx = setup_case_in_distribution(case_number="26-20042")
        resp = api.reopen_claim(ctx["claim"]["id"], TRUSTEE)
        validate_error(resp, ApiErrorId.ERR_CASE_BEYOND_REOPEN)
