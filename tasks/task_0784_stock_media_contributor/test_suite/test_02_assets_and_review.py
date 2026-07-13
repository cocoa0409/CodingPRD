"""Asset creation, metadata editing, the review lifecycle, and similar-reject distance."""
from test_helpers import (
    validate_success, validate_error, validate_paginated, get_success_data,
    is_valid_uuid, ApiErrorId, TEST_USERS,
    make_contributor_headers,
    register_contributor, onboard_active_contributor,
    create_draft_asset, create_in_review_asset, create_accepted_asset,
    assert_review_is_immutable_shape,
)

REVIEWER = TEST_USERS["reviewer_headers"]


def test_create_asset_missing_title_is_validation_error(api):
    """PRD §3.3: "supplies a non-empty `title` of at most 200 characters".
    PRD §2.9: "then generic field/format validation (`ERR_VALIDATION`, 422)".

    Design: Corner/entities/corner_create_asset_missing_required_title
    """
    c = register_contributor(api, display_name="Al")
    ch = make_contributor_headers(c["id"])
    payload = {"contributor_id": c["id"], "media_type": "PHOTO", "content_category": "COMMERCIAL",
               "keywords": ["x"], "perceptual_hash": "aaaa"}
    validate_error(api.create_asset(payload, ch), ApiErrorId.ERR_VALIDATION.value)


def test_create_asset_invalid_media_type_is_validation_error(api):
    """PRD §3.3: "a `media_type` of `PHOTO`, `VIDEO`, or `VECTOR`".
    PRD §2.9: "then generic field/format validation (`ERR_VALIDATION`, 422)".

    Design: Corner/entities/corner_create_asset_invalid_media_type_enum
    """
    c = register_contributor(api, display_name="Be")
    ch = make_contributor_headers(c["id"])
    payload = {"contributor_id": c["id"], "title": "T", "media_type": "GIF",
               "content_category": "COMMERCIAL", "keywords": ["x"], "perceptual_hash": "aaaa"}
    validate_error(api.create_asset(payload, ch), ApiErrorId.ERR_VALIDATION.value)


def test_asset_system_fields_are_server_minted(api):
    """PRD §2.4: "`id` is a server-minted UUID with no type prefix."
    PRD §3.3: "A contributor uploads an asset by creating it in `status` `DRAFT`."

    Design: Corner/entities/corner_asset_id_and_system_fields_generated
    """
    c = register_contributor(api, display_name="Ce")
    a = create_draft_asset(api, c["id"], title="T")
    assert is_valid_uuid(a["id"]), "id must be a UUID with no type prefix"
    assert a["status"] == "DRAFT"
    assert a["version"] == 1


def test_patch_asset_metadata_in_draft_bumps_version(api):
    """PRD §3.3: "While an asset sits in `DRAFT` or `REJECTED`, its owner may edit `title`,
    `keywords`, and `perceptual_hash`."
    PRD §2.4: "`version` is an integer that starts at 1 on creation and increments by exactly 1
    on every mutation of that resource".

    Design: Corner/endpoints/corner_patch_asset_metadata_in_draft
    """
    c = register_contributor(api, display_name="Pa")
    a = create_draft_asset(api, c["id"], keywords=["old"])
    ch = make_contributor_headers(c["id"])
    updated = validate_success(api.update_asset(a["id"], {"keywords": ["new", "tags"]}, ch))
    assert updated["keywords"] == ["new", "tags"]
    assert updated["version"] == 2


def test_claim_draft_asset_rejected_invalid_state(api):
    """PRD §3.3: "A reviewer claims a `SUBMITTED` asset, advancing it from `SUBMITTED` to
    `IN_REVIEW`; claiming an asset that is not `SUBMITTED` yields `ERR_INVALID_STATE`."

    Design: Corner/state_machines/corner_claim_from_draft_invalid_state
    """
    c = register_contributor(api, display_name="Da")
    a = create_draft_asset(api, c["id"])
    validate_error(api.claim_asset(a["id"], REVIEWER), ApiErrorId.ERR_INVALID_STATE.value)


def test_submit_requires_release_without_release_id(api):
    """PRD §3.3: "a submission of a release-requiring asset with no `model_release_id` is rejected
    with `ERR_RELEASE_REQUIRED`."

    Design: Corner/state_machines/corner_submit_requires_release_without_release_id
    """
    c = register_contributor(api, display_name="Su")
    a = create_draft_asset(api, c["id"], requires_release=True)
    ch = make_contributor_headers(c["id"])
    validate_error(api.submit_asset(a["id"], ch), ApiErrorId.ERR_RELEASE_REQUIRED.value)


def test_reject_without_reason_rejected(api):
    """PRD §3.3: "A reject `decision` must carry a `reject_reason` — one of `QUALITY`, `SIMILAR`,
    `METADATA`, or `MISSING_RELEASE` — and a reject that omits it is rejected with
    `ERR_MISSING_REJECT_REASON`."

    Design: Corner/state_machines/corner_reject_without_reason
    """
    c = register_contributor(api, display_name="Rj")
    a = create_in_review_asset(api, c["id"])
    validate_error(api.create_review(a["id"], {"decision": "REJECT"}, REVIEWER),
                   ApiErrorId.ERR_MISSING_REJECT_REASON.value)


def test_similar_reject_without_target_rejected(api):
    """PRD §3.3: "When `reject_reason` is `SIMILAR`, the reviewer must name the earlier accepted
    asset the submission collides with via `similar_to_asset_id`; a `SIMILAR` reject without it is
    rejected with `ERR_MISSING_SIMILAR_TARGET`."

    Design: Corner/state_machines/corner_similar_reject_without_target
    """
    c = register_contributor(api, display_name="Si")
    a = create_in_review_asset(api, c["id"])
    validate_error(api.create_review(a["id"], {"decision": "REJECT", "reject_reason": "SIMILAR"}, REVIEWER),
                   ApiErrorId.ERR_MISSING_SIMILAR_TARGET.value)


def test_asset_review_is_immutable_audit_record(api):
    """PRD §2.4: "The `AssetReview` entity is the sole exception: it is an immutable audit record
    and therefore carries only `id` and `created_at`. It has neither `updated_at` nor `version`,
    because once written it is never mutated."

    Design: Corner/entities/corner_asset_review_immutable_no_version
    """
    c = onboard_active_contributor(api, tax_id="US-2")
    asset = create_accepted_asset(api, c["id"])
    reviews, _meta = validate_paginated(api.list_reviews(REVIEWER, params={"asset_id": asset["id"]}))
    assert len(reviews) >= 1, "accepting an asset produces an AssetReview"
    assert_review_is_immutable_shape(reviews[0])


def test_rejected_asset_resubmits_to_submitted(api):
    """PRD §3.3: "An asset that has previously been rejected can re-enter review through the same
    submission action — a `REJECTED` asset returns to `SUBMITTED`, and on this resubmission the
    asset's `reject_reason` is cleared."

    Design: Difficulty/non_linear_state_machine/asset_reject_then_resubmit_cycle
    """
    c = register_contributor(api, display_name="Ed")
    a = create_in_review_asset(api, c["id"])
    get_success_data(api.create_review(a["id"], {"decision": "REJECT", "reject_reason": "QUALITY"}, REVIEWER))
    ch = make_contributor_headers(c["id"])
    resubmitted = validate_success(api.submit_asset(a["id"], ch))
    assert resubmitted["status"] == "SUBMITTED"


def test_resubmit_clears_reject_reason(api):
    """PRD §3.3: "a `REJECTED` asset returns to `SUBMITTED`, and on this resubmission the asset's
    `reject_reason` is cleared."

    Design: Difficulty/non_linear_state_machine/asset_reject_then_resubmit_cycle
    """
    c = register_contributor(api, display_name="Ed2")
    a = create_in_review_asset(api, c["id"])
    get_success_data(api.create_review(a["id"], {"decision": "REJECT", "reject_reason": "QUALITY"}, REVIEWER))
    ch = make_contributor_headers(c["id"])
    resubmitted = validate_success(api.submit_asset(a["id"], ch))
    assert resubmitted["reject_reason"] is None


def test_similar_reject_at_distance_5_is_valid(api):
    """PRD §3.3: "A `SIMILAR` reject is valid only when that distance is at most 5; a distance of
    exactly 5 still qualifies as similar, while a distance of 6 or more does not, in which case the
    reject is refused with `ERR_NOT_SIMILAR_ENOUGH`."

    Design: Difficulty/boundary_precision_check/similar_distance_5_vs_6
    """
    c = onboard_active_contributor(api, tax_id="US-S")
    a_orig = create_accepted_asset(api, c["id"], perceptual_hash="0000", title="Orig")
    b = create_in_review_asset(api, c["id"], perceptual_hash="001f", title="NearDup")  # distance 5
    get_success_data(api.create_review(
        b["id"], {"decision": "REJECT", "reject_reason": "SIMILAR", "similar_to_asset_id": a_orig["id"]}, REVIEWER))
    asset_b = get_success_data(api.get_asset(b["id"], REVIEWER))
    assert asset_b["status"] == "REJECTED"
    assert asset_b["reject_reason"] == "SIMILAR"


def test_similar_reject_at_distance_6_is_refused(api):
    """PRD §3.3: "A `SIMILAR` reject is valid only when that distance is at most 5; a distance of
    exactly 5 still qualifies as similar, while a distance of 6 or more does not, in which case the
    reject is refused with `ERR_NOT_SIMILAR_ENOUGH`."

    Design: Difficulty/boundary_precision_check/similar_distance_5_vs_6
    """
    c = onboard_active_contributor(api, tax_id="US-S2")
    a_orig = create_accepted_asset(api, c["id"], perceptual_hash="0000", title="Orig")
    d = create_in_review_asset(api, c["id"], perceptual_hash="003f", title="Distinct")  # distance 6
    validate_error(api.create_review(
        d["id"], {"decision": "REJECT", "reject_reason": "SIMILAR", "similar_to_asset_id": a_orig["id"]}, REVIEWER),
        ApiErrorId.ERR_NOT_SIMILAR_ENOUGH.value)
