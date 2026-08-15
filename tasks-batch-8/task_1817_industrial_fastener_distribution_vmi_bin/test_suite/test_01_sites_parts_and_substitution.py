"""Site and part onboarding, catalogue defaults, listing behaviour,
cross-references, substitution, obsolescence cascade, and the global
authentication / error-envelope contract."""
import pytest

from test_helpers import (
    ANONYMOUS_HEADERS,
    ApiErrorId,
    NON_EXISTENT_UUID,
    TEST_USERS,
    assert_cross_reference,
    assert_part,
    assert_site,
    create_agreement,
    create_cross_reference,
    create_part,
    create_part_payload,
    create_site,
    create_site_payload,
    get_success_data,
    is_iso8601_timestamp,
    is_valid_uuid,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["admin_headers"]
DRIVER = TEST_USERS["driver_headers"]
OPERATOR = TEST_USERS["operator_headers"]


class TestSiteOnboarding:
    def test_create_site_defaults_active_and_zero_balance(self, api):
        """PRD §3.1: "A new site begins in `ACTIVE` status with
        `outstanding_balance_cents` at zero."
        PRD §2.5: "`id` (string): a unique, server-generated identifier
        formatted as a UUID, with no type prefix."

        Design: Corner/entities/create_site_success_and_defaults
        """
        resp = api.create_site(
            create_site_payload(name="Acme Plant", ship_to_code="ACME-1",
                                credit_limit_cents=500000,
                                delivery_mode="LINE_SIDE"),
            ADMIN)
        assert resp.status_code == 201, (
            f"site creation must return 201, got {resp.status_code}: {resp.text}"
        )
        site = validate_success(resp, 201)
        assert_site(site)
        assert site["status"] == "ACTIVE"
        assert site["outstanding_balance_cents"] == 0
        assert is_valid_uuid(site["id"])
        assert is_iso8601_timestamp(site["created_at"])

    def test_get_site_unknown_id_not_found(self, api):
        """PRD §2.8: "existence — every path identifier and every foreign key
        in the request body must reference an existing entity, validated
        left-to-right (site before route, route before stop, part before
        cross-reference), surfacing `ERR_NOT_FOUND` for the first identifier
        that does not resolve".

        Design: Corner/entities/get_site_not_found_returns_404
        """
        resp = api.get_site(NON_EXISTENT_UUID, ADMIN)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND, 404)

    def test_duplicate_ship_to_code_rejected(self, api):
        """PRD §3.1: "The `ship_to_code` must be unique across all sites
        regardless of status; a collision is rejected with `ERR_DUPLICATE`."

        Design: Corner/validations/duplicate_ship_to_code_rejected
        """
        first = api.create_site(
            create_site_payload(name="First", ship_to_code="DUP-1",
                                credit_limit_cents=100), ADMIN)
        assert first.status_code == 201
        resp = api.create_site(
            create_site_payload(name="Second", ship_to_code="DUP-1",
                                credit_limit_cents=200,
                                delivery_mode="LINE_SIDE"),
            ADMIN)
        validate_error(resp, ApiErrorId.ERR_DUPLICATE, 409)

    def test_create_site_invalid_delivery_mode_rejected(self, api):
        """PRD §2.8: "request shape — every required input field present, types
        matching the entity schema, enum values within their declared sets, and
        `flat_bin_price_cents` present exactly when `pricing_mode` is
        `COST_PER_BIN`, surfacing `ERR_INVALID_REQUEST`".

        Design: Corner/entities/create_part_invalid_enum_returns_invalid_request
        """
        resp = api.create_site(
            {"name": "Bad Enum", "ship_to_code": "BE-1",
             "credit_limit_cents": 100, "delivery_mode": "AIR_DROP"},
            ADMIN)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST, 400)


class TestPartCatalogue:
    @pytest.mark.parametrize(
        "missing_field",
        ["sku", "description", "unit_price_cents", "total_stock_qty"],
    )
    def test_create_part_missing_required_field_rejected(self, api,
                                                         missing_field):
        """PRD §2.8: "request shape — every required input field present, types
        matching the entity schema, enum values within their declared sets, and
        `flat_bin_price_cents` present exactly when `pricing_mode` is
        `COST_PER_BIN`, surfacing `ERR_INVALID_REQUEST`".
        PRD §3.1: "Each part is created with a distributor `sku` (unique across
        all parts in any status, with duplicates rejected as `ERR_DUPLICATE`),
        a free-text `description`, an `is_critical` flag that defaults to false
        and marks fasteners requiring lot traceability and certification on
        every delivery, a catalogue `unit_price_cents` of at least one cent,
        and a `total_stock_qty` recording physical distributor stock on hand
        (zero or positive)."

        Design: Corner/entities/create_part_missing_required_field_returns_invalid_request
        """
        payload = create_part_payload()
        payload.pop(missing_field)
        resp = api.create_part(payload, ADMIN)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST, 400)

    def test_part_available_qty_initialized_from_stock(self, api):
        """PRD §3.1: "At creation `available_qty` is initialized to the full
        `total_stock_qty` and `reserved_qty` starts at zero; both are
        thereafter maintained by the kitting workflows of §3.6."

        Design: Corner/entities/part_computed_available_qty_initialized_from_stock
        """
        resp = api.create_part(
            create_part_payload(sku="CP-1", unit_price_cents=100,
                                total_stock_qty=250),
            ADMIN)
        part = validate_success(resp, 201)
        assert_part(part)
        assert part["available_qty"] == 250
        assert part["reserved_qty"] == 0

    def test_list_parts_paginates_with_default_limit(self, api):
        """PRD §2.3: "The `limit` parameter caps the number of items returned:
        it defaults to 10, with a minimum of 1 and a maximum of 100."
        PRD §2.3: "List responses carry `limit`, `offset`, `total_count`, and
        `has_more` in the `meta` object of the envelope."

        Design: Corner/entities/list_endpoints_paginate_with_defaults
        """
        for i in range(12):
            resp = api.create_part(
                create_part_payload(sku=f"PG-{i + 1:02d}", unit_price_cents=10,
                                    total_stock_qty=1),
                ADMIN)
            assert resp.status_code == 201
        data, meta = validate_paginated(api.list_parts(ADMIN))
        assert len(data) == 10, "default limit must cap the page at 10"
        assert meta["total_count"] == 12
        assert meta["has_more"] is True
        assert meta["limit"] == 10
        assert meta["offset"] == 0

    def test_list_parts_filter_by_status(self, api):
        """PRD §3.1: "Parts can also be listed with an optional `status`
        filter."

        Design: Corner/entities/list_parts_filter_by_status
        """
        pa = create_part(api, sku="FLT-A", unit_price_cents=10,
                         total_stock_qty=1)
        pb = create_part(api, sku="FLT-B", unit_price_cents=10,
                         total_stock_qty=1)
        get_success_data(api.obsolete_part(pb["id"], ADMIN))
        data, meta = validate_paginated(
            api.list_parts(ADMIN, params={"status": "OBSOLETE"}))
        assert meta["total_count"] == 1
        assert len(data) == 1
        assert all(p["status"] == "OBSOLETE" for p in data)
        assert data[0]["id"] == pb["id"]
        assert pa["id"] not in [p["id"] for p in data]


class TestCrossReferencesAndSubstitution:
    def _two_parts(self, api):
        pa = create_part(api, sku="XR-A", unit_price_cents=10,
                         total_stock_qty=1)
        pb = create_part(api, sku="XR-B", unit_price_cents=10,
                         total_stock_qty=1)
        return pa, pb

    def test_cross_reference_carries_no_version_fields(self, api):
        """PRD §2.5: "Part cross-references are the deliberate exception: a
        cross-reference is a lightweight declaration that is only ever
        deactivated, never edited, so it carries `id` and `created_at` only —
        both `updated_at` and `version` are absent from it."
        PRD §3.1: "A cross-reference whose `is_active` flag is false is never
        selected by substitution; the flag defaults to true."

        Design: Corner/entities/part_cross_reference_common_fields_false_immutable
        """
        pa, pb = self._two_parts(api)
        resp = api.create_part_cross_reference(
            {"from_part_id": pa["id"], "to_part_id": pb["id"],
             "priority_rank": 1},
            ADMIN)
        xref = validate_success(resp, 201)
        assert_cross_reference(xref)
        assert xref["is_active"] is True

    def test_self_referential_cross_reference_rejected(self, api):
        """PRD §3.1: "Declaring a cross-reference from a part to itself is
        rejected with `ERR_NO_SUBSTITUTE`, and declaring the same
        (`from_part_id`, `to_part_id`) pair twice is rejected with
        `ERR_DUPLICATE`."

        Design: Corner/validations/self_referential_cross_reference_rejected
        """
        pa = create_part(api, sku="SELF-1", unit_price_cents=100,
                         total_stock_qty=100)
        resp = api.create_part_cross_reference(
            {"from_part_id": pa["id"], "to_part_id": pa["id"],
             "priority_rank": 1},
            ADMIN)
        validate_error(resp, ApiErrorId.ERR_NO_SUBSTITUTE, 422)

    def test_substitute_selects_lowest_priority_rank(self, api):
        """PRD §3.7: "Eligible candidates resolve only through cross-reference
        rows leading from the agreement's current part whose `is_active` is
        true and whose target part is `ACTIVE`, ordered by `priority_rank`
        ascending with ties broken by `created_at` ascending; the first
        candidate in that order is selected."
        PRD §3.7: "Every bin agreement for the part in `ACTIVE` or
        `AT_CAPACITY` status transitions to `RETIRED` — unless at least one
        active cross-reference leads from this part to some other part that is
        still `ACTIVE`, in which case the agreement stays live so the operator
        can repoint it."

        Design: Corner/validations/substitution_selector_priority_order
        """
        site = create_site(api, ship_to_code="SUB-1")
        po = create_part(api, sku="SUB-O", unit_price_cents=100,
                         total_stock_qty=100)
        ps1 = create_part(api, sku="SUB-S1", unit_price_cents=100,
                          total_stock_qty=100)
        ps2 = create_part(api, sku="SUB-S2", unit_price_cents=100,
                          total_stock_qty=100)
        agr = create_agreement(api, site["id"], po["id"],
                               bin_location="SUB-L", min_qty=1, max_qty=10)
        create_cross_reference(api, po["id"], ps1["id"], priority_rank=2)
        create_cross_reference(api, po["id"], ps2["id"], priority_rank=1)
        get_success_data(api.obsolete_part(po["id"], ADMIN))

        repointed = validate_success(
            api.substitute_bin_agreement(agr["id"], ADMIN))
        assert repointed["part_id"] == ps2["id"], (
            "priority_rank 1 must beat priority_rank 2"
        )
        assert repointed["status"] == "ACTIVE", (
            "agreement survives the obsolescence cascade while an active "
            "substitute exists"
        )

    def test_obsolescence_cascade_retires_bins_and_deactivates_xrefs(self, api):
        """PRD §3.7: "Every bin agreement for the part in `ACTIVE` or
        `AT_CAPACITY` status transitions to `RETIRED` — unless at least one
        active cross-reference leads from this part to some other part that is
        still `ACTIVE`, in which case the agreement stays live so the operator
        can repoint it."
        PRD §3.7: "Every cross-reference naming this part as its `to_part_id`
        is deactivated, its `is_active` set to false, because an obsolete part
        can no longer serve as anyone's substitute; cross-references leading
        from this part, by contrast, remain active precisely to drive that
        substitution."

        Design: Corner/state_machines/obsolescence_cascade_retires_agreements_and_deactivates_xrefs
        """
        site = create_site(api, ship_to_code="OC-1")
        pa = create_part(api, sku="OC-A", unit_price_cents=100,
                         total_stock_qty=100)
        pb = create_part(api, sku="OC-B", unit_price_cents=100,
                         total_stock_qty=100)
        pc = create_part(api, sku="OC-C", unit_price_cents=100,
                         total_stock_qty=100)
        agr_a = create_agreement(api, site["id"], pa["id"], bin_location="W1",
                                 min_qty=1, max_qty=10)
        agr_b = create_agreement(api, site["id"], pb["id"], bin_location="W2",
                                 min_qty=1, max_qty=10)
        xref = create_cross_reference(api, pc["id"], pa["id"], priority_rank=1)

        obsoleted = validate_success(api.obsolete_part(pa["id"], ADMIN))
        assert obsoleted["status"] == "OBSOLETE"

        agr_a_after = get_success_data(api.get_bin_agreement(agr_a["id"], ADMIN))
        assert agr_a_after["status"] == "RETIRED", (
            "PA has no outgoing substitute, so its agreement retires"
        )
        agr_b_after = get_success_data(api.get_bin_agreement(agr_b["id"], ADMIN))
        assert agr_b_after["status"] == "ACTIVE", (
            "an agreement on a different part is untouched"
        )
        xrefs, _meta = validate_paginated(
            api.list_part_cross_references(
                ADMIN, params={"to_part_id": pa["id"]}))
        target = [x for x in xrefs if x["id"] == xref["id"]]
        assert len(target) == 1
        assert target[0]["is_active"] is False, (
            "an obsolete part can no longer serve as a substitute"
        )


class TestAuthenticationAndEnvelope:
    def test_route_driver_cannot_create_parts(self, api):
        """PRD §2.1: "A request whose role is authenticated but not permitted
        on the target endpoint is rejected with `ERR_UNAUTHORIZED` (HTTP 403);
        the per-endpoint role assignments are listed in §4."
        PRD §4: POST /vmi/parts — Authorized Role(s): DistributorAdmin.

        Design: Corner/roles/route_driver_cannot_create_parts
        """
        resp = api.create_part(
            create_part_payload(sku="RB-1", unit_price_cents=100,
                                total_stock_qty=1),
            DRIVER)
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED, 403)

    def test_missing_auth_headers_unauthenticated(self, api):
        """PRD §2.1: "A request missing either header, or presenting a role
        outside the declared set, is rejected with `ERR_UNAUTHENTICATED`
        (HTTP 401)."
        PRD §2.8: "The stages, in evaluation order, are: (1) authentication —
        the headers check of §2.1, surfacing `ERR_UNAUTHENTICATED`".

        Design: Corner/roles/missing_auth_headers_returns_unauthenticated
        """
        resp = api.get_site(NON_EXISTENT_UUID, ANONYMOUS_HEADERS)
        validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED, 401)

    def test_error_envelope_shape(self, api):
        """PRD §2.2: "The `meta` object for error responses contains only
        `api_request_id` and `api_request_timestamp`."
        PRD §2.2: "The `error_id` is a unique, machine-readable string that
        identifies the specific error."

        Design: Corner/errors/error_envelope_shape
        """
        resp = api.get_part(NON_EXISTENT_UUID, ADMIN)
        err = validate_error(resp, ApiErrorId.ERR_NOT_FOUND, 404)
        body = resp.json()
        assert body["response_type"] == "error"
        assert err["error_id"] == "ERR_NOT_FOUND"
        assert isinstance(err["message"], str) and err["message"].strip()
        assert isinstance(body["meta"].get("api_request_id"), str)
        assert isinstance(body["meta"].get("api_request_timestamp"), str)
