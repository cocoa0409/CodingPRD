"""RBAC claims: role denials, ownership denials, segregation of duties, and
trainee supervision signature rules (PRD 2.1, 2.7, 3.6, and the PRD 4 role
table)."""
from test_helpers import (
    UNKNOWN_UUID,
    ApiErrorId,
    add_standard_locked_comps,
    assign_order,
    create_appraiser,
    create_client,
    create_membership,
    create_order,
    create_report,
    create_trainee,
    make_appraiser_headers,
    make_clientuser_headers,
    make_qc_reviewer_headers,
    scope_order,
    accept_order,
    set_clock,
    setup_order_in_analysis,
    start_analysis,
    submit_for_qc,
    qc_pass,
    validate_error,
    validate_success,
    TEST_USERS,
)
from test_helpers import ADMIN, COMPLIANCE

CLIENT_USER = TEST_USERS["client_user_headers"]
APPRAISER_FALLBACK = TEST_USERS["appraiser_headers"]
QC_REVIEWER_FALLBACK = TEST_USERS["qc_reviewer_headers"]


def test_clientuser_cannot_create_clients(api):
    """PRD 2.1: "A request whose role is not listed for the target endpoint is
    rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403)."
    PRD 4: "| POST | `/appraisal/clients` | Create a lender/AMC client |
    FirmAdmin |".

    Design: Corner/rbac/clientuser_cannot_create_clients
    """
    response = api.create_client(
        {
            "name": "C",
            "client_type": "AMC",
            "contact_email": "c@x.example",
            "default_turn_time_days": 7,
        },
        CLIENT_USER,
    )
    validate_error(response, ApiErrorId.ERR_FORBIDDEN_ROLE, 403)


def test_clientuser_cannot_read_foreign_order(api):
    """PRD 2.1: "When `X-User-Role` is `ClientUser`, `X-User-ID` is the `id`
    of the acting Client; ownership checks on any resource that belongs to a
    client compare the resource's `client_id` — or, for child resources such
    as orders, reports, and revision requests, the owning order's `client_id`
    — to `X-User-ID`."
    PRD 2.1: "the rejection is `ERR_NOT_RESOURCE_OWNER` (HTTP 403)."

    Design: Corner/rbac/clientuser_cannot_read_foreign_order
    """
    set_clock("2026-08-01T00:00:00Z")
    client_a = create_client(name="A")
    client_b = create_client(name="B")
    order = create_order(client_b["id"], property_address="9 B St")

    response = api.get_order(order["id"], make_clientuser_headers(client_a["id"]))
    validate_error(response, ApiErrorId.ERR_NOT_RESOURCE_OWNER, 403)


def test_clientuser_cannot_cancel_foreign_order(api):
    """PRD 3.9: "A `ClientUser` may cancel only their own client's orders —
    otherwise `ERR_NOT_RESOURCE_OWNER` — and only while the order is
    `RECEIVED` or `SCOPE_DETERMINED`, a later state again answering
    `ERR_INVALID_STATE`; a `FirmAdmin` faces no such narrowing."

    Design: Corner/rbac/clientuser_cannot_cancel_foreign_order
    """
    set_clock("2026-08-01T00:00:00Z")
    client_a = create_client(name="A")
    client_b = create_client(name="B")
    order = create_order(client_b["id"], property_address="9 B St")

    response = api.cancel_order(
        order["id"], {"reason": "not mine"}, make_clientuser_headers(client_a["id"])
    )
    validate_error(response, ApiErrorId.ERR_NOT_RESOURCE_OWNER, 403)


def test_appraiser_cannot_accept_order(api):
    """PRD 2.1: "A request whose role is not listed for the target endpoint is
    rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403)."
    PRD 4: "| POST | `/appraisal/orders/{id}/accept` | Accept the order,
    locking the final fee and due date | FirmAdmin |".

    Design: Corner/rbac/appraiser_cannot_accept_order
    """
    response = api.accept_order(UNKNOWN_UUID, {}, APPRAISER_FALLBACK)
    validate_error(response, ApiErrorId.ERR_FORBIDDEN_ROLE, 403)


def test_appraiser_cannot_qc_pass(api):
    """PRD 2.1: "A request whose role is not listed for the target endpoint is
    rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403)."
    PRD 4: "| POST | `/appraisal/reports/{id}/qc-pass` | Pass a report under
    review | QCReviewer |".

    Design: Corner/rbac/appraiser_cannot_qc_pass
    """
    response = api.qc_pass_report(UNKNOWN_UUID, APPRAISER_FALLBACK)
    validate_error(response, ApiErrorId.ERR_FORBIDDEN_ROLE, 403)


def test_qcreviewer_cannot_deliver_report(api):
    """PRD 2.1: "A request whose role is not listed for the target endpoint is
    rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403)."
    PRD 4: "| POST | `/appraisal/reports/{id}/deliver` | Deliver a passed
    report to the client | Appraiser |".

    Design: Corner/rbac/qcreviewer_cannot_deliver_report
    """
    response = api.deliver_report(UNKNOWN_UUID, QC_REVIEWER_FALLBACK)
    validate_error(response, ApiErrorId.ERR_FORBIDDEN_ROLE, 403)


def test_firmadmin_cannot_purge_workfile(api):
    """PRD 2.1: "A request whose role is not listed for the target endpoint is
    rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403)."
    PRD 4: "| POST | `/appraisal/workfile-records/{id}/purge` | Purge a
    workfile record past its retention date | ComplianceOfficer |".

    Design: Corner/rbac/firmadmin_cannot_purge_workfile
    """
    response = api.purge_workfile_record(UNKNOWN_UUID, ADMIN)
    validate_error(response, ApiErrorId.ERR_FORBIDDEN_ROLE, 403)


def test_clientuser_cannot_accept_revision(api):
    """PRD 2.1: "A request whose role is not listed for the target endpoint is
    rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403)."
    PRD 4: "| POST | `/appraisal/revision-requests/{id}/accept` | Accept an
    open request, charging the revision fee and reopening the order |
    FirmAdmin |".

    Design: Corner/rbac/clientuser_cannot_accept_revision
    """
    response = api.accept_revision_request(UNKNOWN_UUID, CLIENT_USER)
    validate_error(response, ApiErrorId.ERR_FORBIDDEN_ROLE, 403)


def test_firmadmin_cannot_start_analysis(api):
    """PRD 2.1: "A request whose role is not listed for the target endpoint is
    rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403)."
    PRD 4: "| POST | `/appraisal/orders/{id}/start-analysis` | Begin analysis
    on an inspected or desktop order | Appraiser |".

    Design: Corner/rbac/firmadmin_cannot_start_analysis
    """
    response = api.start_analysis(UNKNOWN_UUID, ADMIN)
    validate_error(response, ApiErrorId.ERR_FORBIDDEN_ROLE, 403)


def test_clientuser_cannot_set_clock(api):
    """PRD 2.1: "A request whose role is not listed for the target endpoint is
    rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403)."
    PRD 4: "| POST | `/_clock/set_current_utc` | Set the logical clock |
    FirmAdmin |".

    Design: Corner/rbac/clientuser_cannot_set_clock
    """
    response = api.set_clock({"to_iso8601": "2026-08-01T00:00:00Z"}, CLIENT_USER)
    validate_error(response, ApiErrorId.ERR_FORBIDDEN_ROLE, 403)


def test_appraiser_cannot_close_complaint(api):
    """PRD 2.1: "A request whose role is not listed for the target endpoint is
    rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403)."
    PRD 4: "| POST | `/appraisal/complaints/{id}/close` | Close a submitted
    complaint with an outcome | ComplianceOfficer |".

    Design: Corner/rbac/appraiser_cannot_close_complaint
    """
    response = api.close_complaint(
        UNKNOWN_UUID, {"outcome": "NO_ACTION"}, APPRAISER_FALLBACK
    )
    validate_error(response, ApiErrorId.ERR_FORBIDDEN_ROLE, 403)


def test_compliance_officer_cannot_determine_scope(api):
    """PRD 2.1: "A request whose role is not listed for the target endpoint is
    rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403)."
    PRD 4: "| POST | `/appraisal/orders/{id}/determine-scope` | Determine
    complexity tier, inspection need, and provisional fee | FirmAdmin |".

    Design: Corner/rbac/compliance_officer_cannot_determine_scope
    """
    response = api.determine_scope(UNKNOWN_UUID, {}, COMPLIANCE)
    validate_error(response, ApiErrorId.ERR_FORBIDDEN_ROLE, 403)


def test_qc_reviewer_sod_cannot_review_own_signature(api):
    """PRD 3.6: "Quality control is performed by a `QCReviewer`, and
    segregation of duties is enforced on both verdicts: the reviewer may not
    be the report's signing appraiser, nor its co-signer, with violations
    failing as `ERR_SOD_REVIEWER_CONFLICT`."

    Design: Corner/rbac/qc_reviewer_sod_cannot_review_own_signature
    """
    ctx = setup_order_in_analysis()
    add_standard_locked_comps(ctx)
    report = create_report(ctx["order"]["id"], ctx["appraiser"]["id"])
    submit_for_qc(report["id"], ctx["appraiser"]["id"])

    # reviewer identity == signing appraiser identity
    response = api.qc_pass_report(
        report["id"], make_qc_reviewer_headers(ctx["appraiser"]["id"])
    )
    validate_error(response, ApiErrorId.ERR_SOD_REVIEWER_CONFLICT, 422)


def test_trainee_delivery_supervision_rules(api):
    """PRD 3.4: "A successful assignment records `assigned_appraiser_id` on
    the order and sets `requires_supervisor_cosign` to true exactly when the
    assignee is a `TRAINEE`."
    PRD 3.6: "When the order's `requires_supervisor_cosign` is set,
    `co_signer_appraiser_id` must be present (`ERR_SIGNATURE_COSIGN_REQUIRED`)."
    PRD 3.6: "The co-signer must be the assignee's declared supervisor,
    meaning the appraiser named by the assignee's own `supervisor_id`, and
    must personally be `ACTIVE` and `CERTIFIED_RESIDENTIAL`; a mismatch on any
    of those conditions is rejected with `ERR_SUPERVISOR_SIGNATURE_MISMATCH`."

    Design: Corner/rbac/trainee_delivery_supervision_rules
    """
    from test_helpers import create_fee_schedule

    set_clock("2026-08-01T00:00:00Z")
    client = create_client()
    create_fee_schedule(client["id"])
    supervisor = create_appraiser(
        full_name="Sara Supervisor", license_number="CR-1"
    )
    trainee = create_trainee(supervisor["id"], full_name="Tina Trainee")
    reviewer = create_appraiser(full_name="Quinn Reviewer", license_number="CR-2")
    create_membership(client["id"], trainee["id"])

    order = create_order(client["id"])
    scope_order(order["id"], requires_inspection=False)
    accept_order(order["id"])
    assigned = assign_order(order["id"], trainee["id"])
    assert assigned["requires_supervisor_cosign"] is True

    trainee_headers = make_appraiser_headers(trainee["id"])
    start_analysis(order["id"], trainee["id"])
    ctx = {"order": assigned, "appraiser": trainee}
    add_standard_locked_comps(ctx)
    report = create_report(order["id"], trainee["id"])
    assert report["signing_appraiser_id"] == trainee["id"]
    submit_for_qc(report["id"], trainee["id"])
    qc_pass(report["id"], reviewer["id"])

    # deliver without the supervisor co-signature
    blocked = api.deliver_report(report["id"], trainee_headers)
    validate_error(blocked, ApiErrorId.ERR_SIGNATURE_COSIGN_REQUIRED, 422)

    # co-sign by a certified appraiser who is not the declared supervisor
    mismatch = api.co_sign_report(report["id"], make_appraiser_headers(reviewer["id"]))
    validate_error(mismatch, ApiErrorId.ERR_SUPERVISOR_SIGNATURE_MISMATCH, 422)

    # co-sign by the declared supervisor, then deliver
    signed = validate_success(
        api.co_sign_report(report["id"], make_appraiser_headers(supervisor["id"])), 200
    )
    assert signed["co_signer_appraiser_id"] == supervisor["id"]

    delivered = validate_success(api.deliver_report(report["id"], trainee_headers), 200)
    assert delivered["status"] == "DELIVERED"
