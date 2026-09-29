"""Error identity: which of two candidate ids a refusal actually carries.

Each group here pins one discrimination the catalogue makes and a naive
implementation collapses: the 404 that names the collection searched rather than a
generic not-found, the pair of order-state ids selected by what the operation
demanded, the availability check re-run at both ends of the offer handshake, the
three separate reasons a window may refuse a reservation, the payer year read off
the target window instead of the clock, the four capability ids at an override
dispatch, the order-level rule that preempts the reship-linkage rule, and the
assignment-status guard that reads status rather than counting calls.
"""

import pytest

from test_helpers import (
    OPS_HEADERS,
    OPS_USER_A,
    OPS_USER_B,
    OPS_USER_C,
    Z1_STANDARD_LINES,
    Z1_STANDARD_SUBTOTAL_CENTS,
    active_allocation,
    advance_to_assigned,
    assert_courier_counters,
    assert_fee_lines,
    assert_grant_ledger,
    assert_payer_mix,
    assert_window_occupancy,
    build_courier,
    build_network,
    build_out_for_delivery,
    build_queued_delivery,
    build_ready_order,
    build_window,
    exhaust_attempt_ladder,
    factories,
    latest_case,
    make_courier_headers,
    make_ops_headers,
    read_assignment,
    read_courier,
    read_delivery,
    read_grant,
    read_order,
    read_window,
    start_review,
    utc_ts,
    validate_error,
    validate_paginated,
    validate_success,
)

STANDARD_ORDER = {
    "rx_line_count": 1,
    "cold_chain_required": False,
    "controlled_schedule": "NONE",
    "total_rx_value_cents": 1000,
}
CONTROLLED_ORDER = {**STANDARD_ORDER, "controlled_schedule": "CII"}
LONG_WINDOW = {"window_end": utc_ts(3, 22), "capacity_slots": 1}

# Well-formed identifiers that name nothing, one per collection under test.
NO_SUCH_ORDER = "3f9c1a52-0000-4000-8000-000000000001"
NO_SUCH_PATIENT = "3f9c1a52-0000-4000-8000-000000000002"
NO_SUCH_WINDOW = "3f9c1a52-0000-4000-8000-000000000003"
NO_SUCH_COURIER = "3f9c1a52-0000-4000-8000-000000000004"
NO_SUCH_ASSIGNMENT = "3f9c1a52-0000-4000-8000-000000000005"
NO_SUCH_CASE = "3f9c1a52-0000-4000-8000-000000000006"
NO_SUCH_GRANT = "3f9c1a52-0000-4000-8000-000000000007"
NO_SUCH_ALLOCATION = "3f9c1a52-0000-4000-8000-000000000008"
NO_SUCH_ATTEMPT = "3f9c1a52-0000-4000-8000-000000000009"


def _error_id(refusal):
    """The id carried by a refusal, echoed back so several can be compared."""
    return refusal["error_id"]


# ─── Nine collections, nine 404 ids ───────────────────


@pytest.fixture
def a_reference_layer_and_nothing_else(api):
    """Payer, pool, site, zone and recipient exist; no order or delivery does."""
    return build_network(api)


class TestEachCollectionOwnsIts404:
    """"Every identifier segment in the path resolves to a stored row of the
    addressed collection — otherwise the 404 belonging to that collection:
    `ERR_ORDER_NOT_FOUND`, `ERR_DELIVERY_NOT_FOUND`, `ERR_WINDOW_NOT_FOUND`,
    `ERR_COURIER_NOT_FOUND`, `ERR_ASSIGNMENT_NOT_FOUND`,
    `ERR_EXCEPTION_CASE_NOT_FOUND`, `ERR_PLAN_GRANT_NOT_FOUND`,
    `ERR_ALLOCATION_NOT_FOUND`, `ERR_ATTEMPT_NOT_FOUND`, or
    `ERR_PATIENT_NOT_FOUND`."
    """

    def test_the_operational_collections_report_five_distinct_ids(
        self, api, a_reference_layer_and_nothing_else
    ):
        """An unknown order is never reported as an unknown window.

        "Existence is deliberately checked *after* scoping, so probing a real
        identifier belonging to another tenant yields 403 rather than leaking the
        difference between 404 and 200."

        Design: Corner/errors/every_collection_returns_its_own_not_found_id
        """
        net = a_reference_layer_and_nothing_else
        seen = [
            _error_id(
                validate_error(
                    api.get_pharmacy_order(NO_SUCH_ORDER, headers=net.pharmacy_headers),
                    "ERR_ORDER_NOT_FOUND",
                    404,
                )
            ),
            _error_id(
                validate_error(
                    api.get_delivery_window(NO_SUCH_WINDOW, headers=OPS_HEADERS),
                    "ERR_WINDOW_NOT_FOUND",
                    404,
                )
            ),
            _error_id(
                validate_error(
                    api.get_courier(NO_SUCH_COURIER, headers=OPS_HEADERS),
                    "ERR_COURIER_NOT_FOUND",
                    404,
                )
            ),
            _error_id(
                validate_error(
                    api.get_courier_assignment(NO_SUCH_ASSIGNMENT, headers=OPS_HEADERS),
                    "ERR_ASSIGNMENT_NOT_FOUND",
                    404,
                )
            ),
            _error_id(
                validate_error(
                    api.get_exception_case(NO_SUCH_CASE, headers=OPS_HEADERS),
                    "ERR_EXCEPTION_CASE_NOT_FOUND",
                    404,
                )
            ),
        ]
        assert len(set(seen)) == 5
        assert "ERR_INVALID_REQUEST" not in seen

    def test_the_money_and_history_collections_report_four_more(
        self, api, a_reference_layer_and_nothing_else
    ):
        """A body-carrying write reports the same collection id as a plain read does.

        "When a path carries an identifier, that identifier is resolved left to
        right and the first segment that names no stored row terminates the request
        with the 404 belonging to *that* collection"

        Design: Corner/errors/every_collection_returns_its_own_not_found_id
        """
        net = a_reference_layer_and_nothing_else
        seen = [
            _error_id(
                validate_error(
                    api.record_patient_consent(
                        NO_SUCH_PATIENT,
                        factories.consent_payload("REVOKED"),
                        headers=net.pharmacy_headers,
                    ),
                    "ERR_PATIENT_NOT_FOUND",
                    404,
                )
            ),
            _error_id(
                validate_error(
                    api.get_plan_grant(NO_SUCH_GRANT, headers=OPS_HEADERS),
                    "ERR_PLAN_GRANT_NOT_FOUND",
                    404,
                )
            ),
            _error_id(
                validate_error(
                    api.get_fee_allocation(NO_SUCH_ALLOCATION, headers=OPS_HEADERS),
                    "ERR_ALLOCATION_NOT_FOUND",
                    404,
                )
            ),
            _error_id(
                validate_error(
                    api.get_delivery_attempt(NO_SUCH_ATTEMPT, headers=OPS_HEADERS),
                    "ERR_ATTEMPT_NOT_FOUND",
                    404,
                )
            ),
        ]
        assert len(set(seen)) == 4

        _rows, meta = validate_paginated(api.list_plan_grants(OPS_HEADERS))
        assert meta["total_count"] == 1
        assert read_grant(api, net.grant["id"])["version"] == 1


# ─── Two ids for one order-state rule ─────────────────


@pytest.fixture
def a_bag_already_scheduled(api):
    """A reservation has driven the order to DISPATCHED."""
    return build_queued_delivery(api, order_kwargs=STANDARD_ORDER)


class TestTheIdNamesTheRequiredState:
    """"`PharmacyOrder.status` is the state the operation requires — otherwise
    `ERR_ORDER_NOT_READY` where `READY` is specifically required (reserving a
    delivery, holding an order), and `ERR_INVALID_ORDER_STATE` for the other
    mismatches (releasing to ready requires `INTAKE`; pickup requires
    `DISPATCHED`)."
    """

    def test_a_hold_wants_ready_and_says_so(self, api, a_bag_already_scheduled):
        """The operation that demands READY reports the not-ready id.

        "A release is reversible. Pulling a `READY` order back to `INTAKE` for
        re-verification requires the order to be `READY` — otherwise
        `ERR_ORDER_NOT_READY` — and requires `hold_count` to be below 2; the third
        attempt is rejected with `ERR_MAX_HOLDS_EXCEEDED`."

        Design: Corner/errors/one_priority_reports_order_not_ready_or_invalid_order_state_by_required_state
        """
        scn = a_bag_already_scheduled
        before = read_order(api, scn.order["id"])
        assert before["status"] == "DISPATCHED"

        validate_error(
            api.hold_order(scn.order["id"], headers=scn.pharmacy_headers),
            "ERR_ORDER_NOT_READY",
            409,
        )
        after = read_order(api, scn.order["id"])
        assert after["status"] == "DISPATCHED"
        assert after["hold_count"] == 0
        assert after["version"] == before["version"]

    def test_a_release_wants_intake_and_says_something_else(self, api, a_bag_already_scheduled):
        """One status, two ids, chosen by what each operation demanded.

        "attempting the release on an order that is not at `INTAKE` is
        `ERR_INVALID_ORDER_STATE`"

        Design: Corner/errors/one_priority_reports_order_not_ready_or_invalid_order_state_by_required_state
        """
        scn = a_bag_already_scheduled
        validate_error(
            api.mark_order_ready(scn.order["id"], headers=scn.pharmacy_headers),
            "ERR_INVALID_ORDER_STATE",
            409,
        )
        hold_id = _error_id(
            validate_error(
                api.hold_order(scn.order["id"], headers=scn.pharmacy_headers),
                "ERR_ORDER_NOT_READY",
                409,
            )
        )
        assert hold_id != "ERR_INVALID_ORDER_STATE"
        assert read_order(api, scn.order["id"])["status"] == "DISPATCHED"
        assert read_delivery(api, scn.delivery["id"])["custody_status"] == "QUEUED"


# ─── Shift state at both ends of the handshake ─────────


@pytest.fixture
def a_queued_bag_and_a_courier_off_shift(api):
    """Ray Ortiz was onboarded and left OFFLINE; the clock reads 13:45Z."""
    scn = build_queued_delivery(api, order_kwargs=STANDARD_ORDER)
    courier = build_courier(api, available=False)
    from_shift = read_courier(api, courier["id"])
    assert from_shift["status"] == "OFFLINE"
    return scn, courier


class TestOfflineIsRefusedTwice:
    """"it must not be `SUSPENDED` (`ERR_COURIER_SUSPENDED`) or `OFFLINE`
    (`ERR_COURIER_UNAVAILABLE`); and the buffered-interval rule still applies."
    """

    def test_an_offline_courier_cannot_be_named_at_dispatch(
        self, api, a_queued_bag_and_a_courier_off_shift
    ):
        """Going on shift is what changes the verdict for an unchanged call.

        "`Courier.status` is compatible with the operation — otherwise
        `ERR_COURIER_SUSPENDED` when the courier is `SUSPENDED` at dispatch or
        accept, `ERR_COURIER_UNAVAILABLE` when it is `OFFLINE` at dispatch or
        accept, and `ERR_INVALID_COURIER_STATE` for an illegal availability change
        (going `OFFLINE` while `active_delivery_count` is greater than 0, or a
        `Courier` trying to clear its own `SUSPENDED` status)."

        Design: Corner/errors/an_offline_courier_is_refused_at_dispatch_and_again_at_accept
        """
        scn, courier = a_queued_bag_and_a_courier_off_shift
        validate_error(
            api.dispatch_delivery(
                scn.delivery["id"],
                headers=OPS_HEADERS,
                payload=factories.dispatch_payload(courier["id"]),
            ),
            "ERR_COURIER_UNAVAILABLE",
            409,
        )
        _rows, meta = validate_paginated(
            api.list_courier_assignments(OPS_HEADERS, delivery_id=scn.delivery["id"])
        )
        assert meta["total_count"] == 0

        validate_success(
            api.set_courier_status(
                courier["id"],
                factories.courier_status_payload("AVAILABLE"),
                headers=make_courier_headers(courier["id"]),
            )
        )
        offer = validate_success(
            api.dispatch_delivery(
                scn.delivery["id"],
                headers=OPS_HEADERS,
                payload=factories.dispatch_payload(courier["id"]),
            ),
            201,
        )
        assert offer["status"] == "OFFERED"

    def test_going_offline_after_the_offer_blocks_the_acceptance(
        self, api, a_queued_bag_and_a_courier_off_shift
    ):
        """The outstanding offer does not pin the courier's availability.

        "A `Courier` accepting an offer must be the assignment's `courier_id`, the
        assignment must be `OFFERED` (`ERR_INVALID_ASSIGNMENT_STATE`), the clock
        must still be earlier than `offer_expires_at` (`ERR_OFFER_EXPIRED`), the
        courier's own `status` must be `AVAILABLE` or `ON_ROUTE`, and the delivery
        must still be `QUEUED`."

        Design: Corner/errors/an_offline_courier_is_refused_at_dispatch_and_again_at_accept
        """
        scn, courier = a_queued_bag_and_a_courier_off_shift
        headers = make_courier_headers(courier["id"])
        validate_success(
            api.set_courier_status(
                courier["id"], factories.courier_status_payload("AVAILABLE"), headers=headers
            )
        )
        offer = validate_success(
            api.dispatch_delivery(
                scn.delivery["id"],
                headers=OPS_HEADERS,
                payload=factories.dispatch_payload(courier["id"]),
            ),
            201,
        )
        off_shift = validate_success(
            api.set_courier_status(
                courier["id"], factories.courier_status_payload("OFFLINE"), headers=headers
            )
        )
        assert_courier_counters(off_shift, active_delivery_count=0, status="OFFLINE")

        validate_error(
            api.accept_assignment(offer["id"], headers=headers),
            "ERR_COURIER_UNAVAILABLE",
            409,
        )
        stalled = read_assignment(api, offer["id"])
        assert stalled["status"] == "OFFERED"
        assert stalled["responded_at"] is None
        waiting = read_delivery(api, scn.delivery["id"])
        assert waiting["custody_status"] == "QUEUED"
        assert waiting["excluded_courier_ids"] == []


# ─── Three ways for one window to refuse ──────────────


@pytest.fixture
def a_roomy_window_and_a_second_ready_bag(api):
    """A three-slot 14:00-16:00Z window holding one bag, and another bag waiting."""
    net = build_network(api)
    first_order = build_ready_order(api, net, **STANDARD_ORDER)
    second_order = build_ready_order(api, net, **STANDARD_ORDER)
    window = build_window(api, net.zone["id"], capacity_slots=3)
    scn = build_queued_delivery(api, net=net, order=first_order, window=window)
    return net, scn, second_order, window


def _reserve_again(api, net, order_id, window_id):
    """A raw reservation on the window's live version, so a refusal is inspectable."""
    version = read_window(api, window_id)["version"]
    return api.create_delivery(
        factories.delivery_payload(order_id, window_id, version),
        headers=net.pharmacy_headers,
    )


class TestTheWindowRefusesForThreeDifferentReasons:
    """"The clock is earlier than the target window's `window_end`, and for a *new*
    reservation on a `SCHEDULED` window the clock is at or before `window_start`
    minus two hours — otherwise `ERR_WINDOW_ELAPSED`."
    """

    def test_the_lead_in_and_the_end_boundary_share_one_id(
        self, api, a_roomy_window_and_a_second_ready_bag
    ):
        """Two clock positions, one id, and no status change behind either.

        "An `ON_DEMAND` window has no lead-time requirement."

        Design: Corner/errors/lead_time_window_end_and_the_closed_flag_are_three_separate_rejections
        """
        net, _scn, second_order, window = a_roomy_window_and_a_second_ready_bag
        validate_success(api.set_clock(utc_ts(3, 13), headers=OPS_HEADERS))
        validate_error(
            _reserve_again(api, net, second_order["id"], window["id"]),
            "ERR_WINDOW_ELAPSED",
            409,
        )
        assert_window_occupancy(
            read_window(api, window["id"]), reserved_slots=1, available_slots=2, status="OPEN"
        )

        validate_success(api.set_clock(utc_ts(3, 16, 30), headers=OPS_HEADERS))
        validate_error(
            _reserve_again(api, net, second_order["id"], window["id"]),
            "ERR_WINDOW_ELAPSED",
            409,
        )
        assert read_window(api, window["id"])["status"] == "OPEN"

    def test_the_closed_flag_takes_over_from_the_clock_after_the_sweep(
        self, api, a_roomy_window_and_a_second_ready_bag
    ):
        """The status flag is a different judgement from the clock comparison.

        "the window must not be `CLOSED` or `FULL` by status flag, or the request is
        `ERR_WINDOW_CLOSED`"

        Design: Corner/errors/lead_time_window_end_and_the_closed_flag_are_three_separate_rejections
        """
        net, _scn, second_order, window = a_roomy_window_and_a_second_ready_bag
        validate_success(api.set_clock(utc_ts(3, 16, 30), headers=OPS_HEADERS))
        report = validate_success(api.run_routing_sweep(OPS_HEADERS))
        assert report["closed_window_count"] == 1
        assert read_window(api, window["id"])["status"] == "CLOSED"

        validate_error(
            _reserve_again(api, net, second_order["id"], window["id"]),
            "ERR_WINDOW_CLOSED",
            409,
        )
        _rows, meta = validate_paginated(
            api.list_deliveries(OPS_HEADERS, order_id=second_order["id"])
        )
        assert meta["total_count"] == 0
        assert read_window(api, window["id"])["reserved_slots"] == 1
        assert read_order(api, second_order["id"])["status"] == "READY"


# ─── The payer year comes from the window ─────────────


@pytest.fixture
def a_pool_funded_for_next_year_only(api):
    """Meridian's only pool is for benefit year 2027; two windows straddle the years."""
    net = build_network(api, grant={"benefit_year": 2027})
    this_year_order = build_ready_order(api, net, **STANDARD_ORDER)
    next_year_order = build_ready_order(api, net, **STANDARD_ORDER)
    this_year_window = build_window(api, net.zone["id"], capacity_slots=1)
    next_year_window = build_window(
        api,
        net.zone["id"],
        window_start=utc_ts(5, 14, month=1, year=2027),
        window_end=utc_ts(5, 16, month=1, year=2027),
        capacity_slots=1,
    )
    return net, this_year_order, next_year_order, this_year_window, next_year_window


class TestTheBenefitYearIsReadOffTheWindow:
    """"Choosing the pool is deterministic and happens before any of the
    arithmetic: among the order's plan's `ACTIVE` pools whose `benefit_year` equals
    the UTC calendar year of the target window's `window_start`, the one with the
    lowest `created_at` wins. If the plan has none, the reservation fails with
    `ERR_GRANT_NOT_APPLICABLE`."
    """

    def test_a_window_in_an_unfunded_year_is_refused(
        self, api, a_pool_funded_for_next_year_only
    ):
        """The clock stands in 2026 and so does the window, yet the pool does not.

        "The `benefit_year` is matched against the UTC calendar year of a delivery
        window's `window_start`, not against the clock at the time of the request, so
        a December order for a January window draws on next year's money."

        Design: Corner/errors/grant_applicability_is_keyed_to_the_window_start_year_not_the_clock_year
        """
        net, this_year_order, _next, this_year_window, _next_window = (
            a_pool_funded_for_next_year_only
        )
        assert net.grant["benefit_year"] == 2027
        validate_error(
            _reserve_again(api, net, this_year_order["id"], this_year_window["id"]),
            "ERR_GRANT_NOT_APPLICABLE",
            409,
        )
        assert_grant_ledger(read_grant(api, net.grant["id"]), committed_cents=0, consumed_cents=0)
        assert read_order(api, this_year_order["id"])["status"] == "READY"
        assert_window_occupancy(
            read_window(api, this_year_window["id"]), reserved_slots=0, status="OPEN"
        )

    def test_the_same_pool_funds_a_window_that_starts_next_year(
        self, api, a_pool_funded_for_next_year_only
    ):
        """One clock instant, two verdicts, decided by each window's start year.

        "The resulting `FeeAllocation` is written with `delivery_id`, `variant`
        `PROVISIONAL`, and `status` `ACTIVE`, its `plan_grant_cents` is added to the
        pool's `committed_cents`, the pool's `remaining_cents` and `status` are
        recomputed, and the delivery's `fee_subtotal_cents` mirrors the
        allocation's."

        Design: Corner/errors/grant_applicability_is_keyed_to_the_window_start_year_not_the_clock_year
        """
        net, _this, next_year_order, _this_window, next_year_window = (
            a_pool_funded_for_next_year_only
        )
        delivery = validate_success(
            _reserve_again(api, net, next_year_order["id"], next_year_window["id"]), 201
        )
        assert delivery["custody_status"] == "QUEUED"
        assert delivery["fee_subtotal_cents"] == Z1_STANDARD_SUBTOTAL_CENTS

        allocation = active_allocation(api, delivery["id"])
        assert_fee_lines(allocation, Z1_STANDARD_LINES)
        assert_payer_mix(
            allocation,
            patient_gross_share_cents=157,
            plan_grant_cents=150,
            pharmacy_absorption_cents=7,
            patient_payable_cents=0,
            pharmacy_payable_cents=1416,
        )
        assert allocation["plan_grant_id"] == net.grant["id"]
        assert_grant_ledger(
            read_grant(api, net.grant["id"]), committed_cents=150, remaining_cents=99850
        )
        assert read_order(api, next_year_order["id"])["status"] == "DISPATCHED"


# ─── Four capability ids at an override ───────────────


@pytest.fixture
def a_controlled_bag_and_three_couriers(api):
    """A CII bag on a Z1 scheduled window, with one gap in each of two couriers."""
    scn = build_queued_delivery(api, order_kwargs=CONTROLLED_ORDER)
    uncertified = build_courier(api, controlled_certified=False)
    wrong_mode = build_courier(api, display_name="Tova Mies", mode="ON_DEMAND")
    qualified = build_courier(api, display_name="Kai Ross")
    validate_success(api.set_clock(utc_ts(3, 13, 45), headers=OPS_HEADERS))
    return scn, uncertified, wrong_mode, qualified


class TestEachCapabilityFailsUnderItsOwnId:
    """"The named courier must be `cold_chain_equipped` for a cold bag
    (`ERR_COURIER_NOT_COLD_CERTIFIED`), `controlled_certified` for a controlled bag
    (`ERR_COURIER_NOT_CONTROLLED_CERTIFIED`), serve the window zone's `zone_code`
    (`ERR_COURIER_ZONE_NOT_SERVED`), and have a `mode` matching the window's
    `courier_mode` (`ERR_COURIER_MODE_MISMATCH`)"
    """

    def test_the_missing_certification_is_named(self, api, a_controlled_bag_and_three_couriers):
        """The bag's snapshotted class is what the certification is checked against.

        "a `CII` schedule demands `GOVT_ID_SCAN`"

        Design: Corner/errors/controlled_certification_and_courier_mode_are_checked_independently_at_dispatch
        """
        scn, uncertified, _wrong_mode, _qualified = a_controlled_bag_and_three_couriers
        pending = read_delivery(api, scn.delivery["id"])
        assert pending["handling_class"] == "CONTROLLED"
        assert pending["signature_required"] is True
        assert pending["required_id_verification"] == "GOVT_ID_SCAN"

        validate_error(
            api.dispatch_delivery(
                scn.delivery["id"],
                headers=OPS_HEADERS,
                payload=factories.dispatch_payload(uncertified["id"]),
            ),
            "ERR_COURIER_NOT_CONTROLLED_CERTIFIED",
            409,
        )
        assert read_delivery(api, scn.delivery["id"])["excluded_courier_ids"] == []

    def test_passing_the_certification_does_not_excuse_the_mode(
        self, api, a_controlled_bag_and_three_couriers
    ):
        """Two independent gates, two ids, and only the courier clearing both is offered.

        "These four certification checks are unreachable through the selector, which
        filters rather than complains."

        Design: Corner/errors/controlled_certification_and_courier_mode_are_checked_independently_at_dispatch
        """
        scn, _uncertified, wrong_mode, qualified = a_controlled_bag_and_three_couriers
        assert wrong_mode["controlled_certified"] is True
        assert wrong_mode["mode"] == "ON_DEMAND"
        validate_error(
            api.dispatch_delivery(
                scn.delivery["id"],
                headers=OPS_HEADERS,
                payload=factories.dispatch_payload(wrong_mode["id"]),
            ),
            "ERR_COURIER_MODE_MISMATCH",
            409,
        )

        offer = validate_success(
            api.dispatch_delivery(
                scn.delivery["id"],
                headers=OPS_HEADERS,
                payload=factories.dispatch_payload(qualified["id"]),
            ),
            201,
        )
        assert offer["courier_id"] == qualified["id"]
        assert offer["status"] == "OFFERED"
        assert offer["rank_score"] == pytest.approx(0.00, abs=0.01)
        assert read_delivery(api, scn.delivery["id"])["excluded_courier_ids"] == []


# ─── One order, two rules against a second reship ─────


@pytest.fixture
def a_reshipped_bag_with_a_second_case_under_review(api):
    """The returned bag already has a live reship, and a DAMAGED case is under review."""
    reship_window_start = utc_ts(4, 14)
    scn = build_out_for_delivery(
        api, order_kwargs=STANDARD_ORDER, window_kwargs=LONG_WINDOW, depart_clock=utc_ts(3, 14)
    )
    reship_window = build_window(
        api,
        scn.net.zone["id"],
        window_start=reship_window_start,
        window_end=utc_ts(4, 16),
        capacity_slots=2,
    )
    exhaust_attempt_ladder(api, scn)
    scn.delivery = validate_success(
        api.confirm_return(scn.delivery["id"], headers=scn.pharmacy_headers)
    )

    first_case = latest_case(api, scn.delivery["id"])
    start_review(api, first_case["id"])
    validate_success(
        api.adjudicate_exception_case(
            first_case["id"],
            factories.adjudication_payload(
                "RESHIP",
                read_delivery(api, scn.delivery["id"])["version"],
                reship_window_id=reship_window["id"],
            ),
            headers=make_ops_headers(OPS_USER_A),
        )
    )
    reships, _meta = validate_paginated(
        api.list_deliveries(OPS_HEADERS, reship_of_delivery_id=scn.delivery["id"])
    )
    assert len(reships) == 1

    second_case = validate_success(
        api.open_exception_case(
            factories.exception_case_payload(scn.delivery["id"], "DAMAGED"),
            headers=make_ops_headers(OPS_USER_B),
        ),
        201,
    )
    start_review(api, second_case["id"], headers=make_ops_headers(OPS_USER_B))
    return scn, reship_window, first_case, second_case, reships[0]


def _adjudicate_reship(api, case_id, delivery_id, window_id):
    """A second-reship attempt by an operator who neither opened nor revoked anything."""
    return api.adjudicate_exception_case(
        case_id,
        factories.adjudication_payload(
            "RESHIP",
            read_delivery(api, delivery_id)["version"],
            reship_window_id=window_id,
        ),
        headers=make_ops_headers(OPS_USER_C),
    )


class TestTheOrderRuleSpeaksBeforeTheReshipRule:
    """"One delivery may spawn at most one reship, and because a reship delivery on
    the same order is itself a live delivery, a *second* reship attempt on that
    order trips `ERR_DUPLICATE_ACTIVE_DELIVERY` ahead of the weaker reship-conflict
    rule."
    """

    def test_the_live_reship_delivery_blocks_the_second_authorisation(
        self, api, a_reshipped_bag_with_a_second_case_under_review
    ):
        """While the reship is alive it is the order-level rule that answers.

        "The order has no delivery other than the one addressed by the request whose
        `custody_status` is something other than `CANCELLED` or `RETURNED` —
        otherwise `ERR_DUPLICATE_ACTIVE_DELIVERY`."

        Design: Corner/errors/a_second_reship_hits_the_duplicate_delivery_rule_before_the_reship_conflict_rule
        """
        scn, reship_window, _first_case, second_case, reship = (
            a_reshipped_bag_with_a_second_case_under_review
        )
        assert reship["custody_status"] == "QUEUED"
        validate_error(
            _adjudicate_reship(
                api, second_case["id"], scn.delivery["id"], reship_window["id"]
            ),
            "ERR_DUPLICATE_ACTIVE_DELIVERY",
            409,
        )
        stalled = validate_success(
            api.get_exception_case(second_case["id"], headers=OPS_HEADERS)
        )
        assert stalled["status"] == "UNDER_REVIEW"
        assert stalled["disposition"] is None
        assert stalled["adjudicated_by_ops_user_id"] is None

    def test_cancelling_the_reship_uncovers_the_linkage_rule(
        self, api, a_reshipped_bag_with_a_second_case_under_review
    ):
        """The weaker rule was preempted, not replaced: it speaks once the bag is gone.

        "A missing `reship_window_id`, or a delivery already linked to a reship, is
        `ERR_OVERRIDE_ADJUDICATION_CONFLICT`; a wrong zone is `ERR_ZONE_MISMATCH`; a
        wrong mode is `ERR_WINDOW_MODE_MISMATCH`; a window with no room is
        `ERR_WINDOW_FULL`."

        Design: Corner/errors/a_second_reship_hits_the_duplicate_delivery_rule_before_the_reship_conflict_rule
        """
        scn, reship_window, first_case, second_case, reship = (
            a_reshipped_bag_with_a_second_case_under_review
        )
        validate_error(
            _adjudicate_reship(
                api, second_case["id"], scn.delivery["id"], reship_window["id"]
            ),
            "ERR_DUPLICATE_ACTIVE_DELIVERY",
            409,
        )

        cancelled = validate_success(
            api.cancel_delivery(reship["id"], headers=scn.pharmacy_headers)
        )
        assert cancelled["custody_status"] == "CANCELLED"
        assert cancelled["settlement_status"] == "VOIDED"
        assert cancelled["fee_subtotal_cents"] == 0
        assert read_order(api, scn.order["id"])["status"] == "RETURNED_TO_STOCK"

        validate_error(
            _adjudicate_reship(
                api, second_case["id"], scn.delivery["id"], reship_window["id"]
            ),
            "ERR_OVERRIDE_ADJUDICATION_CONFLICT",
            409,
        )
        linked = validate_success(api.get_exception_case(first_case["id"], headers=OPS_HEADERS))
        assert linked["reship_delivery_id"] == reship["id"]
        assert_window_occupancy(
            read_window(api, reship_window["id"]), reserved_slots=0, status="OPEN"
        )
        _rows, meta = validate_paginated(
            api.list_deliveries(OPS_HEADERS, order_id=scn.order["id"])
        )
        assert meta["total_count"] == 2


# ─── The assignment guard reads status ────────────────


@pytest.fixture
def an_accepted_leg(api):
    """Ray accepted the bag at 13:45Z, so the assignment is ACCEPTED."""
    scn = build_queued_delivery(api, order_kwargs=STANDARD_ORDER)
    advance_to_assigned(api, scn)
    return scn


class TestDeclineAndRevokeHaveDifferentDomains:
    """"`CourierAssignment.status` is `OFFERED` for accept and decline, and either
    `OFFERED` or `ACCEPTED` for revoke — otherwise `ERR_INVALID_ASSIGNMENT_STATE`;
    then, for accept only, the clock is earlier than `offer_expires_at` — otherwise
    `ERR_OFFER_EXPIRED`."
    """

    def test_an_accepted_assignment_can_no_longer_be_declined(self, api, an_accepted_leg):
        """Decline is an offer-only action, and acceptance has already passed it by.

        "Declining requires the same ownership and the same `OFFERED` status."

        Design: Corner/errors/assignment_actions_are_rejected_once_the_assignment_leaves_offered
        """
        scn = an_accepted_leg
        assert scn.assignment["status"] == "ACCEPTED"
        validate_error(
            api.decline_assignment(scn.assignment["id"], headers=scn.courier_headers),
            "ERR_INVALID_ASSIGNMENT_STATE",
            409,
        )
        assert read_assignment(api, scn.assignment["id"])["status"] == "ACCEPTED"
        assert read_delivery(api, scn.delivery["id"])["custody_status"] == "ASSIGNED"

    def test_revoke_succeeds_once_and_the_replay_fails_on_the_new_status(
        self, api, an_accepted_leg
    ):
        """The guard reads the current status rather than counting calls.

        "It sets the assignment to `REVOKED`, stamps `revoked_by_ops_user_id` with
        the acting `X-User-ID`, appends the courier to `excluded_courier_ids`, and —
        when custody was `ASSIGNED` — walks it back `ASSIGNED → QUEUED` and nulls
        the delivery's `courier_id`."

        Design: Corner/errors/assignment_actions_are_rejected_once_the_assignment_leaves_offered
        """
        scn = an_accepted_leg
        revoked = validate_success(
            api.revoke_assignment(scn.assignment["id"], headers=OPS_HEADERS)
        )
        assert revoked["status"] == "REVOKED"
        assert revoked["revoked_by_ops_user_id"] == OPS_USER_A

        released = read_delivery(api, scn.delivery["id"])
        assert released["custody_status"] == "QUEUED"
        assert released["courier_id"] is None
        assert released["excluded_courier_ids"] == [scn.courier["id"]]
        assert_courier_counters(
            read_courier(api, scn.courier["id"]), active_delivery_count=0, status="AVAILABLE"
        )

        validate_error(
            api.revoke_assignment(scn.assignment["id"], headers=OPS_HEADERS),
            "ERR_INVALID_ASSIGNMENT_STATE",
            409,
        )
        assert_courier_counters(
            read_courier(api, scn.courier["id"]), active_delivery_count=0, status="AVAILABLE"
        )
