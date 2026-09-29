"""Operations gated on the state of a neighbouring entity rather than their own."""

from test_helpers import (
    CLOCK_STARTUP_UTC,
    COMMITTEE_OFFICER_USER_ID,
    SCREENING_ANALYST_USER_ID,
    TEST_USERS,
    advance_other_insurance,
    api_client,
    approve,
    assert_covered_claim,
    assert_instant_equals,
    assert_other_insurance,
    assert_transferred_policy,
    claim_payload,
    get_success_data,
    make_claims_committee_officer_headers,
    policy_payload,
    read_claim,
    read_insolvency,
    read_policy,
    setup_declared_insolvency,
    setup_recommended_claim_with_pursuing_layer,
    trigger_insolvency,
    validate_error,
)

ANALYST = TEST_USERS["coverage_analyst_headers"]
RECEIVER = TEST_USERS["receiver_liaison_headers"]

INCUMBENT_TERM = {
    "policy_number": "PA-1001",
    "policyholder_name": "Ada Renner",
    "effective_date": "2025-10-01",
    "expiration_date": "2026-10-01",
    "annual_premium_cents": 1_200_000,
}
RENEWAL_TERM = {
    "policy_number": "PA-1001",
    "policyholder_name": "Ada Renner",
    "effective_date": "2026-10-01",
    "expiration_date": "2027-10-01",
    "annual_premium_cents": 1_260_000,
}
OVERLAPPING_TERM = {
    "policy_number": "PA-1001",
    "policyholder_name": "Ada Renner",
    "effective_date": "2026-09-01",
    "expiration_date": "2027-09-01",
    "annual_premium_cents": 1_260_000,
}

LARGE_LOSS_CLAIM = {
    "claim_number": "C-1",
    "claimant_name": "Ben Ortiz",
    "gross_loss_cents": 4_500_000,
}
EXCESS_LAYER = {
    "carrier_name": "Northline Casualty",
    "policy_number": "NL-77",
    "coverage_type": "EXCESS",
    "stated_limit_cents": 2_000_000,
}


def _claim_body(env: dict) -> dict:
    return claim_payload(env["insolvency"]["id"], env["policy"]["id"], **LARGE_LOSS_CLAIM)


class TestClaimIntakeRequiresTheTriggeringEvent:
    """A claim may only be presented once the liquidation order has been recorded."""

    def test_a_declared_file_refuses_the_claim(self):
        """The first family demands that the triggering event has already been recorded: presenting a
        covered claim, filing an unearned premium refund, recording an estate remittance, executing a
        distribution run, certifying an assessment and closing the file all require `status` to be
        `TRIGGERED`, and a `DECLARED` file refuses them with `ERR_INSOLVENCY_NOT_TRIGGERED`.

        Design: Difficulty/cross_entity_state_dependency/claim_intake_requires_the_insolvency_to_have_been_triggered
        """
        env = setup_declared_insolvency(policy_overrides=dict(INCUMBENT_TERM))
        assert env["insolvency"]["status"] == "DECLARED", env["insolvency"]["status"]
        assert env["insolvency"]["triggered_at_utc"] is None

        response = api_client.create_claim(_claim_body(env), ANALYST)
        validate_error(response, "ERR_INSOLVENCY_NOT_TRIGGERED", 409)

        assert api_client.list_claims(
            ANALYST, {"insolvency_id": env["insolvency"]["id"], "limit": 50}
        ).json()["data"] == [], "the refused intake must leave no claim behind"
        policy = read_policy(env["policy"]["id"])
        assert policy["status"] == "IMPORTED", policy["status"]

    def test_the_identical_body_is_accepted_once_the_order_is_recorded(self):
        """It stamps `triggered_at_utc` from the logical clock.

        Every transferred policy in `IMPORTED` whose `expiration_date` falls strictly after the
        `liquidation_order_date` moves `IMPORTED → CANCELLED_BY_ORDER`: its `cancellation_date` is set
        to whichever is earlier of its own `expiration_date` and the file's
        `coverage_termination_date`, its `unexpired_days` is set to the number of whole calendar days
        from that `cancellation_date` forward to its `expiration_date`, and its `version` is
        incremented by one.

        Design: Difficulty/cross_entity_state_dependency/claim_intake_requires_the_insolvency_to_have_been_triggered
        """
        env = setup_declared_insolvency(policy_overrides=dict(INCUMBENT_TERM))
        body = _claim_body(env)
        validate_error(api_client.create_claim(body, ANALYST), "ERR_INSOLVENCY_NOT_TRIGGERED", 409)

        insolvency = trigger_insolvency(env["insolvency"]["id"])
        assert insolvency["status"] == "TRIGGERED", insolvency["status"]
        assert_instant_equals(insolvency["triggered_at_utc"], CLOCK_STARTUP_UTC)

        policy = read_policy(env["policy"]["id"])
        assert_transferred_policy(policy)
        assert policy["status"] == "CANCELLED_BY_ORDER", policy["status"]
        assert policy["cancellation_date"] == "2026-03-31", policy["cancellation_date"]

        claim = get_success_data(api_client.create_claim(body, ANALYST))
        assert_covered_claim(claim)
        assert claim["status"] == "RECEIVED", claim["status"]
        assert claim["insolvency_id"] == env["insolvency"]["id"]

        rows = api_client.list_claims(
            ANALYST, {"insolvency_id": env["insolvency"]["id"], "limit": 50}
        ).json()["data"]
        assert len(rows) == 1, f"the accepted body must create exactly one claim, got {len(rows)}"

    def test_the_refused_intake_does_not_consume_the_claim_number(self):
        """`claim_number` is unique within the target `policy_id` → `ERR_DUPLICATE_CLAIM` (HTTP 409),
        on `POST /claims`.

        Design: Difficulty/cross_entity_state_dependency/claim_intake_requires_the_insolvency_to_have_been_triggered
        """
        env = setup_declared_insolvency(policy_overrides=dict(INCUMBENT_TERM))
        body = _claim_body(env)
        validate_error(api_client.create_claim(body, ANALYST), "ERR_INSOLVENCY_NOT_TRIGGERED", 409)
        trigger_insolvency(env["insolvency"]["id"])

        first = get_success_data(api_client.create_claim(body, ANALYST))
        assert first["claim_number"] == "C-1"
        validate_error(api_client.create_claim(body, RECEIVER), "ERR_DUPLICATE_CLAIM", 409)


class TestApprovalRequiresEveryLayerResolved:
    """Approval is gated on the state of the claim's other-insurance children."""

    def _recommended_with_pursuing_layer(self) -> dict:
        return setup_recommended_claim_with_pursuing_layer(
            recommended_amount_cents=2_400_000,
            analyst_user_id=SCREENING_ANALYST_USER_ID,
            claim_overrides=dict(LARGE_LOSS_CLAIM),
            layer_overrides=dict(EXCESS_LAYER),
        )

    def test_a_layer_still_being_pursued_blocks_the_approval(self):
        """Every other-insurance layer on the claim has reached `EXHAUSTED` or `CARRIER_DENIED` →
        `ERR_OTHER_INSURANCE_NOT_EXHAUSTED` (HTTP 409), on `POST /claims/{id}/approve`.

        Design: Difficulty/cross_entity_state_dependency/approval_requires_every_other_insurance_layer_to_be_resolved
        """
        env = self._recommended_with_pursuing_layer()
        assert env["claim"]["status"] == "RECOMMENDED", env["claim"]["status"]
        assert env["layer"]["status"] == "PURSUING", env["layer"]["status"]

        response = api_client.approve_claim(
            env["claim"]["id"], make_claims_committee_officer_headers(COMMITTEE_OFFICER_USER_ID), {}
        )
        validate_error(response, "ERR_OTHER_INSURANCE_NOT_EXHAUSTED", 409)

        claim = read_claim(env["claim"]["id"])
        assert claim["status"] == "RECOMMENDED", claim["status"]
        assert claim["approved_by_user_id"] is None
        insolvency = read_insolvency(env["insolvency"]["id"])
        assert insolvency["reserved_claim_cents"] == 0, (
            "no estate reserve is booked before approval, got "
            f"{insolvency['reserved_claim_cents']}"
        )

    def test_a_carrier_denial_resolves_the_layer_and_the_same_approval_succeeds(self):
        """Reporting a carrier denial moves it `PURSUING → CARRIER_DENIED` and leaves
        `recovered_cents` at 0, but still marks the layer resolved.

        A carrier denial therefore resolves a layer without reducing the association's payable at
        all, which is the intended outcome — the association pays because the other carrier will not.

        Design: Difficulty/cross_entity_state_dependency/approval_requires_every_other_insurance_layer_to_be_resolved
        """
        env = self._recommended_with_pursuing_layer()
        validate_error(
            api_client.approve_claim(
                env["claim"]["id"],
                make_claims_committee_officer_headers(COMMITTEE_OFFICER_USER_ID),
                {},
            ),
            "ERR_OTHER_INSURANCE_NOT_EXHAUSTED",
            409,
        )

        layer = advance_other_insurance(env, env["layer"]["id"], "CARRIER_DENIED")
        assert_other_insurance(layer)
        assert layer["status"] == "CARRIER_DENIED", layer["status"]
        assert layer["recovered_cents"] == 0, (
            f"a denial recovers nothing, got {layer['recovered_cents']}"
        )

        claim = approve(env, COMMITTEE_OFFICER_USER_ID)
        assert claim["status"] == "APPROVED", claim["status"]
        assert claim["other_insurance_recoverable_cents"] == 0
        assert claim["net_payable_cents"] == 3_000_000, (
            "the 4500000 loss less the 10000 deductible is truncated to the 3000000 per-claim cap, "
            f"got {claim['net_payable_cents']}"
        )
        assert claim["approved_by_user_id"] == COMMITTEE_OFFICER_USER_ID

    def test_approval_books_the_full_reserve_that_the_denial_left_standing(self):
        """The resulting `net_payable_cents` is added into the insolvency file's
        `reserved_claim_cents`, which is where the association's hard claim liability now lives.

        Design: Difficulty/cross_entity_state_dependency/approval_requires_every_other_insurance_layer_to_be_resolved
        """
        env = self._recommended_with_pursuing_layer()
        advance_other_insurance(env, env["layer"]["id"], "CARRIER_DENIED")
        approve(env, COMMITTEE_OFFICER_USER_ID)

        insolvency = read_insolvency(env["insolvency"]["id"])
        assert insolvency["reserved_claim_cents"] == 3_000_000, (
            "the whole undiminished payable becomes estate reserve, got "
            f"{insolvency['reserved_claim_cents']}"
        )


class TestPolicyTermsAreHalfOpen:
    """A renewal that starts on the day the incumbent term ends does not intersect it."""

    def test_a_renewal_starting_on_the_expiration_date_is_accepted(self):
        """Because the interval is half-open, terms that merely touch at a boundary — one ending on
        the very day the next begins — do not intersect and are accepted, which is exactly how a
        renewal of the same policy number is expressed.

        Design: Difficulty/resource_temporal_overlap/policy_terms_are_half_open_so_a_touching_renewal_is_accepted
        """
        env = setup_declared_insolvency(policy_overrides=dict(INCUMBENT_TERM))
        renewal = get_success_data(
            api_client.create_policy(
                policy_payload(env["insolvency"]["id"], **RENEWAL_TERM), RECEIVER
            )
        )

        assert_transferred_policy(renewal)
        assert renewal["effective_date"] == "2026-10-01", renewal["effective_date"]
        assert renewal["status"] == "IMPORTED", renewal["status"]
        assert renewal["policy_number"] == "PA-1001"

        insolvency = read_insolvency(env["insolvency"]["id"])
        assert insolvency["policy_count"] == 2, (
            f"both terms of the renewed number are on the book, got {insolvency['policy_count']}"
        )

    def test_a_term_starting_inside_the_incumbent_term_is_refused(self):
        """A policy term is the half-open interval running from `effective_date` inclusive to
        `expiration_date` exclusive. Two policies of the same insolvency file sharing a
        `policy_number` may not have terms that intersect; an attempt to create one is refused with
        `ERR_POLICY_PERIOD_OVERLAP`.

        Design: Difficulty/resource_temporal_overlap/policy_terms_are_half_open_so_a_touching_renewal_is_accepted
        """
        env = setup_declared_insolvency(policy_overrides=dict(INCUMBENT_TERM))
        get_success_data(
            api_client.create_policy(
                policy_payload(env["insolvency"]["id"], **RENEWAL_TERM), RECEIVER
            )
        )

        response = api_client.create_policy(
            policy_payload(env["insolvency"]["id"], **OVERLAPPING_TERM), RECEIVER
        )
        validate_error(response, "ERR_POLICY_PERIOD_OVERLAP", 409)

        rows = api_client.list_policies(
            RECEIVER, {"insolvency_id": env["insolvency"]["id"], "limit": 50}
        ).json()["data"]
        assert len(rows) == 2, f"the refused term must not be stored, got {len(rows)} policies"
        insolvency = read_insolvency(env["insolvency"]["id"])
        assert insolvency["policy_count"] == 2, insolvency["policy_count"]
