"""Role-based access control, authentication, and cross-entity constraint
violations (PRD §2.1, §3.5, §3.7)."""
from test_helpers import (
    validate_success, validate_error, build_user_headers,
    set_logical_clock, make_client, make_engineer,
    setup_project_in_revision, setup_project_approved, setup_ready_deliverable,
    setup_booked_project, create_engineer_payload, create_source_asset_payload,
    make_client_headers, make_engineer_headers, TEST_USERS, ApiErrorId,
)

MANAGER = TEST_USERS["manager_headers"]
QA = TEST_USERS["qa_headers"]


class TestRbac:

    def test_client_cannot_create_engineer(self, api):
        """PRD §2.1: "A request whose role is not permitted on the target endpoint is
        rejected with `ERR_UNAUTHORIZED` (HTTP 403)." PRD §4: the `POST
        /studio/engineers` row lists only StudioManager under "Authorized Role(s)".

        Design: Corner/rbac/client_cannot_create_engineer
        """
        set_logical_clock()
        client = make_client()
        res = api.create_engineer(
            create_engineer_payload(display_name="X", tier="STAFF",
                                    hourly_rate_cents=50000,
                                    capacity_minutes_per_day=240),
            make_client_headers(client["id"]))
        validate_error(res, ApiErrorId.ERR_UNAUTHORIZED, expected_status=403)

    def test_engineer_cannot_approve_revision(self, api):
        """PRD §2.1: "A request whose role is not permitted on the target endpoint is
        rejected with `ERR_UNAUTHORIZED` (HTTP 403)." PRD §3.6: "The client then
        adjudicates each submitted round." PRD §4: the `POST
        /studio/projects/{id}/rounds/{rid}/approve` row lists only Client under
        "Authorized Role(s)".

        Segregation of duties: the engineer who built the work cannot approve it.

        Design: Corner/rbac/engineer_cannot_approve_revision
        """
        ctx = setup_project_in_revision()
        res = api.approve_round(
            ctx["project"]["id"], ctx["round1"]["id"],
            make_engineer_headers(ctx["engineer"]["id"]))
        validate_error(res, ApiErrorId.ERR_UNAUTHORIZED, expected_status=403)

    def test_role_outside_declared_list_rejected(self, api):
        """PRD §2.1: "Every request must carry two HTTP headers: `X-User-ID`,
        identifying the acting party, and `X-User-Role`, declaring one of four roles:
        `Client`, `Engineer`, `QAChecker`, and `StudioManager`. A request missing
        either header, presenting a malformed header, or declaring a role outside
        this list is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."

        Design: Corner/rbac/unauthenticated_request_missing_headers
        """
        set_logical_clock()
        res = api.list_clients(build_user_headers("test-rogue-1", "InvalidRole"))
        validate_error(res, ApiErrorId.ERR_UNAUTHENTICATED, expected_status=401)


class TestUniquenessAndReferentialConstraints:

    def test_duplicate_sha256_within_project_rejected(self, api):
        """PRD §3.5: "The checksum must be unique within the project: uploading
        content whose `sha256` is already present on the same project is rejected
        with `ERR_DUPLICATE_ASSET` (HTTP 409)."

        Design: Corner/validations/aggregate_validation_duplicate_sha256_within_project
        """
        ctx = setup_booked_project()
        eng_headers = make_engineer_headers(ctx["engineer"]["id"])
        project_id = ctx["project"]["id"]
        validate_success(api.begin_intake(project_id, eng_headers), 200)
        sha = "abcdef" * 10 + "abcd"  # 64 lowercase hex chars
        validate_success(api.upload_source_asset(
            project_id, create_source_asset_payload(filename="a.wav", sha256=sha),
            eng_headers), 201)
        res = api.upload_source_asset(
            project_id,
            create_source_asset_payload(filename="b.wav", sha256=sha,
                                        sample_rate_hz=48000, bit_depth=16,
                                        duration_seconds=30.0),
            eng_headers)
        validate_error(res, ApiErrorId.ERR_DUPLICATE_ASSET, expected_status=409)

    def test_metadata_upc_mismatch_rejected(self, api):
        """PRD §3.7: "Malformed codes are rejected with `ERR_INVALID_FORMAT` (HTTP
        400), and when the parent project carries a `upc`, the tag's `upc` must equal
        it exactly, failing with `ERR_METADATA_MISMATCH` (HTTP 422) otherwise."

        The project carries UPC 012345678901; embedding a tag with a well-formed but
        different UPC 999999999999 is rejected.

        Design: Corner/validations/metadata_upc_mismatch_rejected
        """
        ctx = setup_project_approved()
        ctx = setup_ready_deliverable(ctx)
        res = api.embed_metadata(
            ctx["deliverable"]["id"],
            {"isrc": "USRC17607839", "upc": "999999999999"},
            make_engineer_headers(ctx["engineer"]["id"]))
        validate_error(res, ApiErrorId.ERR_METADATA_MISMATCH, expected_status=422)
