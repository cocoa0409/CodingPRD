"""Part catalogue CRUD, access control, pagination, and computed reads.

Breadth coverage of the entities/errors/validations/endpoints surface from
PRD 3.1, 3.3, 2.1, 2.3.
"""
from test_helpers import (
    validate_success, validate_error, validate_paginated, ApiErrorId,
    TEST_USERS, factories, get_success_data, fixtures, NON_EXISTENT_UUID,
    assert_part,
)

DESIGNER = TEST_USERS["designer_headers"]
SUPPLIER_MGR = TEST_USERS["supplier_manager_headers"]
VIEWER = TEST_USERS["viewer_headers"]


class TestPartCreation:
    def test_create_part_returns_201_with_fields(self, api):
        """PRD 3.1: "On creation the part's `revision_count` is 0 and its
        `released_revision_id` is null."
        PRD 2.4: "an integer `version` that begins at its initial value when the
        resource is created and increments by one on every mutation."

        Design: Corner/entities/create_part_returns_201_with_fields
        """
        resp = api.create_part(
            factories.create_part_payload("MAKE", part_number="MK1", name="Make One",
                                          base_cost_cents=1000), DESIGNER)
        data = validate_success(resp, expected_status=201)
        assert_part(data)
        assert data["version"] == 1, data
        assert data["revision_count"] == 0, data
        assert data["released_revision_id"] is None, data

    def test_get_part_returns_stored_entity(self, api):
        """PRD 3.1: "a descriptive `name`, and a `part_type` of `MAKE`, `BUY`, or
        `PHANTOM`."

        Design: Corner/entities/get_part_returns_stored_entity
        """
        created = get_success_data(api.create_part(
            factories.create_part_payload("MAKE", name="Make Two"), DESIGNER))
        data = validate_success(api.get_part(created["id"], VIEWER))
        assert data["part_number"] == created["part_number"]
        assert data["part_type"] == "MAKE"

    def test_list_parts_paginated_envelope(self, api):
        """PRD 2.3: "The `meta` object of a list response carries `limit`, `offset`,
        `total_count`, and `has_more`."

        Design: Corner/entities/list_parts_paginated_envelope
        """
        get_success_data(api.create_part(factories.create_part_payload("PHANTOM"), DESIGNER))
        data, meta = validate_paginated(api.list_parts(VIEWER))
        assert meta["total_count"] >= 1, meta
        assert isinstance(meta["has_more"], bool), meta
        assert isinstance(data, list)

    def test_get_part_not_found(self, api):
        """PRD 2.6: "the system validates those identifiers left to right and rejects
        the request with `ERR_NOT_FOUND` at the first identifier that does not resolve
        to an existing resource."

        Design: Corner/entities/get_part_not_found
        """
        resp = api.get_part(NON_EXISTENT_UUID, VIEWER)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND)

    def test_create_part_missing_part_type_invalid_request(self, api):
        """PRD 3.1: "a descriptive `name`, and a `part_type` of `MAKE`, `BUY`, or
        `PHANTOM`."

        Design: Corner/entities/create_part_missing_required_returns_invalid_request
        """
        resp = api.create_part({"part_number": "MK4", "name": "No Type"}, DESIGNER)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)

    def test_buy_part_without_supplier_invalid_request(self, api):
        """PRD 3.1: "Supplying a supplier for a non-`BUY` part, or omitting it for a
        `BUY` part, is rejected with `ERR_INVALID_REQUEST`."

        Design: Corner/entities/buy_part_without_supplier_returns_invalid_request
        """
        resp = api.create_part(
            {"part_number": "BUYNOSUP", "name": "Buy No Sup", "part_type": "BUY",
             "base_cost_cents": 500}, DESIGNER)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)

    def test_make_part_with_supplier_invalid_request(self, api):
        """PRD 3.1: "a `MAKE` or `PHANTOM` part must omit it (leave it null)."
        PRD 3.1: "Supplying a supplier for a non-`BUY` part, or omitting it for a `BUY`
        part, is rejected with `ERR_INVALID_REQUEST`."

        Design: Corner/entities/make_part_with_supplier_returns_invalid_request
        """
        sup = fixtures.create_supplier()
        resp = api.create_part(
            {"part_number": "MAKESUP", "name": "Make Sup", "part_type": "MAKE",
             "default_supplier_id": sup["id"]}, DESIGNER)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)

    def test_duplicate_part_number_invalid_request(self, api):
        """PRD 3.1: "a `part_number` (uppercased, unique across all parts — a collision
        yields `ERR_INVALID_REQUEST`)".

        Design: Corner/entities/duplicate_part_number_returns_invalid_request
        """
        get_success_data(api.create_part(
            factories.create_part_payload("PHANTOM", part_number="DUPNUM", name="First"),
            DESIGNER))
        resp = api.create_part(
            factories.create_part_payload("PHANTOM", part_number="DUPNUM", name="Second"),
            DESIGNER)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)

    def test_revision_count_increments_released_stays_null(self, api):
        """PRD 3.1: "The latter is a computed pointer to the single revision of this
        part currently in the `RELEASED` state, recomputed every time a revision of the
        part is released or obsoleted; the former is a computed count of the part's
        revisions."

        Design: Corner/entities/computed_revision_count_and_released_revision
        """
        part = fixtures.create_part("MAKE", base_cost_cents=0)
        fixtures.create_revision(part["id"])
        data = validate_success(api.get_part(part["id"], VIEWER))
        assert data["revision_count"] == 1, data
        assert data["released_revision_id"] is None, data


class TestAccessControl:
    def test_missing_auth_header_rejected(self, api):
        """PRD 2.1: "If either header is missing or malformed, the request is rejected
        with `ERR_MISSING_AUTH_HEADER`."

        Design: Corner/errors/missing_auth_header_rejected
        """
        resp = api.list_parts({})  # no auth headers
        validate_error(resp, ApiErrorId.ERR_MISSING_AUTH_HEADER)

    def test_viewer_cannot_create_part(self, api):
        """PRD 2.1: "When the headers are present but the declared role is not permitted
        to perform the requested operation, the request is rejected with
        `ERR_FORBIDDEN_FOR_ROLE`."

        Design: Corner/errors/forbidden_role_on_create_part
        """
        resp = api.create_part(
            factories.create_part_payload("PHANTOM", part_number="VIEW-P", name="ViewPart"),
            VIEWER)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_FOR_ROLE)


class TestPagination:
    def test_limit_below_min_rejected(self, api):
        """PRD 2.3: "A request whose `limit` is below 1 or above 100, or whose `offset`
        is negative, is rejected with `ERR_VALIDATION`."

        Design: Corner/validations/pagination_limit_out_of_range
        """
        resp = api.list_parts(VIEWER, params={"limit": 0})
        validate_error(resp, ApiErrorId.ERR_VALIDATION)


class TestComputedReads:
    def test_bom_lines_filtered_by_child_part(self, api):
        """PRD 3.2: "the full BOM-line collection can be filtered by `child_part_id`
        (this is precisely the where-used edge query) and by `parent_revision_id`."

        Design: Corner/endpoints/where_used_bomline_filter_reverse_reachability
        """
        leaf = fixtures.create_buy_part(base_cost_cents=10)
        part = fixtures.create_part("MAKE", base_cost_cents=0)
        rev = fixtures.create_revision(part["id"])
        fixtures.add_bom_line(rev["id"], leaf["id"], 3)
        rows, _meta = validate_paginated(
            api.list_bom_lines(VIEWER, params={"child_part_id": leaf["id"]}))
        assert len(rows) == 1, rows
        assert rows[0]["parent_revision_id"] == rev["id"], rows[0]
        assert rows[0]["quantity"] == 3, rows[0]

    def test_buy_leaf_cost_is_base_cost(self, api):
        """PRD 3.3: "For a revision whose part is of type `BUY`, the cost is simply that
        part's `base_cost_cents` — a `BUY` part is a purchased leaf."
        PRD 3.3: "A dedicated read returns both figures together, echoing the
        `part_revision_id` alongside `planned_cost_cents` and `effective_cost_cents`."

        Design: Corner/endpoints/simple_buy_leaf_cost_read
        """
        leaf = fixtures.create_buy_part(base_cost_cents=700)
        rev = fixtures.create_revision(leaf["id"])
        cost = validate_success(api.get_revision_cost(rev["id"], VIEWER))
        assert cost["planned_cost_cents"] == 700, cost
        assert cost["effective_cost_cents"] == 700, cost
