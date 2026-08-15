"""Single-event rentals: pricing formula, coverage availability, hold window, fees."""
from test_helpers import (
    ADMIN, FIN, REP,
    ApiClient, ApiErrorId, EVENT_E1, EVENT_E2, EVENT_E5,
    get_single_invoice, list_invoice_rows,
    make_account_holder_headers, make_active_account, make_event, make_executed_agreement,
    make_issued_invoice,
    make_rental, make_season, make_suite, make_venue, pay_invoice_in_full, set_clock,
    setup_confirmed_rental, transition_rental,
    validate_error, validate_success,
)

GOLD_SUITE = dict(suite_code="G-101", tier="GOLD", capacity_seats=20,
                  base_annual_fee_cents=12000000, f_b_minimum_cents=4000000)
SILVER_SUITE = dict(suite_code="S-009", tier="SILVER", capacity_seats=10,
                    base_annual_fee_cents=6000000, f_b_minimum_cents=2000000)


class TestRentalQuoteInteraction:
    def _setup(self, api: ApiClient):
        set_clock("2026-08-01T00:00:00Z")
        venue = make_venue()
        suite = make_suite(venue["id"], **GOLD_SUITE)
        season = make_season(venue["id"])
        event = make_event(season["id"], **EVENT_E5)
        account = make_active_account()
        return venue, suite, event, account

    def test_playoff_quote_with_overage(self, api: ApiClient):
        """PRD §3.8: "The event's `rental_base_price_cents` is multiplied by the
        suite's tier multiplier — 1.60 for `FOUNDERS`, 1.30 for `PLATINUM`, 1.00 for
        `GOLD`, and 0.80 for `SILVER` — then a per-guest overage of 1,500 cents is
        added for every guest beyond the suite's `capacity_seats` ... If the event is
        a `PLAYOFF`, that intermediate sum is then multiplied by 1.25 ... The
        `quoted_price_cents` is that final product, rounded half-up in a single
        rounding at the end, and the `deposit_cents` is computed separately as thirty
        percent of the quoted price, rounded half-up."
        Design: Difficulty/combinatorial_formula/rental_quote_tier_overage_playoff_interaction
        """
        _, suite, event, account = self._setup(api)
        rental = validate_success(api.create_rental(
            {"event_id": event["id"], "suite_id": suite["id"],
             "account_id": account["id"], "guest_count": 24}, REP), expected_status=201)
        # (1200000 * 1.00 + 4 * 1500) * 1.25 = 1507500; deposit round_half_up(30%).
        assert rental["quoted_price_cents"] == 1507500
        assert rental["deposit_cents"] == 452250

    def test_overage_is_multiplied_by_playoff_surcharge(self, api: ApiClient):
        """PRD §3.8: "then a per-guest overage of 1,500 cents is added for every guest
        beyond the suite's `capacity_seats`, with no overage when the party fits within
        capacity. If the event is a `PLAYOFF`, that intermediate sum is then multiplied
        by 1.25".
        Design: Difficulty/combinatorial_formula/rental_quote_tier_overage_playoff_interaction
        """
        _, suite, event, account = self._setup(api)
        over = validate_success(api.create_rental(
            {"event_id": event["id"], "suite_id": suite["id"],
             "account_id": account["id"], "guest_count": 24}, REP), expected_status=201)
        fit = validate_success(api.create_rental(
            {"event_id": event["id"], "suite_id": suite["id"],
             "account_id": account["id"], "guest_count": 20}, REP), expected_status=201)
        assert fit["quoted_price_cents"] == 1500000, "no overage within capacity"
        assert fit["deposit_cents"] == 450000
        assert over["quoted_price_cents"] - fit["quoted_price_cents"] == 7500, (
            "the 6000 overage amplified by 1.25 proves multiplicative interaction")


class TestLicenseCoverageAvailability:
    def _setup(self, api: ApiClient):
        """GOLD suite with one REGULAR and one PLAYOFF event in its season; a QUOTED
        rental on the REGULAR event taken while the suite is still free (PRD §3.8 runs
        the same availability check at quote creation, so the quote must predate the
        license); then an ACTIVE agreement executed over the season."""
        set_clock("2026-08-01T00:00:00Z")
        venue = make_venue()
        suite = make_suite(venue["id"], **GOLD_SUITE)
        season = make_season(venue["id"])
        e1 = make_event(season["id"], **EVENT_E1)
        e5 = make_event(season["id"], **EVENT_E5)
        holder = make_active_account()
        renter = make_active_account()
        regular_quote = make_rental(e1["id"], suite["id"], renter["id"])
        make_executed_agreement(suite, holder, season)
        return suite, e1, e5, renter, regular_quote

    def test_hold_on_license_covered_regular_event_rejected(self, api: ApiClient):
        """PRD §3.8: "The suite must be free for that event: no other rental on the
        same suite and event may sit in `HELD` or `CONFIRMED`; for `REGULAR` and
        `RIVALRY` events the suite must additionally be free of any agreement in
        `ACTIVE`, `SUSPENDED`, or `EXPIRING` covering the event's season ... any of
        these is `ERR_SUITE_NOT_AVAILABLE`."
        Design: Difficulty/resource_temporal_overlap/rental_blocked_by_license_coverage_only_for_covered_event_types
        """
        suite, _e1, _e5, _renter, regular_quote = self._setup(api)
        resp = api.set_rental_status(regular_quote["id"], {"target_status": "HELD"}, REP)
        validate_error(resp, ApiErrorId.ERR_SUITE_NOT_AVAILABLE)
        assert validate_success(api.get_rental(regular_quote["id"], REP))["status"] == "QUOTED"

    def test_hold_on_playoff_event_succeeds_and_stamps_expiry(self, api: ApiClient):
        """PRD §3.8: "`REGULAR` and `RIVALRY` events are covered by season-long license
        agreements, while `PLAYOFF` and `CONCERT` events are not" (§3.1); "A successful
        hold stamps `hold_expires_at` — null until the rental first enters `HELD` — at
        exactly forty-eight hours after the clock."
        Design: Difficulty/resource_temporal_overlap/rental_blocked_by_license_coverage_only_for_covered_event_types
        """
        suite, _e1, e5, renter, _quote = self._setup(api)
        set_clock("2026-12-20T12:00:00Z")
        rental = make_rental(e5["id"], suite["id"], renter["id"])
        held = validate_success(api.set_rental_status(
            rental["id"], {"target_status": "HELD"}, REP))
        assert held["status"] == "HELD"
        assert held["hold_expires_at"] is not None
        assert held["hold_expires_at"].startswith("2026-12-22T12:00:00"), (
            f"clock + 48h expected, got {held['hold_expires_at']}")


class TestHoldTimingGuards:
    def test_rental_hold_expiry_and_expire_guard(self, api: ApiClient):
        """PRD §3.8: "The hold must still be live — the clock at or before
        `hold_expires_at`, else `ERR_HOLD_EXPIRED`" and "a `StadiumAdmin` may move
        `HELD` to `EXPIRED` once the clock is strictly past `hold_expires_at` (earlier
        attempts fail with `ERR_HOLD_NOT_EXPIRED`)".
        Design: Corner/validations/rental_hold_expiry_and_expire_guard
        """
        set_clock("2026-09-20T12:00:00Z")
        venue = make_venue()
        suite = make_suite(venue["id"], **SILVER_SUITE)
        season = make_season(venue["id"])
        event = make_event(season["id"], **EVENT_E2)
        account = make_active_account()
        rental = make_rental(event["id"], suite["id"], account["id"], guest_count=8)
        transition_rental(rental["id"], "HELD")  # hold_expires_at = 2026-09-22T12:00Z
        set_clock("2026-09-22T12:00:00Z")  # exactly at expiry: expire needs strictly past
        resp = api.set_rental_status(rental["id"], {"target_status": "EXPIRED"}, ADMIN)
        validate_error(resp, ApiErrorId.ERR_HOLD_NOT_EXPIRED)
        set_clock("2026-09-22T12:00:01Z")  # one second past expiry
        resp = api.set_rental_status(rental["id"], {"target_status": "CONFIRMED"}, REP)
        validate_error(resp, ApiErrorId.ERR_HOLD_EXPIRED)
        expired = validate_success(api.set_rental_status(
            rental["id"], {"target_status": "EXPIRED"}, ADMIN))
        assert expired["status"] == "EXPIRED"

    def test_rental_confirm_blocked_on_credit_hold(self, api: ApiClient):
        """PRD §3.8: "the account's `credit_standing` must not be `HOLD` (else
        `ERR_ACCOUNT_CREDIT_HOLD`)".
        Design: Corner/validations/rental_confirm_blocked_on_credit_hold
        """
        set_clock("2026-08-01T00:00:00Z")
        venue = make_venue()
        suite = make_suite(venue["id"], **SILVER_SUITE)
        season = make_season(venue["id"])
        event = make_event(season["id"], **EVENT_E2)
        account = make_active_account()
        make_issued_invoice(account["id"], lines=[{"description": "Old debt",
                                                   "quantity": 1, "unit_price_cents": 7000}],
                            due_on="2026-08-10T00:00:00Z")
        set_clock("2026-09-13T00:00:00Z")
        rental = make_rental(event["id"], suite["id"], account["id"], guest_count=8)
        transition_rental(rental["id"], "HELD")
        set_clock("2026-09-14T00:00:00Z")  # invoice is 35 days past due -> HOLD
        assert validate_success(api.get_account(account["id"], FIN))["credit_standing"] == "HOLD"
        resp = api.set_rental_status(rental["id"], {"target_status": "CONFIRMED"}, REP)
        validate_error(resp, ApiErrorId.ERR_ACCOUNT_CREDIT_HOLD)
        assert validate_success(api.get_rental(rental["id"], REP))["status"] == "HELD"
        assert list_invoice_rows({"rental_id": rental["id"]}) == [], (
            "no RENTAL invoice may be created by a rejected confirm")

    def test_rental_hold_blocked_when_suite_out_of_service(self, api: ApiClient):
        """PRD §3.8: "and the suite must not be `OUT_OF_SERVICE` — any of these is
        `ERR_SUITE_NOT_AVAILABLE`."
        Design: Corner/validations/rental_hold_blocked_when_suite_out_of_service
        """
        set_clock("2026-08-01T00:00:00Z")
        venue = make_venue()
        suite = make_suite(venue["id"], **GOLD_SUITE)
        season = make_season(venue["id"])
        event = make_event(season["id"], **EVENT_E5)
        account = make_active_account()
        # Quote while the suite is AVAILABLE (PRD §3.8 runs the same availability
        # check at quote creation), then take the suite out of service.
        rental = make_rental(event["id"], suite["id"], account["id"], guest_count=10)
        validate_success(api.set_suite_status(suite["id"], {"target_status": "OUT_OF_SERVICE"},
                                              ADMIN))
        resp = api.set_rental_status(rental["id"], {"target_status": "HELD"}, REP)
        validate_error(resp, ApiErrorId.ERR_SUITE_NOT_AVAILABLE)
        assert validate_success(api.get_rental(rental["id"], REP))["status"] == "QUOTED"


class TestRentalConfirmationInvoice:
    def test_rental_confirm_creates_invoice_with_event_relative_due(self, api: ApiClient):
        """PRD §3.8: "Confirmation bills the rental: a `RENTAL` invoice is created
        already `ISSUED` for the full `quoted_price_cents`, with `due_on` seven days
        before the event's `starts_at`."
        Design: Corner/endpoints/rental_confirm_creates_invoice_with_event_relative_due
        """
        set_clock("2026-12-01T12:00:00Z")
        venue = make_venue()
        suite = make_suite(venue["id"], **GOLD_SUITE)
        season = make_season(venue["id"])
        event = make_event(season["id"], **EVENT_E5)  # starts 2027-01-10T20:00Z
        account = make_active_account()
        rental = setup_confirmed_rental(event, suite, account, guest_count=20)
        inv = get_single_invoice({"rental_id": rental["id"]})
        assert inv["status"] == "ISSUED"
        assert inv["subtotal_cents"] == 1500000, "1200000 * 1.00 GOLD * 1.25 PLAYOFF"
        assert inv["due_on"].startswith("2027-01-03T20:00:00"), (
            f"event start minus seven days expected, got {inv['due_on']}")
        assert inv["account_id"] == account["id"]
        assert inv["rental_id"] == rental["id"]


class TestRentalCancellation:
    def test_rental_cancel_fee_tier_boundaries(self, api: ApiClient):
        """PRD §3.8: "The fee is tiered by the number of whole days between the
        cancellation clock and the event's start: fourteen days or more out costs ten
        percent of the quoted price; seven to thirteen days costs thirty percent" and
        "On a fee-bearing cancellation the original rental invoice is voided and, when
        the fee is greater than zero, a new `RENTAL` invoice is issued containing a
        single cancellation-fee line, due fourteen days after the clock."
        Design: Corner/calculations/rental_cancel_fee_tier_boundaries
        """
        set_clock("2026-09-20T17:00:00Z")
        venue = make_venue()
        suite = make_suite(venue["id"], **SILVER_SUITE)
        season = make_season(venue["id"])
        event = make_event(season["id"], **EVENT_E2)  # starts 2026-10-05T17:00Z
        account = make_active_account()
        # Rental A cancelled exactly 14 days out -> 10% tier.
        ra = setup_confirmed_rental(event, suite, account, guest_count=10)
        assert ra["quoted_price_cents"] == 520000, "650000 * 0.80 SILVER, no overage"
        set_clock("2026-09-21T17:00:00Z")
        ca = validate_success(api.set_rental_status(ra["id"], {"target_status": "CANCELLED"}, REP))
        assert ca["cancel_fee_cents"] == 52000, "exactly 14 days uses the 10% tier"
        # Rental B cancelled 13 days out -> 30% tier.
        set_clock("2026-09-20T17:00:00Z")
        rb = setup_confirmed_rental(event, suite, account, guest_count=10)
        set_clock("2026-09-22T17:00:00Z")
        cb = validate_success(api.set_rental_status(rb["id"], {"target_status": "CANCELLED"}, REP))
        assert cb["cancel_fee_cents"] == 156000, "13 days uses the 30% tier"
        for rental, fee in ((ra, 52000), (rb, 156000)):
            rows = list_invoice_rows({"rental_id": rental["id"]})
            original = [i for i in rows if i["subtotal_cents"] == 520000]
            fee_inv = [i for i in rows if i["subtotal_cents"] == fee]
            assert len(original) == 1 and original[0]["status"] == "VOID", (
                "the original RENTAL invoice is voided")
            assert len(fee_inv) == 1 and fee_inv[0]["status"] == "ISSUED", (
                "a single cancellation-fee RENTAL invoice is issued")

    def test_rental_cancel_with_paid_invoice_rejected(self, api: ApiClient):
        """PRD §3.8: "Cancelling from `CONFIRMED` requires the rental's invoice to
        still be `ISSUED` — a `PARTIALLY_PAID` or `PAID` invoice demands settlement
        first and yields `ERR_RENTAL_SETTLEMENT_REQUIRED`".
        Design: Corner/validations/rental_cancel_with_paid_invoice_rejected
        """
        set_clock("2026-09-20T12:00:00Z")
        venue = make_venue()
        suite = make_suite(venue["id"], **SILVER_SUITE)
        season = make_season(venue["id"])
        event = make_event(season["id"], **EVENT_E2)
        account = make_active_account()
        rental = setup_confirmed_rental(event, suite, account, guest_count=10)
        inv = get_single_invoice({"rental_id": rental["id"]})
        pay_invoice_in_full(account["id"], inv, method="CARD")
        resp = api.set_rental_status(rental["id"], {"target_status": "CANCELLED"}, REP)
        validate_error(resp, ApiErrorId.ERR_RENTAL_SETTLEMENT_REQUIRED)
        assert validate_success(api.get_rental(rental["id"], REP))["status"] == "CONFIRMED"
        assert validate_success(api.get_invoice(inv["id"], FIN))["status"] == "PAID"
