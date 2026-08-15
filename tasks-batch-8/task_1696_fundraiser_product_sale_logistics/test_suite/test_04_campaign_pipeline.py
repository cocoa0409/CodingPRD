"""Campaign pipeline: close-ordering cascade, supplier aggregation and
case-pack rounding, the supplier-order revision loop, delivery, sort tickets,
mark-sorted, and distribution day."""
from test_helpers import (
    ApiErrorId,
    TEST_DEFAULTS,
    TEST_USERS,
    close_ordering_at_window_end,
    create_and_submit_order,
    create_distribution_event_payload,
    create_group,
    create_order,
    create_product,
    create_seller,
    create_submitted_paid_order,
    drive_campaign_to_delivered,
    drive_campaign_to_distribution_complete,
    generate_and_verify_tickets,
    get_success_data,
    record_and_clear_payment,
    reset_clock,
    setup_campaign_group_product,
    setup_open_campaign_with_seller,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["admin_headers"]
COORD = TEST_USERS["coordinator_headers"]
TREAS = TEST_USERS["treasurer_headers"]
SUPP = TEST_USERS["supplier_rep_headers"]


class TestCloseOrdering:
    def test_close_ordering_boundary_at_window_end(self, api):
        """PRD §3.3: "Once the order window has fully passed — the logical
        clock at or past `order_window_end`, else the close attempt is
        rejected with `ERR_ORDER_WINDOW_NOT_YET_CLOSED` — the admin closes
        ordering".

        Design: Corner/validations/close_ordering_boundary_at_window_end
        """
        reset_clock()
        campaign, _group, _product = setup_campaign_group_product()
        get_success_data(api.open_campaign(campaign["id"], ADMIN))
        reset_clock("2026-08-19T23:59:59Z")
        early = api.close_ordering(campaign["id"], ADMIN)
        validate_error(early, ApiErrorId.ERR_ORDER_WINDOW_NOT_YET_CLOSED)
        reset_clock(TEST_DEFAULTS["ORDER_WINDOW_END"])
        closed = get_success_data(api.close_ordering(campaign["id"], ADMIN))
        assert closed["status"] == "ORDERING_CLOSED", (
            "at exactly order_window_end the close succeeds (inclusive >=)")

    def test_close_ordering_cascades_draft_cancel_and_submit_lock(self, api):
        """PRD §3.3: "The cascade is immediate: every order still in `DRAFT`
        for the campaign is cancelled with no ledger impact, every `SUBMITTED`
        order moves to `LOCKED`".

        Design: Corner/state_machines/close_ordering_cascades_draft_cancel_and_submit_lock
        """
        reset_clock()
        campaign, group, product, seller = setup_open_campaign_with_seller()
        draft = create_order(seller["id"], product["id"], 1,
                             family_contact_name="Fam1")
        submitted = create_and_submit_order(seller["id"], product["id"], 2,
                                            family_contact_name="Fam2")
        close_ordering_at_window_end(campaign["id"])
        draft_after = get_success_data(api.get_order(draft["id"], COORD))
        submitted_after = get_success_data(api.get_order(submitted["id"], COORD))
        assert draft_after["status"] == "CANCELLED"
        assert submitted_after["status"] == "LOCKED"
        group_view = get_success_data(api.get_group(group["id"], TREAS))
        # round_half_up(2 * 400 * 5000/10000) == 400; the DRAFT cancellation
        # posts nothing.
        assert group_view["proceeds_balance_cents"] == 400
        campaign_view = get_success_data(api.get_campaign(campaign["id"], ADMIN))
        assert campaign_view["status"] == "ORDERING_CLOSED"


class TestSupplierOrderAggregation:
    def test_case_pack_exact_multiple_no_extra_case(self, api):
        """PRD §3.3: "Case-pack rounding applies at creation: `ordered_cases`
        is `requested_units` divided by `case_pack_size` rounded up to a whole
        number, and `ordered_units` is `ordered_cases` times `case_pack_size`."
        PRD §3.3: "a product whose aggregated demand is zero is omitted from
        the supplier order entirely."

        Design: Difficulty/boundary_precision_check/case_pack_exact_multiple_no_extra_case
        """
        reset_clock()
        campaign, group, product = setup_campaign_group_product()
        idle = create_product(campaign["id"], name="Mug", sku="MUG-01",
                              unit_price_cents=700, supplier_unit_cost_cents=300,
                              case_pack_size=6)
        seller = create_seller(group["id"])
        get_success_data(api.open_campaign(campaign["id"], ADMIN))
        create_and_submit_order(seller["id"], product["id"], 13)
        create_and_submit_order(seller["id"], product["id"], 11,
                                family_contact_name="Fam2")
        close_ordering_at_window_end(campaign["id"])
        resp = api.create_supplier_order({"campaign_id": campaign["id"]}, ADMIN)
        supplier_order = validate_success(resp, 201)
        lines, _meta = validate_paginated(
            api.list_supplier_order_lines(supplier_order["id"], ADMIN))
        assert len(lines) == 1, (
            f"the zero-demand product {idle['sku']} must be omitted")
        line = lines[0]
        assert line["product_id"] == product["id"]
        assert line["requested_units"] == 24
        assert line["ordered_cases"] == 2, (
            "exact multiple: ceil(24/12) adds no phantom case")
        assert line["ordered_units"] == 24

    def test_case_pack_non_multiple_rounds_up(self, api):
        """PRD §3.3: "`ordered_cases` is `requested_units` divided by
        `case_pack_size` rounded up to a whole number, and `ordered_units` is
        `ordered_cases` times `case_pack_size`."

        Design: Difficulty/boundary_precision_check/case_pack_exact_multiple_no_extra_case
        """
        reset_clock()
        campaign, _group, product, seller = setup_open_campaign_with_seller()
        create_and_submit_order(seller["id"], product["id"], 13)
        close_ordering_at_window_end(campaign["id"])
        supplier_order = get_success_data(
            api.create_supplier_order({"campaign_id": campaign["id"]}, ADMIN))
        lines, _meta = validate_paginated(
            api.list_supplier_order_lines(supplier_order["id"], ADMIN))
        assert lines[0]["requested_units"] == 13
        assert lines[0]["ordered_cases"] == 2
        assert lines[0]["ordered_units"] == 24

    def test_supplier_cost_estimate_vs_actual_divergence(self, api):
        """PRD §3.3: "Submitting the supplier order moves it `DRAFT` →
        `SUBMITTED`, requires at least one supplier order line (an order with
        zero aggregated units is rejected with `ERR_NO_SUBMITTED_ORDERS`),
        pins the `estimated_cost_cents` as the sum over lines of
        `ordered_units` times `unit_cost_estimated_cents`, and stamps
        `submitted_by_user_id` from the acting admin."
        PRD §3.3: "pins the supplier order's `actual_cost_cents` as the sum
        over lines of `delivered_units` times `unit_cost_actual_cents`."

        Design: Difficulty/dual_variant_calc/supplier_cost_estimate_vs_actual_divergence
        """
        reset_clock()
        campaign, _group, product, seller = setup_open_campaign_with_seller()
        create_and_submit_order(seller["id"], product["id"], 13)
        create_and_submit_order(seller["id"], product["id"], 12,
                                family_contact_name="Fam2")
        close_ordering_at_window_end(campaign["id"])
        supplier_order = get_success_data(
            api.create_supplier_order({"campaign_id": campaign["id"]}, ADMIN))
        get_success_data(api.submit_supplier_order(supplier_order["id"], ADMIN))
        submitted = get_success_data(
            api.get_supplier_order(supplier_order["id"], ADMIN))
        # 25 requested -> 3 cases -> 36 units at the 600-cent estimate.
        assert submitted["estimated_cost_cents"] == 21600
        assert submitted["status"] == "SUBMITTED"

        ack_payload = {
            "confirmed_delivery_date": TEST_DEFAULTS["CONFIRMED_DELIVERY_DATE"],
            "line_costs": [{"product_id": product["id"],
                            "unit_cost_actual_cents": 625}],
        }
        get_success_data(api.acknowledge_supplier_order(
            supplier_order["id"], ack_payload, SUPP))
        deliver_payload = {
            "actual_delivery_date": TEST_DEFAULTS["ACTUAL_DELIVERY_DATE"],
            "delivered": [{"product_id": product["id"], "delivered_units": 36}],
        }
        from test_helpers import make_supplier_rep_headers
        get_success_data(api.deliver_supplier_order(
            supplier_order["id"], deliver_payload,
            make_supplier_rep_headers("supp-2")))
        delivered = get_success_data(
            api.get_supplier_order(supplier_order["id"], ADMIN))
        assert delivered["status"] == "DELIVERED"
        # 36 delivered units at the supplier-confirmed 625 actual cost.
        assert delivered["actual_cost_cents"] == 22500, (
            "actual variant prices delivered units at supplier-confirmed cost")

    def test_supplier_cost_estimate_line_shortage_zero(self, api):
        """PRD §3.3: "sets each line's `delivered_units` and computes each
        line's `shortage_units` as `ordered_units` minus `delivered_units`".

        Design: Difficulty/dual_variant_calc/supplier_cost_estimate_vs_actual_divergence
        """
        reset_clock()
        campaign, _group, product, seller = setup_open_campaign_with_seller()
        create_and_submit_order(seller["id"], product["id"], 13)
        create_and_submit_order(seller["id"], product["id"], 12,
                                family_contact_name="Fam2")
        close_ordering_at_window_end(campaign["id"])
        supplier_order = drive_campaign_to_delivered(
            campaign["id"], product["id"], delivered_units=36,
            unit_cost_actual_cents=625)
        lines, _meta = validate_paginated(
            api.list_supplier_order_lines(supplier_order["id"], ADMIN))
        assert lines[0]["requested_units"] == 25
        assert lines[0]["ordered_cases"] == 3
        assert lines[0]["ordered_units"] == 36
        assert lines[0]["delivered_units"] == 36
        assert lines[0]["shortage_units"] == 0

    def test_supplier_unsubmit_revision_loop(self, api):
        """PRD §3.3: "A mistaken submission can be walked back: unsubmitting
        returns `SUBMITTED` → `DRAFT` and increments the supplier order's
        `version` by 1, reopening the revision loop."
        PRD §3.3: "a revision supplies `line_adjustments` alongside the
        mandatory `expected_supplier_order_version` per §2.8, re-derives cases
        and units per the same case-pack rule".

        Design: Corner/state_machines/supplier_unsubmit_revision_loop
        """
        reset_clock()
        campaign, _group, product, seller = setup_open_campaign_with_seller()
        create_and_submit_order(seller["id"], product["id"], 2)
        close_ordering_at_window_end(campaign["id"])
        supplier_order = get_success_data(
            api.create_supplier_order({"campaign_id": campaign["id"]}, ADMIN))
        get_success_data(api.submit_supplier_order(supplier_order["id"], ADMIN))
        unsubmitted = get_success_data(
            api.unsubmit_supplier_order(supplier_order["id"], ADMIN))
        assert unsubmitted["status"] == "DRAFT"
        v = unsubmitted["version"]
        get_success_data(api.patch_supplier_order(
            supplier_order["id"],
            {"expected_supplier_order_version": v,
             "line_adjustments": [{"product_id": product["id"],
                                   "requested_units": 13}]},
            ADMIN))
        lines, _meta = validate_paginated(
            api.list_supplier_order_lines(supplier_order["id"], ADMIN))
        assert lines[0]["requested_units"] == 13
        assert lines[0]["ordered_cases"] == 2, "ceil(13/12) re-derived"
        resubmitted = get_success_data(
            api.submit_supplier_order(supplier_order["id"], ADMIN))
        assert resubmitted["status"] == "SUBMITTED"

    def test_supplier_second_active_order_rejected(self, api):
        """PRD §3.3: "only one active supplier order may exist per campaign —
        creating a second while a non-cancelled, non-delivered one exists is
        rejected with `ERR_CAMPAIGN_HAS_ACTIVE_SUPPLIER_ORDER`."

        Design: Corner/state_machines/supplier_second_active_order_rejected
        """
        reset_clock()
        campaign, _group, product, seller = setup_open_campaign_with_seller()
        create_and_submit_order(seller["id"], product["id"], 1)
        close_ordering_at_window_end(campaign["id"])
        get_success_data(
            api.create_supplier_order({"campaign_id": campaign["id"]}, ADMIN))
        resp = api.create_supplier_order({"campaign_id": campaign["id"]}, ADMIN)
        validate_error(resp, ApiErrorId.ERR_CAMPAIGN_HAS_ACTIVE_SUPPLIER_ORDER)

    def test_supplier_create_without_orders_rejected(self, api):
        """PRD §3.3: "Submitting the supplier order moves it `DRAFT` →
        `SUBMITTED`, requires at least one supplier order line (an order with
        zero aggregated units is rejected with `ERR_NO_SUBMITTED_ORDERS`)".

        Design: Corner/state_machines/supplier_create_without_orders_rejected
        """
        reset_clock()
        campaign, _group, _product = setup_campaign_group_product()
        get_success_data(api.open_campaign(campaign["id"], ADMIN))
        close_ordering_at_window_end(campaign["id"])
        # No orders exist: every product's aggregated demand is zero, so each
        # is omitted from the supplier order entirely (PRD §3.3); creation
        # itself only gates on ORDERING_CLOSED and one-active-order.
        supplier_order = validate_success(
            api.create_supplier_order({"campaign_id": campaign["id"]}, ADMIN),
            201)
        lines, meta = validate_paginated(
            api.list_supplier_order_lines(supplier_order["id"], ADMIN))
        assert meta["total_count"] == 0, (
            "zero aggregated demand yields a supplier order with no lines")
        resp = api.submit_supplier_order(supplier_order["id"], ADMIN)
        validate_error(resp, ApiErrorId.ERR_NO_SUBMITTED_ORDERS)

    def test_supplier_deliver_over_ordered_rejected(self, api):
        """PRD §3.3: "each line's `delivered_units` no greater than its
        `ordered_units` (else `ERR_QUANTITY_INVALID`)".

        Design: Corner/state_machines/supplier_deliver_over_ordered_rejected
        """
        reset_clock()
        campaign, _group, product, seller = setup_open_campaign_with_seller()
        create_and_submit_order(seller["id"], product["id"], 1)
        close_ordering_at_window_end(campaign["id"])
        supplier_order = get_success_data(
            api.create_supplier_order({"campaign_id": campaign["id"]}, ADMIN))
        get_success_data(api.submit_supplier_order(supplier_order["id"], ADMIN))
        ack_payload = {
            "confirmed_delivery_date": TEST_DEFAULTS["CONFIRMED_DELIVERY_DATE"],
            "line_costs": [{"product_id": product["id"],
                            "unit_cost_actual_cents": 600}],
        }
        get_success_data(api.acknowledge_supplier_order(
            supplier_order["id"], ack_payload, SUPP))
        deliver_payload = {
            "actual_delivery_date": TEST_DEFAULTS["ACTUAL_DELIVERY_DATE"],
            # ordered_units == 12 (1 unit rounds to one case of 12); 13 over-delivers.
            "delivered": [{"product_id": product["id"], "delivered_units": 13}],
        }
        from test_helpers import make_supplier_rep_headers
        resp = api.deliver_supplier_order(
            supplier_order["id"], deliver_payload,
            make_supplier_rep_headers("supp-2"))
        validate_error(resp, ApiErrorId.ERR_QUANTITY_INVALID)
        after = get_success_data(
            api.get_supplier_order(supplier_order["id"], ADMIN))
        assert after["status"] == "ACKNOWLEDGED"

    def test_campaign_advancement_waits_for_supplier_acknowledgement(self, api):
        """PRD §3.3: "it sets each line's `unit_cost_actual_cents`, stamps
        `acknowledged_by_user_id`, and — as a cross-entity cascade —
        automatically advances the campaign from `ORDERING_CLOSED` to
        `SUPPLIER_ORDERED`, incrementing the campaign's `version` by 1."
        PRD §3.3: "The campaign then advances automatically from
        `SUPPLIER_ORDERED` to `DELIVERED` with its version incremented".

        Design: Difficulty/cross_entity_state_dependency/campaign_advancement_waits_for_supplier_acknowledgement
        """
        reset_clock()
        campaign, _group, product, seller = setup_open_campaign_with_seller()
        create_and_submit_order(seller["id"], product["id"], 2)
        close_ordering_at_window_end(campaign["id"])
        supplier_order = get_success_data(
            api.create_supplier_order({"campaign_id": campaign["id"]}, ADMIN))
        get_success_data(api.submit_supplier_order(supplier_order["id"], ADMIN))
        before = get_success_data(api.get_campaign(campaign["id"], ADMIN))
        assert before["status"] == "ORDERING_CLOSED", (
            "submitting the supplier order alone must not advance the campaign")

        ack_payload = {
            "confirmed_delivery_date": TEST_DEFAULTS["CONFIRMED_DELIVERY_DATE"],
            "line_costs": [{"product_id": product["id"],
                            "unit_cost_actual_cents": 600}],
        }
        get_success_data(api.acknowledge_supplier_order(
            supplier_order["id"], ack_payload, SUPP))
        after_ack = get_success_data(api.get_campaign(campaign["id"], ADMIN))
        assert after_ack["status"] == "SUPPLIER_ORDERED"

        from test_helpers import deliver_supplier_order
        deliver_supplier_order(supplier_order["id"], product["id"], 12)
        after_deliver = get_success_data(api.get_campaign(campaign["id"], ADMIN))
        assert after_deliver["status"] == "DELIVERED"

    def test_campaign_stays_ordering_closed_until_acknowledge(self, api):
        """PRD §2.11: "When a parent resource transitions, dependent children
        move with it: closing ordering cancels every DRAFT order and locks
        every SUBMITTED one; acknowledging and delivering a supplier order
        advances the campaign in lockstep".

        Design: Difficulty/cross_entity_state_dependency/campaign_advancement_waits_for_supplier_acknowledgement
        """
        reset_clock()
        campaign, _group, product, seller = setup_open_campaign_with_seller()
        create_and_submit_order(seller["id"], product["id"], 2)
        close_ordering_at_window_end(campaign["id"])
        supplier_order = get_success_data(
            api.create_supplier_order({"campaign_id": campaign["id"], }, ADMIN))
        get_success_data(api.submit_supplier_order(supplier_order["id"], ADMIN))
        get_success_data(api.unsubmit_supplier_order(supplier_order["id"], ADMIN))
        get_success_data(api.submit_supplier_order(supplier_order["id"], ADMIN))
        campaign_view = get_success_data(api.get_campaign(campaign["id"], ADMIN))
        assert campaign_view["status"] == "ORDERING_CLOSED", (
            "no revision-loop step may advance the campaign; only the "
            "acknowledge cascade does")


class TestSortTickets:
    def test_sort_verify_over_expected_returns_quantity_invalid(self, api):
        """PRD §3.4: "A coordinator verifies a `PENDING` ticket by supplying
        `verified_qty`, which must lie between zero and the ticket's
        `expected_qty` inclusive (else `ERR_QUANTITY_INVALID`)."

        Design: Corner/state_machines/sort_verify_over_expected_returns_quantity_invalid
        """
        reset_clock()
        campaign, _group, product, seller = setup_open_campaign_with_seller()
        create_and_submit_order(seller["id"], product["id"], 1)
        close_ordering_at_window_end(campaign["id"])
        drive_campaign_to_delivered(campaign["id"], product["id"], 12)
        get_success_data(api.generate_sort_tickets(campaign["id"], COORD))
        tickets, _meta = validate_paginated(
            api.list_sort_tickets(COORD, params={"campaign_id": campaign["id"]}))
        ticket = tickets[0]
        assert ticket["expected_qty"] == 1
        resp = api.verify_sort_ticket(ticket["id"], {"verified_qty": 2}, COORD)
        validate_error(resp, ApiErrorId.ERR_QUANTITY_INVALID)
        after = get_success_data(api.get_sort_ticket(ticket["id"], COORD))
        assert after["status"] == "PENDING"

    def test_sort_tickets_regenerate_rejected(self, api):
        """PRD §3.4: "Generation is one-shot: if sort tickets already exist
        for the campaign, the attempt is rejected with
        `ERR_SORT_TICKETS_ALREADY_GENERATED`."

        Design: Corner/state_machines/sort_tickets_regenerate_rejected
        """
        reset_clock()
        campaign, _group, product, seller = setup_open_campaign_with_seller()
        create_and_submit_order(seller["id"], product["id"], 1)
        close_ordering_at_window_end(campaign["id"])
        drive_campaign_to_delivered(campaign["id"], product["id"], 12)
        get_success_data(api.generate_sort_tickets(campaign["id"], COORD))
        resp = api.generate_sort_tickets(campaign["id"], COORD)
        validate_error(resp, ApiErrorId.ERR_SORT_TICKETS_ALREADY_GENERATED)

    def test_mark_sorted_with_pending_tickets_rejected(self, api):
        """PRD §3.4: "Only when every sort ticket of the campaign has left
        `PENDING` — each one `VERIFIED` or `SHORT`, else the mark-sorted
        attempt is rejected with `ERR_UNVERIFIED_SORT_TICKETS` — may the
        coordinator mark the campaign sorted".

        Design: Corner/state_machines/mark_sorted_with_pending_tickets_rejected
        """
        reset_clock()
        campaign, _group, product, seller = setup_open_campaign_with_seller()
        create_and_submit_order(seller["id"], product["id"], 1)
        close_ordering_at_window_end(campaign["id"])
        drive_campaign_to_delivered(campaign["id"], product["id"], 12)
        get_success_data(api.generate_sort_tickets(campaign["id"], COORD))
        resp = api.mark_sorted(campaign["id"], COORD)
        validate_error(resp, ApiErrorId.ERR_UNVERIFIED_SORT_TICKETS)
        after = get_success_data(api.get_campaign(campaign["id"], ADMIN))
        assert after["status"] == "DELIVERED"

    def test_sort_short_creates_auto_claim_and_lost_units(self, api):
        """PRD §3.4: "When the count falls short, the ticket moves to `SHORT`
        and the system performs a three-way cascade. First, the unit buckets
        move: the gap — `expected_qty` minus `verified_qty` — is subtracted
        from the product's `surplus_units` and added to its `lost_units`."
        PRD §3.4: "the system auto-creates a **ReconciliationClaim** on that
        line with `claim_type` `MISSING`, `quantity` equal to the gap,
        `auto_generated` true, and `reported_by_user_id` set to the verifying
        user".

        Design: Corner/state_machines/sort_short_creates_auto_claim_and_lost_units
        """
        reset_clock()
        campaign, _group, product, seller = setup_open_campaign_with_seller()
        order = create_and_submit_order(seller["id"], product["id"], 3)
        close_ordering_at_window_end(campaign["id"])
        drive_campaign_to_delivered(campaign["id"], product["id"], 12)
        get_success_data(api.generate_sort_tickets(campaign["id"], COORD))
        tickets, _meta = validate_paginated(
            api.list_sort_tickets(COORD, params={"campaign_id": campaign["id"]}))
        ticket = tickets[0]
        verified = get_success_data(api.verify_sort_ticket(
            ticket["id"], {"verified_qty": 1}, COORD))
        assert verified["status"] == "SHORT"

        claims, _meta = validate_paginated(
            api.list_claims(COORD, params={"order_id": order["id"]}))
        assert len(claims) == 1
        claim = claims[0]
        assert claim["claim_type"] == "MISSING"
        assert claim["quantity"] == 2
        assert claim["auto_generated"] is True
        assert claim["status"] == "SUBMITTED"
        assert claim["reported_by_user_id"] == "coord-1"

        product_view = get_success_data(api.get_product(product["id"], COORD))
        assert product_view["lost_units"] == 2
        assert product_view["surplus_units"] == 10

    def test_generate_sort_tickets_assigns_earliest_event(self, api):
        """PRD §3.4: "a `distribution_event_id` pointing at the campaign's
        earliest `SCHEDULED` distribution event — earliest by `window_start`
        ascending with `created_at` ascending as the tie-break — or null when
        no event has been scheduled yet."

        Design: Corner/endpoints/generate_sort_tickets_assigns_earliest_event
        """
        reset_clock()
        campaign, _group, product, seller = setup_open_campaign_with_seller()
        create_and_submit_order(seller["id"], product["id"], 1)
        close_ordering_at_window_end(campaign["id"])
        drive_campaign_to_delivered(campaign["id"], product["id"], 12)
        # The later-window event is created FIRST; the earlier-window second.
        ev_late = get_success_data(api.create_distribution_event(
            create_distribution_event_payload(
                campaign_id=campaign["id"],
                window_start="2026-09-06T18:00:00Z",
                window_end="2026-09-06T21:00:00Z", slot_capacity=1),
            COORD))
        ev_early = get_success_data(api.create_distribution_event(
            create_distribution_event_payload(
                campaign_id=campaign["id"],
                window_start="2026-09-06T15:00:00Z",
                window_end="2026-09-06T18:00:00Z", slot_capacity=1),
            COORD))
        generated = get_success_data(
            api.generate_sort_tickets(campaign["id"], COORD))
        assert generated["created_count"] == 1
        tickets, _meta = validate_paginated(
            api.list_sort_tickets(COORD, params={"campaign_id": campaign["id"]}))
        assert tickets[0]["expected_qty"] == 1
        assert tickets[0]["distribution_event_id"] == ev_early["id"], (
            f"earliest window_start wins even though {ev_late['id']} was "
            "created first")


class TestDistributionEvents:
    def test_event_create_before_supplier_order_rejected(self, api):
        """PRD §3.5: "Distribution events may be scheduled once the campaign
        is `SUPPLIER_ORDERED` or beyond — specifically while the campaign is
        in `SUPPLIER_ORDERED`, `DELIVERED`, `SORTED`, `DISTRIBUTION_COMPLETE`,
        or `RECONCILED`".

        Design: Corner/state_machines/event_create_before_supplier_order_rejected
        """
        reset_clock()
        campaign, _group, _product = setup_campaign_group_product()
        get_success_data(api.open_campaign(campaign["id"], ADMIN))
        resp = api.create_distribution_event(
            create_distribution_event_payload(campaign_id=campaign["id"]), COORD)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    def test_event_complete_before_start_rejected(self, api):
        """PRD §3.5: "may be completed by a coordinator once the logical clock
        has reached its `window_start` (completing earlier is rejected with
        `ERR_EVENT_NOT_STARTED`)".

        Design: Corner/state_machines/event_complete_before_start_rejected
        """
        reset_clock()
        campaign, _group, product, seller = setup_open_campaign_with_seller()
        create_and_submit_order(seller["id"], product["id"], 1)
        close_ordering_at_window_end(campaign["id"])
        supplier_order = get_success_data(
            api.create_supplier_order({"campaign_id": campaign["id"]}, ADMIN))
        get_success_data(api.submit_supplier_order(supplier_order["id"], ADMIN))
        from test_helpers import acknowledge_supplier_order
        acknowledge_supplier_order(supplier_order["id"], product["id"], 600)
        event = get_success_data(api.create_distribution_event(
            create_distribution_event_payload(campaign_id=campaign["id"]), COORD))
        reset_clock("2026-09-01T00:00:00Z")
        resp = api.complete_distribution_event(event["id"], COORD)
        validate_error(resp, ApiErrorId.ERR_EVENT_NOT_STARTED)
        after = get_success_data(api.get_distribution_event(event["id"], COORD))
        assert after["status"] == "SCHEDULED"


class TestSellerLifecycle:
    def test_seller_enrolled_to_active_on_first_submit(self, api):
        """PRD §3.1: "A seller begins `ENROLLED`, flips automatically to
        `ACTIVE` the moment their first order reaches `SUBMITTED`, may be
        suspended (`ACTIVE` → `SUSPENDED`) and later reinstated (`SUSPENDED` →
        `ACTIVE`) by a coordinator".

        Design: Difficulty/non_linear_state_machine/seller_suspend_reinstate_cycle_gates_ordering
        """
        reset_clock()
        _campaign, _group, product, seller = setup_open_campaign_with_seller()
        assert seller["status"] == "ENROLLED"
        create_and_submit_order(seller["id"], product["id"], 1)
        active = get_success_data(api.get_seller(seller["id"], COORD))
        assert active["status"] == "ACTIVE"
        get_success_data(api.suspend_seller(seller["id"], COORD))
        suspended = get_success_data(api.get_seller(seller["id"], COORD))
        assert suspended["status"] == "SUSPENDED"
        get_success_data(api.reinstate_seller(seller["id"], COORD))
        reinstated = get_success_data(api.get_seller(seller["id"], COORD))
        assert reinstated["status"] == "ACTIVE"

    def test_seller_suspend_reinstate_cycle_gates_ordering(self, api):
        """PRD §3.2: "the seller must be `ENROLLED` or `ACTIVE` (submitting
        for a `SUSPENDED` seller is rejected with `ERR_SELLER_SUSPENDED`; a
        `WITHDRAWN` seller fails the state check with `ERR_INVALID_STATE`)".

        Design: Difficulty/non_linear_state_machine/seller_suspend_reinstate_cycle_gates_ordering
        """
        reset_clock()
        _campaign, _group, product, seller = setup_open_campaign_with_seller()
        create_and_submit_order(seller["id"], product["id"], 1)
        order2 = create_order(seller["id"], product["id"], 1,
                              family_contact_name="Fam2")
        get_success_data(api.suspend_seller(seller["id"], COORD))
        blocked = api.submit_order(order2["id"], COORD)
        validate_error(blocked, ApiErrorId.ERR_SELLER_SUSPENDED)
        held = get_success_data(api.get_order(order2["id"], COORD))
        assert held["status"] == "DRAFT"
        get_success_data(api.reinstate_seller(seller["id"], COORD))
        submitted = get_success_data(api.submit_order(order2["id"], COORD))
        assert submitted["status"] == "SUBMITTED", (
            "the gate lifts after reinstatement — the cycle closes")

    def test_order_submit_blocked_when_seller_suspended(self, api):
        """PRD §3.2: "the seller must be `ENROLLED` or `ACTIVE` (submitting
        for a `SUSPENDED` seller is rejected with `ERR_SELLER_SUSPENDED`; a
        `WITHDRAWN` seller fails the state check with `ERR_INVALID_STATE`)".

        Design: Difficulty/cross_entity_state_dependency/order_submit_blocked_when_seller_suspended
        """
        reset_clock()
        _campaign, _group, product, seller = setup_open_campaign_with_seller()
        create_and_submit_order(seller["id"], product["id"], 1)
        order2 = create_order(seller["id"], product["id"], 1,
                              family_contact_name="Fam2")
        get_success_data(api.suspend_seller(seller["id"], COORD))
        resp = api.submit_order(order2["id"], COORD)
        validate_error(resp, ApiErrorId.ERR_SELLER_SUSPENDED)
        after = get_success_data(api.get_order(order2["id"], COORD))
        assert after["status"] == "DRAFT", (
            "the rejected submit leaves the order untouched")

    def test_order_submit_gate_lifts_after_reinstate(self, api):
        """PRD §3.1: "may be suspended (`ACTIVE` → `SUSPENDED`) and later
        reinstated (`SUSPENDED` → `ACTIVE`) by a coordinator".
        PRD §3.2: "the seller must be `ENROLLED` or `ACTIVE`".

        Design: Difficulty/cross_entity_state_dependency/order_submit_blocked_when_seller_suspended
        """
        reset_clock()
        _campaign, _group, product, seller = setup_open_campaign_with_seller()
        create_and_submit_order(seller["id"], product["id"], 1)
        order2 = create_order(seller["id"], product["id"], 1,
                              family_contact_name="Fam2")
        get_success_data(api.suspend_seller(seller["id"], COORD))
        validate_error(api.submit_order(order2["id"], COORD),
                       ApiErrorId.ERR_SELLER_SUSPENDED)
        get_success_data(api.reinstate_seller(seller["id"], COORD))
        seller_view = get_success_data(api.get_seller(seller["id"], COORD))
        assert seller_view["status"] == "ACTIVE"
        submitted = get_success_data(api.submit_order(order2["id"], COORD))
        assert submitted["status"] == "SUBMITTED"

    def test_seller_withdraw_blocked_by_cleared_payment_rejected(self, api):
        """PRD §3.1: "may be withdrawn from any of `ENROLLED`, `ACTIVE`, or
        `SUSPENDED` into the terminal `WITHDRAWN` — but only when no order of
        theirs carries cleared value, otherwise the withdrawal is rejected
        with `ERR_ORDER_HAS_CLEARED_PAYMENTS`."

        Design: Corner/state_machines/seller_withdraw_blocked_by_cleared_payment_rejected
        """
        reset_clock()
        _campaign, _group, product, seller = setup_open_campaign_with_seller()
        create_submitted_paid_order(seller["id"], product["id"], 1)
        resp = api.withdraw_seller(seller["id"], COORD)
        validate_error(resp, ApiErrorId.ERR_ORDER_HAS_CLEARED_PAYMENTS)
        after = get_success_data(api.get_seller(seller["id"], COORD))
        assert after["status"] == "ACTIVE"


class TestCampaignCancelCascade:
    def test_campaign_cancel_blocked_with_cleared_payment_rejected(self, api):
        """PRD §3.1: "cancellation by a `FundraiserAdmin` is permitted from
        `DRAFT` or `OPEN` only when no order of the campaign carries cleared
        value, otherwise `ERR_CAMPAIGN_CANCEL_BLOCKED`."

        Design: Corner/state_machines/campaign_cancel_blocked_with_cleared_payment_rejected
        """
        reset_clock()
        campaign, _group, product, seller = setup_open_campaign_with_seller()
        create_submitted_paid_order(seller["id"], product["id"], 1)
        resp = api.cancel_campaign(campaign["id"], ADMIN)
        validate_error(resp, ApiErrorId.ERR_CAMPAIGN_CANCEL_BLOCKED)
        after = get_success_data(api.get_campaign(campaign["id"], ADMIN))
        assert after["status"] == "OPEN"

    def test_campaign_cancel_voids_recorded_payments(self, api):
        """PRD §3.1: "Cancelling a campaign cascades — every DRAFT or
        SUBMITTED order moves to `CANCELLED` (SUBMITTED cancellations each
        posting a `SALE_REVERSAL_DEBIT`), and every payment still in
        `RECORDED` is moved to `VOIDED`."

        Design: Corner/state_machines/campaign_cancel_voids_recorded_payments
        """
        reset_clock()
        campaign, group, product, seller = setup_open_campaign_with_seller()
        order = create_and_submit_order(seller["id"], product["id"], 1)
        resp = api.create_payment(
            {"order_id": order["id"], "amount_cents": 1000, "method": "CHECK"},
            TREAS)
        validate_success(resp, 201)  # RECORDED, never cleared
        cancelled = get_success_data(api.cancel_campaign(campaign["id"], ADMIN))
        assert cancelled["status"] == "CANCELLED"
        order_after = get_success_data(api.get_order(order["id"], TREAS))
        assert order_after["status"] == "CANCELLED"
        payments, _meta = validate_paginated(
            api.list_order_payments(order["id"], TREAS))
        assert payments[0]["status"] == "VOIDED"
        group_view = get_success_data(api.get_group(group["id"], TREAS))
        assert group_view["proceeds_balance_cents"] == 0, (
            "provisional +200 reversed by -200; the voided payment never "
            "entered cleared value")


class TestComputedTotalsAndMetrics:
    def test_campaign_totals_gross_sales_computed_read(self, api):
        """PRD §3.7: "`gross_sales_cents` (the sum of `total_cents` over
        orders in `SUBMITTED`, `LOCKED`, or `COMPLETED`)".

        Design: Corner/calculations/campaign_totals_gross_sales_computed_read
        """
        reset_clock()
        campaign, _group, product, seller = setup_open_campaign_with_seller()
        create_and_submit_order(seller["id"], product["id"], 1)
        cancelled = create_and_submit_order(seller["id"], product["id"], 2,
                                            family_contact_name="Fam2")
        get_success_data(api.cancel_order(cancelled["id"], COORD))
        create_order(seller["id"], product["id"], 1, family_contact_name="Fam3")
        view = get_success_data(api.get_campaign(campaign["id"], TREAS))
        assert view["gross_sales_cents"] == 1000, (
            "only the still-submitted order counts; CANCELLED and DRAFT "
            "contribute nothing")

    def test_seller_units_exclude_cancelled_and_returned(self, api):
        """PRD §3.8: "A seller's `units_sold` is the sum, over lines of the
        seller's orders in `SUBMITTED`, `LOCKED`, or `COMPLETED`, of each
        line's `quantity` minus its `returned_qty` minus its
        `claim_resolved_refund_qty`."
        PRD §3.8: "A seller's `orders_count` is the count of the seller's
        orders in `SUBMITTED`, `LOCKED`, or `COMPLETED`."

        Design: Corner/calculations/seller_units_exclude_cancelled_and_returned
        """
        reset_clock()
        _campaign, _group, product, seller = setup_open_campaign_with_seller()
        create_and_submit_order(seller["id"], product["id"], 3)
        to_cancel = create_and_submit_order(seller["id"], product["id"], 2,
                                            family_contact_name="Fam2")
        before = get_success_data(api.get_seller(seller["id"], COORD))
        assert before["units_sold"] == 5
        get_success_data(api.cancel_order(to_cancel["id"], COORD))
        after = get_success_data(api.get_seller(seller["id"], COORD))
        assert after["units_sold"] == 3
        assert after["orders_count"] == 1, (
            "the cancelled order leaves both input sets")

    def test_order_list_filter_by_payment_status(self, api):
        """PRD §3.2: "The order is `UNPAID` when `cleared_cents` is zero,
        `PAID` when `cleared_cents` equals `total_cents` (with `total_cents`
        positive), and `PARTIALLY_PAID` when `cleared_cents` lies strictly
        between."
        PRD §4: "GET `/fundraiser/orders` — List/filter orders".

        Design: Corner/endpoints/order_list_filter_by_payment_status
        """
        reset_clock()
        _campaign, _group, product, seller = setup_open_campaign_with_seller()
        paid = create_submitted_paid_order(seller["id"], product["id"], 1)
        create_and_submit_order(seller["id"], product["id"], 1,
                                family_contact_name="Fam2")
        data, meta = validate_paginated(
            api.list_orders(TREAS, params={"seller_id": seller["id"],
                                           "payment_status": "PAID"}))
        assert len(data) == 1 and meta["total_count"] == 1
        assert data[0]["id"] == paid["id"], (
            "the derived-value filter returns only the fully cleared order")
