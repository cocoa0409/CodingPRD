"""Warehouse receipts: issuance guards (custody, capacity, segregation of
duties), cancel compensation, stored-count conservation, and the logical
clock's default date."""
from test_helpers import (
    ApiErrorId,
    CLOCK_DEFAULT_ISO,
    TEST_USERS,
    assert_instant_equal,
    bales_by_tag,
    create_grower,
    create_module,
    create_shift,
    create_warehouse,
    create_warehouse_receipt_payload,
    get_bale,
    get_receipt,
    get_warehouse,
    gin_module,
    issue_receipt,
    list_receipts,
    make_warehouse_manager_headers,
    pledge_receipt,
    setup_classed_bale,
    setup_ginned_bale,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["admin_headers"]
OPERATOR = TEST_USERS["gin_operator_headers"]
WM = TEST_USERS["warehouse_manager_headers"]
ACCOUNTANT = TEST_USERS["accountant_headers"]


class TestSegregationOfDuties:
    def test_ginner_cannot_issue_own_receipt(self, api):
        """PRD: "And the segregation-of-duties rule forbids the acting operator
        from being the one who ginned the module: if the request's `X-User-ID`
        equals the bale's module's `ginned_by_user_id`, the issuance fails with
        `ERR_SEGREGATION_OF_DUTIES` (HTTP 403)."
        PRD: "A successful issuance creates the receipt `ACTIVE` with a
        server-minted unique `receipt_number`"

        Design: Corner/rbac/sod_ginner_cannot_issue_own_receipt
        """
        ctx = setup_ginned_bale(membership_number="MB-C70", legal_name="SoD Farm",
                                bale_tag="B-SD1", stand_label="STAND-SD",
                                operator_user_id="gin-op-9")
        warehouse = create_warehouse("WH-SD", capacity_bales=5, dock_count=1)
        bale = ctx["bale"]

        forbidden = api.create_warehouse_receipt(
            create_warehouse_receipt_payload(bale["id"], warehouse["id"]),
            make_warehouse_manager_headers("gin-op-9"))
        validate_error(forbidden, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)

        receipt = validate_success(api.create_warehouse_receipt(
            create_warehouse_receipt_payload(bale["id"], warehouse["id"]),
            make_warehouse_manager_headers("wm-2")), expected_status=201)
        assert receipt["status"] == "ACTIVE", (
            "the check is on the user id, not the WarehouseManager role")


class TestCapacityBoundary:
    def _setup(self):
        grower = create_grower("MB-701", "Capacity Farm")
        warehouse = create_warehouse("WH-TINY", capacity_bales=1, dock_count=1)
        shift = create_shift("2026", "STAND-K")
        module = create_module(grower["id"], ticket_number="T-1", module_tag="MT-C")
        gin_module(module["id"], shift["id"], [("B-C1", 400), ("B-C2", 400)])
        bales = bales_by_tag(module["id"])
        return grower, warehouse, bales["B-C1"], bales["B-C2"]

    def test_issue_succeeds_at_capacity_minus_one(self, api):
        """PRD: "The warehouse must have room: issuance when
        `stored_bale_count` equals `capacity_bales` is rejected with
        `ERR_WAREHOUSE_AT_CAPACITY` (HTTP 422) — at capacity exactly is
        rejected."
        PRD: "the warehouse's `stored_bale_count` increases by one"

        Design: Difficulty/boundary_precision_check/warehouse_capacity_exact_full_boundary
        """
        _grower, warehouse, b1, _b2 = self._setup()
        receipt = validate_success(api.create_warehouse_receipt(
            create_warehouse_receipt_payload(b1["id"], warehouse["id"]),
            make_warehouse_manager_headers("wm-1")), expected_status=201)
        assert receipt["status"] == "ACTIVE"
        assert get_warehouse(warehouse["id"])["stored_bale_count"] == 1

    def test_issue_rejected_at_exact_capacity(self, api):
        """PRD: "issuance when `stored_bale_count` equals `capacity_bales` is
        rejected with `ERR_WAREHOUSE_AT_CAPACITY` (HTTP 422) — at capacity
        exactly is rejected."

        Design: Difficulty/boundary_precision_check/warehouse_capacity_exact_full_boundary
        """
        _grower, warehouse, b1, b2 = self._setup()
        issue_receipt(b1["id"], warehouse["id"], wm_user_id="wm-1")

        resp = api.create_warehouse_receipt(
            create_warehouse_receipt_payload(b2["id"], warehouse["id"]),
            make_warehouse_manager_headers("wm-1"))
        validate_error(resp, ApiErrorId.ERR_WAREHOUSE_AT_CAPACITY)
        assert get_bale(b2["id"])["custody_status"] == "ON_GIN_FLOOR"
        assert list_receipts(bale_id=b2["id"]) == []


class TestIssueCancelConservation:
    def _setup(self):
        grower = create_grower("MB-910", "Conserve Farm")
        warehouse = create_warehouse("WH-I", capacity_bales=10, dock_count=1)
        shift = create_shift("2026", "STAND-O")
        module = create_module(grower["id"], ticket_number="T-1", module_tag="MT-I")
        gin_module(module["id"], shift["id"], [("B-I1", 500)])
        bale = bales_by_tag(module["id"])["B-I1"]
        return grower, warehouse, bale

    def test_issue_increments_count_and_moves_custody(self, api):
        """PRD: "A successful issuance creates the receipt `ACTIVE` with a
        server-minted unique `receipt_number` and a `storage_start_date` taken
        from the logical clock date — free-day counting starts there. The
        bale's `custody_status` flips to `WAREHOUSED`, the warehouse's
        `stored_bale_count` increases by one, and the warehouse's `version`
        increments."

        Design: Difficulty/compensating_invariant/receipt_issue_cancel_conserve_stored_count
        """
        _grower, warehouse, bale = self._setup()
        receipt = issue_receipt(bale["id"], warehouse["id"], wm_user_id="wm-1")
        assert receipt["status"] == "ACTIVE"
        assert get_warehouse(warehouse["id"])["stored_bale_count"] == 1
        assert get_bale(bale["id"])["custody_status"] == "WAREHOUSED"

    def test_cancel_restores_count_and_custody(self, api):
        """PRD: "Cancellation moves the receipt to terminal `CANCELLED`,
        returns the bale's custody to `ON_GIN_FLOOR`, and decrements the
        warehouse's `stored_bale_count` by one."
        PRD: "A `Warehouse`'s `stored_bale_count` is likewise read-only: it
        counts that warehouse's receipts whose `status` is `ACTIVE`,
        `PLEDGED`, or `RELEASED`, starting at 0 when the warehouse is
        commissioned."

        Design: Difficulty/compensating_invariant/receipt_issue_cancel_conserve_stored_count
        """
        _grower, warehouse, bale = self._setup()
        receipt = issue_receipt(bale["id"], warehouse["id"], wm_user_id="wm-1")
        cancelled = validate_success(
            api.cancel_warehouse_receipt(receipt["id"], WM))
        assert cancelled["status"] == "CANCELLED"
        # the issue/cancel pair leaves the warehouse exactly as before
        assert get_warehouse(warehouse["id"])["stored_bale_count"] == 0
        assert get_bale(bale["id"])["custody_status"] == "ON_GIN_FLOOR"
        assert list_receipts(bale_id=bale["id"], status="ACTIVE") == []


class TestReceiptGuards:
    def test_double_issue_rejected(self, api):
        """PRD: "The bale's custody must be `ON_GIN_FLOOR` with no existing
        receipt in `ACTIVE`, `PLEDGED`, or `RELEASED` status for that bale —
        otherwise `ERR_RECEIPT_NOT_ISSUABLE` (HTTP 409)"

        Design: Corner/state_machines/receipt_double_issue_rejected
        """
        grower = create_grower("MB-C17", "Double Farm")
        warehouse = create_warehouse("WH-DB", capacity_bales=5, dock_count=1)
        shift = create_shift("2026", "STAND-DB")
        module = create_module(grower["id"], ticket_number="T-1", module_tag="MT-DB")
        gin_module(module["id"], shift["id"], [("B-DB1", 500)])
        bale = bales_by_tag(module["id"])["B-DB1"]
        issue_receipt(bale["id"], warehouse["id"], wm_user_id="wm-1")

        resp = api.create_warehouse_receipt(
            create_warehouse_receipt_payload(bale["id"], warehouse["id"]),
            make_warehouse_manager_headers("wm-1"))
        validate_error(resp, ApiErrorId.ERR_RECEIPT_NOT_ISSUABLE)
        assert len(list_receipts(bale_id=bale["id"])) == 1
        assert get_warehouse(warehouse["id"])["stored_bale_count"] == 1

    def test_cancel_from_pledged_rejected(self, api):
        """PRD: "Cancelling undoes an issuance. The receipt must be `ACTIVE`
        (else `ERR_RECEIPT_NOT_CANCELLABLE`, HTTP 409)."

        Design: Corner/state_machines/receipt_cancel_from_pledged_rejected
        """
        ctx = setup_classed_bale(membership_number="MB-C18",
                                 legal_name="Pledge Farm", bale_tag="B-PC1",
                                 stand_label="STAND-PC")
        warehouse = create_warehouse("WH-PC", capacity_bales=5, dock_count=1)
        receipt = issue_receipt(ctx["bale"]["id"], warehouse["id"],
                                wm_user_id="wm-1")
        pledge_receipt(receipt["id"])

        resp = api.cancel_warehouse_receipt(receipt["id"], WM)
        validate_error(resp, ApiErrorId.ERR_RECEIPT_NOT_CANCELLABLE)
        assert get_receipt(receipt["id"])["status"] == "PLEDGED"
        assert get_warehouse(warehouse["id"])["stored_bale_count"] == 1


class TestClockDefault:
    def test_receipt_storage_start_uses_default_logical_clock(self, api):
        """PRD: "Before any clock call is made, the logical clock reads exactly
        `2026-08-01T00:00:00Z`."
        PRD: "A successful issuance creates the receipt `ACTIVE` with a
        server-minted unique `receipt_number` and a `storage_start_date` taken
        from the logical clock date — free-day counting starts there."
        PRD: "All date-stamping in the system — `storage_start_date`,
        `pledged_date`, `redeemed_date`, `ginned_at`, and every day count
        behind storage and interest accrual — reads a logical clock, never
        wall-clock time."

        Design: Corner/endpoints/clock_default_date_applied_to_receipt
        """
        ctx = setup_ginned_bale(membership_number="MB-C61", legal_name="Clock Farm",
                                bale_tag="B-CK1", stand_label="STAND-CK")
        warehouse = create_warehouse("WH-CK", capacity_bales=5, dock_count=1)
        receipt = issue_receipt(ctx["bale"]["id"], warehouse["id"],
                                wm_user_id="wm-1")
        assert_instant_equal(receipt["storage_start_date"], CLOCK_DEFAULT_ISO)
        assert isinstance(receipt["receipt_number"], str) and receipt["receipt_number"]
        assert receipt["status"] == "ACTIVE"
