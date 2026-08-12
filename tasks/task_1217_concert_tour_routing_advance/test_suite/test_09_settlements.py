"""Settlement workflow: artist share variants, variance grading, state gates,
segregation of duties, and terminal lockdown (PRD §2.10, §3.7).
"""
from test_helpers import (
    api_client, validate_success, validate_error,
    create_staged_tour, create_confirmed_show, create_advanced_show,
    create_performed_show, submit_settlement, verify_settlement, pay_settlement,
    update_tickets_payload, get_show, get_settlement,
    make_promoter_headers, make_settlement_accountant_headers,
    assert_settlement, ApiErrorId, TEST_USERS,
)

TM = TEST_USERS["tour_manager_headers"]
PROMOTER = TEST_USERS["promoter_headers"]
ACCOUNTANT = TEST_USERS["settlement_accountant_headers"]


def _stage_performed_show(api, capacity=500, price=5000, guarantee=1000000,
                          versus=70, tour_name="TSet", market_code="X",
                          show_date="2026-08-01", available_dates=None):
    staged = create_staged_tour(
        start_clock="2026-06-01T00:00:00Z",
        tour_overrides={"tour_name": tour_name},
        market_overrides={"market_code": market_code, "metro_name": market_code},
        venue_overrides={"capacity": capacity,
                         "available_dates": available_dates or [show_date]})
    tid = staged["tour"]["id"]
    show, hold = create_performed_show(
        tid, staged["market"]["id"], staged["venue"]["id"],
        show_date=show_date, on_sale_at="2026-07-01T00:00:00Z",
        avg_ticket_price_cents=price,
        hold_overrides={"guarantee_cents": guarantee, "versus_pct": versus})
    return tid, show, hold


class TestSettlementShareGuaranteeVsVersus:
    def test_guarantee_floor_pays_when_versus_falls_short(self, api):
        """PRD §3.7: "the artist's share is then the **greater** of the
        guarantee and the net multiplied by `versus_pct` hundredths, rounded
        half-up to whole cents. When the percentage-of-net figure falls short
        of the guarantee, the guarantee floor pays; when it meets or exceeds
        the guarantee, the versus deal kicks in."

        Net = 1200000 - 50000 - 30000 - 120000 = 1000000; versus arm
        round(1000000 * 0.70) = 700000 < guarantee 1000000.

        Design: Difficulty/dual_variant_calc/settlement_share_guarantee_vs_versus
        """
        tid, show, _ = _stage_performed_show(api, capacity=500, price=5000,
                                             guarantee=1000000, versus=70,
                                             tour_name="T2A")
        settlement = submit_settlement(
            tid, show["id"], box_office_gross_cents=1200000, taxes_cents=50000,
            facility_fees_cents=30000, promoter_expenses_cents=120000)
        assert_settlement(settlement)
        assert settlement["status"] == "SUBMITTED"
        assert settlement["artist_share_cents"] == 1000000, (
            "guarantee_only arm: max(1000000, round(1000000 * 0.7))")

    def test_versus_kicks_in_when_it_meets_guarantee(self, api):
        """PRD §3.7: "when it meets or exceeds the guarantee, the versus deal
        kicks in."

        Net = 2200000 - 50000 - 30000 - 120000 = 2000000; versus arm
        round(2000000 * 0.70) = 1400000 >= guarantee 1000000.

        Design: Difficulty/dual_variant_calc/settlement_share_guarantee_vs_versus
        """
        tid, show, _ = _stage_performed_show(api, capacity=500, price=5000,
                                             guarantee=1000000, versus=70,
                                             tour_name="T2B")
        settlement = submit_settlement(
            tid, show["id"], box_office_gross_cents=2200000, taxes_cents=50000,
            facility_fees_cents=30000, promoter_expenses_cents=120000)
        assert settlement["artist_share_cents"] == 1400000, (
            "versus_kicks_in arm: max(1000000, round(2000000 * 0.7))")


class TestArtistShareMultiInputMax:
    def test_versus_arm_from_joint_inputs(self, api):
        """PRD §3.7: "the net is the box-office gross minus taxes, minus
        facility fees, minus promoter expenses, floored at zero when expenses
        would drive it negative; the artist's share is then the **greater** of
        the guarantee and the net multiplied by `versus_pct` hundredths,
        rounded half-up to whole cents."

        Net = 3000000 - 200000 - 100000 - 200000 = 2500000; versus arm
        round(2500000 * 0.60) = 1500000 > guarantee 800000.

        Design: Difficulty/combinatorial_formula/artist_share_mode_a_multi_input_max
        """
        tid, show, _ = _stage_performed_show(api, capacity=800, price=5000,
                                             guarantee=800000, versus=60,
                                             tour_name="TC")
        settlement = submit_settlement(
            tid, show["id"], box_office_gross_cents=3000000, taxes_cents=200000,
            facility_fees_cents=100000, promoter_expenses_cents=200000)
        assert settlement["artist_share_cents"] == 1500000

    def test_net_floored_at_zero_so_guarantee_pays(self, api):
        """PRD §3.7: "the net is the box-office gross minus taxes, minus
        facility fees, minus promoter expenses, floored at zero when expenses
        would drive it negative".

        Net = 100000 - 50000 - 30000 - 50000 = -30000, floored to 0; versus arm
        round(0 * 0.60) = 0 < guarantee 800000, so the guarantee floor pays.

        Design: Difficulty/combinatorial_formula/artist_share_mode_a_multi_input_max
        """
        tid, show, _ = _stage_performed_show(api, capacity=800, price=5000,
                                             guarantee=800000, versus=60,
                                             tour_name="TC2")
        settlement = submit_settlement(
            tid, show["id"], box_office_gross_cents=100000, taxes_cents=50000,
            facility_fees_cents=30000, promoter_expenses_cents=50000)
        assert settlement["artist_share_cents"] == 800000


class TestSettlementDependsOnShowPerformed:
    def test_submit_on_advanced_show_rejected(self, api):
        """PRD §3.7: "Submission requires the settlement to be in `DRAFT` and
        the show to be `PERFORMED` (otherwise `ERR_SHOW_NOT_PERFORMED`), and it
        computes two derived quantities."

        Design: Difficulty/cross_entity_state_dependency/settlement_verify_depends_on_show_performed
        """
        staged = create_staged_tour(
            start_clock="2026-06-01T00:00:00Z",
            tour_overrides={"tour_name": "TXD2"},
            market_overrides={"market_code": "POR", "metro_name": "Portland"},
            venue_overrides={"capacity": 1900, "available_dates": ["2026-08-08"]})
        tid = staged["tour"]["id"]
        show, _ = create_advanced_show(
            tid, staged["market"]["id"], staged["venue"]["id"],
            show_date="2026-08-08", on_sale_at="2026-07-01T00:00:00Z",
            avg_ticket_price_cents=7500,
            hold_overrides={"guarantee_cents": 1200000, "versus_pct": 80})
        assert show["status"] == "ADVANCED"

        res = api.submit_settlement(
            tid, show["id"],
            {"box_office_gross_cents": 1500000, "taxes_cents": 100000,
             "facility_fees_cents": 50000, "promoter_expenses_cents": 100000},
            PROMOTER)
        validate_error(res, ApiErrorId.ERR_SHOW_NOT_PERFORMED.value)

    def test_submit_on_confirmed_show_rejected(self, api):
        """PRD §3.7: "Submission requires the settlement to be in `DRAFT` and
        the show to be `PERFORMED` (otherwise `ERR_SHOW_NOT_PERFORMED`), and it
        computes two derived quantities."

        Design: Difficulty/cross_entity_state_dependency/settlement_verify_depends_on_show_performed
        """
        staged = create_staged_tour(
            start_clock="2026-06-01T00:00:00Z",
            tour_overrides={"tour_name": "TXD2b"},
            market_overrides={"market_code": "POR", "metro_name": "Portland"},
            venue_overrides={"capacity": 1900, "available_dates": ["2026-08-08"]})
        tid = staged["tour"]["id"]
        show, _ = create_confirmed_show(
            tid, staged["market"]["id"], staged["venue"]["id"],
            show_date="2026-08-08", on_sale_at="2026-07-01T00:00:00Z",
            avg_ticket_price_cents=7500,
            hold_overrides={"guarantee_cents": 1200000, "versus_pct": 80})
        assert show["status"] == "CONFIRMED"

        res = api.submit_settlement(
            tid, show["id"],
            {"box_office_gross_cents": 1500000, "taxes_cents": 100000,
             "facility_fees_cents": 50000, "promoter_expenses_cents": 100000},
            PROMOTER)
        validate_error(res, ApiErrorId.ERR_SHOW_NOT_PERFORMED.value)


class TestSettlementStateGateOnVerifyAndPay:
    def test_verify_on_draft_settlement_rejected(self, api):
        """PRD §3.7: "a `SettlementAccountant` verifies a `SUBMITTED`
        settlement." PRD §2.10: "Sixth, whether the target entity is in a
        permissible state for the requested transition (`ERR_INVALID_STATE`)."
        and "Only then are the domain rules evaluated: venue availability,
        on-sale lead time, the radius-clause sweep, crew-rest enforcement, hold
        counter limits and expiry, advance-packet completeness, settlement
        variance, the budget cap, segregation of duties, and uniqueness
        constraints." — the state gate is evaluated before any business-fiscal
        rule.

        Design: Difficulty/priority_pair_validation_conflict/state_vs_business_fiscal_on_settle_verify
        """
        tid, show, _ = _stage_performed_show(api, capacity=2000, price=8000,
                                             guarantee=1500000, versus=80,
                                             tour_name="TPrio1",
                                             market_code="DAL",
                                             show_date="2026-08-25")
        # Settlement was spawned in DRAFT by mark-performed; never submitted.
        settlement = get_settlement(tid, show["id"])
        assert settlement["status"] == "DRAFT"

        res = api.verify_settlement(tid, show["id"], ACCOUNTANT)
        validate_error(res, ApiErrorId.ERR_INVALID_STATE.value)

    def test_pay_on_submitted_settlement_rejected(self, api):
        """PRD §3.7: "Third, once `VERIFIED`, an accountant pays the
        settlement, moving it to the terminal `PAID`." A `SUBMITTED` settlement
        is not in a permissible state for payment (PRD §2.10 sixth check,
        `ERR_INVALID_STATE`).

        Design: Difficulty/priority_pair_validation_conflict/state_vs_business_fiscal_on_settle_verify
        """
        tid, show, _ = _stage_performed_show(api, capacity=100, price=5000,
                                             guarantee=100000, versus=70,
                                             tour_name="TPrio1b",
                                             market_code="DAL2")
        validate_success(
            api.update_show_tickets(tid, show["id"],
                                    update_tickets_payload(100), PROMOTER), 200)
        settlement = submit_settlement(tid, show["id"], box_office_gross_cents=500000,
                                       taxes_cents=30000, facility_fees_cents=20000,
                                       promoter_expenses_cents=50000)
        assert settlement["status"] == "SUBMITTED"

        res = api.pay_settlement(tid, show["id"], ACCOUNTANT)
        validate_error(res, ApiErrorId.ERR_INVALID_STATE.value)


class TestVarianceFlagBoundary:
    def test_exactly_50000_variance_is_minor(self, api):
        """PRD §3.7: "The `variance_flag` grades the absolute difference —
        `MATERIAL` at 500,000 cents or more, `MINOR` at 50,000 cents or more
        but below the material line, and `NONE` below that. Both boundaries are
        inclusive: exactly 50,000 cents is `MINOR`, exactly 500,000 cents is
        `MATERIAL`."

        tickets 100 * price 10000 = 1000000 expected; gross 1050000 ->
        variance +50000 -> MINOR.

        Design: Corner/calculations/variance_flag_at_exactly_threshold
        """
        tid, show, _ = _stage_performed_show(api, capacity=100, price=10000,
                                             guarantee=100000, versus=70,
                                             tour_name="TVar1")
        validate_success(
            api.update_show_tickets(tid, show["id"],
                                    update_tickets_payload(100), PROMOTER), 200)
        settlement = submit_settlement(
            tid, show["id"], box_office_gross_cents=1050000, taxes_cents=0,
            facility_fees_cents=0, promoter_expenses_cents=0)
        assert settlement["variance_cents"] == 50000
        assert settlement["variance_flag"] == "MINOR", (
            "at exactly VARIANCE_THRESHOLD_CENTS the flag is MINOR (>=, not >)")

    def test_49999_variance_is_none(self, api):
        """PRD §3.7: "`NONE` below that. Both boundaries are inclusive".

        tickets 100 * price 10000 = 1000000 expected; gross 1049999 ->
        variance +49999 -> NONE, one cent below the threshold.

        Design: Corner/calculations/variance_flag_at_exactly_threshold
        """
        tid, show, _ = _stage_performed_show(api, capacity=100, price=10000,
                                             guarantee=100000, versus=70,
                                             tour_name="TVar2")
        validate_success(
            api.update_show_tickets(tid, show["id"],
                                    update_tickets_payload(100), PROMOTER), 200)
        settlement = submit_settlement(
            tid, show["id"], box_office_gross_cents=1049999, taxes_cents=0,
            facility_fees_cents=0, promoter_expenses_cents=0)
        assert settlement["variance_cents"] == 49999
        assert settlement["variance_flag"] == "NONE"


class TestSegregationOfDuties:
    def test_verifier_must_differ_from_submitter(self, api):
        """PRD §3.7: "segregation of duties is enforced by identity: the
        verifying accountant's `X-User-ID` must differ from the submitting
        promoter's `X-User-ID`, or the verification is rejected with
        `ERR_SEGREGATION_OF_DUTIES` (HTTP 403)."

        Design: Corner/validations/segregation_of_duties_settlement_verify
        """
        tid, show, _ = _stage_performed_show(api, capacity=100, price=5000,
                                             guarantee=100000, versus=70,
                                             tour_name="TSoD")
        validate_success(
            api.update_show_tickets(tid, show["id"],
                                    update_tickets_payload(100), PROMOTER), 200)
        # Submit as Promoter user_42 (variance 0 -> NONE, so only the
        # segregation guard can fire at verify).
        submit_settlement(tid, show["id"],
                          promoter_headers=make_promoter_headers("user_42"),
                          box_office_gross_cents=500000, taxes_cents=30000,
                          facility_fees_cents=20000, promoter_expenses_cents=50000)
        res = api.verify_settlement(
            tid, show["id"], make_settlement_accountant_headers("user_42"))
        validate_error(res, ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value)

    def test_distinct_verifier_succeeds(self, api):
        """PRD §3.7: "the verifying accountant's `X-User-ID` must differ from
        the submitting promoter's `X-User-ID`, or the verification is rejected
        with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403)."

        Design: Corner/validations/segregation_of_duties_settlement_verify
        """
        tid, show, _ = _stage_performed_show(api, capacity=100, price=5000,
                                             guarantee=100000, versus=70,
                                             tour_name="TSoD2")
        validate_success(
            api.update_show_tickets(tid, show["id"],
                                    update_tickets_payload(100), PROMOTER), 200)
        submit_settlement(tid, show["id"],
                          promoter_headers=make_promoter_headers("user_42"),
                          box_office_gross_cents=500000, taxes_cents=30000,
                          facility_fees_cents=20000, promoter_expenses_cents=50000)
        verified = verify_settlement(
            tid, show["id"],
            accountant_headers=make_settlement_accountant_headers("user_99"))
        assert verified["status"] == "VERIFIED"


class TestSettlementRbac:
    def test_promoter_cannot_pay_settlement(self, api):
        """PRD §2.1: "A `SettlementAccountant` verifies and pays settlements" —
        payment is exclusive to the accountant, and "An attempt to perform an
        operation outside the caller's role is rejected with
        `ERR_INSUFFICIENT_PERMISSIONS` (HTTP 403)."

        Design: Corner/rbac/rbac_accountant_cannot_pay_own_submitted_settlement
        """
        tid, show, _ = _stage_performed_show(api, capacity=100, price=5000,
                                             guarantee=100000, versus=70,
                                             tour_name="TPay")
        submit_settlement(tid, show["id"], box_office_gross_cents=500000,
                          taxes_cents=30000, facility_fees_cents=20000,
                          promoter_expenses_cents=50000)
        res = api.pay_settlement(tid, show["id"], PROMOTER)
        validate_error(res, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS.value)


class TestSettlementPaidTerminalLockdown:
    def test_paid_settlement_has_no_outgoing_transitions(self, api):
        """PRD §3.7: "Payment cascades: the show moves from `PERFORMED` to
        `SETTLED`, the tour's settled totals absorb the show's settled gross
        and cost, and the forward projections recompute without it." `PAID` is
        terminal, so PRD §2.10's sixth check rejects any further transition
        with `ERR_INVALID_STATE`.

        Design: Corner/state_machines/terminal_state_settlement_paid_lockdown
        """
        tid, show, _ = _stage_performed_show(api, capacity=100, price=5000,
                                             guarantee=100000, versus=70,
                                             tour_name="TLock")
        validate_success(
            api.update_show_tickets(tid, show["id"],
                                    update_tickets_payload(100), PROMOTER), 200)
        submit_settlement(tid, show["id"], box_office_gross_cents=500000,
                          taxes_cents=30000, facility_fees_cents=20000,
                          promoter_expenses_cents=50000)
        verify_settlement(tid, show["id"])
        paid = pay_settlement(tid, show["id"])
        assert_settlement(paid)
        assert paid["status"] == "PAID"
        assert get_show(tid, show["id"])["status"] == "SETTLED"

        res = api.verify_settlement(tid, show["id"], ACCOUNTANT)
        validate_error(res, ApiErrorId.ERR_INVALID_STATE.value)
        res = api.pay_settlement(tid, show["id"], ACCOUNTANT)
        validate_error(res, ApiErrorId.ERR_INVALID_STATE.value)
