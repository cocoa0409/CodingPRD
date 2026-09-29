"""Service order lifecycle.

Covers the two independent status dimensions carried by one ServiceOrder row,
the show-status gate on order creation, the closed floor-occupancy window on a
booth, the billing-status list filter and the booth optimistic-concurrency
parent version.
"""
from test_helpers import (
    BASE_CLOCK,
    TEST_USERS,
    TWO_LINE_ORDER,
    ApiErrorId,
    advance_fulfillment,
    advance_show,
    assert_service_order,
    assert_service_order_waterfall,
    booth_version,
    create_booth,
    create_exhibitor,
    create_service_order_payload,
    create_show,
    create_venue,
    get_booth,
    get_order,
    issue_invoice,
    make_exhibitor_headers,
    open_invoice,
    place_order,
    service_order_line,
    set_clock,
    setup_draft_invoice,
    setup_show_ground,
    validate_error,
    validate_paginated,
    validate_success,
)

OPS_HEADERS = TEST_USERS["show_operations_headers"]
FINANCE_HEADERS = TEST_USERS["finance_controller_headers"]

# The floor window occupied by the first install/dismantle crew, and the second
# window that starts at the exact instant the first one ends.
FIRST_WINDOW_START = "2026-09-19T08:00:00Z"
FIRST_WINDOW_END = "2026-09-19T12:00:00Z"
TOUCHING_WINDOW_START = "2026-09-19T12:00:00Z"
TOUCHING_WINDOW_END = "2026-09-19T16:00:00Z"

INSTALL_LINES = [service_order_line(1, "ID-CREW", 1, 50000, 0)]
CLEANING_LINES = [service_order_line(1, "CLN-VAC", 2, 75000, 0)]


def _ground_with_booth_assigned_after_the_show_opens():
    """Venue, show already walked to OPEN_FOR_ORDERS, exhibitor, then the booth.

    The booth is assigned last so that nothing has written it since it was
    minted and its version is unambiguously the value a freshly created row
    carries.
    """
    set_clock(BASE_CLOCK)
    venue = create_venue()
    show = create_show(venue["id"])
    advance_show(show["id"], "OPEN_FOR_ORDERS")
    exhibitor = create_exhibitor()
    booth = create_booth(show["id"], exhibitor["id"])
    return {"venue": venue, "show": show, "exhibitor": exhibitor, "booth": booth}


class TestServiceOrderParallelDimensions:
    """fulfillment_status and billing_status advance independently."""

    def test_fulfillment_walks_to_scheduled_without_touching_billing_status(self):
        """PENDING -> CONFIRMED -> SCHEDULED leaves billing_status at UNBILLED
        on every hop.

        PRD: "Once written, a service order carries two status dimensions that advance completely independently of one another."
        PRD: "Naming a `to_status` — optionally with an explanatory `note` — advances it: `PENDING → CONFIRMED` requires the show to be in one of the four ordering statuses above and the booth not to be `FROZEN`, and leaves `billing_status` untouched; `CONFIRMED → SCHEDULED` requires the booth not to be `FROZEN` and bumps the order's `version`; `SCHEDULED → DELIVERED` requires the show to be in `MOVE_IN`, `ON_SITE` or `MOVE_OUT`, and once delivered the order is no longer eligible as a change-order target."
        Design: Difficulty/non_linear_state_machine/service_order_parallel_fulfillment_and_billing_dimensions
        """
        ground = setup_draft_invoice()
        order = ground["order"]
        assert order["fulfillment_status"] == "PENDING", \
            "A newly written service order begins at PENDING"
        assert order["billing_status"] == "UNBILLED", \
            "A newly written service order begins at UNBILLED"

        confirmed = advance_fulfillment(order["id"], "CONFIRMED")
        assert confirmed["fulfillment_status"] == "CONFIRMED", \
            f"Expected CONFIRMED, got {confirmed['fulfillment_status']}"
        assert confirmed["billing_status"] == "UNBILLED", \
            "PENDING -> CONFIRMED leaves billing_status untouched at UNBILLED, " \
            f"got {confirmed['billing_status']}"

        scheduled = advance_fulfillment(order["id"], "SCHEDULED")
        assert scheduled["fulfillment_status"] == "SCHEDULED", \
            f"Expected SCHEDULED, got {scheduled['fulfillment_status']}"
        assert scheduled["billing_status"] == "UNBILLED", \
            "CONFIRMED -> SCHEDULED leaves billing_status untouched at UNBILLED, " \
            f"got {scheduled['billing_status']}"
        assert_service_order(scheduled)

    def test_issuing_the_invoice_moves_billing_only_and_leaves_fulfillment_scheduled(self):
        """Issuing the sweeping invoice drives billing_status to INVOICED and
        sets invoice_id, while fulfillment_status stays exactly SCHEDULED.

        PRD: "It advances to `INVOICED` when an invoice listing this order is issued, at which point the order's `invoice_id` is set and `fulfillment_status` is left untouched."
        Design: Difficulty/non_linear_state_machine/service_order_parallel_fulfillment_and_billing_dimensions
        """
        ground = setup_draft_invoice()
        order = ground["order"]
        invoice_id = ground["invoice"]["id"]
        advance_fulfillment(order["id"], "CONFIRMED")
        advance_fulfillment(order["id"], "SCHEDULED")

        issue_invoice(invoice_id)

        settled_view = get_order(order["id"])
        assert settled_view["billing_status"] == "INVOICED", \
            "Issuing an invoice listing the order moves billing_status to INVOICED, " \
            f"got {settled_view['billing_status']}"
        assert settled_view["invoice_id"] == invoice_id, \
            f"Expected invoice_id {invoice_id}, got {settled_view['invoice_id']}"
        assert settled_view["fulfillment_status"] == "SCHEDULED", \
            "The billing dimension advancing must not disturb fulfillment_status, " \
            f"got {settled_view['fulfillment_status']}"

    def test_issued_invoice_total_equals_the_swept_order_total(self):
        """The invoice sweeping the single order carries that order's own
        total_cents of 193858.

        PRD: "`subtotal_cents` is the sum of `total_cents` across the listed orders as of issue time; `total_cents` is `subtotal_cents` plus `adjustments_cents`, where `adjustments_cents` is the running sum of applied change-order price deltas and refurbishment credits."
        Design: Difficulty/non_linear_state_machine/service_order_parallel_fulfillment_and_billing_dimensions
        """
        ground = setup_draft_invoice()
        order = ground["order"]
        advance_fulfillment(order["id"], "CONFIRMED")
        advance_fulfillment(order["id"], "SCHEDULED")

        issued = issue_invoice(ground["invoice"]["id"])

        assert issued["total_cents"] == 193858, \
            f"Expected invoice total_cents 193858, got {issued['total_cents']}"
        assert get_order(order["id"])["total_cents"] == 193858, \
            "The swept order's own total_cents is the invoice subtotal"


class TestServiceOrderCreationGatedByDraftShow:
    """A booth may exist on a DRAFT show, but no order may be placed on it."""

    def test_order_against_a_booth_on_a_draft_show_is_refused(self, api):
        """The show reached from the booth is still DRAFT, so creation is
        refused with ERR_SHOW_NOT_ACCEPTING at HTTP 409.

        PRD: "The show reached from the booth must be in `OPEN_FOR_ORDERS`, `ADVANCE_CLOSED`, `MOVE_IN` or `ON_SITE`, or the request is refused with `ERR_SHOW_NOT_ACCEPTING`."
        PRD: "Shows are born in `DRAFT` with `committed_labor_hours` at 0 and `cancelled_labor_call_count` at 0, and their `status` is server-managed throughout."
        Design: Difficulty/cross_entity_state_dependency/service_order_creation_gated_by_draft_show
        """
        ground = setup_show_ground(show_status="DRAFT")
        assert ground["show"]["status"] == "DRAFT", \
            f"Expected the show to sit in DRAFT, got {ground['show']['status']}"
        booth_id = ground["booth"]["id"]
        payload = create_service_order_payload(booth_id, booth_version(booth_id))

        response = api.create_service_order(
            payload, make_exhibitor_headers(ground["exhibitor"]["id"]))

        validate_error(response, ApiErrorId.ERR_SHOW_NOT_ACCEPTING, 409)

    def test_refused_draft_show_order_writes_no_service_order_row(self, api):
        """The rejected creation leaves the booth with no service orders at all.

        PRD: "The show reached from the target is in a status that admits the operation — otherwise `ERR_SHOW_NOT_ACCEPTING` (409)."
        PRD: "Orders can be listed and filtered by `booth_id`, `invoice_id`, `fulfillment_status` and `billing_status`."
        Design: Difficulty/cross_entity_state_dependency/service_order_creation_gated_by_draft_show
        """
        ground = setup_show_ground(show_status="DRAFT")
        booth_id = ground["booth"]["id"]
        payload = create_service_order_payload(booth_id, booth_version(booth_id))
        response = api.create_service_order(
            payload, make_exhibitor_headers(ground["exhibitor"]["id"]))
        validate_error(response, ApiErrorId.ERR_SHOW_NOT_ACCEPTING, 409)

        rows, meta = validate_paginated(
            api.list_service_orders(OPS_HEADERS, params={"booth_id": booth_id}))

        assert meta["total_count"] == 0, \
            f"Expected 0 service orders on the booth, got {meta['total_count']}"
        assert rows == [], f"Expected an empty order list, got {rows}"


class TestBoothFloorWindowClosedInterval:
    """The floor-occupancy window is a closed interval, so touching collides."""

    @staticmethod
    def _ground_with_first_install_window():
        ground = setup_show_ground()
        ground["order"] = place_order(
            ground["booth"]["id"], ground["exhibitor"]["id"],
            lines=INSTALL_LINES,
            service_type="INSTALL_DISMANTLE",
            window_start=FIRST_WINDOW_START,
            window_end=FIRST_WINDOW_END)
        return ground

    def test_window_starting_at_the_first_windows_end_instant_collides(self, api):
        """A second install window opening at exactly the instant the live one
        closes is refused with ERR_BOOTH_WINDOW_CONFLICT at HTTP 409.

        PRD: "The requested floor window must not collide with any live window on the same booth: for every existing service order on that `booth_id` with a non-null window whose `fulfillment_status` is `PENDING`, `CONFIRMED`, `SCHEDULED` or `HELD`, the request is refused with `ERR_BOOTH_WINDOW_CONFLICT` when the new `window_start` is at or before that order's `window_end` **and** that order's `window_start` is at or before the new `window_end`."
        PRD: "Because the interval is closed, two windows that merely touch at an endpoint do collide."
        Design: Difficulty/resource_temporal_overlap/booth_floor_window_closed_interval_touch_rejects
        """
        ground = self._ground_with_first_install_window()
        booth_id = ground["booth"]["id"]
        payload = create_service_order_payload(
            booth_id, booth_version(booth_id),
            service_type="INSTALL_DISMANTLE",
            window_start=TOUCHING_WINDOW_START,
            window_end=TOUCHING_WINDOW_END,
            lines=INSTALL_LINES)

        response = api.create_service_order(
            payload, make_exhibitor_headers(ground["exhibitor"]["id"]))

        validate_error(response, ApiErrorId.ERR_BOOTH_WINDOW_CONFLICT, 409)

    def test_collided_window_request_leaves_a_single_order_on_the_booth(self, api):
        """The refused second window writes nothing: the booth still carries
        exactly the one install order.

        PRD: "That window is a **closed** interval — both endpoints count as occupied."
        PRD: "The requested floor window must not collide with any live window on the same booth: for every existing service order on that `booth_id` with a non-null window whose `fulfillment_status` is `PENDING`, `CONFIRMED`, `SCHEDULED` or `HELD`, the request is refused with `ERR_BOOTH_WINDOW_CONFLICT` when the new `window_start` is at or before that order's `window_end` **and** that order's `window_start` is at or before the new `window_end`."
        Design: Difficulty/resource_temporal_overlap/booth_floor_window_closed_interval_touch_rejects
        """
        ground = self._ground_with_first_install_window()
        booth_id = ground["booth"]["id"]
        payload = create_service_order_payload(
            booth_id, booth_version(booth_id),
            service_type="INSTALL_DISMANTLE",
            window_start=TOUCHING_WINDOW_START,
            window_end=TOUCHING_WINDOW_END,
            lines=INSTALL_LINES)
        response = api.create_service_order(
            payload, make_exhibitor_headers(ground["exhibitor"]["id"]))
        validate_error(response, ApiErrorId.ERR_BOOTH_WINDOW_CONFLICT, 409)

        rows, meta = validate_paginated(
            api.list_service_orders(OPS_HEADERS, params={"booth_id": booth_id}))

        assert meta["total_count"] == 1, \
            f"Expected exactly 1 service order on the booth, got {meta['total_count']}"
        assert [row["id"] for row in rows] == [ground["order"]["id"]], \
            "The surviving row must be the first install order"

    def test_first_install_order_holds_its_window_and_prices_at_53500(self):
        """The order that took the floor window is live, carries both window
        endpoints and prices to 53500 cents.

        PRD: "Two further inputs, `window_start` and `window_end`, declare the interval during which the crew will occupy the booth floor; they are mandatory when `service_type` is `RIGGING` or `INSTALL_DISMANTLE` and optional otherwise."
        PRD: "Step seven computes `total_cents` as `discounted_base_cents` plus `service_fee_cents`, again exact integer arithmetic."
        Design: Difficulty/resource_temporal_overlap/booth_floor_window_closed_interval_touch_rejects
        """
        ground = self._ground_with_first_install_window()

        order = get_order(ground["order"]["id"])

        assert order["service_type"] == "INSTALL_DISMANTLE", \
            f"Expected INSTALL_DISMANTLE, got {order['service_type']}"
        assert order["fulfillment_status"] == "PENDING", \
            "A live window is one held by a PENDING, CONFIRMED, SCHEDULED or HELD order"
        assert order["window_start"] is not None, \
            "An INSTALL_DISMANTLE order must store its window_start"
        assert order["window_end"] is not None, \
            "An INSTALL_DISMANTLE order must store its window_end"
        assert order["total_cents"] == 53500, \
            f"Expected total_cents 53500, got {order['total_cents']}"
        assert_service_order_waterfall(order)


class TestServiceOrderBillingStatusFilter:
    """GET /service-orders filters on the billing dimension."""

    @staticmethod
    def _ground_with_one_invoiced_and_one_unbilled_order():
        ground = setup_show_ground()
        booth_id = ground["booth"]["id"]
        exhibitor_id = ground["exhibitor"]["id"]
        ground["invoiced_order"] = place_order(booth_id, exhibitor_id,
                                               lines=TWO_LINE_ORDER)
        ground["unbilled_order"] = place_order(booth_id, exhibitor_id,
                                               lines=CLEANING_LINES,
                                               service_type="CLEANING")
        invoice = open_invoice(exhibitor_id, ground["show"]["id"],
                               [ground["invoiced_order"]["id"]])
        ground["invoice"] = issue_invoice(invoice["id"])
        return ground

    def test_billing_status_invoiced_filter_returns_only_the_invoiced_order(self, api):
        """Filtering the booth's orders on billing_status INVOICED returns the
        single order the issued invoice swept.

        PRD: "Orders can be listed and filtered by `booth_id`, `invoice_id`, `fulfillment_status` and `billing_status`."
        PRD: "It advances to `INVOICED` when an invoice listing this order is issued, at which point the order's `invoice_id` is set and `fulfillment_status` is left untouched."
        Design: Corner/endpoints/filtered_list_service_orders_by_billing_status
        """
        ground = self._ground_with_one_invoiced_and_one_unbilled_order()
        booth_id = ground["booth"]["id"]

        response = api.list_service_orders(
            FINANCE_HEADERS,
            params={"booth_id": booth_id, "billing_status": "INVOICED"})

        rows, meta = validate_paginated(response)
        assert response.json()["response_type"] == "array", \
            "A list endpoint answers with response_type array"
        assert meta["total_count"] == 1, \
            f"Expected exactly 1 INVOICED order, got {meta['total_count']}"
        assert [row["id"] for row in rows] == [ground["invoiced_order"]["id"]], \
            "Only the swept order carries billing_status INVOICED"
        assert rows[0]["billing_status"] == "INVOICED", \
            f"Expected INVOICED, got {rows[0]['billing_status']}"

    def test_billing_status_unbilled_filter_returns_only_the_uninvoiced_order(self, api):
        """The complementary filter returns the other order, and dropping the
        billing filter returns both.

        PRD: "The financial dimension, `billing_status`, begins at `UNBILLED` and is likewise never written directly by a client."
        PRD: "Orders can be listed and filtered by `booth_id`, `invoice_id`, `fulfillment_status` and `billing_status`."
        Design: Corner/endpoints/filtered_list_service_orders_by_billing_status
        """
        ground = self._ground_with_one_invoiced_and_one_unbilled_order()
        booth_id = ground["booth"]["id"]

        unbilled_rows, unbilled_meta = validate_paginated(api.list_service_orders(
            FINANCE_HEADERS,
            params={"booth_id": booth_id, "billing_status": "UNBILLED"}))

        assert unbilled_meta["total_count"] == 1, \
            f"Expected exactly 1 UNBILLED order, got {unbilled_meta['total_count']}"
        assert [row["id"] for row in unbilled_rows] == [ground["unbilled_order"]["id"]], \
            "Only the order no invoice swept carries billing_status UNBILLED"

        all_rows, all_meta = validate_paginated(api.list_service_orders(
            FINANCE_HEADERS, params={"booth_id": booth_id}))
        assert all_meta["total_count"] == 2, \
            f"Expected 2 orders on the booth without the filter, got {all_meta['total_count']}"
        assert {row["id"] for row in all_rows} == {ground["invoiced_order"]["id"],
                                                   ground["unbilled_order"]["id"]}, \
            "The unfiltered listing returns both booth orders"


class TestStaleBoothVersionOnServiceOrderCreate:
    """expected_booth_version pins the shared parent the order is written against."""

    def test_second_order_carrying_the_pre_order_booth_version_is_rejected(self, api):
        """A second creation still declaring the booth version read before the
        first order is refused with ERR_STALE_BOOTH_VERSION at HTTP 412, writes
        nothing, and leaves the booth version where the first order left it.

        PRD: "Creating a service order requires `expected_booth_version`, carrying the client's last observed `version` of the target `Booth`."
        PRD: "If the declared value does not equal the parent row's current `version` at the moment the write is processed, the write is rejected outright and no state changes."
        Design: Corner/cross_cutting_layers/occ_stale_booth_version_rejects_second_service_order
        """
        ground = _ground_with_booth_assigned_after_the_show_opens()
        booth_id = ground["booth"]["id"]
        exhibitor_id = ground["exhibitor"]["id"]
        stale_version = ground["booth"]["version"]
        first_order = place_order(booth_id, exhibitor_id, lines=TWO_LINE_ORDER,
                                  expected_booth_version=stale_version)

        response = api.create_service_order(
            create_service_order_payload(booth_id, stale_version,
                                         service_type="CLEANING",
                                         lines=CLEANING_LINES),
            make_exhibitor_headers(exhibitor_id))

        validate_error(response, ApiErrorId.ERR_STALE_BOOTH_VERSION, 412)
        rows, meta = validate_paginated(
            api.list_service_orders(OPS_HEADERS, params={"booth_id": booth_id}))
        assert meta["total_count"] == 1, \
            f"Expected exactly 1 service order to survive, got {meta['total_count']}"
        assert [row["id"] for row in rows] == [first_order["id"]], \
            "Only the first order may exist on the booth"
        assert get_booth(booth_id)["version"] == 2, \
            "The booth version stands at 2 after one order write and one rejection, " \
            f"got {get_booth(booth_id)['version']}"

    def test_resending_with_the_freshly_read_booth_version_succeeds(self, api):
        """Re-reading the booth and resending the same order with the current
        version is accepted with HTTP 201.

        PRD: "A mismatch is rejected with `ERR_STALE_BOOTH_VERSION` (HTTP 412)."
        PRD: "Writing the order is itself a mutation of the booth: a successful creation increments that booth's `version` by one, which is why two clients working from the same booth read cannot both succeed without one of them re-reading."
        Design: Corner/cross_cutting_layers/occ_stale_booth_version_rejects_second_service_order
        """
        ground = _ground_with_booth_assigned_after_the_show_opens()
        booth_id = ground["booth"]["id"]
        exhibitor_id = ground["exhibitor"]["id"]
        stale_version = ground["booth"]["version"]
        place_order(booth_id, exhibitor_id, lines=TWO_LINE_ORDER,
                    expected_booth_version=stale_version)
        rejected = api.create_service_order(
            create_service_order_payload(booth_id, stale_version,
                                         service_type="CLEANING",
                                         lines=CLEANING_LINES),
            make_exhibitor_headers(exhibitor_id))
        validate_error(rejected, ApiErrorId.ERR_STALE_BOOTH_VERSION, 412)

        retried = api.create_service_order(
            create_service_order_payload(booth_id, booth_version(booth_id),
                                         service_type="CLEANING",
                                         lines=CLEANING_LINES),
            make_exhibitor_headers(exhibitor_id))

        created = validate_success(retried, 201)
        assert_service_order(created)
        assert created["booth_id"] == booth_id, \
            "The retried order is written against the same booth"
        _, meta = validate_paginated(
            api.list_service_orders(OPS_HEADERS, params={"booth_id": booth_id}))
        assert meta["total_count"] == 2, \
            f"Expected 2 orders once the retry succeeds, got {meta['total_count']}"


class TestBoothVersionAdvancesOnEveryOrderWrite:
    """The optimistic-concurrency parent moves on every successful order."""

    def test_booth_version_climbs_one_step_per_successful_order(self):
        """The booth reads version 1 before any order, 2 after the first and 3
        after the second, each order pinned to the freshly read value.

        PRD: "Writing the order is itself a mutation of the booth: a successful creation increments that booth's `version` by one, which is why two clients working from the same booth read cannot both succeed without one of them re-reading."
        PRD: "`version` — an integer that begins at 1 when the row is created and increases by exactly 1 on every mutation of that row, again including server-initiated cascades."
        Design: Corner/cross_cutting_layers/booth_version_increments_on_every_order_write
        """
        ground = _ground_with_booth_assigned_after_the_show_opens()
        booth_id = ground["booth"]["id"]
        exhibitor_id = ground["exhibitor"]["id"]
        version_before_any_order = ground["booth"]["version"]
        assert version_before_any_order == 1, \
            f"A freshly assigned booth reads version 1, got {version_before_any_order}"

        place_order(booth_id, exhibitor_id, lines=TWO_LINE_ORDER,
                    expected_booth_version=version_before_any_order)
        version_after_first_order = booth_version(booth_id)
        assert version_after_first_order == 2, \
            f"Expected booth version 2 after one order, got {version_after_first_order}"

        place_order(booth_id, exhibitor_id, lines=CLEANING_LINES,
                    service_type="CLEANING",
                    expected_booth_version=version_after_first_order)
        version_after_second_order = booth_version(booth_id)
        assert version_after_second_order == 3, \
            f"Expected booth version 3 after two orders, got {version_after_second_order}"

    def test_both_orders_persist_and_price_independently(self, api):
        """Both orders survive on the booth and each carries its own total: the
        two-line electrical order at 193858 and the cleaning order at 154080.

        PRD: "`subtotal_cents` is the exact integer sum of the per-line rounded values."
        PRD: "Step two selects a volume-discount rate keyed on `subtotal_cents`: below 100000 cents the rate is zero; from 100000 up to but not including 500000 it is four percent; from 500000 up to but not including 1500000 it is seven percent; at 1500000 and above it is ten percent."
        Design: Corner/cross_cutting_layers/booth_version_increments_on_every_order_write
        """
        ground = _ground_with_booth_assigned_after_the_show_opens()
        booth_id = ground["booth"]["id"]
        exhibitor_id = ground["exhibitor"]["id"]

        electrical = place_order(booth_id, exhibitor_id, lines=TWO_LINE_ORDER,
                                 expected_booth_version=ground["booth"]["version"])
        cleaning = place_order(booth_id, exhibitor_id, lines=CLEANING_LINES,
                               service_type="CLEANING",
                               expected_booth_version=booth_version(booth_id))

        assert electrical["total_cents"] == 193858, \
            f"Expected the electrical order total 193858, got {electrical['total_cents']}"
        assert cleaning["total_cents"] == 154080, \
            f"Expected the cleaning order total 154080, got {cleaning['total_cents']}"
        assert_service_order_waterfall(electrical)
        assert_service_order_waterfall(cleaning)

        rows, meta = validate_paginated(
            api.list_service_orders(OPS_HEADERS, params={"booth_id": booth_id}))
        assert meta["total_count"] == 2, \
            f"Expected 2 orders on the booth, got {meta['total_count']}"
        assert {row["id"] for row in rows} == {electrical["id"], cleaning["id"]}, \
            "Both order writes persist against the same booth"
