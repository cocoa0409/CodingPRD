"""Auth context, validation ordering, RBAC exclusive denials, and segregation of duties."""
from test_helpers import (
    validate_success, validate_error, ApiErrorId, NON_EXISTENT_UUID,
    create_asset, create_cataloged_asset, create_archived_asset, create_rights_grant,
    create_ready_proxy, create_legal_hold, create_retention_policy,
    create_disposal_order, create_staff_member, create_under_review_request,
    create_ingest_batch_payload,
    make_archivist_lead_headers, make_metadata_cataloger_headers,
    make_metadata_librarian_headers, make_legal_counsel_headers,
    make_access_officer_headers, make_requester_headers,
    TEST_USERS,
)

ADMIN = TEST_USERS["system_admin_headers"]
ARCHIVIST = TEST_USERS["archivist_lead_headers"]


def test_missing_user_context_header_rejected(api):
    """PRD §2.1: "Every request must carry two headers: `X-User-ID`, identifying the
    acting user, and `X-User-Role`, naming the role under which that user acts. A
    request where either header is missing or empty is rejected with
    `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400)."

    Design: Corner/validations/missing_user_context_header_returns_400
    """
    res = api.create_ingest_batch(
        create_ingest_batch_payload(batch_name="B1", source_department="NEWS"),
        headers={"Content-Type": "application/json"})
    validate_error(res, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER)


def test_existence_beats_state_on_approve(api):
    """PRD §2.6: "When several checks could reject the same request, the server
    evaluates them in a fixed order and returns the first failure encountered."
    (existence is step 3; state preconditions are step 4.)
    PRD §2.6: "the first unknown id yields that resource's not-found error (HTTP 404):
    `ERR_STAFF_MEMBER_NOT_FOUND`, `ERR_BATCH_NOT_FOUND`, `ERR_ASSET_NOT_FOUND`,
    `ERR_PROXY_NOT_FOUND`, `ERR_GRANT_NOT_FOUND`, `ERR_HOLD_NOT_FOUND`,
    `ERR_ORDER_NOT_FOUND`".

    Design: Corner/validations/existence_beats_state_on_approve
    """
    res = api.approve_disposal_order(
        NON_EXISTENT_UUID, make_archivist_lead_headers("arch-2"))
    validate_error(res, ApiErrorId.ERR_ORDER_NOT_FOUND)


def test_cataloger_cannot_approve_metadata(api):
    """PRD §2.1: "A request whose role is not permitted to perform the operation is
    rejected with `ERR_INSUFFICIENT_PERMISSIONS` (HTTP 403)."
    PRD §4: POST /archive/assets/{id}/metadata-approve is authorized for
    MetadataLibrarian.

    Design: Corner/rbac/cataloger_cannot_approve_metadata_forbidden
    """
    asset = create_asset()
    validate_success(api.submit_metadata(
        asset["id"], make_metadata_cataloger_headers("cat-1")), 200)
    res = api.metadata_approve(asset["id"], make_metadata_cataloger_headers("cat-9"))
    validate_error(res, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS)


def test_storage_cost_read_role_gate(api):
    """PRD §2.1: "A request whose role is not permitted to perform the operation is
    rejected with `ERR_INSUFFICIENT_PERMISSIONS` (HTTP 403)."
    PRD §4: GET /archive/assets/{id}/storage-cost is authorized for SystemAdmin,
    ArchivistLead, FinanceOfficer only.

    Design: Corner/rbac/storage_cost_read_role_gate
    """
    staff = create_staff_member()
    asset = create_asset()
    res = api.get_storage_cost(asset["id"], make_requester_headers(staff["id"]))
    validate_error(res, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS)


def test_sod_all_four_gates_rejected(api):
    """PRD §2.8: "Metadata approval must come from a `MetadataLibrarian` whose
    `X-User-ID` differs from the asset's `metadata_submitted_by_user_id`
    (`ERR_SOD_METADATA_SELF_APPROVE`). Disposal approval must come from an
    `ArchivistLead` whose `X-User-ID` differs from the order's `created_by_user_id`
    (`ERR_SOD_DISPOSAL_SELF_APPROVE`). Retrieval approval must come from an
    `AccessOfficer` whose `X-User-ID` differs from the request's `requester_id`
    (`ERR_SOD_RETRIEVAL_SELF_APPROVE`). Releasing a legal hold must come from a
    `LegalCounsel` whose `X-User-ID` differs from the hold's `placed_by_user_id`
    (`ERR_SOD_HOLD_SELF_RELEASE`)."

    Design: Corner/validations/sod_all_four_gates_rejected
    """
    create_retention_policy("VIDEO", 0)
    staff = create_staff_member()
    batch = validate_success(
        api.create_ingest_batch(create_ingest_batch_payload(), TEST_USERS["ingest_coordinator_headers"]),
        201)

    # Gate 1: metadata self-approve
    a1 = create_asset(batch["id"], title="A")
    validate_success(api.submit_metadata(
        a1["id"], make_metadata_cataloger_headers("shared-u")), 200)
    e1 = api.metadata_approve(a1["id"], make_metadata_librarian_headers("shared-u"))
    validate_error(e1, ApiErrorId.ERR_SOD_METADATA_SELF_APPROVE)

    # Gate 2: disposal self-approve (order PENDING_APPROVAL created by shared-u)
    a2 = create_archived_asset(archivist="shared-u", title="B")
    order = create_disposal_order(a2["id"], expected_asset_version=a2["version"],
                                  user_id="shared-u")
    validate_success(api.submit_disposal_order(
        order["id"], make_archivist_lead_headers("shared-u")), 200)
    e2 = api.approve_disposal_order(order["id"], make_archivist_lead_headers("shared-u"))
    validate_error(e2, ApiErrorId.ERR_SOD_DISPOSAL_SELF_APPROVE)

    # Gate 3: retrieval self-approve (approver X-User-ID == requester_id)
    request = create_under_review_request(a2["id"], staff["id"])
    e3 = api.approve_retrieval_request(
        request["id"], make_access_officer_headers(staff["id"]))
    validate_error(e3, ApiErrorId.ERR_SOD_RETRIEVAL_SELF_APPROVE)

    # Gate 4: hold self-release (on a third asset so the other gates stay reachable)
    a3 = create_asset(batch["id"], title="C")
    hold = create_legal_hold(a3["id"], user_id="lc-9")
    e4 = api.release_legal_hold(hold["id"], make_legal_counsel_headers("lc-9"))
    validate_error(e4, ApiErrorId.ERR_SOD_HOLD_SELF_RELEASE)
