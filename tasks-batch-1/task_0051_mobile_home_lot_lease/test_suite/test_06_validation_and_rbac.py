"""Cross-cutting concerns: creation defaults, not-found / invalid-request
validation, cross-community and duplicate constraints, pagination, and RBAC.
"""
from test_helpers import (
    validate_success,
    validate_error,
    validate_paginated,
    get_success_data,
    ApiErrorId,
    TEST_USERS,
    make_resident_headers,
    fixtures as fx,
)
from test_helpers.constants import NONEXISTENT_UUID

MGR = TEST_USERS["manager_headers"]


class TestEntityDefaults:
    def test_create_community_defaults(self, api):
        """PRD §3.1: "At creation the community's `ownership_model` is set to
        `PARK_OWNED` and its `occupied_lot_count` starts at zero."
        PRD §3.1: "The `utility_apportionment_method` is either `PER_CAPITA` or
        `SUB_METER`, defaulting to `PER_CAPITA` when omitted"

        Design: Corner/entities/create_community_returns_201_with_defaults
        """
        resp = api.create_community(
            fx.f.create_community_payload(name="Solo Park", state_code="FL"), MGR
        )
        data = validate_success(resp, expected_status=201)
        assert data["ownership_model"] == "PARK_OWNED"
        assert data["utility_apportionment_method"] == "PER_CAPITA"
        assert data["occupied_lot_count"] == 0
        assert data["version"] == 1

    def test_lot_defaults_vacant_and_current_rent_equals_base(self, api):
        """PRD §3.1: "A newly created lot begins in `VACANT` status with
        `current_lease_id` null and `current_rent_cents` equal to
        `base_rent_cents`."

        Design: Corner/entities/lot_status_defaults_vacant_current_rent_equals_base
        """
        community = fx.create_community(api, state_code="CA", name="Def Park")
        resp = api.create_lot(
            fx.f.create_lot_payload(community["id"], lot_number="Z2", base_rent_cents=72000), MGR
        )
        data = validate_success(resp, expected_status=201)
        assert data["status"] == "VACANT"
        assert data["current_rent_cents"] == 72000


class TestNotFoundAndInvalidRequest:
    def test_get_nonexistent_lot_returns_not_found(self, api):
        """PRD §2.6: "The first identifier that does not resolve to an existing
        resource causes immediate rejection with `ERR_NOT_FOUND` (HTTP 404),
        before any later identifier or business rule is evaluated."

        Design: Corner/entities/get_nonexistent_lot_returns_not_found
        """
        resp = api.get_lot(NONEXISTENT_UUID, MGR)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value)

    def test_create_lot_missing_base_rent_rejected(self, api):
        """PRD §2.6: "All required body fields must be present and well-typed, and
        any enum-valued field must carry a value from its permitted set; a
        violation yields `ERR_INVALID_REQUEST` (HTTP 400)."

        Design: Corner/entities/create_lot_missing_base_rent_returns_invalid_request
        """
        community = fx.create_community(api, state_code="CA", name="Req Park")
        resp = api.create_lot({"community_id": community["id"], "lot_number": "Z1"}, MGR)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)

    def test_create_community_invalid_state_code_rejected(self, api):
        """PRD §3.1: "The `state_code` is one of `CA`, `OR`, `FL`, or `TX`, and it
        selects the annual rent-increase cap regime described in §3.4."

        Design: Corner/entities/create_lot_invalid_state_code_enum_rejected
        """
        resp = api.create_community(
            fx.f.create_community_payload(name="Bad Park", state_code="ZZ"), MGR
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)


class TestReferentialConstraints:
    def test_cross_community_lease_reference_rejected(self, api):
        """PRD §2.6: "when creating a lease, a utility bill, or a conversion
        ballot, the referenced lot, resident, and lease must all belong to the
        same community. A cross-community reference is rejected with
        `ERR_CROSS_COMMUNITY_REFERENCE` (HTTP 409)."

        Design: Corner/validations/cross_community_lease_reference_rejected
        """
        comm1 = fx.create_community(api, state_code="CA", name="C1")
        comm2 = fx.create_community(api, state_code="CA", name="C2")
        lot = fx.create_lot(comm1["id"], api, lot_number="CC", base_rent_cents=60000)
        resident = fx.create_resident(comm2["id"], api, full_name="RCC")
        resp = api.create_lease(fx.f.create_lease_payload(lot["id"], resident["id"]), MGR)
        validate_error(resp, ApiErrorId.ERR_CROSS_COMMUNITY_REFERENCE.value)

    def test_duplicate_lot_number_rejected(self, api):
        """PRD §3.1: "The `lot_number` is a human-readable label that must be
        unique within its community; a duplicate is rejected with
        `ERR_DUPLICATE_LOT_NUMBER` (HTTP 409)."

        Design: Corner/validations/duplicate_lot_number_within_community_rejected
        """
        community = fx.create_community(api, state_code="CA", name="Dup Park")
        fx.create_lot(community["id"], api, lot_number="A1", base_rent_cents=60000)
        resp = api.create_lot(
            fx.f.create_lot_payload(community["id"], lot_number="A1", base_rent_cents=70000), MGR
        )
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_LOT_NUMBER.value)


class TestPagination:
    def test_list_lots_filtered_and_paginated(self, api):
        """PRD §2.3: "Paginated list responses include the following fields in the
        `meta` object of the response envelope: `limit`, `offset`, `total_count`,
        and `has_more`."

        Design: Corner/endpoints/list_lots_filtered_by_community_paginated
        """
        community = fx.create_community(api, state_code="CA", name="Lst Park")
        fx.create_lot(community["id"], api, lot_number="L1", base_rent_cents=60000)
        fx.create_lot(community["id"], api, lot_number="L2", base_rent_cents=60000)
        resp = api.list_lots(MGR, params={"community_id": community["id"], "limit": 1, "offset": 0})
        data, meta = validate_paginated(resp)
        assert meta["total_count"] == 2
        assert meta["has_more"] is True
        assert len(data) == 1


class TestRbac:
    def test_resident_cannot_create_lot(self, api):
        """PRD §2.1: "When the header is present and recognized but the named role
        is not permitted to perform the requested operation under the access
        matrix, the request is rejected with `ERR_FORBIDDEN` (HTTP 403)."

        Design: Corner/rbac/resident_cannot_create_lot
        """
        community = fx.create_community(api, state_code="CA", name="Rb Park")
        resident = fx.create_resident(community["id"], api, full_name="RRb")
        resp = api.create_lot(
            fx.f.create_lot_payload(community["id"], lot_number="RB", base_rent_cents=60000),
            make_resident_headers(resident["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN.value)

    def test_manager_cannot_accept_rent_schedule(self, api):
        """PRD §4: "All write operations are restricted to the roles shown".
        PRD §3.4: "The `Resident` may accept the proposal, taking it from
        `PROPOSED → ACCEPTED`, or contest it".

        Design: Corner/rbac/manager_cannot_accept_rent_schedule
        """
        community = fx.create_community(api, state_code="CA", name="Pm Park")
        lot = fx.create_lot(community["id"], api, lot_number="PM", base_rent_cents=60000)
        sched = fx.propose_rent_schedule(
            lot["id"], api=api, proposed_rent_cents=61000, effective_date="2027-01-01"
        )
        resp = api.accept_rent_schedule(sched["id"], MGR)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN.value)

    def test_missing_role_header_unauthenticated(self, api):
        """PRD §2.1: "If `X-User-Role` is missing or does not name a recognized
        role, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."

        Design: Corner/rbac/missing_role_header_unauthenticated
        """
        headers = {"X-User-ID": "anon-1", "Content-Type": "application/json"}
        resp = api.get_community(NONEXISTENT_UUID, headers)
        validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED.value)

    def test_housing_authority_can_read_community(self, api):
        """PRD §2.1: "A `HousingAuthority` may invoke any GET endpoint and nothing
        else."

        Design: Corner/rbac/housing_authority_read_only_get_succeeds
        """
        community = fx.create_community(api, state_code="CA", name="Ha Park")
        resp = api.get_community(community["id"], TEST_USERS["authority_headers"])
        data = validate_success(resp, expected_status=200)
        assert data["ownership_model"] == "PARK_OWNED"
