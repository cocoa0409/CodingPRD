"""Claim-filing OCC, law-enforcement referral cycle, and evidence conversion
(PRD §2.6, §3.4, §3.6)."""
from test_helpers import (
    ApiErrorId,
    confirm_pickup,
    convert_to_evidence,
    create_claim,
    create_claim_payload,
    create_claimant,
    create_item,
    create_location,
    get_claim,
    get_item,
    make_claimant_headers,
    make_police_liaison_headers,
    make_property_custodian_headers,
    publish_item,
    refer_item,
    return_to_custody,
    setup_claim_under_review,
    setup_stored_item,
    start_review,
    validate_error,
    validate_success,
)

LIAISON = make_police_liaison_headers("liaison-1")


def test_claim_with_stale_item_version_rejected(api):
    """PRD §2.6: "Filing a claim requires `expected_item_version` matching the
    claimed item's current `version`. A mismatch is rejected with
    `ERR_STALE_ITEM_VERSION` (HTTP 412), because the claimant's view of the
    item — its storage state, competing claims, and referral status — is stale
    and the claim must be re-based on a fresh read."

    Design: Corner/cross_cutting_layers/occ_claim_stale_item_version_returns_412
    """
    ctx = setup_stored_item(declared_value_cents=5000)
    stale_version = ctx.item["version"]
    cage_b = create_location(ctx.program["id"], name="Cage B")
    moved = validate_success(api.move_item(
        ctx.item["id"], cage_b["id"],
        make_property_custodian_headers("custodian-1")), 200)
    assert moved["version"] == stale_version + 1, "the move advances the item version"

    claimant = create_claimant()
    res = api.create_claim(
        create_claim_payload(ctx.item["id"], claimant["id"], stale_version),
        make_claimant_headers(claimant["id"]))
    validate_error(res, ApiErrorId.ERR_STALE_ITEM_VERSION, expected_status=412)


def test_claim_with_fresh_item_version_succeeds(api):
    """PRD §2.6: "Filing a claim requires `expected_item_version` matching the
    claimed item's current `version`." PRD §3.4: "A successfully filed claim
    starts in `SUBMITTED`, its `proof_score` is computed" and "filing itself
    increments the item's version by one".

    Design: Corner/cross_cutting_layers/occ_claim_fresh_version_succeeds
    """
    ctx = setup_stored_item(declared_value_cents=5000)
    cage_b = create_location(ctx.program["id"], name="Cage B")
    validate_success(api.move_item(
        ctx.item["id"], cage_b["id"],
        make_property_custodian_headers("custodian-1")), 200)

    claimant = create_claimant()
    before = get_item(ctx.item["id"])
    res = api.create_claim(
        create_claim_payload(ctx.item["id"], claimant["id"], before["version"]),
        make_claimant_headers(claimant["id"]))
    claim = validate_success(res, 201)
    assert claim["status"] == "SUBMITTED"

    after = get_item(ctx.item["id"])
    assert after["version"] == before["version"] + 1, (
        "filing a claim increments the item's version by exactly one")


def test_claim_against_referred_item_rejected(api):
    """PRD §3.4: "The item must be in `STORED` or `LISTED` — a claim against an
    item in any other state is rejected with `ERR_ITEM_NOT_CLAIMABLE`."
    PRD §3.4: "that stale-version check is evaluated before the claimability
    check."

    Design: Difficulty/cross_entity_state_dependency/claim_create_blocked_by_item_referral
    """
    ctx = setup_stored_item(declared_value_cents=5000)
    referral = refer_item(ctx.item["id"])
    assert referral["status"] == "REFERRED"
    assert get_item(ctx.item["id"])["status"] == "REFERRED_TO_LE"

    claimant = create_claimant()
    fresh_version = get_item(ctx.item["id"])["version"]
    res = api.create_claim(
        create_claim_payload(ctx.item["id"], claimant["id"], fresh_version),
        make_claimant_headers(claimant["id"]))
    validate_error(res, ApiErrorId.ERR_ITEM_NOT_CLAIMABLE, expected_status=409)


def test_claim_against_item_in_le_custody_rejected(api):
    """PRD §3.4: "The item must be in `STORED` or `LISTED` — a claim against an
    item in any other state is rejected with `ERR_ITEM_NOT_CLAIMABLE`."

    Design: Difficulty/cross_entity_state_dependency/claim_create_blocked_by_item_referral
    """
    ctx = setup_stored_item(declared_value_cents=5000)
    referral = refer_item(ctx.item["id"])
    confirm_pickup(referral["id"])
    assert get_item(ctx.item["id"])["status"] == "IN_LE_CUSTODY"

    claimant = create_claimant()
    fresh_version = get_item(ctx.item["id"])["version"]
    res = api.create_claim(
        create_claim_payload(ctx.item["id"], claimant["id"], fresh_version),
        make_claimant_headers(claimant["id"]))
    validate_error(res, ApiErrorId.ERR_ITEM_NOT_CLAIMABLE, expected_status=409)


def test_item_le_custody_cycle_returns_to_stored(api):
    """PRD §3.6: "the referral moves `REFERRED` to `IN_CUSTODY`, the item moves
    to `IN_LE_CUSTODY`" and "Returning the item requires the referral
    `IN_CUSTODY` and the item `IN_LE_CUSTODY`: the referral becomes `RETURNED`,
    the item goes back to `STORED` (re-occupying its slot)".

    Design: Difficulty/non_linear_state_machine/item_le_referral_cycle_return
    """
    ctx = setup_stored_item(declared_value_cents=5000)
    publish_item(ctx.item["id"])
    assert get_item(ctx.item["id"])["status"] == "LISTED"

    referral = refer_item(ctx.item["id"])
    assert get_item(ctx.item["id"])["status"] == "REFERRED_TO_LE"
    confirm_pickup(referral["id"])
    assert get_item(ctx.item["id"])["status"] == "IN_LE_CUSTODY"
    referral = return_to_custody(referral["id"])
    assert referral["status"] == "RETURNED"
    assert get_item(ctx.item["id"])["status"] == "STORED", (
        "the item loops through law-enforcement custody back to STORED")


def test_item_publishable_again_after_le_return(api):
    """PRD §3.6: "the referral becomes `RETURNED`, the item goes back to
    `STORED`" and PRD §3.2: "publishing transitions `STORED` to `LISTED`".

    Design: Difficulty/non_linear_state_machine/item_le_referral_cycle_return
    """
    ctx = setup_stored_item(declared_value_cents=5000)
    publish_item(ctx.item["id"])
    referral = refer_item(ctx.item["id"])
    confirm_pickup(referral["id"])
    return_to_custody(referral["id"])

    relisted = publish_item(ctx.item["id"])
    assert relisted["status"] == "LISTED", (
        "after the custody cycle completes, the item is publishable again")


def test_convert_to_evidence_cascades_item_and_referral(api):
    """PRD §3.6: "Converting the item to evidence, from the same `IN_CUSTODY`
    state, is terminal for the property lifecycle: the referral becomes
    `CONVERTED_TO_EVIDENCE`, the item becomes `EVIDENCE`".

    Design: Difficulty/transitive_cascade/evidence_conversion_depth3_cascade
    """
    ctx = setup_claim_under_review(declared_value_cents=5000)
    referral = refer_item(ctx.item["id"])
    confirm_pickup(referral["id"])

    referral = convert_to_evidence(referral["id"])
    assert referral["status"] == "CONVERTED_TO_EVIDENCE"
    assert get_item(ctx.item["id"])["status"] == "EVIDENCE"


def test_convert_to_evidence_rejects_stayed_claim(api):
    """PRD §3.6: "every claim on the item in `SUBMITTED`, `UNDER_REVIEW`,
    `INFO_REQUESTED`, or `STAYED` is auto-rejected with its `decision_reason`
    set to `ITEM_EVIDENCE`, each version incrementing." PRD §3.6: "every claim
    on the item in `SUBMITTED`, `UNDER_REVIEW`, or `INFO_REQUESTED` is stayed —
    moved to `STAYED` with its previous status preserved in `pre_stay_status`".

    Design: Difficulty/transitive_cascade/evidence_conversion_depth3_cascade
    """
    ctx = setup_claim_under_review(declared_value_cents=5000)
    referral = refer_item(ctx.item["id"])
    stayed = get_claim(ctx.claim["id"])
    assert stayed["status"] == "STAYED", "the referral stays the open claim"
    assert stayed["pre_stay_status"] == "UNDER_REVIEW"

    confirm_pickup(referral["id"])
    convert_to_evidence(referral["id"])
    claim = get_claim(ctx.claim["id"])
    assert claim["status"] == "REJECTED"
    assert claim["decision_reason"] == "ITEM_EVIDENCE"


def test_referral_convert_after_return_rejected(api):
    """PRD §3.6: "A referral case's terminal states are exactly `RETURNED` and
    `CONVERTED_TO_EVIDENCE`." PRD §2.7: "the target resource's current state
    must permit the requested transition, otherwise `ERR_INVALID_STATE`
    (HTTP 409)."

    Design: Corner/state_machines/referral_terminal_lockdown
    """
    ctx = setup_stored_item(declared_value_cents=5000)
    referral = refer_item(ctx.item["id"])
    confirm_pickup(referral["id"])
    referral = return_to_custody(referral["id"])
    assert referral["status"] == "RETURNED"

    res = api.convert_to_evidence(referral["id"], LIAISON)
    validate_error(res, ApiErrorId.ERR_INVALID_STATE, expected_status=409)
    final = validate_success(api.get_referral(referral["id"], LIAISON), 200)
    assert final["status"] == "RETURNED", "RETURNED is terminal for the referral"
