"""Equating is anchored on the cut, and audit sampling counts completions rather than rows."""

from test_helpers import assertions as ax
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers import validate_success
from test_helpers.test_users import (
    ELIGIBILITY_REVIEWER_1_ID,
    ELIGIBILITY_REVIEWER_2_ID,
    make_eligibility_reviewer_headers,
)

EDUCATION_REVIEWER = make_eligibility_reviewer_headers(ELIGIBILITY_REVIEWER_1_ID)
EXPERIENCE_REVIEWER = make_eligibility_reviewer_headers(ELIGIBILITY_REVIEWER_2_ID)


def _two_checked_in_candidates_on_a_four_position_form(api):
    """A published four-item form whose adopted cut is 2, with two approved
    candidates seated in the same test-centre session.
    """
    program = fx.active_program(api, form_length=4)
    item_ids = [fx.operational_item(api, program["id"], stem=f"Equating item {n}")["id"]
                for n in range(1, 5)]
    form = fx.published_form(api, program["id"], item_ids, form_code="CPX-F4")

    candidate_a = fx.create_candidate(api, email="cand.a@example.com", full_name="Cand A")
    application_a = fx.approved_application(api, candidate_a["id"], program["id"])
    candidate_b = fx.create_candidate(api, email="cand.b@example.com", full_name="Cand B")
    application_b = fx.approved_application(api, candidate_b["id"], program["id"])

    session = fx.create_test_center_session(api)
    registration_a = fx.create_registration(api, application_a["id"], form["id"])
    registration_b = fx.create_registration(api, application_b["id"], form["id"])
    fx.schedule_seat(api, registration_a["id"], session["id"], session["version"])
    fx.schedule_seat(api, registration_b["id"], session["id"],
                     fx.read_session(api, session["id"])["version"])

    fx.set_clock(api, "2026-08-10T00:00:00Z")
    fx.check_in(api, registration_a["id"])
    fx.check_in(api, registration_b["id"])
    return {
        "program": program,
        "form": form,
        "application_a": application_a,
        "application_b": application_b,
        "registration_a": registration_a,
        "registration_b": registration_b,
    }


def _four_applications_on_a_sampled_programme(api):
    """Four applications on a programme that audits every second completion; the
    third applicant is short of the experience threshold.
    """
    program = fx.active_program(api, audit_every_nth=2)
    applications = []
    for label, months in (("a", 36), ("b", 36), ("c", 6), ("d", 36)):
        candidate = fx.create_candidate(api, email=f"cand.{label}@example.com",
                                        full_name=f"Cand {label.upper()}")
        applications.append(fx.submitted_application(
            api, candidate["id"], program["id"], experience_months=months))
    return program, applications


def _verify(api, application_id, dimension, headers):
    return validate_success(api.verify_application_dimension(
        application_id, f.verify_dimension_payload(dimension, "PASS"), headers), 200)


class TestPiecewiseEquating:
    """The cut is the hinge, and the pass decision is taken on the scaled score."""

    def test_one_mark_below_the_cut_maps_through_the_lower_segment_to_350(self, api):
        """On a four-position form whose cut is 2, a raw score of 1 travels the lower
        segment to 200 + 1 x 300 / 2 and fails — neither clamp bound produced it.

        PRD §3.8: "When `raw_score` is below the cut, the unrounded scaled value is 500 if
        the cut is 0; otherwise it is 200 plus `raw_score` multiplied by 300 and divided by
        the cut."

        PRD §3.8: "The registration's `outcome` becomes `PASS` when `scaled_score` is at
        least 500 and `FAIL` otherwise."

        Design: Corner/calculations/scaled_score_equating_maps_one_below_the_cut_to_350_and_the_cut_itself_to_exactly_500
        """
        seated = _two_checked_in_candidates_on_a_four_position_form(api)
        assert seated["form"]["scored_item_count"] == 4
        assert seated["form"]["raw_cut_score"] == 2

        scored = validate_success(api.submit_responses(
            seated["registration_a"]["id"], f.submit_responses_payload(1),
            fx.EXAM_OPERATIONS), 200)

        assert scored["scaled_score"] == 350
        assert scored["outcome"] == "FAIL"
        assert scored["scaled_score"] != 200
        ax.assert_exam_registration(scored)

    def test_a_raw_score_exactly_on_the_cut_maps_to_500_and_passes(self, api):
        """Sitting exactly on the cut lands on the anchor itself, which passes on the
        at-least comparison, and scoring alone mints nothing.

        PRD §3.8: "When `raw_score` is at least the cut, the unrounded scaled value is 800
        if the total equals the cut; otherwise it is 500 plus the quantity `raw_score` minus
        the cut, multiplied by 300, divided by the quantity total minus the cut."

        PRD §3.8: "The anchoring is exact by construction: a `raw_score` equal to the cut
        maps to precisely 500 and passes, one mark below the cut lands below 500 and fails,
        a `raw_score` of 0 maps to precisely 200, and a `raw_score` equal to the total maps
        to precisely 800."

        Design: Corner/calculations/scaled_score_equating_maps_one_below_the_cut_to_350_and_the_cut_itself_to_exactly_500
        """
        seated = _two_checked_in_candidates_on_a_four_position_form(api)
        fx.submit_responses(api, seated["registration_a"]["id"], 1)

        scored = validate_success(api.submit_responses(
            seated["registration_b"]["id"], f.submit_responses_payload(2),
            fx.EXAM_OPERATIONS), 200)

        assert scored["scaled_score"] == 500
        assert scored["outcome"] == "PASS"
        assert scored["scaled_score"] != 800

        for registration_id in (seated["registration_a"]["id"], seated["registration_b"]["id"]):
            settled = fx.read_registration(api, registration_id)
            assert settled["seat_status"] == "COMPLETED"
            assert settled["score_status"] == "SCORED"
        assert fx.read_application(api, seated["application_a"]["id"])["attempts_consumed"] == 1
        assert fx.read_application(api, seated["application_b"]["id"])["attempts_consumed"] == 1
        assert fx.read_program(api, seated["program"]["id"])["certificants_issued_count"] == 0


class TestAuditSamplingSequence:
    """The counter advances on the completing verification, and only on a full pair."""

    def test_the_completing_call_stamps_the_sequence_and_every_second_pair_is_sampled(
            self, api):
        """The first dimension moves the application under review without touching the
        counter; the second stamps sequence 1 and approves, and the next pair takes
        sequence 2 and is diverted into audit with no eligibility date.

        PRD §3.6: "The **join** happens on the call that leaves both `education_status` and
        `experience_status` at `VERIFIED`, and it has two divergent branches selected by a
        deterministic every-Nth rule."

        PRD §3.6: "If `audit_sequence_number` is an exact multiple of the program's
        `audit_every_nth` — that is, dividing the sequence number by the sampling interval
        leaves no remainder — the application moves `UNDER_REVIEW → AUDIT_SELECTED`; its
        `eligibility_expires_on` deliberately stays null, and any attempt to register
        against it is refused with `ERR_APPLICATION_NOT_APPROVED` until the audit is
        decided."

        Design: Corner/calculations/audit_sampling_counts_verification_completions_in_order_and_skips_denied_applications
        """
        _program, applications = _four_applications_on_a_sampled_programme(api)

        half_done = _verify(api, applications[0]["id"], "EDUCATION", EDUCATION_REVIEWER)
        assert half_done["status"] == "UNDER_REVIEW"
        assert half_done["education_status"] == "VERIFIED"
        assert half_done["audit_sequence_number"] is None

        first = _verify(api, applications[0]["id"], "EXPERIENCE", EXPERIENCE_REVIEWER)
        assert first["status"] == "APPROVED"
        assert first["audit_sequence_number"] == 1
        assert str(first["eligibility_expires_on"]).startswith("2027-08-01")
        ax.assert_eligibility_application(first)

        _verify(api, applications[1]["id"], "EDUCATION", EDUCATION_REVIEWER)
        second = _verify(api, applications[1]["id"], "EXPERIENCE", EXPERIENCE_REVIEWER)
        assert second["status"] == "AUDIT_SELECTED"
        assert second["audit_sequence_number"] == 2
        assert second["eligibility_expires_on"] is None

    def test_a_denial_consumes_no_sequence_number_so_the_next_pair_is_not_sampled(self, api):
        """The third applicant is denied on arithmetic despite a PASS verdict and takes no
        sequence number, so the fourth applicant receives 3 and is approved rather than
        audited.

        PRD §3.6: "A reviewer who submits `PASS` for an applicant who does not meet the
        thresholds still produces `FAILED`."

        PRD §3.6: "Crucially, a denial **does not** touch the program's
        `verified_application_counter`: only fully verified pairs enter the audit sequence,
        so a denied application never shifts the sampling of applications that come after
        it."

        PRD §3.6: "Sampling therefore depends on the order in which applications *complete
        verification*, not the order in which they were created."

        Design: Corner/calculations/audit_sampling_counts_verification_completions_in_order_and_skips_denied_applications
        """
        program, applications = _four_applications_on_a_sampled_programme(api)
        for application in applications[:2]:
            _verify(api, application["id"], "EDUCATION", EDUCATION_REVIEWER)
            _verify(api, application["id"], "EXPERIENCE", EXPERIENCE_REVIEWER)

        _verify(api, applications[2]["id"], "EDUCATION", EDUCATION_REVIEWER)
        denied = _verify(api, applications[2]["id"], "EXPERIENCE", EXPERIENCE_REVIEWER)

        assert denied["status"] == "DENIED"
        assert denied["experience_status"] == "FAILED"
        assert denied["denial_reason"] == "EXPERIENCE_FAILED"
        assert denied["audit_sequence_number"] is None
        assert fx.read_program(api, program["id"])["verified_application_counter"] == 2

        _verify(api, applications[3]["id"], "EDUCATION", EDUCATION_REVIEWER)
        fourth = _verify(api, applications[3]["id"], "EXPERIENCE", EXPERIENCE_REVIEWER)

        assert fourth["status"] == "APPROVED"
        assert fourth["status"] != "AUDIT_SELECTED"
        assert fourth["audit_sequence_number"] == 3
        assert str(fourth["eligibility_expires_on"]).startswith("2027-08-01")
        assert fx.read_program(api, program["id"])["verified_application_counter"] == 3
