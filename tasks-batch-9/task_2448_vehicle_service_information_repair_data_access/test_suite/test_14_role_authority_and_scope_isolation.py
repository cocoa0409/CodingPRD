"""Who may act: exclusive operations, authentication, entity-backed scope, duties.

Covers the catalogue operations reserved to one role, authentication ahead of
authorization, a shop manager confined to its own shop, a technician confined to
its own seat, the publisher who may not publish what it validated, and a shared
read open to three roles but closed to the fourth.
"""

from test_helpers import (
    COMPLIANCE_OFFICER_1_USER_ID,
    CONTENT_PUBLISHER_1_USER_ID,
    CONTENT_PUBLISHER_2_USER_ID,
    NO_HEADERS,
    UNKNOWN_ROLE_HEADERS,
    ApiErrorId,
    DistributionStatus,
    EntitlementStatus,
    ParityStatus,
    ReviewStatus,
    SeatStatus,
    SessionStatus,
    SettlementStatus,
    ShopTier,
    ToolStatus,
    assert_credential_token_derived_from_session,
    assert_entitlement,
    assert_gateway_session,
    assert_manufacturer,
    assert_seat_assignment,
    assert_seat_counts,
    factories,
    fixtures,
    make_compliance_officer_headers,
    make_content_publisher_headers,
    make_platform_admin_headers,
    make_shop_manager_headers,
    make_technician_headers,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestCatalogueOperationsAreReservedToOneRole:
    """Minting an OEM and minting a system area are both PlatformAdmin work."""

    def test_a_manager_and_a_publisher_are_both_refused_the_admin_catalogue(self, api):
        """Two wrong roles get 403; the owning role's identical payload is accepted.

        PRD 2.1: "When both headers are well-formed but the declared role does not
        appear in the authorized-role list of the endpoint being addressed (see §4),
        the rejection is `ERR_UNAUTHORIZED` (HTTP 403)." PRD 4 authorizes only
        `PlatformAdmin` to "Register an OEM together with the two pricing offers
        that its right-to-repair parity is judged on; stamps parity_index and
        parity_status under LIST_BASIS" and to "Register a vehicle system area used
        as the system axis of coverage cells and as a charge line of a license".

        Design: Corner/rbac/rbac_shop_manager_cannot_create_manufacturer_unauthorized
        """
        admin = make_platform_admin_headers()
        shop = validate_success(api.create_shop(factories.shop_payload(), admin), 201)
        manager = make_shop_manager_headers(shop["id"])
        publisher = make_content_publisher_headers(CONTENT_PUBLISHER_1_USER_ID)

        validate_error(
            api.create_manufacturer(factories.manufacturer_payload(), manager),
            ApiErrorId.UNAUTHORIZED,
            403,
        )
        validate_error(
            api.create_system_area(factories.system_area_payload(), publisher),
            ApiErrorId.UNAUTHORIZED,
            403,
        )

        manufacturer = validate_success(
            api.create_manufacturer(factories.manufacturer_payload(), admin), 201
        )
        assert_manufacturer(manufacturer)
        assert manufacturer["oem_code"] == "ACME"
        assert manufacturer["parity_status"] == ParityStatus.COMPLIANT


class TestAuthenticationIsCheckedBeforeAuthorization:
    """A missing role and an undeclared role both read as 401, never 403."""

    def test_no_headers_and_an_undeclared_role_both_answer_unauthenticated(self, api):
        """The same URL is 401 twice and then 200 under a declared role.

        PRD 2.1: "Every request to every endpoint must carry two headers:
        `X-User-ID`, identifying the caller, and `X-User-Role`, declaring the
        capacity in which the caller is acting. Exactly five roles exist, spelled
        as follows: `PlatformAdmin`, `ContentPublisher`, `ComplianceOfficer`,
        `ShopManager`, and `Technician`. If either header is absent, or if
        `X-User-Role` holds any string other than one of those five, the request is
        rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."

        Design: Corner/rbac/rbac_missing_or_unknown_role_header_returns_4XX_unauthenticated
        """
        admin = make_platform_admin_headers()
        shop = validate_success(api.create_shop(factories.shop_payload(), admin), 201)

        validate_error(
            api.get_shop(shop["id"], NO_HEADERS), ApiErrorId.UNAUTHENTICATED, 401
        )
        undeclared = validate_error(
            api.get_shop(shop["id"], UNKNOWN_ROLE_HEADERS),
            ApiErrorId.UNAUTHENTICATED,
            401,
        )
        assert undeclared["error_id"] != ApiErrorId.UNAUTHORIZED

        read = validate_success(api.get_shop(shop["id"], admin))
        assert read["name"] == "Bay Auto"
        assert read["tier"] == ShopTier.PRO


class TestAShopManagerIsConfinedToItsOwnShop:
    """The rival manager is refused both the write and the read."""

    def test_a_foreign_manager_cannot_seat_or_read_another_shops_roster(self, api):
        """Two cross-shop attempts are 403; the owning manager's seating succeeds.

        PRD 2.1: "When `X-User-Role` is `ShopManager`, `X-User-ID` is the `id` of
        the acting `Shop`; ownership checks on any resource that references a `Shop`
        compare the resource's shop-identifying field to `X-User-ID`. A
        `ShopManager` may therefore address only its own shop, and a mismatch is
        rejected with `ERR_CROSS_SHOP_ACCESS` (HTTP 403)", on eleven operations
        including "seating a technician" and "listing the shop's technicians"; "For
        the seat and entitlement operations, the compared value is the `shop_id`
        recorded on the `ShopEntitlement` the request targets." PRD 3.5: "A
        successful seating recomputes the entitlement's seat ledger, advances the
        entitlement's `version` by 1, appends a `SEAT_ASSIGNED` audit row, and
        answers 201."

        Design: Corner/rbac/rbac_shop_manager_cannot_touch_another_shops_entitlement_or_roster
        """
        ctx = fixtures.build_entitled_shop(api, covered_area_codes=("POWERTRAIN",))
        fixtures.add_technician(api, ctx, key="main", full_name="Tina Tech")
        rival = fixtures.add_second_shop(
            api, ctx, name="Rival Repair", tier=ShopTier.BASIC
        )
        rival_technician = validate_success(
            api.create_technician(
                factories.technician_payload(
                    rival["shop"]["id"], full_name="Bob Rival"
                ),
                rival["headers"],
            ),
            201,
        )
        entitlement = fixtures.refresh_entitlement(api, ctx)

        validate_error(
            api.create_seat_assignment(
                factories.seat_assignment_payload(
                    entitlement["id"], rival_technician["id"], entitlement["version"]
                ),
                rival["headers"],
            ),
            ApiErrorId.CROSS_SHOP_ACCESS,
            403,
        )
        validate_error(
            api.list_shop_technicians(ctx["shop"]["id"], rival["headers"]),
            ApiErrorId.CROSS_SHOP_ACCESS,
            403,
        )

        seat = validate_success(
            api.create_seat_assignment(
                factories.seat_assignment_payload(
                    entitlement["id"],
                    ctx["technicians"]["main"]["id"],
                    entitlement["version"],
                ),
                ctx["manager_headers"],
            ),
            201,
        )
        assert_seat_assignment(seat)
        assert seat["status"] == SeatStatus.ACTIVE

        after = fixtures.refresh_entitlement(api, ctx)
        assert_seat_counts(after, 1, 2)
        assert after["version"] == 3


class TestATechnicianIsConfinedToItsOwnSeat:
    """Sharing an entitlement is not sharing a session."""

    def test_a_colleague_cannot_activate_the_seat_holders_session(self, api):
        """The colleague is 403; only the holder's own call mints the token.

        PRD 2.1: "When `X-User-Role` is `Technician`, `X-User-ID` is the `id` of the
        acting `Technician`; ownership checks compare the seat holder recorded on
        the addressed seat to `X-User-ID`. A technician may act only through a seat
        assigned to itself, and a mismatch is rejected with `ERR_NOT_SEAT_HOLDER`
        (HTTP 403)", and that "applies to seven operations: requesting a gateway
        session, activating one". PRD 3.7 then mints the token "as the literal
        prefix `GW-` followed by the first eight hexadecimal characters of the
        session's own `id`, upper-cased" and moves the tool "to `OCCUPIED` with
        `occupied_by_session_id` set to this session".

        Design: Corner/rbac/rbac_technician_cannot_activate_another_technicians_session
        """
        ctx = fixtures.build_two_seated_technicians(
            api, second_name="Raj Wrench", covered_area_codes=("POWERTRAIN",)
        )
        fixtures.add_session(
            api, ctx, key="main", technician_key="main", tool_key="main", activate=False
        )
        session_id = ctx["sessions"]["main"]["id"]

        validate_error(
            api.activate_gateway_session(session_id, ctx["tech_headers"]["second"]),
            ApiErrorId.NOT_SEAT_HOLDER,
            403,
        )

        activated = validate_success(
            api.activate_gateway_session(session_id, ctx["tech_headers"]["main"])
        )
        assert_gateway_session(activated)
        assert activated["status"] == SessionStatus.ACTIVE
        assert_credential_token_derived_from_session(activated)

        tools, meta = validate_paginated(
            api.list_shop_diagnostic_tools(
                ctx["shop"]["id"], ctx["manager_headers"], {"status": ToolStatus.OCCUPIED}
            )
        )
        assert meta["total_count"] == 1
        assert tools[0]["id"] == ctx["tools"]["main"]["id"]
        assert tools[0]["occupied_by_session_id"] == session_id

        entitlement = fixtures.refresh_entitlement(api, ctx)
        assert_seat_counts(entitlement, 2, 1)


class TestValidationAndPublicationNeedTwoPublishers:
    """The reviewer may not wave its own work out of the door."""

    def test_the_validating_publisher_cannot_publish_but_a_colleague_can(self, api):
        """The self-publish is 403 and leaves the version WITHHELD.

        PRD 2.1: "Publishing a version is refused when the acting
        `ContentPublisher` is the same operator who validated it: if the version's
        `validated_by_user_id` is not null and equals the publishing request's
        `X-User-ID`, the platform returns `ERR_SEGREGATION_OF_DUTIES` (HTTP 403).
        Moving a version through both validation and publication therefore requires
        two distinct `ContentPublisher` operator identifiers." PRD 3.6: "On success
        `distribution_status` becomes `PUBLISHED`, `published_by_user_id` records
        the acting publisher, the parent publication's `published_version_id` is
        repointed at this version".

        Design: Corner/rbac/rbac_segregation_of_duties_same_publisher_cannot_validate_then_publish
        """
        ctx = fixtures.build_catalogue(api, area_codes=("POWERTRAIN",))
        fixtures.add_publication_version(
            api, ctx, validate=True, publish=False, author_user_id=CONTENT_PUBLISHER_1_USER_ID
        )
        version_id = ctx["versions"]["main"]["id"]

        validate_error(
            api.publish_publication_version(
                version_id, make_content_publisher_headers(CONTENT_PUBLISHER_1_USER_ID)
            ),
            ApiErrorId.SEGREGATION_OF_DUTIES,
            403,
        )

        withheld = fixtures.refresh_version(api, ctx)
        assert withheld["distribution_status"] == DistributionStatus.WITHHELD
        assert withheld["published_by_user_id"] is None

        published = validate_success(
            api.publish_publication_version(
                version_id, make_content_publisher_headers(CONTENT_PUBLISHER_2_USER_ID)
            )
        )
        assert published["distribution_status"] == DistributionStatus.PUBLISHED
        assert published["review_status"] == ReviewStatus.VALIDATED
        assert published["validated_by_user_id"] == CONTENT_PUBLISHER_1_USER_ID
        assert published["published_by_user_id"] == CONTENT_PUBLISHER_2_USER_ID

        publication = validate_success(
            api.get_publication(
                ctx["publications"]["main"]["id"], make_platform_admin_headers()
            )
        )
        assert publication["published_version_id"] == version_id


class TestOneReadShapeAcrossThreeRolesAndOneRefusal:
    """Three authorized roles read the same row; the fourth is not on the list."""

    def test_three_roles_read_one_entitlement_identically_and_a_technician_cannot(
        self, api
    ):
        """Admin, officer and owning manager agree field by field; technician is 403.

        PRD 4 opens the read of one entitlement — "Read one entitlement including
        its charge, settlement and seat ledger fields" — to `PlatformAdmin`,
        `ComplianceOfficer`, `ShopManager`, and PRD 2.1 refuses any role not on
        that list: "When both headers are well-formed but the declared role does
        not appear in the authorized-role list of the endpoint being addressed (see
        §4), the rejection is `ERR_UNAUTHORIZED` (HTTP 403)."

        Design: Corner/rbac/rbac_shared_read_open_to_admin_compliance_and_owning_manager_technician_unauthorized
        """
        ctx = fixtures.build_entitled_shop(api, covered_area_codes=("POWERTRAIN",))
        fixtures.add_technician(api, ctx, key="main", full_name="Tina Tech")
        entitlement_id = ctx["entitlement"]["id"]

        as_admin = validate_success(
            api.get_entitlement(entitlement_id, make_platform_admin_headers())
        )
        as_officer = validate_success(
            api.get_entitlement(
                entitlement_id,
                make_compliance_officer_headers(COMPLIANCE_OFFICER_1_USER_ID),
            )
        )
        as_manager = validate_success(
            api.get_entitlement(entitlement_id, ctx["manager_headers"])
        )

        assert_entitlement(as_admin)
        assert as_admin["status"] == EntitlementStatus.ACTIVE
        assert as_officer["charged_cents"] == 85000
        assert as_manager["seats_available"] == 3

        shared_fields = (
            "status",
            "charged_cents",
            "settlement_status",
            "seats_assigned",
            "seats_available",
        )
        for field in shared_fields:
            assert as_admin[field] == as_officer[field] == as_manager[field]
        assert as_admin["settlement_status"] == SettlementStatus.UNSETTLED
        assert_seat_counts(as_admin, 0, 3)

        validate_error(
            api.get_entitlement(
                entitlement_id,
                make_technician_headers(ctx["technicians"]["main"]["id"]),
            ),
            ApiErrorId.UNAUTHORIZED,
            403,
        )
