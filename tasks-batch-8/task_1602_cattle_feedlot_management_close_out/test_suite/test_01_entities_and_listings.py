"""Entity creation defaults, uniqueness constraints, existence checks, and
list-endpoint envelope/pagination behavior."""
from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    TEST_USERS,
    assert_lot,
    assert_lot_head_conservation,
    assert_owner,
    create_assignment_payload,
    create_lot_payload,
    create_owner,
    create_owner_payload,
    create_pen,
    get_success_data,
    validate_error,
    validate_paginated,
    validate_success,
)

FYM = TEST_USERS["feedyard_manager_headers"]
ANY = TEST_USERS["any_headers"]


class TestOwnerCreation:
    def test_owner_create_applies_defaults(self, api):
        """PRD §3.1: "A `FeedyardManager` registers an owner by supplying an
        `owner_name` and a `billing_email`; the new owner starts in `ACTIVE`
        status with an `outstanding_balance_cents` of zero."
        PRD §2.4: "`version` (integer): a system-managed integer that increments
        by one with every modification to the resource"

        Design: Corner/entities/owner_create_applies_defaults
        """
        resp = api.create_owner(
            create_owner_payload(owner_name="O-ENT", billing_email="ent@x.com"),
            FYM,
        )
        owner = validate_success(resp, 201)
        assert_owner(owner)
        assert owner["status"] == "ACTIVE", "A new owner starts ACTIVE"
        assert owner["outstanding_balance_cents"] == 0
        assert owner["version"] == 1, "A new owner is born with version 1"


class TestLotCreation:
    def test_lot_create_derives_counters_and_defaults(self, api):
        """PRD §3.1: "A `FeedyardManager` receives a lot by naming its
        `owner_id`, a yard-unique `lot_number` ..., and optionally
        `commingle_allowed`, which defaults to `false` when omitted."
        PRD §3.1: "The lot is born `OPEN`: `head_count_current` is initialized to
        `head_count_in` ... and `provisional_cog_cents_per_cwt` is null until the
        first clock day has passed and a projected gain exists."

        Design: Corner/entities/lot_create_derives_counters_and_defaults
        """
        owner = create_owner(owner_name="O-ENT2", billing_email="ent2@x.com")
        resp = api.create_lot(
            create_lot_payload(
                owner["id"], lot_number="L-ENT2", sex_class="STEER",
                head_count_in=5, in_weight_total_lbs=3500,
                purchase_cost_cents=700000, arrival_date="2026-08-01",
            ),
            FYM,
        )
        lot = validate_success(resp, 201)
        assert_lot(lot)
        assert_lot_head_conservation(lot)
        assert lot["head_count_current"] == 5, (
            "head_count_current derives from head_count_in at reception"
        )
        assert lot["commingle_allowed"] is False, "Omitted flag defaults to false"
        assert lot["status"] == "OPEN"
        assert lot["provisional_cog_cents_per_cwt"] is None, (
            "Zero days on feed at the default clock means no projected gain, "
            "so the provisional cost of gain is null"
        )

    def test_lot_computed_field_input_ignored(self, api):
        """PRD §3.1: "A `FeedyardManager` receives a lot by naming its
        `owner_id`, a yard-unique `lot_number` ..., the `arrival_date`, and
        optionally `commingle_allowed`" — head_count_current is not among the
        named inputs.
        PRD §3.1: "The lot is born `OPEN`: `head_count_current` is initialized to
        `head_count_in`"

        Design: Corner/entities/lot_computed_field_input_ignored
        """
        owner = create_owner(owner_name="O-ENT3", billing_email="ent3@x.com")
        payload = create_lot_payload(
            owner["id"], lot_number="L-ENT3", sex_class="STEER",
            head_count_in=5, in_weight_total_lbs=3500,
            purchase_cost_cents=700000, arrival_date="2026-08-01",
        )
        payload["head_count_current"] = 999
        lot = validate_success(api.create_lot(payload, FYM), 201)
        assert lot["head_count_current"] == 5, (
            "The server-computed head_count_current wins over any client-supplied value"
        )


class TestUniqueness:
    def test_pen_code_uniqueness_rejected(self, api):
        """PRD §3.1: "Creating a pen takes a `pen_code` — a yard-unique code such
        as \"B-12\", with duplicates rejected as `ERR_DUPLICATE_PEN_CODE`
        (HTTP 409) — and a `capacity_head` greater than zero."

        Design: Corner/entities/pen_code_uniqueness_rejected
        """
        create_pen(pen_code="K-01", capacity_head=50)
        resp = api.create_pen(
            {"pen_code": "K-01", "capacity_head": 80}, FYM)
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_PEN_CODE)

    def test_lot_number_uniqueness_rejected(self, api):
        """PRD §3.1: "A `FeedyardManager` receives a lot by naming its
        `owner_id`, a yard-unique `lot_number` (duplicates rejected with
        `ERR_DUPLICATE_LOT_NUMBER`), the `sex_class` (`STEER` or `HEIFER`)"

        Design: Corner/entities/lot_number_uniqueness_rejected
        """
        owner1 = create_owner(owner_name="O-DUP1", billing_email="d1@x.com")
        owner2 = create_owner(owner_name="O-DUP2", billing_email="d2@x.com")
        get_success_data(api.create_lot(
            create_lot_payload(owner1["id"], lot_number="L-DUP"), FYM))
        resp = api.create_lot(
            create_lot_payload(
                owner2["id"], lot_number="L-DUP", sex_class="HEIFER",
                head_count_in=3, in_weight_total_lbs=2100,
                purchase_cost_cents=420000, arrival_date="2026-08-01"),
            FYM,
        )
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_LOT_NUMBER)


class TestExistence:
    def test_get_unknown_lot_returns_404(self, api):
        """PRD §2.8: "Resource identifiers in the path are validated left to
        right, and foreign-key identifiers in the body must also exist; the first
        missing resource yields its specific 404 error — `ERR_OWNER_NOT_FOUND`,
        `ERR_PEN_NOT_FOUND`, `ERR_LOT_NOT_FOUND`, ..."

        Design: Corner/entities/get_unknown_lot_returns_404
        """
        resp = api.get_lot(NON_EXISTENT_UUID, ANY)
        validate_error(resp, ApiErrorId.ERR_LOT_NOT_FOUND)

    def test_assignment_body_fk_unknown_pen_returns_404(self, api):
        """PRD §2.8: "Resource identifiers in the path are validated left to
        right, and foreign-key identifiers in the body must also exist; the first
        missing resource yields its specific 404 error"

        Design: Corner/entities/assignment_body_fk_unknown_pen_returns_404
        """
        owner = create_owner(owner_name="O-FK", billing_email="fk@x.com")
        lot = get_success_data(api.create_lot(
            create_lot_payload(owner["id"], lot_number="L-FK"), FYM))
        resp = api.create_assignment(
            create_assignment_payload(NON_EXISTENT_UUID, lot["id"], head_count=5,
                                      start_date="2026-08-01"),
            FYM,
        )
        validate_error(resp, ApiErrorId.ERR_PEN_NOT_FOUND)


class TestListPagination:
    def test_list_pagination_envelope_shape(self, api):
        """PRD §2.3: "Unless otherwise specified, all list endpoints return
        resources sorted by their creation timestamp in ascending order."
        PRD §2.3: "Paginated list responses include the following fields in the
        `meta` object of the response envelope: `limit`, `offset`, `total_count`,
        and `has_more`."
        PRD §2.2: "The `response_type` is either \"object\" for a single resource
        or \"array\" for a list of resources."

        Design: Corner/entities/list_pagination_envelope_shape
        """
        for code in ("P-ENUM-1", "P-ENUM-2", "P-ENUM-3"):
            create_pen(pen_code=code, capacity_head=50)

        resp = api.list_pens(ANY, params={"limit": 2, "offset": 2})
        data, meta = validate_paginated(resp)
        assert resp.json()["response_type"] == "array"
        assert len(data) == 1, "limit=2 offset=2 over 3 pens yields exactly one row"
        assert data[0]["pen_code"] == "P-ENUM-3", (
            "created_at ascending: the third-created pen is the last row"
        )
        assert meta["total_count"] == 3
        assert meta["has_more"] is False
        assert meta["limit"] == 2
        assert meta["offset"] == 2
        assert isinstance(resp.json()["meta"]["api_request_id"], str)
        assert isinstance(resp.json()["meta"]["api_request_timestamp"], str)
