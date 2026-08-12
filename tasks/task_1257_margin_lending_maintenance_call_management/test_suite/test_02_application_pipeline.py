"""Application pipeline: review/approve/reject/resubmit lifecycle."""
from test_helpers import (
    ApiErrorId,
    api_client,
    create_application_payload,
    create_approved_account,
    create_customer,
    make_analyst_headers,
    make_customer_headers,
    make_supervisor_headers,
    validate_error,
    validate_success,
)


def test_approve_from_submitted_returns_invalid_state(api, analyst_headers):
    """PRD §3.1: "the application must stand in `COMPLIANCE_REVIEW` (else
    `ERR_APPLICATION_INVALID_STATE` — a wrong-state application surfaces this
    error rather than being masked by later checks)."

    Design: Corner/state_machines/approve_from_submitted_returns_invalid_state
    """
    customer = create_customer()
    cust = make_customer_headers(customer["id"])
    app = validate_success(
        api.create_account_application(create_application_payload(customer["id"]), cust),
        expected_status=201,
    )
    assert app["application_status"] == "SUBMITTED"
    resp = api.approve_application(app["id"], make_supervisor_headers("sup-1"))
    validate_error(resp, ApiErrorId.ERR_APPLICATION_INVALID_STATE)


def test_reject_then_resubmit_returns_to_submitted(api):
    """PRD §3.1: "the owning customer may resubmit, cycling the application
    from `REJECTED` back to `SUBMITTED`."
    PRD §3.1: "On resubmission `reviewed_by_user_id`, `decided_by_user_id`,
    and `rejection_reason` are all reset to null so the next review cycle
    starts clean."

    Design: Difficulty/non_linear_state_machine/application_resubmit_cycle_rejected_to_submitted
    """
    customer = create_customer()
    cust = make_customer_headers(customer["id"])
    app = validate_success(
        api.create_account_application(
            create_application_payload(
                customer["id"],
                annual_income_cents=1_000_000,
                liquid_net_worth_cents=100_000,
                investment_experience_years=0,
            ),
            cust,
        ),
        expected_status=201,
    )
    api.review_application(app["id"], make_analyst_headers("analyst-1"))
    rejected = validate_success(
        api.reject_application(
            app["id"], {"reason": "Insufficient experience"}, make_supervisor_headers("sup-1")
        )
    )
    assert rejected["application_status"] == "REJECTED"

    resubmitted = validate_success(
        api.resubmit_application(
            app["id"],
            {"liquid_net_worth_cents": 5_000_000, "investment_experience_years": 2},
            cust,
        )
    )
    assert resubmitted["application_status"] == "SUBMITTED"
    assert resubmitted["reviewed_by_user_id"] is None
    assert resubmitted["decided_by_user_id"] is None
    assert resubmitted["rejection_reason"] is None
    assert resubmitted["liquid_net_worth_cents"] == 5_000_000
    assert resubmitted["investment_experience_years"] == 2


def test_resubmit_then_second_cycle_approve_creates_active_account(api):
    """PRD §3.1: "On approval the supervisor's identity lands in
    `decided_by_user_id`, and the system creates the `MarginAccount`: owned by
    the customer, linked back to the application through `application_id`, with
    `account_status` `ACTIVE` ..."
    PRD §3.1: "the application reaches its terminal `APPROVED` state."

    Design: Difficulty/non_linear_state_machine/application_resubmit_cycle_rejected_to_submitted
    """
    customer = create_customer()
    cust = make_customer_headers(customer["id"])
    app = validate_success(
        api.create_account_application(
            create_application_payload(
                customer["id"],
                annual_income_cents=1_000_000,
                liquid_net_worth_cents=100_000,
                investment_experience_years=0,
            ),
            cust,
        ),
        expected_status=201,
    )
    api.review_application(app["id"], make_analyst_headers("analyst-1"))
    api.reject_application(
        app["id"], {"reason": "Insufficient experience"}, make_supervisor_headers("sup-1")
    )
    api.resubmit_application(
        app["id"],
        {"liquid_net_worth_cents": 5_000_000, "investment_experience_years": 2},
        cust,
    )
    api.review_application(app["id"], make_analyst_headers("analyst-1"))
    approved = validate_success(
        api.approve_application(app["id"], make_supervisor_headers("sup-1"))
    )
    assert approved["application_status"] == "APPROVED"
    assert approved["account_id"] is not None
    account = validate_success(
        api.get_account(approved["account_id"], make_supervisor_headers("sup-1"))
    )
    assert account["account_status"] == "ACTIVE"
    assert account["customer_id"] == customer["id"]
    assert account["application_id"] == app["id"]


def test_reviewer_cannot_approve_own_review(api):
    """PRD §2.1: "the supervisor who approves or rejects an application must
    not be the analyst who reviewed it ... Any such self-dealing attempt is
    rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403)."

    Design: Corner/rbac/segregation_reviewer_cannot_approve_own_review
    """
    customer = create_customer()
    cust = make_customer_headers(customer["id"])
    app = validate_success(
        api.create_account_application(create_application_payload(customer["id"]), cust),
        expected_status=201,
    )
    api.review_application(app["id"], make_analyst_headers("analyst-1"))
    resp = api.approve_application(app["id"], make_supervisor_headers("analyst-1"))
    validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)
    # A different supervisor approves successfully.
    approved = validate_success(
        api.approve_application(app["id"], make_supervisor_headers("sup-2"))
    )
    assert approved["application_status"] == "APPROVED"
    assert approved["account_id"] is not None


def test_approve_suitability_not_met_when_net_worth_below_minimum(api):
    """PRD §3.1: "the applicant must clear the suitability bar —
    `liquid_net_worth_cents` of at least 200,000 cents (two thousand dollars)
    and `investment_experience_years` of at least 1 (else
    `ERR_SUITABILITY_NOT_MET`)."

    Design: Corner/errors/error_suitability_not_met_on_approve
    """
    customer = create_customer()
    cust = make_customer_headers(customer["id"])
    app = validate_success(
        api.create_account_application(
            create_application_payload(
                customer["id"],
                annual_income_cents=1_000_000,
                liquid_net_worth_cents=100_000,
                investment_experience_years=5,
            ),
            cust,
        ),
        expected_status=201,
    )
    api.review_application(app["id"], make_analyst_headers("analyst-1"))
    resp = api.approve_application(app["id"], make_supervisor_headers("sup-1"))
    validate_error(resp, ApiErrorId.ERR_SUITABILITY_NOT_MET)
