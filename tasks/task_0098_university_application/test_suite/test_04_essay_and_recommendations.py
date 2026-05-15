"""Essay attach/edit and recommendation-letter workflow tests.

Covers PRD §3.4 (essays, customization score) and PRD §3.5
(recommendations: REQUESTED/ACCEPTED/SUBMITTED/DECLINED/EXPIRED,
weak-letter rule, reassign loop).
"""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    assert_essay,
    assert_recommendation,
    attach_essay_payload,
    attach_strong_essay,
    create_applicant,
    create_application,
    create_program,
    create_recommendation,
    create_recommendation_payload,
    create_university,
    accept_recommendation,
    decline_recommendation,
    make_applicant_headers,
    make_recommender_headers,
    NON_EXISTENT_UUID,
    setup_applicant_with_application,
    setup_application_ready_to_submit,
    setup_submitted_application,
    setup_strong_recommendations,
    submit_letter,
    TEST_USERS,
    validate_error,
    validate_success,
)


# ---------------------------------------------------------------------------
# Essay attachment (PRD §3.4)
# ---------------------------------------------------------------------------
class TestEssayAttach:

    def test_attach_essay_creates_submission_and_links_application(self, api):
        """PRD §3.4: "A successful attachment creates an EssaySubmission,
        populates its word_count by whitespace-tokenizing body and
        counting the resulting tokens, computes its customization_score,
        and writes the new submission's id back onto the application's
        essay_id."
        """
        applicant, uni, prog, app = setup_applicant_with_application()
        res = api.attach_essay(
            app["id"],
            attach_essay_payload(prompt_code="P-1", body="word " * 400),
            make_applicant_headers(applicant["id"]),
        )
        essay = validate_success(res, expected_status=201)
        assert_essay(essay)
        assert essay["application_id"] == app["id"]
        # Re-read application — essay_id should be set.
        app_after = validate_success(
            api.get_application(
                app["id"], make_applicant_headers(applicant["id"]),
            )
        )
        assert app_after["essay_id"] == essay["id"]

    def test_attach_essay_word_count_matches_whitespace_tokenization(
        self, api,
    ):
        """PRD §3.4: "populates its word_count by whitespace-tokenizing
        body and counting the resulting tokens..."

        Claim: an essay body containing 400 whitespace-separated tokens
        yields word_count == 400.
        """
        applicant, uni, prog, app = setup_applicant_with_application()
        body = " ".join(["token"] * 400)
        res = api.attach_essay(
            app["id"],
            attach_essay_payload(prompt_code="P-1", body=body),
            make_applicant_headers(applicant["id"]),
        )
        essay = validate_success(res, expected_status=201)
        assert essay["word_count"] == 400, (
            f"word_count expected 400 (whitespace-tokenized), "
            f"got {essay['word_count']}"
        )

    def test_attach_essay_body_too_short_yields_err_essay_length(self, api):
        """PRD §3.4: "The body length must lie in the inclusive range
        from 250 to 6500 characters; outside that window the request
        is rejected with ERR_ESSAY_LENGTH."
        """
        applicant, uni, prog, app = setup_applicant_with_application()
        res = api.attach_essay(
            app["id"],
            attach_essay_payload(prompt_code="P-1", body="x" * 249),
            make_applicant_headers(applicant["id"]),
        )
        validate_error(res, ApiErrorId.ERR_ESSAY_LENGTH.value)

    def test_attach_essay_body_at_minimum_accepted(self, api):
        """PRD §3.4: "The body length must lie in the inclusive range
        from 250 to 6500 characters..."

        Boundary: 250 chars is the inclusive lower bound — must be accepted.
        """
        applicant, uni, prog, app = setup_applicant_with_application()
        res = api.attach_essay(
            app["id"],
            attach_essay_payload(prompt_code="P-1", body="x" * 250),
            make_applicant_headers(applicant["id"]),
        )
        validate_success(res, expected_status=201)

    def test_attach_essay_body_too_long_yields_err_essay_length(self, api):
        """PRD §3.4: "The body length must lie in the inclusive range
        from 250 to 6500 characters; outside that window the request
        is rejected with ERR_ESSAY_LENGTH."
        """
        applicant, uni, prog, app = setup_applicant_with_application()
        res = api.attach_essay(
            app["id"],
            attach_essay_payload(prompt_code="P-1", body="x" * 6501),
            make_applicant_headers(applicant["id"]),
        )
        validate_error(res, ApiErrorId.ERR_ESSAY_LENGTH.value)


# ---------------------------------------------------------------------------
# Essay edit (PRD §3.4)
# ---------------------------------------------------------------------------
class TestEssayEdit:

    def test_patch_essay_after_submit_yields_invalid_state(self, api):
        """PRD §3.4: "attempting an essay edit once the application has
        left DRAFT is rejected with ERR_INVALID_STATE."
        """
        ctx = setup_submitted_application(round_="REGULAR_DECISION")
        res = api.patch_essay(
            ctx["essay"]["id"],
            {"body": "y" * 500},
            make_applicant_headers(ctx["applicant"]["id"]),
        )
        validate_error(res, ApiErrorId.ERR_INVALID_STATE.value)


# ---------------------------------------------------------------------------
# Recommendation create (PRD §3.5)
# ---------------------------------------------------------------------------
class TestRecommendationCreate:

    def test_create_recommendation_starts_in_requested(self, api):
        """PRD §3.5: "The request starts in REQUESTED, with
        invitation_expires_at set to the moment of creation plus 21
        days; letter_body and letter_word_count are null."
        """
        applicant, uni, prog, app = setup_applicant_with_application()
        res = api.create_recommendation(
            app["id"],
            create_recommendation_payload(),
            make_applicant_headers(applicant["id"]),
        )
        rec = validate_success(res, expected_status=201)
        assert_recommendation(rec)
        assert rec["status"] == "REQUESTED"
        assert rec.get("letter_body") is None
        assert rec.get("letter_word_count") is None


# ---------------------------------------------------------------------------
# Recommendation flow (PRD §3.5)
# ---------------------------------------------------------------------------
class TestRecommendationFlow:

    def test_recommender_accept_transitions_to_accepted(self, api):
        """PRD §3.5: "The recommender accepts (transitioning the
        request REQUESTED → ACCEPTED)..."

        Identity check: the recommender's X-User-ID must match the
        recommender_email (PRD §2.1). Helper uses make_recommender_headers.
        """
        applicant, uni, prog, app = setup_applicant_with_application()
        rec = create_recommendation(applicant["id"], app["id"])
        res = api.accept_recommendation(
            rec["id"], make_recommender_headers(rec["recommender_email"]),
        )
        data = validate_success(res)
        assert data["status"] == "ACCEPTED"

    def test_recommender_decline_transitions_to_declined(self, api):
        """PRD §3.5: "...or declines (transitioning REQUESTED → DECLINED)."
        """
        applicant, uni, prog, app = setup_applicant_with_application()
        rec = create_recommendation(applicant["id"], app["id"])
        res = api.decline_recommendation(
            rec["id"], make_recommender_headers(rec["recommender_email"]),
        )
        data = validate_success(res)
        assert data["status"] == "DECLINED"

    def test_recommender_id_mismatch_yields_forbidden(self, api):
        """PRD §2.1: "A recommender may read or act on a
        RecommendationRequest only when the value of X-User-ID matches
        the recommender_email recorded on the request."

        Claim: a Recommender call with X-User-ID != recommender_email
        is rejected with ERR_FORBIDDEN.
        """
        applicant, uni, prog, app = setup_applicant_with_application()
        rec = create_recommendation(applicant["id"], app["id"])
        # Mint headers for a DIFFERENT email.
        wrong_headers = make_recommender_headers("wrong@example.com")
        res = api.accept_recommendation(rec["id"], wrong_headers)
        validate_error(res, ApiErrorId.ERR_FORBIDDEN.value)

    def test_submit_letter_sets_letter_word_count(self, api):
        """PRD §3.5: "The transition ACCEPTED → SUBMITTED computes
        letter_word_count by whitespace-tokenizing letter_body and
        counting tokens."
        """
        applicant, uni, prog, app = setup_applicant_with_application()
        rec = create_recommendation(applicant["id"], app["id"])
        rec = accept_recommendation(rec)
        body = " ".join(["word"] * 250)
        res = api.submit_letter(
            rec["id"], {"letter_body": body},
            make_recommender_headers(rec["recommender_email"]),
        )
        data = validate_success(res)
        assert data["status"] == "SUBMITTED"
        assert data["letter_word_count"] == 250

    def test_submit_letter_below_200_words_yields_err_weak_letter(self, api):
        """PRD §3.5: "A letter whose letter_word_count is below 200 is
        recorded — the transition still completes — but the
        submit-letter request is rejected with ERR_WEAK_LETTER (HTTP
        422), and the letter does not count toward the application's
        recommendation requirement..."
        """
        applicant, uni, prog, app = setup_applicant_with_application()
        rec = create_recommendation(applicant["id"], app["id"])
        rec = accept_recommendation(rec)
        body = " ".join(["word"] * 100)  # only 100 words, < 200
        res = api.submit_letter(
            rec["id"], {"letter_body": body},
            make_recommender_headers(rec["recommender_email"]),
        )
        validate_error(res, ApiErrorId.ERR_WEAK_LETTER.value)

    def test_submit_letter_at_200_words_succeeds(self, api):
        """PRD §3.5: weak-letter threshold is "below 200" — exactly 200
        does not trigger ERR_WEAK_LETTER.

        Boundary: word_count == 200 must succeed.
        """
        applicant, uni, prog, app = setup_applicant_with_application()
        rec = create_recommendation(applicant["id"], app["id"])
        rec = accept_recommendation(rec)
        body = " ".join(["word"] * 200)
        res = api.submit_letter(
            rec["id"], {"letter_body": body},
            make_recommender_headers(rec["recommender_email"]),
        )
        data = validate_success(res)
        assert data["status"] == "SUBMITTED"
        assert data["letter_word_count"] == 200


# ---------------------------------------------------------------------------
# Reassign loop (PRD §3.5)
# ---------------------------------------------------------------------------
class TestRecommendationReassign:

    def test_reassign_after_decline_returns_to_requested(self, api):
        """PRD §3.5: "When the recommender has declined, the applicant
        may re-solicit a different teacher by reassigning the request
        — supplying a new recommender_email while the linked
        application is in DRAFT returns the request to REQUESTED,
        refreshes invitation_expires_at to the current clock plus 21
        days, and writes the new recommender_email."
        """
        applicant, uni, prog, app = setup_applicant_with_application()
        rec = create_recommendation(applicant["id"], app["id"])
        rec = decline_recommendation(rec)
        assert rec["status"] == "DECLINED"
        # Reassign — new email.
        res = api.reassign_recommendation(
            rec["id"], {"recommender_email": "new.teacher@example.com"},
            make_applicant_headers(applicant["id"]),
        )
        data = validate_success(res)
        assert data["status"] == "REQUESTED"
        assert data["recommender_email"] == "new.teacher@example.com"
