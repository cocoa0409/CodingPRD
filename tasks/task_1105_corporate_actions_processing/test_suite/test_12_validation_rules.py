"""Validation corner claims (PRD §2.1, §2.10, §3.3-§3.9): headers, ownership,
scrub integrity, election option rules, temporal windows, fiscal caps,
statement source rules.
"""
from test_helpers import (
    validate_success, validate_error, get_success_data,
    ApiErrorId,
    make_security, make_account, make_lot, make_event_source, set_clock,
    make_confirmed_event, make_scrubbed_event, make_merger_event_confirmed,
    make_rights_event_confirmed, make_missed_entitlement_context,
    make_account_holder_headers,
    split_terms, merger_terms, create_security_payload,
    create_source_notification_payload, get_event_version,
    get_entitlement_for,
)
from test_helpers.fixtures import ADMIN, VENDOR, ANALYST_1, ANALYST_2, OPS, CUSTODIAN
from test_helpers import api_client


class TestMissingHeaders:
    def test_missing_identity_headers_rejected(self, api):
        """PRD §2.1: "A request in which either header is missing or empty is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400)."

        Design: Corner/validations/missing_headers_unauthenticated
        """
        resp = api.create_security(
            create_security_payload(ticker="ACME", cusip="CUSPD00001",
                                    name="Acme Corp"),
            headers={})
        validate_error(resp, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER)


class TestElectionOwnership:
    def test_submit_for_another_account_rejected(self, api):
        """PRD §3.5: "The ownership rule is absolute: the caller's `X-User-ID` must equal the election's `account_id`, otherwise the request is rejected with `ERR_ACCOUNT_OWNERSHIP_MISMATCH` (HTTP 403)."

        Design: Corner/validations/election_submit_ownership_mismatch_rejected
        """
        ctx = make_merger_event_confirmed(account_shares=10)
        other = make_account(account_number="AB-1", holder_name="B")
        set_clock("2026-05-15T00:00:00Z")
        resp = api.submit_election(
            ctx["event"]["id"],
            {"account_id": other["id"], "option_code": "CASH",
             "expected_event_version": get_event_version(ctx["event"]["id"])},
            make_account_holder_headers(ctx["account"]["id"]))
        validate_error(resp, ApiErrorId.ERR_ACCOUNT_OWNERSHIP_MISMATCH)
        _, meta = __import__("test_helpers").validate_paginated(
            api.list_elections(OPS, params={"event_id": ctx["event"]["id"]}))
        assert meta["total_count"] == 0


class TestScrubConflictingTerms:
    def test_loser_terms_rejected_then_winner_accepted(self, api):
        """PRD §3.3: "the submitted `terms` must equal the winning notification's `announced_terms`, where the winner is the notification from the source with the highest `reliability_weight`, ties broken in favor of the earliest notification `created_at`. Any shortfall — too few notifications, the same source twice, a notification not `RECEIVED`, a mismatch on security, type, or record date, or terms that diverge from the winner's announcement — is rejected with `ERR_NOTIFICATION_SCRUB_MISMATCH` (HTTP 409)."

        Design: Corner/validations/scrub_conflicting_terms_rejected
        """
        sec = make_security(ticker="ACME", cusip="CUSPD00004")
        s1 = make_event_source(name="Vendor Alpha", source_type="VENDOR",
                               reliability_weight=10)
        s2 = make_event_source(name="Vendor Beta", source_type="VENDOR",
                               reliability_weight=5)
        terms_2to1 = split_terms(ratio_num=2, ratio_den=1)
        terms_3to1 = split_terms(ratio_num=3, ratio_den=1)
        n1 = get_success_data(api_client.create_source_notification(
            create_source_notification_payload(
                source_id=s1["id"], security_id=sec["id"], event_type="SPLIT",
                record_date="2026-05-15", announced_terms=terms_2to1), VENDOR))
        n2 = get_success_data(api_client.create_source_notification(
            create_source_notification_payload(
                source_id=s2["id"], security_id=sec["id"], event_type="SPLIT",
                record_date="2026-05-15", announced_terms=terms_3to1), VENDOR))
        # Loser's terms (3:1 from weight-5 Beta) rejected.
        resp = api.create_event(
            {"security_id": sec["id"], "event_type": "SPLIT",
             "terms": terms_3to1, "record_date": "2026-05-15",
             "payable_date": "2026-05-29",
             "source_notification_ids": [n1["id"], n2["id"]]},
            ANALYST_1)
        validate_error(resp, ApiErrorId.ERR_NOTIFICATION_SCRUB_MISMATCH)
        # Winner's terms (2:1 from weight-10 Alpha) accepted.
        event = validate_success(api.create_event(
            {"security_id": sec["id"], "event_type": "SPLIT",
             "terms": terms_2to1, "record_date": "2026-05-15",
             "payable_date": "2026-05-29",
             "source_notification_ids": [n1["id"], n2["id"]]},
            ANALYST_1), 201)
        assert event["status"] == "DRAFT"


class TestElectionOptionRules:
    def test_election_on_mandatory_event_rejected(self, api):
        """PRD §3.5: "it must actually be voluntary, else `ERR_EVENT_NOT_VOLUNTARY` (HTTP 422)."

        Design: Corner/validations/election_on_mandatory_event_rejected
        """
        sec = make_security(ticker="ACME", cusip="CUSPD00005")
        acct = make_account(account_number="A-1", holder_name="One")
        make_lot(acct["id"], sec["id"], quantity=10,
                 acquisition_date="2026-04-01", cost_basis_total_cents=50000)
        event, _, _ = make_confirmed_event(sec["id"], "SPLIT", split_terms())
        resp = api.submit_election(
            event["id"],
            {"account_id": acct["id"], "option_code": "CASH",
             "expected_event_version": get_event_version(event["id"])},
            make_account_holder_headers(acct["id"]))
        validate_error(resp, ApiErrorId.ERR_EVENT_NOT_VOLUNTARY)

    def test_exercise_option_on_merger_rejected(self, api):
        """PRD §3.5: "Option validity is type-scoped: a `MERGER` accepts `CASH` or `STOCK`, a `RIGHTS_OFFERING` accepts `EXERCISE`, and `quantity` is required for a rights election and forbidden for any other type; violations are rejected with `ERR_INVALID_ELECTION_OPTION` (HTTP 400)."

        Design: Corner/validations/invalid_option_exercise_on_merger_rejected
        """
        ctx = make_merger_event_confirmed(account_shares=10)
        event, acct = ctx["event"], ctx["account"]
        set_clock("2026-05-15T00:00:00Z")
        resp = api.submit_election(
            event["id"],
            {"account_id": acct["id"], "option_code": "EXERCISE",
             "quantity": 10,
             "expected_event_version": get_event_version(event["id"])},
            make_account_holder_headers(acct["id"]))
        validate_error(resp, ApiErrorId.ERR_INVALID_ELECTION_OPTION)


class TestClaimWindowsAndEligibility:
    def test_claim_after_window_rejected(self, api):
        """PRD §3.8: "a claim must be filed while the logical clock is no later than thirty days after the event's `payable_date`, inclusive of that final day; a later filing is rejected with `ERR_CLAIM_WINDOW_EXPIRED` (HTTP 422)."

        Design: Corner/validations/claim_after_window_rejected
        """
        ctx = make_missed_entitlement_context()
        # payable 2026-05-29 + 30 days = 2026-06-28 inclusive; 2026-06-29 is past.
        set_clock("2026-06-29T00:00:00Z")
        resp = api.create_claim(
            {"event_id": ctx["event"]["id"],
             "entitlement_id": ctx["entitlement"]["id"],
             "account_id": ctx["account"]["id"],
             "reason": "MISSED_ENTITLEMENT", "claimed_amount_cents": 50000},
            make_account_holder_headers(ctx["account"]["id"]))
        validate_error(resp, ApiErrorId.ERR_CLAIM_WINDOW_EXPIRED)

    def test_claim_on_projected_entitlement_rejected(self, api):
        """PRD §3.8: "The named entitlement must belong to the same event and the same account as the claim, and must be in `MISSED` or `SETTLED` status; otherwise the filing is rejected with `ERR_ENTITLEMENT_NOT_CLAIMABLE` (HTTP 422)."

        Design: Corner/validations/claim_on_projected_entitlement_rejected
        """
        sec = make_security(ticker="ACME", cusip="CUSPD00009")
        acct = make_account(account_number="A-1", holder_name="One")
        make_lot(acct["id"], sec["id"], quantity=5,
                 acquisition_date="2026-04-01", cost_basis_total_cents=25000)
        event, _, _ = make_confirmed_event(
            sec["id"], "SPLIT", split_terms(price_per_share_cents=5000),
            compensation_pool_cents=100000)
        ent = get_entitlement_for(event["id"], acct["id"])
        assert ent["status"] == "PROJECTED"
        set_clock("2026-06-01T00:00:00Z")
        resp = api.create_claim(
            {"event_id": event["id"], "entitlement_id": ent["id"],
             "account_id": acct["id"], "reason": "INCORRECT_AMOUNT",
             "claimed_amount_cents": 10000},
            make_account_holder_headers(acct["id"]))
        validate_error(resp, ApiErrorId.ERR_ENTITLEMENT_NOT_CLAIMABLE)


class TestRightsQuantityCap:
    def test_quantity_beyond_entitlement_rejected(self, api):
        """PRD §3.5: "When the rights event's `oversubscription_allowed` is false, the requested `quantity` must not exceed the account's entitled rights; an excess request is rejected with `ERR_ELECTION_QUANTITY_EXCEEDS_ENTITLEMENT` (HTTP 422)."

        Design: Corner/validations/rights_quantity_beyond_entitlement_rejected
        """
        ctx = make_rights_event_confirmed(account_shares=100,
                                          oversubscription_allowed=False)
        event, acct = ctx["event"], ctx["account"]
        set_clock("2026-05-15T00:00:00Z")
        get_success_data(api_client.capture_record_position(event["id"], OPS))
        resp = api.submit_election(
            event["id"],
            {"account_id": acct["id"], "option_code": "EXERCISE",
             "quantity": 150,
             "expected_event_version": get_event_version(event["id"])},
            make_account_holder_headers(acct["id"]))
        validate_error(resp, ApiErrorId.ERR_ELECTION_QUANTITY_EXCEEDS_ENTITLEMENT)


class TestCompensationPoolReserve:
    def _setup_two_missed_claims(self, pool=60000):
        sec = make_security(ticker="ACME", cusip="CUSPD00011")
        a1 = make_account(account_number="A-1", holder_name="One")
        a2 = make_account(account_number="A-2", holder_name="Two")
        for acct in (a1, a2):
            make_lot(acct["id"], sec["id"], quantity=5,
                     acquisition_date="2026-04-01", cost_basis_total_cents=25000)
        terms = split_terms(price_per_share_cents=5000)
        event, _, _ = make_confirmed_event(
            sec["id"], "SPLIT", terms, compensation_pool_cents=pool)
        set_clock("2026-05-15T00:00:00Z")
        get_success_data(api_client.capture_record_position(event["id"], OPS))
        for acct in (a1, a2):
            get_success_data(api_client.update_account(
                acct["id"], {"status": "FROZEN"}, OPS))
        get_success_data(api_client.book_event(event["id"], OPS))
        ent1 = get_entitlement_for(event["id"], a1["id"])
        ent2 = get_entitlement_for(event["id"], a2["id"])
        set_clock("2026-06-01T00:00:00Z")
        return event, a1, a2, ent1, ent2

    def test_approval_beyond_remaining_pool_rejected(self, api):
        """PRD §3.8: "The computed compensation must fit within the event's `compensation_pool_remaining_cents`; if it exceeds the remaining pool the approval is rejected with `ERR_COMPENSATION_POOL_EXHAUSTED` (HTTP 402). On a successful approval the pool's remaining amount is decremented by the compensation — the money is reserved at approval time".

        Design: Corner/validations/approval_beyond_compensation_pool_rejected
        """
        from test_helpers import make_examiner_headers
        event, a1, a2, ent1, ent2 = self._setup_two_missed_claims()
        from test_helpers.fixtures import file_claim
        c1 = file_claim(event["id"], ent1["id"], a1["id"],
                        claimed_amount_cents=50000)
        c2 = file_claim(event["id"], ent2["id"], a2["id"],
                        claimed_amount_cents=50000)
        decided1 = validate_success(api.decide_claim(
            c1["id"], {"decision": "APPROVED"},
            make_examiner_headers("examiner-1")))
        assert decided1["compensation_cents"] == 50000  # 10 sh x 5000
        event_after = get_success_data(api.get_event(event["id"], OPS))
        assert event_after["compensation_pool_remaining_cents"] == 10000
        resp = api.decide_claim(c2["id"], {"decision": "APPROVED"},
                                make_examiner_headers("examiner-1"))
        validate_error(resp, ApiErrorId.ERR_COMPENSATION_POOL_EXHAUSTED)


class TestStatementSourceRules:
    def test_statement_from_vendor_source_rejected(self, api):
        """PRD §3.9: "A `CustodianFeed` submits a statement naming its `source_id` — which must reference a `CUSTODIAN`-type source, else `ERR_SOURCE_NOT_CUSTODIAN` (HTTP 422)".

        Design: Corner/validations/statement_from_vendor_source_rejected
        """
        vendor = make_event_source(name="Vendor Alpha", source_type="VENDOR",
                                   reliability_weight=10)
        resp = api.create_custodian_statement(
            {"source_id": vendor["id"], "coverage_start_date": "2026-05-01",
             "coverage_end_date": "2026-05-31", "lines": []},
            CUSTODIAN)
        validate_error(resp, ApiErrorId.ERR_SOURCE_NOT_CUSTODIAN)

    def test_inverted_coverage_rejected_as_invalid_request(self, api):
        """PRD §3.9: "The coverage window is a closed interval, inclusive of both days, so the start must not fall after the end — an inverted window fails request-shape validation with `ERR_INVALID_REQUEST".

        Design: Corner/validations/statement_inverted_coverage_invalid_request
        """
        cust = make_event_source(name="Custodian Prime", source_type="CUSTODIAN",
                                 reliability_weight=20)
        resp = api.create_custodian_statement(
            {"source_id": cust["id"], "coverage_start_date": "2026-06-01",
             "coverage_end_date": "2026-05-01", "lines": []},
            CUSTODIAN)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


class TestCaptureTemporalGuard:
    def test_capture_before_record_date_rejected(self, api):
        """PRD §3.6: "Once the logical clock has reached midnight UTC at the start of the event's record date, the `OperationsManager` may capture the record position. Attempting capture earlier is rejected with `ERR_RECORD_DATE_NOT_REACHED` (HTTP 422)".

        Design: Corner/validations/capture_before_record_date_rejected
        """
        sec = make_security(ticker="ACME", cusip="CUSPD00012")
        acct = make_account(account_number="A-1", holder_name="One")
        make_lot(acct["id"], sec["id"], quantity=100,
                 acquisition_date="2026-04-01", cost_basis_total_cents=500000)
        event, _, _ = make_confirmed_event(sec["id"], "SPLIT", split_terms())
        set_clock("2026-05-14T00:00:00Z")
        resp = api.capture_record_position(event["id"], OPS)
        validate_error(resp, ApiErrorId.ERR_RECORD_DATE_NOT_REACHED)
        ent = get_entitlement_for(event["id"], acct["id"])
        assert ent["status"] == "PROJECTED"


class TestBookVoluntaryAtDeadline:
    def test_book_at_exact_deadline_rejected(self, api):
        """PRD §3.6: "for a voluntary event the logical clock must be strictly after the `election_deadline`, since booking at or before the deadline is rejected with `ERR_ELECTION_WINDOW_OPEN` (HTTP 422)."

        Design: Corner/validations/book_voluntary_at_deadline_rejected
        """
        ctx = make_merger_event_confirmed(account_shares=10)
        event = ctx["event"]
        set_clock("2026-05-15T00:00:00Z")
        get_success_data(api_client.capture_record_position(event["id"], OPS))
        set_clock("2026-05-20T16:00:00Z")  # exactly the deadline
        resp = api.book_event(event["id"], OPS)
        validate_error(resp, ApiErrorId.ERR_ELECTION_WINDOW_OPEN)
