"""Compliance review workflow: the revision cycle, activation gating, and the
submit-review / decision validations (PRD §3.3, §3.4)."""
import pytest

from test_helpers import (
    api_client, validate_success, validate_error, get_success_data,
    assert_compliance_review,
    create_listing_payload, create_media_asset_payload, create_decision_payload,
    create_agent, owner_headers, create_draft_listing, upload_photo,
    upload_and_ready_photo, create_submittable_listing, submit_listing,
    approve_review, reject_review, create_active_listing, get_listing,
    TEST_USERS,
    ApiErrorId,
)

MC = TEST_USERS["marketing_coordinator_headers"]
CO = TEST_USERS["compliance_officer_headers"]


def _status_change_events(api, listing_id):
    data = get_success_data(
        api.list_listing_events(listing_id, MC, params={"event_type": "STATUS_CHANGE"}), 200)
    return data


class TestComplianceRevisionCycle:
    def test_revision_cycle_status_change_trail(self, api):
        """PRD §3.3: "Rejection is a cascading event. The listing moves from
        `PENDING_REVIEW` to `COMPLIANCE_HOLD`, appending a `STATUS_CHANGE` event and
        incrementing `version`."
        PRD §3.3: "From `COMPLIANCE_HOLD`, the agent or coordinator revises the
        listing back to `DRAFT` to fix the flagged remarks."
        PRD §3.7: "Every lifecycle transition in this document appends a
        `STATUS_CHANGE` entry and increments the listing's `version` by one"

        Design: Difficulty/non_linear_state_machine/listing_compliance_revision_cycle
        """
        agent, listing, _ = create_submittable_listing()
        review = submit_listing(listing, agent)
        reject_review(review)

        held = get_listing(listing["id"])
        assert held["lifecycle_status"] == "COMPLIANCE_HOLD"

        revised = validate_success(api.revise_listing(listing["id"], owner_headers(agent)), 200)
        assert revised["lifecycle_status"] == "DRAFT", "revise loops back to the cycle start"

        review2 = submit_listing(listing, agent)
        approve_review(review2)
        active = validate_success(api.activate_listing(listing["id"], owner_headers(agent)), 200)
        assert active["lifecycle_status"] == "ACTIVE"

        events = _status_change_events(api, listing["id"])
        transitions = [(e["from_lifecycle"], e["to_lifecycle"]) for e in events]
        assert [e["seq"] for e in events] == [1, 2, 3, 4, 5]
        assert transitions == [
            ("DRAFT", "PENDING_REVIEW"),
            ("PENDING_REVIEW", "COMPLIANCE_HOLD"),
            ("COMPLIANCE_HOLD", "DRAFT"),
            ("DRAFT", "PENDING_REVIEW"),
            ("PENDING_REVIEW", "ACTIVE"),
        ]

    def test_revision_cycle_keeps_full_review_history(self, api):
        """PRD §3.3: "a rejection additionally stores `flagged_terms` on the review."
        PRD §3.3: "The listing's full review history remains listable at any time."

        Design: Difficulty/non_linear_state_machine/listing_compliance_revision_cycle
        """
        agent, listing, _ = create_submittable_listing()
        review1 = submit_listing(listing, agent)
        reject_review(review1, flagged_terms=["adults only"])
        validate_success(api.revise_listing(listing["id"], owner_headers(agent)), 200)
        review2 = submit_listing(listing, agent)
        approve_review(review2)

        reviews = get_success_data(api.list_compliance_reviews(listing["id"], MC), 200)
        assert len(reviews) == 2, f"expected 2 reviews, got {len(reviews)}"
        first, second = reviews[0], reviews[1]
        assert first["status"] == "REJECTED"
        assert first["flagged_terms"] == ["adults only"]
        assert second["status"] == "APPROVED"
        for r in reviews:
            assert_compliance_review(r)
            assert r["decided_at"] is not None


class TestActivationComplianceGate:
    def test_activate_with_pending_review_rejected(self, api):
        """PRD §3.4: "the compliance gate, which requires the listing's most recently
        created compliance review to be `APPROVED`, failing with
        `ERR_COMPLIANCE_NOT_APPROVED` otherwise."

        Design: Difficulty/cross_entity_state_dependency/activation_requires_latest_review_approved
        """
        agent, listing, _ = create_submittable_listing()
        submit_listing(listing, agent)  # review stays PENDING

        res = api.activate_listing(listing["id"], owner_headers(agent))
        validate_error(res, ApiErrorId.ERR_COMPLIANCE_NOT_APPROVED, expected_status=409)
        assert get_listing(listing["id"])["lifecycle_status"] == "PENDING_REVIEW"

    def test_activate_after_rejection_and_resubmission_rejected(self, api):
        """PRD §3.4: "the compliance gate, which requires the listing's most recently
        created compliance review to be `APPROVED`, failing with
        `ERR_COMPLIANCE_NOT_APPROVED` otherwise."
        A rejected-then-resubmitted listing's latest review is PENDING, not APPROVED.

        Design: Difficulty/cross_entity_state_dependency/activation_requires_latest_review_approved
        """
        agent, listing, _ = create_submittable_listing()
        review1 = submit_listing(listing, agent)
        reject_review(review1)
        validate_success(api.revise_listing(listing["id"], owner_headers(agent)), 200)
        submit_listing(listing, agent)  # latest review is PENDING

        res = api.activate_listing(listing["id"], owner_headers(agent))
        validate_error(res, ApiErrorId.ERR_COMPLIANCE_NOT_APPROVED, expected_status=409)
        assert get_listing(listing["id"])["lifecycle_status"] == "PENDING_REVIEW"


def test_submit_review_from_active_rejected_invalid_state(api):
    """PRD §3.3: "Submitting a listing for review moves it from `DRAFT` to
    `PENDING_REVIEW` and is guarded by four checks, evaluated in this order."
    PRD §2.9: "Lifecycle and entity state — the current state permits the operation,
    else `ERR_INVALID_STATE`"

    Design: Corner/state_machines/submit_review_from_active_rejected_invalid_state
    """
    agent, active = create_active_listing()
    res = api.submit_review(active["id"], owner_headers(agent))
    validate_error(res, ApiErrorId.ERR_INVALID_STATE, expected_status=409)
    assert get_listing(active["id"])["lifecycle_status"] == "ACTIVE"
    reviews = get_success_data(api.list_compliance_reviews(active["id"], MC), 200)
    assert len(reviews) == 1, "no new review may be created by the rejected submission"


def test_submit_incomplete_listing_returns_listing_incomplete(api):
    """PRD §3.3: "Second, the listing must be complete — `bedrooms`, `bathrooms`,
    `square_feet`, `marketing_remarks`, and `mls_number` all non-null — else
    `ERR_LISTING_INCOMPLETE`."

    Design: Corner/validations/submit_incomplete_listing_returns_listing_incomplete
    """
    agent = create_agent()
    listing = create_draft_listing(agent, complete=False)
    res = api.submit_review(listing["id"], owner_headers(agent))
    validate_error(res, ApiErrorId.ERR_LISTING_INCOMPLETE, expected_status=422)
    assert get_listing(listing["id"])["lifecycle_status"] == "DRAFT"


def test_submit_without_ready_photo_returns_no_ready_photo(api):
    """PRD §3.3: "Third, the listing must have at least one media asset of `kind`
    `PHOTO` in `READY` status, else `ERR_NO_READY_PHOTO`."

    Design: Corner/validations/submit_without_ready_photo_returns_no_ready_photo
    """
    agent = create_agent()
    listing = create_draft_listing(agent, complete=True)
    upload_photo(listing, agent)  # left UPLOADED, never marked ready
    res = api.submit_review(listing["id"], owner_headers(agent))
    validate_error(res, ApiErrorId.ERR_NO_READY_PHOTO, expected_status=422)
    assert get_listing(listing["id"])["lifecycle_status"] == "DRAFT"


def test_submit_twice_returns_review_already_pending(api):
    """PRD §3.3: "Fourth, there must be no other compliance review still `PENDING`
    for this listing, else `ERR_REVIEW_ALREADY_PENDING`."

    Design: Corner/validations/submit_twice_returns_review_already_pending
    """
    agent, listing, _ = create_submittable_listing()
    submit_listing(listing, agent)
    res = api.submit_review(listing["id"], owner_headers(agent))
    validate_error(res, ApiErrorId.ERR_REVIEW_ALREADY_PENDING, expected_status=409)
    reviews = get_success_data(api.list_compliance_reviews(listing["id"], MC), 200)
    assert len(reviews) == 1, "exactly one PENDING review may exist"


def test_decision_on_decided_review_returns_review_decided(api):
    """PRD §3.3: "The review must still be `PENDING`; deciding an already-decided
    review is rejected with `ERR_REVIEW_DECIDED`."

    Design: Corner/validations/decision_on_decided_review_returns_review_decided
    """
    agent, listing, _ = create_submittable_listing()
    review = submit_listing(listing, agent)
    approve_review(review)
    res = api.decide_compliance_review(
        review["id"], create_decision_payload("REJECTED"), CO)
    validate_error(res, ApiErrorId.ERR_REVIEW_DECIDED, expected_status=409)

    reviews = get_success_data(api.list_compliance_reviews(listing["id"], MC), 200)
    assert len(reviews) == 1
    assert reviews[0]["status"] == "APPROVED", "original decision must be unchanged"
    assert get_listing(listing["id"])["lifecycle_status"] == "PENDING_REVIEW"
