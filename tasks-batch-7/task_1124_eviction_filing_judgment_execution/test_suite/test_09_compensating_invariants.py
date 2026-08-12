"""Compensating-action invariants: judgment ledger conservation and deputy
slot conservation (PRD 3.8, 3.7)."""
from test_helpers import (
    ApiErrorId,
    create_collection_entry_payload,
    get_case,
    get_collection_entry,
    get_judgment,
    get_writ,
    make_deputy_headers,
    make_landlord_headers,
    request_and_issue_writ,
    setup_judgment_entered,
    setup_judgment_final,
    validate_error,
    validate_success,
)
from test_helpers import api_client


class TestJudgmentLedgerConservation:
    """Depth instance: money is conserved across PAYMENT + REVERSAL +
    WRITE_OFF."""

    def test_payment_reversal_write_off_conserve_total(self, api):
        """PRD 3.8: "The outstanding balance itself is the total award minus
        the sum of payment amounts, plus the sum of reversal amounts, minus
        the sum of write-off amounts, taken over the judgment's entries that
        have not been reversed."

        Design: Difficulty/compensating_invariant/judgment_ledger_conservation
        """
        ctx = setup_judgment_entered(
            "CA", rent_awarded_cents=100000, damages_cents=5000,
            late_fee_cents=2000, court_costs_cents=1000,
            oldest_unpaid_due_date="2026-06-20",
        )
        judgment = ctx["judgment"]
        assert judgment["total_awarded_cents"] == 108000
        assert judgment["outstanding_balance_cents"] == 108000
        ll = make_landlord_headers(ctx["landlord"]["id"])
        jid = judgment["id"]

        pay = validate_success(api.create_collection_entry(
            jid, create_collection_entry_payload("PAYMENT", 50000), ll), 201)
        assert pay["resulting_outstanding_cents"] == 58000

        rev = validate_success(api.create_collection_entry(
            jid,
            create_collection_entry_payload(
                "REVERSAL", 50000, reversal_of_id=pay["id"]), ll), 201)
        assert rev["resulting_outstanding_cents"] == 108000

        wo = validate_success(api.create_collection_entry(
            jid, create_collection_entry_payload("WRITE_OFF", 8000), ll), 201)
        assert wo["resulting_outstanding_cents"] == 100000

        # The reversal links back onto the original payment.
        assert get_collection_entry(pay["id"])["reversed_by_id"] == rev["id"]

        final = get_judgment(jid)
        assert final["outstanding_balance_cents"] == 100000
        # Conservation: 100000 + (50000 - 50000) + 8000 == 108000.
        assert final["outstanding_balance_cents"] + (50000 - 50000) + 8000 == \
            final["total_awarded_cents"]
        assert final["status"] == "ENTERED"

    def test_waterfall_allocation_records_five_buckets(self, api):
        """PRD 3.8: "A PAYMENT allocates across five buckets in a fixed
        priority order — court costs first, then late fees, then damages,
        then interest, then rent ... the five applied amounts are recorded
        on the entry as its allocation object."

        Design: Difficulty/compensating_invariant/judgment_ledger_conservation
        """
        ctx = setup_judgment_entered(
            "CA", rent_awarded_cents=100000, damages_cents=5000,
            late_fee_cents=2000, court_costs_cents=1000,
            oldest_unpaid_due_date="2026-06-20",
        )
        ll = make_landlord_headers(ctx["landlord"]["id"])
        pay = validate_success(api.create_collection_entry(
            ctx["judgment"]["id"],
            create_collection_entry_payload("PAYMENT", 50000), ll), 201)
        # Waterfall: costs 1000, late 2000, damages 5000, interest 0,
        # rent 42000.
        assert pay["allocation"] == {
            "court_costs": 1000, "late_fees": 2000, "damages": 5000,
            "interest": 0, "rent": 42000,
        }
        assert pay["resulting_outstanding_cents"] == 58000


class TestDeputySlotConservation:
    """Depth instance: cancel frees the deputy day-slot; schedule + cancel +
    three fresh schedules land exactly 3 (a leaked slot would reject the
    third)."""

    def _three_issued_writs(self, api):
        ctxs = [setup_judgment_final("CA") for _ in range(3)]
        for ctx in ctxs:
            ctx["writ"] = request_and_issue_writ(ctx)
        return ctxs

    def test_cancel_frees_slot_no_leak(self, api):
        """PRD 3.7: "Cancellation unwinds cleanly ... returning the writ to
        ISSUED, clearing its deputy_id, window_start, and window_end, freeing
        the deputy's day-slot, and returning the case to WRIT_ISSUED."

        Design: Difficulty/compensating_invariant/deputy_slot_conservation
        """
        ctxs = self._three_issued_writs(api)
        dep = make_deputy_headers("dep-y")
        payload = lambda start, end: {"deputy_id": "dep-y",
                                      "window_start": start, "window_end": end}

        w1 = validate_success(api.schedule_lockout(
            ctxs[0]["writ"]["id"],
            payload("2026-06-26T09:00:00Z", "2026-06-26T10:00:00Z"), dep), 200)
        assert w1["status"] == "SCHEDULED"

        cancelled = validate_success(api.cancel_lockout(
            ctxs[0]["writ"]["id"], {"reason": "tenant vacated voluntarily"},
            dep), 200)
        assert cancelled["status"] == "ISSUED"

        # Re-schedule w1 plus w2, w3: the day load must return to exactly 3.
        s1b = validate_success(api.schedule_lockout(
            ctxs[0]["writ"]["id"],
            payload("2026-06-26T09:00:00Z", "2026-06-26T10:00:00Z"), dep), 200)
        s2 = validate_success(api.schedule_lockout(
            ctxs[1]["writ"]["id"],
            payload("2026-06-26T10:00:00Z", "2026-06-26T11:00:00Z"), dep), 200)
        s3 = validate_success(api.schedule_lockout(
            ctxs[2]["writ"]["id"],
            payload("2026-06-26T11:00:00Z", "2026-06-26T12:00:00Z"), dep), 200)
        assert [s1b["status"], s2["status"], s3["status"]] == \
            ["SCHEDULED", "SCHEDULED", "SCHEDULED"]

    def test_cancel_clears_window_fields_and_reverts_case(self, api):
        """PRD 3.7: "returning the writ to ISSUED, clearing its deputy_id,
        window_start, and window_end, freeing the deputy's day-slot, and
        returning the case to WRIT_ISSUED."

        Design: Difficulty/compensating_invariant/deputy_slot_conservation
        """
        ctxs = self._three_issued_writs(api)
        ctx = ctxs[0]
        dep = make_deputy_headers("dep-y")
        validate_success(api.schedule_lockout(
            ctx["writ"]["id"],
            {"deputy_id": "dep-y",
             "window_start": "2026-06-26T09:00:00Z",
             "window_end": "2026-06-26T10:00:00Z"}, dep), 200)
        cancelled = validate_success(api.cancel_lockout(
            ctx["writ"]["id"], {"reason": "mistake"}, dep), 200)
        assert cancelled["status"] == "ISSUED"
        assert cancelled["deputy_id"] is None
        assert cancelled["window_start"] is None
        assert cancelled["window_end"] is None
        assert get_case(ctx["case"]["id"])["status"] == "WRIT_ISSUED"
