"""Award approval gates: certificate dependency (education completeness),
separation-of-duties precedence over certificate currency, and expired-cert
rejection.

Difficulty:
  cross_entity_state_dependency / award_approve_depends_on_certificate
  priority_pair_validation_conflict / safety_beats_temporal_on_approve
Corner:
  validations / expired_certificate_on_approve_returns_error
"""
from test_helpers import validate_success, validate_error, ApiErrorId
from test_helpers import fixtures as fx
from test_helpers.test_users import make_case_manager_headers


# --- cross_entity_state_dependency / award_approve_depends_on_certificate ----
def test_approve_without_certificate_rejected(api):
    """PRD 3.4: "Second, the education requirement: the applicant must have at
    least one certificate that was ever issued — in either `VALID` or `EXPIRED`
    status — confirming that education was completed at some point; if the
    applicant has no certificate at all, approval is rejected with
    `ERR_EDUCATION_INCOMPLETE` (HTTP 422)."

    Design: Difficulty/cross_entity_state_dependency/award_approve_depends_on_certificate
    """
    ctx = fx.setup_eligible_application(api, with_education=False, reviewer_id="cm_reviewer")
    award = fx.new_award(api, ctx["application"]["id"], "SHARED_APPRECIATION")
    resp = api.approve_award(award["id"], make_case_manager_headers("cm_approver"))
    validate_error(resp, ApiErrorId.ERR_EDUCATION_INCOMPLETE.value)


def test_approve_with_certificate_and_distinct_approver_succeeds(api):
    """PRD 3.4: "Approving an award moves it from `PENDING_EDUCATION` to
    `APPROVED` and is a case-manager action."
    PRD 3.4: "On success the award records the approving operator's `X-User-ID`
    in `approved_by_user_id` and enters `APPROVED`."

    Design: Difficulty/cross_entity_state_dependency/award_approve_depends_on_certificate
    """
    ctx = fx.setup_eligible_application(api, with_education=True, reviewer_id="cm_reviewer")
    award = fx.new_award(api, ctx["application"]["id"], "SHARED_APPRECIATION")
    data = validate_success(api.approve_award(award["id"], make_case_manager_headers("cm_approver")), 200)
    assert data["status"] == "APPROVED"


# --- priority_pair_validation_conflict / safety_beats_temporal_on_approve ----
def test_sod_beats_expired_certificate(api):
    """PRD 3.4: "Three further conditions are then checked in this order. First,
    separation of duties: the approving `X-User-ID` must differ from the
    `reviewed_by_user_id` recorded on the underlying application; if the same
    operator who reviewed the application to eligibility attempts the approval,
    it is rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403)."

    Design: Difficulty/priority_pair_validation_conflict/safety_beats_temporal_on_approve
    """
    # Reviewer == approver (cm_solo) AND certificate expired: SoD wins.
    ctx = fx.setup_eligible_application(
        api, with_education=True, reviewer_id="cm_solo", attend_clock="2026-07-02T13:00:00Z"
    )
    award = fx.new_award(api, ctx["application"]["id"], "SHARED_APPRECIATION")
    fx.set_clock(api, "2027-08-01T00:00:00Z")  # cert (expires 2027-07-02) now expired
    resp = api.approve_award(award["id"], make_case_manager_headers("cm_solo"))
    validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value)


def test_sod_rejected_even_with_valid_certificate(api):
    """PRD 3.4: "First, separation of duties: the approving `X-User-ID` must
    differ from the `reviewed_by_user_id` recorded on the underlying
    application; if the same operator who reviewed the application to
    eligibility attempts the approval, it is rejected with
    `ERR_SEGREGATION_OF_DUTIES` (HTTP 403)."

    Design: Difficulty/priority_pair_validation_conflict/safety_beats_temporal_on_approve
    """
    # Reviewer == approver (cm_solo) with a still-valid certificate: SoD still fires.
    ctx = fx.setup_eligible_application(api, with_education=True, reviewer_id="cm_solo")
    award = fx.new_award(api, ctx["application"]["id"], "SHARED_APPRECIATION")
    resp = api.approve_award(award["id"], make_case_manager_headers("cm_solo"))
    validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value)


# --- Corner / expired_certificate_on_approve_returns_error ------------------
def test_expired_certificate_on_approve_returns_error(api):
    """PRD 3.4: "Third, certificate currency: the certificate must still be
    in-date, meaning the current logical clock is at or before its `expires_at`;
    an expired certificate is rejected with `ERR_CERTIFICATE_EXPIRED`
    (HTTP 422)."

    Design: Corner/validations/expired_certificate_on_approve_returns_error
    """
    # Distinct approver so SoD passes; certificate expired so currency fails.
    ctx = fx.setup_eligible_application(
        api, with_education=True, reviewer_id="cm_reviewer", attend_clock="2026-07-02T13:00:00Z"
    )
    award = fx.new_award(api, ctx["application"]["id"], "SHARED_APPRECIATION")
    fx.set_clock(api, "2027-08-01T00:00:00Z")
    resp = api.approve_award(award["id"], make_case_manager_headers("cm_approver"))
    validate_error(resp, ApiErrorId.ERR_CERTIFICATE_EXPIRED.value)
