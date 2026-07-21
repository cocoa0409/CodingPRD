"""Application review cycle (NEEDS_INFO <-> UNDER_REVIEW) and invalid-state
guards on withdraw/resubmit.

Difficulty:
  non_linear_state_machine / application_needs_info_review_cycle
Corner:
  state_machines / withdraw_already_withdrawn_returns_invalid_state
  state_machines / resubmit_from_submitted_returns_invalid_state
"""
from test_helpers import validate_success, validate_error, ApiErrorId
from test_helpers import fixtures as fx
from test_helpers.test_users import make_applicant_headers, make_case_manager_headers


def _under_review_application(api):
    program = fx.new_program(api)
    fx.new_income_limit(api, program["id"], household_size=4, ami_100_income_cents=10_000_000)
    applicant = fx.new_applicant(api, household_size=4, annual_income_cents=6_000_000)
    prop = fx.new_property(api, purchase_price_cents=20_000_000)
    application = fx.new_application(
        api, applicant["id"], program["id"], prop["id"],
        first_mortgage_amount_cents=15_000_000, buyer_contribution_cents=100_000,
    )
    fx.submit(api, application["id"], applicant["id"])
    fx.review(api, application["id"], "START", "cm_reviewer")
    return application, applicant


# --- non_linear_state_machine / application_needs_info_review_cycle ---------
def test_review_needs_info_sends_to_needs_info(api):
    """PRD 3.2: "From `UNDER_REVIEW`, a decision of `NEEDS_INFO` sends the
    application to `NEEDS_INFO` and records the `review_notes`; the applicant
    then resubmits, which returns the application from `NEEDS_INFO` to
    `UNDER_REVIEW` and recomputes `ami_pct` and `estimated_assistance_cents`
    from the application's current inputs."

    Design: Difficulty/non_linear_state_machine/application_needs_info_review_cycle
    """
    application, _ = _under_review_application(api)
    data = validate_success(
        api.review_application(
            application["id"], {"decision": "NEEDS_INFO", "review_notes": "need paystubs"},
            make_case_manager_headers("cm_reviewer"),
        ),
        200,
    )
    assert data["status"] == "NEEDS_INFO"


def test_resubmit_after_needs_info_returns_to_under_review(api):
    """PRD 3.2: "From `UNDER_REVIEW`, a decision of `NEEDS_INFO` sends the
    application to `NEEDS_INFO` and records the `review_notes`; the applicant
    then resubmits, which returns the application from `NEEDS_INFO` to
    `UNDER_REVIEW` and recomputes `ami_pct` and `estimated_assistance_cents`
    from the application's current inputs."

    Design: Difficulty/non_linear_state_machine/application_needs_info_review_cycle
    """
    application, applicant = _under_review_application(api)
    fx.review(api, application["id"], "NEEDS_INFO", "cm_reviewer", review_notes="need paystubs")
    data = validate_success(
        api.resubmit_application(application["id"], make_applicant_headers(applicant["id"])), 200
    )
    assert data["status"] == "UNDER_REVIEW"


# --- Corner / withdraw_already_withdrawn_returns_invalid_state --------------
def test_withdraw_already_withdrawn_returns_invalid_state(api):
    """PRD 3.2: "At any point while an application is in `DRAFT`, `SUBMITTED`,
    `UNDER_REVIEW`, or `NEEDS_INFO`, the applicant may withdraw it, moving it to
    the terminal `WITHDRAWN` state."
    PRD 2.8: "then the generic state-machine guard (`ERR_INVALID_STATE`, when the
    target resource is not in a state from which the requested transition is
    defined)".

    Design: Corner/state_machines/withdraw_already_withdrawn_returns_invalid_state
    """
    program = fx.new_program(api)
    applicant = fx.new_applicant(api)
    prop = fx.new_property(api)
    application = fx.new_application(api, applicant["id"], program["id"], prop["id"])
    validate_success(api.withdraw_application(application["id"], make_applicant_headers(applicant["id"])), 200)
    resp = api.withdraw_application(application["id"], make_applicant_headers(applicant["id"]))
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


# --- Corner / resubmit_from_submitted_returns_invalid_state -----------------
def test_resubmit_from_submitted_returns_invalid_state(api):
    """PRD 3.2: "the applicant then resubmits, which returns the application from
    `NEEDS_INFO` to `UNDER_REVIEW` and recomputes `ami_pct` and
    `estimated_assistance_cents` from the application's current inputs."
    PRD 2.8: "then the generic state-machine guard (`ERR_INVALID_STATE`, when the
    target resource is not in a state from which the requested transition is
    defined)".

    Design: Corner/state_machines/resubmit_from_submitted_returns_invalid_state
    """
    program = fx.new_program(api)
    fx.new_income_limit(api, program["id"], household_size=4, ami_100_income_cents=10_000_000)
    applicant = fx.new_applicant(api)
    prop = fx.new_property(api)
    application = fx.new_application(api, applicant["id"], program["id"], prop["id"])
    fx.submit(api, application["id"], applicant["id"])  # now SUBMITTED, never NEEDS_INFO
    resp = api.resubmit_application(application["id"], make_applicant_headers(applicant["id"]))
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)
