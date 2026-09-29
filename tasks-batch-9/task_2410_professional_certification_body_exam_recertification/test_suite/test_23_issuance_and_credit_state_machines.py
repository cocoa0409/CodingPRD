"""Release mints two rows the call never names, and one child approval moves the parent."""

import pytest

from test_helpers import assertions as ax
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers import validate_success
from test_helpers.test_users import ELIGIBILITY_REVIEWER_3_ID, make_eligibility_reviewer_headers

REVIEWER = make_eligibility_reviewer_headers(ELIGIBILITY_REVIEWER_3_ID)


class TestScoreReleaseMintsTheCredential:
    """Reporting a pass is the deepest cascade in the system."""

    def test_release_moves_the_score_dimension_and_mints_a_numbered_credential(self, api):
        """The registration reaches REPORTED with its seat still COMPLETED, and a
        certificant appears bearing the composed certificate number and the clock's date.

        PRD §3.8: "Score release is the last operational step and is again an
        `ExamOperations` act, optionally annotated with a `report_note`. It moves
        `score_status` `SCORED → REPORTED`."

        PRD §3.10: "When the released registration's `outcome` is `PASS` and the candidate
        does not already hold a credential awaiting re-examination, **hop one** mints a
        certificant for the candidate-and-program pair: its `candidate_id` and `program_id`
        are taken from the registration and its application rather than supplied by any
        client, its `status` is `ACTIVE`, its `publication_status` is `PUBLISHED`, its
        `issued_on` is stamped from the logical clock, and its `certificate_number` is
        minted as described below."

        Design: Corner/state_machines/report_score_mints_the_certificant_and_opens_the_first_recertification_cycle
        """
        state = fx.pipeline_through_responses(api)

        reported = validate_success(api.report_score(
            state.registration_id, f.report_score_payload(), fx.EXAM_OPERATIONS), 200)

        assert reported["score_status"] == "REPORTED"
        assert reported["seat_status"] == "COMPLETED"

        certificants = validate_success(api.list_certificants(
            fx.PROGRAM_ADMIN, {"candidate_id": state.candidate_id}), 200)
        assert len(certificants) == 1
        certificant = certificants[0]
        assert certificant["certificate_number"] == "CPX-2026-00001"
        assert certificant["status"] == "ACTIVE"
        assert certificant["publication_status"] == "PUBLISHED"
        assert str(certificant["issued_on"]).startswith("2026-08-10")
        ax.assert_certificant(certificant)

    def test_the_first_cycle_opens_with_snapshotted_settings_and_a_grace_window(self, api):
        """Hop three opens cycle one on the credit path with the programme's settings
        pinned, its window dated off the issue instant, and the programme's issuance
        counter advanced.

        PRD §3.10: "**Hop three:** because the certificant now exists, its first
        recertification cycle is opened with `cycle_number` 1, `path` `CEU`,
        `carryover_credits_in` 0, `required_credits` pinned from the program's
        `required_ceu_credits`, and `accrual_basis_snapshot` pinned from the program's
        `ceu_credit_accrual_basis`; the certificant's `current_cycle_id` is repointed at
        it."

        PRD §3.11: "Its `certificant_id` names the holder it belongs to, its `cycle_number`
        is 1 for the cycle minted with the credential and one greater for each successor,
        its `starts_on` is the instant the window opens, its `ends_on` is `starts_on`
        advanced by the program's `cycle_length_months`, and its `grace_ends_on` is
        `ends_on` advanced by the program's `recert_grace_days`."

        PRD §3.10: "**Hop two:** because a certificant was minted, the program's
        `certificants_issued_count` increases by 1 and the certificant's `valid_through` is
        set to `issued_on` advanced by the program's `cycle_length_months`."

        Design: Corner/state_machines/report_score_mints_the_certificant_and_opens_the_first_recertification_cycle
        """
        state = fx.pipeline_through_certificant(api)

        cycles = fx.read_cycles_of(api, state.certificant_id)
        assert len(cycles) == 1
        cycle = cycles[0]
        assert cycle["cycle_number"] == 1
        assert cycle["status"] == "OPEN"
        assert cycle["path"] == "CEU"
        assert float(cycle["required_credits"]) == pytest.approx(12.0, abs=0.01)
        assert float(cycle["credits_applied"]) == pytest.approx(0.00, abs=0.01)
        assert float(cycle["carryover_credits_in"]) == pytest.approx(0.00, abs=0.01)
        assert cycle["accrual_basis_snapshot"] == "STRICT_CYCLE"
        assert str(cycle["starts_on"]).startswith("2026-08-10")
        assert str(cycle["ends_on"]).startswith("2027-08-10")
        assert str(cycle["grace_ends_on"]).startswith("2027-11-08")

        certificant = fx.read_certificant(api, state.certificant_id)
        assert certificant["current_cycle_id"] == cycle["id"]
        assert str(certificant["valid_through"]).startswith("2027-08-10")
        assert fx.read_program(api, state.program_id)["certificants_issued_count"] == 1


class TestCreditApprovalBubblesTheCycle:
    """The child's review, not the parent's own endpoint, moves the cycle."""

    def test_one_approval_records_the_reviewer_and_counts_the_credit(self, api):
        """The reviewed activity keeps its awarded credit, starts counting it, and records
        the acting reviewer.

        PRD §3.11: "The reviewer submits an `outcome` of `APPROVE`, `REJECT`, or
        `SELECT_FOR_AUDIT`, optionally with a `review_note`, and the acting identity is
        recorded as `reviewer_user_id` in all three cases."

        PRD §3.11: "An `APPROVE` requires the activity to be `SUBMITTED`, moves it
        `SUBMITTED → APPROVED`, and sets `counted` to true."

        Design: Corner/state_machines/ceu_approval_bubbles_the_cycle_from_open_to_satisfied
        """
        state = fx.pipeline_through_certificant(api)
        activity = fx.claim_ceu(api, state, contact_hours=12.0)
        assert activity["counted"] is False

        approved = validate_success(api.review_ceu_activity(
            activity["id"],
            f.review_ceu_payload("APPROVE",
                                 review_note="attendance certificate on file"),
            REVIEWER), 200)

        assert approved["status"] == "APPROVED"
        assert approved["counted"] is True
        assert float(approved["credits_awarded"]) == pytest.approx(12.00, abs=0.01)
        assert float(approved["credits_counted"]) == pytest.approx(12.00, abs=0.01)
        assert approved["reviewer_user_id"] == ELIGIBILITY_REVIEWER_3_ID
        ax.assert_ceu_activity(approved)

    def test_the_cycle_and_the_credential_are_rewritten_in_the_same_request(self, api):
        """The cycle re-derives to exactly its requirement and bubbles to SATISFIED while
        staying on the credit path, and the credential's mirrored total follows.

        PRD §3.11: "A `CEU`-path cycle is `SATISFIED` exactly when its `credits_applied` is
        greater than or equal to its `required_credits`, with exact equality satisfying; a
        `RE_EXAM`-path cycle is `SATISFIED` exactly when its `reexam_registration_id` is
        set."

        PRD §3.10: "`ceu_credits_applied` mirrors the `credits_applied` of the
        certificant's cycle whose `status` is `OPEN` or `SATISFIED`, and is 0 when no such
        cycle exists."

        Design: Corner/state_machines/ceu_approval_bubbles_the_cycle_from_open_to_satisfied
        """
        state = fx.pipeline_through_certificant(api)
        activity = fx.claim_ceu(api, state, contact_hours=12.0)

        validate_success(api.review_ceu_activity(
            activity["id"], f.review_ceu_payload("APPROVE"), REVIEWER), 200)

        cycle = fx.read_cycle(api, state.cycle_id)
        assert float(cycle["credits_applied"]) == pytest.approx(12.00, abs=0.01)
        assert cycle["status"] == "SATISFIED"
        assert cycle["path"] == "CEU"
        certificant = fx.read_certificant(api, state.certificant_id)
        assert float(certificant["ceu_credits_applied"]) == pytest.approx(12.00, abs=0.01)
        assert certificant["status"] == "ACTIVE"
        ax.assert_credits_applied_matches_counted_children(
            cycle, fx.read_activities_of(api, state.cycle_id))
