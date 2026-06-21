"""Role-based access control, authentication, and FK-reverse listing
(PRD §2.1, §4 endpoint authorization, §2.3).
"""
from test_helpers import (
    validate_success,
    validate_error,
    validate_paginated,
    ApiErrorId,
    NON_EXISTENT_UUID,
    TEST_USERS,
    make_licensee_headers,
    create_work_payload,
    create_sync_license_payload,
    create_recording_payload,
    create_rightsholder,
    create_registered_work,
    create_locked_recording,
    setup_sync_catalog,
    next_isrc,
)

ADMIN = TEST_USERS["administrator_headers"]
OPERATOR = TEST_USERS["operator_headers"]


# =============================================================================
# Corner queue B — rbac
# =============================================================================

class TestRbac:
    def test_licensee_cannot_create_sync_license(self, api):
        """PRD §2.1: "A RoyaltyOperator runs the royalty machinery: ingesting and
        allocating usage, quoting and executing sync licenses, opening, finalizing, and
        reopening statements, and creating, settling, and reversing payouts."
        PRD §2.1: "When the headers are present but the declared role is not permitted to
        perform the requested operation, the request is rejected with ERR_UNAUTHORIZED."

        Design: Corner/rbac/licensee_cannot_create_sync_license
        """
        holder = create_rightsholder(legal_name="LblRbac", party_type="LABEL")
        work = create_registered_work(holder["id"], pro_affiliation="NONE",
                                       duration_seconds=200, role="PUBLISHER")
        rec = create_locked_recording(work["id"], holder["id"], release_type="PHYSICAL",
                                       duration_seconds=200)
        licensee_headers = make_licensee_headers(holder["id"])
        resp = api.create_sync_license(
            create_sync_license_payload(recording_id=rec["id"], licensee_id=holder["id"],
                                        media_type="FILM", territory="US", term_months=12,
                                        base_fee_cents=100000), licensee_headers)
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED)

    def test_operator_cannot_create_works(self, api):
        """PRD §2.1: "An Administrator manages the catalog and the parties: creating
        rightsholders and suspending them, registering works and locking their
        composition shares ..."
        PRD §2.1: "When the headers are present but the declared role is not permitted to
        perform the requested operation, the request is rejected with ERR_UNAUTHORIZED."

        Design: Corner/rbac/operator_cannot_create_works
        """
        resp = api.create_work(create_work_payload(pro_affiliation="ASCAP"), OPERATOR)
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED)

    def test_licensee_cannot_counter_other_owners_license(self, api):
        """PRD §2.1: "When X-User-Role is Licensee, X-User-ID is the id of the acting
        Rightsholder ...; ownership checks on any sync license compare that license's
        licensee_id field to X-User-ID."
        PRD §2.1: "When an entity-backed actor targets a resource they do not own, the
        request is rejected with ERR_NOT_RESOURCE_OWNER."

        Design: Corner/rbac/licensee_cannot_counter_other_owners_license
        """
        ctx = setup_sync_catalog()
        # Owner is ctx['licensee']; a different licensee B attempts the counter.
        other_licensee = create_rightsholder(legal_name="LicB", party_type="LABEL")
        sl = validate_success(api.create_sync_license(
            create_sync_license_payload(recording_id=ctx["recording"]["id"],
                                        licensee_id=ctx["licensee"]["id"], media_type="FILM",
                                        territory="US", term_months=12, base_fee_cents=100000),
            OPERATOR), expected_status=201)
        resp = api.counter_sync_license(sl["id"], {"counter_fee_cents": 90000},
                                        make_licensee_headers(other_licensee["id"]))
        validate_error(resp, ApiErrorId.ERR_NOT_RESOURCE_OWNER)

    def test_unauthenticated_request_rejected(self, api):
        """PRD §2.1: "If either header is missing or malformed, the request is rejected
        with ERR_UNAUTHENTICATED."

        Design: Corner/rbac/unauthenticated_request_rejected
        """
        resp = api.get_rightsholder(NON_EXISTENT_UUID, {})
        validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED)


# =============================================================================
# Corner queue B — endpoints (FK reverse-reachability listing)
# =============================================================================

class TestFkReverseListing:
    def test_list_recordings_filtered_by_work_id(self, api):
        """PRD §4: "GET /recordings — List recordings; filter by work_id"
        PRD §2.3: "List responses carry the pagination fields limit, offset, total_count,
        and has_more inside the meta object of the envelope."

        Design: Corner/endpoints/fk_reverse_recordings_by_work
        """
        holder = create_rightsholder(legal_name="LblFk", party_type="LABEL")
        work = create_registered_work(holder["id"], pro_affiliation="NONE",
                                       duration_seconds=200, role="PUBLISHER")
        validate_success(api.create_recording(
            create_recording_payload(work_id=work["id"], release_type="PHYSICAL",
                                    duration_seconds=200, isrc=next_isrc()), ADMIN), expected_status=201)
        validate_success(api.create_recording(
            create_recording_payload(work_id=work["id"], release_type="STREAMING",
                                    duration_seconds=210, isrc=next_isrc()), ADMIN), expected_status=201)
        data, meta = validate_paginated(api.list_recordings(ADMIN, params={"work_id": work["id"]}))
        assert meta["total_count"] == 2
        assert all(r["work_id"] == work["id"] for r in data), "every element matches the work_id filter"
