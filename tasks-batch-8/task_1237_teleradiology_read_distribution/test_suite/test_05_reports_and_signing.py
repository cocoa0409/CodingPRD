"""Report drafting and signing: type/state gating, credit variants, TAT
boundary, and segregation of readers."""
import pytest

from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    accept_assignment,
    assert_instant_equals,
    assign_study,
    create_assignment_payload,
    create_draft_report,
    create_routed_study,
    create_study,
    get_success_data,
    make_hospital_user_headers,
    make_radiologist_headers,
    set_clock,
    setup_assignment_ready,
    setup_credentialed_radiologist,
    setup_final_signed_study,
    setup_prelim_signed_study,
    setup_study_in_progress,
    sign_report,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["admin_headers"]
DISPATCH = TEST_USERS["dispatch_headers"]
QA = TEST_USERS["qa_headers"]


class TestReportCreditVariants:
    def test_prelim_credit_is_point_eight_base_and_not_clawed_back(self, api):
        """PRD section 3.6: "On signature the report becomes `SIGNED` with
        `signed_at` stamped from the logical clock, and it earns provisional
        credit: 0.8 times the study's base RVU, rounded half-up to 2 decimal
        places, written to `credited_rvu`."
        PRD section 2.9: "...provisional credit already granted is never clawed
        back when a preliminary report is later superseded..."

        Design: Difficulty/dual_variant_calc/report_credit_provisional_vs_final_variant
        """
        ctx = setup_final_signed_study(accession_number="ACC-V1", priority="STAT",
                                       discrepancy_grade=0)
        pre = get_success_data(api.get_report(ctx["prelim_report"]["id"], QA))
        assert pre["status"] == "SUPERSEDED"
        # CT base 1.5 * 0.8 = 1.2; stands even after supersede.
        assert pre["credited_rvu"] == pytest.approx(1.2)
        rad_pre = get_success_data(api.get_radiologist(
            ctx["prelim_radiologist"]["id"], ADMIN))
        assert rad_pre["completed_rvu_24h"] == pytest.approx(1.2)

    def test_final_credit_is_base_times_one_minus_penalty(self, api):
        """PRD section 3.6: "The final's credit is the study's base RVU
        multiplied by one minus the discrepancy penalty for the grade: grades 0
        and 1 carry a penalty of 0, grade 2 carries 0.25, and grade 3 carries
        0.5; when no signed preliminary exists the grade is null and the penalty
        is 0. The result is rounded half-up to 2 decimal places."

        Design: Difficulty/dual_variant_calc/report_credit_provisional_vs_final_variant
        """
        ctx = setup_final_signed_study(accession_number="ACC-V2", priority="STAT",
                                       discrepancy_grade=0)
        fin = get_success_data(api.get_report(ctx["final_report"]["id"], QA))
        # CT base 1.5 * (1 - 0) = 1.5 — differs from the 1.2 provisional credit
        # on the identical study_rvu.
        assert fin["credited_rvu"] == pytest.approx(1.5)
        assert fin["credited_rvu"] != pytest.approx(1.2)
        rad_fin = get_success_data(api.get_radiologist(
            ctx["final_radiologist"]["id"], ADMIN))
        assert rad_fin["completed_rvu_24h"] == pytest.approx(1.5)


class TestReportTypeGating:
    def test_final_sign_before_prelim_rejected(self, api):
        """PRD section 3.6: "When the resolved policy requires a preliminary, a
        signed preliminary must already exist, else the sign rejects with
        `ERR_FINAL_NOT_DUE`."

        Design: Corner/validations/final_sign_before_prelim_rejected
        """
        ctx = setup_study_in_progress(accession_number="ACC-FD", priority="STAT",
                                      prelim_required=True)
        rad = ctx["radiologist"]
        # The assignment is PRELIMINARY-phase (prelim_required, no prelim yet).
        asg = get_success_data(api.get_assignment(ctx["assignment"]["id"], DISPATCH))
        assert asg["phase"] == "PRELIMINARY"
        rep = create_draft_report(ctx["assignment"]["id"], rad["id"], "FINAL",
                                  discrepancy_grade=0)
        resp = api.sign_report(rep["id"], make_radiologist_headers(rad["id"]))
        validate_error(resp, ApiErrorId.ERR_FINAL_NOT_DUE, 422)
        rep_after = get_success_data(api.get_report(rep["id"], QA))
        assert rep_after["status"] == "DRAFT"
        study = get_success_data(api.get_study(ctx["study"]["id"], DISPATCH))
        assert study["status"] == "IN_PROGRESS"

    def test_prelim_sign_when_not_required_rejected(self, api):
        """PRD section 3.6: "Signing a `PRELIMINARY` report is permitted only
        when the resolved policy's `prelim_required` is true and no signed
        preliminary already exists for the study; both violations reject with
        `ERR_PRELIM_NOT_PERMITTED`."

        Design: Corner/validations/prelim_sign_when_not_required_rejected
        """
        ctx = setup_study_in_progress(accession_number="ACC-PN", priority="ROUTINE",
                                      prelim_required=False)
        rad = ctx["radiologist"]
        rep = create_draft_report(ctx["assignment"]["id"], rad["id"], "PRELIMINARY")
        resp = api.sign_report(rep["id"], make_radiologist_headers(rad["id"]))
        validate_error(resp, ApiErrorId.ERR_PRELIM_NOT_PERMITTED, 422)
        assert get_success_data(api.get_report(rep["id"], QA))["status"] == "DRAFT"
        assert get_success_data(api.get_study(
            ctx["study"]["id"], DISPATCH))["status"] == "IN_PROGRESS"

    def test_same_reader_final_sign_rejected(self, api):
        """PRD section 3.6: "When a signed preliminary exists, the final signer
        must differ from the preliminary signer — a same-reader final rejects
        with `ERR_SAME_READER_CONFLICT` — and the payload must carry a
        `discrepancy_grade`, else `ERR_VALIDATION`..."

        Design: Corner/validations/same_reader_final_sign_rejected
        """
        ctx = setup_prelim_signed_study(accession_number="ACC-SR")
        rad = ctx["prelim_radiologist"]
        study = get_success_data(api.get_study(ctx["study"]["id"], DISPATCH))
        # Manually assign the FINAL phase back to the prelim signer.
        asg2 = assign_study(study["id"], rad["id"])
        accept_assignment(asg2)
        rep2 = create_draft_report(asg2["id"], rad["id"], "FINAL",
                                   discrepancy_grade=1)
        resp = api.sign_report(rep2["id"], make_radiologist_headers(rad["id"]))
        validate_error(resp, ApiErrorId.ERR_SAME_READER_CONFLICT, 422)
        assert get_success_data(api.get_report(rep2["id"], QA))["status"] == "DRAFT"
        assert get_success_data(api.get_study(
            study["id"], DISPATCH))["status"] == "IN_PROGRESS"

    def test_addendum_report_without_final_rejected(self, api):
        """PRD section 3.6: "Signing an `ADDENDUM` report requires the study's
        `first_final_signed_at` to be set — an addendum against a study with no
        signed final rejects with `ERR_ADDENDUM_NOT_PERMITTED`..."

        Design: Corner/validations/addendum_report_without_final_rejected
        """
        ctx = setup_study_in_progress(accession_number="ACC-AN", priority="ROUTINE")
        rad = ctx["radiologist"]
        rep = create_draft_report(ctx["assignment"]["id"], rad["id"], "ADDENDUM")
        resp = api.sign_report(rep["id"], make_radiologist_headers(rad["id"]))
        validate_error(resp, ApiErrorId.ERR_ADDENDUM_NOT_PERMITTED, 422)
        assert get_success_data(api.get_report(rep["id"], QA))["status"] == "DRAFT"
        assert get_success_data(api.get_study(
            ctx["study"]["id"], DISPATCH))["status"] == "IN_PROGRESS"


class TestSignIdempotency:
    def test_sign_already_signed_report_rejected(self, api):
        """PRD section 3.6: "Signing is the pivotal act and is restricted to the
        report's own author (`X-User-ID` equal to the report's `radiologist_id`)
        with the report still `DRAFT`."
        PRD section 2.8: "Sixth (priority 6), state-machine legality: the target
        resource's state must permit the requested transition, else
        `ERR_INVALID_STATE` (HTTP 409)..."

        Design: Corner/state_machines/sign_already_signed_report_rejected
        """
        ctx = setup_study_in_progress(accession_number="ACC-ID", priority="ROUTINE")
        rad = ctx["radiologist"]
        rep = create_draft_report(ctx["assignment"]["id"], rad["id"], "FINAL")
        signed = sign_report(rep["id"], rad["id"])
        assert signed["status"] == "SIGNED"

        resp = api.sign_report(rep["id"], make_radiologist_headers(rad["id"]))
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE, 409)
        # Credit landed exactly once: CT base 1.5, penalty 0 (no prelim).
        rad_after = get_success_data(api.get_radiologist(rad["id"], ADMIN))
        assert rad_after["completed_rvu_24h"] == pytest.approx(1.5)


class TestTatBreachBoundary:
    def _build_two_drafts(self, api):
        ctx = setup_assignment_ready(hospital_name="Hosp Tat", priority="STAT",
                                     prelim_required=False)
        hosp, rad = ctx["hospital"], ctx["radiologist"]
        drafts = []
        studies = []
        for acc in ("ACC-T1", "ACC-T2"):
            study = create_routed_study(hosp["id"], acc, priority="STAT")
            asg = assign_study(study["id"], rad["id"])
            accept_assignment(asg)
            rep = create_draft_report(asg["id"], rad["id"], "FINAL")
            drafts.append(rep)
            studies.append(study)
        return hosp, rad, studies, drafts

    def test_signing_exactly_at_due_at_is_on_time(self, api):
        """PRD section 3.6: "Breach evaluation follows one rule regardless of
        which signature is TAT-relevant: the relevant `signed_at` is compared to
        `due_at`, and `tat_breached` becomes true only when the signature is
        strictly later than the deadline — signing exactly at `due_at` is on
        time. When breached, `breach_minutes` is the number of whole minutes of
        lateness, computed by taking the signed-to-due difference in seconds and
        discarding any partial minute; when on time, `breach_minutes` is 0."

        Design: Difficulty/boundary_precision_check/tat_breach_strict_greater_than_due_at
        """
        _hosp, rad, studies, drafts = self._build_two_drafts(api)
        # Studies received at 2026-05-10T10:00:00Z, STAT default 60 min ->
        # due 2026-05-10T11:00:00Z (compared as an instant; PRD pins the value,
        # not the fractional-second rendering).
        assert_instant_equals(studies[0]["due_at"], "2026-05-10T11:00:00Z")
        set_clock("2026-05-10T11:00:00Z")
        sign_report(drafts[0]["id"], rad["id"])
        s1 = get_success_data(api.get_study(studies[0]["id"], DISPATCH))
        assert s1["tat_breached"] is False
        assert s1["breach_minutes"] == 0

    def test_signing_sixty_seconds_late_breaches_one_minute(self, api):
        """PRD section 3.6: "...`tat_breached` becomes true only when the
        signature is strictly later than the deadline — signing exactly at
        `due_at` is on time. When breached, `breach_minutes` is the number of
        whole minutes of lateness, computed by taking the signed-to-due
        difference in seconds and discarding any partial minute; when on time,
        `breach_minutes` is 0."

        Design: Difficulty/boundary_precision_check/tat_breach_strict_greater_than_due_at
        """
        _hosp, rad, studies, drafts = self._build_two_drafts(api)
        set_clock("2026-05-10T11:01:00Z")  # 60 seconds past the 11:00 deadline
        sign_report(drafts[1]["id"], rad["id"])
        s2 = get_success_data(api.get_study(studies[1]["id"], DISPATCH))
        assert s2["tat_breached"] is True
        assert s2["breach_minutes"] == 1


class TestCancelBlockedAfterPreliminary:
    def test_cancel_blocked_after_preliminary_signed(self, api):
        """PRD section 3.6: "Finalized studies — those in `PRELIMINARY_SIGNED`,
        `FINAL_SIGNED`, or `AMENDMENT_PENDING` — cannot be cancelled; an attempt
        against any impermissible state rejects with `ERR_INVALID_STATE`."

        Design: Corner/state_machines/cancel_blocked_after_preliminary_signed
        """
        ctx = setup_prelim_signed_study(accession_number="ACC-CB")
        resp = api.cancel_study(
            ctx["study"]["id"],
            make_hospital_user_headers(ctx["hospital"]["id"]))
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE, 409)
        assert get_success_data(api.get_study(
            ctx["study"]["id"], DISPATCH))["status"] == "PRELIMINARY_SIGNED"
