"""Role-based access control, ownership, and segregation of duties."""
from test_helpers import (
    validate_error,
    TEST_USERS, make_field_adjuster_headers, make_qa_reviewer_headers,
    create_claim_payload, create_fee_schedule_payload,
)
from test_helpers import fixtures as fx

DESK = TEST_USERS["desk_examiner_headers"]


def test_field_adjuster_create_claim_denied(api):
    """PRD 2.1: "If the headers are well-formed but the named role is not permitted to
    perform the requested operation, the request is rejected with
    ERR_INSUFFICIENT_PERMISSIONS (HTTP 403)." POST /claims is authorized for
    DeskExaminer only (PRD 4).

    Design: Corner/rbac/field_adjuster_create_claim_denied
    """
    adj = fx.create_adjuster(api, adjuster_type="CAT")
    resp = api.create_claim(create_claim_payload(), make_field_adjuster_headers(adj["id"]))
    validate_error(resp, "ERR_INSUFFICIENT_PERMISSIONS")


def test_desk_examiner_create_fee_schedule_denied(api):
    """PRD 2.1: "If the headers are well-formed but the named role is not permitted to
    perform the requested operation, the request is rejected with
    ERR_INSUFFICIENT_PERMISSIONS (HTTP 403)." POST /fee-schedules is authorized for
    BillingManager only (PRD 4).

    Design: Corner/rbac/desk_examiner_create_fee_schedule_denied
    """
    resp = api.create_fee_schedule(create_fee_schedule_payload(), DESK)
    validate_error(resp, "ERR_INSUFFICIENT_PERMISSIONS")


def test_accept_assignment_by_non_owner_returns_not_owner(api):
    """PRD 2.9: "acting on an assignment-scoped resource requires that X-User-ID match
    the adjuster_id of the governing Assignment. This applies to a FieldAdjuster
    accepting or declining an assignment ... A mismatch yields ERR_NOT_ASSIGNMENT_OWNER
    (HTTP 403)."

    Design: Corner/validations/accept_assignment_by_non_owner_returns_not_owner
    """
    adj_a = fx.create_adjuster(api)
    fx.create_active_license(api, adj_a["id"], state_code="FL")
    adj_b = fx.create_adjuster(api)
    claim = fx.create_claim(api, loss_state="FL")
    asg = fx.create_assignment(api, claim["id"], adj_a["id"])
    # Adjuster B (not the assignee) tries to accept.
    resp = api.accept_assignment(asg["id"], make_field_adjuster_headers(adj_b["id"]))
    validate_error(resp, "ERR_NOT_ASSIGNMENT_OWNER")


def test_sod_self_review_returns_segregation(api):
    """PRD 2.9: "When a QAReviewer renders a decision on a report, the acting
    reviewer's X-User-ID must not equal the authoring adjuster ... A reviewer
    attempting to QA their own work is rejected with ERR_SEGREGATION_OF_DUTIES
    (HTTP 403)."

    Design: Corner/validations/sod_self_review_returns_segregation
    """
    ctx = fx.setup_work_complete_assignment(api, rcv_line_cents=50_000, depreciation_pct=10,
                                            photo_count=3, with_fee_schedule=False)
    # The authoring adjuster acts as QAReviewer on their own report.
    resp = api.qa_decision_report(ctx["rpt_id"], {"decision": "APPROVED"},
                                  make_qa_reviewer_headers(ctx["adj_id"]))
    validate_error(resp, "ERR_SEGREGATION_OF_DUTIES")
    report = api.get_report(ctx["rpt_id"], DESK).json()["data"]
    assert report["status"] == "SUBMITTED", "report must be unchanged after a rejected QA decision"
