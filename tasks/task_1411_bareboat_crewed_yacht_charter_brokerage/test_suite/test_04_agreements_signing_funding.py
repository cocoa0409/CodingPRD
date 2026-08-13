"""Acceptance snapshot, funding schedule, signature rules, insurance gate at
signing, void, escrow tranches, and validation-priority on fund."""
from test_helpers import (
    ApiErrorId,
    accept_request,
    assert_charter_agreement,
    assert_escrow_account,
    create_fund_payload,
    create_insurance_certificate_payload,
    create_request,
    file_verified_insurance,
    fund_all,
    fund_tranche,
    get_agreement_escrow,
    list_movements,
    make_central_agent_headers,
    make_client_headers,
    make_offer,
    setup_accepted_agreement,
    setup_offered_request,
    setup_signed_agreement,
    setup_submitted_request,
    sign_as_client,
    sign_both,
    submit_request,
    TEST_USERS,
    api_client,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["platform_admin_headers"]


def test_apa_amount_and_tier_resolution_at_acceptance(api):
    """PRD section 3.4: "The charter fee is already locked from the accepted
    offer. The APA fraction resolves next — the offer's override if one was
    given, else the tier keyed on the locked fee. The APA amount
    `apa_amount_cents` is then the charter fee multiplied by the APA fraction,
    rounded half-up to whole cents."

    Design: Difficulty/combinatorial_formula/funding_schedule_pinned_eval_order
    """
    import pytest

    ctx = setup_accepted_agreement(
        offer_overrides={"quoted_charter_fee_cents": 666673},
        start_date="2026-10-01", end_date="2026-10-11",
        yacht_preset={"pricing_mode": "WEEKLY_PLUS_DAILY",
                      "security_deposit_cents": 400000})
    agreement = ctx.agreement
    assert agreement["apa_pct"] == pytest.approx(0.30), (
        "666673 is strictly below the 2,000,000-cent threshold")
    # round_half_up(666673 x 0.30) = round_half_up(200001.9) = 200002
    assert agreement["apa_amount_cents"] == 200002
    assert agreement["gratuity_pledged_cents"] == 0, (
        "zero for a bareboat charter unless the offer pledged one")


def test_tranche_amounts_odd_cent_lands_in_signing(api):
    """PRD section 3.4: "The signing tranche's charter part is half the
    charter fee, rounded half-up — and because the half is rounded up, an odd
    charter fee donates its odd cent to the signing tranche, leaving the final
    tranche the remainder. The amount due at signing, `signing_due_cents`, is
    that signing charter part plus the full `security_deposit_cents`. The
    final tranche, `final_due_cents`, is the charter fee minus the signing
    charter part, plus the full `apa_amount_cents`, plus the full
    `gratuity_pledged_cents`."

    Design: Difficulty/combinatorial_formula/funding_schedule_pinned_eval_order
    """
    ctx = setup_accepted_agreement(
        offer_overrides={"quoted_charter_fee_cents": 666673},
        start_date="2026-10-01", end_date="2026-10-11",
        yacht_preset={"pricing_mode": "WEEKLY_PLUS_DAILY",
                      "security_deposit_cents": 400000})
    agreement = ctx.agreement
    # round_half_up(666673 x 0.5) = 333337 gets the odd cent; + 400000 deposit.
    assert agreement["signing_due_cents"] == 733337
    # (666673 - 333337) + 200002 apa + 0 gratuity.
    assert agreement["final_due_cents"] == 533338
    assert (agreement["signing_due_cents"] + agreement["final_due_cents"]
            == 666673 + 200002 + 400000 + 0), (
        "the total a client will ever fund is exactly the sum of the two tranches")


def test_funds_axis_advances_independently_of_status(api):
    """PRD section 2.8: "The two axes evolve independently except at four
    pinned gates. Funding actions require the lifecycle axis to be `SIGNED`.
    Starting preparation requires the funds axis to be `FULLY_FUNDED`.
    Cancelling the agreement drives the funds axis into `REFUNDING` and
    ultimately `REFUNDED`. Completing the charter drives the funds axis into
    `SETTLING` and ultimately `SETTLED`."
    PRD section 3.4: "The first signature merely records `client_signed_at` or
    `central_agent_signed_at` and leaves the agreement in
    `PENDING_SIGNATURES`; the transition to `SIGNED` fires when the second
    distinct signature lands and both timestamps are set, incrementing the
    agreement's `version`."

    Design: Difficulty/non_linear_state_machine/agreement_parallel_status_and_funds_axes
    """
    ctx = setup_accepted_agreement(start_date="2026-11-02", end_date="2026-11-12")
    ag = ctx.agreement
    assert ag["funds_status"] == "UNFUNDED"

    # PRD §3.4 gates every signature on a VERIFIED insurance certificate.
    file_verified_insurance(ag["id"], ctx.central_agent["id"])

    after_client = sign_as_client(ag["id"], ctx.client["id"])
    assert after_client["status"] == "PENDING_SIGNATURES"
    assert after_client["funds_status"] == "UNFUNDED"
    assert after_client["client_signed_at"] is not None
    assert after_client["central_agent_signed_at"] is None

    after_ca = validate_success(
        api.sign_charter_agreement(ag["id"], ctx.ca_headers), 200)
    assert after_ca["status"] == "SIGNED"
    assert after_ca["funds_status"] == "UNFUNDED", (
        "signatures do not touch the funds axis")
    assert after_ca["version"] == ag["version"] + 2, (
        "each recorded signature is a mutation and increments the version")

    escrow = fund_tranche(ag["id"], "SIGNING", after_ca["signing_due_cents"],
                          ctx.client["id"])
    mid = validate_success(api.get_charter_agreement(ag["id"], ctx.cl_headers), 200)
    assert mid["status"] == "SIGNED", "funding does not touch the lifecycle axis"
    assert mid["funds_status"] == "DEPOSIT_HELD"


def test_start_prep_funding_gate_and_terminal_axes(api):
    """PRD section 3.7: "Starting preparation moves the agreement from
    `SIGNED` to `IN_PREP` and is gated in a fixed order: the caller must own
    the yacht (`ERR_FORBIDDEN` otherwise); every itinerary leg of the
    agreement must be `PERMITTED` — a single leg still `PLANNED`, whether for
    want of any permit or because a permit is still `REQUESTED`, was `DENIED`,
    or has `EXPIRED`, fails the gate with `ERR_PERMIT_NOT_GRANTED`; and the
    funds axis must be `FULLY_FUNDED`, else `ERR_ESCROW_INSUFFICIENT`."
    PRD section 3.9: "The penalty tier keys off that notice: ninety days or
    more before start costs ten percent of the charter fee; sixty to
    eighty-nine days costs thirty percent — so a cancellation exactly sixty
    days out lands in the thirty-percent tier while fifty-nine days lands in
    the fifty-percent tier; thirty to fifty-nine days costs fifty percent; and
    twenty-nine days or fewer costs the full fee."

    Design: Difficulty/non_linear_state_machine/agreement_parallel_status_and_funds_axes
    """
    ctx = setup_signed_agreement(start_date="2026-11-02", end_date="2026-11-12")
    ag = ctx.agreement
    fund_tranche(ag["id"], "SIGNING", ag["signing_due_cents"], ctx.client["id"])

    res = api.start_prep(ag["id"], ctx.op_headers)
    validate_error(res, ApiErrorId.ERR_ESCROW_INSUFFICIENT, expected_status=422)

    fund_tranche(ag["id"], "FINAL", ag["final_due_cents"], ctx.client["id"])
    funded = validate_success(api.get_charter_agreement(ag["id"], ctx.cl_headers), 200)
    assert funded["status"] == "SIGNED"
    assert funded["funds_status"] == "FULLY_FUNDED"

    # Cancel at the default clock 2026-08-01: 93 whole days before 2026-11-02.
    cancelled = validate_success(
        api.cancel(ag["id"], {"reason": "client change of plans"}, ctx.cl_headers),
        200)
    assert cancelled["status"] == "CANCELLED"
    assert cancelled["funds_status"] == "REFUNDED", (
        "cancelling drives the funds axis into REFUNDING and ultimately REFUNDED")
    assert cancelled["days_before_start"] == 93
    assert cancelled["cancellation_penalty_cents"] == 100000, (
        "93 days of notice is the ten-percent tier on a 1,000,000-cent fee")


def test_sign_without_certificate_rejected(api):
    """PRD section 3.4: "Signing requires a `VERIFIED` insurance certificate
    on the agreement — without one the attempt is rejected with
    `ERR_INSURANCE_NOT_VERIFIED`, a gate evaluated at the state-validity tier
    as section 2.11 describes — and it requires the two parties to sign
    exactly once each: the client caller must be the agreement's `client_id`,
    the central agent caller the agreement's `central_agent_id`, and the same
    party signing twice is rejected with `ERR_INVALID_STATE`."

    Design: Difficulty/cross_entity_state_dependency/sign_gated_by_verified_insurance
    """
    ctx = setup_accepted_agreement(start_date="2026-11-02", end_date="2026-11-12")
    res = api.sign_charter_agreement(ctx.agreement["id"], ctx.cl_headers)
    validate_error(res, ApiErrorId.ERR_INSURANCE_NOT_VERIFIED,
                   expected_status=422)


def test_sign_with_pending_certificate_rejected_then_verified_succeeds(api):
    """PRD section 3.4: "Signing requires a `VERIFIED` insurance certificate
    on the agreement — without one the attempt is rejected with
    `ERR_INSURANCE_NOT_VERIFIED`, a gate evaluated at the state-validity tier
    as section 2.11 describes — and it requires the two parties to sign
    exactly once each: the client caller must be the agreement's `client_id`,
    the central agent caller the agreement's `central_agent_id`, and the same
    party signing twice is rejected with `ERR_INVALID_STATE`."
    PRD section 3.6: "Only a `VERIFIED` certificate opens the signing gate of
    section 3.4, and after a rejection the central agent may file a
    replacement."

    Design: Difficulty/cross_entity_state_dependency/sign_gated_by_verified_insurance
    """
    ctx = setup_accepted_agreement(start_date="2026-11-02", end_date="2026-11-12")
    ag = ctx.agreement

    cert = validate_success(
        api.create_insurance_certificate(
            ag["id"],
            create_insurance_certificate_payload(ag["charter_fee_cents"],
                                                 ag["start_date"],
                                                 ag["end_date"]),
            ctx.ca_headers),
        201)
    assert cert["status"] == "PENDING"

    res = api.sign_charter_agreement(ag["id"], ctx.cl_headers)
    validate_error(res, ApiErrorId.ERR_INSURANCE_NOT_VERIFIED,
                   expected_status=422)

    verified = validate_success(
        api.verify_insurance_certificate(cert["id"], {"outcome": "VERIFIED"},
                                         ADMIN),
        200)
    assert verified["status"] == "VERIFIED"

    after_client = sign_as_client(ag["id"], ctx.client["id"])
    assert after_client["status"] == "PENDING_SIGNATURES", (
        "the first signature leaves the agreement PENDING_SIGNATURES")
    after_ca = validate_success(
        api.sign_charter_agreement(ag["id"], ctx.ca_headers), 200)
    assert after_ca["status"] == "SIGNED", (
        "the transition to SIGNED fires when the second distinct signature lands")


def test_double_signature_rejected(api):
    """PRD section 3.4: "Signing requires a `VERIFIED` insurance certificate
    on the agreement — without one the attempt is rejected with
    `ERR_INSURANCE_NOT_VERIFIED`, a gate evaluated at the state-validity tier
    as section 2.11 describes — and it requires the two parties to sign
    exactly once each: the client caller must be the agreement's `client_id`,
    the central agent caller the agreement's `central_agent_id`, and the same
    party signing twice is rejected with `ERR_INVALID_STATE`."

    Design: Corner/state_machines/double_signature_rejected
    """
    ctx = setup_accepted_agreement(start_date="2026-11-02", end_date="2026-11-12")
    file_verified_insurance(ctx.agreement["id"], ctx.central_agent["id"])
    sign_as_client(ctx.agreement["id"], ctx.client["id"])

    res = api.sign_charter_agreement(ctx.agreement["id"], ctx.cl_headers)
    validate_error(res, ApiErrorId.ERR_INVALID_STATE, expected_status=409)

    after = validate_success(
        api.get_charter_agreement(ctx.agreement["id"], ctx.cl_headers), 200)
    assert after["status"] == "PENDING_SIGNATURES", (
        "still awaiting the central agent's signature")


def test_void_success_cascade_and_void_after_signature_rejected(api):
    """PRD section 3.4: "An unsigned agreement can still be killed cleanly:
    the central agent may void it, but only while neither signature has been
    recorded — once any signature exists, voiding is rejected with
    `ERR_INVALID_STATE`. Voiding moves the agreement to `VOIDED`, releases the
    charter block (`ACTIVE` to `RELEASED`, incrementing the yacht's `version`
    by one), and cancels the source request from `ACCEPTED` to `CANCELLED` —
    the same terminal hop the cancellation cascade uses."

    Design: Corner/state_machines/void_success_cascade_and_void_after_signature_rejected
    """
    ctx = setup_accepted_agreement(start_date="2026-10-01", end_date="2026-10-11")
    ag1 = ctx.agreement
    rq1_id = ctx.request["id"]

    # Second accepted agreement on disjoint dates, carrying one signature.
    rq2 = create_request(ctx.client["id"], ctx.yacht["id"],
                         start_date="2026-12-01", end_date="2026-12-11")
    rq2 = submit_request(rq2["id"], ctx.client["id"])
    offered2 = make_offer(rq2["id"], ctx.central_agent["id"])
    ag2 = accept_request(rq2["id"], ctx.client["id"], offered2["version"])
    file_verified_insurance(ag2["id"], ctx.central_agent["id"],
                            policy_no="POL-2")
    sign_as_client(ag2["id"], ctx.client["id"])

    voided = validate_success(api.void_charter_agreement(ag1["id"], ctx.ca_headers),
                              200)
    assert voided["status"] == "VOIDED"

    blocks, _ = validate_paginated(
        api.list_agreement_availability_blocks(ag1["id"], ctx.op_headers))
    assert len(blocks) == 1 and blocks[0]["status"] == "RELEASED", (
        "voiding releases the charter block")

    source = validate_success(api.get_charter_request(rq1_id, ctx.cl_headers), 200)
    assert source["status"] == "CANCELLED", (
        "voiding cancels the source request from ACCEPTED to CANCELLED")

    res = api.void_charter_agreement(ag2["id"], ctx.ca_headers)
    validate_error(res, ApiErrorId.ERR_INVALID_STATE, expected_status=409)
    after = validate_success(api.get_charter_agreement(ag2["id"], ctx.cl_headers),
                             200)
    assert after["status"] == "PENDING_SIGNATURES"


def test_fund_tranche_order_and_amount(api):
    """PRD section 3.5: "The `SIGNING` tranche requires the funds axis to be
    `UNFUNDED`; the `FINAL` tranche requires `DEPOSIT_HELD`. Funding out of
    order — `FINAL` before `SIGNING`, or `SIGNING` twice — is rejected with
    `ERR_FUNDING_TRANCHE_OUT_OF_ORDER`, and the sequencing check runs before
    the amount check."
    PRD section 3.5: "Each funding call names a `tranche` and an
    `amount_cents`, and the amount must equal the computed due for that
    tranche to the cent — `signing_due_cents` for `SIGNING`, `final_due_cents`
    for `FINAL` — or the call is rejected with `ERR_FUNDING_AMOUNT_MISMATCH`;
    an unrecognized tranche name is a plain `ERR_INVALID_REQUEST`."

    Design: Corner/state_machines/fund_tranche_order_and_amount
    """
    # 20-day charter: fee 2000000 -> apa 0.25 -> signing 1500000, final 1500000.
    ctx = setup_signed_agreement(start_date="2026-10-30", end_date="2026-11-19")
    ag = ctx.agreement
    assert ag["signing_due_cents"] == 1500000
    assert ag["final_due_cents"] == 1500000

    res = api.fund_charter_agreement(
        ag["id"], create_fund_payload("FINAL", 1500000), ctx.cl_headers)
    validate_error(res, ApiErrorId.ERR_FUNDING_TRANCHE_OUT_OF_ORDER,
                   expected_status=422)

    res = api.fund_charter_agreement(
        ag["id"], create_fund_payload("SIGNING", 1499999), ctx.cl_headers)
    validate_error(res, ApiErrorId.ERR_FUNDING_AMOUNT_MISMATCH,
                   expected_status=422)

    escrow = fund_tranche(ag["id"], "SIGNING", 1500000, ctx.client["id"])
    assert_escrow_account(escrow)
    assert escrow["total_funded_cents"] == 1500000, (
        "the two rejected attempts posted nothing")


def test_fund_cancelled_agreement_rejected_invalid_state(api):
    """PRD section 3.5: "Funding an agreement whose lifecycle axis is not
    `SIGNED` is rejected with `ERR_INVALID_STATE`."
    PRD section 2.11: "Every request is validated in a fixed category
    pipeline, and an earlier failure masks all later checks."

    Design: Difficulty/priority_pair_validation_conflict/state_beats_fiscal_on_fund
    """
    ctx = setup_accepted_agreement(start_date="2026-10-30", end_date="2026-11-19")
    cancelled = validate_success(
        api.cancel(ctx.agreement["id"], {}, ctx.cl_headers), 200)
    assert cancelled["status"] == "CANCELLED"

    res = api.fund_charter_agreement(
        ctx.agreement["id"], create_fund_payload("SIGNING", 1), ctx.cl_headers)
    validate_error(res, ApiErrorId.ERR_INVALID_STATE, expected_status=409)


def test_rejected_fund_posts_no_movement(api):
    """PRD section 3.5: "Funding an agreement whose lifecycle axis is not
    `SIGNED` is rejected with `ERR_INVALID_STATE`."
    PRD section 3.5: "It holds `held_charter_fee_cents`, `held_apa_cents`,
    `held_deposit_cents`, and `held_gratuity_cents`, each starting at zero;
    `total_funded_cents` accumulates every `CLIENT_FUND` movement, and
    `total_released_cents` accumulates every outward movement — the three
    `RELEASE_TO_OPERATOR`, `RELEASE_TO_CENTRAL_AGENT`, and
    `RELEASE_TO_RETAIL_BROKER` types plus `REFUND_TO_CLIENT`."

    Design: Difficulty/priority_pair_validation_conflict/state_beats_fiscal_on_fund
    """
    ctx = setup_accepted_agreement(start_date="2026-10-30", end_date="2026-11-19")
    validate_success(api.cancel(ctx.agreement["id"], {}, ctx.cl_headers), 200)

    validate_error(
        api.fund_charter_agreement(
            ctx.agreement["id"], create_fund_payload("SIGNING", 1), ctx.cl_headers),
        ApiErrorId.ERR_INVALID_STATE, expected_status=409)

    escrow = get_agreement_escrow(ctx.agreement["id"])
    assert escrow["total_funded_cents"] == 0, (
        "no CLIENT_FUND movement was posted by the rejected call")


def test_insurance_coverage_window_and_uniqueness(api):
    """PRD section 3.6: "Two constraint checks guard the filing: the coverage
    must be at least the agreement's `charter_fee_cents`, else
    `ERR_INSURANCE_COVERAGE_INSUFFICIENT`; and the window must contain the
    charter window on closed bounds — `valid_from` on or before the
    agreement's `start_date`, `valid_until` on or after its `end_date` — else
    `ERR_INSURANCE_WINDOW_INVALID`."
    PRD section 3.6: "So is a duplicate filing of a livelier sort: while any
    certificate for the agreement is still `PENDING` or `VERIFIED`, submitting
    another is rejected with `ERR_INVALID_STATE`. A new certificate starts
    `PENDING`; a `PlatformAdmin` then verifies it, recording an `outcome` of
    `VERIFIED` or `REJECTED`. Only a `VERIFIED` certificate opens the signing
    gate of section 3.4, and after a rejection the central agent may file a
    replacement."

    Design: Corner/validations/insurance_coverage_window_and_uniqueness
    """
    ctx = setup_accepted_agreement(start_date="2026-11-02", end_date="2026-11-12")
    ag = ctx.agreement  # fee 1000000

    res = api.create_insurance_certificate(
        ag["id"],
        create_insurance_certificate_payload(
            ag["charter_fee_cents"], ag["start_date"], ag["end_date"],
            policy_no="POL-LOW", coverage_amount_cents=999999),
        ctx.ca_headers)
    validate_error(res, ApiErrorId.ERR_INSURANCE_COVERAGE_INSUFFICIENT,
                   expected_status=422)  # 999999 < charter_fee 1000000

    res = api.create_insurance_certificate(
        ag["id"],
        create_insurance_certificate_payload(
            ag["charter_fee_cents"], ag["start_date"], ag["end_date"],
            policy_no="POL-SHORT", valid_from="2026-11-03"),
        ctx.ca_headers)
    validate_error(res, ApiErrorId.ERR_INSURANCE_WINDOW_INVALID,
                   expected_status=422)  # valid_from after the charter start

    cert = validate_success(
        api.create_insurance_certificate(
            ag["id"],
            create_insurance_certificate_payload(
                ag["charter_fee_cents"], ag["start_date"], ag["end_date"],
                policy_no="POL-OK", valid_from="2026-11-02",
                valid_until="2026-11-12"),
            ctx.ca_headers),
        201)
    assert cert["status"] == "PENDING"

    res = api.create_insurance_certificate(
        ag["id"],
        create_insurance_certificate_payload(
            ag["charter_fee_cents"], ag["start_date"], ag["end_date"],
            policy_no="POL-DUP", valid_from="2026-11-02",
            valid_until="2026-11-12"),
        ctx.ca_headers)
    validate_error(res, ApiErrorId.ERR_INVALID_STATE, expected_status=409)

    rejected = validate_success(
        api.verify_insurance_certificate(cert["id"], {"outcome": "REJECTED"},
                                         ADMIN),
        200)
    assert rejected["status"] == "REJECTED"

    replacement = validate_success(
        api.create_insurance_certificate(
            ag["id"],
            create_insurance_certificate_payload(
                ag["charter_fee_cents"], ag["start_date"], ag["end_date"],
                policy_no="POL-FIX", valid_from="2026-11-02",
                valid_until="2026-11-12"),
            ctx.ca_headers),
        201)
    assert replacement["status"] == "PENDING", (
        "after a rejection the central agent may file a replacement")


def test_immediate_visibility_fund_response(api):
    """PRD section 2.9: "Consistency in this system is immediate: every
    mutation is fully applied before its response is rendered, so the response
    body and any subsequent read reflect the change."
    PRD section 3.5: "The signing tranche posts a `CLIENT_FUND` against the
    `CHARTER_FEE` bucket for the signing charter part — half the fee, rounded
    half-up — and a `CLIENT_FUND` against the `DEPOSIT` bucket for the full
    security deposit, and moves the funds axis from `UNFUNDED` to
    `DEPOSIT_HELD`."

    Design: Corner/consistency_model/immediate_visibility_fund_response
    """
    ctx = setup_signed_agreement(start_date="2026-10-30", end_date="2026-11-19")
    ag = ctx.agreement  # fee 2000000, deposit 500000 -> signing 1500000

    escrow = validate_success(
        api.fund_charter_agreement(
            ag["id"], create_fund_payload("SIGNING", ag["signing_due_cents"]),
            ctx.cl_headers),
        200)
    assert escrow["held_charter_fee_cents"] == 1000000
    assert escrow["held_deposit_cents"] == 500000
    assert escrow["total_funded_cents"] == 1500000, (
        "the fund response itself reflects the new escrow buckets")

    after = validate_success(api.get_charter_agreement(ag["id"], ctx.cl_headers),
                             200)
    assert after["funds_status"] == "DEPOSIT_HELD", (
        "the same transaction's effect is visible on a subsequent read")
