"""Validation priority pairs (PRD §2.10) and boundary precision
(PRD §3.5 deadline inclusivity, §3.6 odd-lot threshold).
"""
from test_helpers import (
    validate_success, validate_error, get_success_data,
    ApiErrorId,
    make_security, make_account, make_lot, set_clock,
    make_confirmed_event, make_merger_event_confirmed,
    make_missed_entitlement_context, file_claim,
    make_account_holder_headers, split_terms, merger_terms,
    get_event_version,
)
from test_helpers.fixtures import OPS, ANALYST_1, ANALYST_2
from test_helpers import api_client


def _draft_merger_past_deadline():
    """MERGER left in DRAFT with deadline 2026-05-10T16:00:00Z; clock moved to
    2026-05-11 (past the deadline)."""
    sec = make_security(ticker="ACME")
    newco = make_security(ticker="NWC", name="Newco Inc")
    acct = make_account(account_number="A-1", holder_name="One")
    make_lot(acct["id"], sec["id"], quantity=10,
             acquisition_date="2026-04-01", cost_basis_total_cents=50000)
    terms = merger_terms(newco["id"])
    event, _, _ = __import__("test_helpers").make_scrubbed_event(
        sec["id"], "MERGER", terms, record_date="2026-05-08",
        payable_date="2026-05-29", election_required=True,
        election_deadline="2026-05-10T16:00:00Z")
    set_clock("2026-05-11T00:00:00Z")
    return sec, acct, event


class TestElectionStateErrorBeatsDeadlineError:
    def test_draft_event_and_past_deadline_yields_state_error(self, api):
        """PRD §2.10: "sixth, state preconditions of the target entity; seventh, the optimistic-concurrency version match where the endpoint participates; eighth, segregation of duties; ninth, business constraints and conflicts" and "tenth, temporal windows judged against the logical clock".
        PRD §3.5: "The event must be `CONFIRMED` — an election against an event in any other state is rejected with `ERR_EVENT_NOT_ACCEPTING_ELECTIONS`".

        Design: Difficulty/priority_pair_validation_conflict/election_state_error_beats_deadline_error
        """
        _, acct, event = _draft_merger_past_deadline()
        resp = api.submit_election(
            event["id"],
            {"account_id": acct["id"], "option_code": "CASH",
             "expected_event_version": event["version"]},
            make_account_holder_headers(acct["id"]))
        validate_error(resp, ApiErrorId.ERR_EVENT_NOT_ACCEPTING_ELECTIONS)

    def test_state_error_not_temporal_error_when_both_hold(self, api):
        """PRD §2.10: "Every request is validated in a fixed order, and a
        failure at any step prevents evaluation of the steps that follow."
        PRD §3.5: "a submission strictly after the deadline is rejected with `ERR_ELECTION_DEADLINE_PASSED` (HTTP 422)".

        Design: Difficulty/priority_pair_validation_conflict/election_state_error_beats_deadline_error
        """
        _, acct, event = _draft_merger_past_deadline()
        resp = api.submit_election(
            event["id"],
            {"account_id": acct["id"], "option_code": "CASH",
             "expected_event_version": event["version"]},
            make_account_holder_headers(acct["id"]))
        body = resp.json()
        assert body["data"]["error_id"] == "ERR_EVENT_NOT_ACCEPTING_ELECTIONS"
        assert body["data"]["error_id"] != "ERR_ELECTION_DEADLINE_PASSED"


class TestClaimDuplicateBeatsAmountCap:
    def _setup(self):
        ctx = make_missed_entitlement_context(price_per_share_cents=5000,
                                              compensation_pool_cents=100000)
        first = file_claim(ctx["event"]["id"], ctx["entitlement"]["id"],
                           ctx["account"]["id"], claimed_amount_cents=10000)
        return ctx, first

    def test_duplicate_claim_rejected_despite_over_cap_amount(self, api):
        """PRD §2.10: "ninth, business constraints and conflicts such as suspended securities, overlapping event windows, scrub-set integrity, overlapping statement coverage, duplicate open claims, and account activity or settlement status" and "twelfth, fiscal caps such as the claim amount cap and the compensation pool reserve".
        PRD §3.8: "At most one open claim may exist per entitlement: if another `FILED` claim already references it, the filing is rejected with `ERR_DUPLICATE_OPEN_CLAIM` (HTTP 409)."

        Design: Difficulty/priority_pair_validation_conflict/claim_duplicate_beats_amount_cap
        """
        ctx, first = self._setup()
        resp = api.create_claim(
            {"event_id": ctx["event"]["id"],
             "entitlement_id": ctx["entitlement"]["id"],
             "account_id": ctx["account"]["id"],
             "reason": "INCORRECT_AMOUNT",
             "claimed_amount_cents": 300000},
            make_account_holder_headers(ctx["account"]["id"]))
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_OPEN_CLAIM)

    def test_first_claim_unaffected_by_rejected_duplicate(self, api):
        """PRD §3.8: "At most one open claim may exist per entitlement: if another `FILED` claim already references it, the filing is rejected with `ERR_DUPLICATE_OPEN_CLAIM` (HTTP 409)." and "The claimed amount must be greater than zero and no more than 250,000 cents; anything else is rejected with `ERR_CLAIM_AMOUNT_EXCEEDS_CAP` (HTTP 422)."

        Design: Difficulty/priority_pair_validation_conflict/claim_duplicate_beats_amount_cap
        """
        ctx, first = self._setup()
        resp = api.create_claim(
            {"event_id": ctx["event"]["id"],
             "entitlement_id": ctx["entitlement"]["id"],
             "account_id": ctx["account"]["id"],
             "reason": "INCORRECT_AMOUNT",
             "claimed_amount_cents": 300000},
            make_account_holder_headers(ctx["account"]["id"]))
        body = resp.json()
        assert body["data"]["error_id"] == "ERR_DUPLICATE_OPEN_CLAIM"
        assert body["data"]["error_id"] != "ERR_CLAIM_AMOUNT_EXCEEDS_CAP"
        first_after = get_success_data(api.get_claim(first["id"], OPS))
        assert first_after["review_status"] == "FILED"


class TestElectionDeadlineExactSecondAccepted:
    def _setup(self):
        ctx = make_merger_event_confirmed(account_shares=10)
        acct2 = make_account(account_number="A-2", holder_name="Two")
        make_lot(acct2["id"], ctx["security"]["id"], quantity=10,
                 acquisition_date="2026-04-01", cost_basis_total_cents=50000)
        ctx["account2"] = acct2
        return ctx

    def test_submission_at_exact_deadline_accepted(self, api):
        """PRD §3.5: "The logical clock must be on or before the event's `election_deadline`; a submission strictly after the deadline is rejected with `ERR_ELECTION_DEADLINE_PASSED` (HTTP 422)."

        Design: Difficulty/boundary_precision_check/election_deadline_exact_second_accepted
        """
        ctx = self._setup()
        event, acct = ctx["event"], ctx["account"]
        set_clock("2026-05-20T16:00:00Z")
        election = validate_success(api.submit_election(
            event["id"],
            {"account_id": acct["id"], "option_code": "CASH",
             "expected_event_version": get_event_version(event["id"])},
            make_account_holder_headers(acct["id"])), 201)
        assert election["status"] == "SUBMITTED"

    def test_submission_one_second_after_deadline_rejected(self, api):
        """PRD §3.5: "a submission strictly after the deadline is rejected with `ERR_ELECTION_DEADLINE_PASSED` (HTTP 422)."
        PRD §3.3: "submissions are accepted while the logical clock is on or
        before that deadline."

        Design: Difficulty/boundary_precision_check/election_deadline_exact_second_accepted
        """
        ctx = self._setup()
        event, acct2 = ctx["event"], ctx["account2"]
        # First account submits at the exact deadline (consumed boundary case).
        set_clock("2026-05-20T16:00:00Z")
        set_clock("2026-05-20T16:00:01Z")
        resp = api.submit_election(
            event["id"],
            {"account_id": acct2["id"], "option_code": "CASH",
             "expected_event_version": get_event_version(event["id"])},
            make_account_holder_headers(acct2["id"]))
        validate_error(resp, ApiErrorId.ERR_ELECTION_DEADLINE_PASSED)


class TestOddLotThreshold99Vs100:
    def _setup(self):
        sec = make_security(ticker="ACME")
        newco = make_security(ticker="NWC", name="Newco Inc")
        holders = {}
        for key, num, sh in (("small", "AS-1", 99), ("edge", "AE-1", 100),
                             ("big", "AB-1", 120)):
            acct = make_account(account_number=num, holder_name=key.title())
            make_lot(acct["id"], sec["id"], quantity=sh,
                     acquisition_date="2026-04-01",
                     cost_basis_total_cents=sh * 5000)
            holders[key] = acct
        terms = merger_terms(newco["id"], cash_per_share_cents=5000,
                             cash_pool_cents=900000, default_option="STOCK")
        event, _, _ = make_confirmed_event(
            sec["id"], "MERGER", terms, election_required=True,
            election_deadline="2026-05-20T16:00:00Z")
        set_clock("2026-05-15T00:00:00Z")
        get_success_data(api_client.capture_record_position(event["id"], OPS))
        for acct in holders.values():
            get_success_data(api_client.submit_election(
                event["id"],
                {"account_id": acct["id"], "option_code": "CASH",
                 "expected_event_version": get_event_version(event["id"])},
                make_account_holder_headers(acct["id"])))
        set_clock("2026-05-21T00:00:00Z")
        return sec, newco, holders, event

    def test_99_shares_odd_lot_cashed_in_full(self, api):
        """PRD §3.6: "Accounts are first classified: an odd-lot account holds more than zero and fewer than 100 shares of settled position. Odd-lot accounts that elected `CASH` are honored in full first, at their shares multiplied by the terms' `cash_per_share_cents".

        Design: Difficulty/boundary_precision_check/odd_lot_threshold_99_full_vs_100_prorated
        """
        _, newco, holders, event = self._setup()
        validate_success(api.book_event(event["id"], OPS), 201)
        small = get_success_data(api.get_account(holders["small"]["id"], OPS))
        assert small["cash_balance_cents"] == 495000  # 99 x 5000 in full

    def test_100_shares_not_odd_lot_prorated(self, api):
        """PRD §3.6: "The proration factor is the smaller of one and the quotient of the remaining pool divided by the total round-lot cash elected (the sum over round-lot `CASH` electors of shares multiplied by `cash_per_share_cents`), with that quotient rounded down to four decimal places" and "Each round-lot cash elector then receives cash for its shares multiplied by the factor, rounded down to whole shares, paid at `cash_per_share_cents`; its remaining shares convert into the new security at the terms' ratio".

        Design: Difficulty/boundary_precision_check/odd_lot_threshold_99_full_vs_100_prorated
        """
        _, newco, holders, event = self._setup()
        validate_success(api.book_event(event["id"], OPS), 201)
        edge = get_success_data(api.get_account(holders["edge"]["id"], OPS))
        # factor = floor4((900000-495000)/1100000) = floor4(0.3681...) = 0.3681
        # cash shares = floor(100 x 0.3681) = 36 -> 180000 cents
        assert edge["cash_balance_cents"] == 180000
        assert edge["cash_balance_cents"] != 500000
        resp = api.list_position_lots(
            OPS, params={"account_id": holders["edge"]["id"],
                         "security_id": newco["id"]})
        rows = resp.json()["data"]
        assert len(rows) == 1
        assert rows[0]["quantity"] == 64  # remaining 64 shares convert 1:1
