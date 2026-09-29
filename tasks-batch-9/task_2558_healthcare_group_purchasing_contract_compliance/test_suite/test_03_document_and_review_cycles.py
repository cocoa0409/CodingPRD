"""Re-entrant lifecycles: the letter-of-participation loop and the dossier loop.

Both machines come back to a state they have already occupied.  The letter's
document loop is unbounded in count and closes only by reaching an in-force
state; the dossier's review loop is closed by a counter instead, and each pass
through it rewrites the very score that decides whether the loop can be exited.
"""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import assertions as a
from test_helpers import factories as f
from test_helpers.api_errors import (
    ERR_INVALID_LOP_STATE,
    ERR_INVALID_REVIEW_STATE,
    ERR_REVISION_LIMIT_REACHED,
)
from test_helpers.constants import TIER_0
from test_helpers.fixtures import (
    read_commitment,
    read_contract,
    read_evidence_review,
)
from test_helpers.test_users import (
    CLINICAL_REVIEWER_2,
    clinical_reviewer_2_headers,
    clinical_reviewer_headers,
    contract_manager_headers,
    make_member_materials_manager_headers,
)


class TestLetterOfParticipationCycle:
    """ISSUED → SIGNED → VOID → ISSUED, with election_status frozen throughout."""

    def test_voiding_a_signed_letter_clears_the_signer_and_leaves_the_election_alone(
        self, api, elected_commitment
    ):
        """PRD §3.4: "Voiding is available from `ISSUED` and from `SIGNED`, optionally
        recording a `reason`; it sets `lop_status` to `VOID`, resets `signer_name` to
        null, and leaves `election_status` completely untouched."

        Design: Difficulty/non_linear_state_machine/lop_void_reissue_cycle_leaves_election_status_untouched
        """
        commitment_id = elected_commitment["commitment"]["id"]
        member_id = elected_commitment["member"]["id"]
        member_headers = make_member_materials_manager_headers(member_id)

        validate_success(
            api.issue_lop(commitment_id, {}, headers=contract_manager_headers()), 200
        )
        signed = validate_success(
            api.sign_lop(commitment_id, f.signer_payload("R. Vasquez"), headers=member_headers),
            200,
        )
        assert signed["lop_status"] == "SIGNED"
        assert signed["signer_name"] == "R. Vasquez"

        voided = validate_success(
            api.void_lop(commitment_id, {}, headers=contract_manager_headers()), 200
        )

        assert voided["lop_status"] == "VOID"
        assert voided["signer_name"] is None
        assert voided["election_status"] == "ELECTED"

    def test_a_void_letter_can_be_issued_again_while_the_election_stands(
        self, api, elected_commitment
    ):
        """PRD §3.4: "From `VOID` the same `ContractManager` may issue the letter
        again, closing the document cycle `VOID → ISSUED` and again clearing
        `signer_name`, provided `election_status` is still `ELECTED` — otherwise
        `ERR_COMMITMENT_NOT_ELECTED`."

        Design: Difficulty/non_linear_state_machine/lop_void_reissue_cycle_leaves_election_status_untouched
        """
        commitment_id = elected_commitment["commitment"]["id"]
        member_headers = make_member_materials_manager_headers(
            elected_commitment["member"]["id"]
        )
        validate_success(
            api.issue_lop(commitment_id, {}, headers=contract_manager_headers()), 200
        )
        validate_success(
            api.sign_lop(commitment_id, f.signer_payload("R. Vasquez"), headers=member_headers),
            200,
        )
        validate_success(
            api.void_lop(commitment_id, {}, headers=contract_manager_headers()), 200
        )

        reissued = validate_success(
            api.issue_lop(commitment_id, {}, headers=contract_manager_headers()), 200
        )

        assert reissued["lop_status"] == "ISSUED"
        assert reissued["signer_name"] is None
        assert reissued["election_status"] == "ELECTED"

    def test_countersigning_the_reissued_letter_binds_the_election(
        self, api, elected_commitment
    ):
        """PRD §3.4: "It advances `lop_status` from `SIGNED` to `COUNTERSIGNED`. In
        the same request it drives `election_status` from `ELECTED` to `ACTIVE`. It
        sets `current_tier_code` to the commitment's `elected_tier_code`, which is the
        first moment the member has a tier actually in force rather than merely
        elected. And it recomputes the parent contract's `active_commitment_count` —
        which now genuinely rises, since `ACTIVE` is a counted state — incrementing
        that contract's `version` by one."

        Design: Difficulty/non_linear_state_machine/lop_void_reissue_cycle_leaves_election_status_untouched
        """
        commitment_id = elected_commitment["commitment"]["id"]
        contract_id = elected_commitment["contract"]["id"]
        member_headers = make_member_materials_manager_headers(
            elected_commitment["member"]["id"]
        )
        validate_success(
            api.issue_lop(commitment_id, {}, headers=contract_manager_headers()), 200
        )
        validate_success(
            api.sign_lop(commitment_id, f.signer_payload("R. Vasquez"), headers=member_headers),
            200,
        )
        validate_success(
            api.void_lop(commitment_id, {}, headers=contract_manager_headers()), 200
        )
        validate_success(
            api.issue_lop(commitment_id, {}, headers=contract_manager_headers()), 200
        )
        validate_success(
            api.sign_lop(commitment_id, f.signer_payload("A. Nolan"), headers=member_headers),
            200,
        )

        bound = validate_success(
            api.countersign_lop(commitment_id, {}, headers=contract_manager_headers()), 200
        )

        assert bound["lop_status"] == "COUNTERSIGNED"
        assert bound["election_status"] == "ACTIVE"
        assert bound["current_tier_code"] == TIER_0
        assert bound["signer_name"] == "A. Nolan"
        assert read_contract(api, contract_id)["active_commitment_count"] == 1

    def test_a_countersigned_letter_can_no_longer_be_voided(
        self, api, active_commitment
    ):
        """PRD §3.4: "Once `lop_status` reaches `COUNTERSIGNED`, however, voiding is
        refused with `ERR_INVALID_LOP_STATE`: an in-force letter is unwound by
        terminating the commitment, not by voiding the document."

        Design: Difficulty/non_linear_state_machine/lop_void_reissue_cycle_leaves_election_status_untouched
        """
        commitment_id = active_commitment["commitment"]["id"]

        validate_error(
            api.void_lop(commitment_id, {}, headers=contract_manager_headers()),
            ERR_INVALID_LOP_STATE,
        )

        after = read_commitment(api, commitment_id)
        assert after["lop_status"] == "COUNTERSIGNED"
        assert after["election_status"] == "ACTIVE"


def _request_revision(api, review_id, reason):
    return validate_success(
        api.request_review_revision(
            review_id, f.reason_payload(reason), headers=clinical_reviewer_2_headers()
        ),
        200,
    )


def _resubmit(api, review_id, efficacy, safety, resilience, summary):
    return validate_success(
        api.resubmit_review(
            review_id,
            f.resubmit_payload(efficacy, safety, resilience, summary=summary),
            headers=clinical_reviewer_headers(),
        ),
        200,
    )


def _walk_the_two_permitted_revision_rounds(api, review_id):
    """Both revision rounds, ending with a resubmitted dossier that recommends CONVERT."""
    _request_revision(api, review_id, "Expand the safety cohort.")
    _resubmit(api, review_id, 6.00, 7.00, 7.50, "Safety cohort doubled.")
    _request_revision(api, review_id, "Supply resilience still single-source.")
    return _resubmit(
        api,
        review_id,
        7.00,
        7.00,
        7.60,
        "Second source qualified; safety cohort final.",
    )


class TestEvidenceRevisionCycle:
    """UNDER_REVIEW ⇄ REVISION_REQUESTED, bounded by the revision counter."""

    def test_a_new_dossier_is_scored_and_recommended_on_submission(
        self, api, revision_cycle_setup
    ):
        """PRD §3.2: "The dossier is created in `UNDER_REVIEW` status with
        `revision_round` at zero, and its `submitted_by_user_id` is set to the
        submitting reviewer's `X-User-ID`."
        PRD §3.2: "scores of 6.50, 7.00 and 6.00 give 2.60 plus 2.45 plus 1.50, a
        weighted score of 6.55"
        PRD §3.2: "From the weighted score the server derives
        `conversion_recommendation`: it is `CONVERT` when the weighted score is at
        least 7.00 — the threshold is **inclusive**, so a weighted score of exactly
        7.00 recommends conversion — and `DO_NOT_CONVERT` otherwise."

        Design: Difficulty/non_linear_state_machine/evidence_review_revision_cycle_capped_at_two_rounds
        """
        review = revision_cycle_setup["review"]

        assert review["status"] == "UNDER_REVIEW"
        assert review["revision_round"] == 0
        a.assert_score(review["weighted_score"], 6.55)
        assert review["conversion_recommendation"] == "DO_NOT_CONVERT"

    def test_each_revision_request_consumes_a_round_and_each_resubmission_rescores(
        self, api, revision_cycle_setup
    ):
        """PRD §3.2: "From `UNDER_REVIEW`, a reviewer may send it back with a revision
        request, optionally recording a `reason`; the dossier moves `UNDER_REVIEW →
        REVISION_REQUESTED` and `revision_round` increments by one."
        PRD §3.2: "From `REVISION_REQUESTED`, a resubmission returns the dossier
        `REVISION_REQUESTED → UNDER_REVIEW`, overwrites the three score fields with
        the resubmitted values plus an optional replacement `summary`, recomputes
        `weighted_score` and then `conversion_recommendation` from it, and — this is
        the part that matters for segregation of duties — sets `submitted_by_user_id`
        to the resubmitting reviewer's `X-User-ID`, so the endorsement bar always
        applies to whoever submitted the dossier most recently."
        PRD §3.2: "Resubmission does **not** increment `revision_round`; that counter
        is consumed only by the revision request."

        Design: Difficulty/non_linear_state_machine/evidence_review_revision_cycle_capped_at_two_rounds
        """
        review_id = revision_cycle_setup["review"]["id"]

        first_request = _request_revision(api, review_id, "Expand the safety cohort.")
        assert first_request["status"] == "REVISION_REQUESTED"
        assert first_request["revision_round"] == 1

        first_resubmit = _resubmit(
            api, review_id, 6.00, 7.00, 7.50, "Safety cohort doubled."
        )
        assert first_resubmit["status"] == "UNDER_REVIEW"
        assert first_resubmit["revision_round"] == 1
        a.assert_score(first_resubmit["weighted_score"], 6.73)
        assert first_resubmit["conversion_recommendation"] == "DO_NOT_CONVERT"

        second_request = _request_revision(
            api, review_id, "Supply resilience still single-source."
        )
        assert second_request["status"] == "REVISION_REQUESTED"
        assert second_request["revision_round"] == 2

        second_resubmit = _resubmit(
            api,
            review_id,
            7.00,
            7.00,
            7.60,
            "Second source qualified; safety cohort final.",
        )
        assert second_resubmit["status"] == "UNDER_REVIEW"
        assert second_resubmit["revision_round"] == 2
        a.assert_score(second_resubmit["weighted_score"], 7.15)
        assert second_resubmit["conversion_recommendation"] == "CONVERT"

    def test_a_third_revision_request_is_refused_by_the_revision_budget(
        self, api, revision_cycle_setup
    ):
        """PRD §3.2: "A revision request is permitted only while `revision_round` is 0
        or 1 — that is, at most 1 — so a dossier that has already been through two
        revision cycles and stands at `revision_round` 2 refuses a third with
        `ERR_REVISION_LIMIT_REACHED`."

        Design: Difficulty/non_linear_state_machine/evidence_review_revision_cycle_capped_at_two_rounds
        """
        review_id = revision_cycle_setup["review"]["id"]
        _walk_the_two_permitted_revision_rounds(api, review_id)

        validate_error(
            api.request_review_revision(
                review_id,
                f.reason_payload("Third bite at the apple."),
                headers=clinical_reviewer_2_headers(),
            ),
            ERR_REVISION_LIMIT_REACHED,
        )

        after = read_evidence_review(api, review_id)
        assert after["revision_round"] == 2
        assert after["status"] == "UNDER_REVIEW"

    def test_endorsing_the_rescored_dossier_closes_the_cycle_terminally(
        self, api, revision_cycle_setup
    ):
        """PRD §3.2: "An accepted endorsement sets `status` to `ENDORSED`, records
        `endorsed_by_user_id` as the endorsing reviewer's `X-User-ID`, and then
        reaches across to the parent contract: `evidence_endorsed` is recomputed and
        the contract's `version` increments by one."
        PRD §3.2: "Both `ENDORSED` and `REJECTED` are terminal: neither can be
        revised, revisited, or cycled back into review."
        PRD §3.2: "Attempting any of these transitions from a status where it does not
        exist returns `ERR_INVALID_REVIEW_STATE`."

        Design: Difficulty/non_linear_state_machine/evidence_review_revision_cycle_capped_at_two_rounds
        """
        review_id = revision_cycle_setup["review"]["id"]
        contract_id = revision_cycle_setup["contract"]["id"]
        _walk_the_two_permitted_revision_rounds(api, review_id)

        endorsed = validate_success(
            api.endorse_review(review_id, {}, headers=clinical_reviewer_2_headers()), 200
        )

        assert endorsed["status"] == "ENDORSED"
        assert endorsed["endorsed_by_user_id"] == CLINICAL_REVIEWER_2
        assert read_contract(api, contract_id)["evidence_endorsed"] is True

        validate_error(
            api.resubmit_review(
                review_id,
                f.resubmit_payload(9.00, 9.00, 9.00),
                headers=clinical_reviewer_headers(),
            ),
            ERR_INVALID_REVIEW_STATE,
        )
        assert read_evidence_review(api, review_id)["status"] == "ENDORSED"
