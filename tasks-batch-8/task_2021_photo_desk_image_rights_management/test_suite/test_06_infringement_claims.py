"""Infringement claims: intake latch, negotiation cycle, segregation of duties,
resolution cascades and the pinned settlement split (PRD §3.8)."""
from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    assert_infringement_claim,
    create_accepted_assignment,
    create_active_license,
    create_story,
    get_image_fresh,
    get_photographer_fresh,
    get_story_fresh,
    ingest_cleared_wire_image,
    intake_claim,
    make_rights_manager_headers,
    move_claim_under_review,
    validate_error,
    validate_success,
)


def test_get_claim_not_found_returns_404(api, rights_manager_headers):
    """PRD §2.8: "Resource existence — path parameters and body-referenced foreign
    keys resolve to existing resources, validated left-to-right, each surfacing
    its resource-specific not-found code (`ERR_PHOTOGRAPHER_NOT_FOUND`,
    `ERR_STORY_REQUEST_NOT_FOUND`, `ERR_ASSIGNMENT_NOT_FOUND`, `ERR_IMAGE_NOT_FOUND`,
    `ERR_LICENSE_NOT_FOUND`, `ERR_RELEASE_NOT_FOUND`, `ERR_CLAIM_NOT_FOUND`,
    `ERR_PAYMENT_RUN_NOT_FOUND`)."

    Design: Corner/entities/get_claim_not_found_returns_404
    """
    resp = api.get_claim(NON_EXISTENT_UUID, rights_manager_headers)
    validate_error(resp, ApiErrorId.ERR_CLAIM_NOT_FOUND)


def test_claim_offer_from_intake_rejected(api, rights_manager_alice_headers):
    """PRD §3.8: "From `INTAKE`, a `RightsManager` moves the claim to
    `UNDER_REVIEW`. The negotiation cycle then runs between two states: offering
    a settlement — payload `settlement_offer_cents` — moves `UNDER_REVIEW` to
    `SETTLEMENT_OFFERED`". PRD §2.8: "State-machine from-state preconditions for
    action endpoints; terminal states reject all further transitions; else
    `ERR_INVALID_STATE`."

    Design: Corner/state_machines/claim_offer_from_intake_rejected
    """
    image = ingest_cleared_wire_image()
    claim = intake_claim(image["id"], intaker_id="rm_alice")
    assert claim["status"] == "INTAKE"

    resp = api.offer_settlement(claim["id"], {"settlement_offer_cents": 40000},
                                rights_manager_alice_headers)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


def test_claim_intake_latches_image_restricted(api, rights_manager_headers):
    """PRD §3.8: "Intake stamps the claim's `intaken_by_user_id` with the caller's
    `X-User-ID`, opens the claim in `INTAKE` status, and latches the image's
    `restriction_status` from `NONE` to `RESTRICTED`, blocking new usage runs
    under §3.7's gate."

    Design: Corner/state_machines/claim_intake_latches_image_restricted
    """
    image = ingest_cleared_wire_image()
    claim = intake_claim(image["id"], intaker_id="rm_alice",
                         claim_type="COPYRIGHT_DISPUTE", description="Disputed rights")
    assert_infringement_claim(claim)
    assert claim["status"] == "INTAKE"
    assert claim["intaken_by_user_id"] == "rm_alice", "intake must stamp the caller's X-User-ID"

    after = get_image_fresh(image["id"])
    assert after["status"] == "CLEARED", "the editorial dimension is unchanged by intake"
    assert after["restriction_status"] == "RESTRICTED", "the restriction dimension latches"


def test_sod_resolver_equals_intaker_rejected(api, rights_manager_alice_headers, rights_manager_bob_headers):
    """PRD §3.8: "Resolution is restricted by segregation of duties: the resolving
    `RightsManager`'s `X-User-ID` must differ from the claim's
    `intaken_by_user_id`, or the resolve is rejected with
    `ERR_SEGREGATION_OF_DUTIES` (HTTP 403)."

    Design: Corner/validations/sod_resolver_equals_intaker_rejected
    """
    image = ingest_cleared_wire_image()
    claim = intake_claim(image["id"], intaker_id="rm_alice")
    move_claim_under_review(claim["id"], user_id="rm_alice")

    resp = api.resolve_claim(claim["id"], {"outcome": "DISMISSED"}, rights_manager_alice_headers)
    validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)

    resolved = validate_success(
        api.resolve_claim(claim["id"], {"outcome": "DISMISSED"}, rights_manager_bob_headers), 200,
    )
    assert resolved["status"] == "DISMISSED"


def test_resolve_upheld_missing_amount_rejected(api, rights_manager_bob_headers):
    """PRD §3.8: "The payload must include `settlement_amount_cents`, greater than
    zero and no more than `claimed_amount_cents`, else `ERR_INVALID_REQUEST`."

    Design: Corner/validations/resolve_upheld_missing_amount_rejected
    """
    image = ingest_cleared_wire_image()
    claim = intake_claim(image["id"], intaker_id="rm_alice")
    move_claim_under_review(claim["id"], user_id="rm_alice")

    resp = api.resolve_claim(claim["id"], {"outcome": "UPHELD"}, rights_manager_bob_headers)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


# ---------------------------------------------------------------------------
# Queue A: non_linear_state_machine / claim_offer_counter_negotiation_cycle
# ---------------------------------------------------------------------------

def _setup_wire_image_with_claim_under_review():
    image = ingest_cleared_wire_image()
    claim = intake_claim(image["id"], intaker_id="rm_alice",
                         claimant_name="Rival Wire", claim_type="COPYRIGHT_DISPUTE",
                         description="Disputed exclusivity", claimed_amount_cents=80000)
    move_claim_under_review(claim["id"], user_id="rm_alice")
    return image, claim


def test_offer_counter_cycle_tracks_latest_proposal(api, rights_manager_alice_headers):
    """PRD §3.8: "The negotiation cycle then runs between two states: offering a
    settlement — payload `settlement_offer_cents` — moves `UNDER_REVIEW` to
    `SETTLEMENT_OFFERED` and records the offer on `proposed_settlement_cents`;
    recording the claimant's counter — payload `counter_amount_cents` — moves
    `SETTLEMENT_OFFERED` to `COUNTERED` and overwrites `proposed_settlement_cents`
    with the counter; a renewed offer from `COUNTERED` returns the claim to
    `SETTLEMENT_OFFERED` with `proposed_settlement_cents` updated again."

    Design: Difficulty/non_linear_state_machine/claim_offer_counter_negotiation_cycle
    """
    _image, claim = _setup_wire_image_with_claim_under_review()

    offered = validate_success(
        api.offer_settlement(claim["id"], {"settlement_offer_cents": 50000},
                             rights_manager_alice_headers), 200,
    )
    assert offered["status"] == "SETTLEMENT_OFFERED"
    assert offered["proposed_settlement_cents"] == 50000

    countered = validate_success(
        api.counter_claim(claim["id"], {"counter_amount_cents": 70000},
                          rights_manager_alice_headers), 200,
    )
    assert countered["status"] == "COUNTERED"
    assert countered["proposed_settlement_cents"] == 70000, "the counter overwrites the offer"

    reoffered = validate_success(
        api.offer_settlement(claim["id"], {"settlement_offer_cents": 60000},
                             rights_manager_alice_headers), 200,
    )
    assert reoffered["status"] == "SETTLEMENT_OFFERED"
    assert reoffered["proposed_settlement_cents"] == 60000


def test_resolve_from_negotiated_state_records_settlement(api, rights_manager_bob_headers):
    """PRD §3.8: "Resolution carries an `outcome` of `UPHELD` or `DISMISSED` and
    is available from `UNDER_REVIEW`, `SETTLEMENT_OFFERED`, `COUNTERED`, or
    `ESCALATED`." PRD §3.8: "for wire and stock images it is zero, and the
    organization absorbs the remainder either way."

    Design: Difficulty/non_linear_state_machine/claim_offer_counter_negotiation_cycle
    """
    _image, claim = _setup_wire_image_with_claim_under_review()
    validate_success(api.offer_settlement(claim["id"], {"settlement_offer_cents": 50000},
                                          make_rights_manager_headers("rm_alice")), 200)
    validate_success(api.counter_claim(claim["id"], {"counter_amount_cents": 70000},
                                       make_rights_manager_headers("rm_alice")), 200)
    validate_success(api.offer_settlement(claim["id"], {"settlement_offer_cents": 60000},
                                          make_rights_manager_headers("rm_alice")), 200)

    resolved = validate_success(
        api.resolve_claim(claim["id"],
                          {"outcome": "UPHELD", "settlement_amount_cents": 60000},
                          rights_manager_bob_headers),
        200,
    )
    assert resolved["status"] == "RESOLVED"
    assert resolved["settlement_amount_cents"] == 60000
    assert resolved["photographer_clawback_cents"] == 0, (
        "a WIRE image has no photographer to claw back from"
    )


# ---------------------------------------------------------------------------
# Queue A: transitive_cascade / claim_upheld_cascade_image_license_story
# ---------------------------------------------------------------------------

def _setup_story_image_license_with_claim():
    """Story (budget 30000) + CLEARED WIRE image with an ACTIVE story-linked
    DIGITAL license (fee 12000) + an UNDER_REVIEW claim intaken by rm_alice."""
    story = create_story(slug="flood-aftermath", headline="Flood aftermath")
    image = ingest_cleared_wire_image()
    lic = create_active_license(image["id"], usage_scope="DIGITAL",
                                story_request_id=story["id"])
    assert lic["fee_cents"] == 12000
    claim = intake_claim(image["id"], intaker_id="rm_alice",
                         claimant_name="Rival Wire", description="License terms breached")
    move_claim_under_review(claim["id"], user_id="rm_alice")
    return story, image, lic, claim


def test_upheld_resolution_latches_image_and_revokes_licenses(api, rights_manager_bob_headers):
    """PRD §3.8: "Second, the cascades fire: the image's `restriction_status`
    latches to `RESTRICTED`; every `ACTIVE` license on the image moves to
    `REVOKED`; and each revoked license that named a story releases its
    `fee_cents` from that story's `committed_cents`."

    Design: Difficulty/transitive_cascade/claim_upheld_cascade_image_license_story
    """
    _story, image, lic, claim = _setup_story_image_license_with_claim()

    resolved = validate_success(
        api.resolve_claim(claim["id"],
                          {"outcome": "UPHELD", "settlement_amount_cents": 50000},
                          rights_manager_bob_headers),
        200,
    )
    assert resolved["status"] == "RESOLVED"

    assert get_image_fresh(image["id"])["restriction_status"] == "RESTRICTED"
    lic_after = validate_success(api.get_license(lic["id"], rights_manager_bob_headers), 200)
    assert lic_after["status"] == "REVOKED", "hop 2: every ACTIVE license on the image revokes"


def test_upheld_resolution_releases_story_budget(api, rights_manager_bob_headers, photo_editor_headers):
    """PRD §3.8: "Second, the cascades fire: the image's `restriction_status`
    latches to `RESTRICTED`; every `ACTIVE` license on the image moves to
    `REVOKED`; and each revoked license that named a story releases its
    `fee_cents` from that story's `committed_cents`."

    Design: Difficulty/transitive_cascade/claim_upheld_cascade_image_license_story
    """
    story, _image, lic, claim = _setup_story_image_license_with_claim()
    committed_before = get_story_fresh(story["id"], headers=photo_editor_headers)["committed_cents"]
    assert committed_before == 12000, "activation committed the license fee"

    validate_success(
        api.resolve_claim(claim["id"],
                          {"outcome": "UPHELD", "settlement_amount_cents": 50000},
                          rights_manager_bob_headers),
        200,
    )
    committed_after = get_story_fresh(story["id"], headers=photo_editor_headers)["committed_cents"]
    assert committed_after == 0, (
        f"hop 3: the revoked license's fee 12000 must be released, got {committed_after}"
    )


# ---------------------------------------------------------------------------
# Queue A: combinatorial_formula / settlement_clawback_order_pinned
# ---------------------------------------------------------------------------

def _setup_staff_photographer_with_accrued_and_claim():
    """STAFF photographer (per-image 40000) with one accepted assignment image
    (accrued == 40000) and an UNDER_REVIEW claim on that image."""
    bundle = create_accepted_assignment()
    image_id = bundle["images"][0]["id"]
    claim = intake_claim(image_id, intaker_id="rm_alice",
                         claimant_name="Pix Agency", claim_type="COPYRIGHT_DISPUTE",
                         description="Overlapping exclusive sold elsewhere",
                         claimed_amount_cents=100000)
    move_claim_under_review(claim["id"], user_id="rm_alice")
    return bundle, image_id, claim


def test_clawback_computed_from_settlement_alone(api, rights_manager_bob_headers):
    """PRD §3.8: "First, the photographer's share is computed from the settlement
    alone: for an `ASSIGNMENT` image, `photographer_clawback_cents` is 30 percent
    of `settlement_amount_cents` rounded half-up to integer cents; for wire and
    stock images it is zero, and the organization absorbs the remainder either
    way."

    Design: Difficulty/combinatorial_formula/settlement_clawback_order_pinned
    """
    _bundle, _image_id, claim = _setup_staff_photographer_with_accrued_and_claim()
    resolved = validate_success(
        api.resolve_claim(claim["id"],
                          {"outcome": "UPHELD", "settlement_amount_cents": 100000},
                          rights_manager_bob_headers),
        200,
    )
    assert resolved["status"] == "RESOLVED"
    # round_half_up(100000 x 0.30) = 30000, from the settlement alone.
    assert resolved["photographer_clawback_cents"] == 30000, (
        f"clawback must be 30 percent of the settlement, got {resolved['photographer_clawback_cents']}"
    )


def test_clawback_debits_accrual_last_with_floor(api, rights_manager_bob_headers, finance_admin_headers):
    """PRD §3.8: "Third — last — the photographer's `accrued_earnings_cents` is
    debited by `photographer_clawback_cents`, flooring at zero."

    Design: Difficulty/combinatorial_formula/settlement_clawback_order_pinned
    """
    bundle, _image_id, claim = _setup_staff_photographer_with_accrued_and_claim()
    before = get_photographer_fresh(bundle["photographer"]["id"], headers=finance_admin_headers)
    assert before["accrued_earnings_cents"] == 40000

    validate_success(
        api.resolve_claim(claim["id"],
                          {"outcome": "UPHELD", "settlement_amount_cents": 100000},
                          rights_manager_bob_headers),
        200,
    )
    after = get_photographer_fresh(bundle["photographer"]["id"], headers=finance_admin_headers)
    assert after["accrued_earnings_cents"] == 10000, (
        f"40000 accrued minus the 30000 clawback leaves 10000, got {after['accrued_earnings_cents']}"
    )
