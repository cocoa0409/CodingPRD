"""Resource creation/validation, listing, and role-based access control."""
from test_helpers import (
    validate_success,
    validate_error,
    validate_paginated,
    get_success_data,
    is_valid_uuid,
    ApiErrorId,
    NON_EXISTENT_UUID,
    TEST_USERS,
    make_customer_headers,
    create_distillery,
    create_gauged_run,
    fill_barrel,
    setup_completed_run,
    create_customer,
    create_order,
    create_customer_payload,
)

_OC = TEST_USERS["compliance_headers"]
_PM = TEST_USERS["production_headers"]
_SM = TEST_USERS["sales_headers"]
_TRS = TEST_USERS["tasting_headers"]


class TestCustomerCreation:
    def test_create_returns_all_fields(self, api):
        """PRD 3.8: "A `SalesManager` or `TastingRoomStaff` member creates a customer
        by supplying a `name`, an `email` (the login identity), a ship-to `state_code`,
        an optional `club_tier` ... and an optional `age_verified` flag". PRD 2.4:
        "Every resource carries a server-minted `id`, which is a UUID with no type
        prefix."

        Design: Corner/entities/customer_create_returns_all_fields
        """
        data = validate_success(
            api.create_customer(
                create_customer_payload(name="Ada Buyer", email="ada@x.com", state_code="CA",
                                        club_tier="GOLD", age_verified=True),
                _SM,
            ),
            expected_status=201,
        )
        assert data["club_tier"] == "GOLD"
        assert data["age_verified"] is True
        assert is_valid_uuid(data["id"])

    def test_club_tier_and_age_defaults(self, api):
        """PRD 3.8: "an optional `club_tier` (`NONE`, `SILVER`, `GOLD`, or `RESERVE`,
        defaulting to `NONE`), and an optional `age_verified` flag (defaulting to
        false)."

        Design: Corner/entities/customer_club_tier_defaults_none
        """
        data = validate_success(
            api.create_customer(
                create_customer_payload(name="Bo", email="bo@x.com", state_code="NY"), _TRS
            ),
            expected_status=201,
        )
        assert data["club_tier"] == "NONE"
        assert data["age_verified"] is False

    def test_invalid_club_tier_enum_rejected(self, api):
        """PRD 2.1: body validation covers "enum legality" and surfaces `ERR_VALIDATION`
        (422). PRD 3.8: club_tier is one of "`NONE`, `SILVER`, `GOLD`, or `RESERVE`".

        Design: Corner/entities/customer_create_invalid_enum_club_tier_rejected
        """
        resp = api.create_customer(
            create_customer_payload(name="Ada", email="ada2@x.com", state_code="CA",
                                    club_tier="PLATINUM"),
            _SM,
        )
        validate_error(resp, ApiErrorId.ERR_VALIDATION.value)


class TestDistilleryValidation:
    def test_missing_state_code_rejected(self, api):
        """PRD 3.1: "A `ComplianceOfficer` registers a bonded premises by supplying a
        `name`, a `dsp_permit_number` ..., and a two-letter `state_code`." PRD 2.1:
        body validation of required fields surfaces `ERR_VALIDATION` (422).

        Design: Corner/entities/distillery_create_missing_state_code_returns_validation
        """
        resp = api.create_distillery({"name": "Bench DSP", "dsp_permit_number": "DSP-X"}, _OC)
        validate_error(resp, ApiErrorId.ERR_VALIDATION.value)


class TestNotFoundAndListing:
    def test_get_nonexistent_barrel_returns_not_found(self, api):
        """PRD 2.10: "the server resolves them left to right and rejects the first one
        that does not exist with `ERR_NOT_FOUND` (HTTP 404)."

        Design: Corner/entities/barrel_get_nonexistent_returns_not_found
        """
        resp = api.get_barrel(NON_EXISTENT_UUID, _PM)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value)

    def test_list_barrels_by_run_paginated_envelope(self, api):
        """PRD 2.3: "Each list response reports pagination state in `meta` via `limit`,
        `offset`, `total_count` ... and `has_more`". PRD 2.3: "the filter narrows the
        collection before pagination is applied."

        Design: Corner/endpoints/list_barrels_by_run_returns_paginated_envelope
        """
        dist = create_distillery(api, dsp_permit_number="DSP-RB-1")
        run, _ = create_gauged_run(api, dist["id"], collected_wine_gallons=50, collected_proof=100)
        fill_barrel(api, run["id"], fill_proof_gallons=10, rickhouse_position="A-1")
        fill_barrel(api, run["id"], fill_proof_gallons=10, rickhouse_position="A-2")
        data, meta = validate_paginated(
            api.list_barrels(_PM, params={"distillation_run_id": run["id"], "limit": 10, "offset": 0})
        )
        assert len(data) == 2
        assert meta["total_count"] == 2
        assert meta["has_more"] is False


class TestRoleBasedAccess:
    def test_mash_create_denied_for_salesmanager(self, api):
        """PRD 2.1: "If the role is recognized but is not permitted to perform the
        requested operation, the request is rejected with `ERR_FORBIDDEN` (HTTP 403)."
        Mash-batch creation is a `ProductionManager` operation.

        Design: Corner/rbac/mash_create_denied_for_salesmanager
        """
        dist = create_distillery(api, dsp_permit_number="DSP-RB-2")
        resp = api.create_mash_batch(
            {"distillery_id": dist["id"], "grain_bill": "corn", "volume_gallons": 200}, _SM
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN.value)

    def test_ship_denied_for_customer_role(self, api):
        """PRD 3.8: "Shipping an allocated order is a `SalesManager` action". PRD 2.1:
        a recognized but unpermitted role is rejected with `ERR_FORBIDDEN` (403).

        Design: Corner/rbac/ship_denied_for_customer_role
        """
        ctx = setup_completed_run(api, dsp_permit_number="DSP-RB-3", planned_cases=5, fill_proof_gallons=10)
        cust = create_customer(api, name="Own Ola", email="ola@x.com", age_verified=True)
        headers = make_customer_headers(cust["id"])
        order = create_order(api, cust["id"], ctx["bottling_run"]["id"], channel="SELF_DISTRIBUTION",
                             cases=1, as_headers=headers)
        get_success_data(api.pay_order(order["id"], headers))
        resp = api.ship_order(order["id"], headers)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN.value)

    def test_customer_pays_foreign_order_denied(self, api):
        """PRD 2.1: "A `Customer` who invokes a sales-order or tour-booking operation on
        a row whose `customer_id` does not equal its `X-User-ID` is rejected with
        `ERR_FORBIDDEN` (HTTP 403)."

        Design: Corner/rbac/customer_pays_foreign_order_denied
        """
        ctx = setup_completed_run(api, dsp_permit_number="DSP-RB-4", planned_cases=5, fill_proof_gallons=10)
        c1 = create_customer(api, name="Owner One", email="one@x.com", age_verified=True)
        c2 = create_customer(api, name="Intruder Two", email="two@x.com", age_verified=True)
        order = create_order(api, c1["id"], ctx["bottling_run"]["id"], channel="THREE_TIER", cases=1)
        resp = api.pay_order(order["id"], make_customer_headers(c2["id"]))
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN.value)

    def test_request_without_role_header_unauthenticated(self, api):
        """PRD 2.1: "If `X-User-Role` is missing or is not one of the recognized roles,
        the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."

        Design: Corner/rbac/request_without_role_header_returns_unauthenticated
        """
        resp = api.list_distilleries(TEST_USERS["anonymous_headers"])
        validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED.value)
