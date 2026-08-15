"""Bed-night billing variants, tiers, surcharges, premiums, and confirm gates."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    add_participant,
    clear_screening,
    create_building_released,
    create_building_turn_active,
    create_group,
    create_group_with_revision,
    create_revision_payload,
    get_assignment_for_participant,
    get_group,
    get_success_data,
    make_coordinator_headers,
    set_clock,
    setup_confirmed_group,
    submit_group,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["admin_headers"]
FINANCE = TEST_USERS["finance_headers"]


def _finalize(api, invoice_id):
    return get_success_data(api.finalize_invoice(invoice_id, FINANCE))


class TestProvisionalVsFinalBedNightBilling:
    def _scenario(self, api):
        """CONFIRMED group with 3 assignments, then one no-show and one early
        checkout; group closed out DEPARTED. Returns (group, invoice_id)."""
        building, rooms = create_building_turn_active(name="Baker Hall",
                                                      key_pool_size=10,
                                                      rooms=(("R1", 2), ("R2", 1)))
        group, participants, _rev, invoice_id = setup_confirmed_group(
            building, rooms, client_name="Chess Camp",
            participant_specs=[("P One", "1990-01-01", "ATTENDEE"),
                               ("P Two", "1990-01-02", "ATTENDEE"),
                               ("P Three", "1990-01-03", "ATTENDEE")],
            assignment_room_map=["R1", "R1", "R2"],
            arrival_date="2026-06-15", departure_date="2026-06-19",
            checkin_at="2026-06-15T15:00:00Z", checkout_at="2026-06-19T11:00:00Z",
            contracted_bed_count=3, deposit_paid_cents=20000)
        p1, p2, p3 = participants
        a1 = get_assignment_for_participant(group["id"], p1["id"])
        a2 = get_assignment_for_participant(group["id"], p2["id"])
        a3 = get_assignment_for_participant(group["id"], p3["id"])
        set_clock("2026-06-15T15:30:00Z")
        get_success_data(api.check_in_assignment(a1["id"], ADMIN))
        get_success_data(api.check_in_assignment(a2["id"], ADMIN))
        set_clock("2026-06-16T16:00:00Z")
        get_success_data(api.mark_no_show(a3["id"], ADMIN))
        set_clock("2026-06-18T09:00:00Z")
        get_success_data(api.check_out_assignment(a1["id"], ADMIN))  # 3 actual nights
        set_clock("2026-06-19T10:00:00Z")
        get_success_data(api.check_out_assignment(a2["id"], ADMIN))  # 4 actual nights
        get_success_data(api.close_out_group(group["id"], ADMIN))
        return get_group(group["id"]), invoice_id

    def test_provisional_total_computed_from_planned_nights(self, api):
        """PRD: "The provisional variant, computed at confirmation and recomputed
        whenever a revision supersedes while the group is CONFIRMED, includes the
        assignments of the ACTIVE revision in RESERVED or CHECKED_IN status and
        counts each assignment's planned nights: every calendar date from the
        check-in date up to but not including the checkout date."

        Design: Difficulty/dual_variant_calc/provisional_vs_final_bed_night_billing
        """
        building, rooms = create_building_turn_active(name="Baker Hall",
                                                      key_pool_size=10,
                                                      rooms=(("R1", 2), ("R2", 1)))
        group, participants, _rev, invoice_id = setup_confirmed_group(
            building, rooms, client_name="Chess Camp",
            participant_specs=[("P One", "1990-01-01", "ATTENDEE"),
                               ("P Two", "1990-01-02", "ATTENDEE"),
                               ("P Three", "1990-01-03", "ATTENDEE")],
            assignment_room_map=["R1", "R1", "R2"],
            arrival_date="2026-06-15", departure_date="2026-06-19",
            checkin_at="2026-06-15T15:00:00Z", checkout_at="2026-06-19T11:00:00Z",
            contracted_bed_count=3, deposit_paid_cents=20000)
        invoice = get_success_data(api.get_invoice(invoice_id, FINANCE))
        assert invoice["status"] == "PROVISIONAL"
        assert invoice["provisional_bed_night_subtotal_cents"] == 54000, \
            "12 planned bed-nights at the 4500 base rate (Mon-Thu, no weekend)"
        assert invoice["provisional_total_cents"] == 54000, \
            "the bed-night subtotal is the provisional invoice's only component"
        assert invoice["total_cents"] is None, "final fields stay null until finalize"

    def test_final_variant_prices_reality_not_plans(self, api):
        """PRD: "Assignments that reached CHECKED_OUT bill their actual nights —
        the calendar dates from the actual_checkin_at date up to but not
        including the actual_checkout_at date — under the same tier, surcharge,
        and weekend rules. A NO_SHOW assignment bills exactly one flat night at
        the 4,500-cent base rate with no surcharge, no weekend premium, and no
        tier adjustment. CANCELLED assignments are excluded entirely."

        Design: Difficulty/dual_variant_calc/provisional_vs_final_bed_night_billing
        """
        group, invoice_id = self._scenario(api)
        assert group["status"] == "DEPARTED"
        invoice = _finalize(api, invoice_id)
        assert invoice["status"] == "FINALIZED"
        assert invoice["provisional_total_cents"] == 54000
        assert invoice["final_bed_night_subtotal_cents"] == 36000, (
            "P1 3 actual nights * 4500 = 13500; P2 4 actual nights * 4500 = 18000; "
            "P3 NO_SHOW flat 4500")
        assert invoice["provisional_total_cents"] != invoice["final_bed_night_subtotal_cents"], \
            "early checkout and the no-show make the variants diverge on identical contracts"
        assert invoice["total_cents"] == 36000, "no linen/key/damage charges in play"
        assert invoice["balance_due_cents"] == 16000, "36000 total minus 20000 deposit"


class TestTieredMinorWeekendPricing:
    def _minor_weekend_group(self, api):
        building, rooms = create_building_turn_active(name="Drew Hall",
                                                      key_pool_size=10,
                                                      rooms=(("R1", 2),))
        group, participants, _rev = create_group_with_revision(
            building["id"], rooms, client_name="Youth Orchestra",
            participant_specs=[("Chap One", "1985-03-03", "CHAPERONE"),
                               ("Kid One", "2012-04-04", "ATTENDEE")],
            assignment_room_map=["R1", "R1"],
            arrival_date="2026-06-26", departure_date="2026-06-29",
            checkin_at="2026-06-26T15:00:00Z", checkout_at="2026-06-29T11:00:00Z",
            contracted_bed_count=2, deposit_paid_cents=10000,
            has_minor_participants=True)
        clear_screening(participants[0]["id"], group["id"], "CONS-1")
        submit_group(group["id"])
        return group

    def test_tiered_minor_weekend_bed_night_pricing(self, api):
        """PRD: "If the group's has_minor_participants is true, each night's tier
        rate is increased by a fifteen percent surcharge, rounded half-up to the
        cent per night, before any weekend adjustment. Finally, each night
        falling on a Friday or a Saturday adds a weekend premium of 400 cents,
        applied after the surcharge rounding."

        Design: Difficulty/combinatorial_formula/tiered_minor_weekend_bed_night_pricing
        """
        group = self._minor_weekend_group(api)
        confirmed = validate_success(api.confirm_group(group["id"], ADMIN))
        assert confirmed["status"] == "CONFIRMED"
        invoice = get_success_data(
            api.get_invoice(confirmed["provisional_invoice_id"], FINANCE))
        assert invoice["provisional_bed_night_subtotal_cents"] == 32650, (
            "per-night minor rate round_half_up(4500*1.15)=5175; Fri 2026-06-26 and "
            "Sat 2026-06-27 nights add 400 -> 5575 each; Sun night 5175; per "
            "assignment 16325, two assignments 32650")

    def test_minor_surcharge_rounds_per_night_before_premium(self, api):
        """PRD: "each night's tier rate is increased by a fifteen percent
        surcharge, rounded half-up to the cent per night, before any weekend
        adjustment."
        PRD §2.9: "per night for bed-night billing (before nights are summed)".

        Design: Difficulty/combinatorial_formula/tiered_minor_weekend_bed_night_pricing
        """
        # A single Sunday-night minor stay isolates the per-night rounding from
        # the weekend premium: round_half_up(4500 * 1.15) = 5175 exactly.
        building, rooms = create_building_turn_active(name="Drew Hall",
                                                      key_pool_size=10,
                                                      rooms=(("R1", 2),))
        group, participants, _rev = create_group_with_revision(
            building["id"], rooms, client_name="Youth Orchestra",
            participant_specs=[("Chap One", "1985-03-03", "CHAPERONE"),
                               ("Kid One", "2012-04-04", "ATTENDEE")],
            assignment_room_map=["R1", "R1"],
            arrival_date="2026-06-28", departure_date="2026-06-29",
            checkin_at="2026-06-28T15:00:00Z", checkout_at="2026-06-29T11:00:00Z",
            contracted_bed_count=2, deposit_paid_cents=6000,
            has_minor_participants=True)
        clear_screening(participants[0]["id"], group["id"], "CONS-1")
        submit_group(group["id"])
        confirmed = validate_success(api.confirm_group(group["id"], ADMIN))
        invoice = get_success_data(
            api.get_invoice(confirmed["provisional_invoice_id"], FINANCE))
        # 2 assignments * 1 Sunday night * 5175 = 10350; no weekend premium.
        assert invoice["provisional_bed_night_subtotal_cents"] == 10350


class TestBedNightTierBoundary:
    def _tier_groups(self, api):
        building, rooms = create_building_turn_active(
            name="Mason Hall", key_pool_size=20,
            rooms=(("R3", 3), ("R4", 3), ("R5", 3), ("R6", 3)))
        specs5 = [("G5 P%d" % i, "1990-01-0%d" % i, "ATTENDEE") for i in range(1, 6)]
        g5, _p, _r, inv5 = setup_confirmed_group(
            building, rooms, client_name="G5 Camp", participant_specs=specs5,
            assignment_room_map=["R3", "R3", "R3", "R4", "R4"],
            arrival_date="2026-06-15", departure_date="2026-07-05",
            checkin_at="2026-06-15T15:00:00Z", checkout_at="2026-07-05T11:00:00Z",
            contracted_bed_count=5, deposit_paid_cents=120000)
        specs6 = [("G6 P%d" % i, "1990-02-0%d" % i, "ATTENDEE") for i in range(1, 7)]
        g6, _p, _r, inv6 = setup_confirmed_group(
            building, rooms, client_name="G6 Camp", participant_specs=specs6,
            assignment_room_map=["R4", "R5", "R5", "R5", "R6", "R6"],
            arrival_date="2026-06-15", departure_date="2026-07-05",
            checkin_at="2026-06-15T15:00:00Z", checkout_at="2026-07-05T11:00:00Z",
            contracted_bed_count=6, deposit_paid_cents=140000)
        return inv5, inv6

    def test_exactly_100_bed_nights_all_base_rate(self, api):
        """PRD: "nights up to and including the one-hundredth bed-night bill at
        the base rate of 4,500 cents, and every night beyond the hundredth bills
        at the tier-two rate of 3,900 cents — only the nights past the threshold
        receive the lower rate."

        Design: Difficulty/boundary_precision_check/bed_night_tier_boundary_100_vs_beyond
        """
        inv5, _inv6 = self._tier_groups(api)
        invoice = get_success_data(api.get_invoice(inv5, FINANCE))
        # 100 bed-nights: 100 * 4500 + 5 assignments * 6 Fri/Sat nights * 400.
        assert invoice["provisional_bed_night_subtotal_cents"] == 462000

    def test_120_bed_nights_price_marginally_beyond_100(self, api):
        """PRD: "All included nights across the whole group are then ordered by
        check-in date ascending, ties broken by the participant's created_at
        ascending, and priced marginally by cumulative position"

        Design: Difficulty/boundary_precision_check/bed_night_tier_boundary_100_vs_beyond
        """
        inv5, inv6 = self._tier_groups(api)
        invoice5 = get_success_data(api.get_invoice(inv5, FINANCE))
        invoice6 = get_success_data(api.get_invoice(inv6, FINANCE))
        assert invoice6["provisional_bed_night_subtotal_cents"] == 542400, (
            "120 bed-nights: 100*4500 + 20*3900 marginal + 6 assignments * 6 "
            "weekend nights * 400")
        # Marginal-tier proof: strip the weekend premiums from both subtotals;
        # the difference is exactly 20 nights at the 3900 tier-two rate.
        base5 = invoice5["provisional_bed_night_subtotal_cents"] - 5 * 6 * 400
        base6 = invoice6["provisional_bed_night_subtotal_cents"] - 6 * 6 * 400
        assert base6 - base5 == 20 * 3900


class TestWeekendAndNoShowLegs:
    def test_weekend_premium_friday_saturday_only(self, api):
        """PRD: "each night falling on a Friday or a Saturday adds a weekend
        premium of 400 cents, applied after the surcharge rounding. The subtotal
        is the plain integer sum of these per-night amounts."

        Design: Corner/calculations/weekend_premium_friday_saturday_only
        """
        building, rooms = create_building_turn_active(name="Lord Hall",
                                                      key_pool_size=5,
                                                      rooms=(("R1", 1),))
        group, participants, _rev = create_group_with_revision(
            building["id"], rooms, client_name="Sunday Stay",
            arrival_date="2026-06-28", departure_date="2026-06-29",
            checkin_at="2026-06-28T15:00:00Z", checkout_at="2026-06-29T11:00:00Z",
            deposit_paid_cents=2000)
        submit_group(group["id"])
        confirmed = validate_success(api.confirm_group(group["id"], ADMIN))
        invoice = get_success_data(
            api.get_invoice(confirmed["provisional_invoice_id"], FINANCE))
        assert invoice["provisional_bed_night_subtotal_cents"] == 4500, \
            "a Sunday night carries no weekend premium, surcharge, or tier shift"

    def test_no_show_flat_night_excludes_surcharge_and_premium(self, api):
        """PRD: "A NO_SHOW assignment bills exactly one flat night at the
        4,500-cent base rate with no surcharge, no weekend premium, and no tier
        adjustment."

        Design: Corner/calculations/no_show_flat_night_excludes_surcharge_and_premium
        """
        building, rooms = create_building_turn_active(name="Mann Hall",
                                                      key_pool_size=5,
                                                      rooms=(("R1", 2),))
        group, participants, _rev, invoice_id = setup_confirmed_group(
            building, rooms, client_name="No Show Minors",
            participant_specs=[("Chap One", "1985-03-03", "CHAPERONE"),
                               ("Kid One", "2012-04-04", "ATTENDEE")],
            assignment_room_map=["R1", "R1"],
            arrival_date="2026-06-26", departure_date="2026-06-29",
            checkin_at="2026-06-26T15:00:00Z", checkout_at="2026-06-29T11:00:00Z",
            contracted_bed_count=2, deposit_paid_cents=11000,
            has_minor_participants=True)
        chaperone, kid = participants
        a_chap = get_assignment_for_participant(group["id"], chaperone["id"])
        a_kid = get_assignment_for_participant(group["id"], kid["id"])
        set_clock("2026-06-26T16:00:00Z")
        get_success_data(api.check_in_assignment(a_chap["id"], ADMIN))
        set_clock("2026-06-28T16:00:00Z")  # > 24h past the kid's checkin_at
        get_success_data(api.mark_no_show(a_kid["id"], ADMIN))
        set_clock("2026-06-29T10:00:00Z")
        get_success_data(api.check_out_assignment(a_chap["id"], ADMIN))
        get_success_data(api.close_out_group(group["id"], ADMIN))
        invoice = _finalize(api, invoice_id)
        assert invoice["final_bed_night_subtotal_cents"] == 20825, (
            "chaperone actual nights Fri/Sat/Sun: 5575 + 5575 + 5175 = 16325; "
            "the minor's NO_SHOW leg is a flat 4500 — no 15% surcharge, no premium")


class TestProvisionalRecomputeOnSupersede:
    def test_cascading_provisional_recompute_on_supersede(self, api):
        """PRD: "The provisional variant, computed at confirmation and recomputed
        whenever a revision supersedes while the group is CONFIRMED"
        PRD: "If the group is already CONFIRMED when a revision is created, the
        provisional invoice's bed-night subtotal is recomputed"

        Design: Corner/cross_cutting_layers/cascading_provisional_recompute_on_supersede
        """
        building, rooms = create_building_turn_active(name="Whiskey Hall",
                                                      key_pool_size=5,
                                                      rooms=(("R1", 1),))
        group, participants, _rev, invoice_id = setup_confirmed_group(
            building, rooms, client_name="Shrink Stay",
            arrival_date="2026-06-15", departure_date="2026-06-19",
            checkin_at="2026-06-15T15:00:00Z", checkout_at="2026-06-19T11:00:00Z")
        invoice = get_success_data(api.get_invoice(invoice_id, FINANCE))
        assert invoice["provisional_total_cents"] == 18000, "4 planned nights * 4500"

        version = get_group(group["id"])["version"]
        get_success_data(api.create_rooming_list_revision(
            group["id"],
            create_revision_payload(version, [{
                "participant_id": participants[0]["id"],
                "room_id": rooms["R1"]["id"],
                "checkin_at": "2026-06-15T15:00:00Z",
                "checkout_at": "2026-06-17T11:00:00Z",
            }]),
            make_coordinator_headers(group["id"])))
        invoice_after = get_success_data(api.get_invoice(invoice_id, FINANCE))
        assert invoice_after["provisional_total_cents"] == 9000, \
            "2 planned nights * 4500 — recomputed on supersede with no finalize call"
        building_after = get_success_data(api.get_building(building["id"], ADMIN))
        assert building_after["reserved_bed_count"] == 1, \
            "the old assignment cancelled and the new one reserved"


class TestPaymentExactness:
    def test_payment_amount_must_equal_balance(self, api):
        """PRD: "Recording a payment is legal only on a FINALIZED invoice — an
        attempt against an invoice already PAID (or one VOID) is rejected with
        ERR_INVOICE_ALREADY_PAID — and the tendered amount_cents must equal
        balance_due_cents exactly, else ERR_PAYMENT_AMOUNT_MISMATCH."

        Design: Corner/validations/payment_amount_must_equal_balance
        """
        from test_helpers import setup_finalized_invoice
        building, rooms = create_building_turn_active(name="Zeta Hall",
                                                      key_pool_size=5,
                                                      rooms=(("R1", 1),))
        group, _assignments, invoice = setup_finalized_invoice(
            building, rooms, client_name="Pay Exact", deposit_paid_cents=5000)
        assert invoice["total_cents"] == 9000, "2 actual nights * 4500"
        assert invoice["balance_due_cents"] == 4000, "9000 total minus 5000 deposit"

        resp = api.record_payment(invoice["id"], 3999, FINANCE)
        validate_error(resp, ApiErrorId.ERR_PAYMENT_AMOUNT_MISMATCH)
        still_open = get_success_data(api.get_invoice(invoice["id"], FINANCE))
        assert still_open["status"] == "FINALIZED"

        paid = validate_success(api.record_payment(invoice["id"], 4000, FINANCE))
        assert paid["status"] == "PAID"
        assert get_group(group["id"])["status"] == "CLOSED", \
            "payment bubbles the DEPARTED group to CLOSED"
        validate_error(api.record_payment(invoice["id"], 4000, FINANCE),
                       ApiErrorId.ERR_INVOICE_ALREADY_PAID)


class TestConfirmGates:
    def test_confirm_without_rooming_list_rejected(self, api):
        """PRD: "then the rooming-list gates — an ACTIVE revision with at least
        one assignment must exist (else ERR_ROOMING_LIST_REQUIRED) and its
        assignment count must equal the group's contracted_bed_count (else
        ERR_CONTRACTED_BED_MISMATCH)"

        Design: Corner/validations/confirm_without_rooming_list_rejected
        """
        building, rooms = create_building_turn_active(name="Gamma Hall",
                                                      key_pool_size=5,
                                                      rooms=(("R1", 2),))
        ga = create_group(building["id"], client_name="No List",
                          deposit_paid_cents=5000)
        add_participant(ga["id"])
        submit_group(ga["id"])
        resp = api.confirm_group(ga["id"], ADMIN)
        validate_error(resp, ApiErrorId.ERR_ROOMING_LIST_REQUIRED)

        gb, participants, _rev = create_group_with_revision(
            building["id"], rooms, client_name="Short List",
            contracted_bed_count=2, deposit_paid_cents=5000)
        submit_group(gb["id"])
        resp2 = api.confirm_group(gb["id"], ADMIN)
        validate_error(resp2, ApiErrorId.ERR_CONTRACTED_BED_MISMATCH)

    def test_confirm_when_building_not_turn_active(self, api):
        """PRD: "the host building must be TURN_ACTIVE (else
        ERR_BUILDING_NOT_RELEASED)"
        PRD §3.1: "Once the building is RELEASED, beginning the turn season moves
        it to TURN_ACTIVE — the only building state in which conference groups
        can be confirmed and guests checked in"

        Design: Corner/validations/confirm_when_building_not_turn_active
        """
        building, rooms = create_building_released(name="India Hall", key_pool_size=5,
                                                   rooms=(("R1", 1),))
        group, participants, _rev = create_group_with_revision(
            building["id"], rooms, client_name="Too Early",
            deposit_paid_cents=5000)
        submit_group(group["id"])
        resp = api.confirm_group(group["id"], ADMIN)
        validate_error(resp, ApiErrorId.ERR_BUILDING_NOT_RELEASED)
        get_success_data(api.begin_turn_season(building["id"],
                                               TEST_USERS["facilities_headers"]))
        confirmed = validate_success(api.confirm_group(group["id"], ADMIN))
        assert confirmed["status"] == "CONFIRMED"

    def test_deposit_shortfall_alone_rejected(self, api):
        """PRD: "the deposit must cover at least one quarter of the provisional
        bed-night estimate, evaluated integer-exact as deposit_paid_cents
        multiplied by four being at least the estimate in cents (else
        ERR_DEPOSIT_INSUFFICIENT)."
        PRD: "each deposit call carries amount_cents, which is added to the
        group's deposit_paid_cents"

        Design: Corner/validations/deposit_shortfall_alone_rejected
        """
        building, rooms = create_building_turn_active(name="Golf Hall",
                                                      key_pool_size=5,
                                                      rooms=(("R1", 1),))
        group, participants, _rev = create_group_with_revision(
            building["id"], rooms, client_name="Short Deposit",
            deposit_paid_cents=1000)
        submit_group(group["id"])
        resp = api.confirm_group(group["id"], ADMIN)
        validate_error(resp, ApiErrorId.ERR_DEPOSIT_INSUFFICIENT)
        get_success_data(api.record_deposit(group["id"], 2000, FINANCE))
        confirmed = validate_success(api.confirm_group(group["id"], ADMIN))
        assert confirmed["status"] == "CONFIRMED"
