"""Shipper registration defaults, list pagination, typed 404s, and RBAC."""
from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    build_user_headers,
    create_shipper,
    create_tariff_payload,
    setup_lcl_lane,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.fixtures import FC, OPS
from test_helpers.test_users import (
    make_adjuster_headers,
    make_compliance_headers,
    make_doc_officer_headers,
    make_shipper_headers,
)


class TestShipperAndContractDefaults:
    def test_shipper_defaults_applied(self, api):
        """PRD §3.1: "The shipper's `credit_terms` may also be supplied at
        registration and defaults to `PREPAID_ONLY`; the other accepted values
        are `NET_7` and `NET_30`."
        PRD §3.1: "On creation the shipper's `status` is `ACTIVE`, and both
        exposure counters — `credit_exposure_posted_cents` and
        `credit_exposure_forward_cents` — are initialized to zero."

        Design: Corner/entities/shipper_and_contract_defaults_applied
        """
        shipper = validate_success(
            api.create_shipper(
                {"legal_name": "ACME DEF", "credit_limit_cents": 5000000}, OPS),
            201)
        assert shipper["credit_terms"] == "PREPAID_ONLY"
        assert shipper["status"] == "ACTIVE"
        assert shipper["credit_exposure_posted_cents"] == 0
        assert shipper["credit_exposure_forward_cents"] == 0

    def test_contract_free_time_defaults_applied(self, api):
        """PRD §3.3: "the free-time allowances `demurrage_free_days`
        (default 4) and `detention_free_days` (default 3)".

        Design: Corner/entities/shipper_and_contract_defaults_applied
        """
        contract = validate_success(
            api.create_carrier_contract(
                {
                    "contract_number": "CARR-D",
                    "carrier_name": "OOCL",
                    "service_lane": "CNSHA-USNYC",
                    "container_rates": [
                        {"container_type": "20GP", "rate_cents": 90000},
                    ],
                    "demurrage_tiers": [
                        {"from_day": 1, "to_day": None, "per_diem_cents": 10000},
                    ],
                    "detention_per_diem_cents": 8000,
                    "service_start": "2026-01-01T00:00:00Z",
                    "service_end": "2026-12-31T00:00:00Z",
                },
                OPS),
            201)
        assert contract["demurrage_free_days"] == 4
        assert contract["detention_free_days"] == 3


class TestListPagination:
    def test_shippers_list_pagination_envelope_and_defaults(self, api):
        """PRD §2.3: "The `limit` parameter specifies the maximum number of
        items to return; it defaults to 10 when not provided, has a minimum of
        1, and a maximum of 100. The `offset` parameter specifies the number of
        items to skip and defaults to 0."
        PRD §2.3: "Paginated and non-paginated list responses include `limit`,
        `offset`, `total_count`, and `has_more` in the `meta` object of the
        response envelope."

        Design: Corner/entities/list_pagination_envelope_and_defaults
        """
        for name in ("PG A", "PG B", "PG C"):
            create_shipper(legal_name=name, credit_limit_cents=1000)

        page1, meta1 = validate_paginated(
            api.list_shippers(OPS, params={"limit": 2, "offset": 0}))
        assert meta1["total_count"] == 3
        assert meta1["has_more"] is True
        assert len(page1) == 2

        page2, meta2 = validate_paginated(
            api.list_shippers(OPS, params={"limit": 2, "offset": 2}))
        assert meta2["total_count"] == 3
        assert meta2["has_more"] is False
        assert len(page2) == 1

        page_all, meta_all = validate_paginated(api.list_shippers(OPS))
        assert meta_all["limit"] == 10
        assert len(page_all) == 3
        assert meta_all["has_more"] is False


class TestTypedNotFound:
    def test_booking_get_not_found_returns_404(self, api):
        """PRD §2.9: "When an endpoint path contains an identifier, existence
        is confirmed before any state, role, or business rule runs; a missing
        identifier yields the corresponding 404 (`ERR_SHIPPER_NOT_FOUND`,
        `ERR_TARIFF_NOT_FOUND`, `ERR_CONTRACT_NOT_FOUND`, `ERR_BOND_NOT_FOUND`,
        `ERR_VOYAGE_NOT_FOUND`, `ERR_BOOKING_NOT_FOUND`,
        `ERR_CONSOLIDATION_NOT_FOUND`, `ERR_ASSIGNMENT_NOT_FOUND`,
        `ERR_BL_NOT_FOUND`, `ERR_FILING_NOT_FOUND`, `ERR_INVOICE_NOT_FOUND`,
        `ERR_POLICY_NOT_FOUND`, or `ERR_CLAIM_NOT_FOUND`)."

        Design: Corner/entities/booking_get_not_found_returns_404
        """
        res = api.get_booking(NON_EXISTENT_UUID, OPS)
        validate_error(res, ApiErrorId.ERR_BOOKING_NOT_FOUND, expected_status=404)

    def test_typed_not_found_sweep_across_collections(self, api):
        """PRD §2.9: "a missing identifier yields the corresponding 404
        (`ERR_SHIPPER_NOT_FOUND`, `ERR_TARIFF_NOT_FOUND`,
        `ERR_CONTRACT_NOT_FOUND`, `ERR_BOND_NOT_FOUND`, `ERR_VOYAGE_NOT_FOUND`,
        `ERR_BOOKING_NOT_FOUND`, `ERR_CONSOLIDATION_NOT_FOUND`,
        `ERR_ASSIGNMENT_NOT_FOUND`, `ERR_BL_NOT_FOUND`, `ERR_FILING_NOT_FOUND`,
        `ERR_INVOICE_NOT_FOUND`, `ERR_POLICY_NOT_FOUND`, or
        `ERR_CLAIM_NOT_FOUND`)."

        Design: Corner/errors/typed_not_found_sweep_across_collections
        """
        res = api.get_tariff(NON_EXISTENT_UUID, OPS)
        validate_error(res, ApiErrorId.ERR_TARIFF_NOT_FOUND, expected_status=404)
        res = api.get_voyage(NON_EXISTENT_UUID, OPS)
        validate_error(res, ApiErrorId.ERR_VOYAGE_NOT_FOUND, expected_status=404)
        res = api.get_claim(NON_EXISTENT_UUID, OPS)
        validate_error(res, ApiErrorId.ERR_CLAIM_NOT_FOUND, expected_status=404)
        res = api.get_consolidation(NON_EXISTENT_UUID, OPS)
        validate_error(res, ApiErrorId.ERR_CONSOLIDATION_NOT_FOUND,
                       expected_status=404)


class TestAuthenticationAndRoles:
    def test_undeclared_role_header_rejected(self, api):
        """PRD §2.1: "A request missing either header, or carrying a role value
        outside the declared set, is rejected with
        `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400)."

        Design: Corner/rbac/missing_auth_headers_unauthenticated
        """
        bogus = build_user_headers("test-superuser-1", "SuperUser")
        res = api.get_shipper(NON_EXISTENT_UUID, bogus)
        validate_error(res, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER,
                       expected_status=400)

    def test_any_role_can_read_shared_gets(self, api):
        """PRD §2.1: "The system recognizes seven declared role names —
        `Shipper`, `BookingCoordinator`, `DocumentationOfficer`,
        `ComplianceOfficer`, `FinanceController`, `ClaimsAdjuster`, and
        `OperationsManager` — and treats `Any` as a pseudo-role meaning "every
        declared role may perform this operation" (it appears only on shared
        list-and-get endpoints)."

        Design: Corner/rbac/any_role_can_read_shared_gets
        """
        tariff = validate_success(
            api.create_tariff(create_tariff_payload(tariff_code="T-GET"),
                              make_compliance_headers("co_1")),
            201)
        # ClaimsAdjuster holds no tariff write powers but may read.
        res = api.get_tariff(tariff["id"], make_adjuster_headers("adj_9"))
        data = validate_success(res, 200)
        assert data["tariff_code"] == "T-GET"

    def test_shipper_cannot_publish_side_of_tariffs(self, api):
        """PRD §2.1: "A request whose role is not listed in the endpoint's
        authorized roles is rejected with `ERR_INSUFFICIENT_PERMISSIONS`
        (HTTP 403)."
        PRD §4: POST /freight/tariffs is authorized for ComplianceOfficer.

        Design: Corner/rbac/shipper_cannot_publish_tariff
        """
        shipper = create_shipper(legal_name="ACME RB1")
        res = api.create_tariff(
            create_tariff_payload(tariff_code="T-NO"),
            make_shipper_headers(shipper["id"]))
        validate_error(res, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS,
                       expected_status=403)
        data, meta = validate_paginated(api.list_tariffs(OPS))
        assert meta["total_count"] == 0, "rejected request must not create a row"

    def test_documentation_officer_cannot_confirm_booking(self, api):
        """PRD §2.1: "A request whose role is not listed in the endpoint's
        authorized roles is rejected with `ERR_INSUFFICIENT_PERMISSIONS`
        (HTTP 403)."
        PRD §3.6: "Confirmation — a `BookingCoordinator` action — transitions
        a `QUOTED` booking to `CONFIRMED`."

        Design: Corner/rbac/documentation_officer_cannot_confirm_booking
        """
        ctx = setup_lcl_lane()
        booking = validate_success(
            api.create_booking(
                {
                    "voyage_id": ctx["voyage"]["id"],
                    "tariff_id": ctx["tariff"]["id"],
                    "rate_source": "CONTRACT",
                    "mode": "LCL",
                    "commodity_type": "GENERAL",
                    "gross_weight_kg": 4000,
                    "volume_cbm": 6.0,
                    "terms": "PREPAID",
                },
                make_shipper_headers(ctx["shipper"]["id"])),
            201)
        res = api.confirm_booking(booking["id"], make_doc_officer_headers("doc_1"))
        validate_error(res, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS,
                       expected_status=403)
        after = validate_success(api.get_booking(booking["id"], OPS), 200)
        assert after["status"] == "QUOTED"

    def test_shipper_cannot_cancel_other_shippers_booking(self, api):
        """PRD §2.1: "When `X-User-Role` is `Shipper`, `X-User-ID` is the `id`
        of the acting `Shipper` entity; ownership checks on any resource that
        references a `Shipper` (a booking's `shipper_id`, a claim's `policy_id`
        resolved through its policy's booking, and so on) compare the
        resource's foreign-key field to `X-User-ID`, and a mismatch is
        rejected with `ERR_INSUFFICIENT_PERMISSIONS`."

        Design: Corner/rbac/shipper_cannot_cancel_other_shippers_booking
        """
        shipper_a = create_shipper(legal_name="ACME A")
        shipper_b = create_shipper(legal_name="ACME B")
        ctx = setup_lcl_lane()
        booking = validate_success(
            api.create_booking(
                {
                    "voyage_id": ctx["voyage"]["id"],
                    "tariff_id": ctx["tariff"]["id"],
                    "rate_source": "CONTRACT",
                    "mode": "LCL",
                    "commodity_type": "GENERAL",
                    "gross_weight_kg": 4000,
                    "volume_cbm": 6.0,
                    "terms": "PREPAID",
                },
                make_shipper_headers(shipper_a["id"])),
            201)

        res = api.cancel_booking(booking["id"],
                                 make_shipper_headers(shipper_b["id"]),
                                 reason="not mine")
        validate_error(res, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS,
                       expected_status=403)

        cancelled = validate_success(
            api.cancel_booking(booking["id"],
                               make_shipper_headers(shipper_a["id"]),
                               reason="mine"),
            200)
        assert cancelled["status"] == "CANCELLED"


class TestSuspendedShipperGate:
    def test_suspended_shipper_cannot_create_booking(self, api):
        """PRD §3.1: "A suspended shipper may not create new bookings and may
        not confirm existing quoted ones; either attempt is rejected with
        `ERR_SHIPPER_SUSPENDED`."

        Design: Corner/validations/suspended_shipper_cannot_create_booking
        """
        ctx = setup_lcl_lane()
        shipper = ctx["shipper"]
        get = api.suspend_shipper(shipper["id"], FC)
        assert validate_success(get, 200)["status"] == "SUSPENDED"

        payload = {
            "voyage_id": ctx["voyage"]["id"],
            "tariff_id": ctx["tariff"]["id"],
            "rate_source": "CONTRACT",
            "mode": "LCL",
            "commodity_type": "GENERAL",
            "gross_weight_kg": 4000,
            "volume_cbm": 6.0,
            "terms": "PREPAID",
        }
        res = api.create_booking(payload, make_shipper_headers(shipper["id"]))
        validate_error(res, ApiErrorId.ERR_SHIPPER_SUSPENDED, expected_status=409)

        reinstated = validate_success(api.reinstate_shipper(shipper["id"], FC), 200)
        assert reinstated["status"] == "ACTIVE"
        booking = validate_success(
            api.create_booking(payload, make_shipper_headers(shipper["id"])), 201)
        assert booking["status"] == "QUOTED"
