"""Role authorization, ownership, and authentication-context claims
(PRD §2.1, §2.9)."""
from test_helpers import (
    ALT_STUDENT,
    NO_AUTH_HEADERS,
    ApiErrorId,
    create_authorization,
    create_student,
    create_violation,
    make_student_headers,
    setup_active_student,
    submit_document,
    terminate_record,
    transition_authorization,
    transition_violation,
    validate_error,
)


def test_request_missing_auth_headers_returns_400(api):
    """PRD §2.1: "Every request must carry two HTTP headers: `X-User-ID`
    identifying the acting user and `X-User-Role` naming their operational
    capacity. A request missing either header, or carrying a malformed value,
    is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400)."

    Design: Corner/rbac/request_missing_auth_headers_returns_400
    """
    resp = api.get_student("00000000-0000-0000-0000-000000000000", NO_AUTH_HEADERS)
    validate_error(resp, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER, 400)


def test_student_cannot_review_documents_returns_403(api, dso_headers):
    """PRD §3.1: "Review is a DSO function: the reviewer supplies a `decision`
    of `VERIFIED` or `REJECTED` and may attach an optional `note` recorded as
    `review_note`."
    PRD §2.1: "A request whose role is not permitted on the target endpoint or
    action — for example a `Student` invoking a DSO-only action, or a `DSO`
    invoking record termination or `RESOLVE` — is rejected with
    `ERR_INSUFFICIENT_PERMISSIONS` (HTTP 403)."

    Design: Corner/rbac/student_cannot_review_documents_returns_403
    """
    student = create_student()
    doc = submit_document(student["id"], amount_usd_cents=500000)
    # Even the owning student may not review: review is a DSO-only action.
    resp = api.review_financial_document(
        doc["id"], {"decision": "VERIFIED"}, make_student_headers(student["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS, 403)


def test_dso_cannot_terminate_record_returns_403(api, dso_headers):
    """PRD §3.9: "Termination of an `ACTIVE` SEVIS record is a `PDSO`-exclusive
    action carrying a `termination_reason`. Attempting it on a record not in
    `ACTIVE` is rejected with `ERR_RECORD_NOT_ACTIVE`; attempting it as a `DSO`
    is rejected with `ERR_INSUFFICIENT_PERMISSIONS`."

    Design: Corner/rbac/dso_cannot_terminate_record_returns_403
    """
    ctx = setup_active_student()
    resp = api.terminate_sevis_record(
        ctx["record"]["id"], {"termination_reason": "Unauthorized employment"},
        dso_headers,
    )
    validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS, 403)


def test_dso_cannot_resolve_violation_returns_403(api, dso_headers, pdso_headers):
    """PRD §3.9: "Note the asymmetry of authority: recommending reinstatement
    and dismissing a violation sit with the general DSO body, but the final
    resolution of a reinstatement belongs to the principal official alone."
    PRD §2.1: "A request whose role is not permitted on the target endpoint or
    action — for example a `Student` invoking a DSO-only action, or a `DSO`
    invoking record termination or `RESOLVE` — is rejected with
    `ERR_INSUFFICIENT_PERMISSIONS` (HTTP 403)."

    Design: Corner/rbac/dso_cannot_resolve_violation_returns_403
    """
    ctx = setup_active_student()
    student_id = ctx["student"]["id"]
    terminate_record(ctx["record"]["id"], "Unauthorized employment")
    violation = create_violation(student_id)
    transition_violation(violation["id"], "RECOMMEND_REINSTATEMENT")  # DSO may recommend

    resp = api.transition_status_violation(
        violation["id"], {"action": "RESOLVE", "outcome": "REINSTATED"}, dso_headers,
    )
    validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS, 403)


def test_student_file_on_other_student_auth_returns_403(api, dso_headers):
    """PRD §2.1: "When `X-User-Role` is `Student`, `X-User-ID` is the `id` of
    the acting `Student` resource; ownership checks on any resource that
    references a student compare the resource's `student_id` foreign key to
    `X-User-ID`, and a mismatch is rejected with `ERR_RESOURCE_NOT_OWNED`
    (HTTP 403)."
    PRD §3.5: "**FILE** (the student, and only on their own authorization —
    otherwise `ERR_RESOURCE_NOT_OWNED`) moves `RECOMMENDED` to `FILED` and
    records the `uscis_receipt_number`."

    Design: Corner/rbac/student_file_on_other_student_auth_returns_403
    """
    ctx = setup_active_student()
    auth = create_authorization(
        ctx["student"]["id"], auth_type="OPT_PRE", hours_per_week=20,
        start_date="2027-01-11", end_date="2027-05-31",
    )
    transition_authorization(auth["id"], "RECOMMEND")
    other = create_student(**ALT_STUDENT)

    resp = api.transition_employment_authorization(
        auth["id"],
        {"action": "FILE", "uscis_receipt_number": "IOE1234567890"},
        make_student_headers(other["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_RESOURCE_NOT_OWNED, 403)
