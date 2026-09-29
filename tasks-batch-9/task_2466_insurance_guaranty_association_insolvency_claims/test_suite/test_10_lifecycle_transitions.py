"""Declared lifecycle transitions: batch conversion, intake, the order and the levy."""

from test_helpers import (
    TEST_USERS,
    api_client,
    assert_assessment,
    assert_covered_claim,
    assert_instant_equals,
    assert_member_assessment,
    assert_poc_transfer,
    assert_referral,
    assert_transferred_policy,
    convert_poc_transfer,
    create_policy,
    pay_member_levy,
    poc_claim_record,
    poc_policy_record,
    premium_refund_payload,
    raise_referral,
    read_assessment,
    read_claim,
    read_insolvency,
    read_member_assessment,
    read_policy,
    read_vendor_assignment,
    respond_to_referral,
    screen_claim,
    setup_certified_assessment,
    setup_claim_under_adjustment,
    setup_declared_insolvency,
    setup_delivered_poc_batch,
    setup_presented_claim,
    setup_triggered_insolvency,
    trigger_insolvency,
    validate_error,
    validate_paginated,
)

ADMIN = TEST_USERS["association_admin_headers"]
RECEIVER = TEST_USERS["receiver_liaison_headers"]
ANALYST = TEST_USERS["coverage_analyst_headers"]
SECOND_ANALYST = TEST_USERS["second_coverage_analyst_headers"]

BATCH_POLICY_RECORD = poc_policy_record(
    policy_number="PA-2001",
    policyholder_name="Ada Renner",
    policyholder_net_worth_cents=50_000_000,
)
BATCH_CLAIM_RECORD = poc_claim_record(
    policy_number="PA-2001",
    claimant_name="Ben Ortiz",
    gross_loss_cents=900_000,
)

LIVE_TERM = {
    "policy_number": "PA-1001",
    "policyholder_name": "Ada Renner",
    "effective_date": "2025-10-01",
    "expiration_date": "2026-10-01",
    "annual_premium_cents": 1_200_000,
}
LAPSED_TERM = {
    "policy_number": "PA-0900",
    "policyholder_name": "Dora Vance",
    "effective_date": "2024-10-01",
    "expiration_date": "2025-10-01",
    "annual_premium_cents": 1_200_000,
}

BIG_LOSS_CLAIM = {
    "claim_number": "C-1",
    "claimant_name": "Ben Ortiz",
    "gross_loss_cents": 4_500_000,
}
STALE_LOSS_CLAIM = {
    "claim_number": "C-1",
    "claimant_name": "Ben Ortiz",
    "loss_date": "2024-05-01",
    "gross_loss_cents": 900_000,
}
OHIO_CLAIM = {
    "claim_number": "C-1",
    "claimant_name": "Ben Ortiz",
    "claimant_state_code": "OH",
    "gross_loss_cents": 900_000,
}
OHIO_ADJUSTER = {
    "vendor_name": "Kestrel Claims Services",
    "settlement_authority_cents": 900_000,
    "hourly_rate_cents": 18_000,
    "engagement_start": "2026-08-01",
    "engagement_end": "2026-08-31",
}
SINGLE_MEMBER = [
    {
        "naic_code": "20001",
        "insurer_name": "Huron Standard Insurance",
        "direct_written_premium_cents": 10_000_000,
    }
]


class TestProofOfClaimBatchConversion:
    """The receiver's batch is inert until conversion, and conversion runs once."""

    def test_a_clean_batch_materialises_one_policy_and_one_claim(self):
        """When every element passes, the batch moves `RECEIVED → CONVERTED`: one transferred policy
        is created per `POLICY` element and one covered claim per `CLAIM` element, each with
        `source_transfer_id` set to the batch's own `id`, each claim matched to the transferred policy
        sharing its `policy_number`; `converted_count` is set equal to `record_count`,
        `rejected_count` to 0 and `rejection_reasons` to an empty array; and the insolvency file's
        `policy_count` is recomputed.

        Design: Corner/state_machines/poc_transfer_conversion_materialises_policies_and_claims
        """
        env = setup_delivered_poc_batch(records=[BATCH_POLICY_RECORD, BATCH_CLAIM_RECORD])
        delivered = env["transfer"]
        assert_poc_transfer(delivered)
        assert delivered["record_count"] == 2, delivered["record_count"]
        assert delivered["status"] == "RECEIVED", delivered["status"]

        converted = convert_poc_transfer(env)
        assert converted["status"] == "CONVERTED", converted["status"]
        assert converted["converted_count"] == 2, converted["converted_count"]
        assert converted["rejected_count"] == 0, converted["rejected_count"]
        assert converted["rejection_reasons"] == [], converted["rejection_reasons"]

        policies, _ = validate_paginated(
            api_client.list_policies(RECEIVER, {"source_transfer_id": delivered["id"]})
        )
        assert len(policies) == 1, f"one POLICY element mints one policy, got {len(policies)}"
        assert_transferred_policy(policies[0])
        assert policies[0]["status"] == "IMPORTED", policies[0]["status"]
        assert policies[0]["policy_number"] == "PA-2001"

        claims, _ = validate_paginated(
            api_client.list_claims(ANALYST, {"source_transfer_id": delivered["id"]})
        )
        assert len(claims) == 1, f"one CLAIM element mints one claim, got {len(claims)}"
        assert_covered_claim(claims[0])
        assert claims[0]["status"] == "RECEIVED", claims[0]["status"]
        assert claims[0]["policy_id"] == policies[0]["id"], (
            "the claim must be matched to the policy sharing its policy_number"
        )
        assert read_insolvency(env["insolvency"]["id"])["policy_count"] == 1

    def test_a_second_conversion_of_the_same_batch_is_refused(self):
        """Requesting conversion on a batch that is not in `RECEIVED` is refused with
        `ERR_TRANSFER_INVALID_STATE`, which makes conversion effectively idempotent by refusal rather
        than by silent replay.

        Design: Corner/state_machines/converting_a_poc_transfer_twice_returns_transfer_invalid_state
        """
        env = setup_delivered_poc_batch(records=[BATCH_POLICY_RECORD])
        transfer_id = env["transfer"]["id"]
        first = convert_poc_transfer(env)
        assert first["status"] == "CONVERTED", first["status"]
        assert first["converted_count"] == 1, first["converted_count"]

        validate_error(
            api_client.convert_poc_transfer(transfer_id, RECEIVER),
            "ERR_TRANSFER_INVALID_STATE",
            409,
        )

        replayed = api_client.get_poc_transfer(transfer_id, RECEIVER).json()["data"]
        assert replayed["status"] == "CONVERTED", replayed["status"]
        assert replayed["converted_count"] == 1, (
            f"the refusal must not re-run the pass, got {replayed['converted_count']}"
        )
        assert read_insolvency(env["insolvency"]["id"])["policy_count"] == 1, (
            "the already materialised policy row must not be duplicated"
        )


class TestClaimIntakeAndScreeningStates:
    """A claim is unpriced at intake, and a denial is the end of its road."""

    def test_a_freshly_presented_claim_is_priced_at_nothing(self):
        """The claim is created in `RECEIVED` with `filed_at_utc` stamped from the logical clock, with
        `source_transfer_id` null when filed directly, with `paid_amount_cents` and `remand_count` at
        0, with `cap_binding` at `NONE`, with `pre_referral_status`, `referred_to_state_code`,
        `denial_reason`, `screened_by_user_id`, `approved_by_user_id`, `recommended_amount_cents`,
        `recommended_by_vendor_name` and `recommended_at_utc` all null, and with the next monotone
        `sequence` value assigned by the server.

        Design: Corner/state_machines/new_claim_starts_in_received_with_a_zero_payable
        """
        env = setup_presented_claim(
            claim_overrides=dict(BIG_LOSS_CLAIM), policy_overrides=dict(LIVE_TERM)
        )
        claim = env["claim"]

        assert_covered_claim(claim)
        assert claim["status"] == "RECEIVED", claim["status"]
        assert claim["net_payable_cents"] == 0, (
            f"nothing is priced before screening, got {claim['net_payable_cents']}"
        )
        assert claim["covered_layer_cents"] == 0, claim["covered_layer_cents"]
        assert claim["paid_amount_cents"] == 0, claim["paid_amount_cents"]
        assert claim["remand_count"] == 0, claim["remand_count"]
        assert claim["screened_by_user_id"] is None
        assert claim["cap_binding"] == "NONE", claim["cap_binding"]

        insolvency = read_insolvency(env["insolvency"]["id"])
        assert insolvency["reserved_claim_cents"] == 0, (
            f"an unscreened claim books no estate reserve, got {insolvency['reserved_claim_cents']}"
        )

    def test_a_denied_claim_cannot_be_screened_a_second_time(self):
        """A `decision` of `DENIED` moves the claim `RECEIVED → DENIED_NOT_COVERED` instead. The
        supplied reason code is stored in `denial_reason`, `screened_by_user_id` is recorded from the
        acting `X-User-ID` exactly as on the covered path, `net_payable_cents` is left at 0 so that the
        claim can never enter the distribution waterfall, every vendor engagement on the claim whose
        `status` is `ASSIGNED` is closed, and the claim's `version` is incremented by one.
        `DENIED_NOT_COVERED` is terminal.

        Design: Corner/state_machines/rescreening_a_denied_claim_returns_claim_invalid_state
        """
        env = setup_presented_claim(
            claim_overrides=dict(STALE_LOSS_CLAIM), policy_overrides=dict(LIVE_TERM)
        )
        denied = screen_claim(
            env,
            "DENIED",
            analyst_user_id="analyst-1",
            denial_reason="loss predates the policy term",
        )
        assert denied["status"] == "DENIED_NOT_COVERED", denied["status"]

        response = api_client.screen_claim(
            env["claim"]["id"], {"decision": "COVERED"}, SECOND_ANALYST
        )
        validate_error(response, "ERR_CLAIM_INVALID_STATE", 409)

        after = read_claim(env["claim"]["id"])
        assert after["status"] == "DENIED_NOT_COVERED", after["status"]
        assert after["denial_reason"] == "loss predates the policy term", after["denial_reason"]
        assert after["net_payable_cents"] == 0, after["net_payable_cents"]
        assert after["screened_by_user_id"] == "analyst-1", (
            f"the refused rescreen must not overwrite the first analyst, got "
            f"{after['screened_by_user_id']}"
        )


class TestTheLiquidationOrderFiresOnce:
    """The triggering event is a one-way door with a conditional cascade per policy."""

    def test_recording_the_triggering_event_twice_is_refused(self):
        """Recording the triggering event carries an additional single-shot guard — it requires
        `status` to be exactly `DECLARED`, and a second attempt on a file already in `TRIGGERED` is
        refused with `ERR_INSOLVENCY_ALREADY_TRIGGERED`.

        Design: Corner/state_machines/triggering_the_same_insolvency_twice_is_refused
        """
        env = setup_triggered_insolvency(policy_overrides=dict(LIVE_TERM))
        first = read_insolvency(env["insolvency"]["id"])
        assert first["status"] == "TRIGGERED", first["status"]
        assert_instant_equals(first["triggered_at_utc"], "2026-08-01T00:00:00Z")

        validate_error(
            api_client.trigger_insolvency(env["insolvency"]["id"], ADMIN),
            "ERR_INSOLVENCY_ALREADY_TRIGGERED",
            409,
        )

        after = read_insolvency(env["insolvency"]["id"])
        assert after["status"] == "TRIGGERED", after["status"]
        assert after["triggered_at_utc"] == first["triggered_at_utc"], (
            "the refused second order must not restamp the triggering instant"
        )
        assert after["version"] == first["version"], (
            f"a refusal bumps no version, got {after['version']} after {first['version']}"
        )
        policy = read_policy(env["policy"]["id"])
        assert policy["unexpired_days"] == 184, (
            f"the already cancelled policy must not be re-cancelled, got "
            f"{policy['unexpired_days']}"
        )

    def test_the_cascade_cancels_the_live_term_and_expires_the_lapsed_one(self):
        """Every transferred policy in `IMPORTED` whose `expiration_date` falls on or before the
        `liquidation_order_date` moves `IMPORTED → EXPIRED_BEFORE_ORDER` instead: its
        `cancellation_date` is left null and its `unexpired_days` stays 0 — which is precisely why no
        unearned premium refund can ever be filed on such a policy — and its `version` is likewise
        incremented by one.

        Design: Corner/state_machines/the_order_cancels_unexpired_policies_and_leaves_expired_ones_alone
        """
        env = setup_declared_insolvency(policy_overrides=dict(LIVE_TERM))
        lapsed = create_policy(env["insolvency"]["id"], **LAPSED_TERM)

        triggered = trigger_insolvency(env["insolvency"]["id"])
        assert triggered["status"] == "TRIGGERED", triggered["status"]
        assert triggered["policy_count"] == 2, (
            f"both branches of the cascade stay on the book, got {triggered['policy_count']}"
        )

        live = read_policy(env["policy"]["id"])
        assert live["status"] == "CANCELLED_BY_ORDER", live["status"]
        assert live["cancellation_date"] == "2026-03-31", live["cancellation_date"]
        assert live["unexpired_days"] == 184, live["unexpired_days"]

        dead = read_policy(lapsed["id"])
        assert dead["status"] == "EXPIRED_BEFORE_ORDER", dead["status"]
        assert dead["cancellation_date"] is None, dead["cancellation_date"]
        assert dead["unexpired_days"] == 0, dead["unexpired_days"]

    def test_a_policy_that_expired_before_the_order_earns_no_refund(self):
        """Exactly one refund may exist per policy: a `CoverageAnalyst` files it, and the operation is
        admissible only on a policy whose `status` is `CANCELLED_BY_ORDER` — a policy still in
        `IMPORTED`, or one that expired before the order and sits in `EXPIRED_BEFORE_ORDER`, is
        refused with `ERR_POLICY_NOT_CANCELLED` — and only while that policy's `up_refund_filed` is
        still false, a second attempt being refused with `ERR_UP_REFUND_ALREADY_FILED`.

        Design: Corner/state_machines/premium_refund_on_a_policy_that_expired_before_the_order_is_refused
        """
        env = setup_triggered_insolvency(policy_overrides=dict(LAPSED_TERM))
        policy = read_policy(env["policy"]["id"])
        assert policy["status"] == "EXPIRED_BEFORE_ORDER", policy["status"]

        response = api_client.create_premium_refund(
            policy["id"], premium_refund_payload("PRO_RATA", policy["version"]), ANALYST
        )
        validate_error(response, "ERR_POLICY_NOT_CANCELLED", 409)

        after = read_policy(policy["id"])
        assert after["status"] == "EXPIRED_BEFORE_ORDER", after["status"]
        assert after["cancellation_date"] is None, after["cancellation_date"]
        assert after["unexpired_days"] == 0, after["unexpired_days"]
        assert after["up_refund_filed"] is False, (
            "the refused filing must not mark the policy as refunded"
        )
        insolvency = read_insolvency(env["insolvency"]["id"])
        assert insolvency["pending_up_liability_cents"] == 0, (
            f"no refund exposure may be booked, got {insolvency['pending_up_liability_cents']}"
        )


class TestBubblingTransitions:
    """Two transitions a parent never asks for: the referred-out claim and the settled levy."""

    def test_an_accepted_referral_sends_the_claim_out_and_zeroes_its_payable(self):
        """On `ACCEPTED` the claim moves `REFERRAL_PENDING → REFERRED_OUT`, which is terminal here.
        `referred_to_state_code` is set to the referral's `target_state_code`, `pre_referral_status` is
        cleared to null, every vendor engagement on the claim whose `status` is `ASSIGNED` is closed,
        and `net_payable_cents` is set to 0 so that the departed claim leaves this association's
        waterfall entirely and stops contributing to `reserved_claim_cents`.

        Design: Corner/state_machines/accepted_referral_transfers_the_claim_out_and_zeroes_the_payable
        """
        env = setup_claim_under_adjustment(
            claim_overrides=dict(OHIO_CLAIM),
            assignment_overrides=dict(OHIO_ADJUSTER),
            policy_overrides=dict(LIVE_TERM),
        )
        assert env["claim"]["status"] == "ADJUSTING", env["claim"]["status"]
        assert env["claim"]["net_payable_cents"] == 890_000, env["claim"]["net_payable_cents"]

        raise_referral(env, "OH", "CLAIMANT_RESIDENCE")
        parked = read_claim(env["claim"]["id"])
        assert parked["status"] == "REFERRAL_PENDING", parked["status"]
        assert read_insolvency(env["insolvency"]["id"])["referral_pending_count"] == 1

        referral = respond_to_referral(env, "ACCEPTED", "Ohio association assumes the claim")
        assert_referral(referral)
        assert referral["status"] == "ACCEPTED", referral["status"]

        claim = read_claim(env["claim"]["id"])
        assert claim["status"] == "REFERRED_OUT", claim["status"]
        assert claim["net_payable_cents"] == 0, (
            f"the departed claim leaves the waterfall, got {claim['net_payable_cents']}"
        )
        assert claim["referred_to_state_code"] == "OH", claim["referred_to_state_code"]

        assignment = read_vendor_assignment(claim["id"], env["assignment"]["id"])
        assert assignment["status"] == "CLOSED", assignment["status"]

        insolvency = read_insolvency(env["insolvency"]["id"])
        assert insolvency["referral_pending_count"] == 0, insolvency["referral_pending_count"]
        assert insolvency["reserved_claim_cents"] == 0, insolvency["reserved_claim_cents"]

    def test_paying_the_last_levy_settles_the_parent_assessment(self):
        """When every invoice of an assessment has reached `PAID`, the assessment itself bubbles up
        `CERTIFIED → SETTLED` and its `collected_amount_cents` is set equal to its
        `levied_amount_cents`.

        Design: Corner/state_machines/assessment_settles_once_every_member_levy_is_paid
        """
        env = setup_certified_assessment(
            member_specs=SINGLE_MEMBER,
            needed_amount_cents=150_000,
            policy_overrides=dict(LIVE_TERM),
        )
        assert env["assessment"]["status"] == "CERTIFIED", env["assessment"]["status"]
        invoice = env["member_assessment"]
        assert invoice["levied_amount_cents"] == 150_000, invoice["levied_amount_cents"]
        assert invoice["billing_status"] == "INVOICED", invoice["billing_status"]

        paid = pay_member_levy(env, 150_000, "WIRE-1")
        assert_member_assessment(paid)
        assert paid["billing_status"] == "PAID", paid["billing_status"]
        assert paid["paid_amount_cents"] == 150_000, paid["paid_amount_cents"]

        assessment = read_assessment(env["assessment"]["id"])
        assert_assessment(assessment)
        assert assessment["status"] == "SETTLED", (
            f"the parent settles without an operator call, got {assessment['status']}"
        )
        assert assessment["collected_amount_cents"] == 150_000, (
            assessment["collected_amount_cents"]
        )

        reread = read_member_assessment(invoice["id"])
        assert reread["recoupment_status"] == "NOT_STARTED", (
            f"cash collection leaves the recoupment dimension alone, got "
            f"{reread['recoupment_status']}"
        )
