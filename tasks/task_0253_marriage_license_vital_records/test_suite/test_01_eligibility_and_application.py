"""Marriage application: creation, eligibility screen, and the approve/deny branch."""
from test_helpers import (
    validate_success,
    validate_error,
    get_success_data,
    ApiErrorId,
    create_application_payload,
    make_applicant_headers,
    set_clock,
    create_applicant,
    create_two_applicants,
    create_draft_application,
    create_under_review_application,
    CLERK_1,
)


# ===========================================================================
# Applicant creation (queue B: entities)
# ===========================================================================
def test_create_applicant_minimal_returns_201_and_defaults(api):
    """PRD §3.1: "the applicant's prior_marriage_status, one of NEVER_MARRIED,
    DIVORCED, WIDOWED, or MARRIED and defaulting to NEVER_MARRIED, and
    has_judicial_consent, a boolean defaulting to false".

    Design: Corner/entities/create_applicant_minimal_returns_201_and_defaults
    """
    resp = api.create_applicant(
        {"full_name": "Solo One", "date_of_birth": "1990-01-01"}, CLERK_1,
    )
    data = validate_success(resp, expected_status=201)
    assert data["prior_marriage_status"] == "NEVER_MARRIED"
    assert data["has_judicial_consent"] is False


def test_create_applicant_missing_full_name_returns_invalid_request(api):
    """PRD §2.10: "required fields present, enums valid, and integers in range ...,
    failing which the request is rejected with ERR_INVALID_REQUEST".

    Design: Corner/entities/create_applicant_missing_full_name_returns_invalid_request
    """
    resp = api.create_applicant({"date_of_birth": "1990-01-01"}, CLERK_1)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value, expected_status=400)


# ===========================================================================
# Initial state & invalid transitions (queue B: state_machines)
# ===========================================================================
def test_new_application_starts_in_draft(api):
    """PRD §3.2: "A freshly created application sits in DRAFT."

    Design: Corner/state_machines/new_application_starts_in_draft
    """
    a, b = create_two_applicants()
    resp = api.create_application(create_application_payload(a["id"], b["id"]), CLERK_1)
    data = validate_success(resp, expected_status=201)
    assert data["status"] == "DRAFT"


def test_decide_application_from_draft_without_submit_invalid_state(api):
    """PRD §3.2: "A clerk decides an application that is UNDER_REVIEW by supplying
    a decision."

    Design: Corner/state_machines/decide_application_from_draft_without_submit_invalid_state
    """
    a, b = create_two_applicants()
    app = create_draft_application(a["id"], b["id"])
    resp = api.decide_application(app["id"], {"decision": "APPROVE"}, CLERK_1)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value, expected_status=409)
    assert get_success_data(api.get_application(app["id"], CLERK_1))["status"] == "DRAFT"


# ===========================================================================
# Submit-time validations (queue B: validations / state_machines)
# ===========================================================================
def test_already_married_applicant_blocked_on_submit(api):
    """PRD §3.2: "neither party may carry a prior_marriage_status of MARRIED, or
    the submission is rejected with ERR_APPLICANT_ALREADY_MARRIED."

    Design: Corner/validations/already_married_applicant_blocked_on_submit
    """
    married = create_applicant(full_name="Am A", date_of_birth="1985-01-01",
                               prior_marriage_status="MARRIED")
    other = create_applicant(full_name="Am B", date_of_birth="1986-02-02")
    app = create_draft_application(married["id"], other["id"])
    resp = api.submit_application(app["id"], make_applicant_headers(married["id"]))
    validate_error(resp, ApiErrorId.ERR_APPLICANT_ALREADY_MARRIED.value, expected_status=409)
    assert get_success_data(api.get_application(app["id"], CLERK_1))["status"] == "DRAFT"


def test_duplicate_applicant_blocked_on_submit(api):
    """PRD §3.2: "the two must not be the same person, or the submission is rejected
    with ERR_DUPLICATE_APPLICANT".

    Design: Corner/validations/duplicate_applicant_blocked_on_submit
    """
    a = create_applicant(full_name="Du A", date_of_birth="1985-01-01")
    app = create_draft_application(a["id"], a["id"])
    resp = api.submit_application(app["id"], make_applicant_headers(a["id"]))
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_APPLICANT.value, expected_status=409)


# ===========================================================================
# Approval eligibility screen — age / consent / remarriage (queue B: validations)
# ===========================================================================
def test_age_ineligible_minor_under_sixteen(api):
    """PRD §3.2: "An applicant younger than 16 is ineligible regardless of consent,
    and the approval is rejected with ERR_AGE_INELIGIBLE."

    Design: Corner/validations/age_ineligible_minor_under_sixteen
    """
    set_clock("2026-01-10T09:00:00Z")
    minor = create_applicant(full_name="Ag A", date_of_birth="2010-06-01")  # age 15
    adult = create_applicant(full_name="Ag B", date_of_birth="1991-02-02")
    app = create_under_review_application(minor["id"], adult["id"])
    resp = api.decide_application(app["id"], {"decision": "APPROVE"}, CLERK_1)
    validate_error(resp, ApiErrorId.ERR_AGE_INELIGIBLE.value, expected_status=409)
    assert get_success_data(api.get_application(app["id"], CLERK_1))["status"] == "UNDER_REVIEW"


def test_minor_with_consent_between_16_and_18_approves(api):
    """PRD §3.2: "An applicant who is at least 16 but not yet 18 is eligible only if
    has_judicial_consent is true".

    Design: Corner/validations/minor_with_consent_between_16_and_18_approves
    """
    set_clock("2026-01-10T09:00:00Z")
    minor = create_applicant(full_name="Mc A", date_of_birth="2010-01-10",
                             has_judicial_consent=True)  # turns 16 exactly on clock date
    adult = create_applicant(full_name="Mc B", date_of_birth="1991-02-02")
    app = create_under_review_application(minor["id"], adult["id"])
    data = validate_success(api.decide_application(app["id"], {"decision": "APPROVE"}, CLERK_1))
    assert data["status"] == "APPROVED"


def test_minor_16_without_consent_requires_consent(api):
    """PRD §3.2: "if such an applicant lacks judicial consent the approval is
    rejected with ERR_JUDICIAL_CONSENT_REQUIRED."

    Design: Corner/validations/minor_16_without_consent_requires_consent
    """
    set_clock("2026-01-10T09:00:00Z")
    minor = create_applicant(full_name="Jc A", date_of_birth="2010-01-10",
                             has_judicial_consent=False)
    adult = create_applicant(full_name="Jc B", date_of_birth="1991-02-02")
    app = create_under_review_application(minor["id"], adult["id"])
    resp = api.decide_application(app["id"], {"decision": "APPROVE"}, CLERK_1)
    validate_error(resp, ApiErrorId.ERR_JUDICIAL_CONSENT_REQUIRED.value, expected_status=409)


def test_remarriage_wait_not_met_rejected(api):
    """PRD §3.2: "an applicant becomes eligible to remarry on the day exactly 30 days
    after dissolution and on every day thereafter, and an attempt before that day is
    rejected with ERR_REMARRIAGE_WAIT_NOT_MET."

    Design: Corner/validations/remarriage_wait_not_met_rejected
    """
    set_clock("2026-01-15T09:00:00Z")
    divorced = create_applicant(full_name="Rw A", date_of_birth="1985-01-01",
                                prior_marriage_status="DIVORCED",
                                prior_dissolution_date="2026-01-01")  # +30d = 2026-01-31
    other = create_applicant(full_name="Rw B", date_of_birth="1986-02-02")
    app = create_under_review_application(divorced["id"], other["id"])
    resp = api.decide_application(app["id"], {"decision": "APPROVE"}, CLERK_1)
    validate_error(resp, ApiErrorId.ERR_REMARRIAGE_WAIT_NOT_MET.value, expected_status=409)
    assert get_success_data(api.get_application(app["id"], CLERK_1))["status"] == "UNDER_REVIEW"


# ===========================================================================
# Approve vs deny branch (queue A: non_linear_state_machine)
# ===========================================================================
def test_application_approve_creates_license_and_charge(api):
    """PRD §3.2: "On a successful approval the application status becomes APPROVED,
    the acting clerk's X-User-ID is stored in approved_by_user_id, and the system
    issues a license, charges the license fee, and recomputes the application's
    total_charged_cents".

    Design: Difficulty/non_linear_state_machine/application_branch_approve_vs_deny_divergent_side_effects
    """
    set_clock("2026-01-10T09:00:00Z")
    a, b = create_two_applicants(
        {"full_name": "Hal Vega", "date_of_birth": "1990-01-01"},
        {"full_name": "Ivy Fox", "date_of_birth": "1991-02-02"},
    )
    app = create_under_review_application(a["id"], b["id"])
    data = validate_success(api.decide_application(app["id"], {"decision": "APPROVE"}, CLERK_1))
    assert data["status"] == "APPROVED"
    licenses = get_success_data(api.list_application_licenses(app["id"], CLERK_1))
    assert len(licenses) == 1, "APPROVE must create exactly one MarriageLicense"


def test_application_deny_creates_no_license_records_reason(api):
    """PRD §3.2: "when it is to deny, it advances from UNDER_REVIEW to DENIED,
    recording the supplied or derived denial_reason_code while leaving
    approved_by_user_id null and creating neither a license nor a charge."

    Design: Difficulty/non_linear_state_machine/application_branch_approve_vs_deny_divergent_side_effects
    """
    set_clock("2026-01-10T09:00:00Z")
    a, b = create_two_applicants(
        {"full_name": "Jo Nash", "date_of_birth": "1992-03-03"},
        {"full_name": "Kim Hale", "date_of_birth": "1993-04-04"},
    )
    app = create_under_review_application(a["id"], b["id"])
    data = validate_success(api.decide_application(
        app["id"], {"decision": "DENY", "denial_reason_code": "ERR_INVALID_REQUEST"}, CLERK_1,
    ))
    assert data["status"] == "DENIED"
    assert data["denial_reason_code"] == "ERR_INVALID_REQUEST"
    licenses = get_success_data(api.list_application_licenses(app["id"], CLERK_1))
    assert len(licenses) == 0, "DENY must create no MarriageLicense"
