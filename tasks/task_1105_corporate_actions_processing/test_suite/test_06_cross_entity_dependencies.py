"""Cross-entity state dependencies (PRD §3.5, §3.7): election gated on event
state; completion gated on open recon breaks.
"""
from test_helpers import (
    validate_success, validate_error, get_success_data,
    ApiErrorId,
    make_security, make_account, make_lot, set_clock,
    make_confirmed_event, make_merger_event_confirmed,
    make_custodian_source, submit_statement,
    make_account_holder_headers, split_terms, get_event_version,
)
from test_helpers.fixtures import OPS, ANALYST_1
from test_helpers import api_client


class TestElectionBlockedWhenEventAmended:
    def _setup(self):
        ctx = make_merger_event_confirmed(account_shares=10)
        event = ctx["event"]
        # Amend: CONFIRMED -> AMENDED.
        new_terms = dict(ctx["terms"])
        new_terms["cash_per_share_cents"] = 5100
        get_success_data(api_client.amend_event(
            event["id"],
            {"amended_terms": new_terms, "reason": "cash consideration raised",
             "expected_event_version": event["version"]},
            ANALYST_1))
        set_clock("2026-05-15T00:00:00Z")
        return ctx

    def test_election_on_amended_event_rejected(self, api):
        """PRD §3.5: "The event must be `CONFIRMED` — an election against an event in any other state is rejected with `ERR_EVENT_NOT_ACCEPTING_ELECTIONS".

        Design: Difficulty/cross_entity_state_dependency/election_blocked_when_event_amended
        """
        ctx = self._setup()
        event, acct = ctx["event"], ctx["account"]
        current = get_success_data(api.get_event(event["id"], OPS))
        assert current["status"] == "AMENDED"
        resp = api.submit_election(
            event["id"],
            {"account_id": acct["id"], "option_code": "CASH",
             "expected_event_version": current["version"]},
            make_account_holder_headers(acct["id"]))
        validate_error(resp, ApiErrorId.ERR_EVENT_NOT_ACCEPTING_ELECTIONS)

    def test_election_accepted_after_reconfirmation(self, api):
        """PRD §3.5: "The event must be `CONFIRMED` — an election against an event in any other state is rejected with `ERR_EVENT_NOT_ACCEPTING_ELECTIONS".
        PRD §3.4: "An `AMENDED` event is confirmed again through the same confirmation path — `AMENDED` → `CONFIRMED".

        Design: Difficulty/cross_entity_state_dependency/election_blocked_when_event_amended
        """
        ctx = self._setup()
        event, acct = ctx["event"], ctx["account"]
        resp_before = api.submit_election(
            event["id"],
            {"account_id": acct["id"], "option_code": "CASH",
             "expected_event_version": get_event_version(event["id"])},
            make_account_holder_headers(acct["id"]))
        assert resp_before.json()["data"]["error_id"] == (
            "ERR_EVENT_NOT_ACCEPTING_ELECTIONS")
        from test_helpers.fixtures import ANALYST_2
        validate_success(api.confirm_event(event["id"], ANALYST_2))
        election = validate_success(api.submit_election(
            event["id"],
            {"account_id": acct["id"], "option_code": "CASH",
             "expected_event_version": get_event_version(event["id"])},
            make_account_holder_headers(acct["id"])), 201)
        assert election["status"] == "SUBMITTED"


class TestCompleteBlockedByOpenReconBreak:
    def _setup(self):
        """SPLIT 2:1 BOOKED (1000 -> 2000 shares, no cash movement); custodian
        statement reports cash_cents 5000 against books of 0 -> OPEN
        CASH_MISMATCH break linked to the event."""
        sec = make_security(ticker="ACME")
        acct = make_account(account_number="A-1", holder_name="One")
        make_lot(acct["id"], sec["id"], quantity=1000,
                 acquisition_date="2026-04-01", cost_basis_total_cents=10000000)
        event, _, _ = make_confirmed_event(sec["id"], "SPLIT", split_terms())
        set_clock("2026-05-15T00:00:00Z")
        get_success_data(api_client.capture_record_position(event["id"], OPS))
        get_success_data(api_client.book_event(event["id"], OPS))
        cust = make_custodian_source()
        stmt = submit_statement(
            cust["id"], "2026-05-16", "2026-05-31",
            [{"account_id": acct["id"], "security_id": sec["id"],
              "event_id": event["id"], "quantity": 2000, "cash_cents": 5000}])
        resp = api_client.list_recon_breaks(OPS, params={"statement_id": stmt["id"]})
        brk = resp.json()["data"][0]
        return sec, acct, event, brk

    def test_complete_rejected_while_break_open(self, api):
        """PRD §3.7: "no `OPEN` reconciliation break may reference the event, else `ERR_OPEN_RECON_BREAKS_EXIST` (HTTP 409)."

        Design: Difficulty/cross_entity_state_dependency/complete_blocked_by_open_recon_break
        """
        _, _, event, brk = self._setup()
        assert brk["break_type"] == "CASH_MISMATCH"
        assert brk["status"] == "OPEN"
        resp = api.complete_event(event["id"], OPS)
        validate_error(resp, ApiErrorId.ERR_OPEN_RECON_BREAKS_EXIST)

    def test_complete_succeeds_after_break_resolved(self, api):
        """PRD §3.9: "an `OperationsManager` resolves a break by submitting a `resolution` of `RESOLVED` or `WRITTEN_OFF` together with a `resolution_note"
        and PRD §3.7: "Completion moves the event `BOOKED` → `COMPLETED` and increments its `version`."

        Design: Difficulty/cross_entity_state_dependency/complete_blocked_by_open_recon_break
        """
        _, _, event, brk = self._setup()
        resp = api.complete_event(event["id"], OPS)
        assert resp.json()["data"]["error_id"] == "ERR_OPEN_RECON_BREAKS_EXIST"
        resolved = validate_success(api.resolve_recon_break(
            brk["id"],
            {"resolution": "RESOLVED",
             "resolution_note": "custodian acknowledged fee reclass"},
            OPS))
        assert resolved["status"] == "RESOLVED"
        completed = validate_success(api.complete_event(event["id"], OPS))
        assert completed["status"] == "COMPLETED"
