"""One rule at a time, on the exact input that separates it from its neighbour.

Each group here pins a single rung of the evaluation ladder: the two zone codes
that share one rung, the two zone capability flags that must not be conflated,
the dispensing site's credentials, the cold seal, the three proof-of-delivery
refusals in their fixed order, the cooldown boundary, the live exception case,
the capacity pool a bag may not be moved into, and the aggregate slot count. Each
refusal is paired with the neighbouring call that succeeds, so the rule is shown
to be scoped rather than merely present.
"""

import pytest

from test_helpers import (
    OPS_HEADERS,
    OPS_USER_A,
    Z1_STANDARD_LINES,
    Z1_STANDARD_SUBTOTAL_CENTS,
    ZONE_Z2,
    active_allocation,
    adjudicate,
    advance_to_assigned,
    allocations_for,
    assert_courier_counters,
    assert_delivery_state,
    assert_fee_lines,
    assert_grant_ledger,
    assert_instant,
    assert_payer_mix,
    assert_reliability_scores,
    assert_window_occupancy,
    attempts_for,
    build_network,
    build_order,
    build_out_for_delivery,
    build_queued_delivery,
    build_ready_order,
    build_window,
    build_zone,
    exhaust_attempt_ladder,
    factories,
    find_by,
    latest_case,
    read_courier,
    read_delivery,
    read_grant,
    read_order,
    read_window,
    record_attempt,
    reserve_delivery,
    set_clock,
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
COLD_ORDER = {**STANDARD_ORDER, "cold_chain_required": True}
CONTROLLED_ORDER = {**STANDARD_ORDER, "controlled_schedule": "CIII"}
LONG_WINDOW = {"window_end": utc_ts(3, 22), "capacity_slots": 1}

# The Z1 standard bag priced for three door-step runs: two surcharge units.
THREE_RUN_LINES = [705, 861, 0, 0, 0, 800]


def _reserve(api, net, order, window, version=None):
    """A raw reservation call, so a refusal can be inspected rather than raised."""
    if version is None:
        version = read_window(api, window["id"])["version"]
    return api.create_delivery(
        factories.delivery_payload(order["id"], window["id"], version),
        headers=net.pharmacy_headers,
    )


# ─── Zone identity ────────────────────────────────────


@pytest.fixture
def one_order_and_a_window_in_each_zone(api):
    """A Z1 recipient, a Z1 window with room for two, and a foreign Z2 window."""
    net = build_network(api)
    order = build_ready_order(api, net, **STANDARD_ORDER)
    home = build_window(api, net.zone["id"], capacity_slots=2)
    foreign_zone = build_zone(api, **ZONE_Z2)
    away = build_window(api, foreign_zone["id"], capacity_slots=1)
    return net, order, home, away


class TestWindowZoneMustBeTheRecipientsZone:
    """"the window's `zone_id` must be the zone named by the recipient's
    `zone_code`, or the request is `ERR_ZONE_MISMATCH`, while a `zone_code`
    matching no zone row at all is `ERR_ZONE_NOT_SERVICED`"
    """

    def test_a_window_in_another_territory_is_refused_as_a_zone_mismatch(
        self, api, one_order_and_a_window_in_each_zone
    ):
        """The recipient's own zone is the only territory the bag may be promised to.

        "the window's `zone_id` must be the zone named by the recipient's
        `zone_code`, or the request is `ERR_ZONE_MISMATCH`, while a `zone_code`
        matching no zone row at all is `ERR_ZONE_NOT_SERVICED`"

        Design: Corner/validations/unserviced_patient_zone_and_window_zone_mismatch_are_separate_errors
        """
        net, order, _home, away = one_order_and_a_window_in_each_zone
        validate_error(_reserve(api, net, order, away), "ERR_ZONE_MISMATCH", 409)

        _rows, meta = validate_paginated(api.list_deliveries(OPS_HEADERS, order_id=order["id"]))
        assert meta["total_count"] == 0
        assert_window_occupancy(read_window(api, away["id"]), reserved_slots=0, status="OPEN")
        assert read_window(api, away["id"])["version"] == 1
        assert read_order(api, order["id"])["status"] == "READY"

    def test_the_same_order_reserves_cleanly_in_its_own_zone(
        self, api, one_order_and_a_window_in_each_zone
    ):
        """A refusal on the wrong zone leaves the order free to take the right one.

        "The window's `reserved_slots` rises by one and it flips to `FULL` if that
        reaches `capacity_slots`; the order moves to `DISPATCHED`; and the bill is
        built."

        Design: Corner/validations/unserviced_patient_zone_and_window_zone_mismatch_are_separate_errors
        """
        net, order, home, away = one_order_and_a_window_in_each_zone
        validate_error(_reserve(api, net, order, away), "ERR_ZONE_MISMATCH", 409)

        delivery = validate_success(_reserve(api, net, order, home), 201)
        assert_delivery_state(delivery, custody_status="QUEUED", settlement_status="PROVISIONAL")

        after = read_window(api, home["id"])
        assert_window_occupancy(after, reserved_slots=1, available_slots=1, status="OPEN")
        assert after["version"] == 2
        assert read_window(api, away["id"])["reserved_slots"] == 0


# ─── Zone capability flags ────────────────────────────


@pytest.fixture
def a_zone_that_refuses_controlled_traffic(api):
    """Cold-capable Z1 with `controlled_delivery_allowed` switched off.

    One CIII bag and one plain bag are both READY against the same window, so the
    only difference between the two reservations is the derived handling class.
    """
    net = build_network(api, zone={"controlled_delivery_allowed": False})
    controlled = build_ready_order(api, net, **CONTROLLED_ORDER)
    standard = build_ready_order(api, net, **STANDARD_ORDER)
    window = build_window(api, net.zone["id"], capacity_slots=2)
    return net, controlled, standard, window


class TestControlledBagsObeyZonePolicy:
    """"Zone policy then applies to the bag: a controlled bag into a zone whose
    `controlled_delivery_allowed` is false is `ERR_CONTROLLED_ZONE_PROHIBITED`,
    and a cold bag into a zone whose `cold_chain_supported` is false is
    `ERR_COLD_CHAIN_UNSUPPORTED_ZONE`."
    """

    def test_a_scheduled_drug_cannot_be_routed_into_a_zone_that_forbids_it(
        self, api, a_zone_that_refuses_controlled_traffic
    ):
        """The municipality's ban is enforced against the bag, not the request.

        "Zone policy then applies to the bag: a controlled bag into a zone whose
        `controlled_delivery_allowed` is false is `ERR_CONTROLLED_ZONE_PROHIBITED`,
        and a cold bag into a zone whose `cold_chain_supported` is false is
        `ERR_COLD_CHAIN_UNSUPPORTED_ZONE`."

        Design: Corner/validations/controlled_bag_into_a_zone_that_forbids_controlled_delivery_is_rejected
        """
        net, controlled, _standard, window = a_zone_that_refuses_controlled_traffic
        validate_error(
            _reserve(api, net, controlled, window), "ERR_CONTROLLED_ZONE_PROHIBITED", 409
        )

        order = read_order(api, controlled["id"])
        assert order["status"] == "READY"
        assert order["signature_required"] is True
        assert order["required_id_verification"] == "PHOTO_ID"

    def test_a_plain_bag_takes_the_same_window_in_the_same_zone(
        self, api, a_zone_that_refuses_controlled_traffic
    ):
        """The identical call succeeds once the handling class carries no schedule.

        "The `handling_class` is `COLD_CHAIN_CONTROLLED` when the bag is both cold
        and controlled, `COLD_CHAIN` when it is only cold, `CONTROLLED` when it is
        only controlled, and `STANDARD` otherwise."

        Design: Corner/validations/controlled_bag_into_a_zone_that_forbids_controlled_delivery_is_rejected
        """
        net, controlled, standard, window = a_zone_that_refuses_controlled_traffic
        validate_error(
            _reserve(api, net, controlled, window), "ERR_CONTROLLED_ZONE_PROHIBITED", 409
        )

        delivery = validate_success(_reserve(api, net, standard, window), 201)
        assert delivery["handling_class"] == "STANDARD"
        assert read_window(api, window["id"])["reserved_slots"] == 1
        assert net.zone["cold_chain_supported"] is True


@pytest.fixture
def a_zone_without_refrigerated_capability(api):
    """Z1 with `cold_chain_supported` off but controlled traffic still permitted."""
    net = build_network(api, zone={"cold_chain_supported": False})
    cold = build_ready_order(api, net, **COLD_ORDER)
    controlled = build_ready_order(api, net, **CONTROLLED_ORDER)
    window = build_window(api, net.zone["id"], capacity_slots=2)
    return net, cold, controlled, window


class TestColdBagsObeyTheOtherZoneFlag:
    """"Two booleans, `cold_chain_supported` and `controlled_delivery_allowed`,
    both defaulting to true, say whether refrigerated product and scheduled drugs
    may be routed into the zone at all — some municipalities forbid courier
    delivery of controlled substances outright."
    """

    def test_refrigerated_product_is_refused_by_a_zone_with_no_cold_support(
        self, api, a_zone_without_refrigerated_capability
    ):
        """Nothing is priced and no slot moves when the zone cannot take the bag.

        "a cold bag into a zone whose `cold_chain_supported` is false is
        `ERR_COLD_CHAIN_UNSUPPORTED_ZONE`"

        Design: Corner/validations/cold_bag_into_a_zone_without_cold_support_is_rejected
        """
        net, cold, _controlled, window = a_zone_without_refrigerated_capability
        validate_error(_reserve(api, net, cold, window), "ERR_COLD_CHAIN_UNSUPPORTED_ZONE", 409)

        assert read_order(api, cold["id"])["status"] == "READY"
        _rows, meta = validate_paginated(api.list_deliveries(OPS_HEADERS, order_id=cold["id"]))
        assert meta["total_count"] == 0

        after = read_window(api, window["id"])
        assert_window_occupancy(after, reserved_slots=0, status="OPEN")
        assert after["version"] == 1
        assert_grant_ledger(read_grant(api, net.grant["id"]), committed_cents=0)

    def test_the_zones_controlled_permission_is_a_separate_flag(
        self, api, a_zone_without_refrigerated_capability
    ):
        """A scheduled drug still routes into the very zone that refused the cold bag.

        "a controlled bag into a zone whose `controlled_delivery_allowed` is false
        is `ERR_CONTROLLED_ZONE_PROHIBITED`"

        Design: Corner/validations/cold_bag_into_a_zone_without_cold_support_is_rejected
        """
        net, cold, controlled, window = a_zone_without_refrigerated_capability
        validate_error(_reserve(api, net, cold, window), "ERR_COLD_CHAIN_UNSUPPORTED_ZONE", 409)

        delivery = validate_success(_reserve(api, net, controlled, window), 201)
        assert delivery["handling_class"] == "CONTROLLED"
        assert read_window(api, window["id"])["reserved_slots"] == 1


# ─── Dispensing-site credentials ──────────────────────


@pytest.fixture
def three_bags_at_a_partly_credentialled_site(api):
    """Cedar Rx holds only a CIII_V licence and is not cold-chain certified.

    A CII bag, a cold bag and a CIII bag all sit at `INTAKE`, so one release call
    exercises the licence ladder, the cold flag, and the passing case in turn.
    """
    net = build_network(
        api,
        pharmacy={"cold_chain_certified": False, "controlled_license_tier": "CIII_V"},
    )
    schedule_two = build_order(api, net, **{**STANDARD_ORDER, "controlled_schedule": "CII"})
    cold = build_order(api, net, **COLD_ORDER)
    schedule_three = build_order(api, net, **CONTROLLED_ORDER)
    return net, schedule_two, cold, schedule_three


class TestReleaseNeedsTheSitesCredentials:
    """"It requires the order to be at `INTAKE`, the acting operator to own the
    order's `pharmacy_id`, the recipient's `hipaa_consent_status` to be `GRANTED`,
    and the site's credentials to cover the bag: `controlled_license_tier` `NONE`
    covers only a `NONE` schedule, `CIII_V` covers `NONE` and `CIII`, and `CII_V`
    covers `NONE`, `CIII`, and `CII`, while a cold bag additionally requires
    `cold_chain_certified` to be true."
    """

    def test_a_schedule_two_bag_and_a_cold_bag_share_one_credential_error(
        self, api, three_bags_at_a_partly_credentialled_site
    ):
        """Two different shortfalls, one identifier, and neither order moves.

        "A credential shortfall is `ERR_CONTROLLED_NOT_LICENSED`"

        Design: Corner/validations/pharmacy_cannot_mark_ready_beyond_its_licence_or_cold_certification
        """
        net, schedule_two, cold, _schedule_three = three_bags_at_a_partly_credentialled_site
        validate_error(
            api.mark_order_ready(schedule_two["id"], headers=net.pharmacy_headers),
            "ERR_CONTROLLED_NOT_LICENSED",
            409,
        )
        validate_error(
            api.mark_order_ready(cold["id"], headers=net.pharmacy_headers),
            "ERR_CONTROLLED_NOT_LICENSED",
            409,
        )

        for order_id in (schedule_two["id"], cold["id"]):
            blocked = read_order(api, order_id)
            assert blocked["status"] == "INTAKE"
            assert blocked["hold_count"] == 0

    def test_a_schedule_three_bag_inside_the_licence_is_released(
        self, api, three_bags_at_a_partly_credentialled_site
    ):
        """The covered schedule passes and its two proof fields are recomputed.

        "On success the two derived proof fields are recomputed and the order's
        `version` increments."

        Design: Corner/validations/pharmacy_cannot_mark_ready_beyond_its_licence_or_cold_certification
        """
        net, schedule_two, cold, schedule_three = three_bags_at_a_partly_credentialled_site
        validate_error(
            api.mark_order_ready(schedule_two["id"], headers=net.pharmacy_headers),
            "ERR_CONTROLLED_NOT_LICENSED",
            409,
        )
        validate_error(
            api.mark_order_ready(cold["id"], headers=net.pharmacy_headers),
            "ERR_CONTROLLED_NOT_LICENSED",
            409,
        )

        released = validate_success(
            api.mark_order_ready(schedule_three["id"], headers=net.pharmacy_headers)
        )
        assert released["status"] == "READY"
        assert released["signature_required"] is True
        assert released["required_id_verification"] == "PHOTO_ID"

        _rows, meta = validate_paginated(
            api.list_pharmacy_orders(
                OPS_HEADERS, pharmacy_id=net.pharmacy["id"], status="READY"
            )
        )
        assert meta["total_count"] == 1


# ─── The cold seal at the counter ─────────────────────


@pytest.fixture
def a_cold_bag_waiting_at_the_counter(api):
    """A refrigerated bag accepted by a cold-equipped courier, not yet picked up."""
    scn = build_queued_delivery(api, order_kwargs=COLD_ORDER, window_kwargs=LONG_WINDOW)
    advance_to_assigned(api, scn)
    return scn


class TestColdHandoffNeedsASeal:
    """"When the `handling_class` is `COLD_CHAIN` or `COLD_CHAIN_CONTROLLED`, the
    request must carry a `cold_chain_seal_id`; its absence is
    `ERR_COLD_SEAL_REQUIRED`. For `STANDARD` and `CONTROLLED` bags the field is
    simply ignored."
    """

    def test_a_sealless_pickup_is_refused_and_a_sealed_one_takes_custody(
        self, api, a_cold_bag_waiting_at_the_counter
    ):
        """Custody stays at the counter until the seal number is supplied.

        "On success the delivery advances `ASSIGNED → PICKED_UP`, stores the
        supplied `cold_chain_seal_id`, and stamps `picked_up_at` from the clock —
        the instant from which the cold-chain excursion budget runs."

        Design: Corner/validations/cold_pickup_without_a_seal_id_is_rejected_then_accepted_with_one
        """
        scn = a_cold_bag_waiting_at_the_counter
        sealless = api.pickup_delivery(
            scn.delivery["id"],
            headers=scn.courier_headers,
            payload=factories.pickup_payload(None),
        )
        validate_error(sealless, "ERR_COLD_SEAL_REQUIRED", 409)
        assert read_delivery(api, scn.delivery["id"])["custody_status"] == "ASSIGNED"

        sealed = validate_success(
            api.pickup_delivery(
                scn.delivery["id"],
                headers=scn.courier_headers,
                payload=factories.pickup_payload("SEAL-4471"),
            )
        )
        assert sealed["custody_status"] == "PICKED_UP"
        assert sealed["cold_chain_seal_id"] == "SEAL-4471"
        assert_instant(sealed["picked_up_at"], utc_ts(3, 13, 45))

    def test_the_reservation_asked_for_no_seal_and_priced_one_re_ice(
        self, api, a_cold_bag_waiting_at_the_counter
    ):
        """The seal is a pickup rule only; the bill already knew the bag was cold.

        "`cold_pack_line_cents` is the zone's `cold_pack_fee_cents` multiplied by
        the billable attempts when the `handling_class` is `COLD_CHAIN` or
        `COLD_CHAIN_CONTROLLED`, and 0 otherwise — each door-step run needs a
        fresh gel-pack re-ice."

        Design: Corner/validations/cold_pickup_without_a_seal_id_is_rejected_then_accepted_with_one
        """
        scn = a_cold_bag_waiting_at_the_counter
        assert scn.delivery["handling_class"] == "COLD_CHAIN"

        validate_error(
            api.pickup_delivery(
                scn.delivery["id"],
                headers=scn.courier_headers,
                payload=factories.pickup_payload(None),
            ),
            "ERR_COLD_SEAL_REQUIRED",
            409,
        )
        sealed = validate_success(
            api.pickup_delivery(
                scn.delivery["id"],
                headers=scn.courier_headers,
                payload=factories.pickup_payload("SEAL-4471"),
            )
        )
        assert sealed["version"] == 3

        allocation = active_allocation(api, scn.delivery["id"])
        assert_fee_lines(allocation, [705, 861, 455, 0, 0, 0])
        assert allocation["fee_subtotal_cents"] == 2021


# ─── Proof at the door ────────────────────────────────


@pytest.fixture
def a_high_value_bag_at_the_door(api):
    """A 30000-cent bag out for delivery: signature required, photo ID demanded."""
    scn = build_out_for_delivery(
        api,
        order_kwargs={**STANDARD_ORDER, "total_rx_value_cents": 30000},
        window_kwargs=LONG_WINDOW,
        depart_clock=utc_ts(3, 14),
    )
    return scn


def _door_step(api, scn, **fields):
    return api.record_attempt(
        scn.delivery["id"],
        factories.attempt_payload("DELIVERED", **fields),
        headers=scn.courier_headers,
    )


class TestProofGatesFireInOrder:
    """"If the delivery's `signature_required` is true, `signature_captured` must
    be true — a missing signature is `ERR_SIGNATURE_REQUIRED` — and
    `recipient_relationship` must not be `UNATTENDED`, since a claimed signature
    on an unattended drop is `ERR_UNATTENDED_NOT_PERMITTED`."
    """

    def test_the_signature_gate_speaks_before_the_identity_ladder(
        self, api, a_high_value_bag_at_the_door
    ):
        """Three refusals in the order the rules are declared.

        "Then the submitted `id_verification_method` must rank at or above the
        delivery's `required_id_verification` on the strictly increasing ladder
        `NONE`, `DOB_MATCH`, `PHOTO_ID`, `GOVT_ID_SCAN`; ranking below it is
        `ERR_ID_VERIFICATION_INSUFFICIENT`."

        Design: Corner/validations/proof_of_delivery_rules_fire_in_priority_order_before_the_bag_closes
        """
        scn = a_high_value_bag_at_the_door
        assert scn.delivery["signature_required"] is True
        assert scn.delivery["required_id_verification"] == "PHOTO_ID"

        validate_error(
            _door_step(
                api,
                scn,
                id_verification_method="DOB_MATCH",
                signature_captured=False,
                recipient_relationship="SELF",
            ),
            "ERR_SIGNATURE_REQUIRED",
            409,
        )
        validate_error(
            _door_step(
                api,
                scn,
                id_verification_method="PHOTO_ID",
                signature_captured=True,
                recipient_relationship="UNATTENDED",
            ),
            "ERR_UNATTENDED_NOT_PERMITTED",
            409,
        )
        validate_error(
            _door_step(
                api,
                scn,
                id_verification_method="DOB_MATCH",
                signature_captured=True,
                recipient_relationship="SELF",
            ),
            "ERR_ID_VERIFICATION_INSUFFICIENT",
            409,
        )
        assert attempts_for(api, scn.delivery["id"]) == []

    def test_a_rung_above_the_requirement_closes_the_bag(
        self, api, a_high_value_bag_at_the_door
    ):
        """Only the accepted run is recorded, so the refusals cost the courier nothing.

        "an `attempt_no` equal to the delivery's `attempt_count` after this run is
        counted (so the first run is 1)"

        Design: Corner/validations/proof_of_delivery_rules_fire_in_priority_order_before_the_bag_closes
        """
        scn = a_high_value_bag_at_the_door
        validate_error(
            _door_step(
                api,
                scn,
                id_verification_method="DOB_MATCH",
                signature_captured=False,
                recipient_relationship="SELF",
            ),
            "ERR_SIGNATURE_REQUIRED",
            409,
        )

        accepted = validate_success(
            _door_step(
                api,
                scn,
                id_verification_method="GOVT_ID_SCAN",
                signature_captured=True,
                recipient_relationship="SELF",
            ),
            201,
        )
        assert accepted["outcome"] == "DELIVERED"
        assert accepted["attempt_no"] == 1
        assert read_delivery(api, scn.delivery["id"])["attempt_count"] == 1

        courier = read_courier(api, scn.courier["id"])
        assert_courier_counters(courier, attempt_total_count=1, delivered_count=1)
        assert_reliability_scores(courier, rolling=100.00)


# ─── The cooldown boundary ────────────────────────────


@pytest.fixture
def a_bag_one_run_into_the_ladder(api):
    """One NO_ANSWER recorded at 14:00Z, so the stage-one cooldown is running."""
    scn = build_out_for_delivery(
        api, order_kwargs=STANDARD_ORDER, window_kwargs=LONG_WINDOW, depart_clock=utc_ts(3, 14)
    )
    record_attempt(api, scn, "NO_ANSWER")
    return scn


class TestCooldownAdmitsTheBoundaryInstant:
    """"The courier then re-departs, advancing `ATTEMPT_FAILED →
    OUT_FOR_DELIVERY`, but only after a cooldown that lengthens with each rung:
    one hour must pass after the first failure and three hours after the second,
    measured from `last_attempt_at` on the delivery. Arriving before that is
    `ERR_REATTEMPT_COOLDOWN_ACTIVE`; arriving at exactly the boundary instant is
    allowed."
    """

    def test_one_minute_early_is_refused_and_the_exact_hour_is_admitted(
        self, api, a_bag_one_run_into_the_ladder
    ):
        """Fifty-nine minutes is not an hour; sixty minutes exactly is.

        "Arriving before that is `ERR_REATTEMPT_COOLDOWN_ACTIVE`; arriving at
        exactly the boundary instant is allowed."

        Design: Corner/validations/reattempt_cooldown_rejects_one_minute_early_and_admits_the_exact_boundary
        """
        scn = a_bag_one_run_into_the_ladder
        assert scn.delivery["custody_status"] == "ATTEMPT_FAILED"
        assert scn.delivery["attempt_count"] == 1

        set_clock(api, utc_ts(3, 14, 59))
        validate_error(
            api.depart_delivery(scn.delivery["id"], headers=scn.courier_headers),
            "ERR_REATTEMPT_COOLDOWN_ACTIVE",
            409,
        )
        assert read_delivery(api, scn.delivery["id"])["custody_status"] == "ATTEMPT_FAILED"

        set_clock(api, utc_ts(3, 15))
        departed = validate_success(
            api.depart_delivery(scn.delivery["id"], headers=scn.courier_headers)
        )
        assert departed["custody_status"] == "OUT_FOR_DELIVERY"

    def test_the_second_rung_waits_three_hours_rather_than_one(
        self, api, a_bag_one_run_into_the_ladder
    ):
        """The wait is keyed to the rung the bag stands on, not to a fixed hour.

        "A run that lands at `ATTEMPT_FAILED` raises `attempt_count`, stamps
        `last_attempt_at` from the clock, recomputes both courier reliability
        scores and may cascade a suspension (§3.7), and deliberately **keeps the
        window slot reserved**, because the bag is still out against that window."

        Design: Corner/validations/reattempt_cooldown_rejects_one_minute_early_and_admits_the_exact_boundary
        """
        scn = a_bag_one_run_into_the_ladder
        set_clock(api, utc_ts(3, 15))
        validate_success(api.depart_delivery(scn.delivery["id"], headers=scn.courier_headers))
        record_attempt(api, scn, "NO_ANSWER")

        second = read_delivery(api, scn.delivery["id"])
        assert second["attempt_count"] == 2
        assert_instant(second["last_attempt_at"], utc_ts(3, 15))

        set_clock(api, utc_ts(3, 17, 59))
        validate_error(
            api.depart_delivery(scn.delivery["id"], headers=scn.courier_headers),
            "ERR_REATTEMPT_COOLDOWN_ACTIVE",
            409,
        )
        assert read_delivery(api, scn.delivery["id"])["custody_status"] == "ATTEMPT_FAILED"
        assert read_window(api, scn.window["id"])["reserved_slots"] == 1


# ─── A live exception blocks the money ────────────────


@pytest.fixture
def a_returned_bag_with_a_live_case(api):
    """The ladder is exhausted, the bag is back at Cedar Rx, and a case is OPEN."""
    scn = build_out_for_delivery(
        api, order_kwargs=STANDARD_ORDER, window_kwargs=LONG_WINDOW, depart_clock=utc_ts(3, 14)
    )
    exhaust_attempt_ladder(api, scn)
    scn.delivery = validate_success(
        api.confirm_return(scn.delivery["id"], headers=scn.pharmacy_headers)
    )
    scn.case = latest_case(api, scn.delivery["id"])
    return scn


class TestSettlementWaitsForAdjudication:
    """"and no exception case on that delivery to be `OPEN` or `UNDER_REVIEW`,
    since money may not be finalised while an exception is live; a pending case is
    `ERR_EXCEPTION_PENDING`."
    """

    def test_both_live_case_states_refuse_the_settlement(
        self, api, a_returned_bag_with_a_live_case
    ):
        """`OPEN` blocks, and taking the case up does not unblock it.

        "and no exception case on that delivery to be `OPEN` or `UNDER_REVIEW`,
        since money may not be finalised while an exception is live; a pending case
        is `ERR_EXCEPTION_PENDING`."

        Design: Corner/validations/settlement_is_blocked_while_an_exception_is_open_or_under_review
        """
        scn = a_returned_bag_with_a_live_case
        assert scn.case["status"] == "OPEN"
        assert scn.case["exception_type"] == "ATTEMPTS_EXHAUSTED"

        validate_error(
            api.settle_delivery(scn.delivery["id"], headers=OPS_HEADERS),
            "ERR_EXCEPTION_PENDING",
            409,
        )
        assert_delivery_state(
            read_delivery(api, scn.delivery["id"]),
            custody_status="RETURNED",
            settlement_status="PROVISIONAL",
        )

        reviewing = start_review(api, scn.case["id"])
        assert reviewing["status"] == "UNDER_REVIEW"
        validate_error(
            api.settle_delivery(scn.delivery["id"], headers=OPS_HEADERS),
            "ERR_EXCEPTION_PENDING",
            409,
        )
        assert read_delivery(api, scn.delivery["id"])["settlement_status"] == "PROVISIONAL"

    def test_a_denial_unblocks_the_bill_it_deliberately_leaves_standing(
        self, api, a_returned_bag_with_a_live_case
    ):
        """The null branch closes the case and lets ordinary settlement proceed.

        "Above all, the delivery's `settlement_status` is deliberately left at
        `PROVISIONAL` rather than being driven to `WAIVED`, precisely so that
        ordinary settlement can proceed afterwards and bill the work that was in
        fact performed."

        Design: Corner/validations/settlement_is_blocked_while_an_exception_is_open_or_under_review
        """
        scn = a_returned_bag_with_a_live_case
        validate_error(
            api.settle_delivery(scn.delivery["id"], headers=OPS_HEADERS),
            "ERR_EXCEPTION_PENDING",
            409,
        )
        start_review(api, scn.case["id"])

        version = read_delivery(api, scn.delivery["id"])["version"]
        denied = adjudicate(api, scn.case["id"], "DENY", version)
        assert denied["status"] == "DENIED"
        assert denied["credit_cents"] == 0
        assert denied["adjudicated_by_ops_user_id"] == OPS_USER_A
        assert read_delivery(api, scn.delivery["id"])["settlement_status"] == "PROVISIONAL"

        settled = validate_success(api.settle_delivery(scn.delivery["id"], headers=OPS_HEADERS))
        assert settled["settlement_status"] == "FINALIZED"
        assert settled["fee_subtotal_cents"] == 2366

        rows = allocations_for(api, scn.delivery["id"])
        assert len(rows) == 2
        assert find_by(rows, variant="PROVISIONAL")["status"] == "SUPERSEDED"
        assert_fee_lines(find_by(rows, variant="FINAL"), THREE_RUN_LINES)
        assert_grant_ledger(
            read_grant(api, scn.net.grant["id"]), committed_cents=0, consumed_cents=150
        )


# ─── Capacity pools are not interchangeable ───────────


@pytest.fixture
def one_interval_published_under_both_modes(api):
    """A queued bag on the scheduled 14:00Z window, with two 16:00Z successors.

    The same 16:00-18:00Z interval exists twice in the zone because overlap is
    scoped per zone and mode, so the mode is the only thing separating the legal
    move from the illegal one.
    """
    scn = build_queued_delivery(api, order_kwargs=STANDARD_ORDER)
    on_demand = build_window(
        api,
        scn.net.zone["id"],
        courier_mode="ON_DEMAND",
        window_start=utc_ts(3, 16),
        window_end=utc_ts(3, 18),
        capacity_slots=1,
    )
    scheduled = build_window(
        api,
        scn.net.zone["id"],
        courier_mode="SCHEDULED",
        window_start=utc_ts(3, 16),
        window_end=utc_ts(3, 18),
        capacity_slots=1,
    )
    return scn, on_demand, scheduled


class TestRescheduleStaysInsideOneCapacityPool:
    """"The replacement window must sit in the same zone (`ERR_ZONE_MISMATCH`) and
    must carry the same `courier_mode` as the window the delivery currently holds,
    since on-demand and scheduled capacity pools are not interchangeable and a bag
    priced and staffed against one pool cannot be dropped into the other; a
    mismatch is `ERR_WINDOW_MODE_MISMATCH`."
    """

    def test_the_on_demand_twin_of_the_interval_is_refused(
        self, api, one_interval_published_under_both_modes
    ):
        """Both twins were publishable, and exactly one of them is reachable.

        "and the same interval published under the other `courier_mode` is a
        different capacity pool and is likewise allowed"

        Design: Corner/validations/reschedule_across_courier_modes_returns_window_mode_mismatch
        """
        scn, on_demand, scheduled = one_interval_published_under_both_modes
        assert on_demand["courier_mode"] == "ON_DEMAND"
        assert scheduled["courier_mode"] == "SCHEDULED"
        assert on_demand["window_start"] == scheduled["window_start"]
        assert on_demand["status"] == "OPEN"
        assert scheduled["status"] == "OPEN"

        validate_error(
            api.reschedule_delivery(
                scn.delivery["id"],
                factories.reschedule_payload(on_demand["id"]),
                headers=scn.pharmacy_headers,
            ),
            "ERR_WINDOW_MODE_MISMATCH",
            409,
        )
        assert read_delivery(api, scn.delivery["id"])["window_id"] == scn.window["id"]
        assert read_window(api, on_demand["id"])["reserved_slots"] == 0

    def test_the_scheduled_twin_takes_the_bag_and_the_slot_moves_with_it(
        self, api, one_interval_published_under_both_modes
    ):
        """One slot in the zone, and it follows the delivery rather than duplicating.

        "On success the old window's `reserved_slots` drops by one with `FULL →
        OPEN` where applicable, the new window's rises with `OPEN → FULL` where
        applicable, and both windows bump their `version`."

        Design: Corner/validations/reschedule_across_courier_modes_returns_window_mode_mismatch
        """
        scn, on_demand, scheduled = one_interval_published_under_both_modes
        validate_error(
            api.reschedule_delivery(
                scn.delivery["id"],
                factories.reschedule_payload(on_demand["id"]),
                headers=scn.pharmacy_headers,
            ),
            "ERR_WINDOW_MODE_MISMATCH",
            409,
        )

        moved = validate_success(
            api.reschedule_delivery(
                scn.delivery["id"],
                factories.reschedule_payload(scheduled["id"]),
                headers=scn.pharmacy_headers,
            )
        )
        assert moved["window_id"] == scheduled["id"]

        assert_window_occupancy(
            read_window(api, scn.window["id"]), reserved_slots=0, status="OPEN"
        )
        assert_window_occupancy(
            read_window(api, scheduled["id"]), reserved_slots=1, available_slots=0, status="FULL"
        )
        assert read_window(api, on_demand["id"])["reserved_slots"] == 0

        rows, _meta = validate_paginated(
            api.list_delivery_windows(OPS_HEADERS, zone_id=scn.net.zone["id"], limit=100)
        )
        assert sum(row["reserved_slots"] for row in rows) == 1


# ─── Order state before capacity ──────────────────────


@pytest.fixture
def a_full_window_and_an_unreleased_order(api):
    """A single-slot window already taken, and a second order still at `INTAKE`."""
    scn = build_queued_delivery(api, order_kwargs=STANDARD_ORDER)
    second = build_order(api, scn.net, **STANDARD_ORDER)
    return scn, second


class TestOrderStateSpeaksBeforeCapacity:
    """"This ordering is a contract, not an implementation detail — several rungs
    are deliberately placed so that a stronger fact masks a weaker one."
    """

    def test_an_unreleased_order_hears_about_its_own_state_not_the_full_window(
        self, api, a_full_window_and_an_unreleased_order
    ):
        """Two violations stand at once and the earlier rule answers.

        "The order must be `READY`, or the request is `ERR_ORDER_NOT_READY`"

        Design: Corner/validations/order_state_check_preempts_the_capacity_check
        """
        scn, second = a_full_window_and_an_unreleased_order
        assert read_order(api, second["id"])["status"] == "INTAKE"
        live_version = read_window(api, scn.window["id"])["version"]
        assert_window_occupancy(
            read_window(api, scn.window["id"]), available_slots=0, status="FULL"
        )

        validate_error(
            _reserve(api, scn.net, second, scn.window, live_version),
            "ERR_ORDER_NOT_READY",
            409,
        )
        assert read_window(api, scn.window["id"])["version"] == live_version

    def test_releasing_the_order_surfaces_the_capacity_rule_on_the_same_call(
        self, api, a_full_window_and_an_unreleased_order
    ):
        """Proof the losing rule is live: clear the state objection and it speaks.

        "the window must not be `CLOSED` or `FULL` by status flag, or the request
        is `ERR_WINDOW_CLOSED`"

        Design: Corner/validations/order_state_check_preempts_the_capacity_check
        """
        scn, second = a_full_window_and_an_unreleased_order
        live_version = read_window(api, scn.window["id"])["version"]
        validate_error(
            _reserve(api, scn.net, second, scn.window, live_version),
            "ERR_ORDER_NOT_READY",
            409,
        )

        validate_success(api.mark_order_ready(second["id"], headers=scn.pharmacy_headers))
        validate_error(
            _reserve(api, scn.net, second, scn.window, live_version),
            "ERR_WINDOW_CLOSED",
            409,
        )

        _rows, meta = validate_paginated(api.list_deliveries(OPS_HEADERS, order_id=second["id"]))
        assert meta["total_count"] == 0
        after = read_window(api, scn.window["id"])
        assert after["reserved_slots"] == 1
        assert after["version"] == live_version


# ─── The positive control ─────────────────────────────


@pytest.fixture
def a_reservation_with_nothing_wrong_with_it(api):
    """09:00Z, a READY standard bag, and an OPEN 14:00-16:00Z scheduled window."""
    net = build_network(api)
    order = build_ready_order(api, net, **STANDARD_ORDER)
    window = build_window(api, net.zone["id"], capacity_slots=1)
    return net, order, window


class TestEveryLadderRungHoldsAtOnce:
    """"Timing applies next: the clock must be earlier than `window_end`, and for
    a `SCHEDULED` window the reservation must arrive no later than two hours
    before `window_start`; either failure is `ERR_WINDOW_ELAPSED`."
    """

    def test_the_clean_reservation_is_created_and_priced(
        self, api, a_reservation_with_nothing_wrong_with_it
    ):
        """Consent, licence, zone, lead time, pool and payer all hold together.

        "among the order's plan's `ACTIVE` pools whose `benefit_year` equals the
        UTC calendar year of the target window's `window_start`, the one with the
        lowest `created_at` wins"

        Design: Corner/validations/clean_reservation_satisfies_every_evaluated_rule
        """
        net, order, window = a_reservation_with_nothing_wrong_with_it
        delivery = validate_success(_reserve(api, net, order, window), 201)

        assert "error_id" not in delivery
        assert_delivery_state(delivery, custody_status="QUEUED", settlement_status="PROVISIONAL")
        assert delivery["fee_subtotal_cents"] == Z1_STANDARD_SUBTOTAL_CENTS

        allocation = active_allocation(api, delivery["id"])
        assert_fee_lines(allocation, Z1_STANDARD_LINES)
        assert allocation["plan_grant_cents"] == 150
        assert allocation["plan_grant_id"] == net.grant["id"]

    def test_the_commercial_residue_falls_to_the_pharmacy_not_the_member(
        self, api, a_reservation_with_nothing_wrong_with_it
    ):
        """The Medicaid mandate is evaluated and skipped, so a 7-cent residue is absorbed.

        "Second — and only for a `MEDICAID` payer — if that eligible amount is
        less than the gross share, the request is rejected outright with
        `ERR_GRANT_COVERAGE_INSUFFICIENT`: a Medicaid member may not be billed any
        residue, so a pool that can only partly fund the share cannot be used at
        all."

        Design: Corner/validations/clean_reservation_satisfies_every_evaluated_rule
        """
        net, order, window = a_reservation_with_nothing_wrong_with_it
        assert net.plan["payer_type"] == "COMMERCIAL"
        delivery = validate_success(_reserve(api, net, order, window), 201)

        assert_payer_mix(
            active_allocation(api, delivery["id"]),
            patient_gross_share_cents=157,
            plan_grant_cents=150,
            absorption_tier_cents=50,
            pharmacy_absorption_cents=7,
            patient_payable_cents=0,
            pharmacy_payable_cents=1416,
        )
        assert read_order(api, order["id"])["status"] == "DISPATCHED"
        assert_window_occupancy(
            read_window(api, window["id"]), reserved_slots=1, available_slots=0, status="FULL"
        )


# ─── Capacity is an aggregate ─────────────────────────


@pytest.fixture
def three_ready_bags_and_two_slots(api):
    """Three individually valid reservations queuing for a two-slot window."""
    net = build_network(api)
    orders = [build_ready_order(api, net, **STANDARD_ORDER) for _ in range(3)]
    window = build_window(api, net.zone["id"], capacity_slots=2)
    return net, orders, window


class TestCapacityIsCheckedInTheAggregate:
    """"This is the aggregate check: each individual reservation is legal but the
    collective would exceed `capacity_slots`."
    """

    def test_the_status_flips_to_full_exactly_at_equality(
        self, api, three_ready_bags_and_two_slots
    ):
        """One reservation leaves the window OPEN; the second fills it precisely.

        "The window is `OPEN` while `reserved_slots` is below `capacity_slots` and
        the clock is still earlier than `window_end`, becomes `FULL` exactly when
        `reserved_slots` equals `capacity_slots`, and becomes `CLOSED` —
        permanently — once a routing sweep observes the clock at or after
        `window_end`."

        Design: Corner/validations/each_reservation_is_legal_but_the_third_exceeds_capacity
        """
        net, orders, window = three_ready_bags_and_two_slots
        validate_success(_reserve(api, net, orders[0], window), 201)
        assert_window_occupancy(
            read_window(api, window["id"]), reserved_slots=1, available_slots=1, status="OPEN"
        )

        validate_success(_reserve(api, net, orders[1], window), 201)
        assert_window_occupancy(
            read_window(api, window["id"]), reserved_slots=2, available_slots=0, status="FULL"
        )

    def test_the_third_bag_is_refused_though_nothing_about_it_is_wrong(
        self, api, three_ready_bags_and_two_slots
    ):
        """The collective, not the request, is what fails.

        "the window must not be `CLOSED` or `FULL` by status flag, or the request
        is `ERR_WINDOW_CLOSED`"

        Design: Corner/validations/each_reservation_is_legal_but_the_third_exceeds_capacity
        """
        net, orders, window = three_ready_bags_and_two_slots
        reserve_delivery(api, net, orders[0]["id"], window["id"])
        reserve_delivery(api, net, orders[1]["id"], window["id"])

        validate_error(_reserve(api, net, orders[2], window), "ERR_WINDOW_CLOSED", 409)

        _rows, meta = validate_paginated(
            api.list_deliveries(OPS_HEADERS, window_id=window["id"])
        )
        assert meta["total_count"] == 2
        assert read_order(api, orders[2]["id"])["status"] == "READY"
        assert_grant_ledger(read_grant(api, net.grant["id"]), committed_cents=300)
