"""The application's two parallel lifecycles (review + verification) and the
business validations that gate the decide step.
"""
from test_helpers import (
    api_client as api,
    TEST_USERS,
    get_success_data, validate_success, validate_error, ApiErrorId,
    setup_config, open_application,
    setup_household_with_member, setup_application_under_review,
)

CW = TEST_USERS["caseworker_headers"]
APP = TEST_USERS["applicant_headers"]


# ===========================================================================
# Queue B — state_machines corner (Application)
# ===========================================================================
def test_initial_state_application_draft_unverified():
    """PRD §3.3: "An application advances along two independent state dimensions
    that live on the same record and evolve separately. The first is
    `review_status`, which begins at `DRAFT`. The second is
    `verification_status`, which begins at `UNVERIFIED`."

    Design: Corner/state_machines/initial_state_application_draft_unverified
    """
    hh, _member = setup_household_with_member(state="CA")
    app = open_application(hh["id"], magi_variant="POINT_IN_TIME")
    fresh = validate_success(api.get_application(app["id"], CW))
    assert fresh["review_status"] == "DRAFT"
    assert fresh["verification_status"] == "UNVERIFIED"


def test_submit_application_from_submitted_returns_invalid_state():
    """PRD §3.3: "Submission is only permitted while `review_status` is `DRAFT`".

    Design: Corner/state_machines/submit_application_from_submitted_returns_invalid_state
    """
    hh, _member = setup_household_with_member(state="CA")
    app = open_application(hh["id"], magi_variant="POINT_IN_TIME")
    api.submit_application(app["id"], APP)
    resp = api.submit_application(app["id"], APP)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


# ===========================================================================
# Queue B — validations corner
# ===========================================================================
def test_submit_empty_household_returns_empty_household():
    """PRD §3.3: "it requires that the household have at least one member whose
    `member_status` is `COUNTED`; a submission against a household with no counted
    member is rejected with `ERR_EMPTY_HOUSEHOLD`."

    Design: Corner/validations/submit_empty_household_returns_empty_household
    """
    setup_config(state="CA")
    hh = get_success_data(api.create_household(
        {"state_code": "CA", "fpl_year": 2026, "primary_applicant_name": "Empty E"}, CW))
    app = open_application(hh["id"], magi_variant="POINT_IN_TIME")
    resp = api.submit_application(app["id"], APP)
    validate_error(resp, ApiErrorId.ERR_EMPTY_HOUSEHOLD.value)


def test_decide_before_verified_returns_not_verified():
    """PRD §3.3: "in either direction it requires `verification_status` to have
    reached `VERIFIED`; deciding before verification completes is rejected with
    `ERR_NOT_VERIFIED`."

    Design: Corner/validations/decide_before_verified_returns_not_verified
    """
    hh, _member, app = setup_application_under_review(
        state="CA", income_overrides={"monthly_amount_cents": 120000})
    # An ELIGIBLE determination exists, but verification has not completed.
    api.run_determination(app["id"], CW)
    resp = api.decide_application(app["id"], {"target_status": "APPROVED"}, CW)
    validate_error(resp, ApiErrorId.ERR_NOT_VERIFIED.value)


def test_approve_without_eligible_determination_returns_no_eligible():
    """PRD §3.3: "Approval additionally requires that an eligibility determination
    already exist for the application whose `decision` is `ELIGIBLE`; an approval
    attempted without such a determination is rejected with
    `ERR_NO_ELIGIBLE_DETERMINATION`."

    Design: Corner/validations/approve_without_eligible_determination_returns_no_eligible
    """
    # TX adult threshold 100, income 132500 → fpl% 101 → INELIGIBLE determination.
    hh, _member, app = setup_application_under_review(
        state="TX", income_overrides={"monthly_amount_cents": 132500})
    api.run_determination(app["id"], CW)
    api.verify_application(app["id"], CW)
    resp = api.decide_application(app["id"], {"target_status": "APPROVED"}, CW)
    validate_error(resp, ApiErrorId.ERR_NO_ELIGIBLE_DETERMINATION.value)
