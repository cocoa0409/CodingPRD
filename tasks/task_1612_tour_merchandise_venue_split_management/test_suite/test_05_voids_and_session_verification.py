"""Sale voids, the cash-variance gate, segregation of duties at verify, and
the recount loop."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    count_out_session,
    get_allocation,
    get_session,
    get_success_data,
    make_seller_headers,
    record_sale,
    setup_selling_show,
    staff_session,
    validate_error,
    verify_payload,
    verify_session,
)

TM1 = TEST_USERS["tour_manager_headers"]


class TestSaleThenVoidInvariant:
    def _world_with_sale(self, api):
        world = setup_selling_show(tour_name="CI1 Tour", city="Chico",
                                   venue_name="CI1 Hall",
                                   show_date="2026-08-27T20:00:00Z",
                                   total_units=100, num_sellers=1)
        seller = world["sellers"][0]
        session = staff_session(world, count_out=False)
        sale = record_sale(session["id"], world["allocation"]["id"], 10,
                           "CASH", seller["id"])
        return world, seller, session, sale

    def test_void_restores_expected_cash_and_allocation(self, api):
        """PRD §3.4: "The drawer's expected contents are always derivable: a
        session's `expected_cash_cents` is its `cash_float_cents` plus the sum
        of `gross_cents` over the session's `ACTIVE` sale records tendered
        `CASH` — card sales never enter the drawer, and voided records drop out
        of the expectation."
        PRD §3.8: "The allocation's `quantity_sold` is recomputed over `ACTIVE`
        records only, immediately restoring `quantity_on_hand`. The session's
        `expected_cash_cents` is recomputed as well; and when the session is
        already `COUNTED_OUT`, `cash_variance_cents` is recomputed against the
        recorded `counted_cash_cents`, so an audit void can push a previously
        passing drawer over the tolerance — the session will then need a recount
        via the reject loop or a manager's `variance_override` at verify time,
        as laid out in §3.4."

        Design: Difficulty/compensating_invariant/sale_then_void_leaves_expected_cash_unchanged
        """
        world, seller, session, sale = self._world_with_sale(api)
        assert get_session(session["id"])["expected_cash_cents"] == 45000, (
            "5000 float + 40000 cash sale")
        assert get_allocation(world["allocation"]["id"])["quantity_sold"] == 10

        get_success_data(api.void_sale_record(
            sale["id"], {"void_reason": "miskeyed quantity"},
            make_seller_headers(seller["id"])))

        assert get_session(session["id"])["expected_cash_cents"] == 5000, (
            "the void restores the float baseline exactly")
        allocation = get_allocation(world["allocation"]["id"])
        assert allocation["quantity_sold"] == 0
        assert allocation["quantity_on_hand"] == 100

    def test_void_records_reason_and_actor(self, api):
        """PRD §3.8: "Under either path the record must still be `ACTIVE` —
        voiding a `VOIDED` record fails with `ERR_ALREADY_TERMINAL` — and an
        optional `void_reason` may accompany the request; the system stamps
        `voided_by_user_id` and moves the record to `VOIDED`."

        Design: Difficulty/compensating_invariant/sale_then_void_leaves_expected_cash_unchanged
        """
        _world, seller, _session, sale = self._world_with_sale(api)

        voided = get_success_data(api.void_sale_record(
            sale["id"], {"void_reason": "miskeyed quantity"},
            make_seller_headers(seller["id"])))
        assert voided["status"] == "VOIDED"
        assert voided["void_reason"] == "miskeyed quantity"
        assert voided["voided_by_user_id"] == seller["id"]


def test_sale_record_void_twice_rejected(api):
    """PRD §3.8: "Under either path the record must still be `ACTIVE` — voiding
    a `VOIDED` record fails with `ERR_ALREADY_TERMINAL` — and an optional
    `void_reason` may accompany the request; the system stamps
    `voided_by_user_id` and moves the record to `VOIDED`."

    Design: Corner/state_machines/sale_record_void_twice_rejected
    """
    world = setup_selling_show(tour_name="SM4 Tour", city="Visalia",
                               venue_name="SM4 Hall",
                               show_date="2026-09-01T20:00:00Z",
                               total_units=50, num_sellers=1)
    seller = world["sellers"][0]
    session = staff_session(world, count_out=False)
    sale = record_sale(session["id"], world["allocation"]["id"], 2, "CASH",
                       seller["id"])
    get_success_data(api.void_sale_record(sale["id"], {"void_reason": "miskey"},
                                          make_seller_headers(seller["id"])))

    resp = api.void_sale_record(sale["id"], {"void_reason": "again"},
                                make_seller_headers(seller["id"]))
    validate_error(resp, ApiErrorId.ERR_ALREADY_TERMINAL)
    assert get_allocation(world["allocation"]["id"])["quantity_sold"] == 0, (
        "a single reversal only")


def test_seller_cannot_void_others_record(api):
    """PRD §3.8: "A `Seller` may void a record from their own session while that
    session is still `OPEN` — a record belonging to another seller's session
    fails with `ERR_NOT_RESOURCE_OWNER`, and a session already counted out fails
    with `ERR_SESSION_NOT_OPEN`."
    PRD §2.1: "When `X-User-Role` is `Seller`, `X-User-ID` is the `id` of the
    acting `Seller`; ownership checks on any resource that references a `Seller`
    — a `SellerSession` through its `seller_id`, or a `SaleRecord` through the
    session it was recorded in — compare the resource's foreign-key field to
    `X-User-ID`, and a mismatch is rejected with `ERR_NOT_RESOURCE_OWNER`
    (HTTP 403)."

    Design: Corner/rbac/seller_cannot_void_others_record
    """
    world = setup_selling_show(tour_name="RB4 Tour", city="Gillette",
                               venue_name="RB4 Hall",
                               show_date="2026-09-20T20:00:00Z",
                               total_units=50, num_sellers=2)
    seller_a, seller_b = world["sellers"]
    session = staff_session(world, seller_index=0, count_out=False)
    sale = record_sale(session["id"], world["allocation"]["id"], 1, "CASH",
                       seller_a["id"])

    resp = api.void_sale_record(sale["id"], {"void_reason": "not my drawer"},
                                make_seller_headers(seller_b["id"]))
    validate_error(resp, ApiErrorId.ERR_NOT_RESOURCE_OWNER)
    assert get_success_data(api.get_sale_record(sale["id"], TM1))["status"] == "ACTIVE"


def test_verify_own_session_rejected_sod(api):
    """PRD §3.4: "A `Seller` verifying a colleague's drawer, or a `TourManager`,
    acts on a `COUNTED_OUT` session (otherwise `ERR_SESSION_NOT_COUNTED_OUT`)
    while the parent show is `OPEN` or `RECONCILING` (otherwise
    `ERR_INVALID_SHOW_STATE`), and the verifier's `X-User-ID` must differ from
    the session's `seller_id` (otherwise `ERR_SEGREGATION_OF_DUTIES`)."

    Design: Corner/validations/verify_own_session_rejected_sod
    """
    world = setup_selling_show(tour_name="VA4 Tour", city="Jamestown",
                               venue_name="VA4 Hall",
                               show_date="2026-09-09T20:00:00Z", num_sellers=1)
    seller = world["sellers"][0]
    session = staff_session(world, counted_cash_cents=5000)
    assert session["cash_variance_cents"] == 0

    resp = api.verify_session(session["id"], verify_payload("APPROVE"),
                              make_seller_headers(seller["id"]))
    validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)
    assert get_session(session["id"])["status"] == "COUNTED_OUT"


class TestVarianceToleranceBoundary:
    def _world_with_variance(self, api, counted_cash_cents):
        world = setup_selling_show(tour_name="BP1 Tour", city="Topeka",
                                   venue_name="BP1 Hall",
                                   show_date="2026-08-22T20:00:00Z",
                                   total_units=1000, num_sellers=3)
        seller_a = world["sellers"][0]
        session = staff_session(
            world, seller_index=0, sales=[(100, "CASH")],
            counted_cash_cents=counted_cash_cents, verify=False)
        assert get_session(session["id"])["expected_cash_cents"] == 405000
        return world, seller_a, session

    def test_variance_exactly_at_tolerance_verifies(self, api):
        """PRD §3.4: "With `decision` `APPROVE`, the variance gate applies: when
        the absolute `cash_variance_cents` is at or below the tour's
        `cash_variance_tolerance_cents` the approval goes through freely, but an
        absolute variance exceeding the tolerance — even by a single cent —
        requires `variance_override` set to true and the caller's role to be
        `TourManager`; a `Seller` has no override power, and an over-tolerance
        approval without a manager override is rejected with
        `ERR_VARIANCE_OVERRIDE_REQUIRED`."

        Design: Difficulty/boundary_precision_check/variance_exactly_at_tolerance_verifies
        """
        world, _seller_a, session = self._world_with_variance(api, 406000)
        verifier = world["sellers"][1]

        verified = verify_session(session["id"],
                                  make_seller_headers(verifier["id"]))
        assert verified["status"] == "VERIFIED", (
            "variance +1000 is exactly the tolerance: verifies with no override")
        assert verified["cash_variance_cents"] == 1000

    def test_variance_one_cent_over_tolerance_rejected(self, api):
        """PRD §3.4: "With `decision` `APPROVE`, the variance gate applies: when
        the absolute `cash_variance_cents` is at or below the tour's
        `cash_variance_tolerance_cents` the approval goes through freely, but an
        absolute variance exceeding the tolerance — even by a single cent —
        requires `variance_override` set to true and the caller's role to be
        `TourManager`; a `Seller` has no override power, and an over-tolerance
        approval without a manager override is rejected with
        `ERR_VARIANCE_OVERRIDE_REQUIRED`."

        Design: Difficulty/boundary_precision_check/variance_exactly_at_tolerance_verifies
        """
        world, _seller_a, session = self._world_with_variance(api, 406001)
        verifier = world["sellers"][1]

        resp = api.verify_session(session["id"], verify_payload("APPROVE"),
                                  make_seller_headers(verifier["id"]))
        validate_error(resp, ApiErrorId.ERR_VARIANCE_OVERRIDE_REQUIRED)
        assert get_session(session["id"])["status"] == "COUNTED_OUT", (
            "variance +1001 is tolerance + 1: rejected without an override")


def test_variance_override_only_tourmanager(api):
    """PRD §3.4: "With `decision` `APPROVE`, the variance gate applies: when the
    absolute `cash_variance_cents` is at or below the tour's
    `cash_variance_tolerance_cents` the approval goes through freely, but an
    absolute variance exceeding the tolerance — even by a single cent —
    requires `variance_override` set to true and the caller's role to be
    `TourManager`; a `Seller` has no override power, and an over-tolerance
    approval without a manager override is rejected with
    `ERR_VARIANCE_OVERRIDE_REQUIRED`."

    Design: Corner/complexity_layers/variance_override_only_tourmanager
    """
    world = setup_selling_show(tour_name="CC6 Tour", city="Moab",
                               venue_name="CC6 Hall",
                               show_date="2026-09-22T20:00:00Z",
                               total_units=200, num_sellers=2)
    seller_b = world["sellers"][1]
    session = staff_session(world, seller_index=0, sales=[(100, "CASH")],
                            counted_cash_cents=410000, verify=False)
    assert get_session(session["id"])["cash_variance_cents"] == 5000

    resp = api.verify_session(
        session["id"], verify_payload("APPROVE", variance_override=True),
        make_seller_headers(seller_b["id"]))
    validate_error(resp, ApiErrorId.ERR_VARIANCE_OVERRIDE_REQUIRED)

    verified = verify_session(session["id"], TM1, variance_override=True)
    assert verified["status"] == "VERIFIED", (
        "only a TourManager override verifies an over-tolerance drawer")


class TestSellerSessionRecountLoop:
    def _counted_out_world(self, api):
        world = setup_selling_show(
            tour_name="NL2 Tour", city="Tulsa", venue_name="NL2 Pavilion",
            show_date="2026-08-17T20:00:00Z", price_cents=2000,
            total_units=100, num_sellers=2,
            product_overrides={"sku": "NL2-CAP", "name": "Cap",
                               "base_price_cents": 2000,
                               "initial_stock_by_size": {"OS": 500}})
        session = staff_session(world, seller_index=0, sales=[(5, "CASH")],
                                counted_cash_cents=14000, verify=False)
        assert get_session(session["id"])["expected_cash_cents"] == 15000
        return world, session

    def test_reject_reverts_to_open_for_recount(self, api):
        """PRD §3.4: "With `decision` `REJECT`, the session returns to `OPEN`
        for a recount: `recount_count` increments by one, and both
        `counted_cash_cents` and `cash_variance_cents` are cleared back to null
        until the next count-out."

        Design: Difficulty/non_linear_state_machine/seller_session_recount_loop
        """
        world, session = self._counted_out_world(api)
        verifier = world["sellers"][1]

        rejected = verify_session(session["id"],
                                  make_seller_headers(verifier["id"]),
                                  decision="REJECT")
        assert rejected["status"] == "OPEN"
        assert rejected["recount_count"] == 1
        assert rejected["counted_cash_cents"] is None
        assert rejected["cash_variance_cents"] is None

    def test_recount_then_approve_reaches_verified(self, api):
        """PRD §3.4: "Count-out moves the session from `OPEN` to `COUNTED_OUT`
        and computes `cash_variance_cents` as `counted_cash_cents` minus
        `expected_cash_cents`; until the first count-out the variance is null."
        PRD §3.4: "A successful approval stamps `verified_by_user_id` with the
        verifier's identity and moves the session to `VERIFIED`."

        Design: Difficulty/non_linear_state_machine/seller_session_recount_loop
        """
        world, session = self._counted_out_world(api)
        seller_a, verifier = world["sellers"][0], world["sellers"][1]
        verify_session(session["id"], make_seller_headers(verifier["id"]),
                       decision="REJECT")

        recounted = count_out_session(session["id"], 15000, seller_a["id"])
        assert recounted["status"] == "COUNTED_OUT"
        assert recounted["cash_variance_cents"] == 0, (
            "15000 counted vs 15000 expected")

        verified = verify_session(session["id"],
                                  make_seller_headers(verifier["id"]))
        assert verified["status"] == "VERIFIED"
        assert verified["verified_by_user_id"] == verifier["id"]
