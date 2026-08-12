"""Cyclic state machines (PRD §3.4, §3.5): event amend->reconfirm cycle and
election withdraw->resubmit cycle.
"""
from test_helpers import (
    validate_success, get_success_data,
    make_security, make_account, make_lot, set_clock,
    make_confirmed_event, make_merger_event_confirmed,
    make_account_holder_headers, split_terms, get_event_version,
    get_entitlement_for,
)
from test_helpers.fixtures import OPS, ANALYST_1, ANALYST_2
from test_helpers import api_client


class TestEventAmendmentReconfirmationCycle:
    def _setup(self):
        sec = make_security(ticker="ACME")
        acct = make_account(account_number="A-1", holder_name="One")
        make_lot(acct["id"], sec["id"], quantity=100,
                 acquisition_date="2026-04-01", cost_basis_total_cents=500000)
        event, _, _ = make_confirmed_event(sec["id"], "SPLIT", split_terms())
        return sec, acct, event

    def test_amendment_supersedes_and_reprojects_entitlements(self, api):
        """PRD §3.4: "The amendment also re-projects the world: every `PROJECTED` or `FIRM` entitlement of the event moves to `SUPERSEDED`, and for each superseded entitlement a replacement `PROJECTED` entitlement is created, recomputed on the new terms under `TRADE_DATE_BASIS` and linked to its predecessor through `supersedes_entitlement_id`."

        Design: Difficulty/non_linear_state_machine/event_amendment_reconfirmation_cycle
        """
        _, acct, event = self._setup()
        e1 = get_entitlement_for(event["id"], acct["id"])
        assert e1["entitled_shares"] == 200  # 100 x 2
        amendment = validate_success(api.amend_event(
            event["id"],
            {"amended_terms": split_terms(ratio_num=3),
             "reason": "issuer revised ratio",
             "expected_event_version": event["version"]},
            ANALYST_1), 201)
        assert amendment["amendment_seq"] == 1
        old = get_success_data(api.get_entitlement(e1["id"], OPS))
        assert old["status"] == "SUPERSEDED"
        resp = api.list_entitlements(
            OPS, params={"supersedes_entitlement_id": e1["id"]})
        replacements = resp.json()["data"]
        assert len(replacements) == 1
        e2 = replacements[0]
        assert e2["supersedes_entitlement_id"] == e1["id"]
        assert e2["entitled_shares"] == 300  # 100 x 3
        assert e2["status"] == "PROJECTED"

    def test_amended_event_reconfirms_without_duplicating_entitlements(self, api):
        """PRD §3.4: "An `AMENDED` event is confirmed again through the same confirmation path — `AMENDED` → `CONFIRMED`, with the same segregation-of-duties rule — but this second confirmation generates no entitlements, because the amendment already re-projected them; confirm does not duplicate them."

        Design: Difficulty/non_linear_state_machine/event_amendment_reconfirmation_cycle
        """
        _, acct, event = self._setup()
        validate_success(api.amend_event(
            event["id"],
            {"amended_terms": split_terms(ratio_num=3),
             "reason": "issuer revised ratio",
             "expected_event_version": event["version"]},
            ANALYST_1), 201)
        reconfirmed = validate_success(api.confirm_event(event["id"], ANALYST_2))
        assert reconfirmed["status"] == "CONFIRMED"
        resp = api.list_entitlements(
            OPS, params={"event_id": event["id"], "status": "PROJECTED"})
        assert resp.json()["meta"]["total_count"] == 1


class TestElectionWithdrawResubmitCycle:
    def test_withdraw_then_resubmit_increments_seq_and_event_version(self, api):
        """PRD §3.5: "The holder may withdraw a live election (`SUBMITTED` → `WITHDRAWN`) and later resubmit it (`WITHDRAWN` → `SUBMITTED`); resubmission refreshes `submitted_at`, increments `election_seq`, and supersedes any other `SUBMITTED` election the account has on the event." and "Every submission, withdrawal, and resubmission increments the hosting event's `version` by one".

        Design: Difficulty/non_linear_state_machine/election_withdraw_resubmit_cycle
        """
        ctx = make_merger_event_confirmed(account_shares=120)
        event, acct = ctx["event"], ctx["account"]
        set_clock("2026-05-15T00:00:00Z")
        v_after_confirm = event["version"]
        headers = make_account_holder_headers(acct["id"])
        election = validate_success(api.submit_election(
            event["id"],
            {"account_id": acct["id"], "option_code": "CASH",
             "expected_event_version": v_after_confirm},
            headers), 201)
        assert election["status"] == "SUBMITTED"
        assert election["election_seq"] == 1
        withdrawn = validate_success(api.withdraw_election(election["id"], headers))
        assert withdrawn["status"] == "WITHDRAWN"
        resubmitted = validate_success(api.resubmit_election(election["id"], headers))
        assert resubmitted["status"] == "SUBMITTED"
        assert resubmitted["election_seq"] == 2
        # create(1) -> confirm(2) -> submit(3) -> withdraw(4) -> resubmit(5)
        assert get_event_version(event["id"]) == v_after_confirm + 3

    def test_resubmit_supersedes_other_live_election(self, api):
        """PRD §3.5: "Submission is also replacement: any other `SUBMITTED` election by the same account on the same event moves to `SUPERSEDED`."

        Design: Difficulty/non_linear_state_machine/election_withdraw_resubmit_cycle
        """
        ctx = make_merger_event_confirmed(account_shares=120)
        event, acct = ctx["event"], ctx["account"]
        set_clock("2026-05-15T00:00:00Z")
        headers = make_account_holder_headers(acct["id"])
        e1 = validate_success(api.submit_election(
            event["id"],
            {"account_id": acct["id"], "option_code": "CASH",
             "expected_event_version": get_event_version(event["id"])},
            headers), 201)
        validate_success(api.withdraw_election(e1["id"], headers))
        e2 = validate_success(api.submit_election(
            event["id"],
            {"account_id": acct["id"], "option_code": "STOCK",
             "expected_event_version": get_event_version(event["id"])},
            headers), 201)
        validate_success(api.resubmit_election(e1["id"], headers))
        e2_after = get_success_data(api.get_election(e2["id"], OPS))
        assert e2_after["status"] == "SUPERSEDED"
        e1_after = get_success_data(api.get_election(e1["id"], OPS))
        assert e1_after["status"] == "SUBMITTED"
