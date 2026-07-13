"""Issuance preconditions, their pinned precedence, officer-active gating, and OCC."""
import test_helpers as th
from test_helpers import validate_error, get_success_data, ApiErrorId


def _two_dept_issue_ready_fire_pending(api, company_name):
    """Two ALL departments, COI verified, permit fee paid, POLICE review APPROVED but FIRE
    review left PENDING. Returns app id + a fresh issue_version."""
    th.set_clock(api, th.DEFAULT_CLOCK)
    pc = th.make_company(api, legal_name=company_name, contact_email=f"{company_name}@x.test", primary_contact="H")
    dept_pol = th.make_department(api, code="POLICE", name="Police")
    dept_fire = th.make_department(api, code="FIRE", name="Fire")
    app = th.make_application(api, pc["id"], title=company_name, synopsis="x")
    th.add_location(api, app["id"], pc["id"])
    coi = th.add_coi(api, app["id"], pc["id"])
    th.verify_coi(api, coi["id"])
    th.submit_app(api, app["id"], pc["id"])
    rev_pol = th.get_review(api, app["id"], dept_pol["id"])
    th.decide_review(api, rev_pol["id"], dept_pol["id"], "APPROVE")
    th.pay(api, app["id"], pc["id"], "PERMIT_FEE", 41200)
    return {"pc_id": pc["id"], "app_id": app["id"], "issue_version": th.current_version(api, app["id"])}


class TestIssueStateBeatsFiscal:
    """State precondition (ERR_REVIEWS_INCOMPLETE) pre-empts the fiscal one (ERR_FEE_UNPAID)."""

    def test_reviews_incomplete_reported_when_fee_also_unpaid(self, api):
        """PRD §3.5: "Before anything changes, four preconditions are checked in this order:"
        PRD §3.5: "1. Reviews complete. The application must be UNDER_REVIEW and every
        DepartmentReview for it must be APPROVED; otherwise issuance is rejected with
        ERR_REVIEWS_INCOMPLETE (HTTP 409)."
        PRD §3.5: "4. Permit fee paid. The application's amount_paid_cents must be at least its
        estimated_fee_cents; otherwise issuance is rejected with ERR_FEE_UNPAID (HTTP 402)."

        Design: Difficulty/priority_pair_validation_conflict/issue_state_beats_fiscal
        """
        ctx = th.setup_under_review_single_review(api, company_name="P5aCo",
                                                  with_coi=True, verify=True)  # review PENDING, no fee
        resp = api.issue_application(ctx["app_id"], {"expected_application_version": th.current_version(api, ctx["app_id"])},
                                     th.make_coordinator_headers())
        validate_error(resp, ApiErrorId.ERR_REVIEWS_INCOMPLETE.value)

    def test_issue_rejected_leaves_application_under_review(self, api):
        """PRD §3.5: "1. Reviews complete. The application must be UNDER_REVIEW and every
        DepartmentReview for it must be APPROVED; otherwise issuance is rejected with
        ERR_REVIEWS_INCOMPLETE (HTTP 409)."
        PRD §3.5: "4. Permit fee paid. The application's amount_paid_cents must be at least its
        estimated_fee_cents; otherwise issuance is rejected with ERR_FEE_UNPAID (HTTP 402)."

        Design: Difficulty/priority_pair_validation_conflict/issue_state_beats_fiscal
        """
        ctx = th.setup_under_review_single_review(api, company_name="P5a2Co",
                                                  with_coi=True, verify=True)
        resp = api.issue_application(ctx["app_id"], {"expected_application_version": th.current_version(api, ctx["app_id"])},
                                     th.make_coordinator_headers())
        assert resp.status_code == 409
        app = get_success_data(api.get_application(ctx["app_id"], th.make_coordinator_headers()))
        assert app["status"] == "UNDER_REVIEW"


class TestIssueRequiresAllReviewsApproved:
    """Cross-entity dependency: issuance depends on every DepartmentReview being APPROVED."""

    def test_pending_sibling_review_blocks_issue(self, api):
        """PRD §3.5: "1. Reviews complete. The application must be UNDER_REVIEW and every
        DepartmentReview for it must be APPROVED; otherwise issuance is rejected with
        ERR_REVIEWS_INCOMPLETE (HTTP 409)."

        Design: Difficulty/cross_entity_state_dependency/issue_requires_all_reviews_approved
        """
        ctx = _two_dept_issue_ready_fire_pending(api, "P7aCo")
        resp = api.issue_application(ctx["app_id"], {"expected_application_version": ctx["issue_version"]},
                                     th.make_coordinator_headers())
        validate_error(resp, ApiErrorId.ERR_REVIEWS_INCOMPLETE.value)

    def test_application_stays_under_review_when_a_review_pending(self, api):
        """PRD §3.5: "1. Reviews complete. The application must be UNDER_REVIEW and every
        DepartmentReview for it must be APPROVED; otherwise issuance is rejected with
        ERR_REVIEWS_INCOMPLETE (HTTP 409)."

        Design: Difficulty/cross_entity_state_dependency/issue_requires_all_reviews_approved
        """
        ctx = _two_dept_issue_ready_fire_pending(api, "P7a2Co")
        api.issue_application(ctx["app_id"], {"expected_application_version": ctx["issue_version"]},
                             th.make_coordinator_headers())
        app = get_success_data(api.get_application(ctx["app_id"], th.make_coordinator_headers()))
        assert app["status"] == "UNDER_REVIEW"


class TestAssignmentRequiresOfficerActive:
    """Cross-entity dependency: officer assignment creation depends on Officer.status."""

    def _under_review_app(self, api, company_name):
        ctx = th.setup_under_review_single_review(api, company_name=company_name,
                                                  app_overrides={"shoot_start_at": "2026-06-01T06:00:00Z",
                                                                 "shoot_end_at": "2026-06-01T20:00:00Z"})
        return ctx

    def test_inactive_officer_rejected(self, api):
        """PRD §3.6: "The referenced officer must be ACTIVE; an assignment against an INACTIVE
        officer is rejected with ERR_OFFICER_INACTIVE (HTTP 409)."

        Design: Difficulty/cross_entity_state_dependency/assignment_requires_officer_active
        """
        ctx = self._under_review_app(api, "P7bCo")
        officer = th.make_officer(api, full_name="Ofc Off", badge_number="B-0")
        get_success_data(api.update_officer(officer["id"], {"status": "INACTIVE"}, th.make_coordinator_headers()))
        resp = api.create_officer_assignment(
            {"application_id": ctx["app_id"], "officer_id": officer["id"],
             "shift_start_at": "2026-06-01T08:00:00Z", "shift_end_at": "2026-06-01T18:00:00Z"},
            th.make_coordinator_headers(),
        )
        validate_error(resp, ApiErrorId.ERR_OFFICER_INACTIVE.value)

    def test_active_officer_accepted_inactive_rejected(self, api):
        """PRD §3.6: "The referenced officer must be ACTIVE; an assignment against an INACTIVE
        officer is rejected with ERR_OFFICER_INACTIVE (HTTP 409)."

        Design: Difficulty/cross_entity_state_dependency/assignment_requires_officer_active
        """
        ctx = self._under_review_app(api, "P7b2Co")
        active = th.make_officer(api, full_name="Ofc Active", badge_number="B-A")
        inactive = th.make_officer(api, full_name="Ofc Gone", badge_number="B-G")
        get_success_data(api.update_officer(inactive["id"], {"status": "INACTIVE"}, th.make_coordinator_headers()))
        ok = api.create_officer_assignment(
            {"application_id": ctx["app_id"], "officer_id": active["id"],
             "shift_start_at": "2026-06-01T08:00:00Z", "shift_end_at": "2026-06-01T12:00:00Z"},
            th.make_coordinator_headers(),
        )
        assert ok.status_code == 201
        bad = api.create_officer_assignment(
            {"application_id": ctx["app_id"], "officer_id": inactive["id"],
             "shift_start_at": "2026-06-01T13:00:00Z", "shift_end_at": "2026-06-01T15:00:00Z"},
            th.make_coordinator_headers(),
        )
        validate_error(bad, ApiErrorId.ERR_OFFICER_INACTIVE.value)


def test_issue_fee_unpaid(api):
    """PRD §3.5: "4. Permit fee paid. The application's amount_paid_cents must be at least its
    estimated_fee_cents; otherwise issuance is rejected with ERR_FEE_UNPAID (HTTP 402)."

    Design: Corner/validations/issue_fee_unpaid_only
    """
    ctx = th.setup_issue_ready(api, company_name="Fee Co", pay_fee=False)
    resp = api.issue_application(ctx["app_id"], {"expected_application_version": ctx["issue_version"]},
                                th.make_coordinator_headers())
    validate_error(resp, ApiErrorId.ERR_FEE_UNPAID.value)


def test_issue_coi_not_verified(api):
    """PRD §3.5: "3. Insurance verified. At least one InsuranceCertificate for the application
    must be in VERIFIED status; otherwise issuance is rejected with ERR_COI_NOT_VERIFIED
    (HTTP 422)."

    Design: Corner/validations/issue_coi_not_verified
    """
    ctx = th.setup_issue_ready(api, company_name="NoCoi Co", with_verified_coi=False, pay_fee=True)
    resp = api.issue_application(ctx["app_id"], {"expected_application_version": ctx["issue_version"]},
                                th.make_coordinator_headers())
    validate_error(resp, ApiErrorId.ERR_COI_NOT_VERIFIED.value)


def test_deposit_payment_before_issue_not_allowed(api):
    """PRD §3.4: "The timing of each payment type is constrained: a PERMIT_FEE payment is
    allowed only while the application's status is UNDER_REVIEW or REVISION_REQUIRED, and a
    DEPOSIT payment is allowed only while the status is ISSUED. A payment whose type is not
    allowed for the current status is rejected with ERR_PAYMENT_NOT_ALLOWED (HTTP 409)."

    Design: Corner/validations/deposit_payment_before_issue_not_allowed
    """
    ctx = th.setup_under_review_single_review(api, company_name="Pay Co")
    resp = api.create_payment(ctx["app_id"], {"entry_type": "DEPOSIT", "amount_cents": 5000},
                              th.make_production_company_headers(ctx["pc_id"]))
    validate_error(resp, ApiErrorId.ERR_PAYMENT_NOT_ALLOWED.value)


def test_occ_coi_supersede_stale_version(api):
    """PRD §2.5: "The first guarded operation is submitting an insurance certificate. Because
    submitting a new certificate supersedes the prior active one and advances the application's
    version, a submission whose expected_application_version is older than the application's
    current version means another certificate has already been submitted since the client last
    read the application; the stale submission is rejected with ERR_STALE_APPLICATION_VERSION so
    the client cannot overwrite a certificate state it never saw."

    Design: Corner/cross_cutting_complexity_layers/occ_coi_supersede_stale_version
    """
    pc = th.make_company(api, legal_name="Occ Co", contact_email="oc@x.test", primary_contact="JJ")
    app = th.make_application(api, pc["id"], title="Occ")
    v1 = th.current_version(api, app["id"])
    th.add_coi(api, app["id"], pc["id"], expected_version=v1, policy_number="POL-O1")  # advances version
    resp = api.submit_insurance_certificate(
        app["id"], th.insurance_certificate_payload(v1, policy_number="POL-O2"),
        th.make_production_company_headers(pc["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_STALE_APPLICATION_VERSION.value)


def test_occ_issue_stale_after_rider_added(api):
    """PRD §2.5: "The second guarded operation is issuing the permit. Issuance stamps the final
    fee from the application's current set of approved riders and confirmed bookings; if the
    applicant has added a rider or a location since the coordinator last read the application,
    the application's version has advanced and issuing now would price a production different
    from the one the coordinator reviewed. Such an issue request is rejected with
    ERR_STALE_APPLICATION_VERSION."

    Design: Corner/cross_cutting_complexity_layers/occ_issue_stale_after_rider_added
    """
    ctx = th.setup_issue_ready(api, company_name="OccI Co")
    stale_version = ctx["issue_version"]
    th.add_rider(api, ctx["app_id"], ctx["pc_id"], "STILL_PHOTO")  # advances the version
    resp = api.issue_application(ctx["app_id"], {"expected_application_version": stale_version},
                                th.make_coordinator_headers())
    validate_error(resp, ApiErrorId.ERR_STALE_APPLICATION_VERSION.value)
