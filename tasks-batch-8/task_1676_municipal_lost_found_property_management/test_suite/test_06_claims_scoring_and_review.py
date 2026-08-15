"""Claim filing, proof scoring, examination cycle, and approval (PRD §3.4)."""
from test_helpers import (
    ApiErrorId,
    approve_claim,
    assert_claimant,
    create_claim,
    create_claimant,
    create_item,
    create_location,
    create_policy,
    create_program,
    get_claim,
    get_item,
    make_claimant_headers,
    make_claims_examiner_headers,
    request_info,
    resubmit_claim,
    setup_claim_under_review,
    setup_stored_item,
    start_review,
    validate_error,
    validate_success,
    TEST_USERS,
)

EXAMINER = TEST_USERS["claims_examiner_headers"]


def test_claimant_registration_defaults_id_verified_false(api):
    """PRD §3.4: "a `PublicUser` registers with `full_name`, `email`, and an
    optional `phone`, producing a claimant record whose `id_verified` starts as
    false."

    Design: Corner/entities/claimant_defaults_id_verified_false
    """
    res = api.create_claimant({"full_name": "Pat Owner", "email": "pat@x.com"},
                              TEST_USERS["public_user_headers"])
    claimant = validate_success(res, 201)
    assert_claimant(claimant)
    assert claimant["id_verified"] is False, "id_verified starts as false"


def test_claim_proof_score_serial_only(api):
    """PRD §3.4: "It adds 30 points when the claimant's `id_verified` is true,
    30 points when `proof_serial` is asserted, 15 points when `proof_photo` is
    supplied, 15 points when `proof_description_detail` is `DETAILED`, and 10
    points when `proof_receipt` is supplied, for a maximum of 100."

    Design: Corner/calculations/proof_score_partial_weights
    """
    ctx = setup_stored_item(declared_value_cents=5000)
    claimant = create_claimant()
    claim = create_claim(ctx.item["id"], claimant["id"],
                         proof_serial=True, proof_photo=False,
                         proof_receipt=False, proof_description_detail="BRIEF")
    assert claim["proof_score"] == 30, (
        "only the serial weight applies for an unverified claimant with "
        "serial-only, BRIEF proofs")
    assert claim["status"] == "SUBMITTED"


def test_score_70_approves_mid_tier_claim(api):
    """PRD §3.4: "Proof sufficiency requires the `proof_score` to meet the
    threshold of the item's `value_tier`: at least 40 for `LOW`, at least 60
    for `MID`, and at least 80 for `HIGH`, where `HIGH` additionally requires
    the claimant's `id_verified` to be true; a shortfall is rejected with
    `ERR_CLAIM_PROOF_INSUFFICIENT` (HTTP 422)." PRD §3.4: "On success the claim
    becomes `APPROVED`, the item cascades from `STORED` or `LISTED` to
    `RELEASE_PENDING` with its version incremented".

    Design: Difficulty/combinatorial_formula/claim_proof_score_tier_threshold_branch
    """
    ctx = setup_claim_under_review(
        declared_value_cents=50000, value_tier="MID",
        proof_serial=True, proof_photo=True, proof_receipt=True,
        proof_description_detail="DETAILED")
    assert ctx.claim["proof_score"] == 70, (
        "30 serial + 15 photo + 10 receipt + 15 detail, claimant unverified")

    approved = approve_claim(ctx.claim["id"], ctx.examiner_id)
    assert approved["status"] == "APPROVED", "70 meets the MID threshold of 60"
    assert get_item(ctx.item["id"])["status"] == "RELEASE_PENDING", (
        "approval cascades the item to RELEASE_PENDING")


def test_score_70_rejected_for_high_tier_claim(api):
    """PRD §3.4: "at least 80 for `HIGH`, where `HIGH` additionally requires the
    claimant's `id_verified` to be true; a shortfall is rejected with
    `ERR_CLAIM_PROOF_INSUFFICIENT` (HTTP 422)."

    Design: Difficulty/combinatorial_formula/claim_proof_score_tier_threshold_branch
    """
    program = create_program("TRANSIT")
    create_policy(program["id"], value_tier="HIGH", retention_days=90)
    vault = create_location(program["id"], name="Vault", supports_high_value=True)
    item = create_item(program["id"], vault["id"], declared_value_cents=150000,
                       description="high laptop")
    claimant = create_claimant()
    claim = create_claim(item["id"], claimant["id"],
                         proof_serial=True, proof_photo=True, proof_receipt=True,
                         proof_description_detail="DETAILED")
    assert claim["proof_score"] == 70
    claim = start_review(claim["id"], "examiner-1")

    res = api.approve_claim(claim["id"], make_claims_examiner_headers("examiner-1"))
    validate_error(res, ApiErrorId.ERR_CLAIM_PROOF_INSUFFICIENT, expected_status=422)
    assert get_claim(claim["id"])["status"] == "UNDER_REVIEW", (
        "a failed approval leaves the claim UNDER_REVIEW")


def test_claim_info_request_cycle_returns_to_submitted(api):
    """PRD §3.4: "Requesting more information moves `UNDER_REVIEW` to
    `INFO_REQUESTED`, stores the supplied `info_request_text`, and may only be
    performed by the recording examiner". PRD §3.4: "Resubmission is the
    claimant's reply: the owning claimant moves `INFO_REQUESTED` back to
    `SUBMITTED`, replacing all four proof inputs with the resubmission payload,
    and the score is recomputed."

    Design: Difficulty/non_linear_state_machine/claim_info_request_cycle
    """
    ctx = setup_claim_under_review(declared_value_cents=5000,
                                   proof_serial=True, proof_photo=True)
    assert ctx.claim["proof_score"] == 45, "30 serial + 15 photo at filing"

    requested = request_info(ctx.claim["id"], "need receipt", ctx.examiner_id)
    assert requested["status"] == "INFO_REQUESTED"

    resubmitted = resubmit_claim(ctx.claim["id"], ctx.claimant["id"])
    assert resubmitted["status"] == "SUBMITTED", (
        "the claim loops back to a previously visited state")
    assert resubmitted["proof_score"] == 70, (
        "score recomputed on resubmission: 30+15+10+15")


def test_claim_completes_approval_after_info_cycle(api):
    """PRD §3.4: "Resubmission is the claimant's reply: the owning claimant
    moves `INFO_REQUESTED` back to `SUBMITTED`" and "On success the claim
    becomes `APPROVED`, the item cascades from `STORED` or `LISTED` to
    `RELEASE_PENDING` with its version incremented".

    Design: Difficulty/non_linear_state_machine/claim_info_request_cycle
    """
    ctx = setup_claim_under_review(declared_value_cents=5000,
                                   proof_serial=True, proof_photo=True)
    request_info(ctx.claim["id"], "need receipt", ctx.examiner_id)
    resubmit_claim(ctx.claim["id"], ctx.claimant["id"])
    start_review(ctx.claim["id"], ctx.examiner_id)

    approved = approve_claim(ctx.claim["id"], ctx.examiner_id)
    assert approved["status"] == "APPROVED", (
        "the claim completes the info-request cycle and still reaches APPROVED")
    assert get_item(ctx.item["id"])["status"] == "RELEASE_PENDING"


def test_verify_id_recomputes_proof_score(api):
    """PRD §3.4: "A `ClaimsExaminer` later marks identification as verified,
    which sets `id_verified` to true, increments the claimant's version, and
    triggers a recomputation of the proof score on every one of that claimant's
    claims currently in `SUBMITTED`, `UNDER_REVIEW`, or `INFO_REQUESTED`".

    Design: Corner/cross_cutting_layers/derived_proof_score_recompute_on_verify_id
    """
    program = create_program("TRANSIT")
    create_policy(program["id"], value_tier="HIGH", retention_days=90)
    vault = create_location(program["id"], name="Vault", supports_high_value=True)
    item = create_item(program["id"], vault["id"], declared_value_cents=150000,
                       description="laptop")
    claimant = create_claimant()
    claim = create_claim(item["id"], claimant["id"],
                         proof_serial=True, proof_photo=True, proof_receipt=True,
                         proof_description_detail="DETAILED")
    assert claim["proof_score"] == 70, "no id_verified weight before verification"
    start_review(claim["id"], "examiner-1")

    validate_success(api.verify_claimant_id(
        claimant["id"], make_claims_examiner_headers("examiner-9")), 200)
    after = get_claim(claim["id"])
    assert after["proof_score"] == 100, (
        "verification adds the 30-point id_verified weight: 70 + 30")

    approved = approve_claim(claim["id"], "examiner-1")
    assert approved["status"] == "APPROVED", (
        "100 meets the HIGH threshold of 80 and the claimant is now id-verified")
    assert get_item(item["id"])["status"] == "RELEASE_PENDING"


def test_claim_withdraw_from_approved_rejected(api):
    """PRD §3.4: "Withdrawal moves a claim from `SUBMITTED` or `INFO_REQUESTED`
    to `WITHDRAWN` and is likewise restricted to the owning claimant."
    PRD §2.7: "the target resource's current state must permit the requested
    transition, otherwise `ERR_INVALID_STATE` (HTTP 409)."

    Design: Corner/state_machines/claim_withdraw_from_approved_returns_invalid_state
    """
    ctx = setup_claim_under_review(declared_value_cents=5000,
                                   proof_serial=True, proof_photo=True)
    approve_claim(ctx.claim["id"], ctx.examiner_id)
    assert get_claim(ctx.claim["id"])["status"] == "APPROVED"

    res = api.withdraw_claim(ctx.claim["id"], make_claimant_headers(ctx.claimant["id"]))
    validate_error(res, ApiErrorId.ERR_INVALID_STATE, expected_status=409)
    assert get_claim(ctx.claim["id"])["status"] == "APPROVED"


def test_claimant_cannot_read_others_claim(api):
    """PRD §2.1: "a `Claimant` attempting to act on another claimant's resource,
    is rejected with `ERR_FORBIDDEN` (HTTP 403)." PRD §3.4: "A claimant may read
    only its own record and its own claims".

    Design: Corner/validations/claimant_cannot_read_others_claim
    """
    ctx = setup_stored_item(declared_value_cents=5000)
    owner_a = create_claimant(full_name="Owner A", email="a@x.com")
    owner_b = create_claimant(full_name="Owner B", email="b@x.com")
    claim = create_claim(ctx.item["id"], owner_a["id"])

    res = api.get_claim(claim["id"], make_claimant_headers(owner_b["id"]))
    validate_error(res, ApiErrorId.ERR_FORBIDDEN, expected_status=403)


def test_approve_cascades_item_to_release_pending(api):
    """PRD §3.4: "On success the claim becomes `APPROVED`, the item cascades
    from `STORED` or `LISTED` to `RELEASE_PENDING` with its version
    incremented".

    Design: Difficulty/transitive_cascade/claim_approval_competing_rejection_cascade
    """
    ctx = setup_claim_under_review(
        declared_value_cents=50000, value_tier="MID",
        proof_serial=True, proof_photo=True, proof_receipt=True,
        proof_description_detail="DETAILED")
    item_before = get_item(ctx.item["id"])

    approved = approve_claim(ctx.claim["id"], ctx.examiner_id)
    assert approved["status"] == "APPROVED"
    item_after = get_item(ctx.item["id"])
    assert item_after["status"] == "RELEASE_PENDING"
    assert item_after["version"] == item_before["version"] + 1, (
        "the cascade increments the item's version")


def test_approve_auto_rejects_competing_claims(api):
    """PRD §3.4: "every other claim on the same item that is in `SUBMITTED`,
    `UNDER_REVIEW`, or `INFO_REQUESTED` is auto-rejected with its
    `decision_reason` set to `ITEM_AWARDED`, each such claim's version
    incrementing."

    Design: Difficulty/transitive_cascade/claim_approval_competing_rejection_cascade
    """
    ctx = setup_stored_item(declared_value_cents=50000, value_tier="MID",
                            retention_days=30)
    owner_a = create_claimant(full_name="Owner A", email="a@x.com")
    owner_b = create_claimant(full_name="Owner B", email="b@x.com")
    claim_a = create_claim(ctx.item["id"], owner_a["id"],
                           proof_serial=True, proof_photo=True,
                           proof_receipt=True, proof_description_detail="DETAILED")
    claim_b = create_claim(ctx.item["id"], owner_b["id"],
                           proof_serial=True)
    start_review(claim_a["id"], "examiner-1")

    approve_claim(claim_a["id"], "examiner-1")
    loser = get_claim(claim_b["id"])
    assert loser["status"] == "REJECTED", (
        "the competing claim is auto-rejected when the item is awarded")
    assert loser["decision_reason"] == "ITEM_AWARDED"
