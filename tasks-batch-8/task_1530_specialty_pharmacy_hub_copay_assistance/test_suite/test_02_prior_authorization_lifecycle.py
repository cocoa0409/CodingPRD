"""Prior authorization lifecycle: denial/appeal cycle on the enrollment,
appeal rounds to final denial, the BI-driven PA requirement gate, and role
isolation on payer decisions."""
from test_helpers import (
    ApiErrorId,
    api_client,
    assert_prior_authorization,
    create_approved_enrollment,
    create_pa_pending_enrollment,
    create_pa_payload,
    get_enrollment,
    pa_appeal_payload,
    pa_decision_payload,
    record_benefits_investigation,
    validate_error,
    validate_error_is_one_of,
    validate_paginated,
    validate_success,
)
from test_helpers import TEST_USERS

CM = TEST_USERS["case_manager_headers"]
PR = TEST_USERS["payer_reviewer_headers"]


class TestPaCreationGate:

    def test_pa_creation_rejected_when_bi_does_not_require_it(self):
        """PRD section 3.3: "Creation is only valid while the enrollment is
        in `BENEFITS_VERIFIED` — attempting it from any other enrollment
        state is `ERR_INVALID_TRANSITION` — and only when the investigation's
        `requires_prior_auth` is true; submitting a prior authorization for a
        plan that does not require one is rejected with
        `ERR_PA_NOT_REQUIRED`."

        Design: Difficulty/cross_entity_state_dependency/pa_creation_gated_on_bi_requires_prior_auth

        Precedence note: with `requires_prior_auth` false the enrollment
        auto-advances to APPROVED (PRD 3.2), so the attempt fails BOTH the
        level-5 state check (`ERR_INVALID_TRANSITION`, wrong from-state) and
        the level-7 domain check (`ERR_PA_NOT_REQUIRED`). PRD 2.6 names both
        errors at those levels without stating that the plan-requirement
        check pre-empts the state-check path, so either error id satisfies
        the PRD.
        """
        ctx = create_approved_enrollment(patient_ref="PAT-O")
        resp = api_client.create_prior_authorization(
            ctx["enrollment"]["id"],
            create_pa_payload(payer_reference="PA-X"), CM)
        validate_error_is_one_of(
            resp, [ApiErrorId.ERR_PA_NOT_REQUIRED,
                   ApiErrorId.ERR_INVALID_TRANSITION])

    def test_rejected_pa_creation_persists_no_authorization(self):
        """PRD section 3.3: "submitting a prior authorization for a plan
        that does not require one is rejected with `ERR_PA_NOT_REQUIRED`."
        PRD section 4: "List prior authorizations for an enrollment".

        Design: Difficulty/cross_entity_state_dependency/pa_creation_gated_on_bi_requires_prior_auth

        Precedence note: same both-fail scenario as the sibling test — the
        enrollment stands in APPROVED (PRD 3.2 auto-advance), so PRD 2.6
        admits either the level-5 `ERR_INVALID_TRANSITION` or the level-7
        `ERR_PA_NOT_REQUIRED`. Both rejections precede creation, so the
        no-row-persists assertion holds under either branch.
        """
        ctx = create_approved_enrollment(patient_ref="PAT-O2")
        resp = api_client.create_prior_authorization(
            ctx["enrollment"]["id"], create_pa_payload(), CM)
        validate_error_is_one_of(
            resp, [ApiErrorId.ERR_PA_NOT_REQUIRED,
                   ApiErrorId.ERR_INVALID_TRANSITION])
        _, meta = validate_paginated(
            api_client.list_prior_authorizations(ctx["enrollment"]["id"], CM))
        assert meta["total_count"] == 0, \
            "a rejected PA creation must leave no PriorAuthorization row"


class TestDenialAppealCycle:

    def test_pa_denial_swings_enrollment_to_pa_denied(self):
        """PRD section 3.3: "A `DENIED` outcome moves the authorization to
        `DENIED` whenever its `appeal_round` is below the hard cap of two
        appeal rounds (`MAX_APPEAL_ROUNDS`) — at the initial decision the
        round count is zero, which is always below the cap, so a first
        denial always lands in `DENIED`, and a denial of the first appeal,
        filed at round one, lands in `DENIED` as well. Each such denial
        cascades the enrollment `PA_PENDING` → `PA_DENIED`."

        Design: Difficulty/non_linear_state_machine/enrollment_pa_denial_appeal_cycle
        """
        ctx = create_pa_pending_enrollment(patient_ref="PAT-F")
        resp = api_client.record_pa_decision(
            ctx["pa"]["id"],
            pa_decision_payload("DENIED", rationale="insufficient documentation"),
            PR)
        pa = validate_success(resp, expected_status=200)
        assert pa["status"] == "DENIED"
        enr = get_enrollment(ctx["enrollment"]["id"])
        assert enr["status"] == "PA_DENIED", \
            f"denial must swing the enrollment to PA_DENIED, got {enr['status']}"

    def test_appeal_returns_enrollment_to_pa_pending_and_increments_round(self):
        """PRD section 3.3: "The appeal moves the authorization `DENIED` →
        `APPEALED`, increments `appeal_round` by one, and swings the
        enrollment `PA_DENIED` → `PA_PENDING`."

        Design: Difficulty/non_linear_state_machine/enrollment_pa_denial_appeal_cycle
        """
        ctx = create_pa_pending_enrollment(patient_ref="PAT-F2")
        validate_success(api_client.record_pa_decision(
            ctx["pa"]["id"], pa_decision_payload("DENIED", rationale="r1"), PR),
            expected_status=200)
        resp = api_client.appeal_prior_authorization(
            ctx["pa"]["id"], pa_appeal_payload(), CM)
        pa = validate_success(resp, expected_status=200)
        assert_prior_authorization(pa)
        assert pa["status"] == "APPEALED"
        assert pa["appeal_round"] == 1, \
            f"appeal must increment appeal_round by one, got {pa['appeal_round']}"
        enr = get_enrollment(ctx["enrollment"]["id"])
        assert enr["status"] == "PA_PENDING", \
            "the cycle returns the enrollment to the earlier PA_PENDING state"


class TestAppealRoundsToFinalDenial:

    def test_denials_below_the_appeal_cap_stay_appealable(self):
        """PRD section 3.3: "A `DENIED` outcome moves the authorization to
        `DENIED` whenever its `appeal_round` is below the hard cap of two
        appeal rounds (`MAX_APPEAL_ROUNDS`) — at the initial decision the
        round count is zero, which is always below the cap, so a first
        denial always lands in `DENIED`, and a denial of the first appeal,
        filed at round one, lands in `DENIED` as well."
        PRD section 3.3: "The appeal moves the authorization `DENIED` →
        `APPEALED`, increments `appeal_round` by one, and swings the
        enrollment `PA_DENIED` → `PA_PENDING`."

        Design: Difficulty/non_linear_state_machine/prior_authorization_appeal_rounds_to_final_denial
        """
        ctx = create_pa_pending_enrollment(patient_ref="PAT-G")
        pa_id = ctx["pa"]["id"]

        pa1 = validate_success(api_client.record_pa_decision(
            pa_id, pa_decision_payload("DENIED", rationale="r1"), PR), 200)
        assert pa1["status"] == "DENIED", "round-0 denial stays appealable"

        validate_success(api_client.appeal_prior_authorization(
            pa_id, pa_appeal_payload(), CM), 200)

        pa2 = validate_success(api_client.record_pa_decision(
            pa_id, pa_decision_payload("DENIED", rationale="r2"), PR), 200)
        assert pa2["status"] == "DENIED", \
            "a denial filed at round one is still below the cap"

        pa3 = validate_success(api_client.appeal_prior_authorization(
            pa_id, pa_appeal_payload(), CM), 200)
        assert pa3["appeal_round"] == 2, \
            f"second appeal brings appeal_round to 2, got {pa3['appeal_round']}"
        assert pa3["status"] == "APPEALED"

    def test_denial_at_round_cap_is_final_and_closes_enrollment(self):
        """PRD section 3.3: "A `DENIED` decision on an authorization in
        `APPEALED` whose `appeal_round` has reached two instead terminates
        the authorization in `DENIED_FINAL` and cascades the enrollment
        `PA_PENDING` → `DENIED_CLOSED`; the enrollment sits in `PA_PENDING`
        while the final appeal is under review."
        PRD section 3.3: "Appealing an authorization in any other
        non-terminal state — for instance one still `SUBMITTED` — is
        rejected with `ERR_INVALID_TRANSITION`, and any decision or appeal
        attempted on a terminal authorization (`APPROVED` or `DENIED_FINAL`)
        is rejected with `ERR_ALREADY_TERMINAL`."

        Design: Difficulty/non_linear_state_machine/prior_authorization_appeal_rounds_to_final_denial
        """
        ctx = create_pa_pending_enrollment(patient_ref="PAT-G2")
        pa_id = ctx["pa"]["id"]

        validate_success(api_client.record_pa_decision(
            pa_id, pa_decision_payload("DENIED", rationale="r1"), PR), 200)
        validate_success(api_client.appeal_prior_authorization(
            pa_id, pa_appeal_payload(), CM), 200)
        validate_success(api_client.record_pa_decision(
            pa_id, pa_decision_payload("DENIED", rationale="r2"), PR), 200)
        validate_success(api_client.appeal_prior_authorization(
            pa_id, pa_appeal_payload(), CM), 200)

        pa_final = validate_success(api_client.record_pa_decision(
            pa_id, pa_decision_payload("DENIED", rationale="r3"), PR), 200)
        assert pa_final["status"] == "DENIED_FINAL", \
            f"round-2 denial is terminal, got {pa_final['status']}"
        assert pa_final["appeal_round"] == 2

        enr = get_enrollment(ctx["enrollment"]["id"])
        assert enr["status"] == "DENIED_CLOSED"

        resp = api_client.appeal_prior_authorization(
            pa_id, pa_appeal_payload(), CM)
        validate_error(resp, ApiErrorId.ERR_ALREADY_TERMINAL)


class TestInvalidAndForbiddenTransitions:

    def test_pa_appeal_from_submitted_returns_invalid_transition(self):
        """PRD section 3.3: "Appealing an authorization in any other
        non-terminal state — for instance one still `SUBMITTED` — is
        rejected with `ERR_INVALID_TRANSITION`, and any decision or appeal
        attempted on a terminal authorization (`APPROVED` or `DENIED_FINAL`)
        is rejected with `ERR_ALREADY_TERMINAL`."
        PRD section 3.3: "The new PriorAuthorization enters `SUBMITTED` with
        an `appeal_round` of zero, and the enrollment moves
        `BENEFITS_VERIFIED` → `PA_PENDING`."

        Design: Corner/state_machines/pa_appeal_from_submitted_returns_invalid_transition
        """
        ctx = create_pa_pending_enrollment(patient_ref="PAT-S1")
        resp = api_client.appeal_prior_authorization(
            ctx["pa"]["id"], pa_appeal_payload(), CM)
        validate_error(resp, ApiErrorId.ERR_INVALID_TRANSITION)

        data, _ = validate_paginated(
            api_client.list_prior_authorizations(ctx["enrollment"]["id"], CM))
        assert data[0]["status"] == "SUBMITTED", "a rejected appeal mutates nothing"
        assert data[0]["appeal_round"] == 0

    def test_case_manager_cannot_record_pa_decision(self):
        """PRD section 2.1: "A request whose role is not listed among the
        roles authorized for the target endpoint is rejected with
        `ERR_FORBIDDEN`; the same code applies when a `NurseEducator`
        attempts to resolve a nurse visit assigned to a different nurse."
        PRD section 4: "Record an APPROVED or DENIED payer decision |
        PayerReviewer".

        Design: Corner/rbac/case_manager_cannot_record_pa_decision
        """
        ctx = create_pa_pending_enrollment(patient_ref="PAT-R1")
        resp = api_client.record_pa_decision(
            ctx["pa"]["id"], pa_decision_payload("APPROVED", rationale="ok"), CM)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)

        data, _ = validate_paginated(
            api_client.list_prior_authorizations(ctx["enrollment"]["id"], CM))
        assert data[0]["status"] == "SUBMITTED", \
            "a decision attempted by a denied role must not mutate the PA"
