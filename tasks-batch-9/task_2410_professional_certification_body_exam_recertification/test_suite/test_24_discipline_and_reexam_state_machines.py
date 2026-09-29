"""Two guards protect a revocation, and electing re-examination reverses the credit path."""

import pytest

from test_helpers import ApiErrorId
from test_helpers import assertions as ax
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers import validate_error, validate_paginated, validate_success
from test_helpers.test_users import (
    ETHICS_OFFICER_1_ID,
    ETHICS_OFFICER_2_ID,
    make_ethics_officer_headers,
)

OFFICER_1 = make_ethics_officer_headers(ETHICS_OFFICER_1_ID)
OFFICER_2 = make_ethics_officer_headers(ETHICS_OFFICER_2_ID)

REVOKE = {"outcome": "REVOKED", "decision_note": "Immediate revocation sought"}


def _elected_reexam_cycle(api):
    """A holder with four approved credits who has switched to the exam route."""
    state = fx.pipeline_through_certificant(api)
    fx.approved_ceu(api, state, contact_hours=4.0, activity_date="2026-09-15T00:00:00Z")
    validate_success(api.elect_reexam(
        state.cycle_id,
        f.elect_reexam_payload(election_note="Electing the re-examination route"),
        state.owner_headers), 200)
    return state


class TestRevocationDueProcess:
    """A revocation needs a completed round and an officer who did not bring the case."""

    def test_a_revocation_at_round_zero_is_refused_on_due_process_alone(self, api):
        """A freshly opened case records the opener and stands at round zero, and an
        untainted second officer is still turned away — on due process, not on duties.

        PRD §3.12: "A new case has `status` `OPENED`, `response_round` 0, and
        `response_text`, `outcome`, `sanction_months`, and `decided_on` all null, with
        `opened_by_user_id` set to the acting `X-User-ID`."

        PRD §3.12: "A `SANCTIONED` or `REVOKED` decision requires at least one completed
        response round, so a case whose `response_round` is still 0 is refused with
        `ERR_DUE_PROCESS_INCOMPLETE`."

        Design: Corner/state_machines/revocation_needs_one_completed_response_round_and_a_revoked_certificant_admits_no_new_case
        """
        state = fx.pipeline_through_certificant(api)

        case = validate_success(api.open_disciplinary_case(
            f.open_case_payload(state.certificant_id,
                                description="Credential displayed by a lapsed holder"),
            OFFICER_1), 201)
        assert case["status"] == "OPENED"
        assert case["response_round"] == 0
        assert case["outcome"] is None
        assert case["opened_by_user_id"] == ETHICS_OFFICER_1_ID
        ax.assert_disciplinary_case(case)

        refused = api.decide_case(case["id"], dict(REVOKE), OFFICER_2)

        error = validate_error(refused, ApiErrorId.ERR_DUE_PROCESS_INCOMPLETE.value, 422)
        assert error["error_id"] != ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value
        assert error["error_id"] != ApiErrorId.ERR_INVALID_STATE.value
        unchanged = fx.read_case(api, case["id"])
        assert unchanged["status"] == "OPENED"
        assert unchanged["outcome"] is None
        assert unchanged["decided_on"] is None

    def test_after_the_response_the_opener_is_refused_and_the_other_officer_decides(self, api):
        """The respondent's own answer completes round one, and the identical body that
        due process rejected now fails on duties for the opener and succeeds for the peer.

        PRD §3.12: "The respondent — acting in the `Certificant` role and only on their own
        case — then answers with `response_text`, which moves the case `RESPONSE_REQUESTED
        → UNDER_REVIEW`, increases `response_round` by 1, and overwrites `response_text`
        with the latest submission."

        PRD §3.12: "A `REVOKED` decision additionally requires that the deciding officer
        not be the case's `opened_by_user_id`: the officer who brought the case may never
        be the one who ends the credential, and an attempt is refused with
        `ERR_SEGREGATION_OF_DUTIES`."

        PRD §3.12: "Every decision writes the `outcome` and stamps `decided_on` from the
        logical clock, and moves the case to `CLOSED`, which is terminal."

        Design: Corner/state_machines/revocation_needs_one_completed_response_round_and_a_revoked_certificant_admits_no_new_case
        """
        state = fx.pipeline_through_certificant(api)
        case = validate_success(api.open_disciplinary_case(
            f.open_case_payload(state.certificant_id,
                                description="Credential displayed by a lapsed holder"),
            OFFICER_1), 201)
        validate_success(api.request_case_response(
            case["id"], f.request_response_payload(
                request_note="Respond within the notice period"), OFFICER_1), 200)

        answered = validate_success(api.respond_to_case(
            case["id"],
            f.respond_to_case_payload(
                "The certificate was displayed in error and has been withdrawn"),
            state.owner_headers), 200)

        assert answered["status"] == "UNDER_REVIEW"
        assert answered["response_round"] == 1
        assert answered["response_text"] == (
            "The certificate was displayed in error and has been withdrawn")

        validate_error(api.decide_case(answered["id"], dict(REVOKE), OFFICER_1),
                       ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value, 409)

        decided = validate_success(api.decide_case(
            answered["id"],
            f.decide_case_payload("REVOKED", decision_note="Revocation upheld after response"),
            OFFICER_2), 200)
        assert decided["status"] == "CLOSED"
        assert decided["outcome"] == "REVOKED"
        assert decided["sanction_months"] is None
        assert str(decided["decided_on"]).startswith("2026-08-10T00:00:00")


class TestRevocationFinality:
    """Once the credential is gone, the cascade has run and no second case is admitted."""

    def test_revocation_removes_the_holder_voids_the_cycle_and_bars_a_new_case(self, api):
        """The three-hop cascade lands on the certificant, its cycle and its credit total,
        and the revoked holder refuses a brand-new allegation.

        PRD §3.12: "**Hop one:** the certificant's `status` becomes `REVOKED`, its
        `publication_status` recomputes to `REMOVED` so the credential disappears from
        public verification, and its `current_cycle_id` is cleared."

        PRD §3.12: "**Hop two:** because the certificant was revoked, every recertification
        cycle of that certificant whose `status` is `OPEN`, `SATISFIED`, or `LAPSED` moves
        to `VOID`, which is terminal."

        PRD §3.12: "A case may not be opened against an already-revoked credential; the
        attempt is refused with `ERR_CERTIFICANT_ALREADY_REVOKED`."

        Design: Corner/state_machines/revocation_needs_one_completed_response_round_and_a_revoked_certificant_admits_no_new_case
        """
        state = fx.pipeline_through_certificant(api)
        answered = fx.case_awaiting_decision(api, state)
        validate_success(api.decide_case(answered["id"], dict(REVOKE), OFFICER_2), 200)

        certificant = fx.read_certificant(api, state.certificant_id)
        assert certificant["status"] == "REVOKED"
        assert certificant["publication_status"] == "REMOVED"
        assert float(certificant["ceu_credits_applied"]) == pytest.approx(0.00, abs=0.01)
        assert fx.read_cycle(api, state.cycle_id)["status"] == "VOID"

        refused = api.open_disciplinary_case(
            f.open_case_payload(state.certificant_id, allegation_type="ETHICS_VIOLATION",
                               description="Second allegation after revocation"),
            OFFICER_1)

        validate_error(refused, ApiErrorId.ERR_CERTIFICANT_ALREADY_REVOKED.value, 409)
        _rows, meta = validate_paginated(
            api.list_certificant_disciplinary_cases(state.certificant_id, OFFICER_1))
        assert meta["total_count"] == 1


class TestElectingReexamination:
    """The election zeroes the credit path without satisfying the cycle."""

    def test_the_election_decounts_approved_credit_and_leaves_the_cycle_open(self, api):
        """Switching paths drops the requirement to zero and reverses the four credits
        already applied, yet the cycle stays OPEN because zero-against-zero cannot satisfy
        a re-examination cycle.

        PRD §3.11: "The election sets `path` to `RE_EXAM`, sets `required_credits` to 0,
        forces `counted` to false and `credits_counted` to 0 on every activity under the
        cycle whose `status` is `SUBMITTED`, `APPROVED`, `AUDIT_SELECTED`, or `VERIFIED`,
        and recomputes `credits_applied` to 0.00."

        PRD §3.11: "The cycle leaves the election still `OPEN`, and from that point it can
        be satisfied only by passing an examination."

        PRD §3.11: "a `RE_EXAM`-path cycle is `SATISFIED` exactly when its
        `reexam_registration_id` is set."

        Design: Corner/state_machines/electing_reexamination_zeroes_the_credit_path_and_only_a_passing_sitting_satisfies_the_cycle
        """
        state = fx.pipeline_through_certificant(api)
        activity = fx.approved_ceu(api, state, contact_hours=4.0,
                                   activity_date="2026-09-15T00:00:00Z")
        assert float(fx.read_cycle(api, state.cycle_id)["credits_applied"]) == pytest.approx(
            4.00, abs=0.01)

        elected = validate_success(api.elect_reexam(
            state.cycle_id,
            f.elect_reexam_payload(election_note="Electing the re-examination route"),
            state.owner_headers), 200)

        assert elected["path"] == "RE_EXAM"
        assert float(elected["required_credits"]) == pytest.approx(0.0, abs=0.01)
        assert float(elected["credits_applied"]) == pytest.approx(0.00, abs=0.01)
        assert elected["status"] == "OPEN"
        assert elected["reexam_registration_id"] is None

        decounted = fx.read_activity(api, activity["id"])
        assert decounted["status"] == "APPROVED"
        assert decounted["counted"] is False
        assert float(decounted["credits_counted"]) == pytest.approx(0.00, abs=0.01)
        assert float(fx.read_certificant(api, state.certificant_id)["ceu_credits_applied"]) == (
            pytest.approx(0.00, abs=0.01))

    def test_a_second_election_is_refused_on_state_and_changes_nothing(self, api):
        """The switch is one-way: with `path` already RE_EXAM the combination is no longer
        available, and the refusal leaves every field of the cycle alone.

        PRD §3.11: "Electing re-examination, optionally annotated with an `election_note`,
        is available to the holder while the cycle's `status` is `OPEN` or `LAPSED` and its
        `path` is still `CEU`; any other combination is `ERR_INVALID_STATE`."

        Design: Corner/state_machines/electing_reexamination_zeroes_the_credit_path_and_only_a_passing_sitting_satisfies_the_cycle
        """
        state = _elected_reexam_cycle(api)

        refused = api.elect_reexam(state.cycle_id,
                                  f.elect_reexam_payload(election_note="Electing again"),
                                  state.owner_headers)

        validate_error(refused, ApiErrorId.ERR_INVALID_STATE.value, 409)
        cycle = fx.read_cycle(api, state.cycle_id)
        assert cycle["path"] == "RE_EXAM"
        assert float(cycle["required_credits"]) == pytest.approx(0.0, abs=0.01)
        assert float(cycle["credits_applied"]) == pytest.approx(0.00, abs=0.01)
        assert cycle["status"] == "OPEN"

    def test_the_retake_registration_is_admitted_once_the_wait_has_run(self, api):
        """A holder on the exam route re-registers against the same application: the
        45-day wait off the first sitting's end has elapsed and one consumed attempt is
        below the ceiling of three, so this is attempt two.

        PRD §3.7: "Otherwise the new registration's `attempt_number` is that count plus 1."

        PRD §3.7: "When there is one, the registration is refused with
        `ERR_RETAKE_WAIT_ACTIVE` if the logical clock is strictly earlier than that instant
        advanced by the program's `retake_wait_days` — so a candidate whose last sitting
        ended exactly `retake_wait_days` ago is allowed through, while one an hour short is
        not."

        Design: Corner/state_machines/electing_reexamination_zeroes_the_credit_path_and_only_a_passing_sitting_satisfies_the_cycle
        """
        state = _elected_reexam_cycle(api)
        fx.set_clock(api, "2026-09-25T00:00:00Z")

        retake = validate_success(api.create_exam_registration(
            f.create_registration_payload(state.application_id, state.form_id),
            fx.EXAM_OPERATIONS), 201)

        assert retake["attempt_number"] == 2
        assert retake["seat_status"] == "UNSCHEDULED"
        assert retake["score_status"] == "NOT_APPLICABLE"
        ax.assert_exam_registration(retake)

    def test_the_passing_resitting_satisfies_the_cycle_instead_of_minting_a_credential(
            self, api):
        """Releasing the passing retake records the sitting on the existing cycle and
        satisfies it with zero credits, and no second credential appears.

        PRD §3.11: "Satisfaction arrives as a system consequence of score release: when a
        registration whose candidate matches the certificant's `candidate_id` is reported
        with `outcome` `PASS`, and that candidate already holds a credential whose cycle is
        on the `RE_EXAM` path, the existing cycle records the reported registration in
        `reexam_registration_id` and moves `OPEN → SATISFIED` or `LAPSED → SATISFIED` —
        **instead of** a second certificant being minted."

        PRD §3.8: "On success `seat_status` moves `CHECKED_IN → COMPLETED`, `score_status`
        moves `PENDING → SCORED`, the equated score and outcome are computed, and the
        owning application's `attempts_consumed` increases by 1."

        Design: Corner/state_machines/electing_reexamination_zeroes_the_credit_path_and_only_a_passing_sitting_satisfies_the_cycle
        """
        state = _elected_reexam_cycle(api)
        fx.set_clock(api, "2026-09-25T00:00:00Z")
        retake = fx.create_registration(api, state.application_id, state.form_id)
        session = fx.create_test_center_session(api, starts_at="2026-09-26T00:00:00Z",
                                                ends_at="2026-09-26T04:00:00Z")
        fx.schedule_seat(api, retake["id"], session["id"], session["version"])
        fx.set_clock(api, "2026-09-26T00:00:00Z")
        fx.check_in(api, retake["id"])

        scored = fx.submit_responses(api, retake["id"], 1)
        assert scored["scaled_score"] == 800
        assert scored["outcome"] == "PASS"
        assert fx.read_application(api, state.application_id)["attempts_consumed"] == 2

        released = validate_success(api.report_score(
            retake["id"], f.report_score_payload(report_note="release re-examination result"),
            fx.EXAM_OPERATIONS), 200)
        assert released["score_status"] == "REPORTED"

        cycle = fx.read_cycle(api, state.cycle_id)
        assert cycle["status"] == "SATISFIED"
        assert cycle["reexam_registration_id"] == retake["id"]
        assert float(cycle["credits_applied"]) == pytest.approx(0.00, abs=0.01)
        assert float(cycle["required_credits"]) == pytest.approx(0.0, abs=0.01)

        assert fx.read_program(api, state.program_id)["certificants_issued_count"] == 1
        _rows, meta = validate_paginated(api.list_certificants(
            fx.PROGRAM_ADMIN, {"candidate_id": state.candidate_id}))
        assert meta["total_count"] == 1
        certificant = fx.read_certificant(api, state.certificant_id)
        assert certificant["status"] == "ACTIVE"
        assert str(certificant["valid_through"]).startswith("2027-08-10")
