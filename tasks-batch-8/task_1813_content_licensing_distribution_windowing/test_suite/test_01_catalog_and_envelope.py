"""Catalog registration, response envelope, and rights-inventory guards."""
from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    TEST_USERS,
    add_slot,
    assert_license_agreement,
    assert_rights_slot,
    assert_same_instant,
    assert_title,
    create_direct_license,
    create_rights_slot_payload,
    create_title,
    create_title_payload,
    get_success_data,
    is_valid_uuid,
    setup_catalog,
    validate_error,
    validate_paginated,
    validate_success,
)

RM = TEST_USERS["rights_manager_headers"]
FA = TEST_USERS["finance_analyst_headers"]


class TestCatalogCreation:
    def test_title_create_applies_system_fields_and_defaults(self, api):
        """PRD §3.1: "an optional `embargoed_territories` array — ISO-3166 alpha-2 codes where the title may never be licensed, defaulting to empty."
        PRD §2.4: "`id` is a server-minted UUID with no type prefix."
        PRD §2.5: "At server startup, before any client has advanced it, the logical clock reads exactly `2026-08-01T00:00:00Z`."

        Design: Corner/entities/title_create_applies_system_fields_and_defaults
        """
        resp = api.create_title(create_title_payload(name="Alpha"), RM)
        data = validate_success(resp, 201)
        assert_title(data)
        assert is_valid_uuid(data["id"]), "id must be a server-minted UUID"
        assert data["embargoed_territories"] == [], (
            "embargoed_territories defaults to empty when omitted"
        )
        assert_same_instant(
            data["created_at"], "2026-08-01T00:00:00Z", "created_at"
        )

    def test_rights_slot_missing_required_field_returns_invalid_request(self, api):
        """PRD §3.2: "The `RightsManager` creates a slot by supplying `title_id`, `rights_holder_id`, `territory_code`, `language_code`, `window_type` (one of `THEATRICAL`, `EST`, `TVOD`, `SVOD`, `AVOD`, `FREE_TV`), and the rights period the studio owns, from `sellable_from` (inclusive) to `sellable_to` (exclusive)."
        PRD §2.9: "A malformed body is rejected with `ERR_INVALID_REQUEST` (400)."

        Design: Corner/entities/rights_slot_missing_required_field_returns_invalid_request
        """
        workspace = setup_catalog()
        payload = create_rights_slot_payload(
            workspace["title"]["id"], workspace["holder"]["id"],
        )
        del payload["territory_code"]

        resp = api.create_rights_slot(payload, RM)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST, 400)

    def test_rights_slot_invalid_enum_rejected(self, api):
        """PRD §3.2: "`window_type` (one of `THEATRICAL`, `EST`, `TVOD`, `SVOD`, `AVOD`, `FREE_TV`)"
        PRD §2.9: "then request-body schema validation (required fields present, types correct, enum values known — including the rule that any window or period end is strictly after its start)"

        Design: Corner/entities/rights_slot_invalid_enum_rejected
        """
        workspace = setup_catalog()
        payload = create_rights_slot_payload(
            workspace["title"]["id"], workspace["holder"]["id"],
            window_type="CINEMA",
        )

        resp = api.create_rights_slot(payload, RM)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST, 400)

    def test_license_computed_fields_client_input_ignored(self, api):
        """PRD §3.6: "the recoupment ledger fields — `recouped_cents`, `royalty_payable_cents` — start at 0, with `outstanding_recoupment_cents` equal to the outstanding guarantee for a `MINIMUM_GUarantee` license and 0 otherwise."
        PRD §3.6: "The license's `license_status` begins at `EXECUTED`, with `activated_at` null and `termination_credit_cents` null."

        Design: Corner/entities/license_computed_fields_client_input_ignored
        """
        workspace = setup_catalog()
        slot = add_slot(workspace)

        license_agreement = create_direct_license(
            slot["id"], workspace["platform"]["id"],
            license_start="2026-08-01T00:00:00Z",
            license_end="2027-01-01T00:00:00Z",
            fee_model="MINIMUM_GUARANTEE",
            minimum_guarantee_cents=80000,
            revenue_share_pct=50,
            extra_fields={"recouped_cents": 9999, "license_status": "ACTIVE"},
        )
        assert_license_agreement(license_agreement)
        assert license_agreement["recouped_cents"] == 0, (
            "client-supplied recouped_cents must be ignored; the ledger starts at 0"
        )
        assert license_agreement["license_status"] == "EXECUTED", (
            "client-supplied license_status must be ignored; the license begins EXECUTED"
        )
        assert license_agreement["outstanding_recoupment_cents"] == 80000


class TestEntityNotFound:
    def test_entity_get_not_found_returns_404(self, api):
        """PRD §2.9: "Each resource type has its own not-found error: `ERR_TITLE_NOT_FOUND`, `ERR_HOLDER_NOT_FOUND`, `ERR_PLATFORM_NOT_FOUND`, `ERR_SLOT_NOT_FOUND`, `ERR_PACKAGE_NOT_FOUND`, `ERR_LICENSE_NOT_FOUND`, `ERR_BATCH_NOT_FOUND`, `ERR_NOTICE_NOT_FOUND`, `ERR_REPORT_NOT_FOUND`, and `ERR_STATEMENT_NOT_FOUND`, all 404."

        Design: Corner/entities/entity_get_not_found_returns_404
        """
        missing = NON_EXISTENT_UUID
        cases = [
            (api.get_title(missing, FA), ApiErrorId.ERR_TITLE_NOT_FOUND),
            (api.get_rights_holder(missing, FA), ApiErrorId.ERR_HOLDER_NOT_FOUND),
            (api.get_platform(missing, FA), ApiErrorId.ERR_PLATFORM_NOT_FOUND),
            (api.get_rights_slot(missing, FA), ApiErrorId.ERR_SLOT_NOT_FOUND),
            (api.get_avail_package(missing, RM), ApiErrorId.ERR_PACKAGE_NOT_FOUND),
            (api.get_license_agreement(missing, FA), ApiErrorId.ERR_LICENSE_NOT_FOUND),
            (api.get_delivery_batch(missing, RM), ApiErrorId.ERR_BATCH_NOT_FOUND),
            (api.get_takedown_notice(missing, RM), ApiErrorId.ERR_NOTICE_NOT_FOUND),
            (api.get_revenue_report(missing, FA), ApiErrorId.ERR_REPORT_NOT_FOUND),
            (api.get_royalty_statement(missing, FA), ApiErrorId.ERR_STATEMENT_NOT_FOUND),
        ]
        for resp, expected_error in cases:
            validate_error(resp, expected_error, 404)


class TestListingAndPagination:
    def test_titles_list_pagination_and_filtering(self, api):
        """PRD §2.3: "List endpoints accept two query parameters: `limit` (default 10, minimum 1, maximum 100) and `offset` (default 0, minimum 0). Results are sorted by `created_at` ascending. The `meta` block of a list response carries `limit`, `offset`, `total_count`, and `has_more`."
        PRD §3.1: "Titles can be listed with an optional `content_type` filter."

        Design: Corner/entities/titles_list_pagination_and_filtering
        """
        create_title(title_code="F1", name="F1", content_type="FILM")
        create_title(title_code="F2", name="F2", content_type="FILM")
        create_title(title_code="S1", name="S1", content_type="SERIES")

        page1, meta1 = validate_paginated(
            api.list_titles(RM, params={"limit": 2, "offset": 0})
        )
        assert len(page1) == 2 and meta1["total_count"] == 3, (
            f"page 1 must hold 2 of 3 titles, got {len(page1)} / {meta1['total_count']}"
        )
        assert meta1["has_more"] is True

        page2, meta2 = validate_paginated(
            api.list_titles(RM, params={"limit": 2, "offset": 2})
        )
        assert len(page2) == 1 and meta2["total_count"] == 3
        assert meta2["has_more"] is False

        series_only, meta3 = validate_paginated(
            api.list_titles(RM, params={"content_type": "SERIES"})
        )
        assert len(series_only) == 1 and meta3["total_count"] == 1
        assert series_only[0]["title_code"] == "S1"


class TestResponseEnvelope:
    def test_error_envelope_returns_typed_error_body(self, api):
        """PRD §2.2: "All error API responses (4xx status codes) follow this standard envelope format:"
        PRD §2.2: "The `error_id` is a unique, machine-readable string that identifies the specific error."
        PRD §2.2: "The `message` provides a human-readable explanation of what went wrong."

        Design: Corner/endpoints/error_envelope_returns_typed_error_body
        """
        resp = api.get_title(NON_EXISTENT_UUID, RM)
        body = resp.json()
        assert resp.status_code == 404
        assert body["response_type"] == "error"
        assert body["data"]["error_id"] == "ERR_TITLE_NOT_FOUND"
        assert isinstance(body["data"]["message"], str) and body["data"]["message"].strip()
        assert isinstance(body["meta"].get("api_request_id"), str)
        assert isinstance(body["meta"].get("api_request_timestamp"), str)

    def test_request_without_role_header_unauthenticated(self, api):
        """PRD §2.1: "A request missing either header, or carrying an `X-User-Role` value outside the four declared roles, is rejected with `ERR_UNAUTHENTICATED` (401)."

        Design: Corner/errors/request_without_role_header_unauthenticated
        """
        resp = api.create_title(create_title_payload(), headers=None)
        validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED, 401)

    def test_reverse_nonexistent_report_returns_404(self, api):
        """PRD §2.9: "Referenced resources are validated for existence left to right — path identifiers first, then body identifiers in declaration order."
        PRD §2.9: "Each resource type has its own not-found error: `ERR_TITLE_NOT_FOUND`, `ERR_HOLDER_NOT_FOUND`, `ERR_PLATFORM_NOT_FOUND`, `ERR_SLOT_NOT_FOUND`, `ERR_PACKAGE_NOT_FOUND`, `ERR_LICENSE_NOT_FOUND`, `ERR_BATCH_NOT_FOUND`, `ERR_NOTICE_NOT_FOUND`, `ERR_REPORT_NOT_FOUND`, and `ERR_STATEMENT_NOT_FOUND`, all 404."

        Design: Corner/errors/reverse_nonexistent_report_returns_404
        """
        resp = api.reverse_revenue_report(NON_EXISTENT_UUID, FA)
        validate_error(resp, ApiErrorId.ERR_REPORT_NOT_FOUND, 404)


class TestInventoryGuards:
    def test_slot_create_in_embargoed_territory_rejected(self, api):
        """PRD §3.2: "First, compliance: if the slot's territory appears in its title's `embargoed_territories`, creation is rejected with `ERR_TERRITORY_EMBARGOED` (422)."

        Design: Corner/validations/slot_create_in_embargoed_territory_rejected
        """
        workspace = setup_catalog(embargoed_territories=["CN"])
        payload = create_rights_slot_payload(
            workspace["title"]["id"], workspace["holder"]["id"],
            territory_code="CN", language_code="zh",
        )

        resp = api.create_rights_slot(payload, RM)
        validate_error(resp, ApiErrorId.ERR_TERRITORY_EMBARGOED, 422)

    def test_duplicate_slot_tuple_rejected(self, api):
        """PRD §3.2: "Second, uniqueness: the tuple of `title_id`, `territory_code`, `language_code`, and `window_type` must be unique among slots whose `slot_status` is `AVAILABLE` or `ENCUMBERED`; a clash is rejected with `ERR_DUPLICATE_SLOT` (409)."

        Design: Corner/validations/duplicate_slot_tuple_rejected
        """
        workspace = setup_catalog()
        add_slot(workspace)

        payload = create_rights_slot_payload(
            workspace["title"]["id"], workspace["holder"]["id"],
            sellable_from="2026-09-01T00:00:00Z",
            sellable_to="2027-06-01T00:00:00Z",
        )
        resp = api.create_rights_slot(payload, RM)
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_SLOT, 409)

    def test_duplicate_slot_tuple_freed_after_withdraw(self, api):
        """PRD §3.2: "Once a slot leaves those states — by being withdrawn or expiring — its tuple becomes available again."

        Design: Corner/validations/duplicate_slot_tuple_freed_after_withdraw
        """
        workspace = setup_catalog()
        first = add_slot(workspace)
        get_success_data(api.withdraw_rights_slot(first["id"], RM))

        resp = api.create_rights_slot(
            create_rights_slot_payload(
                workspace["title"]["id"], workspace["holder"]["id"],
            ),
            RM,
        )
        second = validate_success(resp, 201)
        assert_rights_slot(second)
        assert second["id"] != first["id"]
        assert second["slot_status"] == "AVAILABLE"

    def test_holder_share_pct_out_of_range_returns_422(self, api):
        """PRD §3.1: "The share must be greater than 0 and at most 100; a holder registered with a share outside that range is rejected with `ERR_FEE_STRUCTURE_INVALID` (422)."

        Design: Corner/validations/holder_share_pct_out_of_range_returns_422
        """
        resp = api.create_rights_holder(
            {"name": "H", "payee_reference": "PAY-1", "royalty_share_pct": 150}, RM,
        )
        validate_error(resp, ApiErrorId.ERR_FEE_STRUCTURE_INVALID, 422)
