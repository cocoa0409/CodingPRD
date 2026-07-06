"""Entity CRUD, defaults, computed/system fields, FK existence, endpoint CRUD,
and RBAC. Corner-design entities, endpoints, and roles sections.
"""
import pytest
from test_helpers import (
    api_client, validate_success, validate_error, validate_paginated,
    get_success_data, fixtures, TEST_USERS, ApiErrorId, build_user_headers,
    make_client_contact_headers,
)
from test_helpers.constants import MISSING_UUID

AM = TEST_USERS["account_manager_headers"]
GW = TEST_USERS["grant_writer_headers"]
CO = TEST_USERS["compliance_officer_headers"]


# ==========================================================================
# Corner — entities
# ==========================================================================
class TestEntityCreationAndReads:
    def test_client_creation_returns_201_with_defaults(self, api):
        """PRD §3.1: "A new client opens in `ACTIVE` status with its three computed
        counters — `proposals_submitted_count`, `proposals_won_count`, and
        `win_rate_pct` — initialized to zero, the win rate specifically to `0.0`."

        Design: Corner/entities/client_creation_returns_201_with_defaults
        """
        c = validate_success(api.create_client(
            {"org_name": "New Org", "ein": fixtures.unique_ein(),
             "mission_areas": ["EDUCATION"], "annual_budget_cents": 4000000,
             "contact_email": "n@x.org"}, AM), 201)
        assert c["status"] == "ACTIVE"
        assert c["proposals_submitted_count"] == 0
        assert c["proposals_won_count"] == 0
        assert c["win_rate_pct"] == 0.0

    def test_client_retrieval_returns_stored_entity(self, api):
        """PRD §3.1: "A client organization enters the system when an
        `AccountManager` registers it with its `org_name`, its `ein`, the
        `mission_areas` it funds work in (for example `EDUCATION` or `HEALTH`), its
        `annual_budget_cents`, and a primary `contact_email`."

        Design: Corner/entities/client_retrieval_returns_stored_entity
        """
        created = fixtures.create_client(org_name="Stored Org")
        got = validate_success(api.get_client(created["id"], AM), 200)
        assert got["org_name"] == "Stored Org", f"got {got['org_name']!r}"

    def test_opportunities_list_returns_paginated_envelope(self, api):
        """PRD §2.3: "The `meta` object of a list response carries the pagination
        fields `limit`, `offset`, `total_count`, and `has_more`."

        Design: Corner/entities/opportunities_list_returns_paginated_envelope
        """
        fixtures.create_opportunity(funder_name="F1", focus_areas=["EDUCATION"])
        fixtures.create_opportunity(funder_name="F2", focus_areas=["HEALTH"], portal_name="FOUNDANT")
        data, meta = validate_paginated(api.list_opportunities(AM))
        assert meta["total_count"] == 2, f"expected 2, got {meta['total_count']}"
        assert meta["has_more"] is False

    def test_client_not_found_returns_404(self, api):
        """PRD §2.5: "every resource named in the path and every foreign key
        referenced in the body is confirmed to exist, validated left to right
        (`ERR_NOT_FOUND`)."

        Design: Corner/entities/client_not_found_returns_404
        """
        validate_error(api.get_client(MISSING_UUID, AM), ApiErrorId.ERR_NOT_FOUND.value)

    def test_client_missing_required_org_name(self, api):
        """PRD §2.5: "on create and update endpoints, the body is checked for
        well-formedness — required fields present, quantities positive, enums valid,
        and the EIN and boilerplate `section_key` uniqueness rules satisfied
        (`ERR_INVALID_REQUEST`)."

        Design: Corner/entities/client_missing_required_org_name_returns_invalid_request
        """
        validate_error(api.create_client(
            {"ein": fixtures.unique_ein(), "mission_areas": ["EDUCATION"],
             "annual_budget_cents": 1000000, "contact_email": "m@x.org"}, AM),
            ApiErrorId.ERR_INVALID_REQUEST.value)

    def test_client_duplicate_ein_rejected(self, api):
        """PRD §3.1: "The `ein` must be unique across all clients that are not
        `ARCHIVED`; a collision is a malformed-body condition reported as
        `ERR_INVALID_REQUEST`."

        Design: Corner/entities/client_duplicate_ein_among_non_archived_returns_invalid_request
        """
        ein = fixtures.unique_ein()
        fixtures.create_client(org_name="First", ein=ein)
        validate_error(api.create_client(
            {"org_name": "Second", "ein": ein, "mission_areas": ["HEALTH"],
             "annual_budget_cents": 2000000, "contact_email": "b@x.org"}, AM),
            ApiErrorId.ERR_INVALID_REQUEST.value)

    def test_opportunity_floor_amount_default_zero(self, api):
        """PRD §3.1: "an optional `floor_amount_cents` (defaulting to zero) below
        which a request is too small."

        Design: Corner/entities/opportunity_floor_amount_default_zero_applied
        """
        opp = validate_success(api.create_opportunity(
            {"funder_name": "F", "title": "Default Floor", "focus_areas": ["EDUCATION"],
             "ceiling_amount_cents": 500000, "portal_name": "GRANTS_GOV",
             "deadline_utc": "2026-12-31T00:00:00Z"}, AM), 201)
        assert opp["floor_amount_cents"] == 0, f"expected 0, got {opp['floor_amount_cents']}"

    def test_proposal_budget_total_starts_zero(self, api):
        """PRD §3.4: "A new proposal opens in `DRAFTING` with its `revision_round`
        at zero and its computed `budget_total_cents` at zero."

        Design: Corner/entities/budget_total_computed_field_input_ignored
        """
        ctx = fixtures.setup_drafting_proposal()
        prop = ctx["proposal"]
        assert prop["budget_total_cents"] == 0, f"expected 0, got {prop['budget_total_cents']}"
        assert prop["status"] == "DRAFTING"
        assert prop["revision_round"] == 0

    def test_client_system_fields_generated_on_create(self, api):
        """PRD §2.4: "The `version` begins at its initial value when the resource is
        created and increments by one on each mutation of that resource."

        Design: Corner/entities/client_system_fields_generated_on_create
        """
        c = validate_success(api.create_client(
            {"org_name": "Sys Org", "ein": fixtures.unique_ein(),
             "mission_areas": ["EDUCATION"], "annual_budget_cents": 1000000,
             "contact_email": "sy@x.org"}, AM), 201)
        assert c["version"] == 1, f"expected version 1, got {c['version']}"
        assert c["status"] == "ACTIVE"

    def test_engagement_invalid_fee_model_enum_rejected(self, api):
        """PRD §2.5: "the body is checked for well-formedness — required fields
        present, quantities positive, enums valid, and the EIN and boilerplate
        `section_key` uniqueness rules satisfied (`ERR_INVALID_REQUEST`)."

        Design: Corner/entities/engagement_invalid_fee_model_enum_returns_invalid_request
        """
        client = fixtures.create_client()
        validate_error(api.create_engagement(
            {"client_id": client["id"], "fee_model": "BARTER"}, AM),
            ApiErrorId.ERR_INVALID_REQUEST.value)

    def test_proposal_create_wrong_engagement_fk_returns_not_found(self, api):
        """PRD §2.5: "every resource named in the path and every foreign key
        referenced in the body is confirmed to exist, validated left to right
        (`ERR_NOT_FOUND`)."

        Design: Corner/entities/proposal_create_wrong_engagement_fk_returns_not_found
        """
        client = fixtures.create_client()
        opp = fixtures.create_opportunity()
        match = fixtures.create_pursuing_match(client["id"], opp["id"], actor=GW)
        validate_error(api.create_proposal(
            {"engagement_id": MISSING_UUID, "match_id": match["id"],
             "requested_amount_cents": 100000}, GW),
            ApiErrorId.ERR_NOT_FOUND.value)


# ==========================================================================
# Corner — endpoints
# ==========================================================================
class TestEndpointActions:
    def test_deliverable_patch_body_without_changing_state(self, api):
        """PRD §3.4: "A grant writer may edit a deliverable's `body` text at any
        time without disturbing either dimension."

        Design: Corner/endpoints/deliverable_patch_body_updates_without_changing_state
        """
        ctx = fixtures.setup_drafting_proposal()
        deliv = get_success_data(api.create_deliverable(
            {"proposal_id": ctx["proposal"]["id"], "kind": "NARRATIVE",
             "title": "N", "body": "old"}, GW))
        out = validate_success(api.patch_deliverable(deliv["id"], {"body": "new body text"}, GW), 200)
        assert out["body"] == "new body text", f"got {out['body']!r}"
        assert out["content_status"] == "OUTLINE", f"got {out['content_status']}"
        assert out["approval_status"] == "UNREVIEWED", f"got {out['approval_status']}"

    def test_boilerplate_retire_frees_section_key(self, api):
        """PRD §3.4: "A snippet opens `ACTIVE` with its computed `usage_count` at
        zero, and may be retired, moving `ACTIVE` to `RETIRED`, which frees its
        `section_key` for reuse by a new active snippet."

        Design: Corner/endpoints/boilerplate_retire_frees_section_key_for_reuse
        """
        client = fixtures.create_client()
        snip1 = get_success_data(api.create_boilerplate(
            {"client_id": client["id"], "section_key": "ORG_HISTORY", "body": "v1"}, GW))
        get_success_data(api.retire_boilerplate(snip1["id"], GW))
        snip2 = validate_success(api.create_boilerplate(
            {"client_id": client["id"], "section_key": "ORG_HISTORY", "body": "v2"}, GW), 201)
        assert fixtures.get_boilerplate(snip1["id"])["status"] == "RETIRED"
        assert snip2["status"] == "ACTIVE", f"got {snip2['status']}"

    def test_engagements_filtered_by_client_id(self, api):
        """PRD §3.2: "Engagements may be listed and filtered by `client_id` and
        `status`."

        Design: Corner/endpoints/engagements_filtered_list_by_client_id_fk_reverse
        """
        ca = fixtures.create_client()
        cb = fixtures.create_client()
        ea = fixtures.create_engagement(ca["id"], fee_model="HOURLY", hourly_rate_cents=12000)
        fixtures.create_engagement(cb["id"], fee_model="HOURLY", hourly_rate_cents=12000)
        data, meta = validate_paginated(api.list_engagements(AM, params={"client_id": ca["id"]}))
        assert meta["total_count"] == 1, f"expected 1, got {meta['total_count']}"
        assert data[0]["id"] == ea["id"], f"expected {ea['id']}, got {data[0]['id']}"


# ==========================================================================
# Corner — RBAC (roles)
# ==========================================================================
class TestRBAC:
    def test_grantwriter_cannot_create_client(self, api):
        """PRD §2.1: "When the headers are present but the declared role is not
        permitted to perform the requested operation, the request is rejected with
        `ERR_FORBIDDEN_FOR_ROLE`."

        Design: Corner/roles/grantwriter_cannot_create_client_forbidden
        """
        validate_error(api.create_client(
            {"org_name": "X Org", "ein": fixtures.unique_ein(),
             "mission_areas": ["EDUCATION"], "annual_budget_cents": 1000000,
             "contact_email": "x@x.org"}, GW),
            ApiErrorId.ERR_FORBIDDEN_FOR_ROLE.value)

    def test_account_manager_cannot_create_proposal(self, api):
        """PRD §2.1: "When the headers are present but the declared role is not
        permitted to perform the requested operation, the request is rejected with
        `ERR_FORBIDDEN_FOR_ROLE`."

        Design: Corner/roles/account_manager_cannot_create_proposal_forbidden
        """
        client = fixtures.create_client()
        opp = fixtures.create_opportunity()
        match = fixtures.create_pursuing_match(client["id"], opp["id"], actor=AM)
        eng = fixtures.create_active_engagement(client["id"], fee_model="HOURLY",
                                                hourly_rate_cents=12000)
        validate_error(api.create_proposal(
            {"engagement_id": eng["id"], "match_id": match["id"],
             "requested_amount_cents": 100000}, AM),
            ApiErrorId.ERR_FORBIDDEN_FOR_ROLE.value)

    def test_client_contact_request_changes_on_other_clients_proposal_denied(self, api):
        """PRD §2.1: "a `ClientContact` may only request changes on a proposal,
        approve a proposal, approve a deliverable, or open a revision request when
        the resource ultimately rolls up to their own client; a mismatch is rejected
        with `ERR_NOT_RESOURCE_OWNER`."

        Design: Corner/roles/client_contact_request_changes_on_other_clients_proposal_denied
        """
        ctx = fixtures.setup_review_ready_proposal()
        get_success_data(api.submit_proposal_for_review(ctx["proposal"]["id"], GW))
        intruder = fixtures.create_client()  # a different client B
        cc_intruder = make_client_contact_headers(intruder["id"])
        validate_error(api.request_changes_proposal(ctx["proposal"]["id"], cc_intruder),
                       ApiErrorId.ERR_NOT_RESOURCE_OWNER.value)
