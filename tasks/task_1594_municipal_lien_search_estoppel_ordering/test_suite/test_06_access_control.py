"""Access-control claims: role-exclusivity denials, ownership, and both
segregation-of-duties checks."""
from test_helpers import (
    ApiErrorId,
    FINDINGS_EMPTY,
    UTILITY_ONLY_DEPARTMENTS,
    create_jurisdiction_payload,
    create_search_order,
    file_discrepancy,
    get_discrepancy,
    get_order,
    get_task,
    list_order_tasks,
    make_provider_admin_headers,
    make_qa_reviewer_headers,
    make_research_analyst_headers,
    make_title_agent_headers,
    record_findings,
    set_clock,
    complete_task,
    setup_config_a,
    setup_identified_order,
    setup_in_verification,
    start_review,
    submit_order,
    validate_error,
    validate_success,
)

ADMIN = make_provider_admin_headers()
AGENT = make_title_agent_headers("agent_1")
AGENT2 = make_title_agent_headers("agent_2")
ANALYST = make_research_analyst_headers("analyst_1")
QA = make_qa_reviewer_headers("qa_1")


def test_title_agent_cannot_verify_payoff(api):
    """PRD 2.1: "A request whose role is not listed among an endpoint's
    authorized roles is rejected with `ERR_FORBIDDEN_FOR_ROLE` (HTTP 403)."
    PRD 4: POST /search-orders/{id}/verify-payoff is authorized for QAReviewer.

    Design: Corner/rbac/title_agent_cannot_verify_payoff
    """
    ctx = setup_in_verification(
        "P-Z4",
        departments=UTILITY_ONLY_DEPARTMENTS,
        with_association=False,
        findings_per_task=[FINDINGS_EMPTY],
    )
    response = api.verify_payoff(
        ctx["order"]["id"], {"verified_payoff_total_cents": 0}, AGENT
    )
    validate_error(response, ApiErrorId.ERR_FORBIDDEN_FOR_ROLE.value)
    assert get_order(ctx["order"]["id"])["status"] == "VERIFICATION"


def test_research_analyst_cannot_create_jurisdiction(api):
    """PRD 2.1: "A request whose role is not listed among an endpoint's
    authorized roles is rejected with `ERR_FORBIDDEN_FOR_ROLE` (HTTP 403)."
    PRD 4: POST /jurisdictions is authorized for ProviderAdmin.

    Design: Corner/rbac/research_analyst_cannot_create_jurisdiction
    """
    set_clock()
    response = api.create_jurisdiction(
        create_jurisdiction_payload(code="FL-ORA", name="Orange"), ANALYST
    )
    validate_error(response, ApiErrorId.ERR_FORBIDDEN_FOR_ROLE.value)


def test_qa_reviewer_cannot_record_findings(api):
    """PRD 2.1: "A request whose role is not listed among an endpoint's
    authorized roles is rejected with `ERR_FORBIDDEN_FOR_ROLE` (HTTP 403)."
    PRD 4: POST /research-tasks/{id}/record-findings is authorized for
    ResearchAnalyst.

    Design: Corner/rbac/qa_reviewer_cannot_record_findings
    """
    ctx = setup_identified_order(
        "P-AA5", departments=UTILITY_ONLY_DEPARTMENTS, with_association=False
    )
    task = ctx["tasks"][0]
    response = api.record_findings(
        task["id"],
        {"expected_research_task_version": task["version"], "findings": []},
        QA,
    )
    validate_error(response, ApiErrorId.ERR_FORBIDDEN_FOR_ROLE.value)
    assert get_task(task["id"])["status"] == "PENDING"


def test_provider_admin_cannot_file_discrepancy(api):
    """PRD 2.1: "A request whose role is not listed among an endpoint's
    authorized roles is rejected with `ERR_FORBIDDEN_FOR_ROLE` (HTTP 403)."
    PRD 4: POST /discrepancies is authorized for TitleAgent.

    Design: Corner/rbac/provider_admin_cannot_file_discrepancy
    """
    ctx = setup_identified_order(
        "P-AB6", departments=UTILITY_ONLY_DEPARTMENTS, with_association=False
    )
    task = ctx["tasks"][0]
    response = api.create_discrepancy(
        {
            "search_order_id": ctx["order"]["id"],
            "subject_type": "RESEARCH_TASK",
            "subject_id": task["id"],
            "discrepancy_type": "BALANCE_MISMATCH",
            "claimed_amount_cents": 5000,
            "description": "admin filing",
        },
        ADMIN,
    )
    validate_error(response, ApiErrorId.ERR_FORBIDDEN_FOR_ROLE.value)


def test_non_owner_cannot_cancel_order(api):
    """PRD 2.1: "Ownership is enforced by identity comparison: the order-owning
    operations — updating an order, cancelling an order, filing a discrepancy
    against it, and acknowledging its delivery — require `X-User-ID` to equal
    the order's `title_agent_id`, and any other caller is rejected with
    `ERR_NOT_ORDER_OWNER` (HTTP 403)."

    Design: Corner/rbac/non_owner_cannot_cancel_order
    """
    set_clock()
    order = create_search_order("P-AC7", property_address="7 AC St")
    response = api.cancel_search_order(order["id"], AGENT2)
    validate_error(response, ApiErrorId.ERR_NOT_ORDER_OWNER.value)
    assert get_order(order["id"])["status"] == "INTAKE"


def test_verifier_must_differ_from_research_submitter(api):
    """PRD 3.6: "Segregation of duties is enforced two ways: the verifier's
    identity must differ from `research_completed_by_user_id` and from the
    `completed_by_user_id` of every `COMPLETED` research task on the order,
    with a breach rejected as `ERR_SOD_VIOLATION`."

    Design: Corner/rbac/sod_verifier_must_not_be_researcher
    """
    # analyst_1 completes the task and submits; a QAReviewer calling under the
    # same operator id breaches segregation of duties.
    ctx = setup_in_verification(
        "P-AD8",
        departments=UTILITY_ONLY_DEPARTMENTS,
        with_association=False,
        findings_per_task=[FINDINGS_EMPTY],
    )
    qa_as_analyst = make_qa_reviewer_headers("analyst_1")
    response = api.verify_payoff(
        ctx["order"]["id"], {"verified_payoff_total_cents": 0}, qa_as_analyst
    )
    validate_error(response, ApiErrorId.ERR_SOD_VIOLATION.value)
    current = get_order(ctx["order"]["id"])
    assert current["status"] == "VERIFICATION"
    assert current.get("payoff_verified_by_user_id") is None


def test_resolver_must_differ_from_filer(api):
    """PRD 3.8: "Segregation of duties applies here as well: the resolver's
    identity must differ from `filed_by_user_id`, failing with
    `ERR_SOD_VIOLATION`."

    Design: Corner/rbac/sod_resolver_must_not_be_filer
    """
    ctx = setup_identified_order(
        "P-AE9", departments=UTILITY_ONLY_DEPARTMENTS, with_association=False
    )
    task = ctx["tasks"][0]
    discrepancy = file_discrepancy(
        ctx["order"]["id"], "RESEARCH_TASK", task["id"],
        "BALANCE_MISMATCH", 5000, "balance off",
    )
    start_review(discrepancy["id"])

    qa_as_filer = make_qa_reviewer_headers("agent_1")
    response = api.resolve_discrepancy(
        discrepancy["id"], {"resolution_outcome": "REJECTED_INVALID"}, qa_as_filer
    )
    validate_error(response, ApiErrorId.ERR_SOD_VIOLATION.value)
    assert get_discrepancy(discrepancy["id"])["status"] == "UNDER_REVIEW"
