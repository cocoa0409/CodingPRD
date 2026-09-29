"""Two conserved quantities and the compensating transactions that preserve them.

Issuer dividend cash is conserved across execution and reversal: reserve plus paid
never changes, and holder credits always add up to what the issuer reports as paid.
Meeting-slot headcount is conserved across the allocation run, a release with its
waitlist promotion, and event completion: the request ledger always equals the sum
of the four status counters plus the requests still pending.
"""

from test_helpers import (
    ApiClient,
    IR_ADMIN,
    TRANSFER_AGENT,
    TRANSFER_AGENT_USER_ID,
    assertions,
    fixtures,
    validate_success,
)

CLOCK_START = "2026-08-01T00:00:00Z"
CLOCK_PAYABLE = "2026-08-25T00:00:00Z"
CLOCK_REVERSAL = "2026-08-27T00:00:00Z"
REVERSAL_REASON = "Transfer agent reported an incorrect record-date file."


def _build_acknowledged_reversible_dividend(api: ApiClient):
    """Three holders (333/667/1000 shares) and an ACKNOWLEDGED 0.4567c dividend."""
    fixtures.set_clock(api, CLOCK_START)
    company = fixtures.create_company(
        api,
        ticker="REV",
        legal_name="Reversal Invariant Corp",
        shares_outstanding=1000000,
        dividend_reserve_cents=100000,
    )
    holders = [
        fixtures.create_holder(
            api,
            company["id"],
            333,
            display_name="Rev Holder One",
            email="rv1@funds.test",
        ),
        fixtures.create_holder(
            api,
            company["id"],
            667,
            display_name="Rev Holder Two",
            email="rv2@funds.test",
        ),
        fixtures.create_holder(
            api,
            company["id"],
            1000,
            display_name="Rev Holder Three",
            email="rv3@retail.test",
            contact_type="RETAIL_HOLDER",
        ),
    ]
    instruction = fixtures.submit_dividend(
        api,
        company["id"],
        record_date="2026-08-15",
        payable_date="2026-08-25",
        declared_rate_cents_per_share=0.4567,
        funding_mode="DECLARED_RATE",
    )
    fixtures.set_clock(api, CLOCK_PAYABLE)
    acknowledged = fixtures.acknowledge_instruction(
        api, instruction["id"], headers=TRANSFER_AGENT
    )
    assertions.assert_instruction(
        acknowledged,
        status="ACKNOWLEDGED",
        snapshot_holder_count=3,
        snapshot_shares_total=2000,
    )
    return company, holders, acknowledged


def _expected_ledger_rows(holders):
    return [
        {"contact_id": holders[0]["id"], "shares_held": 333, "amount_cents": 152},
        {"contact_id": holders[1]["id"], "shares_held": 667, "amount_cents": 305},
        {"contact_id": holders[2]["id"], "shares_held": 1000, "amount_cents": 457},
    ]


class TestDividendCashConservation:
    """Conserved quantity 1: the issuer's dividend cash and the holders' credits."""

    def test_execution_credits_each_holder_and_conserves_issuer_cash(
        self, api: ApiClient
    ):
        """Round-then-sum gives 152 + 305 + 457 = 914 and only moves cash between accounts.

        PRD §3.9: "For each payee, the amount is that payee's `shares_held` multiplied by
        the effective rate and rounded half up to whole cents."
        PRD §3.9: "This rounding order is pinned and it matters: every holder's amount is
        rounded to whole cents **first** and the rounded amounts are added afterwards."
        PRD §3.9: "It then moves the money: the issuer's `dividend_reserve_cents` decreases
        by `total_payout_cents` while its `dividend_paid_cents` increases by the same figure,
        with the issuer's `version` incremented by 1."
        PRD §3.9: "First, the total of `dividend_reserve_cents` plus `dividend_paid_cents` is
        identical before execution, after execution and after reversal — cash is only ever
        moved between the two accounts, never created or destroyed."
        PRD §3.9: "Second, the sum of `dividend_received_cents` across the issuer's contacts
        always equals the issuer's `dividend_paid_cents`."

        Design: Difficulty/compensating_invariant/dividend_reversal_restores_reserve_paid_and_holder_totals
        """
        company, holders, acknowledged = _build_acknowledged_reversible_dividend(api)
        before = fixtures.read_company(api, company["id"])
        assertions.assert_company(
            before, dividend_reserve_cents=100000, dividend_paid_cents=0
        )

        executed = validate_success(
            api.execute_instruction(acknowledged["id"], TRANSFER_AGENT)
        )
        assertions.assert_instruction(
            executed,
            status="EXECUTED",
            total_payout_cents=914,
            executed_by_user_id=TRANSFER_AGENT_USER_ID,
        )
        assertions.assert_ts_equals(executed["executed_at"], CLOCK_PAYABLE, "executed_at")
        assertions.assert_payout_ledger(executed, _expected_ledger_rows(holders))

        after = fixtures.read_company(api, company["id"])
        assertions.assert_company(
            after, dividend_reserve_cents=99086, dividend_paid_cents=914
        )
        assertions.assert_reserve_plus_paid_unchanged(before, after)
        assertions.assert_version(after, before["version"] + 1, "Company")

        credited = [fixtures.read_contact(api, holder["id"]) for holder in holders]
        for holder, contact, amount in zip(holders, credited, (152, 305, 457)):
            assertions.assert_contact(contact, dividend_received_cents=amount)
            assertions.assert_version(contact, holder["version"] + 1, "Contact")
        assertions.assert_holder_credits_match_paid(after, credited)

    def test_reversal_restores_the_reserve_paid_split_and_every_holder_total(
        self, api: ApiClient
    ):
        """Replaying the stored ledger backwards returns every balance to its opening value.

        PRD §3.9: "Reversal is a compensating transaction, not a recomputation: it replays
        the **stored** `payout_ledger` backwards."
        PRD §3.9: "The issuer's `dividend_reserve_cents` increases by `total_payout_cents`
        while `dividend_paid_cents` decreases by the same figure, with the issuer's `version`
        incremented by 1, and each ledger row debits that holder's `dividend_received_cents`
        by the row's `amount_cents` with that contact's `version` incremented by 1."
        PRD §3.9: "Both `payout_ledger` and `total_payout_cents` are retained on the reversed
        instruction for audit rather than being cleared."
        PRD §3.9: "First, the total of `dividend_reserve_cents` plus `dividend_paid_cents` is
        identical before execution, after execution and after reversal — cash is only ever
        moved between the two accounts, never created or destroyed."

        Design: Difficulty/compensating_invariant/dividend_reversal_restores_reserve_paid_and_holder_totals
        """
        company, holders, acknowledged = _build_acknowledged_reversible_dividend(api)
        before = fixtures.read_company(api, company["id"])

        fixtures.execute_instruction(api, acknowledged["id"], TRANSFER_AGENT)
        midway = fixtures.read_company(api, company["id"])
        assertions.assert_reserve_plus_paid_unchanged(before, midway)

        fixtures.set_clock(api, CLOCK_REVERSAL)
        reversed_instruction = validate_success(
            api.reverse_instruction(acknowledged["id"], REVERSAL_REASON, TRANSFER_AGENT)
        )
        assertions.assert_instruction(
            reversed_instruction,
            status="REVERSED",
            decision_reason=REVERSAL_REASON,
            total_payout_cents=914,
        )
        assertions.assert_payout_ledger(
            reversed_instruction, _expected_ledger_rows(holders)
        )

        after = fixtures.read_company(api, company["id"])
        assertions.assert_company(
            after, dividend_reserve_cents=100000, dividend_paid_cents=0
        )
        assertions.assert_reserve_plus_paid_unchanged(before, after)
        assertions.assert_reserve_plus_paid_unchanged(midway, after)
        assertions.assert_version(after, midway["version"] + 1, "Company")

        debited = [fixtures.read_contact(api, holder["id"]) for holder in holders]
        for holder, contact in zip(holders, debited):
            assertions.assert_contact(contact, dividend_received_cents=0)
            assertions.assert_version(contact, holder["version"] + 2, "Contact")
        assertions.assert_holder_credits_match_paid(after, debited)


def _build_locked_capacity_of_one(api: ApiClient):
    """One-slot event carrying three scored requests: 99.60, 67.20 and 32.40."""
    fixtures.set_clock(api, CLOCK_START)
    company = fixtures.create_company(
        api,
        ticker="LDG",
        legal_name="Ledger Conservation Corp",
        shares_outstanding=1000000,
    )
    top = fixtures.create_holder(
        api,
        company["id"],
        120000,
        display_name="Ledger Holder One",
        email="ldg1@funds.test",
        nda_on_file=True,
    )
    middle = fixtures.create_holder(
        api,
        company["id"],
        20000,
        display_name="Ledger Holder Two",
        email="ldg2@funds.test",
        nda_on_file=True,
    )
    bottom = fixtures.create_holder(
        api,
        company["id"],
        5000,
        display_name="Ledger Holder Three",
        email="ldg3@funds.test",
    )
    event = fixtures.open_event(
        api,
        company["id"],
        event_type="NDR",
        venue_city="Boston",
        window_start="2026-09-01T13:00:00Z",
        window_end="2026-09-01T18:00:00Z",
        slot_minutes=30,
        capacity_slots=1,
    )
    requests = [
        fixtures.create_meeting_request(
            api,
            event["id"],
            top["id"],
            requested_slot_start="2026-09-01T13:00:00Z",
            requested_slot_end="2026-09-01T13:30:00Z",
        ),
        fixtures.create_meeting_request(
            api,
            event["id"],
            middle["id"],
            requested_slot_start="2026-09-01T14:00:00Z",
            requested_slot_end="2026-09-01T14:30:00Z",
        ),
        fixtures.create_meeting_request(
            api,
            event["id"],
            bottom["id"],
            requested_slot_start="2026-09-01T15:00:00Z",
            requested_slot_end="2026-09-01T15:30:00Z",
        ),
    ]
    assertions.assert_roadshow_event(
        fixtures.read_event(api, event["id"]), request_ledger_total=3
    )
    return company, [top, middle, bottom], event, requests


class TestEventRequestLedgerConservation:
    """Conserved quantity 2: the roadshow event's request ledger."""

    def test_allocation_run_splits_three_requests_into_one_slot_and_two_waitlisted(
        self, api: ApiClient
    ):
        """Capacity of one allocates 99.60 and waitlists 67.20 and 32.40, ledger still 3.

        PRD §3.8: "The eligible candidates are ranked by `final_priority_score`
        descending, then — for equal scores — by the requesting contact's `shares_held`
        descending, then by the request's own creation timestamp ascending, compared at
        millisecond precision."
        PRD §3.8: "Remaining capacity is the event's `capacity_slots` minus its current
        `allocated_count`, and the first that many rows of the ranked eligible list
        transition `REQUESTED` → `ALLOCATED`. Every other eligible row, and every
        threshold-deferred row, transitions `REQUESTED` → `WAITLISTED`."
        PRD §3.8: "The run finishes by recomputing the event's counters, setting `status`
        to `LOCKED` and incrementing the event's `version` by 1, and it reports back
        `event_id`, the resulting `event_status`, the `evaluated_count` of candidates it
        scored, the resulting `allocated_count` and `waitlisted_count`, and a
        `threshold_deferred_count` that isolates the requests waitlisted because their
        score fell below 25 rather than because capacity ran out."
        PRD §3.8: "`request_ledger_total` always equals the sum of those four counters
        plus the number of the event's requests still in `REQUESTED`."

        Design: Difficulty/compensating_invariant/event_request_ledger_conserved_across_release_and_complete
        """
        company, holders, event, requests = _build_locked_capacity_of_one(api)

        summary = validate_success(api.allocate_event(event["id"], IR_ADMIN))
        assertions.assert_allocation_summary(
            summary,
            event_id=event["id"],
            event_status="LOCKED",
            evaluated_count=3,
            allocated_count=1,
            waitlisted_count=2,
            threshold_deferred_count=0,
        )

        winner = fixtures.read_meeting_request(api, requests[0]["id"])
        assertions.assert_meeting_request(
            winner, status="ALLOCATED", promoted_from_waitlist=False
        )
        assert winner["final_priority_score"] == assertions.approx_2dp(99.60)
        assertions.assert_ts_equals(winner["allocated_at"], CLOCK_START, "allocated_at")

        runner_up = fixtures.read_meeting_request(api, requests[1]["id"])
        assertions.assert_meeting_request(
            runner_up, status="WAITLISTED", allocated_at=None
        )
        assert runner_up["final_priority_score"] == assertions.approx_2dp(67.20)

        last = fixtures.read_meeting_request(api, requests[2]["id"])
        assertions.assert_meeting_request(last, status="WAITLISTED", allocated_at=None)
        assert last["final_priority_score"] == assertions.approx_2dp(32.40)

        locked = fixtures.read_event(api, event["id"])
        assertions.assert_roadshow_event(
            locked,
            status="LOCKED",
            allocated_count=1,
            waitlisted_count=2,
            released_count=0,
            declined_count=0,
            request_ledger_total=3,
        )
        assertions.assert_request_ledger_conserved(locked, still_requested=0)

    def test_release_promotes_the_waitlist_without_changing_the_ledger_total(
        self, api: ApiClient
    ):
        """One slot leaves ALLOCATED and one enters it, so the total stays at 3.

        PRD §3.8: "The second link, caused by the first, decreases the event's
        `allocated_count` by 1, increases its `released_count` by 1, and increments the
        event's `version` by 1 — a slot is now free."
        PRD §3.8: "the promotion selector picks the single highest-ranked row using the
        same ordering as the run — `final_priority_score` descending, then the contact's
        `shares_held` descending, then creation timestamp ascending — and transitions it
        `WAITLISTED` → `ALLOCATED` with `promoted_from_waitlist` set to true and
        `allocated_at` stamped from the logical clock, then increases the event's
        `allocated_count` by 1 and decreases its `waitlisted_count` by 1."
        PRD §3.8: "`request_ledger_total` is the count of every meeting request ever
        created against the event and is monotonic: it never decreases."
        PRD §3.8: "Separately, `allocated_count` never exceeds `capacity_slots` at any
        point in time."

        Design: Difficulty/compensating_invariant/event_request_ledger_conserved_across_release_and_complete
        """
        company, holders, event, requests = _build_locked_capacity_of_one(api)
        fixtures.allocate_event(api, event["id"])

        released = validate_success(
            api.release_meeting_request(
                requests[0]["id"], "The holder cancelled the trip.", IR_ADMIN
            )
        )
        assertions.assert_meeting_request(
            released,
            status="RELEASED",
            release_reason="The holder cancelled the trip.",
        )

        promoted = fixtures.read_meeting_request(api, requests[1]["id"])
        assertions.assert_meeting_request(
            promoted, status="ALLOCATED", promoted_from_waitlist=True
        )
        assertions.assert_ts_equals(
            promoted["allocated_at"], CLOCK_START, "allocated_at"
        )
        assertions.assert_meeting_request(
            fixtures.read_meeting_request(api, requests[2]["id"]), status="WAITLISTED"
        )

        after = fixtures.read_event(api, event["id"])
        assertions.assert_roadshow_event(
            after,
            status="LOCKED",
            allocated_count=1,
            waitlisted_count=1,
            released_count=1,
            declined_count=0,
            request_ledger_total=3,
        )
        assertions.assert_request_ledger_conserved(after, still_requested=0)
        assert after["allocated_count"] <= after["capacity_slots"]

    def test_completion_declines_the_remaining_waitlist_and_conserves_the_ledger(
        self, api: ApiClient
    ):
        """The waitlist empties into declined_count and the total is still 3.

        PRD §3.8: "The second link, caused by the first, transitions every one of that
        event's requests still in `WAITLISTED` to `DECLINED`, incrementing each of those
        requests' `version` by 1. The third link, caused by the second, sets the event's
        `waitlisted_count` to zero and increases its `declined_count` by exactly the
        number of requests declined in the second link."
        PRD §3.8: "Across all four of those operations — request creation, the allocation
        run, release and completion — the event's ledger obeys one conserved identity."
        PRD §3.8: "`allocated_count`, `waitlisted_count`, `released_count` and
        `declined_count` are the counts of that event's requests in the corresponding
        statuses, and `request_ledger_total` always equals the sum of those four counters
        plus the number of the event's requests still in `REQUESTED`."

        Design: Difficulty/compensating_invariant/event_request_ledger_conserved_across_release_and_complete
        """
        company, holders, event, requests = _build_locked_capacity_of_one(api)
        fixtures.allocate_event(api, event["id"])
        fixtures.release_request(
            api, requests[0]["id"], reason="The holder cancelled the trip."
        )

        completed = validate_success(api.complete_event(event["id"], IR_ADMIN))
        assertions.assert_roadshow_event(
            completed,
            status="COMPLETED",
            allocated_count=1,
            waitlisted_count=0,
            released_count=1,
            declined_count=1,
            request_ledger_total=3,
        )
        assertions.assert_request_ledger_conserved(completed, still_requested=0)

        assertions.assert_meeting_request(
            fixtures.read_meeting_request(api, requests[0]["id"]), status="RELEASED"
        )
        assertions.assert_meeting_request(
            fixtures.read_meeting_request(api, requests[1]["id"]), status="ALLOCATED"
        )
        assertions.assert_meeting_request(
            fixtures.read_meeting_request(api, requests[2]["id"]), status="DECLINED"
        )
