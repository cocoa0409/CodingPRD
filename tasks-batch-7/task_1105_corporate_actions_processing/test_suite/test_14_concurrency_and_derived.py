"""Cross-cutting complexity claims (PRD §2.4, §2.7, §2.9, §3.6): optimistic
concurrency, the fixed default logical clock, derived-counter reconciliation,
and the frozen-account booking skip.
"""
from test_helpers import (
    validate_success, validate_error, validate_paginated, get_success_data,
    ApiErrorId,
    make_security, make_account, make_lot, set_clock,
    make_confirmed_event, make_merger_event_confirmed,
    make_account_holder_headers, split_terms, merger_terms,
    get_event_version, get_entitlement_for,
)
from test_helpers.fixtures import OPS, ANALYST_1, ANALYST_2
from test_helpers import api_client


class TestOccAmendmentStaleVersion:
    def test_stale_amendment_rejected_after_first_amendment(self, api):
        """PRD §2.7: "A request to `POST /api/events/{id}/amendments` must carry `expected_event_version`, a non-optional field holding the event `version` the client last read." and "if the supplied value does not equal the event's current `version` — because a prior amendment, a confirmation, an election submission, or any other version-bumping mutation has advanced it since the client last read the event — the request is rejected with `ERR_STALE_EVENT_VERSION` (HTTP 412), and no change is applied."

        Design: Corner/cross_cutting_complexity_layers/occ_amendment_with_stale_version_rejected

        PRD §2.10 ordering: state preconditions (step 6) precede the OCC version
        match (step 7). After the first amendment the event is `AMENDED`, which
        fails the state check (`ERR_EVENT_NOT_AMENDABLE`) — so a stale-version
        assertion requires re-confirming first (PRD §3.4: "An `AMENDED` event is
        confirmed again through the same confirmation path — `AMENDED` →
        `CONFIRMED`"). With the event `CONFIRMED` at a newer version, a request
        carrying the pre-amendment version exercises the OCC branch alone.
        """
        sec = make_security(ticker="ACME", cusip="CUSPG00001")
        event, _, _ = make_confirmed_event(sec["id"], "SPLIT", split_terms())
        stale_v = event["version"]
        amd1 = validate_success(api.amend_event(
            event["id"],
            {"amended_terms": split_terms(ratio_num=3),
             "reason": "first revision", "expected_event_version": stale_v},
            ANALYST_1), 201)
        assert amd1["amendment_seq"] == 1
        # PRD §3.4: AMENDED → CONFIRMED via the same confirmation path.
        # Use ANALYST_2 (not the scrubber) to satisfy segregation of duties.
        validate_success(api.confirm_event(event["id"], ANALYST_2))
        resp = api.amend_event(
            event["id"],
            {"amended_terms": split_terms(ratio_num=4),
             "reason": "stale second revision",
             "expected_event_version": stale_v},
            ANALYST_2)
        validate_error(resp, ApiErrorId.ERR_STALE_EVENT_VERSION)
        _, meta = validate_paginated(api.list_amendments(event["id"], OPS))
        assert meta["total_count"] == 1


class TestOccElectionStaleVersion:
    def test_second_submit_with_stale_version_rejected(self, api):
        """PRD §2.7: "A request to `POST /api/events/{id}/elections` must likewise carry `expected_event_version`." and "if the supplied value does not equal the event's current `version` — because a prior amendment, a confirmation, an election submission, or any other version-bumping mutation has advanced it since the client last read the event — the request is rejected with `ERR_STALE_EVENT_VERSION` (HTTP 412), and no change is applied." PRD §3.5: "Every submission, withdrawal, and resubmission increments the hosting event's `version` by one".

        Design: Corner/cross_cutting_complexity_layers/occ_election_with_stale_version_rejected
        """
        ctx = make_merger_event_confirmed(account_shares=10)
        event, acct = ctx["event"], ctx["account"]
        set_clock("2026-05-15T00:00:00Z")
        stale_v = event["version"]
        headers = make_account_holder_headers(acct["id"])
        e1 = validate_success(api.submit_election(
            event["id"],
            {"account_id": acct["id"], "option_code": "CASH",
             "expected_event_version": stale_v},
            headers), 201)
        resp = api.submit_election(
            event["id"],
            {"account_id": acct["id"], "option_code": "STOCK",
             "expected_event_version": stale_v},
            headers)
        validate_error(resp, ApiErrorId.ERR_STALE_EVENT_VERSION)
        e1_after = get_success_data(api.get_election(e1["id"], OPS))
        assert e1_after["status"] == "SUBMITTED"


class TestPendingEntitlementCountLifecycle:
    def test_counter_reconciles_across_confirm_capture_book(self, api):
        """PRD §2.9: "An account's `pending_entitlement_count` is the count of its entitlements currently in `PROJECTED` or `FIRM` status. Each recomputation is a mutation of the account record and therefore refreshes the account's `updated_at` and increments its `version`."
        PRD §3.1: "`pending_entitlement_count` starts at zero".

        Design: Corner/cross_cutting_complexity_layers/pending_entitlement_count_tracks_lifecycle
        """
        sec = make_security(ticker="ACME", cusip="CUSPG00004")
        acct = make_account(account_number="A-1", holder_name="One")
        assert acct["pending_entitlement_count"] == 0
        make_lot(acct["id"], sec["id"], quantity=100,
                 acquisition_date="2026-04-01", cost_basis_total_cents=500000)
        event, _, _ = make_confirmed_event(sec["id"], "SPLIT", split_terms())
        after_confirm = get_success_data(api.get_account(acct["id"], OPS))
        assert after_confirm["pending_entitlement_count"] == 1
        set_clock("2026-05-15T00:00:00Z")
        get_success_data(api_client.capture_record_position(event["id"], OPS))
        after_capture = get_success_data(api.get_account(acct["id"], OPS))
        assert after_capture["pending_entitlement_count"] == 1  # FIRM in place
        get_success_data(api_client.book_event(event["id"], OPS))
        after_book = get_success_data(api.get_account(acct["id"], OPS))
        assert after_book["pending_entitlement_count"] == 0


class TestUnsetClockDefaultsToFixedStart:
    def test_deadline_before_default_clock_rejected_without_clock_set(self, api):
        """PRD §2.4: "Before any clock-setting call has been made, the logical
        clock reads exactly 2026-05-01T00:00:00Z and the server must never fall
        back to wall-clock time." PRD §3.5: "a submission strictly after the deadline is rejected with `ERR_ELECTION_DEADLINE_PASSED` (HTTP 422)."

        Design: Corner/cross_cutting_complexity_layers/unset_clock_defaults_to_fixed_start
        """
        # Deadline 2026-04-30T16:00:00Z is before the default clock reading;
        # no clock-set call is ever made in this test.
        ctx = make_merger_event_confirmed(
            account_shares=10, election_deadline="2026-04-30T16:00:00Z",
            record_date="2026-04-15")
        event, acct = ctx["event"], ctx["account"]
        resp = api.submit_election(
            event["id"],
            {"account_id": acct["id"], "option_code": "CASH",
             "expected_event_version": get_event_version(event["id"])},
            make_account_holder_headers(acct["id"]))
        validate_error(resp, ApiErrorId.ERR_ELECTION_DEADLINE_PASSED)


class TestFrozenAccountEntitlementMissed:
    def test_booking_skips_frozen_account_without_mutation(self, api):
        """PRD §3.1: "an account that is not `ACTIVE` is skipped when an event is booked — its entitlement goes to `MISSED`". PRD §3.6: "when the account is not `ACTIVE` it moves `FIRM` → `MISSED`, and no lot is mutated and no cash is credited for it." and "`total_whole_shares_credited` is the sum of whole shares credited across all `SETTLED` entitlements in the booking".

        Design: Corner/cross_cutting_complexity_layers/frozen_account_entitlement_missed_no_mutation
        """
        sec = make_security(ticker="ACME", cusip="CUSPG00007")
        acct = make_account(account_number="A-1", holder_name="One")
        lot = make_lot(acct["id"], sec["id"], quantity=5,
                       acquisition_date="2026-04-01", cost_basis_total_cents=25000)
        event, _, _ = make_confirmed_event(sec["id"], "SPLIT", split_terms())
        set_clock("2026-05-15T00:00:00Z")
        get_success_data(api_client.capture_record_position(event["id"], OPS))
        get_success_data(api_client.update_account(
            acct["id"], {"status": "FROZEN"}, OPS))
        booking = validate_success(api.book_event(event["id"], OPS), 201)
        ent = get_entitlement_for(event["id"], acct["id"])
        assert ent["status"] == "MISSED"
        lot_after = get_success_data(api.get_position_lot(lot["id"], OPS))
        assert lot_after["quantity"] == 5
        acct_after = get_success_data(api.get_account(acct["id"], OPS))
        assert acct_after["cash_balance_cents"] == 0
        assert booking["total_whole_shares_credited"] == 0
        assert booking["total_cash_credited_cents"] == 0
