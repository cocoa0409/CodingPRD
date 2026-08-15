"""Referral disposition: accept/decline/link-duplicate, state machine edges."""
from test_helpers import (
    validate_success, validate_error, validate_error_is_one_of, ApiErrorId,
    make_manager_headers, make_adjuster_headers,
    create_adjuster, create_claim, create_referral, triage_referral, accept_referral,
)
from test_helpers.api_client import api_client
from prd_bench_local_runner.testing import NON_EXISTENT_UUID


class TestReferralStateMachine:
    def test_case_initial_state_is_intake_on_accept(self, api):
        """PRD §3.2: "Acceptance creates a new SIU case in `INTAKE`, stamped with
        `opened_by_referral_id` pointing back to the referral"

        Design: Corner/state_machines/case_initial_state_is_intake
        """
        mh = make_manager_headers()
        adj, ah = create_adjuster(manager_headers=mh)
        claim = create_claim(adj, claimed_amount_cents=100)
        ref = create_referral(claim, headers=ah)
        triage_referral(ref, manager_headers=mh)
        case = accept_referral(ref, manager_headers=mh)
        assert case["status"] == "INTAKE"
        assert case["opened_by_referral_id"] == ref["id"]

    def test_accept_from_declined_returns_invalid_state(self, api):
        """PRD §3.2: "`ACCEPTED`, `DECLINED`, and `DUPLICATE_LINKED` are all
        terminal."
        PRD §2.6: "Target state — a failing state-machine precondition on the
        addressed resource yields `ERR_INVALID_STATE`."

        Design: Corner/state_machines/referral_accept_from_declined_returns_invalid_state
        """
        mh = make_manager_headers()
        adj, ah = create_adjuster(manager_headers=mh)
        claim = create_claim(adj, claimed_amount_cents=100)
        ref = create_referral(claim, headers=ah)
        triage_referral(ref, manager_headers=mh)
        resp = api_client.decline_referral(ref["id"], {"decline_reason": "not credible"}, mh)
        validate_success(resp)
        resp2 = api_client.accept_referral(ref["id"], mh)
        validate_error(resp2, ApiErrorId.ERR_INVALID_STATE)

    def test_accept_with_second_open_case_rejected(self, api):
        """PRD §3.2: "requires that no non-terminal case already exist for the
        claim, since at most one open investigation per claim is allowed; a
        violation is rejected with `ERR_CASE_ALREADY_OPEN`."
        PRD §3.2: "Accepting it requires the claim still be `PENDING` — a claim
        already under review or beyond is rejected with `ERR_CLAIM_ALREADY_UNDER_SIU`"
        (Either error is a faithful outcome here: accepting the first referral
        already moved the claim to UNDER_SIU_REVIEW, so the claim-guard may fire
        first.)

        Design: Corner/validations/case_already_open_uniqueness
        """
        mh = make_manager_headers()
        adj, ah = create_adjuster(manager_headers=mh)
        claim = create_claim(adj, claimed_amount_cents=100)
        ref1 = create_referral(claim, headers=ah)
        triage_referral(ref1, manager_headers=mh)
        accept_referral(ref1, manager_headers=mh)
        ref2 = create_referral(claim, red_flag_codes=["STAGED_ACCIDENT_PATTERN"],
                               headers=ah)
        triage_referral(ref2, manager_headers=mh)
        resp = api_client.accept_referral(ref2["id"], mh)
        validate_error_is_one_of(resp, [ApiErrorId.ERR_CASE_ALREADY_OPEN,
                                        ApiErrorId.ERR_CLAIM_ALREADY_UNDER_SIU])


class TestDuplicateLink:
    def test_link_duplicate_to_referral_on_different_claim_rejected(self, api):
        """PRD §3.2: "the target must resolve (else `ERR_FK_NOT_FOUND`), must
        itself be an `ACCEPTED` referral, and must flag the same claim — otherwise
        `ERR_DUPLICATE_LINK_INVALID`."

        Design: Corner/errors/err_duplicate_link_invalid_trigger
        """
        mh = make_manager_headers()
        adj, ah = create_adjuster(manager_headers=mh)
        c1 = create_claim(adj, claimed_amount_cents=100)
        c2 = create_claim(adj, claimed_amount_cents=200)
        r1 = create_referral(c1, headers=ah)
        triage_referral(r1, manager_headers=mh)
        accept_referral(r1, manager_headers=mh)
        r2 = create_referral(c2, red_flag_codes=["STAGED_ACCIDENT_PATTERN"], headers=ah)
        triage_referral(r2, manager_headers=mh)
        resp = api_client.link_duplicate_referral(
            r2["id"], {"duplicate_of_referral_id": r1["id"]}, mh)
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_LINK_INVALID)


class TestFKNotFound:
    def test_referral_with_nonexistent_claim_returns_fk_not_found(self, api):
        """PRD §2.5: "When a payload references another resource — for example
        `claim_id` on a referral — and that reference does not resolve, the request
        is rejected with `ERR_FK_NOT_FOUND` (HTTP 404)."

        Design: Corner/validations/body_fk_reference_not_found
        """
        mh = make_manager_headers()
        adj, ah = create_adjuster(manager_headers=mh)
        resp = api_client.create_referral(
            {"claim_id": NON_EXISTENT_UUID, "submitted_by_role": "ADJUSTER",
             "red_flag_codes": ["UNWITNESSED_LOSS"], "narrative": "x"}, ah)
        validate_error(resp, ApiErrorId.ERR_FK_NOT_FOUND)
