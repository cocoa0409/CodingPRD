"""Composite setup helpers for the CA-phase test suite.

Every fixture builds its preconditions from scratch via the public API; the
test harness restarts the server (empty database) before every test, so no
state is shared. Lenient get_success_data() is used internally so setup
failures surface as clear errors rather than assertion noise.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import (
    USER_OWNER,
    USER_CONTRACTOR,
    USER_ARCH_LEAD,
    USER_ARCH_2,
)
from .factories import (
    create_project_payload,
    create_submittal_payload,
    create_site_visit_payload,
    create_field_report_payload,
    create_rfi_payload,
    create_payment_application_payload,
    create_change_order_payload,
    create_punch_list_item_payload,
    create_record_document_payload,
    create_additional_service_invoice_payload,
    set_clock_payload,
)
from .test_users import (
    make_firm_admin_headers,
    make_architect_headers,
    make_contractor_headers,
    make_owner_headers,
)


# ---------------------------------------------------------------------------
# Tier 1: project creation / activation
# ---------------------------------------------------------------------------

def create_project(**overrides):
    """Create a project (status SETUP). Returns the project dict."""
    resp = api_client.create_project(create_project_payload(**overrides), make_firm_admin_headers())
    return get_success_data(resp)


def create_active_project(**overrides):
    """Create + activate a project. Returns the activated project dict."""
    project = create_project(**overrides)
    resp = api_client.activate_project(project["id"], make_firm_admin_headers())
    return get_success_data(resp)


def set_clock(to_iso8601: str):
    """Move the server logical clock. Returns the clock payload."""
    resp = api_client.set_clock(set_clock_payload(to_iso8601), make_firm_admin_headers())
    return get_success_data(resp)


# ---------------------------------------------------------------------------
# Tier 2: visit + field-report hierarchy
# ---------------------------------------------------------------------------

def create_performed_visit(project_id, visit_date="2026-08-20",
                           purpose="PAYMENT_VERIFICATION",
                           performed_by_user_id=USER_ARCH_2):
    """Schedule + perform a visit. Returns the visit dict (status PERFORMED)."""
    resp = api_client.create_site_visit(
        create_site_visit_payload(
            project_id, visit_date=visit_date, purpose=purpose,
            performed_by_user_id=performed_by_user_id,
        ),
        make_architect_headers(),
    )
    visit = get_success_data(resp)
    resp = api_client.perform_site_visit(visit["id"], make_architect_headers())
    return get_success_data(resp)


def issue_field_report(visit_id, issued_by_user_id=USER_ARCH_LEAD,
                       conformance_summary="CONFORMING",
                       nonconforming_work_flag=False, **overrides):
    """Issue the field report for a performed visit; flips visit to REPORT_ISSUED."""
    resp = api_client.create_field_report(
        create_field_report_payload(
            visit_id,
            issued_by_user_id=issued_by_user_id,
            conformance_summary=conformance_summary,
            nonconforming_work_flag=nonconforming_work_flag,
            **overrides,
        ),
        make_architect_headers(),
    )
    return get_success_data(resp)


def create_report_issued_visit(project_id, visit_date="2026-08-20",
                               purpose="PAYMENT_VERIFICATION",
                               performed_by_user_id=USER_ARCH_2,
                               issued_by_user_id=USER_ARCH_LEAD,
                               conformance_summary="CONFORMING",
                               nonconforming_work_flag=False):
    """Schedule + perform + report a visit. Returns (visit, report)."""
    visit = create_performed_visit(
        project_id, visit_date=visit_date, purpose=purpose,
        performed_by_user_id=performed_by_user_id,
    )
    report = issue_field_report(
        visit["id"], issued_by_user_id=issued_by_user_id,
        conformance_summary=conformance_summary,
        nonconforming_work_flag=nonconforming_work_flag,
    )
    visit = get_success_data(api_client.get_site_visit(visit["id"], make_architect_headers()))
    return visit, report


# ---------------------------------------------------------------------------
# Tier 2: submittal / RFI helpers
# ---------------------------------------------------------------------------

def create_submittal(project_id, **overrides):
    """Create a submittal as the project's contractor. Returns the submittal."""
    project = get_success_data(api_client.get_project(project_id, make_firm_admin_headers()))
    resp = api_client.create_submittal(
        create_submittal_payload(project_id, **overrides),
        make_contractor_headers(project["contractor_user_id"]),
    )
    return get_success_data(resp)


def create_rfi(project_id, **overrides):
    """Create an RFI as the project's contractor. Returns the RFI."""
    project = get_success_data(api_client.get_project(project_id, make_firm_admin_headers()))
    resp = api_client.create_rfi(
        create_rfi_payload(project_id, **overrides),
        make_contractor_headers(project["contractor_user_id"]),
    )
    return get_success_data(resp)


def review_submittal(submittal_id, outcome, reviewer=USER_ARCH_LEAD, **overrides):
    resp = api_client.review_submittal(
        submittal_id, {"outcome": outcome, **overrides}, make_architect_headers(reviewer),
    )
    return get_success_data(resp)


def answer_rfi(rfi_id, answer_text="Per specification", requires_clarification_drawing=False,
               answerer=USER_ARCH_LEAD):
    resp = api_client.answer_rfi(
        rfi_id,
        {"answer_text": answer_text, "requires_clarification_drawing": requires_clarification_drawing},
        make_architect_headers(answerer),
    )
    return get_success_data(resp)


# ---------------------------------------------------------------------------
# Tier 3: payment-application lifecycle
# ---------------------------------------------------------------------------

def create_payment_application(project_id, verification_visit_id,
                               period_ending_date="2026-08-31",
                               lines=None):
    """Create a payment application as the project's contractor."""
    project = get_success_data(api_client.get_project(project_id, make_firm_admin_headers()))
    payload = create_payment_application_payload(
        project_id, verification_visit_id, period_ending_date=period_ending_date,
    )
    if lines is not None:
        payload["lines"] = lines
    resp = api_client.create_payment_application(
        payload, make_contractor_headers(project["contractor_user_id"]),
    )
    return get_success_data(resp)


def certify_payment_application(application_id, certifier=USER_ARCH_LEAD):
    resp = api_client.certify_payment_application(
        application_id, make_architect_headers(certifier),
    )
    return get_success_data(resp)


def setup_project_with_certified_application(
        work_cents=1000000, sov_lines=None, contract_sum=10000000,
        retainage_mode="TIERED_MARGINAL", visit_date="2026-08-20",
        period_ending_date="2026-08-31", stored_materials_cents=0,
        **project_overrides):
    """ACTIVE project + REPORT_ISSUED verification visit + CERTIFIED application.

    Returns (project, visit, report, application).
    """
    if sov_lines is None:
        sov_lines = [{"line_code": "A", "description": "Concrete",
                      "scheduled_value_cents": contract_sum}]
    project = create_active_project(
        original_contract_sum_cents=contract_sum, sov_lines=sov_lines,
        retainage_mode=retainage_mode, **project_overrides,
    )
    set_clock(f"{visit_date}T09:00:00Z")
    visit, report = create_report_issued_visit(project["id"], visit_date=visit_date)
    line_code = sov_lines[0]["line_code"]
    application = create_payment_application(
        project["id"], visit["id"], period_ending_date=period_ending_date,
        lines=[{"sov_line_code": line_code,
                "work_completed_this_period_cents": work_cents,
                "stored_materials_cents": stored_materials_cents}],
    )
    application = certify_payment_application(application["id"])
    project = get_success_data(api_client.get_project(project["id"], make_firm_admin_headers()))
    return project, visit, report, application


# ---------------------------------------------------------------------------
# Tier 3: change-order lifecycle
# ---------------------------------------------------------------------------

def create_change_order(project_id, **overrides):
    """Create a change order as the project's contractor."""
    project = get_success_data(api_client.get_project(project_id, make_firm_admin_headers()))
    resp = api_client.create_change_order(
        create_change_order_payload(project_id, **overrides),
        make_contractor_headers(project["contractor_user_id"]),
    )
    return get_success_data(resp)


def recommend_change_order(change_order_id, recommendation="ACCEPT",
                           reviewer=USER_ARCH_LEAD):
    resp = api_client.recommend_change_order(
        change_order_id, {"recommendation": recommendation},
        make_architect_headers(reviewer),
    )
    return get_success_data(resp)


def decide_change_order(change_order_id, decision, project):
    resp = api_client.decide_change_order(
        change_order_id, {"decision": decision},
        make_owner_headers(project["owner_user_id"]),
    )
    return get_success_data(resp)


def incorporate_change_order(change_order_id, project):
    """Incorporate an OWNER_ACCEPTED change order with the live project version."""
    project = get_success_data(api_client.get_project(project["id"], make_firm_admin_headers()))
    resp = api_client.incorporate_change_order(
        change_order_id, {"expected_project_version": project["version"]},
        make_owner_headers(project["owner_user_id"]),
    )
    return get_success_data(resp)


def create_owner_accepted_change_order(project, **overrides):
    """Create -> recommend ACCEPT -> owner ACCEPT. Returns the change order."""
    change_order = create_change_order(project["id"], **overrides)
    recommend_change_order(change_order["id"], "ACCEPT")
    return decide_change_order(change_order["id"], "ACCEPT", project)


def create_incorporated_change_order(project, **overrides):
    """Full lifecycle through INCORPORATED. Returns (project, change_order)."""
    change_order = create_owner_accepted_change_order(project, **overrides)
    change_order = incorporate_change_order(change_order["id"], project)
    project = get_success_data(api_client.get_project(project["id"], make_firm_admin_headers()))
    return project, change_order


# ---------------------------------------------------------------------------
# Tier 3: punch list / record documents
# ---------------------------------------------------------------------------

def create_punch_list_item(project_id, raised_visit_id, **overrides):
    resp = api_client.create_punch_list_item(
        create_punch_list_item_payload(project_id, raised_visit_id, **overrides),
        make_architect_headers(),
    )
    return get_success_data(resp)


def create_accepted_record_document(project_id, doc_type):
    """Submit + ACCEPT a record document of the given type."""
    project = get_success_data(api_client.get_project(project_id, make_firm_admin_headers()))
    resp = api_client.create_record_document(
        create_record_document_payload(project_id, doc_type=doc_type),
        make_contractor_headers(project["contractor_user_id"]),
    )
    document = get_success_data(resp)
    resp = api_client.review_record_document(
        document["id"], {"outcome": "ACCEPT"}, make_architect_headers(),
    )
    return get_success_data(resp)


def accept_all_record_documents(project_id):
    """Accept one record document of each of the four types. Returns the list."""
    return [
        create_accepted_record_document(project_id, doc_type)
        for doc_type in ("AS_BUILT", "OM_MANUAL", "WARRANTY", "TEST_REPORT")
    ]


# ---------------------------------------------------------------------------
# Tier 5: project closeout / terminal states
# ---------------------------------------------------------------------------

def setup_substantial_completion_project(**project_overrides):
    """ACTIVE project with a REPORT_ISSUED PUNCH_INSPECTION visit, then
    achieve-substantial-completion. Returns (project, visit, report)."""
    project = create_active_project(**project_overrides)
    set_clock("2026-08-20T09:00:00Z")
    visit, report = create_report_issued_visit(
        project["id"], visit_date="2026-08-20", purpose="PUNCH_INSPECTION",
        conformance_summary="MINOR_DEVIATIONS",
    )
    resp = api_client.achieve_substantial_completion(project["id"], make_architect_headers())
    project = get_success_data(resp)
    return project, visit, report


def setup_final_completion_project(**project_overrides):
    """Project in FINAL_COMPLETION_ACHIEVED (punch visit reported, all four
    record document types accepted, no open punch items). Returns (project, visit)."""
    project, visit, _report = setup_substantial_completion_project(**project_overrides)
    accept_all_record_documents(project["id"])
    resp = api_client.achieve_final_completion(project["id"], make_architect_headers())
    project = get_success_data(resp)
    return project, visit


# ---------------------------------------------------------------------------
# Tier 4: extended-duration billing targeting
# ---------------------------------------------------------------------------

def setup_extended_duration_project(clock_date="2026-11-05T09:00:00Z",
                                    base_scd="2026-09-30", grace_days=5,
                                    billing_method="PER_DIEM_PRORATED",
                                    **project_overrides):
    """ACTIVE project whose clock sits past its billing horizon
    (adjusted date + delay + grace). Returns the project."""
    project = create_active_project(
        base_substantial_completion_date=base_scd, grace_days=grace_days,
        billing_method=billing_method, **project_overrides,
    )
    set_clock(clock_date)
    return get_success_data(api_client.get_project(project["id"], make_firm_admin_headers()))


def create_draft_invoice(project_id, period_start="2026-10-01", period_end="2026-10-31"):
    resp = api_client.create_additional_service_invoice(
        create_additional_service_invoice_payload(
            project_id, period_start=period_start, period_end=period_end,
        ),
        make_firm_admin_headers(),
    )
    return get_success_data(resp)
