"""Composite setup helpers.

Every test starts against an empty database, so all preconditions are built from
scratch here through the endpoints the PRD declares. These helpers use the
lenient `get_success_data` reader: a setup step that returns the wrong shape is a
setup failure, not the assertion the test is making.
"""
from prd_bench_local_runner.testing import get_success_data

from .factories import (
    beneficiary_allocation_payload,
    capital_position_payload,
    carrier_payload,
    consent_record_payload,
    death_claim_payload,
    diligence_review_payload,
    employee_payload,
    exchange_analysis_payload,
    nqdc_liability_payload,
    nqdc_plan_payload,
    policy_payload,
    policy_valuation_payload,
    product_type_payload,
    purchase_request_payload,
    risk_assessment_payload,
)
from .test_users import (
    make_benefits_analyst_headers,
    make_board_secretary_headers,
    make_claims_administrator_headers,
    make_platform_admin_headers,
    make_risk_officer_headers,
    make_treasury_controller_headers,
)

ADMIN = make_platform_admin_headers("admin-1")
ANALYST = make_benefits_analyst_headers("analyst-1")
RISK = make_risk_officer_headers("risk-1")
TREASURY = make_treasury_controller_headers("treasury-1")
CLAIMS = make_claims_administrator_headers("claims-1")
BOARD = make_board_secretary_headers("board-1")


# --------------------------------------------------------------------------
# Logical clock
# --------------------------------------------------------------------------
def move_clock(api, to_iso8601: str) -> dict:
    """Move the platform clock to an instant and return the reported result."""
    return get_success_data(api.set_clock(to_iso8601, ADMIN))


# --------------------------------------------------------------------------
# Capital, carriers, products, diligence
# --------------------------------------------------------------------------
def file_capital_position(api, **overrides) -> dict:
    return get_success_data(
        api.create_capital_position(capital_position_payload(**overrides), TREASURY)
    )


def onboard_carrier(api, **overrides) -> dict:
    """Onboard a carrier; it opens in PENDING_DILIGENCE."""
    return get_success_data(api.create_carrier(carrier_payload(**overrides), ADMIN))


def register_product_type(api, carrier_id: str, **overrides) -> dict:
    return get_success_data(
        api.create_product_type(product_type_payload(carrier_id, **overrides), ADMIN)
    )


def open_diligence_review(api, carrier_id: str, submitter: str = "analyst-1", **overrides) -> dict:
    return get_success_data(
        api.create_diligence_review(
            diligence_review_payload(carrier_id, **overrides),
            make_benefits_analyst_headers(submitter),
        )
    )


def submit_diligence_review(api, review_id: str, submitter: str = "analyst-1") -> dict:
    return get_success_data(
        api.submit_diligence_review(review_id, make_benefits_analyst_headers(submitter))
    )


def authorize_carrier(
    api,
    carrier_id: str,
    submitter: str = "analyst-1",
    approver: str = "risk-1",
    **review_overrides,
) -> dict:
    """Open, submit and approve a diligence review so the carrier is AUTHORIZED.

    The submitting analyst and the deciding risk officer are deliberately
    different users: the same user may not both submit and decide a review.
    """
    review = open_diligence_review(api, carrier_id, submitter=submitter, **review_overrides)
    submit_diligence_review(api, review["id"], submitter=submitter)
    return get_success_data(
        api.approve_diligence_review(review["id"], make_risk_officer_headers(approver))
    )


def authorized_carrier_with_product(
    api, carrier_overrides=None, product_overrides=None, review_overrides=None
) -> dict:
    """A filed capital snapshot, an AUTHORIZED carrier and one OPEN product."""
    capital = file_capital_position(api)
    carrier = onboard_carrier(api, **(carrier_overrides or {}))
    product = register_product_type(api, carrier["id"], **(product_overrides or {}))
    review = authorize_carrier(api, carrier["id"], **(review_overrides or {}))
    return {
        "capital_position_id": capital["id"],
        "capital_position": capital,
        "carrier_id": carrier["id"],
        "carrier": carrier,
        "product_type_id": product["id"],
        "product_type": product,
        "review_id": review["id"],
        "review": review,
    }


# --------------------------------------------------------------------------
# Employees and consent
# --------------------------------------------------------------------------
def register_employee(api, **overrides) -> dict:
    return get_success_data(api.create_employee(employee_payload(**overrides), ANALYST))


def draft_consent(api, employee_id: str, **overrides) -> dict:
    return get_success_data(
        api.create_consent_record(consent_record_payload(employee_id, **overrides), ANALYST)
    )


def execute_consent(api, employee_id: str, **overrides) -> dict:
    """Create a consent record and record the employee signature on it."""
    consent = draft_consent(api, employee_id, **overrides)
    return get_success_data(api.execute_consent_record(consent["id"], ANALYST))


def insured_employee(api, employee_overrides=None, consent_overrides=None) -> dict:
    """An employee whose executed consent establishes insurable interest."""
    employee = register_employee(api, **(employee_overrides or {}))
    consent = execute_consent(api, employee["id"], **(consent_overrides or {}))
    return {
        "employee_id": employee["id"],
        "employee": employee,
        "consent_id": consent["id"],
        "consent": consent,
    }


# --------------------------------------------------------------------------
# Purchase requests
# --------------------------------------------------------------------------
def draft_purchase_request(
    api, carrier_id: str, product_type_id: str, employee_id: str, **overrides
) -> dict:
    return get_success_data(
        api.create_purchase_request(
            purchase_request_payload(carrier_id, product_type_id, employee_id, **overrides),
            ANALYST,
        )
    )


def submitted_purchase_request(
    api, carrier_id: str, product_type_id: str, employee_id: str, submitter: str = "analyst-1", **overrides
) -> dict:
    request = draft_purchase_request(api, carrier_id, product_type_id, employee_id, **overrides)
    return get_success_data(
        api.submit_purchase_request(request["id"], make_benefits_analyst_headers(submitter))
    )


def diligence_cleared_request(
    api, carrier_id: str, product_type_id: str, employee_id: str, submitter: str = "analyst-1", **overrides
) -> dict:
    request = submitted_purchase_request(
        api, carrier_id, product_type_id, employee_id, submitter=submitter, **overrides
    )
    return get_success_data(api.clear_purchase_request_diligence(request["id"], RISK))


def current_carrier_version(api, carrier_id: str) -> int:
    """Read the carrier's current version, which a reservation must echo."""
    return get_success_data(api.get_carrier(carrier_id, RISK))["version"]


def reserve_capacity(api, request_id: str, carrier_id: str, headers=None):
    """Reserve capacity, echoing the carrier version read immediately beforehand.

    Returns the raw response so a test can assert on the reservation outcome.
    """
    version = current_carrier_version(api, carrier_id)
    return api.reserve_purchase_request_capacity(
        request_id, {"expected_carrier_version": version}, headers or TREASURY
    )


def reserved_capacity_request(api, request_id: str, carrier_id: str) -> dict:
    return get_success_data(reserve_capacity(api, request_id, carrier_id))


def approve_purchase_request(api, request_id: str, carrier_id: str, approver: str = "risk-1") -> dict:
    """Carry a CAPACITY_RESERVED request through to APPROVED.

    A request whose premium required a regulatory notice must file that notice
    and let the waiting period elapse first; a request below the threshold goes
    straight to concurrence.
    """
    request = get_success_data(api.get_purchase_request(request_id, RISK))
    if request.get("notice_required"):
        request = get_success_data(api.file_purchase_request_notice(request_id, TREASURY))
        move_clock(api, request["notice_waiting_ends_at"])
    get_success_data(api.request_purchase_request_concurrence(request_id, ANALYST))
    return get_success_data(
        api.approve_purchase_request(request_id, make_risk_officer_headers(approver))
    )


def approved_purchase_request(
    api, carrier_id: str, product_type_id: str, employee_id: str, **overrides
) -> dict:
    request = diligence_cleared_request(
        api, carrier_id, product_type_id, employee_id, **overrides
    )
    reserved_capacity_request(api, request["id"], carrier_id)
    return approve_purchase_request(api, request["id"], carrier_id)


# --------------------------------------------------------------------------
# Policies and statement periods
# --------------------------------------------------------------------------
def issue_policy(api, purchase_request_id: str, **overrides) -> dict:
    return get_success_data(
        api.create_policy(policy_payload(purchase_request_id, **overrides), ANALYST)
    )


def in_force_policy(
    api,
    carrier_overrides=None,
    product_overrides=None,
    review_overrides=None,
    employee_overrides=None,
    consent_overrides=None,
    request_overrides=None,
    policy_overrides=None,
) -> dict:
    """The whole placement chain: capital snapshot through to an IN_FORCE policy.

    Returns every identifier the chain created so a test can drive any later
    workflow — statement periods, death claims, exchanges or plan funding —
    without rebuilding the chain by hand.
    """
    carrier_ctx = authorized_carrier_with_product(
        api,
        carrier_overrides=carrier_overrides,
        product_overrides=product_overrides,
        review_overrides=review_overrides,
    )
    employee_ctx = insured_employee(
        api, employee_overrides=employee_overrides, consent_overrides=consent_overrides
    )
    request = approved_purchase_request(
        api,
        carrier_ctx["carrier_id"],
        carrier_ctx["product_type_id"],
        employee_ctx["employee_id"],
        **(request_overrides or {}),
    )
    policy = issue_policy(api, request["id"], **(policy_overrides or {}))
    context = dict(carrier_ctx)
    context.update(employee_ctx)
    context.update(
        {
            "request_id": request["id"],
            "purchase_request": request,
            "policy_id": policy["id"],
            "policy": policy,
        }
    )
    return context


def post_valuation(api, policy_id: str, **overrides) -> dict:
    return get_success_data(
        api.create_policy_valuation(policy_valuation_payload(policy_id, **overrides), TREASURY)
    )


# --------------------------------------------------------------------------
# Deferred compensation plans
# --------------------------------------------------------------------------
def create_plan(api, **overrides) -> dict:
    return get_success_data(api.create_nqdc_plan(nqdc_plan_payload(**overrides), TREASURY))


def add_liability(api, plan_id: str, employee_id: str, **overrides) -> dict:
    return get_success_data(
        api.create_nqdc_liability(
            nqdc_liability_payload(plan_id, employee_id, **overrides), TREASURY
        )
    )


def plan_with_liability(api, employee_id: str, plan_overrides=None, liability_overrides=None) -> dict:
    plan = create_plan(api, **(plan_overrides or {}))
    liability = add_liability(api, plan["id"], employee_id, **(liability_overrides or {}))
    return {
        "plan_id": plan["id"],
        "plan": plan,
        "liability_id": liability["id"],
        "liability": liability,
    }


def funding_summary(api, plan_id: str, basis: str = None) -> dict:
    params = {"basis": basis} if basis else None
    return get_success_data(api.get_nqdc_funding_summary(plan_id, TREASURY, params=params))


# --------------------------------------------------------------------------
# Death benefit claims
# --------------------------------------------------------------------------
def file_claim(api, policy_id: str, **overrides) -> dict:
    return get_success_data(
        api.create_death_claim(death_claim_payload(policy_id, **overrides), CLAIMS)
    )


def approved_claim(api, policy_id: str, approver: str = "risk-1", **overrides) -> dict:
    """File a claim, move it into adjudication and approve it."""
    claim = file_claim(api, policy_id, **overrides)
    get_success_data(api.start_claim_adjudication(claim["id"], CLAIMS))
    return get_success_data(
        api.approve_death_claim(claim["id"], make_risk_officer_headers(approver))
    )


def add_allocation(api, claim_id: str, **overrides) -> dict:
    return get_success_data(
        api.create_beneficiary_allocation(
            beneficiary_allocation_payload(claim_id, **overrides), CLAIMS
        )
    )


def seal_allocations(api, claim_id: str) -> dict:
    return get_success_data(api.seal_claim_allocations(claim_id, CLAIMS))


def claim_allocations(api, claim_id: str) -> list:
    """Every beneficiary allocation on a claim, in created_at order."""
    body = api.list_beneficiary_allocations(CLAIMS, params={"claim_id": claim_id}).json()
    return body["data"]


# --------------------------------------------------------------------------
# Exchange and surrender analyses
# --------------------------------------------------------------------------
def current_policy_version(api, policy_id: str) -> int:
    """Read the policy's current version, which an analysis create must echo."""
    return get_success_data(api.get_policy(policy_id, TREASURY))["version"]


def create_analysis(api, policy_id: str, expected_policy_version: int = None, **overrides) -> dict:
    if expected_policy_version is None:
        expected_policy_version = current_policy_version(api, policy_id)
    return get_success_data(
        api.create_exchange_analysis(
            exchange_analysis_payload(policy_id, expected_policy_version, **overrides), TREASURY
        )
    )


def committed_analysis(api, policy_id: str, **overrides) -> dict:
    """Draft, review and commit an analysis so the policy is PENDING_EXCHANGE."""
    analysis = create_analysis(api, policy_id, **overrides)
    get_success_data(api.review_exchange_analysis(analysis["id"], RISK))
    return get_success_data(api.commit_exchange_analysis(analysis["id"], TREASURY))


# --------------------------------------------------------------------------
# Annual risk assessment
# --------------------------------------------------------------------------
def compile_assessment(api, capital_position_id: str, **overrides) -> dict:
    return get_success_data(
        api.create_risk_assessment(
            risk_assessment_payload(capital_position_id, **overrides), RISK
        )
    )


def returned_assessment(api, capital_position_id: str, board_note: str = "Rework", **overrides) -> dict:
    """Compile, submit and have the board return an assessment for rework."""
    assessment = compile_assessment(api, capital_position_id, **overrides)
    get_success_data(api.submit_risk_assessment_to_board(assessment["id"], RISK))
    return get_success_data(
        api.return_risk_assessment(assessment["id"], {"board_note": board_note}, BOARD)
    )
