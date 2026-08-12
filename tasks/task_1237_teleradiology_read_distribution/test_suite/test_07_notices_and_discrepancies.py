"""Critical-result communication workflow and discrepancy reconciliation."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    accept_assignment,
    assign_study,
    create_draft_report,
    create_routed_study,
    get_success_data,
    make_hospital_user_headers,
    make_qa_headers,
    make_radiologist_headers,
    set_clock,
    setup_assignment_ready,
    setup_credentialed_radiologist,
    setup_final_signed_study,
    setup_prelim_signed_study,
    sign_report,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["admin_headers"]
DISPATCH = TEST_USERS["dispatch_headers"]
QA = TEST_USERS["qa_headers"]


def _setup_pending_notice(api, name="Hosp Esc"):
    """Sign a critical PRELIMINARY at the work clock; returns (hosp, rad, study,
    report, notice)."""
    ctx = setup_assignment_ready(hospital_name=name, priority="STAT",
                                 prelim_required=True)
    hosp, rad = ctx["hospital"], ctx["radiologist"]
    study = create_routed_study(hosp["id"], "ACC-ESC", priority="STAT")
    asg = assign_study(study["id"], rad["id"])
    accept_assignment(asg)
    rep = create_draft_report(asg["id"], rad["id"], "PRELIMINARY",
                              critical_finding=True)
    sign_report(rep["id"], rad["id"])
    notices, meta = validate_paginated(
        api.list_critical_notices(DISPATCH, params={"report_id": rep["id"]}))
    assert meta["total_count"] == 1
    return hosp, rad, study, rep, notices[0]


class TestNoticeAutoEscalation:
    def test_pending_notice_still_pending_at_plus_29_minutes(self, api):
        """PRD section 3.7: "The clock sweep performs the automatic form: a
        notice still `PENDING` once the logical clock has passed thirty minutes
        beyond its `created_at` escalates, and a `NOTIFIED` notice whose
        read-back is still outstanding (`readback_at` null) once the clock has
        passed sixty minutes beyond `notified_at` escalates; each sweep
        escalation likewise raises `escalation_count` by 1 and increments
        `version`."

        Design: Corner/state_machines/notice_auto_escalates_pending_after_30_minutes
        """
        _hosp, _rad, _study, _rep, notice = _setup_pending_notice(api)
        # Notice created at 2026-05-10T10:00:00Z; +29 min has not passed 30.
        set_clock("2026-05-10T10:29:00Z")
        data = get_success_data(api.get_critical_notice(notice["id"], DISPATCH))
        assert data["status"] == "PENDING"

    def test_pending_notice_escalates_at_plus_31_minutes(self, api):
        """PRD section 3.7: "...a notice still `PENDING` once the logical clock
        has passed thirty minutes beyond its `created_at` escalates...each sweep
        escalation likewise raises `escalation_count` by 1 and increments
        `version`."

        Design: Corner/state_machines/notice_auto_escalates_pending_after_30_minutes
        """
        _hosp, _rad, _study, _rep, notice = _setup_pending_notice(api, "Hosp Esc2")
        set_clock("2026-05-10T10:31:00Z")
        data = get_success_data(api.get_critical_notice(notice["id"], DISPATCH))
        assert data["status"] == "ESCALATED"
        assert data["escalation_count"] == 1


class TestAddendumBlockedByOpenDiscrepancy:
    def test_addendum_request_rejected_while_discrepancy_open(self, api):
        """PRD section 3.6: "...the request-addendum action moves `FINAL_SIGNED
        → AMENDMENT_PENDING` and increments the study's `version`, but it is
        blocked while any discrepancy case for the study sits in `OPEN`,
        `PEER_REVIEW`, or `ESCALATED_QI`, rejecting with
        `ERR_OPEN_DISCREPANCY_EXISTS`."

        Design: Corner/validations/addendum_request_rejected_while_discrepancy_open
        """
        ctx = setup_final_signed_study(accession_number="ACC-AB",
                                       discrepancy_grade=2)
        # Grade 2 auto-opened an OPEN discrepancy case on the study.
        resp = api.request_addendum(
            ctx["study"]["id"],
            make_hospital_user_headers(ctx["hospital"]["id"]))
        validate_error(resp, ApiErrorId.ERR_OPEN_DISCREPANCY_EXISTS, 409)
        assert get_success_data(api.get_study(
            ctx["study"]["id"], DISPATCH))["status"] == "FINAL_SIGNED"


class TestSegregationOfDuties:
    def _setup_peer_review_case(self, api, name="Hosp SD"):
        ctx = setup_final_signed_study(accession_number="ACC-SD",
                                       discrepancy_grade=2)
        cases, meta = validate_paginated(api.list_discrepancy_cases(
            QA, params={"study_id": ctx["study"]["id"]}))
        assert meta["total_count"] == 1
        case = cases[0]
        validate_success(api.open_peer_review(case["id"], QA), 200)
        return ctx, case

    def test_signer_cannot_reconcile_own_discrepancy_case(self, api):
        """PRD section 3.8: "Reconciliation enforces segregation of duties: the
        reconciler's `X-User-ID` must differ from both the preliminary report's
        `radiologist_id` and the final report's `radiologist_id`, else the
        request is rejected with `ERR_SELF_RECONCILIATION_FORBIDDEN`
        (HTTP 403)."

        Design: Corner/rbac/signer_cannot_reconcile_own_discrepancy_case
        """
        ctx, case = self._setup_peer_review_case(api)
        # The final signer attempts to reconcile their own case.
        resp = api.reconcile_case(case["id"], {"reconciliation_note": "self"},
                                  make_qa_headers(ctx["final_radiologist"]["id"]))
        validate_error(resp, ApiErrorId.ERR_SELF_RECONCILIATION_FORBIDDEN, 403)

    def test_neutral_reviewer_reconciles_successfully(self, api):
        """PRD section 3.8: "A successful reconcile records the caller in
        `reconciled_by` alongside the note." and "When `X-User-Role` is
        `PlatformAdmin`, `DispatchOps`, or `QaReviewer`, `X-User-ID` is an
        opaque operator identifier not tied to any persisted entity; the server
        may record it (for example as `reconciled_by` on a discrepancy case at
        reconcile time) but does not compare it to any entity's `id`."

        Design: Corner/rbac/signer_cannot_reconcile_own_discrepancy_case
        """
        ctx, case = self._setup_peer_review_case(api, "Hosp SD2")
        resp = api.reconcile_case(case["id"],
                                  {"reconciliation_note": "reviewed with both"},
                                  make_qa_headers("qa_neutral_1"))
        data = validate_success(resp, 200)
        assert data["status"] == "RECONCILED"
        assert data["reconciled_by"] == "qa_neutral_1"
