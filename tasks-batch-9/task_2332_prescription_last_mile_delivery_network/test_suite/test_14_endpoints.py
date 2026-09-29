"""Endpoint contracts: the bulk sweep, the computed read, and the two-mode write.

These groups exercise surfaces whose behaviour is a property of the endpoint
rather than of one field: the sweep that does three unrelated jobs in one pass and
reports each in its own counter, the read that writes an audit row as a side
effect, the dispatch whose optional field selects between two modes, the lazily
evaluated offer deadline, the settle guard on each of the two status dimensions,
the clock that every later timestamp is stamped from, and the body foreign key
that doubles as a list filter.
"""

import pytest

from test_helpers import (
    OPS_HEADERS,
    ZONE_Z2,
    Z1_STANDARD_SUBTOTAL_CENTS,
    advance_to_assigned,
    allocations_for,
    assert_append_only_record,
    assert_courier_counters,
    assert_courier_projection_shape,
    assert_grant_ledger,
    assert_instant,
    build_courier,
    build_health_plan,
    build_network,
    build_out_for_delivery,
    build_plan_grant,
    build_queued_delivery,
    build_ready_order,
    build_window,
    build_zone,
    deliver,
    factories,
    find_by,
    make_courier_headers,
    masked,
    read_assignment,
    read_courier,
    read_delivery,
    read_grant,
    read_order,
    read_window,
    reserve_delivery,
    set_clock,
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
UNKNOWN_PLAN_ID = "3f9c1a52-0000-4000-8000-000000000abc"


# ─── The routing sweep ────────────────────────────────


@pytest.fixture
def a_stale_offer_an_elapsed_window_and_a_waiting_bag(api):
    """Three jobs waiting for one sweep, and only one courier to do the work.

    Ray was offered the older Z1 bag at 13:45Z; a second bag sits queued behind
    it; and an untouched ON_DEMAND window in zone Z2 ended at 13:00Z. The clock
    now reads 13:56Z, so the offer is stale and the Z2 window is elapsed.
    """
    net = build_network(api)
    first_order = build_ready_order(api, net, **STANDARD_ORDER)
    second_order = build_ready_order(api, net, **STANDARD_ORDER)
    window = build_window(api, net.zone["id"], capacity_slots=2)

    far_zone = build_zone(api, **ZONE_Z2)
    elapsed = build_window(
        api,
        far_zone["id"],
        courier_mode="ON_DEMAND",
        window_start=utc_ts(3, 11),
        window_end=utc_ts(3, 13),
        capacity_slots=1,
    )

    older = reserve_delivery(api, net, first_order["id"], window["id"])
    younger = reserve_delivery(api, net, second_order["id"], window["id"])
    courier = build_courier(api)

    set_clock(api, utc_ts(3, 13, 45))
    offer = validate_success(
        api.dispatch_delivery(
            older["id"], headers=OPS_HEADERS, payload=factories.dispatch_payload(courier["id"])
        ),
        201,
    )
    set_clock(api, utc_ts(3, 13, 56))
    return net, window, elapsed, older, younger, courier, offer


class TestOneSweepDoesThreeJobs:
    """"The response reports `expired_offer_count`, `closed_window_count`,
    `offers_created_count`, and `offered_delivery_ids`. Every row the sweep touches
    bumps its own `version`."
    """

    def test_each_pass_reports_its_own_count(
        self, api, a_stale_offer_an_elapsed_window_and_a_waiting_bag
    ):
        """Expiry, closure and offer creation are counted separately in one response.

        "First, every assignment still `OFFERED` whose `offer_expires_at` the clock
        has reached or passed moves `OFFERED → EXPIRED`, appending its courier to
        that delivery's `excluded_courier_ids`."

        Design: Corner/endpoints/routing_run_sweeps_expiry_window_closure_and_offer_creation_in_one_pass
        """
        _net, window, elapsed, older, younger, _courier, offer = (
            a_stale_offer_an_elapsed_window_and_a_waiting_bag
        )
        report = validate_success(api.run_routing_sweep(OPS_HEADERS))
        assert report["expired_offer_count"] == 1
        assert report["closed_window_count"] == 1
        assert report["offers_created_count"] == 1
        assert report["offered_delivery_ids"] == [younger["id"]]

        assert read_assignment(api, offer["id"])["status"] == "EXPIRED"
        assert read_window(api, elapsed["id"])["status"] == "CLOSED"
        assert read_window(api, window["id"])["status"] == "FULL"
        assert read_delivery(api, older["id"])["custody_status"] == "QUEUED"

    def test_the_expired_courier_is_excluded_and_the_next_sweep_is_a_no_op(
        self, api, a_stale_offer_an_elapsed_window_and_a_waiting_bag
    ):
        """The passes interact: the exclusion written first empties the pool later.

        "deliveries whose pool is empty are skipped silently rather than erroring"

        Design: Corner/endpoints/routing_run_sweeps_expiry_window_closure_and_offer_creation_in_one_pass
        """
        _net, _window, _elapsed, older, younger, courier, _offer = (
            a_stale_offer_an_elapsed_window_and_a_waiting_bag
        )
        validate_success(api.run_routing_sweep(OPS_HEADERS))

        assert read_delivery(api, older["id"])["excluded_courier_ids"] == [courier["id"]]
        rows, _meta = validate_paginated(
            api.list_courier_assignments(OPS_HEADERS, delivery_id=younger["id"])
        )
        fresh = rows[0]
        assert fresh["courier_id"] == courier["id"]
        assert fresh["status"] == "OFFERED"
        assert fresh["rank_score"] == pytest.approx(100.00, abs=0.01)
        assert_instant(fresh["offer_expires_at"], utc_ts(3, 14, 6))

        again = validate_success(api.run_routing_sweep(OPS_HEADERS))
        assert again["expired_offer_count"] == 0
        assert again["closed_window_count"] == 0
        assert again["offers_created_count"] == 0
        assert again["offered_delivery_ids"] == []


# ─── The courier-limited projection ───────────────────


@pytest.fixture
def a_bag_a_courier_may_look_at(api):
    """A 30000-cent bag accepted by Ray Ortiz, whose view of it is about to be read."""
    scn = build_queued_delivery(
        api, order_kwargs={**STANDARD_ORDER, "total_rx_value_cents": 30000}
    )
    advance_to_assigned(api, scn)
    return scn


class TestCourierViewIsAReadThatWrites:
    """"Couriers are third parties. They never receive a delivery's full record;
    they receive a **courier-limited projection**, and every release of that
    projection is logged as a `CourierDataDisclosure` row that cannot afterwards be
    edited."
    """

    def test_the_projection_carries_thirteen_values_and_masks_the_name(
        self, api, a_bag_a_courier_may_look_at
    ):
        """A limited data set: masked name, last four digits, address and flags.

        "`masked_name` is derived from `full_name` by splitting it on whitespace
        and, in each resulting token, keeping the first character and replacing
        every remaining character with an asterisk"

        Design: Corner/endpoints/courier_view_returns_a_minimized_projection_and_appends_a_disclosure_row
        """
        scn = a_bag_a_courier_may_look_at
        view = validate_success(
            api.get_courier_view(scn.delivery["id"], headers=scn.courier_headers)
        )
        assert_courier_projection_shape(view)

        assert view["patient_masked_name"] == masked("Dana Reyes")
        assert view["patient_phone_last4"] == "4417"
        assert view["address_line"] == "881 Alder St"
        assert_instant(view["window_start"], utc_ts(3, 14))
        assert view["handling_class"] == "STANDARD"
        assert view["signature_required"] is True
        assert view["required_id_verification"] == "PHOTO_ID"
        assert view["rx_line_count"] == 1
        assert view["redacted_field_count"] == 6

    def test_two_reads_leave_two_audit_rows_with_the_purposes_requested(
        self, api, a_bag_a_courier_may_look_at
    ):
        """The default purpose applies when the caller does not say, and both ends see it.

        "Whenever a courier is shown the courier-limited projection of §2.11 — or
        an operations user previews that same view, in which case the logged
        `courier_id` is null — a disclosure row is appended with a `purpose` of
        `ROUTING` or `DELIVERY_EXECUTION`, defaulting to `DELIVERY_EXECUTION` when
        the caller does not say."

        Design: Corner/endpoints/courier_view_returns_a_minimized_projection_and_appends_a_disclosure_row
        """
        scn = a_bag_a_courier_may_look_at
        first = validate_success(
            api.get_courier_view(scn.delivery["id"], headers=scn.courier_headers)
        )
        second = validate_success(
            api.get_courier_view(
                scn.delivery["id"], headers=scn.courier_headers, purpose="ROUTING"
            )
        )
        assert first["disclosure_id"] != second["disclosure_id"]

        rows, meta = validate_paginated(
            api.list_courier_disclosures(scn.courier["id"], scn.courier_headers)
        )
        assert meta["total_count"] == 2
        for row in rows:
            assert_append_only_record(row)
            assert row["minimization_profile"] == "COURIER_LIMITED"
            assert_instant(row["disclosed_at"], utc_ts(3, 13, 45))
        assert find_by(rows, id=first["disclosure_id"])["purpose"] == "DELIVERY_EXECUTION"
        assert find_by(rows, id=second["disclosure_id"])["purpose"] == "ROUTING"

        from_the_pharmacy, pharmacy_meta = validate_paginated(
            api.list_delivery_disclosures(scn.delivery["id"], scn.pharmacy_headers)
        )
        assert pharmacy_meta["total_count"] == 2
        assert sorted(row["id"] for row in from_the_pharmacy) == sorted(
            [first["disclosure_id"], second["disclosure_id"]]
        )


# ─── Dispatch has two modes ───────────────────────────


@pytest.fixture
def two_local_couriers_and_one_from_the_next_zone(api):
    """Ray and Tova both serve Z1; Kai serves only Z2 and may not be handed the bag.

    Ray is onboarded first and Tova half an hour later, so the selector's
    `created_at` tie-break would settle an unqualified dispatch in Ray's favour.
    """
    scn = build_queued_delivery(api, order_kwargs=STANDARD_ORDER)
    build_zone(api, **ZONE_Z2)
    ray = build_courier(api)
    set_clock(api, utc_ts(3, 9, 30))
    tova = build_courier(api, display_name="Tova Mies")
    set_clock(api, utc_ts(3, 9, 45))
    kai = build_courier(api, display_name="Kai Ross", served_zone_codes=["Z2"])
    set_clock(api, utc_ts(3, 13, 45))
    return scn, ray, tova, kai


class TestOverrideSkipsRankingNotEligibility:
    """"When a dispatch names an explicit `courier_id`, ranking is bypassed but
    safety is not."
    """

    def test_a_named_courier_from_the_wrong_zone_is_still_refused(
        self, api, two_local_couriers_and_one_from_the_next_zone
    ):
        """The four certification gates survive the override.

        "The named courier must be `cold_chain_equipped` for a cold bag
        (`ERR_COURIER_NOT_COLD_CERTIFIED`), `controlled_certified` for a controlled
        bag (`ERR_COURIER_NOT_CONTROLLED_CERTIFIED`), serve the window zone's
        `zone_code` (`ERR_COURIER_ZONE_NOT_SERVED`), and have a `mode` matching the
        window's `courier_mode` (`ERR_COURIER_MODE_MISMATCH`)"

        Design: Corner/endpoints/explicit_courier_id_bypasses_ranking_but_not_the_capability_gates
        """
        scn, _ray, _tova, kai = two_local_couriers_and_one_from_the_next_zone
        validate_error(
            api.dispatch_delivery(
                scn.delivery["id"],
                headers=OPS_HEADERS,
                payload=factories.dispatch_payload(kai["id"]),
            ),
            "ERR_COURIER_ZONE_NOT_SERVED",
            409,
        )
        _rows, meta = validate_paginated(
            api.list_courier_assignments(OPS_HEADERS, delivery_id=scn.delivery["id"])
        )
        assert meta["total_count"] == 0

    def test_naming_the_second_ranked_courier_is_what_changes_the_outcome(
        self, api, two_local_couriers_and_one_from_the_next_zone
    ):
        """The bag goes to Tova although the ranking would have chosen Ray.

        "a `rank_score` holding the selected courier's `rolling_reliability_score`
        at selection time — or 0.00 when the offer came from an operator override"

        Design: Corner/endpoints/explicit_courier_id_bypasses_ranking_but_not_the_capability_gates
        """
        scn, ray, tova, kai = two_local_couriers_and_one_from_the_next_zone
        validate_error(
            api.dispatch_delivery(
                scn.delivery["id"],
                headers=OPS_HEADERS,
                payload=factories.dispatch_payload(kai["id"]),
            ),
            "ERR_COURIER_ZONE_NOT_SERVED",
            409,
        )

        assert ray["rolling_reliability_score"] == pytest.approx(100.00, abs=0.01)
        assert tova["rolling_reliability_score"] == pytest.approx(100.00, abs=0.01)
        assert ray["created_at"] < tova["created_at"]

        assignment = validate_success(
            api.dispatch_delivery(
                scn.delivery["id"],
                headers=OPS_HEADERS,
                payload=factories.dispatch_payload(tova["id"]),
            ),
            201,
        )
        assert assignment["courier_id"] == tova["id"]
        assert assignment["rank_score"] == pytest.approx(0.00, abs=0.01)

        _rows, meta = validate_paginated(
            api.list_courier_assignments(OPS_HEADERS, delivery_id=scn.delivery["id"])
        )
        assert meta["total_count"] == 1
        assert read_delivery(api, scn.delivery["id"])["custody_status"] == "QUEUED"


# ─── The offer deadline ───────────────────────────────


@pytest.fixture
def offers_minted_one_minute_apart(api):
    """Ray's offer was made at 13:45Z and Tova's at 13:46Z; the clock reads 13:55Z."""
    net = build_network(api)
    first_order = build_ready_order(api, net, **STANDARD_ORDER)
    second_order = build_ready_order(api, net, **STANDARD_ORDER)
    window = build_window(api, net.zone["id"], capacity_slots=2)
    older = reserve_delivery(api, net, first_order["id"], window["id"])
    younger = reserve_delivery(api, net, second_order["id"], window["id"])

    ray = build_courier(api)
    tova = build_courier(api, display_name="Tova Mies")

    set_clock(api, utc_ts(3, 13, 45))
    stale = validate_success(
        api.dispatch_delivery(
            older["id"], headers=OPS_HEADERS, payload=factories.dispatch_payload(ray["id"])
        ),
        201,
    )
    set_clock(api, utc_ts(3, 13, 46))
    fresh = validate_success(
        api.dispatch_delivery(
            younger["id"], headers=OPS_HEADERS, payload=factories.dispatch_payload(tova["id"])
        ),
        201,
    )
    set_clock(api, utc_ts(3, 13, 55))
    return older, younger, ray, tova, stale, fresh


class TestOfferExpiryIsPerAssignment:
    """"A `Courier` accepting an offer must be the assignment's `courier_id`, the
    assignment must be `OFFERED` (`ERR_INVALID_ASSIGNMENT_STATE`), the clock must
    still be earlier than `offer_expires_at` (`ERR_OFFER_EXPIRED`), the courier's
    own `status` must be `AVAILABLE` or `ON_ROUTE`, and the delivery must still be
    `QUEUED`."
    """

    def test_accepting_at_the_deadline_instant_is_refused(
        self, api, offers_minted_one_minute_apart
    ):
        """The comparison is strict: the deadline instant itself is too late.

        "an `offer_expires_at` ten minutes later"

        Design: Corner/endpoints/acceptance_at_the_exact_offer_expiry_is_rejected_while_a_younger_offer_is_admitted
        """
        older, _younger, ray, _tova, stale, _fresh = offers_minted_one_minute_apart
        assert_instant(stale["offer_expires_at"], utc_ts(3, 13, 55))

        validate_error(
            api.accept_assignment(stale["id"], headers=make_courier_headers(ray["id"])),
            "ERR_OFFER_EXPIRED",
            409,
        )
        assert read_assignment(api, stale["id"])["status"] == "OFFERED"

        untouched = read_delivery(api, older["id"])
        assert untouched["custody_status"] == "QUEUED"
        assert untouched["courier_id"] is None
        assert untouched["excluded_courier_ids"] == []
        assert_courier_counters(
            read_courier(api, ray["id"]), active_delivery_count=0, status="AVAILABLE"
        )

    def test_the_offer_minted_one_minute_later_is_still_alive(
        self, api, offers_minted_one_minute_apart
    ):
        """One clock value, two verdicts, because each offer carries its own deadline.

        "Acceptance sets the assignment to `ACCEPTED` with `responded_at` from the
        clock, advances the delivery `QUEUED → ASSIGNED` and writes its
        `courier_id`, raises the courier's `active_delivery_count` by one, and moves
        the courier `AVAILABLE → ON_ROUTE`."

        Design: Corner/endpoints/acceptance_at_the_exact_offer_expiry_is_rejected_while_a_younger_offer_is_admitted
        """
        _older, younger, ray, tova, stale, fresh = offers_minted_one_minute_apart
        validate_error(
            api.accept_assignment(stale["id"], headers=make_courier_headers(ray["id"])),
            "ERR_OFFER_EXPIRED",
            409,
        )

        accepted = validate_success(
            api.accept_assignment(fresh["id"], headers=make_courier_headers(tova["id"]))
        )
        assert accepted["status"] == "ACCEPTED"
        assert_instant(accepted["responded_at"], utc_ts(3, 13, 55))

        assigned = read_delivery(api, younger["id"])
        assert assigned["custody_status"] == "ASSIGNED"
        assert assigned["courier_id"] == tova["id"]
        assert_courier_counters(
            read_courier(api, tova["id"]), active_delivery_count=1, status="ON_ROUTE"
        )
        assert_courier_counters(
            read_courier(api, ray["id"]), active_delivery_count=0, status="AVAILABLE"
        )


# ─── Settlement guards both dimensions ────────────────


@pytest.fixture
def a_bag_at_the_door_before_any_money_moves(api):
    """A plain 1000-cent bag out for delivery at 14:00Z, nothing settled yet."""
    return build_out_for_delivery(
        api, order_kwargs=STANDARD_ORDER, depart_clock=utc_ts(3, 14)
    )


class TestSettleGuardsCustodyThenMoney:
    """"It requires the delivery's `settlement_status` to still be `PROVISIONAL`,
    its `custody_status` to be `DELIVERED` or `RETURNED` — anything earlier is
    `ERR_INVALID_CUSTODY_STATE`, since the physical question must be answered
    before the financial one"
    """

    def test_an_unfinished_custody_dimension_refuses_the_settlement(
        self, api, a_bag_at_the_door_before_any_money_moves
    ):
        """The door-step run closes custody and deliberately leaves the money open.

        "The delivery's `settlement_status` does **not** move — the bill is still
        `PROVISIONAL` and stays that way until settlement."

        Design: Corner/endpoints/settlement_is_refused_before_custody_closes_and_again_after_it_settles
        """
        scn = a_bag_at_the_door_before_any_money_moves
        validate_error(
            api.settle_delivery(scn.delivery["id"], headers=OPS_HEADERS),
            "ERR_INVALID_CUSTODY_STATE",
            409,
        )
        assert read_delivery(api, scn.delivery["id"])["settlement_status"] == "PROVISIONAL"

        attempt = deliver(api, scn, id_verification_method="DOB_MATCH")
        assert attempt["outcome"] == "DELIVERED"
        landed = read_delivery(api, scn.delivery["id"])
        assert landed["custody_status"] == "DELIVERED"
        assert landed["settlement_status"] == "PROVISIONAL"

    def test_the_second_settlement_is_refused_by_the_money_dimension(
        self, api, a_bag_at_the_door_before_any_money_moves
    ):
        """Settle is not idempotent: the terminal money state answers the replay.

        "A new delivery begins at `PROVISIONAL`; `FINALIZED`, `WAIVED`, and
        `VOIDED` are terminal, and an operation that needs the money dimension
        still open is rejected with `ERR_INVALID_SETTLEMENT_STATE` when it is not."

        Design: Corner/endpoints/settlement_is_refused_before_custody_closes_and_again_after_it_settles
        """
        scn = a_bag_at_the_door_before_any_money_moves
        deliver(api, scn, id_verification_method="DOB_MATCH")

        settled = validate_success(api.settle_delivery(scn.delivery["id"], headers=OPS_HEADERS))
        assert settled["settlement_status"] == "FINALIZED"
        assert settled["fee_subtotal_cents"] == Z1_STANDARD_SUBTOTAL_CENTS
        assert read_order(api, scn.order["id"])["status"] == "CLOSED"

        validate_error(
            api.settle_delivery(scn.delivery["id"], headers=OPS_HEADERS),
            "ERR_INVALID_SETTLEMENT_STATE",
            409,
        )
        assert read_delivery(api, scn.delivery["id"])["custody_status"] == "DELIVERED"

        rows = allocations_for(api, scn.delivery["id"])
        assert len(rows) == 2
        assert find_by(rows, variant="PROVISIONAL")["status"] == "SUPERSEDED"
        assert find_by(rows, variant="FINAL")["status"] == "ACTIVE"
        assert_grant_ledger(
            read_grant(api, scn.net.grant["id"]), committed_cents=0, consumed_cents=150
        )


# ─── The logical clock ────────────────────────────────


@pytest.fixture
def a_network_built_at_nine_in_the_morning(api):
    """The reference layer stamped at 2026-08-03T09:00:00Z and nothing else."""
    return build_network(api)


class TestTheClockCapabilityFixesTheInstantInForce:
    """"The clock starts at `2026-08-01T00:00:00Z` and stays there until an
    operations-only capability moves it: that capability accepts a single
    `current_utc` instant and echoes back the `current_utc` now in force."
    """

    def test_the_advance_is_echoed_and_the_next_row_is_written_against_it(
        self, api, a_network_built_at_nine_in_the_morning
    ):
        """The capability answers with the instant now in force, and writes proceed.

        "that capability accepts a single `current_utc` instant and echoes back
        the `current_utc` now in force"

        Design: Corner/endpoints/clock_write_sets_the_deterministic_now_for_every_later_timestamp
        """
        net = a_network_built_at_nine_in_the_morning
        echoed = set_clock(api, utc_ts(4, 10))
        assert_instant(echoed["current_utc"], utc_ts(4, 10))

        window = build_window(
            api,
            net.zone["id"],
            window_start=utc_ts(5, 14),
            window_end=utc_ts(5, 16),
            capacity_slots=1,
        )
        assert window["status"] == "OPEN"
        assert window["reserved_slots"] == 0
        assert window["version"] == 1

    def test_a_later_mutation_bumps_the_version_of_the_row_it_touches(
        self, api, a_network_built_at_nine_in_the_morning
    ):
        """A consent flip after two clock moves is still one mutation of one row.

        "flipping it to `REVOKED` immediately blocks release of that patient's
        orders and reservation of new deliveries with `ERR_CONSENT_NOT_GRANTED`,
        and each such change bumps the patient's `version`"

        Design: Corner/endpoints/clock_write_sets_the_deterministic_now_for_every_later_timestamp
        """
        net = a_network_built_at_nine_in_the_morning
        set_clock(api, utc_ts(4, 10))
        set_clock(api, utc_ts(4, 11, 30))

        revoked = validate_success(
            api.record_patient_consent(
                net.patient["id"],
                factories.consent_payload("REVOKED"),
                headers=net.pharmacy_headers,
            )
        )
        assert revoked["hipaa_consent_status"] == "REVOKED"
        assert revoked["version"] == 2


# ─── A body foreign key that is also a filter ─────────


@pytest.fixture
def one_payer_and_no_pools_yet(api):
    """Meridian Health, registered at 09:00Z, with no grant pool behind it."""
    set_clock(api, utc_ts(3, 9))
    return build_health_plan(api)


class TestGrantPoolsHangOffAnExistingPlan:
    """"A referenced health plan, pharmacy, or delivery zone has no dedicated code
    and reports `ERR_REFERENCE_NOT_FOUND` — this is what a bad `health_plan_id`,
    `pharmacy_id`, or `zone_code` yields, the latter being resolved by natural key
    rather than by identifier."
    """

    def test_funding_a_pool_against_an_unknown_plan_is_a_reference_failure(
        self, api, one_payer_and_no_pools_yet
    ):
        """A well-formed identifier that names nothing is a 404, not a 400.

        "Every foreign key supplied in the request body resolves to a stored row —
        otherwise `ERR_ORDER_NOT_FOUND`, `ERR_WINDOW_NOT_FOUND`,
        `ERR_COURIER_NOT_FOUND`, `ERR_PLAN_GRANT_NOT_FOUND`,
        `ERR_PATIENT_NOT_FOUND`, or `ERR_REFERENCE_NOT_FOUND` for a referenced
        health plan, pharmacy, or delivery zone that has no dedicated code of its
        own."

        Design: Corner/endpoints/plan_grant_links_to_an_existing_health_plan_and_is_listable_by_it
        """
        assert one_payer_and_no_pools_yet["id"] != UNKNOWN_PLAN_ID
        validate_error(
            api.create_plan_grant(
                factories.plan_grant_payload(UNKNOWN_PLAN_ID),
                headers=OPS_HEADERS,
            ),
            "ERR_REFERENCE_NOT_FOUND",
            404,
        )

    def test_one_plan_carries_one_pool_per_benefit_year(
        self, api, one_payer_and_no_pools_yet
    ):
        """The foreign key is the list filter too, and the year separates the pools.

        "A freshly funded pool starts with `committed_cents` and `consumed_cents`
        at 0, `remaining_cents` equal to `grant_budget_cents`, and `status`
        `ACTIVE`."

        Design: Corner/endpoints/plan_grant_links_to_an_existing_health_plan_and_is_listable_by_it
        """
        plan = one_payer_and_no_pools_yet
        this_year = build_plan_grant(api, plan["id"])
        next_year = build_plan_grant(
            api, plan["id"], benefit_year=2027, grant_budget_cents=5000, per_delivery_cap_cents=75
        )
        assert this_year["benefit_year"] == 2026
        assert next_year["benefit_year"] == 2027
        for pool in (this_year, next_year):
            assert_grant_ledger(
                pool,
                committed_cents=0,
                consumed_cents=0,
                remaining_cents=pool["grant_budget_cents"],
                status="ACTIVE",
            )

        rows, meta = validate_paginated(
            api.list_plan_grants(OPS_HEADERS, health_plan_id=plan["id"], benefit_year=2026)
        )
        assert meta["total_count"] == 1
        assert meta["has_more"] is False
        assert [row["id"] for row in rows] == [this_year["id"]]

        _all_rows, all_meta = validate_paginated(
            api.list_plan_grants(OPS_HEADERS, health_plan_id=plan["id"])
        )
        assert all_meta["total_count"] == 2
