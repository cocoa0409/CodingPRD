"""Admission pricing, weigh-out rounding, checkout settlement, payments."""
from test_helpers import (
    TEST_USERS,
    admit_online_session,
    book_addon,
    create_addon_product,
    create_payment_payload,
    create_sales_day,
    create_visit_session_payload,
    create_window,
    enter_session,
    get_sales_day,
    get_session,
    offline_harvest_line_record,
    open_sales_day,
    open_window,
    pay_admission,
    pay_amount,
    set_clock,
    setup_operating_day,
    setup_paid_session,
    sign_waiver,
    upload_batch,
    validate_error,
    validate_paginated,
    validate_success,
    weigh_out,
)

MANAGER = TEST_USERS["farm_manager_headers"]
GATE = TEST_USERS["gate_staff_headers"]
FIELD_STAFF = TEST_USERS["field_staff_headers"]


def _surge_world(api):
    """One field, one waiver covering 3, a weekday window and a weekend window,
    both OPEN under policy A."""
    world = setup_operating_day(waiver_names=("Ann", "Bob", "Cid"))
    day_we = create_sales_day(world["season_id"], date="2026-08-08",
                              day_type="WEEKEND")
    world["day_weekend_id"] = day_we["id"]
    w_we = create_window(world["field_id"], date="2026-08-08",
                         open_time="09:00", close_time="17:00")
    world["window_weekend_id"] = w_we["id"]
    return world


def _open_weekend(api, world):
    set_clock("2026-08-08T09:30:00Z")
    open_sales_day(world["day_weekend_id"])
    open_window(world["window_weekend_id"])


class TestAdmissionCharge:
    def test_admission_weekday_no_surge(self, api):
        """PRD §3.4: "The admission charge is the sum of two components: the
        admission component, which is the pinned policy's
        `admission_per_person_cents` multiplied by `party_size` and then — only
        when the sales day's `day_type` is `WEEKEND` — multiplied by
        `weekend_surge_bps` divided by ten thousand with round-half-up to whole
        cents applied at that surge multiplication only; and the container
        component, which is `container_fee_cents` multiplied by
        `container_count`."

        Design: Difficulty/combinatorial_formula/admission_surge_component_rounding
        """
        world = _surge_world(api)
        session = admit_online_session(world, party_size=3, container_count=2,
                                       parking_spaces=1)
        assert session["admission_charge_cents"] == 2350, (
            "weekday: 650*3 + 200*2, no surge branch")

    def test_admission_weekend_surge_on_admission_component_only(self, api):
        """PRD §3.4: "The admission charge is the sum of two components: the
        admission component, which is the pinned policy's
        `admission_per_person_cents` multiplied by `party_size` and then — only
        when the sales day's `day_type` is `WEEKEND` — multiplied by
        `weekend_surge_bps` divided by ten thousand with round-half-up to whole
        cents applied at that surge multiplication only; and the container
        component, which is `container_fee_cents` multiplied by
        `container_count`."

        Design: Difficulty/combinatorial_formula/admission_surge_component_rounding
        """
        world = _surge_world(api)
        admit_online_session(world, party_size=3, container_count=2,
                             parking_spaces=1)  # weekday guest first
        _open_weekend(api, world)
        session = admit_online_session(world, party_size=3, container_count=2,
                                       parking_spaces=1,
                                       window_id=world["window_weekend_id"])
        # round_half_up(1950 * 12500/10000) = 2438 admission; + 400 containers.
        assert session["admission_charge_cents"] == 2838, (
            "the surge multiplies only the admission component; "
            "a whole-charge multiplication would give 2938")


def _rounding_world(api):
    """Session FIELD_ACTIVE under a 310 c/lb crop, admission paid."""
    world = setup_operating_day(crop_price_per_lb=310)
    session = setup_paid_session(world, container_count=0, enter=True)
    world["session_id"] = session["id"]
    return world


class TestWeighOutRoundingOrder:
    def test_per_line_rounding_half_up(self, api):
        """PRD §3.5: "`line_charge_cents` is `net_oz` multiplied by the crop's
        `price_per_lb_cents` and divided by 16 ounces per pound, rounded half
        up to whole cents."
        PRD §3.5: "two one-ounce lines at 310 cents per pound round to 19
        cents each and total 38 cents per line, whereas rounding the combined
        38.75 cents once would yield 39."

        Design: Difficulty/combinatorial_formula/weighout_per_line_rounding_order
        """
        world = _rounding_world(api)
        line1 = weigh_out(world["session_id"], world["crop_id"], 5, 1)
        line2 = weigh_out(world["session_id"], world["crop_id"], 5, 1)
        assert line1["net_oz"] == 1  # gross 5 - tare 4
        assert line1["line_charge_cents"] == 19, "round_half_up(1*310/16)"
        assert line2["line_charge_cents"] == 19

    def test_checkout_sums_per_line_rounded_charges(self, api):
        """PRD §3.5: "the rounding order is pinned: round each line first, then
        sum the already-rounded line charges. Summing first and rounding once
        is the forbidden alternative"

        Design: Difficulty/combinatorial_formula/weighout_per_line_rounding_order
        """
        world = _rounding_world(api)
        weigh_out(world["session_id"], world["crop_id"], 5, 1)
        weigh_out(world["session_id"], world["crop_id"], 5, 1)
        pay_amount(world["session_id"], 38, key="k2", headers=FIELD_STAFF)
        session = validate_success(
            api.checkout_session(world["session_id"], FIELD_STAFF))
        assert session["final_total_cents"] == 688, (
            "650 admission + 19 + 19 per line; sum-then-round would give 689")


def _bundle_world(api):
    """FIELD_ACTIVE session (party 2, 1 container, admission 1500 paid) with a
    REDEEMED wagon booking and a REDEEMED cafe booking plus one FINALIZED line
    of net 20 oz (600 c)."""
    world = setup_operating_day(waiver_names=("Ann", "Bob"))
    wagon = create_addon_product(world["season_id"], kind="WAGON_RIDE",
                                 name="Orchard Wagon", price_cents=900,
                                 slot_capacity=20)
    cafe = create_addon_product(world["season_id"], kind="CAFE_VOUCHER",
                                name="Cafe Voucher", price_cents=600,
                                slot_capacity=20)
    session = setup_paid_session(world, party_size=2, container_count=1,
                                 enter=True)
    world["session_id"] = session["id"]
    bk_w = book_addon(session["id"], wagon["id"], slot_time="11:00", qty=1)
    bk_c = book_addon(session["id"], cafe["id"], slot_time="12:00", qty=1)
    validate_success(api.redeem_addon_booking(bk_w["id"], FIELD_STAFF))
    validate_success(api.redeem_addon_booking(bk_c["id"], FIELD_STAFF))
    weigh_out(session["id"], world["crop_id"], 36, 4)  # net 20 oz -> 600 c
    pay_amount(session["id"], 1800, method="CARD", key="k2", headers=FIELD_STAFF)
    return world


class TestBundleDiscountOrder:
    def test_bundle_discount_excludes_harvest_from_base(self, api):
        """PRD §3.7: "Second, the discount base is `admission_charge_cents`
        plus that add-on total — harvest charges are excluded from the base."
        PRD §3.7: "Third, `bundle_discount_cents` is zero unless the session
        holds at least one `REDEEMED` `WAGON_RIDE` booking and at least one
        `REDEEMED` `CAFE_VOUCHER` booking; with both present, the discount is
        the lesser of the policy's `bundle_cap_cents` and the policy's
        `bundle_discount_bps` multiplied by the discount base and divided by
        ten thousand, rounded half up to whole cents."

        Design: Difficulty/combinatorial_formula/bundle_discount_evaluation_order
        """
        world = _bundle_world(api)
        session = validate_success(
            api.checkout_session(world["session_id"], FIELD_STAFF))
        # base = 1500 admission + 1500 addons = 3000; min(1500 cap, 300) = 300.
        assert session["bundle_discount_cents"] == 300

    def test_final_total_follows_pinned_evaluation_order(self, api):
        """PRD §3.7: "Fifth and last, `final_total_cents` is
        `admission_charge_cents` plus the add-on total plus the harvest total
        minus `bundle_discount_cents`."

        Design: Difficulty/combinatorial_formula/bundle_discount_evaluation_order
        """
        world = _bundle_world(api)
        session = validate_success(
            api.checkout_session(world["session_id"], FIELD_STAFF))
        # 1500 + 1500 addons + 600 harvest - 300 bundle = 3300; including
        # harvest in the discount base (discount 360, final 3240) is forbidden.
        assert session["final_total_cents"] == 3300
        assert session["visit_status"] == "CHECKED_OUT"
        assert session["checkout_mode"] == "NORMAL"


class TestTareBoundary:
    def test_tare_exactly_equals_gross_zero_net_accepted(self, api):
        """PRD §3.5: "`net_oz` is `gross_weight_oz` minus `tare_oz`; a negative
        result is impossible to accept and the create is rejected with
        `ERR_TARE_EXCEEDS_GROSS` (422), while exactly zero is legal."

        Design: Difficulty/boundary_precision_check/tare_exactly_equals_gross_zero_net
        """
        world = setup_operating_day()
        session = setup_paid_session(world, enter=True)
        line = weigh_out(session["id"], world["crop_id"], 16, 4)  # net 0
        assert line["net_oz"] == 0
        assert line["line_charge_cents"] == 0
        assert line["status"] == "FINALIZED"

    def test_net_below_zero_rejected_and_nothing_persisted(self, api):
        """PRD §3.5: "a negative result is impossible to accept and the create
        is rejected with `ERR_TARE_EXCEEDS_GROSS` (422), while exactly zero is
        legal."

        Design: Difficulty/boundary_precision_check/tare_exactly_equals_gross_zero_net
        """
        world = setup_operating_day()
        session = setup_paid_session(world, enter=True)
        weigh_out(session["id"], world["crop_id"], 16, 4)  # the zero-net line
        resp = api.create_harvest_line(
            {"session_id": session["id"], "crop_id": world["crop_id"],
             "gross_weight_oz": 15, "container_count": 4},
            FIELD_STAFF)
        validate_error(resp, "ERR_TARE_EXCEEDS_GROSS", 422)
        _, meta = validate_paginated(api.list_harvest_lines(
            MANAGER, params={"session_id": session["id"]}))
        assert meta["total_count"] == 1, "only the zero-net line was persisted"


class TestPaymentAmountSanity:
    def test_payment_exceeds_outstanding_obligation_rejected(self, api):
        """PRD §3.7: "an over-collection is rejected with
        `ERR_PAYMENT_AMOUNT_INVALID` (422)."
        PRD §3.7: "`amount_cents` must not exceed the session's outstanding
        obligation"

        Design: Corner/validations/payment_exceeds_outstanding_obligation_rejected
        """
        world = setup_operating_day()
        session = admit_online_session(world)  # admission 650, unpaid
        resp = api.create_payment(
            create_payment_payload(session["id"], amount_cents=700,
                                   idempotency_key="k1"),
            GATE)
        validate_error(resp, "ERR_PAYMENT_AMOUNT_INVALID", 422)


class TestCheckoutGates:
    def test_checkout_blocked_by_provisional_lines(self, api):
        """PRD §3.7: "no harvest line of the session may still be `PROVISIONAL`
        (`ERR_UNRESOLVED_LINES`, 422)"

        Design: Corner/validations/checkout_blocked_by_provisional_lines
        """
        world = setup_operating_day()
        session = setup_paid_session(world, enter=True)
        upload_batch("DEV1", "B7", [offline_harvest_line_record(
            1, "L7", session_ref=session["id"], crop_id=world["crop_id"],
            gross_weight_oz=116, container_count=4)])

        resp = api.checkout_session(session["id"], FIELD_STAFF)
        validate_error(resp, "ERR_UNRESOLVED_LINES", 422)
        after = get_session(session["id"])
        assert after["visit_status"] == "FIELD_ACTIVE"
        assert after["final_total_cents"] is None

    def test_checkout_cancelled_session_returns_invalid_state(self, api):
        """PRD §3.7: "Checkout is the `FieldStaff` close of a visit, moving a
        session from `CHECKED_IN` or `FIELD_ACTIVE` to `CHECKED_OUT` with
        `checkout_mode` `NORMAL`."
        PRD §2.7: "the addressed resource's own state must permit the requested
        transition"

        Design: Corner/state_machines/checkout_cancelled_session_returns_invalid_state
        """
        world = setup_operating_day()
        session = admit_online_session(world)
        validate_success(api.cancel_session(session["id"], GATE))
        resp = api.checkout_session(session["id"], FIELD_STAFF)
        validate_error(resp, "ERR_INVALID_STATE", 409)


class TestManualRefund:
    def test_refund_exceeds_remaining_rejected(self, api):
        """PRD §3.7: "The requested `amount_cents` must not exceed the
        payment's remaining unrefunded amount — its `amount_cents` minus its
        `refunded_amount_cents` — else `ERR_REFUND_EXCEEDS_PAID` (422)."
        PRD §3.7: "a refund exactly equal to the remainder moves the payment to
        `REFUNDED` with `refunded_amount_cents` equal to its full
        `amount_cents`."

        Design: Corner/validations/refund_exceeds_remaining_rejected
        """
        world = setup_operating_day()
        session = admit_online_session(world, container_count=1)
        payment = pay_admission(session, key="k1")  # 850 CASH, SETTLED

        resp = api.refund_payment(payment["id"], 851, MANAGER)
        validate_error(resp, "ERR_REFUND_EXCEEDS_PAID", 422)

        mid = validate_success(api.refund_payment(payment["id"], 400, MANAGER))
        assert mid["status"] == "PARTIALLY_REFUNDED"

        end = validate_success(api.refund_payment(payment["id"], 450, MANAGER))
        assert end["status"] == "REFUNDED", "400 + 450 == 850 exactly"
        assert end["refunded_amount_cents"] == 850

    def test_payment_idempotency_key_replay_charges_once(self, api):
        """PRD §3.7: "The key is unique per session among charge payments, and
        replaying a key that session has already used returns the original
        payment instead of creating a duplicate."

        Design: Corner/cross_cutting_layers/payment_idempotency_key_replay_charges_once
        """
        world = setup_operating_day()
        session = admit_online_session(world, container_count=1)
        first = pay_amount(session["id"], 850, method="CARD", key="k-dup")
        assert first["status"] == "SETTLED"
        second = pay_amount(session["id"], 850, method="CARD", key="k-dup")
        assert second["id"] == first["id"], "replay returns the original payment"
        assert get_session(session["id"])["total_paid_cents"] == 850, (
            "charged exactly once")


def _checked_out_world(api):
    """Session checked out with final_total 2100 (admission 1500 + line 600),
    fully paid by two CASH payments (1500 + 600)."""
    world = setup_operating_day(waiver_names=("Ann", "Bob"))
    session = setup_paid_session(world, party_size=2, container_count=1,
                                 enter=True, key="k1")
    weigh_out(session["id"], world["crop_id"], 36, 4)  # net 20 -> 600 c
    pay_amount(session["id"], 600, key="k2", headers=FIELD_STAFF)
    session = validate_success(api.checkout_session(session["id"], FIELD_STAFF))
    world["session_id"] = session["id"]
    return world


class TestParallelPaymentStatus:
    def test_refund_after_checkout_moves_payment_axis(self, api):
        """PRD §3.4: "Two status dimensions ride on every session row in
        parallel."
        PRD §3.7: "A refund smaller than the remainder leaves the payment
        `PARTIALLY_REFUNDED` with `refunded_amount_cents` increased by the
        refunded amount"

        Design: Difficulty/non_linear_state_machine/session_parallel_payment_after_checkout
        """
        world = _checked_out_world(api)
        rows, _ = validate_paginated(api.list_payments(
            MANAGER, params={"session_id": world["session_id"]}))
        first_payment = rows[0]

        refunded = validate_success(
            api.refund_payment(first_payment["id"], 400, MANAGER))
        assert refunded["status"] == "PARTIALLY_REFUNDED"
        assert refunded["refunded_amount_cents"] == 400
        session = get_session(world["session_id"])
        assert session["payment_status"] == "PARTIALLY_REFUNDED"

    def test_visit_axis_stays_terminal_after_refund(self, api):
        """PRD §3.4: "Neither dimension directly mutates the other — only
        payment and refund writes, and the checkout and weather calculations,
        move `payment_status`, and only the visit transitions move
        `visit_status`."

        Design: Difficulty/non_linear_state_machine/session_parallel_payment_after_checkout
        """
        world = _checked_out_world(api)
        session = get_session(world["session_id"])
        assert session["final_total_cents"] == 2100
        assert session["visit_status"] == "CHECKED_OUT"

        rows, _ = validate_paginated(api.list_payments(
            MANAGER, params={"session_id": world["session_id"]}))
        validate_success(api.refund_payment(rows[0]["id"], 400, MANAGER))
        after = get_session(world["session_id"])
        assert after["visit_status"] == "CHECKED_OUT", (
            "the refund moved only the payment axis")
        assert after["total_refunded_cents"] == 400


class TestMoneyConservation:
    def _settled_world(self, api):
        world = setup_operating_day()
        session = admit_online_session(world, container_count=1)
        payment = pay_admission(session, key="k1")  # 850 CASH
        return world, session, payment

    def test_settle_then_exact_refund_conserves_revenue(self, api):
        """PRD §3.3: "its `revenue_cents` is the sum over all sessions on the
        day's windows of each session's `total_paid_cents` minus its
        `total_refunded_cents`."
        PRD §3.7: "a refund exactly equal to the remainder moves the payment to
        `REFUNDED` with `refunded_amount_cents` equal to its full
        `amount_cents`."

        Design: Difficulty/compensating_invariant/payment_refund_money_conservation
        """
        world, session, payment = self._settled_world(api)
        assert get_sales_day(world["day_id"])["revenue_cents"] == 850

        refunded = validate_success(
            api.refund_payment(payment["id"], 850, MANAGER))
        assert refunded["status"] == "REFUNDED"
        assert refunded["refunded_amount_cents"] == 850
        assert get_sales_day(world["day_id"])["revenue_cents"] == 0, (
            "settle paired with its compensating refund leaves no drift")

    def test_session_ledgers_return_to_zero(self, api):
        """PRD §3.7: "if `total_refunded_cents` is greater than or equal to
        `total_paid_cents` (which here means something was paid and then fully
        returned), the session is `REFUNDED`"

        Design: Difficulty/compensating_invariant/payment_refund_money_conservation
        """
        world, session, payment = self._settled_world(api)
        validate_success(api.refund_payment(payment["id"], 850, MANAGER))
        after = get_session(session["id"])
        assert after["total_paid_cents"] - after["total_refunded_cents"] == 0
        assert after["payment_status"] == "REFUNDED"
        assert after["visit_status"] == "CHECKED_IN", (
            "a refund alone does not cancel the visit")


class TestStateBeatsFiscal:
    def _cancelled_world(self, api):
        world = setup_operating_day()
        session = admit_online_session(world)  # admission 650, never paid
        validate_success(api.cancel_session(session["id"], GATE))
        return world, session

    def test_payment_on_cancelled_session_reports_state_error(self, api):
        """PRD §2.7: "Every request passes through an ordered validation
        pipeline, and the first failing gate wins — its error is the one
        returned, even if a later gate would also have failed."
        PRD §2.7: "the session must be `FIELD_ACTIVE` for harvest-line
        creation, and in `CHECKED_IN` or `FIELD_ACTIVE` for payment collection
        and add-on booking creation (`ERR_SESSION_NOT_ACTIVE`, 409)"

        Design: Difficulty/priority_pair_validation_conflict/state_beats_fiscal_on_cancelled_session_payment
        """
        _, session = self._cancelled_world(api)
        resp = api.create_payment(
            create_payment_payload(session["id"], amount_cents=999999,
                                   idempotency_key="kbad"),
            GATE)
        # Both the state gate and the fiscal sanity gate fail; state wins.
        validate_error(resp, "ERR_SESSION_NOT_ACTIVE", 409)

    def test_state_error_fires_even_for_a_valid_amount(self, api):
        """PRD §2.7: "the session must be `FIELD_ACTIVE` for harvest-line
        creation, and in `CHECKED_IN` or `FIELD_ACTIVE` for payment collection
        and add-on booking creation (`ERR_SESSION_NOT_ACTIVE`, 409)"

        Design: Difficulty/priority_pair_validation_conflict/state_beats_fiscal_on_cancelled_session_payment
        """
        _, session = self._cancelled_world(api)
        # 650 equals the cancelled session's whole obligation: only the state
        # gate can fail here, isolating it from the fiscal gate.
        resp = api.create_payment(
            create_payment_payload(session["id"], amount_cents=650,
                                   idempotency_key="kbad2"),
            GATE)
        validate_error(resp, "ERR_SESSION_NOT_ACTIVE", 409)
