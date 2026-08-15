"""Weather closures: refund tiers, paid basis, and the four-hop cascade."""
from test_helpers import (
    TEST_USERS,
    admit_online_session,
    book_addon,
    create_addon_product,
    create_pricing_policy_payload,
    enter_session,
    get_sales_day,
    offline_harvest_line_record,
    offline_payment_record,
    offline_session_record,
    only_line_of_session,
    only_session_on_window,
    pay_admission,
    pay_amount,
    set_clock,
    setup_operating_day,
    sign_waiver,
    upload_batch,
    validate_paginated,
    validate_success,
    get_session,
    get_window,
    get_field,
)

MANAGER = TEST_USERS["farm_manager_headers"]
GATE = TEST_USERS["gate_staff_headers"]
FIELD_STAFF = TEST_USERS["field_staff_headers"]


def _paid_basis_world(api):
    """Weekend session (party 2, 1 container) admitted under policy v1
    (800/person), paid 2200 CARD, then superseded by policy v2 (1600/400)."""
    world = setup_operating_day(
        date="2026-08-08", day_type="WEEKEND", clock_at="2026-08-08T09:30:00Z",
        waiver_names=("Ann", "Bob"),
        policy_values={"admission_per_person_cents": 800})
    session = admit_online_session(world, party_size=2, container_count=1,
                                   parking_spaces=1)
    assert session["admission_charge_cents"] == 2200  # 2000 surged + 200
    payment = pay_amount(session["id"], 2200, method="CARD", key="k1")
    world["session_id"] = session["id"]
    world["payment_id"] = payment["id"]
    season = validate_success(api.get_season(world["season_id"], MANAGER))
    superseding = validate_success(api.create_pricing_policy(
        create_pricing_policy_payload(
            world["season_id"], season["version"],
            admission_per_person_cents=1600, container_fee_cents=400),
        MANAGER), 201)
    world["policy_v2_id"] = superseding["id"]
    set_clock("2026-08-08T11:30:00Z")  # before noon: full-refund tier
    return world


class TestWeatherRefundPaidBasis:
    def test_weather_refund_uses_pinned_paid_basis(self, api):
        """PRD §3.8: "The refund is always computed from the session's pinned
        policy and its actual `admission_charge_cents` — the paid basis — and
        never repriced against the season's currently `ACTIVE` policy at
        closure time, even if the policy was superseded mid-day."
        PRD §3.8: "A closure before 12:00 refunds one hundred percent of the
        admission component"

        Design: Difficulty/dual_variant_calc/weather_refund_paid_basis_vs_current_policy
        """
        world = _paid_basis_world(api)
        validate_success(api.close_weather(world["day_id"], MANAGER))
        payment = validate_success(api.get_payment(world["payment_id"], MANAGER))
        # 100% of admission component 2000 + container 200 (no FINALIZED
        # lines); a current-policy reprice would yield 4400 and is forbidden.
        assert payment["refunded_amount_cents"] == 2200
        assert payment["status"] == "REFUNDED"
        session = get_session(world["session_id"])
        assert session["total_refunded_cents"] == 2200

    def test_weather_forced_checkout_mode_after_supersede(self, api):
        """PRD §3.8: "each cancelled window force-checks-out its on-site
        sessions to `CHECKED_OUT` with `checkout_mode` `WEATHER_FORCED`"
        PRD §3.1: "Creating a further policy for the same season supersedes the
        incumbent: the old policy becomes `SUPERSEDED` (terminal), the new one
        becomes `ACTIVE`"

        Design: Difficulty/dual_variant_calc/weather_refund_paid_basis_vs_current_policy
        """
        world = _paid_basis_world(api)
        validate_success(api.close_weather(world["day_id"], MANAGER))
        session = get_session(world["session_id"])
        assert session["visit_status"] == "CHECKED_OUT"
        assert session["checkout_mode"] == "WEATHER_FORCED"
        assert session["payment_status"] == "REFUNDED"
        old_policy = validate_success(
            api.get_pricing_policy(world["policy_id"], MANAGER))
        assert old_policy["status"] == "SUPERSEDED"


class TestNoonTierBoundary:
    def _noon_world(self, api):
        """Two paid CHECKED_IN sessions (party 1, 1 container -> 850 each)."""
        world = setup_operating_day()
        wv_b = sign_waiver(world["season_id"], ["Bob"], signer_name="Bob",
                           signer_email="bob@x.com")
        session_a = admit_online_session(world, container_count=1)
        session_b = admit_online_session(world, container_count=1,
                                         waiver_id=wv_b["id"])
        pay_admission(session_a, key="ka")
        pay_admission(session_b, key="kb")
        world["session_a_id"] = session_a["id"]
        world["session_b_id"] = session_b["id"]
        set_clock("2026-08-04T12:00:00Z")  # exactly noon
        return world

    def test_noon_closure_pins_closed_at_and_half_tier(self, api):
        """PRD §3.8: "A closure before 12:00 refunds one hundred percent of the
        admission component; a closure at or after 12:00 but before 15:00
        refunds fifty percent; a closure at or after 15:00 refunds nothing."
        PRD §3.8: "First, `closed_at_time` is pinned from the logical clock's
        current `HH:MM` UTC reading — it drives the refund tiers"

        Design: Difficulty/boundary_precision_check/weather_refund_tier_at_noon_boundary
        """
        world = self._noon_world(api)
        day = validate_success(api.close_weather(world["day_id"], MANAGER))
        assert day["closed_at_time"] == "12:00"
        # 50% of admission component 650 -> 325, plus container 200 (zero
        # FINALIZED lines): 525, not the 850 of the full tier.
        assert get_session(world["session_a_id"])["total_refunded_cents"] == 525
        assert get_session(world["session_b_id"])["total_refunded_cents"] == 525

    def test_noon_closure_leaves_sessions_partially_refunded(self, api):
        """PRD §3.7: "otherwise, if `total_refunded_cents` is greater than
        zero, it is `PARTIALLY_REFUNDED`"
        PRD §3.8: "A closure before 12:00 refunds one hundred percent of the
        admission component; a closure at or after 12:00 but before 15:00
        refunds fifty percent"

        Design: Difficulty/boundary_precision_check/weather_refund_tier_at_noon_boundary
        """
        world = self._noon_world(api)
        validate_success(api.close_weather(world["day_id"], MANAGER))
        session = get_session(world["session_a_id"])
        assert session["payment_status"] == "PARTIALLY_REFUNDED", (
            "850 paid, 525 refunded")
        assert session["checkout_mode"] == "WEATHER_FORCED"


def _cascade_world(api):
    """Offline session (party 2, 1 container, 1500 OFFLINE_CARD settled),
    entered the field, one PROVISIONAL line (net 100 oz), one BOOKED wagon
    booking (900) paid in cash. Clock parked at 11:00 for the full tier."""
    world = setup_operating_day(waiver_names=("Ann", "Bob"))
    wagon = create_addon_product(world["season_id"], kind="WAGON_RIDE",
                                 name="Orchard Wagon", price_cents=900,
                                 slot_capacity=20)
    world["wagon_id"] = wagon["id"]
    upload_batch("DEV1", "B1", [
        offline_session_record(
            1, "S1", window_id=world["window_id"], waiver_id=world["waiver_id"],
            pricing_policy_id=world["policy_id"], party_size=2,
            container_count=1, parking_spaces=1),
        offline_payment_record(2, "P1", session_ref="S1", amount_cents=1500),
    ])
    session = only_session_on_window(world["window_id"])
    world["session_id"] = session["id"]
    enter_session(session["id"])
    upload_batch("DEV1", "B2", [offline_harvest_line_record(
        1, "L1", session_ref="S1", crop_id=world["crop_id"],
        gross_weight_oz=116, container_count=4)])  # net 100 oz, PROVISIONAL
    booking = book_addon(session["id"], world["wagon_id"], slot_time="11:00",
                         qty=1)
    world["booking_id"] = booking["id"]
    pay_amount(session["id"], 900, key="k-addon")  # obligation 1500+900 met
    set_clock("2026-08-04T11:00:00Z")
    return world


class TestWeatherCascade:
    def test_weather_closure_cancels_window_and_force_checks_out(self, api):
        """PRD §3.8: "every window of the date in `SCHEDULED` or `OPEN` is
        cancelled with `cancel_reason` `WEATHER`."
        PRD §3.8: "each cancelled window force-checks-out its on-site sessions
        to `CHECKED_OUT` with `checkout_mode` `WEATHER_FORCED`; sessions
        already `CHECKED_OUT` keep their state."

        Design: Difficulty/transitive_cascade/weather_closure_four_hop_cascade
        """
        world = _cascade_world(api)
        validate_success(api.close_weather(world["day_id"], MANAGER))
        window = get_window(world["window_id"])
        assert window["status"] == "CANCELLED"
        assert window["cancel_reason"] == "WEATHER"
        session = get_session(world["session_id"])
        assert session["visit_status"] == "CHECKED_OUT"
        assert session["checkout_mode"] == "WEATHER_FORCED"

    def test_weather_closure_voids_lines_releases_addons_and_refunds(self, api):
        """PRD §3.8: "each forced checkout voids the session's `PROVISIONAL`
        harvest lines and computes a weather refund applied to its `SETTLED`
        charge payments in `created_at` ascending order, and every `BOOKED`
        add-on booking whose `booking_date` equals the closure date is released
        to `RELEASED` with a face-value refund into its session's ledger"
        PRD §3.8: "the total refund applied to a session never exceeds its net
        collected amount, and any excess is discarded — money is never
        created."

        Design: Difficulty/transitive_cascade/weather_closure_four_hop_cascade
        """
        world = _cascade_world(api)
        validate_success(api.close_weather(world["day_id"], MANAGER))

        line = only_line_of_session(world["session_id"])
        assert line["status"] == "VOIDED", "provisional weight never commits"
        booking = validate_success(
            api.get_addon_booking(world["booking_id"], MANAGER))
        assert booking["status"] == "RELEASED"

        # 1300 admission (100% tier, 11:00 < 12:00) + 200 container (no
        # FINALIZED lines) + 900 addon = 2400, applied oldest first.
        payments, _ = validate_paginated(api.list_payments(
            MANAGER, params={"session_id": world["session_id"]}))
        assert payments[0]["refunded_amount_cents"] == 1500
        assert payments[1]["refunded_amount_cents"] == 900

        session = get_session(world["session_id"])
        assert session["total_refunded_cents"] == 2400
        assert session["payment_status"] == "REFUNDED"
        assert get_sales_day(world["day_id"])["revenue_cents"] == 0
        field = get_field(world["field_id"])
        assert field["committed_picked_oz"] == 0
        assert field["projected_remaining_oz"] == 1000
