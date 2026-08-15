"""Scouting-alert claiming, segregation of duties, the review/release loop,
and outcome validation (PRD section 3.7)."""
from test_helpers import (
    ApiErrorId,
    api_client,
    assert_alert,
    create_pilot,
    make_agronomist_headers,
    setup_field_with_open_alert,
    validate_error,
    validate_success,
)


class TestSegregationOfDuties:

    def test_self_review_forbidden_for_mission_pilot(self):
        """PRD section 3.7: "segregation of duties bars the pilot who flew the
        originating mission from reviewing its own output: when the claimant's
        identity equals that mission's `pilot_id`, the claim is rejected with
        `ERR_SELF_REVIEW_FORBIDDEN` (HTTP 422)."

        Design: Corner/validations/self_review_forbidden_for_mission_pilot
        """
        ctx, mission, _, alert = setup_field_with_open_alert(
            cells_below_threshold=2000, acres=100, ndvi_mean=0.500)
        assert mission["pilot_id"] == ctx["pilot"]["id"]
        resp = api_client.claim_alert(
            alert["id"], make_agronomist_headers(ctx["pilot"]["id"]))
        validate_error(resp, ApiErrorId.ERR_SELF_REVIEW_FORBIDDEN)

    def test_alert_review_by_non_claiming_agronomist_forbidden(self):
        """PRD section 3.7: "From `UNDER_REVIEW`, only the claiming agronomist
        may act; a review or release attempted by anyone whose identity
        differs from `reviewing_agronomist_id` is refused with
        `ERR_NOT_CLAIMING_AGRONOMIST` (HTTP 403)".

        Design: Corner/state_machines/alert_review_by_non_claiming_agronomist_forbidden
        """
        ctx, _, _, alert = setup_field_with_open_alert(
            cells_below_threshold=1000, acres=100, ndvi_mean=0.500)
        agr1 = create_pilot()
        agr2 = create_pilot()
        claimed = validate_success(
            api_client.claim_alert(alert["id"],
                                   make_agronomist_headers(agr1["id"])))
        assert claimed["status"] == "UNDER_REVIEW"
        resp = api_client.review_alert(
            alert["id"], {"review_outcome": "CONFIRMED",
                          "review_notes": "fraud attempt"},
            make_agronomist_headers(agr2["id"]))
        validate_error(resp, ApiErrorId.ERR_NOT_CLAIMING_AGRONOMIST)


class TestReviewOutcomeValidation:

    def test_error_review_outcome_invalid(self):
        """PRD section 3.7: "The review itself submits a `review_outcome` —
        which must be exactly one of `CONFIRMED`, `DISMISSED`, or
        `NEEDS_REFLIGHT`, anything else drawing `ERR_REVIEW_OUTCOME_INVALID`".

        Design: Corner/errors/error_review_outcome_invalid
        """
        ctx, _, _, alert = setup_field_with_open_alert(
            cells_below_threshold=200, acres=100, ndvi_mean=0.500)
        agr = create_pilot()
        validate_success(
            api_client.claim_alert(alert["id"],
                                   make_agronomist_headers(agr["id"])))
        resp = api_client.review_alert(
            alert["id"], {"review_outcome": "MAYBE", "review_notes": "invalid"},
            make_agronomist_headers(agr["id"]))
        validate_error(resp, ApiErrorId.ERR_REVIEW_OUTCOME_INVALID)


class TestReviewReleaseLoop:

    def test_release_returns_alert_to_open_and_clears_reviewer(self):
        """PRD section 3.7: "Release is the gentler exit: the claiming
        agronomist hands the alert back to the queue, returning it to `OPEN`
        and clearing `reviewing_agronomist_id` to null."

        Design: Difficulty/non_linear_state_machine/scouting_alert_review_loop
        """
        ctx, _, _, alert = setup_field_with_open_alert(
            cells_below_threshold=5000, acres=100, ndvi_mean=0.400)
        agr1 = create_pilot()
        validate_success(
            api_client.claim_alert(alert["id"],
                                   make_agronomist_headers(agr1["id"])))
        resp = api_client.release_alert(
            alert["id"], make_agronomist_headers(agr1["id"]))
        released = validate_success(resp, expected_status=200)
        assert_alert(released)
        assert released["status"] == "OPEN", \
            f"release must return the alert to OPEN, got {released['status']}"
        assert released["reviewing_agronomist_id"] is None, \
            "release must clear reviewing_agronomist_id to null"

    def test_second_agronomist_can_claim_after_release(self):
        """PRD section 3.7: "A successful claim moves the alert to
        `UNDER_REVIEW` and stamps `reviewing_agronomist_id` with the
        claimant's identity."
        PRD section 3.7: "Release is the gentler exit: the claiming agronomist
        hands the alert back to the queue, returning it to `OPEN` and clearing
        `reviewing_agronomist_id` to null."

        Design: Difficulty/non_linear_state_machine/scouting_alert_review_loop
        """
        ctx, _, _, alert = setup_field_with_open_alert(
            cells_below_threshold=5000, acres=100, ndvi_mean=0.400)
        agr1 = create_pilot()
        agr2 = create_pilot()
        validate_success(
            api_client.claim_alert(alert["id"],
                                   make_agronomist_headers(agr1["id"])))
        validate_success(
            api_client.release_alert(alert["id"],
                                     make_agronomist_headers(agr1["id"])))
        # The loop OPEN -> UNDER_REVIEW -> OPEN admits a fresh claim.
        resp = api_client.claim_alert(
            alert["id"], make_agronomist_headers(agr2["id"]))
        reclaimed = validate_success(resp, expected_status=200)
        assert reclaimed["status"] == "UNDER_REVIEW", \
            f"second claim after release must succeed, got {reclaimed['status']}"
        assert reclaimed["reviewing_agronomist_id"] == agr2["id"], \
            "the second claimant's identity must be stamped on the alert"
