"""Labels, locker reservations, expiry sweep: supersession chains, terminal
lockdown, reservation lifecycle, lazy expiry, hold-window boundary, slot
exclusivity, and cascade conservation of location counters."""
from test_helpers import (
    ApiErrorId,
    create_location,
    create_order,
    create_return_item_line,
    create_slot,
    issue_label,
    issue_label_payload,
    make_location_operator_headers,
    reserve_slot,
    run_sweep,
    set_clock,
    setup_commercial_spine,
    validate_error,
    validate_success,
)


def _locker_spine(email):
    """Plan (no pickup) + merchant + cycle + shopper + OPERATIONAL locker
    location + one XL slot."""
    spine = setup_commercial_spine(
        plan_overrides={"pickup_enabled": False}, shopper_email=email
    )
    location = create_location(name="L-Lock", kind="LOCKER")
    slot = create_slot(location["id"], size_class="XL")
    return spine, location, slot


def _locker_order_with_reservation(spine, slot, sku="LK"):
    order = create_order(
        spine, method="LOCKER_QR",
        items=[create_return_item_line(sku=sku, longest_side_cm=40,
                                       weight_grams=300)],
    )
    reservation = reserve_slot(order, slot, spine["shopper_headers"])
    return order, reservation


class TestLabelLifecycle:

    def test_label_double_void_terminal_lockdown(self, api):
        """PRD §3.4: "any label action on a non-`ISSUED` label is refused with
        `ERR_LABEL_NOT_ACTIVE`".

        Design: Corner/state_machines/label_double_void_terminal_lockdown
        """
        from test_helpers import api_client
        spine = setup_commercial_spine(shopper_email="slv@x.com")
        order = create_order(spine, method="COUNTER_DROP")
        label = issue_label(order)

        first = api_client.void_label(label["id"], spine["shopper_headers"])
        validate_success(first)
        second = api_client.void_label(label["id"], spine["shopper_headers"])
        validate_error(second, ApiErrorId.ERR_LABEL_NOT_ACTIVE)

    def test_label_reissue_supersedes_and_chain_queryable(self, api):
        """PRD §3.4: "issuing while another label is still active
        **supersedes** the old one — the prior label moves from `ISSUED` to
        `SUPERSEDED` and the new label's `supersedes_label_id` points back at
        it". "Labels are listable with optional `return_order_id`,
        `supersedes_label_id`, and `status` filters."

        Design: Corner/endpoints/label_reissue_supersedes_and_chain_queryable
        """
        spine = setup_commercial_spine(shopper_email="ssup@x.com")
        order = create_order(spine, method="COUNTER_DROP")
        label_a = issue_label(order, label_type="CARRIER_LABEL")

        fresh_order = validate_success(
            api.get_return_order(order["id"], spine["shopper_headers"])
        )
        resp_b = api.issue_label(
            order["id"],
            issue_label_payload("QR_CODE", fresh_order["version"]),
            spine["shopper_headers"],
        )
        label_b = validate_success(resp_b, expected_status=201)
        assert label_b["supersedes_label_id"] == label_a["id"]

        label_a_after = validate_success(
            api.get_label(label_a["id"], spine["shopper_headers"])
        )
        assert label_a_after["status"] == "SUPERSEDED"

        successors = validate_success(
            api.list_labels(spine["shopper_headers"],
                            params={"supersedes_label_id": label_a["id"]})
        )
        assert len(successors) == 1
        assert successors[0]["id"] == label_b["id"]

    def test_error_label_method_mismatch_boxless(self, api):
        """PRD §3.4: "`LOCKER_QR` orders and any boxless order may only carry
        `QR_CODE` labels, so a mismatched request is rejected with
        `ERR_LABEL_METHOD_MISMATCH`."

        Design: Corner/errors/error_label_method_mismatch_boxless
        """
        spine = setup_commercial_spine(shopper_email="slm@x.com")
        order = create_order(spine, method="COUNTER_DROP", boxless=True)
        resp = api.issue_label(
            order["id"],
            issue_label_payload("CARRIER_LABEL", order["version"]),
            spine["shopper_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_LABEL_METHOD_MISMATCH)

    def test_scheduled_clock_default_and_label_issue_fields(self, api):
        """PRD §2.5: "Before any operator sets it, the logical clock starts at
        exactly `2026-05-01T00:00:00Z`; the server must not fall back to
        wall-clock time under any circumstance."
        PRD §3.4: "the new label starts `ISSUED` with `issued_at` stamped from
        the logical clock and `expires_at` set exactly ten days later."

        Design: Corner/cross_cutting_layers/scheduled_clock_default_and_label_issue_fields
        """
        spine = setup_commercial_spine(shopper_email="sck@x.com")
        order = create_order(spine, method="COUNTER_DROP")
        label = issue_label(order, label_type="CARRIER_LABEL")
        assert label["issued_at"] == "2026-05-01T00:00:00Z"
        assert label["expires_at"] == "2026-05-11T00:00:00Z"


class TestLabelExpiry:

    def test_label_ttl_expires_at_exactly_ten_days(self, api):
        """PRD §3.4: "The sweep of §2.5 turns any `ISSUED` label whose
        `expires_at` is at or before the current instant into `EXPIRED` — at
        exactly `expires_at` the label is expired".

        Design: Corner/calculations/label_ttl_expires_at_exactly_ten_days
        """
        from test_helpers import TEST_USERS, api_client
        spine = setup_commercial_spine(shopper_email="stt@x.com")
        order = create_order(spine, method="COUNTER_DROP")
        label = issue_label(order, label_type="CARRIER_LABEL")
        assert label["expires_at"] == "2026-05-11T00:00:00Z"

        set_clock("2026-05-10T23:59:59Z")
        sweep1 = run_sweep()
        assert sweep1["expired_label_count"] == 0

        set_clock("2026-05-11T00:00:00Z")
        sweep2 = run_sweep()
        assert sweep2["expired_label_count"] == 1
        label_after = validate_success(
            api_client.get_label(label["id"], TEST_USERS["platform_admin_headers"])
        )
        assert label_after["status"] == "EXPIRED"

    def test_error_label_expired_on_lazy_confirm(self, api):
        """PRD §3.4: "consuming or confirming against an expired label is
        refused with `ERR_LABEL_EXPIRED`."

        Design: Corner/errors/error_label_expired_on_lazy_confirm
        """
        from test_helpers import (
            TEST_USERS,
            api_client,
            confirm_dropoff_payload,
        )
        spine = setup_commercial_spine(shopper_email="sle@x.com")
        location = create_location(name="L-LE", kind="COUNTER")
        order = create_order(spine, method="COUNTER_DROP")
        label = issue_label(order, label_type="CARRIER_LABEL")

        set_clock("2026-05-12T00:00:00Z")

        resp = api.confirm_dropoff(
            order["id"], confirm_dropoff_payload(location["id"]),
            make_location_operator_headers(location["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_LABEL_EXPIRED)

        # No sweep ran: the row is still ISSUED (lazy check at call time).
        label_after = validate_success(
            api_client.get_label(label["id"], TEST_USERS["platform_admin_headers"])
        )
        assert label_after["status"] == "ISSUED"


class TestReservationLifecycle:

    def test_slot_live_hold_exclusive_interval(self, api):
        """PRD §3.5: "a slot accepts a new reservation only when no *other*
        reservation on that slot is in `HELD` status with a `hold_until`
        still in the future; an overlapping live hold is rejected with
        `ERR_SLOT_UNAVAILABLE`, while an adjacency — a previous hold whose
        `hold_until` is at or before the current instant — blocks nothing."

        Design: Difficulty/resource_temporal_overlap/slot_live_hold_exclusive_interval
        """
        from test_helpers import api_client, create_slot_reservation_payload
        spine, location, slot = _locker_spine("se@x.com")
        order1 = create_order(spine, method="LOCKER_QR",
                              items=[create_return_item_line(sku="E1",
                                                             longest_side_cm=20)])
        order2 = create_order(spine, method="LOCKER_QR",
                              items=[create_return_item_line(sku="E2",
                                                             longest_side_cm=20)])
        res1 = reserve_slot(order1, slot, spine["shopper_headers"])

        # Overlapping live hold -> rejected.
        blocked = api.create_slot_reservation(
            create_slot_reservation_payload(order2["id"], slot["id"]),
            spine["shopper_headers"],
        )
        validate_error(blocked, ApiErrorId.ERR_SLOT_UNAVAILABLE)

        # After release the slot accepts a new hold immediately.
        release = api_client.release_slot_reservation(
            res1["id"], spine["shopper_headers"]
        )
        validate_success(release)
        res2 = validate_success(
            api.create_slot_reservation(
                create_slot_reservation_payload(order2["id"], slot["id"]),
                spine["shopper_headers"],
            ),
            expected_status=201,
        )
        assert res2["status"] == "HELD"

    def test_reservation_requires_location_operational(self, api):
        """PRD §3.5: "A pause — available to both a `PlatformAdmin` and the
        location's own operator — moves `OPERATIONAL` → `PAUSED` and blocks
        new slot reservations and counter drop-offs with
        `ERR_LOCATION_NOT_OPERATIONAL`; resuming returns `PAUSED` →
        `OPERATIONAL`."

        Design: Difficulty/cross_entity_state_dependency/reservation_requires_location_operational
        """
        from test_helpers import TEST_USERS, api_client, create_slot_reservation_payload
        spine, location, slot = _locker_spine("sloc@x.com")
        order = create_order(spine, method="LOCKER_QR",
                             items=[create_return_item_line(sku="LP",
                                                            longest_side_cm=20)])

        validate_success(
            api_client.pause_location(
                location["id"], TEST_USERS["platform_admin_headers"]
            )
        )
        blocked = api.create_slot_reservation(
            create_slot_reservation_payload(order["id"], slot["id"]),
            spine["shopper_headers"],
        )
        validate_error(blocked, ApiErrorId.ERR_LOCATION_NOT_OPERATIONAL)

        validate_success(
            api_client.resume_location(
                location["id"], TEST_USERS["platform_admin_headers"]
            )
        )
        ok = validate_success(
            api.create_slot_reservation(
                create_slot_reservation_payload(order["id"], slot["id"]),
                spine["shopper_headers"],
            ),
            expected_status=201,
        )
        assert ok["status"] == "HELD"

    def test_out_of_service_slot_rejects_reservation(self, api):
        """PRD §3.5: "a slot sitting `OUT_OF_SERVICE` is refused with
        `ERR_SLOT_OUT_OF_SERVICE`."

        Design: Corner/state_machines/out_of_service_slot_rejects_reservation
        """
        from test_helpers import api_client, create_slot_reservation_payload
        spine, location, slot = _locker_spine("sos@x.com")
        validate_success(
            api_client.out_of_service_slot(
                slot["id"], make_location_operator_headers(location["id"])
            )
        )
        order = create_order(spine, method="LOCKER_QR",
                             items=[create_return_item_line(sku="OS",
                                                            longest_side_cm=20)])
        resp = api.create_slot_reservation(
            create_slot_reservation_payload(order["id"], slot["id"]),
            spine["shopper_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_SLOT_OUT_OF_SERVICE)

    def test_reservation_consume_hold_until_time_boundary(self, api):
        """PRD §3.5: "it requires the reservation still `HELD` and the current
        instant strictly before `hold_until`, with an attempt at or after
        `hold_until` rejected as `ERR_RESERVATION_EXPIRED`". "A created
        reservation stamps `hold_start` at the current instant and sets
        `hold_until` exactly 48 hours later, forming a half-open window from
        `hold_start` inclusive to `hold_until` exclusive."

        Design: Difficulty/boundary_precision_check/reservation_consume_hold_until_time_boundary
        """
        from test_helpers import api_client
        spine, location, _slot1 = _locker_spine("sti@x.com")
        slot2 = create_slot(location["id"], size_class="XL")
        order1, res1 = _locker_order_with_reservation(spine, _slot1, sku="TI1")
        order2, res2 = _locker_order_with_reservation(spine, slot2, sku="TI2")

        # hold_start is the default clock 2026-05-01T00:00:00Z; hold_until is
        # exactly 48h later = 2026-05-03T00:00:00Z.
        set_clock("2026-05-02T23:59:59Z")  # hold_until - 1s
        ok = validate_success(
            api_client.consume_slot_reservation(
                res1["id"], make_location_operator_headers(location["id"])
            )
        )
        assert ok["status"] == "CONSUMED"

        set_clock("2026-05-03T00:00:00Z")  # exactly hold_until
        expired = api_client.consume_slot_reservation(
            res2["id"], make_location_operator_headers(location["id"])
        )
        validate_error(expired, ApiErrorId.ERR_RESERVATION_EXPIRED)

    def test_reservation_consume_three_link_cascade(self, api):
        """PRD §3.5: "Consume fires a three-link cascade: first the slot flips
        `RESERVED` → `OCCUPIED`, decrementing the location's
        `reserved_slot_count` and incrementing its `occupied_slot_count`; that
        flip causes the order to move `LABEL_ISSUED` → `DROPPED_OFF` with
        `dropoff_location_id` set to the slot's location; and the drop-off in
        turn consumes the bound label (`ISSUED` → `CONSUMED`), while the
        reservation itself moves from `HELD` to the terminal `CONSUMED`."

        Design: Difficulty/transitive_cascade/reservation_consume_three_link_cascade
        """
        from test_helpers import api_client
        spine, location, slot = _locker_spine("sl@x.com")
        order, reservation = _locker_order_with_reservation(spine, slot)

        op_headers = make_location_operator_headers(location["id"])
        consumed = validate_success(
            api_client.consume_slot_reservation(reservation["id"], op_headers)
        )
        assert consumed["status"] == "CONSUMED"

        slot_after = validate_success(api_client.get_locker_slot(slot["id"], op_headers))
        assert slot_after["status"] == "OCCUPIED"

        order_after = validate_success(api_client.get_return_order(order["id"], op_headers))
        assert order_after["status"] == "DROPPED_OFF"
        assert order_after["dropoff_location_id"] == location["id"]

        label_after = validate_success(
            api_client.get_label(reservation["label_id"], op_headers)
        )
        assert label_after["status"] == "CONSUMED"

        location_after = validate_success(
            api_client.get_dropoff_location(location["id"], op_headers)
        )
        assert location_after["reserved_slot_count"] == 0
        assert location_after["occupied_slot_count"] == 1

    def test_reserve_release_conserves_slot_occupancy_counters(self, api):
        """PRD §3.5: "**Release** — by the shopper or the operator — moves
        `HELD` → `RELEASED` and unwinds the claim: the slot returns to
        `EMPTY`, the bound label is voided, and the order falls back
        `LABEL_ISSUED` → `INITIATED`."
        PRD §3.5: "the slot flips `EMPTY` → `RESERVED` and the location's
        `reserved_slot_count` increments by one".

        Design: Difficulty/compensating_invariant/reserve_release_conserves_slot_occupancy_counters
        """
        from test_helpers import TEST_USERS, api_client
        spine, location, slot = _locker_spine("scn@x.com")
        order = create_order(spine, method="LOCKER_QR",
                             items=[create_return_item_line(sku="CN",
                                                            longest_side_cm=20)])
        reservation = reserve_slot(order, slot, spine["shopper_headers"])

        mid = validate_success(
            api_client.get_dropoff_location(
                location["id"], TEST_USERS["platform_admin_headers"]
            )
        )
        assert mid["reserved_slot_count"] == 1
        assert mid["occupied_slot_count"] == 0

        validate_success(
            api_client.release_slot_reservation(
                reservation["id"], spine["shopper_headers"]
            )
        )

        post = validate_success(
            api_client.get_dropoff_location(
                location["id"], TEST_USERS["platform_admin_headers"]
            )
        )
        assert post["reserved_slot_count"] == 0
        assert post["occupied_slot_count"] == 0

        slot_after = validate_success(
            api_client.get_locker_slot(
                slot["id"], TEST_USERS["platform_admin_headers"]
            )
        )
        assert slot_after["status"] == "EMPTY"

    def test_location_decommission_busy_slot_rejected(self, api):
        """PRD §3.5: "Decommissioning, a `PlatformAdmin` privilege available
        from either `OPERATIONAL` or `PAUSED`, requires that no slot at the
        location is `RESERVED` or `OCCUPIED` — a busy location is refused with
        `ERR_LOCATION_BUSY`".

        Design: Corner/state_machines/location_decommission_busy_slot_rejected
        """
        from test_helpers import TEST_USERS, api_client
        spine, location, slot = _locker_spine("sbz@x.com")
        _order, _reservation = _locker_order_with_reservation(spine, slot)
        resp = api_client.decommission_location(
            location["id"], TEST_USERS["platform_admin_headers"]
        )
        validate_error(resp, ApiErrorId.ERR_LOCATION_BUSY)


class TestSweepCascade:

    def test_sweep_expiry_four_link_cascade(self, api):
        """PRD §2.5: "It expires labels whose ten-day life has elapsed and
        then expires reservations whose 48-hour hold has elapsed, firing the
        cascade links described in §3.4 and §3.5 (a label expiry drags its
        bound reservation down, and a reservation expiry frees its locker slot
        and refreshes location counts)."
        PRD §3.5: "**Expiry** — from the §2.5 sweep — moves `HELD` →
        `EXPIRED` when `hold_until` has been reached, freeing the slot to
        `EMPTY` and recomputing the location's reserved count."

        Design: Difficulty/transitive_cascade/sweep_expiry_four_link_cascade
        """
        from test_helpers import TEST_USERS, api_client
        spine, location, slot = _locker_spine("ss@x.com")
        order, reservation = _locker_order_with_reservation(spine, slot, sku="SW")

        set_clock("2026-05-12T00:00:00Z")  # past both deadlines
        sweep = run_sweep()
        assert sweep["expired_label_count"] == 1
        assert sweep["expired_reservation_count"] == 1

        admin = TEST_USERS["platform_admin_headers"]
        label_after = validate_success(
            api_client.get_label(reservation["label_id"], admin)
        )
        assert label_after["status"] == "EXPIRED"
        reservation_after = validate_success(
            api_client.get_slot_reservation(reservation["id"], admin)
        )
        assert reservation_after["status"] == "EXPIRED"
        slot_after = validate_success(api_client.get_locker_slot(slot["id"], admin))
        assert slot_after["status"] == "EMPTY"
        location_after = validate_success(
            api_client.get_dropoff_location(location["id"], admin)
        )
        assert location_after["reserved_slot_count"] == 0

        # The order itself survives LABEL_ISSUED so re-issue remains possible.
        order_after = validate_success(api_client.get_return_order(order["id"], admin))
        assert order_after["status"] == "LABEL_ISSUED"
