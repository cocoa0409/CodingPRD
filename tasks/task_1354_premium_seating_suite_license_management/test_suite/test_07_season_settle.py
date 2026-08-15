"""Season settlement ops-run and event-cancellation fan-out cascades."""
from test_helpers import (
    ADMIN, ESM, FIN, REP,
    ApiClient, ApiErrorId, EVENT_E1, EVENT_E2,
    complete_event, confirm_catering_order, get_license_fee_invoice,
    get_single_invoice, issue_credential_ok, list_invoice_rows,
    make_account_holder_headers, make_active_account, make_event,
    make_rental, make_season, make_suite, make_venue, make_waitlist_entry,
    pay_invoice_in_full, place_catering_order_ok, set_clock, settle_season,
    setup_active_agreement, setup_confirmed_rental, setup_renewal_offer,
    transition_rental, validate_error, validate_success,
)

GOLD_SUITE = dict(suite_code="G-101", tier="GOLD", capacity_seats=20,
                  base_annual_fee_cents=12000000, f_b_minimum_cents=4000000)


class TestSettleReentrance:
    def test_season_settle_twice_rejected(self, api: ApiClient):
        """PRD §3.5: "Settlement is not re-entrant — `SETTLED` is terminal, and a
        second settle attempt hits the same error."
        Design: Corner/state_machines/season_settle_twice_rejected
        """
        set_clock("2026-08-01T00:00:00Z")
        venue = make_venue()
        season = make_season(venue["id"])
        event = make_event(season["id"], **EVENT_E1)
        complete_event(event["id"], "2027-02-16T00:00:00Z")
        settle_season(season["id"], "2027-02-16T00:00:00Z")
        resp = api.settle_season(season["id"], FIN)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE_TRANSITION)
        assert list_invoice_rows({"season_id": season["id"]}) == [], (
            "a rejected second settle must run no side effects")


class TestSettleSweep:
    def _setup(self, api: ApiClient):
        """Term-1 ACTIVE agreement with its license fee PAID; a stale renewal offer;
        a waitlist entry targeting the season being settled. S1 has no events."""
        s = setup_active_agreement(num_seasons=2, agreement_over=dict(term_seasons=1))
        ac, ag = s["account"], s["agreement"]
        pay_invoice_in_full(ac["id"], get_license_fee_invoice(ag["id"]))
        offer = setup_renewal_offer(ag["id"], s["seasons"][1]["id"],
                                    at_clock="2026-12-10T00:00:00Z",
                                    response_due_on="2027-01-10T00:00:00Z")
        entry = make_waitlist_entry(ac["id"], desired_tier="GOLD",
                                    target_season_id=s["seasons"][0]["id"])
        set_clock("2027-02-20T00:00:00Z")
        return s, offer, entry

    def test_settle_sweep_expires_offers_and_waitlist(self, api: ApiClient):
        """PRD §3.5: "Link five sweeps stragglers: renewal offers of the season's
        agreements sitting in `OFFERED` or `REVISED` with a `response_due_on` before
        the clock become `EXPIRED`, and waitlist entries still `WAITING` whose
        `target_season_id` is this season become `EXPIRED`."
        Design: Corner/cross_cutting_layers/settle_sweep_expires_offers_waitlist_and_ends_term
        """
        s, offer, entry = self._setup(api)
        settle_season(s["seasons"][0]["id"], "2027-02-20T00:00:00Z")
        assert validate_success(api.get_renewal_offer(offer["id"], REP))["status"] == "EXPIRED"
        assert validate_success(api.get_waitlist_entry(entry["id"], REP))["status"] == "EXPIRED"
        assert validate_success(api.get_season(s["seasons"][0]["id"], FIN))["status"] == "SETTLED"

    def test_settle_ends_term_and_releases_suite_with_shortfall(self, api: ApiClient):
        """PRD §3.5: "an agreement whose last covered season is the one being settled
        becomes `RENEWED` when its `renewal_agreement_id` is set and `EXPIRED`
        otherwise — with its suite released to `AVAILABLE` on expiry"; "the shortfall,
        never negative — becomes an `F_B_SHORTFALL` invoice".
        Design: Corner/cross_cutting_layers/settle_sweep_expires_offers_waitlist_and_ends_term
        """
        s, offer, entry = self._setup(api)
        settle_season(s["seasons"][0]["id"], "2027-02-20T00:00:00Z")
        agreement = validate_success(api.get_agreement(s["agreement"]["id"], REP))
        assert agreement["status"] == "EXPIRED", "term ended, offer never accepted"
        suite = validate_success(api.get_suite(s["suite"]["id"], REP))
        assert suite["status"] == "AVAILABLE"
        sh = get_single_invoice({"agreement_id": s["agreement"]["id"],
                                 "invoice_type": "F_B_SHORTFALL"})
        assert sh["subtotal_cents"] == 4000000, "full minimum, zero accrual"

    def test_agreement_renewed_at_final_season_settle(self, api: ApiClient):
        """PRD §3.5: "an agreement whose last covered season is the one being settled
        becomes `RENEWED` when its `renewal_agreement_id` is set and `EXPIRED`
        otherwise". PRD §3.3: "the suite passes through `AVAILABLE` and is immediately
        re-`LICENSED` if the renewal agreement's execution is pending, otherwise
        remaining `AVAILABLE`".
        Design: Corner/state_machines/agreement_renewed_at_final_season_settle
        """
        s = setup_active_agreement(num_seasons=2, agreement_over=dict(term_seasons=1))
        ac, ag = s["account"], s["agreement"]
        pay_invoice_in_full(ac["id"], get_license_fee_invoice(ag["id"]))
        offer = setup_renewal_offer(ag["id"], s["seasons"][1]["id"],
                                    at_clock="2026-12-10T00:00:00Z",
                                    response_due_on="2027-01-10T00:00:00Z")
        validate_success(api.set_renewal_offer_status(
            offer["id"], {"target_status": "ACCEPTED"}, make_account_holder_headers(ac["id"])))
        settle_season(s["seasons"][0]["id"], "2027-02-20T00:00:00Z")
        settled = validate_success(api.get_agreement(ag["id"], REP))
        assert settled["status"] == "RENEWED", "renewal_agreement_id was set before settle"
        renewal = validate_success(api.get_agreement(settled["renewal_agreement_id"], REP))
        assert renewal["status"] == "DRAFT"
        assert renewal["start_season_id"] == s["seasons"][1]["id"]
        suite = validate_success(api.get_suite(s["suite"]["id"], REP))
        assert suite["status"] == "AVAILABLE", "the DRAFT renewal has not executed"


class TestEventCancellationCascade:
    def test_event_cancel_fans_out_full_compensation_cascade(self, api: ApiClient):
        """PRD §3.1: "Cancellation is a wide cascade: every catering order of the event
        still in `DRAFT`, `PLACED`, or `CONFIRMED` moves to `CANCELLED` with
        `cancel_fee_cents` of zero and its accrual removed ...; every access credential
        of the event in `ISSUED` or `ACTIVATED` moves to `EXPIRED`; and every
        single-event rental in `QUOTED`, `HELD`, or `CONFIRMED` moves to `CANCELLED`
        with `cancel_fee_cents` of zero, with its unpaid rental invoice voided."
        Design: Corner/cross_cutting_layers/event_cancel_fans_out_full_compensation_cascade
        """
        set_clock("2026-09-01T12:00:00Z")
        venue = make_venue()
        suite = make_suite(venue["id"], **GOLD_SUITE)
        season = make_season(venue["id"])
        event = make_event(season["id"], **EVENT_E2)
        account = make_active_account()
        rental = setup_confirmed_rental(event, suite, account, guest_count=20)
        order = place_catering_order_ok(
            event["id"], suite["id"], rental_id=rental["id"], guest_count=8,
            account_id=account["id"])
        confirm_catering_order(order["id"])
        cred = issue_credential_ok(event["id"], suite["id"], rental_id=rental["id"])
        set_clock("2026-09-20T00:00:00Z")  # before the 2026-10-05 start
        validate_success(api.set_event_status(event["id"], {"target_status": "CANCELLED"}, ADMIN))
        o = validate_success(api.get_catering_order(order["id"], ESM))
        assert o["status"] == "CANCELLED" and o["cancel_fee_cents"] == 0
        assert validate_success(api.get_credential(cred["id"], ESM))["status"] == "EXPIRED"
        r = validate_success(api.get_rental(rental["id"], REP))
        assert r["status"] == "CANCELLED" and r["cancel_fee_cents"] == 0, (
            "the event-cancel exemption beats the tiered cancel-fee table")
        inv = get_single_invoice({"rental_id": rental["id"]})
        assert inv["status"] == "VOID"
        assert validate_success(api.get_account(account["id"], FIN))["balance_due_cents"] == 0
