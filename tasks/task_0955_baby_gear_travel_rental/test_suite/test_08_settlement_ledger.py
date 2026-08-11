"""Settlement: provisional-vs-final totals, the late-fee grace boundary, the
deposit waterfall and its conservation invariant, hotel commission rounding,
and risk-score threshold triggers."""
import pytest

from test_helpers import (
    TEST_USERS,
    approve_claim,
    assert_deposit_conservation,
    create_catalog_item,
    create_customer,
    create_extension,
    create_hotel_partner,
    create_quoted_reservation,
    create_unit,
    confirm_reservation,
    approve_extension,
    deliver_reservation,
    file_damage_claim,
    get_claim,
    get_customer_by_id,
    get_reservation,
    list_deposit_transactions,
    list_lines,
    make_customer_headers,
    pickup_reservation,
    setup_confirmed_reservation,
    setup_returned_reservation,
    setup_settled_reservation,
    validate_error,
    validate_success,
)


def _ops():
    return TEST_USERS["ops_admin_headers"]


def _settle(api, reservation_id):
    return validate_success(api.settle_reservation(reservation_id, _ops()), 200)


class TestProvisionalVsFinalAfterExtension:
    def _setup_extended_returned(self):
        """Confirmed 06-10 -> 06-13, delivered, extended by 2 days to 06-15,
        returned on time at 2026-06-15T00:00:00Z."""
        ctx = setup_confirmed_reservation()
        customer = ctx["customer"]
        reservation = ctx["reservation"]
        delivery = deliver_reservation(reservation, clock="2026-06-10T09:00:00Z")
        reservation = delivery["reservation"]
        ext = create_extension(reservation["id"], customer["id"], "2026-06-15")
        approved = approve_extension(ext["id"])
        reservation = get_reservation(reservation["id"])
        pickup = pickup_reservation(
            reservation,
            clock="2026-06-15T00:00:00Z",
            route_date="2026-06-15",
            window=("2026-06-15T00:00:00Z", "2026-06-15T06:00:00Z"),
        )
        ctx["reservation"] = pickup["reservation"]
        ctx["extension"] = approved
        return ctx

    def test_final_total_combines_quote_extension_and_late_fee(self, api):
        """PRD 3.7: "The final charge is then `final_total_cents`, the quoted
        total plus the accumulated `extension_charge_cents` plus the
        `late_fee_cents`; identical planned data with an approved extension or
        a late return therefore settles to a different number than the
        provisional quote."
        PRD 3.7: "the first two extension days are billed per day at the unit
        rate times 1.20, rounded half-up, and every day from the third onward
        at the unit rate times 1.50, rounded half-up"

        Quoted 13000 (3 days at 3000/day -> gear 9000, delivery 2500, setup
        1500); 2 extension days at round_half_up(3000 x 1.20) = 3600/day ->
        7200; on-time return -> late fee 0; final 13000 + 7200 + 0 = 20200.

        Design: Difficulty/dual_variant_calc/quote_provisional_vs_final_after_extension
        """
        ctx = self._setup_extended_returned()
        settled = _settle(api, ctx["reservation"]["id"])
        assert settled["quoted_total_cents"] == 13000
        assert settled["extension_charge_cents"] == 7200
        assert settled["late_fee_cents"] == 0
        assert settled["final_total_cents"] == 20200

    def test_final_variant_differs_from_provisional_quote(self, api):
        """PRD 3.7: "identical planned data with an approved extension or a
        late return therefore settles to a different number than the
        provisional quote."
        PRD 3.7: "Because line charges are frozen at quote time, an extension
        changes the final bill without touching any line's
        `line_charge_cents`."

        The provisional variant (13000) and the final variant (20200) price the
        same reservation differently once the extension is approved; the line's
        frozen line_charge_cents stays 9000 while the extension request carries
        the 7200 surcharge.

        Design: Difficulty/dual_variant_calc/quote_provisional_vs_final_after_extension
        """
        ctx = self._setup_extended_returned()
        assert ctx["extension"]["extension_charge_cents"] == 7200
        line = list_lines(ctx["reservation"]["id"])[0]
        assert line["line_charge_cents"] == 9000
        settled = _settle(api, ctx["reservation"]["id"])
        assert settled["final_total_cents"] != settled["quoted_total_cents"]
        assert settled["final_total_cents"] == 20200
        assert settled["status"] == "SETTLED"


class TestLateFeeGraceBoundary:
    def _setup_pair(self):
        """Two customers, two units of one catalog, identical 06-10 -> 06-13
        reservations, both delivered; caller completes the pickups."""
        cust1 = create_customer()
        cust2 = create_customer()
        catalog = create_catalog_item()
        create_unit(catalog["id"])
        create_unit(catalog["id"])
        res1 = create_quoted_reservation(
            cust1["id"],
            lines=[{"catalog_item_id": catalog["id"]}],
            delivery_address="14 Koa Rd",
        )
        res2 = create_quoted_reservation(
            cust2["id"],
            lines=[{"catalog_item_id": catalog["id"]}],
            delivery_address="15 Koa Rd",
        )
        confirm_reservation(res1["id"], cust1["id"])
        confirm_reservation(res2["id"], cust2["id"])
        deliver_reservation(
            get_reservation(res1["id"]),
            clock="2026-06-10T08:30:00Z",
            window=("2026-06-10T08:00:00Z", "2026-06-10T09:00:00Z"),
        )
        deliver_reservation(
            get_reservation(res2["id"]),
            clock="2026-06-10T09:30:00Z",
            window=("2026-06-10T09:00:00Z", "2026-06-10T10:00:00Z"),
        )
        return res1, res2

    def test_exactly_240_minutes_late_is_free(self, api):
        """PRD 3.7: "A grace window of four hours applies: lateness of exactly
        240 minutes or less is free, and no late-return counter moves."

        Returned at 2026-06-13T04:00:00Z against a due instant of
        2026-06-13T00:00:00Z is exactly 240 minutes: late_fee_cents 0, the full
        15000 hold is released, and payment lands REFUNDED.

        Design: Difficulty/boundary_precision_check/late_fee_grace_boundary_240_vs_241
        """
        res1, _ = self._setup_pair()
        pickup_reservation(
            get_reservation(res1["id"]),
            clock="2026-06-13T04:00:00Z",
            window=("2026-06-13T00:00:00Z", "2026-06-13T03:00:00Z"),
        )
        settled = _settle(api, res1["id"])
        assert settled["late_fee_cents"] == 0
        assert settled["payment_status"] == "REFUNDED"
        assert settled["deposit_captured_cents"] == 0
        assert settled["deposit_released_cents"] == 15000
        assert_deposit_conservation(settled)

    def test_241_minutes_late_bills_one_full_hour(self, api):
        """PRD 3.7: "One minute beyond the grace bills a full first hour: the
        minutes beyond 240 are rounded up to whole billable hours, each billed
        at the greater of one cent and the line's `unit_rate_cents` times 0.15
        rounded half-up, and each line's fee is capped at twice its
        `unit_rate_cents`."

        241 minutes late -> 1 billable hour at round_half_up(3000 x 0.15) =
        450; the waterfall captures 450 and releases 14550 of the 15000 hold.

        Design: Difficulty/boundary_precision_check/late_fee_grace_boundary_240_vs_241
        """
        _, res2 = self._setup_pair()
        pickup_reservation(
            get_reservation(res2["id"]),
            clock="2026-06-13T04:01:00Z",
            window=("2026-06-13T03:00:00Z", "2026-06-13T06:00:00Z"),
        )
        settled = _settle(api, res2["id"])
        assert settled["late_fee_cents"] == 450
        assert settled["deposit_captured_cents"] == 450
        assert settled["deposit_released_cents"] == 14550
        assert settled["payment_status"] == "SETTLED_PAID"
        assert_deposit_conservation(settled)


class TestDepositLedgerConservation:
    def _setup_settled_with_claim_and_late(self):
        """Grade-B unit, uninsured, returned at 04:01 (late fee 450) with one
        APPROVED MINOR claim at repair 10000 (capture 4800)."""
        ctx = setup_returned_reservation(
            grade="B", pickup_clock="2026-06-13T04:01:00Z"
        )
        claim = file_damage_claim(
            ctx["lines"][0]["id"],
            severity="MINOR",
            repair_cost_cents=10000,
            description="wheel damage",
        )
        approve_claim(claim["id"], reviewer_user_id="ops-1")
        ctx["claim"] = claim
        return ctx

    def test_hold_equals_captured_plus_released(self, api):
        """PRD 2.9: "The conserved quantity across a reservation's ledger is
        that the original hold equals the total captured plus the total
        released; the counters `deposit_captured_cents` and
        `deposit_released_cents` on the reservation mirror the ledger."

        Hold 15000 = captured 5250 (4800 damage + 450 late) + released 9750.

        Design: Difficulty/compensating_invariant/deposit_ledger_conservation_after_settle
        """
        ctx = self._setup_settled_with_claim_and_late()
        settled = _settle(api, ctx["reservation"]["id"])
        assert settled["deposit_hold_cents"] == 15000
        assert settled["deposit_captured_cents"] == 5250
        assert settled["deposit_released_cents"] == 9750
        assert_deposit_conservation(settled)

    def test_ledger_reproduces_waterfall_entry_by_entry(self, api):
        """PRD 3.7: "The waterfall drains the hold in strict bucket order —
        first the approved claims, processed in claim `created_at` ascending,
        each capturing the lesser of its `capture_amount_cents` and the
        remaining hold under reason `DAMAGE_CLAIM`; then the late fee,
        capturing the lesser of `late_fee_cents` and the remainder under reason
        `LATE_FEE`; and finally a single `RELEASE` entry returns whatever is
        left under reason `RELEASE_REMAINDER`, if anything remains."

        Ledger: HOLD 15000 (balance 15000), CAPTURE 4800 DAMAGE_CLAIM (10200),
        CAPTURE 450 LATE_FEE (9750), RELEASE 9750 RELEASE_REMAINDER (0).

        Design: Difficulty/compensating_invariant/deposit_ledger_conservation_after_settle
        """
        ctx = self._setup_settled_with_claim_and_late()
        _settle(api, ctx["reservation"]["id"])
        txns = list_deposit_transactions(ctx["reservation"]["id"])
        stream = [
            (t["txn_type"], t["amount_cents"], t["reason"], t["balance_after_cents"])
            for t in txns
        ]
        assert stream == [
            ("HOLD", 15000, "HOLD_AT_CONFIRM", 15000),
            ("CAPTURE", 4800, "DAMAGE_CLAIM", 10200),
            ("CAPTURE", 450, "LATE_FEE", 9750),
            ("RELEASE", 9750, "RELEASE_REMAINDER", 0),
        ]


class TestSettleCascadesCaptureRiskSuspension:
    def _setup_three_claims_one_late(self):
        """Three-line reservation (grade-A units, deposit 15000 each),
        returned 1 minute past grace; three APPROVED COSMETIC claims at repair
        10000 each (capture 2500 each, uninsured)."""
        ctx = setup_returned_reservation(
            num_lines=3, pickup_clock="2026-06-13T04:01:00Z"
        )
        claims = []
        for i, line in enumerate(ctx["lines"]):
            claim = file_damage_claim(
                line["id"],
                severity="COSMETIC",
                repair_cost_cents=10000,
                description=f"damage {i}",
            )
            approve_claim(claim["id"], reviewer_user_id="ops-1")
            claims.append(claim)
        ctx["claims"] = claims
        return ctx

    def test_settle_captures_approved_claims_and_late_fee(self, api):
        """PRD 3.7: "Claims resolve into the deposit: claims still
        `UNDER_REVIEW` are simply not captured, while every `APPROVED` claim
        moves to `CAPTURED`, version bumped, reviewer preserved."

        Three COSMETIC captures of round_half_up(10000 x 0.25 x 1.0) = 2500
        each plus a 3-line late fee of 3 x 450 = 1350: captured 8850, released
        36150 of the 45000 hold; all three claims land CAPTURED.

        Design: Difficulty/transitive_cascade/settle_cascades_capture_risk_suspension
        """
        ctx = self._setup_three_claims_one_late()
        settled = _settle(api, ctx["reservation"]["id"])
        assert settled["late_fee_cents"] == 1350
        assert settled["deposit_captured_cents"] == 8850
        assert settled["deposit_released_cents"] == 36150
        assert_deposit_conservation(settled)
        for claim in ctx["claims"]:
            after = get_claim(claim["id"])
            assert after["status"] == "CAPTURED"
            assert after["reviewed_by_user_id"] == "ops-1"

    def test_risk_score_90_auto_suspends_customer(self, api):
        """PRD 3.2: "The `risk_score` is a weighted sum, capped at 100: fifteen
        points per settled late return plus twenty-five points per captured
        damage claim."
        PRD 3.7: "The customer's `captured_damage_count` grows by the number of
        claims captured, the `risk_score` is recomputed from the updated
        counters, and if it has reached 90 the customer cascades from `ACTIVE`
        to `SUSPENDED` there and then."

        3 captured claims (3 x 25) + 1 late return (15) = 90 -> the settlement
        suspends the customer.

        Design: Difficulty/transitive_cascade/settle_cascades_capture_risk_suspension
        """
        ctx = self._setup_three_claims_one_late()
        _settle(api, ctx["reservation"]["id"])
        customer = get_customer_by_id(ctx["customer"]["id"])
        assert customer["late_return_count"] == 1
        assert customer["captured_damage_count"] == 3
        assert customer["risk_score"] == 90
        assert customer["status"] == "SUSPENDED"


class TestHotelCommissionPerLineRounding:
    def _setup_settled_partner_reservation(self):
        """Partner at 10% commission; items P (1055/day) and Q (2055/day), one
        unit each; 1-day reservation 06-10 -> 06-11 delivered and returned on
        time."""
        customer = create_customer()
        partner = create_hotel_partner(zone_code="Z1", commission_pct=0.10)
        cat_p = create_catalog_item(
            name="Item P",
            daily_rate_cents=1055,
            deposit_amount_cents=5000,
            weight_kg=5.0,
            cleaning_turnaround_hours=0,
        )
        cat_q = create_catalog_item(
            name="Item Q",
            category="STROLLER",
            daily_rate_cents=2055,
            deposit_amount_cents=5000,
            weight_kg=5.0,
            cleaning_turnaround_hours=0,
        )
        create_unit(cat_p["id"])
        create_unit(cat_q["id"])
        reservation = create_quoted_reservation(
            customer["id"],
            lines=[{"catalog_item_id": cat_p["id"]}, {"catalog_item_id": cat_q["id"]}],
            hotel_partner_id=partner["id"],
            delivery_address="Grand Hotel Front Desk",
            start_date="2026-06-10",
            end_date="2026-06-11",
        )
        confirm_reservation(reservation["id"], customer["id"])
        deliver_reservation(get_reservation(reservation["id"]))
        pickup = pickup_reservation(
            get_reservation(reservation["id"]),
            clock="2026-06-11T00:00:00Z",
            route_date="2026-06-11",
            window=("2026-06-11T00:00:00Z", "2026-06-11T06:00:00Z"),
        )
        return pickup["reservation"]

    def test_commission_rounds_per_line_then_sums(self, api):
        """PRD 3.7: "When the reservation named a hotel partner, commission is
        computed per line — each line's `line_charge_cents` times the partner's
        `commission_pct`, rounded half-up per line, then summed into
        `commission_cents`; rounding once after summing is a different,
        incorrect value, and extensions do not enter the base because they
        never alter line charges."

        Line charges 1055 and 2055 at 10%: per-line round_half_up gives
        106 + 206 = 312.

        Design: Difficulty/combinatorial_formula/hotel_commission_per_line_rounding_then_sum
        """
        reservation = self._setup_settled_partner_reservation()
        settled = _settle(api, reservation["id"])
        assert settled["commission_cents"] == 312
        assert settled["gear_subtotal_cents"] == 3110

    def test_commission_rejects_sum_then_round(self, api):
        """PRD 3.7: "rounding once after summing is a different, incorrect
        value"

        The forbidden sum-then-round order would produce
        round_half_up(3110 x 0.10) = 311; the pinned per-line order produces
        312, and the settled record must show 312.

        Design: Difficulty/combinatorial_formula/hotel_commission_per_line_rounding_then_sum
        """
        reservation = self._setup_settled_partner_reservation()
        settled = _settle(api, reservation["id"])
        assert settled["commission_cents"] == 312
        assert settled["commission_cents"] != 311, (
            "sum-then-round (311) is the explicitly forbidden order"
        )


def test_settled_reservation_rejects_second_settle(api):
    """PRD 3.7: "Finally `payment_status` leaves `DEPOSIT_HELD` for
    `SETTLED_PAID` when anything was captured, else `REFUNDED`, the reservation
    lands in the terminal `SETTLED` state, and the deposit ledger stands
    conserved: the hold equals exactly what was captured plus what was
    released."
    PRD 2.8: "State-machine preconditions — the transition must be legal from
    the current state, terminal states are locked, ... — else
    `ERR_INVALID_STATE` (409)."

    A second settle on the terminal SETTLED reservation is rejected and the
    ledger keeps exactly its HOLD + RELEASE entries.

    Design: Corner/state_machines/settled_reservation_rejects_second_settle
    """
    ctx = setup_settled_reservation(pickup_clock="2026-06-13T04:00:00Z")
    reservation = ctx["reservation"]
    assert reservation["status"] == "SETTLED"
    txns_before = list_deposit_transactions(reservation["id"])
    assert [(t["txn_type"]) for t in txns_before] == ["HOLD", "RELEASE"]
    res = api.settle_reservation(reservation["id"], _ops())
    validate_error(res, "ERR_INVALID_STATE", expected_status=409)
    txns_after = list_deposit_transactions(reservation["id"])
    assert len(txns_after) == len(txns_before)


def test_risk_score_weighted_sum_after_settle(api):
    """PRD 3.2: "The `risk_score` is a weighted sum, capped at 100: fifteen
    points per settled late return plus twenty-five points per captured damage
    claim."
    PRD 3.7: "when any lateness beyond the grace window occurred, the
    customer's `late_return_count` increments by one — once per reservation, no
    matter how many lines were late."

    One late return (15) + one captured COSMETIC claim (25) -> risk_score
    exactly 40; neither threshold crossed, the customer stays ACTIVE.

    Design: Corner/calculations/risk_score_weighted_sum_after_settle
    """
    ctx = setup_returned_reservation(pickup_clock="2026-06-13T04:01:00Z")
    claim = file_damage_claim(
        ctx["lines"][0]["id"],
        severity="COSMETIC",
        repair_cost_cents=10000,
        description="scuff",
    )
    approve_claim(claim["id"], reviewer_user_id="ops-1")
    _settle(api, ctx["reservation"]["id"])
    customer = get_customer_by_id(ctx["customer"]["id"])
    assert customer["late_return_count"] == 1
    assert customer["captured_damage_count"] == 1
    assert customer["risk_score"] == 40
    assert customer["status"] == "ACTIVE"


def test_deposit_multiplier_applies_at_risk_70(api):
    """PRD 3.4: "The customer's `risk_score` at confirm time selects the
    multiplier: 1.5 when the score is 70 or more, otherwise 1.0. Each line's
    hold is the catalog item's `deposit_amount_cents` times the multiplier,
    rounded half-up per unit, and the reservation's `deposit_hold_cents` is the
    sum of those per-unit holds — rounding each unit first and then summing,
    never the reverse."

    After three captured claims (risk 75 >= 70) the next confirm holds
    round_half_up(15000 x 1.5) = 22500 instead of 15000; 75 < 90 so the
    customer is still ACTIVE.

    Design: Corner/calculations/deposit_multiplier_applies_at_risk_70
    """
    ctx = setup_returned_reservation(
        num_lines=3, pickup_clock="2026-06-13T04:00:00Z"
    )
    customer = ctx["customer"]
    for i, line in enumerate(ctx["lines"]):
        claim = file_damage_claim(
            line["id"],
            severity="COSMETIC",
            repair_cost_cents=10000,
            description=f"d{i}",
        )
        approve_claim(claim["id"], reviewer_user_id="ops-1")
    _settle(api, ctx["reservation"]["id"])
    customer_after = get_customer_by_id(customer["id"])
    assert customer_after["risk_score"] == 75
    assert customer_after["status"] == "ACTIVE"

    catalog2 = create_catalog_item(daily_rate_cents=2000, weight_kg=10.0)
    create_unit(catalog2["id"])
    res2 = create_quoted_reservation(
        customer["id"],
        lines=[{"catalog_item_id": catalog2["id"]}],
        start_date="2026-07-01",
        end_date="2026-07-03",
    )
    confirmed = confirm_reservation(res2["id"], customer["id"])
    assert confirmed["deposit_hold_cents"] == 22500
