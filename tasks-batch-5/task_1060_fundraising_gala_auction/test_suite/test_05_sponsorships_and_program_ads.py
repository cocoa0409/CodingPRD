"""Sponsorship funding and the program-ad review cycle."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    assert_program_ad,
    confirm_sponsor,
    make_sponsor_headers,
    read_program_ad,
    read_sponsor,
    review_program_ad,
    setup_ad_at_revision_budget,
    setup_sponsor_with_ad,
    validate_error,
    validate_success,
)


class TestProgramAdReviewCycle:
    """PRD §3.4's CHANGES_REQUESTED → SUBMITTED → IN_REVIEW loop."""

    def test_resubmit_returns_ad_to_submitted_and_increments_revision_count(self, api):
        """PRD §3.4: "The sponsoring organization may resubmit, moving the ad
        `CHANGES_REQUESTED → SUBMITTED` with a fresh `artwork_ref` that replaces
        the old one, which increases the ad's `revision_count` by one and
        advances its `version`."

        Design: Difficulty/non_linear_state_machine/program_ad_review_cycles_back_from_changes_requested
        """
        env = setup_sponsor_with_ad(ad_state="CHANGES_REQUESTED")
        assert env["ad"]["status"] == "CHANGES_REQUESTED"

        response = api.resubmit_program_ad(
            env["ad"]["id"], "art-v2", make_sponsor_headers(env["sponsor"]["id"])
        )
        ad = validate_success(response, 200)

        assert_program_ad(ad)
        assert ad["status"] == "SUBMITTED", (
            f"Resubmission returns the ad to a state it already occupied, got "
            f"{ad['status']}"
        )
        assert ad["revision_count"] == 1, (
            f"Each resubmission advances revision_count by one, got "
            f"{ad['revision_count']}"
        )
        assert ad["artwork_ref"] == "art-v2", "The fresh artwork replaces the old one"

    def test_resubmitted_ad_can_re_enter_review(self, api):
        """PRD §3.4: "`BEGIN_REVIEW` takes a `SUBMITTED` ad to `IN_REVIEW`."
        PRD §3.4: "The cycle `CHANGES_REQUESTED → SUBMITTED → IN_REVIEW →
        CHANGES_REQUESTED` may therefore repeat, but only within a budget of two
        completed resubmissions: a resubmission is permitted only while
        `revision_count` is strictly less than 2, and a third attempt is refused
        with `ERR_AD_REVISION_LIMIT`."

        Design: Difficulty/non_linear_state_machine/program_ad_review_cycles_back_from_changes_requested
        """
        env = setup_sponsor_with_ad(ad_state="CHANGES_REQUESTED")
        api.resubmit_program_ad(
            env["ad"]["id"], "art-v2", make_sponsor_headers(env["sponsor"]["id"])
        )

        response = api.review_program_ad(
            env["ad"]["id"], {"decision": "BEGIN_REVIEW"},
            TEST_USERS["organizer_headers"],
        )
        ad = validate_success(response, 200)

        assert ad["status"] == "IN_REVIEW", (
            f"The resubmitted ad re-enters review, got {ad['status']}"
        )
        assert ad["revision_count"] == 1, "Re-entering review does not consume budget"


class TestAdApprovalRequiresConfirmedSponsor:
    """PRD §3.4's cross-entity gate from ProgramAd onto its Sponsor."""

    def test_approve_ad_under_pending_sponsor_is_refused(self, api):
        """PRD §3.4: "`APPROVE` takes an `IN_REVIEW` ad to `APPROVED`, and
        additionally requires that the ad's owning sponsor be in `CONFIRMED`;
        approving an ad whose sponsor has not yet fully funded its commitment is
        refused with `ERR_SPONSOR_NOT_CONFIRMED`."

        Design: Difficulty/cross_entity_state_dependency/ad_approval_rejected_because_sponsor_still_pending
        """
        env = setup_sponsor_with_ad(ad_state="IN_REVIEW")
        assert read_sponsor(env["sponsor"]["id"])["status"] == "PENDING"

        response = api.review_program_ad(
            env["ad"]["id"], {"decision": "APPROVE"}, TEST_USERS["organizer_headers"]
        )

        validate_error(response, ApiErrorId.ERR_SPONSOR_NOT_CONFIRMED.value, 409)
        assert read_program_ad(env["ad"]["id"])["status"] == "IN_REVIEW", (
            "A refused approval leaves the ad in review"
        )

    def test_approve_ad_succeeds_once_sponsor_is_confirmed(self, api):
        """PRD §3.4: "Confirmation is a `FinanceOfficer` action recording
        sponsorship cash: the officer submits a `paid_amount_cents` figure,
        which is added to the sponsor's running `paid_amount_cents`."
        PRD §3.4: "On success the sponsor moves `PENDING → CONFIRMED` and its
        `version` advances."
        PRD §3.4: "`APPROVE` takes an `IN_REVIEW` ad to `APPROVED`, and
        additionally requires that the ad's owning sponsor be in `CONFIRMED`;
        approving an ad whose sponsor has not yet fully funded its commitment is
        refused with `ERR_SPONSOR_NOT_CONFIRMED`."

        Design: Difficulty/cross_entity_state_dependency/ad_approval_rejected_because_sponsor_still_pending
        """
        env = setup_sponsor_with_ad(ad_state="IN_REVIEW")

        sponsor = confirm_sponsor(env["sponsor"]["id"], 250_000)
        assert sponsor["status"] == "CONFIRMED", (
            f"Full funding confirms the sponsorship, got {sponsor['status']}"
        )
        assert sponsor["paid_amount_cents"] == 250_000

        ad = review_program_ad(env["ad"]["id"], "APPROVE")
        assert ad["status"] == "APPROVED", (
            f"The same approval now succeeds, got {ad['status']}"
        )


def test_sponsor_confirm_below_commitment_is_refused(api):
    """PRD §3.4: "The sponsor must currently be `PENDING`, and the payment must
    bring the running total to at least the `commitment_cents` promised — a
    partial payment that leaves the sponsor short is refused with
    `ERR_SPONSOR_UNDERFUNDED` and records nothing."

    Design: Corner/validations/sponsor_confirm_below_commitment_is_refused
    """
    env = setup_sponsor_with_ad(ad_state="SUBMITTED")

    response = api.confirm_sponsor(
        env["sponsor"]["id"], 100_000, TEST_USERS["finance_headers"]
    )

    validate_error(response, ApiErrorId.ERR_SPONSOR_UNDERFUNDED.value, 422)
    sponsor = read_sponsor(env["sponsor"]["id"])
    assert sponsor["status"] == "PENDING", "A short payment leaves the sponsor PENDING"
    assert sponsor["paid_amount_cents"] == 0, (
        f"A refused confirmation records nothing, got {sponsor['paid_amount_cents']}"
    )


def test_third_resubmission_hits_the_revision_limit(api):
    """PRD §3.4: "The cycle `CHANGES_REQUESTED → SUBMITTED → IN_REVIEW →
    CHANGES_REQUESTED` may therefore repeat, but only within a budget of two
    completed resubmissions: a resubmission is permitted only while
    `revision_count` is strictly less than 2, and a third attempt is refused
    with `ERR_AD_REVISION_LIMIT`."

    Design: Corner/validations/third_ad_resubmission_hits_the_revision_limit
    """
    env = setup_ad_at_revision_budget()
    assert env["ad_after_second_revision"]["revision_count"] == 2

    response = api.resubmit_program_ad(
        env["ad"]["id"], "art-v4", make_sponsor_headers(env["sponsor"]["id"])
    )

    validate_error(response, ApiErrorId.ERR_AD_REVISION_LIMIT.value, 409)
    ad = read_program_ad(env["ad"]["id"])
    assert ad["revision_count"] == 2, "A refused resubmission consumes no budget"
    assert ad["status"] == "CHANGES_REQUESTED"
    assert ad["artwork_ref"] == "art-v3", "The refused artwork is not stored"
