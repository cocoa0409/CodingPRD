"""Quote acceptance cascade, case decline/withdraw rules, terminal lockdowns."""
import pytest

from test_helpers import (
    validate_success,
    validate_error,
    validate_error_is_one_of,
    validate_paginated,
    get_success_data,
    ApiErrorId,
    api_client,
    create_broker,
    create_case,
    create_case_in_rating,
    add_modeled_plan,
    create_draft_quote,
    create_proposed_quote,
    create_counter_payload,
    create_respond_payload,
    setup_case_with_proposed_quote,
    setup_approved_case,
    make_broker_headers,
    TEST_USERS,
)

UW = TEST_USERS["underwriter_headers"]
SU = TEST_USERS["senior_underwriter_headers"]


class TestAcceptanceCascade:
    def test_accept_supersedes_sibling_quote_and_rejects_rounds(self):
        """PRD section 3.6: "The acceptance cascade is wide: the quote becomes
        `ACCEPTED`; the referenced plan design becomes `SELECTED`; every other
        non-terminal quote on the case becomes `SUPERSEDED`; any negotiation
        rounds still open on those quotes resolve to `REJECTED`; the parent case
        moves to `APPROVED`; and a Commission Disclosure is minted against the
        case, the accepted quote, and the broker of record."
        PRD section 3.6: "Rounds also resolve automatically with their parent
        quote: when the quote is accepted, its outstanding rounds move to
        `ACCEPTED`; when the quote is rejected or superseded, they move to
        `REJECTED`."

        Design: Difficulty/transitive_cascade/accept_supersedes_sibling_quote_and_rejects_rounds
        """
        broker, case, plan, q1 = setup_case_with_proposed_quote()
        broker_headers = make_broker_headers(broker["id"])
        # One counter/respond cycle on Q1 -> one open round resolved later.
        validate_success(api_client.counter_quote(
            q1["id"], create_counter_payload(
                proposed_pepm_cents=5000, proposed_contribution_pct=0.85,
                justification="Round one counter for budget relief",
            ), broker_headers))
        rounds, _ = validate_paginated(
            api_client.list_negotiation_rounds(q1["id"], UW)
        )
        r1 = rounds[0]
        validate_success(api_client.respond_quote(
            q1["id"], create_respond_payload(
                proposed_pepm_cents=5200, proposed_contribution_pct=0.82,
                justification="Round one response with modest concession",
            ), UW))
        # Q2 drafted before Q1 was proposed; propose it now (case back QUOTED
        # after the respond). Proposing Q2 supersedes Q1.
        # Note: Q2 must be created while the case is quotable; the case is
        # currently QUOTED after the respond.
        q2 = create_proposed_quote(case["id"], plan["id"], rate_guarantee_months=18)
        # Q1 (PROPOSED, non-terminal) was superseded when the newer quote on the
        # same case transitioned to PROPOSED.
        q1_after = get_success_data(api_client.get_quote(q1["id"], UW))
        assert q1_after["status"] == "SUPERSEDED"
        r1_after = get_success_data(api_client.get_negotiation_round(r1["id"], UW))
        assert r1_after["status"] == "REJECTED"

        q2 = validate_success(api_client.accept_quote(q2["id"], broker_headers))
        assert q2["status"] == "ACCEPTED"
        case = get_success_data(api_client.get_case(case["id"], UW))
        assert case["status"] == "APPROVED"
        plan = get_success_data(api_client.get_plan_design(plan["id"], UW))
        assert plan["status"] == "SELECTED"
        disclosures, meta = validate_paginated(
            api_client.list_commission_disclosures(case["id"], UW)
        )
        assert meta["total_count"] == 1
        assert disclosures[0]["status"] == "PENDING"
        assert disclosures[0]["quote_id"] == q2["id"]

    def test_accept_creates_disclosure_and_moves_case(self):
        """PRD section 3.6: "The acceptance cascade is wide: the quote becomes
        `ACCEPTED`; the referenced plan design becomes `SELECTED`; every other
        non-terminal quote on the case becomes `SUPERSEDED`; any negotiation
        rounds still open on those quotes resolve to `REJECTED`; the parent
        case moves to `APPROVED`; and a **Commission Disclosure** is minted
        against the case, the accepted quote, and the broker of record."
        PRD section 3.6: "The disclosure computes `total_commission_cents` (the
        accepted quote's annual broker commission), the effective
        `commission_pct`, the `per_enrollee_cents` figure, and compares the
        total against the system-held `disclosure_threshold_cents` — $50 per
        enrollee per year, i.e. 5,000 cents per enrollee — setting
        `requires_disclosure` true when the per-enrollee commission meets or
        exceeds that threshold. The disclosure is born `PENDING` with
        `disclosed_at` unset."

        Design: Difficulty/transitive_cascade/accept_supersedes_sibling_quote_and_rejects_rounds
        """
        broker, case, plan, quote, disclosure = setup_approved_case()
        assert quote["status"] == "ACCEPTED"
        assert case["status"] == "APPROVED"
        assert disclosure["status"] == "PENDING"
        assert disclosure["quote_id"] == quote["id"]
        assert disclosure["broker_id"] == broker["id"]
        assert disclosure.get("disclosed_at") in (None,)
        # annual 25622400 * 0.04 = 1024896; per-enrollee 2562.24 < 5000
        assert disclosure["total_commission_cents"] == 1024896
        assert disclosure["requires_disclosure"] is False


class TestCaseDeclineWithdraw:
    def test_decline_intake_case_fails(self):
        """PRD section 3.6: "The underwriter (or a senior) may decline the entire
        case while it is `QUOTED` or `NEGOTIATING` (else
        `ERR_CASE_NOT_DECLINABLE`)".

        Design: Corner/validations/decline_intake_case_fails
        """
        broker = create_broker()
        case = create_case(broker["id"])
        resp = api_client.decline_case(case["id"], UW)
        validate_error(resp, ApiErrorId.ERR_CASE_NOT_DECLINABLE)
        case = get_success_data(api_client.get_case(case["id"], UW))
        assert case["status"] == "INTAKE"

    def test_withdraw_approved_case_fails(self):
        """PRD section 3.1: "Either the underwriter or the broker of record may
        also withdraw a case at nearly any point in its life — from `INTAKE`,
        `CENSUS_PENDING`, `CENSUS_RECEIVED`, `CLAIMS_PENDING`,
        `RATING_IN_PROGRESS`, `QUOTED`, or `NEGOTIATING` — moving it to the
        terminal `WITHDRAWN` state" — `APPROVED` is not in the withdrawable set.
        PRD section 2.6: "business-state guards fire: the parent-case state guard
        (`ERR_CASE_INVALID_STATE` and its more specific case-state errors), then
        the entity's own transition guard (`ERR_INVALID_STATE_TRANSITION` and
        the more specific per-entity "not in state X" errors)" — for a
        case-level operation the case is both the "parent case" and the
        transitioning entity, so either guard satisfies the PRD.

        Design: Corner/state_machines/withdraw_approved_case_fails
        """
        broker, case, plan, quote, disclosure = setup_approved_case()
        resp = api_client.withdraw_case(
            case["id"], make_broker_headers(broker["id"])
        )
        validate_error_is_one_of(
            resp,
            [ApiErrorId.ERR_CASE_INVALID_STATE, ApiErrorId.ERR_INVALID_STATE_TRANSITION],
        )
        case = get_success_data(api_client.get_case(case["id"], UW))
        assert case["status"] == "APPROVED"

    def test_propose_quote_after_case_withdrawn_fails(self):
        """PRD section 3.5: "the parent case must be in `RATING_IN_PROGRESS`,
        `QUOTED`, or `NEGOTIATING` (else `ERR_CASE_NOT_QUOTABLE`)".

        Design: Corner/validations/propose_quote_after_case_withdrawn_fails
        """
        broker = create_broker()
        case, _ = create_case_in_rating(broker["id"])
        plan = add_modeled_plan(case["id"])
        quote = create_draft_quote(case["id"], plan["id"])
        validate_success(api_client.withdraw_case(case["id"], UW))
        resp = api_client.propose_quote(quote["id"], UW)
        validate_error(resp, ApiErrorId.ERR_CASE_NOT_QUOTABLE)
        quote = get_success_data(api_client.get_quote(quote["id"], UW))
        assert quote["status"] == "DRAFT"
        case = get_success_data(api_client.get_case(case["id"], UW))
        assert case["status"] == "WITHDRAWN"

    def test_reject_rejected_quote_fails_generic_invalid_state(self):
        """PRD section 3.6: "Either the broker or the underwriter may reject a
        live quote — from `PROPOSED` or from `COUNTERED` — moving it to
        `REJECTED`." A quote already in `REJECTED` is terminal, so a second
        reject hits the entity transition guard.
        PRD section 2.6: "then the entity's own transition guard
        (`ERR_INVALID_STATE_TRANSITION` and the more specific per-entity "not in
        state X" errors)" — a `REJECTED` quote is not `PROPOSED`, so both the
        generic guard and `ERR_QUOTE_NOT_PROPOSED` satisfy the PRD.

        Design: Corner/state_machines/reject_rejected_quote_fails_generic_invalid_state
        """
        broker, case, plan, quote = setup_case_with_proposed_quote()
        validate_success(api_client.reject_quote(quote["id"], UW))
        resp = api_client.reject_quote(quote["id"], UW)
        validate_error_is_one_of(
            resp,
            [ApiErrorId.ERR_INVALID_STATE_TRANSITION, ApiErrorId.ERR_QUOTE_NOT_PROPOSED],
        )
        quote = get_success_data(api_client.get_quote(quote["id"], UW))
        assert quote["status"] == "REJECTED"

    def test_suspended_broker_cannot_accept(self):
        """PRD section 3.6: "Accepting a quote requires the quote to be
        `PROPOSED` (else `ERR_QUOTE_NOT_PROPOSED`) and the broker to be `ACTIVE`
        (else `ERR_BROKER_NOT_ACTIVE`)".
        PRD section 3.1: "a `SeniorUnderwriter` may later update a broker's
        `status` — among `ACTIVE`, `SUSPENDED`, and `TERMINATED`".

        Design: Corner/validations/suspended_broker_cannot_accept
        """
        broker, case, plan, quote = setup_case_with_proposed_quote()
        broker2 = validate_success(
            api_client.update_broker(broker["id"], {"status": "SUSPENDED"}, SU)
        )
        assert broker2["status"] == "SUSPENDED"
        resp = api_client.accept_quote(
            quote["id"], make_broker_headers(broker["id"])
        )
        validate_error(resp, ApiErrorId.ERR_BROKER_NOT_ACTIVE)
        quote = get_success_data(api_client.get_quote(quote["id"], UW))
        assert quote["status"] == "PROPOSED"
        case = get_success_data(api_client.get_case(case["id"], UW))
        assert case["status"] == "QUOTED"
